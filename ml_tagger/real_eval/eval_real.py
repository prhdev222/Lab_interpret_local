#!/usr/bin/env python3
"""วัดความถูกต้องของตัวติดป้ายตัวเลข (tagger) กับโน้ตจริง **บนเครื่องนี้เท่านั้น** ไม่ใช้เครือข่าย ไม่ส่งข้อมูลออก

  python3 eval_real.py scan   โน้ต        # นับ + เทียบกับ parser เดิม + สุ่มตัวอย่างให้ตรวจ
  python3 eval_real.py review              # หมอดูทีละตัวเลข: Enter=ถูก / พิมพ์เลขคลาสที่ถูก
  python3 eval_real.py score               # สรุปความถูกต้องจากที่หมอตรวจ

โน้ต = โฟลเดอร์ของไฟล์ .txt (1 ไฟล์ = 1 โน้ต) | ไฟล์ .jsonl (field "note") | ไฟล์ .txt เดียวที่คั่นโน้ตด้วยบรรทัด --- หรือ ===
ต้องใช้: pip install onnxruntime numpy   (ไม่ต้องใช้ torch)
ผลลัพธ์อยู่ใน ./real_eval_out/ : ไม่เก็บข้อความโน้ต เก็บเฉพาะตำแหน่ง/คลาส/ความมั่นใจ (ยังเป็นข้อมูลที่เกี่ยวกับผู้ป่วย ห้ามส่งขึ้นเน็ตหรือ GitHub)
"""
import argparse, glob, json, math, os, random, re, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = "real_eval_out"
DEFAULT_ENGINE = os.path.normpath(os.path.join(HERE, "..", ".."))   # repo root when run from ml_tagger/real_eval/
D2A = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
NUM = re.compile(r"\d+(?:\.\d+)?(?:/\d+){0,2}")
SEP = re.compile(r"^\s*(-{3,}|={3,})\s*$", re.M)


def load_notes(path):
    notes = []
    if os.path.isdir(path):
        for f in sorted(glob.glob(os.path.join(path, "*.txt"))):
            notes.append((os.path.basename(f), open(f, encoding="utf-8").read()))
    elif path.endswith(".jsonl"):
        for i, ln in enumerate(open(path, encoding="utf-8")):
            if ln.strip(): notes.append((f"line{i+1}", json.loads(ln)["note"]))
    else:
        for i, t in enumerate(SEP.split(open(path, encoding="utf-8").read())):
            if t and t.strip() and not re.fullmatch(r"-{3,}|={3,}", t.strip()): notes.append((f"note{i+1}", t))
    return notes


class Tagger:
    def __init__(self, folder=HERE):
        import onnxruntime as ort
        m = json.load(open(os.path.join(folder, "tagger_meta.json"), encoding="utf-8"))
        self.c2i, self.labels, self.maxlen = m["c2i"], m["labels"], m["maxlen"]
        o = ort.SessionOptions(); o.intra_op_num_threads = 1
        self.s = ort.InferenceSession(os.path.join(folder, "tagger.onnx"), o, providers=["CPUExecutionProvider"])

    def chunks(self, text):
        """split into <=maxlen windows at line breaks (the model was trained on short notes)"""
        out, pos = [], 0
        cur_start, cur = 0, ""
        for ln in text.splitlines(keepends=True):
            while len(ln) > self.maxlen:
                if cur: out.append((cur_start, cur)); cur = ""
                out.append((pos, ln[:self.maxlen])); pos += self.maxlen; ln = ln[self.maxlen:]; cur_start = pos
            if len(cur) + len(ln) > self.maxlen:
                out.append((cur_start, cur)); cur_start, cur = pos, ""
            cur += ln; pos += len(ln)
        if cur: out.append((cur_start, cur))
        return out

    def tag(self, text):
        """-> list of (start, end, label, confidence) for every number token (label 'O' = not a lab value)"""
        norm = text.translate(D2A)
        probs = np.zeros((len(norm), len(self.labels)), dtype=np.float32)
        for off, ch in self.chunks(norm):
            ids = np.array([[self.c2i.get(c, 1) for c in ch]], dtype=np.int64)
            lg = self.s.run(None, {"ids": ids})[0][0]
            e = np.exp(lg - lg.max(-1, keepdims=True)); probs[off:off + len(ch)] = e / e.sum(-1, keepdims=True)
        res = []
        for m in NUM.finditer(norm):
            p = probs[m.start():m.end()].mean(0)
            res.append((m.start(), m.end(), self.labels[int(p.argmax())], float(p.max())))
        return res


def rule_flat(norm, engine):
    """values the existing rule parser recovered, per parameter: {class: {'120','150/90',...}}"""
    sys.path.insert(0, engine)
    from engine.parse_note import parse_note, collect_params
    got = collect_params(parse_note(norm))
    out = {}
    for c, d in got.items():
        out[c] = {f"{x[0]:g}/{x[1]:g}" if isinstance(x, list) else f"{x:g}" for x in d.get("series", [])}
    return out


def cmd_scan(a):  # noqa
    os.makedirs(OUT, mode=0o700, exist_ok=True)
    notes, tg = load_notes(a.notes), Tagger()
    engine = os.path.expanduser(a.engine) if a.engine else None
    if engine and not os.path.isdir(os.path.join(engine, "engine")): print("ไม่พบ engine ที่", engine, "-> ข้ามการเทียบกับ parser เดิม"); engine = None
    rows, per_class, tot = [], {}, 0
    for nid, text in notes:
        norm = text.translate(D2A)
        rf = rule_flat(norm, engine) if engine else None
        for s, e, lab, conf in tg.tag(text):
            tot += 1
            if lab == "O": continue
            per_class[lab] = per_class.get(lab, 0) + 1
            flag = ""
            if rf is not None and norm[s:e] not in rf.get(lab, set()): flag = "tagger_only"   # parser did not give this value to this parameter
            elif conf < 0.9: flag = "low_conf"
            rows.append({"note": nid, "s": s, "e": e, "pred": lab, "conf": round(conf, 4), "flag": flag})
    print(f"โน้ต {len(notes)} | ตัวเลขทั้งหมด {tot} | ตัวเลขที่ tagger ว่าเป็นค่าแล็บ {len(rows)}")
    print("ตามพารามิเตอร์:", per_class)
    if rows:
        hi = sum(r["conf"] >= 0.95 for r in rows)
        print(f"ความมั่นใจ >= 0.95: {hi}/{len(rows)} ({100*hi//len(rows)}%)")
    if engine:
        t = sum(r["flag"] == "tagger_only" for r in rows)
        print(f"tagger เห็นแต่ parser เดิมไม่ให้ค่านี้กับพารามิเตอร์เดียวกัน: {t} ตัว (อาจเป็นชื่อใหม่ที่ parser ไม่รู้จัก หรือ tagger พลาด -> ต้องตรวจ)")
    rnd = random.Random(7)
    rnd.shuffle(rows)
    half = a.n // 2
    sample = [dict(r, grp="random") for r in rows[:half]]                       # true random sample = headline accuracy
    sample += [dict(r, grp=r["flag"]) for r in rows[half:] if r["flag"]][:a.n - len(sample)]   # then the doubtful ones
    rnd.shuffle(sample)
    json.dump({"source": os.path.abspath(a.notes), "items": sample}, open(os.path.join(OUT, "sample.json"), "w"))
    print(f"สุ่มตัวอย่างให้ตรวจ {len(sample)} ตัว -> {OUT}/sample.json   ต่อไป: python3 eval_real.py review")


def snippet(text, s, e):
    t = lambda x: x.replace("\n", "⏎")
    return t(text[max(0, s - 60):s]) + "【" + text[s:e] + "】" + t(text[e:e + 30])


def cmd_review(a, ask=input, show=print):
    sample = json.load(open(os.path.join(OUT, "sample.json")))
    notes = dict(load_notes(sample["source"])); tg_labels = Tagger().labels
    rpath = os.path.join(OUT, "review.jsonl")
    done = {json.loads(l)["i"] for l in open(rpath)} if os.path.exists(rpath) else set()
    show("คลาส: " + "  ".join(f"{i}={l}" for i, l in enumerate(tg_labels[1:], 1)) + "  0=ไม่ใช่ค่าแล็บ")
    show("Enter=ที่ทำนายถูก | ตัวเลขคลาส=คลาสที่ถูก | s=ข้าม | q=ออก (กลับมาทำต่อได้)\n")
    with open(rpath, "a") as f:
        for i, it in enumerate(sample["items"]):
            if i in done: continue
            text = notes.get(it["note"])
            if text is None: continue
            show(f"[{i+1}/{len(sample['items'])}] {snippet(text.translate(D2A), it['s'], it['e'])}")
            ans = ask(f"   ทำนาย: {it['pred']} ({it['conf']:.2f}) > ").strip().lower()
            if ans == "q": break
            if ans == "s": continue
            if ans == "": true = it["pred"]
            elif ans.isdigit() and int(ans) < len(tg_labels): true = "O" if ans == "0" else tg_labels[int(ans)]
            else: show("   (ไม่เข้าใจ ข้ามข้อนี้)"); continue
            f.write(json.dumps({"i": i, "pred": it["pred"], "true": true, "conf": it["conf"], "grp": it["grp"]}) + "\n"); f.flush()


def wilson(k, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - r) / d, (c + r) / d)


def cmd_score(a, show=print):
    rows = [json.loads(l) for l in open(os.path.join(OUT, "review.jsonl"))]
    if not rows: show("ยังไม่มีผลการตรวจ"); return
    def acc(rs, name):
        k = sum(r["pred"] == r["true"] for r in rs); lo, hi = wilson(k, len(rs))
        show(f"{name:<34} ตรวจ {len(rs):>4} | ถูก {k:>4} = {100*k/max(1,len(rs)):.1f}%  (ช่วงเชื่อมั่น 95%: {100*lo:.0f}-{100*hi:.0f}%)")
    rnd = [r for r in rows if r["grp"] == "random"]
    acc(rnd, "ตัวอย่างสุ่ม (ตัวชี้วัดหลัก)") if rnd else show("ไม่มีตัวอย่างสุ่ม")
    acc([r for r in rows if r["grp"] == "tagger_only"], "ที่ parser เดิมไม่เห็นด้วย")
    acc([r for r in rows if r["grp"] == "low_conf"], "ความมั่นใจต่ำ (<0.9)")
    for thr in (0.9, 0.95, 0.99):
        kept = [r for r in rows if r["conf"] >= thr]
        if kept: acc(kept, f"เฉพาะความมั่นใจ >= {thr} (ครอบคลุม {100*len(kept)//len(rows)}%)")
    wrong = {}
    for r in rows:
        if r["pred"] != r["true"]: wrong[(r["pred"], r["true"])] = wrong.get((r["pred"], r["true"]), 0) + 1
    if wrong: show("ที่พลาดบ่อย (ทำนาย -> จริง):", sorted(wrong.items(), key=lambda x: -x[1])[:8])
    if len(rnd) < 100: show("\n! ตัวอย่างสุ่มน้อยกว่า 100 ตัว ตัวเลขยังกว้าง/ไม่แน่นอน ควรตรวจเพิ่ม")
    show("ตัวเลขนี้วัดเฉพาะ 'ตัวเลขนี้เป็นพารามิเตอร์อะไร' ไม่ใช่ความถูกต้องของการแปลผลทางคลินิก")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("notes"); s.add_argument("--n", type=int, default=200)
    s.add_argument("--engine", default=DEFAULT_ENGINE, help="โฟลเดอร์ lab-interpret-local เพื่อเทียบกับ parser เดิม (ไม่มีก็ข้าม)")
    sub.add_parser("review"); sub.add_parser("score")
    a = ap.parse_args(); {"scan": cmd_scan, "review": cmd_review, "score": cmd_score}[a.cmd](a)
