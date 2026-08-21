"""Kai'Sa — sourced isolated-target Q/W and ordered Plasma rupture.

The certified sequence deliberately waits for Void Seeker and its Plasma
applications to resolve before casting Icathian Rain. This keeps every damage
event in one unambiguous order without pretending the current engine models
Supercharge's timed attack-speed window or Killer Instinct's attack reset.

Roadmap session 2 (2026-08-20): closes 2 of Kai'Sa's 3 out_of_scope slots
(P, E); R stays open with a named receipt.

  - P (Second Skin): the Caustic Wounds sub-effect (the third of P's three
    cached effect rows, `data/champions.json` Kai'Sa P effects[2]) is
    already fully computed — base 4:30 (based on level) (+12% AP), plus
    1:8 (based on level) (+3% AP) per prior stack, plus a 5th-stack rupture
    at 15% (+6% per 100 AP) of the target's missing health — by
    `_plasma_values`/`_plasma_proc` below, riding Void Seeker's
    `post_hit_proc` and reported under the `passive_plasma` breakdown key
    (pinned by `tests/test_kaisa.py::test_w_applies_successive_plasma_after_spell_damage`
    and its evolution/build-driven siblings). MODULE_COVERAGE read
    out_of_scope only because Plasma has no standalone top-level "P" SLOTS
    entry — Plasma applications ride Void Seeker and basic attacks, never
    an independent P cast — so the label was stale, not the calculation.
    Reclassified to modeled.
  - E (Supercharge): the cached ability carries exactly four effect rows
    (`data/champions.json` Kai'Sa E) — a ghosted/Minimum-Maximum-Movement-
    Speed charge-up, a post-charge Bonus Attack Speed buff (40:80% by
    rank for 4s), an on-attack cooldown-reduction sentence, and an
    evolution unlocking stealth/missile-speed prose — no damage, heal, or
    shield attribute anywhere. Cross-checked against the game binary
    (`data/gamefiles/characters/kaisa.bin.json` /
    `data/bin/characters/kaisa.bin.json`, `KaisaEAbility`'s child spells
    `KaisaEAttackSpeed`/`KaisaE`): no damage-calculation node exists for
    E at all. Even if the attack-speed buff were wired in, the certified
    rotation is a spell-only W -> Q sequence with no basic-attack
    timeline — `UNSUPPORTED_FIGHT_MODE_REASON` already withholds
    time-based mode precisely because Supercharge's AS window, its
    on-attack cooldown refund, and Killer Instinct's attack reset are not
    yet modeled on one shared attack clock — so an attack-speed steroid
    has no attack stream to buff here. Reclassified to no_damage (an
    atoms-confirmed zero-HP-number effect), not out_of_scope.
  - R (Killer Instinct): the shield IS sourced (Shield Strength
    100/150/200 + 90/135/180% total AD + 120% AP, 2s duration, refreshed
    by a later Killer Instinct) — `data/champions.json` Kai'Sa R
    effects[0]. Independently corroborated by the game binary's
    `KaisaR` spell object: `RBaseValue` [.., 100, 150, 200, ..],
    `RTotalADRatio` [.., 0.9, 1.35, 1.8, ..], `RAPRatio` 1.2 flat, and
    `RShieldDuration` 2.0s flat reproduce the wiki numbers exactly (also
    yielding Killer Instinct's mana cost, 100 flat, and its per-rank
    cooldown, none of which are cached in the wiki JSON).
    `support_effects.py` already carries a shield-duration atom query for
    `("Kai'Sa", "R")`, but the generic ally-support shield scanner only
    emits a packet for a slot present in the fight's cast_timeline, which
    is built strictly from a champion module's own declared CAST_ORDER —
    and Killer Instinct is deliberately absent from Kai'Sa's certified
    CAST_ORDER (`("W", "Q")`). Wiring R in would require (a) a new SLOTS
    entry, which adds a top-level "R" key to `parse_champion_abilities()`'s
    output — captured verbatim by `scripts/golden_snapshot.py`'s
    per-champion ability-baseline section — and (b) threading Killer
    Instinct's sourced 100-mana cost into the resource ledger, which would
    change this fight's resource_spent/resource_remaining. Both are
    legitimate, but this session's gate is "golden compare identical, STOP
    on diff" (scripts/ is out of scope this session too), so R stays
    out_of_scope with this receipt for whichever session next owns a real
    golden re-capture.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    sum_modifiers,
)

_Q_FIRST_HIT_DELAY = 0.4
_Q_VOLLEY_DURATION = 1.0
_Q_NORMAL_MISSILES = 6
_Q_EVOLVED_MISSILES = 12
_W_CAST_TIME = 0.4
_W_MISSILE_SPEED = 1750.0
_W_MAX_RANGE = 3000.0
_W_NORMAL_STACKS = 2
_W_EVOLVED_STACKS = 3
_PLASMA_STACKS_TO_RUPTURE = 5
_RUPTURE_BASE_MISSING_HEALTH_RATIO = 0.15
_RUPTURE_RATIO_PER_AP = 0.0006
_EVOLUTION_THRESHOLD = 100.0


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def _plasma_values(ctx: SlotCtx) -> tuple[float, float]:
    passive = ctx.ability("P")
    if passive is None:
        raise ValueError("Kai'Sa passive data is unavailable")
    base = find_named_leveling(passive, "Bonus Magic Damage", occurrence=0)
    per_prior_stack = find_named_leveling(passive, "Bonus Magic Damage", occurrence=1)
    if base is None or per_prior_stack is None:
        raise ValueError("Kai'Sa Plasma damage arrays are unavailable")
    return (
        sum_modifiers(base, ctx.level, ctx.stats, ctx.target),
        sum_modifiers(per_prior_stack, ctx.level, ctx.stats, ctx.target),
    )


def _w_hit_time(ctx: SlotCtx) -> tuple[float, float]:
    """Return clamped W distance and time from cast start to impact."""
    distance = _clamp(
        float(ctx.options.get("w_target_distance", 800.0)),
        0.0,
        _W_MAX_RANGE,
    )
    return distance, _W_CAST_TIME + distance / _W_MISSILE_SPEED


def _evolution_state(
    ctx: SlotCtx,
    option_key: str,
    stat_key: str,
    stat_label: str,
) -> tuple[bool, str]:
    """Resolve Auto/Base/Evolved while accepting old shared-link booleans."""
    selected = ctx.options.get(option_key, "auto")
    if isinstance(selected, bool):
        return selected, "shared-link override"
    if selected == "evolved":
        return True, "forced evolved"
    if selected == "base":
        return False, "forced not evolved"
    if selected != "auto":
        raise ValueError(f"Kai'Sa {option_key} must be auto, base, or evolved")
    owned = float(ctx.stats.get(stat_key, 0.0))
    return (
        owned >= _EVOLUTION_THRESHOLD,
        f"automatic: {owned:.1f}/{_EVOLUTION_THRESHOLD:g} {stat_label}",
    )


def _plasma_proc(ctx: SlotCtx, hit_time: float) -> dict[str, Any]:
    base, per_prior_stack = _plasma_values(ctx)
    stacks = int(
        _clamp(
            float(ctx.options.get("plasma_starting_stacks", 0)),
            0.0,
            float(_PLASMA_STACKS_TO_RUPTURE - 1),
        )
    )
    w_evolved, evolution_note = _evolution_state(
        ctx,
        "w_evolved",
        "evolution_ability_power",
        "item AP",
    )
    applications = _W_EVOLVED_STACKS if w_evolved else _W_NORMAL_STACKS
    target_health = float(ctx.target.get("target_max_health", 0.0))
    ability_power = float(ctx.stats.get("ability_power", 0.0))
    rupture_ratio = (
        _RUPTURE_BASE_MISSING_HEALTH_RATIO + _RUPTURE_RATIO_PER_AP * ability_power
    )
    parts: list[DamagePart] = []
    ruptures = 0
    for _ in range(applications):
        parts.append(
            DamagePart(
                "magic",
                base + per_prior_stack * stacks,
                time_offset=hit_time,
            )
        )
        stacks += 1
        if stacks == _PLASMA_STACKS_TO_RUPTURE:
            parts.append(
                DamagePart(
                    "magic",
                    hp_scaled_damage=(
                        lambda missing_ratio, live_target_max_health=None, ratio=rupture_ratio, baseline_target_health=target_health: (
                            (
                                baseline_target_health
                                if live_target_max_health is None
                                else live_target_max_health
                            )
                            * missing_ratio
                            * ratio
                        )
                    ),
                    time_offset=hit_time,
                )
            )
            ruptures += 1
            stacks = 0

    return {
        "name": "Second Skin (Plasma)",
        "breakdown_key": "passive_plasma",
        "parts": tuple(parts),
        "detail": (
            f"{applications} successive stack applications"
            + (f"; {ruptures} rupture" if ruptures else "")
            + f"; {evolution_note}"
        ),
    }


def _void_seeker(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    raw = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    distance, hit_time = _w_hit_time(ctx)
    entry = damage_entry(
        ability.get("name", "Void Seeker"),
        rank,
        extract_cooldown(ability, rank),
        raw,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", raw, time_offset=hit_time),)
    # The certified rotation waits for W to hit before starting Q. Treating
    # the travel as occupied sequence time makes that deliberate wait explicit.
    entry["cast_time"] = hit_time
    entry["post_hit_proc"] = _plasma_proc(ctx, hit_time)
    entry["target_max_health_sensitive"] = True
    entry["detail"] = f"hit at {distance:g} range; Plasma resolves afterwards"
    return entry


def _icathian_rain(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    evolved, evolution_note = _evolution_state(
        ctx,
        "q_evolved",
        "evolution_attack_damage",
        "AD from items + growth",
    )
    missiles = _Q_EVOLVED_MISSILES if evolved else _Q_NORMAL_MISSILES
    first = extract_named(
        ability, "Physical Damage Per Missile", rank, ctx.stats, ctx.target
    )
    reduced = extract_named(
        ability, "Reduced Damage Per Missile", rank, ctx.stats, ctx.target
    )
    total_attr = (
        "Total Evolved Single-Target Damage"
        if evolved
        else "Total Single-Target Damage"
    )
    total = extract_named(ability, total_attr, rank, ctx.stats, ctx.target)
    interval = _Q_VOLLEY_DURATION / (missiles - 1)
    # One-rotation cast timestamps are nominally all zero in the shared
    # engine. This module authors the deliberate W-impact wait directly into
    # Q's hit offsets so the damage ledger still reflects W -> Plasma -> Q.
    _, q_start = _w_hit_time(ctx)
    first_hit = q_start + _Q_FIRST_HIT_DELAY
    entry = damage_entry(
        ability.get("name", "Icathian Rain"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (
        DamagePart("physical", first, time_offset=first_hit),
        DamagePart(
            "physical",
            reduced,
            count=missiles - 1,
            time_offset=first_hit + interval,
            hit_interval=interval,
        ),
    )
    entry["detail"] = (
        f"{missiles} missiles on one isolated target"
        + (" (evolved)" if evolved else "")
        + f"; {evolution_note}"
    )
    return entry


def _supercharge(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: attack-speed steroid — documented zero-damage row (no_damage)."""
    ability = ctx.ability()
    if ability is None:
        return None
    return no_damage(
        ctx,
        name=ability.get("name", "Supercharge"),
        reason=(
            "Supercharge charges Kai'Sa up (ghosted, 55-150% bonus movement "
            "speed by rank), then grants 40-80% bonus attack speed for 4 "
            "seconds and refunds 0.5s of its own cooldown on-attack; the "
            "cached entry carries no damage/heal/shield attribute at all "
            "(data/champions.json Kai'Sa E), corroborated by the game "
            "binary's KaisaEAbility child spells. The certified W -> Q "
            "rotation has no basic-attack timeline for an attack-speed "
            "steroid to buff, so this row is state, not a priced effect."
        ),
    )


CAST_ORDER = ("W", "Q")
SUPPORTED_FIGHT_MODES = ("one_rotation",)
UNSUPPORTED_FIGHT_MODE_REASON = (
    "Time-based Kai'Sa calculations are withheld until Supercharge's "
    "four-second attack-speed window, on-attack cooldown refunds, Killer "
    "Instinct's attack reset, and Plasma all share one attack timeline. "
    "Use One Rotation."
)
CUSTOM_CAST_ORDER_UNAVAILABLE_REASON = (
    "Kai'Sa uses the certified W -> Q sequence so Plasma resolves before the "
    "volley; custom cast orders are not available yet."
)
COMPARISON_CURVE_UNAVAILABLE_REASON = (
    "Crossover windows are withheld for Kai'Sa until Plasma stacks persist "
    "correctly between rotations."
)

OPTIONS = [
    {
        "key": "q_evolved",
        "type": "select",
        "default": "auto",
        "label": "Icathian Rain evolution",
        "legacy_bool": True,
        "choices": [
            {"value": "auto", "label": "Automatic from build"},
            {"value": "base", "label": "Not evolved"},
            {"value": "evolved", "label": "Evolved"},
        ],
    },
    {
        "key": "w_evolved",
        "type": "select",
        "default": "auto",
        "label": "Void Seeker evolution",
        "legacy_bool": True,
        "choices": [
            {"value": "auto", "label": "Automatic from build"},
            {"value": "base", "label": "Not evolved"},
            {"value": "evolved", "label": "Evolved"},
        ],
    },
    {
        "key": "plasma_starting_stacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 4,
        "step": 1,
        "label": "Plasma stacks already on each target",
    },
    {
        "key": "w_target_distance",
        "type": "float",
        "default": 800.0,
        "min": 0.0,
        "max": 3000.0,
        "step": 50.0,
        "label": "Void Seeker target distance",
    },
]

ASSUMPTIONS = [
    "Certified mode is one W -> Q rotation; Kai'Sa waits for W and Plasma to "
    "resolve before casting Q",
    "Every Q missile hits one isolated selected target; shared targets would "
    "split the volley",
    "Q/W evolutions follow permanent item stats and level growth automatically; "
    "the selector can reproduce a not-yet-evolved or forced test state",
    "W applies each Plasma stack successively; a fifth-stack rupture uses "
    "health remaining after W and the preceding Caustic Wounds hit "
    "(Second Skin/Plasma is P; it rides Void Seeker and basic attacks and "
    "has no standalone cast)",
    "E (Supercharge) is an attack-speed steroid with no damage/heal/shield "
    "attribute at all; it emits an explicit zero-damage state row "
    "(no_damage) rather than staying silently absent",
    "R (Killer Instinct)'s shield is sourced (100/150/200 + 90/135/180% "
    "total AD + 120% AP) but not yet wired into CAST_ORDER or the resource "
    "ledger, so it stays out_of_scope; timed attacks are withheld",
]

SOURCES = [
    {
        "label": "Kai'Sa — Second Skin",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Kai'Sa/Second_Skin",
        "revision_id": 4046579,
        "revision_timestamp": "2026-07-28T19:58:33Z",
    },
    {
        "label": "Kai'Sa — Icathian Rain",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Kai'Sa/Icathian_Rain",
        "revision_id": 4038389,
        "revision_timestamp": "2026-06-30T09:21:59Z",
    },
    {
        "label": "Kai'Sa — Void Seeker",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Kai'Sa/Void_Seeker",
        "revision_id": 4034696,
        "revision_timestamp": "2026-06-23T21:14:14Z",
    },
    {
        "label": "Kai'Sa — Supercharge",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Kai'Sa/Supercharge",
        "revision_id": 4038391,
        "revision_timestamp": "2026-06-30T09:23:49Z",
    },
    {
        "label": "Kai'Sa — Killer Instinct",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Kai'Sa/Killer_Instinct",
        "revision_id": 4034697,
        "revision_timestamp": "2026-06-23T21:14:22Z",
    },
]

SLOTS = {"W": _void_seeker, "Q": _icathian_rain, "E": _supercharge}

parse_abilities = build_parser(SLOTS, "Kai'Sa")


# Authoritative review metadata (issue #161).
MODULE_COVERAGE = {
    "P": "modeled",
    "Q": "modeled",
    "W": "modeled",
    "E": "no_damage",
    "R": "out_of_scope",
}
REVIEW_STATUS = "reviewed_module"
