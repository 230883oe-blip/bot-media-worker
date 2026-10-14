# -*- coding: utf-8 -*-
r"""שער איכות מחמיר - ארבעה תנאי סף, וכל אחד נמדד מהפריים.

    python qa_gate.py --frames <תיקייה> --log <יומן הרנדר> \
        [--json out/qa_gate.json]

הוא נכשל (קוד יציאה 1) אם אחד מהארבעה נופל, ולכן הוא יכול
לשבת בין שלב המבחן לשלב הרינדור ב-CI ולחסום סבב שלם.

ארבעת התנאים, ומה בדיוק נמדד בכל אחד:

1. **העליון בשני משולשים נפרדים.** נספרים איי פיקסל של צבע
   הבד בחצי העליון של כל דמות. שניים נפרדים = עובר; אי אחד
   רחב = "רצועה" = נכשל.
2. **אפס שיער בתיבת הפנים.** נשלף מיומן הרנדר - שם המספר
   נספר על הגאומטריה עצמה, וזו מדידה חזקה בהרבה מניחוש
   צבע על פיקסלים.
3. **ים וחול בתבליט אמיתי.** סטיית התקן של הבהירות ברצועת
   הים וברצועת החול, וזיהוי קצף. משטח שטוח נותן סטייה
   אפסית - זה בדיוק מה שהיה כאן לפני התיקון.
4. **אין חדירת גאומטריה ואין היעלמות תחת תנועת המצלמה.**
   משווה פריימים: שטח הדמויות (פיקסלים שאינם רקע) אינו
   קופץ בין פריים לפריים, ואינו מתאפס.

הסקריפט אינו מייבא בלנדר. הוא קורא PNG עם Pillow ו-numpy.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")


# ----------------------------------------------------------- עזר

def load(p: Path) -> np.ndarray:
    im = Image.open(p).convert("RGB")
    return np.asarray(im).astype(np.float32) / 255.0


def luma(a: np.ndarray) -> np.ndarray:
    return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722


def islands(mask: np.ndarray, min_px: int = 12):
    """רכיבי קשירות ב-4 שכנים, בלי scipy. מחזיר רשימת (שטח, bbox)."""
    h, w = mask.shape
    lab = np.zeros((h, w), np.int32)
    out = []
    cur = 0
    ys, xs = np.nonzero(mask)
    seen = set()
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if lab[y0, x0]:
            continue
        cur += 1
        stack = [(y0, x0)]
        lab[y0, x0] = cur
        n = 0
        ymin = ymax = y0
        xmin = xmax = x0
        while stack:
            y, x = stack.pop()
            n += 1
            if y < ymin:
                ymin = y
            if y > ymax:
                ymax = y
            if x < xmin:
                xmin = x
            if x > xmax:
                xmax = x
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] \
                        and not lab[ny, nx]:
                    lab[ny, nx] = cur
                    stack.append((ny, nx))
        if n >= min_px:
            out.append((n, (xmin, ymin, xmax, ymax)))
        seen.add(cur)
    out.sort(reverse=True)
    return out


# --------------------------------------------------- 1. עליון בשני חלקים

def cloth_mask(sub: np.ndarray):
    """פיקסלים של בד - **לא לפי צבע מדויק**, וזו הנקודה.

    שני בגדי הים כאן הם כחול כהה וּורוד, ו-AgX מזיז את שניהם:
    נמדד ב-``out/_iso/iso_top.png`` שהכחול הלינארי
    ‎(0.055, 0.215, 0.330)‎ מרונדר כ-‎(0.067, 0.128, 0.181)‎.
    השוואה לצבע קבוע הייתה נכשלת בכל שינוי חשיפה. לכן המדד
    הוא **יחס בין הערוצים**: בד = רווי, ואו כחול-דומיננטי
    (שאין כזה בעור) או אדום-דומיננטי בהפרש גדול מכל גוון עור.
    """
    mx = sub.max(axis=2)
    mn = sub.min(axis=2)
    sat = (mx - mn) / np.maximum(1e-5, mx)
    blue = sub[..., 2] > sub[..., 0] + 0.025
    hot = (sub[..., 0] - sub[..., 1]) > 0.14
    return (sat > 0.38) & (blue | hot) & (mx > 0.02)


def check_top(img: np.ndarray, cloth_rgb, tol=0.16):
    """שני איי בד נפרדים בגובה החזה, בכל אחת משתי הדמויות.

    הדמויות מופרדות לפי חצאי הקאדר. בכל חצי נבדק רק הפס
    האנכי שבו החזה יושב (0.30..0.52 מגובה הקאדר - נמדד
    ב-``measure_frame.py``).
    """
    h, w, _ = img.shape
    y0, y1 = int(h * 0.26), int(h * 0.56)
    c = np.array(cloth_rgb, np.float32)
    res = []
    for half, (x0, x1) in enumerate(((0, w // 2), (w // 2, w))):
        sub = img[y0:y1, x0:x1]
        m = cloth_mask(sub)
        isl = islands(m, min_px=max(8, int(m.size / 1500)))
        # שני האיים הגדולים חייבים להיות דומים בשטח ומופרדים
        # אופקית - שני גביעים, ולא גביע ועוד כתם רעש.
        ok = False
        gap = 0
        if len(isl) >= 2:
            a0, b0 = isl[0], isl[1]
            ratio = b0[0] / max(1, a0[0])
            gap = b0[1][0] - a0[1][2] if b0[1][0] > a0[1][2] \
                else a0[1][0] - b0[1][2]
            ok = ratio >= 0.35 and gap >= 1
        res.append({"half": half, "islands": len(isl),
                    "areas": [i[0] for i in isl[:3]],
                    "gap_px": int(gap), "two_cups": bool(ok)})
    return {"name": "עליון בשני משולשים נפרדים",
            "pass": all(r["two_cups"] for r in res),
            "detail": res}


# ------------------------------------------------ 2. שיער בתיבת הפנים

FACE_RX = re.compile(r"בתיבת הפנים אחרי החסם:\s*(\d+)")


def check_face_hair(logtext: str):
    hits = [int(m) for m in FACE_RX.findall(logtext)]
    return {"name": "אפס גדילי שיער בתיבת הפנים",
            "pass": bool(hits) and all(v == 0 for v in hits),
            "detail": {"measured_per_character": hits,
                       "characters": len(hits)}}


# ------------------------------------------------------- 3. ים וחול

def check_sea_sand(img: np.ndarray, horizon=0.42):
    """תבליט אמיתי = שונות מקומית. שטוח = שונות אפסית."""
    h, w, _ = img.shape
    L = luma(img)
    # רצועת ים: מעט מתחת לאופק. רצועת חול: תחתית הקאדר.
    sea = L[int(h * horizon):int(h * (horizon + 0.12)), :]
    sand = L[int(h * 0.80):, :]

    def local_std(a):
        # סטייה מקומית ב-5×5, ולא גלובלית: גרדיינט אור רך
        # נותן סטייה גלובלית גבוהה גם על משטח שטוח לגמרי.
        k = 5
        pad = np.pad(a, k // 2, mode="edge")
        acc = np.zeros_like(a)
        acc2 = np.zeros_like(a)
        for dy in range(k):
            for dx in range(k):
                v = pad[dy:dy + a.shape[0], dx:dx + a.shape[1]]
                acc += v
                acc2 += v * v
        n = k * k
        var = np.maximum(0.0, acc2 / n - (acc / n) ** 2)
        return float(np.sqrt(var).mean())

    sea_s = local_std(sea)
    sand_s = local_std(sand)
    # קצף: פיקסלים בהירים מאוד ברצועת המים.
    foam = float((sea > (float(sea.mean()) + 2.2 * float(sea.std()))).mean())
    ok = sea_s >= 0.012 and sand_s >= 0.010 and foam >= 0.0015
    return {"name": "ים וחול בתבליט, שבירה וקצף",
            "pass": bool(ok),
            "detail": {"sea_local_std": round(sea_s, 5),
                       "sand_local_std": round(sand_s, 5),
                       "foam_fraction": round(foam, 5),
                       "thresholds": {"sea": 0.012, "sand": 0.010,
                                      "foam": 0.0015}}}


# ------------------------------- 4. חדירה / היעלמות תחת תנועת מצלמה

def subject_mask(img: np.ndarray):
    """פיקסלים שאינם ים/חול/שמיים: עור, בד ושיער.

    הזיהוי הוא לפי **רוויה** ולא לפי גוון: חול וים בפריים הזה
    הם כמעט ניטרליים אחרי AgX, והעור והשיער אינם.
    """
    h, w, _ = img.shape
    box = np.zeros((h, w), bool)
    box[int(h * 0.18):int(h * 0.97), int(w * 0.08):int(w * 0.92)] = True
    mx = img.max(axis=2)
    mn = img.min(axis=2)
    sat = (mx - mn) / np.maximum(1e-5, mx)
    # גוון עור ולא "חם": R>G>B בסדר הזה, רוויה בטווח, ובהירות
    # שאינה שמיים שרופים. "חם ורווי" לבדו תפס את החול בשעת
    # זהב ואת האופק, ואז שטח הדמויות קפץ פי שניים בין פריים
    # לפריים בלי שאף דמות זזה - נמדד.
    skin = ((img[..., 0] > img[..., 1] + 0.012)
            & (img[..., 1] >= img[..., 2])
            & (sat > 0.14) & (sat < 0.62)
            & (mx > 0.10) & (mx < 0.985))
    return skin & box


def check_motion(frames, max_jump=0.45, min_area=0.004):
    """שטח הדמויות יציב לאורך השוט, ולעולם אינו מתאפס.

    הבסיס הוא ה**חציון** ולא הפריים הקודם: בשוט של חמש שניות
    המצלמה עושה דולי, כלומר שינוי הדרגתי לגיטימי, והשוואה
    זוגית בלבד מחמיצה סחיפה איטית בדיוק כפי שהיא מתלוננת על
    רעש דגימה. חציון תופס את שניהם.
    """
    areas = []
    for p in frames:
        m = subject_mask(load(p))
        areas.append(float(m.mean()))
    if not areas:
        return {"name": "אין חדירה או היעלמות תחת תנועת מצלמה",
                "pass": False, "detail": {"frames": 0}}
    med = float(np.median(areas))
    devs = [abs(v - med) / max(1e-6, med) for v in areas]
    worst = max(devs)
    ok = min(areas) >= min_area and worst <= max_jump and med >= min_area
    return {"name": "אין חדירה או היעלמות תחת תנועת מצלמה",
            "pass": bool(ok),
            "detail": {"frames": len(areas),
                       "subject_area": [round(a, 5) for a in areas],
                       "median_area": round(med, 5),
                       "worst_dev_from_median": round(worst, 4),
                       "min_area": round(min(areas), 5),
                       "limits": {"max_dev": max_jump,
                                  "min_area": min_area}}}


# ----------------------------------------------------------- ראשי

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", required=True,
                    help="תיקייה עם f####.png")
    ap.add_argument("--log", default="",
                    help="יומן הרנדר (לספירת שיער בתיבת הפנים)")
    ap.add_argument("--json", default="")
    ap.add_argument("--cloth", default="0.80,0.24,0.33",
                    help="צבע הבד ב-RGB מנורמל, אחרי AgX")
    ap.add_argument("--skip", default="",
                    help="שמות תנאים לדלג (מופרדים בפסיק): top,hair,sea,motion")
    a = ap.parse_args()

    fdir = Path(a.frames)
    frames = sorted(fdir.glob("f*.png"))
    if not frames:
        print("שער איכות: לא נמצאו פריימים ב-%s" % fdir)
        return 2
    print("שער איכות: %d פריימים מ-%s" % (len(frames), fdir))
    logtext = ""
    if a.log and Path(a.log).exists():
        logtext = Path(a.log).read_text(encoding="utf-8", errors="replace")

    cloth = tuple(float(x) for x in a.cloth.split(","))
    skip = {s.strip() for s in a.skip.split(",") if s.strip()}
    first = load(frames[0])

    checks = []
    if "top" not in skip:
        checks.append(check_top(first, cloth))
    if "hair" not in skip:
        checks.append(check_face_hair(logtext))
    if "sea" not in skip:
        checks.append(check_sea_sand(first))
    if "motion" not in skip:
        checks.append(check_motion(frames))

    ok = all(c["pass"] for c in checks)
    for c in checks:
        print("  %s %s" % ("✔" if c["pass"] else "✘", c["name"]))
        print("      %s" % json.dumps(c["detail"], ensure_ascii=False))
    out = {"pass": ok, "frames": [p.name for p in frames],
           "checks": checks}
    if a.json:
        pj = Path(a.json)
        pj.parent.mkdir(parents=True, exist_ok=True)
        pj.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    print("QA_GATE: %s" % ("עבר" if ok else "נכשל"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
