"""Sona — CP10.8 full-entry-reviewed packet module.

E8d ally-support: W (Aria of Perseverance) heals and shields the caster and
one selected teammate.  The heal is authored once by ``derive_self_healing``
below (the self copy plus the fan-out clone to the selected teammate under
the ``heal:W:<cast>`` selection key, "heals herself and sends out a tone to
heal the most wounded allied champion nearby") and the Melody shield stays
scanner-owned under ``shield:W:<cast>``, read from the cached W leveling
(Heal 30-90 + 30% AP; Shield Strength 25-105 + 25% AP; scope
self_and_one_teammate) at the W cast time; both packets expose independent
roster selection keys, and the deterministic roster model treats the
selected teammate as the "most wounded" target.  The module declares W in
SLOTS so the fight rotation casts it.

P (Power Chord) is ``modeled``: the sourced chord (240.0 bonus magic damage
at level 18, 0 AP) rides the attack three basic abilities empower.

E (Song of Celerity) stays ``out_of_scope`` on the movement-speed axis,
which ``slotlib``'s ``stat_buff`` dispatch has no key for.
"""

from typing import Any

from ..healing_helpers import ability_json, parsed_rank
from .engine import ONHIT, SlotCtx
from .healing_contract import self_healing_rule
from .packet_module import build_packet_module
from .slotlib import ability_name, extract_named, on_hit_entry
from .inputs import int_option
from .module_contract import coverage

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
    entry = on_hit_entry(ability_name(ability), per_chord, "magic")
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
    int_option(
        "p_power_chords",
        _POWER_CHORDS_PER_ROTATION,
        minimum=0,
        maximum=10,
        label="Power Chords landed",
    ),
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Power Chord) prices the sourced unmodified chord (20 : 270 based on "
    "level + 20% AP) once per three basic abilities (selectable); the "
    "Staccato / Diminuendo / Tempo riders the last-cast tag adds are not "
    "applied, and Accelerando's ability haste is unpriced.",
    "W (Aria of Perseverance) heals the caster and the selected teammate "
    "the sourced Heal (30-90 + 30% AP) via the E1-rule fan-out "
    "(heal:W:<cast> key) and shields the caster and the same selected "
    "teammate the sourced Melody Shield Strength (25-105 + 25% AP) for "
    "1.5s (shield:W:<cast> key); the in-game 'most wounded allied "
    "champion nearby' selection is the explicit roster teammate choice.",
]
MODULE_COVERAGE = coverage(out_of_scope="E")


# pylint: disable=too-many-arguments,too-many-positional-arguments
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Price Aria of Perseverance: the sourced Heal row, once per W cast.

    The heal is paid on the cast — "heals herself and sends out a tone to
    heal the most wounded allied champion nearby" — so it rides the cast
    timeline and declares its own fan-out scope; the roster's selected
    teammate stands in for the most wounded ally.
    """
    del damage_events, fight_duration_seconds
    heal = extract_named(
        ability_json(champion_data, "W"),
        "Heal",
        parsed_rank(ability_damages, "W"),
        champion_stats,
    )
    if heal <= 0.0:
        return []
    healing = [
        {
            "time": float(cast.get("time", 0.0)),
            "amount": heal,
            "source": "Aria of Perseverance",
            "kind": "champion_ability",
            "actor_wide": True,
            "target_scope": "self_and_one_teammate",
            "_event_id": f"sona:w:{cast_index}",
        }
        for cast_index, cast in enumerate(cast_timeline or [])
        if cast.get("slot") == "W"
    ]
    return healing


SELF_HEALING_RULE = self_healing_rule("Sona")(derive_self_healing)
