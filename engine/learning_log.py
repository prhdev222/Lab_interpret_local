"""Opt-in learning log: feature rows (see tools/learn_terms.extract_rows) kept in data/learning_log.json so abbreviations can be learned later.

OFF by default. Only an admin turns it on. A doctor saves an example per case by pressing a button (never automatic), after seeing exactly what
would be stored. No note text, age, sex, date, user name or note id is ever written; rows are inserted at RANDOM positions so the file's order
does not reveal which rows came from the same note. The file can be exported and cleared at any time. It is still patient-derived data:
get the hospital's DPO to approve before enabling it.
"""
from __future__ import annotations

import json
import os
import random
import threading
from typing import Any

from .lexicon import DATA_DIR

PATH = os.path.join(DATA_DIR, "learning_log.json")
MAX_ROWS = 20000
_lock = threading.Lock()


def _read(path: str | None = None) -> dict[str, Any]:
    try:
        with open(path or PATH, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("rows"), list):
            return {"enabled": bool(d.get("enabled")), "rows": d["rows"]}
    except (OSError, ValueError):
        pass
    return {"enabled": False, "rows": []}


def _write(d: dict[str, Any], path: str | None = None) -> None:
    path = path or PATH
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"enabled": d["enabled"], "rows": d["rows"]}, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def status() -> dict[str, Any]:
    d = _read()
    return {"enabled": d["enabled"], "rows": len(d["rows"]), "max": MAX_ROWS}


def set_enabled(on: bool) -> None:
    with _lock:
        d = _read(); d["enabled"] = bool(on); _write(d)


def add_rows(rows: list[dict[str, Any]]) -> int:
    """Inserts at random positions. Returns how many were stored (0 if the log is off or full)."""
    with _lock:
        d = _read()
        if not d["enabled"]:
            return 0
        room = MAX_ROWS - len(d["rows"])
        rng = random.SystemRandom()
        stored = 0
        for r in rows[: max(0, room)]:
            d["rows"].insert(rng.randint(0, len(d["rows"])), r); stored += 1
        _write(d)
        return stored


def export() -> dict[str, Any]:
    return _read()


def clear() -> None:
    with _lock:
        d = _read(); d["rows"] = []; _write(d)
