#!/usr/bin/env python3
"""PreToolUse hook: warn when a Write/Edit lands in the shared main checkout.

This mechanism enforces house-rules 1a.

WHY THIS WARNS AND NEVER BLOCKS
--------------------------------
Garrett was asked directly, choosing between a hard block and a warning, for
this exact rule: "Warn loudly, never block." A blocking version would refuse
every file edit made outside a worktree -- and this cloud session, this very
container, is a plain clone rather than a worktree. A hard gate would stop
every session shaped like this one from turn one, which is the coarse gate
house-rules 21 point 5 forbids.

WHAT IT DETECTS
----------------
Two conditions, both true, before it says anything:

    1. This checkout is NOT a git worktree. `git rev-parse --git-dir` and
       `--git-common-dir` are equal in an ordinary clone or the primary
       checkout; a worktree's git-dir lives under
       `<common-dir>/worktrees/<name>` and the two differ.
    2. HEAD is on a protected branch (main / master).

Both conditions matter. A worktree checked out to `main` is fine -- that is
what a worktree is FOR. A plain clone on a feature branch (this session,
right now) is also fine -- rule 1a's actual concern is a SHARED checkout
being edited while parallel sessions might also be using it, and a session's
own isolated feature branch is not that.

WHAT IT DELIBERATELY DOES NOT DO
----------------------------------
It cannot tell whether the checkout is genuinely SHARED with another live
session -- that is unobservable from inside one process. It only proves the
two structural facts above, which is what the rule's own worked failures
(publisher dead 8 runs, a stray file swept into an unrelated commit) share.

    python3 worktree_warn.py                    # the hook (JSON on stdin)
    python3 worktree_warn.py --check <cwd>
    python3 worktree_warn.py --self-test
"""
from __future__ import annotations

import json
import subprocess
import sys

PROTECTED = ("main", "master")


def _git(args, cwd):
    try:
        out = subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                             text=True, timeout=5)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def is_shared_main_checkout(cwd: str | None,
                            git=_git) -> tuple[bool, str | None]:
    """(is_it, branch). Fails closed to False -- an unreadable repo state
    must never warn on nothing, the same "could not look" is not "clean"
    stance house-rules 6c takes everywhere else."""
    git_dir = git(["rev-parse", "--git-dir"], cwd)
    common_dir = git(["rev-parse", "--git-common-dir"], cwd)
    if git_dir is None or common_dir is None:
        return False, None
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if branch is None or branch not in PROTECTED:
        return False, branch
    # normalise: a relative git-dir ('.git') and its absolute form must
    # compare equal for the worktree/plain-clone distinction to hold.
    is_worktree = git_dir.rstrip("/") != common_dir.rstrip("/") and (
        "worktrees" in git_dir)
    return (not is_worktree), branch


MESSAGE = (
    "house-rules 1a -- this edit is landing directly on the shared `%s` "
    "checkout, not a worktree. Use a worktree for this work, and leave this "
    "checkout clean and not ahead of origin before the session ends. This "
    "is a warning, not a refusal -- carry on if a worktree genuinely is not "
    "available here."
)


def warn_payload(branch: str) -> dict:
    text = MESSAGE % branch
    return {"systemMessage": text,
            "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "additionalContext": text}}


def run_hook(stream=None) -> int:
    raw = (stream or sys.stdin).read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0  # fail open: a malformed payload must never trap a session
    if not isinstance(payload, dict):
        return 0
    if payload.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
        return 0
    cwd = payload.get("cwd")
    try:
        shared, branch = is_shared_main_checkout(cwd)
    except Exception:
        return 0  # fail open: never break a session over a git call
    if shared and branch:
        json.dump(warn_payload(branch), sys.stdout)
    return 0


def self_test() -> int:
    fails = []

    def check(ok, msg):
        print(("  ok   " if ok else "  FAIL ") + msg)
        if not ok:
            fails.append(msg)

    # a fake git() so this never shells out to the real repo -- the real
    # repo's own state is not the thing under test here.
    def fake(git_dir, common_dir, branch):
        def g(args, cwd):
            if args[:2] == ["rev-parse", "--git-dir"]:
                return git_dir
            if args[:2] == ["rev-parse", "--git-common-dir"]:
                return common_dir
            if args[:2] == ["rev-parse", "--abbrev-ref"]:
                return branch
            return None
        return g

    # PLANTED, house-rules 6c: the real bug this hook exists to catch --
    # editing directly in the shared checkout while on main.
    shared, branch = is_shared_main_checkout(
        "/x", git=fake(".git", ".git", "main"))
    check(shared is True and branch == "main",
          "PLANTED: a plain clone on main is flagged as the shared checkout")

    # a WORKTREE on main is fine -- that is what a worktree is for.
    shared, _ = is_shared_main_checkout(
        "/x", git=fake("/x/.git/worktrees/w1", "/x/.git", "main"))
    check(shared is False, "a worktree checked out to main is NOT flagged")

    # a plain clone on a FEATURE branch is fine -- this session, right now.
    shared, _ = is_shared_main_checkout(
        "/x", git=fake(".git", ".git", "claude/some-task-7z"))
    check(shared is False, "a plain clone on a feature branch is NOT flagged")

    # an unreadable repo state must fail CLOSED (never warn on nothing).
    shared, _ = is_shared_main_checkout(
        "/x", git=lambda a, c: None)
    check(shared is False, "an unreadable repo state does not warn")

    # the payload never carries permissionDecision -- this is a warning,
    # never a block, and that is the whole point of Garrett's ruling.
    got = warn_payload("main")
    check("permissionDecision" not in json.dumps(got),
          "the payload must NOT carry permissionDecision -- that would block")
    check(got["hookSpecificOutput"]["hookEventName"] == "PreToolUse",
          "the payload names the PreToolUse event")
    check("worktree" in got["systemMessage"].lower(),
          "the message actually says what to do")

    # NOTE, found live 2026-09-16: this self-test used to assert the real
    # checkout was NOT flagged, on the assumption a session always runs it
    # from a feature branch. That assumption broke the moment a session
    # legitimately checked out `main` to read something -- the self-test's
    # own PASS/FAIL then depended on which branch happened to be checked
    # out at test time, which is exactly the unstable-fact-as-check shape
    # house-rules 6a warns about. The real checkout is now DESCRIBED, never
    # asserted -- the fixture-based cases above already prove the LOGIC in
    # isolation, which is the thing a self-test should be testing.
    real_shared, real_branch = is_shared_main_checkout(".")
    print(f"  info this session's real checkout: branch={real_branch!r} "
          f"flagged={real_shared}")

    if fails:
        print(f"self-test: {len(fails)} FAILURE(S)")
        return 1
    print("self-test: PASS")
    return 0


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    if "--check" in sys.argv:
        idx = sys.argv.index("--check")
        cwd = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        shared, branch = is_shared_main_checkout(cwd)
        print((MESSAGE % branch) if shared else "(clean)")
        sys.exit(0)
    sys.exit(run_hook())


if __name__ == "__main__":
    main()
