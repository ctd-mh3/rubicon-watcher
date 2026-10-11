# Rubicon Watcher

Checks Team Rubicon's Roll Call "Find Events" page every 6 hours and sends a phone
push (via ntfy) for each **new** event whose own max distance reaches your home location.

By Crash Test Dummy Limited (www.crashtestdummylimited.com). This is an unofficial
personal tool, not affiliated with Team Rubicon. It reads only what your own logged-in
account can see, at a polite rate (4 page loads a day).

## Files

| Path | Purpose |
|---|---|
| `watcher.py` | The whole app: `login`, `run`, `test` commands. Heavily commented. |
| `config.example.json` | Published template; copy it to `config.json` (personal, git-ignored) and fill it in. |
| `requirements.txt` | Python deps: `playwright`, `certifi`. |
| `README.md`, `LICENSE` | Public-facing docs and MIT license (© Crash Test Dummy Limited). Keep README in sync when behavior changes. |
| `launchd/com.crashtestdummylimited.rubicon-watcher.plist.template` | macOS launchd schedule with a `__PROJECT_DIR__` placeholder. |
| `install.sh` / `uninstall.sh` | Render the template with this folder's path into `~/Library/LaunchAgents` and load it / unload and remove it. |
| `state/` | Git-ignored runtime state (see below). Safe to inspect; don't commit. |
| `.venv/` | Project virtualenv (git-ignored). |

### `config.json`
JSON can't hold comments, so the keys are documented here. `config.json` holds personal
data (your topic and location), so it's git-ignored; never publish it.

- `ntfy_server`: `https://ntfy.sh` (public server; on iOS, instant delivery only works with it).
- `ntfy_topic`: random topic name. Anyone who knows it can read or post to it, so generate your own, e.g.
  `python3 -c "import secrets; print('rubicon-' + secrets.token_hex(8))"`.
- `home_zip`: informational only.
- `home_lat`, `home_lon`: where distances are measured from (decimal degrees; the center of your ZIP is fine).
- `browser_path` (optional): Chromium-based browser executable; `null`/omitted = Playwright's bundled Chromium.
- `max_miles` (optional, not set): an extra distance cap on top of the alert rule, e.g. `500` to drop events with a nationwide (10000 mi) max distance.

### `state/`
- `browser-profile/`: the watcher's own browser profile holding the Roll Call login. Deleting it means you have to run `login` again.
- `seen.json`: event IDs already handled. Delete it to re-seed; the next run sends one "running" push instead of alerts.
- `last_response.json`: raw API payload from the latest run. It contains organizer names and emails, so don't share it.
- `watcher.log`: launchd stdout/stderr, about one line per run.
- `auth_alert_sent`: its modification time throttles "login needed" pushes to once a day.

## How it works (key facts learned while building)

- Find Events is an Angular app. All published events (~200 nationwide) come from one
  call: `https://wa-evtmgmt-webapi-prod-wus.azurewebsites.net/api/event/getPublishedEvents?emApplicationtoken=…`
- Auth is Azure AD B2C via MSAL.js, with tokens in **localStorage**, not cookies. Borrowing
  cookies from an everyday browser profile won't work. The watcher instead drives real
  Chromium-based browser (Playwright `launch_persistent_context`, e.g. Brave) with its own profile and captures the
  JSON the page fetches itself (`page.route` → `route.fetch` → `route.fulfill`).
- The page redirects `/find-events` → `/find-events/` after load, which discards unread
  response bodies. That's why the code intercepts the request instead of using `expect_response`.
- **Alert rule** (a deliberate choice): distance from home ≤ the event's
  `registrationRadiusOptionSet`. The site's own list is *not* filtered this way; it shows
  everything sorted by distance. Events with a 10000 mi max always qualify.
- Event coordinates are in `customFields.vms_latitude/vms_longitude` (the top-level
  `latitude/longitude` are null). `customFields.vms_state` is `{"Id", "Name"}`.
- Event page link: `https://rollcall.teamrubiconusa.org/event/sessions?id=<readableEventId>`.
- Haversine distances match the site's "N miles away" to within about 1 mile.
- Running scripts inside the live Roll Call tab through the Claude in Chrome extension
  tended to hang the renderer (heavy Bing map). Analyze `state/last_response.json`
  offline instead.

## Platform support

| Platform | Status | Changes needed |
|---|---|---|
| **macOS** | ✅ Built and running here (Apple silicon, python.org Python 3.13, Brave). | None. |
| **Windows** | Should work; untested. | Set `browser_path` in `config.json` (or leave it `null` for Playwright's Chromium). Use `.venv\Scripts\python.exe`. Schedule with **Task Scheduler** (trigger every 6 h, action `python.exe watcher.py run`, "Run only when user is logged on"). The launchd plist doesn't apply. |
| **Linux** | Should work; untested. | Set `browser_path` in `config.json` (e.g. `/usr/bin/google-chrome`), or leave it `null`. Schedule with **cron** (`0 */6 * * * /path/.venv/bin/python /path/watcher.py run >> /path/state/watcher.log 2>&1`) or a **systemd user timer**. `login` needs a display (desktop session, `xvfb-run`, or X forwarding); `run` is headless. |

What's portable vs. macOS-specific:
- **Portable:** all of `watcher.py`'s logic (Playwright, `certifi`, `urllib`, `pathlib`), ntfy, and `config.json`/`state/`.
- **macOS-only:** `install.sh`/`uninstall.sh` and the launchd template, and the macOS prompts described below.
- **Browser choice:** `browser_path` in `config.json` accepts any Chromium-based browser executable (Brave, Chrome, Edge, Chromium; example paths are in `watcher.py`). Leave it `null` to use Playwright's bundled Chromium, after running `.venv/bin/playwright install chromium` once. Firefox and Safari aren't supported (the code uses Chromium-only Playwright APIs).
- **Moving to another machine:** run `login` again there rather than copying `state/browser-profile`. Browser profiles may not carry over cleanly between machines or operating systems.

## System setup (from scratch on a Mac)

### 1. Prerequisites
- **macOS** user account that stays logged in. The watcher is a per-user launchd agent and only runs while you're logged in. The Mac can sleep; missed runs happen on wake.
- **Python 3.13 from python.org** at `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`.
  This build doesn't use the macOS keychain for TLS root certificates, so HTTPS fails with
  `CERTIFICATE_VERIFY_FAILED`. The code works around this with `certifi`, so you don't need
  to run Python's "Install Certificates.command". Another Python 3.10+ would also work.
- **A Chromium-based browser.** Set its executable in `config.json` `browser_path`. Brave on
  macOS, for example, is `/Applications/Brave Browser.app/Contents/MacOS/Brave Browser`. With an
  installed browser, `playwright install` isn't needed. With `browser_path` null, run
  `.venv/bin/playwright install chromium` once to download Playwright's own Chromium.
- **ntfy iPhone app**: the official app is "ntfy" by Philipp Heckel. Subscribe to the topic
  in `config.json` on the default `ntfy.sh` server.
- **Network access** to pypi.org (install), rollcall.teamrubiconusa.org,
  *.b2clogin.com, *.azurewebsites.net, and ntfy.sh.

The README has the beginner-friendly version of these steps (ZIP download, Terminal basics,
finding coordinates, TextEdit smart-quote warning). Most people this is shared with have no
coding or git experience, so keep the README's steps the primary path and in sync with this section.

**Folder location:** use the home folder, e.g. `~/rubicon-watcher`. Never use Desktop,
Documents, Downloads or iCloud Drive: macOS privacy protection (TCC) blocks launchd jobs
from reading them, so scheduled runs fail silently. `install.sh` refuses those locations.
The path must also avoid `& # \ < > "`, which `install.sh` also checks.

**Getting the code:** either GitHub's **Code → Download ZIP** (the folder unzips as
`rubicon-watcher-main`; rename it to `rubicon-watcher`), or
`git clone https://github.com/ctd-mh3/rubicon-watcher.git ~/rubicon-watcher`.

### 2. Install
```sh
cd ~/rubicon-watcher
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 3. Configure and verify
```sh
cp config.example.json config.json  # then edit: your own ntfy_topic, home_lat/home_lon
.venv/bin/python watcher.py test    # phone should get "Rubicon watcher test"
.venv/bin/python watcher.py login   # browser window opens: log in, wait for events, close window
.venv/bin/python watcher.py run     # headless; first run seeds seen.json and sends "running" push
```

### 4. Schedule (launchd)
```sh
zsh install.sh      # renders the template, installs to ~/Library/LaunchAgents, loads it (runs once now)
launchctl print gui/$(id -u)/com.crashtestdummylimited.rubicon-watcher | grep -E "state|last exit|run interval"
tail state/watcher.log
```
Docs use `zsh install.sh` rather than `./install.sh` so it works even if a ZIP download
lost the executable bit. `install.sh` checks that `.venv` and `config.json` exist first. Re-run it after editing the
template or moving the project folder (the paths are baked in at install time, because
launchd doesn't expand `~`).

Run a check now: `launchctl kickstart gui/$(id -u)/com.crashtestdummylimited.rubicon-watcher`.
Uninstall: `zsh uninstall.sh`. It leaves `config.json` and `state/` in place.

### 5. Expected macOS prompts
- **"App Background Activity – Software from 'Python Software Foundation' can run in the
  background"**: this is the launchd agent. Leave it enabled. It appears in System Settings →
  General → Login Items & Extensions; switching it off stops the watcher.
- **"Data Access Blocked – 'python3.13' tried to access your data from other apps"**: probably
  the browser (launched by Python) peeking at other apps' data at startup. The watcher doesn't need
  this access and runs fine with it blocked, so leave it blocked. If it repeats every run,
  consider adding browser launch flags (e.g. `--no-first-run`) in `launch()`.

## Maintenance

- **"login needed" push**: the Azure B2C session expired. Run `.venv/bin/python watcher.py login`.
- **ERROR lines in `watcher.log`**: likely Roll Call changed the page or API. Check
  `state/last_response.json` and the field notes in `watcher.py` (`event_list` fails loudly
  on shape changes).
- **Updating to a new version**: `config.json`, `state/` and `.venv/` aren't in the repo, so
  updates never touch them. With git: `git pull`. From a ZIP: copy the new files over the old
  folder (choose Replace). Either way, then run `.venv/bin/pip install -r requirements.txt && zsh install.sh`.
- **Changing home or radius**: edit `config.json`; no reinstall needed. Each run reads it fresh.
- **Changing the schedule**: edit `StartInterval` (seconds) in the template, then re-run `zsh install.sh`.
- Code changes to `watcher.py` take effect on the next run; launchd runs the file directly.
- **Before publishing**: check that `git status` doesn't show `config.json` or `state/`.
  `state/last_response.json` contains other people's names and emails, and `browser-profile/` holds your login session.
