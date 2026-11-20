#!/usr/bin/env python3
"""w_follow.py -- shared parts of the W follow-up gates (wince_gate.py, wren_gate.py).

RULED 2026-11-16 (Skyne DECISIONS R5, R9, R10, R12, R13, R19, R22). This module
holds what both gates share, so there is one reading of each rule:

* the SWITCH `~/.claude/skyne/w-follow-mode` (R10): `enforce` (the default) or
  `log`. Read as BYTES and decoded by byte-order mark, because Windows
  PowerShell writes UTF-16 (`>`) or UTF-8 with a BOM (`Out-File`) and a plain
  read turns "log" into garbage that silently enforces. Missing = enforce,
  silently. Empty or unrecognized = enforce AND a visible line saying so.
* the LOG `~/.claude/skyne/w-follow.jsonl`: one row per gate call.
* PUBLISH detection (R9): an Artifact call with `action` omitted or "publish"
  and not `asset: true`; a Figma write tool, by suffix, from figma-tools.json.
* the QUEUES the gates read to see whether a Wince grade was filed
  (`wince-grades-queue.jsonl`, `redteam-rounds-queue.jsonl`), by CONTENT: a row
  whose session is THIS session and whose time is after the Wince finish.
* the GO-LIVE record and the day-14 review date (R22). No alarm before it.
* the CLOUD branch (R12), see `cloud_enforces()`.

NAMED BLIND SPOTS (told to Garrett in the pre-C message)
--------------------------------------------------------
* Since 2026-11-19 the trigger is a Plan board feature marked Checked, not a
  label or a publish. Garrett tapping Checked on the board himself is not seen. * Files written by subagents or by scripts are not
  seen as writes. * Cloud: see cloud_enforces(). * A grade filed by a command that
  never reached a queue or a register is not seen, on purpose.

Usage:  python3 w_follow.py --self-test
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from w_ran import FOLLOWED  # noqa: E402  -- the nine labels

LABELS = tuple(w.capitalize() for w in FOLLOWED)        # Wistin ... Wince
LABEL_RX = re.compile(r"^\s*(%s):\s" % "|".join(LABELS))
MAKER_LABELS = ("Wistin", "Wick", "Ward", "Warden", "Whittle")
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
# RULED 2026-11-19 (Skyne DECISIONS): the automatic Wince/Wren runs fire when a turn
# marks a Plan board feature's Checked stage done, and no longer on a W label or a
# publish. The board's stage order lives in skyne data/plan-board/board.json; `s`
# is positional, so the Checked index is read from the row's LENGTH: seven stages
# (asked, decided, designed, CHECKED, built, live, used) since 2026-11-19, five
# (decided, designed, CHECKED, built, live) before it.
CHECKED_AT = {7: 3, 5: 2}
BOARD_TOOL_SUFFIX = "ArtifactData"


def _board_writes(inp: dict) -> list[dict]:
    act = inp.get("action")
    if act in ("set", "update"):
        return [{"collection": inp.get("collection"), "doc_id": inp.get("doc_id"),
                 "data": inp.get("data"), "file_path": inp.get("file_path")}]
    if act == "batch":
        return [w for w in inp.get("writes") or [] if isinstance(w, dict) and w.get("op") in ("set", "update")]
    return []


def _is_features(col) -> bool:
    return str(col or "").split("/")[-1] == "features"


def _write_data(w: dict):
    """The fields a write sends: inline `data`, or the JSON file named by
    `file_path` (Wince 2026-11-19: real batches on this board use file_path)."""
    if isinstance(w.get("data"), dict):
        return w["data"]
    fp = w.get("file_path")
    if fp:
        try:
            with open(fp, encoding="utf-8") as fh:
                d = json.load(fh)
            return d if isinstance(d, dict) else None
        except (OSError, ValueError):
            return None
    return None


def _when(v) -> float | None:
    try:
        t = _dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=_dt.timezone.utc)
    return t.timestamp()


CHECKED_WINDOW = (2 * 3600, 15 * 60)   # a Checked date up to 2 h before the write, or 15 min after


class CheckedWatch:
    """The trigger is the Checked DATE (Wince 2026-11-19, round 2). Skyne's
    plan_board.py check refuses Checked done without stageDates.checked, and
    the board page writes that date on every tap, so marking Checked means
    writing a fresh Checked date (a full time, or today's date in ET). A write fires when it sets
    stageDates.checked to a time near the write itself, and to a value this
    session has not already written for that feature. Re-sending a row
    (Built, Live, the Used number two weeks on) carries the OLD date, so it is
    quiet. Not seen: a Checked marked with no date (the gate cannot tell a new
    undated mark from a re-send of a row that already has a date, so it says
    nothing; the Plan board card and the nightly copy-back, which read the
    STORED row, name it -- Wince 2026-11-20), and a re-send inside two hours of
    the mark from a session that did not make the mark."""

    def __init__(self):
        self.sent = {}           # doc_id -> Checked date this session wrote

    def marks(self, name, inp, ts: str = "") -> list:
        """Feature ids this call marks Checked. Also remembers what it wrote."""
        if not str(name or "").endswith(BOARD_TOOL_SUFFIX) or not isinstance(inp, dict):
            return []
        now = _when(ts) if ts else None
        from w_cost import et_day
        out = []
        for w in _board_writes(inp):
            if not _is_features(w.get("collection")):
                continue
            data = _write_data(w)
            sd = (data or {}).get("stageDates")
            v = sd.get("checked") if isinstance(sd, dict) else None
            fid = str(w.get("doc_id") or "?")
            st = (data or {}).get("s")
            if not v:
                # No date in the WRITE: a new mark or a re-send of a row that already has one (a Built,
                # Live or Used write). The gate cannot tell, so it neither refuses nor logs (Wince
                # 2026-11-20 reproduced the false log on BL-6); the stored row is read nightly instead.
                continue
            if len(str(v)) == 10:            # a date only: today in Garrett's time, or today in UTC
                # (a date written in UTC near midnight is a day ahead of Eastern; Wince 2026-11-20)
                fresh = now is None or str(v) in (et_day(ts), str(ts)[:10])
            else:
                at = _when(v)
                fresh = at is not None and (now is None or now - CHECKED_WINDOW[0] <= at <= now + CHECKED_WINDOW[1])
            if isinstance(st, list) and len(st) in CHECKED_AT and st[CHECKED_AT[len(st)]] != "done":
                fresh = False                # Checked set back while the old date rides along
            if fresh and self.sent.get(fid) != v:
                out.append(fid)
            self.sent[fid] = v
        return out


def checked_marks(name, inp, watch: "CheckedWatch | None" = None, ts: str = "") -> list:
    """Feature ids this one call marks Checked (a fresh watch: nothing known)."""
    return (watch or CheckedWatch()).marks(name, inp, ts)


LENS4_RX = re.compile(r"\[red-team lens 4:\s*([^\]\s][^\]]*?)\s*\]")

# R12: attended cloud chats are meant to enforce like this PC, scheduled runs to
# log only. Cloud delivery and the attended/scheduled signal could NOT be
# confirmed from the PC session that built this (no cloud session can be
# started from here), so C ships PC-only: in the cloud the new triggers LOG and
# never refuse. Flip this once a cloud session has shown the env signal.
CLOUD_ENFORCES = False


# ------------------------------------------------------------------ locations

def state_dir() -> str:
    return os.environ.get("SKYNE_STATE_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude", "skyne")


def _p(env: str, name: str) -> str:
    return os.environ.get(env) or os.path.join(state_dir(), name)


def mode_path() -> str:
    return _p("SKYNE_W_FOLLOW_MODE", "w-follow-mode")


def log_path() -> str:
    return _p("SKYNE_W_FOLLOW_LOG", "w-follow.jsonl")


def grades_queue_path() -> str:
    return _p("SKYNE_GRADES_QUEUE", "wince-grades-queue.jsonl")


def rounds_queue_path() -> str:
    return _p("SKYNE_ROUNDS_QUEUE", "redteam-rounds-queue.jsonl")


def golive_path() -> str:
    return _p("SKYNE_W_FOLLOW_GOLIVE", "w-follow-golive.json")


# --------------------------------------------------------------------- switch

def decode_mode_bytes(raw: bytes) -> str:
    """UTF-8 BOM, UTF-16 LE/BE (with BOM, or BOM-less but NUL-interleaved), plain."""
    if raw.startswith(b"\xef\xbb\xbf"):
        text = raw[3:].decode("utf-8", errors="replace")
    elif raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16", errors="replace")      # the BOM picks the order
    elif len(raw) >= 2 and raw[1:2] == b"\x00" and raw[0:1] != b"\x00":
        text = raw.decode("utf-16-le", errors="replace")
    elif len(raw) >= 2 and raw[0:1] == b"\x00" and raw[1:2] != b"\x00":
        text = raw.decode("utf-16-be", errors="replace")
    else:
        text = raw.decode("utf-8", errors="replace")
    return text.replace("\x00", "").replace("\ufeff", "").strip().lower()


def read_mode(path: str | None = None) -> tuple[str, str]:
    """(mode, note). mode is 'enforce' or 'log'. note is '' unless the file is
    there and says something that is not one of the two words."""
    path = path or mode_path()
    try:
        with open(path, "rb") as f:
            raw = f.read(4096)
    except FileNotFoundError:
        return "enforce", ""
    except OSError as exc:
        return "enforce", f"w-follow-mode could not be read ({type(exc).__name__}): enforcing"
    word = decode_mode_bytes(raw)
    if word in ("enforce", "log"):
        return word, ""
    shown = word[:30] if word else "(empty)"
    return "enforce", (f"w-follow-mode says {shown!r}, which is not 'enforce' or 'log', so "
                       f"the gates enforce. Tell Garrett; only he decides whether they log instead.")


# ----------------------------------------------------------------------- cloud

def is_cloud() -> bool:
    return os.environ.get("CLAUDE_CODE_REMOTE", "").lower() == "true"


def cloud_enforces() -> bool:
    """Whether the NEW triggers may refuse in this environment. On this PC: yes.
    In the cloud: only when CLOUD_ENFORCES is on AND the run is attended; the
    attended/scheduled signal is unconfirmed, so today the answer is no."""
    if not is_cloud():
        return True
    return CLOUD_ENFORCES and os.environ.get("SKYNE_ATTENDED", "") == "1"


# ------------------------------------------------------------------- the log

def now_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def locked_append(path: str, line: str, wait_s: float = 2.0) -> bool:
    """Append one whole line while holding `<path>.wlock` (O_EXCL), so two hooks
    writing in the same instant cannot tear each other's line (seen 2026-11-20:
    the wince and wren gates both wrote at 01:58:18Z and one row was cut in half).
    A hook never hangs on it: after `wait_s` (or on a lock older than 10 s, a
    crash) it writes anyway."""
    import time
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lk = path + ".wlock"
    held = False
    deadline = time.time() + wait_s
    while not held:
        try:
            fd = os.open(lk, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            held = True
        except FileExistsError:
            try:
                if time.time() - os.stat(lk).st_mtime > 10:
                    os.unlink(lk)
                    continue
            except OSError:
                continue
            if time.time() > deadline:
                break
            time.sleep(0.02)
        except OSError:
            # Windows: creating a lock file that is still being deleted raises
            # PermissionError. That is "busy": wait, as w_queue does (W red team round 3).
            if time.time() > deadline:
                break
            time.sleep(0.02)
    try:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line if line.endswith("\n") else line + "\n")
            f.flush()
        return True
    except OSError:
        return False
    finally:
        if held:
            try:
                os.unlink(lk)
            except OSError:
                pass


def log_row(row: dict, path: str | None = None) -> bool:
    path = path or log_path()
    return locked_append(path, json.dumps(dict({"utc": now_utc()}, **row), sort_keys=True))


def log_error(gate: str, exc: BaseException, path: str | None = None) -> None:
    """A gate that crashed writes an `error` row, so the heartbeat can say so
    (W red team round 1, problem 7: a crash used to leave no trace at all)."""
    try:
        log_row({"gate": gate, "action": "error",
                 "error": f"{type(exc).__name__}: {str(exc)[:200]}"}, path)
    except Exception:                                          # noqa: BLE001
        pass


def read_jsonl(path: str) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    out.append(r)
    except OSError:
        pass
    return out


def record_golive(path: str | None = None, today: str | None = None) -> None:
    """First enforced gate run on this PC writes the go-live date, once. The
    day-14 review is that date + 14 (R22). Nothing speaks before it."""
    path = path or golive_path()
    if os.path.exists(path):
        return
    try:
        from w_cost import et_today
        today = today or et_today()
        day = _dt.datetime.strptime(today, "%Y-%m-%d")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "x", encoding="utf-8", newline="\n") as f:
            json.dump({"go_live": today,
                       "review_on": (day + _dt.timedelta(days=14)).strftime("%Y-%m-%d"),
                       "reviewed": False,
                       "note": "R22: the review is at day 14, no mid-trial alarm"}, f, indent=2)
            f.write("\n")
    except (OSError, ImportError, ValueError):
        pass


# ----------------------------------------------------------- publish detection

def _figma_config() -> dict:
    try:
        with open(os.path.join(HERE, "figma-tools.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"server_ids": [], "server_name_contains": ["figma"], "tools": {}}


def split_mcp(name: str) -> tuple[str, str] | None:
    parts = str(name or "").split("__")
    if len(parts) >= 3 and parts[0] == "mcp":
        return parts[1], "__".join(parts[2:])
    return None


def classify_tool(name: str, inp: dict | None, cfg: dict | None = None) -> str:
    """'publish' | 'figma-unknown' | '' for a main-loop tool_use."""
    inp = inp or {}
    if name == "Artifact":
        action = inp.get("action")
        if (action in (None, "", "publish") and not inp.get("asset")
                and (inp.get("file_path") or inp.get("type_url") or inp.get("url"))):
            return "publish"
        return ""
    sp = split_mcp(name)
    if not sp:
        return ""
    server, suffix = sp
    cfg = cfg or _figma_config()
    is_figma = (server in cfg.get("server_ids", [])
                or any(s in server.lower() for s in cfg.get("server_name_contains", ["figma"])))
    if not is_figma:
        return ""
    kind = (cfg.get("tools", {}).get(suffix) or {}).get("kind")
    if kind == "write":
        return "publish"
    if kind is None:
        return "figma-unknown"
    return ""


# ----------------------------------------------------------- transcript facts

def _ts(s) -> str:
    return str(s or "")[:19]


def turn_facts(entries: list[dict], boundary: int, cfg: dict | None = None) -> dict:
    """What the main loop did since Garrett's last message."""
    texts, writes, pubs, unknown, lens4, checked = [], [], [], [], {}, []
    results = {}
    watch = CheckedWatch()
    for e in entries[:boundary + 1]:          # earlier turns: what Claude read or wrote on the board
        if e.get("isSidechain") or e.get("type") != "assistant":
            continue
        for b in (e.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                watch.marks(b.get("name"), b.get("input") or {}, _ts(e.get("timestamp")))
    for e in entries[boundary + 1:]:
        if e.get("isSidechain"):
            continue
        ts = _ts(e.get("timestamp"))
        content = (e.get("message") or {}).get("content")
        if e.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and str(b.get("text") or "").strip():
                    texts.append((ts, str(b["text"])))
                elif b.get("type") == "tool_use":
                    name, inp = b.get("name"), b.get("input") or {}
                    if name in WRITE_TOOLS:
                        writes.append(ts)
                    checked += [(ts, fid) for fid in watch.marks(name, inp, ts)]
                    kind = classify_tool(name, inp, cfg)
                    if kind == "publish":
                        pubs.append((ts, name))
                    elif kind == "figma-unknown":
                        unknown.append(name)
                    if name in ("Agent", "Task"):
                        m = LENS4_RX.search(str(inp.get("prompt") or ""))
                        if m:
                            lens4[b.get("id")] = m.group(1).strip()
        elif e.get("type") == "user" and isinstance(content, list):
            tur = e.get("toolUseResult")
            if isinstance(tur, dict) and tur.get("agentId"):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        results[b.get("tool_use_id")] = tur["agentId"]
    agent_loop = {results[c]: lp for c, lp in lens4.items() if c in results}
    first = texts[0][1] if texts else ""
    last = texts[-1][1] if texts else ""
    labels = {m.group(1) for t in (first, last) if (m := LABEL_RX.match(t))}
    return {"first_text": first, "last_text": last, "labels": labels,
            "writes": writes, "publishes": pubs, "unknown_figma": unknown, "checked": checked,
            "lens4_by_call": lens4, "lens4_by_agent": agent_loop}


def last_work_ts(facts: dict) -> str:
    cands = list(facts["writes"]) + [t for t, _ in facts["publishes"]]
    return max(cands) if cands else ""


# ---------------------------------------------------------------------- filings

def _session_rows(rows: list[dict], session: str) -> list[dict]:
    return [r for r in rows if r.get("session") == session]


def _filing_id(kind: str, r: dict, t: str) -> tuple:
    """One filing, wherever it is seen. The same row sits in the queue, on
    origin/main, and in every worktree's copy of the register: it is ONE filing
    (W red team round 2: one session's 6 grades were counted 24 times, so
    sessions short of a filing passed). `key` when the row has one; otherwise
    what the row is plus when it was filed."""
    if r.get("key"):
        return (kind, r["key"])
    if kind == "g":
        return (kind, r.get("subject"), r.get("pass"), t)
    return (kind, r.get("loop"), r.get("round"), t)


def filings(session: str, extra_registers: list[str] | None = None) -> dict:
    """Content-matched filings for THIS session: {'grades': [ts...], 'rounds': {loop: [ts...]}}.
    Sources: both local queues, plus any register files named (a register row
    counts through its `filed_utc`). Each filing counts once."""
    seen: dict[tuple, tuple] = {}

    def add(kind, r, t):
        if t:
            seen.setdefault(_filing_id(kind, r, t), (kind, str(r.get("loop")), t))
    for r in _session_rows(read_jsonl(grades_queue_path()), session):
        add("g", r, _ts(r.get("queued_utc")))
    for r in _session_rows(read_jsonl(rounds_queue_path()), session):
        add("r", r, _ts(r.get("queued_utc")))
    for path in extra_registers or []:
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        for r in _session_rows(doc.get("grades", []), session):
            add("g", r, _ts(r.get("filed_utc")))
        for r in _session_rows(doc.get("rounds", []), session):
            add("r", r, _ts(r.get("filed_utc")))
    grades, rounds = [], {}
    for kind, loop, t in seen.values():
        if kind == "g":
            grades.append(t)
        else:
            rounds.setdefault(loop, []).append(t)
    return {"grades": sorted(grades), "rounds": {k: sorted(v) for k, v in rounds.items()}}


def unfiled_runs(runs: list[dict], fil: dict, escape_ts: str = "") -> list[dict]:
    """Each Wince FINISH is accounted for separately and consumes ONE filing at
    or after it. A lens-4 run (tagged with its loop id) is satisfied by a
    redteam_rounds row for that loop OR by a grade row: the round can only be
    filed once all four reviewers are in, so demanding it at lens 4's finish
    asked for a filing the tool refuses (W red team round 2)."""
    grades = list(fil["grades"])
    rounds = {k: list(v) for k, v in fil["rounds"].items()}
    owed = []
    for run in sorted(runs, key=lambda r: r["finish"]):
        if escape_ts and run["finish"] <= escape_ts:
            continue                    # "no grade to file: <why>" said after it
        pools = ([rounds.get(run["loop"], [])] if run.get("loop") else []) + [grades]
        for pool in pools:
            hit = next((i for i, t in enumerate(pool) if t >= run["finish"]), None)
            if hit is not None:
                pool.pop(hit)
                break
        else:
            owed.append(run)
    return owed


# RULED 2026-11-20 (board question W-round-record-block): a missing red-team
# round record stops Claude again, but only once EVERY lens agent of that
# loop's round has finished, so lens 4 finishing first is not refused. The
# red-team skill tags all four lens prompts `[red-team lens N: <loop id>]`.
LENS_RX = re.compile(r"\[red-team lens ([1-4]):\s*([^\]\s][^\]]*?)\s*\]")
NOTIFY_CALL_RX = re.compile(r"<tool-use-id>\s*([^<\s]+)\s*</tool-use-id>")
NOTIFY_STATUS_RX = re.compile(r"<status>\s*([A-Za-z_]+)\s*</status>")
NOTIFY_DONE = {"completed", "failed", "killed", "stopped", "error"}


def lens_runs(entries: list[dict]) -> dict:
    """{loop: [{lens, call, launched, finished}]} for every tagged red-team lens
    agent in the session. A lens finishes at its synchronous tool_result, or,
    when it ran in the background, at the task-notification that names its
    tool-use id (the latest one, since a resumed agent notifies again)."""
    calls: dict[str, dict] = {}
    for e in entries:
        if e.get("isSidechain"):
            continue
        ts = _ts(e.get("timestamp"))
        content = (e.get("message") or {}).get("content")
        if e.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if (isinstance(b, dict) and b.get("type") == "tool_use"
                        and b.get("name") in ("Agent", "Task")):
                    m = LENS_RX.search(str((b.get("input") or {}).get("prompt") or ""))
                    if m:
                        calls[b.get("id")] = {"lens": int(m.group(1)), "loop": m.group(2).strip(),
                                              "call": b.get("id"), "launched": ts, "finished": ""}
        elif e.get("type") == "user" and isinstance(content, list) and calls:
            tur = e.get("toolUseResult")
            launched = isinstance(tur, dict) and (tur.get("isAsync") or tur.get("status") == "async_launched")
            for b in content:
                if (isinstance(b, dict) and b.get("type") == "tool_result"
                        and b.get("tool_use_id") in calls and not launched
                        and "Async agent launched" not in json.dumps(b.get("content"))):
                    run = calls[b["tool_use_id"]]
                    run["finished"] = max(run["finished"], ts)
        elif (e.get("type") == "user" and isinstance(content, str)
              and content.lstrip().startswith("<task-notification>") and calls):
            m, st = NOTIFY_CALL_RX.search(content), NOTIFY_STATUS_RX.search(content)
            if m and m.group(1) in calls and st and st.group(1).lower() in NOTIFY_DONE:
                run = calls[m.group(1)]
                run["finished"] = max(run["finished"], ts)
    out: dict[str, list] = {}
    for run in calls.values():
        out.setdefault(run["loop"], []).append(run)
    return out


def unfiled_rounds(entries: list[dict], fil: dict, escape_ts: str = "") -> list[str]:
    """Loops whose latest round is complete (lenses 1 to 4 all launched since
    the loop's last round row, and every one of them finished) with no round
    row after it. A round still running, or one with only lens 4 tagged (the
    old prompts), owes nothing yet."""
    owed = []
    for loop, runs in sorted(lens_runs(entries).items()):
        filed = sorted(fil.get("rounds", {}).get(loop, []))
        last = filed[-1] if filed else ""
        pending = [r for r in runs if r["launched"] > last]
        if not pending or {r["lens"] for r in pending} < {1, 2, 3, 4}:
            continue
        if not all(r["finished"] for r in pending):
            continue
        done = max(r["finished"] for r in pending)
        if escape_ts and escape_ts >= done:
            continue
        owed.append(loop)
    return owed


# ------------------------------------------------------------------ session lines

def session_lines(today: str | None = None) -> list[str]:
    """What SessionStart tells the session (the session relays it to Garrett).
    Each part runs on its own: one that breaks is NAMED, never swallowed, and
    the rest still speak (W red team round 2: a broken w_cost.py used to
    silence the crash, follow-through, cost and review lines together)."""
    out, problems = [], []
    mode = "enforce"

    def part(name, fn):
        try:
            got = fn()
        except Exception as exc:                              # noqa: BLE001
            got = [f"W start-up readout: the {name} part failed ({type(exc).__name__}: "
                   f"{str(exc)[:120]}). Claude fixes it."]
            problems.append(name)
        out.extend(got or [])
        return got

    ft_state: dict = {}

    def mode_lines():
        nonlocal mode
        mode, note = read_mode()
        if note:
            problems.append("mode")           # a garbled switch file
        got = []
        if mode != "enforce":
            got.append("W follow-up gates are in LOG mode: the Checked trigger is recorded but "
                       "does not refuse. The follow-up after a W agent run, unbacked overrules and "
                       "the grade-filing check still refuse.")
        return got + ([note] if note else [])

    def cost_lines():
        import w_cost
        w_cost.ensure_yesterday_in_background(today)
        return [w_cost.line(today=today)]
    part("mode", mode_lines)
    problems += ["heartbeat"] if part("gate health", lambda: heartbeat_lines(today)) else []
    part("follow-through", lambda: follow_through_lines(today, ft_state))
    if ft_state.get("never"):
        problems.append("follow-through")
    part("cost", cost_lines)
    problems += ["queue"] if part("queue", queue_lines) else []
    part("review", lambda: review_lines(today, healthy=not problems and mode == "enforce"))
    return out


def _age_s(ts, now: "_dt.datetime | None" = None) -> float:
    try:
        then = _dt.datetime.strptime(_ts(ts), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return 0.0
    return ((now or _dt.datetime.now(_dt.timezone.utc)) - then).total_seconds()


def queue_rows(path: str) -> list[dict]:
    """A queue's real rows, with any marks a flush left in `*.marks` applied
    (skyne scripts/w_queue.py writes them when it cannot rewrite the queue)."""
    marks = {m["key"]: m for m in read_jsonl(path + ".marks") if m.get("key")}
    rows = []
    for r in read_jsonl(path):
        if r.get("test"):
            continue
        m = marks.get(r.get("key"))
        if m and (not r.get("flushed_in")
                  or str(m.get("flushed_utc") or "") > str(r.get("flushed_utc") or "")):
            # a re-send whose rewrite failed: the row still names the dead PR (round 3)
            r = dict(r, flushed_in=m.get("flushed_in"), flushed_utc=m.get("flushed_utc"))
        rows.append(r)
    return rows


def gh_pr_state(url: str) -> str | None:
    """OPEN / CLOSED / MERGED for a PR url; None if gh cannot say (best effort)."""
    import subprocess
    if "/pull/" not in str(url):
        return None
    try:
        r = subprocess.run(["gh", "pr", "view", str(url), "--json", "state", "-q", ".state"],
                           capture_output=True, text=True, timeout=8, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def queue_lines(hours: int = 24, now: "_dt.datetime | None" = None, pr_state=None) -> list[str]:
    """Grades and rounds that are NOT safely in Skyne's record yet: waiting on
    this PC, stuck in a save PR nobody merged, or damaged lines set aside.
    Saving them is Claude's job (skyne scripts/wince_grades.py flush and
    redteam_rounds.py flush, then merge the PR); a flush re-sends rows whose PR
    was closed unmerged."""
    out = []
    for path, label in ((grades_queue_path(), "Wince grades"), (rounds_queue_path(), "red-team rounds")):
        rows = queue_rows(path)
        waiting = [r for r in rows if not r.get("flushed_in")]
        if waiting and max(_age_s(r.get("queued_utc"), now) for r in waiting) > hours * 3600:
            oldest = min(_ts(r.get("queued_utc")) or "9999" for r in waiting)
            out.append(f"{len(waiting)} {label} are waiting on this PC to be saved to Skyne's record "
                       f"(oldest {oldest[:10]}). Nothing for you to do: Claude saves them.")
        stuck = [r for r in rows if r.get("flushed_in")
                 and _age_s(r.get("flushed_utc") or r.get("queued_utc"), now) > hours * 3600]
        groups: dict = {"OPEN": [], "CLOSED": [], None: []}
        for url in sorted({str(r["flushed_in"]) for r in stuck}):
            st = (pr_state or gh_pr_state)(url)
            if st == "MERGED":
                continue          # merged: the next save drops them, or re-sends any it missed
            groups[st if st in ("OPEN", "CLOSED") else None].append(
                (url, sum(1 for r in stuck if str(r["flushed_in"]) == url)))

        def nums(g):
            return ", ".join("#" + u.rstrip("/").rsplit("/", 1)[-1] for u, _ in g)
        for st, say in (("OPEN", "were sent to be saved more than a day ago, but the pull request "
                                 "is still waiting to be merged ({}). Claude merges it."),
                        ("CLOSED", "were in a pull request that was closed without being merged "
                                   "({}). Claude sends them again."),
                        (None, "were sent to be saved more than a day ago, and whether that pull "
                               "request was merged could not be checked ({}). Claude checks.")):
            if groups[st]:
                out.append(f"{sum(n for _, n in groups[st])} {label} " + say.format(nums(groups[st])))
        try:
            with open(path + ".broken", encoding="utf-8", errors="replace") as f:
                n = sum(1 for line in f if line.strip())
        except OSError:
            n = 0
        if n:
            out.append(f"{n} damaged {label} line(s) were set aside in {path}.broken and are not "
                       f"counted anywhere. Claude reads them and files them again.")
    return out


def crash_seen_path() -> str:
    return _p("SKYNE_W_CRASH_SEEN", "w-follow-crash-seen")


def heartbeat_lines(today: str | None = None) -> list[str]:
    """Speaks only when a gate is broken: one that did not run, or one that
    crashed. There is NO forced-pass alarm: Garrett picked "No alarm, review at
    day 14" (R22), and the alarm that was here counted refusals as passes (W red
    team round 1, 2026-11-20). The cost line is the standing readout; the
    follow-through line says how many refusals went out unchecked. Crashes are
    named once, in the first start-up after them (today's included, and any on a
    day with no chat), then remembered in w-follow-crash-seen."""
    rows = [r for r in read_jsonl(log_path()) if not r.get("test")]
    if not rows or not os.path.exists(golive_path()):
        return []                                # not live yet: nothing to watch
    out = []
    now = _dt.datetime.now(_dt.timezone.utc)
    cutoff = (now - _dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    active = _recent_activity(now)
    for gate in ("wince", "wren"):
        if active and not any(r.get("gate") == gate and str(r.get("utc")) >= cutoff for r in rows):
            out.append(f"{gate}_gate did not run: no w-follow.jsonl row in 24 hours while chats "
                       f"were active. The gate may not be delivered; check hook delivery.")
    try:
        with open(crash_seen_path(), encoding="utf-8") as f:
            seen = f.read().strip()
    except OSError:
        seen = ""
    errs = [r for r in rows if r.get("action") == "error" and str(r.get("utc") or "") > seen]
    if errs:
        gates = sorted({str(r.get("gate")) for r in errs})
        out.append(f"{len(errs)} Wince/Wren gate crash(es) since "
                   f"{'the last start-up that reported one' if seen else 'the trial began'} "
                   f"({', '.join(gates)}; last {str(errs[-1].get('utc'))[:16]}Z: "
                   f"{errs[-1].get('error', '?')}). While a gate crashes it lets every reply through. "
                   f"Tell Garrett in one line and fix it.")
        # Only a chat Garrett is in marks it reported: an unattended run (the 6-hourly
        # SDK ping on this PC) has nobody to tell (W red team round 3).
        if os.environ.get("CLAUDE_CODE_SESSION_ATTENDED") == "1":
            try:
                with open(crash_seen_path(), "w", encoding="utf-8") as f:
                    f.write(max(str(r.get("utc") or "") for r in errs))
            except OSError:
                pass
    # The label-share watch was cut 2026-11-19: it guarded the label trigger, which is retired.
    return out


FOLLOW_WINDOW_S = 2 * 3600     # an owed run that finished within 2 h of the release counts as done late


def main_register_rows() -> list[dict]:
    """Grade and round rows on Skyne's origin/main (best effort, short timeouts):
    a filing that a flush already moved off this PC still counts."""
    import subprocess
    # both: SKYNE_DIR on this PC names an old checkout whose origin/main can lag
    roots = dict.fromkeys(x for x in (os.path.join(os.path.expanduser("~"), "claude-audit"),
                                      os.environ.get("SKYNE_DIR")) if x and os.path.isdir(x))
    out = []
    for root in roots:
        for rel, key in (("data/wince-grades.json", "grades"), ("data/redteam-rounds.json", "rounds")):
            try:
                r = subprocess.run(["git", "-C", root, "show", f"origin/main:{rel}"], capture_output=True,
                                   text=True, encoding="utf-8", timeout=4, stdin=subprocess.DEVNULL)
                if r.returncode == 0:
                    out += json.loads(r.stdout).get(key, [])
            except (OSError, ValueError, subprocess.SubprocessError):
                continue
    return out


def follow_through(day: str, rows: list[dict] | None = None, runs: list[dict] | None = None,
                   grades: list[dict] | None = None) -> dict:
    """For one Eastern day, per REFUSED REPLY that went out anyway on the second
    try (both gates' `released` rows for one reply are one reply): was it
    followed, within FOLLOW_WINDOW_S and in the same session, by every owed
    agent run (w_ran's log) and, if a filing was owed, by a filing (both queues
    plus the registers on main)? {released, followed, unfollowed}.
    Not seen: WHICH work a run or filing was about. A same-session run in the
    window counts even if it reviewed something else (W red team round 2)."""
    from w_cost import et_day
    import datetime as dt
    rows = [r for r in (read_jsonl(log_path()) if rows is None else rows) if not r.get("test")]
    if runs is None:
        from w_ran import log_path as runs_path
        runs = read_jsonl(runs_path())
    if grades is None:
        grades = (read_jsonl(grades_queue_path()) + read_jsonl(rounds_queue_path())
                  + main_register_rows())

    def t(x):
        try:
            return dt.datetime.strptime(str(x)[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
        except ValueError:
            return None
    rel = sorted(((r.get("session_id"), t(r.get("utc")), r) for r in rows
                  if r.get("action") == "released" and et_day(str(r.get("utc"))) == day
                  and t(r.get("utc")) is not None), key=lambda x: (str(x[0]), x[1]))
    replies = []                    # [session, first time, gates owing a run, filing owed]
    for sess, at, r in rel:
        trig = set(r.get("triggers") or [])
        if replies and replies[-1][0] == sess and at - replies[-1][1] <= 60:
            rep = replies[-1]
        else:
            rep = [sess, at, set(), False]
            replies.append(rep)
        if trig - {"unfiled"} or not trig:
            rep[2].add(r.get("gate"))
        if "unfiled" in trig:
            rep[3] = True
    out = {"released": len(replies), "followed": 0, "late": 0, "never": 0}
    for sess, at, gates, filing in replies:
        def done_by(hi):
            def within(x):
                return x is not None and at <= x <= hi
            ran = all(any(x.get("event") == "stop" and x.get("w") == g and x.get("session_id") == sess
                          and within(t(x.get("utc"))) for x in runs) for g in gates)
            filed = not filing or any(g.get("session") == sess
                                      and within(t(g.get("queued_utc") or g.get("filed_utc")))
                                      for g in grades)
            return ran and filed
        out["followed" if done_by(at + FOLLOW_WINDOW_S) else "late" if done_by(float("inf"))
            else "never"] += 1
    out["unfollowed"] = out["late"] + out["never"]
    return out


def follow_through_lines(today: str | None = None, state: dict | None = None) -> list[str]:
    """One plain line, the point first: of yesterday's refused replies that went
    out anyway, how many NEVER got the owed Wince/Wren run or filing, then how
    many got it within the 2-hour window and how many later (W red team round 3:
    "36 never got it" counted 29 that came late). Silent on a day with no
    releases. `state` receives the counts, for the status line."""
    from w_cost import et_today, prev_day
    yday = prev_day(today or et_today())
    ft = follow_through(yday)
    if state is not None:
        state.update(ft)
    n = ft["released"]
    if not n:
        return []
    return [f"W follow-through, {yday}: {ft['never']} of {n} refused repl{'y' if n == 1 else 'ies'} "
            f"never got the owed Wince/Wren run or grade filing. {ft['followed']} got it within "
            f"2 hours, {ft['late']} later."]


def _recent_activity(now) -> bool:
    """Was any chat on this PC written to in the last 24 h? (proxy for 'the gates had a chance')"""
    root = os.environ.get("SKYNE_PROJECTS_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude", "projects")
    cutoff = now.timestamp() - 24 * 3600
    try:
        for d in os.scandir(root):
            if d.is_dir():
                for f in os.scandir(d.path):
                    if f.name.endswith(".jsonl") and f.stat().st_mtime > cutoff:
                        return True
    except OSError:
        pass
    return False


def review_lines(today: str | None = None, healthy: bool = False) -> list[str]:
    """The day-14 review, a real dated trigger. Before the date, one plain
    status line when nothing else is wrong (`healthy`), counting down to it."""
    try:
        with open(golive_path(), encoding="utf-8") as f:
            g = json.load(f)
    except (OSError, ValueError):
        return []
    from w_cost import et_today
    today = today or et_today()
    if g.get("reviewed"):
        return []
    due = g.get("review_on", "9999-99-99")
    if today < due:
        try:
            d = _dt.date.fromisoformat(due)
            left = (d - _dt.date.fromisoformat(today)).days
            when = f"{d.strftime('%b')} {d.day} (in {left} day{'s' if left != 1 else ''})"
        except ValueError:
            when = due
        state = ("running, nothing broken" if healthy else
                 "running, with a problem named above that Claude deals with")
        return [f"W helpers: {state}. Their day-14 review is due {when}: "
                f"Claude brings you the numbers then."]
    return [f"DAY-14 REVIEW DUE: the W follow-up gates went live on {g['go_live']}. "
            f"Run `python3 {os.path.join(HERE, 'w_cost.py')} review` and bring Garrett the real numbers "
            f"(runs a day, share of his tokens, Max weekly % trend), then ask: keep Checked-only as is / "
            f"Wince only at Checked (no Wren) / turn the gates off. After he answers, run it with `review --done`."]


# -------------------------------------------------------------------- self-test

def _asst(ts, *blocks):
    return {"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "content": list(blocks)}}


def self_test() -> int:
    import tempfile
    res = []

    def check(ok, what):
        res.append(bool(ok))
        print(("  ok    " if ok else "  FAIL  ") + what)

    # ---- the switch, all three encodings the PC can produce, and garbage
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "w-follow-mode")

        def put(raw):
            with open(p, "wb") as f:
                f.write(raw)
            return read_mode(p)
        check(read_mode(os.path.join(d, "nope")) == ("enforce", ""), "missing file enforces silently")
        check(put(b"log") == ("log", "") and put(b"  LOG\r\n") == ("log", ""),
              "plain 'log' (any case, whitespace, CRLF) logs")
        check(put(b"\xef\xbb\xbflog\r\n") == ("log", ""), "UTF-8 with a BOM (Out-File) logs")
        check(put("log\r\n".encode("utf-16")) == ("log", ""), "UTF-16 LE with a BOM (PowerShell '>') logs")
        check(put(b"\xfe\xff" + "log".encode("utf-16-be")) == ("log", ""), "UTF-16 BE with a BOM logs")
        check(put("log".encode("utf-16-le")) == ("log", ""), "UTF-16 with no BOM (NUL-interleaved) logs")
        check(put(b"enforce") == ("enforce", ""), "'enforce' enforces with no note")
        m, note = put(b"banana")
        check(m == "enforce" and "banana" in note and "not 'enforce' or 'log'" in note,
              "an unrecognized value enforces AND says so")
        m, note = put(b"")
        check(m == "enforce" and "(empty)" in note, "an empty file enforces and says so")
        m, note = put(b"\xff\xfe\x00\xd8\x00")
        check(m == "enforce" and note, "undecodable garbage enforces and says so")

    # ---- publish detection, with the real tool_use shapes copied from transcripts
    art_pub = {"file_path": "C:\\x\\companion.html", "icon": "compass", "description": "d"}
    check(classify_tool("Artifact", art_pub) == "publish", "an Artifact publish (action omitted) is a publish")
    check(classify_tool("Artifact", dict(art_pub, action="publish")) == "publish", "action=publish is a publish")
    check(classify_tool("Artifact", dict(art_pub, asset=True, url="u")) == "",
          "an asset upload is not a publish")
    check(classify_tool("Artifact", {"action": "list"}) == "" and classify_tool("Artifact", {"action": "read", "url": "u"}) == ""
          and classify_tool("Artifact", {"action": "delete", "url": "u"}) == "",
          "list / read / delete are not publishes")
    fig = "mcp__a2e5608f-73d1-4432-84e6-22b3701e89d8__"
    check(classify_tool(fig + "generate_diagram", {}) == "publish" and classify_tool(fig + "use_figma", {}) == "publish",
          "Figma generate_diagram and use_figma are publishes (by server id)")
    check(classify_tool(fig + "get_screenshot", {}) == "" and classify_tool(fig + "add_code_connect_map", {}) == "",
          "a Figma read and an excluded tool are not publishes")
    check(classify_tool(fig + "brand_new_tool", {}) == "figma-unknown",
          "a Figma tool not in the snapshot is flagged, not silently ignored")
    check(classify_tool("mcp__plugin_design_figma__use_figma", {}) == "publish",
          "a Figma server matched by NAME (plugin:design:figma) counts too")
    check(classify_tool("mcp__other__generate_diagram", {}) == "" and classify_tool("Bash", {}) == "",
          "a same-named tool on another server, and a shell, are not publishes")

    # ---- turn facts
    t = "2026-11-17T15:00:%02d.000Z"
    boundary = {"type": "user", "timestamp": t % 0, "message": {"content": "go"}}
    ent = [boundary,
           _asst(t % 1, {"type": "text", "text": "Wistin: building it."}),
           _asst(t % 2, {"type": "tool_use", "id": "t1", "name": "Write", "input": {"file_path": "a.py"}}),
           _asst(t % 3, {"type": "tool_use", "id": "t2", "name": "Artifact", "input": art_pub}),
           _asst(t % 4, {"type": "tool_use", "id": "t3", "name": "Agent", "input": {
               "subagent_type": "wince", "prompt": "[red-team lens 4: loop-9] grade it"}}),
           {"type": "user", "timestamp": t % 5, "toolUseResult": {"isAsync": True, "status": "async_launched",
            "agentId": "aaa111"}, "message": {"content": [{"type": "tool_result", "tool_use_id": "t3x",
            "content": [{"type": "text", "text": "Async agent launched successfully."}]}]}},
           ]
    ent[5]["message"]["content"][0]["tool_use_id"] = "t3"
    f = turn_facts(ent, 0)
    check(f["labels"] == {"Wistin"} and f["writes"] == [t[:-6] % 2 if False else "2026-11-17T15:00:02"]
          and len(f["publishes"]) == 1 and last_work_ts(f) == "2026-11-17T15:00:03",
          "turn facts: label, last write, publish and the last-work time")
    check(f["lens4_by_agent"] == {"aaa111": "loop-9"},
          "a tagged lens-4 Agent call joins to its agentId through toolUseResult")
    ent2 = [boundary, _asst(t % 1, {"type": "text", "text": "Claude: just answering."})]
    check(turn_facts(ent2, 0)["labels"] == set(), "a Claude: label is not a W label")
    ent3 = [boundary, _asst(t % 1, {"type": "text", "text": "Wince: my own review."})]
    check(turn_facts(ent3, 0)["labels"] == {"Wince"}, "a Wince: label is seen (the gate decides it never satisfies)")
    side = dict(ent[1], isSidechain=True)
    check(turn_facts([boundary, side], 0)["labels"] == set(), "a subagent's sidechain text is not the main loop's label")

    # ---- filings: per finish, by content
    with tempfile.TemporaryDirectory() as d:
        os.environ["SKYNE_GRADES_QUEUE"] = os.path.join(d, "g.jsonl")
        os.environ["SKYNE_ROUNDS_QUEUE"] = os.path.join(d, "r.jsonl")

        def app(path, row):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
        app(os.environ["SKYNE_GRADES_QUEUE"], {"session": "S", "queued_utc": "2026-11-17T15:10:00Z"})
        app(os.environ["SKYNE_GRADES_QUEUE"], {"session": "OTHER", "queued_utc": "2026-11-17T15:10:01Z"})
        app(os.environ["SKYNE_ROUNDS_QUEUE"], {"session": "S", "loop": "L9", "queued_utc": "2026-11-17T15:20:00Z"})
        fl = filings("S")
        check(fl["grades"] == ["2026-11-17T15:10:00"] and fl["rounds"] == {"L9": ["2026-11-17T15:20:00"]},
              "filings are matched on THIS session id only (another chat's row never counts)")
        runs = [{"finish": "2026-11-17T15:05:00", "loop": None}, {"finish": "2026-11-17T15:06:00", "loop": None}]
        check(len(unfiled_runs(runs, fl)) == 1,
              "two Wince finishes and one filing: one is still owed (per-finish accounting)")
        check(unfiled_runs([{"finish": "2026-11-17T15:11:00", "loop": None}], fl)
              == [{"finish": "2026-11-17T15:11:00", "loop": None}],
              "a filing from BEFORE the Wince finish does not cover it")
        check(unfiled_runs([{"finish": "2026-11-17T15:15:00", "loop": "L9"}], fl) == [],
              "a tagged lens-4 run is satisfied by a rounds row for its loop")
        check(unfiled_runs([{"finish": "2026-11-17T15:05:00", "loop": "L9"}], dict(fl, rounds={})) == [],
              "PLANTED: a tagged lens-4 run IS satisfied by its grade row (the round is filed only "
              "when all four reviewers are in; W red team round 2)")
        check(len(unfiled_runs([{"finish": "2026-11-17T15:30:00", "loop": "L9"}], fl)) == 1,
              "a tagged lens-4 run with no filing after it is still owed")
        check(unfiled_runs(runs, fl, escape_ts="2026-11-17T15:06:30") == [],
              "'no grade to file:' said after both finishes accounts for them")
        # PLANTED (W red team round 2): one grade seen in the queue, on main and in a
        # worktree copy is ONE filing, so two finishes still owe one.
        row = {"session": "S2", "key": "k1", "subject": "x", "pass": 1,
               "queued_utc": "2026-11-17T16:00:00Z", "filed_utc": "2026-11-17T16:00:00Z"}
        app(os.environ["SKYNE_GRADES_QUEUE"], row)
        regs = []
        for n in range(3):
            rp = os.path.join(d, "reg%d.json" % n)
            with open(rp, "w", encoding="utf-8") as fh:
                json.dump({"grades": [row, {"session": "S2", "subject": "y", "pass": 1,
                                            "filed_utc": "2026-11-17T16:01:00Z"}]}, fh)
            regs.append(rp)
        fl2 = filings("S2", regs)
        two = [{"finish": "2026-11-17T15:59:00", "loop": None}] * 3
        check(len(fl2["grades"]) == 2 and len(unfiled_runs(two, fl2)) == 1,
              "PLANTED: the same grade in the queue and three register copies counts once "
              "(a keyed row by key, an unkeyed one by subject+pass+time): 3 finishes, 2 filings, 1 owed")
        # the readout: waiting, stuck in an unmerged PR, damaged lines, pending marks
        gq = os.environ["SKYNE_GRADES_QUEUE"]
        with open(gq, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": "w1", "queued_utc": "2026-11-10T00:00:00Z"}) + "\n")
            fh.write(json.dumps({"key": "w2", "queued_utc": "2026-11-10T00:00:00Z"}) + "\n")
            fh.write(json.dumps({"key": "s1", "queued_utc": "2026-11-10T00:00:00Z",
                                 "flushed_in": "https://github.com/x/y/pull/972"}) + "\n")
            fh.write(json.dumps({"key": "s2", "queued_utc": "2026-11-19T00:00:00Z",
                                 "flushed_in": "https://github.com/x/y/pull/1069",
                                 "flushed_utc": "2026-11-19T23:00:00Z"}) + "\n")
        with open(gq + ".marks", "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": "w2", "flushed_in": "https://github.com/x/y/pull/1070",
                                 "flushed_utc": "2026-11-19T23:30:00Z"}) + "\n")
        with open(gq + ".broken", "w", encoding="utf-8") as fh:
            fh.write('{"half a line\n98f6"\n')
        with open(gq, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": "m1", "queued_utc": "2026-11-10T00:00:00Z",
                                 "flushed_in": "https://github.com/x/y/pull/980"}) + "\n")
            fh.write(json.dumps({"key": "c1", "queued_utc": "2026-11-10T00:00:00Z",
                                 "flushed_in": "https://github.com/x/y/pull/981"}) + "\n")
            fh.write(json.dumps({"key": "r1", "queued_utc": "2026-11-10T00:00:00Z",
                                 "flushed_in": "https://github.com/x/y/pull/1",
                                 "flushed_utc": "2026-11-10T00:00:00Z"}) + "\n")
        with open(gq + ".marks", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": "r1", "flushed_in": "https://github.com/x/y/pull/1071",
                                 "flushed_utc": "2026-11-20T11:00:00Z"}) + "\n")
        states = {"972": "OPEN", "980": "MERGED", "981": "CLOSED", "1": "CLOSED"}
        ql = queue_lines(now=_dt.datetime(2026, 11, 20, 12, tzinfo=_dt.timezone.utc),
                         pr_state=lambda u: states.get(u.rsplit("/", 1)[-1]))
        check(not any("#980" in x for x in ql) and any("closed without being merged" in x and "#981" in x
                                                        for x in ql),
              "PLANTED: a merged PR is not called 'never merged'; a closed one is named as closed: "
              + repr(ql))
        check(not any("#1," in x or "#1)" in x for x in ql),
              "PLANTED: a re-send's newer mark beats the dead PR still in the row (#1 is not named)")
        check(any(x.startswith("1 Wince grades are waiting") for x in ql),
              "PLANTED: a row waiting on this PC is named; one whose mark sits in .marks is not "
              "waiting: " + repr(ql))
        check(any(x.startswith("1 Wince grades were sent") and "#972" in x and "#1069" not in x
                  for x in ql),
              "PLANTED: a row sent in a PR more than a day ago is named with its PR; a fresh one is not")
        check(any(x.startswith("2 damaged Wince grades") for x in ql),
              "PLANTED: damaged lines set aside in .broken are counted in the readout")
        check(not any("/handoff" in x or "flush" in x.lower() for x in ql),
              "the queue lines carry no /handoff or flush jargon")
        for k in ("SKYNE_GRADES_QUEUE", "SKYNE_ROUNDS_QUEUE"):
            os.environ.pop(k, None)

    # ---- go-live, review, cloud
    with tempfile.TemporaryDirectory() as d:
        gp = os.path.join(d, "golive.json")
        os.environ["SKYNE_W_FOLLOW_GOLIVE"] = gp
        check(review_lines("2030-01-01") == [], "no go-live file: the review says nothing")
        record_golive(gp, "2026-11-18")
        record_golive(gp, "2026-12-30")
        g = json.load(open(gp))
        check(g["go_live"] == "2026-11-18" and g["review_on"] == "2026-12-02",
              "go-live is recorded once, review date = +14 days")
        check(review_lines("2026-12-01") == ["W helpers: running, with a problem named above that Claude "
                                             "deals with. Their day-14 review is due Dec 2 (in 1 day): "
                                             "Claude brings you the numbers then."],
              "PLANTED: when something is wrong the status line never says 'nothing broken'")
        check(review_lines("2026-11-20", healthy=True)
              == ["W helpers: running, nothing broken. Their day-14 review is due Dec 2 (in 12 days): "
                  "Claude brings you the numbers then."],
              "PLANTED: with nothing wrong, one plain status line counts down to the review")
        check(not any("R19" in x or "R22" in x for x in review_lines("2026-12-03")),
              "the review line carries no R numbers")
        check(len(review_lines("2026-12-02")) == 1 and "DAY-14 REVIEW DUE" in review_lines("2026-12-05")[0],
              "the review line appears on the date and stays until it is done")
        g["reviewed"] = True
        json.dump(g, open(gp, "w"))
        check(review_lines("2026-12-05") == [], "after the review is marked done it is silent")
        lp = os.path.join(d, "wf.jsonl")
        os.environ["SKYNE_W_FOLLOW_LOG"] = lp
        with open(lp, "w", encoding="utf-8") as fh:
            for i in range(30):
                fh.write(json.dumps({"gate": "wince", "action": "refused", "utc": "2026-11-21T20:00:%02dZ" % i,
                                     "triggers": ["checked"]}) + "\n")
            fh.write(json.dumps({"gate": "wince", "action": "allowed", "utc": "2026-11-21T21:00:00Z",
                                 "undated_checked": ["CO-2"]}) + "\n")
        hb = heartbeat_lines("2026-11-22")
        check(not any("forced" in x or "re-ask" in x or "worth its cost" in x for x in hb),
              "30 refusals in a day raise NO mid-trial alarm (R22: 'No alarm, review at day 14')")
        check(not any("CO-2" in x for x in hb),
              "the gate-side undated-Checked line is gone (the nightly reads stored rows instead)")
        os.environ["SKYNE_W_CRASH_SEEN"] = os.path.join(d, "crash-seen")
        os.environ["SKYNE_PROJECTS_DIR"] = os.path.join(d, "no-projects")
        with open(lp, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"gate": "wince", "action": "error", "utc": "2026-11-18T22:00:00Z",
                                 "error": "KeyError: old"}) + "\n")
        was_att = os.environ.get("CLAUDE_CODE_SESSION_ATTENDED")
        os.environ["CLAUDE_CODE_SESSION_ATTENDED"] = "0"
        hb0 = heartbeat_lines("2026-11-22")
        check(any("KeyError: old" in x for x in hb0)
              and not os.path.exists(os.environ["SKYNE_W_CRASH_SEEN"]),
              "PLANTED: an unattended start-up (the 6-hourly ping) names the crash but does not mark "
              "it reported, so Garrett's next chat still hears it")
        os.environ["CLAUDE_CODE_SESSION_ATTENDED"] = "1"
        hb1 = heartbeat_lines("2026-11-22")
        check(any("gate crash" in x and "KeyError: old" in x for x in hb1),
              "PLANTED: a crash followed by days with no start-up is still named (it used to be "
              "named only on the next day)")
        log_error("wren", ValueError("boom"), lp)        # a crash TODAY
        hb2 = heartbeat_lines()
        check(any("1 Wince/Wren gate crash" in x and "boom" in x for x in hb2)
              and not any("KeyError: old" in x for x in hb2),
              "PLANTED: today's crash is named today; one already reported is not repeated")
        check(read_jsonl(lp)[-1]["action"] == "error" and "boom" in read_jsonl(lp)[-1]["error"],
              "log_error writes an error row with the exception")
        # PLANTED: a w_cost that cannot be imported. The crash line still speaks, and the
        # broken part is NAMED (before, one ImportError silenced four lines at once).
        with open(lp, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"gate": "wince", "action": "error", "utc": "2099-01-01T00:00:00Z",
                                 "error": "RuntimeError: later"}) + "\n")
        real_cost = sys.modules.get("w_cost")
        sys.modules["w_cost"] = None          # `import w_cost` now raises ImportError
        try:
            try:
                import w_cost as _wc  # noqa: F401
                broke = False
            except ImportError:
                broke = True
            sl = session_lines("2026-11-22")
        finally:
            if real_cost is not None:
                sys.modules["w_cost"] = real_cost
            else:
                sys.modules.pop("w_cost", None)
        check(broke and any("RuntimeError: later" in x for x in sl)
              and any("the cost part failed" in x for x in sl)
              and any("the follow-through part failed" in x for x in sl),
              "PLANTED: with w_cost.py unimportable, the crash line still speaks and each part "
              "that failed is named: " + repr(sl)[:300])
        os.environ.pop("SKYNE_W_CRASH_SEEN", None)
        os.environ.pop("SKYNE_PROJECTS_DIR", None)
        if was_att is None:
            os.environ.pop("CLAUDE_CODE_SESSION_ATTENDED", None)
        else:
            os.environ["CLAUDE_CODE_SESSION_ATTENDED"] = was_att
        # the status line, with each part stubbed (W red team round 3)
        g2 = dict(g, reviewed=False)
        json.dump(g2, open(gp, "w"))
        G = globals()
        saved_parts = {k: G[k] for k in ("heartbeat_lines", "follow_through_lines", "queue_lines", "read_mode")}
        saved_cost = sys.modules.get("w_cost")
        import types as _types
        sys.modules["w_cost"] = _types.SimpleNamespace(ensure_yesterday_in_background=lambda t: None,
                                                       line=lambda today=None: "cost",
                                                       et_today=lambda: "2026-11-20")

        def status(hb=(), never=0, note=""):
            G["heartbeat_lines"] = lambda t=None: list(hb)
            G["follow_through_lines"] = lambda t=None, st=None: (st.update(never=never) if st is not None
                                                                 else None) or ["ft"]
            G["queue_lines"] = lambda *a, **k: []
            G["read_mode"] = lambda: ("enforce", note)
            return [x for x in session_lines("2026-11-20") if x.startswith("W helpers:")]
        try:
            ok_line = status()
            crash = status(hb=["1 Wince/Wren gate crash(es) since ..."])
            leak = status(never=3)
            garbled = status(note="w-follow-mode says 'banana'")
        finally:
            G.update(saved_parts)
            if saved_cost is not None:
                sys.modules["w_cost"] = saved_cost
            else:
                sys.modules.pop("w_cost", None)
        check(len(ok_line) == 1 and "nothing broken" in ok_line[0],
              "with every part clean the status line says nothing is broken")
        check(all(len(x) == 1 and "nothing broken" not in x[0] for x in (crash, leak, garbled)),
              "PLANTED: beside a crash line, a never-followed refusal, or a garbled switch, the status "
              "line does not say 'nothing broken': " + repr((crash, leak, garbled))[:300])
        # follow-through: released rows matched to what came after them
        rel = [{"gate": "wince", "action": "released", "session_id": "s1", "utc": "2026-11-21T20:00:00Z",
                "triggers": ["checked"]},
               {"gate": "wren", "action": "released", "session_id": "s1", "utc": "2026-11-21T20:00:00Z",
                "triggers": ["checked"]},
               {"gate": "wince", "action": "released", "session_id": "s2", "utc": "2026-11-21T21:00:00Z",
                "triggers": ["unfiled"]},
               {"gate": "wince", "action": "released", "session_id": "s3", "utc": "2026-11-21T21:00:00Z",
                "triggers": ["unfiled"]}]
        runs_ = [{"event": "stop", "w": "wince", "session_id": "s1", "utc": "2026-11-21T20:10:00Z"},
                 {"event": "stop", "w": "wren", "session_id": "s1", "utc": "2026-11-21T19:59:00Z"}]
        grades_ = [{"session": "s2", "queued_utc": "2026-11-21T21:05:00Z"}]
        ft = follow_through("2026-11-21", rel, runs_, grades_)
        check(ft == {"released": 3, "followed": 1, "late": 0, "never": 2, "unfollowed": 2},
              "PLANTED: one reply refused by BOTH gates is one reply (3 replies, not 4); it needs both "
              "runs, and its Wren run came BEFORE the release; s2 filed, s3 never did: " + repr(ft))
        late = [{"session": "s3", "queued_utc": "2026-11-22T01:30:00Z"}]
        main_row = [{"session": "s3", "filed_utc": "2026-11-21T21:10:00Z"}]
        fl = follow_through("2026-11-21", rel, runs_, grades_ + late)
        check(fl["followed"] == 1 and fl["late"] == 1 and fl["never"] == 1
              and follow_through("2026-11-21", rel, runs_, grades_ + main_row)["followed"] == 2,
              "PLANTED: a filing 4.5 hours later counts as LATE, not never; a row already on main "
              "(filed_utc, no queue row) counts")
        # W red team round 3: tests that could not fail
        other = [{"gate": "wince", "action": "released", "session_id": "s4", "utc": "2026-11-21T22:00:00Z",
                  "triggers": ["checked"]}]
        check(follow_through("2026-11-21", other,
                             [{"event": "stop", "w": "wince", "session_id": "elsewhere",
                               "utc": "2026-11-21T22:05:00Z"}], [])["never"] == 1,
              "PLANTED: a Wince run in ANOTHER chat is not this reply's follow-through")
        saved_mr = globals()["main_register_rows"]
        globals()["main_register_rows"] = lambda: [{"session": "s3", "filed_utc": "2026-11-21T21:10:00Z"}]
        os.environ["SKYNE_GRADES_QUEUE"] = os.path.join(d, "none-g.jsonl")
        os.environ["SKYNE_ROUNDS_QUEUE"] = os.path.join(d, "none-r.jsonl")
        try:
            via_main = follow_through("2026-11-21", rel[3:], [], None)
        finally:
            globals()["main_register_rows"] = saved_mr
            os.environ.pop("SKYNE_GRADES_QUEUE", None)
            os.environ.pop("SKYNE_ROUNDS_QUEUE", None)
        check(via_main["followed"] == 1,
              "PLANTED: with no grades given, the filings on Skyne's main are read: " + repr(via_main))
        line = None
        G2 = globals()
        saved_ft = G2["follow_through"]
        G2["follow_through"] = lambda day: {"released": 70, "followed": 34, "late": 29, "never": 7,
                                            "unfollowed": 36}
        try:
            line = follow_through_lines("2026-11-20")[0]
        finally:
            G2["follow_through"] = saved_ft
        check(line == "W follow-through, 2026-11-19: 7 of 70 refused replies never got the owed Wince/Wren "
                      "run or grade filing. 34 got it within 2 hours, 29 later.",
              "PLANTED: the line leads with the never-followed count and splits late from never: " + line)
        # 4g: a lock file being deleted (PermissionError) is waited out, not written past
        lp2 = os.path.join(d, "perm.jsonl")
        tries = {"n": 0}
        real_open = os.open

        def flaky(p, flags, *a):
            if str(p).endswith(".wlock"):
                tries["n"] += 1
                if tries["n"] == 1:
                    raise PermissionError(13, "pending delete")
            return real_open(p, flags, *a)
        os.open = flaky
        try:
            locked_append(lp2, '{"a": 1}')
        finally:
            os.open = real_open
        check(tries["n"] == 2 and read_jsonl(lp2) == [{"a": 1}] and not os.path.exists(lp2 + ".wlock"),
              "PLANTED: a PermissionError on the lock file is waited out and the lock is then taken")
        # torn lines: many writers at once leave whole lines
        import threading
        tp = os.path.join(d, "torn.jsonl")

        def burst(n):
            for i in range(40):
                log_row({"gate": "wince", "n": n, "i": i, "pad": "x" * 3000}, tp)
        ts = [threading.Thread(target=burst, args=(n,)) for n in range(4)]
        [x.start() for x in ts]
        [x.join() for x in ts]
        with open(tp, encoding="utf-8") as fh:
            raw = fh.read().splitlines()
        check(len(raw) == 160 and len(read_jsonl(tp)) == 160,
              "PLANTED: 160 log rows from 4 writers at once are all whole (the write lock)")
        os.environ.pop("SKYNE_W_FOLLOW_LOG", None)
        os.environ.pop("SKYNE_W_FOLLOW_GOLIVE", None)
    # a broken w_follow turns both gates off; the start-up block must say so (W red team round 1)
    import types
    import session_start
    real = sys.modules.get("w_follow")
    sys.modules["w_follow"] = types.SimpleNamespace(session_lines=lambda: 1 / 0)
    try:
        txt = session_start.follow_block()
    finally:
        if real is not None:
            sys.modules["w_follow"] = real
        else:
            sys.modules.pop("w_follow", None)
    check("failed to load" in txt and "ZeroDivisionError" in txt and "may be OFF" in txt,
          "PLANTED: a w_follow that fails to load is named in the start-up block, not swallowed")
    saved = os.environ.get("CLAUDE_CODE_REMOTE")
    os.environ["CLAUDE_CODE_REMOTE"] = "true"
    check(cloud_enforces() is False, "in the cloud the new triggers do not refuse (PC-only until confirmed)")
    os.environ.pop("CLAUDE_CODE_REMOTE", None)
    check(cloud_enforces() is True, "on this PC they may refuse")
    if saved is not None:
        os.environ["CLAUDE_CODE_REMOTE"] = saved

    print(f"w_follow self-test: {sum(res)}/{len(res)} passed")
    return 0 if all(res) else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else 0)
