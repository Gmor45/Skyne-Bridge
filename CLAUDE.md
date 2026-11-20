
## The Skyne Family

<!-- skyne-family: pointer, written by Skyne's govern.py fix. Do not list members here. -->
This product's personas are the Skyne Family. Who they are, and what each one
does HERE, is deliberately not written in this repo: a copy drifts. Read it
from `data/skyne-family.json` in Gmor45/Skyne: `family` for the members,
`cells.bridge` for what each one does in this product. A session reaches
it as `../Skyne/data/skyne-family.json` (a sibling clone) or through the Skyne
connector's `read_note`. The card's version this repo was last brought to is
`family_version` in `.governance.json`; Skyne's `govern.py drift` says when it
is behind.

The W agents (`load-house-rules:wince` and the rest) come from Skyne-Bridge's
plugin. A session without that plugin has no W agent types: say so in one line,
rather than running a generic agent and calling it a W.
