"""Checks a chat reply for a relative-time word sitting next to a date that
does not actually match it.

WHY THIS EXISTS
---------------
House-rules 40, written 2026-09-14 the same hour it happened live: Claude told
Garrett that a capability "landed yesterday" when the file it was reading said
"Added 2026-09-14" -- the same date as that day's actual date. Both dates were
already in the reply and in the source; nothing compared them. Garrett's own
question, verbatim: "if I'd never caught the time thing is there any world it
ever gets flagged by you at any point? cause it should be." Before this file,
the honest answer was no -- `reply_gate.py` checked shape (closing block,
banned words, jargon), never whether a date claim was arithmetically true.

WHAT IT CHECKS
--------------
Every explicit date (YYYY-MM-DD) in the text, and whether a relative-time word
sitting close to it -- yesterday, today, tonight, this morning, earlier today,
"N days ago", "N days old" -- is consistent with `today`. "Yesterday
(2026-09-13)" is arithmetic; "yesterday (2026-09-14)" when today is 2026-09-14
is a claim that contradicts its own evidence.

WHAT IT DELIBERATELY DOES NOT CHECK
------------------------------------
A bare date with no relative word nearby (most dates in this estate -- report
filenames, commit references). A relative word with no date nearby -- there is
nothing to check it against, and guessing would be exactly the "a check that
fires on ordinary work gets deleted" failure house-rules 21 point 5 warns
about. It also only understands Garrett's own local date (Eastern,
house-rules 19) as `today` -- it cannot see what the writer intended by a
vaguer phrase like "recently" or "a while back", and does not try.

WHY IT WARNS THROUGH reply_gate.py RATHER THAN BEING ITS OWN HOOK
--------------------------------------------------------------------
This checks the REPLY TEXT, not a tool call -- the same thing `reply_gate.py`
already owns (jargon, stock phrases, the closing block). It plugs into that
gate as one more complaint rather than standing up a second Stop hook.

DUPLICATION, SAID OUT LOUD
---------------------------
`skyne/scripts/check_date_claims.py` carries the same logic as a CLI, for
scanning dated reports rather than live replies. This file cannot import it --
this plugin has to run standalone and skyne is private. So there are two
copies, same shape as `shell_shapes.py` beside `check_shell_shapes.py`
(house-rules 29) -- and the same fix: a golden corpus
(`date-claims-corpus.json`) both sides check themselves against, with a sha256
each side is frozen to, so the corpus moving on one side and not the other
fails that side's self-test rather than drifting silently.

Usage:
    python3 date_claims.py --check '<text>' [--today YYYY-MM-DD]
    python3 date_claims.py --self-test
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
from datetime import date, timedelta

MARKERS = [
    ("yesterday", re.compile(r"\byesterday\b(?!['’]s)", re.I), -1),
    ("today", re.compile(r"\btoday\b(?!['’]s)", re.I), 0),
    ("tonight", re.compile(r"\btonight\b(?!['’]s)", re.I), 0),
    ("this morning", re.compile(r"\bthis morning\b(?!['’]s)", re.I), 0),
    ("earlier today", re.compile(r"\bearlier today\b(?!['’]s)", re.I), 0),
]
DAYS_AGO = re.compile(r"\b(\d{1,3})\s+days?\s+ago\b", re.I)
DAYS_OLD = re.compile(r"\b(\d{1,3})\s+days?\s+old\b", re.I)
ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

PROXIMITY = 80  # characters either side of the ISO date, not the whole reply


def _real_today() -> date:
    """Garrett's local (Eastern) date -- house-rules 19, never the container's UTC."""
    try:
        from zoneinfo import ZoneInfo
        return date.today() if os.environ.get("SKYNE_TEST_TODAY") else \
            __import__("datetime").datetime.now(ZoneInfo("America/New_York")).date()
    except Exception:
        return date.today()


def _coerce_today(today):
    if today is None:
        return _real_today()
    if isinstance(today, str):
        return date.fromisoformat(today)
    return today


def scan(text: str, today=None) -> list:
    """Findings where a relative-time word near a date disagrees with `today`.

    Pure function of its arguments (no clock read unless `today` is None), so
    the self-test can hand it a fixed date the same way `evaluate()` in
    reply_gate.py stays a pure function of its inputs.
    """
    if not text:
        return []
    today = _coerce_today(today)
    findings = []
    seen = set()
    for m in ISO.finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            claimed = date(y, mo, d)
        except ValueError:
            continue
        lo, hi = max(0, m.start() - PROXIMITY), min(len(text), m.end() + PROXIMITY)
        window = text[lo:hi]

        for name, rx, offset in MARKERS:
            mm = rx.search(window)
            if not mm:
                continue
            expected = today + timedelta(days=offset)
            if claimed != expected:
                key = (name, claimed.isoformat())
                if key not in seen:
                    seen.add(key)
                    findings.append({
                        "shape": "relative-date-mismatch",
                        "marker": name,
                        "claimed": claimed.isoformat(),
                        "expected": expected.isoformat(),
                        "today": today.isoformat(),
                    })

        for mm in DAYS_AGO.finditer(window):
            n = int(mm.group(1))
            expected = today - timedelta(days=n)
            if claimed != expected:
                key = ("%s days ago" % n, claimed.isoformat())
                if key not in seen:
                    seen.add(key)
                    findings.append({
                        "shape": "relative-date-mismatch",
                        "marker": "%s days ago" % n,
                        "claimed": claimed.isoformat(),
                        "expected": expected.isoformat(),
                        "today": today.isoformat(),
                    })

        for mm in DAYS_OLD.finditer(window):
            n = int(mm.group(1))
            expected = today - timedelta(days=n)
            if claimed != expected:
                key = ("%s days old" % n, claimed.isoformat())
                if key not in seen:
                    seen.add(key)
                    findings.append({
                        "shape": "relative-date-mismatch",
                        "marker": "%s days old" % n,
                        "claimed": claimed.isoformat(),
                        "expected": expected.isoformat(),
                        "today": today.isoformat(),
                    })
    return findings


def message(findings) -> str:
    parts = []
    for f in findings[:3]:
        parts.append(
            "'%s' next to %s doesn't add up -- today is %s, so that should "
            "read %s" % (f["marker"], f["claimed"], f["today"], f["expected"])
        )
    return "; ".join(parts)


CORPUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "date-claims-corpus.json")
CORPUS_SHA = "06148237cfbffa453a99dbe1ebf6108ab96241248af01aa1a24a1572caec76ce"


def corpus_rows(path=None):
    path = path or CORPUS_PATH
    raw = io.open(path, encoding="utf-8").read()
    return json.loads(raw)["cases"], hashlib.sha256(raw.encode("utf-8")).hexdigest()


def corpus_failures(rows=None, path=None):
    """Rows this implementation disagrees with. Empty list means in sync.

    Takes `rows` so the self-test can hand it a deliberately wrong expectation
    and prove the comparator still reports -- the same guard shell_shapes'
    corpus_failures() carries, for the same reason: an unblinded comparator
    that never says no is decoration (house-rules 6c).
    """
    if rows is None:
        rows, _ = corpus_rows(path)
    out = []
    for r in rows:
        got = sorted({f["shape"] for f in scan(r["text"], today=r["today"])})
        if got != r["expect"]:
            out.append({"why": r["why"], "expected": r["expect"], "got": got})
    return out


def self_test() -> int:
    fails = []

    def check(ok, msg):
        print(("  ok   " if ok else "  FAIL ") + msg)
        if not ok:
            fails.append(msg)

    def shapes(text, today):
        return {f["shape"] for f in scan(text, today=today)}

    check("relative-date-mismatch" in shapes(
        "as of yesterday (2026-09-14), it landed -- one day ago.", "2026-09-14"),
        "2026-09-14: 'yesterday' next to today's own date is caught")

    check(shapes("night-shift's doc says Added 2026-09-14 -- the same date as today.",
                 "2026-09-14") == set(),
          "a correct same-day claim is silent")

    check(shapes("This was filed yesterday (2026-09-13).", "2026-09-14") == set(),
          "a correct yesterday claim is silent")

    check("relative-date-mismatch" in shapes(
        "The outage started 3 days ago (2026-09-10).", "2026-09-14"),
        "a wrong N-days-ago claim is caught")

    check(shapes("The outage started 3 days ago (2026-09-11).", "2026-09-14") == set(),
          "a correct N-days-ago claim is silent")

    check(shapes("The report is dated 2026-08-19 and covers the overage.",
                 "2026-09-14") == set(),
          "a bare date with no relative word nearby is silent -- nothing to check")

    check(shapes("This landed yesterday, according to Garrett.", "2026-09-14") == set(),
          "a relative word with no date nearby is silent -- nothing to check it against")

    check(shapes("both unrelated to today's work, filed 2026-09-02.",
                 "2026-09-14") == set(),
          "'today's' (possessive) is not the marker 'today' -- the first version's own false positive")

    check("relative-date-mismatch" in shapes(
        "The branch is 2 days old (2026-09-09).", "2026-09-14"),
        "a wrong N-days-old claim is caught")

    # --- the golden corpus: the ONLY thing that catches drift between this
    # implementation and skyne/scripts/check_date_claims.py ---
    rows, sha = corpus_rows()
    check(sha == CORPUS_SHA,
          "the corpus file is the one this code was frozen against "
          "(sha %s vs %s) -- if this fails, the corpus moved on ONE side "
          "only; sync both repos, do not just bump the sha" % (sha[:12], CORPUS_SHA[:12]))
    fails_c = corpus_failures()
    check(not fails_c,
          "all %d corpus rows agree with this implementation%s"
          % (len(rows), (" -- MISMATCH: %s" % fails_c[:3]) if fails_c else ""))

    planted = [dict(rows[0], expect=["a-shape-that-cannot-exist"])]
    check(len(corpus_failures(rows=planted)) == 1,
          "the comparator reports a mismatch when one is planted -- proving it "
          "compares at all, rather than passing because it looked at nothing")

    silent = [r for r in rows if not r["expect"]]
    check(len(silent) >= 8,
          "the corpus carries enough MUST-STAY-SILENT rows to catch "
          "false-positive drift (got %d)" % len(silent))

    print("self-test: PASS" if not fails else "self-test: %d FAILURE(S)" % len(fails))
    return 1 if fails else 0


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    if "--check" in sys.argv:
        idx = sys.argv.index("--check")
        text = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        today = None
        if "--today" in sys.argv:
            ti = sys.argv.index("--today")
            today = sys.argv[ti + 1] if ti + 1 < len(sys.argv) else None
        found = scan(text, today=today)
        print(message(found) if found else "(clean)")
        sys.exit(1 if found else 0)
    print(__doc__)
    sys.exit(0)


if __name__ == "__main__":
    main()
