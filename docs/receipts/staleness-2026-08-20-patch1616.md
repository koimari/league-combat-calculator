# Staleness receipt — 2026-08-20, patch 16.16

Command:

```bash
.venv/bin/python scripts/patch_regression.py check --patch 16.16
```

Output:

```
patch 16.16: comparing 173 champions and 324 items against game files
ddragon tooltip arbitration (16.16.1): 46 champions
stale: 5 champions, 6 items -> data/staleness.json
```

**Exit code: 1** (per `patch_regression.py check`'s documented behavior:
exits 1 when anything is stale — this is the honest current state, not a
gate the task asked to clear).

## Champions: 5 stale, all boundary-documented

`data/staleness.json` flags 5 champions. Every one traces to a stat/row
already recorded as a deliberate, documented boundary in the champion
module's `ASSUMPTIONS` — none is a new, unattributed drift.

| Champion | Stale field | Cached vs game | Documented at |
| --- | --- | --- | --- |
| AurelionSol | Q[0] cost drifted | wiki mana row `8.75/10/11.25/12.5/13.75` vs bin/ddragon `35/40/45/50/55` | `src/calculator/champions/aurelion_sol.py` `ASSUMPTIONS` (lines ~450-461): documents the wiki's Q "cost" row is not the mana cost — a known-degraded parse, not a patch-day change |
| Mel | W[0] cooldown drifted | cached `32` vs bin `[38,38,35,33,29,26,26]` / ddragon `33` at the compared rank | `src/calculator/champions/mel.py` `ASSUMPTIONS` (lines ~254-261): "KNOWN CACHE LAG... W (Rebuttal)'s cached cooldown row is [32]... both say 33, not 32" — `extract_cooldown` reads dynamically, no hardcoded value to fix |
| Nilah | E[0] cost drifted | cached flat `30` at every rank vs bin/ddragon `40` | `src/calculator/champions/nilah.py` `ASSUMPTIONS`: "KNOWN CACHE LAG (verified 16.16.1, not fixed here...): E (Slipstream)'s cached cost row is flat 30 at every rank; the game files say 40" |
| Soraka | W[0] cost drifted | cached `10%` health-only row vs bin mana `[40,45,50,55,60]` / ddragon costBurn `40/45/50/55/60` | `src/calculator/champions/soraka.py` `ASSUMPTIONS`: W is a dual-resource cast (10% current health + mana); the wiki cache never captured the mana leg under any key — a known-degraded wiki parse |
| Kled | `movespeed.flat` 305→345, `attackRange.flat` 250→125 (champion-level `stat_drift`, not an ability row) | `data/champions.json` carries the DISMOUNTED row; the 16.16 game file `CharacterRecords/Root` carries the MOUNTED row | `src/calculator/champions/kled.py` `ASSUMPTIONS`: "Base movement speed and attack range are FORM-ATTRIBUTED, not stale... The wiki's own P[1] text reconciles them exactly" |

Verification method: `compare_ability_rows`/`build_staleness` were called
directly (in-process, same code path `scripts/patch_regression.py check`
uses, including the two-pass ddragon-arbitration flow for `cost`/`cooldown`
rows) against just these 5 champions to read the full, untruncated
row-notes list — the committed `staleness.json` `note` field is capped at
the first 3 row notes (`patch_regression.py:892`, `notes.extend(row_notes[:3])`),
which does not always include the actual stale row. All 5 stale rows above
were confirmed this way and cross-checked word-for-word against each
module's `ASSUMPTIONS` text.

No new, unattributed champion staleness was found. `ability_rows_stale` is
exactly 1 for AurelionSol/Mel/Nilah/Soraka and 0 for Kled (Kled's staleness
is entirely the two `stat_drift` fields).

## Items: 6 stale, all documented off-map Arena drift

All 6 stale item IDs match `docs/item-source-reconciliation.md` §3
("Off-map stat drift — six Arena records (16.16.1 re-pull)") exactly —
same IDs, same cached-vs-game deltas:

| Item | ID | Cached → game (16.16) |
| --- | --- | --- |
| Hellfire Hatchet | 4017 | attackDamage 35 → 40 |
| Spectral Cutlass | 224004 | attackDamage 50 → 60; lethality 15 → 21 |
| The Golden Spatula | 224403 | health 350→250; mana 350→250; armor 40→30; magicResistance 40→30; omnivamp 15%→10% |
| Hexbolt Companion | 443081 | attackSpeed 75 → 50 |
| Prowler's Claw | 446693 | attackDamage 55 → 60 |
| Diamond-Tipped Spear | 447120 | attackSpeed 30 → 40 |

Per §3, all six have `modes["classic sr 5v5"] = false` — Arena-only, off
Summoner's Rift build surface entirely (`item_source.audit_scope(...).in_scope
== False`). §3 documents this as a **known, standing gap**: the wiki's Arena
item pages lag the game files (identical flags were already present in the
committed 16.15 `staleness.json`), and `patch_regression.py` compares every
cached item including off-map ones, so these six are permanent false
positives until the item compare is scoped to `in_scope` items (explicitly
deferred to a separate, reviewed commit per §3's "Known gap" note — not
addressed here).

## Summary

`stale: 5 champions, 6 items`, exit 1. All 11 stale entries are boundary-
documented (5 champion `ASSUMPTIONS` entries, 6 item off-map records in
`docs/item-source-reconciliation.md` §3) — none represents new,
unattributed drift from this session's re-pull. `data/staleness.json` was
written honestly (not hand-edited) by `scripts/patch_regression.py check`
itself, per the runbook's "never hand-edit staleness.json" rule.
