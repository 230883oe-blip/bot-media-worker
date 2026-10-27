import difflib, glob, json, os, re, wave
import numpy as np
from faster_whisper import WhisperModel
os.environ.pop("HF_TOKEN", None)
big = WhisperModel("ivrit-ai/whisper-large-v3-ct2", device="cpu", compute_type="int8", cpu_threads=4)
small = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=4)   # חלש יותר = קרוב לשומע שלא משלים מההקשר
targets = json.load(open("ears/targets.json", encoding="utf-8")) if os.path.exists("ears/targets.json") else {}
norm = lambda s: re.sub(r"[^\u05d0-\u05ea ]", "", s).strip()
def f0(y, r):
    n, hop = int(.04 * r), int(.01 * r); lo, hi = int(r / 500), int(r / 70); v = []; tot = 0
    for i in range(0, len(y) - n, hop):
        x = y[i:i + n] - y[i:i + n].mean()
        if x.std() < 0.01: continue
        tot += 1; ac = np.correlate(x, x, "full")[n - 1:]
        if ac[0] <= 0: continue
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] / ac[0] > 0.4: v.append(r / k)
    return round(float(np.median(v))) if v else 0
def syl_rate(y, r):   # גרעיני הברות: שיאים במעטפת האנרגיה
    n = int(.02 * r); e = np.array([np.sqrt((y[i:i + n] ** 2).mean()) for i in range(0, len(y) - n, n // 2)])
    e = np.convolve(e, np.ones(3) / 3, "same"); th = 0.35 * e.max(); pk = sum(1 for i in range(1, len(e) - 1) if e[i] > th and e[i] >= e[i - 1] and e[i] > e[i + 1])
    act = np.nonzero(e > 0.1 * e.max())[0]; dur = (act[-1] - act[0]) * (n // 2) / r if len(act) else len(y) / r
    return round(pk / max(dur, .1), 1), round(dur, 2)
def hear(m, y):
    segs, _ = m.transcribe(y, language="he", beam_size=1, temperature=0, vad_filter=False, word_timestamps=True, condition_on_previous_text=False)
    ws = [w for s in segs for w in s.words]
    return " ".join(w.word.strip() for w in ws), round(min([w.probability for w in ws] or [0]), 2)
res = {}
for p in [q for q in sorted(glob.glob("ears/*.wav")) if (not targets or os.path.basename(q) in targets)]:
    k = os.path.basename(p); w = wave.open(p); r = w.getframerate(); y = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32767; w.close()
    tb, pb = hear(big, y); ts, ps = hear(small, y); sr, dur = syl_rate(y.astype(float), r)
    tgt = norm(targets.get(k, ""))
    sim = lambda t: round(difflib.SequenceMatcher(None, tgt, norm(t)).ratio(), 2) if tgt else None
    res[k] = {"big": tb, "big_sim": sim(tb), "big_minp": pb, "small": ts, "small_sim": sim(ts), "small_minp": ps, "f0": f0(y.astype(float), r), "syl_per_sec": sr, "speech_sec": dur, "sec": round(len(y) / r, 2)}
    print(k, res[k], flush=True)
os.makedirs("artifacts", exist_ok=True); json.dump(res, open("artifacts/ears.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
