---
name: flow
description: Run a Gartera session the way Garrett actually works — track What he is looking at and How he is working, notice when either drifts, keep a live session pane he can glance at, and package the session for Claude Code when Cowork cannot push. Use for any Gartera worldbuilding session in Cowork, and whenever he says "flow", "start a session", "what have we done", "show me the pane", "where are we", "did anything get dropped", "wrap this up", or "bundle it". Distinct from `gartera`, which routes personas and enforces canon rules — this skill is the session around that work, not the work itself. This skill does not contain the session model — it fetches it.
---

# Flow — pointer

**This skill does not contain the model. The real one lives in the private
`Gmor45/Gartera-Vault` repo**, alongside `Vault Ops/Flow — Design Record.md`,
which the real skill treats as the design of record if the two ever disagree.

## Do this, in order

1. **If the vault is not already cloned this session, run the `gartera-connect`
   pointer first.**

2. **Read the real procedure from the clone, in full, and follow it exactly:**

   ```
   ~/vault-work/Gartera-Vault/.claude/skills/flow/SKILL.md
   ```

   That file governs the session pane (currently one continuous Chain artifact
   per thread of work, republished every turn — this OVERTURNED an earlier
   "one artifact per chat" model on 2026-08-30, so do not assume the older
   shape from a prior session), the What/How tracking, the agreement/challenge
   ledger, and the wrap-up bundle-and-handoff sequence. **Do not act on a
   remembered version** — an installed copy of this exact skill was measured
   on 2026-09-01 to be running the old per-chat artifact model, among other
   gaps, weeks after the repo moved on.

3. **The repo file wins on any disagreement**, for the rest of the session.

## Why this file is this short

The session model changes as Garrett's own working habits are observed and
ruled on — it is not something to freeze into an installed copy. Fetching it
live means a ruling like the 2026-08-30 artifact-model change reaches the very
next session that opens this pointer, with nothing to paste.
