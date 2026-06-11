from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("DB_PATH", str(ROOT / "data" / "worldcup.db")))
PREDICTIONS_PATH = ROOT / "outputs" / "tournament_predictions.json"
WEB_ROOT = ROOT / "web"
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
RATE_BUCKETS: dict[tuple[str, str], list[float]] = {}
RATE_LIMITS = {
    "GET": (120, 60),
    "/api/users": (5, 60),
    "/api/picks": (120, 60),
    "/api/results": (30, 60),
}
UPDATE_STATE = {
    "mode": "starting",
    "interval_seconds": None,
    "last_started_at": None,
    "last_finished_at": None,
    "last_error": None,
}


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT NOT NULL UNIQUE,
                token TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "token" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN token TEXT NOT NULL DEFAULT ''")
        empty_token_rows = conn.execute("SELECT id FROM users WHERE token = ''").fetchall()
        for row in empty_token_rows:
            conn.execute("UPDATE users SET token = ? WHERE id = ?", (secrets.token_urlsafe(32), row["id"]))
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_token_idx ON users(token)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS picks (
                user_id INTEGER NOT NULL,
                match_id TEXT NOT NULL,
                pick TEXT NOT NULL CHECK (pick IN ('home', 'draw', 'away')),
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, match_id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS results (
                match_id TEXT PRIMARY KEY,
                outcome TEXT NOT NULL CHECK (outcome IN ('home', 'draw', 'away')),
                home_score INTEGER,
                away_score INTEGER,
                finalized_at TEXT NOT NULL
            )
            """
        )


def json_response(handler: SimpleHTTPRequestHandler, payload: object, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(body)


def read_json_body(handler: SimpleHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if length == 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def client_ip(handler: SimpleHTTPRequestHandler) -> str:
    forwarded = handler.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return handler.client_address[0]


def check_rate_limit(handler: SimpleHTTPRequestHandler, key: str) -> None:
    limit, window = RATE_LIMITS.get(key, RATE_LIMITS["GET"])
    now = time.monotonic()
    bucket_key = (client_ip(handler), key)
    bucket = [stamp for stamp in RATE_BUCKETS.get(bucket_key, []) if now - stamp < window]
    if len(bucket) >= limit:
        RATE_BUCKETS[bucket_key] = bucket
        raise ValueError("Rate limit exceeded")
    bucket.append(now)
    RATE_BUCKETS[bucket_key] = bucket


def load_predictions() -> dict:
    return json.loads(PREDICTIONS_PATH.read_text(encoding="utf-8"))


def public_user(row: sqlite3.Row | dict) -> dict:
    return {
        "id": int(row["id"]),
        "nickname": row["nickname"],
        "token": row["token"],
        "created_at": row["created_at"],
    }


def clean_nickname(raw: str) -> str:
    nickname = " ".join(str(raw).strip().split())
    nickname = re.sub(r"[^\w\u4e00-\u9fff\- ]", "", nickname, flags=re.UNICODE)
    nickname = nickname[:20]
    if not nickname:
        raise ValueError("Nickname is required")
    return nickname


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def match_by_id(match_id: str) -> dict | None:
    for match in load_predictions().get("matches", []):
        if match.get("id") == match_id:
            return match
    return None


def is_pick_locked(match_id: str) -> bool:
    match = match_by_id(match_id)
    if not match:
        raise ValueError("Unknown match")
    lock_at = match.get("lock_at")
    if not lock_at:
        return False
    return datetime.utcnow() >= parse_utc(lock_at)


def current_update_interval() -> tuple[str, int]:
    """MVP schedule policy.

    Without a paid live-event feed, the server uses the fixture dates in the
    model output. This gives us the right cadence shell now; data adapters can
    later make mode detection exact with kickoff/status values.
    """
    now = datetime.utcnow()
    try:
        matches = load_predictions().get("matches", [])
    except Exception:
        return "fallback", 3600

    today = now.date().isoformat()
    has_today_match = any(match["date"] == today for match in matches)
    future_dates = [datetime.fromisoformat(match["date"]) for match in matches if match["date"] >= today]
    next_match = min(future_dates) if future_dates else None

    if has_today_match:
        return "matchday_full_model", 300
    if next_match and next_match - now <= timedelta(hours=24):
        return "pre_match_24h", 3600
    return "normal_pre_match", 10800


def refresh_predictions() -> None:
    UPDATE_STATE["last_started_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    UPDATE_STATE["last_error"] = None
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "refresh_data.py")],
        cwd=ROOT,
        check=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    UPDATE_STATE["last_finished_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"


def update_loop() -> None:
    while True:
        mode, interval = current_update_interval()
        UPDATE_STATE["mode"] = mode
        UPDATE_STATE["interval_seconds"] = interval
        try:
            refresh_predictions()
        except Exception as exc:
            UPDATE_STATE["last_error"] = str(exc)
        time.sleep(interval)


def start_updater() -> None:
    if os.environ.get("DISABLE_UPDATER") == "1":
        UPDATE_STATE["mode"] = "disabled"
        return
    thread = threading.Thread(target=update_loop, daemon=True)
    thread.start()


def get_or_create_user(nickname: str) -> dict:
    nickname = clean_nickname(nickname)
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE nickname = ?", (nickname,)).fetchone()
        if row:
            if not row["token"]:
                token = secrets.token_urlsafe(32)
                conn.execute("UPDATE users SET token = ? WHERE id = ?", (token, row["id"]))
                row = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
            return public_user(row)
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO users (nickname, token, created_at) VALUES (?, ?, ?)", (nickname, token, now))
        row = conn.execute("SELECT * FROM users WHERE nickname = ?", (nickname,)).fetchone()
        return public_user(row)


def verify_user(user_id: int, token: str) -> None:
    with db() as conn:
        row = conn.execute("SELECT token FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or not token or not secrets.compare_digest(row["token"], token):
        raise ValueError("Invalid user token")


def leaderboard() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
              u.id,
              u.nickname,
              COUNT(p.match_id) AS picks,
              COALESCE(SUM(CASE WHEN r.outcome IS NOT NULL AND p.pick = r.outcome THEN 1 ELSE 0 END), 0) AS correct,
              COALESCE(SUM(CASE WHEN r.outcome IS NOT NULL THEN 1 ELSE 0 END), 0) AS graded
            FROM users u
            LEFT JOIN picks p ON p.user_id = u.id
            LEFT JOIN results r ON r.match_id = p.match_id
            GROUP BY u.id
            ORDER BY correct DESC, graded DESC, picks DESC, u.created_at ASC
            LIMIT 50
            """
        ).fetchall()
    return [dict(row) | {"score": int(row["correct"]) * 3} for row in rows]


def require_admin(handler: SimpleHTTPRequestHandler, payload: dict) -> None:
    token = handler.headers.get("X-Admin-Token") or payload.get("admin_token", "")
    if not ADMIN_TOKEN or not token or not secrets.compare_digest(ADMIN_TOKEN, str(token)):
        raise ValueError("Invalid admin token")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            check_rate_limit(self, "GET")
        except ValueError as exc:
            json_response(self, {"error": str(exc)}, status=429)
            return
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/index.html")
            self.end_headers()
            return
        if path == "/api/tournament":
            json_response(self, load_predictions())
            return
        if path == "/api/leaderboard":
            json_response(self, {"leaderboard": leaderboard()})
            return
        if path == "/api/update-status":
            json_response(self, UPDATE_STATE)
            return
        if path.startswith("/web/"):
            self.path = path.removeprefix("/web") or "/index.html"
            super().do_GET()
            return
        if path in {"/index.html", "/styles.css", "/app.js", "/data.js"}:
            self.path = path
            super().do_GET()
            return
        json_response(self, {"error": "Not found"}, status=404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            check_rate_limit(self, path)
            payload = read_json_body(self)
            if path == "/api/users":
                json_response(self, {"user": get_or_create_user(payload.get("nickname", ""))})
                return
            if path == "/api/picks":
                user_id = int(payload["user_id"])
                verify_user(user_id, str(payload.get("token", "")))
                match_id = str(payload["match_id"])
                if is_pick_locked(match_id):
                    raise ValueError("Picks are locked for this match")
                pick = str(payload["pick"])
                if pick not in {"home", "draw", "away"}:
                    raise ValueError("Invalid pick")
                now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                with db() as conn:
                    conn.execute(
                        """
                        INSERT INTO picks (user_id, match_id, pick, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(user_id, match_id)
                        DO UPDATE SET pick = excluded.pick, updated_at = excluded.updated_at
                        """,
                        (user_id, match_id, pick, now),
                    )
                json_response(self, {"ok": True})
                return
            if path == "/api/results":
                require_admin(self, payload)
                match_id = str(payload["match_id"])
                outcome = str(payload["outcome"])
                if outcome not in {"home", "draw", "away"}:
                    raise ValueError("Invalid outcome")
                home_score = payload.get("home_score")
                away_score = payload.get("away_score")
                now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                with db() as conn:
                    conn.execute(
                        """
                        INSERT INTO results (match_id, outcome, home_score, away_score, finalized_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(match_id)
                        DO UPDATE SET
                          outcome = excluded.outcome,
                          home_score = excluded.home_score,
                          away_score = excluded.away_score,
                          finalized_at = excluded.finalized_at
                        """,
                        (match_id, outcome, home_score, away_score, now),
                    )
                json_response(self, {"ok": True, "leaderboard": leaderboard()})
                return
            json_response(self, {"error": "Not found"}, status=404)
        except Exception as exc:
            status = 429 if str(exc) == "Rate limit exceeded" else 400
            json_response(self, {"error": str(exc)}, status=status)


def main() -> None:
    init_db()
    start_updater()
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Serving http://0.0.0.0:{port}/web/index.html")
    server.serve_forever()


if __name__ == "__main__":
    main()
