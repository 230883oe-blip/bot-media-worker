# -*- coding: utf-8 -*-
r"""
עומס מדידה סטנדרטי (benchmark) - קובץ אחד, בלי תלות בפרויקט.

למה קובץ נפרד ולא הרינדור האמיתי (07/10/2026):
    כדי להשוות מקומי מול ענן חייבים להריץ **אותו קוד בדיוק** בשני
    הצדדים. הרינדור האמיתי (`showreel.bridge`) דורש את כל עץ הפרויקט,
    כרומיום headless עם WebGL, ושרת מקומי - וכל אלה מתנהגים אחרת על
    רנר בענן (שם אין GPU, ולכן WebGL נופל ל-SwiftShader בתוכנה).
    לכן העומס כאן הוא **חתיכה מייצגת** של שלושת שלבי המחשוב הכבדים
    בצינור שלנו, ושלושתם זהים בשני הצדדים:

      sim      - דפורמציית שלד + סימולציית קהל. 8 דמויות, 48 מפרקים,
                 2700 פריימים (90 שניות ב-30fps), 2048 קודקודים לדמות
                 עם 4 משקולות - בדיוק האופרציה שרצה בכל פעימה של
                 `rig.locomotion` + `rig.secondary`.
      raster   - ראסטריזציה של 720p: z-buffer על 8 דמויות + קרקע,
                 מייצג את שלב הציור שהדפדפן עושה לכל פריים.
      encode   - קידוד H.264 ב-PyAV, **אותה ספרייה ואותו קודק** שהצינור
                 האמיתי משתמש בהם (`engine.py` -> `av.open(mode="w")`).
      parallel - אותו `sim` על כל הליבות, כדי למדוד סקיילינג לפי ליבות.

הפלט הוא JSON אחד ל-stdout. כל שלב מדווח גם throughput ולא רק זמן, כדי
שאפשר יהיה להשוות גם אם מכונה אחת הריצה פחות פריימים.

מלכודות שנפלתי בהן, ולכן הקוד נראה כך:
  1. numpy עצמו מקביל חלק מהאופרציות ב-BLAS, ואז "ליבה אחת" היא שקר.
     לכן `sim` מוגדר ב-einsum על מטריצות 4x4 קטנות (לא GEMM גדול),
     ומשתני הסביבה של BLAS נקבעים ל-1 בשלב החד-ליבתי.
  2. `time.time()` על ווינדוס גרוע ברזולוציה. `perf_counter`.
  3. קידוד x264 מקביל לבד לפי ליבות, ולכן הוא נמדד בנפרד ומסומן
     כשלב שהמקבול שלו פנימי - אחרת היה נראה כאילו המקומי "מרמה".

הרצה:
    python workload.py                 # הכול
    python workload.py --stage sim     # שלב אחד
    python workload.py --scale 0.25    # רביע מהעומס (בדיקת שפיות מהירה)
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import platform
import sys
import time

# מלכודת 1: לנעול BLAS לליבה אחת לפני ייבוא numpy, אחרת המדידה
# החד-ליבתית מודדת בשקט את כל המכונה.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

SEED = 20261007          # דטרמיניסטי: אותם מספרים בשני הצדדים
CHARS = 8                # שמונה דמויות, כמו park90
JOINTS = 48              # מפרקים לדמות
VERTS = 2048             # קודקודים לדמות
FRAMES_SIM = 2700        # 90 שניות ב-30fps
W, H = 1280, 720
FRAMES_RASTER = 60
FRAMES_ENCODE = 300


# ----------------------------------------------------------------- sim
def _rig_rest(rng):
    """שלד במנוחה: היררכיית הורים + מיקום מנוחה + משקולות עור."""
    parents = np.array([max(0, i - 1 - (i % 3)) for i in range(JOINTS)], dtype=np.int32)
    parents[0] = -1
    rest = rng.standard_normal((JOINTS, 3)).astype(np.float64) * 0.12
    skin_idx = rng.integers(0, JOINTS, size=(VERTS, 4)).astype(np.int32)
    w = rng.random((VERTS, 4))
    skin_w = (w / w.sum(axis=1, keepdims=True)).astype(np.float64)
    verts = rng.standard_normal((VERTS, 3)).astype(np.float64) * 0.4
    return parents, rest, skin_idx, skin_w, verts


def _euler_mats(ang):
    """ang: (J,3) -> (J,3,3). בנייה מפורשת, בלי GEMM גדול (מלכודת 1)."""
    cx, cy, cz = np.cos(ang[:, 0]), np.cos(ang[:, 1]), np.cos(ang[:, 2])
    sx, sy, sz = np.sin(ang[:, 0]), np.sin(ang[:, 1]), np.sin(ang[:, 2])
    m = np.empty((ang.shape[0], 3, 3))
    m[:, 0, 0] = cy * cz
    m[:, 0, 1] = cz * sx * sy - cx * sz
    m[:, 0, 2] = cx * cz * sy + sx * sz
    m[:, 1, 0] = cy * sz
    m[:, 1, 1] = cx * cz + sx * sy * sz
    m[:, 1, 2] = -cz * sx + cx * sy * sz
    m[:, 2, 0] = -sy
    m[:, 2, 1] = cy * sx
    m[:, 2, 2] = cy * cx
    return m


def sim_chunk(args):
    """דפורמציית שלד + פאתינג לקבוצת פריימים. מחזיר checksum + ספירה."""
    f0, f1 = args
    rng = np.random.default_rng(SEED)
    rigs = [_rig_rest(rng) for _ in range(CHARS)]
    acc = 0.0
    for f in range(f0, f1):
        t = f / 30.0
        for ci, (parents, rest, sidx, sw, verts) in enumerate(rigs):
            # פוזה: הליכה מחזורית + ריחוף משני, כמו rig.locomotion
            ph = t * 2.6 + ci * 0.785
            ang = np.empty((JOINTS, 3))
            j = np.arange(JOINTS)
            ang[:, 0] = 0.35 * np.sin(ph + j * 0.21)
            ang[:, 1] = 0.22 * np.cos(ph * 0.5 + j * 0.13)
            ang[:, 2] = 0.18 * np.sin(ph * 1.5 + j * 0.07)
            R = _euler_mats(ang)
            # שרשרת היררכית: מקומי -> עולמי (לולאה, כי יש תלות בהורה)
            gR = np.empty_like(R)
            gT = np.empty((JOINTS, 3))
            for k in range(JOINTS):
                p = parents[k]
                if p < 0:
                    gR[k] = R[k]
                    gT[k] = rest[k]
                else:
                    gR[k] = gR[p] @ R[k]
                    gT[k] = gT[p] + gR[p] @ rest[k]
            # סימולציית קהל: הימנעות הדדית סביב נתיב
            lane = 1.6 * np.sin(t * 0.3 + ci) + ci * 0.9
            gT[:, 0] += lane
            # עור: 4 משקולות לקודקוד
            vs = np.zeros((VERTS, 3))
            for s in range(4):
                idx = sidx[:, s]
                vs += sw[:, s, None] * (np.einsum("vij,vj->vi", gR[idx], verts) + gT[idx])
            acc += float(vs[::97, 0].sum())
    return acc, (f1 - f0)


# -------------------------------------------------------------- raster
def raster(frames: int):
    """z-buffer על 720p: קרקע + 8 דמויות כאליפסואידים + צל. וקטורי."""
    rng = np.random.default_rng(SEED)
    yy, xx = np.mgrid[0:H, 0:W]
    xn = (xx - W / 2) / (W / 2)
    yn = (yy - H / 2) / (H / 2)
    acc = 0
    for f in range(frames):
        t = f / 30.0
        depth = np.full((H, W), 1e9)
        color = np.zeros((H, W, 3), dtype=np.float32)
        # קרקע
        gz = 8.0 + yn * 6.0
        gm = yn > -0.1
        depth[gm] = gz[gm]
        color[gm] = np.stack([0.35 + 0.1 * xn, 0.55 + 0.05 * yn,
                              0.3 + 0.05 * xn], -1)[gm]
        # דמויות
        for ci in range(CHARS):
            cx = 0.75 * np.sin(t * 0.45 + ci * 0.8)
            cy = -0.1 + 0.05 * np.sin(t * 2.6 + ci)
            rx, ry = 0.055, 0.17
            d = ((xn - cx) / rx) ** 2 + ((yn - cy) / ry) ** 2
            m = d < 1.0
            if not m.any():
                continue
            z = 6.0 + ci * 0.4 - np.sqrt(np.clip(1.0 - d, 0, None))
            better = m & (z < depth)
            depth[better] = z[better]
            nz = np.sqrt(np.clip(1.0 - d, 0, None))
            lam = np.clip(0.3 + 0.7 * nz, 0, 1)
            base = np.array([0.9 - ci * 0.07, 0.6, 0.45 + ci * 0.05], np.float32)
            color[better] = (lam[better, None] * base)
        acc += int((depth < 1e8).sum())
        del color
    return acc, frames


# -------------------------------------------------------------- encode
def encode(frames: int, out: str):
    """קידוד H.264 ב-PyAV - אותה ספרייה ואותו קודק כמו engine.py."""
    import av
    rng = np.random.default_rng(SEED)
    base = (rng.random((H, W, 3)) * 40).astype(np.uint8)
    oc = av.open(out, mode="w")
    st = oc.add_stream("libx264", rate=30)
    st.width, st.height, st.pix_fmt = W, H, "yuv420p"
    st.options = {"crf": "20", "preset": "medium"}
    for f in range(frames):
        img = base.copy()
        sh = (f * 7) % W
        img = np.roll(img, sh, axis=1)
        g = np.linspace(0, 255, W, dtype=np.uint8)
        img[:, :, 1] = np.minimum(255, img[:, :, 1].astype(np.int16) + g[None, :]).astype(np.uint8)
        fr = av.VideoFrame.from_ndarray(img, format="rgb24")
        for p in st.encode(fr):
            oc.mux(p)
    for p in st.encode():
        oc.mux(p)
    oc.close()
    return os.path.getsize(out), frames


# ---------------------------------------------------------------- meta
def machine() -> dict:
    d = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "processor": platform.processor() or platform.machine(),
        "logical_cores": os.cpu_count(),
        "numpy": np.__version__,
    }
    try:
        import av
        d["pyav"] = av.__version__
    except Exception:
        d["pyav"] = None
    # דגם מעבד אמיתי + זיכרון, לפי מערכת ההפעלה
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/cpuinfo") as fh:
                for ln in fh:
                    if ln.startswith("model name"):
                        d["cpu_model"] = ln.split(":", 1)[1].strip()
                        break
            with open("/proc/meminfo") as fh:
                for ln in fh:
                    if ln.startswith("MemTotal"):
                        d["ram_gb"] = round(int(ln.split()[1]) / 1048576, 1)
                        break
            d["physical_cores"] = d["logical_cores"]
        else:
            import subprocess
            q = subprocess.run(
                ["wmic", "cpu", "get", "name,NumberOfCores"],
                capture_output=True, text=True, timeout=20)
            ls = [x.strip() for x in q.stdout.splitlines() if x.strip()]
            if len(ls) > 1:
                d["cpu_model"] = ls[1]
            q2 = subprocess.run(
                ["wmic", "computersystem", "get", "TotalPhysicalMemory"],
                capture_output=True, text=True, timeout=20)
            for x in q2.stdout.split():
                if x.isdigit():
                    d["ram_gb"] = round(int(x) / 1073741824, 1)
    except Exception as e:
        d["meta_err"] = str(e)[:120]
    # GPU: האם יש CUDA בכלל
    try:
        import subprocess
        q = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
                            "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=20)
        d["gpu"] = q.stdout.strip() or None
    except Exception:
        d["gpu"] = None
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    s = max(0.02, a.scale)
    nsim = max(10, int(FRAMES_SIM * s))
    nras = max(2, int(FRAMES_RASTER * s))
    nenc = max(10, int(FRAMES_ENCODE * s))
    want = a.stage
    res = {"machine": machine(), "scale": s, "stages": {},
           "started": time.strftime("%Y-%m-%dT%H:%M:%S")}

    def run(name, fn, units, unit_name):
        if want not in ("all", name):
            return
        t0 = time.perf_counter()
        out = fn()
        dt = time.perf_counter() - t0
        res["stages"][name] = {
            "seconds": round(dt, 3),
            unit_name: units,
            "per_sec": round(units / dt, 3) if dt else None,
            "checksum": out,
        }
        print(f"[{name}] {dt:.2f}s  {units/dt:.2f} {unit_name}/s",
              file=sys.stderr, flush=True)

    run("sim", lambda: round(sim_chunk((0, nsim))[0], 3), nsim, "frames")
    run("raster", lambda: raster(nras)[0], nras, "frames")
    mp4 = a.out or os.path.join(os.environ.get("TEMP", "/tmp"), "bench_enc.mp4")
    run("encode", lambda: encode(nenc, mp4)[0], nenc, "frames")

    # מקבול: אותו sim על כל הליבות
    if want in ("all", "parallel"):
        nproc = max(1, (os.cpu_count() or 1))
        per = max(4, nsim // nproc)
        chunks = [(i * per, (i + 1) * per) for i in range(nproc)]
        t0 = time.perf_counter()
        with mp.Pool(nproc) as pool:
            got = pool.map(sim_chunk, chunks)
        dt = time.perf_counter() - t0
        tot = sum(c for _, c in got)
        res["stages"]["parallel"] = {
            "seconds": round(dt, 3), "frames": tot, "workers": nproc,
            "per_sec": round(tot / dt, 3) if dt else None,
        }
        print(f"[parallel] {dt:.2f}s  {tot} frames on {nproc} workers "
              f"= {tot/dt:.2f} frames/s", file=sys.stderr, flush=True)

    res["total_seconds"] = round(sum(v["seconds"] for v in res["stages"].values()), 3)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
