"""One ``/api/calculate`` driver and its row readers for champion closures.

A closure test pins one champion's sourced mechanic against values recomputed
from the cached ``data/champions.json`` leveling rows and the fight's own
stats, so every number it asserts traces to the cache rather than to the
module under test.  :func:`fight` is the one request builder; a champion's
own file binds the convention it drives with ``functools.partial``:

* a level-18 time-based fight with autos into a 3000-HP Aatrox;
* a one-rotation fight against the bare dummy target at 2000 HP, armor and
  MR zero, so post-mitigation damage equals the raw wiki values;
* the same fight into an Ahri enemy, which is what produces the coupled
  participant ledger that heal and shield receipts are read from.

This is a test helper, not a test module: it holds no assertions beyond the
status check every request shares.
"""

from src import app as app_module
from src.calculator.champions import (
    _CHAMPION_MODULES,
    get_champion_module_contract,
    module_basename,
    parse_champion_abilities,
)
from src.calculator.champions.slot_extract import extract_named
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats

#: Basic abilities maxed, ultimate at rank 3: the level-18 closure ranks.
RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

#: The response rounds each published number to one decimal, so a sum of a
#: few rows is compared to this tolerance rather than exactly.
ROUNDING = 0.6

AATROX = {"champion": "Aatrox", "level": 18, "items": []}

AHRI = {
    "champion": "Ahri",
    "level": 18,
    "items": [],
    "role": "mid",
    # Keep support amount assertions independent of incoming Ahri Charm
    # downtime. Control timing has dedicated interaction tests.
    "ability_ranks": {"Q": 5, "W": 5, "E": 0, "R": 3},
}

TARGET_2000 = {
    "target_max_health": 2000.0,
    "target_current_health": 2000.0,
    "target_missing_health": 0.0,
}

TARGET_3000 = {
    "target_max_health": 3000.0,
    "target_current_health": 3000.0,
    "target_missing_health": 0.0,
}

#: A fixed stat block, so a row that scales resolves against known inputs
#: rather than against whatever the champion's own level-18 sheet holds.
REFERENCE_STATS = {
    "ability_power": 0.0,
    "health": 2000.0,
    "attack_damage": 100.0,
    "bonus_attack_damage": 0.0,
}


def fight(
    champion: str,
    *,
    level: int = 18,
    ranks: dict | None = RANKS,
    options: dict | None = None,
    items: list | None = None,
    role: str | None = None,
    mode: str = "one_rotation",
    duration: float = 10.0,
    include_autos: bool = False,
    auto_uptime: float | None = None,
    target_health: float | None = 2000.0,
    enemy: dict | None = None,
    enemy_ranks: dict | None = None,
    cast_order: list | None = None,
) -> dict:
    """One ``/api/calculate`` fight, as the whole response."""
    payload = {
        "champion": champion,
        "level": level,
        "items": items or [],
        "fight_mode": mode,
        "fight_duration": duration,
        "include_auto_attacks": include_autos,
        "champion_options": options or {},
    }
    if ranks is not None:
        payload["ability_ranks"] = dict(ranks)
    if role is not None:
        payload["role"] = role
    if auto_uptime is not None:
        payload["auto_attack_uptime"] = auto_uptime
    if target_health is not None:
        payload["target_health"] = target_health
        payload["target_armor"] = 0
        payload["target_mr"] = 0
    if enemy is not None:
        payload["enemies"] = [
            enemy if enemy_ranks is None else {**enemy, "ability_ranks": enemy_ranks}
        ]
    if cast_order is not None:
        payload["cast_order"] = cast_order
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()


def combat(champion: str, **kwargs) -> dict:
    """The ``combat`` block of one fight."""
    return fight(champion, **kwargs)["combat"]


def stats(champion: str, level: int = 18) -> dict:
    """The app's no-item stats for one champion."""
    return calculate_total_stats(get_champion(champion), level, [])


def parse(
    champion: str,
    *,
    level: int = 18,
    stats: dict | None = None,
    options: dict | None = None,
    ranks: dict | None = RANKS,
    target: dict | None = TARGET_2000,
) -> tuple[dict, dict, dict]:
    """The cached champion, the stat block it was priced against, its slots."""
    data = get_champion(champion)
    resolved = calculate_total_stats(data, level, []) if stats is None else stats
    return (
        data,
        resolved,
        parse_champion_abilities(
            data,
            level,
            resolved.get("ability_power", 0.0),
            ability_ranks=ranks,
            champion_stats=resolved,
            champion_options=options or {},
            target_stats=target,
        ),
    )


def abilities(champion: str, **kwargs) -> dict:
    """The parsed slots alone."""
    return parse(champion, **kwargs)[2]


def reference_abilities(champion: str, *, stats: dict | None = None, **kwargs) -> dict:
    """The parsed slots over :data:`REFERENCE_STATS`, overridden by ``stats``."""
    return abilities(champion, stats={**REFERENCE_STATS, **(stats or {})}, **kwargs)


def module_coverage(basename: str) -> dict:
    """The declared coverage map of one champion module, by its file name."""
    display = next(
        name
        for name, module in _CHAMPION_MODULES.items()
        if module_basename(module) == basename
    )
    return get_champion_module_contract(display).coverage


def ability_row(champion: str, slot: str) -> dict:
    """The cached first entry of one slot."""
    return get_champion(champion)["abilities"][slot][0]


def expected(
    champion: str, slot: str, attr: str, rank: int, stats: dict, target: dict
) -> float:
    """One cached leveling row resolved against the fight's own stats."""
    return extract_named(ability_row(champion, slot), attr, rank, stats, target)


def slot_total(response: dict, key: str) -> float:
    """The per-slot breakdown total of the main participant."""
    row = response["breakdown"].get(key)
    assert row is not None, f"breakdown row {key!r} missing"
    return float(row["total_damage"])


def fight_stats(response: dict) -> dict:
    """The stat sheet the fight priced against."""
    return dict(response["champion_stats"])


def target_stats(response: dict) -> dict:
    """The target block matching the fight's own effective max health."""
    max_health = float(response["target_effective_max_health"])
    return {
        "target_max_health": max_health,
        "target_current_health": max_health,
        "target_missing_health": 0.0,
    }


def main_breakdown(combat: dict) -> dict:
    """The main participant's breakdown row."""
    return next(row for row in combat["breakdown"] if row["participant_id"] == "main")


def main_survival(combat: dict) -> dict:
    """The main participant's survival block."""
    return next(
        row for row in combat["participants"] if row["participant_id"] == "main"
    )["survival"]


def enemy_stats(combat: dict) -> dict:
    """The enemy participant's own stat sheet, which mitigation is read from."""
    return next(
        row["stats"]
        for row in combat["participants"]
        if row["participant_id"].startswith("enemy")
    )


def main_damage_events(combat: dict, source: str) -> list[dict]:
    """Every damage event the main participant authored from one source."""
    return [
        event
        for event in combat.get("events", [])
        if event.get("attacker") == "main" and event.get("source") == source
    ]


def main_heals(combat: dict, source: str) -> list[dict]:
    """Every heal the main participant received from one source."""
    return [
        heal
        for heal in combat.get("healing_events", [])
        if heal.get("attacker") == "main" and heal.get("source") == source
    ]


def shield_rows(combat: dict, *, source_startswith: str) -> list[dict]:
    """Every shield support event whose source starts with a prefix."""
    return [
        event
        for event in combat.get("support_events", [])
        if event.get("kind") == "shield"
        and str(event.get("source", "")).startswith(source_startswith)
    ]


def main_support(response: dict, source_substring: str) -> list[dict]:
    """Every support event the main participant authored, matched loosely."""
    return [
        event
        for event in response["combat"].get("support_events", [])
        if event.get("attacker") == "main"
        and source_substring.lower() in str(event.get("source", "")).lower()
    ]


def response_heals(response: dict, source: str) -> list[dict]:
    """Heals from one source, wherever the response reports them.

    An enemy fight enriches them under ``combat.healing_events``; a fight
    against the bare dummy reports them at the top level instead.
    """
    events = response["combat"].get("healing_events")
    if not events:
        events = [
            dict(heal, attacker="main")
            for heal in (response.get("self_healing_events") or [])
        ]
    return [
        heal
        for heal in events
        if heal.get("source") == source and heal.get("attacker", "main") == "main"
    ]


def response_shields(response: dict, source_startswith: str) -> list[dict]:
    """Shield support events whose source starts with a prefix."""
    return shield_rows(response["combat"], source_startswith=source_startswith)


def mitigated(raw: float, damage_type: str, enemy_stats: dict) -> float:
    """One raw number through the enemy's own resistance."""
    resist = (
        enemy_stats["armor"]
        if damage_type == "physical"
        else enemy_stats["magic_resistance"]
    )
    return raw * 100.0 / (100.0 + resist)
