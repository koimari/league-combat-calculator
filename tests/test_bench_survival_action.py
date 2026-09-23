"""The survival-action bench runs on a tiny input and prints the rows ``benchmarks.md`` holds."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import bench_survival_action as bench


def test_a_tiny_run_prints_every_row_compare_reads(capsys):
    scenario = bench.WALK_SCENARIOS[-1]
    bench.main(
        ["--scenario", scenario, "--repeats", "2", "--number", "5"]
        + ["--walk-repeats", "2"]
    )
    printed = capsys.readouterr().out
    headers = {"| " + " | ".join(columns) + " |" for columns in bench.TABLES.values()}

    assert printed.startswith("CPython ")
    assert headers <= set(printed.splitlines())
    expected = {
        name
        for name, (table, _) in bench.MEDIAN_COLUMN.items()
        if table != "walk" or name == scenario
    }
    assert set(bench.committed_medians(printed)) == expected
    assert bench.regressions(printed, printed) == []
