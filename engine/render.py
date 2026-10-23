"""Turns findings into plain text from data/templates.json (+ glossary.json for the monk register).

No sentence is composed by a model. A sentence exists only if a rule produced a finding for it, and every number in a
sentence comes from the findings (which come from data/targets.json or from the parsed note).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .lexicon import DATA_DIR

_PROBLEM_ORDER = ["DM", "DN", "DR", "HT", "Dyslipidemia", "Obesity", "MAFLD", "CKD", "CAD", "Stroke", "COPD", "Asthma", "Anemia", "Warfarin", "Risk", "Custom", "Today"]
_ICON = {"ok": "✅", "attention": "🟡", "alert": "🔴", "info": "ℹ️"}
_TOKEN = re.compile(r"\{([^{}]+)\}")
_cache: dict[str, Any] = {}


def _load(name: str) -> dict[str, Any]:
    path = os.path.join(DATA_DIR, name)
    key = f"{path}:{os.path.getmtime(path)}"
    if key not in _cache:
        with open(path, encoding="utf-8") as f:
            _cache[key] = json.load(f)
    return _cache[key]


def fill(text: str, mapping: dict[str, str]) -> str:
    """Replace {name} using mapping; values may themselves contain {name} (resolved in up to 4 passes). Unknown name -> KeyError."""
    for _ in range(4):
        new = _TOKEN.sub(lambda m: mapping[m.group(1)], text)
        if new == text:
            break
        text = new
    if _TOKEN.search(text):
        raise KeyError(f"unresolved placeholder in: {text[:80]}")
    return text


def _mapping(values: dict[str, str], monk: bool, tpl: dict[str, Any]) -> dict[str, str]:
    g = _load("glossary.json")["monk" if monk else "normal"]
    mapping = {**g, **{k: v for k, v in values.items() if k not in tpl["notes"]}}
    for key, text in tpl["notes"].items():            # rules pass a True/False switch; the wording lives in templates.json
        mapping[key] = text if values.get(key) else ""
    return mapping


def finding_line(f: dict[str, Any], kind: str = "short", monk: bool = False) -> str:
    """One finding as the patient would read it (icon + sentence). `kind` = short | long."""
    tpl = _load("templates.json")
    source = f.get("texts") or tpl["findings"][f["key"]]                  # user-written rules carry their own wording
    return f"{_ICON[f['level']]} {fill(source[kind], _mapping(f['values'], monk, tpl))}"


def render_patient(result: dict[str, Any], pattern: str = "standard", monk: bool = False) -> str:
    tpl, glossary = _load("templates.json"), _load("glossary.json")
    if pattern not in ("simple", "standard", "detailed"):
        pattern = "standard"
    base = _mapping({}, monk, tpl)
    items = [f for f in result["findings"] if f["level"] != "info"]
    items.sort(key=lambda f: _PROBLEM_ORDER.index(f["problem"]) if f["problem"] in _PROBLEM_ORDER else 99)
    opening = fill("{เปิด}", base)
    closing = fill("{ปิด}", base)
    title = fill(tpl["titles"]["monk" if monk else "normal"], base)
    if result.get("visit_date_be"):
        title += f" (วันที่ {result['visit_date_be']})"
    out: list[str] = [opening] if opening else []
    out.append(f"🩺 {title}")
    if not items:
        out += ["", fill(tpl["empty"], base), "", closing]
        return "\n".join(out)

    def line(f: dict[str, Any], kind: str) -> str:
        return finding_line(f, kind, monk)

    present = [p for p in _PROBLEM_ORDER if p != "Today" and (p in result["problems_present"] or any(f["problem"] == p for f in items))]
    advice_keys = [p for p in present if p in tpl["advice"]]

    if pattern == "simple":
        rank = {"alert": 0, "attention": 1, "ok": 2}
        ordered = sorted(items, key=lambda f: rank[f["level"]])          # most important first
        must = [f for f in ordered if f["level"] != "ok"]               # attention/alert lines are never dropped
        shown = must + [f for f in ordered if f["level"] == "ok"][: max(0, 8 - len(must))]
        shown.sort(key=lambda f: (_PROBLEM_ORDER.index(f["problem"]) if f["problem"] in _PROBLEM_ORDER else 99))
        out += ["", fill("ผลตรวจของ{ท่าน}:", base)] + [line(f, "short") for f in shown]
        out += ["", "สิ่งที่ควรทำ:"] + [f"• {fill(tpl['advice'][p]['short'], base)}" for p in advice_keys[:4]]
        out.append(f"• {fill(tpl['advice']['General']['short'], base)}")
        out += ["", closing]
        return "\n".join(out)

    out += ["", "📋 สรุปภาพรวม"] + [line(f, "short") for f in items]
    out += ["", "🔬 อธิบายค่าที่สำคัญ"]
    extra_groups = sorted({f["problem"] for f in items} - set(_PROBLEM_ORDER))     # a user rule may use any group name: never drop it
    for p in _PROBLEM_ORDER[:-1] + extra_groups + ["Today"]:
        grp = [f for f in items if f["problem"] == p]
        if grp:
            out.append(f"▸ {tpl['problem_titles'].get(p, p)}")
            out += [f"  {line(f, 'long')}" for f in grp]
    out += ["", "✅ คำแนะนำปฏิบัติตัว"]
    seen: set[str] = set()
    for p in advice_keys + ["General"]:
        for a in tpl["advice"][p]["long"]:
            a = fill(a, base)
            if a not in seen:
                seen.add(a); out.append(f"• {a}")
    if monk and set(advice_keys) & {"DM", "DN", "DR", "HT", "Obesity", "MAFLD", "CKD", "CAD", "Stroke", "COPD", "Asthma", "Dyslipidemia", "Anemia", "Warfarin"}:
        out += [f"• {a}" for a in glossary["monk_extra_advice"]]
    out += ["", "⚠️ สัญญาณที่ต้องมาพบแพทย์ทันที"]
    out += [f"• {tpl['problem_titles'][p]}: {tpl['redflags'][p]}" for p in advice_keys if p in tpl["redflags"]]
    out.append(f"• {tpl['redflags']['General']}")
    if pattern == "detailed":
        out += ["", "📅 การติดตาม", f"• {fill(tpl['followup'], base)}"]
    out += ["", closing]
    return "\n".join(out)


def render_clinician(result: dict[str, Any]) -> list[dict[str, str]]:
    tpl = _load("templates.json")
    notes = []
    for n in result["clinician_notes"]:
        template = (n.get("texts") or {}).get("clinician") or tpl["clinician"][n["key"]]
        text = fill(template, {**tpl["notes"], **n["values"]})
        notes.append({"id": n["id"], "level": n["level"], "icon": _ICON[n["level"]], "text": text})
    return notes
