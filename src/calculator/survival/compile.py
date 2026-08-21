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
identity a self-heal carries back to the event that caused it -- normalized
at ``TRIGGER_TIME_KEY_DIGITS``, which lives here beside its reader and is
imported by the compiler that writes the other side of the same lookup.

``UncompilableActionError`` is raised from ``program/compile.py`` and from
the compile-stage capability checks; it is declared here because ``invariant``
-- the flag saying a failure was search-invariant rather than
candidate-local -- is a fact about the kernel's own compilation, and the
rung ladder reads it back.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from ..resistance import apply_magic_penetration
from .actions import ActionKind, SurvivalAction
from .pricing import mitigate_declared


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

    P2 Slice 4: a heal packet carrying the cleanse marker (Mikael's Purify)
    fails closed with ``support_cleanse`` — the compiled kernel cannot
    reproduce the action-downtime truncation, so the caller falls back to
    the authoritative receipt walk instead of silently dropping the
    cleanse (score/receipt parity, HANDOVER section 9).
    """
    if event.get("cleanse") or event.get("cleanse_item"):
        return "support_cleanse"
    if event.get("overheal_to_shield"):
        return "overheal_to_shield"
    # ``requires_holder_health_ratio`` (Knight's Vow Sacrifice heals,
    # P3 package 3S) is enforced by the shared kernel's heal gate — the
    # compiled walk applies the identical ordered check, so the template
    # is representable.
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


# The resolved support kinds the compiled score ledger can stage.
#
# ``damage_modifier`` joined the set at the H5 stage, which is where the
# kernel was taught timed, typed damage modifiers (D-101; the umbrella's
# ``[H]`` table records the scoping and this module does not re-rule it).
# The transition itself was never the missing half: ``_apply_damage_modifier``
# and ``_apply_cross_participant_modifiers`` are kernel functions both
# adapters have always driven, so what refused was *compilation*.  Widening
# the set is therefore a statement about the compiler's reach and not about
# the walk's, which is why the modifier's own refusals get a function of
# their own below rather than clauses inside the shield/heal ladder: a heal's
# duration is a reason to decline and a modifier's duration is the mechanic.
_STAGED_SUPPORT_KINDS = frozenset({"shield", "heal", "damage_modifier"})


def unrepresentable_modifier_receipt(template: Mapping[str, Any]) -> str | None:
    """Return a named receipt when an armed damage modifier carries a
    transition the compiled score kernel cannot stage, else None.

    Deliberately short, and the shortness is the finding: an armed modifier
    is a timed entry in ``state["active_damage_modifiers"]`` that the shared
    kernel applies, expires and refreshes identically under either ledger,
    so a duration, a persistence flag, a resistance reduction and a
    next-event consumption are all *representable* and none of them is a
    reason to decline.

    What is not representable is an amount only the walk can price — a live
    formula, or a transition a deferral batch owns — and those are the two
    clauses here.  The one refusal this function deliberately does **not**
    make is the class declaration: an armed modifier with no
    ``damage_classes``/``attack_classes`` must raise in
    ``declared_modifier_classes`` on both paths (D-04), and declining it
    here would convert that fail-loud into a quiet fall back to the walk
    that raises anyway.
    """
    if template.get("amount_formula") is not None:
        return "modifier_amount_formula"
    if template.get("_deferred"):
        return "deferred_transition"
    # A *timed* modifier with no window is not a modifier the kernel arms:
    # the walk keeps an entry only while ``until > time``, so a zero window
    # is an authoring failure and reads back as one instead of compiling to
    # an entry that can never apply.  A persistent modifier declares no
    # window and is exempt.
    if not template.get("persistent") and _template_duration(template) <= 0.0:
        return "support_duration=0"
    # The payloads themselves must be numbers the kernel can arithmetic on.
    # A non-finite or negative multiplier is not a modifier the score ledger
    # can stage identically to the walk, and mis-compiling one is silent, so
    # each reads back as its own named receipt.
    if template.get("damage_reduction"):
        amount = _finite_or_none(template.get("amount", 0.0), floor=0.0)
        if amount is None:
            return "support_damage_modifier_amount=nonfinite"
    else:
        multiplier = _finite_or_none(template.get("multiplier", 1.0) or 1.0, floor=0.0)
        if multiplier is None:
            return "support_damage_modifier_multiplier=nonfinite"
    for field in ("armor_reduction_percent", "mr_reduction_percent"):
        if _finite_or_none(template.get(field, 0.0)) is None:
            return f"support_damage_modifier_{field}=nonfinite"
    return None


def _finite_or_none(value: Any, *, floor: float | None = None) -> float | None:
    """One template payload as a finite float, or ``None`` if it is not one.

    ``None`` is the refusal, so a caller that forgets to check it gets a
    ``TypeError`` rather than a mis-compiled zero.
    """
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if floor is not None and number < floor:
        return None
    return number


def _template_duration(template: Mapping[str, Any]) -> float:
    """One template's armed window, clamped at zero and never raising."""
    number = _finite_or_none(template.get("duration", 0.0))
    return max(0.0, number) if number is not None else 0.0


# The resolved support kinds whose whole transition is a timed *state* grant:
# the kernel arms the state, expires it on its own window, and both adapters
# read back the same armed entry, so the only thing that can refuse one is a
# window it cannot arm.
_STAGED_STATE_KINDS = frozenset(
    {"spell_shield", "stasis", "invulnerability", "untargetable"}
)


def unrepresentable_template_receipt(template: Mapping[str, Any]) -> str | None:
    """Return a named receipt when a resolved support template cannot ride
    the compiled score kernel, else None."""
    if template.get("_guardian_reactive"):
        return "guardian_reactive_shield"
    kind = str(template.get("kind", ""))
    if kind == "crowd_control_resist":
        # P2 Slice 8: the Dr. Mundo passive IMMUNITY arm is representable
        # -- it only sets the armed state, and the RESIST gate lives in the
        # shared kernel (``_apply_crowd_control``), so both adapters apply
        # it identically (the score ledger ignores the receipts).
        return None
    if kind in _STAGED_STATE_KINDS:
        if kind == "spell_shield" and template.get("on_block_heal_amount", 0.0):
            return "support_spell_shield_on_block_heal"
        if _template_duration(template) <= 0.0:
            return "support_duration=0"
        return None
    if kind not in _STAGED_SUPPORT_KINDS:
        return f"support_kind={kind}"
    if kind == "damage_modifier":
        return unrepresentable_modifier_receipt(template)
    if template.get("amount_formula") is not None:
        # An amount only the walk can price: the compiler stamps a number
        # and would stamp the wrong one.
        return "support_amount_formula"
    if kind == "shield":
        # Timed shields are represented by the shared typed shield ledger.
        # The support action carries its pool and any while-held CC immunity.
        return unrepresentable_heal_receipt(template)
    # Timed heals (Cryptbloom's Life From Death carries its sourced 1.75s
    # nova window on the packet) apply FLAT in both walks — the shared
    # kernel never reads action.duration for heals — so the duration is
    # metadata, not a rejection (P3 package 3K).
    return unrepresentable_heal_receipt(template)


# The digits a trigger *lookup* is normalized to.  Not presentation --
# nothing publishes this number -- and not the precision registry's, whose
# scope is ``program/``: the reader of this tolerance is ``heal_trigger_key``
# below, on the kernel side of a boundary that runs ``program -> survival``
# and never back.  So the one home is here, and the logical layer imports it.
#
# One home because the two sides must agree exactly.  A lookup normalized to
# nine digits where it is written and ten where it is read silently stops
# matching, and a self-heal that loses its trigger link is not an error: it
# is a heal the walk applies unconditionally.
TRIGGER_TIME_KEY_DIGITS = 9


def trigger_time_key(value: float) -> float:
    """One timestamp, normalized to the digits a trigger lookup keys on."""
    return round(float(value), TRIGGER_TIME_KEY_DIGITS)


def heal_trigger_key(event: Mapping[str, Any]) -> tuple[str, float, int]:
    """The trigger identity carried by an engine self-heal event.

    The *reader* of the key the compiler writes, which is why it normalizes
    its timestamp through :func:`trigger_time_key` rather than spelling a
    digit count of its own.
    """
    return (
        str(event.get("_trigger_source", "")),
        trigger_time_key(event.get("_trigger_time", 0.0)),
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

    This is the tree's oldest from-raw price — a declared magnitude the
    walk's own side mitigates, rather than a number the pair engine already
    mitigated — so the last step is :func:`~.pricing.mitigate_declared`
    rather than a second spelling of it.  What stays here is the half that
    is genuinely a strike-back's: which resistance the return damage meets,
    and the refusal for a declaration whose damage type this mechanic has
    never carried.
    """
    if profile.damage_type != "magic":
        raise ValueError(
            f"{profile.item_name} thorns damage type "
            f"{profile.damage_type!r} is not supported"
        )
    # Bramble's fixed packet keeps a zero ratio; Thornmail authors one.
    bonus_armor_ratio = max(0.0, float(profile.bonus_armor_ratio))
    bonus_armor = max(0.0, float(wearer.stats.get("bonus_armor", 0.0) or 0.0))
    raw_damage = float(profile.damage) + bonus_armor_ratio * bonus_armor
    resistance = apply_magic_penetration(
        float(striker.stats.get("magic_resistance", 0.0)),
        float(wearer.stats.get("magic_penetration_flat", 0.0)),
        float(wearer.stats.get("magic_penetration_percent", 0.0)) / 100.0,
    )
    return mitigate_declared(raw_damage, profile.damage_type, resistance)


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
    "TRIGGER_TIME_KEY_DIGITS",
    "UncompilableActionError",
    "champion_wound_tuple",
    "coalesce_darius_q_heals",
    "thorns_return_damage",
    "heal_trigger_key",
    "trigger_time_key",
    "unrepresentable_damage_receipt",
    "unrepresentable_heal_receipt",
    "unrepresentable_modifier_receipt",
    "unrepresentable_template_receipt",
]
