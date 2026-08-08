# Scryglass — 5-Minute Onboarding Guide (P1a)

For invited beta users. Everything you need to get a trustworthy answer from
Scryglass in five minutes. This is the companion to the first-run overlay
(`docs/onboarding-guide.md`); the overlay itself is three steps and never
blocks.

## 1. The fastest path to an answer

The analyst view is the app, and a next-item answer takes four clicks:

1. **Pick your champion** — the *Main champion* card up top; tap it and
   start typing.
2. **Pick your role** — the Role selector (Top / Jungle / Mid / Bottom /
   Support) defaults to Mid; set it to your real game.
3. **Add an enemy** — “+ Add” a real enemy champion, or press *vs practice
   target* for a default dummy (ranking needs an enemy roster).
4. **Press “Find best item for a slot”** — that's it.

One optional refinement, if you want a closer answer:

- **Items you already own** — fill your build slots first so the ranking
  fills the *next* slot instead of starting from zero.

## 2. Reading the ranked candidates

“Find best item for a slot” scores every legal candidate into the selected
team-fight scenario and lists them best-first:

- **Rank + item icon + name** — what to buy, with its sourced stat line.
- **Score + metric** — the candidate's value under the selected objective
  (the “Rank by” filter switches objectives).
- **Component line** — where the score comes from, per source.
- **“Use”** — applies the candidate to the slot you ranked.
- **Summary line** above the list: how many candidates were certified, the
  coverage note, and how many were withheld.

Candidates whose event order is only partially certified appear as
**Withheld · partial event order** rows — they are never ranked; treat the
mechanic as unscored until its coverage is completed.

## 3. Certainty chips legend

Every number in Scryglass carries a trust chip. The legend appears in the
analyst result column:

| Chip | Meaning | Example |
|---|---|---|
| `EXACT` | Fully sourced formula, no player-controlled options | Q damage from a wiki/game-file formula |
| `ESTIMATE` | Uses a defaulted player-controlled option | Something priced with an assumed setting |
| `BOUNDARY` | Documented but not computed mechanic | A mechanic named but deliberately not priced |
| `Withheld` | Event order only partially certified — never ranked | Best-in-slot “partial event order” rows |

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

- **Sharing:** “Share this build” in the Builds section → a permanent
  read-only link anyone with access can open (sharing is permanent).
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
| Get a next-item answer fast | Champion → role → enemy → Find best item for a slot |
| Compare two full builds | Builds section → builds A/B → compare |
| See exactly why a number is what it is | Analyst → Open event ledger → per-source rows with chips |
| Check if a number is current | Look for the STALE badge / certainty chips |
| Share a build | Share this build → copy the permanent link |
| Report that the calculator disagreed | “Did this match your game?” → No / Off by % |
