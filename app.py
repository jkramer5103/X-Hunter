import os
import time
import json
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_socketio import SocketIO, emit
from werkzeug.security import check_password_hash
import threading

# --- Lade Benutzerdaten aus JSON ---
USERS_FILE = "users.json"
loaded_users = {}
try:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    users_file_path = os.path.join(base_dir, USERS_FILE)
    with open(users_file_path, 'r', encoding='utf-8') as f:
        loaded_users = json.load(f)
    print(f"Benutzerdaten erfolgreich aus {USERS_FILE} geladen.")
except Exception as e:
    print(f"FEHLER beim Laden von {USERS_FILE}: {e}")

# --- Konfiguration ---
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "sehr-geheim-fuer-spiel-mit-decoy")
socketio = SocketIO(app, async_mode="eventlet")

# --- Konstante für Karenzzeit ---
MRX_DISCONNECT_GRACE_PERIOD_SECONDS = 60

# --- Globaler Spielstatus ---
game_state = {
    "active": False,
    "mr_x": None,
    "update_interval_minutes": 5,
    "mr_x_last_broadcast_time": 0,
    "mr_x_last_known_location": None,
    "players": {},
    "mrx_disconnect_task_pending": False,
    "mrx_decoy_available": True,
    "mrx_pending_decoy_location": None,
    "mrx_last_update_was_decoy": False
}

# --- Hilfsfunktionen ---
def end_game_due_to_mrx_disconnect():
    """Wird aufgerufen, wenn die Karenzzeit für Mr. X abläuft."""
    if game_state["mrx_disconnect_task_pending"] and game_state["active"]:
        print(f"Grace period for Mr. X ({game_state['mr_x']}) expired. Ending game.")
        if game_state['mr_x'] not in game_state['players']:
             reset_game_state()
        else:
             print(f"Mr. X ({game_state['mr_x']}) reconnected just before grace period ended. Game continues.")
    game_state["mrx_disconnect_task_pending"] = False

def reset_game_state(notify_clients=True):
    """Setzt den Spielstatus zurück."""
    if game_state["mrx_disconnect_task_pending"]:
        print("Cancelling pending Mr. X disconnect task due to game reset.")
        game_state["mrx_disconnect_task_pending"] = False

    print("Resetting game state.")
    game_state["active"] = False
    game_state["mr_x"] = None
    game_state["update_interval_minutes"] = 5
    game_state["mr_x_last_broadcast_time"] = 0
    game_state["mr_x_last_known_location"] = None
    game_state["players"] = {}
    game_state["mrx_decoy_available"] = True
    game_state["mrx_pending_decoy_location"] = None
    game_state["mrx_last_update_was_decoy"] = False

    if notify_clients:
        print("Notifying clients about game reset.")
        socketio.emit('game_over', {'message': 'Das Spiel wurde beendet oder zurückgesetzt.', 'finder': None})
    else:
         print("Game reset without notifying clients (notification already sent).")


# --- Routen ---

@app.route("/")
def index():
    if not session.get("username"): return redirect(url_for("login"))
    if game_state["active"]: return redirect(url_for("map_page"))
    else:
        registered_users = list(loaded_users.keys())
        return render_template("start.html", registered_users=registered_users)

@app.route("/start_game", methods=["POST"])
def start_game():
    """Nimmt die Spielkonfiguration entgegen und startet das Spiel."""
    if "username" not in session:
        return redirect(url_for("login"))

    if game_state["active"]:
        flash("Ein Spiel läuft bereits!", "warning")
        return redirect(url_for("map_page"))

    selected_mr_x = request.form.get("mr_x")
    interval_str = request.form.get("interval", "5")

    if not selected_mr_x or selected_mr_x not in loaded_users:
        flash("Bitte wähle einen gültigen Spieler als Mr. X aus.", "error")
        return redirect(url_for("index"))
    try:
        interval_minutes = int(interval_str)
        if interval_minutes <= 0:
            raise ValueError("Interval must be positive")
    except ValueError:
        flash("Bitte gib ein gültiges Update-Intervall (positive Zahl) an.", "error")
        return redirect(url_for("index"))

    # --- KEIN reset_game_state() HIER ---
    # Explizite Initialisierung aller Werte für das neue Spiel:
    game_state["active"] = True
    game_state["mr_x"] = selected_mr_x
    game_state["update_interval_minutes"] = interval_minutes
    game_state["mr_x_last_broadcast_time"] = 0 # Für sofortiges erstes Update
    game_state["mr_x_last_known_location"] = None
    game_state["players"] = {}
    game_state["mrx_disconnect_task_pending"] = False
    game_state["mrx_decoy_available"] = True
    game_state["mrx_pending_decoy_location"] = None
    game_state["mrx_last_update_was_decoy"] = False

    print(f"Spiel gestartet! Mr. X: {selected_mr_x}, Interval: {interval_minutes} min")
    flash(f"Spiel gestartet! {selected_mr_x} ist Mr. X.", "success")

    socketio.emit('game_started', {
        'mr_x': game_state['mr_x'],
        'interval': game_state['update_interval_minutes']
    })
    return redirect(url_for("map_page"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        user_data = loaded_users.get(username)
        if user_data and check_password_hash(user_data["password"], password):
            session["username"] = username
            print(f"User '{username}' logged in.")
            return redirect(url_for("index"))
        else:
            flash("Ungültiger Benutzername oder Passwort", "error")
            return redirect(url_for("login"))
    if "username" in session: return redirect(url_for("index"))
    return render_template("login.html")

@app.route("/map")
def map_page():
    if "username" not in session: return redirect(url_for("login"))
    if not game_state["active"]:
        flash("Derzeit läuft kein Spiel.", "info")
        return redirect(url_for("index"))
    return render_template(
        "map.html",
        username=session["username"],
        mr_x_username=game_state["mr_x"],
        current_players_list=[p for p in game_state["players"] if p != session["username"]],
        mrx_decoy_available=game_state["mrx_decoy_available"]
    )

@app.route("/logout")
def logout():
    username = session.pop("username", None)
    if username:
        print(f"User '{username}' logged out.")
        if game_state["active"] and username == game_state["mr_x"]:
            print(f"Mr. X ({username}) explicitly logged out. Ending game.")
            reset_game_state()
    return redirect(url_for("login"))


# --- SocketIO Events ---

@socketio.on("connect")
def handle_connect():
    if "username" not in session: return False
    username = session["username"]
    sid = request.sid
    print(f"Client connected: {username} ({sid})")

    if not game_state["active"]:
        print(f"User {username} connected, but no game active.")
        return

    print(f"User {username} joined active game.")

    if username == game_state["mr_x"] and game_state["mrx_disconnect_task_pending"]:
        print(f"Mr. X ({username}) reconnected within grace period! Cancelling game end task.")
        game_state["mrx_disconnect_task_pending"] = False

    game_state["players"][username] = {"sid": sid, "last_location": game_state["players"].get(username, {}).get('last_location')}

    current_locations = {}
    for player, data in game_state["players"].items():
        loc = data.get('last_location')
        if player != game_state["mr_x"] and loc:
             current_locations[player] = {"lat": loc["lat"], "lon": loc["lon"]}
        elif player == game_state["mr_x"] and game_state["mr_x_last_known_location"]:
             current_locations[player] = {
                 "lat": game_state["mr_x_last_known_location"]["lat"],
                 "lon": game_state["mr_x_last_known_location"]["lon"]
             }

    emit("game_update", {
        "mr_x": game_state["mr_x"],
        "locations": current_locations,
        "players": list(game_state["players"].keys()),
        "mrx_decoy_available": game_state["mrx_decoy_available"] if username == game_state["mr_x"] else None
    })

    socketio.emit("player_joined", {"username": username}, room=None, skip_sid=sid)


@socketio.on("disconnect")
def handle_disconnect():
    username = None
    sid = request.sid
    disconnecting_user = None
    for user, data in game_state["players"].items():
        if data["sid"] == sid:
            disconnecting_user = user
            break

    if disconnecting_user:
        print(f"Client disconnected: {disconnecting_user} ({sid})")
        if game_state["active"]:
            if disconnecting_user == game_state["mr_x"]:
                if not game_state["mrx_disconnect_task_pending"]:
                    print(f"Mr. X ({disconnecting_user}) disconnected. Starting grace period ({MRX_DISCONNECT_GRACE_PERIOD_SECONDS}s)...")
                    game_state["mrx_disconnect_task_pending"] = True
                    socketio.start_background_task(
                        target=end_game_due_to_mrx_disconnect_wrapper,
                        grace_period=MRX_DISCONNECT_GRACE_PERIOD_SECONDS
                    )
                    socketio.emit("player_left", {"username": disconnecting_user})
                else:
                    print(f"Mr. X ({disconnecting_user}) disconnected, but grace period task already pending.")
            else:
                print(f"Player {disconnecting_user} disconnected. Removing.")
                if disconnecting_user in game_state["players"]:
                     del game_state["players"][disconnecting_user]
                socketio.emit("player_left", {"username": disconnecting_user})
                print(f"Removed {disconnecting_user} from active game.")

    else:
        session_username = session.get('username', 'Unknown User')
        print(f"Client disconnected: {session_username} (SID: {sid}), war nicht in aktivem Spiel registriert.")

# Wrapper-Funktion für den Hintergrund-Task
def end_game_due_to_mrx_disconnect_wrapper(grace_period):
    print(f"Background task started: Wait {grace_period}s for Mr. X reconnect.")
    socketio.sleep(grace_period)
    print("Background task finished waiting.")
    end_game_due_to_mrx_disconnect()


@socketio.on("update_location")
def handle_location_update(data):
    if "username" not in session or not game_state["active"]: return
    username = session["username"]
    if username not in game_state["players"]: return

    lat = data.get("lat")
    lon = data.get("lon")
    if lat is None or lon is None: return

    game_state["players"][username]['last_location'] = {"lat": lat, "lon": lon}
    sid = request.sid

    if username == game_state["mr_x"]:
        real_location = {"lat": lat, "lon": lon}
        game_state["mr_x_last_known_location"] = real_location

        now = time.time()
        time_since_last_broadcast = now - game_state["mr_x_last_broadcast_time"]
        interval_seconds = game_state["update_interval_minutes"] * 60

        if time_since_last_broadcast >= interval_seconds:
            location_to_send = None
            is_decoy_update = False
            announce_previous_decoy = False

            if game_state["mrx_pending_decoy_location"]:
                print(f"Sending DECOY location for Mr. X ({username}).")
                location_to_send = game_state["mrx_pending_decoy_location"]
                is_decoy_update = True
                game_state["mrx_last_update_was_decoy"] = True
                game_state["mrx_pending_decoy_location"] = None
            else:
                location_to_send = real_location
                if game_state["mrx_last_update_was_decoy"]:
                    print(f"Sending REAL location for Mr. X ({username}) and announcing previous was DECOY.")
                    announce_previous_decoy = True
                    game_state["mrx_last_update_was_decoy"] = False
                else:
                     print(f"Sending REAL location for Mr. X ({username}).")

            update_data = {
                "username": username,
                "lat": location_to_send["lat"],
                "lon": location_to_send["lon"],
                "previous_was_decoy": announce_previous_decoy
            }

            socketio.emit("location_update", update_data)
            game_state["mr_x_last_broadcast_time"] = now
    else:
        update_data = {"username": username, "lat": lat, "lon": lon}
        socketio.emit("location_update", update_data, room=None, skip_sid=sid)


@socketio.on("set_decoy_location")
def handle_set_decoy_location(data):
    if "username" not in session or not game_state["active"]: return
    username = session["username"]

    if username != game_state["mr_x"]: return
    if not game_state["mrx_decoy_available"]:
        emit('error_message', {'message': 'Ablenkungsmanöver bereits verwendet!'})
        return

    lat = data.get("lat")
    lon = data.get("lon")
    if lat is None or lon is None:
        emit('error_message', {'message': 'Ungültige Koordinaten für Ablenkungsmanöver.'})
        return

    game_state["mrx_pending_decoy_location"] = {"lat": lat, "lon": lon}
    game_state["mrx_decoy_available"] = False
    print(f"Mr. X ({username}) set pending decoy location: Lat={lat}, Lon={lon}")

    emit("decoy_set_confirmation", {"lat": lat, "lon": lon})


@socketio.on("mr_x_found")
def handle_mr_x_found(data):
    if not game_state["active"] or "username" not in session: return
    username = session["username"]
    if username != game_state["mr_x"]: return

    finder = data.get("finder")
    if not finder or finder not in game_state["players"]:
        emit('error_message', {'message': f"Ungültiger Finder '{finder}' ausgewählt."})
        return

    print(f"Mr. X ({username}) reported found by {finder}!")

    socketio.emit('game_over', {
        'message': f"Mr. X ({game_state['mr_x']}) wurde von {finder} gefunden!",
        'finder': finder,
        'mr_x': game_state['mr_x']
    })
    reset_game_state(notify_clients=False)


# --- App Start ---
if __name__ == "__main__":
    print("Starting Flask-SocketIO server for Mr. X Game (with decoy & grace period)...")
    port = 1432
    host = "0.0.0.0"
    try:
        socketio.run(app, host=host, port=port, debug=True)
    except ImportError:
         print("\n--- WARNUNG --- `eventlet` nicht gefunden.")
         socketio.run(app, host=host, port=port, debug=True, allow_unsafe_werkzeug=True)
    except PermissionError: print(f"\n--- FEHLER --- Port {port} nicht verfügbar.")
    except OSError as e:
         if "address already in use" in str(e).lower(): print(f"\n--- FEHLER --- Port {port} wird bereits verwendet.")
         else: print(f"Ein Fehler ist aufgetreten: {e}")

