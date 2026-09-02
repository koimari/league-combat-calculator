"""Lee Sin — full-entry reviewed CP10.3 module with the two-stage Q.

E9-2 gap fix: the reviewed-packets asset carries Resonating Strike
(120-360 + 180% bonus AD, Q[1]) as a Q variant while the batch pinned
Lee Sin's Q to the Sonic Wave row only.  In-game the combo is two
stages: Sonic Wave marks the target, and the recast Resonating Strike
consumes the mark to deal physical damage increased by 0% : 100% (based
on target's missing health) — interpolated between the cached Minimum
and Maximum Physical Damage rows.  The two-stage Q is now the default
(``q_recast`` option, on) with the recast priced at the target's live
missing-health fraction, so a fresh target takes the sourced minimum and
a low target takes up to the maximum.

P (Flurry) stays a documented no-damage row; R's collision splash is
single-target-irrelevant; the Safeguard W shield is authored by the
E8c support scanner.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .inputs import bool_option
from .module_contract import coverage
from .module_helpers import REVIEWED_MODULE_ASSUMPTIONS, no_damage
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
)
from .source_receipts import load_champion_sources

# HARDCODED: verify on patch updates — the recast lands ~0.5s after the
# wave (Sonic Wave's 0.25s cast time plus the recast reaction); the
# wiki only sources the 3-second recast window, so this is the authored
# cadence, not a cached number.
_RECAST_TIME_OFFSET = 0.5


def _sonic_wave_and_resonating_strike(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: Sonic Wave hit + the Resonating Strike recast on the mark.

    The recast reads the cached Minimum/Maximum Physical Damage rows of
    Q[1] and interpolates by the target's missing-health fraction at each
    cast, so the fight prices the two-stage combo honestly.
    """
    ranked = ctx.ranked("Q", 0)
    if ranked is None:
        return None
    wave, rank = ranked

    sonic = extract_named(wave, "Physical Damage", rank, ctx.stats, ctx.target)
    parts = [DamagePart("physical", sonic, time_offset=0.0)]
    total = sonic

    if bool(ctx.option("q_recast")):
        strike = ctx.ability("Q", 1)
        minimum = extract_named(
            strike, "Minimum Physical Damage", rank, ctx.stats, ctx.target
        )
        maximum = extract_named(
            strike, "Maximum Physical Damage", rank, ctx.stats, ctx.target
        )

        def recast_damage(missing_ratio: float) -> float:
            return minimum + (maximum - minimum) * missing_ratio

        parts.append(
            DamagePart(
                "physical",
                hp_scaled_damage=recast_damage,
                time_offset=_RECAST_TIME_OFFSET,
            )
        )
        total += minimum

    entry = damage_entry(
        ability_name(wave),
        rank,
        extract_cooldown(wave, rank),
        total,
        "physical",
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = (
        "Two-stage Q: Sonic Wave + Resonating Strike recast (Minimum/Maximum "
        "Physical Damage rows interpolated by target missing health); "
        f"recast cadence {_RECAST_TIME_OFFSET:g}s authored."
    )
    return entry


SLOTS = {
    "P": lambda ctx: no_damage(
        ctx,
        name="Flurry",
        reason="Two-attack haste and energy restoration are attack-timeline state.",
    ),
    "Q": _sonic_wave_and_resonating_strike,
    "W": lambda ctx: no_damage(
        ctx,
        name="Safeguard",
        reason="Ally dash and shield are defensive/team state.",
    ),
    # Tempest smashes the ground beneath him and Dragon's Rage kicks the
    # target: one instance each, at the cast — the boundary claim that
    # carries MODULE_CC's reviewed kinds into the event ledger.
    "E": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": simple_damage(
        attr="Physical Damage", dmg_type="physical", event_order_certified="single_hit"
    ),
}

# Cached kit review: R "roots the target enemy champion over the cast
# time, then roundhouse kicks them ... and knock[s] them back up to 800
# units"; the E slot's second entry (Cripple) "slows nearby enemies marked
# by Tempest", which is the control the Tempest hit sets up; Q only marks
# and reveals.  P and W deal no damage.
MODULE_CC = {"Q": "none", "E": "slow", "R": "knockback"}

parse_abilities = build_parser(SLOTS, "Lee Sin", cc_kinds=MODULE_CC)

OPTIONS: list[dict[str, Any]] = [
    bool_option("q_recast", True, label="Resonating Strike recast follows Sonic Wave"),
]

ASSUMPTIONS = [
    *list(REVIEWED_MODULE_ASSUMPTIONS),
    "Q is the two-stage combo: Sonic Wave (Physical Damage row) plus the "
    "Resonating Strike recast, which reads Q[1]'s Minimum/Maximum "
    "Physical Damage rows and interpolates by the target's missing-health "
    "fraction at each cast (0% : 100% based on missing health); the "
    "recast cadence (0.5s) is authored from the 3s recast window",
    "With q_recast off the module prices Sonic Wave alone; the recast's "
    "mark consumption and dash are otherwise the only state the Q entry "
    "does not model",
    "P (Flurry) is an attack-haste/energy row — no enemy damage; R's "
    "collision splash is single-target-irrelevant; the Safeguard W shield "
    "is authored by the E8c support scanner.",
]

SOURCES = load_champion_sources("Lee Sin")
MODULE_COVERAGE = coverage(no_damage="PW")
