#!/usr/bin/env python3
"""miss_gate.py -- Stop: a callout from Garrett is answered with a logged miss.

WHY. The learning loop is the core of Skyne: when Garrett calls out a miss, it
is filed, the rule is sharpened, the evidence kept. Nothing made the filing
happen. Measured 2026-10-12, one session: about 20 misses, 5 logged. Garrett:
"Nor did you log a miss anywhere (double check me on that) - that means youre
not doing the core thing of skyne which is a larger problem." So this fires on
every reply, whether or not anyone remembers the loop.

WHAT IT DOES. When Garrett's latest message reads like a callout ("that's a
miss", "you didn't", "should have", "why did X get that wrong", "how is that
enforced", "you let me"), the reply is refused ONCE unless this turn filed a
miss: a tool call that runs `check_misses.py --add` or writes
`data/misses.json`. A reply that says plainly "not a miss:" and why also
passes, so a false alarm costs one line, not a fake row.

WHAT IT DOES NOT DO (house-rules 21 point 5). It sees a callout only in words
like those; a miss Garrett signals some other way gets past. It proves a miss
was FILED, never that it is the right one. Misses caught by a gate or by Claude
itself are not triggered here; their record is still on the session.

NEVER TRAPS A SESSION. `stop_hook_active` allows; every error path exits 0.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wince_gate import last_user_boundary, read_jsonl  # noqa: E402  -- one boundary rule

CALLOUT = re.compile(
    r"\b(?:that'?s|this is|it'?s)\s+(?:also\s+)?a\s+miss\b|\blog (?:a|the|that) miss\b"
    r"|\byou (?:didn'?t|did not|forgot|missed|never)\b|\bshould(?:n'?t)? (?:have|'ve)\b"
    r"|\bwhy did (?:you|\w+) (?:get|miss|do|skip)\b|\bhow is (?:that|this|it) (?:rule )?enforced\b"
    r"|\byou let me\b|\bI (?:already )?(?:told|asked) you\b", re.I)
FILED = re.compile(r"check_misses\.py[^\n]{0,80}--add|data[\\/]+misses\.json", re.I)
NOT_A_MISS = re.compile(r"\bnot a miss\s*:", re.I)


def user_text(entry: dict) -> str:
    c = (entry.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(str(b.get("text", "")) for b in c if isinstance(b, dict))
    return ""


def filed_this_turn(entries: list, b: int) -> bool:
    for e in entries[b + 1:]:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        for blk in (e.get("message") or {}).get("content") or []:
            if isinstance(blk, dict) and blk.get("type") == "tool_use":
                if FILED.search(json.dumps(blk.get("input") or {})):
                    return True
    return False


def decide(payload: dict) -> dict | None:
    if payload.get("stop_hook_active"):
        return None
    entries = read_jsonl(str(payload.get("transcript_path") or ""))
    b = last_user_boundary(entries)
    if b < 0 or not CALLOUT.search(user_text(entries[b])):
        return None
    if filed_this_turn(entries, b):
        return None
    if NOT_A_MISS.search(str(payload.get("last_assistant_message") or "")):
        return None
    return {"decision": "block", "reason":
            "Garrett's message reads like a callout, and this turn filed no miss. The learning "
            "loop is Skyne's core job: file it now (Skyne `scripts/check_misses.py --add`, with "
            "--sweep from 2026-10-13: re-check the same actor's other output first), then answer. "
            "If it is genuinely not a miss, say so in one line starting 'not a miss:' and why."}


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

    def user(text):
        return {"type": "user", "timestamp": "2026-10-12T20:00:00.000Z", "message": {"content": text}}

    def call(name, **inp):
        return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}

    real = ("thats also a miss - you didn't think to make it auto fire. Nor did you log a miss "
            "anywhere (double check me on that)")
    for text, label in [(real, "REPLAY: the 2026-10-12 callout"),
                        ("Ok so why did Wince get that wrong? Thats a miss id want to log", "REPLAY: 'why did Wince get that wrong'"),
                        ("ok but how is that rule ENFORCED", "REPLAY: 'how is that rule ENFORCED'"),
                        ("I love to overcomplicate and you let me", "REPLAY: 'you let me'")]:
        check(bool(CALLOUT.search(text)), f"{label} is read as a callout")
    check(not CALLOUT.search("queue I think for weir"), "an ordinary answer is not a callout")
    check(not CALLOUT.search("A. Yes  B. Wick draws"), "a ruling is not a callout")

    with tempfile.TemporaryDirectory() as d:
        def run(*entries, reply="Claude: done."):
            p = os.path.join(d, "t.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for e in entries:
                    f.write(json.dumps(e) + "\n")
            return decide({"transcript_path": p, "last_assistant_message": reply})

        out = run(user(real), call("Bash", command="git status"))
        check(bool(out) and out["decision"] == "block", "PLANTED: a callout answered with no miss filed is refused")
        check(run(user(real), call("Bash", command="python scripts/check_misses.py --add --id x")) is None,
              "a turn that ran check_misses.py --add passes")
        check(run(user(real), call("Edit", file_path="C:\\x\\Skyne\\data\\misses.json")) is None,
              "a turn that wrote data/misses.json passes")
        check(run(user(real), reply="Claude: not a miss: he was quoting the doc.") is None,
              "an explicit 'not a miss:' with a reason passes")
        check(run(user("merge them"), call("Bash", command="git status")) is None, "no callout, no gate")
        old = run(user(real), call("Bash", command="check_misses.py --add"), user("thanks, next thing"))
        check(old is None, "a miss filed in an EARLIER turn does not answer a new message, and a non-callout passes")
        check(decide({"stop_hook_active": True}) is None, "already refused once: allows")
        r = subprocess.run([sys.executable, __file__], input="garbage", capture_output=True, text=True)
        check(r.returncode == 0 and r.stdout == "", "garbage stdin exits 0 silently")
    print(f"\nmiss_gate self-test: {len(ran) - len(fails)} of {len(ran)} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
