#!/usr/bin/env python3
"""turn_counter.py — house-rules 3a's threshold, fired from inside a live chat.

WHY THIS EXISTS
---------------
Rule 3a is the estate's largest measured cost lever: a turn re-sends everything
behind it, so a chat's cost grows with roughly `turns²`, and ONE session out of
the 82 that record turns is about half of all re-send cost ever incurred
(`skyne/2026-09-04-session-length-is-the-lever-not-the-model.md`).

The rule shipped as prose. `skyne/scripts/session_cost.py` then made the CORPUS
measurable — how concentrated the spend is, what capping is worth — but it could
not see the chat it was running inside, and the SessionStart brief fires when
the count is zero. Both skyne PR #254 and its report named that hole out loud:

    "Nothing counts a live chat's turns automatically."

This closes it. Garrett asked for it directly on 2026-09-05: *"Can we add the
turn counter to the skyne repo (and perhaps every repo just so nothing gets
missed)?"*

WHY IT LIVES IN THE PLUGIN AND NOT IN A REPO
--------------------------------------------
"Every repo" is the ask, and a repo's `.claude/settings.json` reaches only
sessions whose project directory IS that repo — so eight copies would be eight
files that drift, which this estate forbids by name. This plugin is already
installed with **Sync automatically** on, so its hooks arrive with zero clicks
(house-rules 15) and fire in EVERY session on EVERY surface, whatever repo is
attached or none. Same argument that put `reply_gate.py` here rather than in the
private repo. One definition, every repo, no click.

WHAT IT DOES
------------
On every `Stop` it counts the real user turns in the transcript. Under the first
band it does nothing at all. Crossing a band ONCE, it refuses the stop with a
reason telling Claude to say the count to Garrett and run `/handoff` — because
rule 3's own recorded failure is a session announcing that the chat should end
and never writing the handoff.

**Once per band, never again.** A gate that fires every turn past 600 is a gate
that gets deleted, so the band already announced is recorded in a per-session
state file. Crossing the next band fires once more.

**It never blocks work and it always fails open.** Every error path — no stdin,
no transcript, an unwritable state dir, an unparseable line — exits 0 and lets
the stop proceed. A counter that can trap a session is worse than no counter.

Usage:
    python3 turn_counter.py                        # the hook (JSON on stdin)
    python3 turn_counter.py --count -t <path>      # count one transcript
    python3 turn_counter.py --self-test
"""
import hashlib
import json
import os
import sys
import tempfile

# ---------------------------------------------------------------------------
# The threshold. house-rules 3a, and skyne/scripts/session_cost.py's
# TURN_THRESHOLD, which is the same number for the same reason.
#
# TWO COPIES, SAID OUT LOUD rather than hidden: this file cannot import from
# skyne (a plugin hook runs with no repo attached, which is the entire point of
# it being here), and skyne cannot import from a plugin it does not ship. So the
# number is written twice and `skyne`'s promise `turn-threshold-agrees-with-the-
# plugin` compares them whenever both checkouts are present. Where it cannot
# see the plugin it reports that, never a pass.
THRESHOLD = 1_000

# The first band is deliberately BELOW the threshold. Being told at 1,000 that
# you are at 1,000 is being told too late — the handoff has to be written while
# there is still room to write it, which is rule 3's own text.
WARN_AT = 600

# Past the threshold, say it again every this many turns. Not every turn: a
# nag on every stop is noise, and noise is what gets tuned out.
REPEAT_EVERY = 500


def state_dir():
    home = os.path.expanduser("~")
    if not home or home == "~" or not os.access(home, os.W_OK):
        home = tempfile.gettempdir()
    return os.path.join(home, ".turn-counter")


def state_path(transcript_path):
    """Hashed rather than the raw path — an unusual transcript path must never
    become an unwritable or collision-prone filename. Same idiom as the reply
    gate's cooldown, and for the same reason."""
    key = hashlib.sha256((transcript_path or "").encode()).hexdigest()[:16]
    return os.path.join(state_dir(), "band-%s.json" % key)


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


def count_turns(entries):
    """Real user turns — what Garrett would call an exchange.

    The predicate is `reply_gate.last_user_boundary`'s, and copying it is
    deliberate rather than lazy: tool results, meta entries and subagent
    prompts ALL arrive as user-type entries, so a naive `type == "user"` count
    inflates a tool-heavy session by a large multiple and would fire this gate
    on a chat that is nowhere near long. If that predicate is ever wrong it is
    wrong in both files at once, which is the failure mode worth having.
    """
    n = 0
    for e in entries:
        if not isinstance(e, dict):
            continue
        if (e.get("type") == "user"
                and not e.get("isMeta")
                and not e.get("toolUseResult")
                and not e.get("isSidechain")):
            n += 1
    return n


def band_for(turns, threshold=THRESHOLD, warn_at=WARN_AT, repeat=REPEAT_EVERY):
    """The band this turn count sits in, or None below the first one.

    Bands are the NUMBER that was crossed, so they are directly comparable and
    a state file holding a lower one means this band has not been announced.
    """
    if turns >= threshold:
        over = (turns - threshold) // repeat
        return threshold + over * repeat
    if turns >= warn_at:
        return warn_at
    return None


def message(turns, band, threshold=THRESHOLD):
    """What Claude is told to say. It names the number, because a warning that
    does not carry the count leaves Garrett unable to judge it himself."""
    if band < threshold:
        return (
            "SESSION LENGTH (house-rules 3a) — this chat is at about %d turns, "
            "approaching the ~%s-turn threshold. Every turn re-sends the whole "
            "conversation, so cost grows with roughly turns squared.\n\n"
            "Before you end this reply: tell Garrett the turn count in one line, "
            "and say that a handoff should be written while there is still room "
            "to write it. Then carry on with the work — this is a heads-up, not "
            "a stop. It will not fire again until %d turns."
            % (turns, "{:,}".format(threshold), threshold)
        )
    over = turns / float(threshold)
    return (
        "SESSION LENGTH (house-rules 3a) — this chat is at about %d turns, %.1fx "
        "the ~%s-turn threshold. Each turn re-sends all of it, so this chat now "
        "costs roughly %.0fx per turn what a fresh one would.\n\n"
        "Before you end this reply, do BOTH of these, in this order:\n"
        "  1. Tell Garrett the number, in one line, addressed to him.\n"
        "  2. RUN the `/handoff` skill. Rule 3's recorded failure is a session "
        "that said the chat should end four times and never wrote the handoff — "
        "saying it without running it IS the miss, not the fix.\n\n"
        "Then finish the work in front of you. This will not fire again for "
        "another %d turns."
        % (turns, over, "{:,}".format(threshold), over ** 2, REPEAT_EVERY)
    )


def already_announced(transcript_path):
    try:
        with open(state_path(transcript_path), encoding="utf-8") as f:
            return int(json.load(f).get("band", 0))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        # No state, or unreadable state, reads as "nothing announced yet".
        # Failing toward announcing once too often is the safe direction: the
        # cost is one extra line, and the cost of the other direction is the
        # whole mechanism silently never firing.
        return 0


def record(transcript_path, band):
    try:
        os.makedirs(state_dir(), exist_ok=True)
        with open(state_path(transcript_path), "w", encoding="utf-8") as f:
            json.dump({"band": int(band)}, f)
    except OSError:
        pass  # best effort; a lost state file just re-announces once


def allow(why, **kv):
    """Exit 0 with no stdout — the stop proceeds. One stderr marker so a human
    reading the debug log can see which branch fired."""
    extra = " ".join("%s=%s" % (k, v) for k, v in kv.items())
    sys.stderr.write(("turn_counter_allow %s %s" % (why, extra)).rstrip() + "\n")
    sys.exit(0)


def decide(entries, transcript_path, threshold=THRESHOLD):
    """(reason or None, turns, band) — the whole verdict, transcript-free above
    the read so the self-test exercises the real function rather than a copy."""
    turns = count_turns(entries)
    band = band_for(turns, threshold)
    if band is None:
        return None, turns, None
    if band <= already_announced(transcript_path):
        return None, turns, band
    return message(turns, band, threshold), turns, band


def self_test():
    fails = []

    def u(**kw):
        return dict({"type": "user"}, **kw)

    # the predicate: only REAL user turns count
    entries = [u(), u(isMeta=True), u(toolUseResult={"x": 1}), u(isSidechain=True),
               {"type": "assistant"}, u(), "not a dict"]
    if count_turns(entries) != 2:
        fails.append("count_turns must skip meta, tool-result, sidechain and "
                     "assistant entries; got %d" % count_turns(entries))

    # bands
    cases = [(0, None), (599, None), (600, 600), (999, 600),
             (1000, 1000), (1499, 1000), (1500, 1500), (5903, 5500)]
    for turns, want in cases:
        got = band_for(turns)
        if got != want:
            fails.append("band_for(%d) = %r, expected %r" % (turns, got, want))

    # the message must carry the NUMBER, and past the threshold must name /handoff
    warn = message(700, 600)
    if "700" not in warn:
        fails.append("the warning must carry the turn count")
    if "/handoff" in warn:
        fails.append("the pre-threshold warning must not demand /handoff yet — "
                     "it is a heads-up, and a demand at 600 is the nag that "
                     "gets the gate deleted")
    over = message(2000, 2000)
    for must in ("2000", "/handoff", "2.0x"):
        if must not in over:
            fails.append("the over-threshold message must name %r" % must)
    if "4x" not in over:
        fails.append("the over-threshold message must state the squared cost, "
                     "which is the whole reason length beats model choice")

    # once per band, and the NEXT band still fires — the two failures that
    # matter in opposite directions
    import tempfile as _tf
    real_home = os.environ.get("HOME")
    with _tf.TemporaryDirectory() as tmp:
        os.environ["HOME"] = tmp
        try:
            path = "/fake/transcript/a.jsonl"
            short = [u() for _ in range(10)]
            reason, turns, band = decide(short, path)
            if reason is not None:
                fails.append("a short session must produce no reason at all")
            if turns != 10:
                fails.append("a short session must still be counted")

            long_ = [u() for _ in range(650)]
            reason, turns, band = decide(long_, path)
            if reason is None or band != 600:
                fails.append("crossing the first band must fire once")
            record(path, band)
            reason2, _, _ = decide(long_, path)
            if reason2 is not None:
                fails.append("the same band must NOT fire twice — a gate that "
                             "nags every turn is a gate that gets deleted")

            longer = [u() for _ in range(1100)]
            reason3, _, band3 = decide(longer, path)
            if reason3 is None or band3 != 1000:
                fails.append("the NEXT band must still fire after the first was "
                             "announced, or the gate goes silent for good")

            # a different session must not inherit another's state
            other = "/fake/transcript/b.jsonl"
            reason4, _, _ = decide(long_, other)
            if reason4 is None:
                fails.append("state is per-session; another transcript must "
                             "still get its first announcement")

            # an unwritable state dir must not raise and must not go silent
            os.environ["HOME"] = os.path.join(tmp, "does-not-exist-and-cannot")
            reason5, _, _ = decide(long_, path)
            if reason5 is None:
                fails.append("with no readable state the gate must announce, "
                             "not silently skip")
        finally:
            if real_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = real_home

    # a missing or malformed transcript must read as empty, never raise
    if read_transcript("/no/such/file.jsonl") != []:
        fails.append("a missing transcript must read as empty")
    with _tf.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
        fh.write('{"type":"user"}\n{ broken\n{"type":"user"}\n')
        broken_path = fh.name
    try:
        if count_turns(read_transcript(broken_path)) != 2:
            fails.append("a half-written line must be tolerated, not fatal")
    finally:
        os.unlink(broken_path)

    if fails:
        for f in fails:
            print("SELF-TEST FAIL:", f)
        return 1
    print("self-test: %d cases passed" % (len(cases) + 12))
    return 0


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())

    if "--count" in sys.argv:
        path = ""
        for flag in ("-t", "--transcript"):
            if flag in sys.argv:
                path = sys.argv[sys.argv.index(flag) + 1]
        entries = read_transcript(path)
        turns = count_turns(entries)
        band = band_for(turns)
        state = "OK" if band is None else ("NEARING" if band < THRESHOLD else "OVER")
        print("%s: %d turn(s)%s" % (state, turns,
                                    "" if band is None else " — band %d" % band))
        sys.exit(0)

    # From here on nothing may raise. A Stop hook that throws is a Stop hook
    # that can trap a session, and this one is worth exactly one line of output.
    try:
        raw = sys.stdin.read()
    except Exception:
        allow("stdin_unreadable")
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        allow("stdin_unparseable")

    transcript_path = payload.get("transcript_path") or ""
    if not transcript_path:
        allow("no_transcript_path")

    try:
        entries = read_transcript(transcript_path)
        if not entries:
            allow("transcript_empty")
        reason, turns, band = decide(entries, transcript_path)
    except Exception as exc:  # pragma: no cover - the fail-open path
        allow("degraded", err=type(exc).__name__)

    if reason is None:
        allow("under_band", turns=turns)

    record(transcript_path, band)
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
