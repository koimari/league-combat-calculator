# Golden baseline recapture — 2026-08-20 (patch 26.16 wiki re-pull, integration close-out)

This recapture follows the stage-1 audit performed earlier the same day (see
`docs/receipts/golden-recapture-2026-08-20.md` for the prior 26.15/16.16.1
recapture already sitting in `scripts/golden_baseline.json` at the start of
this session). This session's `data/champions.json` / `data/items.json`
re-pull moved `patch_last_changed_max` from `26.15` to `26.16`; this receipt
covers only the diffs introduced by *that* re-pull.

Gate command:

```bash
.venv/bin/python scripts/golden_snapshot.py compare scripts/golden_baseline.json
```

## Pre-recapture compare result

**67 differences**, matching the stage-1 audit's pre-attribution exactly
(count and shape both verified before recapturing — see Verification below).

## Cluster table

| # | Root cause | old → new | Source of truth | Diffs |
| --- | --- | --- | --- | --- |
| A | **28-champion marksman MR rework** — base MR `30 → 33`, per-level growth `1.3 → 1.1` (Tristana joins the marksman MR curve from a different old base: `28 → 33`) | `magic_resistance` at levels 1 and 11 (Tristana also moves at level 18) | `data/champions.json` `stats.magicResistance` | **57** |
| B1 | **Bel'Veth** `health.perLevel` | `110 → 105` | `data/champions.json` Belveth stats | **4** |
| B2 | **Camille** `mana.flat` | `339 → 375` | `data/champions.json` Camille stats | **3** |
| C | Fiddlesticks Q duration `2.5 → 2.25` | — | `data/champions.json` | **0 (did not surface)** |
| D | Metadata | `champions_fetched_at`, `items_fetched_at`, `patch_last_changed_max` (`"26.15" → "26.16"`) | `data/.*.meta` / snapshot metadata | **3** |
| | | | **Total** | **67** |

Cluster C is listed because the stage-1 audit flagged it as a possible
diff source; it did not appear in the actual 67-path diff set, consistent
with the audit's "if it surfaces" hedge — Fiddlesticks Q duration is not a
golden-snapshot output field (cooldown/duration metadata isn't part of the
damage-model snapshot), so a duration-only change producing zero diffs is
expected, not a gap.

## Cluster A — 28-champion marksman MR rework, worked arithmetic

Base MR at level 1 for 27 of the 28 champions moves `30 → 33` (a flat `+3`);
at level 11 the accumulated per-level growth changes the delta because the
growth rate itself changed (`1.3 → 1.1` MR/level):

```
old level 11: 30 + 1.3 * 10 * (0.7025 + 0.0175*10) = 30 + 13*0.8775 = 30 + 11.4075 -> 41 (rounded)
new level 11: 33 + 1.1 * 10 * (0.7025 + 0.0175*10) = 33 + 11*0.8775 = 33 + 9.6525  -> 43 (rounded, matches observed 41 -> 43)
```

(Using the stat-growth formula from `CLAUDE.md`: `base + growth * (level-1)
* (0.7025 + 0.0175*(level-1))`.)

Affected champions (27, base `30 -> 33`, `41 -> 43` at level 11): Akshan,
Aphelios, Ashe, Caitlyn, Corki, Draven, Ezreal, Graves, Jhin, Jinx, Kaisa,
Kalista, Kindred, KogMaw, Lucian, MissFortune, Quinn, Samira, Senna, Sivir,
Smolder, Twitch, Varus, Vayne, Xayah, Yunara, Zeri — each contributes 2 diff
paths (`stats/1/magic_resistance`, `stats/11/magic_resistance`) = **54**.

**Tristana is the odd one out**: her old base MR was already `28` (not the
marksman-default `30`), so she moves `28 -> 33` at level 1 and `39 -> 43` at
level 11 — both consistent with landing on the same new `33` base / `1.1`
growth curve as the other 27. She additionally shows a level-18 diff
(`50 -> 52`) because her level-18 snapshot happens to round differently
under the new curve; the other 27 champions' level-18 MR rounds identically
old vs. new and produces no diff. Tristana contributes 3 diff paths.

Total cluster A: `54 + 3 = 57`, matching the observed diff set exactly (no
unattributed marksman appeared, no expected marksman was missing).

## Cluster B — Bel'Veth health growth, Camille mana base

- **Bel'Veth** `health.perLevel 110 -> 105` moves `base_health`/`health` at
  levels 11 and 18 only (level 1 has zero elapsed levels, so `perLevel` does
  not contribute) — 2 fields x 2 levels = **4** diff paths.
- **Camille** `mana.flat 339 -> 375` moves `max_mana` at all three snapshot
  levels (1, 11, 18) since it is the base term in the mana growth formula at
  every level — **3** diff paths.

## Cluster D — metadata

`champions_fetched_at` and `items_fetched_at` are re-pull wall-clock
timestamps (expected to move on every re-pull) and
`patch_last_changed_max` moved `"26.15" -> "26.16"`, confirming this re-pull
picked up the new patch's wiki `patchLastChanged` fields.

## Verification

Diff-list cross-check performed before recapturing: every one of the 67
observed diff paths falls into exactly one of clusters A/B1/B2/D above (28
champions x {1,2, or 3 fields} for magic_resistance, 4 Bel'Veth health
paths, 3 Camille mana paths, 3 metadata paths); zero paths outside these
clusters; zero clusters silently absent from the diff (Fiddlesticks
correctly produced 0, as hedged).

```
.venv/bin/python scripts/golden_snapshot.py capture scripts/golden_baseline.json

.venv/bin/python scripts/golden_snapshot.py compare scripts/golden_baseline.json
  OK: snapshot identical to scripts/golden_baseline.json   (exit 0)
```

`jq empty scripts/golden_baseline.json` passes.

## Scope note

This receipt covers only the 67-diff delta introduced by this session's
wiki re-pull (26.15 -> 26.16 `patchLastChanged`). It layers on top of the
already-uncommitted 26.15/16.16.1 recapture documented in
`docs/receipts/golden-recapture-2026-08-20.md`; `scripts/golden_baseline.json`
has not been committed at any point in this cycle, per the task's
do-not-commit instruction.
