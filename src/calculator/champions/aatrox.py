"""Aatrox — slot map for the archetype engine.

Why each slot is non-generic:
- R (World Ender) grants bonus AD as a PERCENTAGE of total AD — a
  ``stat_buff`` in percent_of mode (BUFF phase, so Q/W scale off the
  buffed AD).
- Q (The Darkin Blade) is three sequential casts with individually
  named damage attributes; ``_darkin_blade`` sums the sweetspot or
  normal triad selected by the ``sweetspot`` option.
- W (Infernal Chains) hits twice — the "Total Damage" attribute
  (initial + pull-back combined) instead of the single-hit
  "Physical Damage" the classifier would find.
- P (Deathbringer Stance) is on-hit magic damage as a per-LEVEL
  percentage of target max health — champion-local ``_deathbringer_stance``.
- E (Umbral Dash) is a dash with healing amp only — no damage, absent
  from the slot map.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

import re
from typing import Any

from .engine import ONHIT, SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
    pct_health_per_hit,
    simple_damage,
    stat_buff,
)
from ..healing_legacy import (
    _ability,
    _attributed_events,
    _is_persistent,
    _leveling_value,
    _trigger_fields,
)

_Q_SWEETSPOT_ATTRS = [
    "First Sweetspot Damage",
    "Second Sweetspot Damage",
    "Third Sweetspot Damage",
]
_Q_NORMAL_ATTRS = [
    "First Cast Damage",
    "Second Cast Damage",
    "Third Cast Damage",
]


def _darkin_blade(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: sum all three sweetspot or normal casts into one entry."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    attrs = (
        _Q_SWEETSPOT_ATTRS
        if bool(ctx.options.get("sweetspot", True))
        else _Q_NORMAL_ATTRS
    )
    total = sum(
        extract_named(ability, attr, rank, ctx.stats, ctx.target) for attr in attrs
    )
    return damage_entry(
        ability.get("name", "The Darkin Blade"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )


def _deathbringer_stance(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: per-level target-max-health on-hit damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    per_hit = pct_health_per_hit(
        ability,
        "Max Health Damage",
        ctx.level,
        ctx.target,
    )
    if per_hit is None:
        return None
    return on_hit_entry(ability.get("name", "Deathbringer Stance"), per_hit, "magic")


_deathbringer_stance.phase = ONHIT

OPTIONS = [
    {"key": "sweetspot", "type": "bool", "default": True, "label": "Q Sweetspot hits"},
]

ASSUMPTIONS = [
    "Assumed R is always active",
    "W always hits both initial and pull-back damage",
]

SLOTS = {
    "R": stat_buff(
        "Bonus Attack Damage",
        "bonus_attack_damage",
        mode="percent_of",
        percent_of="attack_damage",
        apply_to=("attack_damage", "bonus_attack_damage"),
    ),
    "Q": _darkin_blade,
    "W": simple_damage(attr="Total Damage", dmg_type="physical"),
    "P": _deathbringer_stance,
}

parse_abilities = build_parser(SLOTS, "Aatrox")


# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Price Deathbringer Stance and Umbral Dash healing for Aatrox."""
    del cast_timeline, fight_duration_seconds
    healing: list[dict[str, Any]] = []
    passive_events = _attributed_events(
        damage_events,
        lambda source, _event: "passive" in source.lower(),
    )
    e_description = " ".join(
        effect.get("description", "")
        for effect in _ability(champion_data, "E").get("effects", [])
    )
    ratio_match = re.search(
        r"heals for\s+(\d+(?:\.\d+)?)%\s*\(\+\s*(\d+(?:\.\d+)?)%\s*per\s*100\s*bonus health",
        e_description,
        flags=re.IGNORECASE,
    )
    base_ratio = float(ratio_match.group(1)) / 100.0 if ratio_match else 0.0
    per_100 = float(ratio_match.group(2)) / 100.0 if ratio_match else 0.0
    e_ratio = base_ratio + per_100 * (
        float(champion_stats.get("bonus_health", 0.0)) / 100.0
    )
    r_rank = int(ability_damages.get("R", {}).get("rank", 0) or 0)
    r_inc = _leveling_value(_ability(champion_data, "R"), "Increased Healing", r_rank)
    healing_amp = 1.0 + r_inc / 100.0 if r_rank > 0 else 1.0

    for event in passive_events:
        amount = max(0.0, float(event.get("damage", 0.0))) * healing_amp
        if amount > 0:
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": amount,
                    "source": "Deathbringer Stance",
                    "kind": "champion_passive",
                    **_trigger_fields(event),
                }
            )

    for event in damage_events:
        if _is_persistent(event):
            continue
        amount = max(0.0, float(event.get("damage", 0.0))) * e_ratio * healing_amp
        if amount > 0:
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": amount,
                    "source": "Umbral Dash",
                    "kind": "champion_passive",
                    **_trigger_fields(event),
                }
            )
    return healing


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Aatrox",
        "revision_id": 4013021,
        "revision_timestamp": "2026-04-28T12:46:19Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Aatrox", derive_self_healing)
