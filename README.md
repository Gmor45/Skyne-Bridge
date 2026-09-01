# claude-bootstrap

Public on purpose, and deliberately almost empty.

Claude's `Add marketplace` feature only syncs from a **public** repository
(verified 2026-08-29: a private repo returns *"Marketplace sync failed"*, an
otherwise identical public one syncs). The operating rules this points at are
personal, so publishing them to satisfy that requirement would be a bad trade.

This repo is the way around that. It carries one skill whose only job is to
clone the private repo and read the real rules from there. Nothing here is
worth protecting; everything that is stays private and is read live, so a rule
change is in force on the next session rather than after someone remembers to
paste it.

Install once, in the Plugins panel: **Add → Add marketplace →**
`https://github.com/Gmor45/claude-bootstrap`, leaving **Sync automatically** on.

## It also carries the reply gate

`.claude/hooks/reply_gate.py`, registered as a `Stop` hook in
`.claude/hooks/hooks.json`. It is here rather than in the private repo for one
reason: **a plugin already synced with "Sync automatically" on installs its
hooks with no further click.** House rule 15 says installing a skill is
Garrett's click and he should not be asked to click often — this is the one
delivery path that asks for zero.

**What it does.** When a substantive reply is about to be sent, the gate refuses
the stop unless the reply ends with a fixed block:

```
**What I did**       plain English, no jargon
**Why**              plain English, no jargon
**Recommendations**  optional, each with its reason
**TLDR**             one line
```

The body above the block may be as long and as technical as the work needs. The
block is what makes it optional to read.

**Why a hook and not another line in the rules.** House rule 21: a rule with no
mechanism is a hypothesis, and `convention-no-mechanism` is the single largest
failure class in the miss ledger. "Be concise" had been asked for more often
than anything else and had never held, because it is re-judged every turn and
every turn has a local excuse. A hook is the top row of rule 21's mechanism
table — it fires before the turn exists, with no judgment call.

**What it deliberately does not do.** It cannot tell whether prose is actually
simple; it checks shape, size, and a banned word list inside the block only. That
residue is uncovered on purpose — rule 21 point 5 says name what a gate cannot
see rather than shipping one that passes on the real failure.

It fails open on every error path, ignores short replies and tool-only turns, and
gives up after two re-prompts so it can never trap a session.

```bash
python3 .claude/hooks/reply_gate.py --self-test            # 10 checks
python3 .claude/hooks/reply_gate.py --transcript <file>    # dry-run a real transcript
```

The banned-word list is meant to grow: **when Garrett asks what a word means,
that word goes in the list in the same turn.**
