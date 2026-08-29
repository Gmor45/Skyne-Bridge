---
name: load-house-rules
description: Load Gmor45's standing operating rules before doing anything else. Use at the START of every session on any surface — Claude Code, Cowork, or claude.ai chat — that touches a Gmor45 repository (claude-audit, Gartera-Vault, FusterCluck, Tangle, claude-usage-hud, DnD-Scheduler, cloudflare-deploy, wedding), any Obsidian vault, or anything involving git, commits, branches, pushing, pull requests, merging, GitHub Actions, model choice, thinking effort, session length, usage limits, or cost. Also use on "don't push to main", "am I using this right", "should I start a new chat", "why is this so expensive", or any callout of a repeated mistake. This skill does not contain the rules — it fetches them.
---

# Load the house rules

**This skill is a pointer, not the rules.** The rules live in a private
repository so they can stay specific without being public. This file's only job
is to go get them, so that a rule change pushed to that repo reaches every
surface without anyone pasting anything.

## Do this first, before answering

1. **Clone or pull the private repo** into this session's workspace:

   ```
   git clone --depth 1 https://github.com/Gmor45/claude-audit.git
   # already present? then:  git -C claude-audit pull --ff-only
   ```

2. **Read the rules file in full:**

   ```
   claude-audit/.claude/skills/house-rules/SKILL.md
   ```

   Read the whole thing. Do not skim it, and do not act on a summary of it —
   it is the operating contract for every surface, and the failure it most
   often catches is a session that read *about* a thing instead of opening it.

3. **Follow it as if it had been loaded directly.** Everything in it applies:
   branch discipline, model and session-length guidance, the decisions
   register, the learning loop, the Thread, the braindump sweep.

4. **Also read, in the same repo, whichever of these the task touches:**

   | File | When |
   |---|---|
   | `.claude/skills/house-rules/DECISIONS.md` | Before asking him to re-affirm ANY design or process decision. Grep it first; if the ruling is there, act on it and cite it. |
   | `.claude/skills/night-shift/SKILL.md` | The nightly learning-loop procedure. |
   | `.claude/skills/handoff/SKILL.md` | Ending a session properly. |
   | `.claude/skills/braindump/SKILL.md` | A handwritten PDF, photo dump, or note export arrives. |
   | `.claude/skills/session-digest/SKILL.md` | The session/model audit. |

## If the clone fails

**Say so plainly and immediately. Do not proceed as if there were no rules.**

A session that silently continues without them is the exact failure this whole
arrangement exists to prevent — it will re-derive settled decisions, push to
`main`, and re-ask questions that were answered weeks ago, all while appearing
to work fine.

Known limits, so a failure is diagnosed rather than re-investigated:

- **claude.ai chat has no git.** It cannot clone anything. On that surface this
  skill cannot work, and the rules have to be pasted by hand. Say that rather
  than improvising.
- **Cowork can clone and pull, but cannot push.** Reading is what this skill
  needs, so it works there — verified 2026-08-29. If a *push* fails in Cowork,
  that is expected and documented; it is not this skill's problem.
- **A private repo needs the session to be authorized for it.** If the clone is
  refused, that is an access problem, not a missing file. Report which it was.

## Why it is built this way

The rules must reach Claude Code, Cowork, and claude.ai alike. The only
account-level mechanism for that requires a **public** repository, and the rules
themselves are personal — they name how he works, what he spends, and his own
words about his mistakes. Publishing that to solve a sync problem is a bad
trade.

So the public half is this pointer, which contains nothing worth protecting, and
the private half stays private and is read live. A rule change pushed to
`claude-audit` is in force on the next session that loads this skill — no paste,
no copy to drift out of date.
