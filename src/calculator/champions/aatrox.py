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
- E (Umbral Dash) is a dash with healing amp only — no enemy damage of
  its own, so ``_umbral_dash`` emits a sourced zero rather than leaving
  the slot absent. It is still ``modeled``: ``derive_self_healing``
  prices its heal share of every damaging hit, the
  ``self_healing_rule`` channel the coverage map names. Only the dash
  itself — mobility, an axis the engine lacks — is unpriced.

All numeric values are read from the champion JSON data; nothing is
hardcoded.

Roadmap session (2026-08-21): closes the single out_of_scope slot (E).
E (Umbral Dash): ``data/champions.json`` Aatrox E carries
``damageType: None`` and its three effect rows are entirely non-combat
text — "Passive: Aatrox heals for 16% (+ 1.1% per 100 bonus health) of
non-persistent post-mitigation damage he deals against enemy champions"
(the heal, already modeled by ``derive_self_healing``'s E-ratio path),
"Active: Aatrox dashes in the target direction" (a pure position change),
and the basic-attack-timer-reset/cast-interrupt clause (mobility/utility,
not a combat number). No effect row carries a ``leveling`` entry at all —
there is no enemy-damage attribute anywhere on this ability to model.
So the slot emits an atoms-confirmed zero-HP-number row rather than
staying silently absent, and its heal keeps it ``modeled`` through the
``self_healing_rule`` channel.
"""

import re
from typing import Any

from ..ability_atoms import ability_field, ability_payload
from .healing_contract import self_healing_rule
from .inputs import bool_option, champion_stat, int_option
from .engine import ONHIT, SlotCtx, build_parser
from .module_helpers import no_damage
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
    pct_health_per_hit,
    simple_damage,
    stat_buff,
)

from ..healing_helpers import (
    HealAnchor,
    ability_json,
    event_source,
    leveling_value,
    payments,
    trigger_fields,
)
from .source_receipts import load_champion_sources

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
_Q_VARIANT_ATTRS = [
    *_Q_NORMAL_ATTRS[:1],
    *_Q_SWEETSPOT_ATTRS[:1],
    *_Q_NORMAL_ATTRS[1:2],
    *_Q_SWEETSPOT_ATTRS[1:2],
    *_Q_NORMAL_ATTRS[2:3],
    *_Q_SWEETSPOT_ATTRS[2:3],
    "Maximum Non-Minion Non-Sweetspot Damage",
    "Maximum Non-Minion Sweetspot Damage",
]

# The Darkin Blade's three strikes are one second apart: "Aatrox can
# activate The Darkin Blade three times before the ability goes on
# cooldown, with a 1-second static cooldown between casts" (data/
# champions.json Aatrox Q), and the cache names each strike's damage on its
# own row, so the triad reads as three strikes at 0, 1 and 2 seconds from
# the first.  Unauthored for the reason the comment above
# ``parse_abilities`` gives.
_Q_STRIKE_INTERVAL_SECONDS_UNAUTHORED = 1.0


def _darkin_blade(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: sum all three sweetspot or normal casts into one entry."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    if "q_variant" in ctx.options:
        try:
            variant = int(ctx.options["q_variant"])
        except (TypeError, ValueError):
            variant = len(_Q_VARIANT_ATTRS) - 1
        variant = max(0, min(variant, len(_Q_VARIANT_ATTRS) - 1))
        attribute = _Q_VARIANT_ATTRS[variant]
        total = extract_named(ability, attribute, rank, ctx.stats, ctx.target)
        entry = damage_entry(
            ability_name(ability),
            rank,
            extract_cooldown(ability, rank),
            total,
            "physical",
        )
        entry["detail"] = f"Q variant: {attribute}."
        return entry

    attrs = _Q_SWEETSPOT_ATTRS if bool(ctx.option("sweetspot")) else _Q_NORMAL_ATTRS
    total = sum(
        extract_named(ability, attr, rank, ctx.stats, ctx.target) for attr in attrs
    )
    return damage_entry(
        ability_name(ability),
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
    return on_hit_entry(ability_name(ability), per_hit, "magic")


_deathbringer_stance.phase = ONHIT


def _umbral_dash(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: dash + heal-amp utility — sourced zero-enemy-damage row (no_damage).

    The cached E entry carries ``damageType: None`` and no effect row has a
    ``leveling`` attribute; the passive heal (16% + 1.1% per 100 bonus
    health of non-persistent post-mitigation damage dealt) is already
    priced through ``derive_self_healing`` and the active dash is a pure
    position change. Nothing here deals damage to an enemy champion.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    return no_damage(
        ctx,
        name=ability_name(ability),
        reason=(
            "Umbral Dash is a self-heal-amp dash with no enemy-damage "
            "attribute of its own (data/champions.json Aatrox E carries "
            "damageType: None and no effect row has a leveling entry); "
            "its heal is priced through derive_self_healing."
        ),
    )


OPTIONS = [
    int_option(
        "q_variant",
        7,
        minimum=0,
        maximum=7,
        label="Q damage variant",
        legacy_keys=["sweetspot"],
    ),
    bool_option("sweetspot", True, label="Q Sweetspot hits"),
]

ASSUMPTIONS = [
    "Assumed R is always active",
    "W always hits both initial and pull-back damage",
    "E (Umbral Dash) carries no enemy-damage attribute (damageType: None, "
    "no leveling row on any effect); it emits a sourced no_damage row. Its "
    "heal is priced through derive_self_healing, not this slot.",
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
    "E": _umbral_dash,
}

# MODULE_CC is empty, and for neither row is the reason a missing cadence — both
# cadences are cached, and both are refused by a committed receipt rather
# than by the source.
#
# Q (The Darkin Blade) knocks up only "enemies hit within a Sweetspot of
# the area", which is this module's ``sweetspot`` option, and the cache
# spaces its three casts ("with a 1-second static cooldown between casts")
# while naming each strike's damage separately, so the triad reads as three
# strikes at 0/1/2 seconds.  The engine accepts that: an event past the end
# of a roster fight (``roster_composition.resource_restores``, and Aatrox's
# last Q in an eight-second roster fight lands its third strike at 8.85s) is
# dropped the way the survival walk skips every other post-window action.
# What is left is evidence:
# data/practice-corpus/scenarios.json pins e9-e1-aatrox-umbral-dash-heal at
# one Umbral Dash payment of 276.4 off a single Q event, and the triad pays
# the same total as three (73.7 + 92.1 + 110.6) at 0/1/2 seconds — the heal
# rule follows the hits honestly (``HealAnchor.DAMAGING_HIT``), but the
# corpus scenario is pinned to a src-tree sha and re-pinning it is a
# baseline re-capture, not a review.  The same split moves the live-amp
# roster scenarios, which are pinned the same way.
#
# W (Infernal Chains) slows on the first hit ("slowing them for 1.5
# seconds") and pulls on the second, which the cache times exactly ("a
# tether is formed ... for 1.5 seconds", and at its end "the target is
# dealt the same physical damage again and pulled to the center of the
# area").  Splitting the cached Total into those two hits keeps every
# total, including self-healing, but it splits Umbral Dash's heal from one
# payment into two — the heal is a share of each hit's damage
# (``HealAnchor.DAMAGING_HIT``), so two hits are honestly two shares — and
# docs/receipts/oracle-P4B-leaf29.json pins that single payment
# ("W 157.5 x 0.16 x 2.0 = 50.4") as corpus evidence.  Re-pinning an oracle
# receipt is not this review's to do.
#
# R fears "nearby enemy minions and monsters" only and authors no damage
# part; P is the on-hit stance row.
MODULE_CC: dict[str, str] = {}

parse_abilities = build_parser(SLOTS, "Aatrox", cc_kinds=MODULE_CC)


# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
def _is_persistent(event: dict[str, Any]) -> bool:
    """Return the source-certified persistent/periodic damage boundary.

    The engine's own source keys are stable public receipts for these rows;
    no damage amount or champion archetype is guessed here.
    """
    source = event_source(event).lower()
    return (
        source.startswith("burn_")
        or source.startswith("stacking_dot_")
        or "tibbers_aura" in source
        or source.startswith("immolate_")
    )


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
    # Both rules pay a share of what a hit dealt — Deathbringer Stance
    # "heals for a percentage of the damage dealt" and Umbral Dash the same
    # for every damage source — so both pay per hit that dealt some.
    passive_payments = payments(
        HealAnchor.DAMAGING_HIT,
        lambda source: "passive" in source.lower(),
        damage_events,
    )
    e_description = " ".join(
        effect.get("description", "")
        for effect in ability_json(champion_data, "E").get("effects", [])
    )
    ratio_match = re.search(
        r"heals for\s+(\d+(?:\.\d+)?)%\s*\(\+\s*(\d+(?:\.\d+)?)%\s*per\s*100\s*bonus health",
        e_description,
        flags=re.IGNORECASE,
    )
    base_ratio = float(ratio_match.group(1)) / 100.0 if ratio_match else 0.0
    per_100 = float(ratio_match.group(2)) / 100.0 if ratio_match else 0.0
    e_ratio = base_ratio + per_100 * (
        float(champion_stat(champion_stats, "bonus_health")) / 100.0
    )
    r_rank = int(ability_field(ability_payload(ability_damages, "R"), "rank"))
    r_inc = leveling_value(
        ability_json(champion_data, "R"), "Increased Healing", r_rank
    )
    healing_amp = 1.0 + r_inc / 100.0 if r_rank > 0 else 1.0

    for payment in passive_payments:
        event = payment.event
        amount = max(0.0, float(event.get("damage", 0.0))) * healing_amp
        if amount > 0:
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": amount,
                    "source": "Deathbringer Stance",
                    "kind": "champion_passive",
                    **trigger_fields(event),
                }
            )

    for payment in payments(
        HealAnchor.DAMAGING_HIT, lambda _source: True, damage_events
    ):
        event = payment.event
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
                    **trigger_fields(event),
                }
            )
    return healing


SOURCES = load_champion_sources("Aatrox")

SELF_HEALING_RULE = self_healing_rule("Aatrox")(derive_self_healing)

# E's own row is a sourced zero, so SLOTS derives ``modeled`` without a
# damage number behind it; what prices the slot is the rule above, which
# pays Umbral Dash's heal off every damaging hit (821.5 over a level-18
# timed fight with autos).
COVERAGE_CHANNELS = {"E": ("self_healing_rule",)}
