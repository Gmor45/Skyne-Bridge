#!/usr/bin/env python3
"""tier_gate_golden.py -- the cases tier_gate.py cannot rewrite.

Garrett, 2026-10-10, granting Claude permission to edit its own tier gate:
"we explore guard rails to try and limit the risk of claude grading itself."

tier_gate.py's own --self-test lives inside the file Claude is allowed to
edit, so a session could weaken the gate and its tests in one change. This
runner and tier-gate-golden.json sit OUTSIDE that permission
(Edit(**/.claude/hooks/tier_gate.py) only), so they still need the auto-mode
classifier or Garrett to change. CI runs it on every push.

Three checks, all deterministic (no model is called):
  1. every fixed case in tier-gate-golden.json gives the expected result
  2. the invariants: a medium/large mismatch is never silently allowed in any
     mode, and with SKYNE_TIER_GATE unset run() never blocks
  3. a ratchet: tier_gate.py --self-test passes AND reports at least
     `min_self_test_checks` checks -- deleting a check fails CI

Usage:
  python3 .claude/hooks/tier_gate_golden.py               # all three
  python3 .claude/hooks/tier_gate_golden.py --no-count    # skip 3 (the
      self-test writes a /bin/sh stub, so it cannot run on Windows)
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tier_gate  # noqa: E402

GOLDEN = os.path.join(HERE, "tier-gate-golden.json")


def fixed(grade: dict):
    return lambda _t: dict(grade, why="golden fixture", grader="golden")


def output_kind(out) -> str:
    if out is None:
        return "none"
    if out.get("decision") == "block":
        return "block"
    return "context"


def run_cases(golden: dict) -> list[str]:
    fails = []
    for c in golden["cases"]:
        row, _state, out = tier_gate.decide(c["prompt"], c["model"], c["effort"], {},
                                            fixed(c["grade"]), mode=c["mode"])
        exp, name = c["expect"], c["name"]
        if "action" in exp and row.get("action") != exp["action"]:
            fails.append(f"{name}: action {row.get('action')!r}, expected {exp['action']!r}")
        if "verdict" in exp and row.get("verdict") != exp["verdict"]:
            fails.append(f"{name}: verdict {row.get('verdict')!r}, expected {exp['verdict']!r}")
        if "output" in exp and output_kind(out) != exp["output"]:
            fails.append(f"{name}: output {output_kind(out)!r}, expected {exp['output']!r}")
        text = json.dumps(out or {})
        for s in exp.get("contains", []):
            if json.dumps(s)[1:-1] not in text:
                fails.append(f"{name}: output does not contain {s!r}")
    return fails


def run_invariants() -> list[str]:
    fails = []
    msg = "please audit every promise in the repo and fix the ones that fail today"
    for mode in ("route", "block", "warn"):
        for size in ("medium", "large"):
            for cur, rec in ((("claude-sonnet-5-5", "medium"), ("opus", "high")),
                             (("claude-opus-5-5", "high"), ("haiku", "low"))):
                row, _s, out = tier_gate.decide(msg, cur[0], cur[1], {},
                                                fixed({"model": rec[0], "effort": rec[1], "size": size}),
                                                mode=mode)
                if row.get("action") not in ("delegate", "block", "warn") or out is None:
                    fails.append(f"invariant: {mode}/{size} {cur[0]}->{rec[0]} was let through "
                                 f"silently (action {row.get('action')!r})")

    # the log keeps the opening tag Skyne's miss detector reads -- and only the tag
    for raw, want in (('<agent-message from="x">long text', "<agent-message"),
                      ("[SYSTEM NOTIFICATION - NOT USER INPUT] x", "[SYSTEM NOTIFICATION"),
                      ("please rename the files", None)):
        if tier_gate.prompt_tag(raw) != want:
            fails.append(f"invariant: prompt_tag({raw[:20]!r}) = {tier_gate.prompt_tag(raw)!r}, want {want!r}")

    # with the knob unset, run() never blocks
    saved = {k: os.environ.pop(k, None) for k in ("SKYNE_TIER_GATE", "SKYNE_TIER_GATE_LOG",
                                                  "SKYNE_TIER_GATE_CHILD", "CLAUDE_EFFORT",
                                                  "SKYNE_TIER_GATE_SYNC")}
    real = tier_gate.make_grader
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.environ["SKYNE_TIER_GATE_LOG"] = os.path.join(tmp, "tier-gate.jsonl")
            os.environ["CLAUDE_EFFORT"] = "medium"
            os.environ["SKYNE_TIER_GATE_SYNC"] = "1"   # grade inline, so the patched grader is the one used
            tr = os.path.join(tmp, "t.jsonl")
            with open(tr, "w") as f:
                f.write(json.dumps({"type": "assistant",
                                    "message": {"model": "claude-sonnet-5-5", "content": "ok"}}) + "\n")
            tier_gate.make_grader = lambda *a, **k: fixed({"model": "opus", "effort": "high", "size": "large"})
            out = tier_gate.run({"prompt": msg, "session_id": "golden", "transcript_path": tr})
            if (out or {}).get("decision") == "block":
                fails.append("invariant: with SKYNE_TIER_GATE unset, run() BLOCKED a message")
        finally:
            tier_gate.make_grader = real
            for k, v in saved.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v
    return fails


def run_count(golden: dict) -> list[str]:
    floor = int(golden.get("min_self_test_checks") or 0)
    cp = subprocess.run([sys.executable, os.path.join(HERE, "tier_gate.py"), "--self-test"],
                        capture_output=True, text=True)
    m = re.search(r"(\d+) checks passed", cp.stdout)
    if cp.returncode != 0 or not m:
        return [f"tier_gate.py --self-test failed (exit {cp.returncode}): "
                + (cp.stdout + cp.stderr).strip()[-400:]]
    n = int(m.group(1))
    print(f"tier_gate.py --self-test: {n} checks (floor {floor})")
    if n < floor:
        return [f"ratchet: tier_gate.py --self-test ran {n} checks, below the floor of {floor} "
                "-- a check was deleted. Raising or lowering the floor is Garrett's call."]
    return []


def main() -> int:
    with open(GOLDEN, encoding="utf-8") as f:
        golden = json.load(f)
    fails = run_cases(golden) + run_invariants()
    if "--no-count" not in sys.argv:
        fails += run_count(golden)
    for x in fails:
        print("GOLDEN FAIL:", x)
    print(f"tier_gate_golden: {len(golden['cases'])} cases, "
          f"{'FAILED ' + str(len(fails)) if fails else 'all passed'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
