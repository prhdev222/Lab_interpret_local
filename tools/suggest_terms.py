#!/usr/bin/env python3
"""Finds the words your notes use that the dictionary does not know yet, so you can add them to data/lexicon.json.

  python3 tools/suggest_terms.py my_notes.txt --min-count 5        (notes separated by a blank line, or one per line)

Privacy: a phrase is shown only if it appears at least --min-count times, so one-off text (which is where a name or an ID
would hide) never appears. Phrases containing digits are skipped. Nothing is written to disk.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.parse_note import parse_note  # noqa: E402


def leftovers(text: str) -> list[str]:
    parsed = parse_note(text)
    out = []
    for p in parsed["problems"]:
        out += [t for t in re.split(r"[\s,;]+", p["unparsed"]) if t]
    for v in parsed["visits"]:
        out += v["leftover"]
    for u in parsed["unparsed_lines"]:
        out += [t for t in re.split(r"[\s,;]+", u["text"]) if t]
    return out


def suggest(texts: list[str], min_count: int = 5) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for t in texts:
        counts.update(set(x for x in leftovers(t) if not re.search(r"\d", x) and 2 <= len(x) <= 40))   # per-note presence, not repeats
    return [(w, c) for w, c in counts.most_common() if c >= min_count]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file"); ap.add_argument("--min-count", type=int, default=5)
    a = ap.parse_args()
    raw = open(a.file, encoding="utf-8").read()
    texts = [t for t in re.split(r"\n\s*\n", raw) if t.strip()] if "\n\n" in raw else [l for l in raw.splitlines() if l.strip()]
    res = suggest(texts, a.min_count)
    print(f"notes read: {len(texts)}   unknown phrases seen in >= {a.min_count} notes: {len(res)}")
    for w, c in res[:60]:
        print(f"  {c:>4}  {w}")
    if res:
        print("\nAdd the ones that matter to data/lexicon.json (concepts -> phrases), then re-run the evaluation.")


if __name__ == "__main__":
    main()
