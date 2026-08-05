"""Champion-owned starting defenses compiled from sourced mechanics."""

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .champions.skill_orders import get_ability_rank
from .item_effects import (
    ITEM_EFFECTS,
    input_option_float_value,
    required_effect_value,
)


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
    # A reactive shield is granted after an explicitly typed incoming
    # champion-damage event (for example Noxian Endurance/Persistence).  It
    # is kept separate from opening shields so the trigger packet cannot
    # accidentally absorb the hit that armed it.
    reactive_shield_amount: float = 0.0
    reactive_shield_damage_type: str = ""
    reactive_shield_duration: float = 0.0
    reactive_shield_cooldown: float = 0.0
    reactive_shield_source: str = ""
    bloodthirster_shield_cap: float = 0.0
    bloodthirster_starting_shield: float = 0.0
    spell_shield_ready: bool = False
    spell_shield_source: str = ""
    basic_damage_multiplier: float = 1.0
    incoming_damage_multiplier: float = 1.0
    incoming_damage_linger: float = 0.0
    incoming_damage_cooldown: float = 0.0
    incoming_damage_source: str = ""
    basic_damage_flat_reduction: float = 0.0
    basic_damage_flat_reduction_cap: float = 0.0
    critical_strike_damage_multiplier: float = 1.0
    healing_received_multiplier: float = 1.0
    # Maw's Lifeline grants a temporary omnivamp stat after its shield fires;
    # the ordered timeline toggles this only on the authored threshold event.
    maw_lifeline_omnivamp_percent: float = 0.0
    threshold_shield_amount: float = 0.0
    threshold_shield_health_ratio: float = 0.0
    threshold_shield_duration: float = 0.0
    threshold_shield_damage_type: str = "all"
    threshold_health_bonus: float = 0.0
    threshold_health_heal: float = 0.0
    threshold_health_ratio: float = 0.0
    threshold_health_duration: float = 0.0
    revive_health_amount: float = 0.0
    revive_delay: float = 0.0
    revive_cooldown: float = 0.0
    # Death's Dance ordered defenses.  The participant timeline consumes
    # these fields only when the item is present; zero is the fail-closed
    # absence state for every other loadout.
    damage_deferral_fraction: float = 0.0
    damage_deferral_duration: float = 0.0
    damage_deferral_ticks: int = 0
    defy_window: float = 0.0
    defy_heal_bonus_ad_ratio: float = 0.0
    defy_heal_duration: float = 0.0
    defy_heal_ticks: int = 0
    # Combat-state item defenses.  These are metadata for the ordered ledger;
    # no stack is assumed active at t=0.
    force_stack_duration: float = 0.0
    force_max_stacks: int = 0
    force_stack_interval: float = 0.0
    force_immobilize_stacks: int = 0
    force_bonus_magic_resistance: float = 0.0
    force_bonus_move_speed_percent: float = 0.0
    jaksho_stack_interval: float = 0.0
    jaksho_max_stacks: int = 0
    jaksho_bonus_resistance_multiplier: float = 0.0
    starting_stasis_duration: float = 0.0
    starting_stasis_source: str = ""
    assumptions: tuple[str, ...] = ()
    sources: tuple[DefenseSource, ...] = ()
    coverage: str = "base_and_items_only"

    def public_summary(self) -> dict[str, object]:
        """Return a JSON-safe explanation of the resolved state."""
        incoming_damage = {
            "basic_damage_multiplier": round(self.basic_damage_multiplier, 3),
            "basic_damage_flat_reduction": round(self.basic_damage_flat_reduction, 1),
            "basic_damage_flat_reduction_cap": round(
                self.basic_damage_flat_reduction_cap, 3
            ),
            "critical_strike_damage_multiplier": round(
                self.critical_strike_damage_multiplier, 3
            ),
        }
        if (
            self.incoming_damage_multiplier != 1.0
            or self.incoming_damage_linger > 0.0
            or self.incoming_damage_cooldown > 0.0
            or self.incoming_damage_source
        ):
            incoming_damage.update(
                {
                    "incoming_damage_multiplier": round(
                        self.incoming_damage_multiplier, 3
                    ),
                    "incoming_damage_linger": round(self.incoming_damage_linger, 1),
                    "incoming_damage_cooldown": round(self.incoming_damage_cooldown, 1),
                    "source": self.incoming_damage_source,
                }
            )
        return {
            "magic_shield": round(self.magic_shield, 1),
            "physical_shield": round(self.physical_shield, 1),
            "general_shield": round(self.general_shield, 1),
            "reactive_shield": {
                "amount": round(self.reactive_shield_amount, 1),
                "damage_type": self.reactive_shield_damage_type,
                "duration": round(self.reactive_shield_duration, 1),
                "cooldown": round(self.reactive_shield_cooldown, 1),
                "source": self.reactive_shield_source,
            },
            "ichorshield": {
                "cap": round(self.bloodthirster_shield_cap, 1),
                "starting": round(self.bloodthirster_starting_shield, 1),
            },
            "spell_shield": {
                "ready": bool(self.spell_shield_ready),
                "source": self.spell_shield_source,
            },
            "incoming_damage": incoming_damage,
            "healing_received_multiplier": round(self.healing_received_multiplier, 3),
            "maw_lifeline_omnivamp_percent": round(
                self.maw_lifeline_omnivamp_percent, 3
            ),
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
            "revive": {
                "health_amount": round(self.revive_health_amount, 1),
                "delay": round(self.revive_delay, 1),
                "cooldown": round(self.revive_cooldown, 1),
            },
            "death_dance": {
                "damage_deferral_fraction": round(self.damage_deferral_fraction, 3),
                "damage_deferral_duration": round(self.damage_deferral_duration, 1),
                "damage_deferral_ticks": int(self.damage_deferral_ticks),
                "defy_window": round(self.defy_window, 1),
                "defy_heal_bonus_ad_ratio": round(self.defy_heal_bonus_ad_ratio, 3),
                "defy_heal_duration": round(self.defy_heal_duration, 1),
                "defy_heal_ticks": int(self.defy_heal_ticks),
            },
            "combat_state": {
                "force_of_nature": {
                    "stack_duration": round(self.force_stack_duration, 1),
                    "max_stacks": int(self.force_max_stacks),
                    "stack_interval": round(self.force_stack_interval, 1),
                    "immobilize_stacks": int(self.force_immobilize_stacks),
                    "bonus_magic_resistance": round(
                        self.force_bonus_magic_resistance, 1
                    ),
                    "bonus_move_speed_percent": round(
                        self.force_bonus_move_speed_percent, 1
                    ),
                },
                "jaksho": {
                    "stack_interval": round(self.jaksho_stack_interval, 1),
                    "max_stacks": int(self.jaksho_max_stacks),
                    "bonus_resistance_multiplier": round(
                        self.jaksho_bonus_resistance_multiplier, 3
                    ),
                },
                "starting_stasis": {
                    "duration": round(self.starting_stasis_duration, 3),
                    "source": self.starting_stasis_source,
                },
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

_GUARDIAN_ANGEL_SOURCE = DefenseSource(
    label="Guardian Angel — Rebirth",
    source_url="https://wiki.leagueoflegends.com/en-us/Guardian_Angel",
    revision_id=4046863,
    revision_timestamp="2026-07-28T22:43:08Z",
)

_DEATHS_DANCE_SOURCE = DefenseSource(
    label="Death's Dance — Ignore Pain / Defy",
    source_url="https://wiki.leagueoflegends.com/en-us/Death%27s_Dance",
    # Item mechanics are read from the patch-stamped cached item source; the
    # cache does not expose a MediaWiki revision id, so zero explicitly marks
    # this provenance as cache-backed rather than inventing a revision.
    revision_id=0,
    revision_timestamp="cached data/items.json (patch 16.15)",
)

_FORCE_OF_NATURE_SOURCE = DefenseSource(
    label="Force of Nature — Steadfast",
    source_url="https://wiki.leagueoflegends.com/en-us/Force_of_Nature",
    revision_id=4016272,
    revision_timestamp="2026-05-10T11:45:30Z",
)

_JAKSHO_SOURCE = DefenseSource(
    label="Jak'Sho, The Protean — Voidborn Resilience",
    source_url="https://wiki.leagueoflegends.com/en-us/Jak%27Sho,_The_Protean",
    revision_id=3984950,
    revision_timestamp="2026-01-17T15:12:22Z",
)

_STASIS_SOURCE = DefenseSource(
    label="Zhonya's Hourglass / Seeker's Armguard — Time Stop",
    source_url="https://wiki.leagueoflegends.com/en-us/Zhonya%27s_Hourglass",
    revision_id=3902922,
    revision_timestamp="2025-05-29T13:29:45Z",
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
        "https://wiki.leagueoflegends.com/en-us/" "Module:ItemData/data/Hexdrinker"
    ),
    revision_id=3905721,
    revision_timestamp="2025-06-04T01:19:48Z",
)

_MAW_SOURCE = DefenseSource(
    label="Maw of Malmortius — Lifeline",
    source_url="https://wiki.leagueoflegends.com/en-us/Maw_of_Malmortius",
    revision_id=3984424,
    revision_timestamp="2026-01-14T23:08:00Z",
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
        "https://wiki.leagueoflegends.com/en-us/" "Module:ItemData/data/Sterak%27s_Gage"
    ),
    revision_id=3905864,
    revision_timestamp="2025-06-04T02:46:55Z",
)

_PROTOPLASM_SOURCE = DefenseSource(
    label="Protoplasm Harness — Lifeline",
    source_url=("https://wiki.leagueoflegends.com/en-us/" "Module:ItemData/data"),
    revision_id=4046863,
    revision_timestamp="2026-07-28T22:43:08Z",
)

_ANNUL_SOURCES = {
    "Banshee's Veil": DefenseSource(
        label="Banshee's Veil — Annul",
        source_url="https://wiki.leagueoflegends.com/en-us/Banshee%27s_Veil",
        revision_id=3957919,
        revision_timestamp="2025-10-05T20:03:50Z",
    ),
    "Edge of Night": DefenseSource(
        label="Edge of Night — Annul",
        source_url="https://wiki.leagueoflegends.com/en-us/Edge_of_Night",
        revision_id=4013389,
        revision_timestamp="2026-04-29T06:32:04Z",
    ),
    "Verdant Barrier": DefenseSource(
        label="Verdant Barrier — Annul",
        source_url="https://wiki.leagueoflegends.com/en-us/Verdant_Barrier",
        revision_id=3957920,
        revision_timestamp="2025-10-05T20:04:20Z",
    ),
}

_OPENING_DEFENSE_SOURCES = {
    "Armored Advance": DefenseSource(
        label="Armored Advance — Noxian Endurance / Plating",
        source_url="https://wiki.leagueoflegends.com/en-us/Armored_Advance",
        revision_id=4013702,
        revision_timestamp="2026-04-29T23:40:53Z",
    ),
    "Chainlaced Crushers": DefenseSource(
        label="Chainlaced Crushers — Noxian Persistence",
        source_url="https://wiki.leagueoflegends.com/en-us/Chainlaced_Crushers",
        revision_id=4013705,
        revision_timestamp="2026-04-29T23:41:11Z",
    ),
    "Celestial Opposition": DefenseSource(
        label="Celestial Opposition — Blessing of the Mountain",
        source_url="https://wiki.leagueoflegends.com/en-us/Celestial_Opposition",
        revision_id=4028004,
        revision_timestamp="2026-06-13T11:27:01Z",
    ),
    "Bloodthirster": DefenseSource(
        label="Bloodthirster — Ichorshield",
        source_url="https://wiki.leagueoflegends.com/en-us/Bloodthirster",
        revision_id=4025103,
        revision_timestamp="2026-06-04T21:03:44Z",
    ),
    "Fimbulwinter": DefenseSource(
        label="Fimbulwinter — Everlasting",
        source_url="https://wiki.leagueoflegends.com/en-us/Fimbulwinter",
        revision_id=3984419,
        revision_timestamp="2026-01-14T22:19:05Z",
    ),
}


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


def _late_level_value(minimum: float, maximum: float, level: int, start: int) -> float:
    """Resolve a value that stays at its base until a later level.

    Armored Advance, Chainlaced Crushers, and Bloodthirster currently use
    ``base, then +15/+10 per level from level 9``.  Keeping this interpolation
    here makes the level boundary explicit and testable rather than hiding a
    literal in a call site.
    """
    if level < start:
        return minimum
    steps = max(1, 18 - start + 1)
    return min(maximum, minimum + (maximum - minimum) * (level - start + 1) / steps)


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
    damage_type = str(required_effect_value(name, "damage_type"))
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
    item_options: Mapping[str, Mapping[str, int | float]] | None = None,
) -> StartingDefenses:
    """Resolve sourced champion and item defenses ready at fight start."""
    champion_defenses = StartingDefenses()
    if champion_name == "Galio":
        champion_defenses = _galio_starting_defenses(level, stats["health"])

    names = {str(item.get("name", "")) for item in items}
    magic_shield = champion_defenses.magic_shield
    physical_shield = champion_defenses.physical_shield
    general_shield = champion_defenses.general_shield
    reactive_shield_amount = champion_defenses.reactive_shield_amount
    reactive_shield_damage_type = champion_defenses.reactive_shield_damage_type
    reactive_shield_duration = champion_defenses.reactive_shield_duration
    reactive_shield_cooldown = champion_defenses.reactive_shield_cooldown
    reactive_shield_source = champion_defenses.reactive_shield_source
    bloodthirster_shield_cap = champion_defenses.bloodthirster_shield_cap
    bloodthirster_starting_shield = champion_defenses.bloodthirster_starting_shield
    spell_shield_ready = bool(champion_defenses.spell_shield_ready)
    spell_shield_source = champion_defenses.spell_shield_source
    basic_damage_multiplier = champion_defenses.basic_damage_multiplier
    incoming_damage_multiplier = champion_defenses.incoming_damage_multiplier
    incoming_damage_linger = champion_defenses.incoming_damage_linger
    incoming_damage_cooldown = champion_defenses.incoming_damage_cooldown
    incoming_damage_source = champion_defenses.incoming_damage_source
    basic_damage_flat_reduction = champion_defenses.basic_damage_flat_reduction
    basic_damage_flat_reduction_cap = champion_defenses.basic_damage_flat_reduction_cap
    critical_strike_damage_multiplier = (
        champion_defenses.critical_strike_damage_multiplier
    )
    healing_received_multiplier = champion_defenses.healing_received_multiplier
    maw_lifeline_omnivamp_percent = champion_defenses.maw_lifeline_omnivamp_percent
    threshold_shield_amount = champion_defenses.threshold_shield_amount
    threshold_shield_health_ratio = champion_defenses.threshold_shield_health_ratio
    threshold_shield_duration = champion_defenses.threshold_shield_duration
    threshold_shield_damage_type = champion_defenses.threshold_shield_damage_type
    threshold_health_bonus = champion_defenses.threshold_health_bonus
    threshold_health_heal = champion_defenses.threshold_health_heal
    threshold_health_ratio = champion_defenses.threshold_health_ratio
    threshold_health_duration = champion_defenses.threshold_health_duration
    revive_health_amount = champion_defenses.revive_health_amount
    revive_delay = champion_defenses.revive_delay
    revive_cooldown = champion_defenses.revive_cooldown
    damage_deferral_fraction = champion_defenses.damage_deferral_fraction
    damage_deferral_duration = champion_defenses.damage_deferral_duration
    damage_deferral_ticks = champion_defenses.damage_deferral_ticks
    defy_window = champion_defenses.defy_window
    defy_heal_bonus_ad_ratio = champion_defenses.defy_heal_bonus_ad_ratio
    defy_heal_duration = champion_defenses.defy_heal_duration
    defy_heal_ticks = champion_defenses.defy_heal_ticks
    force_stack_duration = champion_defenses.force_stack_duration
    force_max_stacks = champion_defenses.force_max_stacks
    force_stack_interval = champion_defenses.force_stack_interval
    force_immobilize_stacks = champion_defenses.force_immobilize_stacks
    force_bonus_magic_resistance = champion_defenses.force_bonus_magic_resistance
    force_bonus_move_speed_percent = champion_defenses.force_bonus_move_speed_percent
    jaksho_stack_interval = champion_defenses.jaksho_stack_interval
    jaksho_max_stacks = champion_defenses.jaksho_max_stacks
    jaksho_bonus_resistance_multiplier = (
        champion_defenses.jaksho_bonus_resistance_multiplier
    )
    starting_stasis_duration = champion_defenses.starting_stasis_duration
    starting_stasis_source = champion_defenses.starting_stasis_source
    assumptions = list(champion_defenses.assumptions)
    sources = list(champion_defenses.sources)

    for defensive_name in (
        "Armored Advance",
        "Chainlaced Crushers",
        "Celestial Opposition",
    ):
        if defensive_name not in names:
            continue
        effect = ITEM_EFFECTS[defensive_name]
        source = _OPENING_DEFENSE_SOURCES[defensive_name]
        sources.append(source)
        if defensive_name == "Armored Advance":
            basic_damage_multiplier *= float(
                required_effect_value(defensive_name, "basic_damage_multiplier")
            )
        if "reactive_shield_base" in effect:
            reactive_shield_amount = _late_level_value(
                float(effect["reactive_shield_base"]),
                float(effect["reactive_shield_max"]),
                level,
                int(effect["reactive_shield_scale_start_level"]),
            ) + float(effect["reactive_shield_bonus_health_ratio"]) * float(
                stats.get("bonus_health", 0.0)
            )
            reactive_shield_damage_type = str(effect["reactive_shield_damage_type"])
            reactive_shield_duration = float(effect["reactive_shield_duration"])
            reactive_shield_cooldown = float(effect["reactive_shield_cooldown"])
            reactive_shield_source = f"{defensive_name} — Noxian"
            assumptions.append(
                f"{defensive_name}'s typed reactive shield is ready and is granted "
                f"after champion {reactive_shield_damage_type} damage."
            )
        if defensive_name == "Celestial Opposition":
            incoming_damage_multiplier = float(effect["incoming_damage_multiplier"])
            incoming_damage_linger = float(effect["incoming_damage_linger"])
            incoming_damage_cooldown = float(effect["incoming_damage_cooldown"])
            incoming_damage_source = "Celestial Opposition — Blessed"
            assumptions.append(
                "Blessing of the Mountain starts Blessed, reduces incoming champion "
                "damage by 35%, and lingers for two seconds after the last hit."
            )

    if "Bloodthirster" in names:
        source = _OPENING_DEFENSE_SOURCES["Bloodthirster"]
        sources.append(source)
        effect = ITEM_EFFECTS["Bloodthirster"]
        bloodthirster_shield_cap = _late_level_value(
            float(effect["ichorshield_min"]),
            float(effect["ichorshield_max"]),
            level,
            int(effect["ichorshield_scale_start_level"]),
        )
        supplied = 0
        if item_options:
            supplied = int(
                (item_options.get("Bloodthirster") or {}).get("starting_ichorshield", 0)
            )
        if supplied > 0:
            bloodthirster_starting_shield = min(
                float(supplied), bloodthirster_shield_cap
            )
            general_shield += bloodthirster_starting_shield
            assumptions.append(
                "Bloodthirster's Ichorshield starting state is explicitly supplied "
                "by the scenario and capped at the sourced level maximum."
            )
        else:
            assumptions.append(
                "Bloodthirster's Ichorshield starts empty unless an explicit starting "
                "shield input is supplied; excess lifesteal healing is not guessed."
            )
    if "Fimbulwinter" in names:
        sources.append(_OPENING_DEFENSE_SOURCES["Fimbulwinter"])
        assumptions.append(
            "Fimbulwinter Awe is applied through the typed stat conversion; "
            "Everlasting requires authored crowd-control metadata and is not inferred."
        )

    annul_name = next(
        (
            name
            for name in ("Banshee's Veil", "Edge of Night", "Verdant Barrier")
            if name in names
            and bool(ITEM_EFFECTS.get(name, {}).get("spell_shield_ready", False))
        ),
        None,
    )
    if annul_name:
        spell_shield_ready = True
        spell_shield_source = f"{annul_name} — Annul"
        sources.append(_ANNUL_SOURCES[annul_name])
        assumptions.append(
            f"{annul_name}'s Annul spell shield is ready at the opening and "
            "consumes the first authored hostile ability; cooldown rearm is "
            "outside the modeled exchange."
        )

    if "Kaenic Rookern" in names:
        ratio = float(ITEM_EFFECTS["Kaenic Rookern"]["magic_shield_max_health_ratio"])
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
        if lifeline_name == "Maw of Malmortius":
            maw_lifeline_omnivamp_percent = float(
                required_effect_value(lifeline_name, "lifeline_omnivamp_percent")
            )
            assumptions.append(
                "Maw of Malmortius grants its sourced temporary omnivamp only "
                "after Lifeline triggers; the ordered ledger schedules that state."
            )

    if "Protoplasm Harness" in names:
        effect = ITEM_EFFECTS["Protoplasm Harness"]
        threshold_health_bonus = _linear_level_value(
            float(effect["bonus_health_min"]),
            float(effect["bonus_health_max"]),
            level,
        )
        threshold_health_heal = (
            _linear_level_value(
                float(effect["heal_min"]),
                float(effect["heal_max"]),
                level,
            )
            + float(effect["heal_bonus_armor_ratio"])
            * float(stats.get("bonus_armor", 0.0))
            + float(effect["heal_bonus_mr_ratio"])
            * float(stats.get("bonus_magic_resistance", 0.0))
        )
        threshold_health_ratio = float(effect["health_threshold"])
        threshold_health_duration = float(effect["duration"])
        assumptions.append(
            "Protoplasm Harness's Lifeline is ready. Before damage would leave "
            "the target below 30% maximum health, it grants temporary bonus "
            "health and begins its five-second heal."
        )
        sources.append(_PROTOPLASM_SOURCE)

    if "Guardian Angel" in names:
        revive_health_amount = float(stats.get("base_health", 0.0)) * float(
            required_effect_value("Guardian Angel", "revive_health_ratio")
        )
        revive_delay = float(required_effect_value("Guardian Angel", "revive_delay"))
        revive_cooldown = float(
            required_effect_value("Guardian Angel", "revive_cooldown")
        )
        assumptions.append(
            "Guardian Angel's Rebirth is ready and restores 50% base health "
            "after four seconds of sourced resurrection stasis."
        )
        sources.append(_GUARDIAN_ANGEL_SOURCE)

    if "Death's Dance" in names:
        is_melee = bool(stats.get("is_melee", False))
        damage_deferral_fraction = float(
            required_effect_value(
                "Death's Dance",
                "damage_deferral_melee" if is_melee else "damage_deferral_ranged",
            )
        )
        damage_deferral_duration = float(
            required_effect_value("Death's Dance", "damage_deferral_duration")
        )
        damage_deferral_ticks = int(
            required_effect_value("Death's Dance", "damage_deferral_ticks")
        )
        defy_window = float(required_effect_value("Death's Dance", "defy_window"))
        defy_heal_bonus_ad_ratio = float(
            required_effect_value("Death's Dance", "defy_heal_bonus_ad_ratio")
        )
        defy_heal_duration = float(
            required_effect_value("Death's Dance", "defy_heal_duration")
        )
        defy_heal_ticks = int(required_effect_value("Death's Dance", "defy_heal_ticks"))
        assumptions.append(
            "Death's Dance Ignore Pain defers the sourced fraction of each "
            "post-mitigation physical or magic packet; Defy clears the "
            "remaining store and heals after a qualifying champion takedown."
        )
        sources.append(_DEATHS_DANCE_SOURCE)

    if "Force of Nature" in names:
        force_stack_duration = float(
            required_effect_value("Force of Nature", "steadfast_stack_duration")
        )
        force_max_stacks = int(
            required_effect_value("Force of Nature", "steadfast_max_stacks")
        )
        force_stack_interval = float(
            required_effect_value("Force of Nature", "steadfast_stack_interval")
        )
        force_immobilize_stacks = int(
            required_effect_value("Force of Nature", "steadfast_immobilize_stacks")
        )
        force_bonus_magic_resistance = float(
            required_effect_value("Force of Nature", "steadfast_bonus_magic_resistance")
        )
        force_bonus_move_speed_percent = float(
            required_effect_value(
                "Force of Nature", "steadfast_bonus_move_speed_percent"
            )
        )
        assumptions.append(
            "Force of Nature Steadfast starts at zero stacks; the ordered ledger "
            "arms one stack per eligible magic-damage cast instance per second "
            "and grants the sourced maximum-stack resistance bonus."
        )
        sources.append(_FORCE_OF_NATURE_SOURCE)

    if "Jak'Sho, The Protean" in names:
        jaksho_stack_interval = float(
            required_effect_value("Jak'Sho, The Protean", "voidborn_stack_interval")
        )
        jaksho_max_stacks = int(
            required_effect_value("Jak'Sho, The Protean", "voidborn_max_stacks")
        )
        jaksho_bonus_resistance_multiplier = float(
            required_effect_value(
                "Jak'Sho, The Protean", "voidborn_bonus_resistance_multiplier"
            )
        )
        assumptions.append(
            "Jak'Sho Voidborn Resilience starts at zero combat seconds and "
            "multiplies bonus armor and magic resistance by 30% after five "
            "seconds in champion combat."
        )
        sources.append(_JAKSHO_SOURCE)

    for stasis_name in ("Zhonya's Hourglass", "Seeker's Armguard"):
        if stasis_name not in names:
            continue
        active_seconds = input_option_float_value(
            [dict(item) for item in items],
            item_options,
            stasis_name,
            "stasis_active_seconds",
        )
        if active_seconds <= 0.0:
            continue
        maximum = float(required_effect_value(stasis_name, "stasis_duration"))
        starting_stasis_duration = min(maximum, active_seconds)
        starting_stasis_source = f"{stasis_name} — Time Stop"
        assumptions.append(
            f"{stasis_name} Time Stop is explicitly active for "
            f"{starting_stasis_duration:g} seconds from the scenario input; "
            "it is never assumed active by item presence alone."
        )
        sources.append(_STASIS_SOURCE)
        break

    has_shield = (
        magic_shield > 0
        or physical_shield > 0
        or general_shield > 0
        or reactive_shield_amount > 0
        or threshold_shield_amount > 0
    )
    if "Spirit Visage" in names and has_shield:
        multiplier = float(ITEM_EFFECTS["Spirit Visage"]["shield_received_multiplier"])
        healing_received_multiplier = multiplier
        magic_shield *= multiplier
        physical_shield *= multiplier
        general_shield *= multiplier
        reactive_shield_amount *= multiplier
        threshold_shield_amount *= multiplier
        assumptions.append("Boundless Vitality increases every modeled shield by 25%.")
        sources.append(_SPIRIT_VISAGE_SOURCE)

    if "Spirit Visage" in names and threshold_health_heal > 0:
        healing_received_multiplier = float(
            ITEM_EFFECTS["Spirit Visage"]["shield_received_multiplier"]
        )
        threshold_health_heal *= float(
            ITEM_EFFECTS["Spirit Visage"]["shield_received_multiplier"]
        )
        assumptions.append(
            "Boundless Vitality increases Protoplasm Harness's modeled healing "
            "by 25%."
        )
        if _SPIRIT_VISAGE_SOURCE not in sources:
            sources.append(_SPIRIT_VISAGE_SOURCE)

    if "Spirit Visage" in names:
        # Boundless Vitality applies to every heal received, including
        # timestamped item/champion heals handled by the participant ledger.
        # Starting shields and Protoplasm's threshold heal above are already
        # pre-resolved with this same multiplier and are not multiplied again
        # by the survival walk.
        healing_received_multiplier = float(
            ITEM_EFFECTS["Spirit Visage"]["shield_received_multiplier"]
        )
        if _SPIRIT_VISAGE_SOURCE not in sources:
            sources.append(_SPIRIT_VISAGE_SOURCE)
        if not any("all modeled heals" in note for note in assumptions):
            assumptions.append(
                "Boundless Vitality increases all modeled healing received by 25%."
            )

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
        reactive_shield_amount=reactive_shield_amount,
        reactive_shield_damage_type=reactive_shield_damage_type,
        reactive_shield_duration=reactive_shield_duration,
        reactive_shield_cooldown=reactive_shield_cooldown,
        reactive_shield_source=reactive_shield_source,
        bloodthirster_shield_cap=bloodthirster_shield_cap,
        bloodthirster_starting_shield=bloodthirster_starting_shield,
        spell_shield_ready=spell_shield_ready,
        spell_shield_source=spell_shield_source,
        basic_damage_multiplier=basic_damage_multiplier,
        incoming_damage_multiplier=incoming_damage_multiplier,
        incoming_damage_linger=incoming_damage_linger,
        incoming_damage_cooldown=incoming_damage_cooldown,
        incoming_damage_source=incoming_damage_source,
        basic_damage_flat_reduction=basic_damage_flat_reduction,
        basic_damage_flat_reduction_cap=basic_damage_flat_reduction_cap,
        critical_strike_damage_multiplier=critical_strike_damage_multiplier,
        healing_received_multiplier=healing_received_multiplier,
        maw_lifeline_omnivamp_percent=maw_lifeline_omnivamp_percent,
        threshold_shield_amount=threshold_shield_amount,
        threshold_shield_health_ratio=threshold_shield_health_ratio,
        threshold_shield_duration=threshold_shield_duration,
        threshold_shield_damage_type=threshold_shield_damage_type,
        threshold_health_bonus=threshold_health_bonus,
        threshold_health_heal=threshold_health_heal,
        threshold_health_ratio=threshold_health_ratio,
        threshold_health_duration=threshold_health_duration,
        revive_health_amount=revive_health_amount,
        revive_delay=revive_delay,
        revive_cooldown=revive_cooldown,
        damage_deferral_fraction=damage_deferral_fraction,
        damage_deferral_duration=damage_deferral_duration,
        damage_deferral_ticks=damage_deferral_ticks,
        defy_window=defy_window,
        defy_heal_bonus_ad_ratio=defy_heal_bonus_ad_ratio,
        defy_heal_duration=defy_heal_duration,
        defy_heal_ticks=defy_heal_ticks,
        force_stack_duration=force_stack_duration,
        force_max_stacks=force_max_stacks,
        force_stack_interval=force_stack_interval,
        force_immobilize_stacks=force_immobilize_stacks,
        force_bonus_magic_resistance=force_bonus_magic_resistance,
        force_bonus_move_speed_percent=force_bonus_move_speed_percent,
        jaksho_stack_interval=jaksho_stack_interval,
        jaksho_max_stacks=jaksho_max_stacks,
        jaksho_bonus_resistance_multiplier=jaksho_bonus_resistance_multiplier,
        starting_stasis_duration=starting_stasis_duration,
        starting_stasis_source=starting_stasis_source,
        assumptions=tuple(assumptions),
        sources=tuple(sources),
        coverage="modeled_starting_defenses",
    )
