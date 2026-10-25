# -*- coding: utf-8 -*-
"""בדיקת שטח: הורדת יוטיוב מ-IP של רנר דרך השער בענן (25/10/2026).

סבב א' (05:48) מדד שמונה-עשר מסלולים ישירים מהרנר — yt-dlp בכל
הלקוחות, PO token, שמונה Invidious, חמישה Piped, חמישה cobalt — וכולם
נכשלו. החסימה היא על טווח ה-IP של מכונות CI, ולכן שום חתימת לקוח
אינה פותרת אותה.

סבב ב' (כאן) בודק את המסלול היחיד שנותר הגיוני: **הענן מבקש, הרנר
מוריד**. Apps Script יושב על IP של גוגל (נמדד 24/10: 200 מגוגל, 403
מהבית), הוא מחזיר קישור ישיר, והשאלה הנמדדת כאן היא אם *הרנר* מצליח
להוריד ממנו — כלומר אם הקישור אינו נעול ל-IP המבקש.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

VID = "jNQXAC9IVRw"           # "Me at the zoo" — 19 שניות
URL = f"https://www.youtube.com/watch?v={VID}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def say(ok: bool, name: str, note: str) -> None:
    print(f"[{'OK ' if ok else 'FAIL'}] {name}: {note}", flush=True)


def gate(url: str) -> dict:
    gas, admin = os.environ.get("GAS_URL", ""), os.environ.get("GAS_ADMIN", "")
    if not (gas and admin):
        say(False, "שער", "חסרים סודות GAS_URL/GAS_ADMIN")
        return {}
    body = json.dumps({"admin": admin, "action": "ytgate", "u": url,
                       "q": "720"}).encode()
    req = urllib.request.Request(gas, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:                            # noqa: BLE001
        say(False, "שער", f"{type(exc).__name__}: {str(exc)[:120]}")
        return {}


def download(link: str, out: str) -> int:
    req = urllib.request.Request(link, headers={"User-Agent": UA})
    total = 0
    with urllib.request.urlopen(req, timeout=300) as r, open(out, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
    return total


def main() -> int:
    print(f"סבב ב' — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        with urllib.request.urlopen("https://api.ipify.org?format=json", timeout=15) as r:
            print("IP:", r.read().decode()[:60])
    except Exception:                                   # noqa: BLE001
        pass

    targets = [URL, "https://www.youtube.com/watch?v=aqz-KE-bpKQ"]
    import os as _os
    if _os.environ.get("YT_URL"):
        targets = [_os.environ["YT_URL"]]
    ok_all = True
    for t in targets:
        print(chr(10) + ">>> " + t, flush=True)
        ok_all = one(t) and ok_all
    print(chr(10) + "===== מסקנה =====")
    print("הורדת יוטיוב בענן עובדת מקצה לקצה" if ok_all
          else "לא כל הסרטונים ירדו — ראה למעלה")
    return 0 if ok_all else 1


def one(URL: str) -> bool:
    g = gate(URL)
    print("תשובת השער:", json.dumps({k: (str(v)[:70]) for k, v in g.items()},
                                     ensure_ascii=False))
    if not g.get("ok") or not g.get("url"):
        say(False, "שער בענן", "לא החזיר קישור: " + str(g.get("tried"))[:200])
        return False
    say(True, "שער בענן",
        f"{g.get('kind')} {g.get('client') or ''} {g.get('name')}")

    try:
        n = download(g["url"], "/tmp/yt.mp4")
    except urllib.error.HTTPError as exc:
        say(False, "הורדה מהרנר", f"HTTP {exc.code}")
        return False
    except Exception as exc:                            # noqa: BLE001
        say(False, "הורדה מהרנר", f"{type(exc).__name__}: {str(exc)[:120]}")
        return False
    ok = n > 50000
    say(ok, "הורדה מהרנר", f"{n / 1048576:.2f}MB")

    if g.get("audio_url"):
        try:
            m = download(g["audio_url"], "/tmp/yt.m4a")
            say(m > 10000, "שמע נפרד", f"{m / 1048576:.2f}MB")
        except Exception as exc:                        # noqa: BLE001
            say(False, "שמע נפרד", type(exc).__name__)

    return ok


if __name__ == "__main__":
    raise SystemExit(main())
