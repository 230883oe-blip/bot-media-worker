# -*- coding: utf-8 -*-
"""בדיקת שטח: אילו מסלולי הורדה מיוטיוב עובדים מ-IP של רנר (25/10/2026).

למה זה קיים: yt-dlp על GitHub Actions מחזיר "Sign in to confirm you're
not a bot" על כל סרטון, כי יוטיוב חוסמת את טווחי ה-IP של מכונות CI.
השאלה אינה "מה אמור לעבוד" אלא "מה עובד *משם*", ואת זה אפשר למדוד רק
משם. הסקריפט מנסה כל מסלול בנפרד, מוריד מגה אחד לאימות, ומדפיס טבלה.

מריצים אותו דרך ריצת ytprobe.yml בריפו הציבורי — אפס מכסה, אפס סודות.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

VID = "jNQXAC9IVRw"           # "Me at the zoo" — 19 שניות, בלי רישוי מוזיקה
URL = f"https://www.youtube.com/watch?v={VID}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
RESULTS: list[tuple[str, str, str]] = []

INVIDIOUS = [
    "https://inv.nadeko.net", "https://invidious.nerdvpn.de",
    "https://yewtu.be", "https://invidious.f5.si",
    "https://iv.ggtyler.dev", "https://invidious.privacyredirect.com",
    "https://inv.tux.pizza", "https://invidious.jing.rocks",
]
PIPED = [
    "https://pipedapi.kavin.rocks", "https://pipedapi.adminforge.de",
    "https://pipedapi.reallyaweso.me", "https://api.piped.private.coffee",
    "https://pipedapi.darkness.services",
]
COBALT = [
    "https://cobalt-api.kwiatekmiki.com", "https://co.eepy.today",
    "https://cobalt-api.ayo.tf", "https://api.cobalt.tools",
    "https://cobalt-backend.canine.tools",
]


def say(name: str, ok: bool, note: str) -> None:
    RESULTS.append((name, "OK " if ok else "FAIL", note))
    print(f"[{'OK ' if ok else 'FAIL'}] {name}: {note}", flush=True)


def get(url: str, timeout: int = 25, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def pull(url: str, want: int = 1 << 20, timeout: int = 40) -> tuple[int, str]:
    """מוריד עד want בתים. מחזיר (בתים, סוג תוכן)."""
    with get(url, timeout) as r:
        ctype = (r.headers.get("Content-Type") or "").lower()
        data = r.read(want)
    return len(data), ctype


# ------------------------------------------------------------- yt-dlp

def ytdlp_try(label: str, extra: list[str]) -> bool:
    cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings",
           "-f", "best[height<=720]/best", "--skip-download",
           "--print", "%(format_id)s|%(ext)s|%(filesize_approx)s", *extra, URL]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=180)
    except subprocess.TimeoutExpired:
        say(label, False, "timeout")
        return False
    if res.returncode == 0 and res.stdout.strip():
        say(label, True, res.stdout.strip().splitlines()[-1][:120])
        return True
    err = " ".join((res.stderr or "").split())[-180:]
    say(label, False, err or f"rc={res.returncode}")
    return False


def test_ytdlp() -> None:
    ytdlp_try("yt-dlp ברירת מחדל", [])
    for client in ("tv_simply", "android_vr", "tv_embedded", "web_embedded",
                   "mweb", "ios", "web_safari"):
        ytdlp_try(f"yt-dlp client={client}",
                  ["--extractor-args", f"youtube:player_client={client}"])


def test_pot() -> None:
    """PO token מקומי (bgutil). דורש node — קיים על הרנר."""
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                        "bgutil-ytdlp-pot-provider"], timeout=240,
                       capture_output=True)
    except Exception as exc:                            # noqa: BLE001
        say("PO token (bgutil)", False, f"התקנה נכשלה: {exc!r}"[:120])
        return
    ytdlp_try("yt-dlp + PO token (web)",
              ["--extractor-args", "youtube:player_client=web"])


# --------------------------------------------------------- invidious

def test_invidious() -> None:
    for base in INVIDIOUS:
        try:
            with get(f"{base}/api/v1/videos/{VID}?fields=title,formatStreams",
                     20) as r:
                meta = json.loads(r.read().decode("utf-8", "replace"))
        except Exception as exc:                        # noqa: BLE001
            say(f"invidious {base}", False, f"api: {type(exc).__name__}")
            continue
        itag = "18"
        for f in meta.get("formatStreams") or []:
            if str(f.get("itag")) == "22":
                itag = "22"
        link = f"{base}/latest_version?id={VID}&itag={itag}&local=true"
        try:
            n, ctype = pull(link)
        except Exception as exc:                        # noqa: BLE001
            say(f"invidious {base}", False, f"stream: {type(exc).__name__}")
            continue
        ok = n > 100000 and "video" in ctype
        say(f"invidious {base}", ok,
            f"itag={itag} {n / 1024:.0f}KB {ctype} | {link}")
        if ok:
            return


# ------------------------------------------------------------- piped

def test_piped() -> None:
    for base in PIPED:
        try:
            with get(f"{base}/streams/{VID}", 20) as r:
                meta = json.loads(r.read().decode("utf-8", "replace"))
        except Exception as exc:                        # noqa: BLE001
            say(f"piped {base}", False, f"api: {type(exc).__name__}")
            continue
        best = ""
        for f in (meta.get("videoStreams") or []):
            if f.get("videoOnly") is False and f.get("url"):
                best = f["url"]
                if "720" in str(f.get("quality")):
                    break
        if not best:
            say(f"piped {base}", False, "אין זרם משולב")
            continue
        try:
            n, ctype = pull(best)
        except Exception as exc:                        # noqa: BLE001
            say(f"piped {base}", False, f"stream: {type(exc).__name__}")
            continue
        ok = n > 100000
        say(f"piped {base}", ok, f"{n / 1024:.0f}KB {ctype}")
        if ok:
            return


# ------------------------------------------------------------ cobalt

def test_cobalt() -> None:
    for base in COBALT:
        body = json.dumps({"url": URL, "videoQuality": "720",
                           "youtubeVideoCodec": "h264"}).encode()
        req = urllib.request.Request(
            base.rstrip("/") + "/", data=body,
            headers={"Content-Type": "application/json",
                     "Accept": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            say(f"cobalt {base}", False,
                f"HTTP {exc.code} {exc.read()[:120].decode('utf-8', 'replace')}")
            continue
        except Exception as exc:                        # noqa: BLE001
            say(f"cobalt {base}", False, type(exc).__name__)
            continue
        link = d.get("url") or (d.get("picker") or [{}])[0].get("url") or ""
        if not link:
            say(f"cobalt {base}", False, json.dumps(d, ensure_ascii=False)[:140])
            continue
        try:
            n, ctype = pull(link)
        except Exception as exc:                        # noqa: BLE001
            say(f"cobalt {base}", False, f"stream: {type(exc).__name__}")
            continue
        ok = n > 100000
        say(f"cobalt {base}", ok, f"{n / 1024:.0f}KB {ctype}")
        if ok:
            return


def main() -> int:
    print(f"בדיקת שטח יוטיוב — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        with get("https://api.ipify.org?format=json", 15) as r:
            print("IP:", r.read().decode()[:80])
    except Exception:                                   # noqa: BLE001
        pass
    for fn in (test_invidious, test_piped, test_cobalt, test_ytdlp, test_pot):
        print("\n--- " + fn.__name__ + " ---", flush=True)
        try:
            fn()
        except Exception as exc:                        # noqa: BLE001
            print(f"!! {fn.__name__} נפל: {exc!r}")
    print("\n===== סיכום =====")
    for name, state, note in RESULTS:
        print(f"{state} {name} :: {note[:160]}")
    wins = [n for n, s, _ in RESULTS if s == "OK "]
    print("\nמסלולים שעבדו:", len(wins))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
