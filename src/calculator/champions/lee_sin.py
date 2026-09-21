"""Lee Sin: full-entry reviewed module with the two-stage Q.

Q is two stages: Sonic Wave marks the target and the recast, Resonating Strike,
consumes the mark for physical damage increased by 0 to 100% on the target's
missing health, interpolated between the cached Minimum and Maximum Physical
Damage rows.  The two-stage Q is the default under ``q_recast``, priced at the
target's live missing-health fraction, so a fresh target takes the sourced
minimum and a low one up to the maximum.
P (Flurry) stays a documented no-damage row, R's collision splash is irrelevant
to a single target, and the Safeguard W shield is authored by the support
scanner.
"""

from typing import Any

from ..ability_spec import DamagePart
from .contract_vocabulary import coverage
from .engine import SlotCtx, build_parser
from .inputs import bool_option
from .module_helpers import REVIEWED_MODULE_ASSUMPTIONS, no_damage, ranked_slot
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named
from .slotlib import simple_damage
from .source_receipts import load_champion_sources

# HARDCODED: verify on patch updates — the recast lands ~0.5s after the
# wave (Sonic Wave's 0.25s cast time plus the recast reaction); the
# wiki only sources the 3-second recast window, so this is the authored
# cadence, not a cached number.
_RECAST_TIME_OFFSET = 0.5


@ranked_slot
def _sonic_wave_and_resonating_strike(
    ctx: SlotCtx, wave: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Q: Sonic Wave hit + the Resonating Strike recast on the mark.

    The recast reads the cached Minimum/Maximum Physical Damage rows of
    Q[1] and interpolates by the target's missing-health fraction at each
    cast, so the fight prices the two-stage combo honestly.
    """

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
MODULE_CC = {"Q": "none", "E": "slow", "R": "knockback", "P": "none", "W": "none"}

parse_abilities = build_parser(SLOTS, "Lee Sin", cc_kinds=MODULE_CC)

OPTIONS: list[dict[str, Any]] = [
    bool_option(
        "q_recast",
        True,
        label="Resonating Strike recast follows Sonic Wave",
        rotation={"role": "self_state", "slot": "Q"},
    ),
]

ASSUMPTIONS = [
    *list(REVIEWED_MODULE_ASSUMPTIONS),
    "Q is two stages: Sonic Wave's Physical Damage row plus the Resonating Strike "
    "recast.",
    "The recast reads Q[1]'s Minimum and Maximum rows, 0% : 100% by target missing "
    "health at each cast.",
    "Its 0.5s recast cadence is authored from the sourced 3s recast window.",
    "With q_recast off only Sonic Wave is priced; the recast's mark and dash are "
    "state Q does not model.",
    "P (Flurry) is an attack-haste and energy row with no enemy damage; R's collision "
    "splash needs a crowd.",
    "W's Safeguard shield is authored by the support scanner.",
]

SOURCES = load_champion_sources("Lee Sin")
MODULE_COVERAGE = coverage(no_damage="PW")
