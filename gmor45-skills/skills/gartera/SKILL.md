---
name: gartera
description: Load the correct Gartera vault persona (Wistin, Ward, or Weir) and their authority files before doing any worldbuilding, canon, structural, or campaign work on the Gartera D&D setting. Use whenever the conversation touches Gartera, the Lore Hunt campaign, the Primes, Cosmic Tensions, Prime Inheritances, the Aegis, Structural Axioms, the Canon Log, Open Pins, the Throughline, or any file in the Gartera Vault. Also use for requests phrased as "be Wistin", "ask Ward", "what does Weir think", "check canon", "is this consistent", or "put a pin in that". This skill does not contain the persona rules — it fetches them.
---

# Gartera persona loader — pointer

**This skill is a pointer, not the personas.** Wistin, Ward, and Weir are
defined in the private `Gmor45/Gartera-Vault` repo, and duplicating their
definitions here would be the one-fact-two-writers problem this vault exists
to prevent in its own lore — pointed at its own instructions instead.

## Do this, in order

1. **If the vault is not already cloned this session, run the `gartera-connect`
   pointer first.** It gets `~/vault-work/Gartera-Vault` current and sets up
   the required git config.

2. **Read the real procedure from the clone, in full, and follow it exactly:**

   ```
   ~/vault-work/Gartera-Vault/.claude/skills/gartera/SKILL.md
   ```

   That file is the actual persona router — routing rules, the mandatory
   Canon Brief / pin-token / pin-pressure sequence, the shared-store write
   protocol, the naming ledger, and the "Wistin:/Ward:/Weir:/Claude:" speaking
   rule. Read it whole. **Do not act on a memory of an earlier session's copy
   of this skill** — measured live on 2026-09-01, an installed copy of this
   exact skill was found running behind the repo by weeks, missing the
   `whois.py` mandatory-lookup step, the derived pin-token script, and an
   entire section on lossy reads added the same week.

3. **The repo file wins on any disagreement**, for the rest of the session.
   This pointer's only job was routing you to it.

## Why this file is this short

Everything that actually governs persona behavior lives in the repo and is
fetched live, every session — a canon or process change Garrett makes there is
in force the moment this pointer next loads, with nothing to paste and nothing
to fall behind.
