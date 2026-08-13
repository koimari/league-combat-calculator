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

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any, NamedTuple

from ..ability_spec import AttackClass, DamageClass
from ..survival.actions import (
    EVENT_SLOTS,
    NO_SLOT,
    ActionKind,
    SurvivalAction,
    TransitionRank,
    action_key,
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
from ..trigger_stream import is_immobilizing_event
from . import events as ev
from .build import Program, Projection
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
    trigger_id = get("_trigger_event_id")
    batch_id = get("_deferred_batch_id")
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
        baseline_effective_armor=(
            float(baseline_armor) if baseline_armor is not None else None
        ),
        baseline_effective_mr=(float(baseline_mr) if baseline_mr is not None else None),
        healing_category=str(get("healing_category", "")),
        amount_formula=get("amount_formula"),
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
        health_ratio=max(0.0, float(get("health_ratio", 0.0) or 0.0)),
        bonus_attack_speed_percent=float(get("bonus_attack_speed_percent", 0.0) or 0.0),
        ability_power=float(get("ability_power", 0.0) or 0.0),
        ability_haste=float(get("ability_haste", 0.0) or 0.0),
        on_hit_magic_damage=float(get("on_hit_magic_damage", 0.0) or 0.0),
        persistent=bool(get("persistent")),
        multiplier=float(get("multiplier", 1.0) or 1.0),
        damage_reduction=bool(get("damage_reduction")),
        next_event_only=bool(get("next_event_only")),
        armor_reduction_percent=float(get("armor_reduction_percent", 0.0) or 0.0),
        mr_reduction_percent=float(get("mr_reduction_percent", 0.0) or 0.0),
        resistance_type=str(get("resistance_type", "")),
        # The packet declares its holder as a participant id, because that is
        # what an item support author knows; the kernel wants the roster slot.
        # An owner outside this roster resolves to ``-1`` and arms no skip,
        # which is byte-identical to the string compare it replaces: the id
        # the packet carries always comes from a combatant, so a miss here
        # would have been a miss there.
        holder=index_of.get(str(get("owner", "")), -1),
        damage_classes=declared_class_set(get("damage_classes"), DamageClass),
        attack_classes=declared_class_set(get("attack_classes"), AttackClass),
        gold_amount=float(get("gold_amount", 0.0) or 0.0),
        ward_uses=float(get("ward_uses", 0.0) or 0.0),
        duration_set="duration" in event,
    )


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
        revive_amount = max(
            0.0, float(getattr(defenses, "revive_health_amount", 0.0) or 0.0)
        )
        revive_delay = max(0.0, float(getattr(defenses, "revive_delay", 0.0) or 0.0))
        if revive_amount <= 0.0 or revive_delay <= 0.0:
            continue
        revive_source = (
            str(getattr(defenses, "revive_source", "") or "")
            or "Guardian Angel (Rebirth)"
        )
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

    def add_packet(
        self,
        packet: Mapping[str, Any],
        attacker_i: int,
        defender_i: int,
        grievous_by_dtype: Mapping[str, Any],
        duration: float,
        heal_dedup: dict[tuple[str, float], float],
        *,
        suppress_actor_wide_heals: bool = False,
    ) -> None:
        """Compile one pair packet's damage events and self-heals.

        ``heal_dedup`` spans the attacker's packets, replaying the legacy
        actor-wide heal deduplication across that attacker's pair fights.
        ``suppress_actor_wide_heals`` marks a packet whose actor-wide copies
        are never the legacy-kept copy: an enemy attacker's ordered pair
        list is ``[main, *allies]``, so the receipt walk always keeps the
        main-pair copy and this compiler must skip the ally-pair copies —
        the engine may price them differently per defender (issue #169,
        Dr. Mundo's Maximum Dosage).  Trigger-linked actor-wide heals still
        fail closed before the skip.
        """
        actions_append = self.actions.append
        order_append = self.damage_order[attacker_i].append
        strikes_append = self.auto_strikes_into[defender_i].append
        heals = packet["heals"]
        aidx_by_key: dict[tuple[str, float, int], int] | None = {} if heals else None
        aidx_by_source_time: dict[tuple[str, float], list[int]] = defaultdict(list)
        aidx = self.next_aidx
        for event in packet["events"]:
            # Packet events are enriched engine-ledger rows: these fields
            # are written unconditionally, so index them directly.
            time_value = event["time"]
            damage_type = event["damage_type"]
            damage = event["damage"]
            raw_formula = event.get("raw_formula")
            raw_damage = float(event.get("raw_damage", 0.0) or 0.0)
            live_formula = (
                raw_formula if callable(raw_formula) and raw_damage > 0 else None
            )
            grievous = grievous_by_dtype.get(damage_type)
            # Issue #137: fail closed on any damage transition the score
            # kernel cannot stage (execute thresholds, redirects, deferred
            # batches, stack self-shields) instead of silently erasing it.
            damage_receipt = unrepresentable_damage_receipt(event)
            if damage_receipt is not None:
                raise UncompilableActionError(
                    receipt=damage_receipt,
                    source=str(event.get("source", event.get("source_key", "packet"))),
                )
            # Champion-applied wounds (Katarina R, Varus E) arrive stamped
            # on the packet events by ``_pair_packet``; the walk consumes
            # them exactly like a thorns strike-back wound.
            wound = None
            wound_duration = float(event.get("grievous_duration", 0.0) or 0.0)
            if wound_duration > 0.0:
                wound = (
                    wound_duration,
                    str(event.get("_wound_source", "Grievous Wounds")),
                )
            actions_append(
                SurvivalAction(
                    sort_key=event["_sk"],
                    time=time_value,
                    # ``_pair_packet`` authored this key at the damage rank
                    # (``participant_timeline``); the action names the rank
                    # rather than reading the ordering slot back out of the
                    # key, which is a fold and not a phase.
                    phase=TransitionRank.DAMAGE,
                    kind=(
                        ActionKind.PLAIN_DAMAGE
                        if live_formula is None and grievous is None and wound is None
                        else ActionKind.DAMAGE
                    ),
                    subject=defender_i,
                    attacker=attacker_i,
                    aidx=aidx,
                    amount=damage if damage > 0.0 else 0.0,
                    damage_type=damage_type,
                    raw_formula=live_formula,
                    raw_damage=raw_damage,
                    grievous=grievous,
                    wound=wound,
                    reactive=False,
                    source_key=str(event.get("source_key", "")),
                    source=str(event.get("source", event.get("source_key", ""))),
                    event_slot=EVENT_SLOTS.slot(str(event.get("_event_id", ""))),
                    sequence=event.get("sequence"),
                )
            )
            if time_value <= duration:
                order_append((aidx, time_value))
            if aidx_by_key is not None:
                aidx_by_key[
                    (
                        event["source_key"],
                        trigger_time_key(time_value),
                        event["sequence"],
                    )
                ] = aidx
                aidx_by_source_time[
                    (event["source_key"], trigger_time_key(time_value))
                ].append(aidx)
            if event["source_key"] == "auto_attacks" or event.get("basic_attack"):
                strikes_append((aidx, time_value, event["sequence"], attacker_i))
            aidx += 1
        self.next_aidx = aidx
        for event in heals:
            # Issue #137: fail closed on any heal transition the score
            # kernel cannot stage (Severum overheal-to-shield, vamp source
            # categories, live gates) instead of silently erasing it.
            heal_receipt = unrepresentable_heal_receipt(event)
            if heal_receipt is not None:
                raise UncompilableActionError(
                    receipt=heal_receipt,
                    source=str(event.get("source", event.get("source_key", "heal"))),
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
            if event.get("actor_wide"):
                if "_trigger_source" in event:
                    # Cross-pair dedup below keeps the copy that compiled
                    # first; a trigger link would make copies
                    # pair-dependent, so fail closed instead of guessing.
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
                        # The dedup keeps one copy per (source, time); that
                        # is only sound while every copy is value-identical.
                        # Fail closed onto the receipt walk, which owns the
                        # legacy keep-first precedence.
                        raise UncompilableActionError(
                            receipt="actor_wide_heal_copies_disagree",
                            source=str(event.get("source", "")),
                        )
                    continue
                heal_dedup[dedup_key] = amount
            aidx = self.next_aidx
            self.next_aidx += 1
            time_value = float(event.get("time", 0.0))
            actions_append(
                SurvivalAction(
                    sort_key=event["_sk"],
                    time=time_value,
                    # As above: the packet's heals were keyed at the recovery
                    # rank, so that is the rank this action carries.
                    phase=TransitionRank.RECOVERY,
                    kind=ActionKind.HEAL,
                    subject=attacker_i,
                    attacker=attacker_i,
                    trigger=trigger,
                    aidx=aidx,
                    amount=max(0.0, float(event.get("amount", 0.0))),
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
                    event_slot=EVENT_SLOTS.slot(str(event.get("_event_id", ""))),
                    sequence=event.get("sequence"),
                )
            )
        self.coverage.append(packet["result"].get("timeline_coverage", {}))

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
    ) -> None:
        """Compile a fresh one-pair fight straight from the engine rows.

        Equivalent to ``_pair_packet`` + :meth:`add_packet` — identical sort
        keys, trigger linkage, and heal dedup — minus the per-event dict
        enrichment nothing in score mode ever reads.  The sort-key layout is
        ``action_key``'s; both must change together.  ``id_strings`` is the
        search-lifetime cache of this pair's positional event-id strings.

        ``defender_index`` mirrors ``_pair_packet``'s: later roster targets
        are re-priced to a sourced reduced heal amount when the engine
        authored one, so the compiled walk matches the ordered receipt.

        ``champion_wounds`` maps the attacker's wound-declaring source keys
        (Katarina R, Varus E) to their packets; score mode skips
        ``_pair_packet``'s per-event dict enrichment, so the wound tuple is
        built here from the same sourced packets instead.
        """
        order_a, order_b = participant_order(attacker_id)
        # The event-id *string* stays in the sort key (position 6) and the
        # action carries only its slot, so both loops below intern once per
        # row.  Bound to a local because these two loops build tens of
        # thousands of actions per request.
        slot_of = EVENT_SLOTS.slot
        actions_append = self.actions.append
        order_append = self.damage_order[attacker_i].append
        strikes_append = self.auto_strikes_into[defender_i].append
        # Engine damage arms at the damage rank, on both the tuple ledger and
        # the dict one.  These two inline tuples are ``action_key``'s output
        # written by hand, so element 1 is that function's element 1: the
        # rank's ordering slot, which for ``DAMAGE`` is the rank itself.
        # Named once per call rather than per action: these two loops build
        # tens of thousands of sort keys per request, and the alternative — a
        # bare ordinal in tuple position 1 — is a phase nobody can grep for,
        # which is exactly how both branches escaped the first migration
        # pass.
        damage_phase = ordering_slot(TransitionRank.DAMAGE)
        known_ids = len(id_strings)
        aidx = self.next_aidx
        if result.get("damage_events_tuple"):
            # The engine's light ledger rows: (sort_key, damage, damage_type,
            # source_key, raw_formula, raw_damage), guaranteed heal-free by
            # the pipeline's tuple-ledger predicate, so no trigger linkage
            # can exist.  Every field below reads the same engine value the
            # dict path would.
            for index, row in enumerate(result.get("damage_events", [])):
                key = row[0]
                time_value = key[0]
                source_key = row[3]
                raw_formula = row[4]
                raw_damage = row[5]
                if index < known_ids:
                    event_id = id_strings[index]
                else:
                    event_id = f"{attacker_id}:{defender_id}:{index}"
                    id_strings.append(event_id)
                    known_ids += 1
                live_formula = (
                    raw_formula if callable(raw_formula) and raw_damage > 0 else None
                )
                grievous = grievous_by_dtype.get(row[2])
                wound = (
                    champion_wound_tuple(champion_wounds, source_key, row[1])
                    if champion_wounds
                    else None
                )
                actions_append(
                    compiled_damage_action(
                        (
                            time_value,
                            damage_phase,
                            key[3],
                            order_a,
                            order_b,
                            defender_id,
                            event_id,
                            source_key,
                        ),
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
                        row[1],
                        row[2],
                        live_formula,
                        raw_damage,
                        grievous,
                        wound,
                        source_key,
                        source_key,
                        slot_of(event_id),
                        key[3],
                    )
                )
                if time_value <= duration:
                    order_append((aidx, time_value))
                # Light tuple ledgers intentionally omit per-event metadata;
                # only their explicit auto stream can trigger Thorns.
                if source_key == "auto_attacks":
                    strikes_append((aidx, time_value, key[3], attacker_i))
                aidx += 1
            self.next_aidx = aidx
            self.coverage.append(result.get("timeline_coverage", {}))
            return
        heals = result.get("self_healing_events", [])
        # The trigger-linkage index costs a key tuple per damage event, so
        # a fight with no self-heals (most candidates) never builds it.
        aidx_by_key: dict[tuple[str, float, int], int] | None = {} if heals else None
        aidx_by_source_time: dict[tuple[str, float], list[int]] = defaultdict(list)
        for index, event in enumerate(result.get("damage_events", [])):
            if "sequence" not in event:
                # See action_key: pair-local event ids stay order-irrelevant
                # only while every engine event carries its per-fight sequence.
                raise ValueError(
                    f"{attacker_id} damage event {event.get('source_key', '')!r} "
                    "has no sequence; the walk's tie-break order would depend on "
                    "event-id numbering"
                )
            # The engine ledger writes these five fields unconditionally
            # (damage.add / add_declared_events), so index them directly.
            time_value = event["time"]
            sequence = event["sequence"]
            source_key = event["source_key"]
            damage_type = event["damage_type"]
            damage = event["damage"]
            raw_formula = event.get("raw_formula")
            raw_damage = float(event.get("raw_damage", 0.0) or 0.0)
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
            # Issue #137: fail closed on damage transitions the score kernel
            # cannot stage (execute thresholds, redirects, deferred batches,
            # stack self-shields) instead of silently erasing them.
            damage_receipt = unrepresentable_damage_receipt(event)
            if damage_receipt is not None:
                raise UncompilableActionError(
                    receipt=damage_receipt,
                    source=str(event.get("source", source_key)),
                )
            wound = (
                champion_wound_tuple(champion_wounds, source_key, damage)
                if champion_wounds
                else None
            )
            source = str(event.get("source", source_key))
            actions_append(
                compiled_damage_action(
                    (
                        time_value,
                        damage_phase,
                        sequence,
                        order_a,
                        order_b,
                        defender_id,
                        event_id,
                        source,
                    ),
                    time_value,
                    (
                        ActionKind.PLAIN_DAMAGE
                        if live_formula is None and grievous is None and wound is None
                        else ActionKind.DAMAGE
                    ),
                    defender_i,
                    attacker_i,
                    aidx,
                    damage if damage > 0.0 else 0.0,
                    damage_type,
                    live_formula,
                    raw_damage,
                    grievous,
                    wound,
                    source_key,
                    source,
                    slot_of(event_id),
                    sequence,
                )
            )
            if time_value <= duration:
                order_append((aidx, time_value))
            if aidx_by_key is not None:
                time_key = trigger_time_key(time_value)
                aidx_by_key[(source_key, time_key, sequence)] = aidx
                aidx_by_source_time[(source_key, time_key)].append(aidx)
            if source_key == "auto_attacks" or event.get("basic_attack"):
                strikes_append((aidx, time_value, sequence, attacker_i))
            aidx += 1
        self.next_aidx = aidx
        for heal_index, event in enumerate(heals):
            # Issue #137: fail closed on any heal transition the score
            # kernel cannot stage (Severum overheal-to-shield, vamp source
            # categories, live gates) instead of silently erasing it.
            heal_receipt = unrepresentable_heal_receipt(event)
            if heal_receipt is not None:
                raise UncompilableActionError(
                    receipt=heal_receipt,
                    source=str(event.get("source", event.get("source_key", "heal"))),
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
            if event.get("actor_wide"):
                if "_trigger_source" in event:
                    # Same invariant as add_packet's dedup above.
                    raise UncompilableActionError(
                        receipt="actor_wide_heal_trigger_link",
                        source=str(event.get("source", "")),
                    )
                dedup_key = (
                    str(event.get("source", "")),
                    float(event.get("time", 0.0)),
                )
                amount = max(0.0, float(event.get("amount", 0.0)))
                kept = heal_dedup.get(dedup_key)
                if kept is not None:
                    if kept != amount:
                        # Same fail-closed fallback as add_packet's dedup.
                        raise UncompilableActionError(
                            receipt="actor_wide_heal_copies_disagree",
                            source=str(event.get("source", "")),
                        )
                    continue
                heal_dedup[dedup_key] = amount
            aidx = self.next_aidx
            self.next_aidx += 1
            time_value = float(event.get("time", 0.0))
            # Same later-target re-price as _pair_packet: the engine authors
            # per-champion flat heals at the full value because a pair fight
            # cannot see the roster; a defender past the first uses the
            # sourced reduced amount so score mode matches the ordered walk.
            amount = max(0.0, float(event.get("amount", 0.0)))
            later_amount = event.get("_later_target_amount")
            if defender_index > 0 and later_amount is not None:
                amount = max(0.0, float(later_amount))
            # The heal id mirrors ``_pair_packet``'s enrichment
            # (``{raw_id}:{defender_id}``) so fan-out clones can point
            # ``_source_event_id`` at the applied self copy (issue #143).
            raw_heal_id = event.get("_event_id") or (f"{attacker_id}:heal:{heal_index}")
            heal_event_id = f"{raw_heal_id}:{defender_id}"
            actions_append(
                SurvivalAction(
                    sort_key=(
                        time_value,
                        ordering_slot(TransitionRank.RECOVERY),
                        event_sequence(event),
                        order_a,
                        order_b,
                        attacker_id,
                        heal_event_id,
                        str(event.get("source", event.get("source_key", ""))),
                    ),
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
            priority = support_transition_rank(template)
            aidx = self.next_aidx
            self.next_aidx += 1
            time_value = float(template.get("time", 0.0))
            self.actions.append(
                SurvivalAction(
                    sort_key=action_key(time_value, priority, target_id, template),
                    time=time_value,
                    phase=priority,
                    kind=ActionKind.SHIELD if kind == "shield" else ActionKind.HEAL,
                    subject=subject_i,
                    attacker=attacker_i,
                    aidx=aidx,
                    amount=max(0.0, float(template.get("amount", 0.0))),
                    healing_category=str(template.get("healing_category", "")),
                    source_key=str(template.get("source_key", "")),
                    source=str(template.get("source", "")),
                    event_slot=EVENT_SLOTS.slot(str(template.get("_event_id", ""))),
                    sequence=template.get("sequence"),
                )
            )
            self.support_entries.append((target_id, attacker_i, aidx, kind == "heal"))

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


# What a routed payload compiles to.  A family absent from this table is not
# a gap the compiler fills with a neutral action -- it raises, naming the
# family, because an event the compiler silently dropped is the whole
# incident.
_PAYLOAD_KINDS = {
    ev.Damage: ActionKind.DAMAGE,
    ev.Recovery: ActionKind.HEAL,
    ev.Barrier: ActionKind.SHIELD,
    ev.TemporaryHealth: ActionKind.TEMP_HEALTH,
}


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
    in it.
    """
    actions: list[SurvivalAction] = []
    for aidx, event in enumerate(program.events):
        kind = _PAYLOAD_KINDS.get(type(event.payload))
        if kind is None:
            raise UncompilableActionError(
                receipt=f"payload_family={type(event.payload).__name__}",
                source=event_id_text(event.id),
            )
        payload = event.payload
        text = event_id_text(event.id)
        actions.append(
            SurvivalAction(
                sort_key=(
                    float(event.time),
                    ordering_slot(event.rank),
                    int(event.sequence),
                    *participant_order(program.participants[int(event.source)]),
                    str(program.participants[int(event.subject)]),
                    text,
                    "",
                ),
                time=float(event.time),
                phase=event.rank,
                kind=kind,
                subject=int(event.subject),
                attacker=int(event.source),
                aidx=aidx,
                amount=max(0.0, float(getattr(payload, "amount", 0.0))),
                damage_type=str(getattr(payload, "damage_type", "")),
                raw_formula=getattr(payload, "live_formula", None),
                raw_damage=float(getattr(payload, "raw_amount", 0.0)),
                healing_category=str(getattr(payload, "healing_category", "")),
                amount_formula=getattr(payload, "amount_formula", None),
                duration=float(getattr(payload, "duration", 0.0)),
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
    "ProgramKey",
    "WalkCompiler",
    "action_from_event",
    "compile_program",
    "grey_health_heal_action",
    "program_key",
    "revive_candidate_actions",
]
