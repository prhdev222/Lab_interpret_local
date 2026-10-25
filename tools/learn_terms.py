#!/usr/bin/env python3
"""Learns, from YOUR notes on YOUR machine, which unknown abbreviations probably mean which known thing, and proposes them for a doctor to approve.

  python3 tools/learn_terms.py my_notes.txt --out learned_terms.json [--min-count 3]
  (notes separated by a blank line, or one per line; use de-identified notes only)

It is small statistical learning, not a language model and not a cloud service:
  * unknown parameter names (the word written before a number, e.g. "BS 112") are matched to known parameters using the
    values themselves (does 112 look like the FBS values in your notes?), the problem line they appear in (DM line, HT line ...),
    how similar the spelling is, and whether the known parameter already appears in the same line (an alias replaces it, so it would not);
  * unknown words in dated lines are matched to the closest known symptom phrase (spelling variants);
  * unknown problem names are matched to the problem whose parameters they contain.
Nothing is changed by this tool: it writes a review file in which each suggestion has "approve": false. A doctor flips the ones that are right,
then tools/apply_terms.py applies them with checks. Privacy: only words seen in at least --min-count different notes are listed, parameter
names are letters only, and no note text is written to the output.
"""
from __future__ import annotations

import argparse
import difflib
import json
import math
import os
import re
import statistics
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.lexicon import load_lexicon  # noqa: E402
from engine.parse_note import collect_params, normalize, parse_note  # noqa: E402
from tools.suggest_terms import leftovers  # noqa: E402

_CAND = re.compile(r"(?<![A-Za-z0-9ก-๙/])(?P<w>[A-Za-z][A-Za-z0-9]{0,11})\s*[:=]?\s*(?P<v>\d+(?:\.\d+)?)(?:/(?P<v2>\d+(?:\.\d+)?))?")
_DATE = re.compile(r"^\s*\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\s*:")


def bigrams(s: str) -> set[str]:
    s = re.sub(r"\s+", "", s.lower())
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def dice(a: str, b: str) -> float:
    x, y = bigrams(a), bigrams(b)
    return 2 * len(x & y) / (len(x) + len(y)) if x and y else 0.0


def split_notes(raw: str) -> list[str]:
    return [t for t in re.split(r"\n\s*\n", raw) if t.strip()] if "\n\n" in raw else [l for l in raw.splitlines() if l.strip()]


def extract_rows(text: str, lex=None) -> list[dict]:
    """The ONLY thing that may be kept from a note for learning (no text, no age/sex/date/name/user/note id):
       known : {"k","p"=parameter,"v"=first value,"g"=problem group}
       unk   : {"k","t"=unknown abbreviation before a number,"v","pair","g","with"=known parameters in that line}
       word  : {"k","t"=unknown word that is spelled like a known symptom phrase}
       prob  : {"k","t"=unknown problem abbreviation,"with"=parameters in that line}
    Privacy filters: an unknown abbreviation is kept only if it is <= 12 ASCII characters and its value fits some known parameter's plausible range;
    a free-text word is kept only if it resembles a known symptom phrase (so names and other free text never qualify)."""
    lex = lex or load_lexicon()
    known_words = set(lex.param_alias) | {re.sub(r"\s+", "", u.lower()) for u in lex.data["units"]} | {re.sub(r"\s+", "", a.lower()) for a in lex.problem_alias}
    ranges = [spec["range"] for spec in lex.params.values() if spec.get("range") and spec.get("kind") != "range"]
    parsed = parse_note(text)
    by_line = {p["line_no"]: p for p in parsed["problems"]}
    rows: list[dict] = []
    for no, raw in enumerate(normalize(text).split("\n"), 1):
        p = by_line.get(no)
        if p is None or _DATE.match(raw):
            continue
        group = p["problems"][0] if p["known"] else None
        have = sorted({v["param"] for v in p["values"]})
        if group:
            for v in p["values"]:
                if not v["invalid"]:
                    first = v["latest"][0] if isinstance(v["latest"], list) else v["latest"]
                    rows.append({"k": "known", "p": v["param"], "v": float(first), "g": group})
        rest = raw.split(":", 1)[1] if ":" in raw else raw
        for m in _CAND.finditer(rest):
            w = m.group("w").lower()
            val = float(m.group("v"))
            if w in known_words or not group or not any(lo <= val <= hi for lo, hi in ranges):
                continue
            rows.append({"k": "unk", "t": w, "v": val, "pair": m.group("v2") is not None, "g": group, "with": have})
        if not p["known"] and p["values"] and re.fullmatch(r"[A-Za-z]{1,12}", p["name"]):
            rows.append({"k": "prob", "t": p["name"].lower(), "with": have})
    phrases = [ph for spec in lex.concepts.values() for ph in spec["phrases"]]
    for w in {_strip_prefix(x, lex) for x in leftovers(text) if not re.search(r"\d", x) and 2 <= len(x) <= 30 and re.search(r"[A-Za-zก-๙]", x)}:
        if w.lower() in known_words:
            continue
        if any(difflib.SequenceMatcher(None, w, ph).ratio() >= 0.7 or (len(ph) >= 3 and (ph in w or w in ph)) for ph in phrases):
            rows.append({"k": "word", "t": w})
    return rows


def _notes(rows: list[dict]) -> int:
    return len({r["i"] for r in rows}) if rows and "i" in rows[0] else len(rows)


def profile_from_rows(rows: list[dict]) -> dict:
    values: dict[str, list[float]] = defaultdict(list)
    groups: dict[str, Counter] = defaultdict(Counter)
    prob_params: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r["k"] == "known":
            values[r["p"]].append(r["v"]); groups[r["p"]][r["g"]] += 1; prob_params[r["g"]][r["p"]] += 1
    return {"values": values, "groups": groups, "prob_params": prob_params}


def candidates_from_rows(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rows:
        if r["k"] != "unk":
            continue
        c = out.setdefault(r["t"], {"rows": [], "values": [], "pair": False, "groups": Counter(), "with_params": Counter(), "lines": 0})
        c["rows"].append(r); c["lines"] += 1; c["values"].append(r["v"]); c["pair"] = c["pair"] or r["pair"]
        c["groups"][r["g"]] += 1; c["with_params"].update(r["with"])
    for c in out.values():
        c["notes"] = _notes(c["rows"])
    return out


def score_param(cand: dict, target: str, spec: dict, prof: dict, lex) -> tuple[float, dict] | None:
    lo, hi = spec.get("range", (None, None))
    is_bp = spec.get("kind") == "bp"
    if cand["pair"] != is_bp:
        return None
    vals = cand["values"]
    if lo is not None:
        inside = sum(lo <= v <= hi for v in vals) / len(vals)
        if inside < 0.9:
            return None
    else:
        inside = 1.0
    ref = prof["values"].get(target, [])
    cm = statistics.median(vals)
    if len(ref) >= 5:                                            # real evidence: what this parameter looks like in YOUR notes
        pm = statistics.median(ref)
        s_val = math.exp(-2 * abs(math.log(max(cm, 1e-3) / max(pm, 1e-3)))) if pm > 0 and cm > 0 else 0.0
    else:                                                        # no evidence in this corpus: do not reward a wide-open range
        pm, s_val = (math.sqrt(max(lo or 0, 0.1) * hi) if lo is not None else cm), 0.25
    s_spec = 0.0 if lo is None else min(1.0, max(0.0, 1 - math.log10((hi + 1) / (lo + 1)) / 4))      # narrow plausible ranges are more informative
    gtot = sum(prof["groups"].get(target, {}).values()) or 1
    s_ctx = sum(cand["groups"][g] * prof["groups"].get(target, {}).get(g, 0) / gtot for g in cand["groups"]) / max(1, sum(cand["groups"].values()))
    aliases = spec["aliases"] + [target]
    s_name = max(dice(cand_name, a) for cand_name in [cand["name"]] for a in aliases)
    same = cand["with_params"].get(target, 0) / max(1, cand["lines"])
    score = 0.40 * s_val + 0.20 * s_ctx + 0.20 * s_name + 0.10 * (1 - same) + 0.10 * s_spec
    ev = {"median_here": round(cm, 2), "median_known": round(pm, 2), "inside_range": round(inside, 2), "line_context": round(s_ctx, 2),
          "spelling": round(s_name, 2), "range_specificity": round(s_spec, 2), "known_param_also_in_same_line": round(same, 2)}
    return score, ev


def _strip_prefix(w: str, lex) -> str:
    for pre in sorted(["มี"] + list(lex.negations), key=len, reverse=True):
        if w.startswith(pre) and len(w) - len(pre) >= 2:
            return w[len(pre):]
    return w


def concept_suggestions(rows: list[dict], lex, min_count: int, skip: set[str] = frozenset()) -> list[dict]:
    words = [r for r in rows if r["k"] == "word" and r["t"].lower() not in skip]
    counts: Counter[str] = Counter()
    seen: dict[str, set] = defaultdict(set)
    for r in words:
        if "i" in r:
            seen[r["t"]].add(r["i"])
        else:
            counts[r["t"]] += 1
    for w, ids in seen.items():
        counts[w] = len(ids)
    phrases = [(cid, ph) for cid, spec in lex.concepts.items() for ph in spec["phrases"]]
    out = []
    for w, c in counts.most_common():
        if c < min_count:
            continue
        scored = {}
        for cid, ph in phrases:
            r = difflib.SequenceMatcher(None, w, ph).ratio()
            if len(ph) >= 3 and (ph in w or w in ph):
                r = max(r, 0.8)
            if r > scored.get(cid, (0, ""))[0]:
                scored[cid] = (r, ph)
        top = sorted(((r, cid, ph) for cid, (r, ph) in scored.items() if r >= 0.7), reverse=True)[:3]
        if top:
            out.append({"kind": "concept_phrase", "term": w, "target": top[0][1], "score": round(top[0][0], 2), "notes": c,
                        "alternatives": [{"target": cid, "score": round(r, 2)} for r, cid, _ in top[1:]],
                        "evidence": f"สะกดใกล้กับวลีที่รู้จัก '{top[0][2]}' ({lex.concepts[top[0][1]]['label']})"})
    return out


def problem_suggestions(rows: list[dict], lex, prof: dict, min_count: int) -> list[dict]:
    unknown: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["k"] == "prob":
            unknown[r["t"]].append(r)
    out = []
    groups = list(prof["prob_params"])
    for name, lines in unknown.items():
        if _notes(lines) < min_count or not groups:
            continue
        total = Counter(); [total.update(l["with"]) for l in lines]
        best = []
        for g in groups:
            gp, gt = prof["prob_params"][g], sum(prof["prob_params"][g].values())
            ll = sum(n * math.log((gp.get(param, 0) + 0.5) / (gt + 0.5 * len(lex.params))) for param, n in total.items())
            best.append((ll, g))
        best.sort(reverse=True)
        probs = [math.exp(l - best[0][0]) for l, _ in best]
        conf = probs[0] / sum(probs)
        out.append({"kind": "problem_alias", "term": name, "target": best[0][1], "score": round(conf, 2), "notes": _notes(lines),
                    "alternatives": [{"target": g, "score": round(p / sum(probs), 2)} for p, (_, g) in list(zip(probs, best))[1:3] if p / sum(probs) > 0.05],
                    "evidence": "ค่าที่เขียนในบรรทัดนี้: " + ", ".join(f"{k} x{v}" for k, v in total.most_common(5))})
    return out


TAUGHT_TERM = re.compile(r"[A-Za-zก-๙][A-Za-z0-9ก-๙.\- ]{0,23}")


def valid_taught_term(term) -> bool:
    return isinstance(term, str) and bool(TAUGHT_TERM.fullmatch(term)) and term == term.strip() and "  " not in term


def taught_suggestions(rows: list[dict], lex, min_count: int) -> list[dict]:
    """A doctor pressed 'use FBS instead of sugar' (and then 'remember') in the page: {"k":"taught","t":name,"p":parameter}.
    That is a human decision, so fewer repeats are needed than for statistical guesses (at most 2); an admin still approves each one."""
    by_term: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r.get("k") == "taught" and valid_taught_term(r.get("t")) and r.get("p") in lex.params:
            by_term[r["t"].lower()][r["p"]] += 1
    out = []
    for term, c in by_term.items():
        total = sum(c.values())
        if total < min(min_count, 2):
            continue
        (target, n), rest = c.most_common(1)[0], c.most_common()[1:]
        share = n / total
        out.append({"kind": "param_alias", "term": term, "target": target, "score": round(share, 2), "notes": total,
                    "confidence": "high" if share >= 0.8 and n >= 2 else "low",
                    "alternatives": [{"target": t, "score": round(k / total, 2)} for t, k in rest[:2]],
                    "evidence": f"หมอกดยืนยันว่าเป็น {target} {n} จาก {total} ครั้ง" + ("" if not rest else " (มีบางครั้งที่เลือกเป็นอย่างอื่น ตรวจให้ดี)")})
    return out


def _known_terms(lex) -> set[str]:
    return ({re.sub(r"\s+", "", a.lower()) for a in lex.param_alias} | {re.sub(r"\s+", "", a.lower()) for a in lex.problem_alias}
            | {re.sub(r"\s+", "", ph.lower()) for spec in lex.concepts.values() for ph in spec["phrases"]})


def learn_rows(rows: list[dict], min_count: int = 3) -> list[dict]:
    lex = load_lexicon()
    known = _known_terms(lex)
    rows = [r for r in rows if r["k"] in ("known",) or re.sub(r"\s+", "", r["t"].lower()) not in known]       # already approved terms are not proposed again
    prof = profile_from_rows(rows)
    sugg: list[dict] = []
    for w, c in candidates_from_rows(rows).items():
        if c["notes"] < min_count:
            continue
        c["name"] = w
        scored = []
        for target, spec in lex.params.items():
            if spec.get("kind") == "range":
                continue
            r = score_param(c, target, spec, prof, lex)
            if r:
                scored.append((r[0], target, r[1]))
        scored.sort(reverse=True)
        if not scored:
            sugg.append({"kind": "unknown_param", "term": w, "target": None, "score": 0.0, "notes": c["notes"], "alternatives": [],
                         "evidence": "ไม่มีค่าที่รู้จักตัวไหนมีช่วงค่าตรงกัน — อาจเป็นค่าใหม่ ให้เพิ่มเองใน lexicon.json"}); continue
        top = scored[0]
        margin = top[0] - (scored[1][0] if len(scored) > 1 else 0)
        sugg.append({"kind": "param_alias", "term": w, "target": top[1], "score": round(top[0], 2), "notes": c["notes"],
                     "confidence": "high" if top[0] >= 0.7 and margin >= 0.12 else "low",
                     "alternatives": [{"target": t, "score": round(s, 2)} for s, t, _ in scored[1:3]], "evidence": top[2]})
    taught = taught_suggestions(rows, lex, min_count)
    sugg = [x for x in sugg if x["term"] not in {t["term"] for t in taught}] + taught          # a doctor's explicit answer beats a statistical guess
    sugg += concept_suggestions(rows, lex, min_count, {x["term"] for x in sugg}) + problem_suggestions(rows, lex, prof, min_count)
    for i, s in enumerate(sugg, 1):
        s["id"] = f"s-{i}"; s["approve"] = False
    return sugg


def learn(texts: list[str], min_count: int = 3) -> list[dict]:
    """From notes in a file: same pipeline as from the log (notes -> feature rows -> suggestions); the note index only serves to count distinct notes."""
    lex = load_lexicon()
    rows = [dict(r, i=i) for i, t in enumerate(texts) for r in extract_rows(t, lex)]
    return learn_rows(rows, min_count)


def coverage(texts: list[str], lex=None) -> dict:
    """How much of the notes the parser understands: share of notes with nothing left over, and average leftover words per note."""
    left = [len(leftovers(t)) for t in texts]
    return {"notes": len(texts), "fully_read": round(sum(1 for n in left if n == 0) / max(1, len(texts)), 3), "avg_leftover_words": round(sum(left) / max(1, len(texts)), 2)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="notes file, or the learning log (data/learning_log.json) written by the web page's 'save example' button")
    ap.add_argument("--out", default="learned_terms.json"); ap.add_argument("--min-count", type=int, default=3)
    a = ap.parse_args()
    raw = open(a.file, encoding="utf-8").read()
    if raw.lstrip().startswith("{") and '"rows"' in raw[:200000]:
        log = json.loads(raw)
        sugg, texts = learn_rows(log.get("rows", []), a.min_count), []
        print(f"learning log: {len(log.get('rows', []))} feature rows (no note text)")
    else:
        texts = split_notes(raw)
        sugg = learn(texts, a.min_count)
    json.dump({"notes_read": len(texts), "coverage_before": coverage(texts) if texts else None, "min_count": a.min_count,
               "how_to": "เปลี่ยน approve เป็น true เฉพาะข้อที่ถูกต้อง แล้วรัน python3 tools/apply_terms.py " + a.out, "suggestions": sugg},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"notes read: {len(texts)}  coverage: {coverage(texts) if texts else 'n/a'}")
    for s in sugg[:40]:
        print(f"  {s['id']:<6} {s['kind']:<13} {s['term']:<14} -> {str(s['target']):<14} score {s['score']:<5} in {s['notes']} notes")
    print(f"\nwrote {a.out} ({len(sugg)} suggestions, none applied). Review it, set approve:true on the right ones, then run tools/apply_terms.py")


if __name__ == "__main__":
    main()
