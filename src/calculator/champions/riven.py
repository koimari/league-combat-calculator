"""Riven: full-entry-reviewed packet module.

P (Runic Blade) is an on-hit entry: each empowered basic attack consumes a stack
for bonus physical damage worth 30 to 46.76% of AD by level, and the row
declares the crit clause the cached row states.  Its 100% life-steal
effectiveness is a healing axis an on-hit row does not carry.
R (Blade of the Exile) is two things.  The R1 active is a BUFF-phase stat entry
granting a flat 20% of her BONUS attack damage at every rank, sourced from the
game file rather than the ranked wiki row, so every later physical slot scales
off the buffed AD; the amount is factored at the cast and does not change.  The
R2 Wind Slash is the ultimate's own damage.
E (Valor) is ``no_damage``: both cached effects are self-directed, its "Shield
Strength" row being the dash's own defensive shield.
"""

from typing import Any

from ..binary_roots import data_value, spell_object
from .engine import BUFF, ONHIT, SlotCtx
from .module_helpers import ability_slot
from .packet_module import build_packet_module
from .slot_entries import damage_entry, on_hit_entry
from .slot_extract import ability_name, extract_cooldown, extract_named

PACKET_SHA256 = "efecdb1959bc6c813777c1d4cf4f8b8befcb4d93093c291c8cf973464d2226b8"


# Both rooted in the binary (RivenFengShuiEngine PercentBonusAD /
# Duration DataValues); wiki patch history ("reduced to 20% bonus AD
# from 25%") and the R prose ("empowers her blade for 15 seconds")
# corroborate.
_RIVEN_R_SPELL = spell_object("Riven", "RivenFengShuiEngine")
_R_BONUS_AD_RATIO = data_value(_RIVEN_R_SPELL, "PercentBonusAD")
_R_BUFF_DURATION = data_value(_RIVEN_R_SPELL, "Duration")

# Runic Blade's own cached sentence: "The bonus damage is affected by
# critical strike modifiers and applies life steal at 100% effectiveness"
# (P effect 1) — full crit probability, which is what this key scales.
_RUNIC_BLADE_CRIT_EFFECTIVENESS = 1.0


def _blade_of_the_exile(ctx: SlotCtx) -> dict[str, Any] | None:
    """R1: +20% of bonus AD as bonus AD for 15s (BUFF phase).

    Runs before every damage slot, so Q/W/R all scale off the buffed
    bonus AD within the ult window.  The amount is snapshot at cast
    ("factored upon cast, and does not change" — cached R[0] notes).
    """
    ranked = ctx.ranked("R", 0)
    if ranked is None:
        return None
    ability, rank = ranked
    value = _R_BONUS_AD_RATIO * float(ctx.stat("bonus_attack_damage") or 0.0)
    ctx.stats["attack_damage"] = float(ctx.stat("attack_damage") or 0.0) + value
    ctx.stats["bonus_attack_damage"] = (
        float(ctx.stat("bonus_attack_damage") or 0.0) + value
    )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
    )
    entry["stat_buff"] = {"bonus_attack_damage": value}
    entry["detail"] = (
        f"+{value:g} bonus attack damage ({_R_BONUS_AD_RATIO * 100:g}% of "
        f"bonus AD) for {_R_BUFF_DURATION:g}s; the Wind Slash is priced "
        "by the R slot"
    )
    return entry


_blade_of_the_exile.phase = BUFF


@ability_slot("P")
def _runic_blade(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """P: empowered basic attacks deal per-level % AD bonus physical damage."""
    percent = extract_named(
        ability, "Per-Level Scaling", ctx.level, ctx.stats, ctx.target
    )
    per_hit = float(ctx.stat("attack_damage") or 0.0) * percent / 100.0
    return on_hit_entry(
        ability_name(ability),
        per_hit,
        "physical",
        crit_effectiveness=_RUNIC_BLADE_CRIT_EFFECTIVENESS,
    )


_runic_blade.phase = ONHIT


# Cached kit review.  W "deal[s] physical damage to nearby enemies and
# stun[s] them for 0.75 seconds", and R's Wind Slash only damages.  Q is
# the priced *per-cast* slash ("Physical Damage", the row each of the three
# casts deals), which "deal[s] physical damage to enemies struck within an
# area" and applies nothing; only the third cast adds a 75-unit knock back,
# and this module prices one slash rather than that specific one.  E deals
# no damage, P is an on-hit rider on the auto stream, and R_buff is the AD
# steroid with a zero-damage row, so none of the three carries an event.
MODULE_CC = {"Q": "none", "W": "stun", "R": "none", "P": "none", "E": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Riven",
    PACKET_SHA256,
    # Each priced row is one blow: the packet's Q is a single Broken Wings
    # slash ("Physical Damage" 45 : 165, not the three-cast total), Ki
    # Burst is one flash and Wind Slash one wave — the boundary claim that
    # carries MODULE_CC's reviewed answers into the event ledger.
    single_hit_slots=frozenset({"Q", "W", "R"}),
    slot_parsers={
        "R_buff": _blade_of_the_exile,
        "P": _runic_blade,
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "P (Runic Blade) prices the cached per-level AD ratio: 30% to 46.76% by level AD "
    "on an empowered auto.",
    "One stack is banked per auto, from the cached P Per-Level Scaling row.",
    "Runic Blade's bonus is affected by critical strike modifiers (cached P effect).",
    "The on-hit row declares crit_effectiveness 1.0, priced at the fight's crit "
    "chance and multiplier.",
    "The same sentence's 100% life-steal effectiveness is a healing axis the row does "
    "not carry.",
    "R1 (Blade of the Exile) prices the AD steroid: +20% of bonus AD for 15s, "
    "factored at the cast.",
    "riven.bin.json PercentBonusAD is a flat 0.20 at every rank.",
    "Wind Slash stays priced by the R slot and scales off the buffed AD.",
    "E (Valor) has no enemy-damage formula: both cached effects are self-directed.",
    "Those are the 70 to 170 + 110% bonus AD shield for 1.5s on a no-damage dash and "
    "the cast-during note.",
    "E emits the sourced zero-damage row while the scanner prices the Valor shield, "
    "so the slot is modeled.",
]
