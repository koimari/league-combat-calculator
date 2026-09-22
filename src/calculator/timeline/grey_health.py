"""The grey pool: banked from the packets that landed, repaid by the active."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..cast_event_row import cast_slot as _row_cast_slot
from ..cast_event_row import cast_time as _row_cast_time
from ..champions.shared_option_keys import TAHM_KENCH_GREY_SHIELD
from ..champions.skill_orders import get_ability_rank
from ..champions.slot_extract import extract_named
from ..composed_event_row import row_damage, row_raw_damage, row_time
from ..healing import GREY_HEALTH_RULE_CHAMPIONS
from ..survival import SUPPORT_RANK_KEY, TransitionRank, action_key
from .grey_rates import (
    _LOCKE_W_AUTO_RECAST_SECONDS,
    _LOCKE_W_CONSUME_HEAL_RATIO,
    _LOCKE_W_STORE_RATIO,
    _LOCKE_W_STORE_WINDOW_SECONDS,
    _MORDE_W_RECAST_AVAILABLE_SECONDS,
    _MORDE_W_SHIELD_TO_HEALING_RANK,
    _MORDE_W_STORE_CAP_RATIO,
    _MORDE_W_STORE_DEALT_RATIO,
    _MORDE_W_STORE_TAKEN_PRE_RATIO,
    _PYKE_P_STORE_BONUS_AD_CAP_RATIO,
    _PYKE_P_STORE_FLAT_CAP,
    _PYKE_P_STORE_MAX_HEALTH_CAP_RATIO,
    _RENGAR_W_CONSUME_HEAL_RATIO,
    _RENGAR_W_STORE_RATIO,
    _RENGAR_W_STORE_WINDOW_SECONDS,
    _TAHM_E_OUT_OF_COMBAT_SECONDS,
    _TAHM_E_STORE_CAP_RATIO,
    _TAHM_E_STORE_MULTI_RANK,
    _TAHM_E_STORE_RANK,
    _declared_option,
    _grey_ability,
    _grey_cooldown,
    _grey_health_event_receipt,
    _grey_level_ratio,
    _press_thick_skin,
    _pyke_store_ratio,
)
from .records import GreySubject, Ledgers


# pylint: disable=too-many-arguments
# pylint: disable=too-many-locals,too-many-branches,too-many-statements
def _grey_health_receipts(
    champion_name: str,
    champion_data: Mapping[str, Any],
    level: int,
    stats: Mapping[str, float],
    *,
    incoming: list[tuple[float, float, float]],
    outgoing: Iterable[tuple[float, float, float]],
    cast_timeline: Iterable[Mapping[str, Any]],
    duration: float,
    enemy_count: int,
    ability_ranks: Mapping[str, int] | None = None,
    champion_options: Mapping[str, Any] | None = None,
) -> tuple[
    list[tuple[float, str, float]],
    list[tuple[float, str, float, float]],
    dict[str, float | str],
]:
    """Author the grey-health consumes for one grey-health main champion.

    ``incoming``/``outgoing`` are ``(time, post_mitigation,
    pre_mitigation)`` damage records for damage the main TAKES (its
    defenders' pair packets) and DEALS within the fight window.  Returns
    ``(consume_heals, consume_shields, summary)`` — a heal is ``(time,
    source, amount)``, a shield adds its duration — and the summary
    carries the ``grey_health_stored`` pool, the ``grey_health_consumed``
    total, and a ``source`` label for the receipt.  The pool accumulates
    the sourced ratio of post-mitigation incoming damage (Mordekaiser also
    stores from pre-mitigation damage taken and from post-mitigation
    damage dealt), capped per champion.  Only Tahm Kench's E active pays a
    pool as a shield, and only when its option is on.
    """
    name = str(champion_name)
    heals: list[tuple[float, str, float]] = []
    shields: list[tuple[float, str, float, float]] = []

    def _slot_rank(slot: str) -> int:
        if ability_ranks and slot in ability_ranks:
            return max(0, int(ability_ranks[slot] or 0))
        return max(0, int(get_ability_rank(slot, level, name)))

    if name == "Pyke":
        ratio = _pyke_store_ratio(stats, enemy_count)
        max_health = max(0.0, float(stats.get("health", 0.0) or 0.0))
        bonus_ad = max(0.0, float(stats.get("bonus_attack_damage", 0.0) or 0.0))
        cap = min(
            _PYKE_P_STORE_FLAT_CAP + _PYKE_P_STORE_BONUS_AD_CAP_RATIO * bonus_ad,
            _PYKE_P_STORE_MAX_HEALTH_CAP_RATIO * max_health,
        )
        pool = min(cap, ratio * sum(post for _t, post, _pre in incoming))
        # Out-of-vision consume: vision is a boundary the 1v1 ledger does
        # not model, so the 100% heal is documented, not authored.
        return (
            heals,
            shields,
            {
                "grey_health_stored": pool,
                "grey_health_consumed": 0.0,
                "source": (
                    "Gift of the Drowned Ones (9% + 0.2% per Lethality of "
                    "post-mitigation damage taken; out-of-vision consume is a "
                    "vision boundary, not modeled in-window)"
                ),
            },
        )
    if name == "Rengar":
        w_casts = sorted(
            float(_row_cast_time(cast))
            for cast in cast_timeline
            if str(_row_cast_slot(cast)) == "W"
        )
        consumed = 0.0
        for cast_time in w_casts:
            window = sum(
                post
                for event_time, post, _pre in incoming
                if cast_time - _RENGAR_W_STORE_WINDOW_SECONDS <= event_time <= cast_time
            )
            amount = _RENGAR_W_STORE_RATIO * _RENGAR_W_CONSUME_HEAL_RATIO * window
            if amount > 0.0 and cast_time <= duration:
                heals.append((cast_time, "Battle Roar (grey health)", amount))
                consumed += amount
        stored = _RENGAR_W_STORE_RATIO * sum(post for _t, post, _pre in incoming)
        return (
            heals,
            shields,
            {
                "grey_health_stored": stored,
                "grey_health_consumed": consumed,
                "source": (
                    "Battle Roar (50% of post-mitigation damage taken in the "
                    "last 1.5 seconds stored as grey health; the active heals "
                    "the stored pool)"
                ),
            },
        )
    if name == "Tahm Kench":
        e_rank = max(1, _slot_rank("E"))
        rank_row = _TAHM_E_STORE_MULTI_RANK if enemy_count >= 2 else _TAHM_E_STORE_RANK
        ratio = rank_row[min(e_rank, len(rank_row)) - 1]
        max_health = max(0.0, float(stats.get("health", 0.0) or 0.0))
        ability = _grey_ability(champion_data, "E")
        pool = min(
            _TAHM_E_STORE_CAP_RATIO * max_health,
            ratio * sum(post for _t, post, _pre in incoming),
        )
        consumed = 0.0
        # The E ACTIVE, when the module's option turns it on: each press
        # converts the grey banked since the previous one into a 2.5 s
        # shield, on E's own haste-scaled cooldown.
        residual, last_press = pool, None
        cooldown = _grey_cooldown(ability, e_rank, stats)
        if _declared_option(name, champion_options, TAHM_KENCH_GREY_SHIELD):
            banked, press_time = 0.0, None
            for event_time, post, _pre in sorted(incoming):
                if press_time is not None and event_time >= press_time:
                    banked = _press_thick_skin(shields, press_time, banked, duration)
                    last_press, press_time = press_time, press_time + cooldown
                banked = min(
                    _TAHM_E_STORE_CAP_RATIO * max_health, banked + ratio * post
                )
                if press_time is None:
                    press_time = event_time
            if press_time is not None:
                banked = _press_thick_skin(shields, press_time, banked, duration)
                last_press = press_time
            residual = banked
            consumed = pool - residual
        if residual > 0.0 and incoming:
            last_damage_time = max(event_time for event_time, _post, _pre in incoming)
            consume_time = last_damage_time + _TAHM_E_OUT_OF_COMBAT_SECONDS
            # "While Thick Skin is not on cooldown, and after 4 seconds
            # without taking damage": a press inside the window blocks the
            # heal until its own cooldown has run out.
            ready = last_press is None or last_press + cooldown <= consume_time
            if consume_time <= duration and ready:
                restore = _grey_level_ratio(ability, "Max Health Damage", level)
                amount = restore * residual
                if amount > 0.0:
                    heals.append((consume_time, "Thick Skin (grey health)", amount))
                    consumed += amount
        return (
            heals,
            shields,
            {
                "grey_health_stored": pool,
                "grey_health_consumed": consumed,
                "source": (
                    "Thick Skin (E-rank % of post-mitigation damage taken "
                    "stored as grey health; the out-of-combat consume restores "
                    "60% : 100% based on level of the pool after 4 seconds "
                    "without damage, and the active converts the pool into a "
                    "2.5s shield when its option is on)"
                ),
            },
        )
    if name == "Mordekaiser":
        w_rank = max(1, _slot_rank("W"))
        heal_ratio = _MORDE_W_SHIELD_TO_HEALING_RANK[
            min(w_rank, len(_MORDE_W_SHIELD_TO_HEALING_RANK)) - 1
        ]
        max_health = max(0.0, float(stats.get("health", 0.0) or 0.0))
        cap = _MORDE_W_STORE_CAP_RATIO * max_health
        dealt_total = _MORDE_W_STORE_DEALT_RATIO * sum(
            post for _t, post, _pre in outgoing
        )
        taken_total = _MORDE_W_STORE_TAKEN_PRE_RATIO * sum(
            pre for _t, _post, pre in incoming
        )
        pool = min(cap, dealt_total + taken_total)
        w_casts = sorted(
            float(_row_cast_time(cast))
            for cast in cast_timeline
            if str(_row_cast_slot(cast)) == "W"
        )
        consumed = 0.0
        if w_casts:
            w1_time = w_casts[0]
            dealt_up_to = _MORDE_W_STORE_DEALT_RATIO * sum(
                post for event_time, post, _pre in outgoing if event_time <= w1_time
            )
            taken_up_to = _MORDE_W_STORE_TAKEN_PRE_RATIO * sum(
                pre for event_time, _post, pre in incoming if event_time <= w1_time
            )
            shield_amount = min(cap, dealt_up_to + taken_up_to)
            recast_time = w1_time + _MORDE_W_RECAST_AVAILABLE_SECONDS
            amount = heal_ratio * shield_amount
            if amount > 0.0 and recast_time <= duration:
                heals.append((recast_time, "Indestructible (grey health)", amount))
                consumed = amount
        return (
            heals,
            shields,
            {
                "grey_health_stored": pool,
                "grey_health_consumed": consumed,
                "source": (
                    "Indestructible (45% of post-mitigation damage dealt + "
                    "7.5% of pre-mitigation damage taken stored as Potential "
                    "Shield, capped at 30% of maximum health; the W recast "
                    "heals the Shield-to-Healing % of the stored shield — the "
                    "recast is modeled at its earliest available time, shield "
                    "decay is state)"
                ),
            },
        )
    if name == "Locke":
        # Soul Ignition (W): each W cast opens a 6-second storage window
        # during which 100% of the post-mitigation champion damage taken
        # accumulates as grey health, capped by the rank row; the
        # automatic recast at the 6 s boundary consumes the pool to heal
        # for the same amount (cached W prose, leveling row "Damage taken
        # grey health cap").  The health-cost and missing-health bonus
        # terms remain documented boundaries (dynamic self-state, per the
        # E1-b6 scope note).
        w_rank = max(1, _slot_rank("W"))
        cap = extract_named(
            _grey_ability(champion_data, "W"),
            "Damage taken grey health cap",
            w_rank,
            stats,
            {},
        )
        w_casts = sorted(
            float(_row_cast_time(cast))
            for cast in cast_timeline
            if str(_row_cast_slot(cast)) == "W"
        )
        consumed = 0.0
        for cast_time in w_casts:
            window_start = cast_time
            window_end = cast_time + _LOCKE_W_STORE_WINDOW_SECONDS
            stored = min(
                cap,
                _LOCKE_W_STORE_RATIO
                * sum(
                    post
                    for event_time, post, _pre in incoming
                    if window_start <= event_time <= window_end
                ),
            )
            consume_time = cast_time + _LOCKE_W_AUTO_RECAST_SECONDS
            amount = _LOCKE_W_CONSUME_HEAL_RATIO * stored
            if amount > 0.0 and consume_time <= duration:
                heals.append((consume_time, "Soul Ignition (grey health)", amount))
                consumed += amount
        return (
            heals,
            shields,
            {
                "grey_health_stored": min(
                    cap,
                    _LOCKE_W_STORE_RATIO * sum(post for _t, post, _pre in incoming),
                ),
                "grey_health_consumed": consumed,
                "source": (
                    "Soul Ignition (100% of post-mitigation damage taken from "
                    "enemy champions during the 6s active stored as grey "
                    "health, capped by the 'Damage taken grey health cap' row; "
                    "the automatic recast at 6s heals the stored pool; the "
                    "health-cost add and missing-health bonus remain dynamic "
                    "self-state boundaries)"
                ),
            },
        )
    if name == "Kled":
        # Skaarl's 400 : 1400 (based on level) health pool is the mounted
        # duo's damage sink; dismount at zero and the remount restore are a
        # revive-boundary pattern (like Aatrox's ghost atom) and are NOT
        # implemented.  No heal is authored; the module documents it.
        return (
            heals,
            shields,
            {
                "grey_health_stored": 0.0,
                "grey_health_consumed": 0.0,
                "source": (
                    "Skaarl the Cowardly Lizard (the mounted duo's damage pool "
                    "is a revive-boundary pattern; dismount/remount are not "
                    "modeled)"
                ),
            },
        )
    return (
        heals,
        shields,
        {
            "grey_health_stored": 0.0,
            "grey_health_consumed": 0.0,
            "source": "",
        },
    )


def _grey_damage_record(event: Mapping[str, Any]) -> tuple[float, float, float]:
    """One ``(time, post_mitigation, pre_mitigation)`` record; a packet priced
    with no pre-mitigation figure banks the post-mitigation one for both."""
    damage = row_damage(event)
    raw = row_raw_damage(event)
    return (row_time(event), damage, damage if raw is None else raw)


def _apply_grey_health(
    subject: GreySubject, ledgers: Ledgers
) -> dict[str, float | str]:
    """Bank and repay the main champion's grey health, and stamp its receipts.

    When the main is the defender and is a grey-health champion, the
    incoming ledger accumulates the sourced % of post-mitigation damage
    taken and the champion's active pays the stored pool back as a heal.
    Authored after every incoming source (pair fights, thorns, reactive)
    exists so the receipts see the same event set the walk applies; the
    consume heals carry fixed sourced amounts and ride the ordinary heal
    application (Grievous, overheal caps).
    """
    main_name = subject.name
    if main_name not in GREY_HEALTH_RULE_CHAMPIONS or not subject.enemy_count:
        return {}
    params = subject.params
    duration = params.fight_duration_seconds
    main_incoming = [
        event for event in ledgers.incoming["main"] if row_time(event) <= duration
    ]
    main_outgoing = [
        event for event in ledgers.outgoing["main"] if row_time(event) <= duration
    ]
    grey_heals, grey_shields, grey_summary = _grey_health_receipts(
        main_name,
        subject.champion_data,
        subject.level,
        subject.stats,
        incoming=[_grey_damage_record(event) for event in main_incoming],
        outgoing=[_grey_damage_record(event) for event in main_outgoing],
        cast_timeline=ledgers.main_cast_timeline,
        duration=duration,
        enemy_count=subject.enemy_count,
        ability_ranks=params.ability_ranks,
        champion_options=params.champion_options,
    )
    for index, (heal_time, source, amount) in enumerate(grey_heals):
        heal_event: dict[str, Any] = {
            "time": float(heal_time),
            "amount": float(amount),
            "source": source,
            "kind": "champion_ability",
            "attacker": "main",
            "_event_id": f"main:grey:{source}:{index}",
            "_grey_health": True,
        }
        heal_event["_sk"] = action_key(
            float(heal_time),
            TransitionRank.RECOVERY,
            "main",
            heal_event,
        )
        ledgers.healing["main"].append(heal_event)
    ledgers.support_effects["main"].extend(
        {
            "time": float(grant_time),
            "kind": "shield",
            "amount": float(amount),
            "duration": float(window),
            "source": source,
            "source_key": source,
            "attacker": "main",
            "target": "main",
            "target_scope": "self",
            "target_policy": "self",
            "_event_id": f"main:grey:{source}:shield:{index}",
            # Grey health is banked by damage already taken, so the
            # barrier this press raises arms after it.
            SUPPORT_RANK_KEY: TransitionRank.LATE_BARRIER,
        }
        for index, (grant_time, source, amount, window) in enumerate(grey_shields)
    )
    for taken, events in ((True, main_incoming), (False, main_outgoing)):
        for event in events:
            receipt = _grey_health_event_receipt(
                main_name,
                subject.level,
                subject.stats,
                subject.enemy_count,
                event,
                incoming=taken,
                ability_ranks=params.ability_ranks,
            )
            if receipt is not None and receipt > 0.0:
                event["grey_health_stored"] = round(receipt, 6)
    return grey_summary
