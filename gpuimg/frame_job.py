# -*- coding: utf-8 -*-
"""מפיק **פריים מאסטר** על A10G חינמי, מתוך רנר ציבורי של גיטהאב.

למה הקובץ הזה קיים
-------------------
12/10/26: הסרטון כבר הופק בענן (`gpuvid/chain.py`), אבל **הפריים**
עוד נוצר מהמחשב הביתי. ארנק ZeroGPU נספר לפי כתובת IP, ולכן
בשלב מסוים בלילה הכתובת הביתית הגיעה ל-0 שניות:

    AppError: You have exceeded your ZeroGPU quota
              (90s requested vs. 0s left)

ומאותו רגע **שום** פריים לא נוצר - כולל פריים שש הדמויות
שהמשתמש ביקש. הסרטון הופק מפריים ישן של שתי דמויות.

אותה נוסחה שפתרה את הווידאו פותרת גם את זה, וזו הסיבה היחידה
לקיומו של הקובץ: רנר של גיטהאב יושב על כתובת Azure נקייה, כלומר
**ארנק ZeroGPU מלא בכל ריצה**, ומאגר ציבורי מקבל דקות Actions
בלתי מוגבלות. מטריצת רנרים = מטריצת ארנקים, והמכסה מפסיקה להיות
גורם.

מה הרנר עושה, ומה הוא **לא** עושה
-----------------------------------
הוא לא מכיר שום דמות ושום סצנה: כל התוכן מגיע ב-`gpuimg/job.json`
שהמפיק דוחף. זה מכוון - פרומפט שמתעדכן לא דורש עריכה של סקריפט
בענן, ושינוי מודל אינו שינוי קוד.

כל רנר (``SHARD``) מקבל **ספק אחר וזרע אחר**. לא שמונה נסיונות
על אותו מודל: מודל טקסט-לתמונה מחמיץ "שש דמויות נפרדות" בדרכים
שונות לגמרי, ולכן גיוון הספקים הוא מה שמעלה את הסיכוי שלפחות
תוצר אחד יחזיר שש פנים. המפיק סופר פנים בבית ובוחר.

שתי מלכודות שנמדדו (ולכן הקוד נראה כך)
----------------------------------------
1. **חתימות ה-Spaces אינן זהות.** ``/infer`` של FLUX.1-schnell
   מקבל ``num_inference_steps``; של Qwen-Image לא. ארגומנט עודף
   אינו "מתעלמים ממנו" - הוא ``TypeError`` ורנר שרוף. לכן אחרי
   כשל בארגומנטים הקבועים יש מסלול שני שקורא ``view_api`` ובונה
   את הקריאה מהשמות שה-Space **מצהיר** עליהם.
2. **429 נראה כמו מכסה.** רצף קריאות מהיר מחזיר 429, וספירה שלו
   כ"ארנק נגמר" מוציאה מהמחזור מרחב חי. לכן יש ``PACE`` בין
   נסיונות, בדיוק כמו ב-`chain.py`.
"""
import json
import os
import shutil
import threading
import time
from pathlib import Path

SHARD = int(os.environ.get("SHARD", "1"))
#: מרווח נשימה בין שני נסיונות. נמדד ב-`chain.py`: 3 שניות לא
#: הספיקו תמיד, 8 כן.
PACE = float(os.environ.get("PACE", "8"))
#: תקרה לקריאה בודדת. מרחב שנתקע בתור חוסם את הרנר עד
#: ``timeout-minutes``, ואז הארטיפקט לא נעלה בכלל.
CALL_TIMEOUT = float(os.environ.get("CALL_TIMEOUT", "240"))

HERE = Path(__file__).resolve().parent
OUT = Path("artifacts")
OUT.mkdir(exist_ok=True)

JOB = json.loads((HERE / "job.json").read_text(encoding="utf-8"))

PROMPT = str(JOB.get("prompt") or "")
NEGATIVE = str(JOB.get("negative") or "")
W = int(JOB.get("width") or 1024)
H = int(JOB.get("height") or 640)
#: זרע לכל רנר. ``base + shard`` ולא ``randomize`` - כך הרצה
#: חוזרת עם אותו job.json מחזירה אותו פריים, וזה מה שמאפשר
#: להשוות שתי הרצות.
SEED = int(JOB.get("seed") or 1000) + SHARD * 7919
SPECS = list(JOB.get("specs") or [])
#: כמה ספקים ינסה הרנר הזה לפני שהוא מוותר. הוא מתחיל מהספק
#: ששייך לו (``SHARD-1``) וממשיך במעגל - כך אין שני רנרים
#: שמתחילים מאותו מודל, ובכל זאת אין ספק שלא ייבדק בכלל.
TRIES = int(JOB.get("tries_per_runner") or 3)

if not SPECS:
    (OUT / ("img_%d.json" % SHARD)).write_text(
        json.dumps({"shard": SHARD, "ok": False,
                    "err": "job.json בלי specs"}, ensure_ascii=False),
        encoding="utf-8")
    raise SystemExit(0)

from gradio_client import Client                         # noqa: E402

#: שמות פרמטרים נפוצים, למסלול השני (``view_api``).
_P_PROMPT = ("prompt", "text", "positive_prompt", "query", "caption",
             "description")
_P_NEG = ("negative_prompt", "negative", "neg_prompt")
_P_W = ("width", "w", "image_width")
_P_H = ("height", "h", "image_height")
_P_SEED = ("seed", "random_seed")


def _fill(v):
    """מחליף מחזיקי מקום בערכים של העבודה הזו."""
    if isinstance(v, str):
        return {"@PROMPT": PROMPT, "@NEGATIVE": NEGATIVE,
                "@W": W, "@H": H, "@SEED": SEED}.get(v, v)
    return v


def deadline(fn, secs: float):
    """מריץ ``fn`` עם תקרת זמן. חוט ולא signal - הרנר הוא לינוקס
    אבל gradio_client חוסם בתוך httpx, ו-SIGALRM שם לא תמיד קוטע."""
    box = {}

    def run():
        try:
            box["v"] = fn()
        except BaseException as exc:                     # noqa: BLE001
            box["e"] = exc
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(secs)
    if th.is_alive():
        raise TimeoutError("%.0f שניות" % secs)
    if "e" in box:
        raise box["e"]
    return box.get("v")


def _pick(res):
    """נתיב התמונה מתוך תשובת predict.

    Spaces מחזירים או מחרוזת, או dict עם ``path``/``image``, או
    tuple שבו התמונה אינה בהכרח ראשונה (יש מי שמחזיר (seed, img)).
    """
    seen = res if isinstance(res, (list, tuple)) else [res]
    for item in seen:
        p = item
        if isinstance(p, dict):
            p = p.get("path") or p.get("image") or p.get("name") or p.get("url")
        if isinstance(p, (str, Path)):
            q = Path(str(p))
            if q.exists() and q.suffix.lower() in (".png", ".jpg", ".jpeg",
                                                   ".webp"):
                return q
    return None


def _auto(c: Client):
    """קריאה ל-Space לפי הפרמטרים שהוא **מצהיר** עליהם.

    זה המסלול שמציל ספק שחתימתו השתנתה: רשימת ארגומנטים קבועה
    נשברת בשקט ברגע ש-Space מעדכן את ה-API שלו, ואז הרנר נשרף
    על TypeError ולא על GPU.
    """
    api = c.view_api(return_format="dict") or {}
    for name, info in (api.get("named_endpoints") or {}).items():
        params = info.get("parameters") or []
        names = [str(p.get("parameter_name") or p.get("label")
                      or "").lower() for p in params]
        if not any(n in _P_PROMPT for n in names):
            continue
        kw = {}
        for p, n in zip(params, names):
            key = p.get("parameter_name")
            if not key:
                continue
            if n in _P_PROMPT:
                kw[key] = PROMPT
            elif n in _P_NEG:
                kw[key] = NEGATIVE
            elif n in _P_W:
                kw[key] = W
            elif n in _P_H:
                kw[key] = H
            elif n in _P_SEED:
                kw[key] = SEED
            elif p.get("parameter_has_default"):
                continue
            else:
                kw[key] = p.get("parameter_default")
        return c.predict(api_name=name, **kw)
    raise RuntimeError("אין נקודת קצה עם פרומפט")


def attempt(spec: dict) -> tuple[Path | None, str]:
    """נסיון אחד מול ספק אחד. מחזיר (נתיב, שגיאה)."""
    space = str(spec.get("space") or "")
    api = str(spec.get("api") or "/infer")
    args = {k: _fill(v) for k, v in (spec.get("args") or {}).items()}
    c = deadline(lambda: Client(space, verbose=False), 90)
    try:
        res = deadline(lambda: c.predict(api_name=api, **args), CALL_TIMEOUT)
    except TypeError as exc:
        # חתימה שונה ממה שהמפיק חשב. זה לא כשל GPU - שווה מסלול שני.
        print("  %s: חתימה לא תואמת (%s) - עובר ל-view_api"
              % (space, str(exc)[:90]), flush=True)
        res = deadline(lambda: _auto(c), CALL_TIMEOUT)
    p = _pick(res)
    if p is None:
        return None, "התשובה לא הכילה תמונה: %r" % (res,)
    return p, ""


log = []
made = None
order = [SPECS[(SHARD - 1 + k) % len(SPECS)] for k in range(len(SPECS))]
for i, spec in enumerate(order[:max(1, TRIES)]):
    if i:
        time.sleep(PACE)
    space = str(spec.get("space") or "?")
    t0 = time.time()
    try:
        p, err = attempt(spec)
        dt = round(time.time() - t0, 1)
        if p is None:
            log.append({"space": space, "ok": False, "secs": dt, "err": err})
            print("✗ %s · %.1f שנ' · %s" % (space, dt, err[:160]), flush=True)
            continue
        dest = OUT / ("img_%d.png" % SHARD)
        shutil.copy(p, dest)
        made = dest
        log.append({"space": space, "ok": True, "secs": dt,
                    "bytes": dest.stat().st_size})
        print("✓ %s · %.1f שנ' · %d בייט"
              % (space, dt, dest.stat().st_size), flush=True)
        break
    except BaseException as exc:                         # noqa: BLE001
        dt = round(time.time() - t0, 1)
        log.append({"space": space, "ok": False, "secs": dt,
                    "err": "%s: %s" % (type(exc).__name__, str(exc)[:220])})
        print("✗ %s · %.1f שנ' · %s: %s"
              % (space, dt, type(exc).__name__, str(exc)[:160]), flush=True)

(OUT / ("img_%d.json" % SHARD)).write_text(
    json.dumps({"shard": SHARD, "seed": SEED, "ok": made is not None,
                "file": (made.name if made else ""), "w": W, "h": H,
                "log": log}, ensure_ascii=False, indent=1),
    encoding="utf-8")

# **יציאה 0 גם בכשל.** ``continue-on-error`` ב-workflow מכסה את
# הצעד, אבל רנר שנפל לפני ``upload-artifact`` לא משאיר את היומן -
# וכשל בלי יומן הוא בדיוק מה שאי אפשר לאבחן מהבית.
print("רנר %d: %s" % (SHARD, "הפיק פריים" if made else "לא הפיק"),
      flush=True)
