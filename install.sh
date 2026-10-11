#!/bin/zsh
# Install (or reinstall) the macOS launchd schedule for the Rubicon watcher.
#
# Renders launchd/<label>.plist.template with this project's absolute path and the check
# interval (config.json "check_interval_hours", default 24), writes it to
# ~/Library/LaunchAgents, and loads it. Safe to re-run after editing the template or
# moving the project folder. It does NOT create the venv, config.json or the Roll Call
# login; see CLAUDE.md "System setup" for those steps (do them first).
#
# macOS only. On Windows use Task Scheduler; on Linux use cron or a systemd user timer.
set -euo pipefail

LABEL=com.crashtestdummylimited.rubicon-watcher
PROJECT_DIR=${0:A:h}                       # absolute dir of this script (zsh modifier)
TEMPLATE="$PROJECT_DIR/launchd/$LABEL.plist.template"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"                      # per-user GUI session domain

# Fail early with a helpful message instead of installing a job that can't run.
[[ -x "$PROJECT_DIR/.venv/bin/python" ]] || { echo "Missing .venv; run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2; exit 1; }
[[ -f "$PROJECT_DIR/config.json" ]] || { echo "Missing config.json; copy config.example.json and fill it in" >&2; exit 1; }
# macOS privacy protection (TCC) blocks launchd jobs from reading Desktop, Documents,
# Downloads and iCloud Drive, so a job installed from there fails silently every run.
case "$PROJECT_DIR/" in
  "$HOME/Desktop/"*|"$HOME/Documents/"*|"$HOME/Downloads/"*|"$HOME/Library/Mobile Documents/"*)
    echo "This folder is in Desktop, Documents, Downloads or iCloud Drive, which macOS blocks" >&2
    echo "background jobs from reading. Move it to your home folder (e.g. ~/rubicon-watcher)," >&2
    echo "then run: cd ~/rubicon-watcher && zsh install.sh" >&2
    exit 1 ;;
esac
# The path is pasted into XML by sed below, unescaped: '#' would end the sed expression,
# '&' and '\' are special in sed replacements, and '<' '&' '"' would corrupt the plist.
# Allow only ordinary path characters rather than trying to escape for both at once.
[[ "$PROJECT_DIR" =~ '^[A-Za-z0-9 ./_+@-]+$' ]] || { echo "Unsupported characters in project path: $PROJECT_DIR (move the folder)" >&2; exit 1; }

# Check interval: optional "check_interval_hours" in config.json (git-ignored, so a personal
# setting survives updates). Default 24 hours; must be a positive number (fractions allowed).
INTERVAL_SECONDS=$("$PROJECT_DIR/.venv/bin/python" - "$PROJECT_DIR/config.json" <<'PY'
import json, sys
h = json.load(open(sys.argv[1])).get("check_interval_hours", 24)
if isinstance(h, bool) or not isinstance(h, (int, float)) or h <= 0:
    sys.exit(f"check_interval_hours must be a positive number, got {h!r}")
print(max(60, round(h * 3600)))   # launchd's floor is effectively 1 minute
PY
) || { echo "Fix check_interval_hours in config.json" >&2; exit 1; }
INTERVAL_DESC=$(( INTERVAL_SECONDS % 3600 == 0 ? INTERVAL_SECONDS / 3600 : -1 ))
[[ $INTERVAL_DESC -gt 0 ]] && INTERVAL_DESC="every $INTERVAL_DESC hour(s)" || INTERVAL_DESC="every $INTERVAL_SECONDS seconds"

mkdir -p "$PROJECT_DIR/state" "$HOME/Library/LaunchAgents"
chmod 700 "$PROJECT_DIR/state"   # login session + organizer contact data; owner only
sed -e "s#__PROJECT_DIR__#$PROJECT_DIR#g" -e "s#__INTERVAL_SECONDS__#$INTERVAL_SECONDS#g" "$TEMPLATE" > "$TARGET"
plutil -lint "$TARGET" >/dev/null

# Unload any previous version first (errors if not loaded, which is fine), then load.
# Loading also triggers one immediate run because of RunAtLoad.
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$TARGET"

echo "Installed $LABEL (runs $INTERVAL_DESC; log: $PROJECT_DIR/state/watcher.log)"
