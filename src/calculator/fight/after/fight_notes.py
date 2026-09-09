"""The notes a finished fight publishes about its conditional assumptions."""

from ... import item_effects
from ..results import OnHitResult, RotationResult
from ..state import FightState, _crit_profile


def _collect_fight_notes(
    state: FightState,
    rotation: RotationResult,
    on_hits: OnHitResult,
) -> None:
    """Collect the notes documenting conditional item and timeline assumptions."""
    notes = state.notes
    notes.extend(state.damage_effects.conditional_notes)

    if state.target_class != item_effects.DEFAULT_TARGET_CLASS:
        armed = state.class_restricted_strikes
        armed_names = ", ".join(sorted(effect.source.item_name for effect in armed))
        notes.append(
            f"Target class '{state.target_class}': the sourced class-restricted "
            f"item branches are armed ({armed_names or 'none in this build'}). "
            "Named boundary — champion ABILITY class clauses (Nasus Q stacks, "
            "Cho'Gath Feast, Ezreal R's minion row) are not adjudicated, and "
            "ability-carried on-hit applications do not carry the class-"
            "restricted branch; the target's stats stay caller-supplied, not "
            "a sourced minion stat block."
        )

    timeline = state.stack_timeline
    if timeline is not None and timeline.buff_windows:
        uptime = sum(end - start for start, end in timeline.buff_windows)
        notes.append(
            f"{timeline.buff_name}: {len(timeline.buff_windows)} window(s) "
            f"from the stack timeline — +{timeline.buff_bonus_ad:.0f} bonus AD, "
            f"first at {timeline.buff_windows[0][0]:.2f}s, {uptime:.2f}s "
            f"committed (a window runs its full duration past the fight's "
            f"end, like the DoT it rides)."
        )

    if (
        rotation.has_navori
        and rotation.navori_refund > 0
        and rotation.autos_per_second > 0
    ):
        refund = _crit_profile(state).cooldown_refund
        assert refund is not None
        notes.append(
            f"{refund.owner}: basic ability CDs reduced by "
            f"{rotation.navori_refund:.0%} per auto attack "
            f"({rotation.autos_per_second:.2f} autos/sec effective)."
        )

    if on_hits.phantom_hit_count > 0:
        phantom_hit = state.damage_effects.phantom_hit
        assert phantom_hit is not None
        notes.append(
            f"{phantom_hit.item_name}: {on_hits.phantom_hit_count} phantom hit(s) — "
            f"all on-hit effects apply an additional time on autos "
            f"#{', #'.join(str(a + 1) for a in sorted(on_hits.phantom_hit_autos))}."
        )
