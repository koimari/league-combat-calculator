# Full-Coverage Campaign — close report

Plan: `docs/plans/2026-08-18-full-coverage-campaign.md`. Gate:
`scripts/coverage_census.py`. Receipts: `docs/coverage-census.json`,
`docs/coverage-residue.json`.

## The frontier

The census sweeps every champion × fight mode, champion × legally-slotted item,
champion × keystone, certified-item × enemy champion, a Lifeline-outliving
window, comparison curves and a BIS sample — through the real payload
boundaries, no mocks.

| Category | Opened | Closed |
|---|---|---|
| mode refusals | 12 | 0 |
| bare-kit coarse | 2 | 0 |
| item-pair failures | 832 | 0 |
| item-pair coarse | 937 | 25 |
| unmodeled keystones | 13 | 0 |
| keystone failures | 16 | 0 |
| certified-enemy withholds | 37 | 0 |
| expiry refusals | 1 | 0 |
| crossover unavailable | 4 | 0 |
| BIS errors | 4 | 0 |
| **total** | **1858** | **25** |

The 25 are acknowledged in `docs/coverage-residue.json`, each naming its slots,
the cached sentence describing those hits, and what that sentence fails to say.
The gate fails on an entry nothing acknowledges *and* on an acknowledgement
that no longer reproduces; both reds were driven before it landed.

## Gates, this session

`pytest` 10059 passed / 0 failed · `black --check` 793 files clean ·
`pylint src/` 9.62/10 unchanged · `plan_audit` 11 documents clean ·
`golden_snapshot compare` identical · census exit 0.

## What the coverage work found

Coverage was the brief; the defects were the yield. Each was invisible to every
existing gate.

| Defect | Effect |
|---|---|
| 372 packet slots served a rank-1 cooldown at every rank | Thresh Q waited 19s for 9; 39 champions gained casts, median +17% TDD |
| Nine abilities priced one leg where the cache carries the cast | Xin Zhao W served 32.5 against a true 630 |
| Eclipse's walk mis-matched rounded cast times | 234 of 237 fights **overstated**; the fallback invented procs |
| Reattribution debited a blended average, removed actual values | Coverage flipped coarse on a crit roll; 1345 of 1650 runs |
| Heal rules counted damage events, not casts | Zaahen paid twice, Naafiri's second heal vanished |
| Autos-only windows priced uncast abilities | Malzahar's Voidlings dealt 1943 with W never cast |
| Two `MODULE_CC` declarations were dead | Reviewed-looking, never read |
| A 1.14e-13 float crumb | Eight empty rows read as active coarse sources |
| Command's merge was named `EXTEND`, computed `REFRESH` | Correct behaviour, wrong name, since it shipped |

## Rulings

1. **Declaring a fact is free.** Stating a kit's crowd control reordered
   rotations and moved damage, so batches suppressed true facts. Ordering now
   comes only from declared `CAST_DEPENDENCIES`.
2. **A closed campaign measures its own commits.** Its ledger, ownership map and
   report claims all read `584071e..HEAD`, written when HEAD *was* its tip. Each
   now ends at `7e1de9e`.
3. **Command merges by refresh**, the conservative reading; the Wiki's "extend"
   is recorded as a costed divergence rather than silently adopted.
4. **A moved leaf is declared, never edited.** 19 boundary leaves moved again;
   each is superseded by a claim naming what it replaces.

## Out of contract, and why

Silent zeros — self-healing absent for ~116 champions, grey health for all but
5 — degrade without withholding, so the census cannot see them. They are the
next campaign's frontier, not this one's residue.

## Known, recorded, not fixed

`roster_composition` aside: three heal rules anchored on events were fixed;
`resource_restores` now drops a late event rather than refusing the packet.
Aatrox's sourced cadence is blocked by practice-corpus pins; Anivia's chill is
held for a reserved ruling; Darius needs a part that scales rather than repeats;
Yone's event is engine-built with no module part. Each is in the residue file.
