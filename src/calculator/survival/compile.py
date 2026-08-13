"""What the compiled score kernel refuses, and what a strike-back costs.

The compiler itself moved to ``program/compile.py`` at Phase 4 S4 -- one
``SurvivalAction`` constructor, on the logical side of the layering.  What
stays here is what ``survival/`` genuinely owns: the kernel's own refusals
and the two prices a strike-back needs before the walk runs.

**The refusals.**  Compilation fails closed by transition type: a packet,
heal or resolved support template carrying a state transition the score
ledger cannot represent yields a named receipt, and the caller falls back to
the authoritative receipt walk instead of silently dropping the transition
(Phase 1's contract, kept verbatim).  These four functions are statements
about the *kernel's* representation, which is why they did not follow the
compiler out: a later stage that teaches the score ledger a new transition
edits the ledger and its refusal together, in one package.

**The prices.**  ``thorns_return_damage`` and ``champion_wound_tuple`` are
priced before the walk by both adapters, and ``heal_trigger_key`` is the
identity a self-heal carries back to the event that caused it.

``UncompilableActionError`` is raised from ``program/compile.py`` and from
the compile-stage capability checks; it is declared here because ``invariant``
-- the flag saying a failure was search-invariant rather than
candidate-local -- is a fact about the kernel's own compilation, and the
rung ladder reads it back.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..resistance import apply_magic_penetration, apply_resistance
from .actions import ActionKind, SurvivalAction


class UncompilableActionError(ValueError):
    """A packet/loadout transition the compiled score kernel cannot represent.

    Raised by ``program.compile`` and the compile-stage capability checks
    so the caller falls back to the authoritative event walk instead of
    silently dropping a state transition (issue #137).  ``receipt`` names
    the transition, ``source`` names where it was authored, and
    ``invariant`` marks failures in search-invariant compilation (roster
    pairs, signature panels) so the caller can skip re-attempting the
    compiled path for the rest of the search.
    """

    def __init__(self, *, receipt: str, source: str, invariant: bool = False) -> None:
        super().__init__(f"uncompilable action {receipt!r} from {source!r}")
        self.receipt = receipt
        self.source = source
        self.invariant = invariant


def unrepresentable_heal_receipt(event: Mapping[str, Any]) -> str | None:
    """Return a named receipt when a heal packet carries a transition the
    compiled score kernel cannot stage, else None.

    ``healing_category`` is not a rejection: every compiled heal action
    carries the field, so the kernel's vamp carve-outs (received-healing
    multiplier exemption, ichor conversion) apply identically (issue #169).
    """
    if event.get("overheal_to_shield"):
        return "overheal_to_shield"
    if event.get("requires_holder_health_ratio"):
        return "requires_holder_health_ratio"
    if event.get("requires_damage_free_seconds"):
        return "requires_damage_free_seconds"
    if event.get("_deferred"):
        return "deferred_transition"
    return None


def unrepresentable_damage_receipt(event: Mapping[str, Any]) -> str | None:
    """Return a named receipt when a damage packet carries a transition the
    compiled score kernel cannot stage, else None."""
    if event.get("execute_threshold_ratio") is not None:
        return f"execute_threshold={event.get('execute_source', '')}"
    if event.get("redirect_fraction"):
        return "redirect_fraction"
    if event.get("_deferred"):
        return "deferred_transition"
    if event.get("self_shield"):
        return "self_shield_payload"
    return None


def unrepresentable_template_receipt(template: Mapping[str, Any]) -> str | None:
    """Return a named receipt when a resolved support template cannot ride
    the compiled score kernel, else None."""
    kind = str(template.get("kind", ""))
    if kind not in {"shield", "heal"}:
        return f"support_kind={kind}"
    try:
        duration = max(0.0, float(template.get("duration", 0.0) or 0.0))
    except (TypeError, ValueError):
        duration = 0.0
    if duration > 0.0:
        return f"support_duration={template.get('duration')}"
    if template.get("amount_formula") is not None:
        return "support_amount_formula"
    return unrepresentable_heal_receipt(template)


def heal_trigger_key(event: Mapping[str, Any]) -> tuple[str, float, int]:
    """The trigger identity carried by an engine self-heal event."""
    return (
        str(event.get("_trigger_source", "")),
        round(float(event.get("_trigger_time", 0.0)), 9),
        int(event.get("_trigger_sequence", 0) or 0),
    )


def champion_wound_tuple(
    champion_wounds: Mapping[str, Any] | None,
    source_key: str,
    damage: float,
) -> tuple[float, str] | None:
    """Resolve one event's champion-applied wound tuple for the compiled walk.

    Mirrors ``_pair_packet``'s stamping: a wound-declaring ability hit
    (Katarina R, Varus E) rides its damaging event as ``(duration, label)``
    exactly like a thorns strike-back wound, so the walk's ``wound`` branch
    applies the patch-wide factor without new arithmetic.
    """
    if not champion_wounds:
        return None
    packet = champion_wounds.get(str(source_key))
    if packet is None or float(damage or 0.0) <= 0.0:
        return None
    return (
        float(packet.get("duration", 0.0)),
        str(packet.get("source", "Grievous Wounds")),
    )


def thorns_return_damage(profile: Any, wearer: Any, striker: Any) -> float:
    """Price one thorns strike-back against the striker's resistances.

    Thorns damage benefits from the wearer's penetration and is mitigated
    by the striker like any other damage of its type.  Lives here (not in
    the kernel) because both the receipt scheduler and the compiler price
    strike-backs before the walk runs.
    """
    if profile.damage_type != "magic":
        raise ValueError(
            f"{profile.item_name} thorns damage type "
            f"{profile.damage_type!r} is not supported"
        )
    # Bramble's fixed packet keeps a zero ratio.  Thornmail supplies an
    # authored bonus-armor ratio through ``ThornsEffect``; read it through a
    # compatibility default so cached Bramble packets remain unchanged while
    # the item layer rolls out the typed field.
    bonus_armor_ratio = max(
        0.0, float(getattr(profile, "bonus_armor_ratio", 0.0) or 0.0)
    )
    bonus_armor = max(0.0, float(wearer.stats.get("bonus_armor", 0.0) or 0.0))
    raw_damage = float(profile.damage) + bonus_armor_ratio * bonus_armor
    resistance = apply_magic_penetration(
        float(striker.stats.get("magic_resistance", 0.0)),
        float(wearer.stats.get("magic_penetration_flat", 0.0)),
        float(wearer.stats.get("magic_penetration_percent", 0.0)) / 100.0,
    )
    return apply_resistance(raw_damage, resistance)


def coalesce_darius_q_heals(
    actions: Iterable[SurvivalAction],
) -> list[SurvivalAction]:
    """Coalesce compiled Decimate heals across pair packets.

    Replaces the former ``_coalesce_compiled_darius_q_heals``: the receipt
    walk coalesces the healing ledger before the walk, the score compiler
    coalesces the flat actions after building them — same semantics over
    the typed representation.
    """
    if isinstance(actions, list) and not any(
        action.kind is ActionKind.HEAL and action.source == "Decimate"
        for action in actions
    ):
        # No Decimate heal compiled: nothing to coalesce, keep the caller's
        # own per-evaluation list instead of rebuilding it.
        return actions
    groups: dict[tuple[int, float, int, str], tuple[int, int]] = {}
    kept: list[SurvivalAction] = []
    for action in actions:
        if action.kind != ActionKind.HEAL or action.source != "Decimate":
            kept.append(action)
            continue
        key = (
            int(action.attacker),
            float(action.time),
            int(action.sort_key[2]),
            str(action.source),
        )
        first = groups.get(key)
        if first is None:
            groups[key] = (len(kept), 1)
            kept.append(action)
            continue
        first_index, count = first
        groups[key] = (first_index, count + 1)
    for first_index, count in groups.values():
        action = kept[first_index]
        formula = action.amount_formula
        if not callable(formula):
            continue

        def coalesced(current_health, maximum_health, formula=formula, count=count):
            return max(0.0, float(formula(current_health, maximum_health))) * min(
                3, count
            )

        kept[first_index] = action._replace(amount_formula=coalesced)
    return kept


__all__ = [
    "UncompilableActionError",
    "champion_wound_tuple",
    "coalesce_darius_q_heals",
    "thorns_return_damage",
    "heal_trigger_key",
    "unrepresentable_damage_receipt",
    "unrepresentable_heal_receipt",
    "unrepresentable_template_receipt",
]
