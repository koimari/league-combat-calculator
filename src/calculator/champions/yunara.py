"""Yunara — CP10.10 full-entry-reviewed packet module.

Every basic attack carries Cultivation of Spirit's bonus magic damage, so
the kit is priced on the swing stream rather than as casts:

- P (Vow of the First Lands): every critical strike deals a share of its
  pre-mitigation damage again as magic, ``0.10 + 0.001 x AP`` (the binary
  ``YunaraPassive`` ``Calc_Damage_Amp``).  Declared as
  ``critical_strike_magic_ratio``; the auto simulation prices it on each
  crit, so a build with no crit chance pays nothing.
- Q passive (``Q_passive`` slot): the "Passive Bonus Magic Damage" row on
  every basic attack, an ordinary on-hit that Rageblade phantoms and
  spellblade re-application double.
- Q active (``Q`` slot): Unleash, the 5-second window (binary ``YunaraQ``
  ``Buff_Duration``) of "Bonus Attack Speed" whose swings carry the "Active
  Bonus Magic Damage" row as a second on-hit.  The window opens at the Q
  cast; one cast per fight, so the second Unleash a long fight would earn
  after re-stacking is not placed (ASSUMPTIONS).  The spread attacks hit
  OTHER enemies and are not priced against the single target.
- W (Arc of Judgment) prices the initial impact AND the lingering-bead
  DoT: the bead lingers for 1 second, ticking 4 times at 0.25-second
  intervals (the sourced "Linger Magic Damage per Tick" row x 4 == the
  "Total Expanded Damage" row; per-tick is 15% of the initial impact).
- R (Transcend One's Self) is a buff: the zero-damage R entry documents
  the Transcendent State, and ``r_transcendent`` (default False, the base
  form is the deterministic default, the Shyvana dragon-form convention)
  switches W to Arc of Ruin (base 160/320/480 by R rank + 120% bonus AD +
  75% AP) and keeps Unleash active for the whole state: the attack speed
  covers the fight and the on-hit reads the "Combined Bonus Magic Damage"
  row.  Exact for a fight that fits inside the 15-second state.
"""

from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import (
    calculation_coefficient,
    calculation_constant,
    data_value,
    spell_object,
)
from .engine import ONHIT, SlotCtx
from .module_helpers import (
    no_damage,
    ranked_slot,
    require_named_leveling,
    steroid_entry,
)
from .packet_module import build_packet_module
from .slot_entries import damage_entry, on_hit_entry
from .slot_extract import ability_name, extract_cooldown, extract_named

# HARDCODED: verify on patch updates — the linger cadence (4 ticks at
# 0.25s over the 1-second linger) is wiki W prose, reconciled by
# Total Expanded Damage / Linger Magic Damage per Tick == 4 at every
# rank.  Arc of Ruin's 120% bonus AD and 75% AP ratios live only in the
# cached W[1] description prose.
_W_LINGER_TICKS = 4
_W_LINGER_TICK_INTERVAL = 0.25
_YUNARA_P_SPELL = spell_object("Yunara", "YunaraPassive")
_YUNARA_Q_SPELL = spell_object("Yunara", "YunaraQ")
_YUNARA_R_SPELL = spell_object("Yunara", "YunaraR")
_P_CRIT_MAGIC_BASE = calculation_constant(_YUNARA_P_SPELL, "Calc_Damage_Amp")
_P_CRIT_MAGIC_PER_AP = calculation_coefficient(_YUNARA_P_SPELL, "Calc_Damage_Amp")
_Q_UNLEASH_DURATION = data_value(_YUNARA_Q_SPELL, "Buff_Duration")
_R_ARC_OF_RUIN_BONUS_AD_RATIO = data_value(_YUNARA_R_SPELL, "RW_ADRatio")
_R_ARC_OF_RUIN_AP_RATIO = data_value(_YUNARA_R_SPELL, "RW_APRatio")
_R_TRANSCENDENT_DURATION = data_value(_YUNARA_R_SPELL, "Buff_Duration")

_Q_PASSIVE_ROW = "Passive Bonus Magic Damage"
_Q_ACTIVE_ROW = "Active Bonus Magic Damage"
_Q_COMBINED_ROW = "Combined Bonus Magic Damage"
_Q_ATTACK_SPEED_ROW = "Bonus Attack Speed"

PACKET_SHA256 = "5ad671471e6280db293bcad126fc07d1f6a41c6f5916861a4a3b59278ea133be"


def _vow_of_the_first_lands(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: each critical strike deals a share of its damage again as magic."""
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
    ratio = _P_CRIT_MAGIC_BASE + _P_CRIT_MAGIC_PER_AP * float(ctx.stat("ability_power"))
    return {
        "name": ability_name(ability),
        "damage_type": "magic",
        "total_raw": 0.0,  # priced per critical strike by the fight engine
        "parts": (),
        "critical_strike_magic_ratio": ratio,
        "detail": (
            f"each critical strike deals {ratio * 100:.1f}% of its pre-mitigation "
            f"damage again as magic ({_P_CRIT_MAGIC_BASE * 100:g}% + "
            f"{_P_CRIT_MAGIC_PER_AP * 100 * 100:g}% per 100 AP)"
        ),
    }


_vow_of_the_first_lands.phase = ONHIT


def _q_row(ctx: SlotCtx, ability: dict[str, Any], row: str, rank: int) -> float:
    """One of Q's leveling rows at *rank*, failing loud when the cache lost it."""
    require_named_leveling("Yunara", ability, row)
    return extract_named(ability, row, rank, ctx.stats, ctx.target)


@ranked_slot
def _cultivation_of_spirit(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Q active: the Unleash attack-speed window and its second on-hit."""
    bonus_as = _q_row(ctx, ability, _Q_ATTACK_SPEED_ROW, rank)
    transcendent = bool(ctx.option("r_transcendent"))
    if transcendent:
        return steroid_entry(
            ability,
            rank,
            {"bonus_attack_speed": bonus_as},
            f"Transcendent State keeps Unleash active: +{bonus_as:g}% bonus attack "
            f"speed for the whole fight (the {_R_TRANSCENDENT_DURATION:g}s state), "
            "and the Q passive row prices the combined on-hit",
            dmg_type="magic",
        )
    active = _q_row(ctx, ability, _Q_ACTIVE_ROW, rank)
    return steroid_entry(
        ability,
        rank,
        {"bonus_attack_speed": bonus_as},
        f"Unleash: +{bonus_as:g}% bonus attack speed for {_Q_UNLEASH_DURATION:g}s "
        f"from the Q cast, and every swing inside the window deals {active:g} "
        "more bonus magic damage on-hit",
        dmg_type="magic",
        auto_attack_override={"active_duration": _Q_UNLEASH_DURATION},
        on_hit={
            "name": "Cultivation of Spirit (Unleash on-hit)",
            "damage_per_hit": active,
            "damage_type": "magic",
            "proc_window": _Q_UNLEASH_DURATION,
        },
    )


def _cultivation_passive(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q passive: bonus magic damage on every basic attack."""
    ranked = ctx.ranked("Q")
    if ranked is None:
        return None
    ability, rank = ranked
    transcendent = bool(ctx.option("r_transcendent"))
    row = _Q_COMBINED_ROW if transcendent else _Q_PASSIVE_ROW
    per_hit = _q_row(ctx, ability, row, rank)
    entry = on_hit_entry("Cultivation of Spirit (passive)", per_hit, "magic")
    entry["detail"] = f"{per_hit:g} bonus magic damage on every basic attack" + (
        " (Transcendent State: the passive and Unleash rows combined)"
        if transcendent
        else ""
    )
    return entry


_cultivation_passive.phase = ONHIT


@ranked_slot
def _arc_of_judgment(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """W: initial impact plus the 4 lingering-bead ticks (or Arc of Ruin)."""
    transcendent = bool(ctx.option("r_transcendent"))
    if transcendent:
        r_rank = ctx.rank_for("R")
        base = extract_named(
            ctx.ability("R", 0),
            "Arc of Ruin Base Damage",
            r_rank,
            ctx.stats,
            ctx.target,
        )
        bonus_ad = float(ctx.stat("bonus_attack_damage"))
        ap = float(ctx.stat("ability_power"))
        initial = (
            base
            + _R_ARC_OF_RUIN_BONUS_AD_RATIO * bonus_ad
            + _R_ARC_OF_RUIN_AP_RATIO * ap
        )
        name = "Arc of Ruin"
        linger_per_tick = 0.0  # Arc of Ruin is a beam; no linger beads
        linger_total = 0.0
        detail = (
            f"Transcendent State: Arc of Ruin base {base:g} (R rank {r_rank}) "
            f"+ 120% bonus AD + 75% AP"
        )
    else:
        initial = extract_named(
            ability, "Initial Magic Damage", rank, ctx.stats, ctx.target
        )
        linger_per_tick = extract_named(
            ability, "Linger Magic Damage per Tick", rank, ctx.stats, ctx.target
        )
        linger_total = extract_named(
            ability, "Total Expanded Damage", rank, ctx.stats, ctx.target
        )
        name = ability_name(ability)
        detail = (
            f"initial impact {initial:g} + {_W_LINGER_TICKS} linger ticks at "
            f"{_W_LINGER_TICK_INTERVAL:g}s intervals (total {linger_total:g})"
        )
    entry = damage_entry(
        name,
        rank,
        extract_cooldown(ability, rank),
        initial + linger_total,
        "magic",
    )
    parts: list[DamagePart] = [DamagePart("magic", initial, time_offset=0.0)]
    parts.extend(
        DamagePart(
            "magic",
            linger_per_tick,
            time_offset=index * _W_LINGER_TICK_INTERVAL,
        )
        for index in range(1, _W_LINGER_TICKS + 1)
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = detail
    return entry


@ranked_slot
def _transcend_one_self(
    ctx: SlotCtx, ability: dict[str, Any], _rank: int
) -> dict[str, Any] | None:
    """R: the Transcendent State buff shell (zero direct damage)."""
    return no_damage(
        ctx,
        name=ability_name(ability),
        reason=(
            f"Transcendent State ({_R_TRANSCENDENT_DURATION:g}s): a buff that "
            "keeps Unleash active and empowers W into Arc of Ruin; with "
            "r_transcendent=True the Q rows price the combined on-hit and the "
            "whole-fight attack speed, and the W row prices the empowered base "
            "160/320/480 by R rank + 120% bonus AD + 75% AP"
        ),
    )


# Arc of Judgment's initial hit "deals magic damage and slows them by 99%
# decaying over 1.5 seconds", and the Transcendent upgrade Arc of Ruin
# likewise "slows them by 99% decaying over 1 second" — one answer for both
# branches of ``r_transcendent``.  Cultivation of Spirit only adds bonus
# magic damage on-hit.  E is a dash, R is the Transcendent State buff shell
# and P is the crit bonus; none of the three authors a damage part.
MODULE_CC = {"Q": "none", "W": "slow", "P": "none", "E": "none", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Yunara",
    PACKET_SHA256,
    slot_parsers={
        "P": _vow_of_the_first_lands,
        "Q": _cultivation_of_spirit,
        "Q_passive": _cultivation_passive,
        "W": _arc_of_judgment,
        "R": _transcend_one_self,
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "P (Vow of the First Lands) rides each critical strike as a share of its "
    "pre-mitigation damage dealt again as magic (10% + 10% per 100 AP); a "
    "build with no critical strike chance pays nothing.",
    "Q's passive bonus magic damage is an on-hit on every basic attack, so "
    "Rageblade phantom hits and spellblade re-application apply it again.",
    "Q's active (Unleash) is placed once, at the Q cast, as a 5-second "
    "attack-speed window whose swings carry the active on-hit; the Unleash "
    "stacks a longer fight would rebuild for a second cast are not modeled, "
    "and the spread attacks (30% AD, 30% on-hit) hit other enemies, never "
    "the single target.",
    "W (Arc of Judgment) prices the initial impact plus 4 lingering-bead "
    "ticks at 0.25s intervals over the 1-second linger (Linger Magic "
    "Damage per Tick x 4 == Total Expanded Damage; per-tick is 15% of "
    "the initial impact).",
    "R (Transcend One's Self) is a buff, not direct damage: the zero-"
    "damage R entry documents the Transcendent State; r_transcendent "
    "(default False) switches W to the empowered Arc of Ruin (base "
    "160/320/480 by R rank + 120% bonus AD + 75% AP) and keeps Unleash "
    "active for the whole fight (exact up to the 15-second state).",
]
OPTIONS.append(
    {
        "key": "r_transcendent",
        "type": "bool",
        "default": False,
        "label": "R Transcendent State (Unleash stays active, W becomes Arc of Ruin)",
    }
)
