import datetime
import unittest

from engine.parse_note import parse_note
from engine.rules import evaluate

TODAY = datetime.date(2026, 10, 22)


def run(note, age=60, sex="M", tcvr=None):
    return evaluate(parse_note(note, today=TODAY), {"age": age, "sex": sex, "tcvr": tcvr})


def keys(r):
    return [f["key"] for f in r["findings"]]


def notes(r):
    return [n["key"] for n in r["clinician_notes"]]


class Albuminuria(unittest.TestCase):
    def test_bands_and_boundaries(self):
        self.assertIn("ckd.uacr.a1", keys(run("DM : UACR 29.9")))
        self.assertIn("ckd.uacr.a2", keys(run("DM : UACR 30")))
        self.assertIn("ckd.uacr.a2", keys(run("DM : UACR 300")))
        self.assertIn("ckd.uacr.a3", keys(run("DM : UACR 301")))

    def test_uma_needs_an_explicit_mg_per_g_unit(self):
        self.assertIn("ckd.uacr.a2", keys(run("DM : UMA 40 mg/g")))
        for bad in ("DM : UMA 40", "DM : UMA 40 mg/L"):                                    # could be mg/L or mg/24h: never guessed
            r = run(bad); self.assertFalse([k for k in keys(r) if k.startswith("ckd.uacr")], bad)
            self.assertIn("data.invalid", notes(r))

    def test_dn_group_and_doctor_hint(self):
        r = run("DM/DN : UACR 120 mg/g")
        self.assertEqual({f["problem"] for f in r["findings"] if f["key"].startswith("ckd.uacr")}, {"DN"})
        self.assertIn("dn.possible", notes(r))

    def test_missing_uacr_hints(self):
        self.assertIn("dm.uacr_missing", notes(run("DM : HbA1c 7")))
        self.assertIn("ckd.albuminuria_missing", notes(run("DN : eGFR 50")))
        self.assertNotIn("dm.uacr_missing", notes(run("DM : HbA1c 7 UMA 10 mg/g")))

    def test_kdigo_risk_grid(self):
        r = run("CKD : eGFR 40 UACR 100")
        self.assertIn("สูงมาก", " ".join(n["values"]["risk"] for n in r["clinician_notes"] if n["key"] == "ckd.kdigo_risk"))


class KidneyUltrasound(unittest.TestCase):
    def test_negation_and_findings(self):
        r = run("CKD : Cr 1.5 U/S KUB increased echo, no hydro, stone")
        self.assertIn("ckd.us.parenchymal", keys(r)); self.assertIn("ckd.us.stone", keys(r)); self.assertNotIn("ckd.us.hydro", keys(r))
        self.assertIn("ckd.us.hydro", keys(run("CKD : U/S KUB hydronephrosis")))
        self.assertNotIn("ckd.us.hydro", keys(run("CKD : U/S KUB ไม่มี hydro")))

    def test_normal_is_not_reported_when_something_abnormal_is_also_written(self):
        self.assertIn("ckd.us.normal", keys(run("CKD : U/S KUB normal size")))
        self.assertNotIn("ckd.us.normal", keys(run("CKD : U/S KUB normal size, stone")))

    def test_mass_is_alert_and_cyst_is_doctor_only(self):
        r = run("CKD : U/S KUB renal mass, cyst")
        self.assertEqual([f["level"] for f in r["findings"] if f["key"] == "ckd.us.mass"], ["alert"])
        self.assertIn("ckd.us.cyst", notes(r)); self.assertNotIn("ckd.us.cyst", keys(r))

    def test_kub_words_are_not_unparsed_noise(self):
        self.assertNotIn("data.unparsed", notes(run("CKD : Cr 1.5 U/S KUB normal size both kidneys")))


class Retina(unittest.TestCase):
    def test_grades(self):
        for text, key in (("no DR", "dr.none"), ("NPDR mild", "dr.npdr_mild"), ("moderate NPDR", "dr.npdr_moderate"), ("NPDR severe", "dr.npdr_severe"),
                          ("PDR", "dr.pdr"), ("NPDR", "dr.npdr_unspecified")):
            self.assertIn(key, keys(run(f"DR : {text}")), text)

    def test_pdr_is_not_confused_with_npdr(self):
        self.assertNotIn("dr.pdr", keys(run("DR : NPDR mild")))
        self.assertNotIn("dr.pdr", keys(run("DR : non-proliferative moderate")))

    def test_contradiction_is_not_interpreted(self):
        r = run("DR : no DR, NPDR mild")
        self.assertEqual([k for k in keys(r) if k.startswith("dr.")], []); self.assertIn("dr.conflict", notes(r))

    def test_dme_and_treatment_history(self):
        r = run("DR : NPDR moderate, DME, laser")
        self.assertIn("dr.dme", keys(r))
        self.assertTrue(next(f for f in r["findings"] if f["key"] == "dr.npdr_moderate")["values"]["treated_note"])

    def test_missing_eye_exam_hint_for_dm(self):
        self.assertIn("dr.no_eye_exam", notes(run("DM : HbA1c 7")))
        self.assertNotIn("dr.no_eye_exam", notes(run("DM : HbA1c 7\nDR : no DR")))


class Liver(unittest.TestCase):
    def test_fib4_is_computed_and_checked_by_hand(self):
        # 60 * 60 / (180 * sqrt(85)) = 2.169...
        r = run("MAFLD : ALT 85 AST 60 Plt 180")
        f = next(f for f in r["findings"] if f["id"] == "liver.fib4")
        self.assertEqual(f["values"]["fib4"], "2.17"); self.assertEqual(f["key"], "liver.fib4.indet")

    def test_fib4_bands_and_age_cutoff(self):
        self.assertIn("liver.fib4.low", keys(run("MAFLD : ALT 30 AST 25 Plt 300", age=50)))
        self.assertIn("liver.fib4.high", keys(run("MAFLD : ALT 90 AST 120 Plt 100", age=50)))
        # 66*25/(150*sqrt(40)) = 1.74: between 1.3 and 2.0, so "low" only because the age>=65 cut-off is used
        self.assertIn("liver.fib4.low", keys(run("MAFLD : ALT 40 AST 25 Plt 150", age=66)))
        self.assertIn("liver.fib4.indet", keys(run("MAFLD : ALT 40 AST 25 Plt 150", age=60)))

    def test_fib4_not_used_below_35_and_not_without_age(self):
        r = run("MAFLD : ALT 80 AST 60 Plt 180", age=30)
        self.assertFalse([k for k in keys(r) if k.startswith("liver.fib4")]); self.assertIn("liver.fib4.young", notes(r))
        r = run("MAFLD : ALT 80 AST 60 Plt 180", age=None); self.assertIn("data.need_demo", notes(r))

    def test_missing_inputs_named(self):
        r = run("MAFLD : ALT 80 AST 60")
        self.assertEqual(next(n for n in r["clinician_notes"] if n["key"] == "liver.fib4.missing")["values"]["miss"], "Plt")

    def test_platelets_written_as_180000_are_scaled_and_disclosed(self):
        r = parse_note("MAFLD : Plt 180000")
        v = r["problems"][0]["values"][0]
        self.assertEqual(v["latest"], 180.0); self.assertTrue(v["converted"])

    def test_fibroscan_bands(self):
        for v, key in ((7.9, "low"), (8, "grey"), (11.9, "grey"), (12, "high")):
            self.assertIn(f"liver.lsm.{key}", keys(run(f"MAFLD : LSM {v}")), v)
        self.assertIn("liver.lsm.quality", notes(run("MAFLD : LSM 9")))

    def test_cap_bands(self):
        for v, key in ((200, "s0"), (250, "s1"), (270, "s2"), (300, "s3")):
            self.assertIn(f"liver.cap.{key}", keys(run(f"MAFLD : CAP {v}")), v)

    def test_discordant_fib4_and_lsm_is_flagged(self):
        self.assertIn("liver.discord", notes(run("MAFLD : ALT 90 AST 120 Plt 100 LSM 5", age=50)))

    def test_enzymes_use_the_worse_of_alt_ast(self):
        self.assertIn("liver.enz.high", keys(run("MAFLD : ALT 30 AST 130")))
        self.assertIn("liver.enz.ok", keys(run("MAFLD : ALT 40 AST 20")))


class AscvdAndStroke(unittest.TestCase):
    def goal(self, note):
        return next(n for n in run(note)["clinician_notes"] if n["key"] == "dlp.goal_depends")["values"]["goal"]

    def test_ldl_goal_ladder(self):
        self.assertEqual(self.goal("DLP : LDL 120"), "130")
        self.assertEqual(self.goal("DM : FBS 100\nDLP : LDL 120"), "100")
        self.assertEqual(self.goal("CAD : s/p PCI\nDLP : LDL 120"), "70")
        self.assertEqual(self.goal("Stroke : ischemic\nDLP : LDL 120"), "70")

    def test_unspecified_or_hemorrhagic_stroke_does_not_get_the_ascvd_goal(self):
        self.assertEqual(self.goal("Stroke : mRS 2\nDLP : LDL 120"), "100")
        self.assertEqual(self.goal("Stroke : hemorrhagic\nDLP : LDL 120"), "100")
        self.assertIn("stroke.type_unknown", notes(run("Stroke : mRS 2")))

    def test_bp_target_is_stricter_with_cad_or_stroke(self):
        self.assertIn("ht.clinic.above", keys(run("CAD : PCI\nHT : BP 135/85")))
        self.assertIn("ht.clinic.ok", keys(run("HT : BP 135/85")))

    def test_missing_secondary_prevention_drugs_are_only_a_doctor_note(self):
        r = run("CAD : s/p PCI")
        self.assertIn("ascvd.meds", notes(r)); self.assertNotIn("ascvd.meds", keys(r))
        self.assertNotIn("ascvd.meds", notes(run("CAD : s/p PCI, statin, aspirin")))
        r = run("Stroke : hemorrhagic")
        self.assertNotIn("ยาต้านเกล็ดเลือด", next(n for n in r["clinician_notes"] if n["key"] == "ascvd.meds")["values"]["miss"])

    def test_ef_bands(self):
        for v, key in ((55, "normal"), (45, "mild"), (40, "reduced")):
            self.assertIn(f"cad.ef.{key}", keys(run(f"CAD : LVEF {v}")), v)

    def test_mrs(self):
        n = next(n for n in run("Stroke : ischemic mRS 3")["clinician_notes"] if n["key"] == "stroke.mrs")
        self.assertIn("ปานกลาง", n["values"]["label"])
        self.assertIn("data.invalid", notes(run("Stroke : mRS 6")))                       # 6 = death, impossible for a patient


class Lungs(unittest.TestCase):
    def test_gold_grades(self):
        for v, g in ((85, "g1"), (60, "g2"), (40, "g3"), (25, "g4")):
            self.assertIn(f"copd.gold.{g}", keys(run(f"COPD : FEV1 {v} FEV1/FVC 0.6")), v)

    def test_no_obstruction_means_no_grade(self):
        r = run("COPD : FEV1 60 FEV1/FVC 0.8")
        self.assertFalse([k for k in keys(r) if k.startswith("copd.gold")]); self.assertIn("copd.ratio_inconsistent", notes(r))
        self.assertIn("copd.ratio_missing", notes(run("COPD : FEV1 60")))

    def test_ratio_as_percent_or_fraction(self):
        for text in ("0.62", "62%"):
            v = parse_note(f"COPD : FEV1/FVC {text}")["problems"][0]["values"][0]
            self.assertEqual((v["param"], v["latest"], v["invalid"]), ("FEV1FVC", 0.62, False))
        self.assertTrue(parse_note("COPD : FEV1/FVC 62")["problems"][0]["values"][0]["invalid"])      # 62 with no unit is never guessed

    def test_gold_group(self):
        def grp(note): return next(n["values"]["grp"] for n in run(note)["clinician_notes"] if n["key"] == "copd.group")
        self.assertEqual(grp("COPD : mMRC 0 CAT 5 Exac 0"), "A")
        self.assertEqual(grp("COPD : mMRC 2 Exac 0"), "B")
        self.assertEqual(grp("COPD : CAT 12 Exac 1"), "B")
        self.assertEqual(grp("COPD : CAT 5 Exac 2"), "E")
        self.assertEqual(grp("COPD : CAT 5 Exac 0 ExacHosp 1"), "E")
        self.assertIn("copd.group_missing", notes(run("COPD : CAT 5")))

    def test_spo2_in_copd_is_not_called_low_unless_very_low(self):
        self.assertFalse([k for k in keys(run("COPD : FEV1 60 FEV1/FVC 0.6 SpO2 91")) if k.startswith("spo2")])
        self.assertIn("spo2.very_low", keys(run("COPD : SpO2 87")))
        self.assertIn("spo2.copd", notes(run("COPD : SpO2 91")))
        self.assertIn("spo2.low", keys(run("Vitals : SpO2 92")))

    def test_asthma(self):
        for v, k in ((20, "good"), (19, "partly"), (16, "partly"), (15, "poor")):
            self.assertIn(f"asthma.act.{k}", keys(run(f"Asthma : ACT {v}")), v)
        self.assertIn("asthma.pef.green", keys(run("Asthma : PEF 360 PEFbest 450")))      # exactly 80%
        self.assertIn("asthma.pef.yellow", keys(run("Asthma : PEF 359 PEFbest 450")))
        self.assertIn("asthma.pef.red", keys(run("Asthma : PEF 200 PEFbest 450")))
        self.assertFalse([k for k in keys(run("Asthma : PEF 200")) if k.startswith("asthma.pef")])   # needs the personal best

    def test_respiratory_symptoms_only_matter_with_lung_disease(self):
        self.assertIn("life.resp", keys(run("COPD : FEV1 60\n22/10/69 : ไอ เสมหะ")))
        self.assertNotIn("life.resp", keys(run("DM : FBS 100\n22/10/69 : ไอ")))


class WaistAndBmi(unittest.TestCase):
    def test_waist_by_sex(self):
        self.assertIn("ob.waist.high", keys(run("Obesity : Waist 90", sex="M")))
        self.assertIn("ob.waist.ok", keys(run("Obesity : Waist 89", sex="M")))
        self.assertIn("ob.waist.high", keys(run("Obesity : Waist 80", sex="F")))
        self.assertIn("data.need_demo", notes(run("Obesity : Waist 100", sex=None)))

    def test_bmi_is_computed_from_weight_and_height_and_disclosed(self):
        r = run("Obesity : BW 80 Height 170")                      # 80 / 1.7^2 = 27.7
        f = next(f for f in r["findings"] if f["id"] == "ob.bmi.class")
        self.assertEqual((f["key"], f["values"]["v"], f["values"]["computed_note"]), ("ob.bmi.obese1", "27.7", True))
        r = run("Obesity : BMI 27 BW 80 Height 170")
        self.assertFalse(next(f for f in r["findings"] if f["id"] == "ob.bmi.class")["values"]["computed_note"])


class ThaiCvRisk(unittest.TestCase):
    def test_categories_and_boundaries(self):
        for v, k in ((9.9, "low"), (10, "moderate"), (19.9, "moderate"), (20, "high"), (29.9, "high"), (30, "very_high")):
            self.assertIn(f"risk.tcvr.{k}", keys(run("HT : BP 120/70", tcvr=v)), v)

    def test_invalid_entry_is_ignored(self):
        for bad in ("abc", "-5", "150", ""):
            self.assertFalse([k for k in keys(run("HT : BP 120/70", tcvr=bad)) if k.startswith("risk.tcvr")], bad)

    def test_value_is_labelled_as_manual_and_scope_is_checked(self):
        r = run("HT : BP 120/70", tcvr=15, age=80)
        self.assertIn("risk.tcvr.manual", notes(r)); self.assertIn("risk.tcvr.scope", notes(r))
        self.assertIn("risk.tcvr.scope", notes(run("CAD : PCI", tcvr=15)))
        self.assertNotIn("risk.tcvr.scope", notes(run("HT : BP 120/70", tcvr=15, age=50)))

    def test_completeness_check(self):
        full = "DM : FBS 100\nHT : BP 150/90 TC 200\n22/10/69 : ไม่สูบบุหรี่"
        n = next(n for n in run(full)["clinician_notes"] if n["key"].startswith("risk.inputs"))
        self.assertEqual(n["key"], "risk.inputs.complete")
        n = next(n for n in run("HT : BP 150/90", sex=None)["clinician_notes"] if n["key"].startswith("risk.inputs"))
        self.assertEqual(n["key"], "risk.inputs.missing")
        for what in ("เพศ", "การสูบบุหรี่", "ค่าเลือด"): self.assertIn(what, n["values"]["miss"])

    def test_completeness_says_when_diabetes_is_assumed_and_is_silent_for_other_notes(self):
        n = next(n for n in run("HT : BP 150/90 TC 200\n22/10/69 : ไม่สูบบุหรี่")["clinician_notes"] if n["key"].startswith("risk.inputs"))
        self.assertIn("ถือว่าไม่เป็น", n["values"]["assumed"])
        self.assertFalse([k for k in notes(run("CBC : Hb 12")) if k.startswith("risk.inputs")])
        self.assertFalse([k for k in notes(run("CAD : PCI\nHT : BP 150/90")) if k.startswith("risk.inputs")])      # already ASCVD: tool not applicable

    def test_no_score_is_ever_computed_by_the_system(self):
        r = run("DM : FBS 100\nHT : BP 150/90 TC 200\n22/10/69 : ไม่สูบบุหรี่")
        self.assertFalse([k for k in keys(r) if k.startswith("risk.")])


class MonkMeals(unittest.TestCase):
    def hint(self, note):
        return next((n for n in run(note)["clinician_notes"] if n["key"] == "monk.meals"), None)

    def test_one_or_two_meals_are_read_and_reach_the_doctor_only(self):
        for text, n in (("ฉัน 1 มื้อ", "1"), ("ฉัน 2 มื้อ", "2"), ("ฉันมื้อเดียว", "1"), ("ฉันสองมื้อ", "2"), ("ฉัน1มื้อ", "1")):
            r = run(f"DM : FBS 100\n22/10/69 : {text}")
            h = next(x for x in r["clinician_notes"] if x["key"] == "monk.meals")
            self.assertEqual(h["values"]["n"], n, text); self.assertIn("น้ำตาลต่ำ", h["values"]["why"])
            self.assertNotIn("monk.meals", keys(r))                                  # never a patient sentence
            self.assertNotIn("data.unparsed", [x["key"] for x in r["clinician_notes"]], text)

    def test_warfarin_gets_its_own_reason_and_unrelated_notes_get_a_generic_one(self):
        self.assertIn("INR", self.hint("Warfarin : INR 2.5\n22/10/69 : ฉัน 2 มื้อ")["values"]["why"])
        self.assertIn("พร้อมหรือหลังอาหาร", self.hint("HT : BP 130/80\n22/10/69 : ฉัน 2 มื้อ")["values"]["why"])

    def test_no_hint_without_the_statement_or_with_normal_wording(self):
        self.assertIsNone(self.hint("DM : FBS 100\n22/10/69 : ฉันได้น้อย"))          # "eats little" is a different concept
        self.assertIsNone(self.hint("DM : FBS 100"))

    def test_hint_never_names_a_drug_or_dose(self):
        text = self.hint("DM : FBS 100\n22/10/69 : ฉัน 1 มื้อ")["values"]["why"].lower()
        for bad in ("insulin", "metformin", "sulfonylurea", "อินซูลิน", "เพิ่มยา", "ลดยา", "หยุดยา"):
            self.assertNotIn(bad, text)


if __name__ == "__main__":
    unittest.main()
