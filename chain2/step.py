import json, os, shutil, sys, time
from pathlib import Path
import cv2, numpy as np, av
from gradio_client import Client, handle_file
os.environ.pop("HF_TOKEN", None)
idx = int(sys.argv[1]); inp = sys.argv[2]; REF = "chain2/start.png"
STYLE = ("Pixar style 3D animated movie, a cute little girl with two long black braids tied neatly with yellow ribbons, "
         "braids stay braided and tied the whole time, brown eyes and rosy cheeks, wearing a yellow dress and yellow sandals, "
         "on a sunny tropical beach, warm cinematic lighting, soft shadows, detailed skin and hair, high quality, ")
ACT = ["she smiles and starts walking toward the camera, braids swinging",
       "she keeps walking toward the camera with a happy smile, natural arm swing",
       "she keeps walking, glancing at the sea, same yellow sandals",
       "she keeps walking and tilts her head, looking around the beach happily",
       "she slows down, smiling at the camera, hands at her sides",
       "she stops and waves at the camera with a big smile"][idx - 1]
NEG = ("worst quality, inconsistent motion, blurry, jittery, distorted, extra limbs, deformed face, different person, "
       "loose hair, untied braids, orange shoes, hand on face")
det = cv2.FaceDetectorYN.create("chain2/yunet.onnx", "", (320, 320), 0.6)
def face_lab(bgr):
    h, w = bgr.shape[:2]; det.setInputSize((w, h)); _, fs = det.detect(bgr)
    if fs is None or len(fs) == 0: return None
    x, y, fw, fh = [int(v) for v in fs[0][:4]]
    roi = bgr[max(y + fh // 3, 0):y + fh * 3 // 4, max(x + fw // 6, 0):x + fw * 5 // 6]
    if roi.size == 0: return None
    lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(float).mean(0)
    return lab, fw / w
def frames_of(p):
    c = av.open(p); fr = [f.to_ndarray(format="bgr24") for f in c.decode(video=0)]; return fr
ref = face_lab(cv2.imread(REF))
out = Path("artifacts"); out.mkdir(exist_ok=True); log = {"clip": idx, "tries": []}
c = Client("Lightricks/ltx-video-distilled", verbose=False)
best = None
for attempt in range(1, 5):
    t0 = time.time()
    try:
        r = c.predict(prompt=STYLE + ACT, negative_prompt=NEG, input_image_filepath=handle_file(inp),
                      input_video_filepath=None, height_ui=384, width_ui=704, mode="image-to-video",
                      duration_ui=3, ui_frames_to_use=9, seed_ui=100 * idx + attempt, randomize_seed=False,
                      ui_guidance_scale=1, improve_texture_flag=True, api_name="/image_to_video")
        v = r[0]; v = v.get("video") if isinstance(v, dict) else v
        if not (v and os.path.exists(v)): raise RuntimeError("no video")
        fr = frames_of(v); des = []
        for k in (len(fr) // 3, 2 * len(fr) // 3, len(fr) - 1):
            m = face_lab(fr[k]); des.append(None if m is None else float(np.linalg.norm(m[0] - ref[0])))
        found = [d for d in des if d is not None]
        score = (max(found) if found else 99) + 20 * (3 - len(found))
        ok = len(found) == 3 and max(found) < 18
        log["tries"].append({"n": attempt, "secs": round(time.time() - t0, 1), "dE": des, "score": round(score, 1), "pass": ok})
        if best is None or score < best[0]:
            shutil.copy(v, out / f"clip_{idx}.mp4"); best = (score, fr[-1])
        if ok: break
    except Exception as e:
        log["tries"].append({"n": attempt, "secs": round(time.time() - t0, 1), "err": f"{type(e).__name__}: {str(e)[:140]}"})
        time.sleep(30)
if best:
    cv2.imwrite(str(out / f"last_{idx}.png"), best[1]); log["best_score"] = round(best[0], 1)
(out / f"log_{idx}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(log, ensure_ascii=False, indent=1))
if not best: sys.exit(1)
