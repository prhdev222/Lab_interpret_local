"""Reads one OPD note written in the problem-oriented shorthand and returns structured data.

    DM : FBS 120->130->110 HbA1C 12->10->6.5%          problem line: name : parameter value(s)
    22/10/69 : มีเวียนศีรษะ ฉันได้น้อย ยังสูบบุหรี่อยู่   dated line: free Thai text about that day

Rules of the format: in a series the LEFT value is the oldest and the RIGHT value is the newest.
Nothing is guessed: unknown words are returned in `leftover`/`unparsed` for a human to read, and implausible
numbers are flagged `invalid` so they are never interpreted.
No patient data is stored by this module; it is a pure function of its input.
"""
from __future__ import annotations

import datetime
import re
from typing import Any

from .lexicon import Lexicon, load_lexicon

MAX_CHARS = 20000
MAX_LINE = 2000
MAX_LINES = 200

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿"), None)
_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_ARROW_CHARS = str.maketrans({"→": "->", "⇒": "=>", "➔": "->", "➡": "->", "⟶": "->", "：": ":", " ": " ", "μ": "µ"})

DATE_LINE = re.compile(r"^\s*(?P<date>\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})\s*:\s*(?P<rest>.*)$")
PROBLEM_LINE = re.compile(r"^\s*(?P<name>[^:\d][^:]{0,40}?)\s*:\s*(?P<rest>.*)$")


def normalize(text: str) -> str:
    text = text.translate(_ZERO_WIDTH).translate(_THAI_DIGITS).translate(_ARROW_CHARS)
    return text.replace("\r\n", "\n").replace("\r", "\n")


# ---------------------------------------------------------------- numbers
def _unit_key(u: str | None) -> str:
    k = (u or "").strip().lower().replace("µ", "u").replace("μ", "u")
    return "mg/g" if k in ("mg/gcr", "mg/g cr") else k            # "mg/g creatinine" is the same unit as mg/g


def _same_unit(a: str, b: str) -> bool:
    a, b = _unit_key(a), _unit_key(b)
    return a == b or {a, b} <= {"ml/min", "ml/min/1.73m2", ""}


def _parse_series(lex: Lexicon, canon: str, series_text: str) -> dict[str, Any]:
    spec = lex.params[canon]
    is_bp = spec.get("kind") == "bp"
    default_unit = spec.get("unit", "")
    values: list[Any] = []
    flags: list[str] = []
    invalid = False
    converted = False
    units_seen: set[str] = set()
    for part in lex.arrow_re.split(series_text.strip()):
        m = lex.elem_re.match(part.strip())
        if not m:                                           # cannot happen if the token regex matched, but never trust
            invalid = True; flags.append(f"อ่านค่า '{part.strip()}' ไม่ได้"); continue
        unit = _unit_key(m.group("u"))
        if unit: units_seen.add(unit)
        if is_bp:
            if m.group("b") is None:
                invalid = True; flags.append(f"{m.group('a')} ไม่ใช่รูปแบบ BP (ต้องเป็น บน/ล่าง)"); values.append(float(m.group("a"))); continue
            sbp, dbp = float(m.group("a")), float(m.group("b"))
            if not (sbp > dbp and 60 <= sbp <= 260 and 30 <= dbp <= 160):
                invalid = True; flags.append(f"BP {sbp:g}/{dbp:g} เป็นไปไม่ได้ → ตรวจสอบ")
            values.append([sbp, dbp])
            continue
        if m.group("b") is not None:
            invalid = True; flags.append(f"{m.group('a')}/{m.group('b')} ไม่ควรเป็นคู่ตัวเลขสำหรับ {canon}"); values.append(float(m.group("a"))); continue
        v = float(m.group("a"))
        if spec.get("require_unit") and not unit:
            invalid = True; flags.append(f"{canon} ต้องระบุหน่วยให้ชัด (mg/g) เพราะอาจเป็น mg/L หรือ mg/24h → ไม่แปลผล ตรวจสอบ")
        if unit and not _same_unit(unit, default_unit):
            conv = spec.get("convert", {}).get(unit)
            if conv:
                v = v * conv["factor"] + conv["offset"]; converted = True
            else:
                invalid = True; flags.append(f"หน่วย '{unit}' ไม่รู้จักสำหรับ {canon} (คาดว่า {default_unit}) → ตรวจสอบ")
        scale = spec.get("auto_scale")
        if scale and v > scale["above"]:
            v = v / scale["divide"]; converted = True                       # e.g. platelets written as 180000 -> 180 (x10^3/µL)
        lo, hi = spec.get("range", (None, None))
        if lo is not None and not (lo <= v <= hi):
            invalid = True; flags.append(f"{canon} {v:g} อยู่นอกช่วงที่เป็นไปได้ ({lo:g}-{hi:g}) → ตรวจสอบ")
        values.append(round(v, 2))
    if converted:
        flags.append("มีการแปลงหน่วยอัตโนมัติ (ตรวจสอบค่าที่แสดงอีกครั้ง)")
    if len(units_seen) > 1:
        invalid = True; flags.append("หน่วยในชุดค่าเดียวกันไม่ตรงกัน → ตรวจสอบ")
    return {"param": canon, "series": values, "first": values[0] if values else None, "latest": values[-1] if values else None,
            "unit": default_unit, "kind": "bp" if is_bp else "number", "invalid": invalid, "flags": flags, "converted": converted}


def _parse_range(lex: Lexicon, m: re.Match) -> dict[str, Any]:
    canon = lex.param_alias[re.sub(r"\s+", "", m.group("name").lower())]
    lo, hi = float(m.group("lo")), float(m.group("hi"))
    rlo, rhi = lex.params[canon].get("range", (None, None))
    flags, invalid = [], False
    if not lo < hi:
        invalid = True; flags.append(f"ช่วง {lo:g}-{hi:g} ไม่ถูกต้อง (ค่าแรกต้องน้อยกว่า) → ตรวจสอบ")
    if rlo is not None and not (rlo <= lo and hi <= rhi):
        invalid = True; flags.append(f"ช่วง {lo:g}-{hi:g} อยู่นอกช่วงที่เป็นไปได้ ({rlo:g}-{rhi:g}) → ตรวจสอบ")
    return {"param": canon, "series": [[lo, hi]], "first": [lo, hi], "latest": [lo, hi], "unit": "", "kind": "range",
            "invalid": invalid, "flags": flags, "converted": False}


_NEG_BEFORE = re.compile(r"(?:^|[\s(])(?:no|not|without|nil|neg|negative|absent|ไม่มี|ไม่พบ|ปฏิเสธ|ไม่)\s*(?:evidence of|sign of|signs of)?\s*$", re.IGNORECASE)
_GRADES = ("dr_npdr_mild", "dr_npdr_moderate", "dr_npdr_severe")


def _extract_tags(lex: Lexicon, rest: str, covered: list[bool]) -> list[dict]:
    """Free-text findings inside a problem line (imaging, DR grade, history). Longest match wins; 'no X' / 'ไม่มี X' = absent."""
    hits = []
    for tid, patterns in lex.tags.items():
        for rx in patterns:
            for m in rx.finditer(rest):
                if m.end() > m.start() and not any(covered[m.start():m.end()]):
                    hits.append((m.end() - m.start(), m.start(), m.end(), tid))
    hits.sort(key=lambda h: (-h[0], h[1]))
    tags: list[dict] = []
    for _, a, b, tid in hits:
        if any(covered[a:b]):
            continue
        before = rest[max(0, a - 22):a]
        before = re.split(r"[,;]", before)[-1]
        absent = bool(_NEG_BEFORE.search(before))
        if absent:
            a_neg = a - len(before)
            for i in range(max(0, a_neg), b):
                covered[i] = True
        for i in range(a, b):
            covered[i] = True
        tags.append({"id": tid, "value": "absent" if absent else "present", "source": rest[a:b]})
    present = {t["id"] for t in tags if t["value"] == "present"}
    if present & set(_GRADES):                                               # a specific NPDR grade supersedes bare 'NPDR'
        tags = [t for t in tags if not (t["id"] == "dr_npdr" and t["value"] == "present")]
    return tags


def _parse_problem_rest(lex: Lexicon, rest: str) -> tuple[list[dict], str, list[dict]]:
    out, covered = [], [False] * len(rest)
    if lex.range_re is not None:
        for m in lex.range_re.finditer(rest):
            item = _parse_range(lex, m)
            item["raw"] = m.group(0).strip(); item["has_rules"] = True
            out.append(item)
            for i in range(m.start(), m.end()):
                covered[i] = True
    for m in lex.token_re.finditer(rest):
        canon = lex.param_alias[re.sub(r"\s+", "", m.group("name").lower())]
        item = _parse_series(lex, canon, m.group("series"))
        item["raw"] = m.group(0).strip()
        item["has_rules"] = bool(lex.params[canon].get("has_rules"))
        out.append(item)
        for i in range(m.start(), m.end()):
            covered[i] = True
    tags = _extract_tags(lex, rest.lower(), covered) if lex.tags else []
    leftover = "".join(c for c, used in zip(rest, covered) if not used)
    if lex.filler_re is not None:
        leftover = lex.filler_re.sub(" ", leftover)                          # harmless connecting words are not "unparsed"
    return out, tags, re.sub(r"^[\s,;.()\-]+|[\s,;.()\-]+$", "", re.sub(r"[\s,;]{2,}", " ", leftover)).strip()


# ---------------------------------------------------------------- dates / free text
def parse_date(lex: Lexicon, s: str, today: datetime.date | None = None) -> tuple[datetime.date | None, str]:
    today = today or datetime.date.today()
    m = re.fullmatch(r"\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})\s*", s)
    if not m:
        return None, "รูปแบบวันที่ไม่รู้จัก"
    d, mo, ys = int(m[1]), int(m[2]), m[3]
    y = int(ys)
    if len(ys) == 2:
        year = (2500 + y - 543) if lex.two_digit_year_is_be else 2000 + y
    else:
        year = y - 543 if y >= 2400 else y
    try:
        dt = datetime.date(year, mo, d)
    except ValueError:
        return None, f"วันที่เป็นไปไม่ได้ ({d}/{mo}/{ys})"
    if dt > today:
        return dt, "วันที่อยู่ในอนาคต → ตรวจสอบ"
    if (today - dt).days > 3650:
        return dt, "วันที่เก่ามาก → ตรวจสอบ"
    return dt, ""


def _negated(lex: Lexicon, clause: str) -> tuple[bool, str]:
    for neg in lex.negations:
        if clause.startswith(neg):
            return True, clause[len(neg):]
    return False, clause


def _smoking(lex: Lexicon, clause: str) -> str | None:
    s = lex.smoking
    if not any(k in clause for k in s["keywords"][:2] + [s["keywords"][2]]):
        return None
    if any(p in clause for p in s["quit"]):
        return "former"
    if any(p in clause for p in s["never"]):
        return "never"
    neg, _ = _negated(lex, clause)
    if neg:
        return "not_smoking"
    return "current"


_MEALS = re.compile(r"ฉัน\s*(?:(?P<n>[1-3])\s*มื้อ|(?P<one>มื้อเดียว|หนึ่งมื้อ)|(?P<two>สองมื้อ))")


def _parse_visit_text(lex: Lexicon, text: str) -> tuple[list[dict], list[str]]:
    concepts, leftover = [], []
    mm = _MEALS.search(text)                                                  # "ฉัน 1 มื้อ" / "ฉัน 2 มื้อ": monks eat one or two meals a day
    if mm:
        n = mm.group("n") or ("1" if mm.group("one") else "2")
        concepts.append({"id": "meals", "label": "จำนวนมื้อที่ฉันต่อวัน", "value": n, "source": mm.group(0)})
        text = text[:mm.start()] + " " + text[mm.end():]
    for clause in [c for c in re.split(r"[\s,;]+", text) if c]:
        hit = False
        smk = _smoking(lex, clause)
        if smk:
            concepts.append({"id": "smoking", "label": "การสูบบุหรี่", "value": smk, "source": clause}); hit = True
        neg, body = _negated(lex, clause)
        for cid, spec in lex.concepts.items():
            if any(p in clause for p in spec["phrases"]):
                value = "absent" if neg else "present"
                same = next((c for c in concepts if c["id"] == cid and c["value"] == value), None)
                if same: same["source"] += "、" + clause                        # one entry per concept; keep every phrase the doctor wrote
                else: concepts.append({"id": cid, "label": spec["label"], "value": value, "source": clause})
                hit = True
        if not hit:
            leftover.append(clause)
    return concepts, leftover


# ---------------------------------------------------------------- public API
def parse_note(text: str, lexicon: Lexicon | None = None, today: datetime.date | None = None) -> dict[str, Any]:
    lex = lexicon or load_lexicon()
    result: dict[str, Any] = {"problems": [], "visits": [], "unparsed_lines": [], "warnings": []}
    if not isinstance(text, str):
        result["warnings"].append("ข้อมูลที่ส่งมาไม่ใช่ข้อความ"); return result
    if len(text) > MAX_CHARS:
        result["warnings"].append(f"บันทึกยาวเกิน {MAX_CHARS} ตัวอักษร ตัดส่วนท้ายออก"); text = text[:MAX_CHARS]
    lines = normalize(text).split("\n")
    if len(lines) > MAX_LINES:
        result["warnings"].append(f"บันทึกมีมากกว่า {MAX_LINES} บรรทัด อ่านเฉพาะส่วนแรก"); lines = lines[:MAX_LINES]
    for no, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        if len(line) > MAX_LINE:
            result["unparsed_lines"].append({"line_no": no, "text": line[:200] + " …", "reason": "บรรทัดยาวเกินไป"}); continue
        m = DATE_LINE.match(line)
        if m:
            dt, warn = parse_date(lex, m.group("date"), today)
            concepts, leftover = _parse_visit_text(lex, m.group("rest"))
            result["visits"].append({
                "line_no": no, "source": line, "date": dt.isoformat() if dt else None,
                "date_be": f"{dt.day}/{dt.month}/{dt.year + 543}" if dt else None, "date_warning": warn,
                "concepts": concepts, "leftover": leftover})
            continue
        m = PROBLEM_LINE.match(line)
        if m:
            tokens = [t for t in re.split(r"[,/&+\s]+", m.group("name").strip().lower()) if t]
            known = [lex.problem_alias[t] for t in tokens if t in lex.problem_alias]
            name = known[0] if known else m.group("name").strip()
            values, tags, leftover = _parse_problem_rest(lex, m.group("rest"))
            if not values and not tags and not known:
                result["unparsed_lines"].append({"line_no": no, "text": line, "reason": "ไม่พบค่าที่รู้จักในบรรทัดนี้"}); continue
            result["problems"].append({"line_no": no, "source": line, "name": name, "problems": known or [name], "known": bool(known),
                                       "values": values, "tags": tags, "unparsed": leftover})
            continue
        result["unparsed_lines"].append({"line_no": no, "text": line, "reason": "ไม่ใช่รูปแบบ 'ปัญหา : ค่า' หรือ 'วันที่ : ข้อความ'"})
    return result


def collect_params(parsed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """One entry per parameter. If a parameter appears twice, the longer series wins and a warning is added to parsed."""
    best: dict[str, dict[str, Any]] = {}
    for prob in parsed["problems"]:
        for v in prob["values"]:
            cur = best.get(v["param"])
            if cur is None or len(v["series"]) > len(cur["series"]):
                if cur is not None and cur["latest"] != v["latest"]:
                    parsed["warnings"].append(f"{v['param']} ปรากฏหลายครั้งด้วยค่าล่าสุดต่างกัน ใช้ชุดที่ยาวกว่า → ตรวจสอบ")
                best[v["param"]] = {**v, "problem": prob["name"]}
            elif cur is not None and cur["latest"] != v["latest"]:
                parsed["warnings"].append(f"{v['param']} ปรากฏหลายครั้งด้วยค่าล่าสุดต่างกัน ใช้ชุดที่ยาวกว่า → ตรวจสอบ")
    return best


def collect_tags(parsed: dict[str, Any]) -> dict[str, str]:
    """tag id -> 'present' | 'absent' across the whole note ('present' wins if the note contradicts itself)."""
    out: dict[str, str] = {}
    for prob in parsed["problems"]:
        for t in prob.get("tags", []):
            if out.get(t["id"]) != "present":
                out[t["id"]] = t["value"]
    return out


def latest_visit(parsed: dict[str, Any]) -> dict[str, Any] | None:
    dated = [v for v in parsed["visits"] if v["date"]]
    if dated:
        return max(dated, key=lambda v: v["date"])
    return parsed["visits"][-1] if parsed["visits"] else None
