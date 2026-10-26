import bpy, sys, math, os
from mathutils import Vector

glb, outdir, mode = sys.argv[sys.argv.index("--") + 1:][:3]
os.makedirs(outdir, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
mat = bpy.data.materials.new("clay"); mat.use_nodes = True
b = mat.node_tree.nodes["Principled BSDF"]
b.inputs["Base Color"].default_value = (0.9, 0.78, 0.6, 1)
b.inputs["Roughness"].default_value = 0.55
try:
    b.inputs["Subsurface Weight"].default_value = 0.15
except KeyError:
    pass
for m in meshes:
    m.data.materials.clear(); m.data.materials.append(mat)
    for p in m.data.polygons: p.use_smooth = True

pts = [m.matrix_world @ Vector(c) for m in meshes for c in m.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
ctr = (lo + hi) / 2; size = max(hi - lo)

sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.use_denoising = True
still = mode == "still"
sc.cycles.samples = 128 if still else 24
sc.render.resolution_x, sc.render.resolution_y = (800, 1000) if still else (384, 480)
sc.world = bpy.data.worlds.new("w"); sc.world.use_nodes = True
sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.8, 0.84, 0.9, 1)
sc.world.node_tree.nodes["Background"].inputs[1].default_value = 0.8
def light(name, kind, energy, rot, size_=3):
    l = bpy.data.lights.new(name, kind); l.energy = energy
    if kind == "AREA": l.size = size_
    o = bpy.data.objects.new(name, l); sc.collection.objects.link(o)
    o.location = ctr + Vector((0, 0, size)) ; o.rotation_euler = rot
light("key", "SUN", 3.0, (math.radians(55), 0, math.radians(35)))
light("rim", "SUN", 1.5, (math.radians(60), 0, math.radians(-150)))
cam = bpy.data.cameras.new("c"); cam.lens = 70
co = bpy.data.objects.new("c", cam); sc.collection.objects.link(co); sc.camera = co

def shoot(deg, path):
    a = math.radians(deg); d = size * 2.6
    co.location = ctr + Vector((math.sin(a) * d, -math.cos(a) * d, 0))
    co.rotation_euler = (ctr - co.location).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)

if still:
    for ang in (0, 45, 90, 180):
        shoot(ang, f"{outdir}/still_{ang:03d}.png")
else:
    for i in range(24):
        shoot(i * 15, f"{outdir}/t_{i:03d}.png")
