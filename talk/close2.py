import json, os, shutil, time
from pathlib import Path
import cv2, av
from gradio_client import Client, handle_file
os.environ.pop("HF_TOKEN", None)
out = Path("artifacts"); out.mkdir(exist_ok=True); log = {}
det = cv2.FaceDetectorYN.create("talk/yunet.onnx", "", (320, 320), 0.6)
def facew(b):
    h, w = b.shape[:2]; det.setInputSize((w, h)); _, fs = det.detect(b)
    return 0 if fs is None or len(fs) != 1 else fs[0][2] / w
P = ("Pixar style 3D animated movie close-up portrait of a cute little girl with two long black braids tied with yellow ribbons, "
     "brown eyes, rosy cheeks, yellow dress, looking straight at the camera, face fills the center of the frame, "
     "sunny tropical beach blurred in the background, warm cinematic lighting, detailed skin, high quality")
ACTS = {1: "she is talking happily to the camera, speaking naturally, head steady, camera static",
        2: "she is talking excitedly to the camera, eyebrows raised, speaking naturally, head steady, camera static",
        3: "she is talking warmly and smiling to the camera, speaking naturally, head steady, camera static"}
lt = Client("Lightricks/ltx-video-distilled", verbose=False)
for i, act in ACTS.items():
    for k in range(1, 5):
        try:
            r = lt.predict(prompt=P + ", " + act, negative_prompt="worst quality, blurry, jittery, distorted, deformed face, different person, hand on face",
                           input_image_filepath=handle_file("talk/face.png"), input_video_filepath=None, height_ui=384, width_ui=704,
                           mode="image-to-video", duration_ui=3, ui_frames_to_use=9, seed_ui=400 + 10 * i + k, randomize_seed=False,
                           ui_guidance_scale=1, improve_texture_flag=True, api_name="/image_to_video")
            v = r[0]; v = v.get("video") if isinstance(v, dict) else v
            fr = [f.to_ndarray(format="bgr24") for f in av.open(v).decode(video=0)]
            ws = [facew(fr[j]) for j in (0, len(fr) // 2, len(fr) - 1)]
            log.setdefault(i, []).append({"seed": 400 + 10 * i + k, "facew": [round(float(x), 2) for x in ws]})
            shutil.copy(v, out / f"base_{i}.mp4")
            if all(x > 0.15 for x in ws): break
        except Exception as e:
            log.setdefault(i, []).append({"err": str(e)[:120]}); time.sleep(30)
(out / "log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8"); print(log)
