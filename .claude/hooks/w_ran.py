#!/usr/bin/env python3
"""w_ran.py -- SubagentStart / SubagentStop: record that a Skyne Family agent actually ran.

WHY THIS EXISTS
---------------
Garrett, 2026-10-05: *"whenever I want Skyne to do something, it fires up the
corresponding agent, the agent does the thing, and then I'm done. The Ws are
the buckets that all skyne falls into -- the loop is how the buckets get
BETTER."*

`tier_gate.py` now NAMES the agent a job belongs to (the W router). A hook
cannot start an agent, so the session has to send it -- and a router whose
advice is ignored looks exactly like one that works, unless something records
what actually ran. This is that record. One row per start and per stop, joined
to the router's row in `tier-gate.jsonl` on `prompt_id`, so
`skyne/scripts/w_triggers.py --logs` can say, per W: routed N times, ran M
times, ran without being routed K times. That number is what the Loop
improves.

WHAT IT RECORDS
---------------
`~/.claude/skyne/w-runs.jsonl`, one row per event:
    utc, event (start|stop), w (the bare member id, or null for any other
    agent), agent_type (as the harness sent it), agent_id, session_id,
    prompt_id, and on stop the length of the agent's last message (never its
    text -- the log is a count, not a copy).

Every agent is logged, not only the family, so "how often does work go to an
agent that is NOT a W" is answerable too (Explore, haiku-mechanic, ...).

NEVER GETS IN THE WAY
---------------------
SubagentStart cannot block, and this hook never blocks SubagentStop either:
it prints nothing and exits 0 on every path, including garbage stdin and an
unwritable log.

Usage:
    python3 w_ran.py              # the hook (JSON on stdin)
    python3 w_ran.py --self-test
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import tempfile

# The family, in the card's order (Skyne data/skyne-family.json) -- eight
# since Wren joined on 2026-10-07.
# ci.yml checks this tuple against reply_gate.SPEAKER_LABELS.
W_AGENTS = ("wistin", "ward", "weir", "wander", "warden", "whittle", "wick", "wren")


def log_path() -> str:
    return os.environ.get("SKYNE_W_RUNS_LOG") or os.path.join(
        os.path.expanduser("~"), ".claude", "skyne", "w-runs.jsonl")


def member(agent_type) -> str | None:
    """'load-house-rules:warden' / 'Warden' / 'warden' -> 'warden'; anything else -> None."""
    bare = str(agent_type or "").strip().strip("^$").split(":")[-1].lower()
    return bare if bare in W_AGENTS else None


def row_for(payload: dict) -> dict | None:
    ev = str(payload.get("hook_event_name") or "")
    if ev not in ("SubagentStart", "SubagentStop"):
        return None
    row = {"utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "event": "start" if ev == "SubagentStart" else "stop",
           "w": member(payload.get("agent_type")),
           "agent_type": payload.get("agent_type"),
           "agent_id": payload.get("agent_id"),
           "session_id": payload.get("session_id"),
           "prompt_id": payload.get("prompt_id")}
    if row["event"] == "stop":
        row["last_message_chars"] = len(str(payload.get("last_assistant_message") or ""))
    return row


def append(row: dict, path: str | None = None) -> bool:
    path = path or log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        return True
    except OSError:
        return False


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        row = row_for(payload) if isinstance(payload, dict) else None
        if row:
            append(row)
    except Exception:  # noqa: BLE001 -- a logging hook must never cost a turn
        pass
    return 0


def self_test() -> int:
    ran, fails = [], []

    def check(ok, label):
        ran.append(label)
        if not ok:
            fails.append(label)

    check(member("warden") == "warden", "a bare member id is recognised")
    check(member("load-house-rules:wick") == "wick", "a plugin-scoped member is recognised")
    check(member("Weir") == "weir", "case does not matter")
    check(member("Explore") is None and member("haiku-mechanic") is None,
          "an agent that is not a family member is not credited to a W")
    check(member("") is None and member(None) is None, "no agent type is no member")

    start = row_for({"hook_event_name": "SubagentStart", "agent_type": "load-house-rules:warden",
                     "agent_id": "a1", "session_id": "s1", "prompt_id": "p1"})
    check(start and start["event"] == "start" and start["w"] == "warden" and start["prompt_id"] == "p1",
          "a W start is recorded with its prompt_id (the join key to the router)")
    stop = row_for({"hook_event_name": "SubagentStop", "agent_type": "wick", "agent_id": "a2",
                    "last_assistant_message": "Wick: drew it"})
    check(stop and stop["event"] == "stop" and stop["last_message_chars"] == 13
          and "drew it" not in json.dumps(stop), "a stop records the length of the reply, never its text")
    check(row_for({"hook_event_name": "Stop"}) is None, "other events are ignored")
    other = row_for({"hook_event_name": "SubagentStart", "agent_type": "Explore"})
    check(other and other["w"] is None, "a non-W agent is still logged, with w null")

    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "deep", "w-runs.jsonl")
        check(append(start, p) and append(stop, p), "the log is created and appended")
        with open(p) as f:
            rows = [json.loads(x) for x in f]
        check([r["event"] for r in rows] == ["start", "stop"], "rows land in order, one per event")
        check(not append(start, os.path.join(p, "cannot", "be", "a", "dir")),
              "an unwritable log returns False rather than raising")

    import subprocess
    for bad in ("not json", "[]", ""):
        cp = subprocess.run([sys.executable, os.path.abspath(__file__)], input=bad,
                            capture_output=True, text=True,
                            env=dict(os.environ, SKYNE_W_RUNS_LOG=os.path.join(tempfile.gettempdir(),
                                                                               "w-runs-selftest.jsonl")))
        check(cp.returncode == 0 and not cp.stdout.strip(), f"stdin {bad!r} exits 0 and prints nothing")

    if fails:
        for f in fails:
            print("SELF-TEST FAIL:", f)
        print(f"w_ran self-test: {len(fails)} FAILED")
        return 1
    print(f"w_ran self-test: {len(ran)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv[1:] else main())
