"""Typed, timestamped ally/team item packets for the participant ledger.

The ordinary item compiler owns damage emitted by the holder.  This module
owns the other side of the same Wiki entries: ally shields/heals, temporary
health, stat buffs, all-source debuffs, and explicit item-actives.  It never
assumes an active or a trigger that is absent from the authored event stream.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import math
from typing import Any

from .state_lifecycle import (
    CcTriggerRule,
    CooldownRule,
    CooldownState,
    InstanceCadence,
    SourceReceipt,
)

from .capabilities import SUPPORT_TARGET_SCOPES
from .item_effects import (
    ALLY_ITEM_EFFECTS,
    ITEM_INPUT_OPTIONS,
    ally_item_effect_value,
    ally_item_level_value,
    fimbulwinter_mana_gate_authority,
    fimbulwinter_nearby_enemy_range_authority,
    required_effect_value,
)

_MISSING = object()


def _same_side(attacker: Any, actor: Any) -> bool:
    left = "main" if attacker.team in {"main", "ally"} else attacker.team
    right = "main" if actor.team in {"main", "ally"} else actor.team
    return left == right


def _teammates(attacker: Any, all_actors: Iterable[Any]) -> list[Any]:
    attacker_id = getattr(attacker, "participant_id", None)
    return [
        actor
        for actor in all_actors
        if getattr(actor, "participant_id", None) != attacker_id
        and _same_side(attacker, actor)
    ]


def _item_names(attacker: Any) -> set[str]:
    return {str(item.get("name", "")) for item in attacker.items}


def _option(attacker: Any, item_name: str, key: str, default: float = 0.0) -> float:
    request = getattr(attacker, "request", None)
    item_options = getattr(request, "item_options", {}) or {}
    options = item_options.get(item_name, {})
    value = options.get(key, default) if isinstance(options, Mapping) else default
    if isinstance(value, bool):
        raise ValueError(f"{item_name}.{key} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{item_name}.{key} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{item_name}.{key} must be finite")
    return parsed


def _active_seconds(attacker: Any, item_name: str) -> float:
    """One validated active-seconds read for an ally-support item.

    Delegates to the typed ``input_option_float_value`` accessor so the
    emission layer re-checks the schema bounds AND step multiple (P3
    package 3F/3G): a direct timeline caller cannot author an out-of-domain
    activation (e.g. 31.0 or 0.3) even though the request layer already
    validates.  Missing/absent input reads 0.0 (no cast).
    """
    from .item_effects import input_option_float_value

    request = getattr(attacker, "request", None)
    item_options = getattr(request, "item_options", None) or {}
    return input_option_float_value(
        list(attacker.items), item_options, item_name, "active_seconds"
    )


def _event_time(event: Mapping[str, Any]) -> float:
    value = event.get("time", 0.0)
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("item support event time must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError("item support event time must be finite")
    return parsed


def _packet(
    *,
    attacker: Any,
    target: Any,
    time: float,
    kind: str,
    source: str,
    amount: float = 0.0,
    duration: float = 0.0,
    target_scope: str = "one_teammate",
    **fields: Any,
) -> dict[str, Any]:
    if not math.isfinite(float(amount)) or float(amount) < 0.0:
        raise ValueError(f"{source} packet amount must be finite and non-negative")
    if not math.isfinite(float(duration)) or float(duration) < 0.0:
        raise ValueError(f"{source} packet duration must be finite and non-negative")
    if target_scope not in SUPPORT_TARGET_SCOPES:
        raise ValueError(
            f"{source} packet target_scope {target_scope!r} is outside the "
            f"closed support scope vocabulary: {sorted(SUPPORT_TARGET_SCOPES)}"
        )
    attacker_id = getattr(attacker, "participant_id", None)
    target_id = getattr(target, "participant_id", None)
    if kind != "item_denial" and (
        not isinstance(attacker_id, str)
        or not attacker_id.strip()
        or not isinstance(target_id, str)
        or not target_id.strip()
    ):
        raise ValueError(f"{source} applied packet requires participant identity")
    return {
        "time": float(time),
        "kind": kind,
        "amount": float(amount),
        "duration": float(duration),
        "source": source,
        "source_key": source,
        "attacker": attacker_id,
        "target": target_id,
        "target_scope": target_scope,
        "target_policy": "explicit_selected_roster_target",
        "target_selection_key": fields.get("target_selection_key", f"{kind}:{source}"),
        "_item_support": True,
        **fields,
    }


def _support_triggers(
    trigger_effects: Iterable[Mapping[str, Any]], attacker: Any
) -> list[Mapping[str, Any]]:
    """Return ally heal/shield packets that can trigger item passives."""
    return [
        event
        for event in trigger_effects
        if str(event.get("kind", "")) in {"heal", "shield"}
        and str(event.get("target", "")) != attacker.participant_id
    ]


# Everlasting's crowd-control trigger predicate is kernel-owned
# (state_lifecycle.CcTriggerRule): immobilize from the sourced
# action-blocking vocabulary, or slow for a melee holder.  A bare
# ``crowd_control`` flag does not distinguish the branches and stays
# insufficient, exactly as the reviewed item coverage decided.
_FIMBULWINTER_TRIGGER_RULE = CcTriggerRule(
    name="Fimbulwinter — Everlasting crowd-control trigger",
    slow_melee_only=True,
    source=SourceReceipt.from_mapping(ITEM_INPUT_OPTIONS["Fimbulwinter"]),
)


def _cc_event_stream(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The deduplicated damage + control-only event stream.

    Damage-attached control rides ``damage_events``; control-ONLY packets
    (Darius E, Elise E, ...) ride ``control_events``.  The coupled pair
    enrichment merges control-only rows INTO the per-event view, so a
    ``(time, source_key, cc_kind)`` dedupe keeps exactly one copy of every
    packet and never double-fires the same control packet.
    """
    seen: set[tuple[float, str, str]] = set()
    out: list[Mapping[str, Any]] = []
    for stream in (
        result.get("damage_events", ()),
        result.get("control_events", ()),
    ):
        for event in stream:
            if not isinstance(event, Mapping):
                continue
            try:
                event_time = float(event.get("time", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            key = (
                round(event_time, 9),
                str(event.get("source_key", "")),
                str(event.get("cc_kind", "") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(event)
    return out


def _cc_triggers(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return CC packets that can carry an authored CC trigger."""
    return [
        event
        for event in _cc_event_stream(result)
        if _FIMBULWINTER_TRIGGER_RULE.is_candidate(event)
    ]


def _mana_input(
    raw: object,
    *,
    missing_reason: str,
    invalid_reason: str,
) -> tuple[float | None, str | None]:
    """Validate one explicit mana value without inventing a fallback."""
    if raw is _MISSING:
        return None, missing_reason
    if raw is None or isinstance(raw, bool):
        return None, invalid_reason
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None, invalid_reason
    if not math.isfinite(value) or value < 0.0:
        return None, invalid_reason
    return value, None


def _current_mana_at(
    result: Mapping[str, Any], event_time: float, initial_current_mana: object
) -> tuple[float | None, str | None]:
    """Resolve current mana from explicit state and ordered cast receipts."""
    current, initial_reason = _mana_input(
        initial_current_mana,
        missing_reason="missing_current_mana",
        invalid_reason="invalid_current_mana",
    )
    casts = result.get("cast_timeline", ())
    if not isinstance(casts, Iterable):
        return current, initial_reason
    ordered = []
    for cast in casts:
        if not isinstance(cast, Mapping):
            continue
        try:
            cast_time = float(cast.get("time", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(cast_time) or cast_time > event_time + 1e-9:
            continue
        ordered.append((cast_time, cast))
    for _, cast in sorted(ordered, key=lambda row: row[0]):
        if "resource_after" not in cast:
            continue
        parsed, reason = _mana_input(
            cast["resource_after"],
            missing_reason="missing_current_mana",
            invalid_reason="invalid_current_mana",
        )
        if reason is not None:
            return None, reason
        current = parsed
        initial_reason = None
    return current, initial_reason


def _takedown_triggers(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return only explicit takedown receipts; never infer a kill from damage."""
    return [
        event
        for event in result.get("takedown_events", [])
        if isinstance(event, Mapping)
        and event.get("time") is not None
        and str(event.get("target", ""))
    ]


def _damage_triggers(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return authored non-reactive champion damage packets for item stacks."""
    return [
        event
        for event in result.get("damage_events", [])
        if isinstance(event, Mapping)
        and float(event.get("damage", 0.0) or 0.0) > 0.0
        and not event.get("_reactive")
        and str(event.get("target", ""))
    ]


def _target_by_id(all_actors: Iterable[Any], participant_id: str) -> Any | None:
    return next(
        (actor for actor in all_actors if actor.participant_id == participant_id), None
    )


def _selected_teammate(attacker: Any, teammates: list[Any]) -> Any | None:
    if not teammates:
        return None
    raw_index = _option(attacker, "Knight's Vow", "worthy_target_index", -1.0)
    if float(raw_index) < 0.0:
        # Pledge is unit-targeted: a MISSING authored index means no
        # designation — fail closed instead of inventing the first
        # teammate as Worthy (P3 package 3S).
        return None
    index = max(0, min(len(teammates) - 1, int(raw_index)))
    return teammates[index]


def resolve_knights_vow_tether(
    holder: Any, all_actors: Iterable[Any]
) -> dict[str, Any] | None:
    """Resolve one Knight's Vow holder's Worthy tether.

    Returns the authored target, the option gates, and the typed Sacrifice
    values, or ``None`` when the holder carries no Knight's Vow, has no
    eligible teammate, or the authored Worthy index is the no-selection
    sentinel (P3 package 3S).  Both the receipt scheduler and the compiled
    score staging consume this single resolution so the walks cannot
    disagree about the tether.
    """
    if "Knight's Vow" not in _item_names(holder):
        return None
    teammates = _teammates(holder, list(all_actors))
    target = _selected_teammate(holder, teammates)
    if target is None:
        return None
    return {
        "holder": holder,
        "target": target,
        "redirect_fraction": ally_item_effect_value(
            "Knight's Vow", "redirect_fraction"
        ),
        "heal_fraction": ally_item_effect_value("Knight's Vow", "holder_heal_fraction"),
        "within_range": _option(holder, "Knight's Vow", "worthy_within_range", 1.0),
        "holder_health_ready": _option(
            holder, "Knight's Vow", "holder_above_30_percent", 1.0
        ),
        "range_units": ally_item_effect_value("Knight's Vow", "worthy_range_units"),
        "threshold": ally_item_effect_value(
            "Knight's Vow", "holder_health_threshold_ratio"
        ),
        "source_revision_id": int(
            ally_item_effect_value("Knight's Vow", "source_revision_id")
        ),
    }


# Items whose cross-participant packets are derived by scanning the
# holder's damage/takedown event stream below (Phage's Rage autos, Black
# Cleaver Carve stacks, Bloodletter's Curse, Bloodsong's Expose Weakness,
# Cryptbloom's takedown nova).  The optimizer's score-only tuple ledger
# carries positional rows the scan cannot read, so the pipeline's tuple
# predicate consults this set and keeps dict rows for these holders
# (issue #169).  Every new branch below that reads ``damage_events`` or
# ``takedown_events`` must add its item here, or a score-only fight will
# silently starve its scan.
EVENT_SCAN_SUPPORT_ITEMS = frozenset(
    {
        "Black Cleaver",
        "Bloodletter's Curse",
        "Bloodsong",
        "Cryptbloom",
        "Phage",
        # CC-trigger holders (Fimbulwinter Everlasting, Bandlepipes,
        # Solstice Sleigh, Imperial Mandate) scan the CC-adjacent event
        # stream; a score-only tuple-ledger fight must keep dict rows or
        # the scan silently starves (P3 package 3B hardening).
        "Fimbulwinter",
        "Bandlepipes",
        "Solstice Sleigh",
        "Imperial Mandate",
        # Knight's Vow's Sacrifice staging reads the per-event redirect
        # view (P3 package 3S): a score-only tuple-ledger fight must keep
        # dict rows or the compiled staging silently starves.
        "Knight's Vow",
    }
)


def has_event_scan_support_items(items: Iterable[Mapping[str, Any]]) -> bool:
    """Whether any held item derives support packets from the event stream."""
    return any(str(item.get("name", "")) in EVENT_SCAN_SUPPORT_ITEMS for item in items)


# The subset whose trigger is the takedown stream: the receipt composition
# synthesizes ``takedown_events`` from the pair fight's one-pair shield
# outcome (``target_ending_health``), so a score-only fight for these
# holders must keep that outcome instead of skipping it (issue #169).
TAKEDOWN_SCAN_SUPPORT_ITEMS = frozenset({"Cryptbloom"})


def has_takedown_scan_support_items(items: Iterable[Mapping[str, Any]]) -> bool:
    """Whether any held item derives support packets from takedowns."""
    return any(
        str(item.get("name", "")) in TAKEDOWN_SCAN_SUPPORT_ITEMS for item in items
    )


# The holders that consume each pre-scanned trigger stream below.  The
# streams are built lazily from these sets: every consumer branch in
# ``derive_item_support_effects`` is gated on its item name, so a holder
# with none of a stream's items can skip that scan entirely.  A new branch
# that reads ``cc_events``/``damage_events`` must add its item here, or
# its stream will arrive empty.
CC_TRIGGER_ITEMS = frozenset(
    {"Fimbulwinter", "Bandlepipes", "Solstice Sleigh", "Imperial Mandate"}
)
DAMAGE_TRIGGER_ITEMS = frozenset({"Bloodsong", "Black Cleaver", "Bloodletter's Curse"})

# Every holder whose scan reads the per-event view at all (``target`` /
# ``_event_id`` enrichment, the takedown synthesis, or a raw damage sum).
# The optimizer's compiled path builds that enriched per-event view only
# for these holders; everyone else scans the plain engine result.
EVENT_VIEW_SUPPORT_ITEMS = (
    EVENT_SCAN_SUPPORT_ITEMS
    | TAKEDOWN_SCAN_SUPPORT_ITEMS
    | CC_TRIGGER_ITEMS
    | frozenset({"Echoes of Helia"})
)


def has_event_view_support_items(items: Iterable[Mapping[str, Any]]) -> bool:
    """Whether any held item scans the per-event damage/takedown view."""
    return any(str(item.get("name", "")) in EVENT_VIEW_SUPPORT_ITEMS for item in items)


def _cleanse_active_packet(
    attacker: Any, target: Any, time: float, item: str
) -> dict[str, Any]:
    """One self-cast cleanse-kind packet for a cleanse active item."""
    from .cleanse_eligibility import item_declaration

    declaration = item_declaration(item)
    return _packet(
        attacker=attacker,
        target=target,
        time=time,
        kind="cleanse",
        source=f"{item} — {declaration['active_name']}",
        amount=1.0,
        target_scope="self",
        cleanse_item=item,
        source_key=item,
        utility_kind="cleanse",
    )


def _cleanse_movement_declaration(item: str) -> dict[str, Any]:
    """The atom-backed movement entry of a cleanse active item (ONE kernel
    builder — the walk consumes the same shape)."""
    from .cleanse_eligibility import item_declaration, movement_entry

    movement = movement_entry(item_declaration(item))
    if movement is None:
        raise KeyError(f"cleanse declaration for {item!r} has no movement entry")
    return movement


def derive_item_support_effects(
    attacker: Any,
    result: Mapping[str, Any],
    all_actors: list[Any],
    trigger_effects: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Compile the holder's explicit cross-participant item packets."""
    if attacker.team == "ally" and not getattr(
        getattr(attacker, "request", None), "ally_effects_enabled", False
    ):
        return []
    names = _item_names(attacker)
    teammates = _teammates(attacker, all_actors)
    packets: list[dict[str, Any]] = []
    triggers = _support_triggers(trigger_effects, attacker)
    # Each stream scans the full event ledger, so it is built only when a
    # held item consumes it (the registries above own that knowledge).
    cc_events = _cc_triggers(result) if names & CC_TRIGGER_ITEMS else []
    takedown_events = (
        _takedown_triggers(result) if names & TAKEDOWN_SCAN_SUPPORT_ITEMS else []
    )
    damage_events = _damage_triggers(result) if names & DAMAGE_TRIGGER_ITEMS else []

    # Reap is a progression/economy branch, not a guessed combat bonus.  The
    # authored minion-kill count is bounded by its sourced 100-kill quest and
    # produces one inspectable gold receipt only after the caller supplies it.
    if "Cull" in names:
        minion_kills = max(0.0, _option(attacker, "Cull", "reap_minion_kills"))
        cap = required_effect_value("Cull", "reap_max_gold")
        per_minion = required_effect_value("Cull", "reap_gold_per_minion")
        completion_gold = required_effect_value("Cull", "reap_completion_gold")
        earned = min(minion_kills, cap) * per_minion
        if minion_kills >= cap:
            earned += completion_gold
        if earned > 0.0:
            source_meta = ITEM_INPUT_OPTIONS["Cull"]
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=0.0,
                    kind="economy",
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

    # Rage is emitted from the same authored auto stream used by the damage
    # ledger.  No movement state is invented when the stream is absent or
    # coarse; each qualifying basic attack gets its own timestamped packet.
    if "Phage" in names:
        is_melee = bool(attacker.stats.get("is_melee", False))
        speed_key = (
            "rage_bonus_move_speed_melee"
            if is_melee
            else "rage_bonus_move_speed_ranged"
        )
        bonus_speed = required_effect_value("Phage", speed_key)
        duration = required_effect_value("Phage", "rage_duration")
        source_meta = ITEM_INPUT_OPTIONS["Phage"]
        for event in result.get("damage_events", ()):
            if not isinstance(event, Mapping):
                continue
            if str(event.get("source_key", "")) != "auto_attacks" and not bool(
                event.get("basic_attack")
            ):
                continue
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=_event_time(event),
                    kind="movement",
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

    # Support Quest is represented as explicit economy and vision outcomes.
    # The role-quest contract decides which transformed item is equipped; this
    # packet layer records only the authored progress/ward state for that item.
    # The sourced Shared Riches cadence and per-minion-type gold values ride
    # the economy receipt so the parser-backed numbers are visible beside the
    # authored progress instead of living only in the stat metadata.
    for quest_item in ("World Atlas", "Runic Compass"):
        if quest_item not in names:
            continue
        source_meta = ITEM_INPUT_OPTIONS[quest_item]
        gold = max(0.0, _option(attacker, quest_item, "shared_riches_gold"))
        gold_cap = required_effect_value(quest_item, "support_quest_threshold")
        ward_cap = required_effect_value(quest_item, "ward_charges")
        if gold > 0.0:
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=0.0,
                    kind="economy",
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
        ward_uses = max(0.0, min(_option(attacker, quest_item, "ward_uses"), ward_cap))
        if ward_uses > 0.0:
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=0.0,
                    kind="vision",
                    source=f"{quest_item} — Ward",
                    amount=ward_uses,
                    target_scope="self",
                    ward_uses=ward_uses,
                    ward_charges=ward_cap,
                    quest_threshold=gold_cap,
                    source_url=source_meta["source_url"],
                    source_revision_id=source_meta["source_revision_id"],
                )
            )

    # Tear of the Goddess — Manaflow packets are a PROJECTION of the typed
    # mana resource ledger (P3 slice 1): the fight engine admits casts
    # through ``resource_ledger``, records every PROVEN accepted eligible
    # hit (a denied cast can never trigger Tear, and a missing hit identity
    # fails closed), and applies each granted bonus max-mana to the same
    # account.  This layer only shapes the accepted hit receipts into the
    # public kind="resource" packet schema — it never recomputes cadence,
    # charges, or caps (the retired duplicate state).  A fight result
    # without a ledger section has no Manaflow activity by construction.
    if "Tear of the Goddess" in names:
        ledger_section = result.get("resource_ledger")
        tear = (
            ledger_section.get("tear") if isinstance(ledger_section, Mapping) else None
        )
        if isinstance(tear, Mapping):
            interval = required_effect_value(
                "Tear of the Goddess", "manaflow_charge_interval"
            )
            max_charges = max(
                1,
                int(
                    required_effect_value("Tear of the Goddess", "manaflow_max_charges")
                ),
            )
            per_trigger = required_effect_value(
                "Tear of the Goddess", "manaflow_bonus_mana_per_trigger"
            )
            per_champion = required_effect_value(
                "Tear of the Goddess", "manaflow_bonus_mana_per_champion"
            )
            mana_cap = required_effect_value(
                "Tear of the Goddess", "manaflow_bonus_mana_max"
            )
            source_meta = ITEM_INPUT_OPTIONS["Tear of the Goddess"]
            authored_mana = max(
                0.0, _option(attacker, "Tear of the Goddess", "manaflow_bonus_mana")
            )
            for hit in (
                tear.get("hits", ()) if isinstance(tear.get("hits"), Iterable) else ()
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
                        kind="resource",
                        source="Tear of the Goddess — Manaflow",
                        amount=grant,
                        target_scope="self",
                        bonus_mana_total=max(0.0, ledger_total - authored_capped),
                        bonus_mana_cap=float(hit.get("cap", mana_cap) or mana_cap),
                        authored_bonus_mana=authored_capped,
                        manaflow_charge_interval=interval,
                        manaflow_max_charges=max_charges,
                        manaflow_bonus_mana_per_trigger=per_trigger,
                        manaflow_bonus_mana_per_champion=per_champion,
                        trigger_kind="ability_cast_vs_champion",
                        charge_accrued_at=(use_count - 1) * interval,
                        _priority=-1.0,
                        source_url=source_meta["source_url"],
                        source_revision_id=source_meta["source_revision_id"],
                    )
                )

    # Umbral Glaive — Blackout is the ward-denial vision state: the sourced
    # one-second unseen gate arms Nightstalker, whose sourced true damage
    # (50 + 1.5 x lethality) rides the typed first-auto packet in the damage
    # ledger.  Blackout itself (the 8-second ward/trap denial aura) has no
    # champion-facing target in the fighter model, so this layer emits one
    # vision-dimension receipt when the authored ready gate is set; it never
    # guesses ward hits or converts the denial into damage.
    if "Umbral Glaive" in names:
        ready = _option(attacker, "Umbral Glaive", "nightstalker_ready") > 0.0
        if ready:
            source_meta = ITEM_INPUT_OPTIONS["Umbral Glaive"]
            lethality = max(
                0.0,
                (
                    float(attacker.stats.get("lethality", 0.0) or 0.0)
                    if isinstance(attacker.stats, Mapping)
                    else 0.0
                ),
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=0.0,
                    kind="vision",
                    source="Umbral Glaive — Blackout",
                    amount=1.0,
                    target_scope="self",
                    ward_uses=0.0,
                    nightstalker_ready=True,
                    blackout_trigger_windows=1,
                    unseen_gate_seconds=required_effect_value(
                        "Umbral Glaive", "nightstalker_unseen_seconds"
                    ),
                    trigger_window_seconds=required_effect_value(
                        "Umbral Glaive", "nightstalker_trigger_window"
                    ),
                    blackout_duration=required_effect_value(
                        "Umbral Glaive", "blackout_duration"
                    ),
                    ward_only=True,
                    ward_hits_modeled=0,
                    true_damage_on_ward_hit=(
                        required_effect_value("Umbral Glaive", "base")
                        + required_effect_value("Umbral Glaive", "lethality_ratio")
                        * lethality
                    ),
                    source_url=source_meta["source_url"],
                    source_revision_id=source_meta["source_revision_id"],
                )
            )

    # Fimbulwinter's Everlasting is a self shield that fires only from an
    # explicitly marked immobilize, or a slow for a melee holder.  Its
    # trigger predicate, per-cast-instance cadence, and cooldown are
    # kernel-owned (state_lifecycle); the mana gate and shield pricing stay
    # here.  No cast or crowd-control state is inferred from a spell name.
    # Every denial is a named ``item_denial`` receipt (ranged_slow,
    # mana_gate, cooldown, duplicate_instance, missing_instance_identity,
    # untyped_cc, unknown_cc_kind) so a silent skip can never hide an
    # unreviewed or ambiguous trigger.
    if "Fimbulwinter" in names:
        is_melee = bool(attacker.stats.get("is_melee", False))
        champion_stats = result.get("champion_stats", attacker.stats)
        if not isinstance(champion_stats, Mapping):
            champion_stats = attacker.stats
        raw_maximum_mana = champion_stats.get(
            "max_mana", attacker.stats.get("max_mana", _MISSING)
        )
        maximum_mana, maximum_mana_reason = _mana_input(
            raw_maximum_mana,
            missing_reason="missing_maximum_mana",
            invalid_reason="invalid_maximum_mana",
        )
        raw_current_mana = attacker.stats.get("mana", _MISSING)
        mana_gate = fimbulwinter_mana_gate_authority()
        range_authority = fimbulwinter_nearby_enemy_range_authority()
        holder_identity = getattr(attacker, "participant_id", None)
        source_meta = ITEM_INPUT_OPTIONS["Fimbulwinter"]

        def _denial(
            event: Mapping[str, Any], reason: str, **details: Any
        ) -> dict[str, Any]:
            """One named fail-closed receipt for a denied Everlasting trigger.

            Receipts are NOT applied packets: consumers of the applied
            support stream filter ``kind == "item_denial"`` (the participant
            timeline splits them into the public denial-receipt section).
            """
            return _packet(
                attacker=attacker,
                target=attacker,
                time=_event_time(event),
                kind="item_denial",
                source="Fimbulwinter — Everlasting",
                target_scope="self",
                reason=reason,
                cc_kind=str(event.get("cc_kind", "") or ""),
                event_id=event.get("_event_id"),
                trigger_rule=_FIMBULWINTER_TRIGGER_RULE.public_receipt(),
                mana_gate_status=mana_gate["status"],
                nearby_enemy_range_units=range_authority["range_units"],
                range_center=(
                    holder_identity
                    if isinstance(holder_identity, str) and holder_identity.strip()
                    else None
                ),
                range_input_status=range_authority["spatial_input_status"],
                source_url=source_meta["source_url"],
                source_revision_id=source_meta["source_revision_id"],
                _priority=0.0,
                **details,
            )

        if not isinstance(holder_identity, str) or not holder_identity.strip():
            for event in cc_events:
                if _FIMBULWINTER_TRIGGER_RULE.match(event, is_melee=is_melee):
                    packets.append(_denial(event, "missing_holder_identity"))
            cc_events = []

        # Ambiguous / unknown / ranged-slow metadata: every CC-adjacent
        # event (damage-attached or control-only) that cannot match a branch
        # is receipted once (an event with NO CC metadata is not a candidate
        # and produces nothing).
        for event in _cc_event_stream(result):
            reason = _FIMBULWINTER_TRIGGER_RULE.denial_reason(event, is_melee=is_melee)
            if reason:
                packets.append(_denial(event, reason))

        cooldown_rule = CooldownRule(
            name="Fimbulwinter — Everlasting",
            cooldown_seconds=float(
                required_effect_value("Fimbulwinter", "everlasting_cooldown")
            ),
            per_target=False,
            source=SourceReceipt.from_mapping(source_meta),
        )
        cooldown_state = CooldownState(cooldown_rule)
        # One shield per cast instance: a multi-part cast that carries
        # several CC-marked events still arms Everlasting once.
        cast_cadence = InstanceCadence(once_only=True)
        for event in cc_events:
            trigger_kind = _FIMBULWINTER_TRIGGER_RULE.match(event, is_melee=is_melee)
            if not trigger_kind:
                # The CC-adjacent scan above already receipted this event
                # with its named reason (ranged_slow / untyped_cc /
                # unknown_cc_kind); it is not an eligible branch.
                continue
            time = _event_time(event)
            raw_cast_identity = event.get("ability_instance")
            if not isinstance(raw_cast_identity, str) or not raw_cast_identity.strip():
                packets.append(_denial(event, "missing_instance_identity"))
                continue
            cast_identity = raw_cast_identity.strip()
            if not cast_cadence.allow(time, cast_identity):
                packets.append(_denial(event, "duplicate_instance"))
                continue
            if not cooldown_state.is_ready(time):
                packets.append(_denial(event, "cooldown"))
                continue
            if maximum_mana_reason is not None:
                packets.append(_denial(event, maximum_mana_reason))
                continue
            current_mana, current_mana_reason = _current_mana_at(
                result, time, raw_current_mana
            )
            if current_mana_reason is not None:
                packets.append(_denial(event, current_mana_reason))
                continue
            if mana_gate["status"] == "source_unavailable":
                packets.append(
                    _denial(
                        event,
                        "mana_gate_authority_unavailable",
                        current_mana=current_mana,
                        maximum_mana=maximum_mana,
                        mana_threshold_ratio=mana_gate["threshold_ratio"],
                        mana_comparison=mana_gate["comparison"],
                    )
                )
                continue
            if mana_gate["status"] != "script_authorized":
                raise ValueError(
                    "Fimbulwinter Everlasting mana gate has an unsupported "
                    f"authority status: {mana_gate['status']!r}"
                )
            if current_mana is None or maximum_mana is None:
                raise RuntimeError("validated Fimbulwinter mana state is unavailable")
            threshold_ratio, threshold_reason = _mana_input(
                mana_gate["threshold_ratio"],
                missing_reason="missing_mana_threshold_ratio",
                invalid_reason="invalid_mana_threshold_ratio",
            )
            if threshold_reason is not None or threshold_ratio is None:
                raise ValueError(
                    "script-authorized Fimbulwinter mana gate requires a valid "
                    "threshold_ratio"
                )
            if mana_gate["comparison"] != "current_mana > maximum_mana * ratio":
                raise ValueError(
                    "script-authorized Fimbulwinter mana gate requires an exact "
                    "comparison contract"
                )
            if maximum_mana == 0.0 or current_mana <= maximum_mana * threshold_ratio:
                packets.append(
                    _denial(
                        event,
                        "mana_gate",
                        current_mana=current_mana,
                        maximum_mana=maximum_mana,
                        mana_threshold_ratio=threshold_ratio,
                        mana_comparison=mana_gate["comparison"],
                    )
                )
                continue

            raw_target_identity = event.get("target")
            if (
                not isinstance(raw_target_identity, str)
                or not raw_target_identity.strip()
            ):
                packets.append(_denial(event, "missing_target_identity"))
                continue

            # The base shield remains sourced.  The actor model has no typed
            # holder-centered position or distance snapshot, so the 1.8
            # branch stays withheld.  Whole-roster size is not range proof.
            multiplier = 1.0
            packets.append(
                _denial(
                    event,
                    "nearby_enemy_spatial_input_unavailable",
                    denied_component="multi_target_multiplier",
                    base_shield_applied=True,
                    nearby_enemy_count=None,
                    requested_multi_target_multiplier=range_authority["multiplier"],
                    applied_multi_target_multiplier=multiplier,
                )
            )
            amount = (
                required_effect_value("Fimbulwinter", "everlasting_base_shield")
                + current_mana
                * required_effect_value(
                    "Fimbulwinter", "everlasting_current_mana_ratio"
                )
            ) * multiplier
            cooldown_state.start(time, sequence=0)
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=time,
                    kind="shield",
                    source="Fimbulwinter — Everlasting",
                    _event_id=(
                        f"{attacker.participant_id}:fimbulwinter:{cast_identity}"
                    ),
                    amount=amount,
                    duration=required_effect_value(
                        "Fimbulwinter", "everlasting_duration"
                    ),
                    target_scope="self",
                    trigger=trigger_kind,
                    _trigger_event_id=event.get("_event_id"),
                    trigger_kind=trigger_kind,
                    current_mana=current_mana,
                    mana_threshold=maximum_mana * threshold_ratio,
                    nearby_enemy_count=None,
                    nearby_enemy_range_units=range_authority["range_units"],
                    range_center=holder_identity,
                    range_input_status=range_authority["spatial_input_status"],
                    range_boundary_status=range_authority["boundary_status"],
                    requested_multi_target_multiplier=range_authority["multiplier"],
                    multi_target_multiplier=multiplier,
                    cooldown=cooldown_rule.cooldown_seconds,
                    cooldown_until=time + cooldown_rule.cooldown_seconds,
                    trigger_rule=_FIMBULWINTER_TRIGGER_RULE.public_receipt(),
                    source_url=source_meta["source_url"],
                    source_revision_id=source_meta["source_revision_id"],
                    _priority=0.5,
                )
            )

    # Shared target modifiers are emitted only from an authored trigger.  The
    # holder's own pair engine already prices its personal Black Cleaver,
    # Bloodletter, Bloodsong, and Abyssal branches; the ordered participant
    # walk consumes these packets for every other eligible source without
    # double-counting the originating holder.
    if "Abyssal Mask" in names:
        for target in (
            actor for actor in all_actors if not _same_side(attacker, actor)
        ):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=0.0,
                    kind="damage_modifier",
                    source="Abyssal Mask — Unmake",
                    amount=ally_item_effect_value("Abyssal Mask", "magic_damage_amp"),
                    multiplier=1.0
                    + ally_item_effect_value("Abyssal Mask", "magic_damage_amp"),
                    all_sources=True,
                    persistent=True,
                    range_assumption="within_700_units",
                )
            )

    if "Bloodsong" in names:
        expose_key = (
            "expose_weakness_melee"
            if bool(attacker.stats.get("is_melee", False))
            else "expose_weakness_ranged"
        )
        for event in damage_events:
            if str(event.get("source_key", "")) != "spellblade_Bloodsong":
                continue
            target = _target_by_id(all_actors, str(event.get("target", "")))
            if target is None:
                continue
            rate = ally_item_effect_value("Bloodsong", expose_key)
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=_event_time(event),
                    kind="damage_modifier",
                    source="Bloodsong — Expose Weakness",
                    amount=rate,
                    duration=ally_item_effect_value(
                        "Bloodsong", "expose_weakness_duration"
                    ),
                    multiplier=1.0 + rate,
                    all_sources=True,
                    cooldown=ally_item_effect_value(
                        "Bloodsong", "expose_weakness_cooldown"
                    ),
                    owner=attacker.participant_id,
                    trigger_event_id=event.get("_event_id"),
                )
            )

    reduction_stacks: dict[tuple[str, str], int] = {}
    for event in damage_events:
        target = _target_by_id(all_actors, str(event.get("target", "")))
        if target is None:
            continue
        damage_type = str(event.get("damage_type", ""))
        source_id = str(event.get("_event_id", ""))
        if "Black Cleaver" in names and damage_type == "physical":
            key = (target.participant_id, "armor")
            stacks = min(
                int(
                    ally_item_effect_value(
                        "Black Cleaver", "armor_reduction_max_stacks"
                    )
                ),
                reduction_stacks.get(key, 0) + 1,
            )
            reduction_stacks[key] = stacks
            percent = stacks * ally_item_effect_value(
                "Black Cleaver", "armor_reduction_per_stack"
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=_event_time(event),
                    kind="damage_modifier",
                    source="Black Cleaver — Carve",
                    amount=percent,
                    duration=ally_item_effect_value(
                        "Black Cleaver", "armor_reduction_duration"
                    ),
                    armor_reduction_percent=percent,
                    resistance_type="armor",
                    owner=attacker.participant_id,
                    trigger_event_id=event.get("_event_id", source_id),
                    stack_count=stacks,
                )
            )
        if (
            "Bloodletter's Curse" in names
            and damage_type == "magic"
            and bool(event.get("is_ability"))
        ):
            key = (target.participant_id, "mr")
            stacks = min(
                int(
                    ally_item_effect_value(
                        "Bloodletter's Curse", "mr_reduction_max_stacks"
                    )
                ),
                reduction_stacks.get(key, 0) + 1,
            )
            reduction_stacks[key] = stacks
            percent = stacks * ally_item_effect_value(
                "Bloodletter's Curse", "mr_reduction_per_stack"
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=_event_time(event),
                    kind="damage_modifier",
                    source="Bloodletter's Curse — Vile Decay",
                    amount=percent,
                    duration=ally_item_effect_value(
                        "Bloodletter's Curse", "mr_reduction_duration"
                    ),
                    mr_reduction_percent=percent,
                    resistance_type="magic_resistance",
                    owner=attacker.participant_id,
                    trigger_event_id=event.get("_event_id", source_id),
                    stack_count=stacks,
                )
            )

    for takedown in takedown_events:
        if "Cryptbloom" not in names:
            break
        amount = ally_item_effect_value("Cryptbloom", "life_from_death_base_heal") + (
            float(attacker.stats.get("ability_power", 0.0) or 0.0)
            * ally_item_effect_value("Cryptbloom", "life_from_death_ap_ratio")
        )
        for recipient in (attacker, *teammates):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=recipient,
                    time=_event_time(takedown),
                    kind="heal",
                    source="Cryptbloom — Life From Death",
                    amount=amount,
                    duration=ally_item_effect_value(
                        "Cryptbloom", "life_from_death_nova_duration"
                    ),
                    target_scope="nova_allied_champions",
                    trigger="explicit_takedown_within_damage_window",
                    cooldown=ally_item_effect_value(
                        "Cryptbloom", "life_from_death_cooldown"
                    ),
                )
            )

    # Triggered enchanter passives.  The target is carried by the authored
    # champion packet; no cursor or radius is guessed.
    for trigger in triggers:
        target = _target_by_id(all_actors, str(trigger.get("target", "")))
        if target is None:
            continue
        time = _event_time(trigger)
        if "Ardent Censer" in names:
            packets.extend(
                (
                    _packet(
                        attacker=attacker,
                        target=recipient,
                        time=time,
                        kind="stat_buff",
                        source="Ardent Censer — Sanctify",
                        amount=ally_item_effect_value(
                            "Ardent Censer", "sanctify_bonus_attack_speed"
                        ),
                        duration=ally_item_effect_value(
                            "Ardent Censer", "sanctify_duration"
                        ),
                        bonus_attack_speed_percent=ally_item_effect_value(
                            "Ardent Censer", "sanctify_bonus_attack_speed"
                        ),
                        on_hit_magic_damage=ally_item_effect_value(
                            "Ardent Censer", "sanctify_on_hit_magic"
                        ),
                        recipient_role="holder_and_healed_ally",
                    )
                    for recipient in (attacker, target)
                )
            )
        if "Staff of Flowing Water" in names:
            packets.extend(
                (
                    _packet(
                        attacker=attacker,
                        target=recipient,
                        time=time,
                        kind="stat_buff",
                        source="Staff of Flowing Water — Rapids",
                        amount=ally_item_effect_value(
                            "Staff of Flowing Water", "bonus_ability_power"
                        ),
                        duration=ally_item_effect_value(
                            "Staff of Flowing Water", "duration"
                        ),
                        ability_power=ally_item_effect_value(
                            "Staff of Flowing Water", "bonus_ability_power"
                        ),
                        ability_haste=ally_item_effect_value(
                            "Staff of Flowing Water", "bonus_ability_haste"
                        ),
                        recipient_role="holder_and_healed_ally",
                    )
                    for recipient in (attacker, target)
                )
            )
        if "Moonstone Renewer" in names:
            candidates = [
                actor
                for actor in teammates
                if actor.participant_id != target.participant_id
            ]
            chain_target = candidates[0] if candidates else target
            fraction_key = (
                "heal_chain_fraction"
                if str(trigger.get("kind")) == "heal"
                else "shield_chain_fraction"
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=chain_target,
                    time=time,
                    kind=str(trigger.get("kind", "shield")),
                    source="Moonstone Renewer — Starlit Grace",
                    amount=float(trigger.get("amount", 0.0))
                    * ally_item_effect_value("Moonstone Renewer", fraction_key),
                    duration=float(trigger.get("duration", 0.0) or 0.0),
                    target_scope="other_nearest_wounded_ally",
                    chain_fraction=ally_item_effect_value(
                        "Moonstone Renewer", fraction_key
                    ),
                )
            )
        if "Dream Maker" in names:
            packets.extend(
                (
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=time,
                        kind="damage_modifier",
                        source="Dream Maker — Blue Dream Bubble",
                        amount=ally_item_level_value(
                            "Dream Maker",
                            "blue_reduction_min",
                            "blue_reduction_max",
                            target.level,
                        ),
                        duration=ally_item_effect_value(
                            "Dream Maker", "dream_duration"
                        ),
                        damage_reduction=True,
                        next_event_only=True,
                    ),
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=time,
                        kind="on_hit_magic",
                        source="Dream Maker — Purple Dream Bubble",
                        amount=ally_item_level_value(
                            "Dream Maker",
                            "purple_magic_min",
                            "purple_magic_max",
                            target.level,
                        ),
                        duration=ally_item_effect_value(
                            "Dream Maker", "dream_duration"
                        ),
                        next_event_only=True,
                    ),
                )
            )
        if "Echoes of Helia" in names:
            raw_damage = sum(
                max(
                    0.0,
                    float(event.get("raw_damage", event.get("damage", 0.0)) or 0.0),
                )
                for event in result.get("damage_events", [])
            )
            cap = ally_item_level_value(
                "Echoes of Helia", "charge_cap_min", "charge_cap_max", target.level
            )
            charges = min(
                cap,
                raw_damage
                * ally_item_effect_value("Echoes of Helia", "charge_damage_ratio"),
            )
            if charges > 0.0:
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=time,
                        kind="heal",
                        source="Echoes of Helia — Soul Siphon",
                        amount=charges,
                        target_scope="healed_or_shielded_ally",
                        charges_consumed=charges,
                    )
                )
                # Soul Charges are consumed by the first qualifying heal or
                # shield; subsequent triggers in this authored window do not
                # duplicate the same stored pool.
                break
        if "Diadem of Songs" in names:
            wounded = target
            packets.append(
                _packet(
                    attacker=attacker,
                    target=wounded,
                    time=time,
                    kind="heal",
                    source="Diadem of Songs — Consonance",
                    amount=float(attacker.stats.get("mana", 0.0))
                    * ally_item_effect_value(
                        "Diadem of Songs", "consonance_max_mana_ratio"
                    ),
                    target_scope="nearest_most_wounded_ally",
                    cooldown=ally_item_effect_value(
                        "Diadem of Songs", "consonance_cooldown"
                    ),
                )
            )

    # A hard-CC marker is required for the passives below.  If the reviewed
    # champion module does not emit one, the effect is intentionally absent;
    # callers must not turn an arbitrary cast boundary into a slow/root.
    for cc in cc_events:
        time = _event_time(cc)
        if "Bandlepipes" in names:
            is_melee = bool(attacker.stats.get("is_melee", False))
            duration_key = (
                "fanfare_duration_melee" if is_melee else "fanfare_duration_ranged"
            )
            as_key = (
                "fanfare_ally_attack_speed_melee"
                if is_melee
                else "fanfare_ally_attack_speed_ranged"
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=time,
                    kind="movement",
                    source="Bandlepipes — Fanfare",
                    amount=ally_item_effect_value(
                        "Bandlepipes", "fanfare_bonus_move_speed"
                    ),
                    duration=ally_item_effect_value("Bandlepipes", duration_key),
                    bonus_move_speed_percent=ally_item_effect_value(
                        "Bandlepipes", "fanfare_bonus_move_speed"
                    ),
                    target_scope="self",
                    trigger="authored_immobilize_or_slow",
                )
            )
            for recipient in (attacker, *teammates):
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=recipient,
                        time=time,
                        kind="stat_buff",
                        source="Bandlepipes — Fanfare",
                        amount=ally_item_effect_value("Bandlepipes", as_key),
                        duration=ally_item_effect_value("Bandlepipes", duration_key),
                        bonus_attack_speed_percent=ally_item_effect_value(
                            "Bandlepipes", as_key
                        ),
                        trigger="authored_immobilize_or_slow",
                    )
                )
        if "Solstice Sleigh" in names and teammates:
            target = teammates[0]
            for recipient in (attacker, target):
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=recipient,
                        time=time,
                        kind="temporary_health",
                        source="Solstice Sleigh — Going Sledding",
                        amount=ally_item_level_value(
                            "Solstice Sleigh",
                            "temporary_health_min",
                            "temporary_health_max",
                            recipient.level,
                        ),
                        duration=ally_item_effect_value("Solstice Sleigh", "duration"),
                        bonus_move_speed_percent=ally_item_effect_value(
                            "Solstice Sleigh", "bonus_move_speed_percent"
                        ),
                        cooldown=ally_item_effect_value("Solstice Sleigh", "cooldown"),
                        target_scope=(
                            "self" if recipient is attacker else "most_wounded_ally"
                        ),
                    )
                )
        if "Imperial Mandate" in names:
            target = _target_by_id(all_actors, str(cc.get("target", "")))
            if target is not None:
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=time,
                        kind="damage_modifier",
                        source="Imperial Mandate — Command",
                        amount=ally_item_effect_value(
                            "Imperial Mandate", "command_damage_amp"
                        ),
                        duration=ally_item_effect_value(
                            "Imperial Mandate", "command_duration"
                        ),
                        multiplier=1.0
                        + ally_item_effect_value(
                            "Imperial Mandate", "command_damage_amp"
                        ),
                        all_sources=True,
                    )
                )

    # Explicit item-actives.  A non-zero timestamp is the complete trigger
    # contract; the packet is not emitted at t=0 by default.
    active_time = _active_seconds(attacker, "Locket of the Iron Solari")
    if "Locket of the Iron Solari" in names and active_time > 0.0:
        for target in (attacker, *teammates):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=active_time,
                    kind="shield",
                    source="Locket of the Iron Solari — Devotion",
                    amount=ally_item_level_value(
                        "Locket of the Iron Solari",
                        "shield_min",
                        "shield_max",
                        target.level,
                    ),
                    duration=ally_item_effect_value(
                        "Locket of the Iron Solari", "shield_duration"
                    ),
                    target_scope="all_selected_teammates",
                )
            )
    active_time = _active_seconds(attacker, "Mikael's Blessing")
    if "Mikael's Blessing" in names and active_time > 0.0 and teammates:
        target = teammates[0]
        packets.append(
            _packet(
                attacker=attacker,
                target=target,
                time=active_time,
                kind="heal",
                source="Mikael's Blessing — Purify",
                amount=ally_item_level_value(
                    "Mikael's Blessing", "heal_min", "heal_max", target.level
                ),
                target_scope="explicit_selected_ally",
                cleanse=True,
                cleanse_item="Mikael's Blessing",
            )
        )
    # Quicksilver Sash / Mercurial Scimitar — Quicksilver (P2 Slice 4):
    # self-only cleanse actives.  An explicit active_seconds input emits
    # the sourced self-cast cleanse packet; Mercurial additionally grants
    # its SEPARATE movement utility (amount/duration sourced from the
    # atom-backed cleanse declaration — never a call-site literal).
    active_time = _active_seconds(attacker, "Quicksilver Sash")
    if "Quicksilver Sash" in names and active_time > 0.0:
        packets.append(
            _cleanse_active_packet(attacker, attacker, active_time, "Quicksilver Sash")
        )
    active_time = _active_seconds(attacker, "Mercurial Scimitar")
    if "Mercurial Scimitar" in names and active_time > 0.0:
        packets.append(
            _cleanse_active_packet(
                attacker, attacker, active_time, "Mercurial Scimitar"
            )
        )
        movement = _cleanse_movement_declaration("Mercurial Scimitar")
        packets.append(
            _packet(
                attacker=attacker,
                target=attacker,
                time=active_time,
                kind="movement",
                source=movement["source"],
                amount=movement["amount"],
                duration=movement["duration"],
                bonus_move_speed_percent=movement["amount"],
                target_scope="self",
                cleanse_item="Mercurial Scimitar",
                source_key="Mercurial Scimitar",
                utility_kind="movement",
            )
        )
    active_time = _active_seconds(attacker, "Redemption")
    if "Redemption" in names and active_time > 0.0:
        beam_delay = ally_item_effect_value("Redemption", "beam_delay")
        range_units = ally_item_effect_value("Redemption", "target_area_range_units")
        for target in (attacker, *teammates):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=active_time + beam_delay,
                    kind="heal",
                    source="Redemption — Intervention",
                    amount=ally_item_level_value(
                        "Redemption", "heal_min", "heal_max", target.level
                    ),
                    target_scope="redemption_allies_in_radius",
                    beam_delay=beam_delay,
                    range_assumption=f"within_{range_units:g}_units",
                )
            )
        # Intervention is also an area true-damage packet.  The calculator has
        # no map coordinates, so every selected enemy is an explicit roster
        # target under the sourced area-radius assumption; no proximity order
        # is invented.  The packet enters the normal phase-0 damage walk so
        # shields, death cutoffs, and attribution remain shared with all other
        # damage events.
        true_damage_ratio = ally_item_effect_value(
            "Redemption", "enemy_max_health_true_damage_ratio"
        )
        for target in (
            actor for actor in all_actors if not _same_side(attacker, actor)
        ):
            amount = (
                max(0.0, float(target.stats.get("health", 0.0))) * true_damage_ratio
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=active_time + beam_delay,
                    kind="damage",
                    source="Redemption — Intervention",
                    amount=amount,
                    damage=amount,
                    damage_type="true",
                    event_precision="exact",
                    target_scope="enemy_champions_in_radius",
                    range_assumption=f"within_{range_units:g}_units",
                    beam_delay=beam_delay,
                    _priority=0.0,
                    sequence=0,
                )
            )
        # Intervention grants sight of the target area for the beam
        # call-down ("granting sight of the area for the duration"): one
        # vision receipt per selected enemy, window [cast, impact] =
        # the sourced 2.5s beam_delay.  The registry previously carried a
        # 3.0s reveal duration with NO local source (wiki text names no
        # number, the binary has no reveal value) — removed in P3-3H; the
        # sourced call-down window is the receipt.
        for target in (
            actor for actor in all_actors if not _same_side(attacker, actor)
        ):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=active_time,
                    kind="vision",
                    source="Redemption — Intervention",
                    amount=beam_delay,
                    duration=beam_delay,
                    reveal_duration=beam_delay,
                    target_scope="enemy_champions_in_radius",
                    range_assumption=f"within_{range_units:g}_units",
                    beam_delay=beam_delay,
                )
            )
    active_time = _active_seconds(attacker, "Shurelya's Battlesong")
    if "Shurelya's Battlesong" in names and active_time > 0.0:
        for target in (attacker, *teammates):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=active_time,
                    kind="movement",
                    source="Shurelya's Battlesong — Inspiring Speech",
                    amount=ally_item_effect_value(
                        "Shurelya's Battlesong", "bonus_move_speed_percent"
                    ),
                    duration=ally_item_effect_value(
                        "Shurelya's Battlesong", "duration"
                    ),
                    bonus_move_speed_percent=ally_item_effect_value(
                        "Shurelya's Battlesong", "bonus_move_speed_percent"
                    ),
                    target_scope="all_selected_teammates",
                )
            )
    active_time = _active_seconds(attacker, "Stridebreaker")
    if "Stridebreaker" in names and active_time > 0.0:
        slow_percent = float(required_effect_value("Stridebreaker", "slow_percent"))
        slow_duration = float(required_effect_value("Stridebreaker", "slow_duration"))
        move_speed_percent = float(
            required_effect_value("Stridebreaker", "bonus_move_speed_percent")
        )
        move_speed_duration = float(
            required_effect_value("Stridebreaker", "bonus_move_speed_duration")
        )
        area_radius = float(required_effect_value("Stridebreaker", "area_radius"))
        front_offset = float(required_effect_value("Stridebreaker", "front_offset"))
        for target in (
            actor for actor in all_actors if not _same_side(attacker, actor)
        ):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=active_time,
                    kind="slow",
                    source="Stridebreaker — Breaking Shockwave",
                    amount=slow_percent,
                    duration=slow_duration,
                    target_scope="enemy_champions_in_radius",
                    slow_percent=slow_percent,
                    range_assumption=f"within_{area_radius:g}_units",
                    cast_geometry=f"{front_offset:g}_unit_front_offset",
                    trigger="explicit_active_seconds",
                )
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=active_time,
                    kind="movement",
                    source="Stridebreaker — Breaking Shockwave",
                    amount=move_speed_percent,
                    duration=move_speed_duration,
                    target_scope="self_per_champion_hit",
                    bonus_move_speed_percent=move_speed_percent,
                    champion_hit_target=target.participant_id,
                    range_assumption=f"within_{area_radius:g}_units",
                    cast_geometry=f"{front_offset:g}_unit_front_offset",
                    trigger="explicit_active_seconds",
                )
            )
    return packets


def schedule_knights_vow(
    all_actors: list[Any],
    incoming: Mapping[str, list[dict[str, Any]]],
    outgoing: Mapping[str, list[dict[str, Any]]],
    support_effects: dict[str, list[dict[str, Any]]],
) -> None:
    """Attach one deterministic Worthy tether and redirect/heal receipts."""
    for holder in all_actors:
        tether = resolve_knights_vow_tether(holder, all_actors)
        if tether is None:
            continue
        target = tether["target"]
        fraction = tether["redirect_fraction"]
        heal_fraction = tether["heal_fraction"]
        within_range = tether["within_range"]
        holder_health_ready = tether["holder_health_ready"]
        # Pledge is unit-targeted and only operates inside 1250 units.  The
        # roster has no spatial coordinates, so the scenario must expose the
        # authored in-range assumption instead of letting the calculator
        # silently guess it.  The holder-health gate is checked again by the
        # ordered survival walk as health changes over time.
        if within_range <= 0.0 or holder_health_ready <= 0.0:
            reason = (
                "worthy_out_of_range"
                if within_range <= 0.0
                else "holder_health_gate_disabled"
            )
            for event in incoming.get(target.participant_id, []):
                if str(event.get("damage_type", "")) in {"physical", "magic"}:
                    event["redirect_skipped_reason"] = reason
            continue
        for event in incoming.get(target.participant_id, []):
            if str(event.get("damage_type", "")) not in {"physical", "magic"}:
                continue
            if event.get("_reactive") or event.get("_deferred"):
                continue
            if event.get("redirect_fraction"):
                continue
            if not any(
                actor.participant_id == str(event.get("attacker", ""))
                and not _same_side(holder, actor)
                for actor in all_actors
            ):
                continue
            event["redirect_fraction"] = fraction
            event["redirect_target"] = holder.participant_id
            event["redirect_source"] = "Knight's Vow — Sacrifice"
            event["redirect_pre_mitigation_required"] = True
            event["redirect_holder_health_ratio"] = ally_item_effect_value(
                "Knight's Vow", "holder_health_threshold_ratio"
            )
            event["redirect_range_units"] = ally_item_effect_value(
                "Knight's Vow", "worthy_range_units"
            )
            event["redirect_source_revision_id"] = int(
                ally_item_effect_value("Knight's Vow", "source_revision_id")
            )
        for event in outgoing.get(target.participant_id, []):
            if str(event.get("damage_type", "")) not in {"physical", "magic", "true"}:
                continue
            amount = max(0.0, float(event.get("damage", 0.0) or 0.0))
            if amount <= 0.0:
                continue
            support_effects[holder.participant_id].append(
                _packet(
                    attacker=holder,
                    target=holder,
                    time=_event_time(event),
                    kind="heal",
                    source="Knight's Vow — Sacrifice",
                    amount=amount * heal_fraction,
                    target_scope="holder_from_worthy_damage",
                    healing_category="knights_vow",
                    requires_holder_health_ratio=ally_item_effect_value(
                        "Knight's Vow", "holder_health_threshold_ratio"
                    ),
                    range_units=ally_item_effect_value(
                        "Knight's Vow", "worthy_range_units"
                    ),
                    source_revision_id=int(
                        ally_item_effect_value("Knight's Vow", "source_revision_id")
                    ),
                )
            )


def has_ordered_item_team_effects(items: Iterable[Mapping[str, Any]]) -> bool:
    """Whether any build requires the legacy event walk for team packets."""
    return any(str(item.get("name", "")) in ALLY_ITEM_EFFECTS for item in items)


__all__ = [
    "derive_item_support_effects",
    "has_ordered_item_team_effects",
    "schedule_knights_vow",
]
