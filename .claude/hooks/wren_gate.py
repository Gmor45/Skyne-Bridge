#!/usr/bin/env python3
"""wren_gate.py -- Stop: something was made that can be used, and Wren never tried it.

RULED 2026-10-17, then NARROWED by R5/R9 on 2026-11-16 (Skyne DECISIONS). Wren had
nothing that ever set him off; Garrett chose "After something new is built". The
old trigger was a Wistin or Wick AGENT run. Since 2026-11-16 those two are labels,
not agents, so the trigger is the work itself:

CHECKED ONLY (RULED 2026-11-19, Skyne DECISIONS)
-------------------------------------------------
The publish and maker-label triggers below are RETIRED. A reply is now refused
ONCE when the turn marked a Plan board feature's Checked stage done (an
ArtifactData write, w_follow.checked_marks) and no `wren` run finished after the
turn's last edit. Checked means "Passed Wince and Wren" on the board, so this is
the board's own definition, enforced. The escape line below still works.

WHAT IT CAUGHT UNTIL 2026-11-19
-------------------------------
A reply was refused ONCE when, since Garrett's last message, either
* a PUBLISH of something runnable happened (an Artifact publish that is not an
  asset upload), or
* a MAKER label (Wistin:, Wick:, Ward:, Warden:, Whittle:) is on the first or
  newest text block of a turn that WROTE a file (Edit/Write/NotebookEdit),
and no `wren` agent run FINISHED after the turn's last edit/publish. The refusal
tells the session to send Wren to try it the lazy way: no docs, the obvious
button. Wren runs first; then ONE Wince pass grades the work and Wren's report
(wince_gate.py enforces that order).

Not everything a maker writes can be used (lore, a note). The escape is a LINE
in the reply starting "nothing for Wren to try:" and a reason.

THE SWITCH, THE LOG, THE CLOUD
------------------------------
Same as wince_gate.py: `log` in ~/.claude/skyne/w-follow-mode turns the refusal
into a log row ("log-would-refuse"); every call writes a row to
~/.claude/skyne/w-follow.jsonl; in the cloud the trigger only logs.

WHAT IT DOES NOT DO (house-rules 21 point 5)
--------------------------------------------
* Files written by subagents, by scripts, or by a shell redirect are not writes
  here; a build done under "Claude:" is not a maker label. Only the main loop's
  own Edit/Write calls and its own labels are seen.
* It proves Wren RAN after the work, never that Wren tried that thing.
* One escape line covers every maker thing before it in the turn.

HOW A REFUSAL IS SENT
---------------------
As Stop feedback (`hookSpecificOutput.additionalContext`), not a `block` hook
error, opening with one plain line for Garrett: see wince_gate.py.

NEVER TRAPS A SESSION
---------------------
`stop_hook_active` means it already refused once this turn: it allows (and logs
"released"). An error prints nothing, exits 0 and writes an `error` row.

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
from wince_gate import (  # noqa: E402  -- one boundary rule, one way to read a run
    CRITIC, IMPORT_ERROR, _raw_error_row, agent_runs, hook_output, last_user_boundary, read_jsonl,
    review_floor)
try:
    from w_ran import log_path  # noqa: E402  -- one log path
    import w_follow  # noqa: E402
except Exception as _exc:  # noqa: BLE001 -- recorded by main()
    IMPORT_ERROR = IMPORT_ERROR or _exc

USER = "wren"
MAKERS = tuple(m.lower() for m in w_follow.MAKER_LABELS)
# A LINE that starts "nothing for Wren to try:" and gives a real reason.
NOTHING = re.compile(r"^[ \t>*_-]*nothing for wren to try:[ \t]*[^\s\"'<>]", re.I | re.M)


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


def wren_owed(facts: dict, entries: list[dict], boundary: int) -> bool:
    """Does this turn owe a Wren try? (before looking for his run)"""
    return bool(facts["checked"]) and not escaped(entries, boundary)


def old_rule(facts: dict) -> bool:
    """What the retired 2026-11-16 trigger would have fired on. Logged, never enforced."""
    runnable = any(n == "Artifact" for _, n in facts["publishes"])
    made = bool(facts["labels"] & set(w_follow.MAKER_LABELS)) and bool(facts["writes"])
    return runnable or made


def refusal(facts: dict) -> str:
    marked = sorted({fid for _, fid in facts["checked"]})
    what = [f"a Plan board feature marked Checked ({', '.join(marked)})"]
    return (f"Wren tries what is made before it counts as Checked: this turn has "
            f"{' and '.join(what)}, and no `wren` agent run has finished since. Before Claude finishes, "
            f"run the `wren` agent on what was made: use it the way "
            f"Garrett would on a lazy day -- no docs, the obvious button -- and report where it "
            f"got stuck (render_page.py gives him a look at a page). Wren reports; he never "
            f"fixes. Then ONE `wince` pass grades the work and Wren's report. If nothing made can "
            f"be used (lore, a note), say \"nothing for Wren to try: <why>\" in one line instead.")


def decide(payload: dict, log_rows: list[dict] | None = None, log_it: bool = True) -> dict | None:
    entries = read_jsonl(str(payload.get("transcript_path") or ""))
    b = last_user_boundary(entries)
    if b < 0:
        return None
    since_s = str(entries[b].get("timestamp") or "")[:19]
    session = str(payload.get("session_id") or "")
    rows = read_jsonl(log_path()) if log_rows is None else log_rows
    mode, mode_note = w_follow.read_mode()
    cloud = w_follow.is_cloud()
    facts = w_follow.turn_facts(entries, b)
    all_facts = w_follow.turn_facts(entries, -1)
    owed = wren_owed(facts, entries, b)
    satisfied = wince_too = False
    if owed:
        floor, recent = review_floor(entries, b)       # a try in the turn before counts
        work = max(w_follow.last_work_ts(recent), floor)
        satisfied = any(r["finish"] >= work
                        for r in agent_runs(entries, rows, session, USER, all_facts))
        # wince_gate refuses this same mark with BOTH steps (Wren, then one Wince)
        # unless a Wince already covers it: then one message is enough.
        wince_too = not any(r["finish"] >= work
                            for r in agent_runs(entries, rows, session, CRITIC, all_facts))
    out, action = None, "quiet"
    if owed and not satisfied:
        if mode == "enforce" and w_follow.cloud_enforces():
            if wince_too:
                action = "left-to-wince"
            else:
                out, action = {"decision": "block", "reason": refusal(facts)}, "refused"
        else:
            action = "log-would-refuse"
    elif owed:
        action = "satisfied"
    if payload.get("stop_hook_active"):
        # A Wren still owed on the second try goes out with the reply. Log it as
        # released even when wince_gate's refusal carried it (left-to-wince), or the
        # follow-through count never sees the Wren debt (W red team round 3).
        if out or action == "left-to-wince":
            action = "released"
        out = None
    if log_it:
        w_follow.log_row({"gate": "wren", "action": action, "mode": mode, "cloud": cloud,
                          "session_id": session,
                          "triggers": ["checked"] if facts["checked"] else [],
                          "old_rule": old_rule(facts)})
        if mode == "enforce" and session and not cloud:
            w_follow.record_golive()
    return out


def main() -> int:
    if IMPORT_ERROR is not None:
        _raw_error_row("wren", IMPORT_ERROR)
        return 0
    try:
        raw = sys.stdin.read() or "{}"
        try:
            payload = json.loads(raw)
        except ValueError:
            return 0            # not a hook call
        out = decide(payload) if isinstance(payload, dict) else None
        if out:
            print(json.dumps(hook_output(out)))
    except Exception as exc:  # noqa: BLE001 -- a gate must never cost a turn
        w_follow.log_error("wren", exc)
    return 0


# -------------------------------------------------------------------- self-test

def self_test() -> int:
    import subprocess
    import tempfile
    ran, fails = [], []

    def check(ok, label):
        ran.append(label)
        if not ok:
            fails.append(label)
        print(("  ok   " if ok else "  FAIL ") + label)

    t = "2026-11-17T15:00:%02d.000Z"
    user = {"type": "user", "timestamp": t % 0, "message": {"content": "go"}}

    def said(sec, text):
        return {"type": "assistant", "timestamp": t % sec,
                "message": {"content": [{"type": "text", "text": text}]}}

    def tool(sec, name, inp, tid="x"):
        return {"type": "assistant", "timestamp": t % sec, "message": {"content": [
            {"type": "tool_use", "id": tid, "name": name, "input": inp}]}}

    write = lambda sec: tool(sec, "Write", {"file_path": "C:\\x\\a.py", "content": "print(1)"})
    # Claude marks feature BL-1 Checked on the Plan board (seven stages, Checked = index 3)
    mark = lambda sec: tool(sec, "ArtifactData", {"action": "update", "url": "https://claude.ai/artifact/X",
                                                  "collection": "features", "doc_id": "BL-1", "if_version": 2,
                                                  "data": {"s": ["done"] * 4 + ["no"] * 3,
                                                           "stageDates": {"checked": "2026-11-17T15:00:%02dZ" % sec}}}, tid=f"m{sec}")
    publish = lambda sec: tool(sec, "Artifact", {"file_path": "C:\\x\\page.html", "icon": "chart",
                                                 "description": "d"})

    def wren_done(sec):
        return [tool(sec, "Agent", {"subagent_type": "wren", "prompt": "try it"}, tid="wr1"),
                {"type": "user", "timestamp": t % (sec + 1), "toolUseResult": {"status": "completed"},
                 "message": {"content": [{"type": "tool_result", "tool_use_id": "wr1",
                                          "content": [{"type": "text", "text": "Wren: stuck at login"}]}]}}]

    with tempfile.TemporaryDirectory() as d:
        os.environ["SKYNE_W_FOLLOW_LOG"] = os.path.join(d, "w-follow.jsonl")
        os.environ["SKYNE_W_FOLLOW_MODE"] = os.path.join(d, "mode")
        os.environ["SKYNE_W_FOLLOW_GOLIVE"] = os.path.join(d, "golive.json")
        os.environ.pop("CLAUDE_CODE_REMOTE", None)

        def transcript(*entries, **kw):
            p = os.path.join(d, "t.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for e in entries:
                    f.write(json.dumps(e) + "\n")
            return dict({"transcript_path": p, "session_id": "s1"}, **kw)

        def logged():
            return read_jsonl(os.environ["SKYNE_W_FOLLOW_LOG"])

        check(decide(transcript(user, said(1, "Wistin: here is the script."), write(2), said(3, "Wistin: done.")), []) is None
              and logged()[-1]["old_rule"] is True,
              "a Wistin: turn that wrote a file no longer owes Wren (RULED 2026-11-19); the log says the old rule would have")
        WL = [{"event": "stop", "w": "wince", "session_id": "s1", "agent_id": "aw", "utc": "2026-11-17T15:00:08Z"}]      # a Wince that already covers the work
        out = decide(transcript(user, said(1, "Here is the script."), write(2), mark(3), said(4, "Marked Checked.")), WL)
        check(bool(out) and out["decision"] == "block" and "Wren tries what is made" in out["reason"]
              and "BL-1" in out["reason"],
              "PLANTED: marking a board feature Checked with no Wren run owes Wren")
        check(logged()[-1]["action"] == "refused" and logged()[-1]["gate"] == "wren",
              "the refusal is logged to w-follow.jsonl")
        check(decide(transcript(user, said(1, "Wistin: here."), write(2), mark(2), *wren_done(3), said(6, "Wistin: done.")), []) is None
              and logged()[-1]["action"] == "satisfied",
              "a Wren run that finished after the write satisfies it")
        check(decide(transcript(user, said(1, "Wistin: here."), *wren_done(2), write(5), mark(5), said(6, "Wistin: done.")), WL)
              is not None, "PLANTED: a Wren run BEFORE the last write does not count")
        check(decide(transcript(user, said(1, "Here."), write(2), mark(3), said(4, "Marked.")), []) is None
              and logged()[-1]["action"] == "left-to-wince",
              "PLANTED: with no Wince either, Wren stays quiet: wince_gate's one refusal names both steps")
        check(decide(dict(transcript(user, said(1, "Here."), write(2), mark(3), said(4, "Marked.")),
                          stop_hook_active=True), []) is None
              and logged()[-1]["action"] == "released",
              "PLANTED: a Wren still owed when the reply goes out anyway is logged released, so the "
              "follow-through count owes it (it used to read left-to-wince and vanish)")
        check("before replying" not in refusal({"checked": [(0, "BL-1")]}).lower(),
              "PLANTED: the refusal says 'before Claude finishes', not 'before replying' (round 3)")
        # a background agent's finish (real shape, transcript 1fbee306) is not Garrett's turn: the
        # Wren try before it, in his previous turn, still covers the mark after his "yes"
        note = {"type": "user", "timestamp": t % 6, "promptSource": "system",
                "origin": {"kind": "task-notification", "producer": "session-task"},
                "message": {"role": "user", "content": "<task-notification>\n<status>completed</status>"}}
        yes = {"type": "user", "timestamp": t % 7, "origin": {"kind": "human"}, "message": {"content": "yes"}}
        check(decide(transcript(user, said(1, "Here."), write(2), *wren_done(3), note, yes, mark(8),
                                said(9, "Marked.")), WL) is None,
              "PLANTED: a task-notification between the Wren try and Garrett's yes does not move the floor")
        # W red team round 3: a Wren call that was refused, failed, or stopped saying nothing is a
        # SKIPPED run, and used to count as done
        wren_err = [tool(3, "Agent", {"subagent_type": "wren", "prompt": "try it"}, tid="wr2"),
                    {"type": "user", "timestamp": t % 4, "toolUseResult": {"status": "error"},
                     "message": {"content": [{"type": "tool_result", "tool_use_id": "wr2", "is_error": True,
                                              "content": "Agent type 'wren' could not start"}]}}]
        check(decide(transcript(user, said(1, "Here."), write(2), *wren_err, mark(5), said(6, "Marked.")), WL) is not None,
              "PLANTED: a Wren call that failed to start (is_error) is a skipped run, not done (round 3)")
        silent = [{"event": "stop", "w": "wren", "session_id": "s1", "agent_id": "as", "utc": "2026-11-17T15:00:04Z",
                   "last_message_chars": 0}]
        check(decide(transcript(user, said(1, "Here."), write(2), mark(5), said(6, "Marked.")), WL + silent) is not None,
              "PLANTED: a Wren stop that said nothing (0 characters) is a skipped run, not done (round 3)")
        said_it = [dict(silent[0], last_message_chars=40)]
        check(decide(transcript(user, said(1, "Here."), write(2), mark(5), said(6, "Marked.")), WL + said_it) is None,
              "a Wren stop with a real report (40 characters) still counts")
        prev = {"type": "user", "timestamp": "2026-11-17T14:59:00.000Z", "message": {"content": "build"}}
        tried = [{"event": "stop", "w": "wren", "session_id": "s1", "agent_id": "ar", "utc": "2026-11-17T14:59:30Z"}]
        check(decide(transcript(prev, tool(0, "Write", {"file_path": "a", "content": "1"}) | {"timestamp": "2026-11-17T14:59:10.000Z"},
                                user, mark(3), said(4, "Marked.")), WL + tried) is None,
              "PLANTED: a Wren try in the turn before the Checked mark covers it")
        check(decide(transcript(user, said(1, "Weir: I would pick B."), said(2, "Weir: so B.")), []) is None,
              "a non-maker label (Weir) with no file is quiet")
        check(decide(transcript(user, said(1, "Weir: one more option."), write(2), said(3, "Weir: done.")), []) is None,
              "a non-maker label that wrote a file is Wince's, not Wren's")
        check(decide(transcript(user, said(1, "Claude: quick fix."), write(2), said(3, "Claude: done.")), []) is None,
              "a Claude:-labeled turn that wrote a file triggers nothing (a named blind spot)")
        check(decide(transcript(user, said(1, "Wistin: lore."), write(2), mark(2),
                                said(3, "Wistin: done.\nNothing for Wren to try: it is a lore note.")), []) is None,
              "the escape line, with a reason, lets it through")
        check(decide(transcript(user, said(1, "Wistin: lore."), write(2), mark(2),
                                said(3, 'the hook wants "nothing for Wren to try" said')), WL) is not None,
              "PLANTED: mentioning the escape mid-line is not using it")
        quoted = (decide(transcript(user, said(1, "Wistin: x"), write(2), mark(2)), WL) or {}).get("reason", "")
        check(bool(quoted) and decide(transcript(user, said(1, "Wistin: x"), write(2), mark(2), said(3, quoted)), WL) is not None,
              "PLANTED: quoting the refusal back (its '<why>' placeholder) is not the escape")
        check(decide(transcript(user, publish(1)), []) is None and logged()[-1]["old_rule"] is True,
              "an Artifact publish no longer owes Wren (RULED 2026-11-19); still logged")
        check(decide(transcript(user, tool(1, "Artifact", {"action": "publish", "asset": True, "url": "u",
                                                           "file_path": "a.png"})), []) is None,
              "an asset upload is not a publish")
        check(decide(transcript(user, tool(1, "mcp__a2e5608f-73d1-4432-84e6-22b3701e89d8__generate_diagram", {})), []) is None,
              "a Figma generate_diagram is Wince's (a look), not Wren's (nothing runnable)")
        old = {"type": "user", "timestamp": "2026-11-17T14:00:00.000Z", "message": {"content": "earlier"}}
        check(decide(transcript(old, said(1, "Wistin: x"), write(2), mark(2), user), []) is None,
              "a make from an EARLIER turn is not this turn's debt")
        p = transcript(user, said(1, "Wistin: x"), write(2), mark(2), said(3, "Wistin: y"))
        check(decide(dict(p, stop_hook_active=True), WL) is None and logged()[-1]["action"] == "released",
              "already refused once this turn: it allows, and logs 'released'")
        log = [{"event": "stop", "w": "wren", "session_id": "s1", "agent_id": "a1", "utc": "2026-11-17T15:00:09Z"}]
        check(decide(transcript(user, said(1, "Wistin: x"), write(2), mark(2), said(3, "Wistin: y")), log) is None,
              "a Wren that finished in the background (w_ran log) after the write satisfies it")
        check(decide(transcript(user, said(1, "Wistin: x"), write(2), mark(2), said(3, "Wistin: y")),
                     [dict(log[0], session_id="s2")] + WL) is not None,
              "another session's Wren run is not this session's")

        # the switch
        def set_mode(raw):
            with open(os.environ["SKYNE_W_FOLLOW_MODE"], "wb") as f:
                f.write(raw)
        trig = transcript(user, said(1, "Wistin: x"), write(2), mark(2), said(3, "Wistin: y"))
        for label, raw in (("plain", b"log"), ("utf-8 BOM", b"\xef\xbb\xbflog\r\n"),
                           ("utf-16", "log\r\n".encode("utf-16"))):
            set_mode(raw)
            check(decide(trig, []) is None and logged()[-1]["action"] == "log-would-refuse",
                  f"switch written as {label}: logs, refuses nothing")
        set_mode(b"banana")
        out = decide(trig, WL)
        check(bool(out) and "w-follow-mode" not in out["reason"],
              "a garbage switch value enforces; the refusal never names the switch file")
        os.unlink(os.environ["SKYNE_W_FOLLOW_MODE"])

        # cloud: logs, never refuses (PC-only until a cloud session confirms)
        os.environ["CLAUDE_CODE_REMOTE"] = "true"
        check(decide(trig, []) is None and logged()[-1]["cloud"] is True
              and logged()[-1]["action"] == "log-would-refuse",
              "in the cloud the Wren trigger logs and refuses nothing (R12 not live there)")
        os.environ.pop("CLAUDE_CODE_REMOTE", None)

        # end to end through stdin, as the harness runs it
        runs_log = os.path.join(d, "runs.jsonl")
        with open(runs_log, "w", encoding="utf-8") as f:
            f.write(json.dumps(WL[0]) + "\n")
        env = dict(os.environ, SKYNE_W_RUNS_LOG=runs_log)
        r = subprocess.run([sys.executable, __file__], input=json.dumps(trig),
                           capture_output=True, text=True, env=env)
        printed = json.loads(r.stdout or "{}")
        ctx = (printed.get("hookSpecificOutput") or {}).get("additionalContext", "")
        check(r.returncode == 0 and "decision" not in printed and "Wren tries what is made" in ctx
              and ctx.startswith("Claude owes a Wince/Wren follow-up")
              and not any(x in ctx for x in ("RULED", "load-house-rules:", "w-follow-mode")),
              "PLANTED: end to end, a refusal is printed as plain Stop feedback (not a 'block' hook "
              "error, no rule numbers or off switch) and the exit is 0")
        r = subprocess.run([sys.executable, __file__], input="not json",
                           capture_output=True, text=True, env=env)
        check(r.returncode == 0 and r.stdout == "", "garbage stdin exits 0, silently")
        check(logged()[0].get("utc", "").endswith("Z") and all("gate" in x for x in logged()),
              "every gate call wrote a row with a time and a gate name")
        check(os.path.exists(os.environ["SKYNE_W_FOLLOW_GOLIVE"]),
              "the first enforced run recorded the go-live date")
        for k in ("SKYNE_W_FOLLOW_LOG", "SKYNE_W_FOLLOW_MODE", "SKYNE_W_FOLLOW_GOLIVE"):
            os.environ.pop(k, None)

    print(f"\nwren_gate self-test: {len(ran) - len(fails)} of {len(ran)} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
