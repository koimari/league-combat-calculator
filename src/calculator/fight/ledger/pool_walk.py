"""The target's live pools, walked event by event."""

from dataclasses import dataclass
from typing import Any

from ... import shield_ledger
from ...interpreters import delta_amp, threshold_defense
from ...item_behavior import Probe
from ..cast_slots import DEFAULT_CAST_ORDER
from .event_ledger import _ordered_damage_events


@dataclass
class _ThresholdHealDrip:
    """Protoplasm Harness's sourced heal, delivered on its authored ticks.

    ``shield_ledger`` owns the Lifeline itself — the threshold crossing, the
    temporary bonus health, and the expiry that removes it again.  The Wiki
    sources the accompanying heal "over the same duration"; the cadence it is
    subdivided on is the mechanic's own declared ``heal_tick_interval``, so
    this author lands whole ticks at authored times rather than interpolating
    a continuous drip between whatever damage events happen to exist.  That
    is what makes the target-side heal an event timeline instead of a coarse
    total, and ``ticks`` is the count a coverage reader certifies against.
    """

    duration: float = 0.0
    tick_interval: float = 0.0
    tick_amount: float = 0.0
    ticks: int = 0
    ticks_delivered: int = 0
    triggered: bool = False
    trigger_time: float = -1.0
    healing_received: float = 0.0

    def start(
        self,
        pools: shield_ledger.ShieldPools,
        event_time: float,
        armed: shield_ledger.Absorption,
    ) -> None:
        """Begin the heal on the instance whose damage armed the Lifeline.

        The window and the sourced total are read back off the armed Lifeline
        rather than staged a second time here.  The arming instant already
        delivered whatever the defender's missing health could take; only the
        remainder is scheduled, so the two authors never exceed the sourced
        amount.
        """
        self.triggered = True
        self.trigger_time = event_time
        self.duration = pools.threshold_health.duration
        self.tick_interval = threshold_defense.threshold_health_tick_interval()
        remainder = max(
            0.0, armed.threshold_health_heal - armed.threshold_health_healed
        )
        self.ticks = (
            round(self.duration / self.tick_interval)
            if self.tick_interval > 0.0 and self.duration > 0.0
            else 0
        )
        self.tick_amount = remainder / self.ticks if self.ticks else 0.0
        self.healing_received += armed.threshold_health_healed

    def advance_to(self, pools: shield_ledger.ShieldPools, event_time: float) -> None:
        """Land every authored tick due by ``event_time``, then the expiry.

        The final tick falls on the window's last instant, which is also the
        instant the temporary maximum lapses; the heal lands first because
        the source has it running for the whole duration, and the expiry then
        clamps against the maximum it leaves behind.
        """
        if not self.triggered:
            return
        while self.ticks_delivered < self.ticks:
            due = self.ticks_delivered + 1
            tick_time = self.trigger_time + due * self.tick_interval
            if tick_time > event_time + 1e-9:
                break
            self.ticks_delivered += 1
            received = min(self.tick_amount, max(0.0, pools.max_health - pools.health))
            if received > 0.0 and pools.health > 0.0:
                pools.health += received
                self.healing_received += received
        shield_ledger.expire_threshold_health(pools, event_time)

    # A declaration subdividing the window into no ticks leaves the heal's
    # timing unsourced — the coverage downgrade the target-side Lifeline owes.
    # Asking the drip keeps that measured rather than assumed by the reader.
    def cadence_certified(self) -> bool:
        """Whether the heal was delivered on an authored tick schedule."""
        return not self.triggered or self.ticks > 0


_LIANDRY_BURN_KEY = "burn_Liandry's Torment"


def _liandry_max_health_reprice(
    source_key: str,
    damage: float,
    event_time: float,
    *,
    pools: Any,
    opening_max_health: float,
    heal_drip: "_ThresholdHealDrip",
) -> tuple[float, float]:
    """Reprice one burn tick against the target's *current* maximum health.
    Liandry's Torment burns for a percentage of maximum health, so a lifeline
    that raises the target's maximum mid-fight raises every tick landing after
    it.  The reprice rides the ordered ledger because that is where the
    target's live pools exist.  Returns the repriced damage and the delta it
    adds to the burn's total, ``(damage, 0.0)`` when it is not a burn tick."""
    if source_key != _LIANDRY_BURN_KEY:
        return damage, 0.0
    if not heal_drip.triggered or event_time <= heal_drip.trigger_time + 1e-9:
        return damage, 0.0
    adjusted = damage * pools.max_health / opening_max_health
    return adjusted, adjusted - damage


def _simulate_ordered_damage(
    cinderbloom: "delta_amp.AmpSlot | None",
    breakdown: dict[str, Any],
    ability_damages: dict[str, dict[str, Any]],
    target_health: float,
    cast_order: list[str] | None = None,
    *,
    cast_events: list[dict[str, Any]] | None = None,
    target_magic_shield: float = 0.0,
    target_physical_shield: float = 0.0,
    target_general_shield: float = 0.0,
    target_threshold_shield_amount: float = 0.0,
    target_threshold_shield_health_ratio: float = 0.0,
    target_threshold_shield_duration: float = 0.0,
    target_threshold_shield_damage_type: str = "all",
    target_threshold_health_bonus: float = 0.0,
    target_threshold_health_heal: float = 0.0,
    target_threshold_health_ratio: float = 0.0,
    target_threshold_health_duration: float = 0.0,
    roster_target_index: int | None = None,
) -> tuple[float, dict[str, float], list[dict[str, Any]], dict[str, Any]]:
    """Simulate the ordered damage ledger against the target's pools.

    **This is not one mechanic's function.**  Two unrelated things need the
    target's live pools event by event, and this walk is the only place those
    exist: Shadowflame's Cinderbloom, which amplifies magic and true damage
    below a health threshold, and Liandry's max-health reprice, which raises
    later burn ticks when a lifeline raises the target's maximum health.  The
    reprice is reported in ``adjustments`` and is nobody's bonus — it belongs
    to the burn's own row.

    Args:
        breakdown: Current damage breakdown dict.
        ability_damages: Parsed ability data with damage types.
        target_health: Target's maximum health at the start of the fight.
        cast_order: Ability cast order (e.g., ["E", "Q", "W", "R"]).

    Returns:
        (total Cinderbloom bonus, bonus per damage type — the crit bonus
        keeps the underlying damage's type, the bonus events, the
        non-Cinderbloom adjustments the same walk produced).
    """
    if cast_order is None:
        cast_order = list(DEFAULT_CAST_ORDER)
    crit_bonus = cinderbloom.bonus_fraction if cinderbloom is not None else 0.0
    pools = shield_ledger.build_pools(
        target_health,
        magic_shield=target_magic_shield,
        physical_shield=target_physical_shield,
        general_shield=target_general_shield,
        threshold_shield_amount=target_threshold_shield_amount,
        threshold_shield_health_ratio=target_threshold_shield_health_ratio,
        threshold_shield_duration=target_threshold_shield_duration,
        threshold_shield_damage_type=target_threshold_shield_damage_type,
        threshold_health_bonus=target_threshold_health_bonus,
        threshold_health_heal=target_threshold_health_heal,
        threshold_health_ratio=target_threshold_health_ratio,
        threshold_health_duration=target_threshold_health_duration,
    )
    heal_drip = _ThresholdHealDrip()
    total_bonus = 0.0
    bonus_by_type: dict[str, float] = {}
    bonus_events: list[dict[str, Any]] = []
    liandry_delta = 0.0
    liandry_events: list[dict[str, Any]] = []

    events = _ordered_damage_events(
        breakdown,
        ability_damages,
        cast_order,
        cast_events=cast_events,
        roster_target_index=roster_target_index,
    )

    # 4. Simulate damage order, tracking target HP
    for event in events:
        damage = event["damage"]
        dtype = event["damage_type"]
        event_time = float(event["time"])
        heal_drip.advance_to(pools, event_time)
        source_key = str(event["source_key"])
        damage, reprice_delta = _liandry_max_health_reprice(
            source_key,
            damage,
            event_time,
            pools=pools,
            opening_max_health=target_health,
            heal_drip=heal_drip,
        )
        liandry_delta += reprice_delta
        if source_key == _LIANDRY_BURN_KEY:
            liandry_events.append(
                {
                    "time": event_time,
                    "damage_type": dtype,
                    "damage": damage,
                }
            )
        event_damage = damage
        if (
            cinderbloom is not None
            and cinderbloom.prices_damage_type(dtype)
            and cinderbloom.live_predicate_holds(
                Probe.TARGET_HEALTH_FRACTION, pools.health, pools.max_health
            )
        ):
            bonus = damage * crit_bonus
            total_bonus += bonus
            bonus_by_type[dtype] = bonus_by_type.get(dtype, 0.0) + bonus
            bonus_events.append(
                {
                    "time": event_time,
                    "damage": bonus,
                    "damage_type": dtype,
                    "source_key": f"shadowflame_{cinderbloom.owner}",
                    "trigger_source": event["source_key"],
                }
            )
            event_damage += bonus

        outcome = shield_ledger.absorb(pools, event_damage, dtype, event_time)
        if outcome.threshold_health_triggered:
            heal_drip.start(pools, event_time, outcome)

    adjustments = {
        "liandry_delta": liandry_delta,
        "liandry_events": liandry_events,
        "threshold_health_triggered": heal_drip.triggered,
        "threshold_health_trigger_time": heal_drip.trigger_time,
    }
    return total_bonus, bonus_by_type, bonus_events, adjustments
