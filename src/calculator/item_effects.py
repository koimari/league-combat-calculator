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
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Sequence

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Complete offline item effect snapshot
# ---------------------------------------------------------------------------
# Normal cached-data operation does not merge from this table. It is the
# explicit whole-system fallback and the parity reference for parser updates.
_OFFLINE_ITEM_EFFECTS: dict[str, dict[str, Any]] = {
    # ── On-Hit (per auto attack) ──────────────────────────────────────────
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
    "Terminus": {
        "type": "on_hit",
        "formula": "flat",
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
        "formula": "max_hp",
        "secondary_behavior": "auto_cooldown",
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
    # ── Spellblade (after ability, next auto, mutually exclusive) ─────────
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
    },
    # ── Burn / DoT ────────────────────────────────────────────────────────
    "Liandry's Torment": {
        "type": "burn",
        "formula": "max_hp",
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
        "formula": "flat_ap",
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
        "formula": "bonus_hp_dps",
        "damage_type": "magic",
        # 20 + 1% bonus HP per second
        "base_per_second": 20.0,
        "bonus_hp_ratio_per_second": 0.01,
    },
    "Hollow Radiance": {
        "type": "immolate",
        "formula": "bonus_hp_dps",
        "damage_type": "magic",
        # 15 + 1% bonus HP per second
        "base_per_second": 15.0,
        "bonus_hp_ratio_per_second": 0.01,
    },
    # ── Proc Damage (cooldown-gated) ──────────────────────────────────────
    "Luden's Echo": {
        "type": "proc",
        "formula": "charged_ap",
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
    },
    "Stormsurge": {
        "type": "proc",
        "formula": "flat_ap",
        "repeat_on_cooldown": False,
        "damage_type": "magic",
        # 125 + 10% AP, 30s CD (triggers at 25% HP damage in 2.5s)
        "base": 125.0,
        "ap_ratio": 0.10,
        "cooldown": 30.0,
        "is_ability_damage": True,  # Amplified by Actualizer
    },
    "Zaz'Zak's Realmspike": {
        "type": "proc",
        "formula": "flat_ap_max_hp",
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
        "formula": "total_ad",
        "damage_type": "physical",
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
        "formula": "total_ad",
        "damage_type": "physical",
        # Ravenous Crescent: 80% total AD
        "total_ad_ratio": 0.80,
        "cooldown": 10.0,
    },
    "Stridebreaker": {
        "type": "active",
        "formula": "total_ad",
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
        "formula": "max_hp",
        "breakdown_key": "proc_Eclipse",
        "display_name": "Eclipse (Ever Rising Moon)",
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
        "formula": "flat",
        "breakdown_key": "on_hit_once_Rapid Firecannon",
        "display_name": "Rapid Firecannon (Sharpshooter)",
        "damage_type": "magic",
        # Sharpshooter: 40 bonus magic damage on first energized auto
        "base": 40.0,
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
        "rapids_bonus_ap": 40.0,
    },
    "Sterak's Gage": {
        "type": "stat_conversion",
        "base_ad_to_bonus_ad_ratio": 0.45,
    },
    "Stormrazor": {
        "type": "on_hit_once",
        "formula": "flat",
        "breakdown_key": "on_hit_once_Stormrazor",
        "display_name": "Stormrazor (Bolt)",
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
        "formula": "current_hp",
        "breakdown_key": "on_hit_once_Voltaic Cyclosword",
        "display_name": "Voltaic Cyclosword (Firmament)",
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
        "formula": "bonus_hp",
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
        "is_ability_damage",
        "double_on_hit",
    }
)

_STATIC_VALUE_KEYS_BY_ITEM: dict[str, frozenset[str]] = {
    "Blade of the Ruined King": frozenset({"min_damage"}),
    "Experimental Hexplate": frozenset({"bonus_attack_speed_percent"}),
    "Hextech Gunblade": frozenset({"base_min", "base_max", "cooldown"}),
    "Hextech Rocketbelt": frozenset({"cooldown"}),
    "Malignance": frozenset({"base", "ap_ratio", "duration"}),
    "Muramana": frozenset(
        {"max_mana_ratio_ability_melee", "max_mana_ratio_ability_ranged"}
    ),
    "Profane Hydra": frozenset({"cooldown"}),
    "Ravenous Hydra": frozenset({"cooldown"}),
    "Stridebreaker": frozenset({"cooldown"}),
    "Titanic Hydra": frozenset({"active_cooldown"}),
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


# Build the live registry at import time.
ITEM_EFFECTS: dict[str, dict[str, Any]] = _build_item_effects()


def _required_effect_value(item_name: str, key: str) -> Any:
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


def _item_names(items: list[dict[str, Any]]) -> set[str]:
    """Return the set of item names in a build."""
    return {item.get("name", "") for item in items}


# ---------------------------------------------------------------------------
# Compiled fight-engine boundary
# ---------------------------------------------------------------------------

DamageType = Literal["physical", "magic", "true"]
RawDamageFormula = Callable[["DamageInputs"], float]


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


@dataclass(frozen=True, slots=True)
class PerHitEffect:
    """Damage applied on each auto-attack on-hit application."""

    source: DamageSource
    tracks_current_health: bool = False


@dataclass(frozen=True, slots=True)
class SpellbladeEffect:
    """One mutually-exclusive spellblade behavior."""

    source: DamageSource
    cooldown: float
    weave_delay: float
    double_on_hit: bool = False
    expose_weakness_melee: float = 0.0
    expose_weakness_ranged: float = 0.0


@dataclass(frozen=True, slots=True)
class BurnEffect:
    """Refreshable burn behavior with an item-owned base-duration formula."""

    source: DamageSource
    duration: float


@dataclass(frozen=True, slots=True)
class PeriodicEffect:
    """Damage applied once per fixed interval."""

    source: DamageSource
    interval: float


@dataclass(frozen=True, slots=True)
class CooldownProcEffect:
    """Triggered damage with optional repeated cooldown applications."""

    source: DamageSource
    cooldown: float
    repeat_on_cooldown: bool = True
    late_phase: bool = False


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
    basic_amp: float = 1.0
    ability_amp: AbilityAmplifierEffect | None = None
    hypershot_amp: float = 1.0
    armor_reduction: ArmorReductionEffect | None = None
    basic_amp_source: str | None = None
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
) -> DamageSource:
    """Build shared source metadata without leaking registry records."""
    return DamageSource(
        item_name=item_name,
        breakdown_key=breakdown_key or f"on_hit_{item_name}",
        display_name=f"{item_name} ({suffix})",
        damage_type=damage_type,
        raw_damage=raw_damage,
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
    return PerHitEffect(source, tracks_current_health=formula == "current_hp")


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
    return SpellbladeEffect(
        source=source,
        cooldown=required.number("cooldown"),
        weave_delay=required.number("weave_delay"),
        double_on_hit=bool(values.get("double_on_hit", False)),
        expose_weakness_melee=float(values.get("expose_weakness_melee", 0.0)),
        expose_weakness_ranged=float(values.get("expose_weakness_ranged", 0.0)),
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

    else:
        raise ValueError(f"Unsupported burn formula {formula!r} for {item_name!r}")
    source = _damage_source(
        item_name,
        required.value("damage_type"),
        raw,
        suffix="burn",
        breakdown_key=f"burn_{item_name}",
    )
    return BurnEffect(source, required.number("duration"))


def _compile_immolate(item_name: str, values: Mapping[str, Any]) -> DamageSource:
    """Compile one Immolate formula as raw damage per second."""
    required = _RequiredValues(item_name, values)
    if required.value("formula") != "bonus_hp_dps":
        raise ValueError(f"Unsupported Immolate formula for {item_name!r}")
    base = required.number("base_per_second")
    bonus_hp_ratio = required.number("bonus_hp_ratio_per_second")

    def raw(inputs: DamageInputs) -> float:
        return base + bonus_hp_ratio * inputs.champion_stats.get("bonus_health", 0.0)

    return _damage_source(
        item_name,
        required.value("damage_type"),
        raw,
        suffix="Immolate",
        breakdown_key=f"immolate_{item_name}",
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
    return PeriodicEffect(source, required.number("interval"))


def _compile_proc(item_name: str, values: Mapping[str, Any]) -> CooldownProcEffect:
    """Compile one triggered proc's per-application raw damage."""
    required = _RequiredValues(item_name, values)
    formula = required.value("formula")
    if formula == "charged_ap":
        base = required.number("base_per_charge")
        ap_ratio = required.number("ap_ratio_per_charge")
        multiplier = required.number("single_target_multiplier")

        def raw(inputs: DamageInputs) -> float:
            ap = inputs.champion_stats.get("ability_power", 0.0)
            return (base + ap_ratio * ap) * multiplier

    elif formula == "flat_ap":
        base = required.number("base")
        ap_ratio = required.number("ap_ratio")

        def raw(inputs: DamageInputs) -> float:
            return base + ap_ratio * inputs.champion_stats.get("ability_power", 0.0)

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
    )
    return CooldownProcEffect(
        source,
        required.number("cooldown"),
        bool(values.get("repeat_on_cooldown", True)),
    )


def _compile_ultimate_proc(
    item_name: str,
    values: Mapping[str, Any],
) -> UltimateProcEffect:
    """Compile one ultimate-triggered duration formula."""
    required = _RequiredValues(item_name, values)
    if required.value("formula") != "flat_ap":
        raise ValueError(f"Unsupported ultimate proc formula for {item_name!r}")
    base = required.number("base")
    ap_ratio = required.number("ap_ratio")

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
        float(values.get("mr_reduction", 0.0)),
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
    return _damage_source(
        item_name,
        required.value("damage_type"),
        raw,
        suffix="active",
        breakdown_key=f"active_{item_name}",
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
    return FirstAutoEffect(
        _explicit_damage_source(item_name, required, raw),
        max_procs=max_procs,
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

    def raw(inputs: DamageInputs) -> float:
        ratio = melee_ratio if inputs.is_melee else ranged_ratio
        return ratio * inputs.target_max_health

    return CooldownProcEffect(
        source=_explicit_damage_source(item_name, required, raw),
        cooldown=required.number("cooldown"),
        late_phase=True,
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
        "execute",
        "first_auto_crit",
        "hypershot_amp",
        "immolate",
        "magic_damage_amp",
        "magic_true_crit",
        "max_hp_proc",
        "mr_reduction_stacking",
        "on_hit",
        "on_hit_once",
        "on_hit_stacking",
        "periodic_aoe",
        "proc",
        "shaped_charge",
        "spellblade",
        "stat_conversion",
        "ult_attack_speed_buff",
        "ult_empowered_autos",
        "ult_proc",
    }
)


def resolve_damage_effects(
    items: Sequence[Mapping[str, Any]],
) -> BuildDamageEffects:
    """Compile a build's registered damage behaviors from the live registry."""
    per_hits: list[PerHitEffect] = []
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
    basic_amp = 1.0
    ability_amp: AbilityAmplifierEffect | None = None
    hypershot_amp = 1.0
    armor_reduction: ArmorReductionEffect | None = None
    basic_amp_source: str | None = None
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
                f"({required.number('bonus_attack_speed_percent'):.0f}% bonus AS) "
                "is applied from time 0."
            )
        elif effect_type == "magic_true_crit":
            required = _RequiredValues(item_name, values)
            magic_true_crit = MagicTrueCritEffect(
                item_name,
                required.number("health_threshold"),
                required.number("crit_multiplier"),
            )
        elif effect_type == "basic_damage_amp":
            basic_amp += _RequiredValues(item_name, values).number("max_amp")
            basic_amp_source = item_name
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
            )

    return BuildDamageEffects(
        per_hits=tuple(per_hits),
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
        basic_amp_source=basic_amp_source,
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


def _mana_to_ap_bonus(items: list[dict[str, Any]], bonus_mana: float) -> float:
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


def _dawncore_bonus_ap(
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


def _flowing_water_bonus_ap(items: list[dict[str, Any]]) -> float:
    """Staff of Flowing Water Rapids: flat bonus AP (assumed always active).

    Args:
        items: List of item data dicts.

    Returns:
        Flat bonus AP from Rapids.
    """
    if "Staff of Flowing Water" not in _item_names(items):
        return 0.0
    return _required_effect_value("Staff of Flowing Water", "rapids_bonus_ap")


def _passive_attack_speed_bonus(
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


def _muramana_bonus_ad(items: list[dict[str, Any]], max_mana: float) -> float:
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


def _bloodmail_bonus_ad(
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


def _steraks_bonus_ad(items: list[dict[str, Any]], base_ad: float) -> float:
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


def _terminus_max_stack_bonuses(
    items: list[dict[str, Any]],
    level: int,
) -> tuple[float, float]:
    """Terminus Juxtaposition at max stacks: (bonus armor/MR, pen percent).

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
    max_stacks = _required_effect_value("Terminus", "dark_max_stacks")
    low_resist = _required_effect_value("Terminus", "light_resist_min")
    high_resist = _required_effect_value("Terminus", "light_resist_max")
    clamped_level = max(1, min(level, 18))
    resist_per_stack = (
        low_resist + (high_resist - low_resist) * (clamped_level - 1) / 17.0
    )
    bonus_resist = resist_per_stack * max_stacks
    pen_percent = (
        _required_effect_value("Terminus", "dark_pen_per_stack") * max_stacks * 100.0
    )
    return bonus_resist, pen_percent


def _basic_ability_haste(items: list[dict[str, Any]]) -> float:
    """Spear of Shojin Dragonforce: basic ability haste (Q, W, E only).

    Args:
        items: List of item data dicts.

    Returns:
        Total basic ability haste.
    """
    if "Spear of Shojin" not in _item_names(items):
        return 0.0
    return _required_effect_value("Spear of Shojin", "basic_ability_haste")


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
    ap_multiplier: float  # Rabadon's / Blackfire additive %AP (1.0 = none)
    bonus_ad: float  # Muramana, Overlord's Bloodmail, Sterak's Gage
    attack_speed_percent: float  # Bandlepipes, Hexplate, Yun Tal
    bonus_resists: float  # Terminus light stacks (armor AND MR)
    bonus_pen_percent: float  # Terminus dark stacks (armor AND magic pen)
    basic_ability_haste: float  # Spear of Shojin (Q/W/E only)


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
) -> StatBonuses:
    """Compile the stat-granting passives of *items* into one bundle.

    Callers supply the pre-computed stats each conversion reads (Awe
    reads bonus mana, Muramana total mana, Bloodmail bonus health,
    Sterak's base AD, Dawncore bonus base mana regen). A stat-converting
    item added here is the ONLY edit item-side; ``stats.py`` never grows
    a new import or call site.
    """
    terminus_resists, terminus_pen = _terminus_max_stack_bonuses(items, level)
    return StatBonuses(
        bonus_ap=(
            _mana_to_ap_bonus(items, bonus_mana)
            + _dawncore_bonus_ap(items, bonus_mana_regen_percent)
            + _flowing_water_bonus_ap(items)
        ),
        ap_multiplier=_ap_multiplier(items),
        bonus_ad=(
            _muramana_bonus_ad(items, max_mana)
            + _bloodmail_bonus_ad(items, bonus_health)
            + _steraks_bonus_ad(items, base_attack_damage)
        ),
        attack_speed_percent=_passive_attack_speed_bonus(items, is_melee),
        bonus_resists=terminus_resists,
        bonus_pen_percent=terminus_pen,
        basic_ability_haste=_basic_ability_haste(items),
    )
