"""The survival kernel, driven the way the packet tests drive it.

The kernel's public shape is a walk plus the view that reads it, and every
packet test wants the pair, so the composition lives here once rather than
in each file:

* :func:`simulate_survival` runs the walk over a combatant list and returns
  the view's payload, keyed by participant; and
* :func:`survival_of` picks one participant's block out of a fight result.

This is a test helper, not a test module: it holds no assertions.
"""

from src.calculator.participant_timeline import _simulate_survival as _walk
from src.calculator.program.build import roster_program
from src.calculator.program.views.survival import survival as _survival_view


def simulate_survival(combatants, *args, **kwargs):
    """The survival view over one walk of *combatants*."""
    combatant_list = list(combatants)
    return _survival_view(
        roster_program(combatant_list),
        _walk(combatant_list, *args, **kwargs),
    )


def survival_of(result, participant_id="main"):
    """One participant's survival block out of a fight result."""
    return next(
        row["survival"]
        for row in result["participants"]
        if row["participant_id"] == participant_id
    )
