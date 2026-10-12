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
    launchctl bootstrap "gui/$(id -u)" "$AGENTS/$name"
    echo "installed $label"
done
echo
echo "Last step — lets your Mac wake itself before each run (asks for your Mac password):"
echo "  sudo pmset repeat wakeorpoweron TRU 08:55:00"
