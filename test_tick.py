"""Checks for tick.py, tick.yml and windows.json. Run: python3 test_tick.py (check.yml runs it on every change).
No network: the site's answer, the clock and GitHub are fakes."""
import datetime, json, os, re, sys, tempfile, urllib.error
import tick
UTC = datetime.timezone.utc
here = os.path.dirname(os.path.abspath(__file__))
T = lambda s: datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
fails, count = [], 0
def check(name, got, want=True):
    global count; count += 1
    if got != want: fails.append(f"{name}: got {got!r}, want {want!r}")
def day(date, first=None, last=None):
    return {"date": date, "first_start": first, "last_end": last, "no-timetable": first is None}
def ev(slug, tz, days, docs_until):
    return {"event": slug, "timezone": tz, "days": days, "docs_until": docs_until, "no-timetable": all(d["no-timetable"] for d in days)}
def site(now, events):
    return json.dumps({"ok": True, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "events": events})
def run(now, events, fb=None, last_tick=None):
    return tick.decide(T(now), tick.parse_site(site(T(now), events), T(now)), None, fb, None, T(last_tick) if last_tick else None)
def modes(r): return {o["event"]: o["mode"] for o in r["open"]}
def post_ok():
    calls = []
    def post(path, body): calls.append((path, body)); return 204
    return calls, post

# Adelaide is UTC+10:30 and Perth UTC+8 in late November
ADE = ev("2026-adelaide", "Australia/Adelaide", [
    day("2026-11-26", "2026-11-25T22:30:00Z", "2026-11-26T07:30:00Z"),      # Thu 09:00 to 18:00
    day("2026-11-27", "2026-11-26T22:30:00Z", "2026-11-27T14:00:00Z"),      # Fri 09:00 to Sat 00:30 (past midnight)
    day("2026-11-28", "2026-11-27T23:30:00Z", "2026-11-28T07:30:00Z"),
    day("2026-11-29", "2026-11-28T23:30:00Z", "2026-11-29T07:00:00Z")], "2026-11-30T23:30:00Z")
PER = ev("2026-perth", "Australia/Perth", [day("2026-11-26", "2026-11-26T02:00:00Z", "2026-11-26T09:00:00Z")], "2026-12-01T02:00:00Z")
FB = tick.load_fallback()

# 1. the rule, one event: 1 h before the first session, 2 h after the last end, 2 h slow, then off
check("before the window", run("2026-11-25T21:29:00Z", [ADE])["action"], "idle")
check("idle wakes at the opening", run("2026-11-25T21:20:00Z", [ADE])["gap"], 600)
check("idle is at most 30 min", run("2026-11-25T12:00:00Z", [ADE])["gap"], 1800)
r = run("2026-11-25T21:30:00Z", [ADE]); check("opens 1 h before", (r["action"], r["gap"], modes(r)), ("go", 600, {"2026-adelaide": "fast"}))
check("fast to last end + 2 h", modes(run("2026-11-26T09:29:00Z", [ADE])), {"2026-adelaide": "fast"})
r = run("2026-11-26T09:30:00Z", [ADE]); check("then slow", (r["action"], r["gap"], modes(r)), ("go", 1800, {"2026-adelaide": "slow"}))
check("slow for 2 h", modes(run("2026-11-26T11:29:00Z", [ADE])), {"2026-adelaide": "slow"})
check("then off", run("2026-11-26T11:30:00Z", [ADE])["action"], "idle")

# 2. midnight crossing: Friday's last session ends Sat 00:30 Adelaide; fast to 02:30, slow to 04:30
check("past midnight fast", modes(run("2026-11-27T15:59:00Z", [ADE])), {"2026-adelaide": "fast"})
check("past midnight slow", modes(run("2026-11-27T16:00:00Z", [ADE])), {"2026-adelaide": "slow"})
check("past midnight off", modes(run("2026-11-27T18:00:00Z", [ADE])), {})

# 3. two events at once in different zones: one start each, each with its own slug
r = run("2026-11-26T03:00:00Z", [ADE, PER]); check("two open", modes(r), {"2026-adelaide": "fast", "2026-perth": "fast"})
calls, post = post_ok(); lines, failed = tick.dispatch(r["due"], post)
check("two starts", [c[1]["inputs"]["event"] for c in calls], ["2026-adelaide", "2026-perth"])
check("start address", calls[0][0], "repos/AC-Novantum/race-engineering-runner/actions/workflows/watcher.yml/dispatches")
check("each start logged", lines, ["watcher started for 2026-adelaide", "watcher started for 2026-perth"])
# one fast, one slow: the slow one only once per 30 min slot
r = run("2026-11-26T09:40:00Z", [ADE, PER], last_tick="2026-11-26T09:30:00Z")
check("slow not due inside the slot", ([o["event"] for o in r["due"]], r["gap"]), (["2026-perth"], 600))
r = run("2026-11-26T10:00:10Z", [ADE, PER], last_tick="2026-11-26T09:50:10Z")
check("slow due in a new slot", [o["event"] for o in r["due"]], ["2026-perth", "2026-adelaide"])
check("first tick of a chain starts slow ones", len(run("2026-11-26T09:40:00Z", [ADE, PER])["due"]), 2)

# 4. documents watch after the event: every 30 min 07:00 to 21:00 event time to docs_until (Tue 10:00), then stop
check("Mon 06:59 off", modes(run("2026-11-29T20:29:00Z", [ADE])), {})
r = run("2026-11-29T20:30:00Z", [ADE]); check("Mon 07:00 slow", (modes(r), r["gap"]), ({"2026-adelaide": "slow"}, 1800))
check("Mon 20:59 slow", modes(run("2026-11-30T10:29:00Z", [ADE])), {"2026-adelaide": "slow"})
check("Mon 21:00 off", modes(run("2026-11-30T10:30:00Z", [ADE])), {})
check("Tue 09:59 slow", modes(run("2026-11-30T23:29:00Z", [ADE])), {"2026-adelaide": "slow"})
check("Tue 10:00 over", modes(run("2026-11-30T23:30:00Z", [ADE])), {})
r = run("2026-12-02T00:00:00Z", []); check("nothing listed: stop", (r["action"], r["gap"], r["alarms"]), ("stop", 0, []))

# 5. no timetable: wide default 06:00 to 23:00 event time and the run is red; on the days the clocks change too.
# 4 Oct 2026 daylight time starts (Melbourne UTC+11, Adelaide UTC+10:30 from 02:00); 5 Apr 2026 it ends.
for tz, open_utc, slow_utc, off_utc in (("Australia/Melbourne", "2026-10-03T19:00:00Z", "2026-10-04T10:00:00Z", "2026-10-04T12:00:00Z"),
                                        ("Australia/Adelaide", "2026-10-03T19:30:00Z", "2026-10-04T10:30:00Z", "2026-10-04T12:30:00Z")):
    e = ev("2026-dst", tz, [day("2026-10-03"), day("2026-10-04")], "2026-10-05T23:00:00Z" if "Melb" in tz else "2026-10-05T23:30:00Z")
    one = datetime.timedelta(minutes=1); f = lambda t: modes(tick.decide(t, tick.parse_site(site(t, [e]), t)))
    check(f"{tz} DST day 05:59", f(T(open_utc) - one), {})
    check(f"{tz} DST day 06:00", f(T(open_utc)), {"2026-dst": "fast"})
    check(f"{tz} DST day 21:00", f(T(slow_utc)), {"2026-dst": "slow"})
    check(f"{tz} DST day 23:00", f(T(off_utc)), {})
    r = run(open_utc, [e]); check(f"{tz} no timetable is red", (len(r["alarms"]) >= 1, "NO TIMETABLE" in r["alarms"][0], r["action"]), (True, True, "go"))
    std = "2026-10-02T20:00:00Z" if "Melb" in tz else "2026-10-02T20:30:00Z"     # 06:00 the day before, standard time
    check(f"{tz} day before 06:00", (f(T(std) - one), f(T(std))), ({}, {"2026-dst": "fast"}))
for tz, seven, du in (("Australia/Melbourne", "2026-04-04T21:00:00Z", "2026-04-07T00:00:00Z"), ("Australia/Adelaide", "2026-04-04T21:30:00Z", "2026-04-07T00:30:00Z")):
    e = ev("2026-apr", tz, [day("2026-04-04", "2026-04-03T23:00:00Z", "2026-04-04T05:00:00Z")], du)   # docs watch Sun 5 Apr, clocks back
    f = lambda t: modes(tick.decide(t, tick.parse_site(site(t, [e]), t)))
    check(f"{tz} clocks-back day 06:59", f(T(seven) - datetime.timedelta(minutes=1)), {})
    check(f"{tz} clocks-back day 07:00", f(T(seven)), {"2026-apr": "slow"})
    check(f"{tz} clocks-back day 21:00", f(T(seven) + datetime.timedelta(hours=14)), {})
NT = ev("2026-notimes", "Australia/Adelaide", [day("2026-11-26"), day("2026-11-27")], "2026-11-30T23:30:00Z")
r = run("2026-11-20T00:00:00Z", [NT]); check("no timetable 6 days out: warned, not red", (len(r["warns"]), r["alarms"]), (2, []))
r = run("2026-11-25T00:00:00Z", [NT]); check("no timetable the day before: red", len(r["alarms"]), 1)
mixed = ev("2026-adelaide", "Australia/Adelaide", [ADE["days"][0], day("2026-11-27")], "2026-11-30T23:30:00Z")
r = run("2026-11-27T02:00:00Z", [mixed]); check("one day without times: that day wide, red", (modes(r), len(r["alarms"])), ({"2026-adelaide": "fast"}, 1))

# 6. the owner's case: ten events at once = ten starts per tick, each logged; more than the limit is cut and red
ten = [ev(f"2026-event-{i:02d}", "Australia/Adelaide", ADE["days"][:1], "2026-11-30T23:30:00Z") for i in range(10)]
r = run("2026-11-26T03:00:00Z", ten); calls, post = post_ok(); lines, failed = tick.dispatch(r["due"], post)
check("ten open", (r["action"], len(r["due"]), r["alarms"]), ("go", 10, []))
check("ten starts, one per event", sorted(c[1]["inputs"]["event"] for c in calls), [e["event"] for e in ten])
check("ten log lines", (len(lines), failed, sum("open 2026-event-" in l for l in r["lines"])), (10, [], 10))
many = [ev(f"2026-event-{i:02d}", "Australia/Adelaide", ADE["days"][:1], "2026-11-30T23:30:00Z") for i in range(25)]
r = run("2026-11-26T03:00:00Z", many); calls, post = post_ok(); tick.dispatch(r["due"], post)
check("bounded", (len(calls), len(r["alarms"]), "2026-event-24" in r["alarms"][0]), (tick.MAX_EVENTS, 1, True))

# 7. site down or garbage
now = T("2026-11-26T03:00:00Z")                                               # Thu 13:30 Adelaide, a day windows.json lists
r = tick.decide(now, None, "HTTP 503", FB, None)
check("site down, fallback lists today: go by it, said in the log", (r["action"], modes(r), r["alarms"], r["lines"][0]),
      ("go", {"2026-adelaide": "fast"}, [], "source FALLBACK windows.json (site: HTTP 503)"))
r = tick.decide(T("2026-11-20T03:00:00Z"), None, "HTTP 503", FB, None)
check("site down, today not in the fallback: red, look again in 10 min", (r["action"], r["gap"], len(r["alarms"])), ("idle", 600, 1))
r = tick.decide(now, None, "URLError: timed out", None, "ValueError: bad file")
check("site down, no fallback: red", (r["action"], len(r["alarms"]), r["due"]), ("idle", 1, []))
r = tick.decide(now, [], None, FB, None)
check("site lists nothing on a day the fallback lists: go by the fallback, red", (r["action"], modes(r), len(r["alarms"])), ("go", {"2026-adelaide": "fast"}, 1))
r = run("2026-11-26T03:00:00Z", [ADE], fb=FB); check("site and fallback agree: the site, no alarm", (r["alarms"], r["source"]), ([], "site (1 event listed)"))
def bad(text, t=now):
    try: tick.parse_site(text, t); return False
    except Exception: return True
check("html is garbage", bad("<html>503</html>"))
check("ok false is garbage", bad('{"ok": false, "error": "not-configured"}'))
check("stale is garbage", bad(site(T("2026-11-26T01:00:00Z"), [ADE])))
check("a slug with shell characters is garbage", bad(site(now, [dict(ADE, event="x; rm -rf $HOME")])))
check("a bad zone is garbage", bad(site(now, [dict(ADE, timezone="Mars/Olympus")])))
check("times out of order are garbage", bad(site(now, [ev("2026-x", "Australia/Adelaide", [day("2026-11-26", "2026-11-26T07:00:00Z", "2026-11-26T01:00:00Z")], "2026-11-30T23:30:00Z")])))
check("the same event twice is garbage", bad(site(now, [ADE, ADE])))
# fetch: 2 tries, 10 s each, https only; read_all turns a dead site into the fallback
tries = []
def dead(req, timeout): tries.append(timeout); raise urllib.error.URLError("timed out")
site_, err, fb, fb_err = tick.read_all(now, "https://example.invalid/x", dead, sleep=lambda s: None)
check("2 tries of 10 s", tries, [10, 10]); check("dead site", (site_, "timed out" in err, fb is not None), (None, True, True))
def e500(req, timeout): raise urllib.error.HTTPError(req.full_url, 500, "x", {}, None)
check("HTTP 500", tick.read_all(now, "https://example.invalid/x", e500, sleep=lambda s: None)[1], "HTTP 500")
check("http refused", tick.read_all(now, "http://example.invalid/x", dead)[1], "address is not https")
class Good:
    status = 200
    def __init__(s, t): s.t = t
    def __enter__(s): return s
    def __exit__(s, *a): return False
    def read(s, n): return s.t.encode()
got = tick.read_all(now, "https://example.invalid/x", lambda req, timeout: Good(site(now, [ADE, PER])))
check("good answer read", ([e["event"] for e in got[0]], got[1]), (["2026-adelaide", "2026-perth"], None))
with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
    f.write("{not json"); f.flush()
    check("broken fallback file reported", tick.read_all(now, "https://example.invalid/x", dead, f.name, sleep=lambda s: None)[3] is not None)

# 8. starting the watcher: one failure does not stop the others; a refused input (422) is red, never a blind start
seq = iter([500, 500, 500, 204])
lines, failed = tick.dispatch([{"event": "2026-a"}, {"event": "2026-b"}], lambda p, b: next(seq), sleep=lambda s: None)
check("one fails, the other starts", (failed, lines[1]), (["2026-a"], "watcher started for 2026-b"))
bodies = []
def old_watcher(p, b): bodies.append(b); return 422 if "inputs" in b else 204
lines, failed = tick.dispatch([{"event": "2026-a"}], old_watcher)
check("422 with one event: red, no start without the input", (failed, [b for b in bodies if "inputs" not in b], "COULD NOT START" in lines[0]), (["2026-a"], [], True))
lines, failed = tick.dispatch([{"event": "2026-a"}, {"event": "2026-b"}], old_watcher)
check("422 with two events: red, never one blind start for two", failed, ["2026-a", "2026-b"])
calls, post = post_ok(); tick.dispatch([{"event": ""}], post); check("fallback with no slug: no input", calls[0][1], {"ref": "main"})

# 9. keep-alive (the schedule trigger): exits at once when a chain is running, starts one when none is
runs = lambda *r: (lambda path: {"workflow_runs": [dict(zip(("id", "event", "status", "created_at"), x)) for x in r]})
calls, post = post_ok()
line = tick.keepalive(runs((5, "schedule", "in_progress", "t"), (4, "workflow_dispatch", "in_progress", "t0"), (3, "workflow_dispatch", "completed", "t")), post, 5, "o/r", "main")
check("chain running: nothing started", (calls, line.startswith("chain already running (run 4")), ([], True))
line = tick.keepalive(runs((7, "workflow_dispatch", "queued", "t")), post, 9, "o/r", "main"); check("a queued tick counts", calls, [])
line = tick.keepalive(runs((5, "schedule", "in_progress", "t"), (6, "schedule", "queued", "t"), (3, "workflow_dispatch", "completed", "t")), post, 5, "o/r", "main")
check("no chain: one started", (calls, line), ([("repos/o/r/actions/workflows/tick.yml/dispatches", {"ref": "main"})], "no chain running: started one"))
try: tick.keepalive(runs(), lambda p, b: 403, 1, "o/r", "main"); check("start refused is red", False)
except SystemExit as e: check("start refused is red", "COULD NOT START" in str(e))

# 10. the workflow file and the repo: schedule trigger, one chain, no secret but the dispatch key, nothing written
y = open(os.path.join(here, ".github/workflows/tick.yml")).read()
check("schedule trigger", len(re.findall(r"^\s+- cron: ", y, re.M)) >= 1 and "schedule:" in y)
check("keep-alive job outside the chain's group", bool(re.search(r"keepalive:\n\s+if: github.event_name == 'schedule'\n(?:(?!concurrency).)*?\n  tick:", y, re.S)))
check("chain job in one group, never cancelled", bool(re.search(r"tick:\n\s+if: github.event_name == 'workflow_dispatch'.*?concurrency:\n(?:\s+#.*\n)*\s+group: tick-\$\{\{ inputs.test_window != '' && 'test' \|\| 'chain' \}\}\n\s+cancel-in-progress: false", y, re.S)))
check("a test run never shares the live chain's group", "group: tick\n" not in y and "'test' || 'chain'" in y)
check("only the dispatch key", sorted(set(re.findall(r"secrets\.([A-Za-z_]+)", y))), ["RUNNER_DISPATCH"])
check("read-only checkout", "contents: read" in y and "contents: write" not in y)
check("no input pasted into a shell line", re.findall(r"^\s+(?:gh|python3|echo|wait|for|sleep) .*\$\{\{", y, re.M), [])
src = open(os.path.join(here, "tick.py")).read()
check("tick.py writes only the workflow output file", re.findall(r"open\([^)]*[\"'][wa][\"']", src), ['open(os.environ["GITHUB_OUTPUT"], "a"'])
check("default address is the production site", tick.DEFAULT_URL, "https://visorup.com.au/api/public/watch-windows")

# 11. windows.json (the fallback): well formed; all days past is a note, not a failure (the site's list is the source)
check("fallback event slug", FB["event"], "2026-adelaide")
if max(FB["days"]) < datetime.datetime.now(FB["tz"]).strftime("%Y-%m-%d"): print(f"note: every day in windows.json is past (newest {max(FB['days'])}); the fallback covers no coming event")

if fails: print("\n".join("FAIL " + f for f in fails)); sys.exit(1)
print(f"ok {count} checks")
