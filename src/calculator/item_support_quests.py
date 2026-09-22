"""The economy, vision, resource and movement receipts a fight opens with."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from .ally_packet_shape import _option, _packet
from .interpreters.ally_packet import AllyPacketSlot
from .item_behavior import AllyProducer, PacketKind
from .item_effects import (
    ITEM_INPUT_OPTIONS,
    manaflow_declaration,
    required_effect_value,
)
from .support_context import SupportCtx
from .survival.phases import TransitionRank


def _support_quest_packets(
    attacker: Any, shared_riches: AllyPacketSlot, ward: AllyPacketSlot
) -> list[dict[str, Any]]:
    """One support-quest item's authored economy and vision outcomes.

    World Atlas and Runic Compass carry the same quest, and the two outcomes
    — the gold and the ward — are two declared producers on the one record,
    because each has its own capability and packet source.  The
    item is whichever transformed stage the build equipped, read off the
    declarations rather than spelled: ``validate_resolved_loadout`` already
    refuses a build carrying two support quest items, and ``_producer``'s
    two-holder stop is that same rule restated where the packets are built.
    """
    packets: list[dict[str, Any]] = []
    quest_item = shared_riches.owner
    source_meta = ITEM_INPUT_OPTIONS[quest_item]
    gold = max(0.0, _option(attacker, quest_item, "shared_riches_gold"))
    gold_cap = shared_riches.value("support_quest_threshold")
    if gold > 0.0:
        packets.append(
            _packet(
                attacker=attacker,
                target=attacker,
                time=0.0,
                kind=PacketKind.ECONOMY.value,
                source=f"{quest_item} — Shared Riches",
                amount=min(gold, gold_cap),
                target_scope="self",
                gold_amount=min(gold, gold_cap),
                quest_threshold=gold_cap,
                quest_complete=gold >= gold_cap,
                shared_riches_interval=required_effect_value(
                    quest_item, "shared_riches_interval"
                ),
                shared_riches_gold_minion=required_effect_value(
                    quest_item, "shared_riches_gold_minion"
                ),
                shared_riches_gold_melee=required_effect_value(
                    quest_item, "shared_riches_gold_melee"
                ),
                shared_riches_gold_ranged=required_effect_value(
                    quest_item, "shared_riches_gold_ranged"
                ),
                source_url=source_meta["source_url"],
                source_revision_id=source_meta["source_revision_id"],
            )
        )
    ward_uses = max(
        0.0,
        min(_option(attacker, quest_item, "ward_uses"), ward.value("ward_charges")),
    )
    if ward_uses > 0.0:
        packets.append(
            _packet(
                attacker=attacker,
                target=attacker,
                time=0.0,
                kind=PacketKind.VISION.value,
                source=f"{quest_item} — Ward",
                amount=ward_uses,
                target_scope="self",
                ward_uses=ward_uses,
                ward_charges=ward.value("ward_charges"),
                quest_threshold=gold_cap,
                source_url=source_meta["source_url"],
                source_revision_id=source_meta["source_revision_id"],
            )
        )
    return packets


def _reap_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """Cull's authored minion kills, as one inspectable gold receipt.

    A progression and economy branch, not a guessed combat bonus: the kill
    count is bounded by its sourced 100-kill quest and produces a receipt
    only once the caller supplies the count.
    """
    reap = ctx.producer(AllyProducer.REAP)
    if reap is None:
        return []
    attacker = ctx.attacker
    packets: list[dict[str, Any]] = []
    reap.declared(PacketKind.ECONOMY)
    minion_kills = max(0.0, _option(attacker, reap.owner, "reap_minion_kills"))
    cap = reap.value("reap_max_gold")
    per_minion = reap.value("reap_gold_per_minion")
    completion_gold = reap.value("reap_completion_gold")
    earned = min(minion_kills, cap) * per_minion
    if minion_kills >= cap:
        earned += completion_gold
    if earned > 0.0:
        source_meta = ITEM_INPUT_OPTIONS[reap.owner]
        packets.append(
            _packet(
                attacker=attacker,
                target=attacker,
                time=0.0,
                kind=PacketKind.ECONOMY.value,
                source="Cull — Reap",
                amount=earned,
                target_scope="self",
                gold_amount=earned,
                minion_kills=min(minion_kills, cap),
                completion_granted=minion_kills >= cap,
                source_url=source_meta["source_url"],
                source_revision_id=source_meta["source_revision_id"],
            )
        )
    return packets


def _rage_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """Phage's move speed, one timestamped packet per qualifying basic attack.

    Emitted from the same authored auto stream the damage ledger reads, so
    no movement state is invented when that stream is absent or coarse.
    """
    rage = ctx.producer(AllyProducer.RAGE)
    if rage is None:
        return []
    attacker = ctx.attacker
    damage_events = ctx.damage_events
    packets: list[dict[str, Any]] = []
    rage.declared(PacketKind.MOVEMENT)
    is_melee = bool(attacker.stats.get("is_melee", False))
    speed_key = (
        "rage_bonus_move_speed_melee" if is_melee else "rage_bonus_move_speed_ranged"
    )
    bonus_speed = rage.value(speed_key)
    duration = rage.value("rage_duration")
    source_meta = ITEM_INPUT_OPTIONS[rage.owner]
    for event in damage_events:
        if event.source_key != "auto_attacks" and not event.basic_attack:
            continue
        packets.append(
            _packet(
                attacker=attacker,
                target=attacker,
                time=event.time,
                kind=PacketKind.MOVEMENT.value,
                source="Phage — Rage",
                amount=bonus_speed,
                duration=duration,
                target_scope="self",
                bonus_move_speed_percent=bonus_speed,
                trigger="authored_basic_attack",
                source_url=source_meta["source_url"],
                source_revision_id=source_meta["source_revision_id"],
            )
        )
    return packets


def _quest_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """The support quest's economy and vision outcomes.

    The role-quest contract decides which transformed item is equipped;
    this layer records only the authored progress and ward state for it.
    """
    shared_riches = ctx.producer(AllyProducer.SHARED_RICHES)
    ward = ctx.producer(AllyProducer.WARD)
    if shared_riches is None or ward is None:
        return []
    shared_riches.declared(PacketKind.ECONOMY)
    ward.declared(PacketKind.VISION)
    return _support_quest_packets(ctx.attacker, shared_riches, ward)


def _manaflow_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """The typed mana ledger's accepted hits, in the public resource schema.

    The fight engine admits casts through ``resource_ledger``, records every
    PROVEN accepted eligible hit (a denied cast can never trigger Manaflow,
    and a missing hit identity fails closed), and applies each granted bonus
    max-mana to the same account.  This layer only shapes those receipts; it
    never recomputes cadence, charges or caps.  A fight result without a
    ledger section has no Manaflow activity by construction, and that section
    IS the guard: it names its own holder, so the block asks the typed ledger
    which item ran instead of asking the build for a name.
    """
    attacker = ctx.attacker
    result = ctx.result
    packets: list[dict[str, Any]] = []
    ledger_section = result.get("resource_ledger")
    manaflow = (
        ledger_section.get("manaflow") if isinstance(ledger_section, Mapping) else None
    )
    if isinstance(manaflow, Mapping):
        declaration = manaflow.get("declaration")
        if not isinstance(declaration, Mapping):
            raise ValueError(
                "a Manaflow ledger section carries no declaration, so its "
                "holder cannot be named"
            )
        holder = str(declaration["item"])
        sourced = manaflow_declaration(holder)
        interval = sourced["charge_interval"]
        max_charges = max(1, sourced["max_charges"])
        per_trigger = sourced["bonus_mana_per_trigger"]
        per_champion = sourced["bonus_mana_per_champion"]
        mana_cap = sourced["bonus_mana_max"]
        authored_mana = max(0.0, _option(attacker, holder, "manaflow_bonus_mana"))
        for hit in (
            manaflow.get("hits", ())
            if isinstance(manaflow.get("hits"), Iterable)
            else ()
        ):
            if not isinstance(hit, Mapping):
                continue
            if not hit.get("accepted"):
                # Denial receipts (missing identity, no charge, cap)
                # are public ledger rows, not support packets.
                continue
            try:
                hit_time = float(hit.get("time", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(hit_time) or hit_time < 0.0:
                continue
            try:
                grant = float(hit.get("bonus_delta", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if grant <= 0.0:
                continue
            try:
                use_count = max(1, int(hit.get("use_count", 1) or 1))
            except (TypeError, ValueError):
                use_count = 1
            # The packet's public bonus_mana_total keeps the historic
            # in-fight accrual semantics (authored progress is a separate
            # field), while the ledger receipt tracks the full total.
            authored_capped = min(authored_mana, mana_cap)
            try:
                ledger_total = float(hit.get("bonus_total", grant) or grant)
            except (TypeError, ValueError):
                ledger_total = grant
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=hit_time,
                    kind=PacketKind.RESOURCE.value,
                    source=f"{holder} — Manaflow",
                    amount=grant,
                    target_scope="self",
                    bonus_mana_total=max(0.0, ledger_total - authored_capped),
                    bonus_mana_cap=float(hit.get("cap", mana_cap) or mana_cap),
                    authored_bonus_mana=authored_capped,
                    manaflow_charge_interval=interval,
                    manaflow_max_charges=max_charges,
                    manaflow_bonus_mana_per_trigger=per_trigger,
                    manaflow_bonus_mana_per_champion=per_champion,
                    trigger_kind=f"{hit.get('trigger')}_vs_{hit.get('target_kind')}",
                    charge_accrued_at=(use_count - 1) * interval,
                    rank=TransitionRank.BARRIER_GRANT,
                    source_url=sourced["source_url"],
                    source_revision_id=sourced["source_revision_id"],
                )
            )
    return packets


def _nightstalker_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """Umbral Glaive's Blackout, the ward-denial vision state.

    The sourced one-second unseen gate arms Nightstalker, whose sourced true
    damage rides the typed first-auto packet in the damage ledger.  Blackout
    itself has no champion-facing target in the fighter model, so this layer
    emits one vision-dimension receipt when the authored ready gate is set;
    it never guesses ward hits or converts the denial into damage.
    """
    nightstalker = ctx.producer(AllyProducer.NIGHTSTALKER)
    attacker = ctx.attacker
    if (
        nightstalker is None
        or _option(attacker, nightstalker.owner, "nightstalker_ready") <= 0.0
    ):
        return []
    packets: list[dict[str, Any]] = []
    nightstalker.declared(PacketKind.VISION)
    source_meta = ITEM_INPUT_OPTIONS[nightstalker.owner]
    lethality = max(0.0, float(attacker.stats.get("lethality", 0.0) or 0.0))
    packets.append(
        _packet(
            attacker=attacker,
            target=attacker,
            time=0.0,
            kind=PacketKind.VISION.value,
            source="Umbral Glaive — Blackout",
            amount=1.0,
            target_scope="self",
            ward_uses=0.0,
            nightstalker_ready=True,
            blackout_trigger_windows=1,
            unseen_gate_seconds=nightstalker.value("nightstalker_unseen_seconds"),
            trigger_window_seconds=nightstalker.value("nightstalker_trigger_window"),
            blackout_duration=nightstalker.value("blackout_duration"),
            ward_only=True,
            ward_hits_modeled=0,
            # The true damage the gate arms is the first-auto packet's
            # number, which no ally-packet declaration carries, so it is
            # read through the typed accessor that ledger reads.
            true_damage_on_ward_hit=(
                required_effect_value(nightstalker.owner, "base")
                + required_effect_value(nightstalker.owner, "lethality_ratio")
                * lethality
            ),
            source_url=source_meta["source_url"],
            source_revision_id=source_meta["source_revision_id"],
        )
    )
    return packets
