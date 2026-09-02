"""K'Sante's marked attack, charge-scaled W and All Out mixed damage."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import CC_PER_PART, ONHIT, SlotCtx, build_parser
from .inputs import bool_option, float_option, int_option
from .module_helpers import no_damage, ranked_slot
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    simple_damage,
)
from .source_receipts import load_champion_sources

# Rooted in KSanteR.Omnivamp; the cached R prose corroborates the 20% value.
_ALLOUT_OMNIVAMP_PERCENT = (
    data_value(spell_object("K'Sante", "KSanteR"), "Omnivamp") * 100.0
)


def _marked_attack(ctx: SlotCtx, ability: dict[str, Any]) -> float:
    base = extract_value(ability, "Bonus Damage", ctx.level)
    ratio = extract_value(ability, "Max Health Damage", ctx.level) / 100.0
    all_out = bool(ctx.option("all_out"))
    extra = (
        0.01
        + 0.01 * ctx.stat("bonus_armor") / 100.0
        + 0.01 * ctx.stat("bonus_magic_resistance") / 100.0
        if all_out
        else 0.0
    )
    return base + (ratio + extra) * float(ctx.target_stat("target_max_health") or 0.0)


def _dauntless(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    count = min(max(int(ctx.option("p_marks")), 0), 8)
    if count <= 0:
        return None
    value = _marked_attack(ctx, ability)
    return {
        "name": ability_name(ability),
        "damage_type": "physical",
        "total_raw": value * count,
        "parts": (
            DamagePart(
                "physical",
                value,
                count=count,
                basic_damage=True,
                time_offset=0.0,
                hit_interval=0.5,
            ),
        ),
        "proc_count": count,
        "event_phase": "effect",
        "damage_events": [
            {
                "time": i * 0.5,
                "damage_type": "physical",
                "damage": value,
                "event_precision": "phase_order",
            }
            for i in range(count)
        ],
        "detail": (
            f"{count} marked attack consumption(s); All Out bonus is "
            f"{bool(ctx.option('all_out'))}."
        ),
    }


_dauntless.phase = ONHIT


def _ntofo(ctx: SlotCtx) -> dict[str, Any] | None:
    return simple_damage(
        attr="Physical Damage",
        dmg_type="physical",
        # "deals physical damage to enemies hit and slows them by 80% for
        # 0.5 seconds" — the empowered two-stack recast's pull and stun are
        # a branch this module does not price.
        event_order_certified="single_hit",
    )(ctx)


# W bonus-resistance ratios (P3 package 4A — typed declaration with
# receipts).  The wiki's W rows carry the ratios ONLY inside the degraded
# units text ("(+ 2% per 100 bonus armor) (+ 2% per 100 bonus magic
# resistance) of target's maximum health"); the game file prices them as
# MaxHealthDamageResistRatio 0.0002 per 1 bonus armor/MR (= 2% per 100)
# and the All Out true-damage fraction RDamageIncreaseMin 0.1 /
# RDamageIncreaseMax 0.8 of the physical formula — the wiki min/max true
# rows are exactly those fractions (0.8% = 0.1 x 8%, 0.2% = 0.1 x 2%,
# 6.4% = 0.8 x 8%, 1.6% = 0.8 x 2%).  The resist terms MUST use the
# caster's BONUS armor/magic resistance (the game's mStat 1/6) — the
# generic compound-unit resolver misattributes them to TOTAL stats.
_W_PHYS_RESIST_PCT_PER_100 = 2.0
_W_TRUE_MIN_RESIST_PCT_PER_100 = 0.2
_W_TRUE_MAX_RESIST_PCT_PER_100 = 1.6


def _require_row(ability: dict[str, Any], attribute: str) -> None:
    """Fail loud when the named leveling row is absent (cache corruption)."""
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                return
    raise KeyError(f"K'Sante {ability_name(ability)} has no {attribute!r} leveling row")


class _PathMakerRule:
    """The typed Path Maker declaration (P3 package 4A).

    W prices one physical packet: the cached flat row + the % max-health
    term (base 8%, plus 2% per 100 BONUS armor and 2% per 100 BONUS
    magic resistance — the game MaxHealthDamageResistRatio 0.0002,
    wiki-fossilized in the degraded units).  In All Out the true-damage
    range interpolates between the Minimum/Maximum Bonus True Damage
    rows (the game's 10%..80% fractions of the physical formula) by the
    w_charge fraction.  The bonus-resist terms are priced with the
    caster's bonus stats (never the target's or the totals); the R
    armor/MR-to-AD conversion and the 65% health threshold remain
    named state.
    """

    def __init__(self) -> None:
        self.physical_row_attribute = "Physical Damage"
        self.min_true_row_attribute = "Minimum Bonus True Damage"
        self.max_true_row_attribute = "Maximum Bonus True Damage"
        self.base_max_health_percent = 8.0
        self.resist_percent_per_100 = _W_PHYS_RESIST_PCT_PER_100
        self.true_min_resist_percent_per_100 = _W_TRUE_MIN_RESIST_PCT_PER_100
        self.true_max_resist_percent_per_100 = _W_TRUE_MAX_RESIST_PCT_PER_100
        self.default = 1.0
        self.min = 0.0
        self.max = 1.0
        self.step = 0.25
        self.source = {
            "label": "Local League Wiki cache — K'Sante W template + game file",
            "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_K%27Sante/W",
            "revision_id": 3471720,
            "revision_timestamp": "2022-10-16T16:25:10Z",
            "parent_revision_id": 4011715,
            "game_file": "data/bin/characters/ksante.bin.json "
            "(MaxHealthDamage 0.08, MaxHealthDamageResistRatio 0.0002, "
            "RDamageIncreaseMin 0.1 / Max 0.8)",
            "note": "the resist ratios survive ONLY in the degraded units "
            "text; the bonus attribution is game-verified (mStat 1/6 = "
            "bonus armor / bonus magic resistance).",
        }

    def public_receipt(self) -> dict[str, Any]:
        return {
            "name": "K'Sante — Path Maker (W)",
            "physical_row_attribute": self.physical_row_attribute,
            "min_true_row_attribute": self.min_true_row_attribute,
            "max_true_row_attribute": self.max_true_row_attribute,
            "base_max_health_percent": self.base_max_health_percent,
            "resist_percent_per_100": self.resist_percent_per_100,
            "true_min_resist_percent_per_100": self.true_min_resist_percent_per_100,
            "true_max_resist_percent_per_100": self.true_max_resist_percent_per_100,
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "step": self.step,
            "source": dict(self.source),
        }


KSANTE_PATH_MAKER_RULE = _PathMakerRule()


@ranked_slot
def _path_maker(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    charge = min(max(float(ctx.option("w_charge")), 0.0), 1.0)
    for attribute in (
        "Physical Damage",
        "Minimum Bonus True Damage",
        "Maximum Bonus True Damage",
    ):
        _require_row(ability, attribute)
    flat = extract_value(ability, "Physical Damage", rank, 0)
    base_pct = extract_value(ability, "Physical Damage", rank, 1)
    bonus_armor = ctx.stat("bonus_armor")
    bonus_mr = ctx.stat("bonus_magic_resistance")
    max_health = float(ctx.target_stat("target_max_health") or 0.0)
    resist_pct = _W_PHYS_RESIST_PCT_PER_100 * (bonus_armor / 100.0) + (
        _W_PHYS_RESIST_PCT_PER_100 * (bonus_mr / 100.0)
    )
    physical = flat + (base_pct + resist_pct) / 100.0 * max_health
    if bool(ctx.option("all_out")):
        min_flat = extract_value(ability, "Minimum Bonus True Damage", rank, 0)
        min_pct = extract_value(ability, "Minimum Bonus True Damage", rank, 1)
        max_flat = extract_value(ability, "Maximum Bonus True Damage", rank, 0)
        max_pct = extract_value(ability, "Maximum Bonus True Damage", rank, 1)
        min_resist_pct = _W_TRUE_MIN_RESIST_PCT_PER_100 * (bonus_armor / 100.0) + (
            _W_TRUE_MIN_RESIST_PCT_PER_100 * (bonus_mr / 100.0)
        )
        max_resist_pct = _W_TRUE_MAX_RESIST_PCT_PER_100 * (bonus_armor / 100.0) + (
            _W_TRUE_MAX_RESIST_PCT_PER_100 * (bonus_mr / 100.0)
        )
        low = min_flat + (min_pct + min_resist_pct) / 100.0 * max_health
        high = max_flat + (max_pct + max_resist_pct) / 100.0 * max_health
        true_value = low + (high - low) * charge
        # Both packets are the one dash, so the physical half lands at the
        # same authored instant as the true half.  All Out's Path Maker
        # applies no knock back and no stun.
        parts = (
            DamagePart("physical", physical, time_offset=charge, cc_kind="none"),
            DamagePart("true", true_value, time_offset=charge, cc_kind="none"),
        )
        total = physical + true_value
    else:
        parts = (DamagePart("physical", physical, time_offset=charge, cc_kind="stun"),)
        total = physical
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = parts
    entry["detail"] = (
        f"{charge:.2f} charge; All Out true damage is {bool(ctx.option('all_out'))}."
    )
    return entry


@ranked_slot
def _all_out(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
    value = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    if bool(ctx.option("r_terrain")):
        strike = extract_named(
            ability, "Strike Physical Damage", rank, ctx.stats, ctx.target
        )
        parts = (
            DamagePart("physical", value, time_offset=0.3),
            DamagePart("physical", strike, time_offset=0.432),
        )
        total = value + strike
    else:
        parts = (DamagePart("physical", value, time_offset=0.3),)
        total = value
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = parts
    entry["detail"] = (
        "Terrain strike is explicit; the 65% health threshold and resist "
        "conversion are state; All Out's 20% omnivamp is priced on the "
        "fight's explicitly single-target attack/on-hit packets."
    )
    if bool(ctx.option("all_out")):
        entry["stat_buff"] = {
            "bonus_attack_speed": extract_value(ability, "Bonus Attack Speed", rank),
            "armor_penetration_bonus_percent": 50.0,
            # "he gains bonus attack speed, 50% bonus-armor penetration, and
            # 20% omnivamp" (cached R fourth effect).  The fight engine's
            # omnivamp channel prices 20% of the post-mitigation damage of
            # explicitly single-target attack/on-hit packets (its
            # full-effectiveness certification scope); the remaining
            # ability-damage omnivamp stays a documented boundary, matching
            # the engine's conservative omnivamp contract.
            "omnivamp_percent": _ALLOUT_OMNIVAMP_PERCENT,
        }
    return entry


SLOTS = {
    "P": _dauntless,
    "Q": _ntofo,
    "W": _path_maker,
    "E": lambda ctx: no_damage(
        ctx,
        name="Footwork",
        reason="Dash and self/ally shield are defensive/ally utility.",
    ),
    "R": _all_out,
}
# R's target "is stunned for 0.3 seconds once [the displacement] ends" —
# and 0.5 seconds after the airborne on the terrain branch — so both of its
# packets land with a stun.  W's kind depends on the All Out branch and
# rides its parts.  E authors no damage part, and P's mark-consumption row
# is an effect-phase proc with a module-built event list the marker would
# not reach.
MODULE_CC = {"Q": "slow", "W": CC_PER_PART, "R": "stun"}

parse_abilities = build_parser(SLOTS, "K'Sante", cc_kinds=MODULE_CC)
OPTIONS = [
    int_option(
        "p_marks", 1, minimum=0, maximum=8, label="Dauntless Instinct marked attacks"
    ),
    float_option(
        "w_charge",
        1.0,
        minimum=0.0,
        maximum=1.0,
        label="Path Maker charge fraction",
        step=0.25,
        state=KSANTE_PATH_MAKER_RULE.public_receipt(),
    ),
    bool_option("r_terrain", False, label="All Out terrain strike"),
    bool_option("all_out", False, label="All Out state"),
]
ASSUMPTIONS = [
    "Dauntless Instinct is an explicit marked-attack proc, not an assumed proc on every auto.",
    "Path Maker uses its physical packet and optionally the authored All Out "
    "true-damage range; charge duration is explicit.",
    "All Out terrain routing and the health threshold / resistance conversion remain "
    "visible state rather than hidden arithmetic; the 20% omnivamp IS priced on the "
    "fight's explicitly single-target attack/on-hit packets (the engine's "
    "full-effectiveness omnivamp scope) and the remaining ability-damage omnivamp is "
    "a documented boundary",
]
SOURCES = load_champion_sources("K'Sante")
