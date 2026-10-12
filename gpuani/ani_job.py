# -*- coding: utf-8 -*-
"""סנכרון שפתיים **מקורי** (audio-driven) מתוך רנר של גיטהאב.

למה כאן ולא במכונה הביתית - נמדד 12/10 בערב
--------------------------------------------
הקריאה הראשונה והשנייה מהבית עברו ב-27 וב-24 שניות, והשלישית
חזרה::

    You have exceeded your ZeroGPU quota (90s requested vs. 0s left)

כלומר הארנק האנונימי מחזיק בפועל כשתי קריאות, והוא נספר **לפי
כתובת IP**. רנר של גיטהאב מקבל כתובת Azure נקייה, ומטריצה של
שישה רנרים היא שישה ארנקים נפרדים - אותה נוסחה בדיוק של
``gpulip.yml``, שכבר הוכחה כאן.

במה זה שונה מ-``lip_job.py``
-----------------------------
``lip_job`` שולח **וידאו + שמע** ומקבל וידאו שהפה בו הוחלף. זה
מה שמרח את הפנים: המודל מקודד מחדש את הקאדר ומדביק אזור פה
מיוצר. כאן נשלחים **תמונה + שמע**, והמודל בונה את תנועת הפנים
מאפס לפי גלי הקול - אין מסכה שמודבקת, ולכן אין מה שימרח.

המגבלה שנמדדה, וההתאמה אליה
----------------------------
``AniPortrait`` דוחה מעל 90 פריימים (``Value 120 is greater than
maximum value 90``). ב-30fps זה שלוש שניות. התכנון של הסרט כבר
מחלק כל שוט לקטעים של 2.5 שניות - 75 פריימים - ולכן ההתאמה
מושלמת ואין צורך לפרק מחדש.
"""
import json
import os
import shutil
import threading
import time
from pathlib import Path

SHARD = int(os.environ.get("SHARD", "1"))
PACE = float(os.environ.get("PACE", "6"))
CALL_TIMEOUT = float(os.environ.get("CALL_TIMEOUT", "600"))
CONNECT_TIMEOUT = float(os.environ.get("CONNECT_TIMEOUT", "90"))

HERE = Path(__file__).resolve().parent
OUT = Path("artifacts")
OUT.mkdir(exist_ok=True)

#: המרחבים, בסדר הניסיון. ``flavor`` קובע את שמות הפרמטרים -
#: הם שונים לגמרי בין המרחבים, ושליחת הצורה הלא נכונה מחזירה
#: שגיאה ממרחב חי לגמרי.
CAND = [
    ("ZJYang/AniPortrait_official", "/audio2video", "ani", 90),
    ("fffiloni/echomimic-v2", "/generate", "echo2", 240),
    ("fffiloni/EchoMimic", "/generate_video", "echo", 1200),
]


def payload(flavor, img, aud, n, hf):
    """פרמטרים לפי מרחב. ``n`` הוא תמיד **מספר פריימים**."""
    i, a = hf(str(img)), hf(str(aud))
    if flavor == "ani":
        return dict(input_audio=a, ref_img=i, headpose_video=None,
                    size=384, steps=15, length=int(min(n, 90)), seed=42)
    if flavor == "echo2":
        return dict(image_input=i, audio_input=a,
                    pose_input="assets/halfbody_demo/pose/",
                    preset_name="Showcase", width=512, height=512,
                    length=int(max(n, 100)), steps=15, sample_rate=16000,
                    cfg=2.5, fps=24, context_frames=12, context_overlap=3,
                    quantization_input=False, seed=42)
    return dict(uploaded_img=i, uploaded_audio=a, width=512, height=512,
                length=int(max(n, 100)), seed=42,
                facemask_dilation_ratio=0.1, facecrop_dilation_ratio=0.5,
                context_frames=12, context_overlap=3, cfg=2.5, steps=15,
                sample_rate=16000, fps=24, device="cuda")


def deadline(fn, seconds):
    """חוט daemon עם תקרת זמן. ``ThreadPoolExecutor`` אינו מתאים -
    הוא ממתין לחוט ביציאה, ולכן תקרה עליו אינה מצילה דבר."""
    box = {}

    def run():
        try:
            box["v"] = fn()
        except BaseException as e:                        # noqa: BLE001
            box["e"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TimeoutError("%.0f שניות" % seconds)
    if "e" in box:
        raise box["e"]
    return box.get("v")


def pick(res):
    """מחלץ נתיב וידאו מתשובה - מחרוזת, מילון, רשימה או טאפל.

    ``AniPortrait`` מחזיר ``({'video': ..., 'subtitles': None}, '...')``,
    כלומר מילון **בתוך** טאפל - צורה שלא קיימת בשאר המרחבים.
    """
    got = res
    if isinstance(got, (list, tuple)):
        got = got[0] if got else None
    if isinstance(got, dict):
        got = got.get("video") or got.get("path") or got.get("value")
    if isinstance(got, dict):
        got = got.get("path")
    return got if isinstance(got, str) else None


def _ok(path, min_bytes=20000):
    """200 אינו וידאו. הכלל הזה חוזר בכל ערוץ חינמי בפרויקט."""
    try:
        p = Path(str(path))
        if not p.exists() or p.stat().st_size < min_bytes:
            return False
        import av
        with av.open(str(p)) as c:
            return bool(c.streams.video) and \
                (c.streams.video[0].frames or 0) > 1
    except Exception:                                     # noqa: BLE001
        return False


def candidates(only=""):
    """המרחבים לניסיון. ``only`` מקבע **וריאנט** למרחב אחד.

    בלי הקיבוע הזה אין "שני וריאנטים": ``one`` נופל למרחב הבא
    ברשימה, ולכן שתי ריצות שנקראות בשמות שונים יכולות לרוץ על
    אותו מרחב בדיוק ולהיות מושוות זו לזו כאילו הן שונות.
    """
    only = str(only or "").strip().lower()
    if not only:
        return list(CAND)
    picked = [c for c in CAND if c[2] == only or only in c[0].lower()]
    return picked or list(CAND)


def one(idx, img, aud, n, log, cands=None):
    from gradio_client import Client, handle_file         # noqa: PLC0415
    dst = OUT / ("ani_%02d.mp4" % idx)
    for sid, api, flavor, cap in (cands or CAND):
        t0 = time.time()
        try:
            c = deadline(lambda s=sid: Client(s, verbose=False),
                         CONNECT_TIMEOUT)
            res = deadline(
                lambda cl=c, a=api, f=flavor: cl.predict(
                    api_name=a, **payload(f, img, aud, n, handle_file)),
                CALL_TIMEOUT)
            got = pick(res)
            if not _ok(got):
                raise RuntimeError("לא חזר וידאו: %s" % str(res)[:160])
            shutil.copy(got, dst)
            log.append({"piece": idx, "space": sid, "api": api,
                        "cap": cap, "seconds": round(time.time() - t0, 1),
                        "ok": True})
            return dst, sid
        except BaseException as e:                        # noqa: BLE001
            log.append({"piece": idx, "space": sid, "api": api, "cap": cap,
                        "seconds": round(time.time() - t0, 1), "ok": False,
                        "why": str(e).replace("\n", " ")[:220]})
            time.sleep(PACE)
    return None, ""


def main():
    job = json.loads((HERE / "job.json").read_text(encoding="utf-8"))
    mine = [p for p in job.get("pieces", []) if int(p.get("shard", 0)) == SHARD]
    cands = candidates(job.get("engine", ""))
    log, made = [], []
    print("שורה %d · מרחבים: %s" % (SHARD, [c[0] for c in cands]), flush=True)
    if not mine:
        print("שורה %d: אין קטעים - יוצא בלי לגעת ב-GPU" % SHARD, flush=True)
    for p in mine:
        i = int(p["i"])
        img, aud = HERE / ("s%02d.png" % i), HERE / ("a%02d.wav" % i)
        if not img.exists() or not aud.exists():
            log.append({"piece": i, "ok": False, "why": "חסר קלט"})
            continue
        got, sid = one(i, img, aud, int(p.get("frames") or 75), log, cands)
        if got:
            made.append({"piece": i, "file": got.name, "space": sid})
            print("קטע %d הונפש ב-%s" % (i, sid), flush=True)
        else:
            print("קטע %d לא הונפש בשום מרחב" % i, flush=True)
    (OUT / ("ani_%d.json" % SHARD)).write_text(
        json.dumps({"shard": SHARD, "made": made, "log": log},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
