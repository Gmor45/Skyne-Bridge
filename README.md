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
