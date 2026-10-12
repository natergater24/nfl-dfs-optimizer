#!/bin/bash
# Creates a double-clickable "Launch NFL DFS" on the Desktop.
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$HOME/Desktop/Launch_NFL_DFS.command"
printf '#!/bin/bash\nbash "%s/launch.sh"\n' "$PROJECT" > "$TARGET"
chmod +x "$TARGET"
echo "created $TARGET"
