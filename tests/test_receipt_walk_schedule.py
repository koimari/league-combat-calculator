"""The priced-row predicate reproduces the fight's own total.

Amendment O, Ruling 1 distinguishes a row a family authors from a row that
publishes a difference and is summed into no total.  The whole receipt-walk
triage turns on that predicate, so it is checked exactly rather than trusted.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import receipt_walk_schedule  # noqa: E402  (path is set above)


def test_the_priced_row_predicate_reproduces_the_fights_own_total() -> None:
    """Summing ``total_damage`` over exactly :func:`priced_rows` is the total.

    A row the predicate drops is therefore a row the total genuinely does not
    hold.  The probe deliberately holds one informational-row item (Sundered
    Sky), one execute (The Collector) and one heal row (Bloodthirster's
    lifesteal) — the three shapes that would otherwise be counted as authored.
    """
    champions = receipt_walk_schedule.golden_snapshot.fetch_champion_data()
    by_name = {
        data["name"]: data
        for data in receipt_walk_schedule.golden_snapshot.fetch_item_data().values()
    }
    held = ["Sundered Sky", "The Collector", "Bloodthirster"]
    result = receipt_walk_schedule.golden_snapshot._run_fight(  # noqa: SLF001
        champions["Caitlyn"],
        receipt_walk_schedule.PROBE_LEVEL,
        [by_name[name] for name in held],
        auto_attack_uptime=1.0,
        one_rotation=False,
    )
    priced = receipt_walk_schedule.priced_rows(result)
    assert {"sundered_sky", "execute", "heal_lifesteal"}.isdisjoint(priced)
    assert sum(
        float(result["breakdown"][key]["total_damage"]) for key in priced
    ) == pytest.approx(float(result["total_damage"]), rel=0, abs=1e-9)
