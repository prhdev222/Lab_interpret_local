"""Tiny char-level tagger: which parameter does each number in an OPD note belong to?
Train on SEEN aliases only; test on SEEN (in-distribution) and UNSEEN aliases. Compare with the rule parser on the same notes.
Run: .venv/bin/python train.py"""
import random, sys, time, json, os
import numpy as np, torch, torch.nn as nn
from synth import gen_note, tokens, CLASSES

torch.manual_seed(0); np.random.seed(0)
LABELS = ["O"] + CLASSES
L2I = {l: i for i, l in enumerate(LABELS)}
D2A = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
MAXLEN = 256


def make(n, seed, unseen):
    r = random.Random(seed)
    return [gen_note(r, unseen) for _ in range(n)]


train = make(40000, 1, False)
val_seen, val_unseen = make(2000, 2, False), make(2000, 3, True)
chars = sorted({c for t, _ in train for c in t.translate(D2A)})
C2I = {c: i + 2 for i, c in enumerate(chars)}             # 0 pad, 1 unk
print("vocab", len(C2I), "train notes", len(train), flush=True)


def enc(text):
    return [C2I.get(c, 1) for c in text.translate(D2A)[:MAXLEN]]


def batchify(items, drop=0.0):
    ids = torch.zeros(len(items), MAXLEN, dtype=torch.long)
    lab = torch.full((len(items), MAXLEN), -100, dtype=torch.long)
    for i, (t, l) in enumerate(items):
        e = enc(t)
        ids[i, :len(e)] = torch.tensor(e)
        lab[i, :len(e)] = torch.tensor([L2I[x] for x in l[:MAXLEN]])
    if drop:
        m = (torch.rand(ids.shape) < drop) & (ids > 1)
        ids = ids.masked_fill(m, 1)
    return ids, lab


class Tagger(nn.Module):
    def __init__(self, v, e=48, h=96, k=len(LABELS)):
        super().__init__()
        self.emb = nn.Embedding(v, e, padding_idx=0)
        self.rnn = nn.GRU(e, h, num_layers=2, bidirectional=True, batch_first=True)
        self.out = nn.Linear(2 * h, k)

    def forward(self, x):
        return self.out(self.rnn(self.emb(x))[0])


dev = "mps" if torch.backends.mps.is_available() else "cpu"
model = Tagger(len(C2I) + 2).to(dev)
print("params", sum(p.numel() for p in model.parameters()), "device", dev, flush=True)
opt = torch.optim.AdamW(model.parameters(), lr=3e-3, weight_decay=1e-2)
EPOCHS, BS = 6, 128
steps = EPOCHS * (len(train) // BS)
sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=3e-3, total_steps=steps)
lossf = nn.CrossEntropyLoss(ignore_index=-100)


@torch.no_grad()
def predict(items):
    model.eval()
    probs = []
    for i in range(0, len(items), 256):
        ids, _ = batchify(items[i:i + 256])
        probs.append(torch.softmax(model(ids.to(dev)), -1).cpu().numpy())
    return np.concatenate(probs)


def token_eval(items, probs):
    """per number token: predicted class = argmax of the mean char probability over the token."""
    rows = []
    for (t, l), p in zip(items, probs):
        for a, b in tokens(t):
            if b > MAXLEN: continue
            m = p[a:b].mean(0)
            rows.append((l[a], LABELS[int(m.argmax())], float(m.max())))
    return rows


def report(name, rows):
    acc = np.mean([g == p for g, p, _ in rows])
    lab = [r for r in rows if r[0] != "O"]
    acc_l = np.mean([g == p for g, p, _ in lab])
    fp = np.mean([p != "O" for g, p, _ in rows if g == "O"])
    print(f"{name:<18} numbers {len(rows):>6} | all-token acc {acc:.3f} | lab-value acc {acc_l:.3f} | date/age numbers wrongly tagged as lab {fp:.3f}")
    for thr in (0.8, 0.9, 0.95):
        kept = [r for r in lab if r[2] >= thr]
        print(f"   confidence >= {thr}: coverage {len(kept)/len(lab):.2f}, accuracy {np.mean([g == p for g, p, _ in kept]):.3f}" if kept else f"   conf>={thr}: none")
    return acc_l


t0 = time.time()
for ep in range(EPOCHS):
    model.train(); random.Random(ep).shuffle(train); tot = 0
    for i in range(0, len(train) - BS + 1, BS):
        ids, lab = batchify(train[i:i + BS], drop=0.04)
        ids, lab = ids.to(dev), lab.to(dev)
        loss = lossf(model(ids).reshape(-1, len(LABELS)), lab.reshape(-1))
        opt.zero_grad(); loss.backward(); nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step(); sched.step(); tot += loss.item()
    print(f"epoch {ep+1} loss {tot/(len(train)//BS):.4f}  ({time.time()-t0:.0f}s)", flush=True)

ps, pu = predict(val_seen), predict(val_unseen)
print("== tagger =="); report("seen aliases", token_eval(val_seen, ps)); report("UNSEEN aliases", token_eval(val_unseen, pu))

# baseline: the existing rule parser on the same notes (lab values it recovers under the right parameter)
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
from engine.parse_note import parse_note, collect_params


def baseline(items):
    hit = tot = 0
    for t, l in items:
        try: got = collect_params(parse_note(t.translate(D2A)))
        except Exception: got = {}
        for a, b in tokens(t):
            c = l[a]
            if c == "O": continue
            tot += 1
            s = t.translate(D2A)[a:b]
            ser = got.get(c, {}).get("series", [])
            flat = [f"{x[0]:g}/{x[1]:g}" if isinstance(x, list) else f"{x:g}" for x in ser]
            hit += s in flat
    return hit / tot


print("== rule parser (existing, no ML) =="); print(f"seen aliases   lab-value recall {baseline(val_seen):.3f}"); print(f"UNSEEN aliases lab-value recall {baseline(val_unseen):.3f}")

# export
torch.save({"sd": model.state_dict(), "c2i": C2I}, "tagger.pt")
json.dump({"c2i": C2I, "labels": LABELS, "maxlen": MAXLEN}, open("tagger_meta.json", "w"), ensure_ascii=False)
model.eval().cpu()
torch.onnx.export(model, torch.zeros(1, 64, dtype=torch.long), "tagger.onnx", input_names=["ids"], output_names=["logits"],
                  dynamic_axes={"ids": {0: "b", 1: "t"}, "logits": {0: "b", 1: "t"}}, opset_version=17, dynamo=False)
print("onnx size KB", os.path.getsize("tagger.onnx") // 1024)
