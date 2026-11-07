# -*- coding: utf-8 -*-
"""
חידוש עצמי של הזדהות קלוד **בתוך מכונת הענן** (08/11/2026).

== הפער שזה סוגר, במדידה ולא בהשערה ==

עד היום המחשב דחף לסוד `CLAUDE_CODE_OAUTH_TOKEN` את *אסימון הגישה*
המקומי. אסימון גישה תקף שמונה שעות. כלומר מרגע שהמחשב נכבה, קלוד
בענן עבד עוד 8 שעות לכל היותר, ואחרי זה כל ריצה החזירה
`401 OAuth access token has been revoked`. נמדד כאן ב-08/11 01:17:
הסוד החזיק אסימון שתוקפו 09:13 — שמונה שעות מהכיבוי, לא יומיים
ובהחלט לא שבוע. זה *בדיוק* מה שהמשתמש חווה כ"הבוטים מפסיקים לעבוד
כשהמחשב כבוי".

== התיקון ==

לענן יש מעכשיו **אסימון רענון** משלו (סוד `CLAUDE_REFRESH_TOKEN`),
והריצה מחדשת בעצמה את אסימון הגישה לפני שהיא מפעילה את קלוד. אסימון
רענון תקף 28 יום, **וכל רענון דוחף את התוקף שלו קדימה** — ולכן מכונת
ענן שרצה אחת לכמה ימים מחזיקה את עצמה בחיים ללא הגבלת זמן, בלי
שהמחשב יידלק אפילו פעם אחת.

== המלכודת היחידה כאן, והיא קריטית ==

אנתרופיק **מסתובבת את אסימון הרענון בכל רענון** (נמדד ותועד ב-
claude_bot/claudeauth.py, 01/10): הרענון מחזיר אסימון רענון *חדש*
ומבטל את הישן. לכן רענון בענן הופך את האסימון שבמחשב למבוטל, ואם
אין לזה מענה — ההתחברות של Claude Code *במחשב עצמו* נשברת ברגע
שהמשתמש מדליק אותו. זו תקלה חמורה בהרבה מזו שאנחנו מתקנים.

ולכן הסקריפט הזה **מפרסם את ההזדהות החדשה בחזרה אל המחשב**: הוא
כותב אותה מוצפנת (nacl SecretBox, מפתח `CLOUD_CRED_KEY` שקיים רק
ב-.env של המחשב וכסוד בריפו) למאגר פרטי `bots-auth`, והמחשב מאמץ
אותה בעלייה ובכל רבע שעה (claude_bot/cloudcreds.py). כלומר האסימון
נשאר **אחד**, מסונכרן לשני הכיוונים — "אותו קלוד" בענן ובמחשב, ממש
כמו שהמשתמש ביקש.

הפרסום נעשה **לפני** השימוש באסימון החדש: אם הריצה תיפול באמצע,
המחשב עדיין יוכל להתאושש. סדר הפוך היה משאיר אסימון מבוטל במחשב
ואסימון חי שאיש אינו מכיר.

== מה הסקריפט מדפיס, ומה לא ==

לעולם לא את האסימונים עצמם, גם לא חלקית. הוא מדפיס רק טביעת אצבע
של שמונה תווים, את זמני הפקיעה, ושורת סיכום בעברית. בנוסף הוא מבקש
מ-GitHub להסתיר את האסימון החדש מכל פלט (`::add-mask::`), כי הריפו
ציבורי והיומן גלוי לכל.

הרצה (בתוך הרנר):
    python3 cloudrefresh.py --out /tmp/claude_token.txt
יציאה 0 = יש אסימון גישה תקף בקובץ היעד. יציאה 1 = אין, והקורא
צריך ליפול חזרה לסוד הישן.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_URLS = (
    "https://console.anthropic.com/v1/oauth/token",
    "https://api.anthropic.com/v1/oauth/token",
)
AUTH_REPO = "bots-auth"          # מאגר פרטי, רק לקובץ ההזדהות המוצפן
AUTH_PATH = "cred.enc"
SECRET_REFRESH = "CLAUDE_REFRESH_TOKEN"
SECRET_ACCESS = "CLAUDE_CODE_OAUTH_TOKEN"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                       # noqa: BLE001
    pass


def say(msg: str) -> None:
    print(msg, flush=True)


def fp(tok: str) -> str:
    """טביעת אצבע לזיהוי שינוי. האסימון עצמו אינו נרשם בשום מקום."""
    return hashlib.sha256((tok or "").encode()).hexdigest()[:8]


def when(ms) -> str:
    try:
        ms = int(ms or 0)
    except Exception:                                   # noqa: BLE001
        return "?"
    if not ms:
        return "?"
    return time.strftime("%d/%m %H:%M", time.gmtime(ms / 1000)) + " UTC"


# --------------------------------------------------------------- GitHub

def gh(method: str, path: str, data=None):
    tok = os.environ.get("GH_TOKEN", "").strip()
    if not tok:
        return 0, "אין GH_TOKEN"
    url = path if path.startswith("http") else "https://api.github.com" + path
    req = urllib.request.Request(
        url, method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization": "Bearer " + tok,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json",
                 "User-Agent": "cloudrefresh"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            body = r.read()
            return r.status, (json.loads(body) if body.strip() else {})
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:300]
    except Exception as exc:                            # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


_me = [""]


def me() -> str:
    if not _me[0]:
        st, d = gh("GET", "/user")
        _me[0] = d.get("login", "") if st == 200 and isinstance(d, dict) else ""
    return _me[0]


def set_secret(repo_slug: str, name: str, value: str) -> bool:
    """
    כתיבת סוד דורשת sealed box של libsodium מול המפתח הציבורי של הריפו.
    אין דרך לשלוח סוד בטקסט גלוי — ה-API דוחה.
    """
    try:
        from nacl import encoding, public                # noqa: PLC0415
    except Exception as exc:                             # noqa: BLE001
        say(f"  ⚠️ אין pynacl ({exc}) — לא ניתן לעדכן סוד")
        return False
    st, key = gh("GET", f"/repos/{repo_slug}/actions/secrets/public-key")
    if st != 200 or not isinstance(key, dict):
        say(f"  ⚠️ אין גישה לסודות ({st})")
        return False
    sealed = public.SealedBox(
        public.PublicKey(key["key"].encode(), encoding.Base64Encoder))
    enc = base64.b64encode(sealed.encrypt(value.encode())).decode()
    st, res = gh("PUT", f"/repos/{repo_slug}/actions/secrets/{name}",
                 {"encrypted_value": enc, "key_id": key["key_id"]})
    ok = st in (201, 204)
    say(("  ✅ סוד עודכן: " if ok else "  ⚠️ עדכון סוד נכשל: ") + name
        + ("" if ok else f" ({st} {res})"))
    return ok


# --------------------------------------------- המאגר הפרטי של ההזדהות

def seal(payload: dict, key_src: str) -> bytes:
    from nacl import secret                              # noqa: PLC0415
    box = secret.SecretBox(hashlib.sha256(key_src.encode()).digest())
    return box.encrypt(json.dumps(payload, ensure_ascii=False).encode())


def ensure_auth_repo(slug: str) -> bool:
    st, _ = gh("GET", f"/repos/{slug}")
    if st == 200:
        return True
    st, res = gh("POST", "/user/repos",
                 {"name": AUTH_REPO, "private": True, "auto_init": True,
                  "description": "הזדהות מוצפנת בין המחשב למכונת הענן"})
    ok = st in (201,)
    say(("  ✅ נוצר מאגר ההזדהות הפרטי" if ok
         else f"  ⚠️ יצירת מאגר ההזדהות נכשלה ({st} {res})"))
    return ok


def publish(creds: dict) -> bool:
    """מפרסם את ההזדהות החדשה, מוצפנת, כדי שהמחשב יאמץ אותה בעלייה."""
    key_src = os.environ.get("CLOUD_CRED_KEY", "").strip()
    if not key_src:
        say("  ⚠️ אין CLOUD_CRED_KEY — ההזדהות החדשה לא תפורסם למחשב. "
            "זו בדיוק המלכודת שמשאירה את המחשב עם אסימון מבוטל.")
        return False
    owner = me()
    if not owner:
        say("  ⚠️ אין זיהוי חשבון גיטהאב — אין לאן לפרסם")
        return False
    slug = f"{owner}/{AUTH_REPO}"
    if not ensure_auth_repo(slug):
        return False
    try:
        blob = seal({"claudeAiOauth": creds, "at": int(time.time() * 1000),
                     "by": "cloud"}, key_src)
    except Exception as exc:                            # noqa: BLE001
        say(f"  ⚠️ הצפנה נכשלה ({exc})")
        return False
    st, cur = gh("GET", f"/repos/{slug}/contents/{AUTH_PATH}")
    body = {"message": "הזדהות חדשה ממכונת הענן",
            "content": base64.b64encode(blob).decode()}
    if st == 200 and isinstance(cur, dict) and cur.get("sha"):
        body["sha"] = cur["sha"]
    st, res = gh("PUT", f"/repos/{slug}/contents/{AUTH_PATH}", body)
    ok = st in (200, 201)
    say("  ✅ ההזדהות החדשה פורסמה למחשב (מוצפנת)" if ok
        else f"  ⚠️ פרסום ההזדהות נכשל ({st} {res})")
    return ok


# ------------------------------------------------------------- הרענון

def post(url: str, payload: dict):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "cloudrefresh"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:                            # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def refresh(token: str):
    """מחזיר (creds|None, הסבר). creds במבנה claudeAiOauth של ה-CLI."""
    last = ""
    for url in TOKEN_URLS:
        code, body = post(url, {"grant_type": "refresh_token",
                                "refresh_token": token,
                                "client_id": CLIENT_ID})
        if code != 200:
            last = f"HTTP {code}: {body[:160]}"
            continue
        try:
            got = json.loads(body)
        except Exception as exc:                        # noqa: BLE001
            last = f"תשובה שאינה JSON ({exc})"
            continue
        access = got.get("access_token") or got.get("accessToken")
        if not access:
            last = "בתשובת השרת אין אסימון גישה"
            continue
        now_ms = int(time.time() * 1000)
        creds = {"accessToken": access,
                 "refreshToken": (got.get("refresh_token")
                                  or got.get("refreshToken") or token)}
        if got.get("expires_in") is not None:
            creds["expiresAt"] = now_ms + int(float(got["expires_in"]) * 1000)
        if got.get("refresh_expires_in") is not None:
            creds["refreshTokenExpiresAt"] = \
                now_ms + int(float(got["refresh_expires_in"]) * 1000)
        if isinstance(got.get("scope"), str):
            creds["scopes"] = got["scope"].split()
        creds["subscriptionType"] = got.get("subscriptionType") or "max"
        return creds, "רענון הצליח"
    return None, last or "לא התקבלה תשובה"


def write_cli_creds(creds: dict) -> None:
    """כותב את קובץ ההתחברות של ה-CLI, כדי שגם מסלול הקובץ יעבוד."""
    home = os.path.expanduser("~")
    d = os.path.join(home, ".claude")
    try:
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, ".credentials.json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"claudeAiOauth": creds}, fh)
        os.replace(tmp, os.path.join(d, ".credentials.json"))
        os.chmod(os.path.join(d, ".credentials.json"), 0o600)
    except Exception as exc:                            # noqa: BLE001
        say(f"  ⚠️ כתיבת קובץ ההתחברות נכשלה ({exc})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/claude_token.txt")
    args = ap.parse_args()

    repo_slug = os.environ.get("GITHUB_REPOSITORY", "").strip()
    rtok = os.environ.get("CLAUDE_REFRESH_TOKEN", "").strip()
    atok = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()

    if not rtok:
        say("אין אסימון רענון בענן — נשארים על האסימון שהמחשב דחף.")
        say("(זה המצב הישן: תקף שמונה שעות מהכיבוי בלבד.)")
        if atok:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(atok)
            return 0
        return 1

    say(f"מחדש הזדהות בענן (אסימון רענון {fp(rtok)})…")
    creds, why = refresh(rtok)
    if not creds:
        say(f"⚠️ החידוש נכשל: {why}")
        if atok:
            say("ממשיכים עם האסימון שהמחשב דחף (אם הוא עוד תקף).")
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(atok)
            return 0
        return 1

    say(f"✅ {why}. אסימון גישה עד {when(creds.get('expiresAt'))}, "
        f"אסימון רענון עד {when(creds.get('refreshTokenExpiresAt'))}.")
    # הסתרה מהיומן לפני כל שימוש. הריפו ציבורי.
    say("::add-mask::" + creds["accessToken"])
    say("::add-mask::" + creds["refreshToken"])

    # *** סדר הפעולות כאן אינו שרירותי. ***
    # קודם מפרסמים למחשב, ורק אחר כך משתמשים. הסיבוב כבר ביטל את
    # האסימון שבמחשב ברגע שהשרת ענה; אם נקרוס לפני הפרסום, המחשב
    # יישאר בלי התחברות ואיש לא יידע את החדשה.
    publish(creds)
    if repo_slug:
        set_secret(repo_slug, SECRET_REFRESH, creds["refreshToken"])
        set_secret(repo_slug, SECRET_ACCESS, creds["accessToken"])

    write_cli_creds(creds)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(creds["accessToken"])
    say("ההזדהות בענן מחודשת ומסונכרנת.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
