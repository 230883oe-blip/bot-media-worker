# -*- coding: utf-8 -*-
"""שולח את תשובת קלוד מהרנר ישר לטלגרם.

רץ בתוך GitHub Actions, בלי שום תלות במחשב של המשתמש. נכתב כקובץ נפרד
ולא בתוך ה-yml כי טקסט עברי ארוך בתוך heredoc של yml נשבר על הזחה.

מלכודות:
  * טלגרם חותך הודעה ב-4096 תווים ומחזיר שגיאה על יותר - לכן חיתוך
    לפרקים כאן ולא הסתמכות על השרת.
  * parse_mode לא מוגדר בכוונה: תשובה של מודל מכילה כוכביות וקו תחתון
    חופשיים, ו-Markdown היה מפיל את השליחה כולה על תחביר לא סגור.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

LIMIT = 3900


def read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except Exception:
        return ""


def send(token: str, chat: str, text: str) -> bool:
    data = urllib.parse.urlencode({
        "chat_id": chat,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode()).get("ok", False)
    except Exception as exc:                      # noqa: BLE001
        print(f"שליחה נכשלה: {exc!r}", flush=True)
        return False


def main() -> int:
    token = os.environ.get("TG_TOKEN", "").strip()
    chat = os.environ.get("CHAT", "").strip()
    rc = os.environ.get("RC", "?").strip()
    if not token or not chat:
        print("אין טוקן או צ'אט - לא שולח (זה תקין בריצת בדיקה)", flush=True)
        return 0

    answer = read(sys.argv[1] if len(sys.argv) > 1 else "/tmp/answer.txt")
    err = read(sys.argv[2] if len(sys.argv) > 2 else "/tmp/err.txt")

    if answer:
        head = "☁️ קלוד ענן:\n\n"
    elif rc == "124":
        head = "☁️ קלוד ענן: נגמר הזמן שהוקצב לריצה.\n\n"
        answer = err[-1500:] or "(אין פלט)"
    else:
        head = f"☁️ קלוד ענן: הריצה נכשלה (קוד {rc}).\n\n"
        answer = err[-1500:] or "(אין פלט)"

    body = head + answer
    parts = [body[i:i + LIMIT] for i in range(0, len(body), LIMIT)] or [head]
    ok = True
    for idx, part in enumerate(parts[:6]):
        suffix = "" if len(parts) == 1 else f"\n\n({idx + 1}/{min(len(parts), 6)})"
        ok = send(token, chat, part + suffix) and ok
    print("נשלח" if ok else "שליחה חלקית/נכשלה", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
