"""A `target_debuff`'s uptime, its resistance reduction, and the two shapes that gate it."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ...ability_atoms import ability_field
from ...resistance import apply_magic_penetration, reduce_resistance
from ..resists import Resists


def _ability_mr(resists: Resists, vile_decay_stacks: int) -> float:
    """Effective MR one ability's magic damage is mitigated by.

    Malignance's Hatefog only applies once the rotation has accepted an R
    cast (``resists.ult_cast``), and Bloodletter's Curse deepens the
    reduction per Vile Decay stack.
    """
    if resists.mr_shred is None or vile_decay_stacks <= 0:
        return resists.effective_mr
    base = resists.reduced_mr if resists.ult_cast else resists.base_mr
    reduced = reduce_resistance(
        base,
        resists.mr_shred.reduction_percent(vile_decay_stacks),
    )
    return apply_magic_penetration(
        max(reduced, min(0.0, base)),
        resists.magic_pen_flat,
        resists.ability_magic_pen_percent,
    )


def _debuff_coverage(
    cast_times: Sequence[float],
    duration: float,
    fight_duration: float,
) -> float:
    """Share of the fight a duration-limited ``target_debuff`` is up.

    Every shred in the game expires (Kog'Maw Q 4s, Jayce R 5s, ...), but
    resistances here are one scalar for the whole fight. Rather than
    re-price every consumer per instant, the shred is applied
    time-weighted by this coverage: a debuff up for half the fight
    shreds half as much. That is exact at full and zero coverage, and
    within a fraction of a percent between (resistance -> damage is
    mildly non-linear), while a champion who REFRESHES the debuff before
    it lapses tiles the fight and keeps the full shred.

    Overlapping windows count once — refreshing a debuff extends it, it
    does not stack.
    """
    if duration <= 0 or fight_duration <= 0:
        return 1.0
    windows = sorted(
        (start, min(start + duration, fight_duration))
        for start in cast_times
        if start < fight_duration
    )
    covered = 0.0
    open_start = open_end = 0.0
    for start, end in windows:
        if open_end == 0.0 or start > open_end:
            covered += open_end - open_start
            open_start, open_end = start, end
        else:
            open_end = max(open_end, end)
    covered += open_end - open_start
    return min(1.0, covered / fight_duration)


def _apply_target_shred(
    resists: Resists,
    debuff: dict[str, Any],
    fraction: float = 1.0,
) -> None:
    """Apply a ``target_debuff``'s resistance reduction to the target.

    Supported keys: ``armor_reduction_percent`` / ``mr_reduction_percent``
    (Kog'Maw Q, Briar Q, Jarvan IV Q) and ``armor_reduction_flat`` /
    ``mr_reduction_flat`` (Corki E), each naming the FULL reduction.
    ``fraction`` applies one equal share of it — the ramp seam below.
    """
    armor_pct = ability_field(debuff, "armor_reduction_percent", form="target_debuff")
    armor_flat = (
        ability_field(debuff, "armor_reduction_flat", form="target_debuff") * fraction
    )
    if armor_pct or armor_flat:
        resists.shred_armor(armor_pct * fraction, armor_flat)
    mr_pct = ability_field(debuff, "mr_reduction_percent", form="target_debuff")
    mr_flat = (
        ability_field(debuff, "mr_reduction_flat", form="target_debuff") * fraction
    )
    if mr_pct or mr_flat:
        resists.shred_mr(mr_pct * fraction, mr_flat)


@dataclass
class _ShredRamp:
    """A ``target_debuff`` that stacks up across its own ability's hits.

    Corki's Gatling Gun applies one shred stack per tick to a cap: tick 1
    lands unshredded, tick 2 against one stack, and so on. Declared as
    ``"stacks": N`` on the debuff, this fires one Nth of the reduction
    after each of the ability's first N HITS — counting every hit of
    every part, so a champion declares its ticks as one part with a
    ``count`` and never has to mirror the engine's loop. First cast only:
    the engine's shreds are permanent, so later casts land against the
    full stack. Stages that never fire — fewer hits than stacks, or an
    uncast ability — land together via ``apply_remainder``, matching the
    unramped "shred applies after the ability" rule.
    """

    resists: Resists
    debuff: dict[str, Any]
    stacks: int
    ability_mr: Callable[[], float]
    fired: int = 0

    def stage(self, current_mr: float) -> float:
        """Apply one stack after a hit; return MR for the hits after it."""
        if self.fired >= self.stacks:
            return current_mr
        self.fired += 1
        _apply_target_shred(self.resists, self.debuff, 1.0 / self.stacks)
        return self.ability_mr()

    # Stages that already fired did so DURING the ability's own hits, at full
    # strength.  ``coverage`` is the share outliving the ability, so this
    # SETTLES the total at it rather than adding a flat remainder — exactly
    # ``(stacks - fired) / stacks`` at full coverage.  The settlement is signed
    # and so hands reduction back, exact for a flat shred and not a percent one.
    def apply_remainder(self, coverage: float = 1.0) -> None:
        """Top the shred up to its lasting share of the reduction."""
        _apply_target_shred(
            self.resists, self.debuff, coverage - self.fired / self.stacks
        )


@dataclass
class _ThresholdShred:
    """A resistance reduction that begins only after a hit threshold.

    Some abilities do not ramp their reduction one share at a time: Garen's
    Judgment, for example, applies the full 25% armor reduction only after the
    sixth spin.  Keeping this separate from ``_ShredRamp`` prevents a
    percentage reduction from being approximated as six smaller reductions.
    """

    resists: Resists
    debuff: dict[str, Any]
    threshold_hits: int
    fired: bool = False

    def stage(self, current_mr: float) -> float:
        """Count one authored hit and apply the full shred at the threshold."""
        if not self.fired:
            self._hits += 1
            if self._hits >= self.threshold_hits:
                self.fired = True
                _apply_target_shred(self.resists, self.debuff)
        return self.resists.effective_mr

    def apply_remainder(self, coverage: float = 1.0) -> None:
        """Do not apply a threshold shred that never reached its threshold."""

    _hits: int = 0


def _make_shred_ramp(
    resists: Resists,
    ability_info: dict[str, Any],
    vile_decay_stacks: int,
) -> _ShredRamp | _ThresholdShred | None:
    """Build the hit ramp/threshold for a target debuff, else None."""
    debuff = ability_info.get("target_debuff")
    threshold_hits = (
        int(ability_field(debuff, "threshold_hits", form="target_debuff"))
        if debuff
        else 0
    )
    if threshold_hits > 0:
        if debuff.get("stacks"):
            raise ValueError(
                f"{ability_field(ability_info, 'name')!r}: target_debuff cannot "
                "declare both threshold_hits and stacks"
            )
        return _ThresholdShred(
            resists=resists,
            debuff=debuff,
            threshold_hits=threshold_hits,
        )
    stacks = int(ability_field(debuff, "stacks", form="target_debuff")) if debuff else 0
    if stacks <= 0:
        return None
    if debuff.get("armor_reduction_percent") or debuff.get("mr_reduction_percent"):
        raise ValueError(
            f"{ability_field(ability_info, 'name')!r}: a ramped target_debuff must "
            "reduce resistances by a FLAT amount — percent stages compound "
            "multiplicatively and cannot be split into equal shares"
        )
    return _ShredRamp(
        resists=resists,
        debuff=debuff,
        stacks=stacks,
        ability_mr=lambda: _ability_mr(resists, vile_decay_stacks),
    )
