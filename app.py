import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any

from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
USERS_JSON_FILE = DATA_DIR / "users.json"
USERS_DB_FILE = DATA_DIR / "users.db"

MRX_DISCONNECT_GRACE_PERIOD_SECONDS = 60
DEFAULT_DECOYS = 1
DEFAULT_INVISIBILITY_USES = 2
DEFAULT_INVISIBILITY_DURATION_SECONDS = 30
SEEKERS_CHAT_ROOM = "seekers_chat_room"


class UserRepository:
    """Persistent user management with SQLite and JSON auto-migration."""

    def __init__(self, db_path: Path, legacy_json_path: Path) -> None:
        self.db_path = db_path
        self.legacy_json_path = legacy_json_path
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        DATA_DIR.mkdir(exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT,
                    has_password INTEGER NOT NULL DEFAULT 0,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()
        self._migrate_legacy_json_if_needed()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _migrate_legacy_json_if_needed(self) -> None:
        if not self.legacy_json_path.exists() or self.users_exist():
            return

        try:
            legacy_users = json.loads(self.legacy_json_path.read_text(encoding="utf-8"))
        except Exception as exc:  # best effort migration only
            print(f"WARN: failed to read legacy users JSON: {exc}")
            return

        now = int(time.time())
        with self._connect() as conn:
            for username, payload in legacy_users.items():
                password_hash = payload.get("password")
                has_password = payload.get("has_password")
                if has_password is None:
                    has_password = password_hash is not None

                conn.execute(
                    """
                    INSERT OR IGNORE INTO users(username, password_hash, has_password, is_admin, created_at)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        password_hash,
                        int(bool(has_password)),
                        int(bool(payload.get("is_admin", False))),
                        now,
                    ),
                )
            conn.commit()
        print(f"Migrated legacy users from {self.legacy_json_path} to {self.db_path}.")

    def users_exist(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
            return bool(row["c"])

    def list_users(self) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT username, password_hash, has_password, is_admin FROM users ORDER BY username"
            ).fetchall()

        users: dict[str, dict[str, Any]] = {}
        for row in rows:
            users[row["username"]] = {
                "password": row["password_hash"],
                "has_password": bool(row["has_password"]),
                "is_admin": bool(row["is_admin"]),
            }
        return users

    def get_user(self, username: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT username, password_hash, has_password, is_admin FROM users WHERE username = ?",
                (username,),
            ).fetchone()

        if not row:
            return None

        return {
            "username": row["username"],
            "password": row["password_hash"],
            "has_password": bool(row["has_password"]),
            "is_admin": bool(row["is_admin"]),
        }

    def add_user(self, username: str, is_admin: bool = False) -> bool:
        now = int(time.time())
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO users(username, password_hash, has_password, is_admin, created_at)
                    VALUES (?, NULL, 0, ?, ?)
                    """,
                    (username, int(is_admin), now),
                )
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def delete_user(self, username: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM users WHERE username = ?", (username,))
            conn.commit()
            return cur.rowcount > 0

    def set_admin(self, username: str, is_admin: bool) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE users SET is_admin = ? WHERE username = ?",
                (int(is_admin), username),
            )
            conn.commit()
            return cur.rowcount > 0

    def count_admins(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM users WHERE is_admin = 1").fetchone()
            return int(row["c"])

    def set_password_hash(self, username: str, password_hash: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE users SET password_hash = ?, has_password = 1 WHERE username = ?",
                (password_hash, username),
            )
            conn.commit()
            return cur.rowcount > 0

    def reset_password(self, username: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE users SET password_hash = NULL, has_password = 0 WHERE username = ?",
                (username,),
            )
            conn.commit()
            return cur.rowcount > 0


@dataclass
class PlayerState:
    sid: str
    last_location: dict[str, float] | None = None
    remaining_invisibility: int = DEFAULT_INVISIBILITY_USES
    invisible_until: float | None = None


@dataclass
class GameState:
    active: bool = False
    mr_x: str | None = None
    update_interval_minutes: int = 5
    mr_x_last_broadcast_time: float = 0
    mr_x_last_known_location: dict[str, float] | None = None
    players: dict[str, PlayerState] = field(default_factory=dict)
    mrx_disconnect_task_pending: bool = False
    mrx_total_decoys: int = DEFAULT_DECOYS
    mrx_remaining_decoys: int = DEFAULT_DECOYS
    mrx_pending_decoy_location: dict[str, float] | None = None
    mrx_last_update_was_decoy: bool = False
    seeker_invisibility_uses: int = DEFAULT_INVISIBILITY_USES
    seeker_invisibility_duration_seconds: int = DEFAULT_INVISIBILITY_DURATION_SECONDS

    def reset(self) -> None:
        self.active = False
        self.mr_x = None
        self.update_interval_minutes = 5
        self.mr_x_last_broadcast_time = 0
        self.mr_x_last_known_location = None
        self.players = {}
        self.mrx_disconnect_task_pending = False
        self.mrx_total_decoys = DEFAULT_DECOYS
        self.mrx_remaining_decoys = DEFAULT_DECOYS
        self.mrx_pending_decoy_location = None
        self.mrx_last_update_was_decoy = False
        self.seeker_invisibility_uses = DEFAULT_INVISIBILITY_USES
        self.seeker_invisibility_duration_seconds = DEFAULT_INVISIBILITY_DURATION_SECONDS


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "sehr-geheim-fuer-spiel-mit-chat")
socketio = SocketIO(app, async_mode="eventlet")
user_repo = UserRepository(USERS_DB_FILE, USERS_JSON_FILE)
game = GameState()


def current_user() -> str | None:
    return session.get("username")


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        username = current_user()
        if not username:
            flash("Bitte zuerst einloggen.", "warning")
            return redirect(url_for("login"))

        user_data = user_repo.get_user(username)
        if not user_data or not user_data.get("is_admin", False):
            flash("Zugriff verweigert. Nur Administratoren erlaubt.", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    return decorated_function


def end_game_due_to_mrx_disconnect() -> None:
    if game.mrx_disconnect_task_pending and game.active:
        if game.mr_x not in game.players:
            reset_game_state()
        else:
            print(f"Mr. X ({game.mr_x}) reconnected before grace period ended.")
    game.mrx_disconnect_task_pending = False


def end_game_due_to_mrx_disconnect_wrapper(grace_period: int) -> None:
    socketio.sleep(grace_period)
    end_game_due_to_mrx_disconnect()


def make_visible_again(username: str, expected_expiration: float) -> None:
    if not game.active:
        return

    player = game.players.get(username)
    if not player:
        return

    current_expiration = player.invisible_until
    if current_expiration is None or abs(current_expiration - expected_expiration) > 1:
        return

    player.invisible_until = None
    socketio.emit("invisibility_ended", room=player.sid)

    if player.last_location:
        socketio.emit(
            "player_visible",
            {
                "username": username,
                "lat": player.last_location["lat"],
                "lon": player.last_location["lon"],
            },
            skip_sid=player.sid,
        )
    else:
        socketio.emit(
            "player_visible",
            {"username": username, "lat": None, "lon": None},
            skip_sid=player.sid,
        )


def make_visible_again_wrapper(username: str, expected_expiration: float, duration: int) -> None:
    socketio.sleep(duration)
    make_visible_again(username, expected_expiration)


def reset_game_state(notify_clients: bool = True) -> None:
    game.reset()
    if notify_clients:
        socketio.emit(
            "game_over",
            {"message": "Das Spiel wurde beendet oder zurückgesetzt.", "finder": None},
        )


@app.route("/")
def index():
    if not user_repo.users_exist():
        return redirect(url_for("setup"))

    username = current_user()
    if not username:
        return redirect(url_for("login"))

    if game.active:
        return redirect(url_for("map_page"))

    users = user_repo.list_users()
    is_admin = bool(users.get(username, {}).get("is_admin", False))
    return render_template(
        "start.html",
        registered_users=list(users.keys()),
        is_admin=is_admin,
        default_decoys=DEFAULT_DECOYS,
        default_invisibility_uses=DEFAULT_INVISIBILITY_USES,
        default_invisibility_duration=DEFAULT_INVISIBILITY_DURATION_SECONDS,
    )


@app.route("/start_game", methods=["POST"])
@admin_required
def start_game():
    if game.active:
        flash("Ein Spiel läuft bereits!", "warning")
        return redirect(url_for("map_page"))

    users = user_repo.list_users()
    selected_mr_x = request.form.get("mr_x")

    try:
        interval_minutes = int(request.form.get("interval", "5"))
        num_decoys = int(request.form.get("num_decoys", str(DEFAULT_DECOYS)))
        num_invisibility = int(request.form.get("num_invisibility", str(DEFAULT_INVISIBILITY_USES)))
        invisibility_duration = int(
            request.form.get("invisibility_duration", str(DEFAULT_INVISIBILITY_DURATION_SECONDS))
        )
        if interval_minutes <= 0 or num_decoys < 0 or num_invisibility < 0 or invisibility_duration <= 0:
            raise ValueError
    except ValueError:
        flash("Bitte gib gültige Zahlen für Intervall, Ablenkungsmanöver und Unsichtbarkeit an.", "error")
        return redirect(url_for("index"))

    if not selected_mr_x or selected_mr_x not in users:
        flash("Bitte wähle einen gültigen Spieler als Mr. X aus.", "error")
        return redirect(url_for("index"))

    game.active = True
    game.mr_x = selected_mr_x
    game.update_interval_minutes = interval_minutes
    game.mr_x_last_broadcast_time = 0
    game.mr_x_last_known_location = None
    game.players = {}
    game.mrx_disconnect_task_pending = False
    game.mrx_total_decoys = num_decoys
    game.mrx_remaining_decoys = num_decoys
    game.mrx_pending_decoy_location = None
    game.mrx_last_update_was_decoy = False
    game.seeker_invisibility_uses = num_invisibility
    game.seeker_invisibility_duration_seconds = invisibility_duration

    socketio.emit(
        "game_started",
        {
            "mr_x": game.mr_x,
            "interval": game.update_interval_minutes,
            "num_decoys": num_decoys,
            "num_invisibility": num_invisibility,
            "invisibility_duration": invisibility_duration,
        },
    )
    flash(f"Spiel gestartet! {selected_mr_x} ist Mr. X.", "success")
    return redirect(url_for("map_page"))


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if user_repo.users_exist():
        return redirect(url_for("login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        if not username:
            flash("Benutzername ist erforderlich.", "error")
            return render_template("setup.html")

        if not user_repo.add_user(username, is_admin=True):
            flash("Fehler beim Speichern des Benutzers. Bitte versuchen Sie es erneut.", "error")
            return render_template("setup.html")

        flash(
            "Admin-Benutzer erfolgreich erstellt! Sie können sich jetzt anmelden und Ihr Passwort festlegen.",
            "success",
        )
        return redirect(url_for("login"))

    return render_template("setup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        user_data = user_repo.get_user(username)

        if not user_data:
            flash("Benutzername nicht gefunden", "error")
            return render_template("login_username.html")

        session["temp_username"] = username
        if user_data.get("has_password", False):
            return redirect(url_for("login_password"))
        return redirect(url_for("login_setup_password"))

    if current_user():
        return redirect(url_for("index"))

    return render_template("login_username.html")


@app.route("/login/password", methods=["GET", "POST"])
def login_password():
    username = session.get("temp_username")
    if not username:
        return redirect(url_for("login"))

    user_data = user_repo.get_user(username)
    if not user_data or not user_data.get("has_password", False):
        return redirect(url_for("login"))

    if request.method == "POST":
        password = request.form.get("password", "")
        password_hash = user_data.get("password") or ""
        if check_password_hash(password_hash, password):
            session.pop("temp_username", None)
            session["username"] = username
            return redirect(url_for("index"))
        flash("Ungültiges Passwort", "error")

    return render_template("login_password.html", username=username)


@app.route("/login/setup-password", methods=["GET", "POST"])
def login_setup_password():
    username = session.get("temp_username")
    if not username:
        return redirect(url_for("login"))

    user_data = user_repo.get_user(username)
    if not user_data or user_data.get("has_password", False):
        return redirect(url_for("login"))

    if request.method == "POST":
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        if not password or not password_confirm:
            flash("Passwort und Bestätigung sind erforderlich.", "error")
        elif password != password_confirm:
            flash("Passwörter stimmen nicht überein.", "error")
        elif len(password) < 6:
            flash("Passwort muss mindestens 6 Zeichen lang sein.", "error")
        else:
            ok = user_repo.set_password_hash(username, generate_password_hash(password))
            if not ok:
                flash("Fehler beim Speichern des Passworts. Bitte versuchen Sie es erneut.", "error")
            else:
                session.pop("temp_username", None)
                session["username"] = username
                flash("Passwort erfolgreich festgelegt!", "success")
                return redirect(url_for("index"))

    return render_template("login_setup_password.html", username=username)


@app.route("/map")
def map_page():
    username = current_user()
    if not username:
        return redirect(url_for("login"))

    if not game.active:
        flash("Derzeit läuft kein Spiel.", "info")
        return redirect(url_for("index"))

    users = user_repo.list_users()
    is_admin = users.get(username, {}).get("is_admin", False)

    return render_template(
        "map.html",
        username=username,
        mr_x_username=game.mr_x,
        current_players_list=[p for p in game.players if p != username],
        mrx_remaining_decoys=game.mrx_remaining_decoys,
        seeker_remaining_invisibility=game.seeker_invisibility_uses,
        is_admin=is_admin,
    )


@app.route("/logout")
def logout():
    username = session.pop("username", None)
    session.pop("temp_username", None)
    if username and game.active and username == game.mr_x:
        reset_game_state()
    return redirect(url_for("login"))


@app.route("/manage_users", methods=["GET", "POST"])
@admin_required
def manage_users():
    current_admin = session["username"]

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            new_username = (request.form.get("new_username") or "").strip()
            is_new_admin = request.form.get("is_new_admin") == "on"
            if not new_username:
                flash("Benutzername darf nicht leer sein.", "error")
            elif not user_repo.add_user(new_username, is_admin=is_new_admin):
                flash(f"Benutzername '{new_username}' existiert bereits.", "error")
            else:
                flash(
                    f"Benutzer '{new_username}' {'als Admin ' if is_new_admin else ''}erfolgreich hinzugefügt. Passwort wird beim ersten Login festgelegt.",
                    "success",
                )

        elif action == "delete":
            username_to_delete = request.form.get("username_to_delete")
            user = user_repo.get_user(username_to_delete or "")
            if not username_to_delete or not user:
                flash("Benutzer nicht gefunden.", "error")
            elif username_to_delete == current_admin:
                flash("Du kannst dich nicht selbst löschen.", "error")
            elif user["is_admin"] and user_repo.count_admins() <= 1:
                flash("Der letzte Administrator kann nicht gelöscht werden.", "error")
            elif user_repo.delete_user(username_to_delete):
                flash(f"Benutzer '{username_to_delete}' erfolgreich gelöscht.", "success")

        elif action in {"grant_admin", "revoke_admin", "reset_password"}:
            username_to_modify = request.form.get("username_to_modify")
            user = user_repo.get_user(username_to_modify or "")
            if not username_to_modify or not user:
                flash("Benutzer nicht gefunden.", "error")
            elif action == "grant_admin":
                if user["is_admin"]:
                    flash(f"Benutzer '{username_to_modify}' ist bereits Admin.", "warning")
                else:
                    user_repo.set_admin(username_to_modify, True)
                    flash(f"'{username_to_modify}' wurden Admin-Rechte erteilt.", "success")
            elif action == "revoke_admin":
                if username_to_modify == current_admin:
                    flash("Du kannst dir nicht selbst die Admin-Rechte entziehen.", "error")
                elif not user["is_admin"]:
                    flash(f"Benutzer '{username_to_modify}' ist kein Admin.", "warning")
                elif user_repo.count_admins() <= 1:
                    flash("Dem letzten Administrator können die Rechte nicht entzogen werden.", "error")
                else:
                    user_repo.set_admin(username_to_modify, False)
                    flash(f"'{username_to_modify}' wurden die Admin-Rechte entzogen.", "success")
            else:
                user_repo.reset_password(username_to_modify)
                flash(
                    f"Passwort für '{username_to_modify}' wurde zurückgesetzt. Der Benutzer muss beim nächsten Login ein neues Passwort festlegen.",
                    "success",
                )

        return redirect(url_for("manage_users"))

    users = user_repo.list_users()
    users_list = [
        {"username": username, "is_admin": data.get("is_admin", False)}
        for username, data in users.items()
        if username != current_admin
    ]
    return render_template("manage_users.html", users_list=users_list)


@socketio.on("connect")
def handle_connect():
    username = current_user()
    if not username:
        return False

    if not game.active:
        return

    sid = request.sid
    if username == game.mr_x and game.mrx_disconnect_task_pending:
        game.mrx_disconnect_task_pending = False

    existing = game.players.get(username)
    if not existing:
        game.players[username] = PlayerState(
            sid=sid,
            remaining_invisibility=game.seeker_invisibility_uses,
        )
    else:
        existing.sid = sid

    if username != game.mr_x:
        join_room(SEEKERS_CHAT_ROOM, sid=sid)

    current_locations: dict[str, dict[str, float]] = {}
    for player_name, player in game.players.items():
        is_invisible = bool(player.invisible_until and player.invisible_until > time.time())
        if is_invisible and player_name != username:
            continue

        if player_name == game.mr_x and game.mr_x_last_known_location:
            current_locations[player_name] = {
                "lat": game.mr_x_last_known_location["lat"],
                "lon": game.mr_x_last_known_location["lon"],
            }
        elif player.last_location and player_name != game.mr_x:
            current_locations[player_name] = {
                "lat": player.last_location["lat"],
                "lon": player.last_location["lon"],
            }

    player_state = game.players[username]
    emit(
        "game_update",
        {
            "mr_x": game.mr_x,
            "locations": current_locations,
            "players": list(game.players.keys()),
            "mrx_remaining_decoys": game.mrx_remaining_decoys if username == game.mr_x else None,
            "seeker_remaining_invisibility": player_state.remaining_invisibility
            if username != game.mr_x
            else None,
            "mrx_update_interval_minutes": game.update_interval_minutes,
            "mrx_last_broadcast_time": game.mr_x_last_broadcast_time,
        },
    )
    socketio.emit("player_joined", {"username": username}, skip_sid=sid)


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    disconnecting_user = None

    for username, player in game.players.items():
        if player.sid == sid:
            disconnecting_user = username
            break

    if not disconnecting_user:
        return

    if disconnecting_user != game.mr_x:
        leave_room(SEEKERS_CHAT_ROOM, sid=sid)

    if disconnecting_user == game.mr_x:
        if not game.mrx_disconnect_task_pending:
            game.mrx_disconnect_task_pending = True
            socketio.start_background_task(
                target=end_game_due_to_mrx_disconnect_wrapper,
                grace_period=MRX_DISCONNECT_GRACE_PERIOD_SECONDS,
            )
            socketio.emit("player_invisible", {"username": disconnecting_user})
    else:
        del game.players[disconnecting_user]
        socketio.emit("player_left", {"username": disconnecting_user})


@socketio.on("update_location")
def handle_location_update(data):
    username = current_user()
    if not username or not game.active:
        return

    player = game.players.get(username)
    if not player:
        return

    lat = data.get("lat")
    lon = data.get("lon")
    if lat is None or lon is None:
        return

    player.last_location = {"lat": lat, "lon": lon}

    if username == game.mr_x:
        now = time.time()
        game.mr_x_last_known_location = {"lat": lat, "lon": lon}
        interval_seconds = game.update_interval_minutes * 60
        if now - game.mr_x_last_broadcast_time < interval_seconds:
            return

        announce_previous_decoy = False
        if game.mrx_pending_decoy_location:
            location_to_send = game.mrx_pending_decoy_location
            game.mrx_pending_decoy_location = None
            game.mrx_last_update_was_decoy = True
        else:
            location_to_send = game.mr_x_last_known_location
            if game.mrx_last_update_was_decoy:
                announce_previous_decoy = True
            game.mrx_last_update_was_decoy = False

        socketio.emit(
            "location_update",
            {
                "username": username,
                "lat": location_to_send["lat"],
                "lon": location_to_send["lon"],
                "previous_was_decoy": announce_previous_decoy,
            },
        )
        game.mr_x_last_broadcast_time = now
        socketio.emit("mrx_update_timer", {"last_broadcast_time": now})
        return

    if player.invisible_until and player.invisible_until > time.time():
        return

    socketio.emit(
        "location_update",
        {"username": username, "lat": lat, "lon": lon},
        skip_sid=request.sid,
    )


@socketio.on("set_decoy_location")
def handle_set_decoy_location(data):
    username = current_user()
    if not username or not game.active or username != game.mr_x:
        return

    if game.mrx_remaining_decoys <= 0:
        emit("error_message", {"message": "Keine Ablenkungsmanöver mehr verfügbar!"})
        return

    lat = data.get("lat")
    lon = data.get("lon")
    if lat is None or lon is None:
        emit("error_message", {"message": "Ungültige Koordinaten für Ablenkungsmanöver."})
        return

    game.mrx_pending_decoy_location = {"lat": lat, "lon": lon}
    game.mrx_remaining_decoys -= 1
    emit(
        "decoy_set_confirmation",
        {"lat": lat, "lon": lon, "remaining_decoys": game.mrx_remaining_decoys},
    )


@socketio.on("activate_invisibility")
def handle_activate_invisibility():
    username = current_user()
    if not username or not game.active or username == game.mr_x:
        return

    player = game.players.get(username)
    if not player:
        return

    if player.invisible_until and player.invisible_until > time.time():
        emit("error_message", {"message": "Du bist bereits unsichtbar!"})
        return

    if player.remaining_invisibility <= 0:
        emit("error_message", {"message": "Keine Unsichtbarkeits-Nutzungen mehr verfügbar!"})
        return

    player.remaining_invisibility -= 1
    duration = game.seeker_invisibility_duration_seconds
    expiration = time.time() + duration
    player.invisible_until = expiration

    emit(
        "invisibility_activated",
        {"duration": duration, "remaining_uses": player.remaining_invisibility},
    )
    socketio.emit("player_invisible", {"username": username}, skip_sid=request.sid)
    socketio.start_background_task(
        target=make_visible_again_wrapper,
        username=username,
        expected_expiration=expiration,
        duration=duration,
    )


@socketio.on("send_chat_message")
def handle_send_chat_message(data):
    username = current_user()
    if not username or not game.active:
        return
    if username == game.mr_x or username not in game.players:
        return

    message_text = (data.get("message") or "").strip()
    if not message_text:
        return

    max_len = 200
    if len(message_text) > max_len:
        message_text = message_text[:max_len] + "..."

    socketio.emit(
        "new_chat_message",
        {"username": username, "message": message_text},
        room=SEEKERS_CHAT_ROOM,
    )


@socketio.on("mr_x_found")
def handle_mr_x_found(data):
    username = current_user()
    if not game.active or not username or username != game.mr_x:
        return

    finder = data.get("finder")
    if not finder or finder not in game.players:
        emit("error_message", {"message": f"Ungültiger Finder '{finder}' ausgewählt."})
        return

    socketio.emit(
        "game_over",
        {
            "message": f"Mr. X ({game.mr_x}) wurde von {finder} gefunden!",
            "finder": finder,
            "mr_x": game.mr_x,
        },
    )
    reset_game_state(notify_clients=False)


if __name__ == "__main__":
    port = 1432
    host = "0.0.0.0"
    try:
        socketio.run(app, host=host, port=port, debug=True)
    except ImportError:
        socketio.run(app, host=host, port=port, debug=True, allow_unsafe_werkzeug=True)
