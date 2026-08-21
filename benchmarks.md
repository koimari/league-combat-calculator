# Benchmarks

Canonical performance numbers — nothing else in the tree restates one.

Captured at `7bb9701e` (engine-retirement campaign start, D8) on AMD Ryzen 7 7800X3D,
Windows 11, CPython 3.14.2. Re-captured at campaign close on the same machine with the
same commands; every delta is explained in the closing commit.

## Request latency — `calculate_payload`

```bash
python scripts/bench_request.py                           # table
python scripts/bench_request.py --compare benchmarks.md   # exits 1 on a >25% median regression
```

Warm process, `deterministic=True`, median and p90 over 50 calls; the loop column is one
20-call loop timed whole. Requests are read from `golden_snapshot.COUPLED_SCENARIOS` by
name.

| scenario | median ms | p90 ms | 20-call s |
|---|---|---|---|
| simple_auto_only | 8.43 | 8.82 | 0.173 |
| crit_carry | 32.39 | 38.17 | 0.679 |
| full_roster | 32.85 | 36.05 | 0.684 |

`import src.calculator.calculate` in a fresh interpreter: 345 ms (median of 3).

The PR #202 audit measured the regression this table now pins: warm `calculate_payload`
went 4.9 → 10.5 ms and a 20-call loop 0.09 → 0.22 s when the second engine landed beside
the first.

## Optimizer search — `/api/optimize`

```bash
python scripts/bench_coupled_optimizer.py
```

Wall time is best of 3 at the endpoint's default 12 s budget. `--fixed-work` reports the
counter families that move before wall time leaves the noise.

| scenario | wall ms | evaluations |
|---|---|---|
| cassiopeia_3champ | 5018 | 1324 |
| cassiopeia_5champ | 5080 | 1033 |
| mundo_3champ | 4265 | 1143 |
| syndra_mandate_3champ | 7643 | 796 |
