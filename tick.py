"""tick.py - what the ticker does now. Prints one line: 'go <gap_s>' (start the watcher, next tick in gap_s) or
'stop <why>'. Reads windows.json; TEST_WINDOW (start,fast_until,slow_until as HH:MM, today) overrides it for tests,
with TEST_FAST_S and TEST_SLOW_S."""
import datetime, json, os, sys
from zoneinfo import ZoneInfo

w = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "windows.json")))
now = datetime.datetime.now(ZoneInfo(w["timezone"]))
day, hm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
fast, slow = w["fast_s"], w["slow_s"]
d = w["days"].get(day)
if os.environ.get("TEST_WINDOW"):
    s, f, sl = os.environ["TEST_WINDOW"].split(",")
    d = {"start": s, "fast_until": f, "slow_until": sl}
    fast, slow = int(os.environ.get("TEST_FAST_S", 60)), int(os.environ.get("TEST_SLOW_S", 120))
if not d: print(f"stop no race day {day}"); sys.exit()
if hm < d["start"]: print(f"stop before start {d['start']} ({hm})"); sys.exit()
if hm < d["fast_until"]: print(f"go {fast}"); sys.exit()
if hm < d["slow_until"]: print(f"go {slow}"); sys.exit()
print(f"stop after {d['slow_until']} ({hm})")
