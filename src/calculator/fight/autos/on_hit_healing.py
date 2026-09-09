"""Item heals that ride a basic attack: authored on-hit receipts and the first attack."""

from ... import item_effects
from ...interpreters.sustain import declared_sustain
from ...item_behavior import OnHitHealRule
from ..results import AutoAttackResult, OnHitResult
from ..state import FightState, _crit_profile
from .swing_schedule import _auto_attack_timestamps


def _add_on_hit_healing(
    state: FightState,
    autos: AutoAttackResult,
    on_hits: OnHitResult,
) -> None:
    """Emit exact item-heal receipts for authored basic-attack on-hits.

    Cull's Reap heal is attached to the auto stream, including sourced
    Rageblade phantom and double-shot applications.  Ability-carried on-hit
    copies, pets, and other un-timestamped carriers remain withheld rather
    than receiving an invented time.
    """
    slot = declared_sustain(
        sorted({item_effects.resolved_item_name(item) for item in state.items}),
        OnHitHealRule,
    )
    if slot is None or state.num_auto_attacks <= 0:
        return
    swing_times = _auto_attack_timestamps(state)
    if len(swing_times) != state.num_auto_attacks:
        return

    application_times: list[float] = []
    double_shot_extra = state.num_auto_attacks if autos.double_shot_info else 0
    for auto_index, swing_time in enumerate(swing_times):
        application_times.append(swing_time)
        if auto_index in on_hits.phantom_hit_autos:
            application_times.append(swing_time)
        if double_shot_extra:
            application_times.append(swing_time)

    if not application_times:
        return
    amount = slot.value("amount")
    state.breakdown[f"heal_{slot.owner}"] = {
        "name": f"{slot.owner} (Reap)",
        "count": len(application_times),
        "amount_per_proc": amount,
        "total_amount": amount * len(application_times),
        "unit": "health",
        "heal_events": [
            {
                "time": event_time,
                "amount": amount,
                "trigger_source": "auto_attacks",
            }
            for event_time in application_times
        ],
        "event_phase": "heal",
    }


def _add_first_auto_healing(state: FightState) -> None:
    """Emit Sundered Sky's first-attack heal with a live missing-HP formula."""
    effect = _crit_profile(state).forced_crit
    if effect is None or (
        effect.heal_base_ad_ratio <= 0.0 and effect.heal_missing_health_ratio <= 0.0
    ):
        return
    auto_row = state.breakdown.get("auto_attacks")
    damage_events = auto_row.get("damage_events") if auto_row else None
    if not isinstance(damage_events, list) or not damage_events:
        return
    try:
        event_time = float(damage_events[0]["time"])
    except (KeyError, TypeError, ValueError):
        return
    base_ad = float(state.champion_stats["base_attack_damage"])
    # Lightshield Strike heals 100% bAD (melee) / 50% bAD (ranged) — the
    # ranged variant is sourced from the wiki's {{rd|100%|50%}} (pass 17).
    heal_ratio = (
        effect.heal_base_ad_ratio_ranged
        if state.is_melee is False
        else effect.heal_base_ad_ratio
    )
    base_amount = heal_ratio * base_ad
    if base_amount <= 0.0:
        return

    def amount_formula(
        current_health: float,
        maximum_health: float,
        base_amount: float = base_amount,
        missing_ratio: float = effect.heal_missing_health_ratio,
    ) -> float:
        return base_amount + missing_ratio * max(0.0, maximum_health - current_health)

    state.breakdown[f"heal_{effect.owner}"] = {
        "name": f"{effect.owner} (Lightshield Strike)",
        "count": 1,
        "amount_per_proc": base_amount,
        "total_amount": base_amount,
        "unit": "health",
        "heal_events": [
            {
                "time": event_time,
                "amount": base_amount,
                "amount_formula": amount_formula,
                "trigger_source": "auto_attacks",
                "overheal_to_temporary_health": (
                    effect.temporary_health_duration > 0.0
                ),
                "temporary_health_duration": effect.temporary_health_duration,
            }
        ],
        "event_phase": "heal",
    }
