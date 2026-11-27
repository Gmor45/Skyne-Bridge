#!/usr/bin/env python3
"""PreToolUse hook: refuse to save a GitHub Actions workflow that would spend
minutes with nothing limiting it (house-rules 1g, "a new check pays its way").

WHY THIS EXISTS
---------------
All of Garrett's private repos share ONE pool of 3,000 Actions minutes a
month, and it went over four months running (Aug-Nov 2026). The only thing
standing between a chat and a costly workflow was a memory reminder that
pops up when a workflow file is written. On 2026-11-27 a repo created that
afternoon (whip-it) already had a check that re-ran on every push to every
PR and a weekly timer with no brake: the reminder was read past. Garrett,
asked how to make sure new repos never go over: "build it".

WHAT IT REFUSES
---------------
A Write / Edit / MultiEdit of `.github/workflows/*.yml` whose RESULT has:
  1. a `pull_request`, `pull_request_target` or `push` trigger with no
     `paths:` / `paths-ignore:` filter -- it re-runs on every push whatever
     changed (pushes to open PRs were 45% of November's minutes);
  2. a `schedule:` trigger with no ACTIONS_BRAKE guard -- the meter turns the
     brake on when the month is about to go over, and an unguarded timer
     keeps spending through it.
Either is allowed when the file says why, in a comment:
    # no-paths: this guard checks every file, so it cannot be filtered
    # no-brake: deploys must run even when the month is tight
The refusal costs one line to answer, so it never blocks real work. It only
blocks a check nobody thought about.

IT ONLY REFUSES WHAT THE EDIT ADDS
----------------------------------
22 older workflows already break one rule on purpose (data guards that must
see every file, deploy timers). Editing one of those for an unrelated reason
is not refused: the hook compares the file before and after, and refuses
only a problem the edit introduces.

WHAT IT CANNOT SEE
------------------
A workflow written by a shell command (a heredoc, a Python script) or on
GitHub's website never passes through Write/Edit. The daily sweep in the
actions-collector Worker (claude-usage-hud) reads every repo's workflows and
reports new breaks in the `actions_meter` reading; that is the backstop for
this hole. On any internal error it fails OPEN, like every hook here.

Usage:
    python3 workflow_gate.py                 # the hook (JSON on stdin)
    python3 workflow_gate.py --check FILE    # lint one workflow file
    python3 workflow_gate.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import sys

WORKFLOW_RE = re.compile(r"(^|/)\.github/workflows/[^/]+\.ya?ml$", re.I)
FILTERED = ("pull_request", "pull_request_target", "push")
NO_PATHS_RE = re.compile(r"#\s*no-paths:\s*\S.{4,}", re.I)
NO_BRAKE_RE = re.compile(r"#\s*no-brake:\s*\S.{4,}", re.I)
ON_RE = re.compile(r"""^(on|"on"|'on'|true)\s*:(.*)$""")


def _strip_comment(s: str) -> str:
    return re.sub(r"\s+#.*$", "", s).strip()


def triggers(text: str) -> dict[str, str]:
    """Each trigger under `on:` mapped to the text of its own settings
    ('' when it has none). Line-based on purpose: the hook must run on a bare
    python3 with no PyYAML, and workflow `on:` blocks are regular enough."""
    lines = text.replace("\r\n", "\n").split("\n")
    out: dict[str, str] = {}
    for i, line in enumerate(lines):
        m = ON_RE.match(line)
        if not m:
            continue
        rest = _strip_comment(m.group(2))
        if rest:  # on: push   /   on: [push, pull_request]   /   on: {push: ...}
            if rest.startswith("{"):
                for name, body in re.findall(r"(\w+)\s*:\s*(\{[^{}]*\}|\[[^\]]*\]|[^,}]*)", rest[1:]):
                    out[name] = body
            else:
                for name in re.findall(r"[A-Za-z_]+", rest):
                    out[name] = ""
            return out
        child = None
        current = None
        for raw in lines[i + 1:]:
            if not raw.strip() or raw.lstrip().startswith("#"):
                if current:
                    out[current] += raw + "\n"  # keep comments in the block
                continue
            indent = len(raw) - len(raw.lstrip())
            if indent == 0:
                break
            if child is None:
                child = indent
            body = raw.strip()
            if indent == child:
                lm = re.match(r"-\s*([A-Za-z_]+)\s*$", body)
                km = re.match(r"([A-Za-z_]+)\s*:(.*)$", body)
                if lm:
                    current = lm.group(1)
                    out[current] = ""
                elif km:
                    current = km.group(1)
                    out[current] = _strip_comment(km.group(2)) + "\n"
                continue
            if current:
                out[current] += body + "\n"
        return out
    return out


def problems(text: str) -> set[str]:
    """The set of rule breaks in one workflow file, as stable keys
    ('paths:pull_request', 'paths:push', 'brake') so a before/after
    comparison can tell an old break from a new one."""
    found: set[str] = set()
    trig = triggers(text)
    excused_paths = bool(NO_PATHS_RE.search(text))
    for name in FILTERED:
        if name not in trig:
            continue
        block = trig[name]
        if re.search(r"\bpaths(-ignore)?\s*:", block):
            continue
        if name == "push" and re.search(r"\btags(-ignore)?\s*:", block) and not re.search(r"\bbranches(-ignore)?\s*:", block):
            continue  # tag pushes only: a release, not every commit
        tm = re.search(r"\btypes\s*:\s*\[([^\]]*)\]", block)
        if name.startswith("pull_request") and tm and {t.strip(" '\"") for t in tm.group(1).split(",")} <= {"closed"}:
            continue  # once per PR, at close (branch cleanup)
        if not excused_paths:
            found.add(f"paths:{name}")
    if "schedule" in trig and "ACTIONS_BRAKE" not in text and not NO_BRAKE_RE.search(text):
        found.add("brake")
    return found


def explain(new: set[str], path: str) -> str:
    lines = [
        f"house-rules 1g -- not saved: {os.path.basename(path)} would spend GitHub Actions minutes with nothing limiting it. "
        "All of Garrett's private repos share ONE 3,000-minute pool a month, and it went over four months running.",
    ]
    for key in sorted(new):
        if key.startswith("paths:"):
            trig = key.split(":", 1)[1]
            lines.append(
                f"- `{trig}` has no `paths:` filter, so it re-runs on every push whatever changed. Add `paths:` "
                "listing the files this workflow actually tests. If it truly must run on every change (a guard that "
                "checks every file), put `# no-paths: <why>` in the file instead."
            )
        if key == "brake":
            lines.append(
                "- it has a `schedule:` but no brake. Add `if: vars.ACTIONS_BRAKE != 'true'` to each scheduled job "
                "(the meter switches the brake on when the month is about to go over). If it must never pause "
                "(a deploy), put `# no-brake: <why>` in the file instead."
            )
    lines.append("Then save again, and say in your reply roughly what it will cost a month (runs x minutes).")
    return "\n".join(lines)


def deny_payload(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def after_edit(tool: str, ti: dict, before: str) -> str | None:
    """The file's text once this tool call lands, or None when it cannot be
    worked out (then the hook stays out of the way)."""
    if tool == "Write":
        return ti.get("content") or ""
    edits = ti.get("edits") if tool == "MultiEdit" else [ti]
    text = before
    for e in edits or []:
        old, new = e.get("old_string", ""), e.get("new_string", "")
        if not old or old not in text:
            return None
        text = text.replace(old, new) if e.get("replace_all") else text.replace(old, new, 1)
    return text


def verdict(tool: str, ti: dict) -> str | None:
    path = str(ti.get("file_path") or "").replace("\\", "/")
    if tool not in ("Write", "Edit", "MultiEdit") or not WORKFLOW_RE.search(path):
        return None
    before = _read(ti.get("file_path"))
    after = after_edit(tool, ti, before)
    if after is None:
        return None
    new = problems(after) - problems(before)
    return explain(new, path) if new else None


def self_test() -> int:
    fails: list[str] = []

    def want(name: str, text: str, expect: set[str]) -> None:
        got = problems(text)
        if got != expect:
            fails.append(f"{name}: expected {sorted(expect)}, got {sorted(got)}")

    want("PR with no paths", "on:\n  pull_request:\njobs: {}\n", {"paths:pull_request"})
    want("PR with paths", "on:\n  pull_request:\n    paths: ['app/**']\njobs: {}\n", set())
    want("push to main, no paths", "on:\n  push:\n    branches: [main]\n", {"paths:push"})
    want("push and PR, only PR filtered", "on:\n  pull_request:\n    paths: [x]\n  push:\n    branches: [main]\n", {"paths:push"})
    want("tag pushes only", "on:\n  push:\n    tags: ['v*']\n", set())
    want("flow list", "on: [push, pull_request]\n", {"paths:push", "paths:pull_request"})
    want("bare scalar", "on: pull_request\n", {"paths:pull_request"})
    want("quoted on", '"on":\n  pull_request:\n', {"paths:pull_request"})
    want("flow map with paths", "on: {pull_request: {paths: [src]}}\n", set())
    want("closed PRs only", "on:\n  pull_request:\n    types: [closed]\n", set())
    want("dispatch only", "on:\n  workflow_dispatch:\n", set())
    want("timer, no brake", "on:\n  schedule:\n    - cron: '0 9 * * 1'\njobs:\n  a:\n    runs-on: x\n", {"brake"})
    want("timer, braked", "on:\n  schedule:\n    - cron: '0 9 * * 1'\njobs:\n  a:\n    if: vars.ACTIONS_BRAKE != 'true'\n", set())
    want("timer, excused", "# no-brake: deploys must run even when tight\non:\n  schedule:\n    - cron: '1 1 * * *'\n", set())
    want("PR excused with a reason", "# no-paths: guards every file in the repo\non:\n  pull_request:\n", set())
    want("PR excused with NO reason", "# no-paths:\non:\n  pull_request:\n", {"paths:pull_request"})
    want("comment inside on: block", "on:\n  # checks\n  pull_request:\n    paths: [x]\n", set())
    want("the whip-it ci.yml shape", "name: Checks\non:\n  pull_request:\n  push:\n    branches: [main]\njobs:\n  check: {}\n",
         {"paths:pull_request", "paths:push"})

    # Before/after: an old break is not this edit's fault; a new one is.
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, ".github", "workflows", "guard.yml")
    os.makedirs(os.path.dirname(p))
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("name: Guard\non:\n  pull_request:\njobs:\n  g:\n    runs-on: ubuntu-latest\n")
    if verdict("Edit", {"file_path": p, "old_string": "name: Guard", "new_string": "name: Data guard"}):
        fails.append("an unrelated edit to an old unfiltered guard must not be refused")
    r = verdict("Edit", {"file_path": p, "old_string": "on:\n", "new_string": "on:\n  schedule:\n    - cron: '0 3 * * *'\n"})
    if not r or "schedule" not in r or "ACTIONS_BRAKE" not in r:
        fails.append("adding an unbraked timer to an old file must be refused, naming the brake")
    if not verdict("Write", {"file_path": os.path.join(d, ".github", "workflows", "new.yml"), "content": "on: [pull_request]\n"}):
        fails.append("a brand-new unfiltered workflow must be refused")
    if verdict("Write", {"file_path": os.path.join(d, "notes.yml"), "content": "on: [pull_request]\n"}):
        fails.append("a yml outside .github/workflows must be ignored")
    if verdict("Edit", {"file_path": p, "old_string": "not in the file", "new_string": "x"}) is not None:
        fails.append("an edit that cannot apply must be left to the Edit tool (fail open)")
    if not verdict("MultiEdit", {"file_path": p, "edits": [{"old_string": "on:\n", "new_string": "on:\n  push:\n"}]}):
        fails.append("a MultiEdit must be checked too")
    # The path match itself, separately: a Windows path cannot be opened on
    # the Linux CI runner, so the read is tested above with the native path.
    if not WORKFLOW_RE.search(r"C:\repo\.github\workflows\ci.yml".replace("\\", "/")):
        fails.append("a Windows-style workflow path must match")

    pay = deny_payload("why")["hookSpecificOutput"]
    if pay.get("permissionDecision") != "deny" or pay.get("hookEventName") != "PreToolUse":
        fails.append("the refusal must be a PreToolUse deny")
    text = explain({"paths:pull_request", "brake"}, "x.yml")
    for must in ("1g", "paths:", "# no-paths:", "ACTIONS_BRAKE", "# no-brake:", "cost a month"):
        if must not in text:
            fails.append(f"the refusal must tell the chat {must!r}")

    if fails:
        for f in fails:
            print("FAIL", f)
        return 1
    print("workflow_gate self-test: all checks pass")
    return 0


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    if "--check" in sys.argv:
        path = sys.argv[sys.argv.index("--check") + 1]
        found = problems(_read(path))
        print(", ".join(sorted(found)) or "ok")
        sys.exit(1 if found else 0)
    try:
        payload = json.load(sys.stdin)
        reason = verdict(payload.get("tool_name", ""), payload.get("tool_input") or {})
    except Exception:
        sys.exit(0)  # fail open: never break a session over a workflow lint
    if reason:
        json.dump(deny_payload(reason), sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
