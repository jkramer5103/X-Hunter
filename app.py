import os
import time
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
# Importiere SocketIO und die kontextbezogene emit-Funktion
from flask_socketio import SocketIO, emit
from werkzeug.security import check_password_hash

# Importiere nur das 'users' Dictionary
from users import users

# --- Konfiguration ---
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "sehr-geheim-fuer-spiel-ohne-bilder")
# Verwende eventlet oder gevent für bessere Asynchronität
socketio = SocketIO(app, async_mode="eventlet")

# --- Globaler Spielstatus ---
game_state = {
    "active": False,
    "mr_x": None, # Username von Mr. X
    "update_interval_minutes": 5, # Standard-Intervall
    "mr_x_last_broadcast_time": 0,
    "mr_x_last_known_location": None, # Letzte Position von Mr. X
    # Speichert jetzt nur noch SID und letzte Position
    "players": {} # {username: {'sid': ..., 'last_location': {'lat': ..., 'lon': ...}}}
}

# --- Hilfsfunktionen ---
def reset_game_state(notify_clients=True): # Parameter hinzugefügt
    """Setzt den Spielstatus zurück."""
    print("Resetting game state.")
    game_state["active"] = False
    game_state["mr_x"] = None
    game_state["update_interval_minutes"] = 5
    game_state["mr_x_last_broadcast_time"] = 0
    game_state["mr_x_last_known_location"] = None
    game_state["players"] = {}
    # Sende die Nachricht nur, wenn notify_clients True ist
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
        registered_users = list(users.keys())
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

    if not selected_mr_x or selected_mr_x not in users:
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
    # ÄNDERUNG HIER: Setze auf 0, damit das erste Update sofort durchkommt
    game_state["mr_x_last_broadcast_time"] = 0
    game_state["mr_x_last_known_location"] = None
    game_state["players"] = {}

    print(f"Spiel gestartet! Mr. X: {selected_mr_x}, Interval: {interval_minutes} min")
    flash(f"Spiel gestartet! {selected_mr_x} ist Mr. X.", "success")

    # Informiere alle Clients über den Spielstart (ohne broadcast=True)
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
        user_data = users.get(username)
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
        # Wenn der User im Spiel war und Mr. X ist, Spiel beenden
        if game_state["active"] and username == game_state["mr_x"]:
            print(f"Mr. X ({username}) hat sich ausgeloggt. Spiel wird beendet.")
            reset_game_state() # Ruft mit notify_clients=True (Standard) auf
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
    game_state["players"][username] = {"sid": sid, "last_location": None}

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

    # Sende nur an den neuen Client
    emit("game_update", {
        "mr_x": game_state["mr_x"],
        "locations": current_locations,
        "players": list(game_state["players"].keys())
    })

    # Informiere andere über neuen Spieler (ohne broadcast=True, mit skip_sid)
    socketio.emit("player_joined", {"username": username}, room=None, skip_sid=sid)


@socketio.on("disconnect")
def handle_disconnect():
    """Wenn ein Client die Verbindung trennt."""
    username = None
    sid = request.sid
    for user, data in list(game_state["players"].items()):
        if data["sid"] == sid:
            username = user
            del game_state["players"][username]
            break

    if username:
        print(f"Client disconnected: {username} ({sid})")
        if game_state["active"]:
            # Informiere alle verbleibenden Clients (ohne broadcast=True)
            socketio.emit("player_left", {"username": username})
            print(f"Removed {username} from active game.")

            # Prüfe NUR, ob Mr. X gegangen ist
            if username == game_state["mr_x"]:
                print(f"Mr. X ({username}) disconnected. Ending game.")
                reset_game_state() # Ruft mit notify_clients=True (Standard) auf

    else:
        session_username = session.get('username', 'Unknown User')
        print(f"Client disconnected: {session_username} (SID: {sid}), war nicht in aktivem Spiel registriert.")


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
        # Die Zeit seit der letzten Sendung wird geprüft
        time_since_last_broadcast = now - game_state["mr_x_last_broadcast_time"]
        interval_seconds = game_state["update_interval_minutes"] * 60

        # Die Bedingung wird beim ersten Mal (da mr_x_last_broadcast_time = 0 ist) erfüllt sein
        if time_since_last_broadcast >= interval_seconds:
            print(f"Broadcasting Mr. X ({username}) location update.")
            # Sende an alle (ohne broadcast=True)
            socketio.emit("location_update", update_data)
            # Setze den Zeitstempel für die nächste Prüfung
            game_state["mr_x_last_broadcast_time"] = now
    else:
        # Sende Update sofort an alle ANDEREN (ohne broadcast=True, mit skip_sid)
        socketio.emit("location_update", update_data, room=None, skip_sid=sid)


@socketio.on("mr_x_found")
def handle_mr_x_found(data):
    """Mr. X meldet, dass er gefunden wurde."""
    if not game_state["active"] or "username" not in session: return
    username = session["username"]
    if username != game_state["mr_x"]: return

    finder = data.get("finder")
    if not finder or finder not in game_state["players"]:
        emit('error_message', {'message': f"Ungültiger Finder '{finder}' ausgewählt."})
        return

    print(f"Mr. X ({username}) reported found by {finder}!")

    # 1. Informiere alle Clients über das Spielende (mit spezifischer Nachricht)
    socketio.emit('game_over', {
        'message': f"Mr. X ({game_state['mr_x']}) wurde von {finder} gefunden!",
        'finder': finder,
        'mr_x': game_state['mr_x']
    })

    # 2. Spielstatus zurücksetzen, OHNE erneut zu benachrichtigen
    reset_game_state(notify_clients=False) # Hier False übergeben!


# --- App Start ---
if __name__ == "__main__":
    print("Starting Flask-SocketIO server for Mr. X Game (no profile pics)...")
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
