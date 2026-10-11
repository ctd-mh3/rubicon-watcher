#!/bin/zsh
# Install (or reinstall) the macOS launchd schedule for the Rubicon watcher.
#
# Renders launchd/<label>.plist.template with this project's absolute path, writes it to
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

mkdir -p "$PROJECT_DIR/state" "$HOME/Library/LaunchAgents"
chmod 700 "$PROJECT_DIR/state"   # login session + organizer contact data; owner only
sed "s#__PROJECT_DIR__#$PROJECT_DIR#g" "$TEMPLATE" > "$TARGET"
plutil -lint "$TARGET" >/dev/null

# Unload any previous version first (errors if not loaded, which is fine), then load.
# Loading also triggers one immediate run because of RunAtLoad.
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$TARGET"

echo "Installed $LABEL (runs every 6 hours; log: $PROJECT_DIR/state/watcher.log)"
