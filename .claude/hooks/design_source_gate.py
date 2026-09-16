#!/usr/bin/env python3
"""PreToolUse hook: refuse a design edit until its governing source was opened.

WHY THIS EXISTS
---------------
House-rules rule 38 — "Designing anything? One door, and it is this table" —
is rule 33's 26th instance, and as of 2026-09-15 it is ITS OWN THIRD BREAK IN
ONE DAY, all three about Skyne-Loom's visual surface:

  1. A rail's colour was recommended as "an open decision" without checking
     whether it was already answered. It was — `Codex/Config/Palette.md`
     already carries a validated, protanopia-checked sibling hue ring.
  2. A whole rail was built and Loom's look judged without opening either
     source that governs it — the Feature Roadmap Garrett wrote for Loom, or
     the locked Pin Card format spec, both cited BY NAME in files already
     read that session.
  3. `check_design.py` — the estate's own automated design gate — had never
     once been pointed at Loom's built page.

All three are filed `stale-source` / `knew-didnt-connect`. Rule 38's own text
already names the failure exactly: *"nothing can tell that a sentence was
written from a summary rather than a source."* This hook is the thing that
can tell. It answers one factual question from the session's OWN transcript,
not from a claim: before writing to a file that carries Garrett's visual
design, did THIS session actually open the doc that rules it?

WHAT IT REFUSES
----------------
A `Write`, `Edit` or `MultiEdit` to a short, explicit set of files that ARE
the visual surface — `render.py`, `editor_ui.py`, `tokens.css`,
`build_tokens.py`, `build_icons.py`, `make_icon.py`, anything under a
`brand/` directory, or any `.css` file — when the transcript shows no prior
read of the doc rule 38's own table says governs it:

    what the file/content is                 doc required (rule 38's table)
    ----------------------------------        --------------------------------
    ANY edit to one of the files above        DESIGN.md              (baseline)
    `render.py` / `editor_ui.py` itself       Skyne Console — Design Record.md
                                               + Dashboard Design Philosophy.md
    `@keyframes` / `transition:` / `animation:` in the content
                                               Braid Panel — Build Spec.md
    `tokens.css` / `build_tokens.py` / a `brand/` path
                                               BRANDING.md
    a hex colour near "sibling" or "accent"   Palette.md

WHY A DENY, NOT A NOTE
------------------------
Rule 21's ladder ranks a hard gate above a reminder when the check is a fact,
not a judgement — the same reasoning `no_push_to_main.py` already uses for
"does this push to main". "Did THIS session Read this doc" is the same
shape: answerable from the transcript with no interpretation needed. Rule
38's table is loaded into every session, every turn, as house-rules text, and
did not fire three times running — a note is demonstrably not the tier this
rule needs.

WHAT COUNTS AS "READ"
------------------------
A `Read` tool_use whose `file_path` basename matches (dashes, en-dashes,
spaces and case all ignored), OR a `Bash` tool_use whose `command` string
contains that doc's exact basename. The second channel is not a fallback —
it is how every doc in rule 38's own table was actually read, during the
session that built this hook, because the governing docs live in
`Gartera-Vault` and `Skyne`, not necessarily checked out beside whichever
repo is being edited, and a cross-repo read routinely goes through
`gh api .../contents/<path>` rather than the `Read` tool.

WHAT IT DELIBERATELY DOES NOT COVER (house-rules 21 point 5)
--------------------------------------------------------------
It cannot see a session that read the doc through neither channel — recalled
it from an earlier session, or from training. It does not cover rule 38's
Feature Roadmap row: "did you open your OWN product's roadmap before scoping
a whole feature" is a planning question with no reliable file/content signal
that exists BEFORE the edit, and stays a judgement call outside this
mechanism's reach. And it only fires on the narrow file list above —
widening the trigger to "any file with a hex string in it" would fire on
this very file's own self-test fixtures inside a day and get deleted, the
exact false-positive death every hook in this plugin names by name.

NO OVERRIDE, ON PURPOSE
------------------------
Same standing as `no_push_to_main.py` and this estate's other write-surface
guards. If skipping the doc is genuinely right here, that is Garrett's call
to make, not Claude's to grant itself.

Usage:
    python3 design_source_gate.py                  # the hook (JSON on stdin)
    python3 design_source_gate.py --self-test
"""
from __future__ import annotations

import json
import re
import sys
from urllib.parse import unquote

# -- rule 38's own table, reused rather than re-derived ---------------------
DESIGN_MD = "DESIGN.md"
CONSOLE_RECORD = "Skyne Console — Design Record.md"
DASHBOARD_PHIL = "Dashboard Design Philosophy.md"
BRAID_SPEC = "Braid Panel — Build Spec.md"
BRANDING = "BRANDING.md"
PALETTE = "Palette.md"

INSTRUMENT_FILES = {"render.py", "editor_ui.py"}
TOKEN_FILES = {"tokens.css", "build_tokens.py", "build_icons.py", "make_icon.py"}

HEX_RE = re.compile(r"#[0-9a-fA-F]{3}(?:(?:[0-9a-fA-F]{3})(?:[0-9a-fA-F]{2})?)?\b")
MOTION_RE = re.compile(r"@keyframes|transition\s*:|animation\s*:", re.IGNORECASE)
SIBLING_RE = re.compile(r"\bsibling\b|\baccent\b", re.IGNORECASE)


def _basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _norm(name: str) -> str:
    """A doc name, reduced to a bare comparison key.

    Dashes (hyphen and every en/em-dash variant), spaces and case all drop
    out, and the extension goes with them, so `Skyne Console — Design
    Record.md`, `skyne-console-design-record.md` and a `Bash` command that
    only ever typed a plain hyphen all collapse to the same key.
    """

    name = _basename(name)
    name = re.sub(r"\.(md|css|py)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[\u2010-\u2015_\-\s]+", "", name)
    return name.lower()


def is_design_file(path: str) -> bool:
    base = _basename(path)
    if base in INSTRUMENT_FILES or base in TOKEN_FILES:
        return True
    if "/brand/" in ("/" + path.replace("\\", "/").lower()):
        return True
    return base.lower().endswith(".css")


def required_docs(path: str, content: str) -> list[str]:
    """Which docs rule 38's table says this edit needs, in table order."""

    if not is_design_file(path):
        return []
    base = _basename(path)
    content = content or ""
    docs = [DESIGN_MD]
    if base in INSTRUMENT_FILES:
        docs += [CONSOLE_RECORD, DASHBOARD_PHIL]
    if MOTION_RE.search(content):
        docs.append(BRAID_SPEC)
    if base in TOKEN_FILES or "/brand/" in ("/" + path.replace("\\", "/").lower()):
        docs.append(BRANDING)
    if SIBLING_RE.search(content) and HEX_RE.search(content):
        docs.append(PALETTE)
    seen: set[str] = set()
    out: list[str] = []
    for d in docs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def read_transcript(path: str) -> list[dict]:
    entries = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return entries


ALL_DOCS = (DESIGN_MD, CONSOLE_RECORD, DASHBOARD_PHIL, BRAID_SPEC, BRANDING, PALETTE)


def docs_read(entries: list[dict] | None) -> set[str]:
    """Every design doc this session has evidence of having opened."""

    found: set[str] = set()
    for e in entries or []:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for blk in content:
            if not isinstance(blk, dict) or blk.get("type") != "tool_use":
                continue
            name = blk.get("name")
            inp = blk.get("input") or {}
            if name == "Read":
                fp = inp.get("file_path") or ""
                if fp:
                    found.add(_norm(fp))
            elif name == "Bash":
                # `gh api .../Console%20%E2%80%94%20Design%20Record.md` never
                # contains the literal doc name -- it contains its URL escape.
                # Un-quoting once is enough for both `%20` and a UTF-8-encoded
                # em-dash; a command with no escapes decodes to itself.
                cmd = unquote(inp.get("command") or "")
                for doc in ALL_DOCS:
                    if doc in cmd or doc.replace("—", "-") in cmd:
                        found.add(_norm(doc))
    return found


def verdict(path: str, content: str, entries: list[dict]) -> str | None:
    """The refusal reason, or None to allow.

    Pure apart from `entries`, so the self-test exercises the real function
    against a fabricated transcript rather than a real file on disk.
    """

    need = required_docs(path, content)
    if not need:
        return None
    have = docs_read(entries)
    missing = [d for d in need if _norm(d) not in have]
    if not missing:
        return None
    lines = [
        f"Refused: {path} is part of Garrett's visual surface, and house-rules "
        f"rule 38 names what governs it. This session has not opened:",
    ]
    for d in missing:
        lines.append(f"  - {d}")
    lines.append(
        "Rule 38 is rule 33's 26th instance and this is its third break in one "
        "day, all about Loom's look. Open the file(s) above, then retry the edit."
    )
    lines.append("There is deliberately no override.")
    return "\n".join(lines)


def deny_payload(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _content_of(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Write":
        return tool_input.get("content") or ""
    if tool_name == "Edit":
        return (tool_input.get("new_string") or "") + "\n" + (tool_input.get("old_string") or "")
    if tool_name == "MultiEdit":
        edits = tool_input.get("edits") or []
        return "\n".join(
            (e.get("new_string") or "") for e in edits if isinstance(e, dict)
        )
    return ""


def self_test() -> int:
    fails: list[str] = []

    def mk_read(path: str) -> dict:
        return {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": path}}
            ]},
        }

    def mk_bash(cmd: str) -> dict:
        return {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": cmd}}
            ]},
        }

    def refuse(path, content, entries, why):
        got = verdict(path, content, entries)
        if got is None:
            fails.append(f"must REFUSE ({why}): {path}")

    def allow(path, content, entries, why):
        got = verdict(path, content, entries)
        if got is not None:
            fails.append(f"must ALLOW ({why}): {path} -> {got!r}")

    # -- the three real 2026-09-15 misses, planted as regression fixtures --
    refuse(
        "loom/render.py", "background: #d98d37; border-radius: 8px;", [],
        "the rail-and-console miss -- no doc read at all",
    )
    allow(
        "loom/render.py", "background: #d98d37; border-radius: 8px;",
        [
            mk_read("C:/x/DESIGN.md"),
            mk_read("C:/x/Skyne Console — Design Record.md"),
            mk_read("C:/x/Dashboard Design Philosophy.md"),
        ],
        "all three required docs were read",
    )
    refuse(
        "brand/loom/tokens.css", "--rail-accent: #987aca; /* sibling hue */", [],
        "the sibling-colour miss -- BRANDING and Palette both unread",
    )
    allow(
        "brand/loom/tokens.css", "--rail-accent: #987aca; /* sibling hue */",
        [
            mk_read("x/DESIGN.md"),
            mk_read("Skyne/assets/brand/skyne/BRANDING.md"),
            mk_bash("curl .../Codex/Config/Palette.md"),
        ],
        "DESIGN.md, BRANDING via Read, Palette via a Bash fetch",
    )

    # -- the baseline: an instrument file needs its docs even with no colour
    refuse(
        "loom/render.py", "def add(a, b): return a + b", [],
        "an instrument file with no colour signal still owes DESIGN.md + the "
        "console docs -- rule 38's table names the FILE, not the diff",
    )
    allow(
        "loom/render.py", "def add(a, b): return a + b",
        [
            mk_read("x/DESIGN.md"),
            mk_read("x/Skyne Console - Design Record.md"),
            mk_read("x/Dashboard Design Philosophy.md"),
        ],
        "baseline satisfied even with no colour in this particular edit",
    )

    # -- false positives: the thing that gets every gate here deleted -------
    allow(
        "scripts/some_backend.py", "return {'a': 1}", [],
        "no design signal, and not one of the named files at all",
    )
    allow(
        "README.md", "background: #d98d37; border-radius: 8px", [],
        "a markdown file describing colours in PROSE must never trigger",
    )
    allow(
        "tests/test_design_source_gate.py", "assert '#d98d37' in css", [],
        "this hook's own test fixtures must never trigger on themselves",
    )
    allow(
        "loom/editor_ui.py", "x = 1",
        [
            mk_read("x/DESIGN.md"),
            mk_bash("gh api repos/Gmor45/Gartera-Vault/contents/Vault%20Ops/"
                    "Skyne%20Console%20%E2%80%94%20Design%20Record.md"),
            mk_read("x/Dashboard Design Philosophy.md"),
        ],
        "the console doc read via a gh api Bash call, not the Read tool",
    )

    # -- dash / case normalisation --------------------------------------------
    if _norm("Skyne/.claude/skills/house-rules/DESIGN.md") != _norm("design.md"):
        fails.append("normalise must reduce a full path to its bare basename key")
    if _norm("Skyne Console — Design Record.md") != _norm("skyne-console-design-record.md"):
        fails.append("em-dash and hyphen must normalise identically")

    # -- fail-open plumbing ----------------------------------------------------
    try:
        verdict("loom/render.py", None, [])  # type: ignore[arg-type]
    except Exception as exc:  # pragma: no cover
        fails.append(f"must not raise on None content: {exc}")
    try:
        verdict("loom/render.py", "#fff", None)  # type: ignore[arg-type]
    except Exception as exc:  # pragma: no cover
        fails.append(f"must not raise on None entries: {exc}")

    payload = deny_payload("because")
    hso = payload.get("hookSpecificOutput", {})
    if hso.get("hookEventName") != "PreToolUse":
        fails.append("deny payload must name the PreToolUse event")
    if hso.get("permissionDecision") != "deny":
        fails.append("deny payload must carry permissionDecision=deny")

    reason = verdict("loom/render.py", "background:#d98d37", [])
    for must in ("rule 38", "no override"):
        if must.lower() not in (reason or "").lower():
            fails.append(f"refusal text must contain {must!r}")

    if fails:
        for f in fails:
            print("SELF-TEST FAIL:", f)
        return 1
    print("self-test: 14 cases passed")
    return 0


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)  # fail open: no stdin, or unparsable
    if not isinstance(payload, dict):
        sys.exit(0)

    tool_name = payload.get("tool_name")
    if tool_name not in ("Write", "Edit", "MultiEdit"):
        sys.exit(0)
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or ""
    if not path:
        sys.exit(0)

    content = _content_of(tool_name, tool_input)
    entries = read_transcript(payload.get("transcript_path") or "")

    try:
        reason = verdict(path, content, entries)
    except Exception:
        sys.exit(0)  # fail open: never break a session over a string scan

    if reason:
        json.dump(deny_payload(reason), sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
