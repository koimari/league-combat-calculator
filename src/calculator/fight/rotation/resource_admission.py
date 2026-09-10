"""Which resource walk admits this fight's casts."""

from ...ability_atoms import ability_field
from ..results import CastPlan
from ..state import FightState
from .energy_walk import _apply_energy_resource_limits
from .mana_walk import _apply_mana_resource_limits


def _apply_resource_limits(state: FightState, plan: CastPlan) -> CastPlan:
    """Drop casts that cannot be paid for on the shared cast timeline.

    MANA fights run through the typed mana resource ledger
    (``resource_ledger``): one account owns regen ticks, external restores
    (Catalyst's Eternity, Essence Reaver's Spellblade), ability restores,
    cast spends, Manaflow's max-mana growth, and Lost Chapter's Enlighten.
    ENERGY fights run ``_apply_energy_resource_limits`` instead.  The account
    is certified for mana only and its maximum grows but never falls, so it
    cannot hold the temporary maximum Akali's W declares; and every mechanic
    the mana walk carries beyond the shared skeleton restores MANA, so an
    energy fight routed through it would have to switch each one off by kind.
    Both walks admit casts on the same skeleton (``_cast_admission_events``,
    ``_resource_timeline``, ``_CastAdmission``) and price a cast against the
    one ``actualizer_resource_cost_multiplier``.
    """
    if not state.enforce_resource_limits:
        # Direct engine callers may provide an intentionally partial stat
        # packet. The typed pipeline opts in after it has resolved the full
        # champion stat and ability packets.
        return plan
    resource_types = {
        str(ability_field(info, "resource_type"))
        for info in state.ability_damages.values()
    }
    resource_types.discard("NONE")
    resource_types.discard("RAGE")
    if not resource_types:
        return plan
    if len(resource_types) != 1:
        state.notes.append("Resource limits unavailable: mixed resource types.")
        return plan
    resource_type = next(iter(resource_types))
    if resource_type not in {"MANA", "ENERGY"}:
        state.notes.append(
            f"Resource limits unavailable for {resource_type.lower().replace('_', ' ')}."
        )
        return plan
    if resource_type == "ENERGY":
        return _apply_energy_resource_limits(state, plan)
    if any(
        float(ability_field(info, "resource_maximum_bonus") or 0.0) > 0.0
        for info in state.ability_damages.values()
    ):
        # Only the energy walk models a temporary maximum; the mana account's
        # maximum grows and never falls.  Fail closed rather than dropping a
        # declared mechanic silently (the only declarer today is ENERGY Akali).
        raise ValueError(
            "temporary resource maximum bonus is not modeled for MANA; "
            "route the kit through the energy walk or extend the ledger"
        )
    return _apply_mana_resource_limits(state, plan)
