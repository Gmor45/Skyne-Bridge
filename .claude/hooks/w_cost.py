#!/usr/bin/env python3
"""w_cost.py -- what the automatic Wince/Wren follow-ups actually cost (R19).

RULED 2026-11-16, R19. Garrett: "lets try wide and keep tabs on what it actually
costs me for my usage on the max plan". So cost is MEASURED, not estimated, and
read next to the Max plan's weekly percent. This writes one row per day to
`~/.claude/skyne/w-cost.jsonl` and builds the SessionStart line from it.

HOW IT MEASURES (round 11's findings are the spec)
--------------------------------------------------
* Tokens come from the SUBAGENT TRANSCRIPTS on disk
  (`~/.claude/projects/*/<session>/subagents/agent-<id>.jsonl`), summed over
  every assistant message. The totals an Agent result or a task-notification
  reports are the LAST call only, 2-8x too low; and each task-notification
  appears about 3 times in a transcript. So notifications are never read here:
  each agent is counted ONCE by its file, and each model message ONCE by its
  message id (a streamed message repeats its id on every content line; resumed
  and forked chats copy history into new files, so the id is de-duplicated
  across ALL files).
* By model and by token type (input, cache write, cache read, output), because
  a cache read and an output token do not cost the same.
* "Automatic" is defined from the trigger log, not guessed: a Wince or Wren run
  that STARTED within 20 minutes after a gate row in `w-follow.jsonl` that
  refused the reply, in the same session. Everything else is "manual".
* The day is Garrett's (US Eastern), not UTC.
* The Max plan view is the usage HUD's weekly percent
  (`C:\\Users\\gmoor\\claude-usage-hud\\usage-history.jsonl`, rows
  {t: epoch ms, session, weekly}); the day's first, last and change are shown.
* Cloud runs are NOT counted here (their transcripts are not on this PC). The
  readout says so; a count per cloud session via list_events is a lower bound
  the day-14 review adds by hand.

NEVER GETS IN THE WAY: no function here raises into a hook; a day with no data
writes a row of zeros (a calm zero, not a missing day).

Usage:
    python3 w_cost.py compute [--day YYYY-MM-DD]   # write that day's row (default yesterday)
    python3 w_cost.py line                         # the SessionStart line
    python3 w_cost.py --self-test
"""
from __future__ import annotations

import datetime as _dt
import glob
import json
import time
import os
import sys
import tempfile

HOME = os.path.expanduser("~")
TOKEN_TYPES = ("input", "cache_write", "cache_read", "output")
AUTO_WINDOW_S = 20 * 60
CHECKED_SINCE = "2026-11-20"   # first full Eastern day under the Checked-only trigger (ruled 2026-11-19);
                               # days before it ran the old, wider trigger
COMPUTE_STALE_S = 30 * 60      # a background compute older than this is a crash
HUD_DEFAULT = r"C:\Users\gmoor\claude-usage-hud\usage-history.jsonl"


def state_dir() -> str:
    return os.environ.get("SKYNE_STATE_DIR") or os.path.join(HOME, ".claude", "skyne")


def cost_path() -> str:
    return os.path.join(state_dir(), "w-cost.jsonl")


def follow_path() -> str:
    return os.environ.get("SKYNE_W_FOLLOW_LOG") or os.path.join(state_dir(), "w-follow.jsonl")


def projects_dir() -> str:
    return os.environ.get("SKYNE_PROJECTS_DIR") or os.path.join(HOME, ".claude", "projects")


def hud_path() -> str:
    return os.environ.get("SKYNE_HUD_HISTORY") or HUD_DEFAULT


# ------------------------------------------------------------------ his clock

def _nth_sunday(year: int, month: int, n: int) -> _dt.date:
    d = _dt.date(year, month, 1)
    first = d + _dt.timedelta(days=(6 - d.weekday()) % 7)
    return first + _dt.timedelta(weeks=n - 1)


def et_offset_hours(utc: _dt.datetime) -> int:
    """-4 during US daylight time (2nd Sunday of March 07:00Z to 1st Sunday of
    November 06:00Z), else -5. No tzdata needed (Windows Python often lacks it)."""
    y = utc.year
    start = _dt.datetime.combine(_nth_sunday(y, 3, 2), _dt.time(7, 0))
    end = _dt.datetime.combine(_nth_sunday(y, 11, 1), _dt.time(6, 0))
    return -4 if start <= utc.replace(tzinfo=None) < end else -5


def et_day(iso_utc: str) -> str | None:
    try:
        t = _dt.datetime.strptime(iso_utc[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return (t + _dt.timedelta(hours=et_offset_hours(t))).strftime("%Y-%m-%d")


def et_today() -> str:
    return et_day(_dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")) or ""


def prev_day(day: str) -> str:
    return (_dt.datetime.strptime(day, "%Y-%m-%d") - _dt.timedelta(days=1)).strftime("%Y-%m-%d")


def day_start_epoch(day: str) -> float:
    """Epoch of Eastern midnight at the start of `day` (an hour of slack either way)."""
    t = _dt.datetime.strptime(day, "%Y-%m-%d")
    utc_midnight = t.replace(tzinfo=_dt.timezone.utc).timestamp()
    return utc_midnight - et_offset_hours(t + _dt.timedelta(hours=12)) * 3600 - 3600


# --------------------------------------------------------------------- scanning

def _bare(agent_type: str) -> str:
    return str(agent_type or "").split(":")[-1].strip().lower()


def _usage(u: dict) -> dict:
    cc = u.get("cache_creation_input_tokens")
    if cc is None:
        c2 = u.get("cache_creation") or {}
        cc = sum(v for v in c2.values() if isinstance(v, int))
    return {"input": int(u.get("input_tokens") or 0), "cache_write": int(cc or 0),
            "cache_read": int(u.get("cache_read_input_tokens") or 0),
            "output": int(u.get("output_tokens") or 0)}


def agent_types(root: str) -> dict:
    """{agent_id: bare type} from EVERY subagent meta file. A forked chat copies the
    subagent transcripts into its own folder WITHOUT the .meta.json, so the type is
    looked up by agent id, never only beside the copy (W red team round 1: the 11-16
    row said 1 run by hand when there were 15)."""
    out = {}
    for m in glob.glob(os.path.join(root, "*", "*", "subagents", "agent-*.meta.json")):
        aid = os.path.basename(m)[len("agent-"):-len(".meta.json")]
        try:
            with open(m, encoding="utf-8") as f:
                t = _bare(json.load(f).get("agentType"))
        except (OSError, ValueError):
            continue
        if t:
            out[aid] = t
    return out


def scan(day: str, root: str | None = None) -> dict:
    """{message_id: {model, ts, tok, agent, agent_type, session}} for that Eastern day."""
    root = root or projects_dir()
    floor = day_start_epoch(day)
    files = [(f, None) for f in glob.glob(os.path.join(root, "*", "*.jsonl"))]
    files += [(f, True) for f in glob.glob(os.path.join(root, "*", "*", "subagents", "agent-*.jsonl"))]
    types = agent_types(root)
    msgs: dict[str, dict] = {}
    for path, is_sub in files:
        try:
            if os.path.getmtime(path) < floor:
                continue
        except OSError:
            continue
        agent = None
        if is_sub:
            agent = os.path.basename(path)[len("agent-"):-len(".jsonl")]
            session = os.path.basename(os.path.dirname(os.path.dirname(path)))
        else:
            session = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"usage"' not in line or '"assistant"' not in line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    m = e.get("message") or {}
                    if e.get("type") != "assistant" or not isinstance(m.get("usage"), dict):
                        continue
                    ts = str(e.get("timestamp") or "")
                    if et_day(ts) != day:
                        continue
                    tok = _usage(m["usage"])
                    mid = m.get("id") or e.get("requestId") or f"{path}:{ts}"
                    # the LINE says whose message it is; a forked copy keeps the original ids
                    a_id = e.get("agentId") or agent
                    sess = e.get("sessionId") or session
                    old = msgs.get(mid)
                    if old:
                        # same message again: keep the larger count per type, never add
                        old["tok"] = {k: max(old["tok"][k], tok[k]) for k in TOKEN_TYPES}
                        old["ts"] = min(old["ts"], ts)
                        if not old["agent"] and a_id:
                            old["agent"], old["agent_type"] = a_id, types.get(a_id)
                        continue
                    msgs[mid] = {"model": m.get("model") or "unknown", "ts": ts, "tok": tok,
                                 "agent": a_id, "agent_type": types.get(a_id) if a_id else None,
                                 "session": sess}
        except OSError:
            continue
    return msgs


def _blank() -> dict:
    return {t: 0 for t in TOKEN_TYPES}


def _add(into: dict, tok: dict) -> None:
    for t in TOKEN_TYPES:
        into[t] += tok[t]


def read_jsonl(path: str) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    out.append(r)
    except OSError:
        pass
    return out


def hud_view(day: str, path: str | None = None) -> dict:
    rows = read_jsonl(path or hud_path())
    mine = [r for r in rows if isinstance(r.get("t"), (int, float)) and r.get("weekly") is not None
            and et_day(_dt.datetime.fromtimestamp(r["t"] / 1000, _dt.timezone.utc)
                       .strftime("%Y-%m-%dT%H:%M:%S")) == day]
    last_t = max((r["t"] for r in rows if isinstance(r.get("t"), (int, float))), default=None)
    mine.sort(key=lambda r: r["t"])
    return {"weekly_first": mine[0]["weekly"] if mine else None,
            "weekly_last": mine[-1]["weekly"] if mine else None,
            "hud_rows": len(mine),
            "hud_last_utc": (_dt.datetime.fromtimestamp(last_t / 1000, _dt.timezone.utc)
                             .strftime("%Y-%m-%dT%H:%M:%SZ") if last_t else None)}


def compute_day(day: str, root=None, follow=None, hud=None) -> dict:
    msgs = scan(day, root)
    refusals = [r for r in read_jsonl(follow or follow_path())
                if r.get("action") == "refused" and not r.get("test")]
    total, by_model = _blank(), {}
    agents: dict[str, dict] = {}
    for m in msgs.values():
        _add(total, m["tok"])
        if m["agent"] and m["agent_type"] in ("wince", "wren"):
            a = agents.setdefault(m["agent"], {"type": m["agent_type"], "session": m["session"],
                                               "start": m["ts"], "model": {}})
            a["start"] = min(a["start"], m["ts"])
            _add(a["model"].setdefault(m["model"], _blank()), m["tok"])
    runs = {"wince": {"auto": 0, "manual": 0}, "wren": {"auto": 0, "manual": 0}}
    auto_tok, manual_tok = _blank(), _blank()
    for aid, a in agents.items():
        forced = False
        try:
            s = _dt.datetime.strptime(a["start"][:19], "%Y-%m-%dT%H:%M:%S")
            for r in refusals:
                if r.get("session_id") != a["session"]:
                    continue
                t = _dt.datetime.strptime(str(r.get("utc"))[:19], "%Y-%m-%dT%H:%M:%S")
                if 0 <= (s - t).total_seconds() <= AUTO_WINDOW_S:
                    forced = True
                    break
        except ValueError:
            pass
        runs[a["type"]]["auto" if forced else "manual"] += 1
        for model, tok in a["model"].items():
            _add(auto_tok if forced else manual_tok, tok)
            if forced:
                _add(by_model.setdefault(model, _blank()), tok)
    all_total = sum(total.values())
    auto_total = sum(auto_tok.values())
    row = {"day": day, "runs": runs,
           "auto_runs": runs["wince"]["auto"] + runs["wren"]["auto"],
           "manual_runs": runs["wince"]["manual"] + runs["wren"]["manual"],
           "auto_tokens": auto_tok, "auto_by_model": by_model, "manual_tokens": manual_tok,
           "all_tokens": total, "all_messages": len(msgs),
           "share_all": round(auto_total / all_total, 4) if all_total else 0.0,
           "share_output": round(auto_tok["output"] / total["output"], 4) if total["output"] else 0.0,
           "cloud": "not counted: cloud transcripts are not on this PC",
           "written_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    row.update(hud_view(day, hud))
    return row


def _take(lock: str, stale_s: float) -> bool:
    """Create `lock` exclusively; a lock older than stale_s is a crash and is replaced."""
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except (FileExistsError, PermissionError):
            try:
                if time.time() - os.stat(lock).st_mtime > stale_s:
                    os.unlink(lock)
                    continue
            except OSError:
                continue
            return False
    return False


def write_row(row: dict, path: str | None = None) -> None:
    """Replace one day's row. One writer at a time (a `.wlock` beside the file),
    each with its own temp file: two computes used to share one .tmp."""
    path = path or cost_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock = path + ".wlock"
    deadline = time.time() + 15
    while not _take(lock, 60):
        if time.time() > deadline:
            raise RuntimeError(f"{lock} held for 15 s; nothing written")
        time.sleep(0.05)
    try:
        rows = [r for r in read_jsonl(path) if r.get("day") != row["day"]]
        rows.append(row)
        rows.sort(key=lambda r: r.get("day", ""))
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r, sort_keys=True) + "\n")
        for _ in range(100):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:          # Windows: a reader holds the file a moment
                time.sleep(0.05)
        else:
            os.unlink(tmp)
            raise RuntimeError(f"could not replace {path}")
    finally:
        try:
            os.unlink(lock)
        except OSError:
            pass


def fmt_tokens(n: int) -> str:
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e3 else str(n)


def pct(share: float) -> str:
    """Whole percent, half rounds up: the same rule as the Companion card's
    Math.round (Python's round() rounds half to even, and the two disagreed)."""
    return f"{int(share * 100 + 0.5)}%"


def per_day(rows: list[dict]) -> str:
    return f"{sum(r['auto_runs'] for r in rows) / len(rows):.0f}" if rows else "-"


def regimes(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(days under the old wide trigger, days under Checked-only)."""
    return ([r for r in rows if r.get("day", "") < CHECKED_SINCE],
            [r for r in rows if r.get("day", "") >= CHECKED_SINCE])


def line(path: str | None = None, hud=None, today: str | None = None) -> str:
    """The SessionStart readout: yesterday's automatic runs, tokens, share, weekly %."""
    today = today or et_today()
    yday = prev_day(today)
    row = next((r for r in read_jsonl(path or cost_path()) if r.get("day") == yday), None)
    parts = []
    if row:
        a = row["auto_tokens"]
        wk = ""
        if row.get("weekly_last") is not None:
            d = row["weekly_last"] - (row.get("weekly_first") or row["weekly_last"])
            wk = (f" Max weekly {row['weekly_last']}% for the whole plan, all chats "
                  f"({'+' if d >= 0 else ''}{d} that day).")
        n, m = row["auto_runs"], row["manual_runs"]
        by_hand = f" (and {m} more that Claude started itself)" if m else ""
        parts.append(
            f"W follow-up cost, {yday}: the gates asked for {n} Wince/Wren run{'s' if n != 1 else ''}"
            f"{by_hand}. The ones the gates asked for wrote "
            f"{pct(row['share_output'])} of this PC's output that day ({fmt_tokens(a['output'])} of "
            f"{fmt_tokens(row['all_tokens']['output'])} tokens).{wk} Cloud runs not counted.")
        old, new = regimes([r for r in read_jsonl(path or cost_path())
                            if r.get("day", "") >= (go_live_day() or "")])
        if old and new:
            parts.append(f"Gate-asked runs a day: {per_day(old)} under the old wide trigger, "
                         f"{per_day(new)} since the Checked-only change.")
    else:
        parts.append(f"W follow-up cost for {yday}: not computed yet (a background job "
                     f"is computing it; the next session shows it).")
    last = hud_view(yday, hud)["hud_last_utc"]
    if last is None or (_dt.datetime.now(_dt.timezone.utc)
                        - _dt.datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(
                            tzinfo=_dt.timezone.utc)).total_seconds() > 24 * 3600:
        parts.append("The usage HUD has no reading in the last 24 hours, so the Max weekly "
                     "percent is stale: check claude-usage-hud.")
    return " ".join(parts)


def go_live_day() -> str | None:
    try:
        from w_follow import golive_path
        with open(golive_path(), encoding="utf-8") as f:
            return json.load(f).get("go_live")
    except (OSError, ValueError, ImportError):
        return None


def missing_days(today: str | None = None, path: str | None = None, since: str | None = None) -> list[str]:
    """Every day from go-live to yesterday with no FINAL row (a row written on its own
    day is partial). Before this only yesterday was ever computed, so a day with chats
    followed by a day with none was never computed at all (W red team round 1)."""
    today = today or et_today()
    yday = prev_day(today)
    since = since or go_live_day() or yday
    final = {r.get("day") for r in read_jsonl(path or cost_path())
             if r.get("day") and et_day(str(r.get("written_utc"))) != r.get("day")}
    out, d = [], yday
    while d >= since and len(out) < 31:
        if d not in final:
            out.append(d)
        d = prev_day(d)
    return sorted(out)


def ensure_yesterday_in_background(today: str | None = None) -> bool:
    """If any day since go-live (yesterday included) has no final row, start the
    computation detached (SessionStart has a short budget; a full scan is not
    instant). Returns True if one was started."""
    import subprocess
    days = missing_days(today)
    if not days:
        return False
    lock = cost_path() + ".computing"
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    if not _take(lock, COMPUTE_STALE_S):
        return False                     # one is already running: never two full scans at once
    flags = 0
    if sys.platform == "win32":
        flags = 0x00000008 | 0x00000200 | 0x08000000      # DETACHED | NEW_GROUP | NO_WINDOW
    try:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "compute", "--days", ",".join(days)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags,
                         close_fds=True)
        return True
    except OSError:
        try:
            os.unlink(lock)
        except OSError:
            pass
        return False


# -------------------------------------------------------------------- self-test

def _msg(mid, ts, model, inp, cw, cr, out, agent=None, session="S1"):
    """A transcript line in the shape Claude Code writes (copied from a real
    subagent transcript, 2026-11-17): assistant, message{id, model, usage}."""
    e = {"parentUuid": "p", "isSidechain": bool(agent), "type": "assistant", "timestamp": ts,
         "sessionId": session, "message": {"id": mid, "model": model, "role": "assistant",
         "content": [{"type": "text", "text": "x"}],
         "usage": {"input_tokens": inp, "cache_creation_input_tokens": cw,
                   "cache_read_input_tokens": cr, "output_tokens": out,
                   "cache_creation": {"ephemeral_5m_input_tokens": cw, "ephemeral_1h_input_tokens": 0},
                   "service_tier": "standard"}}}
    if agent:
        e["agentId"] = agent
    return json.dumps(e)


def self_test() -> int:
    res = []

    def check(ok, what):
        res.append(bool(ok))
        print(("  ok    " if ok else "  FAIL  ") + what)

    check(et_day("2026-11-17T04:59:59Z") == "2026-11-16" and et_day("2026-11-17T05:00:00Z") == "2026-11-17",
          "the day is Eastern: 05:00Z is midnight in November")
    check(et_day("2026-07-01T03:59:59Z") == "2026-06-30" and et_day("2026-07-01T04:00:00Z") == "2026-07-01",
          "the day is Eastern: 04:00Z is midnight in July (daylight time)")

    with tempfile.TemporaryDirectory() as tmp:
        proj = os.path.join(tmp, "projects", "C--proj")
        sess = "sess-1"
        sub = os.path.join(proj, sess, "subagents")
        os.makedirs(sub)
        day = "2026-11-16"
        # main transcript: one message streamed over 3 lines (same id) = counted once
        with open(os.path.join(proj, sess + ".jsonl"), "w", encoding="utf-8") as f:
            for _ in range(3):
                f.write(_msg("msg_main", "2026-11-16T15:00:00.000Z", "claude-opus-5-5", 2, 1000, 9000, 500) + "\n")
            f.write(_msg("msg_other", "2026-11-17T06:00:00.000Z", "claude-opus-5-5", 9, 9, 9, 9) + "\n")   # next day
        # a forked chat copies msg_main into another file: still once
        with open(os.path.join(proj, "sess-fork.jsonl"), "w", encoding="utf-8") as f:
            f.write(_msg("msg_main", "2026-11-16T15:00:00.000Z", "claude-opus-5-5", 2, 1000, 9000, 500) + "\n")
        # ...and copies the Wince subagent transcript into ITS folder with no .meta.json. The
        # copy sorts FIRST ("a-fork" < "sess-1"), as in the real fork 23663721 of b692ce7f.
        forkdir = os.path.join(proj, "a-fork", "subagents")
        os.makedirs(forkdir)
        with open(os.path.join(forkdir, "agent-awince1.jsonl"), "w", encoding="utf-8") as f:
            f.write(_msg("m1awince1", "2026-11-16T16:02:00.000Z", "claude-opus-5-5", 2, 28000, 64000, 200,
                         agent="awince1", session=sess) + "\n")
        # Wince run, forced (starts 2 min after a refusal), two model messages, one repeated id
        for aid, typ, start in (("awince1", "load-house-rules:wince", "2026-11-16T16:02:00.000Z"),
                                ("awren01", "wren", "2026-11-16T18:00:00.000Z"),
                                ("agen001", "general-purpose", "2026-11-16T16:03:00.000Z")):
            with open(os.path.join(sub, f"agent-{aid}.jsonl"), "w", encoding="utf-8") as f:
                f.write(_msg(f"m1{aid}", start, "claude-opus-5-5", 2, 28000, 64000, 200, agent=aid, session=sess) + "\n")
                f.write(_msg(f"m1{aid}", start, "claude-opus-5-5", 2, 28000, 64000, 200, agent=aid, session=sess) + "\n")
                f.write(_msg(f"m2{aid}", start[:15] + "9:00.000Z", "claude-opus-5-5", 3, 100, 90000, 800, agent=aid, session=sess) + "\n")
            with open(os.path.join(sub, f"agent-{aid}.meta.json"), "w", encoding="utf-8") as f:
                json.dump({"agentType": typ, "isBuiltIn": False, "finished": True}, f)
        follow = os.path.join(tmp, "w-follow.jsonl")
        with open(follow, "w", encoding="utf-8") as f:
            f.write(json.dumps({"utc": "2026-11-16T16:00:00Z", "session_id": sess, "gate": "wince", "action": "refused"}) + "\n")
            f.write(json.dumps({"utc": "2026-11-16T16:00:00Z", "session_id": sess, "gate": "wince", "action": "refused", "test": True}) + "\n")
        hud = os.path.join(tmp, "usage-history.jsonl")
        t0 = int(_dt.datetime(2026, 11, 16, 14, 0, tzinfo=_dt.timezone.utc).timestamp() * 1000)
        with open(hud, "w", encoding="utf-8") as f:
            f.write(json.dumps({"t": t0, "session": 10, "weekly": 30}) + "\n")
            f.write(json.dumps({"t": t0 + 3600000 * 5, "session": None, "weekly": 33}) + "\n")
        row = compute_day(day, os.path.join(tmp, "projects"), follow, hud)
        check(row["all_messages"] == 1 + 3 * 2, "each message id counts once across streamed lines and forked files "
              "(1 main + 3 agents x 2 messages)")
        check(row["runs"]["wince"] == {"auto": 1, "manual": 0} and row["runs"]["wren"] == {"auto": 0, "manual": 1},
              "PLANTED: a Wince run started 2 minutes after a refusal is automatic, even when a forked "
              "chat's meta-less copy of its transcript is read first; a Wren run 2 hours later is by hand")
        check(row["auto_runs"] == 1 and row["manual_runs"] == 1, "a general-purpose agent is neither")
        a = row["auto_tokens"]
        check(a == {"input": 5, "cache_write": 28100, "cache_read": 154000, "output": 1000},
              f"automatic tokens sum both messages once, by type: {a}")
        check(list(row["auto_by_model"]) == ["claude-opus-5-5"], "tokens are reported by model")
        check(row["share_all"] == round(sum(a.values()) / sum(row["all_tokens"].values()), 4)
              and 0 < row["share_all"] < 1, "share is the automatic tokens over ALL the day's tokens")
        check(row["weekly_first"] == 30 and row["weekly_last"] == 33, "the HUD's weekly % that day is read")
        check(scan("2026-11-17", os.path.join(tmp, "projects")).get("msg_other") is not None
              and "msg_other" not in scan(day, os.path.join(tmp, "projects")),
              "a message on the next Eastern day belongs to the next day")
        cp = os.path.join(tmp, "w-cost.jsonl")
        write_row(row, cp)
        write_row(dict(row, auto_runs=7), cp)
        rows = read_jsonl(cp)
        check(len(rows) == 1 and rows[0]["auto_runs"] == 7, "writing a day twice replaces it, never duplicates")
        os.environ["SKYNE_HUD_HISTORY"] = hud
        text = line(cp, hud, today="2026-11-17")
        check("asked for 7 Wince/Wren runs" in text and "Max weekly 33% for the whole plan, all chats (+3 that day)" in text
              and "Cloud runs not counted" in text and "no reading in the last 24 hours" in text
              and "[" not in text and "models" not in text,
              "the start line shows runs, output share, weekly %, says the HUD is stale, and has no "
              "token bracket")
        check(pct(0.2395) == "24%" and pct(0.245) == "25%" and pct(0.0) == "0%",
              "PLANTED: whole percent, half rounds up (Python's round() gives 24% for 0.245's float)")
        # PLANTED: two writers at once -- every day survives (one shared .tmp lost rows before)
        import threading
        wp = os.path.join(tmp, "w-cost-race.jsonl")
        days = [f"2026-10-{i:02d}" for i in range(1, 21)]
        ths = [threading.Thread(target=write_row, args=(dict(row, day=dd), wp)) for dd in days]
        [x.start() for x in ths]
        [x.join() for x in ths]
        check(sorted(r["day"] for r in read_jsonl(wp)) == days,
              "PLANTED: 20 writers at once keep all 20 days (the write lock)")
        # PLANTED: SessionStart in two chats at once starts ONE background compute
        import subprocess as _sp
        started = []
        real_popen = _sp.Popen
        _sp.Popen = lambda *a, **k: started.append(a)
        saved_state = os.environ.get("SKYNE_STATE_DIR")
        os.environ["SKYNE_STATE_DIR"] = tmp
        try:
            r1 = ensure_yesterday_in_background("2026-11-22")
            r2 = ensure_yesterday_in_background("2026-11-22")
        finally:
            _sp.Popen = real_popen
            if saved_state is None:
                os.environ.pop("SKYNE_STATE_DIR", None)
            else:
                os.environ["SKYNE_STATE_DIR"] = saved_state
        check(r1 is True and r2 is False and len(started) == 1,
              "PLANTED: a second start-up while a compute runs does not start another full scan")
        check("not computed yet" in line(os.path.join(tmp, "none.jsonl"), hud, today="2026-11-17"),
              "a missing day says it has not been computed yet")
        empty = compute_day("2026-01-02", os.path.join(tmp, "projects"), follow, hud)
        check(empty["auto_runs"] == 0 and empty["share_all"] == 0.0, "a day with no data is a row of zeros")
        # backfill: every day since go-live without a FINAL row, not just yesterday
        bp = os.path.join(tmp, "w-cost-b.jsonl")
        write_row(dict(row, day="2026-11-18", written_utc="2026-11-19T12:00:00Z"), bp)   # final
        write_row(dict(row, day="2026-11-20", written_utc="2026-11-20T15:00:00Z"), bp)   # partial
        check(missing_days("2026-11-22", bp, "2026-11-18") == ["2026-11-19", "2026-11-20", "2026-11-21"],
              "PLANTED: a skipped day and a partial day since go-live are both computed, not just yesterday")
        # the review counts from go-live only
        rp = os.path.join(tmp, "w-cost-r.jsonl")
        write_row(dict(row, day="2026-11-17", auto_runs=0, share_all=0.0, share_output=0.0), rp)
        write_row(dict(row, day="2026-11-18", auto_runs=12, share_all=0.07, share_output=0.28), rp)
        write_row(dict(row, day="2026-11-19", auto_runs=40, share_all=0.07, share_output=0.24), rp)
        write_row(dict(row, day="2026-11-20", auto_runs=4, share_all=0.01, share_output=0.05), rp)
        rv = review(rp, since="2026-11-18", follow_rows=[], runs=[], grades=[])
        check("3 day(s) from 2026-11-18" in rv and "2 day(s), 52 gate-asked runs (26.0 a day" in rv
              and "1 day(s), 4 gate-asked runs (4.0 a day" in rv and "claude.ai" in rv
              and "Checked-only" in rv,
              "PLANTED: the review leaves out the days before go-live and shows the old wide trigger "
              "and Checked-only apart (mixed, the 4-a-day trigger read as 18.7)")
        os.environ["SKYNE_W_FOLLOW_GOLIVE"] = os.path.join(tmp, "golive.json")
        with open(os.environ["SKYNE_W_FOLLOW_GOLIVE"], "w", encoding="utf-8") as f:
            json.dump({"go_live": "2026-11-18"}, f)
        lt = line(rp, hud, today="2026-11-21")
        os.environ.pop("SKYNE_W_FOLLOW_GOLIVE", None)
        check("26 under the old wide trigger, 4 since the Checked-only change" in lt,
              "PLANTED: the start line gives the yardstick: runs a day before and after the change: " + lt)
        check(" tokens)." in lt and "run by hand" not in lt and "that Claude started itself" in lt,
              "PLANTED: the token counts carry a unit and hand runs read as 'that Claude started "
              "itself': " + lt)
        # the follow-through total is split at the trigger change too (W red team round 3)
        fr = [{"gate": "wince", "action": "released", "session_id": "a", "utc": "2026-11-19T20:00:00Z",
               "triggers": ["checked"]},
              {"gate": "wince", "action": "released", "session_id": "b", "utc": "2026-11-20T20:00:00Z",
               "triggers": ["checked"]}]
        rv2 = review(rp, since="2026-11-18", follow_rows=fr, runs=[], grades=[])
        check("Follow-through, old wide trigger: 1 of 1 refused reply never got" in rv2
              and "Follow-through, Checked-only: 1 of 1 refused reply never got" in rv2,
              "PLANTED: the review's follow-through is shown before and after the change: " + rv2)
        os.environ.pop("SKYNE_HUD_HISTORY", None)
    print(f"w_cost self-test: {sum(res)}/{len(res)} passed")
    return 0 if all(res) else 1


def review(path: str | None = None, since: str | None = None, follow_rows=None, runs=None,
           grades=None) -> str:
    """The real numbers for the day-14 review (R19/R22): runs a day, share of his
    output and of all tokens, Max weekly % trend, and how many refusals went out
    unchecked -- counted from go-live only (the two days before it had no
    automatic runs and pulled the average down; W red team round 1)."""
    since = since or go_live_day() or ""
    rows = [r for r in read_jsonl(path or cost_path()) if r.get("day") and r["day"] >= since]
    if not rows:
        return "no w-cost.jsonl rows since go-live yet: nothing to review."
    wk = [r for r in rows if r.get("weekly_last") is not None]
    lines = [f"W follow-up review: {len(rows)} day(s) from {rows[0]['day']} to {rows[-1]['day']} "
             f"(go-live {since or 'unknown'} onward). The trigger changed on {CHECKED_SINCE}, so the "
             f"two are shown apart: decide on the second."]
    for label, part in zip((f"Old wide trigger (before {CHECKED_SINCE})", "Checked-only (since then)"),
                           regimes(rows)):
        if not part:
            lines.append(f"  {label}: no days.")
            continue
        n = len(part)
        auto = sum(r["auto_runs"] for r in part)
        outs = [r["share_output"] for r in part]
        lines.append(f"  {label}: {n} day(s), {auto} gate-asked runs ({auto / n:.1f} a day, peak "
                     f"{max(r['auto_runs'] for r in part)}; {sum(r['manual_runs'] for r in part)} more "
                     f"that Claude started itself); they wrote {pct(sum(outs) / n)} of this PC's output on average "
                     f"(worst day {pct(max(outs))}).")
    try:
        import w_follow
        for label, part in zip(("old wide trigger", "Checked-only"), regimes(rows)):
            c = {"released": 0, "followed": 0, "late": 0, "never": 0}
            for r in part:
                ft = w_follow.follow_through(r["day"], follow_rows, runs, grades)
                for k in c:
                    c[k] += ft[k]
            n = c["released"]
            lines.append(f"  Follow-through, {label}: {c['never']} of {n} refused repl"
                         f"{'y' if n == 1 else 'ies'} never got the owed Wince/Wren run or filing; "
                         f"{c['followed']} got it within 2 hours, {c['late']} later.")
    except Exception:                                           # noqa: BLE001
        lines.append("  Follow-through: could not be counted (w_follow did not load).")
    if wk:
        lines.append(f"  Max weekly %: {wk[0]['weekly_last']} on {wk[0]['day']} -> {wk[-1]['weekly_last']} on "
                     f"{wk[-1]['day']} (the HUD view; it resets weekly, so read the trend, not the change).")
    else:
        lines.append("  Max weekly %: the HUD recorded no reading on these days.")
    lines.append("  NOT in these numbers: cloud runs, and Wince passes in claude.ai chats and Cowork "
                 "(none of them leave a transcript on this PC).")
    lines.append("  Ask Garrett: keep Checked-only as is / Wince only at Checked (no Wren) / turn the gates off. "
                 "Then run `review --done`.")
    return "\n".join(lines)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv:
        return self_test()
    try:
        if argv and argv[0] == "review":
            if "--done" in argv:
                from w_follow import golive_path
                with open(golive_path(), encoding="utf-8") as f:
                    g = json.load(f)
                g["reviewed"] = True
                g["reviewed_on"] = et_today()
                with open(golive_path(), "w", encoding="utf-8", newline="\n") as f:
                    json.dump(g, f, indent=2)
                    f.write("\n")
                print("day-14 review marked done; the start line goes quiet.")
            else:
                print(review())
        elif argv and argv[0] == "compute":
            if "--days" in argv:
                days = [x for x in argv[argv.index("--days") + 1].split(",") if x]
            else:
                days = [argv[argv.index("--day") + 1] if "--day" in argv else prev_day(et_today())]
            try:
                for day in days:
                    row = compute_day(day)
                    write_row(row)
                    print(f"w-cost {day}: {row['auto_runs']} automatic, {row['manual_runs']} manual, "
                          f"share {row['share_all'] * 100:.2f}%")
            finally:
                if "--days" in argv:      # the background run started by SessionStart
                    try:
                        os.unlink(cost_path() + ".computing")
                    except OSError:
                        pass
        elif argv and argv[0] == "line":
            print(line())
        else:
            print(__doc__)
    except Exception as exc:                                  # noqa: BLE001
        print(f"w_cost: {type(exc).__name__}: {exc}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
