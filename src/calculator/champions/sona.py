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

E (Song of Celerity) is ``no_damage``: movement only, with no
enemy-damage clause anywhere in the slot.  The movement half IS priced,
because ``slotlib``'s ``stat_buff`` dispatch carries the key it needs:
``move_speed_percent`` is a term in the shared ``resolve_move_speed``
fold (``damage._apply_stat_buff_ultimates``), published by Teemo W,
Seraphine W, Sivir R, Naafiri W, Udyr E and Singed.  Seraphine W is the
same grant shape to the digit (20% + 2% per 100 AP, self half published,
ally half withheld), so E follows that wiring: the self grant is
published time-weighted over the fight window through
``buff_window_share``, and the ranked ally half (Melody Bonus
10/12/14/16/18%) is withheld for want of a teammate the parse can see.
"""

import re
from typing import Any

from ..healing_helpers import ability_json, parsed_rank
from .engine import CC_PER_PART, ONHIT, SlotCtx
from .healing_contract import self_healing_rule
from .inputs import int_option
from .module_contract import coverage
from .module_helpers import buff_window_share
from .packet_module import build_packet_module
from .slotlib import ability_name, extract_named, on_hit_entry

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


# Song of Celerity's SELF grant has no leveling row of any kind — the
# active's whole magnitude and both of its windows are one cached
# sentence, so the sentence is read rather than copied (the Shyvana-P
# shape).  Only the ranked ALLY row ("Melody Bonus", 10/12/14/16/18 +
# 2% per 100 AP) is a leveling row, and that half has no 1v1 channel.
_E_ACTIVE_MARKER = "bonus movement speed"
_E_GRANT_RE = re.compile(
    r"Sona gains\s+(?P<base>\d+(?:\.\d+)?)%\s*\(\+\s*"
    r"(?P<per_100_ap>\d+(?:\.\d+)?)%\s*per 100 AP\)\s*bonus movement speed"
    r"\s*for\s+(?P<undisturbed>\d+(?:\.\d+)?)\s*seconds",
    re.IGNORECASE,
)
_E_DAMAGED_WINDOW_RE = re.compile(
    r"If she takes damage during this time.*?"
    r"(?P<damaged>\d+(?:\.\d+)?)\s*seconds have elapsed",
    re.IGNORECASE | re.DOTALL,
)


def _celerity_grant(ability: dict[str, Any] | None) -> tuple[float, float, float]:
    """E's self grant: ``(base %, % per 100 AP, damaged window seconds)``.

    Both windows are stated in the same sentence — 7 seconds undisturbed,
    cut to 3 once she takes damage.  A modelled fight is by construction a
    state in which she takes damage, so the DAMAGED window is the one this
    surface can source; it is also the shorter of the two, so reading it
    can only understate the grant, never overstate it.  This is the same
    call Teemo W makes when it refuses the passive branch whose
    "5 seconds without taking damage" condition a fight never satisfies.
    """
    # Direct indexing: a cache-shape break raises KeyError loudly here
    # rather than falling through silently (the loop's own fail-closed
    # raise below still guards the no-match case).
    for effect in ability["effects"]:
        text = str(effect["description"])
        if _E_ACTIVE_MARKER not in text:
            continue
        grant = _E_GRANT_RE.search(text)
        window = _E_DAMAGED_WINDOW_RE.search(text)
        if grant is None or window is None:
            continue
        return (
            float(grant.group("base")),
            float(grant.group("per_100_ap")),
            float(window.group("damaged")),
        )
    raise ValueError(
        "Sona E (Song of Celerity): the cached active no longer states "
        "'Sona gains <n>% (+ <n>% per 100 AP) bonus movement speed for <n> "
        "seconds' together with the damaged window '<n> seconds have "
        "elapsed' — the self grant cannot be sourced"
    )


def _song_of_celerity(packet_e):
    """E: movement only — a sourced zero-enemy-damage row.

    Replaces the packet's generic "no enemy-damage formula" stub with the
    sourced grant, published as a ``move_speed_percent`` stat buff (the
    Teemo-W / Seraphine-W wiring).  Only Sona's own half is published: the
    ranked Melody Bonus goes to tagged allied champions, which the 1v1
    surface has no room for.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_e(ctx)
        if entry is None:
            return None
        base, per_100_ap, window = _celerity_grant(ctx.ability())
        granted = base + per_100_ap * (float(ctx.stat("ability_power") or 0.0) / 100.0)
        # The cast expires, and a stat_buff is one scalar for the whole
        # fight, so the grant lands time-weighted by the share of the
        # window it covers (module_helpers.buff_window_share).
        published = granted * buff_window_share(ctx, window)
        entry["stat_buff"] = {"move_speed_percent": published}
        entry["detail"] = (
            f"Movement only: the cast's own {base:g}% "
            f"(+ {per_100_ap:g}% per 100 AP) grant ({granted:g}% at this "
            f"build, {published:g}% over the fight window at the sourced "
            f"{window:g}s damaged duration) is published as a "
            "move_speed_percent stat buff, a term in the shared "
            "movement-speed fold. The ranked Melody Bonus to tagged allies "
            "is not published: it needs allied champions."
        )
        return entry

    return parse


# Reviewed crowd control, read from the cached kit.  Q (Hymn of Valor)
# "sends out bolts of sound to the two nearest visible enemies ... Each
# bolt deals magic damage" and applies no control (Power Chord's Tempo
# slow is the passive's empowered attack, not Q).  R (Crescendo) "deals
# magic damage to enemies hit and stuns them for 1.5 seconds".  W and E
# deal no damage, so they carry no reviewable control.
MODULE_CC = {"Q": "none", "R": "stun", "P": CC_PER_PART, "W": "none", "E": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Sona",
    PACKET_SHA256,
    # One bolt on the duel's single target, one chord: each packet is one
    # part and one hit, so the reviewed answer reaches the event ledger.
    single_hit_slots=frozenset({"Q", "R"}),
    slot_parsers={"P": _power_chord},
    slot_wrappers={"E": _song_of_celerity},
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    *list(OPTIONS),
    int_option(
        "p_power_chords",
        _POWER_CHORDS_PER_ROTATION,
        minimum=0,
        maximum=10,
        label="Power Chords landed",
    ),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
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
    "E (Song of Celerity) deals no damage; its SELF grant (20% + 2% per "
    "100 AP) is published as a move_speed_percent stat buff, a term in "
    "the shared resolve_move_speed fold (soft caps included), "
    "time-weighted by buff_window_share over the sourced window: a "
    "stat_buff is one scalar for the whole fight, so an unweighted term "
    "would read the same in a 5s fight and a 30s one. The grant and both "
    "of its windows are cached PROSE with no leveling row of any kind, so "
    "the sentence is READ (no module literal, the Shyvana-P shape) and a "
    "sentence that stops stating them raises. The DAMAGED window (3s) is "
    "the one priced, not the undisturbed 7s: a modelled fight is a state "
    "in which she takes damage, and the shorter window can only "
    "understate the grant — the same call Teemo W makes against its own "
    "5s-undamaged passive branch. The ranked Melody Bonus "
    "(10/12/14/16/18% + 2% per 100 AP) is NOT published: it goes to "
    "tagged allied champions, which the 1v1 surface has no room for.",
]
MODULE_COVERAGE = coverage(no_damage="E")


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
    return [
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


SELF_HEALING_RULE = self_healing_rule("Sona")(derive_self_healing)
