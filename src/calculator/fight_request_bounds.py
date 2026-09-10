"""What a public fight request may say, and the readers that coerce it."""

import math
import re
from collections.abc import Mapping
from typing import Any

from . import item_effects, minion_stats
from .auto_attack_policy import AUTO_ATTACK_UPTIME_MODE_CALCULATED
from .cast_dependency import BASE_CAST_SLOTS
from .fight.config import MINION_SOURCED_TARGET_FIELDS, sourced_minion_target
from .rank_allocation import SPECIAL_CHAMPIONS, rank_rules
from .request_parsing import request_string

DEFAULT_TARGET: dict[str, float] = {
    "health": 1000.0,
    "bonus_health": 0.0,
    "armor": 100.0,
    "mr": 100.0,
}


DEFAULT_FIGHT_DURATION = 8.0


DEFAULT_AUTO_ATTACK_UPTIME = 0.8


DEFAULT_AUTO_ATTACK_UPTIME_MODE = AUTO_ATTACK_UPTIME_MODE_CALCULATED


DEFAULT_FIGHT_MODE = "one_rotation"


ONE_ROTATION_DURATION = 5.0


MAX_ROTATIONS = 6


# The roster bounds live beside the other public request bounds rather than in
# scenario.py, which composes the roster: a support packet's teammate index is
# checked here and the roster lists are parsed there, and one of the two would
# otherwise spell the other's limit as a literal.
MAX_ENEMIES = 5


MAX_ALLIES = 4


PUBLIC_INPUT_LIMITS: dict[str, tuple[float, float]] = {
    # The prototype exposes up to six five-second rotations, so a timed
    # request must be able to represent the complete sequential window.
    "fight_duration": (1.0, 30.0),
    "auto_attack_uptime": (0.0, 1.0),
    "target_health": (1.0, 10_000.0),
    "target_bonus_health": (0.0, 10_000.0),
    "target_armor": (0.0, 500.0),
    "target_bonus_armor": (0.0, 500.0),
    "target_mr": (0.0, 500.0),
}


_PUBLIC_FIGHT_MODES = frozenset({"one_rotation", "time_based", "timed", "auto_only"})


def rank_allocation_contract() -> dict[str, object]:
    """Return the backend-owned manual rank rules for public clients."""
    return {
        "default": "manual",
        "by_champion": dict.fromkeys(SPECIAL_CHAMPIONS, "manual"),
        "default_rules": rank_rules(""),
        "rules_by_champion": {name: rank_rules(name) for name in SPECIAL_CHAMPIONS},
    }


def _bounded_request_float(
    data: Mapping[str, Any],
    key: str,
    default: float | None,
    *,
    allow_none: bool = False,
) -> float | None:
    """Parse one finite public number inside its UI-supported range.

    The one home for the public number policy, kept here rather than beside
    its integer and string siblings in :mod:`request_parsing`: every number
    the public API accepts is a key of ``PUBLIC_INPUT_LIMITS``, so its range
    is read from that table by name and can never be passed in, and a caller
    has nowhere to spell a second range for the same field.
    """
    value = data.get(key, default)
    if allow_none and value is None:
        return None
    minimum, maximum = PUBLIC_INPUT_LIMITS[key]
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{key} must be finite")
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{key} must be between {minimum:g} and {maximum:g}")
    return parsed


def validate_cast_order_shape(cast_order: object, *, field: str) -> None:
    """Reject a requested cast order no champion could satisfy.

    Champion-agnostic on purpose: a cast order is a non-empty list of distinct
    ability slots.  Which slots a champion actually offers is a property of its
    parsed kit, checked once against ``cast_dependency.orderable_slots`` in
    :meth:`FightParams.validate_for_champion`, so no slot set is spelled here.
    """
    if cast_order is None:
        return
    if not isinstance(cast_order, list) or any(
        not isinstance(slot, str) for slot in cast_order
    ):
        raise ValueError(f"{field} must be a list of ability slots")
    if not cast_order:
        raise ValueError(f"{field} must name at least one ability slot")
    if len(set(cast_order)) != len(cast_order):
        raise ValueError(f"{field} must not repeat an ability slot")


# How the cast vocabulary spells a castable slot: a base slot letter, plus an
# optional charge index for a second or third cast of the same ability.  The
# letters come from BASE_CAST_SLOTS rather than a second hand list, and "P" is
# excluded because the passive is not castable and has its own spellings.
CAST_SLOT_SPELLING = re.compile(
    "^[" + "".join(slot for slot in BASE_CAST_SLOTS if slot != "P") + "][0-9]*$"
)


def cast_slot_surface(
    ability_damages: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    """The parsed rows a cast order schedules, keyed as the cast vocabulary spells them.

    The parse publishes the passive as ``"passive"`` and the cast vocabulary as
    ``"P"``, and both spellings occur across the roster.  Cast slots are told
    apart from rider rows (``W_frenzy``, ``R_onhit``) by spelling, never by the
    ``recast_of`` stamp: reading the stamp here would filter an unstamped ``Q2``
    out as a rider and silently drop it from a requested order, which is what
    ``cast_dependency.orderable_slots`` fails closed on downstream.
    """
    surface: dict[str, Mapping[str, Any]] = {}
    for slot, entry in ability_damages.items():
        if not isinstance(entry, Mapping):
            continue
        if slot in ("P", "passive"):
            surface["P"] = entry
        elif CAST_SLOT_SPELLING.match(slot):
            surface[slot] = entry
    return surface


def _request_target_class(data: Mapping[str, Any]) -> str:
    """Read the public target-class selector, failing closed.

    Omitting the key selects the champion-class fight.  A supplied value must
    match a :data:`item_effects.TARGET_CLASSES` spelling exactly, with no case
    folding and no plurals, so the request layer and ``FightConfig``'s own guard
    share one spelling contract rather than the request layer widening what the
    kernel accepts.
    """
    value = request_string(data, "target_class", item_effects.DEFAULT_TARGET_CLASS)
    if value not in item_effects.TARGET_CLASSES:
        raise ValueError(
            "target_class must be "
            + " or ".join(item_effects.TARGET_CLASSES)
            + f"; got {value!r}"
        )
    return value


def _request_minion_type(data: Mapping[str, Any], target_class: str) -> str:
    """Read which lane minion the request faces, failing closed.

    Omitting the key keeps the target caller-shaped, which is what every
    request that predates the sourced stat block does. Naming a type requires
    the minion target class, so a champion-class body cannot quietly carry a
    minion selector that nothing would apply.
    """
    value = request_string(data, "minion_type")
    if not value:
        return ""
    if target_class != item_effects.MINION_TARGET_CLASS:
        raise ValueError(
            f"minion_type={value!r} requires target_class="
            f"{item_effects.MINION_TARGET_CLASS!r}; got {target_class!r}"
        )
    if value not in minion_stats.MINION_TYPES:
        raise ValueError(
            "minion_type must be one of "
            + ", ".join(minion_stats.MINION_TYPES)
            + f"; got {value!r}"
        )
    return value


def _request_target_durability(
    data: Mapping[str, Any], minion_type: str
) -> dict[str, float | None]:
    """The fight target's durability fields, from the request or the source.

    Without a named minion type these are read from the body exactly as they
    always are. With one, the fields ``MINION_SOURCED_TARGET_FIELDS`` names
    come from that minion's own character record instead, and supplying one
    of them in the body is REFUSED rather than overridden or ignored — a
    request must not be able to claim a sourced minion and then hand it a
    different target's health.

    ``target_mr`` is never sourced: no minion character record states a magic
    resistance, so it stays a request value for every target class.
    """
    supplied: dict[str, float | None] = {
        "target_health": _bounded_request_float(
            data, "target_health", DEFAULT_TARGET["health"]
        ),
        "target_bonus_health": _bounded_request_float(
            data, "target_bonus_health", DEFAULT_TARGET["bonus_health"]
        ),
        "target_armor": _bounded_request_float(
            data, "target_armor", DEFAULT_TARGET["armor"]
        ),
        "target_bonus_armor": _bounded_request_float(
            data, "target_bonus_armor", None, allow_none=True
        ),
    }
    if not minion_type:
        return supplied
    conflicting = sorted(set(data) & set(MINION_SOURCED_TARGET_FIELDS))
    if conflicting:
        raise ValueError(
            f"minion_type={minion_type!r} sources "
            + ", ".join(sorted(MINION_SOURCED_TARGET_FIELDS))
            + f"; remove {', '.join(conflicting)} from the request. "
            "Only target_mr is still yours to supply for a minion, because "
            "no minion character record states a magic resistance."
        )
    supplied.update(sourced_minion_target(minion_type))
    return supplied
