# -*- coding: utf-8 -*-
"""
עובד המדיה של הענן — הורדה, חיתוך, צריבת כתוביות וקבצים עד 2GB.

זה הקובץ *היחיד* שעושה עבודה על קובץ בפועל, והוא רץ בשלוש סביבות
בלי שינוי: GitHub Actions (אוטונומי לחלוטין), Google Colab, והמחשב.

למה בכלל: Apps Script הוא המוח בענן אבל הוא לא יכול להריץ בינארי, ולכן
ffmpeg חייב לרוץ במקום אחר. GitHub Actions נותן אובונטו שלם עם ffmpeg
מותקן, שש שעות ריצה, חינם ובלי כרטיס אשראי, ומופעל בבקשת HTTP אחת —
ולכן אין בו שום חלון שהמשתמש צריך לפתוח.

הפרוטוקול זהה לזה של עובד Colab שקדם לו (work=next / work=fail), כדי
שהמוח בענן לא יצטרך לדעת מי העובד.

מלכודות שנכתבו כאן במפורש, כל אחת עלתה בכישלון אמיתי:
  * Bot API לא מוריד מעל 20MB ולא מעלה מעל 50MB. MTProto (Telethon) עם
    *אותו טוקן בוט* עוקף את שניהם עד 2GB, ודורש רק api_id/api_hash —
    בלי חשבון מששתמש ובלי התחברות בטלפון.
  * Telethon צריך להכיר את ההודעה. בצ'אט פרטי get_messages(None, ids=..)
    עובד בלי ישות, וזה המסלול היחיד שעובד בעובד שלא קיבל עדכונים.
  * חיתוך: -ss לפני -i הוא מהיר אבל לא מדויק לפריים. עם -c copy צריך
    לחתוך על keyframe, ולכן כאן: -ss לפני -i (מהיר) + -c copy, ואם
    היציאה יצאה ריקה — נסיון שני עם קידוד מחדש.
  * צריבה: הכתוביות מגיעות כ-SRT מהמוח בענן (Gemini מתמלל עם חותמות
    זמן), ולא מ-whisper — על מעבד של רנר זה היה לוקח יותר מהריצה.
  * subtitles= ב-ffmpeg מפרש : ו-\\ ו-' בתוך הנתיב. לכן קובץ הכתוביות
    נשמר תמיד בשם קבוע בתיקיית העבודה ומורצים משם.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = os.environ.get("CLOUD_URL", "").strip()
SECRET = os.environ.get("CLOUD_SECRET", "").strip()
WORK = Path(os.environ.get("WORKER_DIR") or "/tmp/mediaworker")
# 45 דקות לריצה, ויציאה אחרי 6 דקות בלי עבודה: ב-GitHub Actions יש 2000
# דקות חינם בחודש לריפו פרטי, ולכן רנר שיושב בטל הוא בזבוז אמיתי.
RUN_SECONDS = int(os.environ.get("RUN_SECONDS", "2700"))
IDLE_SLEEP = int(os.environ.get("IDLE_SLEEP", "15"))
IDLE_EXIT = int(os.environ.get("IDLE_EXIT", "360"))
NONCE = os.environ.get("CLOUD_NONCE", "").strip()

TG_UPLOAD_LIMIT = 48 * 1024 * 1024        # Bot API מעלה עד 50MB; שוליים
_cfg: dict = {}


# --------------------------------------------------------------- כלים

def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def ffmpeg_exe() -> str:
    """ffmpeg של המערכת, ואם אין — זה של imageio (לבדיקה במחשב)."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def run(cmd: list[str], timeout: int = 1800, cwd=None) -> subprocess.CompletedProcess:
    log("$ " + " ".join(str(c) for c in cmd)[:300])
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          cwd=str(cwd) if cwd else None)


def api(params: dict, timeout: int = 120) -> dict:
    """קריאה לשער הניהול של המוח בענן."""
    q = dict(params, secret=SECRET)
    url = BASE + ("&" if "?" in BASE else "?") + urllib.parse.urlencode(q)
    with urllib.request.urlopen(url, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw}


def cfg() -> dict:
    """api_id/api_hash נשלפים מהענן פעם אחת, כדי שלא ישבו ב-GitHub."""
    global _cfg
    if not _cfg:
        try:
            _cfg = api({"work": "cfg"}) or {}
        except Exception as exc:
            log(f"cfg נכשל: {exc!r}")
            _cfg = {}
    return _cfg


# ------------------------------------------------- טלגרם: שליחה והורדה

def tg_send(token: str, chat, path: Path, caption: str = "") -> bool:
    """שולח קובץ. עד 48MB דרך Bot API, ומעל זה דרך MTProto."""
    size = path.stat().st_size
    if size <= TG_UPLOAD_LIMIT:
        if _tg_send_botapi(token, chat, path, caption):
            return True
    return _tg_send_mtproto(token, chat, path, caption)


def _tg_send_botapi(token: str, chat, path: Path, caption: str) -> bool:
    video = path.suffix.lower() in (".mp4", ".mkv", ".mov", ".webm")
    audio = path.suffix.lower() in (".mp3", ".m4a", ".ogg", ".opus", ".wav")
    method, field = ("sendVideo", "video") if video else \
                    ("sendAudio", "audio") if audio else ("sendDocument", "document")
    body, boundary = _multipart({"chat_id": str(chat), "caption": caption[:1000],
                                 "supports_streaming": "true"}, field, path)
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except Exception as exc:
        log(f"שליחה ב-Bot API נכשלה: {exc!r}")
        return False


def _multipart(fields: dict, file_field: str, path: Path) -> tuple[bytes, str]:
    boundary = "----mw" + str(int(time.time() * 1000))
    out = bytearray()
    for k, v in fields.items():
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                f"{v}\r\n").encode()
    out += (f"--{boundary}\r\nContent-Disposition: form-data; "
            f"name=\"{file_field}\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode()
    out += path.read_bytes() + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), boundary


def _tg_send_mtproto(token: str, chat, path: Path, caption: str) -> bool:
    c = cfg()
    if not (c.get("api_id") and c.get("api_hash")):
        log("אין api_id/api_hash — אי אפשר לשלוח קובץ גדול")
        return False
    try:
        import asyncio
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        async def go():
            cl = TelegramClient(StringSession(), int(c["api_id"]), c["api_hash"],
                                receive_updates=False)
            await cl.start(bot_token=token)
            try:
                await cl.send_file(int(chat), str(path), caption=caption[:1000],
                                   supports_streaming=path.suffix.lower() == ".mp4")
            finally:
                await cl.disconnect()
            return True

        return bool(asyncio.run(go()))
    except Exception as exc:
        log(f"שליחה ב-MTProto נכשלה: {exc!r}")
        return False


def tg_fetch_big(token: str, chat, msg_id: int, dest: Path) -> Path | None:
    """מוריד קובץ מהודעת טלגרם עד 2GB. זה מה ש-Bot API חוסם ב-20MB."""
    c = cfg()
    if not (c.get("api_id") and c.get("api_hash")):
        return None
    try:
        import asyncio
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        async def go():
            cl = TelegramClient(StringSession(), int(c["api_id"]), c["api_hash"],
                                receive_updates=False)
            await cl.start(bot_token=token)
            try:
                try:
                    msg = await cl.get_messages(int(chat), ids=int(msg_id))
                except ValueError:
                    msg = await cl.get_messages(None, ids=int(msg_id))
                if msg is None or not msg.media:
                    return None
                dest.mkdir(parents=True, exist_ok=True)
                return await cl.download_media(msg, file=str(dest))
            finally:
                await cl.disconnect()

        got = asyncio.run(go())
        return Path(got) if got else None
    except Exception as exc:
        log(f"הורדת קובץ גדול נכשלה: {exc!r}")
        return None


# ------------------------------------------------------------- הורדה

def ytdlp(url: str, dest: Path, audio: bool = False) -> Path | None:
    """מוריד עם yt-dlp. מחזיר את הקובץ הכי גדול שנוצר."""
    dest.mkdir(parents=True, exist_ok=True)
    fmt = "bestaudio/best" if audio else \
          "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best"
    # --ffmpeg-location הוא חובה: בלעדיו yt-dlp לא ממזג וידאו+שמע ומשאיר
    # שני קבצי ביניים, ואז "הקובץ הגדול" שנבחר הוא השמע בלבד. נתפס 01/10
    # בבדיקה חיה — המשתמש קיבל קול בלי תמונה.
    cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings",
           "--ffmpeg-location", ffmpeg_exe(),
           "--print", "after_move:filepath", "--no-simulate",
           "-f", fmt, "-o", str(dest / "%(title).60s.%(ext)s")]
    if audio:
        cmd += ["-x", "--audio-format", "mp3"]
    else:
        cmd += ["--merge-output-format", "mp4"]
    res = run(cmd + [url], timeout=2400)
    if res.returncode != 0:
        log("yt-dlp: " + (res.stderr or "")[-400:])
    # הנתיב המדויק שיצא, מפי yt-dlp עצמו — ולא ניחוש לפי גודל.
    for line in reversed((res.stdout or "").splitlines()):
        cand = Path(line.strip())
        if line.strip() and cand.exists() and cand.stat().st_size > 1000:
            return cand
    # גיבוי: הגדול ביותר, בלי קבצי ביניים של פורמט בודד (.f137.mp4)
    files = [f for f in dest.iterdir()
             if f.is_file() and f.stat().st_size > 1000
             and not re.search(r"\.f\d+\.[a-z0-9]+$", f.name, re.I)]
    if not files:
        files = [f for f in dest.iterdir() if f.is_file() and f.stat().st_size > 1000]
    return max(files, key=lambda f: f.stat().st_size) if files else None


def direct(url: str, dest: Path) -> Path | None:
    """הורדה ישרה של קישור לקובץ (למשל מה שהשער הציבורי החזיר)."""
    dest.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[\\/:*?\"<>|]+", "_",
                  urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name)) or "media"
    if not re.search(r"\.[a-z0-9]{2,4}$", name, re.I):
        name += ".mp4"
    out = dest / name
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r, out.open("wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
    except Exception as exc:
        log(f"הורדה ישרה נכשלה: {exc!r}")
        return None
    return out if out.exists() and out.stat().st_size > 1000 else None


# --------------------------------------------------------- ffmpeg עצמו

def to_seconds(t: str) -> float:
    parts = [float(x) for x in str(t).split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def cut(src: Path, start: str, end: str, out: Path) -> Path | None:
    """חיתוך. קודם בהעתקה (מהיר), ואם נכשל — בקידוד מחדש (מדויק)."""
    dur = max(0.5, to_seconds(end) - to_seconds(start))
    ff = ffmpeg_exe()
    fast = [ff, "-y", "-ss", str(to_seconds(start)), "-i", str(src),
            "-t", str(dur), "-c", "copy", "-movflags", "+faststart", str(out)]
    res = run(fast, timeout=1200)
    if res.returncode == 0 and out.exists() and out.stat().st_size > 20000:
        return out
    log("חיתוך בהעתקה נכשל — מקודד מחדש")
    exact = [ff, "-y", "-ss", str(to_seconds(start)), "-i", str(src),
             "-t", str(dur), "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "23", "-c:a", "aac", "-movflags", "+faststart", str(out)]
    res = run(exact, timeout=2400)
    if res.returncode != 0:
        log("ffmpeg: " + (res.stderr or "")[-400:])
    return out if out.exists() and out.stat().st_size > 20000 else None


def burn(src: Path, srt_text: str, out: Path, work: Path) -> Path | None:
    """צריבת כתוביות. שם קובץ קבוע — ffmpeg מפרש תווים בנתיב."""
    sub = work / "subs.srt"
    sub.write_text(srt_text, encoding="utf-8")
    font = os.environ.get("SUB_FONT") or ("Arial" if os.name == "nt" else "DejaVu Sans")
    style = (f"FontName={font},FontSize=22,PrimaryColour=&H00FFFFFF,"
             "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,"
             "Alignment=2,MarginV=40")
    # cwd=work הוא חובה: מסנן subtitles פותח את הנתיב בעצמו ומפרש : ו-\,
    # ולכן מריצים משם עם שם קצר. בלי זה — "Unable to open subs.srt".
    res = run([ffmpeg_exe(), "-y", "-i", str(src),
               "-vf", f"subtitles=subs.srt:force_style='{style}'",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
               "-c:a", "copy", "-movflags", "+faststart", str(out)],
              timeout=3600, cwd=work)
    if res.returncode != 0:
        log("ffmpeg(burn): " + (res.stderr or "")[-500:])
        # -c:a copy נופל כשהמקור לא AAC
        res = run([ffmpeg_exe(), "-y", "-i", str(src),
                   "-vf", f"subtitles=subs.srt:force_style='{style}'",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                   "-c:a", "aac", str(out)], timeout=3600, cwd=work)
    return out if out.exists() and out.stat().st_size > 20000 else None


def small_audio(src: Path, out: Path) -> Path | None:
    """
    מכווץ לשמע מונו 32kbps. סרטון של 300 מגה נהפך לכמה מגה, ורק כך
    אפשר להחזיר אותו למוח בענן לתמלול — שם התקרה היא 50 מגה לבקשה.
    """
    res = run([ffmpeg_exe(), "-y", "-i", str(src), "-vn", "-ac", "1",
               "-ar", "16000", "-b:a", "32k", str(out)], timeout=2400)
    if res.returncode != 0:
        log("ffmpeg(audio): " + (res.stderr or "")[-300:])
    return out if out.exists() and out.stat().st_size > 2000 else None


def post_transcribe(job: dict, mp3: Path) -> bool:
    """מחזיר את השמע המכווץ למוח בענן, שמתמלל ושולח לצ'אט."""
    import base64
    body = json.dumps({
        "pull": SECRET, "action": "transcribe",
        "bot": job.get("bot", ""), "chat": job.get("chat"),
        "ask": (job.get("extra") or {}).get("ask") or job.get("text") or "",
        "mime": "audio/mpeg", "name": "audio.mp3",
        "b64": base64.b64encode(mp3.read_bytes()).decode(),
    }).encode()
    req = urllib.request.Request(BASE, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return json.loads(r.read().decode("utf-8", "replace")).get("ok", False)
    except Exception as exc:
        log(f"החזרת שמע לתמלול נכשלה: {exc!r}")
        return False


# ------------------------------------------------------- ביצוע עבודה

WANT_AUDIO = re.compile(r"(שמע|אודיו|mp3|רק את הקול|בלי וידאו)")
CUT_RE = re.compile(r"(?:מ-?\s*)?(\d{1,2}:\d{2}(?::\d{2})?)\s*"
                    r"(?:עד|-|–|to|until)\s*(\d{1,2}:\d{2}(?::\d{2})?)")


def source_file(job: dict, jdir: Path) -> Path | None:
    """משיג את קובץ המקור: מהודעת טלגרם, או מהרשת."""
    extra = job.get("extra") or {}
    if extra.get("msg_id"):
        got = tg_fetch_big(job.get("token", ""), extra.get("chat") or job.get("chat"),
                           int(extra["msg_id"]), jdir)
        if got:
            return got
    url = (job.get("url") or "").strip()
    if not url:
        m = re.search(r"https?://\S+", job.get("text") or "")
        url = m.group(0) if m else ""
    if not url:
        return None
    audio = bool(WANT_AUDIO.search(job.get("text") or ""))
    got = ytdlp(url, jdir, audio)
    return got or direct(url, jdir)


def tg_text(token: str, chat, text: str) -> bool:
    """שולח טקסט. חותך לגודל שטלגרם מרשה."""
    data = urllib.parse.urlencode(
        {"chat_id": str(chat), "text": text[:4000],
         "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=data, timeout=60) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except Exception as exc:
        log(f"שליחת טקסט נכשלה: {exc!r}")
        return False


# מה שמותר להתקין בריצת קוד. pip בענן של GitHub פתוח, אבל התקנה של
# חבילה כבדה שורפת דקות מהמכסה החודשית, ולכן יש תקרה על המספר.
CODE_PIP_MAX = 6
# 20 דקות לריצה אחת. הרנר עצמו חי 55 דקות, וצריך להשאיר מקום לעבודות
# נוספות בתור — ריצה שנתקעת לא תבלע את כל המכונה.
CODE_TIMEOUT = 1200


def run_code(job: dict, jdir: Path) -> bool:
    """
    מריץ קוד פייתון בענן ומחזיר את הפלט ואת הקבצים שנוצרו לטלגרם.
    זה מה שמאפשר "תכנות ובנייה" בלי שהמחשב הביתי דלוק.

    הקוד עצמו נכתב במוח שבענן (Apps Script) ומגיע כאן מוכן בשדה code,
    כדי שהעובד יישאר טיפש — הוא רק אובונטו עם פייתון.
    """
    token, chat = job.get("token") or "", job.get("chat")
    # הקוד מגיע או בשדה code ברמה העליונה, או בתוך extra — תור העבודות
    # בענן מעביר שדות חופשיים דרך extra, ושני המסלולים נתמכים.
    extra = job.get("extra") or {}
    code = job.get("code") or extra.get("code") or ""
    if not code.strip():
        return False
    pkgs = [p for p in (job.get("pip") or extra.get("pip") or [])
            if re.fullmatch(r"[A-Za-z0-9_.\-\[\]]{1,40}", str(p))][:CODE_PIP_MAX]
    if pkgs:
        log(f"מתקין: {' '.join(pkgs)}")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                        "--disable-pip-version-check", *pkgs],
                       cwd=jdir, timeout=900, check=False)
    script = jdir / "task.py"
    script.write_text(code, encoding="utf-8")
    before = {p.name for p in jdir.iterdir()}
    log("מריץ את הקוד")
    try:
        # PYTHONIOENCODING מפורש: בלעדיו פלט בעברית יוצא ג'יבריש בכל
        # סביבה שבה קידוד המסוף אינו UTF-8 (נמדד בווינדוס 01/10/26).
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        r = subprocess.run([sys.executable, "-u", "task.py"], cwd=jdir,
                           capture_output=True, text=True, errors="replace",
                           encoding="utf-8", env=env, timeout=CODE_TIMEOUT)
        out, err, rc = r.stdout or "", r.stderr or "", r.returncode
    except subprocess.TimeoutExpired:
        out, err, rc = "", f"הריצה נעצרה אחרי {CODE_TIMEOUT // 60} דקות.", -1
    head = "✅ הקוד רץ בענן, בלי המחשב." if rc == 0 else \
           f"⚠️ הקוד רץ בענן וסיים בשגיאה (קוד {rc})."
    body = (out.strip() or "(אין פלט)")
    if err.strip():
        body += "\n\n— שגיאות —\n" + err.strip()[-1200:]
    tg_text(token, chat, head + "\n\n" + body[:3500])
    # קבצים שהקוד ייצר — נשלחים כמסמכים, עד חמישה, עד 45 מגה כל אחד.
    sent = 0
    for p in sorted(jdir.iterdir()):
        if p.name in before or not p.is_file() or p.name == "task.py":
            continue
        if p.stat().st_size == 0 or p.stat().st_size > 45 * 1024 * 1024:
            continue
        tg_send(token, chat, p, f"📎 {p.name} · נוצר בענן")
        sent += 1
        if sent >= 5:
            break
    return True


def handle(job: dict) -> bool:
    op = job.get("op") or "download"
    token = job.get("token") or ""
    chat = job.get("chat")
    jdir = WORK / str(job.get("id") or int(time.time()))
    if jdir.exists():
        shutil.rmtree(jdir, ignore_errors=True)
    jdir.mkdir(parents=True, exist_ok=True)
    log(f"עבודה {job.get('id')} op={op}")

    # ריצת קוד אינה עובדת על קובץ מקור, ולכן היא לפני source_file —
    # אחרת כל עבודת קוד הייתה נופלת על "אין מקור".
    if op == "code":
        ok = run_code(job, jdir)
        shutil.rmtree(jdir, ignore_errors=True)
        return ok

    src = source_file(job, jdir)
    if not src:
        return False
    log(f"מקור: {src.name}  {src.stat().st_size / 1048576:.1f}MB")

    text = job.get("text") or ""
    extra = job.get("extra") or {}
    result, cap = src, ""

    if op == "cut" or extra.get("from"):
        m = CUT_RE.search(text)
        a = extra.get("from") or (m.group(1) if m else "0:00")
        b = extra.get("to") or (m.group(2) if m else "0:30")
        out = cut(src, a, b, jdir / ("cut_" + re.sub(r"\W+", "_", src.stem)[:40] + ".mp4"))
        if not out:
            return False
        result, cap = out, f"✂️ {a}–{b} · נחתך בענן, בלי המחשב."
    elif op == "burn":
        srt = ""
        try:
            srt = (api({"work": "srt", "u": job.get("url") or text}, 600) or {}).get("srt", "")
        except Exception as exc:
            log(f"שליפת כתוביות נכשלה: {exc!r}")
        if not srt.strip():
            return False
        out = burn(src, srt, jdir / ("sub_" + re.sub(r"\W+", "_", src.stem)[:40] + ".mp4"), jdir)
        if not out:
            return False
        result, cap = out, "🔥 כתוביות נצרבו בענן, בלי המחשב."
    elif op == "transcribe":
        # קובץ מעל 20 מגה: ההורדה נעשתה כאן בפרוטוקול הישיר, והתמלול
        # נעשה במוח בענן על שמע מכווץ. כך אף צד לא פוגש את המגבלה.
        mp3 = small_audio(src, jdir / "small.mp3")
        if not mp3:
            return False
        log(f"שמע מכווץ: {mp3.stat().st_size / 1048576:.1f}MB")
        if mp3.stat().st_size > 45 * 1024 * 1024:
            log("גם אחרי כיווץ זה גדול מדי להחזרה")
            return False
        ok = post_transcribe(job, mp3)
        shutil.rmtree(jdir, ignore_errors=True)
        return ok
    else:
        cap = "⬇️ הורד בענן, בלי המחשב."

    ok = tg_send(token, chat, result, cap)
    shutil.rmtree(jdir, ignore_errors=True)
    return ok


# ------------------------------------------------------------- לולאה

def redeem_nonce() -> bool:
    """
    מחליף אסימון חד-פעמי בסוד האמיתי. ההפעלה של GitHub נושאת רק את
    האסימון, כדי שהסוד לא ישב בשום מקום מחוץ לענן של גוגל.
    """
    global SECRET
    if SECRET or not (BASE and NONCE):
        return bool(SECRET)
    url = BASE + ("&" if "?" in BASE else "?") + urllib.parse.urlencode(
        {"work": "auth", "nonce": NONCE})
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:
        log(f"פדיון אסימון נכשל: {exc!r}")
        return False
    if not d.get("secret"):
        log("האסימון נדחה")
        return False
    SECRET = d["secret"]
    if d.get("api_id"):
        _cfg.update({"api_id": d["api_id"], "api_hash": d.get("api_hash", "")})
    return True


def main() -> int:
    redeem_nonce()
    if not (BASE and SECRET):
        print("חסרים CLOUD_URL / CLOUD_SECRET", file=sys.stderr)
        return 2
    WORK.mkdir(parents=True, exist_ok=True)
    log(f"עובד המדיה עלה. ffmpeg={ffmpeg_exe()}")
    deadline = time.time() + RUN_SECONDS
    idle_since = time.time()
    done = 0
    while time.time() < deadline:
        try:
            job = (api({"work": "next"}) or {}).get("job")
        except Exception as exc:
            log(f"משיכה נכשלה: {exc!r}")
            time.sleep(IDLE_SLEEP)
            continue
        if not job:
            # אין עבודה חצי שעה — יוצאים, ו-GitHub לא שורף דקות לחינם.
            if time.time() - idle_since > IDLE_EXIT:
                log(f"אין עבודה {IDLE_EXIT // 60} דקות — יוצא")
                break
            time.sleep(IDLE_SLEEP)
            continue
        idle_since = time.time()
        try:
            ok = handle(job)
        except Exception as exc:
            log(f"העבודה קרסה: {exc!r}")
            ok = False
        if ok:
            done += 1
            log(f"עבודה {job.get('id')} הסתיימה")
        else:
            log(f"עבודה {job.get('id')} נכשלה — מחזיר למחשב")
            try:
                api({"work": "fail", "bot": job.get("bot", ""), "chat": job.get("chat", ""),
                     "text": (job.get("text") or "")[:300], "why": "עובד הענן לא הצליח"})
            except Exception:
                pass
    log(f"סיום. {done} עבודות הושלמו.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
