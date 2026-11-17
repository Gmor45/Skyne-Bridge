#!/usr/bin/env python3
"""Wince's reporter for Skyne-Bridge: does the instruction text this repo ships
say things a reader (a model or Garrett) can act on, and are they true?

It reads the agent files, the skill pointers and the messages hooks print.
It only REPORTS. It never rewrites anything, and it does not judge whether the
prose is GOOD (that is Wince's own job, a model, not a script).

    python scripts/wince_read.py              # report
    python scripts/wince_read.py --self-test  # plant faults, prove each is caught

What it catches:
  1. a file path named in an agent or skill that is not in this repo and does not
     say which repo it lives in (a reader cannot open it)
  2. an agent file whose tool list names a tool that does not exist
  3. an archived W named as if it could still be sent as an agent
  4. a count that contradicts the disk ("the three W agent files" vs the files)
  5. the README announcing a plugin version higher than plugin.json
  6. two copies of one file that have drifted apart (wherewasi SKILL vs PASTE-ME)
  7. padding: the same long sentence written twice, and stock filler phrases
"""
import json
import re
import sys
import tempfile
from pathlib import Path

REAL_TOOLS = {
    "Read", "Glob", "Grep", "Bash", "Skill", "ToolSearch", "WebSearch", "WebFetch",
    "Edit", "Write", "NotebookEdit", "Agent", "ListSkills", "ListPlugins",
    "SearchSkills", "SearchPlugins", "PowerShell", "Monitor", "SendMessage",
}
NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
NON_W_AGENTS = {"haiku-mechanic"}
# Words that say a path belongs to some OTHER repo, so a reader knows where to look.
ANCHORS = re.compile(r"\b(skyne|claude-audit|gartera|gmor45|private|repo|repository|vault|clone)\b", re.I)
EXTERNAL_PREFIX = re.compile(r"^(skyne|claude-audit|gartera-vault|gmor45)/", re.I)
FILLER = ["it is important to note", "please note that", "make sure to", "needless to say", "it goes without saying"]

# Known gaps found 2026-11-17. The reporter must find no MORE than these.
# Each is a plain-sentence prefix; a finding is "known" if it starts with one.
KNOWN_GAPS = []  # the five repo-less references were fixed in wince.md 2026-11-17

PATH_TOKEN = re.compile(r"`([A-Za-z0-9_./\-]+\.(?:py|md|json|yml|html))`")


def _read(p):
    return Path(p).read_text(encoding="utf-8")


def _front(text):
    m = re.match(r"---\r?\n(.*?)\r?\n---", text, re.S)
    out = {}
    if m:
        for line in m.group(1).splitlines():
            k, sep, v = line.partition(":")
            if sep:
                out[k.strip()] = v.strip().strip('"')
    return out


def _prose_files(root):
    fs = sorted((root / ".claude" / "agents").glob("*.md"))
    fs += sorted((root / ".claude" / "skills").glob("*/*.md"))
    fs += sorted((root / "gmor45-skills" / "skills").glob("*/SKILL.md"))
    return fs


def check(root):
    root = Path(root)
    f = []
    files = _prose_files(root)
    on_disk = {p.name for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}

    # 1. paths a reader cannot open
    for p in files:
        text = _read(p)
        # a pointer skill that says anywhere it fetches from another repo has said where its paths live
        if p.name != "wince.md" and p.parent.name != "agents" and ANCHORS.search(text):
            continue
        longer = set(PATH_TOKEN.findall(text))
        for ln in text.splitlines():
            for tok in PATH_TOKEN.findall(ln):
                if "/" not in tok and any(o != tok and o.endswith("/" + tok) for o in longer):
                    continue
                if EXTERNAL_PREFIX.match(tok):
                    continue
                here = [root / tok, root / ".claude" / tok, root / ".claude" / "hooks" / tok]
                if any(h.exists() for h in here) or Path(tok).name in on_disk and "/" not in tok:
                    continue
                if ANCHORS.search(ln):
                    continue
                f.append(f"{p.name} names `{tok}` but it is not in this repo and the line does not say which repo has it"
                         if p.name != "SKILL.md" else
                         f"{p.parent.name}/SKILL.md names `{tok}` but it is not in this repo and the line does not say which repo has it")

    # 2. tools that do not exist
    for p in sorted((root / ".claude" / "agents").glob("*.md")):
        fm = _front(_read(p))
        for t in [x.strip() for x in fm.get("tools", "").split(",") if x.strip()]:
            if t not in REAL_TOOLS and not t.startswith("mcp__"):
                f.append(f"{p.name} lists a tool '{t}' that is not a known tool name")
        if not fm.get("description"):
            f.append(f"{p.name} has no description, so nothing can pick this agent")

    # 3. archived W named as if still sendable
    archived = [p.stem for p in (root / ".claude" / "agents-archive").glob("*.md") if p.stem != "README"]
    for p in files:
        t = _read(p)
        for a in archived:
            if re.search(rf"(subagent_type[\"':= ]+{a}\b|load-house-rules:{a}\b|\.claude/agents/{a}\.md)", t, re.I):
                f.append(f"{p.name} sends work to archived W '{a}' as if it were an agent")

    # 4. counts against the disk
    w_agents = [p.stem for p in (root / ".claude" / "agents").glob("*.md") if p.stem not in NON_W_AGENTS]
    for p in files:
        for m in re.finditer(r"\b(two|three|four|five|six|seven|eight|nine)\s+W\s+agent\s+files", _read(p), re.I):
            if NUMBER_WORDS[m.group(1).lower()] != len(w_agents):
                f.append(f"{p.name} says '{m.group(0)}' but there are {len(w_agents)} on disk")

    # 5. README version claim
    pj = root / ".claude" / ".claude-plugin" / "plugin.json"
    rd = root / "README.md"
    if pj.exists() and rd.exists():
        cur = tuple(int(x) for x in json.loads(_read(pj)).get("version", "0.0.0").split("."))
        for v in re.findall(r"plugin (\d+\.\d+\.\d+)", _read(rd)):
            if tuple(int(x) for x in v.split(".")) > cur:
                f.append(f"README announces plugin {v} but plugin.json is {'.'.join(map(str, cur))}")

    # 6. copies that drifted
    ww = root / ".claude" / "skills" / "wherewasi"
    if (ww / "SKILL.md").exists() and (ww / "PASTE-ME.md").exists():
        if _read(ww / "SKILL.md") != _read(ww / "PASTE-ME.md"):
            f.append("wherewasi/SKILL.md and wherewasi/PASTE-ME.md are meant to be the same text and no longer are")

    # 7. padding (PASTE-ME is a deliberate copy; sentences shared between files are
    # deliberate template text, so only a repeat INSIDE one file counts)
    for p in files:
        if p.name == "PASTE-ME.md":
            continue
        t = _read(p)
        nm = p.relative_to(root).as_posix()
        for fl in FILLER:
            if fl in t.lower():
                f.append(f"{nm} uses the filler '{fl}'")
        body = re.sub(r"^---.*?---", "", t, count=1, flags=re.S)
        seen = set()
        for s in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", body)):
            s = s.strip()
            if len(s) >= 70 and not s.startswith(("|", "-", "#", "`")):
                if s in seen:
                    f.append(f"{nm} says '{s[:60]}...' twice")
                seen.add(s)
    return f


def known(x):
    return any(x.startswith(k) for k in KNOWN_GAPS)


def report(root):
    found = check(root)
    for x in found:
        print(("KNOWN  " if known(x) else "DEFECT ") + x)
    new = [x for x in found if not known(x)]
    print(f"{len(found)} finding(s), {len(new)} not on the known-gaps list")
    return found, new


def _mini(b):
    (b / ".claude" / "agents").mkdir(parents=True)
    (b / ".claude" / "agents-archive").mkdir()
    (b / ".claude" / "skills" / "s").mkdir(parents=True)
    (b / ".claude" / ".claude-plugin").mkdir()
    (b / ".claude" / "agents" / "a.md").write_text(
        "---\nname: a\ndescription: does a\ntools: Read, Bash\n---\nRun `real.py` to see it.\n", encoding="utf-8")
    (b / ".claude" / "agents-archive" / "ward.md").write_text("x", encoding="utf-8")
    (b / ".claude" / "skills" / "s" / "SKILL.md").write_text("---\nname: s\ndescription: d\n---\nShort.\n", encoding="utf-8")
    (b / "real.py").write_text("x", encoding="utf-8")
    (b / ".claude" / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "1.6.0"}), encoding="utf-8")
    (b / "README.md").write_text("Update (plugin 1.6.0): fine.\n", encoding="utf-8")


def self_test():
    ok = True

    def expect(label, cond):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + label)
        ok = ok and cond

    with tempfile.TemporaryDirectory() as t:
        _mini(Path(t))
        expect("a clean mini repo has no findings", check(t) == [])
    long_s = "This is a sentence that is long enough to count as padding when written twice over."
    faults = {
        "a path nobody can open": ("a.md", "---\nname: a\ndescription: d\n---\nOpen `missing/file.md` now.\n", "missing/file.md"),
        "a tool that does not exist": ("a.md", "---\nname: a\ndescription: d\ntools: Read, Teleport\n---\nx\n", "Teleport"),
        "an archived W sent as an agent": ("a.md", "---\nname: a\ndescription: d\n---\nUse subagent_type: ward for this.\n", "archived W 'ward'"),
        "a wrong count": ("a.md", "---\nname: a\ndescription: d\n---\nWe keep the five W agent files.\n", "on disk"),
        "an agent with no description": ("a.md", "---\nname: a\n---\nx\n", "no description"),
        "filler": ("a.md", "---\nname: a\ndescription: d\n---\nPlease note that this matters.\n", "filler"),
        "a repeated sentence": ("a.md", "---\nname: a\ndescription: d\n---\n" + long_s + " " + long_s + "\n", "twice"),
    }
    for label, (fn, text, needle) in faults.items():
        with tempfile.TemporaryDirectory() as t:
            b = Path(t)
            _mini(b)
            (b / ".claude" / "agents" / fn).write_text(text, encoding="utf-8")
            expect("catches: " + label, any(needle in x for x in check(b)))
    with tempfile.TemporaryDirectory() as t:
        b = Path(t)
        _mini(b)
        (b / "README.md").write_text("Update (plugin 9.0.0): oops.\n", encoding="utf-8")
        expect("catches: README claims a newer version", any("README announces" in x for x in check(b)))
    with tempfile.TemporaryDirectory() as t:
        b = Path(t)
        _mini(b)
        ww = b / ".claude" / "skills" / "wherewasi"
        ww.mkdir()
        (ww / "SKILL.md").write_text("---\nname: wherewasi\ndescription: d\n---\none\n", encoding="utf-8")
        (ww / "PASTE-ME.md").write_text("two\n", encoding="utf-8")
        expect("catches: two copies drifted", any("no longer are" in x for x in check(b)))
    with tempfile.TemporaryDirectory() as t:
        b = Path(t)
        _mini(b)
        (b / ".claude" / "agents" / "a.md").write_text(
            "---\nname: a\ndescription: d\n---\nSee `other/thing.md` in the Skyne repo.\n", encoding="utf-8")
        expect("does not flag a path that names its repo", check(b) == [])
    root = Path(__file__).resolve().parent.parent
    new = [x for x in check(root) if not known(x)]
    for x in new:
        print("  not on the known-gaps list:", x)
    expect("the real repo has nothing beyond the known gaps", not new)
    print("SELF-TEST " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    report(Path(__file__).resolve().parent.parent)
