# Archived agent files (2026-11-16)

Garrett ruled on 2026-11-16 (skyne DECISIONS, R2 and R8) that only three of the
nine W names keep an agent file. The other six stay as **labels** a reply
speaks under (house-rules 32), but they no longer exist as subagents.

| Archived file | W | What it did | Who does the job now |
|---|---|---|---|
| ward.md | Ward | keeps data and structure tidy | the main session, under the `Ward:` label |
| warden.md | Warden | runs and builds checks | the main session, under the `Warden:` label |
| weir.md | Weir | tees up a decision | the main session, under the `Weir:` label |
| whittle.md | Whittle | retires what no longer flows | the main session, under the `Whittle:` label |
| wick.md | Wick | draws and lays out | the main session, under the `Wick:` label |
| wistin.md | Wistin | makes new things | the main session, under the `Wistin:` label |

Still live in `.claude/agents/`: `wince`, `wren`, `wander`, and `haiku-mechanic`
(which is not a W).

These files were moved with `git mv`, never deleted. To bring one back, move it
back to `.claude/agents/`, add its name to `AGENT_FILES` in `tier_gate.py` and
`w_ran.py`, and bump the plugin version (versions only move forward).
Claude Code loads agents only from `.claude/agents/`, so nothing in this folder
is ever offered to a chat.
