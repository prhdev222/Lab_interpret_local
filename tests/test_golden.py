import copy
import json
import os
import tempfile
import unittest

from engine import golden, targets_edit
from engine.rules import load_targets

SHIPPED = golden.load(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "golden_cases.json"))


class Seed(unittest.TestCase):
    def test_shipped_examples_are_synthetic_unconfirmed_and_alive(self):
        self.assertGreaterEqual(len(SHIPPED), 25)
        self.assertEqual(len({c["id"] for c in SHIPPED}), len(SHIPPED))
        for c in SHIPPED:
            self.assertFalse(c.get("confirmed"), "the developer must not pre-confirm clinical results")
            sn = golden.snapshot(c)
            self.assertTrue(sn["findings"] or sn["notes"], c["note"])

    def test_every_disease_group_has_an_example(self):
        text = "\n".join(c["note"] for c in SHIPPED)
        for word in ("DM", "HT", "Obesity", "CKD", "DN", "DR", "MAFLD", "CAD", "Stroke", "COPD", "Asthma", "CBC", "Warfarin", "DLP"):
            self.assertIn(word, text, word)

    def test_typical_ranges_table_matches_the_shipped_targets(self):
        t = json.load(open(targets_edit.PATH, encoding="utf-8"))
        ranges = json.load(open(targets_edit.RANGES_PATH, encoding="utf-8"))["ranges"]
        paths = {p for p, _, _ in targets_edit.leaves(t)} | {f"{p}[{i}]" for p, k, _ in targets_edit.leaves(t) if k == "pair" for i in (0, 1)}
        for p, (lo, hi) in ranges.items():
            self.assertIn(p, paths, p); self.assertLess(lo, hi, p)
            self.assertTrue(lo <= targets_edit._get(t, p) <= hi, f"shipped {p} is outside its own typical range")


class Diff(unittest.TestCase):
    def setUp(self):
        self.cases = [{"id": "g-1", "note": "DM : HbA1c 7.4", "age": 60, "sex": "M"}, {"id": "g-2", "note": "HT : BP 125/75", "age": 60, "sex": "M"}]

    def test_no_change_no_diff(self):
        self.assertEqual(golden.compare({}, {}, self.cases), [])

    def test_threshold_change_shows_exactly_what_moves(self):
        t = copy.deepcopy(load_targets()); t["dm"]["hba1c"]["target_max"] = 7.5
        d = golden.compare({}, {"targets": t}, self.cases)
        self.assertEqual([x["id"] for x in d], ["g-1"])                                    # the BP example is untouched
        self.assertIn("สูงกว่าเป้าหมายเล็กน้อย", d[0]["removed"][0]["text"]); self.assertIn("อยู่ในเป้าหมาย", d[0]["added"][0]["text"])

    def test_custom_rule_shows_up_as_added(self):
        rule = {"id": "t.r", "enabled": True, "problem": "HT", "level": "attention", "when": {"param": "BP", "field": "sys", "op": ">=", "value": 120},
                "patient": {"short": "ความดันบน {BP.sys} ค่อนข้างสูง", "long": "ความดันบน {BP.sys} ค่อนข้างสูง ควรปรึกษาแพทย์"}}
        d = golden.compare({}, {"custom_override": {"rules": [rule]}}, self.cases)
        self.assertEqual([x["id"] for x in d], ["g-2"]); self.assertTrue(d[0]["added"])

    def test_disabling_a_standard_rule_shows_what_disappears(self):
        d = golden.compare({}, {"custom_override": {"disable_builtin": ["ht.clinic.status"], "rules": []}}, self.cases)
        by = {x["id"]: x for x in d}
        self.assertTrue(by["g-2"]["removed"]); self.assertFalse(by["g-2"]["added"])
        self.assertFalse(by["g-1"]["removed"]); self.assertTrue(any("data.disabled_rules" in k for k in by["g-1"]["notes_added"]))   # every note is told a rule was switched off

    def test_confirmed_case_that_changes_is_reported(self):
        c = dict(self.cases[0], confirmed=True, approved=golden.snapshot(self.cases[0]))
        self.assertEqual(golden.approved_violations({}, [c]), [])
        t = copy.deepcopy(load_targets()); t["dm"]["hba1c"]["target_max"] = 7.5
        self.assertEqual(golden.approved_violations({"targets": t}, [c]), ["g-1"])
        self.assertEqual(golden.approved_violations({"targets": t}, [dict(self.cases[0])]), [])      # unconfirmed cases are not "violated"

    def test_a_setting_that_breaks_a_case_is_reported_not_raised(self):
        d = golden.compare({}, {"targets": {"dm": {}}}, self.cases[:1])
        self.assertTrue(d and d[0].get("error"))


class Storage(unittest.TestCase):
    def test_round_trip_and_ids(self):
        path = os.path.join(tempfile.mkdtemp(), "g.json")
        cases = [{"id": "g-3", "note": "DM : FBS 100"}]
        golden.save(cases, path)
        self.assertEqual(golden.load(path), cases); self.assertEqual(golden.next_id(cases), "g-4")
        self.assertEqual(golden.load(os.path.join(tempfile.mkdtemp(), "none.json")), [])

    def test_validation(self):
        self.assertEqual(golden.validate_new("DM : FBS 100", "60", "M")[0], {"note": "DM : FBS 100", "age": 60.0, "sex": "M"})
        for bad in (("", None, None), ("x" * 3000, None, None), ("a", "abc", None), ("a", 0, None), ("a", None, "Q")):
            self.assertIsNotNone(golden.validate_new(*bad)[1], bad)


if __name__ == "__main__":
    unittest.main()
