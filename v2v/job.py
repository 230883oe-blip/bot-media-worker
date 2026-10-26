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
import re
def run(vid):
    return c.predict(prompt=PROMPT, negative_prompt=NEG, input_image_filepath=None,
                     input_video_filepath=vid, height_ui=384, width_ui=704, mode="video-to-video",
                     duration_ui=3, ui_frames_to_use=25, seed_ui=42, randomize_seed=False,
                     ui_guidance_scale=1, improve_texture_flag=True, api_name="/text_to_video")
server_path = None
t0 = time.time()
try:
    run(handle_file("v2v/input_704.mp4"))                      # מעלה את הקובץ לשרת; נכשל אבל חושף את הנתיב
except Exception as e:
    m = re.search(r"'path': '([^']+)'", str(e))
    server_path = m.group(1) if m else None
    log["upload_probe"] = {"secs": round(time.time() - t0, 1), "server_path": server_path}
COMBOS = [(2, 25, 704, 384), (2, 9, 704, 384), (2, 49, 704, 384)]
if server_path:
    def runc(vid, d, fr, w, h):
        return c.predict(prompt=PROMPT, negative_prompt=NEG, input_image_filepath=None,
                         input_video_filepath=vid, height_ui=h, width_ui=w, mode="video-to-video",
                         duration_ui=d, ui_frames_to_use=fr, seed_ui=42, randomize_seed=False,
                         ui_guidance_scale=1, improve_texture_flag=False, api_name="/text_to_video")
    for d, fr, w, h in COMBOS:
        key = f"d{d}_f{fr}_{w}x{h}"
        t0 = time.time()
        try:
            r = runc(server_path, d, fr, w, h)
            v = r[0]; v = v.get("video") if isinstance(v, dict) else v
            log[key] = {"secs": round(time.time() - t0, 1), "path": str(v)}
            if v and os.path.exists(v):
                shutil.copy(v, out / f"v2v_{key}.mp4"); log["ok"] = key
                break
        except Exception as e:
            log[key] = {"secs": round(time.time() - t0, 1), "error": f"{type(e).__name__}: {str(e)[:160]}"}
        time.sleep(4)
(out / "v2v_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(log, ensure_ascii=False, indent=1))
