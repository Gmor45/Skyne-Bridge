#!/usr/bin/env python3
"""SessionStart hook, delivered as a plugin — not as claude-audit's own hook.

WHY THIS FILE EXISTS HERE AND NOT IN claude-audit
--------------------------------------------------
claude-audit already has a SessionStart hook (`scripts/session_start.py`,
registered in its own `.claude/settings.json`) and it is good — it prints
live miss-ledger and architecture-gap counts, not a static reminder. The
problem was never its content. The problem is reachability.

Claude Code on the web resolves a repo's `.claude/settings.json` relative to
the SESSION'S PROJECT DIRECTORY. When a session attaches several repos side
by side (this session: /home/user/Gartera-Vault, /home/user/claude-audit,
/home/user/claude-bootstrap), the project directory is their PARENT, and
claude-audit's settings.json is just a file in a subdirectory — never
discovered, whatever its `command` field says. `$CLAUDE_PROJECT_DIR` is
unset in that shape (verified live, 2026-09-01), so even the hook's own
fallback chain (`$CLAUDE_PROJECT_DIR/scripts/... || claude-audit/scripts/...
|| scripts/...`) never runs at all, because nothing invokes it.

This has cost four recorded misses on one date (2026-09-01) alone, the
sharpest being a session that proposed deleting a workaround by using the
exact bug the workaround exists to route around — because it never loaded
the rules that already say not to.

THE FIX: A PLUGIN HOOK, NOT A REPO HOOK
----------------------------------------
`hooks/reply_gate.py` in this same plugin already proves the fix. It fires
in EVERY session with `load-house-rules` installed, regardless of which
repos are attached or what the project directory looks like, because it is
keyed off `${CLAUDE_PLUGIN_ROOT}` — the plugin's own install path — not off
project-relative resolution. A plugin hook does not care what shape the
session's sources are in. That is the entire fix. Nothing about
claude-audit's session_start.py needed to change; it needed a caller that
can always find it.

WHAT THIS SCRIPT DOES
----------------------
1. Reads the SessionStart hook's stdin JSON for the real `cwd` (the CLI
   supplies it; do not guess from `$CLAUDE_PROJECT_DIR`, which this exact
   failure shape leaves unset).
2. Looks for a claude-audit checkout: first `cwd` itself (a session whose
   *only* source is claude-audit), then cwd's immediate subdirectories (a
   multi-repo session) — matching on the presence of
   `scripts/session_start.py` alongside `data/misses.json`, so a
   similarly-named unrelated directory cannot false-positive.
3. If found: run IT and pass its output through verbatim. This is a
   caller, not a reimplementation — the rules and the live counts still
   live in exactly one place, per this plugin's own no-duplication rule.
4. If not found: say so plainly and tell the session to load the skill
   anyway (the skill can clone the private repo itself) rather than
   silently proceeding with no rules loaded at all — the exact failure
   this whole arrangement exists to stop.

Bounded, fails open, never blocks a session start.
"""
import json
import os
import subprocess
import sys

TIMEOUT_SECONDS = 12
MAX_SEARCH_DEPTH_NOTE = "cwd and its immediate children only — this is a nudge, not a filesystem crawl"


def _read_stdin_cwd():
    """The hook's stdin JSON carries the session's real cwd. Fall back to
    os.getcwd() only if stdin is empty or unparseable — never guess a path."""
    try:
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
            cwd = data.get("cwd")
            if cwd and os.path.isdir(cwd):
                return cwd
    except Exception:
        pass
    return os.getcwd()


def _looks_like_claude_audit(path):
    """Marker-based, not name-based — a session could clone it under any
    directory name. Two files together are the signature; either alone is
    too common to trust."""
    return (
        os.path.isfile(os.path.join(path, "scripts", "session_start.py"))
        and os.path.isfile(os.path.join(path, "data", "misses.json"))
    )


def find_claude_audit(cwd):
    """Return an absolute path to a claude-audit checkout reachable from this
    session, or None. Checks cwd itself first (single-source session), then
    cwd's immediate children (multi-repo session — the shape that broke)."""
    if _looks_like_claude_audit(cwd):
        return cwd
    try:
        entries = sorted(os.listdir(cwd))
    except OSError:
        return None
    for name in entries:
        candidate = os.path.join(cwd, name)
        if os.path.isdir(candidate) and _looks_like_claude_audit(candidate):
            return candidate
    return None


def run_upstream_hook(audit_root):
    """Invoke claude-audit's own session_start.py by absolute path. It
    resolves its OWN root from `__file__`, so calling it from any cwd is
    safe — this function is a caller, not a second copy of its logic."""
    script = os.path.join(audit_root, "scripts", "session_start.py")
    result = subprocess.run(
        [sys.executable or "python3", script],
        capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
    )
    out = (result.stdout or "").strip()
    return out if out else None


def not_found_message(cwd):
    return "\n".join([
        "=== load-house-rules plugin · SessionStart ===",
        "",
        "The brain repo (skyne, formerly claude-audit; spelled skine for one day)",
        "is not reachable from this session (checked cwd and its immediate",
        f"children under {cwd}, by content — any of those directory names would",
        "have matched).",
        "",
        "LOAD THE RULES ANYWAY: Skill('house-rules'). It can clone the private",
        "repo itself. Do not proceed on any of Gmor45's repos, or on git, commits,",
        "PRs, model/effort choice, or cost, without them loaded first.",
        "",
        "If this is unexpected — the brain repo genuinely IS attached — say so",
        "plainly rather than silently continuing with no rules: this nudge could",
        "not find it and the mismatch is itself worth reporting.",
        "=== end ===",
    ])


def brief():
    cwd = _read_stdin_cwd()
    audit_root = find_claude_audit(cwd)
    if audit_root is None:
        return not_found_message(cwd)
    try:
        upstream = run_upstream_hook(audit_root)
    except Exception as e:
        upstream = None
        degraded_reason = f"{type(e).__name__}: {e}"
    else:
        degraded_reason = None
    if upstream:
        return upstream
    # claude-audit was found but its own hook produced nothing or errored —
    # still never leave the session with zero nudge to load the rules.
    msg = [
        "=== load-house-rules plugin · SessionStart ===",
        "",
        f"Found the brain repo at {audit_root}, but its own session_start.py",
        "produced no output" + (f" ({degraded_reason})" if degraded_reason else "") + ".",
        "",
        "LOAD THE RULES ANYWAY: Skill('house-rules').",
        "=== end ===",
    ]
    return "\n".join(msg)


def self_test():
    import tempfile
    fails = []

    # 1. claude-audit at cwd itself (single-source session)
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "scripts"))
        os.makedirs(os.path.join(tmp, "data"))
        with open(os.path.join(tmp, "scripts", "session_start.py"), "w") as f:
            f.write("print('hi from upstream')\n")
        with open(os.path.join(tmp, "data", "misses.json"), "w") as f:
            f.write("{}")
        found = find_claude_audit(tmp)
        if found != tmp:
            fails.append("must find claude-audit when cwd IS the checkout")
        try:
            out = run_upstream_hook(found)
        except Exception as e:
            out = None
            fails.append(f"run_upstream_hook raised on a good checkout: {e}")
        if out != "hi from upstream":
            fails.append(f"must pass upstream stdout through verbatim, got {out!r}")

    # 2. claude-audit as a sibling directory (the multi-repo shape that broke)
    with tempfile.TemporaryDirectory() as parent:
        audit_dir = os.path.join(parent, "claude-audit")
        os.makedirs(os.path.join(audit_dir, "scripts"))
        os.makedirs(os.path.join(audit_dir, "data"))
        with open(os.path.join(audit_dir, "scripts", "session_start.py"), "w") as f:
            f.write("print('sibling case')\n")
        with open(os.path.join(audit_dir, "data", "misses.json"), "w") as f:
            f.write("{}")
        os.makedirs(os.path.join(parent, "some-other-repo"))
        found = find_claude_audit(parent)
        if found != audit_dir:
            fails.append("must find claude-audit as a sibling of other attached repos")

    # 3. not found anywhere -> must say so plainly, never proceed silently
    with tempfile.TemporaryDirectory() as empty:
        os.makedirs(os.path.join(empty, "unrelated-repo"))
        found = find_claude_audit(empty)
        if found is not None:
            fails.append("must not false-positive on a directory with neither marker file")
        msg = not_found_message(empty)
        if "Skill('house-rules')" not in msg:
            fails.append("not-found path must still tell the session to load the skill")
        if "not reachable" not in msg:
            fails.append("not-found path must say plainly that it could not find claude-audit")

    # 4. a marker file alone (no sibling) must not false-positive
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "scripts"))
        with open(os.path.join(tmp, "scripts", "session_start.py"), "w") as f:
            f.write("print('should not run')\n")
        # no data/misses.json
        if _looks_like_claude_audit(tmp):
            fails.append("one marker file alone must not be treated as a real checkout")

    if fails:
        for f in fails:
            print("SELF-TEST FAIL:", f)
        return 1
    print("self-test: 8 cases passed")
    return 0


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        print(brief())
    except Exception as e:  # never fail a session start
        print("=== load-house-rules plugin · SessionStart ===")
        print("LOAD THE RULES ANYWAY: Skill('house-rules').")
        print(f"(session_start.py nudge degraded: {type(e).__name__}: {e})")
    sys.exit(0)


if __name__ == "__main__":
    main()
