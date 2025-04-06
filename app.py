import os
import time
import json
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_socketio import SocketIO, emit
from werkzeug.security import check_password_hash, generate_password_hash
import threading

# --- Lade/Speichere Benutzerdaten ---
USERS_FILE = "users.json"
loaded_users = {}
# (load_users_from_json und save_users_to_json bleiben unverändert)
def load_users_from_json():
    global loaded_users
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        users_file_path = os.path.join(base_dir, USERS_FILE)
        if not os.path.exists(users_file_path):
            with open(users_file_path, 'w', encoding='utf-8') as f:
                initial_admin_user = "jaron"; initial_admin_pass = "admin123"
                initial_users = { initial_admin_user: { "password": generate_password_hash(initial_admin_pass), "is_admin": True } }
                json.dump(initial_users, f, indent=2)
            print(f"{USERS_FILE} nicht gefunden, Datei mit initialem Admin '{initial_admin_user}' erstellt.")
            loaded_users = initial_users; return
        with open(users_file_path, 'r', encoding='utf-8') as f: loaded_users = json.load(f)
        print(f"Benutzerdaten erfolgreich aus {USERS_FILE} geladen.")
    except Exception as e: print(f"FEHLER beim Laden von {USERS_FILE}: {e}"); loaded_users = {}

def save_users_to_json():
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        users_file_path = os.path.join(base_dir, USERS_FILE)
        with open(users_file_path, 'w', encoding='utf-8') as f: json.dump(loaded_users, f, indent=2)
        print(f"Benutzerdaten erfolgreich in {USERS_FILE} gespeichert."); return True
    except Exception as e: print(f"FEHLER: Konnte Benutzerdaten nicht in {USERS_FILE} speichern: {e}"); return False

load_users_from_json()

# --- Konfiguration ---
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "sehr-geheim-fuer-spiel-mit-invis-v2")
socketio = SocketIO(app, async_mode="eventlet")

# --- Konstanten ---
MRX_DISCONNECT_GRACE_PERIOD_SECONDS = 60
DEFAULT_DECOYS = 1
DEFAULT_INVISIBILITY_USES = 2
DEFAULT_INVISIBILITY_DURATION_SECONDS = 30

# --- Globaler Spielstatus ---
game_state = {
    "active": False, "mr_x": None, "update_interval_minutes": 5, "mr_x_last_broadcast_time": 0,
    "mr_x_last_known_location": None, "players": {}, "mrx_disconnect_task_pending": False,
    "mrx_total_decoys": DEFAULT_DECOYS, "mrx_remaining_decoys": DEFAULT_DECOYS,
    "mrx_pending_decoy_location": None, "mrx_last_update_was_decoy": False,
    "seeker_invisibility_uses": DEFAULT_INVISIBILITY_USES,
    "seeker_invisibility_duration_seconds": DEFAULT_INVISIBILITY_DURATION_SECONDS
}

# --- Hilfsfunktionen & Decorator ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session: flash("Bitte zuerst einloggen.", "warning"); return redirect(url_for('login'))
        username = session['username']
        user_data = loaded_users.get(username)
        if not user_data or not user_data.get('is_admin', False): flash("Zugriff verweigert. Nur Administratoren erlaubt.", "danger"); return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def end_game_due_to_mrx_disconnect():
    if game_state["mrx_disconnect_task_pending"] and game_state["active"]:
        print(f"Grace period for Mr. X ({game_state['mr_x']}) expired. Ending game.")
        if game_state['mr_x'] not in game_state['players']: reset_game_state()
        else: print(f"Mr. X ({game_state['mr_x']}) reconnected just before grace period ended. Game continues.")
    game_state["mrx_disconnect_task_pending"] = False

def reset_game_state(notify_clients=True):
    if game_state["mrx_disconnect_task_pending"]:
        print("Cancelling pending Mr. X disconnect task due to game reset.")
        game_state["mrx_disconnect_task_pending"] = False
    print("Resetting game state.")
    game_state["active"] = False; game_state["mr_x"] = None; game_state["update_interval_minutes"] = 5
    game_state["mr_x_last_broadcast_time"] = 0; game_state["mr_x_last_known_location"] = None
    game_state["players"] = {}; game_state["mrx_total_decoys"] = DEFAULT_DECOYS
    game_state["mrx_remaining_decoys"] = DEFAULT_DECOYS; game_state["mrx_pending_decoy_location"] = None
    game_state["mrx_last_update_was_decoy"] = False
    game_state["seeker_invisibility_uses"] = DEFAULT_INVISIBILITY_USES
    game_state["seeker_invisibility_duration_seconds"] = DEFAULT_INVISIBILITY_DURATION_SECONDS
    if notify_clients:
        print("Notifying clients about game reset.")
        socketio.emit('game_over', {'message': 'Das Spiel wurde beendet oder zurückgesetzt.', 'finder': None})
    else: print("Game reset without notifying clients (notification already sent).")

# --- Routen ---
@app.route("/")
def index():
    if not session.get("username"): return redirect(url_for("login"))
    if game_state["active"]: return redirect(url_for("map_page"))
    else:
        registered_users = list(loaded_users.keys())
        is_admin = loaded_users.get(session['username'], {}).get('is_admin', False)
        return render_template("start.html", registered_users=registered_users, is_admin=is_admin,
                               default_decoys=DEFAULT_DECOYS, default_invisibility_uses=DEFAULT_INVISIBILITY_USES,
                               default_invisibility_duration=DEFAULT_INVISIBILITY_DURATION_SECONDS)

@app.route("/start_game", methods=["POST"])
@admin_required
def start_game():
    if game_state["active"]: flash("Ein Spiel läuft bereits!", "warning"); return redirect(url_for("map_page"))
    selected_mr_x = request.form.get("mr_x")
    interval_str = request.form.get("interval", "5")
    num_decoys_str = request.form.get("num_decoys", str(DEFAULT_DECOYS))
    num_invisibility_str = request.form.get("num_invisibility", str(DEFAULT_INVISIBILITY_USES))
    invisibility_duration_str = request.form.get("invisibility_duration", str(DEFAULT_INVISIBILITY_DURATION_SECONDS))
    if not selected_mr_x or selected_mr_x not in loaded_users: flash("Bitte wähle einen gültigen Spieler als Mr. X aus.", "error"); return redirect(url_for("index"))
    try:
        interval_minutes = int(interval_str); num_decoys = int(num_decoys_str)
        num_invisibility = int(num_invisibility_str); invisibility_duration = int(invisibility_duration_str)
        if interval_minutes <= 0 or num_decoys < 0 or num_invisibility < 0 or invisibility_duration <= 0: raise ValueError("Invalid game settings")
    except ValueError: flash("Bitte gib gültige Zahlen für Intervall, Ablenkungsmanöver und Unsichtbarkeit an.", "error"); return redirect(url_for("index"))
    game_state["active"] = True; game_state["mr_x"] = selected_mr_x; game_state["update_interval_minutes"] = interval_minutes
    game_state["mr_x_last_broadcast_time"] = 0; game_state["mr_x_last_known_location"] = None; game_state["players"] = {}
    game_state["mrx_disconnect_task_pending"] = False; game_state["mrx_total_decoys"] = num_decoys
    game_state["mrx_remaining_decoys"] = num_decoys; game_state["mrx_pending_decoy_location"] = None
    game_state["mrx_last_update_was_decoy"] = False; game_state["seeker_invisibility_uses"] = num_invisibility
    game_state["seeker_invisibility_duration_seconds"] = invisibility_duration
    print(f"Spiel gestartet! Mr. X: {selected_mr_x}, Interval: {interval_minutes} min, Decoys: {num_decoys}, Invis Uses: {num_invisibility}, Invis Duration: {invisibility_duration}s")
    flash(f"Spiel gestartet! {selected_mr_x} ist Mr. X.", "success")
    socketio.emit('game_started', { 'mr_x': game_state['mr_x'], 'interval': game_state['update_interval_minutes'],
                                   'num_decoys': num_decoys, 'num_invisibility': num_invisibility,
                                   'invisibility_duration': invisibility_duration })
    return redirect(url_for("map_page"))

@app.route("/login", methods=["GET", "POST"])
def login():
    # (unverändert)
    if request.method == "POST":
        username = request.form.get("username"); password = request.form.get("password")
        user_data = loaded_users.get(username)
        if user_data and check_password_hash(user_data.get("password", ""), password):
            session["username"] = username; print(f"User '{username}' logged in."); return redirect(url_for("index"))
        else: flash("Ungültiger Benutzername oder Passwort", "error"); return redirect(url_for("login"))
    if "username" in session: return redirect(url_for("index"))
    return render_template("login.html")

@app.route("/map")
def map_page():
    # (unverändert)
    if "username" not in session: return redirect(url_for("login"))
    if not game_state["active"]: flash("Derzeit läuft kein Spiel.", "info"); return redirect(url_for("index"))
    is_admin = loaded_users.get(session['username'], {}).get('is_admin', False)
    initial_invis_uses = game_state["seeker_invisibility_uses"]
    return render_template( "map.html", username=session["username"], mr_x_username=game_state["mr_x"],
                           current_players_list=[p for p in game_state["players"] if p != session["username"]],
                           mrx_remaining_decoys=game_state["mrx_remaining_decoys"],
                           seeker_remaining_invisibility=initial_invis_uses, is_admin=is_admin )

@app.route("/logout")
def logout():
    # (unverändert)
    username = session.pop("username", None)
    if username:
        print(f"User '{username}' logged out.")
        if game_state["active"] and username == game_state["mr_x"]:
            print(f"Mr. X ({username}) explicitly logged out. Ending game."); reset_game_state()
    return redirect(url_for("login"))

@app.route('/manage_users', methods=['GET', 'POST'])
@admin_required
def manage_users():
    # (unverändert)
    current_admin_username = session['username']
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            new_username = request.form.get('new_username'); new_password = request.form.get('new_password'); is_new_admin = request.form.get('is_new_admin') == 'on'
            if not new_username or not new_password: flash("Benutzername und Passwort dürfen nicht leer sein.", "error")
            elif new_username in loaded_users: flash(f"Benutzername '{new_username}' existiert bereits.", "error")
            else:
                hashed_password = generate_password_hash(new_password); loaded_users[new_username] = { "password": hashed_password, "is_admin": is_new_admin }
                if save_users_to_json(): flash(f"Benutzer '{new_username}' {'als Admin ' if is_new_admin else ''}erfolgreich hinzugefügt.", "success"); print(f"User added: {new_username} (Admin: {is_new_admin})")
                else: flash("Fehler beim Speichern der Benutzerdaten.", "error"); del loaded_users[new_username]
            return redirect(url_for('manage_users'))
        elif action == 'delete':
            username_to_delete = request.form.get('username_to_delete')
            if not username_to_delete: flash("Kein Benutzer zum Löschen ausgewählt.", "error")
            elif username_to_delete not in loaded_users: flash(f"Benutzer '{username_to_delete}' nicht gefunden.", "error")
            elif username_to_delete == current_admin_username: flash("Du kannst dich nicht selbst löschen.", "error")
            else:
                admin_count = sum(1 for u in loaded_users.values() if u.get('is_admin')); is_deleting_admin = loaded_users[username_to_delete].get('is_admin', False)
                if is_deleting_admin and admin_count <= 1: flash("Der letzte Administrator kann nicht gelöscht werden.", "error")
                else:
                    del loaded_users[username_to_delete]
                    if save_users_to_json(): flash(f"Benutzer '{username_to_delete}' erfolgreich gelöscht.", "success"); print(f"User deleted: {username_to_delete}")
                    else: flash("Fehler beim Speichern nach dem Löschen.", "error"); load_users_from_json()
            return redirect(url_for('manage_users'))
        elif action == 'grant_admin':
            username_to_grant = request.form.get('username_to_modify')
            if not username_to_grant: flash("Kein Benutzer ausgewählt.", "error")
            elif username_to_grant not in loaded_users: flash(f"Benutzer '{username_to_grant}' nicht gefunden.", "error")
            elif loaded_users[username_to_grant].get('is_admin', False): flash(f"Benutzer '{username_to_grant}' ist bereits Admin.", "warning")
            else:
                loaded_users[username_to_grant]['is_admin'] = True
                if save_users_to_json(): flash(f"'{username_to_grant}' wurden Admin-Rechte erteilt.", "success"); print(f"Admin granted: {username_to_grant}")
                else: flash("Fehler beim Speichern der Admin-Rechte.", "error"); loaded_users[username_to_grant]['is_admin'] = False
            return redirect(url_for('manage_users'))
        elif action == 'revoke_admin':
            username_to_revoke = request.form.get('username_to_modify')
            if not username_to_revoke: flash("Kein Benutzer ausgewählt.", "error")
            elif username_to_revoke not in loaded_users: flash(f"Benutzer '{username_to_revoke}' nicht gefunden.", "error")
            elif not loaded_users[username_to_revoke].get('is_admin', False): flash(f"Benutzer '{username_to_revoke}' ist kein Admin.", "warning")
            elif username_to_revoke == current_admin_username: flash("Du kannst dir nicht selbst die Admin-Rechte entziehen.", "error")
            else:
                admin_count = sum(1 for u in loaded_users.values() if u.get('is_admin'))
                if admin_count <= 1: flash("Dem letzten Administrator können die Rechte nicht entzogen werden.", "error")
                else:
                    loaded_users[username_to_revoke]['is_admin'] = False
                    if save_users_to_json(): flash(f"'{username_to_revoke}' wurden die Admin-Rechte entzogen.", "success"); print(f"Admin revoked: {username_to_revoke}")
                    else: flash("Fehler beim Speichern nach Entzug der Admin-Rechte.", "error"); loaded_users[username_to_revoke]['is_admin'] = True
            return redirect(url_for('manage_users'))
    users_list_with_status = []
    for username, data in loaded_users.items():
        if username != current_admin_username: users_list_with_status.append({ 'username': username, 'is_admin': data.get('is_admin', False) })
    return render_template('manage_users.html', users_list=users_list_with_status)

# --- SocketIO Events ---
@socketio.on("connect")
def handle_connect():
    if "username" not in session: return False
    username = session["username"]
    sid = request.sid
    print(f"Client connected: {username} ({sid})")
    if not game_state["active"]: print(f"User {username} connected, but no game active."); return
    print(f"User {username} joined active game.")
    if username == game_state["mr_x"] and game_state["mrx_disconnect_task_pending"]:
        print(f"Mr. X ({username}) reconnected within grace period! Cancelling game end task.")
        game_state["mrx_disconnect_task_pending"] = False

    if username not in game_state["players"]:
         game_state["players"][username] = { "sid": sid, "last_location": None,
                                            "remaining_invisibility": game_state["seeker_invisibility_uses"],
                                            "invisible_until": None }
    else: game_state["players"][username]["sid"] = sid

    current_locations = {}
    for player, data in game_state["players"].items():
        loc = data.get('last_location')
        # Prüfe Unsichtbarkeit für ANDERE Spieler
        is_invisible = data.get('invisible_until') and data['invisible_until'] > time.time()
        if is_invisible and player != username: # Sende keine Position von anderen unsichtbaren Spielern
             continue

        if player != game_state["mr_x"] and loc:
             current_locations[player] = {"lat": loc["lat"], "lon": loc["lon"]}
        elif player == game_state["mr_x"] and game_state["mr_x_last_known_location"]:
             current_locations[player] = { "lat": game_state["mr_x_last_known_location"]["lat"],
                                           "lon": game_state["mr_x_last_known_location"]["lon"] }

    emit("game_update", {
        "mr_x": game_state["mr_x"], "locations": current_locations, "players": list(game_state["players"].keys()),
        "mrx_remaining_decoys": game_state["mrx_remaining_decoys"] if username == game_state["mr_x"] else None,
        "seeker_remaining_invisibility": game_state["players"][username].get("remaining_invisibility", 0) if username != game_state["mr_x"] else None,
        "mrx_update_interval_minutes": game_state["update_interval_minutes"],
        "mrx_last_broadcast_time": game_state["mr_x_last_broadcast_time"]
    })
    # Informiere andere über Beitritt (ohne Standort, da er ggf. unsichtbar ist)
    socketio.emit("player_joined", {"username": username}, room=None, skip_sid=sid)

@socketio.on("disconnect")
def handle_disconnect():
    username = None; sid = request.sid; disconnecting_user = None
    for user, data in game_state["players"].items():
        if data["sid"] == sid: disconnecting_user = user; break
    if disconnecting_user:
        print(f"Client disconnected: {disconnecting_user} ({sid})")
        if game_state["active"]:
            if disconnecting_user == game_state["mr_x"]:
                if not game_state["mrx_disconnect_task_pending"]:
                    print(f"Mr. X ({disconnecting_user}) disconnected. Starting grace period ({MRX_DISCONNECT_GRACE_PERIOD_SECONDS}s)...")
                    game_state["mrx_disconnect_task_pending"] = True
                    socketio.start_background_task( target=end_game_due_to_mrx_disconnect_wrapper, grace_period=MRX_DISCONNECT_GRACE_PERIOD_SECONDS )
                    # Sende player_invisible statt player_left für Mr. X Disconnect
                    socketio.emit("player_invisible", {"username": disconnecting_user})
                else: print(f"Mr. X ({disconnecting_user}) disconnected, but grace period task already pending.")
            else:
                print(f"Player {disconnecting_user} disconnected. Removing.")
                if disconnecting_user in game_state["players"]: del game_state["players"][disconnecting_user]
                # Sende player_left für normale Spieler
                socketio.emit("player_left", {"username": disconnecting_user})
                print(f"Removed {disconnecting_user} from active game.")
    else:
        session_username = session.get('username', 'Unknown User')
        print(f"Client disconnected: {session_username} (SID: {sid}), war nicht in aktivem Spiel registriert.")

def end_game_due_to_mrx_disconnect_wrapper(grace_period):
    print(f"Background task started: Wait {grace_period}s for Mr. X reconnect.")
    socketio.sleep(grace_period)
    print("Background task finished waiting.")
    end_game_due_to_mrx_disconnect()

@socketio.on("update_location")
def handle_location_update(data):
    # (unverändert)
    if "username" not in session or not game_state["active"]: return
    username = session["username"]; player_data = game_state["players"].get(username)
    if not player_data: return
    lat = data.get("lat"); lon = data.get("lon")
    if lat is None or lon is None: return
    player_data['last_location'] = {"lat": lat, "lon": lon}; sid = request.sid
    if username == game_state["mr_x"]:
        real_location = {"lat": lat, "lon": lon}; game_state["mr_x_last_known_location"] = real_location
        now = time.time(); time_since_last_broadcast = now - game_state["mr_x_last_broadcast_time"]
        interval_seconds = game_state["update_interval_minutes"] * 60
        if time_since_last_broadcast >= interval_seconds:
            location_to_send = None; is_decoy_update = False; announce_previous_decoy = False
            if game_state["mrx_pending_decoy_location"]:
                print(f"Sending DECOY location for Mr. X ({username}).")
                location_to_send = game_state["mrx_pending_decoy_location"]
                is_decoy_update = True; game_state["mrx_last_update_was_decoy"] = True; game_state["mrx_pending_decoy_location"] = None
            else:
                location_to_send = real_location
                if game_state["mrx_last_update_was_decoy"]:
                    print(f"Sending REAL location for Mr. X ({username}) and announcing previous was DECOY.")
                    announce_previous_decoy = True; game_state["mrx_last_update_was_decoy"] = False
                else: print(f"Sending REAL location for Mr. X ({username}).")
            update_data = { "username": username, "lat": location_to_send["lat"], "lon": location_to_send["lon"], "previous_was_decoy": announce_previous_decoy }
            socketio.emit("location_update", update_data)
            new_broadcast_time = now; game_state["mr_x_last_broadcast_time"] = new_broadcast_time
            socketio.emit("mrx_update_timer", {"last_broadcast_time": new_broadcast_time})
    else:
        is_invisible = player_data.get('invisible_until') and player_data['invisible_until'] > time.time()
        if not is_invisible:
            print(f"Sending location update for visible seeker {username}.")
            update_data = {"username": username, "lat": lat, "lon": lon}
            socketio.emit("location_update", update_data, room=None, skip_sid=sid)
        else: print(f"Seeker {username} is invisible. Location update suppressed for others.")

@socketio.on("set_decoy_location")
def handle_set_decoy_location(data):
    # (unverändert)
    if "username" not in session or not game_state["active"]: return
    username = session["username"];
    if username != game_state["mr_x"]: return
    if game_state["mrx_remaining_decoys"] <= 0: emit('error_message', {'message': 'Keine Ablenkungsmanöver mehr verfügbar!'}); return
    lat = data.get("lat"); lon = data.get("lon")
    if lat is None or lon is None: emit('error_message', {'message': 'Ungültige Koordinaten für Ablenkungsmanöver.'}); return
    game_state["mrx_pending_decoy_location"] = {"lat": lat, "lon": lon}; game_state["mrx_remaining_decoys"] -= 1
    print(f"Mr. X ({username}) set pending decoy location: Lat={lat}, Lon={lon}. Decoys remaining: {game_state['mrx_remaining_decoys']}")
    emit("decoy_set_confirmation", { "lat": lat, "lon": lon, "remaining_decoys": game_state["mrx_remaining_decoys"] })

@socketio.on("activate_invisibility")
def handle_activate_invisibility():
    if "username" not in session or not game_state["active"]: return
    username = session["username"]
    if username == game_state["mr_x"]: return
    player_data = game_state["players"].get(username)
    if not player_data: return
    if player_data.get('invisible_until') and player_data['invisible_until'] > time.time(): emit('error_message', {'message': 'Du bist bereits unsichtbar!'}); return
    if player_data.get("remaining_invisibility", 0) <= 0: emit('error_message', {'message': 'Keine Unsichtbarkeits-Nutzungen mehr verfügbar!'}); return

    player_data["remaining_invisibility"] -= 1
    duration = game_state["seeker_invisibility_duration_seconds"]
    expiration_time = time.time() + duration
    player_data["invisible_until"] = expiration_time
    print(f"Seeker {username} activated invisibility for {duration}s. Uses remaining: {player_data['remaining_invisibility']}")

    emit("invisibility_activated", { "duration": duration, "remaining_uses": player_data["remaining_invisibility"] })
    # Sende player_invisible statt player_left
    socketio.emit("player_invisible", {"username": username}, room=None, skip_sid=request.sid)
    socketio.start_background_task( target=make_visible_again_wrapper, username=username, expected_expiration=expiration_time, duration=duration )

def make_visible_again_wrapper(username, expected_expiration, duration):
    print(f"Background task started: Wait {duration}s for {username} to become visible.")
    socketio.sleep(duration)
    print(f"Background task finished waiting for {username}.")
    make_visible_again(username, expected_expiration)

def make_visible_again(username, expected_expiration):
    if not game_state["active"]: return
    player_data = game_state["players"].get(username)
    if not player_data: return
    current_expiration = player_data.get('invisible_until')
    if current_expiration is None or abs(current_expiration - expected_expiration) > 1:
        print(f"Task make_visible_again for {username} is outdated or already handled. Ignoring.")
        return

    print(f"Making seeker {username} visible again.")
    player_data['invisible_until'] = None
    socketio.emit("invisibility_ended", room=player_data['sid'])

    # Sende player_visible mit aktueller Position
    current_location = player_data.get('last_location')
    if current_location:
        update_data = { "username": username, "lat": current_location["lat"], "lon": current_location["lon"] }
        socketio.emit("player_visible", update_data, room=None, skip_sid=player_data['sid'])
    else:
        # Fallback, sollte nicht nötig sein
        socketio.emit("player_visible", {"username": username, "lat": None, "lon": None}, room=None, skip_sid=player_data['sid'])


@socketio.on("mr_x_found")
def handle_mr_x_found(data):
    # (unverändert)
    if not game_state["active"] or "username" not in session: return
    username = session["username"];
    if username != game_state["mr_x"]: return
    finder = data.get("finder")
    if not finder or finder not in game_state["players"]: emit('error_message', {'message': f"Ungültiger Finder '{finder}' ausgewählt."}); return
    print(f"Mr. X ({username}) reported found by {finder}!")
    socketio.emit('game_over', { 'message': f"Mr. X ({game_state['mr_x']}) wurde von {finder} gefunden!", 'finder': finder, 'mr_x': game_state['mr_x'] })
    reset_game_state(notify_clients=False)

# --- App Start ---
if __name__ == "__main__":
    # (unverändert)
    print("Starting Flask-SocketIO server for Mr. X Game (with invisibility v2)...")
    port = 1432; host = "0.0.0.0"
    try: socketio.run(app, host=host, port=port, debug=True)
    except ImportError: print("\n--- WARNUNG --- `eventlet` nicht gefunden."); socketio.run(app, host=host, port=port, debug=True, allow_unsafe_werkzeug=True)
    except PermissionError: print(f"\n--- FEHLER --- Port {port} nicht verfügbar.")
    except OSError as e:
         if "address already in use" in str(e).lower(): print(f"\n--- FEHLER --- Port {port} wird bereits verwendet.")
         else: print(f"Ein Fehler ist aufgetreten: {e}")

