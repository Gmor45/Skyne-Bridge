#!/usr/bin/env python3
"""reply_notes.py -- deliver the reply gate's reminders WHEN they help, not after.

RULED 2026-11-09 (Skyne DECISIONS.md). Garrett: "make the top three refusals
warn instead of refuse ... I do like claude via skyne knowing to do this - the
answer is WHEN so its not costing extra tokens".

A Stop-hook refusal arrives AFTER the reply is written, and costs a whole
extra turn (the chat is re-sent) to add one line. Measured that day: 9 forced
turns in one chat, at least 32 across 29 recent ones. This hook moves the
reminder to a moment where it costs nothing extra:

  UserPromptSubmit  -- if reply_gate.py saved a warning last turn, add ONE
                       short line to Garrett's next message, then forget it.
                       The lesson rides on a turn that was happening anyway.
  PostToolUse       -- right after a PR is opened or merged, remind Claude to
                       name the repo's open-PR and conflicting counts, BEFORE
                       it writes the reply. Matched in hooks.json to the two
                       GitHub PR tools only.

It never blocks anything: every path exits 0, and a bug prints nothing.

    python3 reply_notes.py --self-test
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PR_TOOLS = ("create_pull_request", "merge_pull_request")
PR_REMINDER = ("You just opened or merged a PR. In this reply, name that repo's "
               "open-PR count and how many are conflicting (house-rules 1e; "
               "data/open-prs.json perRepo), e.g. '4 open PRs, 1 conflicting'.")


def pending_notes(transcript_path):
    """Read and CLEAR the notes reply_gate.py queued. Each note is delivered once."""
    import reply_gate
    path = reply_gate.notes_path(transcript_path)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            keys = json.load(fh)
    except Exception:
        keys = []
    try:
        os.remove(path)
    except OSError:
        pass
    return [reply_gate.WARN_NOTE[k] for k in keys if k in reply_gate.WARN_NOTE]


def respond(payload):
    """The text to add for this event, or None. Pure apart from the notes file."""
    event = payload.get("hook_event_name") or ""
    if event == "PostToolUse":
        tool = payload.get("tool_name") or ""
        return PR_REMINDER if tool.endswith(PR_TOOLS) else None
    if event == "UserPromptSubmit":
        notes = pending_notes(payload.get("transcript_path") or "")
        return " ".join(notes) if notes else None
    return None


def emit(event, text):
    json.dump({"hookSpecificOutput": {"hookEventName": event,
                                      "additionalContext": text}}, sys.stdout)


def self_test():
    import tempfile
    import reply_gate
    fails = []

    def check(name, ok):
        print("  %-52s %s" % (name, "ok" if ok else "FAIL"))
        if not ok:
            fails.append(name)

    with tempfile.TemporaryDirectory() as d:
        os.environ["HOME"] = d
        tp = os.path.join(d, "t.jsonl")
        check("no queued note -> nothing added",
              respond({"hook_event_name": "UserPromptSubmit", "transcript_path": tp}) is None)
        reply_gate.save_notes(tp, ["companion", "pr-count"])
        got = respond({"hook_event_name": "UserPromptSubmit", "transcript_path": tp}) or ""
        check("a queued warning is delivered on the next message",
              "Companion" in got and "open-PR" in got)
        check("...exactly once",
              respond({"hook_event_name": "UserPromptSubmit", "transcript_path": tp}) is None)
        other = os.path.join(d, "other.jsonl")
        reply_gate.save_notes(tp, ["wrapups"])
        check("another chat's note is not delivered here",
              respond({"hook_event_name": "UserPromptSubmit", "transcript_path": other}) is None)
    check("opening a PR adds the backlog reminder before the reply",
          respond({"hook_event_name": "PostToolUse",
                   "tool_name": "mcp__github__create_pull_request"}) == PR_REMINDER)
    check("merging a PR adds it too",
          respond({"hook_event_name": "PostToolUse",
                   "tool_name": "mcp__github__merge_pull_request"}) == PR_REMINDER)
    check("any other tool adds nothing",
          respond({"hook_event_name": "PostToolUse", "tool_name": "Bash"}) is None)
    print("\n%s" % ("all checks passed" if not fails else "FAILED: %d" % len(fails)))
    return 1 if fails else 0


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        text = respond(payload)
        if text:
            emit(payload.get("hook_event_name"), text)
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
