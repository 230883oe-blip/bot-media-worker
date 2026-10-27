import glob, json, os, wave
import numpy as np
from faster_whisper import WhisperModel
os.environ.pop("HF_TOKEN", None)
m = WhisperModel("ivrit-ai/whisper-large-v3-ct2", device="cpu", compute_type="int8", cpu_threads=4)
def f0(y, r):
    n, hop = int(.04 * r), int(.01 * r); lo, hi = int(r / 500), int(r / 70); v = []; tot = 0
    for i in range(0, len(y) - n, hop):
        x = y[i:i + n] - y[i:i + n].mean()
        if x.std() < 0.01: continue
        tot += 1; ac = np.correlate(x, x, "full")[n - 1:]
        if ac[0] <= 0: continue
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] / ac[0] > 0.4: v.append(r / k)
    return (round(float(np.median(v))) if v else 0), round(len(v) / max(tot, 1), 2)
def cent(y, r):
    s = np.abs(np.fft.rfft(y)); f = np.fft.rfftfreq(len(y), 1 / r); return round(float((s * f).sum() / s.sum()))
res = {}
for p in sorted(glob.glob("ears/*.wav")):
    w = wave.open(p); r = w.getframerate(); y = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32767; w.close()
    segs, _ = m.transcribe(y, language="he", beam_size=5, vad_filter=False)
    F, V = f0(y.astype(float), r)
    res[os.path.basename(p)] = {"text": " ".join(s.text.strip() for s in segs), "f0": F, "voiced": V, "centroid": cent(y, r), "sec": round(len(y) / r, 2)}
    print(os.path.basename(p), res[os.path.basename(p)], flush=True)
os.makedirs("artifacts", exist_ok=True); json.dump(res, open("artifacts/ears.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
