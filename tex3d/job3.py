import json, shutil, time, os, traceback
from pathlib import Path
from gradio_client import Client, handle_file
os.environ.pop("HF_TOKEN", None)
out = Path("artifacts"); out.mkdir(exist_ok=True)
log = {}
def pth(x):
    if isinstance(x, dict): x = x.get("value") or x.get("path")
    if isinstance(x, (list, tuple)):
        x = [pth(i) for i in x]
    return x
def flat(x):
    if isinstance(x, (list, tuple)):
        for i in x: yield from flat(i)
    elif isinstance(x, str): yield x
# 1. Stable-Fast-3D
t0 = time.time()
try:
    c = Client("stabilityai/stable-fast-3d", verbose=False)
    r = c.predict(input_image=handle_file("tex3d/ref_rgba.png"), foreground_ratio=0.85,
                  remesh_option="None", vertex_count=-1, texture_size=1024, api_name="/run_button")
    fs = [f for f in flat(pth(r)) if os.path.exists(f)]
    log["sf3d"] = {"secs": round(time.time() - t0, 1), "files": fs}
    for i, f in enumerate(fs):
        shutil.copy(f, out / f"sf3d_{i}{Path(f).suffix}")
except Exception as e:
    log["sf3d"] = {"secs": round(time.time() - t0, 1), "error": f"{type(e).__name__}: {str(e)[:400]}"}
time.sleep(5)
# 2. Hunyuan3D-2mv generation_all
t0 = time.time()
try:
    c = Client("tencent/Hunyuan3D-2mv", verbose=False)
    r = c.predict(caption=None, image=None, mv_image_front=handle_file("tex3d/ref_rgba.png"),
                  mv_image_back=None, mv_image_left=None, mv_image_right=None, steps=30,
                  guidance_scale=5.0, seed=1234, octree_resolution=256, check_box_rembg=True,
                  num_chunks=8000, randomize_seed=False, api_name="/generation_all")
    fs = [f for f in flat(pth(r[:2])) if os.path.exists(f)]
    log["hy2mv"] = {"secs": round(time.time() - t0, 1), "files": fs}
    for i, f in enumerate(fs):
        shutil.copy(f, out / f"hy2mv_{i}{Path(f).suffix}")
except Exception as e:
    log["hy2mv"] = {"secs": round(time.time() - t0, 1), "error": f"{type(e).__name__}: {str(e)[:400]}"}
(out / "tex_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(log, ensure_ascii=False, indent=1))
