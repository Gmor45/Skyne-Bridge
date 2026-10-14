#!/usr/bin/env python3
"""wince_gate.py -- Stop: a W finished and Wince did not follow it, or Wince graded and nobody filed it.

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

AND A WINCE GRADE NOBODY FILED (added 2026-10-14)
-------------------------------------------------
Garrett: *"if Wince gives it an F and it never changes then why did I do it?"*
Skyne's `scripts/wince_grades.py` records every pass, but nothing made a
session run it, so a grade that went nowhere left no trace. This refuses a
reply -- at most once a turn, and again every turn until it is dealt with --
when a Wince run FINISHED in this session after the last command naming
`wince_grades` (`wince_grades.py add`, or an inline script that imports it).
Finished means: a synchronous Agent call whose result came back, or a `stop`
row in w_ran.py's log -- so a Wince still running in the background is never
owed yet. A Wince run that was not a graded pass (a prose critique, say) is
let through once the reply has a line starting "no grade to file:" and a reason.

WHAT IT DOES NOT DO (house-rules 21 point 5)
--------------------------------------------
- It sees the register writer's NAME in a shell command after the grade --
  not that the command ran, succeeded, or wrote this grade. A `cat` of the
  script, or an `add` the register refused, reads as filed. And one filing
  covers every grade before it (a single script often records several), so
  two grades and one filing pass. The escape works the same way: one
  "no grade to file:" line covers every grade before it, real ones included.
  Like the register itself, what a session types about its own work is
  trusted.
- A script SAVED to a file and run by name (`python3 seed.py`) is not seen
  even if it imports the writer; the session gets refused and files with a
  command that names it.
- With no w_ran.py log (a cloud container, or the plugin not delivered), a
  Wince run in the BACKGROUND is never seen finishing -- the transcript only
  shows "Async agent launched" -- so it is never owed. Only synchronous runs
  are caught on that path.
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
import re
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


FILER = "wince_grades"            # Skyne's register writer, in any invocation
# The stated escape: a LINE that starts "no grade to file:" and gives a reason.
# Starting its own line is what tells using the escape from describing it --
# prose, a quoted refusal or a code block that mentions it mid-line does not
# count (Wince, passes 2 and 3). The reason must be real text: the refusal's
# own placeholder "<why>" is not one.
NO_GRADE = re.compile(r"^[ \t>*_-]*no grade to file:[ \t]*[^\s\"'<>]", re.I | re.M)
SHELLS = ("Bash", "PowerShell")


def _ts(s) -> str:
    """Seconds-precision UTC, so transcript and log timestamps compare."""
    return str(s or "")[:19]


def wince_finishes(entries: list[dict], rows: list[dict], session: str) -> list[str]:
    """When each Wince run in this session FINISHED. The log when it has rows
    for this session, else the transcript -- the same precedence as the
    W-follow check, so one run is never counted twice (Wince, hook pass 1)."""
    # One row per agent_id: on the work laptop w_ran.py is registered twice
    # (plugin and personal copy), so every event lands twice -- measured
    # 2026-10-14 on this very session's log.
    logged = {r.get("agent_id") or (r.get("utc"), i): _ts(r.get("utc"))
              for i, r in enumerate(rows)
              if r.get("event") == "stop" and r.get("w") == CRITIC
              and r.get("session_id") == session}
    if logged:
        return [t for t in logged.values() if t]
    out, calls = [], set()
    for e in entries:
        if e.get("type") == "assistant" and not e.get("isSidechain"):
            for blk in (e.get("message") or {}).get("content") or []:
                if (isinstance(blk, dict) and blk.get("type") == "tool_use"
                        and blk.get("name") in ("Agent", "Task")
                        and member((blk.get("input") or {}).get("subagent_type")) == CRITIC):
                    calls.add(blk.get("id"))
        elif e.get("type") == "user" and calls:
            for blk in (e.get("message") or {}).get("content") or []:
                if (isinstance(blk, dict) and blk.get("type") == "tool_result"
                        and blk.get("tool_use_id") in calls
                        and "Async agent launched" not in json.dumps(blk.get("content"))):
                    out.append(_ts(e.get("timestamp")))
    return [t for t in out if t]


def last_accounted(entries: list[dict]) -> str:
    """The last moment every finished grade so far was accounted for: a shell
    command naming the register's writer, OR the main loop saying "no grade
    to file". Both move the same watermark, so an escape said once is not
    asked for again every later turn, and an escape said BEFORE a Wince run
    does not cover it (Wince, hook pass 1). '' if never."""
    last = ""
    for e in entries:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        for blk in (e.get("message") or {}).get("content") or []:
            if not isinstance(blk, dict):
                continue
            filed = (blk.get("type") == "tool_use" and blk.get("name") in SHELLS
                     and FILER in str((blk.get("input") or {}).get("command") or ""))
            escaped = (blk.get("type") == "text"
                       and bool(NO_GRADE.search(str(blk.get("text") or ""))))
            if filed or escaped:
                last = max(last, _ts(e.get("timestamp")))
    return last


def unfiled_grades(entries: list[dict], rows: list[dict], session: str) -> int:
    done = last_accounted(entries)
    return sum(1 for t in wince_finishes(entries, rows, session) if t > done)


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
    reasons = []
    n = unbacked_overrules(session, since, overrules_path) if session and len(since) == 20 else 0
    if n:
        reasons.append(
            f"Wince overruled {n} verdict(s) this turn without a receipt that holds up "
            f"(overrule_gate.py logged them as unbacked). Do not pass those verdicts on as "
            f"Wince's findings: tell Garrett in one line which ones are unbacked, or re-run "
            f"Wince on the W's full output.")
    rows = read_jsonl(log_path()) if log_rows is None else log_rows
    owed = unfiled_grades(entries, rows, session) if session else 0
    if owed:
        reasons.append(
            f"{owed} Wince grade(s) finished in this session after the grade register "
            f"was last written. Record them in Skyne's register (python3 "
            f"scripts/wince_grades.py add ...; one command can record several), so a "
            f"grade that changed nothing still leaves a trace (RULED 2026-10-14). If a "
            f"Wince run was not a graded pass, say \"no grade to file: <why>\" in one line.")
    order = from_log(rows, session, since) if session and len(since) == 20 else []
    source = "w_ran log"
    if not order:
        order, source = from_transcript(entries, b), "transcript"
    ws = unfollowed(order)
    if ws:
        reasons.append(refusal(ws, source))
    # One refusal a turn is all a Stop hook gets (stop_hook_active lets the
    # next one through), so both debts go in it or the second is dropped.
    return {"decision": "block", "reason": " ALSO: ".join(reasons)} if reasons else None


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
        filed_late = {"type": "assistant", "timestamp": "2026-10-12T16:00:10.000Z",
                      "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {
                          "command": "python3 scripts/wince_grades.py add --grade B"}}]}}
        check(decide(transcript(user, filed_late), log) is None,
              "log: a background W followed by Wince (grade filed) allows, with no Agent call")
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
        out = decide(transcript(user, call("wander"), tool_result), [], op)
        check(bool(out) and "unbacked" in out["reason"] and "Wander" in out["reason"],
              "PLANTED: an unbacked overrule no longer hides an unfollowed W -- both are named")
        stale_op = os.path.join(d, "stale.jsonl")
        with open(stale_op, "w", encoding="utf-8") as f:
            f.write(json.dumps({"status": "unbacked", "session_id": "s1",
                                "utc": "2026-10-12T15:59:00Z"}) + "\n")
        check(decide(transcript(user), [], stale_op) is None,
              "an unbacked overrule from an earlier turn is not this turn's")

        # A Wince GRADE nobody filed (RULED 2026-10-14). Sync run: the result came back.
        def wince_call(at):
            return {"type": "assistant", "timestamp": at, "message": {"content": [
                {"type": "tool_use", "id": "w1", "name": "Agent",
                 "input": {"subagent_type": "load-house-rules:wince", "prompt": "grade"}}]}}

        def wince_result(at, text="Wince: GRADE: B"):
            return {"type": "user", "timestamp": at, "toolUseResult": {"x": 1},
                    "message": {"content": [{"type": "tool_result", "tool_use_id": "w1",
                                             "content": [{"type": "text", "text": text}]}]}}

        def filing(at, cmd="python3 scripts/wince_grades.py add --subject x --grade B"):
            return {"type": "assistant", "timestamp": at, "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": cmd}}]}}

        def said(text):
            return {"type": "assistant", "timestamp": "2026-10-12T16:00:30.000Z",
                    "message": {"content": [{"type": "text", "text": text}]}}

        graded = (user, wince_call("2026-10-12T16:00:01.000Z"),
                  wince_result("2026-10-12T16:00:20.000Z"))
        out = decide(transcript(*graded), [])
        check(bool(out) and "wince_grades.py add" in out["reason"],
              "PLANTED: a Wince grade that came back and was never filed is refused")
        check(decide(transcript(*graded, filing("2026-10-12T16:00:25.000Z")), []) is None,
              "a grade filed after it came back allows")
        check(decide(transcript(filing("2026-10-12T15:00:00.000Z"), *graded), []) is not None,
              "PLANTED: a filing from BEFORE the grade came back does not cover it")
        check(decide(transcript(*graded, filing("2026-10-12T16:00:25.000Z",
                    "cd skyne && python3 - <<'PY'\nimport wince_grades as w\nw.add(doc, ...)\nPY")),
                     []) is None,
              "a script that imports the register's writer counts as filing")
        check(decide(transcript(*graded, said('the hook wants "no grade to file" said')), []) is not None,
              "PLANTED: prose that only MENTIONS the phrase (no colon) does not count as the escape")
        check(decide(transcript(*graded, said(
            "I would write no grade to file: and the reason, but this was graded")), []) is not None,
              "PLANTED: describing the escape mid-sentence is not using it")
        check(decide(transcript(*graded, said("```say no grade to file: reason here```")), [])
              is not None, "PLANTED: a code span quoting the escape is not using it")
        check(decide(transcript(*graded, said("Wince read prose.\nNo grade to file: it was a critique.")), []) is None,
              "a Wince run that was not a graded pass is let through when the reply says so")
        quoted = decide(transcript(*graded), [])["reason"]
        check(decide(transcript(*graded, said(f"The hook said: {quoted}")), []) is not None,
              "PLANTED: quoting the refusal back (its '<why>' placeholder) is not the escape")
        early_escape = {"type": "assistant", "timestamp": "2026-10-12T16:00:00.500Z",
                        "message": {"content": [{"type": "text", "text": "no grade to file: early"}]}}
        check(decide(transcript(user, early_escape, *graded[1:]), []) is not None,
              "PLANTED: 'no grade to file' said BEFORE the Wince run does not cover it")
        later_turn = {"type": "user", "timestamp": "2026-10-12T17:00:00.000Z",
                      "message": {"content": "next thing"}}
        check(decide(transcript(*graded, said("No grade to file: prose only."), later_turn), [])
              is None, "an escape said in an EARLIER turn still covers it -- no nagging every turn")
        both = [{"event": "stop", "w": "wince", "session_id": "s1", "agent_id": "a1",
                 "utc": "2026-10-12T16:00:20Z"}] * 2   # the hook registered twice
        out = decide(transcript(*graded), both)
        check(bool(out) and out["reason"].startswith("1 Wince grade"),
              "a run in both the log and the transcript is counted once")
        out = decide(transcript(*graded, call("wander")), [])
        check(bool(out) and "wince_grades.py add" in out["reason"] and "Wander" in out["reason"],
              "PLANTED: an unfiled grade AND an unfollowed W are both named in the one refusal")
        bg = (user, wince_call("2026-10-12T16:00:01.000Z"),
              wince_result("2026-10-12T16:00:02.000Z", "Async agent launched successfully."))
        check(decide(transcript(*bg), []) is None,
              "a Wince still running in the background is not owed yet")
        late = [{"event": "stop", "w": "wince", "session_id": "s1", "utc": "2026-10-12T16:00:40Z"}]
        check(decide(transcript(*bg), late) is not None,
              "PLANTED: the background Wince is owed once the log shows it finished")
        check(decide(transcript(*bg), [dict(late[0], session_id="s2")]) is None,
              "another session's Wince is not this session's to file")

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
