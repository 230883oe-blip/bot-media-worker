# -*- coding: utf-8 -*-
r"""בניית ערכת מפות עור **פוטו-ריאליסטיות** ממקור פתוח לגמרי.

למה המודול הזה קיים
--------------------
שער האיכות פסל שלוש פעמים ברצף על אותו שורש אחד: חומר העור היה
**צבע אחיד פרוצדורלי**. ``quality_gate`` מודד את זה בשלושה מקומות
בלתי תלויים, וכל שלושתם נגזרים מאותה עובדה:

* ``asset.images == 0`` - glTF שומר **רק** טקסטורות תמונה. Noise
  ו-Voronoi של Blender אינם עוברים, ולכן הנכס מצהיר "חומר שטוח".
* ``chroma_std`` 8.7 מול 25.2 ברפרנס - וריאציית גוון של רמפת צבע
  היא רציפה וחלקה, ולעור אמיתי יש פסיפס מקומי של אדמומיות.
* ``sharp_detail`` 0.848 מהרפרנס - נקבוביות Voronoi היא תבנית
  מחזורית, ובמסננים היא נקראת כרעש ולא כפירוט.

המקור, ולמה **אין** צורך לעקוף שום הרשמה
-----------------------------------------
נמדד 14/10 מול השרת: ב-``api.polyhaven.com`` (868 טקסטורות) וב-
``ambientcg.com/api/v2`` אין **אף** מפת עור אנושי - החיפוש מחזיר
Leather בלבד. ``texturecan.com`` מחזיר 406 מ-Mod_Security. כלומר
המאגרים הגדולים אינם המקור, וזה לא עניין של הרשמה.

מה **כן** פתוח, בלי חשבון ובלי מפתח: ויקישיתוף. ה-API הציבורי
(``action=query&prop=imageinfo``) מחזיר את הרישיון בשדה מובנה,
ושלוש תמונות מאקרו של עור אנושי יושבות שם ב-**CC0** - כלומר
ויתור מלא על זכויות, בלי ייחוס חובה ובלי תנאים. אומת בשדה
``extmetadata.LicenseShortName`` ולא הונח.

לכן לא נעשה כאן שום עקיפה: נבחר מקור שפתוח מרצון. תמונה
ב-CC BY-SA (``Menschliche Haut``, ``Palm hand``) **לא** נכנסת -
רישיון שמחייב שיתוף-זהה על תוצר מסחרי אינו "פתוח לגמרי".

העיבוד, והנימוק לכל שלב
-----------------------
להדביק צילום כף יד על גוף שלם אינו פתרון - הטון של הדמות נקבע
בצינור (``tone``), ומפה עם תאורה צרובה הייתה כופה עליו צל זר.
לכן המפה עוברת **הפרדה של תאורה ממרקם** במרחב Lab:

1. ``L`` מאבד את הרכיב הגלובלי (``L - blur(L)``) ונשאר רק
   המיקרו - נקבוביות, קמטיקים, שערות. זה מה שמזיז ``sharp_detail``
   והוא פירוט **אמיתי** ולא תבנית מחזורית.
2. ``a``/``b`` שומרים את **השארית המקומית** ומוגברים. זה הפסיפס
   הכרומטי שמזיז ``chroma_std``; הגוון הבסיסי נשאר של הדמות.
3. הופכים ל-tileable בשילוב מראה מוזן, כי הגוף מקבל UV
   מ-Smart Project ושם אין ערובה לרציפות בין איים.

היציאה: ``albedo`` (sRGB), ``roughness`` (מונו) ו-``normal``
(מרחב משיק) - שלוש מפות PBR שעוברות ל-glTF כתמונות, ולכן מה
שהנכס מצהיר הוא בדיוק מה שנרנדר.

הרצה::

    python skinmaps.py --out <תיקייה> --size 2048
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

UA = "anim-studio/1.0 (Blender beach shot; CC0 texture fetch)"

# שלושת המקורות, כולם CC0 מאומת בשדה המובנה של ויקישיתוף.
# הסדר הוא סדר העדפה: רזולוציה גבוהה ומשטח עור רצוף.
SOURCES = [
    {
        "name": "Human_skin_close-up.jpg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/"
               "5/5f/Human_skin_close-up.jpg",
        "page": "https://commons.wikimedia.org/wiki/File:Human_skin_close-up.jpg",
        "license": "CC0",
        "px": (5312, 2988),
    },
    {
        "name": "Image_skin_texture.jpg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/"
               "7/75/Image_skin_texture.jpg",
        "page": "https://commons.wikimedia.org/wiki/File:Image_skin_texture.jpg",
        "license": "CC0",
        "px": (3693, 2462),
    },
    {
        "name": "Hand_skin_closeup.jpg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/"
               "6/6b/Hand_skin_closeup.jpg",
        "page": "https://commons.wikimedia.org/wiki/File:Hand_skin_closeup.jpg",
        "license": "CC0",
        "px": (1920, 1080),
    },
]


def log(*a):
    print("[skinmaps]", *a, flush=True)


# ------------------------------------------------------------------ הורדה

def fetch(src: dict, cache: Path, timeout: float = 90.0) -> Path | None:
    """מוריד תמונה אחת למטמון. מחזיר ``None`` בכשל, בלי לזרוק.

    כשל הורדה **אינו** עוצר את הצינור: ``skin_material`` נופל חזרה
    לשכבות הפרוצדורליות ורושם אזהרה. נפילה כאן הייתה הופכת תקלת
    רשת רגעית ברנר לכשל הפקה שלם.
    """
    cache.mkdir(parents=True, exist_ok=True)
    dst = cache / src["name"]
    if dst.exists() and dst.stat().st_size > 50_000:
        log("מהמטמון:", src["name"])
        return dst
    req = urllib.request.Request(src["url"], headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            blob = r.read()
    except Exception as e:                                   # noqa: BLE001
        log("הורדה נכשלה (%s): %s" % (src["name"], e))
        return None
    if len(blob) < 50_000:
        log("קובץ קצר מדי (%d בייט) - נדחה" % len(blob))
        return None
    dst.write_bytes(blob)
    log("הורד %s (%.1fMB)" % (src["name"], len(blob) / 1e6))
    return dst


# ------------------------------------------------------------------ עזר

def _blur(a: np.ndarray, radius: int) -> np.ndarray:
    """טשטוש קופסה מופרד, דרך סכום מצטבר. O(n) ובלי scipy.

    ``scipy`` אינו בתלויות של הרנר, ו-``PIL.GaussianBlur`` עובד על
    8 ביט - כלומר היה חותך את השארית העדינה שכל העיבוד הזה נשען
    עליה. סכום מצטבר על float32 שומר את הדיוק.
    """
    if radius < 1:
        return a.astype(np.float32)
    out = a.astype(np.float32)
    for axis in (0, 1):
        n = out.shape[axis]
        r = min(radius, max(1, n // 2 - 1))
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        p = np.pad(out, pad, mode="reflect")
        c = np.cumsum(p, axis=axis, dtype=np.float32)
        zero = np.zeros_like(np.take(c, [0], axis=axis))
        c = np.concatenate([zero, c], axis=axis)
        hi = np.take(c, np.arange(2 * r + 1, n + 2 * r + 1), axis=axis)
        lo = np.take(c, np.arange(0, n), axis=axis)
        out = (hi - lo) / float(2 * r + 1)
    return out


def _srgb_to_lin(a: np.ndarray) -> np.ndarray:
    a = np.clip(a, 0.0, 1.0)
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def _lin_to_srgb(a: np.ndarray) -> np.ndarray:
    a = np.clip(a, 0.0, 1.0)
    return np.where(a <= 0.0031308, a * 12.92,
                    1.055 * np.power(a, 1.0 / 2.4) - 0.055)


_M_RGB2XYZ = np.array([[0.4124564, 0.3575761, 0.1804375],
                       [0.2126729, 0.7151522, 0.0721750],
                       [0.0193339, 0.1191920, 0.9503041]], dtype=np.float32)
_M_XYZ2RGB = np.linalg.inv(_M_RGB2XYZ).astype(np.float32)
_WP = np.array([0.95047, 1.0, 1.08883], dtype=np.float32)


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    xyz = _srgb_to_lin(rgb) @ _M_RGB2XYZ.T / _WP
    e, k = 216.0 / 24389.0, 24389.0 / 27.0
    f = np.where(xyz > e, np.cbrt(np.maximum(xyz, 1e-9)), (k * xyz + 16.0) / 116.0)
    return np.stack([116.0 * f[..., 1] - 16.0,
                     500.0 * (f[..., 0] - f[..., 1]),
                     200.0 * (f[..., 1] - f[..., 2])], axis=-1)


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    fy = (lab[..., 0] + 16.0) / 116.0
    fx = fy + lab[..., 1] / 500.0
    fz = fy - lab[..., 2] / 200.0
    e, k = 216.0 / 24389.0, 24389.0 / 27.0
    f = np.stack([fx, fy, fz], axis=-1)
    xyz = np.where(f ** 3 > e, f ** 3, (116.0 * f - 16.0) / k) * _WP
    return np.clip(_lin_to_srgb(xyz @ _M_XYZ2RGB.T), 0.0, 1.0)


def make_tileable(img: np.ndarray, frac: float = 0.14) -> np.ndarray:
    """הופך לרציף בקצוות בשילוב מראה מוזן.

    הדרך המקובלת (offset ב-50% ואז רטוש) דורשת ציור ידני. שילוב
    מראה אינו מוסיף תפר **בכלל**, במחיר סימטריה קלה - ועל מיקרו
    של עור, סימטריה בקצה של 14% אינה נראית, בעוד תפר חוזר נראה
    בכל פריים.
    """
    h, w = img.shape[:2]
    bw = max(2, int(round(w * frac)))
    bh = max(2, int(round(h * frac)))
    out = img.astype(np.float32).copy()
    ramp = np.linspace(0.0, 1.0, bw, dtype=np.float32)
    ramp = ramp * ramp * (3.0 - 2.0 * ramp)                  # smoothstep
    wx = ramp.reshape(1, bw, *([1] * (img.ndim - 2)))
    left = out[:, :bw]
    right_mirror = out[:, w - bw:][:, ::-1]
    out[:, :bw] = left * wx + right_mirror * (1.0 - wx)
    out[:, w - bw:] = out[:, :bw][:, ::-1]
    rampy = np.linspace(0.0, 1.0, bh, dtype=np.float32)
    rampy = rampy * rampy * (3.0 - 2.0 * rampy)
    wy = rampy.reshape(bh, 1, *([1] * (img.ndim - 2)))
    top = out[:bh]
    bottom_mirror = out[h - bh:][::-1]
    out[:bh] = top * wy + bottom_mirror * (1.0 - wy)
    out[h - bh:] = out[:bh][::-1]
    return out


def seam_error(img: np.ndarray) -> float:
    """הפרש ממוצע בין עמודה ראשונה לאחרונה (ושורה). 0 = רציף."""
    a = img.astype(np.float32)
    dx = float(np.abs(a[:, 0] - a[:, -1]).mean())
    dy = float(np.abs(a[0, :] - a[-1, :]).mean())
    return (dx + dy) / 2.0


# ------------------------------------------------------------------ בנייה

def build_maps(path: Path, size: int, chroma_gain: float = 2.6,
               micro_gain: float = 1.35) -> dict[str, np.ndarray]:
    """מצילום אחד -> albedo / roughness / normal, כולם tileable."""
    im = Image.open(path).convert("RGB")
    w, h = im.size
    side = min(w, h)
    # חיתוך ריבוע מרכזי: שוליים של צילום מאקרו נוטים להיות
    # מחוץ לפוקוס, וחוסר חדות שם היה מתפרש כ"עור חלק".
    im = im.crop(((w - side) // 2, (h - side) // 2,
                  (w - side) // 2 + side, (h - side) // 2 + side))
    im = im.resize((size, size), Image.LANCZOS)
    rgb = np.asarray(im, dtype=np.float32) / 255.0

    lab = rgb_to_lab(rgb)
    L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]
    r_big = max(4, size // 12)

    # --- 1. הפרדת תאורה ממרקם. ``L`` מאבד את הרכיב הגלובלי.
    L_micro = (L - _blur(L, r_big)) * micro_gain
    # --- 2. שארית כרומטית מקומית, מוגברת. זה ``chroma_std``.
    A_res = (A - _blur(A, r_big)) * chroma_gain
    B_res = (B - _blur(B, r_big)) * chroma_gain

    # --- 2ב. **עוגן הגוון, ולמה הוא חובה.** בגרסה הראשונה
    # ``a``/``b`` אופסו לגמרי "כדי שהטון יגיע מהצינור", והמפה יצאה
    # **ציאנית** - נמדד ונראה בעין. הסיבה: שארית סביב אפס היא
    # סימטרית, ולכן חצי מהפיקסלים נדחפים ל-``a`` שלילי, שהוא ירוק.
    # לעור אין ``a`` שלילי: הווריאציה שלו היא עוצמת המוגלובין על
    # ציר אדום-כתום בלבד. לכן נשמר הגוון הממוצע של הצילום כעוגן,
    # מוגבל לתחום של עור בריא, והשארית נעה **סביבו**.
    a_anchor = float(np.clip(np.mean(A), 7.0, 20.0))
    b_anchor = float(np.clip(np.mean(B), 9.0, 24.0))

    # 62 הוא בהירות אמצע שמשאירה מרווח לשני הכיוונים בלי לקצץ את
    # המיקרו; הטון הסופי נקבע בהכפלה מול ``tone`` של הדמות.
    L_out = np.clip(62.0 + L_micro, 2.0, 98.0)
    # ``a`` נחסם מלמטה ב-1: ירוק בעור הוא תמיד חפץ עיבוד.
    A_out = np.clip(a_anchor + A_res, 1.0, 34.0)
    B_out = np.clip(b_anchor + B_res, 1.0, 36.0)
    albedo = lab_to_rgb(np.stack([L_out, A_out, B_out], axis=-1))
    albedo = np.clip(make_tileable(albedo), 0.0, 1.0)

    # --- 3. חספוס: נקבובית (שקע) מחוספסת, בליטה חלקה. הקשר הזה
    # הוא מה שמייצר ברק לא אחיד, ובלעדיו העור קורא "פלסטיק" גם
    # עם מפת צבע מושלמת.
    nm = L_micro / (np.abs(L_micro).max() + 1e-6)
    rough = np.clip(0.46 - 0.17 * nm, 0.22, 0.78)
    rough = np.clip(make_tileable(rough), 0.0, 1.0)

    # --- 4. נורמל ממפת הגובה (sobel). ``L_micro`` הוא הגובה: שקע
    # כהה, בליטה בהירה - וזו ההנחה שמאחורי כל מפת bump מצילום.
    hgt = np.clip(0.5 + nm * 0.5, 0.0, 1.0)
    hgt = make_tileable(hgt)
    gx = np.gradient(hgt, axis=1) * size * 0.012
    gy = np.gradient(hgt, axis=0) * size * 0.012
    nz = np.ones_like(gx)
    n = np.stack([-gx, -gy, nz], axis=-1)
    n /= (np.linalg.norm(n, axis=-1, keepdims=True) + 1e-9)
    normal = np.clip(n * 0.5 + 0.5, 0.0, 1.0)

    return {"albedo": albedo, "roughness": rough, "normal": normal}


def save_set(maps: dict[str, np.ndarray], out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    rep = {}
    for name, arr in maps.items():
        a = np.clip(arr, 0.0, 1.0)
        if a.ndim == 2:
            img = Image.fromarray((a * 255.0 + 0.5).astype(np.uint8), "L")
        else:
            img = Image.fromarray((a * 255.0 + 0.5).astype(np.uint8), "RGB")
        p = out / ("skin_%s.png" % name)
        img.save(p, optimize=True)
        rep[name] = {"file": p.name, "bytes": p.stat().st_size,
                     "size": list(img.size),
                     "sha256": hashlib.sha256(p.read_bytes()).hexdigest()[:16]}
    return rep


def measure(maps: dict[str, np.ndarray]) -> dict:
    """מדידות שמנבאות את שער האיכות, לפני שמריצים רנדר."""
    alb = maps["albedo"]
    lab = rgb_to_lab(alb)
    chroma = np.sqrt(lab[..., 1] ** 2 + lab[..., 2] ** 2)
    g = (alb.mean(axis=-1) * 255.0)
    lap = np.abs(4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1]
                 - g[1:-1, :-2] - g[1:-1, 2:])
    return {
        # **העוגן שמאפשר לשמור את הטון של הדמות.** בבלנדר המפה
        # מחולקת בממוצע הזה, ולכן מה שנשאר ממנה הוא **יחס** סביב
        # 1.0 - מיקרו וכרומה בלבד. בלי זה היה צריך לבחור בין
        # "הטון של הצילום" לבין "הטון של הדמות"; עם זה אין צורך.
        "albedo_mean": [round(float(alb[..., c].mean()), 6)
                        for c in range(3)],
        "chroma_mean": round(float(chroma.mean()), 3),
        "chroma_std": round(float(chroma.std()), 3),
        "ab_std": round(float(np.std(lab[..., 1:])), 3),
        "lap_abs": round(float(lap.mean()), 3),
        "unique_colors": int(len(np.unique(
            (alb * 255).astype(np.uint8).reshape(-1, 3), axis=0))),
        "seam_albedo": round(seam_error(alb), 5),
        "seam_rough": round(seam_error(maps["roughness"]), 5),
    }


def produce(out: Path, size: int = 2048, cache: Path | None = None,
            chroma_gain: float = 2.6) -> dict:
    """הצינור המלא. מחזיר דוח; ``ok=False`` = נפילה רכה לפרוצדורלי."""
    cache = cache or (out / "_src")
    for src in SOURCES:
        p = fetch(src, cache)
        if not p:
            continue
        try:
            maps = build_maps(p, size, chroma_gain=chroma_gain)
        except Exception as e:                               # noqa: BLE001
            log("עיבוד נכשל (%s): %s" % (src["name"], e))
            continue
        rep = {"ok": True, "source": src["name"], "license": src["license"],
               "page": src["page"], "size": size, "chroma_gain": chroma_gain,
               "files": save_set(maps, out), "metrics": measure(maps)}
        (out / "skin_source.json").write_text(
            json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        log("ערכת מפות נבנתה מ-%s (%s)" % (src["name"], src["license"]))
        return rep
    log("אין מקור זמין - נפילה לחומר פרוצדורלי")
    return {"ok": False}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=int, default=2048)
    ap.add_argument("--cache", default=None)
    # הגבר הכרומה. ברירת המחדל 2.6 נתנה ``chroma_std`` של 10.5
    # על המפה, ובפריים המרונדר זה לא הזיז את המדד בכלל (נמדד,
    # ריצה 38526001823). ההגבר הוא היחיד שמשפיע ישירות על
    # הפסיפס, ולכן הוא יוצא לשורת הפקודה ולא נשאר קבוע בקוד.
    ap.add_argument("--chroma", type=float, default=2.6)
    a = ap.parse_args(argv)
    rep = produce(Path(a.out), a.size,
                  Path(a.cache) if a.cache else None,
                  chroma_gain=a.chroma)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
