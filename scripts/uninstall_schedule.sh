#!/bin/bash
# Removes the NFL DFS LaunchAgents.
AGENTS="$HOME/Library/LaunchAgents"
for f in "$AGENTS"/com.nfldfs.*.plist; do
    [ -e "$f" ] || continue
    launchctl bootout "gui/$(id -u)/$(basename "$f" .plist)" 2>/dev/null || true
    rm -f "$f"
    echo "removed $(basename "$f" .plist)"
done
echo
echo "To also stop the automatic wake-ups: sudo pmset repeat cancel"
