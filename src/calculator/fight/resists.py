"""The target's resistances against this attacker's penetration, and what spends them."""

from dataclasses import dataclass

from ..ability_spec import DamageClass
from ..interpreters import resistance_shred
from ..resistance import (
    apply_armor_penetration,
    apply_magic_penetration,
    apply_resistance,
    reduce_resistance,
)


@dataclass
class Resists:
    """Target resistances and the attacker's penetration, resolved together.

    Owns the penetration math that fight setup resolves and that later
    steps re-resolve when something changes mid-fight: stat-buff ultimates
    that grant pen (Ambessa R), target shreds (Kog'Maw Q), and the swing
    count Terminus' Juxtaposition ramps over.

    The stat sheet carries Terminus' pen at maximum stacks; the fight serves
    ONE pen to every packet, ability and auto alike, with that max-stack
    share replaced by the ramp's Cesàro mean over the fight's autos
    (``effective_*_pen_percent``).  Juxtaposition's Dark stacks are a
    champion stat, so a cast meets the same penetration a swing does.

    The ``effective_*`` fields hold the currently-resolved resistances
    that damage math applies.  ``effective_mr`` follows ``ult_cast``:
    Malignance's Hatefog MR reduction applies only once the rotation
    accepts an R cast, so both the pre- and post-ult variants are kept and
    the outcome picks.
    """

    # Attacker penetration
    magic_pen_flat: float
    magic_pen_percent: float
    armor_pen_percent: float
    flat_armor_pen: float
    # Terminus Juxtaposition: the stat sheet's max-stack pen and the
    # fight's averaged ramp that replaces it
    has_terminus: bool
    terminus_stat_pen: float
    terminus_avg_pen: float
    # Target resistances (mutated by shreds)
    target_armor: float
    base_mr: float
    reduced_mr: float  # base MR minus Malignance Hatefog reduction
    malignance_mr_reduction: float
    bc_reduction: float  # Black Cleaver % armor reduction
    mr_shred: "resistance_shred.ShredSlot | None"
    # Percent BONUS armor penetration (Last Whisper family, K'Sante All
    # Out) and the target's base/bonus armor split (None = split unknown;
    # the quick-scenario total-pen reading applies).
    armor_pen_bonus_percent: float = 0.0
    target_bonus_armor: float | None = None
    # Target passives such as Amumu's Tantrum reduce each physical raw
    # damage instance before resistance mitigation. The cap is a fraction
    # of that instance, not a cap on the total fight damage.
    physical_damage_flat_reduction: float = 0.0
    physical_damage_flat_reduction_cap: float = 0.0
    # Resolved values (recomputed by the resolve/shred methods below)
    effective_armor_pen_percent: float = 0.0
    effective_magic_pen_percent: float = 0.0
    reduced_armor: float = 0.0
    effective_armor: float = 0.0
    effective_mr_pre_ult: float = 0.0
    effective_mr_post_ult: float = 0.0
    effective_mr: float = 0.0
    # The rotation's R outcome: set once an R cast is accepted.  An R the
    # resource budget refused, a cast order without R, or an auto-only
    # window never sets it, and ``effective_mr`` stays pre-ult.
    ult_cast: bool = False
    # The rotation's final Bloodletter's Curse stacks.  Set once the
    # rotation is over, because the damage that outlives it (autos,
    # on-hits, item procs, burns) meets the debuff at full depth; the
    # rotation's own hits read their per-hit count through ``_ability_mr``.
    shred_stacks: int = 0

    def mark_ult_cast(self) -> None:
        """Record the rotation's accepted R cast; Hatefog's zone is open."""
        self.ult_cast = True
        self._select_mr()

    def apply_shred_stacks(self, stacks: int) -> None:
        """Record the rotation's final Vile Decay stacks; the served MR follows."""
        self.shred_stacks = stacks
        self._select_mr()

    def _select_mr(self) -> None:
        """Serve the MR the rotation's outcome leaves behind.

        The one home for ``effective_mr``, so the order the outcome's two
        halves land in cannot change it: ``ult_cast`` picks Hatefog's
        reduction, ``shred_stacks`` deepens whichever it picked, and every
        method that re-resolves the pen ends here.
        """
        if self.mr_shred is None or self.shred_stacks <= 0:
            self.effective_mr = (
                self.effective_mr_post_ult
                if self.ult_cast
                else self.effective_mr_pre_ult
            )
            return
        base = self.reduced_mr if self.ult_cast else self.base_mr
        stacked = max(
            reduce_resistance(base, self.mr_shred.reduction_percent(self.shred_stacks)),
            min(0.0, base),
        )
        self.effective_mr = apply_magic_penetration(
            stacked, self.magic_pen_flat, self.effective_magic_pen_percent
        )

    def _served_pen(self, stat_pen: float) -> float:
        """The stat sheet's pen with Terminus' max-stack share replaced by the ramp's mean."""
        if not self.has_terminus:
            return stat_pen
        stripped = max(0.0, stat_pen - self.terminus_stat_pen)
        if self.terminus_avg_pen <= 0:
            return stripped
        return 1.0 - (1.0 - stripped) * (1.0 - self.terminus_avg_pen)

    def resolve_magic(self) -> None:
        """Recompute the served magic pen and effective MR."""
        self.effective_magic_pen_percent = self._served_pen(self.magic_pen_percent)
        self.effective_mr_pre_ult = apply_magic_penetration(
            self.base_mr, self.magic_pen_flat, self.effective_magic_pen_percent
        )
        self.effective_mr_post_ult = apply_magic_penetration(
            self.reduced_mr, self.magic_pen_flat, self.effective_magic_pen_percent
        )
        self._select_mr()

    def resolve_armor(self) -> None:
        """Recompute the served armor pen and effective armor."""
        self.effective_armor_pen_percent = self._served_pen(self.armor_pen_percent)
        self._resolve_armor_from_target()

    def _resolve_armor_from_target(self) -> None:
        """Re-derive reduced/effective armor from the target's armor."""
        self.reduced_armor = reduce_resistance(
            self.target_armor, self.bc_reduction * 100.0
        )
        self.effective_armor = apply_armor_penetration(
            self.reduced_armor,
            self.flat_armor_pen,
            self.effective_armor_pen_percent,
            self.armor_pen_bonus_percent,
            bonus_armor=self.target_bonus_armor,
        )

    def _resolve_mr_from_target(self) -> None:
        """Re-derive reduced/effective MR from the target's base MR."""
        # Malignance's Hatefog is a flat reduction. Its historical floor
        # at 0 is kept for a positive-MR target, but it must never LIFT
        # an MR that a shred already drove negative.
        self.reduced_mr = max(
            reduce_resistance(
                self.base_mr, reduction_flat=self.malignance_mr_reduction
            ),
            min(0.0, self.base_mr),
        )
        self.effective_mr_pre_ult = apply_magic_penetration(
            self.base_mr, self.magic_pen_flat, self.effective_magic_pen_percent
        )
        self.effective_mr_post_ult = apply_magic_penetration(
            self.reduced_mr, self.magic_pen_flat, self.effective_magic_pen_percent
        )
        self._select_mr()

    def shred_armor(
        self, reduction_percent: float = 0.0, reduction_flat: float = 0.0
    ) -> None:
        """Reduce the target's armor and re-resolve armor.
        Percent shreds (Kog'Maw Q) scale the armor that is left; flat shreds
        (Corki E) subtract from it.  Reduction, unlike penetration, has no
        floor: negative armor amplifies damage."""
        self.target_armor = reduce_resistance(
            self.target_armor, reduction_percent, reduction_flat
        )
        self._resolve_armor_from_target()

    def shred_mr(
        self, reduction_percent: float = 0.0, reduction_flat: float = 0.0
    ) -> None:
        """Reduce the target's magic resist and re-resolve MR.  Same rules as
        :meth:`shred_armor`: flat reduction may take MR below zero, where it
        amplifies damage."""
        self.base_mr = reduce_resistance(
            self.base_mr, reduction_percent, reduction_flat
        )
        self._resolve_mr_from_target()


def _mitigate(
    raw_damage: float,
    damage_type: str,
    resists: Resists,
    magic_amp: float,
    *,
    ability_mr: float | None = None,
) -> float:
    """Apply the fight's resolved resistance and magic-only amplifier.

    ``ability_mr`` is the MR one ability's own hits meet; absent it, the
    fight's resolved MR answers.
    """
    damage_class = DamageClass.named(damage_type)
    if damage_class is DamageClass.MAGIC:
        mr = resists.effective_mr if ability_mr is None else ability_mr
        return apply_resistance(raw_damage, mr) * magic_amp
    if damage_class is DamageClass.PHYSICAL:
        reduced_raw = _apply_physical_damage_reduction(raw_damage, resists)
        return apply_resistance(reduced_raw, resists.effective_armor)
    return raw_damage


def _resistance_met_fields(
    damage_type: str,
    resists: Resists,
    *,
    ability_mr: float | None = None,
) -> dict[str, float]:
    """The ``resistance_met`` an event states, off what :func:`_mitigate` reads.

    The same class dispatch and the same two arguments, so the field cannot
    name a resistance the mitigation did not apply.  Empty for a class no
    resistance answers for: a packet that met none states no field rather
    than a zero it did not meet.
    """
    damage_class = DamageClass.named(damage_type)
    met = (
        None
        if damage_class is None
        else damage_class.resistance_term(
            armor=resists.effective_armor,
            magic_resistance=(
                resists.effective_mr if ability_mr is None else ability_mr
            ),
        )
    )
    return {} if met is None else {"resistance_met": float(met)}


def _apply_physical_damage_reduction(raw_damage: float, resists: Resists) -> float:
    """Apply a target's capped flat reduction to one physical raw instance."""
    if raw_damage <= 0.0:
        return raw_damage
    flat = float(resists.physical_damage_flat_reduction or 0.0)
    cap = float(resists.physical_damage_flat_reduction_cap or 0.0)
    if flat <= 0.0 or cap <= 0.0:
        return raw_damage
    return max(0.0, raw_damage - min(flat, raw_damage * cap))
