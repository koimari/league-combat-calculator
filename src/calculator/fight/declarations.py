"""What this build declares before anything is walked, resolved through its rules."""

from dataclasses import dataclass

from ..interpreters import (
    cast_proc,
    charged_strike,
    periodic,
    resistance_shred,
    secondary_target,
)


@dataclass(frozen=True)
class BuildDeclarations:
    """The declared families this build brings, each resolved through its rule.

    These stay off the registry's build projection on purpose: a projection
    field that defaulted to an empty tuple would price a whole family at zero
    with nothing saying so.
    """

    # The clock-driven strikes, split by cadence.  One field rather than three
    # because the three cadences are one declared family.
    periodics: periodic.PeriodicSlots
    # The cast-triggered procs, split by shape.
    cast_procs: cast_proc.CastProcSlots
    # The charged strikes, split by shape.
    charged_strikes: charged_strike.ChargedStrikeSlots
    # The declared armour shred.  A keystone that re-prices the auto count
    # (Hail of Blades, Lethal Tempo) re-averages it from the same slot the
    # opening resistances were resolved from.
    armor_shred: resistance_shred.ShredSlot | None
    secondary_target_bolts: secondary_target.SecondaryTargetSlot | None
