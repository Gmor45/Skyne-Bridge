#!/usr/bin/env python3
"""PreToolUse hook: warn when a chat is about to push AGAIN to a branch that
already has an open pull request (house-rules 1f, "finish before you push").

WHY THIS EXISTS
---------------
Every push to a branch with an open PR re-runs all of that PR's checks. In
November 2026 that was 1,456 of 3,624 GitHub Actions minutes (45%), the
single biggest cause of the fourth month over the shared 3,000-minute pool.
Merging, the thing everyone worried about, was under 1%. Measured the day
this was built: one Bluelink branch ran its checks 38 times in one day, and
another was pushed 7 times in a morning while a chat fixed things one at a
time. Rule 1f already said "run the checks locally, then push once". It was
a sentence with nothing behind it. Garrett, 2026-11-27: "do 1f".

WHAT IT DOES
------------
For a `git push` to a non-protected branch, it asks GitHub two things:
  1. does this branch have an OPEN pull request?  (no PR -> pushes are free,
     rule 1, say nothing)
  2. how many earlier pushes already ran that PR's checks?  (distinct head
     commits among the branch's `pull_request` workflow runs)
When this push would be the THIRD or later, it warns, naming the PR, the
count, and what to do instead. The first fix-up push after review is normal;
the third is the pattern that cost the minutes.

WHY IT WARNS AND DOES NOT REFUSE
--------------------------------
no_push_to_main.py refuses because "does this push to main?" is a string and
pushing to main is never right. "Is this push one too many?" is a judgement:
a push that fixes a red check IS the right move, and a gate that blocks it
gets deleted. So the strongest honest rung here is a warning that arrives at
the exact moment the push is about to happen (rule 21's ladder: a hook, but a
warning one).

WHAT IT CANNOT SEE
------------------
It needs `gh` signed in and reachable. On any failure (no gh, no network, not
a GitHub remote, unparsable command) it fails OPEN and says nothing, like
every hook in this plugin. It cannot see pushes made outside the Bash tool's
command string. Protected-branch pushes are left to no_push_to_main.py.

Usage:
    python3 push_count_gate.py                  # the hook (JSON on stdin)
    python3 push_count_gate.py --check "<cmd>"  # dry-run against the real repo
    python3 push_count_gate.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from no_push_to_main import PROTECTED, SPLIT_RE, current_branch, destinations  # noqa: E402

WARN_FROM = 2          # this many earlier pushes already ran checks -> warn
GH_TIMEOUT = 8


def _run(args: list[str], cwd: str | None = None) -> str | None:
    try:
        out = subprocess.run(args, cwd=cwd or None, capture_output=True, text=True,
                             timeout=GH_TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def origin_of(cwd: str | None) -> str | None:
    """"owner/repo" of the checkout's origin, or None."""
    url = _run(["git", "remote", "get-url", "origin"], cwd)
    if not url:
        return None
    m = re.search(r"github\.com[:/]([^/:\s]+)/([^/\s]+?)(?:\.git)?/?$", url.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def open_pr(repo: str, branch: str) -> int | None:
    """The open PR number for this head branch, or None."""
    out = _run(["gh", "pr", "list", "-R", repo, "--head", branch, "--state", "open",
                "--json", "number", "-q", ".[0].number"])
    out = (out or "").strip()
    return int(out) if out.isdigit() else None


def pushes_with_checks(repo: str, branch: str) -> int | None:
    """How many distinct commits on this branch already ran PR checks."""
    out = _run(["gh", "run", "list", "-R", repo, "--branch", branch, "--event",
                "pull_request", "--limit", "100", "--json", "headSha"])
    if out is None:
        return None
    try:
        return len({r.get("headSha") for r in json.loads(out) if r.get("headSha")})
    except (ValueError, AttributeError):
        return None


def push_targets(command: str, cwd: str | None, branch_lookup=current_branch):
    """[(effective cwd, branch)] for every `git push` in the command that
    writes a non-protected branch. Tracks `cd X &&` and `git -C X`."""
    hits = []
    here = cwd
    for seg in SPLIT_RE.split(command or ""):
        try:
            toks = shlex.split(seg.strip(), comments=True)
        except ValueError:
            continue
        if len(toks) >= 2 and toks[0] == "cd":
            here = toks[1] if os.path.isabs(toks[1]) or not here else os.path.join(here, toks[1])
            continue
        if "git" not in toks or "push" not in toks or toks.index("git") > toks.index("push"):
            continue
        where = here
        gi = toks.index("git")
        if gi + 2 < len(toks) and toks[gi + 1] == "-C":
            where = toks[gi + 2]
        if "--delete" in toks or "-d" in toks or "--tags" in toks:
            continue
        dests = destinations(toks)
        if dests is None:
            b = branch_lookup(where)
            dests = [b] if b else []
        for d in dests:
            if d and d not in PROTECTED and d != "HEAD":
                hits.append((where, d))
    return hits


def warning(repo: str, branch: str, pr: int, earlier: int) -> str:
    n = earlier + 1
    return (
        f"house-rules 1f -- this is push #{n} to {repo} PR #{pr} (branch {branch}). "
        f"Every push to an open PR re-runs ALL its checks: the {earlier} earlier "
        f"push(es) already did. Re-pushing to open PRs was 45% of November's "
        f"GitHub Actions minutes (1,456 of 3,624).\n"
        f"If more fixes are coming, commit them locally, run the repo's checks "
        f"locally, and push ONCE at the end. If this push fixes a red check, go "
        f"ahead. This is a warning, not a refusal."
    )


def verdict(command: str, cwd: str | None = None, branch_lookup=current_branch,
            origin=origin_of, pr_lookup=open_pr, count=pushes_with_checks) -> str | None:
    if not command or "push" not in command:
        return None
    for where, branch in push_targets(command, cwd, branch_lookup):
        repo = origin(where)
        if not repo:
            continue
        pr = pr_lookup(repo, branch)
        if pr is None:
            continue  # no open PR: a push fires nothing (rule 1)
        earlier = count(repo, branch)
        if earlier is not None and earlier >= WARN_FROM:
            return warning(repo, branch, pr, earlier)
    return None


def warn_payload(text: str) -> dict:
    # Same two channels as shell_shapes.py: additionalContext for the model on
    # recent builds, systemMessage for older ones.
    return {"systemMessage": text,
            "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "additionalContext": text}}


def self_test() -> int:
    fails = []
    on_feature = lambda _c: "claude/fix-x"      # noqa: E731
    on_main = lambda _c: "main"                 # noqa: E731
    origin = lambda _c: "Gmor45/Project-Bluelink"  # noqa: E731
    has_pr = lambda _r, _b: 140                 # noqa: E731
    no_pr = lambda _r, _b: None                 # noqa: E731

    def v(cmd, earlier, pr=has_pr, branch=on_feature, org=origin):
        return verdict(cmd, "/repo", branch, org, pr, lambda _r, _b: earlier)

    # the case it exists for: third push to an open PR
    w = v("git push", 2)
    if not w:
        fails.append("third push to an open PR must warn")
    for must in ("1f", "#3", "PR #140", "push ONCE", "not a refusal"):
        if must not in (w or ""):
            fails.append(f"warning must contain {must!r}")
    if not v("git push origin claude/fix-x", 7):
        fails.append("eighth push with an explicit branch must warn")
    if not v("cd /repo && git add -A && git commit -m x && git push", 3):
        fails.append("a push after cd/commit in one command must warn")
    if not v("git -C /some/repo push -u origin claude/fix-x", 2):
        fails.append("git -C push must warn")

    # what it must leave alone
    if v("git push", 0) or v("git push", 1):
        fails.append("first and second push must stay quiet")
    if v("git push", 9, pr=no_pr):
        fails.append("a branch with no open PR must stay quiet (pushes are free)")
    if v("git push", 9, branch=on_main) or v("git push origin main", 9):
        fails.append("protected branches are no_push_to_main.py's job, not this one")
    if v("git push origin --delete claude/fix-x", 9):
        fails.append("deleting a branch must stay quiet")
    if v("git push", 9, org=lambda _c: None):
        fails.append("a non-GitHub remote must fail open")
    if v("git push", None):
        fails.append("an unknown count (gh failed) must fail open")
    for quiet in ("git fetch origin", "echo 'git push'", "git status", ""):
        if v(quiet, 9):
            fails.append(f"must stay quiet on {quiet!r}")
    for junk in ('git push "unbalanced', "git push $(", "\x00"):
        try:
            v(junk, 9)
        except Exception as exc:  # pragma: no cover
            fails.append(f"must not raise on {junk!r}: {exc}")

    # the payload must be a shape the harness surfaces
    p = warn_payload("x")
    if p.get("hookSpecificOutput", {}).get("additionalContext") != "x" or p.get("systemMessage") != "x":
        fails.append("payload must carry the text on both channels")
    if "permissionDecision" in p.get("hookSpecificOutput", {}):
        fails.append("a warning must never carry a permission decision")

    if fails:
        for f in fails:
            print("SELF-TEST FAIL:", f)
        return 1
    print("push_count_gate self-test: all cases passed")
    return 0


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    if "--check" in sys.argv:
        i = sys.argv.index("--check")
        print(verdict(sys.argv[i + 1] if i + 1 < len(sys.argv) else "", os.getcwd()) or "(quiet)")
        sys.exit(0)
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw else {}
        if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
            sys.exit(0)
        ti = payload.get("tool_input") or {}
        text = verdict((ti.get("command") if isinstance(ti, dict) else "") or "", payload.get("cwd"))
    except Exception:
        sys.exit(0)  # fail open: never break a session over a push count
    if text:
        json.dump(warn_payload(text), sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
