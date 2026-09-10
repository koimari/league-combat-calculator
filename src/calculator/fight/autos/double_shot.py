"""A second attack per swing at a reduced AD ratio (Akshan's Dirty Fighting)."""

import random
from collections.abc import Sequence
from typing import Any

from ...ability_atoms import ability_field
from ..mitigation import _mitigate_basic_attack_swing
from ..resists import _resistance_met_fields
from ..state import FightState


def _add_double_shot(
    state: FightState,
    double_shot_info: dict[str, Any],
    attack_damage: float,
    auto_times: Sequence[float],
) -> float:
    """Price the second shot on every swing and publish its row.

    Each shot rolls (or expects) its own crit at the reduced AD ratio, so
    the row keeps its own crit split beside the auto row's.  Returns the
    mitigated total added to the fight.
    """
    ds_ratio = ability_field(double_shot_info, "ad_ratio", form="double_shot")
    crit_chance = state.crit_chance
    crit_multiplier = state.crit_multiplier
    ds_ad = attack_damage * ds_ratio
    ds_crits = 0
    double_shot_total = 0.0
    double_shot_events: list[dict[str, Any]] = []
    for i in range(state.num_auto_attacks):
        if state.deterministic:
            event_damage = crit_chance * _mitigate_basic_attack_swing(
                state,
                ds_ad * crit_multiplier,
                critical_strike=True,
            ) + (1.0 - crit_chance) * _mitigate_basic_attack_swing(state, ds_ad)
        else:
            ds_crit = random.random() < crit_chance
            if ds_crit:
                ds_crits += 1
                raw_ds = ds_ad * crit_multiplier
            else:
                raw_ds = ds_ad
            event_damage = _mitigate_basic_attack_swing(
                state,
                raw_ds,
                critical_strike=ds_crit,
            )
        double_shot_total += event_damage
        double_shot_events.append(
            {
                "time": auto_times[i] if i < len(auto_times) else 0.0,
                "damage_type": "physical",
                "damage": event_damage,
                "event_precision": "exact",
                **_resistance_met_fields("physical", state.resists),
            }
        )

    state.breakdown["double_shot"] = {
        "name": ability_field(double_shot_info, "name", form="double_shot"),
        "count": state.num_auto_attacks,
        "num_crits": ds_crits,
        "num_non_crits": state.num_auto_attacks - ds_crits,
        "total_damage": double_shot_total,
        "damage_type": "physical",
        "damage_events": double_shot_events,
        "event_phase": "auto",
    }
    return double_shot_total
