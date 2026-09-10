"""What a swing pays back, and what schedules an on-hit application.

**Case 3 — Abilities that apply ITEM on-hits** (e.g. Bel'Veth Q/E):
    Ability entries may declare::

        "applies_item_on_hits": {"effectiveness": 0.75, "hits": 4}

    Each rotation cast then applies the build's per-hit on-hit item
    effects ``hits`` times at the given effectiveness, evaluated by
    ``_ability_applied_on_hit_damage`` from the same compiled specs the
    auto stream reads. The optional ``triggers`` key (default
    ``("on_hit",)``) declares what each application carries, matched
    against the item trigger taxonomy (``item_effects.counter_trigger``
    over the wiki's canonical On-Attacking list):

    - ``"on_hit"`` — deals the per-hit item damage and counts one hit
      on on-hit-gated counters (Kraken/Hullbreaker). Counters run
      ability hits first, then autos; a proc fires at the effectiveness
      of the hit that landed it.
    - ``"on_attack"`` — the application is a real attack (Bel'Veth E
      slashes) and advances on-attack cadences: Guinsoo's phantom-hit
      counter (a slash-fired phantom re-applies item on-hits at the
      slash's effectiveness and grants an extra on-hit counter stack).
      On-attack mechanics the engine does not model per-hit (energized
      stacking, Navori's refund rate, Yun Tal, Runaan's) are unaffected.

    Spellblade is neither: it is consumed by the next basic attack and
    stays on the auto timeline.
"""

import math
from collections.abc import Collection, Mapping, Sequence
from typing import Any

from ... import item_effects
from ..ledger.event_rows import _finite_numeric_receipt
from ..resists import _mitigate
from ..state import FightState, _damage_inputs


def _active_lifesteal_amount(
    state: FightState,
    damage_event: Mapping[str, Any],
    effectiveness: float,
) -> float | None:
    """Return one certified active life-steal heal amount.

    A heal is emitted only when the source event, effectiveness, and
    attacker's cached life-steal stat are complete and finite; missing or
    malformed receipts are deliberately withheld.
    """
    event_time = _finite_numeric_receipt(damage_event.get("time"))
    damage = _finite_numeric_receipt(damage_event.get("damage"))
    if event_time is None or damage is None or damage <= 0.0:
        return None

    lifesteal_percent = _finite_numeric_receipt(
        state.champion_stats.get("lifesteal_percent")
    )
    if lifesteal_percent is None or lifesteal_percent < 0.0:
        return None

    effectiveness = _finite_numeric_receipt(effectiveness)
    if effectiveness is None or effectiveness <= 0.0:
        return None

    amount = damage * (lifesteal_percent / 100.0) * effectiveness
    return amount if math.isfinite(amount) and amount > 0.0 else None


def _add_lifesteal_events(
    state: FightState,
    ordered_events: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    """Emit exact life-steal packets for timestamped physical attacks.

    Life steal is eligible on the primary target's physical basic attack and
    on-hit packets.  The damage rows already carry post-mitigation amounts and
    authored swing timestamps, so applying the cached percentage here avoids
    inventing a second damage walk.  Ability, magic, true, and un-timestamped
    rows are deliberately excluded; those require the separate omnivamp/AoE
    eligibility contract and remain unavailable.
    """
    raw_percent = _finite_numeric_receipt(state.champion_stats.get("lifesteal_percent"))
    if raw_percent is None or raw_percent <= 0.0:
        return

    eligible_prefixes = ("on_hit_", "on_hit_once_")
    heals: list[dict[str, float | str]] = []
    if ordered_events is None:
        # Unit callers may provide only the breakdown.  This path remains
        # conservative: rows without authored event timing are withheld.
        event_rows: list[tuple[str, Mapping[str, Any]]] = []
        for source_key, row in state.breakdown.items():
            if not isinstance(row, Mapping):
                continue
            events = row.get("damage_events")
            if not isinstance(events, list):
                continue
            event_rows.extend(
                (str(source_key), event)
                for event in events
                if isinstance(event, Mapping)
            )
    else:
        event_rows = [
            (str(event["source_key"]), event)
            for event in ordered_events
            if isinstance(event, Mapping)
        ]
    for source_key, event in event_rows:
        source_is_attack = source_key == "auto_attacks" or source_key.startswith(
            eligible_prefixes
        )
        if not source_is_attack and not event.get("basic_attack"):
            continue
        if event.get("damage_type") != "physical":
            continue
        event_time = _finite_numeric_receipt(event.get("time"))
        damage = _finite_numeric_receipt(event.get("damage"))
        if event_time is None or damage is None or damage <= 0.0:
            continue
        # An empowered/basic swing may share an ability row with ordinary
        # physical spell damage.  Only the explicitly marked swing is
        # life-steal eligible; never infer eligibility from the ability name
        # or row aggregate.
        if not source_is_attack and not event.get("basic_attack"):
            continue
        amount = damage * raw_percent / 100.0
        if math.isfinite(amount) and amount > 0.0:
            heals.append(
                {
                    "time": event_time,
                    "amount": amount,
                    "trigger_source": source_key,
                    # Life steal is a stat-scaled vamp effect.  Spirit
                    # Visage does not amplify the stat itself; the ordered
                    # survival ledger uses this category to avoid applying
                    # Boundless Vitality a second time.
                    "healing_category": "vamp",
                }
            )

    if not heals:
        return
    heals.sort(key=lambda event: (float(event["time"]), str(event["trigger_source"])))
    state.breakdown["heal_lifesteal"] = {
        "name": "Life steal (basic attacks and on-hit)",
        "count": len(heals),
        "total_amount": sum(float(event["amount"]) for event in heals),
        "unit": "health",
        "heal_events": heals,
        "event_phase": "heal",
    }


def _add_omnivamp_events(
    state: FightState,
    ordered_events: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    """Emit omnivamp only for explicitly single-target attack packets.

    The current event ledger does not certify area, pet, or copied-target
    scope for ordinary ability rows.  Attack and primary on-hit rows are
    explicitly marked by ``_ordered_damage_events`` and therefore receive
    their sourced full-effectiveness heal; every other event remains withheld
    instead of being treated as a guessed single-target packet.
    """
    raw_percent = _finite_numeric_receipt(state.champion_stats.get("omnivamp_percent"))
    if raw_percent is None or raw_percent <= 0.0:
        return
    if ordered_events is None:
        return
    heals: list[dict[str, float | str]] = []
    for event in ordered_events:
        if not isinstance(event, Mapping):
            continue
        effectiveness = _finite_numeric_receipt(event.get("omnivamp_effectiveness"))
        damage_type = event.get("damage_type")
        damage = _finite_numeric_receipt(event.get("damage"))
        event_time = _finite_numeric_receipt(event.get("time"))
        if (
            effectiveness is None
            or effectiveness <= 0.0
            or damage_type == "true"
            or damage is None
            or damage <= 0.0
            or event_time is None
        ):
            continue
        amount = damage * (raw_percent / 100.0) * effectiveness
        if math.isfinite(amount) and amount > 0.0:
            heals.append(
                {
                    "time": event_time,
                    "amount": amount,
                    "trigger_source": str(event["source_key"]),
                    # Omnivamp is likewise a direct stat conversion rather
                    # than a received-healing packet for Spirit Visage.
                    "healing_category": "vamp",
                }
            )
    if not heals:
        return
    heals.sort(key=lambda event: (float(event["time"]), str(event["trigger_source"])))
    state.breakdown["heal_omnivamp"] = {
        "name": "Omnivamp (explicit single-target attacks and on-hit)",
        "count": len(heals),
        "total_amount": sum(float(event["amount"]) for event in heals),
        "unit": "health",
        "heal_events": heals,
        "event_phase": "heal",
    }


def _ability_applied_on_hit_damage(
    state: FightState,
    effectiveness: float,
    target_current_health: float,
) -> dict[str, float]:
    """Mitigated item on-hit damage for ONE ability-carried application.

    Champions whose abilities apply item on-hit effects (Bel'Veth Q/E)
    declare ``applies_item_on_hits`` on the ability entry; the rotation
    calls this once per hit. It reads the SAME compiled per-hit specs
    the auto stream applies (``state.per_hit_strikes``) —
    including BoRK's current-health formula, evaluated at the rotation's
    modeled target HP. Counter-gated procs (Kraken/Hullbreaker) are NOT
    summed here — the application is recorded on the fight's shared hit
    counter and its procs fire in ``_add_stacking_strikes``.
    On-ATTACK-only mechanics (energized procs, spellblade, phantom
    hits) are attack-triggered and never apply here. Per-hit components
    marked ``superseded_by_ability_proc`` (Muramana) are skipped too —
    their per-ability-cast damage already fired for this cast.
    """
    inputs = _damage_inputs(state, target_current_health)
    by_type: dict[str, float] = {}
    for effect in state.per_hit_strikes:
        if effect.superseded_by_ability_proc:
            # Muramana: Shock's ability damage already procs once per
            # cast (``per_ability_hits``); the on-hit component never
            # stacks with it on one ability hit.
            continue
        raw = effect.source.raw_damage(inputs) * effectiveness
        if raw <= 0:
            continue
        dtype = effect.source.damage_type
        by_type[dtype] = by_type.get(dtype, 0.0) + _mitigate(
            raw, dtype, state.resists, state.magic_amp
        )
    return by_type


def _calculate_phantom_hits(
    num_auto_attacks: int,
    effect: item_effects.PhantomHitEffect | None,
    leading_attacks: int = 0,
) -> tuple[list[int], set[int]]:
    """The 0-indexed leading attacks and autos that trigger phantom hits.

    Rageblade grants stacking attack speed per attack (Seething Strike).  The
    4th attack maxes Seething and starts Phantom stacking.  At 2 Phantom
    stacks the next attack consumes them to trigger a Phantom Hit that applies
    all on-hit effects an additional time.

    Sequence: 5 attacks to build up, the 6th triggers, then every 3rd after
    (6, 9, 12, 15, 18, ...).  Phantom stacking is an ON-ATTACK mechanic, so the
    counter runs over one shared attack sequence: ability-carried attacks
    (Bel'Veth E slashes) lead and the fight's autos continue it, so a slash can
    be the 6th attack that fires the phantom.
    """
    total_attacks = leading_attacks + num_auto_attacks
    if effect is None or total_attacks <= effect.stacking_autos:
        return [], set()

    ability_phantoms: list[int] = []
    phantom_autos: set[int] = set()
    # First phantom hit at combined attack index = stacking_autos
    # (0-indexed, so the 6th attack).
    attack_index = effect.stacking_autos
    while attack_index < total_attacks:
        if attack_index < leading_attacks:
            ability_phantoms.append(attack_index)
        else:
            phantom_autos.add(attack_index - leading_attacks)
        attack_index += effect.interval

    return ability_phantoms, phantom_autos


def _calculate_stacking_procs(
    num_auto_attacks: int,
    phantom_hit_autos: Collection[int],
    double_on_hit_procs: int,
    hits_required: int,
    *,
    leading_ability_hits: int = 0,
    ability_extra_stacks: set[int] | None = None,
) -> tuple[list[int], list[int]]:
    """Simulate every-Nth-on-hit procs with extra-application awareness.

    The counter runs over ONE shared hit sequence: ability-carried
    on-hit applications first (the rotation leads the fight model),
    then the fight's autos — leftover stacks carry across, so an
    ability hit can land the Nth stack and the next auto continues from
    a reset counter (Bel'Veth Q/E feeding Kraken).

    Args:
        num_auto_attacks: Total auto attacks in the fight.
        phantom_hit_autos: Set of 0-indexed autos that trigger phantom hits.
        double_on_hit_procs: Number of Dusk and Dawn double on-hit procs.
        hits_required: On-hit applications needed to proc.
        leading_ability_hits: Ability-carried applications that precede
            the autos on the shared counter.
        ability_extra_stacks: Leading-hit indices that apply on-hit an
            extra time (a Guinsoo phantom hit fired by that ability
            attack), granting an extra stack like phantom autos do.

    Returns:
        Tuple of (0-indexed ability-hit indices where procs fire,
        0-indexed auto indices where procs fire).

    Theorem (modular counting): for a pure auto stream with no phantom or
    double-on-hit applications, the counter fires on exactly the attacks
    with 1-based index N, 2N, 3N, ... — i.e. 0-indexed procs at
    N-1, 2N-1, ... and a total of floor(num_attacks/N) procs (expected
    count of a deterministic every-Nth proc chain; see
    docs/math-foundations.md section 1.2). Phantom and double-on-hit
    applications add one extra counter step on their own attacks, which is
    exactly the in-game shared-counter semantics.
    """
    stacks = 0
    ability_procs: list[int] = []
    extra_stacks = ability_extra_stacks or set()
    for i in range(leading_ability_hits):
        stacks += 1
        if stacks >= hits_required:
            ability_procs.append(i)
            stacks = 0
        if i in extra_stacks:
            stacks += 1
            if stacks >= hits_required:
                ability_procs.append(i)
                stacks = 0

    proc_autos: list[int] = []

    double_on_hit_auto_set: set[int] = set()
    if double_on_hit_procs > 0:
        for i in range(min(double_on_hit_procs, num_auto_attacks)):
            double_on_hit_auto_set.add(i)

    for i in range(num_auto_attacks):
        stacks += 1
        if stacks >= hits_required:
            proc_autos.append(i)
            stacks = 0

        if i in phantom_hit_autos:
            stacks += 1
            if stacks >= hits_required:
                proc_autos.append(i)
                stacks = 0

        if i in double_on_hit_auto_set:
            stacks += 1
            if stacks >= hits_required:
                proc_autos.append(i)
                stacks = 0

    return ability_procs, proc_autos


def _schedule_cooldown_procs(
    swing_times: Sequence[float],
    proc_cooldown: float,
) -> list[int]:
    """Sorted 0-indexed swings on which a per-target-cooldown on-hit procs.
    The first swing always procs; each later swing procs when its authored
    timestamp is at least ``proc_cooldown`` after the previous proc (Jarvan
    IV's Martial Cadence pattern).  Consuming the same schedule that stamps
    damage events keeps the scheduling decision and the stamped time from
    diverging during empowered attack-speed windows."""
    proc_autos: list[int] = []
    next_ready = 0.0
    for i, timestamp in enumerate(swing_times):
        if timestamp >= next_ready:
            proc_autos.append(i)
            next_ready = timestamp + proc_cooldown
    return proc_autos
