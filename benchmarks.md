# Benchmarks

Canonical performance numbers: nothing else in the tree restates one.

Two captures on the same machine (AMD Ryzen 7 7800X3D, Windows 11, CPython 3.14.2) with
the same commands: `7bb9701e`, the engine-retirement campaign start (D8), and the
campaign close. A `@7bb9701e` row is history and is not gated, and `--compare` reads the
scenario-named rows, which are always the close numbers.

## Request latency: `calculate_payload`

```bash
python scripts/bench_request.py                           # table
python scripts/bench_request.py --compare benchmarks.md   # exits 1 on a >25% median regression
```

Warm process, `deterministic=True`, median and p90 over 50 calls; the loop column is one
20-call loop timed whole. Requests are read from `golden_snapshot.COUPLED_SCENARIOS` by
name. Each close row is the median of three consecutive runs.

| scenario | median ms | p90 ms | 20-call s |
|---|---|---|---|
| simple_auto_only @7bb9701e | 8.43 | 8.82 | 0.173 |
| simple_auto_only | 7.55 | 7.81 | 0.153 |
| crit_carry @7bb9701e | 32.39 | 38.17 | 0.679 |
| crit_carry | 29.12 | 29.73 | 0.593 |
| full_roster @7bb9701e | 32.85 | 36.05 | 0.684 |
| full_roster | 26.79 | 27.11 | 0.541 |

`import src.calculator.calculate` in a fresh interpreter: 345 ms at `7bb9701e`, 334 ms at
close (median of 3), unchanged; no unit touched import-time work.

`import src.calculator.quantity` is 391 ms here, median of 3 whole-interpreter runs, 392
modules in `sys.modules`. Cutting the `src/calculator`
facade is worth about 130 ms and cannot reach 100 ms on its own: the one line that file
keeps, `publish_rune_compilers()`, pulls the 173-module champion roster through
`rune_effects` to `champions.inputs.champion_stat`, which two `rune_paths` modules import
too. The rest needs `champions/inputs.py` out of the champions package.

Where the three deltas come from, both changes measured one per commit against three
identical golden compares:

- **−0.9 / −3.0 / −4.5 ms, `get_item_by_name` reads an index instead of scanning.** It
  compared every one of 324 cached records by lowered name on each of its 4–20 calls per
  request. The index is keyed on the same `(path, mtime)` version as the parse, so a
  replaced cache file is a different key, and `setdefault` keeps the first spelling,
  which is the record the scan returned. Parity proven over all 324 names.
- **Same commit: the cache path is canonicalized once.** `_read_cache` called
  `Path.resolve()` on every read, 48 `realpath` syscalls per request. The freshness
  `stat` is untouched, so a mid-process refresh still invalidates.
- **−0.1 / −0.5 / −0.7 ms, concrete types lead four `isinstance` ladders.** A check
  against `collections.abc.Mapping` runs Python at 0.13 µs; one against a concrete type
  runs C at 0.017 µs. A crit_carry request paid 11,136 abstract-base checks, 8,333 of
  them in `LeafBlock.publish`/`_walk` and two row guards in `damage.py`; it now pays
  6,531. `dict` is a `Mapping`, so every site answers as before.

The PR #202 audit measured the regression this table opened against: warm
`calculate_payload` went 4.9 → 10.5 ms and a 20-call loop 0.09 → 0.22 s when the second
engine landed beside the first. The close numbers recover the campaign-start figures by
12–17%; the rest of that gap is the receipt-and-dispositions design itself, not
recoverable work. At close the profile's remaining weight is `program/views` (18% of a
warm crit_carry request, ~7.5 Python calls and two dataclass allocations per published
leaf, by D-72's single-writer rule) and `program/compile.action_from_event` (10%, ~89
`dict.get` calls per event). Both are the shape the design asks for, so moving either is
a design change rather than a tuning pass.

## Survival action: record construction and the walk

```bash
python scripts/bench_survival_action.py                           # tables
python scripts/bench_survival_action.py --compare benchmarks.md   # exits 1 on a >25% median regression
```

Captured at `3fb9b938` on the machine above, CPython 3.14.2. Each cell is the median of three
runs alternating with base `6ad828b5`, whose rows carry `@6ad828b5`. Every input is a real
action from the named golden scenario's walk. A group's representative is its first action at
the group's median count of fields set away from the neutral value. Construction is `timeit`,
the median of 15 repeats of 20,000 calls. The four source walks hold 873 actions. A
`@6ad828b5` row builds each as one 96-field tuple. The other rows build the record of its kind
in `survival/action_families`, a median of 48 fields stored and 16 set.

| group | scenario | set fields | all-kw µs | set-kw µs | narrow µs |
|---|---|---|---|---|---|
| damage @6ad828b5 | crit_onhit_carry_roster | 16 | 3.523 | 1.55 | 0.397 |
| heal @6ad828b5 | cleaver_bloodsong_roster | 12 | 3.519 | 1.481 | 0.344 |
| shield @6ad828b5 | lethality_window_assassin_roster | 14 | 3.531 | 1.53 | 0.359 |
| buff @6ad828b5 | cleaver_bloodsong_roster | 19 | 3.537 | 1.691 | 0.446 |
| state @6ad828b5 | control_event_roster | 19 | 3.589 | 1.595 | 0.441 |
| damage | crit_onhit_carry_roster | 16 | 1.36 | 0.826 | 0.39 |
| heal | cleaver_bloodsong_roster | 12 | 1.533 | 0.837 | 0.339 |
| shield | lethality_window_assassin_roster | 13 | 1.251 | 0.747 | 0.351 |
| buff | cleaver_bloodsong_roster | 18 | 0.985 | 0.727 | 0.428 |
| state | control_event_roster | 19 | 1.118 | 0.787 | 0.438 |

`all-kw` builds the action's own record by every field it stores, the width
`program/compile.action_from_event` pays. `set-kw` passes only the set fields, and `narrow`
builds a NamedTuple of only those fields. A record's `all-kw` is 2.3x to 3.6x below its
`@6ad828b5` row. The shield and buff representatives set one field fewer because their records
do not store `duration_set`, which only the utility transition reads. Over the 354 events of
`crit_onhit_carry_roster`, `action_from_event` takes about 4.4 µs an event, and 9.9 at
`6ad828b5`.

| constructor | fields | µs |
|---|---|---|
| row_copy @6ad828b5 | 29 | 1.18 |
| keywords @6ad828b5 | 29 | 1.737 |
| narrow @6ad828b5 | 29 | 0.679 |
| keywords | 29 | 1.095 |
| narrow | 29 | 0.689 |

`keywords` is the score compiler's damage construction: the 29 keywords
`WalkCompiler._compile_pair` passes, read off its call. `row_copy @6ad828b5` is that commit's
compiler, a default 96-field row assigned through 29 field indices. The 48-field
`DamageAction` by keyword is below it.

| scenario | actions | walk median µs | p10-p90 µs | request ms |
|---|---|---|---|---|
| crit_onhit_carry_roster @6ad828b5 | 354 | 2254 | 146 | 34.57 |
| cleaver_bloodsong_roster @6ad828b5 | 182 | 1833 | 138 | 19.43 |
| lethality_window_assassin_roster @6ad828b5 | 139 | 1240 | 60 | 15.15 |
| crit_onhit_carry_roster | 354 | 2203 | 156 | 32.12 |
| cleaver_bloodsong_roster | 182 | 1821 | 88 | 17.98 |
| lethality_window_assassin_roster | 139 | 1224 | 118 | 13.93 |

The walk rows time `run_survival_walk` inside a warm `calculate_payload(deterministic=True)`
over 50 requests, and `request ms` is the whole request's median. The walk reads a field a
record does not store off the `SurvivalAction` class attribute, no slower than a tuple slot,
so each walk median sits inside the spread of its `@6ad828b5` row. Requests sit 7 to 8% below
those rows, and construction is the difference.

## Optimizer search: `/api/optimize`

```bash
python scripts/bench_coupled_optimizer.py
```

Wall time is best of 3 at the endpoint's default 12 s budget. `--fixed-work` reports the
counter families that move before wall time leaves the noise. Evaluation counts and
winning builds are identical across the two captures: the search does the same work and
returns the same answer, only faster.

| scenario | wall ms | evaluations |
|---|---|---|
| cassiopeia_3champ @7bb9701e | 5018 | 1324 |
| cassiopeia_3champ | 4774 | 1324 |
| cassiopeia_5champ @7bb9701e | 5080 | 1033 |
| cassiopeia_5champ | 4762 | 1033 |
| mundo_3champ @7bb9701e | 4265 | 1143 |
| mundo_3champ | 3848 | 1143 |
| syndra_mandate_3champ @7bb9701e | 7643 | 796 |
| syndra_mandate_3champ | 4521 | 796 |

`syndra_mandate_3champ` is the outlier and only part of its −41% is this campaign's: the
same scenario re-measured at the campaign base in the close session read 5671 ms, so
−20% is code and the rest was load on the machine that took the `7bb9701e` capture.

## Optimizer search: `optimize_build`, uncoupled

```bash
python scripts/bench_optimize_build.py            # table
python scripts/bench_optimize_build.py --profile  # cProfile one warm search
```

Ahri level 18, five legendary slots, target 2000 HP / 50 armor / 40 MR: the scenario
`tests/test_optimizer.py`'s smoke cap drives, and the one every figure in that cap's
docstring was measured on. Warm process, `deterministic=True`, engine-reported
`optimization_time_ms`, median of 7 after one warmup. `@2e5b3da6` is the retired
pre-merge engine replayed with this harness; both rows elect the same build and the same
5653.5 score, so the search returns the same answer either way.

| tree | median ms | best ms | spread ms | evaluations |
|---|---|---|---|---|
| ahri_18_5 @2e5b3da6 (pre-merge main) | 1662.4 | 1627.5 | 144.1 | 3813 |
| ahri_18_5 | 2852.9 | 2829.1 | 62.1 | 3848 |

The merged-vs-main gap was 1190 ms, wider than the 819 ms the merge-202 audit recorded
(1584 → 2403 ms). That audit's own two trees replay here at 1627 and 2488 ms best-of-7,
so the machine has not drifted. At that point the `lean` row shape did not reach this
path: `build_evaluation._evaluate_build_uncached` called `run_fight` without `score_only`,
which only `participant_timeline._score_with_search_context` passed, and forcing it on
measured −0.7% with the answer unchanged, a coupled-path win only.

Re-measured after the optimizer adopted the lean row via `score_only`
(optimizer.py → participant_timeline.py:4246 → damage.py): the gap is gone. Same
harness, same scenario, alternating trees on one machine:

| tree | median ms | best ms | spread ms | evaluations |
|---|---|---|---|---|
| ahri_18_5 (post-lean adoption, working tree @195a3c0a) | 1693.6 | 1681.8 | 22.1 | 3848 |
| ahri_18_5 @1304424b (main alone, same day) | 1704.4 | 1700.2 | 11.9 | 3848 |

Same evaluation count and the same 5653.5 score both sides, so it is the same search.
The alternating `--by-build-size` run agrees: per-evaluation medians sit within ±2% at
every held-item count (1/2/3/4/6 items), e.g. 501.9 vs 499.8 µs cold at one item and
835.4 vs 828.2 µs at six. The merged-vs-main gap is closed; no residual to act on.

### Read the per-evaluation budget without the profiler

```bash
python scripts/bench_optimize_build.py --budget         # the table below
python scripts/bench_optimize_build.py --by-build-size  # per-evaluation µs by items held
```

**cProfile's shares over-weight this engine's small helpers by roughly two to one**,
because it charges about a microsecond to every call and the merged engine's cost is
spread across millions of one-line ones. `--budget` takes *call counts* from the
profile, which it reports exactly, and *shares* from `timeit` best-of-7 against the
whole evaluation. One evaluation is `run_fight` over the elected six-item build,
800 µs, and 3601 of them are most of the search's wall time:

| term | calls per search | real share of one evaluation | profile said |
|---|---|---|---|
| `champions.engine.parse_abilities` | 3,601 | 57 µs, 7.3% | 10% |
| `FightParams.pre_combat_stats` | 3,601 | 50 µs, 6.4% | n/a |
| `fight.ledger.event_rows._damage_event_row` | 142,974 | 1.045 µs each, 39 µs, 4.9% | 6% |
| `item_behavior_catalog.behavior_rules` folds | 561,783 | 49 µs, 6.1% | 8% |
| `item_effects.resolved_item_name` + `_item_names` | 908,617 | 0.073 µs each, 30 µs, 3.8% | 4% |

**None of the five is a tuning target.** `parse_abilities` and `pre_combat_stats` read
the build's own stats, so no two evaluations share inputs; `_damage_event_row` is the
certified event-row schema, whose 15 field reads per row is what the schema costs and
whose light tuple row already prices at 0.200 µs where a consumer can take it;
`resolved_item_name` is a validated `item["name"]` at 73 ns, below the cost of memoizing
it. `behavior_rules`' fold is the one that looked recoverable: a memoized per-build pass
was measured and does not pay, because a per-build cache re-verifies its owners'
registry records on every read for about what the per-owner memo hits cost. It lives in
`6dfef122`, reverted by `3c0d8df4`; `--by-build-size --against <checkout of 6dfef122>`
reproduces the comparison: it wins at six items, loses at one, and the greedy search
evaluates far more partial builds than full ones. The only shape that could win hoists
the fold to the fight, resolving a build's buckets once where `held_owners` is resolved,
which changes thirteen selector signatures and is a design change, not a tuning pass.
