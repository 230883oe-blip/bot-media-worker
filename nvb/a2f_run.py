# -*- coding: utf-8 -*-
"""הרצת Audio2Face-3D של NVIDIA על מעבד, ופתרון ל-52 בלנדשייפים.

למה זה קיים, ומה הוא **לא**.

המשתמש ביקש לבחון מנוע תלת-ממד מבוקר (Blender + NVIDIA
Audio2Face-3D) במקום להמשיך לעוות את הווידאו. המגבלה שנמדדה
כאן קודם: **אין במכונה כרטיס NVIDIA** (Intel Graphics בלבד),
ולכן ה-NIM הרשמי של A2F-3D אינו יכול לרוץ כאן.

מה שכן נמדד: NVIDIA פרסמה את ``nvidia/Audio2Face-3D-v3.0``
כ-**ONNX** פתוח ולא-מוגדר (gated=False), ו-``onnxruntime``
כבר מותקן ב-venv של הסטודיו. ONNX רץ על **מעבד**. כלומר
החסם של הכרטיס אינו חסם למודל עצמו - רק ל-NIM ול-TensorRT.

## מה המודול הזה עושה

1. מחלק את השמע לחלונות של שנייה (16kHz, 16000 דגימות).
2. מריץ את הרשת (diffusion, 2 צעדים, GRU דו-שכבתי) וגורף
   את 30 הפריימים המרכזיים מכל חלון - ``num_frames_left_truncate``
   ו-``_right_truncate`` הם 15 כל אחד מתוך 60, כלומר 30fps.
3. פותר את הגאומטריה שחזרה ל-**52 משקלי ARKit** מול בסיס
   הצורות של הדמות (``bs_skin_Claire.npz``, 53 צורות עם שמות
   מפורשים). זה הגשר אל ``rig.arkit`` שכבר מחזיק 52/52 מדויקים.

## מה **לא** נעשה כאן, ובמכוון

* **אין נגיעה במאסטר.** המודול כותב ל-``_3d_exploration/`` בלבד.
* **אין כיול של השער.** ``facegate`` לא נגע. מדד ההגייה החדש
  (``artic.py``) הוא מדד **נוסף**, לא מחליף.
* **אין הצהרה שהמודל "עבד" לפני שנמדד.** כל הפסק יוצא מ-
  ``artic.py`` על ספים שנקבעו מראש.

## מלכודות שנמדדו כאן

* **הפלט הוא מיקום מוחלט ולא דלתא.** נבדק מול ``neutral_skin``
  ולא הונח; ``_is_absolute`` מדפיס את המדידה.
* **הרעש של הדיפוזיה הוא קלט ולא פנימי.** ``noise`` בצורה
  ``[B,3,60,88831]`` = 64MB לפריט. זרע קבוע, אחרת כל הרצה
  מחזירה אנימציה אחרת ואי אפשר להשוות שתי תצורות.
* **ה-GRU סטייטפולי.** ``output_latents`` של חלון אחד הם
  ``input_latents`` של הבא. בלי זה כל שנייה מתחילה מאפס
  והתפרים נשמעים כקפיצה.
"""
from __future__ import annotations

import json
import math
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
A2F = HERE / "a2f"

#: 16kHz, שנייה אחת לחלון. מתוך ``network_info.json`` ולא מנוחש.
SR = 16000
BUF = 16000
TRUNC_L = 15
TRUNC_R = 15
CENTER = 30
FPS = 30.0

#: גדלי הפלט, מתוך ``network_info.json``.
SKIN = 72006        # 24002 * 3
TONGUE = 16806      # 5602 * 3
JAW = 15
EYES = 4
TOTAL = SKIN + TONGUE + JAW + EYES   # 88831

#: רגולריזציה של הפתרון, מתוך ``bs_skin_config_Claire.json``.
L2 = 0.1
TEMPORAL = 0.15


class A2FError(RuntimeError):
    """המודל לא יכול להפיק פלט - נרשם ולא מוחזר בשקט כאפס."""


def read_wav(path, t0: float = 0.0, t1: float = 0.0):
    """מונו 16kHz float32 בטווח ``t0..t1``. ללא תלות חיצונית.

    ``soundfile`` ו-``librosa`` אינם מותקנים כאן, ו-``wave``
    של הספרייה התקנית מספיק: קובצי השמע של הסטודיו הם PCM 16
    ביט בקצב 16000 - נמדד.
    """
    import numpy as np
    with wave.open(str(path), "rb") as w:
        n, ch, sw, sr = (w.getnframes(), w.getnchannels(),
                         w.getsampwidth(), w.getframerate())
        raw = w.readframes(n)
    if sw != 2:
        raise A2FError("נתמך רק PCM 16 ביט, התקבל %d בתים" % sw)
    a = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if sr != SR:
        # דגימה מחדש לינארית. המודל נעול על 16000 ואין כאן scipy.
        m = int(round(len(a) * SR / float(sr)))
        a = np.interp(np.linspace(0, len(a) - 1, m),
                      np.arange(len(a)), a).astype("float32")
    if t1 > t0:
        a = a[int(t0 * SR):int(t1 * SR)]
    if len(a) < SR // 4:
        raise A2FError("קטע השמע קצר מרבע שנייה")
    return a


def _basis(identity: str = "Claire"):
    """``(שמות, B, neutral)`` - בסיס 52 הצורות.

    **הצורות ב-npz הן דלתאות, והמנוחה היא מיקום מוחלט** - נמדד
    ולא הונח: ``|neutral|`` ממוצע 50.1 מול ``|jawOpen|`` 0.21.
    הגרסה הראשונה כאן חיסרה את המנוחה מכל צורה, וקיבלה בסיס
    שכולו המנוחה בסימן הפוך; הפתרון החזיר אפס לכל 52 המשקלים
    ו"אין תנועת פה" - כשל שקט שנראה בדיוק כמו מודל שלא עובד.
    """
    import numpy as np
    z = np.load(A2F / ("bs_skin_%s.npz" % identity), allow_pickle=True)
    names = [n.decode() if isinstance(n, bytes) else str(n)
             for n in z["poseNames"]]
    neutral = np.asarray(z["neutral"], dtype="float32")
    poses = [n for n in names if n != "neutral"]
    if len(poses) != 52:
        raise A2FError("ציפינו ל-52 צורות, יש %d" % len(poses))
    B = np.stack([np.asarray(z[n], dtype="float32").reshape(-1)
                  for n in poses], axis=1)
    return poses, B, neutral


def _is_absolute(pred_frame, neutral) -> dict:
    """מדידה ולא הנחה: הפלט הוא מיקום מוחלט או דלתא?

    נמדד: ``pred`` 0.051 מול ``neutral`` 50.1 - כלומר **דלתא**,
    באותו סדר גודל של צורות הבסיס.
    """
    import numpy as np
    p = np.asarray(pred_frame[:SKIN], dtype="float32")
    nt = neutral.reshape(-1)
    return {"pred_absmean": round(float(np.abs(p).mean()), 5),
            "neutral_absmean": round(float(np.abs(nt).mean()), 5),
            "verdict": "delta" if float(np.abs(p).mean()) <
            float(np.abs(nt).mean()) / 10.0 else "absolute"}


def solve(geo, identity: str = "Claire"):
    """גאומטריה -> ``(שמות, משקלים[frames,52])`` בפתרון ריבועי.

    ``w = argmin ||B·w - d||² + L2·||w||²`` עם הידוק ל-0..1
    והחלקה בזמן. אין כאן L1, סימטריה או ביטול-זוגות של ה-SDK:
    הם משפרים נראות ואינם משנים את **מה שנמדד** (סגירת שפתיים
    ועיגול), ולכן הם מוצהרים חסרים ולא מוסתרים.
    """
    import numpy as np
    names, B, _neutral = _basis(identity)
    BtB = B.T @ B
    BtB += np.eye(BtB.shape[0], dtype="float32") * float(L2) * \
        float(np.trace(BtB)) / BtB.shape[0]
    out = np.zeros((len(geo), len(names)), dtype="float32")
    for i, fr in enumerate(geo):
        # הפלט **הוא** הדלתא. אין כאן חיסור מנוחה - ראו ``_basis``.
        d = np.asarray(fr[:SKIN], dtype="float32")
        w = np.linalg.solve(BtB, B.T @ d)
        out[i] = np.clip(w, 0.0, 1.0)
    if TEMPORAL > 0 and len(out) > 2:
        k = np.asarray([TEMPORAL, 1.0 - 2 * TEMPORAL, TEMPORAL],
                       dtype="float32")
        pad = np.vstack([out[:1], out, out[-1:]])
        out = np.stack([np.convolve(pad[:, j], k, mode="same")[1:-1]
                        for j in range(out.shape[1])], axis=1)
    return names, np.clip(out, 0.0, 1.0)


def lip_sets(identity: str = "Claire", k: int = 400):
    """``(עליונה, תחתונה)`` - אינדקסי קודקודי השפתיים.

    לא נכתבים ביד ולא מנוחשים: הם **נגזרים מהמודל עצמו**. הצורה
    ``mouthClose`` מזיזה בדיוק את השפתיים, ולכן ``k`` הקודקודים
    שהיא מזיזה יותר מכולם *הם* השפתיים. ההפרדה לעליונה/תחתונה
    היא לפי הכיוון שבו ``jawOpen`` מזיזה אותם בציר ``Y``: שפה
    תחתונה יורדת עם הלסת, עליונה כמעט לא.
    """
    import numpy as np
    z = np.load(A2F / ("bs_skin_%s.npz" % identity), allow_pickle=True)
    close = np.asarray(z["mouthClose"], dtype="float32")
    jaw = np.asarray(z["jawOpen"], dtype="float32")
    mag = np.linalg.norm(close, axis=1)
    idx = np.argsort(-mag)[:int(k)]
    dy = jaw[idx, 1]
    lower = idx[dy < float(np.median(dy))]
    upper = idx[dy >= float(np.median(dy))]
    if len(lower) < 20 or len(upper) < 20:
        raise A2FError("הפרדת שפתיים נכשלה: %d/%d" % (len(upper), len(lower)))
    return upper, lower


def lip_aperture(geo, identity: str = "Claire"):
    """מרווח השפתיים לפריים, ביחידות המודל. 0 = מגע.

    **מדד פיזי ולא נגזרת של הפתרון.** פתיחת הלסת של A2F יושבת
    בבלוק ``jaw`` הנפרד ולא במשקלי העור, ולכן ``jawOpen`` כמשקל
    מחזיר מספר קטן גם כשהפה פעור - וזה היה מייצר "אין תנועה"
    על מודל שעובד. כאן נמדד ההפרש בציר ``Y`` בין קודקודי השפה
    העליונה לתחתונה על הרשת המשוחזרת (מנוחה + דלתא).
    """
    import numpy as np
    z = np.load(A2F / ("bs_skin_%s.npz" % identity), allow_pickle=True)
    neutral = np.asarray(z["neutral"], dtype="float32")
    up, lo = lip_sets(identity)
    out = np.zeros(len(geo), dtype="float32")
    for i, fr in enumerate(geo):
        v = neutral + np.asarray(fr[:SKIN], dtype="float32").reshape(-1, 3)
        out[i] = float(v[up, 1].mean() - v[lo, 1].mean())
    base = float((neutral[up, 1].mean() - neutral[lo, 1].mean()))
    return out - base, base


def run(wav, t0: float = 0.0, t1: float = 0.0, identity: str = "Claire",
        seed: int = 1234, emotion=None) -> dict:
    """מריץ את המודל על קטע שמע ומחזיר משקלי ARKit לפריים."""
    import numpy as np
    import onnxruntime as ort

    net = A2F / "network.onnx"
    if not net.exists():
        raise A2FError("network.onnx חסר ב-%s" % A2F)
    audio = read_wav(wav, t0, t1)
    secs = len(audio) / float(SR)

    ids = ["Claire", "James", "Mark"]
    if identity not in ids:
        raise A2FError("זהות לא מוכרת: %s" % identity)
    one = np.zeros((1, 3), dtype="float32")
    one[0, ids.index(identity)] = 1.0
    emo = np.zeros((1, CENTER, 10), dtype="float32")
    if emotion:
        for k, v in dict(emotion).items():
            emo[0, :, int(k)] = float(v)

    so = ort.SessionOptions()
    so.intra_op_num_threads = 6          # 12 ליבות; 6 נמדד כמהיר
    sess = ort.InferenceSession(str(net), so,
                                providers=["CPUExecutionProvider"])

    rng = np.random.default_rng(int(seed))
    noise = rng.standard_normal((1, 3, 60, TOTAL)).astype("float32")
    lat = np.zeros((2, 2, 1, 256), dtype="float32")

    # ריפוד שנייה בכל צד: ``padding_left``/``right`` מ-network_info.
    pad = np.zeros(SR, dtype="float32")
    sig = np.concatenate([pad, audio, pad])
    nwin = int(math.ceil(len(sig) / float(BUF)))
    frames, diag = [], None
    for i in range(nwin):
        chunk = sig[i * BUF:(i + 1) * BUF]
        if len(chunk) < BUF:
            chunk = np.concatenate([chunk, np.zeros(BUF - len(chunk),
                                                    dtype="float32")])
        pred, lat = sess.run(["prediction", "output_latents"], {
            "window": chunk.reshape(1, BUF),
            "identity": one, "emotion": emo,
            "input_latents": lat, "noise": noise})
        mid = pred[0][TRUNC_L:TRUNC_L + CENTER]
        if diag is None:
            _n, _B, neutral = _basis(identity)
            diag = _is_absolute(mid[0], neutral)
        frames.append(mid)
    geo = np.concatenate(frames, axis=0)
    # החלון הראשון הוא הריפוד השקט - נזרק, וכך גם העודף בסוף.
    want = int(round(secs * FPS))
    geo = geo[CENTER:CENTER + want]
    if len(geo) < 4:
        raise A2FError("חזרו %d פריימים בלבד" % len(geo))
    names, w = solve(geo, identity)
    gap, base = lip_aperture(geo, identity)
    return {"names": names, "weights": w, "fps": FPS,
            "seconds": round(secs, 3), "frames": int(len(w)),
            "identity": identity, "seed": int(seed),
            "geometry_diag": diag,
            "lip_gap": gap, "lip_gap_neutral": round(base, 4),
            # הגאומטריה נשמרת כדי שהרינדור לא יריץ את המודל שוב.
            # היא כ-53MB לחמש שניות, ולכן ``save`` אינו כותב אותה.
            "_geo": geo,
            "model": "nvidia/Audio2Face-3D-v3.0 · network.onnx · CPU"}


def aperture(res) -> tuple:
    """``(פתיחה, עיגול)`` ב-0..1 לפריים, מתוך משקלי ARKit.

    פתיחה = ``jawOpen`` פחות ``mouthClose``. זה לא קוסמטי:
    ``mouthClose`` היא הצורה שסוגרת שפתיים **מעל** לסת פתוחה,
    וזו בדיוק ההגייה של ב/מ/פ בתוך מילה. בלי החיסור, "אמא"
    היה נמדד כפה פתוח.
    """
    import numpy as np
    nm = {n: i for i, n in enumerate(res["names"])}
    w = res["weights"]
    op = w[:, nm["jawOpen"]] - w[:, nm["mouthClose"]]
    rd = np.maximum(w[:, nm["mouthPucker"]], w[:, nm["mouthFunnel"]])
    op = np.clip(op, 0.0, None)
    return op.astype("float32"), np.clip(rd, 0.0, 1.0).astype("float32")


def save(res, path) -> Path:
    """שומר משקלים + תקציר. ``npz`` למספרים, ``json`` לאדם."""
    import numpy as np
    p = Path(path)
    np.savez_compressed(p.with_suffix(".npz"),
                        weights=res["weights"],
                        names=np.asarray(res["names"]))
    meta = {k: v for k, v in res.items()
            if k not in ("weights", "_geo", "lip_gap")}
    nm = {n: i for i, n in enumerate(res["names"])}
    w = res["weights"]
    meta["summary"] = {n: round(float(w[:, i].mean()), 4)
                       for n, i in sorted(nm.items())
                       if float(w[:, i].mean()) > 0.01}
    p.with_suffix(".json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return p.with_suffix(".npz")


if __name__ == "__main__":
    import sys
    wav = sys.argv[1] if len(sys.argv) > 1 else \
        r"D:\claude-bot\out\מרפסת שקיעה - בימוי.wav"
    t0 = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
    t1 = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
    r = run(wav, t0, t1)
    op, rd = aperture(r)
    g = r["lip_gap"]
    print(json.dumps({"frames": r["frames"], "diag": r["geometry_diag"],
                      "jawopen_w_max": round(float(op.max()), 4),
                      "round_mean": round(float(rd.mean()), 4),
                      "lip_gap_min": round(float(g.min()), 4),
                      "lip_gap_max": round(float(g.max()), 4),
                      "lip_gap_std": round(float(g.std()), 4)},
                     ensure_ascii=False, indent=1))
