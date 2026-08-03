"""Timeline-coverage progress meter for the timestamp-certification campaign.

Runs a fixed set of TIMED fights (10s, 10% auto uptime, deterministic) and
prints each build's ``timeline_coverage`` verdict: whether every active
damage source authored real per-event timestamps (``complete=True``) and
which sources still fall back to coarse phase ordering.

Usage:
    python scripts/timeline_coverage_probe.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.stats import calculate_total_stats

BUILDS = [
    (
        "Ahri mage",
        "Ahri",
        ["Liandry's Torment", "Shadowflame", "Rabadon's Deathcap"],
        "",
    ),
    ("Ahri Luden", "Ahri", ["Luden's Echo", "Malignance", "Stormsurge"], "Electrocute"),
    (
        "Vayne on-hit",
        "Vayne",
        ["Blade of the Ruined King", "Wit's End", "Kraken Slayer"],
        "",
    ),
    (
        "Kai'Sa hybrid",
        "Kai'Sa",
        ["Guinsoo's Rageblade", "Nashor's Tooth", "Statikk Shiv"],
        "",
    ),
    (
        "Darius bruiser",
        "Darius",
        ["Stridebreaker", "Sundered Sky", "Sterak's Gage"],
        "",
    ),
    (
        "Ezreal spellblade",
        "Ezreal",
        ["Trinity Force", "Muramana", "Serylda's Grudge"],
        "",
    ),
    ("Corki poke", "Corki", ["Trinity Force", "Luden's Echo"], ""),
]


def probe_build(champ_key: str, item_names: list[str], keystone: str) -> dict:
    """Run one timed fight and return its ``timeline_coverage`` block."""
    champ = get_champion(champ_key)
    items = [get_item_by_name(name) for name in item_names]
    stats = calculate_total_stats(champ, 18, items)
    abilities = parse_champion_abilities(
        champ, 18, stats.get("ability_power", 0.0), champion_stats=stats
    )
    result = calculate_fight_damage(
        stats,
        abilities,
        items,
        FightConfig(
            target_health=3000.0,
            target_armor=100.0,
            target_magic_resistance=100.0,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.10,
            one_rotation=False,
            deterministic=True,
            keystone=keystone,
        ),
    )
    return result["timeline_coverage"]


def main() -> int:
    """Print one stable table row per probe build; return 0 always."""
    print(f"{'build':<18} {'complete':<9} coarse_sources")
    for label, champ_key, item_names, keystone in BUILDS:
        try:
            coverage = probe_build(champ_key, item_names, keystone)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"{label:<18} ERROR: {type(exc).__name__}: {exc}")
            continue
        coarse = ", ".join(coverage["coarse_sources"]) or "-"
        print(f"{label:<18} {str(coverage['complete']):<9} {coarse}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
