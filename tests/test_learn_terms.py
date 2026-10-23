import copy
import json
import os
import random
import re
import unittest

from engine.lexicon import Lexicon, load_lexicon
from tools import apply_terms, learn_terms, synth_notes

RAW = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "lexicon.json"), encoding="utf-8"))


def corpus(n=400, seed=7, other_share=0.4):
    """Synthetic notes: most written in the usual style, `other_share` by a second 'doctor' who abbreviates differently."""
    rnd, out = random.Random(seed), []
    for _ in range(n):
        t = synth_notes.make(rnd)["note"]
        if rnd.random() < other_share:
            t = re.sub(r"\b(FBS|fbs|fpg)\b", "BS", t); t = re.sub(r"\bCr\b", "Crea", t); t = re.sub(r"\b(BW|wt)\b", "Wgt", t)
            t = re.sub(r"(HbA1C|HbA1c|hba1c)", "HbA", t); t = t.replace("เวียนศีรษะ", "เวียนศรีษะ")
        out.append(t)
    return out


TEXTS = corpus()
SUG = learn_terms.learn(TEXTS, 5)
BY = {s["term"]: s for s in SUG}


class Learning(unittest.TestCase):
    def test_finds_the_right_meaning_for_each_new_abbreviation(self):
        for term, target in (("bs", "FBS"), ("crea", "Creatinine"), ("wgt", "BW"), ("hba", "HbA1c"), ("เวียนศรีษะ", "dizziness")):
            self.assertEqual(BY[term]["target"], target, term)

    def test_confident_suggestions_are_never_wrong(self):
        for s in SUG:
            if s.get("confidence") == "high":
                self.assertIn((s["term"], s["target"]), {("bs", "FBS"), ("crea", "Creatinine"), ("hba", "HbA1c"), ("wgt", "BW")}, s)

    def test_every_suggestion_starts_unapproved_with_evidence(self):
        self.assertTrue(SUG)
        for s in SUG:
            self.assertIs(s["approve"], False); self.assertTrue(s["evidence"]); self.assertGreaterEqual(s["notes"], 5)

    def test_rare_words_never_appear(self):
        rare = TEXTS + ["DM : ZQX 150 FBS 100\n22/10/69 : สมชายนามสมมติ ปวดมาก"]
        terms = {s["term"] for s in learn_terms.learn(rare, 5)}
        self.assertNotIn("zqx", terms); self.assertFalse([t for t in terms if "สมชาย" in t])

    def test_no_note_text_in_the_output(self):
        blob = json.dumps(SUG, ensure_ascii=False)
        for line in TEXTS[:20]:
            self.assertNotIn(line, blob)
        self.assertNotRegex(blob, r"\d{1,2}/\d{1,2}/\d{2,4}")                           # no dates

    def test_an_unknown_name_whose_values_fit_nothing_is_not_even_kept(self):
        rnd = random.Random(1)
        text = f"DM : FBS {rnd.randint(80, 200)} Zork {rnd.randint(20000, 30000)}"           # 20000+ fits no known parameter: dropped by the privacy filter
        self.assertEqual([r for r in learn_terms.extract_rows(text) if r["k"] == "unk"], [])
        self.assertNotIn("zork", {x["term"] for x in learn_terms.learn([text] * 10, 5)})

    def test_unknown_problem_name_is_matched_by_what_is_written_in_it(self):
        rnd = random.Random(2)
        texts = [f"DM : FBS {rnd.randint(80, 200)} HbA1c {round(rnd.uniform(6, 11), 1)}" for _ in range(10)]
        texts += [f"Diab : FBS {rnd.randint(80, 200)} HbA1c {round(rnd.uniform(6, 11), 1)}" for _ in range(8)]
        s = next(x for x in learn_terms.learn(texts, 5) if x["kind"] == "problem_alias")
        self.assertEqual((s["term"], s["target"]), ("diab", "DM"))


class Applying(unittest.TestCase):
    def approve(self, *terms):
        out = copy.deepcopy(SUG)
        for s in out:
            s["approve"] = s["term"] in terms
        return out

    def test_only_approved_are_applied_and_the_notes_become_readable(self):
        new, done, refused = apply_terms.apply(RAW, self.approve("bs", "crea", "wgt", "hba", "เวียนศรีษะ"))
        self.assertEqual(len(done), 5, (done, refused))
        self.assertIn("bs", new["params"]["FBS"]["aliases"]); self.assertNotIn("bs", RAW["params"]["FBS"]["aliases"])
        self.assertEqual(apply_terms.apply(RAW, self.approve())[1], [])                   # nothing approved = nothing applied
        before = learn_terms.coverage(TEXTS)
        import engine.parse_note as pn
        lex, orig = Lexicon(new), pn.load_lexicon
        pn.load_lexicon = lambda *_: lex
        try: after = learn_terms.coverage(TEXTS)
        finally: pn.load_lexicon = orig
        self.assertGreater(after["fully_read"], before["fully_read"] + 0.3)

    def test_nothing_that_was_read_before_changes(self):
        new, _, _ = apply_terms.apply(RAW, self.approve("bs", "crea", "wgt", "hba", "เวียนศรีษะ"))
        self.assertEqual(apply_terms.regression(RAW, new, apply_terms.check_corpus(TEXTS)), [])

    def test_a_term_that_already_means_something_is_refused(self):
        bad = [{"approve": True, "kind": "param_alias", "term": "bp", "target": "FBS"}, {"approve": True, "kind": "param_alias", "term": "mg", "target": "FBS"},
               {"approve": True, "kind": "concept_phrase", "term": "เวียนหัว", "target": "palpitations"}, {"approve": True, "kind": "problem_alias", "term": "dm", "target": "HT"}]
        new, done, refused = apply_terms.apply(RAW, bad)
        self.assertEqual((done, len(refused)), ([], 4)); self.assertEqual(new, RAW)

    def test_bad_targets_and_shapes_are_refused(self):
        bad = [{"approve": True, "kind": "param_alias", "term": "xx", "target": "NoSuch"}, {"approve": True, "kind": "param_alias", "term": "bad name!", "target": "FBS"},
               {"approve": True, "kind": "concept_phrase", "term": "ปวด5", "target": "headache"}, {"approve": "yes", "kind": "param_alias", "term": "ok1", "target": "FBS"}]
        self.assertEqual(apply_terms.apply(RAW, bad)[1], [])

    def test_regression_guard_catches_a_change_in_how_old_notes_are_read(self):
        broken = copy.deepcopy(RAW)
        broken["params"]["FBS"]["aliases"].remove("fbs"); broken["params"]["HbA1c"]["aliases"].append("fbs")        # 'fbs' would now mean HbA1c
        bad = apply_terms.regression(RAW, broken, ["DM : FBS 120"])
        self.assertTrue(bad and "FBS" in bad[0])

    def test_applied_lexicon_still_loads_and_validates(self):
        new, _, _ = apply_terms.apply(RAW, self.approve("bs", "hba"))
        Lexicon(new)


if __name__ == "__main__":
    unittest.main()
