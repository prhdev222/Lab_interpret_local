"""Interpretation rules: structured values + patient (age/sex) -> findings.

Design: every rule is a small function registered with a stable id and a human-readable description, so the
physician-review document (docs/RULES_REVIEW.md) is generated from this very registry and cannot drift from the code.
All thresholds come from data/targets.json; none are hard-coded here. Rules never write patient-facing text:
they only return a finding id + values, and the wording lives in data/templates.json.
Nothing here diagnoses or prescribes; clinician_only findings are hints for the doctor, not for the patient.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

from .egfr import ckd_epi_2021
from .lexicon import DATA_DIR
from .parse_note import collect_params, collect_tags, latest_visit

RULES: list[dict[str, Any]] = []
_targets_cache: dict[str, Any] = {}


def load_targets(path: str | None = None) -> dict[str, Any]:
    path = path or os.path.join(DATA_DIR, "targets.json")
    key = f"{path}:{os.path.getmtime(path)}"
    if key not in _targets_cache:
        _targets_cache.clear()
        with open(path, encoding="utf-8") as f:
            _targets_cache[key] = json.load(f)
    return _targets_cache[key]


def rule(rule_id: str, problem: str, describe: Callable[[dict], str]):
    def deco(fn):
        RULES.append({"id": rule_id, "problem": problem, "describe": describe, "fn": fn})
        return fn
    return deco


def fmt(x: float) -> str:
    return f"{round(x, 2):g}"


def series_text(series: list[Any]) -> str:
    return " → ".join(f"{fmt(v[0])}/{fmt(v[1])}" if isinstance(v, list) else fmt(v) for v in series)


def finding(fid: str, problem: str, level: str, key: str, clinician_only: bool = False, **values: Any) -> dict[str, Any]:
    return {"id": fid, "problem": problem, "level": level, "key": key, "clinician_only": clinician_only,
            "values": {k: (fmt(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in values.items()}}


class Ctx:
    def __init__(self, parsed: dict[str, Any], patient: dict[str, Any], t: dict[str, Any]):
        self.parsed, self.patient, self.t = parsed, patient, t
        self.params = collect_params(parsed)
        self.problems = {p for pr in parsed["problems"] for p in pr["problems"]}
        self.tags = collect_tags(parsed)
        self.visit = latest_visit(parsed)
        self.concepts = {c["id"]: c["value"] for c in (self.visit["concepts"] if self.visit else [])}

    def get(self, name: str) -> dict[str, Any] | None:
        v = self.params.get(name)
        return v if v and not v["invalid"] and v["latest"] is not None else None

    def tag(self, name: str) -> bool:
        return self.tags.get(name) == "present"

    @property
    def comorbid(self) -> bool:                      # DM / CKD / DN / CAD / Stroke listed => stricter BP target and LDL goal (see targets.json)
        return bool({"DM", "CKD", "DN", "CAD", "Stroke"} & self.problems)

    @property
    def ascvd(self) -> bool:                         # CAD, or a stroke the note says is ischaemic/TIA (an unspecified stroke type is NOT assumed)
        return "CAD" in self.problems or ("Stroke" in self.problems and self.tag("stroke_ischemic"))


# ============================================================ DM
def _hba1c_band(v: float, t: dict) -> str:
    return "ok" if v <= t["target_max"] else "mild_high" if v < t["mild_high_below"] else "high" if v < t["high_below"] else "very_high"


@rule("dm.hba1c.status", "DM", lambda t: (
    f"HbA1c ล่าสุด ≤ {t['dm']['hba1c']['target_max']} = อยู่ในเป้า; < {t['dm']['hba1c']['mild_high_below']} = สูงกว่าเป้าเล็กน้อย; "
    f"< {t['dm']['hba1c']['high_below']} = สูงกว่าเป้า; ≥ {t['dm']['hba1c']['high_below']} = สูงมาก (ระดับแจ้งเตือน)"))
def r_hba1c_status(c: Ctx):
    p, t = c.get("HbA1c"), c.t["dm"]["hba1c"]
    if not p: return []
    band = _hba1c_band(p["latest"], t)
    return [finding("dm.hba1c.status", "DM", {"ok": "ok", "mild_high": "attention", "high": "attention", "very_high": "alert"}[band],
                    f"dm.hba1c.{band}", v=p["latest"], target=t["target_max"], series=series_text(p["series"]))]


@rule("dm.hba1c.trend", "DM", lambda t: (
    f"ถ้ามีหลายค่า: ล่าสุด − แรกสุด ≤ {t['dm']['hba1c']['improving_delta']} = ดีขึ้น; ≥ +{t['dm']['hba1c']['worsening_delta']} = แย่ลง; ที่เหลือ = ใกล้เคียงเดิม"))
def r_hba1c_trend(c: Ctx):
    p, t = c.get("HbA1c"), c.t["dm"]["hba1c"]
    if not p or len(p["series"]) < 2: return []
    d = p["latest"] - p["first"]
    kind = "improving" if d <= t["improving_delta"] else "worsening" if d >= t["worsening_delta"] else "stable"
    return [finding("dm.hba1c.trend", "DM", "attention" if kind == "worsening" else "ok" if kind == "improving" else "info",
                    f"dm.hba1c.trend.{kind}", series=series_text(p["series"]), delta=d)]


@rule("dm.hba1c.rapid_drop", "DM", lambda t: f"[เฉพาะแพทย์] HbA1c ลดลงรวม ≥ {t['dm']['hba1c']['rapid_drop']} จุด (ไม่ทราบช่วงเวลาระหว่างค่า)")
def r_hba1c_rapid(c: Ctx):
    p, t = c.get("HbA1c"), c.t["dm"]["hba1c"]
    if not p or len(p["series"]) < 2 or p["first"] - p["latest"] < t["rapid_drop"]: return []
    return [finding("dm.hba1c.rapid_drop", "DM", "info", "dm.hba1c.rapid_drop", True, drop=p["first"] - p["latest"], series=series_text(p["series"]))]


@rule("dm.fbs.status", "DM", lambda t: (
    f"FBS ล่าสุด < {t['dm']['fbs']['low_below']} = ต่ำ (แจ้งเตือน); < {t['dm']['fbs']['slightly_low_below']} = ค่อนข้างต่ำ; "
    f"{t['dm']['fbs']['target'][0]}-{t['dm']['fbs']['target'][1]} = อยู่ในเป้า; < {t['dm']['fbs']['high_from']} = สูงกว่าเป้า; ≥ {t['dm']['fbs']['high_from']} = สูงมาก (แจ้งเตือน)"))
def r_fbs(c: Ctx):
    p, t = c.get("FBS"), c.t["dm"]["fbs"]
    if not p: return []
    v, (lo, hi) = p["latest"], t["target"]
    band = "low" if v < t["low_below"] else "slightly_low" if v < t["slightly_low_below"] else "ok" if v <= hi else "above" if v < t["high_from"] else "high"
    level = {"low": "alert", "slightly_low": "attention", "ok": "ok", "above": "attention", "high": "alert"}[band]
    return [finding("dm.fbs.status", "DM", level, f"dm.fbs.{band}", v=v, lo=lo, hi=hi, low=t["low_below"], series=series_text(p["series"]))]


# ============================================================ HT
def _bp_targets(c: Ctx, which: str) -> tuple[float, float]:
    t = c.t["ht"][which]
    return tuple(t["target_comorbid"] if c.comorbid else t["target_general"])  # type: ignore[return-value]


@rule("ht.clinic.status", "HT", lambda t: (
    f"BP คลินิกล่าสุด: เป้า < {t['ht']['clinic']['target_general'][0]}/{t['ht']['clinic']['target_general'][1]} "
    f"(< {t['ht']['clinic']['target_comorbid'][0]}/{t['ht']['clinic']['target_comorbid'][1]} ถ้าบันทึกว่ามี DM หรือ CKD); "
    f"≥ {t['ht']['clinic']['crisis'][0]} หรือ ≥ {t['ht']['clinic']['crisis'][1]} = วิกฤต (แจ้งเตือน)"))
def r_clinic_bp(c: Ctx):
    p = c.get("BP")
    if not p: return []
    sbp, dbp = p["latest"]
    ts, td = _bp_targets(c, "clinic")
    cs, cd = c.t["ht"]["clinic"]["crisis"]
    out = []
    if sbp >= cs or dbp >= cd:
        out.append(finding("ht.clinic.status", "HT", "alert", "ht.clinic.crisis", sbp=sbp, dbp=dbp))
        out.append(finding("ht.clinic.crisis.clinician", "HT", "info", "ht.clinic.crisis", True, sbp=sbp, dbp=dbp, crit=f"{cs}/{cd}"))
        return out
    ok = sbp < ts and dbp < td
    return [finding("ht.clinic.status", "HT", "ok" if ok else "attention", "ht.clinic.ok" if ok else "ht.clinic.above",
                    sbp=sbp, dbp=dbp, tsys=ts, tdia=td, comorbid_note=c.comorbid)]


@rule("ht.home.status", "HT", lambda t: (
    f"BP ที่บ้านล่าสุด: เป้า < {t['ht']['home']['target_general'][0]}/{t['ht']['home']['target_general'][1]} "
    f"(< {t['ht']['home']['target_comorbid'][0]}/{t['ht']['home']['target_comorbid'][1]} ถ้าบันทึกว่ามี DM หรือ CKD)"))
def r_home_bp(c: Ctx):
    p = c.get("HomeBP")
    if not p: return []
    sbp, dbp = p["latest"]
    ts, td = _bp_targets(c, "home")
    ok = sbp < ts and dbp < td
    return [finding("ht.home.status", "HT", "ok" if ok else "attention", "ht.home.ok" if ok else "ht.home.above", sbp=sbp, dbp=dbp, tsys=ts, tdia=td)]


@rule("ht.discordance", "HT", lambda t: (
    f"BP คลินิก ≥ {t['ht']['discordance']['clinic_high'][0]}/{t['ht']['discordance']['clinic_high'][1]} แต่บ้าน < "
    f"{t['ht']['discordance']['home_high'][0]}/{t['ht']['discordance']['home_high'][1]} → เข้าได้กับ white-coat; กลับกัน → masked (ให้แพทย์ตัดสิน)"))
def r_discord(c: Ctx):
    cl, hm, d = c.get("BP"), c.get("HomeBP"), c.t["ht"]["discordance"]
    if not cl or not hm: return []
    (cs, cd), (hs, hd) = cl["latest"], hm["latest"]
    clinic_high = cs >= d["clinic_high"][0] or cd >= d["clinic_high"][1]
    home_high = hs >= d["home_high"][0] or hd >= d["home_high"][1]
    if clinic_high == home_high: return []
    kind = "white_coat" if clinic_high else "masked"
    vals = dict(csbp=cs, cdbp=cd, hsbp=hs, hdbp=hd, ct=f"{d['clinic_high'][0]}/{d['clinic_high'][1]}", ht=f"{d['home_high'][0]}/{d['home_high'][1]}")
    return [finding("ht.discordance", "HT", "attention", f"ht.discord.{kind}", **vals),
            finding("ht.discordance.clinician", "HT", "info", f"ht.discord.{kind}", True, **vals)]


# ============================================================ Obesity
@rule("ob.bmi.class", "Obesity", lambda t: (
    f"BMI (เกณฑ์เอเชีย) < {t['obesity']['bmi_asian']['underweight_below']} น้ำหนักต่ำ; < {t['obesity']['bmi_asian']['normal_below']} ปกติ; "
    f"< {t['obesity']['bmi_asian']['overweight_below']} น้ำหนักเกิน; < {t['obesity']['bmi_asian']['obese1_below']} อ้วนระดับ 1; มากกว่านั้น อ้วนระดับ 2"))
def r_bmi(c: Ctx):
    p, t = c.get("BMI"), c.t["obesity"]["bmi_asian"]
    computed = False
    if not p:
        bw, ht = c.get("BW"), c.get("Height")
        if not (bw and ht): return []
        p, computed = {"latest": round(bw["latest"] / (ht["latest"] / 100) ** 2, 1)}, True
    v = p["latest"]
    band = "underweight" if v < t["underweight_below"] else "normal" if v < t["normal_below"] else "overweight" if v < t["overweight_below"] else "obese1" if v < t["obese1_below"] else "obese2"
    return [finding("ob.bmi.class", "Obesity", "ok" if band == "normal" else "attention", f"ob.bmi.{band}", v=v, computed_note=computed)]


@rule("ob.weight.change", "Obesity", lambda t: f"น้ำหนักเปลี่ยนจากค่าแรกสุดถึงล่าสุด ≥ {t['obesity']['weight_change']['significant_pct']}% ถือว่ามีนัย (ลด/เพิ่ม)")
def r_weight(c: Ctx):
    p, t = c.get("BW"), c.t["obesity"]["weight_change"]
    if not p or len(p["series"]) < 2: return []
    delta = p["latest"] - p["first"]
    pct = abs(delta) / p["first"] * 100
    kind = "stable" if pct < t["significant_pct"] else ("loss" if delta < 0 else "gain")
    return [finding("ob.weight.change", "Obesity", "ok" if kind == "loss" else "attention" if kind == "gain" else "info", f"ob.weight.{kind}",
                    abs=abs(delta), pct=round(pct, 1), series=series_text(p["series"]))]


# ============================================================ CKD
def _stage(v: float, t: dict) -> str:
    return "g1" if v >= t["g1_from"] else "g2" if v >= t["g2_from"] else "g3a" if v >= t["g3a_from"] else "g3b" if v >= t["g3b_from"] else "g4" if v >= t["g4_from"] else "g5"


def _uacr(c: Ctx):
    """UACR, or urine microalbumin (UMA) when written with an explicit mg/g unit; UMA in mg/L or without unit is skipped as invalid."""
    return c.get("UACR") or c.get("UMA")


def _egfr(c: Ctx) -> tuple[float | None, bool]:
    """(value, computed_by_system). Reported eGFR wins; otherwise compute from Cr + age + sex when available."""
    reported = c.get("eGFR")
    if reported: return reported["latest"], False
    cr = c.get("Creatinine")
    age, sex = c.patient.get("age"), c.patient.get("sex")
    if cr and age is not None and sex in ("M", "F"):
        return round(ckd_epi_2021(cr["latest"], age, sex), 1), True
    return None, False


@rule("ckd.egfr.stage", "CKD", lambda t: (
    f"eGFR ≥ {t['ckd']['egfr_stage']['g1_from']} G1; ≥ {t['ckd']['egfr_stage']['g2_from']} G2; ≥ {t['ckd']['egfr_stage']['g3a_from']} G3a; "
    f"≥ {t['ckd']['egfr_stage']['g3b_from']} G3b; ≥ {t['ckd']['egfr_stage']['g4_from']} G4; ต่ำกว่านั้น G5 (ถ้าไม่มี eGFR แต่มี Cr + อายุ + เพศ จะคำนวณ CKD-EPI 2021 และระบุว่าคำนวณโดยระบบ)"))
def r_egfr_stage(c: Ctx):
    v, computed = _egfr(c)
    if v is None: return []
    stage = _stage(v, c.t["ckd"]["egfr_stage"])
    level = "ok" if stage == "g1" else "info" if stage == "g2" else "alert" if stage in ("g4", "g5") else "attention"
    p = c.get("eGFR")
    return [finding("ckd.egfr.stage", "CKD", level, f"ckd.stage.{stage}", v=v, computed_note=computed, ckd_caveat=True, series=series_text(p["series"]) if p else fmt(v))]


@rule("ckd.egfr.trend", "CKD", lambda t: f"eGFR ล่าสุดต่างจากค่าแรกสุด ≥ {t['ckd']['decline_flag']} (ลด = แย่ลง, เพิ่ม = ดีขึ้น)")
def r_egfr_trend(c: Ctx):
    p = c.get("eGFR")
    if not p or len(p["series"]) < 2: return []
    d = p["latest"] - p["first"]
    lim = c.t["ckd"]["decline_flag"]
    if d <= -lim: return [finding("ckd.egfr.trend", "CKD", "attention", "ckd.trend.worsening", series=series_text(p["series"]))]
    if d >= lim: return [finding("ckd.egfr.trend", "CKD", "ok", "ckd.trend.improving", series=series_text(p["series"]))]
    return []


@rule("ckd.crosscheck", "CKD", lambda t: (
    f"[เฉพาะแพทย์] เทียบ eGFR ที่ระบุกับค่าคำนวณ CKD-EPI 2021 จาก Cr + อายุ + เพศ: ต่างเกิน {t['ckd']['crosscheck']['tolerance_pct']}% และเกิน {t['ckd']['crosscheck']['tolerance_abs']} หน่วย = ตรวจสอบ"))
def r_crosscheck(c: Ctx):
    rep, cr = c.get("eGFR"), c.get("Creatinine")
    age, sex = c.patient.get("age"), c.patient.get("sex")
    if not rep or not cr: return []
    if age is None or sex not in ("M", "F"):
        return [finding("data.need_age_sex", "CKD", "info", "data.need_age_sex", True)]
    comp = ckd_epi_2021(cr["latest"], age, sex)
    tol = c.t["ckd"]["crosscheck"]
    diff = abs(rep["latest"] - comp)
    bad = diff > tol["tolerance_abs"] and diff / max(comp, 1) * 100 > tol["tolerance_pct"]
    return [finding("ckd.crosscheck", "CKD", "attention" if bad else "info", "ckd.crosscheck.mismatch" if bad else "ckd.crosscheck.ok", True,
                    reported=rep["latest"], computed=round(comp, 1), cr=cr["latest"], age=age, sex="ชาย" if sex == "M" else "หญิง")]


@rule("ckd.albuminuria_missing", "CKD", lambda t: "[เฉพาะแพทย์] มี CKD ในบันทึกแต่ไม่มีค่า UACR → แจ้งว่าจัดระยะ albuminuria (A) ไม่ได้")
def r_albuminuria(c: Ctx):
    if ({"CKD", "DN"} & c.problems) and not _uacr(c):
        return [finding("ckd.albuminuria_missing", "CKD", "info", "ckd.albuminuria_missing", True)]
    return []


@rule("dm.uacr_missing", "DM", lambda t: "[เฉพาะแพทย์] มี DM ในบันทึก (ไม่มี CKD/DN) แต่ไม่มีค่า UACR → แจ้งว่าไม่มีข้อมูลคัดกรองไตจากเบาหวาน")
def r_uacr_missing(c: Ctx):
    if "DM" in c.problems and not ({"CKD", "DN"} & c.problems) and not _uacr(c):
        return [finding("dm.uacr_missing", "DM", "info", "dm.uacr_missing", True)]
    return []


# ============================================================ Today (dated line)
_SYMPTOMS = ("dizziness", "vertigo", "headache", "palpitations", "edema", "dyspnea")


@rule("life.smoking", "Today", lambda t: "บรรทัดวันที่ล่าสุดบอกว่า 'ยังสูบบุหรี่' → ข้อความให้ความรู้เรื่องเลิกบุหรี่ (เบอร์สายด่วนจาก targets.json); 'เลิกแล้ว' → ข้อความชื่นชม")
def r_smoking(c: Ctx):
    v = c.concepts.get("smoking")
    q = c.t["lifestyle"]["quitline"]
    if v == "current": return [finding("life.smoking", "Today", "attention", "life.smoking.current", quitline=q)]
    if v == "former": return [finding("life.smoking", "Today", "ok", "life.smoking.former")]
    return []


@rule("life.symptoms", "Today", lambda t: "บรรทัดวันที่ล่าสุดมีอาการ (เวียนศีรษะ บ้านหมุน ปวดศีรษะ ใจสั่น บวม เหนื่อย) → แนะนำให้แจ้งแพทย์/พยาบาล (ไม่สรุปสาเหตุ)")
def r_symptoms(c: Ctx):
    labels = [s["label"] for s in (c.visit["concepts"] if c.visit else []) if s["id"] in _SYMPTOMS and s["value"] == "present"]
    return [finding("life.symptoms", "Today", "attention", "life.symptoms", list="、".join(dict.fromkeys(labels)))] if labels else []


@rule("life.intake", "Today", lambda t: "บรรทัดวันที่ล่าสุดบอกว่ารับประทานได้น้อยลง → แนะนำให้แจ้งแพทย์/พยาบาล")
def r_intake(c: Ctx):
    return [finding("life.intake", "Today", "attention", "life.intake.reduced")] if c.concepts.get("reduced_intake") == "present" else []


@rule("xr.dm_hypo", "Today", lambda t: "[เฉพาะแพทย์] มี DM ในบันทึก + (เวียนศีรษะ หรือ ใจสั่น) + รับประทานได้น้อยลง → เตือนให้พิจารณาภาวะน้ำตาลต่ำและยาที่ใช้ (ไม่ตัดสิน)")
def r_dm_hypo(c: Ctx):
    if "DM" not in c.problems or c.concepts.get("reduced_intake") != "present": return []
    sx = [s["label"] for s in (c.visit["concepts"] if c.visit else []) if s["id"] in ("dizziness", "palpitations") and s["value"] == "present"]
    if not sx: return []
    ctx = []
    h, f = c.get("HbA1c"), c.get("FBS")
    if h: ctx.append(f"HbA1c {series_text(h['series'])}")
    if f: ctx.append(f"FBS ล่าสุด {fmt(f['latest'])}")
    return [finding("xr.dm_hypo", "Today", "info", "xr.dm_hypo", True, list="、".join(dict.fromkeys(sx)), context=(" (" + "; ".join(ctx) + ")") if ctx else "")]


# ============================================================ Dyslipidemia
def _ldl_goal(c: Ctx) -> int:
    t = c.t["dlp"]["ldl"]
    return t["goal_ascvd"] if c.ascvd else t["goal_dm_or_ckd"] if c.comorbid else t["goal_default"]


@rule("dlp.ldl.status", "Dyslipidemia", lambda t: (
    f"LDL ล่าสุด < เป้า = อยู่ในเป้า (เป้า {t['dlp']['ldl']['goal_default']}; {t['dlp']['ldl']['goal_dm_or_ckd']} ถ้าบันทึกว่ามี DM หรือ CKD); "
    f"ไม่เกินเป้า + {t['dlp']['ldl']['near_margin']} = ใกล้เป้า; มากกว่านั้น = สูงกว่าเป้า; ≥ {t['dlp']['ldl']['very_high_from']} = สูงมาก (แจ้งเตือน) "
    "[เฉพาะแพทย์: เตือนว่าเป้า LDL จริงขึ้นกับความเสี่ยง ASCVD ซึ่งบันทึกไม่ได้ระบุ]"))
def r_ldl(c: Ctx):
    p, t = c.get("LDL"), c.t["dlp"]["ldl"]
    if not p: return []
    v, goal = p["latest"], _ldl_goal(c)
    band = "very_high" if v >= t["very_high_from"] else "ok" if v < goal else "near" if v < goal + t["near_margin"] else "high"
    level = {"ok": "ok", "near": "attention", "high": "attention", "very_high": "alert"}[band]
    basis = "บันทึกมี CAD หรือ Stroke ชนิดขาดเลือด" if c.ascvd else "บันทึกมี DM/CKD/DN/CAD/Stroke" if c.comorbid else "บันทึกไม่มี DM/CKD/CAD/Stroke"
    tail = ("ใช้เป้าของผู้ที่มี ASCVD แล้ว (บางแนวทางใช้ต่ำกว่านี้ในกลุ่มเสี่ยงสูงมาก)" if c.ascvd else
            "เป้าจริงขึ้นกับความเสี่ยง ASCVD ซึ่งบันทึกไม่ได้ระบุ (ถ้ามี ASCVD หรือความเสี่ยงสูงมาก เป้าต่ำกว่านี้)")
    return [finding("dlp.ldl.status", "Dyslipidemia", level, f"dlp.ldl.{band}", v=v, goal=goal, comorbid_note=c.comorbid and not c.ascvd, ascvd_note=c.ascvd, series=series_text(p["series"])),
            finding("dlp.goal_depends", "Dyslipidemia", "info", "dlp.goal_depends", True, goal=goal, basis=basis, tail=tail)]


@rule("dlp.ldl.trend", "Dyslipidemia", lambda t: f"ถ้ามีหลายค่า: LDL ล่าสุดเทียบค่าแรกสุดลด ≥ {t['dlp']['ldl']['trend_pct']}% = ดีขึ้น; เพิ่ม ≥ {t['dlp']['ldl']['trend_pct']}% = แย่ลง")
def r_ldl_trend(c: Ctx):
    p, t = c.get("LDL"), c.t["dlp"]["ldl"]
    if not p or len(p["series"]) < 2 or not p["first"]: return []
    pct = (p["latest"] - p["first"]) / p["first"] * 100
    if pct <= -t["trend_pct"]: return [finding("dlp.ldl.trend", "Dyslipidemia", "ok", "dlp.ldl.trend.improving", series=series_text(p["series"]))]
    if pct >= t["trend_pct"]: return [finding("dlp.ldl.trend", "Dyslipidemia", "attention", "dlp.ldl.trend.worsening", series=series_text(p["series"]))]
    return []


@rule("dlp.tg.status", "Dyslipidemia", lambda t: (
    f"TG ล่าสุด < {t['dlp']['tg']['borderline_from']} ปกติ; < {t['dlp']['tg']['high_from']} ค่อนข้างสูง; < {t['dlp']['tg']['very_high_from']} สูง; "
    f"≥ {t['dlp']['tg']['very_high_from']} สูงมาก (แจ้งเตือน เสี่ยงตับอ่อนอักเสบ)"))
def r_tg(c: Ctx):
    p, t = c.get("TG"), c.t["dlp"]["tg"]
    if not p: return []
    v = p["latest"]
    band = "normal" if v < t["borderline_from"] else "borderline" if v < t["high_from"] else "high" if v < t["very_high_from"] else "very_high"
    level = {"normal": "ok", "borderline": "attention", "high": "attention", "very_high": "alert"}[band]
    return [finding("dlp.tg.status", "Dyslipidemia", level, f"dlp.tg.{band}", v=v, b=t["borderline_from"], h=t["high_from"], vh=t["very_high_from"])]


@rule("dlp.hdl.status", "Dyslipidemia", lambda t: (
    f"HDL ล่าสุด ต่ำกว่า {t['dlp']['hdl']['low_below_male']} (ชาย) / {t['dlp']['hdl']['low_below_female']} (หญิง) = ต่ำ "
    "(ถ้าไม่ระบุเพศ ใช้เกณฑ์ผู้ชายและบอกแพทย์)"))
def r_hdl(c: Ctx):
    p, t = c.get("HDL"), c.t["dlp"]["hdl"]
    if not p: return []
    sex = c.patient.get("sex")
    low = t["low_below_female"] if sex == "F" else t["low_below_male"]
    out = [finding("dlp.hdl.status", "Dyslipidemia", "attention" if p["latest"] < low else "ok", "dlp.hdl.low" if p["latest"] < low else "dlp.hdl.ok", v=p["latest"], low=low)]
    if sex not in ("M", "F"):
        out.append(finding("data.need_sex_hdl", "Dyslipidemia", "info", "data.need_sex_hdl", True, low=low))
    return out


@rule("dlp.tc.status", "Dyslipidemia", lambda t: f"TC ล่าสุด < {t['dlp']['tc']['borderline_from']} ที่ต้องการ; < {t['dlp']['tc']['high_from']} ค่อนข้างสูง; มากกว่านั้น สูง")
def r_tc(c: Ctx):
    p, t = c.get("TC"), c.t["dlp"]["tc"]
    if not p: return []
    v = p["latest"]
    band = "desirable" if v < t["borderline_from"] else "borderline" if v < t["high_from"] else "high"
    return [finding("dlp.tc.status", "Dyslipidemia", "ok" if band == "desirable" else "attention", f"dlp.tc.{band}", v=v, b=t["borderline_from"], h=t["high_from"])]


# ============================================================ Anemia / CBC
@rule("anemia.hb.status", "Anemia", lambda t: (
    f"Hb ล่าสุด: ซีดเมื่อ < {t['anemia']['hb']['anemia_below_male']} (ชาย) / < {t['anemia']['hb']['anemia_below_female']} (หญิง); "
    f"เล็กน้อย ≥ {t['anemia']['hb']['mild_from']}; ปานกลาง ≥ {t['anemia']['hb']['moderate_from']}; รุนแรง ต่ำกว่านั้น (แจ้งเตือน) "
    "— **ต้องระบุเพศ** ถ้าไม่ระบุจะไม่แปลผล Hb และบอกแพทย์ (ไม่ได้แยกตั้งครรภ์/ผู้สูงอายุ)"))
def r_hb(c: Ctx):
    p, t = c.get("Hb"), c.t["anemia"]["hb"]
    if not p: return []
    sex = c.patient.get("sex")
    if sex not in ("M", "F"):
        return [finding("data.need_sex_hb", "Anemia", "info", "data.need_sex_hb", True)]
    v = p["latest"]
    cut = t["anemia_below_male"] if sex == "M" else t["anemia_below_female"]
    band = "normal" if v >= cut else "mild" if v >= t["mild_from"] else "moderate" if v >= t["moderate_from"] else "severe"
    level = {"normal": "ok", "mild": "attention", "moderate": "attention", "severe": "alert"}[band]
    return [finding("anemia.hb.status", "Anemia", level, f"anemia.hb.{band}", v=v, series=series_text(p["series"]))]


@rule("anemia.hb.trend", "Anemia", lambda t: f"ถ้ามีหลายค่า: Hb ล่าสุดต่างจากค่าแรกสุด ≥ {t['anemia']['hb']['trend_delta']} g/dL (เพิ่ม = ดีขึ้น, ลด = แย่ลง)")
def r_hb_trend(c: Ctx):
    p, t = c.get("Hb"), c.t["anemia"]["hb"]
    if not p or len(p["series"]) < 2 or c.patient.get("sex") not in ("M", "F"): return []
    d = p["latest"] - p["first"]
    if d >= t["trend_delta"]: return [finding("anemia.hb.trend", "Anemia", "ok", "anemia.hb.trend.improving", series=series_text(p["series"]))]
    if d <= -t["trend_delta"]: return [finding("anemia.hb.trend", "Anemia", "attention", "anemia.hb.trend.worsening", series=series_text(p["series"]))]
    return []


@rule("anemia.mcv.class", "Anemia", lambda t: f"MCV ล่าสุด < {t['anemia']['mcv']['micro_below']} เม็ดเลือดแดงเล็ก; > {t['anemia']['mcv']['macro_above']} ใหญ่; ที่เหลือปกติ")
def r_mcv(c: Ctx):
    p, t = c.get("MCV"), c.t["anemia"]["mcv"]
    if not p: return []
    v = p["latest"]
    band = "micro" if v < t["micro_below"] else "macro" if v > t["macro_above"] else "normal"
    return [finding("anemia.mcv.class", "Anemia", "ok" if band == "normal" else "attention", f"anemia.mcv.{band}", v=v)]


@rule("anemia.mentzer", "Anemia", lambda t: f"[เฉพาะแพทย์] MCV < {t['anemia']['mcv']['micro_below']} และมี RBC: Mentzer = MCV/RBC; < {t['anemia']['mentzer_cut']} เข้าได้กับ thalassemia trait, ≥ เกณฑ์ เข้าได้กับขาดธาตุเหล็ก (ประกอบเท่านั้น)")
def r_mentzer(c: Ctx):
    mcv, rbc, t = c.get("MCV"), c.get("RBC"), c.t["anemia"]
    if not mcv or not rbc or mcv["latest"] >= t["mcv"]["micro_below"]: return []
    m = mcv["latest"] / rbc["latest"]
    interp = "เข้าได้กับ thalassemia trait" if m < t["mentzer_cut"] else "เข้าได้กับภาวะขาดธาตุเหล็ก"
    return [finding("anemia.mentzer", "Anemia", "info", "anemia.mentzer", True, m=round(m, 1), interp=interp, cut=t["mentzer_cut"])]


@rule("anemia.rdw", "Anemia", lambda t: f"[เฉพาะแพทย์] RDW ล่าสุด > {t['anemia']['rdw_high_above']}% = สูง")
def r_rdw(c: Ctx):
    p, t = c.get("RDW"), c.t["anemia"]
    if not p or p["latest"] <= t["rdw_high_above"]: return []
    return [finding("anemia.rdw", "Anemia", "info", "anemia.rdw_high", True, v=p["latest"], cut=t["rdw_high_above"])]


@rule("anemia.crosscheck", "Anemia", lambda t: (
    f"[เฉพาะแพทย์] ตรวจการพิมพ์ผิด: MCV ที่ระบุต่างจาก Hct/RBC×10 เกิน {t['anemia']['crosscheck']['mcv_tolerance_pct']}%; "
    f"Hct/Hb อยู่นอก {t['anemia']['crosscheck']['hct_hb_ratio'][0]}-{t['anemia']['crosscheck']['hct_hb_ratio'][1]}"))
def r_cbc_crosscheck(c: Ctx):
    mcv, hct, rbc, hb, t = c.get("MCV"), c.get("Hct"), c.get("RBC"), c.get("Hb"), c.t["anemia"]["crosscheck"]
    out = []
    if mcv and hct and rbc:
        calc = hct["latest"] / rbc["latest"] * 10
        if abs(calc - mcv["latest"]) / mcv["latest"] * 100 > t["mcv_tolerance_pct"]:
            out.append(finding("anemia.crosscheck.mcv", "Anemia", "attention", "anemia.crosscheck.mcv", True, mcv=mcv["latest"], calc=round(calc, 1)))
    if hct and hb:
        ratio = hct["latest"] / hb["latest"]
        if not t["hct_hb_ratio"][0] <= ratio <= t["hct_hb_ratio"][1]:
            out.append(finding("anemia.crosscheck.hcthb", "Anemia", "attention", "anemia.crosscheck.hcthb", True, r=round(ratio, 2), lo=t["hct_hb_ratio"][0], hi=t["hct_hb_ratio"][1]))
    return out


# ============================================================ Warfarin / INR
@rule("warfarin.inr.status", "Warfarin", lambda t: (
    f"INR ล่าสุดเทียบเป้าที่ระบุในบรรทัด (goal a-b; ถ้าไม่ระบุใช้ {t['warfarin']['default_goal'][0]}-{t['warfarin']['default_goal'][1]} และบอกแพทย์): "
    f"ในช่วง = ตามเป้า; ต่ำกว่า/สูงกว่า = แจ้งแพทย์; ≥ {t['warfarin']['alert_above']} และสูงกว่าเป้า = สูงมาก (แจ้งเตือน) "
    "— ระบบไม่แนะนำขนาดยา ไม่แนะนำให้ปรับยา"))
def r_inr(c: Ctx):
    p, t = c.get("INR"), c.t["warfarin"]
    if not p: return []
    g = c.get("INRgoal")
    lo, hi = (g["latest"][0], g["latest"][1]) if g else tuple(t["default_goal"])
    v = p["latest"]
    band = "high" if (v >= t["alert_above"] and v > hi) else "ok" if lo <= v <= hi else "below" if v < lo else "above"
    level = {"ok": "ok", "below": "attention", "above": "attention", "high": "alert"}[band]
    out = [finding("warfarin.inr.status", "Warfarin", level, f"warfarin.inr.{band}", v=v, lo=lo, hi=hi)]
    if not g:
        out.append(finding("warfarin.goal_default", "Warfarin", "info", "warfarin.goal_default", True, lo=lo, hi=hi))
    return out


@rule("warfarin.hints", "Warfarin", lambda t: "[เฉพาะแพทย์] มี Warfarin ในบันทึก + รับประทานได้น้อยลง → เตือนว่า INR อาจสูงขึ้น; + เลือดออก/ฟกช้ำ → เตือนให้ประเมินเลือดออก")
def r_warfarin_hints(c: Ctx):
    if "Warfarin" not in c.problems and not c.get("INR"): return []
    out = []
    if c.concepts.get("reduced_intake") == "present":
        out.append(finding("warfarin.intake", "Warfarin", "info", "warfarin.intake", True))
    if c.concepts.get("bleeding") == "present":
        out.append(finding("warfarin.bleeding", "Warfarin", "info", "warfarin.bleeding", True, list=_bleeding_list(c)))
    return out


def _bleeding_list(c: Ctx) -> str:
    return "、".join(s["source"] for s in (c.visit["concepts"] if c.visit else []) if s["id"] == "bleeding" and s["value"] == "present")


@rule("life.bleeding", "Today", lambda t: "บรรทัดวันที่ล่าสุดมีเลือดออก/ฟกช้ำ/ถ่ายดำ → แนะนำให้แจ้งแพทย์/พยาบาลทันที (ถ้ามี Warfarin ระดับแจ้งเตือน)")
def r_bleeding(c: Ctx):
    if c.concepts.get("bleeding") != "present": return []
    on_warfarin = "Warfarin" in c.problems or bool(c.get("INR"))
    return [finding("life.bleeding", "Today", "alert" if on_warfarin else "attention", "life.bleeding", list=_bleeding_list(c))]


# ============================================================ driver
def evaluate(parsed: dict[str, Any], patient: dict[str, Any] | None = None, targets: dict[str, Any] | None = None, use_custom: bool = True, custom_override: dict[str, Any] | None = None) -> dict[str, Any]:
    patient = _clean_patient(patient or {})
    t = targets or load_targets()
    ctx = Ctx(parsed, patient, t)
    findings, notes, warnings = [], [], []
    from . import custom_rules
    ids = {r["id"] for r in RULES}
    if custom_override is not None:                                    # the web editor's "try" button: evaluate a draft that is not saved
        custom, custom_errors, disabled = custom_rules.validate(custom_override, ids)
    else:
        custom, custom_errors, disabled = custom_rules.load(ids) if use_custom else ([], [], [])
    for r in RULES:
        if r["id"] in disabled:
            continue
        for f in r["fn"](ctx):
            (notes if f["clinician_only"] else findings).append(f)
    cf, cn, skipped = custom_rules.evaluate_custom(ctx, custom)
    findings += cf; notes += cn
    for msg in custom_errors + skipped:
        notes.append(finding("data.custom_error", "-", "attention", "data.custom_error", True, msg=msg))
    if disabled:
        notes.append(finding("data.disabled_rules", "-", "info", "data.disabled_rules", True, ids=", ".join(disabled)))
    # data quality: values skipped because they need checking; values read but without a rule
    for prob in parsed["problems"]:
        for v in prob["values"]:
            if v["invalid"]:
                notes.append(finding("data.invalid", prob["name"], "attention", "data.invalid", True, param=v["param"], why="; ".join(v["flags"])))
            elif not v["has_rules"]:
                notes.append(finding("data.no_rules", prob["name"], "info", "data.no_rules", True, param=v["param"],
                                     latest=series_text([v["latest"]])))
        if prob["unparsed"]:
            notes.append(finding("data.unparsed", prob["name"], "info", "data.unparsed", True, text=prob["unparsed"]))
    for ul in parsed["unparsed_lines"]:
        notes.append(finding("data.unparsed", "-", "info", "data.unparsed", True, text=ul["text"]))
    for v in parsed["visits"]:
        if v["leftover"]:
            notes.append(finding("data.unparsed", "Today", "info", "data.unparsed", True, text=" ".join(v["leftover"])))
        if v["date_warning"]:
            warnings.append(f"{v['source'][:40]}: {v['date_warning']}")
    warnings += parsed["warnings"]
    return {"findings": findings, "clinician_notes": notes, "warnings": warnings, "patient": patient,
            "problems_present": sorted(ctx.problems), "visit_date_be": ctx.visit["date_be"] if ctx.visit else None,
            "targets_status": _status(t)}


def _status(t: dict[str, Any]) -> str:
    from . import signoff
    return signoff.effective_status(t["_meta"].get("status"))


def _clean_patient(p: dict[str, Any]) -> dict[str, Any]:
    age, sex = p.get("age"), (p.get("sex") or "").upper()[:1]
    try:
        age = float(age) if age not in (None, "") else None
    except (TypeError, ValueError):
        age = None
    if age is not None and not (0 < age < 125):
        age = None
    tcvr = p.get("tcvr")
    try:
        tcvr = float(tcvr) if tcvr not in (None, "") else None
    except (TypeError, ValueError):
        tcvr = None
    if tcvr is not None and not (0 <= tcvr <= 100):
        tcvr = None
    return {"age": age, "sex": sex if sex in ("M", "F") else None, "tcvr": tcvr}


from . import rules_extra  # noqa: E402,F401  (registers the DN/DR/MAFLD/CAD/Stroke/COPD/Asthma/Risk rules)
