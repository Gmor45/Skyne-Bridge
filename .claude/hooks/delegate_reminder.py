#!/usr/bin/env python3
"""delegate_reminder.py -- RETIRED 2026-09-23. Superseded by tier_gate.py.

A TOMBSTONE, NOT A DELETION, AND THE REASON IS A MEASURED TRAP
---------------------------------------------------------------
This hook suggested the `haiku-mechanic` subagent, once per session, when a
prompt matched rule 2's keyword tells. `tier_gate.py` now grades EVERY message
with Haiku (falling back to these same tells, moved there verbatim) and holds
a message that is on the wrong tier -- so this reminder is a strict subset of
it. Whittle: it no longer earns its place, and it is unregistered in
`hooks.json`.

The file itself stays, as a no-op, because deleting it would BREAK every
running cloud container. `skyne/scripts/self_install.py` only ever ADDS hook
registrations, never removes them, and the cloud image's `settings.json`
already registers this path. A registered script that is missing makes
`python3` exit 2 -- and on UserPromptSubmit exit 2 BLOCKS AND ERASES THE
PROMPT. Deleting this file would have blocked every message Garrett typed in
every container provisioned before the deletion.

It prints nothing and exits 0 whatever it is handed. Remove it only once
`check_hook_delivery.py` shows no container registers it.

    python3 delegate_reminder.py --self-test
"""
import subprocess
import sys


def self_test() -> int:
    cp = subprocess.run([sys.executable, __file__], input='{"prompt": "rename the files"}',
                        capture_output=True, text=True)
    ok = cp.returncode == 0 and not cp.stdout.strip() and not cp.stderr.strip()
    print("delegate_reminder tombstone self-test: " + ("PASS (silent, exit 0)" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        sys.stdin.read()
    except Exception:
        pass
    sys.exit(0)
