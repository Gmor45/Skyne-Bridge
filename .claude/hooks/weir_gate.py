#!/usr/bin/env python3
"""weir_gate.py -- Stop: a reply that hands Garrett a menu with no pick is Weir's job, undone.

Garrett, 2026-10-05: *"Lets do Weir > Whittle < Wistin"* -- Weir's event
trigger is first. Weir tees up a decision: the question, the real options,
and a pick, never the call itself. House-rules 10 already says it in its own
words: *"A menu of options is worse than either -- he does not want choices
organised, he wants the call made."* and rule 2 treats a menu where a
decision was owed as a sign the work is under-tiered. Nothing fired on it.

WHAT IT CATCHES, DELIBERATELY NARROW
------------------------------------
A reply is refused ONCE when all three hold:
  1. it ends by asking Garrett something (the last non-empty paragraph
     contains a question mark);
  2. it lays out alternatives (option/choice markers: "Option A/B", "A -", a
     list of "or" choices, "which do you prefer", "which one");
  3. nowhere in it does it say which one it would pick ("I'd pick", "my
     pick", "I recommend", "my recommendation", "go with").
The refusal tells the session to answer in Weir's shape -- the question in
one line, the options with what each costs, and a pick with the reason -- or
to hand the job to the `weir` agent. It never makes the choice for him.

A question with ONE option ("want me to merge it?") is not a menu and is left
alone. A menu with a pick is not a failure. A reply that is mostly work with a
closing confirmation is left alone.

NEVER TRAPS A SESSION
---------------------
`stop_hook_active` (the platform's own re-entry flag) means it already refused
once this turn: it allows. Every error path prints nothing and exits 0.

Usage:
    python3 weir_gate.py             # the hook (JSON on stdin)
    python3 weir_gate.py --self-test
"""
from __future__ import annotations

import json
import re
import sys

OPTION_RX = re.compile(
    r"(?:\boption\s+[a-d1-4]\b|^\s*\*{0,2}\(?[A-D]\)?[\s:.\-)—–]+\S|\bwhich (?:one|of these|do you|would you|should)\b"
    r"|\beither\b.*\bor\b|\bor would you rather\b|\bA or B\b)", re.I | re.M)
LABELLED_LIST_RX = re.compile(r"^\s*(?:[-*]\s*)?\*{0,2}\(?[A-C]\)?\*{0,2}[\s:.\-)—–]", re.M)
PICK_RX = re.compile(
    r"(?:\bI(?:'d| would| will) (?:pick|choose|go with|recommend)\b|\bmy (?:pick|recommendation|call|vote)\b"
    r"|\bI recommend\b|\bI(?:'d| would) go with\b|\bgo with (?:option\s+)?[A-D]\b|\brecommend(?:ed|ation)?:)", re.I)
RULED_MSG = ("Weir's job, undone: this reply ends on a question to Garrett and lays out "
             "alternatives but never says which one it would pick. House-rules 10: he does "
             "not want choices organised, he wants the call made. Re-send ONLY the decision, "
             "in Weir's shape: (1) the question in one line, (2) the real options, each with "
             "what it costs, (3) your pick and the reason. You still do not make the call -- "
             "he does. Or hand it to the `weir` agent. If this was not a decision, say so in "
             "one line.")


def last_paragraph(text: str) -> str:
    paras = [p for p in re.split(r"\n\s*\n", (text or "").strip()) if p.strip()]
    return paras[-1] if paras else ""


def is_menu_without_pick(text: str) -> bool:
    text = text or ""
    if "?" not in last_paragraph(text):
        return False
    labelled = len(LABELLED_LIST_RX.findall(text))
    if not (labelled >= 2 or OPTION_RX.search(text)):
        return False
    return not PICK_RX.search(text)


def decide(payload: dict) -> dict | None:
    if payload.get("stop_hook_active"):
        return None
    if not is_menu_without_pick(str(payload.get("last_assistant_message") or "")):
        return None
    return {"decision": "block", "reason": RULED_MSG}


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        out = decide(payload) if isinstance(payload, dict) else None
        if out:
            print(json.dumps(out))
    except Exception:  # noqa: BLE001 -- a gate must never cost a turn
        pass
    return 0


def self_test() -> int:
    ran, fails = [], []

    def check(ok, label):
        ran.append(label)
        if not ok:
            fails.append(label)

    menu = ("Two ways to host the board.\n\nA - Workers: private access is not enforced there.\n"
            "B - Pages branch deploy: already behind Access.\n\nWhich do you want?")
    check(is_menu_without_pick(menu), "a labelled A/B menu ending on a question, with no pick, is caught")
    check(is_menu_without_pick("Option A is faster. Option B is safer.\n\nWhich one should I do?"),
          "'Option A / Option B ... which one' is caught")
    check(not is_menu_without_pick(menu.replace("Which do you want?", "I'd pick B: it is already gated. Which do you want?")),
          "the same menu WITH a pick is left alone (a menu with a pick is Weir's shape)")
    check(not is_menu_without_pick(menu.replace("Which do you want?", "My recommendation is B. Agree?")),
          "'my recommendation' counts as a pick")
    check(not is_menu_without_pick("Merged both PRs and the checks are green.\n\nWant me to start on the backlog?"),
          "one yes/no question after finished work is not a menu")
    check(not is_menu_without_pick("I'd go with Pages.\n\nA - Pages\nB - Workers\n\nDone."),
          "a menu that does not end on a question is left alone")
    check(not is_menu_without_pick(""), "an empty reply is left alone")
    check(not is_menu_without_pick("Which stage is gauge in right now?"),
          "a bare question with no alternatives is not a menu")

    out = decide({"last_assistant_message": menu})
    check(out and out["decision"] == "block" and "Weir" in out["reason"] and "pick" in out["reason"],
          "a menu with no pick is refused with Weir's shape")
    check(decide({"last_assistant_message": menu, "stop_hook_active": True}) is None,
          "stop_hook_active means it already refused once: allow (never traps a session)")
    check(decide({}) is None and decide({"last_assistant_message": None}) is None, "no message is allowed")

    import subprocess
    for bad in ("not json", "[]", ""):
        cp = subprocess.run([sys.executable, __file__], input=bad, capture_output=True, text=True)
        check(cp.returncode == 0 and not cp.stdout.strip(), f"stdin {bad!r} exits 0 and prints nothing")
    cp = subprocess.run([sys.executable, __file__], input=json.dumps({"last_assistant_message": menu}),
                        capture_output=True, text=True)
    check(cp.returncode == 0 and json.loads(cp.stdout)["decision"] == "block",
          "end to end through stdin, a menu with no pick is refused and the hook still exits 0")

    if fails:
        for f in fails:
            print("SELF-TEST FAIL:", f)
        print(f"weir_gate self-test: {len(fails)} FAILED")
        return 1
    print(f"weir_gate self-test: {len(ran)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv[1:] else main())
