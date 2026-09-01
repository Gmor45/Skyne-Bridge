---
name: gartera-connect
description: Use this at the very start of any new Cowork chat that will touch the Gartera Obsidian vault, before doing any worldbuilding, canon, or file work. Clones or pulls github.com/Gmor45/Gartera-Vault into the session workspace, sets up a git identity, and confirms the vault is present and current. Trigger on phrases like "connect to the vault", "pull/sync the vault", "let's work on gartera", "hook up gartera", "new gartera chat", or any request to read/edit/audit Gartera vault files where the repo isn't already cloned in this session. This is distinct from (and hands off to) the `gartera` skill, which handles persona routing and canon rules once the vault is actually reachable — this skill's only job is getting the vault reachable in the first place. This skill does not contain the procedure — it fetches it.
---

# Connect to the Gartera vault

**This skill is a pointer, not the procedure.** The real, current procedure lives
in the private `Gmor45/Gartera-Vault` repo, in the same path this file sits at.
Copying it here would create the exact drift this whole arrangement exists to
stop — measured live on 2026-09-01, when the installed copy of this skill's
sibling (`gartera`) and `flow` were both found running weeks behind the repo,
missing rules added as recently as that same morning.

## Do this, in order

1. **Clone or pull the vault** into the session workspace:

   ```
   git clone https://github.com/Gmor45/Gartera-Vault.git ~/vault-work/Gartera-Vault
   # already present? then:
   git -C ~/vault-work/Gartera-Vault pull --ff-only
   ```

   If Cowork's custom instructions already carry a GitHub PAT for this account,
   splice it into the clone URL for this one command
   (`https://<PAT>@github.com/Gmor45/Gartera-Vault.git`) rather than writing it
   to git config or to any file, then strip it back out of the remote once the
   clone succeeds (`git remote set-url origin https://github.com/Gmor45/Gartera-Vault.git`).

2. **Read the real procedure from the clone you just made, in full, and follow
   it exactly as if it had been loaded directly:**

   ```
   ~/vault-work/Gartera-Vault/.claude/skills/gartera-connect/SKILL.md
   ```

   That file carries the actual clone-verification steps, the required git
   config (`core.hooksPath`, `core.autocrlf`, `pull.rebase`, `rebase.autostash`,
   `merge.conflictstyle`), the shared-store write protocol, and the hand-off to
   the `gartera` and `flow` pointers below. Do not summarize it or act on a
   recollection of an earlier session — read the file that is in the clone
   right now.

3. **If the repo copy of this file differs from anything you remember about
   how this skill works, the repo wins**, for the rest of the session. This
   file's only job was getting you there.

## Why this file is this short

The installed skill on Garrett's account only needs to describe *when* to
trigger — the matching happens against this description before anything is
read. Everything about *what to do* lives in the repo, fetched live, exactly
once, every session. A rule change pushed to `Gartera-Vault` is in force on the
next session that loads this pointer — no paste, no second copy to go stale.
