# -*- coding: utf-8 -*-
r"""עבודת ענן 2/3: Blender על רנר מרוחק - שוט החוף, שתי דמויות.

רץ **בתוך** בלנדר:
    blender -b --factory-startup -P beach_blender.py -- \
        --glb nava.glb --arkit arkit.json --out artifacts/frames \
        --start 1 --end 10 --total 120

מדיניות. הכול כאן קורה על רנר של GitHub Actions. אין בלנדר
מקומי בשרשרת הזו, גם לא לבדיקה - עבודת ``smoke`` בענן היא
שמוודאת שהסקריפט רץ לפני שהמטריצה נדלקת.

העלילה - **זהה למשימה הקודמת** (``beach_shot.py``), כדי שההשוואה
תהיה חוקית: שתי דמויות נשיות על קו המים, גוף מלא מכף רגל עד
ראש, מצלמה נעולה, רוח ים בשיער, אחת מפנה את ראשה אל השנייה
ומחייכת, גלים רדודים סביב הרגליים, אור יום בהיר.

מה שונה מהמשימה הקודמת, ובכוונה
--------------------------------
1. **הקאדר מאומת גאומטרית ולא מקוּוה.** בריצה הקודמת שתיים
   מארבע הפקודות הורו למצלמה לזוז, והרגליים נחתכו בשש
   מהפריימים. מודל i2v אי אפשר לאלץ. מצלמה בבלנדר **כן**:
   ``fit_camera`` מקרין את שמונה פינות תיבת החסימה של שתי
   הדמויות אל מרחב המצלמה ומרחיק אותה עד שכל הפינות בתוך
   ``0..1`` עם שולי ביטחון. אם לא הצליח - הריצה נופלת.
2. **הפה מונע ממודל של NVIDIA.** ``arkit.json`` מגיע מעבודת
   ה-A2F, ו-28 מ-52 משקלי ה-ARKit יש להם בלנדשייפ מקביל בנכס.
   ``jawOpen`` אינו בלנדשייפ בנכס והוא מופעל על **עצם הלסת**.
3. **אין מצלמה שזזה בכלל.** נעולה על חצובה, כפי שנרשם שם.

מלכודות שנסגרו כאן מראש
------------------------
* **אין ``bpy.ops.object.mode_set``.** ברקע הקונטקסט לא תמיד
  מאפשר מעבר מצבים; ``pose.bones[..].rotation_euler`` עובד
  בלי מצב עריכה כלל.
* **כיוון סיבוב של עצם אינו ידוע מראש** - הוא תלוי בכיוון
  שבו ה-glTF ייצא את העצם. ``pose_arms`` **מודד**: מנסה שלושה
  צירים בשני סימנים ובוחר את זה שמצמצם את מפתח הידיים.
* **הנכס הוא 24MB לא דחוס.** נדחס ל-1.8MB (ריפוד אפסים), ולכן
  נשלח דרך contents API בלי LFS.
* **``to_mesh`` חייב ``to_mesh_clear``** אחרת כל מדידה מדליפה
  רשת ו-40k קודקודים × 10 מדידות הם 2GB.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy                                                  # noqa: E402
from mathutils import Vector                                # noqa: E402

# ---------------------------------------------------------------- מפת ARKit

#: 28 מ-52 משקלי ARKit -> בלנדשייפים של הנכס. שמות הנכס נקראו
#: מתוך ``targetNames`` של ה-GLB ולא נוחשו, ושמות ה-ARKit מתוך
#: ``bs_skin_config_Claire.npz`` של NVIDIA.
#:
#: 24 המשקלים שאין להם מקביל (עיניים, גבות, לשון, jawLeft/Right)
#: מוצהרים חסרים ולא מוסתרים: לנכס אין בלנדשייפ גבה ולשון.
ARKIT_TO_MORPH = {
    "mouthClose": "mouth_close",
    "mouthPucker": "lip_pucker",
    "mouthFunnel": "lip_funnel",
    "mouthSmileLeft": "mouth_corner_up_L",
    "mouthSmileRight": "mouth_corner_up_R",
    "mouthFrownLeft": "mouth_corner_down_L",
    "mouthFrownRight": "mouth_corner_down_R",
    "mouthStretchLeft": "mouth_stretch_L",
    "mouthStretchRight": "mouth_stretch_R",
    "mouthDimpleLeft": "mouth_dimple_L",
    "mouthDimpleRight": "mouth_dimple_R",
    "mouthPressLeft": "lip_press_L",
    "mouthPressRight": "lip_press_R",
    "mouthLowerDownLeft": "lip_lo_depress_L",
    "mouthLowerDownRight": "lip_lo_depress_R",
    "mouthUpperUpLeft": "lip_up_raise_L",
    "mouthUpperUpRight": "lip_up_raise_R",
    "mouthRollUpper": "lip_roll_up",
    "mouthRollLower": "lip_roll_lo",
    "mouthShrugUpper": "lip_shrug_up",
    "mouthShrugLower": "lip_shrug_lo",
    "mouthLeft": "mouth_shift_L",
    "mouthRight": "mouth_shift_R",
    "noseSneerLeft": "nose_sneer_L",
    "noseSneerRight": "nose_sneer_R",
    "cheekSquintLeft": "cheek_raise_L",
    "cheekSquintRight": "cheek_raise_R",
    "jawForward": "jaw_thrust",
}

#: ``jawOpen`` אינו בלנדשייפ בנכס. פתיחה מלאה = 17 מעלות על
#: עצם ``jaw``. מעבר לזה הלסת נפרדת מהפנים בעין.
JAW_DEG = 17.0

# ---------------------------------------------------------------- כלים

def log(*a):
    print(*a, flush=True)


def wipe():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def world_bbox(obs):
    """תיבת חסימה במרחב העולם של רשתות **אחרי** מודיפיירים."""
    dg = bpy.context.evaluated_depsgraph_get()
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for ob in obs:
        oe = ob.evaluated_get(dg)
        me = oe.to_mesh()
        mw = ob.matrix_world
        for v in me.vertices:
            w = mw @ v.co
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
        oe.to_mesh_clear()
    return lo, hi


def principled(mat):
    if not mat or not mat.use_nodes:
        return None
    for n in mat.node_tree.nodes:
        if n.type == "BSDF_PRINCIPLED":
            return n
    return None


# ---------------------------------------------------------------- סצנה

def build_world(sun_elev_deg: float = 42.0):
    """שמי Nishita + שמש. אור יום בהיר על מים, כמו בשוט הקודם."""
    w = bpy.data.worlds.new("beach")
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    sky = nt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(sun_elev_deg)
    sky.sun_rotation = math.radians(150.0)
    sky.altitude = 0.0
    sky.air_density = 1.0
    sky.dust_density = 0.6
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = 0.9
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(sky.outputs[0], bg.inputs[0])
    nt.links.new(bg.outputs[0], out.inputs[0])

    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    bpy.context.collection.objects.link(sun)
    sun.data.energy = 4.0
    sun.data.angle = math.radians(2.0)
    sun.rotation_euler = (math.radians(90 - sun_elev_deg),
                          0.0, math.radians(150.0))
    return sky


def plane(name: str, size: float, loc, rot=(0, 0, 0)):
    me = bpy.data.meshes.new(name)
    h = size / 2.0
    me.from_pydata([(-h, -h, 0), (h, -h, 0), (h, h, 0), (-h, h, 0)],
                   [], [(0, 1, 2, 3)])
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    ob.rotation_euler = rot
    bpy.context.collection.objects.link(ob)
    return ob


def sand_material():
    mat = bpy.data.materials.new("sand")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    co = nt.nodes.new("ShaderNodeTexCoord")
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 180.0
    nz.inputs["Detail"].default_value = 8.0
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.35
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.74, 0.63, 0.46, 1)
    ramp.color_ramp.elements[1].color = (0.90, 0.82, 0.66, 1)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.92
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(co.outputs["Object"], nz.inputs["Vector"])
    nt.links.new(nz.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(nz.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return mat


def water_material():
    """מים + ``w`` של הרעש כידית אנימציה לגלים."""
    mat = bpy.data.materials.new("water")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    co = nt.nodes.new("ShaderNodeTexCoord")
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.noise_dimensions = "4D"
    nz.inputs["Scale"].default_value = 7.0
    nz.inputs["Detail"].default_value = 6.0
    nz.name = "waves"
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.22
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (0.06, 0.26, 0.31, 1)
    bsdf.inputs["Roughness"].default_value = 0.09
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(co.outputs["Object"], nz.inputs["Vector"])
    nt.links.new(nz.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return mat, nz


def foam_material():
    """קו קצף רדוד סביב הרגליים - לבן שקוף-למחצה."""
    mat = bpy.data.materials.new("foam")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    co = nt.nodes.new("ShaderNodeTexCoord")
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.noise_dimensions = "4D"
    nz.inputs["Scale"].default_value = 11.0
    nz.name = "foam_noise"
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.52
    ramp.color_ramp.elements[1].position = 0.66
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (1, 1, 1, 1)
    bsdf.inputs["Roughness"].default_value = 0.5
    mix = nt.nodes.new("ShaderNodeMixShader")
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(co.outputs["Object"], nz.inputs["Vector"])
    nt.links.new(nz.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], mix.inputs["Fac"])
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(bsdf.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs[0])
    mat.blend_method = "BLEND"
    return mat, nz


# ---------------------------------------------------------------- דמויות

def import_char(glb: Path, tag: str):
    """מחזיר ``(armature, mesh)``. ה-GLB מכיל רשת אחת ושלד אחד."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    new = [o for o in bpy.data.objects if o not in before]
    arm = next((o for o in new if o.type == "ARMATURE"), None)
    mesh = next((o for o in new if o.type == "MESH"), None)
    if not arm or not mesh:
        raise SystemExit("ייבוא נכשל: שלד=%s רשת=%s" % (bool(arm), bool(mesh)))
    for o in new:
        o.name = "%s_%s" % (tag, o.name)
    for o in new:
        if o.parent is None:
            o.rotation_mode = "XYZ"
    return arm, mesh


def bone(arm, name: str):
    """עצם לפי סיומת - שמות העצמות קיבלו תחילית בייבוא."""
    pb = arm.pose.bones
    if name in pb:
        return pb[name]
    for b in pb:
        if b.name == name or b.name.endswith("_" + name):
            return b
    return None


def set_rot(arm, name: str, x=0.0, y=0.0, z=0.0):
    b = bone(arm, name)
    if not b:
        return False
    b.rotation_mode = "XYZ"
    b.rotation_euler = (math.radians(x), math.radians(y), math.radians(z))
    return True


def pose_arms(arm, mesh) -> dict:
    """מוריד את הידיים - **במדידה ולא בניחוש**.

    הנכס מיוצא בפוזת A/T (מפתח ידיים 1.78 מ' על ציר X). כיוון
    הסיבוב שמוריד זרוע תלוי בכיוון העצם ב-glTF ואינו ידוע מראש,
    לכן כאן נמדדות שש אפשרויות (3 צירים × 2 סימנים) ונבחרת זו
    שמצמצמת את המפתח. בלי זה היה 50% סיכוי לזרועות שמצביעות
    למעלה - תקלה שעוברת קומפילציה בשקט.
    """
    base_lo, base_hi = world_bbox([mesh])
    base_w = base_hi.x - base_lo.x
    best = (base_w, None, None)
    for ax in range(3):
        for sg in (1.0, -1.0):
            for nm in ("upperarm_L", "upperarm_R"):
                v = [0.0, 0.0, 0.0]
                s = sg if nm.endswith("_L") else -sg
                v[ax] = 62.0 * s
                set_rot(arm, nm, *v)
            bpy.context.view_layer.update()
            lo, hi = world_bbox([mesh])
            w = hi.x - lo.x
            if w < best[0]:
                best = (w, ax, sg)
    for nm in ("upperarm_L", "upperarm_R"):
        set_rot(arm, nm, 0, 0, 0)
    if best[1] is None:
        log("  ! הורדת ידיים לא שיפרה דבר - נשאר בפוזת הייצוא")
        return {"arms_posed": False, "span_before": round(base_w, 3)}
    ax, sg = best[1], best[2]
    for nm, ang in (("upperarm_L", 62.0), ("upperarm_R", 62.0),
                    ("forearm_L", 16.0), ("forearm_R", 16.0)):
        v = [0.0, 0.0, 0.0]
        s = sg if nm.endswith("_L") else -sg
        v[ax] = ang * s
        set_rot(arm, nm, *v)
    bpy.context.view_layer.update()
    lo, hi = world_bbox([mesh])
    log("  ידיים: מפתח %.2f -> %.2f מ' (ציר %d, סימן %+.0f)"
        % (base_w, hi.x - lo.x, ax, sg))
    return {"arms_posed": True, "axis": ax, "sign": sg,
            "span_before": round(base_w, 3),
            "span_after": round(float(hi.x - lo.x), 3)}


def recolor(mesh, skin, hair, eye_dark: bool = False):
    """מעתיק את החומרים ומחליף צבע בסיס - שתי דמויות נפרדות.

    בלי העתקה, שינוי על הדמות השנייה היה משנה גם את הראשונה:
    ``import_scene.gltf`` מאחד חומרים בעלי אותו שם.
    """
    got = []
    for i, sl in enumerate(mesh.material_slots):
        if not sl.material:
            continue
        m = sl.material.copy()
        m.name = sl.material.name.split(".")[0] + "_b"
        sl.material = m
        p = principled(m)
        if not p:
            continue
        nm = m.name
        if nm.startswith("skin"):
            p.inputs["Base Color"].default_value = (*skin, 1)
            p.inputs["Roughness"].default_value = 0.42
            if "Subsurface Weight" in p.inputs:
                p.inputs["Subsurface Weight"].default_value = 0.14
                p.inputs["Subsurface Radius"].default_value = (0.9, 0.3, 0.2)
        elif nm.startswith("hair"):
            p.inputs["Base Color"].default_value = (*hair, 1)
            p.inputs["Roughness"].default_value = 0.34
        elif nm.startswith("eye"):
            p.inputs["Base Color"].default_value = (
                (0.08, 0.05, 0.04, 1) if eye_dark else (0.16, 0.26, 0.30, 1))
            p.inputs["Roughness"].default_value = 0.08
        got.append(m.name)
    return got


def identity_morphs(mesh, offs: dict):
    """הטיית זהות קבועה דרך הבלנדשייפים - שתי פנים ולא אחת."""
    kb = mesh.data.shape_keys
    if not kb:
        return 0
    n = 0
    for k, v in offs.items():
        if k in kb.key_blocks:
            kb.key_blocks[k].value = float(v)
            n += 1
    return n


# ---------------------------------------------------------------- מצלמה

def fit_camera(obs, lens: float = 50.0, margin: float = 0.08,
               res=(960, 540)) -> dict:
    """מצלמה נעולה שמכילה **את כל** תיבת החסימה, במדידה.

    זו התקלה המדויקת של הריצה הקודמת: מודל הווידאו חתך כפות
    רגליים ב-6 מ-15 פריימים שנדגמו. כאן שמונה פינות התיבה
    מוקרנות למרחב המצלמה, והמצלמה נסוגה עד שכולן בתוך
    ``margin..1-margin``. אם 40 צעדים לא הספיקו - נפילה, לא
    פריים חתוך.
    """
    from bpy_extras.object_utils import world_to_camera_view

    sc = bpy.context.scene
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    bpy.context.collection.objects.link(cam)
    sc.camera = cam
    cam.data.lens = lens
    sc.render.resolution_x, sc.render.resolution_y = res

    lo, hi = world_bbox(obs)
    mid = (lo + hi) / 2.0
    height = hi.z - lo.z
    # גובה המצלמה בשני שליש הגוף - עין אנושית, לא מרכז גאומטרי.
    cz = lo.z + height * 0.60
    dist = 4.0
    corners = [Vector((x, y, z)) for x in (lo.x, hi.x)
               for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    for step in range(40):
        cam.location = (mid.x, lo.y - dist, cz)
        # מביט לכיוון +Y, אופק ישר. ללא סיבוב סביב Y - אין הטיה.
        cam.rotation_euler = (math.radians(90.0), 0.0, 0.0)
        bpy.context.view_layer.update()
        uv = [world_to_camera_view(sc, cam, c) for c in corners]
        u0 = min(p.x for p in uv)
        u1 = max(p.x for p in uv)
        v0 = min(p.y for p in uv)
        v1 = max(p.y for p in uv)
        ok = (u0 > margin and u1 < 1 - margin
              and v0 > margin and v1 < 1 - margin)
        if ok:
            log("  מצלמה: %.2f מ' · קאדר u[%.3f,%.3f] v[%.3f,%.3f]"
                % (dist, u0, u1, v0, v1))
            return {"distance": round(dist, 3), "lens": lens,
                    "frame_u": [round(u0, 4), round(u1, 4)],
                    "frame_v": [round(v0, 4), round(v1, 4)],
                    "margin": margin, "steps": step,
                    "subject_height_m": round(float(height), 3),
                    "fits": True}
        dist *= 1.12
    raise SystemExit("fit_camera: 40 צעדים ולא הצליח להכיל את הגוף המלא")


# ---------------------------------------------------------------- בימוי

def beat(frame: int, total: int) -> dict:
    """ארבע הפעימות של השוט הקודם, בזמן ולא בטקסט.

    0.00-0.25 נשימה והבהוב · 0.20-0.60 אחת מפנה ראש אל השנייה
    ומחייכת · 0.45-0.80 רוח ים בשיער · 0.75-1.00 רגע סוגר רגוע.
    """
    t = (frame - 1) / float(max(total - 1, 1))

    def ramp(a, b):
        if t <= a:
            return 0.0
        if t >= b:
            return 1.0
        x = (t - a) / (b - a)
        return x * x * (3 - 2 * x)

    turn = ramp(0.18, 0.46) * (1.0 - 0.25 * ramp(0.80, 1.0))
    smile = ramp(0.30, 0.58)
    breath = math.sin(t * math.pi * 2.0 * 1.6)
    breeze = math.sin(t * math.pi * 2.0 * 2.3)
    breeze2 = math.sin(t * math.pi * 2.0 * 1.7 + 1.1)
    sway = math.sin(t * math.pi * 2.0 * 0.8)
    return {"t": t, "turn": turn, "smile": smile, "breath": breath,
            "breeze": breeze, "breeze2": breeze2, "sway": sway}


def apply_frame(cast, arkit, frame: int, total: int, waves, foam):
    b = beat(frame, total)
    wi = min(frame - 1, len(arkit["weights"]) - 1)
    w = arkit["weights"][wi]
    nmi = {n: i for i, n in enumerate(arkit["names"])}

    for ci, c in enumerate(cast):
        arm, mesh = c["arm"], c["mesh"]
        kb = mesh.data.shape_keys
        speaks = c["speaks"]

        # --- פה: NVIDIA Audio2Face על הדוברת, מנוחה על המאזינה
        if kb:
            for k, v in c["ident"].items():
                if k in kb.key_blocks:
                    kb.key_blocks[k].value = float(v)
            for ark, mo in ARKIT_TO_MORPH.items():
                if mo not in kb.key_blocks or ark not in nmi:
                    continue
                val = float(w[nmi[ark]]) if speaks else 0.0
                val += float(c["ident"].get(mo, 0.0))
                if mo in ("mouth_corner_up_L", "mouth_corner_up_R"):
                    val += b["smile"] * (0.55 if not speaks else 0.30)
                kb.key_blocks[mo].value = max(0.0, min(1.0, val))

        # --- לסת: ``jawOpen`` אינו בלנדשייפ בנכס, אלא עצם
        jo = float(w[nmi["jawOpen"]]) if (speaks and "jawOpen" in nmi) else 0.0
        set_rot(arm, "jaw", x=jo * JAW_DEG)

        # --- נשימה: חזה + בית חזה, אמפליטודה קטנה בכוונה
        set_rot(arm, "spine_02", x=0.8 + b["breath"] * 0.9)
        set_rot(arm, "chest", x=b["breath"] * 0.7)

        # --- הפניית ראש: הדוברת פונה אל המאזינה ובחזרה
        d = 1.0 if ci == 0 else -1.0
        set_rot(arm, "head", z=b["turn"] * 19.0 * d,
                x=-b["turn"] * 3.0)
        set_rot(arm, "neck", z=b["turn"] * 8.0 * d)

        # --- רוח ים בשיער: ארבע עצמות שיער בפאזות שונות
        ph = 0.0 if ci == 0 else 2.1
        bz = math.sin((b["t"] * math.pi * 2.0 * 2.3) + ph)
        bz2 = math.sin((b["t"] * math.pi * 2.0 * 1.7) + ph + 1.1)
        set_rot(arm, "hair_front", x=bz * 3.4, z=bz2 * 2.2)
        set_rot(arm, "hair_side_L", x=bz * 5.1, y=bz2 * 3.0)
        set_rot(arm, "hair_side_R", x=bz2 * 5.1, y=bz * 3.0)
        set_rot(arm, "hair_back", x=bz2 * 4.2)

        # --- העברת משקל על החול, לא ריחוף
        set_rot(arm, "hips", y=b["sway"] * 1.6 * d)
        arm.location = (c["x"] + b["sway"] * 0.012 * d, c["y"], 0.0)

    # --- גלים: ``w`` של רעש 4D הוא ציר הזמן של המים
    waves.inputs["W"].default_value = b["t"] * 2.4
    foam.inputs["W"].default_value = b["t"] * 3.1
    bpy.context.view_layer.update()
    return b


# ---------------------------------------------------------------- ראשי

def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True)
    ap.add_argument("--arkit", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    ap.add_argument("--total", type=int, default=120)
    ap.add_argument("--samples", type=int, default=28)
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--height", type=int, default=540)
    a = ap.parse_args(argv)

    arkit = json.loads(Path(a.arkit).read_text(encoding="utf-8"))
    log("== ARKit: %d פריימים · %s" % (arkit["frames"], arkit["model"]))

    wipe()
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = a.samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.02
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:                                        # noqa: BLE001
        pass
    sc.cycles.max_bounces = 5
    sc.cycles.transmission_bounces = 2
    sc.cycles.caustics_reflective = False
    sc.cycles.caustics_refractive = False
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = "PNG"
    sc.view_settings.view_transform = "Filmic"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.25

    build_world()

    sand = plane("sand", 90.0, (0.0, 6.0, 0.0))
    sand.data.materials.append(sand_material())
    wmat, waves = water_material()
    water = plane("water", 240.0, (0.0, 62.0, -0.03))
    water.data.materials.append(wmat)
    fmat, foam = foam_material()
    wet = plane("foam", 26.0, (0.0, 2.4, 0.012))
    wet.data.materials.append(fmat)

    glb = Path(a.glb)
    # שתי דמויות נשיות, גובה ומראה שונים. אותה רשת בסיס בכוונה:
    # ההבדל נמדד בפרופורציה, בגוון ובהטיית הבלנדשייפים - ולא
    # נטען על סמך שני קבצים שונים.
    specs = [
        {"tag": "noa", "x": -0.46, "y": 0.0, "scale": 1.00,
         "skin": (0.78, 0.60, 0.48), "hair": (0.86, 0.72, 0.38),
         "eye_dark": False, "speaks": True,
         "ident": {"cheek_hollow_L": 0.18, "cheek_hollow_R": 0.18,
                   "lip_up_raise_L": 0.07, "lip_up_raise_R": 0.07}},
        {"tag": "tal", "x": 0.50, "y": 0.26, "scale": 0.945,
         "skin": (0.55, 0.39, 0.29), "hair": (0.10, 0.07, 0.06),
         "eye_dark": True, "speaks": False,
         "ident": {"cheek_raise_L": 0.13, "cheek_raise_R": 0.13,
                   "nose_flare": 0.16, "mouth_shift_L": 0.05}},
    ]
    cast, info = [], []
    for s in specs:
        arm, mesh = import_char(glb, s["tag"])
        arm.location = (s["x"], s["y"], 0.0)
        arm.scale = (s["scale"],) * 3
        arm.rotation_euler = (0.0, 0.0,
                              math.radians(-9.0 if s["speaks"] else 9.0))
        bpy.context.view_layer.update()
        pa = pose_arms(arm, mesh)
        mats = recolor(mesh, s["skin"], s["hair"], s["eye_dark"])
        nm = identity_morphs(mesh, s["ident"])
        cast.append({"arm": arm, "mesh": mesh, "x": s["x"], "y": s["y"],
                     "speaks": s["speaks"], "ident": s["ident"]})
        info.append({"tag": s["tag"], "scale": s["scale"], "arms": pa,
                     "materials": mats, "identity_morphs": nm,
                     "shape_keys": len(mesh.data.shape_keys.key_blocks)
                     if mesh.data.shape_keys else 0})
        log("  %s: %d בלנדשייפים · %d הטיות זהות · חומרים %s"
            % (s["tag"], info[-1]["shape_keys"], nm, mats))

    apply_frame(cast, arkit, 1, a.total, waves, foam)
    camf = fit_camera([c["mesh"] for c in cast],
                      res=(a.width, a.height))

    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    meta = {"camera": camf, "cast": info, "total": a.total,
            "samples": a.samples, "res": [a.width, a.height],
            "arkit_mapped": len(ARKIT_TO_MORPH),
            "arkit_total": len(arkit["names"]),
            "engine": "blender %s · CYCLES · CPU" % bpy.app.version_string,
            "a2f_model": arkit["model"]}
    (outdir.parent / "blender_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    import time
    for f in range(a.start, a.end + 1):
        t0 = time.perf_counter()
        b = apply_frame(cast, arkit, f, a.total, waves, foam)
        sc.render.filepath = str(outdir / ("f%04d.png" % f))
        bpy.ops.render.render(write_still=True)
        log("  פריים %d/%d · t=%.3f · %.1fs"
            % (f, a.total, b["t"], time.perf_counter() - t0))
    log("== הסתיים: פריימים %d..%d" % (a.start, a.end))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
