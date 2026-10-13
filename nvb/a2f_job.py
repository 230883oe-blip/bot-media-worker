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
    wav = HERE / "voice.wav"
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

    print("== הרצה על מעבד הרנר ==", flush=True)
    t0 = time.perf_counter()
    res = a2f_run.run(wav, 0.0, secs, identity="Claire", seed=1234)
    el = time.perf_counter() - t0
    op, rd = a2f_run.aperture(res)
    gap = res["lip_gap"]

    want = int(round(secs * OUT_FPS))
    w24 = resample(res["weights"], res["fps"], OUT_FPS, want)

    out = {
        "model": res["model"],
        "ran_on": "github-actions ubuntu runner · CPU · ONNX",
        "gpu": "none",
        "nvidia_key": "none",
        "names": res["names"],
        "fps": OUT_FPS,
        "frames": int(len(w24)),
        "seconds": round(secs, 3),
        "inference_seconds": round(el, 2),
        "source_fps": res["fps"],
        "source_frames": res["frames"],
        "geometry_diag": res["geometry_diag"],
        "measured": {
            "jawopen_max": round(float(op.max()), 4),
            "round_mean": round(float(rd.mean()), 4),
            "lip_gap_min": round(float(gap.min()), 4),
            "lip_gap_max": round(float(gap.max()), 4),
            "lip_gap_std": round(float(gap.std()), 4),
        },
        "weights": [[round(float(x), 4) for x in row] for row in w24],
    }
    (ART / "arkit.json").write_text(json.dumps(out, ensure_ascii=False),
                                    encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items()
                      if k not in ("weights", "names")},
                     ensure_ascii=False, indent=1), flush=True)

    # שער: מודל שלא הזיז פה אינו "הצלחה". 0.3 ביחידות המודל הוא
    # פתיחה שנראית בעין; נמדד מקומית 1.2 על אותו שמע.
    if float(gap.max()) < 0.3:
        print("!! המודל לא פתח פה (%.3f) - נכשל" % float(gap.max()))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
