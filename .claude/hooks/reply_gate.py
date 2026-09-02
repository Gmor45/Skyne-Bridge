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

DELIVERY — this gate cannot fire in a multi-repo remote session
---------------------------------------------------------------
CORRECTED 2026-09-02 (evening) — read this before the paragraph under it. The
outcome below is right; the cause given for it was wrong. This gate ships as a
PLUGIN hook (`hooks/hooks.json`), not through a repo's `.claude/settings.json`,
so the subdirectory explanation does not apply to it. Measured in a remote
multi-repo session: `~/.claude/plugins/synced` held only `marketplace.json` —
the plugin was simply not installed there — and the only Stop hook registered
was the platform's own git check. The subdirectory failure is real for the
REPO-registered hooks (the vault's SessionStart brief, `findings_gate.py`,
`trail.py hook`: none of their per-call artifacts existed after 158 vault
scripts had run). Two different causes, one outcome: nothing of Skyne's fires
on that surface. Filed as `2026-09-02-no-skyne-hook-fired-in-a-multi-repo-
remote-session` in the brain repo's miss ledger; a "hooks fired this session"
probe is the S6 work item that makes the hole visible instead of documented.

Measured 2026-09-02. This repo's hooks are registered in its own
`.claude/settings.json`. When a Claude Code session clones SEVERAL repos side
by side, the project directory is their PARENT, this file sits in a
subdirectory, and those settings are never loaded — the same failure already
documented for claude-audit's SessionStart hook.

So on the surface where Garrett does much of his work, this gate is inert while
looking installed. It caught the 2026-09-02 double-summary on shape when run by
hand and did not fire once during the session that produced it. Do not read a
clean session as evidence the gate is working; run `--self-test` to see whether
the CODE is right, and check the session type to know whether it can RUN.

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

# Tools that, on their own, mean the turn did no work worth reporting. Kept as a
# set so a turn using ANY other tool is exempt automatically.
NO_WORK_TOOLS = {"ReadNotifications"}

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

# ---------------------------------------------------------------- AI-isms
#
# Banned ANYWHERE in the reply, unlike BANNED_IN_SUMMARY above which only
# guards the closing block. These are not jargon — they are the stock phrases
# an assistant reaches for to sound engaged, and Garrett clocked them as a
# tell rather than as content.
#
# Ruled 2026-09-02. He had just caught a real failure, and the reply opened
# "You're right, and it's worse than you're saying." His response: *"you love
# that dont you? ... can we add that to the bin of AI-isms I want you to avoid
# using repetitively from now on?"*
#
# WHY A GATE AND NOT A PREFERENCE. "Avoid stock phrases" is an adjective, and
# house-rules 0a is the measured proof that adjectives do not hold: three of
# his formatting rules ran for months, the two with a countable shape held
# every time and the one that was a judgement call held never. A phrase list is
# countable. So it is counted.
#
# EACH ENTRY IS A PHRASE HE ACTUALLY SAW. Do not pad this list with plausible
# AI-isms — a banned list nobody triggered is a list nobody trusts, and it will
# eventually block a reply for a phrase that was fine. Grow it the same way
# BANNED_IN_SUMMARY grows: he names one, it lands here in the same turn.
#
# Escalation, not perfection: the check reports the phrase and asks for a
# rewrite of that sentence. It never rewrites the reply itself.
BANNED_ANYWHERE = [
    # 2026-09-02, named by Garrett
    r"it'?s worse than (you'?re|you are|that)",
    r"you'?re (absolutely )?right,? and",
    r"and (it|that)'?s the (whole|entire) point\b",
    r"let me (be )?(perfectly |completely )?(clear|honest) (with you )?here\b",
    r"\bi'?ll be honest\b",
    r"that'?s a (great|fair|excellent) (question|point|catch)\b",
    r"\bhere'?s the (thing|kicker|rub)\b",
    r"\bthe (real|actual) (question|answer|issue) (here )?is\b",
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


def tools_used(entries, boundary):
    """Tool names invoked in the main loop this turn.

    Cause 1 of house-rules 0b is countable and this is what counts it: a turn
    whose ONLY tool call was ReadNotifications did no work, so a long reply
    about it is a reply that should not exist. If a notification genuinely
    needed acting on, some other tool would appear here — that is the
    discriminator, and it is structural rather than a judgement about tone.
    """
    names = set()
    for e in entries[boundary + 1:]:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "tool_use":
                n = blk.get("name")
                if n:
                    names.add(n)
    return names


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


def evaluate(text, tools=None):
    """Return a list of complaints. Empty list == the reply passes.

    Pure and transcript-free so the self-test exercises the real thing rather
    than a copy of it. `tools` is the set of tool names used this turn, or None
    when the caller cannot say; None disables only the echo check below.
    """
    problems = []
    if words(text) < TRIVIAL_WORDS:
        return []  # short answer, nothing to skim past

    # house-rules 0b, cause 1. Measured 2026-09-01: four consecutive replies
    # existed only to relay PR notifications that echoed Claude's own actions,
    # and every one of them passed this gate on shape. Reading a queue is not
    # work, so a turn that did nothing else owes Garrett one line, not four
    # sections. This fires BEFORE the shape checks on purpose — telling a reply
    # that should not exist to fix its heading order is the wrong instruction.
    if tools is not None and tools and tools <= NO_WORK_TOOLS:
        return [
            "this turn only read the notification queue and did no other work, "
            "yet the reply is %d words. An event that echoes your own action is "
            "safe to skip — say it in ONE line with no closing block (under %d "
            "words is exempt), or say nothing at all"
            % (words(text), TRIVIAL_WORDS)
        ]

    # AI-isms: whole reply, not just the block. Reported alongside whatever
    # else is wrong rather than short-circuiting — a reply can be both
    # stock-phrased and missing a section, and hearing one at a time wastes a
    # round trip.
    stock = [rx for rx in BANNED_ANYWHERE if re.search(rx, text, re.I)]
    if stock:
        shown = [re.search(rx, text, re.I).group(0) for rx in stock[:3]]
        problems.append(
            "stock phrase(s) Garrett has asked you to stop using: %s. He named "
            "these as a tell rather than content — say the same thing in your "
            "own words, or just say the thing itself and skip the wind-up"
            % ", ".join('"%s"' % x for x in shown)
        )

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

    # TWO Recommendations sections is the shape this actually catches, and the
    # old message described the symptom (position) instead of the cause.
    #
    # Garrett, 2026-09-02: "why do I feel like this is a lazy fix?" — after a
    # reply with a `## Recommendations` section in the body AND one inside the
    # block, plus a TLDR. He read it as three summaries of the same reply, and
    # he was right. The duplication is not carelessness: rule 0a's block already
    # CONTAINS Recommendations, while rule 10 separately says to put
    # recommendations in their own short section. Obey both literally and you
    # get two. One place, and the block is it.
    #
    # This gate already caught it on position — verified against the real reply
    # — but never ran, because in a multi-repo remote session this repo's hooks
    # sit in a subdirectory and are never loaded. See DELIVERY, below.
    all_recs = [n for n, ln in enumerate(lines) if RECS_RE.search(ln)]
    i_recs = all_recs[0] if all_recs else -1
    if len(all_recs) > 1:
        problems.append(
            "there are %d Recommendations sections. The closing block's is the "
            "only one — rule 0a's block already contains Recommendations, so a "
            "second one in the body makes the reply summarise itself twice. "
            "Delete the body copy; keep the reasons in the block's"
            % len(all_recs)
        )
    elif i_recs >= 0 and not (i_why < i_recs < i_tldr):
        problems.append(
            "Recommendations must sit INSIDE the closing block, between Why and "
            "TLDR — not as its own section up in the body"
        )

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


ECHO_REPLY = (
    "All four were echoes of my own actions on the pull request - the "
    "subscription, the ready-for-review flip, the green CI I had already "
    "polled, and the merge I had already verified against origin/main. GitHub "
    "auto-unsubscribed the session. Queue is empty, nothing outstanding. Still "
    "finished. The paste block from my last message is what you need, and there "
    "is nothing further for anyone to act on here tonight at all.\n\n"
    "**What I did** - Read the notification queue, confirmed all four were my "
    "own actions coming back. No work needed.\n\n"
    "**Why** - I check the queue rather than assume it is noise, but I am not "
    "going to invent work out of it.\n\n"
    "**TLDR** - Empty queue, nothing to act on, chat still done."
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

    # ---- AI-isms, ruled 2026-09-02 -----------------------------------------
    # Garrett, after a reply opened "You're right, and it's worse than you're
    # saying": *"you love that dont you? ... can we add that to the bin of
    # AI-isms I want you to avoid using repetitively from now on?"*
    #
    # The VERBATIM opening is the fixture, so this can never quietly become a
    # check that only ever passes. Both directions are asserted: the real
    # phrase fails, and a reply saying the same thing plainly passes — a gate
    # that fired on both would just be banning disagreement.
    expect("the real 2026-09-02 opener fails",
           "You're right, and it's worse than you're saying. " + GOOD, False)
    expect("saying it plainly still passes",
           "You are right, and the cause is one I had already documented. " + GOOD,
           True)
    for phrase in ("That's a great question. ",
                   "Here's the thing. ",
                   "Let me be honest with you here. ",
                   "You're absolutely right, and that changes things. "):
        expect("banned: %s" % phrase.strip()[:28], phrase + GOOD, False)
    # A banned phrase must be reported even when the block is ALSO malformed —
    # hearing one complaint per round trip wastes a turn.
    both = evaluate("Here's the thing. " + SAMPLE_BODY + "\n**What I did**\n- x\n")
    if not any("stock phrase" in c for c in both):
        fails.append("banned phrase not reported alongside a shape failure")
    print("  %-34s %s" % ("reported beside a shape failure",
                          "ok" if any("stock phrase" in c for c in both) else "FAIL"))

    # ---- the double summary, measured 2026-09-02 ----------------------------
    # Garrett: "why the hell are There TWO tldrs?" then "why do I feel like this
    # is a lazy fix?" The reply had a `## Recommendations` section in the body
    # AND one in the block, so it summarised itself twice. This gate ALREADY
    # caught the shape on position — the failure was delivery, not detection
    # (see DELIVERY at the top). The message now names duplication rather than
    # position, and both directions are asserted so it cannot become a check
    # that only ever fires.
    _f = "filler word " * 90
    _dup = ("Body.\n\n## Recommendations\n\n- a\n\n---\n\n"
            "**What I did** — d.\n\n**Why** — w. " + _f +
            "\n\n**Recommendations** — r.\n\n**TLDR** — t.\n")
    _one = ("Body. " + _f + "\n\n**What I did** — d.\n\n**Why** — w.\n\n"
            "**Recommendations** — r.\n\n**TLDR** — t.\n")
    _none = ("Body. " + _f + "\n\n**What I did** — d.\n\n**Why** — w.\n\n"
             "**TLDR** — t.\n")
    expect("two Recommendations sections fail", _dup, False)
    expect("one, inside the block, passes", _one, True)
    expect("no Recommendations at all passes", _none, True)
    _msgs = " ".join(evaluate(_dup))
    if "2 Recommendations sections" not in _msgs:
        fails.append("the duplicate message must COUNT them, not just complain")
    print("  %-34s %s" % ("the message names the count",
                          "ok" if "2 Recommendations sections" in _msgs else "FAIL"))

    # ---- house-rules 0b cause 1: the echo reply, measured 2026-09-01 ----
    # This block is the regression. The verbatim failing reply below PASSED
    # every shape check the gate had at the time, which is what made Garrett
    # ask for a summary at the end of a fully compliant session.
    def expect_t(name, text, tools, should_pass):
        got = evaluate(text, tools)
        ok = (len(got) == 0) == should_pass
        if not ok:
            fails.append("%s: expected %s, got %r" % (
                name, "pass" if should_pass else "fail", got))
        print("  %-34s %s" % (name, "ok" if ok else "FAIL"))

    expect_t("echo-only turn is caught", ECHO_REPLY, {"ReadNotifications"}, False)
    expect_t("...and it passed on shape alone", ECHO_REPLY, None, True)
    expect_t("echo + real work is exempt", ECHO_REPLY,
             {"ReadNotifications", "Bash"}, True)
    expect_t("one-line echo is fine", "All four echo my own actions; nothing to do.",
             {"ReadNotifications"}, True)
    expect_t("no tools recorded falls back to shape", GOOD, set(), True)

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
        problems = evaluate(text, tools_used(entries, b))
        print("reply words: %d" % words(text))
        print("tools this turn: %s" % (sorted(tools_used(entries, b)) or "none"))
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

    problems = evaluate(text, tools_used(entries, boundary))
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
