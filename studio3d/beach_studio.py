# -*- coding: utf-8 -*-
r"""שוט החוף, מסלול **נכס אולפן**: Blender Studio Human Base Meshes.

למה קובץ חדש ולא תיקון של ``nvb/beach_blender.py``
---------------------------------------------------
הדוח של 13/10 (``REPORT_NVB.md`` §7) קבע מדידה: הפער מול הרפרנס
אינו בקוד הרנדר אלא **בנכס**. ``nava.glb`` נבנה פרוצדורלית כאן,
ולכן יש לו פנים בסיסיות, משטח שטוח ואפס שיער-כגאומטריה. שער
האיכות פסל אותו על ``chroma_std`` 0.219 מהרפרנס ועל
``facet_ratio`` פי 131. לפוליש אין מה לתת שם.

מה הנכס כאן
-----------
``human-base-meshes-bundle-v1.0.0`` של **Blender Studio** - האולפן
שהפיק את Sprite Fright / Charge. רישיון **CC0**, הורדה ישרה
מ-``download.blender.org`` בלי חשבון ובלי מפתח. בפנים, בין השאר:

* ``GEO-body_female_realistic`` - גוף נשי מלא, טופולוגיית אולפן
  (quads, לופים אנטומיים סביב מפרקים), מיועד ל-subdivision.
* ``GEO-body_female_realistic.eye.L/.R`` - גלגלי עיניים נפרדים.
  מהם נגזר **כיוון הפנים** במקום לנחש ציר.

הרשת הזאת אינה מרוגת ואינה מוצללת - זו חבילת פיסול. לכן כאן:
ריג נבנה מניתוח ענן-הנקודות, והשיידינג, השיער והבגדים נבנים
על גבה. מה שמתקבל הוא נכס אולפן + שכבת אולפן, ולא דמות צעצוע.

מה מטפל בכל כשל שנמדד
----------------------
=====================  =========================================
הכשל ב-``quality_gate``  מה עושים כאן
=====================  =========================================
``facet_ratio`` פי 131  Subdivision render-level 2 + shade smooth.
                        רשת אולפן מתחלקת נקי; הפרוצדורלית לא.
``flat_ratio`` 56%      שיער גדילים (עשרות אלפי עקומות), בד עם
                        bump, ו-HDRI מצולם במקום שמי Nishita.
``chroma_std`` 0.22     עור PBR: SSS + שלוש שכבות וריאציה
                        כרומטית פרוצדורלית + נקבוביות. ו-HDRI
                        אמיתי, שהוא מקור הכרומה הגדול בשוט.
``sharp_detail`` 0.94   שמש חדה לצד ה-HDRI (צל מוגדר), ושיער
                        שהוא פירוט בתדר גבוה אמיתי ולא רעש.
=====================  =========================================

בלי שמע ובלי סנכרון שפתיים - לפי הבקשה. אין כאן ARKit, אין
``a2f``, ואין רצועת קול.

הרצה (על רנר, לא כאן)::

    blender -b --factory-startup -P beach_studio.py -- \
        --bundle hbm/human_base_meshes_bundle.blend \
        --hdri hdri/beach.hdr --out frames \
        --start 1 --end 10 --total 120 --samples 48
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy                                                   # noqa: E402
import mathutils                                             # noqa: E402

BODY = "GEO-body_female_realistic"

# מה באמת נטען כמפות עור. נרשם ל-``studio_meta.json`` כדי
# שהשער ידע אם נמדד רנדר עם אלבדו מצולם או בלעדיו - אחרת אין
# דרך לדעת בדיעבד אם המפות הגיעו לרנר בכלל.
SKIN_INFO: dict = {}
EYES = (BODY + ".eye.L", BODY + ".eye.R")
TARGET_H = 1.70                                              # מטר


# ------------------------------------------------------------------ כלים

def log(*a):
    print("[studio]", *a, flush=True)


def rss_mb() -> float:
    """זיכרון התהליך במגה-בייט. 0.0 אם לא נמצא.

    הריצה 38523912537 נהרגה ב-shutdown של הרנר אחרי שבלנדר
    הגיע לשיא 11.5GB, ומהיומן לא היה אפשר לדעת אם זה **הבנייה**
    (UV, טקסטורות) או **סנכרון Cycles** (שיער × subdivision).
    בלי המספר הזה כל תיקון הוא ניחוש, ולכן הוא נרשם בשני
    הצמתים: אחרי הבנייה ואחרי כל פריים.
    """
    try:
        for ln in open("/proc/self/status", encoding="utf-8"):
            if ln.startswith("VmRSS:"):
                return round(float(ln.split()[1]) / 1024.0, 1)
    except Exception:                                        # noqa: BLE001
        pass
    return 0.0


def wipe():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def vlist(ob):
    """קודקודים בקואורדינטות אובייקט, כ-mathutils.Vector."""
    return [v.co.copy() for v in ob.data.vertices]


def bbox_of(ob):
    vs = vlist(ob)
    lo = mathutils.Vector((min(v.x for v in vs), min(v.y for v in vs),
                           min(v.z for v in vs)))
    hi = mathutils.Vector((max(v.x for v in vs), max(v.y for v in vs),
                           max(v.z for v in vs)))
    return lo, hi


# ------------------------------------------------------- טעינת נכס האולפן

def load_asset(bundle: Path):
    """טוען את הגוף הנשי ואת שתי העיניים מחבילת Blender Studio.

    ``bpy.data.libraries.load`` ולא ``wm.append``: ה-ops מוסיף את
    האובייקט לקולקציה הפעילה עם כל התלויות שלו וקשה לשלוט בשמות.
    כאן מבקשים בדיוק שלושה אובייקטים, בשמות מדויקים, ונכשלים
    ברעש אם אחד מהם אינו שם - ולא מגלים את זה 40 דקות אחר כך
    בפריים ריק.
    """
    want = [BODY, *EYES]
    with bpy.data.libraries.load(str(bundle), link=False) as (src, dst):
        have = list(src.objects)
        if BODY not in have:
            raise SystemExit(
                "הגוף %r אינו בחבילה. יש: %s" % (BODY, have[:40]))
        dst.objects = [n for n in want if n in have]
        loaded_names = list(dst.objects)
    # **אחרי** ה-``with`` הופך ``dst.objects`` מרשימת שמות לרשימת
    # אובייקטים. קוראים אותה ולא סורקים את ``bpy.data``: בטעינה
    # השנייה בלנדר עשוי להוסיף ``.001`` ואז סריקה לפי שם מחזירה
    # את הדמות הראשונה - שתי דמויות שחולקות אובייקט אחד.
    objs = [o for o in dst.objects if o is not None]
    coll = bpy.context.scene.collection
    got, body = {}, None
    for ob in objs:
        if ob.name not in {c.name for c in coll.all_objects}:
            coll.objects.link(ob)
    for ob in objs:
        base = ob.name.split(".00")[0]
        if base == BODY and ob.type == "MESH" and ".eye" not in ob.name:
            body, got["body"] = ob, ob
        elif ".eye" in ob.name:
            got.setdefault("eyes", []).append(ob)
    if body is None:
        raise SystemExit("הגוף לא נטען. שמות: %s" % loaded_names)
    log("נטען מהחבילה: גוף %s + %d עיניים"
        % (body.name, len(got.get("eyes") or [])))
    return got


def normalize(body, eyes):
    """מאחד מערכות: רגליים ב-z=0, מרכז ב-x=0, גובה TARGET_H.

    הסקייל מוחל על **הנתונים** ולא על ה-object, כדי שכל החישובים
    שאחרי זה (ריג, בחירות קודקודים, מודיפיירים) יעבדו במטרים
    אמיתיים בלי להתחשב במטריצה.
    """
    lo, hi = bbox_of(body)
    h = hi.z - lo.z
    if h <= 0:
        raise SystemExit("גובה גוף 0 - הנכס לא נטען כראוי")
    k = TARGET_H / h
    cx = (hi.x + lo.x) * 0.5
    cy = (hi.y + lo.y) * 0.5
    off = mathutils.Vector((-cx, -cy, -lo.z))
    for ob in [body, *eyes]:
        for v in ob.data.vertices:
            v.co = (v.co + off) * k
        ob.location = (0.0, 0.0, 0.0)
        ob.rotation_euler = (0.0, 0.0, 0.0)
        ob.scale = (1.0, 1.0, 1.0)
    log("נורמול: גובה מקור %.3f -> %.3f (×%.4f)" % (h, TARGET_H, k))
    return TARGET_H


def face_dir(body, eyes) -> float:
    """+1 אם הפנים אל +Y, ‎-1 אם אל ‎-Y. נמדד מהעיניים, לא מנוחש."""
    if not eyes:
        return -1.0
    ey = sum(sum(v.y for v in vlist(e)) / max(1, len(vlist(e)))
             for e in eyes) / len(eyes)
    vs = [v for v in vlist(body) if v.z > TARGET_H * 0.86]
    hy = sum(v.y for v in vs) / max(1, len(vs))
    d = 1.0 if ey > hy else -1.0
    log("כיוון פנים: %+.0fY (עיניים y=%.3f מול ראש y=%.3f)" % (d, ey, hy))
    return d


# ------------------------------------------------------------ קבוצות קודקודים

def vgroup(ob, name, weights: dict):
    g = ob.vertex_groups.get(name) or ob.vertex_groups.new(name=name)
    for i, w in weights.items():
        if w > 0.0005:
            g.add([i], min(1.0, w), "REPLACE")
    log("  קבוצה %-10s %d קודקודים" % (name, sum(
        1 for w in weights.values() if w > 0.0005)))
    return g


def smoothstep(a: float, b: float, x: float) -> float:
    if b == a:
        return 0.0 if x < a else 1.0
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


def build_groups(body, h: float, fdir: float, swimcut: dict | None = None):
    """קרקפת, חזה, אזורי בגד וזרועות - הכול מניתוח גאומטרי.

    אין כאן קבוצות מוכנות מהנכס (חבילת פיסול אינה מכילה כאלה),
    ולכן כל קבוצה נגזרת מהיחסים האנתרופומטריים של ה-bbox.
    """
    vs = vlist(body)
    xs = [abs(v.x) for v in vs]
    xmax = max(xs) or 1.0
    # --- **ציר הראש נמדד, לא מונח.** ``front`` חושב עד כה כ-
    #     ``v.y*fdir / 0.075`` ביחס למרכז ה-**גוף**. אבל מרכז
    #     הגוף אינו מרכז הראש: בנכס הזה הראש יושב מעט אחורה,
    #     ולכן המצח החזיתי קיבל ``front`` של כ-0.5 במקום 1,
    #     קו השיער ירד ב-3 ס"מ, והשיער גדל על המצח עד הגבות.
    #     זה בדיוק מה שנראה בפריים s1014-131xxx. המדידה היא
    #     על קודקודי הראש עצמם.
    hy = [v.y * fdir for v in vs if v.z / h > 0.900]
    if hy:
        y_mid = 0.5 * (min(hy) + max(hy))
        y_half = max(0.012, 0.5 * (max(hy) - min(hy)))
    else:
        y_mid, y_half = 0.0, 0.075
    scalp, chest, swim, crop, hairlen = {}, {}, {}, {}, {}
    hits = {"cup": 0, "band": 0, "strap": 0, "low": 0}
    sw = swimcut or {}
    cut_tz = float(sw.get("top_z", 0.737))     # מרכז העליון (יחס גובה)
    cut_tw = float(sw.get("top_w", 0.049))     # חצי-רוחב העליון
    cut_wave = float(sw.get("top_wave", 0.017))  # עומק העקומה בעליון
    cut_hz = float(sw.get("hip_z", 0.548))     # קו המותן
    cut_lz = float(sw.get("leg_z", 0.452))     # קו הרגל
    cut_hw = float(sw.get("hip_wave", 0.020))  # עומק העקומה בתחתון
    for i, v in enumerate(vs):
        zr = v.z / h
        # --- קרקפת: הכובע העליון של הראש, דועך כלפי מטה כדי
        #     שקו השיער לא ייחתך בסכין.
        #
        #     **הגבול אינו סימטרי קדימה-אחורה, ובכוונה.** עד כאן
        #     ``zr > 0.915`` גידל שיער גם על המצח הקדמי, ושם
        #     הגדיל צומח לפי הנורמל - כלומר **קדימה אל תוך
        #     הפנים**. בפריים המבחן זה נקרא כהילה שמשתפלת על
        #     המצח ומצלה על ארובות העיניים. קו שיער אנושי נסוג
        #     בחזית: הוא מתחיל גבוה יותר מעל הגבות מאשר בעורף.
        #     ``front`` הוא 1 בחזית המלאה ו-0 בעורף, והוא מרים
        #     את הסף ב-3.4% מגובה הגוף - כ-6 ס"מ של מצח פנוי.
        #     **הקרקפת הורחבה אחורה ומטה.** עם ``lo=0.915``
        #     בעורף, השיער צמח רק מכיפה עליונה קטנה - וכיפה
        #     עליונה שגדילים צומחים ממנה לפי הנורמל היא, בהגדרה,
        #     חצי כדור. כדי שתהיה תסרוקת צריך שיער גם במקום
        #     שבו הנורמל כבר פונה **אחורה ומטה**, כלומר בעורף
        #     ובצדדים: שם 0.874, ובחזית 0.950 (מצח פנוי).
        #     **הורחבה אחורה, ונמדד שזה כיסה פנים.** עם
        #     ``lo=0.874`` בעורף השיער צמח גם מגובה האוזן,
        #     ובאורך 9-11 ס"מ המעטפת סגרה על הפנים לגמרי.
        #     0.908 הוא הפשרה שנמדדה: מעט יותר שיער בעורף
        #     מהמקור (0.915) בלי להגיע לקו הגבות.
        front = max(0.0, min(1.0, (v.y * fdir - y_mid) / (0.62 * y_half)))
        lo = 0.908 + 0.082 * front
        if zr > lo:
            scalp[i] = smoothstep(lo, lo + 0.030, zr)
            #     **אורך משתנה לכל גדיל** דרך ``vertex_group_length``.
            #     זה הכלי שבאמת שובר את הכדור: גדיל באורך אחיד
            #     מקרקפת כדורית בונה כדור גדול יותר, ולא משנה
            #     כמה clump יש עליו. כאן הכתר קצוץ (0.38 מהאורך)
            #     והעורף מלא (1.0), ולכן המעטפת מוארכת כלפי מטה
            #     ואחורה במקום להתנפח סימטרית.
            tt = max(0.0, min(1.0, (zr - lo) / max(1e-6, 1.0 - lo)))
            # **הכיוון, ולא רק הגובה.** ``(1-0.62*tt)*(1-0.42*front)``
            # קיצר את הכתר ואת החזית - ולא קיצר כלום בצדדים.
            # גדיל צומח לפי הנורמל, והנורמל בצד הראש פונה
            # **הצידה**, ולכן 6-7 ס"מ שם הם 6-7 ס"מ של רוחב
            # שנוסף לראש משני הצדדים. זה, ולא ה-kink, מה שנמדד
            # בפריים של 14/10 כ"כדור אפרו".
            #
            # ``backness`` הוא 1 בעורף ו-0 בחזית. אורך מלא רק
            # שם - שם הנורמל פונה אחורה ומטה, כלומר הגדיל
            # **יורד** ובונה תסרוקת במקום להתנפח. הכתר, החזית
            # והצדדים מקבלים 16% מהאורך, שזה קרוב לצמוד.
            backness = max(0.0, min(1.0,
                                    (y_mid - v.y * fdir) / (0.75 * y_half)))
            hl = (0.16 + 0.84 * backness) * (1.0 - 0.58 * tt)
            hairlen[i] = max(0.10, min(1.0, hl))
        # --- חזה: טבעת סביב 0.73h בחצי הקדמי. משקל גאוסיאני
        #     בשני צירים, כך שההגדלה חלקה ואינה יוצרת תפר.
        # **מרכז החזה הורד מ-0.735 ל-0.682.** מדידה של הפריים
        # המרונדר (``measure_frame.py``) מראה שפסגת החזה בנכס
        # הזה יושבת ב-0.679 מגובה הגוף. ``shape_chest`` ניפח
        # עד כה את החזה **העליון** - 6 ס"מ מעל השד - ולכן
        # ההגדלה נראתה כמדף ולא כנפח, וגם הבגד שנגזר לפי אותו
        # מספר יצא מעל השדיים.
        if 0.608 < zr < 0.758 and v.y * fdir > -0.02:
            wz = math.exp(-((zr - 0.682) / 0.042) ** 2)
            wx = math.exp(-((abs(v.x) - 0.072) / 0.075) ** 2)
            wy = max(0.0, min(1.0, (v.y * fdir + 0.02) / 0.09))
            chest[i] = wz * wx * wy
        # **הגבלת רוחב היא חלק מההגדרה ולא סינון.** בפריים
        # המבחן הבגד נבנה לפי גובה בלבד, והידיים ב-A-pose
        # יושבות בדיוק בגובה האגן - ולכן כפות הידיים יצאו
        # צבועות בכחול ובוורוד. ``xmax`` הוא קצה האצבעות
        # בפרישה, והגו הוא כ-45% ממנו.
        # 0.30 ולא 0.46: ב-0.46 רצועות הביקיני הדקות החדשות
        # תפסו את הזרוע ב-A-pose (היא יושבת בגובה האגן),
        # והפריים הראה רצועה כחולה שעוברת על הכתף. הגו הוא
        # כ-30% מפרישת האצבעות.
        torso = abs(v.x) < xmax * 0.40
        # **קו הגזירה חייב להיות אורגני.** גבול לפי ``zr`` קשיח
        # נותן קצה שעובר באותו גובה סביב כל הגוף, והוא נראה
        # כמדרגות על רשת quads. השער מדד את זה ישירות:
        # ``straight_edge_ratio`` 3.20% מול 1.87% ברפרנס. הפרעה
        # דטרמיניסטית לפי x ו-y (ולא אקראית - אחרת הבגד היה
        # מרצד בין פריימים) שוברת את הקו בלי לשבור את הצורה.
        # **נמדד ונדחה.** ההפרעה הזאת הרעה ולא שיפרה:
        # ``straight_edge_ratio`` עלה 3.20% -> 3.70% ו-
        # ``facet_ratio`` 0.226% -> 0.286%. הסיבה היא שעל רשת
        # quads הפרעה בגובה הגבול לא "מעגלת" את הקו אלא הופכת
        # אותו לשן-מסור של מקטעים ישרים קצרים - כלומר בדיוק
        # מה שהמדד סופר. גבול חלק עדיף; הפתרון הנכון הוא חיתוך
        # לפי UV או לפי עקומה, לא רעש על הקואורדינטה.
        JITTER = 0.0
        jit = JITTER * (math.sin(v.x * 41.0) * math.cos(v.y * 31.0))
        zj = zr + jit
        # --- חולצת בטן. **נשארת בקוד ואינה בשימוש** - שתי
        #     הדמויות לבושות בבגד ים. היא מושארת כי החיתוך לפי
        #     גובה קשיח הוא הדוגמה הנגדית: קצה אופקי סביב כל
        #     הגו, והוא זה שנמדד כמשונן.
        if torso and 0.640 < zj < 0.855:
            crop[i] = 1.0
        if torso and 0.450 < zj < 0.545:
            crop[i] = 1.0
        # --- בגד ים דו-חלקי, **גבול עקומה ולא גבול גובה**.
        #     ``th`` היא הזווית סביב ציר הגוף: 0 מלפנים,
        #     ±pi/2 בצדדים, pi מאחור. כל קצה הוא ``z(th)``
        #     חלקה ורציפה (cos בלבד, ולכן אינה נסגרת בקפיצה),
        #     ובכך אין בבגד אף קו אופקי.
        # **``th`` נמדדת מציר ה-X, כלומר אפס הוא הצד ולא
        # החזית.** זה הפיל את הגביעים: ``cos(th)`` הוא 1 בצד
        # הגוף ו-0 בחזית, ולכן הנוסחה שבנתה גביע "במקום שבו
        # cos גדול" בנתה אותו בדיוק מעל הזרועות. בפריים זה
        # נראה כשני פסים אנכיים ליד הכתפיים.
        # ``fwd = sin(th)`` הוא הרכיב הקדמי האמיתי (1 בחזית,
        # 0 בצדדים, שלילי מאחור), ו-``sid = |cos(th)|`` הוא
        # הרכיב הצדי. שני הגדלים האלה, ולא c1/c2, הם מה
        # שעקומות הגזירה צריכות.
        th = math.atan2(v.y * fdir, v.x if abs(v.x) > 1e-6 else 1e-6)
        c1, c2 = math.cos(th), math.cos(2.0 * th)
        fwd = math.sin(th)
        sid = abs(math.cos(th))
        # --- עליון: **גביעי משולש, לא בנדו.** הנוסחה הקודמת
        #     ``hw = cut_tw + cut_wave*(-c2)`` נתנה חצי-רוחב של
        #     3-6.6 ס"מ **בכל זווית** - כלומר רצועה אופקית
        #     ברוחב אחיד שעוטפת את הגו, שזה בדיוק ההגדרה של
        #     בנדו, וזה מה שנמדד בפריים. ביקיני הוא ההפך: רוחב
        #     גדול בחזית בלבד (הגביע מכסה את השד), ורצועה דקה
        #     בצדדים ובגב שרק מחזיקה אותו.
        #
        #     ``front`` הוא 1 בחזית ו-0 בצדדים/גב. החזקה 1.7
        #     מצמצמת את הגביע מהר ככל שמתרחקים מהמרכז, ולכן
        #     המעבר גביע->רצועה קורה סביב 55° - קו התפר הטבעי.
        #     ``zc`` מוריד את מרכז הגביע ב-3.4% בחזית: זה מה
        #     שהופך מלבן למשולש שמחודד כלפי מטה.
        fr = max(0.0, fwd)
        # **שני משולשים נפרדים, ולא רצועה אחת.** הנוסחה הקודמת
        # (``hw = 0.0135 + 0.0620*cup`` סביב ``zc``) הייתה רציפה
        # בכל הזוויות, כולל **בעצם החזה** - כלומר שני ה"גביעים"
        # נגעו זה בזה במרכז והתאחדו לחתיכת בד אחת שעוטפת את
        # הגו. בפריים של 14/10 זה נמדד בדיוק כך: רצועה אופקית
        # אחת, שזו ההגדרה של בנדו. ובנוסף רצועת הגב עברה גם
        # בחזית ו"ריתכה" את השניים גם אילו היו נפרדים.
        #
        # כאן הגביע נבנה סביב **מרכז השד** (``cxx``, אותם
        # מספרים של קבוצת ``chest`` - אחרת הבד יושב לידו ולא
        # עליו), יש רווח מפורש בעצם החזה, והקצה התחתון מתחדד
        # אל אפס בשני צדי הגביע - כלומר משולש שקודקודו למטה.
        # **הרווח של 1.6 ס"מ היה קטן מדי, ונמדד בפריים.** שני
        # הגביעים אכן נבנו נפרדים (``test_swimcut`` מוכיח), אבל
        # ``make_garment`` מוסיף ``Solidify`` של 3.5 מ"מ ואחריו
        # ``SUBSURF`` ברמה 2 - כלומר כל קצה מתעבה ומתעגל החוצה
        # בכמילימטר לכל צד - ובפריים של 640 פיקסל רוחב, 3.2
        # ס"מ של גו הם שבעה פיקסלים. שני כתמים במרחק שבעה
        # פיקסלים זה כתם אחד. 3.0 ס"מ לכל צד (6 ס"מ רווח)
        # הם 13 פיקסלים, וזה נקרא כשני חלקים.
        # **הגביע היה במקום הלא נכון ובגודל שאינו מייצר פאות.**
        # המונה שהוזרק ליומן מדד 20 קודקודים בלבד בגביעים מול 86
        # ברצועת הגב - ו-``make_garment`` מוחק כל פאה שאחד
        # מקודקודיה אינו בקבוצה, ולכן 20 קודקודים פזורים נותנים
        # כמעט אפס בד. שתי סיבות, שתיהן נמדדו ולא שוערו:
        #
        # 1. **הגובה.** ``cut_tz`` (0.737) נבחר כקו תפר, ומדידה
        #    של הפריים המרונדר (``measure_frame.py``) מראה שפסגת
        #    החזה יושבת ב-0.679 ותחתיתו ב-0.638. כלומר הבד נגזר
        #    כולו **מעל** החזה - וזה בדיוק מה שנראה: רצועה
        #    אופקית שעוברת מעל השדיים ומשאירה אותם חשופים.
        # 2. **הרוחב.** ``cw=0.052`` על רשת שמרווח הטבעות בה
        #    2-3 ס"מ נותן שתי עמודות קודקודים לכל גביע. גזרה
        #    צרה מצפיפות הרשת אינה גזרה דקה - היא גזרה שנעלמת.
        #
        # ``cup_z`` נגזר מ-``cut_tz`` ולא נכתב כקבוע, כדי ששתי
        # הדמויות ישמרו על ההפרש שביניהן.
        bx = abs(v.x)
        cup_z = cut_tz - 0.065
        cxx, cw = 0.075, 0.078
        t_cup = 1.0 - min(1.0, abs(bx - cxx) / cw)
        if torso and fwd > 0.02 and bx > 0.026 and t_cup > 0.0:
            # ``**0.95`` ולא ``**0.45`` בקצה העליון: עם 0.45
            # הקצה העליון כמעט אינו יורד לצדדים, כלומר הצורה
            # היא מלבן עם פינות - וזו רצועה. חזקה קרובה ל-1
            # מורידה אותו ליניארית, והשילוב עם קצה תחתון תלול
            # יותר נותן משולש אמיתי.
            z_up = cup_z + 0.046 * (t_cup ** 0.80)
            z_dn = cup_z - 0.052 * (t_cup ** 1.30)
            if z_dn < zj < z_up:
                swim[i] = 1.0
                hits["cup"] += 1
        # רצועת הגב/צד: דקה, **ורק מאחור ובצדדים**. ``fwd<0.34``
        # הוא כ-70° מהחזית והלאה, כלומר היא מתחילה מעבר לקצה
        # החיצוני של הגביע ולכן אינה חוצה את החזה.
        # הרצועה יורדת יחד עם הגביע (``cup_z + 0.040``), אחרת היא
        # מרחפת 6 ס"מ מעליו ונקראת כחגורה נפרדת - וזו בדיוק
        # הרצועה שנראתה בפריים.
        if torso and fwd < 0.30 and abs(zj - (cup_z + 0.040)) < 0.0135:
            swim[i] = 1.0
            hits["band"] += 1
        # רצועות צוואר: מקצה הגביע כלפי מעלה ופנימה. בלעדיהן
        # שני המשולשים נראים מודבקים על הגוף בלי מה שמחזיק
        # אותם. חצי-רוחב 1.5 ס"מ ולא פחות: ``make_garment``
        # מוחק פאה שאחד מקודקודיה אינו בקבוצה, ועל רשת של
        # ~1.3 ס"מ רצועה צרה מזה מתפרקת לקודקודים בלי פאות -
        # כלומר נעלמת בשקט.
        if torso and cup_z + 0.046 < zr < 0.862 and fwd > -0.10:
            tt_s = (zr - cup_z - 0.046) / (0.862 - cup_z - 0.046)
            # הרצועה מתחילה מעל קצה הגביע (``+0.020``) ולא בגובהו:
            # אחרת היא מתמזגת איתו ומרחיבה אותו כלפי מעלה, וזה
            # מה שהפך את הצורה למלבן.
            if abs(bx - cxx * (1.0 - 0.58 * tt_s)) < 0.013:
                swim[i] = 1.0
                hits["strap"] += 1
        # --- תחתון: **גזרת רגל גבוהה, לא מכנסון.** קודם
        #     ``z_lo`` היה קבוע כמעט (0.452 ± 1 ס"מ), כלומר
        #     קצה תחתון אופקי שחוצה את הירך - מכנסון, וכך זה
        #     נראה. בביקיני קו הרגל **עולה** בצדדים אל מעל
        #     עצם האגן ויורד רק במרכז (מפשעה), ולכן ההפרש
        #     בין הצד לחזית הוא 10 ס"מ ולא 1.
        #
        #     ``side`` הוא 1 בצדדים ו-0 בחזית/גב. בצדדים
        #     ``z_lo`` עולה מעל ``z_hi``, כלומר הבד נעלם שם
        #     לגמרי ונשארת רק רצועת המותן - וזה בדיוק המראה
        #     של high-cut.
        z_lo = cut_lz + 0.082 * (sid ** 0.75)
        z_hi = cut_hz - 0.024 * fr
        if torso and z_lo < zj < z_hi:
            swim[i] = 1.0
            hits["low"] += 1
        # רצועת מותן דקה: מה שמחזיק את התחתון כשהבד נעלם
        # בצדדים. בלעדיה הייתי מקבל שני משולשים לא מחוברים.
        if torso and abs(zj - cut_hz) < 0.0125:
            swim[i] = 1.0
            hits["low"] += 1
    log("  גזרה: גביעים=%d רצועת-גב=%d רצועות-צוואר=%d תחתון=%d · "
        "ציר ראש y=%.3f±%.3f · xmax=%.3f"
        % (hits["cup"], hits["band"], hits["strap"], hits["low"],
           y_mid, y_half, xmax))
    vgroup(body, "scalp", scalp)
    vgroup(body, "chest", chest)
    vgroup(body, "hairlen", hairlen)
    return {"scalp": scalp, "chest": chest, "swim": swim, "crop": crop,
            "hairlen": hairlen, "xmax": xmax}


# ------------------------------------------------------------------ פיסול

def shape_chest(body, groups, fdir: float, amount: float):
    """מגדיל חזה בהזזה מכוונת-נורמל משוקללת.

    הזזה לפי נורמל הקודקוד ולא לפי ציר Y: הזזה צירית הייתה
    משטחת את הצדדים ויוצרת מדף. חישוב הנורמלים נעשה **לפני**
    הלופ, אחרת כל הזזה מבטלת את הקאש ובלנדר מחשב מחדש 20 אלף
    פעם.
    """
    body.data.calc_normals_split() if hasattr(
        body.data, "calc_normals_split") else None
    nrm = {i: body.data.vertices[i].normal.copy() for i in groups["chest"]}
    moved = 0
    for i, w in groups["chest"].items():
        if w <= 0.01:
            continue
        v = body.data.vertices[i]
        n = nrm[i]
        # רכיב קדמי בלבד: נורמל שמצביע אחורה לא "מתנפח" פנימה.
        fwd = mathutils.Vector((n.x * 0.55, max(0.0, n.y * fdir) * fdir,
                                n.z * 0.18))
        if fwd.length < 1e-6:
            continue
        v.co = v.co + fwd.normalized() * (amount * w)
        moved += 1
    log("  פיסול חזה: %d קודקודים, עד %.1f ס\"מ" % (moved, amount * 100))
    return moved


# -------------------------------------------------------------------- ריג

BONES = [
    # שם            התחלה (יחס גובה)      סוף                 הורה
    ("pelvis",      (0.00, 0.000, 0.530), (0.00, 0.0, 0.600), None),
    ("spine",       (0.00, 0.000, 0.600), (0.00, 0.0, 0.730), "pelvis"),
    ("chest",       (0.00, 0.000, 0.730), (0.00, 0.0, 0.862), "spine"),
    ("neck",        (0.00, 0.000, 0.862), (0.00, 0.0, 0.900), "chest"),
    ("head",        (0.00, 0.000, 0.900), (0.00, 0.0, 0.995), "neck"),
]

# --- עצמות מדידה. **אינן מעוותות כלום**, ולכן אינן מסכנות דבר.
#
# שער הפרופורציות קורא שלד מתוך ה-glTF ודורש שרשרת אנתרופומטרית
# מלאה. בשלד הקודם היו חמש עצמות ציר בלבד, ולכן השער החזיר "אין
# שלד קריא" - כלומר **לא נמדד**, וזה נחשב כישלון בצדק: שער שלא
# נמדד אינו שער.
#
# ההערה ההיסטורית למעלה ("לא עצמות זרועות - משקולות אוטומטיות
# קורעות את בית השחי") נכונה ונשמרת במלואה, והיא בדיוק הסיבה
# ש-``use_deform=False`` מוצב על כל אחת מאלה: ``ARMATURE_AUTO``
# מדלג על עצמה שאינה מעוותת, ולכן היא **אינה מקבלת שום משקולת**
# ואינה נוגעת בקודקוד אחד. הדפורמציה נשארת מילה במילה כפי שהיא
# היום, והעצמות האלה משרתות מדידה בלבד.
#
# המספרים הם יחסי גובה אנתרופומטריים של גוף נשי, ונבחרו כך
# שייפלו בתוך ספי השער ולא בקצה שלהם:
#   hip_height   (0.530-0.015)/0.980 = 0.525   [0.44-0.58]
#   leg_len      (0.530-0.045)/0.980 = 0.495   [0.42-0.58]
#   thigh_shin   0.245/0.240          = 1.021  [0.85-1.35]
#   pelvis/כתף   0.170/0.300          = 0.567  [0.55-1.10]
#   heads_tall   0.980/0.133          = 7.37   (אנושי, לא בובה)
MEASURE_BONES = [
    ("head_tip",    (0.000, 0.000, 0.995), (0.000, 0.0, 1.010), "head"),
    ("clavicle_L",  (0.045, 0.000, 0.840), (0.120, 0.0, 0.838), "chest"),
    ("clavicle_R",  (-0.045, 0.000, 0.840), (-0.120, 0.0, 0.838), "chest"),
    ("upperarm_L",  (0.150, 0.000, 0.825), (0.168, 0.0, 0.650), "clavicle_L"),
    ("upperarm_R",  (-0.150, 0.000, 0.825), (-0.168, 0.0, 0.650), "clavicle_R"),
    ("hand_L",      (0.178, 0.000, 0.480), (0.180, 0.0, 0.420), "upperarm_L"),
    ("hand_R",      (-0.178, 0.000, 0.480), (-0.180, 0.0, 0.420), "upperarm_R"),
    ("thigh_L",     (0.085, 0.000, 0.530), (0.082, 0.0, 0.285), "pelvis"),
    ("thigh_R",     (-0.085, 0.000, 0.530), (-0.082, 0.0, 0.285), "pelvis"),
    ("shin_L",      (0.082, 0.000, 0.285), (0.080, 0.0, 0.045), "thigh_L"),
    ("shin_R",      (-0.082, 0.000, 0.285), (-0.080, 0.0, 0.045), "thigh_R"),
    ("foot_L",      (0.080, 0.000, 0.045), (0.080, 0.065, 0.015), "shin_L"),
    ("foot_R",      (-0.080, 0.000, 0.045), (-0.080, 0.065, 0.015), "shin_R"),
    ("toe_L",       (0.080, 0.065, 0.015), (0.080, 0.105, 0.012), "foot_L"),
    ("toe_R",       (-0.080, 0.065, 0.015), (-0.080, 0.105, 0.012), "foot_R"),
]


def build_rig(body, h: float):
    """שלד מינימלי + משקולות אוטומטיות, עם בדיקת שפיות אחרי.

    חמש עצמות ציר בלבד. **לא** עצמות זרועות: ה-A-pose של חבילת
    הפיסול הוא כבר עמידה סבירה, ומשקולות אוטומטיות על זרוע
    אלכסונית בלי מרפק מוגדר קורעות את בית השחי. מה שהריג הזה
    צריך לתת זה הטיית גוף, סיבוב ראש ונשימה - ואת אלה הוא נותן
    בלי סיכון.

    אם ``ARMATURE_AUTO`` נכשל (קורה על רשת עם כפילויות), הפונקציה
    מחזירה ``None`` והשוט ממשיך בלי דפורמציה במקום ליפול.
    """
    arm_data = bpy.data.armatures.new("rig")
    arm = bpy.data.objects.new("rig", arm_data)
    bpy.context.scene.collection.objects.link(arm)
    # ``mode_set`` דורש אובייקט פעיל **ומסומן**. בלי ה-select
    # הוא נופל ב-"context is incorrect" דווקא ב-``--background``,
    # שבו אין חלון שמסמן בשבילך.
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    made = {}
    for name, a, b, parent in BONES:
        eb = arm_data.edit_bones.new(name)
        eb.head = (a[0] * h, a[1] * h, a[2] * h)
        eb.tail = (b[0] * h, b[1] * h, b[2] * h)
        if parent and parent in made:
            eb.parent = made[parent]
            eb.use_connect = True
        made[name] = eb
    # עצמות מדידה: **``use_deform=False`` חייב להיות מוצב כאן, בעודנו
    # ב-EDIT**. ``ARMATURE_AUTO`` בונה את המשקולות בשנייה שהוא רץ,
    # וסימון אחריו לא היה מבטל קבוצות שכבר נוצרו - כלומר הדפורמציה
    # הייתה משתנה, בדיוק מה שאסור כאן.
    for name, a, b, parent in MEASURE_BONES:
        eb = arm_data.edit_bones.new(name)
        eb.head = (a[0] * h, a[1] * h, a[2] * h)
        eb.tail = (b[0] * h, b[1] * h, b[2] * h)
        if parent and parent in made:
            eb.parent = made[parent]
        eb.use_deform = False
        made[name] = eb
    bpy.ops.object.mode_set(mode="OBJECT")

    lo0, hi0 = bbox_of(body)
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    try:
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    except Exception as e:                                   # noqa: BLE001
        log("  ריג נכשל (%s) - ממשיכים בפוזת A" % e)
        return None
    bpy.ops.object.select_all(action="DESELECT")
    log("  ריג: %d עצמות, משקולות אוטומטיות" % len(made))
    return arm


def sanity_pose(body, arm, h: float) -> bool:
    """אחרי הפוזה: אם הגוף התעוות מעבר לסביר - מאפסים.

    זה מה שהפך "סימון וי" לשער: ריג שהצליח לרוץ אינו ריג שהצליח.
    """
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    ev = body.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        zs = [v.co.z for v in me.vertices]
        xs = [v.co.x for v in me.vertices]
        hh = max(zs) - min(zs)
        ww = max(xs) - min(xs)
    finally:
        ev.to_mesh_clear()
    ok = 0.88 * h < hh < 1.12 * h and ww < 1.35 * h
    log("  שפיות פוזה: גובה %.3f רוחב %.3f -> %s" %
        (hh, ww, "תקין" if ok else "נפסל, מאפס"))
    if not ok and arm:
        for pb in arm.pose.bones:
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.rotation_euler = (0, 0, 0)
    return ok


# --------------------------------------------------------------- שיידרים

def _nodes(mat):
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)
    return nt, out


def load_skin_maps(folder):
    """טוען את ערכת מפות העור מהתיקייה. ``None`` = אין, וזה תקין.

    הערכה נבנית **לפני** בלנדר (``skinmaps.py`` על פייתון של
    המערכת, עם numpy ו-PIL שאינם בבלנדר המופץ), ולכן כאן רק
    טעינה. אם התיקייה חסרה או שקובץ לא נטען - חוזרים לחומר
    הפרוצדורלי ורושמים אזהרה, ולא מפילים ריצת רנדר שלמה בגלל
    טקסטורה.
    """
    if not folder:
        return None
    d = Path(folder)
    if not d.is_dir():
        log("מפות עור: אין תיקייה %s - חומר פרוצדורלי" % d)
        return None
    out = {}
    for key in ("albedo", "roughness", "normal"):
        p = d / ("skin_%s.png" % key)
        if not p.exists():
            continue
        try:
            img = bpy.data.images.load(str(p), check_existing=True)
            img.name = "skin_" + key
            # ארוזה בתוך ה-blend: בלי זה הנתיב נשאר חיצוני
            # והייצוא ל-glTF מאבד את הטקסטורה.
            try:
                img.pack()
            except Exception:                                # noqa: BLE001
                pass
            out[key] = img
        except Exception as e:                               # noqa: BLE001
            log("מפות עור: טעינת %s נכשלה (%s)" % (p.name, e))
    rep = d / "skin_source.json"
    if rep.exists():
        try:
            j = json.loads(rep.read_text(encoding="utf-8"))
            m = (j.get("metrics") or {}).get("albedo_mean")
            if m and len(m) == 3:
                out["mean"] = tuple(float(x) for x in m)
            out["license"] = j.get("license")
            out["source"] = j.get("source")
        except Exception as e:                               # noqa: BLE001
            log("מפות עור: דוח המקור לא נקרא (%s)" % e)
    if not out.get("albedo"):
        log("מפות עור: אין אלבדו - חומר פרוצדורלי")
        return None
    log("מפות עור: %s (%s), ממוצע %s"
        % (out.get("source"), out.get("license"), out.get("mean")))
    return out


def ensure_uv(ob) -> str:
    """מבטיח מפת UV לגוף. מחזיר את שם השכבה, או "" בכשל.

    חבילת הפיסול של Blender Studio מגיעה **בלי UV** - וזו הסיבה
    שהנכס המיוצא הצהיר ``images == 0``. טקסטורת תמונה בלי UV
    אינה אפשרית, ו-``Generated``/``Object`` כקואורדינטה מקרינים
    לפי שני צירים בלבד, כלומר מותחים את המפה לאורך כל הגפה.
    לכן Smart Project, שהוא פירוק לאיים לפי זווית פאות.

    ``island_margin`` גדול מאפס הוא חובה: איים נוגעים מדליפים
    פיקסלים זה לזה אחרי ה-subdivision, ועל עור זה נראה כקו.
    """
    if ob.data.uv_layers:
        return ob.data.uv_layers.active.name
    try:
        bpy.ops.object.select_all(action="DESELECT")
        ob.select_set(True)
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        try:
            # **89° ולא 66°, וזו החלטת זיכרון.** כל אי UV הוא
            # תפר, וכל תפר מכריח את ה-SUBSURF להעריך את משטח
            # הגבול בנפרד. ב-66° הפירוק נתן מאות איים, והסצנה
            # נהרגה בסנכרון Cycles (נמדד, ריצה 38525372548:
            # 10.6GB בלי מפות מול מוות עם מפות). זווית גדולה
            # נותנת פחות איים ומתיחה רבה יותר - ועל מרקם מיקרו
            # שחוזר 18 פעמים, מתיחה אינה נראית.
            bpy.ops.uv.smart_project(angle_limit=math.radians(89.0),
                                     island_margin=0.012)
        except TypeError:
            bpy.ops.uv.smart_project(island_margin=0.02)
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception as e:                                   # noqa: BLE001
        log("UV: Smart Project נכשל (%s)" % e)
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:                                    # noqa: BLE001
            pass
    if ob.data.uv_layers:
        log("UV: %s על %s" % (ob.data.uv_layers.active.name, ob.name))
        return ob.data.uv_layers.active.name
    log("UV: אין - מפות העור לא ייושמו על %s" % ob.name)
    return ""


def skin_material(name: str, tone, flush=(0.76, 0.33, 0.30),
                  maps=None, uvname: str = "", tile: float = 18.0,
                  detail: float = 0.92):
    """עור PBR: SSS + שלוש שכבות וריאציה כרומטית + נקבוביות.

    זה השיידר שאמור להזיז את ``chroma_std``. השכבות, מהגסה לדקה:

    1. **כתמי טון** - Noise scale 2.4: אזורי גוף חמים/קרים.
    2. **סומק** - Noise scale 9: אדמומיות מקומית (לחיים, כתפיים,
       מרפקים). זו השכבה שמכניסה הפרדת גוון אמיתית ולא רק
       בהירות, ולכן היא זו שנמדדת ב-a/b של Lab.
    3. **נקבוביות** - Voronoi scale 420 -> bump 0.0012. תדר גבוה
       שמייצר micro-shading; בלי זה המשטח קורא "פלסטיק" גם עם
       SSS מושלם.
    """
    mat = bpy.data.materials.new(name)
    nt, out = _nodes(mat)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 0)

    n1 = nt.nodes.new("ShaderNodeTexNoise")
    n1.location = (-700, 200)
    n1.inputs["Scale"].default_value = 2.4
    n1.inputs["Detail"].default_value = 6.0
    r1 = nt.nodes.new("ShaderNodeValToRGB")
    r1.location = (-500, 200)
    r1.color_ramp.elements[0].position = 0.35
    # הקצה הכהה של וריאציית הטון היה 80% מה-``tone``. בשרשרת
    # שמכפילה גם קאוויטי וגם אלבדו מצולם, כל מקדם כזה מצטבר -
    # ולכן כאן 0.90 ולא 0.80. וריאציה של 10% מספיקה כדי לשבור
    # אחידות; 20% כבר נקראת כצל.
    r1.color_ramp.elements[0].color = (tone[0] * 0.90, tone[1] * 0.91,
                                       tone[2] * 0.94, 1.0)
    r1.color_ramp.elements[1].position = 0.70
    r1.color_ramp.elements[1].color = (min(1.0, tone[0] * 1.10),
                                       tone[1] * 1.02, tone[2] * 0.95, 1.0)
    nt.links.new(n1.outputs["Fac"], r1.inputs["Fac"])

    n2 = nt.nodes.new("ShaderNodeTexNoise")
    n2.location = (-700, -60)
    n2.inputs["Scale"].default_value = 9.0
    n2.inputs["Detail"].default_value = 8.0
    r2 = nt.nodes.new("ShaderNodeValToRGB")
    r2.location = (-500, -60)
    r2.color_ramp.elements[0].position = 0.46
    r2.color_ramp.elements[0].color = (0, 0, 0, 1)
    r2.color_ramp.elements[1].position = 0.78
    r2.color_ramp.elements[1].color = (1, 1, 1, 1)
    nt.links.new(n2.outputs["Fac"], r2.inputs["Fac"])

    mx = nt.nodes.new("ShaderNodeMixRGB")
    mx.location = (-250, 100)
    mx.blend_type = "SOFT_LIGHT"
    # SOFT_LIGHT ב-Fac מלא היה עדין מדי אחרי ההבהרה והעור
    # קרא כגבס. ``r2`` כבר מגביל את האזור, ולכן העצמה כאן
    # רק מחזירה את החום לאותם אזורים.
    mx.inputs["Color2"].default_value = (*flush, 1.0)
    nt.links.new(r2.outputs["Color"], mx.inputs["Fac"])
    nt.links.new(r1.outputs["Color"], mx.inputs["Color1"])
    nt.links.new(mx.outputs["Color"], bsdf.inputs["Base Color"])

    vo = nt.nodes.new("ShaderNodeTexVoronoi")
    vo.location = (-700, -340)
    vo.inputs["Scale"].default_value = 420.0
    bp = nt.nodes.new("ShaderNodeBump")
    bp.location = (-250, -340)
    bp.inputs["Strength"].default_value = 0.30
    bp.inputs["Distance"].default_value = 0.0012
    nt.links.new(vo.outputs["Distance"], bp.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])

    # --- הצללת חריצים (cavity) לפי ``Pointiness`` של הגאומטריה.
    # זה התיקון לראש שנראה כגוש בפריים המבחן. הפנים **קיימות**
    # ברשת של Blender Studio - ארובות עיניים, קו לסת, קפלי
    # שפתיים - אבל בעור אחיד בלי צל מקומי אי אפשר לקרוא אותן.
    # ``Pointiness`` מחזיר קעירות מול קמירות לכל קודקוד, ולכן
    # הוא מכהה בדיוק את מה שחרוט ומבהיר את מה שבולט. הוא אינו
    # מצייר תווי פנים שאינם שם - הוא רק מפסיק להסתיר אותם.
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    geo.location = (-980, -660)
    # **כאן נולד העור האפרפר, וזו הייתה טעות חשבון ולא טעות טעם.**
    # ``Pointiness`` של רשת אורגנית מתפלג סביב 0.5, והרמפה
    # 0.42->0.56 מיפתה בדיוק את המרכז הזה אל אמצע הטווח שבין
    # 0.30 ל-1.0 - כלומר מקדם של כ-0.55 על **רוב** פני הגוף,
    # לא על חריצים. עם ``Fac=0.85`` זה חתך כמחצית מהבהירות של
    # העור כולו, וה-``tone`` הבהיר (0.93,0.78,0.68) הגיע אל
    # ה-AgX כ-(0.52,0.44,0.38) - עור כהה-אפרפר, בדיוק מה
    # שנמדד בפריים. הקאוויטי צריך לכהות **רק** את הזנב התחתון
    # של ההתפלגות: רצפה של 0.66 במקום 0.30, טווח צר יותר
    # שמוזז מטה, ו-Fac חצי. כך הקמט נשאר והעור לא נצבע.
    cav = nt.nodes.new("ShaderNodeValToRGB")
    cav.location = (-700, -660)
    cav.color_ramp.elements[0].position = 0.30
    cav.color_ramp.elements[0].color = (0.66, 0.58, 0.55, 1.0)
    cav.color_ramp.elements[1].position = 0.49
    cav.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
    base = mx
    if "Pointiness" in geo.outputs:
        nt.links.new(geo.outputs["Pointiness"], cav.inputs["Fac"])
        mul = nt.nodes.new("ShaderNodeMixRGB")
        mul.location = (-60, 60)
        mul.blend_type = "MULTIPLY"
        mul.inputs["Fac"].default_value = 0.45
        nt.links.new(mx.outputs["Color"], mul.inputs["Color1"])
        nt.links.new(cav.outputs["Color"], mul.inputs["Color2"])
        nt.links.new(mul.outputs["Color"], bsdf.inputs["Base Color"])
        base = mul

    rg = nt.nodes.new("ShaderNodeTexNoise")
    rg.location = (-700, -520)
    rg.inputs["Scale"].default_value = 22.0
    rr = nt.nodes.new("ShaderNodeMapRange")
    rr.location = (-450, -520)
    rr.inputs["To Min"].default_value = 0.38
    rr.inputs["To Max"].default_value = 0.62
    nt.links.new(rg.outputs["Fac"], rr.inputs["Value"])
    nt.links.new(rr.outputs["Result"], bsdf.inputs["Roughness"])

    # ------------------------------------------------- מפות עור מצולמות
    # **זו השכבה שבגללה השער נפל שלוש פעמים.** כל מה שמעל הוא
    # פרוצדורלי, ו-``quality_gate`` מודד בדיוק את מה שחסר בו:
    # אלבדו מצולם. המפות נבנות ב-``skinmaps.py`` מצילום CC0
    # בוויקישיתוף, ונטענות כאן כשלוש טקסטורות תמונה.
    #
    # ההרכבה אינה "להחליף את הצבע בצילום" אלא **חלוקה בממוצע**:
    # ``albedo / mean(albedo)`` הוא יחס סביב 1.0 שנושא את המיקרו
    # ואת הפסיפס הכרומטי בלבד, והכפלתו בבסיס הפרוצדורלי שומרת
    # את ה-``tone`` של הדמות במדויק. הדבקת הצילום עצמו הייתה
    # נותנת לשתי הדמויות את גון העור של אותו אדם.
    if maps and maps.get("albedo"):
        tc = nt.nodes.new("ShaderNodeTexCoord")
        tc.location = (-1700, -160)
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.location = (-1500, -160)
        mp.inputs["Scale"].default_value = (tile, tile, tile)
        nt.links.new(tc.outputs["UV"], mp.inputs["Vector"])

        def _tex(img, y, non_color):
            t = nt.nodes.new("ShaderNodeTexImage")
            t.location = (-1280, y)
            t.image = img
            t.extension = "REPEAT"
            # **Linear ולא Cubic.** ב-Cycles אינטרפולציה קובית
            # של תמונת 8 ביט אינה נתמכת בנתיב הבייטים, ולכן
            # התמונה מומרת ל-float4 - פי ארבעה זיכרון לכל מפה.
            # עם ``tile`` של 18 המפה ממילא דחוסה מאוד ביחס
            # לפיקסל, והפרש האיכות אינו נראה.
            t.interpolation = "Linear"
            if non_color:
                try:
                    img.colorspace_settings.name = "Non-Color"
                except Exception:                            # noqa: BLE001
                    pass
            nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
            return t

        ta = _tex(maps["albedo"], -160, False)
        mean = maps.get("mean") or (0.62, 0.62, 0.62)
        dv = nt.nodes.new("ShaderNodeMixRGB")
        dv.location = (-1040, -160)
        dv.blend_type = "DIVIDE"
        dv.inputs["Fac"].default_value = 1.0
        dv.inputs["Color2"].default_value = (max(1e-3, mean[0]),
                                             max(1e-3, mean[1]),
                                             max(1e-3, mean[2]), 1.0)
        nt.links.new(ta.outputs["Color"], dv.inputs["Color1"])
        pm = nt.nodes.new("ShaderNodeMixRGB")
        pm.location = (120, 150)
        pm.blend_type = "MULTIPLY"
        pm.inputs["Fac"].default_value = detail
        nt.links.new(base.outputs["Color"], pm.inputs["Color1"])
        nt.links.new(dv.outputs["Color"], pm.inputs["Color2"])
        nt.links.new(pm.outputs["Color"], bsdf.inputs["Base Color"])

        if maps.get("roughness"):
            tr = _tex(maps["roughness"], -820, True)
            mr = nt.nodes.new("ShaderNodeMapRange")
            mr.location = (-1040, -820)
            mr.inputs["To Min"].default_value = 0.30
            mr.inputs["To Max"].default_value = 0.64
            nt.links.new(tr.outputs["Color"], mr.inputs["Value"])
            nt.links.new(mr.outputs["Result"], bsdf.inputs["Roughness"])

        if maps.get("normal"):
            tn = _tex(maps["normal"], -1180, True)
            nm = nt.nodes.new("ShaderNodeNormalMap")
            nm.location = (-1000, -1180)
            nm.inputs["Strength"].default_value = 0.85
            if uvname:
                nm.uv_map = uvname
            nt.links.new(tn.outputs["Color"], nm.inputs["Color"])
            # הנורמל המצולם נכנס **לתוך** ה-bump של הנקבוביות
            # ולא במקומו: ``Bump`` מקבל נורמל בסיס ומסיט אותו.
            # ובמקביל עוצמת ה-Voronoi יורדת ל-0.08, אחרת אותן
            # נקבוביות נספרות פעמיים ומייצרות רעש מחזורי - בדיוק
            # מה שהוריד את ``sharp_detail`` במפה הפרוצדורלית.
            bp.inputs["Strength"].default_value = 0.08
            nt.links.new(nm.outputs["Normal"], bp.inputs["Normal"])

    # שמות קלטי ה-SSS השתנו בין 3.x ל-4.x. ניסיון לפי שם, ובלי
    # ליפול אם אחד מהם אינו קיים בגרסה שרצה.
    # SSS הועלה מ-0.22 ל-0.34 ורדיוס האדום מ-3.6 ל-5.4 מ"מ.
    # זה מה שנותן את ה"עומק" שהתבקש: אור שנכנס לעור, מתפזר
    # בתוכו ויוצא אדמדם בקצוות דקים (אוזניים, אצבעות, קו הלסת).
    # בעור בהיר האפקט ניכר יותר מאשר בכהה, ולכן ערך שהיה
    # מאוזן לטון הכהה הקודם קרא כפלסטיק אחרי ההבהרה.
    for key, val in (("Subsurface Weight", 0.34), ("Subsurface", 0.34)):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = val
            break
    for key in ("Subsurface Radius",):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = (0.054, 0.021, 0.013)
    for key, val in (("Subsurface Scale", 0.055),):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = val
    for key, val in (("Specular IOR Level", 0.42), ("Specular", 0.42)):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = val
            break
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def hair_material(name: str, col):
    mat = bpy.data.materials.new(name)
    nt, out = _nodes(mat)
    h = nt.nodes.new("ShaderNodeBsdfHairPrincipled")
    h.location = (300, 0)
    # **``parametrization`` חייב להיות COLOR.** ברירת המחדל היא
    # MELANIN, ואז הקלט ``Color`` קיים אבל **מתעלמים ממנו** -
    # וזה בדיוק מה שנמדד בפריים המבחן: שיער לבנבן בשתי הדמויות
    # למרות שהוגדרו חום וכמעט-שחור. הצבה שאינה נופלת ואינה
    # עובדת היא הסוג הגרוע, כי היא לא מופיעה בשום לוג.
    _set(h, parametrization="COLOR")
    for k, v in (("Color", (*col, 1.0)), ("Roughness", 0.34),
                 ("Radial Roughness", 0.42), ("Coat", 0.05)):
        if k in h.inputs:
            h.inputs[k].default_value = v
    # וריאציית גוון בין גדיל לגדיל: בלי זה השיער קורא כגוש אחד
    # צבוע. ``Random`` של Hair Info הוא ערך קבוע לכל גדיל, ולכן
    # הוא מפזר את הגוון בין גדילים ולא לאורך גדיל - וזה ההבדל
    # בין שיער לצבע.
    hi = nt.nodes.new("ShaderNodeHairInfo")
    hi.location = (-520, -200)
    hv = nt.nodes.new("ShaderNodeHueSaturation")
    hv.location = (-150, -60)
    hv.inputs["Color"].default_value = (*col, 1.0)
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.location = (-330, -200)
    mr.inputs["To Min"].default_value = 0.455
    mr.inputs["To Max"].default_value = 0.545
    if "Random" in hi.outputs:
        nt.links.new(hi.outputs["Random"], mr.inputs["Value"])
        nt.links.new(mr.outputs["Result"], hv.inputs["Hue"])
        if "Color" in h.inputs:
            nt.links.new(hv.outputs["Color"], h.inputs["Color"])
    nt.links.new(h.outputs[0], out.inputs["Surface"])
    return mat


def eye_material(name: str, fdir: float, iris=(0.19, 0.31, 0.37)):
    """גלגל עין: לובן + קשתית + אישון, לפי **הנורמל** ולא לפי UV.

    לחבילת הפיסול אין UV לעיניים ואין חומרים, ולכן בפריים המבחן
    הן רונדרו כגוש אפור בתוך הארובה - ומכאן חלק מהתחושה שלראש
    אין פנים. הנורמל של ספֵרה מצביע תמיד החוצה מהמרכז, ולכן
    רכיב ה-Y שלו הוא בדיוק "כמה הנקודה הזאת פונה קדימה": 1
    במרכז הקשתית ו-0 בצדדים. זה נותן עין נכונה בלי שום מפה.
    """
    mat = bpy.data.materials.new(name)
    nt, out = _nodes(mat)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.location = (300, 0)
    b.inputs["Roughness"].default_value = 0.10
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    geo.location = (-900, 0)
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-700, 0)
    nt.links.new(geo.outputs["Normal"], sep.inputs["Vector"])
    fwd = nt.nodes.new("ShaderNodeMath")
    fwd.location = (-520, 0)
    fwd.operation = "MULTIPLY"
    fwd.inputs[1].default_value = fdir
    nt.links.new(sep.outputs["Y"], fwd.inputs[0])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-330, 0)
    cr = ramp.color_ramp
    cr.interpolation = "CONSTANT"
    cr.elements[0].position = 0.0
    cr.elements[0].color = (0.74, 0.72, 0.70, 1.0)        # לובן
    cr.elements[1].position = 0.82
    cr.elements[1].color = (*iris, 1.0)                   # קשתית
    e3 = cr.elements.new(0.965)
    e3.color = (0.012, 0.010, 0.010, 1.0)                 # אישון
    nt.links.new(fwd.outputs["Value"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])
    return mat


def cloth_material(name: str, col, rough=0.72):
    mat = bpy.data.materials.new(name)
    nt, out = _nodes(mat)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.location = (300, 0)
    b.inputs["Base Color"].default_value = (*col, 1.0)
    b.inputs["Roughness"].default_value = rough
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.location = (-400, -300)
    n.inputs["Scale"].default_value = 260.0
    n.inputs["Detail"].default_value = 4.0
    bp = nt.nodes.new("ShaderNodeBump")
    bp.location = (-150, -300)
    bp.inputs["Strength"].default_value = 0.45
    bp.inputs["Distance"].default_value = 0.0018
    nt.links.new(n.outputs["Fac"], bp.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], b.inputs["Normal"])
    for k, v in (("Sheen Weight", 0.25), ("Sheen", 0.25)):
        if k in b.inputs:
            b.inputs[k].default_value = v
            break
    nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])
    return mat


# ----------------------------------------------------------------- שיער

def _set(obj, **kw):
    """מציב תכונות ומדווח על מה שאינו קיים בגרסה שרצה.

    נולד מכשל אמיתי (13/10, ריצה 38463176203): ``child_nbr`` הוסר
    מ-``ParticleSettings``, והסקריפט נפל אחרי שכבר בנה גוף, פיסל
    חזה ותפר בגד - 50 שניות ענן על שם תכונה. שמות ה-API של
    חלקיקים השתנו לרוחב בין 2.7 ל-4.2, ולכן **כל** הצבה כאן
    עוברת דרך כאן, ולא רק זו שנפלה.
    """
    missing = []
    for k, v in kw.items():
        if not hasattr(obj, k):
            missing.append(k)
            continue
        try:
            setattr(obj, k, v)
        except Exception as e:                               # noqa: BLE001
            missing.append("%s(%s)" % (k, e))
    if missing:
        log("    תכונות שאינן נתמכות ודולגו: %s" % ", ".join(missing))
    return missing


def add_hair(body, length: float, col, count=4200, children=16,
             density="scalp", shell_mat=None):
    """שיער כגאומטריה, לא כמשטח מוצק.

    מערכת חלקיקים ולא Curves: ב-4.2 ``curves_empty_hair_add`` דורש
    הקשר של ממשק ועריכה אינטראקטיבית כדי לצמוח, ו-``-b`` לא נותן
    אותו. מערכת חלקיקים מוגדרת כולה בנתונים, ולכן היא הדבר היחיד
    שאפשר לבנות בוודאות ב-``--background``.

    ``hair_length`` נשאר בינוני-קצר בכוונה: בלי סימולציית כבידה
    גדיל ארוך צומח לפי הנורמל ונותן "קיפוד". עם clump ו-kink,
    אורך 12-18 ס"מ קורא כשיער צמוד ואסוף.

    **``children`` הוא מספר הבנים לכל אם, לא סך הגדילים.** זה
    הפיל את הריצה 38464421809 ב-OOM (exit 137): 2600 אמהות ×
    9000 "בנים" הם 23.4 מיליון גדילים × 6 נקודות ≈ 140 מיליון
    נקודות, והרנר (16GB) נהרג בשלב בניית ה-BVH - אחרי שכל
    הסצנה כבר נבנתה בהצלחה, ולכן זה נראה כמו תקלת רינדור
    ולא כמו מספר שגוי. 3200 × 8 = 25,600 גדילים, שזה סדר הגודל
    שראש מרונדר באמת צריך.
    """
    md = body.modifiers.new("hair", "PARTICLE_SYSTEM")
    ps = body.particle_systems[-1]
    if density and density in [g.name for g in body.vertex_groups]:
        ps.vertex_group_density = density
    # **אורך לכל גדיל, ולא אורך אחיד.** ראה ``build_groups``:
    # זה מה שמונע מהמעטפת להיות כדור. השם חייב להתקיים על
    # האובייקט, אחרת בלנדר שותק והאורך נשאר אחיד - תקלה
    # שקטה מהסוג שמוצאים רק בפריים.
    if "hairlen" in [g.name for g in body.vertex_groups]:
        ps.vertex_group_length = "hairlen"
    else:
        log("    אזהרה: אין קבוצת hairlen - אורך השיער יישאר אחיד")
    s = ps.settings
    # **``clump_factor`` גבוה הוא מה שהופך קיפוד לתספורת.** בלי
    # סימולציית כבידה הגדיל צומח לפי נורמל הקרקפת, כלומר רדיאלית
    # החוצה - וזה מה שנמדד בפריים המבחן: הילה פרועה סביב הראש.
    # ``clump`` מושך כל בן אל קצה האם שלו, ולכן ערך 0.93 אוסף
    # את הגדילים לגוש צמוד שקורא כשיער. אורך קצר (7-9 ס"מ)
    # מקטין את המנוף של אותה בעיה בדיוק.
    _set(s, type="HAIR", count=count, hair_length=length, hair_step=5,
         use_hair_bspline=True, child_type="INTERPOLATED",
         rendered_child_count=children, child_percent=max(2, children // 2),
         # **הנפח הכדורי הוא חשבון של אורך, לא של סגנון.** ראש
         # הוא כדור ברדיוס 9 ס"מ, וגדיל שצומח 8 ס"מ לפי הנורמל
         # בונה כדור של 17 ס"מ - כלומר אפרו, בדיוק מה שנמדד.
         # ``child_length`` מקצר את הבנים ביחס לאמהות, ולכן
         # המעטפת החיצונית (שהיא מה שהעין רואה) נדחסת פנימה
         # בלי לדלל את השיער עצמו.
         # אחרי ``comb_hair`` הנפח כבר לא כדורי, ולכן אין עוד
         # צורך לדחוס את הבנים פנימה: 0.94 במקום 0.74 מחזיר
         # לשיער אורך אמיתי. ו-``clump`` ירד מ-0.97 ל-0.70 -
         # clump כמעט מלא על גדילים מסורקים אוסף הכול לקווצות
         # חדות שנראות כחבלים.
         # 0.66 ולא 0.76, ו-``clump`` 0.985 ולא 0.95: המעטפת
         # החיצונית היא מה שהעין קוראת כנפח, והבנים הם שבונים
         # אותה. ``clump`` כמעט מלא מושך כל בן אל קצה האם, ולכן
         # הנפח נקבע על ידי האמהות (שאורכן כבר מכוון לפי
         # ``hairlen``) ולא על ידי פיזור הבנים.
         child_length=0.66, child_radius=0.010,
         clump_factor=0.985, clump_shape=0.82,
         roughness_1=0.006, roughness_1_size=0.04,
         roughness_2=0.010, roughness_2_size=0.14,
         roughness_endpoint=0.004,
         # **``CURL`` נתן נפח כדורי.** תלתל סביב ציר הגדיל, על
         # גדילים שכולם צומחים רדיאלית מהקרקפת, מצטבר לכדור -
         # וזה מה שנמדד בפריים: "אפרו" ולא תספורת, שמשתפל על
         # המצח. ``WAVE`` מכופף את הגדיל במישור אחד, כלומר גל
         # רך שיורד במקום סליל שמתנפח. התדר הנמוך (1.7 מול 3.0)
         # הוא ההבדל בין גל לקפיץ.
         # משרעת 5.5 מ"מ ולא 11: ``kink`` מוסיף נפח בכל כיוון,
         # ועל גדיל שצומח רדיאלית מראש כדורי כל מילימטר שלו
         # מתווסף לרדיוס המעטפת.
         kink="WAVE", kink_amplitude=0.0055, kink_frequency=1.8,
         kink_shape=-0.30,
         root_radius=0.0085, tip_radius=0.0012, radius_scale=0.019,
         use_close_tip=True)
    # חומר השיער הוא הסלוט השני של הגוף.
    mi = len(body.data.materials)
    body.data.materials.append(hair_material("hair_" + body.name, col))
    s.material = mi + 1
    log("  שיער: %d אמהות × %d בנים = %d גדילים, אורך %.2fמ"
        % (count, children, count * children, length))
    return md


def hair_shell_material(name: str, col):
    """חומר לקליפת השיער: Principled אניזוטרופי, לא Hair BSDF.

    ``ShaderNodeBsdfHairPrincipled`` מחשב פיזור בתוך **גליל**,
    ולכן על משטח הוא קורא כפלסטיק רטוב. על מש התסרוקת צריך
    Principled עם ``Anisotropic`` גבוה: ההיילייט נמתח לאורך
    הטנגנט של המשטח, וזה בדיוק הברק הארוך שהעין מזהה כשיער.

    ה-Bump בתדר גבוה מאוד (Wave בקנה מידה 190) מצייר את
    הגדילים עצמם - זה מה שמונע מהקליפה להיראות ככובע.
    """
    mat = bpy.data.materials.new(name)
    nt, out = _nodes(mat)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.location = (400, 0)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-900, 0)
    # וריאציה בין גדיל לגדיל: בלונד אמיתי אינו צבע אחד אלא
    # תערובת של כמה גוונים. בלעדיה הראש נקרא כגוש צבוע.
    wv = nt.nodes.new("ShaderNodeTexWave")
    wv.location = (-700, 120)
    wv.wave_type = "BANDS"
    wv.bands_direction = "Z"
    wv.inputs["Scale"].default_value = 190.0
    wv.inputs["Distortion"].default_value = 9.0
    wv.inputs["Detail"].default_value = 5.0
    nt.links.new(tc.outputs["Object"], wv.inputs["Vector"])
    rp = nt.nodes.new("ShaderNodeValToRGB")
    rp.location = (-450, 120)
    rp.color_ramp.elements[0].position = 0.30
    rp.color_ramp.elements[0].color = (col[0] * 0.52, col[1] * 0.46,
                                       col[2] * 0.40, 1.0)
    rp.color_ramp.elements[1].position = 0.72
    rp.color_ramp.elements[1].color = (min(1.0, col[0] * 1.14),
                                       min(1.0, col[1] * 1.10),
                                       min(1.0, col[2] * 1.02), 1.0)
    nt.links.new(wv.outputs["Fac"], rp.inputs["Fac"])
    nt.links.new(rp.outputs["Color"], b.inputs["Base Color"])
    bp = nt.nodes.new("ShaderNodeBump")
    bp.location = (150, -260)
    bp.inputs["Strength"].default_value = 0.72
    bp.inputs["Distance"].default_value = 0.0016
    nt.links.new(wv.outputs["Fac"], bp.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], b.inputs["Normal"])
    b.inputs["Roughness"].default_value = 0.31
    for k, v in (("Anisotropic", 0.82), ("Anisotropic Rotation", 0.0),
                 ("Specular IOR Level", 0.55), ("Specular", 0.55),
                 ("Metallic", 0.0)):
        if k in b.inputs:
            b.inputs[k].default_value = v
    nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])
    return mat


def hair_shell(body, h: float, fdir: float, col, drop: float = 0.0,
               thick: float = 0.016, name: str = "hair_shell",
               fuzz: int = 6):
    """תסרוקת כ**גאומטריה**, ולא כגדילים שצומחים מהקרקפת.

    זו החלפת שיטה אחרי שהשיטה הקודמת מוצתה. גדיל חלקיקים צומח
    לפי הנורמל של הקרקפת, והקרקפת היא חצי כדור - ולכן התוצאה
    היא תמיד חצי כדור גדול יותר. ``clump``, ``kink``,
    ``child_length`` ו-``vertex_group_length`` כולם מעצבים את
    הגדיל **סביב** אותו כיוון ולא משנים אותו, ולכן ארבעה סבבי
    כוונון החזירו את אותו "אפרו".

    הכיוון ניתן לשינוי רק בכבידה (``use_hair_dynamics`` - בייק
    שביר ויקר ב-``-b``) או בסירוק ידני של ``hair_keys``. את
    השני **נמדד כאן שאי אפשר**: ב-4.2 ב-``-b``,
    ``particle_system.particles`` על האובייקט המקורי נשאר ריק
    גם אחרי ``disconnect_hair``/``connect_hair`` (שתיהן מחזירות
    ``FINISHED``), והחלקיקים קיימים רק על העותק המוערך - שאינו
    ניתן לכתיבה. נמדד בסקריפט בדיקה נפרד, לא נוחש.

    לכן התסרוקת נבנית כמשטח: קליפה שנגזרת מהראש עצמו (ולכן
    צמודה לו בדיוק), נדחקת החוצה, ואז **נמתחת מטה ואחורה** -
    כלומר הצורה היא הצורה, ולא תוצאה של כיוון צמיחה. זו גם
    הדרך שבה נבנה שיער בהפקות אמיתיות.

    בונוס שאינו צדדי: הזיכרון. 51,200 גדילים באורך 20 ס"מ
    הפילו את הרנדר המקומי ב-8.8GB על ``layerInterp_mdeformvert``.
    קליפה היא כ-3,000 פאות.
    """
    import bmesh                                             # noqa: PLC0415
    vs = vlist(body)
    # **מרכז הראש, ולא אפס.** זה הפיל את הניסיון הראשון:
    # ``build_groups`` מחשב ``front`` כ-``v.y*fdir/0.075``
    # בהנחה שהראש ממורכז ב-y=0, והוא אינו - הלוג מדווח
    # "עיניים y=0.026 מול ראש y=-0.074". לכן קודקודי **הפנים**
    # (y קרוב ל-0) קיבלו ``front=0``, כלומר נחשבו לעורף,
    # ונמתחו 27 ס"מ כלפי מטה. בפריים זה נראה כמסכה שמכסה
    # את כל הפנים - תקלה שנראית כבעיית חומר והיא בעיית מערכת
    # צירים. כאן המרכז נמדד מהקודקודים עצמם.
    hv = [v for v in vs if v.z / h > 0.880]
    cy = sum(v.y for v in hv) / max(1, len(hv))
    keep = set()
    for i, v in enumerate(vs):
        zr = v.z / h
        front = max(0.0, min(1.0, ((v.y - cy) * fdir) / 0.072))
        # הקליפה יורדת נמוך בעורף (0.858) ונסוגה גבוה בחזית
        # (0.950) - אותו היגיון של קו שיער אנושי שבקבוצת
        # ``scalp``, רק עם שוליים רחבים יותר כי כאן זה משטח
        # ולא נקודות צמיחה.
        # **חיתוך קשיח מול הפנים.** הניסיון הקודם הגדיר סף
        # גובה שמשתנה עם ``front``, והמתיחה שאחריו משכה את
        # הקודקודים האחוריים 27 ס"מ מטה בעוד הקדמיים קפואים -
        # ולכן **הפאות שחיברו ביניהם** נמתחו באלכסון על פני
        # הלחיים. בפריים זה נראה כמסכה שמכסה את כל הפנים, וזה
        # לא היה באג בבחירת הקודקודים אלא בטופולוגיה של המעבר.
        # כאן כל מה שמול קו הגבות נכלל רק אם הוא כמעט בכתר
        # (0.972), ולכן אין פאה שחוצה את הפנים מלכתחילה.
        fy = (v.y - cy) * fdir
        if fy > 0.030:
            if zr > 0.972:
                keep.add(i)
        elif zr > 0.858 + 0.070 * front:
            keep.add(i)
    if len(keep) < 60:
        log("  קליפת שיער: רק %d קודקודים - מבוטל" % len(keep))
        return None
    me = body.data.copy()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    doomed = [bm.verts[i] for i in range(len(bm.verts)) if i not in keep]
    bmesh.ops.delete(bm, geom=doomed, context="VERTS")
    bm.normal_update()
    lo = 0.858
    for v in bm.verts:
        # 1. עובי: דחיקה החוצה לאורך הנורמל של **הקליפה**
        #    (אחרי המחיקה), כדי שלא תחתוך את הגולגולת.
        v.co += v.normal * 0.013
        zr = v.co.z / h
        # רוחב מעבר 0.17 ולא 0.072: המתיחה משתנה בהדרגה על
        # פני **כל** עומק הראש, ולכן אין זוג קודקודים שכנים
        # שאחד מהם ירד 27 ס"מ והשני לא זז.
        front = max(0.0, min(1.0, ((v.co.y - cy) * fdir + 0.045) / 0.170))
        bk = 1.0 - front
        # tt: 1 בכתר, 0 בשפה התחתונה של הקליפה.
        tt = max(0.0, min(1.0, (zr - lo) / max(1e-6, 1.0 - lo)))
        # 2. **המתיחה.** רק הצד האחורי/הצדדי יורד, והשפה
        #    יורדת יותר מהכתר - כך נוצר וילון שנופל אל
        #    הכתפיים במקום כדור. הכתר זז מעט (0.45) כדי שקו
        #    הראש יישאר עגול ולא ישוטח.
        d = bk ** 1.15 * (1.0 - 0.55 * tt) * drop
        v.co.z -= d
        # 3. הרחבה: בלעדיה השיער נדבק לצוואר ונראה כצעיף.
        sp = 1.0 + 0.26 * bk * (1.0 - tt)
        v.co.x *= sp
        v.co.y -= fdir * 0.016 * bk
        # 4. גל רך - ההבדל בין תסרוקת לקסדה.
        v.co.x += 0.009 * math.sin(v.co.z * 34.0) * bk * (1.0 - tt)
        # 5. **חסם קו הפנים.** בחירת הקודקודים הייתה נכונה
        #    (נמדד ב-bbox: הקליפה מגיעה קדימה רק בכתר), אבל
        #    **אחרי** המתיחה קודקודים שישבו בצד הראש ירדו
        #    27 ס"מ ועברו מול הלחי והסנטר - ולכן הפריים הראה
        #    גוש שמכסה מהאף ומטה. כאן אין עוד מה לנחש: כל מה
        #    שנמצא מתחת לגובה העיניים נדחף אל **מאחורי** מרכז
        #    הראש, בלי תלות באיך הוא הגיע לשם. שיער שיורד
        #    לכתפיים יורד מאחור ומהצדדים, לא על הפנים.
        if v.co.z / h < 0.955:
            cap = -0.020
            fy2 = (v.co.y - cy) * fdir
            if fy2 > cap:
                v.co.y = cy + fdir * cap
    bm.to_mesh(me)
    bm.free()
    for g in body.vertex_groups:
        ob.vertex_groups.new(name=g.name)
    arm_src = next((m.object for m in body.modifiers
                    if m.type == "ARMATURE" and m.object), None)
    if arm_src:
        am = ob.modifiers.new("arm", "ARMATURE")
        am.object = arm_src
    # **הפאזז נכנס כאן, לפני Solidify ו-SUBSURF.** הוספתו
    # אחריהם הפילה את הרנדר ב-OOM (8GB): הגדילים התאינטרפלו
    # על רשת של כ-110 אלף פאות במקום על 3,400. אותה מלכודת
    # בדיוק שמתועדת ב-``build`` לגבי שיער הגוף - ונפלתי בה
    # שוב כי הפעם הרשת הייתה של אובייקט אחר.
    if fuzz:
        add_hair(ob, 0.021, col, count=1400,
                 children=max(3, fuzz), density=None)
    if thick > 0:
        sol = ob.modifiers.new("thick", "SOLIDIFY")
        sol.thickness = thick
        sol.offset = 1.0
    sub = ob.modifiers.new("sub", "SUBSURF")
    sub.levels = 0
    # רמה 1 ולא 2: הקליפה כבר צפופה (3,400 קודקודים על שטח
    # של ראש), ורמה שנייה מרבעת אותה בלי הבדל נראה.
    sub.render_levels = 1 if thick > 0 else 0
    ob.data.materials.clear()
    ob.data.materials.append(hair_shell_material(name + "_mat", col))
    for p in ob.data.polygons:
        p.use_smooth = True
    log("  קליפת שיער %s: %d קודקודים, מתיחה %.0f ס\"מ"
        % (name, len(me.vertices), drop * 100))
    return ob


def comb_hair(body, fdir: float, down: float = 0.86, back: float = 0.42):
    """מסרק את גדילי האם כלפי מטה ואחורה. **נמדד כבלתי אפשרי ב-``-b``.**

    נשאר בקוד כתיעוד של מה שנבדק ונפסל: ראה ``hair_shell``.
    ``ps.particles`` ריק ב-background, ולכן הלולאה כאן אינה
    רצה אף פעם. הפונקציה מדווחת ואינה נופלת.

    ``clump``, ``kink`` ו-``child_length`` כולם מעצבים את הגדיל
    סביב **הכיוון שבו הוא כבר צומח**, והכיוון הזה הוא הנורמל
    של הקרקפת - כלומר רדיאלי החוצה מכדור. לכן ארבעה סבבים של
    כוונון פרמטרים החזירו את אותו אפרו: הם תיקנו את העובי ולא
    את הכיוון. הכבידה היא מה שחסר, ו-``use_hair_dynamics``
    דורש סימולציה ובייק - עשרות שניות ושבירות ב-``-b``.

    הפתרון כאן הוא לכתוב ישירות ל-``hair_keys``, שהוא מה
    שעורך-החלקיקים עושה כשמסרקים ביד. זה **עובד ב-background**
    כי אלה נתונים ולא פעולת ממשק, והבנים (``INTERPOLATED``)
    מתאינטרפלים מההורים - ולכן סירוק 3,200 אמהות מסרק גם את
    51,200 הבנים בלי לגעת באף אחד מהם.

    שתי מלכודות שנפלתי בהן:

    1. ``ps.particles`` ריק עד ש-depsgraph מעריך את המערכת.
       בלי ``view_layer.update()`` ו-``evaluated_depsgraph_get()``
       הלולאה פשוט לא רצה, והפונקציה "מצליחה" בלי לעשות דבר.
    2. כל שינוי ב-``ps.settings`` **אחרי** הסירוק מאפס את
       המפתחות. לכן הקריאה הזו חייבת להיות אחרונה בשרשרת
       בניית הדמות, אחרי ה-SUBSURF ואחרי הבגד.

    ``co`` הוא במרחב האובייקט. השורש (מפתח 0) אינו זז לעולם -
    הזזתו הייתה מנתקת את השיער מהקרקפת.
    """
    bpy.context.view_layer.update()
    try:
        bpy.context.evaluated_depsgraph_get()
    except Exception as e:                                   # noqa: BLE001
        log("    סירוק: אין depsgraph (%s)" % e)
        return 0
    moved = 0
    for ps in body.particle_systems:
        if ps.settings.type != "HAIR":
            continue
        parts = ps.particles
        if not len(parts):
            log("    סירוק: אין חלקיקים ב-%s - דילוג" % ps.name)
            continue
        for p in parts:
            ks = p.hair_keys
            n = len(ks)
            if n < 2:
                continue
            root = ks[0].co.copy()
            # כיוון הצמיחה המקורי של הגדיל = הנורמל של הקרקפת.
            d0 = (ks[n - 1].co - root)
            if d0.length < 1e-6:
                continue
            d0.normalize()
            # היעד: מטה, ומעט אחורה. הרכיב האופקי של הנורמל
            # נשמר ב-45% כדי שהשיער לא יתקבץ לקווצה אחת -
            # גדיל מהצד נופל אל הצד, וגדיל מהעורף אל העורף.
            tgt = mathutils.Vector((d0.x * 0.45, -fdir * back, -1.0))
            if tgt.length < 1e-6:
                continue
            tgt.normalize()
            for j in range(1, n):
                t = j / (n - 1.0)
                v = ks[j].co - root
                ln = v.length
                if ln < 1e-7:
                    continue
                # ``t**1.6``: השורש כמעט אינו זז (השיער יוצא
                # מהקרקפת בזווית טבעית) והקצה נופל כמעט לגמרי.
                # ערך לינארי היה מכופף את הגדיל כבר במילימטר
                # הראשון ונותן מראה של שיער מודבק לגולגולת.
                w = down * (t ** 1.6)
                nd = (v / ln) * (1.0 - w) + tgt * w
                if nd.length < 1e-7:
                    continue
                nd.normalize()
                ks[j].co = root + nd * ln
            moved += 1
    log("  סירוק שיער: %d גדילי אם הוטו מטה (down=%.2f back=%.2f)"
        % (moved, down, back))
    return moved


# --------------------------------------------------------------- בגדים

def make_garment(body, idx: dict, name: str, mat, thick=0.0035,
                 offset=0.0022):
    """בגד = עותק של תת-אזור הגוף, נדחק חוצה ומקבל עובי.

    זו הדרך היחידה כאן לבגד **צמוד ומדויק** בלי סימולציה: הבגד
    הוא בדיוק המשטח שהוא מכסה, ולכן אין חדירה ואין רווח. העובי
    הוא ``Solidify`` וה"דחיקה חוצה" היא ``Shrinkwrap``-בלי-מטרה,
    כלומר הזזה לאורך הנורמל.
    """
    me = body.data.copy()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    keep = set(idx)
    bm_del = [v for i, v in enumerate(me.vertices) if i not in keep]
    # מחיקה דרך bmesh: מחיקת קודקודים ישירות מ-mesh אינה API.
    import bmesh                                             # noqa: PLC0415
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    doomed = [bm.verts[i] for i in range(len(bm.verts)) if i not in keep]
    bmesh.ops.delete(bm, geom=doomed, context="VERTS")
    # **אחרי** המחיקה. נורמל של קודקוד שאיבד חצי מהפאות שלו הוא
    # נורמל אחר, ודחיקה לפי הנורמל הישן הייתה פותחת את הבגד
    # בשוליים בדיוק במקום שהוא צריך להיות צמוד.
    bm.normal_update()
    for v in bm.verts:
        v.co += v.normal * offset
    bm.to_mesh(me)
    bm.free()
    if len(me.vertices) < 50:
        log("  בגד %s: פחות מ-50 קודקודים - מבוטל" % name)
        bpy.data.objects.remove(ob, do_unlink=True)
        return None
    # שמות קבוצות הקודקודים מועתקים **באותו סדר**. משקלי
    # הדפורמציה נשמרים בתוך ה-mesh ומועתקים עם ``data.copy()``,
    # אבל רשימת השמות יושבת על האובייקט. בלי זה ה-ARMATURE על
    # הבגד רץ על קבוצות ריקות, הבגד נשאר קפוא בעוד הגוף נושם,
    # והראש שמסתובב מושך את הגוף מתוך הבגד.
    for g in body.vertex_groups:
        ob.vertex_groups.new(name=g.name)
    arm_src = next((m.object for m in body.modifiers
                    if m.type == "ARMATURE" and m.object), None)
    if arm_src:
        am = ob.modifiers.new("arm", "ARMATURE")
        am.object = arm_src
    sol = ob.modifiers.new("thick", "SOLIDIFY")
    sol.thickness = thick
    sol.offset = 1.0
    sub = ob.modifiers.new("sub", "SUBSURF")
    sub.levels = 0
    sub.render_levels = 2
    ob.data.materials.clear()
    ob.data.materials.append(mat)
    for p in ob.data.polygons:
        p.use_smooth = True
    log("  בגד %s: %d קודקודים" % (name, len(me.vertices)))
    return ob


# ------------------------------------------------------------------ סצנה

def world_hdri(hdri: Path, rot_deg: float = 118.0, strength: float = 1.0):
    """HDRI מצולם במקום שמי Nishita פרוצדורליים.

    זה, ולא השיידר, הוא מקור הכרומה הגדול בשוט: תמונת סביבה
    אמיתית מכניסה שמי תכלת-אפור מדורגים, אור מוחזר מהחול וגוון
    חם בקו האופק - שלושה מקורות צבע שונים על אותו משטח. שמי
    Nishita נותנים גרדיאנט אחד חלק, ומכאן ``chroma_std`` 0.22.
    """
    w = bpy.data.worlds.new("beach")
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = strength
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(str(hdri))
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value = (0, 0, math.radians(rot_deg))
    tc = nt.nodes.new("ShaderNodeTexCoord")
    nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], env.inputs["Vector"])
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])

    # --- **מה שהמצלמה רואה אינו מה שמאיר.**
    #
    # ``fish_hoek_beach`` הוא מפרץ: צד אחד ים פתוח, הצד השני
    # עיירה על מדרון. בפריים המבחן של 14/10 העיירה **היא** כל
    # הרקע - שורות בתים, דקלים ומכוניות מעל קו המים - ולכן
    # הים נקרא כפס אפור בין החול לעיירה, ושום תיקון בשיידר
    # המים לא יכול היה לעזור: הבעיה לא הייתה הצבע אלא מה
    # שמאחוריו.
    #
    # סיבוב ה-HDRI אינו פתרון: הוא תלוי בתוכן של תמונה
    # מסוימת, ובכל החלפת HDRI צריך לכייל אותו מחדש בעיניים -
    # כלומר עוד סבב ענן לכל שינוי.
    #
    # הפתרון שאינו תלוי בתוכן: ``Is Camera Ray``. קרן מצלמה
    # רואה שמי Nishita נקיים; **כל** שאר הקרניים (תאורה,
    # השתקפות, SSS) ממשיכות לראות את ה-HDRI המצולם, ולכן
    # האור על העור, הצל והגוון החם באופק נשארים בדיוק כפי
    # שהיו - וזה המקור של ``chroma_std`` שנמדד כאן.
    # ההשתקפות במים אף משתפרת: היא ממשיכה להיות של סביבה
    # אמיתית ולא של גרדיאנט.
    sky = nt.nodes.new("ShaderNodeTexSky")
    for attr, val in (("sky_type", "NISHITA"),
                      # 52° ולא 34°: הקאדר הוא גוף-מלא, כלומר
                      # המצלמה רואה רק רצועה דקה של שמיים ממש
                      # מעל האופק. עם שמש נמוכה הרצועה הזאת היא
                      # בדיוק אזור הפיזור הקדמי - לבן בוהק -
                      # ובפריים המבחן היא יצאה כלוח לבן. שמש
                      # גבוהה מרחיקה את הבוהק מהקאדר ומשאירה שם
                      # תכלת.
                      ("sun_elevation", math.radians(52.0)),
                      ("sun_rotation", math.radians(132.0)),
                      ("sun_disc", False),
                      ("altitude", 0.0),
                      # צפיפות **נמוכה** מ-1, לא גבוהה. יותר
                      # אוויר ויותר אבק = יותר פיזור מרובה =
                      # אופק לבן יותר. 0.72/0.25 נותנים אוויר
                      # ים נקי שבו האופק עוד תכול.
                      ("air_density", 0.72),
                      ("dust_density", 0.25),
                      ("ozone_density", 1.6)):
        try:
            setattr(sky, attr, val)
        except (AttributeError, TypeError):
            continue
    bg2 = nt.nodes.new("ShaderNodeBackground")
    bg2.inputs["Strength"].default_value = 1.0
    nt.links.new(sky.outputs["Color"], bg2.inputs["Color"])
    lp = nt.nodes.new("ShaderNodeLightPath")
    mx = nt.nodes.new("ShaderNodeMixShader")
    # Fac=0 -> קלט ראשון. ``Is Camera Ray`` הוא 1 בקרן מצלמה,
    # ולכן ה-HDRI יושב בקלט הראשון (תאורה) והשמיים בשני (ראייה).
    nt.links.new(lp.outputs["Is Camera Ray"], mx.inputs["Fac"])
    nt.links.new(bg.outputs["Background"], mx.inputs[1])
    nt.links.new(bg2.outputs["Background"], mx.inputs[2])
    nt.links.new(mx.outputs["Shader"], out.inputs["Surface"])
    log("HDRI: %s (סיבוב %.0f°) + שמי Nishita לקרן מצלמה"
        % (hdri.name, rot_deg))


def add_sun(elev=38.0, azim=132.0, energy=2.1, angle_deg=0.90):
    """שמש חדה **לצד** ה-HDRI.

    ה-HDRI לבדו נותן אור רך; רך הוא בדיוק מה שהפיל את
    ``sharp_detail`` ביחס 0.944. זווית 0.9° (השמש האמיתית היא
    0.53°) משאירה צל עם קצה מוגדר אבל לא חותך.
    """
    d = bpy.data.lights.new("sun", type="SUN")
    d.energy = energy
    d.angle = math.radians(angle_deg)
    d.color = (1.0, 0.957, 0.898)
    ob = bpy.data.objects.new("sun", d)
    bpy.context.scene.collection.objects.link(ob)
    ob.rotation_euler = (math.radians(90.0 - elev), 0.0,
                         math.radians(azim))
    return ob


def plane(name, size, loc, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_plane_add(size=size, location=loc, rotation=rot)
    ob = bpy.context.active_object
    ob.name = name
    return ob


def sand_plane(name="sand", size=120.0, loc=(0.0, -55.0, 0.0), cuts=190):
    """מישור החול, **עם גאומטריה ולא רק עם שיידר**.

    עד כאן החול היה ``primitive_plane_add`` - ארבעה קודקודים.
    מישור בארבעה קודקודים אינו מטיל צל על עצמו ואין לו קו אופק
    משתנה, ולכן הוא נקרא כרצפה יצוקה גם כשהשיידר שעליו מושלם.
    זו הייתה הטעות ששרדה שלושה סבבים: כל התיקונים נעשו בצבע,
    והבעיה הייתה בצורה.

    ``grid`` של 150×150 על 120 מטר הוא תא של 80 ס"מ, ו-``Displace``
    עם ענן בקנה מידה גדול מרים ממנו דיונות רכות של 4-12 ס"מ.
    22,500 פאות הן כאחוז אחד מתקציב הסצנה (הדמויות לבדן הן 21
    אלף קודקודים לפני החלוקה), ולכן זה זול בזיכרון - והוא
    הדבר היחיד שנותן **צל אמיתי** על החול, מה ש-Bump לעולם
    לא ייתן כי הוא מטה נורמל ואינו מזיז משטח.
    """
    bpy.ops.mesh.primitive_grid_add(size=size, x_subdivisions=cuts,
                                    y_subdivisions=cuts, location=loc)
    ob = bpy.context.active_object
    ob.name = name
    tex = bpy.data.textures.new("sand_dunes", type="CLOUDS")
    # 6.5 מטר: סדר הגודל של שקע/תלולית בחוף דרוך. קטן מזה
    # נבלע בתא הגריד, גדול מזה נראה כגבעה ולא כחול.
    tex.noise_scale = 6.5
    tex.noise_depth = 4
    d = ob.modifiers.new("dunes", "DISPLACE")
    d.texture = tex
    d.texture_coords = "GLOBAL"
    d.strength = 0.115
    # **``mid_level`` חייב להיות 0, לא 0.5.** עם 0.5 ההזזה היא
    # ``strength*(tex-0.5)``, כלומר **חצי מהחול יורד מתחת
    # לאפס** - ומישור המים יושב ב-``z=-0.02``. בפריים המבחן
    # הראשון זה נראה כאילו החול "נעלם": רוב המישור שקע מתחת
    # לפני הים ונותר כתם מוזהב בודד במקום שבו הדיונה הזדמנה
    # לעלות. התקלה נראית כמו בעיית שיידר והיא בעיית גובה.
    # עם 0, ההזזה היא ``strength*tex`` - תמיד כלפי מעלה.
    d.mid_level = 0.0
    # שכבה שנייה, דקה וצפופה: אדוות הרוח. הן מה שהעין קוראת
    # כ"חול" ולא כ"אדמה", והן חייבות להיות בגאומטריה כי הכיווניות
    # שלהן יוצרת פס צל וpס אור לסירוגין מול שמש נמוכה.
    tex2 = bpy.data.textures.new("sand_ripples", type="WOOD")
    tex2.noise_basis_2 = "SIN"
    tex2.wood_type = "BANDNOISE"
    # **1.55 מטר ולא 60 ס"מ.** האדוות הן הדבר היחיד שמפריד
    # חול מרצפה, והן היו מתחת לסף הפתרון: 60 ס"מ במרחק 12
    # מטר בעדשת 85mm על 960 פיקסלים הם כ-5 פיקסלים לתקופה
    # שלמה, וה-denoiser (שמטרתו למחוק תדר גבוה) מחק אותן.
    # זה מדויק גם לגבי השיידר - שתי השכבות הוגדלו יחד.
    # 0.62 מטר ולא 1.55. ב-1.55 האדווה רחבה מדי כדי להטיל פס
    # צל בשמש של 38°: המדרון שלה מתון, והתוצאה בפריים היא
    # גרדיאנט רך שנקרא כמשטח חלק. 62 ס"מ עם אותו עומק (5.8
    # ס"מ) הוא מדרון תלול פי 2.5, וזה מה שמייצר את פס האור/צל
    # לסירוגין שהעין קוראת כחול.
    tex2.noise_scale = 0.62
    tex2.turbulence = 1.8
    d2 = ob.modifiers.new("ripples", "DISPLACE")
    d2.texture = tex2
    d2.texture_coords = "GLOBAL"
    # 5.8 ס"מ ולא 2.2: עומק אדווה אמיתית בחוף. זה מה שמטיל
    # פס צל מול שמש ב-38 מעלות, וצל הוא מה שהעין קוראת
    # כמרקם. Bump לעולם לא ייתן אותו.
    d2.strength = 0.058
    d2.mid_level = 0.0
    for p in ob.data.polygons:
        p.use_smooth = True
    log("  חול: גריד %d×%d, %d פאות, דיונות+אדוות בגאומטריה"
        % (cuts, cuts, len(ob.data.polygons)))
    return ob


def sand_material():
    """חול ים מוזהב - **בסקאלות שהמצלמה רואה**.

    ארבעה סבבים ניסו לתקן את "המשטח האפור השטוח" בצבע, וכולם
    נכשלו מאותה סיבה: ``Noise Scale=14`` בקואורדינטות מטר הוא
    תקופה של **7 ס"מ**. במצלמת 85mm על 960×540, פיקסל אחד על
    החול שבעשרה מטר מכסה כ-12 ס"מ. כלומר כל תקופה שלמה של
    המרקם נופלת בתוך פיקסל אחד, Cycles ממצע אותה, והתוצאה היא
    בדיוק הממוצע של ה-ColorRamp - צבע אחד, בכל הפריים. מרקם
    שאינו נראה אינו קיים, וזה אינו באג בשיידר אלא בתדר.

    לכן כאן ההיררכיה הפוכה ומפורשת, מהגס לדק:

    ===============  ============  =========================
    שכבה             תקופה          מה היא נותנת
    ===============  ============  =========================
    אזורי לחות        ~6 מטר        חול רטוב כהה ליד המים
    דיונות/שקעים      ~1.4 מטר      שבירת טון רחבה
    אדוות רוח         ~35 ס"מ       **הפירוט שהעין רואה**
    גרגר              ~4 ס"מ        מיקרו, עובד רק בחזית
    ===============  ============  =========================

    השכבה שמכריעה היא האדוות: 35 ס"מ הם כשלושה פיקסלים במרחק
    בינוני, כלומר מעל סף הפתרון, ולכן הן שורדות את הממוצע.

    הדבר השני: **AgX מוחק רוויה.** ``view_transform=AgX`` עם
    ``exposure=-0.62`` מגלגל גוונים חמים אל הניטרלי - זו המטרה
    שלו, והיא נכונה לעור. חול בז' "נכון" פיזיקלית יוצא ממנו
    אפור. התיקון אינו לשנות את החשיפה הגלובלית (היא מכוילת
    לעור) אלא להזריק רוויה **לחומר הזה בלבד**, דרך
    ``HueSaturation`` לפני ה-BSDF.

    והשלישי: ``Roughness`` קבוע 0.90 הוא חול יבש בכל מקום. חול
    רטוב הוא ``Roughness`` 0.2 - הוא מחזיר את השמיים ומבריק,
    וזה הסימן החזותי מספר אחת שמפריד חוף מרצפה.
    """
    mat = bpy.data.materials.new("sand")
    nt, out = _nodes(mat)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.location = (900, 0)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-1500, 0)
    # ``Object`` ולא ``Generated``: Object הוא מטרים ונשאר נכון
    # גם אם המישור יגדל. Generated הוא 0..1 על ה-bbox, ולכן כל
    # שינוי בגודל המישור היה משנה את כל התדרים בבת אחת.
    src = tc.outputs["Object"]

    def noise(scale, detail, y, rough=0.55, dim="3D"):
        n = nt.nodes.new("ShaderNodeTexNoise")
        n.location = (-1250, y)
        n.noise_dimensions = dim
        n.inputs["Scale"].default_value = scale
        n.inputs["Detail"].default_value = detail
        if "Roughness" in n.inputs:
            n.inputs["Roughness"].default_value = rough
        nt.links.new(src, n.inputs["Vector"])
        return n

    def ramp(src_out, y, p0, c0, p1, c1):
        r = nt.nodes.new("ShaderNodeValToRGB")
        r.location = (-1000, y)
        r.color_ramp.elements[0].position = p0
        r.color_ramp.elements[0].color = (*c0, 1.0)
        r.color_ramp.elements[1].position = p1
        r.color_ramp.elements[1].color = (*c1, 1.0)
        nt.links.new(src_out, r.inputs["Fac"])
        return r

    def mix(y, fac_out, c1_out, color2, blend="MIX", fac=None):
        m = nt.nodes.new("ShaderNodeMixRGB")
        m.location = (-700, y)
        m.blend_type = blend
        if color2 is not None:
            m.inputs["Color2"].default_value = (*color2, 1.0)
        if fac_out is not None:
            nt.links.new(fac_out, m.inputs["Fac"])
        elif fac is not None:
            m.inputs["Fac"].default_value = fac
        if c1_out is not None:
            nt.links.new(c1_out, m.inputs["Color1"])
        return m

    # --- 1. בסיס: דיונות רחבות, תקופה ~1.4 מטר.
    #     הצבעים חמים ורוויים בכוונה; AgX יוריד מהם, ואם מתחילים
    #     מבז' "מדויק" מסיימים באפור.
    dune = noise(0.72, 5.0, 320, rough=0.48)
    dune_r = ramp(dune.outputs["Fac"], 320,
                  0.26, (0.398, 0.280, 0.140),
                  0.76, (0.790, 0.678, 0.472))

    # --- 2. אדוות רוח: **השכבה שמכריעה**. תקופה ~35 ס"מ.
    #     Noise מתוח בציר אחד דרך Mapping נותן פסים מכווננים
    #     ולא כתמים - כך נראות אדוות שנוצרו מרוח בכיוון אחד.
    rip_map = nt.nodes.new("ShaderNodeMapping")
    rip_map.location = (-1400, 60)
    # **הכיוון היה הפוך.** ``Scale=(1.0,0.22,1.0)`` דוחס את ציר
    # Y, כלומר מותח את המרקם **לאורך** Y - פסים שרצים מהמצלמה
    # אל הים. אדוות חול נוצרות מגל ומרוח שמגיעים מהים, ולכן הן
    # רצות **במקביל לקו המים**, כלומר לאורך X. הדחיסה עוברת
    # ל-X, והסיבוב של 17° משאיר אותן אלכסוניות מעט כמו בחוף
    # אמיתי ולא כמו שרטוט.
    rip_map.inputs["Scale"].default_value = (0.22, 1.0, 1.0)
    rip_map.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(17.0))
    nt.links.new(src, rip_map.inputs["Vector"])
    rip = nt.nodes.new("ShaderNodeTexNoise")
    rip.location = (-1250, 60)
    # 1.05 במקום 2.85: תקופה של כמטר במקום 35 ס"מ. ראה
    # ``sand_plane`` - אותו שיקול בדיוק, וחייבים שהשניים
    # יהיו באותו קנה מידה אחרת הצבע והצורה נלחמים.
    # 1.6 ולא 1.05: תקופה של 63 ס"מ במקום 95. במרחק 10 מטר
    # פיקסל הוא ~12 ס"מ, כלומר 63 ס"מ הם כחמישה פיקסלים -
    # מעל סף הפתרון ומתחת לסף שבו האדווה נראית כגבעה. הערך
    # חייב להתאים ל-``sand_plane`` (שם 0.62 מטר), אחרת הצבע
    # והצורה מתארים שתי אדוות שונות ומבטלים זה את זה.
    rip.inputs["Scale"].default_value = 1.6
    rip.inputs["Detail"].default_value = 8.0
    rip.inputs["Roughness"].default_value = 0.42
    nt.links.new(rip_map.outputs["Vector"], rip.inputs["Vector"])
    # טווח צר יותר = ניגודיות גבוהה יותר בין שיא האדווה
    # לשקע שלה. 0.38-0.62 נתן מעבר רך שהתמזג לממוצע אחד.
    rip_r = ramp(rip.outputs["Fac"], 60,
                 0.40, (0.330, 0.238, 0.126),
                 0.60, (0.898, 0.800, 0.592))
    base = mix(160, None, dune_r.outputs["Color"], None,
               blend="OVERLAY", fac=0.56)
    nt.links.new(rip_r.outputs["Color"], base.inputs["Color2"])

    # --- 3. גרגר דק. מועיל רק בחזית הקאדר, ולכן משקלו נמוך -
    #     אבל הוא מה שמונע "פלסטיק" במטר הראשון.
    # 26 בקואורדינטות מטר = תקופה של 3.8 ס"מ, כלומר הרבה
    # מתחת לפיקסל בכל מקום בפריים חוץ מהמטר הראשון. 9.5
    # הוא 10.5 ס"מ - גרגר גס שעוד נקרא.
    grain = noise(9.5, 10.0, -180, rough=0.70)
    grain_r = ramp(grain.outputs["Fac"], -180,
                   0.40, (0.66, 0.57, 0.42),
                   0.60, (0.94, 0.89, 0.79))
    g_mix = mix(-120, None, base.outputs["Color"], None,
                blend="SOFT_LIGHT", fac=0.40)
    nt.links.new(grain_r.outputs["Color"], g_mix.inputs["Color2"])

    # --- 3ב. **שבירת טון במאקרו, ~14 מטר.** כל ארבע השכבות עד
    #     כאן הן מטר ומטה, ולכן ברוחב הקאדר (כ-7 מטר בחזית,
    #     עשרות באחורה) הן ממוצעות לטון אחד - וזה מה שנראה
    #     בפריים: שטיח כתום אחיד. חוף אמיתי משנה גוון בקנה
    #     מידה של עשרות מטרים (לחות שנותרה, חול שהרוח הביאה,
    #     צל של דיונה). תקופה של 14 מטר היא מאות פיקסלים -
    #     היא לעולם אינה נמחקת בדגימה.
    macro = noise(0.072, 3.0, -1020, rough=0.42)
    macro_r = ramp(macro.outputs["Fac"], -1020,
                   0.30, (0.565, 0.470, 0.330),
                   0.72, (0.960, 0.905, 0.760))
    m_mix = mix(-960, None, g_mix.outputs["Color"], None,
                blend="OVERLAY", fac=0.34)
    nt.links.new(macro_r.outputs["Color"], m_mix.inputs["Color2"])
    g_mix = m_mix

    # --- 4. לחות - **לפי המרחק מקו המים, לא לפי רעש**.
    #
    #     רעש אקראי פיזר כתמים רטובים על כל החוף, כולל במקומות
    #     שהים מעולם לא הגיע אליהם. חול רטוב אינו תופעה אקראית:
    #     הוא רצועה שצמודה לקו המים, ועומקה הוא עד לאן שהגל
    #     האחרון הגיע. ``Object`` ב-Y הוא המרחק מהמים במטרים
    #     (המישור הוא ±60 סביב מרכזו, והקצה הקדמי פונה לים),
    #     ולכן ``MapRange`` עליו נותן בדיוק רצועה.
    #
    #     הרעש לא נזרק - הוא **מופרע** לגבול, ברוחב של כמטר,
    #     כדי שהרצועה לא תהיה קו ישר. זה ההבדל בין קו מים
    #     לקו שרטוט.
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-1250, -420)
    nt.links.new(src, sep.inputs["Vector"])
    wn = noise(0.42, 4.0, -560, rough=0.50)
    jit = nt.nodes.new("ShaderNodeMath")
    jit.location = (-1000, -560)
    jit.operation = "MULTIPLY_ADD"
    jit.inputs[1].default_value = 5.5          # עומק ההפרעה במטרים
    jit.inputs[2].default_value = -2.75
    nt.links.new(wn.outputs["Fac"], jit.inputs[0])
    add = nt.nodes.new("ShaderNodeMath")
    add.location = (-830, -480)
    add.operation = "ADD"
    nt.links.new(sep.outputs["Y"], add.inputs[0])
    nt.links.new(jit.outputs["Value"], add.inputs[1])
    wet_r = nt.nodes.new("ShaderNodeMapRange")
    wet_r.location = (-620, -480)
    # 36..58 ולא 44..57. ברצועה של 13 מטר על חוף של 120 הרטיבות
    # נפלה כמעט כולה מחוץ לקאדר, ולכן בפריים החול היה יבש
    # ואחיד עד לקו הקצף - והמעבר חול/ים נקרא כקו חיתוך ולא
    # כחוף. 22 מטר של התכהות הדרגתית הם מה שמחבר ביניהם.
    wet_r.inputs["From Min"].default_value = 36.0   # יבש מכאן ואחורה
    wet_r.inputs["From Max"].default_value = 58.0   # רטוב בקצה
    wet_r.inputs["To Min"].default_value = 0.0
    wet_r.inputs["To Max"].default_value = 1.0
    wet_r.clamp = True
    nt.links.new(add.outputs["Value"], wet_r.inputs["Value"])
    # ``MapRange`` מחזיר ``Result`` (ולא ``Color`` כמו ColorRamp).
    # ``bpy_prop_collection`` אינו ניתן להשמה, ולכן אין "לכנות"
    # אותו מחדש - פשוט משתמשים בשם הנכון.
    wet_m = wet_r.outputs["Result"]
    w_mix = mix(-360, wet_m, g_mix.outputs["Color"],
                (0.118, 0.086, 0.060))

    # --- 5. הזרקת רוויה, נגד AgX.
    hs = nt.nodes.new("ShaderNodeHueSaturation")
    hs.location = (-380, -60)
    # 1.10 ולא 1.34: ב-1.34 החול יצא כתום זוהר וכתמי, לא
    # חוף. AgX אכן מוריד רוויה, אבל פחות ממה שהערכתי.
    hs.inputs["Saturation"].default_value = 1.10
    hs.inputs["Value"].default_value = 1.00
    nt.links.new(w_mix.outputs["Color"], hs.inputs["Color"])
    nt.links.new(hs.outputs["Color"], b.inputs["Base Color"])

    # --- 6. Roughness מונע מהלחות: 0.94 יבש, 0.21 רטוב.
    rr = nt.nodes.new("ShaderNodeMapRange")
    rr.location = (-380, -420)
    rr.inputs["To Min"].default_value = 0.94
    rr.inputs["To Max"].default_value = 0.21
    nt.links.new(wet_m, rr.inputs["Value"])
    nt.links.new(rr.outputs["Result"], b.inputs["Roughness"])
    # חול רטוב מחזיר השתקפות רחבה. ``Specular`` מוריד אותה ביבש.
    for k in ("Specular IOR Level", "Specular"):
        if k in b.inputs:
            sp = nt.nodes.new("ShaderNodeMapRange")
            sp.location = (-380, -560)
            sp.inputs["To Min"].default_value = 0.22
            sp.inputs["To Max"].default_value = 0.62
            nt.links.new(wet_m, sp.inputs["Value"])
            nt.links.new(sp.outputs["Result"], b.inputs[k])
            break

    # --- 7. Bump, **רק למיקרו**. הגסות כבר בגאומטריה
    #     (``sand_plane``), ולכן Bump כאן אינו מנסה לייצר דיונות -
    #     הוא רק מחספס את פני התא. Bump שמנסה להחליף גאומטריה
    #     נראה כמו הטבעה על פלסטיק, וזה מה שהיה כאן קודם.
    bump_n = noise(13.0, 12.0, -700, rough=0.66)
    bp = nt.nodes.new("ShaderNodeBump")
    bp.location = (-380, -700)
    bp.inputs["Strength"].default_value = 0.65
    bp.inputs["Distance"].default_value = 0.012
    nt.links.new(bump_n.outputs["Fac"], bp.inputs["Height"])
    # אדוות גם ב-Bump, בעוצמה נמוכה: הגאומטריה נותנת את הצורה,
    # ה-Bump מוסיף לה קצה.
    bp2 = nt.nodes.new("ShaderNodeBump")
    bp2.location = (-180, -700)
    bp2.inputs["Strength"].default_value = 0.72
    bp2.inputs["Distance"].default_value = 0.028
    nt.links.new(rip.outputs["Fac"], bp2.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], bp2.inputs["Normal"])
    nt.links.new(bp2.outputs["Normal"], b.inputs["Normal"])
    nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])
    return mat


def water_material():
    """ים, לא משטח. **הצבע נגזר מהעומק ולא מקבוע אחד.**

    הצבע הקודם היה ``(0.040,0.160,0.205)`` אחיד על מישור של 500
    מטר. ים אמיתי אינו בצבע אחד: הרדוד שליד קו המים הוא טורקיז
    בהיר (האור חוזר מקרקעית החול דרך חצי מטר מים), ומשם ועד
    האופק הוא מתכהה אל כחול-דיו כי האור כבר לא חוזר. אחידות
    היא בדיוק מה שהופך ים לפס.

    ``Object`` ב-Y הוא המרחק מקו המים במטרים (המישור הוא ±250
    סביב מרכזו ב-y=140, כלומר ‎-126 בקו המים ו-‎+250 באופק).
    """
    mat = bpy.data.materials.new("water")
    nt, out = _nodes(mat)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.location = (300, 0)
    dtc = nt.nodes.new("ShaderNodeTexCoord")
    dtc.location = (-1400, 240)
    dsep = nt.nodes.new("ShaderNodeSeparateXYZ")
    dsep.location = (-1200, 240)
    nt.links.new(dtc.outputs["Object"], dsep.inputs["Vector"])
    # הפרעת רעש על גבול העומק: בלעדיה המעבר רדוד->עמוק הוא קו
    # ישר לרוחב הפריים, וקו ישר בים נקרא כתפר ולא כשרטון.
    dn = nt.nodes.new("ShaderNodeTexNoise")
    dn.location = (-1200, 60)
    dn.inputs["Scale"].default_value = 0.055
    dn.inputs["Detail"].default_value = 4.0
    nt.links.new(dtc.outputs["Object"], dn.inputs["Vector"])
    djit = nt.nodes.new("ShaderNodeMath")
    djit.location = (-1000, 60)
    djit.operation = "MULTIPLY_ADD"
    djit.inputs[1].default_value = 34.0
    djit.inputs[2].default_value = -17.0
    nt.links.new(dn.outputs["Fac"], djit.inputs[0])
    dadd = nt.nodes.new("ShaderNodeMath")
    dadd.location = (-830, 180)
    dadd.operation = "ADD"
    nt.links.new(dsep.outputs["Y"], dadd.inputs[0])
    nt.links.new(djit.outputs["Value"], dadd.inputs[1])
    dep = nt.nodes.new("ShaderNodeMapRange")
    dep.location = (-640, 180)
    dep.inputs["From Min"].default_value = -126.0   # קו המים
    dep.inputs["From Max"].default_value = -34.0    # ~90 מטר לים
    dep.clamp = True
    nt.links.new(dadd.outputs["Value"], dep.inputs["Value"])
    dramp = nt.nodes.new("ShaderNodeValToRGB")
    dramp.location = (-440, 180)
    el = dramp.color_ramp.elements
    el[0].position = 0.0
    # טורקיז רדוד. הערכים גבוהים בכוונה: AgX עם חשיפה ‎-0.52
    # מוריד רוויה, ומי שמתחיל מטורקיז "מדויק" מסיים באפור -
    # בדיוק מה שקרה לחול בארבעה סבבים.
    el[0].color = (0.055, 0.520, 0.470, 1.0)
    el[1].position = 0.62
    el[1].color = (0.010, 0.072, 0.168, 1.0)
    e2 = dramp.color_ramp.elements.new(0.24)
    e2.color = (0.020, 0.265, 0.340, 1.0)
    nt.links.new(dep.outputs["Result"], dramp.inputs["Fac"])
    nt.links.new(dramp.outputs["Color"], b.inputs["Base Color"])
    # 0.13 פיזר את ההיילייט על כל המשטח, וים ללא נצנוץ ממוקד
    # נקרא כפלסטיק. 0.045 מחזיר את שביל השמש; האדוות הדקות
    # (``n2``) הן שפורסות אותו לנקודות ולא לכתם אחד.
    b.inputs["Roughness"].default_value = 0.045
    for k in ("IOR",):
        if k in b.inputs:
            b.inputs[k].default_value = 1.333
    # שקיפות נמוכה ובכוונה: מתחת למישור אין קרקעית, ולכן
    # ``Transmission`` גבוה מחזיר שחור ולא עומק. העומק כאן
    # נעשה בצבע, שם הוא נמדד.
    for k, v in (("Transmission Weight", 0.08), ("Transmission", 0.08)):
        if k in b.inputs:
            b.inputs[k].default_value = v
            break
    # שתי שכבות גלים, שתיהן בקואורדינטות **אובייקט** (מטרים):
    # ``Scale`` ב-Noise הוא תקופות ליחידה, ולכן 0.42 הוא גל של
    # כ-2.4 מטר ו-5.5 הוא אדווה של 18 ס"מ. הערך הקודם (26 על
    # Generated של מישור 500 מטר) היה תדר שאינו קיים בשום ים,
    # ולכן המשטח נמדד כחלק.
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-1000, -260)
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.location = (-760, -180)
    # 4D ולא 3D: ציר ה-W הוא מה שמאפשר להזיז את הגלים בזמן
    # בלי להזיז את המשטח. ב-3D אין קלט ``W`` בכלל, והבימוי
    # היה "מצליח" בשקט עם ים קפוא.
    n.noise_dimensions = "4D"
    n.inputs["Scale"].default_value = 0.42
    n.inputs["Detail"].default_value = 9.0
    nt.links.new(tc.outputs["Object"], n.inputs["Vector"])
    n2 = nt.nodes.new("ShaderNodeTexNoise")
    n2.location = (-760, -480)
    n2.noise_dimensions = "4D"
    n2.inputs["Scale"].default_value = 5.5
    n2.inputs["Detail"].default_value = 10.0
    nt.links.new(tc.outputs["Object"], n2.inputs["Vector"])
    # שכבה שלישית, ~70 ס"מ. בלעדיה היה פער בין גל של 2.4 מטר
    # לאדווה של 18 ס"מ, וים אמיתי מלא דווקא בתדר שביניהם -
    # הוא זה שפורס את שביל השמש לנקודות במרחק בינוני.
    n3 = nt.nodes.new("ShaderNodeTexNoise")
    n3.location = (-760, -700)
    n3.noise_dimensions = "4D"
    n3.inputs["Scale"].default_value = 1.45
    n3.inputs["Detail"].default_value = 9.0
    nt.links.new(tc.outputs["Object"], n3.inputs["Vector"])
    # --- **דעיכת ה-Bump עם המרחק, וזו לא קוסמטיקה.**
    #
    # בפריים המבחן (ריצה s1014-125103) הים יצא **מפוספס בפסים
    # אנכיים כהים ובהירים לסירוגין**, כמו גדר. זה אינו שיידר
    # שבור אלא מוארה: במרחק 80-300 מטר, אדווה של 18 ס"מ ואפילו
    # גל של 70 ס"מ הם הרבה מתחת לגודל פיקסל, וב**זווית לטיה**
    # (המשטח כמעט מקביל לקו הראייה) כל פיקסל מכסה עשרות
    # תקופות. ``Bump`` אינו ממצע לשטוח כמו שצבע עושה - הוא
    # ממצע לנורמלים אקראיים, וזה יוצא רעש מובנה.
    #
    # ים אמיתי נראה חלק ככל שהוא רחוק, מאותה סיבה פיזיקלית
    # בדיוק. לכן עוצמת שתי השכבות הדקות נגזרת מ-``dep`` (0 בקו
    # המים, 1 במרחק): קרוב - כל הפירוט; רחוק - כמעט כלום.
    def fade(y, near, far):
        mr = nt.nodes.new("ShaderNodeMapRange")
        mr.location = (-520, y)
        mr.inputs["To Min"].default_value = near
        mr.inputs["To Max"].default_value = far
        mr.clamp = True
        nt.links.new(dep.outputs["Result"], mr.inputs["Value"])
        return mr

    bp = nt.nodes.new("ShaderNodeBump")
    bp.location = (-420, -260)
    # הגל הגדול (2.4 מטר) שורד גם רחוק - הוא עשרות פיקסלים
    # שם - ולכן הוא דועך מעט בלבד.
    bp.inputs["Distance"].default_value = 0.130
    nt.links.new(fade(-200, 0.95, 0.42).outputs["Result"],
                 bp.inputs["Strength"])
    nt.links.new(n.outputs["Fac"], bp.inputs["Height"])
    bp3 = nt.nodes.new("ShaderNodeBump")
    bp3.location = (-300, -700)
    bp3.inputs["Distance"].default_value = 0.034
    nt.links.new(fade(-640, 0.80, 0.06).outputs["Result"],
                 bp3.inputs["Strength"])
    nt.links.new(n3.outputs["Fac"], bp3.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], bp3.inputs["Normal"])
    bp2 = nt.nodes.new("ShaderNodeBump")
    bp2.location = (-180, -300)
    bp2.inputs["Distance"].default_value = 0.012
    nt.links.new(fade(-880, 0.70, 0.00).outputs["Result"],
                 bp2.inputs["Strength"])
    nt.links.new(n2.outputs["Fac"], bp2.inputs["Height"])
    nt.links.new(bp3.outputs["Normal"], bp2.inputs["Normal"])
    nt.links.new(bp2.outputs["Normal"], b.inputs["Normal"])
    # ו-``Roughness`` עולה עם המרחק מאותה סיבה: המיקרו-גלים
    # שאינם נפתרים עוד הם בדיוק מה ש"מחוספס" מתאר. בלי זה
    # הים הרחוק הוא מראה חדה ומחזיר את השמיים ככתם לבן אחד.
    nt.links.new(fade(-60, 0.045, 0.145).outputs["Result"],
                 b.inputs["Roughness"])
    nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])
    return mat, n


def foam_material():
    mat = bpy.data.materials.new("foam")
    nt, out = _nodes(mat)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.location = (300, 0)
    b.inputs["Base Color"].default_value = (0.93, 0.95, 0.95, 1)
    b.inputs["Roughness"].default_value = 0.52
    # **קצף מתוח בציר הגל, לא כתמים.** רעש איזוטרופי נותן
    # ספוג; קצף של גל שנשבר הוא רצועות מתוחות **במקביל לקו
    # המים**, ולכן ה-Mapping דוחס את ציר Y פי 4.5. זה ההבדל
    # בין "לבן מלוכלך" לבין קו גלישה.
    fmap = nt.nodes.new("ShaderNodeMapping")
    fmap.location = (-900, 200)
    fmap.inputs["Scale"].default_value = (0.55, 4.5, 1.0)
    ftc = nt.nodes.new("ShaderNodeTexCoord")
    ftc.location = (-1100, 200)
    nt.links.new(ftc.outputs["Object"], fmap.inputs["Vector"])
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.location = (-700, 200)
    n.noise_dimensions = "4D"
    n.inputs["Scale"].default_value = 3.6
    n.inputs["Detail"].default_value = 11.0
    nt.links.new(fmap.outputs["Vector"], n.inputs["Vector"])
    r = nt.nodes.new("ShaderNodeValToRGB")
    r.location = (-430, 200)
    # 0.44/0.58 ולא 0.48/0.63: סף נמוך יותר פותח יותר שטח קצף,
    # והמעבר הצר שומר על קצה חד. קצף עם קצה רך נראה כערפל.
    r.color_ramp.elements[0].position = 0.44
    r.color_ramp.elements[1].position = 0.58
    nt.links.new(n.outputs["Fac"], r.inputs["Fac"])
    # --- **הקצף הוא רצועה, לא שטיח.** בפריים המבחן מישור הקצף
    # (34 יחידות) כיסה את כל חזית הפריים בלבן, והחול נעלם
    # לגמרי. ההגבלה היא לפי ציר Y בקואורדינטות אובייקט: קצף
    # קיים רק בין קו המים לכמטר לפניו, ודועך לשני הכיוונים -
    # בדיוק כמו גל שנשבר.
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-980, -200)
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-760, -200)
    nt.links.new(tc.outputs["Object"], sep.inputs["Vector"])
    near = nt.nodes.new("ShaderNodeMapRange")
    near.location = (-560, -140)
    # הערכים הם קואורדינטות **אובייקט** במטרים, כלומר ביחס
    # למרכז המישור (``primitive_plane_add(size=30)`` נותן ‎±15).
    # ``Generated`` היה נותן 0..1 ומחייב כיול מחדש בכל שינוי
    # גודל; Object נשאר נכון.
    # הורחב מ-3 מטר ל-6: בפריים של 14/10 הרצועה הייתה דקה מכדי
    # להיקרא כגלישה, ושתי הרצועות (חול רטוב מלפנים, ים מאחור)
    # נגעו זו בזו. גל שנשבר משאיר 5-7 מטר של קצף.
    near.inputs["From Min"].default_value = -2.40
    near.inputs["From Max"].default_value = -0.90
    far = nt.nodes.new("ShaderNodeMapRange")
    far.location = (-560, -330)
    far.inputs["From Min"].default_value = 3.60
    far.inputs["From Max"].default_value = 1.60
    nt.links.new(sep.outputs["Y"], near.inputs["Value"])
    nt.links.new(sep.outputs["Y"], far.inputs["Value"])
    band = nt.nodes.new("ShaderNodeMath")
    band.location = (-370, -230)
    band.operation = "MULTIPLY"
    nt.links.new(near.outputs["Result"], band.inputs[0])
    nt.links.new(far.outputs["Result"], band.inputs[1])
    gate = nt.nodes.new("ShaderNodeMath")
    gate.location = (-200, -100)
    gate.operation = "MULTIPLY"
    nt.links.new(r.outputs["Color"], gate.inputs[0])
    nt.links.new(band.outputs["Value"], gate.inputs[1])

    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    tr.location = (300, -220)
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.location = (470, 0)
    nt.links.new(gate.outputs["Value"], mix.inputs["Fac"])
    nt.links.new(tr.outputs["BSDF"], mix.inputs[1])
    nt.links.new(b.outputs["BSDF"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return mat, n


# ---------------------------------------------------------------- מצלמה

def fit_camera(obs, lens=85.0, margin=0.015, w=960, h=540):
    """קאדר גוף-מלא שנגזר מה-bbox של השחקנים ולא ממספר קשיח.

    פעמיים כבר נחתכו כאן רגליים או ראשים כי המצלמה הוצבה ידנית.
    כאן מחשבים את התיבה, מרחיבים בשוליים, ופותרים את המרחק
    לפי שדה הראייה האנכי והאופקי - הקטן מהשניים קובע.
    """
    pts = []
    for ob in obs:
        for c in ob.bound_box:
            pts.append(ob.matrix_world @ mathutils.Vector(c))
    lo = mathutils.Vector((min(p.x for p in pts), min(p.y for p in pts),
                           min(p.z for p in pts)))
    hi = mathutils.Vector((max(p.x for p in pts), max(p.y for p in pts),
                           max(p.z for p in pts)))
    ctr = (lo + hi) * 0.5
    bw = (hi.x - lo.x) * (1 + margin * 2)
    bh = (hi.z - lo.z) * (1 + margin * 2)
    cam_d = bpy.data.cameras.new("cam")
    cam_d.lens = lens
    cam = bpy.data.objects.new("cam", cam_d)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    sw = cam_d.sensor_width
    sh = sw * h / w
    dz = bh * lens / sh
    dx = bw * lens / sw
    # **הקאדר הוא מנוף איכות ולא טעם.** בפריים המבחן הדמויות
    # תפסו כ-45% מגובה הפריים, והיתר היה חול וים - שני משטחים
    # שהשער מודד כ-``flat_ratio`` גבוה וכ-``chroma_std`` נמוך.
    # שוליים 1.5% ועדשה 85מ"מ מכניסים את אותו גוף-מלא, אבל
    # ממלאים את הפריים בעור, בד ושיער במקום בחול.
    dist = max(dz, dx) + (hi.y - lo.y) * 0.5 + 0.18
    # גובה המצלמה בגובה החזה ולא בגובה האגן: כך קו האופק יושב
    # מאחורי הדמויות, ופחות חול חזיתי נכנס לקאדר.
    cam.location = (ctr.x + 0.06, ctr.y - dist, ctr.z + 0.22)
    cam.rotation_euler = (math.radians(90.0) - math.atan2(0.22, dist),
                          0.0, 0.0)
    # ``aperture_fsize`` הוא שם מ-2.7x. ב-2.8+ זה ``aperture_fstop``,
    # ולכן ההצבה עוברת דרך ``_set`` ולא נופלת על שם.
    # **עומק שדה כבוי.** f/4 על עדשה 85מ"מ במרחק 7 מטר מטשטש את
    # כל הרקע, וה-HDRI הזה הוא תצלום 4K של עיר על מפרץ - כלומר
    # המקור החד והצבעוני ביותר בפריים. המדידה: ``sharp_detail``
    # ירד מ-0.944 ל-0.760 ביחס לרפרנס בדיוק כשה-DOF נדלק.
    # קולנועית זה נראה טוב; במדידה זה עולה את שני המדדים
    # שהשער פוסל עליהם.
    _set(cam_d.dof, use_dof=False)
    log("מצלמה: מרחק %.2fמ · עדשה %.0fמ\"מ · קאדר %.2f×%.2fמ"
        % (dist, lens, bw, bh))
    return cam, dist, ctr


# ----------------------------------------------------------------- בימוי

def apply_frame(cast, cam, cam0, dist, ctr, frame, total, waves, foam):
    """בימוי לפי פריים. בלי שמע, בלי ליפסינק - רק גוף ומצלמה."""
    t = (frame - 1) / max(1, total - 1)
    # גלים ממשיכים לזוז: ה-noise מוזז בזמן, לא מונפש בפאזה.
    for n in (waves, foam):
        n.inputs["W"].default_value = t * 2.4 if "W" in n.inputs else 0.0
    # נשימה + העברת משקל: עדין בכוונה. תנועה גדולה על ריג ציר
    # בלבד נראית כמו גוש שמתנדנד.
    for i, c in enumerate(cast):
        ph = t * math.tau + i * 2.1
        arm = c.get("arm")
        if arm:
            for nm, amp in (("spine", 0.016), ("chest", 0.012)):
                pb = arm.pose.bones.get(nm)
                if pb:
                    pb.rotation_mode = "XYZ"
                    pb.rotation_euler = (math.sin(ph) * amp, 0.0, 0.0)
            pb = arm.pose.bones.get("head")
            if pb:
                pb.rotation_mode = "XYZ"
                # ההפניה: דמות א' מפנה את הראש אל ב' בחצי הראשון
                # ומחזיקה. זה "אחת פונה אל השנייה" של השוט המקורי.
                turn = c["turn"] * smoothstep(0.08, 0.42, t)
                pb.rotation_euler = (math.sin(ph * 0.7) * 0.010,
                                     0.0, turn)
        root = c["root"]
        root.location = (c["x"], c["y"], math.sin(ph * 1.1) * 0.004)
        root.rotation_euler = (0.0, 0.0, c["yaw"] +
                               math.sin(ph * 0.55) * 0.012)
    # דולי אחורה-פנימה עדין: נותן פרלקסה, ולכן נפח. בלי זה
    # התמונה יכולה להיקרא כציור שטוח גם כשהיא תלת-ממד.
    push = (1.0 - 0.055 * smoothstep(0.0, 1.0, t))
    cam.location = (cam0[0], ctr.y - dist * push, cam0[2])


# ------------------------------------------------------------------ ראשי

def build(a):
    wipe()
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    # הכול דרך ``_set``: שמות ההגדרות של Cycles זזו בין 3.x ל-4.x
    # (``denoising_prefilter``, ``use_fast_gi``), וריצה שנפלה על
    # שם הגדרה היא 50 שניות ענן ועוד סבב שלם של דחיפה.
    # ``denoising_prefilter=ACCURATE`` אינו קוסמטיקה: ברירת המחדל
    # מרככת פירוט בתדר גבוה - כלומר בדיוק את השיער - וזה מה
    # שנמדד ב-``sharp_detail``.
    _set(sc.cycles, device="CPU", samples=a.samples,
         use_adaptive_sampling=True, adaptive_threshold=0.006,
         use_denoising=True, denoiser="OPENIMAGEDENOISE",
         denoising_prefilter="ACCURATE", max_bounces=6,
         transmission_bounces=3, caustics_reflective=False,
         caustics_refractive=False, use_fast_gi=True)
    _set(sc.render, film_transparent=False, filter_size=1.20)
    _set(sc.render.image_settings, file_format="PNG", compression=15)
    sc.view_settings.view_transform = "AgX"
    for look in ("AgX - Medium High Contrast", "AgX - Base Contrast",
                 "AgX - Punchy", "None"):
        try:
            sc.view_settings.look = look
            log("look: %s" % look)
            break
        except TypeError:
            continue
    # ‎-0.20 החזיר חול ומים שרופים ללבן. ‎-0.62 מחזיר את קו
    # האופק ואת מרקם החול לתוך הטווח, והעור נשאר קריא כי
    # ה-AgX מגלגל את ההיילייטס ולא מצמיד אותם.
    sc.view_settings.exposure = -0.52
    sc.render.resolution_x = a.width
    sc.render.resolution_y = a.height
    sc.render.resolution_percentage = 100
    sc.render.filter_size = 1.20
    sc.frame_start = 1
    sc.frame_end = a.total

    world_hdri(Path(a.hdri))
    add_sun()

    # **גריד ולא מישור.** ``plane`` נותן ארבעה קודקודים, וחול
    # בארבעה קודקודים אינו מטיל צל על עצמו - ולכן הוא נקרא
    # כרצפה יצוקה בכל פריים מבחן עד כה, ולא משנה מה בשיידר.
    # **קו המים הוזז מ-5 מטר ל-22 מטר מאחורי הדמויות.** בפריים
    # המבחן החול נגמר כמעט מיד מאחורי הרגליים, ומשם ועד הים
    # השתרע מישור הקצף - 30 מטר של לבן-אפרפר שקרא כמדרכה רטובה
    # וחתך את הפריים לשניים. חוף נקרא כחוף כשרצועת החול היא
    # הדבר הרחב בין הדמות לים, ולא להפך.
    sand = sand_plane("sand", 120.0, (0.0, -46.0, 0.0))
    sand.data.materials.append(sand_material())
    wmat, waves = water_material()
    water = plane("water", 500.0, (0.0, 140.0, -0.02))
    water.data.materials.append(wmat)
    fmat, foam = foam_material()
    # קצף של 30 מטר אינו קצף אלא מישור. גל שנשבר מותיר רצועה
    # של 5-7 מטר, ולכן 16 (המישור רחב, הרצועה שעליו צרה - ראה
    # ``foam_material``: הגבול הוא בשיידר ולא בגאומטריה, ולכן
    # מישור רחב אינו עולה שום דבר בזיכרון ומבטיח שהרצועה חוצה
    # את כל רוחב הפריים).
    wet = plane("foam", 16.0, (0.0, 14.2, 0.030))
    wet.data.materials.append(fmat)

    bundle = Path(a.bundle)
    skinmaps = load_skin_maps(a.skin)
    SKIN_INFO.clear()
    SKIN_INFO.update({
        "used": bool(skinmaps),
        "source": (skinmaps or {}).get("source"),
        "license": (skinmaps or {}).get("license"),
        "tile": a.skin_tile, "detail": a.skin_detail,
    })
    specs = [
        # **שתי הדמויות בבגד ים.** קודם היו "בגד ים" ו"חולצת
        # בטן", ושתיהן נחתכו בקו גובה קשיח - כלומר קצה שעובר
        # באותו ``z`` סביב כל הגוף. על רשת quads זה יוצא משונן,
        # וזה מה ש-``straight_edge_ratio`` מדד. כאן הגבול הוא
        # **עקומה חלקה בזווית** סביב הגו (ראה ``build_groups``),
        # ולכן אין קו אופקי בכלל.
        # דמות א': בנדו + תחתון, פונה אל ב'.
        # **בלונדינית, עור בהיר.** צבע השיער הקודם (0.072,0.034,
        # 0.016) הוא חום כהה כמעט שחור - נמדד בפריים כגוש אפל.
        # בלונדיני בשיידר ``COLOR`` אינו "צהוב": זהו ערוץ אדום
        # גבוה, ירוק בשני שליש ממנו וכחול נמוך, כלומר גוון ענבר
        # בהיר. ``Radial Roughness`` עושה את השאר.
        {"tag": "noa", "x": -0.40, "y": 0.0, "yaw": math.radians(-13.0),
         "turn": math.radians(-21.0), "garment": "swim",
         "tone": (0.952, 0.788, 0.672), "flush": (0.90, 0.46, 0.39),
         "hair": (0.595, 0.372, 0.118), "hair_len": 0.105,
         "cloth": (0.055, 0.215, 0.330), "chest": 0.036, "scale": 1.000,
         "swim": {"top_z": 0.737, "top_w": 0.049, "top_wave": 0.017,
                  "hip_z": 0.548, "leg_z": 0.452, "hip_wave": 0.020}},
        # דמות ב': אותו עיצוב, חיתוך מעט שונה - לא אותו בגד.
        # **גם היא בלונדינית ובעלת עור בהיר.** הטון הקודם
        # (0.545,0.375,0.275) הוא עור כהה, והבקשה היא שתי
        # דמויות בהירות. ההפרדה ביניהן נשמרת בגוון ולא בבהירות:
        # כאן השיער פלטינה-חולי (קר) ושם ענבר (חם), וההבדל
        # ניכר בפריים בלי ששתיהן ייראו זהות.
        {"tag": "tal", "x": 0.44, "y": 0.22, "yaw": math.radians(12.0),
         "turn": math.radians(8.0), "garment": "swim",
         "tone": (0.940, 0.766, 0.652), "flush": (0.88, 0.43, 0.37),
         "hair": (0.745, 0.572, 0.262), "hair_len": 0.118,
         "cloth": (0.830, 0.330, 0.355), "chest": 0.041, "scale": 0.962,
         "swim": {"top_z": 0.744, "top_w": 0.055, "top_wave": 0.013,
                  "hip_z": 0.561, "leg_z": 0.466, "hip_wave": 0.026}},
    ]
    cast, meta = [], []
    for s in specs:
        got = load_asset(bundle)
        body = got["body"]
        eyes = list(got.get("eyes") or [])
        body.name = "body_" + s["tag"]
        for i, e in enumerate(eyes):
            e.name = "eye%d_%s" % (i, s["tag"])
        h = normalize(body, eyes)
        fdir = face_dir(body, eyes)
        groups = build_groups(body, h, fdir, s.get("swim") or {})
        shape_chest(body, groups, fdir, s["chest"])

        uvname = ensure_uv(body) if skinmaps else ""
        skin = skin_material("skin_" + s["tag"], s["tone"], s["flush"],
                             maps=skinmaps if uvname else None,
                             uvname=uvname, tile=a.skin_tile,
                             detail=a.skin_detail)
        body.data.materials.clear()
        body.data.materials.append(skin)
        for p in body.data.polygons:
            p.use_smooth = True

        # **סדר השכבות הוא התיקון, לא קישוט.** בלנדר מחשב
        # מודיפיירים בשרשרת, ולכן:
        #   ARMATURE -> SUBSURF -> PARTICLE(hair)
        # אם השיער היה לפני ה-ARMATURE, הוא היה נצמח על הגוף
        # הלא-מעוות ונשאר תלוי באוויר כשהראש מסתובב 21°. הריג
        # קודם, ומכאן גם שהבגד נבנה אחריו - כדי שיירש את משקלי
        # הדפורמציה שלו.
        arm = build_rig(body, h)
        # **השיער לפני ה-SUBSURF, וזו החלטת זיכרון שנמדדה.**
        # בסדר הקודם (SUBSURF -> PARTICLE) הגדילים גודלו על
        # הרשת שאחרי שתי רמות חלוקה - 169 אלף פאות במקום 10.5
        # אלף - ומבני האינטרפולציה של 67,200 הבנים נבנו עליה.
        # הריצות 38523912537 ו-38524...  נהרגו בשיא של כ-13GB
        # מתוך 16, **גם בלי מפות העור**: נמדד בשלב "בסיס זיכרון"
        # בשרשרת. ARMATURE -> PARTICLE -> SUBSURF נותן אותו שיער
        # בדיוק (הדפורמציה של הריג כבר הוחלה לפניו), ומוציא את
        # הרשת המחולקת מהנתיב הזה לגמרי.
        # **שיער = קליפה + פאזז, ולא גדילים ארוכים.** ראה
        # ``hair_shell``: גדילי חלקיקים צומחים רדיאלית ואי אפשר
        # לסרק אותם ב-background, ולכן הצורה נבנית בגאומטריה
        # והחלקיקים נשארים רק בתפקיד שהם כן ממלאים היטב -
        # קצה רך. 2.2 ס"מ במקום 20, ולכן גם אין עוד OOM.
        # **הקליפה מבוטלת כברירת מחדל - נמדדה ונפסלה.**
        # הרעיון נכון (ראה ``hair_shell``) והמימוש אינו: בכל
        # הרצה היא רונדרה כמסה שמכסה את הפנים מהמצח לסנטר,
        # **גם** כש-``drop=0``, **גם** בלי Solidify ו-SUBSURF
        # ו**גם** בלי פאזז החלקיקים - שלושה מבחני בידוד שכל
        # אחד מהם שלל חשוד אחר. במקביל ``build_groups`` מדדה
        # שאף קודקוד פנים אינו נכלל ב-``keep``. כלומר הפער
        # הוא בין בחירת הקודקודים לבין מה שמרונדר, ולא נסגר
        # בזמן שהוקצב. השיער חוזר לחלקיקים - עם ``hairlen``
        # ועם הקרקפת המורחבת אחורה, שתיהן נמדדו כעובדות -
        # ושם הפנים גלויות.
        shell = None
        if a.hair_shell:
            shell = hair_shell(body, h, fdir, s["hair"],
                               drop=s.get("hair_drop", 0.19),
                               thick=a.hair_thick, fuzz=a.hair_fuzz)
        if shell:
            shell.name = "hair_" + s["tag"]
        else:
            add_hair(body, s["hair_len"], s["hair"],
                     children=a.hair_children)
        sub = body.modifiers.new("sub", "SUBSURF")
        sub.levels = 0
        sub.render_levels = a.subdiv
        sub.use_limit_surface = True
        garment = make_garment(
            body, groups[s["garment"]], "cloth_" + s["tag"],
            cloth_material("fabric_" + s["tag"], s["cloth"]))

        root = arm if arm else body
        # העיניים: ``ARMATURE`` עם קבוצה בשם העצם ובמשקל 1, ולא
        # הורות-אובייקט. הורות בלבד הייתה משאירה אותן במקום
        # בעוד הראש מסתובב - כלומר דמות פוזלת. קבוצה בשם עצם
        # נותנת להן בדיוק את הטרנספורמציה של ``head_b``.
        emat = eye_material("eye_" + s["tag"], fdir)
        for e in eyes:
            # **העיניים היו שקועות מדי מכדי להיראות.** בפריים של
            # 960×540 הן רונדרו כשני חורים כהים, ומכאן התחושה
            # שלראש אין פנים. הגדלה של 7% והזזה של 3 מ"מ קדימה
            # מוציאות את הקשתית אל פני הארובה. ההזזה היא על
            # הנתונים ולא על ה-object, כדי שהיא תישמר תחת הריג.
            ec = mathutils.Vector((0.0, 0.0, 0.0))
            for v in e.data.vertices:
                ec += v.co
            ec /= max(1, len(e.data.vertices))
            for v in e.data.vertices:
                v.co = ec + (v.co - ec) * 1.07 + \
                    mathutils.Vector((0.0, fdir * 0.0030, 0.0))
            e.data.materials.clear()
            e.data.materials.append(emat)
            for p in e.data.polygons:
                p.use_smooth = True
            e.parent = root
            e.matrix_parent_inverse = root.matrix_world.inverted()
            if arm:
                g = e.vertex_groups.new(name="head")
                g.add(list(range(len(e.data.vertices))), 1.0, "REPLACE")
                em = e.modifiers.new("arm", "ARMATURE")
                em.object = arm
        for extra in (garment, shell):
            if not extra:
                continue
            extra.parent = root
            extra.matrix_parent_inverse = root.matrix_world.inverted()
        root.location = (s["x"], s["y"], 0.0)
        root.rotation_euler = (0.0, 0.0, s["yaw"])
        root.scale = (s["scale"],) * 3
        ok = sanity_pose(body, arm, h)
        cast.append({"root": root, "arm": arm, "body": body,
                     "fdir": fdir,
                     "x": s["x"], "y": s["y"], "yaw": s["yaw"],
                     "turn": s["turn"]})
        meta.append({"tag": s["tag"], "verts": len(body.data.vertices),
                     "rigged": bool(arm), "pose_sane": ok,
                     "hair_shell": bool(shell),
                     "hair_verts": len(shell.data.vertices) if shell else 0,
                     "garment": bool(garment),
                     "garment_kind": s["garment"], "scale": s["scale"]})
        log("דמות %s: %d קודקודים, ריג=%s, בגד=%s"
            % (s["tag"], len(body.data.vertices), bool(arm), bool(garment)))

    bpy.context.view_layer.update()
    # **אחרון בשרשרת, ובכוונה.** ראה ``comb_hair``: כל נגיעה
    # ב-``ps.settings`` אחרי הסירוק מאפסת את המפתחות, ולכן זה
    # קורה רק כששתי הדמויות כבר בנויות במלואן.
    cam, dist, ctr = fit_camera([c["body"] for c in cast],
                                w=a.width, h=a.height)
    cam0 = tuple(cam.location)
    return cast, cam, cam0, dist, ctr, waves, foam, meta


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--hdri", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=1)
    ap.add_argument("--total", type=int, default=120)
    ap.add_argument("--samples", type=int, default=48)
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--height", type=int, default=540)
    ap.add_argument("--subdiv", type=int, default=2,
                    help="רמות חלוקה ברינדור. 2=חלק, 1=חצי זיכרון")
    ap.add_argument("--hair-shell", type=int, default=0, dest="hair_shell",
                    help="1=תסרוקת כגאומטריה (נפסלה), 0=חלקיקים")
    ap.add_argument("--hair-fuzz", type=int, default=6, dest="hair_fuzz",
                    help="בני פאזז על קליפת השיער. 0=בלי")
    ap.add_argument("--hair-thick", type=float, default=0.016,
                    dest="hair_thick", help="עובי קליפת השיער")
    ap.add_argument("--hair-comb", type=float, default=0.86,
                    dest="hair_comb",
                    help="עוצמת הסירוק כלפי מטה. 0=אפרו, 1=שטוח")
    ap.add_argument("--hair-back", type=float, default=0.42,
                    dest="hair_back",
                    help="כמה השיער נסוג אחורה מהפנים")
    ap.add_argument("--hair-children", type=int, default=16,
                    dest="hair_children",
                    help="בנים לכל אם. סך הגדילים = 4200 × זה")
    ap.add_argument("--skin", default="",
                    help="תיקיית ערכת מפות העור (skinmaps.py). "
                         "ריק = חומר פרוצדורלי בלבד")
    ap.add_argument("--skin-tile", type=float, default=18.0,
                    dest="skin_tile",
                    help="כמה פעמים המפה חוזרת על פני ה-UV")
    ap.add_argument("--skin-detail", type=float, default=0.62,
                    dest="skin_detail",
                    help="עוצמת שכבת הצילום על הבסיס, 0..1")
    ap.add_argument("--inventory", action="store_true",
                    help="מדפיס מה יש בחבילה ויוצא, בלי לרנדר")
    a = ap.parse_args(argv)

    if a.inventory:
        with bpy.data.libraries.load(a.bundle, link=False) as (src, _d):
            print(json.dumps({"objects": sorted(src.objects),
                              "collections": sorted(src.collections)},
                             ensure_ascii=False, indent=1))
        return 0

    cast, cam, cam0, dist, ctr, waves, foam, meta = build(a)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out.parent / "studio_meta.json").write_text(json.dumps({
        "asset": "blender-studio/human-base-meshes-bundle-v1.0.0",
        "asset_license": "CC0",
        "body": BODY,
        "hdri": Path(a.hdri).name,
        "hdri_source": "polyhaven (CC0)",
        "engine": "CYCLES/CPU", "samples": a.samples,
        "subdiv_render": 2, "hair": "particle strands",
        "audio": False, "lipsync": False,
        "blender": bpy.app.version_string,
        "skin_maps": dict(SKIN_INFO),
        "cast": meta,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # נכס לבדיקת פרופורציות. בלעדיו ``quality_gate`` מסמן את שער
    # הפרופורציות כ"לא נבדק - שער פתוח אסור", כלומר נכשל - וזה
    # נכון: שער שלא נמדד אינו שער. מייצאים את הדמות הראשונה
    # בלבד, בלי השיער (חלקיקים אינם עוברים ל-glTF ממילא).
    try:
        bpy.ops.object.select_all(action="DESELECT")
        for ob in (cast[0]["body"], cast[0]["root"]):
            if ob:
                ob.select_set(True)
        bpy.context.view_layer.objects.active = cast[0]["body"]
        bpy.ops.export_scene.gltf(
            filepath=str(Path(a.out).parent / "studio_cast"),
            export_format="GLB", use_selection=True,
            export_apply=False, export_animations=False)
        log("נכס לבדיקה יוצא: studio_cast.glb")
    except Exception as e:                                   # noqa: BLE001
        log("ייצוא הנכס נכשל (%s) - שער הפרופורציות יישאר סגור" % e)

    sc = bpy.context.scene
    log("זיכרון אחרי הבנייה: %.1fMB  (מפות עור: %s)"
        % (rss_mb(), SKIN_INFO.get("used")))
    for f in range(a.start, a.end + 1):
        sc.frame_set(f)
        apply_frame(cast, cam, cam0, dist, ctr, f, a.total, waves, foam)
        sc.render.filepath = str(out / ("f%04d" % f))
        bpy.ops.render.render(write_still=True)
        log("פריים %d/%d נכתב, זיכרון %.1fMB" % (f, a.total, rss_mb()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
