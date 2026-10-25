"""Optional helper: a tiny ONNX model (ml_tagger/) guesses which parameter an UNREAD number belongs to.
It only SUGGESTS. Nothing changes until the doctor accepts a suggestion on the page, and the accepted change is a visible
edit of the note text (the unknown name is replaced by the standard one), after which the normal rule engine reads the note.
Needs `pip install onnxruntime numpy`; if they or the model files are missing, available() is False and the feature is off.
Nothing about the note is stored or logged."""
from __future__ import annotations

import json
import os
import re

from .lexicon import load_lexicon
from .parse_note import collect_params, parse_note

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.environ.get("TAGGER_DIR") or os.path.join(ROOT, "ml_tagger", "real_eval")
D2A = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
NUM = re.compile(r"\d+(?:\.\d+)?(?:/\d+){0,2}")
MIN_CONF = 0.5
STANDARD_NAME = {"FBS": "FBS", "HbA1c": "HbA1c", "BP": "BP", "HomeBP": "HMBP", "BW": "BW", "BMI": "BMI", "Creatinine": "Cr", "eGFR": "eGFR"}
LABEL_TH = {"FBS": "FBS (น้ำตาลตอนอดอาหาร)", "HbA1c": "HbA1c", "BP": "BP (ความดัน)", "HomeBP": "HMBP (ความดันที่บ้าน)", "BW": "BW (น้ำหนัก)",
            "BMI": "BMI", "Creatinine": "Cr (creatinine)", "eGFR": "eGFR"}
NAME_TAIL = re.compile(r"([^\s:：=,;()\d%][^\s:：=,;()]*(?: [^\s:：=,;()\d%][^\s:：=,;()]*){0,2})$")
ARROW_GAP = re.compile(r"^[\s\-=>→⇒]*$")

_cache: dict = {}


def available(model_dir: str | None = None) -> bool:
    return _load(model_dir or MODEL_DIR) is not None


def _load(model_dir: str):
    if model_dir in _cache:
        return _cache[model_dir]
    tg = None
    try:
        import numpy as np
        import onnxruntime as ort
        meta = json.load(open(os.path.join(model_dir, "tagger_meta.json"), encoding="utf-8"))
        opts = ort.SessionOptions(); opts.intra_op_num_threads = 1
        sess = ort.InferenceSession(os.path.join(model_dir, "tagger.onnx"), opts, providers=["CPUExecutionProvider"])
        tg = (np, sess, meta["c2i"], meta["labels"], meta["maxlen"])
    except Exception:                                         # missing package or model -> feature simply off
        tg = None
    _cache[model_dir] = tg
    return tg


def _chunks(text: str, maxlen: int):
    out, pos, cur_start, cur = [], 0, 0, ""
    for ln in text.splitlines(keepends=True):
        while len(ln) > maxlen:
            if cur:
                out.append((cur_start, cur)); cur = ""
            out.append((pos, ln[:maxlen])); pos += maxlen; ln = ln[maxlen:]; cur_start = pos
        if len(cur) + len(ln) > maxlen:
            out.append((cur_start, cur)); cur_start, cur = pos, ""
        cur += ln; pos += len(ln)
    if cur:
        out.append((cur_start, cur))
    return out


def tag_numbers(norm: str, model_dir: str | None = None):
    """[(start, end, label, confidence)] for every number token ('O' = not a lab value)."""
    t = _load(model_dir or MODEL_DIR)
    if t is None:
        return []
    np, sess, c2i, labels, maxlen = t
    probs = np.zeros((len(norm), len(labels)), dtype=np.float32)
    for off, ch in _chunks(norm, maxlen):
        ids = np.array([[c2i.get(c, 1) for c in ch]], dtype=np.int64)
        lg = sess.run(None, {"ids": ids})[0][0]
        e = np.exp(lg - lg.max(-1, keepdims=True))
        probs[off:off + len(ch)] = e / e.sum(-1, keepdims=True)
    res = []
    for m in NUM.finditer(norm):
        p = probs[m.start():m.end()].mean(0)
        res.append((m.start(), m.end(), labels[int(p.argmax())], float(p.max())))
    return res


def _known_words() -> set[str]:
    lex = load_lexicon().data
    words = {a.lower() for p in lex.get("params", {}).values() for a in p.get("aliases", [])}
    words |= {a.lower() for al in lex.get("problems", {}).values() for a in al}
    words |= {u.lower() for u in lex.get("units", [])}
    words |= {w.lower() for w in lex.get("filler_words", [])}
    return words


def _name_before(norm: str, s: int, bound: int, known: set[str]):
    """The unknown name written just before the first number of a run -> (name, start, end) or None.
    `bound` = end of the previous number that is itself a lab value (so '120->130 glycated Hb 9.4' yields 'glycated Hb')."""
    line_start = norm.rfind("\n", 0, s) + 1
    start = max(line_start, bound)
    for sep in (":", "：", "="):                               # 'DM : sugar 120' / 'sugar=120' -> the name sits after the header colon
        i = norm.rfind(sep, start, s)
        if i != -1 and sep != "=": start = i + 1
    seg = norm[start:s]
    for m in re.finditer(r"\S+", seg):                       # first word that is not an arrow/unit/header word
        w = m.group(0).strip("->→⇒=,;([")
        if w and w.lower() not in known:
            first = start + m.start() + (len(m.group(0)) - len(m.group(0).lstrip("->→⇒=,;([")))
            break
    else:
        return None
    name = norm[first:s].rstrip(" :：=([\t")
    if not name or len(name.split()) > 3 or len(name) > 30 or name.lower() in known:
        return None
    return name, first, first + len(name)


def suggest(note: str, model_dir: str | None = None) -> list[dict]:
    norm = note.translate(D2A)
    tags = tag_numbers(norm, model_dir)
    if not tags:
        return []
    got = collect_params(parse_note(note))
    read = {c: {f"{x[0]:g}/{x[1]:g}" if isinstance(x, list) else f"{x:g}" for x in d.get("series", [])} for c, d in got.items()}
    known = _known_words()
    cands = [(s, e, lab, conf) for s, e, lab, conf in tags if lab != "O" and conf >= MIN_CONF and norm[s:e] not in read.get(lab, set())]
    groups, cur = [], []
    for c in cands:                                           # numbers of one series (120->130->110) become one suggestion
        if cur and cur[-1][2] == c[2] and ARROW_GAP.match(norm[cur[-1][1]:c[0]]):
            cur.append(c)
        else:
            if cur: groups.append(cur)
            cur = [c]
    if cur: groups.append(cur)
    out = []
    for g in groups:
        bound = max([e for s0, e, lb, _ in tags if lb != "O" and e <= g[0][0]], default=0)
        nm = _name_before(norm, g[0][0], bound, known)
        lab = g[0][2]
        out.append({"param": lab, "label": LABEL_TH.get(lab, lab), "alias": STANDARD_NAME.get(lab, lab), "conf": round(min(x[3] for x in g), 3),
                    "values": [norm[x[0]:x[1]] for x in g], "name": nm[0] if nm else None, "ns": nm[1] if nm else None, "ne": nm[2] if nm else None})
    return out[:12]
