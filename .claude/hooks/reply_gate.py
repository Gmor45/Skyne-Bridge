#!/usr/bin/env python3
"""Stop hook: refuse to end a substantive turn without a plain-English closing block.

WHY THIS EXISTS
---------------
Garrett has asked for shorter, simpler answers more times than for anything
else, and it has never held. Two other formatting rules in the same preferences
block — "always include a TLDR" and "always include Recommendations" — hold
every time. The difference is not emphasis. It is that those two can be checked
by looking, and "be concise" cannot: it is re-judged every turn, and every turn
there is a local excuse ("this one was genuinely complicated").

So this gate does not ask for concise. It asks for a fixed closing block, which
is countable, and it refuses the stop until the block is there:

    **What I did**       plain English, no jargon
    **Why**              plain English, no jargon
    **Recommendations**  optional — only when there are real ones
    **TLDR**             one line

The body ABOVE that block may be as long and as technical as the work needs.
That is the point of the design: the technical layer stays, and the block makes
it optional to read. Length was never the complaint — having to read the length
to find the answer was.

WHAT IT CANNOT DO, STATED HONESTLY
----------------------------------
No script can tell whether prose is actually simple. This one checks structure
(sections present, in order), size (the block stays skimmable), and a banned
vocabulary list *inside the block only*. It will happily pass a badly-written
summary that has the right shape. That residue is uncovered, and pretending
otherwise would be worse than leaving it named — a check that passes on the
real failure converts an open problem into a solved one.

FAIL-OPEN, ALWAYS
-----------------
Every error path allows the stop. A gate that traps the model is worse than no
gate. The per-turn counter caps re-prompts below the CLI's global ceiling so a
turn that genuinely cannot satisfy it still gets to end.
"""

import json
import os
import re
import sys
import tempfile

# ---------------------------------------------------------------- constants

# Below this, a reply is a one-liner and needs no closing block. Set from the
# shape of the failure: nobody has ever complained that a 40-word answer was
# hard to skim.
TRIVIAL_WORDS = 60

# The closing block must stay skimmable. This is the number that makes
# "concise" countable instead of arguable.
SUMMARY_MAX_WORDS = 170

# Re-prompts per turn before giving up. Deliberately low: a gate that nags
# three times is one he learns to ignore, which is the failure it exists to fix.
LOCAL_CAP = 2

# Banned INSIDE the closing block only. Not a style opinion — these are words
# that do not survive translation into "explain it like I'm five", so their
# presence means the block was written for the wrong reader. The body above the
# block may use any of them freely.
#
# GROW THIS LIST. When Garrett asks what a word means, that word belongs here in
# the same turn. That is the whole maintenance model.
BANNED_IN_SUMMARY = [
    "idempotent", "deterministic", "heuristic", "regex", "refactor",
    "frontmatter", "endpoint", "payload", "schema", "boolean", "serialize",
    "deserialize", "instantiate", "middleware", "stdin", "stdout", "jsonl",
    "transpile", "polyfill", "mutex", "race condition", "memoize",
    "dependency injection", "monkeypatch", "symlink", "subprocess", "stdlib",
    "venv", "orm", "cors", "mtls", "bytecode", "closure", "recursion",
    "abstraction", "sidechain", "transcript_path", "concurrency",
    "atomic", "immutable", "canonical", "normalize", "traversal",
]

# Section markers, in required order. Recommendations is optional by design —
# mandating it would manufacture filler recommendations, which is noise, and
# noise is what he tunes out.
WHAT_RE = re.compile(r"^\W*\**\s*what i (did|found|changed)\b", re.I)
WHY_RE = re.compile(r"^\W*\**\s*why\b", re.I)
TLDR_RE = re.compile(r"^\W*\**\s*tl;?dr\b", re.I)
RECS_RE = re.compile(r"^\W*\**\s*recommendation", re.I)


# ---------------------------------------------------------------- plumbing

def allow(path="ok", **kv):
    """Exit 0 with no stdout = the stop proceeds. One stderr marker so a human
    can see which branch fired; never emits reply content."""
    safe = lambda v: re.sub(r"[^A-Za-z0-9._<>/-]", "_", str(v))[:96]
    extra = " ".join("%s=%s" % (k, safe(v)) for k, v in kv.items())
    sys.stderr.write(("reply_gate_allow path=%s %s" % (path, extra)).rstrip() + "\n")
    sys.exit(0)


def block(reason):
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
    sys.exit(0)


def read_transcript(path):
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
                    continue  # tolerate a half-written tail line
    except OSError:
        return []
    return entries


def last_user_boundary(entries):
    """Index of the newest real user turn. Tool results, meta entries and
    subagent prompts all arrive as user-type entries; anchoring on one of those
    would treat part of this turn as a previous turn."""
    for i in range(len(entries) - 1, -1, -1):
        e = entries[i]
        if (
            e.get("type") == "user"
            and not e.get("isMeta")
            and not e.get("toolUseResult")
            and not e.get("isSidechain")
        ):
            return i
    return -1


def reply_text(entries, boundary):
    """Main-loop assistant prose written this turn. Subagent (sidechain) output
    is not the reply — it never reaches Garrett."""
    out = []
    for e in entries[boundary + 1:]:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "text":
                out.append(blk.get("text") or "")
    return "\n".join(out).strip()


# ---------------------------------------------------------------- the check

def words(s):
    return len(s.split())


def find_line(text, rx):
    for i, line in enumerate(text.splitlines()):
        if rx.search(line):
            return i
    return -1


def evaluate(text):
    """Return a list of complaints. Empty list == the reply passes.

    Pure and transcript-free so the self-test exercises the real thing rather
    than a copy of it.
    """
    problems = []
    if words(text) < TRIVIAL_WORDS:
        return []  # short answer, nothing to skim past

    lines = text.splitlines()
    i_what = find_line(text, WHAT_RE)
    i_why = find_line(text, WHY_RE)
    i_tldr = find_line(text, TLDR_RE)

    if i_what < 0:
        problems.append('no "**What I did**" section')
    if i_why < 0:
        problems.append('no "**Why**" section')
    if i_tldr < 0:
        problems.append('no "**TLDR**" line')

    if problems:
        return problems

    # Order matters: the block is one landing zone, not three scattered bits.
    if not (i_what < i_why < i_tldr):
        problems.append(
            "the closing sections are out of order — it must run "
            "What I did -> Why -> (Recommendations) -> TLDR, together at the end"
        )

    i_recs = find_line(text, RECS_RE)
    if i_recs >= 0 and not (i_why < i_recs < i_tldr):
        problems.append("Recommendations must sit between Why and TLDR")

    block_text = "\n".join(lines[i_what:])
    n = words(block_text)
    if n > SUMMARY_MAX_WORDS:
        problems.append(
            "the closing block is %d words; the limit is %d. It is meant to be "
            "skimmed, so move detail up into the body rather than trimming the body"
            % (n, SUMMARY_MAX_WORDS)
        )

    low = block_text.lower()
    hits = [w for w in BANNED_IN_SUMMARY if re.search(r"\b%s\b" % re.escape(w), low)]
    if hits:
        problems.append(
            "jargon inside the closing block: %s. The block is the layer that has "
            "to work for someone who does not code — say it in ordinary words "
            "instead (the body above may use them freely)"
            % ", ".join(sorted(hits)[:6])
        )
    return problems


def build_reason(problems, attempt):
    head = (
        "Do not end this turn yet. Garrett reads the closing block and often "
        "nothing else, so a turn without one lands as unreadable."
        if attempt <= 1 else
        "Still not right. Fix ONLY the closing block and finish:"
    )
    body = "\n".join("  - " + p for p in problems)
    shape = (
        "\nRequired shape, at the very END of your reply, in this order:\n"
        "  **What I did** - plain English, no jargon\n"
        "  **Why** - plain English, no jargon\n"
        "  **Recommendations** - only if you actually have some, each with its reason\n"
        "  **TLDR** - one line\n"
        "Reading those four alone must be enough to know what happened. "
        "Keep the detailed body above them; do not delete it and do not "
        "summarise it away."
    )
    return "%s\n%s\n%s" % (head, body, shape)


# ---------------------------------------------------------------- counter

def counter_path():
    home = os.path.expanduser("~")
    if not home or home == "~" or not os.access(home, os.W_OK):
        home = tempfile.gettempdir()
    d = os.path.join(home, ".reply-gate")
    return d, os.path.join(d, "turn-counter.json")


def bump(turn_key):
    d, p = counter_path()
    state = {}
    try:
        with open(p, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    count = state.get("count", 0) if state.get("turn_key") == turn_key else 0
    count += 1
    try:
        os.makedirs(d, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"turn_key": turn_key, "count": count}, f)
    except OSError:
        pass  # best effort; the CLI's global block ceiling still bounds this
    return count


# ---------------------------------------------------------------- self-test

SAMPLE_BODY = (
    "I looked at the four files and found the counter was reset in the wrong "
    "place, so every run started from zero. I moved it above the loop and ran "
    "the suite twice to be sure it was not luck. The second run took nine "
    "seconds and both passed cleanly with nothing skipped or ignored anywhere.\n"
)

GOOD = SAMPLE_BODY + (
    "\n**What I did**\n"
    "- Fixed a counter that kept starting over.\n"
    "- Ran the tests twice; both passed.\n\n"
    "**Why**\n"
    "- It was resetting in the wrong spot, so it never counted past one.\n\n"
    "**TLDR** Fixed the counter, tests pass.\n"
)


def self_test():
    fails = []

    def expect(name, text, should_pass):
        got = evaluate(text)
        ok = (len(got) == 0) == should_pass
        if not ok:
            fails.append("%s: expected %s, got %r" % (
                name, "pass" if should_pass else "fail", got))
        print("  %-34s %s" % (name, "ok" if ok else "FAIL"))

    print("reply_gate self-test")
    expect("short reply needs no block", "Yes, that is already true.", True)
    expect("well-formed reply passes", GOOD, True)

    # The regression this gate exists to stop: each required section must fail
    # the gate on its own when dropped, or the gate is one that only ever passes.
    for label, rx in (("What I did", WHAT_RE), ("Why", WHY_RE), ("TLDR", TLDR_RE)):
        stripped = "\n".join(
            l for l in GOOD.splitlines() if not rx.search(l))
        expect("missing %s is caught" % label, stripped, False)

    expect(
        "out-of-order block is caught",
        SAMPLE_BODY + "\n**TLDR** done.\n\n**What I did**\n- a thing\n\n**Why**\n- reasons\n",
        False,
    )
    expect(
        "jargon in the block is caught",
        GOOD.replace("Fixed a counter that kept starting over.",
                     "Made the counter idempotent."),
        False,
    )
    expect(
        "jargon in the BODY is allowed",
        GOOD.replace("I looked at the four files",
                     "I refactored the regex and the schema payload"),
        True,
    )
    expect(
        "an oversized block is caught",
        SAMPLE_BODY + "\n**What I did**\n" + ("- word word word word word\n" * 40)
        + "\n**Why**\n- because\n\n**TLDR** done.\n",
        False,
    )
    expect(
        "recommendations in the wrong place is caught",
        SAMPLE_BODY + "\n**Recommendations**\n- do a thing\n\n**What I did**\n- a thing\n\n"
        "**Why**\n- reasons\n\n**TLDR** done.\n",
        False,
    )

    if fails:
        print("\nFAILED:")
        for f in fails:
            print("  " + f)
        return 1
    print("\nall checks passed")
    return 0


# ---------------------------------------------------------------- entry

def run():
    if "--self-test" in sys.argv:
        sys.exit(self_test())

    if "--transcript" in sys.argv:
        # Dry run against a real transcript, so a session can prove the gate
        # fires on live data rather than only on its own fixtures.
        path = sys.argv[sys.argv.index("--transcript") + 1]
        entries = read_transcript(path)
        b = last_user_boundary(entries)
        text = reply_text(entries, b)
        problems = evaluate(text)
        print("reply words: %d" % words(text))
        print("verdict: %s" % ("BLOCK" if problems else "allow"))
        for p in problems:
            print("  - " + p)
        sys.exit(0)

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        allow("stdin_unparseable")

    entries = read_transcript(payload.get("transcript_path") or "")
    if not entries:
        allow("transcript_empty")

    boundary = last_user_boundary(entries)
    text = reply_text(entries, boundary)
    if not text:
        # A tool-only turn (spawned work, ran a command, said nothing). There is
        # no reply to shape, so there is nothing to gate.
        allow("no_assistant_text")

    problems = evaluate(text)
    if not problems:
        allow("well_formed", words=words(text))

    e = entries[boundary] if boundary >= 0 else {}
    key = e.get("uuid") or e.get("timestamp") or "unkeyed"
    n = bump(key)
    if n > LOCAL_CAP:
        allow("cap_exhausted", count=n)
    block(build_reason(problems, n))


def main():
    try:
        run()
    except SystemExit:
        raise
    except Exception as exc:  # never trap the model on a bug in this file
        sys.stderr.write("reply_gate_allow path=exception exc_type=%s\n"
                         % type(exc).__name__)
        sys.exit(0)


if __name__ == "__main__":
    main()
