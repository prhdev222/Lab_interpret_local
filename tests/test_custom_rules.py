import json
import os
import tempfile
import unittest

from engine import custom_rules
from engine.parse_note import parse_note
from engine.render import render_clinician, render_patient
from engine.rules import RULES, evaluate

IDS = {r["id"] for r in RULES}
NOTE = "DM : HbA1c 9\nDLP : LDL 170"


def rule(**kw):
    base = {"id": "t.one", "problem": "Dyslipidemia", "level": "attention",
            "when": {"param": "LDL", "op": ">=", "value": 160},
            "patient": {"short": "LDL {LDL} สูงกว่าเกณฑ์ที่แพทย์ตั้งไว้", "long": "ค่า LDL ของ{ท่าน}คือ {LDL} mg/dL สูงกว่าเกณฑ์ที่แพทย์ตั้งไว้"},
            "clinician": "LDL {LDL} (กฎเพิ่มเอง)"}
    base.update(kw)
    return base


class WithFile(unittest.TestCase):
    def use(self, data):
        d = tempfile.mkdtemp(); path = os.path.join(d, "c.json")
        open(path, "w", encoding="utf-8").write(data if isinstance(data, str) else json.dumps(data))
        self._old = custom_rules.PATH; custom_rules.PATH = path
        self.addCleanup(lambda: setattr(custom_rules, "PATH", self._old))

    def run_note(self, note=NOTE):
        return evaluate(parse_note(note), {"age": 60, "sex": "M"})


class Validation(unittest.TestCase):
    def check(self, r, data=None):
        return custom_rules.validate(data or {"rules": [r]}, IDS)

    def test_valid_rule_accepted(self):
        good, errors, _ = self.check(rule()); self.assertEqual((len(good), errors), (1, []))

    def test_digits_in_patient_text_rejected(self):
        good, errors, _ = self.check(rule(patient={"short": "LDL สูงเกิน 160", "long": "สูงเกิน 160"}))
        self.assertEqual(good, []); self.assertTrue(errors)

    def test_lay_word_without_glossary_token_rejected(self):
        good, errors, _ = self.check(rule(patient={"short": "ควรลดอาหารมัน", "long": "ควรลดอาหารมัน"}))
        self.assertEqual(good, []); self.assertTrue(errors)

    def test_unknown_disable_id_reported(self):
        _, errors, _ = custom_rules.validate({"disable_builtin": ["nope.rule"], "rules": []}, IDS)
        self.assertTrue(errors)

    def test_too_deep_or_too_many_rules_rejected(self):
        cond = {"param": "LDL", "op": ">", "value": 1}
        for _ in range(8):
            cond = {"not": cond}
        self.assertEqual(self.check(rule(when=cond))[0], [])
        many = {"rules": [rule(id=f"t.r{i}") for i in range(201)]}
        good, errors, _ = custom_rules.validate(many, IDS)
        self.assertTrue(errors); self.assertLessEqual(len(good), 200)

    def test_disabled_rule_not_used(self):
        self.assertEqual(self.check(rule(enabled=False))[0], [])


class Behaviour(WithFile):
    def test_fires_and_renders_in_both_registers(self):
        self.use({"rules": [rule()]}); r = self.run_note()
        self.assertTrue(any(f.get("custom") for f in r["findings"]))
        for monk in (False, True):
            text = render_patient(r, "detailed", monk)
            self.assertIn("170", text); self.assertNotRegex(text, r"[{}]")
        self.assertIn("กฎเพิ่มเอง", " ".join(x["text"] for x in render_clinician(r)))

    def test_missing_value_never_fires(self):
        self.use({"rules": [rule()]})
        self.assertFalse(any(f.get("custom") for f in self.run_note("DM : HbA1c 9")["findings"]))

    def test_not_of_unknown_is_still_unknown(self):
        self.use({"rules": [rule(when={"not": {"param": "LDL", "op": "<", "value": 160}})]})
        self.assertFalse(any(f.get("custom") for f in self.run_note("DM : HbA1c 9")["findings"]))

    def test_unknown_group_name_still_rendered(self):
        self.use({"rules": [rule(problem="MyGroup")]})
        self.assertIn("LDL 170", render_patient(self.run_note(), "standard", False))

    def test_disable_builtin_removes_rule_and_tells_doctor(self):
        before = self.run_note()
        victim = next(f["id"] for f in before["findings"] if f["problem"] == "DM")
        self.use({"disable_builtin": [victim], "rules": []}); after = self.run_note()
        self.assertNotIn(victim, [f["id"] for f in after["findings"]])
        self.assertIn(victim, " ".join(x["text"] for x in render_clinician(after)))

    def test_broken_file_fails_safe(self):
        self.use("{ not json")
        r = self.run_note()
        self.assertTrue(r["findings"])                                            # built-in rules still work
        self.assertIn("data.custom_error", [n["key"] for n in r["clinician_notes"]])
        render_clinician(r)

    def test_one_bad_rule_does_not_stop_the_others(self):
        self.use({"rules": [rule(id="t.bad", patient={"short": "สูง 160", "long": "สูง 160"}), rule(id="t.good")]})
        r = self.run_note()
        ids = [f["id"] for f in r["findings"]]
        self.assertIn("custom.t.good", ids); self.assertNotIn("custom.t.bad", ids)
        self.assertIn("data.custom_error", [n["key"] for n in r["clinician_notes"]])

    def test_shipped_starter_file_is_valid_and_inactive(self):
        d = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "custom_rules.json"), encoding="utf-8"))
        good, errors, disabled = custom_rules.validate(d, IDS)
        self.assertEqual((good, errors, disabled), ([], [], []))
        self.assertTrue(all(x["enabled"] is False for x in d["rules"]))


if __name__ == "__main__":
    unittest.main()
