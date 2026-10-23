import json
import os
import shutil
import tempfile
import unittest

import engine.rules as rules_module
from engine import custom_rules, golden, signoff, targets_edit
from engine.parse_note import parse_note
from engine.rules import evaluate

REAL = os.path.dirname(targets_edit.PATH)


class Env(unittest.TestCase):
    """A private copy of data/ so signing never touches the real files."""
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for n in os.listdir(REAL):
            if n.endswith(".json"):
                shutil.copy(os.path.join(REAL, n), self.dir)
        self.saved = (signoff.DATA_DIR, signoff.PATH, targets_edit.PATH, golden.PATH, custom_rules.PATH, rules_module.DATA_DIR)
        signoff.DATA_DIR, signoff.PATH, rules_module.DATA_DIR = self.dir, os.path.join(self.dir, "signoff.json"), self.dir      # the engine must read the same private copy
        targets_edit.PATH, golden.PATH, custom_rules.PATH = (os.path.join(self.dir, "targets.json"), os.path.join(self.dir, "golden_cases.json"), os.path.join(self.dir, "custom_rules.json"))
        self.addCleanup(lambda: (setattr(signoff, "DATA_DIR", self.saved[0]), setattr(signoff, "PATH", self.saved[1]), setattr(targets_edit, "PATH", self.saved[2]),
                                 setattr(golden, "PATH", self.saved[3]), setattr(custom_rules, "PATH", self.saved[4]), setattr(rules_module, "DATA_DIR", self.saved[5])))

    def make_ready(self):
        t = json.load(open(targets_edit.PATH, encoding="utf-8"))
        def fix(o):
            for k, v in o.items():
                if isinstance(v, dict):
                    if "needs_citation" in v:
                        v["needs_citation"] = False
                        if "source" in v: v["source"] = "แนวทางสมมติสำหรับการทดสอบ ฉบับ 2569"
                    fix(v)
        fix({k: v for k, v in t.items() if k != "_meta"})
        json.dump(t, open(targets_edit.PATH, "w", encoding="utf-8"), ensure_ascii=False)
        cases = golden.load()
        for c in cases:
            c["confirmed"], c["approved"] = True, golden.snapshot(c)
        golden.save(cases)


class Signing(Env):
    def test_unsigned_by_default_and_says_draft(self):
        self.assertFalse(signoff.state()["signed"]); self.assertIn("DRAFT", signoff.effective_status())

    def test_blockers_are_reported_and_signing_is_refused(self):
        c = signoff.checklist()
        self.assertTrue(c["needs_citation"]); self.assertTrue(c["unconfirmed_examples"])
        ok, errors = signoff.sign("นพ.ทดสอบ", signoff.PHRASE)
        self.assertFalse(ok); self.assertTrue(any("อ้างอิง" in e for e in errors)); self.assertTrue(any("ยังไม่ยืนยันผล" in e for e in errors))
        self.assertIn("DRAFT", signoff.effective_status()); self.assertFalse(os.path.exists(signoff.PATH))

    def test_name_and_phrase_are_required(self):
        self.make_ready()
        for name, phrase in (("", signoff.PHRASE), ("x", signoff.PHRASE), ("นพ.ทดสอบ", "ok"), ("นพ.ทดสอบ", None)):
            self.assertFalse(signoff.sign(name, phrase)[0], (name, phrase))

    def test_ready_and_signed(self):
        self.make_ready()
        self.assertEqual(signoff.blockers(signoff.checklist()), [])
        ok, errors = signoff.sign("นพ.ทดสอบ", signoff.PHRASE)
        self.assertTrue(ok, errors)
        st = signoff.state(); self.assertTrue(st["signed"]); self.assertEqual(st["by"], "นพ.ทดสอบ")
        self.assertNotIn("DRAFT", signoff.effective_status()); self.assertIn("นพ.ทดสอบ", signoff.effective_status())
        res = evaluate(parse_note("DM : HbA1c 7.4"), {"age": 60, "sex": "M"})
        self.assertNotIn("DRAFT", res["targets_status"])

    def test_any_later_edit_falls_back_to_draft(self):
        for edit in ("targets", "templates", "glossary", "lexicon", "custom"):
            self.setUp()
            self.make_ready(); self.assertTrue(signoff.sign("นพ.ทดสอบ", signoff.PHRASE)[0])
            if edit == "targets":
                d = json.load(open(targets_edit.PATH, encoding="utf-8")); d["dm"]["hba1c"]["target_max"] = 7.5; json.dump(d, open(targets_edit.PATH, "w", encoding="utf-8"), ensure_ascii=False)
            elif edit == "custom":
                json.dump({"disable_builtin": ["dm.fbs.status"], "rules": []}, open(custom_rules.PATH, "w", encoding="utf-8"))
            else:
                p = os.path.join(self.dir, f"{edit}.json"); d = json.load(open(p, encoding="utf-8"))
                (d["normal"].update({"ท่าน": "คุณ"}) if edit == "glossary" else d["concepts"]["dizziness"]["phrases"].append("เวียนมาก") if edit == "lexicon"
                 else d["findings"]["dm.fbs.ok"].update({"short": "แก้แล้ว"}))
                json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
            st = signoff.state()
            self.assertFalse(st["signed"], edit); self.assertTrue(st["edited_after"], edit); self.assertIn("DRAFT", signoff.effective_status()); self.assertIn("แก้ไขหลังลงนาม", signoff.effective_status())

    def test_status_and_notes_do_not_count_as_reviewed_content(self):
        self.make_ready(); self.assertTrue(signoff.sign("นพ.ทดสอบ", signoff.PHRASE)[0])
        d = json.load(open(targets_edit.PATH, encoding="utf-8")); d["_meta"]["note"] = "แก้โน้ต"; json.dump(d, open(targets_edit.PATH, "w", encoding="utf-8"), ensure_ascii=False)
        self.assertTrue(signoff.state()["signed"])

    def test_editing_a_confirmed_example_blocks_signing_until_reconfirmed(self):
        self.make_ready()
        t = json.load(open(targets_edit.PATH, encoding="utf-8")); t["dm"]["hba1c"]["target_max"] = 7.5; json.dump(t, open(targets_edit.PATH, "w", encoding="utf-8"), ensure_ascii=False)
        ok, errors = signoff.sign("นพ.ทดสอบ", signoff.PHRASE)
        self.assertFalse(ok); self.assertTrue(any("ผลเปลี่ยนจากที่เคยยืนยัน" in e for e in errors))

    def test_revoke_and_history(self):
        self.make_ready(); signoff.sign("นพ.ทดสอบ", signoff.PHRASE); signoff.revoke("admin")
        self.assertFalse(signoff.state()["signed"]); self.assertEqual([h["action"] for h in signoff.history()], ["sign", "revoke"])

    def test_corrupt_signoff_file_means_draft(self):
        open(signoff.PATH, "w").write("{ nope"); self.assertFalse(signoff.state()["signed"]); self.assertIn("DRAFT", signoff.effective_status())


if __name__ == "__main__":
    unittest.main()
