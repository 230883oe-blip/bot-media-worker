import json, os, shutil, sys, time
from pathlib import Path
from gradio_client import Client, handle_file
os.environ.pop("HF_TOKEN", None)
inp, az, tag = sys.argv[1], float(sys.argv[2]), sys.argv[3]
out = Path("artifacts"); out.mkdir(exist_ok=True); log = {}
for space in ("multimodalart/qwen-image-multiple-angles-3d-camera", "linoyts/Qwen-Image-Edit-Angles"):
    t0 = time.time()
    try:
        c = Client(space, verbose=False)
        r = c.predict(image=handle_file(inp), azimuth=az, elevation=0, distance=1.0, api_name="/infer_camera_edit")
        p = r[0]; p = p.get("path") if isinstance(p, dict) else p
        log[space] = {"secs": round(time.time() - t0, 1), "path": str(p), "prompt": str(r[-1])[:160]}
        if p and os.path.exists(p):
            shutil.copy(p, out / f"{tag}_{int(az)}.png"); log["ok"] = space; break
    except Exception as e:
        log[space] = {"secs": round(time.time() - t0, 1), "error": f"{type(e).__name__}: {str(e)[:300]}"}
(out / f"{tag}_{int(az)}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(log, ensure_ascii=False, indent=1))
