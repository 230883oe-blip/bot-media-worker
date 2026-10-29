# -*- coding: utf-8 -*-
"""
שואל את Ollama שרץ על ראנר GitHub, וכותב את התשובה ל-answer.json.

הקובץ הזה רץ **בענן**, לא כאן. הוא נשלח לריפו על ידי `ollama_cloud.py`
ומופעל מתוך `ollama.yml`. אין לו שום תלות חוץ מפייתון הסטנדרטי - על
ראנר נקי אין httpx ואין requests, והתקנה שלהם היא 20 שניות מבוזבזות.

הקלט מגיע כולו ממשתני סביבה (ולא משורת הפקודה) כדי ששאלה בעברית עם
גרשיים לא תישבר ב-shell, וכדי שלא תהיה שום דרך להזריק פקודה.

הפלט הוא **תמיד** answer.json, גם בכישלון: `if: always()` מעלה אותו
כ-artifact, והצד הקורא מעדיף שגיאה מוסברת על "אין קובץ".
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
from pathlib import Path

HOST = "http://127.0.0.1:11434"
OUT = Path("answer.json")

SYSTEM_HE = (
    "אתה עוזר שעונה בעברית תקנית וטבעית, בקצרה ולעניין. "
    "אם השאלה באנגלית - ענה באנגלית. "
    "אל תמציא עובדות; אם אינך יודע, אמור שאינך יודע."
)


def post(path: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        HOST + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8", "replace"))


def installed() -> list[str]:
    try:
        req = urllib.request.Request(HOST + "/api/tags")
        with urllib.request.urlopen(req, timeout=20) as res:
            data = json.loads(res.read().decode("utf-8", "replace"))
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


def pick(want: str, fallback: str, have: list[str]) -> str:
    """
    המודל שבאמת קיים על הראנר - ולא זה שביקשנו.

    *** למה זו בדיקה ולא השמה. *** שלב ה-pull ב-yml נופל בכוונה למודל
    חלופי אם הגדול לא נמשך. אם היינו שולחים כאן את השם המקורי, Ollama
    היה מחזיר 404 והריצה כולה הייתה מתבזבזת אחרי שכבר הורדנו מודל
    עובד.
    """
    for cand in (want, fallback):
        if not cand:
            continue
        for name in have:
            if name == cand or name.split(":")[0] == cand.split(":")[0]:
                return name
    return have[0] if have else want


def main() -> int:
    q = (os.environ.get("OLL_Q") or "").strip()
    want = (os.environ.get("OLL_MODEL") or "gemma3:12b").strip()
    fallback = (os.environ.get("OLL_FALLBACK") or "gemma3:4b").strip()
    img = (os.environ.get("OLL_IMG") or "").strip()
    sys_prompt = (os.environ.get("OLL_SYS") or "").strip() or SYSTEM_HE

    result = {"ok": False, "answer": "", "model": "", "seconds": 0.0,
              "error": "", "runner": "github-actions"}

    have = installed()
    use = pick(want, fallback, have)
    result["model"] = use
    result["available"] = have

    if not q:
        result["error"] = "לא הגיעה שאלה"
        OUT.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return 1

    message: dict = {"role": "user", "content": q}
    msgs = [{"role": "system", "content": sys_prompt}, message]

    if img:
        pic = Path(img)
        if not pic.exists():
            result["error"] = f"התמונה {img} לא נמצאה בריפו"
            OUT.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            return 1
        message["images"] = [base64.b64encode(pic.read_bytes()).decode("ascii")]
        # אותה מלכודת שנמדדה במכונה המקומית: מודל ראייה קטן מחזיר תשובה
        # ריקה לגמרי כשיש תפקיד system בבקשה. לכן ההנחיה נדחסת לתוכן.
        message["content"] = sys_prompt + "\n\n" + q
        msgs = [message]

    payload = {"model": use, "stream": False, "messages": msgs,
               # הראנר הוא 16GB, ולכן אין כאן את הצמצום ל-2048 שנדרש
               # במכונה הביתית. הקשר רחב = תשובה טובה יותר.
               "options": {"temperature": 0.6, "num_ctx": 8192}}

    began = time.perf_counter()
    try:
        data = post("/api/chat", payload, 1500.0)
        answer = ((data or {}).get("message") or {}).get("content", "").strip()
        if not answer:                       # מסלול גיבוי, ממשק ישן
            flat = {k: v for k, v in payload.items() if k != "messages"}
            flat["prompt"] = "\n\n".join(m.get("content", "") for m in msgs)
            images = [i for m in msgs for i in (m.get("images") or [])]
            if images:
                flat["images"] = images
            answer = (post("/api/generate", flat, 1500.0) or {}).get(
                "response", "").strip()
        result["answer"] = answer
        result["ok"] = bool(answer)
        if not answer:
            result["error"] = "המודל החזיר תשובה ריקה בשני המסלולים"
    except Exception as exc:                 # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["seconds"] = round(time.perf_counter() - began, 1)

    OUT.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "answer"},
                     ensure_ascii=False))
    print("---- התשובה ----")
    print(result["answer"][:2000])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
