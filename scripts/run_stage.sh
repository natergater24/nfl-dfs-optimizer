#!/bin/bash
# LaunchAgent wrapper: ./scripts/run_stage.sh <stage>
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
LOG="$PROJECT/logs/launchagent.log"
STAGE="$1"
mkdir -p "$PROJECT/logs"
cd "$PROJECT" || exit 1

# A scheduled wake on battery is a "dark wake": macOS goes back to sleep within minutes unless something
# says the user is active. -u (user active) turns it into a full wake and also works on battery; -s only
# works on power. A closed lid on battery still forces sleep, so keep the lid open or the Mac plugged in.
case "$STAGE" in
    sunday)                      KEEP_AWAKE=11700 ;;  # 9:00 through the 11:45 run (3h15m)
    tuesday|thursday|sunday_late|nba) KEEP_AWAKE=5400 ;;   # 90 minutes; a normal run takes a few
    *)                           KEEP_AWAKE=0 ;;
esac
if [ "$KEEP_AWAKE" -gt 0 ]; then
    caffeinate -dimsu -t "$KEEP_AWAKE" >/dev/null 2>&1 &
    KEEP_PID=$!
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === $STAGE starting ===" >> "$LOG"
caffeinate -dims "$PYTHON" run_pipeline.py --stage "$STAGE" >> "$LOG" 2>&1
RC=$?
echo "[$(date '+%Y-%m-%d %H:%M:%S')] === $STAGE finished (exit $RC) ===" >> "$LOG"
# Sunday 9:00 keeps the Mac awake through the 11:45 run; every other stage lets it sleep again when done.
if [ -n "$KEEP_PID" ] && [ "$STAGE" != "sunday" ]; then
    kill "$KEEP_PID" 2>/dev/null
fi
exit $RC
