#!/usr/bin/env python3
"""Applies the suggestions a doctor approved in learned_terms.json to data/lexicon.json, with safety checks.

  python3 tools/apply_terms.py learned_terms.json                         # dry run: shows what would change and the effect on --notes
  python3 tools/apply_terms.py learned_terms.json --notes my_notes.txt    # also measures how much more of YOUR notes is understood
  python3 tools/apply_terms.py learned_terms.json --write                 # really writes (keeps data/lexicon.json.bak)

Only entries with "approve": true are used. A term is refused if it already means something else (another parameter/problem/symptom/unit),
and the whole change is refused if, on the golden examples + synthetic notes + your notes, any value or symptom that was read BEFORE is read
differently AFTER (new readings may only be added, never changed).
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import golden  # noqa: E402
from engine.lexicon import DATA_DIR, Lexicon  # noqa: E402
from engine.parse_note import collect_params, latest_visit, parse_note  # noqa: E402
from tools import synth_notes  # noqa: E402
from tools.learn_terms import coverage, split_notes  # noqa: E402

LEXICON = os.path.join(DATA_DIR, "lexicon.json")
KINDS = ("param_alias", "concept_phrase", "problem_alias")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s.lower())


def used_terms(data: dict) -> dict[str, str]:
    """Every word the dictionary already uses -> what it means (to refuse a clash)."""
    out: dict[str, str] = {}
    for canon, spec in data["params"].items():
        for a in spec["aliases"] + [canon]: out[_norm(a)] = f"ค่า {canon}"
    for canon, al in data["problems"].items():
        for a in al + [canon]: out[_norm(a)] = f"โรค {canon}"
    for cid, spec in data["concepts"].items():
        for ph in spec["phrases"]: out[_norm(ph)] = f"อาการ {cid}"
    for u in data["units"]:
        out[_norm(u)] = f"หน่วย {u}"
        for frag in re.split(r"[/\d.^]+", u):                          # "mg/dl" also reserves "mg" and "dl"
            if frag: out.setdefault(_norm(frag), f"ส่วนของหน่วย {u}")
    for n in data["negation_prefixes"]: out[_norm(n)] = "คำปฏิเสธ"
    return out


def apply(data: dict, suggestions: list[dict]) -> tuple[dict, list[str], list[str]]:
    new = copy.deepcopy(data)
    done, refused = [], []
    for s in suggestions:
        if s.get("approve") is not True or s.get("kind") not in KINDS or not s.get("target"):
            continue
        term, target, kind = str(s["term"]).strip(), s["target"], s["kind"]
        clash = used_terms(new).get(_norm(term))
        if clash:
            refused.append(f"{term}: ใช้แล้วในพจนานุกรม ({clash})"); continue
        if kind == "param_alias":
            if target not in new["params"] or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,11}", term):
                refused.append(f"{term}: ชื่อค่าไม่ถูกต้องหรือไม่รู้จัก '{target}'"); continue
            new["params"][target]["aliases"].append(term.lower())
        elif kind == "concept_phrase":
            if target not in new["concepts"] or not 2 <= len(term) <= 30 or re.search(r"\d", term):
                refused.append(f"{term}: วลีไม่ถูกต้องหรือไม่รู้จัก '{target}'"); continue
            new["concepts"][target]["phrases"].append(term)
        else:
            if target not in new["problems"] or not 1 <= len(term) <= 40:
                refused.append(f"{term}: ชื่อโรคไม่ถูกต้องหรือไม่รู้จัก '{target}'"); continue
            new["problems"][target].append(term.lower())
        done.append(f"{term} → {target}")
    return new, done, refused


def reading(text: str, lex: Lexicon | None) -> dict:
    parsed = parse_note(text, lexicon=lex)
    visit = latest_visit(parsed)
    return {"params": {k: v["series"] for k, v in collect_params(parsed).items() if not v["invalid"]},
            "concepts": {c["id"]: c["value"] for c in (visit["concepts"] if visit else [])}}


def regression(old: dict, new: dict, texts: list[str]) -> list[str]:
    """Notes where something read before is now read differently (additions are fine)."""
    lo, ln = Lexicon(old), Lexicon(new)
    bad = []
    for i, t in enumerate(texts):
        a, b = reading(t, lo), reading(t, ln)
        for k, v in a["params"].items():
            if b["params"].get(k) != v: bad.append(f"บันทึกที่ {i + 1}: ค่า {k} เปลี่ยนจาก {v} เป็น {b['params'].get(k)}")
        for k, v in a["concepts"].items():
            if b["concepts"].get(k) != v: bad.append(f"บันทึกที่ {i + 1}: อาการ {k} เปลี่ยนจาก {v} เป็น {b['concepts'].get(k)}")
    return bad


def check_corpus(user_texts: list[str]) -> list[str]:
    rnd = random.Random(3)
    return [c["note"] for c in golden.load()] + [synth_notes.make(rnd)["note"] for _ in range(150)] + user_texts


def apply_and_write(selected: list[dict], path: str | None = None) -> dict:
    """For the web page: apply the approved suggestions to the dictionary with the same checks as the command line. Writes only if every check passes."""
    path = path or LEXICON
    with open(path, encoding="utf-8") as f:
        old = json.load(f)
    new, done, refused = apply(old, [dict(s, approve=True) for s in selected])
    if not done:
        return {"success": False, "applied": [], "refused": refused, "regression": []}
    bad = regression(old, new, check_corpus([]))
    if bad:
        return {"success": False, "applied": [], "refused": refused, "regression": bad[:20]}
    with open(path + ".bak", "w", encoding="utf-8") as f:
        json.dump(old, f, ensure_ascii=False, indent=1)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return {"success": True, "applied": done, "refused": refused, "regression": []}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file"); ap.add_argument("--notes"); ap.add_argument("--write", action="store_true"); ap.add_argument("--lexicon", default=LEXICON)
    a = ap.parse_args()
    suggestions = json.load(open(a.file, encoding="utf-8")).get("suggestions", [])
    with open(a.lexicon, encoding="utf-8") as f:
        old = json.load(f)
    new, done, refused = apply(old, suggestions)
    user = split_notes(open(a.notes, encoding="utf-8").read()) if a.notes else []
    print(f"approved and applicable: {len(done)}   refused: {len(refused)}")
    for d in done: print("  +", d)
    for r in refused: print("  ✗", r)
    if not done:
        sys.exit("nothing to apply")
    bad = regression(old, new, check_corpus(user))
    if bad:
        print("\nREFUSED: the change would alter something that was read correctly before:")
        for b in bad[:20]: print("  ", b)
        sys.exit(1)
    if user:
        print(f"\ncoverage of your notes   before: {coverage(user)}")
        import engine.parse_note as pn
        lex_new = Lexicon(new)
        orig = pn.load_lexicon; pn.load_lexicon = lambda *_: lex_new
        try: print(f"                         after:  {coverage(user)}")
        finally: pn.load_lexicon = orig
    if not a.write:
        print("\ndry run only. Add --write to apply."); return
    with open(a.lexicon + ".bak", "w", encoding="utf-8") as f: json.dump(old, f, ensure_ascii=False, indent=1)
    with open(a.lexicon, "w", encoding="utf-8") as f: json.dump(new, f, ensure_ascii=False, indent=1)
    print(f"written. previous version kept at {a.lexicon}.bak")


if __name__ == "__main__":
    main()
