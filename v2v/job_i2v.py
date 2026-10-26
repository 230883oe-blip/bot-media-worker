import json, os, re, shutil, time
from pathlib import Path
from gradio_client import Client, handle_file
os.environ.pop("HF_TOKEN", None)
out = Path("artifacts"); out.mkdir(exist_ok=True); log = {}
PROMPT = ("Pixar style 3D animated movie, a cute little girl with braids in a yellow dress walking on a sunny "
          "beach, warm cinematic lighting, soft shadows, detailed hair and skin, high quality, smooth natural motion")
NEG = "worst quality, inconsistent motion, blurry, jittery, distorted, extra limbs"
c = Client("Lightricks/ltx-video-distilled", verbose=False)
def run(img, d=2, fr=9):
    return c.predict(prompt=PROMPT, negative_prompt=NEG, input_image_filepath=img, input_video_filepath=None,
                     height_ui=384, width_ui=704, mode="image-to-video", duration_ui=d, ui_frames_to_use=fr,
                     seed_ui=42, randomize_seed=False, ui_guidance_scale=1, improve_texture_flag=True,
                     api_name="/image_to_video")
sp = None
try: run(handle_file("v2v/frame.png"))
except Exception as e:
    m = re.search(r"'path': '([^']+)'", str(e)); sp = m.group(1) if m else None
    log["probe"] = {"server_path": sp, "err": str(e)[:120] if not sp else ""}
for key, arg in (("server_path", sp),) if sp else ():
    for d in (2, 4):
        t0 = time.time()
        try:
            r = run(arg, d); v = r[0]; v = v.get("video") if isinstance(v, dict) else v
            log[f"{key}_d{d}"] = {"secs": round(time.time() - t0, 1), "path": str(v)}
            if v and os.path.exists(v):
                shutil.copy(v, out / f"i2v_d{d}.mp4"); log["ok"] = True
        except Exception as e:
            log[f"{key}_d{d}"] = {"secs": round(time.time() - t0, 1), "error": f"{type(e).__name__}: {str(e)[:200]}"}
        time.sleep(4)
(out / "v2v_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(log, ensure_ascii=False, indent=1))
