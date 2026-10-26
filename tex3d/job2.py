import json, shutil, time, os, io, contextlib, traceback
from pathlib import Path
from gradio_client import Client, handle_file
os.environ.pop("HF_TOKEN", None)
out = Path("artifacts"); out.mkdir(exist_ok=True)
log = {}
def pth(x):
    if isinstance(x, dict): x = x.get("value") or x.get("path") or x.get("video")
    if isinstance(x, (list, tuple)): x = x[0]
    return x
CANDS = ["microsoft/TRELLIS", "JeffreyXiang/TRELLIS", "TencentARC/InstantMesh",
         "stabilityai/stable-fast-3d", "VAST-AI/TripoSR", "tencent/Hunyuan3D-2mini",
         "tencent/Hunyuan3D-2mv", "frogleo/Image-to-3D"]
apis = {}
clients = {}
for s in CANDS:
    try:
        c = Client(s, verbose=False); clients[s] = c
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            a = c.view_api(return_format="dict")
        apis[s] = {n: [(p.get("parameter_name"), p.get("parameter_default")) for p in i["parameters"]]
                   for n, i in (a.get("named_endpoints") or {}).items()}
    except Exception as e:
        apis[s] = f"ERR {type(e).__name__}: {str(e)[:150]}"
(out / "apis.json").write_text(json.dumps(apis, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

# TRELLIS
for s in ("microsoft/TRELLIS", "JeffreyXiang/TRELLIS"):
    c = clients.get(s)
    if not c: continue
    t0 = time.time()
    try:
        try: c.predict(api_name="/start_session")
        except Exception as e: log[s + "_session"] = str(e)[:120]
        r = c.predict(image=handle_file("tex3d/ref.png"), multiimages=[], seed=0,
                      ss_guidance_strength=7.5, ss_sampling_steps=12,
                      slat_guidance_strength=3.0, slat_sampling_steps=12,
                      multiimage_algo="stochastic", api_name="/image_to_3d")
        log[s + "_i2_3d"] = {"secs": round(time.time() - t0, 1), "raw": str(r)[:200]}
        r2 = c.predict(mesh_simplify=0.95, texture_size=1024, api_name="/extract_glb")
        p = pth(r2)
        log[s + "_glb"] = {"secs": round(time.time() - t0, 1), "path": str(p)}
        if p and os.path.exists(p):
            shutil.copy(p, out / "trellis.glb"); log["ok"] = s
            break
    except Exception as e:
        log[s] = f"{type(e).__name__}: {str(e)[:400]}"
(out / "tex_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(log, ensure_ascii=False, indent=1))
