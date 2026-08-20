"""Sona — CP10.8 full-entry-reviewed packet module.

E8d ally-support: W (Aria of Perseverance) heals and shields the caster and
one selected teammate.  The event is authored by the engine's ally-support
scanner from the cached W leveling (Heal 30-90 + 30% AP; Shield Strength
25-105 + 25% AP; scope self_and_one_teammate) at the W cast time; the module
declares W in SLOTS so the fight rotation casts it.

P (Power Chord) is ``modeled``: the sourced chord (240.0 bonus magic damage
at level 18, 0 AP) rides the attack three basic abilities empower.

E (Song of Celerity) stays ``out_of_scope`` on the movement-speed axis,
which ``slotlib``'s ``stat_buff`` dispatch has no key for.
"""

from typing import Any

from .engine import ONHIT, SlotCtx
from .healing_contract import declare_healing_rule
from .packet_module import build_packet_module
from .slotlib import extract_named, on_hit_entry

PACKET_SHA256 = "c78392f6b8f667c85594d31be2e6a9c1b7c6504d5cd02e3c5b385271dafc6c06"

# Power Chord fires once every three basic abilities, and Sona has exactly
# three (Q, W, E), so one rotation is worth one chord — the default.
_POWER_CHORDS_PER_ROTATION = 1


def _power_chord(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the Power Chord bonus on the attack three basic abilities empower."""
    ability = ctx.ability()
    if ability is None:
        return None
    # The FIRST "Per-Level Scaling" row is the unmodified chord (20 : 270);
    # the second is Staccato, which only the Hymn of Valor tag applies.  The
    # module's rotation ends its basic abilities on Tempo (E), which modifies
    # movement speed rather than the chord's damage, so the base row is the
    # one this cast order fires.
    per_chord = extract_named(
        ability, "Per-Level Scaling", ctx.level, ctx.stats, ctx.target, level=ctx.level
    ) + 0.20 * float(ctx.stat("ability_power") or 0.0)
    if per_chord <= 0:
        return None
    chords = max(0, int(ctx.option("p_power_chords")))
    entry = on_hit_entry(ability.get("name", "Power Chord"), per_chord, "magic")
    entry["on_hit"]["max_procs"] = chords
    entry["detail"] = (
        f"{chords} Power Chord(s) of {per_chord:.2f} bonus magic damage "
        "(20 : 270 based on level + 20% AP), one per three basic abilities; "
        "the Staccato / Diminuendo / Tempo tag riders are not applied"
    )
    return entry


_power_chord.phase = ONHIT

# Reviewed crowd control, read from the cached kit.  Q (Hymn of Valor)
# "sends out bolts of sound to the two nearest visible enemies ... Each
# bolt deals magic damage" and applies no control (Power Chord's Tempo
# slow is the passive's empowered attack, not Q).  R (Crescendo) "deals
# magic damage to enemies hit and stuns them for 1.5 seconds".  W and E
# deal no damage, so they carry no reviewable control.
MODULE_CC = {"Q": "none", "R": "stun"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Sona",
    PACKET_SHA256,
    # One bolt on the duel's single target, one chord: each packet is one
    # part and one hit, so the reviewed answer reaches the event ledger.
    single_hit_slots=frozenset({"Q", "R"}),
    slot_parsers={"P": _power_chord},
    cc_kinds=MODULE_CC,
)

OPTIONS = list(OPTIONS) + [
    {
        "key": "p_power_chords",
        "type": "int",
        "default": _POWER_CHORDS_PER_ROTATION,
        "min": 0,
        "max": 10,
        "label": "Power Chords landed",
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Power Chord) prices the sourced unmodified chord (20 : 270 based on "
    "level + 20% AP) once per three basic abilities (selectable); the "
    "Staccato / Diminuendo / Tempo riders the last-cast tag adds are not "
    "applied, and Accelerando's ability haste is unpriced.",
]
MODULE_COVERAGE = {
    slot: ("out_of_scope" if slot == "E" else "modeled") for slot in "PQWER"
}

SELF_HEALING_RULE = declare_healing_rule("Sona")
