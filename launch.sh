#!/bin/bash
# Starts the local NFL DFS app on http://localhost:8502 and opens Chrome (data refresh is in the app).
PROJECT="$(cd "$(dirname "$0")" && pwd)"
STREAMLIT="/Library/Frameworks/Python.framework/Versions/3.14/bin/streamlit"
LOG="$PROJECT/logs/streamlit.log"
mkdir -p "$PROJECT/logs"
cd "$PROJECT" || exit 1
pkill -f "streamlit run app.py --server.headless true --server.port 8502" 2>/dev/null || true
# Wait (up to 5 s) for the old server to release port 8502 before starting a new one.
for _ in 1 2 3 4 5; do
    lsof -i :8502 -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 1
done
nohup caffeinate -i "$STREAMLIT" run app.py --server.headless true --server.port 8502 >> "$LOG" 2>&1 &
for _ in $(seq 1 30); do
    sleep 1
    if lsof -i :8502 -sTCP:LISTEN >/dev/null 2>&1; then
        open -a "Google Chrome" http://localhost:8502 2>/dev/null || open http://localhost:8502
        echo "NFL DFS app running at http://localhost:8502"
        exit 0
    fi
done
echo "The app didn't start — see $LOG"
tail -20 "$LOG"
exit 1
