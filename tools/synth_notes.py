#!/usr/bin/env python3
"""Synthetic OPD notes in several writing styles, with the ground truth. No patient data is involved or needed.

  python3 tools/synth_notes.py 200 > data_synthetic.jsonl        (one JSON per line: {"note": ..., "expected": {...}})

Styles are *guesses* at how different doctors write. Scores measured on this data are optimistic by construction (the parser
was written by looking at the same styles); the real number comes from running eval/evaluate_parser.py on real,
de-identified, clinician-labelled notes inside the hospital.
"""
from __future__ import annotations

import json
import random
import sys

THAI_DIGITS = str.maketrans("0123456789", "๐๑๒๓๔๕๖๗๘๙")
ARROWS = ["->", "-->", "→", "=>", " -> ", "--->"]


def series(rnd, lo, hi, n, ndigits=0, down=False):
    vals = sorted((round(rnd.uniform(lo, hi), ndigits) for _ in range(n)), reverse=down)
    return [int(v) if ndigits == 0 else v for v in vals] if rnd.random() < 0.5 else vals[::-1] if not down else vals


def fmt(v):
    return f"{v:g}"


def make(rnd: random.Random) -> dict:
    style = rnd.choice(["A", "A", "B", "C", "D"])
    arrow = rnd.choice(ARROWS if style != "A" else ["->", "-->"])
    lines, params, concepts = [], {}, {}

    def join(vals): return arrow.join(fmt(v) for v in vals)

    if rnd.random() < 0.8:                                           # DM
        fbs, a1c = series(rnd, 70, 240, rnd.randint(1, 3)), series(rnd, 5.5, 13, rnd.randint(1, 3), 1)
        params["FBS"], params["HbA1c"] = fbs, a1c
        names = {"A": ("DM", "FBS", "HbA1C"), "B": ("T2DM", "fpg", "A1c"), "C": ("DM", "FBS", "HbA1c"), "D": ("dm", "fbs", "hba1c")}[style]
        unit = "%" if rnd.random() < 0.6 else ""
        lines.append(f"{names[0]} : {names[1]} {join(fbs)} {names[2]} {join(a1c)}{unit}")
    if rnd.random() < 0.7:                                           # HT
        bp = [[rnd.randint(110, 175), rnd.randint(65, 100)] for _ in range(rnd.randint(1, 2))]
        bp = [[max(s, d + 20), d] for s, d in bp]
        hm = [[max(s, d + 20), d] for s, d in [[rnd.randint(105, 160), rnd.randint(60, 95)]]]
        params["BP"], params["HomeBP"] = bp, hm
        pair = lambda v: f"{v[0]}/{v[1]}"
        unit = "mmHg" if rnd.random() < 0.5 else ""
        lines.append(f"{'HT' if style != 'B' else 'HTN'} : BP {arrow.join(pair(v) for v in bp)}{unit} {'HMBP' if style != 'B' else 'hmbp'} {pair(hm[0])}{unit}")
    if rnd.random() < 0.5:                                           # obesity
        bw = series(rnd, 60, 130, rnd.randint(1, 2), 0, down=True)
        bmi = round(rnd.uniform(20, 40), 1)
        params["BW"], params["BMI"] = bw, [bmi]
        lines.append(f"{'Obesity' if style != 'B' else 'Obese'} : {'BW' if style != 'B' else 'wt'} {join(bw)}{'Kg' if rnd.random() < 0.6 else ''} BMI {fmt(bmi)}")
    if rnd.random() < 0.5:                                           # CKD
        cr, gfr = round(rnd.uniform(0.7, 4.0), 1), rnd.randint(10, 100)
        params["Creatinine"], params["eGFR"] = [cr], [gfr]
        lines.append(f"CKD : Cr {fmt(cr)} {'GFR' if style != 'B' else 'eGFR'} {gfr}")
    if rnd.random() < 0.7:                                           # today's line
        day = f"{rnd.randint(1, 28)}/{rnd.randint(1, 12)}/{rnd.choice(['69', '2569', '68'])}"
        parts = []
        for cid, pos, neg in (("dizziness", "มีเวียนศีรษะ", "ไม่มีเวียนศีรษะ"), ("palpitations", "ใจสั่น", "ไม่มีใจสั่น"), ("reduced_intake", "ฉันได้น้อย", None)):
            if rnd.random() < 0.5:
                if neg and rnd.random() < 0.3: parts.append(neg); concepts[cid] = "absent"
                else: parts.append(pos); concepts[cid] = "present"
        smk = rnd.choice([None, ("ยังสูบบุหรี่อยู่", "current"), ("เลิกสูบบุหรี่แล้ว", "former"), ("ไม่สูบบุหรี่", "not_smoking")])
        if smk: parts.append(smk[0]); concepts["smoking"] = smk[1]
        if parts:
            lines.append(f"{day} : {' '.join(parts)}")
    rnd.shuffle(lines) if False else None                            # keep problem lines first, dated line last (as written)
    note = "\n".join(lines) or "DM : FBS 100"
    if not lines: params["FBS"] = [100]
    if style == "C":
        note = note.translate(THAI_DIGITS).replace(":", "：", 1)
        # Thai digits must still parse to the same numbers
    return {"note": note, "expected": {"params": params, "concepts": concepts}}


def main(argv):
    n = int(argv[0]) if argv else 100
    rnd = random.Random(int(argv[1]) if len(argv) > 1 else 1)
    for _ in range(n):
        print(json.dumps(make(rnd), ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
