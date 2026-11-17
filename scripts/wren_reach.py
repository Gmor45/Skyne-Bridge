#!/usr/bin/env python3
"""Wren's reporter for Skyne-Bridge: can Garrett actually reach the estate
from each way in, the lazy way, and which ways fail or need a step he would skip?

It only READS this PC and REPORTS. It uses no passwords or tokens, opens no
browser, and changes nothing. Anything that would need a login is printed as
MANUAL with the one step to do by hand.

    python scripts/wren_reach.py              # report
    python scripts/wren_reach.py --self-test  # plant faults, prove each is caught

Each line is OK, FAILED or MANUAL.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN = "load-house-rules"
MARKET = "gmor45-bootstrap"
POINTER = ("load-house-rules",)   # the skill claude.ai / Cowork need uploaded


def _j(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


def _ver(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except Exception:
        return (0,)


def _python3_runs():
    exe = shutil.which("python3")
    if not exe:
        return False, "the command 'python3' is not found, so every hook would silently not run"
    try:
        r = subprocess.run([exe, "-c", "print(1)"], capture_output=True, text=True, timeout=20)
    except Exception as e:  # noqa
        return False, f"'python3' would not start: {e}"
    if r.stdout.strip() != "1":
        return False, "'python3' is there but does not run Python (likely the Windows Store stub)"
    return True, "'python3' runs"


def check(home, repo, python_check=_python3_runs):
    """Return a list of (way_in, status, plain sentence)."""
    home, repo = Path(home), Path(repo)
    out = []
    repo_plugin = _j(repo / ".claude" / ".claude-plugin" / "plugin.json") or {}
    want = repo_plugin.get("version", "?")

    # 1. Claude Code on this PC: is the plugin installed, current and switched on?
    inst = _j(home / "plugins" / "installed_plugins.json") or {}
    entry = (inst.get("plugins", {}).get(f"{PLUGIN}@{MARKET}") or [None])[0]
    enabled = (_j(home / "settings.json") or {}).get("enabledPlugins", {}).get(f"{PLUGIN}@{MARKET}")
    if not entry:
        out.append(("Claude Code on this PC", "FAILED", f"{PLUGIN} is not installed, so no hook and no rules pointer loads"))
    else:
        if enabled is not True:
            out.append(("Claude Code on this PC", "FAILED", f"{PLUGIN} is installed but switched OFF, so none of its hooks run"))
        else:
            out.append(("Claude Code on this PC", "OK", f"{PLUGIN} is installed and on"))
        if _ver(entry.get("version")) < _ver(want):
            out.append(("Hooks delivered", "FAILED",
                        f"installed copy is {entry.get('version')} but this repo is {want}; the newer hooks have not arrived"))
        else:
            out.append(("Hooks delivered", "OK", f"installed copy {entry.get('version')} is current"))
        ip = Path(entry.get("installPath", ""))
        hj = _j(ip / "hooks" / "hooks.json")
        if hj is None:
            out.append(("Hooks delivered", "FAILED", "installed copy has no readable hooks.json"))
        else:
            missing = set()
            for groups in hj.get("hooks", {}).values():
                for g in groups:
                    for h in g.get("hooks", []):
                        for n in re.findall(r"hooks/([A-Za-z0-9_\-]+\.py)", h.get("command", "")):
                            if not (ip / "hooks" / n).exists():
                                missing.add(n)
            if missing:
                out.append(("Hooks delivered", "FAILED", "installed copy names hook files that are not there: " + ", ".join(sorted(missing))))
    # 2. Can a hook even start?
    ok, why = python_check()
    out.append(("Hooks can start", "OK" if ok else "FAILED", why))

    # 3. The second plugin (the pointer skills for handoff, research...)
    if not (inst.get("plugins", {}).get(f"gmor45-skills@{MARKET}")):
        out.append(("Pointer skills plugin (gmor45-skills)", "FAILED",
                    "not installed on this PC, so handoff / research / game-it-out are not there for Claude Code"))
    else:
        out.append(("Pointer skills plugin (gmor45-skills)", "OK", "installed"))

    # 4. claude.ai / Cowork / phone need the pointer skill uploaded by hand
    for name in POINTER:
        sk = repo / ".claude" / "skills" / name / "SKILL.md"
        if not sk.exists():
            out.append(("claude.ai / Cowork pointer skill", "FAILED", f"{name}/SKILL.md is missing in the repo"))
        else:
            out.append(("claude.ai / Cowork pointer skill", "MANUAL",
                        f"{name}/SKILL.md is ready here; whether it is uploaded to claude.ai Settings > Skills cannot be seen from this PC"))
    out.append(("Cowork", "MANUAL", "needs a look at Cowork's own skill list; nothing on this PC shows it"))
    out.append(("Phone", "MANUAL", "uses the claude.ai skill list; open the app and ask for the house rules once"))

    # 5. The Skyne connector: only whether one is configured by name, never its keys
    cfg = _j(home.parent / ".claude.json") or {}
    names = set((cfg.get("mcpServers") or {}).keys())
    if any("skyne" in n.lower() for n in names):
        out.append(("Skyne connector", "MANUAL", "a Skyne server is configured here; whether it answers needs a login, so ask Claude to call it once"))
    else:
        out.append(("Skyne connector", "MANUAL", "no Skyne server is listed in the local config (it may come from a plugin or claude.ai); check the connectors list by hand"))
    return out


def report(home, repo):
    rows = check(home, repo)
    for way, st, why in rows:
        print(f"{st:7} {way}: {why}")
    bad = [r for r in rows if r[1] == "FAILED"]
    print(f"{len(bad)} failed, {sum(r[1] == 'MANUAL' for r in rows)} manual, {sum(r[1] == 'OK' for r in rows)} ok")
    return rows


def _fake_home(base, version="1.6.0", enabled=True, skills=True, hooks_file=True):
    h = base / "home" / ".claude"
    ip = h / "plugins" / "cache" / PLUGIN
    (ip / "hooks").mkdir(parents=True)
    plugins = {f"{PLUGIN}@{MARKET}": [{"version": version, "installPath": str(ip)}]}
    if skills:
        plugins[f"gmor45-skills@{MARKET}"] = [{"version": "1.1.0", "installPath": str(ip)}]
    (h / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": plugins}), encoding="utf-8")
    (h / "settings.json").write_text(json.dumps({"enabledPlugins": {f"{PLUGIN}@{MARKET}": enabled}}), encoding="utf-8")
    cmd = 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/a.py"'
    (ip / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"command": cmd}]}]}}), encoding="utf-8")
    if hooks_file:
        (ip / "hooks" / "a.py").write_text("x", encoding="utf-8")
    return h


def _fake_repo(base, with_skill=True):
    r = base / "repo"
    (r / ".claude" / ".claude-plugin").mkdir(parents=True)
    (r / ".claude" / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "1.6.0"}), encoding="utf-8")
    if with_skill:
        (r / ".claude" / "skills" / PLUGIN).mkdir(parents=True)
        (r / ".claude" / "skills" / PLUGIN / "SKILL.md").write_text("x", encoding="utf-8")
    return r


def self_test():
    ok = True

    def expect(label, cond):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + label)
        ok = ok and cond

    good = lambda: (True, "fine")
    bad_py = lambda: (False, "no python3")

    def run(py=good, **kw):
        rk = {k: kw.pop(k) for k in ("with_skill",) if k in kw}
        with tempfile.TemporaryDirectory() as t:
            b = Path(t)
            h = _fake_home(b, **kw)
            r = _fake_repo(b, **rk)
            return check(h, r, py)

    fails = lambda rows: [x for x in rows if x[1] == "FAILED"]
    expect("a healthy setup has no failures", fails(run()) == [])
    expect("catches: plugin switched off", any("OFF" in x[2] for x in fails(run(enabled=False))))
    expect("catches: installed copy is older than the repo", any("not arrived" in x[2] for x in fails(run(version="1.5.1"))))
    expect("catches: hooks.json names a file that is not there", any("not there" in x[2] for x in fails(run(hooks_file=False))))
    expect("catches: python3 does not run", any("python3" in x[2] for x in fails(run(py=bad_py))))
    expect("catches: pointer-skills plugin not installed", any("gmor45-skills" in x[0] for x in fails(run(skills=False))))
    expect("catches: pointer skill missing in the repo", any("pointer skill" in x[0] for x in fails(run(with_skill=False))))
    manual = [x for x in run() if x[1] == "MANUAL"]
    expect("login-only ways in are MANUAL, never faked as OK", len(manual) >= 4)
    print("SELF-TEST " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    report(Path.home() / ".claude", Path(__file__).resolve().parent.parent)
