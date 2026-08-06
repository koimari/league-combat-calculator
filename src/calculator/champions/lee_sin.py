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
from .reviewed_batch_03 import build_batch_module
from .slotlib import damage_entry, extract_cooldown, extract_named

_packet_parse, _packet_slots, _packet_assumptions, _packet_sources, _packet_options = (
    build_batch_module("Lee Sin")
)

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
    wave = ctx.ability("Q", 0)
    if wave is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None

    sonic = extract_named(wave, "Physical Damage", rank, ctx.stats, ctx.target)
    parts = [DamagePart("physical", sonic, time_offset=0.0)]
    total = sonic

    if bool(ctx.options.get("q_recast", True)):
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
        wave.get("name", "Sonic Wave"),
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


SLOTS = dict(_packet_slots)
SLOTS["Q"] = _sonic_wave_and_resonating_strike
parse_abilities = build_parser(SLOTS, "Lee Sin")

OPTIONS: list[dict[str, Any]] = [
    {
        "key": "q_recast",
        "type": "bool",
        "default": True,
        "label": "Resonating Strike recast follows Sonic Wave",
    },
]

ASSUMPTIONS = list(_packet_assumptions) + [
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

SOURCES = list(_packet_sources)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "no_damage") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
