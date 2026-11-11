# race-engineering-ticker

Timer only. Starts the Sportity official-documents watcher (`watcher.yml` in the private repo
AC-Novantum/race-engineering-runner) when an event's document window is open. Holds no data, documents or results.

Built 6 Nov 2026 at Sandown because GitHub's own timer fired only 2 of about 170 watcher slots that Friday.

## How it works (automatic since 11 Nov 2026: nothing is set per event)
1. **The list**: the site publishes when the watcher should run, for every live event at once:
   `https://visorup.com.au/api/public/watch-windows` (public, read-only: event slug, time zone, each day's first
   session start and last session end, docs_until). It comes from the timetable the site already holds.
2. **Each tick**: `tick.py` reads the list and decides per event:
   - every 10 min from 1 h before the first session until 2 h after the last session ends
   - every 30 min for 2 more hours, then nothing until the next day
   - after the event, every 30 min 07:00 to 21:00 event time until docs_until (10:00 Tuesday, event time)
   It starts the watcher once per event that is due, with the event slug as the `event` input (key: secret
   `RUNNER_DISPATCH`), prints which events are open, waits out the gap and starts the next tick. Ten events open
   means ten watcher starts per tick (limit 20; more is cut and the run goes red).
3. **No timetable on the site** for a day of an event: 06:00 to 23:00 event time is used and the run is RED until
   the session times are loaded. Never a silent skip.
4. **Site not read** (2 tries, 10 s): `windows.json`, the hand-set fallback, is used and the log line says
   `source FALLBACK windows.json`. Red when the fallback does not list today either (nothing is known), and red when
   the site lists nothing on a day the fallback lists.
5. **Keep-alive**: tick.yml's own schedule (`7,37 * * * *`) checks that a chain is running and starts one if not.
   A slot that lands while a chain runs exits at once. With no event within 7 days the chain stops and a slot
   starts it again when one appears. No person and no morning task.
6. **Watchdog**: one hourly Claude scheduled task, all year (`scheduled-tasks/`). It asks `tick.py --status` what
   is open and alerts when an open event has had no watcher run for 25 min (fast) or 70 min (slow).
7. **Backup**: the private repo's own cron on `watcher.yml` stays on; when it fires it just adds a run.

A red tick never ends the chain: the next tick is started first, then the run turns red.

Why a separate public repo: waiting inside a GitHub job is billed on private repos. Public repos run free, so the
waiting happens here and the private repo pays only for each watcher run (about 2.4 min each).

## For an event
Nothing here. The event must be on the site with its session times (the site's schedule load), and the private
repo needs its event record (`events/<slug>.json`, same slug as the site). To check: `python3 tick.py --status`.
The night-before test is in `scheduled-tasks/README.md`. Tests: `python3 test_tick.py` (no network).

GitHub turns schedules off in a public repo after 60 days without a commit: the watchdog checks the workflow is
still active and says so.

## The key
`RUNNER_DISPATCH`: fine-grained token "ticker-dispatch", repo race-engineering-runner only, Actions read/write,
expires **6 Nov 2027**. A Claude scheduled task reminds Andrew a week before. To renew: GitHub, Settings,
Developer settings, Personal access tokens, Fine-grained tokens, Generate new token (same settings), then this
repo, Settings, Secrets and variables, Actions, edit RUNNER_DISPATCH, paste.

## Security
The key can start, stop or re-run any workflow on race-engineering-runner and read their logs (that includes the
runner's other workflows, not only the watcher). It can't read or change code, data or the site key. Secrets are
never shown in logs and are not given to forks. Only people with write access here can start the ticker by hand.
The list the ticker reads is public and holds nothing private; what it says is checked (slug, zone, times) before
any of it is used, and none of it is written to this repo.
