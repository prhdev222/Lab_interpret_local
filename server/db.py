"""Tiny SQLite layer: users, sessions, usage counters. It never stores a note, a lab value or anything about a patient."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time

PBKDF2_ITER = 200_000
SESSION_HOURS = 8
MAX_FAILS, LOCK_SECONDS = 5, 300
MIN_PIN = 6


def hash_pin(pin: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, PBKDF2_ITER).hex()


class DB:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.con = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        if path != ":memory:":
            os.chmod(path, 0o600)
        self.con.executescript("""
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, salt BLOB NOT NULL, pin_hash TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'staff', display_name TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0,
              fails INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0, created_at TEXT DEFAULT (datetime('now')));
            CREATE TABLE IF NOT EXISTS sessions (
              token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS tagger_feedback (
              id INTEGER PRIMARY KEY AUTOINCREMENT, param TEXT NOT NULL, accepted INTEGER NOT NULL, conf_band TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')));
            CREATE TABLE IF NOT EXISTS usage_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, pattern TEXT, monk_mode INTEGER, created_at TEXT DEFAULT (datetime('now')));
        """)

    # ---- users
    def user_count(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def add_user(self, username: str, pin: str, display_name: str, role: str = "staff", is_admin: bool = False) -> None:
        if len(pin) < MIN_PIN:
            raise ValueError(f"PIN ต้องอย่างน้อย {MIN_PIN} หลัก")
        salt = secrets.token_bytes(16)
        try:
            with self.lock:
                self.con.execute("INSERT INTO users (username, salt, pin_hash, role, display_name, is_admin) VALUES (?,?,?,?,?,?)",
                                 (username, salt, hash_pin(pin, salt), role, display_name, int(is_admin)))
        except sqlite3.IntegrityError:
            raise ValueError("ชื่อผู้ใช้ซ้ำ")

    def set_pin(self, user_id: int, pin: str) -> None:
        if len(pin) < MIN_PIN:
            raise ValueError(f"PIN ต้องอย่างน้อย {MIN_PIN} หลัก")
        salt = secrets.token_bytes(16)
        with self.lock:
            self.con.execute("UPDATE users SET salt=?, pin_hash=?, fails=0, locked_until=0 WHERE id=?", (salt, hash_pin(pin, salt), user_id))
            self.con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    def check_pin(self, user_id: int, pin: str) -> bool:
        row = self.con.execute("SELECT salt, pin_hash FROM users WHERE id=?", (user_id,)).fetchone()
        return bool(row) and hmac.compare_digest(hash_pin(pin, row["salt"]), row["pin_hash"])

    def list_users(self) -> list[dict]:
        return [dict(r) for r in self.con.execute("SELECT id, username, role, display_name, is_admin, created_at FROM users ORDER BY id")]

    def delete_user(self, user_id: int) -> None:
        with self.lock:
            self.con.execute("DELETE FROM sessions WHERE user_id=? AND user_id IN (SELECT id FROM users WHERE is_admin=0)", (user_id,))
            self.con.execute("DELETE FROM users WHERE id=? AND is_admin=0", (user_id,))

    # ---- login with lockout (the same message for unknown user and wrong PIN, so usernames cannot be probed)
    def login(self, username: str, pin: str) -> tuple[str | None, dict | None, str]:
        now = time.time()
        row = self.con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if row is None:
            hash_pin(pin, b"x" * 16)                                   # same work as a real check: no timing difference
            return None, None, "ชื่อผู้ใช้หรือ PIN ไม่ถูกต้อง"
        if row["locked_until"] > now:
            return None, None, f"ใส่ PIN ผิดหลายครั้ง ถูกล็อกชั่วคราว รออีก {int(row['locked_until'] - now) // 60 + 1} นาที"
        if not hmac.compare_digest(hash_pin(pin, row["salt"]), row["pin_hash"]):
            fails = row["fails"] + 1
            with self.lock:
                if fails >= MAX_FAILS:
                    self.con.execute("UPDATE users SET fails=0, locked_until=? WHERE id=?", (now + LOCK_SECONDS, row["id"]))
                else:
                    self.con.execute("UPDATE users SET fails=? WHERE id=?", (fails, row["id"]))
            return None, None, "ชื่อผู้ใช้หรือ PIN ไม่ถูกต้อง"
        token = secrets.token_hex(32)
        with self.lock:
            self.con.execute("UPDATE users SET fails=0, locked_until=0 WHERE id=?", (row["id"],))
            self.con.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            self.con.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?,?,?)",
                             (hashlib.sha256(token.encode()).hexdigest(), row["id"], now + SESSION_HOURS * 3600))
        return token, {"username": row["username"], "role": row["role"], "displayName": row["display_name"], "isAdmin": bool(row["is_admin"]), "id": row["id"]}, ""

    def session_user(self, token: str) -> dict | None:
        if not token:
            return None
        row = self.con.execute(
            "SELECT u.id, u.username, u.role, u.display_name, u.is_admin FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token_hash=? AND s.expires_at>?", (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return None if row is None else {"id": row["id"], "username": row["username"], "role": row["role"], "displayName": row["display_name"], "isAdmin": bool(row["is_admin"])}

    def logout(self, token: str) -> None:
        with self.lock:
            self.con.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def clear_sessions(self, keep_token: str) -> None:
        with self.lock:
            self.con.execute("DELETE FROM sessions WHERE token_hash != ?", (hashlib.sha256(keep_token.encode()).hexdigest(),))

    # ---- usage counters only (user, pattern, monk flag, time)
    def log_use(self, user_id: int, pattern: str, monk: bool) -> None:
        with self.lock:
            self.con.execute("INSERT INTO usage_log (user_id, pattern, monk_mode) VALUES (?,?,?)", (user_id, pattern, int(monk)))
            self.con.execute("DELETE FROM usage_log WHERE created_at < datetime('now','-30 days')")

    # ---- doctor's answer to a tagger suggestion: parameter + yes/no + confidence band only (never the note, the name or the values)
    @staticmethod
    def _band(conf: float) -> str:
        return ">=0.95" if conf >= 0.95 else "0.8-0.95" if conf >= 0.8 else "<0.8"

    def log_tagger(self, param: str, accepted: bool, conf: float) -> None:
        with self.lock:
            self.con.execute("INSERT INTO tagger_feedback (param, accepted, conf_band) VALUES (?,?,?)", (param, int(accepted), self._band(conf)))

    def tagger_stats(self) -> dict:
        q = self.con.execute
        rows = [dict(r) for r in q("SELECT conf_band AS band, SUM(accepted) AS accepted, COUNT(*) - SUM(accepted) AS rejected FROM tagger_feedback GROUP BY conf_band ORDER BY band")]
        per = [dict(r) for r in q("SELECT param, SUM(accepted) AS accepted, COUNT(*) - SUM(accepted) AS rejected FROM tagger_feedback GROUP BY param ORDER BY param")]
        return {"byBand": rows, "byParam": per, "total": q("SELECT COUNT(*) FROM tagger_feedback").fetchone()[0]}

    def clear_logs(self) -> None:
        with self.lock:
            self.con.execute("DELETE FROM usage_log")

    def stats(self) -> dict:
        q = self.con.execute
        return {
            "daily": [dict(r) for r in q("SELECT date(created_at) AS day, COUNT(*) AS count FROM usage_log WHERE created_at >= datetime('now','-7 days') GROUP BY day ORDER BY day DESC")],
            "perUser": [dict(r) for r in q("SELECT u.display_name, u.username, COUNT(l.id) AS count FROM usage_log l JOIN users u ON u.id=l.user_id WHERE l.created_at >= datetime('now','-30 days') GROUP BY l.user_id ORDER BY count DESC")],
            "perPattern": [dict(r) for r in q("SELECT pattern, COUNT(*) AS count FROM usage_log WHERE created_at >= datetime('now','-30 days') GROUP BY pattern ORDER BY count DESC")],
            "activeSessions": q("SELECT COUNT(*) FROM sessions WHERE expires_at >= ?", (time.time(),)).fetchone()[0],
            "totalLogs": q("SELECT COUNT(*) FROM usage_log").fetchone()[0],
            "tagger": self.tagger_stats(),
        }
