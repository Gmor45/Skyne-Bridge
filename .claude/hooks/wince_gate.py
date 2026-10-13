#!/usr/bin/env python3
"""wince_gate.py -- Stop: a W finished this turn and Wince did not follow it.

RULED 2026-10-12 (Skyne DECISIONS.md). Garrett: *"From now on I want Wince to
follow every other W when they do something."* Then, on how: *"Check output not
steps. But if it finds issues in output, it should work backwards to look at
process"*, and on whether this check was optional: *"Hook enforces everything
is supposed to be a standing skyne rule you shouldn't have to propose that you
should have done it from the start."* So this hook is part of the ruling, not an
option on it (house-rules 21).

WHAT IT CATCHES
---------------
A reply is refused ONCE when, since Garrett's last message, a Skyne Family W
other than Wince finished a run and no Wince run finished after it. The refusal
names the W(s) and tells the session to send Wince over that output before
replying: output first, and where Wince finds a problem, back to the process
that made it.

WHERE IT LOOKS, IN ORDER
------------------------
1. `w_ran.py`'s log (~/.claude/skyne/w-runs.jsonl, or $SKYNE_W_RUNS_LOG): stop
   rows for THIS session since the last user message, ordered by when each run
   FINISHED. Authoritative when present, because it sees a W that ran in the
   background and finished later, and it orders by completion, not by launch
   (Wince launched beside a W, in parallel, has not critiqued its output).
2. The transcript, when the log has nothing for this session (a cloud
   container, or w_ran.py not delivered): Agent/Task calls in the main loop
   since the last user message, in call order.
Neither needs `prompt_id`, which no hook in this repo has ever been shown to
receive -- measured 2026-10-12, no log on the machine and only fake ids in tests.

WHAT IT DOES NOT DO (house-rules 21 point 5)
--------------------------------------------
- A W run as a generic agent (a session without Bridge's plugin has no W agent
  types) is invisible to both sources. Bridge's agent files and every product's
  family pointer tell the session to say so rather than pretend.
- It proves Wince RAN after the W, never that Wince read that W's output. The
  refusal says which output; the critique itself is still Wince's.
- It does not critique Garrett. That lens is Wince's, on request; nothing here
  fires on his messages.

NEVER TRAPS A SESSION
---------------------
`stop_hook_active` (the platform's re-entry flag) means it already refused once
this turn: it allows. Every error path prints nothing and exits 0.

Usage:
    python3 wince_gate.py             # the hook (JSON on stdin)
    python3 wince_gate.py --self-test
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from w_ran import log_path, member  # noqa: E402  -- one W roster, one log path

CRITIC = "wince"


def read_jsonl(path: str) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a half-written tail line
                if isinstance(row, dict):
                    out.append(row)
    except OSError:
        return []
    return out


def last_user_boundary(entries: list[dict]) -> int:
    """Index of the newest real user turn (same test as reply_gate.py)."""
    for i in range(len(entries) - 1, -1, -1):
        e = entries[i]
        if (e.get("type") == "user" and not e.get("isMeta")
                and not e.get("toolUseResult") and not e.get("isSidechain")):
            return i
    return -1


def from_transcript(entries: list[dict], boundary: int) -> list[str]:
    """W ids called from the main loop since the boundary, in call order."""
    order = []
    for e in entries[boundary + 1:]:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for blk in content:
            if (isinstance(blk, dict) and blk.get("type") == "tool_use"
                    and blk.get("name") in ("Agent", "Task")):
                w = member((blk.get("input") or {}).get("subagent_type"))
                if w:
                    order.append(w)
    return order


def from_log(rows: list[dict], session_id: str, since_utc: str) -> list[str]:
    """W ids that FINISHED in this session since `since_utc`, in finish order."""
    stops = [r for r in rows
             if r.get("event") == "stop" and r.get("w")
             and r.get("session_id") == session_id
             and str(r.get("utc") or "") >= since_utc]
    stops.sort(key=lambda r: str(r.get("utc")))  # stable: file order breaks ties
    return [r["w"] for r in stops]


def unfollowed(order: list[str]) -> list[str]:
    """The non-critic Ws with no critic run after the last of them."""
    last_other = max((i for i, w in enumerate(order) if w != CRITIC), default=-1)
    if last_other < 0:
        return []
    if any(w == CRITIC for w in order[last_other + 1:]):
        return []
    seen = []
    for w in order:
        if w != CRITIC and w not in seen:
            seen.append(w)
    return seen


def refusal(ws: list[str], source: str) -> str:
    names = ", ".join(w.capitalize() for w in ws)
    return (f"Wince follows every W (RULED 2026-10-12): {names} finished this turn "
            f"and no Wince run came after it ({source}). Before replying, run the "
            f"`wince` agent (load-house-rules:wince) on that output: grade the "
            f"OUTPUT first, against what that W's output is for, and where it finds "
            f"a problem, work back to the process that produced it. Wince grades and "
            f"names problems; it never rewrites. If Wince is unavailable in this "
            f"session, say so in one line instead.")


def unbacked_overrules(session: str, since: str, path: str | None = None) -> int:
    """Overrules Wince made this turn that overrule_gate.py could not back."""
    p = path or os.environ.get("SKYNE_OVERRULES_LOG") or os.path.join(
        os.path.expanduser("~"), ".claude", "skyne", "overrules.jsonl")
    return sum(1 for r in read_jsonl(p) if r.get("status") == "unbacked"
               and r.get("session_id") == session and str(r.get("utc") or "") >= since)


def decide(payload: dict, log_rows: list[dict] | None = None,
           overrules_path: str | None = None) -> dict | None:
    if payload.get("stop_hook_active"):
        return None
    entries = read_jsonl(str(payload.get("transcript_path") or ""))
    b = last_user_boundary(entries)
    if b < 0:
        return None
    since = str(entries[b].get("timestamp") or "")[:19] + "Z"
    session = str(payload.get("session_id") or "")
    n = unbacked_overrules(session, since, overrules_path) if session and len(since) == 20 else 0
    if n:
        return {"decision": "block", "reason":
                f"Wince overruled {n} verdict(s) this turn without a receipt that holds up "
                f"(overrule_gate.py logged them as unbacked). Do not pass those verdicts on as "
                f"Wince's findings: tell Garrett in one line which ones are unbacked, or re-run "
                f"Wince on the W's full output."}
    rows = read_jsonl(log_path()) if log_rows is None else log_rows
    order = from_log(rows, session, since) if session and len(since) == 20 else []
    source = "w_ran log"
    if not order:
        order, source = from_transcript(entries, b), "transcript"
    ws = unfollowed(order)
    return {"decision": "block", "reason": refusal(ws, source)} if ws else None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        out = decide(payload) if isinstance(payload, dict) else None
        if out:
            print(json.dumps(out))
    except Exception:  # noqa: BLE001 -- a gate must never cost a turn
        pass
    return 0


def self_test() -> int:
    import subprocess
    import tempfile
    ran, fails = [], []

    def check(ok, label):
        ran.append(label)
        if not ok:
            fails.append(label)
        print(("  ok   " if ok else "  FAIL ") + label)

    check(unfollowed([]) == [], "no W ran: nothing owed")
    check(unfollowed(["wince"]) == [], "only Wince ran: nothing owed")
    check(unfollowed(["wander", "wince"]) == [], "a W followed by Wince is clean")
    check(unfollowed(["wander"]) == ["wander"], "PLANTED: a W with no Wince is caught")
    check(unfollowed(["wince", "wander"]) == ["wander"],
          "PLANTED: Wince BEFORE the W does not count -- it cannot have read the output")
    check(unfollowed(["wander", "wince", "wistin"]) == ["wander", "wistin"],
          "PLANTED: a second W after the critique owes its own Wince, and both are named")
    check(member("load-house-rules:Wince") == "wince" and member("general-purpose") is None,
          "the plugin-prefixed agent type resolves; a generic agent is not a W")

    t0 = "2026-10-12T16:00:00.000Z"
    user = {"type": "user", "timestamp": t0, "message": {"content": "go"}}

    def call(w):
        return {"type": "assistant", "timestamp": t0, "message": {"content": [
            {"type": "tool_use", "name": "Agent",
             "input": {"subagent_type": f"load-house-rules:{w}", "prompt": "x"}}]}}
    tool_result = {"type": "user", "toolUseResult": {"x": 1}, "timestamp": t0,
                   "message": {"content": [{"type": "tool_result"}]}}
    sidechain = dict(call("wince"), isSidechain=True)

    with tempfile.TemporaryDirectory() as d:
        # never read this machine's real overrule log during a self-test
        os.environ["SKYNE_OVERRULES_LOG"] = os.path.join(d, "no-such-log.jsonl")

        def transcript(*entries):
            p = os.path.join(d, "t.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for e in entries:
                    f.write(json.dumps(e) + "\n")
            return {"transcript_path": p, "session_id": "s1"}

        check(decide(transcript(user, call("wander"), tool_result, call("wince")), []) is None,
              "transcript: W then Wince allows")
        out = decide(transcript(user, call("wander"), tool_result), [])
        check(bool(out) and out["decision"] == "block" and "Wander" in out["reason"],
              "PLANTED: transcript: a W with no Wince is refused, naming the W")
        check(decide(transcript(user, call("wander"), sidechain), []) is not None,
              "PLANTED: a Wince call inside a subagent's sidechain does not count for the main loop")
        old = {"type": "user", "timestamp": "2026-10-12T15:00:00.000Z",
               "message": {"content": "earlier"}}
        check(decide(transcript(old, call("wander"), tool_result, user), []) is None,
              "a W from an EARLIER turn is not this turn's debt")
        p = transcript(user, call("wander"), tool_result)
        check(decide(dict(p, stop_hook_active=True), []) is None,
              "already refused once this turn: it allows (never traps a session)")

        # the log: authoritative, ordered by finish, and per-session
        log = [{"event": "stop", "w": "wander", "session_id": "s1", "utc": "2026-10-12T16:00:05Z"},
               {"event": "stop", "w": "wince", "session_id": "s1", "utc": "2026-10-12T16:00:09Z"}]
        check(decide(transcript(user), log) is None,
              "log: a background W followed by Wince allows, with no Agent call in the transcript")
        out = decide(transcript(user), log[:1])
        check(bool(out) and "w_ran log" in out["reason"],
              "PLANTED: log: a background W that finished with no Wince is refused")
        par = [dict(log[1], utc="2026-10-12T16:00:03Z"), log[0]]
        check(decide(transcript(user, call("wince"), call("wander")), par) is not None,
              "PLANTED: Wince that FINISHED before the W finished did not critique it")
        other = [dict(log[0], session_id="s2")]
        check(decide(transcript(user), other) is None,
              "another session's W runs are not this session's debt")
        stale = [dict(log[0], utc="2026-10-12T15:59:59Z")]
        check(decide(transcript(user), stale) is None,
              "a W that finished before Garrett's last message is not this turn's")

        # an unbacked overrule logged by overrule_gate.py this turn refuses the reply
        op = os.path.join(d, "overrules.jsonl")
        with open(op, "w", encoding="utf-8") as f:
            f.write(json.dumps({"status": "unbacked", "session_id": "s1",
                                "utc": "2026-10-12T16:00:07Z"}) + "\n")
        out = decide(transcript(user, call("wander"), tool_result, call("wince")), [], op)
        check(bool(out) and "unbacked" in out["reason"],
              "PLANTED: an unbacked Wince overrule this turn refuses the reply")
        stale_op = os.path.join(d, "stale.jsonl")
        with open(stale_op, "w", encoding="utf-8") as f:
            f.write(json.dumps({"status": "unbacked", "session_id": "s1",
                                "utc": "2026-10-12T15:59:00Z"}) + "\n")
        check(decide(transcript(user), [], stale_op) is None,
              "an unbacked overrule from an earlier turn is not this turn's")

        # end to end through stdin, as the harness runs it
        env = dict(os.environ, SKYNE_W_RUNS_LOG=os.path.join(d, "none.jsonl"))
        r = subprocess.run([sys.executable, __file__], input=json.dumps(
            transcript(user, call("warden"), tool_result)), capture_output=True,
            text=True, env=env)
        check(r.returncode == 0 and '"block"' in r.stdout and "Warden" in r.stdout,
              "PLANTED: end to end, a block is printed as JSON and the exit is 0")
        r = subprocess.run([sys.executable, __file__], input="not json",
                           capture_output=True, text=True, env=env)
        check(r.returncode == 0 and r.stdout == "", "garbage stdin exits 0, silently")

    print(f"\nwince_gate self-test: {len(ran) - len(fails)} of {len(ran)} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
