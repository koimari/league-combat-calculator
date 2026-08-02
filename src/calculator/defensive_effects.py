"""Champion-owned starting defenses compiled from sourced mechanics."""

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .champions.skill_orders import get_ability_rank
from .item_effects import ITEM_EFFECTS


@dataclass(frozen=True, slots=True)
class DefenseSource:
    """Revision-backed provenance for one defensive mechanic."""

    label: str
    source_url: str
    revision_id: int
    revision_timestamp: str


@dataclass(frozen=True, slots=True)
class StartingDefenses:
    """Defenses assumed ready when the modeled exchange begins."""

    magic_shield: float = 0.0
    physical_shield: float = 0.0
    general_shield: float = 0.0
    basic_damage_multiplier: float = 1.0
    basic_damage_flat_reduction: float = 0.0
    basic_damage_flat_reduction_cap: float = 0.0
    critical_strike_damage_multiplier: float = 1.0
    threshold_shield_amount: float = 0.0
    threshold_shield_health_ratio: float = 0.0
    threshold_shield_duration: float = 0.0
    threshold_shield_damage_type: str = "all"
    threshold_health_bonus: float = 0.0
    threshold_health_heal: float = 0.0
    threshold_health_ratio: float = 0.0
    threshold_health_duration: float = 0.0
    assumptions: tuple[str, ...] = ()
    sources: tuple[DefenseSource, ...] = ()
    coverage: str = "base_and_items_only"

    def public_summary(self) -> dict[str, object]:
        """Return a JSON-safe explanation of the resolved state."""
        return {
            "magic_shield": round(self.magic_shield, 1),
            "physical_shield": round(self.physical_shield, 1),
            "general_shield": round(self.general_shield, 1),
            "incoming_damage": {
                "basic_damage_multiplier": round(self.basic_damage_multiplier, 3),
                "basic_damage_flat_reduction": round(
                    self.basic_damage_flat_reduction, 1
                ),
                "basic_damage_flat_reduction_cap": round(
                    self.basic_damage_flat_reduction_cap, 3
                ),
                "critical_strike_damage_multiplier": round(
                    self.critical_strike_damage_multiplier, 3
                ),
            },
            "threshold_shield": {
                "amount": round(self.threshold_shield_amount, 1),
                "health_ratio": round(self.threshold_shield_health_ratio, 3),
                "duration": round(self.threshold_shield_duration, 1),
                "damage_type": self.threshold_shield_damage_type,
            },
            "threshold_health": {
                "bonus_health": round(self.threshold_health_bonus, 1),
                "healing": round(self.threshold_health_heal, 1),
                "health_ratio": round(self.threshold_health_ratio, 3),
                "duration": round(self.threshold_health_duration, 1),
            },
            "assumptions": list(self.assumptions),
            "sources": [
                {
                    "label": source.label,
                    "url": source.source_url,
                    "revision_id": source.revision_id,
                    "revision_timestamp": source.revision_timestamp,
                }
                for source in self.sources
            ],
            "coverage": self.coverage,
        }


_GALIO_W_SOURCE = DefenseSource(
    label="Galio — Shield of Durand",
    source_url=(
        "https://wiki.leagueoflegends.com/en-us/" "Template:Data_Galio/Shield_of_Durand"
    ),
    revision_id=3990299,
    revision_timestamp="2026-02-07T07:08:21Z",
)

_KAENIC_SOURCE = DefenseSource(
    label="Kaenic Rookern — Magebane",
    source_url="https://wiki.leagueoflegends.com/en-us/Kaenic_Rookern",
    revision_id=3984971,
    revision_timestamp="2026-01-17T16:04:29Z",
)

_SPIRIT_VISAGE_SOURCE = DefenseSource(
    label="Spirit Visage — Boundless Vitality",
    source_url="https://wiki.leagueoflegends.com/en-us/Spirit_Visage",
    revision_id=4016166,
    revision_timestamp="2026-05-09T17:09:08Z",
)

_PLATED_STEELCAPS_SOURCE = DefenseSource(
    label="Plated Steelcaps — Plating",
    source_url="https://wiki.leagueoflegends.com/en-us/Plated_Steelcaps",
    revision_id=4022248,
    revision_timestamp="2026-05-24T02:13:22Z",
)

_WARDENS_MAIL_SOURCE = DefenseSource(
    label="Warden's Mail — Rock Solid",
    source_url="https://wiki.leagueoflegends.com/en-us/Warden%27s_Mail",
    revision_id=3987228,
    revision_timestamp="2026-01-25T05:28:19Z",
)

_RANDUINS_OMEN_SOURCE = DefenseSource(
    label="Randuin's Omen — Resilience",
    source_url="https://wiki.leagueoflegends.com/en-us/Randuin%27s_Omen",
    revision_id=4021798,
    revision_timestamp="2026-05-21T14:21:13Z",
)

_IMMORTAL_SHIELDBOW_SOURCE = DefenseSource(
    label="Immortal Shieldbow — Lifeline",
    source_url="https://wiki.leagueoflegends.com/en-us/Immortal_Shieldbow",
    revision_id=4030401,
    revision_timestamp="2026-06-15T20:45:46Z",
)

_HEXDRINKER_SOURCE = DefenseSource(
    label="Hexdrinker — Lifeline",
    source_url=(
        "https://wiki.leagueoflegends.com/en-us/"
        "Module:ItemData/data/Hexdrinker"
    ),
    revision_id=3905721,
    revision_timestamp="2025-06-04T01:19:48Z",
)

_MAW_SOURCE = DefenseSource(
    label="Maw of Malmortius — Lifeline",
    source_url=(
        "https://wiki.leagueoflegends.com/en-us/"
        "Module:ItemData/data/Maw_of_Malmortius"
    ),
    revision_id=3905768,
    revision_timestamp="2025-06-04T01:58:07Z",
)

_SERAPHS_SOURCE = DefenseSource(
    label="Seraph's Embrace — Lifeline",
    source_url=(
        "https://wiki.leagueoflegends.com/en-us/"
        "Module:ItemData/data/Seraph%27s_Embrace"
    ),
    revision_id=3905841,
    revision_timestamp="2025-06-04T02:29:36Z",
)

_STERAKS_SOURCE = DefenseSource(
    label="Sterak's Gage — Lifeline",
    source_url=(
        "https://wiki.leagueoflegends.com/en-us/"
        "Module:ItemData/data/Sterak%27s_Gage"
    ),
    revision_id=3905864,
    revision_timestamp="2025-06-04T02:46:55Z",
)

_PROTOPLASM_SOURCE = DefenseSource(
    label="Protoplasm Harness — Lifeline",
    source_url=(
        "https://wiki.leagueoflegends.com/en-us/" "Module:ItemData/data"
    ),
    revision_id=4046863,
    revision_timestamp="2026-07-28T22:43:08Z",
)


def _shieldbow_shield_amount(level: int) -> float:
    effect = ITEM_EFFECTS["Immortal Shieldbow"]
    base = float(effect["shield_base"])
    maximum = float(effect["shield_max"])
    start = int(effect["shield_scale_start_level"])
    end = int(effect["shield_scale_end_level"])
    if level < start:
        return base
    increments = end - start + 1
    return min(maximum, base + (maximum - base) * (level - start + 1) / increments)


def _linear_level_value(minimum: float, maximum: float, level: int) -> float:
    """Interpolate a Wiki ``X to Y based on level`` value across levels 1–18."""
    scaling_level = min(18, max(1, level))
    return minimum + (maximum - minimum) * (scaling_level - 1) / 17.0


def _lifeline_defense(
    name: str, level: int, stats: Mapping[str, float]
) -> tuple[float, float, float, str, str, DefenseSource]:
    """Resolve one mutually exclusive Lifeline item's ready shield."""
    effect = ITEM_EFFECTS[name]
    is_melee = bool(stats.get("is_melee", False))
    if name == "Immortal Shieldbow":
        amount = _shieldbow_shield_amount(level)
        source = _IMMORTAL_SHIELDBOW_SOURCE
    elif name == "Hexdrinker":
        prefix = "melee" if is_melee else "ranged"
        amount = _linear_level_value(
            float(effect[f"shield_{prefix}_min"]),
            float(effect[f"shield_{prefix}_max"]),
            level,
        )
        source = _HEXDRINKER_SOURCE
    elif name == "Maw of Malmortius":
        prefix = "melee" if is_melee else "ranged"
        amount = float(effect[f"shield_{prefix}_base"]) + float(
            effect[f"shield_{prefix}_bonus_ad_ratio"]
        ) * float(stats.get("bonus_attack_damage", 0.0))
        source = _MAW_SOURCE
    elif name == "Seraph's Embrace":
        amount = float(effect["shield_max_mana_ratio"]) * float(
            stats.get("max_mana", 0.0)
        )
        source = _SERAPHS_SOURCE
    elif name == "Sterak's Gage":
        amount = float(effect["shield_bonus_health_ratio"]) * float(
            stats.get("bonus_health", 0.0)
        )
        source = _STERAKS_SOURCE
    else:  # pragma: no cover - private helper is called from a closed registry
        raise KeyError(f"Unsupported Lifeline item: {name}")
    damage_type = str(effect.get("damage_type", "all"))
    qualifier = " magic" if damage_type == "magic" else ""
    assumption = (
        f"{name}'s Lifeline is ready and triggers before{qualifier} damage "
        "that would leave the target below 30% maximum health."
    )
    return (
        amount,
        float(effect["health_threshold"]),
        float(effect["duration"]),
        damage_type,
        assumption,
        source,
    )


def _galio_starting_defenses(level: int, maximum_health: float) -> StartingDefenses:
    if get_ability_rank("W", level, "Galio") < 1:
        return StartingDefenses()
    shield_percent = 7.5 + (13.5 - 7.5) * (level - 1) / 17.0
    return StartingDefenses(
        magic_shield=maximum_health * shield_percent / 100.0,
        assumptions=(
            "Anti-Magic Bulwark is ready because Galio has not recently taken damage.",
        ),
        sources=(_GALIO_W_SOURCE,),
        coverage="modeled_starting_passive",
    )


def resolve_starting_defenses(
    champion_name: str,
    level: int,
    stats: dict[str, float],
    items: Sequence[Mapping[str, Any]] = (),
) -> StartingDefenses:
    """Resolve sourced champion and item defenses ready at fight start."""
    champion_defenses = StartingDefenses()
    if champion_name == "Galio":
        champion_defenses = _galio_starting_defenses(level, stats["health"])

    names = {str(item.get("name", "")) for item in items}
    magic_shield = champion_defenses.magic_shield
    physical_shield = champion_defenses.physical_shield
    general_shield = champion_defenses.general_shield
    basic_damage_multiplier = champion_defenses.basic_damage_multiplier
    basic_damage_flat_reduction = champion_defenses.basic_damage_flat_reduction
    basic_damage_flat_reduction_cap = (
        champion_defenses.basic_damage_flat_reduction_cap
    )
    critical_strike_damage_multiplier = (
        champion_defenses.critical_strike_damage_multiplier
    )
    threshold_shield_amount = champion_defenses.threshold_shield_amount
    threshold_shield_health_ratio = champion_defenses.threshold_shield_health_ratio
    threshold_shield_duration = champion_defenses.threshold_shield_duration
    threshold_shield_damage_type = champion_defenses.threshold_shield_damage_type
    threshold_health_bonus = champion_defenses.threshold_health_bonus
    threshold_health_heal = champion_defenses.threshold_health_heal
    threshold_health_ratio = champion_defenses.threshold_health_ratio
    threshold_health_duration = champion_defenses.threshold_health_duration
    assumptions = list(champion_defenses.assumptions)
    sources = list(champion_defenses.sources)

    if "Kaenic Rookern" in names:
        ratio = float(
            ITEM_EFFECTS["Kaenic Rookern"]["magic_shield_max_health_ratio"]
        )
        magic_shield += stats["health"] * ratio
        assumptions.append(
            "Magebane is ready because the target has not taken magic damage "
            "during the previous 15 seconds."
        )
        sources.append(_KAENIC_SOURCE)

    lifeline_name = next(
        (
            name
            for name in (
                "Immortal Shieldbow",
                "Hexdrinker",
                "Maw of Malmortius",
                "Seraph's Embrace",
                "Sterak's Gage",
            )
            if name in names
        ),
        None,
    )
    if lifeline_name:
        (
            threshold_shield_amount,
            threshold_shield_health_ratio,
            threshold_shield_duration,
            threshold_shield_damage_type,
            lifeline_assumption,
            lifeline_source,
        ) = _lifeline_defense(lifeline_name, level, stats)
        assumptions.append(lifeline_assumption)
        sources.append(lifeline_source)

    if "Protoplasm Harness" in names:
        effect = ITEM_EFFECTS["Protoplasm Harness"]
        threshold_health_bonus = _linear_level_value(
            float(effect["bonus_health_min"]),
            float(effect["bonus_health_max"]),
            level,
        )
        threshold_health_heal = _linear_level_value(
            float(effect["heal_min"]),
            float(effect["heal_max"]),
            level,
        ) + float(effect["heal_bonus_armor_ratio"]) * float(
            stats.get("bonus_armor", 0.0)
        ) + float(effect["heal_bonus_mr_ratio"]) * float(
            stats.get("bonus_magic_resistance", 0.0)
        )
        threshold_health_ratio = float(effect["health_threshold"])
        threshold_health_duration = float(effect["duration"])
        assumptions.append(
            "Protoplasm Harness's Lifeline is ready. Before damage would leave "
            "the target below 30% maximum health, it grants temporary bonus "
            "health and begins its five-second heal."
        )
        sources.append(_PROTOPLASM_SOURCE)

    has_shield = (
        magic_shield > 0
        or physical_shield > 0
        or general_shield > 0
        or threshold_shield_amount > 0
    )
    if "Spirit Visage" in names and has_shield:
        multiplier = float(
            ITEM_EFFECTS["Spirit Visage"]["shield_received_multiplier"]
        )
        magic_shield *= multiplier
        physical_shield *= multiplier
        general_shield *= multiplier
        threshold_shield_amount *= multiplier
        assumptions.append(
            "Boundless Vitality increases every modeled shield by 25%."
        )
        sources.append(_SPIRIT_VISAGE_SOURCE)

    if "Spirit Visage" in names and threshold_health_heal > 0:
        threshold_health_heal *= float(
            ITEM_EFFECTS["Spirit Visage"]["shield_received_multiplier"]
        )
        assumptions.append(
            "Boundless Vitality increases Protoplasm Harness's modeled healing "
            "by 25%."
        )
        if _SPIRIT_VISAGE_SOURCE not in sources:
            sources.append(_SPIRIT_VISAGE_SOURCE)

    if "Plated Steelcaps" in names:
        basic_damage_multiplier *= float(
            ITEM_EFFECTS["Plated Steelcaps"]["basic_damage_multiplier"]
        )
        assumptions.append("Plating reduces every non-true basic-damage instance.")
        sources.append(_PLATED_STEELCAPS_SOURCE)

    if "Warden's Mail" in names:
        basic_damage_flat_reduction = float(
            ITEM_EFFECTS["Warden's Mail"]["basic_damage_flat_reduction"]
        )
        basic_damage_flat_reduction_cap = float(
            ITEM_EFFECTS["Warden's Mail"]["basic_damage_flat_reduction_cap"]
        )
        assumptions.append(
            "Rock Solid reduces the first post-mitigation basic-damage "
            "instance of each attack or cast."
        )
        sources.append(_WARDENS_MAIL_SOURCE)

    if "Randuin's Omen" in names:
        critical_strike_damage_multiplier *= float(
            ITEM_EFFECTS["Randuin's Omen"]["critical_strike_damage_multiplier"]
        )
        assumptions.append("Resilience reduces damage from critical strikes.")
        sources.append(_RANDUINS_OMEN_SOURCE)

    if not sources:
        return StartingDefenses()
    return StartingDefenses(
        magic_shield=magic_shield,
        physical_shield=physical_shield,
        general_shield=general_shield,
        basic_damage_multiplier=basic_damage_multiplier,
        basic_damage_flat_reduction=basic_damage_flat_reduction,
        basic_damage_flat_reduction_cap=basic_damage_flat_reduction_cap,
        critical_strike_damage_multiplier=critical_strike_damage_multiplier,
        threshold_shield_amount=threshold_shield_amount,
        threshold_shield_health_ratio=threshold_shield_health_ratio,
        threshold_shield_duration=threshold_shield_duration,
        threshold_shield_damage_type=threshold_shield_damage_type,
        threshold_health_bonus=threshold_health_bonus,
        threshold_health_heal=threshold_health_heal,
        threshold_health_ratio=threshold_health_ratio,
        threshold_health_duration=threshold_health_duration,
        assumptions=tuple(assumptions),
        sources=tuple(sources),
        coverage="modeled_starting_defenses",
    )
