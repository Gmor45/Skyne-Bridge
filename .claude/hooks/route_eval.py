#!/usr/bin/env python3
"""route_eval.py -- the W router's exam: does Haiku pick the right bucket?

Garrett, 2026-10-05: *"How are we testing each trigger fires at the right
time? Are there prompts that could cause it to misfire?"*

`tier_gate.py --self-test` proves the PLUMBING with fixed fake grades: a
small job is never routed, a block is never routed, an invented bucket is
none. It cannot prove the grader picks the RIGHT bucket, because the grader
is a model. This is that half. It sends every prompt in `route-corpus.json`
through the real grader -- the same `haiku_grade()` call and system prompt the
hook uses -- and compares the bucket it names with the bucket(s) the row
expects. Rows marked `trap` use one W's keyword inside another W's job
("check out this villain idea", "make sure the night shift ran") because a
router only ever shown easy prompts is a router nobody has seen fail.

    python3 route_eval.py                 # run the exam (needs the `claude` CLI; ~$0.003 a prompt)
    python3 route_eval.py --workers 8     # in parallel
    python3 route_eval.py --self-test     # corpus shape + scoring, no model

Prints accuracy overall, on traps, and per bucket, then every miss. Exit 0
when it ran (a low score is a FINDING, reported, not a crash); exit 2 when it
could not grade at all -- "could not run" must never read as "scored 0" or
"passed".

The live half is Skyne's `scripts/w_triggers.py --logs`: routed vs. ran,
per member, on real messages. This file is the exam; that is the field record.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tier_gate  # noqa: E402

CORPUS = os.path.join(HERE, "route-corpus.json")
BUCKETS = tier_gate.W_AGENTS + ("none",)


def load(path=CORPUS) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["rows"]


def corpus_errors(rows) -> list[str]:
    errs = []
    seen = set()
    for i, r in enumerate(rows):
        p = str(r.get("prompt", "")).strip()
        if len(p.split()) <= tier_gate.SHORT_WORDS:
            errs.append(f"row {i}: {p!r} is {len(p.split())} words -- the gate never grades a message that short")
        if p in seen:
            errs.append(f"row {i}: duplicate prompt")
        seen.add(p)
        exp = r.get("expect") or []
        if not exp or any(e not in BUCKETS for e in exp):
            errs.append(f"row {i}: expect {exp!r} must be a non-empty list of {BUCKETS}")
    for w in BUCKETS:
        if not any(w in r.get("expect", []) for r in rows):
            errs.append(f"no row expects {w!r} -- that bucket is never examined")
    if not any(r.get("trap") for r in rows):
        errs.append("no trap rows -- an exam of easy prompts cannot show a misfire")
    return errs


def score(rows, answers) -> dict:
    """answers[i] = the bucket graded for rows[i], or None when grading failed."""
    graded = [(r, a) for r, a in zip(rows, answers) if a is not None]
    hits = [(r, a) for r, a in graded if a in r["expect"]]
    traps = [(r, a) for r, a in graded if r.get("trap")]
    per = {}
    for w in BUCKETS:
        mine = [(r, a) for r, a in graded if r["expect"][0] == w]
        per[w] = (sum(1 for r, a in mine if a in r["expect"]), len(mine))
    return {"total": len(rows), "graded": len(graded), "right": len(hits),
            "trap_right": sum(1 for r, a in traps if a in r["expect"]), "traps": len(traps),
            "per": per,
            "misses": [{"prompt": r["prompt"], "expect": r["expect"], "got": a, "trap": r.get("trap")}
                       for r, a in graded if a not in r["expect"]],
            "failed": [r["prompt"] for r, a in zip(rows, answers) if a is None]}


def grade_one(prompt: str):
    g = tier_gate.haiku_grade(prompt, "", timeout=60)
    return None if g.get("error") else g.get("w", "none")


def report(s) -> None:
    pct = lambda a, b: f"{round(100 * a / b)}%" if b else "n/a"
    print(f"W router exam: {s['right']} of {s['graded']} right ({pct(s['right'], s['graded'])})"
          f"; traps {s['trap_right']} of {s['traps']} ({pct(s['trap_right'], s['traps'])})"
          f"; {len(s['failed'])} could not be graded")
    for w, (a, b) in s["per"].items():
        print(f"  {w:<8} {a}/{b}")
    if s["misses"]:
        print(f"\nMisses ({len(s['misses'])}) -- each is a prompt that would be sent to the wrong agent:")
        for m in s["misses"]:
            print(f"  - got {m['got']!r}, wanted {'/'.join(m['expect'])}: {m['prompt']}"
                  + (f"   [trap: {m['trap']}]" if m["trap"] else ""))
    for p in s["failed"]:
        print(f"  ? not graded: {p}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    rows = load()
    errs = corpus_errors(rows)
    if errs:
        print("corpus is malformed:\n  " + "\n  ".join(errs))
        return 2
    if not tier_gate.claude_bin():
        print("NOT RUN -- no `claude` CLI on this machine, so the real grader cannot be asked. Not a score.")
        return 2
    with cf.ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        answers = list(ex.map(grade_one, [r["prompt"] for r in rows]))
    s = score(rows, answers)
    if a.json:
        print(json.dumps(s, indent=2))
    else:
        report(s)
    if s["graded"] == 0:
        print("NOT RUN -- every grading call failed. Not a score.")
        return 2
    return 0


def self_test() -> int:
    ran, fails = [], []

    def check(ok, label):
        ran.append(label)
        if not ok:
            fails.append(label)

    rows = load()
    check(corpus_errors(rows) == [], "the real corpus is well-formed (every bucket examined, traps present, no short rows)")
    check(len(rows) >= 30, "the exam has at least 30 prompts")
    check(sum(1 for r in rows if r.get("trap")) >= 5, "the exam carries at least 5 traps")
    check(any("no row expects 'whittle'" in e for e in corpus_errors([r for r in rows if "whittle" not in r["expect"]])),
          "a corpus that never examines a bucket is refused")
    check(any("no trap rows" in e for e in corpus_errors([dict(r, trap=None) for r in rows])),
          "a corpus with no traps is refused")
    check(any("words" in e for e in corpus_errors(rows + [{"prompt": "fix it", "expect": ["warden"]}])),
          "a prompt too short to be graded is refused")
    two = [{"prompt": "a", "expect": ["warden"]}, {"prompt": "b", "expect": ["wick"], "trap": "x"},
           {"prompt": "c", "expect": ["weir", "wistin"]}]
    s = score(two, ["warden", "warden", "wistin"])
    check(s["right"] == 2 and s["traps"] == 1 and s["trap_right"] == 0,
          "scoring credits any listed answer and counts a missed trap")
    check(s["misses"] == [{"prompt": "b", "expect": ["wick"], "got": "warden", "trap": "x"}],
          "a miss names the prompt, what was wanted and what was got")
    s = score(two, [None, None, None])
    check(s["graded"] == 0 and s["right"] == 0 and len(s["failed"]) == 3,
          "ungraded rows are failures to grade, never wrong answers")
    check(set(BUCKETS) == set(tier_gate.W_AGENTS) | {"none"}, "the exam's buckets are the router's buckets")

    if fails:
        for f in fails:
            print("SELF-TEST FAIL:", f)
        print(f"route_eval self-test: {len(fails)} FAILED")
        return 1
    print(f"route_eval self-test: {len(ran)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
