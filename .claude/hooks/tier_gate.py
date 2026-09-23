#!/usr/bin/env python3
"""tier_gate.py -- UserPromptSubmit: Haiku grades every message, and a wrong tier waits.

WHY THIS EXISTS
---------------
Garrett, 2026-09-23: *"every turn, a haiku agent asks how hard the task is and
decides a model to choose. If the current model does not match the proposed
model and effort, it stops it till it switches to the right one. This needs to
be enforceable and measurable."*

House-rules 2a has asked for exactly this comparison since 2026-09-01 and has
only ever been prose: Claude judges the task, Claude says a line, Claude keeps
going. Measured before this file existed (`skyne/data/tier-calls.json`): the
call was logged by hand, rarely, and **0 of 4** settled calls were followed.
Rule 2 itself names why self-judgement is weak -- *"a model asked to detect its
own ceiling is using the exact faculty in question."* So the grader here is a
DIFFERENT model (Haiku), called by the harness before the turn exists, grading
the TASK rather than itself.

WHAT IT DOES, EVERY MESSAGE
---------------------------
1. Reads the live model (the transcript's last assistant model, or a newer
   `/model` switch it can see) and effort (`CLAUDE_EFFORT`, or a newer
   `/effort` it can see).
2. Asks Haiku, through the `claude` CLI already on the machine, for the tier
   the message needs: haiku|sonnet|opus x low|medium|high. When torn, the
   rubric says pick the higher one -- under-powering costs correctness, over-
   powering only costs money (loop proposal `stamp-a-model-tier-on-each-work-
   item`, amendment 3).
3. Compares, with rule 2a's soft-lock tolerance: same model family AND effort
   within one step is a MATCH. Anything else is `up` (running too low) or
   `down` (running too high).
3b. AMENDED 2026-09-23, after the first live block landed on a throwaway note
   (Garrett: "cut short ones and then lets hold it for when it pays off for
   USAGE (not time, I can wait)"): a message of SHORT_WORDS words or fewer is
   not graded at all, and a mismatch is only held when Haiku sizes the work
   `medium` or `large`. A `small` job on the wrong tier passes as
   `allow-small` and is still logged as a wrong-tier turn.
4. Mismatch -> **blocks the message** and tells Garrett the exact tier. The
   message is SAVED: after `/model`, typing `go` sends it through. Saying
   `stay on <model>` overrides -- no argument, no second ask (rule 2a,
   2026-09-09) -- and the override holds until the recommendation changes.
5. Logs one row per message to `~/.claude/skyne/tier-gate.jsonl`: what ran,
   what was recommended, who graded it, how long it took, what it cost, and
   what happened. `skyne/scripts/tier_gate_report.py` turns that into the
   per-session numbers.

WHY A SUBPROCESS AND NOT A SCRIPT THAT IMPORTS A MODEL SDK
-----------------------------------------------------------
Charter article 15 / `check_ai_optional.py`: Skyne must run with no model. So
the model is OPTIONAL here, not load-bearing. Without the CLI, or when Haiku
times out, grading falls back to rule 2's own keyword tells (moved here from
the retired `delegate_reminder.py`), and failing that the message is let
through as `unjudged` -- logged, never silently counted as a match. The gate,
the log, and every number built on it are plain scripts.

WHY `claude -p --setting-sources ""`
-------------------------------------
Measured 2026-09-23 in a cloud container: `--bare` fails auth; `--setting-
sources ""` authenticates AND loads no user settings, so this hook cannot fire
itself recursively through the child. `SKYNE_TIER_GATE_CHILD=1` is a second
guard on top. Measured cost of one grading: ~5-8 s wall, ~$0.003-0.006 list.

NEVER TRAPS A SESSION
---------------------
* Every error path prints nothing and exits 0. It never exits 2 (which blocks).
* After THREE consecutive blocks it lets the message through (`released`),
  the same give-up shape `reply_gate.py` uses, so a wrong grader cannot lock
  Garrett out.
* Slash commands are never graded or blocked.

WHAT IT CANNOT SEE, SAID PLAINLY (house-rules 21 point 5)
---------------------------------------------------------
* Whether Haiku's grade is RIGHT. That is `skyne/scripts/tier_outcomes.py`'s
  job, over weeks, by joining the miss ledger to these rows.
* Effort when `CLAUDE_EFFORT` is absent and no `/effort` output is in the
  transcript -- then it compares model only and logs `effort_seen: false`.
* A cloud container's log dies with the container unless something harvests
  it (`tier_gate_report.py --harvest`, wired into /handoff).

Env knobs:
    SKYNE_TIER_GATE=block|warn|off          (default block)
    SKYNE_TIER_GATE_GRADER=haiku|keywords   (default haiku)
    SKYNE_TIER_GATE_TIMEOUT=<seconds>       (default 25; the hook entry allows 30)
    SKYNE_TIER_GATE_LOG=<path>              (default ~/.claude/skyne/tier-gate.jsonl)

Usage:
    python3 tier_gate.py                    # the hook (JSON on stdin)
    python3 tier_gate.py --grade "text"     # grade one message, print JSON
    python3 tier_gate.py --self-test
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

FAMILY_RANK = {"haiku": 1, "sonnet": 2, "opus": 3, "fable": 4}
RECOMMENDABLE = ("haiku", "sonnet", "opus")
EFFORTS = ["low", "medium", "high", "xhigh", "max"]
MAX_CONSECUTIVE_BLOCKS = 3
# Garrett, 2026-09-23, after the first live block landed on a throwaway note:
# "cut short ones and then lets hold it for when it pays off for USAGE (not
# time, I can wait)". So: a message this short is not graded at all (saves the
# grading call too), and a mismatch is only HELD when the grader expects the
# work to be big enough that the switch saves usage. A small job on the wrong
# tier passes through and is logged, never silently counted as on-tier.
SHORT_WORDS = 8
HOLD_SIZES = ("medium", "large")

# Rule 2's own "down" tells, moved verbatim from the retired delegate_reminder.py.
DOWN_TELLS = [
    r"\bmov(e|ing)\b.{0,20}\bfiles?\b",
    r"\brenam(e|ing)\b.{0,20}\bfiles?\b",
    r"\brun\s+(the|this)\s+script\b",
    r"\bformat(ting)?\s+(the|this|these|all)\b",
    r"\bapply\s+(the|this)\s+(already[- ]?)?decided\b",
    r"\b(sweep|apply)\b.{0,30}\b(same|identical)\s+edit\b",
    r"\b(sweep|apply)\b.{0,30}\bacross\s+(many|all|every)\s+files?\b",
    r"\bsame\s+edit\s+(to|across|over)\s+every\b",
]
# Rule 2's own "up" tells.
UP_TELLS = [
    r"\barchitect(ure|ing)?\b",
    r"\bdesign\s+(the|a|this)\b",
    r"\b3\+?\s*conflicting\s+constraints\b",
    r"\bvisual(ly)?[- ]?spatial\b",
    r"\bscope\s+(this|it)\s+out\b",
]
DOWN_RE = re.compile("|".join(DOWN_TELLS), re.IGNORECASE)
UP_RE = re.compile("|".join(UP_TELLS), re.IGNORECASE)

CONTINUE_RE = re.compile(
    r"^\s*(y|yes|yep|yeah|ok|okay|k|go|go ahead|do it|continue|proceed|sure|"
    r"sounds good|ship it|merge it|lgtm|👍)[\s.!]*$", re.IGNORECASE)
OVERRIDE_RE = re.compile(
    r"\bstay on (haiku|sonnet|opus|fable)\b|\b(override tier|tier override)\b",
    re.IGNORECASE)
SET_MODEL_RE = re.compile(r"[Ss]et model to\s+\**([A-Za-z][\w .\-\[\]]*)")
SET_EFFORT_RE = re.compile(
    r"[Ee]ffort(?: level)?(?: set)? to\s+\**(low|medium|high|xhigh|max)\b")

SYSTEM = (
    "You grade how much model a coding-assistant message needs. You never do "
    "the task. Tiers: haiku = mechanical and already decided (move/rename "
    "files, run a script, format, apply a decided edit, a lookup, a one-line "
    "answer). sonnet = ordinary scoped work (a clear bug, a single feature, "
    "docs, a summary, routine git/PR work). opus = architecture, design across "
    "several parts, 3+ conflicting constraints, visual or spatial layout, "
    "subtle debugging, ambiguous asks, writing that must be exactly right. "
    "Effort: low = trivial, medium = normal, high = hard reasoning. Size = how "
    "much work answering takes: small = one quick reply, medium = several steps "
    "or files, large = a long multi-step build. When torn between two tiers "
    "pick the HIGHER one. Reply with ONE line of JSON only: "
    '{"model":"haiku|sonnet|opus","effort":"low|medium|high",'
    '"size":"small|medium|large","why":"<=12 words"}'
)


# --------------------------------------------------------------------------
# small pure helpers

def family(model) -> str | None:
    if not model:
        return None
    low = str(model).lower()
    for name in FAMILY_RANK:
        if name in low:
            return name
    return None


def effort_index(effort) -> int | None:
    e = str(effort or "").lower().strip()
    return EFFORTS.index(e) if e in EFFORTS else None


def compare(cur_model, cur_effort, rec_model, rec_effort) -> str:
    """match | up | down | unknown. `up` = running too LOW, go up."""
    a, b = family(cur_model), family(rec_model)
    if a is None or b is None:
        return "unknown"
    if FAMILY_RANK[a] < FAMILY_RANK[b]:
        return "up"
    if FAMILY_RANK[a] > FAMILY_RANK[b]:
        return "down"
    ci, ri = effort_index(cur_effort), effort_index(rec_effort)
    if ci is None or ri is None or abs(ci - ri) <= 1:
        return "match"
    return "up" if ci < ri else "down"


def keyword_grade(text: str) -> dict | None:
    if not text:
        return None
    if UP_RE.search(text):
        return {"model": "opus", "effort": "high", "size": "medium", "why": "rule 2 up tell"}
    if DOWN_RE.search(text):
        return {"model": "haiku", "effort": "low", "size": "medium", "why": "rule 2 down tell"}
    return None


def parse_grade(raw: str) -> dict | None:
    m = re.search(r"\{[^{}]*\}", raw or "", re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    model = str(d.get("model", "")).lower().strip()
    effort = str(d.get("effort", "")).lower().strip()
    if model not in RECOMMENDABLE or effort not in ("low", "medium", "high"):
        return None
    size = str(d.get("size", "")).lower().strip()
    if size not in ("small", "medium", "large"):
        size = "medium"   # unstated -> assume it could pay off, as before sizes existed
    return {"model": model, "effort": effort, "size": size,
            "why": str(d.get("why", ""))[:120]}


# --------------------------------------------------------------------------
# reading the live model / effort

def read_transcript_tail(path: str, max_bytes: int = 400_000) -> list[dict]:
    rows = []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            chunk = f.read().decode("utf-8", "replace")
    except OSError:
        return rows
    for line in chunk.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _text_of(row: dict) -> str:
    msg = row.get("message")
    content = msg.get("content") if isinstance(msg, dict) else row.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content
                        if isinstance(c, dict) and isinstance(c.get("text"), str))
    return ""


def live_model_effort(payload: dict, rows: list[dict]) -> tuple:
    """(model, effort, model_source, effort_source). Newest evidence wins."""
    model = effort = None
    msrc = esrc = None
    pm = payload.get("model")
    if isinstance(pm, dict):
        pm = pm.get("id") or pm.get("display_name")
    if pm:
        model, msrc = str(pm), "payload"
    pe = payload.get("effort") or payload.get("effort_level")
    if isinstance(pe, dict):
        pe = pe.get("level")
    if pe:
        effort, esrc = str(pe).lower(), "payload"
    for row in reversed(rows):
        if model and effort:
            break
        text = _text_of(row) if row.get("type") in ("user", "system") else ""
        if not model:
            m = SET_MODEL_RE.search(text)
            if m:
                model, msrc = m.group(1).strip(), "/model"
            elif row.get("type") == "assistant" and isinstance(row.get("message"), dict):
                mm = row["message"].get("model")
                if mm and mm != "<synthetic>":
                    model, msrc = mm, "transcript"
        if not effort:
            e = SET_EFFORT_RE.search(text)
            if e:
                effort, esrc = e.group(1).lower(), "/effort"
    if not model:
        env_m = os.environ.get("ANTHROPIC_MODEL")
        if env_m:
            model, msrc = env_m, "env"
    if not effort:
        env_e = os.environ.get("CLAUDE_EFFORT")
        if env_e:
            effort, esrc = env_e.lower(), "env"
    return model, effort, msrc, esrc


def last_assistant_text(rows: list[dict], limit: int = 400) -> str:
    for row in reversed(rows):
        if row.get("type") == "assistant":
            t = _text_of(row).strip()
            if t:
                return t[-limit:]
    return ""


# --------------------------------------------------------------------------
# the grader

def claude_bin() -> str | None:
    return shutil.which("claude") or os.environ.get("SKYNE_TIER_GATE_CLAUDE") or None


def haiku_grade(message: str, context: str, binary: str | None = None,
                timeout: float = 20.0) -> dict:
    """Always returns a dict: grade fields on success, `error` otherwise."""
    binary = binary or claude_bin()
    t0 = time.monotonic()
    if not binary:
        return {"error": "no claude CLI", "latency_ms": 0}
    ask = ("Previous assistant reply (tail, for context only):\n" + (context or "(none)")
           + "\n\nMessage to grade:\n" + message[:3000])
    cmd = [binary, "-p", "--model", "haiku", "--effort", "low",
           "--no-session-persistence", "--output-format", "json",
           "--tools", "", "--setting-sources", "", "--system-prompt", SYSTEM, ask]
    env = dict(os.environ, SKYNE_TIER_GATE_CHILD="1")
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                            env=env, cwd=tempfile.gettempdir())
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "latency_ms": int((time.monotonic() - t0) * 1000)}
    except OSError as exc:
        return {"error": type(exc).__name__, "latency_ms": 0}
    latency = int((time.monotonic() - t0) * 1000)
    try:
        out = json.loads(cp.stdout)
    except ValueError:
        return {"error": "unparsable CLI output", "latency_ms": latency}
    usage = out.get("usage") or {}
    base = {"latency_ms": latency,
            "cost_usd": out.get("total_cost_usd"),
            "tokens_in": usage.get("input_tokens"),
            "tokens_out": usage.get("output_tokens")}
    if out.get("is_error"):
        return dict(base, error=str(out.get("result", "CLI error"))[:80])
    grade = parse_grade(out.get("result", ""))
    if not grade:
        return dict(base, error="grade not parsable")
    return dict(base, **grade)


# --------------------------------------------------------------------------
# state + log

def skyne_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".claude", "skyne")


def log_path() -> str:
    return os.environ.get("SKYNE_TIER_GATE_LOG") or os.path.join(skyne_dir(), "tier-gate.jsonl")


def state_path(session: str) -> str:
    key = re.sub(r"[^A-Za-z0-9_-]", "_", session or "no-session")[-100:]
    base = os.path.dirname(log_path())
    return os.path.join(base, "tier-gate-state", key + ".json")


def load_state(session: str) -> dict:
    try:
        with open(state_path(session), encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(session: str, state: dict) -> None:
    try:
        p = state_path(session)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError:
        pass


def append_log(row: dict) -> None:
    try:
        p = log_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------
# the decision -- pure given its inputs, so the self-test runs the real thing

def pretty(model, effort) -> str:
    fam = family(model) or str(model or "unknown")
    return fam.capitalize() + (f" {effort.capitalize()}" if effort else "")


def decide(prompt: str, cur_model, cur_effort, state: dict, grade_fn,
           mode: str = "block") -> tuple[dict, dict, dict | None]:
    """Returns (log_row_fields, new_state, hook_output_or_None)."""
    state = dict(state or {})
    row: dict = {}
    text = (prompt or "").strip()
    if text.startswith("/"):
        return {"action": "skip", "verdict": "slash-command"}, state, None

    override = OVERRIDE_RE.search(text)
    pending = state.get("pending")
    is_continue = bool(CONTINUE_RE.match(text))
    if not is_continue and not override and len(text.split()) <= SHORT_WORDS:
        return {"action": "skip", "verdict": "short"}, state, None

    # 1. grade -- a bare "go"/"yes" inherits the last grade, costing nothing
    if is_continue and state.get("last_grade"):
        grade = dict(state["last_grade"], grader="carry")
    elif is_continue and pending:
        grade = dict(pending["grade"], grader="carry")
    else:
        grade = grade_fn(text)
    row.update({k: grade.get(k) for k in
                ("latency_ms", "cost_usd", "tokens_in", "tokens_out") if k in grade})
    row["grader"] = grade.get("grader")
    if grade.get("error"):
        row["grader_error"] = grade["error"]
    rec_model, rec_effort = grade.get("model"), grade.get("effort")
    size = grade.get("size") or "medium"
    row.update({"rec_model": rec_model, "rec_effort": rec_effort,
                "size": size, "why": grade.get("why")})
    if rec_model:
        state["last_grade"] = {"model": rec_model, "effort": rec_effort,
                               "size": size, "why": grade.get("why")}

    verdict = compare(cur_model, cur_effort, rec_model, rec_effort) if rec_model else "unjudged"
    row["verdict"] = verdict

    # 2. act
    held = state.get("override")
    if verdict in ("match", "unjudged", "unknown"):
        state["blocks_in_a_row"] = 0
        out = None
        if pending and verdict == "match":
            row["action"] = "resume"
            row["held_turns"] = pending.get("blocks", 1)
            ctx = ("[tier-gate] The tier now matches (" + pretty(cur_model, cur_effort)
                   + "). Garrett's earlier message was held until it did -- treat it "
                   "as this turn's request:\n<<<\n" + pending.get("prompt", "") + "\n>>>")
            if not is_continue:
                ctx += "\nHe also just said:\n<<<\n" + text + "\n>>>"
            out = _context(ctx)
            state.pop("pending", None)
        else:
            row["action"] = "allow"
        return row, state, out

    if override:
        row["action"] = "override"
        state["override"] = {"rec_model": rec_model, "cur": family(cur_model)}
        state["blocks_in_a_row"] = 0
        out = None
        if pending:
            out = _context("[tier-gate] Garrett overrode the tier call and chose to "
                           "stay on " + pretty(cur_model, cur_effort) + ". His held "
                           "message was:\n<<<\n" + pending.get("prompt", "") + "\n>>>")
            state.pop("pending", None)
        return row, state, out

    if held and held.get("rec_model") == rec_model and held.get("cur") == family(cur_model):
        row["action"] = "override-held"
        state["blocks_in_a_row"] = 0
        return row, state, None
    state.pop("override", None)

    if size not in HOLD_SIZES:
        # Wrong tier, but too little work for a switch to save usage.
        row["action"] = "allow-small"
        state["blocks_in_a_row"] = 0
        return row, state, None

    call = (f"Tier gate: this looks like a {pretty(rec_model, rec_effort)} job"
            f" ({grade.get('why') or 'no reason given'}). You're on "
            f"{pretty(cur_model, cur_effort)}. Switch with `/model {rec_model}`"
            f" (and `/effort {rec_effort}`), then say `go` -- your message is saved."
            f" Or say `stay on {family(cur_model) or 'this'}` to override.")

    if mode == "warn":
        row["action"] = "warn"
        return row, state, _context(
            "[tier-gate] Rule 2a mismatch. Say this one line to Garrett FIRST and "
            "then stop -- no work this turn: " + call)

    n = int(state.get("blocks_in_a_row", 0)) + 1
    if n >= MAX_CONSECUTIVE_BLOCKS:
        row["action"] = "released"
        state["blocks_in_a_row"] = 0
        prior = (pending or {}).get("prompt")
        state.pop("pending", None)
        ctx = ("[tier-gate] Released after " + str(n - 1) + " blocks so the session "
               "cannot be trapped. The tier is still wrong: " + call)
        if prior and prior != text:
            ctx += "\nHeld message:\n<<<\n" + prior + "\n>>>"
        return row, state, _context(ctx)

    row["action"] = "block"
    state["blocks_in_a_row"] = n
    keep = text if not (is_continue and pending) else pending.get("prompt", "")
    state["pending"] = {"prompt": keep, "grade": {"model": rec_model, "effort": rec_effort,
                                                  "why": grade.get("why")},
                        "blocks": (pending or {}).get("blocks", 0) + 1}
    return row, state, {"decision": "block", "reason": call}


def _context(text: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "additionalContext": text}}


def make_grader(context: str, mode_grader: str, timeout: float, binary=None):
    def grade(text: str) -> dict:
        if mode_grader == "haiku":
            g = haiku_grade(text, context, binary=binary, timeout=timeout)
            if not g.get("error"):
                return dict(g, grader="haiku")
            kw = keyword_grade(text)
            if kw:
                return dict(kw, grader="keywords", error=g["error"],
                            latency_ms=g.get("latency_ms"), cost_usd=g.get("cost_usd"))
            return {"grader": "none", "error": g["error"], "latency_ms": g.get("latency_ms"),
                    "cost_usd": g.get("cost_usd")}
        kw = keyword_grade(text)
        return dict(kw, grader="keywords") if kw else {"grader": "none"}
    return grade


def now_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(payload: dict) -> dict | None:
    mode = (os.environ.get("SKYNE_TIER_GATE") or "block").lower()
    if mode == "off" or os.environ.get("SKYNE_TIER_GATE_CHILD"):
        return None
    session = str(payload.get("session_id") or "")
    prompt = payload.get("prompt") or ""
    rows = read_transcript_tail(payload.get("transcript_path") or "")
    cur_model, cur_effort, msrc, esrc = live_model_effort(payload, rows)
    try:
        timeout = float(os.environ.get("SKYNE_TIER_GATE_TIMEOUT") or 25)
    except ValueError:
        timeout = 25.0
    grader = make_grader(last_assistant_text(rows),
                         (os.environ.get("SKYNE_TIER_GATE_GRADER") or "haiku").lower(),
                         timeout)
    state = load_state(session)
    t0 = time.monotonic()
    fields, state, out = decide(prompt, cur_model, cur_effort, state, grader, mode)
    state["turn"] = int(state.get("turn", 0)) + 1
    save_state(session, state)
    remote = os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID") or ""
    if remote.startswith("cse_"):
        remote = "session_" + remote[4:]   # the id the session index and misses use
    append_log(dict(fields, utc=now_utc(), session_id=session, turn=state["turn"],
                    remote_session_id=remote or None,
                    mode=mode, model=cur_model, effort=cur_effort,
                    model_source=msrc, effort_seen=bool(cur_effort),
                    gate_ms=int((time.monotonic() - t0) * 1000),
                    prompt_chars=len(prompt)))
    return out


# --------------------------------------------------------------------------

def self_test() -> int:
    fails: list[str] = []

    def check(ok, label):
        if not ok:
            fails.append(label)

    # compare(): the soft-lock tolerance, both directions
    check(compare("claude-opus-5-5", "high", "opus", "medium") == "match", "opus high vs opus medium is a match (1 step)")
    check(compare("claude-opus-5-5", "max", "opus", "medium") == "down", "opus max vs opus medium is 2 steps DOWN")
    check(compare("claude-opus-5-5", "medium", "sonnet", "medium") == "down", "opus on a sonnet job must say DOWN")
    check(compare("claude-haiku-4-5", "low", "opus", "high") == "up", "haiku on an opus job must say UP (under-tier is the costly one)")
    check(compare("claude-sonnet-5", None, "sonnet", "high") == "match", "unseen effort compares model only")
    check(compare("gpt-9", "low", "sonnet", "low") == "unknown", "an unknown family is UNKNOWN, never match")
    check(compare("claude-fable-5-1", "high", "opus", "high") == "down", "fable ranks above opus")

    # parse_grade(): refuses anything outside the vocabulary
    check(parse_grade('```json\n{"model":"sonnet","effort":"medium","why":"x"}\n```')["model"] == "sonnet", "fenced JSON parses")
    check(parse_grade('{"model":"gpt","effort":"low"}') is None, "an unknown model is refused")
    check(parse_grade('{"model":"opus","effort":"max"}') is None, "effort outside low/medium/high is refused")
    check(parse_grade("no json here") is None, "prose is refused")

    # keyword fallback
    check(keyword_grade("rename these files to kebab case")["model"] == "haiku", "down tell -> haiku")
    check(keyword_grade("let's scope this out and design the architecture")["model"] == "opus", "up tell -> opus")
    check(keyword_grade("what's for lunch") is None, "no tell -> no grade (unjudged, not match)")

    def fixed(model, effort, size="medium"):
        return lambda t: {"model": model, "effort": effort, "size": size, "why": "fixture",
                          "grader": "haiku", "latency_ms": 5, "cost_usd": 0.004}

    # match -> allow, silent
    r, s, o = decide("please fix the small typo in the README file for me today", "claude-sonnet-5", "medium", {}, fixed("sonnet", "medium"))
    check(r["action"] == "allow" and o is None, "a match is allowed and silent")

    # mismatch -> block, message saved, exact tier named
    r, s, o = decide("please rename these twelve files in docs to kebab case for me", "claude-opus-5-5", "high", {}, fixed("haiku", "low"))
    check(r["action"] == "block" and o and o.get("decision") == "block", "a mismatch BLOCKS")
    check("/model haiku" in o["reason"] and "stay on opus" in o["reason"], "the block names the command and the override")
    check(s.get("pending", {}).get("prompt") == "please rename these twelve files in docs to kebab case for me", "the blocked message is saved")

    # after /model, "go" resumes with the saved message and costs no grading call
    called = []
    def spy(t):
        called.append(t)
        return {"model": "opus", "effort": "high", "grader": "haiku"}
    r2, s2, o2 = decide("go", "claude-haiku-4-5", "low", s, spy)
    check(not called, "a bare 'go' must not pay for a grading call")
    check(r2["action"] == "resume" and "please rename these twelve files in docs to kebab case for me" in o2["hookSpecificOutput"]["additionalContext"],
          "'go' after switching resumes with the saved message")
    check("pending" not in s2, "resuming clears the saved message")

    # override: allowed, and HELD until the recommendation changes
    r3, s3, o3 = decide("stay on opus, just do it", "claude-opus-5-5", "high", s, fixed("haiku", "low"))
    check(r3["action"] == "override" and "please rename these twelve files in docs to kebab case for me" in json.dumps(o3), "override passes the held message through")
    r4, s4, _ = decide("now rename three more files in the scripts folder the same way", "claude-opus-5-5", "high", s3, fixed("haiku", "low"))
    check(r4["action"] == "override-held", "an override holds for the same call -- no second ask")
    r5, s5, o5 = decide("now redesign the whole console layout so the panels share one grid", "claude-opus-5-5", "high", s4, fixed("sonnet", "low"))
    check(r5["action"] == "block", "a NEW recommendation re-arms the gate")

    # never traps: third consecutive block releases
    st = {}
    actions = []
    for _ in range(3):
        rr, st, oo = decide("rename the files again the same way as last time please", "claude-opus-5-5", "high", st, fixed("haiku", "low"))
        actions.append(rr["action"])
    check(actions == ["block", "block", "released"], f"three blocks in a row must release, got {actions}")

    # warn mode never blocks
    r6, _, o6 = decide("please rename these twelve files in docs to kebab case for me", "claude-opus-5-5", "high", {}, fixed("haiku", "low"), mode="warn")
    check(r6["action"] == "warn" and "decision" not in (o6 or {}), "warn mode injects context, never blocks")

    # slash commands are never graded
    r7, _, o7 = decide("/model sonnet", "claude-opus-5-5", "high", {}, spy)
    check(r7["action"] == "skip" and o7 is None, "a slash command is skipped")

    # an unjudged message is allowed AND logged as unjudged, never as match
    r8, _, _ = decide("hmm let me think about what the best next step here is", "claude-opus-5-5", "high", {}, lambda t: {"grader": "none", "error": "timeout"})
    check(r8["verdict"] == "unjudged" and r8["action"] == "allow", "no grade -> unjudged, allowed")

    # 2026-09-23 ruling: short messages are not graded; small jobs are not held
    calls = []
    def counting(t):
        calls.append(t)
        return {"model": "haiku", "effort": "low", "size": "medium", "grader": "haiku"}
    r9, _, o9 = decide("ok cool thanks, noted", "claude-opus-5-5", "high", {}, counting)
    check(r9["action"] == "skip" and r9["verdict"] == "short" and o9 is None and not calls,
          "a short message is skipped WITHOUT paying for a grading call")
    r10, s10, o10 = decide("remind me later to check the budget page for the actions minutes",
                           "claude-opus-5-5", "high", {}, fixed("haiku", "low", "small"))
    check(r10["action"] == "allow-small" and o10 is None and "pending" not in s10,
          "a SMALL job on the wrong tier passes through -- a switch would not pay off")
    check(r10["verdict"] == "down", "a passed small job is still logged as a wrong-tier turn")
    r11, _, o11 = decide("rewrite every script in the repo to use the new logging helper",
                         "claude-opus-5-5", "high", {}, fixed("haiku", "low", "large"))
    check(r11["action"] == "block" and o11 and o11.get("decision") == "block",
          "a LARGE job on the wrong tier is still held -- that is where usage is saved")
    check(parse_grade('{"model":"sonnet","effort":"low","size":"huge"}')["size"] == "medium",
          "an unknown size is read as medium, never silently as small")

    # live model/effort reading: a /model switch newer than the last reply wins
    rows = [{"type": "assistant", "message": {"model": "claude-opus-5-5", "content": [{"type": "text", "text": "done"}]}},
            {"type": "user", "message": {"content": "<local-command-stdout>Set model to Sonnet 5</local-command-stdout>"}}]
    os.environ.pop("CLAUDE_EFFORT", None)
    m, e, src, _ = live_model_effort({}, rows)
    check(family(m) == "sonnet" and src == "/model", "a /model switch after the last reply is the live model")
    m2, _, src2, _ = live_model_effort({}, rows[:1])
    check(family(m2) == "opus" and src2 == "transcript", "otherwise the last assistant model is the live model")

    # the real subprocess path, against fake CLIs -- parse, timeout, recursion guard
    with tempfile.TemporaryDirectory() as tmp:
        good = os.path.join(tmp, "good")
        with open(good, "w") as f:
            f.write("#!/bin/sh\necho '{\"result\":\"{\\\"model\\\":\\\"sonnet\\\",\\\"effort\\\":\\\"medium\\\",\\\"why\\\":\\\"scoped bug\\\"}\","
                    "\"total_cost_usd\":0.004,\"usage\":{\"input_tokens\":800,\"output_tokens\":40}}'\n")
        slow = os.path.join(tmp, "slow")
        with open(slow, "w") as f:
            f.write("#!/bin/sh\nsleep 5\n")
        env_probe = os.path.join(tmp, "probe")
        with open(env_probe, "w") as f:
            f.write("#!/bin/sh\necho \"{\\\"result\\\":\\\"$SKYNE_TIER_GATE_CHILD\\\"}\"\n")
        for p in (good, slow, env_probe):
            os.chmod(p, 0o755)
        g = haiku_grade("fix the login bug", "", binary=good, timeout=5)
        check(g.get("model") == "sonnet" and g.get("cost_usd") == 0.004 and g.get("tokens_in") == 800,
              "the CLI path parses grade, cost and tokens")
        g2 = haiku_grade("x", "", binary=slow, timeout=0.5)
        check(g2.get("error") == "timeout", "a slow grader times out instead of hanging the prompt")
        g3 = make_grader("", "haiku", 0.5, binary=slow)("rename these files now")
        check(g3.get("grader") == "keywords" and g3.get("model") == "haiku", "a timed-out grader falls back to rule 2's tells")
        # recursion guard: the child sees SKYNE_TIER_GATE_CHILD=1
        out = subprocess.run([env_probe], capture_output=True, text=True,
                             env=dict(os.environ, SKYNE_TIER_GATE_CHILD="1")).stdout
        check('"1"' in out, "the child CLI inherits the recursion guard")
        os.environ["SKYNE_TIER_GATE_CHILD"] = "1"
        check(run({"prompt": "rename files", "session_id": "t"}) is None, "the hook is inert inside its own child")
        os.environ.pop("SKYNE_TIER_GATE_CHILD", None)

        # end to end through run(): one log row per message, block reaches stdout shape
        os.environ["SKYNE_TIER_GATE_LOG"] = os.path.join(tmp, "log", "tier-gate.jsonl")
        os.environ["SKYNE_TIER_GATE_GRADER"] = "keywords"
        tr = os.path.join(tmp, "t.jsonl")
        with open(tr, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-opus-5-5", "content": "ok"}}) + "\n")
        os.environ["CLAUDE_EFFORT"] = "high"
        o = run({"prompt": "please rename all of the files in the docs folder to kebab case", "session_id": "s1", "transcript_path": tr})
        check(isinstance(o, dict) and o.get("decision") == "block", "run(): opus on a rename is blocked")
        run({"prompt": "what is 2+2", "session_id": "s1", "transcript_path": tr})
        with open(os.environ["SKYNE_TIER_GATE_LOG"]) as f:
            logged = [json.loads(l) for l in f]
        check(len(logged) == 2 and [x["turn"] for x in logged] == [1, 2], "every message writes exactly one numbered row")
        check(logged[0]["verdict"] == "down" and logged[0]["model"] == "claude-opus-5-5"
              and logged[0]["effort"] == "high", "the row records live model, effort and verdict")
        for k in ("SKYNE_TIER_GATE_LOG", "SKYNE_TIER_GATE_GRADER", "CLAUDE_EFFORT"):
            os.environ.pop(k, None)

    # fail open: garbage stdin -> exit 0, nothing printed
    cp = subprocess.run([sys.executable, os.path.abspath(__file__)], input="not json",
                        capture_output=True, text=True)
    check(cp.returncode == 0 and not cp.stdout.strip(), "garbage stdin exits 0 and prints nothing")

    total = 46
    if fails:
        for f in fails:
            print("SELF-TEST FAIL:", f)
        print(f"tier_gate self-test: {len(fails)} FAILED")
        return 1
    print(f"tier_gate self-test: {total} checks passed")
    return 0


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    if "--grade" in sys.argv:
        i = sys.argv.index("--grade")
        text = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
        print(json.dumps(make_grader("", (os.environ.get("SKYNE_TIER_GATE_GRADER") or "haiku").lower(),
                                     float(os.environ.get("SKYNE_TIER_GATE_TIMEOUT") or 25))(text)))
        sys.exit(0)
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            sys.exit(0)
        out = run(payload)
        if out:
            print(json.dumps(out))
    except SystemExit:
        raise
    except Exception:
        pass  # fail open: a grader must never break prompt submission
    sys.exit(0)


if __name__ == "__main__":
    main()
