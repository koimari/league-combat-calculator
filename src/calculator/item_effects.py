"""Registry and calculation functions for legendary item damage effects.

Each item with a damage-relevant passive/active is registered in ITEM_EFFECTS.
Functions compute bonus damage based on fight context (stats, target, duration).

**Data sourcing:** Values are loaded from the cached item JSON data via
``passive_parser`` whenever the data is available. ``_STATIC_ITEM_EFFECTS``
owns schema and values the parser cannot provide; ``_OFFLINE_ITEM_EFFECTS``
is a complete last-known-good snapshot used only when loading or parsing fails
as a whole. When JSON data is refreshed, ``refresh_item_effects()`` re-parses
and updates ``ITEM_EFFECTS`` in place.
"""

import logging
import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Sequence

logger = logging.getLogger(__name__)


# Shared named-effect source.  Energized is not an item-specific passive: the
# Wiki defines one charge model that every Energized item consumes, then each
# item supplies its own trigger/proc packet.  Keep the source receipt beside
# the typed accessors so a parser refresh cannot silently invent a recharge
# cadence at a call site.
ENERGIZED_SOURCE_RECEIPT: dict[str, Any] = {
    "source_url": "https://wiki.leagueoflegends.com/en-us/Template:Tip_data/Energized",
    "source_revision_id": 4013385,
    "max_stacks": 100,
    "attack_stacks": 6,
    "distance_units_per_stack": 24.0,
}


# Public controls for stateful item stats.  Both validation metadata and the
# sourced numeric mechanics live here so routes/UI never carry item constants.
ITEM_INPUT_OPTIONS: dict[str, dict[str, Any]] = {
    "Dark Seal": {
        "options": {
            "glory_stacks": {
                "type": "int",
                "label": "Glory stacks",
                "default": 0,
                "min": 0,
                "max": 10,
                "step": 1,
                "bonus_ap_per_unit": 4.0,
            }
        },
        "bonus_ap_per_stack": 4.0,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Dark_Seal",
        "source_revision_id": 4015213,
    },
    "Mejai's Soulstealer": {
        "options": {
            "glory_stacks": {
                "type": "int",
                "label": "Glory stacks",
                "default": 0,
                "min": 0,
                "max": 25,
                "step": 1,
                "bonus_ap_per_unit": 5.0,
                "move_speed_threshold": 10,
                "move_speed_percent": 10.0,
            }
        },
        "bonus_ap_per_stack": 5.0,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Mejai's_Soulstealer",
        "source_revision_id": 3902926,
    },
    "Heartsteel": {
        "options": {
            "bonus_health": {
                "type": "int",
                "label": "Permanent bonus health",
                "default": 0,
                "min": 0,
                "max": 10000,
                "step": 10,
                "bonus_health_per_unit": 1.0,
            }
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Heartsteel",
        "source_revision_id": 4044274,
    },
    "Rod of Ages": {
        "options": {
            "timeless_stacks": {
                "type": "int",
                "label": "Timeless stacks",
                "default": 0,
                "min": 0,
                "max": 10,
                "step": 1,
                "bonus_ap_per_unit": 3.0,
                "bonus_health_per_unit": 10.0,
                "bonus_mana_per_unit": 30.0,
            }
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Rod_of_Ages",
        "source_revision_id": 3984371,
    },
    "Actualizer": {
        "options": {
            "mana_made_real_active": {
                "type": "int",
                "label": "Mana Made Real active",
                "default": 0,
                "min": 0,
                "max": 1,
                "step": 1,
            }
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Actualizer",
        "source_revision_id": 3991377,
    },
    "Hubris": {
        "options": {
            "eminence_stacks": {
                "type": "int",
                "label": "Eminence stacks",
                "default": 0,
                "min": 0,
                "max": 1000,
                "step": 1,
            },
            "eminence_active_seconds": {
                "type": "int",
                "label": "Eminence seconds remaining",
                "default": 0,
                "min": 0,
                "max": 90,
                "step": 5,
            },
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Hubris",
        "source_revision_id": 4013949,
    },
    "Endless Hunger": {
        "options": {
            "feast_active_seconds": {
                "type": "int",
                "label": "Feast seconds remaining",
                "default": 0,
                "min": 0,
                "max": 8,
                "step": 1,
            }
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Endless_Hunger",
        "source_revision_id": 4019625,
    },
    "Archangel's Staff": {
        "options": {
            "manaflow_bonus_mana": {
                "type": "int",
                "label": "Manaflow bonus mana",
                "default": 0,
                "min": 0,
                "max": 360,
                "step": 6,
                "bonus_mana_per_unit": 1.0,
            }
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Archangel%27s_Staff",
        "source_revision_id": 3989100,
    },
    "Manamune": {
        "options": {
            "manaflow_bonus_mana": {
                "type": "int",
                "label": "Manaflow bonus mana",
                "default": 0,
                "min": 0,
                "max": 360,
                "step": 6,
                "bonus_mana_per_unit": 1.0,
            }
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Manamune",
        "source_revision_id": 3982212,
    },
    "Whispering Circlet": {
        "options": {
            "manaflow_bonus_mana": {
                "type": "int",
                "label": "Manaflow bonus mana",
                "default": 0,
                "min": 0,
                "max": 360,
                "step": 8,
                "bonus_mana_per_unit": 1.0,
            }
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Whispering_Circlet",
        "source_revision_id": 4015267,
    },
    "Winter's Approach": {
        "options": {
            "manaflow_bonus_mana": {
                "type": "int",
                "label": "Manaflow bonus mana",
                "default": 0,
                "min": 0,
                "max": 360,
                "step": 6,
                "bonus_mana_per_unit": 1.0,
            }
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Winter%27s_Approach",
        "source_revision_id": 3984418,
    },
    "Bloodthirster": {
        "options": {
            "starting_ichorshield": {
                "type": "int",
                "label": "Starting Ichorshield",
                "default": 0,
                "min": 0,
                "max": 315,
                "step": 15,
            }
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Bloodthirster",
        "source_revision_id": 4025103,
    },
    "Yun Tal Wildarrows": {
        "options": {
            "crit_stacks": {
                "type": "int",
                "label": "Practice Makes Lethal stacks",
                "default": 0,
                "min": 0,
                "max": 125,
                "step": 1,
            }
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Yun_Tal_Wildarrows",
        "source_revision_id": 4046569,
    },
    "Overlord's Bloodmail": {
        "options": {
            "missing_health_percent": {
                "type": "int",
                "label": "Starting missing health",
                "default": 0,
                "min": 0,
                "max": 70,
                "step": 5,
            }
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Overlord%27s_Bloodmail",
        "source_revision_id": 4046569,
    },
    "Zhonya's Hourglass": {
        "options": {
            "stasis_active_seconds": {
                "type": "float",
                "label": "Time Stop active seconds",
                "default": 0.0,
                "min": 0.0,
                "max": 2.5,
                "step": 0.5,
            }
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Zhonya's_Hourglass",
        "source_revision_id": 3902922,
    },
    "Seeker's Armguard": {
        "options": {
            "stasis_active_seconds": {
                "type": "float",
                "label": "Time Stop active seconds",
                "default": 0.0,
                "min": 0.0,
                "max": 2.5,
                "step": 0.5,
            }
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Zhonya's_Hourglass",
        "source_revision_id": 3902922,
    },
    # Ally/team actives use an explicit timestamp.  A zero value means that
    # the active was not used in the authored window; the timeline never
    # invents a cast at t=0 merely because the item is equipped.
    "Locket of the Iron Solari": {
        "options": {
            "active_seconds": {
                "type": "float",
                "label": "Devotion active seconds",
                "default": 0.0,
                "min": 0.0,
                "max": 30.0,
                "step": 0.5,
            }
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Locket_of_the_Iron_Solari",
        "source_revision_id": 4022957,
    },
    "Mikael's Blessing": {
        "options": {
            "active_seconds": {
                "type": "float",
                "label": "Purify active seconds",
                "default": 0.0,
                "min": 0.0,
                "max": 30.0,
                "step": 0.5,
            }
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Mikael%27s_Blessing",
        "source_revision_id": 3984364,
    },
    "Redemption": {
        "options": {
            "active_seconds": {
                "type": "float",
                "label": "Intervention active seconds",
                "default": 0.0,
                "min": 0.0,
                "max": 30.0,
                "step": 0.5,
            }
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Redemption",
        "source_revision_id": 4015392,
    },
    "Shurelya's Battlesong": {
        "options": {
            "active_seconds": {
                "type": "float",
                "label": "Inspiring Speech active seconds",
                "default": 0.0,
                "min": 0.0,
                "max": 30.0,
                "step": 0.5,
            }
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Shurelya%27s_Battlesong",
        "source_revision_id": 3984368,
    },
    "Knight's Vow": {
        "options": {
            "worthy_target_index": {
                "type": "int",
                "label": "Worthy ally index",
                "default": 0,
                "min": 0,
                "max": 4,
                "step": 1,
            },
            "worthy_within_range": {
                "type": "int",
                "label": "Worthy ally within 1250 units",
                # The coupled roster represents the selected Worthy ally as
                # the scenario target.  Keep that authored assumption visible
                # and overridable instead of silently inventing a coordinate.
                "default": 1,
                "min": 0,
                "max": 1,
                "step": 1,
            },
            "holder_above_30_percent": {
                "type": "int",
                "label": "Holder above 30% health",
                # The survival walk re-checks this gate at every incoming
                # packet; the input only controls whether the scenario
                # authorizes that sourced branch at all.
                "default": 1,
                "min": 0,
                "max": 1,
                "step": 1,
            },
        },
        "source_url": "https://wiki.leagueoflegends.com/en-us/Knight%27s_Vow",
        "source_revision_id": 4023793,
    },
}


# Typed, source-owned ally/team packets.  These values are deliberately kept
# outside the outgoing-damage registry: the regular item compiler remains the
# authority for the holder's own damage, while this table is the authority for
# cross-participant effects.  Every consumer uses ``ally_item_effect_value``
# so a partial refresh fails loudly instead of borrowing a call-site literal.
ALLY_ITEM_EFFECTS: dict[str, dict[str, Any]] = {
    "Ardent Censer": {
        "sanctify_bonus_attack_speed": 25.0,
        "sanctify_on_hit_magic": 20.0,
        "sanctify_duration": 6.0,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Ardent_Censer",
        "source_revision_id": 4031605,
    },
    "Abyssal Mask": {
        "magic_damage_amp": 0.12,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Abyssal_Mask",
        "source_revision_id": 3984960,
    },
    "Bandlepipes": {
        "fanfare_bonus_move_speed": 20.0,
        "fanfare_duration_melee": 8.0,
        "fanfare_duration_ranged": 4.0,
        "fanfare_ally_attack_speed_melee": 30.0,
        "fanfare_ally_attack_speed_ranged": 20.0,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Bandlepipes",
        "source_revision_id": 4013408,
    },
    "Black Cleaver": {
        "armor_reduction_per_stack": 0.06,
        "armor_reduction_max_stacks": 5,
        "armor_reduction_duration": 6.0,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Black_Cleaver",
        "source_revision_id": 4036012,
    },
    "Bloodletter's Curse": {
        "mr_reduction_per_stack": 0.075,
        "mr_reduction_max_stacks": 4,
        "mr_reduction_duration": 6.0,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Bloodletter%27s_Curse",
        "source_revision_id": 3981906,
    },
    "Bloodsong": {
        "expose_weakness_melee": 0.08,
        "expose_weakness_ranged": 0.05,
        "expose_weakness_duration": 4.0,
        "expose_weakness_cooldown": 1.5,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Bloodsong",
        "source_revision_id": 4028002,
    },
    "Cryptbloom": {
        "life_from_death_base_heal": 100.0,
        "life_from_death_ap_ratio": 0.20,
        "life_from_death_nova_duration": 1.75,
        "life_from_death_cooldown": 60.0,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Cryptbloom",
        "source_revision_id": 3989109,
    },
    "Diadem of Songs": {
        "harmony_bonus_mana_ratio": 0.005,
        "consonance_max_mana_ratio": 0.008,
        "consonance_cooldown": 1.0,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Diadem_of_Songs",
        "source_revision_id": 3993317,
    },
    "Dream Maker": {
        "level_scaling_start": 7,
        "blue_reduction_min": 50.0,
        "blue_reduction_max": 194.0,
        "purple_magic_min": 40.0,
        "purple_magic_max": 160.0,
        "dream_duration": 3.0,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Dream_Maker",
        "source_revision_id": 4030400,
    },
    "Echoes of Helia": {
        "charge_damage_ratio": 0.30,
        "charge_cap_min": 80.0,
        "charge_cap_max": 250.0,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Echoes_of_Helia",
        "source_revision_id": 4046489,
    },
    "Imperial Mandate": {
        "command_damage_amp": 0.07,
        "command_duration": 4.0,
        "control_ability_haste": 20.0,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Imperial_Mandate",
        "source_revision_id": 4034680,
    },
    "Knight's Vow": {
        "redirect_fraction": 0.14,
        "holder_heal_fraction": 0.12,
        "worthy_range_units": 1250.0,
        "holder_health_threshold_ratio": 0.30,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Knight%27s_Vow",
        "source_revision_id": 4023793,
    },
    "Locket of the Iron Solari": {
        "level_scaling_start": 9,
        "shield_min": 290.0,
        "shield_max": 360.0,
        "shield_duration": 2.5,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Locket_of_the_Iron_Solari",
        "source_revision_id": 4022957,
    },
    "Mikael's Blessing": {
        "heal_min": 100.0,
        "heal_max": 250.0,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Mikael%27s_Blessing",
        "source_revision_id": 3984364,
    },
    "Moonstone Renewer": {
        "heal_chain_fraction": 0.30,
        "shield_chain_fraction": 0.35,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Moonstone_Renewer",
        "source_revision_id": 4022988,
    },
    "Redemption": {
        "heal_min": 150.0,
        "heal_max": 350.0,
        "enemy_max_health_true_damage_ratio": 0.10,
        "target_area_range_units": 5500.0,
        "target_area_reveal_duration": 3.0,
        "beam_delay": 2.5,
        "cooldown": 120.0,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Redemption",
        "source_revision_id": 4015392,
    },
    "Shurelya's Battlesong": {
        "bonus_move_speed_percent": 30.0,
        "duration": 4.0,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Shurelya%27s_Battlesong",
        "source_revision_id": 3984368,
    },
    "Solstice Sleigh": {
        "level_scaling_start": 7,
        "bonus_move_speed_percent": 20.0,
        "temporary_health_min": 50.0,
        "temporary_health_max": 230.0,
        "duration": 2.5,
        "cooldown": 30.0,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Solstice_Sleigh",
        "source_revision_id": 4028003,
    },
    "Staff of Flowing Water": {
        "bonus_ability_power": 40.0,
        "bonus_ability_haste": 15.0,
        "duration": 6.0,
        "source_url": "https://wiki.leagueoflegends.com/en-us/Staff_of_Flowing_Water",
        "source_revision_id": 4031602,
    },
}


def ally_item_effect_value(item_name: str, key: str) -> float:
    """Return one required numeric cross-participant item value."""
    record = ALLY_ITEM_EFFECTS.get(item_name)
    if not isinstance(record, Mapping):
        raise KeyError(f"ALLY_ITEM_EFFECTS[{item_name!r}] is missing")
    if key not in record:
        raise KeyError(
            f"ALLY_ITEM_EFFECTS[{item_name!r}] is missing {key!r} — "
            "source/schema bug"
        )
    value = record[key]
    if isinstance(value, bool):
        raise ValueError(f"ALLY_ITEM_EFFECTS[{item_name!r}][{key!r}] must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"ALLY_ITEM_EFFECTS[{item_name!r}][{key!r}] must be numeric"
        ) from exc
    if not math.isfinite(parsed):
        raise ValueError(f"ALLY_ITEM_EFFECTS[{item_name!r}][{key!r}] must be finite")
    return parsed


def ally_item_level_value(
    item_name: str, low_key: str, high_key: str, level: int
) -> float:
    """Interpolate a sourced level-scaled ally packet value.

    The cached Wiki qualifiers sometimes hold the low value through level 6
    or 8 before scaling to level 18.  ``level_scaling_start`` keeps that
    breakpoint in the typed source registry instead of hiding it in a caller.
    """
    low = ally_item_effect_value(item_name, low_key)
    high = ally_item_effect_value(item_name, high_key)
    record = ALLY_ITEM_EFFECTS.get(item_name)
    start = 1
    if isinstance(record, Mapping) and "level_scaling_start" in record:
        start = max(
            1, min(18, int(ally_item_effect_value(item_name, "level_scaling_start")))
        )
    clamped = max(start, min(18, int(level)))
    span = max(1, 18 - start)
    return low + (high - low) * (clamped - start) / span


def _item_option_schemas(config: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    """Return the typed state controls for one item configuration."""
    # Keep compatibility with the original two-option schema while all new
    # controls use the explicit ``options`` mapping.
    if "options" in config:
        return config["options"]
    legacy = config.get("glory_stacks")
    return {"glory_stacks": legacy} if isinstance(legacy, Mapping) else {}


def item_input_options_meta() -> dict[str, dict[str, Any]]:
    """Return the browser-safe controls and provenance for stateful items."""
    metadata: dict[str, dict[str, Any]] = {}
    for item_name, config in ITEM_INPUT_OPTIONS.items():
        schemas = _item_option_schemas(config)
        metadata[item_name] = {
            "options": {
                key: {
                    key2: value2
                    for key2, value2 in schema.items()
                    if not key2.endswith("_per_unit")
                }
                for key, schema in schemas.items()
            },
            "stat_effects": {
                key: {
                    key2: value2
                    for key2, value2 in schema.items()
                    if key2.endswith("_per_unit")
                    or key2 in {"move_speed_threshold", "move_speed_percent"}
                }
                for key, schema in schemas.items()
                if any(
                    key2.endswith("_per_unit")
                    or key2 in {"move_speed_threshold", "move_speed_percent"}
                    for key2 in schema
                )
            },
            "source_url": config["source_url"],
            "source_revision_id": config["source_revision_id"],
        }
    # Yun Tal's crit conversion is sourced from ITEM_EFFECTS rather than the
    # input schema because its melee/ranged caps are part of the item packet.
    if "Yun Tal Wildarrows" in metadata:
        metadata["Yun Tal Wildarrows"]["derived"] = {
            key: required_effect_value("Yun Tal Wildarrows", key)
            for key in (
                "crit_chance_per_stack_melee",
                "crit_chance_per_stack_ranged",
                "crit_stack_max_melee",
                "crit_stack_max_ranged",
                "crit_chance_cap",
            )
        }
    return metadata


def stat_conversion_metadata(item_name: str) -> dict[str, float]:
    """Return browser-safe sourced stat-conversion metadata for one item."""
    effect = ITEM_EFFECTS.get(item_name, {})
    metadata = {}
    keys = (
        "bonus_mana_to_ap_ratio",
        "bonus_mana_to_health_ratio",
        "bonus_health_to_ap_ratio",
        "max_mana_to_ad_ratio",
        "bonus_health_to_ad_ratio",
        "base_ad_to_bonus_ad_ratio",
        "retribution_missing_health_max",
        "item_bonus_health_ratio",
        "ap_per_mana_regen_unit",
        "mana_regen_threshold_percent",
        "rapids_bonus_ap",
        "ultimate_haste",
        "adaptive_force_per_total_move_speed",
        "bonus_mana_to_heal_shield_power_ratio",
        "manaflow_charge_interval",
        "manaflow_max_charges",
        "manaflow_bonus_mana_per_trigger",
        "manaflow_bonus_mana_per_champion",
        "manaflow_bonus_mana_max",
        "manaflow_transform_bonus_mana",
        "timeless_bonus_health_per_stack",
        "timeless_bonus_mana_per_stack",
        "timeless_bonus_ap_per_stack",
        "timeless_max_stacks",
        "feast_omnivamp_percent",
        "feast_duration",
        "feast_trigger_window",
    )
    if item_name in {"Bandlepipes", "Experimental Hexplate"}:
        keys += ("bonus_attack_speed_melee", "bonus_attack_speed_ranged")
    if item_name == "Yun Tal Wildarrows":
        keys += ("bonus_attack_speed_percent",)
    if item_name == "Endless Hunger":
        keys += (
            "famine_base_ability_haste",
            "famine_bonus_ad_to_ability_haste_melee",
            "famine_bonus_ad_to_ability_haste_ranged",
        )
    for key in keys:
        value = effect.get(key)
        if value is not None:
            metadata[key] = float(value)
    return metadata


def validate_item_input_options(value: object) -> dict[str, dict[str, int | float]]:
    """Validate the nested public item-option object."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("item_options must be an object")
    unknown_items = set(value) - set(ITEM_INPUT_OPTIONS)
    if unknown_items:
        raise ValueError(f"Unknown item option target: {sorted(unknown_items)[0]}")

    parsed: dict[str, dict[str, int | float]] = {}
    for item_name, raw_options in value.items():
        if not isinstance(raw_options, Mapping):
            raise ValueError(f"item_options.{item_name} must be an object")
        config = ITEM_INPUT_OPTIONS[item_name]
        schemas = _item_option_schemas(config)
        declared = set(schemas)
        unknown_options = set(raw_options) - declared
        if unknown_options:
            raise ValueError(
                f"Unknown option for {item_name}: {sorted(unknown_options)[0]}"
            )
        parsed[item_name] = {}
        for option_name, option in schemas.items():
            supplied = raw_options.get(option_name, option["default"])
            if option["type"] == "int" and (
                isinstance(supplied, bool) or not isinstance(supplied, int)
            ):
                raise ValueError(
                    f"item_options.{item_name}.{option_name} must be an integer"
                )
            if option["type"] != "int":
                if isinstance(supplied, bool):
                    raise ValueError(
                        f"item_options.{item_name}.{option_name} must be numeric"
                    )
                try:
                    supplied = float(supplied)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"item_options.{item_name}.{option_name} must be numeric"
                    ) from exc
                if not math.isfinite(supplied):
                    raise ValueError(
                        f"item_options.{item_name}.{option_name} must be finite"
                    )
            if not option["min"] <= supplied <= option["max"]:
                raise ValueError(
                    f"item_options.{item_name}.{option_name} must be between "
                    f"{option['min']} and {option['max']}"
                )
            parsed[item_name][option_name] = supplied
    return parsed


def _input_option_stat_bonuses(
    items: list[dict[str, Any]],
    item_options: Mapping[str, Mapping[str, int]] | None,
) -> tuple[float, float, float, float]:
    """Return AP, move speed, health, and mana from equipped item state."""
    if not item_options:
        return 0.0, 0.0, 0.0, 0.0
    equipped = _item_names(items)
    bonus_ap = 0.0
    move_speed_percent = 0.0
    bonus_health = 0.0
    bonus_mana = 0.0
    for item_name, options in item_options.items():
        if item_name not in equipped or item_name not in ITEM_INPUT_OPTIONS:
            continue
        config = ITEM_INPUT_OPTIONS[item_name]
        for option_name, schema in _item_option_schemas(config).items():
            units = options.get(option_name, schema["default"])
            bonus_ap += units * schema.get("bonus_ap_per_unit", 0.0)
            bonus_health += units * schema.get("bonus_health_per_unit", 0.0)
            bonus_mana += units * schema.get("bonus_mana_per_unit", 0.0)
            threshold = schema.get("move_speed_threshold")
            if threshold is not None and units >= threshold:
                move_speed_percent += schema["move_speed_percent"]
    return bonus_ap, move_speed_percent, bonus_health, bonus_mana


def input_option_stat_bonuses(
    items: list[dict[str, Any]],
    item_options: Mapping[str, Mapping[str, int]] | None,
) -> tuple[float, float, float, float]:
    """Return sourced stat deltas from explicit item state controls."""
    return _input_option_stat_bonuses(items, item_options)


def input_option_crit_chance(
    items: list[dict[str, Any]],
    item_options: Mapping[str, Mapping[str, int]] | None,
    *,
    is_melee: bool,
) -> float:
    """Return explicit permanent crit chance from item state, in percent.

    Yun Tal's Practice Makes Lethal stacks are long-lived scenario state. The
    typed accessor owns the melee/ranged caps and parser-backed per-stack
    values; this adapter only converts its fractional result to the percent
    units used by the public stat bundle.
    """
    if "Yun Tal Wildarrows" not in _item_names(items) or not item_options:
        return 0.0
    options = item_options.get("Yun Tal Wildarrows")
    if not options:
        return 0.0
    stacks = options.get("crit_stacks", 0)
    return 100.0 * yun_tal_permanent_crit_chance(
        stacks=stacks,
        is_melee=is_melee,
        item_name="Yun Tal Wildarrows",
    )


def input_option_value(
    items: list[dict[str, Any]],
    item_options: Mapping[str, Mapping[str, int]] | None,
    item_name: str,
    option_name: str,
) -> int:
    """Return one validated bounded state value for an equipped item."""
    if not item_options or item_name not in _item_names(items):
        return 0
    options = item_options.get(item_name) or {}
    return int(options.get(option_name, 0) or 0)


def input_option_float_value(
    items: list[dict[str, Any]],
    item_options: Mapping[str, Mapping[str, int | float]] | None,
    item_name: str,
    option_name: str,
) -> float:
    """Return one validated numeric item-state value without truncation."""
    if not item_options or item_name not in _item_names(items):
        return 0.0
    options = item_options.get(item_name) or {}
    value = options.get(option_name, 0.0)
    if isinstance(value, bool):
        raise ValueError(f"item_options.{item_name}.{option_name} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"item_options.{item_name}.{option_name} must be numeric"
        ) from exc
    if not math.isfinite(parsed):
        raise ValueError(f"item_options.{item_name}.{option_name} must be finite")
    schema = _item_option_schemas(ITEM_INPUT_OPTIONS[item_name]).get(option_name)
    if schema is None:
        raise ValueError(f"Unknown option for {item_name}: {option_name}")
    if not float(schema["min"]) <= parsed <= float(schema["max"]):
        raise ValueError(
            f"item_options.{item_name}.{option_name} must be between "
            f"{schema['min']} and {schema['max']}"
        )
    return parsed


def hubris_input_bonus_ad(
    items: list[dict[str, Any]],
    item_options: Mapping[str, Mapping[str, int]] | None,
) -> float:
    """Return Hubris Eminence AD while its explicit window is active."""
    if "Hubris" not in _item_names(items):
        return 0.0
    stacks = input_option_value(items, item_options, "Hubris", "eminence_stacks")
    active_seconds = input_option_value(
        items, item_options, "Hubris", "eminence_active_seconds"
    )
    return hubris_eminence_bonus_ad(
        stacks=stacks,
        active=active_seconds > 0,
        item_name="Hubris",
    )


def endless_hunger_input_omnivamp(
    items: list[dict[str, Any]],
    item_options: Mapping[str, Mapping[str, int]] | None,
) -> float:
    """Return Feast's explicit remaining-window omnivamp percentage."""
    if "Endless Hunger" not in _item_names(items):
        return 0.0
    remaining = input_option_value(
        items, item_options, "Endless Hunger", "feast_active_seconds"
    )
    if remaining <= 0:
        return 0.0
    return required_effect_value("Endless Hunger", "feast_omnivamp_percent")


def swiftmarch_adaptive_force(
    items: list[dict[str, Any]],
    *,
    total_move_speed: float,
    item_name: str = "Swiftmarch",
) -> float:
    """Return Noxian Fervor's adaptive force from total movement speed."""
    if item_name not in _item_names(items):
        return 0.0
    ratio = required_effect_value(item_name, "adaptive_force_per_total_move_speed")
    return max(0.0, float(total_move_speed)) * float(ratio)


def item_option_active(
    items: list[dict[str, Any]],
    item_options: Mapping[str, Mapping[str, int]] | None,
    item_name: str,
    option_name: str,
) -> bool:
    """Return whether a boolean-like integer item state is active."""
    return input_option_value(items, item_options, item_name, option_name) > 0


# ---------------------------------------------------------------------------
# Complete offline item effect snapshot
# ---------------------------------------------------------------------------
# Normal cached-data operation does not merge from this table. It is the
# explicit whole-system fallback and the parity reference for parser updates.
_OFFLINE_ITEM_EFFECTS: dict[str, dict[str, Any]] = {
    # ── Ordered sustain packets ─────────────────────────────────────────
    # These values are intentionally registry-owned.  The cached item JSON
    # still supplies ordinary stats, but the current Wiki entries describe
    # the stateful heal/regen branches below and those branches are not
    # reliably represented in the Riot description cache.
    "Doran's Blade": {
        "type": "sustain",
        "direct_heal_post_mitigation_ratio": 0.025,
        "direct_heal_aoe_effectiveness": 0.333,
        # The current entry replaced the old Warmonger omnivamp stat with
        # Life Draining.  Keep the override beside the sourced replacement so
        # a stale cache value cannot leak into the public stat bundle.
        "stat_override_omnivamp_percent": 0.0,
    },
    "Doran's Ring": {
        "type": "sustain",
        "drain_restoration_per_second": 1.0,
        "drain_combat_restoration_per_second": 2.0,
        "drain_combat_duration": 5.0,
        "drain_health_conversion": 0.45,
        "drain_tick_interval": 1.0,
    },
    "Doran's Shield": {
        "type": "sustain",
        "enduring_focus_total_melee": 40.0,
        "enduring_focus_total_reduced": 30.0,
        "enduring_focus_missing_health_cap": 0.75,
        "enduring_focus_duration": 8.0,
        "health_regen_tick_interval": 0.5,
    },
    # ── On-Hit (per auto attack) ──────────────────────────────────────────
    "Cull": {
        "type": "on_hit_heal",
        # Reap's Riot description explicitly says each on-hit restores 3
        # health.  The cached passive branch only contains the quest/gold
        # progression, so this sourced value is intentionally code-owned;
        # the progression remains fail-closed in item_coverage.py.
        "health_per_on_hit": 3.0,
    },
    "Nashor's Tooth": {
        "type": "on_hit",
        "formula": "flat_ap",
        "damage_type": "magic",
        "base": 15.0,
        "ap_ratio": 0.15,
    },
    "Blade of the Ruined King": {
        "type": "on_hit",
        "formula": "current_hp",
        "damage_type": "physical",
        "current_hp_ratio_melee": 0.09,
        "current_hp_ratio_ranged": 0.06,
        "min_damage": 5.0,  # Flat minimum when target HP is modeled at 0
    },
    "Wit's End": {
        "type": "on_hit",
        "formula": "flat",
        "damage_type": "magic",
        "base": 45.0,
    },
    "Recurve Bow": {
        "type": "on_hit",
        "formula": "flat",
        "damage_type": "physical",
        "base": 15.0,
    },
    "Terminus": {
        "type": "on_hit",
        "formula": "flat_bonus_ad_ap",
        "damage_type": "magic",
        "base": 30.0,
        "bonus_ad_ratio": 0.10,
        "ap_ratio": 0.10,
        # Juxtaposition: alternating Light/Dark hits, each stacks up to 3 times.
        # Dark hits (2nd, 4th, 6th auto): 10% armor/magic pen per stack
        "dark_pen_per_stack": 0.10,
        "dark_max_stacks": 3,
        # Light hits (1st, 3rd, 5th auto): bonus armor + MR per stack (level-scaled)
        "light_resist_min": 6.0,  # per stack at level 1
        "light_resist_max": 8.0,  # per stack at max level
    },
    "Titanic Hydra": {
        "type": "on_hit",
        "formula": "max_hp",
        "secondary_behavior": "auto_cooldown",
        "damage_type": "physical",
        "max_hp_ratio_melee": 0.01,
        "max_hp_ratio_ranged": 0.005,
        # Cleave cone packet to each nearby secondary target.
        "secondary_max_hp_ratio_melee": 0.03,
        "secondary_max_hp_ratio_ranged": 0.015,
        # Titanic Crescent active: empowered Cleave on next auto (10s CD)
        "active_max_hp_ratio_melee": 0.04,
        "active_max_hp_ratio_ranged": 0.02,
        "active_secondary_max_hp_ratio_melee": 0.09,
        "active_secondary_max_hp_ratio_ranged": 0.045,
        "active_cooldown": 10.0,
    },
    "Guinsoo's Rageblade": {
        "type": "on_hit",
        "formula": "flat",
        "damage_type": "magic",
        "base": 30.0,
        # Phantom Hit: 3 autos to max Seething Strike stacks. The 4th auto
        # both maxes Seething AND starts Phantom stacking. So:
        #   Auto 4: Seething 4 (max) + Phantom stack 1
        #   Auto 5: Phantom stack 2
        #   Auto 6: PHANTOM HIT (consumes stacks)
        # After that, every 3rd auto triggers another (9, 12, 15, 18...).
        # Phantom hit applies ALL on-hit effects an additional time.
        "phantom_hit": True,
        "stacking_autos": 5,  # Autos before first phantom hit (6th triggers)
        "phantom_interval": 3,  # Every 3rd auto after first phantom hit
        "seething_attack_speed_per_stack": 0.08,
        "seething_max_stacks": 4,
        "seething_duration": 3.0,
        "phantom_duration": 6.0,
        "phantom_stacks_required": 2,
    },
    "Muramana": {
        "type": "on_hit",
        "formula": "max_mana",
        "secondary_behavior": "per_ability_hit",
        "damage_type": "physical",
        "max_mana_ratio_on_hit": 0.012,
        "max_mana_ratio_ability_melee": 0.04,
        "max_mana_ratio_ability_ranged": 0.03,
        # Awe passive: 2% max mana as bonus AD (stat conversion)
        "max_mana_to_ad_ratio": 0.02,
    },
    "Endless Hunger": {
        "type": "stat_conversion",
        "famine_base_ability_haste": 5.0,
        "famine_bonus_ad_to_ability_haste_melee": 0.13,
        "famine_bonus_ad_to_ability_haste_ranged": 0.10,
        "feast_omnivamp_percent": 15.0,
        "feast_duration": 8.0,
        "feast_trigger_window": 3.0,
    },
    # ── Spellblade (after ability, next auto, mutually exclusive) ─────────
    "Sheen": {
        "type": "spellblade",
        "formula": "base_ad",
        "damage_type": "physical",
        "base_ad_ratio": 1.0,
        "cooldown": 1.5,
        "weave_delay": 1.5,  # CD starts after empowered attack
    },
    "Trinity Force": {
        "type": "spellblade",
        "formula": "base_ad",
        "damage_type": "physical",
        "base_ad_ratio": 2.0,
        "cooldown": 1.5,
        "weave_delay": 1.5,  # CD starts after empowered attack
    },
    "Lich Bane": {
        "type": "spellblade",
        "formula": "base_ad_ap",
        "damage_type": "magic",
        "base_ad_ratio": 0.75,
        "ap_ratio": 0.45,
        # Spellblade's empowered attack also gains 50% bonus attack speed.
        "bonus_attack_speed_percent": 50.0,
        "cooldown": 1.5,
        "weave_delay": 1.5,  # CD starts after empowered attack
    },
    "Essence Reaver": {
        "type": "spellblade",
        "formula": "base_ad_crit",
        "damage_type": "physical",
        "base_ad_ratio": 1.25,
        # Bonus damage scales 0-50 based on crit chance
        "crit_bonus_max": 50.0,
        # Manaflow restores half of Spellblade's damage formula: 62.5% base
        # AD plus up to 25% of bonus AD at 100% crit chance.
        "mana_restore_base_ad_ratio": 0.625,
        "mana_restore_crit_ratio": 0.25,
        "cooldown": 1.5,
        "weave_delay": 1.5,  # CD starts after empowered attack
    },
    "Iceborn Gauntlet": {
        "type": "spellblade",
        "formula": "base_ad",
        "damage_type": "physical",
        "base_ad_ratio": 1.50,
        "cooldown": 1.5,
        "weave_delay": 1.5,  # CD starts after empowered attack
    },
    "Bloodsong": {
        "type": "spellblade",
        "formula": "base_ad",
        "damage_type": "physical",
        "base_ad_ratio": 1.0,
        "cooldown": 1.5,
        "weave_delay": 1.5,  # CD starts after empowered attack
        "expose_weakness_melee": 0.08,
        "expose_weakness_ranged": 0.05,
    },
    "Dusk and Dawn": {
        "type": "spellblade",
        "formula": "base_ad_ap",
        "damage_type": "magic",
        "base_ad_ratio": 0.75,
        "ap_ratio": 0.10,
        "cooldown": 1.5,
        "weave_delay": 1.5,  # CD starts after empowered attack
        "double_on_hit": True,  # Applies all on-hit effects again
        "self_heal_ap_ratio": 0.10,
        "self_heal_bonus_health_ratio": 0.03,
    },
    # ── Burn / DoT ────────────────────────────────────────────────────────
    "Fated Ashes": {
        "type": "burn",
        "formula": "flat",
        "damage_type": "magic",
        # Inflame: 2.5 per 0.5s for 3s = 15 total, no AP scaling
        "base_total": 15.0,
        "duration": 3.0,
        "tick_interval": 0.5,
    },
    "Liandry's Torment": {
        "type": "burn",
        "formula": "max_hp",
        "damage_type": "magic",
        # 1% max HP every 0.5s for 3s = 6% max HP total
        "max_hp_ratio_total": 0.06,
        "duration": 3.0,
        "tick_interval": 0.5,
        # Suffering: 2% increased damage per second, up to 6%
        "damage_amp_per_second": 0.02,
        "damage_amp_max": 0.06,
    },
    "Blackfire Torch": {
        "type": "burn",
        "formula": "flat_ap",
        "damage_type": "magic",
        # 10 + 1% AP per 0.5s for 3s = 60 + 6% AP total
        "base_total": 60.0,
        "ap_ratio_total": 0.06,
        "duration": 3.0,
        "tick_interval": 0.5,
        # 4% bonus AP per burning champion
        "ap_amp_per_target": 0.04,
    },
    "Sunfire Aegis": {
        "type": "immolate",
        "formula": "bonus_hp_dps",
        "damage_type": "magic",
        "event_interval": 1.0,
        # 20 + 1% bonus HP per second
        "base_per_second": 20.0,
        "bonus_hp_ratio_per_second": 0.01,
    },
    "Hollow Radiance": {
        "type": "immolate",
        "formula": "bonus_hp_dps",
        "damage_type": "magic",
        "event_interval": 1.0,
        # 15 + 1% bonus HP per second
        "base_per_second": 15.0,
        "bonus_hp_ratio_per_second": 0.01,
    },
    "Bami's Cinder": {
        "type": "immolate",
        "formula": "flat_dps",
        "damage_type": "magic",
        "event_interval": 1.0,
        # Flat 15 per second (bonus-health scaling removed in V14.19)
        "base_per_second": 15.0,
    },
    # ── Proc Damage (cooldown-gated) ──────────────────────────────────────
    "Luden's Echo": {
        "type": "proc",
        "formula": "charged_ap",
        "trigger": "ability_damage",
        "damage_type": "magic",
        # 6 charges, single target: primary + 5 × 20% = ×2.0 multiplier
        "base_per_charge": 75.0,
        "ap_ratio_per_charge": 0.05,
        "charges": 6,
        "single_target_multiplier": 2.0,
        "cooldown": 12.0,
    },
    "Statikk Shiv": {
        "type": "on_hit_once",
        "formula": "flat",
        "uses_empowered_auto_count": True,
        "breakdown_key": "on_hit_once_Statikk Shiv",
        "display_name": "Statikk Shiv (Electrospark)",
        "damage_type": "magic",
        # Electrospark: ONE empowered attack deals 60 bonus magic damage,
        # chain-lightning to up to 4-8 targets by level (single-target: 1 proc)
        "base": 60.0,
        "empowered_auto_count": 1,
        "chain_targets_min": 4,
        "chain_targets_max": 8,
        "energized_max_stacks": 100,
        "energized_attack_stacks": 15,
        "energized_distance_units_per_stack": 24.0,
    },
    "Stormsurge": {
        "type": "proc",
        "formula": "flat_ap",
        "trigger": "damage_threshold",
        "repeat_on_cooldown": False,
        "damage_type": "magic",
        # 125 + 10% AP, 30s CD (triggers at 25% HP damage in 2.5s)
        "base": 125.0,
        "ap_ratio": 0.10,
        "cooldown": 30.0,
        # Squall arms after this share of the target's max health is
        # dealt within the rolling window below (Stormraider's trigger).
        "damage_threshold_ratio": 0.25,
        "damage_threshold_window": 2.5,
        "is_ability_damage": True,  # Amplified by Actualizer
    },
    "Hextech Alternator": {
        "type": "proc",
        "formula": "flat",
        "trigger": "champion_damage",
        "damage_type": "magic",
        # Revved: 65 bonus magic damage on damaging a champion, 40s CD
        "base": 65.0,
        "cooldown": 40.0,
    },
    "Scout's Slingshot": {
        "type": "proc",
        "formula": "flat",
        "trigger": "champion_damage",
        "damage_type": "magic",
        # Bullseye: 40 bonus magic damage on damaging a champion.
        # 40s CD, refunded 1s per completed attack windup.
        "base": 40.0,
        "cooldown": 40.0,
        "attack_refund": True,
        "on_attack_cooldown_refund": 1.0,
        # Wiki notes: Bullseye's damage triggers spell effects.
        "is_ability_damage": True,
    },
    "Zaz'Zak's Realmspike": {
        "type": "proc",
        "formula": "flat_ap_max_hp",
        "trigger": "ability_damage",
        "damage_type": "magic",
        # 10 + 15% AP + 3% target max HP, 10s CD
        "base": 10.0,
        "ap_ratio": 0.15,
        "target_max_hp_ratio": 0.03,
        "cooldown": 10.0,
        "is_ability_damage": True,  # Amplified by Actualizer
    },
    # ── Ultimate Proc ─────────────────────────────────────────────────────
    "Malignance": {
        "type": "ult_proc",
        "ultimate_haste": 20.0,
        "formula": "flat_ap",
        "damage_type": "magic",
        # Hatefog: (60 + 5% AP) per second for 3s = 180 + 15% AP per
        # application.  Each R dash refreshes the zone timer, extending
        # effective duration to (R_dash_spread + 3) seconds.
        "base": 180.0,
        "ap_ratio": 0.15,
        "duration": 3.0,
        # Also reduces target MR by 10 for 3s
        "mr_reduction": 10.0,
    },
    # ── Active Items (used once per fight) ────────────────────────────────
    "Hextech Rocketbelt": {
        "type": "active",
        "formula": "flat_ap",
        "damage_type": "magic",
        # 100 + 10% AP magic damage
        "base": 100.0,
        "ap_ratio": 0.10,
        "cooldown": 40.0,
    },
    "Profane Hydra": {
        "type": "active",
        "cleave_on_hit": True,
        "formula": "total_ad",
        "damage_type": "physical",
        "secondary_ad_ratio_melee": 0.40,
        "secondary_ad_ratio_ranged": 0.20,
        # Active: 80% total AD
        "total_ad_ratio": 0.80,
        "cooldown": 10.0,
    },
    "Hextech Gunblade": {
        "type": "active",
        "formula": "level_ap",
        "damage_type": "magic",
        # Lightning Bolt: 175-262 (scales linearly levels 1-20) + 30% AP
        "base_min": 175.0,
        "base_max": 262.0,
        "ap_ratio": 0.30,
        "cooldown": 60.0,
    },
    "Ravenous Hydra": {
        "type": "active",
        "cleave_on_hit": True,
        "formula": "total_ad",
        "damage_type": "physical",
        "secondary_ad_ratio_melee": 0.40,
        "secondary_ad_ratio_ranged": 0.20,
        # Ravenous Crescent: 80% total AD
        "total_ad_ratio": 0.80,
        # Cleave and Ravenous Crescent both explicitly apply life steal at
        # full effectiveness.  This value is parser-owned from the cached
        # branch text, not a call-site fallback.
        "lifesteal_effectiveness": 1.0,
        "cooldown": 10.0,
    },
    "Runaan's Hurricane": {
        "type": "secondary_target",
        "secondary_ad_ratio": 0.55,
        "max_secondary_targets": 2,
        "applies_on_hit": True,
    },
    "Tiamat": {
        "type": "active",
        "cleave_on_hit": True,
        "formula": "total_ad",
        "damage_type": "physical",
        "secondary_ad_ratio_melee": 0.40,
        "secondary_ad_ratio_ranged": 0.20,
        # Crescent: 75% total AD
        "total_ad_ratio": 0.75,
        "cooldown": 10.0,
        # Cleave (the on-hit passive) strikes OTHER enemies in a radius
        # around the attack target — it never damages the selected target,
        # so its splash belongs to the shared multi-target roster model.
        "unmodeled_splash_note": (
            "Tiamat's Cleave splashes other enemies only and adds no damage "
            "against the selected target; its splash belongs to the "
            "multi-target roster model."
        ),
    },
    "Stridebreaker": {
        "type": "active",
        "cleave_on_hit": True,
        "formula": "total_ad",
        "damage_type": "physical",
        "secondary_ad_ratio_melee": 0.40,
        "secondary_ad_ratio_ranged": 0.20,
        # Breaking Shockwave: 80% total AD + slow
        "total_ad_ratio": 0.80,
        "cooldown": 15.0,
    },
    # Note: Goredrinker, Everfrost, Galeforce, Prowler's Claw are
    # DISTRIBUTED items (Arena only) — not available on Summoner's Rift.
    # ── Damage Amplification ──────────────────────────────────────────────
    # Liandry's amp is handled in its burn entry above.
    "Riftmaker": {
        "type": "damage_amp",
        # 2% per second in combat, up to 8% (4 stacks)
        "amp_per_second": 0.02,
        "amp_max": 0.08,
        "max_stack_omnivamp": 10.0,
        # Void Infusion: 2% of bonus health as ability power.
        "bonus_health_to_ap_ratio": 0.02,
    },
    "Haunting Guise": {
        "type": "damage_amp",
        # Madness: 2% per second in combat, up to 6% (3 stacks)
        "amp_per_second": 0.02,
        "amp_max": 0.06,
    },
    "Lord Dominik's Regards": {
        "type": "damage_amp",
        # 0-15% bonus damage based on target's bonus health
        # Scales linearly: 0% at 0 bonus HP, 15% at 1500+ bonus HP
        "max_amp": 0.15,
        "bonus_hp_cap": 1500.0,
    },
    "Spear of Shojin": {
        "type": "damage_amp",
        # 3% increased ability damage per stack, max 4 stacks = 12%
        "amp_per_stack": 0.03,
        "max_stacks": 4,
        # Dragonforce: 25 basic ability haste (Q, W, E only)
        "basic_ability_haste": 25.0,
    },
    "Hexoptics C44": {
        "type": "basic_damage_amp",
        # Magnification: 0-10% increased basic damage based on distance
        # 1% per 50 units, max 10% at 500 units. Ranged champs are assumed
        # at max distance (full amp); melee champs at ~100 units, which
        # scales the amp down linearly (2% with current values).
        "max_amp": 0.10,
        "max_distance": 500.0,
        "melee_assumed_distance": 100.0,
    },
    "Horizon Focus": {
        "type": "hypershot_amp",
        # Hypershot: 10% increased damage after hitting with an ability
        # at 600+ range. We always assume max range (amp active).
        # First ability triggers the mark — its own damage is NOT amped.
        "amp": 0.10,
    },
    "Abyssal Mask": {
        "type": "magic_damage_amp",
        # Enemies within 700 units take 12% increased magic damage
        "magic_amp": 0.12,
    },
    "Actualizer": {
        "type": "ability_damage_amp",
        # Mana Made Real active: 15% + 0.5% per 100 bonus mana
        # increased ability damage
        "base_amp": 0.15,
        "amp_per_100_bonus_mana": 0.005,
        "mana_made_real_duration": 8.0,
        "mana_cost_multiplier": 2.0,
        "basic_cooldown_progress_multiplier": 1.30,
        "mana_made_real_cooldown": 60.0,
    },
    # ── Ultimate-Triggered Attack Speed Buffs ──────────────────────────────
    "Experimental Hexplate": {
        "type": "ult_attack_speed_buff",
        "ultimate_haste": 30.0,
        # Overdrive: melee 50% / ranged 35% bonus AS (+ MS) for 8s on R cast,
        # 30s CD.
        "bonus_attack_speed_melee": 50.0,
        "bonus_attack_speed_ranged": 35.0,
        "duration": 8.0,
        "cooldown": 30.0,
    },
    "Fiendhunter Bolts": {
        "type": "ult_empowered_autos",
        "ultimate_haste": 30.0,
        # After R, next 3 autos within 8s gain 50% bonus AS and
        # guaranteed crit at 80% crit damage. If would have naturally
        # crit, deals normal crit + 15% of AD as true damage.
        "bonus_attack_speed_percent": 50.0,
        "empowered_auto_count": 3,
        "reduced_crit_ratio": 0.80,
        "natural_crit_true_damage_ratio": 0.15,
        "duration": 8.0,
    },
    # ── Max HP Proc (cooldown-gated, %max HP physical) ────────────────────
    "Eclipse": {
        "type": "max_hp_proc",
        "formula": "max_hp",
        "breakdown_key": "proc_Eclipse",
        "display_name": "Eclipse (Ever Rising Moon)",
        "damage_type": "physical",
        # Ever Rising Moon: 2 stacks within 2s deals bonus physical damage
        # Melee 6% / Ranged 4% of target's maximum health
        "target_max_hp_ratio_melee": 0.06,
        "target_max_hp_ratio_ranged": 0.04,
        # The passive arms on two separate champion hits within this window;
        # the completed pair starts the per-target cooldown.
        "stack_required": 2,
        "stack_window": 2.0,
        "cooldown": 6.0,
        # Ever Rising Moon's self-shield is attached to the exact completed
        # pair event and consumed by the coupled participant timeline.
        "shield_melee_base": 160.0,
        "shield_ranged_base": 80.0,
        "shield_melee_bonus_ad_ratio": 0.40,
        "shield_ranged_bonus_ad_ratio": 0.20,
        "shield_duration": 2.0,
    },
    # ── Lethality Proc (ability damage trigger) ──────────────────────────
    "Bastionbreaker": {
        "type": "shaped_charge",
        # Shaped Charge: next ability damage deals bonus true damage
        # Melee: 50 + 1.5 per lethality, Ranged: 25 + 0.75 per lethality
        "base_melee": 50.0,
        "base_ranged": 25.0,
        "lethality_ratio_melee": 1.5,
        "lethality_ratio_ranged": 0.75,
        "cooldown": 20.0,
    },
    # ── Reactive strike-back (consumed by the coupled timeline) ───────────
    "Bramble Vest": {
        "type": "thorns",
        "damage_type": "magic",
        # Thorns: 10 magic damage to each basic-attack striker, who is
        # also wounded for 3 seconds. Fires only from modeled incoming
        # attack events — never assumed in a one-attacker fight.
        "base": 10.0,
        "bonus_armor_ratio": 0.0,
        "grievous_duration": 3.0,
    },
    "Thornmail": {
        "type": "thorns",
        "damage_type": "magic",
        "base": 20.0,
        "bonus_armor_ratio": 0.10,
        "grievous_duration": 3.0,
    },
    # ── Resistance Reduction ──────────────────────────────────────────────
    "Black Cleaver": {
        "type": "armor_reduction",
        # 6% armor reduction per stack, up to 5 stacks = 30%
        "reduction_per_stack": 0.06,
        "max_stacks": 5,
    },
    "Bloodletter's Curse": {
        "type": "mr_reduction_stacking",
        # Vile Decay: 7.5% MR reduction per stack, up to 4 stacks = 30%
        # Each magic damage ability applies one stack; the ability's own
        # damage benefits from the stack it applies.
        "mr_reduction_per_stack": 0.075,
        "max_stacks": 4,
    },
    # ── Execute ───────────────────────────────────────────────────────────
    "The Collector": {
        "type": "execute",
        # Execute below 5% max HP
        "threshold": 0.05,
    },
    # ── Critical Strike ───────────────────────────────────────────────────
    "Infinity Edge": {
        "type": "crit_modifier",
        # +30% crit damage (200% -> 230%)
        "bonus_crit_damage": 0.30,
    },
    "Navori Flickerblade": {
        "type": "crit_modifier",
        # Basic attacks reduce basic ability remaining CDs by 15%
        "cd_refund_percent": 0.15,
    },
    # ── Magic/True Critical Strike ──────────────────────────────────────
    "Shadowflame": {
        "type": "magic_true_crit",
        # Cinderbloom: magic and true damage critically strike for 120%
        # against enemies below 40% maximum health
        "crit_multiplier": 1.20,
        "health_threshold": 0.40,
    },
    # ── Energized ──────────────────────────────────────────────────────────
    "Rapid Firecannon": {
        "type": "on_hit_once",
        "formula": "flat",
        "breakdown_key": "on_hit_once_Rapid Firecannon",
        "display_name": "Rapid Firecannon (Sharpshooter)",
        "damage_type": "magic",
        # Sharpshooter: 40 bonus magic damage on first energized auto
        "base": 40.0,
        "energized_max_stacks": 100,
        "energized_attack_stacks": 6,
        "energized_distance_units_per_stack": 24.0,
    },
    # ── Other single-proc items ───────────────────────────────────────────
    "Dead Man's Plate": {
        "type": "on_hit_once",
        "formula": "flat_base_ad",
        "breakdown_key": "on_hit_once_Dead Man's Plate",
        "display_name": "Dead Man's Plate (first hit)",
        "damage_type": "physical",
        # At max momentum: 40 + 100% base AD
        "base": 40.0,
        "base_ad_ratio": 1.0,
    },
    "Heartsteel": {
        "type": "on_hit_once",
        "formula": "flat_max_hp",
        "breakdown_key": "on_hit_once_Heartsteel",
        "display_name": "Heartsteel (Colossal Consumption)",
        "damage_type": "physical",
        # Colossal Consumption: 70 + 6% max HP bonus physical damage
        # 30s cooldown — assumed to proc once per fight
        "base": 70.0,
        "max_hp_ratio": 0.06,
        "cooldown": 30.0,
        "permanent_bonus_health_ratio": 0.10,
        # Wiki Damage tags: this item proc is tagged BasicAttack.
        "basic_damage": True,
    },
    "Hullbreaker": {
        "type": "on_hit_stacking",
        "formula": "base_ad_max_hp",
        "breakdown_key": "on_hit_Hullbreaker",
        "display_name": "Hullbreaker (Skipper)",
        "damage_type": "physical",
        # Skipper: every 5th on-hit application against any target.
        # At max stacks, next auto vs champion deals:
        #   Melee: 120% base AD + 5% champion max HP
        #   Ranged: 84% base AD + 3.5% champion max HP
        "base_ad_ratio_melee": 1.20,
        "base_ad_ratio_ranged": 0.84,
        "max_hp_ratio_melee": 0.05,
        "max_hp_ratio_ranged": 0.035,
        "hits_required": 5,
    },
    "Kraken Slayer": {
        "type": "on_hit_stacking",
        "formula": "level_missing_hp",
        "breakdown_key": "on_hit_Kraken Slayer",
        "display_name": "Kraken Slayer (Bring It Down)",
        "damage_type": "physical",
        # Every 3rd hit. Base damage is flat from levels 1-8, then scales
        # per level from 9 onward:
        #   Melee: 150 base, +5/level from 9  (level 18 = 200, level 20 = 210)
        #   Ranged: 120 base, +4/level from 9 (level 18 = 160, level 20 = 168)
        # Bonus: +5% damage per 6.667% target missing HP (max +75% at 0 HP)
        "base_melee": 150.0,
        "per_level_melee": 5.0,
        "base_ranged": 120.0,
        "per_level_ranged": 4.0,
        "scaling_start_level": 9,
        "missing_hp_bonus_max": 0.75,
        "hits_required": 3,
        # Wiki Damage tags: this item proc is tagged BasicAttack.
        "basic_damage": True,
    },
    # ── Stat Conversion (passives that modify champion stats) ──────────────
    "Rabadon's Deathcap": {
        "type": "stat_conversion",
        "ap_percent_increase": 0.30,
    },
    "Archangel's Staff": {
        "type": "stat_conversion",
        "bonus_mana_to_ap_ratio": 0.01,
        "manaflow_charge_interval": 8.0,
        "manaflow_max_charges": 5,
        "manaflow_bonus_mana_per_trigger": 5.0,
        "manaflow_bonus_mana_per_champion": 10.0,
        "manaflow_bonus_mana_max": 360.0,
        "manaflow_transform_bonus_mana": 360.0,
    },
    "Manamune": {
        "type": "stat_conversion",
        "max_mana_to_ad_ratio": 0.02,
        "manaflow_charge_interval": 8.0,
        "manaflow_max_charges": 4,
        "manaflow_bonus_mana_per_trigger": 3.0,
        "manaflow_bonus_mana_per_champion": 6.0,
        "manaflow_bonus_mana_max": 360.0,
        "manaflow_transform_bonus_mana": 360.0,
    },
    "Fimbulwinter": {
        "type": "stat_conversion",
        "bonus_mana_to_health_ratio": 0.15,
        # Everlasting is event-driven.  The participant timeline only arms
        # this branch when a champion module supplies explicit crowd-control
        # metadata; it never infers a slow or immobilize from an ability name.
        "everlasting_base_shield": 100.0,
        "everlasting_current_mana_ratio": 0.045,
        "everlasting_multi_target_multiplier": 1.80,
        "everlasting_duration": 3.0,
        "everlasting_cooldown": 8.0,
        "everlasting_trigger_kind": "crowd_control",
    },
    "Winter's Approach": {
        "type": "stat_conversion",
        "bonus_mana_to_health_ratio": 0.15,
        "manaflow_charge_interval": 8.0,
        "manaflow_max_charges": 4,
        "manaflow_bonus_mana_per_trigger": 3.0,
        "manaflow_bonus_mana_per_champion": 6.0,
        "manaflow_bonus_mana_max": 360.0,
        "manaflow_transform_bonus_mana": 360.0,
    },
    "Whispering Circlet": {
        "type": "stat_conversion",
        "bonus_mana_to_heal_shield_power_ratio": 0.005,
        "manaflow_charge_interval": 8.0,
        "manaflow_max_charges": 5,
        "manaflow_bonus_mana_per_trigger": 4.0,
        "manaflow_bonus_mana_per_champion": 8.0,
        "manaflow_bonus_mana_max": 360.0,
        "manaflow_transform_bonus_mana": 360.0,
    },
    "Rod of Ages": {
        "type": "stat_conversion",
        "timeless_bonus_health_per_stack": 10.0,
        "timeless_bonus_mana_per_stack": 30.0,
        "timeless_bonus_ap_per_stack": 3.0,
        "timeless_max_stacks": 10,
        "timeless_level_gain_at_max": True,
    },
    "Swiftmarch": {
        "type": "stat_conversion",
        "adaptive_force_per_total_move_speed": 0.05,
    },
    "Zeke's Convergence": {
        "type": "ult_proc",
        "ultimate_haste": 15.0,
        "formula": "flat",
        "damage_type": "magic",
        "base": 150.0,
        "tick_interval": 0.25,
        "duration": 5.0,
        "cooldown": 45.0,
        "slow_percent": 30.0,
    },
    "Dawncore": {
        "type": "stat_conversion",
        "ap_per_mana_regen_unit": 10.0,
        "mana_regen_threshold_percent": 100.0,
    },
    "Bandlepipes": {
        "type": "stat_conversion",
        "bonus_attack_speed_melee": 30.0,
        "bonus_attack_speed_ranged": 20.0,
    },
    "Hubris": {
        "type": "stat_conversion",
        "eminence_base_ad": 12.0,
        "eminence_ad_per_stack": 3.0,
        "eminence_duration": 90.0,
    },
    "Axiom Arc": {
        "type": "stat_conversion",
        "ultimate_refund_base_ratio": 0.10,
        "ultimate_refund_per_lethality_ratio": 0.0025,
        "ultimate_refund_trigger_window": 3.0,
    },
    "Overlord's Bloodmail": {
        "type": "stat_conversion",
        "bonus_health_to_ad_ratio": 0.025,
        "retribution_missing_health_min": 0.0,
        "retribution_missing_health_max": 0.70,
    },
    "Staff of Flowing Water": {
        "type": "stat_conversion",
        "rapids_bonus_ap": 40.0,
    },
    "Warmog's Armor": {
        "type": "stat_conversion",
        "item_bonus_health_ratio": 0.12,
        "heart_bonus_health_threshold": 2000.0,
        "heart_max_health_ratio_per_tick": 0.015,
        "heart_tick_interval": 0.5,
        "heart_champion_damage_cooldown": 8.0,
        "heart_nonchampion_damage_cooldown": 3.0,
    },
    # ── Starting defenses (consumed by defensive_effects.py) ─────────────
    "Armored Advance": {
        "type": "defensive_start",
        "basic_damage_multiplier": 0.90,
        "reactive_shield_damage_type": "physical",
        "reactive_shield_base": 100.0,
        "reactive_shield_max": 200.0,
        "reactive_shield_scale_start_level": 9,
        "reactive_shield_scale_end_level": 18,
        "reactive_shield_bonus_health_ratio": 0.08,
        "reactive_shield_duration": 5.0,
        "reactive_shield_cooldown": 15.0,
    },
    "Chainlaced Crushers": {
        "type": "defensive_start",
        "reactive_shield_damage_type": "magic",
        "reactive_shield_base": 100.0,
        "reactive_shield_max": 200.0,
        "reactive_shield_scale_start_level": 9,
        "reactive_shield_scale_end_level": 18,
        "reactive_shield_bonus_health_ratio": 0.08,
        "reactive_shield_duration": 5.0,
        "reactive_shield_cooldown": 15.0,
    },
    "Celestial Opposition": {
        "type": "defensive_start",
        "incoming_damage_multiplier": 0.65,
        "incoming_damage_linger": 2.0,
        "incoming_damage_cooldown": 20.0,
    },
    "Bloodthirster": {
        "type": "defensive_start",
        "ichorshield_min": 165.0,
        "ichorshield_max": 315.0,
        "ichorshield_scale_start_level": 9,
        "ichorshield_scale_end_level": 18,
    },
    "Kaenic Rookern": {
        "type": "defensive_start",
        "magic_shield_max_health_ratio": 0.15,
    },
    "Spirit Visage": {
        "type": "defensive_start",
        "shield_received_multiplier": 1.25,
    },
    "Plated Steelcaps": {
        "type": "target_mitigation",
        "basic_damage_multiplier": 0.90,
    },
    "Warden's Mail": {
        "type": "target_mitigation",
        "basic_damage_flat_reduction": 15.0,
        "basic_damage_flat_reduction_cap": 0.20,
    },
    "Frozen Heart": {
        "type": "target_attack_speed_aura",
        # Winter's Caress cripples nearby champions' total attack speed by 20%.
        "attack_speed_reduction": 0.20,
        # The roster has no coordinates; the coupled pair is explicitly
        # treated as being inside this sourced enemy-only aura.
        "range_units": 700.0,
    },
    "Randuin's Omen": {
        "type": "target_mitigation",
        "critical_strike_damage_multiplier": 0.70,
    },
    "Guardian Angel": {
        "type": "defensive_start",
        # Rebirth: after lethal damage, resurrect after four seconds with
        # 50% of base health.  The timeline owns the trigger because the
        # lethal packet is target-state dependent.
        "revive_health_ratio": 0.50,
        "revive_delay": 4.0,
        "revive_cooldown": 300.0,
    },
    "Force of Nature": {
        "type": "target_state",
        "steadfast_stack_duration": 7.0,
        "steadfast_max_stacks": 8,
        "steadfast_stack_interval": 1.0,
        "steadfast_immobilize_stacks": 2,
        "steadfast_bonus_magic_resistance": 70.0,
        "steadfast_bonus_move_speed_percent": 6.0,
    },
    "Jak'Sho, The Protean": {
        "type": "target_state",
        "voidborn_stack_interval": 1.0,
        "voidborn_max_stacks": 5,
        "voidborn_bonus_resistance_multiplier": 0.30,
    },
    "Zhonya's Hourglass": {
        "type": "defensive_start",
        "stasis_duration": 2.5,
    },
    "Seeker's Armguard": {
        "type": "defensive_start",
        "stasis_duration": 2.5,
    },
    "Death's Dance": {
        "type": "defensive_start",
        # Ignore Pain stores post-mitigation physical and magic damage.  The
        # participant timeline expands it into one-third true-damage ticks;
        # Defy clears the remainder and heals on a sourced takedown.
        "damage_deferral_melee": 0.30,
        "damage_deferral_ranged": 0.10,
        "damage_deferral_duration": 3.0,
        "damage_deferral_ticks": 3,
        "defy_window": 3.0,
        "defy_heal_bonus_ad_ratio": 0.75,
        "defy_heal_duration": 2.0,
        "defy_heal_ticks": 2,
    },
    # Annul is ready at the opening of a modeled exchange.  The timeline
    # consumes it on the first authored hostile ability; cooldown/rearm is
    # intentionally not inferred from an item's name or from unscheduled
    # damage events.
    "Banshee's Veil": {
        "type": "defensive_start",
        "spell_shield_ready": True,
        "spell_shield_cooldown": 40.0,
    },
    "Edge of Night": {
        "type": "defensive_start",
        "spell_shield_ready": True,
        "spell_shield_cooldown": 40.0,
    },
    "Verdant Barrier": {
        "type": "defensive_start",
        "spell_shield_ready": True,
        "spell_shield_cooldown": 60.0,
    },
    "Immortal Shieldbow": {
        "type": "target_threshold_shield",
        "damage_type": "all",
        "health_threshold": 0.30,
        "shield_base": 400.0,
        "shield_max": 700.0,
        "shield_scale_start_level": 9,
        "shield_scale_end_level": 18,
        "duration": 3.0,
    },
    "Hexdrinker": {
        "type": "target_threshold_shield",
        "health_threshold": 0.30,
        "shield_melee_min": 110.0,
        "shield_melee_max": 280.0,
        "shield_ranged_min": 82.5,
        "shield_ranged_max": 210.0,
        "duration": 2.5,
        "damage_type": "magic",
    },
    "Maw of Malmortius": {
        "type": "stat_conversion",
        "health_threshold": 0.30,
        "shield_melee_base": 200.0,
        "shield_melee_bonus_ad_ratio": 1.50,
        "shield_ranged_base": 150.0,
        "shield_ranged_bonus_ad_ratio": 1.125,
        "duration": 3.0,
        "damage_type": "magic",
    },
    "Seraph's Embrace": {
        "type": "stat_conversion",
        "bonus_mana_to_ap_ratio": 0.02,
        "health_threshold": 0.30,
        "shield_max_mana_ratio": 0.18,
        "duration": 3.0,
        "damage_type": "all",
    },
    "Sterak's Gage": {
        "type": "stat_conversion",
        "base_ad_to_bonus_ad_ratio": 0.45,
        "health_threshold": 0.30,
        "shield_bonus_health_ratio": 0.60,
        "duration": 4.5,
        "damage_type": "all",
    },
    "Protoplasm Harness": {
        "type": "target_threshold_health",
        "health_threshold": 0.30,
        "bonus_health_min": 100.0,
        "bonus_health_max": 300.0,
        "heal_min": 100.0,
        "heal_max": 400.0,
        "heal_bonus_armor_ratio": 1.75,
        "heal_bonus_mr_ratio": 1.75,
        "duration": 5.0,
        "cooldown": 90.0,
    },
    # ── Shield reduction (attacker passives that cut the target's shields) ──
    "Serpent's Fang": {
        "type": "shield_reduction",
        # Shield Reaver: dealing damage inflicts a 3-second venom cutting
        # shields the target gains; magic-damage shields are unaffected.
        "shield_reduction_melee": 0.50,
        "shield_reduction_ranged": 0.35,
        "venom_duration": 3.0,
    },
    "Stormrazor": {
        "type": "on_hit_once",
        "formula": "flat",
        "breakdown_key": "on_hit_once_Stormrazor",
        "display_name": "Stormrazor (Bolt)",
        "damage_type": "magic",
        "base": 100.0,
        "energized_max_stacks": 100,
        "energized_attack_stacks": 6,
        "energized_distance_units_per_stack": 24.0,
    },
    # ── Sundered Sky (first-auto crit modifier) ─────────────────────────────
    "Sundered Sky": {
        "type": "first_auto_crit",
        # Lightshield Strike: first auto crits at 80% of normal crit damage
        # Overrides natural crit even if you would have crit normally
        "reduced_crit_ratio": 0.80,
        "cooldown": 10.0,
        # Lightshield Strike also heals the attacker for base AD plus 6% of
        # missing health.  The latter is evaluated against the live
        # participant state when the ordered ledger is replayed.
        "heal_base_ad_ratio": 1.0,
        "heal_missing_health_ratio": 0.06,
        # Excess Lightshield Strike healing becomes bonus health for 8 seconds.
        "temporary_health_duration": 8.0,
    },
    # ── Voltaic Cyclosword (energized first-auto) ───────────────────────────
    "Voltaic Cyclosword": {
        "type": "on_hit_once",
        "formula": "current_hp",
        "breakdown_key": "on_hit_once_Voltaic Cyclosword",
        "display_name": "Voltaic Cyclosword (Firmament)",
        "damage_type": "physical",
        # Firmament: % of target's CURRENT health (melee 9% / ranged 7%),
        # capped at 200
        "current_hp_ratio_melee": 0.09,
        "current_hp_ratio_ranged": 0.07,
        "damage_cap": 200.0,
        "temporary_lethality_melee": 15.0,
        "temporary_lethality_ranged": 12.0,
        "temporary_lethality_duration": 4.0,
        "energized_max_stacks": 100,
        "energized_attack_stacks": 6,
        "energized_distance_units_per_stack": 24.0,
        # V26.09 Galvanize lets a damaging ability consume a ready
        # Energized effect before the triggering attack/ability packet.
        "energized_ability_trigger": True,
    },
    # ── Unending Despair (periodic AoE damage) ──────────────────────────────
    "Unending Despair": {
        "type": "periodic_aoe",
        "formula": "bonus_hp",
        "damage_type": "magic",
        # Anguish: every 4 seconds, deal 3% bonus health as magic damage
        "interval": 4.0,
        # Anguish saps every enemy champion within this radius.
        "range_units": 650.0,
        "bonus_hp_ratio": 0.03,
        # Anguish heals the wearer for 250% of post-mitigation damage dealt.
        "self_heal_post_mitigation_multiplier": 2.50,
    },
    # ── Yun Tal Wildarrows (conditional AS on attack) ───────────────────────
    "Yun Tal Wildarrows": {
        "type": "conditional_attack_speed",
        # Flurry: 30% bonus AS for 6 seconds after attacking a champion
        "bonus_attack_speed_percent": 30.0,
        "duration": 6.0,
        "cooldown": 30.0,
        "attack_refund_base": 1.0,
        "attack_refund_crit": 2.0,
        "crit_chance_per_stack_melee": 0.004,
        "crit_chance_per_stack_ranged": 0.002,
        "crit_stack_max_melee": 63,
        "crit_stack_max_ranged": 125,
        "crit_chance_cap": 0.25,
    },
}


# Fields owned by code rather than wiki parsing. Every remaining offline field
# is explicitly parser-owned through ``_PARSEABLE_ITEM_KEYS`` below.
_STRUCTURAL_EFFECT_KEYS = frozenset(
    {
        "type",
        "formula",
        "secondary_behavior",
        "breakdown_key",
        "display_name",
        "damage_type",
        "phantom_hit",
        "uses_empowered_auto_count",
        "repeat_on_cooldown",
        "trigger",
        "is_ability_damage",
        "double_on_hit",
        "basic_damage",
        "unmodeled_splash_note",
        "attack_refund",
        "applies_on_hit",
        "energized_max_stacks",
        "energized_ability_trigger",
        "cleave_on_hit",
    }
)

_STATIC_VALUE_KEYS_BY_ITEM: dict[str, frozenset[str]] = {
    "Armored Advance": frozenset(
        {
            "basic_damage_multiplier",
            "reactive_shield_damage_type",
            "reactive_shield_base",
            "reactive_shield_max",
            "reactive_shield_scale_start_level",
            "reactive_shield_scale_end_level",
            "reactive_shield_bonus_health_ratio",
            "reactive_shield_duration",
            "reactive_shield_cooldown",
        }
    ),
    "Chainlaced Crushers": frozenset(
        {
            "reactive_shield_damage_type",
            "reactive_shield_base",
            "reactive_shield_max",
            "reactive_shield_scale_start_level",
            "reactive_shield_scale_end_level",
            "reactive_shield_bonus_health_ratio",
            "reactive_shield_duration",
            "reactive_shield_cooldown",
        }
    ),
    "Celestial Opposition": frozenset(
        {
            "incoming_damage_multiplier",
            "incoming_damage_linger",
            "incoming_damage_cooldown",
        }
    ),
    "Bloodthirster": frozenset(
        {
            "ichorshield_min",
            "ichorshield_max",
            "ichorshield_scale_start_level",
            "ichorshield_scale_end_level",
        }
    ),
    "Doran's Blade": frozenset(
        {
            "direct_heal_post_mitigation_ratio",
            "direct_heal_aoe_effectiveness",
            "stat_override_omnivamp_percent",
        }
    ),
    "Doran's Ring": frozenset(
        {
            "drain_restoration_per_second",
            "drain_combat_restoration_per_second",
            "drain_combat_duration",
            "drain_health_conversion",
            "drain_tick_interval",
        }
    ),
    "Doran's Shield": frozenset(
        {
            "enduring_focus_total_melee",
            "enduring_focus_total_reduced",
            "enduring_focus_missing_health_cap",
            "enduring_focus_duration",
            "health_regen_tick_interval",
        }
    ),
    "Warmog's Armor": frozenset(
        {
            "heart_bonus_health_threshold",
            "heart_max_health_ratio_per_tick",
            "heart_tick_interval",
            "heart_champion_damage_cooldown",
            "heart_nonchampion_damage_cooldown",
        }
    ),
    "Fimbulwinter": frozenset(
        {
            "bonus_mana_to_health_ratio",
            "everlasting_base_shield",
            "everlasting_current_mana_ratio",
            "everlasting_multi_target_multiplier",
            "everlasting_duration",
            "everlasting_cooldown",
            "everlasting_trigger_kind",
        }
    ),
    "Cull": frozenset({"health_per_on_hit"}),
    "Banshee's Veil": frozenset({"spell_shield_ready", "spell_shield_cooldown"}),
    "Edge of Night": frozenset({"spell_shield_ready", "spell_shield_cooldown"}),
    "Verdant Barrier": frozenset({"spell_shield_ready", "spell_shield_cooldown"}),
    "Blade of the Ruined King": frozenset({"min_damage"}),
    "Blackfire Torch": frozenset({"tick_interval"}),
    "Bami's Cinder": frozenset({"event_interval"}),
    "Fated Ashes": frozenset({"tick_interval"}),
    "Hexdrinker": frozenset(
        {
            "health_threshold",
            "shield_melee_min",
            "shield_melee_max",
            "shield_ranged_min",
            "shield_ranged_max",
            "duration",
        }
    ),
    "Hexoptics C44": frozenset({"melee_assumed_distance"}),
    "Hextech Gunblade": frozenset({"base_min", "base_max", "cooldown"}),
    "Hextech Rocketbelt": frozenset({"cooldown"}),
    "Bramble Vest": frozenset({"bonus_armor_ratio"}),
    "Frozen Heart": frozenset({"attack_speed_reduction", "range_units"}),
    "Unending Despair": frozenset({"range_units"}),
    "Guardian Angel": frozenset(
        {"revive_health_ratio", "revive_delay", "revive_cooldown"}
    ),
    "Force of Nature": frozenset(
        {
            "steadfast_stack_duration",
            "steadfast_max_stacks",
            "steadfast_stack_interval",
            "steadfast_immobilize_stacks",
            "steadfast_bonus_magic_resistance",
            "steadfast_bonus_move_speed_percent",
        }
    ),
    "Jak'Sho, The Protean": frozenset(
        {
            "voidborn_stack_interval",
            "voidborn_max_stacks",
            "voidborn_bonus_resistance_multiplier",
        }
    ),
    "Zhonya's Hourglass": frozenset({"stasis_duration"}),
    "Seeker's Armguard": frozenset({"stasis_duration"}),
    "Malignance": frozenset({"base", "ap_ratio", "duration"}),
    "Liandry's Torment": frozenset({"tick_interval"}),
    "Hollow Radiance": frozenset({"event_interval"}),
    "Maw of Malmortius": frozenset(
        {
            "health_threshold",
            "shield_melee_base",
            "shield_melee_bonus_ad_ratio",
            "shield_ranged_base",
            "shield_ranged_bonus_ad_ratio",
            "duration",
        }
    ),
    "Sunfire Aegis": frozenset({"event_interval"}),
    "Profane Hydra": frozenset({"cooldown"}),
    "Protoplasm Harness": frozenset(
        {
            "health_threshold",
            "bonus_health_min",
            "bonus_health_max",
            "heal_min",
            "heal_max",
            "heal_bonus_armor_ratio",
            "heal_bonus_mr_ratio",
            "duration",
            "cooldown",
        }
    ),
    "Ravenous Hydra": frozenset({"cooldown"}),
    "Tiamat": frozenset({"cooldown"}),
    "Thornmail": frozenset({"bonus_armor_ratio"}),
    "Seraph's Embrace": frozenset(
        {"health_threshold", "shield_max_mana_ratio", "duration"}
    ),
    "Serpent's Fang": frozenset(
        {"shield_reduction_melee", "shield_reduction_ranged", "venom_duration"}
    ),
    "Sterak's Gage": frozenset(
        {"health_threshold", "shield_bonus_health_ratio", "duration"}
    ),
    "Stormsurge": frozenset({"damage_threshold_ratio", "damage_threshold_window"}),
    "Eclipse": frozenset({"stack_required", "stack_window"}),
    "Death's Dance": frozenset({"damage_deferral_ticks", "defy_heal_ticks"}),
    "Stridebreaker": frozenset({"cooldown"}),
    "Titanic Hydra": frozenset({"active_cooldown"}),
    "Rapid Firecannon": frozenset(
        {
            "energized_attack_stacks",
            "energized_distance_units_per_stack",
        }
    ),
    "Statikk Shiv": frozenset({"energized_distance_units_per_stack"}),
    "Stormrazor": frozenset(
        {
            "energized_attack_stacks",
            "energized_distance_units_per_stack",
        }
    ),
    "Voltaic Cyclosword": frozenset(
        {
            "energized_attack_stacks",
            "energized_distance_units_per_stack",
        }
    ),
    "Sundered Sky": frozenset(
        {
            "heal_base_ad_ratio",
            "heal_missing_health_ratio",
            "temporary_health_duration",
        }
    ),
    # The cached item packet does not carry Actualizer's active cooldown;
    # the full Wiki entry is the source receipt for this code-owned value.
    "Actualizer": frozenset({"mana_made_real_cooldown"}),
}


def _static_keys(item_name: str) -> frozenset[str]:
    """Return the code-owned registry keys for one item."""
    return _STRUCTURAL_EFFECT_KEYS | _STATIC_VALUE_KEYS_BY_ITEM.get(
        item_name, frozenset()
    )


_STATIC_ITEM_EFFECTS: dict[str, dict[str, Any]] = {
    item_name: {
        key: value for key, value in values.items() if key in _static_keys(item_name)
    }
    for item_name, values in _OFFLINE_ITEM_EFFECTS.items()
}

_PARSEABLE_ITEM_KEYS: dict[str, frozenset[str]] = {
    item_name: frozenset(values) - _static_keys(item_name)
    for item_name, values in _OFFLINE_ITEM_EFFECTS.items()
}


# ---------------------------------------------------------------------------
# Dynamic loading from JSON data
# ---------------------------------------------------------------------------


def _build_item_effects() -> dict[str, dict[str, Any]]:
    """Build live effects from code-owned schema plus parsed values.

    A successful parse never borrows a missing parser-owned value from the
    offline snapshot. Loading failure, parser failure, or an empty whole-parse
    result uses the complete last-known-good snapshot instead.

    Returns:
        Merged dict suitable for use as ``ITEM_EFFECTS``.
    """
    result = deepcopy(_STATIC_ITEM_EFFECTS)

    try:
        from .data_fetcher import DEFAULT_DATA_DIR, fetch_item_data

        items_data = fetch_item_data(data_directory=DEFAULT_DATA_DIR)
    except Exception as exc:
        logger.debug("Could not load item JSON for parsing: %s", exc)
        return deepcopy(_OFFLINE_ITEM_EFFECTS)

    try:
        from .passive_parser import parse_all_item_effects

        parsed = parse_all_item_effects(items_data)
    except Exception as exc:
        logger.warning("Item passive parsing failed: %s", exc)
        return deepcopy(_OFFLINE_ITEM_EFFECTS)

    if not parsed:
        logger.warning("Item passive parsing produced no registered effects")
        return deepcopy(_OFFLINE_ITEM_EFFECTS)

    for item_name, parsed_values in parsed.items():
        if item_name in result:
            parseable_keys = _PARSEABLE_ITEM_KEYS[item_name]
            result[item_name].update(
                {
                    key: value
                    for key, value in parsed_values.items()
                    if key in parseable_keys
                }
            )
        else:
            result[item_name] = dict(parsed_values)

    return result


def refresh_item_effects() -> None:
    """Re-parse item effects from the latest cached JSON data.

    Call this after the data updater has fetched fresh item data so
    that ``ITEM_EFFECTS`` reflects the newest balance values.

    Mutates ``ITEM_EFFECTS`` in place (clear + update) rather than
    rebinding the module global, so modules that imported it via
    ``from .item_effects import ITEM_EFFECTS`` (e.g. ``calculator/__init__.py``)
    keep seeing the refreshed values through their existing binding.
    """
    ITEM_EFFECTS.clear()
    ITEM_EFFECTS.update(_build_item_effects())
    # Compiled-build memo derives from this registry; drop it with the data.
    _RESOLVED_DAMAGE_EFFECTS.clear()


# Build the live registry at import time.
ITEM_EFFECTS: dict[str, dict[str, Any]] = _build_item_effects()


def required_effect_value(item_name: str, key: str) -> Any:
    """Read a required key from an item's effect entry, failing loudly.

    A missing key means the parser omitted a required parser-owned value or
    code omitted a structural value. Raise with item and key context instead
    of silently borrowing a potentially stale offline number.
    """
    effect = ITEM_EFFECTS.get(item_name, {})
    if key not in effect:
        raise KeyError(
            f"ITEM_EFFECTS[{item_name!r}] is missing {key!r} — "
            "parser/schema bug; check _STATIC_ITEM_EFFECTS and "
            "passive_parser"
        )
    return effect[key]


def sustain_effect_value(item_name: str, key: str) -> float:
    """Read one sourced sustain value from an item's typed effect record."""
    value = required_effect_value(item_name, key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"ITEM_EFFECTS[{item_name!r}][{key!r}] must be numeric for sustain"
        )
    return float(value)


def override_item_stat(item_name: str, stat_key: str, value: float) -> float:
    """Apply a source-backed stat correction when the cache is stale.

    A small number of item pages deliberately replace a stat passive with a
    named effect (Doran's Blade's old omnivamp is one example).  The typed
    registry owns that correction; callers never supply a fallback literal.
    """
    key = f"stat_override_{stat_key}"
    effect = ITEM_EFFECTS.get(item_name, {})
    if key not in effect:
        return float(value)
    return sustain_effect_value(item_name, key)


def _item_names(items: list[dict[str, Any]]) -> set[str]:
    """Return the set of item names in a build."""
    return {item.get("name", "") for item in items}


def has_item(items: list[dict[str, Any]], item_name: str) -> bool:
    """Return whether a resolved build contains one canonical item name."""
    return item_name in _item_names(items)


def death_dance_deferral_fraction(
    items: list[dict[str, Any]], *, is_melee: bool
) -> float:
    """Return Death's Dance's sourced Ignore Pain fraction for this holder."""
    if not has_item(items, "Death's Dance"):
        return 0.0
    key = "damage_deferral_melee" if is_melee else "damage_deferral_ranged"
    return float(required_effect_value("Death's Dance", key))


def death_dance_defy_heal_amount(
    items: list[dict[str, Any]], *, bonus_attack_damage: float
) -> float:
    """Return Death's Dance's sourced Defy heal for the holder's bonus AD."""
    if not has_item(items, "Death's Dance"):
        return 0.0
    ratio = float(required_effect_value("Death's Dance", "defy_heal_bonus_ad_ratio"))
    return max(0.0, float(bonus_attack_damage)) * ratio


def eclipse_shield_amount(
    items: list[dict[str, Any]], *, bonus_attack_damage: float, is_melee: bool
) -> float:
    """Return Eclipse's sourced shield amount for a completed pair."""
    if not has_item(items, "Eclipse"):
        return 0.0
    suffix = "melee" if is_melee else "ranged"
    base = float(required_effect_value("Eclipse", f"shield_{suffix}_base"))
    ratio = float(required_effect_value("Eclipse", f"shield_{suffix}_bonus_ad_ratio"))
    return max(0.0, base + ratio * float(bonus_attack_damage))


# ---------------------------------------------------------------------------
# Compiled fight-engine boundary
# ---------------------------------------------------------------------------

DamageType = Literal["physical", "magic", "true"]
RawDamageFormula = Callable[["DamageInputs"], float]

# The wiki's canonical "On-Attacking" item list (a short, CLOSED set):
# effects triggered by COMPLETING a basic attack's windup rather than by
# a hit landing. Everything not listed here counts on-hit (Nashor's,
# Wit's End, BotRK, Kraken's counter, Hullbreaker's counter, ...).
# Ability sources that merely APPLY on-hit effects (Bel'Veth Q) never
# advance on-attack mechanics; sources that count as attacks (autos,
# Bel'Veth E slashes) advance both.
# https://wiki.leagueoflegends.com/en-us/Basic_attack (On-attacking)
ON_ATTACK_TRIGGER_ITEMS = frozenset(
    {
        "Guinsoo's Rageblade",
        "Navori Flickerblade",
        "Rapid Firecannon",
        "Runaan's Hurricane",
        "Voltaic Cyclosword",
        "Yun Tal Wildarrows",
    }
)


def counter_trigger(item_name: str) -> str:
    """Trigger class of an item's counter/cadence mechanic.

    ``"on_attack"`` for the canonical wiki On-Attacking items (Guinsoo's
    phantom-hit cadence, energized stacking, ...), ``"on_hit"`` for
    everything else (Kraken/Hullbreaker counters). The fight engine uses
    this to decide which ability-carried applications advance a counter.
    """
    return "on_attack" if item_name in ON_ATTACK_TRIGGER_ITEMS else "on_hit"


@dataclass(frozen=True, slots=True)
class DamageInputs:
    """Runtime values a compiled raw-damage formula may read."""

    champion_stats: Mapping[str, float]
    level: int
    is_melee: bool
    target_max_health: float
    target_current_health: float


@dataclass(frozen=True, slots=True)
class DamageSource:
    """One item-owned raw damage formula plus its presentation metadata."""

    item_name: str
    breakdown_key: str
    display_name: str
    damage_type: DamageType
    raw_damage: RawDamageFormula
    is_ability_damage: bool = False
    multi_target_charges: int = 0
    repeated_target_multiplier: float = 1.0
    single_target_multiplier: float = 1.0
    basic_damage: bool = False
    # Some active packets explicitly inherit life steal.  The parser carries
    # that sourced effectiveness into the runtime source; zero means no
    # life-steal sibling is eligible.
    lifesteal_effectiveness: float = 0.0
    # Sourced cadence for continuous item damage (for example Immolate).
    # ``None`` means the aggregate row must remain untimed.
    event_interval: float | None = None


@dataclass(frozen=True, slots=True)
class PerHitEffect:
    """Damage applied on each auto-attack on-hit application."""

    source: DamageSource
    tracks_current_health: bool = False
    # The item ALSO deals per-ability-hit damage (Muramana Shock). Wiki
    # rule: the on-hit and ability damage never stack on one ability
    # hit — an ability that applies on-hit effects (Ezreal Q, Bel'Veth
    # Q/E) deals only the ability-hit damage, which the rotation engine
    # already procs once per cast. Ability-carried on-hit applications
    # must therefore skip this per-hit component; real basic attacks
    # (and their phantom hits) still apply it.
    superseded_by_ability_proc: bool = False


@dataclass(frozen=True, slots=True)
class OnHitHealEffect:
    """Health restored by one authored on-hit application."""

    item_name: str
    amount: float


@dataclass(frozen=True, slots=True)
class SpellbladeEffect:
    """One mutually-exclusive spellblade behavior."""

    source: DamageSource
    cooldown: float
    weave_delay: float
    double_on_hit: bool = False
    expose_weakness_melee: float = 0.0
    expose_weakness_ranged: float = 0.0
    bonus_attack_speed_percent: float = 0.0
    mana_restore_base_ad_ratio: float = 0.0
    mana_restore_crit_ratio: float = 0.0
    self_heal_ap_ratio: float = 0.0
    self_heal_bonus_health_ratio: float = 0.0


@dataclass(frozen=True, slots=True)
class BurnEffect:
    """Refreshable burn behavior with an item-owned base-duration formula."""

    source: DamageSource
    duration: float
    tick_interval: float


@dataclass(frozen=True, slots=True)
class PeriodicEffect:
    """Damage applied once per fixed interval."""

    source: DamageSource
    interval: float
    self_heal_post_mitigation_multiplier: float = 0.0


@dataclass(frozen=True, slots=True)
class CooldownProcEffect:
    """Triggered damage with optional repeated cooldown applications.

    ``damage_threshold_ratio`` / ``damage_threshold_window`` describe a
    ``damage_threshold`` trigger: the proc arms once that share of the
    target's max health is dealt within the rolling window (seconds).
    """

    source: DamageSource
    cooldown: float
    repeat_on_cooldown: bool = True
    late_phase: bool = False
    trigger: str = "coarse"
    damage_threshold_ratio: float = 0.0
    damage_threshold_window: float = 0.0
    # Seconds refunded from a running cooldown per completed attack
    # windup (Scout's Slingshot's Bullseye).
    on_attack_cooldown_refund: float = 0.0
    # Optional stack gate for effects such as Eclipse's two-hit trigger.
    # Values are parser-owned in ITEM_EFFECTS and remain zero for ordinary
    # cooldown procs.
    stack_required: int = 0
    stack_window: float = 0.0
    # Eclipse's completed pair also creates a self shield.  These values are
    # parser-owned and remain zero for ordinary cooldown procs.
    self_shield_melee_base: float = 0.0
    self_shield_ranged_base: float = 0.0
    self_shield_melee_bonus_ad_ratio: float = 0.0
    self_shield_ranged_bonus_ad_ratio: float = 0.0
    self_shield_duration: float = 0.0


@dataclass(frozen=True, slots=True)
class UltimateProcEffect:
    """Ultimate-triggered damage whose base formula spans one duration."""

    source: DamageSource
    duration: float
    mr_reduction: float = 0.0


@dataclass(frozen=True, slots=True)
class FirstAutoEffect:
    """Damage triggered by the first eligible auto attack."""

    source: DamageSource
    max_procs: int = 1
    temporary_lethality_melee: float = 0.0
    temporary_lethality_ranged: float = 0.0
    temporary_lethality_duration: float = 0.0
    energized_max_stacks: int = 0
    energized_attack_stacks: int = 0
    energized_ability_trigger: bool = False
    chain_targets_min: int = 0
    chain_targets_max: int = 0


@dataclass(frozen=True, slots=True)
class AutoCooldownEffect:
    """Empowered-auto damage available again after a cooldown."""

    source: DamageSource
    cooldown: float


@dataclass(frozen=True, slots=True)
class StackingOnHitEffect:
    """Damage triggered after a fixed number of on-hit applications."""

    source: DamageSource
    hits_required: int
    tracks_target_health: bool = False


@dataclass(frozen=True, slots=True)
class PhantomHitEffect:
    """Cadence for an extra on-hit application after autos stack."""

    item_name: str
    stacking_autos: int
    interval: int


@dataclass(frozen=True, slots=True)
class UltimateAutoBuffEffect:
    """Ultimate-triggered attack-speed and empowered-auto behavior."""

    item_name: str
    bonus_attack_speed_percent: float
    empowered_auto_count: int
    duration: float
    reduced_crit_ratio: float
    natural_crit_true_damage_ratio: float


@dataclass(frozen=True, slots=True)
class StackingPenEffect:
    """Alternating-auto penetration that ramps to a stack cap."""

    pen_per_stack: float
    max_stacks: int

    @property
    def max_pen(self) -> float:
        """Return the penetration fraction at maximum stacks."""
        return self.pen_per_stack * self.max_stacks

    def average_pen(self, num_auto_attacks: int) -> float:
        """Return average penetration across the modeled auto sequence."""
        if num_auto_attacks <= 0:
            return 0.0
        total_pen = 0.0
        dark_stacks = 0
        for auto_number in range(1, num_auto_attacks + 1):
            if auto_number % 2 == 0:
                dark_stacks = min(dark_stacks + 1, self.max_stacks)
            total_pen += dark_stacks * self.pen_per_stack
        return total_pen / num_auto_attacks


@dataclass(frozen=True, slots=True)
class FirstAutoCritEffect:
    """Forced first-auto crit expressed as a fraction of full crit damage."""

    item_name: str
    reduced_crit_ratio: float
    heal_base_ad_ratio: float = 0.0
    heal_missing_health_ratio: float = 0.0
    temporary_health_duration: float = 0.0


@dataclass(frozen=True, slots=True)
class MagicTrueCritEffect:
    """Low-health critical modifier for magic and true damage."""

    item_name: str
    health_threshold: float
    crit_multiplier: float


@dataclass(frozen=True, slots=True)
class StackingReductionEffect:
    """Per-hit resistance reduction and its stack cap."""

    reduction_per_stack: float
    max_stacks: int


@dataclass(frozen=True, slots=True)
class ExecuteEffect:
    """Display-only low-health execution threshold."""

    item_name: str
    threshold: float


@dataclass(frozen=True, slots=True)
class DamageAmplifierEffect:
    """One fight-wide amplifier with registry values already captured."""

    item_name: str
    amp_fraction: Callable[[float, float], float]


@dataclass(frozen=True, slots=True)
class AbilityAmplifierEffect:
    """Ability-only amplifier derived from champion bonus mana."""

    item_name: str
    base_amp: float
    amp_per_100_bonus_mana: float

    def multiplier(
        self,
        champion_stats: Mapping[str, float],
        include_actives: bool,
    ) -> float:
        """Return the active multiplier for this champion state."""
        if not include_actives:
            return 1.0
        bonus_mana = champion_stats.get("bonus_mana", 0.0)
        return 1.0 + self.base_amp + self.amp_per_100_bonus_mana * (bonus_mana / 100.0)


@dataclass(frozen=True, slots=True)
class BasicAmplifierEffect:
    """Distance-scaled basic damage amplifier (Hexoptics C44 Magnification)."""

    item_name: str
    max_amp: float
    max_distance: float
    melee_assumed_distance: float

    def multiplier(self, is_melee: bool) -> float:
        """Return the amp multiplier under the fight's range assumption.

        Ranged champions are assumed to attack from max Magnification
        distance (full amp); melee champions attack from roughly
        ``melee_assumed_distance`` units, scaling the amp down linearly.
        """
        if is_melee:
            distance = min(self.melee_assumed_distance, self.max_distance)
            return 1.0 + self.max_amp * (distance / self.max_distance)
        return 1.0 + self.max_amp


@dataclass(frozen=True, slots=True)
class ArmorReductionEffect:
    """Average stacking armor reduction for one fight."""

    reduction_per_stack: float
    max_stacks: int

    def average_reduction(self, num_auto_attacks: int) -> float:
        """Preserve the engine's established Black Cleaver ramp model."""
        hits = num_auto_attacks + 4
        if hits >= self.max_stacks:
            average_stacks = self.max_stacks * 0.8
        else:
            average_stacks = hits / 2.0
        return self.reduction_per_stack * average_stacks


@dataclass(frozen=True, slots=True)
class BuildDamageEffects:
    """Typed item behaviors compiled once for one fight."""

    per_hits: tuple[PerHitEffect, ...] = ()
    on_hit_heals: tuple[OnHitHealEffect, ...] = ()
    spellblade: SpellbladeEffect | None = None
    burns: tuple[BurnEffect, ...] = ()
    immolates: tuple[DamageSource, ...] = ()
    periodic: tuple[PeriodicEffect, ...] = ()
    cooldown_procs: tuple[CooldownProcEffect, ...] = ()
    ultimate_procs: tuple[UltimateProcEffect, ...] = ()
    actives: tuple[DamageSource, ...] = ()
    first_autos: tuple[FirstAutoEffect, ...] = ()
    auto_cooldowns: tuple[AutoCooldownEffect, ...] = ()
    stacking_on_hits: tuple[StackingOnHitEffect, ...] = ()
    per_ability_hits: tuple[DamageSource, ...] = ()
    shaped_charges: tuple[CooldownProcEffect, ...] = ()
    phantom_hit: PhantomHitEffect | None = None
    ultimate_auto_buff: UltimateAutoBuffEffect | None = None
    stacking_pen: StackingPenEffect | None = None
    navori_refund_percent: float = 0.0
    crit_damage_bonus: float = 0.0
    first_auto_crit: FirstAutoCritEffect | None = None
    magic_true_crit: MagicTrueCritEffect | None = None
    damage_amplifiers: tuple[DamageAmplifierEffect, ...] = ()
    magic_amp: float = 1.0
    basic_amp: BasicAmplifierEffect | None = None
    ability_amp: AbilityAmplifierEffect | None = None
    hypershot_amp: float = 1.0
    armor_reduction: ArmorReductionEffect | None = None
    ability_amp_source: str | None = None
    execute: ExecuteEffect | None = None
    stacking_mr_reduction: StackingReductionEffect | None = None
    cooldown_refund_source: str | None = None
    conditional_notes: tuple[str, ...] = ()


class _RequiredValues:
    """Typed, contextual reads from one live registry record."""

    def __init__(self, item_name: str, values: Mapping[str, Any]) -> None:
        self.item_name = item_name
        self.values = values

    def value(self, key: str) -> Any:
        """Return one required value or raise with item and key context."""
        if key not in self.values:
            raise KeyError(
                f"ITEM_EFFECTS[{self.item_name!r}] is missing {key!r} — "
                "parser/defaults bug; check item effect schema"
            )
        return self.values[key]

    def number(self, key: str) -> float:
        """Return one required numeric value as a float."""
        return float(self.value(key))


def _damage_source(
    item_name: str,
    damage_type: DamageType,
    raw_damage: RawDamageFormula,
    *,
    suffix: str = "on-hit",
    breakdown_key: str | None = None,
    lifesteal_effectiveness: float = 0.0,
    event_interval: float | None = None,
) -> DamageSource:
    """Build shared source metadata without leaking registry records."""
    return DamageSource(
        item_name=item_name,
        breakdown_key=breakdown_key or f"on_hit_{item_name}",
        display_name=f"{item_name} ({suffix})",
        damage_type=damage_type,
        raw_damage=raw_damage,
        lifesteal_effectiveness=lifesteal_effectiveness,
        event_interval=event_interval,
    )


def _compile_on_hit(
    item_name: str,
    values: Mapping[str, Any],
) -> PerHitEffect:
    """Compile one declarative on-hit formula from validated values."""
    required = _RequiredValues(item_name, values)
    formula = required.value("formula")
    damage_type = required.value("damage_type")

    if formula == "flat_ap":
        base = required.number("base")
        ap_ratio = required.number("ap_ratio")

        def raw(inputs: DamageInputs) -> float:
            return base + ap_ratio * inputs.champion_stats.get("ability_power", 0.0)

    elif formula == "flat_bonus_ad_ap":
        base = required.number("base")
        bonus_ad_ratio = required.number("bonus_ad_ratio")
        ap_ratio = required.number("ap_ratio")

        def raw(inputs: DamageInputs) -> float:
            stats = inputs.champion_stats
            return (
                base
                + bonus_ad_ratio * stats.get("bonus_attack_damage", 0.0)
                + ap_ratio * stats.get("ability_power", 0.0)
            )

    elif formula == "current_hp":
        melee_ratio = required.number("current_hp_ratio_melee")
        ranged_ratio = required.number("current_hp_ratio_ranged")
        minimum = required.number("min_damage")

        def raw(inputs: DamageInputs) -> float:
            ratio = melee_ratio if inputs.is_melee else ranged_ratio
            return max(minimum, ratio * inputs.target_current_health)

    elif formula == "flat":
        base = required.number("base")

        def raw(_inputs: DamageInputs) -> float:
            return base

    elif formula == "max_hp":
        melee_ratio = required.number("max_hp_ratio_melee")
        ranged_ratio = required.number("max_hp_ratio_ranged")

        def raw(inputs: DamageInputs) -> float:
            ratio = melee_ratio if inputs.is_melee else ranged_ratio
            return ratio * inputs.champion_stats.get("health", 0.0)

    elif formula == "max_mana":
        ratio = required.number("max_mana_ratio_on_hit")

        def raw(inputs: DamageInputs) -> float:
            return ratio * inputs.champion_stats.get("max_mana", 0.0)

    else:
        raise ValueError(f"Unsupported on-hit formula {formula!r} for {item_name!r}")

    source = _damage_source(item_name, damage_type, raw)
    return PerHitEffect(
        source,
        tracks_current_health=formula == "current_hp",
        superseded_by_ability_proc=values.get("secondary_behavior")
        == "per_ability_hit",
    )


def _compile_on_hit_heal(
    item_name: str,
    values: Mapping[str, Any],
) -> OnHitHealEffect:
    """Compile one fixed health receipt from an on-hit item passive."""
    required = _RequiredValues(item_name, values)
    amount = required.number("health_per_on_hit")
    if amount <= 0.0:
        raise ValueError(f"{item_name!r} on-hit heal must be positive")
    return OnHitHealEffect(item_name=item_name, amount=amount)


def _compile_auto_cooldown(
    item_name: str,
    values: Mapping[str, Any],
) -> AutoCooldownEffect:
    """Compile Titanic-style empowered-auto damage."""
    required = _RequiredValues(item_name, values)
    melee_ratio = required.number("active_max_hp_ratio_melee")
    ranged_ratio = required.number("active_max_hp_ratio_ranged")

    def raw(inputs: DamageInputs) -> float:
        ratio = melee_ratio if inputs.is_melee else ranged_ratio
        return ratio * inputs.champion_stats.get("health", 0.0)

    source = _damage_source(
        item_name,
        required.value("damage_type"),
        raw,
        suffix="Titanic Crescent",
        breakdown_key=f"active_{item_name}",
    )
    return AutoCooldownEffect(source, required.number("active_cooldown"))


def _compile_per_ability_hit(
    item_name: str,
    values: Mapping[str, Any],
) -> DamageSource:
    """Compile Muramana-style damage applied per ability hit."""
    required = _RequiredValues(item_name, values)
    melee_ratio = required.number("max_mana_ratio_ability_melee")
    ranged_ratio = required.number("max_mana_ratio_ability_ranged")

    def raw(inputs: DamageInputs) -> float:
        ratio = melee_ratio if inputs.is_melee else ranged_ratio
        return ratio * inputs.champion_stats.get("max_mana", 0.0)

    return _damage_source(
        item_name,
        required.value("damage_type"),
        raw,
        suffix="Shock - abilities",
        breakdown_key="muramana_ability",
    )


def _compile_spellblade(
    item_name: str,
    values: Mapping[str, Any],
) -> SpellbladeEffect:
    """Compile one spellblade formula and its engine scheduling values."""
    required = _RequiredValues(item_name, values)
    formula = required.value("formula")
    base_ad_ratio = required.number("base_ad_ratio")

    if formula == "base_ad":

        def raw(inputs: DamageInputs) -> float:
            return base_ad_ratio * inputs.champion_stats.get("base_attack_damage", 0.0)

    elif formula == "base_ad_ap":
        ap_ratio = required.number("ap_ratio")

        def raw(inputs: DamageInputs) -> float:
            stats = inputs.champion_stats
            return base_ad_ratio * stats.get(
                "base_attack_damage", 0.0
            ) + ap_ratio * stats.get("ability_power", 0.0)

    elif formula == "base_ad_crit":
        crit_bonus_max = required.number("crit_bonus_max")

        def raw(inputs: DamageInputs) -> float:
            stats = inputs.champion_stats
            crit_ratio = min(stats.get("critical_strike_chance", 0.0) / 100.0, 1.0)
            return (
                base_ad_ratio * stats.get("base_attack_damage", 0.0)
                + crit_bonus_max * crit_ratio
            )

    else:
        raise ValueError(
            f"Unsupported spellblade formula {formula!r} for {item_name!r}"
        )

    source = _damage_source(
        item_name,
        required.value("damage_type"),
        raw,
        suffix="Spellblade",
        breakdown_key=f"spellblade_{item_name}",
    )
    # These sibling mechanics are parser-owned for specific spellblades.  A
    # successful parse that drops one must fail closed rather than silently
    # compiling a weaker version of the item.
    required_siblings: dict[str, tuple[str, ...]] = {
        "Lich Bane": ("bonus_attack_speed_percent",),
        "Essence Reaver": (
            "mana_restore_base_ad_ratio",
            "mana_restore_crit_ratio",
        ),
        "Bloodsong": ("expose_weakness_melee", "expose_weakness_ranged"),
        "Dusk and Dawn": (
            "self_heal_ap_ratio",
            "self_heal_bonus_health_ratio",
        ),
    }
    sibling_values = {
        key: required.number(key) for key in required_siblings.get(item_name, ())
    }
    return SpellbladeEffect(
        source=source,
        cooldown=required.number("cooldown"),
        weave_delay=required.number("weave_delay"),
        double_on_hit=bool(values.get("double_on_hit", False)),
        expose_weakness_melee=sibling_values.get(
            "expose_weakness_melee", float(values.get("expose_weakness_melee", 0.0))
        ),
        expose_weakness_ranged=sibling_values.get(
            "expose_weakness_ranged", float(values.get("expose_weakness_ranged", 0.0))
        ),
        bonus_attack_speed_percent=sibling_values.get(
            "bonus_attack_speed_percent",
            float(values.get("bonus_attack_speed_percent", 0.0)),
        ),
        mana_restore_base_ad_ratio=sibling_values.get(
            "mana_restore_base_ad_ratio",
            float(values.get("mana_restore_base_ad_ratio", 0.0)),
        ),
        mana_restore_crit_ratio=sibling_values.get(
            "mana_restore_crit_ratio", float(values.get("mana_restore_crit_ratio", 0.0))
        ),
        self_heal_ap_ratio=sibling_values.get(
            "self_heal_ap_ratio", float(values.get("self_heal_ap_ratio", 0.0))
        ),
        self_heal_bonus_health_ratio=sibling_values.get(
            "self_heal_bonus_health_ratio",
            float(values.get("self_heal_bonus_health_ratio", 0.0)),
        ),
    )


def _compile_burn(item_name: str, values: Mapping[str, Any]) -> BurnEffect:
    """Compile one refreshable burn's base-duration raw damage."""
    required = _RequiredValues(item_name, values)
    formula = required.value("formula")
    if formula == "max_hp":
        ratio = required.number("max_hp_ratio_total")

        def raw(inputs: DamageInputs) -> float:
            return ratio * inputs.target_max_health

    elif formula == "flat_ap":
        base = required.number("base_total")
        ap_ratio = required.number("ap_ratio_total")

        def raw(inputs: DamageInputs) -> float:
            return base + ap_ratio * inputs.champion_stats.get("ability_power", 0.0)

    elif formula == "flat":
        base = required.number("base_total")

        def raw(_inputs: DamageInputs) -> float:
            return base

    else:
        raise ValueError(f"Unsupported burn formula {formula!r} for {item_name!r}")
    source = _damage_source(
        item_name,
        required.value("damage_type"),
        raw,
        suffix="burn",
        breakdown_key=f"burn_{item_name}",
    )
    return BurnEffect(
        source,
        required.number("duration"),
        required.number("tick_interval"),
    )


def _compile_immolate(item_name: str, values: Mapping[str, Any]) -> DamageSource:
    """Compile one Immolate formula as raw damage per second."""
    required = _RequiredValues(item_name, values)
    formula = required.value("formula")
    if formula == "bonus_hp_dps":
        base = required.number("base_per_second")
        bonus_hp_ratio = required.number("bonus_hp_ratio_per_second")

        def raw(inputs: DamageInputs) -> float:
            return base + bonus_hp_ratio * inputs.champion_stats.get(
                "bonus_health", 0.0
            )

    elif formula == "flat_dps":
        base = required.number("base_per_second")

        def raw(_inputs: DamageInputs) -> float:
            return base

    else:
        raise ValueError(f"Unsupported Immolate formula for {item_name!r}")

    return _damage_source(
        item_name,
        required.value("damage_type"),
        raw,
        suffix="Immolate",
        breakdown_key=f"immolate_{item_name}",
        event_interval=required.number("event_interval"),
    )


def _compile_periodic(item_name: str, values: Mapping[str, Any]) -> PeriodicEffect:
    """Compile one fixed-interval periodic damage formula."""
    required = _RequiredValues(item_name, values)
    if required.value("formula") != "bonus_hp":
        raise ValueError(f"Unsupported periodic formula for {item_name!r}")
    bonus_hp_ratio = required.number("bonus_hp_ratio")

    def raw(inputs: DamageInputs) -> float:
        return bonus_hp_ratio * inputs.champion_stats.get("bonus_health", 0.0)

    source = _damage_source(
        item_name,
        required.value("damage_type"),
        raw,
        suffix="Anguish",
        breakdown_key=f"periodic_{item_name}",
    )
    self_heal_multiplier = (
        required.number("self_heal_post_mitigation_multiplier")
        if item_name == "Unending Despair"
        else 0.0
    )
    return PeriodicEffect(source, required.number("interval"), self_heal_multiplier)


def _compile_proc(item_name: str, values: Mapping[str, Any]) -> CooldownProcEffect:
    """Compile one triggered proc's per-application raw damage."""
    required = _RequiredValues(item_name, values)
    formula = required.value("formula")
    if formula == "charged_ap":
        base = required.number("base_per_charge")
        ap_ratio = required.number("ap_ratio_per_charge")
        multiplier = required.number("single_target_multiplier")
        charges = int(required.number("charges"))
        repeated_target_multiplier = (multiplier - 1.0) / max(1, charges - 1)

        def raw(inputs: DamageInputs) -> float:
            ap = inputs.champion_stats.get("ability_power", 0.0)
            return (base + ap_ratio * ap) * multiplier

    elif formula == "flat_ap":
        base = required.number("base")
        ap_ratio = required.number("ap_ratio")

        def raw(inputs: DamageInputs) -> float:
            return base + ap_ratio * inputs.champion_stats.get("ability_power", 0.0)

    elif formula == "flat":
        base = required.number("base")

        def raw(_inputs: DamageInputs) -> float:
            return base

    elif formula == "flat_ap_max_hp":
        base = required.number("base")
        ap_ratio = required.number("ap_ratio")
        hp_ratio = required.number("target_max_hp_ratio")

        def raw(inputs: DamageInputs) -> float:
            return (
                base
                + ap_ratio * inputs.champion_stats.get("ability_power", 0.0)
                + hp_ratio * inputs.target_max_health
            )

    else:
        raise ValueError(f"Unsupported proc formula {formula!r} for {item_name!r}")
    source = DamageSource(
        item_name=item_name,
        breakdown_key=f"proc_{item_name}",
        display_name=f"{item_name} (proc)",
        damage_type=required.value("damage_type"),
        raw_damage=raw,
        is_ability_damage=bool(values.get("is_ability_damage", False)),
        multi_target_charges=charges if formula == "charged_ap" else 0,
        repeated_target_multiplier=(
            repeated_target_multiplier if formula == "charged_ap" else 1.0
        ),
        single_target_multiplier=(multiplier if formula == "charged_ap" else 1.0),
    )
    trigger = str(values.get("trigger", "coarse"))
    threshold = trigger == "damage_threshold"
    return CooldownProcEffect(
        source,
        required.number("cooldown"),
        bool(values.get("repeat_on_cooldown", True)),
        trigger=trigger,
        damage_threshold_ratio=(
            required.number("damage_threshold_ratio") if threshold else 0.0
        ),
        damage_threshold_window=(
            required.number("damage_threshold_window") if threshold else 0.0
        ),
        # The structural flag decides whether a refund exists; its parsed
        # value is then required, so a parse miss raises instead of
        # silently compiling a refund-less Bullseye.
        on_attack_cooldown_refund=(
            required.number("on_attack_cooldown_refund")
            if values.get("attack_refund")
            else 0.0
        ),
    )


def _compile_ultimate_proc(
    item_name: str,
    values: Mapping[str, Any],
) -> UltimateProcEffect:
    """Compile one ultimate-triggered duration formula."""
    required = _RequiredValues(item_name, values)
    formula = required.value("formula")
    if formula not in {"flat_ap", "flat"}:
        raise ValueError(f"Unsupported ultimate proc formula for {item_name!r}")
    base = required.number("base")
    ap_ratio = required.number("ap_ratio") if formula == "flat_ap" else 0.0

    def raw(inputs: DamageInputs) -> float:
        return base + ap_ratio * inputs.champion_stats.get("ability_power", 0.0)

    source = _damage_source(
        item_name,
        required.value("damage_type"),
        raw,
        suffix="Hatefog",
        breakdown_key=f"ult_proc_{item_name}",
    )
    return UltimateProcEffect(
        source,
        required.number("duration"),
        # Malignance's Hatefog packet and its target MR reduction are one
        # parser-owned sibling effect. Other ultimate procs have no MR
        # reduction and therefore carry an explicit zero.
        (
            required.number("mr_reduction")
            if item_name == "Malignance"
            else (required.number("mr_reduction") if "mr_reduction" in values else 0.0)
        ),
    )


def _compile_active(item_name: str, values: Mapping[str, Any]) -> DamageSource:
    """Compile one once-per-fight active damage formula."""
    required = _RequiredValues(item_name, values)
    formula = required.value("formula")
    if formula == "flat_ap":
        base = required.number("base")
        ap_ratio = required.number("ap_ratio")

        def raw(inputs: DamageInputs) -> float:
            return base + ap_ratio * inputs.champion_stats.get("ability_power", 0.0)

    elif formula == "total_ad":
        ratio = required.number("total_ad_ratio")

        def raw(inputs: DamageInputs) -> float:
            return ratio * inputs.champion_stats.get("attack_damage", 0.0)

    elif formula == "level_ap":
        base_min = required.number("base_min")
        base_max = required.number("base_max")
        ap_ratio = required.number("ap_ratio")

        def raw(inputs: DamageInputs) -> float:
            level = max(1, min(inputs.level, 20))
            base = base_min + (base_max - base_min) * (level - 1) / 19
            return base + ap_ratio * inputs.champion_stats.get("ability_power", 0.0)

    else:
        raise ValueError(f"Unsupported active formula {formula!r} for {item_name!r}")
    raw_lifesteal_effectiveness = values.get("lifesteal_effectiveness", 0.0)
    lifesteal_effectiveness = (
        float(raw_lifesteal_effectiveness)
        if isinstance(raw_lifesteal_effectiveness, (int, float))
        and not isinstance(raw_lifesteal_effectiveness, bool)
        else 0.0
    )
    return _damage_source(
        item_name,
        required.value("damage_type"),
        raw,
        suffix="active",
        breakdown_key=f"active_{item_name}",
        lifesteal_effectiveness=lifesteal_effectiveness,
    )


def _explicit_damage_source(
    item_name: str,
    required: _RequiredValues,
    raw_damage: RawDamageFormula,
) -> DamageSource:
    """Compile registry-owned presentation metadata for special behaviors."""
    return DamageSource(
        item_name=item_name,
        breakdown_key=str(required.value("breakdown_key")),
        display_name=str(required.value("display_name")),
        damage_type=required.value("damage_type"),
        raw_damage=raw_damage,
        basic_damage=bool(required.values.get("basic_damage", False)),
    )


def _compile_first_auto(
    item_name: str,
    values: Mapping[str, Any],
) -> FirstAutoEffect:
    """Compile a first-auto raw formula without exposing item identity."""
    required = _RequiredValues(item_name, values)
    formula = required.value("formula")
    if formula == "flat":
        base = required.number("base")

        def raw(_inputs: DamageInputs) -> float:
            return base

    elif formula == "flat_base_ad":
        base = required.number("base")
        base_ad_ratio = required.number("base_ad_ratio")

        def raw(inputs: DamageInputs) -> float:
            return base + base_ad_ratio * inputs.champion_stats.get(
                "base_attack_damage", 0.0
            )

    elif formula == "flat_max_hp":
        base = required.number("base")
        max_hp_ratio = required.number("max_hp_ratio")

        def raw(inputs: DamageInputs) -> float:
            return base + max_hp_ratio * inputs.champion_stats.get("health", 0.0)

    elif formula == "current_hp":
        melee_ratio = required.number("current_hp_ratio_melee")
        ranged_ratio = required.number("current_hp_ratio_ranged")

        def raw(inputs: DamageInputs) -> float:
            ratio = melee_ratio if inputs.is_melee else ranged_ratio
            return ratio * inputs.target_current_health

    else:
        raise ValueError(
            f"Unsupported first-auto formula {formula!r} for {item_name!r}"
        )

    max_procs = 1
    if values.get("uses_empowered_auto_count"):
        max_procs = int(required.number("empowered_auto_count"))
    temporary_lethality_keys = (
        "temporary_lethality_melee",
        "temporary_lethality_ranged",
        "temporary_lethality_duration",
    )
    # Voltaic's first-auto proc is the only registered temporary-lethality
    # effect.  Its three values are one typed contract; accepting a partial
    # record would silently turn a parser break into zero lethality/duration.
    if item_name == "Voltaic Cyclosword" or any(
        key in values for key in temporary_lethality_keys
    ):
        temporary_lethality = {
            key: required.number(key) for key in temporary_lethality_keys
        }
    else:
        temporary_lethality = {}
    return FirstAutoEffect(
        _explicit_damage_source(item_name, required, raw),
        max_procs=max_procs,
        temporary_lethality_melee=temporary_lethality.get(
            "temporary_lethality_melee", 0.0
        ),
        temporary_lethality_ranged=temporary_lethality.get(
            "temporary_lethality_ranged", 0.0
        ),
        temporary_lethality_duration=temporary_lethality.get(
            "temporary_lethality_duration", 0.0
        ),
        energized_max_stacks=(
            int(required.number("energized_max_stacks"))
            if "energized_max_stacks" in values
            else 0
        ),
        energized_attack_stacks=(
            int(required.number("energized_attack_stacks"))
            if "energized_attack_stacks" in values
            else 0
        ),
        energized_ability_trigger=bool(values.get("energized_ability_trigger", False)),
        chain_targets_min=(
            int(required.number("chain_targets_min"))
            if "chain_targets_min" in values
            else 0
        ),
        chain_targets_max=(
            int(required.number("chain_targets_max"))
            if "chain_targets_max" in values
            else 0
        ),
    )


def _compile_stacking_on_hit(
    item_name: str,
    values: Mapping[str, Any],
) -> StackingOnHitEffect:
    """Compile every-Nth-on-hit damage and its current-HP dependency."""
    required = _RequiredValues(item_name, values)
    formula = required.value("formula")
    if formula == "base_ad_max_hp":
        base_ad_melee = required.number("base_ad_ratio_melee")
        base_ad_ranged = required.number("base_ad_ratio_ranged")
        hp_melee = required.number("max_hp_ratio_melee")
        hp_ranged = required.number("max_hp_ratio_ranged")

        def raw(inputs: DamageInputs) -> float:
            base_ad_ratio = base_ad_melee if inputs.is_melee else base_ad_ranged
            hp_ratio = hp_melee if inputs.is_melee else hp_ranged
            stats = inputs.champion_stats
            return base_ad_ratio * stats.get(
                "base_attack_damage", 0.0
            ) + hp_ratio * stats.get("health", 0.0)

        tracks_target_health = False
    elif formula == "level_missing_hp":
        base_melee = required.number("base_melee")
        per_level_melee = required.number("per_level_melee")
        base_ranged = required.number("base_ranged")
        per_level_ranged = required.number("per_level_ranged")
        scaling_start = int(required.number("scaling_start_level"))
        missing_bonus = required.number("missing_hp_bonus_max")

        def raw(inputs: DamageInputs) -> float:
            base = base_melee if inputs.is_melee else base_ranged
            per_level = per_level_melee if inputs.is_melee else per_level_ranged
            if inputs.level >= scaling_start:
                base += per_level * (inputs.level - scaling_start + 1)
            missing_ratio = max(
                0.0,
                1.0 - inputs.target_current_health / inputs.target_max_health,
            )
            return base * (1.0 + missing_bonus * missing_ratio)

        tracks_target_health = True
    else:
        raise ValueError(f"Unsupported stacking formula {formula!r} for {item_name!r}")

    return StackingOnHitEffect(
        source=_explicit_damage_source(item_name, required, raw),
        hits_required=int(required.number("hits_required")),
        tracks_target_health=tracks_target_health,
    )


def _compile_max_hp_proc(
    item_name: str,
    values: Mapping[str, Any],
) -> CooldownProcEffect:
    """Compile a cooldown proc based on target maximum health."""
    required = _RequiredValues(item_name, values)
    if required.value("formula") != "max_hp":
        raise ValueError(f"Unsupported max-HP proc formula for {item_name!r}")
    melee_ratio = required.number("target_max_hp_ratio_melee")
    ranged_ratio = required.number("target_max_hp_ratio_ranged")
    stack_required = int(required.number("stack_required"))
    stack_window = required.number("stack_window")
    shield_melee_base = 0.0
    shield_ranged_base = 0.0
    shield_melee_bonus_ad_ratio = 0.0
    shield_ranged_bonus_ad_ratio = 0.0
    shield_duration = 0.0
    if item_name == "Eclipse":
        shield_melee_base = required.number("shield_melee_base")
        shield_ranged_base = required.number("shield_ranged_base")
        shield_melee_bonus_ad_ratio = required.number("shield_melee_bonus_ad_ratio")
        shield_ranged_bonus_ad_ratio = required.number("shield_ranged_bonus_ad_ratio")
        shield_duration = required.number("shield_duration")

    def raw(inputs: DamageInputs) -> float:
        ratio = melee_ratio if inputs.is_melee else ranged_ratio
        return ratio * inputs.target_max_health

    return CooldownProcEffect(
        source=_explicit_damage_source(item_name, required, raw),
        cooldown=required.number("cooldown"),
        late_phase=True,
        stack_required=stack_required,
        stack_window=stack_window,
        self_shield_melee_base=shield_melee_base,
        self_shield_ranged_base=shield_ranged_base,
        self_shield_melee_bonus_ad_ratio=shield_melee_bonus_ad_ratio,
        self_shield_ranged_bonus_ad_ratio=shield_ranged_bonus_ad_ratio,
        self_shield_duration=shield_duration,
    )


def _compile_shaped_charge(
    item_name: str,
    values: Mapping[str, Any],
) -> CooldownProcEffect:
    """Compile an ability-triggered lethality proc without scheduling it."""
    required = _RequiredValues(item_name, values)
    base_melee = required.number("base_melee")
    base_ranged = required.number("base_ranged")
    ratio_melee = required.number("lethality_ratio_melee")
    ratio_ranged = required.number("lethality_ratio_ranged")

    def raw(inputs: DamageInputs) -> float:
        base = base_melee if inputs.is_melee else base_ranged
        ratio = ratio_melee if inputs.is_melee else ratio_ranged
        return base + ratio * inputs.champion_stats.get("lethality", 0.0)

    source = DamageSource(
        item_name=item_name,
        breakdown_key=f"shaped_charge_{item_name}",
        display_name=f"{item_name} (Shaped Charge)",
        damage_type="true",
        raw_damage=raw,
    )
    return CooldownProcEffect(source, required.number("cooldown"))


def _compile_damage_amplifier(
    item_name: str,
    values: Mapping[str, Any],
) -> DamageAmplifierEffect:
    """Compile one supported amplifier schema into a fight-time formula."""
    required = _RequiredValues(item_name, values)

    if "damage_amp_per_second" in values:
        per_second = required.number("damage_amp_per_second")
        maximum = required.number("damage_amp_max")

        def amp_fraction(duration: float, _target_bonus_health: float) -> float:
            stacks = min(duration, maximum / per_second)
            return per_second * stacks / 2.0

    elif "amp_per_second" in values:
        per_second = required.number("amp_per_second")
        maximum = required.number("amp_max")

        def amp_fraction(duration: float, _target_bonus_health: float) -> float:
            stacks = min(duration, maximum / per_second)
            return per_second * stacks / 2.0

    elif "bonus_hp_cap" in values:
        maximum = required.number("max_amp")
        bonus_hp_cap = required.number("bonus_hp_cap")

        def amp_fraction(_duration: float, target_bonus_health: float) -> float:
            return maximum * min(target_bonus_health / bonus_hp_cap, 1.0)

    elif "amp_per_stack" in values:
        per_stack = required.number("amp_per_stack")
        maximum_stacks = int(required.number("max_stacks"))

        def amp_fraction(duration: float, _target_bonus_health: float) -> float:
            stacks = min(maximum_stacks, max(1, int(duration / 2)))
            return per_stack * stacks

    else:
        raise KeyError(
            f"ITEM_EFFECTS[{item_name!r}] has unsupported damage-amplifier schema"
        )

    return DamageAmplifierEffect(item_name, amp_fraction)


_KNOWN_EFFECT_TYPES = frozenset(
    {
        "ability_damage_amp",
        "active",
        "armor_reduction",
        "basic_damage_amp",
        "burn",
        "conditional_attack_speed",
        "crit_modifier",
        "damage_amp",
        "defensive_start",
        "execute",
        "first_auto_crit",
        "hypershot_amp",
        "immolate",
        "magic_damage_amp",
        "magic_true_crit",
        "max_hp_proc",
        "mr_reduction_stacking",
        "on_hit",
        "on_hit_heal",
        "on_hit_once",
        "on_hit_stacking",
        "periodic_aoe",
        "proc",
        "shaped_charge",
        "shield_reduction",
        "spellblade",
        "secondary_target",
        "stat_conversion",
        "sustain",
        "target_mitigation",
        "target_state",
        "target_attack_speed_aura",
        "target_threshold_health",
        "target_threshold_shield",
        "thorns",
        "ult_attack_speed_buff",
        "ult_empowered_autos",
        "ult_proc",
    }
)


def resolve_damage_effects(
    items: Sequence[Mapping[str, Any]],
) -> BuildDamageEffects:
    """Compile a build's registered damage behaviors from the live registry.

    The compilation is a pure function of the item names and their registry
    entries, and the result is immutable, so repeat builds (the optimizer
    scores thousands per search) reuse one compiled object.  A hit is valid
    only while every referenced registry entry is the identical object —
    replacing an entry (tests, data refresh) invalidates it naturally, and
    ``refresh_item_effects`` clears the memo wholesale.
    """
    memo_key = tuple(str(item.get("name", "")) for item in items)
    cached = _RESOLVED_DAMAGE_EFFECTS.get(memo_key)
    if cached is not None:
        resolved, entry_refs = cached
        if all(ITEM_EFFECTS.get(name) is ref for name, ref in entry_refs):
            return resolved
    resolved = _resolve_damage_effects_uncached(items)
    if len(_RESOLVED_DAMAGE_EFFECTS) >= 4096:
        _RESOLVED_DAMAGE_EFFECTS.clear()
    _RESOLVED_DAMAGE_EFFECTS[memo_key] = (
        resolved,
        tuple((name, ITEM_EFFECTS.get(name)) for name in memo_key),
    )
    return resolved


_RESOLVED_DAMAGE_EFFECTS: dict[
    tuple[str, ...],
    tuple[BuildDamageEffects, tuple[tuple[str, Any], ...]],
] = {}


def _resolve_damage_effects_uncached(
    items: Sequence[Mapping[str, Any]],
) -> BuildDamageEffects:
    """Compile a build's registered damage behaviors from the live registry."""
    per_hits: list[PerHitEffect] = []
    on_hit_heals: list[OnHitHealEffect] = []
    spellblade: SpellbladeEffect | None = None
    burns: list[BurnEffect] = []
    immolates: list[DamageSource] = []
    periodic: list[PeriodicEffect] = []
    cooldown_procs: list[CooldownProcEffect] = []
    ultimate_procs: list[UltimateProcEffect] = []
    actives: list[DamageSource] = []
    first_autos: list[FirstAutoEffect] = []
    stacking_on_hits: list[StackingOnHitEffect] = []
    auto_cooldowns: list[AutoCooldownEffect] = []
    per_ability_hits: list[DamageSource] = []
    shaped_charges: list[CooldownProcEffect] = []
    phantom_hit: PhantomHitEffect | None = None
    ultimate_auto_buff: UltimateAutoBuffEffect | None = None
    stacking_pen: StackingPenEffect | None = None
    navori_refund_percent = 0.0
    crit_damage_bonus = 0.0
    first_auto_crit: FirstAutoCritEffect | None = None
    magic_true_crit: MagicTrueCritEffect | None = None
    damage_amplifiers: list[DamageAmplifierEffect] = []
    magic_amp = 1.0
    basic_amp: BasicAmplifierEffect | None = None
    ability_amp: AbilityAmplifierEffect | None = None
    hypershot_amp = 1.0
    armor_reduction: ArmorReductionEffect | None = None
    ability_amp_source: str | None = None
    execute: ExecuteEffect | None = None
    stacking_mr_reduction: StackingReductionEffect | None = None
    cooldown_refund_source: str | None = None
    conditional_notes: list[str] = []

    for item in items:
        item_name = str(item.get("name", ""))
        values = ITEM_EFFECTS.get(item_name)
        if not values:
            continue
        effect_type = values.get("type")
        if effect_type not in _KNOWN_EFFECT_TYPES:
            raise ValueError(
                f"ITEM_EFFECTS[{item_name!r}] has unknown effect type {effect_type!r}"
            )
        if effect_type == "on_hit":
            per_hits.append(_compile_on_hit(item_name, values))
        elif effect_type == "on_hit_heal":
            on_hit_heals.append(_compile_on_hit_heal(item_name, values))
        elif effect_type == "spellblade" and spellblade is None:
            spellblade = _compile_spellblade(item_name, values)
        elif effect_type == "burn":
            burns.append(_compile_burn(item_name, values))
        elif effect_type == "immolate":
            immolates.append(_compile_immolate(item_name, values))
        elif effect_type == "periodic_aoe":
            periodic.append(_compile_periodic(item_name, values))
        elif effect_type == "proc":
            cooldown_procs.append(_compile_proc(item_name, values))
        elif effect_type == "ult_proc":
            ultimate_procs.append(_compile_ultimate_proc(item_name, values))
        elif effect_type == "active":
            actives.append(_compile_active(item_name, values))
        elif effect_type == "on_hit_once":
            first_autos.append(_compile_first_auto(item_name, values))
        elif effect_type == "on_hit_stacking":
            stacking_on_hits.append(_compile_stacking_on_hit(item_name, values))
        elif effect_type == "max_hp_proc":
            cooldown_procs.append(_compile_max_hp_proc(item_name, values))
        elif effect_type == "shaped_charge":
            shaped_charges.append(_compile_shaped_charge(item_name, values))
        elif effect_type == "ult_empowered_autos":
            required = _RequiredValues(item_name, values)
            ultimate_auto_buff = UltimateAutoBuffEffect(
                item_name=item_name,
                bonus_attack_speed_percent=required.number(
                    "bonus_attack_speed_percent"
                ),
                empowered_auto_count=int(required.number("empowered_auto_count")),
                duration=required.number("duration"),
                reduced_crit_ratio=required.number("reduced_crit_ratio"),
                natural_crit_true_damage_ratio=required.number(
                    "natural_crit_true_damage_ratio"
                ),
            )
            conditional_notes.append(
                "R is assumed to be cast at the start of the fight. "
                f"{item_name} empowered attacks "
                f"({required.number('bonus_attack_speed_percent'):.0f}% bonus AS, "
                "guaranteed crits) are applied from time 0."
            )
        elif effect_type == "ult_attack_speed_buff":
            required = _RequiredValues(item_name, values)
            conditional_notes.append(
                "R is assumed to be cast at the start of the fight. "
                f"{item_name} Overdrive "
                f"({required.number('bonus_attack_speed_melee'):.0f}% melee / "
                f"{required.number('bonus_attack_speed_ranged'):.0f}% ranged "
                "bonus AS) is applied from time 0."
            )
        elif effect_type == "magic_true_crit":
            required = _RequiredValues(item_name, values)
            magic_true_crit = MagicTrueCritEffect(
                item_name,
                required.number("health_threshold"),
                required.number("crit_multiplier"),
            )
        elif effect_type == "basic_damage_amp":
            required = _RequiredValues(item_name, values)
            basic_amp = BasicAmplifierEffect(
                item_name=item_name,
                max_amp=required.number("max_amp"),
                max_distance=required.number("max_distance"),
                melee_assumed_distance=required.number("melee_assumed_distance"),
            )
        elif effect_type == "ability_damage_amp":
            required = _RequiredValues(item_name, values)
            ability_amp = AbilityAmplifierEffect(
                item_name,
                required.number("base_amp"),
                required.number("amp_per_100_bonus_mana"),
            )
            ability_amp_source = item_name
        elif effect_type == "execute":
            execute = ExecuteEffect(
                item_name,
                _RequiredValues(item_name, values).number("threshold"),
            )
        elif effect_type == "mr_reduction_stacking":
            required = _RequiredValues(item_name, values)
            stacking_mr_reduction = StackingReductionEffect(
                required.number("mr_reduction_per_stack"),
                int(required.number("max_stacks")),
            )
        elif effect_type == "crit_modifier":
            required = _RequiredValues(item_name, values)
            if "bonus_crit_damage" in values:
                crit_damage_bonus += required.number("bonus_crit_damage")
            if "cd_refund_percent" in values:
                navori_refund_percent = required.number("cd_refund_percent")
                cooldown_refund_source = item_name
        elif effect_type == "secondary_target":
            # Wind's Fury is priced by the shared roster event ledger.  Keep
            # the typed effect in the build projection without adding a stale
            # conditional note that would contradict its targeting receipt.
            continue
        if "damage_amp_per_second" in values or effect_type == "damage_amp":
            damage_amplifiers.append(_compile_damage_amplifier(item_name, values))
        if effect_type == "magic_damage_amp":
            magic_amp += _RequiredValues(item_name, values).number("magic_amp")
        if effect_type == "hypershot_amp":
            hypershot_amp += _RequiredValues(item_name, values).number("amp")
        if effect_type == "armor_reduction":
            required = _RequiredValues(item_name, values)
            armor_reduction = ArmorReductionEffect(
                required.number("reduction_per_stack"),
                int(required.number("max_stacks")),
            )
        splash_note = values.get("unmodeled_splash_note")
        if splash_note:
            conditional_notes.append(str(splash_note))
        secondary = values.get("secondary_behavior")
        if secondary == "auto_cooldown":
            auto_cooldowns.append(_compile_auto_cooldown(item_name, values))
        elif secondary == "per_ability_hit":
            per_ability_hits.append(_compile_per_ability_hit(item_name, values))
        if values.get("phantom_hit"):
            required = _RequiredValues(item_name, values)
            phantom_hit = PhantomHitEffect(
                item_name,
                int(required.number("stacking_autos")),
                int(required.number("phantom_interval")),
            )
        if "dark_pen_per_stack" in values and "dark_max_stacks" in values:
            required = _RequiredValues(item_name, values)
            stacking_pen = StackingPenEffect(
                required.number("dark_pen_per_stack"),
                int(required.number("dark_max_stacks")),
            )
        if "reduced_crit_ratio" in values and effect_type == "first_auto_crit":
            first_auto_crit = FirstAutoCritEffect(
                item_name,
                _RequiredValues(item_name, values).number("reduced_crit_ratio"),
                heal_base_ad_ratio=(
                    _RequiredValues(item_name, values).number("heal_base_ad_ratio")
                    if "heal_base_ad_ratio" in values
                    else 0.0
                ),
                heal_missing_health_ratio=(
                    _RequiredValues(item_name, values).number(
                        "heal_missing_health_ratio"
                    )
                    if "heal_missing_health_ratio" in values
                    else 0.0
                ),
                temporary_health_duration=(
                    _RequiredValues(item_name, values).number(
                        "temporary_health_duration"
                    )
                    if "temporary_health_duration" in values
                    else 0.0
                ),
            )

    return BuildDamageEffects(
        per_hits=tuple(per_hits),
        on_hit_heals=tuple(on_hit_heals),
        spellblade=spellblade,
        burns=tuple(burns),
        immolates=tuple(immolates),
        periodic=tuple(periodic),
        cooldown_procs=tuple(cooldown_procs),
        ultimate_procs=tuple(ultimate_procs),
        actives=tuple(actives),
        first_autos=tuple(first_autos),
        stacking_on_hits=tuple(stacking_on_hits),
        auto_cooldowns=tuple(auto_cooldowns),
        per_ability_hits=tuple(per_ability_hits),
        shaped_charges=tuple(shaped_charges),
        phantom_hit=phantom_hit,
        ultimate_auto_buff=ultimate_auto_buff,
        stacking_pen=stacking_pen,
        navori_refund_percent=navori_refund_percent,
        crit_damage_bonus=crit_damage_bonus,
        first_auto_crit=first_auto_crit,
        magic_true_crit=magic_true_crit,
        damage_amplifiers=tuple(damage_amplifiers),
        magic_amp=magic_amp,
        basic_amp=basic_amp,
        ability_amp=ability_amp,
        hypershot_amp=hypershot_amp,
        armor_reduction=armor_reduction,
        ability_amp_source=ability_amp_source,
        execute=execute,
        stacking_mr_reduction=stacking_mr_reduction,
        cooldown_refund_source=cooldown_refund_source,
        conditional_notes=tuple(conditional_notes),
    )


# ---------------------------------------------------------------------------
# Stat-modifying passives (consumed by stats.py)
# ---------------------------------------------------------------------------
# These accessors own both the ITEM_EFFECTS lookup and the numeric
# semantics of each stat-granting passive; stats.py only orchestrates
# when to apply them.  Each passive applies once per build regardless of
# duplicate copies (legendary items are unique).


def _ap_multiplier(items: list[dict[str, Any]]) -> float:
    """Backward-compatible private alias for :func:`ap_multiplier`."""
    return ap_multiplier(items)


def ap_multiplier(items: list[dict[str, Any]]) -> float:
    """Return parser-owned additive AP multiplier from item passives.

    Rabadon's Deathcap (+30% AP) and Blackfire Torch (+4% AP per burning
    champion, assumed 1 target) stack additively: 30% + 4% = ×1.34.

    Args:
        items: List of item data dicts.

    Returns:
        Multiplier applied to total AP (e.g. 1.30 with Rabadon's).
    """
    names = _item_names(items)
    bonus = 0.0
    if "Rabadon's Deathcap" in names:
        bonus += required_effect_value("Rabadon's Deathcap", "ap_percent_increase")
    if "Blackfire Torch" in names:
        bonus += required_effect_value("Blackfire Torch", "ap_amp_per_target")
    return 1.0 + bonus


def _permanent_ap_multiplier(items: list[dict[str, Any]]) -> float:
    """Backward-compatible private alias for :func:`permanent_ap_multiplier`."""
    return permanent_ap_multiplier(items)


def permanent_ap_multiplier(items: list[dict[str, Any]]) -> float:
    """Return parser-backed AP multiplier eligible as a permanent stat.

    Rabadon's always applies. Blackfire Torch's per-burning-target increase is
    a combat state and therefore cannot unlock Living Weapon.
    """
    if "Rabadon's Deathcap" not in _item_names(items):
        return 1.0
    return 1.0 + required_effect_value("Rabadon's Deathcap", "ap_percent_increase")


def _mana_to_ap_bonus(items: list[dict[str, Any]], bonus_mana: float) -> float:
    """Backward-compatible private alias for :func:`mana_to_ap_bonus`."""
    return mana_to_ap_bonus(items, bonus_mana)


def mana_to_ap_bonus(items: list[dict[str, Any]], bonus_mana: float) -> float:
    """Return parser-owned Awe bonus-mana-to-AP conversion.

    Args:
        items: List of item data dicts.
        bonus_mana: Total bonus mana from items.

    Returns:
        Flat bonus AP from mana conversion.
    """
    names = _item_names(items)
    total = 0.0
    for name in ("Archangel's Staff", "Seraph's Embrace"):
        if name in names:
            total += required_effect_value(name, "bonus_mana_to_ap_ratio") * bonus_mana
    return total


def mana_to_health_bonus(items: list[dict[str, Any]], bonus_mana: float) -> float:
    """Return parser-owned Awe bonus-mana-to-health conversion."""
    names = _item_names(items)
    total = 0.0
    for name in ("Fimbulwinter", "Winter's Approach"):
        if name in names:
            total += (
                required_effect_value(name, "bonus_mana_to_health_ratio") * bonus_mana
            )
    return total


def _dawncore_bonus_ap(
    items: list[dict[str, Any]],
    bonus_mana_regen_percent: float,
) -> float:
    """Backward-compatible private alias for :func:`dawncore_bonus_ap`."""
    return dawncore_bonus_ap(items, bonus_mana_regen_percent)


def dawncore_bonus_ap(
    items: list[dict[str, Any]],
    bonus_mana_regen_percent: float,
) -> float:
    """Return parser-owned Dawncore AP from additional base mana regen.

    Args:
        items: List of item data dicts.
        bonus_mana_regen_percent: Total bonus base mana regen (percent).

    Returns:
        Flat bonus AP from mana regen conversion.
    """
    if "Dawncore" not in _item_names(items):
        return 0.0
    ap_per_unit = required_effect_value("Dawncore", "ap_per_mana_regen_unit")
    threshold = required_effect_value("Dawncore", "mana_regen_threshold_percent")
    return (bonus_mana_regen_percent / threshold) * ap_per_unit


def _flowing_water_bonus_ap(items: list[dict[str, Any]]) -> float:
    """Backward-compatible private alias for :func:`flowing_water_bonus_ap`."""
    return flowing_water_bonus_ap(items)


def flowing_water_bonus_ap(items: list[dict[str, Any]]) -> float:
    """Return parser-owned Staff of Flowing Water Rapids AP.

    Args:
        items: List of item data dicts.

    Returns:
        Flat bonus AP from Rapids.
    """
    if "Staff of Flowing Water" not in _item_names(items):
        return 0.0
    return required_effect_value("Staff of Flowing Water", "rapids_bonus_ap")


def _passive_attack_speed_bonus(
    items: list[dict[str, Any]],
    is_melee: bool,
) -> float:
    """Backward-compatible private alias for :func:`passive_attack_speed_bonus`."""
    return passive_attack_speed_bonus(items, is_melee)


def passive_attack_speed_bonus(
    items: list[dict[str, Any]],
    is_melee: bool,
) -> float:
    """Return parser-owned assumed-active item attack-speed bonuses.

    Bandlepipes Fanfare (melee/ranged split), Experimental Hexplate
    Overdrive (active from R cast at fight start), and Yun Tal Wildarrows
    Flurry (active while attacking a champion).

    Args:
        items: List of item data dicts.
        is_melee: Whether the champion is melee.

    Returns:
        Bonus attack speed percentage (e.g. 50.0 for 50%).
    """
    names = _item_names(items)
    bonus = 0.0
    split_key = "bonus_attack_speed_melee" if is_melee else "bonus_attack_speed_ranged"
    for name in ("Bandlepipes", "Experimental Hexplate"):
        if name in names:
            bonus += required_effect_value(name, split_key)
    if "Yun Tal Wildarrows" in names:
        # The public stat panel shows the sourced conditional package; the
        # fight resolver subtracts it from the opening rate and re-applies it
        # through the authored swing schedule after the first attack.
        bonus += required_effect_value(
            "Yun Tal Wildarrows", "bonus_attack_speed_percent"
        )
    return bonus


def guinsoo_attack_speed_percent(
    items: list[dict[str, Any]], stack_count: int
) -> float:
    """Return Seething Strike's temporary attack-speed bonus.

    The ordered fight ledger owns stack admission and expiry; this accessor
    keeps the patch-sourced values in ``ITEM_EFFECTS`` so that callers cannot
    smuggle a stale 8%/32% literal into an attack schedule.
    """
    if "Guinsoo's Rageblade" not in _item_names(items):
        return 0.0
    per_stack = float(
        required_effect_value("Guinsoo's Rageblade", "seething_attack_speed_per_stack")
    )
    max_stacks = int(
        required_effect_value("Guinsoo's Rageblade", "seething_max_stacks")
    )
    return 100.0 * per_stack * min(max(0, int(stack_count)), max_stacks)


# The schedule intentionally accepts the authored timing inputs explicitly so
# callers cannot hide state in an untyped global or stale fallback.
# pylint: disable=too-many-arguments,too-many-locals
def guinsoo_swing_schedule(
    items: list[dict[str, Any]],
    *,
    attack_speed: float,
    attack_speed_ratio: float,
    duration_seconds: float,
    uptime: float = 1.0,
    critical_chance: float = 0.0,
) -> tuple[float, ...]:
    """Build the authored auto schedule while Seething stacks rise/expire.

    The first attack lands at ``t=0``. Each completed attack grants one
    Seething stack for the sourced three-second duration, capped at the
    sourced stack count. When Yun Tal is present, the first champion attack
    also starts Flurry; later attacks reduce its cooldown by the sourced
    base/critical refund while its six-second attack-speed window is active.
    This helper deliberately has no roster or damage side effects; the fight
    ledger consumes only the resulting authored timestamps.
    """
    if duration_seconds <= 0.0 or uptime <= 0.0 or attack_speed <= 0.0:
        return ()
    names = _item_names(items)
    has_guinsoo = "Guinsoo's Rageblade" in names
    has_yun_tal = "Yun Tal Wildarrows" in names
    if not has_guinsoo and not has_yun_tal:
        interval = 1.0 / (attack_speed * uptime)
        count = max(0, int(duration_seconds * attack_speed * uptime))
        return tuple(index * interval for index in range(count))

    stack_duration = (
        float(required_effect_value("Guinsoo's Rageblade", "seething_duration"))
        if has_guinsoo
        else 0.0
    )
    times: list[float] = [0.0]
    stack_times: list[float] = [0.0]
    current = 0.0
    yun_active_until = (
        float(required_effect_value("Yun Tal Wildarrows", "duration"))
        if has_yun_tal
        else 0.0
    )
    yun_cooldown = (
        float(required_effect_value("Yun Tal Wildarrows", "cooldown"))
        if has_yun_tal
        else 0.0
    )
    first_attack = True
    yun_refund = (
        float(required_effect_value("Yun Tal Wildarrows", "attack_refund_base"))
        + max(0.0, min(1.0, float(critical_chance)))
        * float(required_effect_value("Yun Tal Wildarrows", "attack_refund_crit"))
        if has_yun_tal
        else 0.0
    )
    while True:
        if has_guinsoo:
            stack_times[:] = [t for t in stack_times if current - t < stack_duration]
        else:
            stack_times.clear()
        bonus = (
            guinsoo_attack_speed_percent(items, len(stack_times))
            if has_guinsoo
            else 0.0
        )
        effective_rate = (attack_speed + attack_speed_ratio * bonus / 100.0) * uptime
        if has_yun_tal and not first_attack and current < yun_active_until:
            effective_rate += (
                attack_speed_ratio
                * required_effect_value(
                    "Yun Tal Wildarrows", "bonus_attack_speed_percent"
                )
                / 100.0
                * uptime
            )
        if effective_rate <= 0.0:
            break
        next_time = current + 1.0 / effective_rate
        if next_time >= duration_seconds - 1e-12:
            break
        if has_yun_tal:
            elapsed = next_time - current
            yun_cooldown = max(0.0, yun_cooldown - elapsed)
            if not first_attack:
                yun_cooldown = max(0.0, yun_cooldown - yun_refund)
            if yun_cooldown <= 0.0 and not first_attack:
                yun_active_until = next_time + required_effect_value(
                    "Yun Tal Wildarrows", "duration"
                )
                yun_cooldown = required_effect_value("Yun Tal Wildarrows", "cooldown")
        times.append(next_time)
        if has_guinsoo:
            stack_times.append(next_time)
        current = next_time
        first_attack = False
    return tuple(times)


# pylint: enable=too-many-arguments,too-many-locals


# pylint: disable=too-many-arguments
def yun_tal_swing_schedule(
    items: list[dict[str, Any]],
    *,
    attack_speed: float,
    attack_speed_ratio: float,
    duration_seconds: float,
    uptime: float = 1.0,
    critical_chance: float = 0.0,
) -> tuple[float, ...]:
    """Return the same composed authored schedule for Yun Tal Flurry.

    The shared implementation also composes Guinsoo when both items are
    equipped; this named wrapper keeps the item-facing API explicit for
    focused tests and future consumers.
    """
    return guinsoo_swing_schedule(
        items,
        attack_speed=attack_speed,
        attack_speed_ratio=attack_speed_ratio,
        duration_seconds=duration_seconds,
        uptime=uptime,
        critical_chance=critical_chance,
    )


# pylint: enable=too-many-arguments


def energized_proc_indices(
    item_name: str,
    num_attacks: int,
    *,
    initial_stacks: float = 100,
    movement_units_per_attack: Sequence[float] | None = None,
) -> tuple[int, ...]:
    """Return attack indices that consume an Energized charge.

    The charge schedule follows the shared Wiki Energized entry: movement
    contributes one charge per sourced distance unit and each basic attack
    contributes the item's attack branch (15 for Statikk, 6 for the ordinary
    Energized family).  ``movement_units_per_attack`` is an explicit authored
    schedule; an omitted schedule means an attack-only timeline with zero
    movement, never a guessed distance.
    """
    if num_attacks <= 0:
        return ()
    values = ITEM_EFFECTS.get(item_name)
    if not values or "energized_max_stacks" not in values:
        raise KeyError(f"ITEM_EFFECTS[{item_name!r}] is missing 'energized_max_stacks'")
    maximum = int(required_effect_value(item_name, "energized_max_stacks"))
    stacks = max(0.0, min(float(initial_stacks), float(maximum)))
    if "energized_attack_stacks" not in values:
        raise KeyError(
            f"ITEM_EFFECTS[{item_name!r}] is missing 'energized_attack_stacks' — "
            "parser/schema bug; check passive_parser"
        )
    gain = int(required_effect_value(item_name, "energized_attack_stacks"))
    distance_per_stack = float(
        values.get(
            "energized_distance_units_per_stack",
            ENERGIZED_SOURCE_RECEIPT["distance_units_per_stack"],
        )
    )
    if distance_per_stack <= 0.0:
        raise ValueError(f"{item_name} has invalid Energized distance cadence")
    movement = tuple(movement_units_per_attack or ())
    if len(movement) > num_attacks:
        raise ValueError(f"{item_name} movement schedule has more entries than attacks")
    if any(
        isinstance(units, bool) or not isinstance(units, (int, float)) or units < 0
        for units in movement
    ):
        raise ValueError(
            f"{item_name} movement schedule must contain non-negative numbers"
        )
    procs: list[int] = []
    for index in range(num_attacks):
        if index < len(movement):
            stacks = min(
                float(maximum), stacks + float(movement[index]) / distance_per_stack
            )
        if stacks >= maximum:
            procs.append(index)
            stacks = 0
        stacks = min(float(maximum), stacks + gain)
    return tuple(procs)


def energized_schedule_receipt(item_name: str) -> dict[str, Any]:
    """Return the complete source receipt used by an Energized schedule."""
    maximum = int(required_effect_value(item_name, "energized_max_stacks"))
    attack_stacks = int(required_effect_value(item_name, "energized_attack_stacks"))
    values = ITEM_EFFECTS.get(item_name, {})
    distance = float(
        values.get(
            "energized_distance_units_per_stack",
            ENERGIZED_SOURCE_RECEIPT["distance_units_per_stack"],
        )
    )
    if maximum <= 0 or attack_stacks <= 0 or distance <= 0.0:
        raise ValueError(f"{item_name} has invalid Energized schedule values")
    return {
        "source_url": ENERGIZED_SOURCE_RECEIPT["source_url"],
        "source_revision_id": ENERGIZED_SOURCE_RECEIPT["source_revision_id"],
        "max_stacks": maximum,
        "attack_stacks": attack_stacks,
        "distance_units_per_stack": distance,
        "movement_schedule": "explicit_per_attack; omitted_means_zero_distance",
    }


def runaan_secondary_target_count(
    *,
    roster_target_count: int,
    item_name: str = "Runaan's Hurricane",
) -> int:
    """Return Wind's Fury's bounded secondary-target count.

    The main target is excluded; the ordered roster allocator decides which
    nearby enemies receive these bolts. This helper only supplies the sourced
    cardinality and fails closed if parser data is incomplete.
    """
    if roster_target_count <= 1:
        return 0
    max_targets = int(required_effect_value(item_name, "max_secondary_targets"))
    return min(max_targets, roster_target_count - 1)


def runaan_secondary_target_damage(
    *, total_attack_damage: float, item_name: str = "Runaan's Hurricane"
) -> float:
    """Return one Wind's Fury bolt's AD-scaled physical packet.

    Target allocation and copied on-hit effects remain owned by the shared
    roster ledger; this accessor only exposes the parser-owned per-bolt value.
    """
    ratio = required_effect_value(item_name, "secondary_ad_ratio")
    return float(total_attack_damage) * ratio


def statikk_chain_target_bounds(*, item_name: str = "Statikk Shiv") -> tuple[int, int]:
    """Return Electrospark's sourced minimum/maximum chain target bounds.

    Energized generation and roster fan-out remain owned by the event ledger;
    this helper only exposes the parser-backed level-scaled bounds.
    """
    minimum = int(required_effect_value(item_name, "chain_targets_min"))
    maximum = int(required_effect_value(item_name, "chain_targets_max"))
    if minimum < 1 or maximum < minimum:
        raise ValueError(f"{item_name} has invalid chain target bounds")
    return minimum, maximum


def statikk_chain_target_count(level: int, *, item_name: str = "Statikk Shiv") -> int:
    """Return Electrospark's level-scaled chain target count.

    The cached source gives 4 to 8 targets at levels 1/6/10/14/20.  The
    selected roster may still contain fewer targets; the caller applies that
    roster bound when allocating one proc across participants.
    """
    minimum, maximum = statikk_chain_target_bounds(item_name=item_name)
    breakpoints = (1, 6, 10, 14, 20)
    increments = sum(int(level >= threshold) for threshold in breakpoints[1:])
    return min(maximum, minimum + increments)


def hydra_secondary_target_damage(
    *,
    max_health: float,
    is_melee: bool,
    empowered: bool = False,
    item_name: str = "Titanic Hydra",
) -> float:
    """Return one Hydra Cleave cone packet for a secondary target.

    The fight ledger currently prices only the selected primary target. This
    typed accessor keeps the parser-owned cone ratio available for the future
    multi-target ledger without inventing a fallback when a patch omits it.
    """
    prefix = "active_secondary_" if empowered else "secondary_"
    suffix = "max_hp_ratio_melee" if is_melee else "max_hp_ratio_ranged"
    ratio = required_effect_value(item_name, prefix + suffix)
    return float(max_health) * ratio


def hydra_secondary_item_name(items: Sequence[Mapping[str, Any]]) -> str | None:
    """Return the selected build item with a max-health Cleave cone."""
    required = {
        "secondary_max_hp_ratio_melee",
        "active_secondary_max_hp_ratio_melee",
    }
    for item in items:
        name = str(item.get("name", ""))
        if required.issubset(ITEM_EFFECTS.get(name, {})):
            return name
    return None


def hydra_primary_target_damage(
    *,
    max_health: float,
    is_melee: bool,
    empowered: bool = False,
    item_name: str = "Titanic Hydra",
) -> float:
    """Return one Hydra Cleave packet for the selected primary target.

    Titanic Crescent's empowered packet replaces the ordinary primary
    Cleave value.  Keeping both values behind typed accessors lets the fight
    ledger price only the active delta when the base on-hit row already
    contains the ordinary packet.
    """
    prefix = "active_" if empowered else ""
    suffix = "max_hp_ratio_melee" if is_melee else "max_hp_ratio_ranged"
    ratio = required_effect_value(item_name, prefix + suffix)
    return float(max_health) * ratio


def hydra_cleave_secondary_ad_damage(
    *, total_attack_damage: float, is_melee: bool, item_name: str
) -> float:
    """Return one AD-scaled Hydra/Tiamat Cleave secondary packet."""
    suffix = "secondary_ad_ratio_melee" if is_melee else "secondary_ad_ratio_ranged"
    ratio = required_effect_value(item_name, suffix)
    return float(total_attack_damage) * ratio


def active_secondary_ad_item_name(
    items: Sequence[Mapping[str, Any]],
) -> str | None:
    """Return the selected active with a sourced secondary AD packet."""
    required = {
        "secondary_ad_ratio_melee",
        "secondary_ad_ratio_ranged",
        "total_ad_ratio",
    }
    for item in items:
        name = str(item.get("name", ""))
        values = ITEM_EFFECTS.get(name, {})
        if values.get("type") == "active" and required.issubset(values):
            return name
    return None


def cleave_on_hit_item_name(items: Sequence[Mapping[str, Any]]) -> str | None:
    """Return the selected item whose basic attacks carry Cleave splash."""
    for item in items:
        name = str(item.get("name", ""))
        if ITEM_EFFECTS.get(name, {}).get("cleave_on_hit"):
            return name
    return None


def navori_cooldown_refund_seconds(
    *,
    base_cooldown: float,
    attack_count: int = 1,
    item_name: str = "Navori Flickerblade",
) -> float:
    """Return basic-ability cooldown seconds refunded by Navori autos.

    The refund fraction is parser-owned and applies once per basic attack;
    callers supply the authored attack count from the event ledger.
    """
    if attack_count <= 0 or base_cooldown <= 0:
        return 0.0
    fraction = required_effect_value(item_name, "cd_refund_percent")
    return float(base_cooldown) * fraction * int(attack_count)


def item_bonus_health_multiplier(items: list[dict[str, Any]]) -> float:
    """Return Warmog's parser-owned multiplier for item-granted health."""
    if "Warmog's Armor" not in _item_names(items):
        return 1.0
    return 1.0 + required_effect_value("Warmog's Armor", "item_bonus_health_ratio")


def _muramana_bonus_ad(items: list[dict[str, Any]], max_mana: float) -> float:
    """Backward-compatible private alias for :func:`muramana_bonus_ad`."""
    return muramana_bonus_ad(items, max_mana)


def muramana_bonus_ad(items: list[dict[str, Any]], max_mana: float) -> float:
    """Return Muramana's parser-owned maximum-mana-to-AD conversion.

    Args:
        items: List of item data dicts.
        max_mana: Champion's total maximum mana (base + items).

    Returns:
        Flat bonus AD from Awe.
    """
    if "Muramana" not in _item_names(items):
        return 0.0
    return required_effect_value("Muramana", "max_mana_to_ad_ratio") * max_mana


def endless_hunger_ability_haste(
    items: list[dict[str, Any]],
    *,
    bonus_attack_damage: float,
    is_melee: bool,
) -> float:
    """Return Famine's parser-backed bonus-AD ability haste.

    ``bonus_attack_damage`` is the item's flat AD plus permanent item AD
    conversions already resolved by this stat bundle.  Feast's takedown
    omnivamp is a separate combat state and is intentionally not included.
    """
    if "Endless Hunger" not in _item_names(items):
        return 0.0
    base = required_effect_value("Endless Hunger", "famine_base_ability_haste")
    suffix = "melee" if is_melee else "ranged"
    ratio = required_effect_value(
        "Endless Hunger", f"famine_bonus_ad_to_ability_haste_{suffix}"
    )
    return float(base) + max(0.0, float(bonus_attack_damage)) * float(ratio)


def bloodmail_bonus_ad(
    items: list[dict[str, Any]],
    bonus_health: float,
) -> float:
    """Overlord's Bloodmail Tyranny passive: % of bonus health as bonus AD.

    Public (like ``steraks_bonus_ad``): the fight engine re-applies it
    for ability bonus-health buffs (Cho'Gath R's Feast stacks) — the
    conversion is linear, so the delta composes.

    Args:
        items: List of item data dicts.
        bonus_health: Bonus health to convert (items, or a buff delta).

    Returns:
        Flat bonus AD from Tyranny.
    """
    if "Overlord's Bloodmail" not in _item_names(items):
        return 0.0
    ratio = required_effect_value("Overlord's Bloodmail", "bonus_health_to_ad_ratio")
    return ratio * bonus_health


def bloodmail_retribution_bonus_ad(
    *,
    total_attack_damage: float,
    missing_health_fraction: float,
    item_name: str = "Overlord's Bloodmail",
) -> float:
    """Return Retribution's missing-health-scaled bonus AD.

    The caller supplies total AD from other sources and the ordered health
    state; the participant ledger owns applying this temporary value.
    """
    if item_name not in ITEM_EFFECTS:
        raise KeyError(f"ITEM_EFFECTS[{item_name!r}] is missing")
    missing = max(0.0, min(1.0, float(missing_health_fraction)))
    minimum = required_effect_value(item_name, "retribution_missing_health_min")
    maximum = required_effect_value(item_name, "retribution_missing_health_max")
    return float(total_attack_damage) * (minimum + (maximum - minimum) * missing)


def input_option_retribution_bonus_ad(
    items: list[dict[str, Any]],
    item_options: Mapping[str, Mapping[str, int]] | None,
    *,
    total_attack_damage: float,
) -> float:
    """Return Bloodmail Retribution from explicit starting health state."""
    if "Overlord's Bloodmail" not in _item_names(items) or not item_options:
        return 0.0
    options = item_options.get("Overlord's Bloodmail")
    if not options:
        return 0.0
    missing_percent = options.get("missing_health_percent", 0)
    return bloodmail_retribution_bonus_ad(
        total_attack_damage=total_attack_damage,
        missing_health_fraction=float(missing_percent) / 100.0,
    )


def riftmaker_bonus_ap(*, bonus_health: float, item_name: str = "Riftmaker") -> float:
    """Return Void Infusion's bonus-health-to-AP conversion."""
    if item_name not in ITEM_EFFECTS:
        raise KeyError(f"ITEM_EFFECTS[{item_name!r}] is missing")
    ratio = required_effect_value(item_name, "bonus_health_to_ap_ratio")
    return max(0.0, float(bonus_health)) * ratio


def riftmaker_max_stack_omnivamp(
    *, fight_duration_seconds: float, item_name: str = "Riftmaker"
) -> float:
    """Return Void Corruption's max-stack omnivamp after its sourced ramp.

    Riftmaker gains one 2% damage stack per second, up to four stacks.  The
    fight timeline starts in combat, so a continuous fight reaches the
    max-stack omnivamp branch at four seconds; shorter fights receive none.
    """
    if item_name not in ITEM_EFFECTS:
        raise KeyError(f"ITEM_EFFECTS[{item_name!r}] is missing")
    per_second = required_effect_value(item_name, "amp_per_second")
    max_amp = required_effect_value(item_name, "amp_max")
    max_omnivamp = required_effect_value(item_name, "max_stack_omnivamp")
    if per_second <= 0.0 or max_amp <= 0.0:
        return 0.0
    max_stack_seconds = max_amp / per_second
    return (
        float(max_omnivamp)
        if fight_duration_seconds + 1e-9 >= max_stack_seconds
        else 0.0
    )


def hubris_eminence_bonus_ad(
    *, stacks: int, active: bool = True, item_name: str = "Hubris"
) -> float:
    """Return Eminence's sourced temporary bonus AD for explicit kill state."""
    if item_name not in ITEM_EFFECTS:
        raise KeyError(f"ITEM_EFFECTS[{item_name!r}] is missing")
    if isinstance(stacks, bool) or not isinstance(stacks, int) or stacks < 0:
        raise ValueError("Hubris Eminence stacks must be a non-negative integer")
    if not active:
        return 0.0
    base = required_effect_value(item_name, "eminence_base_ad")
    per_stack = required_effect_value(item_name, "eminence_ad_per_stack")
    return float(base) + float(stacks) * float(per_stack)


def axiom_arc_ultimate_refund_fraction(
    *, lethality: float, item_name: str = "Axiom Arc"
) -> float:
    """Return Flux's sourced fraction of ultimate cooldown refunded."""
    if item_name not in ITEM_EFFECTS:
        raise KeyError(f"ITEM_EFFECTS[{item_name!r}] is missing")
    base = required_effect_value(item_name, "ultimate_refund_base_ratio")
    per_lethality = required_effect_value(
        item_name, "ultimate_refund_per_lethality_ratio"
    )
    return max(0.0, float(base) + max(0.0, float(lethality)) * float(per_lethality))


def essence_reaver_mana_restore_per_proc(
    *,
    base_attack_damage: float,
    critical_strike_chance: float,
    item_name: str = "Essence Reaver",
) -> float:
    """Return Manaflow's sourced mana restoration for one Spellblade proc."""
    if item_name not in ITEM_EFFECTS:
        raise KeyError(f"ITEM_EFFECTS[{item_name!r}] is missing")
    base_ratio = required_effect_value(item_name, "mana_restore_base_ad_ratio")
    crit_ratio = required_effect_value(item_name, "mana_restore_crit_ratio")
    crit_fraction = min(1.0, max(0.0, float(critical_strike_chance) / 100.0))
    return max(0.0, float(base_attack_damage)) * base_ratio + crit_ratio * crit_fraction


def yun_tal_permanent_crit_chance(
    *, stacks: int, is_melee: bool, item_name: str = "Yun Tal Wildarrows"
) -> float:
    """Return Practice Makes Lethal's bounded permanent crit chance."""
    if item_name not in ITEM_EFFECTS:
        raise KeyError(f"ITEM_EFFECTS[{item_name!r}] is missing")
    if isinstance(stacks, bool) or not isinstance(stacks, int) or stacks < 0:
        raise ValueError("Yun Tal stacks must be a non-negative integer")
    suffix = "melee" if is_melee else "ranged"
    per_stack = required_effect_value(item_name, f"crit_chance_per_stack_{suffix}")
    maximum = int(required_effect_value(item_name, f"crit_stack_max_{suffix}"))
    cap = required_effect_value(item_name, "crit_chance_cap")
    return min(float(cap), min(stacks, maximum) * float(per_stack))


def shield_reduction_fraction(items: list[dict[str, Any]], *, is_melee: bool) -> float:
    """Serpent's Fang Shield Reaver: fraction cut from the target's shields.

    The venom does not affect magic-damage shields; the caller applies the
    cut only to non-magic shield pools.

    Args:
        items: The attacker's item data dicts.
        is_melee: Whether the attacker is melee (50% cut) or ranged (35%).

    Returns:
        The reduction fraction, or 0.0 without the item.
    """
    if "Serpent's Fang" not in _item_names(items):
        return 0.0
    key = "shield_reduction_melee" if is_melee else "shield_reduction_ranged"
    return float(required_effect_value("Serpent's Fang", key))


@dataclass(frozen=True, slots=True)
class ThornsEffect:
    """One reactive strike-back packet consumed by the coupled timeline.

    The wearer deals ``damage`` (pre-mitigation) to each champion whose
    basic attack strikes them and wounds that attacker for
    ``grievous_duration`` seconds. The Grievous Wounds strength itself is
    the patch-wide rule in :mod:`healing_reduction`.
    """

    item_name: str
    damage_type: DamageType
    damage: float
    grievous_duration: float
    bonus_armor_ratio: float = 0.0


def thorns_effects(items: Sequence[Mapping[str, Any]]) -> tuple[ThornsEffect, ...]:
    """Compile the build's reactive Thorns packets (Bramble Vest).

    Args:
        items: The wearer's item data dicts.

    Returns:
        One packet per equipped thorns item; empty without one.
    """
    compiled: list[ThornsEffect] = []
    for item in items:
        item_name = str(item.get("name", ""))
        values = ITEM_EFFECTS.get(item_name)
        if not values or values.get("type") != "thorns":
            continue
        required = _RequiredValues(item_name, values)
        compiled.append(
            ThornsEffect(
                item_name=item_name,
                damage_type=required.value("damage_type"),
                damage=required.number("base"),
                bonus_armor_ratio=required.number("bonus_armor_ratio"),
                grievous_duration=required.number("grievous_duration"),
            )
        )
    return tuple(compiled)


def steraks_bonus_ad(items: list[dict[str, Any]], base_ad: float) -> float:
    """Return parser-backed Sterak's base-AD conversion.

    Args:
        items: List of item data dicts.
        base_ad: Champion's base attack damage at the current level.

    Returns:
        Flat bonus AD from the passive.
    """
    if "Sterak's Gage" not in _item_names(items):
        return 0.0
    return required_effect_value("Sterak's Gage", "base_ad_to_bonus_ad_ratio") * base_ad


def _terminus_max_stack_bonuses(
    items: list[dict[str, Any]],
    level: int,
) -> tuple[float, float]:
    """Backward-compatible private alias for :func:`terminus_max_stack_bonuses`."""
    return terminus_max_stack_bonuses(items, level)


def terminus_max_stack_bonuses(
    items: list[dict[str, Any]],
    level: int,
) -> tuple[float, float]:
    """Return parser-owned Terminus max-stack resist and pen state.

    Light hits grant level-scaled bonus armor + MR per stack; dark hits
    grant % armor and magic penetration per stack.  Both are assumed at
    max stacks for the stat display; the fight engine consumes the compiled
    ``StackingPenEffect`` to use a ramping per-auto average.

    Args:
        items: List of item data dicts.
        level: Champion level (1-18).

    Returns:
        Tuple of (bonus armor and MR, penetration as a percentage such
        as 30.0).  ``(0.0, 0.0)`` when Terminus is not in the build.
    """
    if "Terminus" not in _item_names(items):
        return 0.0, 0.0
    max_stacks = required_effect_value("Terminus", "dark_max_stacks")
    low_resist = required_effect_value("Terminus", "light_resist_min")
    high_resist = required_effect_value("Terminus", "light_resist_max")
    clamped_level = max(1, min(level, 18))
    resist_per_stack = (
        low_resist + (high_resist - low_resist) * (clamped_level - 1) / 17.0
    )
    bonus_resist = resist_per_stack * max_stacks
    pen_percent = (
        required_effect_value("Terminus", "dark_pen_per_stack") * max_stacks * 100.0
    )
    return bonus_resist, pen_percent


def _basic_ability_haste(items: list[dict[str, Any]]) -> float:
    """Backward-compatible private alias for :func:`basic_ability_haste`."""
    return basic_ability_haste(items)


def basic_ability_haste(items: list[dict[str, Any]]) -> float:
    """Return parser-backed Spear of Shojin basic ability haste.

    Args:
        items: List of item data dicts.

    Returns:
        Total basic ability haste.
    """
    if "Spear of Shojin" not in _item_names(items):
        return 0.0
    return required_effect_value("Spear of Shojin", "basic_ability_haste")


@dataclass(frozen=True)
class StatBonuses:
    """Every stat-granting item passive for one build, compiled.

    The stat layer's counterpart to ``BuildDamageEffects``: ``stats.py``
    reads these typed fields instead of importing one accessor per item.
    Application contract (owned by ``stats.calculate_total_stats``):
    ``bonus_ap`` adds to AP *before* ``ap_multiplier`` multiplies;
    ``bonus_resists`` adds to both armor and MR; ``bonus_pen_percent``
    adds to both armor and magic percent pen (Terminus max-stack display
    assumption — the fight engine ramps the real per-auto average).
    """

    bonus_ap: float  # Awe mana→AP, Dawncore, Staff of Flowing Water
    bonus_health: float  # Fimbulwinter/Winter's Approach Awe
    ap_multiplier: float  # Rabadon's / Blackfire additive %AP (1.0 = none)
    bonus_ad: float  # Muramana, Overlord's Bloodmail, Sterak's Gage
    attack_speed_percent: float  # Bandlepipes, Hexplate, Yun Tal
    bonus_resists: float  # Terminus light stacks (armor AND MR)
    bonus_pen_percent: float  # Terminus dark stacks (armor AND magic pen)
    basic_ability_haste: float  # Spear of Shojin (Q/W/E only)
    ability_haste: float  # Endless Hunger Famine's bonus-AD conversion
    ultimate_haste: float  # Scorn/Hexcharged/Night Vigil/Cryocombustion
    bonus_omnivamp: float  # Endless Hunger Feast's explicit takedown window
    bonus_heal_shield_power: float  # Harmony's bonus-mana conversion
    bonus_move_speed_percent: float  # Mejai's 10+ Glory
    item_bonus_health_multiplier: float  # Warmog's Vitality (1.0 = none)
    # Permanent item-owned subsets used by Kai'Sa's Living Weapon. These
    # exclude temporary combat effects (Blackfire, Rapids, AS windows).
    permanent_bonus_ap: float
    permanent_ap_multiplier: float
    permanent_bonus_ad: float


def resolve_stat_effects(
    items: list[dict[str, Any]],
    *,
    bonus_mana: float,
    max_mana: float,
    bonus_health: float,
    base_attack_damage: float,
    bonus_mana_regen_percent: float,
    is_melee: bool,
    level: int,
    item_options: Mapping[str, Mapping[str, int]] | None = None,
    bonus_attack_damage: float = 0.0,
    total_move_speed: float = 0.0,
    adaptive_type: str = "",
) -> StatBonuses:
    """Compile the stat-granting passives of *items* into one bundle.

    Callers supply the pre-computed stats each conversion reads (Awe
    reads bonus mana, Muramana total mana, Bloodmail bonus health,
    Sterak's base AD, Dawncore bonus base mana regen). A stat-converting
    item added here is the ONLY edit item-side; ``stats.py`` never grows
    a new import or call site.
    """
    terminus_resists, terminus_pen = terminus_max_stack_bonuses(items, level)
    input_bonus_ap, input_move_speed, _, _ = _input_option_stat_bonuses(
        items, item_options
    )
    health_multiplier = item_bonus_health_multiplier(items)
    mana_bonus_ap = mana_to_ap_bonus(items, bonus_mana)
    mana_bonus_health = mana_to_health_bonus(items, bonus_mana)
    effective_bonus_health = (bonus_health + mana_bonus_health) * health_multiplier
    dawncore_ap = dawncore_bonus_ap(items, bonus_mana_regen_percent)
    permanent_bonus_ap = mana_bonus_ap + dawncore_ap + input_bonus_ap
    if "Riftmaker" in _item_names(items):
        permanent_bonus_ap += riftmaker_bonus_ap(
            bonus_health=effective_bonus_health, item_name="Riftmaker"
        )
    permanent_bonus_ad = (
        muramana_bonus_ad(items, max_mana)
        + bloodmail_bonus_ad(items, effective_bonus_health)
        + steraks_bonus_ad(items, base_attack_damage)
    )
    hubris_ad = hubris_input_bonus_ad(items, item_options)
    feast_omnivamp = endless_hunger_input_omnivamp(items, item_options)
    famine_ability_haste = endless_hunger_ability_haste(
        items,
        bonus_attack_damage=bonus_attack_damage + permanent_bonus_ad + hubris_ad,
        is_melee=is_melee,
    )
    ultimate_haste = sum(
        float(ITEM_EFFECTS[name].get("ultimate_haste", 0.0))
        for name in _item_names(items)
        if name in ITEM_EFFECTS
    )
    harmony_ratio = (
        required_effect_value(
            "Whispering Circlet", "bonus_mana_to_heal_shield_power_ratio"
        )
        if "Whispering Circlet" in _item_names(items)
        else 0.0
    )
    harmony_power = (
        harmony_ratio * bonus_mana
        if "Whispering Circlet" in _item_names(items)
        else 0.0
    )
    adaptive_force = swiftmarch_adaptive_force(items, total_move_speed=total_move_speed)
    normalized_adaptive_type = str(adaptive_type or "").upper()
    adaptive_ap = (
        adaptive_force
        if normalized_adaptive_type in {"AP", "ABILITY_POWER", "MAGIC_DAMAGE"}
        else 0.0
    )
    adaptive_ad = (
        adaptive_force
        if normalized_adaptive_type in {"AD", "ATTACK_DAMAGE", "PHYSICAL_DAMAGE"}
        else 0.0
    )
    return StatBonuses(
        bonus_ap=permanent_bonus_ap + flowing_water_bonus_ap(items) + adaptive_ap,
        bonus_health=mana_bonus_health,
        ap_multiplier=ap_multiplier(items),
        bonus_ad=permanent_bonus_ad + hubris_ad + adaptive_ad,
        attack_speed_percent=passive_attack_speed_bonus(items, is_melee),
        bonus_resists=terminus_resists,
        bonus_pen_percent=terminus_pen,
        basic_ability_haste=basic_ability_haste(items),
        ability_haste=famine_ability_haste,
        ultimate_haste=ultimate_haste,
        bonus_omnivamp=feast_omnivamp,
        bonus_heal_shield_power=harmony_power,
        bonus_move_speed_percent=input_move_speed,
        item_bonus_health_multiplier=health_multiplier,
        permanent_bonus_ap=permanent_bonus_ap,
        permanent_ap_multiplier=permanent_ap_multiplier(items),
        permanent_bonus_ad=permanent_bonus_ad,
    )
