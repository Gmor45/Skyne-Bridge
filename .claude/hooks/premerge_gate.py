#!/usr/bin/env python3
"""PreToolUse hook: refuse merging a Skyne PR until its checks passed LOCALLY.

WHY THIS EXISTS
---------------
2026-11-20, after the third month over the 3,000 included GitHub Actions
minutes. Lean mode (2026-10-19) stopped running Skyne's full checks on pull
requests to save minutes and moved them to a nightly run on main. Two days
later main went red and stayed red every night, because a check that runs
AFTER the merge can only describe the breakage. Garrett's go, same day: run
the checks before merging, on the session's own computer, where they cost
nothing.

Skyne's `scripts/premerge.py` runs the CI steps locally and stamps
`.git/premerge-pass.json` with the HEAD it checked. This hook refuses
`gh pr merge` (including `--auto`) and the GitHub MCP merge / auto-merge tools
on a Gmor45/Skyne PR unless that stamp exists in the checkout and matches HEAD.

WHAT IT REFUSES
---------------
    gh pr merge 1068 --auto --squash          (cwd is a Skyne checkout)
    gh pr merge https://github.com/Gmor45/Skyne/pull/1068 --squash
    cd ~/Skyne && gh pr merge --auto
    mcp__github__merge_pull_request / enable_pr_auto_merge with repo Skyne
...when the stamp is missing, unreadable, or names a different commit. And a
Skyne merge started from a directory that is not a Skyne checkout, because
there is no stamp to read there.

WHAT IT LETS THROUGH
--------------------
Merges in every other repo; `gh pr merge --disable-auto`; `gh pr view`,
`gh pr checks` and other read commands that merely name a merge.

NO OVERRIDE, ON PURPOSE
-----------------------
Same standing as no_push_to_main.py: an escape hatch Claude can set is
decoration. The refusal names the one command that clears it.

WHAT IT CANNOT SEE, STATED PLAINLY
----------------------------------
- It compares the stamp to the checkout's HEAD, not to the PR's head on
  GitHub: a branch pushed from elsewhere after the stamp is not noticed.
- A merge made by anything other than these tool calls (the GitHub web page,
  a script, the hosted Skyne server's own mcp-store merges) is not seen.
- It fails OPEN on an unparsable command or payload, like every hook in this
  plugin, so it narrows the failure rather than closing it (house-rules 21.5).

Usage:
    python3 premerge_gate.py                  # the hook (JSON on stdin)
    python3 premerge_gate.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

TARGET = ("gmor45", "skyne")
STAMP_NAME = "premerge-pass.json"
SPLIT_RE = re.compile(r"&&|\|\||;|\||\n")
MCP_MERGE_RE = re.compile(r"(merge_pull_request|enable_pr_auto_merge)$")
PR_URL_RE = re.compile(r"github\.com/([^/\s]+)/([^/\s]+)/pull/\d+", re.I)


def _norm(owner: str | None, repo: str | None) -> tuple[str, str]:
    return ((owner or "").lower(), (repo or "").lower().removesuffix(".git"))


def origin_of(cwd: str | None) -> tuple[str, str] | None:
    """(owner, repo) of the checkout's origin remote, or None."""
    try:
        out = subprocess.run(["git", "remote", "get-url", "origin"], cwd=cwd or None,
                             capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", out.stdout.strip())
    return _norm(m.group(1), m.group(2)) if m else None


def stamp_state(cwd: str | None) -> str | None:
    """None when the stamp matches HEAD, else the reason it does not."""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd or None,
                              capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL).stdout.strip()
        gitdir = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=cwd or None,
                                capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "could not read this checkout's HEAD"
    path = os.path.join(gitdir, STAMP_NAME)
    try:
        with open(path, encoding="utf-8") as f:
            stamp = json.load(f)
    except FileNotFoundError:
        return "premerge.py has not passed in this checkout"
    except (OSError, ValueError):
        return "the premerge stamp is unreadable"
    if stamp.get("head") != head:
        return (f"the last local pass was for {str(stamp.get('head'))[:10]}, "
                f"but HEAD is now {head[:10]}")
    return None


def bash_targets(command: str, cwd: str | None, origin=origin_of) -> list[tuple[tuple[str, str] | None, str | None]]:
    """[(repo or None-if-unknown, effective cwd)] for every `gh pr merge` that merges."""
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
        if "gh" not in toks:
            continue
        rest = toks[toks.index("gh") + 1:]
        if rest[:2] != ["pr", "merge"] or "--disable-auto" in rest:
            continue
        repo = None
        for i, t in enumerate(rest):
            if t in ("-R", "--repo") and i + 1 < len(rest):
                o, _, r = rest[i + 1].rpartition("/")
                repo = _norm(o.rsplit("/", 1)[-1], r)
            elif t.startswith("--repo="):
                o, _, r = t.split("=", 1)[1].rpartition("/")
                repo = _norm(o.rsplit("/", 1)[-1], r)
            else:
                m = PR_URL_RE.search(t)
                if m:
                    repo = _norm(m.group(1), m.group(2))
        hits.append((repo or origin(here), here))
    return hits


def verdict(payload: dict, origin=origin_of, stamp=stamp_state) -> str | None:
    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}
    cwd = payload.get("cwd")
    checks: list[tuple[tuple[str, str] | None, str | None]] = []
    if tool == "Bash":
        checks = bash_targets(ti.get("command") or "", cwd, origin)
    elif MCP_MERGE_RE.search(tool):
        checks = [(_norm(ti.get("owner"), ti.get("repo") or ti.get("repository")), cwd)]
    for repo, where in checks:
        if repo != TARGET:
            continue
        if origin(where) != TARGET:
            return refusal("this merge is not being run from a Skyne checkout, so there is no local pass to read")
        why = stamp(where)
        if why:
            return refusal(why)
    return None


def refusal(why: str) -> str:
    return (
        f"Refused: merging a Skyne PR needs its checks to have passed locally first ({why}).\n"
        "Since lean mode (2026-10-19) GitHub runs only the ledger check on Skyne PRs, and main "
        "went red two days later and stayed red. Running the checks here costs no Actions minutes.\n"
        "Do this, in the checkout of the PR branch: `python3 scripts/premerge.py`. It runs the CI "
        "steps, blocks only on failures that are new on this branch, and stamps HEAD. Then merge.\n"
        "There is deliberately no override (Garrett, 2026-11-20)."
    )


def deny_payload(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def self_test() -> int:
    SK, OTHER = TARGET, ("gmor45", "tangle")

    def origin(where):
        return {"/sk": SK, "/sk/sub": SK, "/tg": OTHER}.get(where)

    def good(_):
        return None

    def missing(_):
        return "premerge.py has not passed in this checkout"

    def bash(cmd, cwd="/sk"):
        return {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd}

    must_block = [
        ("auto-merge from a Skyne checkout, no stamp", bash("gh pr merge 12 --auto --squash"), missing),
        ("by URL from elsewhere", bash("gh pr merge https://github.com/Gmor45/Skyne/pull/12 --squash", "/tg"), good),
        ("-R from a non-Skyne dir", bash("gh pr merge 12 -R Gmor45/Skyne --squash", "/tg"), good),
        ("--repo= form", bash("gh pr merge 12 --repo=Gmor45/skyne", "/tg"), good),
        ("after a cd into Skyne, no stamp", bash("cd /sk && gh pr merge --auto", "/tg"), missing),
        ("chained after other commands", bash("git push -u origin x && gh pr merge 3 --auto"), missing),
        ("MCP merge tool", {"tool_name": "mcp__github__merge_pull_request",
                            "tool_input": {"owner": "Gmor45", "repo": "Skyne"}, "cwd": "/sk"}, missing),
        ("MCP auto-merge tool", {"tool_name": "mcp__skyne__enable_pr_auto_merge",
                                 "tool_input": {"owner": "gmor45", "repo": "skyne"}, "cwd": "/sk"}, missing),
    ]
    must_allow = [
        ("stamp matches HEAD", bash("gh pr merge 12 --auto --squash"), good),
        ("another repo, no stamp", bash("gh pr merge 61 -R Gmor45/Tangle --squash", "/sk"), missing),
        ("another repo by cwd", bash("gh pr merge 61 --squash", "/tg"), missing),
        ("turning auto-merge OFF", bash("gh pr merge 12 --disable-auto"), missing),
        ("reading, not merging", bash("gh pr view 12 && gh pr checks 12"), missing),
        ("a string that only mentions it", bash("echo 'run gh pr merge later'"), missing),
        ("MCP merge in another repo", {"tool_name": "mcp__github__merge_pull_request",
                                       "tool_input": {"owner": "Gmor45", "repo": "Tangle"}, "cwd": "/sk"}, missing),
        ("unrelated tool", {"tool_name": "Write", "tool_input": {"file_path": "x"}, "cwd": "/sk"}, missing),
    ]
    bad = []
    for name, p, st in must_block:
        if verdict(p, origin, st) is None:
            bad.append(f"must BLOCK: {name}")
    for name, p, st in must_allow:
        if verdict(p, origin, st) is not None:
            bad.append(f"must ALLOW: {name}")
    total = len(must_block) + len(must_allow)
    for b in bad:
        print("  " + b)
    print(f"premerge_gate self-test: {total - len(bad)} of {total} passed")
    return 1 if bad else 0


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw else {}
    except Exception:
        sys.exit(0)  # fail open
    if not isinstance(payload, dict):
        sys.exit(0)
    try:
        reason = verdict(payload)
    except Exception:
        sys.exit(0)  # fail open: never break a session over a parse
    if reason:
        json.dump(deny_payload(reason), sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
