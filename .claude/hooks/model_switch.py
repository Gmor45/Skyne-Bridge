#!/usr/bin/env python3
"""PostModelSwitch / PreModelSwitch hook: record every model change, forever.

WHY THIS EXISTS
---------------
House-rules 2 is the one rule in this estate that NO mechanism can enforce.
Only Garrett can type `/model`; saying it out loud is the entire
implementation. Rule 23 says so in as many words, and names the consequence:

    "Rule 2 is the case that proves the channel. It is the one rule here that
     no mechanism can ever enforce ... and until 2026-09-01 there was no record
     of it having worked even once. It works; nothing could see that."

That was true of ENFORCEMENT and it was wrongly generalised to OBSERVATION.
Claude Code has fired `PostModelSwitch` — carrying `from_model` and `to_model`
— for as long as this estate has been complaining that model changes leave no
trace. Rule 14 states the belief outright: "Model and effort in particular have
NO passive signal: Garrett runs /model locally and nothing tells you it
happened." The first half of that is now false, and this file is the correction.

WHAT IT DOES, AND THE ONE THING IT DOES NOT
-------------------------------------------
It appends one line per model change to a durable log and exits. That is all.
It NEVER blocks, and that is a decision rather than a limitation:

  * `PostModelSwitch` cannot block by design — it is observational.
  * `PreModelSwitch` CAN block, and this hook deliberately does not use it.
    Blocking a switch Garrett asked for would be hostile, and deciding which
    switches to block needs a judgement about the task that no shell script
    has. Wiring a capability because it exists is exactly the failure
    house-rules 22 warns about. The block stays unused, on purpose.

`PreModelSwitch` is registered anyway, for one narrow reason: it fires on a
switch that was REQUESTED, and `PostModelSwitch` only on one that LANDED. A
request with no landing is Garrett trying to downshift and it not taking, which
is a fact worth having and is invisible from the Post event alone.

WHAT IT CANNOT SEE, STATED PLAINLY
-----------------------------------
**Effort/thinking tier is not in the payload.** The hook receives model names
and nothing else, so `opus-high -> opus-low` is invisible to it. Rule 2 is about
model AND tier, and this covers one of the two. Saying so is the point:
house-rules 21 point 5 forbids shipping a coarse gate and calling the rest
covered, and a log that silently omitted half its subject would read exactly
like a log that had nothing to report.

FAIL-OPEN, ALWAYS
-----------------
Every error path exits 0 and writes nothing. A hook that can break a session in
order to record a statistic has its priorities backwards.

    python3 model_switch.py --self-test
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import sys

# Where the log lives. User-level rather than in a repo, because a model change
# is a fact about the SESSION and not about whichever checkout happened to be
# open — and because a repo path would simply not exist on half the surfaces
# this runs on.
DEFAULT_LOG = pathlib.Path.home() / ".claude" / "skyne" / "model-switches.jsonl"
ENV_LOG = "SKYNE_MODEL_LOG"

# Family rank, so a row can say UP or DOWN rather than making every future
# reader re-derive it. Deliberately coarse: this answers "which way", not
# "how far", and a table pretending to rank point releases would go stale.
FAMILY_RANK = {"haiku": 1, "sonnet": 2, "opus": 3}

# Garrett is in Georgia; the container is UTC. Rule 19 — an off-by-one date in
# a ledger keyed by date is not cosmetic.
LOCAL_TZ = "America/New_York"


def log_path() -> pathlib.Path:
    override = os.environ.get(ENV_LOG, "").strip()
    return pathlib.Path(override) if override else DEFAULT_LOG


def family(model: str | None) -> str | None:
    """The family a canonical model name belongs to, or None if unrecognised."""
    if not model:
        return None
    low = str(model).lower()
    for name in FAMILY_RANK:
        if name in low:
            return name
    return None


def direction(from_model: str | None, to_model: str | None) -> str:
    """UP, DOWN, noop, or unknown — never a guess dressed as a fact.

    `unknown` is a real answer and is reported as loudly as the others: a new
    model family this table has never heard of must not silently score as
    'noop', which is what a dict.get(..., 0) would have done.
    """
    a, b = family(from_model), family(to_model)
    if from_model and to_model and str(from_model) == str(to_model):
        return "noop"
    if a is None or b is None:
        return "unknown"
    if FAMILY_RANK[b] > FAMILY_RANK[a]:
        return "up"
    if FAMILY_RANK[b] < FAMILY_RANK[a]:
        return "down"
    return "noop"


def build_row(payload: dict, now: _dt.datetime | None = None) -> dict:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        local_date = now.astimezone(ZoneInfo(LOCAL_TZ)).strftime("%Y-%m-%d")
    except Exception:
        local_date = None       # named, not silently swapped for the UTC date

    frm = payload.get("from_model")
    to = payload.get("to_model")
    return {
        "utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "local_date": local_date,
        "event": payload.get("hook_event_name"),
        "from_model": frm,
        "to_model": to,
        "direction": direction(frm, to),
        "session_id": payload.get("session_id"),
        "cwd": payload.get("cwd"),
        # Recorded so no future reader mistakes this for a tier log. Rule 2 is
        # about model AND effort; the payload carries only the first.
        "effort_visible": False,
    }


def append(row: dict, path: pathlib.Path | None = None) -> None:
    path = path or log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def run() -> None:
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
    if not isinstance(payload, dict):
        return
    # A payload with neither model field is not a model switch. Writing a row
    # of nulls would pad the log with entries that look like data.
    if payload.get("from_model") is None and payload.get("to_model") is None:
        return
    append(build_row(payload))


def report(path: pathlib.Path | None = None, limit: int = 20) -> int:
    """Read the log back. A write-only log is a silent backlog, not a mechanism.

    The counts are the point: rule 2's win:miss ratio has been computed by hand
    until now, and by hand means "when somebody remembers to".
    """
    path = path or log_path()
    if not path.is_file():
        print(f"no model-switch log yet at {path}")
        print("This is a calm zero, not a failure — it means no switch has been "
              "recorded since the hook was installed.")
        return 0

    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"direction": "corrupt", "utc": "?", "event": "?"})

    landed = [r for r in rows if r.get("event") == "PostModelSwitch"]
    counts: dict[str, int] = {}
    for r in landed:
        counts[r.get("direction", "unknown")] = counts.get(r.get("direction", "unknown"), 0) + 1

    print(f"model switches — {path}")
    print(f"  {len(rows)} row(s), {len(landed)} landed")
    for key in ("down", "up", "noop", "unknown", "corrupt"):
        if counts.get(key):
            print(f"    {key:<8} {counts[key]}")
    if not landed:
        print("    (none landed yet)")

    # A requested switch with no landed counterpart is Garrett trying to change
    # tier and it not taking. Invisible from the Post event alone.
    requested = [r for r in rows if r.get("event") == "PreModelSwitch"]
    if len(requested) > len(landed):
        print(f"  !! {len(requested) - len(landed)} requested switch(es) with no "
              f"landing — a downshift that did not take is still a downshift missed")

    print("\n  NOTE: effort/thinking tier is NOT in the payload and is not logged. "
          "Rule 2 covers model AND tier; this covers model.")

    if rows:
        print(f"\n  last {min(limit, len(rows))}:")
        for r in rows[-limit:]:
            print(f"    {r.get('utc','?')}  {str(r.get('direction','?')):<8} "
                  f"{r.get('from_model')} -> {r.get('to_model')}  ({r.get('event')})")
    return 0


def self_test() -> int:
    import tempfile

    fails: list[str] = []

    def check(ok: bool, msg: str) -> None:
        if not ok:
            fails.append(msg)

    # --- direction is the field every future reader depends on --------------
    check(direction("claude-opus-5", "claude-sonnet-5") == "down",
          "opus -> sonnet must be DOWN — this is rule 2's whole question")
    check(direction("claude-sonnet-5", "claude-opus-5") == "up",
          "sonnet -> opus must be UP")
    check(direction("claude-sonnet-5", "claude-haiku-4-5") == "down",
          "sonnet -> haiku must be DOWN")
    check(direction("claude-opus-5", "claude-opus-4-6") == "noop",
          "a switch inside one family is not a tier change this hook can see")
    check(direction("claude-opus-5", "claude-opus-5") == "noop",
          "an identical restore must be noop, not a switch")
    # the trap: an unheard-of family must NOT score as noop
    check(direction("claude-opus-5", "claude-brandnew-9") == "unknown",
          "an unrecognised model must be UNKNOWN, never quietly noop")
    check(direction(None, "claude-opus-5") == "unknown",
          "a missing side is unknown, not a direction")

    # --- a row carries what the ledger needs --------------------------------
    row = build_row({"hook_event_name": "PostModelSwitch",
                     "from_model": "claude-opus-5",
                     "to_model": "claude-sonnet-5",
                     "session_id": "s1", "cwd": "/home/user/skyne"})
    for key in ("utc", "local_date", "event", "from_model", "to_model",
                "direction", "session_id", "cwd", "effort_visible"):
        check(key in row, f"a row must carry {key!r}")
    check(row["direction"] == "down", "the row must carry the computed direction")
    check(row["effort_visible"] is False,
          "a row must declare that effort/tier was NOT observed — half of "
          "rule 2 is invisible here and the log must say so")
    check(row["local_date"] is not None,
          "a row must carry Garrett's local date, not only the container's UTC")

    # --- writing, and never on a non-switch ---------------------------------
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "nested" / "switches.jsonl"
        append(row, p)
        append(row, p)
        check(p.is_file(), "append must create the log and its parent directory")
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        check(len(lines) == 2, f"append must add one line per call, got {len(lines)}")
        check(json.loads(lines[0])["direction"] == "down",
              "each line must be valid JSON carrying the row")

        os.environ[ENV_LOG] = str(p)
        try:
            saved_stdin = sys.stdin
            import io
            # a payload with no model fields must write NOTHING
            sys.stdin = io.StringIO(json.dumps({"hook_event_name": "PostModelSwitch"}))
            run()
            sys.stdin = saved_stdin
            after = p.read_text(encoding="utf-8").strip().splitlines()
            check(len(after) == 2,
                  "a payload carrying no model fields must not append a row of nulls")

            sys.stdin = io.StringIO(json.dumps(
                {"hook_event_name": "PreModelSwitch",
                 "from_model": "claude-opus-5", "to_model": "claude-haiku-4-5"}))
            run()
            sys.stdin = saved_stdin
            after = p.read_text(encoding="utf-8").strip().splitlines()
            check(len(after) == 3, "a real switch must append")
            check(json.loads(after[-1])["event"] == "PreModelSwitch",
                  "the row must record WHICH event fired — a requested switch "
                  "and a landed one are different facts")
        finally:
            sys.stdin = saved_stdin
            del os.environ[ENV_LOG]

    # --- the reader exists and survives a corrupt line ----------------------
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "r.jsonl"
        p.write_text(json.dumps(build_row({
            "hook_event_name": "PostModelSwitch",
            "from_model": "claude-opus-5", "to_model": "claude-sonnet-5"})) +
            "\n{ this is not json\n", encoding="utf-8")
        import contextlib, io as _io
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            report(p)
        out = buf.getvalue()
        check("down" in out, "the report must count a downshift")
        check("corrupt" in out, "a corrupt line must be counted, never skipped silently")
        check("effort" in out.lower(),
              "the report must say tier is not covered, every time it is read")

        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            report(pathlib.Path(td) / "nothing.jsonl")
        check("calm zero" in buf.getvalue(),
              "an empty log and a broken reader must not look the same")

    for f in fails:
        print("FAIL:", f)
    print("model_switch self-test: PASS" if not fails
          else f"model_switch self-test: {len(fails)} FAILED")
    return 0 if not fails else 1


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    if "--report" in sys.argv:
        return report()
    try:
        run()
    except Exception as exc:   # never break a session to record a statistic
        sys.stderr.write("model_switch skipped: %s\n" % type(exc).__name__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
