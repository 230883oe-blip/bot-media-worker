import json, os, shutil, time
from pathlib import Path
import cv2, av
from gradio_client import Client, handle_file
os.environ.pop("HF_TOKEN", None)
out = Path("artifacts"); out.mkdir(exist_ok=True); log = {}
det = cv2.FaceDetectorYN.create("talk/yunet.onnx", "", (320, 320), 0.6)
def facew(bgr):
    h, w = bgr.shape[:2]; det.setInputSize((w, h)); _, fs = det.detect(bgr)
    return 0 if fs is None or len(fs) != 1 else fs[0][2] / w
P = ("Pixar style 3D animated movie close-up portrait of a cute little girl with two long black braids tied with yellow ribbons, "
     "brown eyes, rosy cheeks, yellow dress, looking straight at the camera, face fills the center of the frame, "
     "sunny tropical beach blurred in the background, warm cinematic lighting, detailed skin, high quality")
fx = Client("black-forest-labs/FLUX.1-schnell", verbose=False)
img = None
for k in range(6):
    try:
        r = fx.predict(prompt=P, seed=k, randomize_seed=False, width=1024, height=576, num_inference_steps=4, api_name="/infer")
        p = r[0]; p = p.get("path") if isinstance(p, dict) else p
        w = facew(cv2.imread(p)); log.setdefault("flux", []).append({"seed": k, "facew": round(float(w), 2)})
        if 0.18 <= w <= 0.5: img = p; shutil.copy(p, out / "face.png"); break
        if w and img is None: shutil.copy(p, out / "face_fallback.png")
    except Exception as e:
        log.setdefault("flux", []).append({"seed": k, "err": str(e)[:120]}); time.sleep(20)
if img is None and (out / "face_fallback.png").exists(): img = str(out / "face_fallback.png")
if img is None: (out / "log.json").write_text(json.dumps(log)); raise SystemExit(1)
lt = Client("Lightricks/ltx-video-distilled", verbose=False)
for k in range(1, 5):
    try:
        r = lt.predict(prompt=P + ", she is talking to the camera, speaking naturally, head steady, camera static",
                       negative_prompt="worst quality, blurry, jittery, distorted, deformed face, different person, hand on face, closed mouth smile only",
                       input_image_filepath=handle_file(img), input_video_filepath=None, height_ui=384, width_ui=704,
                       mode="image-to-video", duration_ui=3, ui_frames_to_use=9, seed_ui=300 + k, randomize_seed=False,
                       ui_guidance_scale=1, improve_texture_flag=True, api_name="/image_to_video")
        v = r[0]; v = v.get("video") if isinstance(v, dict) else v
        fr = [f.to_ndarray(format="bgr24") for f in av.open(v).decode(video=0)]
        ws = [facew(fr[i]) for i in (0, len(fr) // 2, len(fr) - 1)]
        log.setdefault("ltx", []).append({"seed": 300 + k, "facew": [round(float(x), 2) for x in ws]})
        shutil.copy(v, out / "talk_base.mp4")
        if all(x > 0.15 for x in ws): break
    except Exception as e:
        log.setdefault("ltx", []).append({"err": str(e)[:120]}); time.sleep(30)
(out / "log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8"); print(log)
