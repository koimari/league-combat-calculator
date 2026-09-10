"""The order the survival walk consumes actions in, and the row it compiles one into.

``action_key``, ``participant_order``, ``event_sequence`` and
``event_timestamp`` build the total order; ``compiled_damage_action`` builds the
row, keyed by the ``_I_*`` field indices of :class:`SurvivalAction`.  The sort
key is part of an action's identity, so the receipt composition and the score
compiler build the same keys from here.

The rest of this interface lives beside it, one concept per module: the typed
action, its kind and its live amplification in :mod:`typed_action`, what an
event *is* and which modifier classes it declares in :mod:`classify`, when a
transition resolves in :mod:`phases`, and the kernel's four event references in
:mod:`event_slots`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .phases import TransitionRank, ordering_slot
from .pricing import DeclaredPacket
from .typed_action import ActionKind, LiveAmp, SurvivalAction

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


def event_timestamp(event: Mapping[str, Any]) -> float:
    """Return one raw event row's timestamp, the walk's ordering axis.

    A row that states no time is at 0.0, the fight's own origin; a row
    that states an unusable one is a stop, because no total order can
    place it.
    """
    value = event.get("time", 0.0)
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("event time must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError("event time must be finite")
    return parsed


def participant_order(participant_id: object) -> tuple[int, str]:
    """Use a deterministic side order when sources share a timestamp."""
    text = str(participant_id or "")
    if text == "main":
        return (0, text)
    if text.startswith("ally:"):
        return (1, text)
    if text.startswith("enemy:"):
        return (2, text)
    return (3, text)


# --- Fast compiled-damage construction -------------------------------------
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
_I_EVENT_SLOT = _INDEX("event_slot")
_I_SEQUENCE = _INDEX("sequence")
_I_LIVE_AMP = _INDEX("live_amp")
_I_DECLARED = _INDEX("declared")
_I_IS_ABILITY = _INDEX("is_ability")
_I_BASIC_ATTACK = _INDEX("basic_attack")
_I_BASELINE_ARMOR = _INDEX("baseline_effective_armor")
_I_BASELINE_MR = _INDEX("baseline_effective_mr")
_I_IMMOBILIZED = _INDEX("immobilized")
_I_CC_KIND = _INDEX("cc_kind")
_I_CC_DURATION = _INDEX("cc_duration")
_I_SKILLSHOT = _INDEX("skillshot")
_I_DAMAGE_OVER_TIME = _INDEX("damage_over_time")
_I_AREA_DAMAGE = _INDEX("area_damage")
_I_ABILITY_INSTANCE = _INDEX("ability_instance")


def compiled_damage_action(
    sort_key: tuple,
    time: float,
    kind: ActionKind,
    subject: int,
    *,
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
    event_slot: int,
    sequence: Any,
    live_amp: LiveAmp | None,
    declared: DeclaredPacket | None,
    is_ability: bool,
    basic_attack: bool,
    baseline_effective_armor: float | None,
    baseline_effective_mr: float | None,
    immobilized: bool = False,
    cc_kind: str = "",
    cc_duration: float = 0.0,
    skillshot: bool = False,
    damage_over_time: bool = False,
    area_damage: bool = False,
    ability_instance: Any = None,
) -> SurvivalAction:
    """Build a compiler damage action without keyword-default parsing.

    Exactly ``SurvivalAction(**those twenty-eight fields)``: every other field
    keeps its class default, ``reactive=False`` and the phase included.  There is
    no ``_I_PHASE`` because the class default *is* ``TransitionRank.DAMAGE``; read
    the rank at :class:`SurvivalAction`, not here.

    Six parameters have no default, because each has a neutral value
    indistinguishable from an unasked question, and a compiler that forgot one
    would score a build silently missing a term:

    * ``live_amp`` is the amplification the packet earned.  Every call site
      states it, ``None`` included.
    * ``declared`` is the declaration the walk prices.  A compiler that omitted
      it would score the family at the pair engine's number after that row had
      left the total: priced twice on one path and not at all on the other.
    * ``is_ability`` and ``basic_attack`` are how a packet says it was delivered
      (:func:`attack_class_of`).  At their ``False`` default every compiled
      packet classifies as ``OTHER``, and a modifier declaring all three attack
      classes reaches only rows whose ``source_key`` is ``auto_attacks``.
    * The two resistance baselines are the pair fight's own final effective
      armour and magic resistance, which a resistance-reducing modifier re-prices
      its packet against.  ``None`` is the honest "this fight published no such
      figure", receipted as ``support_resistance_reduction_unavailable`` rather
      than as a made-up mitigation ratio.

    The delivery facts a certified packet carries (``immobilized``, ``cc_kind``,
    ``cc_duration``, ``skillshot``, ``damage_over_time``, ``area_damage``,
    ``ability_instance``) keep neutral defaults instead: they are the *absence* of
    a declaration rather than a number a compiler could forget, and each is inert.
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
    row[_I_EVENT_SLOT] = event_slot
    row[_I_SEQUENCE] = sequence
    row[_I_LIVE_AMP] = live_amp
    row[_I_DECLARED] = declared
    row[_I_IS_ABILITY] = is_ability
    row[_I_BASIC_ATTACK] = basic_attack
    row[_I_BASELINE_ARMOR] = baseline_effective_armor
    row[_I_BASELINE_MR] = baseline_effective_mr
    row[_I_IMMOBILIZED] = immobilized
    row[_I_CC_KIND] = cc_kind
    row[_I_CC_DURATION] = cc_duration
    row[_I_SKILLSHOT] = skillshot
    row[_I_DAMAGE_OVER_TIME] = damage_over_time
    row[_I_AREA_DAMAGE] = area_damage
    row[_I_ABILITY_INSTANCE] = ability_instance
    return tuple.__new__(SurvivalAction, row)


#: The walk's total order for one action: time, ordering slot, sequence,
#: participant order (side, id), participant id, event id, source.
ActionSortKey = tuple[float, TransitionRank, int, int, str, str, str, str]


def action_key(
    event_time: float,
    phase: TransitionRank,
    participant_id: str,
    event: Mapping[str, Any],
) -> ActionSortKey:
    """The survival walk's total order over event phases, never comparing
    payload dictionaries; pair packets precompute it per event (``_sk``).

    Element 1 is the rank's :func:`ordering_slot`, so one pair of ranks
    resolves together and ``compile.py``'s inline sort tuples stay comparable
    with this one.  ``_event_id`` is a dead tie-break for engine damage
    events: ``sequence`` is unique per pair fight, so an event without one is
    rejected rather than letting numbering become order-relevant.  NaN/inf is
    the one time ``float()`` accepts that no total order can place, and every
    action reaches this function, so the one guard is here.
    """
    time_value = float(event_time)
    if not math.isfinite(time_value):
        raise ValueError(
            f"action_key: event time must be finite, got {event_time!r} "
            f"(event_id={event.get('_event_id')!r}); a non-finite timestamp "
            "cannot establish a stable total order"
        )
    source_id = event.get("attacker", participant_id)
    return (
        time_value,
        ordering_slot(phase),
        event_sequence(event),
        *participant_order(source_id),
        str(participant_id),
        str(event.get("_event_id", "")),
        str(event.get("source", event.get("source_key", ""))),
    )


# ---------------------------------------------------------------------------
# Event classification (receipt adapter)
# ---------------------------------------------------------------------------


# The two helpers above are public because the one constructor lives in
# ``program.compile.action_from_event``, which classifies over prefetched
# hot fields and resolves a packet's declared class sets: a leading
# underscore on a name another layer must call is a boundary nobody can
# see.  What stays here is the vocabulary that constructor converts *into*.


__all__ = ["action_key", "event_sequence", "event_timestamp", "participant_order"]
