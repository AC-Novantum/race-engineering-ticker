# Claude scheduled task for the ticker: ONE watchdog, set once, for every event

Since 11 Nov 2026 nothing is created per event. The morning start tasks are gone: the ticker's own schedule
trigger (tick.yml, `7,37 * * * *`) starts the chain when none is running. The watchdog reads the same list as the
ticker, so it needs no dates.

## Watchdog (one task, kept all year)
- name: `Watcher watchdog`
- cron_expression: `CRON_TZ=Australia/Adelaide 17 6-23 * * *` (hourly; with no event window open it stops after one
  command). A late-night session in another zone: widen the hours.
- cloud task (requires local device off), push and email on
- prompt: the text of `watchdog_prompt.md`, unchanged
- it needs outbound access to visorup.com.au and GitHub

## Test before an event (the night before)
- Ticker: dispatch tick.yml with test_window = a few minutes from now (start,fast_until,slow_until), test_fast_s 60,
  test_slow_s 120, test_event = the event slug. Expect a watcher run per tick, the gap moving to 120 s, then a stop.
- Watchdog: `python3 tick.py --status` shows what it will see. To test the restart, cancel the running tick inside an
  open window, wait 25 minutes and fire the task (fire_trigger, no text). Expect "WATCHER RESTARTED" on Andrew's
  phone and email.

## Old tasks
Sandown 2026 task ids (delete): watchdog trig_01KLxfv3BkC5KPNWBNKt7av9, Sat start trig_01C1isY3BiWHdz8ep4Sdp4i8,
Sun start trig_01BifufjZaTvdb4Mg3A5bRCJ. Key renewal reminder trig_01PUh4Dfq5wntKCiVGb9eJr2 (30 Oct 2027, keep).
