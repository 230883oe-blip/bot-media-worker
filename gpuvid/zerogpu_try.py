# -*- coding: utf-8 -*-
"""מבחן ארנק ZeroGPU מתוך רנר ציבורי + ניסיון הנפשה אמיתי.

השאלה שנמדדת: האם כתובת ה-IP של רנר GitHub (Azure) מחזיקה ארנק
ZeroGPU אנונימי, והאם היא בכלל לא חסומה. שלושה יועצים אמרו שהיא
כנראה שחוקה - מדידה אחת זולה יותר משלוש דעות.
"""
import json, os, re, shutil, sys, threading, time, urllib.request
from pathlib import Path

OUT = Path("artifacts"); OUT.mkdir(exist_ok=True)
IMG = Path("gpuvid/frame.png")
RX = re.compile(r"\(([\d.]+)s requested vs\.\s*(-?[\d.]+)s left")
rep = {"runner_ip": None, "tests": []}

try:
    rep["runner_ip"] = urllib.request.urlopen(
        "https://api.ipify.org", timeout=20).read().decode().strip()
except Exception as e:
    rep["runner_ip"] = f"err:{e}"
print("IP של הרנר:", rep["runner_ip"], flush=True)

from gradio_client import Client, handle_file

def dl(fn, s):
    b = {}
    def r():
        try: b["v"] = fn()
        except BaseException as e: b["e"] = e
    t = threading.Thread(target=r, daemon=True); t.start(); t.join(s)
    if t.is_alive(): raise TimeoutError(f"{s}s")
    if "e" in b: raise b["e"]
    return b.get("v")

PROMPT = ("cinematic 3d animated film, the characters come alive: subtle head "
          "turn, eyes blink, warm sunset light, gentle camera push in, smooth "
          "natural motion, high quality")
NEG = "static, still, blurry, distorted, extra limbs, text, watermark"

def ltx(c):
    return c.predict(prompt=PROMPT, negative_prompt=NEG,
                     input_image_filepath=handle_file(str(IMG)),
                     input_video_filepath=None, height_ui=480, width_ui=832,
                     mode="image-to-video", duration_ui=3.0,
                     ui_frames_to_use=9, seed_ui=42, randomize_seed=True,
                     ui_guidance_scale=1.0, improve_texture_flag=False,
                     api_name="/image_to_video")

def anime(c):
    return c.predict(image=handle_file(str(IMG)), prompt=PROMPT,
                     negative_prompt=NEG, api_name="/generate_video")

def shimti(c):
    return c.predict(prompt=PROMPT, negative_prompt=NEG,
                     input_image_filepath=handle_file(str(IMG)),
                     input_video_filepath=None, height_ui=480, width_ui=832,
                     mode="image-to-video", duration_ui=2.0, ui_frames_to_use=9,
                     seed_ui=42, randomize_seed=True, ui_guidance_scale=1.0,
                     improve_texture_flag=False, api_name="/image_to_video")

def svd(c):
    return c.predict(image=handle_file(str(IMG)), seed=42, randomize_seed=True,
                     motion_bucket_id=127, fps_id=10, noise_aug_strength=0.1,
                     decoding_t=3, video_format="mp4", frame_format="png",
                     version="auto", api_name="/video")

CANDS = [("Lightricks/ltx-video-distilled", ltx, 120),
         ("aidealab/AnimeGen-I2V", anime, 180),
         ("Shimti/shimti-ltx-video", shimti, 60),
         ("seawolf2357/img2vid", svd, 180)]

def pick(o):
    if isinstance(o, str): return o
    if isinstance(o, dict):
        for k in ("video", "path", "url"):
            if o.get(k): return pick(o[k])
    if isinstance(o, (list, tuple)):
        for x in o:
            p = pick(x)
            if p and str(p).lower().endswith((".mp4", ".webm")): return p
        for x in o:
            p = pick(x)
            if p: return p
    return None

won = None
for sid, call, dur in CANDS:
    t = time.time()
    row = dict(space=sid, declared=dur)
    try:
        c = dl(lambda: Client(sid, verbose=False), 90)
        out = dl(lambda: call(c), 280)
        p = pick(out)
        row.update(ok=True, sec=round(time.time() - t, 1), path=str(p)[:200])
        if p and os.path.exists(p):
            dst = OUT / (sid.replace("/", "_") + Path(p).suffix)
            shutil.copy(p, dst)
            row["bytes"] = dst.stat().st_size
            row["file"] = dst.name
            print(f"✅ {sid}: {dst.name} {dst.stat().st_size} בייט "
                  f"ב-{row['sec']}ש", flush=True)
            won = won or dst.name
        else:
            print(f"⚠️ {sid}: עבר אבל אין קובץ: {str(out)[:200]}", flush=True)
    except BaseException as e:
        s = str(e).replace("\n", " ")
        m = RX.search(s)
        row.update(ok=False, sec=round(time.time() - t, 1),
                   err=f"{type(e).__name__}: {s[:220]}")
        if m:
            row["wallet_left"] = float(m.group(2))
            row["wallet_need"] = float(m.group(1))
            print(f"✗ {sid}: ביקש {m.group(1)}ש, בארנק {m.group(2)}ש", flush=True)
        else:
            print(f"✗ {sid}: {type(e).__name__}: {s[:200]}", flush=True)
    rep["tests"].append(row)
    if won:
        break

rep["won"] = won
(OUT / "zerogpu_report.json").write_text(
    json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
print("\n== סיכום ==")
print(json.dumps(rep, ensure_ascii=False, indent=1), flush=True)
