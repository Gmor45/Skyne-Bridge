#!/usr/bin/env python3
"""wren_gate.py -- Stop: a W built something Garrett would use, and Wren never tried it.

RULED 2026-10-17 (Skyne DECISIONS.md). Wren had nothing that ever set him off:
`w_triggers.py` read him 0 scheduled, 0 event. Asked what should, Garrett chose
"After something new is built": when a W builds a page, board or script he
would use, the chat cannot reply until Wren has tried it. Same shape as
`wince_gate.py`, which makes Wince follow every W.

WHAT IT CATCHES
---------------
A reply is refused ONCE when, since Garrett's last message, a MAKER finished a
run and no Wren run finished after it. The makers are the two Ws whose output
is a thing to use: Wistin (makes code, scripts, pages) and Wick (draws boards,
charts, layouts). The refusal names them and tells the session to send Wren
to try what they made, the lazy way, before replying.

Not everything Wistin makes can be used -- lore, a note, a character. The
escape for that is a LINE in the reply starting "nothing for Wren to try:"
with a reason, the same shape as wince_gate's "no grade to file:".

WHERE IT LOOKS
--------------
Exactly where wince_gate.py looks, through its own functions: w_ran.py's log
first (it sees background runs and orders by finish), the transcript
otherwise. One boundary rule, one log, one roster.

WHAT IT DOES NOT DO (house-rules 21 point 5)
--------------------------------------------
- Most building happens in the main loop, not in a W agent -- a session
  writing a script itself is invisible here. Only a Wistin or Wick RUN is
  seen. Catching main-loop builds would mean judging every Edit, which fires
  on ordinary work.
- It proves Wren RAN after the maker, never that Wren tried that maker's
  thing. The refusal says which; the trying is still Wren's.
- A maker run as a generic agent is invisible, as in wince_gate.py.
- One escape line covers every maker before it in the turn.

NEVER TRAPS A SESSION
---------------------
`stop_hook_active` means it already refused once this turn: it allows. Every
error path prints nothing and exits 0.

Usage:
    python3 wren_gate.py             # the hook (JSON on stdin)
    python3 wren_gate.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from w_ran import log_path  # noqa: E402  -- one log path
from wince_gate import (  # noqa: E402  -- one boundary rule, one way to read a run
    from_log, from_transcript, last_user_boundary, read_jsonl)

USER = "wren"
MAKERS = ("wistin", "wick")
# A LINE that starts "nothing for Wren to try:" and gives a real reason.
NOTHING = re.compile(r"^[ \t>*_-]*nothing for wren to try:[ \t]*[^\s\"'<>]", re.I | re.M)


def untried(order: list[str]) -> list[str]:
    """The makers with no Wren run after the last of them."""
    last_maker = max((i for i, w in enumerate(order) if w in MAKERS), default=-1)
    if last_maker < 0:
        return []
    if any(w == USER for w in order[last_maker + 1:]):
        return []
    seen = []
    for w in order:
        if w in MAKERS and w not in seen:
            seen.append(w)
    return seen


def escaped(entries: list[dict], boundary: int) -> bool:
    """The main loop said "nothing for Wren to try:" this turn."""
    for e in entries[boundary + 1:]:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        for blk in (e.get("message") or {}).get("content") or []:
            if (isinstance(blk, dict) and blk.get("type") == "text"
                    and NOTHING.search(str(blk.get("text") or ""))):
                return True
    return False


def refusal(ws: list[str], source: str) -> str:
    names = ", ".join(w.capitalize() for w in ws)
    return (f"Wren tries what a W builds (RULED 2026-10-17): {names} finished this turn "
            f"and no Wren run came after it ({source}). Before replying, run the `wren` "
            f"agent (load-house-rules:wren) on what was made: use it the way Garrett "
            f"would on a lazy day -- no docs, the obvious button -- and report where it "
            f"got stuck. Wren reports; he never fixes. If nothing made can be used (lore, "
            f"a note), say \"nothing for Wren to try: <why>\" in one line instead.")


def decide(payload: dict, log_rows: list[dict] | None = None) -> dict | None:
    if payload.get("stop_hook_active"):
        return None
    entries = read_jsonl(str(payload.get("transcript_path") or ""))
    b = last_user_boundary(entries)
    if b < 0:
        return None
    since = str(entries[b].get("timestamp") or "")[:19] + "Z"
    session = str(payload.get("session_id") or "")
    rows = read_jsonl(log_path()) if log_rows is None else log_rows
    order = from_log(rows, session, since) if session and len(since) == 20 else []
    source = "w_ran log"
    if not order:
        order, source = from_transcript(entries, b), "transcript"
    ws = untried(order)
    if not ws or escaped(entries, b):
        return None
    return {"decision": "block", "reason": refusal(ws, source)}


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

    check(untried([]) == [], "no W ran: nothing owed")
    check(untried(["wander", "warden"]) == [], "non-makers owe Wren nothing")
    check(untried(["wistin", "wren"]) == [], "a maker followed by Wren is clean")
    check(untried(["wistin"]) == ["wistin"], "PLANTED: a maker with no Wren is caught")
    check(untried(["wren", "wick"]) == ["wick"],
          "PLANTED: Wren BEFORE the maker does not count -- nothing was built yet")
    check(untried(["wistin", "wren", "wick"]) == ["wistin", "wick"],
          "PLANTED: a second maker after Wren owes its own try, and both are named")
    check(untried(["wistin", "wren", "wince"]) == [],
          "Wince after Wren does not reopen Wren's debt")

    t0 = "2026-10-17T18:00:00.000Z"
    user = {"type": "user", "timestamp": t0, "message": {"content": "go"}}

    def call(w):
        return {"type": "assistant", "timestamp": t0, "message": {"content": [
            {"type": "tool_use", "name": "Agent",
             "input": {"subagent_type": f"load-house-rules:{w}", "prompt": "x"}}]}}

    def said(text):
        return {"type": "assistant", "timestamp": t0,
                "message": {"content": [{"type": "text", "text": text}]}}

    tool_result = {"type": "user", "toolUseResult": {"x": 1}, "timestamp": t0,
                   "message": {"content": [{"type": "tool_result"}]}}

    with tempfile.TemporaryDirectory() as d:
        def transcript(*entries):
            p = os.path.join(d, "t.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for e in entries:
                    f.write(json.dumps(e) + "\n")
            return {"transcript_path": p, "session_id": "s1"}

        check(decide(transcript(user, call("wistin"), tool_result, call("wren")), []) is None,
              "transcript: maker then Wren allows")
        out = decide(transcript(user, call("wick"), tool_result), [])
        check(bool(out) and out["decision"] == "block" and "Wick" in out["reason"],
              "PLANTED: transcript: a maker with no Wren is refused, naming the maker")
        check(decide(transcript(user, call("wander"), tool_result), []) is None,
              "a proposer (not a maker) running alone is not Wren's debt")
        check(decide(transcript(user, call("wistin"), dict(call("wren"), isSidechain=True)), [])
              is not None, "PLANTED: a Wren call inside a sidechain does not count")
        check(decide(transcript(user, call("wistin"), tool_result,
                                said("Wistin wrote lore.\nNothing for Wren to try: it is a lore note.")),
                     []) is None, "the escape line, with a reason, lets it through")
        check(decide(transcript(user, call("wistin"), tool_result,
                                said('the hook wants "nothing for Wren to try" said')), []) is not None,
              "PLANTED: mentioning the escape mid-line is not using it")
        quoted = (decide(transcript(user, call("wistin"), tool_result), []) or {}).get("reason", "")
        check(decide(transcript(user, call("wistin"), tool_result, said(quoted)), []) is not None,
              "PLANTED: quoting the refusal back (its '<why>' placeholder) is not the escape")
        old = {"type": "user", "timestamp": "2026-10-17T17:00:00.000Z",
               "message": {"content": "earlier"}}
        check(decide(transcript(old, call("wistin"), tool_result, user), []) is None,
              "a maker from an EARLIER turn is not this turn's debt")
        p = transcript(user, call("wistin"), tool_result)
        check(decide(dict(p, stop_hook_active=True), []) is None,
              "already refused once this turn: it allows (never traps a session)")

        log = [{"event": "stop", "w": "wick", "session_id": "s1", "utc": "2026-10-17T18:00:05Z"},
               {"event": "stop", "w": "wren", "session_id": "s1", "utc": "2026-10-17T18:00:09Z"}]
        check(decide(transcript(user), log) is None,
              "log: a background maker followed by Wren allows")
        out = decide(transcript(user), log[:1])
        check(bool(out) and "w_ran log" in out["reason"],
              "PLANTED: log: a background maker that finished with no Wren is refused")
        check(decide(transcript(user), [dict(log[0], session_id="s2")]) is None,
              "another session's maker is not this session's debt")

        env = dict(os.environ, SKYNE_W_RUNS_LOG=os.path.join(d, "none.jsonl"))
        r = subprocess.run([sys.executable, __file__], input=json.dumps(
            transcript(user, call("wistin"), tool_result)), capture_output=True,
            text=True, env=env)
        check(r.returncode == 0 and '"block"' in r.stdout and "Wistin" in r.stdout,
              "PLANTED: end to end, a block is printed as JSON and the exit is 0")
        r = subprocess.run([sys.executable, __file__], input="not json",
                           capture_output=True, text=True, env=env)
        check(r.returncode == 0 and r.stdout == "", "garbage stdin exits 0, silently")

    print(f"\nwren_gate self-test: {len(ran) - len(fails)} of {len(ran)} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
