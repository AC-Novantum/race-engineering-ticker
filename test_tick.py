"""Checks for windows.json and tick.py. Run: python3 test_tick.py (also run by tick.yml before it decides).
Fails when the file is malformed, a window is out of order, or every day in the file is in the past (the fault
found 11 Nov 2026: the file still held only Sandown's two days, so the ticker would have said 'stop no race day'
on every Adelaide day and ended green, with the watchdog silent)."""
import datetime, json, os, re, subprocess, sys
from zoneinfo import ZoneInfo
here = os.path.dirname(os.path.abspath(__file__))
w = json.load(open(os.path.join(here, "windows.json")))
tz = ZoneInfo(w["timezone"]); today = datetime.datetime.now(tz).strftime("%Y-%m-%d")
errs = []
hm = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
for day, d in w["days"].items():
    try: datetime.date.fromisoformat(day)
    except ValueError: errs.append(f"{day}: not a date")
    for k in ("start", "fast_until", "slow_until"):
        if not hm.match(d.get(k, "")): errs.append(f"{day}: {k} is not HH:MM")
    if not errs and not (d["start"] < d["fast_until"] <= d["slow_until"]): errs.append(f"{day}: start < fast_until <= slow_until does not hold (a window cannot pass midnight)")
if not w["days"]: errs.append("no days")
elif max(w["days"]) < today and not os.environ.get("ALLOW_PAST"): errs.append(f"every day in windows.json is in the past (newest {max(w['days'])}, today {today}): set the next event's days")
def run(day_hm):
    # tick.py with a fixed clock, via a tiny shim
    code = ("import datetime as _d, runpy, sys\n"
            f"_fixed=_d.datetime.fromisoformat('{day_hm}')\n"
            "class D(_d.datetime):\n    @classmethod\n    def now(cls, tz=None): return _fixed.replace(tzinfo=tz)\n"
            "_d.datetime=D\nrunpy.run_path(sys.argv[1], run_name='__main__')\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("TEST_")}
    return subprocess.run([sys.executable, "-c", code, os.path.join(here, "tick.py")], capture_output=True, text=True, env=env).stdout.strip()
for day, d in w["days"].items():
    if errs: break
    got = run(f"{day}T{d['start']}:00")
    if got != f"go {w['fast_s']}": errs.append(f"{day} at start: expected go {w['fast_s']}, got {got!r}")
    got = run(f"{day}T{d['slow_until']}:00")
    if not got.startswith("stop after"): errs.append(f"{day} at slow_until: expected stop, got {got!r}")
if errs: print("\n".join("FAIL " + e for e in errs)); sys.exit(1)
print(f"ok {len(w['days'])} days, time zone {w['timezone']}")
