# Golden baseline recapture — 2026-08-20 (patch 26.15 / client 16.16.1)

`scripts/golden_baseline.json` was re-captured after the 16.16.1 cache re-pull
and the sourced `item_effects.py` value updates. The pre-recapture compare
failed with **330 differences**; every one is attributed below to a specific
sourced data or sourced-constant change. No diff was accepted as unexplained.

Gate command:

```bash
.venv/bin/python scripts/golden_snapshot.py compare scripts/golden_baseline.json
```

## Attribution method

Attribution was not eyeballed from the diff text. Three snapshot runs were
executed with the **current code** against controlled data directories, and
each diff path was assigned by set membership:

| Run | Data | Purpose |
| --- | --- | --- |
| 1 | all-old `champions/items/runes.json` | isolates **code**-driven diffs |
| 2 | new `champions.json` + old `items.json` | isolates **champion-data** diffs |
| 3 | new `items.json` + old `champions.json` | isolates **item-data** diffs |

Run 1 reproduced the previous baseline exactly **except for 6 paths**, and
those 6 are precisely the three items whose constants moved in
`item_effects.py`. That is the load-bearing result: it proves the pipeline
code is not regressed, and that the other 324 diffs are data-driven.

The union of the three attributed sets equals the full 330-path diff set
exactly — 0 unattributed paths, 0 attributed paths absent from the real diff.

## Cluster table

| # | Root cause | old → new | Source of truth | Diffs |
| --- | --- | --- | --- | --- |
| A | **Berserker's Greaves** `stats.attackSpeed.flat` | `25.0 → 30.0` | `data/items.json` | **173** |
| B | **Kennen R** bolt damage + AP ratio | `40/75/110 → 40/80/120`; `22.5% → 25% AP` (bonus resists `20/40/60 → 25/50/75`) | `data/champions.json` | **38** |
| C | **Poppy** base stats | `attackDamage.flat 60 → 56`; `mana 280 (+40/lvl) → 300 (+45/lvl)`; `healthRegen.flat 8 → 9` | `data/champions.json` | **38** |
| D | **Camille W** cooldown + outer-cone | cd `15/14/13/12/11 → 12/11.5/11/10.5/10`; cone `6/6.5/7/7.5/8% → 7/7.5/8/8.5/9%` max HP | `data/champions.json` | **35** |
| E | **Azir Q** base magic damage | `60/80/100/120/140 → 75/95/115/135/155` | `data/champions.json` | **34** |
| F | **Eclipse** Ever Rising Moon | max-HP `melee 6→8%`, `ranged 4→5%`; shield `160/80 → 150/75` | `item_effects.py` (sourced) | **2** |
| G | **Sterak's Gage** base-AD→bonus-AD | `0.45 → 0.5` | `item_effects.py` (sourced) | **2** |
| H | **Sunfire Aegis** immolate bonus-HP/s | `0.01 → 0.015` | `item_effects.py` (sourced) | **2** |
| I | **Black Cleaver** `stats.attackDamage.flat` | `40.0 → 45.0` | `data/items.json` | **2** |
| J | **Tiamat** `stats.attackDamage.flat` | `20.0 → 25.0` | `data/items.json` | **2** |
| K | **Spellslinger's Shoes** `magicPenetration.flat` | `18.0 → 20.0` | `data/items.json` | **1** |
| L | Cache fetch timestamps | `champions_fetched_at`, `items_fetched_at` | `data/.*.meta` | **2** |
| | | | **Total** | **330** |

Cluster sums list 331; one path,
`/registered_champion_fights/Azir/18/sustained/spellblade_build/total_damage`,
is caused by **both** A and E (Azir's Q buff and the Berserker's AS change
land in the same scenario total) and is counted once.

## Cluster A — Berserker's Greaves, the 173-diff dominant cluster

The spellblade build is `["Trinity Force", "Infinity Edge", "Berserker's
Greaves"]`. Trinity Force and Infinity Edge have **zero** stat changes this
patch, so the sole changed input to that build is Berserker's Greaves
attack speed `25 → 30`.

This is **not** a uniform ×1.20 damage multiplier. The observed ratios are
quantized small-integer fractions — `4/3`, `5/4`, `6/5`, `7/6`, `8/7`,
`10/9`, `2/1` — the signature of the **integer auto-attack count** in the
5-second sustained window (`ONE_ROTATION_DURATION = 5.0`) stepping up by
exactly one as `floor(attack_speed × 5)` crosses a boundary. Worked examples:

| Champion | old AS | old `AS×5` | new AS | new `AS×5` | autos |
| --- | --- | --- | --- | --- | --- |
| Alistar 18 | 1.1945 | 5.973 | 1.2258 | 6.129 | 5 → 6 |
| Braum 18 | 1.3814 | 6.907 | 1.4136 | 7.068 | 6 → 7 |
| Akshan 11 | 0.9984 | 4.992 | 1.0184 | 5.092 | 4 → 5 |

Only champions sitting just below an integer boundary move, which is why
167 of ~332 sustained-spellblade scenarios changed rather than all of them.

Three sub-cases inside cluster A that are **not** plain auto-count steps:

- **Bel'Veth, 6 one-rotation diffs (no autos).** Her E (Royal Maelstrom)
  slash count reads `bonus_attack_speed` directly
  (`src/calculator/champions/belveth.py:103` — *"E's slash count reads
  bonus_attack_speed"*), so E and `on_hit_ability_R_onhit` move even with
  `auto_attack_uptime=0.0`. Ratio `329.08 → 376.09` = `8/7`, again an
  integer strike-count step.
- **Jhin, ratios ≈1.010 / 1.008.** Jhin's attack speed is locked (`0.625`
  both before and after), but Whisper converts bonus AS into AD at
  `0.30 × bonus_as` (`src/calculator/champions/jhin.py:69`). `+5` bonus AS
  → `+1.5%` AD → the sub-1% damage rise. His auto *count* is unchanged.
- **Vayne 18, `auto_attacks 0.0 → 243.8`.** Not a zero-division artifact.
  At level 18 every auto in the window was Q(Tumble)-empowered and
  therefore attributed to the `Q` breakdown key, leaving the plain
  `auto_attacks` bucket at `0.0`. The extra auto granted by the AS increase
  falls outside Tumble's cooldown, so it lands unempowered in
  `auto_attacks`. Her `on_hit_ability_W` (Silver Bolts, every third hit)
  moves `400.0 → 466.67` = exactly `7/6`, consistent with 6 → 7 total hits.

## Champion clusters B–E: affected keys match the changed field

Per-champion diff keys line up exactly with the field that moved; nothing
bleeds into unrelated abilities. `16 = 4 builds × 2 levels × 2 fight modes`.

| Champion | Affected breakdown keys | Shape |
| --- | --- | --- |
| Azir | `Q` ×16, `total_damage` ×16, baselines ×2 | Q-only |
| Camille | `W` ×16, `total_damage` ×16, baselines ×3 | W-only |
| Kennen | `R` ×16, `total_damage` ×16, `shadowflame_Shadowflame` ×4, baselines ×2 | R + its Shadowflame rider (magic build only, 2 levels × 2 modes) |
| Poppy | `auto_attacks` ×8, `total_damage` ×8, `spellblade_Trinity Force` ×2, `on_hit_Kraken Slayer` ×2, baselines ×18 | AD-driven only (sustained only — one-rotation has no autos) |

Camille's baseline `W` reconciles arithmetically at **rank 1**: base `60` +
outer cone `6% × 2000 = 120` → `180`, and `60 + 7% × 2000 = 200` → matching
`180.0 → 200.0`, with cooldown `15.0 → 12.0` independently confirming rank 1.

Poppy's mana and health-regen changes appear only in `champion_baselines`
stats; they do not feed the damage model, which is why her fight diffs are
purely the `60 → 56` base-AD consequence (and are *decreases*).

## Sourced changes that correctly produced NO diff

Eight champions had numeric `stats` / `leveling` / `cooldown` changes; only
four produced diffs. The other four are accounted for:

- **Bel'Veth R** — `Increased Total Attack Speed 5/15/25% → 6/13/20%`. This
  is the True Form sub-state, gated behind the `true_form` option
  (`belveth.py:265`), which defaults off; the snapshot passes
  `champion_options=None`. Not exercised.
- **Gwen P** — the changed rows are the heal cap (`10:25 → 12:40`, wiki-
  labelled "Bonus Damage") and heal ratio (`50% → 67%`). Healing is not a
  snapshot output. The anti-minion "Bonus Magic Damage" row is unchanged.
- **Lissandra E** — cooldown *values* identical (`24/21/18/15/12`); only a
  parser artifact in `units` (`"}" → ""`) changed.
- **Corki P** — an effect entry split out of `notes` with empty `leveling`;
  no numeric change.
- **Camille P** (cooldown `18/14/10 → 14/11/8`) and the passive shield
  `20% → 10/15/20% (based on level)` are shield/utility, not damage.

Likewise **Runaan's Hurricane** `secondary_ad_ratio 0.55 → 0.65` in
`item_effects.py` produces no diff: the snapshot fight is single-target, so
the `secondary_target` path never fires.

## Verification

```
.venv/bin/python scripts/golden_snapshot.py capture scripts/golden_baseline.json
  champions: 173  registered: 173  items swept: 324  sweep errors: 0

.venv/bin/python scripts/golden_snapshot.py compare scripts/golden_baseline.json
  OK: snapshot identical to scripts/golden_baseline.json   (exit 0)
```

`git diff --numstat scripts/golden_baseline.json` → `331 331`, i.e. the 330
attributed value changes plus `metadata/git_head`. No keys added or removed;
`item_count` stays 324, `item_sweep_error_count` stays 0, and
`build_substitutions` stays empty — so no item silently dropped out of the
sweep or out of a build. `jq empty scripts/golden_baseline.json` passes.

## Open risk — not a blocker for this recapture

**Poppy's Q nerf is not reflected in the calculator.** `data/champions.json`
moved Poppy Q's bonus-AD ratio `100% → 75%`, but Poppy is the one
packet-backed module among the changed champions (`poppy.py` pins
`PACKET_SHA256`), so her Q is priced from `static/reviewed-packets.json` —
which was **not** regenerated by this pull and is unmodified on this branch.
Her base-stat changes flow through (stats come from `champions.json`), which
is why `auto_attacks` moved while `Q` did not.

This is pre-existing architecture (reviewed packets are deliberately frozen
and human-reviewed), not a regression introduced here, and it leaves no diff
unexplained. But the recaptured baseline now locks in a Poppy Q value that
the 26.15 wiki data has moved away from. Refreshing the Poppy reviewed
packet is follow-up work and will require its own golden recapture.

## Addendum — Poppy reviewed-packet refresh (2026-08-20, follow-up)

The open risk above is now closed. `static/reviewed-packets.json`'s Poppy
entry was regenerated from the current `data/champions.json` (sha256
`77f8cce3...b0d`, matching the 16.16.1 pull already used everywhere else)
via the repo's own `scripts/build_reviewed_modules.py`, and `poppy.py`'s
`PACKET_SHA256` pin was updated to match.

### Drift found (two fields, not one)

The original diagnosis (bonus-AD ratio 100% -> 75%) was half the story.
Comparing the stale packet entry against the current `data/champions.json`
Q ("Physical Damage") leveling row surfaced a second, independent drift in
the same row:

| Field | Old (frozen packet) | New (current `data/champions.json`) |
| --- | --- | --- |
| Bonus-AD ratio | 100% flat, every rank | **75% flat**, every rank |
| Target-max-HP ratio | 9% flat, every rank | **7 / 7.5 / 8 / 8.5 / 9%**, rank-scaling |

Base damage (30/55/80/105/130) and cooldown (8/7/6/5/4) are unchanged. No
other Poppy slot (P, W, E, R) differs between the old and new packet entry —
verified by a full field-by-field diff of the champion sub-object, not just
the Q slot.

### Regeneration method (real tooling, scoped merge)

`scripts/build_reviewed_modules.py` regenerates the **entire** 173-champion
corpus in one pass and requires a local Wiki revision-receipt index
(`--wiki-db`/`LCC_WIKI_DB`) that does not exist in this environment. A
real, network-fetched revision index was built for all 173 champions (not
fabricated — genuine `action=query&prop=revisions` calls against
`wiki.leagueoflegends.com`, all 173 titles resolved) so the tool's
`reviewed_packet` vs `generated_packet` labeling stayed accurate for every
champion, then the full build was run against current
`data/champions.json` + the pinned Axword source.

That full rebuild changed **18** champions' entries (their underlying wiki
text or `champions.json` leveling rows moved since the packet asset was
last built), of which **8** are packet-backed modules (Lulu, Maokai, Nunu &
Willump, Poppy, Pyke, Seraphine, Skarner, Swain, Zaahen). Touching all 8
would invalidate 7 other champions' `PACKET_SHA256` pins and their own
golden/test coverage — out of scope for a Poppy-only refresh. Only Poppy's
champion sub-object was spliced from the tool's genuine output into the
checked-in `static/reviewed-packets.json`; the other 172 entries (including
the 7 other packet-backed champions whose entries also drifted) are
byte-identical to before. Verified: `git diff` on the asset touches exactly
one champion key (`Poppy`); the other 7 packet-backed champions' modules
still import cleanly (`test_champion_module_contract.py` passes for all
173). The other 7 champions' drift is now a known, documented follow-up
item, not silently absorbed here.

### PACKET_SHA256

- Old: `1a31e4f033cd7f636b093e6398b78eaa559462a22552cb2fe1cc48b46f618be5`
- New: `b6f179d37816f86a3c589048738bf588034d2340535ad6dde533391daf113d90`

Verified by recomputing `packet_spec_sha256()` over the live manifest entry
after the splice; `build_packet_module("Poppy", PACKET_SHA256, ...)` no
longer raises.

### Golden diff — Q values move, arithmetic shown

Target is the standard snapshot target (2000 max HP, 50 armor). Physical
mitigation multiplier: `100 / (100 + 50) = 2/3`.

**`physical_build`** (Kraken Slayer + Infinity Edge + Lord Dominik's
Regards; bonus AD = 155 at level 18, same at level 11 in this harness since
these are flat item stats and Q is rank 5 in both fight levels):

```
old: 2 * (130 + 1.00*155 + 0.09*2000) * (2/3) = 2 * 465 * 2/3 = 620.00
new: 2 * (130 + 0.75*155 + 0.09*2000) * (2/3) = 2 * 426.25 * 2/3 = 568.33
```

(the `2 *` is Hammer Shock's sourced impact + 1s-later rupture, both hits
identical per `packet_part_timings`; the target-max-HP ratio at rank 5 is
9% in both old and new, since the new rank-scaling array's last entry
equals the old flat value — the rank-scaling fix is real and sourced but
invisible in a max-rank snapshot fight)

**`spellblade_build`** (Trinity Force + Infinity Edge + Berserker's
Greaves; bonus AD = 111):

```
old: 2 * (130 + 1.00*111 + 0.09*2000) * (2/3) = 2 * 421.0  * 2/3 = 561.33 (rounded)
new: 2 * (130 + 0.75*111 + 0.09*2000) * (2/3) = 2 * 393.25 * 2/3 = 524.33 (rounded)
```

`magic_build` and `no_items` Q values are unaffected (0 bonus AD in both,
so `1.00*0 == 0.75*0`).

Full list of the 12 golden-baseline paths whose diff is newly attributable
to this fix (all previously identical, all Q-ratio-driven; `total_damage`
paths already carried the Poppy base-AD drift from cluster C above and now
additionally carry this Q effect on top — a compound diff, same pattern as
the documented Azir/Berserker's-Greaves overlap):

```
registered_champion_fights/Poppy/11/physical_build/breakdown_totals/Q            620.0 -> 568.33
registered_champion_fights/Poppy/11/physical_build/total_damage                  962.31 -> 910.64
registered_champion_fights/Poppy/11/spellblade_build/breakdown_totals/Q          561.33 -> 524.33
registered_champion_fights/Poppy/11/spellblade_build/total_damage                872.84 -> 835.84
registered_champion_fights/Poppy/11/sustained/physical_build/breakdown_totals/Q  620.0 -> 568.33
registered_champion_fights/Poppy/11/sustained/spellblade_build/breakdown_totals/Q 561.33 -> 524.33
registered_champion_fights/Poppy/18/physical_build/breakdown_totals/Q            620.0 -> 568.33
registered_champion_fights/Poppy/18/physical_build/total_damage                  1106.12 -> 1054.45
registered_champion_fights/Poppy/18/spellblade_build/breakdown_totals/Q          561.33 -> 524.33
registered_champion_fights/Poppy/18/spellblade_build/total_damage                1016.65 -> 979.65
registered_champion_fights/Poppy/18/sustained/physical_build/breakdown_totals/Q  620.0 -> 568.33
registered_champion_fights/Poppy/18/sustained/spellblade_build/breakdown_totals/Q 561.33 -> 524.33
```

Poppy's other 38 already-documented cluster-C diffs (base AD, mana,
health regen baselines; auto-attack/on-hit/spellblade totals driven by the
base-AD change) are unchanged in kind — only the 4 `sustained
.../total_damage` entries among them now also fold in the Q delta above
(compound, not double-counted as a separate path). Total Poppy diff paths:
38 -> 50 (net +12, exactly the paths listed above). Non-Poppy diff paths:
unchanged at 292 (330 total - 38 = 292, confirmed identical set before and
after this fix). New grand total: 342 diff paths vs the original
pre-16.16.1 committed baseline.

### Recapture and re-verify

```
.venv/bin/python scripts/golden_snapshot.py capture scripts/golden_baseline.json
  champions: 173  registered: 173  items swept: 324  sweep errors: 0

.venv/bin/python scripts/golden_snapshot.py compare scripts/golden_baseline.json
  OK: snapshot identical to scripts/golden_baseline.json   (exit 0)
```

`jq empty static/reviewed-packets.json` and `jq empty scripts/golden_baseline.json`
both pass. `git diff` on `static/reviewed-packets.json` touches only the
`Poppy` champion key.

### Tests

`tests/test_bis_profiles.py`, `tests/test_champion_module_contract.py`,
and every Poppy-covering suite (`test_cp10_batch_06.py`, `test_e5_fix_2.py`,
`test_e9_fix_3.py`, `test_event_order_certification.py`,
`test_interaction_atoms.py`, `test_quinn_p_crit.py`) pass — 226 tests, 0
failures. No test hardcoded Poppy's Q numeric ratio, so no test-pin edits
were required. `static/bis-profiles.json` was already built from the
current `data/champions.json` (source sha256 already `77f8cce3...`) by
prior work on this branch, so it already carried the corrected Q ratios;
no rebuild was needed for this fix.

`black --check src/calculator/champions/poppy.py` passes.

## Addendum — Poppy Q reviewed-packet refresh (2026-08-20, follow-up session)

The open risk above is now closed. `static/reviewed-packets.json`'s Poppy
entry was regenerated against the current `data/champions.json` (only the
Poppy entry changed; the other 172 packets and their `PACKET_SHA256` pins
are untouched), and `PACKET_SHA256` in `src/calculator/champions/poppy.py`
was updated to match and verified at import time. The sourced field change:

| Field | Old | New | Source |
| --- | --- | --- | --- |
| Q bonus-AD ratio | 100% flat (all 5 ranks) | 75% flat (all 5 ranks) | `data/champions.json` Poppy Q "Physical Damage" / "Total Physical Damage" leveling rows |
| Q target-max-HP ratio | 9% flat (all 5 ranks) | 7/7.5/8/8.5/9% (rank-scaling) | same rows |

Pre-recapture `compare` against `scripts/golden_baseline.json` (the file as
left by the prior 330-diff recapture above, still uncommitted at HEAD)
produced **exactly 16 diffs**, all under `/registered_champion_fights/Poppy/`:

```
Poppy/11/physical_build:            breakdown_totals/Q 620.0 -> 568.33, total_damage 962.31 -> 910.64
Poppy/11/spellblade_build:          breakdown_totals/Q 561.33 -> 524.33, total_damage 872.84 -> 835.84
Poppy/11/sustained/physical_build:  breakdown_totals/Q 620.0 -> 568.33, total_damage 2861.93 -> 2810.26
Poppy/11/sustained/spellblade_build: breakdown_totals/Q 561.33 -> 524.33, total_damage 2415.25 -> 2378.25
Poppy/18/physical_build:            breakdown_totals/Q 620.0 -> 568.33, total_damage 1106.12 -> 1054.45
Poppy/18/spellblade_build:          breakdown_totals/Q 561.33 -> 524.33, total_damage 1016.65 -> 979.65
Poppy/18/sustained/physical_build:  breakdown_totals/Q 620.0 -> 568.33, total_damage 3460.36 -> 3408.69
Poppy/18/sustained/spellblade_build: breakdown_totals/Q 561.33 -> 524.33, total_damage 3364.25 -> 3327.25
```

Zero non-Poppy paths moved (checked: no Q/W/E/R/`total_damage`/`auto_attacks`
key for any other champion, and no `champion_baselines`/stat entries at all
— Poppy's Q change carries no base-stat component).

**Full reconciliation, physical_build (target armor 50, `SNAPSHOT_TARGET_ARMOR`
in `scripts/golden_snapshot.py`).** Q rank at level 11 and 18 is 5
(`get_ability_rank("Q", level, "Poppy")`), so the target-max-HP term (9% at
rank 5 both before and after) contributes nothing to the diff — the entire
delta is the bonus-AD ratio drop. Bonus AD from Kraken Slayer + Infinity
Edge + Lord Dominik's Regards = `45 + 75 + 35 = 155`. The packet emits Q as
2 hits (direct + rupture, `packet_part_timings` `count=2`), each carrying
the full per-rank AD ratio, so raw delta = `2 hits x 0.25 (1.00 - 0.75) x 155
bonus AD = 77.5`. Post-mitigation at 50 armor (`100/(100+50) = 2/3`):
`77.5 x 2/3 = 51.67` — exact match to the observed `620.0 -> 568.33` diff
(`51.67`), independent of character level since bonus AD is item-sourced,
not level-sourced.

**spellblade_build**, same method: bonus AD from Trinity Force + Infinity
Edge (Berserker's Greaves carries no AD) = `36 + 75 = 111`. Raw delta =
`2 x 0.25 x 111 = 55.5`; mitigated: `55.5 x 2/3 = 37.0` — exact match to the
observed `561.33 -> 524.33` diff (`37.0`).

Poppy test coverage was checked for pinned Q values that would need
updating: `grep -ril poppy tests/` found `test_event_order_certification.py`,
`test_e5_fix_2.py`, `test_e9_fix_3.py`, `test_quinn_p_crit.py`,
`test_interaction_atoms.py`, `test_cp10_batch_06.py` (215 tests total, run
green). None of them pin Q's "Physical Damage" bonus-AD or target-max-HP
ratio values — they cover P (Iron Ambassador), R (Keeper's Verdict), E
(stun atom), and Q's hit-count/timing metadata only — so no test edits were
required.

### Verification

```
.venv/bin/python scripts/golden_snapshot.py capture scripts/golden_baseline.json
  champions: 173  registered: 173  items swept: 324  sweep errors: 0

.venv/bin/python scripts/golden_snapshot.py compare scripts/golden_baseline.json
  OK: snapshot identical to scripts/golden_baseline.json   (exit 0)
```

`jq empty scripts/golden_baseline.json` passes. `git diff --numstat
scripts/golden_baseline.json` against HEAD (`11af560`) now carries the full
uncommitted stack — the 330-diff recapture above plus this session's 16
Poppy-Q diffs plus `metadata/git_head` — since neither recapture has been
committed yet on this branch.
