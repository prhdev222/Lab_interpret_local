"""Boundary tests for the dyslipidemia, anemia/CBC and warfarin rules."""
import datetime
import unittest

from engine.parse_note import parse_note
from engine.rules import evaluate

TODAY = datetime.date(2026, 10, 22)


def run(note, age=60, sex="M"):
    return evaluate(parse_note(note, today=TODAY), {"age": age, "sex": sex})


def keys(r): return {f["key"] for f in r["findings"]}
def notes(r): return {f["key"] for f in r["clinician_notes"]}
def pick(r, prefix): return next(k for k in keys(r) if k.startswith(prefix))


class Dyslipidemia(unittest.TestCase):
    def test_ldl_general_goal(self):
        for v, want in ((129.9, "ok"), (130, "near"), (159.9, "near"), (160, "high"), (189.9, "high"), (190, "very_high")):
            self.assertEqual(pick(run(f"DLP : LDL {v}"), "dlp.ldl."), f"dlp.ldl.{want}", v)

    def test_ldl_stricter_goal_when_dm_or_ckd_is_listed(self):
        for v, want in ((99, "ok"), (100, "near"), (129, "near"), (130, "high")):
            self.assertEqual(pick(run(f"DM : FBS 100\nDLP : LDL {v}"), "dlp.ldl."), f"dlp.ldl.{want}", v)
        self.assertEqual(pick(run("CKD : eGFR 50\nDLP : LDL 110"), "dlp.ldl."), "dlp.ldl.near")
        self.assertEqual(pick(run("DLP : LDL 110"), "dlp.ldl."), "dlp.ldl.ok")

    def test_goal_depends_on_risk_is_told_to_the_doctor_only(self):
        r = run("DLP : LDL 110")
        self.assertIn("dlp.goal_depends", notes(r)); self.assertNotIn("dlp.goal_depends", keys(r))

    def test_ldl_trend(self):
        self.assertIn("dlp.ldl.trend.improving", keys(run("DLP : LDL 160->136")))        # exactly -15%
        self.assertFalse([k for k in keys(run("DLP : LDL 160->137")) if "trend" in k])
        self.assertIn("dlp.ldl.trend.worsening", keys(run("DLP : LDL 100->115")))

    def test_tg_bands(self):
        for v, want in ((149, "normal"), (150, "borderline"), (199, "borderline"), (200, "high"), (499, "high"), (500, "very_high")):
            self.assertEqual(pick(run(f"DLP : TG {v}"), "dlp.tg."), f"dlp.tg.{want}", v)

    def test_hdl_by_sex(self):
        self.assertEqual(pick(run("DLP : HDL 39", sex="M"), "dlp.hdl."), "dlp.hdl.low")
        self.assertEqual(pick(run("DLP : HDL 40", sex="M"), "dlp.hdl."), "dlp.hdl.ok")
        self.assertEqual(pick(run("DLP : HDL 49", sex="F"), "dlp.hdl."), "dlp.hdl.low")
        self.assertEqual(pick(run("DLP : HDL 50", sex="F"), "dlp.hdl."), "dlp.hdl.ok")

    def test_hdl_without_sex_uses_the_male_cut_and_tells_the_doctor(self):
        r = run("DLP : HDL 45", sex=None)
        self.assertEqual(pick(r, "dlp.hdl."), "dlp.hdl.ok"); self.assertIn("data.need_sex_hdl", notes(r))
        self.assertNotIn("data.need_sex_hdl", notes(run("DLP : HDL 45", sex="F")))

    def test_tc_bands(self):
        for v, want in ((199, "desirable"), (200, "borderline"), (239, "borderline"), (240, "high")):
            self.assertEqual(pick(run(f"DLP : TC {v}"), "dlp.tc."), f"dlp.tc.{want}", v)


class Anemia(unittest.TestCase):
    def band(self, hb, sex):
        return pick(run(f"CBC : Hb {hb}", sex=sex), "anemia.hb.")

    def test_men(self):
        for v, want in ((13, "normal"), (12.9, "mild"), (11, "mild"), (10.9, "moderate"), (8, "moderate"), (7.9, "severe")):
            self.assertEqual(self.band(v, "M"), f"anemia.hb.{want}", v)

    def test_women(self):
        for v, want in ((12, "normal"), (11.9, "mild"), (11, "mild"), (10.9, "moderate"), (8, "moderate"), (7.9, "severe")):
            self.assertEqual(self.band(v, "F"), f"anemia.hb.{want}", v)

    def test_same_value_different_verdict_by_sex(self):
        self.assertEqual(self.band(12.5, "M"), "anemia.hb.mild"); self.assertEqual(self.band(12.5, "F"), "anemia.hb.normal")

    def test_no_sex_no_interpretation(self):
        r = run("CBC : Hb 9", sex=None)
        self.assertFalse([k for k in keys(r) if k.startswith("anemia.hb")]); self.assertIn("data.need_sex_hb", notes(r))

    def test_hb_trend(self):
        self.assertIn("anemia.hb.trend.improving", keys(run("CBC : Hb 8->9")))            # exactly +1
        self.assertIn("anemia.hb.trend.worsening", keys(run("CBC : Hb 10->9")))
        self.assertFalse([k for k in keys(run("CBC : Hb 10->9.5")) if "trend" in k])

    def test_mcv_classes(self):
        for v, want in ((79.9, "micro"), (80, "normal"), (100, "normal"), (100.1, "macro")):
            self.assertEqual(pick(run(f"CBC : MCV {v}"), "anemia.mcv."), f"anemia.mcv.{want}", v)

    def test_mentzer_is_doctor_only_and_only_for_microcytosis(self):
        r = run("CBC : MCV 68 RBC 4.9")
        n = next(n for n in r["clinician_notes"] if n["key"] == "anemia.mentzer"); self.assertEqual(n["values"]["m"], "13.9"); self.assertIn("ขาดธาตุเหล็ก", n["values"]["interp"])
        self.assertIn("thalassemia", next(n for n in run("CBC : MCV 68 RBC 6")["clinician_notes"] if n["key"] == "anemia.mentzer")["values"]["interp"])
        self.assertNotIn("anemia.mentzer", notes(run("CBC : MCV 85 RBC 4.9")))
        self.assertNotIn("anemia.mentzer", keys(r))

    def test_rdw(self):
        self.assertNotIn("anemia.rdw_high", notes(run("CBC : RDW 14.5"))); self.assertIn("anemia.rdw_high", notes(run("CBC : RDW 14.6")))

    def test_crosschecks_catch_typos(self):
        self.assertNotIn("anemia.crosscheck.mcv", notes(run("CBC : Hct 28 RBC 4.9 MCV 57")))
        self.assertIn("anemia.crosscheck.mcv", notes(run("CBC : Hct 28 RBC 4.9 MCV 90")))
        self.assertIn("anemia.crosscheck.hcthb", notes(run("CBC : Hb 9 Hct 40")))
        self.assertNotIn("anemia.crosscheck.hcthb", notes(run("CBC : Hb 9.2 Hct 28")))


class Warfarin(unittest.TestCase):
    def band(self, note): return pick(run(note), "warfarin.inr.")

    def test_default_goal_2_to_3(self):
        for v, want in ((1.9, "below"), (2.0, "ok"), (3.0, "ok"), (3.1, "above"), (4.4, "above"), (4.5, "high"), (6, "high")):
            self.assertEqual(self.band(f"Warfarin : INR {v}"), f"warfarin.inr.{want}", v)

    def test_default_goal_is_disclosed_to_the_doctor(self):
        self.assertIn("warfarin.goal_default", notes(run("Warfarin : INR 2.5")))
        self.assertNotIn("warfarin.goal_default", notes(run("Warfarin : INR 2.5 goal 2-3")))

    def test_goal_from_the_note(self):
        self.assertEqual(self.band("Warfarin : INR 3.4 goal 2.5-3.5"), "warfarin.inr.ok")
        self.assertEqual(self.band("Warfarin : INR 3.4 goal 2-3"), "warfarin.inr.above")
        self.assertEqual(self.band("Warfarin : INR 4.6 goal 3-4"), "warfarin.inr.high")
        self.assertEqual(self.band("Warfarin : INR 4.6 goal 4-5"), "warfarin.inr.ok")      # in range of a high goal: not an alert
        self.assertEqual(self.band("Warfarin : INR 2.5 เป้า 2.5–3.5"), "warfarin.inr.ok")  # Thai keyword and en dash

    def test_invalid_goal_falls_back_to_default_and_is_reported(self):
        r = run("Warfarin : INR 3.4 goal 3-2")
        self.assertEqual(pick(r, "warfarin.inr."), "warfarin.inr.above"); self.assertIn("data.invalid", notes(r)); self.assertIn("warfarin.goal_default", notes(r))

    def test_system_never_gives_a_dose(self):
        for n in run("Warfarin : INR 1.2")["clinician_notes"] + run("Warfarin : INR 6.0")["clinician_notes"]:
            self.assertNotRegex(n["key"], r"dose|dosage")

    def test_bleeding_is_urgent_on_warfarin_and_hinted_to_the_doctor(self):
        r = run("Warfarin : INR 2.5\n22/10/69 : เลือดกำเดา ฟกช้ำ")
        f = next(f for f in r["findings"] if f["id"] == "life.bleeding")
        self.assertEqual(f["level"], "alert"); self.assertIn("เลือดกำเดา", f["values"]["list"]); self.assertIn("ฟกช้ำ", f["values"]["list"])
        self.assertIn("warfarin.bleeding", notes(r))

    def test_bleeding_without_warfarin_is_attention_and_has_no_warfarin_hint(self):
        r = run("DM : FBS 100\n22/10/69 : ถ่ายดำ")
        self.assertEqual(next(f for f in r["findings"] if f["id"] == "life.bleeding")["level"], "attention"); self.assertNotIn("warfarin.bleeding", notes(r))

    def test_negated_bleeding_gives_nothing(self):
        r = run("Warfarin : INR 2.5\n22/10/69 : ไม่มีเลือดออก")
        self.assertFalse([f for f in r["findings"] if f["id"] == "life.bleeding"]); self.assertNotIn("warfarin.bleeding", notes(r))

    def test_reduced_intake_hint_only_with_warfarin(self):
        self.assertIn("warfarin.intake", notes(run("Warfarin : INR 2.5\n22/10/69 : ฉันได้น้อย")))
        self.assertNotIn("warfarin.intake", notes(run("DM : FBS 100\n22/10/69 : ฉันได้น้อย")))


if __name__ == "__main__":
    unittest.main()
