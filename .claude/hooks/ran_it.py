"""Did you run it? Refuses a "works / fixed / passes" claim about code that was
changed this turn and never run afterwards.

WHY THIS EXISTS
---------------
Garrett, 2026-10-05: *"one of the things I often do is challenge claude or the
W agents to prove their work."* Measured that day: of 437 logged misses,
Garrett caught 175 -- more than every script (51) and the night shift (37)
together -- and the second-largest family he catches is
`assert-without-measure` (40): Claude said a thing worked without measuring
it. House-rules 0 has said *"Never say something works unless you ran it.
'Should work' is a lie with extra steps"* since August, as a line of prose.
This is the cheap half of his "prove it", made countable so it fires without
him: a script, not a second persona grading its own homework (the 2026-09-09
ruling that a "Watcher" persona cannot do this job).

WHAT IT CHECKS
--------------
Three facts, all read from the turn's own tool calls and the reply, none a
judgement call:

1. A CODE file was changed this turn -- Edit / Write / MultiEdit /
   NotebookEdit, or a Bash command that writes one (`sed -i`, `> x.py`,
   `tee`). Markdown and plain text are not code: a typo fix cannot "work".
2. The reply claims it works -- "works now", "fixed", "tests pass", "is
   green", "verified", or the hedge "should work".
3. Nothing RAN after the last such change. A run is a Bash command with at
   least one segment that executes something (python3, pytest, node, make,
   bash, ./x ...) rather than only reading or moving files (cat, grep, ls,
   git add/commit/push ...), or a tool that reports on a run (a CI check, a
   subagent that may have run it).

All three true -> the turn is refused, with the file named.

WHAT IT DELIBERATELY DOES NOT CHECK (house-rules 21 point 5)
------------------------------------------------------------
- Whether the run PASSED. A failed command is often the point (a planted
  failure, a grep with no hits), so "the last command errored" fires on
  ordinary work. Rule 0's other half -- claiming green over a red run -- is
  uncovered here and said so.
- Whether the run tested the RIGHT thing. `python3 -c 1` after an edit counts
  as a run. This narrows "never ran anything" to zero; it does not prove the
  claim.
- A claim about work from an EARLIER turn. No edit this turn, nothing to tie
  the claim to, so it stays silent rather than guess.
- An honest disclosure passes on purpose: "I didn't run it" / "untested" is
  exactly the sentence rule 0 wants instead of the claim.

WHY IT LIVES BESIDE reply_gate.py RATHER THAN AS ITS OWN HOOK
-------------------------------------------------------------
Same reason as date_claims.py: it checks the REPLY, which reply_gate.py
already owns, and plugging in as one more complaint keeps one Stop hook, one
re-prompt cap, and one fail-open path. It is the only copy -- nothing in
skyne scans live turns, so there is no twin to keep in sync.

Usage:
    python3 ran_it.py --self-test
"""

from __future__ import annotations

import re
import sys

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# Extensions where "it works" is a claim about behaviour. Docs are excluded on
# purpose: firing on "fixed the typo" in a README is the coarse gate that gets
# a check switched off.
CODE_EXT = (
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".sh", ".bash",
    ".yml", ".yaml", ".json", ".jsonc", ".toml", ".html", ".htm", ".css",
    ".sql", ".go", ".rs", ".rb", ".php", ".java", ".kt", ".swift", ".c",
    ".cc", ".cpp", ".h", ".ipynb", ".svg",
)

# Tools whose call means something was run or a run's result was read. A
# subagent counts because it may well have run the thing, and guessing wrong
# in the firing direction costs a false refusal.
RUN_TOOLS = {"Agent", "Task", "Monitor", "Workflow"}
RUN_TOOL_RX = re.compile(
    r"(actions_get|actions_list|get_check_run|get_job_logs|actions_run_trigger)$")

# First words of a shell segment that only read, move or record files.
# Anything NOT in here is treated as executing something, so an unfamiliar
# command counts as a run -- the silent direction.
PASSIVE = {
    "cat", "ls", "head", "tail", "grep", "rg", "egrep", "find", "wc", "echo",
    "printf", "pwd", "cd", "which", "type", "sleep", "true", "false", "diff",
    "sort", "uniq", "cut", "tr", "awk", "sed", "less", "more", "file", "stat",
    "du", "df", "mkdir", "rm", "mv", "cp", "touch", "chmod", "ln", "tee",
    "basename", "dirname", "realpath", "date", "env", "export", "set",
    "unset", "test", "[", "jq", "xargs", "column", "nl", "base64",
    "sha256sum", "md5sum", "git",
}
# git subcommands that execute project code are rare; `git` is passive.

WRITES_CODE_RX = re.compile(
    r"(?:\bsed\s+-i\b[^|;&]*?|>>?\s*|\btee\s+(?:-a\s+)?)"
    r"['\"]?([\w./~${}-]+(?:%s))\b" % "|".join(re.escape(e) for e in CODE_EXT))

CLAIM_RX = [
    re.compile(r"\b(?:it|this|that|everything|all of it|the \w+(?: \w+)?)\s+"
               r"(?:now\s+)?works\b", re.I),
    re.compile(r"\bworks\s+(?:now|again|fine|correctly|perfectly)\b", re.I),
    re.compile(r"\b(?:is|are|now)\s+(?:fixed|working|green|passing)\b", re.I),
    re.compile(r"(?:^|[.!:;]\s+|\n\s*[-*]?\s*)(?:fixed|done)\s*(?:[.!,:—-]|$)",
               re.I | re.M),
    re.compile(r"\b(?:tests?|checks?|self-tests?|suite|build|ci|gate)\s+"
               r"(?:all\s+)?(?:pass(?:es|ed)?|passing|(?:is|are)\s+green)\b",
               re.I),
    re.compile(r"\ball\s+\d+(?:/\d+)?\s+(?:checks?|tests?|cases?)\s+pass", re.I),
    re.compile(r"\b(?:verified|confirmed)\s+(?:it\s+|that\s+it\s+)?works\b", re.I),
    re.compile(r"\bit(?:'s| is)\s+verified\b", re.I),
    re.compile(r"\bshould\s+(?:now\s+)?(?:work|pass|be\s+fixed|be\s+working|"
               r"fix\s+it)\b", re.I),
]

NEGATION_RX = re.compile(
    r"(?:\bnot\b|n't\b|\bnever\b|\bno\b|\bunverified\b|\buntested\b|"
    r"\bwhether\b|\bif\b|\bunless\b|\buntil\b)[^.!?\n]{0,30}$", re.I)

DISCLOSED_RX = re.compile(
    r"\b(?:did(?:n't| not)|have(?:n't| not)|could(?:n't| not)|can(?:'t|not))"
    r"\s+(?:yet\s+)?(?:run|test|verify|execute)\b|\buntested\b|"
    r"\bnot\s+(?:yet\s+)?(?:run|tested|verified)\b", re.I)

CODE_SPAN_RX = re.compile(r"```.*?```|`[^`\n]*`", re.S)
QUOTE_LINE_RX = re.compile(r"^\s*>.*$", re.M)


def _is_code_path(path: str) -> bool:
    return bool(path) and path.lower().endswith(CODE_EXT)


def _segments(cmd: str):
    # A heredoc body is data, not commands -- drop everything after the
    # first `<<` marker's line so prose inside it is never read as a command.
    first, _, _ = cmd.partition("\n")
    head = cmd if "<<" not in first else first
    for seg in re.split(r"&&|\|\||;|\||\n", head):
        words = seg.strip().split()
        while words and (re.match(r"^\w+=", words[0]) or words[0] in ("sudo", "time", "nohup")):
            words = words[1:]
        if words:
            yield words


def bash_runs(cmd: str) -> bool:
    """True when any segment executes something rather than only reading."""
    for words in _segments(cmd or ""):
        w0 = words[0].lstrip("(")
        if w0 not in PASSIVE:
            return True
    return False


def bash_writes_code(cmd: str):
    m = WRITES_CODE_RX.search(cmd or "")
    return m.group(1) if m else None


def events_from_calls(calls):
    """Turn (tool name, input) pairs into an ordered list of 'edit'/'run'."""
    out = []
    for name, inp in calls:
        inp = inp or {}
        if name in EDIT_TOOLS:
            path = inp.get("file_path") or inp.get("notebook_path") or ""
            if _is_code_path(path):
                out.append(("edit", path))
        elif name == "Bash":
            cmd = inp.get("command") or ""
            wrote = bash_writes_code(cmd)
            if wrote:
                out.append(("edit", wrote))
            if bash_runs(cmd):
                out.append(("run", cmd[:60]))
        elif name in RUN_TOOLS or RUN_TOOL_RX.search(name or ""):
            out.append(("run", name))
    return out


def claims(text: str):
    """Positive works-claims in the reply, ignoring code spans, quotes and
    negated or conditional phrasings."""
    t = QUOTE_LINE_RX.sub(" ", CODE_SPAN_RX.sub(" ", text or ""))
    found = []
    for rx in CLAIM_RX:
        for m in rx.finditer(t):
            before = t[max(0, m.start() - 40):m.start()]
            if NEGATION_RX.search(before):
                continue
            found.append(m.group(0).strip(" .!,:\n-*"))
    return found


def check(calls, text: str):
    """Return None when the turn is fine, else {'file', 'claims'}."""
    if DISCLOSED_RX.search(CODE_SPAN_RX.sub(" ", text or "")):
        return None
    ev = events_from_calls(calls)
    last_edit = None
    for i, (kind, what) in enumerate(ev):
        if kind == "edit":
            last_edit = (i, what)
    if last_edit is None:
        return None
    if any(kind == "run" for kind, _ in ev[last_edit[0] + 1:]):
        return None
    said = claims(text)
    if not said:
        return None
    return {"file": last_edit[1], "claims": said}


def message(finding) -> str:
    return (
        "the reply says %s, but %s was changed this turn and nothing ran "
        "after that change. House-rules 0: never say something works unless "
        "you ran it. Run it (the self-test, the script, the tests) and report "
        "what it printed -- or say plainly that you did not run it"
        % (", ".join('"%s"' % c for c in finding["claims"][:3]),
           finding["file"].rsplit("/", 1)[-1])
    )


# ---------------------------------------------------------------- self-test

CASES = [
    # (name, calls, reply, should_fire)
    ("edit then claim, nothing ran",
     [("Edit", {"file_path": "/r/x.py"})], "Fixed — it works now.", True),
    ("edit, commit, push, claim tests pass",
     [("Edit", {"file_path": "/r/x.py"}),
      ("Bash", {"command": "git add -A && git commit -m x && git push"})],
     "All 12 tests pass and it is pushed.", True),
    ("ran, then edited again, then claimed",
     [("Edit", {"file_path": "/r/a.py"}),
      ("Bash", {"command": "python3 a.py --self-test"}),
      ("Edit", {"file_path": "/r/a.py"})],
     "Self-test passes.", True),
    ("the hedge rule 0 names",
     [("Write", {"file_path": "/r/foo.sh"})], "This should work.", True),
    ("sed -i is an edit too",
     [("Bash", {"command": "sed -i 's/a/b/' scripts/x.py"})],
     "Done. It works now.", True),
    ("a read after the edit is not a run",
     [("Edit", {"file_path": "/r/x.py"}),
      ("Bash", {"command": "cat x.py | grep foo && git diff"})],
     "The check is green.", True),

    ("edit then ran it",
     [("Edit", {"file_path": "/r/x.py"}),
      ("Bash", {"command": "python3 x.py --self-test"})],
     "It works now.", False),
    ("a doc edit cannot 'work'",
     [("Edit", {"file_path": "/r/README.md"})],
     "Fixed the typo; it works.", False),
    ("no edit this turn",
     [("Bash", {"command": "git status"})], "The hook works.", False),
    ("honest disclosure passes",
     [("Edit", {"file_path": "/r/x.py"})],
     "I changed it but didn't run it yet, so it is untested.", False),
    ("negated claim",
     [("Edit", {"file_path": "/r/x.py"})],
     "It is not fixed yet and it doesn't work.", False),
    ("cd then pytest is a run",
     [("Edit", {"file_path": "/r/x.py"}),
      ("Bash", {"command": "cd repo && pytest -q"})], "Tests pass.", False),
    ("claim only inside a code block",
     [("Edit", {"file_path": "/r/x.py"})],
     "Changed the regex:\n```\n# it works now\n```\nNext I will run it.", False),
    ("a subagent ran it",
     [("Edit", {"file_path": "/r/x.py"}), ("Agent", {"prompt": "run tests"})],
     "Verified it works.", False),
    ("a CI read counts",
     [("Edit", {"file_path": "/r/x.yml"}),
      ("mcp__github__get_check_run", {})], "CI is green.", False),
    ("write and run in one command",
     [("Bash", {"command": "sed -i 's/a/b/' x.py && python3 x.py --self-test"})],
     "Fixed, works now.", False),
    ("conditional, not a claim",
     [("Edit", {"file_path": "/r/x.py"})],
     "Next turn I will check whether it works.", False),
    ("heredoc prose is not a command",
     [("Edit", {"file_path": "/r/x.py"}),
      ("Bash", {"command": "git commit -F - <<'MSG'\nrun python3 later\nMSG"})],
     "Committed. It works now.", True),
]


def self_test() -> int:
    failures = 0

    def ok(cond, label):
        nonlocal failures
        print("  [%s] %s" % ("ok" if cond else "FAIL", label))
        if not cond:
            failures += 1

    fired = silent = 0
    for name, calls, reply, should in CASES:
        got = check(calls, reply) is not None
        ok(got == should, "%s -> %s" % (name, "fires" if should else "silent"))
        fired += should
        silent += not should

    # house-rules 6c: an absence is not a pass. The silent cases above assert
    # absences; these planted presences prove the comparator can say NO.
    ok(fired >= 5 and silent >= fired, "more must-stay-silent cases than firing ones")
    ok(bash_runs("python3 x.py") and not bash_runs("git add . && git commit -m x"),
       "the run detector tells executing from recording")
    ok(claims("Done. It works now.") and not claims("It doesn't work yet."),
       "the claim detector reports a planted claim and drops a negated one")
    f = check([("Edit", {"file_path": "/r/x.py"})], "It works now.")
    ok(f is not None and "x.py" in message(f), "the message names the file")

    print("%d case(s), %d failure(s)" % (len(CASES), failures))
    return 1 if failures else 0


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    print(__doc__)


if __name__ == "__main__":
    main()
