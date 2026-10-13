#!/usr/bin/env python3
"""overrule_gate.py -- SubagentStop: Wince may not overrule a W without a real receipt.

WHY. 2026-10-12: Wince overruled Wren's own NEEDED for Exceed, quoting "pins
already log friction" as a concession. Wren had written the opposite. Wince had
been handed Claude's summary, not Wren's report, and nothing caught it but
Garrett. A rule in wince.md saying "back every overrule" is the thing Garrett
named: "Saying 'dont do that' is asking for claude to forget." So this fires
when Wince FINISHES, whether or not anyone remembers the rule.

WHAT IT DOES. On SubagentStop for the wince agent:
  1. If Wince's final message overrules anyone ("overrule", "I say", "Wince
     says") but carries no ```overrule``` receipt block, Wince is sent back:
     add a receipt per overrule, or withdraw it.
  2. Each receipt (JSON in a ```overrule fence) must have `cell`,
     `overruled`, `their_words`, `their_rebuttal`, `evidence`. Both quotes must
     appear VERBATIM in that W's OWN output in this session's transcript: the
     result of an Agent call to that W, or its hand-back. Claude's own text
     (prompts, summaries it wrote) never counts, so a summary cannot launder
     a quote.
  3. On the second stop (`stop_hook_active`) it lets Wince finish but writes
     the overrule to ~/.claude/skyne/overrules.jsonl as `unbacked`, and
     wince_gate.py then refuses the main reply until Claude tells Garrett.

WHAT IT DOES NOT DO (house-rules 21 point 5). It proves the quotes are the W's
and the evidence was named, never that the judgement is right. An overrule
phrased with none of the trigger words gets past step 1. A W run as a generic
agent (no plugin) is invisible to it, as to every W hook.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from w_ran import member  # noqa: E402

TRIGGER = re.compile(r"\boverrul|\bI say\b|\bWince says\b", re.I)
FENCE = re.compile(r"```overrule\s*\n(.*?)```", re.S)
FIELDS = ("cell", "overruled", "their_words", "their_rebuttal", "evidence")


def log_path() -> str:
    return os.environ.get("SKYNE_OVERRULES_LOG") or os.path.join(
        os.path.expanduser("~"), ".claude", "skyne", "overrules.jsonl")


def norm(t) -> str:
    return re.sub(r"\s+", " ", str(t or "")).strip()


def receipts(message: str) -> list:
    out = []
    for body in FENCE.findall(message or ""):
        try:
            r = json.loads(body)
        except json.JSONDecodeError:
            out.append({"_bad": "a receipt is not valid JSON"})
            continue
        out.extend(r if isinstance(r, list) else [r])
    return out


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text(b.get("text") if isinstance(b, dict) and "text" in b
                               else b.get("content") if isinstance(b, dict) else b)
                         for b in content)
    return ""


def w_outputs(entries: list, w: str) -> str:
    """Everything W itself said this session: Agent results for W, W's hand-backs."""
    calls, out = {}, []
    for e in entries:
        content = (e.get("message") or {}).get("content")
        if e.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ("Agent", "Task"):
                    calls[b.get("id")] = member((b.get("input") or {}).get("subagent_type"))
        elif e.get("type") == "user":
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result" and calls.get(b.get("tool_use_id")) == w:
                        out.append(_text(b.get("content")))
            text = _text(content)
            # a background W's hand-back opens with its speaker label (house-rules 32)
            if "hand-back" in text.lower() and re.search(rf"\b{re.escape(w)}\s*:", text, re.I):
                out.append(text)
    return norm("\n".join(out))


def read_jsonl(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip().startswith("{")]
    except (OSError, json.JSONDecodeError):
        return []


def problems(message: str, entries: list) -> list[str]:
    rs = receipts(message)
    if not rs:
        return (["you overruled a W with no ```overrule receipt (wince.md rule 7)"]
                if TRIGGER.search(message or "") else [])
    out = []
    for r in rs:
        if "_bad" in r:
            out.append(r["_bad"])
            continue
        miss = [f for f in FIELDS if not r.get(f)]
        if miss:
            out.append(f"{r.get('cell', '?')}: missing {', '.join(miss)}")
            continue
        w = member(r["overruled"]) or str(r["overruled"]).lower()
        src = w_outputs(entries, w)
        if not src:
            out.append(f"{r['cell']}: no output from {w} in this session to check against")
            continue
        for f in ("their_words", "their_rebuttal"):
            if norm(r[f]) not in src:
                out.append(f"{r['cell']}: {f} is not in {w}'s own output: {str(r[f])[:60]!r}")
    return out


def decide(payload: dict, entries: list | None = None) -> dict | None:
    if payload.get("hook_event_name") not in (None, "SubagentStop"):
        return None
    if member(payload.get("agent_type")) != "wince":
        return None
    msg = str(payload.get("last_assistant_message") or "")
    if entries is None:
        entries = read_jsonl(str(payload.get("transcript_path") or ""))
    found = problems(msg, entries)
    if not found:
        return None
    if payload.get("stop_hook_active"):
        row = {"utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "session_id": payload.get("session_id"), "status": "unbacked", "problems": found}
        try:
            os.makedirs(os.path.dirname(log_path()), exist_ok=True)
            with open(log_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except OSError:
            pass
        return None
    return {"decision": "block", "reason":
            "Overrule receipt check (wince.md rule 7, ruled 2026-10-12): " + "; ".join(found)
            + ". For each verdict you overrule, add a ```overrule block with JSON: cell, "
              "overruled, their_words and their_rebuttal (VERBATIM from that W's own output), "
              "evidence (a path or ruling:<quote>). If you cannot back it, withdraw the overrule "
              "and leave the W's verdict standing."}


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

    wren_said = ("Strongest case: Exceed is Garrett's own tool and its pins already log what hurt him "
                 "in use, so Wren duplicates a feed. Does not win, because the pins react after "
                 "friction, while Wren walks the path before he does.")
    summary = "exceed NEEDED (weakest): tired-evening use; pins already log friction after the fact"
    entries = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Agent",
                                                       "input": {"subagent_type": "load-house-rules:wren", "prompt": "go"}}]}},
        {"type": "user", "toolUseResult": {}, "message": {"content": [{"type": "tool_result", "tool_use_id": "t1",
                                                                      "content": [{"type": "text", "text": "Wren: " + wren_said}]}]}},
        # Claude's own summary, written into a later prompt: must never count
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t2", "name": "Agent",
                                                       "input": {"subagent_type": "load-house-rules:wince", "prompt": summary}}]}},
    ]

    def stop(msg, **kw):
        return dict({"hook_event_name": "SubagentStop", "agent_type": "load-house-rules:wince",
                     "last_assistant_message": msg, "session_id": "s1"}, **kw)

    def fence(r):
        return "Wince: verdicts.\n```overrule\n" + json.dumps(r) + "\n```\n"

    check(decide(stop("Wince: grade 3/5. Nothing to overrule."), entries) is not None,
          "PLANTED: the word 'overrule' with no receipt is refused")
    check(decide(stop("Wince: grade 3/5, the output holds."), entries) is None,
          "a critique with no overrule passes")
    replay = {"cell": "exceed.wren", "overruled": "wren", "their_words": "pins already log friction",
              "their_rebuttal": "", "evidence": "x"}
    out = decide(stop(fence(replay)), entries)
    check(bool(out) and "missing their_rebuttal" in out["reason"],
          "REPLAY: the 2026-10-12 overrule with Wren's rebuttal dropped is refused")
    replay["their_rebuttal"] = "pins already log friction after the fact"
    out = decide(stop(fence(replay)), entries)
    check(bool(out) and "not in wren's own output" in out["reason"],
          "REPLAY: a quote that exists only in Claude's summary is refused (the summary does not count)")
    honest = {"cell": "exceed.wren", "overruled": "wren",
              "their_words": "its pins already log what hurt him in use",
              "their_rebuttal": "Does not win, because the pins react after friction",
              "evidence": "Skyne-Exceed/02 Pins"}
    check(decide(stop(fence(honest)), entries) is None, "an honest receipt with Wren's real words passes")
    check(decide(stop(fence(dict(honest, overruled="weir"))), entries) is not None,
          "PLANTED: quoting a W that produced nothing this session is refused")
    check(decide(stop("```overrule\n{not json\n```"), entries) is not None, "PLANTED: a broken receipt is refused")
    check(decide(dict(stop("I overrule wren"), agent_type="load-house-rules:wren"), entries) is None,
          "only Wince is gated")
    with tempfile.TemporaryDirectory() as d:
        os.environ["SKYNE_OVERRULES_LOG"] = os.path.join(d, "o.jsonl")
        check(decide(stop("I overrule wren", stop_hook_active=True), entries) is None
              and read_jsonl(os.environ["SKYNE_OVERRULES_LOG"])[0]["status"] == "unbacked",
              "second stop lets Wince finish but logs the overrule as unbacked")
        tp = os.path.join(d, "t.jsonl")
        with open(tp, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        r = subprocess.run([sys.executable, __file__], input=json.dumps(stop(fence(replay), transcript_path=tp)),
                           capture_output=True, text=True)
        check(r.returncode == 0 and '"block"' in r.stdout, "PLANTED: end to end through stdin, a block is printed, exit 0")
        r = subprocess.run([sys.executable, __file__], input="garbage", capture_output=True, text=True)
        check(r.returncode == 0 and r.stdout == "", "garbage stdin exits 0 silently")
        os.environ.pop("SKYNE_OVERRULES_LOG", None)
    print(f"\noverrule_gate self-test: {len(ran) - len(fails)} of {len(ran)} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
