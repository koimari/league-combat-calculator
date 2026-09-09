"""The execution threshold a declared execute displays, as a row worth no damage."""

from ...interpreters import damage_routing
from ..state import FightState, _held_owners


def _add_execute_display(state: FightState) -> None:
    """Add The Collector's execute-threshold display row.

    The execute damage is NOT added to the total; the row displays the HP
    threshold at which the target would be executed.
    """
    execute = damage_routing.declared_execution(_held_owners(state))
    if execute is not None:
        collector_threshold = state.target_health * execute.threshold
        threshold_pct = (
            collector_threshold / state.target_health * 100
            if state.target_health
            else 0.0
        )
        state.breakdown["execute"] = {
            "name": f"{execute.owner} (Execute)",
            "total_damage": 0.0,
            "damage_type": "true",
            "execution_threshold_hp": collector_threshold,
            "detail": (
                f"{execute.owner} Execution Threshold: "
                f"{collector_threshold:.0f} HP "
                f"({threshold_pct:.0f}% of {state.target_health:.0f})"
            ),
            "damage_display": f"{collector_threshold:.0f} HP",
            "informational": True,
        }
