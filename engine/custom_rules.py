"""Rules the doctor writes in data/custom_rules.json: a small declarative language, evaluated WITHOUT eval().

    {"disable_builtin": ["dm.fbs.status"],
     "rules": [{"id": "my.ldl_dm", "enabled": true, "problem": "Dyslipidemia", "level": "attention",
                "when": {"all": [{"param": "LDL", "op": ">=", "value": 160}, {"problem": "DM"}]},
                "patient": {"short": "LDL {LDL} สูง ควรปรึกษาแพทย์", "long": "..."},      # optional, shown to the patient
                "clinician": "..."}]}                                                      # optional, shown to the doctor only

Safety rules of this module:
  * three-valued logic: a condition about a value that is missing/invalid is UNKNOWN, and a rule fires only when its
    condition is definitely true (so "not LDL < 100" never fires just because LDL was not written);
  * a rule that does not validate is skipped and the doctor is told why; a broken file never stops the built-in rules;
  * patient wording obeys the same lint as templates.json (no hard-coded numbers, glossary tokens for lay/monk words,
    no diagnosing/prescribing words) so the monk register cannot leak and numbers cannot drift from the condition.
"""
from __future__ import annotations

import json
import math
import os
import re
from typing import Any

from .lexicon import DATA_DIR, load_lexicon

PATH = os.path.join(DATA_DIR, "custom_rules.json")
OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
       "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
LEVELS = ("ok", "attention", "alert", "info")
PATIENT_LEVELS = ("ok", "attention", "alert")
NUM_FIELDS, BP_FIELDS = {"latest", "first", "delta", "pct"}, {"sys", "dia"}
MAX_RULES, MAX_TEXT, MAX_DEPTH, MAX_NODES, MAX_LIST = 200, 400, 6, 40, 20
RULE_KEYS = {"id", "enabled", "problem", "when", "level", "patient", "clinician", "note"}
BANNED_PATIENT = ["เป็นโรค", "ท่านเป็น", "สั่งยา", "ให้ยา", "เพิ่มยา", "ลดยา", "ปรับยา", "metformin", "insulin", "อินซูลิน", "statin", "สแตติน", "aspirin", "แอสไพริน"]
LAY_WORDS = ("รับประทาน", "อาหาร", "ร่างกาย", "นอนหลับ", "ออกกำลังกาย", "เจ็บป่วย")
SMOKING_STATES = ("current", "former", "never", "not_smoking")
_TOKEN = re.compile(r"\{([^{}]+)\}")
_cache: dict[str, Any] = {}


class Bad(Exception):
    pass


def _num(x: Any, what: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise Bad(f"{what} ต้องเป็นตัวเลข")
    return float(x)


# ------------------------------------------------------------------ validation
def _param(lex, name: Any) -> str:
    if not isinstance(name, str):
        raise Bad("param ต้องเป็นข้อความ")
    canon = lex.param_alias.get(re.sub(r"\s+", "", name.lower()))
    if not canon:
        raise Bad(f"ไม่รู้จักค่า '{name}' (ดูรายชื่อใน data/lexicon.json → params)")
    if canon in lex.range_params:
        raise Bad(f"'{name}' เป็นค่าประเภทช่วง ใช้ในเงื่อนไขไม่ได้")
    return canon


def _check_cond(c: Any, lex, depth: int, counter: list[int]) -> None:
    counter[0] += 1
    if counter[0] > MAX_NODES:
        raise Bad(f"เงื่อนไขซับซ้อนเกินไป (เกิน {MAX_NODES} ส่วน)")
    if depth > MAX_DEPTH:
        raise Bad(f"เงื่อนไขซ้อนลึกเกินไป (เกิน {MAX_DEPTH} ชั้น)")
    if not isinstance(c, dict) or not c:
        raise Bad("เงื่อนไขแต่ละส่วนต้องเป็นวัตถุ { ... }")
    kinds = [k for k in ("all", "any", "not", "param", "problem", "patient", "concept") if k in c]
    if len(kinds) != 1:
        raise Bad(f"เงื่อนไขต้องมีชนิดเดียว (all/any/not/param/problem/patient/concept) ได้ {sorted(c)}")
    kind = kinds[0]
    allowed = {"all": {"all"}, "any": {"any"}, "not": {"not"}, "problem": {"problem"}, "concept": {"concept", "is"},
               "param": {"param", "field", "op", "value"}, "patient": {"patient", "op", "value"}}[kind]
    if set(c) - allowed:
        raise Bad(f"คีย์ที่ไม่รู้จักในเงื่อนไข {kind}: {sorted(set(c) - allowed)}")
    if kind in ("all", "any"):
        if not isinstance(c[kind], list) or not 1 <= len(c[kind]) <= MAX_LIST:
            raise Bad(f"{kind} ต้องเป็นรายการ 1-{MAX_LIST} ข้อ")
        for sub in c[kind]:
            _check_cond(sub, lex, depth + 1, counter)
    elif kind == "not":
        _check_cond(c["not"], lex, depth + 1, counter)
    elif kind == "problem":
        if c["problem"] not in set(lex.problem_alias.values()):
            raise Bad(f"ไม่รู้จักโรค '{c['problem']}' (ใช้: {', '.join(sorted(set(lex.problem_alias.values())))})")
    elif kind == "concept":
        cid = c["concept"]
        if cid != "smoking" and cid not in lex.concepts:
            raise Bad(f"ไม่รู้จักอาการ '{cid}' (ดู data/lexicon.json → concepts หรือใช้ smoking)")
        state = c.get("is", "present")
        ok = SMOKING_STATES if cid == "smoking" else ("present", "absent")
        if state not in ok:
            raise Bad(f"is ของ {cid} ต้องเป็นหนึ่งใน {ok}")
    elif kind == "patient":
        if c["patient"] == "age":
            _num(c.get("value"), "value ของอายุ")
            if c.get("op") not in OPS: raise Bad(f"op ต้องเป็นหนึ่งใน {sorted(OPS)}")
        elif c["patient"] == "sex":
            if c.get("op") not in ("==", "!="): raise Bad("เพศใช้ได้เฉพาะ == หรือ !=")
            if c.get("value") not in ("M", "F"): raise Bad("เพศต้องเป็น M หรือ F")
        else:
            raise Bad("patient ต้องเป็น age หรือ sex")
    else:  # param
        canon = _param(lex, c["param"])
        is_bp = lex.params[canon].get("kind") == "bp"
        field = c.get("field", "sys" if is_bp else "latest")
        if is_bp and field not in BP_FIELDS: raise Bad(f"{canon} เป็นความดัน ต้องระบุ field เป็น sys หรือ dia")
        if not is_bp and field not in NUM_FIELDS: raise Bad(f"field ของ {canon} ต้องเป็นหนึ่งใน {sorted(NUM_FIELDS)}")
        if c.get("op") not in OPS: raise Bad(f"op ต้องเป็นหนึ่งใน {sorted(OPS)}")
        _num(c.get("value"), "value")


def _placeholders(text: str, lex, glossary: set[str]) -> list[tuple[str, str]]:
    """-> [(param canonical, field)] for value placeholders; raises Bad for unknown names."""
    out = []
    for name in _TOKEN.findall(text):
        if name in glossary:
            continue
        base, _, field = name.partition(".")
        canon = lex.param_alias.get(re.sub(r"\s+", "", base.lower()))
        if not canon or canon in lex.range_params:
            raise Bad(f"ช่อง {{{name}}} ไม่รู้จัก (ใช้ชื่อค่า เช่น {{LDL}} {{BP.sys}} {{HbA1c.first}} หรือคำสงฆ์ เช่น {{ท่าน}})")
        is_bp = lex.params[canon].get("kind") == "bp"
        field = field or ("sys" if is_bp else "latest")
        if field not in (BP_FIELDS if is_bp else NUM_FIELDS):
            raise Bad(f"ช่อง {{{name}}}: field '{field}' ใช้กับ {canon} ไม่ได้")
        out.append((canon, field))
    return out


def _check_text(text: Any, patient: bool, lex, glossary: set[str]) -> None:
    if not isinstance(text, str) or not text.strip():
        raise Bad("ข้อความต้องไม่ว่าง")
    if len(text) > MAX_TEXT:
        raise Bad(f"ข้อความยาวเกิน {MAX_TEXT} ตัวอักษร")
    _placeholders(text, lex, glossary)
    if patient:
        plain = _TOKEN.sub("", text)
        if re.search(r"\d", plain):
            raise Bad("ข้อความถึงผู้ป่วยห้ามมีตัวเลขเขียนตรง ๆ (ใช้ช่อง {LDL} เพื่อให้ตัวเลขตรงกับเงื่อนไขเสมอ)")
        for lay in LAY_WORDS:
            if lay in plain.replace("อาหารเสริม", ""):
                raise Bad(f"คำว่า '{lay}' ต้องใช้ช่องคำสงฆ์ ({{ทาน}} {{อาหาร}} {{กาย}} {{นอน}} {{ออกกำลัง}} {{อาพาธ}}) เพื่อให้โหมดพระสงฆ์ถูกต้อง")
        low = plain.lower().replace("ห้ามปรับยา", "").replace("ห้ามปรับหรือหยุดยา", "")
        for b in BANNED_PATIENT:
            if b in low:
                raise Bad(f"ข้อความถึงผู้ป่วยห้ามมีคำว่า '{b}' (ระบบไม่วินิจฉัยและไม่สั่งยา)")


def validate(data: Any, builtin_ids: set[str], lexicon=None, glossary: set[str] | None = None) -> tuple[list[dict], list[str], list[str]]:
    """-> (valid enabled rules, error messages, disabled built-in ids). Never raises."""
    lex = lexicon or load_lexicon()
    glossary = glossary if glossary is not None else _glossary_tokens()
    errors: list[str] = []
    if not isinstance(data, dict):
        return [], ["ไฟล์ custom_rules.json ต้องเป็นวัตถุ { ... }"], []
    extra = set(data) - {"_meta", "disable_builtin", "rules"}
    if extra:
        errors.append(f"คีย์ที่ไม่รู้จักในไฟล์: {sorted(extra)}")
    disabled: list[str] = []
    for rid in data.get("disable_builtin", []) if isinstance(data.get("disable_builtin", []), list) else []:
        if rid in builtin_ids: disabled.append(rid)
        else: errors.append(f"disable_builtin: ไม่มีกฎมาตรฐานชื่อ '{rid}' (พิมพ์ผิดหรือเปล่า? ดูรหัสใน docs/RULES_REVIEW.md)")
    if not isinstance(data.get("disable_builtin", []), list):
        errors.append("disable_builtin ต้องเป็นรายการ")
    rules_in = data.get("rules", [])
    if not isinstance(rules_in, list):
        return [], errors + ["rules ต้องเป็นรายการ"], disabled
    if len(rules_in) > MAX_RULES:
        errors.append(f"มีกฎเกิน {MAX_RULES} ข้อ อ่านเฉพาะส่วนแรก"); rules_in = rules_in[:MAX_RULES]
    good, seen = [], set()
    for i, r in enumerate(rules_in, 1):
        rid = r.get("id") if isinstance(r, dict) else None
        label = rid if isinstance(rid, str) else f"ข้อที่ {i}"
        try:
            if not isinstance(r, dict): raise Bad("แต่ละกฎต้องเป็นวัตถุ { ... }")
            if set(r) - RULE_KEYS: raise Bad(f"คีย์ที่ไม่รู้จัก: {sorted(set(r) - RULE_KEYS)}")
            if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9_.\-]{2,60}", rid): raise Bad("id ต้องเป็น a-z 0-9 _ . - ยาว 2-60 ตัว")
            if rid in seen: raise Bad("id ซ้ำ")
            seen.add(rid)
            if r.get("enabled", True) is not True:
                continue                                                  # disabled rules are not even validated deeply (examples stay quiet)
            if r.get("level") not in LEVELS: raise Bad(f"level ต้องเป็นหนึ่งใน {LEVELS}")
            if not isinstance(r.get("problem", "Custom"), str): raise Bad("problem ต้องเป็นข้อความ")
            if "when" not in r: raise Bad("ต้องมี when")
            _check_cond(r["when"], lex, 1, [0])
            if "patient" not in r and "clinician" not in r: raise Bad("ต้องมี patient หรือ clinician อย่างน้อยหนึ่งอย่าง")
            if "patient" in r:
                if r["level"] not in PATIENT_LEVELS: raise Bad("กฎที่มีข้อความถึงผู้ป่วยต้องมี level เป็น ok / attention / alert")
                p = r["patient"]
                if not isinstance(p, dict) or set(p) != {"short", "long"}: raise Bad("patient ต้องมี short และ long เท่านั้น")
                _check_text(p["short"], True, lex, glossary); _check_text(p["long"], True, lex, glossary)
            if "clinician" in r:
                _check_text(r["clinician"], False, lex, glossary)
            good.append(r)
        except Bad as e:
            errors.append(f"กฎ {label}: {e}")
    return good, errors, disabled


def _glossary_tokens() -> set[str]:
    with open(os.path.join(DATA_DIR, "glossary.json"), encoding="utf-8") as f:
        return set(json.load(f)["normal"])


def load(builtin_ids: set[str], path: str | None = None) -> tuple[list[dict], list[str], list[str]]:
    path = path or PATH
    if not os.path.exists(path):
        return [], [], []
    st = os.stat(path)
    key = f"{path}:{st.st_mtime_ns}:{st.st_size}"
    if key not in _cache:
        _cache.clear()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            _cache[key] = validate(data, builtin_ids)
        except (OSError, ValueError) as e:                                  # unreadable or not JSON: ignore the whole file, keep built-in rules
            _cache[key] = ([], [f"อ่านไฟล์ custom_rules.json ไม่ได้ ({type(e).__name__}) ใช้เฉพาะกฎมาตรฐาน"], [])
    return _cache[key]


def save(data: Any, builtin_ids: set[str], path: str | None = None) -> tuple[bool, list[str]]:
    """Writes the file only if EVERYTHING in it validates (the web editor never stores a broken rule). Keeps one .bak copy."""
    path = path or PATH
    good, errors, _ = validate(data, builtin_ids)
    if errors:
        return False, errors
    meta = {}
    try:
        with open(path, encoding="utf-8") as f:
            meta = json.load(f).get("_meta", {})
    except (OSError, ValueError, AttributeError):
        pass
    out = {"_meta": meta, "disable_builtin": list(dict.fromkeys(data.get("disable_builtin", []))), "rules": data.get("rules", [])}
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f, open(path + ".bak", "w", encoding="utf-8") as b:
            b.write(f.read())
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return True, []


# ------------------------------------------------------------------ evaluation (three-valued logic: True / False / None = unknown)
def _field_value(entry: dict | None, field: str):
    if not entry:
        return None
    series, latest, first = entry["series"], entry["latest"], entry["first"]
    if field in BP_FIELDS:
        i = 0 if field == "sys" else 1
        return latest[i] if isinstance(latest, list) else None
    if isinstance(latest, list):
        return None
    if field == "latest": return latest
    if field == "first": return first
    if len(series) < 2: return None
    if field == "delta": return latest - first
    if field == "pct": return None if not first else (latest - first) / first * 100
    return None


def _eval(c: dict, ctx) -> bool | None:
    lex = load_lexicon()
    if "all" in c or "any" in c:
        vals = [_eval(s, ctx) for s in c.get("all", c.get("any"))]
        if "all" in c:
            return False if False in vals else None if None in vals else True
        return True if True in vals else None if None in vals else False
    if "not" in c:
        v = _eval(c["not"], ctx)
        return None if v is None else not v
    if "problem" in c:
        return c["problem"] in ctx.problems
    if "concept" in c:
        cid, state = c["concept"], c.get("is", "present")
        got = ctx.concepts.get(cid)
        if cid == "smoking":
            return None if got is None else got == state
        if state == "present":
            return got == "present"
        return True if got == "absent" else None if got is None else False
    if "patient" in c:
        v = ctx.patient.get(c["patient"])
        return None if v is None else OPS[c["op"]](v, c["value"])
    canon = lex.param_alias[re.sub(r"\s+", "", c["param"].lower())]
    is_bp = lex.params[canon].get("kind") == "bp"
    v = _field_value(ctx.get(canon), c.get("field", "sys" if is_bp else "latest"))
    return None if v is None else OPS[c["op"]](v, c["value"])


def _values_for(text_list: list[str], ctx, lex) -> dict[str, str] | None:
    out: dict[str, str] = {}
    for text in text_list:
        for name in _TOKEN.findall(text):
            base, _, field = name.partition(".")
            canon = lex.param_alias.get(re.sub(r"\s+", "", base.lower()))
            if not canon:
                continue                                                    # glossary token
            is_bp = lex.params[canon].get("kind") == "bp"
            v = _field_value(ctx.get(canon), field or ("sys" if is_bp else "latest"))
            if v is None:
                return None
            out[name] = f"{round(v, 2):g}"
    return out


def evaluate_custom(ctx, rules: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    """-> (patient findings, doctor-only notes, skipped-at-runtime messages)"""
    lex = load_lexicon()
    findings, notes, skipped = [], [], []
    for r in rules:
        if _eval(r["when"], ctx) is not True:
            continue
        texts = [r["clinician"]] if "clinician" in r and "patient" not in r else (list(r["patient"].values()) + ([r["clinician"]] if "clinician" in r else []))
        values = _values_for(texts, ctx, lex)
        if values is None:
            skipped.append(f"กฎ {r['id']}: ข้ามเพราะไม่มีค่าที่ข้อความต้องใช้"); continue
        base = {"id": f"custom.{r['id']}", "problem": r.get("problem", "Custom"), "level": r["level"], "key": f"custom.{r['id']}", "values": values, "custom": True}
        if "patient" in r:
            findings.append({**base, "clinician_only": False, "texts": r["patient"]})
        if "clinician" in r:
            notes.append({**base, "id": f"custom.{r['id']}.clinician", "level": "info", "clinician_only": True, "texts": {"clinician": r["clinician"]}})
    return findings, notes, skipped


# ------------------------------------------------------------------ human-readable description (for docs/RULES_REVIEW.md)
def describe(c: dict) -> str:
    if "all" in c: return "(" + " และ ".join(describe(s) for s in c["all"]) + ")"
    if "any" in c: return "(" + " หรือ ".join(describe(s) for s in c["any"]) + ")"
    if "not" in c: return f"ไม่ใช่ {describe(c['not'])}"
    if "problem" in c: return f"บันทึกมี {c['problem']}"
    if "concept" in c: return f"{c['concept']} = {c.get('is', 'present')}"
    if "patient" in c: return f"{c['patient']} {c['op']} {c['value']}"
    lex = load_lexicon()                                              # (no backslash inside an f-string: Python 3.10 on the RDK X5 rejects it)
    canon = lex.param_alias[re.sub(r"\s+", "", c["param"].lower())]
    field = c.get("field", "sys" if lex.params[canon].get("kind") == "bp" else "latest")
    return f"{c['param']}.{field} {c['op']} {c['value']}"
