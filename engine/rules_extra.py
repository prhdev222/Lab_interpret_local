"""Rules for DN, DR, MAFLD (+Fibroscan), CAD, Stroke, COPD, Asthma, CKD ultrasound, waist, SpO2 and the Thai CV risk entry/completeness check.

Same contract as rules.py: stable ids, thresholds only from data/targets.json, wording only in data/templates.json.
Nothing here diagnoses or prescribes. Free-text results (imaging, DR grade, history) come from lexicon tags.
"""
from __future__ import annotations

import math

from .rules import Ctx, _egfr, _stage, _uacr, finding, fmt, rule, series_text


# ============================================================ CKD / DN : albuminuria, KDIGO risk, ultrasound
def _alb_cat(v: float, t: dict) -> str:
    return "a3" if v > t["a3_above"] else "a2" if v >= t["a2_from"] else "a1"


def _alb_group(c: Ctx) -> str:
    return "DN" if "DN" in c.problems else "CKD"


@rule("ckd.uacr.stage", "CKD", lambda t: (
    f"UACR (หรือ urine microalbumin ที่ระบุหน่วย mg/g) < {t['ckd']['albuminuria']['a2_from']} = A1 ปกติ; ≤ {t['ckd']['albuminuria']['a3_above']} = A2 สูงเล็กน้อยถึงปานกลาง; "
    f"มากกว่านั้น A3 สูงมาก (ใช้กลุ่ม DN ถ้าบันทึกมี DN; แจ้งว่าต้องยืนยันซ้ำ)"))
def r_uacr(c: Ctx):
    p = _uacr(c)
    if not p: return []
    cat = _alb_cat(p["latest"], c.t["ckd"]["albuminuria"])
    level = {"a1": "ok", "a2": "attention", "a3": "alert"}[cat]
    return [finding("ckd.uacr.stage", _alb_group(c), level, f"ckd.uacr.{cat}", v=p["latest"], confirm_note=cat != "a1", series=series_text(p["series"]))]


@rule("dn.possible", "DN", lambda t: "[เฉพาะแพทย์] มี DM + albuminuria (A2/A3) → ชี้ว่าเข้าได้กับโรคไตจากเบาหวานถ้ายืนยันซ้ำ และให้พิจารณาสาเหตุอื่น")
def r_dn_possible(c: Ctx):
    p = _uacr(c)
    if p and "DM" in c.problems and _alb_cat(p["latest"], c.t["ckd"]["albuminuria"]) != "a1":
        return [finding("dn.possible", "DN", "info", "dn.possible", True, v=p["latest"])]
    return []


@rule("ckd.kdigo_risk", "CKD", lambda t: "[เฉพาะแพทย์] มีทั้ง eGFR (G) และ UACR (A) → ระดับความเสี่ยง KDIGO (ต่ำ/ปานกลาง/สูง/สูงมาก) ตามตาราง heat map")
def r_kdigo(c: Ctx):
    egfr, _ = _egfr(c)
    p = _uacr(c)
    if egfr is None or not p: return []
    g = _stage(egfr, c.t["ckd"]["egfr_stage"])
    a = _alb_cat(p["latest"], c.t["ckd"]["albuminuria"])
    grid = {"g1": "low moderate high", "g2": "low moderate high", "g3a": "moderate high very_high", "g3b": "high very_high very_high",
            "g4": "very_high very_high very_high", "g5": "very_high very_high very_high"}
    risk = grid[g].split()[("a1", "a2", "a3").index(a)]
    return [finding("ckd.kdigo_risk", "CKD", "info", "ckd.kdigo_risk", True, g=g.upper(), a=a.upper(), risk={"low": "ต่ำ", "moderate": "ปานกลาง", "high": "สูง", "very_high": "สูงมาก"}[risk])]


_KUB_BAD = ("kub_echo", "kub_small", "kub_hydro", "kub_stone", "kub_mass", "kub_cyst", "kub_asym")


@rule("ckd.us.kub", "CKD", lambda t: (
    "ผลอัลตราซาวด์ไตที่เขียนในบรรทัด CKD (คำใน lexicon.json หมวด tags): ปกติทั้งหมด = อยู่ในเกณฑ์ดี; echo เพิ่ม/ไตเล็ก = เข้าได้กับเนื้อไตเสื่อมเรื้อรัง; "
    "hydronephrosis = ควรพบแพทย์; นิ่ว = ควรพบแพทย์; ก้อน = เร่งด่วน; cyst และไตสองข้างไม่เท่ากัน = เฉพาะแพทย์; 'no hydro' = ไม่มี"))
def r_kub(c: Ctx):
    out = []
    if c.tag("kub_mass"): out.append(finding("ckd.us.kub", "CKD", "alert", "ckd.us.mass"))
    if c.tag("kub_hydro"): out.append(finding("ckd.us.kub", "CKD", "attention", "ckd.us.hydro"))
    if c.tag("kub_stone"): out.append(finding("ckd.us.kub", "CKD", "attention", "ckd.us.stone"))
    if c.tag("kub_echo") or c.tag("kub_small"):
        what = [w for w, k in (("เนื้อไตสว่างขึ้น", "kub_echo"), ("ขนาดไตเล็กลง", "kub_small")) if c.tag(k)]
        out.append(finding("ckd.us.kub", "CKD", "attention", "ckd.us.parenchymal", what=" และ ".join(what)))
    if c.tag("kub_cyst"): out.append(finding("ckd.us.kub", "CKD", "info", "ckd.us.cyst", True))
    if c.tag("kub_asym"): out.append(finding("ckd.us.kub", "CKD", "info", "ckd.us.asym", True))
    if c.tag("kub_normal") and not any(c.tag(k) for k in _KUB_BAD):
        out.append(finding("ckd.us.kub", "CKD", "ok", "ckd.us.normal"))
    return out


# ============================================================ Obesity: waist
@rule("ob.waist", "Obesity", lambda t: f"รอบเอว (เกณฑ์เอเชีย) ชาย ≥ {t['obesity']['waist']['male_from']} ซม. / หญิง ≥ {t['obesity']['waist']['female_from']} ซม. = อ้วนลงพุง (ต้องระบุเพศ)")
def r_waist(c: Ctx):
    p = c.get("Waist")
    if not p: return []
    sex = c.patient.get("sex")
    if sex not in ("M", "F"):
        return [finding("data.need_demo", "Obesity", "info", "data.need_demo", True, need="เพศ", what="รอบเอว")]
    t = c.t["obesity"]["waist"]
    high = p["latest"] >= t["male_from" if sex == "M" else "female_from"]
    return [finding("ob.waist", "Obesity", "attention" if high else "ok", "ob.waist.high" if high else "ob.waist.ok", v=p["latest"])]


# ============================================================ DR
_DR_GRADES = (("dr_pdr", "pdr", "alert"), ("dr_npdr_severe", "npdr_severe", "alert"), ("dr_npdr_moderate", "npdr_moderate", "attention"),
              ("dr_npdr_mild", "npdr_mild", "attention"), ("dr_npdr", "npdr_unspecified", "attention"))
_DR_ANY = ("dr_none", "dr_pdr", "dr_npdr_severe", "dr_npdr_moderate", "dr_npdr_mild", "dr_npdr", "dr_dme")


@rule("dr.grade", "DR", lambda t: "จอประสาทตาเบาหวานตามที่เขียน (no DR / NPDR mild-moderate-severe / PDR / DME): ไม่มี = ดี; mild-moderate = ติดตามกับจักษุแพทย์; severe, PDR, DME = ต้องพบจักษุแพทย์ใกล้ชิด; ถ้าเขียนขัดกัน (no DR กับมีเกรด) = แจ้งแพทย์")
def r_dr(c: Ctx):
    out = []
    grade = next(((k, lvl) for tag, k, lvl in _DR_GRADES if c.tag(tag)), None)
    if grade and c.tag("dr_none"):
        return [finding("dr.conflict", "DR", "info", "dr.conflict", True)]
    if grade:
        out.append(finding("dr.grade", "DR", grade[1], f"dr.{grade[0]}", treated_note=c.tag("dr_treated")))
    elif c.tag("dr_none"):
        out.append(finding("dr.grade", "DR", "ok", "dr.none"))
    if c.tag("dr_dme"):
        out.append(finding("dr.dme", "DR", "alert", "dr.dme"))
    return out


@rule("dr.no_eye_exam", "DR", lambda t: "[เฉพาะแพทย์] มี DM (หรือ DR) ในบันทึกแต่ไม่มีผลจอประสาทตาที่ระบบอ่านได้ → แจ้งว่าไม่มีข้อมูลการตรวจตา")
def r_dr_missing(c: Ctx):
    if ({"DM", "DR"} & c.problems) and not any(c.tag(t) for t in _DR_ANY):
        return [finding("dr.no_eye_exam", "DR", "info", "dr.no_eye_exam", True)]
    return []


# ============================================================ MAFLD
@rule("liver.enzymes", "MAFLD", lambda t: (
    f"ALT/AST (ใช้ค่าสูงสุดปกติ {t['mafld']['enzymes']['uln']} U/L ตั้งต้น ต้องแก้ตามห้องแล็บ): ไม่เกิน = ปกติ; เกินแต่ต่ำกว่า {t['mafld']['enzymes']['high_multiple']} เท่า = สูงเล็กน้อย; ตั้งแต่ {t['mafld']['enzymes']['high_multiple']} เท่า = สูงมาก"))
def r_enzymes(c: Ctx):
    alt, ast = c.get("ALT"), c.get("AST")
    if not (alt or ast): return []
    t = c.t["mafld"]["enzymes"]
    worst = max(p["latest"] for p in (alt, ast) if p)
    band = "high" if worst >= t["uln"] * t["high_multiple"] else "mild" if worst > t["uln"] else "ok"
    enz = ", ".join(f"{n} {fmt(p['latest'])}" for n, p in (("ALT", alt), ("AST", ast)) if p)
    return [finding("liver.enzymes", "MAFLD", {"ok": "ok", "mild": "attention", "high": "alert"}[band], f"liver.enz.{band}", enz=enz)]


def fib4(age: float, ast: float, alt: float, plt: float) -> float:
    return age * ast / (plt * math.sqrt(alt))


def _fib4_band(c: Ctx, v: float) -> str:
    t = c.t["mafld"]["fib4"]
    low = t["low_below_older"] if c.patient["age"] >= t["older_age"] else t["low_below"]
    return "low" if v < low else "high" if v > t["high_above"] else "indet"


@rule("liver.fib4", "MAFLD", lambda t: (
    f"FIB-4 คำนวณเองจากอายุ x AST / (Plt x รากที่สองของ ALT) เมื่อมี ALT AST Plt และอายุ: < {t['mafld']['fib4']['low_below']} ({t['mafld']['fib4']['low_below_older']} ถ้าอายุ ≥ {t['mafld']['fib4']['older_age']}) = โอกาสพังผืดระยะลุกลามต่ำ; "
    f"> {t['mafld']['fib4']['high_above']} = สูง; ระหว่างนั้น = ยังสรุปไม่ได้; อายุ < {t['mafld']['fib4']['min_age']} ไม่ใช้ (แจ้งแพทย์); ถ้าบันทึกมี MAFLD แต่ขาดค่า = แจ้งว่าขาดอะไร"))
def r_fib4(c: Ctx):
    alt, ast, plt = c.get("ALT"), c.get("AST"), c.get("Plt")
    if not (alt and ast and plt):
        if "MAFLD" in c.problems:
            miss = [n for n, p in (("ALT", alt), ("AST", ast), ("Plt", plt)) if not p]
            return [finding("liver.fib4.missing", "MAFLD", "info", "liver.fib4.missing", True, miss="、".join(miss))]
        return []
    age = c.patient.get("age")
    if age is None:
        return [finding("data.need_demo", "MAFLD", "info", "data.need_demo", True, need="อายุ", what="FIB-4")]
    if age < c.t["mafld"]["fib4"]["min_age"]:
        return [finding("liver.fib4.young", "MAFLD", "info", "liver.fib4.young", True, age=age)]
    v = round(fib4(age, ast["latest"], alt["latest"], plt["latest"]), 2)
    band = _fib4_band(c, v)
    return [finding("liver.fib4", "MAFLD", {"low": "ok", "indet": "attention", "high": "attention"}[band], f"liver.fib4.{band}", fib4=v, computed_note=True),
            finding("liver.fib4.inputs", "MAFLD", "info", "liver.fib4.inputs", True, fib4=v, age=age, ast=ast["latest"], alt=alt["latest"], plt=plt["latest"])]


@rule("liver.lsm", "MAFLD", lambda t: (
    f"Fibroscan LSM < {t['mafld']['lsm']['low_below']} kPa = โอกาสพังผืดระยะลุกลามต่ำ; ถึง < {t['mafld']['lsm']['high_from']} = ยังสรุปไม่ได้ (grey zone); ≥ {t['mafld']['lsm']['high_from']} = สงสัยพังผืดมาก ควรพบผู้เชี่ยวชาญ; "
    "[เฉพาะแพทย์] ระบบไม่ทราบคุณภาพการตรวจ (จำนวนครั้ง, IQR/median)"))
def r_lsm(c: Ctx):
    p = c.get("LSM")
    if not p: return []
    t = c.t["mafld"]["lsm"]
    band = "low" if p["latest"] < t["low_below"] else "grey" if p["latest"] < t["high_from"] else "high"
    return [finding("liver.lsm", "MAFLD", {"low": "ok", "grey": "attention", "high": "alert"}[band], f"liver.lsm.{band}", v=p["latest"], series=series_text(p["series"])),
            finding("liver.lsm.quality", "MAFLD", "info", "liver.lsm.quality", True, v=p["latest"])]


@rule("liver.cap", "MAFLD", lambda t: f"CAP < {t['mafld']['cap']['s1_from']} = ไม่มีไขมันพอกตับชัดเจน; ≥ {t['mafld']['cap']['s1_from']} เล็กน้อย; ≥ {t['mafld']['cap']['s2_from']} ปานกลาง; ≥ {t['mafld']['cap']['s3_from']} มาก (เกณฑ์ต่างกันตามเครื่อง)")
def r_cap(c: Ctx):
    p = c.get("CAP")
    if not p: return []
    t = c.t["mafld"]["cap"]
    s = "s3" if p["latest"] >= t["s3_from"] else "s2" if p["latest"] >= t["s2_from"] else "s1" if p["latest"] >= t["s1_from"] else "s0"
    return [finding("liver.cap", "MAFLD", "ok" if s == "s0" else "attention", f"liver.cap.{s}", v=p["latest"])]


@rule("liver.discord", "MAFLD", lambda t: "[เฉพาะแพทย์] FIB-4 กับ Fibroscan ให้ผลสวนทางกัน (FIB-4 สูงแต่ LSM ต่ำ หรือ FIB-4 ต่ำแต่ LSM สูง) → ชี้ให้ตรวจสอบ")
def r_discord_liver(c: Ctx):
    alt, ast, plt, lsm, age = c.get("ALT"), c.get("AST"), c.get("Plt"), c.get("LSM"), c.patient.get("age")
    if not (alt and ast and plt and lsm) or age is None or age < c.t["mafld"]["fib4"]["min_age"]: return []
    v = round(fib4(age, ast["latest"], alt["latest"], plt["latest"]), 2)
    band, lt = _fib4_band(c, v), c.t["mafld"]["lsm"]
    if (band == "high" and lsm["latest"] < lt["low_below"]) or (band == "low" and lsm["latest"] >= lt["high_from"]):
        return [finding("liver.discord", "MAFLD", "attention", "liver.discord", True, fib4=v, lsm=lsm["latest"])]
    return []


@rule("liver.us", "MAFLD", lambda t: "ผลอัลตราซาวด์ตับที่เขียนว่าเข้าได้กับตับแข็ง (cirrhosis / coarse / nodular) → แจ้งให้พบแพทย์ผู้เชี่ยวชาญโรคตับ")
def r_liver_us(c: Ctx):
    return [finding("liver.us", "MAFLD", "alert", "liver.cirrhosis")] if c.tag("us_cirrhosis") else []


# ============================================================ CAD / Stroke
@rule("cad.lvef", "CAD", lambda t: f"LVEF ≥ {t['cad']['lvef']['mild_to'] + 1} = การบีบตัวปกติ; {t['cad']['lvef']['reduced_to'] + 1}-{t['cad']['lvef']['mild_to']} = ลดลงเล็กน้อย; ≤ {t['cad']['lvef']['reduced_to']} = ลดลง")
def r_lvef(c: Ctx):
    p = c.get("LVEF")
    if not p: return []
    t = c.t["cad"]["lvef"]
    band = "reduced" if p["latest"] <= t["reduced_to"] else "mild" if p["latest"] <= t["mild_to"] else "normal"
    return [finding("cad.lvef", "CAD", "ok" if band == "normal" else "attention", f"cad.ef.{band}", v=p["latest"])]


@rule("ascvd.meds", "CAD", lambda t: "[เฉพาะแพทย์] มี CAD หรือ Stroke แต่บันทึกไม่ระบุ statin และ/หรือยาต้านเกล็ดเลือด (ไม่ใช้ถ้า Stroke เลือดออก สำหรับยาต้านเกล็ด) → แจ้งว่าไม่มีข้อมูลในบันทึก (ไม่ได้แปลว่าไม่ได้รับยา)")
def r_ascvd_meds(c: Ctx):
    if not ({"CAD", "Stroke"} & c.problems): return []
    hemorrhagic = "CAD" not in c.problems and c.tag("stroke_hemorrhagic") and not c.tag("stroke_ischemic")
    miss = []
    if not c.tag("med_statin"): miss.append("statin")
    if not hemorrhagic and not c.tag("med_antiplatelet"): miss.append("ยาต้านเกล็ดเลือด")
    return [finding("ascvd.meds", "CAD" if "CAD" in c.problems else "Stroke", "info", "ascvd.meds", True, miss=" และ ".join(miss))] if miss else []


_MRS = ["ไม่มีอาการ", "ไม่มีความพิการสำคัญ", "พิการเล็กน้อย", "พิการปานกลาง (ต้องมีคนช่วยบางส่วน)", "ค่อนข้างรุนแรง (เดินเองไม่ได้)", "รุนแรง (ต้องดูแลตลอดเวลา)"]


@rule("stroke.mrs", "Stroke", lambda t: "[เฉพาะแพทย์] แสดงระดับ mRS ล่าสุดพร้อมความหมาย 0-5 (ไม่ใช้ตัดสินยา)")
def r_mrs(c: Ctx):
    p = c.get("mRS")
    if not p or p["latest"] != int(p["latest"]): return []
    return [finding("stroke.mrs", "Stroke", "info", "stroke.mrs", True, v=p["latest"], label=_MRS[int(p["latest"])])]


@rule("stroke.type", "Stroke", lambda t: "[เฉพาะแพทย์] บันทึกมี Stroke แต่ไม่ระบุชนิด (ischemic/TIA หรือ hemorrhagic) → ไม่ใช้เป้า LDL ของ ASCVD และแจ้งให้ระบุ")
def r_stroke_type(c: Ctx):
    if "Stroke" in c.problems and not (c.tag("stroke_ischemic") or c.tag("stroke_hemorrhagic")):
        return [finding("stroke.type_unknown", "Stroke", "info", "stroke.type_unknown", True)]
    return []


# ============================================================ COPD
def _resp_group(c: Ctx) -> str:
    return "COPD" if "COPD" in c.problems else "Asthma" if "Asthma" in c.problems else "Today"


@rule("copd.gold", "COPD", lambda t: (
    f"มี COPD + FEV1 (% ของค่าคาดหวัง): ≥ {t['copd']['gold']['g1_from']} GOLD 1; ≥ {t['copd']['gold']['g2_from']} GOLD 2; ≥ {t['copd']['gold']['g3_from']} GOLD 3; ต่ำกว่า GOLD 4. "
    f"ถ้า FEV1/FVC ≥ {t['copd']['gold']['obstruction_below']} ไม่ให้เกรด (แจ้งแพทย์); ถ้าไม่มี FEV1/FVC ให้เกรดแต่แจ้งว่ายืนยัน obstruction ไม่ได้"))
def r_gold(c: Ctx):
    if "COPD" not in c.problems: return []
    fev, ratio = c.get("FEV1"), c.get("FEV1FVC")
    if not fev: return []
    t = c.t["copd"]["gold"]
    if ratio and ratio["latest"] >= t["obstruction_below"]:
        return [finding("copd.ratio_inconsistent", "COPD", "attention", "copd.ratio_inconsistent", True, ratio=ratio["latest"], cut=t["obstruction_below"])]
    g = "g1" if fev["latest"] >= t["g1_from"] else "g2" if fev["latest"] >= t["g2_from"] else "g3" if fev["latest"] >= t["g3_from"] else "g4"
    out = [finding("copd.gold", "COPD", "alert" if g in ("g3", "g4") else "attention", f"copd.gold.{g}", v=fev["latest"])]
    if not ratio:
        out.append(finding("copd.ratio_missing", "COPD", "info", "copd.ratio_missing", True, cut=t["obstruction_below"]))
    return out


@rule("copd.symptoms", "COPD", lambda t: f"มี COPD + mMRC ≥ {t['copd']['symptoms']['mmrc_high_from']} หรือ CAT ≥ {t['copd']['symptoms']['cat_high_from']} = อาการมาก; น้อยกว่านั้น = อาการน้อย (ต้องมีอย่างน้อยหนึ่งค่า)")
def r_copd_sx(c: Ctx):
    if "COPD" not in c.problems: return []
    mm, cat = c.get("mMRC"), c.get("CAT")
    if not (mm or cat): return []
    t = c.t["copd"]["symptoms"]
    high = (mm and mm["latest"] >= t["mmrc_high_from"]) or (cat and cat["latest"] >= t["cat_high_from"])
    return [finding("copd.symptoms", "COPD", "attention" if high else "ok", "copd.sx.high" if high else "copd.sx.low")]


def _exac_kind(c: Ctx) -> tuple[str | None, float | None, float | None]:
    ex, hosp = c.get("Exac"), c.get("ExacHosp")
    if not ex and not hosp: return None, None, None
    n = ex["latest"] if ex else 0
    h = hosp["latest"] if hosp else 0
    t = c.t["copd"]["exac"]
    frequent = n >= t["frequent_from"] or h >= t["hosp_from"]
    return ("frequent" if frequent else "none" if n == 0 and h == 0 else "once"), n, h


@rule("copd.exac", "COPD", lambda t: f"มี COPD + จำนวนครั้งกำเริบใน 1 ปี (Exac): 0 = ไม่มี; 1 = หนึ่งครั้ง; ≥ {t['copd']['exac']['frequent_from']} ครั้ง หรือต้องนอน รพ. ≥ {t['copd']['exac']['hosp_from']} (ExacHosp) = บ่อย/รุนแรง")
def r_copd_exac(c: Ctx):
    if "COPD" not in c.problems: return []
    kind, _, _ = _exac_kind(c)
    return [finding("copd.exac", "COPD", "ok" if kind == "none" else "attention", f"copd.exac.{kind}")] if kind else []


@rule("copd.group", "COPD", lambda t: "[เฉพาะแพทย์] กลุ่ม GOLD A/B/E: E = กำเริบ ≥ 2 ครั้ง หรือนอน รพ. ≥ 1; ไม่ใช่ E: B = mMRC ≥ 2 หรือ CAT ≥ 10, A = น้อยกว่านั้น (ต้องมี Exac และ mMRC หรือ CAT; ถ้าขาดจะบอกว่าขาดอะไร)")
def r_copd_group(c: Ctx):
    if "COPD" not in c.problems: return []
    kind, n, h = _exac_kind(c)
    mm, cat = c.get("mMRC"), c.get("CAT")
    if kind is None or not (mm or cat):
        miss = [x for x, ok in (("Exac", kind is not None), ("mMRC หรือ CAT", bool(mm or cat))) if not ok]
        return [finding("copd.group_missing", "COPD", "info", "copd.group_missing", True, miss="、".join(miss))]
    t = c.t["copd"]["symptoms"]
    if kind == "frequent": grp = "E"
    else:
        high = (mm and mm["latest"] >= t["mmrc_high_from"]) or (cat and cat["latest"] >= t["cat_high_from"])
        grp = "B" if high else "A"
    return [finding("copd.group", "COPD", "info", "copd.group", True, grp=grp, n=n, h=h)]


# ============================================================ Asthma
@rule("asthma.act", "Asthma", lambda t: f"ACT ≥ {t['asthma']['act']['good_from']} = ควบคุมได้ดี; {t['asthma']['act']['partly_from']}-{t['asthma']['act']['good_from'] - 1} = ควบคุมได้ไม่ดีนัก; ต่ำกว่านั้น = ควบคุมไม่ได้")
def r_act(c: Ctx):
    p = c.get("ACT")
    if not p or "Asthma" not in c.problems: return []
    t = c.t["asthma"]["act"]
    band = "good" if p["latest"] >= t["good_from"] else "partly" if p["latest"] >= t["partly_from"] else "poor"
    return [finding("asthma.act", "Asthma", "ok" if band == "good" else "attention", f"asthma.act.{band}", v=p["latest"], series=series_text(p["series"]))]


@rule("asthma.pef", "Asthma", lambda t: f"PEF เป็น % ของค่าดีที่สุดส่วนตัว (PEFbest): ≥ {t['asthma']['pef']['green_from']}% โซนเขียว; ≥ {t['asthma']['pef']['yellow_from']}% โซนเหลือง; ต่ำกว่าโซนแดง (ต้องมีทั้ง PEF และ PEFbest)")
def r_pef(c: Ctx):
    pef, best = c.get("PEF"), c.get("PEFbest")
    if not pef or not best or "Asthma" not in c.problems: return []
    raw = pef["latest"] / best["latest"] * 100                       # zones use the exact ratio; the display is rounded DOWN so it never reads as a higher zone
    pct = math.floor(raw)
    t = c.t["asthma"]["pef"]
    zone = "green" if raw >= t["green_from"] else "yellow" if raw >= t["yellow_from"] else "red"
    return [finding("asthma.pef", "Asthma", {"green": "ok", "yellow": "attention", "red": "alert"}[zone], f"asthma.pef.{zone}", pct=pct)]


@rule("asthma.exac", "Asthma", lambda t: "มี Asthma + Exac (ครั้งที่ต้องใช้สเตียรอยด์กิน/ฉุกเฉิน/นอน รพ. ใน 1 ปี): 0 = ไม่มี; ≥ 1 = ควรทบทวนการรักษากับแพทย์")
def r_asthma_exac(c: Ctx):
    ex = c.get("Exac")
    if not ex or "Asthma" not in c.problems: return []
    return [finding("asthma.exac", "Asthma", "ok" if ex["latest"] == 0 else "attention", "asthma.exac.none" if ex["latest"] == 0 else "asthma.exac.some")]


# ============================================================ SpO2
@rule("spo2.status", "Today", lambda t: (
    f"SpO2 ≥ {t['spo2']['ok_from']}% ปกติ; ต่ำกว่าถึง {t['spo2']['alert_below']}% ต่ำเล็กน้อย; ต่ำกว่า {t['spo2']['alert_below']}% ต่ำมาก. "
    f"ถ้าบันทึกมี COPD เป้าหมายต่างออกไป: ไม่บอกผู้ป่วยว่าต่ำ เว้นแต่ ≤ {t['spo2']['copd_alert_to']}% และแจ้งแพทย์เสมอ"))
def r_spo2(c: Ctx):
    p = c.get("SpO2")
    if not p: return []
    t, v, grp = c.t["spo2"], p["latest"], _resp_group(c)
    if "COPD" in c.problems:
        out = [finding("spo2.copd", grp, "info", "spo2.copd", True, v=v)]
        if v <= t["copd_alert_to"]:
            out.append(finding("spo2.status", grp, "alert", "spo2.very_low", v=v))
        return out
    band = "ok" if v >= t["ok_from"] else "low" if v >= t["alert_below"] else "very_low"
    return [finding("spo2.status", grp, {"ok": "ok", "low": "attention", "very_low": "alert"}[band], f"spo2.{band}", v=v)]


# ============================================================ today's symptoms that matter for these diseases
def _present(c: Ctx, cid: str) -> bool:
    return c.concepts.get(cid) == "present"


@rule("life.chest_pain", "Today", lambda t: "บรรทัดวันที่ล่าสุดมี 'เจ็บ/แน่นหน้าอก' → แจ้งให้พบแพทย์ทันทีถ้าเกิดขึ้น (ทุกกรณี)")
def r_chest(c: Ctx):
    return [finding("life.chest_pain", "Today", "alert", "life.chest_pain")] if _present(c, "chest_pain") else []


@rule("life.stroke_signs", "Today", lambda t: "บรรทัดวันที่ล่าสุดมีอ่อนแรง/ชา/พูดไม่ชัด/ปากเบี้ยว → แจ้งให้มาโรงพยาบาลทันที")
def r_stroke_signs(c: Ctx):
    return [finding("life.stroke_signs", "Today", "alert", "life.stroke_signs")] if _present(c, "stroke_signs") else []


@rule("life.vision", "Today", lambda t: "บรรทัดวันที่ล่าสุดมีตามัว/ภาพซ้อน/ม่านบังตา/แสงวาบ → แจ้งให้พบแพทย์หรือจักษุแพทย์โดยเร็ว")
def r_vision(c: Ctx):
    return [finding("life.vision", "Today", "attention", "life.vision")] if _present(c, "blurred_vision") else []


@rule("life.resp", "Today", lambda t: "มี COPD หรือ Asthma + บรรทัดวันที่ล่าสุดมี ไอ/เสมหะ/หายใจวี้ด → แนะนำให้แจ้งแพทย์ (ไม่สรุปสาเหตุ)")
def r_resp(c: Ctx):
    if ({"COPD", "Asthma"} & c.problems) and _present(c, "resp_sx"):
        return [finding("life.resp", _resp_group(c), "attention", "life.resp")]
    return []


# ============================================================ Thai CV risk: manual entry + completeness
@rule("risk.tcvr.status", "Risk", lambda t: (
    f"ค่า Thai CV risk (% ใน 10 ปี) ที่ผู้ใช้กรอกเอง (ระบบไม่คำนวณ): < {t['thai_cv']['categories']['moderate_from']} ต่ำ; < {t['thai_cv']['categories']['high_from']} ปานกลาง; "
    f"< {t['thai_cv']['categories']['very_high_from']} สูง; ≥ {t['thai_cv']['categories']['very_high_from']} สูงมาก (ขอบเขตค่าที่เท่ากับเกณฑ์ปัดขึ้นไปกลุ่มสูงกว่า). "
    f"[เฉพาะแพทย์] แจ้งเสมอว่าค่านี้กรอกเอง และแจ้งถ้าอายุนอก {t['thai_cv']['applicable_age'][0]}-{t['thai_cv']['applicable_age'][1]} หรือบันทึกมี CAD/Stroke ชนิดขาดเลือด"))
def r_tcvr(c: Ctx):
    v = c.patient.get("tcvr")
    if v is None: return []
    t = c.t["thai_cv"]["categories"]
    band = "very_high" if v >= t["very_high_from"] else "high" if v >= t["high_from"] else "moderate" if v >= t["moderate_from"] else "low"
    out = [finding("risk.tcvr.status", "Risk", {"low": "ok", "moderate": "attention", "high": "attention", "very_high": "alert"}[band], f"risk.tcvr.{band}", v=v),
           finding("risk.tcvr.manual", "Risk", "info", "risk.tcvr.manual", True, v=v)]
    lo, hi = c.t["thai_cv"]["applicable_age"]
    age = c.patient.get("age")
    if (age is not None and not lo <= age <= hi) or c.ascvd:
        why = []
        if age is not None and not lo <= age <= hi: why.append(f"อายุ {fmt(age)} อยู่นอกช่วง {lo}-{hi} ปี")
        if c.ascvd: why.append("บันทึกมี CAD/Stroke ชนิดขาดเลือด (เครื่องมือนี้ใช้กับผู้ที่ยังไม่เคยเป็น ASCVD)")
        out.append(finding("risk.tcvr.scope", "Risk", "attention", "risk.tcvr.scope", True, why="; ".join(why)))
    return out


_CV_PROBLEMS = {"DM", "HT", "Dyslipidemia", "Obesity", "CKD", "DN"}


@rule("risk.inputs", "Risk", lambda t: (
    "[เฉพาะแพทย์] ตรวจว่าบันทึกมีข้อมูลสำหรับคำนวณ Thai CV risk ครบไหม (เมื่อมี HT/DM/DLP/Obesity/CKD และยังไม่มี CAD/Stroke ชนิดขาดเลือด): "
    f"ต้องมี {', '.join(t['thai_cv']['required'])} และอย่างน้อยหนึ่งใน {', '.join(t['thai_cv']['one_of'])}; "
    "เบาหวานถือว่า 'ไม่เป็น' ถ้าไม่ได้เขียน DM (แจ้งว่าสมมติ); รายการนี้เป็นค่าตั้งต้น ต้องตรวจกับเครื่องมือจริง; ไม่คำนวณคะแนน"))
def r_risk_inputs(c: Ctx):
    if c.ascvd or not (_CV_PROBLEMS & c.problems): return []
    t = c.t["thai_cv"]
    have, miss, assumed = [], [], []
    bp = c.get("BP")
    smoke = c.concepts.get("smoking")
    facts = {"age": c.patient.get("age") is not None, "sex": c.patient.get("sex") is not None, "smoking": smoke in ("current", "former", "never", "not_smoking"),
             "sbp": bool(bp)}
    names = {"age": "อายุ", "sex": "เพศ", "smoking": "การสูบบุหรี่ (จากบรรทัดวันที่ล่าสุด)", "sbp": "ความดันตัวบน (BP คลินิก)"}
    for k in t["required"]:
        (have if facts.get(k) else miss).append(names.get(k, k))
    alt = [p for p in t["one_of"] if c.get(p)]
    (have if alt else miss).append("ค่าเลือด/ร่างกายอย่างน้อยหนึ่งอย่าง: " + ("/".join(alt) if alt else "/".join(t["one_of"])))
    if "DM" in c.problems: have.append("เบาหวาน (มี DM)")
    elif t.get("diabetes_assumed_no_if_unlisted"): assumed.append("เบาหวาน: บันทึกไม่มี DM จึงถือว่าไม่เป็น")
    key = "risk.inputs.missing" if miss else "risk.inputs.complete"
    return [finding("risk.inputs", "Risk", "info", key, True, have="; ".join(have), miss="; ".join(miss), assumed="; ".join(assumed) or "-", note=t["check_note"])]


# ============================================================ monk meal pattern (affects when/what drugs are given: doctor-only hint)
@rule("monk.meals", "Today", lambda t: (
    "[เฉพาะแพทย์] บรรทัดวันที่ล่าสุดบอกว่า 'ฉัน 1 มื้อ' หรือ 'ฉัน 2 มื้อ' → เตือนแพทย์ให้พิจารณาเวลา/ชนิดยาให้สอดคล้องกับมื้อที่ฉัน: "
    "DM = ความเสี่ยงน้ำตาลต่ำ; Warfarin = ปริมาณอาหาร/วิตามินเคไม่สม่ำเสมออาจกระทบ INR; ระบบ **ไม่แนะนำยา ขนาดยา หรือเวลาใช้ยา**"))
def r_meals(c: Ctx):
    n = c.concepts.get("meals")
    if n not in ("1", "2"): return []
    why = []
    if "DM" in c.problems: why.append("DM: พิจารณาความเสี่ยงน้ำตาลต่ำและยาลดน้ำตาลที่ใช้ให้สอดคล้องกับมื้อที่ฉัน")
    if "Warfarin" in c.problems: why.append("Warfarin: ปริมาณอาหารและวิตามินเคที่ไม่สม่ำเสมออาจกระทบ INR")
    if not why: why.append("ยาที่กำหนดให้ฉันพร้อมหรือหลังอาหาร พิจารณาเวลาให้สอดคล้องกับมื้อที่ฉัน")
    return [finding("monk.meals", "Today", "info", "monk.meals", True, n=n, why="; ".join(why))]
