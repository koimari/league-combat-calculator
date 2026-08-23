# Benchmarks

Canonical performance numbers — nothing else in the tree restates one.

Two captures on the same machine (AMD Ryzen 7 7800X3D, Windows 11, CPython 3.14.2) with
the same commands: `7bb9701e`, the engine-retirement campaign start (D8), and the
campaign close. A `@7bb9701e` row is history and is not gated — `--compare` reads the
scenario-named rows, which are always the close numbers.

## Request latency — `calculate_payload`

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
close (median of 3) — unchanged; no unit touched import-time work.

Where the three deltas come from, both changes measured one per commit against three
identical golden compares:

- **−0.9 / −3.0 / −4.5 ms, `get_item_by_name` reads an index instead of scanning.** It
  compared every one of 324 cached records by lowered name on each of its 4–20 calls per
  request. The index is keyed on the same `(path, mtime)` version as the parse, so a
  replaced cache file is a different key, and `setdefault` keeps the first spelling —
  which is the record the scan returned. Parity proven over all 324 names.
- **Same commit: the cache path is canonicalized once.** `_read_cache` called
  `Path.resolve()` on every read — 48 `realpath` syscalls per request. The freshness
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

## Optimizer search — `/api/optimize`

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

## Optimizer search — `optimize_build`, uncoupled

```bash
python scripts/bench_optimize_build.py            # table
python scripts/bench_optimize_build.py --profile  # cProfile one warm search
```

Ahri level 18, five legendary slots, target 2000 HP / 50 armor / 40 MR — the scenario
`tests/test_optimizer.py`'s smoke cap drives, and the one every figure in that cap's
docstring was measured on. Warm process, `deterministic=True`, engine-reported
`optimization_time_ms`, median of 7 after one warmup. `@2e5b3da6` is the retired
pre-merge engine replayed with this harness; both rows elect the same build and the same
5653.5 score, so the search returns the same answer either way.

| tree | median ms | best ms | spread ms | evaluations |
|---|---|---|---|---|
| ahri_18_5 @2e5b3da6 (pre-merge main) | 1662.4 | 1627.5 | 144.1 | 3813 |
| ahri_18_5 | 2852.9 | 2829.1 | 62.1 | 3848 |

The merged-vs-main gap is 1190 ms, wider than the 819 ms the merge-202 audit recorded
(1584 → 2403 ms). That audit's own two trees replay here at 1627 and 2488 ms best-of-7,
so the machine has not drifted. The `lean` row shape does not reach this path:
`optimizer.py:442` calls `run_fight` without `score_only`, which only
`participant_timeline.py:4256` passes, and forcing it on measures −0.7% with the answer
unchanged — the lean adoption is a coupled-path win only.

### Read the per-evaluation budget without the profiler

**cProfile's shares over-weight this engine's small helpers by roughly two to one**,
because it charges about a microsecond to every call and the merged engine's cost is
spread across millions of one-line ones. Take *call counts* from the profile, which it
reports exactly, and *shares* from `timeit` best-of-7 against the whole evaluation.
One evaluation is `run_fight` over the elected six-item build — 800 µs, and 3601 of them
are most of the search's wall time. Every share below was measured that way:

| term | calls per search | real share of one evaluation | profile said |
|---|---|---|---|
| `champions.engine.parse_abilities` | 3,601 | 57 µs, 7.3% | 10% |
| `FightParams.pre_combat_stats` | 3,601 | 50 µs, 6.4% | — |
| `damage._damage_event_row` | 142,974 | 1.045 µs each, 39 µs, 4.9% | 6% |
| `item_behavior_catalog.behavior_rules` folds | 561,783 | 49 µs, 6.1% | 8% |
| `item_effects.resolved_item_name` + `_item_names` | 908,617 | 0.073 µs each, 30 µs, 3.8% | 4% |

**None of the five is a tuning target, and that is the answer to #213's remaining arm.**
`parse_abilities` and `pre_combat_stats` read the build's own stats, so no two
evaluations share inputs. `_damage_event_row` is the certified event-row schema: 15
field reads per row is what the schema costs, and the light tuple row already prices at
0.200 µs where a consumer can take it. `resolved_item_name` is 73 ns — a validated
`item["name"]`, below the cost of memoizing it.

`behavior_rules` was the one that looked recoverable, and it was tried: one memoized
per-build pass bucketed by family, replacing the thirteen interpreter generator
expressions that each re-open the same fold. It works and it does not pay — 561,783
`behavior_rules` calls fall to 34,828 and the search does 23.23M function calls instead
of 25.35M, but the wall time does not move on either bench. **A per-build cache has to
re-verify its owners' registry records on every read, which costs about what the
per-owner memo hits cost**, and the fixed per-call frames it adds do not shrink with the
build. Measured per evaluation against build size, cold build memo, subprocesses
interleaved so drift lands on both trees:

| items held | 1 | 2 | 3 | 4 | 6 |
|---|---|---|---|---|---|
| per-owner fold (current) | 497.6 | 597.6 | 696.0 | 713.4 | 802.7 |
| per-build fold (tried) | 508.4 | 608.3 | 689.9 | 717.0 | 785.7 |

It wins at six items and loses at one, and a greedy multi-start search evaluates far
more partial builds than full ones, so the two cancel. Run against each other in a
quieter session than the row above was captured in, this tree read 2714 and 2720 ms
best-of-7 against the attempt's 2726 and 2727, and the coupled `mundo_3champ` bench
4081 against 4109 — the same answer from both, at the same speed. Reverted.
The only shape that could win is hoisting the fold to the fight — resolving a build's
buckets once where `held_owners` is resolved and handing them down — which changes
thirteen selector signatures and is a design change, not a tuning pass.
