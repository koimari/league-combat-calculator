"""The one walk that owns every mana transition against a single `resource_ledger` account."""

import heapq
from typing import Any

from ... import (
    item_effects,
    mana_item_schedules,
    manaflow_ledger,
    resource_events,
    resource_ledger,
)
from ...ability_atoms import ability_field
from ..config import declared_option_default
from ..results import CastPlan
from ..state import FightState
from .cast_plan import _cast_admission_events, _CastAdmission, _resource_timeline
from .cast_schedule import _CAST_SCHEDULE_EPS
from .mana_declarations import (
    _auto_restore_decl,
    _auto_restore_schedule,
    _enlighten_decl_for,
    _kill_refund_decl,
    _kill_refund_decl_for_state,
    _manaflow_hit_identity,
    _manaflow_ledger_for,
    _manaflow_swing_rows,
    _mark_refund_decl,
    _mark_refund_decl_for_state,
    _return_denied_burst_budget,
)


def _apply_mana_resource_limits(state: FightState, plan: CastPlan) -> CastPlan:
    """Admit MANA casts through the typed resource ledger (P3 slice 1).

    One account per fight owner owns every transition: base regeneration
    ticks, external restores (Catalyst's Eternity, Essence Reaver's
    Spellblade), ability restores, per-auto mana restores (Jayce's W
    passive), Essence Flux mark refunds (Ezreal's W), cast spends, the
    Manaflow holder's max-mana growth (proven accepted eligible hits only),
    and Lost Chapter's Enlighten level-up restore.  The ledger's receipts are
    the single source the public resource section and the Manaflow packets
    project from, so there is no second receipt-only ledger.

    Champion resource mechanics ride the SAME account as cast admission,
    so restored/refunded mana can enable later casts; every restore lands
    on the restore tier (0) before a simultaneous cast's spend tier (1),
    and a denied cast never arms, detonates, or restores anything.
    """
    base_maximum = float(state.champion_stats["max_mana"])
    regen = float(state.champion_stats["resource_regen_per_second"])
    owner = str(state.resource_ledger_owner)
    ledger = resource_ledger.ResourceLedger(
        owner,
        maximum=base_maximum,
        current=base_maximum,
        regen_per_second=regen,
    )
    manaflow = _manaflow_ledger_for(state, owner)
    enlighten_decl = _enlighten_decl_for(state)

    events = _cast_admission_events(state, plan)

    admission = _CastAdmission(state, plan)
    previous_time = 0.0

    # Essence Reaver's Manaflow is restored by the accepted Spellblade attack,
    # not by the ability that arms it.  Keep those restores on the same
    # ordered resource timeline so a later cast can actually spend the mana
    # the preceding empowered attack returned.  Scheduling the restore only
    # after its arming cast is accepted also prevents an omitted cast from
    # minting phantom resources.
    spellblade = state.item_spellblade
    mana_restore_per_proc = 0.0
    spellblade_cooldown_ready = float("-inf")
    spellblade_restore_count = 0
    if (
        spellblade is not None
        and (
            spellblade.mana_restore_base_ad_ratio or spellblade.mana_restore_crit_ratio
        )
        and state.num_auto_attacks > 0
    ):
        stats = state.champion_stats
        mana_restore_per_proc = item_effects.essence_reaver_mana_restore_per_proc(
            base_attack_damage=stats["base_attack_damage"],
            critical_strike_chance=stats["critical_strike_chance"],
            item_name=spellblade.source.item_name,
        )

    # The external restores on this lane are Catalyst's Eternity rows; the
    # restore handler reads the producer off the key rather than dispatching
    # on an item name.
    timeline = _resource_timeline(state, events, restore_producer="Catalyst of Aeons")
    # Lost Chapter's Enlighten: the explicit sourced level-up timing (the
    # smallest public option choice) authors ONE marker event.  On pop it
    # schedules the deterministic 20%-over-3s ticks against the account's
    # LIVE maximum; a missing choice creates no trigger.
    enlighten_holder = "Lost Chapter"
    enlighten_level_up = 0.0
    if enlighten_decl is not None:
        unset = declared_option_default(
            "item", enlighten_holder, "enlighten_level_up_seconds"
        )
        enlighten_level_up = float(
            ((state.item_options or {}).get(enlighten_holder) or {}).get(
                "enlighten_level_up_seconds", unset
            )
            or unset
        )
    if enlighten_decl is not None and enlighten_level_up > 0.0:
        timeline.append(
            (enlighten_level_up, 0, -2, 0, "enlighten", enlighten_holder, 0.0),
        )
    # (Enlighten tick events ride kind "enlighten_tick" so popping a tick
    # can never re-enter the level-up marker handler and re-schedule.)
    # Per-auto mana restore (Jayce's W passive): one ledger gain per
    # modeled basic attack.  Ordinary swings ride the fight's uniform
    # ordinary-rate schedule (post-burst count — see
    # ``_auto_restore_schedule``); empowered-burst swings (Hyper Charge's
    # 3 attacks) restore at their cast-relative times and are gated on
    # their arming cast being ACCEPTED, so a denied cast can never mint
    # mana.  All land on the restore tier, so a simultaneous cast input
    # sees them (engine restore-before-cast convention).
    auto_restore_decl = _auto_restore_decl(state)
    auto_restore_key = auto_restore_decl[0] if auto_restore_decl is not None else None
    auto_restore = auto_restore_decl[1] if auto_restore_decl is not None else None
    auto_restore_rows: list[dict[str, Any]] = []
    auto_restore_denials: list[dict[str, Any]] = []
    if auto_restore is not None:
        ordinary_times, swing_events = _auto_restore_schedule(state, plan)
        auto_restore_rows = [
            {"kind": "ordinary", "auto_index": index + 1}
            for index in range(len(ordinary_times))
        ]
        for swing in swing_events:
            auto_restore_rows.append(
                {
                    "kind": "swing",
                    "auto_index": len(auto_restore_rows) + 1,
                    "arming_key": swing["arming_key"],
                    "burst_seconds": swing.get("burst_seconds", 0.0),
                    "arming_ordinal": swing["arming_ordinal"],
                    "swing_index": swing["swing_index"],
                }
            )
        for row_index, restore_time in enumerate(ordinary_times):
            timeline.append((restore_time, 0, -4, row_index, "auto_restore", "", 0.0))
        for row_index in range(len(ordinary_times), len(auto_restore_rows)):
            swing = swing_events[row_index - len(ordinary_times)]
            if swing["time"] <= state.fight_duration_seconds + _CAST_SCHEDULE_EPS:
                timeline.append(
                    (swing["time"], 0, -4, row_index, "auto_swing_restore", "", 0.0)
                )
    # Manaflow's second trigger stream.  Three of the five holders spend a
    # charge "on-hit and whenever affecting an enemy or ally with an
    # ability" (cached clause), and the sentence that grants the mana covers
    # both triggers, so the streams share one cadence, one charge pool and
    # one grant pair.  Basic attacks ride the same swing schedule the
    # per-auto restore walk does and sort on the restore phase, so a swing
    # at 1.0 takes the charge a cast at 1.2 then finds spent.
    manaflow_swings = _manaflow_swing_rows(state, plan, manaflow)
    for row_index, swing_row in enumerate(manaflow_swings):
        timeline.append(
            (swing_row["time"], 0, -5, row_index, "manaflow_on_hit", "", 0.0)
        )
    heapq.heapify(timeline)

    sequence = 0
    manaflow_hits: list[dict[str, Any]] = []
    enlighten_public: dict[str, Any] | None = None
    # Essence Flux marks: one row per accepted W cast (arm order), FIFO
    # consumption by the next accepted ability cast (the model assumes
    # every cast hits, so the mark is always detonated by the next
    # ability — the 4s mark window and target-side spell shields are not
    # modeled; see the champion module's ASSUMPTIONS).
    pending_marks: list[dict[str, Any]] = []
    mark_refunds: list[dict[str, Any]] = []
    mark_decl_public: dict[str, Any] | None = None
    mark_refund_key = _mark_refund_decl_for_state(state)
    kill_refund_key = _kill_refund_decl_for_state(state)
    while timeline:
        (
            cast_time,
            _phase,
            _order_index,
            ordinal,
            kind,
            key,
            restore_amount,
        ) = heapq.heappop(timeline)
        # Base regeneration accrues on EVERY pop, restores included, so the
        # integration is per event rather than per cast.
        regen_amount = max(0.0, cast_time - previous_time) * regen
        previous_time = cast_time
        if regen_amount > 0.0:
            ledger.apply(
                resource_events.ResourceEvent(
                    owner=owner,
                    operation=resource_events.OP_REGEN,
                    amount=regen_amount,
                    time=cast_time,
                    source="base regeneration",
                    sequence=sequence,
                    tier=resource_events.TIER_RESTORE,
                )
            )
            sequence += 1
        if kind == "restore":
            # The heap key names the restore source: Catalyst's Eternity rows
            # ride the item name, Spellblade procs ride the empty key.  No
            # item-name dispatch happens here.
            source = (
                "Catalyst of Aeons (Eternity)" if key else "Essence Reaver (Manaflow)"
            )
            ledger.apply(
                resource_events.ResourceEvent(
                    owner=owner,
                    operation=resource_events.OP_GAIN,
                    amount=restore_amount,
                    time=cast_time,
                    source=source,
                    sequence=sequence,
                    tier=resource_events.TIER_RESTORE,
                )
            )
            sequence += 1
            continue
        if kind == "enlighten":
            enlighten_public = _schedule_enlighten(
                state,
                ledger,
                owner,
                enlighten_decl,
                level_up_time=enlighten_level_up,
                marker_time=cast_time,
                timeline=timeline,
            )
            continue
        if kind == "enlighten_tick":
            # One deterministic Enlighten tick: 20% max mana over 3s in
            # equal parts, applied on the restore tier so a simultaneous
            # cast sees it (engine restore-before-cast convention).
            ledger.apply(
                resource_events.ResourceEvent(
                    owner=owner,
                    operation=resource_events.OP_GAIN,
                    amount=restore_amount,
                    time=cast_time,
                    source="Lost Chapter \u2014 Enlighten",
                    sequence=sequence,
                    tier=resource_events.TIER_RESTORE,
                    detail={
                        "tick": ordinal,
                        "ticks": (
                            enlighten_decl.ticks if enlighten_decl is not None else 0
                        ),
                        "level_up_time": enlighten_level_up,
                    },
                )
            )
            sequence += 1
            continue
        if kind == "manaflow_on_hit" and manaflow is not None:
            # One modeled basic attack spending from the shared charge pool.
            # A burst swing whose arming cast was denied never lands, so it
            # cannot spend; every other swing is receipted whether or not a
            # charge was banked, the same way an accepted cast is.
            swing_row = manaflow_swings[ordinal]
            arming_key = swing_row["arming_key"]
            if arming_key is not None:
                fired = admission.accepted_ordinals.get(arming_key, set())
                if swing_row["arming_ordinal"] not in fired:
                    continue
            hit_receipt, manaflow_event = manaflow.hit(
                time=cast_time,
                hit_identity=f"auto:{swing_row['auto_index']}",
                target_kind=state.target_class,
                trigger=manaflow_ledger.TRIGGER_BASIC_ATTACK,
                sequence=sequence,
            )
            sequence += 1
            manaflow_hits.append(hit_receipt)
            if manaflow_event is not None:
                ledger.apply(manaflow_event)
                sequence += 1
            continue
        if kind in ("auto_restore", "auto_swing_restore"):
            # One modeled basic attack's mana restore (Jayce's W passive).
            # A burst swing whose arming Hyper Charge was denied never
            # lands, so its restore is a denial receipt, not a guess.
            row = auto_restore_rows[ordinal]
            if row["kind"] == "swing":
                arming = admission.accepted_ordinals.get(row["arming_key"], set())
                if row["arming_ordinal"] not in arming:
                    auto_restore_denials.append(
                        {
                            "time": cast_time,
                            "source": auto_restore["source"],
                            "accepted": False,
                            "reason": "arming_cast_denied",
                            "arming_slot": row["arming_key"],
                            "arming_ordinal": row["arming_ordinal"] + 1,
                            "swing_index": row["swing_index"],
                        }
                    )
                    # P1 Slice 12 (R1): a DENIED arming cast never fires
                    # its swings, so the fight never saved that burst
                    # time — return it to the ordinary restore budget.
                    #  The first denied swing of the cast mints the
                    #  returned ordinary rows at the current count's
                    #  continuation (the engine's post-admission ordinary
                    #  stream is uninterrupted).
                    if row["swing_index"] == 1:
                        _return_denied_burst_budget(
                            state,
                            plan,
                            auto_restore_rows,
                            row,
                            timeline=timeline,
                        )
                    continue
            detail: dict[str, Any] = {
                "slot": auto_restore_key,
                "auto_index": row["auto_index"],
                "kind": row["kind"],
            }
            if row["kind"] == "swing":
                detail["arming_slot"] = row["arming_key"]
                detail["arming_ordinal"] = row["arming_ordinal"] + 1
                detail["swing_index"] = row["swing_index"]
            ledger.apply(
                resource_events.ResourceEvent(
                    owner=owner,
                    operation=resource_events.OP_GAIN,
                    amount=auto_restore["amount"],
                    time=cast_time,
                    source=auto_restore["source"],
                    sequence=sequence,
                    tier=resource_events.TIER_RESTORE,
                    atoms=auto_restore["atoms"],
                    detail=detail,
                )
            )
            sequence += 1
            continue
        info = state.ability_damages[key]
        if admission.recast_parent_denied(info, ordinal):
            admission.omit(key)
            continue
        cost = float(ability_field(info, "resource_cost"))
        if (
            cost > 0.0
            and state.actualizer_active_until > cast_time + _CAST_SCHEDULE_EPS
        ):
            cost *= state.actualizer_resource_cost_multiplier
        spend = ledger.apply(
            resource_events.ResourceEvent(
                owner=owner,
                operation=resource_events.OP_SPEND,
                amount=cost,
                time=cast_time,
                source=f"ability {key} cast",
                sequence=sequence,
                tier=resource_events.TIER_CAST,
                detail={"slot": key, "ordinal": ordinal + 1},
            )
        )
        sequence += 1
        if not spend.accepted:
            # A denied cast cannot spend, so it can never consume a Manaflow
            # charge (the hit is only driven below for accepted casts).
            admission.omit(key)
            continue
        before = spend.current_before
        remaining = spend.current_after
        admission.spent += cost

        restored = admission.restore_for(info)
        if restored > 0.0:
            restored_receipt = ledger.apply(
                resource_events.ResourceEvent(
                    owner=owner,
                    operation=resource_events.OP_GAIN,
                    amount=restored,
                    time=cast_time,
                    source=f"ability {key} restore",
                    sequence=sequence,
                    tier=resource_events.TIER_RESTORE,
                )
            )
            sequence += 1
            remaining = restored_receipt.current_after
        accepted_ordinal = admission.accept(
            key,
            ordinal,
            cast_time,
            resource_before=before,
            resource_restored=restored,
            resource_after=remaining,
        )

        # Manaflow: only an ACCEPTED cast with a PROVEN target-affecting
        # identity can consume a charge.  The granted bonus maximum mana
        # enters the authoritative account; a missing identity fails closed
        # with a receipt and no charge is spent.  The fight's own target
        # class picks which of the holder's two sourced amounts is paid —
        # the declaration carries both, so a minion-class fight pays the
        # trigger amount rather than the champion one.
        if manaflow is not None:
            identity = _manaflow_hit_identity(key, accepted_ordinal, info)
            hit_receipt, manaflow_event = manaflow.hit(
                time=cast_time,
                hit_identity=identity,
                target_kind=state.target_class,
                sequence=sequence,
            )
            sequence += 1
            manaflow_hits.append(hit_receipt)
            if manaflow_event is not None:
                ledger.apply(manaflow_event)
                sequence += 1

        # Essence Flux mark refund (Ezreal's W): an accepted mark-arming
        # cast (W) both consumes the OLDEST pending mark (if any — the
        # mark is detonated by the next ability cast against the target;
        # every cast is assumed to hit) and arms a fresh mark.  The
        # refund is 60 + the detonating ability's ACTUAL paid cost (the
        # same ``cost`` this cast just spent, Actualizer discount
        # included).  It lands AFTER this cast's spend at the same
        # timestamp, so it can only enable LATER casts — never the
        # detonating one (the in-game sequence: cast, hit, refund).
        # Denied casts never arm or detonate (they never happen).
        mark_refund = _mark_refund_decl(info) if key == mark_refund_key else None
        kill_refund = _kill_refund_decl(info) if key == kill_refund_key else None
        if pending_marks:
            # ANY accepted ability cast against the target detonates the
            # OLDEST pending Essence Flux mark (every cast is assumed to
            # hit).  The refund is the mark's flat (60) plus THIS cast's
            # actual paid cost (the same ``cost`` just spent, Actualizer
            # discount included); it lands after this cast's spend, so it
            # can only enable LATER casts — never the detonating one
            # (in-game sequence: cast, hit, refund).  With the
            # basic_attack detonation option no mark is ever pending
            # (nothing is armed), so nothing consumes here.
            # P1 Slice 13 (R1): the mark's 4s window is enforced — a
            # detonation landing after the window is receipted
            # ``mark_expired`` and never refunds (the cached prose "marks
            # ... for 4 seconds", the binary DetonationTimeout 4.0, the
            # atom timing.active_duration b32849b968950b8e).
            if (
                cast_time - pending_marks[0]["time"]
                > pending_marks[0]["window_seconds"] + _CAST_SCHEDULE_EPS
            ):
                # The mark expired before this cast's hit — receipted, no
                # refund, and the cast still arms its own mark below.
                expired = pending_marks.pop(0)
                expired["accepted"] = False
                expired["reason"] = "mark_expired"
                expired["detonating_slot"] = None
                expired["detonating_ordinal"] = None
                expired["detonating_cost"] = 0.0
                expired["refund_amount"] = 0.0
                expired["refund_time"] = None
            else:
                consumed = pending_marks.pop(0)
                refund_amount = consumed["flat"] + cost
                consumed["accepted"] = True
                consumed["reason"] = "applied"
                consumed["detonating_slot"] = key
                consumed["detonating_ordinal"] = ordinal + 1
                consumed["detonating_cost"] = cost
                consumed["refund_amount"] = refund_amount
                consumed["refund_time"] = cast_time
                ledger.apply(
                    resource_events.ResourceEvent(
                        owner=owner,
                        operation=resource_events.OP_GAIN,
                        amount=refund_amount,
                        time=cast_time,
                        source=consumed["source"],
                        sequence=sequence,
                        tier=resource_events.TIER_RESTORE,
                        atoms=consumed["atoms"],
                        detail={
                            "mark_slot": consumed["mark_slot"],
                            "mark_ordinal": consumed["mark_ordinal"],
                            "detonating_slot": key,
                            "detonating_ordinal": ordinal + 1,
                            "detonating_cost": cost,
                            "flat": consumed["flat"],
                        },
                    )
                )
                sequence += 1
        if mark_refund is not None:
            # This accepted cast arms a fresh mark (Ezreal's W).  Denied
            # casts never arm (they never happen).  The public declaration
            # is captured once from the first arming cast.
            if mark_decl_public is None:
                mark_decl_public = {
                    "flat": mark_refund["flat"],
                    "window_seconds": mark_refund["window_seconds"],
                    "source": mark_refund["source"],
                    "atoms": [list(atom) for atom in mark_refund["atoms"]],
                    "detonation": mark_refund["detonation"],
                }
            mark_row: dict[str, Any] = {
                "time": cast_time,
                "source": mark_refund["source"],
                "flat": mark_refund["flat"],
                "window_seconds": mark_refund["window_seconds"],
                "atoms": [list(atom) for atom in mark_refund["atoms"]],
                "accepted": False,
                "reason": (
                    "basic_attack_detonation"
                    if mark_refund["detonation"] == "basic_attack"
                    else "armed"
                ),
                "mark_slot": key,
                "mark_ordinal": ordinal + 1,
                "detonating_slot": None,
                "detonating_ordinal": None,
                "detonating_cost": 0.0,
                "refund_amount": 0.0,
                "refund_time": None,
            }
            mark_refunds.append(mark_row)
            if mark_refund["detonation"] == "ability":
                pending_marks.append(mark_row)

        # P4-14: Darius W's asserted kill refund — an accepted W cast in
        # the kill declaration refunds the flat (the sourced 40) at the
        # cast's timestamp AFTER its spend (cast, hit, refund — the
        # Ezreal mark-refund ordering), so it can only enable later
        # casts.  Denied casts never refund (they never happen).
        if key == kill_refund_key and kill_refund is not None:
            ledger.apply(
                resource_events.ResourceEvent(
                    owner=owner,
                    operation=resource_events.OP_GAIN,
                    amount=kill_refund["flat"],
                    time=cast_time,
                    source=kill_refund["source"],
                    sequence=sequence,
                    tier=resource_events.TIER_RESTORE,
                    atoms=kill_refund["atoms"],
                    detail={"slot": key, "ordinal": ordinal + 1},
                )
            )
            sequence += 1

        # One Spellblade proc is consumed by one basic attack.  The
        # authored auto stream caps how many accepted casts can return
        # mana; cooldown and weave delay determine when each return lands.
        if (
            mana_restore_per_proc > 0.0
            and spellblade is not None
            and spellblade_restore_count < state.num_auto_attacks
        ):
            proc_time = (
                max(cast_time, spellblade_cooldown_ready) + spellblade.weave_delay
            )
            spellblade_cooldown_ready = proc_time + spellblade.cooldown
            if proc_time <= state.fight_duration_seconds + _CAST_SCHEDULE_EPS:
                heapq.heappush(
                    timeline,
                    (
                        proc_time,
                        0,
                        -1,
                        spellblade_restore_count,
                        "restore",
                        "",
                        mana_restore_per_proc,
                    ),
                )
                spellblade_restore_count += 1

    # Marks still pending when the fight ends were never detonated by an
    # ability in-window — receipted, never guessed (fail closed).  A mark
    # whose 4s window elapsed before the fight ended is ``mark_expired``
    # (P1 Slice 13), otherwise ``mark_undetonated``.
    for mark in pending_marks:
        if not mark["accepted"]:
            if (
                mark["time"] + mark.get("window_seconds", 0.0)
                < state.fight_duration_seconds + _CAST_SCHEDULE_EPS
            ):
                mark["reason"] = "mark_expired"
            else:
                mark["reason"] = "mark_undetonated"

    auto_restore_section: dict[str, Any] | None = None
    if auto_restore is not None:
        auto_restore_section = {
            "declaration": {
                "amount": auto_restore["amount"],
                "source": auto_restore["source"],
                "atoms": [list(atom) for atom in auto_restore["atoms"]],
            },
            "denials": auto_restore_denials,
        }
    mark_refunds_section: dict[str, Any] | None = None
    if mark_decl_public is not None:
        mark_refunds_section = {
            "declaration": mark_decl_public,
            "marks": mark_refunds,
        }

    # Catalyst's Eternity heal is a projection of THIS account's accepted
    # spend receipts: one heal row per accepted spend at the cast time, capped
    # per cast and per one-second bucket.  It is computed here, once, from the
    # ledger receipts, so the receipt walk and the score-only walk carry
    # byte-identical heal rows.  Recomputing it from ``cast_timeline`` instead
    # would read rows score-only mode truncates to the undiscounted
    # ``resource_cost``.
    catalyst_section: dict[str, Any] | None = None
    if item_effects.has_item(state.items, "Catalyst of Aeons"):
        declaration = item_effects.catalyst_eternity_declaration()
        heal_rows = mana_item_schedules.catalyst_eternity_heal_schedule(
            ledger.receipts(),
            heal_ratio=declaration["mana_spent_heal_ratio"],
            cap_per_cast=declaration["mana_spent_heal_cap_per_cast"],
            cap_per_second=declaration["mana_spent_heal_cap_per_second"],
        )
        catalyst_section = {
            "declaration": declaration,
            "heals": [row.public() for row in heal_rows],
        }
    return admission.cast_plan(
        resource_remaining=ledger.account.current,
        resource_ledger=_resource_ledger_public(
            ledger,
            manaflow,
            manaflow_hits,
            enlighten_public,
            auto_restore=auto_restore_section,
            mark_refunds=mark_refunds_section,
            catalyst=catalyst_section,
        ),
    )


def _schedule_enlighten(
    state: FightState,
    ledger: resource_ledger.ResourceLedger,
    owner: str,
    declaration: mana_item_schedules.EnlightenDeclaration | None,
    *,
    level_up_time: float,
    marker_time: float,
    timeline: list[tuple[float, int, int, int, str, str, float]],
) -> dict[str, Any]:
    """Pop the Enlighten level-up marker and schedule its restore ticks.

    The 20% base is fixed at the level-up moment against the account's LIVE
    maximum (Manaflow hits before the level-up enlarge the base; later events
    never retroactively resize it).  Ticks land at +1/+2/+3s on the restore
    tier, so a simultaneous cast sees them (the engine's restore-before-
    cast convention); resource changes affect only casts at or after each
    tick's timestamp.  A level-up authored outside the fight window is
    receipted, never guessed.
    """
    if declaration is None:
        return {
            "triggered": False,
            "reason": "no_declaration",
            "level_up_time": level_up_time,
            "ticks_total": 0,
            "ticks_within_window": 0,
        }
    if marker_time > state.fight_duration_seconds + _CAST_SCHEDULE_EPS:
        return {
            "declaration": declaration.public(),
            "triggered": False,
            "reason": "outside_fight_window",
            "level_up_time": level_up_time,
            "ticks_total": declaration.ticks,
            "ticks_within_window": 0,
        }
    ticks = mana_item_schedules.enlighten_schedule(
        level_up_time=level_up_time,
        maximum_mana=ledger.account.maximum,
        declaration=declaration,
        sequence=0,
        owner=owner,
    )
    within_window = 0
    for tick in ticks:
        if tick.time > state.fight_duration_seconds + _CAST_SCHEDULE_EPS:
            continue
        within_window += 1
        heapq.heappush(
            timeline,
            (
                tick.time,
                0,
                -3,
                int(tick.detail.get("tick", 0)),
                "enlighten_tick",
                "Lost Chapter",
                tick.amount,
            ),
        )
    return {
        "declaration": declaration.public(),
        "triggered": True,
        "reason": "level_up_restore_scheduled",
        "level_up_time": level_up_time,
        "maximum_mana_at_level_up": round(ledger.account.maximum, 6),
        "ticks_total": declaration.ticks,
        "ticks_within_window": within_window,
    }


def _resource_ledger_public(
    ledger: resource_ledger.ResourceLedger,
    manaflow: manaflow_ledger.ManaflowLedger | None,
    manaflow_hits: list[dict[str, Any]],
    enlighten_public: dict[str, Any] | None,
    *,
    auto_restore: dict[str, Any] | None = None,
    mark_refunds: dict[str, Any] | None = None,
    catalyst: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """JSON-safe public resource ledger section for a fight result.

    Additive P3 package-2/3A sub-sections (contract stays resource_ledger_v1):
    ``auto_restore`` (per-auto mana restore declaration + swing denials),
    ``mark_refunds`` (Essence Flux declaration + per-mark rows,
    applied/undetonated/basic-attack denials included), and ``catalyst``
    (Eternity declaration + the heal rows projected from the account's
    accepted spend receipts).
    """
    account = ledger.account
    section: dict[str, Any] = {
        "contract": "resource_ledger_v1",
        "owner": account.owner,
        "kind": account.kind,
        "opening_maximum": round(account.base_maximum, 6),
        "opening_current": round(account.base_maximum, 6),
        "closing_maximum": round(account.maximum, 6),
        "closing_current": round(account.current, 6),
        "base_maximum": round(account.base_maximum, 6),
        "bonus_maximum": round(account.bonus_maximum, 6),
        "receipts": [receipt.public() for receipt in ledger.receipts()],
    }
    if manaflow is not None:
        section["manaflow"] = {
            "declaration": manaflow.declaration.public(),
            "authored_bonus_mana": round(
                manaflow.bonus_total
                - sum(
                    float(hit.get("bonus_delta", 0.0) or 0.0) for hit in manaflow_hits
                ),
                6,
            ),
            "hits": manaflow_hits,
            "use_count": manaflow.use_count,
            "bonus_total": round(manaflow.bonus_total, 6),
            "stored_charges": manaflow.stored_charges,
        }
    if enlighten_public is not None:
        section["enlighten"] = enlighten_public
    if auto_restore is not None:
        section["auto_restore"] = auto_restore
    if mark_refunds is not None:
        section["mark_refunds"] = mark_refunds
    if catalyst is not None:
        section["catalyst"] = catalyst
    return section
