# race-engineering-ticker

Timer only. Starts the Sportity official-documents watcher (`watcher.yml` in the private repo
AC-Novantum/race-engineering-runner) on a race-day timetable. Holds no data, documents or results.

Built 6 Nov 2026 at Sandown because GitHub's own timer fired only 2 of about 170 watcher slots that Friday.

## How it works
1. **Morning start**: a one-off Claude scheduled task (cloud, no PC) starts `tick.yml` here at the day's `start` time.
2. **Each tick**: `tick.py` reads `windows.json` and says go or stop. On go, the tick starts the watcher in the
   private repo (key: secret `RUNNER_DISPATCH`), waits out the gap, then starts the next tick.
   - every 10 min from 1 h before the first session until 2 h after the last session ends (`fast_until`)
   - every 30 min for 2 more hours (`slow_until`), then it stops on its own
3. **Watchdog**: an hourly Claude scheduled task (cloud) during race days. Inside the window, if no tick for
   15 min (40 min in the 30-min phase) it restarts the ticker and alerts Andrew by push and email. If the last 3
   watcher runs failed it alerts too. Outside the window it does nothing.
4. **Backup**: the private repo's own cron on `watcher.yml` stays on; when it fires it just adds a run.

Why a separate public repo: waiting inside a GitHub job is billed on private repos. Public repos run free, so the
waiting happens here and the private repo pays only for each check (about 2 min, about US$0.90 per race day).

## SET UP FOR EVERY EVENT (not automatic yet)
Do all four before the first day of the event. Nothing runs until they are done.
1. **windows.json**: one entry per race day (Melbourne time keys; use the circuit's local time zone if it isn't
   Melbourne and change `timezone`): `start` = first session minus 1 h, `fast_until` = last session's expected end
   plus 2 h, `slow_until` = `fast_until` plus 2 h. Source: the event's schedule in VU-RE shared. Remove old days.
2. **Watcher config** in the private repo (`tools/watcher/watcher_config.example.json`): the event slug, name,
   board URL and dates (this is the watcher's own setup, unchanged by the ticker).
3. **Claude scheduled tasks** (cloud, not local device), one set per event:
   - one-off "watcher start <day>" per race day at that day's `start`, prompt: dispatch `tick.yml` on main here and
     confirm a tick and a watcher run appear; push and email on.
   - "watcher watchdog": hourly at :17 across the race days' hours; push and email on.
   Exact names, schedules and prompts: `scheduled-tasks/README.md`, `start_prompt.md`, `watchdog_prompt.md`.
4. **Test the night before**: dispatch `tick.yml` with `test_window` set to a few minutes from now
   (start,fast_until,slow_until), `test_fast_s` 60, `test_slow_s` 120. Check: a watcher run starts each tick,
   the gap switches to 120 s, the chain stops at slow_until. Then fire the watchdog once with no ticker running
   inside a test window and check it restarts and alerts.

## The key
`RUNNER_DISPATCH`: fine-grained token "ticker-dispatch", repo race-engineering-runner only, Actions read/write,
expires **6 Nov 2027**. A Claude scheduled task reminds Andrew a week before. To renew: GitHub, Settings,
Developer settings, Personal access tokens, Fine-grained tokens, Generate new token (same settings), then this
repo, Settings, Secrets and variables, Actions, edit RUNNER_DISPATCH, paste.

## Security
The key can only start, stop or re-run workflows on race-engineering-runner and read their logs. It can't read or
change code, data or the site key. Secrets are never shown in logs and are not given to forks. Only people with
write access here can start the ticker.
