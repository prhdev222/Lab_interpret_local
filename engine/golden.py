"""Golden cases: example notes (SYNTHETIC only, never real patients) used as a safety net when thresholds or rules are edited.

Before a change is written, every case is interpreted with the current settings and with the proposed ones, and the differences are
shown to the doctor ("HbA1c 7.4: 'slightly above target' -> 'in target'"). A case the doctor has confirmed keeps the confirmed result,
so a later change to it is called out explicitly. This is a regression check, not proof of clinical correctness: the doctor decides.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .lexicon import DATA_DIR
from .parse_note import parse_note
from .render import finding_line, render_clinician
from .rules import evaluate

PATH = os.path.join(DATA_DIR, "golden_cases.json")
MAX_CASES, MAX_NOTE = 200, 2000


def load(path: str | None = None) -> list[dict[str, Any]]:
    try:
        with open(path or PATH, encoding="utf-8") as f:
            d = json.load(f)
        return [c for c in d.get("cases", []) if isinstance(c, dict) and isinstance(c.get("note"), str)]
    except (OSError, ValueError, AttributeError):
        return []


def save(cases: list[dict[str, Any]], path: str | None = None) -> None:
    path = path or PATH
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"_meta": {"note": "ตัวอย่างบันทึกสังเคราะห์ ห้ามใส่ข้อมูลผู้ป่วยจริง ใช้ตรวจว่าการแก้เกณฑ์/กฎทำให้ผลเปลี่ยนตรงไหน"}, "cases": cases}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def snapshot(case: dict[str, Any], **eval_kw: Any) -> dict[str, Any]:
    """What the engine says for this case: findings as (key, level) with the short sentence, and the doctor-only note keys."""
    res = evaluate(parse_note(case["note"]), {"age": case.get("age"), "sex": case.get("sex"), "tcvr": case.get("tcvr")}, **eval_kw)
    items = {f"{f['id']}|{f['key']}": {"level": f["level"], "text": finding_line(f, "short")} for f in res["findings"]}
    notes = sorted(f"{n['id']}|{n['key']}" for n in res["clinician_notes"])
    return {"findings": items, "notes": notes}


def diff_snapshots(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] | None:
    removed = [{"key": k, **v} for k, v in a["findings"].items() if k not in b["findings"] or b["findings"][k]["level"] != v["level"]]
    added = [{"key": k, **v} for k, v in b["findings"].items() if k not in a["findings"] or a["findings"][k]["level"] != v["level"]]
    notes_removed = [k for k in a["notes"] if k not in b["notes"]]
    notes_added = [k for k in b["notes"] if k not in a["notes"]]
    if not (removed or added or notes_removed or notes_added):
        return None
    return {"removed": removed, "added": added, "notes_removed": notes_removed, "notes_added": notes_added}


def compare(before: dict[str, Any], after: dict[str, Any], cases: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """before/after are keyword args for evaluate() (targets=..., custom_override=...). -> one entry per case whose result changes."""
    out = []
    for c in cases if cases is not None else load():
        try:
            d = diff_snapshots(snapshot(c, **before), snapshot(c, **after))
        except Exception as e:                                   # a proposed setting that breaks a case is itself a finding
            d = {"removed": [], "added": [], "notes_removed": [], "notes_added": [], "error": f"{type(e).__name__}"}
        if d:
            out.append({"id": c.get("id", "?"), "note": c["note"], "confirmed": bool(c.get("confirmed")), **d})
    return out


def approved_violations(after: dict[str, Any], cases: list[dict[str, Any]] | None = None) -> list[str]:
    """Confirmed cases whose result under the proposed settings differs from what the doctor confirmed."""
    bad = []
    for c in cases if cases is not None else load():
        if c.get("confirmed") and isinstance(c.get("approved"), dict):
            if diff_snapshots(c["approved"], snapshot(c, **after)):
                bad.append(c.get("id", "?"))
    return bad


def validate_new(note: Any, age: Any, sex: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(note, str) or not note.strip():
        return None, "กรุณาใส่บันทึกตัวอย่าง"
    if len(note) > MAX_NOTE:
        return None, f"บันทึกยาวเกิน {MAX_NOTE} ตัวอักษร"
    case: dict[str, Any] = {"note": note.strip()}
    if age not in (None, ""):
        try:
            a = float(age)
        except (TypeError, ValueError):
            return None, "อายุไม่ถูกต้อง"
        if not 0 < a < 125:
            return None, "อายุไม่ถูกต้อง"
        case["age"] = a
    if sex not in (None, "", "M", "F"):
        return None, "เพศต้องเป็น M หรือ F"
    if sex in ("M", "F"):
        case["sex"] = sex
    return case, None


def next_id(cases: list[dict[str, Any]]) -> str:
    nums = [int(m.group(1)) for c in cases for m in [re.fullmatch(r"g-(\d+)", str(c.get("id", "")))] if m]
    return f"g-{max(nums, default=0) + 1}"
