# Item source reconciliation (issue #86)

Resolutions recorded 2026-08-06 against patch **16.15** (game files via cdtb / Community Dragon; wiki revisions; Riot ddragon tooltips as arbiter for tooltip-vs-bin disputes).

Authority order (from `scripts/patch_regression.py`): game files (Community Dragon bin, verified against local WADs) > Riot ddragon tooltip > wiki cache revision. The wiki cache stays authoritative for **mode availability** (classic SR 5v5 flag in `data/items.json`).

## 1. Gunmetal Greaves (3172) — Noxian Gait

- **Conflict**: Riot 16.15 cache text advertised Noxian Gait (on-hit movement speed); wiki page (rev 4013706, 2026-04-29) records V26.01 removed Noxian Gait, leaving only the stat line.
- **Resolution**: **Wiki-authoritative** — Noxian Gait removed in V26.01; the game file (16.15) has no Noxian Gait branch on 3172 (verified by the P3 stat/ability regression; item flagged `noEffects=true`, stat-only). 
- **Mode availability**: classic SR 5v5 = true (a tier-3 boot).
- **Resulting coverage**: `stats_only`, optimizer-eligible — a stat boot with the Riot-only movement branch explicitly out of scope. `data/staleness.json` reports no drift on 3172.

## 2. Radiant Virtue (446667) — Judgement passive

- **Conflict**: Riot cache advertised a Judgement passive granting 30 ultimate haste; wiki page (rev 3976494, 2025-12-16) is an Arena-only entry with no Judgement branch in its item table.
- **Resolution**: **Arena-only** — the cache itself marks classic SR 5v5 = false (AR = true); the wiki agrees. The Judgement branch is not a Classic SR effect and is not selectable for SR builds.
- **Resulting coverage**: `blocked` (not reviewed for SR outgoing damage/state), optimizer-ineligible, excluded from SR selection — the correct fail-closed state for an Arena-only item.

## Gate

Both items exit the reconciliation gate with the source, revision/date, mode availability, and resulting coverage recorded above. Related: #40 (parent), #51, #85.
