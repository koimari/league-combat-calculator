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
