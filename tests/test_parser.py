import datetime
import random
import unittest

from engine.lexicon import load_lexicon
from engine.parse_note import collect_params, parse_note

TODAY = datetime.date(2026, 10, 22)
SAMPLE = """DM : FBS 120->130->110 HbA1C 12->10->6.5%
HT : BP 150/90mmHg HMBP 120/80mmHg
Obesity : BW 110-->100Kg BMI 31
CKD : Cr 1.5 GFR 54
22/10/69 : มีเวียนศีรษะ ฉันได้น้อย ยังสูบบุหรี่อยู่"""


def vals(parsed):
    return {v["param"]: v for p in parsed["problems"] for v in p["values"]}


class UserSample(unittest.TestCase):
    def setUp(self):
        self.p = parse_note(SAMPLE, today=TODAY)

    def test_every_value_read(self):
        v = vals(self.p)
        self.assertEqual(v["FBS"]["series"], [120, 130, 110])
        self.assertEqual(v["HbA1c"]["series"], [12, 10, 6.5])
        self.assertEqual(v["BP"]["series"], [[150, 90]])
        self.assertEqual(v["HomeBP"]["latest"], [120, 80])
        self.assertEqual(v["BW"]["series"], [110, 100])
        self.assertEqual(v["BMI"]["latest"], 31)
        self.assertEqual(v["Creatinine"]["latest"], 1.5)
        self.assertEqual(v["eGFR"]["latest"], 54)
        self.assertFalse(any(x["invalid"] for x in v.values()))

    def test_rightmost_is_latest(self):
        c = collect_params(self.p)
        self.assertEqual(c["HbA1c"]["latest"], 6.5)
        self.assertEqual(c["HbA1c"]["first"], 12)

    def test_nothing_left_over(self):
        self.assertEqual(self.p["unparsed_lines"], [])
        self.assertTrue(all(pr["unparsed"] == "" for pr in self.p["problems"]))
        self.assertEqual(self.p["warnings"], [])

    def test_dated_line(self):
        v = self.p["visits"][0]
        self.assertEqual(v["date"], "2026-10-22")
        self.assertEqual(v["date_be"], "22/10/2569")
        got = {c["id"]: c["value"] for c in v["concepts"]}
        self.assertEqual(got, {"dizziness": "present", "reduced_intake": "present", "smoking": "current"})
        self.assertEqual(v["leftover"], [])


class Variants(unittest.TestCase):
    def test_arrow_styles_and_case(self):
        for arrow in ("->", "-->", "--->", "=>", "→", "⇒", " -> ", "  -->  "):
            p = parse_note(f"dm : fbs 120{arrow}130{arrow}110", today=TODAY)
            self.assertEqual(vals(p)["FBS"]["series"], [120, 130, 110], arrow)

    def test_thai_digits_and_fullwidth_colon(self):
        p = parse_note("DM ： HbA1c ๑๒->๑๐->๖.๕%", today=TODAY)
        self.assertEqual(vals(p)["HbA1c"]["series"], [12, 10, 6.5])

    def test_aliases(self):
        p = parse_note("T2DM: A1c 8.1 fpg 150\nHTN : bp 130/80\nObese: wt 90>x", today=TODAY)
        self.assertEqual(vals(p)["HbA1c"]["latest"], 8.1)
        self.assertEqual(vals(p)["FBS"]["latest"], 150)
        self.assertEqual(vals(p)["BP"]["latest"], [130, 80])

    def test_unit_conversion_is_flagged_not_silent(self):
        p = parse_note("DM : FBS 6.1mmol/L HbA1c 48 mmol/mol\nCKD : Cr 132 umol/L", today=TODAY)
        v = vals(p)
        self.assertAlmostEqual(v["FBS"]["latest"], 109.9, delta=0.2)
        self.assertAlmostEqual(v["HbA1c"]["latest"], 6.5, delta=0.05)
        self.assertAlmostEqual(v["Creatinine"]["latest"], 1.49, delta=0.02)
        self.assertTrue(all(v[k]["converted"] and any("แปลงหน่วย" in f for f in v[k]["flags"]) for k in ("FBS", "HbA1c", "Creatinine")))

    def test_param_not_confused_with_longer_word(self):
        p = parse_note("DM : CRP 12 Cr 1.0", today=TODAY)
        v = vals(p)
        self.assertEqual(list(v), ["Creatinine"])                 # 'CRP 12' must not be read as Cr
        self.assertIn("CRP", p["problems"][0]["unparsed"])

    def test_unknown_things_are_kept_not_dropped_or_guessed(self):
        p = parse_note("Gout : uric 9.2\nAnemia Hb 9.2\nnonsense line", today=TODAY)
        self.assertEqual(p["problems"], [])
        texts = [u["text"] for u in p["unparsed_lines"]]
        self.assertEqual(texts, ["Gout : uric 9.2", "Anemia Hb 9.2", "nonsense line"])      # every line is preserved verbatim

    def test_unknown_problem_name_with_known_value(self):
        p = parse_note("Gout : Cr 1.2", today=TODAY)
        self.assertEqual((p["problems"][0]["name"], p["problems"][0]["known"]), ("Gout", False))
        self.assertEqual(vals(p)["Creatinine"]["latest"], 1.2)


class BadInputIsCaught(unittest.TestCase):
    def test_implausible_numbers_are_invalid(self):
        v = vals(parse_note("DM : HbA1c 65 FBS 1200\nHT : BP 90/150 BP 150", today=TODAY))
        self.assertTrue(v["HbA1c"]["invalid"] and v["FBS"]["invalid"] and v["BP"]["invalid"])

    def test_dates(self):
        lex = load_lexicon()
        for text, warn in (("31/2/69 : เวียนศีรษะ", "เป็นไปไม่ได้"), ("22/10/79 : เวียนศีรษะ", "อนาคต"), ("1/1/2500 : เวียนศีรษะ", "เก่ามาก")):
            v = parse_note(text, lex, TODAY)["visits"][0]
            self.assertIn(warn, v["date_warning"], text)

    def test_four_digit_be_and_ce_years(self):
        a = parse_note("15/1/2569 : ใจสั่น", today=TODAY)["visits"][0]["date"]
        b = parse_note("15/1/2026 : ใจสั่น", today=TODAY)["visits"][0]["date"]
        self.assertEqual((a, b), ("2026-01-15", "2026-01-15"))

    def test_series_with_mixed_units_is_invalid(self):
        v = vals(parse_note("OB : BW 110kg->100lb", today=TODAY))
        self.assertTrue(v == {} or v["BW"]["invalid"] or "lb" in parse_note("OB : BW 110kg->100lb", today=TODAY)["problems"][0]["unparsed"])


class Symptoms(unittest.TestCase):
    def concepts(self, text):
        v = parse_note(f"22/10/69 : {text}", today=TODAY)["visits"][0]
        return {c["id"]: c["value"] for c in v["concepts"]}, v["leftover"]

    def test_negation(self):
        c, _ = self.concepts("ไม่มีเวียนศีรษะ ฉันได้ดี เลิกสูบบุหรี่แล้ว")
        self.assertEqual(c, {"dizziness": "absent", "normal_intake": "present", "smoking": "former"})

    def test_smoking_states(self):
        self.assertEqual(self.concepts("ไม่สูบบุหรี่")[0]["smoking"], "not_smoking")
        self.assertEqual(self.concepts("ไม่เคยสูบ")[0]["smoking"], "never")
        self.assertEqual(self.concepts("สูบบุหรี่")[0]["smoking"], "current")
        self.assertEqual(self.concepts("ยังสูบอยู่")[0]["smoking"], "current")

    def test_unknown_clause_goes_to_leftover(self):
        c, left = self.concepts("นอนไม่หลับ ใจสั่น")
        self.assertEqual(left, ["นอนไม่หลับ"])
        self.assertEqual(c, {"palpitations": "present"})


class NewSyntax(unittest.TestCase):
    def test_new_parameters(self):
        v = vals(parse_note("CBC : Hb 9.2 MCV 68 RBC 4.9 RDW 17 Hct 28\nDLP : LDL 160 HDL 35 TG 310 TC 245", today=TODAY))
        self.assertEqual({k: x["latest"] for k, x in v.items()}, {"Hb": 9.2, "MCV": 68, "RBC": 4.9, "RDW": 17, "Hct": 28, "LDL": 160, "HDL": 35, "TG": 310, "TC": 245})

    def test_goal_range_in_every_spelling(self):
        for text, want in (("goal 2-3", [2, 3]), ("goal 2.5-3.5", [2.5, 3.5]), ("goal 2–3", [2, 3]), ("goal 2 to 3", [2, 3]), ("เป้า 2.5–3.5", [2.5, 3.5]), ("GOAL:2-3", [2, 3])):
            v = vals(parse_note(f"Warfarin : INR 2.5 {text}", today=TODAY))
            self.assertEqual(v["INRgoal"]["latest"], want, text); self.assertEqual(v["INRgoal"]["kind"], "range")
            self.assertEqual(v["INR"]["series"], [2.5], text)

    def test_goal_range_errors_are_invalid_not_guessed(self):
        for text in ("goal 3-2", "goal 2-2", "goal 0.1-9"):
            self.assertTrue(vals(parse_note(f"Warfarin : INR 2.5 {text}", today=TODAY))["INRgoal"]["invalid"], text)

    def test_inr_series_with_goal(self):
        v = vals(parse_note("Warfarin : INR 1.8->2.4->2.9 goal 2-3", today=TODAY))
        self.assertEqual(v["INR"]["series"], [1.8, 2.4, 2.9])

    def test_repeated_bleeding_words_become_one_concept(self):
        c = parse_note("22/10/69 : เลือดกำเดา ฟกช้ำ", today=TODAY)["visits"][0]["concepts"]
        self.assertEqual(len(c), 1); self.assertEqual(c[0]["id"], "bleeding"); self.assertEqual(c[0]["source"], "เลือดกำเดา、ฟกช้ำ")


class Robustness(unittest.TestCase):
    def test_garbage_never_crashes(self):
        rnd = random.Random(7)
        alphabet = list("DMHT: ->=→,.0123456789/%abcfbsHbA1cBPเวียนศีรษะฉันได้น้อย\n\t()ๆ๐๑") + ["mmHg", "kg", "->", "-->", "FBS", "BP", "22/10/69"]
        for _ in range(3000):
            s = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 120)))
            p = parse_note(s, today=TODAY)
            self.assertIn("problems", p)

    def test_pathological_inputs_are_fast(self):
        import time
        nasty = ["DM : " + "FBS " + "1" * 5000, "DM : " + "->" * 3000, "DM : FBS " + "1->" * 1000 + "1", "x" * 30000, ("DM : BP " + "1/" * 500 + "\n") * 300,
                 "DM :" + " " * 5000 + "FBS 1"]
        t = time.time()
        for s in nasty:
            parse_note(s, today=TODAY)
        self.assertLess(time.time() - t, 2.0)

    def test_non_string_and_empty(self):
        self.assertTrue(parse_note(None)["warnings"])      # type: ignore[arg-type]
        self.assertEqual(parse_note("")["problems"], [])


if __name__ == "__main__":
    unittest.main()
