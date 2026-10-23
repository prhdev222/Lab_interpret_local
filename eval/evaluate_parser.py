#!/usr/bin/env python3
"""Measures how well the note parser reads notes, per field. Run it on YOUR machine with YOUR gold file.

  python3 eval/evaluate_parser.py --synthetic 300                  # sanity check only (optimistic by construction)
  python3 eval/evaluate_parser.py --gold my_gold.jsonl             # real measurement: one JSON per line {"note": "...", "expected": {...}}

expected = {"params": {"HbA1c": [12, 10, 6.5], "BP": [[150, 90]], ...}, "concepts": {"dizziness": "present", "smoking": "current"}}
Privacy: the report prints counts and field names only. Note text is never printed unless you pass --show-text yourself.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.parse_note import collect_params, latest_visit, parse_note  # noqa: E402


def same(a, b) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    try:
        return abs(float(a) - float(b)) < 0.06
    except (TypeError, ValueError):
        return a == b


def evaluate(records: list[dict], show_text: bool = False, out=sys.stdout) -> dict:
    stat = defaultdict(lambda: {"expected": 0, "read": 0, "exact": 0, "wrong": 0, "extra": 0})
    notes_perfect = 0
    problems = []
    for i, rec in enumerate(records):
        parsed = parse_note(rec["note"])
        got = {k: v["series"] for k, v in collect_params(parsed).items() if not v["invalid"]}
        visit = latest_visit(parsed)
        got_c = {c["id"]: c["value"] for c in (visit["concepts"] if visit else [])}
        exp, exp_c = rec["expected"]["params"], rec["expected"].get("concepts", {})
        perfect = True
        for name, series in exp.items():
            s = stat[f"param:{name}"]; s["expected"] += 1
            if name in got:
                s["read"] += 1
                if same(got[name], series): s["exact"] += 1
                else: s["wrong"] += 1; perfect = False; problems.append((i, name, "wrong value"))
            else:
                perfect = False; problems.append((i, name, "missed"))
        for name in got:
            if name not in exp:
                stat[f"param:{name}"]["extra"] += 1; perfect = False; problems.append((i, name, "not in the note (invented)"))
        for cid, val in exp_c.items():
            s = stat[f"concept:{cid}"]; s["expected"] += 1
            if cid in got_c:
                s["read"] += 1
                if got_c[cid] == val: s["exact"] += 1
                else: s["wrong"] += 1; perfect = False; problems.append((i, cid, "wrong state"))
            else:
                perfect = False; problems.append((i, cid, "missed"))
        for cid in got_c:
            if cid not in exp_c:
                stat[f"concept:{cid}"]["extra"] += 1; perfect = False; problems.append((i, cid, "not in the note (invented)"))
        notes_perfect += perfect
    print(f"notes: {len(records)}   read perfectly: {notes_perfect} ({notes_perfect / max(len(records), 1):.1%})\n", file=out)
    print(f"{'field':<26}{'in gold':>8}{'found':>7}{'exact':>7}{'wrong':>7}{'invented':>10}{'recall':>8}{'precision':>10}", file=out)
    for name in sorted(stat):
        s = stat[name]
        recall = s["exact"] / s["expected"] if s["expected"] else float("nan")
        prec = s["exact"] / (s["read"] + s["extra"]) if (s["read"] + s["extra"]) else float("nan")
        print(f"{name:<26}{s['expected']:>8}{s['read']:>7}{s['exact']:>7}{s['wrong']:>7}{s['extra']:>10}{recall:>8.1%}{prec:>10.1%}", file=out)
    if problems:
        print(f"\nproblem cases: {len(problems)}  (note index, field, kind){'' if show_text else ' — note text hidden; use --show-text to see it'}", file=out)
        for i, field, kind in problems[:30]:
            print(f"  #{i}  {field}  {kind}" + (f"\n      {records[i]['note']!r}" if show_text else ""), file=out)
    return {"notes": len(records), "perfect": notes_perfect, "problems": problems, "stat": dict(stat)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold"); ap.add_argument("--synthetic", type=int); ap.add_argument("--show-text", action="store_true")
    a = ap.parse_args()
    if a.gold:
        records = [json.loads(line) for line in open(a.gold, encoding="utf-8") if line.strip()]
    elif a.synthetic:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import random
        from synth_notes import make
        rnd = random.Random(1)
        records = [make(rnd) for _ in range(a.synthetic)]
        print("NOTE: synthetic data written by the same author as the parser — scores are optimistic, not a measurement of real notes.\n")
    else:
        ap.error("give --gold FILE or --synthetic N")
    evaluate(records, a.show_text)


if __name__ == "__main__":
    main()
