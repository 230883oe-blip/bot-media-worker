import json, os, re, shutil, sys, time
from pathlib import Path
from gradio_client import Client, handle_file
import av
os.environ.pop("HF_TOKEN", None)
idx = int(sys.argv[1]); inp = sys.argv[2]
STYLE = ("Pixar style 3D animated movie, a cute little girl with two long black braids, brown eyes and rosy cheeks, "
         "wearing a yellow dress and yellow sandals, on a sunny tropical beach, warm cinematic lighting, soft shadows, "
         "detailed skin and hair, high quality, ")
ACT = ["she smiles and starts walking toward the camera, braids swinging",
       "she keeps walking toward the camera with a happy smile, natural arm swing",
       "she keeps walking and tilts her head, looking around the beach happily",
       "she slows down, stops and waves at the camera with a big smile"][idx - 1]
NEG = "worst quality, inconsistent motion, blurry, jittery, distorted, extra limbs, deformed face, different person"
out = Path("artifacts"); out.mkdir(exist_ok=True); log = {"clip": idx, "tries": []}
c = Client("Lightricks/ltx-video-distilled", verbose=False)
ok = False
for attempt in range(1, 6):
    t0 = time.time()
    try:
        r = c.predict(prompt=STYLE + ACT, negative_prompt=NEG, input_image_filepath=handle_file(inp),
                      input_video_filepath=None, height_ui=384, width_ui=704, mode="image-to-video",
                      duration_ui=4, ui_frames_to_use=9, seed_ui=42 + idx, randomize_seed=False,
                      ui_guidance_scale=1, improve_texture_flag=True, api_name="/image_to_video")
        v = r[0]; v = v.get("video") if isinstance(v, dict) else v
        if v and os.path.exists(v):
            shutil.copy(v, out / f"clip_{idx}.mp4"); ok = True
            log["tries"].append({"n": attempt, "secs": round(time.time() - t0, 1), "ok": True}); break
    except Exception as e:
        log["tries"].append({"n": attempt, "secs": round(time.time() - t0, 1), "err": f"{type(e).__name__}: {str(e)[:140]}"})
        time.sleep(30)
if ok:
    cont = av.open(str(out / f"clip_{idx}.mp4")); last = None
    for f in cont.decode(video=0): last = f
    last.to_image().save(out / f"last_{idx}.png"); log["frames_ok"] = True
(out / f"log_{idx}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(log, ensure_ascii=False, indent=1))
if not ok: sys.exit(1)
