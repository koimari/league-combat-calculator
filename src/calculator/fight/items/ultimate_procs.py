"""The damage zone an ultimate cast opens (Malignance, Zeke's Convergence)."""

from ...ability_atoms import ability_field
from ..resists import _mitigate, _resistance_met_fields
from ..results import RotationResult
from ..state import FightState, _damage_inputs
from .cast_procs import _proc_declaration


def _add_ultimate_proc_damage(
    state: FightState,
    rotation: RotationResult,
) -> None:
    """Add the zone an accepted ultimate cast opens."""
    resists = state.resists
    for effect in state.declared.cast_procs.ultimate_procs:
        # The zone opens at R1, so the accepted cast timeline decides: a
        # window that holds no R cast (``auto_only``, a custom order without
        # R, an R the resource budget refused) never opens it, and the row
        # is absent rather than a coarse total — the same fail-closed shape
        # as Command's amp.
        r_info = state.ability_damages.get("R")
        r_cast_times = [
            float(event["time"])
            for event in rotation.cast_events
            if event.get("slot") == "R"
        ]
        if r_info is None or not r_cast_times:
            continue
        source = effect.source
        raw = source.raw_damage(_damage_inputs(state))

        # Hatefog zone refreshes on each R dash.  Effective duration is
        # the time from R1 to R_last plus the base zone duration.
        hatefog_duration = effect.duration
        r_total_casts = ability_field(r_info, "cast_instances")
        r_dash_spread = (r_total_casts - 1) * 0.5  # ~0.5s between dashes
        effective_hatefog = r_dash_spread + hatefog_duration
        raw *= effective_hatefog / hatefog_duration

        ult_proc_mitigated = _mitigate(raw, "magic", resists, state.magic_amp)

        state.breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": ult_proc_mitigated,
            "damage_type": source.damage_type,
            "pair_preview_of": source.previewed_mechanic(),
            # The zone's duration scaling is already folded into ``raw``
            # above, so what the declaration states is this packet's own
            # pre-mitigation magnitude and not the item's base figure.
            "declared": _proc_declaration(source, raw, False),
        }
        # Stamp the proc at the cast timeline's first R cast.
        state.breakdown[source.breakdown_key]["damage_events"] = [
            {
                "time": min(r_cast_times),
                "damage": ult_proc_mitigated,
                "damage_type": source.damage_type,
                "declared": _proc_declaration(source, raw, False),
                # The class ``_mitigate`` above was handed, not the row's:
                # the zone is priced as magic whatever the source spells.
                **_resistance_met_fields("magic", resists),
            }
        ]
        state.total_damage += ult_proc_mitigated
