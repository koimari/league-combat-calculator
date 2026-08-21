"""Rakan — revision-backed offensive slot map.

Gleaming Quill and Grand Entrance each deal one magic-damage instance. The
Quickness damages each enemy at most once per cast, so every selected enemy
receives one hit. Fey Feathers and Battle Dance do not damage enemies.

E8d ally-support: Q (Gleaming Quill) heals Rakan and nearby allies (cached
Heal 40-230 by level + 55% AP; scope self_and_all_teammates) — the event is
authored by the engine's ally-support scanner from cached leveling at the Q
cast time.  P (Fey Feathers) is a passive periodic self-shield (cached
Shield 30-247.94 by level + 95% AP); it is authored directly by this
module (``_q_with_p_shield`` below, the Shen Ki Barrier precedent), not
by the ally-support scanner.

Roadmap session (2026-08-21): closes one of Rakan's two out_of_scope
slots (P); E stays open with a named receipt.

  - P (Fey Feathers): not a damage gap but a stale label. The shield IS
    already computed and emitted — ``_q_with_p_shield`` attaches it to
    every Q cast via ``attach_self_shield`` (the sourced 30:247.94 by
    level + 95% AP row, riding Q exactly as Shen's Ki Barrier rides E).
    ``MODULE_COVERAGE`` read "out_of_scope" only because P has no
    standalone top-level SLOTS entry of its own — the label was stale,
    not the calculation. Reclassified to modeled (the Shen-P precedent:
    a self-shield authored inside another slot's own parser counts as
    modeled, not no_damage/out_of_scope).
  - E (Battle Dance): the shield IS sourced (cached "Shield Strength"
    50/75/100/125/150 + 70% AP, data/champions.json Rakan E) and its
    attribute name is already recognized by the generic ally-support
    scanner (``support_effects._SUPPORT_ATTRIBUTES`` includes "Shield
    Strength"). It stays out_of_scope because the scanner keys strictly
    off ``cast_timeline`` slot entries built from THIS module's own
    ``parse_abilities`` output (``derive_ally_effects`` filters
    ``event.get("slot") == slot`` against the engine's cast timeline,
    not against raw champion_data) — and E has no SLOTS entry, so no E
    cast is ever scheduled (confirmed: ``parse_champion_abilities``
    returns exactly ``{"Q", "W", "R"}`` for Rakan today, pinned by
    ``tests/test_rakan.py::test_rakan_rotation_counts_each_enemy_damage_cast_once``).
    Wiring E therefore needs (a) a new "E" SLOTS entry (a ``no_damage``
    row, the Kai'Sa-E/Shen-W precedent) so E gets a cast and a
    cast_timeline slot, which changes the published ability count and
    is captured verbatim by ``scripts/golden_snapshot.py`` and the
    pinned ability-set test above, and (b) the sourced "free 5s recast"
    ("Battle Dance can be recast within 5 seconds at no additional
    cost... mimics the first cast's effects") is a second-cast timing
    rule this engine has no existing convention for (unlike Shen's E,
    which is a single dash) — both are real, in-scope-eventually work
    this session's stale-label cadence does not cover. Stays
    out_of_scope with this receipt (the Kai'Sa-R precedent) for
    whichever session next owns the SLOTS + recast wiring.
"""

from typing import Any

from .engine import build_parser
from .slotlib import attach_self_shield, simple_damage, with_control

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

SOURCES = [
    {
        "label": "Fey Feathers",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Rakan/Fey_Feathers",
        "revision_id": 4016025,
        "revision_timestamp": "2026-05-08T17:35:55Z",
    },
    {
        "label": "Gleaming Quill",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Rakan/Gleaming_Quill",
        "revision_id": 3996425,
        "revision_timestamp": "2026-03-04T16:52:28Z",
    },
    {
        "label": "Grand Entrance",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Rakan/Grand_Entrance",
        "revision_id": 4007760,
        "revision_timestamp": "2026-04-12T14:15:53Z",
    },
    {
        "label": "Battle Dance",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Rakan/Battle_Dance",
        "revision_id": 4008001,
        "revision_timestamp": "2026-04-13T02:59:27Z",
    },
    {
        "label": "The Quickness",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Rakan/The_Quickness",
        "revision_id": 3971183,
        "revision_timestamp": "2025-12-02T06:20:48Z",
    },
]

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
    entry = simple_damage(attr="Magic Damage", dmg_type="magic")(ctx)
    if entry is None or int(entry.get("rank", 0) or 0) < 1:
        return entry
    shield = _p_shield_amount(ctx.level, ctx.stats.get("ability_power", 0.0))
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
    "Q": _q_with_p_shield,
    "W": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "R": with_control(
        simple_damage(attr="Magic Damage", dmg_type="magic"),
        kind="charm",
        duration_attr="Disable Duration",
    ),
}

parse_abilities = build_parser(SLOTS, "Rakan")


# Authoritative review metadata (issue #161).
MODULE_COVERAGE = {
    "P": "modeled",
    "Q": "modeled",
    "W": "modeled",
    "E": "out_of_scope",
    "R": "modeled",
}
REVIEW_STATUS = "reviewed_module"

from .. import healing_helpers as _healing  # pylint: disable=wrong-import-position


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument,wrong-import-position
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Rakan self-healing events from its authored packet."""
    healing = []
    level = max(1, int(champion_stats.get("level", 18) or 18))
    heal = _healing.extract_named(
        _healing._ability(champion_data, "Q"), "Heal", level, champion_stats
    )
    if heal > 0.0:
        for event in _healing._attributed_events(
            damage_events, lambda source, _event: source == "Q"
        ):
            healing.append(
                {
                    "time": float(event.get("time", 0.0)) + 3.0,
                    "amount": heal,
                    "source": "Gleaming Quill",
                    "kind": "champion_ability",
                    "actor_wide": True,
                }
            )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Rakan", derive_self_healing)
