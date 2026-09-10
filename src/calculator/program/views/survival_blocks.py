"""The state blocks a survival row publishes only when the state has them."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..precision import round_field
from ..walk import SurvivalFold
from .leaf import LeafBlock


def _optional_time(field: str, value: float | None) -> float | None:
    """A published timestamp, or ``None`` where the walk recorded none: not zero."""
    return None if value is None else round_field(field, value)


def _combat_state_blocks(
    state: Mapping[str, Any], row: dict[str, Any], leaf: LeafBlock
) -> None:
    """The two stack-ledger sub-blocks, whose leaf names collide.

    ``dynamic_bonus_magic_resistance`` is published under both Force of
    Nature and Jak'Sho, which is why the precision registry keys these on
    ``block.name`` rather than on the bare leaf -- and why the two blocks get
    their own leaf paths in the ``dispositions`` map for the same reason.
    """
    force: dict[str, Any] = {}
    row["force_of_nature"] = force
    inner = leaf.nested(force, "force_of_nature")
    inner.raw("stacks", int(state["force_stacks"]))
    inner.measured(
        "stacks_until",
        round_field("force_of_nature.stacks_until", state["force_stacks_until"]),
    )
    inner.structure("events", list(state["force_stack_events"]))
    inner.measured(
        "dynamic_bonus_magic_resistance",
        round_field(
            "force_of_nature.dynamic_bonus_magic_resistance",
            float(state.get("dynamic_bonus_magic_resistance", 0.0) or 0.0),
        ),
    )
    jaksho: dict[str, Any] = {}
    row["jaksho"] = jaksho
    inner = leaf.nested(jaksho, "jaksho")
    inner.raw("stacks", int(state["jaksho_stacks"]))
    inner.structure("events", list(state["jaksho_stack_events"]))
    inner.measured(
        "dynamic_bonus_armor",
        round_field(
            "jaksho.dynamic_bonus_armor",
            float(state.get("dynamic_bonus_armor", 0.0) or 0.0),
        ),
    )
    inner.measured(
        "dynamic_bonus_magic_resistance",
        round_field(
            "jaksho.dynamic_bonus_magic_resistance",
            float(state.get("dynamic_bonus_magic_resistance", 0.0) or 0.0),
        ),
    )


def _rune_state_blocks(
    state: Mapping[str, Any], row: dict[str, Any], leaf: LeafBlock
) -> None:
    """The two rune lifecycle sub-blocks (Guardian, Aftershock).

    Their own block rather than part of :func:`_combat_state_blocks`, because
    the two answer different questions: those are item stack ledgers whose
    leaf names collide, these are rune windows whose names do not.
    """
    guardian: dict[str, Any] = {}
    row["guardian"] = guardian
    inner = leaf.nested(guardian, "guardian")
    inner.measured(
        "cooldown_until",
        round_field("guardian.cooldown_until", state["guardian_cooldown_until"]),
    )
    inner.structure("trigger_events", list(state["guardian_trigger_events"]))
    aftershock: dict[str, Any] = {}
    row["aftershock"] = aftershock
    inner = leaf.nested(aftershock, "aftershock")
    inner.measured("until", round_field("aftershock.until", state["aftershock_until"]))
    inner.measured(
        "bonus_armor",
        round_field("aftershock.bonus_armor", float(state["aftershock_bonus_armor"])),
    )
    inner.measured(
        "bonus_magic_resistance",
        round_field(
            "aftershock.bonus_magic_resistance",
            float(state["aftershock_bonus_magic_resistance"]),
        ),
    )
    inner.structure("trigger_events", list(state["aftershock_trigger_events"]))


def _cleanse_receipt(
    state: Mapping[str, Any], fold: SurvivalFold, participant_id: str
) -> dict[str, Any]:
    """One recipient row's published cleanse receipt.

    The decision fields (removed/rejected controls, downtime before) were
    frozen at activation; ``intervals_after`` and ``downtime_after`` name the
    FINAL interval ledger instead, so a control landing after the activation
    -- a cleanse creates no immunity -- is visible in the receipt rather than
    implied by its absence.  The union itself is the walk's
    (:attr:`~..walk.SurvivalFold.crowd_control_downtime`); this only names it.
    """
    receipt = dict(state["cleanse"])
    # The walk-level intervals mirror the survival row's interval shape
    # (kind/start/end/source + recipient), so naming them here keeps them
    # identical to ``crowd_control_intervals`` by construction.
    receipt["intervals_after"] = [
        {"recipient": participant_id, **event}
        for event in state["crowd_control_intervals"]
    ]
    receipt["downtime_after"] = round_field(
        "cleanse.downtime_after", fold.crowd_control_downtime
    )
    return receipt


# The champion-authored state blocks the walk writes only when the mechanic
# fired: Dr. Mundo's passive lifecycle and Olaf's Ragnarok window.  An absent
# key means "this never happened", which is why nothing publishes a neutral
# row for them -- a reader must ask with a membership check rather than a
# ``.get(..., {})`` that cannot tell the two apart.
_CONDITIONAL_STATE_BLOCKS = (
    "passive_cost",
    "canister",
    "pickup",
    "passive_cooldown",
    "passive_state",
    "ragnarok_immunity",
)
