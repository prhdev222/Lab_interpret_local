import datetime
import unittest

from engine.egfr import ckd_epi_2021
from engine.parse_note import parse_note
from engine.rules import evaluate

TODAY = datetime.date(2026, 10, 22)


def run(note, age=None, sex=None):
    return evaluate(parse_note(note, today=TODAY), {"age": age, "sex": sex})


def keys(r):
    return {f["key"] for f in r["findings"]}


def note_keys(r):
    return {f["key"] for f in r["clinician_notes"]}


class CkdEpi2021(unittest.TestCase):
    # Reference values computed by hand from the published equation (Inker et al., NEJM 2021):
    # eGFR = 142 x min(Scr/k,1)^a x max(Scr/k,1)^-1.200 x 0.9938^age x 1.012 [female]; k = 0.7 F / 0.9 M; a = -0.241 F / -0.302 M
    def test_reference_points(self):
        self.assertAlmostEqual(ckd_epi_2021(1.0, 40, "M"), 97.5, delta=1.0)
        self.assertAlmostEqual(ckd_epi_2021(1.0, 60, "F"), 64.5, delta=1.0)
        self.assertAlmostEqual(ckd_epi_2021(1.5, 70, "M"), 49.8, delta=1.0)
        self.assertAlmostEqual(ckd_epi_2021(1.5, 60, "M"), 53.0, delta=1.0)

    def test_monotonic(self):
        self.assertGreater(ckd_epi_2021(1.0, 50, "M"), ckd_epi_2021(1.5, 50, "M"))
        self.assertGreater(ckd_epi_2021(1.2, 40, "F"), ckd_epi_2021(1.2, 70, "F"))


class Dm(unittest.TestCase):
    def band(self, h):
        return next(k for k in keys(run(f"DM : HbA1c {h}")) if k.startswith("dm.hba1c.") and "trend" not in k)

    def test_hba1c_boundaries(self):
        for h, want in ((6.9, "ok"), (7.0, "ok"), (7.01, "mild_high"), (7.99, "mild_high"), (8.0, "high"), (9.99, "high"), (10.0, "very_high")):
            self.assertEqual(self.band(h), f"dm.hba1c.{want}", h)

    def test_fbs_boundaries(self):
        def b(v): return next(k for k in keys(run(f"DM : FBS {v}")))
        for v, want in ((69, "low"), (69.9, "low"), (70, "slightly_low"), (79.9, "slightly_low"), (80, "ok"), (130, "ok"), (130.1, "above"), (179, "above"), (180, "high")):
            self.assertEqual(b(v), f"dm.fbs.{want}", v)

    def test_trends(self):
        self.assertIn("dm.hba1c.trend.improving", keys(run("DM : HbA1c 9->7.4")))
        self.assertIn("dm.hba1c.trend.worsening", keys(run("DM : HbA1c 7->8")))
        self.assertIn("dm.hba1c.trend.stable", keys(run("DM : HbA1c 7.0->7.2")))
        self.assertNotIn("dm.hba1c.trend.stable", keys(run("DM : HbA1c 7.0")))        # a single value has no trend

    def test_rapid_drop_is_clinician_only(self):
        r = run("DM : HbA1c 12->10->6.5")
        self.assertIn("dm.hba1c.rapid_drop", note_keys(r))
        self.assertNotIn("dm.hba1c.rapid_drop", keys(r))
        self.assertNotIn("dm.hba1c.rapid_drop", note_keys(run("DM : HbA1c 9->7.5")))


class Ht(unittest.TestCase):
    def clinic(self, note):
        return next(k for k in keys(run(note)) if k.startswith("ht.clinic."))

    def test_general_target(self):
        self.assertEqual(self.clinic("HT : BP 139/89"), "ht.clinic.ok")
        self.assertEqual(self.clinic("HT : BP 140/80"), "ht.clinic.above")
        self.assertEqual(self.clinic("HT : BP 120/90"), "ht.clinic.above")

    def test_stricter_target_only_when_dm_or_ckd_is_listed(self):
        self.assertEqual(self.clinic("DM : FBS 100\nHT : BP 129/79"), "ht.clinic.ok")
        self.assertEqual(self.clinic("DM : FBS 100\nHT : BP 130/79"), "ht.clinic.above")
        self.assertEqual(self.clinic("CKD : eGFR 50\nHT : BP 125/80"), "ht.clinic.above")
        self.assertEqual(self.clinic("HT : BP 130/79"), "ht.clinic.ok")              # no DM/CKD listed -> general target

    def test_crisis_and_clinician_note(self):
        r = run("HT : BP 185/95")
        self.assertIn("ht.clinic.crisis", keys(r))
        self.assertIn("ht.clinic.crisis", note_keys(r))
        self.assertIn("ht.clinic.crisis", keys(run("HT : BP 150/120")))
        self.assertNotIn("ht.clinic.crisis", keys(run("HT : BP 179/119")))

    def test_discordance(self):
        self.assertIn("ht.discord.white_coat", keys(run("HT : BP 150/90 HMBP 120/80")))
        self.assertIn("ht.discord.masked", keys(run("HT : BP 125/75 HMBP 140/90")))
        self.assertFalse({"ht.discord.white_coat", "ht.discord.masked"} & keys(run("HT : BP 150/90 HMBP 145/92")))
        self.assertFalse({"ht.discord.white_coat", "ht.discord.masked"} & keys(run("HT : BP 120/70 HMBP 118/72")))
        self.assertFalse({"ht.discord.white_coat", "ht.discord.masked"} & keys(run("HT : BP 150/90")))   # needs both readings

    def test_home_bp_boundary(self):
        self.assertIn("ht.home.ok", keys(run("HT : HMBP 134/84")))
        self.assertIn("ht.home.above", keys(run("HT : HMBP 135/84")))


class Obesity(unittest.TestCase):
    def test_bmi_bands(self):
        def b(v): return next(k for k in keys(run(f"Obesity : BMI {v}")) if k.startswith("ob.bmi"))
        for v, want in ((18.4, "underweight"), (18.5, "normal"), (22.9, "normal"), (23, "overweight"), (24.9, "overweight"), (25, "obese1"), (29.9, "obese1"), (30, "obese2"), (31, "obese2")):
            self.assertEqual(b(v), f"ob.bmi.{want}", v)

    def test_weight_change(self):
        self.assertIn("ob.weight.loss", keys(run("Obesity : BW 100->95")))            # exactly 5%
        self.assertIn("ob.weight.stable", keys(run("Obesity : BW 100->95.1")))
        self.assertIn("ob.weight.gain", keys(run("Obesity : BW 100->106")))
        self.assertFalse([k for k in keys(run("Obesity : BW 100")) if k.startswith("ob.weight")])


class Ckd(unittest.TestCase):
    def stage(self, e):
        return next(k for k in keys(run(f"CKD : eGFR {e}")) if k.startswith("ckd.stage"))

    def test_stage_boundaries(self):
        for e, want in ((120, "g1"), (90, "g1"), (89.9, "g2"), (60, "g2"), (59.9, "g3a"), (45, "g3a"), (44.9, "g3b"), (30, "g3b"), (29.9, "g4"), (15, "g4"), (14.9, "g5")):
            self.assertEqual(self.stage(e), f"ckd.stage.{want}", e)

    def test_computed_egfr_is_labelled_and_needs_age_sex(self):
        r = run("CKD : Cr 1.5", 60, "M")
        f = next(f for f in r["findings"] if f["id"] == "ckd.egfr.stage")
        self.assertTrue(f["values"]["computed_note"])
        self.assertEqual(f["key"], "ckd.stage.g3a")
        self.assertEqual([f for f in run("CKD : Cr 1.5")["findings"] if f["id"] == "ckd.egfr.stage"], [])   # no age/sex -> no guess
        self.assertEqual([f for f in run("CKD : Cr 1.5", 60)["findings"] if f["id"] == "ckd.egfr.stage"], [])

    def test_reported_egfr_wins_over_computed(self):
        r = run("CKD : Cr 1.5 eGFR 95", 60, "M")
        self.assertEqual(next(f for f in r["findings"] if f["id"] == "ckd.egfr.stage")["key"], "ckd.stage.g1")

    def test_crosscheck(self):
        self.assertIn("ckd.crosscheck.mismatch", note_keys(run("CKD : Cr 1.5 eGFR 90", 60, "M")))
        self.assertIn("ckd.crosscheck.ok", note_keys(run("CKD : Cr 1.5 eGFR 54", 60, "M")))
        self.assertIn("data.need_age_sex", note_keys(run("CKD : Cr 1.5 eGFR 54")))

    def test_trend(self):
        self.assertIn("ckd.trend.worsening", keys(run("CKD : eGFR 70->55->48")))
        self.assertIn("ckd.trend.improving", keys(run("CKD : eGFR 40->52")))
        self.assertFalse([k for k in keys(run("CKD : eGFR 52->50")) if k.startswith("ckd.trend")])

    def test_albuminuria_hint(self):
        self.assertIn("ckd.albuminuria_missing", note_keys(run("CKD : eGFR 50")))
        self.assertNotIn("ckd.albuminuria_missing", note_keys(run("CKD : eGFR 50 UACR 30")))


class TodayLine(unittest.TestCase):
    def test_smoking(self):
        self.assertIn("life.smoking.current", keys(run("22/10/69 : ยังสูบบุหรี่อยู่")))
        self.assertIn("life.smoking.former", keys(run("22/10/69 : เลิกสูบบุหรี่แล้ว")))
        self.assertFalse([k for k in keys(run("22/10/69 : ไม่สูบบุหรี่")) if k.startswith("life.smoking")])

    def test_negated_symptom_gives_no_finding(self):
        self.assertFalse([k for k in keys(run("22/10/69 : ไม่มีเวียนศีรษะ")) if k.startswith("life.")])

    def test_latest_dated_line_wins(self):
        r = run("01/10/69 : ยังสูบบุหรี่อยู่\n22/10/69 : เลิกสูบบุหรี่แล้ว")
        self.assertIn("life.smoking.former", keys(r))
        self.assertNotIn("life.smoking.current", keys(r))

    def test_dm_hypoglycemia_hint_needs_all_conditions(self):
        base = "DM : HbA1c 6.5\n"
        self.assertIn("xr.dm_hypo", note_keys(run(base + "22/10/69 : เวียนศีรษะ ฉันได้น้อย")))
        self.assertNotIn("xr.dm_hypo", note_keys(run(base + "22/10/69 : เวียนศีรษะ")))
        self.assertNotIn("xr.dm_hypo", note_keys(run(base + "22/10/69 : ฉันได้น้อย")))
        self.assertNotIn("xr.dm_hypo", note_keys(run("HT : BP 130/80\n22/10/69 : เวียนศีรษะ ฉันได้น้อย")))
        self.assertIn("xr.dm_hypo", note_keys(run(base + "22/10/69 : ใจสั่น ฉันได้น้อย")))
        self.assertNotIn("xr.dm_hypo", keys(run(base + "22/10/69 : เวียนศีรษะ ฉันได้น้อย")))   # never shown to the patient


class DataQuality(unittest.TestCase):
    def test_invalid_value_is_never_interpreted(self):
        r = run("DM : HbA1c 65")
        self.assertFalse([k for k in keys(r) if k.startswith("dm.hba1c")])
        self.assertIn("data.invalid", note_keys(r))

    def test_values_without_rules_are_reported(self):
        self.assertIn("data.no_rules", note_keys(run("Obesity : Height 170")))     # Height is read but has no interpretation rule of its own
        self.assertNotIn("data.no_rules", note_keys(run("DLP : LDL 130")))        # LDL has one now

    def test_bad_age_sex_are_ignored_not_trusted(self):
        for age, sex in ((-5, "M"), (200, "F"), ("abc", "M"), (60, "X"), (None, None)):
            r = run("CKD : Cr 1.5", age, sex)
            self.assertEqual([f for f in r["findings"] if f["id"] == "ckd.egfr.stage"], [], (age, sex))

    def test_empty_note(self):
        r = run("")
        self.assertEqual((r["findings"], r["clinician_notes"]), ([], []))


if __name__ == "__main__":
    unittest.main()
