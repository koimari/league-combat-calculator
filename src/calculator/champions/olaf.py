"""Olaf — CP10.5 full-entry-reviewed packet module, plus the E8c W shield.

E8c addition over the reviewed packet:
- W (Tough It Out) grants Olaf a shield for 2.5 seconds equal to
  10/40/70/100/130 (+ 17.5% missing health) (cached Shield Strength
  row).  W deals no damage, so the shield is emitted by the
  ally-support scanner at the W cast (self-targeted).  The missing
  health term is evaluated by the scanner at 0 (full-health floor);
  the sourced 17.5% missing-health scaling is a documented boundary —
  the module pins it as a constant for audit, but the scanner's packet
  carries the flat component only.

The three stat steroids are priced here, each from its cached leveling
row and each as a BUFF-phase ``stat_buff`` the fight engine folds in:

- P (Berserker Rage) scales "0% : 100% (based on missing health)" of a
  per-level attack-speed row (50% : 107.84%), so the share of Olaf's
  health that is missing is an explicit option — the fight engine runs
  no self-health timeline.  The second per-level row is life steal,
  for which the dispatch has no key.
- W (Tough It Out) carries a Bonus Attack Speed row (40-80%) beside the
  shield above, for the same sourced 5 seconds.
- R (Ragnarok) grants bonus attack damage (10/20/30 + 25% AD) and
  bonus resistances (10/15/20) for 3 seconds; its bonus movement speed
  has no key.

R's cleanse, its 3s crowd-control immunity, the 10% size increase and
the per-hit duration extension have no kernel field and stay named
rather than priced (tests/test_olaf_r_cleanse.py is their receipt).
"""

from typing import Any

from .engine import BUFF, SlotCtx
from .module_helpers import buff_window_share
from .packet_module import build_packet_module
from .slotlib import (
    STEROID_ZERO,
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    sum_modifiers,
)
from .inputs import int_option

PACKET_SHA256 = "abc0765ed94d66999d26bc7fe98c41c49c3d5e3631c4cca2a96a59de1ba776eb"

# HARDCODED: verify on patch updates — the two Per-Level Scaling rows on
# Berserker Rage are ordered attack speed first, life steal second
# ("bonus attack speed and 8% : 27.67% (based on level) life steal"),
# and the sourced buff windows are cached prose: Tough It Out "for 5
# seconds", Ragnarok "enraged for 3 seconds".
_P_ATTACK_SPEED_OCCURRENCE = 0
_P_LIFE_STEAL_OCCURRENCE = 1
_W_DURATION_SECONDS = 5.0
_R_DURATION_SECONDS = 3.0
# Dr. Mundo's declared self-missing-health default, the one convention
# this tree has for a fight state the engine does not track.
_DEFAULT_MISSING_HEALTH_PERCENT = 30


def _per_level_row(ability: dict[str, Any], occurrence: int, level: int) -> float:
    """One of Berserker Rage's two Per-Level Scaling rows at *level*."""
    leveling = find_named_leveling(ability, "Per-Level Scaling", occurrence=occurrence)
    if leveling is None:
        # A silent zero would erase the passive — fail loudly instead.
        raise ValueError(
            f"Olaf P: 'Per-Level Scaling' leveling entry #{occurrence} "
            "(attack speed / life steal) missing from the ability JSON"
        )
    return sum_modifiers(leveling, level, level=level)


def _berserker_rage(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: missing-health-scaled attack speed (0-100% of 50-107.84%)."""
    ability = ctx.ability("P")
    if ability is None:
        return None

    missing = (
        min(max(float(ctx.option("olaf_missing_health_percent")), 0.0), 100.0) / 100.0
    )
    at_full_rage = _per_level_row(ability, _P_ATTACK_SPEED_OCCURRENCE, ctx.level)
    life_steal = _per_level_row(ability, _P_LIFE_STEAL_OCCURRENCE, ctx.level)
    bonus_as = at_full_rage * missing
    entry = damage_entry(
        ability_name(ability),
        ctx.level,
        0.0,
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    entry["detail"] = (
        f"{missing * 100:g}% missing health of the +{at_full_rage:g}% "
        f"per-level row = +{bonus_as:g}% bonus attack speed; the row's "
        f"{life_steal:g}% life steal has no stat_buff key"
    )
    return entry


_berserker_rage.phase = BUFF


def _tough_it_out(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the 40-80% attack speed beside the scanner-owned shield."""
    ranked = ctx.ranked("W")
    if ranked is None:
        return None
    ability, rank = ranked

    granted = extract_value(ability, "Bonus Attack Speed", rank)
    bonus_as = granted * buff_window_share(ctx, _W_DURATION_SECONDS)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    entry["detail"] = (
        f"+{granted:g}% bonus attack speed for {_W_DURATION_SECONDS:g}s "
        f"({bonus_as:g}% over the fight window); the cast's Shield "
        "Strength row is emitted by the ally-support scanner"
    )
    return entry


_tough_it_out.phase = BUFF


def _ragnarok(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: bonus attack damage (10-30 + 25% AD) and resistances for 3s."""
    ranked = ctx.ranked("R")
    if ranked is None:
        return None
    ability, rank = ranked

    share = buff_window_share(ctx, _R_DURATION_SECONDS)
    granted_ad = extract_named(
        ability, "Bonus Attack Damage", rank, ctx.stats, ctx.target
    )
    granted_resists = extract_value(ability, "Bonus Resistances", rank)
    movement = extract_value(ability, "Bonus Movement Speed", rank)
    bonus_ad = granted_ad * share
    resists = granted_resists * share
    ctx.stats["bonus_attack_damage"] = ctx.stat("bonus_attack_damage") + bonus_ad
    ctx.stats["attack_damage"] = ctx.stat("attack_damage") + bonus_ad
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {
        "bonus_attack_damage": bonus_ad,
        "armor": resists,
        "magic_resistance": resists,
    }
    entry["detail"] = (
        f"+{granted_ad:g} bonus attack damage and +{granted_resists:g} "
        f"armour/magic resistance for {_R_DURATION_SECONDS:g}s "
        f"(+{bonus_ad:g} AD over the fight window); the row's "
        f"+{movement:g}% movement speed, the crowd-control immunity and "
        "the takedown duration extension have no channel"
    )
    return entry


_ragnarok.phase = BUFF


# Cached kit review.  Undertow's axe "deals physical damage to enemies it
# passes through and slows them for 1 : 3 (based on distance travelled)
# seconds" — the armour reduction beside it is a resistance shred, not a
# control class.  Reckless Swing only "deal[s] true damage".  W (a shield
# and attack speed), R (Olaf's own cleanse and immunity) and P (attack
# speed and life steal) damage nothing, so no event of theirs could carry
# an answer.
MODULE_CC = {"Q": "slow", "E": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Olaf",
    PACKET_SHA256,
    # The axe hits each enemy in its line once and Reckless Swing strikes
    # its target once — the boundary claim that carries MODULE_CC's
    # reviewed answers into the event ledger.
    single_hit_slots=frozenset({"Q", "E"}),
    slot_parsers={
        "P": _berserker_rage,
        "W": _tough_it_out,
        "R": _ragnarok,
    },
    cc_kinds=MODULE_CC,
)

# The Ragnarok rows that have NO channel to reach the fight (game file
# OlafRagnarok: HasteDuration 1.0, DurationExtension 2.5, the 10% size
# increase; the first-second MS facing/2000-unit condition is prose-only,
# and the movement utility surface carries the amount + its 1s window) are
# named-unsupported — never applied.  The rows that DO reach the fight
# (Duration 3.0, FlatAD 10/20/30 + PercentTotalADAmp 0.25, Resists
# 10/15/20) are not restated here: ``_ragnarok`` reads them live from the
# cache, and the cleanse + immunity receipts are authored per R cast by the
# participant timeline.

# HARDCODED: verify on patch updates — Tough It Out's 2.5s shield
# duration and 17.5% missing-health ratio are prose/cached leveling
# (data/champions.json, Olaf W): "grants himself a shield for 2.5
# seconds" + Shield Strength 10/40/70/100/130 (+ 17.5% missing health),
# capped at 70% missing health.  The scanner emits the flat component at
# the full-health floor; the missing-health term is documented.
TOUGH_IT_OUT_SHIELD_DURATION_SECONDS = 2.5
TOUGH_IT_OUT_MISSING_HEALTH_RATIO = 0.175
TOUGH_IT_OUT_MISSING_HEALTH_CAP = 0.70

OPTIONS = list(OPTIONS) + [
    int_option(
        "olaf_missing_health_percent",
        _DEFAULT_MISSING_HEALTH_PERCENT,
        minimum=0,
        maximum=100,
        label="Olaf's missing health (%) — scales Berserker Rage",
        rotation={
            "role": "self_state",
            "slot": "P",
            "note": (
                "Olaf's own health, which the fight engine does not track; "
                "it scales P alone."
            ),
        },
    ),
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Tough It Out) shields Olaf for the sourced 10/40/70/100/130 + "
    "17.5% missing health for 2.5s at the cast; the ally-support scanner "
    "emits the self packet with the flat component at the full-health "
    "floor (the missing-health term and its 70%-of-missing-health cap "
    "are documented boundaries), and it absorbs incoming damage in the "
    "participant ledger",
    "P (Berserker Rage) grants the first Per-Level Scaling row "
    "(50% : 107.84% bonus attack speed) scaled by Olaf's missing health, "
    "which the fight engine does not track — olaf_missing_health_percent "
    "is that input, defaulting to 30% (the tree's one declared "
    "self-missing-health default).  The second row (8% : 27.67% life "
    "steal) has no stat_buff key and is named rather than priced.",
    "W's Bonus Attack Speed row (40-80%) and R's Bonus Attack Damage "
    "(10/20/30 + 25% AD) and Bonus Resistances (10/15/20) rows are "
    "applied for their sourced 5- and 3-second windows, time-weighted by "
    "the share of the fight window each covers.  R's bonus movement "
    "speed, its crowd-control immunity and the up-to-2.5s-per-hit "
    "duration extension are named rather than priced.",
]

# No MODULE_COVERAGE: every one of the five slots emits a priced row now
# (Q/E damage, W a shield plus a steroid, P and R stat buffs).
