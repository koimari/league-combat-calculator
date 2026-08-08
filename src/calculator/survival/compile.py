"""Compile engine packets into typed survival actions (issue #137).

One compiler builds the invariant panel (roster pairs), another builds an
evaluation's fresh actions starting after the panel's action-id range so
trigger references and the per-evaluation ``applied`` array stay aligned.

Compilation fails closed by action type: any packet/loadout carrying a
state transition the score ledger cannot represent raises
:class:`UncompilableActionError` with a named receipt, and the caller
falls back to the authoritative receipt walk instead of silently dropping
the transition (Phase 1's contract, kept verbatim).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from .actions import (
    ActionKind,
    SurvivalAction,
    action_key,
    compiled_damage_action,
    event_sequence,
    participant_order,
)
from ..item_effects import sustain_effect_value


class UncompilableActionError(ValueError):
    """A packet/loadout transition the compiled score kernel cannot represent.

    Raised by :class:`WalkCompiler` and the compile-stage capability checks
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


# Item mechanics that never surface as a packet flag but are authored
# inside the authoritative event walk (or a legacy-only second pass) and
# would be silently erased by the compiled score kernel.  This is the
# compiler's capability report, not a dispatch blocklist: the dispatch
# predicate no longer names items; compilation itself fails closed.
#
# Issue #137 Phase 2: with the defense-object dispatch gate gone, the
# report also covers defense-armed mechanics the score ledger cannot
# stage: walk-authored recovery/revive/redirect/deferral (Death's Dance,
# Knight's Vow, Guardian Angel), and state transitions that need
# per-packet metadata the light score ledger cannot carry (Annul spell
# shields, Force of Nature / Jak'Sho dynamic-resistance repricing).  The
# kernel implements all of them for the receipt adapter; the score
# adapter fails closed until their storage is representable.
#
# Warmog's Armor is not listed: its dedicated branch below owns the item
# (issue #169 — a search-invariant roster holder's Heart ticks compile
# into the base panel, so only the per-candidate scan still reports it).
COMPILED_WALK_UNREPRESENTABLE_ITEMS = frozenset(
    {
        "Banshee's Veil",  # Annul spell shield needs cast metadata
        "Catalyst of Aeons",  # Eternity resource-restore second pass is legacy-only
        "Death's Dance",  # Ignore Pain ticks + Defy authored in the event walk
        "Doran's Blade",  # Life Draining trigger-gated sustain (conservative)
        "Doran's Ring",  # Drain tick cadence (conservative)
        "Doran's Shield",  # Enduring Focus authored in the event walk
        "Eclipse",  # stack self-shield attached only by the receipt path
        "Edge of Night",  # Annul spell shield needs cast metadata
        "Fimbulwinter",  # Awe stat conversion (conservative)
        "Force of Nature",  # Steadfast reprice needs baseline resistances
        "Guardian Angel",  # Rebirth candidates authored in the event walk
        "Immortal Path",  # below-half received-healing multiplier state
        "Jak'Sho, The Protean",  # Voidborn reprice needs baseline resistances
        "Knight's Vow",  # Worthy redirect authored by the receipt scheduler
        "Maw of Malmortius",  # Lifeline omnivamp state transition
        "Verdant Barrier",  # Annul spell shield needs cast metadata
    }
)


def uncompilable_item_receipt(
    items: Iterable[Mapping[str, Any]],
    *,
    loadout_stats: Mapping[str, float] | None = None,
    warmog_ticks_compiled: bool = False,
) -> str | None:
    """Return a named receipt when a build cannot ride the compiled walk.

    Item mechanics the score kernel cannot stage either (a) are authored
    inside the authoritative event walk (Warmog's Heart, Doran's Shield
    Enduring Focus) or (b) ride a legacy-only receipt pass (Catalyst's
    Eternity resource restores).  Lifesteal/omnivamp builds are not
    reported here: compiled heal actions carry ``healing_category``, so
    the vamp carve-outs (received-healing multiplier exemption, ichor
    conversion) ride the shared kernel identically (issue #169).

    ``loadout_stats`` is the actor's resolved stats.  It is required for
    Warmog's Armor so the check mirrors the receipt walk's own gate: the
    Heart ticks are only authored once the bonus-health threshold is met,
    so an inactive Warmog is numerically identical in both walks (the
    legacy ``_has_active_warmog`` precision).  ``None`` fails closed.
    ``warmog_ticks_compiled`` is the search-invariant caller's claim that
    it authors the holder's Heart ticks itself (the roster scan; issue
    #169), so an active Warmog stops being a reason to fall back.
    """
    for item in items:
        name = str(item.get("name", ""))
        if name == "Warmog's Armor":
            if warmog_ticks_compiled:
                continue
            if loadout_stats is None:
                return f"item_mechanic={name}"
            try:
                threshold = sustain_effect_value(
                    "Warmog's Armor", "heart_bonus_health_threshold"
                )
            except (KeyError, TypeError, ValueError):
                return f"item_mechanic={name}"
            if float(loadout_stats.get("bonus_health", 0.0) or 0.0) >= float(threshold):
                return f"item_mechanic={name}"
            continue
        if name in COMPILED_WALK_UNREPRESENTABLE_ITEMS:
            return f"item_mechanic={name}"
    return None


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
    from ..resistance import apply_magic_penetration, apply_resistance

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


_DAMAGE_ACTION_KINDS = frozenset(
    {
        ActionKind.PLAIN_DAMAGE,
        ActionKind.DAMAGE,
        ActionKind.EXECUTE,
        ActionKind.DEFER,
        ActionKind.REDIRECT,
    }
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
                        candidate_time, 0.0, actor.participant_id, candidate
                    ),
                    time=candidate_time,
                    phase=0.0,
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
                    phase=float(event["_sk"][1]),
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
                    event_id=str(event.get("_event_id", "")),
                    sequence=event.get("sequence"),
                )
            )
            if time_value <= duration:
                order_append((aidx, time_value))
            if aidx_by_key is not None:
                aidx_by_key[
                    (event["source_key"], round(time_value, 9), event["sequence"])
                ] = aidx
                aidx_by_source_time[(event["source_key"], round(time_value, 9))].append(
                    aidx
                )
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
                        round(float(event.get("_trigger_time", 0.0)), 9),
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
                    phase=float(event["_sk"][1]),
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
                    event_id=str(event.get("_event_id", "")),
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
        actions_append = self.actions.append
        order_append = self.damage_order[attacker_i].append
        strikes_append = self.auto_strikes_into[defender_i].append
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
                            0.0,
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
                        event_id,
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
                        0.0,
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
                    event_id,
                    sequence,
                )
            )
            if time_value <= duration:
                order_append((aidx, time_value))
            if aidx_by_key is not None:
                time_key = round(time_value, 9)
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
                        round(float(event.get("_trigger_time", 0.0)), 9),
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
                        1.0,
                        event_sequence(event),
                        order_a,
                        order_b,
                        attacker_id,
                        heal_event_id,
                        str(event.get("source", event.get("source_key", ""))),
                    ),
                    time=time_value,
                    phase=1.0,
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
                    event_id=heal_event_id,
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
            priority = -1.0 if kind == "shield" else 1.0
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
                # No current support author emits a trigger link; resolving
                # one would need the same cross-pair id map as heals, so
                # fail closed instead of silently skipping what the legacy
                # walk might apply.
                raise UncompilableActionError(
                    receipt="support_trigger_link",
                    source=str(template.get("source", "")),
                )
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
                    event_id=str(template.get("_event_id", "")),
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
                    0.5,
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
                        phase=0.5,
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
                        event_id=sort_key[6],
                        sequence=strike_sequence,
                    )
                )
                if strike_time <= duration:
                    order.append((aidx, strike_time))


__all__ = [
    "COMPILED_WALK_UNREPRESENTABLE_ITEMS",
    "UncompilableActionError",
    "WalkCompiler",
    "champion_wound_tuple",
    "coalesce_darius_q_heals",
    "thorns_return_damage",
    "heal_trigger_key",
    "uncompilable_item_receipt",
    "unrepresentable_damage_receipt",
    "unrepresentable_heal_receipt",
    "unrepresentable_template_receipt",
]
