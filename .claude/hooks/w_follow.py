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


def _checked_done(st) -> bool | None:
    """Checked done in a stage list? None when the list is not a board row."""
    if isinstance(st, list) and len(st) in CHECKED_AT:
        return st[CHECKED_AT[len(st)]] == "done"
    return None


def _board_writes(inp: dict) -> list[dict]:
    act = inp.get("action")
    if act in ("set", "update"):
        return [{"collection": inp.get("collection"), "doc_id": inp.get("doc_id"), "data": inp.get("data")}]
    if act == "batch":
        return [w for w in inp.get("writes") or [] if isinstance(w, dict) and w.get("op") in ("set", "update")]
    return []


def _is_features(col) -> bool:
    return str(col or "").split("/")[-1] == "features"


def _epoch(ts: str) -> float:
    try:
        return _dt.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=_dt.timezone.utc).timestamp()
    except ValueError:
        return 0.0


class CheckedWatch:
    """Remembers, across the whole session, each feature's Checked state as Claude
    last READ it (an ArtifactData read saved with out_dir: the file on disk, if it
    was written before the write being judged) or last WROTE it. A write fires
    when it turns Checked to done and the remembered state was not done, or is
    unknown (no read on record: a review is owed rather than skipped).
    Wince 2026-11-19: the first version's "frontier" rule missed rows with Built
    already done (CO-1, CO-4..7) and re-fired on rows re-sent at the frontier."""

    def __init__(self):
        self.known = {}          # doc_id -> bool (Checked done)
        self.read_dirs = []      # out_dir of each features read, in order

    def note_call(self, name, inp) -> None:
        if not str(name or "").endswith(BOARD_TOOL_SUFFIX) or not isinstance(inp, dict):
            return
        if inp.get("action") in ("get", "list", "query") and _is_features(inp.get("collection")) and inp.get("out_dir"):
            self.read_dirs.append(str(inp["out_dir"]))

    def _read_state(self, fid: str, ts: str):
        when = _epoch(ts)
        for d in reversed(self.read_dirs):
            fp = os.path.join(d, "features", fid + ".json")
            try:
                if when and os.path.getmtime(fp) > when + 1:
                    continue                      # re-read AFTER this write: not the before-state
                with open(fp, encoding="utf-8") as fh:
                    return _checked_done((json.load(fh) or {}).get("s"))
            except (OSError, ValueError):
                continue
        return None

    def marks(self, name, inp, ts: str = "") -> list:
        """Feature ids this call turns Checked to done. Also updates memory."""
        if not str(name or "").endswith(BOARD_TOOL_SUFFIX) or not isinstance(inp, dict):
            return []
        self.note_call(name, inp)
        out = []
        for w in _board_writes(inp):
            data = w.get("data")
            if not _is_features(w.get("collection")) or not isinstance(data, dict):
                continue
            fid = str(w.get("doc_id") or "?")
            now = _checked_done(data.get("s"))
            sd = data.get("stageDates")
            if now is None and isinstance(sd, dict) and sd.get("checked"):
                now = True
            if now is None:
                continue
            before = self.known.get(fid)
            if before is None:
                before = self._read_state(fid, ts)
            if now and before is not True:
                out.append(fid)
            self.known[fid] = now
        return out


def checked_marks(name, inp, watch: "CheckedWatch | None" = None, ts: str = "") -> list:
    """Feature ids this one call turns Checked to done (a fresh watch: nothing known)."""
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
    return "enforce", (f"w-follow-mode says {shown!r}, which is not 'enforce' or 'log': "
                       f"enforcing. Write the single word log (or enforce) to {path}.")


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


def log_row(row: dict, path: str | None = None) -> bool:
    path = path or log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(dict({"utc": now_utc()}, **row), sort_keys=True) + "\n")
        return True
    except OSError:
        return False


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


def filings(session: str, extra_registers: list[str] | None = None) -> dict:
    """Content-matched filings for THIS session: {'grades': [ts...], 'rounds': {loop: [ts...]}}.
    Sources: both local queues, plus any register files named (a register row
    counts through its `filed_utc`)."""
    grades, rounds = [], {}
    for r in _session_rows(read_jsonl(grades_queue_path()), session):
        t = _ts(r.get("queued_utc"))
        if t:
            grades.append(t)
    for r in _session_rows(read_jsonl(rounds_queue_path()), session):
        t = _ts(r.get("queued_utc"))
        if t:
            rounds.setdefault(str(r.get("loop")), []).append(t)
    for path in extra_registers or []:
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        for r in _session_rows(doc.get("grades", []), session):
            if _ts(r.get("filed_utc")):
                grades.append(_ts(r["filed_utc"]))
        for r in _session_rows(doc.get("rounds", []), session):
            if _ts(r.get("filed_utc")):
                rounds.setdefault(str(r.get("loop")), []).append(_ts(r["filed_utc"]))
    return {"grades": sorted(grades), "rounds": {k: sorted(v) for k, v in rounds.items()}}


def unfiled_runs(runs: list[dict], fil: dict, escape_ts: str = "") -> list[dict]:
    """Each Wince FINISH is accounted for separately and consumes ONE filing at
    or after it. A lens-4 run (tagged with its loop id) is satisfied only by a
    redteam_rounds row for that loop; any other run by a grade row."""
    grades = list(fil["grades"])
    rounds = {k: list(v) for k, v in fil["rounds"].items()}
    owed = []
    for run in sorted(runs, key=lambda r: r["finish"]):
        if escape_ts and run["finish"] <= escape_ts:
            continue                    # "no grade to file: <why>" said after it
        pool = rounds.get(run["loop"], []) if run.get("loop") else grades
        hit = next((i for i, t in enumerate(pool) if t >= run["finish"]), None)
        if hit is None:
            owed.append(run)
        else:
            pool.pop(hit)
    return owed


# ------------------------------------------------------------------ session lines

def session_lines(today: str | None = None) -> list[str]:
    """What SessionStart tells the session (the session relays it to Garrett)."""
    out = []
    try:
        mode, note = read_mode()
        if mode != "enforce":
            out.append("W follow-up gates are in LOG mode (~/.claude/skyne/w-follow-mode): "
                       "they record but refuse nothing.")
        if note:
            out.append(note)
    except Exception:                                         # noqa: BLE001
        pass
    try:
        out.extend(heartbeat_lines(today))
    except Exception:                                         # noqa: BLE001
        pass
    try:
        import w_cost
        w_cost.ensure_yesterday_in_background(today)
        out.append(w_cost.line(today=today))
    except Exception:                                         # noqa: BLE001
        pass
    try:
        out.extend(queue_lines())
        out.extend(review_lines(today))
    except Exception:                                         # noqa: BLE001
        pass
    return out


def queue_lines(hours: int = 24) -> list[str]:
    out = []
    for path, label in ((grades_queue_path(), "Wince grades"), (rounds_queue_path(), "red-team rounds")):
        rows = [r for r in read_jsonl(path) if not r.get("test")]
        if not rows:
            continue
        oldest = min(_ts(r.get("queued_utc")) or "9999" for r in rows)
        try:
            age = (_dt.datetime.now(_dt.timezone.utc) - _dt.datetime.strptime(
                oldest, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=_dt.timezone.utc)).total_seconds()
        except ValueError:
            continue
        if age > hours * 3600:
            out.append(f"{len(rows)} {label} queued since {oldest[:10]}: /handoff flushes them "
                       f"into a PR.")
    return out


BASELINE_LABEL_SHARE = 0.03          # DECISIONS R9: ~3% of replies carry a W label (unused since 2026-11-19; kept for old readers)
FORCED_PASSES_ALERT = 12             # R16/R19: forced passes a day that re-open the call


def heartbeat_lines(today: str | None = None) -> list[str]:
    """Speaks only when something is wrong: a gate that did not run, a label share
    under half its baseline over 7 days, or more forced passes in a day than R16
    allows. Quiet otherwise (the cost line is the standing readout)."""
    from w_cost import et_day, et_today, prev_day
    today = today or et_today()
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
    yday = prev_day(today)
    forced = sum(1 for r in rows if r.get("action") == "refused"
                 and et_day(str(r.get("utc"))) == yday)
    if forced > FORCED_PASSES_ALERT:
        out.append(f"{forced} forced Wince/Wren passes on {yday}, over R16's {FORCED_PASSES_ALERT} a day, "
                   f"with the triggers already narrowed to the Checked stage (RULED 2026-11-19): "
                   f"tell Garrett and ask whether Checked-only is still worth its cost.")
    # The label-share watch was cut 2026-11-19: it guarded the label trigger, which is retired.
    return out


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


def review_lines(today: str | None = None) -> list[str]:
    """R22: the day-14 review, a real dated trigger. Silent before the date."""
    try:
        with open(golive_path(), encoding="utf-8") as f:
            g = json.load(f)
    except (OSError, ValueError):
        return []
    from w_cost import et_today
    today = today or et_today()
    if g.get("reviewed") or today < g.get("review_on", "9999-99-99"):
        return []
    return [f"DAY-14 REVIEW DUE: the W follow-up gates went live on {g['go_live']} (R19/R22). "
            f"Run `python3 {os.path.join(HERE, 'w_cost.py')} review` and bring Garrett the real numbers "
            f"(runs a day, share of his tokens, Max weekly % trend), then ask: keep as is / publishes "
            f"only / labels only / one pass. After he answers, run it with `review --done`."]


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
        check(len(unfiled_runs([{"finish": "2026-11-17T15:05:00", "loop": "L9"}], dict(fl, rounds={}))) == 1,
              "a tagged lens-4 run is NOT satisfied by a plain grade row")
        check(unfiled_runs(runs, fl, escape_ts="2026-11-17T15:06:30") == [],
              "'no grade to file:' said after both finishes accounts for them")
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
        check(review_lines("2026-12-01") == [], "no alarm one day before the review")
        check(len(review_lines("2026-12-02")) == 1 and "DAY-14 REVIEW DUE" in review_lines("2026-12-05")[0],
              "the review line appears on the date and stays until it is done")
        g["reviewed"] = True
        json.dump(g, open(gp, "w"))
        check(review_lines("2026-12-05") == [], "after the review is marked done it is silent")
        os.environ.pop("SKYNE_W_FOLLOW_GOLIVE", None)
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
