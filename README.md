# Rubicon Watcher

Get a phone notification when a new event is posted on Team Rubicon's
[Roll Call](https://rollcall.teamrubiconusa.org/find-events) near you.

Roll Call's own new-event notifications don't always arrive. This tool checks the Find
Events page once a day (adjustable) as you (using your own login) and sends a push notification
through [ntfy](https://ntfy.sh) for each new event whose max travel distance reaches your
home. Tapping the notification opens that event's sign-up page.

> **Unofficial.** This is a personal tool by
> [Crash Test Dummy Limited](https://www.crashtestdummylimited.com) and is not affiliated
> with or endorsed by Team Rubicon. It only reads what your own logged-in account can
> already see, once a day by default.

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
- Python 3.10+ (the python.org installer is the easy way; see Setup)
- A Chromium-based browser: Brave, Chrome, Edge or Chromium, or Playwright's bundled
  Chromium if you'd rather not use an installed browser (see `browser_path` below)
- The official **ntfy** app on your phone (by Philipp Heckel; iOS and Android, see
  [ntfy's phone setup](https://docs.ntfy.sh/subscribe/phone/))
- A Team Rubicon Roll Call account

## Setup (macOS)

No coding experience needed. Plan on 20–30 minutes. You'll copy commands into the
**Terminal** app, a window where you type commands. Paste **one command at a time** and
press Return after each.

### 1. Install the prerequisites

- **Python:** download and run the macOS installer from
  [python.org/downloads](https://www.python.org/downloads/). Don't rely on the `python3`
  that comes with macOS, which may ask to install "developer tools" instead.
- **A Chromium-based browser:** Google Chrome, Brave or Microsoft Edge. You probably have one already.
- **The ntfy app** on your phone (see Requirements above).

### 2. Download the watcher and put it in your home folder

Put the folder directly in your **home folder** (the one with your username, which
Finder's **Go → Home** opens), named `rubicon-watcher`. It ends up at `~/rubicon-watcher`.

> **Don't keep it in Downloads, Desktop or Documents** (or in iCloud Drive). macOS blocks
> background jobs from reading those folders, so the scheduled checks would fail
> without telling you. Also avoid special characters such as `&` or `#` in the folder path.

**Option A: download a ZIP (no git needed)**
1. On this project's GitHub page, click the green **Code** button → **Download ZIP**.
2. Double-click the ZIP in Downloads to unzip it. You get a folder named `rubicon-watcher-main`.
3. Rename that folder to `rubicon-watcher` and drag it into your home folder.

**Option B: with git** (if you have it), in Terminal:
```sh
git clone https://github.com/ctd-mh3/rubicon-watcher.git ~/rubicon-watcher
```

### 3. Install the watcher

Open **Terminal**: press ⌘-Space, type `Terminal`, and press Return. Then run:
```sh
cd ~/rubicon-watcher
```
```sh
python3 -m venv .venv
```
```sh
.venv/bin/pip install -r requirements.txt
```
This downloads the two components the watcher needs and keeps them inside the folder.
Every command from here on assumes Terminal is still "in" the folder. If you open a new
Terminal window, run `cd ~/rubicon-watcher` first.

### 4. Configure

Create your settings file and a private topic name for your notifications:
```sh
cp config.example.json config.json
```
```sh
python3 -c "import secrets; print('rubicon-' + secrets.token_hex(8))"
```
Copy the `rubicon-…` name it prints. Then open the settings file in TextEdit:
```sh
open -e config.json
```
Before typing, turn off curly quotes: **Edit → Substitutions → Smart Quotes** (unchecked).
The settings file needs plain straight quotes (`"`), and curly ones (`“ ”`) break it.

Fill in these values, keeping the quotes and commas as they are:

| Key | Value |
|---|---|
| `ntfy_topic` | The random topic name you just generated. Anyone who knows it can read or post your notifications, so keep it private. |
| `home_lat`, `home_lon` | Your home location in decimal degrees, e.g. `39.8` and `-89.6` (Springfield, IL). In Google Maps, right-click your home (or your town) and click the numbers at the top of the menu to copy them; the first is latitude, the second longitude. Neighborhood-level accuracy is plenty. |
| `home_zip` | Optional; for your reference only. |
| `browser_path` | The browser the watcher should use. Chrome: `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`. Brave: `"/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"`. Edge: `"/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"`. Or leave it `null` to use a separate copy of Chromium, after running `.venv/bin/playwright install chromium` once. |
| `check_interval_hours` | How often to check, in hours. Default `24`. For example `12` or `6` checks more often; please don't go below `1`, to stay polite to Roll Call. After changing it, run `zsh install.sh` again. |
| `max_miles` | Optional (add it if you want it). Ignore events farther than this, e.g. `500`. Without it, events open to volunteers nationwide are included. |

Save (⌘S) and close TextEdit. To check the file, run
`.venv/bin/python -m json.tool config.json`. It should print your settings back. An
error message usually means a missing comma or quote.

In the ntfy app, tap **+** and subscribe to your topic on the default `ntfy.sh` server.

### 5. Test, log in and start the schedule

```sh
.venv/bin/python watcher.py test
```
Your phone should get a test notification.
```sh
.venv/bin/python watcher.py login
```
A browser window opens. Log into Roll Call, wait until the Find Events page shows events,
then close that window. This login is saved for the watcher only; it doesn't change your
normal browser.
```sh
.venv/bin/python watcher.py run
```
The first run records the current events and sends a "Rubicon watcher is running" notification.
```sh
zsh install.sh
```
This starts the automatic schedule: every 24 hours, and again whenever you log into your Mac.
You're done. You can close Terminal.

### Updating to a newer version

Your settings (`config.json`) and login (`state/`) are not part of the download, so
updating leaves them alone.

- **Downloaded as a ZIP:** download the new ZIP and unzip it. Copy everything from the new
  `rubicon-watcher-main` folder into your `~/rubicon-watcher` folder, choosing **Replace**
  when asked. Then, in Terminal, run:
  `cd ~/rubicon-watcher && .venv/bin/pip install -r requirements.txt && zsh install.sh`
- **Used git:** in Terminal, run:
  `cd ~/rubicon-watcher && git pull && .venv/bin/pip install -r requirements.txt && zsh install.sh`

### macOS prompts you may see

- **"App Background Activity… Python Software Foundation"**: this is the scheduled job.
  Leave it enabled (System Settings → General → Login Items & Extensions).
- **"Data Access Blocked… python3.13"**: the watcher doesn't need that access. Leave it blocked.

## Usage

Run these in Terminal from inside the folder (`cd ~/rubicon-watcher` first).

| Command | What it does |
|---|---|
| `.venv/bin/python watcher.py run` | Check now (what the schedule runs). |
| `.venv/bin/python watcher.py login` | Log in again after a "login needed" notification. |
| `.venv/bin/python watcher.py test` | Send a test notification. |
| `zsh install.sh` | Install or update the schedule. Re-run it after moving the folder or editing the template. |
| `zsh uninstall.sh` | Remove the schedule. Your config and login are kept. |
| `tail state/watcher.log` | See recent runs, e.g. `7 events, 0 new.` |

**When does it run?** Every 24 hours by default (set `check_interval_hours` in `config.json`,
then re-run `zsh install.sh`) while you're logged into your Mac, plus once each time
you log in. If the Mac is asleep when a check is due, it runs once on wake. It doesn't run
while no one is logged in (for example, right after a reboot before you log in).

**Which events alert?** New events where your distance from the event is within *that
event's own* maximum travel distance, as set by its organizer (shown on Roll Call as
"N miles away vs a M mile max distance"). Events open to everyone always qualify unless
you set `max_miles`. Events already in range on the first run don't alert. An event that's
out of range is re-checked every run, so if its organizer later raises its max distance to
reach you, you're notified once at that point.

## Other platforms

The Python code is cross-platform; only the browser path and the scheduler are macOS-specific.

- **Browser:** set `browser_path` in `config.json`, e.g.
  `C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe` (Windows, with backslashes
  doubled because it's JSON) or `/usr/bin/google-chrome` (Linux). Or leave it `null` to use
  Playwright's bundled Chromium. More example paths are in `watcher.py`.
- **Windows scheduling:** create a Task Scheduler task that runs
  `.venv\Scripts\python.exe watcher.py run` daily (or as often as you like) while you're logged on.
- **Linux scheduling:** use cron, e.g.
  `0 8 * * * /path/.venv/bin/python /path/watcher.py run >> /path/state/watcher.log 2>&1`,
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
