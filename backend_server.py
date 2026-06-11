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
from datetime import date
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("DB_PATH", str(ROOT / "data" / "worldcup.db")))
PREDICTIONS_PATH = ROOT / "outputs" / "tournament_predictions.json"
WEB_ROOT = ROOT / "web"
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
LIVE_DATA_PROVIDER = os.environ.get("LIVE_DATA_PROVIDER", "football-data").strip().lower()
FOOTBALL_DATA_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "")
FOOTBALL_DATA_COMPETITION = os.environ.get("FOOTBALL_DATA_COMPETITION", "WC")
LIVE_CACHE_SECONDS = int(os.environ.get("LIVE_CACHE_SECONDS", "60"))
RATE_BUCKETS: dict[tuple[str, str], list[float]] = {}
RATE_LIMITS = {
    "GET": (120, 60),
    "/api/users": (5, 60),
    "/api/picks": (120, 60),
    "/api/live": (60, 60),
    "/api/results": (30, 60),
}
UPDATE_STATE = {
    "mode": "starting",
    "interval_seconds": None,
    "last_started_at": None,
    "last_finished_at": None,
    "last_error": None,
}
LIVE_STATE = {
    "provider": LIVE_DATA_PROVIDER or "none",
    "connected": False,
    "last_checked_at": None,
    "last_error": None,
    "matches": [],
}
LIVE_CACHE = {"expires_at": 0.0, "payload": None}


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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS live_overrides (
                match_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                minute INTEGER,
                injury_time INTEGER,
                home_score INTEGER,
                away_score INTEGER,
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
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
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Token")
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


def utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def normalize_team_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def match_key(date_value: str, home: str, away: str) -> str:
    return "|".join([date_value, normalize_team_name(home), normalize_team_name(away)])


def predicted_match_index() -> dict[str, str]:
    index = {}
    for match in load_predictions().get("matches", []):
        index[match_key(match["date"], match["home"], match["away"])] = match["id"]
    return index


def predictions_by_id() -> dict[str, dict]:
    return {match["id"]: match for match in load_predictions().get("matches", [])}


def fetch_json(url: str, headers: dict[str, str], timeout: int = 12) -> dict:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def score_value(match: dict, side: str) -> int | None:
    score = match.get("score") or {}
    full_time = score.get("fullTime") or {}
    regular_time = score.get("regularTime") or {}
    half_time = score.get("halfTime") or {}
    for node in (full_time, regular_time, half_time):
        value = node.get(side)
        if value is not None:
            return value
    return None


def map_football_data_match(match: dict, match_ids: dict[str, str]) -> dict:
    utc_date = match.get("utcDate") or ""
    match_date = utc_date[:10] if utc_date else ""
    home = (match.get("homeTeam") or {}).get("name") or ""
    away = (match.get("awayTeam") or {}).get("name") or ""
    match_id = match_ids.get(match_key(match_date, home, away))
    return {
        "id": match_id,
        "provider_id": match.get("id"),
        "date": match_date,
        "utc_date": utc_date,
        "home": home,
        "away": away,
        "status": match.get("status") or "UNKNOWN",
        "minute": match.get("minute"),
        "injury_time": match.get("injuryTime"),
        "venue": match.get("venue"),
        "home_score": score_value(match, "home"),
        "away_score": score_value(match, "away"),
        "last_updated": match.get("lastUpdated"),
    }


def manual_live_matches() -> list[dict]:
    predictions = predictions_by_id()
    with db() as conn:
        rows = conn.execute(
            """
            SELECT match_id, status, minute, injury_time, home_score, away_score, note, updated_at
            FROM live_overrides
            ORDER BY updated_at DESC
            """
        ).fetchall()
    matches = []
    for row in rows:
        predicted = predictions.get(row["match_id"])
        if not predicted:
            continue
        matches.append(
            {
                "id": row["match_id"],
                "provider_id": f"manual:{row['match_id']}",
                "date": predicted["date"],
                "utc_date": predicted.get("lock_at"),
                "home": predicted["home"],
                "away": predicted["away"],
                "status": row["status"],
                "minute": row["minute"],
                "injury_time": row["injury_time"],
                "venue": predicted.get("city"),
                "home_score": row["home_score"],
                "away_score": row["away_score"],
                "last_updated": row["updated_at"],
                "note": row["note"],
                "source": "manual",
            }
        )
    return matches


def merge_live_matches(provider_matches: list[dict], manual_matches: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    anonymous = []
    for match in provider_matches:
        if match.get("id"):
            merged[match["id"]] = match
        else:
            anonymous.append(match)
    for match in manual_matches:
        merged[match["id"]] = match
    return list(merged.values()) + anonymous


def football_data_url() -> str:
    today = date.today().isoformat()
    query = urlencode(
        {
            "competitions": FOOTBALL_DATA_COMPETITION,
            "dateFrom": today,
            "dateTo": (date.today() + timedelta(days=1)).isoformat(),
        }
    )
    return f"https://api.football-data.org/v4/matches?{query}"


def load_live_matches(force: bool = False) -> dict:
    now = time.monotonic()
    if not force and LIVE_CACHE["payload"] and now < LIVE_CACHE["expires_at"]:
        return LIVE_CACHE["payload"]

    LIVE_STATE["provider"] = LIVE_DATA_PROVIDER or "none"
    LIVE_STATE["last_checked_at"] = utc_now_iso()
    manual_matches = manual_live_matches()

    if LIVE_DATA_PROVIDER not in {"football-data", "footballdata"}:
        payload = {
            **LIVE_STATE,
            "connected": bool(manual_matches),
            "last_error": "LIVE_DATA_PROVIDER is not configured",
            "matches": manual_matches,
            "source": "manual" if manual_matches else None,
        }
    elif not FOOTBALL_DATA_TOKEN:
        payload = {
            **LIVE_STATE,
            "connected": bool(manual_matches),
            "last_error": "FOOTBALL_DATA_TOKEN is not configured",
            "matches": manual_matches,
            "source": "manual" if manual_matches else None,
        }
    else:
        try:
            headers = {
                "X-Auth-Token": FOOTBALL_DATA_TOKEN,
                "X-Unfold-Goals": "true",
                "X-Unfold-Bookings": "true",
                "User-Agent": "WorldCup2026Predictor/0.1",
            }
            raw = fetch_json(football_data_url(), headers)
            match_ids = predicted_match_index()
            live_matches = [map_football_data_match(match, match_ids) for match in raw.get("matches", [])]
            merged_matches = merge_live_matches(live_matches, manual_matches)
            payload = {
                "provider": LIVE_DATA_PROVIDER,
                "connected": True,
                "last_checked_at": LIVE_STATE["last_checked_at"],
                "last_error": None,
                "matches": merged_matches,
                "source": "football-data.org" + (" + manual" if manual_matches else ""),
            }
        except Exception as exc:
            payload = {
                **LIVE_STATE,
                "connected": bool(manual_matches),
                "last_error": str(exc),
                "matches": manual_matches,
                "source": "manual" if manual_matches else None,
            }

    LIVE_STATE.update(payload)
    LIVE_CACHE["payload"] = payload
    LIVE_CACHE["expires_at"] = now + LIVE_CACHE_SECONDS
    return payload


def clear_live_cache() -> None:
    LIVE_CACHE["payload"] = None
    LIVE_CACHE["expires_at"] = 0.0


def save_live_override(payload: dict) -> dict:
    match_id = str(payload["match_id"])
    predicted = match_by_id(match_id)
    if not predicted:
        raise ValueError("Unknown match")
    status = str(payload.get("status", "IN_PLAY")).upper()
    allowed = {
        "SCHEDULED",
        "TIMED",
        "IN_PLAY",
        "PAUSED",
        "EXTRA_TIME",
        "PENALTY_SHOOTOUT",
        "FINISHED",
        "SUSPENDED",
        "POSTPONED",
        "CANCELLED",
        "AWARDED",
    }
    if status not in allowed:
        raise ValueError("Invalid live status")
    minute = payload.get("minute")
    injury_time = payload.get("injury_time")
    home_score = payload.get("home_score")
    away_score = payload.get("away_score")
    note = str(payload.get("note", ""))[:160]
    updated_at = utc_now_iso()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO live_overrides (match_id, status, minute, injury_time, home_score, away_score, note, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id)
            DO UPDATE SET
              status = excluded.status,
              minute = excluded.minute,
              injury_time = excluded.injury_time,
              home_score = excluded.home_score,
              away_score = excluded.away_score,
              note = excluded.note,
              updated_at = excluded.updated_at
            """,
            (match_id, status, minute, injury_time, home_score, away_score, note, updated_at),
        )
    clear_live_cache()
    return load_live_matches(force=True)


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
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Token")
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
            json_response(self, {**UPDATE_STATE, "live": load_live_matches()})
            return
        if path == "/api/live":
            json_response(self, load_live_matches())
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
            if path == "/api/live":
                require_admin(self, payload)
                json_response(self, {"ok": True, "live": save_live_override(payload)})
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
