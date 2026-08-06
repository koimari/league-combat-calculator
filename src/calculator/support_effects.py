"""Sourced ally-targeted shields/heals from champion ability packets."""

from __future__ import annotations

import math
from typing import Any

from .champions.slotlib import extract_named
from .champions.skill_orders import get_ability_rank


def _ability(data: dict[str, Any], slot: str) -> dict[str, Any]:
    entries = data.get("abilities", {}).get(slot, [])
    return entries[0] if entries and isinstance(entries[0], dict) else {}


def _first_attribute(ability: dict[str, Any], names: tuple[str, ...]) -> str | None:
    available = {
        leveling.get("attribute", "")
        for effect in ability.get("effects", [])
        for leveling in effect.get("leveling", [])
    }
    return next((name for name in names if name in available), None)


# Attribute names that make a kit a support-packet candidate — the union of
# the shield and heal lookups below.  A champion whose ability JSON carries
# none of them can never emit a packet, so the coupled optimizer's per-
# candidate calls skip the full walk.  Memoized by champion-data identity
# and re-verified on every hit, so a data refresh can never serve a stale
# answer through a recycled ``id()``.
_SUPPORT_ATTRIBUTES = frozenset(
    {
        "Shield Strength",
        "Shield",
        "Total Heal",
        "Heal",
        "Heal Per Tick",
        # E8d follow-up: Bard W (Caretaker's Shrine) heals scale with charge
        # time between these two sourced rows; Taric Q carries only the
        # "Maximum Charges" attribute (prose heal, see _MODULE_HEAL_AMOUNTS).
        "Minimum Heal",
        "Maximum Heal",
    }
)
_SUPPORT_ATTRS_MEMO: dict[int, tuple[dict[str, Any], bool]] = {}

# E8d follow-up: per-champion heal-attribute overrides.  Bard W's shrine
# gathers power over 5s; the deterministic single-target model prices the
# fully-charged sourced row (Maximum Heal) and documents the charge-time
# boundary in the packet source label.
_CHAMPION_HEAL_ATTR: dict[tuple[str, str], str] = {
    ("Bard", "W"): "Maximum Heal",
}

# P1-3: per-champion shield-attribute overrides.  Lux W (Prismatic
# Barrier) shields Lux on both the throw and the return of the wand, so
# one cast stacks two "Shield Strength" shields into the sourced
# "Maximum Shield" row (80-200 + 80% AP by rank, data/champions.json);
# the generic scanner would price one half-strength shield.
_CHAMPION_SHIELD_ATTR: dict[tuple[str, str], str] = {
    ("Lux", "W"): "Maximum Shield",
}

# E8d follow-up: prose-only ally heals that the cached leveling rows do not
# carry as a resolvable attribute.  Each entry is
# (base, ap_ratio, max_health_ratio) with the wiki citation in the source
# label; the amount is computed at cast time from the fight's own stats.
# Taric Q heals for 25 (+15% AP) (+1% max HP) per stocked charge; the
# stocking cadence is combat state, so the deterministic model prices ONE
# charge per cast (the conservative floor, documented in ASSUMPTIONS).
_MODULE_HEAL_AMOUNTS: dict[tuple[str, str], tuple[float, float, float]] = {
    ("Taric", "Q"): (25.0, 0.15, 0.01),
}

# E8d follow-up: target-scope overrides for casts whose cached description
# markers cannot express the sourced targeting.  Yuumi's E (Zoomies) shields
# the attached ally, not Yuumi herself, while attached — the deterministic
# roster model targets one selected teammate (the anchor).
_SCOPE_OVERRIDES: dict[tuple[str, str], str] = {
    ("Yuumi", "E"): "one_teammate",
    # P1-3: Lux W (Prismatic Barrier) shields Lux herself on the throw and
    # the return ("Lux gains the shield upon throwing and upon retrieving
    # the wand"); the allied half needs a teammate roster the 1v1 lacks,
    # so the deterministic single-target cast targets self.
    ("Lux", "W"): "self",
}

# E8c: slots whose shield the champion module authors itself (via the
# ``self_shield_events`` payload on its damage entry) instead of this
# scanner.  The scanner would otherwise re-derive the same ability from
# its cached JSON — with a rank-indexed (not level-indexed) base for
# Ambessa W and a description-marker miss that mis-targets Vex W's
# self-only Personal Space as a one-teammate packet — and double-grant
# the shield.  Modules own the exact level/stat formula and duration;
# the scanner defers so the ledger sees exactly one sourced shield.
_MODULE_AUTHORED_SHIELD_SLOTS = frozenset(
    {
        ("Ambessa", "W"),
        ("Vex", "W"),
        # E9-3: Shyvana's Inferno Aegis module authors the sourced shield
        # ('Shield Strength' + 12% bonus health + the per-nearby-champion
        # 'Increased shield per champion' increment) with an explicit
        # consumed-at-recast duration; the scanner's rank-based read of the
        # same rows would double-grant a less precise amount.
        ("Shyvana", "W"),
    }
)

# E9-3: slots whose heal the champion module/healing rule authors itself
# instead of this scanner.  Shyvana's Inferno Aegis 'Heal' row is the
# DRAGON-FORM recast heal (60 : 104.71 by level + 4% : 8.47% by level
# missing health, gated on the explosion hitting a champion) and is
# authored by ``healing.derive_self_healing``; the scanner's static read
# would emit the rank-indexed flat at the cast time unconditionally (no
# dragon gate, no missing-health term, wrong leveling index), so it
# defers to the healing rule.
_MODULE_AUTHORED_HEAL_SLOTS = frozenset(
    {
        ("Shyvana", "W"),
    }
)

# E9-2: slots whose heal the champion module + the E1 self-heal rule
# author exactly (Naafiri's Q recast heal rides the module's Q damage
# receipts at the cached "Heal" row).  The scanner would otherwise
# re-derive the same ability from its cached JSON and double-grant the
# heal in a separate ledger, so it defers these slots.
_MODULE_AUTHORED_HEAL_SLOTS = frozenset(
    {
        ("Naafiri", "Q"),
    }
)


def _has_support_attributes(champion_data: dict[str, Any]) -> bool:
    memo = _SUPPORT_ATTRS_MEMO.get(id(champion_data))
    if memo is not None and memo[0] is champion_data:
        return memo[1]
    found = any(
        leveling.get("attribute") in _SUPPORT_ATTRIBUTES
        for slot in ("Q", "W", "E", "R")
        for effect in _ability(champion_data, slot).get("effects", [])
        for leveling in effect.get("leveling", [])
    )
    _SUPPORT_ATTRS_MEMO[id(champion_data)] = (champion_data, found)
    return found


# The attribute names and target-scope markers below are pure cached-JSON
# facts per ability, so they are derived once per ability object (identity-
# verified on every hit) instead of per optimizer candidate.
_SUPPORT_PROFILE_MEMO: dict[int, tuple[dict, tuple]] = {}


def _sourced_cast_time(cast: dict[str, Any], *, slot: str) -> float:
    """Return one finite authored cast time; never default a missing timestamp."""
    if "time" not in cast:
        raise ValueError(f"Support cast {slot} is missing its sourced time")
    value = cast["time"]
    if isinstance(value, bool):
        raise ValueError(f"Support cast {slot} time must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Support cast {slot} time must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"Support cast {slot} time must be finite")
    return parsed


def _support_profile(
    ability: dict[str, Any],
) -> tuple[str | None, str | None, bool, str]:
    memo = _SUPPORT_PROFILE_MEMO.get(id(ability))
    if memo is not None and memo[0] is ability:
        return memo[1]
    shield_attr = _first_attribute(ability, ("Shield Strength", "Shield"))
    heal_attr = _first_attribute(
        ability,
        ("Total Heal", "Heal", "Heal Per Tick", "Minimum Heal", "Maximum Heal"),
    )
    description = " ".join(
        str(effect.get("description", "")) for effect in ability.get("effects", [])
    ).lower()
    target_self = any(
        marker in description
        for marker in (
            "shields herself",
            "shields himself",
            "shields themselves",
            "shield themselves",
            "grants herself",
            "granting herself",
            "grants himself",
            "granting himself",
            "grants themselves",
            "granting themselves",
            "or herself",
            "or himself",
            "or themselves",
            "herself or",
            "himself or",
            "themselves or",
            "around herself",
            "around himself",
            "around themselves",
            "heals herself",
            "heals himself",
            "heals themselves",
            "healing herself",
            "healing himself",
            "healing themselves",
            "healing and cleansing herself",
            "healing and cleansing himself",
            "healing and cleansing themselves",
            "to herself",
            "to himself",
            "to themselves",
        )
    )
    all_teammates = any(
        marker in description
        for marker in (
            "all allied champions",
            "all allied units",
            "nearby allied champions",
            "nearby allied units",
            "nearby allies",
            "all allies",
        )
    )
    # Several reviewed support casts affect the caster and another selected
    # ally (Sona W), or the caster plus every nearby ally (Soraka R, Janna R,
    # Seraphine W, Milio R).  Keep those scopes explicit so the roster
    # resolver does not silently drop the self packet or treat a self-only
    # cast as an area effect.
    if target_self and all_teammates:
        target_scope = "self_and_all_teammates"
    elif target_self and any(
        f"{pronoun} and" in description
        for pronoun in ("herself", "himself", "themselves")
    ):
        target_scope = "self_and_one_teammate"
    elif target_self and any(
        f"{pronoun} or" in description or f"or {pronoun}" in description
        for pronoun in ("herself", "himself", "themselves")
    ):
        # Self-or-target casts (Karma E, Orianna E) use the deterministic
        # selected-teammate branch when a roster target exists, while the
        # ledger falls back to self when no teammate is selected.
        target_scope = "one_teammate"
    elif target_self:
        target_scope = "self"
    elif all_teammates:
        target_scope = "all_teammates"
    else:
        target_scope = "one_teammate"
    profile = (shield_attr, heal_attr, target_self, target_scope)
    _SUPPORT_PROFILE_MEMO[id(ability)] = (ability, profile)
    return profile


def derive_ally_effects(
    champion_data: dict[str, Any],
    level: int,
    stats: dict[str, float],
    cast_timeline: list[dict[str, Any]],
    ability_ranks: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Return explicit shield/heal packets and their sourced cast times.

    The timeline has no player cursor/target selection, so packets carry a
    sourced target scope for the coupled resolver to apply deterministically:
    ``self``, one selected teammate, or all selected teammates.  A missing
    scope is never silently treated as an area effect.
    """
    if not _has_support_attributes(champion_data):
        return []
    effects: list[dict[str, Any]] = []
    requested_ranks = ability_ranks or {}
    for slot in ("Q", "W", "E", "R"):
        ability = _ability(champion_data, slot)
        if not ability:
            continue
        default_rank = get_ability_rank(slot, level, champion_data.get("name", ""))
        requested_rank = requested_ranks.get(slot, default_rank)
        try:
            rank = max(0, int(requested_rank))
        except (TypeError, ValueError):
            rank = default_rank
        if rank < 1:
            continue
        # E8c: a module-authored shield slot is the module's exact receipt
        # (level-indexed bases, stat scalings, and sourced duration).  The
        # scanner defers to it so the ledger never grants the same shield
        # twice from two derivations of one ability.
        if (champion_data.get("name", ""), slot) in _MODULE_AUTHORED_SHIELD_SLOTS or (
            champion_data.get("name", ""),
            slot,
        ) in _MODULE_AUTHORED_HEAL_SLOTS:
            continue
        shield_attr, heal_attr, target_self, target_scope = _support_profile(ability)
        champion_key = (champion_data.get("name", ""), slot)
        # E8d follow-up: a sourced per-champion attribute override wins over
        # the generic lookup (Bard W fully-charged shrine).
        heal_attr = _CHAMPION_HEAL_ATTR.get(champion_key, heal_attr)
        # P1-3: a sourced per-champion shield attribute override wins over
        # the generic lookup (Lux W's two stacked shields == Maximum Shield).
        shield_attr = _CHAMPION_SHIELD_ATTR.get(champion_key, shield_attr)
        # E8d follow-up: prose-only module heals (Taric Q) carry no JSON heal
        # attribute; the registry makes the slot a heal candidate anyway.
        if heal_attr is None and champion_key in _MODULE_HEAL_AMOUNTS:
            heal_attr = "_module_prose_heal"
        # E8d follow-up: a sourced per-champion target-scope override wins
        # over the description markers (Yuumi E attached anchor).
        target_scope = _SCOPE_OVERRIDES.get(champion_key, target_scope)
        if shield_attr is None and heal_attr is None:
            continue
        casts = [event for event in cast_timeline if event.get("slot") == slot]
        for cast in casts:
            # Validate every authored support cast, even when its resolved
            # packet is zero or intentionally omitted (for example, a
            # per-tick heal without a complete cadence).
            _sourced_cast_time(cast, slot=slot)
            if shield_attr is not None:
                amount = extract_named(ability, shield_attr, rank, stats, {})
                if amount > 0:
                    effects.append(
                        {
                            "time": _sourced_cast_time(cast, slot=slot),
                            "kind": "shield",
                            "amount": float(amount),
                            "source": f"{ability.get('name', slot)} · {shield_attr}",
                            "slot": slot,
                            "target_self": target_self,
                            "target_scope": target_scope,
                            "rank": rank,
                        }
                    )
            # E9-3: a module/healing-rule-authored heal slot is the exact
            # receipt (level-indexed bases, missing-health terms, and a
            # dragon-form gate the scanner cannot see).  The scanner defers
            # so the ledger never pays the same heal twice from two
            # derivations of one ability.
            if (champion_data.get("name", ""), slot) in _MODULE_AUTHORED_HEAL_SLOTS:
                heal_attr = None
            if heal_attr is not None:
                module_heal = _MODULE_HEAL_AMOUNTS.get(champion_key)
                if module_heal is not None:
                    base, ap_ratio, max_health_ratio = module_heal
                    amount = (
                        base
                        + ap_ratio * float(stats.get("ability_power", 0.0))
                        + max_health_ratio * float(stats.get("health", 0.0))
                    )
                    source_label = (
                        f"{ability.get('name', slot)} · prose heal "
                        f"(25 + 15% AP + 1% max HP per charge, 1 charge)"
                    )
                else:
                    amount = extract_named(ability, heal_attr, rank, stats, {})
                    source_label = f"{ability.get('name', slot)} · {heal_attr}"
                # A per-tick entry is not a complete heal packet without its
                # authored duration/tick cadence; fail closed here rather than
                # multiplying a guessed number.
                if heal_attr == "Heal Per Tick":
                    continue
                if amount > 0:
                    effects.append(
                        {
                            "time": _sourced_cast_time(cast, slot=slot),
                            "kind": "heal",
                            "amount": float(amount),
                            "source": source_label,
                            "slot": slot,
                            "target_self": False,
                            "target_scope": target_scope,
                            "rank": rank,
                        }
                    )
    return sorted(effects, key=lambda event: (event["time"], event["kind"]))
