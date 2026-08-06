# Scryglass — 5-Minute Onboarding Guide (P1a)

For invited beta users. Everything you need to get a trustworthy answer from
Scryglass in five minutes. This is the guide the first-run overlay points to
(`docs/onboarding-guide.md`); the overlay itself is three steps and never
blocks.

## 1. The quick mode 3-click path

Quick mode is the landing page and the fastest way to an answer. It takes
exactly three clicks:

1. **Pick your champion** — start typing in *Your champion*, then tap the
   champion when it appears.
2. **Pick your role** — the segmented control (Top / Jungle / Mid / Bottom /
   Support) defaults to Mid; set it to your real game.
3. **Press “Best next item”** — that's it.

Two optional refinements between steps 2 and 3, if you want a closer answer:

- **Enemy** (optional) — search a real enemy champion instead of the default
  practice target.
- **Items you already own** (optional) — add your current build so the
  recommendation fills the *next* slot instead of starting from zero.

The “Quick” tab hint says *3 clicks* because champion, role, and the run
button are the only required steps.

## 2. Reading the top-3 cards

“Best next item” simulates each candidate in the slot against your current
build and shows the three best as cards, ranked 1-3:

- **Rank + item icon + name + gold** — what to buy and what it costs.
- **TDD delta** — how much total damage the item adds to your rotation,
  relative to your current build (green `+`, red `-`).
- **eHP delta** — how much effective health it adds against your selected
  enemy (durability / survival).
- **The “why” line** — a plain-language reason: e.g. *“Bypasses the enemy's
  heavy magic resistance”*, *“Biggest single-slot damage gain (+1234 TDD)”*,
  *“Adds durability — your current build is fragile here”*.
- **Baseline line** under the cards: your current build's TDD and eHP before
  adding an item, so the deltas have context.

If a candidate list carries a `PARTIAL` chip (coupled multi-enemy rosters),
the event order is only partially certified — treat the scores as estimates
until the roster is re-certified.

## 3. Certainty chips legend

Every number in Scryglass carries a trust chip. The legend appears in both
modes (quick after-row and analyst result column):

| Chip | Meaning | Example |
|---|---|---|
| `EXACT` | Fully sourced formula, no player-controlled options | Q damage from a wiki/game-file formula |
| `ESTIMATE` | Uses a defaulted player-controlled option | Something priced with an assumed setting |
| `BOUNDARY` | Documented but not computed mechanic | A mechanic named but deliberately not priced |
| `PARTIAL` | Coupled-roster event order only partially certified (quick mode) | 4v4 preset scores |

The model fails closed: unmodelled mechanics are *named*, never silently
zeroed. If you see a chip you don't understand, hover it for the tooltip.

## 4. The STALE badge

After a League patch, wiki/game-file caches drift from what actually shipped.
A **`STALE · PATCH x.y`** badge (champion heading) or **`STALE`** badge (item
slot) means that entity's numbers were verified against an older patch than
the live game.

What to do:

- **Treat stale numbers as approximate** — prefer non-stale items/roster
  members for decisions that matter.
- **Report it** — the badge is also the ops team's patch-day trigger
  (`docs/patch-day-runbook.md`); a re-cert normally lands within 72h.

## 5. Share links

- **Quick mode:** after a result, “Share this build” → a permanent read-only
  link anyone with access can open (sharing is permanent).
- **Analyst:** “Share this build” in the Builds section works the same way.
- **Reading a shared link:** `?share=<token>` renders the build read-only
  with a banner; “Open in editor” loads it back into the full calculator.

## 6. The feedback widget — “did this match?”

In the analyst result column, the **“Did this match your game?”** widget
records a game receipt against the exact loadout on screen:

- **Yes / No / Off by %** — confirm the prediction, or report the damage you
  actually saw and how far off it was.
- **Paste a combat log** — import observed damage lines instead of typing.
- Every receipt is stored with the loadout snapshot (champion, level, role,
  items, ability ranks, fight window), so a mismatch can be triaged as a
  calculator bug, a practice error, or a context mismatch — never just
  discarded.

Receipts feed the validation corpus (`docs/beta-operations.md` step 4-5);
flagged champions (≥5 receipts, >±15% bias) open a tracking issue.

## 7. What to do on patch day

1. **Watch for STALE badges** — they appear automatically the first time the
   staleness report (vs the new patch) is fetched.
2. **Don't hard-code the old numbers** — the badge is the signal that the
   calculator's cache is behind; the ops team re-pulls and re-certifies.
3. **If you spot a bad number with no badge**, use the feedback widget and
   mention the patch — it routes to the same triage.
4. **Recertification SLA:** detection < 4h, triage < 24h, full re-cert
   < 72h after the patch ships (see `docs/patch-day-runbook.md`).

## Cheat sheet

| I want to… | Do this |
|---|---|
| Get a next-item answer fast | Quick mode: champion → role → Best next item |
| Compare two full builds | Analyst tab → builds A/B → compare |
| See exactly why a number is what it is | Analyst → Open event ledger → per-source rows with chips |
| Check if a number is current | Look for the STALE badge / certainty chips |
| Share a build | Share this build → copy the permanent link |
| Report that the calculator disagreed | “Did this match your game?” → No / Off by % |
