#!/usr/bin/env python3
"""wince_gate.py -- Stop: a W finished and Wince did not follow it, or Wince graded and nobody filed it.

RULED 2026-10-12 (Skyne DECISIONS.md). Garrett: *"From now on I want Wince to
follow every other W when they do something."* Then, on how: *"Check output not
steps. But if it finds issues in output, it should work backwards to look at
process"*, and on whether this check was optional: *"Hook enforces everything
is supposed to be a standing skyne rule you shouldn't have to propose that you
should have done it from the start."* So this hook is part of the ruling, not an
option on it (house-rules 21).

WHAT IT CATCHES
---------------
A reply is refused ONCE when, since Garrett's last message, a Skyne Family W
other than Wince finished a run and no Wince run finished after it. The refusal
names the W(s) and tells the session to send Wince over that output before
replying: output first, and where Wince finds a problem, back to the process
that made it.

WHERE IT LOOKS, IN ORDER
------------------------
1. `w_ran.py`'s log (~/.claude/skyne/w-runs.jsonl, or $SKYNE_W_RUNS_LOG): stop
   rows for THIS session since the last user message, ordered by when each run
   FINISHED. Authoritative when present, because it sees a W that ran in the
   background and finished later, and it orders by completion, not by launch
   (Wince launched beside a W, in parallel, has not critiqued its output).
2. The transcript, when the log has nothing for this session (a cloud
   container, or w_ran.py not delivered): Agent/Task calls in the main loop
   since the last user message, in call order.
Neither needs `prompt_id`, which no hook in this repo has ever been shown to
receive -- measured 2026-10-12, no log on the machine and only fake ids in tests.

AND A WINCE GRADE NOBODY FILED (added 2026-10-14)
-------------------------------------------------
Garrett: *"if Wince gives it an F and it never changes then why did I do it?"*
Skyne's `scripts/wince_grades.py` records every pass, but nothing made a
session run it, so a grade that went nowhere left no trace. This refuses a
reply -- at most once a turn, and again every turn until it is dealt with --
when a Wince run FINISHED in this session after the last command naming
`wince_grades` (`wince_grades.py add`, or an inline script that imports it).
Finished means: a synchronous Agent call whose result came back, or a `stop`
row in w_ran.py's log -- so a Wince still running in the background is never
owed yet. A Wince run that was not a graded pass (a prose critique, say) is
let through once the reply has a line starting "no grade to file:" and a reason.

WHAT IT DOES NOT DO (house-rules 21 point 5)
--------------------------------------------
- It sees the register writer's NAME in a shell command after the grade --
  not that the command ran, succeeded, or wrote this grade. A `cat` of the
  script, or an `add` the register refused, reads as filed. And one filing
  covers every grade before it (a single script often records several), so
  two grades and one filing pass. The escape works the same way: one
  "no grade to file:" line covers every grade before it, real ones included.
  Like the register itself, what a session types about its own work is
  trusted.
- A script SAVED to a file and run by name (`python3 seed.py`) is not seen
  even if it imports the writer; the session gets refused and files with a
  command that names it.
- With no w_ran.py log (a cloud container, or the plugin not delivered), a
  Wince run in the BACKGROUND is never seen finishing -- the transcript only
  shows "Async agent launched" -- so it is never owed. Only synchronous runs
  are caught on that path.
- A W run as a generic agent (a session without Bridge's plugin has no W agent
  types) is invisible to both sources. Bridge's agent files and every product's
  family pointer tell the session to say so rather than pretend.
- It proves Wince RAN after the W, never that Wince read that W's output. The
  refusal says which output; the critique itself is still Wince's.
- It does not critique Garrett. That lens is Wince's, on request; nothing here
  fires on his messages.
- A `research` skill run is seen only in the transcript. Where w_ran.py's log
  has rows for the turn (it logs agents, not skills), the log wins and a
  research run is missed if another W also ran and Wince followed that W.

CHECKED ONLY (RULED 2026-11-19, Skyne DECISIONS; ends the wide trial below early)
-------------------------------------------------------------------------------
The label and publish triggers below are RETIRED. What owes the follow-up now is
a turn that marks a Plan board feature's Checked stage done (an ArtifactData
write that sets a fresh stageDates.checked date, see w_follow.CheckedWatch). Checked is defined on the board as "Passed
Wince and Wren", so Wren runs first and ONE Wince pass after him. Measured
before the change: 99 of 119 forced follow-ups since go-live included a label
or publish trigger, and 62 had nothing else, so about 62 of 119 go away. The agent-W trigger and the filed-check are unchanged. Labels and
publishes are still LOGGED (`old_rule`) so the cost tracker can show what the
retired rule would have fired on. Not seen: Garrett tapping Checked on the
board himself (that is his own sign-off), a mark written by a subagent or
a script, a Checked marked with no date, and Claude never marking Checked at
all. The trigger is Claude's own hand, so it can only catch a mark Claude makes.

STAGE 2 (RULED 2026-11-16, R5 R9 R10 R12 R19; plan Piece C; label/publish retired 2026-11-19)
-----------------------------------------------------------
Two NEW triggers join the agent-W one, and the filed-check is rebuilt:
* A reply LABELED as a W (first or newest text block of the turn, any label but
  "Claude:" and "Wince:") owes a Wince run that finished AFTER the turn's last
  Edit/Write/publish. A "Wince:" label is never a review: only a `wince` agent
  run counts.
* A PUBLISH (Artifact publish, not an asset upload; a Figma write tool from
  figma-tools.json) owes the same.
* When Wren is owed (wren_gate.py: a runnable publish, or a maker label in a
  turn that wrote a file) Wren runs first and ONE Wince pass grades the work and
  Wren's report, so Wince must finish after Wren too.
* The filed-check (PC): each Wince FINISH is accounted for separately and must
  be matched by a row whose SESSION is this session and whose time is after that
  finish, in `~/.claude/skyne/wince-grades-queue.jsonl` (via `wince_grades.py
  queue`) or a register (via `add`/a flush); a red-team lens-4 run (the prompt
  carries `[red-team lens 4: <loop id>]`, joined to its agent id through the
  Agent result's `toolUseResult.agentId`) by a `redteam_rounds.py` row for that
  loop or by its own grade row (the round can be filed only once all four
  reviewers are in; W red team round 2). Each filing counts once wherever it is
  seen. Typing the script's NAME no longer counts. One filing covers one
  finish. `no grade to file: <why>` still accounts for the finishes before it.
* The round record (RULED 2026-11-20): when lenses 1 to 4 of a red-team loop
  (each prompt tagged `[red-team lens N: <loop id>]`) have ALL finished since
  that loop's last round row, a `redteam_rounds.py` row for the loop is owed.
  A round still running owes nothing, so lens 4 finishing first is not refused.
  Background lenses finish at the task-notification naming their tool-use id.
* The switch `~/.claude/skyne/w-follow-mode` (w_follow.py): `log` makes the NEW
  triggers record "would have refused" and refuse nothing. The agent-W trigger,
  unbacked overrules and the filed-check keep blocking either way (R10).
* Every call writes a row to `~/.claude/skyne/w-follow.jsonl`.
* In the cloud the new triggers only LOG (w_follow.cloud_enforces) and the old
  filed-check rules apply: R12 is NOT live there until a cloud session has
  confirmed delivery and the attended/scheduled signal.

HOW A REFUSAL IS SENT (W red team round 1, 2026-11-20)
-----------------------------------------------------
As `hookSpecificOutput.additionalContext`, not `decision: "block"`. Claude Code's
hooks doc: additionalContext on Stop is "Non-error feedback for Claude. The
conversation continues so Claude can act on it, but unlike decision: "block" it
is shown in the transcript as hook feedback rather than a hook error", with the
same `stop_hook_active` and 8-continuation protections. Garrett saw 80+ red
"hook error" notices a day for the gate doing its job. The text opens with one
plain line telling him there is nothing for him to do, and carries no rule
numbers, plugin ids or the off switch (the switch is his, R10).

NEVER TRAPS A SESSION
---------------------
`stop_hook_active` (the platform's re-entry flag) means it already refused once
this turn: it allows (and logs "released"). An error prints nothing and exits 0,
and writes an `error` row to the log so the next session's heartbeat names it.

Usage:
    python3 wince_gate.py             # the hook (JSON on stdin)
    python3 wince_gate.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from w_ran import log_path, member  # noqa: E402  -- one W roster, one log path
    import w_follow  # noqa: E402  -- the switch, the log, publish detection, filings
    IMPORT_ERROR = None
except Exception as _exc:  # noqa: BLE001 -- W red team round 1: a broken import left no trace
    IMPORT_ERROR = _exc
    w_follow = None


def _raw_error_row(gate: str, exc: BaseException) -> None:
    """Write an error row with nothing but the standard library (w_follow may be what broke)."""
    try:
        import datetime as _dt
        path = os.environ.get("SKYNE_W_FOLLOW_LOG") or os.path.join(
            os.path.expanduser("~"), ".claude", "skyne", "w-follow.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        row = {"utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "gate": gate, "action": "error", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    except Exception:  # noqa: BLE001
        pass


LEAD = ("Claude owes a Wince/Wren follow-up before it finishes. Nothing for you "
        "to do, Garrett: this is Claude's checklist.")


def hook_output(out: dict | None) -> dict | None:
    """The gate's verdict as the JSON a Stop hook prints: non-error feedback."""
    if not out:
        return None
    return {"hookSpecificOutput": {"hookEventName": "Stop",
                                   "additionalContext": LEAD + "\n\n" + out["reason"]}}

CRITIC = "wince"


def read_jsonl(path: str) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a half-written tail line
                if isinstance(row, dict):
                    out.append(row)
    except OSError:
        return []
    return out


def review_floor(entries: list[dict], b: int) -> tuple[str, dict]:
    """(start of the turn BEFORE this one, the facts from then to now). A Wince or
    Wren run since then can cover a Checked mark made this turn (W red team round 2)."""
    prev = last_user_boundary(entries[:b]) if b > 0 else -1
    at = prev if prev >= 0 else b
    return str(entries[at].get("timestamp") or "")[:19], w_follow.turn_facts(entries, at)


def is_garrett_turn(e: dict) -> bool:
    """A user entry Garrett typed. A background agent's finish arrives as a user
    entry too (origin kind "task-notification", promptSource "system"); counting
    it as his turn moved the review floor past a Wince that had just run, so the
    Checked mark after his "yes" was refused (W red team round 3, transcript
    1fbee306: Wince 16:09:00, its notification 16:09:04, "yes" 16:12). An entry
    with no origin (older transcripts) is his."""
    if (e.get("type") != "user" or e.get("isMeta") or e.get("toolUseResult")
            or e.get("isSidechain")):
        return False
    kind = (e.get("origin") or {}).get("kind")
    if kind and kind != "human":
        return False
    content = (e.get("message") or {}).get("content")
    return not (isinstance(content, str) and content.lstrip().startswith("<task-notification>"))


def last_user_boundary(entries: list[dict]) -> int:
    """Index of the newest turn Garrett typed (see is_garrett_turn)."""
    for i in range(len(entries) - 1, -1, -1):
        if is_garrett_turn(entries[i]):
            return i
    return -1


# A research run is graded like a W's output (RULED 2026-10-17): the
# `research` skill wraps Anthropic's `deep-research`, which spawns GENERIC
# agents, so without this it would be the one big output Wince never saw.
RESEARCH_SKILLS = ("research", "deep-research")


def from_transcript(entries: list[dict], boundary: int) -> list[str]:
    """W ids called from the main loop since the boundary, in call order.
    A research skill run counts as the pseudo-W "research"."""
    order = []
    for e in entries[boundary + 1:]:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for blk in content:
            if not (isinstance(blk, dict) and blk.get("type") == "tool_use"):
                continue
            if blk.get("name") in ("Agent", "Task"):
                w = member((blk.get("input") or {}).get("subagent_type"))
                if w:
                    order.append(w)
            elif (blk.get("name") == "Skill" and str((blk.get("input") or {}).get(
                    "skill") or "").split(":")[-1] in RESEARCH_SKILLS):
                order.append("research")
    return order


def from_log(rows: list[dict], session_id: str, since_utc: str) -> list[str]:
    """W ids that FINISHED in this session since `since_utc`, in finish order."""
    stops = [r for r in rows
             if r.get("event") == "stop" and r.get("w")
             and r.get("session_id") == session_id
             and str(r.get("utc") or "") >= since_utc]
    stops.sort(key=lambda r: str(r.get("utc")))  # stable: file order breaks ties
    return [r["w"] for r in stops]


def unfollowed(order: list[str]) -> list[str]:
    """The non-critic Ws with no critic run after the last of them."""
    last_other = max((i for i, w in enumerate(order) if w != CRITIC), default=-1)
    if last_other < 0:
        return []
    if any(w == CRITIC for w in order[last_other + 1:]):
        return []
    seen = []
    for w in order:
        if w != CRITIC and w not in seen:
            seen.append(w)
    return seen


def refusal(ws: list[str], source: str) -> str:
    names = ", ".join(w.capitalize() for w in ws)
    return (f"Wince follows every W: {names} finished this turn "
            f"and no Wince run came after it ({source}). Before Claude finishes, run the "
            f"`wince` agent on that output: grade the "
            f"OUTPUT first, against what that W's output is for, and where it finds "
            f"a problem, work back to the process that produced it. Wince grades and "
            f"names problems; it never rewrites. If Wince is unavailable in this "
            f"session, say so in one line instead.")


FILER = "wince_grades"            # Skyne's register writer, in any invocation
# The stated escape: a LINE that starts "no grade to file:" and gives a reason.
# Starting its own line is what tells using the escape from describing it --
# prose, a quoted refusal or a code block that mentions it mid-line does not
# count (Wince, passes 2 and 3). The reason must be real text: the refusal's
# own placeholder "<why>" is not one.
NO_GRADE = re.compile(r"^[ \t>*_-]*no grade to file:[ \t]*[^\s\"'<>]", re.I | re.M)
SHELLS = ("Bash", "PowerShell")


def _ts(s) -> str:
    """Seconds-precision UTC, so transcript and log timestamps compare."""
    return str(s or "")[:19]


def wince_finishes(entries: list[dict], rows: list[dict], session: str) -> list[str]:   # legacy (cloud)
    """When each Wince run in this session FINISHED. The log when it has rows
    for this session, else the transcript -- the same precedence as the
    W-follow check, so one run is never counted twice (Wince, hook pass 1)."""
    # One row per (agent_id, finish time): w_ran.py registered twice writes the SAME
    # row twice, while a Wince continued with SendMessage finishes again LATER, and
    # each of those finishes is its own pass (W red team round 1, 2026-11-20).
    logged = {(r.get("agent_id"), _ts(r.get("utc"))) if r.get("agent_id") else (r.get("utc"), i):
              _ts(r.get("utc"))
              for i, r in enumerate(rows)
              if r.get("event") == "stop" and r.get("w") == CRITIC
              and r.get("session_id") == session}
    if logged:
        return [t for t in logged.values() if t]
    out, calls = [], set()
    for e in entries:
        if e.get("type") == "assistant" and not e.get("isSidechain"):
            for blk in (e.get("message") or {}).get("content") or []:
                if (isinstance(blk, dict) and blk.get("type") == "tool_use"
                        and blk.get("name") in ("Agent", "Task")
                        and member((blk.get("input") or {}).get("subagent_type")) == CRITIC):
                    calls.add(blk.get("id"))
        elif e.get("type") == "user" and calls:
            for blk in (e.get("message") or {}).get("content") or []:
                if (isinstance(blk, dict) and blk.get("type") == "tool_result"
                        and blk.get("tool_use_id") in calls
                        and "Async agent launched" not in json.dumps(blk.get("content"))):
                    out.append(_ts(e.get("timestamp")))
    return [t for t in out if t]


def last_accounted(entries: list[dict]) -> str:
    """The last moment every finished grade so far was accounted for: a shell
    command naming the register's writer, OR the main loop saying "no grade
    to file". Both move the same watermark, so an escape said once is not
    asked for again every later turn, and an escape said BEFORE a Wince run
    does not cover it (Wince, hook pass 1). '' if never."""
    last = ""
    for e in entries:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        for blk in (e.get("message") or {}).get("content") or []:
            if not isinstance(blk, dict):
                continue
            filed = (blk.get("type") == "tool_use" and blk.get("name") in SHELLS
                     and FILER in str((blk.get("input") or {}).get("command") or ""))
            escaped = (blk.get("type") == "text"
                       and bool(NO_GRADE.search(str(blk.get("text") or ""))))
            if filed or escaped:
                last = max(last, _ts(e.get("timestamp")))
    return last


def unfiled_grades(entries: list[dict], rows: list[dict], session: str) -> int:
    done = last_accounted(entries)
    return sum(1 for t in wince_finishes(entries, rows, session) if t > done)


def unbacked_overrules(session: str, since: str, path: str | None = None) -> int:
    """Overrules Wince made this turn that overrule_gate.py could not back."""
    p = path or os.environ.get("SKYNE_OVERRULES_LOG") or os.path.join(
        os.path.expanduser("~"), ".claude", "skyne", "overrules.jsonl")
    return sum(1 for r in read_jsonl(p) if r.get("status") == "unbacked"
               and r.get("session_id") == session and str(r.get("utc") or "") >= since)


# --------------------------------------------------------------- stage 2 logic

CLAUDE_LABEL = re.compile(r"^\s*Claude:\s")


def agent_runs(entries: list[dict], rows: list[dict], session: str, who: str,
               facts: dict | None = None) -> list[dict]:
    """Every FINISH of agent `who` in this session: {finish, agent_id, loop}.
    The w_ran log wins when it has rows for this session (it sees background
    runs, and gives each run's agent id); the transcript is the fallback and
    sees only synchronous results."""
    facts = facts or w_follow.turn_facts(entries, -1)
    seen, logged = set(), []
    for i, r in enumerate(rows):
        if (r.get("event") == "stop" and r.get("w") == who
                and r.get("session_id") == session
                and r.get("last_message_chars") != 0):   # said nothing = skipped, not done (round 3)
            # (agent, finish time): a double-registered hook writes the same row twice, but a
            # continued agent (SendMessage) finishes again later and that is a new pass
            # (W red team round 1: session ee79be7b was refused although Wince had re-finished).
            key = (r.get("agent_id"), _ts(r.get("utc"))) if r.get("agent_id") else (r.get("utc"), i)
            if key in seen:
                continue
            seen.add(key)
            logged.append({"finish": _ts(r.get("utc")), "agent_id": r.get("agent_id"),
                           "loop": facts["lens4_by_agent"].get(r.get("agent_id"))})
    logged = [x for x in logged if x["finish"]]
    if logged:
        return logged
    out, calls = [], {}
    for e in entries:
        if e.get("type") == "assistant" and not e.get("isSidechain"):
            for blk in (e.get("message") or {}).get("content") or []:
                if (isinstance(blk, dict) and blk.get("type") == "tool_use"
                        and blk.get("name") in ("Agent", "Task")
                        and member((blk.get("input") or {}).get("subagent_type")) == who):
                    calls[blk.get("id")] = blk
        elif e.get("type") == "user" and calls:
            for blk in (e.get("message") or {}).get("content") or []:
                if (isinstance(blk, dict) and blk.get("type") == "tool_result"
                        and blk.get("tool_use_id") in calls
                        and "Async agent launched" not in json.dumps(blk.get("content"))
                        and not blk.get("is_error")):    # a refused or failed call is not a run (round 3)
                    call = calls[blk["tool_use_id"]]
                    m = w_follow.LENS4_RX.search(str((call.get("input") or {}).get("prompt") or ""))
                    out.append({"finish": _ts(e.get("timestamp")), "agent_id": None,
                                "loop": m.group(1).strip() if m else None})
    return [x for x in out if x["finish"]]


def last_escape_ts(entries: list[dict]) -> str:
    """Newest main-loop line starting 'no grade to file: <reason>'."""
    last = ""
    for e in entries:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        for blk in (e.get("message") or {}).get("content") or []:
            if (isinstance(blk, dict) and blk.get("type") == "text"
                    and NO_GRADE.search(str(blk.get("text") or ""))):
                last = max(last, _ts(e.get("timestamp")))
    return last


FILER_PATH_RX = re.compile(r"""([A-Za-z]:[\\/][^\s"'`;&|]*?|/[^\s"'`;&|]*?|\.{1,2}[\\/][^\s"'`;&|]*?)[\\/]scripts[\\/](?:wince_grades|redteam_rounds)\.py""")
CD_RX = re.compile(r"""(?:^|&&|;|\n|\|\|)\s*(?:cd|Set-Location|git\s+-C)\s+("[^"]+"|'[^']+'|[^\s;&|]+)""")


def _norm_dir(path: str, base: str) -> str:
    path = path.strip().strip("'\"")
    m = re.match(r"^/([a-zA-Z])/(.*)$", path)          # Git Bash: /c/Users/... -> C:/Users/...
    if m and os.name == "nt":
        path = f"{m.group(1).upper()}:/{m.group(2)}"
    path = os.path.expanduser(path)
    if not os.path.isabs(path) and base:
        path = os.path.join(base, path)
    return os.path.normpath(path)


def filer_dirs(entries: list[dict]) -> list[str]:
    """Skyne checkouts this session ran the grade or round writer in (W red team round 1:
    an `add` run in a scratchpad clone was never seen, and the session was refused five
    times). Read from the shell commands that name the writer: the folder before
    scripts/<writer>.py, a `cd`/`git -C` folder, and the turn's own cwd."""
    found = []
    for e in entries:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        base = str(e.get("cwd") or "")
        for b in (e.get("message") or {}).get("content") or []:
            if not (isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in SHELLS):
                continue
            cmd = str((b.get("input") or {}).get("command") or "")
            if "wince_grades" not in cmd and "redteam_rounds" not in cmd:
                continue
            cands = [base] + [m.group(1) for m in FILER_PATH_RX.finditer(cmd)] \
                + [m.group(1) for m in CD_RX.finditer(cmd)]
            for c in cands:
                if not c:
                    continue
                d = _norm_dir(c, base)
                if os.path.isfile(os.path.join(d, "data", "wince-grades.json")) and d not in found:
                    found.append(d)
    return found


def register_candidates(cwd: str, extra: list[str] | None = None) -> list[str]:
    """Skyne checkouts whose registers may already hold this session's filings."""
    home = os.path.expanduser("~")
    roots = [cwd, os.environ.get("SKYNE_DIR", ""), os.path.join(home, "claude-audit-wt-live"),
             os.path.join(home, "claude-audit")] + list(extra or [])
    roots += [x for x in os.environ.get("SKYNE_EXTRA_ROOTS", "").split(os.pathsep) if x]
    return [r for r in dict.fromkeys(roots) if r and os.path.isdir(r)]


def origin_register_files(session: str, roots: list[str]) -> list[str]:
    """Copies of origin/main's registers (best effort, short timeouts) as temp
    files, so a filing that was flushed and dropped from the queue still counts."""
    import subprocess
    import tempfile
    out = []
    for root in roots:
        for rel in ("data/wince-grades.json", "data/redteam-rounds.json"):
            try:
                r = subprocess.run(["git", "-C", root, "show", f"origin/main:{rel}"],
                                   capture_output=True, text=True, timeout=4,
                                   stdin=subprocess.DEVNULL, encoding="utf-8")
            except (OSError, subprocess.SubprocessError):
                continue
            if r.returncode == 0 and session in r.stdout:
                fd, path = tempfile.mkstemp(suffix=".json", prefix="origin-reg-")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(r.stdout)
                out.append(path)
        # the checkout's own working registers count too (a worktree `add`)
        for rel in ("data/wince-grades.json", "data/redteam-rounds.json"):
            path = os.path.join(root, rel.replace("/", os.sep))
            if os.path.isfile(path):
                out.append(path)
    return out


def owed_filings(entries, rows, session, facts, cwd="") -> list[dict]:
    runs = agent_runs(entries, rows, session, CRITIC, facts)
    if not runs:
        return []
    esc = last_escape_ts(entries)
    fil = w_follow.filings(session)
    owed = w_follow.unfiled_runs(runs, fil, esc)
    if owed:
        # not in the queues: has a flush already moved them to a register?
        regs = origin_register_files(session, register_candidates(cwd, filer_dirs(entries)))
        extra = [x for x in os.environ.get("SKYNE_EXTRA_REGISTERS", "").split(os.pathsep) if x]
        try:
            owed = w_follow.unfiled_runs(runs, w_follow.filings(session, regs + extra), esc)
        finally:
            for pth in regs:
                if os.path.basename(pth).startswith("origin-reg-"):
                    try:
                        os.unlink(pth)
                    except OSError:
                        pass
    return owed


def owed_rounds(entries, session, cwd="") -> list[str]:
    """Red-team loops whose round is complete and unrecorded (RULED 2026-11-20)."""
    if not w_follow.lens_runs(entries):
        return []
    esc = last_escape_ts(entries)
    owed = w_follow.unfiled_rounds(entries, w_follow.filings(session), esc)
    if owed:
        regs = origin_register_files(session, register_candidates(cwd, filer_dirs(entries)))
        extra = [x for x in os.environ.get("SKYNE_EXTRA_REGISTERS", "").split(os.pathsep) if x]
        try:
            owed = w_follow.unfiled_rounds(entries, w_follow.filings(session, regs + extra), esc)
        finally:
            for pth in regs:
                if os.path.basename(pth).startswith("origin-reg-"):
                    try:
                        os.unlink(pth)
                    except OSError:
                        pass
    return owed


def evaluate(payload: dict, log_rows: list[dict] | None = None,
             overrules_path: str | None = None) -> dict | None:
    """Everything the gate knows about this turn. None if there is no turn."""
    entries = read_jsonl(str(payload.get("transcript_path") or ""))
    b = last_user_boundary(entries)
    if b < 0:
        return None
    since = str(entries[b].get("timestamp") or "")[:19] + "Z"
    since_s = since[:19]
    session = str(payload.get("session_id") or "")
    rows = read_jsonl(log_path()) if log_rows is None else log_rows
    mode, mode_note = w_follow.read_mode()
    cloud = w_follow.is_cloud()
    facts = w_follow.turn_facts(entries, b)
    all_facts = w_follow.turn_facts(entries, -1)        # whole session: lens-4 joins
    ev = {"session": session, "mode": mode, "mode_note": mode_note, "cloud": cloud,
          "facts": facts, "required": [], "always": [], "triggers": []}

    # --- checks that block today, mode or no mode ------------------------------
    n = unbacked_overrules(session, since, overrules_path) if session and len(since) == 20 else 0
    if n:
        ev["always"].append(
            f"Wince overruled {n} verdict(s) this turn without a receipt that holds up "
            f"(overrule_gate.py logged them as unbacked). Do not pass those verdicts on as "
            f"Wince's findings: tell Garrett in one line which ones are unbacked, or re-run "
            f"Wince on the W's full output.")
    legacy = cloud     # the cloud keeps the old name-in-a-command filed-check
    if legacy:
        owed = unfiled_grades(entries, rows, session) if session else 0
        if owed:
            ev["always"].append(
                f"{owed} Wince grade(s) finished in this session after the grade register "
                f"was last written. Record them in Skyne's register (python3 "
                f"scripts/wince_grades.py add ...; one command can record several), so a "
                f"grade that changed nothing still leaves a trace (RULED 2026-10-14). If a "
                f"Wince run was not a graded pass, say \"no grade to file: <why>\" in one line.")
            ev["triggers"].append("unfiled")
    elif session:
        owed = owed_filings(entries, rows, session, all_facts, str(payload.get("cwd") or ""))
        if owed:
            ev["always"].append(
                f"{len(owed)} Wince grade(s) finished in this session with no filing from THIS "
                f"session after it. File each one: `python3 scripts/wince_grades.py queue ...` (one "
                f"command per finish; for the critic run in a red-team review, its grade row "
                f"counts). Naming the script in a command does not count: the row has to reach the "
                f"queue (or a register in a skyne checkout this session ran the writer in). "
                f"If a Wince run was not a graded pass, say \"no grade to file: <why>\" in one line.")
            ev["triggers"].append("unfiled")
        rounds_owed = owed_rounds(entries, session, str(payload.get("cwd") or ""))
        if rounds_owed:
            ev["always"].append(
                f"Red-team review {', '.join(rounds_owed)}: all four reviewers have finished, but "
                f"the round is not recorded. Record it before Claude finishes: `python3 "
                f"scripts/redteam_rounds.py queue ...` with the four lenses' findings and Wince's "
                f"letter. The 3-round limit counts these records, so an unrecorded round cannot "
                f"be counted (RULED 2026-11-20). If it was not a real round, say \"no grade to "
                f"file: <why>\" in one line.")
            ev["triggers"].append("round-unfiled")

    # --- the agent-W trigger (as before) ----------------------------------------
    order = from_log(rows, session, since) if session and len(since) == 20 else []
    source = "w_ran log"
    if not order:
        order, source = from_transcript(entries, b), "transcript"
    ws = unfollowed(order)
    if ws:
        ev["always"].append(refusal(ws, source))
        ev["triggers"].append("agent-w")

    # --- the Checked trigger (RULED 2026-11-19), under the switch ---------------
    labels = facts["labels"] - {"Wince"}
    pubs = facts["publishes"]
    first_last = [facts["first_text"], facts["last_text"]]
    ev["labeled"] = bool(labels)
    ev["claude_wrote"] = bool(facts["writes"]) and any(CLAUDE_LABEL.match(t) for t in first_last)
    ev["old_rule"] = bool(labels or pubs)   # logged only: what the retired wide trial would have fired on
    why = []
    marked = sorted({fid for _, fid in facts["checked"]})
    if marked:
        why.append("a Plan board feature marked Checked (" + ", ".join(marked) + ")")
        ev["triggers"].append("checked")
    wren_owed = False
    if why:
        import wren_gate
        wren_owed = wren_gate.wren_owed(facts, entries, b)
        # A review in the turn BEFORE the mark counts (review, Garrett says yes, Claude
        # marks Checked next turn); the work must not have changed since it.
        floor, recent = review_floor(entries, b)
        wren_runs = agent_runs(entries, rows, session, "wren", all_facts)
        wren_done = [r["finish"] for r in wren_runs if r["finish"] >= floor]
        wren_last = wren_done[-1] if wren_done else ""
        need = max(w_follow.last_work_ts(recent), wren_last, floor)
        mine = [r["finish"] for r in agent_runs(entries, rows, session, CRITIC, all_facts)
                if r["finish"] >= floor]
        satisfied = any(f >= need for f in mine)
        ev["wren_owed"] = wren_owed
        ev["satisfied"] = satisfied
        if not satisfied:
            ev["required"].append(
                "W follow-up (Checked on the Plan board means it passed Wince and Wren): this turn has "
                + " and ".join(why) + f", and no `wince` agent run has finished since "
                f"{'the work was last changed' if not wren_owed else 'the work was made and Wren tried it'}. "
                + ("Run the `wren` agent first (he tries what was made, the lazy way), then ONE "
                   "`wince` pass over the work AND Wren's report. " if wren_owed else
                   "Run the `wince` agent on the work before Claude finishes: "
                   "grade the OUTPUT first, work back to the process where it finds a problem. ")
                + "A \"Wince:\" label is not a review; only a run of the agent counts. "
                  "Wince grades and names problems, it never rewrites. If the work was "
                  "answered in a few words and nothing was made, say so plainly.")
    if facts["unknown_figma"]:
        ev["note_figma"] = (f"Unknown Figma tool(s) used: {', '.join(sorted(set(facts['unknown_figma'])))}. "
                            f"Classify them in .claude/hooks/figma-tools.json (write/read/excluded) "
                            f"so a publish through them triggers the follow-up.")
    return ev


def decide(payload: dict, log_rows: list[dict] | None = None,
           overrules_path: str | None = None, log_it: bool = True) -> dict | None:
    ev = evaluate(payload, log_rows, overrules_path)
    if ev is None:
        return None
    enforce_new = ev["mode"] == "enforce" and w_follow.cloud_enforces()
    reasons = list(ev["always"])
    if enforce_new:
        reasons += ev["required"]
    out = None
    action = "quiet"
    if reasons:
        # One refusal a turn is all a Stop hook gets (stop_hook_active lets the
        # next one through), so every debt goes in it or the next is dropped.
        extra = [x for x in (ev.get("note_figma"),) if x]   # the mode note is a start-up line
        out = {"decision": "block", "reason": " ALSO: ".join(reasons + extra)}
        action = "refused"
    elif ev["required"]:
        action = "log-would-refuse"
    elif ev["triggers"]:
        action = "satisfied"
    if payload.get("stop_hook_active"):
        if out:
            action = "released"
        out = None
    if log_it:
        w_follow.log_row({"gate": "wince", "action": action, "mode": ev["mode"],
                          "cloud": ev["cloud"], "session_id": ev["session"],
                          "triggers": sorted(set(ev["triggers"])),
                          "owed_new": bool(ev["required"]), "labeled": ev["labeled"],
                          "old_rule": ev.get("old_rule", False),
                          "claude_wrote": ev["claude_wrote"],
                          "unknown_figma": sorted(set(ev["facts"]["unknown_figma"]))})
        if ev["mode"] == "enforce" and ev["session"] and not ev["cloud"]:
            w_follow.record_golive()
    return out



def main() -> int:
    if IMPORT_ERROR is not None:
        _raw_error_row("wince", IMPORT_ERROR)
        return 0
    try:
        raw = sys.stdin.read() or "{}"
        try:
            payload = json.loads(raw)
        except ValueError:
            return 0            # not a hook call: nothing to judge, nothing to log
        out = decide(payload) if isinstance(payload, dict) else None
        if out:
            print(json.dumps(hook_output(out)))
    except Exception as exc:  # noqa: BLE001 -- a gate must never cost a turn
        w_follow.log_error("wince", exc)
    return 0


def self_test() -> int:
    import subprocess
    import tempfile
    ran, fails = [], []
    _scratch = tempfile.mkdtemp(prefix="wince-gate-test-")
    for _k, _v in (("SKYNE_W_FOLLOW_LOG", "w-follow.jsonl"), ("SKYNE_W_FOLLOW_MODE", "mode"),
                   ("SKYNE_W_FOLLOW_GOLIVE", "golive.json"), ("SKYNE_GRADES_QUEUE", "gq.jsonl"),
                   ("SKYNE_ROUNDS_QUEUE", "rq.jsonl")):
        os.environ[_k] = os.path.join(_scratch, _v)
    os.environ["SKYNE_EXTRA_ROOTS"] = os.path.join(_scratch, "none")
    # Everything up to the "STAGE 2" marker below is the cloud / legacy path: the old
    # name-in-a-command filed-check, which the cloud keeps. Stage-2 tests clear this.
    os.environ["CLAUDE_CODE_REMOTE"] = "true"

    def check(ok, label):
        ran.append(label)
        if not ok:
            fails.append(label)
        print(("  ok   " if ok else "  FAIL ") + label)

    check(unfollowed([]) == [], "no W ran: nothing owed")
    check(unfollowed(["wince"]) == [], "only Wince ran: nothing owed")
    check(unfollowed(["wander", "wince"]) == [], "a W followed by Wince is clean")
    check(unfollowed(["wander"]) == ["wander"], "PLANTED: a W with no Wince is caught")
    check(unfollowed(["wince", "wander"]) == ["wander"],
          "PLANTED: Wince BEFORE the W does not count -- it cannot have read the output")
    check(unfollowed(["wander", "wince", "wistin"]) == ["wander", "wistin"],
          "PLANTED: a second W after the critique owes its own Wince, and both are named")
    check(member("load-house-rules:Wince") == "wince" and member("general-purpose") is None,
          "the plugin-prefixed agent type resolves; a generic agent is not a W")

    t0 = "2026-10-12T16:00:00.000Z"
    user = {"type": "user", "timestamp": t0, "message": {"content": "go"}}

    def call(w):
        return {"type": "assistant", "timestamp": t0, "message": {"content": [
            {"type": "tool_use", "name": "Agent",
             "input": {"subagent_type": f"load-house-rules:{w}", "prompt": "x"}}]}}
    tool_result = {"type": "user", "toolUseResult": {"x": 1}, "timestamp": t0,
                   "message": {"content": [{"type": "tool_result"}]}}
    sidechain = dict(call("wince"), isSidechain=True)

    with tempfile.TemporaryDirectory() as d:
        # never read this machine's real overrule log during a self-test
        os.environ["SKYNE_OVERRULES_LOG"] = os.path.join(d, "no-such-log.jsonl")

        def transcript(*entries, session_id="s1"):
            p = os.path.join(d, "t.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for e in entries:
                    f.write(json.dumps(e) + "\n")
            return {"transcript_path": p, "session_id": session_id}

        check(decide(transcript(user, call("wander"), tool_result, call("wince")), []) is None,
              "transcript: W then Wince allows")
        out = decide(transcript(user, call("wander"), tool_result), [])
        check(bool(out) and out["decision"] == "block" and "Wander" in out["reason"],
              "PLANTED: transcript: a W with no Wince is refused, naming the W")
        check(decide(transcript(user, call("wander"), sidechain), []) is not None,
              "PLANTED: a Wince call inside a subagent's sidechain does not count for the main loop")
        old = {"type": "user", "timestamp": "2026-10-12T15:00:00.000Z",
               "message": {"content": "earlier"}}
        check(decide(transcript(old, call("wander"), tool_result, user), []) is None,
              "a W from an EARLIER turn is not this turn's debt")
        p = transcript(user, call("wander"), tool_result)
        check(decide(dict(p, stop_hook_active=True), []) is None,
              "already refused once this turn: it allows (never traps a session)")

        def skill(name):
            return {"type": "assistant", "timestamp": t0, "message": {"content": [
                {"type": "tool_use", "name": "Skill", "input": {"skill": name}}]}}
        out = decide(transcript(user, skill("research"), tool_result), [])
        check(bool(out) and "Research" in out["reason"],
              "PLANTED: a research skill run with no Wince after it is refused")
        check(decide(transcript(user, skill("anthropic-skills:deep-research"), tool_result,
                                call("wince")), []) is None,
              "a deep-research run followed by Wince allows")
        check(decide(transcript(user, skill("handoff"), tool_result), []) is None,
              "an ordinary skill is not a W and owes Wince nothing")

        # the log: authoritative, ordered by finish, and per-session
        log = [{"event": "stop", "w": "wander", "session_id": "s1", "utc": "2026-10-12T16:00:05Z"},
               {"event": "stop", "w": "wince", "session_id": "s1", "utc": "2026-10-12T16:00:09Z"}]
        filed_late = {"type": "assistant", "timestamp": "2026-10-12T16:00:10.000Z",
                      "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {
                          "command": "python3 scripts/wince_grades.py add --grade B"}}]}}
        check(decide(transcript(user, filed_late), log) is None,
              "log: a background W followed by Wince (grade filed) allows, with no Agent call")
        out = decide(transcript(user), log[:1])
        check(bool(out) and "w_ran log" in out["reason"],
              "PLANTED: log: a background W that finished with no Wince is refused")
        par = [dict(log[1], utc="2026-10-12T16:00:03Z"), log[0]]
        check(decide(transcript(user, call("wince"), call("wander")), par) is not None,
              "PLANTED: Wince that FINISHED before the W finished did not critique it")
        other = [dict(log[0], session_id="s2")]
        check(decide(transcript(user), other) is None,
              "another session's W runs are not this session's debt")
        stale = [dict(log[0], utc="2026-10-12T15:59:59Z")]
        check(decide(transcript(user), stale) is None,
              "a W that finished before Garrett's last message is not this turn's")

        # an unbacked overrule logged by overrule_gate.py this turn refuses the reply
        op = os.path.join(d, "overrules.jsonl")
        with open(op, "w", encoding="utf-8") as f:
            f.write(json.dumps({"status": "unbacked", "session_id": "s1",
                                "utc": "2026-10-12T16:00:07Z"}) + "\n")
        out = decide(transcript(user, call("wander"), tool_result, call("wince")), [], op)
        check(bool(out) and "unbacked" in out["reason"],
              "PLANTED: an unbacked Wince overrule this turn refuses the reply")
        out = decide(transcript(user, call("wander"), tool_result), [], op)
        check(bool(out) and "unbacked" in out["reason"] and "Wander" in out["reason"],
              "PLANTED: an unbacked overrule no longer hides an unfollowed W -- both are named")
        stale_op = os.path.join(d, "stale.jsonl")
        with open(stale_op, "w", encoding="utf-8") as f:
            f.write(json.dumps({"status": "unbacked", "session_id": "s1",
                                "utc": "2026-10-12T15:59:00Z"}) + "\n")
        check(decide(transcript(user), [], stale_op) is None,
              "an unbacked overrule from an earlier turn is not this turn's")

        # A Wince GRADE nobody filed (RULED 2026-10-14). Sync run: the result came back.
        def wince_call(at):
            return {"type": "assistant", "timestamp": at, "message": {"content": [
                {"type": "tool_use", "id": "w1", "name": "Agent",
                 "input": {"subagent_type": "load-house-rules:wince", "prompt": "grade"}}]}}

        def wince_result(at, text="Wince: GRADE: B"):
            return {"type": "user", "timestamp": at, "toolUseResult": {"x": 1},
                    "message": {"content": [{"type": "tool_result", "tool_use_id": "w1",
                                             "content": [{"type": "text", "text": text}]}]}}

        def filing(at, cmd="python3 scripts/wince_grades.py add --subject x --grade B"):
            return {"type": "assistant", "timestamp": at, "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": cmd}}]}}

        def said(text):
            return {"type": "assistant", "timestamp": "2026-10-12T16:00:30.000Z",
                    "message": {"content": [{"type": "text", "text": text}]}}

        graded = (user, wince_call("2026-10-12T16:00:01.000Z"),
                  wince_result("2026-10-12T16:00:20.000Z"))
        out = decide(transcript(*graded), [])
        check(bool(out) and "wince_grades.py add" in out["reason"],
              "PLANTED: a Wince grade that came back and was never filed is refused")
        check(decide(transcript(*graded, filing("2026-10-12T16:00:25.000Z")), []) is None,
              "a grade filed after it came back allows")
        check(decide(transcript(filing("2026-10-12T15:00:00.000Z"), *graded), []) is not None,
              "PLANTED: a filing from BEFORE the grade came back does not cover it")
        check(decide(transcript(*graded, filing("2026-10-12T16:00:25.000Z",
                    "cd skyne && python3 - <<'PY'\nimport wince_grades as w\nw.add(doc, ...)\nPY")),
                     []) is None,
              "a script that imports the register's writer counts as filing")
        check(decide(transcript(*graded, said('the hook wants "no grade to file" said')), []) is not None,
              "PLANTED: prose that only MENTIONS the phrase (no colon) does not count as the escape")
        check(decide(transcript(*graded, said(
            "I would write no grade to file: and the reason, but this was graded")), []) is not None,
              "PLANTED: describing the escape mid-sentence is not using it")
        check(decide(transcript(*graded, said("```say no grade to file: reason here```")), [])
              is not None, "PLANTED: a code span quoting the escape is not using it")
        check(decide(transcript(*graded, said("Wince read prose.\nNo grade to file: it was a critique.")), []) is None,
              "a Wince run that was not a graded pass is let through when the reply says so")
        quoted = decide(transcript(*graded), [])["reason"]
        check(decide(transcript(*graded, said(f"The hook said: {quoted}")), []) is not None,
              "PLANTED: quoting the refusal back (its '<why>' placeholder) is not the escape")
        early_escape = {"type": "assistant", "timestamp": "2026-10-12T16:00:00.500Z",
                        "message": {"content": [{"type": "text", "text": "no grade to file: early"}]}}
        check(decide(transcript(user, early_escape, *graded[1:]), []) is not None,
              "PLANTED: 'no grade to file' said BEFORE the Wince run does not cover it")
        later_turn = {"type": "user", "timestamp": "2026-10-12T17:00:00.000Z",
                      "message": {"content": "next thing"}}
        check(decide(transcript(*graded, said("No grade to file: prose only."), later_turn), [])
              is None, "an escape said in an EARLIER turn still covers it -- no nagging every turn")
        both = [{"event": "stop", "w": "wince", "session_id": "s1", "agent_id": "a1",
                 "utc": "2026-10-12T16:00:20Z"}] * 2   # the hook registered twice
        out = decide(transcript(*graded), both)
        check(bool(out) and out["reason"].startswith("1 Wince grade"),
              "a run in both the log and the transcript is counted once")
        out = decide(transcript(*graded, call("wander")), [])
        check(bool(out) and "wince_grades.py add" in out["reason"] and "Wander" in out["reason"],
              "PLANTED: an unfiled grade AND an unfollowed W are both named in the one refusal")
        bg = (user, wince_call("2026-10-12T16:00:01.000Z"),
              wince_result("2026-10-12T16:00:02.000Z", "Async agent launched successfully."))
        check(decide(transcript(*bg), []) is None,
              "a Wince still running in the background is not owed yet")
        late = [{"event": "stop", "w": "wince", "session_id": "s1", "utc": "2026-10-12T16:00:40Z"}]
        check(decide(transcript(*bg), late) is not None,
              "PLANTED: the background Wince is owed once the log shows it finished")
        check(decide(transcript(*bg), [dict(late[0], session_id="s2")]) is None,
              "another session's Wince is not this session's to file")

        # end to end through stdin, as the harness runs it
        env = dict(os.environ, SKYNE_W_RUNS_LOG=os.path.join(d, "none.jsonl"))
        r = subprocess.run([sys.executable, __file__], input=json.dumps(
            transcript(user, call("warden"), tool_result)), capture_output=True,
            text=True, env=env)
        printed = json.loads(r.stdout or "{}")
        ctx = (printed.get("hookSpecificOutput") or {}).get("additionalContext", "")
        check(r.returncode == 0 and "decision" not in printed
              and printed.get("hookSpecificOutput", {}).get("hookEventName") == "Stop"
              and ctx.startswith("Claude owes a Wince/Wren follow-up") and "Nothing for you" in ctx
              and "Warden" in ctx,
              "PLANTED: end to end, a refusal is printed as Stop feedback (additionalContext, not "
              "a 'block' hook error), opens with the plain line, and the exit is 0")
        check(not any(x in ctx for x in ("RULED", "load-house-rules:", "w-follow-mode")),
              "the refusal Garrett sees carries no rule numbers, plugin ids or the off switch")
        r = subprocess.run([sys.executable, __file__], input="not json",
                           capture_output=True, text=True, env=env)
        check(r.returncode == 0 and r.stdout == "", "garbage stdin exits 0, silently")
        # a crash, or a broken import, leaves an error row the heartbeat reads (W red team round 1)
        elog = os.path.join(d, "err.jsonl")
        keep_log = os.environ.get("SKYNE_W_FOLLOW_LOG")
        os.environ["SKYNE_W_FOLLOW_LOG"] = elog
        _raw_error_row("wince", SyntaxError("bad w_follow"))
        rows_e = read_jsonl(elog)
        check(len(rows_e) == 1 and rows_e[0]["action"] == "error" and "SyntaxError" in rows_e[0]["error"],
              "PLANTED: a gate that cannot import its shared module writes an error row")
        os.environ["SKYNE_W_FOLLOW_LOG"] = keep_log


        # ================= STAGE 2 (PC): label + publish triggers, content-match filing =======
        os.environ.pop("CLAUDE_CODE_REMOTE", None)
        t = "2026-11-17T15:00:%02d.000Z"
        u2 = {"type": "user", "timestamp": t % 0, "message": {"content": "go"}}

        def says(sec, text):
            return {"type": "assistant", "timestamp": t % sec,
                    "message": {"content": [{"type": "text", "text": text}]}}

        def tu(sec, name, inp, tid):
            return {"type": "assistant", "timestamp": t % sec, "message": {"content": [
                {"type": "tool_use", "id": tid, "name": name, "input": inp}]}}

        wr = lambda sec: tu(sec, "Write", {"file_path": "C:\\x\\a.py", "content": "1"}, f"w{sec}")
        art = lambda sec: tu(sec, "Artifact", {"file_path": "C:\\x\\page.html", "icon": "chart",
                                               "description": "d"}, f"a{sec}")

        def agent(sec, who, tid, prompt="do it"):
            return tu(sec, "Agent", {"subagent_type": who, "prompt": prompt}, tid)

        def mk(sec, st=None, when=None):   # Claude marks feature BL-1 Checked (s plus the Checked date)
            return tu(sec, "ArtifactData", {"action": "update", "url": "https://claude.ai/artifact/X",
                                            "collection": "features", "doc_id": "BL-1", "if_version": 3,
                                            "data": {"s": st or ["done", "done", "done", "done", "no", "no", "no"],
                                                     "stageDates": {"checked": when or t % sec}}},
                      f"m{sec}")

        def sync_back(sec, tid, text="done"):
            return {"type": "user", "timestamp": t % sec, "toolUseResult": {"status": "completed"},
                    "message": {"content": [{"type": "tool_result", "tool_use_id": tid,
                                             "content": [{"type": "text", "text": text}]}]}}

        def async_back(sec, tid, agent_id):
            return {"type": "user", "timestamp": t % sec,
                    "toolUseResult": {"isAsync": True, "status": "async_launched", "agentId": agent_id},
                    "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": [
                        {"type": "text", "text": "Async agent launched successfully.\nagentId: " + agent_id}]}]}}

        def stop_row(w, aid, utc, sess="s1"):
            return {"event": "stop", "w": w, "agent_id": aid, "session_id": sess, "utc": utc}

        def flog():
            return read_jsonl(os.environ["SKYNE_W_FOLLOW_LOG"])

        def queue_row(path, **kw):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(kw) + "\n")

        def go(*entries, log=(), **kw):
            return decide(transcript(*entries, **kw), list(log))

        # the Checked trigger (RULED 2026-11-19); the label trigger is retired
        check(go(u2, says(1, "Wistin: built it."), wr(2), says(3, "Wistin: done.")) is None
              and flog()[-1]["labeled"] is True and flog()[-1]["old_rule"] is True,
              "a Wistin-labeled reply that wrote a file no longer owes Wince; the log says the old rule would have")
        out = go(u2, says(1, "Built it."), wr(2), mk(3), says(4, "Marked it Checked."))
        check(bool(out) and "W follow-up" in out["reason"] and "marked Checked (BL-1)" in out["reason"],
              "PLANTED: marking a board feature Checked with no Wince run is refused")
        check(flog()[-1]["action"] == "refused" and flog()[-1]["triggers"] == ["checked"],
              "the refusal is logged with its trigger")
        check(go(u2, mk(2), mk(3, ["done"] * 5 + ["no"] * 2, when=t % 2), says(4, "Marked Built.")) is not None
              and go(u2, says(1, "x"), mk(2), says(3, "y"), {"type": "user", "timestamp": t % 4, "message": {"content": "next"}}, mk(5, ["done"] * 5 + ["no"] * 2, when=t % 2), says(6, "Built.")) is None,
              "re-sending a row whose Checked was already done (written earlier in the session) does not fire again")
        check(go(u2, mk(2, ["done"] * 5 + ["no"] * 2, when="2026-11-01T10:00:00Z"), says(3, "Built.")) is None,
              "a new session re-sending a row with its OLD Checked date (Built, Live, the Used number) does not fire")
        check(go(u2, tu(2, "ArtifactData", {"action": "update", "url": "u", "collection": "features", "doc_id": "BL-1",
                                            "data": {"s": ["done", "done", "done", "done", "no", "no", "no"]}}, "nd"),
                 says(3, "Marked it.")) is None and "undated_checked" not in flog()[-1],
              "known blind spot: a write with Checked done and no date neither refuses nor logs "
              "(it may be a Built/Live re-send of a dated row; the nightly reads the stored row)")
        tn = "2026-11-18T03:00:%02d.000Z"        # 22:00 Eastern on 11-17: the UTC date is 11-18
        un = {"type": "user", "timestamp": tn % 0, "message": {"content": "go"}}
        mn = dict(mk(2, when="2026-11-18"), timestamp=tn % 2)
        out = go(un, mn, dict(says(3, "Checked."), timestamp=tn % 3))
        check(bool(out) and "BL-1" in out["reason"],
              "PLANTED: a date-only Checked written as the UTC date (a day ahead of Eastern near "
              "midnight) still fires")
        out = go(u2, mk(2, when="2026-11-17"), says(3, "Checked."))
        check(bool(out) and "BL-1" in out["reason"], "PLANTED: a date-only Checked (today, ET) fires (Wince round 3)")
        check(go(u2, mk(2, ["done", "done", "done", "no", "no", "no", "no"], when=t % 2), says(3, "Undid it.")) is None,
              "setting Checked back to not done, with the old date riding along, does not fire")
        fp = os.path.join(_scratch, "f-bl9.json")
        with open(fp, "w", encoding="utf-8") as fh:
            json.dump({"s": ["no", "done", "done", "done", "no", "no", "no"], "stageDates": {"checked": t % 2}}, fh)
        out = go(u2, tu(2, "ArtifactData", {"action": "batch", "url": "u", "writes": [
                 {"op": "update", "collection": "features", "doc_id": "BL-9", "file_path": fp, "if_version": 1}]}, "fp"),
                 says(3, "Done."))
        check(bool(out) and "BL-9" in out["reason"], "PLANTED: a Checked mark sent through file_path fires (Wince round 2)")
        out = go(u2, mk(2, ["done", "done", "done", "no", "no"]), says(3, "Old board."))
        check(bool(out), "PLANTED: a five-stage row (before 2026-11-19) marked Checked still fires")
        out = go(u2, tu(2, "ArtifactData", {"action": "batch", "url": "u", "writes": [
                 {"op": "update", "collection": "inbox", "doc_id": "IN-1", "data": {"status": "open"}},
                 {"op": "update", "collection": "features", "doc_id": "CO-4",
                  "data": {"s": ["no", "done", "done", "done", "no", "no", "no"], "stageDates": {"checked": t % 2}},
                  "if_version": 2}]}, "bt"),
                 says(3, "Done."))
        check(bool(out) and "CO-4" in out["reason"], "PLANTED: a batch write that marks Checked fires")
        out = go(u2, tu(2, "ArtifactData", {"action": "update", "url": "u", "collection": "features",
                                            "doc_id": "SK-1", "data": {"stageDates": {"checked": t % 2}}}, "sd"),
                 says(3, "Dated."))
        check(bool(out) and "SK-1" in out["reason"], "PLANTED: setting stageDates.checked alone fires")
        check(go(u2, tu(2, "ArtifactData", {"action": "list", "url": "u", "collection": "features"}, "rd"),
                 says(3, "Read it.")) is None, "reading the board fires nothing")
        check(go(u2, tu(2, "ArtifactData", {"action": "update", "url": "u", "collection": "inbox", "doc_id": "IN-2",
                                            "data": {"s": ["done"] * 7}}, "ib"), says(3, "x")) is None,
              "a write outside features fires nothing")
        ok_run = [agent(4, "wince", "wc1"), sync_back(6, "wc1")]
        check(go(u2, says(1, "Wistin: built it."), wr(2), mk(3), *ok_run, says(7, "Wistin: done."),
                 log=[]) is not None,
              "PLANTED: a synchronous Wince that came back owes its filing, so work-then-Wince "
              "without filing is still refused (filed-check)")
        queue_row(os.environ["SKYNE_GRADES_QUEUE"], session="s1", queued_utc="2026-11-17T15:00:08Z",
                  subject="x", key="k1")
        check(go(u2, says(1, "Wistin: built it."), wr(2), mk(3), *ok_run, says(7, "Wistin: done.")) is None
              and flog()[-1]["action"] == "satisfied",
              "work, then Wince, the grade queued under THIS session, then 'Wistin:' passes")
        check(go(u2, says(1, "Wistin: built it."), *ok_run, wr(7), mk(7), says(8, "Wistin: done.")) is not None,
              "PLANTED: a Wince run BEFORE the last write does not count")
        out = go(u2, says(1, "Wince: I reviewed it, it is fine."))
        check(out is None, "a 'Wince:' label alone triggers nothing (no work to follow)")
        out = go(u2, says(1, "Wistin: built it."), wr(2), mk(3), says(4, "Wince: it looks great."))
        check(bool(out) and "W follow-up" in out["reason"],
              "PLANTED: a 'Wince:' label never satisfies the follow-up (only an agent run does)")
        check(go(u2, says(1, "Claude: here is a quick answer."), says(2, "Claude: and the follow-up.")) is None
              and flog()[-1]["action"] == "quiet",
              "a quiet Claude: Q&A turn triggers nothing")
        out = go(u2, says(1, "Weir: I would choose the second."))
        check(out is None, "a W label on a plain Q&A reply no longer owes a Wince run (wide trial ended 2026-11-19)")
        # publish: retired as a trigger, still logged
        out = go(u2, art(2), says(3, "Here is the page."))
        check(out is None and flog()[-1]["old_rule"] is True,
              "an Artifact publish no longer owes a Wince run; the log still records it")
        check(go(u2, tu(2, "Artifact", {"action": "publish", "asset": True, "url": "u", "file_path": "a.png"}, "p1"),
                 says(3, "Uploaded.")) is None,
              "an asset upload is not a publish")
        fig = "mcp__a2e5608f-73d1-4432-84e6-22b3701e89d8__"
        out = go(u2, tu(2, fig + "generate_diagram", {"name": "flow", "mermaidSyntax": "graph TD"}, "f1"),
                 says(3, "Diagram made."))
        check(out is None, "a Figma generate_diagram no longer triggers the follow-up")
        out = go(u2, tu(2, fig + "get_screenshot", {"nodeId": "1:2"}, "f2"), says(3, "Looked."))
        check(out is None, "a Figma get_screenshot (a read) does not")
        out = go(u2, tu(2, fig + "totally_new_tool", {}, "f3"), mk(3), says(4, "Weir: x"))
        check(bool(out) and "Unknown Figma tool" in out["reason"],
              "an unknown Figma tool is flagged in the refusal and the log")
        check(flog()[-1]["unknown_figma"] == ["mcp__a2e5608f-73d1-4432-84e6-22b3701e89d8__totally_new_tool"]
              or flog()[-1]["unknown_figma"], "the unknown tool name is in the log row")
        # Wander agent run forces Wince (the agent-W path, as before)
        out = go(u2, agent(2, "wander", "wd1"), sync_back(3, "wd1"), says(4, "Here is what Wander found."))
        check(bool(out) and "Wander" in out["reason"], "a real Wander agent run forces Wince as before")
        # haiku-mechanic is not a W
        out = go(u2, agent(2, "haiku-mechanic", "hm1"), sync_back(3, "hm1"), says(4, "Moved the files."))
        check(out is None, "a haiku-mechanic agent run forces nothing (R8)")
        # Wren first, then ONE Wince pass after Wren
        steps_wren_then_wince = [u2, says(1, "Wistin: built it."), wr(2), mk(2), agent(3, "wren", "wn1"), sync_back(5, "wn1"),
                                 agent(6, "wince", "wc2"), sync_back(8, "wc2"), says(9, "Wistin: done.")]
        queue_row(os.environ["SKYNE_GRADES_QUEUE"], session="s1", queued_utc="2026-11-17T15:00:09Z", key="k2")
        check(go(*steps_wren_then_wince) is None, "Wren first, then Wince after it, filed: passes")
        steps_wince_then_wren = [u2, says(1, "Wistin: built it."), wr(2), mk(2), agent(3, "wince", "wc3"), sync_back(5, "wc3"),
                                 agent(6, "wren", "wn2"), sync_back(8, "wn2"), says(9, "Wistin: done.")]
        out = go(*steps_wince_then_wren)
        check(bool(out) and "Wren tried it" in out["reason"],
              "PLANTED: Wince that finished BEFORE Wren's try does not grade Wren's report")
        # same-second tie counts as after
        tie = [u2, says(1, "Wistin: x"), wr(2), mk(2), agent(3, "wince", "wc4"), sync_back(2, "wc4"), says(9, "Wistin: done.")]
        check(go(*tie) is None, "a Wince run finishing in the same second as the last edit counts as after")

        # red-team lens 4: tagged, joined through the agentId, only a rounds row counts
        queue_row(os.environ["SKYNE_ROUNDS_QUEUE"], session="s2", loop="L7", queued_utc="2026-11-17T15:00:20Z")
        lens4 = [u2, says(1, "Weir: reviewing."),
                 agent(2, "wince", "l4", "[red-team lens 4: L7] grade this deck"), async_back(3, "l4", "agentLens4")]
        log4 = [stop_row("wince", "agentLens4", "2026-11-17T15:00:25Z", "s2")]
        out = go(*lens4, says(16, "Weir: done."), log=log4, session_id="s2")
        check(bool(out) and "1 Wince grade" in out["reason"] and "lens-4" not in out["reason"],
              "PLANTED: a tagged lens-4 Wince run whose rounds row is dated BEFORE the finish is refused, "
              "in plain words")
        queue_row(os.environ["SKYNE_ROUNDS_QUEUE"], session="s2", loop="L7", queued_utc="2026-11-17T15:00:30Z")
        check(go(*lens4, says(31, "Weir: done."), log=log4, session_id="s2") is None,
              "lens 4 + a redteam_rounds row for its loop, after the run, passes with no refusal")
        queue_row(os.environ["SKYNE_GRADES_QUEUE"], session="s3", queued_utc="2026-11-17T15:00:40Z", key="g3")
        lens4_s3 = [u2, says(1, "Weir: reviewing."),
                    agent(2, "wince", "l5", "[red-team lens 4: L8] grade"), async_back(3, "l5", "agentLens5")]
        out = go(*lens4_s3, says(41, "Weir: done."), log=[stop_row("wince", "agentLens5", "2026-11-17T15:00:15Z", "s3")],
                 session_id="s3")
        check(out is None,
              "a tagged lens-4 run followed by its wince_grades row passes: the round itself is filed "
              "once all four reviewers are in (W red team round 2)")

        # RULED 2026-11-20: the round record stops Claude again, once every lens has finished
        def notif(sec, tid, status="completed"):
            return {"type": "user", "timestamp": t % sec, "promptSource": "system",
                    "origin": {"kind": "task-notification"},
                    "message": {"content": "<task-notification>\n<task-id>x" + tid + "</task-id>\n"
                                           "<tool-use-id>" + tid + "</tool-use-id>\n<status>" + status +
                                           "</status>\n<summary>Agent finished</summary>\n</task-notification>"}}

        def lenses(loop, ids, sec):
            out = []
            for n, tid in zip((1, 2, 3, 4), ids):
                who = "wince" if n == 4 else "general-purpose"
                out += [agent(sec, who, tid, f"[red-team lens {n}: {loop}] review the deck"),
                        async_back(sec, tid, "ag" + tid)]
            return out
        rt = [u2, says(1, "Reviewing.")] + lenses("R5", ["r51", "r52", "r53", "r54"], 2)
        out = go(*rt, notif(5, "r54"), says(6, "Waiting on the other lenses."), session_id="s5")
        check(out is None, "PLANTED: lens 4 finishing first, other lenses still running, is not refused")
        out = go(*rt, notif(5, "r54"), notif(6, "r51"), notif(7, "r52"), notif(8, "r53", "failed"),
                 says(9, "Round done."), session_id="s5")
        check(bool(out) and "Red-team review R5" in out["reason"] and "not recorded" in out["reason"]
              and "round-unfiled" in flog()[-1]["triggers"],
              "PLANTED: all four lenses finished (one failed) and no round record is refused")
        check(go(*rt, notif(5, "r54"), notif(6, "r51"), notif(7, "r52"), notif(8, "r53"),
                 says(9, "no grade to file: test run"), session_id="s5") is None,
              "the escape line after the last finish accounts for the round")
        queue_row(os.environ["SKYNE_ROUNDS_QUEUE"], session="s5", loop="R9", queued_utc="2026-11-17T15:00:10Z")
        check(go(*rt, notif(5, "r54"), notif(6, "r51"), notif(7, "r52"), notif(8, "r53"),
                 says(9, "Round done."), session_id="s5") is not None,
              "a round record for a different loop does not count")
        queue_row(os.environ["SKYNE_ROUNDS_QUEUE"], session="s5", loop="R5", queued_utc="2026-11-17T15:00:10Z")
        done1 = rt + [notif(5, "r54"), notif(6, "r51"), notif(7, "r52"), notif(8, "r53")]
        check(go(*done1, says(11, "Filed."), session_id="s5") is None,
              "PLANTED: the round recorded after all four finished passes")
        rt2 = done1 + lenses("R5", ["r61", "r62", "r63", "r64"], 12)
        check(go(*rt2, notif(13, "r61"), notif(14, "r64"), says(15, "Round 2 running."), session_id="s5") is None,
              "round 2 half finished owes nothing yet")
        out = go(*rt2, notif(13, "r61"), notif(14, "r64"), notif(15, "r62"), notif(16, "r63"),
                 says(17, "Round 2 done."), session_id="s5")
        check(bool(out) and "R5" in out["reason"],
              "PLANTED: round 2 complete is owed its own record (round 1's does not cover it)")
        sync = [u2] + [x for n, tid in zip((1, 2, 3, 4), ("q1", "q2", "q3", "q4"))
                       for x in (agent(2, "general-purpose", tid, f"[red-team lens {n}: R6] x"), sync_back(3, tid))]
        check(bool(go(*sync, says(4, "Done."), session_id="s6")),
              "four synchronous lenses that returned owe the round record too")
        old = [u2, agent(2, "wince", "o4", "[red-team lens 4: R7] grade"), sync_back(3, "o4"),
               says(4, "Graded."), agent(5, "general-purpose", "o1", "coverage lens"),
               sync_back(6, "o1"), says(7, "Done.")]
        queue_row(os.environ["SKYNE_GRADES_QUEUE"], session="s7", queued_utc="2026-11-17T15:00:04Z", key="g7")
        check(go(*old, session_id="s7") is None,
              "only lens 4 tagged (the old prompts) owes no round record: the gate cannot see the round")

        # the filed-check by CONTENT
        qa = tmp_q = os.path.join(_scratch, "gq.jsonl")
        os.unlink(qa)
        graded = [u2, says(1, "Weir: reviewing."), agent(2, "wince", "g1"), sync_back(4, "g1")]
        cmd_only = tu(6, "Bash", {"command": "python3 scripts/wince_grades.py queue --subject x"}, "b1")
        out = go(*graded, cmd_only, says(7, "Weir: done."))
        check(bool(out) and "wince_grades.py queue" in out["reason"],
              "PLANTED: naming wince_grades in a command with no row in the queue is refused")
        queue_row(qa, session="OTHER-CHAT", queued_utc="2026-11-17T15:00:05Z")
        check(go(*graded, cmd_only, says(7, "Weir: done.")) is not None,
              "PLANTED: another chat filing at the same moment does not count for this session")
        queue_row(qa, session="s1", queued_utc="2026-11-17T15:00:03Z")
        check(go(*graded, says(7, "Weir: done.")) is not None,
              "PLANTED: a row from THIS session dated before the Wince finish does not count")
        queue_row(qa, session="s1", queued_utc="2026-11-17T15:00:05Z")
        check(go(*graded, says(7, "Weir: done.")) is None, "a row from this session after the finish counts")
        two = [u2, says(1, "Weir: r"), agent(2, "wince", "g1"), sync_back(4, "g1"),
               agent(5, "wince", "g2"), sync_back(7, "g2")]
        out = go(*two, says(8, "Weir: done."))
        check(bool(out) and out["reason"].count("1 Wince grade") >= 1,
              "PLANTED: two Wince finishes and one filing leaves one owed (per-finish accounting)")
        failed_queue = [u2, says(1, "Weir: r"), agent(2, "wince", "g1"), sync_back(4, "g1"),
                        tu(5, "Bash", {"command": "python3 scripts/wince_grades.py queue --bad"}, "b2"),
                        {"type": "user", "timestamp": t % 6, "toolUseResult": {"stdout": "refused: x"},
                         "message": {"content": [{"type": "tool_result", "tool_use_id": "b2", "is_error": True,
                                                  "content": "refused: pass should be 2"}]}}]
        os.unlink(qa)
        check(go(*failed_queue, says(7, "Weir: done.")) is not None,
              "PLANTED: a failed `queue` call (refused, nothing queued) is refused here too")
        check(go(*graded, says(7, "Weir: done.\nNo grade to file: it was a prose critique.")) is None,
              "'no grade to file: <why>' after the finish still accounts for it")
        queue_row(qa, session="s1", queued_utc="2026-11-17T15:00:05Z")

        # a grade that was flushed and dropped from the queue is found in a register
        os.unlink(qa)
        reg = os.path.join(_scratch, "wince-grades.json")
        with open(reg, "w", encoding="utf-8") as fh:
            json.dump({"grades": [{"session": "s1", "filed_utc": "2026-11-17T15:00:05Z"}]}, fh)
        os.environ["SKYNE_EXTRA_REGISTERS"] = reg
        check(go(*graded, says(7, "Weir: done.")) is None,
              "a filing that already reached a register (queue row dropped) still counts")
        os.environ.pop("SKYNE_EXTRA_REGISTERS", None)
        # an `add` run in a skyne clone the gate was never told about (W red team round 1)
        clone = os.path.join(_scratch, "scratchpad", "skyne-clone")
        os.makedirs(os.path.join(clone, "data"))
        with open(os.path.join(clone, "data", "wince-grades.json"), "w", encoding="utf-8") as fh:
            json.dump({"grades": [{"session": "s1", "filed_utc": "2026-11-17T15:00:05Z"}]}, fh)
        add_there = tu(5, "Bash", {"command": f'cd "{clone}" && python3 scripts/wince_grades.py add --subject x'}, "b9")
        check(go(*graded, add_there, says(7, "Weir: done.")) is None,
              "an `add` run in an unknown skyne clone (found from the command's cd) counts")
        add_path = tu(5, "Bash", {"command": f"python3 {clone}/scripts/wince_grades.py add --subject x"}, "b9")
        check(go(*graded, add_path, says(7, "Weir: done.")) is None,
              "an `add` run by the clone's full script path counts")
        check(go(*graded, tu(5, "Bash", {"command": "python3 scripts/wince_grades.py add --subject x"}, "b9"),
                 says(7, "Weir: done.")) is not None,
              "PLANTED: the same `add` with no way to find the clone is still refused")
        queue_row(qa, session="s1", queued_utc="2026-11-17T15:00:05Z")
        # a Wince continued with SendMessage finishes more than once: each finish is a pass
        twice = [stop_row("wince", "aW", "2026-11-17T15:00:04Z"), stop_row("wince", "aW", "2026-11-17T15:00:04Z"),
                 stop_row("wince", "aW", "2026-11-17T15:00:20Z")]
        out = go(*graded, says(21, "Weir: done."), log=twice)
        check(bool(out) and "1 Wince grade" in out["reason"],
              "PLANTED: a Wince that finishes again later (SendMessage) owes a second filing; the "
              "double-registered duplicate row still counts once")
        mark_then_continue = [u2, mk(2), says(3, "Checked.")]
        queue_row(qa, session="s1", queued_utc="2026-11-17T15:00:06Z")
        cont = [stop_row("wince", "aW", "2026-11-17T14:59:00Z"), stop_row("wren", "aR", "2026-11-17T15:00:03Z"),
                stop_row("wince", "aW", "2026-11-17T15:00:04Z")]
        check(go(*mark_then_continue, log=cont) is None,
              "a continued Wince that re-finishes AFTER the Checked mark satisfies it (session ee79be7b)")
        # W red team round 2: reviewed in the turn before, marked Checked after Garrett's yes
        tp = "2026-11-17T16:00:%02d.000Z"
        ua = {"type": "user", "timestamp": tp % 0, "message": {"content": "build it"}}
        ub = {"type": "user", "timestamp": tp % 10, "message": {"content": "yes, mark it Checked"}}
        wr_a = dict(wr(1), timestamp=tp % 1)
        mk_b = dict(mk(11, when="2026-11-17T16:00:11Z"), timestamp=tp % 11)
        rev = [stop_row("wren", "aR2", "2026-11-17T16:00:03Z"), stop_row("wince", "aW2", "2026-11-17T16:00:05Z")]
        queue_row(qa, session="s1", queued_utc="2026-11-17T16:00:06Z")
        check(go(ua, wr_a, dict(says(7, "Reviewed."), timestamp=tp % 7), ub, mk_b,
                 dict(says(12, "Marked."), timestamp=tp % 12), log=rev) is None,
              "PLANTED: a Wince+Wren review in the turn BEFORE the Checked mark covers it (no second pass)")
        wr_late = dict(wr(8), timestamp=tp % 8)
        out = go(ua, wr_a, dict(says(7, "Reviewed."), timestamp=tp % 7), wr_late, ub, mk_b,
                 dict(says(12, "Marked."), timestamp=tp % 12), log=rev)
        check(bool(out) and "BL-1" in out["reason"],
              "PLANTED: work changed AFTER that review is not covered by it")
        uc = {"type": "user", "timestamp": "2026-11-17T15:59:00.000Z", "message": {"content": "earlier"}}
        out = go(uc, dict(says(1, "x"), timestamp="2026-11-17T15:59:01.000Z"), ua, wr_a,
                 dict(says(7, "x"), timestamp=tp % 7), ub, mk_b, dict(says(12, "Marked."), timestamp=tp % 12),
                 log=[stop_row("wince", "aW3", "2026-11-17T15:59:02Z")])
        check(bool(out), "PLANTED: a review two turns back does not cover a mark")
        check("before replying" not in refusal(["wander"], "w_ran").lower(),
              "PLANTED: the refusal says 'before Claude finishes', not 'before replying' (round 3)")
        out = go(ua, wr_a, mk_b, dict(says(12, "Marked.\nnothing for Wren to try: it is lore"),
                                      timestamp=tp % 12))
        check(bool(out) and "before claude finishes" in out["reason"].lower()
              and "before replying" not in out["reason"].lower(),
              "PLANTED: the Checked refusal with no Wren owed says 'before Claude finishes': "
              + repr((out or {}).get("reason", ""))[:200])
        # W red team round 3: a background agent's finish is not Garrett's turn. Shape copied from
        # transcript 1fbee306 (2026-11-20T16:09:04Z); the runId and paths are shortened.
        note = {"type": "user", "timestamp": tp % 8, "isSidechain": False, "promptSource": "system",
                "origin": {"kind": "task-notification", "producer": "session-task", "runId": "x"},
                "queueTranscriptOnly": True,
                "message": {"role": "user", "content": "<task-notification>\n<task-id>a1</task-id>\n"
                            "<status>completed</status>\n<summary>Agent \"Wince\" finished</summary>"}}
        ub_h = dict(ub, origin={"kind": "human"}, promptSource="sdk")
        check(go(ua, wr_a, dict(says(7, "Reviewed."), timestamp=tp % 7), note, ub_h, mk_b,
                 dict(says(12, "Marked."), timestamp=tp % 12), log=rev) is None,
              "PLANTED: a task-notification between the review and Garrett's yes does not move the floor")
        check(not is_garrett_turn(note) and is_garrett_turn(ub_h) and is_garrett_turn(ub)
              and not is_garrett_turn(dict(ub, message={"content": "<task-notification>\n<status>x"}))
              and not is_garrett_turn(dict(note, message={"content": [{"type": "text", "text": "x"}]})),
              "PLANTED: notifications (by origin, or by text in older logs) are not Garrett's turn")

        # the switch: log mode logs the NEW triggers, the old blocks keep blocking (R10)
        def set_mode(raw):
            with open(os.environ["SKYNE_W_FOLLOW_MODE"], "wb") as fh:
                fh.write(raw)
        trig = [u2, says(1, "Wistin: x"), wr(2), mk(2), says(3, "Wistin: y")]
        for name, raw in (("plain", b"log"), ("UTF-8 BOM", b"\xef\xbb\xbflog\r\n"),
                          ("UTF-16", "log\r\n".encode("utf-16"))):
            set_mode(raw)
            check(go(*trig) is None and flog()[-1]["action"] == "log-would-refuse" and flog()[-1]["mode"] == "log",
                  f"switch written as {name}: the Checked trigger logs and refuses nothing")
        check(go(u2, agent(2, "wander", "wd2"), sync_back(3, "wd2"), says(4, "found it")) is not None,
              "log mode does not release the agent-W trigger (it blocks today, R10)")
        set_mode(b"banana")
        out = go(*trig)
        check(bool(out) and "not 'enforce' or 'log'" not in out["reason"]
              and "w-follow-mode" not in out["reason"]
              and "not 'enforce' or 'log'" in w_follow.read_mode()[1],
              "PLANTED: a garbage switch value enforces; the refusal never names the switch file, the "
              "start-up readout does")
        os.unlink(os.environ["SKYNE_W_FOLLOW_MODE"])

        # cloud: new triggers log only
        os.environ["CLAUDE_CODE_REMOTE"] = "true"
        check(go(*trig) is None and flog()[-1]["cloud"] is True and flog()[-1]["action"] == "log-would-refuse",
              "an attended-cloud-shaped env still only LOGS the new trigger (R12 is PC-only until confirmed)")
        os.environ.pop("CLAUDE_CODE_REMOTE", None)

        # released by stop_hook_active is logged
        out = decide(dict(transcript(*trig), stop_hook_active=True), [])
        check(out is None and flog()[-1]["action"] == "released", "released-by-stop_hook_active is logged")
        check(os.path.exists(os.environ["SKYNE_W_FOLLOW_GOLIVE"]), "the go-live date was recorded")
        # a call with no new facts still writes its heartbeat row
        n0 = len(flog())
        go(u2, says(1, "Claude: hi"))
        check(len(flog()) == n0 + 1 and flog()[-1]["action"] == "quiet", "a quiet turn still writes a heartbeat row")

        # replay a REAL transcript from this PC through the gate: it must not crash and must answer
        real = os.environ.get("SKYNE_REPLAY_TRANSCRIPT")
        if real and os.path.exists(real):
            try:
                decide({"transcript_path": real, "session_id": "replay"}, [], log_it=False)
                check(True, "a real local transcript replays through the gate without error")
            except Exception as exc:  # noqa: BLE001
                check(False, f"a real transcript replays without error ({exc})")
        for k in ("SKYNE_W_FOLLOW_LOG", "SKYNE_W_FOLLOW_MODE", "SKYNE_W_FOLLOW_GOLIVE",
                  "SKYNE_GRADES_QUEUE", "SKYNE_ROUNDS_QUEUE", "SKYNE_EXTRA_ROOTS"):
            os.environ.pop(k, None)

    print(f"\nwince_gate self-test: {len(ran) - len(fails)} of {len(ran)} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
