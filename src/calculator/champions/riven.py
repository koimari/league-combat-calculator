"""Riven — CP10.6 full-entry-reviewed packet module.

E5-2 fix — Runic Blade (P): the reviewed packet declared the passive
no_damage, but the wiki carries a sourced formula: "Riven's basic
attacks are empowered to each consume a stack to deal bonus physical
damage equal to 30% : 46.76% (based on level) AD" (data/champions.json
P "Per-Level Scaling" [0], 30-46.76% AD; the second row is the 50%
structure-reduced share).  The passive is an on-hit entry priced at
``AD x per-level% / 100`` per empowered auto, declaring the crit clause
the cached row states (``_RUNIC_BLADE_CRIT_EFFECTIVENESS``).  The 100%
life-steal effectiveness is a healing axis the on-hit row does not carry.

P1-3 fix — Blade of the Exile (R1): the reviewed R slot priced only
the Wind Slash.  The R1 active buffs Riven for 15 seconds with bonus
attack damage; the current game file sources it as a flat 20% of her
BONUS attack damage at every rank (riven.bin.json RivenFengShuiEngine
PercentBonusAD 0.20 x bonus AD; wiki patch history: "Blade of the
Exile: Bonus attack damage ratio reduced to 20% bonus AD from 25%";
the cached R[0] description reads "gaining 20% AD bonus attack
damage").  The buff is a BUFF-phase stat entry (the Aatrox R
precedent) so every later physical slot (Q/W/R) scales off the buffed
AD; the amount is factored at cast and does not change (wiki note).

Roadmap session 4 batch F (2026-08-21): E (Valor) is a mobility dash
plus a self shield, with no enemy-damage formula. Both cached E
effects (data/champions.json) are self-directed: effect 0's "Shield
Strength" leveling row is the dash's own defensive shield, effect 1 is
the cast-during-dash utility note — already documented below as
"outside the packet's damage model." The pinned reviewed packet
(static/reviewed-packets.json) independently declares E ``kind:
"no_damage"`` with a sourced reason, and E is not overridden away from
``build_packet_module``'s cast slots (only P and R_buff are reassigned
below), so it already emits the packet's sourced zero-damage row today
— MODULE_COVERAGE was simply stale, still reading "out_of_scope" for
an already-covered slot (the Malzahar/Nasus precedent, roadmap session
4 batch D). Reclassified to "no_damage"; zero fight-computation change.
"""

from ..binary_roots import data_value, spell_object
from .engine import BUFF, ONHIT, SlotCtx
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
)

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


def _blade_of_the_exile(ctx: SlotCtx):
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


def _runic_blade(ctx: SlotCtx):
    """P: empowered basic attacks deal per-level % AD bonus physical damage."""
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
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
MODULE_CC = {"Q": "none", "W": "stun", "R": "none"}

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
    "P (Runic Blade) prices the wiki's per-level AD ratio: empowered "
    "basic attacks deal bonus physical damage equal to 30% : 46.76% "
    "(based on level) AD, one stack per auto (data/champions.json P "
    "'Per-Level Scaling' [0]).",
    "Runic Blade's bonus damage 'is affected by critical strike "
    "modifiers' (cached P effect 1), so the on-hit row declares "
    "crit_effectiveness=1.0 and the engine prices it at the fight's own "
    "crit chance and multiplier.  The same sentence's 100% life-steal "
    "effectiveness is a healing axis the row does not carry.",
    "R1 (Blade of the Exile) prices the AD steroid: +20% of bonus AD "
    "as bonus AD for 15s (riven.bin.json PercentBonusAD 0.20 x bonus "
    "AD, flat at all ranks — the retired 20/25/30% rank array was "
    "patched to a flat 20% bonus AD), factored at cast; the Wind Slash "
    "stays priced by the R slot and now scales off the buffed AD.",
    "E (Valor) has no enemy-damage formula: both cached effects are "
    "self-directed — the 70-170 + 110% bonus AD shield for 1.5s on a "
    "no-damage dash, and the cast-during-dash utility note — which the "
    "pinned reviewed packet confirms with kind='no_damage' for E. E is "
    "a cast slot here: it emits that sourced zero-damage row while the "
    "support scanner prices its Valor shield, so the slot is modeled.",
]
