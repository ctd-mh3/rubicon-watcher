#!/bin/zsh
# Remove the macOS launchd schedule for the Rubicon watcher.
# Leaves the project folder, config.json and state/ (login, seen events, log) untouched.
set -euo pipefail

LABEL=com.crashtestdummylimited.rubicon-watcher
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true   # ignore "not loaded"
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Uninstalled $LABEL"
