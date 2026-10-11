# Rubicon Watcher

Get a phone notification when a new event is posted on Team Rubicon's
[Roll Call](https://rollcall.teamrubiconusa.org/find-events) near you.

Roll Call's own new-event notifications don't always arrive. This tool checks the Find
Events page every 6 hours as you (using your own login) and sends a push notification
through [ntfy](https://ntfy.sh) for each new event whose max travel distance reaches your
home. Tapping the notification opens that event's sign-up page.

> **Unofficial.** This is a personal tool by
> [Crash Test Dummy Limited](https://www.crashtestdummylimited.com) and is not affiliated
> with or endorsed by Team Rubicon. It only reads what your own logged-in account can
> already see, about 4 times a day.

Example notification:

```
New Rubicon event: Springfield Trailer Inventory
2026-10-17 · Springfield, IL · 85 mi away · Engagement
```

## How it works

Roll Call signs you in through Microsoft Azure AD B2C, and the session lives inside the
web page, so a simple script with a cookie can't fetch the events. Instead, the watcher
opens Roll Call in a real Chromium-based browser, running headless with its own separate profile.
You log into that profile once, and it captures the events data that the page itself
downloads. Then it:

1. measures the distance from your home to each event,
2. keeps the events whose own max distance reaches you,
3. compares them against the events it has already seen, and
4. sends one ntfy push per new event.

If Roll Call ever logs it out, you get a "login needed" push (at most once a day).

## Requirements

- macOS (Windows and Linux should work with small changes; see [Other platforms](#other-platforms))
- Python 3.10+
- A Chromium-based browser: Brave, Chrome, Edge or Chromium, or Playwright's bundled
  Chromium if you'd rather not use an installed browser (see `browser_path` below)
- The official **ntfy** app on your phone (by Philipp Heckel; iOS and Android, see
  [ntfy's phone setup](https://docs.ntfy.sh/subscribe/phone/))
- A Team Rubicon Roll Call account

## Setup (macOS)

```sh
git clone <this repo> rubicon-watcher && cd rubicon-watcher

# 1. Install
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Configure
cp config.example.json config.json
python3 -c "import secrets; print('rubicon-' + secrets.token_hex(8))"   # your private topic name
```

Edit `config.json`:

| Key | Value |
|---|---|
| `ntfy_topic` | The random topic name generated above. Anyone who knows it can read or post your notifications, so keep it private. |
| `home_lat`, `home_lon` | Your home location in decimal degrees (the center of your ZIP code is fine). |
| `home_zip` | Optional; for your reference only. |
| `browser_path` | Optional. Path to your browser's executable, e.g. `/Applications/Brave Browser.app/Contents/MacOS/Brave Browser` or `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`. Leave `null` to use Playwright's bundled Chromium; then run `.venv/bin/playwright install chromium` once. |
| `max_miles` | Optional. Ignore events farther than this, e.g. `500`. Without it, events open to volunteers nationwide are included. |

In the ntfy app, tap **+** and subscribe to your topic on the default `ntfy.sh` server. Then:

```sh
# 3. Verify
.venv/bin/python watcher.py test    # your phone should get a test notification
.venv/bin/python watcher.py login   # a browser window opens: log in, wait for events to load, close it
.venv/bin/python watcher.py run     # first run records current events and sends a "running" notification

# 4. Schedule (every 6 hours, starts automatically at login)
./install.sh
```

Run each command on a single line.

### macOS prompts you may see

- **"App Background Activity… Python Software Foundation"**: this is the scheduled job.
  Leave it enabled (System Settings → General → Login Items & Extensions).
- **"Data Access Blocked… python3.13"**: the watcher doesn't need that access. Leave it blocked.

## Usage

| Command | What it does |
|---|---|
| `.venv/bin/python watcher.py run` | Check now (what the schedule runs). |
| `.venv/bin/python watcher.py login` | Log in again after a "login needed" notification. |
| `.venv/bin/python watcher.py test` | Send a test notification. |
| `./install.sh` | Install or update the schedule. Re-run it after moving the folder or editing the template. |
| `./uninstall.sh` | Remove the schedule. Your config and login are kept. |
| `tail state/watcher.log` | See recent runs, e.g. `7 events, 0 new.` |

**When does it run?** Every 6 hours while you're logged into your Mac, plus once each time
you log in. If the Mac is asleep when a check is due, it runs once on wake. It doesn't run
while no one is logged in (for example, right after a reboot before you log in). To change
the interval, edit `StartInterval` (in seconds) in `launchd/*.plist.template` and re-run
`./install.sh`.

**Which events alert?** New events where your distance from the event is within *that
event's own* maximum travel distance, as set by its organizer (shown on Roll Call as
"N miles away vs a M mile max distance"). Events open to everyone always qualify unless
you set `max_miles`. Events already listed on the first run don't alert.

## Other platforms

The Python code is cross-platform; only the browser path and the scheduler are macOS-specific.

- **Browser:** set `browser_path` in `config.json`, e.g.
  `C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe` (Windows, with backslashes
  doubled because it's JSON) or `/usr/bin/google-chrome` (Linux). Or leave it `null` to use
  Playwright's bundled Chromium. More example paths are in `watcher.py`.
- **Windows scheduling:** create a Task Scheduler task that runs
  `.venv\Scripts\python.exe watcher.py run` every 6 hours while you're logged on.
- **Linux scheduling:** use cron, e.g.
  `0 */6 * * * /path/.venv/bin/python /path/watcher.py run >> /path/state/watcher.log 2>&1`,
  or a systemd user timer. `login` needs a display; `run` doesn't.

Windows and Linux haven't been tested.

## Privacy

- Your Roll Call login stays in the local `state/browser-profile/` folder. The watcher never
  sees or stores your password.
- `config.json` (your topic and location) and `state/` are git-ignored. Don't share them.
  `state/last_response.json` contains event organizers' contact details.
- Notifications go through the public ntfy.sh server and contain only event names, dates,
  places and distances.

## If something breaks

Roll Call isn't a public API, so changes on Team Rubicon's side can break the watcher.
Errors show up in `state/watcher.log`. `CLAUDE.md` has detailed technical notes on how the
site works and how the code maps its data.

## License

[MIT](LICENSE) © 2026 Crash Test Dummy Limited
