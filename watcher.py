#!/usr/bin/env python3
"""Watch Team Rubicon Roll Call "Find Events" for new events and notify you about them
(phone push via ntfy and/or a desktop notification on macOS or Windows).

How it works
------------
Roll Call (rollcall.teamrubiconusa.org) is an Angular single-page app. The Find Events
page loads every published event nationwide from one JSON endpoint:

    https://wa-evtmgmt-webapi-prod-wus.azurewebsites.net/api/event/getPublishedEvents

Login goes through Azure AD B2C via MSAL.js, which keeps its tokens in the page's
localStorage (not cookies). Rather than re-implementing that auth flow, the watcher
drives a real Chromium-based browser (via Playwright) with its own dedicated profile, loads the
Find Events page, and captures the JSON the page fetches for itself. Your one-time
interactive login (`watcher.py login`) is persisted in that profile, and MSAL silently
renews tokens on each headless run for as long as the B2C session lasts.

Each run then:
  1. keeps only events within reach of your home (see in_radius),
  2. compares their IDs against state/seen.json,
  3. sends one notification per never-seen event (see notify), and
  4. records them as seen.

Usage:
  watcher.py login   # opens a visible browser window; log into Roll Call once, then close it
  watcher.py run     # headless check (what launchd runs; every 24 h by default)
  watcher.py test    # send a test notification (phone and/or desktop)

Exit codes for `run`: 0 = success, 2 = login needed; other failures raise (non-zero).

Platform support
----------------
Built and tested only on macOS (Apple silicon, python.org Python 3.13, Brave). The Python
code itself is portable: Playwright, certifi and the standard library all run on macOS,
Windows and Linux, and the browser is chosen in config.json (see BROWSER_PATH below).
The one macOS-specific piece is scheduling: install.sh + launchd/*.plist.template use
launchd. Use Task Scheduler on Windows, or a cron job / systemd user timer on Linux, to
run `watcher.py run` every 24 hours (or whatever interval you like).
`login` opens a visible browser window, so it needs a desktop session; on a headless
Linux server, run it under xvfb-run or over X forwarding. `run` is headless and needs no
display. Windows and Linux are expected to work with those changes but are untested.
Desktop notifications (see desktop_notify) support macOS and Windows; on Linux they are
skipped, so use ntfy there.
"""
import json
import math
import os
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import certifi
from playwright.sync_api import sync_playwright

# --- Paths -----------------------------------------------------------------------------
# Everything lives next to this file so the project folder is self-contained.
ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"                       # git-ignored runtime state
PROFILE_DIR = STATE_DIR / "browser-profile"      # dedicated browser profile holding the login
SEEN_FILE = STATE_DIR / "seen.json"              # sorted list of eventIds already handled
LAST_RESPONSE = STATE_DIR / "last_response.json" # raw API payload from the latest run (debugging)
AUTH_ALERT_FILE = STATE_DIR / "auth_alert_sent"  # mtime = when we last sent "login needed"

# config.json keys: ntfy_server, ntfy_topic (null = no phone pushes), home_lat, home_lon,
# optional max_miles, optional browser_path, optional desktop_notifications (default
# true), optional check_interval_hours (read by install.sh, not here; default 24).
# (home_zip is informational only; the code uses the lat/lon.) config.json is personal
# and git-ignored; config.example.json is the published template to copy from.
CONFIG_FILE = ROOT / "config.json"
if not CONFIG_FILE.exists():
    sys.exit(f"Missing {CONFIG_FILE}: copy config.example.json to config.json and fill it in.")
CONFIG = json.loads(CONFIG_FILE.read_text())
# Both channels are optional, but at least one must be on or alerts would go nowhere.
USE_NTFY = bool(CONFIG.get("ntfy_topic"))
USE_DESKTOP = CONFIG.get("desktop_notifications", True)
if not (USE_NTFY or USE_DESKTOP):
    sys.exit("config.json: set ntfy_topic and/or desktop_notifications, or you'll never be notified.")

# python.org builds of Python on macOS don't use the system keychain for TLS roots, so
# HTTPS fails with CERTIFICATE_VERIFY_FAILED. Use certifi's CA bundle explicitly.
SSL_CTX = ssl.create_default_context(cafile=certifi.where())

# --- Browser ---------------------------------------------------------------------------
# Any Chromium-based browser works (Brave, Chrome, Edge, Chromium); Playwright drives it
# over the Chrome DevTools Protocol, so Firefox/Safari won't. config.json "browser_path"
# is the browser's executable, e.g.
#   macOS:   /Applications/Brave Browser.app/Contents/MacOS/Brave Browser
#            /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
#   Windows: C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe
#            C:\Program Files\Google\Chrome\Application\chrome.exe
#   Linux:   /usr/bin/brave-browser, /usr/bin/google-chrome, /usr/bin/chromium
# Omitted or null: use Playwright's own bundled Chromium, which must be downloaded once
# with `.venv/bin/playwright install chromium`.
BROWSER_PATH = CONFIG.get("browser_path")

# --- Roll Call endpoints -----------------------------------------------------------------
FIND_EVENTS_URL = "https://rollcall.teamrubiconusa.org/find-events"
# Per-event page; takes the event's readableEventId, e.g.
# .../event/sessions?id=Springfield_Trailer_Inventory123456789
EVENT_URL = "https://rollcall.teamrubiconusa.org/event/sessions"
# Substring matched against request URLs to spot the events API call. The real request
# also carries an emApplicationtoken query param, which the page adds itself.
EVENTS_API = "api/event/getPublishedEvents"


def ensure_state_dir():
    """Create state/ readable only by you (0700): it holds the browser login session
    and last_response.json, which includes event organizers' names and emails.
    Restricting the directory covers every file inside it, old and new."""
    STATE_DIR.mkdir(mode=0o700, exist_ok=True)
    STATE_DIR.chmod(0o700)


def log(msg):
    """Timestamped line to stdout; under launchd this goes to state/watcher.log."""
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


NTFY_PRIORITY = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}


def ntfy(title, message, click=None, priority="high", tags="rotating_light"):
    """Publish a push notification to the configured ntfy topic.

    Uses ntfy's JSON publishing (POST to the server root) rather than the simpler
    "body + Title/Tags headers" form. Titles contain organizer-supplied event names, and
    HTTP headers can't carry newlines or non-Latin-1 characters (emoji, em dashes, curly
    quotes): one such event name would make urllib raise on every run. A JSON body is
    UTF-8 and keeps untrusted text out of headers entirely.

      title    - bold first line of the notification
      priority - min/low/default/high/urgent; "high" makes the phone buzz/sound
      tags     - comma-separated; names matching emoji shortcodes render as emoji
      click    - URL opened when the notification is tapped (always built by us,
                 never taken from the API, so the payload can't redirect you elsewhere).
                 Also sent as an "Open Event" view-action button: the iOS app only
                 follows the tap-URL from the system banner, while tapping the message
                 inside the app copies its text. The button works in both places
                 (long-press the banner to see it).
    Anyone who knows the topic name can read or post to it, so it's a random string.
    """
    payload = {
        "topic": CONFIG["ntfy_topic"],
        "title": title,
        "message": message,
        "priority": NTFY_PRIORITY[priority],
        "tags": tags.split(","),
        **({"click": click,
            "actions": [{"action": "view", "label": "Open Event", "url": click}]}
           if click else {}),
    }
    req = urllib.request.Request(
        CONFIG["ntfy_server"].rstrip("/") + "/",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=20, context=SSL_CTX).read()


# macOS dialog for alerts that have a link (macOS notifications can't open a URL when
# clicked; they open Script Editor). A dialog stays on screen until you click a button,
# so it also can't be missed the way a banner can. argv: window title, text, URL.
MAC_DIALOG_SCRIPT = """on run argv
activate
if (item 4 of argv) is "1" then beep
set r to display dialog (item 2 of argv) with title (item 1 of argv) ¬
    buttons {"Dismiss", "Open Event"} default button "Open Event" with icon note
if button returned of r is "Open Event" then open location (item 3 of argv)
end run"""

# Windows toast: Windows PowerShell 5.1 (powershell.exe, built into Windows 10/11; not
# PowerShell 7's pwsh) can call the WinRT toast API directly, so nothing extra is needed.
# The toast XML is built and escaped in Python and passed in an environment variable, so
# event text never becomes part of the PowerShell script. Toasts must belong to a
# registered app ID; PowerShell's own is borrowed, so they appear as "Windows PowerShell".
WINDOWS_TOAST_PS = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($env:RUBICON_TOAST_XML)
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show(
    [Windows.UI.Notifications.ToastNotification]::new($xml))
"""


def desktop_notify(title, message, click=None, sound=True):
    """Show a notification on this computer's desktop (macOS or Windows).

    The watcher only runs while you're logged in, so a desktop notification reaches you
    whenever a check happens at your computer. Both methods use tools built into the OS
    and pass event text as data (argv / an environment variable), never spliced into a
    script, because event names come from Roll Call organizers.

      macOS:   with a link (new events, test): a dialog with "Open Event" / "Dismiss"
               buttons (MAC_DIALOG_SCRIPT) that stays until you answer it. osascript is
               started detached in its own session, so the run doesn't wait for you and
               launchd doesn't kill it when the run ends; several new events give
               several dialogs. Without a link ("running", "login needed"): a regular
               notification ("display notification"), which macOS attributes to
               "Script Editor" in System Settings > Notifications.
      Windows: a toast via PowerShell (see WINDOWS_TOAST_PS). Clicking it opens the
               event page; missed toasts wait in Notification Center.
      Other:   not supported; does nothing.
    """
    if sys.platform == "darwin" and click:
        subprocess.Popen(["osascript", "-e", MAC_DIALOG_SCRIPT, "Rubicon Watcher",
                          f"{title}\n\n{message}", click, "1" if sound else "0"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    elif sys.platform == "darwin":
        script = ("on run argv\n"
                  "display notification (item 2 of argv) with title (item 1 of argv)"
                  + (' sound name "Glass"' if sound else "") + "\n"
                  "end run")
        subprocess.run(["osascript", "-e", script, title, message],
                       check=True, capture_output=True, timeout=30)
    elif sys.platform == "win32":
        # click is always our own event_url, but escape it anyway since it's an attribute.
        launch = (f' activationType="protocol" launch="{xml_escape(click, {chr(34): "&quot;"})}"'
                  if click else "")
        audio = "" if sound else '<audio silent="true"/>'
        toast = (f'<toast{launch}><visual><binding template="ToastGeneric">'
                 f"<text>{xml_escape(title)}</text><text>{xml_escape(message)}</text>"
                 f"</binding></visual>{audio}</toast>")
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_TOAST_PS],
                       env={**os.environ, "RUBICON_TOAST_XML": toast},
                       check=True, capture_output=True, timeout=60,
                       creationflags=subprocess.CREATE_NO_WINDOW)  # no console window flash


def notify(title, message, click=None, priority="high", tags="rotating_light"):
    """Send one alert through every enabled channel: ntfy (phone) and the desktop.

    An ntfy failure raises, so cmd_run stops before updating seen.json and retries next
    run. A desktop failure is only logged: the computer may have notifications turned
    off, and that shouldn't block the phone push or cause repeats.
    """
    if USE_NTFY:
        ntfy(title, message, click=click, priority=priority, tags=tags)
    if USE_DESKTOP:
        try:
            desktop_notify(title, message, click=click, sound=priority in ("high", "urgent"))
        except Exception as e:
            log(f"Desktop notification failed: {e!r}")


# --- Browser / data capture ---------------------------------------------------------------

def launch(p, headless):
    """Start the configured Chromium-based browser with the watcher's persistent profile.

    A persistent context (rather than a fresh one) is what keeps the Roll Call login
    between runs. Only one process can hold a Chromium profile at a time, which is why
    this uses its own profile under state/ instead of your everyday browser profile.
    executable_path=None means Playwright's bundled Chromium.
    """
    return p.chromium.launch_persistent_context(
        str(PROFILE_DIR), executable_path=BROWSER_PATH, headless=headless,
        viewport={"width": 1400, "height": 900},
    )


class AuthRequired(Exception):
    """The page ended up on the B2C login screen instead of loading events."""


def fetch_events(headless=True, timeout_s=90):
    """Load Find Events in the watcher's browser profile and return the events API JSON.

    Raises AuthRequired if the session has expired, TimeoutError if the events request
    never completes (site down, page changed, etc.).
    """
    with sync_playwright() as p:
        ctx = launch(p, headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        captured = []

        # Intercept the events request, perform it ourselves, keep a copy of the body,
        # then hand the identical response back to the page. Simply waiting for the
        # response doesn't work: the page redirects (/find-events -> /find-events/)
        # right after load, and Chromium discards bodies Playwright hasn't read yet.
        def handle(route):
            resp = route.fetch()  # replays the page's request, auth headers included
            if resp.ok:
                captured.append(resp.json())
            route.fulfill(response=resp)

        page.route(f"**/{EVENTS_API}*", handle)
        try:
            page.goto(FIND_EVENTS_URL, wait_until="domcontentloaded")
            # Poll rather than block on a single event so redirects, MSAL token renewal
            # and the Bing map loading can't wedge us; stop at the first captured payload.
            deadline = time.time() + timeout_s
            while not captured and time.time() < deadline:
                page.wait_for_timeout(500)
            if captured:
                return captured[-1]
            # No data: if we were bounced to the Azure B2C login, the session expired.
            if "b2clogin.com" in page.url or "login" in page.url.lower():
                raise AuthRequired(page.url)
            raise TimeoutError(f"No events response within {timeout_s}s (at {page.url})")
        finally:
            ctx.close()


# --- Event fields ----------------------------------------------------------------------
# getPublishedEvents returns a JSON list of event dicts. Fields used here:
#   eventId                      GUID; stable unique key used for "seen" tracking
#   readableEventId              slug used in the per-event page URL
#   eventName, startDate         display ("2026-10-17T09:00:00", event-local time)
#   serviceType                  "Engagement" | "Training" | "Operation"
#   registrationRadiusOptionSet  the event's own max distance in miles (50..450, or
#                                10000 for events open to everyone)
#   customFields.vms_latitude / vms_longitude   event location (top-level latitude/
#                                longitude are null; use these)
#   customFields.vms_city, vms_state            vms_state is {"Id": ..., "Name": "WI"}
# The payload also contains organizer names/emails; don't log or forward it wholesale.

def event_list(data):
    """Validate the payload shape; fail loudly if Roll Call changes its API."""
    if not isinstance(data, list):
        raise ValueError(f"Unexpected events payload: {type(data).__name__}")
    return data


def event_id(ev):
    return ev["eventId"]


def miles_between(lat1, lon1, lat2, lon2):
    """Great-circle (haversine) distance in statute miles; 3958.8 = Earth radius in mi.

    Matches Roll Call's own "N miles away" figures to within ~1 mile.
    """
    lat1, lon1, lat2, lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    a = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 3958.8 * 2 * math.asin(math.sqrt(a))


def distance_miles(ev):
    """Miles from home (config home_lat/home_lon) to the event, or None if unknown."""
    cf = ev.get("customFields") or {}
    lat, lon = cf.get("vms_latitude"), cf.get("vms_longitude")
    if lat is None or lon is None:
        return None
    return miles_between(CONFIG["home_lat"], CONFIG["home_lon"], lat, lon)


def in_radius(ev):
    """Should this event trigger an alert?

    Rule: home is within the event's own max distance
    (registrationRadiusOptionSet). Note this is NOT what the Find Events list shows;
    that list includes everything sorted by distance. Events with a 10000-mile max
    therefore always qualify; set config max_miles to cap distance on top of the rule.
    Events without coordinates are skipped.
    """
    d = distance_miles(ev)
    if d is None:
        return False
    limit = ev.get("registrationRadiusOptionSet") or 0
    cap = CONFIG.get("max_miles")
    return d <= limit and (cap is None or d <= cap)


def event_url(ev):
    """Link opened when the notification is tapped; falls back to the Find Events list."""
    rid = ev.get("readableEventId")
    if not rid:
        return FIND_EVENTS_URL
    return f"{EVENT_URL}?id={urllib.parse.quote(rid)}"


def describe(ev):
    """(title, detail) for a notification, e.g.
    ("Springfield Trailer Inventory", "2026-10-17 · Springfield, IL · 85 mi away · Engagement")."""
    cf = ev.get("customFields") or {}
    state = cf.get("vms_state")
    state = state.get("Name") if isinstance(state, dict) else state
    place = ", ".join(x for x in (cf.get("vms_city"), state) if x)
    start = (ev.get("startDate") or "")[:10]
    d = distance_miles(ev)
    bits = [start, place, f"{d:.0f} mi away" if d is not None else None, ev.get("serviceType")]
    return ev.get("eventName") or "(untitled event)", " · ".join(b for b in bits if b)


# --- Commands ------------------------------------------------------------------------

def cmd_login():
    """Interactive one-time login: a visible browser window on the watcher's profile.

    Whatever you sign into here is saved in state/browser-profile and reused by `run`.
    Also clears the "login needed" throttle so a future expiry alerts promptly.
    """
    ensure_state_dir()
    print("A browser window will open. Log into Roll Call, wait for the Find Events page\n"
          "to show events, then close the window.")
    with sync_playwright() as p:
        ctx = launch(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(FIND_EVENTS_URL)
        page.wait_for_event("close", timeout=0)  # wait as long as the user needs
        ctx.close()
    AUTH_ALERT_FILE.unlink(missing_ok=True)
    print("Saved. Run `watcher.py run` to check that it works headless.")


def cmd_run():
    """One headless check. Returns the process exit code (0 ok, 2 login needed)."""
    ensure_state_dir()
    try:
        data = fetch_events()
    except AuthRequired:
        log("Not logged in.")
        # Alert at most once a day so an expired session doesn't spam you every run.
        if not AUTH_ALERT_FILE.exists() or time.time() - AUTH_ALERT_FILE.stat().st_mtime > 86400:
            notify("Rubicon watcher: login needed",
                   "Roll Call session expired. Run: watcher.py login", tags="warning")
            AUTH_ALERT_FILE.touch()
        return 2

    # Keep the raw payload for debugging / adjusting field mappings.
    LAST_RESPONSE.write_text(json.dumps(data, indent=2))
    events = [e for e in event_list(data) if in_radius(e)]
    current = {event_id(e): e for e in events}

    # First run (no seen.json) only records what's already listed, so you aren't
    # flooded with every existing event; it sends one confirmation push instead.
    first_run = not SEEN_FILE.exists()
    seen = set(json.loads(SEEN_FILE.read_text())) if not first_run else set()
    new_ids = [i for i in current if i not in seen]

    if first_run:
        notify("Rubicon watcher is running",
               f"Tracking {len(current)} current events. You'll be notified about new ones.",
               priority="default", tags="white_check_mark")
        log(f"First run: seeded {len(current)} events.")
    else:
        for i in new_ids:
            name, detail = describe(current[i])
            notify(f"New Rubicon event: {name}", detail or name, click=event_url(current[i]))
        log(f"{len(current)} events, {len(new_ids)} new.")

    # seen.json only grows (union), so an event that disappears and reappears won't
    # re-alert. It only gets in-radius IDs, so an event whose radius later expands to
    # include you will alert at that point. Written after notifying: if a push fails,
    # the run raises before this, so that run's new events are retried next run
    # (any that were already pushed before the failure will alert a second time).
    SEEN_FILE.write_text(json.dumps(sorted(seen | set(current))))
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "login":
        cmd_login()
    elif cmd == "run":
        try:
            sys.exit(cmd_run())
        except Exception as e:
            # Log a one-line summary (the traceback follows from the re-raise) so
            # failures are easy to spot when scanning state/watcher.log.
            log(f"ERROR: {e!r}")
            raise
    elif cmd == "test":
        # With a link, so the test also shows the macOS dialog (opens Find Events).
        notify("Rubicon watcher test", "If you see this, notifications are set up.",
               click=FIND_EVENTS_URL, tags="tada")
        print("Sent.")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
