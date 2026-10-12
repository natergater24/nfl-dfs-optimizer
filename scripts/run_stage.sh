#!/bin/bash
# LaunchAgent wrapper: ./scripts/run_stage.sh <stage>
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
LOG="$PROJECT/logs/launchagent.log"
STAGE="$1"
mkdir -p "$PROJECT/logs"
cd "$PROJECT" || exit 1
if [ "$STAGE" = "sunday" ]; then
    # Keep the Mac awake from 9:00 through the 11:45 run (3h15m).
    caffeinate -dims -t 11700 >/dev/null 2>&1 &
fi
echo "[$(date '+%Y-%m-%d %H:%M:%S')] === $STAGE starting ===" >> "$LOG"
caffeinate -i "$PYTHON" run_pipeline.py --stage "$STAGE" >> "$LOG" 2>&1
RC=$?
echo "[$(date '+%Y-%m-%d %H:%M:%S')] === $STAGE finished (exit $RC) ===" >> "$LOG"
exit $RC
