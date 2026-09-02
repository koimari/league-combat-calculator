"""Rakan — revision-backed offensive slot map.

Gleaming Quill and Grand Entrance each deal one magic-damage instance. The
Quickness damages each enemy at most once per cast, so every selected enemy
receives one hit. Fey Feathers and Battle Dance do not damage enemies.

E8d ally-support: Q (Gleaming Quill) heals Rakan and nearby allies (cached
Heal 40-230 by level + 55% AP; scope self_and_all_teammates) — the event is
authored by the engine's ally-support scanner from cached leveling at the Q
cast time.  E (Battle Dance) is a zero-damage cast so the scanner prices its
sourced ally shield (150.0 at rank 5, 0 AP); the free recast within 5
seconds re-applies it and is not modeled.

P (Fey Feathers) is ``modeled`` through the ``self_shield_events`` channel,
not through the scanner: the periodic self-shield (30 : 247.94 by level +
95% AP — 247.94 at level 18) rides the Q cast, which is the only channel a
shield-only passive has (a passive is never cast, so no packet can hang on
it).  The out-of-combat refresh cadence stays state.
"""

from typing import Any

from .. import healing_helpers as _healing
from .engine import build_parser
from .healing_contract import self_healing_rule
from .inputs import champion_stat
from .module_contract import coverage
from .slotlib import (
    attach_self_shield,
    extract_named,
    simple_damage,
    support_cast,
    with_control,
)
from .source_receipts import load_champion_sources

OPTIONS: list[dict[str, Any]] = []

ASSUMPTIONS = [
    "Gleaming Quill counts one enemy hit; its ally heal is excluded.",
    "Grand Entrance counts one completed landing hit.",
    "The Quickness counts one collision per selected enemy; one cast cannot "
    "damage an enemy twice.",
    "Battle Dance is excluded because it deals no enemy damage.",
    "Fey Feathers' periodic self-shield (30:247.94 by level + 95% AP) rides "
    "the first damaging cast (Q) as a timed shield for the fight window; "
    "the periodic/out-of-combat refresh cadence is state.",
    "Q (Gleaming Quill) emits an ally-only heal packet per cast (scope "
    "all_teammates, selection key heal:Q:<cast>) priced at the scanner's "
    "rank-indexed 80 + 55% AP while the champion rule owns the per-level "
    "self heal (40 : 230 based on level + 55% AP) — the self copy pays "
    "exactly once and the ally branch never double-grants it.",
    "P (Fey Feathers) has no standalone cast; its sourced self-shield "
    "(30:247.94 by level + 95% AP) is attached to Q (Gleaming Quill), "
    "this module's own parser, via attach_self_shield -- the Shen Ki "
    "Barrier precedent. The periodic/out-of-combat refresh cadence and "
    "the 'until broken' persistence beyond the fight window are state.",
    "E (Battle Dance)'s ally shield is sourced (Shield Strength "
    "50-150 + 70% AP, data/champions.json Rakan E) and its attribute "
    "name is already recognized by the generic ally-support scanner, "
    "but E is not yet wired: it has no SLOTS entry, so no E cast is "
    "ever scheduled onto the engine's cast_timeline (parse_abilities "
    "returns only Q/W/R today) and the scanner therefore never fires "
    "for it. The sourced 'free 5s recast, mimics the first cast' rule "
    "is also unmodeled second-cast timing. E stays out_of_scope.",
]

SOURCES = load_champion_sources("Rakan")

# HARDCODED: verify on patch updates — Fey Feathers' shield is the cached
# "Shield" per-level row (30 : 247.94 based on level) + 95% AP; the
# "until broken" shield is modeled as the fight window (E8c passive-shield
# convention).  The shield rides the first damaging cast (Q) so the shared
# ledger can grant it as a timed self-shield.
_P_SHIELD_BASE_LEVEL_1 = 30.0
_P_SHIELD_BASE_LEVEL_18 = 247.94
_P_SHIELD_AP_RATIO = 0.95
_P_SHIELD_DURATION_SECONDS = 10.0


def _p_shield_amount(level: int, ability_power: float) -> float:
    base = _P_SHIELD_BASE_LEVEL_1 + (
        _P_SHIELD_BASE_LEVEL_18 - _P_SHIELD_BASE_LEVEL_1
    ) * ((level - 1) / 17.0)
    return base + _P_SHIELD_AP_RATIO * ability_power


def _q_with_p_shield(ctx: Any) -> dict[str, Any] | None:
    entry = simple_damage(
        attr="Magic Damage",
        dmg_type="magic",
        event_order_certified="single_hit",
    )(ctx)
    if entry is None or int(entry.get("rank", 0) or 0) < 1:
        return entry
    shield = _p_shield_amount(ctx.level, ctx.stat("ability_power"))
    return attach_self_shield(
        entry,
        amount=shield,
        duration=_P_SHIELD_DURATION_SECONDS,
        source="Fey Feathers",
        detail=(
            f"Q cast also grants the periodic Fey Feathers self-shield "
            f"({shield:g} for {_P_SHIELD_DURATION_SECONDS:g}s, 30:247.94 "
            f"by level + 95% AP; until-broken modeled as the window)"
        ),
    )


SLOTS = {
    # Each of the three deals one magic-damage instance per enemy (the
    # module's own assumption above), so each certifies the cast boundary
    # its reviewed control rides on.
    "Q": _q_with_p_shield,
    "W": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": with_control(
        simple_damage(
            attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
        ),
        duration_attr="Disable Duration",
    ),
    # Battle Dance shields the target ally ("Rakan grants a shield to the
    # target allied champion for 3 seconds", cached "Shield Strength"
    # 50-150 + 70% AP).  The slot exists so the rotation casts it and the
    # support scanner can price the shield; the free recast within 5
    # seconds re-applies it and is not modeled.
    "E": support_cast(
        default_name="Battle Dance",
        detail="Ally shield (sourced by the support scanner); the free "
        "recast within 5s is not modeled.",
    ),
}

# Cached kit review.  Q's feather only "deals magic damage to the first
# enemy hit" before healing Rakan and his allies.  W "deals magic damage to
# nearby enemies and knocks them up for 1 second" — the "immobilizing"
# wording beside it is about Rakan being knocked down mid-dash, not about
# control he applies.  R "deals magic damage to enemies he collides with
# and charms and slows them by 75%": the charm is the immobilize the slow
# rides with.  P (a self-shield) and E (an ally shield and dash) damage
# nothing, so neither is declared: P is never cast, and E's slot exists
# only so the support scanner can price its ally shield.
MODULE_CC = {"Q": "none", "W": "knockup", "R": "charm", "E": "none"}

parse_abilities = build_parser(SLOTS, "Rakan", cc_kinds=MODULE_CC)

# P emits no cast row of its own — a passive is never cast — so the
# derivation would call it out_of_scope; the shield Q carries is what the
# engine prices (247.94 for 10s at level 18 with no items).
MODULE_COVERAGE = coverage()
COVERAGE_CHANNELS = {"P": ("self_shield_events",)}


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Resolve Rakan self-healing events from its authored packet."""
    healing = []
    level = max(1, int(champion_stat(champion_stats, "level")))
    heal = extract_named(
        _healing.ability_json(champion_data, "Q"), "Heal", level, champion_stats
    )
    if heal > 0.0:
        for payment in _healing.payments(
            _healing.HealAnchor.CAST, "Q", damage_events, cast_timeline
        ):
            event = payment.event
            healing.append(
                {
                    "time": float(event.get("time", 0.0)) + 3.0,
                    "amount": heal,
                    "source": "Gleaming Quill",
                    "kind": "champion_ability",
                    "actor_wide": True,
                }
            )
    return healing


SELF_HEALING_RULE = self_healing_rule("Rakan")(derive_self_healing)
