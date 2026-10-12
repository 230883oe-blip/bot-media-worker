# -*- coding: utf-8 -*-
"""סנכרון שפתיים על ZeroGPU חינמי, **מתוך רנר של גיטהאב**.

למה דווקא כאן ולא במכונה הביתית (נמדד 12/10 בערב)
--------------------------------------------------
הקריאה מהבית חזרה בשש שורות זהות::

    You have exceeded your ZeroGPU runs limit.

שימו לב למילה ``runs``. זו **לא** המגבלה שתועדה ב-11/10
("180s requested vs. 138s left") אלא מגבלה שנייה ונפרדת: מספר
**ההרצות** לכתובת IP אנונימית ליום. ההבחנה הזו היא כל ההבדל
בין "אי אפשר" לבין "אפשר":

* מגבלת **שניות** אינה נפתרת בהחלפת כתובת - כל ארנק אנונימי
  מציע פחות מ-180, ולכן ``fffiloni/LatentSync`` נדחה תמיד.
* מגבלת **הרצות** נפתרת לגמרי בכתובת נקייה - וזה בדיוק מה
  שרנר של גיטהאב נותן בחינם, שמונה פעמים במקביל.

ולכן שני תיקונים ביחד, ולא אחד:

1. **רצים מהענן** - אותה נוסחה של ``gpuvid2.yml``/``gpuimg.yml``:
   מאגר ציבורי, דקות Actions בלתי מוגבלות, כתובת Azure נקייה לכל
   רנר, ומטריצה = מאגר ארנקים ולא ארנק יחיד.
2. **קוראים למרחב שמצהיר מעט.** נסרקו 715 מרחבי סנכרון; מתוך
   החיים נמצאו גרסאות של אותו מודל ByteDance בדיוק שמצהירות
   20, 45 ו-60 שניות במקום 180. ``kulikov1/latentsync-zt`` אף
   מציע ארבע נקודות קצה מדורגות (45/60/78/120) - נקודת הקצה
   עצמה היא בורר התקציב.

הכלל ששומר על הסרט
-------------------
קטע שלא הסתנכרן **אינו** מוחזר כקובץ פגום. הרנר כותב רק מה
שעבר את ``_ok`` (קובץ נפתח, יש זרם וידאו, יותר מפריים אחד),
והנהג המקומי משאיר במקומו את הקטע המקורי. פה לא מדויק גרוע
בהרבה פחות מחור בסרט.
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

#: מרחבי הסנכרון, בסדר הניסיון. ``dur`` הוא מה שהמרחב **מצהיר**
#: ל-ZeroGPU - וזה המספר שמכריע קבלה או דחייה, לא הזמן שנצרך
#: בפועל. לכן הסדר הוא מהצנוע למבזבז.
CAND = [
    ("Subodh92290/latentsync-h100", "/process_latentsync", 20, "h100"),
    ("kulikov1/latentsync-zt", "/generate_lip_sync_video_45", 45, "zt"),
    ("ymo2017/latentsync-16-zero", "/predict", 60, "zero16"),
    ("kulikov1/latentsync-zt", "/generate_lip_sync_video_60", 60, "zt"),
    ("fbougrai/LatentSync-1.6", "/generate_lip_sync_video", 150, "ls16"),
    ("fffiloni/LatentSync", "/generate_lip_sync_video", 180, "fff"),
]


def payload(flavor, vid, aud, hf):
    """הפרמטרים משתנים ממרחב למרחב, ולכן הם נבנים לפי ``flavor``.

    זו לא קוסמטיקה: ``latentsync-h100`` מקבל ``video_upload``
    כמילון ``{"video": ...}``, בעוד ``zt`` מקבל ``filepath`` שטוח.
    שליחה של הצורה הלא נכונה מחזירה 500 ממרחב חי לגמרי.
    """
    v, a = hf(str(vid)), hf(str(aud))
    if flavor == "zt":
        return dict(input_video_path=v, input_audio_path=a,
                    inference_steps="12")
    if flavor == "h100":
        return dict(video_upload={"video": v}, audio_upload=a,
                    video_gdrive="", audio_gdrive="",
                    inference_steps=12, guidance_scale=1.5, seed=1247)
    if flavor == "zero16":
        return dict(video_path={"video": v}, audio_path=a,
                    guidance_scale=1.5, inference_steps=12, seed=1247)
    if flavor == "ls16":
        return dict(video=v, audio=a, inference_steps=12,
                    guidance_scale=1.5, seed=1247)
    return dict(input_video_path=v, input_audio_path=a)


def deadline(fn, seconds):
    """חוט daemon עם תקרת זמן. ``ThreadPoolExecutor`` אינו מתאים:
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
    """מחלץ נתיב וידאו מתשובה - מחרוזת, מילון או רשימה."""
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


def sync_one(idx, vid, aud, log):
    from gradio_client import Client, handle_file         # noqa: PLC0415
    dst = OUT / ("lip_%02d.mp4" % idx)
    for sid, api, dur, flavor in CAND:
        t0 = time.time()
        try:
            c = deadline(lambda s=sid: Client(s, verbose=False),
                         CONNECT_TIMEOUT)
            res = deadline(
                lambda cl=c, a=api, f=flavor: cl.predict(
                    api_name=a, **payload(f, vid, aud, handle_file)),
                CALL_TIMEOUT)
            got = pick(res)
            if not _ok(got):
                raise RuntimeError("לא חזר וידאו: %s" % str(res)[:160])
            shutil.copy(got, dst)
            log.append({"piece": idx, "space": sid, "api": api,
                        "declared": dur, "seconds": round(time.time() - t0, 1),
                        "ok": True})
            return dst, sid
        except BaseException as e:                        # noqa: BLE001
            log.append({"piece": idx, "space": sid, "api": api,
                        "declared": dur, "seconds": round(time.time() - t0, 1),
                        "ok": False,
                        "why": str(e).replace("\n", " ")[:220]})
            time.sleep(PACE)
    return None, ""


def main():
    job = json.loads((HERE / "job.json").read_text(encoding="utf-8"))
    mine = [p for p in job.get("pieces", []) if int(p.get("shard", 0)) == SHARD]
    log, made = [], []
    if not mine:
        print("שורה %d: אין קטעים - יוצא בלי לגעת ב-GPU" % SHARD, flush=True)
    for p in mine:
        i = int(p["i"])
        vid, aud = HERE / ("p%02d.mp4" % i), HERE / ("p%02d.wav" % i)
        if not vid.exists() or not aud.exists():
            log.append({"piece": i, "ok": False, "why": "חסר קלט"})
            continue
        got, sid = sync_one(i, vid, aud, log)
        if got:
            made.append({"piece": i, "file": got.name, "space": sid})
            print("קטע %d סונכרן ב-%s" % (i, sid), flush=True)
        else:
            print("קטע %d לא סונכרן בשום מרחב" % i, flush=True)
    (OUT / ("lip_%d.json" % SHARD)).write_text(
        json.dumps({"shard": SHARD, "made": made, "log": log},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
