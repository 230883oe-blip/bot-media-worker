# -*- coding: utf-8 -*-
r"""מדידה: האם שיער העקומות באמת נע עם השלד.

השאלה אינה "האם המודיפייר נוסף" אלא "האם הנקודות זזו". לכן
הסקריפט מעריך את האובייקט דרך ה-depsgraph בשני מצבי פוזה -
ראש ישר מול ראש מסובב - ומשווה את המיקומים בפועל.

    blender -b --factory-startup -P test_hairrig.py -- \
        --bundle <hbm.blend> [--json out/hairrig.json]

קריטריון המעבר (שלושתם, אחרת כישלון):
  * השיער זז מעל 5 מ"מ בממוצע כשהראש מסתובב 25°.
  * התזוזה שלו מתואמת עם תזוזת קודקודי הראש (יחס 0.3..2.0).
  * גוף הדמות אכן זז (אחרת המבחן מדד כלום).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import mathutils

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "studio3d"))
import beach_studio as bs                                      # noqa: E402


def hair_points(ob, dg):
    """מיקומי נקודות העקומות **אחרי** כל המודיפיירים."""
    ev = ob.evaluated_get(dg)
    data = ev.data
    pts = getattr(data, "points", None)
    if pts is None or len(pts) == 0:
        # ``Set Hair Curve Profile`` עשוי להחזיר מש; גם אז יש
        # קודקודים, והם מה שמרונדר.
        vs = getattr(data, "vertices", None)
        if vs is None:
            return []
        return [mathutils.Vector(v.co) for v in vs]
    out = [0.0] * (len(pts) * 3)
    pts.foreach_get("position", out)
    return [mathutils.Vector(out[i:i + 3]) for i in range(0, len(out), 3)]


def head_points(body, dg, zmin):
    ev = body.evaluated_get(dg)
    return [mathutils.Vector(v.co) for v in ev.data.vertices
            if v.co.z > zmin]


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--json", default="")
    ap.add_argument("--strands", type=int, default=2500)
    ap.add_argument("--turn", type=float, default=25.0)
    ap.add_argument("--bare", action="store_true")
    a = ap.parse_args(argv)

    bs.wipe()
    got = bs.load_asset(Path(a.bundle))
    body = got["body"]
    eyes = list(got.get("eyes") or [])
    h = bs.normalize(body, eyes)
    fdir = bs.face_dir(body, eyes)
    groups = bs.build_groups(body, h, fdir, {"sep_top": True})
    bs.clear_face_hair(body, eyes, h, fdir, groups)

    uvname = bs.ensure_uv(body)
    print("UV: %s" % uvname)
    arm = bs.build_rig(body, h)
    if not arm:
        print("נכשל: אין שלד")
        return 2
    curves = bs.hair_curves_asset(
        body, eyes, h, fdir, groups, (0.42, 0.30, 0.14),
        {"hair_len": 0.105, "comb_down": 0.86, "comb_back": 0.46},
        strands=a.strands)
    if not curves:
        print("נכשל: לא נוצר שיער")
        return 2
    curves.parent = arm
    curves.matrix_parent_inverse = arm.matrix_world.inverted()
    if a.bare:
        for m in list(curves.modifiers):
            if m.name != "deform":
                curves.modifiers.remove(m)
        print("מבחן מבודד: רק %s"
              % ", ".join(m.name for m in curves.modifiers))
    at = curves.data.attributes.get("surface_uv_coordinate")
    if at is not None:
        buf = [0.0] * (len(at.data) * 2)
        at.data.foreach_get("vector", buf)
        nz = sum(1 for i in range(0, len(buf), 2)
                 if abs(buf[i]) > 1e-9 or abs(buf[i + 1]) > 1e-9)
        print("surface_uv_coordinate: %d רשומות, %d לא-אפס, דוגמה %s"
              % (len(at.data), nz, buf[:6]))
    else:
        print("surface_uv_coordinate: חסר!")
    print("surface=%s uv_map=%r"
          % (getattr(curves.data, "surface", None),
             getattr(curves.data, "surface_uv_map", None)))

    dg = bpy.context.evaluated_depsgraph_get()
    bpy.context.view_layer.update()
    zmin = h * 0.880
    hair0 = hair_points(curves, dg)
    head0 = head_points(body, dg, zmin)
    print("נקודות שיער: %d · קודקודי ראש: %d" % (len(hair0), len(head0)))
    if not hair0 or not head0:
        print("נכשל: אין מה למדוד")
        return 2

    pb = arm.pose.bones.get("head")
    if not pb:
        print("נכשל: אין עצם ראש")
        return 2
    pb.rotation_mode = "XYZ"
    pb.rotation_euler = (0.0, 0.0, math.radians(a.turn))
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    hair1 = hair_points(curves, dg)
    head1 = head_points(body, dg, zmin)

    if len(hair1) != len(hair0):
        print("אזהרה: מספר נקודות השיער השתנה (%d -> %d)"
              % (len(hair0), len(hair1)))
    n = min(len(hair0), len(hair1))
    d_hair = sum((hair1[i] - hair0[i]).length for i in range(n)) / max(1, n)
    mx_hair = max((hair1[i] - hair0[i]).length for i in range(n)) if n else 0.0
    m = min(len(head0), len(head1))
    d_head = sum((head1[i] - head0[i]).length for i in range(m)) / max(1, m)

    ratio = d_hair / d_head if d_head > 1e-9 else 0.0
    ok_body = d_head > 0.004
    ok_move = d_hair > 0.005
    ok_ratio = 0.30 <= ratio <= 2.0
    res = {
        "turn_deg": a.turn,
        "hair_points": len(hair0),
        "head_verts": len(head0),
        "hair_move_mm": round(d_hair * 1000.0, 2),
        "hair_move_max_mm": round(mx_hair * 1000.0, 2),
        "head_move_mm": round(d_head * 1000.0, 2),
        "ratio": round(ratio, 3),
        "body_moved": ok_body,
        "hair_moved": ok_move,
        "ratio_sane": ok_ratio,
        "pass": bool(ok_body and ok_move and ok_ratio),
        "modifiers": [m.name for m in curves.modifiers],
    }
    print(json.dumps(res, ensure_ascii=False, indent=1))
    if a.json:
        p = Path(a.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(res, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    print("HAIRRIG: %s" % ("עבר" if res["pass"] else "נכשל"))
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
