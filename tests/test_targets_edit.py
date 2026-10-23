import copy
import json
import os
import tempfile
import unittest

from engine import targets_edit as te
from engine.parse_note import parse_note
from engine.rules import evaluate, load_targets

T = json.load(open(te.PATH, encoding="utf-8"))


class Core(unittest.TestCase):
    def test_shipped_file_satisfies_its_own_checks(self):
        self.assertEqual(te.check(T), [])

    def test_every_numeric_threshold_is_editable_and_labelled(self):
        paths = {p for p, k, _ in te.leaves(T)}
        self.assertIn("dm.hba1c.target_max", paths); self.assertIn("ckd.egfr_stage.g2_from", paths); self.assertIn("ht.clinic.target_comorbid", paths)
        for p, k, _ in te.leaves(T):
            key = p.rsplit(".", 1)[-1]
            self.assertIn(key, te.KEYS, f"no Thai label for {p}")
            self.assertTrue(any(p.startswith(g + ".") or p.rsplit(".", 1)[0] == g for g in te.GROUPS), f"no group label for {p}")

    def test_structure_and_name_lists_cannot_be_changed(self):
        for path in ("_meta.status", "thai_cv.required", "thai_cv.one_of", "nope.x", "dm"):
            new, errors = te.apply_changes(T, {path: 5}); self.assertIsNone(new); self.assertTrue(errors, path)

    def test_wrong_types_and_non_finite_numbers_refused(self):
        for bad in ("7", None, float("nan"), float("inf"), True, [1, 2]):
            self.assertIsNone(te.apply_changes(T, {"dm.hba1c.target_max": bad})[0], repr(bad))
        self.assertIsNone(te.apply_changes(T, {"dm.fbs.target": [80]})[0])
        self.assertIsNone(te.apply_changes(T, {"dm.fbs.target": ["a", 130]})[0])

    def test_ladders_are_enforced(self):
        for path, value in (("ckd.egfr_stage.g2_from", 95), ("obesity.bmi_asian.normal_below", 26), ("dlp.tg.high_from", 100), ("mafld.lsm.high_from", 5),
                            ("thai_cv.categories.high_from", 5), ("spo2.alert_below", 99), ("dm.hba1c.mild_high_below", 6), ("ht.clinic.target_comorbid", [150, 80]),
                            ("ht.clinic.target_general", [90, 140]), ("warfarin.alert_above", 2.5)):
            new, errors = te.apply_changes(T, {path: value}); self.assertIsNone(new, path); self.assertTrue(errors, path)

    def test_a_consistent_multi_change_is_accepted(self):
        new, errors = te.apply_changes(T, {"dm.hba1c.target_max": 7.5, "dm.hba1c.mild_high_below": 8.5, "dm.hba1c.high_below": 10.5})
        self.assertEqual(errors, []); self.assertEqual(new["dm.hba1c.target_max".split(".")[0]]["hba1c"]["target_max"], 7.5)

    def test_range_limits(self):
        self.assertIsNone(te.apply_changes(T, {"dm.fbs.stable_pct": 150})[0])
        self.assertIsNone(te.apply_changes(T, {"dm.fbs.low_below": -5})[0])
        self.assertIsNone(te.apply_changes(T, {"lifestyle.quitline": "16ab"})[0])
        self.assertIsNone(te.apply_changes(T, {"dm.hba1c.source": "x" * 500})[0])


class Saving(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp(); self.path = os.path.join(d, "t.json")
        json.dump(T, open(self.path, "w", encoding="utf-8"), ensure_ascii=False)

    def test_save_writes_backup_and_records_date_only(self):
        ok, errors, changed = te.save({"dm.hba1c.target_max": 7.5, "dm.hba1c.source": "ADA 2026"}, self.path)
        self.assertTrue(ok, errors); self.assertEqual(sorted(changed), ["dm.hba1c.source", "dm.hba1c.target_max"])
        new = json.load(open(self.path, encoding="utf-8"))
        self.assertEqual(new["dm"]["hba1c"]["target_max"], 7.5); self.assertIn("last_web_edit", new["_meta"])
        self.assertEqual(json.load(open(self.path + ".bak", encoding="utf-8"))["dm"]["hba1c"]["target_max"], 7.0)

    def test_failed_save_leaves_the_file_untouched(self):
        before = open(self.path, "rb").read()
        ok, errors, _ = te.save({"ckd.egfr_stage.g2_from": 95}, self.path)
        self.assertFalse(ok); self.assertTrue(errors); self.assertEqual(open(self.path, "rb").read(), before)
        self.assertFalse(os.path.exists(self.path + ".bak"))

    def test_no_change_is_not_a_save(self):
        self.assertFalse(te.save({"dm.hba1c.target_max": 7.0}, self.path)[0])


class Effect(unittest.TestCase):
    def test_changed_threshold_changes_the_interpretation(self):
        t = copy.deepcopy(load_targets())
        note = parse_note("DM : HbA1c 7.4")
        base = [f["key"] for f in evaluate(note, {}, t)["findings"]]
        t["dm"]["hba1c"]["target_max"] = 7.5
        changed = [f["key"] for f in evaluate(parse_note("DM : HbA1c 7.4"), {}, t)["findings"]]
        self.assertIn("dm.hba1c.mild_high", base); self.assertIn("dm.hba1c.ok", changed)


if __name__ == "__main__":
    unittest.main()


class RuleToNumbers(unittest.TestCase):
    """The "แก้เกณฑ์" button on each standard rule must lead to every number the rule really uses."""
    def test_reported_groups_cover_what_every_rule_actually_reads(self):
        from engine.rules import RULES, Ctx, _clean_patient
        from tests.test_render import battery
        t = load_targets()
        reported = {r["id"]: set(te.groups_read_by(r["describe"], t, r["id"])) for r in RULES}
        missing = {}
        for note in battery():
            parsed = parse_note(note)
            for patient in ({"age": 60, "sex": "M", "tcvr": 15}, {"age": 30, "sex": "F"}):
                for r in RULES:
                    seen = set()
                    try:
                        r["fn"](Ctx(parse_note(note), _clean_patient(patient), te._Rec(t, [], seen)))
                    except Exception:
                        continue
                    used = {p.rsplit(".", 1)[0] for p in seen if "." in p}
                    gap = used - reported[r["id"]]
                    if gap:
                        missing.setdefault(r["id"], set()).update(gap)
        self.assertEqual(missing, {}, "add these to te.EXTRA_GROUPS")

    def test_every_reported_group_exists_and_is_editable(self):
        from engine.rules import RULES
        t = load_targets()
        editable = {p.rsplit(".", 1)[0] for p, _, _ in te.leaves(json.load(open(te.PATH, encoding="utf-8")))}
        for r in RULES:
            for g in te.groups_read_by(r["describe"], t, r["id"]):
                self.assertTrue(any(e == g or e.startswith(g + ".") for e in editable), f"{r['id']} -> {g}")
