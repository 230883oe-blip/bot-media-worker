import json, os, shutil, time, traceback
from pathlib import Path
from gradio_client import Client, handle_file
os.environ.pop("HF_TOKEN", None)
out = Path("artifacts"); out.mkdir(exist_ok=True)
log = {}
PROMPT = ("Pixar style 3D animated movie, a cute little girl with braids in a yellow dress walking on a sunny "
          "beach, warm cinematic lighting, soft shadows, detailed hair and skin, high quality")
NEG = "worst quality, inconsistent motion, blurry, jittery, distorted, extra limbs"
URL = "https://raw.githubusercontent.com/230883oe-blip/bot-media-worker/main/v2v/input.mp4"
c = Client("Lightricks/ltx-video-distilled", verbose=False)
for name, vid in (("file", handle_file("v2v/input.mp4")), ("url", URL), ("localpath", os.path.abspath("v2v/input.mp4"))):
    t0 = time.time()
    try:
        r = c.predict(prompt=PROMPT, negative_prompt=NEG, input_image_filepath=None,
                      input_video_filepath=vid, height_ui=384, width_ui=704, mode="video-to-video",
                      duration_ui=3, ui_frames_to_use=25, seed_ui=42, randomize_seed=False,
                      ui_guidance_scale=1, improve_texture_flag=True, api_name="/text_to_video")
        v = r[0]; v = v.get("video") if isinstance(v, dict) else v
        log[name] = {"secs": round(time.time() - t0, 1), "path": str(v)}
        if v and os.path.exists(v):
            shutil.copy(v, out / f"v2v_{name}.mp4"); log["ok"] = name
            break
    except Exception as e:
        log[name] = {"secs": round(time.time() - t0, 1), "error": f"{type(e).__name__}: {str(e)[:300]}"}
    time.sleep(6)
(out / "v2v_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(log, ensure_ascii=False, indent=1))
