# -*- coding: utf-8 -*-
"""עבודת ענן 1/3: NVIDIA Audio2Face-3D על **מעבד של רנר מרוחק**.

למה הקובץ הזה קיים
-------------------
ב-13/10 דווח כאן "אין כרטיס NVIDIA ולכן אין A2F". זו טענה
שגויה, והיא תוקנה כבר באותו יום בתוך ``a2f_run.py``: NVIDIA
פרסמה את ``nvidia/Audio2Face-3D-v3.0`` ב-HuggingFace כ-**ONNX
פתוח** (``gated=false``). ONNX רץ על מעבד. היעדר כרטיס חוסם את
ה-NIM הרשמי ואת TensorRT - **לא את המודל**.

מה שחסר היה אז, ומה שנסגר כאן: ההרצה ההיא הייתה **מקומית**.
המודול הזה מריץ את אותו מודל בדיוק על רנר של GitHub Actions,
כלומר בענן, בלי כרטיס ובלי מפתח NVIDIA.

מה הוא מוציא
-------------
``artifacts/arkit.json`` - 52 משקלי ARKit לפריים, בקצב 30fps,
ולצידם המדידה שמוכיחה שהמודל אכן הזיז פה (``lip_gap``). הקובץ
הזה הוא הקלט של עבודת הבלנדר, ולכן הוא העבודה **הראשונה**
בשרשרת ולא קישוט.

מלכודות שנסגרו כאן מראש
------------------------
* **אין ``huggingface_hub`` ברנר.** ההורדה היא ``resolve/main``
  ישר, עם ניסיון חוזר - 725MB על רשת של רנר נופלים לפעמים
  באמצע, וזה נראה כמו מודל פגום.
* **הקצב של המודל הוא 30fps, הסרטון 24fps.** הדגימה מחדש
  נעשית כאן ולא בבלנדר, כדי שיהיה קובץ אחד שמצהיר על הקצב.
* **אין כתיבה אל שום מקום פרט ל-``artifacts/``.**
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
A2F = HERE / "a2f"
ART = Path("artifacts")

HF = "https://huggingface.co/nvidia/Audio2Face-3D-v3.0/resolve/main/"

#: רק מה שצריך לזהות Claire. 725MB + 15MB ולא 2.2GB של שלוש הזהויות.
NEED = ("network.onnx", "network_info.json", "bs_skin_Claire.npz",
        "bs_skin_config_Claire.json", "model_config_Claire.json")

#: קצב היעד של הסרטון. המודל מחזיר 30.
OUT_FPS = 24.0


def grab(name: str, tries: int = 4) -> Path:
    dst = A2F / name
    if dst.exists() and dst.stat().st_size > 0:
        print("  = %s (קיים)" % name, flush=True)
        return dst
    for i in range(tries):
        try:
            t0 = time.perf_counter()
            req = urllib.request.Request(HF + name,
                                         headers={"User-Agent": "anim-nvb"})
            with urllib.request.urlopen(req, timeout=120) as r, \
                    open(dst, "wb") as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
            print("  + %s · %.1fMB · %.1fs" % (
                name, dst.stat().st_size / 1e6, time.perf_counter() - t0),
                flush=True)
            return dst
        except Exception as e:                               # noqa: BLE001
            print("  ! %s ניסיון %d: %s" % (name, i + 1, e), flush=True)
            if dst.exists():
                dst.unlink()
            if i == tries - 1:
                raise
            time.sleep(5)
    return dst


def resample(w, src_fps: float, dst_fps: float, want: int):
    """דגימה מחדש לינארית של המשקלים. 30fps -> 24fps."""
    import numpy as np
    n = len(w)
    t = np.arange(want, dtype="float32") * (src_fps / dst_fps)
    t = np.clip(t, 0, n - 1)
    i0 = np.floor(t).astype("int32")
    i1 = np.minimum(i0 + 1, n - 1)
    a = (t - i0).reshape(-1, 1)
    return (w[i0] * (1.0 - a) + w[i1] * a).astype("float32")


def main() -> int:
    import numpy as np

    ART.mkdir(parents=True, exist_ok=True)
    A2F.mkdir(parents=True, exist_ok=True)
    secs = float(os.environ.get("SECONDS", "5.0"))

    print("== הורדת המודל של NVIDIA מ-HuggingFace ==", flush=True)
    for n in NEED:
        grab(n)

    sys.path.insert(0, str(HERE))
    import a2f_run                                            # noqa: E402

    # המודול מחפש את המודל ב-``HERE/a2f``, וזה בדיוק המקום שבו
    # הוא יושב כאן. אין צורך לשנות אותו - וזה העיקר: **אותו קוד**
    # שרץ מקומית רץ עכשיו בענן.
    a2f_run.A2F = A2F

    # **הבחירה נעשית בענן ולא בבית.** הריצה הראשונה (13/10 17:12)
    # נפלה כי קטע השמע שנבחר מראש היה שקט ופתח פה ב-0.20 בלבד.
    # במקום לכייל את הסף עד שיעבור - שלושה מועמדים רצים כאן
    # והחזק נבחר. ההרצה היא 6 שניות; ההורדה היא שקרה פעם אחת.
    cands = sorted(HERE.glob("voice*.wav"))
    if not cands:
        raise SystemExit("אין קובצי voice*.wav")
    print("== הרצה על מעבד הרנר · %d מועמדים ==" % len(cands), flush=True)

    best, tried = None, []
    for wav in cands:
        t0 = time.perf_counter()
        res = a2f_run.run(wav, 0.0, secs, identity="Claire", seed=1234)
        el = time.perf_counter() - t0
        gap = res["lip_gap"]
        score = float(np.percentile(gap, 97))
        tried.append({"wav": wav.name, "lip_gap_p97": round(score, 4),
                      "lip_gap_max": round(float(gap.max()), 4),
                      "inference_seconds": round(el, 2)})
        print("  %s: p97=%.4f max=%.4f · %.1fs"
              % (wav.name, score, float(gap.max()), el), flush=True)
        if best is None or score > best[0]:
            best = (score, res, wav, el)

    score, res, wav, el = best
    op, rd = a2f_run.aperture(res)
    gap = res["lip_gap"]

    want = int(round(secs * OUT_FPS))
    w24 = resample(res["weights"], res["fps"], OUT_FPS, want)

    # **פתיחת הלסת אינה משקל ARKit, והיא לא יכולה להיות.**
    # ``a2f_run`` מתעד את זה: בלוק ה-``jaw`` של A2F נפרד ממשקלי
    # העור, ולכן ``jawOpen`` כמשקל מוחזר קטן (0.25) גם כשהפה
    # פעור. הריצה הראשונה כאן הייתה מזיזה לסת ב-4 מעלות בלבד.
    # המדד הפיזי הוא ``lip_gap`` - מרווח השפתיים על הרשת
    # המשוחזרת - והוא מנורמל כאן ל-0..1 מול האחוזון ה-97,
    # כלומר פתיחה מלאה בהגייה הרחבה ביותר של הקטע.
    jaw = np.clip(gap / max(score, 1e-6), 0.0, 1.0).astype("float32")
    jaw24 = resample(jaw.reshape(-1, 1), res["fps"], OUT_FPS,
                     want).reshape(-1)

    out = {
        "model": res["model"],
        "ran_on": "github-actions ubuntu runner · CPU · ONNX",
        "gpu": "none",
        "nvidia_key": "none",
        "voice": wav.name,
        "candidates": tried,
        "names": res["names"],
        "fps": OUT_FPS,
        "frames": int(len(w24)),
        "seconds": round(secs, 3),
        "inference_seconds": round(el, 2),
        "source_fps": res["fps"],
        "source_frames": res["frames"],
        "geometry_diag": res["geometry_diag"],
        "measured": {
            "jawopen_weight_max": round(float(op.max()), 4),
            "round_mean": round(float(rd.mean()), 4),
            "lip_gap_min": round(float(gap.min()), 4),
            "lip_gap_max": round(float(gap.max()), 4),
            "lip_gap_p97": round(score, 4),
            "lip_gap_std": round(float(gap.std()), 4),
            "jaw_open_mean": round(float(jaw24.mean()), 4),
            "jaw_frames_open": int((jaw24 > 0.25).sum()),
        },
        "jaw_open": [round(float(x), 4) for x in jaw24],
        "weights": [[round(float(x), 4) for x in row] for row in w24],
    }
    (ART / "arkit.json").write_text(json.dumps(out, ensure_ascii=False),
                                    encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items()
                      if k not in ("weights", "names", "jaw_open")},
                     ensure_ascii=False, indent=1), flush=True)

    # השער בודק **תנועה**, לא עוצמה. מודל שהחזיר פה קפוא הוא כשל;
    # קטע שקט הוא בחירת קלט ולא תקלה. לכן הסף הוא על הסטייה
    # בזמן (0.02 ביחידות המודל) ועל מספר הפריימים שבהם הפה פתוח.
    if float(gap.std()) < 0.02 or int((jaw24 > 0.25).sum()) < 8:
        print("!! הפה אינו זז (std=%.4f · פריימים פתוחים=%d) - נכשל"
              % (float(gap.std()), int((jaw24 > 0.25).sum())))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
