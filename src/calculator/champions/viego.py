"""Viego: full-entry-reviewed packet module.

Q (Blade of the Ruined King) is three things at once: the ACTIVE "Physical
Damage" row, the passive %current-health on-hit with its "Minimum Bonus Damage"
floor on the engine's every-auto path, and the mark-consuming second strike,
prose-sourced, through ``q_second_strike``.  Pricing only the health-ratio rows
drops the active entirely.
R (Heartbreaker) is the 120% AD base strike from wiki prose PLUS the cached
%missing-health bonus as a live hp-scaled part.
E (Harrowed Path) prices the one grant the engine has a channel for, the cached
"Bonus Attack Speed" row scaled by the explicit ``e_mist_uptime`` share of the
fight spent on his own trail.  Its movement speed and camouflage have none.
P stays an emitted zero row: possession assumes another champion's whole kit,
which is out of scope by construction.
"""

from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import calculation_coefficient, data_value, spell_object
from .contract_vocabulary import coverage
from .engine import BUFF, SlotCtx
from .inputs import int_option
from .module_helpers import ranked_slot
from .packet_module import build_packet_module
from .slot_entries import STEROID_ZERO, damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named, extract_value
from .slotlib import with_item_on_hits

# The Q second-strike ratios and R base ratio are rooted in named binary
# calculation fields; the cached descriptions corroborate their semantics.
# The mark-consuming second strike deals "20% AD (+ 15% AP) physical
# damage" (Q description, cached JSON); Heartbreaker's base strike is
# "120% AD physical damage" (R description, cached JSON).
_VIEGO_Q_SPELL = spell_object("Viego", "ViegoQ")
_VIEGO_R_SPELL = spell_object("Viego", "ViegoR")
# The second-strike AD coefficient is a binary calculation coefficient; its AP
# coefficient and R's base ratio are DataValues.
_Q_SECOND_STRIKE_AD_RATIO = calculation_coefficient(
    _VIEGO_Q_SPELL, "SecondAttackDamage"
)
_Q_SECOND_STRIKE_AP_RATIO = data_value(_VIEGO_Q_SPELL, "SecondAttackAPRatio")
_R_BASE_AD_RATIO = data_value(_VIEGO_R_SPELL, "ADRatio")

PACKET_SHA256 = "d0f43663666c21a592a44a6a4ee267b0e18e355d9908363bf4f8aa866160756b"


def _blade_of_the_ruined_king(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the active thrust plus the on-hit passive and mark second strike."""
    ranked = ctx.ranked("Q")
    if ranked is None:
        return None
    ability, rank = ranked
    active = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    second_strikes = min(max(int(ctx.option("q_second_strike")), 0), 20)
    second_damage = (
        second_strikes
        * (
            _Q_SECOND_STRIKE_AD_RATIO * float(ctx.stat("attack_damage"))
            + _Q_SECOND_STRIKE_AP_RATIO * float(ctx.stat("ability_power"))
        )
        if second_strikes > 0
        else 0.0
    )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        active + second_damage,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", active + second_damage),)
    entry["event_order_certified"] = "single_hit"
    # The passive: every basic attack deals 2-6% of the target's CURRENT
    # health (minimum 10-30) bonus physical damage — the engine's
    # current-health on-hit simulation (Jarvan IV pattern) prices it
    # against the decayed target HP; proc_cooldown 0 = every auto procs.
    pct = extract_value(ability, "Bonus Physical Damage", rank, 0)
    floor = extract_value(ability, "Minimum Bonus Damage", rank, 0)
    entry["on_hit"] = {
        "name": "Blade of the Ruined King (on-hit)",
        "damage_type": "physical",
        "current_health_percent": pct,
        "min_damage": floor,
        "proc_cooldown": 0.0,
    }
    detail = (
        f"active thrust {active:.2f} + {second_strikes} mark-consuming second strike(s)"
    )
    if second_strikes > 0:
        detail += (
            f" ({second_damage:.2f} = 20% AD + 15% AP each); the passive "
            "%current-health on-hit rides every auto"
        )
    else:
        detail += (
            "; the passive %current-health on-hit rides every auto; set "
            "q_second_strike to price the mark-consuming second strike"
        )
    entry["detail"] = detail
    return entry


def _heartbreaker(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: the 120% AD base strike plus the live %missing-health bonus."""
    ranked = ctx.ranked("R")
    if ranked is None:
        return None
    ability, rank = ranked
    ad = float(ctx.stat("attack_damage"))
    base = _R_BASE_AD_RATIO * ad
    missing_pct = extract_value(ability, "Physical Damage", rank, 0)
    per_100_bad = extract_value(ability, "Physical Damage", rank, 1)
    bonus_ad = float(ctx.stat("bonus_attack_damage"))
    target_max = float(ctx.target_stat("target_max_health"))

    def missing_health_bonus(missing_ratio: float) -> float:
        return (
            (missing_pct / 100.0 + per_100_bad / 100.0 * bonus_ad / 100.0)
            * target_max
            * missing_ratio
        )

    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        base,
        "physical",
    )
    entry["parts"] = (
        # Both the 120% AD base strike and the live %missing-health bonus
        # land at the cast boundary: authored time_offset 0.0 upgrades the
        # dynamic part's events from cast_boundary to "hit" precision, so
        # the coverage classifier certifies the row instead of downgrading
        # it coarse (cast_boundary events are never exact).
        DamagePart("physical", base, time_offset=0.0),
        DamagePart("physical", hp_scaled_damage=missing_health_bonus, time_offset=0.0),
    )
    entry["detail"] = (
        f"{_R_BASE_AD_RATIO * 100:g}% AD base strike ({base:.2f}) + "
        f"{missing_pct}% (+ {per_100_bad}% per 100 bonus AD) of the "
        "target's missing health, evaluated at the strike"
    )
    return entry


# Q's thrust "deals physical damage to enemies hit" and its passive second
# strike only damages; Spectral Maw's mist "deals magic damage to the first
# enemy hit and stuns them for 0.25 : 1.25 (based on channel time) seconds";
# Heartbreaker "strikes the most wounded enemy champion nearby, dealing
# physical damage, slowing them by 99% for 0.25 seconds" — the slow is what
# lands on the target this module prices (the knockback is for the *other*
# nearby enemies).  E creates a mist trail and P is the possession
# mechanic; neither authors a damage part, so neither can carry a kind —
# E's attack-speed grant is a stat row, and P prices nothing at all.
MODULE_CC = {"Q": "none", "W": "stun", "R": "slow", "P": "none", "E": "none"}


@ranked_slot
def _harrowed_path(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """E: the 30-50% attack speed Viego holds while inside his own mist."""

    granted = extract_value(ability, "Bonus Attack Speed", rank)
    uptime = min(max(float(ctx.option("e_mist_uptime")), 0.0), 100.0) / 100.0
    bonus_as = granted * uptime
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
        f"+{granted:g}% bonus attack speed inside the mist at "
        f"{uptime * 100:g}% uptime ({bonus_as:g}% applied); the trail's "
        "movement speed and camouflage have no channel"
    )
    return entry


_harrowed_path.phase = BUFF

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Viego",
    PACKET_SHA256,
    single_hit_slots=frozenset({"W"}),
    slot_parsers={
        "E": _harrowed_path,
        "Q": with_item_on_hits(
            _blade_of_the_ruined_king, effectiveness=1.0, hits=1, triggers=("on_hit",)
        ),
        "R": with_item_on_hits(
            _heartbreaker, effectiveness=1.0, hits=1, triggers=("on_hit",)
        ),
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    *list(OPTIONS),
    int_option(
        "q_second_strike",
        0,
        minimum=0,
        maximum=20,
        label="Mark-consuming second strikes (Q passive)",
        rotation={
            "role": "self_state",
            "slot": "Q",
            "note": "Mark applied and consumed by Q's own passive autos "
            "(auto-stream self-consumed mark) — no cross-slot edge.",
        },
    ),
    int_option(
        "e_mist_uptime",
        100,
        minimum=0,
        maximum=100,
        label="Share of the fight Viego spends inside Harrowed Path (%)",
        rotation={
            "role": "self_state",
            "slot": "E",
            "note": "Positional uptime of E's own mist — self-state, with no "
            "cross-slot cast edge.",
        },
    ),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "Q's mark-consuming second strike needs a prior damaging ability and the next "
    "marked basic attack.",
    "That stateful rider is option-gated by this named module.",
    "Q (Blade of the Ruined King) prices the active Physical Damage row, 25 to 85 + "
    "70% AD.",
    "Its passive 2 to 6% current health on-hit, minimum 10 to 30, rides every auto.",
    "The mark-consuming second strike, 20% AD + 15% AP wiki prose, is q_second_strike "
    "(0 by default).",
    "R (Heartbreaker) prices the 120% AD base strike (wiki prose).",
    "It adds the %missing-health bonus row, 12/16/20% + 5% per 100 bonus AD, live at "
    "the strike.",
    "total_raw is the static base bound.",
    "E (Harrowed Path) grants the cached 30 to 50% Bonus Attack Speed while Viego "
    "stands in his mist.",
    "E's e_mist_uptime (default 100%) is that share of the fight.",
    "The trail lasts 8 seconds and E's cooldown falls to 6 by rank 5.",
    "The trail's bonus movement speed and camouflage have no engine channel.",
    "The possession/transform mechanic is inherently out of scope (E8d "
    "note): P stays an emitted zero-damage row.",
]

# P is emitted and grants nothing the engine prices — Possession assumes
# another champion's whole kit, which no axis expresses.
MODULE_COVERAGE = coverage(no_damage="P")
