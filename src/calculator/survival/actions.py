"""Typed survival actions — the single state-transition interface (issue #137).

Every mechanic the coupled survival walks apply is expressed as one
:class:`SurvivalAction` carrying an :class:`ActionKind` and all typed fields
that mechanic reads.  The receipt walk and the optimizer's score walk both
consume this interface; the only thing that differs between them is the
ledger representation (event-annotating dicts vs parallel-array
accumulation) behind :func:`~survival.transitions.apply_transition`.

Ordering helpers (``action_key``, ``participant_order``, ``event_sequence``)
live here too because the sort key is part of the action's identity: the
walk consumes actions in exactly this total order, and both the receipt
composition and the score compiler build the same keys.
"""

from __future__ import annotations

from enum import Enum
from collections.abc import Mapping
from typing import Any, NamedTuple

# ---------------------------------------------------------------------------
# Action kinds
# ---------------------------------------------------------------------------


class ActionKind(Enum):
    """Every survival mechanic the kernel can transition, as one dispatch key.

    Standalone kinds are returned by :func:`classify_event_kind` and
    dispatched by :func:`~survival.transitions.apply_transition`.  The
    remaining members are *embedded* transitions — state changes authored
    *inside* a damage/heal application (lifeline thresholds, reactive
    barriers, Maw omnivamp, Defy, timed-shield expiry) — implemented as
    named kernel functions and listed here so the typed interface covers
    every mechanic without inventing artificial action boundaries.
    """

    # Damage (``PLAIN_DAMAGE`` is the hot-loop marker: no trigger link, no
    # live-health repricing, no Grievous pack, no wound — the walk reads
    # none of those four fields for it).
    PLAIN_DAMAGE = "plain_damage"
    DAMAGE = "damage"
    EXECUTE = "execute"
    DEFER = "defer"
    REDIRECT = "redirect"
    # Recovery / barriers
    HEAL = "heal"
    OVERHEAL_SHIELD = "overheal_shield"
    ICHOR_CONVERT = "ichor_convert"
    SHIELD = "shield"
    TEMP_HEALTH = "temporary_health"
    # Combat-state transitions
    REVIVE = "revive"
    STASIS = "stasis"
    INVULNERABLE = "invulnerable"
    UNTARGETABLE = "untargetable"
    SPELL_SHIELD = "spell_shield"
    STAT_BUFF = "stat_buff"
    DAMAGE_MODIFIER = "damage_modifier"
    ON_HIT_MAGIC = "on_hit_magic"
    UTILITY = "utility"
    # Timed-shield expiry, lifeline threshold triggers, reactive shields,
    # Maw omnivamp, and Defy are embedded transitions implemented as kernel
    # functions; they never appear as standalone actions.


# Kinds a damage event may classify to; every one applies the shared damage
# kernel (the kind only drives observation and the fast-branch marker).
_DAMAGE_KINDS = frozenset(
    {
        ActionKind.PLAIN_DAMAGE,
        ActionKind.DAMAGE,
        ActionKind.EXECUTE,
        ActionKind.DEFER,
        ActionKind.REDIRECT,
    }
)


# ---------------------------------------------------------------------------
# The typed action
# ---------------------------------------------------------------------------


class SurvivalAction(NamedTuple):
    """One typed state transition in the coupled survival walk.

    Both adapters consume exactly this interface.  ``event`` is the
    receipt adapter's observation target (the event dict the public
    timeline serializes); score-mode actions leave it ``None`` so the
    kernel never annotates what the optimizer does not read.
    """

    # Ordering / routing
    sort_key: tuple = ()
    time: float = 0.0
    phase: float = 0.0
    kind: ActionKind = ActionKind.DAMAGE
    subject: int = -1
    attacker: int = -1
    # Ledger linkage
    aidx: int = -1
    trigger: int = -1
    trigger_event_id: str | None = None
    event: dict | None = None
    # Damage fields
    amount: float = 0.0
    damage_type: str = ""
    raw_formula: Any = None
    raw_damage: float = 0.0
    grievous: Any = None
    wound: tuple | None = None
    reactive: bool = False
    execute_threshold_ratio: float = 0.0
    execute_source: str = ""
    deferred: bool = False
    deferred_batch_id: str | None = None
    redirected: bool = False
    redirect_holder_health_ratio: float = 0.0
    redirect_original_damage: float = 0.0
    redirect_cancelled: bool = False
    # Attack metadata
    is_ability: bool = False
    basic_attack: bool = False
    ability_instance: Any = None
    source_key: str = ""
    source: str = ""
    event_id: str | None = None
    sequence: Any = None
    immobilized: bool = False
    cc_kind: str = ""
    baseline_effective_armor: float | None = None
    baseline_effective_mr: float | None = None
    # Heal fields
    healing_category: str = ""
    amount_formula: Any = None
    requires_holder_health_ratio: float = 0.0
    requires_damage_free_seconds: float = 0.0
    overheal_to_temporary_health: bool = False
    temporary_health_duration: float = 0.0
    overheal_to_shield: bool = False
    overheal_shield_cap: float = 0.0
    overheal_shield_duration: float = 0.0
    defy_trigger_id: str | None = None
    # Timed / state kinds
    duration: float = 0.0
    health_ratio: float = 0.0
    # Stat buff fields
    bonus_attack_speed_percent: float = 0.0
    ability_power: float = 0.0
    ability_haste: float = 0.0
    on_hit_magic_damage: float = 0.0
    # Damage-modifier fields
    persistent: bool = False
    multiplier: float = 1.0
    damage_reduction: bool = False
    next_event_only: bool = False
    armor_reduction_percent: float = 0.0
    mr_reduction_percent: float = 0.0
    resistance_type: str = ""
    owner: str = ""
    # Utility fields
    utility_kind: str = ""
    gold_amount: float = 0.0
    ward_uses: float = 0.0
    duration_set: bool = False


# ---------------------------------------------------------------------------
# Ordering helpers (shared by the receipt composition and the compiler)
# ---------------------------------------------------------------------------


def event_sequence(event: Mapping[str, Any]) -> int:
    """Return a stable source sequence for simultaneous event ordering."""
    value = event.get("sequence", event.get("_trigger_sequence", 0))
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def participant_order(participant_id: Any) -> tuple[int, str]:
    """Use a deterministic side order when sources share a timestamp."""
    text = str(participant_id or "")
    if text == "main":
        return (0, text)
    if text.startswith("ally:"):
        return (1, text)
    if text.startswith("enemy:"):
        return (2, text)
    return (3, text)


# --- Fast compiled-damage construction (issue #171) ------------------------
# The optimizer compiles tens of thousands of damage actions per request;
# the generated NamedTuple ``__new__`` costs ~1.5 us parsing 60+ keyword
# defaults per call.  Copying a default row and assigning the compiler's
# sixteen damage fields by index builds the identical tuple in under half
# that.  The indices derive from ``_fields`` at import time, so reordering
# or extending the NamedTuple cannot desynchronize them.
_ACTION_DEFAULT_ROW = list(SurvivalAction())
_INDEX = SurvivalAction._fields.index
_I_SORT_KEY = _INDEX("sort_key")
_I_TIME = _INDEX("time")
_I_KIND = _INDEX("kind")
_I_SUBJECT = _INDEX("subject")
_I_ATTACKER = _INDEX("attacker")
_I_AIDX = _INDEX("aidx")
_I_AMOUNT = _INDEX("amount")
_I_DAMAGE_TYPE = _INDEX("damage_type")
_I_RAW_FORMULA = _INDEX("raw_formula")
_I_RAW_DAMAGE = _INDEX("raw_damage")
_I_GRIEVOUS = _INDEX("grievous")
_I_WOUND = _INDEX("wound")
_I_SOURCE_KEY = _INDEX("source_key")
_I_SOURCE = _INDEX("source")
_I_EVENT_ID = _INDEX("event_id")
_I_SEQUENCE = _INDEX("sequence")


def compiled_damage_action(
    sort_key: tuple,
    time: float,
    kind: ActionKind,
    subject: int,
    attacker: int,
    aidx: int,
    amount: float,
    damage_type: str,
    raw_formula: Any,
    raw_damage: float,
    grievous: Any,
    wound: tuple | None,
    source_key: str,
    source: str,
    event_id: str,
    sequence: Any,
) -> SurvivalAction:
    """Build a compiler damage action without keyword-default parsing.

    Exactly ``SurvivalAction(**those sixteen fields)``: every other field
    keeps its class default (``phase=0.0`` and ``reactive=False`` included,
    matching what the compiler always passes for damage packets).
    """
    row = _ACTION_DEFAULT_ROW.copy()
    row[_I_SORT_KEY] = sort_key
    row[_I_TIME] = time
    row[_I_KIND] = kind
    row[_I_SUBJECT] = subject
    row[_I_ATTACKER] = attacker
    row[_I_AIDX] = aidx
    row[_I_AMOUNT] = amount
    row[_I_DAMAGE_TYPE] = damage_type
    row[_I_RAW_FORMULA] = raw_formula
    row[_I_RAW_DAMAGE] = raw_damage
    row[_I_GRIEVOUS] = grievous
    row[_I_WOUND] = wound
    row[_I_SOURCE_KEY] = source_key
    row[_I_SOURCE] = source
    row[_I_EVENT_ID] = event_id
    row[_I_SEQUENCE] = sequence
    return tuple.__new__(SurvivalAction, row)


def action_key(
    event_time: float,
    phase: float,
    participant_id: str,
    event: Mapping[str, Any],
) -> tuple[Any, ...]:
    """Order event phases without ever comparing payload dictionaries.

    This is the survival walk's total order.  Pair packets precompute it per
    event (``_sk``) because the walk re-sorts the same roster events for
    every optimizer candidate.

    The ``_event_id`` component is a dead tie-break for engine damage
    events: ``sequence`` is unique per pair fight, and events from
    different pairs already differ at the source/participant components.
    ``_pair_packet``'s pair-local event numbering depends on that — if an
    engine event ever arrived without its sequence, the packet builder
    rejects that instead of letting numbering become order-relevant.
    """
    source_id = event.get("attacker", participant_id)
    return (
        float(event_time),
        float(phase),
        event_sequence(event),
        *participant_order(source_id),
        str(participant_id),
        str(event.get("_event_id", "")),
        str(event.get("source", event.get("source_key", ""))),
    )


# ---------------------------------------------------------------------------
# Event classification (receipt adapter)
# ---------------------------------------------------------------------------

_HEAL_KINDS = frozenset({"heal", "regen"})
_UTILITY_KINDS = frozenset(
    {"on_hit_magic", "movement", "cleanse", "slow", "economy", "vision"}
)


def _classify_heal(event: Mapping[str, Any]) -> ActionKind:
    """Heal-kind classification with the sourced transition markers."""
    if event.get("overheal_to_shield"):
        return ActionKind.OVERHEAL_SHIELD
    if event.get("healing_category"):
        return ActionKind.ICHOR_CONVERT
    return ActionKind.HEAL


# The fixed-kind dispatch table for classification; the phase-gated and
# damage-path branches below cannot ride a flat lookup.
_STANDALONE_KINDS = {
    "revive": ActionKind.REVIVE,
    "stasis": ActionKind.STASIS,
    "invulnerability": ActionKind.INVULNERABLE,
    "untargetable": ActionKind.UNTARGETABLE,
    "spell_shield": ActionKind.SPELL_SHIELD,
    "shield": ActionKind.SHIELD,
    "stat_buff": ActionKind.STAT_BUFF,
    "damage_modifier": ActionKind.DAMAGE_MODIFIER,
    "on_hit_magic": ActionKind.ON_HIT_MAGIC,
    "movement": ActionKind.UTILITY,
    "cleanse": ActionKind.UTILITY,
    "slow": ActionKind.UTILITY,
    "economy": ActionKind.UTILITY,
    "vision": ActionKind.UTILITY,
}


def _classify_prefetched(
    event: Mapping[str, Any],
    phase: float,
    kind: str,
    execute_ratio_raw: Any,
    deferred_raw: Any,
    redirected_raw: Any,
    raw_formula: Any,
    raw_damage: float,
    grievous_duration: float,
) -> ActionKind:
    """The one classification implementation, over prefetched hot fields."""
    standalone = _STANDALONE_KINDS.get(kind)
    if standalone is not None:
        return standalone
    if phase == -1 and kind == "temporary_health":
        return ActionKind.TEMP_HEALTH
    if phase == -1 and kind in _HEAL_KINDS:
        return _classify_heal(event)
    if phase == 1:
        # The authoritative walk's phase-1 branch heals every remaining
        # packet unconditionally (the kind gate exists only in phase -1);
        # engine self-heals may carry arbitrary kind strings such as
        # ``champion_ability``.
        return _classify_heal(event)
    if phase < 0:
        # Phase -1 kinds outside the enumerated support transitions are
        # silent no-ops in the authoritative walk; every kind authored
        # today is classified above.
        return ActionKind.UTILITY
    # Damage path.  The plain-damage marker mirrors the compiler: no live
    # health formula, no Grievous pack, no wound.
    if execute_ratio_raw is not None:
        return ActionKind.EXECUTE
    if deferred_raw:
        return ActionKind.DEFER
    if redirected_raw:
        return ActionKind.REDIRECT
    if grievous_duration <= 0.0 and not (callable(raw_formula) and raw_damage > 0):
        return ActionKind.PLAIN_DAMAGE
    return ActionKind.DAMAGE


def classify_event_kind(event: Mapping[str, Any], phase: float) -> ActionKind:
    """Map one receipt event (dict + phase) to its typed action kind.

    Mirrors the authoritative walk's dispatch precedence exactly: revive,
    combat-state transitions, spell shield, shield, stat buff, damage
    modifier, utility kinds, then the phase-gated recovery branches, then
    damage (with execute/deferred/redirect markers and the plain-damage
    fast-branch classification).
    """
    get = event.get
    return _classify_prefetched(
        event,
        phase,
        str(get("kind", "")),
        get("execute_threshold_ratio"),
        get("_deferred"),
        get("_redirected"),
        get("raw_formula"),
        float(get("raw_damage", 0.0) or 0.0),
        float(get("grievous_duration", 0.0) or 0.0),
    )


def survival_action_from_event(
    event: Mapping[str, Any],
    phase: float,
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
    kind = _classify_prefetched(
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
    defy_id = get("_defy_trigger_id")
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
        trigger_event_id=str(trigger_id) if trigger_id else None,
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
        execute_source=str(get("execute_source", "The Collector")),
        deferred=bool(deferred_raw),
        deferred_batch_id=str(batch_id) if batch_id else None,
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
        event_id=str(event_id) if event_id is not None else None,
        sequence=get("sequence"),
        immobilized=bool(
            get("immobilized")
            or get("crowd_control")
            or get("hard_cc")
            or cc_kind.lower()
            in {"immobilize", "stun", "root", "knockup", "suppression"}
        ),
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
        defy_trigger_id=str(defy_id) if defy_id else None,
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
        owner=str(get("owner", "")),
        utility_kind=kind if kind in _UTILITY_KINDS else "",
        gold_amount=float(get("gold_amount", 0.0) or 0.0),
        ward_uses=float(get("ward_uses", 0.0) or 0.0),
        duration_set="duration" in event,
    )


# The heal amount lives in ``amount`` for recovery packets; the damage
# amount lives in ``damage``.  ``survival_action_from_event`` above merges
# both into one ``amount`` field; this alias documents that convention.
__all__ = [
    "ActionKind",
    "SurvivalAction",
    "action_key",
    "classify_event_kind",
    "event_sequence",
    "participant_order",
    "survival_action_from_event",
]
