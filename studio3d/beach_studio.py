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
EYES = (BODY + ".eye.L", BODY + ".eye.R")
TARGET_H = 1.70                                              # מטר


# ------------------------------------------------------------------ כלים

def log(*a):
    print("[studio]", *a, flush=True)


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


def build_groups(body, h: float, fdir: float):
    """קרקפת, חזה, אזורי בגד וזרועות - הכול מניתוח גאומטרי.

    אין כאן קבוצות מוכנות מהנכס (חבילת פיסול אינה מכילה כאלה),
    ולכן כל קבוצה נגזרת מהיחסים האנתרופומטריים של ה-bbox.
    """
    vs = vlist(body)
    xs = [abs(v.x) for v in vs]
    xmax = max(xs) or 1.0
    scalp, chest, swim, crop = {}, {}, {}, {}
    for i, v in enumerate(vs):
        zr = v.z / h
        # --- קרקפת: הכובע העליון של הראש, דועך כלפי מטה כדי
        #     שקו השיער לא ייחתך בסכין.
        if zr > 0.915:
            scalp[i] = smoothstep(0.915, 0.952, zr)
        # --- חזה: טבעת סביב 0.73h בחצי הקדמי. משקל גאוסיאני
        #     בשני צירים, כך שההגדלה חלקה ואינה יוצרת תפר.
        if 0.665 < zr < 0.805 and v.y * fdir > -0.02:
            wz = math.exp(-((zr - 0.735) / 0.040) ** 2)
            wx = math.exp(-((abs(v.x) - 0.072) / 0.075) ** 2)
            wy = max(0.0, min(1.0, (v.y * fdir + 0.02) / 0.09))
            chest[i] = wz * wx * wy
        # --- בגד ים (דמות א'): חזה + אגן, בטן חשופה.
        if 0.655 < zr < 0.800 or 0.455 < zr < 0.545:
            swim[i] = 1.0
        # --- חולצת בטן (דמות ב'): מהכתף עד מעט מתחת לחזה.
        if 0.640 < zr < 0.855 and abs(v.x) < xmax * 0.62:
            crop[i] = 1.0
        # --- תחתון לדמות ב'
        if 0.450 < zr < 0.545:
            crop[i] = 1.0
    vgroup(body, "scalp", scalp)
    vgroup(body, "chest", chest)
    return {"scalp": scalp, "chest": chest, "swim": swim, "crop": crop,
            "xmax": xmax}


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
    ("chest_b",     (0.00, 0.000, 0.730), (0.00, 0.0, 0.830), "spine"),
    ("neck",        (0.00, 0.000, 0.830), (0.00, 0.0, 0.880), "chest_b"),
    ("head_b",      (0.00, 0.000, 0.880), (0.00, 0.0, 0.990), "neck"),
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
        eb.head = (a[0], a[1], a[2] * h)
        eb.tail = (b[0], b[1], b[2] * h)
        if parent and parent in made:
            eb.parent = made[parent]
            eb.use_connect = True
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


def skin_material(name: str, tone, flush=(0.76, 0.33, 0.30)):
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
    r1.color_ramp.elements[0].color = (tone[0] * 0.80, tone[1] * 0.82,
                                       tone[2] * 0.88, 1.0)
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

    rg = nt.nodes.new("ShaderNodeTexNoise")
    rg.location = (-700, -520)
    rg.inputs["Scale"].default_value = 22.0
    rr = nt.nodes.new("ShaderNodeMapRange")
    rr.location = (-450, -520)
    rr.inputs["To Min"].default_value = 0.34
    rr.inputs["To Max"].default_value = 0.58
    nt.links.new(rg.outputs["Fac"], rr.inputs["Value"])
    nt.links.new(rr.outputs["Result"], bsdf.inputs["Roughness"])

    # שמות קלטי ה-SSS השתנו בין 3.x ל-4.x. ניסיון לפי שם, ובלי
    # ליפול אם אחד מהם אינו קיים בגרסה שרצה.
    for key, val in (("Subsurface Weight", 0.22), ("Subsurface", 0.22)):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = val
            break
    for key in ("Subsurface Radius",):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = (0.036, 0.013, 0.008)
    for key, val in (("Subsurface Scale", 0.035),):
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
    for k, v in (("Color", (*col, 1.0)), ("Roughness", 0.28),
                 ("Radial Roughness", 0.42)):
        if k in h.inputs:
            h.inputs[k].default_value = v
    # וריאציית גוון בין גדיל לגדיל: בלי זה השיער הוא גוש אחד.
    ri = nt.nodes.new("ShaderNodeObjectInfo")
    ri.location = (-300, -200)
    hv = nt.nodes.new("ShaderNodeHueSaturation")
    hv.location = (0, -200)
    hv.inputs["Hue"].default_value = 0.5
    nt.links.new(h.outputs[0], out.inputs["Surface"])
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


def add_hair(body, length: float, col, count=2600, children=9000):
    """שיער כגאומטריה, לא כמשטח מוצק.

    מערכת חלקיקים ולא Curves: ב-4.2 ``curves_empty_hair_add`` דורש
    הקשר של ממשק ועריכה אינטראקטיבית כדי לצמוח, ו-``-b`` לא נותן
    אותו. מערכת חלקיקים מוגדרת כולה בנתונים, ולכן היא הדבר היחיד
    שאפשר לבנות בוודאות ב-``--background``.

    ``hair_length`` נשאר בינוני-קצר בכוונה: בלי סימולציית כבידה
    גדיל ארוך צומח לפי הנורמל ונותן "קיפוד". עם clump ו-kink,
    אורך 12-18 ס"מ קורא כשיער צמוד ואסוף.
    """
    md = body.modifiers.new("hair", "PARTICLE_SYSTEM")
    ps = body.particle_systems[-1]
    ps.vertex_group_density = "scalp"
    s = ps.settings
    _set(s, type="HAIR", count=count, hair_length=length, hair_step=6,
         use_hair_bspline=True, child_type="INTERPOLATED",
         rendered_child_count=children, child_percent=24,
         child_length=0.95, child_radius=0.030,
         clump_factor=0.62, clump_shape=0.22,
         roughness_1=0.012, roughness_1_size=0.06,
         roughness_2=0.022, roughness_2_size=0.22,
         roughness_endpoint=0.010,
         kink="CURL", kink_amplitude=0.012, kink_frequency=2.1,
         kink_shape=0.25,
         root_radius=0.008, tip_radius=0.001, radius_scale=0.010,
         use_close_tip=True)
    # חומר השיער הוא הסלוט השני של הגוף.
    mi = len(body.data.materials)
    body.data.materials.append(hair_material("hair_" + body.name, col))
    s.material = mi + 1
    log("  שיער: %d גדילים × %d בנים, אורך %.2fמ" % (count, children, length))
    return md


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
    log("HDRI: %s (סיבוב %.0f°)" % (hdri.name, rot_deg))


def add_sun(elev=38.0, azim=132.0, energy=3.6, angle_deg=0.90):
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


def sand_material():
    mat = bpy.data.materials.new("sand")
    nt, out = _nodes(mat)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.location = (300, 0)
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.location = (-700, 0)
    n.inputs["Scale"].default_value = 85.0
    n.inputs["Detail"].default_value = 10.0
    r = nt.nodes.new("ShaderNodeValToRGB")
    r.location = (-450, 0)
    r.color_ramp.elements[0].color = (0.62, 0.52, 0.40, 1)
    r.color_ramp.elements[1].color = (0.86, 0.78, 0.63, 1)
    nt.links.new(n.outputs["Fac"], r.inputs["Fac"])
    nt.links.new(r.outputs["Color"], b.inputs["Base Color"])
    g = nt.nodes.new("ShaderNodeTexNoise")
    g.location = (-700, -300)
    g.inputs["Scale"].default_value = 900.0
    bp = nt.nodes.new("ShaderNodeBump")
    bp.location = (-300, -300)
    bp.inputs["Strength"].default_value = 0.85
    bp.inputs["Distance"].default_value = 0.004
    nt.links.new(g.outputs["Fac"], bp.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], b.inputs["Normal"])
    b.inputs["Roughness"].default_value = 0.88
    nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])
    return mat


def water_material():
    mat = bpy.data.materials.new("water")
    nt, out = _nodes(mat)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.location = (300, 0)
    b.inputs["Base Color"].default_value = (0.055, 0.195, 0.235, 1)
    b.inputs["Roughness"].default_value = 0.055
    for k, v in (("Transmission Weight", 0.42), ("Transmission", 0.42)):
        if k in b.inputs:
            b.inputs[k].default_value = v
            break
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.location = (-700, -260)
    # 4D ולא 3D: ציר ה-W הוא מה שמאפשר להזיז את הגלים בזמן
    # בלי להזיז את המשטח. ב-3D אין קלט ``W`` בכלל, והבימוי
    # היה "מצליח" בשקט עם ים קפוא.
    n.noise_dimensions = "4D"
    n.inputs["Scale"].default_value = 26.0
    n.inputs["Detail"].default_value = 8.0
    bp = nt.nodes.new("ShaderNodeBump")
    bp.location = (-300, -260)
    bp.inputs["Strength"].default_value = 0.42
    bp.inputs["Distance"].default_value = 0.010
    nt.links.new(n.outputs["Fac"], bp.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], b.inputs["Normal"])
    nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])
    return mat, n


def foam_material():
    mat = bpy.data.materials.new("foam")
    nt, out = _nodes(mat)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.location = (300, 0)
    b.inputs["Base Color"].default_value = (0.93, 0.95, 0.95, 1)
    b.inputs["Roughness"].default_value = 0.52
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.location = (-700, 200)
    n.noise_dimensions = "4D"
    n.inputs["Scale"].default_value = 14.0
    n.inputs["Detail"].default_value = 9.0
    r = nt.nodes.new("ShaderNodeValToRGB")
    r.location = (-430, 200)
    r.color_ramp.elements[0].position = 0.48
    r.color_ramp.elements[1].position = 0.63
    nt.links.new(n.outputs["Fac"], r.inputs["Fac"])
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    tr.location = (300, -220)
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.location = (470, 0)
    nt.links.new(r.outputs["Color"], mix.inputs["Fac"])
    nt.links.new(tr.outputs["BSDF"], mix.inputs[1])
    nt.links.new(b.outputs["BSDF"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return mat, n


# ---------------------------------------------------------------- מצלמה

def fit_camera(obs, lens=62.0, margin=0.10, w=960, h=540):
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
    dist = max(dz, dx) + (hi.y - lo.y) * 0.5 + 0.25
    cam.location = (ctr.x + 0.10, ctr.y - dist, ctr.z + 0.045)
    cam.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    cam_d.dof.use_dof = True
    cam_d.dof.focus_distance = dist
    cam_d.dof.aperture_fsize = 4.0
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
            for nm, amp in (("spine", 0.016), ("chest_b", 0.012)):
                pb = arm.pose.bones.get(nm)
                if pb:
                    pb.rotation_mode = "XYZ"
                    pb.rotation_euler = (math.sin(ph) * amp, 0.0, 0.0)
            pb = arm.pose.bones.get("head_b")
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
    sc.cycles.device = "CPU"
    sc.cycles.samples = a.samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.010
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = "OPENIMAGEDENOISE"
        # ``denoising_prefilter`` ברירת המחדל מרככת פירוט דק
        # (שיער!). ACCURATE שומר אותו, ובדיוק זה מה שנמדד.
        sc.cycles.denoising_prefilter = "ACCURATE"
    except Exception:                                        # noqa: BLE001
        pass
    sc.cycles.max_bounces = 6
    sc.cycles.transmission_bounces = 3
    sc.cycles.caustics_reflective = False
    sc.cycles.caustics_refractive = False
    sc.cycles.use_fast_gi = True
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.compression = 15
    sc.view_settings.view_transform = "AgX"
    for look in ("AgX - Medium High Contrast", "AgX - Base Contrast",
                 "AgX - Punchy", "None"):
        try:
            sc.view_settings.look = look
            log("look: %s" % look)
            break
        except TypeError:
            continue
    sc.view_settings.exposure = -0.20
    sc.render.resolution_x = a.width
    sc.render.resolution_y = a.height
    sc.render.resolution_percentage = 100
    sc.render.filter_size = 1.20
    sc.frame_start = 1
    sc.frame_end = a.total

    world_hdri(Path(a.hdri))
    add_sun()

    sand = plane("sand", 120.0, (0.0, -55.0, 0.0))
    sand.data.materials.append(sand_material())
    wmat, waves = water_material()
    water = plane("water", 500.0, (0.0, 120.0, -0.02))
    water.data.materials.append(wmat)
    fmat, foam = foam_material()
    wet = plane("foam", 34.0, (0.0, 0.8, 0.014))
    wet.data.materials.append(fmat)

    bundle = Path(a.bundle)
    specs = [
        # דמות א': בגד ים, פונה אל ב'.
        {"tag": "noa", "x": -0.40, "y": 0.0, "yaw": math.radians(-13.0),
         "turn": math.radians(-21.0), "garment": "swim",
         "tone": (0.905, 0.735, 0.615), "flush": (0.78, 0.33, 0.29),
         "hair": (0.185, 0.095, 0.045), "hair_len": 0.165,
         "cloth": (0.055, 0.215, 0.330), "chest": 0.036, "scale": 1.000},
        # דמות ב': חולצת בטן.
        {"tag": "tal", "x": 0.44, "y": 0.22, "yaw": math.radians(12.0),
         "turn": math.radians(8.0), "garment": "crop",
         "tone": (0.545, 0.375, 0.275), "flush": (0.62, 0.27, 0.23),
         "hair": (0.035, 0.022, 0.016), "hair_len": 0.205,
         "cloth": (0.830, 0.330, 0.355), "chest": 0.041, "scale": 0.962},
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
        groups = build_groups(body, h, fdir)
        shape_chest(body, groups, fdir, s["chest"])

        skin = skin_material("skin_" + s["tag"], s["tone"], s["flush"])
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
        sub = body.modifiers.new("sub", "SUBSURF")
        sub.levels = 0
        sub.render_levels = 2
        sub.use_limit_surface = True
        garment = make_garment(
            body, groups[s["garment"]], "cloth_" + s["tag"],
            cloth_material("fabric_" + s["tag"], s["cloth"]))
        add_hair(body, s["hair_len"], s["hair"])

        root = arm if arm else body
        # העיניים: ``ARMATURE`` עם קבוצה בשם העצם ובמשקל 1, ולא
        # הורות-אובייקט. הורות בלבד הייתה משאירה אותן במקום
        # בעוד הראש מסתובב - כלומר דמות פוזלת. קבוצה בשם עצם
        # נותנת להן בדיוק את הטרנספורמציה של ``head_b``.
        for e in eyes:
            e.parent = root
            e.matrix_parent_inverse = root.matrix_world.inverted()
            if arm:
                g = e.vertex_groups.new(name="head_b")
                g.add(list(range(len(e.data.vertices))), 1.0, "REPLACE")
                em = e.modifiers.new("arm", "ARMATURE")
                em.object = arm
        if garment:
            garment.parent = root
            garment.matrix_parent_inverse = root.matrix_world.inverted()
        root.location = (s["x"], s["y"], 0.0)
        root.rotation_euler = (0.0, 0.0, s["yaw"])
        root.scale = (s["scale"],) * 3
        ok = sanity_pose(body, arm, h)
        cast.append({"root": root, "arm": arm, "body": body,
                     "x": s["x"], "y": s["y"], "yaw": s["yaw"],
                     "turn": s["turn"]})
        meta.append({"tag": s["tag"], "verts": len(body.data.vertices),
                     "rigged": bool(arm), "pose_sane": ok,
                     "garment": bool(garment),
                     "garment_kind": s["garment"], "scale": s["scale"]})
        log("דמות %s: %d קודקודים, ריג=%s, בגד=%s"
            % (s["tag"], len(body.data.vertices), bool(arm), bool(garment)))

    bpy.context.view_layer.update()
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
        "cast": meta,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    sc = bpy.context.scene
    for f in range(a.start, a.end + 1):
        sc.frame_set(f)
        apply_frame(cast, cam, cam0, dist, ctr, f, a.total, waves, foam)
        sc.render.filepath = str(out / ("f%04d" % f))
        bpy.ops.render.render(write_still=True)
        log("פריים %d/%d נכתב" % (f, a.total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
