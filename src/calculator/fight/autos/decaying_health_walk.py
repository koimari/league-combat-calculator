"""Pricing a proc formula that reads current health against a target that is losing it."""

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

from ... import item_effects
from ...ability_atoms import ability_field
from ..ledger.event_rows import _finite_numeric_receipt
from ..resists import Resists, _mitigate
from ..state import FightState


class StackingProc(NamedTuple):
    """One repeating strike's packet: what it declared, and what it was paid.

    Both halves ride together because a repeating strike re-reads the
    target's falling health per proc, so the two numbers are per packet and
    a caller holding only one of them would have to recover the other by
    dividing a mitigation back out — the ratio step the from-declaration
    pricing path exists to remove (umbrella Amendment L, Ruling 3).

    ``raw`` is pre-mitigation and already carries the pair-local factor the
    engine applies outside :func:`_mitigate`, which is the magnitude a
    declaration states; ``mitigated`` is what the pair engine's own row
    publishes.
    """

    raw: float
    mitigated: float


class OnHitProc(NamedTuple):
    """One current-health on-hit application: declared, and paid.

    :class:`StackingProc`'s shape for the other family that re-reads the
    target's falling health per packet.  Blade of the Ruined King is the one
    of the eight declared on-hit strikes whose magnitude moves between
    applications of the same fight, so its row's applications cannot share a
    single declared number and cannot recover one by dividing the row total
    by the hit count either — the two applications either side of a big auto
    attack are priced against different health.

    ``raw`` is pre-mitigation and already carries the on-hit effectiveness of
    the application that spent it, which is the magnitude a declaration
    states; ``mitigated`` is what the pair engine's own row publishes.
    """

    raw: float
    mitigated: float


@dataclass(slots=True)
class DecayingTarget:
    """The target's health as an ordered walk of the fight reads it.

    Every current-health formula prices against a health that falls as the
    fight runs, and this engine has TWO readings of "what has landed before
    this instant" that disagree.  A per-auto walk decays by INDEX: each auto
    subtracts its own swing plus the averaged per-hit share of the other
    on-hit effects, and a proc prices against the health left before its own
    auto settles.  :meth:`ledger_health` decays by TIMESTAMP: it sums the
    authored packets the shared ledger stamped strictly before the instant,
    so a packet stamped AT that instant, and every untimed row, is outside
    it.  The two answers are kept exactly as they are — the readings differ
    because the walks price different things, and unifying them here would
    move numbers rather than share code.
    """

    max_health: float
    current_health: float

    @classmethod
    def at_full(cls, max_health: float) -> "DecayingTarget":
        """A target the walk has not hit yet."""
        return cls(max_health, max_health)

    def inputs(
        self, base_inputs: item_effects.DamageInputs
    ) -> item_effects.DamageInputs:
        """The pricing inputs a proc landing right now reads."""
        return item_effects.DamageInputs(
            champion_stats=base_inputs.champion_stats,
            level=base_inputs.level,
            is_melee=base_inputs.is_melee,
            target_max_health=self.max_health,
            target_current_health=self.current_health,
        )

    def take_proc(self, mitigated: float) -> None:
        """A proc lands: the next proc on this same auto prices below it."""
        self.current_health -= mitigated

    def settle_auto(self, mitigated: float) -> None:
        """The auto and its siblings land and the walk settles at zero."""
        self.current_health -= mitigated
        self.current_health = max(self.current_health, 0)

    @staticmethod
    def ledger_health(state: "FightState", timestamp: float) -> float:
        """Target HP before the packets authored AT ``timestamp``.

        Current-health item formulas that hold a real swing time read the
        shared event ledger rather than the fight aggregate.  Untimed rows are
        deliberately ignored: they cannot justify a fabricated HP transition
        and remain an explicit coverage gap.
        """
        dealt = 0.0
        for row in state.breakdown.values():
            if not isinstance(row, (dict, Mapping)):
                continue
            events = row.get("damage_events")
            if not isinstance(events, list):
                continue
            for event in events:
                if not isinstance(event, (dict, Mapping)):
                    continue
                event_time = _finite_numeric_receipt(event.get("time"))
                damage = _finite_numeric_receipt(event.get("damage"))
                if (
                    event_time is not None
                    and damage is not None
                    and event_time < timestamp - 1e-9
                ):
                    dealt += max(0.0, damage)
        return max(0.0, float(state.target_health) - dealt)


class AutoSwings(NamedTuple):
    """The auto-attack stream an on-hit proc walk decays its target against.

    ``auto_damage_per_hit`` and ``other_on_hit_per_hit`` are the mitigated
    damage every swing lands beside the proc being priced, so the walk knows
    the target's live health at each proc.
    """

    target_health: float
    num_auto_attacks: int
    auto_damage_per_hit: float
    other_on_hit_per_hit: float
    resists: Resists
    magic_amp: float


def _simulate_stacking_on_hit_damage(
    effect: item_effects.StackingOnHitEffect,
    base_inputs: item_effects.DamageInputs,
    swings: AutoSwings,
    *,
    proc_autos: list[int],
    effectiveness: float = 1.0,
    target_basic_damage_multiplier: float = 1.0,
) -> list[StackingProc]:
    """Simulate a stacking proc whose formula reads decreasing target HP.

    Kraken's bonus damage scales with the target's missing health at
    the time of each proc: ``base * (1 + 0.75 * missing_ratio)``.
    This must be simulated per-auto because each auto (and its on-hit
    effects) reduces target HP, changing the missing ratio for later procs.

    Args:
        swings: The auto-attack stream to decay the target against.
        proc_autos: Sorted 0-indexed auto indices where the effect procs.
        effectiveness: On-hit effectiveness multiplier on each proc's raw
            damage (Azir soldiers proc at 50%).
        target_basic_damage_multiplier: Target-side percentage modifier for
            the rare item proc that the Wiki tags as basic damage.

    Returns:
        Each proc as a :class:`StackingProc` in ascending-auto order — the
        same order as sorted ``proc_autos`` — so callers can stamp per-swing
        damage events and the declaration each one carries.
    """
    if not proc_autos:
        return []

    # Convert proc list to a counter: how many procs fire on each auto
    proc_counts: dict[int, int] = Counter(proc_autos)

    target = DecayingTarget.at_full(swings.target_health)
    proc_damages: list[StackingProc] = []

    for i in range(swings.num_auto_attacks):
        procs_this_auto = proc_counts.get(i, 0)

        for _ in range(procs_this_auto):
            inputs = target.inputs(base_inputs)
            raw_damage = effect.source.raw_damage(inputs) * effectiveness
            mitigated = _mitigate(
                raw_damage,
                effect.source.damage_type,
                swings.resists,
                swings.magic_amp,
            )
            basic_share = 1.0
            if effect.source.basic_damage and effect.source.damage_type != "true":
                mitigated *= target_basic_damage_multiplier
                basic_share = target_basic_damage_multiplier
            proc_damages.append(StackingProc(raw_damage * basic_share, mitigated))
            target.take_proc(mitigated)

        # Reduce HP from auto attack + other on-hit damage
        target.settle_auto(swings.auto_damage_per_hit + swings.other_on_hit_per_hit)

    return proc_damages


def _hp_scaled_on_hit_raw(
    on_hit_data: Mapping[str, Any],
    target_health: float,
) -> Callable[[float], float]:
    """One application's raw damage at a target current HP.

    Two declared shapes read the same live health and so share one walk:
    a share of the target's CURRENT health floored at a minimum (Jarvan
    IV's Martial Cadence), and a flat amount amplified by the target's
    MISSING health — ``missing_health_amp`` 1.0 doubles at full missing
    health (Samira's Daredevil Impulse blade rider).
    """
    percent = on_hit_data.get("current_health_percent")
    if percent is not None:
        share = float(percent) / 100.0
        floor = float(ability_field(on_hit_data, "min_damage", form="on_hit"))
        return lambda current_hp: max(share * current_hp, floor)
    amount = float(ability_field(on_hit_data, "damage_per_hit", form="on_hit"))
    amp = float(ability_field(on_hit_data, "missing_health_amp", form="on_hit"))
    return lambda current_hp: amount * (
        1.0 + amp * (1.0 - current_hp / target_health if target_health > 0 else 1.0)
    )


def _simulate_hp_scaled_on_hit_procs(
    on_hit_data: dict[str, Any],
    swings: AutoSwings,
    *,
    proc_autos: list[int],
    effectiveness: float = 1.0,
) -> list[float]:
    """Price schedule-gated procs against the target's decayed live health.

    :func:`_hp_scaled_on_hit_raw` prices each proc at ``proc_autos``
    (0-indexed) before that auto's own damage settles — the same order
    as the stacking on-hit walk. Returns each proc's mitigated damage
    in proc order.
    """
    if not proc_autos:
        return []

    raw_for = _hp_scaled_on_hit_raw(on_hit_data, swings.target_health)
    dmg_type = ability_field(on_hit_data, "damage_type", form="on_hit")
    proc_set = set(proc_autos)

    target = DecayingTarget.at_full(swings.target_health)
    proc_damages: list[float] = []
    for i in range(swings.num_auto_attacks):
        if i in proc_set:
            raw_damage = raw_for(target.current_health) * effectiveness
            mitigated = _mitigate(
                raw_damage, dmg_type, swings.resists, swings.magic_amp
            )
            proc_damages.append(mitigated)
            target.take_proc(mitigated)

        # Reduce HP from auto attack + other on-hit damage
        target.settle_auto(swings.auto_damage_per_hit + swings.other_on_hit_per_hit)

    return proc_damages


def _simulate_current_health_on_hit(
    effect: item_effects.PerHitEffect,
    base_inputs: item_effects.DamageInputs,
    swings: AutoSwings,
    *,
    phantom_hit_autos: set[int] | None = None,
    double_hit_all: bool = False,
    effectiveness: float = 1.0,
    first_auto_damage_by_auto: Sequence[float] = (),
) -> tuple[float, int, list["OnHitProc"]]:
    """Simulate a current-health on-hit against decreasing target HP.

    BoRK's passive deals physical damage based on the target's *current*
    health, which drops after every auto attack. Once the modeled HP
    reaches zero, BoRK deals a flat minimum damage instead.

    On phantom hit autos, BoRK procs twice (the normal hit + phantom hit),
    both reducing the target's HP. When ``double_hit_all`` is True (e.g.
    Akshan double shot), BoRK procs an extra time on every auto.

    Args:
        swings: The auto-attack stream to decay the target against.
        phantom_hit_autos: Set of 0-indexed auto numbers that trigger phantom
            hits (from Guinsoo's Rageblade). BoRK procs an extra time on these.
        double_hit_all: If True, BoRK procs an extra time on every auto
            (e.g. Akshan's double shot applies on-hits).
        effectiveness: On-hit effectiveness multiplier on each proc's raw
            damage (Azir soldiers apply on-hit at 50%).

    Returns:
        Tuple of (total mitigated BoRK damage, total BoRK hit count, each
        hit as an :class:`OnHitProc` in application order — one entry per
        counted hit, so callers can stamp per-swing damage events and the
        declaration each one carries).
    """
    if phantom_hit_autos is None:
        phantom_hit_autos = set()

    target = DecayingTarget.at_full(swings.target_health)
    total_damage = 0.0
    total_hits = 0
    hit_damages: list[OnHitProc] = []

    for i in range(swings.num_auto_attacks):
        # How many times BoRK procs this auto (1 normally, +1 on phantom hit,
        # +1 if double_hit_all e.g. Akshan double shot)
        procs_this_auto = 1
        if i in phantom_hit_autos:
            procs_this_auto += 1
        if double_hit_all:
            procs_this_auto += 1

        for _ in range(procs_this_auto):
            inputs = target.inputs(base_inputs)
            raw_damage = effect.source.raw_damage(inputs) * effectiveness
            mitigated = _mitigate(
                raw_damage,
                effect.source.damage_type,
                swings.resists,
                swings.magic_amp,
            )
            total_damage += mitigated
            total_hits += 1
            hit_damages.append(OnHitProc(raw_damage, mitigated))

            target.take_proc(mitigated)

        # Also reduce HP by auto attack damage and other on-hit damage
        # (other on-hit phantom procs are accounted for in other_on_hit_per_hit
        #  which is already multiplied by the average hits-per-auto)
        on_hit_this_auto = swings.other_on_hit_per_hit
        if i in phantom_hit_autos:
            on_hit_this_auto += swings.other_on_hit_per_hit  # phantom extra proc
        # First-auto packets are authored by the charge-spending pass, but
        # they still land on this auto and must lower the HP used by later
        # current-health procs. Keep this as an HP-only input: the packet is
        # added to the breakdown exactly once by _add_first_auto_strikes.
        if i < len(first_auto_damage_by_auto):
            on_hit_this_auto += max(0.0, float(first_auto_damage_by_auto[i]))
        target.settle_auto(swings.auto_damage_per_hit + on_hit_this_auto)

    return total_damage, total_hits, hit_damages
