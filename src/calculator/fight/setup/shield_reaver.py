"""The Shield Reaver venom's cut to the target's non-magic shields."""

from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any

from ... import item_effects
from ...interpreters import damage_routing
from ...item_behavior import FightFacts
from ..config import FightConfig


def _apply_shield_reaver_venom(
    config: FightConfig,
    items: Iterable[dict[str, Any]],
    champion_stats: Mapping[str, float],
) -> tuple[FightConfig, list[str]]:
    """Cut the target's non-magic shields for the attacker's Shield Reaver.

    The venom reduces the target's active shields on first damage and any
    shields gained while the attacker keeps dealing damage — a sustained
    rotation keeps the venom applied throughout. Magic-damage shields
    (Hexdrinker, Maw of Malmortius, Kaenic Rookern, ability magic shields)
    are unaffected, and Protoplasm Harness's temporary health and healing
    are not shields.

    Which item carries the venom, how deep the cut is and how long it lasts
    are all read off the declaration: the holder's own ``damage_routing``
    rule, resolved for the holder's range class.
    """
    is_melee = bool(champion_stats["is_melee"])
    bypass = damage_routing.resolve_shield_bypass(
        [item_effects.resolved_item_name(item) for item in items],
        facts=FightFacts(
            level=int(champion_stats["level"]),
            fight_duration_seconds=config.fight_duration_seconds,
            target_bonus_health=max(0.0, config.target_bonus_health),
            holder_is_melee=is_melee,
        ),
    )
    if bypass is None or bypass.fraction <= 0.0:
        return config, []
    fraction = bypass.fraction

    keep = 1.0 - fraction
    threshold_is_cuttable = (
        config.target_threshold_shield_damage_type != "magic"
        and config.target_threshold_shield_amount > 0
    )
    if (
        config.target_physical_shield <= 0
        and config.target_general_shield <= 0
        and not threshold_is_cuttable
    ):
        return config, []

    reduced = replace(
        config,
        target_physical_shield=config.target_physical_shield * keep,
        target_general_shield=config.target_general_shield * keep,
        target_threshold_shield_amount=(
            config.target_threshold_shield_amount * keep
            if threshold_is_cuttable
            else config.target_threshold_shield_amount
        ),
    )
    note = (
        f"{bypass.owner}: Shield Reaver cuts the target's non-magic shields "
        f"by {fraction:.0%} ({'melee' if is_melee else 'ranged'}) — the "
        f"rotation keeps its {bypass.duration:g}-second venom applied; "
        "magic-damage shields are unaffected."
    )
    return reduced, [note]
