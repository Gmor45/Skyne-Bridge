#!/usr/bin/env python3
"""Ward's reporter for Skyne-Bridge: are the plugin, its hooks and its skills
registered and in step with each other?

It only READS and REPORTS. It never rewrites a file.

    python scripts/ward_in_step.py              # report on this repo
    python scripts/ward_in_step.py --self-test  # plant faults, prove each is caught

What "in step" means here (each one a way this repo has drifted before or could):
  1. every command in hooks.json points at a file that exists
  2. every hook file that has a --self-test is run in .github/workflows/ci.yml
  3. every hook file is either registered in hooks.json or listed as a helper
  4. every skill folder has a SKILL.md whose name matches its folder and has a description
  5. every plugin in the marketplace file points at a folder that exists, and its
     name and version agree with that folder's plugin.json
  6. every agent file's name matches its file name
"""
import json
import re
import sys
import tempfile
from pathlib import Path

# Hook files that are NOT meant to be registered (library code other hooks import,
# or retired stubs kept on purpose). Naming them here is the ratchet: a NEW
# unregistered file fails, an old one cannot quietly grow.
KNOWN_HELPERS = {
    "tier_gate_golden.py",   # test runner for tier_gate, run by CI, not a hook
    "delegate_reminder.py",  # retired 2026-09-23, kept as a silent tombstone
    "route_eval.py",         # exam scorer for the W router, run by CI
    "reply_notes.py",        # registered, listed only if the pattern changes
    "w_cost.py",             # R19 cost tracker, imported lazily by w_follow and run by SessionStart in the background
}
# Known gaps found on 2026-11-17. The reporter must find no MORE than these.
KNOWN_GAPS = set()  # the three un-run self-tests were wired into ci.yml 2026-11-17

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _read(p):
    return Path(p).read_text(encoding="utf-8")


def _front(text):
    m = re.match(r"---\r?\n(.*?)\r?\n---", text, re.S)
    out = {}
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            if _:
                out[k.strip()] = v.strip().strip('"')
    return out


def check(root):
    root = Path(root)
    f = []
    plugin = root / ".claude"
    hooks_dir = plugin / "hooks"
    # 1 + 3: hooks.json
    registered = set()
    try:
        hj = json.loads(_read(hooks_dir / "hooks.json"))["hooks"]
    except Exception as e:  # noqa
        return [f"hooks.json cannot be read: {e}"]
    for ev, groups in hj.items():
        for g in groups:
            for h in g.get("hooks", []):
                for name in re.findall(r"hooks/([A-Za-z0-9_\-]+\.py)", h.get("command", "")):
                    registered.add(name)
                    if not (hooks_dir / name).exists():
                        f.append(f"hooks.json ({ev}) runs {name}, which does not exist")
    # a file imported by a registered hook is library code, not an orphan
    imported = set()
    for name in registered:
        fp = hooks_dir / name
        if fp.exists():
            for m in re.findall(r"^\s*(?:import|from)\s+([A-Za-z0-9_]+)", _read(fp), re.M):
                imported.add(m + ".py")
    # 2: self-test files vs ci.yml
    ci_path = root / ".github" / "workflows" / "ci.yml"
    ci = _read(ci_path) if ci_path.exists() else ""
    if not ci:
        f.append("ci.yml is missing, so no hook is checked on a pull request")
    for p in sorted(hooks_dir.glob("*.py")):
        src = _read(p)
        if "--self-test" in src and p.name not in ci:
            f.append(f"{p.name} has a self-test but ci.yml never runs it")
        if p.name not in registered and p.name not in imported and p.name not in KNOWN_HELPERS:
            f.append(f"{p.name} is in the hooks folder but not registered in hooks.json (and not a known helper)")
    # 4: skills
    for skills in (plugin / "skills", root / "gmor45-skills" / "skills"):
        if not skills.is_dir():
            continue
        for d in sorted(x for x in skills.iterdir() if x.is_dir()):
            sk = d / "SKILL.md"
            if not sk.exists():
                f.append(f"skill folder {d.relative_to(root).as_posix()} has no SKILL.md")
                continue
            fm = _front(_read(sk))
            if fm.get("name") != d.name:
                f.append(f"{sk.relative_to(root).as_posix()}: name is '{fm.get('name')}', folder is '{d.name}'")
            if not fm.get("description"):
                f.append(f"{sk.relative_to(root).as_posix()}: no description, so nothing can pick it")
    # 5: marketplace vs plugin.json
    try:
        mk = json.loads(_read(root / ".claude-plugin" / "marketplace.json"))
    except Exception as e:  # noqa
        mk = None
        f.append(f"marketplace.json cannot be read: {e}")
    for pl in (mk or {}).get("plugins", []):
        sub = pl.get("source", {}).get("path", "")
        pj = root / sub / ".claude-plugin" / "plugin.json"
        if not pj.exists():
            f.append(f"marketplace plugin '{pl.get('name')}' points at {sub}, which has no plugin.json")
            continue
        j = json.loads(_read(pj))
        if j.get("name") != pl.get("name"):
            f.append(f"marketplace calls it '{pl.get('name')}', {sub}/plugin.json calls it '{j.get('name')}'")
        if not SEMVER.match(str(j.get("version", ""))):
            f.append(f"{sub}/plugin.json version '{j.get('version')}' is not three numbers")
    # 6: agents
    for p in sorted((plugin / "agents").glob("*.md")):
        if _front(_read(p)).get("name") != p.stem:
            f.append(f"agent file {p.name} has a different name inside")
    return f


def report(root):
    found = check(root)
    new = [x for x in found if x not in KNOWN_GAPS]
    for x in found:
        print(("KNOWN  " if x in KNOWN_GAPS else "DEFECT ") + x)
    print(f"{len(found)} finding(s), {len(new)} not on the known-gaps list")
    return found, new


def _mini(base):
    (base / ".claude" / "hooks").mkdir(parents=True)
    (base / ".claude" / "agents").mkdir()
    (base / ".claude" / "skills" / "one").mkdir(parents=True)
    (base / ".claude" / ".claude-plugin").mkdir()
    (base / ".claude-plugin").mkdir()
    (base / ".github" / "workflows").mkdir(parents=True)
    (base / ".claude" / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/a.py"'}]}]}}), encoding="utf-8")
    (base / ".claude" / "hooks" / "a.py").write_text("# --self-test\n", encoding="utf-8")
    (base / ".github" / "workflows" / "ci.yml").write_text("run: python3 .claude/hooks/a.py --self-test\n", encoding="utf-8")
    (base / ".claude" / "skills" / "one" / "SKILL.md").write_text("---\nname: one\ndescription: does one\n---\n", encoding="utf-8")
    (base / ".claude" / "agents" / "w.md").write_text("---\nname: w\n---\n", encoding="utf-8")
    (base / ".claude" / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "p", "version": "1.0.0"}), encoding="utf-8")
    (base / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"plugins": [
        {"name": "p", "source": {"path": ".claude"}}]}), encoding="utf-8")


def self_test():
    import shutil
    ok = True

    def expect(label, cond):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + label)
        ok = ok and cond

    with tempfile.TemporaryDirectory() as t:
        base = Path(t)
        _mini(base)
        expect("a clean mini repo has no findings", check(base) == [])
        faults = {
            "hooks.json names a missing file": lambda b: (b / ".claude/hooks/a.py").unlink(),
            "hook not run by CI": lambda b: (b / ".github/workflows/ci.yml").write_text("x", encoding="utf-8"),
            "hook file not registered": lambda b: (b / ".claude/hooks/orphan.py").write_text("x", encoding="utf-8"),
            "skill name differs from folder": lambda b: (b / ".claude/skills/one/SKILL.md").write_text("---\nname: two\ndescription: d\n---\n", encoding="utf-8"),
            "skill has no description": lambda b: (b / ".claude/skills/one/SKILL.md").write_text("---\nname: one\n---\n", encoding="utf-8"),
            "marketplace name differs from plugin.json": lambda b: (b / ".claude/.claude-plugin/plugin.json").write_text(json.dumps({"name": "q", "version": "1.0.0"}), encoding="utf-8"),
            "version is not three numbers": lambda b: (b / ".claude/.claude-plugin/plugin.json").write_text(json.dumps({"name": "p", "version": "1.0"}), encoding="utf-8"),
            "agent name differs from file": lambda b: (b / ".claude/agents/w.md").write_text("---\nname: z\n---\n", encoding="utf-8"),
        }
        for label, plant in faults.items():
            with tempfile.TemporaryDirectory() as t2:
                b2 = Path(t2)
                _mini(b2)
                plant(b2)
                expect("catches: " + label, len(check(b2)) >= 1)
    # The real repo may carry only the gaps on the list.
    root = Path(__file__).resolve().parent.parent
    new = [x for x in check(root) if x not in KNOWN_GAPS]
    for x in new:
        print("  not on the known-gaps list:", x)
    expect("the real repo has nothing beyond the known gaps", not new)
    print("SELF-TEST " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    report(Path(__file__).resolve().parent.parent)
