"""Physician sign-off. The system says "DRAFT" until a responsible admin signs; the signature is bound to the exact content that was reviewed.

A sign-off records who/when and a hash of the reviewed content (thresholds, wording, glossary, dictionary, custom rules). Any later change to
that content, from the web page or by hand, makes the status fall back to DRAFT ("edited after sign-off"): a signature can never silently cover
text the signer did not see. This is bookkeeping for the doctor's attestation; the system cannot judge clinical correctness itself.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from typing import Any

from .lexicon import DATA_DIR

PATH = os.path.join(DATA_DIR, "signoff.json")
PHRASE = "ลงนามรับรอง"
DRAFT_TEXT = "DRAFT — ยังไม่ผ่านการตรวจทานโดยแพทย์"
FILES = ["targets.json", "templates.json", "glossary.json", "lexicon.json", "custom_rules.json"]


def _canonical(name: str) -> str:
    try:
        with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return ""
    if isinstance(d, dict):
        d = {k: v for k, v in d.items() if k != "_meta"}                      # status/notes are not reviewed content
    return json.dumps(d, sort_keys=True, ensure_ascii=False)


def content_hash() -> str:
    h = hashlib.sha256()
    for name in FILES:
        h.update(name.encode()); h.update(_canonical(name).encode())
    return h.hexdigest()


def _read() -> dict[str, Any]:
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return {"signed": d.get("signed") if isinstance(d.get("signed"), dict) else None, "history": d.get("history") if isinstance(d.get("history"), list) else []}
    except (OSError, ValueError):
        pass
    return {"signed": None, "history": []}


def _write(d: dict[str, Any]) -> None:
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PATH)


def state() -> dict[str, Any]:
    d = _read()
    s = d["signed"]
    if not s:
        return {"signed": False, "edited_after": False, "by": None, "date": None}
    valid = s.get("hash") == content_hash()
    return {"signed": valid, "edited_after": not valid, "by": s.get("by"), "date": s.get("date")}


def effective_status(raw: str | None = None) -> str:
    st = state()
    if st["signed"]:
        return f"ตรวจรับรองแล้วโดย {st['by']} วันที่ {st['date']}"
    if st["edited_after"]:
        return f"DRAFT — มีการแก้ไขหลังลงนามเมื่อ {st['date']} ต้องตรวจรับรองใหม่"
    return raw if raw and "DRAFT" in raw else DRAFT_TEXT


def checklist() -> dict[str, Any]:
    """What still blocks a sign-off (empty lists = ready)."""
    from . import custom_rules, golden, targets_edit
    from .rules import RULES
    with open(targets_edit.PATH, encoding="utf-8") as f:
        t = json.load(f)
    leaves = targets_edit.leaves(t)
    unsourced = [p for p, k, v in leaves if k == "bool" and v is True]
    stale = [p for p, k, v in leaves if p.endswith(".source") and "ต้องระบุฉบับ" in str(v)
             and next((vv for pp, kk, vv in leaves if pp == p.rsplit(".", 1)[0] + ".needs_citation"), True) is False]
    cases = golden.load()
    unconfirmed = [c.get("id") for c in cases if not c.get("confirmed")]
    changed = [c.get("id") for c in cases if c.get("confirmed") and isinstance(c.get("approved"), dict) and golden.diff_snapshots(c["approved"], golden.snapshot(c))]
    try:
        with open(custom_rules.PATH, encoding="utf-8") as f:
            rules_errors = custom_rules.validate(json.load(f), {r["id"] for r in RULES})[1]
    except (OSError, ValueError):
        rules_errors = []
    return {"needs_citation": unsourced, "source_text_unchanged": stale, "no_examples": not cases, "unconfirmed_examples": unconfirmed,
            "examples_changed_since_confirmed": changed, "custom_rule_errors": rules_errors, "examples": len(cases)}


def blockers(c: dict[str, Any]) -> list[str]:
    out = []
    if c["needs_citation"]: out.append(f"ยังมีเกณฑ์ {len(c['needs_citation'])} กลุ่มที่ยังไม่ได้ระบุอ้างอิง (ติ๊ก 'ยังต้องระบุฉบับอ้างอิง' ออกหลังใส่ฉบับ): " + ", ".join(c["needs_citation"][:6]) + (" …" if len(c["needs_citation"]) > 6 else ""))
    if c["source_text_unchanged"]: out.append("ข้อความอ้างอิงยังเขียนว่า 'ต้องระบุฉบับ': " + ", ".join(c["source_text_unchanged"][:6]))
    if c["no_examples"]: out.append("ยังไม่มีบันทึกตัวอย่างในหน้า ✅ ตัวอย่าง")
    if c["unconfirmed_examples"]: out.append(f"ตัวอย่างที่แพทย์ยังไม่ยืนยันผล {len(c['unconfirmed_examples'])} ข้อ")
    if c["examples_changed_since_confirmed"]: out.append("ตัวอย่างที่ผลเปลี่ยนจากที่เคยยืนยัน: " + ", ".join(map(str, c["examples_changed_since_confirmed"])))
    if c["custom_rule_errors"]: out.append("กฎที่เพิ่มเองมีข้อผิดพลาด")
    return out


def sign(name: Any, phrase: Any) -> tuple[bool, list[str]]:
    errors = []
    if not isinstance(name, str) or not 2 <= len(name.strip()) <= 60:
        errors.append("กรุณาใส่ชื่อผู้ตรวจรับรอง (2-60 ตัวอักษร)")
    if phrase != PHRASE:
        errors.append(f"พิมพ์คำว่า '{PHRASE}' เพื่อยืนยัน")
    errors += blockers(checklist())
    if errors:
        return False, errors
    d = _read()
    d["signed"] = {"by": name.strip(), "date": datetime.date.today().isoformat(), "hash": content_hash()}
    d["history"].append({"action": "sign", "by": name.strip(), "date": d["signed"]["date"]})
    _write(d)
    return True, []


def revoke(by: str = "") -> None:
    d = _read()
    if d["signed"]:
        d["history"].append({"action": "revoke", "by": by, "date": datetime.date.today().isoformat()})
    d["signed"] = None
    _write(d)


def history() -> list[dict[str, Any]]:
    return _read()["history"][-20:]
