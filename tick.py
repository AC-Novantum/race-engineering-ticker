"""tick.py - decides, per event, whether the official-documents watcher runs now, and starts it.

Source of truth: the site's public list (WATCH_WINDOWS_URL, default the production address), which gives every live
event's time zone, each day's first session start and last session end, and docs_until. No per-event setting here.
Rule (Andrew 6 Nov 2026): every 10 min from 1 h before the first session to 2 h after the last session ends, then
every 30 min for 2 h, then stop; after the event, every 30 min 07:00 to 21:00 event time until docs_until.
A day with no session times on the site: 06:00 to 21:00 fast, to 23:00 slow, event time, and the run goes red.
Fallback: windows.json (hand-set days), used when the site cannot be read or lists nothing on a day that file lists.

  python3 tick.py            decide and print (changes nothing)
  python3 tick.py --run      decide, start the watcher once per event that is due, write the workflow outputs
  python3 tick.py --status   one JSON line for the watchdog (changes nothing)
  python3 tick.py --keepalive   schedule trigger: exit at once when a chain is running, else start one

Nothing read from the site is written to the repo. The only secret is the existing dispatch key (env RUNNER_DISPATCH)."""
import datetime, json, os, re, sys, time, urllib.error, urllib.request
from zoneinfo import ZoneInfo

UTC = datetime.timezone.utc
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_URL = "https://visorup.com.au/api/public/watch-windows"
RUNNER = "AC-Novantum/race-engineering-runner"
FAST_S, SLOW_S = 600, 1800
IDLE_MAX_S, MIN_GAP_S = 1800, 60
MAX_EVENTS = 20            # most watcher starts in one tick; more than this is cut and the run goes red
STALE_S = 1800             # a site answer older than this is not believed
SLUG = re.compile(r"^[a-z0-9-]{2,80}$")
HM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
H = datetime.timedelta(hours=1)


def _iso(s):
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", s): raise ValueError(f"not a UTC time: {s!r}")
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _local(day, hour, tz):
    return datetime.datetime(day.year, day.month, day.day, hour, tzinfo=tz).astimezone(UTC)


def parse_site(text, now):
    """The site's answer as a checked list of events. ValueError on anything unexpected (the caller falls back)."""
    j = json.loads(text)
    if not isinstance(j, dict) or j.get("ok") is not True or not isinstance(j.get("events"), list): raise ValueError("not the watch-windows list")
    if abs((now - _iso(j.get("generated_at"))).total_seconds()) > STALE_S: raise ValueError(f"stale answer ({j.get('generated_at')})")
    if len(j["events"]) > 200: raise ValueError("more than 200 events")
    out = []
    for e in j["events"]:
        if not isinstance(e, dict) or not isinstance(e.get("event"), str) or not SLUG.match(e["event"]): raise ValueError("bad event slug")
        slug = e["event"]
        try: tz = ZoneInfo(e.get("timezone"))
        except Exception: raise ValueError(f"{slug}: bad time zone")
        days = e.get("days")
        if not isinstance(days, list) or not 1 <= len(days) <= 31: raise ValueError(f"{slug}: bad days")
        ds = []
        for d in days:
            day = datetime.date.fromisoformat(d["date"])
            if d.get("no-timetable") is True: ds.append({"date": day, "no-timetable": True})
            elif d.get("no-timetable") is False:
                fs, le = _iso(d.get("first_start")), _iso(d.get("last_end"))
                if not fs <= le <= fs + 36 * H: raise ValueError(f"{slug} {day}: first start and last end out of order")
                ds.append({"date": day, "no-timetable": False, "first_start": fs, "last_end": le})
            else: raise ValueError(f"{slug} {day}: no-timetable missing")
        du = _iso(e.get("docs_until"))
        last = max(d["date"] for d in ds)
        if not _local(last, 0, tz) <= du <= _local(last, 0, tz) + 15 * 24 * H: raise ValueError(f"{slug}: docs_until out of range")
        out.append({"event": slug, "timezone": e["timezone"], "tz": tz, "days": ds, "docs_until": du})
    if len({e["event"] for e in out}) != len(out): raise ValueError("an event is listed twice")
    return out


def intervals(ev):
    """[(start, end, mode, why)] in UTC for one event from the site."""
    tz, out = ev["tz"], []
    for d in ev["days"]:
        if d["no-timetable"]:
            a, b, c = _local(d["date"], 6, tz), _local(d["date"], 21, tz), _local(d["date"], 23, tz)
            out += [(a, b, "fast", "NO TIMETABLE, wide default 06:00 to 21:00"), (b, c, "slow", "NO TIMETABLE, wide default 21:00 to 23:00")]
        else:
            a, b = d["first_start"] - H, d["last_end"] + 2 * H
            span = f"first session {d['first_start'].astimezone(tz):%H:%M}, last end {d['last_end'].astimezone(tz):%a %H:%M}"
            out += [(a, b, "fast", span), (b, b + 2 * H, "slow", span + ", last 2 h")]
    day = max(d["date"] for d in ev["days"]) + datetime.timedelta(days=1)
    for _ in range(16):
        a = _local(day, 7, tz)
        if a >= ev["docs_until"]: break
        out.append((a, min(_local(day, 21, tz), ev["docs_until"]), "slow", f"documents watch to {ev['docs_until'].astimezone(tz):%a %d %b %H:%M}"))
        day += datetime.timedelta(days=1)
    return out


def state(ivs, now):
    """(mode, why, next_start): fast beats slow; next_start is the next interval start after now, or None."""
    mode, why = "off", ""
    for a, b, m, w in ivs:
        if a <= now < b and (mode == "off" or (m == "fast" and mode == "slow")): mode, why = m, w
    nxt = min((a for a, _, _, _ in ivs if a > now), default=None)
    return mode, why, nxt


def load_fallback(path=None):
    """windows.json checked. ValueError when it cannot be used."""
    w = json.load(open(path or os.path.join(HERE, "windows.json")))
    tz = ZoneInfo(w["timezone"])
    ev = w.get("event", "")
    if ev and not SLUG.match(ev): raise ValueError("windows.json: bad event slug")
    for day, d in w["days"].items():
        datetime.date.fromisoformat(day)
        for k in ("start", "fast_until", "slow_until"):
            if not HM.match(d.get(k, "")): raise ValueError(f"windows.json {day}: {k} is not HH:MM")
        if not d["start"] < d["fast_until"] <= d["slow_until"]: raise ValueError(f"windows.json {day}: start < fast_until <= slow_until does not hold")
    return {"event": ev, "timezone": w["timezone"], "tz": tz, "days": w["days"]}


def fallback_intervals(fb):
    out = []
    for day, d in fb["days"].items():
        dt = datetime.date.fromisoformat(day)
        t = lambda hm: datetime.datetime(dt.year, dt.month, dt.day, int(hm[:2]), int(hm[3:]), tzinfo=fb["tz"]).astimezone(UTC)
        out += [(t(d["start"]), t(d["fast_until"]), "fast", f"windows.json {day}"), (t(d["fast_until"]), t(d["slow_until"]), "slow", f"windows.json {day}")]
    return out


def decide(now, site=None, site_err=None, fb=None, fb_err=None, last_tick=None):
    """What this tick does. site: parse_site() result or None with site_err. fb: load_fallback() result or None with
    fb_err. last_tick: when the tick before this one in the chain ran (None for the first of a chain).
    Returns {action: go|idle|stop, gap, source, due: [...], open: [...], alarms: [...], warns: [...], lines: [...]}."""
    alarms, warns, lines, opn, nexts = [], [], [], [], []
    fb_today = bool(fb) and now.astimezone(fb["tz"]).strftime("%Y-%m-%d") in fb["days"]

    def use_fallback():
        mode, why, nxt = state(fallback_intervals(fb), now)
        if nxt: nexts.append(nxt)
        if mode != "off": opn.append({"event": fb["event"], "mode": mode, "why": why})

    if site is not None:
        source = f"site ({len(site)} event{'s' if len(site) != 1 else ''} listed)"
        site_today = False
        for ev in site:
            tz = ev["tz"]; today = now.astimezone(tz).date()
            if min(d["date"] for d in ev["days"]) <= today <= ev["docs_until"].astimezone(tz).date(): site_today = True
            mode, why, nxt = state(intervals(ev), now)
            if nxt: nexts.append(nxt)
            if mode != "off": opn.append({"event": ev["event"], "mode": mode, "why": f"{why} {ev['timezone']}"})
            for d in ev["days"]:
                if not d["no-timetable"] or _local(d["date"], 23, tz) <= now: continue
                msg = f"NO TIMETABLE on the site for {ev['event']} {d['date']}: wide default 06:00 to 23:00 {ev['timezone']} used; load the session times"
                (alarms if _local(d["date"], 6, tz) - 24 * H <= now else warns).append(msg)
        if fb_err: warns.append(f"fallback windows.json cannot be used ({fb_err})")
        if fb_today and not site_today:
            alarms.append("the site lists no event today but windows.json lists today: going by windows.json; load the event on the site")
            source += " + FALLBACK windows.json for today"
            use_fallback()
    else:
        source = f"FALLBACK windows.json (site: {site_err})"
        if fb is None:
            alarms.append(f"SITE NOT READ ({site_err}) and windows.json cannot be used ({fb_err}): nothing known")
        elif fb_today:
            warns.append(f"site not read ({site_err}): going by windows.json")
            use_fallback()
        else:
            alarms.append(f"SITE NOT READ ({site_err}) and windows.json does not list today: cannot know whether an event is on")
    lines.append(f"source {source}")

    opn.sort(key=lambda o: (o["mode"] != "fast", o["event"]))
    slot_new = last_tick is None or int(now.timestamp()) // SLOW_S != int(last_tick.timestamp()) // SLOW_S
    any_fast = any(o["mode"] == "fast" for o in opn)
    due = [o for o in opn if o["mode"] == "fast" or slot_new]   # slow: once per 30 min slot, however often the chain ticks
    for o in opn:
        lines.append(f"open {o['event'] or '(event not named)'} {o['mode']}{'' if o in due else ' (not due this tick)'}: {o['why']}")
    if len(due) > MAX_EVENTS:
        alarms.append(f"{len(due)} events are due, more than the limit of {MAX_EVENTS} starts per tick: not started: {', '.join(o['event'] for o in due[MAX_EVENTS:])}")
        due = due[:MAX_EVENTS]

    to_next = min(((n - now).total_seconds() for n in nexts), default=None)
    if opn:
        action, gap = ("go" if due else "idle"), (FAST_S if any_fast else SLOW_S)
    elif site is not None and not site and not fb_today:
        action, gap = "stop", 0          # nothing within 7 days: the chain ends, the schedule trigger restarts it
    else:
        action, gap = "idle", (FAST_S if site is None else IDLE_MAX_S)   # site not read: look again in 10 min
    if action != "stop" and to_next is not None: gap = min(gap, to_next)
    gap = 0 if action == "stop" else int(max(MIN_GAP_S, gap))
    lines.append({"go": f"go: {len(due)} watcher start{'s' if len(due) != 1 else ''}, next tick in {gap} s",
                  "idle": f"idle: no window open now, next tick in {gap} s",
                  "stop": "stop: the site lists no event within 7 days; the schedule trigger starts the chain again"}[action])
    return {"action": action, "gap": gap, "source": source, "due": due, "open": opn, "alarms": alarms, "warns": warns, "lines": lines}


def fetch(url, opener=None, tries=2, timeout=10, sleep=time.sleep):
    """The site's answer as text, or raises RuntimeError with a short reason. 2 tries, 10 s each."""
    if not url.startswith("https://"): raise RuntimeError("address is not https")
    opener = opener or urllib.request.urlopen
    why = "no answer"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": "race-engineering-ticker"})
            with opener(req, timeout=timeout) as r:
                if getattr(r, "status", 200) != 200: raise RuntimeError(f"HTTP {r.status}")
                return r.read(1_000_000).decode("utf-8")
        except urllib.error.HTTPError as e: why = f"HTTP {e.code}"
        except Exception as e: why = f"{type(e).__name__}: {str(e)[:80]}"
        if i + 1 < tries: sleep(3)
    raise RuntimeError(why)


def read_all(now, url=None, opener=None, fallback_path=None, sleep=time.sleep):
    site = site_err = fb = fb_err = None
    try: site = parse_site(fetch(url or os.environ.get("WATCH_WINDOWS_URL") or DEFAULT_URL, opener, sleep=sleep), now)
    except Exception as e: site_err = f"{type(e).__name__}: {str(e)[:120]}" if not isinstance(e, RuntimeError) else str(e)
    try: fb = load_fallback(fallback_path)
    except Exception as e: fb_err = f"{type(e).__name__}: {str(e)[:120]}"
    return site, site_err, fb, fb_err


def _github_post(path, body, token):
    req = urllib.request.Request("https://api.github.com/" + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"authorization": "Bearer " + token, "accept": "application/vnd.github+json", "user-agent": "race-engineering-ticker"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return r.status
    except urllib.error.HTTPError as e: return e.code
    except Exception: return 0


def dispatch(due, post, ref="main", tries=3, sleep=time.sleep):
    """Start watcher.yml once per due event, with the event slug as the `event` input. Returns (lines, failures).
    post(path, body) -> HTTP status. One event failing does not stop the others. HTTP 422 (the watcher refused the
    input) is a failure and the run goes red: a start without the event input could watch the wrong event."""
    lines, failed = [], []
    path = f"repos/{RUNNER}/actions/workflows/watcher.yml/dispatches"
    for o in due[:MAX_EVENTS]:
        name = o["event"] or "(event not named)"
        body = {"ref": ref, "inputs": {"event": o["event"]}} if o["event"] else {"ref": ref}
        st = 0
        for i in range(tries):
            st = post(path, body)
            if st == 204 or st == 422: break
            if i + 1 < tries: sleep(10)
        if st == 204: lines.append(f"watcher started for {name}")
        else: failed.append(name); lines.append(f"COULD NOT START THE WATCHER for {name} (HTTP {st})")
    return lines, failed


ACTIVE = ("queued", "in_progress", "pending", "waiting", "requested")


def chain_running(runs, self_id):
    """The tick runs that make a chain right now: started by dispatch (not by the schedule) and not finished."""
    return [r for r in runs if r.get("event") == "workflow_dispatch" and r.get("status") in ACTIVE and str(r.get("id")) != str(self_id)]


def keepalive(get, post, self_id, repo, ref):
    """The schedule trigger. Exits at once when a chain is running; otherwise starts one. Returns the log line."""
    live = chain_running(get(f"repos/{repo}/actions/workflows/tick.yml/runs?per_page=30").get("workflow_runs", []), self_id)
    if live: return f"chain already running (run {live[0].get('id')}, {live[0].get('status')} since {live[0].get('created_at')}): nothing to do"
    st = post(f"repos/{repo}/actions/workflows/tick.yml/dispatches", {"ref": ref})
    if st != 204: raise SystemExit(f"NO CHAIN RUNNING AND COULD NOT START ONE (HTTP {st})")
    return "no chain running: started one"


def _test_window(now):
    """TEST_WINDOW=start,fast_until,slow_until (HH:MM today in the windows.json zone): the night-before test."""
    s, f, sl = os.environ["TEST_WINDOW"].split(",")
    w = json.load(open(os.path.join(HERE, "windows.json"))); tz = ZoneInfo(w["timezone"])
    fb = {"event": os.environ.get("TEST_EVENT", ""), "timezone": w["timezone"], "tz": tz,
          "days": {now.astimezone(tz).strftime("%Y-%m-%d"): {"start": s, "fast_until": f, "slow_until": sl}}}
    r = decide(now, None, "TEST WINDOW", fb, None, None)
    r["alarms"] = []
    if r["action"] == "idle": r["action"], r["gap"] = "stop", 0
    if r["action"] == "go": r["gap"] = int(os.environ.get("TEST_FAST_S", 60)) if r["due"][0]["mode"] == "fast" else int(os.environ.get("TEST_SLOW_S", 120))
    return r


def main(argv):
    now = datetime.datetime.now(UTC)
    if "--keepalive" in argv:
        tok = os.environ["GH_TOKEN"]
        def get(path):
            req = urllib.request.Request("https://api.github.com/" + path, headers={"authorization": "Bearer " + tok, "accept": "application/vnd.github+json", "user-agent": "race-engineering-ticker"})
            with urllib.request.urlopen(req, timeout=20) as r: return json.load(r)
        print(keepalive(get, lambda p, b: _github_post(p, b, tok), os.environ.get("GITHUB_RUN_ID", ""), os.environ["GITHUB_REPOSITORY"], os.environ.get("GITHUB_REF_NAME", "main")))
        return 0
    last = os.environ.get("LAST_TICK", "")
    last_tick = datetime.datetime.fromtimestamp(int(last), UTC) if last.isdigit() else None
    r = _test_window(now) if os.environ.get("TEST_WINDOW") else decide(now, *read_all(now), last_tick=last_tick)
    if "--status" in argv:
        print(json.dumps({k: r[k] for k in ("action", "gap", "source", "open", "alarms", "warns")})); return 0
    print(f"tick {now:%Y-%m-%dT%H:%M:%SZ}")
    for l in r["lines"]: print(l)
    failed = []
    if "--run" in argv and r["due"]:
        tok = os.environ.get("RUNNER_DISPATCH", "")
        lines, failed = dispatch(r["due"], lambda p, b: _github_post(p, b, tok), os.environ.get("WATCHER_REF") or "main") if tok else ([], ["(no dispatch key)"])
        for l in lines: print(l)
    for w in r["warns"]: print(f"::warning::{w}")
    for a in r["alarms"] + [f"COULD NOT START THE WATCHER for {', '.join(failed)}"] * bool(failed): print(f"::error::{a}")
    if "--run" in argv and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"action={r['action']}\ngap={r['gap']}\nred={'yes' if r['alarms'] or failed else 'no'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
