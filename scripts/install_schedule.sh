#!/bin/bash
# Installs (or re-installs) the weekly NFL DFS schedule as macOS LaunchAgents.
set -e
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS" "$PROJECT/logs"
for tpl in "$PROJECT"/scripts/launchagents/*.plist.template; do
    name="$(basename "$tpl" .template)"
    label="${name%.plist}"
    sed -e "s#__PROJECT__#$PROJECT#g" -e "s#__HOME__#$HOME#g" "$tpl" > "$AGENTS/$name"
    plutil -lint "$AGENTS/$name" >/dev/null
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
    # bootout is asynchronous: retry bootstrap until the old job has gone.
    booted=0
    for _ in 1 2 3 4 5; do
        if launchctl bootstrap "gui/$(id -u)" "$AGENTS/$name" 2>/dev/null; then
            booted=1
            break
        fi
        sleep 1
    done
    if [ "$booted" -ne 1 ]; then
        echo "could not load $label after 5 attempts (launchctl bootstrap failed)."
        echo "Check it with: launchctl print gui/$(id -u)/$label"
        exit 1
    fi
    echo "installed $label"
done
echo
echo "Last step — lets your Mac wake itself before each run (asks for your Mac password):"
echo "  sudo pmset repeat wakeorpoweron TRU 08:55:00"
