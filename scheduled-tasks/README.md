# Claude scheduled tasks for the ticker (create these for EVERY event)

Create them from a Race Engineering chat with the scheduled-task tool (create_trigger). All run in the cloud:
leave "requires local device" off. Notifications: push and email on (Andrew's alarms go by email too).
Times are the circuit's local time zone (Melbourne for Sandown); use the same times as windows.json.

## 1. Morning start: one per race day
- name: `<Event> watcher start <Day>` (e.g. "Sandown watcher start Sat")
- run_once_at: that day's windows.json `start`, e.g. `2026-11-07T07:30:00[Australia/Melbourne]`
- prompt: the text of `start_prompt.md`, unchanged

## 2. Watchdog: one per event
- name: `<Event> watcher watchdog`
- cron_expression: `CRON_TZ=<zone> 17 <first start hour + 1>-<last slow_until hour> <race-day dates> <month> *`
  e.g. Sandown 7-8 Nov: `CRON_TZ=Australia/Melbourne 17 8-21 7-8 11 *`
- prompt: the text of `watchdog_prompt.md`, unchanged (it reads windows.json itself, so it needs no edits)

## 3. Test before the event (the night before)
- Ticker: dispatch tick.yml with test_window = a few minutes from now (start,fast_until,slow_until), test_fast_s 60,
  test_slow_s 120. Expect a watcher run per tick, the gap moving to 120 s, then a stop.
- Watchdog: add a test day for today to windows.json covering the next 15 minutes, make sure no tick is running,
  fire the watchdog task once (fire_trigger). Expect "WATCHER RESTARTED", a new tick run, and the alert on
  Andrew's phone and email. Then remove the test day from windows.json.

## 4. After the event
Disable or delete the event's tasks (they would otherwise sit in the list; the dates in the cron stop them firing).
Sandown 2026 task ids: watchdog trig_01KLxfv3BkC5KPNWBNKt7av9, Sat start trig_01C1isY3BiWHdz8ep4Sdp4i8,
Sun start trig_01BifufjZaTvdb4Mg3A5bRCJ. Key renewal reminder trig_01PUh4Dfq5wntKCiVGb9eJr2 (30 Oct 2027, keep).
