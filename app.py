import os
import time
import json # Importiere das json Modul
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_socketio import SocketIO, emit
from werkzeug.security import check_password_hash
import threading

# --- Lade Benutzerdaten aus JSON ---
USERS_FILE = "users.json"
loaded_users = {} # Standardmäßig leeres Dictionary

try:
    # Stelle sicher, dass der Pfad relativ zum Skriptverzeichnis ist
    base_dir = os.path.dirname(os.path.abspath(__file__))
    users_file_path = os.path.join(base_dir, USERS_FILE)
    with open(users_file_path, 'r', encoding='utf-8') as f:
        loaded_users = json.load(f)
    print(f"Benutzerdaten erfolgreich aus {USERS_FILE} geladen.")
except FileNotFoundError:
    print(f"FEHLER: {USERS_FILE} nicht gefunden. Keine Benutzer geladen.")
    # Hier könntest du entscheiden, ob die App trotzdem starten soll
except json.JSONDecodeError:
    print(f"FEHLER: Konnte JSON aus {USERS_FILE} nicht dekodieren. Bitte Format prüfen.")
except Exception as e:
    print(f"FEHLER: Unerwarteter Fehler beim Laden von {USERS_FILE}: {e}")

# --- Konfiguration ---
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "sehr-geheim-fuer-spiel-ohne-bilder")
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
    "mrx_disconnect_task_pending": False
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

    if notify_clients:
        print("Notifying clients about game reset.")
        socketio.emit('game_over', {'message': 'Das Spiel wurde beendet oder zurückgesetzt.', 'finder': None})
    else:
         print("Game reset without notifying clients (notification already sent).")


# --- Routen ---

@app.route("/")
def index():
    """Startseite: Zeigt Spielkonfiguration oder leitet zur Karte/Login weiter."""
    if not session.get("username"):
        return redirect(url_for("login"))

    if game_state["active"]:
        return redirect(url_for("map_page"))
    else:
        # Verwende loaded_users
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

    # Verwende loaded_users
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

    game_state["active"] = True
    game_state["mr_x"] = selected_mr_x
    game_state["update_interval_minutes"] = interval_minutes
    game_state["mr_x_last_broadcast_time"] = 0
    game_state["mr_x_last_known_location"] = None
    game_state["players"] = {}
    game_state["mrx_disconnect_task_pending"] = False

    print(f"Spiel gestartet! Mr. X: {selected_mr_x}, Interval: {interval_minutes} min")
    flash(f"Spiel gestartet! {selected_mr_x} ist Mr. X.", "success")

    socketio.emit('game_started', {
        'mr_x': game_state['mr_x'],
        'interval': game_state['update_interval_minutes']
    })

    return redirect(url_for("map_page"))


@app.route("/login", methods=["GET", "POST"])
def login():
    """Verarbeitet den Login."""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        # Verwende loaded_users
        user_data = loaded_users.get(username)
        if user_data and check_password_hash(user_data["password"], password):
            session["username"] = username
            print(f"User '{username}' logged in.")
            return redirect(url_for("index"))
        else:
            flash("Ungültiger Benutzername oder Passwort", "error")
            return redirect(url_for("login"))

    if "username" in session:
        return redirect(url_for("index"))

    return render_template("login.html")

@app.route("/map")
def map_page():
    """Zeigt die Karte, aber nur wenn ein Spiel aktiv ist."""
    if "username" not in session:
        return redirect(url_for("login"))
    if not game_state["active"]:
        flash("Derzeit läuft kein Spiel.", "info")
        return redirect(url_for("index"))

    return render_template(
        "map.html",
        username=session["username"],
        mr_x_username=game_state["mr_x"],
        current_players_list=[p for p in game_state["players"] if p != session["username"]]
    )

@app.route("/logout")
def logout():
    """Meldet den Nutzer ab."""
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
    """Wenn ein Client verbindet."""
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
        "players": list(game_state["players"].keys())
    })

    socketio.emit("player_joined", {"username": username}, room=None, skip_sid=sid)


@socketio.on("disconnect")
def handle_disconnect():
    """Wenn ein Client die Verbindung trennt."""
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

# Wrapper-Funktion für den Hintergrund-Task, um Argumente zu übergeben
def end_game_due_to_mrx_disconnect_wrapper(grace_period):
    """Wrapper, um socketio.sleep im Hintergrund-Task zu verwenden."""
    print(f"Background task started: Wait {grace_period}s for Mr. X reconnect.")
    socketio.sleep(grace_period)
    print("Background task finished waiting.")
    end_game_due_to_mrx_disconnect()


@socketio.on("update_location")
def handle_location_update(data):
    """Empfängt Standort-Update und verteilt es gemäß Spielregeln."""
    if "username" not in session or not game_state["active"]: return
    username = session["username"]
    if username not in game_state["players"]: return

    lat = data.get("lat")
    lon = data.get("lon")
    if lat is None or lon is None: return

    game_state["players"][username]['last_location'] = {"lat": lat, "lon": lon}
    update_data = {"username": username, "lat": lat, "lon": lon}
    sid = request.sid

    if username == game_state["mr_x"]:
        game_state["mr_x_last_known_location"] = {"lat": lat, "lon": lon}
        now = time.time()
        time_since_last_broadcast = now - game_state["mr_x_last_broadcast_time"]
        interval_seconds = game_state["update_interval_minutes"] * 60

        if time_since_last_broadcast >= interval_seconds:
            print(f"Broadcasting Mr. X ({username}) location update.")
            socketio.emit("location_update", update_data)
            game_state["mr_x_last_broadcast_time"] = now
    else:
        socketio.emit("location_update", update_data, room=None, skip_sid=sid)


@socketio.on("mr_x_found")
def handle_mr_x_found(data):
    """Mr. X meldet, dass er gefunden wurde."""
    if not game_state["active"] or "username" not in session: return
    username = session["username"]
    if username != game_state["mr_x"]: return

    finder = data.get("finder")
    # Verwende loaded_users hier nicht, prüfe gegen game_state["players"]
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
    print("Starting Flask-SocketIO server for Mr. X Game (users from JSON)...")
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

