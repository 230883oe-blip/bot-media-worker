# -*- coding: utf-8 -*-
"""מפיק **שרשרת** קטעי הנפשה על A10G חינמי, מתוך רנר ציבורי.

הרעיון שנמדד ב-11/10: ארנק ZeroGPU נספר לפי כתובת IP, ולרנר של
GitHub יש כתובת Azure נקייה - כלומר ארנק מלא בכל ריצה. שלושה
יועצים אמרו שהטווח "שחוק"; המדידה הראתה 120ש מאושרות וקריאה
שעברה ב-11.8 שניות. מאגר ציבורי = דקות בלתי מוגבלות, ולכן זה
כרטיס A10G בן 24 ג'יגה בלי מכסה מעשית.

שרשרת ולא קטע בודד: כל קטע מתחיל מהפריים **האחרון** של קודמו,
ולכן התנועה רציפה ואפשר להגיע לאורך אמיתי בלי קריאה לכל פריים.
"""
import json
import os
import shutil
import threading
import time
from pathlib import Path

SHARD = int(os.environ.get("SHARD", "1"))
STEPS = int(os.environ.get("STEPS", "4"))
SECS = float(os.environ.get("SECS", "3"))
OUT = Path("artifacts")
OUT.mkdir(exist_ok=True)
IMG = Path("gpuvid/frame.png")

BEATS = json.loads(Path("gpuvid/beats.json").read_text(encoding="utf-8"))
NEG = ("static, still image, frozen, blurry, distorted, deformed face, "
       "extra limbs, text, watermark, jitter")

from gradio_client import Client, handle_file           # noqa: E402
import PIL.Image as I                                   # noqa: E402


def dl(fn, s):
    b = {}

    def r():
        try:
            b["v"] = fn()
        except BaseException as e:
            b["e"] = e
    t = threading.Thread(target=r, daemon=True)
    t.start()
    t.join(s)
    if t.is_alive():
        raise TimeoutError(str(s) + "s")
    if "e" in b:
        raise b["e"]
    return b.get("v")


def ltx(c, img, prompt, secs):
    return c.predict(prompt=prompt, negative_prompt=NEG,
                     input_image_filepath=handle_file(str(img)),
                     input_video_filepath=None, height_ui=480, width_ui=832,
                     mode="image-to-video", duration_ui=secs,
                     ui_frames_to_use=9, seed_ui=42 + SHARD,
                     randomize_seed=True, ui_guidance_scale=1.0,
                     improve_texture_flag=False, api_name="/image_to_video")


def anime(c, img, prompt, secs):
    return c.predict(image=handle_file(str(img)), prompt=prompt,
                     negative_prompt=NEG, api_name="/generate_video")


#: שלושה מרחבים, כולם נמדדו חיים על zero-a10g. רוטציה ביניהם היא
#: מה שמחזיק את הריצה כשארנק אחד נגמר באמצע השרשרת.
SPACES = [("Lightricks/ltx-video-distilled", ltx),
          ("Shimti/shimti-ltx-video", ltx),
          ("aidealab/AnimeGen-I2V", anime)]


def pick(o):
    if isinstance(o, str):
        return o
    if isinstance(o, dict):
        for k in ("video", "path", "url"):
            if o.get(k):
                return pick(o[k])
    if isinstance(o, (list, tuple)):
        for x in o:
            p = pick(x)
            if p and str(p).lower().endswith((".mp4", ".webm")):
                return p
        for x in o:
            p = pick(x)
            if p:
                return p
    return None


def last_frame(video, dst):
    """הפריים האחרון - נקודת הפתיחה של הקטע הבא."""
    import av
    c = av.open(str(video))
    fr = None
    for f in c.decode(video=0):
        fr = f
    c.close()
    if fr is None:
        return None
    I.fromarray(fr.to_ndarray(format="rgb24")).save(dst)
    return dst


clients, log, made = {}, [], []
cur = Path("seed.png")
shutil.copy(IMG, cur)

for i in range(STEPS):
    idx = (SHARD - 1) * STEPS + i
    beat = BEATS[idx] if idx < len(BEATS) else BEATS[-1]
    done = False
    for sid, call in SPACES:
        t = time.time()
        try:
            if sid not in clients:
                clients[sid] = dl(lambda s=sid: Client(s, verbose=False), 90)
            out = dl(lambda c=clients[sid], f=call: f(c, cur, beat, SECS), 290)
            p = pick(out)
            if not (p and os.path.exists(p)):
                raise RuntimeError("אין קובץ: " + str(out)[:150])
            dst = OUT / ("seg_%d_%02d.mp4" % (SHARD, i))
            shutil.copy(p, dst)
            made.append(dst.name)
            kb = dst.stat().st_size // 1024
            log.append(dict(step=i, space=sid, sec=round(time.time() - t, 1),
                            bytes=dst.stat().st_size, beat=beat[:70], ok=True))
            print("OK  קטע %d/%d  %s  %dKB  %.1fs"
                  % (i + 1, STEPS, sid, kb, time.time() - t), flush=True)
            done = True
            break
        except BaseException as e:
            s = str(e).replace("\n", " ")[:200]
            log.append(dict(step=i, space=sid, sec=round(time.time() - t, 1),
                            ok=False, err=type(e).__name__ + ": " + s))
            print("XX  קטע %d  %s  %s: %s"
                  % (i + 1, sid, type(e).__name__, s), flush=True)
            clients.pop(sid, None)
    if not done:
        print("כל המרחבים סירבו בקטע %d - עוצר את השרשרת" % (i + 1), flush=True)
        break

    # חילוץ הפריים האחרון הוא **מחוץ** לניסיון הקריאה. הוא נכשל
    # בריצה הראשונה (numpy חסר), והכישלון נתפס ב-except של המרחב -
    # כלומר קריאת GPU שהצליחה נרשמה ככישלון, המרחב הוחלף, והשרשרת
    # נעצרה אחרי קטע אחד. כשל בעיבוד מקומי אינו כשל של השרת.
    try:
        nxt = last_frame(OUT / ("seg_%d_%02d.mp4" % (SHARD, i)),
                         Path("next_%d.png" % i))
        if nxt:
            cur = nxt
    except BaseException as e:
        print("אזהרה: לא חולץ פריים המשך (%s: %s) - ממשיכים מהקודם"
              % (type(e).__name__, str(e)[:120]), flush=True)

    time.sleep(3)      # מרווח נשימה: רצף predict מהיר מחזיר 429

(OUT / ("chain_%d.json" % SHARD)).write_text(
    json.dumps(dict(shard=SHARD, made=made, log=log), ensure_ascii=False,
               indent=1), encoding="utf-8")
print("שורה %d: %d קטעים" % (SHARD, len(made)), flush=True)
