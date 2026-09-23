"""The one place ``src/`` builds a survival action.

Every action is one of the records in ``survival/action_families``, and
every expression building one is in this module:
``tests/test_program_structure.py`` counts those outside it, and the count
is zero.  One home for construction is one place to change a field, so the
receipt adapter and the score compiler cannot stamp one differently.

Three builders:

* :func:`action_from_event` converts one authored packet dict -- the receipt
  path's unit of work.
* :class:`WalkCompiler` accumulates the score path's flat actions with stable
  per-action ids.
* :func:`revive_candidate_actions` and :func:`grey_health_heal_action` author
  the two action shapes neither of the first two produces.

**Why the kernel does not import this module.**  ``program -> survival`` runs
one way, so ``survival/receipt_state`` cannot call the builder it needs when
the walk authors a recovery packet mid-flight.  It takes the builder as a
constructor parameter instead -- the same device ``build_state``'s
``below_half_healing_bonus`` and ``TransitionContext``'s
``regeneration_windows`` already use, and for the same reason: the boundary
that builds the walk compiles what the walk may not reach and hands it over.
"""

# file-length-ok: the module IS the one-constructor boundary its docstring
# argues for — splitting it puts SurvivalAction fields back in two files,
# which is the disagreement (a field one builder stamps and the other does
# not) this file exists to make impossible.
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, MutableMapping, Sequence
from enum import Enum
from operator import itemgetter
from typing import Any, NamedTuple

from ..ability_spec import AttackClass, DamageClass
from ..cast_event_row import cast_slot as _row_cast_slot
from ..cast_event_row import cast_time as _row_cast_time
from ..defensive_effects import armed_revive
from ..delivery_facts import CombatantFacts
from ..event_row_field import build_stat_field as _stat
from ..event_row_field import optional_field
from ..fight_result_row import result_breakdown as _row_breakdown
from ..fight_result_row import result_cast_timeline as _row_cast_timeline
from ..fight_result_row import result_control_events as _row_control_events
from ..fight_result_row import result_damage_events as _row_damage_events
from ..fight_result_row import result_self_healing_events as _row_self_heals
from ..fight_result_row import result_timeline_coverage as _row_timeline_coverage
from ..fight_result_row import result_total_damage as _row_total_damage
from ..heal_event_row import healed_amount, healed_category, healed_source, healed_time
from ..healing_reduction import amplifies_recovery
from ..interpreters.part_amp import StaticHolderAmps
from ..item_effects import ThornsEffect
from ..ledger_inputs import LightRow
from ..resistance import (
    apply_armor_penetration,
    apply_magic_penetration,
    apply_resistance,
)
from ..survival.action_families import (
    CORE,
    FAMILY_OF,
    DamageAction,
    HealAction,
    WideAction,
)
from ..survival.actions import (
    action_key,
    event_sequence,
    participant_order,
)
from ..survival.classify import (
    UTILITY_KINDS,
    classify_event_kind,
    classify_prefetched,
    declared_class_set,
    support_transition_rank,
)
from ..survival.compile import (
    UncompilableActionError,
    champion_wound_tuple,
    heal_trigger_key,
    thorns_return_damage,
    trigger_time_key,
    unrepresentable_damage_receipt,
    unrepresentable_heal_receipt,
    unrepresentable_template_receipt,
)
from ..survival.event_slots import EVENT_SLOTS, NO_SLOT
from ..survival.phases import TransitionRank, ordering_slot
from ..survival.pricing import (
    AuthoredDeclaration,
    DeclaredPacket,
    RoutingProvenance,
    route_declared_packet,
)
from ..survival.typed_action import ActionKind, SurvivalAction
from ..trigger_stream import HolderStacking, is_immobilizing_event
from .amp import NO_AMPS, AmpRiders, live_amp_for
from .capability import arming_stacking, dropped_pair_previews, pair_preview_sources


class PairFight(NamedTuple):
    """One pair fight's own facts: whose rows these are, and against whom.

    The three a pair fight cannot see for itself, and its caller can:

    * ``defender_index`` -- the defender's slot in the attacker's ordered
      roster.  A later target is re-priced to the sourced reduced heal
      amount when the engine authored one (Vladimir's Hemoplague).
    * ``champion_wounds`` -- the attacker's wound-declaring source keys
      (Katarina R, Varus E) mapped to their packets, so a champion wound
      rides its damage event as the same receipt an item wound does.
    * ``amps`` -- the attacker's amplifiers.  ``live`` riders ride their own
      damage packets so the bonus dies with its host, and the default is
      empty because most holders declare none, never because a caller may
      leave it out.  ``holder`` is the static, pair-local factor a re-priced
      preview's declaration needs, required rather than defaulted the moment
      this fight carries one.
    """

    result: Mapping[str, Any]
    attacker_id: str
    defender_id: str
    defender_index: int = 0
    champion_wounds: Mapping[str, Any] | None = None
    amps: AmpRiders = NO_AMPS


class WalkSlots(NamedTuple):
    """Where one pair fight's staged actions are filed, and by what window.

    Every field is bookkeeping the walk owns and the fight cannot see for
    itself: the two roster slots the actions are filed under, the fight
    window that bounds them, the attacker's grievous packs, the cross-fight
    heal dedup this fight replays into, and the search-lifetime cache of
    this pair's positional event-id strings.  The last two are written
    through, so each fight takes its own record: a shared one carries one
    fight's event ids into the next, and the coupled walk then sees two
    applied contributions for one mechanic.

    ``suppress_actor_wide_heals`` marks a fight whose actor-wide heal copies
    are never the kept copy: an enemy attacker's ordered pair list is
    ``[main, *allies]``, so the walk always keeps the main-pair copy and the
    ally-pair copies are skipped, because the engine may price them
    differently per defender (Dr. Mundo's Maximum Dosage).  Trigger-linked
    actor-wide heals still fail closed before the skip.
    """

    attacker_i: int
    defender_i: int
    grievous_by_dtype: Mapping[str, Any]
    duration: float
    heal_dedup: dict[tuple[str, float], float]
    id_strings: list[str]
    suppress_actor_wide_heals: bool = False


def projection_only() -> WalkSlots:
    """What the receipt projection files: nothing, in its own record."""
    return WalkSlots(-1, -1, {}, 0.0, {}, [])


class PairView:
    """One pair fight as the roster composition reads it.

    The receipt projection of the same compile the score panels take: every
    field on an enriched event is a value :meth:`WalkCompiler._compile_pair`
    already decided for the action beside it, so the two representations of
    one fight cannot drift.

    ``result`` is the fight as the roster composes it — pair previews
    removed, because a row the registry declares ``THEORETICAL`` is a preview
    of a number the coupled walk owns and the two must never be in one total.
    The engine's own result stays untouched: that is what the per-pair
    ``fights`` receipt publishes, and there the preview *is* the answer.

    ``support`` and ``support_denials`` are the attacker's resolved support
    templates, memoized by the composition on first use; a cached fight
    serves them to every later evaluation.

    ``amps`` travels with the fight because its riders are facts about this
    pair, and resolving them is not free: a search that re-compiles one
    cached fight into a panel per defensive signature would otherwise pay
    for them once per signature instead of once per pair.
    """

    __slots__ = (
        "amps",
        # The engine's own result, unmodified: what the per-pair ``fights``
        # receipt publishes and what the score panels compile.
        "engine",
        # The event-id string of each compiled damage action, so a self-heal
        # can publish the id of the hit that caused it.  The compiler already
        # resolved that link by action index; this is the same link one
        # representation over.
        "event_id_by_aidx",
        "events",
        "heals",
        "result",
        "source_names",
        "support",
        "support_denials",
    )

    def __init__(
        self,
        result: Mapping[str, Any],
        amps: AmpRiders = NO_AMPS,
    ) -> None:
        self.engine: Mapping[str, Any] = result
        self.result: Mapping[str, Any] = result
        self.amps = amps
        self.events: list[dict[str, Any]] = []
        self.heals: list[dict[str, Any]] = []
        self.source_names: dict[str, dict[str, Any]] = {}
        self.support: Any = None
        self.support_denials: Any = None
        self.event_id_by_aidx: dict[int, str] = {}


def _enriched_damage_event(
    row: Mapping[str, Any],
    attacker_id: str,
    defender_id: str,
    event_id: str,
    *,
    is_ability: bool,
    ability_instance: Any,
    basic_attack: bool,
    wound: tuple[float, str] | None,
    time_value: float,
    source_row: Any,
    baseline_fields: Mapping[str, float],
    live_amp: Any,
    declared: Any,
    sort_key: tuple[Any, ...],
) -> dict[str, Any]:
    """One compiled damage row, as the receipt composition reads it.

    Every argument past the row is a value the compiler already decided for
    the action beside this dict; nothing here re-derives one.  A field the
    fight did not produce stays *absent* rather than present-and-neutral —
    the walk tells "nobody declared one" from "one measured zero".
    """
    enriched = {
        **row,
        "attacker": attacker_id,
        "target": defender_id,
        "_event_id": event_id,
        "is_ability": is_ability,
        "ability_instance": ability_instance,
    }
    if basic_attack:
        enriched["basic_attack"] = True
    if wound is not None:
        # When the window closes is the annotator's answer, not the receipt
        # view's: the two other sites that arm a wound already write it here,
        # and the view computing it for the third was the one place a
        # published timestamp had two producers.
        enriched["grievous_duration"] = wound[0]
        enriched["_wound_source"] = wound[1]
        enriched["_wound_until"] = time_value + wound[0]
    # Multi-target rows are authored on the engine breakdown.  Carry the same
    # target-allocation receipt onto each ordered packet so the coupled
    # timeline can prove which roster slot received it instead of displaying
    # an unexplained aggregate secondary hit.
    if isinstance(source_row, Mapping) and isinstance(
        source_row.get("targeting"), Mapping
    ):
        enriched["targeting"] = dict(source_row["targeting"])
    enriched.update(baseline_fields)
    if live_amp is not None:
        enriched["_live_amp"] = live_amp
    if declared is not None:
        enriched["_declared"] = declared
    enriched["_sk"] = sort_key
    return enriched


def _without_pair_previews(
    result: Mapping[str, Any],
    result_breakdown: Mapping[str, Any],
    previewed: frozenset[str],
) -> Mapping[str, Any]:
    """The pair result as the roster composes it — previews removed.

    A shallow copy, and only when there is something to remove: the original
    object is what the per-pair ``fights`` receipt publishes, and that is the
    one surface where the preview *is* the answer.  Returning a modified copy
    rather than mutating is what keeps those two readings from becoming one.
    """
    if not previewed:
        return result
    removed = sum(
        # 126 of 24,860 engine breakdown rows carry no ``total_damage``: a
        # row that priced an amount, or one published for its detail alone.
        optional_field(result_breakdown[source], "total_damage", float) or 0.0
        for source in previewed
    )
    return {
        **result,
        "total_damage": _row_total_damage(result) - removed,
        "breakdown": {
            source: entry
            for source, entry in result_breakdown.items()
            if source not in previewed
        },
    }


def pair_view(
    result: Mapping[str, Any],
    attacker_id: str,
    defender_id: str,
    defender_index: int = 0,
    *,
    champion_wounds: Mapping[str, Any] | None = None,
    amps: AmpRiders = NO_AMPS,
) -> PairView:
    """One pair fight's receipt view, through the one packet compiler."""
    view = PairView(result, amps)
    WalkCompiler(0).project_pair_view(
        PairFight(
            result,
            attacker_id,
            defender_id,
            defender_index,
            champion_wounds=champion_wounds,
            amps=amps,
        ),
        view,
    )
    return view


_CAST_SLOTS = frozenset({"Q", "W", "E", "R"})


def is_authored_ability_event(event: Mapping[str, Any]) -> bool:
    """Identify a champion cast without treating passive/proc rows as casts."""
    if "is_ability" in event:
        return bool(event["is_ability"])
    return optional_field(event, "source_key", str) in _CAST_SLOTS


def ability_instance_for_event(
    event: Mapping[str, Any], cast_timeline: Iterable[Mapping[str, Any]]
) -> str | None:
    """Attach a cast ordinal so multi-packet abilities share one shield use.

    The engine stamps its own ``slot:ordinal`` cast id on every packet it can
    attribute to a cast (``control_events`` carry it as ``application_id``);
    this derives the same spelling for the damage rows, which carry the cast
    time but not the id.  Both ordinals are 1-based, so one cast has one
    identity whichever row of it a consumer holds.
    """
    if not is_authored_ability_event(event):
        return None
    slot = optional_field(event, "source_key", str) or ""
    try:
        event_time = optional_field(event, "time", float) or 0.0
    except (TypeError, ValueError):
        return None
    candidates = [
        cast
        for cast in cast_timeline
        if str(_row_cast_slot(cast)) == slot
        and float(_row_cast_time(cast)) <= event_time
    ]
    if not candidates:
        return f"{slot}:{trigger_time_key(event_time)}"
    cast = max(candidates, key=_row_cast_time)
    ordinal = cast.get("ordinal")
    return (
        f"{slot}:{ordinal}"
        if ordinal is not None
        else f"{slot}:{trigger_time_key(float(_row_cast_time(cast)))}"
    )


def declared_packet_of(
    declaration: Any,
    damage_type: str,
    source_key: str,
    holder_amps: StaticHolderAmps | None,
) -> DeclaredPacket:
    """One re-priced packet's declaration, composed for the walk to price.

    The engine ledger carries such a packet as the five facts of an
    :class:`~..survival.pricing.AuthoredDeclaration` and no price: which
    rule authored it, the pre-mitigation magnitude that rule's own
    interpreter compiled, the attack class the rule declares — which is what
    decides *which* of the holder's amplifiers this packet earns — the
    effective resistance the packet itself met, which the pair engine's own
    re-pricing windows keep in step, and the basic-attack swing composition
    it was delivered through, if it was.  The remaining term, the amplifier
    itself, is resolved on this side from the declarations that produce it:
    a walk that took a pre-multiplied number would be reading the pair
    engine's price again under another name.

    One home for both compositions, because a roster composes a pair fight in
    two places and the score path is the one that picks the optimizer's
    winner.

    A packet stamped as re-priced with no declaration on it is a stop, not a
    fallback: the pair engine's number has already left the roster total by
    the time this runs, so returning nothing would delete the family's
    damage — a half-performed move, which is worse than neither half.
    """
    if not isinstance(declaration, tuple) or not 3 <= len(declaration) <= len(
        AuthoredDeclaration._fields
    ):
        raise ValueError(
            f"pair row {source_key!r} is stamped as a re-priced preview and "
            "carries no declaration; the walk has nothing to price and the "
            "pair engine's number has already left the roster total"
        )
    authored = AuthoredDeclaration(*declaration)
    packet = DeclaredPacket(
        raw_amount=float(authored.raw_amount),
        damage_type=damage_type,
        rule_id=str(authored.rule_id),
        holder_amp=holder_amps.factor_for(
            damage_type, AttackClass(authored.attack_class)
        ),
        effective_resistance=authored.effective_resistance,
        swing=authored.swing,
    )
    routing = authored.routing
    if routing is None:
        return packet
    # A routing family re-delivered this packet at a second subject, and what
    # a route does to a packet has exactly one home: the share is applied
    # there and the provenance recorded there, so a site that scaled the
    # magnitude itself would be a second reader of one rule.
    return route_declared_packet(packet, routing)


#: How one event dict states one action field, called as ``read(event, index_of)``.
_Reader = Callable[[Mapping[str, Any], Mapping[str, int]], Any]


def _flag(key: str) -> _Reader:
    """``bool`` of the event's *key*; absent is False."""
    return lambda event, _index_of: bool(event.get(key))


def _text(key: str) -> _Reader:
    """The event's *key* as text; absent is ``""``."""
    return lambda event, _index_of: str(event.get(key, ""))


def _label(key: str) -> _Reader:
    """The event's *key* as text; absent or ``None`` is ``""``."""
    return lambda event, _index_of: str(event.get(key, "") or "")


def _number(key: str) -> _Reader:
    """The event's *key* as a float; absent or falsy is 0.0."""
    return lambda event, _index_of: float(event.get(key, 0.0) or 0.0)


def _share(key: str) -> _Reader:
    """The event's *key* as a float floored at 0.0."""
    return lambda event, _index_of: max(0.0, float(event.get(key, 0.0) or 0.0))


def _value(key: str) -> _Reader:
    """The event's *key* as stated; absent is ``None``."""
    return lambda event, _index_of: event.get(key)


def _optional_number(key: str) -> _Reader:
    """The event's *key* as a float, or ``None`` when the event states none."""

    def read(event: Mapping[str, Any], _index_of: Mapping[str, int]) -> Any:
        value = event.get(key)
        return float(value) if value is not None else None

    return read


def _classes(key: str, vocabulary: type[Enum]) -> _Reader:
    """The class set the event declares under *key*, over *vocabulary*."""
    return lambda event, _index_of: declared_class_set(event.get(key), vocabulary)


def _wound(event: Mapping[str, Any], _index_of: Mapping[str, int]) -> Any:
    """The Grievous Wounds the packet applies, as ``(duration, source)``."""
    duration = float(event.get("grievous_duration", 0.0) or 0.0)
    if duration <= 0.0:
        return None
    return (duration, str(event.get("_wound_source", "Grievous Wounds")))


def _immobilized(event: Mapping[str, Any], _index_of: Mapping[str, int]) -> bool:
    """The bus's immobilize answer, or the bare marker it leaves unclassified."""
    return is_immobilizing_event(event) or bool(event.get("crowd_control"))


def _amplified_recovery(event: Mapping[str, Any], _index_of: Mapping[str, int]) -> bool:
    """Whether heal and shield power reaches this recovery, from its kind."""
    return amplifies_recovery(
        str(event.get("kind", "")), str(event.get("healing_category", ""))
    )


def _shield_gate_subject(event: Mapping[str, Any], index_of: Mapping[str, int]) -> int:
    """The roster slot a shield gate names; ``"attacker"`` is the packet's own."""
    target = event.get("shield_gate_target")
    if target == "attacker":
        target = event.get("attacker")
    return index_of.get(str(target), -1) if target is not None else -1


def _defy_trigger_slot(event: Mapping[str, Any], _index_of: Mapping[str, int]) -> int:
    """The one reference the walk authors, so the key already holds a slot."""
    slot = event.get("_defy_trigger_slot")
    return int(slot) if slot is not None else NO_SLOT


def _batch_slot(event: Mapping[str, Any], _index_of: Mapping[str, int]) -> int:
    """The deferred batch this packet belongs to, as a slot."""
    batch_id = event.get("_deferred_batch_id")
    return EVENT_SLOTS.slot(str(batch_id)) if batch_id else NO_SLOT


def _cc_kind(event: Mapping[str, Any], _index_of: Mapping[str, int]) -> str:
    """The raw control token, copied onto the action and never classified."""
    return str(event.get("cc_kind", ""))


def _utility_kind(event: Mapping[str, Any], _index_of: Mapping[str, int]) -> str:
    """The event's authored kind when it is a utility kind, else ``""``."""
    kind = str(event.get("kind", ""))
    return kind if kind in UTILITY_KINDS else ""


# Every field past the core, by the reader that states it from an event.
# ``execute_source`` has no fallback name: an execution whose packet did not
# carry its item is an unstamped packet.  ``live_amp`` and ``declared`` stay
# ``None`` when nobody declared one, which the kernel tells apart from a zero.
# ``holder`` resolves the packet's owner id to its roster slot, ``-1`` for an
# owner outside the roster.  ``grievous`` is the compiled path's alone.
_FROM_EVENT: Mapping[str, _Reader] = {
    "rebinds_on_ability_hit": _flag("_rebind_on_ability_hit"),
    "damage_type": _text("damage_type"),
    "declared": _value("_declared"),
    "raw_formula": _value("raw_formula"),
    "raw_damage": _number("raw_damage"),
    "grievous": lambda _event, _index_of: None,
    "wound": _wound,
    "reactive": _flag("_reactive"),
    "live_amp": _value("_live_amp"),
    "execute_threshold_ratio": _share("execute_threshold_ratio"),
    "execute_source": _text("execute_source"),
    "deferred": _flag("_deferred"),
    "deferred_batch_slot": _batch_slot,
    "redirect_holder_health_ratio": _share("redirect_holder_health_ratio"),
    "redirect_original_damage": _share("_redirect_original_damage"),
    "is_ability": _flag("is_ability"),
    "basic_attack": _flag("basic_attack"),
    "ability_instance": _value("ability_instance"),
    "immobilized": _immobilized,
    "cc_kind": _cc_kind,
    "cc_duration": _share("cc_duration"),
    "skillshot": _flag("skillshot"),
    "area_damage": _flag("area_damage"),
    "damage_over_time": _flag("damage_over_time"),
    "baseline_effective_armor": _optional_number("_baseline_effective_armor"),
    "baseline_effective_mr": _optional_number("_baseline_effective_mr"),
    "healing_category": _text("healing_category"),
    "amplified_recovery": _amplified_recovery,
    "amount_formula": _value("amount_formula"),
    "requires_existing_shield": _flag("requires_existing_shield"),
    "cast_while_disabled": _flag("cast_while_disabled"),
    "cast_blocked_by_attacker_control": _flag("cast_blocked_by_attacker_control"),
    "cleanse_group": _label("cleanse_group"),
    "requires_maw_lifeline_omnivamp": _flag("requires_maw_lifeline_omnivamp"),
    "shield_gate_subject": _shield_gate_subject,
    "shield_gate_time": _optional_number("shield_gate_time"),
    "requires_holder_health_ratio": _share("requires_holder_health_ratio"),
    "requires_damage_free_seconds": _share("requires_damage_free_seconds"),
    "overheal_to_temporary_health": _flag("overheal_to_temporary_health"),
    "temporary_health_duration": _share("temporary_health_duration"),
    "overheal_to_shield": _flag("overheal_to_shield"),
    "overheal_shield_cap": _share("overheal_shield_cap"),
    "overheal_shield_duration": _share("overheal_shield_duration"),
    "defy_trigger_slot": _defy_trigger_slot,
    "duration": _share("duration"),
    "delay": _share("delay"),
    "health_ratio": _share("health_ratio"),
    "on_block_heal_amount": _share("on_block_heal_amount"),
    "on_block_heal_delay": _share("on_block_heal_delay"),
    "on_block_heal_source": _label("on_block_heal_source"),
    "bonus_attack_speed_percent": _number("bonus_attack_speed_percent"),
    "bonus_move_speed_percent": _number("bonus_move_speed_percent"),
    "bonus_armor": _number("bonus_armor"),
    "bonus_magic_resistance": _number("bonus_magic_resistance"),
    "bonus_health": _number("bonus_health"),
    "ability_power": _number("ability_power"),
    "ability_haste": _number("ability_haste"),
    "on_hit_magic_damage": _number("on_hit_magic_damage"),
    "shield_pool": _label("shield_pool"),
    "crowd_control_immunity_while_shield": _flag("crowd_control_immunity_while_shield"),
    "crowd_control_immunity_source": _label("crowd_control_immunity_source"),
    "persistent": _flag("persistent"),
    "multiplier": lambda event, _index_of: float(event.get("multiplier", 1.0) or 1.0),
    "damage_reduction": _flag("damage_reduction"),
    "next_event_only": _flag("next_event_only"),
    "all_sources": _flag("all_sources"),
    "armor_reduction_percent": _number("armor_reduction_percent"),
    "mr_reduction_percent": _number("mr_reduction_percent"),
    "resistance_type": _text("resistance_type"),
    "holder": lambda event, index_of: index_of.get(str(event.get("owner", "")), -1),
    "damage_classes": _classes("damage_classes", DamageClass),
    "attack_classes": _classes("attack_classes", AttackClass),
    "source_participant": _text("source_participant"),
    "utility_kind": _utility_kind,
    "duration_set": lambda event, _index_of: "duration" in event,
    "cleanse": _flag("cleanse"),
    "cleanse_item": _label("cleanse_item"),
}

#: Each record's readers, in its field order past the core.
_EVENT_READERS: Mapping[type[SurvivalAction], tuple[_Reader, ...]] = {
    family: tuple(_FROM_EVENT[field] for field in family._fields[len(CORE) :])
    for family in set(FAMILY_OF.values())
}


def action_from_event(
    event: Mapping[str, Any],
    phase: TransitionRank,
    subject_index: int,
    index_of: Mapping[str, int],
    *,
    subject_id: str = "",
    aidx: int = -1,
) -> SurvivalAction:
    """Build the typed action for one receipt event.

    The receipt composition converts its ``(sort_key, participant_id,
    event)`` triples through this function once per event; the kernel and
    the annotated ledger then consume the same typed interface the score
    compiler produces.  ``subject_id`` is the ledger bucket the event was
    authored into (the receipt walk's sort key uses it, not the event's
    target field).  The kind picks the record, and the record's fields are
    read through :data:`_FROM_EVENT`; missing optional metadata fails closed
    to the field's neutral value, never to a guessed number.
    """
    get = event.get
    execute_ratio_raw = get("execute_threshold_ratio")
    redirected_raw = get("_redirected")
    kind = classify_prefetched(
        event,
        phase,
        str(get("kind", "")),
        execute_ratio_raw,
        deferred_raw=get("_deferred"),
        redirected_raw=redirected_raw,
        raw_formula=get("raw_formula"),
        raw_damage=float(get("raw_damage", 0.0) or 0.0),
        grievous_duration=float(get("grievous_duration", 0.0) or 0.0),
    )
    attacker_id = get("attacker")
    event_id = get("_event_id")
    time_value = float(get("time", 0.0))
    if not math.isfinite(time_value):
        raise ValueError(
            f"action_from_event: event time must be finite, got "
            f"{time_value!r} (event_id={event_id!r}); a non-finite "
            f"timestamp cannot establish a stable total order"
        )
    trigger_id = get("_trigger_event_id")
    family = FAMILY_OF[kind]
    # The core, in ``CORE`` order.  ``event_slot`` tests ``is not None``
    # rather than truth: an event carrying an empty id string had one.
    return family._make(
        (
            get("_sk")
            or action_key(
                time_value,
                phase,
                subject_id or str(get("target", "") or ""),
                event,
            ),
            time_value,
            phase,
            kind,
            subject_index,
            index_of.get(str(attacker_id), -1) if attacker_id else -1,
            aidx,
            -1,
            EVENT_SLOTS.slot(str(trigger_id)) if trigger_id else NO_SLOT,
            event,
            EVENT_SLOTS.slot(str(event_id)) if event_id is not None else NO_SLOT,
            str(get("source_key", "")),
            str(get("source", get("source_key", ""))),
            get("sequence"),
            max(0.0, float(get("damage", get("amount", 0.0)) or 0.0)),
            bool(redirected_raw),
            *[read(event, index_of) for read in _EVENT_READERS[family]],
        )
    )


def pair_resistance_baselines(
    result: Mapping[str, Any],
) -> tuple[float | None, float | None]:
    """One pair fight's final effective armour and magic resistance.

    ``None`` for either figure the engine did not publish, or published as a
    non-finite number.  Absent rather than zero: a resistance reduction
    re-prices its packet as the ratio of two mitigation factors, so a missing
    baseline is receipted as ``support_resistance_reduction_unavailable``.
    Read once per fight and stamped onto both the action and the enriched
    event, so the modifier cannot price differently on the two.
    """
    baselines: list[float | None] = []
    for field in ("effective_armor", "effective_mr"):
        try:
            value = float(result[field])
        except (KeyError, TypeError, ValueError):
            baselines.append(None)
            continue
        baselines.append(value if math.isfinite(value) else None)
    return baselines[0], baselines[1]


def modifier_delivery_receipt(
    compilers: Iterable[WalkCompiler],
) -> str | None:
    """Refuse an armed modifier the compiled walk cannot classify against.

    An armed cross-participant modifier declares which attack classes it
    applies to, and the light tuple ledger carries no delivery flags.
    """
    if not any(compiler.staged_modifier for compiler in compilers):
        return None
    if not any(compiler.unclassified_delivery for compiler in compilers):
        return None
    return "modifier_over_light_ledger"


def revive_candidate_actions(
    actions: Iterable[SurvivalAction],
    combatants: Iterable[CombatantFacts],
    next_aidx: int,
) -> tuple[list[SurvivalAction], int]:
    """Author revive candidates beside every incoming damage action.

    Mirrors the receipt walk's pre-walk expansion: a participant whose
    defenses arm a sourced revive (Guardian Angel, or a champion passive —
    Anivia Rebirth, Zac Cell Division, Zilean Chronoshift) gets a candidate
    revive after every damaging incoming packet; the kernel applies the
    earliest one only when the participant is actually dead and ignores the
    rest.  The score ledger stages these exactly like the receipt, so a
    revive never depends on which adapter drives the walk.
    """
    combatant_list = list(combatants)
    candidates: list[SurvivalAction] = []
    aidx = next_aidx
    for actor_index, actor in enumerate(combatant_list):
        revive = armed_revive(actor.defenses)
        if revive is None:
            continue
        revive_amount, revive_delay, revive_source, revive_key = revive
        for action in actions:
            if action.subject != actor_index or action.kind not in DamageAction.kinds:
                continue
            if action.amount <= 0.0:
                continue
            candidate_time = float(action.time) + revive_delay
            candidate = {
                "time": candidate_time,
                "kind": "revive",
                "amount": revive_amount,
                "source": revive_source,
                "source_key": revive_key,
                "sequence": int(action.sequence or 0),
                "_revive_candidate": True,
                "attacker": actor.participant_id,
                "target": actor.participant_id,
            }
            candidates.append(
                WideAction(
                    sort_key=action_key(
                        candidate_time,
                        TransitionRank.DAMAGE,
                        actor.participant_id,
                        candidate,
                    ),
                    time=candidate_time,
                    phase=TransitionRank.DAMAGE,
                    kind=ActionKind.REVIVE,
                    subject=actor_index,
                    attacker=-1,
                    aidx=aidx,
                    amount=revive_amount,
                    # The sourced stasis window itself, carried onto the
                    # candidate: the kernel re-anchors it to the *death*
                    # time, so a candidate authored off a pre-lethal packet
                    # cannot resurrect before death + delay.  Without it the
                    # window is zero and the compiled path revives on the
                    # first candidate at or after death.
                    delay=revive_delay,
                    source=revive_source,
                    source_key=revive_key,
                    sequence=int(action.sequence or 0),
                )
            )
            aidx += 1
    return candidates, aidx


class WalkCompiler:
    """Accumulates flat survival actions with stable per-action ids.

    One compiler builds the invariant panel (roster pairs), another builds
    an evaluation's fresh actions starting after the panel's id range so
    trigger references and the per-eval ``applied`` array stay aligned.
    Every action is a typed :class:`SurvivalAction` whose ``sort_key``
    drives the presorted merge; the walk consumes the same interface the
    receipt adapter builds from event dicts.
    """

    __slots__ = (
        "actions",
        "auto_strikes_into",
        "coverage",
        "damage_order",
        "next_aidx",
        "staged_modifier",
        "support_entries",
        "thorns_order",
        "unclassified_delivery",
    )

    def __init__(self, first_aidx: int = 0) -> None:
        self.actions: list[SurvivalAction] = []
        self.damage_order: dict[int, list[tuple[int, float]]] = defaultdict(list)
        self.thorns_order: dict[int, list[tuple[int, float]]] = defaultdict(list)
        self.support_entries: list[tuple[str, int, int, bool]] = []
        self.auto_strikes_into: dict[int, list[tuple[int, float, int, int]]] = (
            defaultdict(list)
        )
        self.coverage: list[dict[str, Any]] = []
        self.next_aidx = first_aidx
        # Whether this compiler consumed an engine result whose rows cannot
        # say how a packet was delivered — the light tuple ledger, which
        # carries no ``is_ability``/``basic_attack`` at all.  Read by the
        # walk assembly, which refuses to stage an armed damage modifier
        # over rows no attack-class restriction can be evaluated against.
        self.unclassified_delivery = False
        # Whether this compiler staged an armed cross-participant damage
        # modifier.  The other half of the same question, and separate from
        # it because the two can land in different compilers: the roster
        # panel arms an ally's curse and the candidate's own fresh result
        # supplies the packets it applies to.
        self.staged_modifier = False

    def add_engine_result(self, fight: PairFight, slots: WalkSlots) -> None:
        """Stage one pair fight's actions and ledgers for the walk."""
        self._compile_pair(fight, slots, view=None)

    def project_pair_view(self, fight: PairFight, view: PairView) -> None:
        """Enrich *view*'s events from one pair fight, staging nothing."""
        self._compile_pair(fight, projection_only(), view=view)

    def _compile_pair(
        self, fight: PairFight, slots: WalkSlots, *, view: PairView | None
    ) -> None:
        """Compile one pair fight from the engine's own rows.

        The one packet compiler: every roster pair, every signature panel,
        every candidate's fresh fights and the receipt projection reach the
        walk through here, so a fact about a packet is decided once.  The two
        entry points above are the two jobs, and *view* is the one thing that
        differs: the projection enriches it, staging has none.  The sort-key
        layout is ``action_key``'s; both must change together.

        Three things the score walk owes are not the projection's: the
        fail-closed refusal of a transition *the score kernel* cannot stage
        (the receipt walk stages every one of them, which is what the
        fallback is), the cross-fight actor-wide heal dedup (the composition
        owns its own, over the copies published here), and the actions
        themselves — nobody reads them, and building them would make the
        receipt path pay for the score path's representation.

        A pair row the registry declares ``THEORETICAL`` is a *preview* of a
        number the coupled walk owns, so it and its events are dropped
        (:func:`~.capability.pair_preview_sources`) — composing it would put
        the walk's number and a preview of it into one total.  A preview the
        walk *re-prices* keeps its packet: the walk is about to price it from
        its declaration, and dropping it would delete the family's damage.

        Both records are read into locals here rather than through their
        fields, because the loop below builds tens of thousands of actions
        per request.
        """
        result = fight.result
        attacker_id = fight.attacker_id
        defender_id = fight.defender_id
        defender_index = fight.defender_index
        champion_wounds = fight.champion_wounds
        amps = fight.amps
        attacker_i = slots.attacker_i
        defender_i = slots.defender_i
        grievous_by_dtype = slots.grievous_by_dtype
        duration = slots.duration
        heal_dedup = slots.heal_dedup
        id_strings = slots.id_strings
        suppress_actor_wide_heals = slots.suppress_actor_wide_heals
        result_breakdown = _row_breakdown(result)
        previewed = pair_preview_sources(result_breakdown)
        # A preview the walk *re-prices* keeps its packet on both paths: the
        # pair engine's number leaves the total either way, but a re-priced
        # family's packet is the thing the walk is about to price from its
        # declaration, so dropping it would delete the family's damage.
        dropped = dropped_pair_previews(result_breakdown)
        repriced = previewed - dropped
        if repriced and amps.holder is None:
            raise ValueError(
                f"{attacker_id} carries {len(repriced)} re-priced pair "
                "preview(s) and no resolved static holder amps; pricing them "
                "without the holder's own amplifiers would silently drop a "
                "term the pair engine applied"
            )
        staging = view is None
        if not staging:
            view.result = _without_pair_previews(result, result_breakdown, previewed)
            # Display-name rows for the attacker breakdown; never mutated (the
            # post-survival pass rebuilds source rows wholesale), so a cached
            # fight shares them across evaluations as-is.
            view.source_names = {
                source: {
                    "name": entry.get("name", source),
                    "total_damage": 0.0,
                    **(
                        {"targeting": dict(entry["targeting"])}
                        if isinstance(entry.get("targeting"), Mapping)
                        else {}
                    ),
                }
                for source, entry in result_breakdown.items()
                if isinstance(entry, Mapping) and source not in dropped
            }
        order_a, order_b = participant_order(attacker_id)
        # The event-id *string* stays in the sort key (position 6) and the
        # action carries only its slot, so the loop below interns once per
        # row.  Bound to a local because it builds tens of thousands of
        # actions per request.
        slot_of = EVENT_SLOTS.slot
        actions_append = self.actions.append
        order_append = self.damage_order[attacker_i].append
        strikes_append = self.auto_strikes_into[defender_i].append
        # Engine damage arms at the damage rank, on both the tuple ledger and
        # the dict one.  The inline tuple below is ``action_key``'s output
        # written by hand, so element 1 is that function's element 1: the
        # rank's ordering slot, which for ``DAMAGE`` is the rank itself.
        # Named once per call rather than per action: this loop builds tens
        # of thousands of sort keys per request, and the alternative — a bare
        # ordinal in tuple position 1 — is a phase nobody can grep for, which
        # is exactly how both row shapes escaped the first migration pass.
        damage_phase = ordering_slot(TransitionRank.DAMAGE)
        # A control-ONLY event is not damage and does not sort as damage: it
        # takes effect after everything that landed at its own timestamp.  A
        # control that RIDES damage keeps the damage rank, because it
        # resolves with the packet it rode in on.
        control_phase = ordering_slot(TransitionRank.DEBUFF_ARM)
        known_ids = len(id_strings)
        aidx = self.next_aidx
        # Per fight, not per event: the engine publishes one pair of final
        # effective resistances for the whole pair fight, and every packet of
        # it carries them.  Stamped only when the fight published a finite
        # figure, so an absent value stays absent and the walk refuses to
        # invent a mitigation ratio for that packet rather than reading zero.
        baseline_armor, baseline_mr = pair_resistance_baselines(result)
        baseline_fields = {
            key: value
            for key, value in (
                ("_baseline_effective_armor", baseline_armor),
                ("_baseline_effective_mr", baseline_mr),
            )
            if value is not None
        }
        cast_timeline = _row_cast_timeline(result)
        if not isinstance(cast_timeline, list):
            cast_timeline = ()
        # **Two row shapes, one reader.**  The engine publishes its damage
        # ledger either as enriched dicts or — for a score-only request whose
        # adequacy conditions hold — as light positional rows ``(sort_key,
        # damage, damage_type, source_key, raw_formula, raw_damage)``.  Those
        # are two *representations of one ledger*, so what differs between
        # them is how a field is spelled and nothing else: the block below is
        # the whole of the difference, and every line after it is one tail
        # both shapes reach.  One tail, so a fix cannot land on one shape and
        # miss the other.
        light = bool(result.get("damage_events_tuple"))
        # A light ledger declares no self-heals, so the heal loop below is a
        # no-op for it rather than skipped by an early return -- and that is
        # an invariant of a *different* module: ``pipeline.py`` sets
        # ``self_healing_events = []`` on the same three lines that set
        # ``damage_events_tuple``, and the comment there says the empty list
        # is the exact value ``derive_self_healing`` would have returned.
        # Reading it here rather than branching around it is what lets the
        # linkage index, the heals and the coverage append be written once.
        # The refusal below keeps the invariant structural rather than a
        # promise kept in another file's comment: the tuple rows
        # below carry no ``time``/``source_key`` dict keys, so a light result
        # that did declare heals would link every one of them to nothing and
        # compile a fight whose heals silently vanished.
        heals = _row_self_heals(result)
        if light and heals:
            raise ValueError(
                f"{attacker_id} published a tuple damage ledger and "
                f"{len(heals)} self-heal(s); the light row shape carries no "
                "field the heal linkage reads, so those heals would compile "
                "to nothing"
            )
        if light and not staging:
            # The light shape exists because a score-only request proved
            # nothing reads the per-event view.  Enriching one would publish
            # a receipt of fields the rows do not carry.
            raise ValueError(
                f"{attacker_id} published a tuple damage ledger and was asked "
                "for the receipt projection; the light row shape carries none "
                "of the fields an enriched event publishes"
            )
        # The trigger-linkage index costs a key tuple per damage event, so
        # a fight with no self-heals (most candidates, and every light
        # ledger) never builds it.
        aidx_by_key: dict[tuple[str, float, int], int] | None = {} if heals else None
        aidx_by_source_time: dict[tuple[str, float], list[int]] = defaultdict(list)
        for index, row in enumerate(_row_damage_events(result)):
            if light:
                # The positional layout is declared once, in
                # ``ledger_projection.LightRow``; naming it here costs one
                # tuple-subclass construction and buys the loop out of seven
                # magic indices that nothing could grep for.
                light_row = LightRow._make(row)
                key = light_row.sort_key
                time_value = key[0]
                sequence = key[3]
                source_key = light_row.source_key
            else:
                if "sequence" not in row:
                    # See action_key: pair-local event ids stay
                    # order-irrelevant only while every engine event carries
                    # its per-fight sequence.
                    raise ValueError(
                        f"{attacker_id} damage event {row.get('source_key')!r} "
                        "has no sequence; the walk's tie-break order would depend "
                        "on event-id numbering"
                    )
                # The engine ledger writes these three fields unconditionally
                # (damage.add / add_declared_events), so index them directly.
                time_value = row["time"]
                sequence = row["sequence"]
                source_key = row["source_key"]
            if source_key in dropped:
                # ``continue`` rather than a filtered list: ``index`` is
                # the per-pair event id, and re-numbering the survivors
                # would move every public id downstream of the first
                # preview.
                continue
            if light:
                damage_type = light_row.damage_type
                # One number for both readers: a light row's damage is the
                # engine's own, and the clamp below belongs to the dict
                # shape, whose ``damage`` field can carry a negative for a
                # transition the wound tuple still prices at face value.
                wound_damage = damage = light_row.damage
                raw_formula = light_row.raw_formula
                raw_damage = light_row.raw_damage
                declaration = light_row.declared
                source = source_key
                # A light ledger row carries no delivery metadata, so
                # neither flag can be answered from it.  That is recorded
                # once for the whole result below (``unclassified_delivery``)
                # rather than guessed per row: a modifier restricted by
                # attack class must not read ``False`` as "this was neither
                # an attack nor a spell".
                is_ability = basic_attack = False
                # Nor can it answer any delivery fact.  Their neutral values
                # are what the tuple shape *is*, not a guess about the packet.
                immobilized = skillshot = area_damage = damage_over_time = False
                cc_kind = ""
                cc_duration = 0.0
                ability_instance = None
            else:
                damage_type = row["damage_type"]
                wound_damage = row["damage"]
                damage = max(0.0, wound_damage)
                raw_formula = row.get("raw_formula")
                # The published pre-mitigation figure, on some rows and not
                # others (1,365 of the 1,706 the receipt view is handed).
                # Zero prices no raw and no live formula, which is what a
                # row that published none of it says.
                raw_damage = optional_field(row, "raw_damage", float) or 0.0
                declaration = row.get("declared")
                source = str(row.get("source", source_key))
                # The two delivery facts an engine row does not always spell
                # out, derived here rather than by whoever calls this: an
                # authored ability event IS an ability, and the ordinary auto
                # row IS the canonical basic-attack packet.  Reading the raw
                # keys alone left an auto row classified ``unknown_delivery``
                # and an ability row outside every attack-class restriction.
                is_ability = is_authored_ability_event(row)
                basic_attack = (
                    bool(row.get("basic_attack")) or source_key == "auto_attacks"
                )
                # The delivery facts a certified packet carries, read off the
                # same keys ``action_from_event`` reads.  Force of Nature's
                # Steadfast counts an immobilizing hit double and throttles
                # per cast instance, the spell-shield gate groups a
                # multi-part cast by that same instance, and a Knight's Vow
                # redirect child copies the control window off its parent --
                # unstamped, all three price differently on the two paths.
                immobilized = is_immobilizing_event(row) or bool(
                    row.get("crowd_control")
                )
                cc_kind = optional_field(row, "cc_kind", str) or ""
                cc_duration = max(0.0, optional_field(row, "cc_duration", float) or 0.0)
                skillshot = bool(row.get("skillshot"))
                area_damage = bool(row.get("area_damage"))
                damage_over_time = bool(row.get("damage_over_time"))
                # The cast ordinal is what makes a multi-packet ability ONE
                # spell-shield use.  The engine stamps it on the rows it can
                # attribute; the rest are derived from the same cast timeline,
                # in the same spelling.
                ability_instance = row.get("ability_instance")
                if ability_instance is None:
                    ability_instance = ability_instance_for_event(row, cast_timeline)
            if index < known_ids:
                event_id = id_strings[index]
            else:
                event_id = f"{attacker_id}:{defender_id}:{index}"
                id_strings.append(event_id)
                known_ids += 1
            live_formula = (
                raw_formula if callable(raw_formula) and raw_damage > 0 else None
            )
            grievous = grievous_by_dtype.get(damage_type)
            if staging and not light:
                # Fail closed on damage transitions *the score kernel*
                # cannot stage (execute thresholds, redirects, deferred
                # batches, stack self-shields) instead of silently erasing
                # them.  A light row cannot answer the question,
                # the fields the check reads are the enrichment it omits —
                # and it does not have to: ``ledger_projection`` selects the
                # light shape only for a request whose adequacy conditions
                # already exclude every transition this would catch.
                damage_receipt = unrepresentable_damage_receipt(row)
                if damage_receipt is not None:
                    raise UncompilableActionError(
                        receipt=damage_receipt,
                        source=source,
                    )
            wound = (
                champion_wound_tuple(champion_wounds, source_key, wound_damage)
                if champion_wounds
                else None
            )
            live_amp = live_amp_for(amps.live, damage_type)
            declared = (
                declared_packet_of(declaration, damage_type, source_key, amps.holder)
                if source_key in repriced
                else None
            )
            sort_key = (
                time_value,
                damage_phase,
                sequence,
                order_a,
                order_b,
                defender_id,
                event_id,
                source,
            )
            if staging:
                # ``live_amp``, ``declared``, the two delivery flags and the
                # two resistance baselines are stated even at their neutral
                # values: each neutral is also an answer, and a packet built
                # without one would score a term missing.  ``phase`` is the
                # record's damage-rank default.
                actions_append(
                    DamageAction(
                        sort_key=sort_key,
                        time=time_value,
                        kind=(
                            ActionKind.PLAIN_DAMAGE
                            if live_formula is None
                            and grievous is None
                            and wound is None
                            else ActionKind.DAMAGE
                        ),
                        subject=defender_i,
                        attacker=attacker_i,
                        aidx=aidx,
                        amount=damage,
                        damage_type=damage_type,
                        raw_formula=live_formula,
                        raw_damage=raw_damage,
                        grievous=grievous,
                        wound=wound,
                        source_key=source_key,
                        source=source,
                        event_slot=slot_of(event_id),
                        sequence=sequence,
                        live_amp=live_amp,
                        declared=declared,
                        is_ability=is_ability,
                        basic_attack=basic_attack,
                        baseline_effective_armor=baseline_armor,
                        baseline_effective_mr=baseline_mr,
                        immobilized=immobilized,
                        cc_kind=cc_kind,
                        cc_duration=cc_duration,
                        skillshot=skillshot,
                        damage_over_time=damage_over_time,
                        area_damage=area_damage,
                        ability_instance=ability_instance,
                    )
                )
                if time_value <= duration:
                    order_append((aidx, time_value))
                # A light ledger omits per-event metadata, so ``basic_attack``
                # is False for it and only its explicit auto stream triggers
                # Thorns.
                if source_key == "auto_attacks" or basic_attack:
                    strikes_append((aidx, time_value, sequence, attacker_i))
            else:
                view.events.append(
                    _enriched_damage_event(
                        row,
                        attacker_id,
                        defender_id,
                        event_id,
                        is_ability=is_ability,
                        ability_instance=ability_instance,
                        basic_attack=basic_attack,
                        wound=wound,
                        time_value=time_value,
                        source_row=result_breakdown.get(source_key),
                        baseline_fields=baseline_fields,
                        live_amp=live_amp,
                        declared=declared,
                        sort_key=sort_key,
                    )
                )
                view.event_id_by_aidx[aidx] = event_id
            if aidx_by_key is not None:
                time_key = trigger_time_key(time_value)
                aidx_by_key[(source_key, time_key, sequence)] = aidx
                aidx_by_source_time[(source_key, time_key)].append(aidx)
            aidx += 1
        # Standalone crowd-control intervals.  The engine publishes each
        # control application as its own row, and one action is staged per
        # row: compiling the fight without them would give the walk a roster
        # nobody could be immobilized in.
        for control_index, raw_event in enumerate(_row_control_events(result)):
            if "sequence" not in raw_event:
                # Same refusal as the damage loop above: pair-local event ids
                # stay order-irrelevant only while every engine row carries
                # its per-fight sequence, and a missing one would silently
                # tie-break at zero.
                raise ValueError(
                    f"{attacker_id} control event "
                    f"{raw_event.get('source_key')!r} has no sequence; the "
                    "walk's tie-break order would depend on event-id numbering"
                )
            # Cast grouping: the cast id IS ``slot:ordinal``, which is exactly
            # what :func:`ability_instance_for_event` derives from the cast
            # timeline, so one blocked cast costs one spell-shield use however
            # its identity was reached.
            instance = (
                raw_event.get("application_id")
                or raw_event.get("cast_id")
                or ability_instance_for_event(raw_event, cast_timeline)
            )
            event = {
                **raw_event,
                "attacker": attacker_id,
                "target": defender_id,
                "_event_id": f"{attacker_id}:{defender_id}:control:{control_index}",
                # A control packet is a cast landing, whatever the row says.
                "is_ability": True,
                "ability_instance": instance,
                **baseline_fields,
            }
            # The control stream is 18 rows across the whole coupled set,
            # far too thin to license a fail-closed read, so what a row does
            # not spell stays optional here.
            time_value = optional_field(event, "time", float) or 0.0
            event["_sk"] = (
                time_value,
                control_phase,
                event_sequence(event),
                order_a,
                order_b,
                defender_id,
                event["_event_id"],
                str(
                    event.get("source", optional_field(event, "source_key", str) or "")
                ),
            )
            if staging:
                actions_append(
                    action_from_event(
                        event,
                        TransitionRank.DEBUFF_ARM,
                        defender_i,
                        {attacker_id: attacker_i},
                        subject_id=defender_id,
                        aidx=aidx,
                    )
                )
                if time_value <= duration:
                    order_append((aidx, time_value))
            else:
                # The dict the action would have been built from *is* the
                # receipt's enriched control event; there is nothing to
                # project because the two representations start as one.
                view.events.append(event)
            aidx += 1
        self.unclassified_delivery = self.unclassified_delivery or light
        self.next_aidx = aidx
        for heal_index, event in enumerate(heals):
            if staging:
                # Fail closed on any heal transition *the score kernel*
                # cannot stage (Severum overheal-to-shield, vamp source
                # categories, live gates) instead of silently erasing it.
                # The receipt walk stages all three.
                heal_receipt = unrepresentable_heal_receipt(event)
                if heal_receipt is not None:
                    raise UncompilableActionError(
                        receipt=heal_receipt, source=healed_source(event)
                    )
            trigger = aidx_by_key.get(heal_trigger_key(event), -1)
            if trigger < 0:
                # The two stamps the trigger linkage reads are the
                # composition's own, on a heal that rode a packet and on no
                # other, so an unlinked heal answers the empty key here.
                candidates = aidx_by_source_time.get(
                    (
                        optional_field(event, "_trigger_source", str) or "",
                        trigger_time_key(
                            optional_field(event, "_trigger_time", float) or 0.0
                        ),
                    ),
                    [],
                )
                if len(candidates) == 1:
                    trigger = candidates[0]
            if staging and event.get("actor_wide"):
                # The cross-fight dedup is the *score walk's* replay of the
                # composition's keep-first rule.  The receipt projection
                # publishes every copy and the composition dedups its own.
                if "_trigger_source" in event:
                    # The dedup below keeps the copy that compiled first; a
                    # trigger link would make the copies pair-dependent, so
                    # fail closed rather than guess which one to keep.
                    raise UncompilableActionError(
                        receipt="actor_wide_heal_trigger_link",
                        source=healed_source(event),
                    )
                if suppress_actor_wide_heals:
                    continue
                dedup_key = (healed_source(event), healed_time(event))
                amount = max(0.0, healed_amount(event))
                kept = heal_dedup.get(dedup_key)
                if kept is not None:
                    if kept != amount:
                        # One copy per (source, time) is only sound while
                        # every copy is value-identical.  Fail closed onto
                        # the receipt walk, which owns the keep-first rule.
                        raise UncompilableActionError(
                            receipt="actor_wide_heal_copies_disagree",
                            source=healed_source(event),
                        )
                    continue
                heal_dedup[dedup_key] = amount
            aidx = self.next_aidx
            self.next_aidx += 1
            time_value = healed_time(event)
            # The engine authors per-champion flat heals at the full value
            # because a pair fight cannot see the roster; a defender past the
            # first uses the sourced reduced amount (Vladimir's Hemoplague).
            amount = max(0.0, healed_amount(event))
            later_amount = event.get("_later_target_amount")
            if defender_index > 0 and later_amount is not None:
                amount = max(0.0, float(later_amount))
            # ``{raw_id}:{defender_id}`` so fan-out clones can point
            # ``_source_event_id`` at the applied self copy.
            raw_heal_id = event.get("_event_id") or (f"{attacker_id}:heal:{heal_index}")
            heal_event_id = f"{raw_heal_id}:{defender_id}"
            heal_sort_key = (
                time_value,
                ordering_slot(TransitionRank.RECOVERY),
                event_sequence(event),
                order_a,
                order_b,
                attacker_id,
                heal_event_id,
                healed_source(event),
            )
            if not staging:
                enriched_heal = {
                    **event,
                    "attacker": attacker_id,
                    "_event_id": heal_event_id,
                }
                if defender_index > 0 and later_amount is not None:
                    enriched_heal["amount"] = amount
                trigger_id = view.event_id_by_aidx.get(trigger)
                if trigger_id is not None:
                    enriched_heal["_trigger_event_id"] = trigger_id
                # A triggered self-heal is authored by this attacker/defender
                # pair.  The heal's ``attacker`` is its recipient, so name the
                # target that generated the life-steal/on-hit packet
                # explicitly.  Actor-wide regeneration carries no trigger and
                # gets none: its copies are deduplicated across pair fights.
                if "_trigger_source" in event:
                    enriched_heal["trigger_target"] = defender_id
                enriched_heal["_sk"] = heal_sort_key
                view.heals.append(enriched_heal)
                continue
            actions_append(
                HealAction(
                    sort_key=heal_sort_key,
                    time=time_value,
                    phase=TransitionRank.RECOVERY,
                    kind=ActionKind.HEAL,
                    subject=attacker_i,
                    attacker=attacker_i,
                    trigger=trigger,
                    aidx=aidx,
                    amount=amount,
                    amount_formula=event.get("amount_formula"),
                    healing_category=healed_category(event) or "",
                    amplified_recovery=amplifies_recovery(
                        # `kind` is on every fights row and on 909 combat
                        # rows it is not, so the intersection reader has no
                        # accessor for it: tests/test_heal_event_row.py pins
                        # exactly that split.
                        optional_field(event, "kind", str) or "",
                        healed_category(event) or "",
                    ),
                    temporary_health_duration=(
                        max(
                            0.0,
                            optional_field(event, "temporary_health_duration", float)
                            or 0.0,
                        )
                        if event.get("overheal_to_temporary_health")
                        else 0.0
                    ),
                    overheal_to_temporary_health=bool(
                        event.get("overheal_to_temporary_health")
                    ),
                    source_key=optional_field(event, "source_key", str) or "",
                    source=healed_source(event),
                    event_slot=slot_of(heal_event_id),
                    sequence=event.get("sequence"),
                    # The declared exemption from the walk's attacker
                    # crowd-control gate (Gangplank's Remove Scurvy is the
                    # game's canCastWhileDisabled: being held is the reason
                    # to cast it).  ``action_from_event`` stamps it off the
                    # same field, and a heal only one builder exempts is a
                    # heal one walk applies and the other blocks.
                    cast_while_disabled=bool(event.get("cast_while_disabled")),
                    # The same pair for the cleanse a heal can ride
                    # (Mikael's Purify), read where ``add_support_templates``
                    # reads it.
                    cleanse=bool(event.get("cleanse")),
                    cleanse_item=optional_field(event, "cleanse_item", str) or "",
                )
            )
        self.coverage.append(_row_timeline_coverage(result))

    def add_support_templates(
        self,
        templates: Iterable[Mapping[str, Any]],
        attacker_i: int,
        index_of: Mapping[str, int],
    ) -> None:
        """Compile one attacker's resolved support packets.

        Every field below is read as optional and for one reason: a support
        packet is an AUTHORED declaration, from ``ally_packet_shape._packet``,
        a champion module's ally effects or Lulu's own deriver, and an absent
        key is that author saying the packet carries no such facet.  The book
        is 70 rows across the whole coupled set, which is far too thin to
        license a fail-closed read of anything but ``target``.
        """
        for template in templates:
            target_id = str(template["target"])
            subject_i = index_of[target_id]
            kind = optional_field(template, "kind", str) or ""
            source = optional_field(template, "source", str) or ""
            # Fail closed on any resolved support template the score kernel
            # cannot stage: kinds outside the staged set (stat buffs, on-hit
            # magic, temporary health, movement), timed shields (duration >
            # 0), live gates, live amount formulas, and trigger links —
            # instead of mis-compiling it as a flat heal or silently
            # dropping it.
            template_receipt = unrepresentable_template_receipt(template)
            if template_receipt is not None:
                raise UncompilableActionError(receipt=template_receipt, source=source)
            if template.get("_trigger_event_id") is not None:
                # A support author *does* emit a trigger link: the
                # Everlasting branch in ``item_support_effects`` stamps
                # ``_trigger_event_id`` on every Fimbulwinter shield the
                # enriched view produced (``None`` when it did not, which
                # is what ``is not None`` reads).  That packet is refused
                # one branch earlier for its 3 s duration, so this guard is
                # the narrower second net: it catches a linked template
                # ``unrepresentable_template_receipt`` admits — whatever
                # clears every clause it checks.  Resolving the link would
                # need the same cross-pair id map as heals, so fail closed
                # rather than silently drop what the receipt walk would
                # apply.  All three facts are pinned by
                # ``tests/test_trigger_stream.py``'s
                # ``TestTheSupportTriggerLinkRaise`` rather than left here
                # to go stale the way the sentence this replaced did.
                raise UncompilableActionError(
                    receipt="support_trigger_link", source=source
                )
            # When this packet arms and what it becomes are both read from
            # the classifiers the receipt adapter reads, never from a kind
            # literal here: a packet's own ``_rank`` declaration has to win
            # (a shield declaring ``LATE_BARRIER`` arms after the damage it
            # was placed behind, on both paths), and one packet has to become
            # one action kind whichever adapter compiles it.  So widening
            # ``unrepresentable_template_receipt`` admits a kind to its rank
            # and to its action kind at once: read this before widening it.
            # ``ActionKind``'s own spelling, not a literal: the packet kind
            # and the action kind are the same word by construction (the
            # receipt adapter's classifier maps one to the other), and
            # writing it twice is how the two would drift.
            if kind == ActionKind.DAMAGE_MODIFIER.value:
                self._add_damage_modifier(template, attacker_i, subject_i, index_of)
                continue
            priority = support_transition_rank(template)
            aidx = self.next_aidx
            self.next_aidx += 1
            time_value = optional_field(template, "time", float) or 0.0
            category = optional_field(template, "healing_category", str) or ""
            self.actions.append(
                WideAction(
                    sort_key=action_key(time_value, priority, target_id, template),
                    time=time_value,
                    phase=priority,
                    # The same classifier the receipt adapter runs, for the
                    # reason the rank above uses ``support_transition_rank``.
                    # A kind fold spelled here instead is silence: a
                    # ``crowd_control_resist`` arm or a ``stasis`` grant that
                    # compiled as a zero-amount HEAL would leave the holder
                    # unprotected on the score walk and armed on the receipt
                    # walk, with nothing saying so.
                    kind=classify_event_kind(template, priority),
                    subject=subject_i,
                    attacker=attacker_i,
                    aidx=aidx,
                    amount=max(0.0, optional_field(template, "amount", float) or 0.0),
                    healing_category=category,
                    amplified_recovery=amplifies_recovery(kind, category),
                    source_key=optional_field(template, "source_key", str) or "",
                    source=source,
                    event_slot=EVENT_SLOTS.slot(
                        optional_field(template, "_event_id", str) or ""
                    ),
                    sequence=template.get("sequence"),
                    # The typed facts a barrier carries into the shield
                    # ledger.  They read the same template fields
                    # ``action_from_event`` reads off the same packet: the
                    # two builders must produce the same tuple from one
                    # dict, and a field only one of them stamps is a
                    # mechanic one walk applies and the other drops.
                    duration=max(
                        0.0, optional_field(template, "duration", float) or 0.0
                    ),
                    duration_set="duration" in template,
                    shield_pool=optional_field(template, "shield_pool", str) or "",
                    crowd_control_immunity_while_shield=bool(
                        template.get("crowd_control_immunity_while_shield")
                    ),
                    crowd_control_immunity_source=(
                        optional_field(template, "crowd_control_immunity_source", str)
                        or ""
                    ),
                    requires_holder_health_ratio=max(
                        0.0,
                        optional_field(template, "requires_holder_health_ratio", float)
                        or 0.0,
                    ),
                    requires_existing_shield=bool(
                        template.get("requires_existing_shield")
                    ),
                    requires_maw_lifeline_omnivamp=bool(
                        template.get("requires_maw_lifeline_omnivamp")
                    ),
                    overheal_to_temporary_health=bool(
                        template.get("overheal_to_temporary_health")
                    ),
                    temporary_health_duration=max(
                        0.0,
                        optional_field(template, "temporary_health_duration", float)
                        or 0.0,
                    ),
                    # The cleanse dispatch's own inputs, read off the same
                    # template fields ``action_from_event`` reads: the marker
                    # pair the heal branch tests, the per-cast group a
                    # fan-out shares one use across, the typed utility kind a
                    # self-cast activation dispatches on, and the caster gate
                    # a blocked cast is receipted through.
                    cleanse=bool(template.get("cleanse")),
                    cleanse_item=optional_field(template, "cleanse_item", str) or "",
                    cleanse_group=optional_field(template, "cleanse_group", str) or "",
                    utility_kind=kind if kind in UTILITY_KINDS else "",
                    cast_blocked_by_attacker_control=bool(
                        template.get("cast_blocked_by_attacker_control")
                    ),
                )
            )
            self.support_entries.append((target_id, attacker_i, aidx, kind == "heal"))

    def _add_damage_modifier(
        self,
        template: Mapping[str, Any],
        attacker_i: int,
        subject_i: int,
        index_of: Mapping[str, int],
    ) -> None:
        """Compile one armed cross-participant damage modifier (H5).

        The kernel has always applied these; until the H5 stage the compiler
        refused to build one, so every amp holder was priced by the receipt
        walk with ``support_kind=damage_modifier`` as its named cause.  This
        is that branch, and it reads the same template fields
        :func:`action_from_event` reads off the same packet, because the two
        builders must produce the same tuple from the same dict or the two
        walks disagree about a mechanic — failure mode C of the incident.

        **The one thing it refuses is the aura.**  Whether a second holder
        of one mechanic arms a second modifier on one subject is a declared
        per-mechanic fact and the receipt composition answers it with
        an :class:`~.amp.ArmingLedger` built once per composed fight.  The
        compiled path has no such moment: the roster panel is compiled once
        per search and the candidate's own actions once per evaluation, so
        an ``IDEMPOTENT_AURA`` whose two holders sit on opposite sides of
        that split has no single ledger to collide in.  Rather than compile
        a second curse the walk would have dropped, the aura keeps a named
        refusal of its own.  ``PER_HOLDER`` needs none: its key carries the
        holder, so its armings can never collide across holders, and a
        second arming by *one* holder is a re-arm the kernel's own window
        refresh already owns.
        """
        source = optional_field(template, "source", str) or ""
        declared = arming_stacking().get(source)
        if declared is not None and declared[1] is HolderStacking.IDEMPOTENT_AURA:
            raise UncompilableActionError(
                receipt=f"modifier_aura_arming={source}",
                source=source,
            )
        priority = support_transition_rank(template)
        aidx = self.next_aidx
        self.next_aidx += 1
        target_id = str(template["target"])
        time_value = optional_field(template, "time", float) or 0.0
        self.actions.append(
            WideAction(
                sort_key=action_key(time_value, priority, target_id, template),
                time=time_value,
                phase=priority,
                kind=ActionKind.DAMAGE_MODIFIER,
                subject=subject_i,
                attacker=attacker_i,
                aidx=aidx,
                amount=max(0.0, optional_field(template, "amount", float) or 0.0),
                duration=max(0.0, optional_field(template, "duration", float) or 0.0),
                persistent=bool(template.get("persistent")),
                multiplier=optional_field(template, "multiplier", float) or 1.0,
                damage_reduction=bool(template.get("damage_reduction")),
                next_event_only=bool(template.get("next_event_only")),
                # The declared escape from the delivery gate: a modifier
                # that reads "from all sources" prices packets no attack
                # class covers (an auto-attack's true-damage rider).  The
                # receipt path stamps it in ``action_from_event``; omitting
                # it here made the two walks disagree by exactly the
                # unpriced packets, which no equality gate could attribute.
                all_sources=bool(template.get("all_sources")),
                source_participant=(
                    optional_field(template, "source_participant", str) or ""
                ),
                armor_reduction_percent=(
                    optional_field(template, "armor_reduction_percent", float) or 0.0
                ),
                mr_reduction_percent=(
                    optional_field(template, "mr_reduction_percent", float) or 0.0
                ),
                resistance_type=optional_field(template, "resistance_type", str) or "",
                # The packet names its holder as a participant id because
                # that is what a support author knows; the kernel's owner
                # skip wants the roster slot, and an owner outside this
                # roster resolves to ``-1`` — "this packet declares no
                # holder" — exactly as ``action_from_event`` resolves it.
                holder=index_of.get(optional_field(template, "owner", str) or "", -1),
                damage_classes=declared_class_set(
                    template.get("damage_classes"), DamageClass
                ),
                attack_classes=declared_class_set(
                    template.get("attack_classes"), AttackClass
                ),
                source_key=optional_field(template, "source_key", str) or "",
                source=source,
                event_slot=EVENT_SLOTS.slot(
                    optional_field(template, "_event_id", str) or ""
                ),
                sequence=template.get("sequence"),
                duration_set="duration" in template,
            )
        )
        # An armed modifier heals and shields nobody, and it is still support
        # the holder provided: the receipt path sums ``applied_amount`` into
        # ``support_value`` for every non-damage support packet, amps
        # included (H3 is the open question about whether it *should*, not
        # about whether it does).  So the entry is recorded with
        # ``is_heal=False``, which is what keeps the compiled per-attacker
        # support value equal to the walk's and the healing output untouched.
        self.support_entries.append((target_id, attacker_i, aidx, False))
        self.staged_modifier = True

    def add_thorns(
        self,
        holder: CombatantFacts,
        holder_i: int,
        strikes: Iterable[tuple[int, float, int, CombatantFacts, int]],
        profiles: tuple[ThornsEffect, ...],
        *,
        grievous_by_dtype: Mapping[str, Any],
        duration: float,
        id_namespace: str,
    ) -> None:
        """Compile the holder's strike-back events for a run of strikes.

        ``strikes`` carries ``(strike_aidx, time, sequence, striker,
        striker_i)`` in the receipt composition's incoming order.  The synthetic
        event-id string participates only in the sort key, where every pair
        of distinct thorns events already differs at the sequence or
        participant component, so panel and fresh namespaces may number
        independently without affecting order.
        """
        actions = self.actions
        order = self.thorns_order[holder_i]
        holder_order = participant_order(holder.participant_id)
        return_damage: dict[tuple[str, int], float] = {}
        for index, (
            strike_aidx,
            strike_time,
            strike_sequence,
            striker,
            striker_i,
        ) in enumerate(strikes):
            for profile in profiles:
                damage_key = (profile.item_name, striker_i)
                damage = return_damage.get(damage_key)
                if damage is None:
                    damage = thorns_return_damage(profile, holder, striker)
                    return_damage[damage_key] = damage
                aidx = self.next_aidx
                self.next_aidx += 1
                sort_key = (
                    strike_time,
                    ordering_slot(TransitionRank.REACTIVE),
                    strike_sequence,
                    *holder_order,
                    striker.participant_id,
                    (
                        f"{holder.participant_id}:{striker.participant_id}"
                        f":thorns:{profile.item_name}:{id_namespace}{index}"
                    ),
                    f"{profile.item_name} (Thorns)",
                )
                actions.append(
                    DamageAction(
                        sort_key=sort_key,
                        time=strike_time,
                        phase=TransitionRank.REACTIVE,
                        kind=ActionKind.DAMAGE,
                        subject=striker_i,
                        attacker=holder_i,
                        trigger=strike_aidx,
                        aidx=aidx,
                        amount=max(0.0, damage),
                        damage_type=profile.damage_type,
                        grievous=grievous_by_dtype.get(profile.damage_type),
                        wound=(
                            (
                                profile.grievous_duration,
                                f"{profile.item_name} · Thorns",
                            )
                            if profile.grievous_duration > 0
                            else None
                        ),
                        reactive=True,
                        source_key=f"thorns_{profile.item_name}",
                        source=f"{profile.item_name} (Thorns)",
                        event_slot=EVENT_SLOTS.slot(sort_key[6]),
                        sequence=strike_sequence,
                    )
                )
                if strike_time <= duration:
                    order.append((aidx, strike_time))


class TargetMitigation(NamedTuple):
    """One recipient's share of a redirected packet, and at what resistance.

    ``effective_resistance`` is ``None`` for true damage, which met none.  It
    is the recipient's own baseline: the split hands it to the redirected
    child so the walk prices that child against the resistance it actually
    met rather than the Worthy's, which is what the child inherited while the
    two lanes each computed the factor for themselves.
    """

    factor: float
    effective_resistance: float | None


# The routing family a Knight's Vow split records on the declarations it
# re-delivers.  Sacrifice declares a share and a second subject and no
# magnitude of its own, so the routed packet keeps the source mechanic's
# ``rule_id`` and names this as its router.
KNIGHTS_VOW_ROUTER = "knights_vow.sacrifice"


def knights_vow_target_factor(
    *,
    damage_type: str,
    basic_attack: bool,
    damage_over_time: bool,
    source: Any,
    target: Any,
    raw_amount: float,
) -> TargetMitigation | None:
    """One recipient's mitigation of a Knight's Vow split, at its own
    resistance.

    Computed from the recipient's combatant stats, the attacker's
    penetration, and the recipient's basic-damage / flat-reduction defenses.
    Dynamic combat-state bonuses are deliberately absent: they are armed by
    the walk, which runs after the split, and the walk prices them onto the
    child itself from the baseline this returns.

    ``None`` is "this packet's mitigation cannot be reconstructed", which
    leaves the packet unsplit rather than splitting it at a guessed factor.
    Both lanes call this one function, so a split cannot be priced two ways.
    """
    damage_class = DamageClass.named(damage_type)
    if damage_class is None:
        return None
    if not damage_class.is_mitigable:
        return TargetMitigation(1.0, None)
    if damage_class is DamageClass.PHYSICAL:
        effective = apply_armor_penetration(
            _stat(target.stats, "armor"),
            _stat(source.stats, "flat_armor_penetration"),
            _stat(source.stats, "armor_penetration_percent") / 100.0,
            _stat(source.stats, "armor_penetration_bonus_percent") / 100.0,
            bonus_armor=_stat(target.stats, "bonus_armor"),
        )
    else:
        effective = apply_magic_penetration(
            _stat(target.stats, "magic_resistance"),
            _stat(source.stats, "magic_penetration_flat"),
            _stat(source.stats, "magic_penetration_percent") / 100.0,
        )
    factor = apply_resistance(1.0, effective)
    if not math.isfinite(factor) or factor < 0.0:
        return None
    defenses = target.defenses
    if basic_attack:
        # Basic-damage defenses are post-mitigation and belong to the
        # recipient of each split, not the Worthy.
        factor *= max(0.0, float(defenses.basic_damage_multiplier))
        flat = max(0.0, float(defenses.basic_damage_flat_reduction))
        cap = max(0.0, float(defenses.basic_damage_flat_reduction_cap))
        if flat > 0.0 and cap > 0.0:
            mitigated = raw_amount * factor
            factor = max(0.0, (mitigated - min(flat, mitigated * cap)) / raw_amount)
    flat = max(
        0.0,
        float(
            (
                defenses.champion_dot_damage_flat_reduction
                if damage_over_time
                else defenses.champion_damage_flat_reduction
            )
            or 0.0
        ),
    )
    if flat > 0.0:
        mitigated = raw_amount * factor
        factor = max(0.0, (mitigated - min(flat, mitigated)) / raw_amount)
    return TargetMitigation(factor, effective)


def routed_declaration(declared: Any, share: float) -> Any:
    """One packet's declaration re-delivered at ``share`` of its magnitude;
    ``None`` when its family declared none and the pair engine priced it."""
    if declared is None:
        return None
    return route_declared_packet(declared, RoutingProvenance(KNIGHTS_VOW_ROUTER, share))


def _tether_indexes(
    tether: Mapping[str, Any], combatants: Sequence[Any]
) -> tuple[str, int, str, int] | None:
    """The holder and target ids and combatant indexes of an armed Knight's Vow tether,
    or ``None`` when it is out of range, unready, or names nobody present."""
    if tether["within_range"] <= 0.0 or tether["holder_health_ready"] <= 0.0:
        return None
    holder_id = str(tether["holder"].participant_id)
    target_id = str(tether["target"].participant_id)
    holder_i = next(
        (i for i, c in enumerate(combatants) if c.participant_id == holder_id), -1
    )
    target_i = next(
        (i for i, c in enumerate(combatants) if c.participant_id == target_id), -1
    )
    if holder_i < 0 or target_i < 0:
        return None
    return holder_id, holder_i, target_id, target_i


def stage_knights_vow_redirect_actions(
    compiler: WalkCompiler,
    combatants: Sequence[Any],
    tether: Mapping[str, Any],
    redirect_children: MutableMapping[int, SurvivalAction],
    *,
    next_aidx: int,
) -> int:
    """Stage the receipt walk's Knight's Vow pre-mitigation split onto one
    compiled panel's typed damage actions.

    For every incoming physical/magic damage action whose subject is the
    Worthy ally and whose attacker is an enemy combatant, recover the raw
    pre-mitigation amount (from ``raw_damage`` or the stamped baseline
    resistance), compute each recipient's mitigation factor, replace the
    parent action with the direct share, append the redirected child
    (:attr:`ActionKind.REDIRECT`, trigger-linked to the parent, at the
    reactive rank the receipt clone sorts at, CC fields copied so immobilize
    windows stay byte-identical), and register the child under the parent's
    event slot so the kernel's holder-health gate can cancel it.
    Unrecoverable packets stay untouched: the receipt walk zeroes their
    fraction with a named reason, and the compiled path simply never stages
    them.
    """
    indexes = _tether_indexes(tether, combatants)
    if indexes is None:
        return next_aidx
    holder_id, holder_i, target_id, target_i = indexes
    target = tether["target"]
    holder = tether["holder"]
    fraction = max(0.0, min(1.0, float(tether["redirect_fraction"])))
    threshold = float(tether["threshold"])
    aidx = next_aidx
    rebuilt: list[SurvivalAction] = []
    for action in compiler.actions:
        if (
            action.subject != target_i
            or action.kind not in DamageAction.kinds
            or action.amount <= 0.0
            or action.deferred
            or action.redirected
        ):
            rebuilt.append(action)
            continue
        damage_class = DamageClass.named(str(action.damage_type))
        if damage_class is None or not damage_class.is_mitigable:
            rebuilt.append(action)
            continue
        source = (
            combatants[action.attacker]
            if 0 <= action.attacker < len(combatants)
            else None
        )
        if source is None or str(source.participant_id) == target_id:
            rebuilt.append(action)
            continue
        if action.declared is not None and action.declared.routing is not None:
            # A packet another family already re-delivered carries one route
            # and one share; splitting it again would either lose that
            # provenance or pay a share of a share nobody declared.
            rebuilt.append(action)
            continue
        original_amount = max(0.0, float(action.amount))
        raw_amount: float | None = None
        try:
            candidate = float(action.raw_damage or 0.0)
        except (TypeError, ValueError):
            candidate = 0.0
        if candidate > 0.0 and math.isfinite(candidate):
            raw_amount = candidate
        else:
            baseline = damage_class.resistance_term(
                armor=action.baseline_effective_armor,
                magic_resistance=action.baseline_effective_mr,
            )
            if baseline is not None:
                try:
                    baseline_factor = apply_resistance(1.0, float(baseline))
                    if baseline_factor > 0.0 and math.isfinite(baseline_factor):
                        raw_amount = original_amount / baseline_factor
                except (TypeError, ValueError, ZeroDivisionError):
                    raw_amount = None
        if raw_amount is None or not math.isfinite(raw_amount):
            rebuilt.append(action)
            continue
        split = {
            "damage_type": str(action.damage_type),
            "basic_attack": bool(action.basic_attack),
            "damage_over_time": bool(action.damage_over_time),
            "source": source,
            "raw_amount": raw_amount,
        }
        protected_share = knights_vow_target_factor(target=target, **split)
        holder_share = knights_vow_target_factor(target=holder, **split)
        if protected_share is None or holder_share is None:
            rebuilt.append(action)
            continue
        direct_amount = max(0.0, raw_amount * (1.0 - fraction) * protected_share.factor)
        redirected_amount = max(0.0, raw_amount * fraction * holder_share.factor)
        # A declaration reaches the walk as the WHOLE mechanic's magnitude, so
        # each side of the split carries its own share of it.  Left untouched
        # it would be re-priced in full at both recipients, which is what made
        # one immolate tick cost the roster nearly two.
        parent = action._replace(
            amount=direct_amount,
            declared=routed_declaration(action.declared, 1.0 - fraction),
            redirect_original_damage=original_amount,
            redirect_holder_health_ratio=threshold,
        )
        holder_resistance = holder_share.effective_resistance
        child_text = f"{EVENT_SLOTS.text(action.event_slot)}:redirect"
        child = DamageAction(
            sort_key=action_key(
                float(action.time),
                TransitionRank.REACTIVE,
                holder_id,
                {"attacker": str(source.participant_id), "_event_id": child_text},
            ),
            time=float(action.time),
            phase=TransitionRank.REACTIVE,
            kind=ActionKind.REDIRECT,
            subject=holder_i,
            attacker=action.attacker,
            aidx=aidx,
            amount=redirected_amount,
            damage_type=action.damage_type,
            raw_damage=raw_amount * fraction,
            source_key=action.source_key,
            source=action.source,
            event_slot=EVENT_SLOTS.slot(child_text),
            sequence=action.sequence,
            trigger=action.aidx,
            trigger_slot=action.event_slot,
            redirected=True,
            redirect_holder_health_ratio=threshold,
            redirect_original_damage=original_amount,
            cc_kind=action.cc_kind,
            cc_duration=action.cc_duration,
            immobilized=action.immobilized,
            skillshot=action.skillshot,
            damage_over_time=action.damage_over_time,
            basic_attack=action.basic_attack,
            # The redirected share met the HOLDER's resistance, so the walk's
            # dynamic reprice and declared pricing read the holder's baseline
            # here.  The parent's baseline is the Worthy's and belongs to the
            # direct share alone.
            baseline_effective_armor=(
                holder_resistance
                if damage_class is DamageClass.PHYSICAL
                else action.baseline_effective_armor
            ),
            baseline_effective_mr=(
                holder_resistance
                if damage_class is DamageClass.MAGIC
                else action.baseline_effective_mr
            ),
            declared=routed_declaration(action.declared, fraction),
            is_ability=action.is_ability,
            ability_instance=action.ability_instance,
            area_damage=action.area_damage,
        )
        aidx += 1
        if action.event_slot != NO_SLOT:
            redirect_children[action.event_slot] = child
        rebuilt.append(parent)
        rebuilt.append(child)
        # The child's applied amount belongs to the same attacker's outgoing
        # total (the receipt mirrors it into the attacker's ledger); register
        # it in the panel's damage order so the score breakdown attributes it
        # identically.  The child shares the parent's timestamp: a child the
        # walk never reaches (past the fight window) contributes a zero
        # applied amount, so the unconditional entry is harmless.
        compiler.damage_order[action.attacker].append((child.aidx, float(action.time)))
    compiler.actions = rebuilt
    return aidx


def stage_knights_vow_heals(
    compiler: WalkCompiler,
    combatants: Sequence[Any],
    tether: Mapping[str, Any],
    next_aidx: int,
) -> int:
    """Stage the receipt scheduler's Sacrifice holder-heal onto one compiled
    panel: the Worthy ally's outgoing physical/magic/true damage packets
    author a holder heal (kind ``HEAL``, subject = the Knight's Vow holder,
    gated by the typed holder-health ratio the kernel enforces)."""
    indexes = _tether_indexes(tether, combatants)
    if indexes is None:
        return next_aidx
    holder_id, holder_i, _, target_i = indexes
    heal_fraction = max(0.0, float(tether["heal_fraction"]))
    threshold = float(tether["threshold"])
    aidx = next_aidx
    appended: list[SurvivalAction] = []
    for action in compiler.actions:
        if (
            action.attacker != target_i
            or action.kind not in DamageAction.kinds
            or action.amount <= 0.0
            or str(action.damage_type) not in {"physical", "magic", "true"}
        ):
            continue
        heal_amount = max(0.0, float(action.amount)) * heal_fraction
        if heal_amount <= 0.0:
            continue
        heal_text = f"{EVENT_SLOTS.text(action.event_slot)}:kv_heal"
        appended.append(
            HealAction(
                sort_key=action_key(
                    float(action.time),
                    TransitionRank.RECOVERY,
                    holder_id,
                    {"attacker": holder_id, "_event_id": heal_text},
                ),
                time=float(action.time),
                phase=TransitionRank.RECOVERY,
                kind=ActionKind.HEAL,
                subject=holder_i,
                attacker=holder_i,
                aidx=aidx,
                amount=heal_amount,
                healing_category="knights_vow",
                source_key="Knight's Vow — Sacrifice",
                source="Knight's Vow — Sacrifice",
                event_slot=EVENT_SLOTS.slot(heal_text),
                sequence=action.sequence,
                requires_holder_health_ratio=threshold,
            )
        )
        aidx += 1
    if appended:
        compiler.actions.extend(appended)
        compiler.actions.sort(key=itemgetter(0))
        for heal in appended:
            compiler.support_entries.append((holder_id, holder_i, heal.aidx, True))
    return aidx


def grey_health_heal_action(
    heal_time: float, source: str, amount: float, index: int, *, aidx: int
) -> SurvivalAction:
    """One main-participant grey-health regeneration tick, as an action.

    Authored by the compiled panel path, which knows the ticks only as
    ``(time, source, amount)`` triples and has no packet dict to convert.
    The subject and attacker are roster slot ``0`` because grey health is the
    main participant's own regeneration and the panel builds it for nobody
    else.
    """
    event_id = f"main:grey:{source}:{index}"
    return HealAction(
        sort_key=action_key(
            float(heal_time),
            TransitionRank.RECOVERY,
            "main",
            {"attacker": "main", "_event_id": event_id, "source": source},
        ),
        time=float(heal_time),
        phase=TransitionRank.RECOVERY,
        kind=ActionKind.HEAL,
        subject=0,
        attacker=0,
        aidx=aidx,
        amount=float(amount),
        source_key=str(source),
        source=str(source),
        event_slot=EVENT_SLOTS.slot(event_id),
    )


def grey_health_shield_action(
    grant_time: float,
    source: str,
    amount: float,
    duration: float,
    *,
    index: int,
    aidx: int,
) -> SurvivalAction:
    """One main-participant grey-health-to-shield press, as an action.

    The barrier sibling of :func:`grey_health_heal_action`, in the shape
    the receipt composition's own support template compiles to, so the two
    walks stage one press identically (Tahm Kench's Thick Skin active).
    """
    event_id = f"main:grey:{source}:shield:{index}"
    return WideAction(
        sort_key=action_key(
            float(grant_time),
            TransitionRank.LATE_BARRIER,
            "main",
            {"attacker": "main", "_event_id": event_id, "source": source},
        ),
        time=float(grant_time),
        phase=TransitionRank.LATE_BARRIER,
        kind=ActionKind.SHIELD,
        subject=0,
        attacker=0,
        aidx=aidx,
        amount=float(amount),
        source_key=str(source),
        source=str(source),
        event_slot=EVENT_SLOTS.slot(event_id),
        duration=float(duration),
        duration_set=True,
    )


__all__ = [
    "PairView",
    "WalkCompiler",
    "ability_instance_for_event",
    "action_from_event",
    "grey_health_heal_action",
    "grey_health_shield_action",
    "is_authored_ability_event",
    "modifier_delivery_receipt",
    "pair_resistance_baselines",
    "pair_view",
    "revive_candidate_actions",
]
