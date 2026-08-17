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
from collections.abc import Iterable, Mapping, Sequence
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
from ..survival.pricing import (
    AuthoredDeclaration,
    DeclaredPacket,
    route_declared_packet,
)
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

    One home for both readers, because both must agree exactly.  The
    receipt path stamps these onto every enriched pair event
    (``participant_timeline._pair_packet``) and the compiler reads them off
    the engine result once per fight; the same figure has to reach the same
    kernel field either way, or a resistance-reducing modifier prices
    differently on the two paths.
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
                    live_amp=event.get("_live_amp"),
                    # Composed once, by ``_pair_packet``, exactly like
                    # ``_live_amp`` beside it: this method compiles packets
                    # that path already enriched, and re-composing the
                    # declaration here would be a second reader of one
                    # declaration.
                    declared=event.get("_declared"),
                    # How the packet was delivered, read off the same two
                    # enriched fields ``action_from_event`` reads (H5).  An
                    # armed damage modifier restricts itself by attack class
                    # (D-04), so a compiled packet that could not say which
                    # class it belongs to would be amplified differently on
                    # the two paths.
                    is_ability=bool(event.get("is_ability")),
                    basic_attack=bool(event.get("basic_attack")),
                    # ``_pair_packet`` stamps these only when the fight
                    # published a finite figure, so ``get`` returning
                    # ``None`` is the same absent-means-refuse the receipt
                    # adapter reads off the same key.
                    baseline_effective_armor=event.get("_baseline_effective_armor"),
                    baseline_effective_mr=event.get("_baseline_effective_mr"),
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
        live_amps: Sequence[LiveAmpRider] = (),
        holder_amps: Any = None,
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

        "Equivalent to ``_pair_packet``" is a claim this method has to keep,
        and the pair-preview exclusion is part of it: a pair row the registry
        declares ``THEORETICAL`` is a preview of a number the coupled walk
        owns, so composing it here would put the walk's number and a preview
        of it into one score.  The receipt path drops those rows and their
        events; so does this one, through the same
        :func:`~.build.pair_preview_sources` join, because the surface that
        picks the optimizer's winner is the worst place for the two paths to
        disagree.

        ``live_amps`` is the same claim one field over.  The attacker's
        declared live-predicate amplifiers ride their own damage packets and
        the kernel prices them at the instant of the hit; score mode skips
        the enrichment that carries them on the receipt path, so the caller
        hands them over here instead.  The default is empty because most
        holders declare none — never because a caller may leave it out and
        have the amplification quietly vanish, which is why the two stamping
        sites read the same :func:`~.amp.live_amp_for`.

        ``holder_amps`` is the third field of that same shape: the attacker's
        own static, pair-local amplifiers, needed to compose the declaration
        of a re-priced preview and required — not defaulted — the moment this
        fight carries one.
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
        known_ids = len(id_strings)
        aidx = self.next_aidx
        # Per fight, not per event: the engine publishes one pair of final
        # effective resistances for the whole pair fight, which is exactly
        # what ``_pair_packet`` stamps onto every enriched event of it.
        baseline_armor, baseline_mr = pair_resistance_baselines(result)
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
        # The trigger-linkage index costs a key tuple per damage event, so
        # a fight with no self-heals (most candidates, and every light
        # ledger) never builds it.
        aidx_by_key: dict[tuple[str, float, int], int] | None = {} if heals else None
        aidx_by_source_time: dict[tuple[str, float], list[int]] = defaultdict(list)
        for index, row in enumerate(result.get("damage_events", [])):
            if light:
                key = row[0]
                time_value = key[0]
                sequence = key[3]
                source_key = row[3]
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
                # ``continue`` rather than a filtered list, exactly as in
                # ``_pair_packet``: ``index`` is the per-pair event id and
                # re-numbering the survivors would move every public id
                # downstream of the first preview.
                continue
            if light:
                damage_type = row[2]
                # One number for both readers: a light row's damage is the
                # engine's own, and the clamp below belongs to the dict
                # shape, whose ``damage`` field can carry a negative for a
                # transition the wound tuple still prices at face value.
                wound_damage = damage = row[1]
                raw_formula = row[4]
                raw_damage = row[5]
                declaration = row[6]
                source = source_key
                # A light ledger row carries no delivery metadata, so
                # neither flag can be answered from it.  That is recorded
                # once for the whole result below (``unclassified_delivery``)
                # rather than guessed per row: a modifier restricted by
                # attack class must not read ``False`` as "this was neither
                # an attack nor a spell".
                is_ability = basic_attack = False
            else:
                damage_type = row["damage_type"]
                wound_damage = row["damage"]
                damage = wound_damage if wound_damage > 0.0 else 0.0
                raw_formula = row.get("raw_formula")
                raw_damage = float(row.get("raw_damage", 0.0) or 0.0)
                declaration = row.get("declared")
                source = str(row.get("source", source_key))
                is_ability = bool(row.get("is_ability"))
                basic_attack = bool(row.get("basic_attack"))
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
            if not light:
                # Issue #137: fail closed on damage transitions the score
                # kernel cannot stage (execute thresholds, redirects,
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
                    live_amp_for(live_amps, damage_type),
                    (
                        declared_packet_of(
                            declaration, damage_type, source_key, holder_amps
                        )
                        if source_key in repriced
                        else None
                    ),
                    is_ability,
                    basic_attack,
                    baseline_armor,
                    baseline_mr,
                )
            )
            if time_value <= duration:
                order_append((aidx, time_value))
            if aidx_by_key is not None:
                time_key = trigger_time_key(time_value)
                aidx_by_key[(source_key, time_key, sequence)] = aidx
                aidx_by_source_time[(source_key, time_key)].append(aidx)
            # A light ledger omits per-event metadata, so ``basic_attack`` is
            # False for it and only its explicit auto stream triggers Thorns
            # — the same sentence the two loops used to say twice.
            if source_key == "auto_attacks" or basic_attack:
                strikes_append((aidx, time_value, sequence, attacker_i))
            aidx += 1
        self.unclassified_delivery = self.unclassified_delivery or light
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

# Which rider families this compiler can stage on the action it builds.
# **Empty on purpose**, and empty is a claim rather than an omission: riders
# are a second axis (``events.RIDER_KINDS`` -- execute, defer, redirect,
# wound, amp bonus), every one of them modifies the host event's arithmetic,
# and this entry point stages none of them yet.  An unstageable *payload*
# raised while an unstageable *rider* vanished, which is the same fail-open
# shape one axis over: a compiled action with the execute threshold dropped
# is a hit that silently failed to kill.  Teaching the entry point a rider is
# one row here beside the code that reads it -- the same shape as widening
# ``_PAYLOAD_KINDS`` -- so a rider can never be staged by nobody.
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
        kind = _PAYLOAD_KINDS.get(type(event.payload))
        if kind is None:
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
        payload = event.payload
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
    "modifier_delivery_receipt",
    "pair_resistance_baselines",
    "program_key",
    "revive_candidate_actions",
]
