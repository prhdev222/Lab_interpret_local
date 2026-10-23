"""Editing data/targets.json from the web page, safely.

The page sends only {path: new value}. Only numeric thresholds, numeric pairs, `source`/note text and `needs_citation`
can change (never the structure, never lists of names), every value is range-checked, and the ladders that the rules rely on
(e.g. G1 > G2 > G3a, BMI cut-offs rising) are checked as a whole. Nothing is written unless everything passes; one .bak is kept.
"""
from __future__ import annotations

import copy
import datetime
import json
import math
import os
from typing import Any

from .lexicon import DATA_DIR

PATH = os.path.join(DATA_DIR, "targets.json")
TEXT_KEYS = {"source", "quitline", "quitline_note", "check_note"}
PERCENT_KEYS = {"stable_pct", "trend_pct", "significant_pct", "tolerance_pct", "mcv_tolerance_pct"}
MAX_TEXT = 400

# paths are dotted; each ladder lists values that must be STRICTLY increasing ("asc"), non-decreasing ("asc_eq") or STRICTLY decreasing ("desc"); "[0]"/"[1]" pick a pair member
LADDERS = [
    ("desc", ["ckd.egfr_stage.g1_from", "ckd.egfr_stage.g2_from", "ckd.egfr_stage.g3a_from", "ckd.egfr_stage.g3b_from", "ckd.egfr_stage.g4_from"]),
    ("desc", ["copd.gold.g1_from", "copd.gold.g2_from", "copd.gold.g3_from"]),
    ("desc", ["asthma.act.good_from", "asthma.act.partly_from"]),
    ("desc", ["asthma.pef.green_from", "asthma.pef.yellow_from"]),
    ("asc", ["anemia.hb.moderate_from", "anemia.hb.mild_from", "anemia.hb.anemia_below_female"]),
    ("asc", ["anemia.hb.mild_from", "anemia.hb.anemia_below_male"]),
    ("asc", ["dm.fbs.low_below", "dm.fbs.slightly_low_below"]),
    ("asc_eq", ["dm.fbs.slightly_low_below", "dm.fbs.target[0]"]),
    ("asc", ["dm.fbs.target[0]", "dm.fbs.target[1]", "dm.fbs.high_from"]),
    ("asc", ["dm.hba1c.target_max", "dm.hba1c.mild_high_below", "dm.hba1c.high_below"]),
    ("asc", ["dm.hba1c.improving_delta", "dm.hba1c.worsening_delta"]),
    ("asc", ["obesity.bmi_asian.underweight_below", "obesity.bmi_asian.normal_below", "obesity.bmi_asian.overweight_below", "obesity.bmi_asian.obese1_below"]),
    ("asc", ["dlp.tg.borderline_from", "dlp.tg.high_from", "dlp.tg.very_high_from"]),
    ("asc", ["dlp.tc.borderline_from", "dlp.tc.high_from"]),
    ("asc", ["dlp.ldl.goal_ascvd", "dlp.ldl.goal_dm_or_ckd"]),
    ("asc", ["dlp.ldl.goal_dm_or_ckd", "dlp.ldl.goal_default", "dlp.ldl.very_high_from"]),
    ("asc", ["ckd.albuminuria.a2_from", "ckd.albuminuria.a3_above"]),
    ("asc", ["mafld.lsm.low_below", "mafld.lsm.high_from"]),
    ("asc", ["mafld.cap.s1_from", "mafld.cap.s2_from", "mafld.cap.s3_from"]),
    ("asc", ["mafld.fib4.low_below", "mafld.fib4.high_above"]),
    ("asc", ["mafld.fib4.low_below_older", "mafld.fib4.high_above"]),
    ("asc", ["mafld.fib4.min_age", "mafld.fib4.older_age"]),
    ("asc", ["thai_cv.categories.moderate_from", "thai_cv.categories.high_from", "thai_cv.categories.very_high_from"]),
    ("asc", ["thai_cv.applicable_age[0]", "thai_cv.applicable_age[1]"]),
    ("asc", ["spo2.copd_alert_to", "spo2.alert_below", "spo2.ok_from"]),
    ("asc", ["cad.lvef.reduced_to", "cad.lvef.mild_to"]),
    ("asc", ["anemia.mcv.micro_below", "anemia.mcv.macro_above"]),
    ("asc", ["anemia.crosscheck.hct_hb_ratio[0]", "anemia.crosscheck.hct_hb_ratio[1]"]),
    ("asc", ["warfarin.default_goal[0]", "warfarin.default_goal[1]", "warfarin.alert_above"]),
    ("asc", ["ht.clinic.target_general[1]", "ht.clinic.target_general[0]", "ht.clinic.crisis[0]"]),     # diastolic < systolic < crisis systolic
    ("asc", ["ht.clinic.target_comorbid[1]", "ht.clinic.target_comorbid[0]"]),
    ("asc", ["ht.home.target_general[1]", "ht.home.target_general[0]"]),
    ("asc", ["ht.home.target_comorbid[1]", "ht.home.target_comorbid[0]"]),
    ("asc", ["ht.discordance.clinic_high[1]", "ht.discordance.clinic_high[0]"]),
    ("asc", ["ht.discordance.home_high[1]", "ht.discordance.home_high[0]"]),
    ("asc", ["ht.clinic.crisis[1]", "ht.clinic.crisis[0]"]),
]
# the stricter (comorbid) target must not be looser than the general one
NOT_LOOSER = [("ht.clinic.target_comorbid", "ht.clinic.target_general"), ("ht.home.target_comorbid", "ht.home.target_general")]


GROUPS = {
    "dm.hba1c": "เบาหวาน · HbA1c (%)", "dm.fbs": "เบาหวาน · น้ำตาลตอนเช้า FBS (mg/dL)", "ht.clinic": "ความดัน · ที่โรงพยาบาล (mmHg, บน/ล่าง)",
    "ht.home": "ความดัน · ที่บ้าน (mmHg, บน/ล่าง)", "ht.discordance": "ความดัน · เกณฑ์เทียบที่บ้านกับที่โรงพยาบาล", "obesity.bmi_asian": "BMI เกณฑ์คนเอเชีย",
    "obesity.weight_change": "น้ำหนักที่เปลี่ยน", "obesity.waist": "รอบเอวคนเอเชีย (ซม.)", "ckd.egfr_stage": "ไต · ระยะ eGFR", "ckd": "ไต · ทั่วไป",
    "ckd.crosscheck": "ไต · ตรวจ eGFR ที่ระบุกับที่คำนวณ", "ckd.albuminuria": "ไต · อัลบูมินรั่ว UACR (mg/g)", "lifestyle": "สายด่วนเลิกบุหรี่",
    "dlp.ldl": "ไขมัน · LDL (mg/dL)", "dlp.tg": "ไขมัน · TG (mg/dL)", "dlp.hdl": "ไขมัน · HDL (mg/dL)", "dlp.tc": "ไขมัน · คอเลสเตอรอลรวม (mg/dL)",
    "anemia.hb": "ซีด · Hb (g/dL)", "anemia.mcv": "ซีด · MCV (fL)", "anemia": "ซีด · ทั่วไป", "anemia.crosscheck": "ซีด · ตรวจความสอดคล้อง CBC",
    "warfarin": "วาฟาริน · INR", "mafld.enzymes": "ตับ · ALT/AST", "mafld.fib4": "ตับ · FIB-4", "mafld.lsm": "ตับ · Fibroscan LSM (kPa)", "mafld.cap": "ตับ · Fibroscan CAP (dB/m)",
    "cad.lvef": "หัวใจ · LVEF (%)", "spo2": "ออกซิเจนในเลือด SpO2 (%)", "copd.gold": "COPD · GOLD", "copd.symptoms": "COPD · อาการ (mMRC, CAT)", "copd.exac": "COPD · อาการกำเริบ",
    "asthma.act": "หืด · ACT", "asthma.pef": "หืด · โซน PEF (% ของค่าดีที่สุด)", "thai_cv.categories": "Thai CV risk · กลุ่มความเสี่ยง (%)", "thai_cv": "Thai CV risk · ทั่วไป"}
KEYS = {
    "target_max": "เป้าสูงสุด", "mild_high_below": "สูงเล็กน้อยถ้าต่ำกว่า", "high_below": "สูงถ้าต่ำกว่า (เกินนี้ = สูงมาก)", "improving_delta": "ดีขึ้นเมื่อเปลี่ยน ≤", "worsening_delta": "แย่ลงเมื่อเปลี่ยน ≥",
    "rapid_drop": "ลดเร็วเมื่อลดรวม ≥", "target": "ช่วงเป้า (ต่ำ, สูง)", "low_below": "ต่ำถ้าต่ำกว่า", "slightly_low_below": "ต่ำเล็กน้อยถ้าต่ำกว่า", "high_from": "สูงตั้งแต่", "stable_pct": "ถือว่านิ่งถ้าเปลี่ยนไม่เกิน (%)",
    "target_general": "เป้าทั่วไป (บน, ล่าง)", "target_comorbid": "เป้าเมื่อมีโรคร่วม (บน, ล่าง)", "crisis": "วิกฤต (บน, ล่าง)", "clinic_high": "สูงที่โรงพยาบาล (บน, ล่าง)", "home_high": "สูงที่บ้าน (บน, ล่าง)",
    "underweight_below": "น้ำหนักต่ำถ้าต่ำกว่า", "normal_below": "ปกติถ้าต่ำกว่า", "overweight_below": "น้ำหนักเกินถ้าต่ำกว่า", "obese1_below": "อ้วนระดับ 1 ถ้าต่ำกว่า", "significant_pct": "ถือว่ามีนัยเมื่อเปลี่ยน ≥ (%)",
    "male_from": "ชาย ตั้งแต่", "female_from": "หญิง ตั้งแต่", "g1_from": "G1 ตั้งแต่", "g2_from": "G2 ตั้งแต่", "g3a_from": "G3a ตั้งแต่", "g3b_from": "G3b ตั้งแต่", "g4_from": "G4 ตั้งแต่ (ต่ำกว่า = G5)",
    "decline_flag": "eGFR เปลี่ยนมีนัยเมื่อ ≥", "tolerance_pct": "ยอมให้ต่างได้ (%)", "tolerance_abs": "ยอมให้ต่างได้ (หน่วย)", "a2_from": "A2 ตั้งแต่", "a3_above": "A3 เมื่อมากกว่า",
    "quitline": "เบอร์สายด่วน", "quitline_note": "หมายเหตุ", "goal_default": "เป้าทั่วไป (ต่ำกว่า)", "goal_dm_or_ckd": "เป้าเมื่อมี DM/CKD (ต่ำกว่า)", "goal_ascvd": "เป้าเมื่อมี CAD/Stroke ขาดเลือด (ต่ำกว่า)",
    "near_margin": "ใกล้เป้าถ้าเกินเป้าไม่เกิน", "very_high_from": "สูงมากตั้งแต่", "trend_pct": "ดีขึ้น/แย่ลงเมื่อเปลี่ยน ≥ (%)", "borderline_from": "ค่อนข้างสูงตั้งแต่",
    "low_below_male": "ต่ำในชายถ้าต่ำกว่า", "low_below_female": "ต่ำในหญิงถ้าต่ำกว่า", "anemia_below_male": "ซีดในชายถ้าต่ำกว่า", "anemia_below_female": "ซีดในหญิงถ้าต่ำกว่า",
    "mild_from": "ซีดเล็กน้อยตั้งแต่", "moderate_from": "ซีดปานกลางตั้งแต่ (ต่ำกว่า = รุนแรง)", "trend_delta": "เปลี่ยนมีนัยเมื่อ ≥", "micro_below": "เล็กถ้าต่ำกว่า", "macro_above": "ใหญ่ถ้ามากกว่า",
    "rdw_high_above": "RDW สูงถ้ามากกว่า", "mentzer_cut": "Mentzer แบ่งที่", "mcv_tolerance_pct": "MCV ยอมต่างได้ (%)", "hct_hb_ratio": "อัตรา Hct/Hb ที่ปกติ (ต่ำ, สูง)",
    "default_goal": "เป้า INR ตั้งต้น (ต่ำ, สูง)", "alert_above": "แจ้งเตือนถ้ามากกว่า", "uln": "ค่าสูงสุดปกติ (U/L)", "high_multiple": "สูงมากเมื่อ ≥ กี่เท่า", "min_age": "ใช้ได้ตั้งแต่อายุ", "older_age": "อายุ ≥ นี้ใช้เกณฑ์ผู้สูงอายุ",
    "low_below_older": "ต่ำถ้าต่ำกว่า (อายุสูง)", "high_above": "สูงถ้ามากกว่า", "s1_from": "ไขมันพอก เล็กน้อย ตั้งแต่", "s2_from": "ปานกลาง ตั้งแต่", "s3_from": "มาก ตั้งแต่", "reduced_to": "ลดลงถ้า ≤", "mild_to": "ลดลงเล็กน้อยถ้า ≤",
    "ok_from": "ปกติตั้งแต่", "alert_below": "ต่ำมากถ้าต่ำกว่า", "copd_alert_to": "ใน COPD บอกว่าต่ำเมื่อ ≤", "obstruction_below": "ยืนยัน obstruction ถ้า FEV1/FVC ต่ำกว่า", "g3_from": "GOLD 3 ตั้งแต่ (ต่ำกว่า = 4)",
    "mmrc_high_from": "อาการมากเมื่อ mMRC ≥", "cat_high_from": "อาการมากเมื่อ CAT ≥", "frequent_from": "กำเริบบ่อยเมื่อ ≥ (ครั้ง/ปี)", "hosp_from": "รุนแรงเมื่อนอน รพ. ≥ (ครั้ง)", "good_from": "ควบคุมได้ดีตั้งแต่",
    "partly_from": "ไม่ดีนักตั้งแต่ (ต่ำกว่า = ควบคุมไม่ได้)", "green_from": "โซนเขียวตั้งแต่", "yellow_from": "โซนเหลืองตั้งแต่ (ต่ำกว่า = แดง)", "moderate_from_": "", "applicable_age": "ช่วงอายุที่ใช้ได้ (ต่ำสุด, สูงสุด)",
    "source": "อ้างอิงฉบับ/แนวทาง", "needs_citation": "ยังต้องระบุฉบับอ้างอิง", "check_note": "หมายเหตุ"}


def leaves(t: dict, prefix: str = "") -> list[tuple[str, str, Any]]:
    """Editable leaves as (path, kind, value); kind = num | pair | text | bool."""
    out = []
    for k, v in t.items():
        if k == "_meta":
            continue
        p = f"{prefix}{k}"
        if isinstance(v, dict):
            out += leaves(v, p + ".")
        elif isinstance(v, bool):
            if k == "needs_citation": out.append((p, "bool", v))
        elif isinstance(v, (int, float)):
            out.append((p, "num", v))
        elif isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
            out.append((p, "pair", v))
        elif isinstance(v, str) and k in TEXT_KEYS:
            out.append((p, "text", v))
    return out


def _get(t: dict, path: str) -> Any:
    idx = None
    if path.endswith("]"):
        path, idx = path[:-3], int(path[-2])
    node: Any = t
    for part in path.split("."):
        node = node[part]
    return node[idx] if idx is not None else node


def _set(t: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    node = t
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def check(proposed: dict) -> list[str]:
    errors = []
    for path, kind, v in leaves(proposed):
        key = path.split(".")[-1]
        nums = v if kind == "pair" else [v] if kind == "num" else []
        for x in nums:
            lo = -1000 if key.endswith("_delta") else 0
            hi = 100 if key in PERCENT_KEYS else 100000
            if not lo <= x <= hi:
                errors.append(f"{path}: ค่า {x:g} อยู่นอกช่วงที่ยอมรับ ({lo}-{hi})")
        if kind == "text" and (len(v) > MAX_TEXT or (key == "quitline" and not v.isdigit())):
            errors.append(f"{path}: ข้อความยาวเกิน {MAX_TEXT} ตัวอักษร" if len(v) > MAX_TEXT else f"{path}: เบอร์โทรต้องเป็นตัวเลขล้วน")
    for order, chain in LADDERS:
        vals = [_get(proposed, p) for p in chain]
        ok = all({"asc": a < b, "asc_eq": a <= b, "desc": a > b}[order] for a, b in zip(vals, vals[1:]))
        if not ok:
            word = "มากไปน้อย" if order == "desc" else "น้อยไปมาก"
            errors.append("ลำดับค่าไม่ถูกต้อง ต้องเรียง" + word + ": " + " → ".join(f"{p.split('.', 1)[-1] if '.' in p else p}={v:g}" for p, v in zip(chain, vals)))
    for strict, general in NOT_LOOSER:
        for i in (0, 1):
            if _get(proposed, f"{strict}[{i}]") > _get(proposed, f"{general}[{i}]"):
                errors.append(f"{strict} ต้องไม่หลวมกว่า {general}")
                break
    return errors


RANGES_PATH = os.path.join(DATA_DIR, "target_ranges.json")
BIG_CHANGE = 0.4


def warnings(current: dict, proposed: dict, changed: list[str]) -> list[str]:
    """Not errors: a value outside the usual range, or a big jump from the old value (typo guard). The doctor can still confirm."""
    try:
        with open(RANGES_PATH, encoding="utf-8") as f:
            ranges = json.load(f).get("ranges", {})
    except (OSError, ValueError, AttributeError):
        ranges = {}
    out = []
    for path in changed:
        kind = next((k for p, k, _ in leaves(proposed) if p == path), None)
        if kind not in ("num", "pair"):
            continue
        for sub in ([path] if kind == "num" else [f"{path}[0]", f"{path}[1]"]):
            new, old = _get(proposed, sub), _get(current, sub)
            if new == old:
                continue
            rng = ranges.get(sub)
            if rng and not rng[0] <= new <= rng[1]:
                out.append(f"{sub} = {new:g} อยู่นอกช่วงที่พบทั่วไป ({rng[0]:g}–{rng[1]:g}) ตรวจว่าพิมพ์ถูกและตรงกับแนวทางที่ใช้")
            elif abs(old) >= 1 and abs(new - old) / abs(old) > BIG_CHANGE:
                out.append(f"{sub} เปลี่ยนจาก {old:g} เป็น {new:g} (เปลี่ยนมากกว่า {int(BIG_CHANGE * 100)}%) ตรวจว่าไม่ได้พิมพ์ผิด")
    return out


def apply_changes(current: dict, changes: Any) -> tuple[dict | None, list[str]]:
    """-> (new targets, errors). `changes` is {path: value}; anything that is not an editable leaf of the right type is refused."""
    if not isinstance(changes, dict) or not changes:
        return None, ["ไม่มีการเปลี่ยนแปลง"]
    editable = {p: (k, v) for p, k, v in leaves(current)}
    new, errors = copy.deepcopy(current), []
    for path, value in changes.items():
        if path not in editable:
            errors.append(f"{path}: ไม่ใช่ค่าที่แก้ผ่านหน้าเว็บได้"); continue
        kind = editable[path][0]
        if kind == "num" and _finite(value): _set(new, path, value)
        elif kind == "pair" and isinstance(value, list) and len(value) == 2 and all(_finite(x) for x in value): _set(new, path, list(value))
        elif kind == "text" and isinstance(value, str): _set(new, path, value.strip())
        elif kind == "bool" and isinstance(value, bool): _set(new, path, value)
        else: errors.append(f"{path}: ชนิดของค่าไม่ถูกต้อง")
    if errors:
        return None, errors
    errors = check(new)
    return (None, errors) if errors else (new, [])


def save(changes: Any, path: str | None = None) -> tuple[bool, list[str], list[str]]:
    """-> (ok, errors, changed paths). Writes only if everything validates; keeps targets.json.bak."""
    path = path or PATH
    with open(path, encoding="utf-8") as f:
        current = json.load(f)
    new, errors = apply_changes(current, changes)
    if errors:
        return False, errors, []
    changed = [p for p, _, v in leaves(new) if _get(current, p) != v]
    if not changed:
        return False, ["ค่าไม่เปลี่ยน"], []
    new["_meta"]["last_web_edit"] = datetime.date.today().isoformat()
    with open(path + ".bak", "w", encoding="utf-8") as b:
        json.dump(current, b, ensure_ascii=False, indent=1)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return True, [], changed
