"""The one ``SurvivalAction`` constructor in ``src/``.

Nine construction expressions built the kernel's action tuple before this
stage: two in ``survival/actions``, six in ``survival/compile`` and one in
``participant_timeline``.  Nine constructors are nine chances for two of them
to disagree about a field, and they did -- the receipt adapter and the score
compiler each rebuilt the same sort key by hand, in two spellings, and a
phase written as a float at one of them was invisible at the other.  A
mechanic priced by one engine and not the other is failure mode C of the
incident this campaign exists to close.

So construction lives here, once.  Counter 5 of the migration frontier is the
count of ``SurvivalAction(...)`` expressions **outside this file**, and its
target is one: ``survival/actions``'s ``_ACTION_DEFAULT_ROW``, the issue-#171
fast constructor's default row, which is the declared performance fallback
the phase's criterion 17 keeps.

Outside, and only outside — so the arithmetic is worth stating plainly, since
"nine become one" reads as a subtraction and is not one.  The tree held nine
expressions before the move and holds **ten** after it: nine here and the one
declared survivor.  Eight relocated, ``compile_program`` added a tenth, and
the counter went 9 -> 1 because every one of the nine is now in the file the
counter does not scan.  What the migration bought is a single place to change
a field, not fewer places that build the tuple.

Four builders and one entry point:

* :func:`action_from_event` converts one authored packet dict -- the receipt
  path's unit of work.  It was the kernel's own from-event builder and its
  body is unchanged; what moved is which layer owns it, and the old name is
  pinned at zero occurrences so a reader greps it and finds nothing.
* :class:`WalkCompiler` accumulates the score path's flat actions with stable
  per-action ids.  It was ``survival.compile.WalkCompiler``.
* :func:`revive_candidate_actions` and :func:`grey_health_heal_action` author
  the two action shapes neither of the first two produces.
* :func:`compile_program` is the phase's declared entry: a
  :class:`~.build.Program` in, a tuple of actions out, with the
  :class:`~.build.Projection` selecting which fields are read and never which
  events exist.

**Why the kernel does not import this module.**  ``program -> survival`` runs
one way, so ``survival/receipt_state`` cannot call the builder it needs when
the walk authors a recovery packet mid-flight.  It takes the builder as a
constructor parameter instead -- the same device ``build_state``'s
``below_half_healing_bonus`` and ``TransitionContext``'s
``regeneration_windows`` already use, and for the same reason: the boundary
that builds the walk compiles what the walk may not reach and hands it over.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from operator import itemgetter
from typing import Any, NamedTuple

from ..ability_spec import AttackClass, DamageClass
from ..resistance import (
    apply_armor_penetration,
    apply_magic_penetration,
    apply_resistance,
)
from ..survival.actions import (
    EVENT_SLOTS,
    NO_SLOT,
    UTILITY_KINDS,
    ActionKind,
    SurvivalAction,
    TransitionRank,
    action_key,
    classify_event_kind,
    classify_prefetched,
    compiled_damage_action,
    declared_class_set,
    event_sequence,
    ordering_slot,
    participant_order,
    support_transition_rank,
)
from ..survival.compile import (
    UncompilableActionError,
    champion_wound_tuple,
    heal_trigger_key,
    thorns_return_damage,
    unrepresentable_damage_receipt,
    unrepresentable_heal_receipt,
    unrepresentable_template_receipt,
    trigger_time_key,
)
from ..survival.pricing import (
    AuthoredDeclaration,
    DeclaredPacket,
    route_declared_packet,
)
from ..ledger_projection import LightRow
from ..trigger_stream import HolderStacking, is_immobilizing_event
from . import events as ev
from .amp import LiveAmpRider, live_amp_for
from .build import (
    Program,
    Projection,
    arming_stacking,
    dropped_pair_previews,
    pair_preview_sources,
)
from .caches import program_fingerprint, roster_fingerprint
from .identity import event_id_text

# Kinds a compiled damage action may carry; a revive candidate is authored
# beside each of them.  Moved here with ``revive_candidate_actions``, which is
# its only reader.
_DAMAGE_ACTION_KINDS = frozenset(
    {
        ActionKind.PLAIN_DAMAGE,
        ActionKind.DAMAGE,
        ActionKind.EXECUTE,
        ActionKind.DEFER,
        ActionKind.REDIRECT,
    }
)


class PairView:
    """One pair fight as the roster composition reads it.

    The receipt projection of the same compile the score panels take: every
    field on an enriched event is a value :meth:`WalkCompiler.add_engine_result`
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

    ``live_amps`` and ``holder_amps`` travel with the fight because they are
    facts about this pair, and resolving them is not free: a search that
    re-compiles one cached fight into a panel per defensive signature would
    otherwise pay for them once per signature instead of once per pair.
    """

    __slots__ = (
        # The engine's own result, unmodified: what the per-pair ``fights``
        # receipt publishes and what the score panels compile.
        "engine",
        "result",
        "live_amps",
        "holder_amps",
        "events",
        "heals",
        "source_names",
        "support",
        "support_denials",
        # The event-id string of each compiled damage action, so a self-heal
        # can publish the id of the hit that caused it.  The compiler already
        # resolved that link by action index; this is the same link one
        # representation over.
        "event_id_by_aidx",
    )

    def __init__(
        self,
        result: Mapping[str, Any],
        live_amps: Sequence[LiveAmpRider] = (),
        holder_amps: Any = None,
    ) -> None:
        self.engine: Mapping[str, Any] = result
        self.result: Mapping[str, Any] = result
        self.live_amps = live_amps
        self.holder_amps = holder_amps
        self.events: list[dict[str, Any]] = []
        self.heals: list[dict[str, Any]] = []
        self.source_names: dict[str, dict[str, Any]] = {}
        self.support: Any = None
        self.support_denials: Any = None
        self.event_id_by_aidx: dict[int, str] = {}


def _enriched_damage_event(  # pylint: disable=too-many-arguments
    row: Mapping[str, Any],
    attacker_id: str,
    defender_id: str,
    event_id: str,
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
        float(result_breakdown[source].get("total_damage", 0.0) or 0.0)
        for source in previewed
    )
    return {
        **result,
        "total_damage": float(result.get("total_damage", 0.0)) - removed,
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
    live_amps: Sequence[LiveAmpRider] = (),
    holder_amps: Any = None,
) -> PairView:
    """One pair fight's receipt view, through the one packet compiler.

    The walk's own bookkeeping arguments are neutral here and named in one
    place for that reason: the receipt projection stages no actions, so it
    has no roster slots to file them under, no fight window to bound them by
    and no cross-fight heal dedup to replay.  The composition owns that
    dedup itself, over the copies this view publishes.
    """
    view = PairView(result, live_amps, holder_amps)
    WalkCompiler(0).add_engine_result(
        result,
        attacker_id,
        -1,
        defender_id,
        -1,
        {},
        0.0,
        {},
        [],
        defender_index,
        champion_wounds=champion_wounds,
        live_amps=live_amps,
        holder_amps=holder_amps,
        view=view,
    )
    return view


_CAST_SLOTS = frozenset({"Q", "W", "E", "R"})


def is_authored_ability_event(event: Mapping[str, Any]) -> bool:
    """Identify a champion cast without treating passive/proc rows as casts.

    Champion modules use the canonical Q/W/E/R source keys for cast packets.
    A packet may override this marker when a source-backed mechanic supplies
    a more precise cast classification; absent that receipt, item procs and
    passive rows remain eligible to land normally.
    """
    if "is_ability" in event:
        return bool(event["is_ability"])
    return str(event.get("source_key", "")) in _CAST_SLOTS


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
    slot = str(event.get("source_key", ""))
    try:
        event_time = float(event.get("time", 0.0))
    except (TypeError, ValueError):
        return None
    candidates = [
        cast
        for cast in cast_timeline
        if str(cast.get("slot", "")) == slot
        and float(cast.get("time", 0.0)) <= event_time
    ]
    if not candidates:
        return f"{slot}:{trigger_time_key(event_time)}"
    cast = max(candidates, key=lambda row: float(row.get("time", 0.0)))
    ordinal = cast.get("ordinal")
    return (
        f"{slot}:{ordinal}"
        if ordinal is not None
        else f"{slot}:{trigger_time_key(float(cast.get('time', 0.0)))}"
    )


def declared_packet_of(
    declaration: Any, damage_type: str, source_key: str, holder_amps: Any
) -> DeclaredPacket:
    """One re-priced packet's declaration, composed for the walk to price.

    The engine ledger carries a retired family's packet as the five facts of
    an :class:`~..survival.pricing.AuthoredDeclaration` and no price: which
    rule authored it, the pre-mitigation magnitude that rule's own
    interpreter compiled, the attack class the rule declares — which is what
    decides *which* of the holder's amplifiers this packet earns — the
    effective resistance the packet itself met, which the pair engine's own
    re-pricing windows keep in step (umbrella Amendment N, Ruling 1), and the
    basic-attack swing composition it was delivered through, if it was
    (umbrella Amendment R, Ruling 1).  The remaining term, the amplifier
    itself, is resolved on this side from the declarations that produce it
    (umbrella Amendment M, Ruling 1): a walk that took a pre-multiplied
    number would be reading the pair engine's price again under another name.

    One home for both compositions, because a roster composes a pair fight in
    two places and the score path is the one that picks the optimizer's
    winner.

    A packet stamped as re-priced with no declaration on it is a stop, not a
    fallback: the pair engine's number has already left the roster total by
    the time this runs, so returning nothing would delete the family's
    damage — the half-performed retirement umbrella Amendment L, Ruling 1
    calls worse than neither half.
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
        swing=authored.swing_composition(),
    )
    routing = authored.routing_provenance()
    if routing is None:
        return packet
    # A routing family re-delivered this packet at a second subject, and what
    # a route does to a packet has exactly one home (umbrella Amendment R,
    # Ruling 3): the share is applied there and the provenance recorded
    # there, so a site that scaled the magnitude itself would be a second
    # reader of one rule.
    return route_declared_packet(packet, routing)


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
    target field).  Missing optional metadata fails closed to the field's
    neutral value, never to a guessed number.
    """
    get = event.get
    kind_str = str(get("kind", ""))
    execute_ratio_raw = get("execute_threshold_ratio")
    deferred_raw = get("_deferred")
    redirected_raw = get("_redirected")
    raw_formula = get("raw_formula")
    raw_damage = float(get("raw_damage", 0.0) or 0.0)
    grievous_duration = float(get("grievous_duration", 0.0) or 0.0)
    kind = classify_prefetched(
        event,
        phase,
        kind_str,
        execute_ratio_raw,
        deferred_raw,
        redirected_raw,
        raw_formula,
        raw_damage,
        grievous_duration,
    )
    attacker_id = get("attacker")
    attacker_index = index_of.get(str(attacker_id), -1) if attacker_id else -1
    event_id = get("_event_id")
    time_value = float(get("time", 0.0))
    if not math.isfinite(time_value):
        raise ValueError(
            f"action_from_event: event time must be finite, got "
            f"{time_value!r} (event_id={event_id!r}); a non-finite "
            f"timestamp cannot establish a stable total order"
        )
    trigger_id = get("_trigger_event_id")
    batch_id = get("_deferred_batch_id")
    # A shield gate names its subject as a participant id, or as the literal
    # ``"attacker"`` meaning "whoever dealt this packet"; the kernel wants a
    # roster slot either way.
    shield_gate_target = get("shield_gate_target")
    if shield_gate_target == "attacker":
        shield_gate_target = attacker_id
    shield_gate_time_raw = get("shield_gate_time")
    # The one reference the *walk* authors rather than reads: ``trigger_defy``
    # stamps the slot it already holds, so this key carries a slot and the
    # other three carry the id text a pre-walk author wrote.
    defy_slot = get("_defy_trigger_slot")
    baseline_armor = get("_baseline_effective_armor")
    baseline_mr = get("_baseline_effective_mr")
    cc_kind = str(get("cc_kind", ""))
    return SurvivalAction(
        sort_key=get("_sk")
        or action_key(
            time_value,
            phase,
            subject_id or str(get("target", "") or ""),
            event,
        ),
        time=time_value,
        phase=phase,
        kind=kind,
        subject=subject_index,
        attacker=attacker_index,
        aidx=aidx,
        trigger=-1,
        trigger_slot=EVENT_SLOTS.slot(str(trigger_id)) if trigger_id else NO_SLOT,
        event=event,
        amount=max(0.0, float(get("damage", get("amount", 0.0)) or 0.0)),
        damage_type=str(get("damage_type", "")),
        raw_formula=raw_formula,
        raw_damage=raw_damage,
        wound=(
            (grievous_duration, str(get("_wound_source", "Grievous Wounds")))
            if grievous_duration > 0.0
            else None
        ),
        reactive=bool(get("_reactive")),
        execute_threshold_ratio=max(0.0, float(execute_ratio_raw or 0.0)),
        # The source is the declaring item's own name, stamped on the packet
        # beside the ratio by whoever authored the execution.  There is no
        # fallback name: an execution whose source the packet did not carry
        # is an unstamped packet, and naming a plausible item here would be
        # the stale literal this migration removes.
        execute_source=str(get("execute_source", "")),
        deferred=bool(deferred_raw),
        deferred_batch_slot=(EVENT_SLOTS.slot(str(batch_id)) if batch_id else NO_SLOT),
        redirected=bool(redirected_raw),
        redirect_holder_health_ratio=max(
            0.0, float(get("redirect_holder_health_ratio", 0.0) or 0.0)
        ),
        redirect_original_damage=max(
            0.0, float(get("_redirect_original_damage", 0.0) or 0.0)
        ),
        redirect_cancelled=bool(get("_redirect_cancelled")),
        is_ability=bool(get("is_ability")),
        basic_attack=bool(get("basic_attack")),
        ability_instance=get("ability_instance"),
        source_key=str(get("source_key", "")),
        source=str(get("source", get("source_key", ""))),
        # ``is not None`` rather than a truth test, deliberately: an event
        # carrying an empty id string had one, and the walk keyed its applied
        # status by that empty string.  It gets a slot of its own.
        event_slot=(
            EVENT_SLOTS.slot(str(event_id)) if event_id is not None else NO_SLOT
        ),
        sequence=get("sequence"),
        # The bus answers "is this an immobilize?" for every consumer; the
        # walk used to answer it again, and the fourth re-typing is what
        # D-08 had to widen when a module started authoring ``charm``.  The
        # bare ``crowd_control`` marker stays a disjunct because it always
        # was one: the bus classifies it ``UNCLASSIFIED_CONTROL`` — control
        # nobody narrowed — and narrowing Steadfast to reject it would be a
        # semantic correction, which is Phase 0's to make and not a
        # refactor's.
        immobilized=is_immobilizing_event(event) or bool(get("crowd_control")),
        cc_kind=cc_kind,
        cc_duration=max(0.0, float(get("cc_duration", 0.0) or 0.0)),
        skillshot=bool(get("skillshot")),
        area_damage=bool(get("area_damage")),
        damage_over_time=bool(get("damage_over_time")),
        # The live-predicate amplifier the composition stamped on this
        # packet, if its holder declared one that rides this damage class.
        # ``None`` is "nobody declared one", which the kernel tells apart
        # from a bonus that measured zero.
        live_amp=get("_live_amp"),
        # The declaration this packet's retired family handed the walk, if
        # its row was stamped as a re-priced preview.  ``None`` is "the pair
        # engine still prices this family", which is every packet whose
        # family has not retired.
        declared=get("_declared"),
        baseline_effective_armor=(
            float(baseline_armor) if baseline_armor is not None else None
        ),
        baseline_effective_mr=(float(baseline_mr) if baseline_mr is not None else None),
        healing_category=str(get("healing_category", "")),
        amount_formula=get("amount_formula"),
        requires_existing_shield=bool(get("requires_existing_shield")),
        cast_while_disabled=bool(get("cast_while_disabled")),
        cast_blocked_by_attacker_control=bool(get("cast_blocked_by_attacker_control")),
        cleanse_group=str(get("cleanse_group", "") or ""),
        requires_maw_lifeline_omnivamp=bool(get("requires_maw_lifeline_omnivamp")),
        shield_gate_subject=(
            index_of.get(str(shield_gate_target), -1)
            if shield_gate_target is not None
            else -1
        ),
        shield_gate_time=(
            float(shield_gate_time_raw) if shield_gate_time_raw is not None else None
        ),
        requires_holder_health_ratio=max(
            0.0, float(get("requires_holder_health_ratio", 0.0) or 0.0)
        ),
        requires_damage_free_seconds=max(
            0.0, float(get("requires_damage_free_seconds", 0.0) or 0.0)
        ),
        overheal_to_temporary_health=bool(get("overheal_to_temporary_health")),
        temporary_health_duration=max(
            0.0, float(get("temporary_health_duration", 0.0) or 0.0)
        ),
        overheal_to_shield=bool(get("overheal_to_shield")),
        overheal_shield_cap=max(0.0, float(get("overheal_shield_cap", 0.0) or 0.0)),
        overheal_shield_duration=max(
            0.0, float(get("overheal_shield_duration", 0.0) or 0.0)
        ),
        defy_trigger_slot=int(defy_slot) if defy_slot is not None else NO_SLOT,
        duration=max(0.0, float(get("duration", 0.0) or 0.0)),
        delay=max(0.0, float(get("delay", 0.0) or 0.0)),
        health_ratio=max(0.0, float(get("health_ratio", 0.0) or 0.0)),
        on_block_heal_amount=max(0.0, float(get("on_block_heal_amount", 0.0) or 0.0)),
        on_block_heal_delay=max(0.0, float(get("on_block_heal_delay", 0.0) or 0.0)),
        on_block_heal_source=str(get("on_block_heal_source", "") or ""),
        bonus_attack_speed_percent=float(get("bonus_attack_speed_percent", 0.0) or 0.0),
        bonus_armor=float(get("bonus_armor", 0.0) or 0.0),
        bonus_magic_resistance=float(get("bonus_magic_resistance", 0.0) or 0.0),
        bonus_health=float(get("bonus_health", 0.0) or 0.0),
        ability_power=float(get("ability_power", 0.0) or 0.0),
        ability_haste=float(get("ability_haste", 0.0) or 0.0),
        on_hit_magic_damage=float(get("on_hit_magic_damage", 0.0) or 0.0),
        shield_pool=str(get("shield_pool", "") or ""),
        crowd_control_immunity_while_shield=bool(
            get("crowd_control_immunity_while_shield")
        ),
        crowd_control_immunity_source=str(
            get("crowd_control_immunity_source", "") or ""
        ),
        persistent=bool(get("persistent")),
        multiplier=float(get("multiplier", 1.0) or 1.0),
        damage_reduction=bool(get("damage_reduction")),
        next_event_only=bool(get("next_event_only")),
        all_sources=bool(get("all_sources")),
        armor_reduction_percent=float(get("armor_reduction_percent", 0.0) or 0.0),
        mr_reduction_percent=float(get("mr_reduction_percent", 0.0) or 0.0),
        resistance_type=str(get("resistance_type", "")),
        # A *restriction* on which participant's damage this modifier applies
        # to, never the holder: ``holder`` below still resolves the owner.
        source_participant=str(get("source_participant", "")),
        # The packet declares its holder as a participant id, because that is
        # what an item support author knows; the kernel wants the roster slot.
        # An owner outside this roster resolves to ``-1`` and arms no skip,
        # which is byte-identical to the string compare it replaces: the id
        # the packet carries always comes from a combatant, so a miss here
        # would have been a miss there.
        holder=index_of.get(str(get("owner", "")), -1),
        damage_classes=declared_class_set(get("damage_classes"), DamageClass),
        attack_classes=declared_class_set(get("attack_classes"), AttackClass),
        # ``kind_str`` is the event's authored kind string — the typed
        # utility marker must come from the event, not the classified
        # ActionKind enum (an enum is never a member of the string set).
        utility_kind=kind_str if kind_str in UTILITY_KINDS else "",
        gold_amount=float(get("gold_amount", 0.0) or 0.0),
        ward_uses=float(get("ward_uses", 0.0) or 0.0),
        duration_set="duration" in event,
        cleanse=bool(get("cleanse")),
        cleanse_item=str(get("cleanse_item", "") or ""),
    )


def pair_resistance_baselines(
    result: Mapping[str, Any],
) -> tuple[float | None, float | None]:
    """One pair fight's final effective armour and magic resistance.

    ``None`` for either figure the engine did not publish, or published as
    a non-finite number.  Deliberately absent rather than zero: a resistance
    reduction re-prices its packet as the ratio of two mitigation factors,
    and a missing baseline is a question the fight cannot answer, which the
    walk receipts as ``support_resistance_reduction_unavailable`` instead of
    inventing a mitigation ratio.

    One home for both representations: the compiler reads these off the
    engine result once per fight and stamps the same figure onto the action
    and onto the enriched event beside it, because a resistance-reducing
    modifier must not price differently on the two.
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
    compilers: Iterable["WalkCompiler"],
) -> str | None:
    """Refuse an armed modifier the compiled walk cannot classify against.

    An armed cross-participant modifier declares which damage classes and
    which **attack classes** it applies to (D-04), and the kernel answers
    the second question with :func:`~..survival.actions.attack_class_of`,
    which reads two per-packet delivery flags.  The engine's light tuple
    ledger carries neither: it is the score-only shape for a fight nothing
    reads per event, and there is no ``is_ability`` on a positional row to
    read.

    Those two facts meet across compilers, which is why this is asked of
    the assembled set rather than inside one of them: a roster ally's
    curse is armed in the invariant panel while the packets it amplifies
    come from the candidate's own fresh result.  Either half alone is
    fine — a light ledger with no modifier over it, or a modifier over
    enriched rows — and only the pair is unrepresentable.

    Fail closed rather than approximate: reading the flags' ``False``
    default as "this packet was neither an attack nor a spell" would amp
    exactly the auto-attack rows and quietly drop every ability row, which
    is a modifier the score path priced differently from the walk with
    nothing saying so.
    """
    if not any(compiler.staged_modifier for compiler in compilers):
        return None
    if not any(compiler.unclassified_delivery for compiler in compilers):
        return None
    return "modifier_over_light_ledger"


def revive_candidate_actions(
    actions: Iterable[SurvivalAction],
    combatants: Iterable[Any],
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
        defenses = actor.defenses
        revive_amount = max(0.0, float(defenses.revive_health_amount))
        revive_delay = max(0.0, float(defenses.revive_delay))
        if revive_amount <= 0.0 or revive_delay <= 0.0:
            continue
        revive_source = str(defenses.revive_source) or "Guardian Angel (Rebirth)"
        revive_key = (
            f"revive_{revive_source.replace(' ', '_')}"
            if revive_source != "Guardian Angel (Rebirth)"
            else "revive_Guardian Angel"
        )
        for action in actions:
            if action.subject != actor_index or action.kind not in _DAMAGE_ACTION_KINDS:
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
                SurvivalAction(
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
        "damage_order",
        "thorns_order",
        "support_entries",
        "auto_strikes_into",
        "coverage",
        "next_aidx",
        "unclassified_delivery",
        "staged_modifier",
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

    def add_engine_result(
        self,
        result: Mapping[str, Any],
        attacker_id: str,
        attacker_i: int,
        defender_id: str,
        defender_i: int,
        grievous_by_dtype: Mapping[str, Any],
        duration: float,
        heal_dedup: dict[tuple[str, float], float],
        id_strings: list[str],
        defender_index: int = 0,
        champion_wounds: Mapping[str, Any] | None = None,
        live_amps: Sequence[LiveAmpRider] = (),
        holder_amps: Any = None,
        suppress_actor_wide_heals: bool = False,
        view: "PairView | None" = None,
    ) -> None:
        """Compile one pair fight from the engine's own rows.

        The one packet compiler: every roster pair, every signature panel and
        every candidate's fresh fights reach the walk through here, so a fact
        about a packet is decided once.  The sort-key layout is
        ``action_key``'s; both must change together.  ``id_strings`` is the
        search-lifetime cache of this pair's positional event-id strings.

        A pair row the registry declares ``THEORETICAL`` is a *preview* of a
        number the coupled walk owns, so it and its events are dropped
        (:func:`~.build.pair_preview_sources`) — composing it would put the
        walk's number and a preview of it into one total.  A preview the walk
        *re-prices* keeps its packet: the walk is about to price it from its
        declaration, and dropping it would delete the family's damage.

        The four fields a pair fight cannot see for itself, and the caller
        can:

        * ``defender_index`` — the defender's slot in the attacker's ordered
          roster.  A later target is re-priced to the sourced reduced heal
          amount when the engine authored one (Vladimir's Hemoplague).
        * ``champion_wounds`` — the attacker's wound-declaring source keys
          (Katarina R, Varus E) mapped to their packets, so a champion wound
          rides its damage event as the same receipt an item wound does.
        * ``live_amps`` — the attacker's declared live-predicate amplifiers.
          They ride their own damage packets so the bonus dies with its host.
          The default is empty because most holders declare none, never
          because a caller may leave it out.
        * ``holder_amps`` — the attacker's own static, pair-local
          amplifiers, needed to compose a re-priced preview's declaration and
          required, not defaulted, the moment this fight carries one.

        ``suppress_actor_wide_heals`` marks a fight whose actor-wide heal
        copies are never the kept copy: an enemy attacker's ordered pair list
        is ``[main, *allies]``, so the walk always keeps the main-pair copy
        and the ally-pair copies are skipped here — the engine may price them
        differently per defender (issue #169, Dr. Mundo's Maximum Dosage).
        Trigger-linked actor-wide heals still fail closed before the skip.

        ``view`` selects the **receipt projection** (:class:`~.build.Projection`
        ``RECEIPT``): the per-event dict enrichment the roster composition
        reads, built from the same locals the action beside it is built from.
        Three things the score walk owes are not the receipt's: the
        fail-closed refusal of a transition *the score kernel* cannot stage
        (the receipt walk stages every one of them, which is what the
        fallback is), the cross-fight actor-wide heal dedup (the composition
        owns its own, over the copies published here), and the actions
        themselves — nobody reads them, and building them would make the
        receipt path pay for the score path's representation.
        """
        result_breakdown = result.get("breakdown") or {}
        previewed = pair_preview_sources(result_breakdown)
        # A preview the walk *re-prices* keeps its packet on both paths: the
        # pair engine's number leaves the total either way, but a re-priced
        # family's packet is the thing the walk is about to price from its
        # declaration, so dropping it would delete the family's damage.
        dropped = dropped_pair_previews(result_breakdown)
        repriced = previewed - dropped
        if repriced and holder_amps is None:
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
        cast_timeline = result.get("cast_timeline") or ()
        if not isinstance(cast_timeline, list):
            cast_timeline = ()
        # **Two row shapes, one reader.**  The engine publishes its damage
        # ledger either as enriched dicts or — for a score-only request whose
        # adequacy conditions hold — as light positional rows ``(sort_key,
        # damage, damage_type, source_key, raw_formula, raw_damage)``.  Those
        # are two *representations of one ledger*, so what differs between
        # them is how a field is spelled and nothing else: the block below is
        # the whole of the difference, and every line after it is one tail
        # both shapes reach.  It used to be two loops with fifty duplicated
        # lines each, which is how a fix applied to one of them could miss
        # the other for a whole migration.
        light = bool(result.get("damage_events_tuple"))
        # A light ledger declares no self-heals, so the heal loop below is a
        # no-op for it rather than skipped by an early return -- and that is
        # an invariant of a *different* module: ``pipeline.py`` sets
        # ``self_healing_events = []`` on the same three lines that set
        # ``damage_events_tuple``, and the comment there says the empty list
        # is the exact value ``derive_self_healing`` would have returned.
        # Reading it here rather than branching around it is what lets the
        # linkage index, the heals and the coverage append be written once;
        # the early return used to enforce the invariant structurally, so
        # dropping it without a check would trade a structure for a promise
        # kept in another file's comment.  Hence the refusal: the tuple rows
        # below carry no ``time``/``source_key`` dict keys, so a light result
        # that did declare heals would link every one of them to nothing and
        # compile a fight whose heals silently vanished.
        heals = result.get("self_healing_events", [])
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
        for index, row in enumerate(result.get("damage_events", [])):
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
                        f"{attacker_id} damage event {row.get('source_key', '')!r} "
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
                damage = wound_damage if wound_damage > 0.0 else 0.0
                raw_formula = row.get("raw_formula")
                raw_damage = float(row.get("raw_damage", 0.0) or 0.0)
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
                cc_kind = str(row.get("cc_kind", ""))
                cc_duration = max(0.0, float(row.get("cc_duration", 0.0) or 0.0))
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
                # Issue #137: fail closed on damage transitions *the score
                # kernel* cannot stage (execute thresholds, redirects,
                # deferred batches, stack self-shields) instead of silently
                # erasing them.  A light row cannot answer the question —
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
            live_amp = live_amp_for(live_amps, damage_type)
            declared = (
                declared_packet_of(declaration, damage_type, source_key, holder_amps)
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
                actions_append(
                    compiled_damage_action(
                        sort_key,
                        time_value,
                        (
                            ActionKind.PLAIN_DAMAGE
                            if live_formula is None
                            and grievous is None
                            and wound is None
                            else ActionKind.DAMAGE
                        ),
                        defender_i,
                        attacker_i,
                        aidx,
                        damage,
                        damage_type,
                        live_formula,
                        raw_damage,
                        grievous,
                        wound,
                        source_key,
                        source,
                        slot_of(event_id),
                        sequence,
                        live_amp,
                        declared,
                        is_ability,
                        basic_attack,
                        baseline_armor,
                        baseline_mr,
                        immobilized,
                        cc_kind,
                        cc_duration,
                        skillshot,
                        damage_over_time,
                        area_damage,
                        ability_instance,
                    )
                )
                if time_value <= duration:
                    order_append((aidx, time_value))
                # A light ledger omits per-event metadata, so ``basic_attack``
                # is False for it and only its explicit auto stream triggers
                # Thorns — the same sentence the two loops used to say twice.
                if source_key == "auto_attacks" or basic_attack:
                    strikes_append((aidx, time_value, sequence, attacker_i))
            else:
                view.events.append(
                    _enriched_damage_event(
                        row,
                        attacker_id,
                        defender_id,
                        event_id,
                        is_ability,
                        ability_instance,
                        basic_attack,
                        wound,
                        time_value,
                        result_breakdown.get(source_key),
                        baseline_fields,
                        live_amp,
                        declared,
                        sort_key,
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
        for control_index, raw_event in enumerate(result.get("control_events", ())):
            if "sequence" not in raw_event:
                # Same refusal as the damage loop above: pair-local event ids
                # stay order-irrelevant only while every engine row carries
                # its per-fight sequence, and a missing one would silently
                # tie-break at zero.
                raise ValueError(
                    f"{attacker_id} control event "
                    f"{raw_event.get('source_key', '')!r} has no sequence; the "
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
            time_value = float(event.get("time", 0.0))
            event["_sk"] = (
                time_value,
                control_phase,
                event_sequence(event),
                order_a,
                order_b,
                defender_id,
                event["_event_id"],
                str(event.get("source", event.get("source_key", ""))),
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
                # Issue #137: fail closed on any heal transition *the score
                # kernel* cannot stage (Severum overheal-to-shield, vamp
                # source categories, live gates) instead of silently erasing
                # it.  The receipt walk stages all three.
                heal_receipt = unrepresentable_heal_receipt(event)
                if heal_receipt is not None:
                    raise UncompilableActionError(
                        receipt=heal_receipt,
                        source=str(
                            event.get("source", event.get("source_key", "heal"))
                        ),
                    )
            trigger = aidx_by_key.get(heal_trigger_key(event), -1)
            if trigger < 0:
                candidates = aidx_by_source_time.get(
                    (
                        str(event.get("_trigger_source", "")),
                        trigger_time_key(event.get("_trigger_time", 0.0)),
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
                        source=str(event.get("source", "")),
                    )
                if suppress_actor_wide_heals:
                    continue
                dedup_key = (
                    str(event.get("source", "")),
                    float(event.get("time", 0.0)),
                )
                amount = max(0.0, float(event.get("amount", 0.0)))
                kept = heal_dedup.get(dedup_key)
                if kept is not None:
                    if kept != amount:
                        # One copy per (source, time) is only sound while
                        # every copy is value-identical.  Fail closed onto
                        # the receipt walk, which owns the keep-first rule.
                        raise UncompilableActionError(
                            receipt="actor_wide_heal_copies_disagree",
                            source=str(event.get("source", "")),
                        )
                    continue
                heal_dedup[dedup_key] = amount
            aidx = self.next_aidx
            self.next_aidx += 1
            time_value = float(event.get("time", 0.0))
            # The engine authors per-champion flat heals at the full value
            # because a pair fight cannot see the roster; a defender past the
            # first uses the sourced reduced amount (Vladimir's Hemoplague).
            amount = max(0.0, float(event.get("amount", 0.0)))
            later_amount = event.get("_later_target_amount")
            if defender_index > 0 and later_amount is not None:
                amount = max(0.0, float(later_amount))
            # ``{raw_id}:{defender_id}`` so fan-out clones can point
            # ``_source_event_id`` at the applied self copy (issue #143).
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
                str(event.get("source", event.get("source_key", ""))),
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
                SurvivalAction(
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
                    healing_category=str(event.get("healing_category", "")),
                    temporary_health_duration=(
                        max(
                            0.0,
                            float(event.get("temporary_health_duration", 0.0) or 0.0),
                        )
                        if event.get("overheal_to_temporary_health")
                        else 0.0
                    ),
                    overheal_to_temporary_health=bool(
                        event.get("overheal_to_temporary_health")
                    ),
                    source_key=str(event.get("source_key", "")),
                    source=str(event.get("source", event.get("source_key", ""))),
                    event_slot=slot_of(heal_event_id),
                    sequence=event.get("sequence"),
                )
            )
        self.coverage.append(result.get("timeline_coverage", {}))

    def add_support_templates(
        self,
        templates: Iterable[Mapping[str, Any]],
        attacker_i: int,
        index_of: Mapping[str, int],
    ) -> None:
        """Compile one attacker's resolved support packets."""
        for template in templates:
            target_id = str(template["target"])
            subject_i = index_of[target_id]
            kind = str(template.get("kind", ""))
            # Issue #137: fail closed on any resolved support template the
            # score kernel cannot stage — non-heal/shield kinds (stat buffs,
            # damage modifiers, on-hit magic, temporary health, ...), timed
            # shields/heals (duration > 0), live gates, vamp source
            # categories, live amount formulas, and trigger links — instead
            # of mis-compiling it as a flat heal or silently dropping it.
            template_receipt = unrepresentable_template_receipt(template)
            if template_receipt is not None:
                raise UncompilableActionError(
                    receipt=template_receipt,
                    source=str(template.get("source", "")),
                )
            if template.get("_trigger_event_id") is not None:
                # A support author *does* emit a trigger link: the
                # Everlasting branch in ``item_support_effects`` stamps
                # ``_trigger_event_id`` on every Fimbulwinter shield the
                # enriched view produced (``None`` when it did not, which
                # is what ``is not None`` reads).  That packet is declined
                # one branch earlier for its 3 s duration, so this guard is
                # the narrower second net: it catches a linked template
                # ``unrepresentable_template_receipt`` admits — whatever
                # clears every clause it checks.  Resolving the link would
                # need the same cross-pair id map as heals, so fail closed
                # rather than silently drop what the legacy walk would
                # apply (D-03).  All three facts are pinned by
                # ``tests/test_trigger_stream.py``'s
                # ``TestTheSupportTriggerLinkRaise`` rather than left here
                # to go stale the way the sentence this replaced did.
                raise UncompilableActionError(
                    receipt="support_trigger_link",
                    source=str(template.get("source", "")),
                )
            # When this packet arms, read from the same classifier the
            # receipt walk reads.  Classifying by kind here instead would
            # ignore a packet's own ``_rank`` declaration, so a shield
            # declaring ``LATE_BARRIER`` would arm before the damage it was
            # placed after on the compiled path and after it on the walk —
            # a desync no equality gate can see until such a packet exists.
            #
            # This also widened the *kind* ladder, which is a second thing
            # and is inert only because of the receipt above.  The branch
            # this replaced was ``BARRIER_GRANT if kind == "shield" else
            # RECOVERY``, so for the kinds ``unrepresentable_template_receipt``
            # rejects — everything but ``shield`` and ``heal`` — the rank
            # moved: ``temporary_health`` to ``BARRIER_GRANT`` and
            # ``stasis`` to ``STATE_GRANT`` (both ordering moves, out of the
            # recovery slot and ahead of the damage), ``stat_buff``/
            # ``damage_modifier`` to ``DEBUFF_ARM`` and
            # ``movement``/``cleanse``/... to ``UTILITY_ARM`` (rank moves
            # inside one ordering slot, inert until S6 splits it).
            # Admitting a kind to compilation therefore lands two behaviour
            # changes, not one: read this line before widening that
            # receipt.
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
            time_value = float(template.get("time", 0.0))
            self.actions.append(
                SurvivalAction(
                    sort_key=action_key(time_value, priority, target_id, template),
                    time=time_value,
                    phase=priority,
                    # The same classifier the receipt adapter runs, for the
                    # reason the rank above uses ``support_transition_rank``:
                    # one packet must become one action kind whichever
                    # adapter compiles it.  The literal this replaces --
                    # ``SHIELD if kind == "shield" else HEAL`` -- was a
                    # two-way fold that was correct only while the receipt
                    # admitted exactly those two kinds.  It stopped being
                    # correct the moment the state kinds were admitted: a
                    # ``crowd_control_resist`` arm (Dr. Mundo's passive) or a
                    # ``stasis``/``spell_shield``/``invulnerability``/
                    # ``untargetable`` grant compiled as a zero-amount HEAL,
                    # which is silence -- the score walk left the holder
                    # unprotected while the receipt walk armed it, and the
                    # two priced the same fight differently with nothing
                    # saying so.
                    kind=classify_event_kind(template, priority),
                    subject=subject_i,
                    attacker=attacker_i,
                    aidx=aidx,
                    amount=max(0.0, float(template.get("amount", 0.0))),
                    healing_category=str(template.get("healing_category", "")),
                    source_key=str(template.get("source_key", "")),
                    source=str(template.get("source", "")),
                    event_slot=EVENT_SLOTS.slot(str(template.get("_event_id", ""))),
                    sequence=template.get("sequence"),
                    # The typed facts a barrier carries into the shield
                    # ledger.  They read the same template fields
                    # ``action_from_event`` reads off the same packet: the
                    # two builders must produce the same tuple from one
                    # dict, and a field only one of them stamps is a
                    # mechanic one walk applies and the other drops.
                    duration=max(0.0, float(template.get("duration", 0.0) or 0.0)),
                    duration_set="duration" in template,
                    shield_pool=str(template.get("shield_pool", "") or ""),
                    crowd_control_immunity_while_shield=bool(
                        template.get("crowd_control_immunity_while_shield")
                    ),
                    crowd_control_immunity_source=str(
                        template.get("crowd_control_immunity_source", "") or ""
                    ),
                    requires_holder_health_ratio=max(
                        0.0,
                        float(template.get("requires_holder_health_ratio", 0.0) or 0.0),
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
                        float(template.get("temporary_health_duration", 0.0) or 0.0),
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
        per-mechanic fact (D-66) and the receipt composition answers it with
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
        source = str(template.get("source", ""))
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
        time_value = float(template.get("time", 0.0))
        self.actions.append(
            SurvivalAction(
                sort_key=action_key(time_value, priority, target_id, template),
                time=time_value,
                phase=priority,
                kind=ActionKind.DAMAGE_MODIFIER,
                subject=subject_i,
                attacker=attacker_i,
                aidx=aidx,
                amount=max(0.0, float(template.get("amount", 0.0) or 0.0)),
                duration=max(0.0, float(template.get("duration", 0.0) or 0.0)),
                persistent=bool(template.get("persistent")),
                multiplier=float(template.get("multiplier", 1.0) or 1.0),
                damage_reduction=bool(template.get("damage_reduction")),
                next_event_only=bool(template.get("next_event_only")),
                # The declared escape from the delivery gate: a modifier
                # that reads "from all sources" prices packets no attack
                # class covers (an auto-attack's true-damage rider).  The
                # receipt path stamps it in ``action_from_event``; omitting
                # it here made the two walks disagree by exactly the
                # unpriced packets, which no equality gate could attribute.
                all_sources=bool(template.get("all_sources")),
                source_participant=str(template.get("source_participant", "")),
                armor_reduction_percent=float(
                    template.get("armor_reduction_percent", 0.0) or 0.0
                ),
                mr_reduction_percent=float(
                    template.get("mr_reduction_percent", 0.0) or 0.0
                ),
                resistance_type=str(template.get("resistance_type", "")),
                # The packet names its holder as a participant id because
                # that is what a support author knows; the kernel's owner
                # skip wants the roster slot, and an owner outside this
                # roster resolves to ``-1`` — "this packet declares no
                # holder" — exactly as ``action_from_event`` resolves it.
                holder=index_of.get(str(template.get("owner", "")), -1),
                damage_classes=declared_class_set(
                    template.get("damage_classes"), DamageClass
                ),
                attack_classes=declared_class_set(
                    template.get("attack_classes"), AttackClass
                ),
                source_key=str(template.get("source_key", "")),
                source=source,
                event_slot=EVENT_SLOTS.slot(str(template.get("_event_id", ""))),
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
        wearer: Any,
        wearer_i: int,
        strikes: Iterable[tuple[int, float, int, Any, int]],
        profiles: tuple[Any, ...],
        grievous_by_dtype: Mapping[str, Any],
        duration: float,
        id_namespace: str,
    ) -> None:
        """Compile the wearer's strike-back events for a run of strikes.

        ``strikes`` carries ``(strike_aidx, time, sequence, striker,
        striker_i)`` in the legacy incoming-list order.  The synthetic
        event-id string participates only in the sort key, where every pair
        of distinct thorns events already differs at the sequence or
        participant component, so panel and fresh namespaces may number
        independently without affecting order.
        """
        actions = self.actions
        order = self.thorns_order[wearer_i]
        wearer_order = participant_order(wearer.participant_id)
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
                    damage = thorns_return_damage(profile, wearer, striker)
                    return_damage[damage_key] = damage
                aidx = self.next_aidx
                self.next_aidx += 1
                sort_key = (
                    strike_time,
                    ordering_slot(TransitionRank.REACTIVE),
                    strike_sequence,
                    *wearer_order,
                    striker.participant_id,
                    (
                        f"{wearer.participant_id}:{striker.participant_id}"
                        f":thorns:{profile.item_name}:{id_namespace}{index}"
                    ),
                    f"{profile.item_name} (Thorns)",
                )
                actions.append(
                    SurvivalAction(
                        sort_key=sort_key,
                        time=strike_time,
                        phase=TransitionRank.REACTIVE,
                        kind=ActionKind.DAMAGE,
                        subject=striker_i,
                        attacker=wearer_i,
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


def _knight_target_factor(
    action: SurvivalAction,
    source: Any,
    target: Any,
    raw_amount: float,
) -> float | None:
    """One recipient's mitigation factor for a Knight's Vow split.

    The receipt walk computes it from the target's combatant stats (dynamic
    bonuses are zero before the walk runs), the attacker's penetration, and
    the target's basic-damage / flat-reduction defenses.  ``None`` is "this
    packet's mitigation cannot be reconstructed", which leaves the packet
    unsplit rather than splitting it at a guessed factor.
    """
    damage_type = str(action.damage_type)
    if damage_type == "physical":
        effective = apply_armor_penetration(
            float(target.stats.get("armor", 0.0) or 0.0),
            float(source.stats.get("flat_armor_penetration", 0.0) or 0.0),
            float(source.stats.get("armor_penetration_percent", 0.0) or 0.0) / 100.0,
            float(source.stats.get("armor_penetration_bonus_percent", 0.0) or 0.0)
            / 100.0,
            float(target.stats.get("bonus_armor", 0.0) or 0.0),
        )
    elif damage_type == "magic":
        effective = apply_magic_penetration(
            float(target.stats.get("magic_resistance", 0.0) or 0.0),
            float(source.stats.get("magic_penetration_flat", 0.0) or 0.0),
            float(source.stats.get("magic_penetration_percent", 0.0) or 0.0) / 100.0,
        )
    elif damage_type == "true":
        return 1.0
    else:
        return None
    factor = apply_resistance(1.0, effective)
    if not math.isfinite(factor) or factor < 0.0:
        return None
    if action.basic_attack and damage_type != "true":
        defenses = target.defenses
        factor *= max(
            0.0, float(getattr(defenses, "basic_damage_multiplier", 1.0) or 1.0)
        )
        flat = max(
            0.0,
            float(getattr(defenses, "basic_damage_flat_reduction", 0.0) or 0.0),
        )
        cap = max(
            0.0,
            float(getattr(defenses, "basic_damage_flat_reduction_cap", 0.0) or 0.0),
        )
        if flat > 0.0 and cap > 0.0:
            mitigated = raw_amount * factor
            factor = max(0.0, (mitigated - min(flat, mitigated * cap)) / raw_amount)
    if damage_type != "true":
        defenses = target.defenses
        flat = max(
            0.0,
            float(
                getattr(
                    defenses,
                    (
                        "champion_dot_damage_flat_reduction"
                        if action.damage_over_time
                        else "champion_damage_flat_reduction"
                    ),
                    0.0,
                )
                or 0.0
            ),
        )
        if flat > 0.0:
            mitigated = raw_amount * factor
            factor = max(0.0, (mitigated - min(flat, mitigated)) / raw_amount)
    return factor


def stage_knights_vow_redirect_actions(
    compiler: WalkCompiler,
    combatants: Sequence[Any],
    tether: Mapping[str, Any],
    redirect_children: MutableMapping[int, SurvivalAction],
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
    if tether["within_range"] <= 0.0 or tether["holder_health_ready"] <= 0.0:
        return next_aidx
    target = tether["target"]
    holder = tether["holder"]
    fraction = max(0.0, min(1.0, float(tether["redirect_fraction"])))
    threshold = float(tether["threshold"])
    target_id = str(target.participant_id)
    holder_id = str(holder.participant_id)
    target_i = next(
        (
            i
            for i, combatant in enumerate(combatants)
            if combatant.participant_id == target_id
        ),
        -1,
    )
    holder_i = next(
        (
            i
            for i, combatant in enumerate(combatants)
            if combatant.participant_id == holder_id
        ),
        -1,
    )
    if target_i < 0 or holder_i < 0:
        return next_aidx
    aidx = next_aidx
    rebuilt: list[SurvivalAction] = []
    for action in compiler.actions:
        if (
            action.subject != target_i
            or action.kind not in _DAMAGE_ACTION_KINDS
            or action.amount <= 0.0
            or str(action.damage_type) not in {"physical", "magic"}
            or action.deferred
            or action.redirected
        ):
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
        original_amount = max(0.0, float(action.amount))
        raw_amount: float | None = None
        try:
            candidate = float(action.raw_damage or 0.0)
        except (TypeError, ValueError):
            candidate = 0.0
        if candidate > 0.0 and math.isfinite(candidate):
            raw_amount = candidate
        else:
            baseline = (
                action.baseline_effective_armor
                if str(action.damage_type) == "physical"
                else action.baseline_effective_mr
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
        protected_factor = _knight_target_factor(action, source, target, raw_amount)
        holder_factor = _knight_target_factor(action, source, holder, raw_amount)
        if protected_factor is None or holder_factor is None:
            rebuilt.append(action)
            continue
        direct_amount = max(0.0, raw_amount * (1.0 - fraction) * protected_factor)
        redirected_amount = max(0.0, raw_amount * fraction * holder_factor)
        parent = action._replace(
            amount=direct_amount,
            redirect_original_damage=original_amount,
            redirect_holder_health_ratio=threshold,
        )
        child_text = f"{EVENT_SLOTS.text(action.event_slot)}:redirect"
        child = SurvivalAction(
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
            baseline_effective_armor=action.baseline_effective_armor,
            baseline_effective_mr=action.baseline_effective_mr,
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
    if tether["within_range"] <= 0.0 or tether["holder_health_ready"] <= 0.0:
        return next_aidx
    holder = tether["holder"]
    target = tether["target"]
    heal_fraction = max(0.0, float(tether["heal_fraction"]))
    threshold = float(tether["threshold"])
    holder_id = str(holder.participant_id)
    target_id = str(target.participant_id)
    holder_i = next(
        (i for i, c in enumerate(combatants) if c.participant_id == holder_id), -1
    )
    target_i = next(
        (i for i, c in enumerate(combatants) if c.participant_id == target_id), -1
    )
    if holder_i < 0 or target_i < 0:
        return next_aidx
    aidx = next_aidx
    appended: list[SurvivalAction] = []
    for action in compiler.actions:
        if (
            action.attacker != target_i
            or action.kind not in _DAMAGE_ACTION_KINDS
            or action.amount <= 0.0
            or str(action.damage_type) not in {"physical", "magic", "true"}
        ):
            continue
        heal_amount = max(0.0, float(action.amount)) * heal_fraction
        if heal_amount <= 0.0:
            continue
        heal_text = f"{EVENT_SLOTS.text(action.event_slot)}:kv_heal"
        appended.append(
            SurvivalAction(
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
    heal_time: float, source: str, amount: float, index: int, aidx: int
) -> SurvivalAction:
    """One main-participant grey-health regeneration tick, as an action.

    Authored by the compiled panel path, which knows the ticks only as
    ``(time, source, amount)`` triples and has no packet dict to convert.
    The subject and attacker are roster slot ``0`` because grey health is the
    main participant's own regeneration and the panel builds it for nobody
    else.
    """
    event_id = f"main:grey:{source}:{index}"
    return SurvivalAction(
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


# ---------------------------------------------------------------------------
# The program entry point
# ---------------------------------------------------------------------------


class ProgramKey(NamedTuple):
    """The value key a compiled program is cached under.

    Three components rather than one hash, so a cache miss says *which* of
    the three moved.  Every component is derived from what it stands for --
    never an ``id()`` -- so a mutated roster or a patched pass misses instead
    of serving a number computed from inputs it no longer has.
    """

    roster: tuple
    program: tuple
    projection: str


def program_key(program: Program, projection: Projection) -> ProgramKey:
    """One program's cache key, derived from the program and nothing else.

    "Nothing else" cuts both ways, and the second direction is the one a
    cache key gets wrong: **every** field of the program is in the key, not
    the fields a reader expects to matter.  ``compile_program`` reads the
    events, so two programs sharing a roster and a pass but holding
    different events are two keys; the patch and the pass index are in for
    the same reason, since a cross-pass rebuild is a different program
    wearing the same roster.  ``caches.CACHES['compiled_actions']`` declares
    this function's parameters as its key fields and the test file reads
    both bodies to check that what the compiler takes off ``program`` is a
    subset of what this takes off it.
    """
    roster = roster_fingerprint(program.participants)
    return ProgramKey(
        roster=roster,
        program=program_fingerprint(
            roster, program.events, program.pass_index, program.patch
        ),
        projection=projection.value,
    )


class _StagedPayload(NamedTuple):
    """The action fields one routed payload family contributes.

    Each family carries its own half of the union -- ``Recovery`` has no
    damage type, ``Damage`` no duration -- so each stages itself off its own
    typed fields.  Reading them off an untyped payload with a default per
    field could not tell an absent field from a family that never had one.
    """

    kind: ActionKind
    amount: float
    damage_type: str = ""
    raw_formula: Any = None
    raw_damage: float = 0.0
    healing_category: str = ""
    amount_formula: Any = None
    duration: float = 0.0


def _stage_damage(payload: ev.Damage) -> _StagedPayload:
    return _StagedPayload(
        ActionKind.DAMAGE,
        max(0.0, float(payload.amount)),
        damage_type=str(payload.damage_type),
        raw_formula=payload.live_formula,
        raw_damage=float(payload.raw_amount),
    )


def _stage_recovery(payload: ev.Recovery) -> _StagedPayload:
    return _StagedPayload(
        ActionKind.HEAL,
        max(0.0, float(payload.amount)),
        healing_category=str(payload.healing_category),
        amount_formula=payload.amount_formula,
    )


def _stage_barrier(payload: ev.Barrier) -> _StagedPayload:
    return _StagedPayload(
        ActionKind.SHIELD,
        max(0.0, float(payload.amount)),
        duration=float(payload.duration),
    )


def _stage_temporary_health(payload: ev.TemporaryHealth) -> _StagedPayload:
    return _StagedPayload(
        ActionKind.TEMP_HEALTH,
        max(0.0, float(payload.amount)),
        duration=float(payload.duration),
    )


# How a routed payload compiles.  A family absent from this table is not a
# gap the compiler fills with a neutral action -- it raises, naming the
# family, because an event the compiler silently dropped is the whole
# incident.
_PAYLOAD_STAGING: Mapping[type, Any] = {
    ev.Damage: _stage_damage,
    ev.Recovery: _stage_recovery,
    ev.Barrier: _stage_barrier,
    ev.TemporaryHealth: _stage_temporary_health,
}

# Which rider families this compiler can stage on the action it builds.
# **Empty on purpose**, and empty is a claim rather than an omission: riders
# are a second axis (``events.RIDER_KINDS`` -- execute, defer, redirect,
# wound, amp bonus), every one of them modifies the host event's arithmetic,
# and this entry point stages none of them yet.  An unstageable *payload*
# raised while an unstageable *rider* vanished, which is the same fail-open
# shape one axis over: a compiled action with the execute threshold dropped
# is a hit that silently failed to kill.  Teaching the entry point a rider is
# one row here beside the code that reads it -- the same shape as widening
# ``_PAYLOAD_STAGING`` -- so a rider can never be staged by nobody.
_STAGED_RIDERS: frozenset[type] = frozenset()


def compile_program(
    program: Program, *, projection: Projection
) -> tuple[SurvivalAction, ...]:
    """The declared entry: one program in, the kernel's actions out.

    ``projection`` selects which fields are read -- ``SCORE`` leaves the
    observation dict off every action, because the optimizer never reads one
    -- and never which events exist.  Both projections compile the same
    events, which is the property that makes "the optimizer scored a build
    whose amplification it dropped" unrepresentable rather than tested-for.

    A payload family the kernel cannot stage raises
    :class:`~..survival.compile.UncompilableActionError` with a named
    receipt, exactly as the packet and engine-row paths do, so the caller
    falls back to the receipt walk instead of walking a program with a hole
    in it.  **A rider family it cannot stage raises the same way**, on the
    same rule and for the same reason: riders are the second axis an event
    carries (:data:`~.events.RIDER_KINDS`), the builder attaches them to
    every routed event, and a compiler that read only the payload would drop
    an execute threshold or a wound in silence -- fail-open on the axis whose
    sibling fails closed.  :data:`_STAGED_RIDERS` names the families this
    entry point can carry and is empty today.

    The sort key comes from :func:`~..survival.actions.action_key` and is not
    rebuilt here.  This function is the phase's declared future entry point,
    which makes it precisely where a fourth spelling of the eight-element key
    would take root -- and the reason the one constructor exists is that the
    receipt adapter and the score compiler each rebuilt that key by hand and
    drifted apart on a field.  Its eighth element, the source label, is empty
    for a program-built action because a routed payload carries no source
    name today; it is empty *by the same rule that empties it everywhere
    else* -- an absent key read through the one key function -- rather than
    by a literal pinned at this call site.
    """
    actions: list[SurvivalAction] = []
    for aidx, event in enumerate(program.events):
        stage = _PAYLOAD_STAGING.get(type(event.payload))
        if stage is None:
            raise UncompilableActionError(
                receipt=f"payload_family={type(event.payload).__name__}",
                source=event_id_text(event.id),
            )
        unstageable = next(
            (rider for rider in event.riders if type(rider) not in _STAGED_RIDERS),
            None,
        )
        if unstageable is not None:
            raise UncompilableActionError(
                receipt=f"rider_family={type(unstageable).__name__}",
                source=event_id_text(event.id),
            )
        staged = stage(event.payload)
        text = event_id_text(event.id)
        actions.append(
            SurvivalAction(
                sort_key=action_key(
                    event.time,
                    event.rank,
                    program.participants[int(event.subject)],
                    {
                        "attacker": program.participants[int(event.source)],
                        "sequence": event.sequence,
                        "_event_id": text,
                    },
                ),
                time=float(event.time),
                phase=event.rank,
                kind=staged.kind,
                subject=int(event.subject),
                attacker=int(event.source),
                aidx=aidx,
                amount=staged.amount,
                damage_type=staged.damage_type,
                raw_formula=staged.raw_formula,
                raw_damage=staged.raw_damage,
                healing_category=staged.healing_category,
                amount_formula=staged.amount_formula,
                duration=staged.duration,
                event_slot=EVENT_SLOTS.slot(text),
                sequence=event.sequence,
            )
        )
    if projection is Projection.SCORE:
        return tuple(actions)
    return tuple(
        action._replace(event={"_event_id": event_id_text(event.id)})
        for action, event in zip(actions, program.events)
    )


__all__ = [
    "PairView",
    "ProgramKey",
    "WalkCompiler",
    "ability_instance_for_event",
    "action_from_event",
    "compile_program",
    "grey_health_heal_action",
    "is_authored_ability_event",
    "modifier_delivery_receipt",
    "pair_resistance_baselines",
    "pair_view",
    "program_key",
    "revive_candidate_actions",
]
