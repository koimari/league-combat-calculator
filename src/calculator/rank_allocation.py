"""Manual ranks use the cached kit and the sourced skill-point rules."""

from collections.abc import Mapping

SPECIAL_CHAMPIONS = ("Elise", "Jayce", "Karma", "Nidalee", "Udyr")
_FREE_ULTIMATE = frozenset({"Elise", "Jayce", "Karma", "Nidalee"})
_BASIC_LEVELS = (1, 3, 5, 7, 9)


def rank_rules(champion: str) -> dict[str, object]:
    """Expose unlock levels and free ranks for manual clients."""
    basic = (*_BASIC_LEVELS, 11) if champion == "Jayce" else _BASIC_LEVELS
    if champion == "Udyr":
        basic = (*_BASIC_LEVELS, 16)
    ultimate = (6, 11, 16)
    if champion in _FREE_ULTIMATE:
        ultimate = (1,) if champion == "Jayce" else (1, 6, 11, 16)
    elif champion == "Udyr":
        ultimate = basic
    return {
        "rank_unlock_levels": {
            "Q": list(basic),
            "W": list(basic),
            "E": list(basic),
            "R": list(ultimate),
        },
        "free_ranks": {"Q": 0, "W": 0, "E": 0, "R": int(champion in _FREE_ULTIMATE)},
    }


def validate_manual_ranks(champion: str, level: int, ranks: Mapping[str, int]) -> None:
    """Validate all spent points while preserving the free starting rank."""
    rules = rank_rules(champion)
    unlocks = rules["rank_unlock_levels"]
    free = rules["free_ranks"]
    for slot, levels in unlocks.items():
        rank = ranks[slot]
        if rank < free[slot] or rank > len(levels):
            raise ValueError(
                f"{slot} rank must be {free[slot]}-{len(levels)} for {champion}"
            )
        if rank and level < levels[rank - 1]:
            raise ValueError(
                f"{slot} rank {rank} requires champion level {levels[rank - 1]}"
            )
    if sum(ranks.values()) - sum(free.values()) > min(level, 18):
        raise ValueError(
            "Ability ranks spend more skill points than the champion level allows"
        )
