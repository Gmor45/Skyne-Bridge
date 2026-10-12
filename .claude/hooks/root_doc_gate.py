#!/usr/bin/env python3
"""root_doc_gate — refuse a NEW loose doc at any repo's root.

WHY THIS EXISTS
---------------
Garrett, 2026-10-12, on opening Skyne:

    "the handoffs are a mess. There's tons of them, no consistent format, no
     storage ... Create an enforceable hook so that this doesn't pile up again
     ... I don't like loose docs outside of like README, gitignore, and the
     standard ones you'd find on the home page"

THE MISS. Skyne's root held 366 dated session reports (3.5 MB) because its own
README said "root-flat until it hurts" and the /handoff skill wrote one more
there every session. The estate standard listed what a repo must CARRY and
never what it must not, so nothing flagged a single one. Skyne fixed its own
copy (handoffs/, a project hook, a CI check), but a project hook only fires
when that repo is the session's root -- a session opened one folder up never
sees it. This plugin hook reaches every session with the plugin synced.

WHAT IT REFUSES, AND WHAT IT DOES NOT
-------------------------------------
Refuses: a Write that CREATES a .md/.txt/.markdown/.rst directly in a git
repo's top folder, when the name is not on the standard list.

Never refuses an edit to a file that already exists (old debt is govern.py's
job, reported as `no-loose-root-docs`, not a hook's -- a hook that fired on
every existing file would be switched off in a week, house-rules 21 point 5).
Never refuses in a repo whose .governance.json says `"kind": "vault"`: an
Obsidian vault's root notes are content, and the standard ranks this rule a
convention there. Fails open on every error path.

The rule's wording and reason live in Skyne's data/repo-standard.json, vendored
next to this file; --self-test fails if that copy stops carrying the rule.

    python3 .claude/hooks/root_doc_gate.py --self-test
"""
import json
import os
import sys
import tempfile

RULE_ID = "no-loose-root-docs"
VENDORED = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "repo-standard.json")
DOC_EXT = (".md", ".txt", ".markdown", ".rst")
ALLOWED = {
    "README.md", "LICENSE", "LICENSE.md", "LICENSE.txt", "CHANGELOG.md",
    "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md", "CLAUDE.md",
    "AGENTS.md", "Thread.md", "requirements.txt", "robots.txt",
}


def repo_root_of(path: str):
    """The folder holding `path` if that folder is a git repo's top, else None.
    `.git` may be a directory or (in a worktree) a file."""
    folder = os.path.dirname(os.path.abspath(path))
    return folder if os.path.exists(os.path.join(folder, ".git")) else None


def is_vault(root: str) -> bool:
    try:
        with open(os.path.join(root, ".governance.json"), encoding="utf-8") as f:
            return json.load(f).get("kind") == "vault"
    except (OSError, ValueError):
        return False


def refuses(path: str) -> bool:
    if not path:
        return False
    name = os.path.basename(path)
    if not name.lower().endswith(DOC_EXT) or name in ALLOWED:
        return False
    if os.path.exists(path):
        return False
    root = repo_root_of(path)
    return bool(root) and not is_vault(root)


def vendored_rule() -> dict:
    try:
        with open(VENDORED, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return {}
    return next((r for r in doc.get("rules", []) if r.get("id") == RULE_ID), {})


def message(name: str) -> str:
    r = vendored_rule()
    return (
        f"Refused: '{name}' would be a new loose doc at the repo root.\n\n"
        f"{r.get('rule', 'Reports, handoffs, plans and notes live in a folder.')}\n\n"
        f"{r.get('why', '')}\n\n"
        "Put it in a folder (Skyne: handoffs/cards/<id>.md, format in "
        "handoffs/README.md). Standard: repo-standard.json rule "
        f"'{RULE_ID}'."
    )


def run() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if (payload.get("tool_name") or "") != "Write":
        return 0
    path = (payload.get("tool_input") or {}).get("file_path") or ""
    try:
        if not refuses(path):
            return 0
    except Exception:
        return 0
    print(message(os.path.basename(path)), file=sys.stderr)
    return 2


def self_test() -> int:
    fails = []

    def check(ok, label):
        print("  %-60s %s" % (label, "ok" if ok else "FAIL"))
        if not ok:
            fails.append(label)

    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "repo")
        os.makedirs(os.path.join(repo, ".git"))
        os.makedirs(os.path.join(repo, "docs"))
        j = lambda *p: os.path.join(repo, *p)
        check(refuses(j("2026-10-12-a-session-report.md")),
              "PLANTED: a new dated report at the root is refused")
        check(refuses(j("notes.txt")), "PLANTED: a new .txt at the root is refused")
        check(not refuses(j("README.md")), "README.md is allowed")
        check(not refuses(j("Thread.md")), "Thread.md (house-rules 11) is allowed")
        check(not refuses(j("docs", "plan.md")), "a doc in a folder is allowed")
        check(not refuses(j("script.py")), "a non-doc file is allowed")
        with open(j("old-report.md"), "w") as f:
            f.write("x")
        check(not refuses(j("old-report.md")),
              "editing an EXISTING root doc is not refused (old debt)")
        check(not refuses(os.path.join(tmp, "not-a-repo.md")),
              "a folder that is not a repo top is ignored")
        with open(j(".governance.json"), "w") as f:
            json.dump({"kind": "vault"}, f)
        check(not refuses(j("New Note.md")), "a vault's root notes are allowed")
        check(not refuses(""), "an empty path is allowed (fails open)")

    r = vendored_rule()
    check(bool(r), f"the vendored standard still carries rule {RULE_ID!r}")
    check(bool(r.get("why")) and r.get("why", "") in message("x.md"),
          "the refusal quotes the STANDARD's reason")

    print("\nSELF-TEST " + ("FAILED" if fails else "PASSED"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    sys.exit(run())
