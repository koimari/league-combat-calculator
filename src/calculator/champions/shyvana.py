"""Shyvana's human/dragon combat states, self-shield, and timed packets.

E9-3: Inferno Aegis (W) now carries the sourced self-shield
('Shield Strength' + 12% bonus health, plus the per-nearby-champion
'Increased shield per champion' increment) as an E8c
``self_shield_events`` payload — the shield is granted at the cast and
consumed by the one-second recast.  The dragon-form recast heal
(60 : 104.71 by level + 4% : 8.47% by level missing health when the
explosion hits a champion) is authored by the healing rule in
``healing.py`` (HEALING_RULE_CHAMPIONS), keyed on the W recast damage
events and gated on the ``dragon_form`` option; the support scanner
defers both (see ``support_effects._MODULE_AUTHORED_SHIELD_SLOTS`` and
``_MODULE_AUTHORED_HEAL_SLOTS``).

P (Scalemail) is the ``scalemail_stacks`` option's one consumer: the
per-stack resists live in the cached effect prose alone, so
``_scalemail_per_stack`` reads them out of that sentence.  Its
``no_damage`` disposition is sourced on both sides of the cache — the
entry's two effects are the stack-generation rule and the resist grant
with ``damageType`` null and ``affects`` "Self", and the game data's
``ShyvanaPassiveAbility/ShyvanaPassive`` carries only the DataValues
``BonusArmor``/``BonusMagicResist``/``PassiveScale`` (0.3 each) and the
four ``Stacks_Per_*`` counts, with no damage node of any kind."""

import re
from typing import Any

from .. import healing_helpers as _healing
from ..ability_atoms import ability_payload
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import BUFF, SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .inputs import bool_option, champion_stat, int_option
from .module_contract import coverage
from .module_helpers import ranked_slot
from .slotlib import (
    STEROID_ZERO,
    ability_name,
    attach_self_shield,
    damage_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
)
from .source_receipts import load_champion_sources

# Rooted in ShyvanaW.Duration; the cached W description corroborates the
# 2.5-second shield window. The 1-second recast window remains prose.
_W_SHIELD_DURATION_SECONDS = data_value(spell_object("Shyvana", "ShyvanaW"), "Duration")
_W_RECAST_WINDOW_SECONDS = 1.0


def _inferno_aegis_shield(ctx: SlotCtx) -> float:
    """W's self-shield: rank base + 12% bonus health, plus the sourced
    per-nearby-champion increment (a 1v1 duel is one nearby champion)."""
    ability = ctx.ability("W")
    if ability is None:
        return 0.0
    rank = ctx.rank_for("W")
    nearby = min(max(int(ctx.option("w_nearby_champions")), 0), 5)
    base = extract_named(ability, "Shield Strength", rank, ctx.stats, ctx.target)
    per_champion = extract_named(
        ability, "Increased shield per champion", rank, ctx.stats, ctx.target
    )
    return base + nearby * per_champion


# Scalemail's per-stack resists are cached PROSE with no leveling row of
# any kind, so the sentence itself is the source and is read here rather
# than copied — the Ornn P (Temper) shape.  ``_SCALEMAIL_MAX_STACKS`` is
# the option's own bound, not a game cap: takedown stacks have none.
_SCALEMAIL_EFFECT_MARKER = "Scalemail:"
_SCALEMAIL_RE = re.compile(
    r"For each stack,\s*Shyvana gains\s+(?P<armor>\d+(?:\.\d+)?)\s+bonus armor"
    r"\s+and\s+(?P<mr>\d+(?:\.\d+)?)\s+bonus magic resistance",
    re.IGNORECASE,
)
_SCALEMAIL_MAX_STACKS = 100


def _scalemail_per_stack(passive: dict[str, Any] | None) -> tuple[float, float]:
    """One Scalemail stack's bonus armor and bonus magic resistance."""
    match = next(
        filter(
            None,
            (
                _SCALEMAIL_RE.search(text)
                for text in (
                    str(effect.get("description") or "")
                    for effect in (passive or {}).get("effects") or []
                )
                if _SCALEMAIL_EFFECT_MARKER in text
            ),
        ),
        None,
    )
    if match is None:
        raise ValueError(
            "Shyvana P (Scalemail): the cached passive description no longer "
            "states 'For each stack, Shyvana gains <n> bonus armor and <n> "
            "bonus magic resistance' — the per-stack resists cannot be sourced"
        )
    return float(match.group("armor")), float(match.group("mr"))


def _scalemail(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the sourced per-stack armor and magic resistance (BUFF phase)."""
    ability = ctx.ability("P")
    if ability is None:
        return None
    armor_per_stack, mr_per_stack = _scalemail_per_stack(ability)
    stacks = min(max(int(ctx.option("scalemail_stacks")), 0), _SCALEMAIL_MAX_STACKS)
    bonus_armor = stacks * armor_per_stack
    bonus_mr = stacks * mr_per_stack
    entry = damage_entry(
        ability_name(ability),
        ctx.level,
        0.0,
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {"armor": bonus_armor, "magic_resistance": bonus_mr}
    entry["detail"] = (
        f"{stacks} Scalemail stack(s) x {armor_per_stack:g} armor / "
        f"{mr_per_stack:g} magic resistance: +{bonus_armor:.2f} armor, "
        f"+{bonus_mr:.2f} magic resistance"
    )
    return entry


_scalemail.phase = BUFF


@ranked_slot
def _emberstrike(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    casts = min(max(int(ctx.option("q_casts")), 1), 3)
    dragon = bool(ctx.option("dragon_form"))
    human = extract_named(ability, "Area Physical Damage", rank, ctx.stats, ctx.target)
    dragon_third = extract_named(ability, "True Damage", rank, ctx.stats, ctx.target)
    parts: list[DamagePart] = []
    for index in range(casts):
        amount = dragon_third if dragon and index == 2 else human
        dtype = "true" if dragon and index == 2 else "physical"
        parts.append(DamagePart(dtype, amount, time_offset=0.0, hit_interval=0.0))
    total = sum(part.amount for part in parts)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        (
            "mixed"
            if len({part.damage_type for part in parts}) > 1
            else parts[0].damage_type
        ),
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = (
        f"{casts} Emberstrike cast(s), {'dragon' if dragon else 'human'} form"
    )
    entry["empowers_next_auto"] = True
    return entry


def _inferno_aegis(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the sourced self-shield plus the explosion damage.

    The shield is granted at the cast and consumed by the explosion: with
    w_recast=True (default) the player recasts after the sourced one-
    second window, with w_recast=False the shield holds its full 2.5-
    second window and the explosion fires automatically at expiry (wiki
    prose: "can be recast ... and does so automatically after it expires
    or is broken").  The E8c ``self_shield_events`` payload rides the
    explosion event (the ledger grants the timed shield at that event's
    timestamp — the module's sourced shield amount is the same either
    way).  The dragon-form explosion heal (60 : 104.71 by level + 4% :
    8.47% by level missing health when the explosion hits a champion) is
    authored by the healing rule in ``healing.py``, keyed on the W
    damage events and gated on the dragon-form marker in this detail.
    """
    ability = ctx.ability("W")
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    recast = bool(ctx.option("w_recast"))
    dragon = bool(ctx.option("dragon_form"))
    shield = _inferno_aegis_shield(ctx)
    total = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    if recast:
        name = "Inferno Aegis (recast)"
        detail = (
            f"recast consumes the shield after the sourced "
            f"{_W_RECAST_WINDOW_SECONDS:g}-second window; the shield "
            f"({shield:g}) rides the explosion event"
        )
        detail += "; dragon form" if dragon else ""
        return attach_self_shield(
            damage_entry(
                name,
                rank,
                extract_cooldown(ability, rank),
                total,
                "magic",
            )
            | {
                "parts": (
                    DamagePart("magic", total, time_offset=_W_RECAST_WINDOW_SECONDS),
                )
            },
            amount=shield,
            duration=_W_RECAST_WINDOW_SECONDS,
            source="Inferno Aegis",
            detail=detail,
        )
    name = "Inferno Aegis"
    detail = (
        f"no recast: the shield ({shield:g}) holds its full "
        f"{_W_SHIELD_DURATION_SECONDS:g}-second window and the "
        f"auto-explosion fires at expiry (+{_W_SHIELD_DURATION_SECONDS:g}s)"
    )
    detail += "; dragon form" if dragon else ""
    return attach_self_shield(
        damage_entry(
            name,
            rank,
            extract_cooldown(ability, rank),
            total,
            "magic",
        )
        | {
            "parts": (
                DamagePart("magic", total, time_offset=_W_SHIELD_DURATION_SECONDS),
            )
        },
        amount=shield,
        duration=_W_SHIELD_DURATION_SECONDS,
        source="Inferno Aegis",
        detail=detail,
    )


def _molten_burst(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("E")
    if ability is None:
        return None
    rank = ctx.rank_for("E")
    dragon = bool(ctx.option("dragon_form"))
    attr = "Increased/Explosion Magic Damage" if dragon else "Magic Damage"
    total = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    parts = [DamagePart("magic", total, time_offset=0.0)]
    if dragon and bool(ctx.option("e_second_explosion")):
        second = extract_named(
            ability, "Subsequent Explosion Damage", rank, ctx.stats, ctx.target
        )
        parts.append(DamagePart("magic", second, time_offset=0.0))
        total += second
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = "dragon-form explosion" if dragon else "human-form fireball"
    return entry


SLOTS = {
    "P": _scalemail,
    "Q": _emberstrike,
    "W": _inferno_aegis,
    "E": _molten_burst,
    # One flight, one cone of fire per target ("breathing fire in a cone
    # along the way that deals magic damage to enemies hit"), so the row
    # is a hit the ledger can time and its fear reaches the readers.
    "R": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
}

# Reviewed crowd control, read from the cached kit.  Q (Emberstrike) is
# empowered attacks — slash, tail slam, dragon-form bite — with no control
# clause; W (Inferno Aegis) shields and explodes "dealing magic damage to
# nearby enemies" and applies none either.  E (Molten Burst) deals damage
# "and slowing them by 30% for 2 seconds".  R (Dragon's Descent) "deals
# magic damage to enemies hit and fears them for 0.75 seconds, as well as
# slows them by 99%" — the fear is the immobilizing half.
MODULE_CC = {"Q": "none", "W": "none", "E": "slow", "R": "fear"}

parse_abilities = build_parser(SLOTS, "Shyvana", cc_kinds=MODULE_CC)

OPTIONS = [
    int_option(
        "scalemail_stacks",
        0,
        minimum=0,
        maximum=_SCALEMAIL_MAX_STACKS,
        label="Scalemail stacks",
    ),
    bool_option("dragon_form", False, label="Dragon Form"),
    int_option("q_casts", 1, minimum=1, maximum=3, label="Emberstrike casts"),
    bool_option("w_recast", True, label="Inferno Aegis recast hits"),
    int_option(
        "w_nearby_champions",
        1,
        minimum=0,
        maximum=5,
        label="Nearby enemy champions (W shield increment)",
    ),
    bool_option("e_second_explosion", False, label="Dragon E second explosion"),
]

MODULE_COVERAGE = coverage(no_damage="P")

ASSUMPTIONS = [
    "P (Scalemail) prices the stack resists: the cached effect "
    "sentence 'For each stack, Shyvana gains 0.3 bonus armor and 0.3 "
    "bonus magic resistance' is read out of the description (there is no "
    "leveling row anywhere in the entry) and multiplied by the "
    "user-set scalemail_stacks option, emitted as a BUFF-phase "
    "stat_buff.  Takedown stacking is not simulated -- stacks come from "
    "takedowns before the fight -- so the count is an input with a "
    "disclosed default of 0, and the slot deals no enemy damage.",
    "Inferno Aegis grants the sourced self-shield ('Shield Strength' 60-140 "
    "by rank + 12% bonus health, plus 'Increased shield per champion' "
    "18-42 by rank + 3.6% bonus health per nearby enemy champion, "
    "w_nearby_champions default 1 for a 1v1) for 2.5s, or until the "
    "one-second recast consumes it.",
    "The dragon-form recast heal (60 : 104.71 based on level + 4% : 8.47% "
    "based on level of missing health when the explosion hits a champion) "
    "is authored by the healing rule (healing.py, HEALING_RULE_CHAMPIONS) "
    "keyed on the W recast damage events and gated on dragon_form; the "
    "human-form recast deals the sourced damage without healing.",
    "Inferno Aegis defaults to its one-second recast damage; with "
    "w_recast=False the shield holds its full 2.5-second window and the "
    "auto-explosion at expiry is not priced.",
    "Dragon-form Q/E variants and the second explosion are explicit "
    "options, never inferred from a cast count.",
]

SOURCES = load_champion_sources("Shyvana")


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Shyvana self-healing events from its authored packet."""
    healing = []
    w_row = ability_payload(ability_damages, "W")
    if "dragon form" in str(w_row.get("detail", "")).lower():
        level = max(1, int(champion_stat(champion_stats, "level")))
        w = _healing.ability_json(champion_data, "W")
        flat = extract_named(w, "Heal", level, champion_stats, {})
        missing_pct = _healing.leveling_modifier(w, "Missing Health Damage", level, 0)

        inferno_aegis_heal = _healing.flat_plus_missing_heal(flat, missing_pct)
        for payment in _healing.payments(
            _healing.HealAnchor.CAST, "W", damage_events, cast_timeline
        ):
            event = payment.event
            if float(event.get("damage", 0.0)) <= 0.0:
                continue
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": 0.0,
                    "amount_formula": inferno_aegis_heal,
                    "source": "Inferno Aegis",
                    "kind": "champion_ability",
                    **_healing.trigger_fields(event),
                }
            )
    return healing


SELF_HEALING_RULE = self_healing_rule("Shyvana")(derive_self_healing)
