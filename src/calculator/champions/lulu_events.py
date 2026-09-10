"""Source-valued Lulu support windows for explicit recipient casts."""

from collections.abc import Iterable, Mapping
from typing import Any

from ..binary_roots import calculation_coefficient, data_value, spell_object
from .skill_orders import get_ability_rank
from .slotlib import extract_named, extract_value


def derive_lulu_support_events(
    champion_data: dict[str, Any],
    level: int,
    stats: Mapping[str, float],
    cast_timeline: Iterable[Mapping[str, Any]],
    *,
    ability_ranks: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Price W's friendly branch and R at their accepted cast timestamps."""
    if champion_data["name"] != "Lulu":
        return []
    rows = []
    for index, cast in enumerate(cast_timeline):
        slot = str(cast["slot"])
        if slot not in {"W", "R"}:
            continue
        rank = (
            ability_ranks[slot]
            if ability_ranks is not None and slot in ability_ranks
            else get_ability_rank(slot, level, "Lulu")
        )
        if rank <= 0:
            continue
        ability = champion_data["abilities"][slot][0]
        row = {
            "time": float(cast["time"]),
            "slot": slot,
            "rank": rank,
            "source": ability["name"],
            "target_scope": "one_teammate",
            "target_self": True,
            "target_selection_key": f"buff:{slot}:{index}",
        }
        if slot == "W":
            spell = spell_object("Lulu", "LuluW")
            movement = (
                data_value(spell, "BaseMS")
                + calculation_coefficient(spell, "TotalMS") * stats["ability_power"]
            ) * 100.0
            row.update(
                kind="stat_buff",
                amount=0.0,
                duration=extract_value(ability, "Effect Duration", rank),
                bonus_attack_speed_percent=extract_value(
                    ability, "Bonus Attack Speed", rank
                ),
                bonus_move_speed_percent=movement,
            )
        else:
            row.update(
                kind="temporary_health",
                amount=extract_named(ability, "Bonus Health", rank, dict(stats), {}),
                duration=data_value(spell_object("Lulu", "LuluR"), "BuffDuration"),
            )
        rows.append(row)
    return rows
