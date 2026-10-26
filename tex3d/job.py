import json, shutil, time, os, sys, traceback
from pathlib import Path
from gradio_client import Client, handle_file
os.environ.pop("HF_TOKEN", None)
out = Path("artifacts"); out.mkdir(exist_ok=True)
log = {}
def path_of(x):
    if isinstance(x, dict): x = x.get("value") or x.get("path")
    if isinstance(x, (list, tuple)): x = x[0]
    return x
for space in ("tencent/Hunyuan3D-2.1", "tencent/Hunyuan3D-2"):
    tag = space.split("/")[1]
    t0 = time.time()
    try:
        c = Client(space, verbose=False)
        kw = dict(image=handle_file("tex3d/ref.png"), mv_image_front=None, mv_image_back=None,
                  mv_image_left=None, mv_image_right=None, steps=30, guidance_scale=5.0,
                  seed=1234, octree_resolution=256, check_box_rembg=True, num_chunks=8000,
                  randomize_seed=False, api_name="/generation_all")
        if tag == "Hunyuan3D-2":
            kw["caption"] = None
        res = c.predict(**kw)
        files = [path_of(r) for r in res[:2]]
        log[tag] = {"secs": round(time.time() - t0, 1), "files": files, "raw": str(res)[:400]}
        for i, f in enumerate(files):
            if f and os.path.exists(f):
                shutil.copy(f, out / f"{tag}_{i}{Path(f).suffix}")
                log[tag][f"size_{i}"] = os.path.getsize(f)
        if any(f and os.path.exists(f) for f in files[1:]):
            break
    except Exception as e:
        log[tag] = {"secs": round(time.time() - t0, 1), "error": f"{type(e).__name__}: {str(e)[:400]}"}
        traceback.print_exc()
    time.sleep(5)
(out / "tex_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(log, ensure_ascii=False, indent=1))
