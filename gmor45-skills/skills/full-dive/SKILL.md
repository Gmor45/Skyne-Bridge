---
name: full-dive
description: Run the maximal whole-vault Gartera audit — the "mother of all audits" that checks everything piece by piece with proof of coverage. Use ONLY when Garrett explicitly invokes it — "full dive", "full-dive", "run the big audit", "heavy audit", "the mother of all audits", "magnifying-glass pass", "audit everything" — and never for routine checks (vault_health, background audit, "is the vault healthy" all stay with the gartera skill and existing scripts). This is a heavy, rare operation intended at most weekly. This skill does not contain the audit procedure — it fetches it.
---

# Full-dive vault audit — pointer

**This skill is a pointer, not the audit.** The real, current procedure lives
in the private `Gmor45/Gartera-Vault` repo.

## Do this, in order

1. **If the vault is not already cloned this session, run the `gartera-connect`
   pointer first.**

2. **Read the real procedure from the clone, in full, and follow it exactly:**

   ```
   ~/vault-work/Gartera-Vault/.claude/skills/full-dive/SKILL.md
   ```

   That file defines the coverage manifest, the semantic deep-read layer, and
   the dated-report format this audit must produce. Read it whole — this is
   a rare, heavy operation and a stale or partial copy of its procedure is the
   worst place for that to matter.

3. **The repo file wins on any disagreement**, for the rest of the session.

## Why this file is this short

Same reason as its siblings (`gartera`, `gartera-connect`, `flow`): the
procedure lives in one place, fetched live, so it never has a second copy to
drift out of date.
