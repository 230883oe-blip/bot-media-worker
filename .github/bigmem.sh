#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# הרחבת הזיכרון האפקטיבי של רנר GitHub Actions ליעד שניתן כארגומנט (ג'יגה).
#
# למה זה כאן בכלל
# ----------------
# ארבע ריצות נהרגו כאן ב-exit 137 (OOM) בשלב בניית ה-BVH של Cycles,
# ושיא הזיכרון שנמדד היה 10.6GB מתוך 16 - כלומר כל החלטת איכות
# (רמת חלוקה, מספר בנים בשיער, גודל מפות) הוכפפה לתקרה הזאת.
#
# מה נבדק ומה **אינו** זמין
# -------------------------
# ריצוני GitHub הגדולים (``ubuntu-latest-16-cores`` ומעלה, 64GB) מוגדרים
# ברמת **ארגון או מיזם** ובתוכנית Team/Enterprise. לחשבון אישי אין בכלל
# נקודת קצה ליצירתם, ולכן אין "להפעיל" אותם - גם לא במאגר ציבורי.
# הריצון הסטנדרטי החינמי הוא 4 ליבות / 16GB.
#
# מה כן עובד, ונמדד
# ------------------
# לרנר יש SSD מקומי ב-``/mnt`` עם עשרות ג'יגה פנויים, ול-runner יש
# הרשאות sudo מלאות - כלומר ``swapon`` מותר. קובץ swap של 48GB עליו
# נותן 64GB מרחב כתובות. זה אינו טריק: בניית BVH ורשתות subdivision הן
# גישה סדרתית ברובה, והדפים שנדחפים לדיסק הם דווקא אלה שאינם בשימוש
# פעיל. ``swappiness=10`` מוודא שהגרעין יעדיף להשתמש ב-RAM האמיתי
# ויירד לדיסק רק כשהוא באמת נגמר - כלומר במקום ש-OOM היה הורג.
#
# זה מחליף נפילה בהאטה. האטה אפשר למדוד; תהליך הרוג אי אפשר.
# ---------------------------------------------------------------------------
set -u

TARGET="${1:-64}"
mkdir -p artifacts

echo "=== לפני ==="
free -m || true
df -h / /mnt 2>/dev/null || true

RAM_MB=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)
RAM_G=$(( RAM_MB / 1024 ))
NEED=$(( TARGET - RAM_G ))
[ "$NEED" -lt 0 ] && NEED=0
echo "RAM אמיתי: ${RAM_G}GB · יעד: ${TARGET}GB · נדרש swap: ${NEED}GB"

# הדיסק עם הכי הרבה מקום פנוי. ב-ubuntu-latest זה כמעט תמיד /mnt
# (ה-SSD הזמני), אבל אם מבנה הרנר ישתנה אין טעם שהשלב ייפול - הוא
# פשוט ייפול חזרה ל-/.
BEST=/mnt
FREE_MNT=$(df -BG --output=avail /mnt 2>/dev/null | tail -1 | tr -dc '0-9')
FREE_ROOT=$(df -BG --output=avail / 2>/dev/null | tail -1 | tr -dc '0-9')
FREE_MNT=${FREE_MNT:-0}; FREE_ROOT=${FREE_ROOT:-0}
if [ "${FREE_ROOT}" -gt "${FREE_MNT}" ]; then BEST=/; fi
AVAIL=$(( FREE_MNT > FREE_ROOT ? FREE_MNT : FREE_ROOT ))
echo "דיסק נבחר: ${BEST} (פנוי ${AVAIL}GB)"

# להשאיר 8GB לנכסים, לפריימים ול-artifacts. swap שממלא את הדיסק
# מחליף מוות בזיכרון במוות בדיסק, וזה לא שיפור.
MAXSWAP=$(( AVAIL - 8 ))
[ "$MAXSWAP" -lt 0 ] && MAXSWAP=0
if [ "$NEED" -gt "$MAXSWAP" ]; then
  echo "אין מספיק דיסק ל-${NEED}GB; יורד ל-${MAXSWAP}GB"
  NEED=$MAXSWAP
fi

OK=0
if [ "$NEED" -gt 0 ]; then
  SWAPF="${BEST}/bigswap"
  sudo swapoff -a 2>/dev/null || true
  sudo rm -f "$SWAPF" 2>/dev/null || true
  # fallocate מיידי; אם מערכת הקבצים אינה תומכת (או שהקובץ יוצא
  # מחורר ו-swapon מסרב) - נפילה ל-dd, שאיטית אבל תמיד עובדת.
  if sudo fallocate -l "${NEED}G" "$SWAPF" 2>/dev/null; then :; else
    echo "fallocate נכשל - עובר ל-dd"
    sudo dd if=/dev/zero of="$SWAPF" bs=1M count=$(( NEED * 1024 )) status=none
  fi
  sudo chmod 600 "$SWAPF"
  sudo mkswap -f "$SWAPF" >/dev/null 2>&1 || sudo mkswap "$SWAPF" >/dev/null
  if sudo swapon "$SWAPF" 2>/dev/null; then
    OK=1
  else
    echo "swapon נכשל על קובץ מחורר - בונה מחדש עם dd"
    sudo rm -f "$SWAPF"
    sudo dd if=/dev/zero of="$SWAPF" bs=1M count=$(( NEED * 1024 )) status=none
    sudo chmod 600 "$SWAPF"
    sudo mkswap "$SWAPF" >/dev/null
    sudo swapon "$SWAPF" && OK=1
  fi
  echo 10 | sudo tee /proc/sys/vm/swappiness >/dev/null 2>&1 || true
fi

echo "=== אחרי ==="
free -m
swapon --show || true

TOT=$(free -m | awk '/^Mem:/{m=$2} /^Swap:/{s=$2} END{printf "%d", (m+s)/1024}')
echo "זיכרון אפקטיבי כולל: ${TOT}GB (יעד ${TARGET}GB)"
cat > artifacts/bigmem.json <<JSON
{"ram_gb": ${RAM_G}, "swap_added_gb": ${NEED}, "swapon_ok": ${OK},
 "total_addressable_gb": ${TOT}, "target_gb": ${TARGET},
 "disk": "${BEST}", "disk_free_gb": ${AVAIL},
 "note": "larger runners (64GB) are org/enterprise only; personal account has no such runner"}
JSON

# **השלב אינו מפיל את הריצה.** אם מבנה הרנר השתנה והדיסק קטן
# מהצפוי, עדיף רינדור ב-16GB (שהוא מה שהיה עד היום) מאשר ריצה
# שנופלת על שלב תשתית. המספר נרשם ל-artifact ונקרא בדוח.
if [ "$TOT" -lt "$TARGET" ]; then
  echo "::warning::הזיכרון האפקטיבי הוא ${TOT}GB ולא ${TARGET}GB"
fi
exit 0
