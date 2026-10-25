import json, time, sys, numpy as np, onnxruntime as ort
meta = json.load(open("tagger_meta.json")); c2i = meta["c2i"]
note = "DM : FBS 120->130->110 HbA1C 12->10->6.5%\nHT : BP 150/90mmHg HMBP 120/80mmHg\nObesity : BW 110-->100Kg BMI 31\nCKD : Cr 1.5 GFR 54\n22/10/69 : มีเวียนศีรษะ ฉันได้น้อย ยังสูบบุหรี่อยู่"
ids = np.array([[c2i.get(c, 1) for c in note[:256]]], dtype=np.int64)
o = ort.SessionOptions(); o.intra_op_num_threads = int(sys.argv[2]) if len(sys.argv) > 2 else 1
s = ort.InferenceSession(sys.argv[1], o, providers=["CPUExecutionProvider"])
for _ in range(5): s.run(None, {"ids": ids})
t = time.perf_counter(); n = 100
for _ in range(n): out = s.run(None, {"ids": ids})[0]
ms = (time.perf_counter() - t) / n * 1000
print(f"{sys.argv[1]} chars={ids.shape[1]} threads={o.intra_op_num_threads} {ms:.1f} ms/note")
