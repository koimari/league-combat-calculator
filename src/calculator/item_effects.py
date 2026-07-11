"""Registry and calculation functions for legendary item damage effects.

Each item with a damage-relevant passive/active is registered in ITEM_EFFECTS.
Functions compute bonus damage based on fight context (stats, target, duration).

**Data sourcing:** Values are loaded from the cached item JSON data via
``passive_parser`` whenever the data is available.  The ``_DEFAULT_ITEM_EFFECTS``
dict below provides fallback values for fields that cannot be parsed from
the wiki markup (e.g. cooldowns not stored in JSON, structural flags like
``phantom_hit``).  When JSON data is refreshed (new patch), calling
``refresh_item_effects()`` re-parses and updates ``ITEM_EFFECTS`` in place.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default / fallback item effect values
# ---------------------------------------------------------------------------
# These serve as the base for ITEM_EFFECTS.  Parsed values from JSON
# override these where available; fields not parseable from the wiki
# markup are kept from the defaults.

_DEFAULT_ITEM_EFFECTS: dict[str, dict[str, Any]] = {
    # ── On-Hit (per auto attack) ──────────────────────────────────────────
    "Nashor's Tooth": {
        "type": "on_hit",
        "damage_type": "magic",
        "base": 15.0,
        "ap_ratio": 0.15,
    },
    "Blade of the Ruined King": {
        "type": "on_hit",
        "damage_type": "physical",
        "current_hp_ratio_melee": 0.09,
        "current_hp_ratio_ranged": 0.06,
        "min_damage": 5.0,  # Flat minimum when target HP is modeled at 0
    },
    "Wit's End": {
        "type": "on_hit",
        "damage_type": "magic",
        "base": 45.0,
    },
    "Terminus": {
        "type": "on_hit",
        "damage_type": "magic",
        "base": 30.0,
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
        "damage_type": "physical",
        "max_hp_ratio_melee": 0.01,
        "max_hp_ratio_ranged": 0.005,
        # Titanic Crescent active: empowered Cleave on next auto (10s CD)
        "active_max_hp_ratio_melee": 0.04,
        "active_max_hp_ratio_ranged": 0.02,
        "active_cooldown": 10.0,
    },
    "Guinsoo's Rageblade": {
        "type": "on_hit",
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
    },
    "Muramana": {
        "type": "on_hit",
        "damage_type": "physical",
        "max_mana_ratio_on_hit": 0.012,
        "max_mana_ratio_ability_melee": 0.04,
        "max_mana_ratio_ability_ranged": 0.03,
        # Awe passive: 2% max mana as bonus AD (stat conversion)
        "max_mana_to_ad_ratio": 0.02,
    },
    # ── Spellblade (after ability, next auto, mutually exclusive) ─────────
    "Trinity Force": {
        "type": "spellblade",
        "damage_type": "physical",
        "base_ad_ratio": 2.0,
        "cooldown": 1.5,
        "weave_delay": 1.5,  # CD starts after empowered attack
    },
    "Lich Bane": {
        "type": "spellblade",
        "damage_type": "magic",
        "base_ad_ratio": 0.75,
        "ap_ratio": 0.40,
        "cooldown": 1.5,
        "weave_delay": 1.5,  # CD starts after empowered attack
    },
    "Essence Reaver": {
        "type": "spellblade",
        "damage_type": "physical",
        "base_ad_ratio": 1.25,
        # Bonus damage scales 0-50 based on crit chance
        "crit_bonus_max": 50.0,
        "cooldown": 1.5,
        "weave_delay": 1.5,  # CD starts after empowered attack
    },
    "Iceborn Gauntlet": {
        "type": "spellblade",
        "damage_type": "physical",
        "base_ad_ratio": 1.50,
        "cooldown": 1.5,
        "weave_delay": 1.5,  # CD starts after empowered attack
    },
    "Bloodsong": {
        "type": "spellblade",
        "damage_type": "physical",
        "base_ad_ratio": 1.0,
        "cooldown": 1.5,
        "weave_delay": 1.5,  # CD starts after empowered attack
        "expose_weakness_melee": 0.08,
        "expose_weakness_ranged": 0.05,
    },
    "Dusk and Dawn": {
        "type": "spellblade",
        "damage_type": "magic",
        "base_ad_ratio": 0.75,
        "ap_ratio": 0.10,
        "cooldown": 1.5,
        "weave_delay": 1.5,  # CD starts after empowered attack
        "double_on_hit": True,  # Applies all on-hit effects again
    },
    # ── Burn / DoT ────────────────────────────────────────────────────────
    "Liandry's Torment": {
        "type": "burn",
        "damage_type": "magic",
        # 1% max HP every 0.5s for 3s = 6% max HP total
        "max_hp_ratio_total": 0.06,
        "duration": 3.0,
        # Suffering: 2% increased damage per second, up to 6%
        "damage_amp_per_second": 0.02,
        "damage_amp_max": 0.06,
    },
    "Blackfire Torch": {
        "type": "burn",
        "damage_type": "magic",
        # 10 + 1% AP per 0.5s for 3s = 60 + 6% AP total
        "base_total": 60.0,
        "ap_ratio_total": 0.06,
        "duration": 3.0,
        # 4% bonus AP per burning champion
        "ap_amp_per_target": 0.04,
    },
    "Sunfire Aegis": {
        "type": "immolate",
        "damage_type": "magic",
        # 20 + 1% bonus HP per second
        "base_per_second": 20.0,
        "bonus_hp_ratio_per_second": 0.01,
    },
    "Hollow Radiance": {
        "type": "immolate",
        "damage_type": "magic",
        # 15 + 1% bonus HP per second
        "base_per_second": 15.0,
        "bonus_hp_ratio_per_second": 0.01,
    },
    # ── Proc Damage (cooldown-gated) ──────────────────────────────────────
    "Luden's Echo": {
        "type": "proc",
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
        "damage_type": "magic",
        # Electrospark: ONE empowered attack deals 60 bonus magic damage,
        # chain-lightning to up to 4-8 targets by level (single-target: 1 proc)
        "base": 60.0,
        "empowered_auto_count": 1,
        "chain_targets_min": 4,
        "chain_targets_max": 8,
    },
    "Stormsurge": {
        "type": "proc",
        "damage_type": "magic",
        # 125 + 10% AP, 30s CD (triggers at 25% HP damage in 2.5s)
        "base": 125.0,
        "ap_ratio": 0.10,
        "cooldown": 30.0,
        "is_ability_damage": True,  # Amplified by Actualizer
    },
    "Zaz'Zak's Realmspike": {
        "type": "proc",
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
        "damage_type": "magic",
        # 100 + 10% AP magic damage
        "base": 100.0,
        "ap_ratio": 0.10,
        "cooldown": 40.0,
    },
    "Profane Hydra": {
        "type": "active",
        "damage_type": "physical",
        # Active: 80% total AD
        "total_ad_ratio": 0.80,
        "cooldown": 10.0,
    },
    "Hextech Gunblade": {
        "type": "active",
        "damage_type": "magic",
        # Lightning Bolt: 175-262 (scales linearly levels 1-20) + 30% AP
        "base_min": 175.0,
        "base_max": 262.0,
        "ap_ratio": 0.30,
        "cooldown": 60.0,
    },
    "Ravenous Hydra": {
        "type": "active",
        "damage_type": "physical",
        # Ravenous Crescent: 80% total AD
        "total_ad_ratio": 0.80,
        "cooldown": 10.0,
    },
    "Stridebreaker": {
        "type": "active",
        "damage_type": "physical",
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
        # 1% per 50 units, max 10% at 500 units
        "max_amp": 0.10,
        "max_distance": 500.0,
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
    },
    # ── Ultimate-Triggered Attack Speed Buffs ──────────────────────────────
    "Experimental Hexplate": {
        "type": "ult_attack_speed_buff",
        # Overdrive: 50% bonus AS + 20% MS for 8s on R cast (30s CD)
        "bonus_attack_speed_percent": 50.0,
        "duration": 8.0,
        "cooldown": 30.0,
    },
    "Fiendhunter Bolts": {
        "type": "ult_empowered_autos",
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
        "damage_type": "physical",
        # Ever Rising Moon: 2 stacks within 2s deals bonus physical damage
        # Melee 6% / Ranged 4% of target's maximum health
        "target_max_hp_ratio_melee": 0.06,
        "target_max_hp_ratio_ranged": 0.04,
        "cooldown": 6.0,
    },
    # ── Lethality Proc (ability damage trigger) ──────────────────────────
    "Bastionbreaker": {
        "type": "shaped_charge",
        # Shaped Charge: next ability damage deals bonus true damage
        # Melee: 30 + 1.5 per lethality, Ranged: 15 + 0.75 per lethality
        "base_melee": 30.0,
        "base_ranged": 15.0,
        "lethality_ratio_melee": 1.5,
        "lethality_ratio_ranged": 0.75,
        "cooldown": 45.0,
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
        "damage_type": "magic",
        # Sharpshooter: 40 bonus magic damage on first energized auto
        "base": 40.0,
    },
    # ── Other single-proc items ───────────────────────────────────────────
    "Dead Man's Plate": {
        "type": "on_hit_once",
        "damage_type": "physical",
        # At max momentum: 40 + 100% base AD
        "base": 40.0,
        "base_ad_ratio": 1.0,
    },
    "Heartsteel": {
        "type": "on_hit_once",
        "damage_type": "physical",
        # Colossal Consumption: 70 + 6% max HP bonus physical damage
        # 30s cooldown — assumed to proc once per fight
        "base": 70.0,
        "max_hp_ratio": 0.06,
        "cooldown": 30.0,
    },
    "Hullbreaker": {
        "type": "on_hit_stacking",
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
    },
    # ── Stat Conversion (passives that modify champion stats) ──────────────
    "Rabadon's Deathcap": {
        "type": "stat_conversion",
        "ap_percent_increase": 0.30,
    },
    "Archangel's Staff": {
        "type": "stat_conversion",
        "bonus_mana_to_ap_ratio": 0.01,
    },
    "Seraph's Embrace": {
        "type": "stat_conversion",
        "bonus_mana_to_ap_ratio": 0.02,
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
    "Overlord's Bloodmail": {
        "type": "stat_conversion",
        "bonus_health_to_ad_ratio": 0.025,
    },
    "Staff of Flowing Water": {
        "type": "stat_conversion",
        "rapids_bonus_ap": 45.0,
    },
    "Sterak's Gage": {
        "type": "stat_conversion",
        "base_ad_to_bonus_ad_ratio": 0.45,
    },
    "Stormrazor": {
        "type": "on_hit_once",
        "damage_type": "magic",
        "base": 100.0,
    },
    # ── Sundered Sky (first-auto crit modifier) ─────────────────────────────
    "Sundered Sky": {
        "type": "first_auto_crit",
        # Lightshield Strike: first auto crits at 80% of normal crit damage
        # Overrides natural crit even if you would have crit normally
        "reduced_crit_ratio": 0.80,
        "cooldown": 10.0,
    },
    # ── Voltaic Cyclosword (energized first-auto) ───────────────────────────
    "Voltaic Cyclosword": {
        "type": "on_hit_once",
        "damage_type": "physical",
        # Firmament: % of target's CURRENT health (melee 9% / ranged 7%),
        # capped at 200
        "current_hp_ratio_melee": 0.09,
        "current_hp_ratio_ranged": 0.07,
        "damage_cap": 200.0,
    },
    # ── Unending Despair (periodic AoE damage) ──────────────────────────────
    "Unending Despair": {
        "type": "periodic_aoe",
        "damage_type": "magic",
        # Anguish: every 4 seconds, deal 3% bonus health as magic damage
        "interval": 4.0,
        "bonus_hp_ratio": 0.03,
    },
    # ── Yun Tal Wildarrows (conditional AS on attack) ───────────────────────
    "Yun Tal Wildarrows": {
        "type": "conditional_attack_speed",
        # Flurry: 30% bonus AS for 6 seconds after attacking a champion
        "bonus_attack_speed_percent": 30.0,
        "duration": 6.0,
        "cooldown": 30.0,
    },
}


# ---------------------------------------------------------------------------
# Dynamic loading from JSON data
# ---------------------------------------------------------------------------


def _build_item_effects(
    defaults: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build ITEM_EFFECTS by merging parsed JSON values over defaults.

    For each item the default dict is deep-copied, then any values
    successfully parsed from the cached ``items.json`` are applied on
    top.  Fields that the parser cannot extract (e.g. cooldowns absent
    from JSON, structural flags like ``phantom_hit``) are preserved
    from the defaults.

    Returns:
        Merged dict suitable for use as ``ITEM_EFFECTS``.
    """
    import copy

    result = copy.deepcopy(defaults)

    try:
        from .data_fetcher import DEFAULT_DATA_DIR, fetch_item_data

        items_data = fetch_item_data(data_directory=DEFAULT_DATA_DIR)
    except Exception as exc:
        logger.debug("Could not load item JSON for parsing: %s", exc)
        return result

    try:
        from .passive_parser import parse_all_item_effects

        parsed = parse_all_item_effects(items_data)
    except Exception as exc:
        logger.warning("Item passive parsing failed: %s", exc)
        return result

    for item_name, parsed_values in parsed.items():
        if item_name in result:
            # Override default values with parsed ones
            result[item_name].update(parsed_values)
        else:
            # New item not in defaults — add it
            result[item_name] = parsed_values

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
    ITEM_EFFECTS.update(_build_item_effects(_DEFAULT_ITEM_EFFECTS))


# Build the live registry at import time.
ITEM_EFFECTS: dict[str, dict[str, Any]] = _build_item_effects(
    _DEFAULT_ITEM_EFFECTS,
)


def _required_effect_value(item_name: str, key: str) -> Any:
    """Read a required key from an item's effect entry, failing loudly.

    ``ITEM_EFFECTS`` merges parsed wiki values over ``_DEFAULT_ITEM_EFFECTS``,
    so every registered item is guaranteed to carry its default keys.  A
    missing key therefore means a parser/defaults bug — raise a KeyError
    naming the item and key instead of silently substituting a stale
    literal (the failure mode behind the Statikk Shiv bug).
    """
    effect = ITEM_EFFECTS.get(item_name, {})
    if key not in effect:
        raise KeyError(
            f"ITEM_EFFECTS[{item_name!r}] is missing {key!r} — "
            "parser/defaults bug; check _DEFAULT_ITEM_EFFECTS and "
            "passive_parser"
        )
    return effect[key]


def _item_names(items: list[dict[str, Any]]) -> set[str]:
    """Return the set of item names in a build."""
    return {item.get("name", "") for item in items}


# ---------------------------------------------------------------------------
# Stat-modifying passives (consumed by stats.py)
# ---------------------------------------------------------------------------
# These accessors own both the ITEM_EFFECTS lookup and the numeric
# semantics of each stat-granting passive; stats.py only orchestrates
# when to apply them.  Each passive applies once per build regardless of
# duplicate copies (legendary items are unique).


def get_ap_multiplier(items: list[dict[str, Any]]) -> float:
    """Additive AP multiplier from item passives.

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
        bonus += _required_effect_value("Rabadon's Deathcap", "ap_percent_increase")
    if "Blackfire Torch" in names:
        bonus += _required_effect_value("Blackfire Torch", "ap_amp_per_target")
    return 1.0 + bonus


def get_mana_to_ap_bonus(items: list[dict[str, Any]], bonus_mana: float) -> float:
    """Awe passives (Archangel's Staff, Seraph's Embrace): bonus mana → AP.

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
            total += _required_effect_value(name, "bonus_mana_to_ap_ratio") * bonus_mana
    return total


def get_dawncore_bonus_ap(
    items: list[dict[str, Any]],
    bonus_mana_regen_percent: float,
) -> float:
    """Dawncore First Light: AP per 100% additional base mana regen.

    Args:
        items: List of item data dicts.
        bonus_mana_regen_percent: Total bonus base mana regen (percent).

    Returns:
        Flat bonus AP from mana regen conversion.
    """
    if "Dawncore" not in _item_names(items):
        return 0.0
    ap_per_unit = _required_effect_value("Dawncore", "ap_per_mana_regen_unit")
    threshold = _required_effect_value("Dawncore", "mana_regen_threshold_percent")
    return (bonus_mana_regen_percent / threshold) * ap_per_unit


def get_flowing_water_bonus_ap(items: list[dict[str, Any]]) -> float:
    """Staff of Flowing Water Rapids: flat bonus AP (assumed always active).

    Args:
        items: List of item data dicts.

    Returns:
        Flat bonus AP from Rapids.
    """
    if "Staff of Flowing Water" not in _item_names(items):
        return 0.0
    return _required_effect_value("Staff of Flowing Water", "rapids_bonus_ap")


def get_passive_attack_speed_bonus(
    items: list[dict[str, Any]],
    is_melee: bool,
) -> float:
    """Flat bonus attack speed (percent) from assumed-active item passives.

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
    if "Bandlepipes" in names:
        key = "bonus_attack_speed_melee" if is_melee else "bonus_attack_speed_ranged"
        bonus += _required_effect_value("Bandlepipes", key)
    for name in ("Experimental Hexplate", "Yun Tal Wildarrows"):
        if name in names:
            bonus += _required_effect_value(name, "bonus_attack_speed_percent")
    return bonus


def get_muramana_bonus_ad(items: list[dict[str, Any]], max_mana: float) -> float:
    """Muramana Awe passive: % of maximum mana as bonus AD.

    Args:
        items: List of item data dicts.
        max_mana: Champion's total maximum mana (base + items).

    Returns:
        Flat bonus AD from Awe.
    """
    if "Muramana" not in _item_names(items):
        return 0.0
    return _required_effect_value("Muramana", "max_mana_to_ad_ratio") * max_mana


def get_bloodmail_bonus_ad(
    items: list[dict[str, Any]],
    bonus_health: float,
) -> float:
    """Overlord's Bloodmail Tyranny passive: % of bonus health as bonus AD.

    Args:
        items: List of item data dicts.
        bonus_health: Total bonus health from items.

    Returns:
        Flat bonus AD from Tyranny.
    """
    if "Overlord's Bloodmail" not in _item_names(items):
        return 0.0
    ratio = _required_effect_value("Overlord's Bloodmail", "bonus_health_to_ad_ratio")
    return ratio * bonus_health


def get_steraks_bonus_ad(items: list[dict[str, Any]], base_ad: float) -> float:
    """Sterak's Gage The Claws that Catch: % of base AD as bonus AD.

    Args:
        items: List of item data dicts.
        base_ad: Champion's base attack damage at the current level.

    Returns:
        Flat bonus AD from the passive.
    """
    if "Sterak's Gage" not in _item_names(items):
        return 0.0
    return (
        _required_effect_value("Sterak's Gage", "base_ad_to_bonus_ad_ratio") * base_ad
    )


def get_terminus_max_stack_bonuses(
    items: list[dict[str, Any]],
    level: int,
) -> tuple[float, float]:
    """Terminus Juxtaposition at max stacks: (bonus armor/MR, pen percent).

    Light hits grant level-scaled bonus armor + MR per stack; dark hits
    grant % armor and magic penetration per stack.  Both are assumed at
    max stacks for the stat display; the fight engine later replaces the
    max-stack pen with a ramping per-auto average
    (``get_terminus_pen_stacks``).

    Args:
        items: List of item data dicts.
        level: Champion level (1-18).

    Returns:
        Tuple of (bonus armor and MR, penetration as a percentage such
        as 30.0).  ``(0.0, 0.0)`` when Terminus is not in the build.
    """
    if "Terminus" not in _item_names(items):
        return 0.0, 0.0
    max_stacks = _required_effect_value("Terminus", "dark_max_stacks")
    bonus_resist = get_terminus_light_resist_per_stack(level) * max_stacks
    pen_percent = (
        _required_effect_value("Terminus", "dark_pen_per_stack") * max_stacks * 100.0
    )
    return bonus_resist, pen_percent


def get_basic_ability_haste(items: list[dict[str, Any]]) -> float:
    """Spear of Shojin Dragonforce: basic ability haste (Q, W, E only).

    Args:
        items: List of item data dicts.

    Returns:
        Total basic ability haste.
    """
    if "Spear of Shojin" not in _item_names(items):
        return 0.0
    return _required_effect_value("Spear of Shojin", "basic_ability_haste")


# ---------------------------------------------------------------------------
# Calculation helpers
# ---------------------------------------------------------------------------


def _lerp_by_level(
    min_val: float,
    max_val: float,
    level: int,
    max_level: int = 18,
) -> float:
    """Linearly interpolate a value between level 1 and max_level."""
    clamped = max(1, min(level, max_level))
    return min_val + (max_val - min_val) * (clamped - 1) / (max_level - 1)


def get_on_hit_damage(
    item_name: str,
    champion_stats: dict[str, float],
    target_health: float,
    is_melee: bool,
) -> float:
    """Calculate bonus on-hit damage for a single auto attack.

    Args:
        item_name: Name of the item.
        champion_stats: Champion's calculated stats.
        target_health: Target's current health.
        is_melee: Whether the champion is melee.

    Returns:
        Raw bonus damage per auto attack (before resistances).
    """
    effect = ITEM_EFFECTS.get(item_name)
    if not effect or effect["type"] != "on_hit":
        return 0.0

    if item_name == "Nashor's Tooth":
        return effect["base"] + effect["ap_ratio"] * champion_stats.get(
            "ability_power", 0
        )

    if item_name == "Blade of the Ruined King":
        ratio = (
            effect["current_hp_ratio_melee"]
            if is_melee
            else effect["current_hp_ratio_ranged"]
        )
        return ratio * target_health

    if item_name == "Wit's End":
        return effect["base"]

    if item_name == "Terminus":
        return effect["base"]

    if item_name == "Titanic Hydra":
        ratio = (
            effect["max_hp_ratio_melee"] if is_melee else effect["max_hp_ratio_ranged"]
        )
        return ratio * champion_stats.get("health", 0)

    if item_name == "Guinsoo's Rageblade":
        return effect["base"]

    if item_name == "Muramana":
        max_mana = champion_stats.get("max_mana", 0)
        return effect["max_mana_ratio_on_hit"] * max_mana

    return 0.0


def get_spellblade_damage(
    item_name: str,
    champion_stats: dict[str, float],
) -> float:
    """Calculate spellblade proc damage.

    Args:
        item_name: Name of the spellblade item.
        champion_stats: Champion's calculated stats.

    Returns:
        Raw spellblade damage per proc (before resistances).
    """
    effect = ITEM_EFFECTS.get(item_name)
    if not effect or effect["type"] != "spellblade":
        return 0.0

    base_ad = champion_stats.get("base_attack_damage", 0)

    if item_name == "Trinity Force":
        return effect["base_ad_ratio"] * base_ad

    if item_name == "Lich Bane":
        ap = champion_stats.get("ability_power", 0)
        return effect["base_ad_ratio"] * base_ad + effect["ap_ratio"] * ap

    if item_name == "Essence Reaver":
        crit = champion_stats.get("critical_strike_chance", 0)
        crit_bonus = effect["crit_bonus_max"] * min(crit / 100.0, 1.0)
        return effect["base_ad_ratio"] * base_ad + crit_bonus

    if item_name == "Iceborn Gauntlet":
        return effect["base_ad_ratio"] * base_ad

    if item_name == "Bloodsong":
        return effect["base_ad_ratio"] * base_ad

    if item_name == "Dusk and Dawn":
        ap = champion_stats.get("ability_power", 0)
        return effect["base_ad_ratio"] * base_ad + effect["ap_ratio"] * ap

    return 0.0


def get_spellblade_damage_type(item_name: str) -> str:
    """Return the damage type of a spellblade proc."""
    effect = ITEM_EFFECTS.get(item_name)
    if effect:
        return effect.get("damage_type", "physical")
    return "physical"


def calculate_burn_damage(
    item_name: str,
    champion_stats: dict[str, float],
    target_health: float,
) -> float:
    """Calculate total burn/DoT damage from an item.

    Args:
        item_name: Name of the burn item.
        champion_stats: Champion's calculated stats.
        target_health: Target's maximum health.

    Returns:
        Total raw burn damage (before resistances).
    """
    effect = ITEM_EFFECTS.get(item_name)
    if not effect:
        return 0.0

    if item_name == "Liandry's Torment":
        return effect["max_hp_ratio_total"] * target_health

    if item_name == "Blackfire Torch":
        ap = champion_stats.get("ability_power", 0)
        return effect["base_total"] + effect["ap_ratio_total"] * ap

    return 0.0


def calculate_immolate_damage(
    item_name: str,
    champion_stats: dict[str, float],
    fight_duration: float,
) -> float:
    """Calculate total immolate (aura) damage over a fight.

    Args:
        item_name: Name of the immolate item.
        champion_stats: Champion's calculated stats.
        fight_duration: Fight duration in seconds.

    Returns:
        Total raw immolate damage (before resistances).
    """
    effect = ITEM_EFFECTS.get(item_name)
    if not effect or effect["type"] != "immolate":
        return 0.0

    bonus_hp = champion_stats.get("bonus_health", 0)
    dps = effect["base_per_second"] + effect["bonus_hp_ratio_per_second"] * bonus_hp
    return dps * fight_duration


def calculate_proc_damage(
    item_name: str,
    champion_stats: dict[str, float],
    target_health: float,
    fight_duration: float,
    level: int,
) -> float:
    """Calculate total proc damage over a fight duration.

    Args:
        item_name: Name of the proc item.
        champion_stats: Champion's calculated stats.
        target_health: Target's maximum health.
        fight_duration: Fight duration in seconds.
        level: Champion level.

    Returns:
        Total raw proc damage (before resistances).
    """
    effect = ITEM_EFFECTS.get(item_name)
    if not effect or effect["type"] != "proc":
        return 0.0

    ap = champion_stats.get("ability_power", 0)

    if item_name == "Luden's Echo":
        per_charge = effect["base_per_charge"] + effect["ap_ratio_per_charge"] * ap
        single_proc = per_charge * effect["single_target_multiplier"]
        num_procs = 1 + int(fight_duration / effect["cooldown"])
        return single_proc * num_procs

    if item_name == "Stormsurge":
        # Usually only procs once per fight (30s CD)
        return effect["base"] + effect["ap_ratio"] * ap

    if item_name == "Zaz'Zak's Realmspike":
        per_proc = (
            effect["base"]
            + effect["ap_ratio"] * ap
            + effect["target_max_hp_ratio"] * target_health
        )
        num_procs = 1 + int(fight_duration / effect["cooldown"])
        return per_proc * num_procs

    return 0.0


def _level_scaled_base(effect: dict[str, Any], level: int) -> float:
    """Interpolate base damage that scales linearly from min to max by level."""
    base_min = effect.get("base_min", 0.0)
    base_max = effect.get("base_max", base_min)
    max_level = effect.get("max_level", 20)
    clamped = max(1, min(level, max_level))
    return base_min + (base_max - base_min) * (clamped - 1) / (max_level - 1)


def calculate_active_damage(
    item_name: str,
    champion_stats: dict[str, float],
    target_health: float = 0.0,
) -> float:
    """Calculate damage from an item active (used once per fight).

    Args:
        item_name: Name of the active item.
        champion_stats: Champion's calculated stats.
        target_health: Target's maximum health (for %HP actives).

    Returns:
        Total raw active damage (before resistances).
    """
    effect = ITEM_EFFECTS.get(item_name)
    if not effect or effect["type"] != "active":
        return 0.0

    ap = champion_stats.get("ability_power", 0.0)
    total_ad = champion_stats.get("attack_damage", 0.0)
    level = int(champion_stats.get("level", 1))

    if item_name == "Hextech Rocketbelt":
        return effect["base"] + effect["ap_ratio"] * ap

    if item_name in ("Profane Hydra", "Ravenous Hydra", "Stridebreaker"):
        return effect["total_ad_ratio"] * total_ad

    if item_name == "Hextech Gunblade":
        base = _level_scaled_base(effect, level)
        return base + effect["ap_ratio"] * ap

    return 0.0


def get_damage_amplifier(
    items: list[dict[str, Any]],
    fight_duration: float,
    target_bonus_health: float = 0.0,
) -> float:
    """Calculate total damage amplification multiplier from items.

    Args:
        items: List of item data dicts.
        fight_duration: Fight duration in seconds.
        target_bonus_health: Target's bonus health (for Lord Dominik's).

    Returns:
        Total multiplier (e.g., 1.06 for 6% amp).
    """
    _, total = get_damage_amplifier_breakdown(
        items,
        fight_duration,
        target_bonus_health,
    )
    return total


def get_damage_amplifier_breakdown(
    items: list[dict[str, Any]],
    fight_duration: float,
    target_bonus_health: float = 0.0,
) -> tuple[list[tuple[str, float]], float]:
    """Calculate per-item damage amplification with source names.

    Returns:
        Tuple of (list of (item_name, amp_fraction) pairs, total multiplier).
    """
    sources: list[tuple[str, float]] = []

    for item in items:
        name = item.get("name", "")
        effect = ITEM_EFFECTS.get(name)
        if not effect:
            continue

        if name == "Liandry's Torment":
            max_time = effect["damage_amp_max"] / effect["damage_amp_per_second"]
            stacks = min(fight_duration, max_time)
            avg_amp = effect["damage_amp_per_second"] * stacks / 2.0
            sources.append((name, avg_amp))

        elif name == "Riftmaker":
            stacks = min(fight_duration, effect["amp_max"] / effect["amp_per_second"])
            avg_amp = effect["amp_per_second"] * stacks / 2.0
            sources.append((name, avg_amp))

        elif name == "Lord Dominik's Regards":
            ratio = min(target_bonus_health / effect["bonus_hp_cap"], 1.0)
            sources.append((name, effect["max_amp"] * ratio))

        elif name == "Spear of Shojin":
            stacks = min(effect["max_stacks"], max(1, int(fight_duration / 2)))
            sources.append((name, effect["amp_per_stack"] * stacks))

        elif effect.get("type") == "magic_damage_amp":
            pass

    total = 1.0 + sum(amp for _, amp in sources)
    return sources, total


def get_magic_damage_amplifier(items: list[dict[str, Any]]) -> float:
    """Get magic-only damage amplification (e.g., Abyssal Mask).

    Args:
        items: List of item data dicts.

    Returns:
        Multiplier for magic damage only (e.g., 1.12 for 12% amp).
    """
    amp = 0.0
    for item in items:
        name = item.get("name", "")
        effect = ITEM_EFFECTS.get(name)
        if effect and effect.get("type") == "magic_damage_amp":
            amp += effect["magic_amp"]
    return 1.0 + amp


def get_ability_damage_amplifier(
    items: list[dict[str, Any]],
    champion_stats: dict[str, float],
    include_actives: bool = True,
) -> float:
    """Calculate ability-specific damage amplification (e.g., Actualizer).

    Args:
        items: List of item data dicts.
        champion_stats: Champion's calculated stats.
        include_actives: Whether active item effects are enabled.

    Returns:
        Multiplier for ability damage (e.g., 1.165 for 16.5% amp).
    """
    amp = 0.0
    for item in items:
        name = item.get("name", "")
        effect = ITEM_EFFECTS.get(name)
        if not effect or effect.get("type") != "ability_damage_amp":
            continue
        if not include_actives:
            continue
        bonus_mana = champion_stats.get("bonus_mana", 0.0)
        base_amp = effect["base_amp"]
        per_100 = effect["amp_per_100_bonus_mana"]
        amp += base_amp + per_100 * (bonus_mana / 100.0)
    return 1.0 + amp


def get_hypershot_amplifier(items: list[dict[str, Any]]) -> float:
    """Get Horizon Focus Hypershot damage amplification.

    Always assumes max range (amp is active). The first ability triggers
    the mark and does NOT benefit from the amp — the caller is responsible
    for excluding it.

    Args:
        items: List of item data dicts.

    Returns:
        Multiplier for all damage after the trigger (e.g. 1.10 for 10%).
    """
    amp = 0.0
    for item in items:
        name = item.get("name", "")
        effect = ITEM_EFFECTS.get(name)
        if effect and effect.get("type") == "hypershot_amp":
            amp += effect["amp"]
    return 1.0 + amp


def get_basic_damage_amplifier(
    items: list[dict[str, Any]],
) -> float:
    """Calculate basic (auto attack) damage amplification from items.

    Hexoptics C44 Magnification grants up to ``max_amp`` increased basic
    damage based on distance.  We always assume maximum distance for the
    calculation.

    Args:
        items: List of item data dicts.

    Returns:
        Multiplier for basic attack damage (e.g. 1.10 for 10% amp).
    """
    amp = 0.0
    for item in items:
        name = item.get("name", "")
        effect = ITEM_EFFECTS.get(name)
        if not effect or effect.get("type") != "basic_damage_amp":
            continue
        amp += effect["max_amp"]
    return 1.0 + amp


def calculate_eclipse_damage(
    target_max_health: float,
    is_melee: bool,
    fight_duration: float,
) -> float:
    """Calculate Eclipse Ever Rising Moon proc damage over a fight.

    Assumes one proc occurs immediately, then additional procs every 6s.

    Args:
        target_max_health: Target's maximum health.
        is_melee: Whether the champion is melee.
        fight_duration: Fight duration in seconds.

    Returns:
        Total raw bonus physical damage from Eclipse procs.
    """
    effect = ITEM_EFFECTS.get("Eclipse")
    if not effect:
        return 0.0

    ratio = (
        effect["target_max_hp_ratio_melee"]
        if is_melee
        else effect["target_max_hp_ratio_ranged"]
    )
    per_proc = ratio * target_max_health

    cooldown = effect["cooldown"]
    num_procs = 1 + int(fight_duration / cooldown)
    return per_proc * num_procs


def calculate_shaped_charge_damage(
    champion_stats: dict[str, float],
    is_melee: bool,
    fight_duration: float,
) -> float:
    """Calculate Bastionbreaker Shaped Charge true damage.

    Procs on the first ability damage instance, then every 45s.

    Args:
        champion_stats: Champion's calculated stats.
        is_melee: Whether the champion is melee.
        fight_duration: Fight duration in seconds.

    Returns:
        Total true damage from Shaped Charge procs.
    """
    effect = ITEM_EFFECTS.get("Bastionbreaker")
    if not effect:
        return 0.0

    lethality = champion_stats.get("lethality", 0.0)
    if is_melee:
        per_proc = effect["base_melee"] + effect["lethality_ratio_melee"] * lethality
    else:
        per_proc = effect["base_ranged"] + effect["lethality_ratio_ranged"] * lethality

    cooldown = effect["cooldown"]
    num_procs = 1 + int(fight_duration / cooldown)
    return per_proc * num_procs


def get_armor_reduction(
    items: list[dict[str, Any]],
    fight_duration: float,
    num_auto_attacks: int,
) -> float:
    """Calculate average armor reduction fraction from items like Black Cleaver.

    Args:
        items: List of item data dicts.
        fight_duration: Fight duration in seconds.
        num_auto_attacks: Number of auto attacks in the fight.

    Returns:
        Fraction of armor reduced (e.g., 0.24 for 24% reduction).
    """
    for item in items:
        name = item.get("name", "")
        effect = ITEM_EFFECTS.get(name)
        if effect and effect.get("type") == "armor_reduction":
            # Assume stacks build up over fight; approximate average
            hits = num_auto_attacks + 4  # abilities also apply stacks
            max_stacks = effect["max_stacks"]
            # Ramp up: average stacks over the fight
            if hits >= max_stacks:
                # Most of the fight is at max stacks
                avg_stacks = max_stacks * 0.8
            else:
                avg_stacks = hits / 2.0
            return effect["reduction_per_stack"] * avg_stacks
    return 0.0


def calculate_execute_damage(
    items: list[dict[str, Any]],
    target_health: float,
    total_damage_dealt: float,
) -> float:
    """Calculate bonus damage from execute effects (The Collector).

    If total damage would leave target below execute threshold, the
    remaining HP counts as bonus damage.

    Args:
        items: List of item data dicts.
        target_health: Target's maximum health.
        total_damage_dealt: Total damage already calculated.

    Returns:
        Bonus execute damage (remaining HP below threshold).
    """
    for item in items:
        name = item.get("name", "")
        effect = ITEM_EFFECTS.get(name)
        if effect and effect.get("type") == "execute":
            remaining_hp = target_health - total_damage_dealt
            threshold_hp = target_health * effect["threshold"]
            if 0 < remaining_hp <= threshold_hp:
                return remaining_hp
    return 0.0


def calculate_hullbreaker_proc_damage(
    champion_stats: dict[str, float],
    is_melee: bool,
) -> float:
    """Calculate raw Hullbreaker Skipper proc damage (before resistances).

    Args:
        champion_stats: Champion's calculated stats.
        is_melee: Whether the champion is melee.

    Returns:
        Raw bonus physical damage per proc.
    """
    effect = ITEM_EFFECTS.get("Hullbreaker")
    if not effect:
        return 0.0

    base_ad = champion_stats.get("base_attack_damage", 0.0)
    max_hp = champion_stats.get("health", 0.0)

    if is_melee:
        ad_ratio = effect["base_ad_ratio_melee"]
        hp_ratio = effect["max_hp_ratio_melee"]
    else:
        ad_ratio = effect["base_ad_ratio_ranged"]
        hp_ratio = effect["max_hp_ratio_ranged"]

    return ad_ratio * base_ad + hp_ratio * max_hp


def get_crit_multiplier(items: list[dict[str, Any]]) -> float:
    """Get the critical strike damage multiplier.

    Base crit multiplier is 2.0 (200% AD). Infinity Edge adds +0.30.

    Args:
        items: List of item data dicts.

    Returns:
        Crit damage multiplier (e.g., 2.05 with IE).
    """
    base_crit = 2.0
    for item in items:
        name = item.get("name", "")
        effect = ITEM_EFFECTS.get(name)
        if effect and effect.get("type") == "crit_modifier":
            # Polymorphic across crit_modifier items: Navori Flickerblade
            # has no bonus_crit_damage key, so 0 means "no crit damage
            # modifier" — NOT a stale duplicate of a registry value.
            base_crit += effect.get("bonus_crit_damage", 0)
    return base_crit


def calculate_dead_mans_plate_damage(
    champion_stats: dict[str, float],
) -> float:
    """Calculate Dead Man's Plate first-auto damage at max momentum.

    Args:
        champion_stats: Champion's calculated stats.

    Returns:
        Raw bonus damage for the first auto attack.
    """
    effect = ITEM_EFFECTS.get("Dead Man's Plate")
    if not effect:
        return 0.0
    base_ad = champion_stats.get("base_attack_damage", 0)
    return effect["base"] + effect["base_ad_ratio"] * base_ad


def calculate_heartsteel_damage(
    champion_stats: dict[str, float],
) -> float:
    """Calculate Heartsteel Colossal Consumption proc damage.

    Deals 70 + 6% of the champion's maximum health as bonus physical
    damage. Applied once per fight (30s cooldown).

    Args:
        champion_stats: Champion's calculated stats.

    Returns:
        Raw bonus physical damage from Heartsteel proc.
    """
    effect = ITEM_EFFECTS.get("Heartsteel")
    if not effect:
        return 0.0
    max_hp = champion_stats.get("health", 0)
    return effect["base"] + effect["max_hp_ratio"] * max_hp


def get_stacking_mr_reduction(
    items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return stacking MR reduction effect data if any item provides it.

    Args:
        items: List of item data dicts.

    Returns:
        Effect dict with mr_reduction_per_stack and max_stacks, or None.
    """
    for item in items:
        name = item.get("name", "")
        effect = ITEM_EFFECTS.get(name)
        if effect and effect.get("type") == "mr_reduction_stacking":
            return effect
    return None


def get_item_effect_names(items: list[dict[str, Any]]) -> list[str]:
    """Return names of items that have registered effects.

    Args:
        items: List of item data dicts.

    Returns:
        List of item names that have effects in the registry.
    """
    return [
        item.get("name", "") for item in items if item.get("name", "") in ITEM_EFFECTS
    ]


def get_muramana_ability_damage(
    champion_stats: dict[str, float],
    is_melee: bool,
    num_ability_hits: int,
) -> float:
    """Calculate Muramana bonus damage from ability hits.

    Args:
        champion_stats: Champion's calculated stats.
        is_melee: Whether champion is melee.
        num_ability_hits: Number of ability damage instances.

    Returns:
        Total raw bonus physical damage from Muramana on abilities.
    """
    effect = ITEM_EFFECTS.get("Muramana")
    if not effect:
        return 0.0

    max_mana = champion_stats.get("max_mana", 0)
    ratio = (
        effect["max_mana_ratio_ability_melee"]
        if is_melee
        else effect["max_mana_ratio_ability_ranged"]
    )
    return ratio * max_mana * num_ability_hits


def calculate_unending_despair_damage(
    champion_stats: dict[str, float],
    fight_duration: float,
) -> float:
    """Calculate Unending Despair Anguish damage over a fight.

    Procs every N seconds after entering combat with champions.

    Args:
        champion_stats: Champion's calculated stats.
        fight_duration: Fight duration in seconds.

    Returns:
        Total raw magic damage from Anguish procs.
    """
    effect = ITEM_EFFECTS.get("Unending Despair")
    if not effect:
        return 0.0

    interval = effect["interval"]
    bonus_hp = champion_stats.get("bonus_health", 0)
    ratio = effect["bonus_hp_ratio"]
    per_proc = ratio * bonus_hp

    # First proc at interval seconds, then every interval thereafter
    num_procs = int(fight_duration / interval) if interval > 0 else 0
    return per_proc * num_procs


def get_terminus_pen_stacks(
    num_auto_attacks: int,
) -> float:
    """Calculate average Terminus armor/magic penetration across all autos.

    Dark hits occur on every other auto (2nd, 4th, 6th...) and each
    grants a penetration stack that also applies to that auto's damage.
    Stacks cap at dark_max_stacks.

    The pen per auto ramps up as stacks build:
        Auto 1: 0%, Auto 2: 10%, Auto 3: 10%, Auto 4: 20%,
        Auto 5: 20%, Auto 6+: 30%

    Returns the weighted average pen across all autos, similar to how
    Black Cleaver computes average armor reduction.

    Args:
        num_auto_attacks: Total auto attacks in the fight.

    Returns:
        Average penetration fraction (e.g. 0.225 for 22.5% average).
    """
    effect = ITEM_EFFECTS.get("Terminus")
    if not effect:
        return 0.0

    pen_per_stack = effect["dark_pen_per_stack"]
    max_stacks = effect["dark_max_stacks"]

    if num_auto_attacks == 0:
        return 0.0

    # Simulate pen at each auto
    total_pen = 0.0
    dark_stacks = 0
    for i in range(num_auto_attacks):
        is_dark = (i + 1) % 2 == 0  # Dark hits on 2nd, 4th, 6th, ...
        if is_dark:
            dark_stacks = min(dark_stacks + 1, max_stacks)
        # This auto's damage uses the current pen level
        total_pen += dark_stacks * pen_per_stack

    return total_pen / num_auto_attacks


def get_terminus_light_resist_per_stack(level: int) -> float:
    """Calculate Terminus bonus armor/MR per light hit stack at a given level.

    Light hits grant bonus armor and magic resistance that scales with level.
    At level 1 it's ``light_resist_min``, at level 18 it's ``light_resist_max``.

    Args:
        level: Champion level (1-18).

    Returns:
        Bonus armor (and MR) per light hit stack.
    """
    effect = ITEM_EFFECTS.get("Terminus")
    if not effect:
        return 0.0
    low = effect["light_resist_min"]
    high = effect["light_resist_max"]
    clamped = max(1, min(level, 18))
    return low + (high - low) * (clamped - 1) / 17.0


def get_collector_execution_threshold(
    items: list[dict[str, Any]],
    target_health: float,
) -> float | None:
    """Return the Collector execution HP threshold for display purposes.

    Args:
        items: List of item data dicts.
        target_health: Target's maximum health.

    Returns:
        HP value below which the target would be executed, or None if
        The Collector is not in the build.
    """
    for item in items:
        name = item.get("name", "")
        effect = ITEM_EFFECTS.get(name)
        if effect and effect.get("type") == "execute":
            return target_health * effect["threshold"]
    return None
