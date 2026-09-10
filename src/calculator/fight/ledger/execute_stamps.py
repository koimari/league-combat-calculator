"""The execution threshold each authored packet carries, stamped on the ledger."""

from collections.abc import Iterable
from typing import Any

from ...ability_atoms import ability_field, ability_payload
from ...interpreters import damage_routing
from ..state import FightState, _held_owners


def _stamp_execute_thresholds(state: FightState, damage_events: Iterable[Any]) -> None:
    """Stamp each ledger row with the execute threshold that terminates it.

    Execute thresholds are terminal target-state transitions.  An ability
    threshold applies only to its own cast and an item threshold to every
    authored packet, so when both apply the larger one is kept.
    """
    item_execute = damage_routing.declared_execution(_held_owners(state))
    for event in damage_events:
        if not isinstance(event, dict):
            continue
        source_key = str(event["source_key"])
        ability = ability_payload(state.ability_damages, source_key)
        # P4: the on-hit passive row's events carry source_key
        # "on_hit_ability_passive" — resolve the passive entry's own
        # execute stamp (Zeri's Living Battery).
        if not ability and source_key == "on_hit_ability_passive":
            ability = ability_payload(state.ability_damages, "passive")
        ability_ratio = float(ability_field(ability, "execute_threshold_ratio"))
        item_ratio = float(item_execute.threshold) if item_execute is not None else 0.0
        if ability_ratio >= item_ratio and ability_ratio > 0:
            event["execute_threshold_ratio"] = ability_ratio
            event["execute_source"] = str(
                ability.get("execute_source") or ability.get("name") or source_key
            )
            # Which producer decided this stamp.  The roster walk owns
            # the item rider and clears the stamps it owns; a cast's
            # own threshold was never that rider's to clear, and
            # without this marker the two are indistinguishable by
            # name alone.
            event["execute_declared_by_cast"] = True
        elif item_ratio > 0:
            event["execute_threshold_ratio"] = item_ratio
            event["execute_source"] = item_execute.owner
