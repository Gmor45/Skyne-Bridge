---
name: web-standard
description: "The Web Standard: the one list of rules every one of Garrett's websites is built and graded against (Bluelink, Tangle, Sourced Ballot, Third Eye, Hearth, the Skyne sites). Load BEFORE writing or editing any web page, stylesheet, page script or page template in any repo, before designing a screen, and before trying (Wren) or grading (Wince) a site. A hook refuses website edits until this has been opened. Cite rules by number (L3, R2, P1)."
---

# The Web Standard

Ruled 2026-11-20 (Garrett: "go"). Plan of record: Gmor45/Skyne
`handoffs/full/2026-11-20-website-standard-plan.md`; rulings in Skyne
`DECISIONS.md` 2026-11-19 and 2026-11-20.

**Who uses it.** Wick (the main chat) builds to it. Wren tries a site
against it. Wince grades against it. All three cite the rule number.

**Where your taste wins.** Garrett's taste comes first (the L rules, from
Skyne `.claude/skills/house-rules/DESIGN.md` and `.claude/rules/ui.md`).
The published standards add the rest. Where they disagree, taste wins,
**except where WCAG 2.2 AA makes it pass/fail** (the R rules). DESIGN.md
stays the full record of taste; this file is the short version that
loads in every repo. Skyne's `check_web_standard_sync.py` fails if the
two drift on the numbers below.

**How a site is graded.**
1. **Automatic check, every pull request.** `web_check.mjs` (this repo,
   `scripts/web_check/`) runs axe plus the rules marked *auto* below, at
   phone width (390px) and at 2560px, in light and dark. A site's known
   problems sit in its `.web-check/baseline.json`; the check fails when
   any count goes UP. Machines catch about half of accessibility
   problems (Deque's study: 57% by count), so a pass means "nothing a
   machine can see", never "good".
2. **Two separate reviews, once, when a website pull request opens**
   (RULED 2026-11-19). Wince and Wren each mark every rule pass or fail
   and rate each problem 0 (not a problem) to 4 (catastrophe), without
   seeing each other's notes. Two reviewers is under Nielsen's three;
   that weak spot is known, not hidden.
3. **Tryouts with real people** before a site goes to strangers: 3 to 5
   people of one type, thinking out loud, one hint allowed, one 7-point
   "how easy was that" question. Sourced Ballot is skipped for the
   Dec 1 runoff (RULED 2026-11-20).

---

## L. Look (Garrett's taste)

- **L1** Colors come from the site's tokens file, never a hex typed into a
  page, style or script. *(review)*
- **L2** Red means trouble, and only trouble. A choice, a reject or a
  delete button is not red; a costly action asks first or can be undone.
  *(review)*
- **L3** Corners are 8, 14 or 22px, or a full pill (999). Nothing in
  between. Hairlines of 2 to 6px on tiny marks are allowed. *(auto)*
- **L4** Use the width. A single column on a 2560px screen is a bug;
  reach for `repeat(auto-fit, minmax(340px, 1fr))`. Boards have no max
  width; only running prose is capped, at about 75 characters. A page
  that is prose on purpose says so with `data-layout="prose"` on `<main>`.
  *(auto)*
- **L5** Every dashboard is tiles the reader can drag and resize, using
  the one shared engine (`gridlayout`), with each person's layout kept on
  their device and a "Reset layout" control. Phones stack. *(review)*
- **L6** A box means "this is one thing", never decoration. No boxes
  inside boxes for looks ("card soup"). *(review)*
- **L7** Light and dark. The page follows the device's own setting
  (`prefers-color-scheme`), and a toggle marked `data-theme-toggle`
  overrides it and remembers the choice in `localStorage`. Both color sets
  are contrast-checked. *(auto: the page must change with the setting, and
  the toggle must exist)*
- **L8** Motion only when it carries information. Feedback about 100ms,
  panels 200 to 300ms, nothing over 400ms. Respect
  `prefers-reduced-motion`. *(review)*
- **L9** The finding goes in words above the picture, computed from the
  same numbers the picture draws. Never make the reader decode a legend.
  *(review)*
- **L10** A list is not a picture. If the data has a shape (an order, a
  graph, a spread), draw the shape. *(review)*

## U. Use (Nielsen's heuristics)

- **U1** After every click, the page shows something changed within a
  tenth of a second. *(review)*
- **U2** The reader's words, not the builder's: no code, file names,
  GitHub links or jargon on screen. *(review)*
- **U3** Every action can be undone, or asks first when it cannot.
  *(review)*
- **U4** The same thing has the same name and the same place on every
  page. *(review)*
- **U5** Stop errors before they happen: disable what cannot work,
  confirm what destroys. *(review)*
- **U6** Show the options; never make the reader remember them from an
  earlier screen. *(review)*
- **U7** An error says, in plain words next to the field, what went wrong
  and how to fix it. *(review)*
- **U8** An empty state says why it is empty and what to do next.
  *(review)*
- **U9** Hold still: nothing moves, re-sorts or animates that the reader
  did not touch. Mark what changed in words on the item. *(review)*
- **U10** Would anyone miss it? Cut what nobody would. *(review)*

## G. Grouping (Gestalt)

- **G1** The most important thing on the screen is first and biggest.
  *(review)*
- **G2** Things that belong together sit closer to each other than to
  anything else. *(review)*
- **G3** Things that do the same job look the same; things that differ
  look different. *(review)*
- **G4** Spacing comes from the 4 / 8 / 12 / 16 / 24 ladder. *(review)*

## R. Reach (WCAG 2.2 AA: pass/fail, beats taste)

- **R1** Keyboard only works: Tab reaches every control, the focus ring
  is always visible, and a sticky bar never hides it (2.1.1, 2.4.7,
  2.4.11). *(partly auto)*
- **R2** Anything you can drag also has a plain-click way to do it
  (2.5.7). Arrow keys do not count. Tiles get an "Arrange" button, built
  once in the shared engine. *(review)*
- **R3** Text is readable: 4.5 to 1 against the surface it actually sits
  on (3 to 1 for text 24px, or 18.66px bold), in light AND dark (1.4.3).
  *(auto)*
- **R4** Controls and marks reach 3 to 1 against what is next to them
  (1.4.11). *(partly auto)*
- **R5** Color is never the only signal; red always comes with a word
  (1.4.1). *(review)*
- **R6** At 200% zoom, and at a 390px phone width, nothing is cut off and
  nothing scrolls sideways (1.4.4, 1.4.10). *(auto at phone width)*
- **R7** Every image has alt text and every control has a name a screen
  reader can say (1.1.1, 4.1.2). *(auto)*
- **R8** Sign-in never blocks pasting a code or a password manager, and
  never asks a puzzle (3.3.8). *(review)*
- **R9** The page has a language, a title, and headings in order (3.1.1,
  2.4.2, 1.3.1). *(auto)*
- **R10** No information only in a tooltip: a `title` never shows on a
  phone. *(review)*

## P. Phone (Apple and Material, where they agree)

- **P1** Everything clickable is at least **44px** by 44px, on every
  screen size (Garrett, 2026-11-19). Tight lists and board rows grow to
  44px tall. Links inside a sentence are exempt. *(auto)*
- **P2** Form inputs are 16px text or larger, or iOS zooms the page.
  *(auto)*
- **P3** Every screen is designed for the phone AND the computer from
  the start; checks run at both widths. *(auto)*
- **P4** A sidebar folds under 980px; tiles stack under 820px and do not
  drag. *(review)*
- **P5** A draggable area uses `touch-action: pan-y`, never `none`, which
  steals the page scroll. *(auto)*

## S. Plumbing (one recipe per need)

- **S1 Sign-in.** Cloudflare Access (Google or an emailed code). The
  app's own member list is the ONE list anyone edits; a script copies it
  to Access. A check warns when all sites together pass **40 of the 50**
  free seats; that is the signal to move a site to in-app sign-in
  (Better Auth), never to pay per seat (RULED 2026-11-20).
- **S2 Public forms.** Cloudflare Turnstile, a hidden trap field, a
  per-address speed limit, and a daily cap. No picture puzzles.
- **S3 Publishing.** A merge to main publishes the site automatically
  through Gmor45/cloudflare-deploy, with no approval step (RULED
  2026-11-20). One merge starts exactly one publish (it carries a request
  id and checks that one run carries it). A signed-in site's lock is
  checked BEFORE the new version goes live.
- **S4 Payments** wait for a lawyer and Stripe's rules for political
  groups. When they come: Stripe is the truth about money, amounts are
  stored in cents, every Stripe message is signature-checked and counted
  once.
- **S5 Privacy.** No account opens to people who are not on a list until
  the site has a privacy page.

---

## What the automatic check reports

Each finding names its rule. `axe:<id>` comes from axe (R rules);
`tap-44` is P1, `radius` is L3, `input-16` is P2, `h-scroll` is R6,
`touch-none` is P5, `one-column` is L4, `no-light-dark` and
`no-theme-toggle` are L7. A count that drops is good news: lower the
baseline in the same pull request (`--update-baseline`).
