#!/usr/bin/env python3
"""The hard switches. Two hooks, one file: a PreToolUse gate on `git push`
and a Stop gate on the top model tier.

WHY THIS EXISTS
---------------
Garrett, 2026-09-16: *"both actions and usage should have warnings thresholds
that show up early and prompt the system to recommend behavior switches that,
if ignored, trigger the system to begin doing hard switches to keep myself
from hitting the ceiling."*

Skyne's `scripts/guardrails.py` computes the ladder (clear -> advise ->
recommend -> enforce) and writes `data/guardrails-state.json`. Everything up
to `recommend` is words. THIS is the part that is not words.

WHY ONLY TWO LANES, WHEN THE REGISTER DESCRIBES SEVEN
-----------------------------------------------------
Because the other five were measured and cannot be enforced for free, and
shipping a gate that saves nothing is worse than shipping none (house-rules 21
point 5). Measured 2026-09-16:

  publish-core     4 of the last 100 runs in Gmor45/skyne, against 96 for ci.
                   Under 2% of the bill, and switching it off costs Garrett
                   the one page he actually looks at.
  branch-cleanup   `workflow_dispatch`-only. Fires zero times on its own.
  mcp-smoke        `workflow_dispatch`-only. Same.
  any in-workflow  GitHub bills per JOB with a one-minute minimum, so a guard
  guard step       step spends exactly what the job it blocks would have.

So the only Actions lever that costs nothing to pull is on THIS side of the
push, which is what the first half of this file does.

HOW IT FAILS
------------
OPEN, every time, and deliberately in that direction:

  - no state file found        -> allow
  - state older than 2 days    -> allow (a stale posture must not enforce)
  - unreadable / any exception -> allow
  - the lane is not switched off -> allow
  - the lane is overridden today -> allow, and the override is already a
    recorded row in Skyne's data/guardrail-overrides.jsonl

A gate that trapped a session because a feed went missing would be the coarse
gate house-rules 21 point 5 forbids, and it would be switched off within a
week, which costs more than it ever saved.

Usage:
  python3 guardrail_gate.py                       # the hook (JSON on stdin)
  python3 guardrail_gate.py --check "git push …"  # what it would say
  python3 guardrail_gate.py --state               # which state file it found
  python3 guardrail_gate.py --self-test
"""
import datetime as dt
import json
import os
import re
import shlex
import sys

COOLDOWN_DEFAULT_MIN = 20
STATE_MAX_AGE_DAYS = 2
OVERRIDE_PHRASE = "override the guardrail"

# Where a Skyne clone's state file might be. The env var wins, then the copy
# guardrails.py drops into the user's own Claude directory precisely so a hook
# with no idea where the repo lives can still find it.
STATE_CANDIDATES = (
    os.environ.get("SKYNE_GUARDRAIL_STATE"),
    os.path.join(os.path.expanduser("~"), ".claude", "skyne", "guardrails-state.json"),
    os.path.join(os.getcwd(), "data", "guardrails-state.json"),
    os.path.join(os.getcwd(), "Skyne", "data", "guardrails-state.json"),
    os.path.join(os.path.expanduser("~"), "Skyne", "data", "guardrails-state.json"),
    "/home/user/Skyne/data/guardrails-state.json",
)

PUSH_LOG = os.path.join(os.path.expanduser("~"), ".claude", "skyne", "push-log.json")

DOWNSHIFT = re.compile(r"go down to\s+(sonnet|haiku)", re.IGNORECASE)
HANDOFF = re.compile(r"/handoff|run the handoff", re.IGNORECASE)


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------

def find_state(candidates=None, today=None):
    """-> (state, why). `state` is None whenever the gate must stand down, and
    `why` always says which of the fail-open reasons applied — an absent gate
    and a silent gate must not look the same (house-rules 6c)."""
    today = today or dt.date.today()
    for path in (candidates if candidates is not None else STATE_CANDIDATES):
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            return None, "found %s but could not read it — standing down" % path
        stamp = str(state.get("generatedFor") or "")
        try:
            when = dt.date(*(int(x) for x in stamp.split("-")))
        except (TypeError, ValueError):
            return None, "%s has no usable date — standing down" % path
        if (today - when).days > STATE_MAX_AGE_DAYS:
            return None, ("%s is %d days old — a stale posture must not enforce"
                          % (path, (today - when).days))
        return state, path
    return None, "no guardrail state on disk — nothing to enforce"


def lane_is_off(state, lane):
    if not isinstance(state, dict):
        return False
    if lane in (state.get("lanesOverridden") or []):
        return False
    return lane in (state.get("lanesOff") or [])


# ---------------------------------------------------------------------------
# lane 1 — push batching
# ---------------------------------------------------------------------------

def is_push(command):
    """A `git push` that actually sends commits.

    Deliberately narrow. A branch DELETE sends nothing and fires nothing, so
    holding one back would be pure cost — the same reasoning that kept
    dispatch-only workflows out of the lane list."""
    if not command:
        return False
    for part in re.split(r"&&|\|\||;|\n", command):
        try:
            words = shlex.split(part, posix=True)
        except ValueError:
            words = part.split()
        if "git" not in words:
            continue
        try:
            after = words[words.index("git") + 1:]
        except (ValueError, IndexError):
            continue
        after = [w for w in after if not w.startswith("-") or w in ("--delete", "-d")]
        if not after or after[0] != "push":
            continue
        if "--delete" in words or "-d" in after:
            return False
        return True
    return False


def push_key(command, cwd):
    """One counter per checkout. Branch names are not parsed out of the
    command on purpose: `git push -u origin HEAD`, a bare `git push`, and an
    explicit branch name are the same push, and a key that told them apart
    would hand a session three free pushes for one branch."""
    return os.path.basename(str(cwd or os.getcwd()) or "repo")


def _load_pushes(path=PUSH_LOG):
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_pushes(doc, path=PUSH_LOG):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
    except OSError:
        pass  # a counter we cannot persist means the next push is allowed


def push_verdict(command, cwd, state, now=None, log_path=PUSH_LOG,
                 cooldown_min=COOLDOWN_DEFAULT_MIN, record=True):
    """-> a refusal string, or None to allow."""
    if not is_push(command):
        return None
    if not lane_is_off(state, "push-batching"):
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    key = push_key(command, cwd)
    log = _load_pushes(log_path)
    last = log.get(key)
    if last:
        try:
            when = dt.datetime.fromisoformat(str(last))
            if when.tzinfo is None:
                when = when.replace(tzinfo=dt.timezone.utc)
            waited = (now - when).total_seconds() / 60
        except (TypeError, ValueError):
            waited = cooldown_min + 1
        if waited < cooldown_min:
            left = int(round(cooldown_min - waited))
            return (
                "GUARDRAIL — Actions minutes are at the ceiling, so pushes to this "
                "checkout are being batched.\n\n"
                "This branch was pushed %d minute(s) ago. Every push to a branch with "
                "an open PR reruns the whole suite: 96 of the last 100 runs in skyne "
                "were exactly that.\n\n"
                "Keep committing locally and push once, in about %d minute(s). "
                "If this one genuinely cannot wait, Garrett can say \"%s\" and it "
                "re-opens for the rest of the day."
                % (int(waited), left, OVERRIDE_PHRASE))
    if record:
        log[key] = now.isoformat()
        _save_pushes(log, log_path)
    return None


# ---------------------------------------------------------------------------
# lane 2 — the top model tier
# ---------------------------------------------------------------------------

def last_assistant(entries):
    for entry in reversed(entries or []):
        if entry.get("type") == "assistant":
            return entry
    return None


def reply_text(entry):
    msg = (entry or {}).get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content
    out = []
    for part in content or []:
        if isinstance(part, dict) and part.get("type") == "text":
            out.append(part.get("text") or "")
    return "\n".join(out)


def tier_verdict(entries, state):
    """-> a block reason, or None.

    house-rules 2a made the downshift call a SOFT lock on Garrett's explicit
    2026-09-09 ruling, so a WRONG tier call could be waved through. That still
    stands and is untouched. This is the different case he ruled on
    2026-09-16: not "Claude thinks this is a Sonnet task" but "the week's
    budget is nearly gone", where the thing running out is not a judgement.
    Even here it does not force a model — nothing can (a hook can observe a
    switch and block one, never initiate one). It refuses to let the turn end
    SILENTLY on the top tier.
    """
    if not lane_is_off(state, "opus"):
        return None
    entry = last_assistant(entries)
    if entry is None:
        return None
    model = str(((entry.get("message") or {}).get("model")) or "")
    if "opus" not in model.lower():
        return None
    text = reply_text(entry)
    if DOWNSHIFT.search(text):
        return None
    return (
        "GUARDRAIL — the week's Claude allowance is nearly spent, and this turn ran "
        "on %s.\n\n"
        "Add the downshift line, addressed to him by name, as its own line:\n\n"
        "    Garrett — go down to Sonnet for this. (Say \"stay on Opus\" to override.)\n\n"
        "This is house-rules 2a's soft lock, hardened only while the budget is at "
        "its ceiling. It does not change the model — nothing can do that but "
        "Garrett — it just refuses to let the turn end without saying so."
        % model)


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

def self_test():
    import tempfile
    fails, total = [], 0

    def check(cond, label):
        nonlocal total
        total += 1
        if not cond:
            fails.append(label)

    today = dt.date(2026, 9, 16)
    now = dt.datetime(2026, 9, 16, 12, 0, tzinfo=dt.timezone.utc)
    ON = {"generatedFor": today.isoformat(), "lanesOff": ["push-batching", "opus"],
          "lanesOverridden": []}
    OFF = {"generatedFor": today.isoformat(), "lanesOff": [], "lanesOverridden": []}

    # --- which strings are a push at all ---
    check(is_push("git push -u origin my-branch"), "a plain push is a push")
    check(is_push("git push"), "a bare push is a push")
    check(is_push("cd x && git push origin HEAD"), "a push after && is a push")
    check(not is_push("git push --delete origin old"), "a branch DELETE sends nothing")
    check(not is_push("git status"), "status is not a push")
    check(not is_push("echo 'git push' >> notes.md"), "a push inside a quoted string is not one")
    check(not is_push(""), "an empty command is not a push")

    with tempfile.TemporaryDirectory() as tmp:
        log = os.path.join(tmp, "push-log.json")

        # --- the ABSENCE assertion, and the PLANTED PRESENCE beside it (6c) ---
        check(push_verdict("git push", "/r", OFF, now, log) is None,
              "lane open: the first push is allowed")
        check(push_verdict("git push", "/r", OFF, now, log) is None,
              "lane open: a SECOND push straight after is still allowed")

        log2 = os.path.join(tmp, "log2.json")
        check(push_verdict("git push", "/r", ON, now, log2) is None,
              "PLANTED, lane off: the first push is still allowed — nothing to batch yet")
        second = push_verdict("git push", "/r", ON, now + dt.timedelta(minutes=3), log2)
        check(second is not None and "batched" in second,
              "PLANTED, lane off: a push 3 minutes later is REFUSED")
        check("17 minute(s)" in second, "and it says how long is left")
        later = push_verdict("git push", "/r", ON,
                             now + dt.timedelta(minutes=25), log2)
        check(later is None, "past the cooldown the push goes through")

        # an override re-opens it
        log3 = os.path.join(tmp, "log3.json")
        OV = dict(ON, lanesOverridden=["push-batching"])
        push_verdict("git push", "/r", OV, now, log3)
        check(push_verdict("git push", "/r", OV, now + dt.timedelta(minutes=1), log3) is None,
              "an overridden lane does not refuse")

        # --- the state loader fails OPEN, in every direction, and says why ---
        st, why = find_state([os.path.join(tmp, "nope.json")], today)
        check(st is None and "nothing to enforce" in why, "no state file: stands down, and says so")

        stale = os.path.join(tmp, "stale.json")
        with open(stale, "w", encoding="utf-8") as fh:
            json.dump({"generatedFor": "2026-09-01", "lanesOff": ["push-batching"]}, fh)
        st, why = find_state([stale], today)
        check(st is None and "stale posture" in why, "a 15-day-old state must not enforce")

        broken = os.path.join(tmp, "broken.json")
        with open(broken, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        st, why = find_state([broken], today)
        check(st is None and "could not read" in why, "an unreadable state stands down, loudly")

        fresh = os.path.join(tmp, "fresh.json")
        with open(fresh, "w", encoding="utf-8") as fh:
            json.dump(ON, fh)
        st, why = find_state([fresh], today)
        check(st is not None and lane_is_off(st, "push-batching"),
              "PLANTED: a fresh state DOES switch the lane off — the gate can fire")

    # --- the model tier ---
    def turn(model, text):
        return [{"type": "assistant",
                 "message": {"model": model, "content": [{"type": "text", "text": text}]}}]

    check(tier_verdict(turn("claude-opus-5", "done"), OFF) is None,
          "lane open: an Opus turn is not touched")
    r = tier_verdict(turn("claude-opus-5", "done"), ON)
    check(r is not None and "go down to Sonnet" in r,
          "PLANTED, lane off: an Opus turn with no downshift line is refused")
    check(tier_verdict(turn("claude-opus-5",
                            "Garrett — go down to Sonnet for this."), ON) is None,
          "an Opus turn that DOES carry the line passes")
    check(tier_verdict(turn("claude-sonnet-5", "done"), ON) is None,
          "a Sonnet turn is never refused by the Opus lane")
    check(tier_verdict([], ON) is None, "an empty transcript stands down")
    check(tier_verdict(turn("", "done"), ON) is None, "an unknown model stands down")

    print("guardrail_gate self-test: %d checks, %d failed" % (total, len(fails)))
    for f in fails:
        print("  FAIL:", f)
    return 1 if fails else 0


# ---------------------------------------------------------------------------
# hook entry
# ---------------------------------------------------------------------------

def deny_payload(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())

    if "--state" in sys.argv:
        state, why = find_state()
        print("state: %s" % ("found at " + why if state else "NOT ENFORCING — " + why))
        if state:
            print("posture: %s" % state.get("posture"))
            print("lanes off: %s" % ", ".join(state.get("lanesOff") or []) or "none")
        sys.exit(0)

    if "--check" in sys.argv:
        idx = sys.argv.index("--check")
        cmd = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        state, _ = find_state()
        print(push_verdict(cmd, os.getcwd(), state, record=False) or "(allowed)")
        sys.exit(0)

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw else {}
    except Exception:
        sys.exit(0)
    if not isinstance(payload, dict):
        sys.exit(0)

    try:
        state, _ = find_state()
        if state is None:
            sys.exit(0)

        event = payload.get("hook_event_name") or ""
        if payload.get("tool_name") == "Bash" and event != "Stop":
            tool_input = payload.get("tool_input") or {}
            command = tool_input.get("command") if isinstance(tool_input, dict) else ""
            reason = push_verdict(command or "", payload.get("cwd"), state)
            if reason:
                json.dump(deny_payload(reason), sys.stdout)
            sys.exit(0)

        if event == "Stop":
            path = payload.get("transcript_path") or ""
            entries = []
            try:
                with open(path, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            try:
                                entries.append(json.loads(line))
                            except ValueError:
                                continue
            except OSError:
                sys.exit(0)
            reason = tier_verdict(entries, state)
            if reason:
                json.dump({"decision": "block", "reason": reason}, sys.stdout)
            sys.exit(0)
    except Exception:
        sys.exit(0)  # fail open: never trap a session over a guardrail

    sys.exit(0)


if __name__ == "__main__":
    main()
