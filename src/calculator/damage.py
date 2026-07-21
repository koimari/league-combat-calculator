"""Fight damage engine — orchestrates all damage sources over a fight duration.

This module is champion-agnostic. Champion ability data (including cooldowns)
is provided by the caller via the ``ability_damages`` dict. Item effects are
delegated to ``item_effects``.

Ability On-Hit Framework
~~~~~~~~~~~~~~~~~~~~~~~~
Champions with abilities that augment auto attacks can participate in the
on-hit system via two mechanisms:

**Case 1 — Stack acceleration** (e.g. Vayne W Silver Bolts):
    Abilities that build stacks per auto and proc on reaching N stacks.
    Phantom hits grant an extra stack per proc. The ``phantom_hit_autos``
    set is returned in the fight result so champion-specific calculators
    can model accelerated stack procs. The champion module is responsible
    for counting stacks and determining when procs happen.

**Case 2 — On-hit damage** (e.g. Viego passive % health on auto):
    Abilities that add flat/scaling damage per auto attack. These are
    registered by adding an ``on_hit`` key to the ability's entry in
    ``ability_damages``::

        ability_damages["passive"] = {
            "name": "Blade of the Ruined Blade",
            "on_hit": {
                "name": "Viego Passive (on-hit)",
                "damage_per_hit": 42.0,
                "damage_type": "physical",
            },
        }

    The fight engine processes these alongside item on-hits, and phantom
    hits automatically double them.
"""

import math
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from . import item_effects
from .ability_spec import DamagePart, parts_raw_total
from .resistance import (
    apply_resistance,
    apply_magic_penetration,
    apply_armor_penetration,
)

# Critical strikes deal 200% base damage (this changed once before, from
# 175%). Items add on top via crit_damage_bonus; anything recovering the
# item bonus from a total multiplier must subtract this same constant.
BASE_CRIT_MULTIPLIER = 2.0

# Default ability cast order when a fight doesn't specify one. Q2 is
# skipped harmlessly for champions without a second Q cast. A tuple so a
# fight can never mutate the shared default; use sites materialize a list.
DEFAULT_CAST_ORDER = ("Q", "Q2", "W", "E", "R")


def effective_cooldown(base_cooldown: float, ability_haste: float) -> float:
    """Calculate effective cooldown after ability haste.

    Formula: base_cd * 100 / (100 + ability_haste)

    Args:
        base_cooldown: Base cooldown in seconds.
        ability_haste: Total ability haste.

    Returns:
        Effective cooldown in seconds.
    """
    if base_cooldown <= 0:
        return 0.0
    return base_cooldown * (100.0 / (100.0 + ability_haste))


# ─────────────────────────────────────────────────────────────────────────
# Fight-model state
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class Resists:
    """Target resistances and the attacker's penetration, resolved together.

    Owns the penetration math that fight setup resolves and that later
    steps re-resolve when something changes mid-fight: stat-buff ultimates
    that grant pen (Ambessa R), target shreds (Kog'Maw Q), and the
    ability→auto switch for Terminus' auto-only stacking pen.

    Two penetration variants are tracked (the Terminus split):

    - ``ability_*_pen_percent`` — pen for ability damage (Terminus'
      max-stack pen stripped; it never applies to abilities).
    - ``auto_*_pen_percent`` — pen for auto attacks, folding in Terminus'
      weighted-average stacking pen across the fight's autos.

    The ``effective_*`` fields hold the currently-resolved resistances
    that damage math applies. During the ability rotation they reflect
    ability pen; ``use_auto_pen`` switches them to auto pen once the
    rotation is done. ``effective_mr`` pre/post ult variants exist because
    Malignance's Hatefog MR reduction only activates once R is cast.
    """

    # Attacker penetration
    magic_pen_flat: float
    magic_pen_percent: float
    armor_pen_percent: float
    flat_armor_pen: float
    # Terminus Juxtaposition: auto-only stacking pen (weighted average)
    has_terminus: bool
    terminus_stat_pen: float
    terminus_avg_pen: float
    # Target resistances (mutated by shreds)
    target_armor: float
    base_mr: float
    reduced_mr: float  # base MR minus Malignance Hatefog reduction
    malignance_mr_reduction: float
    bc_reduction: float  # Black Cleaver % armor reduction
    mr_reduction_effect: item_effects.StackingReductionEffect | None
    # Resolved values (recomputed by the resolve/shred methods below)
    ability_armor_pen_percent: float = 0.0
    ability_magic_pen_percent: float = 0.0
    auto_armor_pen_percent: float = 0.0
    auto_magic_pen_percent: float = 0.0
    reduced_armor: float = 0.0
    effective_armor: float = 0.0
    effective_mr_pre_ult: float = 0.0
    effective_mr_post_ult: float = 0.0
    effective_mr: float = 0.0

    def resolve_magic(self) -> None:
        """Recompute magic pen variants and effective MR (ability pen)."""
        self.ability_magic_pen_percent = self.magic_pen_percent
        self.auto_magic_pen_percent = self.magic_pen_percent
        if self.has_terminus:
            stripped = max(0.0, self.magic_pen_percent - self.terminus_stat_pen)
            self.ability_magic_pen_percent = stripped
            self.auto_magic_pen_percent = stripped
            if self.terminus_avg_pen > 0:
                self.auto_magic_pen_percent = 1.0 - (1.0 - stripped) * (
                    1.0 - self.terminus_avg_pen
                )
        self.effective_mr_pre_ult = apply_magic_penetration(
            self.base_mr, self.magic_pen_flat, self.ability_magic_pen_percent
        )
        self.effective_mr_post_ult = apply_magic_penetration(
            self.reduced_mr, self.magic_pen_flat, self.ability_magic_pen_percent
        )
        self.effective_mr = self.effective_mr_post_ult

    def resolve_armor(self) -> None:
        """Recompute armor pen variants and effective armor (ability pen)."""
        self.ability_armor_pen_percent = self.armor_pen_percent
        self.auto_armor_pen_percent = self.armor_pen_percent
        if self.has_terminus:
            stripped = max(0.0, self.armor_pen_percent - self.terminus_stat_pen)
            self.ability_armor_pen_percent = stripped
            self.auto_armor_pen_percent = stripped
            if self.terminus_avg_pen > 0:
                self.auto_armor_pen_percent = 1.0 - (1.0 - stripped) * (
                    1.0 - self.terminus_avg_pen
                )
        self.reduced_armor = self.target_armor * (1.0 - self.bc_reduction)
        self.effective_armor = apply_armor_penetration(
            self.reduced_armor, self.flat_armor_pen, self.ability_armor_pen_percent
        )

    def shred_armor(self, reduction_percent: float) -> None:
        """Apply a % armor shred (e.g. Kog'Maw Q) and re-resolve armor."""
        self.target_armor *= 1.0 - reduction_percent / 100.0
        self.reduced_armor = self.target_armor * (1.0 - self.bc_reduction)
        self.effective_armor = apply_armor_penetration(
            self.reduced_armor, self.flat_armor_pen, self.ability_armor_pen_percent
        )

    def shred_mr(self, reduction_percent: float) -> None:
        """Apply a % MR shred (e.g. Kog'Maw Q) and re-resolve MR."""
        self.base_mr *= 1.0 - reduction_percent / 100.0
        self.reduced_mr = max(self.base_mr - self.malignance_mr_reduction, 0)
        self.effective_mr_pre_ult = apply_magic_penetration(
            self.base_mr, self.magic_pen_flat, self.ability_magic_pen_percent
        )
        self.effective_mr_post_ult = apply_magic_penetration(
            self.reduced_mr, self.magic_pen_flat, self.ability_magic_pen_percent
        )
        self.effective_mr = self.effective_mr_post_ult

    def use_auto_pen(self) -> None:
        """Switch effective resistances to auto-attack pen (Terminus avg).

        Called once the ability rotation is done: remaining damage (autos,
        on-hits, item procs) uses the auto-attack pen variants.
        """
        self.effective_armor = apply_armor_penetration(
            self.reduced_armor, self.flat_armor_pen, self.auto_armor_pen_percent
        )
        self.effective_mr_pre_ult = apply_magic_penetration(
            self.base_mr, self.magic_pen_flat, self.auto_magic_pen_percent
        )
        self.effective_mr_post_ult = apply_magic_penetration(
            self.reduced_mr, self.magic_pen_flat, self.auto_magic_pen_percent
        )
        self.effective_mr = self.effective_mr_post_ult


def _mitigate(
    raw_damage: float,
    damage_type: str,
    resists: Resists,
    magic_amp: float,
) -> float:
    """Apply the fight's resolved resistance and magic-only amplifier."""
    if damage_type == "magic":
        return apply_resistance(raw_damage, resists.effective_mr) * magic_amp
    if damage_type == "physical":
        return apply_resistance(raw_damage, resists.effective_armor)
    return raw_damage


@dataclass(frozen=True)
class FightConfig:
    """Everything configurable about one fight, in one spelling.

    Pure configuration — champion_stats / ability_damages / items are
    DATA and stay positional arguments to the engine. Defaults mirror
    the engine's historical keyword defaults.
    """

    target_health: float
    target_armor: float
    target_magic_resistance: float
    fight_duration_seconds: float
    target_bonus_health: float = 0.0
    auto_attack_uptime: float = 0.0
    one_rotation: bool = False
    include_actives: bool = True
    cast_order: list[str] | None = None
    auto_attacks_only: bool = False
    deterministic: bool = False


@dataclass
class FightState:
    """Shared mutable state threaded through the fight-model step functions.

    Holds the fight configuration (inputs, read-only once built), the
    resolved combat numbers (resistances, amplifiers, crit, attack
    timing — some mutated mid-fight by stat buffs and shreds), and the
    damage accumulators every step writes into. Values produced by one
    step and consumed by the next travel as step-function results
    instead of living here.
    """

    # ── Fight configuration (read-only after setup) ──────────────────────
    champion_stats: dict[str, float]
    ability_damages: dict[str, dict[str, Any]]
    items: list[dict[str, Any]]
    damage_effects: item_effects.BuildDamageEffects
    cast_order: list[str]
    target_health: float
    target_bonus_health: float
    fight_duration_seconds: float
    auto_attack_uptime: float
    ability_haste: float
    one_rotation: bool
    include_actives: bool
    auto_attacks_only: bool
    deterministic: bool
    is_melee: bool
    level: int
    # ── Resolved combat numbers ───────────────────────────────────────────
    resists: Resists
    magic_amp: float  # Abyssal Mask
    ability_amp: float  # Actualizer
    basic_amp: float  # Hexoptics C44
    hypershot_amp: float  # Horizon Focus
    # ── Attack timing ─────────────────────────────────────────────────────
    attack_speed: float
    attack_speed_ratio: float
    num_auto_attacks: int
    empowered_autos: int
    # ── Crit (resolved after stat-buff ultimates) ─────────────────────────
    crit_chance: float = 0.0
    crit_multiplier: float = BASE_CRIT_MULTIPLIER
    # ── Accumulators ──────────────────────────────────────────────────────
    breakdown: dict[str, Any] = field(default_factory=dict)
    total_damage: float = 0.0
    notes: list[str] = field(default_factory=list)


def _damage_inputs(
    state: FightState,
    target_current_health: float | None = None,
) -> item_effects.DamageInputs:
    """Project mutable fight state into an item-owned raw-formula input."""
    return item_effects.DamageInputs(
        champion_stats=state.champion_stats,
        level=state.level,
        is_melee=state.is_melee,
        target_max_health=state.target_health,
        target_current_health=(
            state.target_health
            if target_current_health is None
            else target_current_health
        ),
    )


def _calculate_phantom_hits(
    num_auto_attacks: int,
    effect: item_effects.PhantomHitEffect | None,
) -> tuple[int, set[int]]:
    """Calculate phantom-hit count and which autos trigger.

    Rageblade grants stacking attack speed per auto (Seething Strike).
    The 4th auto maxes Seething AND starts Phantom stacking. At 2
    Phantom stacks, the next auto consumes them to trigger a Phantom Hit
    that applies all on-hit effects an additional time.

    Sequence: 5 autos to build up, 6th triggers, then every 3rd after
    (6, 9, 12, 15, 18, ...).

    Args:
        num_auto_attacks: Total auto attacks in the fight.
        effect: Compiled phantom-hit cadence, or ``None``.

    Returns:
        Tuple of (phantom_hit_count, set of 0-indexed auto numbers that
        trigger phantom hits).
    """
    if effect is None or num_auto_attacks <= effect.stacking_autos:
        return 0, set()

    phantom_autos: set[int] = set()
    # First phantom hit at auto index = stacking_autos (0-indexed, so 6th auto)
    auto_index = effect.stacking_autos
    while auto_index < num_auto_attacks:
        phantom_autos.add(auto_index)
        auto_index += effect.interval

    return len(phantom_autos), phantom_autos


def _calculate_stacking_procs(
    num_auto_attacks: int,
    phantom_hit_autos: set[int],
    double_on_hit_procs: int,
    hits_required: int,
) -> tuple[int, list[int]]:
    """Simulate every-Nth-on-hit procs with extra-application awareness.

    Args:
        num_auto_attacks: Total auto attacks in the fight.
        phantom_hit_autos: Set of 0-indexed autos that trigger phantom hits.
        double_on_hit_procs: Number of Dusk and Dawn double on-hit procs.
        hits_required: On-hit applications needed to proc.

    Returns:
        Tuple of (proc_count, list of 0-indexed auto indices where procs
        fire).
    """
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

    return len(proc_autos), proc_autos


def _simulate_stacking_on_hit_damage(
    effect: item_effects.StackingOnHitEffect,
    base_inputs: item_effects.DamageInputs,
    target_health: float,
    num_auto_attacks: int,
    auto_damage_per_hit: float,
    other_on_hit_per_hit: float,
    resists: Resists,
    magic_amp: float,
    proc_autos: list[int],
) -> float:
    """Simulate a stacking proc whose formula reads decreasing target HP.

    Kraken's bonus damage scales with the target's missing health at
    the time of each proc: ``base * (1 + 0.75 * missing_ratio)``.
    This must be simulated per-auto because each auto (and its on-hit
    effects) reduces target HP, changing the missing ratio for later procs.

    Args:
        target_health: Target's starting (max) health.
        num_auto_attacks: Number of auto attacks in the fight.
        auto_damage_per_hit: Mitigated base auto attack damage per hit.
        other_on_hit_per_hit: Mitigated damage from other on-hit items per hit.
        resists: Resolved target resistances.
        magic_amp: Magic-damage multiplier.
        proc_autos: Sorted 0-indexed auto indices where the effect procs.

    Returns:
        Total mitigated damage across all procs.
    """
    if not proc_autos:
        return 0.0

    # Convert proc list to a counter: how many procs fire on each auto
    proc_counts: dict[int, int] = Counter(proc_autos)

    current_hp = target_health
    total_damage = 0.0

    for i in range(num_auto_attacks):
        procs_this_auto = proc_counts.get(i, 0)

        for _ in range(procs_this_auto):
            inputs = item_effects.DamageInputs(
                champion_stats=base_inputs.champion_stats,
                level=base_inputs.level,
                is_melee=base_inputs.is_melee,
                target_max_health=target_health,
                target_current_health=current_hp,
            )
            raw_damage = effect.source.raw_damage(inputs)
            mitigated = _mitigate(
                raw_damage,
                effect.source.damage_type,
                resists,
                magic_amp,
            )
            total_damage += mitigated
            current_hp -= mitigated

        # Reduce HP from auto attack + other on-hit damage
        current_hp -= auto_damage_per_hit + other_on_hit_per_hit
        if current_hp < 0:
            current_hp = 0

    return total_damage


def _simulate_current_health_on_hit(
    effect: item_effects.PerHitEffect,
    base_inputs: item_effects.DamageInputs,
    target_health: float,
    num_auto_attacks: int,
    auto_damage_per_hit: float,
    other_on_hit_per_hit: float,
    resists: Resists,
    magic_amp: float,
    phantom_hit_autos: set[int] | None = None,
    double_hit_all: bool = False,
) -> tuple[float, int]:
    """Simulate a current-health on-hit against decreasing target HP.

    BoRK's passive deals physical damage based on the target's *current*
    health, which drops after every auto attack. Once the modeled HP
    reaches zero, BoRK deals a flat minimum damage instead.

    On phantom hit autos, BoRK procs twice (the normal hit + phantom hit),
    both reducing the target's HP. When ``double_hit_all`` is True (e.g.
    Akshan double shot), BoRK procs an extra time on every auto.

    Args:
        target_health: Target's starting health.
        num_auto_attacks: Number of auto attacks in the fight.
        auto_damage_per_hit: Mitigated base auto attack damage per hit.
        other_on_hit_per_hit: Mitigated damage from non-BoRK on-hit items per hit.
        resists: Resolved target resistances.
        magic_amp: Magic-damage multiplier.
        phantom_hit_autos: Set of 0-indexed auto numbers that trigger phantom
            hits (from Guinsoo's Rageblade). BoRK procs an extra time on these.
        double_hit_all: If True, BoRK procs an extra time on every auto
            (e.g. Akshan's double shot applies on-hits).

    Returns:
        Tuple of (total mitigated BoRK damage, total BoRK hit count).
    """
    if phantom_hit_autos is None:
        phantom_hit_autos = set()

    current_hp = target_health
    total_damage = 0.0
    total_hits = 0

    for i in range(num_auto_attacks):
        # How many times BoRK procs this auto (1 normally, +1 on phantom hit,
        # +1 if double_hit_all e.g. Akshan double shot)
        procs_this_auto = 1
        if i in phantom_hit_autos:
            procs_this_auto += 1
        if double_hit_all:
            procs_this_auto += 1

        for _ in range(procs_this_auto):
            inputs = item_effects.DamageInputs(
                champion_stats=base_inputs.champion_stats,
                level=base_inputs.level,
                is_melee=base_inputs.is_melee,
                target_max_health=target_health,
                target_current_health=current_hp,
            )
            raw_damage = effect.source.raw_damage(inputs)
            mitigated = _mitigate(
                raw_damage,
                effect.source.damage_type,
                resists,
                magic_amp,
            )
            total_damage += mitigated
            total_hits += 1

            current_hp -= mitigated

        # Also reduce HP by auto attack damage and other on-hit damage
        # (other on-hit phantom procs are accounted for in other_on_hit_per_hit
        #  which is already multiplied by the average hits-per-auto)
        on_hit_this_auto = other_on_hit_per_hit
        if i in phantom_hit_autos:
            on_hit_this_auto += other_on_hit_per_hit  # phantom extra proc
        current_hp -= auto_damage_per_hit + on_hit_this_auto
        if current_hp < 0:
            current_hp = 0

    return total_damage, total_hits


def _calculate_shadowflame_bonus(
    effect: item_effects.MagicTrueCritEffect,
    breakdown: dict[str, Any],
    ability_damages: dict[str, dict[str, Any]],
    target_health: float,
    cast_order: list[str] | None = None,
) -> float:
    """Calculate bonus damage from Shadowflame's Cinderbloom passive.

    Simulates damage dealt in ability-cast order. When the target's
    modeled HP drops below 40% maximum health, subsequent magic and
    true damage instances deal 120% damage (20% bonus).

    Args:
        breakdown: Current damage breakdown dict.
        ability_damages: Parsed ability data with damage types.
        target_health: Target's maximum health.
        cast_order: Ability cast order (e.g., ["E", "Q", "W", "R"]).

    Returns:
        Total bonus damage from Shadowflame crits.
    """
    if cast_order is None:
        cast_order = list(DEFAULT_CAST_ORDER)
    threshold_hp = target_health * effect.health_threshold
    crit_bonus = effect.crit_multiplier - 1.0
    current_hp = target_health
    total_bonus = 0.0

    # Build events: (damage_amount, is_magic_or_true)
    events: list[tuple[float, bool]] = []

    # 1. Abilities in cast order
    for key in cast_order:
        if key not in breakdown:
            continue
        entry = breakdown[key]
        damage = entry["total_damage"]
        dtype = entry.get("damage_type", "magic")

        if dtype == "mixed" and key in ability_damages:
            # Split into magic (mitigated) and true portions
            casts = entry.get("casts", 1)
            true_per_cast = parts_raw_total(
                ability_damages[key].get("parts", ()), "true"
            )
            total_true = true_per_cast * casts
            magic_portion = damage - total_true
            events.append((magic_portion, True))
            events.append((total_true, True))
        elif dtype in ("magic", "true"):
            # R with multiple dashes: split into individual events
            if key == "R" and ability_damages.get("R", {}).get("cast_instances", 1) > 1:
                total_dashes = ability_damages["R"]["cast_instances"]
                casts = entry.get("casts", 1)
                per_event = damage / (total_dashes * casts)
                for _ in range(total_dashes * casts):
                    events.append((per_event, True))
            else:
                events.append((damage, True))
        else:
            events.append((damage, False))

    # 2. Auto attacks (physical, never crits from Shadowflame)
    auto = breakdown.get("auto_attacks")
    if auto and auto["total_damage"] > 0:
        events.append((auto["total_damage"], False))

    # 3. Item effect damage (burns, procs, on-hits, etc.)
    # Skip every ability row the rotation pass already consumed — derived from
    # cast_order, not a Q/W/E/R literal, so synthetic recast rows
    # (e.g. Ambessa "Q2") are not double-counted.
    # No damage_amp_* rows can exist here: this reconstruction runs before
    # _apply_damage_amplifiers. "execute" is created later and is a
    # zero-damage display row regardless.
    skip_keys = set(cast_order) | {"auto_attacks", "execute"}
    for key, entry in breakdown.items():
        if key in skip_keys:
            continue
        damage = entry.get("total_damage", 0)
        if damage <= 0:
            continue
        dtype = entry.get("damage_type", "")
        events.append((damage, dtype in ("magic", "true")))

    # 4. Simulate damage order, tracking target HP
    for damage, is_crittable in events:
        if is_crittable and current_hp < threshold_hp:
            total_bonus += damage * crit_bonus
        current_hp -= damage

    return total_bonus


def _navori_effective_cd(
    base_cd: float,
    autos_per_second: float,
    refund_percent: float,
) -> float:
    """Compute effective cooldown with Navori Flickerblade CD refund.

    The cooldown ticks down in real time (1 second per 1 second).  Each
    auto attack that lands reduces the *remaining* cooldown by
    ``refund_percent`` (e.g. 15%).  We simulate this step-by-step:

    Example (7s CD, 1 auto/sec, 15% refund)::

        t=0  Cast, 7s remaining
        t=1  Auto → remaining = (7-1) * 0.85 = 5.10
        t=2  Auto → remaining = (5.10-1) * 0.85 = 3.485
        t=3  Auto → remaining = (3.485-1) * 0.85 = 2.112
        t=4  Auto → remaining = (2.112-1) * 0.85 = 0.945
        t=5  Auto → remaining ≤ 0, ability ready
        Effective CD ≈ 5.0s (down from 7.0s)

    Args:
        base_cd: Cooldown after ability haste (seconds).
        autos_per_second: Effective auto-attack rate (attack_speed * uptime).
        refund_percent: Fraction of remaining CD refunded per auto (0.15).

    Returns:
        Reduced effective cooldown in seconds.
    """
    if base_cd <= 0 or autos_per_second <= 0 or refund_percent <= 0:
        return base_cd

    retain = 1.0 - refund_percent  # 0.85 for 15% refund
    auto_interval = 1.0 / autos_per_second
    remaining = base_cd
    elapsed = 0.0

    # Simulate auto attacks landing at regular intervals
    next_auto = auto_interval
    while remaining > 0:
        if next_auto <= remaining:
            # Time passes until auto lands, then refund
            elapsed += next_auto
            remaining -= next_auto
            remaining *= retain
            next_auto = auto_interval
        else:
            # No more autos before CD expires — just wait it out
            elapsed += remaining
            remaining = 0.0

    return elapsed


def _resolve_combat_state(
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    items: list[dict[str, Any]],
    config: FightConfig,
) -> FightState:
    """Resolve resistances, penetration, amplifiers and attack timing.

    Builds the ``FightState`` every later step operates on: effective
    armor/MR after penetration (with the Terminus ability/auto split and
    Malignance's pre/post-ult MR), Black Cleaver armor reduction, the
    fight's auto-attack count (including Fiendhunter Bolts' empowered-auto
    window), and the fight-wide damage amplifiers.
    """
    fight_duration_seconds = config.fight_duration_seconds
    auto_attack_uptime = config.auto_attack_uptime
    is_melee = champion_stats.get("is_melee", True)
    level = int(champion_stats.get("level", 1))
    damage_effects = item_effects.resolve_damage_effects(items)

    magic_pen_flat = champion_stats.get("magic_penetration_flat", 0.0)
    magic_pen_percent = champion_stats.get("magic_penetration_percent", 0.0) / 100.0

    # Malignance MR reduction only activates on R cast, so abilities before
    # R in the cast_order use base MR.  Both effective values are resolved
    # and the rotation tracks which one to use per-ability.
    malignance_mr_reduction = (
        sum(effect.mr_reduction for effect in damage_effects.ultimate_procs)
        if "R" in ability_damages
        else 0.0
    )

    base_mr = max(config.target_magic_resistance, 0)
    reduced_mr = max(config.target_magic_resistance - malignance_mr_reduction, 0)

    # Stacking MR reduction (Bloodletter's Curse Vile Decay)
    mr_reduction_effect = damage_effects.stacking_mr_reduction

    # Armor penetration: percent pen + lethality (flat)
    armor_pen_percent = champion_stats.get("armor_penetration_percent", 0.0) / 100.0
    flat_armor_pen = champion_stats.get("flat_armor_penetration", 0.0)

    attack_speed = champion_stats["attack_speed"]
    as_ratio = champion_stats["attack_speed_ratio"]

    # ── Ultimate-triggered AS buffs (Fiendhunter Bolts) ──────
    # NOTE: Hexplate 50% bonus AS is now baked into champion stats (stats.py)
    ultimate_auto_buff = damage_effects.ultimate_auto_buff
    empowered_autos = 0

    if ultimate_auto_buff is not None and auto_attack_uptime > 0:
        buffed_as = attack_speed + as_ratio * (
            ultimate_auto_buff.bonus_attack_speed_percent / 100.0
        )

        # Fiendhunter: 3 empowered autos at buffed AS, then normal AS
        buff_dur = min(ultimate_auto_buff.duration, fight_duration_seconds)
        possible_in_window = math.floor(buffed_as * buff_dur * auto_attack_uptime)
        empowered_autos = min(
            ultimate_auto_buff.empowered_auto_count,
            possible_in_window,
        )
        if empowered_autos > 0 and buffed_as > 0:
            time_for_empowered = empowered_autos / (buffed_as * auto_attack_uptime)
        else:
            time_for_empowered = 0.0
        remaining_dur = fight_duration_seconds - time_for_empowered
        normal_autos = math.floor(
            attack_speed * max(0, remaining_dur) * auto_attack_uptime
        )
        num_auto_attacks = empowered_autos + normal_autos
    else:
        num_auto_attacks = math.floor(
            attack_speed * fight_duration_seconds * auto_attack_uptime
        )

    # Terminus Juxtaposition: stacking armor/magic pen every other auto.
    # The pen is displayed in champion stats at max stacks, but the fight
    # engine computes a weighted average pen across all autos (like Black
    # Cleaver) since stacks ramp up: 0%, 10%, 10%, 20%, 20%, 30%, 30%...
    # Terminus pen only applies to auto attacks, NOT abilities — see the
    # Resists docstring for the ability/auto pen split.
    stacking_pen = damage_effects.stacking_pen
    has_terminus = stacking_pen is not None
    terminus_avg_pen = 0.0
    terminus_stat_pen = 0.0
    if stacking_pen is not None:
        terminus_avg_pen = stacking_pen.average_pen(num_auto_attacks)
        terminus_stat_pen = stacking_pen.max_pen

    # Stacking armor reduction applies before penetration.
    armor_reduction = damage_effects.armor_reduction
    bc_reduction = (
        armor_reduction.average_reduction(num_auto_attacks)
        if armor_reduction is not None
        else 0.0
    )

    resists = Resists(
        magic_pen_flat=magic_pen_flat,
        magic_pen_percent=magic_pen_percent,
        armor_pen_percent=armor_pen_percent,
        flat_armor_pen=flat_armor_pen,
        has_terminus=has_terminus,
        terminus_stat_pen=terminus_stat_pen,
        terminus_avg_pen=terminus_avg_pen,
        target_armor=config.target_armor,
        base_mr=base_mr,
        reduced_mr=reduced_mr,
        malignance_mr_reduction=malignance_mr_reduction,
        bc_reduction=bc_reduction,
        mr_reduction_effect=mr_reduction_effect,
    )
    resists.resolve_magic()
    resists.resolve_armor()

    return FightState(
        champion_stats=champion_stats,
        ability_damages=ability_damages,
        items=items,
        damage_effects=damage_effects,
        cast_order=(
            config.cast_order
            if config.cast_order is not None
            else list(DEFAULT_CAST_ORDER)
        ),
        target_health=config.target_health,
        target_bonus_health=config.target_bonus_health,
        fight_duration_seconds=fight_duration_seconds,
        auto_attack_uptime=auto_attack_uptime,
        ability_haste=champion_stats.get("ability_haste", 0.0),
        one_rotation=config.one_rotation,
        include_actives=config.include_actives,
        auto_attacks_only=config.auto_attacks_only,
        deterministic=config.deterministic,
        is_melee=is_melee,
        level=level,
        resists=resists,
        magic_amp=damage_effects.magic_amp,
        ability_amp=(
            damage_effects.ability_amp.multiplier(
                champion_stats, config.include_actives
            )
            if damage_effects.ability_amp is not None
            else 1.0
        ),
        basic_amp=damage_effects.basic_amp,
        hypershot_amp=damage_effects.hypershot_amp,
        attack_speed=attack_speed,
        attack_speed_ratio=as_ratio,
        num_auto_attacks=num_auto_attacks,
        empowered_autos=empowered_autos,
    )


def _apply_stat_buff_ultimates(state: FightState) -> None:
    """Apply ability stat buffs (e.g. Aatrox R bonus AD) and resolve crit.

    Mutates ``champion_stats`` in place (callers observe the buffed stats,
    as before this refactor) and re-resolves anything derived from a
    buffed stat: attack damage, magic/armor penetration, and attack speed
    (which changes the fight's auto-attack count — note the Fiendhunter
    empowered/normal split is NOT recomputed here, matching the original
    behavior). Crit chance/multiplier are resolved afterwards so ability
    crit scaling and the auto-attack simulation both see buffed values.
    """
    stats = state.champion_stats
    resists = state.resists

    for ability_info in state.ability_damages.values():
        stat_buff = ability_info.get("stat_buff")
        if not stat_buff:
            continue
        for stat_key, buff_value in stat_buff.items():
            stats[stat_key] = stats.get(stat_key, 0.0) + buff_value
        # Recalculate attack_damage if either AD component was buffed
        # (base AD buffs exist too: Gnar's Mega form is a base-stat grant,
        # which also feeds base-AD item scalings like spellblade)
        if "base_attack_damage" in stat_buff:
            # Items that convert base AD to bonus AD (Sterak's Gage) grow
            # with a base-AD buff, exactly as in-game on Mega Gnar. The
            # accessor is linear, so the delta composes.
            steraks_delta = item_effects.steraks_bonus_ad(
                state.items, stat_buff["base_attack_damage"]
            )
            if steraks_delta:
                stats["bonus_attack_damage"] = (
                    stats.get("bonus_attack_damage", 0.0) + steraks_delta
                )
        if "bonus_attack_damage" in stat_buff or "base_attack_damage" in stat_buff:
            stats["attack_damage"] = stats.get("base_attack_damage", 0.0) + stats.get(
                "bonus_attack_damage", 0.0
            )
        # Recalculate magic penetration if it was buffed
        if "magic_penetration_percent" in stat_buff:
            resists.magic_pen_percent = (
                stats.get("magic_penetration_percent", 0.0) / 100.0
            )
            resists.resolve_magic()
        # Recalculate armor penetration if it was buffed
        if "armor_penetration_percent" in stat_buff:
            resists.armor_pen_percent = (
                stats.get("armor_penetration_percent", 0.0) / 100.0
            )
            resists.resolve_armor()
        # Recalculate attack speed and auto count if AS was buffed
        if "bonus_attack_speed" in stat_buff:
            bonus_as_pct = stat_buff["bonus_attack_speed"]
            state.attack_speed = state.attack_speed + state.attack_speed_ratio * (
                bonus_as_pct / 100.0
            )
            stats["attack_speed"] = state.attack_speed
            state.num_auto_attacks = math.floor(
                state.attack_speed
                * state.fight_duration_seconds
                * state.auto_attack_uptime
            )

    # Crit stats — needed by both ability crit scaling (rotation) and the
    # auto-attack simulation.
    state.crit_chance = min(stats.get("critical_strike_chance", 0) / 100.0, 1.0)
    state.crit_multiplier = (
        BASE_CRIT_MULTIPLIER + state.damage_effects.crit_damage_bonus
    )


@dataclass
class RotationResult:
    """Values produced by the ability rotation and consumed by later steps."""

    total_ability_casts: int = 0
    total_muramana_procs: int = 0  # one per cast; multi-cast R counts each
    first_ability_damage: float = 0.0  # Horizon Focus trigger (not amped)
    has_navori: bool = False
    navori_refund: float = 0.0
    autos_per_second: float = 0.0
    last_cast_time: float = 0.0  # timed mode: when the final recast lands


def _evaluate_cast_parts(
    state: "FightState",
    parts: tuple[DamagePart, ...],
    num_casts: int,
    ability_mr: float,
    running_damage: float,
) -> tuple[float, float]:
    """Evaluate an ability's typed damage parts over its casts.

    Returns (total mitigated damage pre-amp, first part's mitigated
    damage on the first cast — the Horizon Focus trigger value for
    mixed entries). Threads running target damage through every part
    and cast so HP-scaled parts see prior hits (Akali R2 after R1,
    Kog'Maw R shot after shot).
    """
    resists = state.resists
    target_health = state.target_health
    total = 0.0
    first_part_first_cast = 0.0
    for cast_index in range(num_casts):
        for part_index, part in enumerate(parts):
            if part.hp_scaled_damage is not None:
                hp_now = max(0.0, target_health - running_damage)
                missing_ratio = (
                    1.0 - hp_now / target_health if target_health > 0 else 1.0
                )
                raw = part.hp_scaled_damage(missing_ratio)
            else:
                raw = part.amount
            if part.crit_effectiveness > 0:
                eff = part.crit_effectiveness
                bonus_crit = state.crit_multiplier - BASE_CRIT_MULTIPLIER
                raw *= (
                    1 + eff * state.crit_chance + eff * bonus_crit * state.crit_chance
                )
            if part.damage_type == "true":
                mitigated = raw * part.count
            elif part.damage_type == "physical":
                mitigated = apply_resistance(raw, resists.effective_armor) * part.count
            else:
                mitigated = (
                    apply_resistance(raw, ability_mr) * state.magic_amp * part.count
                )
            if cast_index == 0 and part_index == 0:
                first_part_first_cast = mitigated
            total += mitigated
            running_damage += mitigated
    return total, first_part_first_cast


def _compute_ability_rotation(state: FightState) -> RotationResult:
    """Cast the ability rotation and accumulate mitigated ability damage.

    In time-based mode abilities recast when their cooldown expires within
    the fight duration (with ability haste, Spear of Shojin basic-ability
    haste, and Navori auto-attack CD refunds); in one-rotation mode each
    ability is cast exactly once. Damage arithmetic is evaluated from each
    entry's typed DamageParts (_evaluate_cast_parts) — champion-specific
    scaling lives in champion-module closures, never here. This function
    owns scheduling plus Malignance's pre/post-ult MR, Bloodletter's Vile
    Decay stacking, and target shreds applied AFTER the shredding
    ability's own damage.

    On return the resists are switched to auto-attack penetration
    (Terminus average) and Vile Decay stacks are folded into
    ``effective_mr`` — remaining damage sources occur during/after the
    full rotation.
    """
    resists = state.resists
    breakdown = state.breakdown
    ability_damages = state.ability_damages
    target_health = state.target_health
    magic_amp = state.magic_amp

    result = RotationResult()
    vile_decay_stacks = 0  # Bloodletter's Curse MR reduction stacks
    ult_cast = False  # Tracks if R has been reached in cast_order
    mitigated_damage_dealt = 0.0  # Running total for missing-HP scaling
    first_ability_key: str | None = None

    # NOTE: Blackfire Torch's 4% AP amp is baked into champion_stats, but
    # the first ability in cast_order fires before any target is burning
    # (so it should use ~4% less AP).  This is a known minor inaccuracy
    # (~2% on the first ability) that would require re-parsing ability
    # damages mid-fight to fix properly.

    # Basic attacks may reduce basic ability cooldowns.
    result.navori_refund = state.damage_effects.navori_refund_percent
    result.has_navori = result.navori_refund > 0
    result.autos_per_second = (
        state.attack_speed * state.auto_attack_uptime
        if result.navori_refund > 0
        else 0.0
    )

    basic_ability_haste = state.champion_stats.get("basic_ability_haste", 0.0)

    recast_counts: dict[str, int] = {}  # Track casts for recast pairing

    for ability_key in state.cast_order:
        if ability_key not in ability_damages:
            continue
        ability_info = ability_damages[ability_key]

        if state.auto_attacks_only:
            num_casts = 0
        elif state.one_rotation or ability_key == "R":
            num_casts = 1
        else:
            # Recasts (e.g. Q2) always match their parent ability's casts
            parent_key = ability_info.get("recast_of")
            if parent_key and parent_key in recast_counts:
                num_casts = recast_counts[parent_key]
            else:
                base_cd = ability_info.get("cooldown", 0.0)
                # Basic ability haste (e.g. Spear of Shojin) applies to Q, W, E
                total_haste = state.ability_haste
                if ability_key in ("Q", "W", "E"):
                    total_haste += basic_ability_haste
                cd = effective_cooldown(base_cd, total_haste)
                # Navori reduces basic ability CDs (Q, W, E) via auto attacks
                if (
                    result.navori_refund > 0
                    and cd > 0
                    and ability_key in ("Q", "W", "E")
                ):
                    cd = _navori_effective_cd(
                        cd, result.autos_per_second, result.navori_refund
                    )
                num_casts = 1 + int(state.fight_duration_seconds / cd) if cd > 0 else 1
                # Recasts land on cooldown: the last one at (N-1) x cd.
                # Burns use the fight-wide max as their final refresh.
                if cd > 0 and num_casts > 1:
                    result.last_cast_time = max(
                        result.last_cast_time, (num_casts - 1) * cd
                    )

        recast_counts[ability_key] = num_casts

        # Malignance MR reduction activates when R is cast
        if ability_key == "R":
            ult_cast = True

        result.total_ability_casts += num_casts
        damage_type = ability_info["damage_type"]

        # Determine base MR for this ability: pre-ult or post-ult
        current_base_mr = resists.reduced_mr if ult_cast else resists.base_mr

        # Bloodletter's Curse: magic damage abilities apply a Vile Decay
        # stack. The ability's own damage benefits from its stack.
        if resists.mr_reduction_effect and damage_type in ("magic", "mixed"):
            vile_decay_stacks = min(
                vile_decay_stacks + 1,
                resists.mr_reduction_effect.max_stacks,
            )
            mr_reduced = current_base_mr * (
                1 - resists.mr_reduction_effect.reduction_per_stack * vile_decay_stacks
            )
            mr_reduced = max(mr_reduced, 0)
            ability_mr = apply_magic_penetration(
                mr_reduced, resists.magic_pen_flat, resists.ability_magic_pen_percent
            )
        else:
            ability_mr = (
                resists.effective_mr_post_ult
                if ult_cast
                else resists.effective_mr_pre_ult
            )

        # All damage arithmetic is typed DamageParts — champion-specific
        # scaling lives in the champion module's closures, never here.
        ability_total, first_part_damage = _evaluate_cast_parts(
            state,
            ability_info["parts"],
            num_casts,
            ability_mr,
            mitigated_damage_dealt,
        )

        # Apply ability-specific damage amplifiers (e.g., Actualizer)
        ability_total *= state.ability_amp

        # Muramana procs once per ability cast. Multi-instance abilities
        # (e.g. Ahri R with 3 dashes) proc once per instance.
        cast_instances = ability_info.get("cast_instances", 1)
        result.total_muramana_procs += cast_instances * num_casts

        # Track the first ability hit for Horizon Focus (trigger, not amped).
        # For mixed-type abilities (e.g. Ahri Q: magic outgoing + true return),
        # only the first hit (magic portion) triggers — the return is amped.
        if first_ability_key is None and num_casts > 0:
            first_ability_key = ability_key
            if damage_type == "mixed":
                result.first_ability_damage = first_part_damage
            else:
                result.first_ability_damage = ability_total / num_casts

        breakdown[ability_key] = {
            "name": ability_info["name"],
            "casts": num_casts,
            "total_damage": ability_total,
            "damage_type": damage_type,
        }
        state.total_damage += ability_total
        mitigated_damage_dealt += ability_total

        # Apply target debuffs (e.g. Kog'Maw Q resistance shred) AFTER
        # computing this ability's own damage, so subsequent abilities
        # benefit from the shred but the source ability does not.
        target_debuff = ability_info.get("target_debuff")
        if target_debuff:
            armor_reduction_pct = target_debuff.get("armor_reduction_percent", 0.0)
            if armor_reduction_pct > 0:
                resists.shred_armor(armor_reduction_pct)

            mr_reduction_pct = target_debuff.get("mr_reduction_percent", 0.0)
            if mr_reduction_pct > 0:
                resists.shred_mr(mr_reduction_pct)

    # Update effective MR for non-ability damage using final Vile Decay stacks.
    # Non-ability damage occurs during/after the full rotation, so use
    # post-ult MR (Malignance reduction active).
    if resists.mr_reduction_effect and vile_decay_stacks > 0:
        mr_with_stacks = resists.reduced_mr * (
            1 - resists.mr_reduction_effect.reduction_per_stack * vile_decay_stacks
        )
        mr_with_stacks = max(mr_with_stacks, 0)
        resists.effective_mr = apply_magic_penetration(
            mr_with_stacks, resists.magic_pen_flat, resists.auto_magic_pen_percent
        )

    # Abilities are done; remaining damage (autos, on-hit, item procs)
    # switches to the auto-attack pen variants (Terminus average).
    if resists.has_terminus and resists.terminus_avg_pen > 0:
        resists.use_auto_pen()

    return result


def _add_precomputed_proc_damage(state: FightState) -> None:
    """Add fixed-count ability proc damage (e.g. Akali passive).

    Ability entries with a ``proc_count`` field represent damage that
    occurs a fixed number of times, not tied to cooldowns or auto attacks.
    """
    resists = state.resists
    for key, info in state.ability_damages.items():
        if key in state.cast_order or "on_hit" in info or "stat_buff" in info:
            continue
        proc_count = info.get("proc_count", 0)
        if proc_count <= 0:
            continue

        parts = info["parts"]
        if any(part.hp_scaled_damage is not None for part in parts):
            raise ValueError(
                f"proc entry {info.get('name', key)!r}: hp-scaled parts are "
                "not supported outside the cast rotation (procs have no "
                "target-HP context)"
            )
        dtype = info["damage_type"]
        per_proc = sum(
            _mitigate(part.amount, part.damage_type, resists, state.magic_amp)
            * part.count
            for part in parts
        )
        if per_proc <= 0:
            continue

        proc_total = per_proc * proc_count
        state.breakdown[key] = {
            "name": info.get("name", key),
            "count": proc_count,
            "damage_per_hit": per_proc,
            "total_damage": proc_total,
            "damage_type": dtype,
        }
        state.total_damage += proc_total


def _add_shaped_charge_damage(state: FightState) -> None:
    """Add ability-triggered lethality procs over the fight duration."""
    for effect in state.damage_effects.shaped_charges:
        source = effect.source
        procs = 1 + int(state.fight_duration_seconds / effect.cooldown)
        total_damage = source.raw_damage(_damage_inputs(state)) * procs
        state.breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": total_damage,
            "damage_type": source.damage_type,
        }
        state.total_damage += total_damage


@dataclass
class AutoAttackResult:
    """Values produced by the auto-attack simulation for later steps."""

    auto_damage_per_hit: float = 0.0
    double_shot_info: dict[str, Any] | None = None


def _simulate_auto_attacks(state: FightState) -> AutoAttackResult:
    """Simulate each auto attack individually, rolling (or expecting) crits.

    Handles champion auto-attack overrides (Ashe: crit chance converts to
    bonus damage on every auto), Fiendhunter Bolts empowered autos
    (guaranteed-crit true damage / reduced non-crits), Sundered Sky's
    forced first-auto crit, double-shot passives (Akshan), and the basic
    damage amplifier (Hexoptics). In deterministic mode crits are blended
    at expected value instead of rolled.
    """
    resists = state.resists
    breakdown = state.breakdown
    num_auto_attacks = state.num_auto_attacks
    empowered_autos = state.empowered_autos
    ultimate_auto_buff = state.damage_effects.ultimate_auto_buff
    crit_chance = state.crit_chance
    crit_multiplier = state.crit_multiplier
    basic_amp = state.basic_amp
    deterministic = state.deterministic
    effective_armor = resists.effective_armor

    attack_damage = state.champion_stats["attack_damage"]

    # Detect auto_attack_override (e.g. Ashe passive — crit chance converts
    # to bonus damage instead of crit strikes; Q changes AD ratio).
    auto_attack_override: dict[str, Any] | None = None
    for _ov_key, _ov_info in state.ability_damages.items():
        if "auto_attack_override" in _ov_info:
            auto_attack_override = _ov_info["auto_attack_override"]
            break

    # Detect champion double-shot passive (e.g. Akshan — second auto per
    # attack at reduced AD ratio, applies on-hits and can crit).
    double_shot_info: dict[str, Any] | None = None
    for _ds_key, _ds_info in state.ability_damages.items():
        if "double_shot" in _ds_info:
            double_shot_info = _ds_info["double_shot"]
            break

    # Simulate each auto attack individually, rolling for crits
    auto_physical_total = 0.0
    fiendhunter_true_total = 0.0
    num_crits = 0
    crit_damage_per_hit = 0.0
    non_crit_damage_per_hit = 0.0

    fh_reduced_crit = (
        ultimate_auto_buff.reduced_crit_ratio if ultimate_auto_buff is not None else 0.0
    )
    fh_true_ratio = (
        ultimate_auto_buff.natural_crit_true_damage_ratio
        if ultimate_auto_buff is not None
        else 0.0
    )

    first_auto_crit = state.damage_effects.first_auto_crit
    ss_reduced_crit = (
        first_auto_crit.reduced_crit_ratio if first_auto_crit is not None else 0.0
    )

    sundered_sky_damage_diff = 0.0  # + = bonus damage, - = lost damage

    # Ashe-style override: crit chance converts to bonus AD ratio on every
    # auto instead of random crit strikes.  ad_ratio replaces the normal 1.0.
    override_ad_ratio = 0.0
    override_crit_as_bonus = False
    if auto_attack_override:
        override_ad_ratio = auto_attack_override.get("ad_ratio", 1.0)
        override_crit_as_bonus = auto_attack_override.get("crit_as_bonus", False)

    for i in range(num_auto_attacks):
        is_empowered = ultimate_auto_buff is not None and i < empowered_autos
        is_sundered = first_auto_crit is not None and i == 0
        if deterministic:
            natural_crit = False
        else:
            natural_crit = random.random() < crit_chance

        if natural_crit:
            num_crits += 1

        if override_crit_as_bonus:
            # Crit chance converts to bonus damage on every auto (e.g. Ashe).
            # Passive: "bonus damage equal to X% of the attack's damage."
            # The bonus is multiplicative with the attack's base damage ratio,
            # because each Q arrow individually applies Frost Shot.
            # Formula: AD * ad_ratio * (1 + crit_chance * (crit_mult - 1))
            # Without IE: AD * ratio * (1 + crit_chance)
            # With IE:    AD * ratio * (1 + crit_chance * 1.30)
            bonus_crit_ratio = crit_multiplier - 1.0
            raw_phys = (
                attack_damage * override_ad_ratio * (1 + crit_chance * bonus_crit_ratio)
            )
            raw_true = 0.0
        elif is_empowered:
            if deterministic:
                # Expected-value for empowered autos
                raw_phys_crit = attack_damage * crit_multiplier
                raw_true_crit = raw_phys_crit * fh_true_ratio
                raw_phys_no = attack_damage * crit_multiplier * fh_reduced_crit
                raw_phys = crit_chance * raw_phys_crit + (1 - crit_chance) * raw_phys_no
                raw_true = crit_chance * raw_true_crit
            elif natural_crit:
                # Full crit + bonus true damage
                raw_phys = attack_damage * crit_multiplier
                raw_true = raw_phys * fh_true_ratio
            else:
                # Reduced crit (80% of normal crit damage)
                raw_phys = attack_damage * crit_multiplier * fh_reduced_crit
                raw_true = 0.0
            fiendhunter_true_total += raw_true
        elif is_sundered:
            # Sundered Sky: forced crit at reduced ratio, overrides natural crit
            raw_phys = attack_damage * crit_multiplier * ss_reduced_crit
            # Calculate what the auto would have dealt without Sundered Sky
            if deterministic:
                normal_raw = attack_damage * (
                    crit_chance * crit_multiplier + (1 - crit_chance)
                )
            elif natural_crit:
                normal_raw = attack_damage * crit_multiplier
            else:
                normal_raw = attack_damage
            sundered_sky_damage_diff = raw_phys - normal_raw
            raw_true = 0.0
        else:
            if deterministic:
                # Expected-value: blend crit and non-crit damage
                raw_phys = attack_damage * (
                    crit_chance * crit_multiplier + (1 - crit_chance)
                )
            elif natural_crit:
                raw_phys = attack_damage * crit_multiplier
            else:
                raw_phys = attack_damage
            raw_true = 0.0

        mitigated = apply_resistance(raw_phys, effective_armor)
        auto_physical_total += mitigated

        # Track per-hit damage for crits vs non-crits (last value wins;
        # all crits deal the same and all non-crits deal the same)
        if deterministic:
            non_crit_damage_per_hit = mitigated
        elif natural_crit:
            crit_damage_per_hit = mitigated
        else:
            non_crit_damage_per_hit = mitigated

    # Apply basic damage amplification (e.g. Hexoptics C44 Magnification)
    auto_physical_total *= basic_amp
    fiendhunter_true_total *= basic_amp
    crit_damage_per_hit *= basic_amp
    non_crit_damage_per_hit *= basic_amp

    auto_total = auto_physical_total
    auto_damage_per_hit = auto_total / num_auto_attacks if num_auto_attacks > 0 else 0.0
    num_non_crits = num_auto_attacks - num_crits

    breakdown["auto_attacks"] = {
        "name": "Auto Attacks",
        "count": num_auto_attacks,
        "num_crits": num_crits,
        "num_non_crits": num_non_crits,
        "crit_damage_per_hit": crit_damage_per_hit if num_crits > 0 else None,
        "non_crit_damage_per_hit": (
            non_crit_damage_per_hit if num_non_crits > 0 else None
        ),
        "damage_per_hit": auto_damage_per_hit,
        "total_damage": auto_total,
        "damage_type": "physical",
    }
    if ultimate_auto_buff is not None and empowered_autos > 0:
        breakdown["auto_attacks"]["empowered_count"] = empowered_autos

    # Sundered Sky breakdown: show the damage difference on first auto
    if first_auto_crit is not None and num_auto_attacks > 0:
        mitigated_diff = (
            apply_resistance(
                abs(sundered_sky_damage_diff),
                effective_armor,
            )
            * basic_amp
        )
        if sundered_sky_damage_diff > 0:
            ss_note = f"+{mitigated_diff:.0f} bonus damage (non-crit turned into {ss_reduced_crit * 100:.0f}% crit)"
        elif sundered_sky_damage_diff < 0:
            ss_note = f"-{mitigated_diff:.0f} lost damage (normal crit overridden to {ss_reduced_crit * 100:.0f}% crit)"
        else:
            ss_note = "No damage change"
        breakdown["sundered_sky"] = {
            "name": f"{first_auto_crit.item_name} (Lightshield Strike)",
            "total_damage": mitigated_diff,
            "detail": ss_note,
            "informational": True,
        }

    if fiendhunter_true_total > 0:
        assert ultimate_auto_buff is not None
        breakdown["fiendhunter_true_damage"] = {
            "name": f"{ultimate_auto_buff.item_name} (true damage)",
            "count": empowered_autos,
            "total_damage": fiendhunter_true_total,
            "damage_type": "true",
        }

    # Add basic damage amp breakdown entry (informational — already applied)
    if basic_amp > 1.0:
        amp_name = state.damage_effects.basic_amp_source or "Basic Damage"
        basic_amp_bonus = (
            (auto_total + fiendhunter_true_total) * (basic_amp - 1.0) / basic_amp
        )
        breakdown[f"basic_amp_{amp_name}"] = {
            "name": f"Damage Amplification ({amp_name})",
            "multiplier": basic_amp,
            "total_damage": basic_amp_bonus,
            "detail": "included in auto attack totals above",
            "informational": True,
        }

    # Double shot: second auto per attack at reduced AD (e.g. Akshan passive)
    double_shot_total = 0.0
    if double_shot_info and num_auto_attacks > 0:
        ds_ratio = double_shot_info.get("ad_ratio", 0.5)
        ds_crits = 0
        for i in range(num_auto_attacks):
            ds_ad = attack_damage * ds_ratio
            if deterministic:
                ds_crit = False
                raw_ds = ds_ad * (crit_chance * crit_multiplier + (1 - crit_chance))
            else:
                ds_crit = random.random() < crit_chance
                if ds_crit:
                    ds_crits += 1
                    raw_ds = ds_ad * crit_multiplier
                else:
                    raw_ds = ds_ad
            double_shot_total += apply_resistance(raw_ds, effective_armor) * basic_amp

        ds_non_crits = num_auto_attacks - ds_crits
        breakdown["double_shot"] = {
            "name": double_shot_info.get("name", "Double Shot"),
            "count": num_auto_attacks,
            "num_crits": ds_crits,
            "num_non_crits": ds_non_crits,
            "total_damage": double_shot_total,
            "damage_type": "physical",
        }

    state.total_damage += auto_total + fiendhunter_true_total + double_shot_total

    return AutoAttackResult(
        auto_damage_per_hit=auto_damage_per_hit,
        double_shot_info=double_shot_info,
    )


@dataclass
class OnHitResult:
    """Values produced by on-hit layering and consumed by later steps."""

    phantom_hit_count: int = 0
    phantom_hit_autos: set[int] = field(default_factory=set)
    static_on_hit_per_hit: float = 0.0  # mitigated, for HP simulations
    current_health_on_hit_avg: float = 0.0
    has_current_health_on_hit: bool = False


def _layer_on_hit_effects(state: FightState, autos: AutoAttackResult) -> OnHitResult:
    """Layer per-hit on-hit damage (items and abilities) onto the autos.

    Computes Guinsoo's Rageblade phantom hits centrally — they apply ALL
    on-hit effects an additional time — and counts double-shot extra
    applications. Constant-damage on-hit items and ability on-hits
    (e.g. Vayne W stacks, Viego passive) multiply per-hit damage by the
    total application count; BoRK is simulated per-auto against the
    target's decreasing current HP.
    """
    resists = state.resists
    breakdown = state.breakdown
    num_auto_attacks = state.num_auto_attacks
    magic_amp = state.magic_amp

    on_hit_total = 0.0
    current_health_effect = next(
        (
            effect
            for effect in state.damage_effects.per_hits
            if effect.tracks_current_health
        ),
        None,
    )
    result = OnHitResult(has_current_health_on_hit=current_health_effect is not None)

    # Calculate Guinsoo's Rageblade phantom hits centrally — these apply
    # ALL on-hit effects (items AND abilities) an additional time.
    result.phantom_hit_count, result.phantom_hit_autos = _calculate_phantom_hits(
        num_auto_attacks, state.damage_effects.phantom_hit
    )
    # Double shot applies on-hit effects an additional time per auto
    double_shot_extra = num_auto_attacks if autos.double_shot_info else 0
    on_hit_hits = num_auto_attacks + result.phantom_hit_count + double_shot_extra

    # Process fixed-formula per-hit effects. Current-health effects are
    # simulated below because each application changes the next one's input.
    damage_inputs = _damage_inputs(state)
    for effect in state.damage_effects.per_hits:
        if effect.tracks_current_health:
            continue

        source = effect.source
        raw_per_hit = source.raw_damage(damage_inputs)
        if raw_per_hit <= 0:
            continue

        per_hit = _mitigate(raw_per_hit, source.damage_type, resists, magic_amp)

        # All on-hit items get phantom hit bonus procs.
        hits = on_hit_hits
        item_damage = per_hit * hits
        on_hit_total += item_damage
        result.static_on_hit_per_hit += per_hit

        breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "count": hits,
            "damage_per_hit": per_hit,
            "total_damage": item_damage,
            "damage_type": source.damage_type,
        }

    # Process ability on-hit effects (Case 2: abilities that add damage per
    # auto attack, e.g. Viego passive % health on-hit). These are passed in
    # ability_damages with an "on_hit" key containing per-hit damage info.
    # Phantom hits also apply these an additional time.
    for ability_key, ability_info in state.ability_damages.items():
        on_hit_data = ability_info.get("on_hit")
        if not on_hit_data or num_auto_attacks == 0:
            continue

        raw_per_hit = on_hit_data.get("damage_per_hit", 0.0)
        if raw_per_hit <= 0:
            continue

        dmg_type = on_hit_data.get("damage_type", "magic")
        per_hit = _mitigate(raw_per_hit, dmg_type, resists, magic_amp)

        hits = on_hit_hits
        ability_on_hit_damage = per_hit * hits
        on_hit_total += ability_on_hit_damage
        result.static_on_hit_per_hit += per_hit

        ability_name = on_hit_data.get("name", f"{ability_key} (on-hit)")
        stacks_required = on_hit_data.get("stacks_required", 0)
        if stacks_required > 1:
            # Stack-based on-hit (e.g. Vayne W): display as procs
            proc_count = hits // stacks_required
            damage_per_proc = per_hit * stacks_required
            breakdown[f"on_hit_ability_{ability_key}"] = {
                "name": ability_name,
                "count": proc_count,
                "damage_per_hit": damage_per_proc,
                "total_damage": ability_on_hit_damage,
                "damage_type": dmg_type,
                "unit": "procs",
            }
        else:
            breakdown[f"on_hit_ability_{ability_key}"] = {
                "name": ability_name,
                "count": hits,
                "damage_per_hit": per_hit,
                "total_damage": ability_on_hit_damage,
                "damage_type": dmg_type,
            }

    # BoRK: simulate with decreasing target current HP per auto attack.
    # Phantom hit autos cause BoRK to proc twice (at different current HP).
    # Double shot (e.g. Akshan) also procs BoRK an extra time per auto.
    if current_health_effect is not None and num_auto_attacks > 0:
        current_health_total, current_health_hits = _simulate_current_health_on_hit(
            effect=current_health_effect,
            base_inputs=_damage_inputs(state),
            target_health=state.target_health,
            num_auto_attacks=num_auto_attacks,
            auto_damage_per_hit=autos.auto_damage_per_hit,
            other_on_hit_per_hit=result.static_on_hit_per_hit,
            resists=resists,
            magic_amp=magic_amp,
            phantom_hit_autos=result.phantom_hit_autos,
            double_hit_all=autos.double_shot_info is not None,
        )
        result.current_health_on_hit_avg = (
            current_health_total / current_health_hits
            if current_health_hits > 0
            else 0.0
        )
        on_hit_total += current_health_total

        source = current_health_effect.source
        breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "count": current_health_hits,
            "damage_per_hit": result.current_health_on_hit_avg,
            "total_damage": current_health_total,
            "damage_type": source.damage_type,
        }

    state.total_damage += on_hit_total
    return result


@dataclass
class SpellbladeResult:
    """Values produced by the spellblade step and consumed by later steps."""

    item: str | None = None
    procs: int = 0
    damage_per_proc: float = 0.0  # mitigated damage per proc
    double_on_hit_procs: int = 0  # extra on-hit stacks (Dusk and Dawn + double shot)
    expose_weakness_melee: float = 0.0
    expose_weakness_ranged: float = 0.0


def _add_spellblade_damage(
    state: FightState,
    rotation: RotationResult,
    autos: AutoAttackResult,
    on_hits: OnHitResult,
) -> SpellbladeResult:
    """Add spellblade proc damage and Dusk and Dawn's double on-hit.

    Procs are limited by ability casts, the spellblade's cooldown plus
    weave delay, and the fight's auto count. Also totals the extra on-hit
    stack applications (Dusk and Dawn double on-hits, double-shot autos)
    that accelerate Kraken Slayer / Hullbreaker stacking later.
    """
    resists = state.resists
    result = SpellbladeResult()

    effect = state.damage_effects.spellblade
    if effect is not None:
        result.item = effect.source.item_name
        result.expose_weakness_melee = effect.expose_weakness_melee
        result.expose_weakness_ranged = effect.expose_weakness_ranged

    if effect is not None and state.num_auto_attacks > 0:
        source = effect.source
        raw_sb = source.raw_damage(_damage_inputs(state))
        effective_sb_cd = effect.cooldown + effect.weave_delay

        result.damage_per_proc = _mitigate(
            raw_sb, source.damage_type, resists, state.magic_amp
        )

        # Number of procs: limited by ability casts and cooldown
        result.procs = min(
            rotation.total_ability_casts,
            1 + int(state.fight_duration_seconds / effective_sb_cd),
            state.num_auto_attacks,
        )
        sb_total = result.damage_per_proc * result.procs

        state.breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "procs": result.procs,
            "damage_per_proc": result.damage_per_proc,
            "total_damage": sb_total,
            "damage_type": source.damage_type,
        }
        state.total_damage += sb_total

    # ── Double on-hit from spellblade (Dusk and Dawn) ──
    if effect is not None and result.procs > 0:
        if effect.double_on_hit:
            result.double_on_hit_procs = result.procs
            extra_on_hit = on_hits.static_on_hit_per_hit * result.double_on_hit_procs

            # Current-health extra procs use the fight's average per-hit damage.
            if on_hits.has_current_health_on_hit and state.num_auto_attacks > 0:
                extra_on_hit += (
                    on_hits.current_health_on_hit_avg * result.double_on_hit_procs
                )

            if extra_on_hit > 0:
                state.breakdown[f"double_on_hit_{result.item}"] = {
                    "name": f"{result.item} (Double On-Hit)",
                    "procs": result.double_on_hit_procs,
                    "total_damage": extra_on_hit,
                    "damage_type": "mixed",
                }
                state.total_damage += extra_on_hit

    # Double shot on-hit stacking: each auto generates an extra on-hit
    # application, accelerating Kraken Slayer / Hullbreaker procs.
    if autos.double_shot_info:
        result.double_on_hit_procs += state.num_auto_attacks

    return result


def _add_burn_damage(state: FightState, rotation: RotationResult) -> None:
    """Add burn/DoT item damage: burns, Immolate, and Unending Despair.

    Burns refresh on each ability hit (and on Malignance's Hatefog DoT),
    so the effective burn window stretches across the rotation's cast
    spread — capped at the fight duration outside one-rotation mode.
    """
    resists = state.resists
    ability_damages = state.ability_damages

    for effect in state.damage_effects.burns:
        source = effect.source
        raw_burn = source.raw_damage(_damage_inputs(state))
        burn_duration = effect.duration
        # Burn refreshes on each ability hit (including R dashes —
        # only multi-instance Rs declare cast_instances; default 1).
        r_info = ability_damages.get("R")
        r_extra = 0
        if r_info:
            r_extra = r_info.get("cast_instances", 1) - 1
        # Estimate time from first to last ability hit.  In a fast
        # one-rotation combo, casts are ~0.5s apart (GCD-limited).
        inter_cast_delay = 0.5
        cast_spread = (rotation.total_ability_casts - 1 + r_extra) * inter_cast_delay

        # Other item DoTs (e.g. Malignance Hatefog) deal ability
        # damage that also refreshes burns.  Hatefog starts at R cast
        # (not at fight start), so its refresh window begins partway
        # through the cast_spread.
        # In timed mode, abilities recast on cooldown across the whole
        # fight — the last recast (rotation.last_cast_time) refreshes
        # the burn far beyond the GCD combo spread.
        dot_refresh_end = max(cast_spread, rotation.last_cast_time)
        for ultimate_proc in state.damage_effects.ultimate_procs:
            if "R" in ability_damages:
                # R1 lands r_extra dashes (x0.5s each) before the last hit
                r_start = cast_spread - r_extra * inter_cast_delay
                hatefog_end = r_start + ultimate_proc.duration
                dot_refresh_end = max(dot_refresh_end, hatefog_end)

        if state.one_rotation:
            effective_burn_time = dot_refresh_end + burn_duration
        else:
            effective_burn_time = min(
                dot_refresh_end + burn_duration,
                state.fight_duration_seconds,
            )
        if effective_burn_time > burn_duration:
            burn_multiplier = effective_burn_time / burn_duration
            raw_burn *= burn_multiplier
        burn_mitigated = _mitigate(raw_burn, "magic", resists, state.magic_amp)

        state.breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": burn_mitigated,
            "damage_type": source.damage_type,
        }
        state.total_damage += burn_mitigated

    for source in state.damage_effects.immolates:
        raw_immolate = source.raw_damage(_damage_inputs(state))
        raw_immolate *= state.fight_duration_seconds
        immolate_mitigated = _mitigate(
            raw_immolate, source.damage_type, resists, state.magic_amp
        )

        state.breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": immolate_mitigated,
            "damage_type": source.damage_type,
        }
        state.total_damage += immolate_mitigated

    for effect in state.damage_effects.periodic:
        source = effect.source
        procs = (
            int(state.fight_duration_seconds / effect.interval)
            if effect.interval > 0
            else 0
        )
        raw_periodic = source.raw_damage(_damage_inputs(state)) * procs
        if raw_periodic > 0:
            periodic_mitigated = _mitigate(
                raw_periodic, source.damage_type, resists, state.magic_amp
            )
            state.breakdown[source.breakdown_key] = {
                "name": source.display_name,
                "total_damage": periodic_mitigated,
                "damage_type": source.damage_type,
            }
            state.total_damage += periodic_mitigated


def _add_item_proc_damage(state: FightState) -> None:
    """Add proc-type item damage and ultimate-triggered procs (Malignance)."""
    resists = state.resists

    for effect in state.damage_effects.cooldown_procs:
        if effect.late_phase:
            continue
        source = effect.source
        raw_proc = source.raw_damage(_damage_inputs(state))
        if effect.repeat_on_cooldown:
            raw_proc *= 1 + int(state.fight_duration_seconds / effect.cooldown)
        proc_mitigated = _mitigate(
            raw_proc, source.damage_type, resists, state.magic_amp
        )

        # Stormsurge and Zaz'Zak deal ability damage — amplified by Actualizer
        if source.is_ability_damage:
            proc_mitigated *= state.ability_amp

        state.breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": proc_mitigated,
            "damage_type": source.damage_type,
        }
        state.total_damage += proc_mitigated

    # ── Ultimate-triggered procs (Malignance) ──
    for effect in state.damage_effects.ultimate_procs:
        # Only triggers if R was cast
        r_info = state.ability_damages.get("R")
        if r_info is None:
            continue
        source = effect.source
        raw = source.raw_damage(_damage_inputs(state))

        # Hatefog zone refreshes on each R dash.  Effective duration is
        # the time from R1 to R_last plus the base zone duration.
        hatefog_duration = effect.duration
        r_total_casts = r_info.get("cast_instances", 1)
        r_dash_spread = (r_total_casts - 1) * 0.5  # ~0.5s between dashes
        effective_hatefog = r_dash_spread + hatefog_duration
        raw *= effective_hatefog / hatefog_duration

        ult_proc_mitigated = _mitigate(raw, "magic", resists, state.magic_amp)

        state.breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": ult_proc_mitigated,
            "damage_type": source.damage_type,
        }
        state.total_damage += ult_proc_mitigated


def _add_item_active_damage(state: FightState) -> None:
    """Add active-item damage (skipped when actives are excluded)."""
    if not state.include_actives:
        return
    resists = state.resists
    for source in state.damage_effects.actives:
        raw_active = source.raw_damage(_damage_inputs(state))
        active_mitigated = _mitigate(
            raw_active, source.damage_type, resists, state.magic_amp
        )

        state.breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": active_mitigated,
            "damage_type": source.damage_type,
        }
        state.total_damage += active_mitigated


def _add_single_proc_on_hits(
    state: FightState,
    rotation: RotationResult,
    autos: AutoAttackResult,
    on_hits: OnHitResult,
    spellblade: SpellbladeResult,
) -> None:
    """Add items that proc once (or on a stack counter) rather than per hit.

    First-hit procs (Dead Man's Plate, Heartsteel, energized Rapid
    Firecannon / Stormrazor / Voltaic Cyclosword / Statikk Shiv), the
    Titanic Hydra Crescent active, stack-counter procs simulated against
    the target's dropping HP (Kraken Slayer, Hullbreaker — phantom hits
    and double on-hits each grant an extra stack), Eclipse, and
    Muramana's per-ability-cast Shock damage.
    """
    resists = state.resists
    breakdown = state.breakdown
    num_auto_attacks = state.num_auto_attacks

    if num_auto_attacks > 0:
        inputs = _damage_inputs(state)
        for effect in state.damage_effects.first_autos:
            source = effect.source
            procs = min(effect.max_procs, num_auto_attacks)
            raw_damage = source.raw_damage(inputs) * procs
            mitigated = _mitigate(
                raw_damage, source.damage_type, resists, state.magic_amp
            )
            breakdown[source.breakdown_key] = {
                "name": source.display_name,
                "procs": procs,
                "total_damage": mitigated,
                "damage_type": source.damage_type,
            }
            state.total_damage += mitigated

    if num_auto_attacks > 0:
        inputs = _damage_inputs(state)
        for effect in state.damage_effects.auto_cooldowns:
            source = effect.source
            procs = (
                1 + int(state.fight_duration_seconds / effect.cooldown)
                if effect.cooldown > 0
                else 1
            )
            procs = min(procs, num_auto_attacks)
            raw_damage = source.raw_damage(inputs) * procs
            mitigated = _mitigate(
                raw_damage, source.damage_type, resists, state.magic_amp
            )
            breakdown[source.breakdown_key] = {
                "name": source.display_name,
                "procs": procs,
                "total_damage": mitigated,
                "damage_type": source.damage_type,
            }
            state.total_damage += mitigated

    if num_auto_attacks > 0:
        other_on_hit_per_hit = on_hits.static_on_hit_per_hit
        if on_hits.has_current_health_on_hit and on_hits.current_health_on_hit_avg > 0:
            other_on_hit_per_hit += on_hits.current_health_on_hit_avg

        for effect in state.damage_effects.stacking_on_hits:
            source = effect.source
            procs, proc_autos = _calculate_stacking_procs(
                num_auto_attacks,
                on_hits.phantom_hit_autos,
                spellblade.double_on_hit_procs,
                hits_required=effect.hits_required,
            )
            if procs <= 0:
                continue

            if effect.tracks_target_health:
                total_damage = _simulate_stacking_on_hit_damage(
                    effect,
                    _damage_inputs(state),
                    state.target_health,
                    num_auto_attacks,
                    autos.auto_damage_per_hit,
                    other_on_hit_per_hit,
                    resists,
                    state.magic_amp,
                    proc_autos,
                )
            else:
                raw = source.raw_damage(_damage_inputs(state)) * procs
                total_damage = _mitigate(
                    raw, source.damage_type, resists, state.magic_amp
                )

            breakdown[source.breakdown_key] = {
                "name": source.display_name,
                "procs": procs,
                "damage_per_proc": total_damage / procs,
                "total_damage": total_damage,
                "damage_type": source.damage_type,
            }
            state.total_damage += total_damage

    for effect in state.damage_effects.cooldown_procs:
        if not effect.late_phase:
            continue
        source = effect.source
        procs = (
            1 + int(state.fight_duration_seconds / effect.cooldown)
            if effect.repeat_on_cooldown
            else 1
        )
        raw = source.raw_damage(_damage_inputs(state)) * procs
        total_damage = _mitigate(raw, source.damage_type, resists, state.magic_amp)
        breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": total_damage,
            "damage_type": source.damage_type,
        }
        state.total_damage += total_damage

    for source in state.damage_effects.per_ability_hits:
        raw = source.raw_damage(_damage_inputs(state))
        raw *= rotation.total_muramana_procs
        total_damage = _mitigate(raw, source.damage_type, resists, state.magic_amp)
        breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": total_damage,
            "damage_type": source.damage_type,
        }
        state.total_damage += total_damage


def _add_shadowflame_cinderbloom(state: FightState) -> None:
    """Add Shadowflame's Cinderbloom bonus (magic/true crits below 40% HP)."""
    effect = state.damage_effects.magic_true_crit
    if effect is None:
        return
    shadowflame_bonus = _calculate_shadowflame_bonus(
        effect,
        state.breakdown,
        state.ability_damages,
        state.target_health,
        state.cast_order,
    )
    if shadowflame_bonus > 0:
        state.breakdown[f"shadowflame_{effect.item_name}"] = {
            "name": f"{effect.item_name} (Cinderbloom)",
            "total_damage": shadowflame_bonus,
            "damage_type": "mixed",
        }
        state.total_damage += shadowflame_bonus


def _add_expose_weakness(
    state: FightState,
    autos: AutoAttackResult,
    spellblade: SpellbladeResult,
) -> None:
    """Add Bloodsong's Expose Weakness amp on damage after the first proc."""
    if not (spellblade.item and spellblade.procs > 0):
        return
    expose_rate = (
        spellblade.expose_weakness_melee
        if state.is_melee
        else spellblade.expose_weakness_ranged
    )
    if expose_rate <= 0:
        return

    # First ability cast + first auto + first spellblade proc
    # occur before Expose Weakness is applied and don't benefit.
    breakdown = state.breakdown
    first_ability_key = next((k for k in state.cast_order if k in breakdown), None)
    damage_before_expose = 0.0
    if first_ability_key:
        entry = breakdown[first_ability_key]
        casts = entry.get("casts", 1)
        if casts > 0:
            damage_before_expose += entry["total_damage"] / casts
    damage_before_expose += autos.auto_damage_per_hit
    damage_before_expose += spellblade.damage_per_proc

    amped_damage = max(0, state.total_damage - damage_before_expose)
    expose_bonus = amped_damage * expose_rate

    breakdown[f"expose_weakness_{spellblade.item}"] = {
        "name": f"{spellblade.item} (Expose Weakness)",
        "amplifier": 1.0 + expose_rate,
        "total_damage": expose_bonus,
        "damage_type": "mixed",
    }
    state.total_damage += expose_bonus


def _apply_damage_amplifiers(state: FightState, rotation: RotationResult) -> None:
    """Apply fight-wide damage amplifiers and their breakdown rows.

    General amps (Lord Dominik's Regards, Riftmaker-class) multiply the
    whole running total, one ``damage_amp_<source>`` row per source. The
    Actualizer ability amp was already applied per-ability/per-proc, so
    its row is informational only. Horizon Focus amplifies everything
    except the first ability cast (the trigger).
    """
    breakdown = state.breakdown

    amp_sources = [
        (
            effect.item_name,
            effect.amp_fraction(
                state.fight_duration_seconds,
                max(0, state.target_bonus_health),
            ),
        )
        for effect in state.damage_effects.damage_amplifiers
    ]
    amp = 1.0 + sum(source_amp for _, source_amp in amp_sources)
    if amp > 1.0:
        amp_bonus = state.total_damage * (amp - 1.0)
        # Create per-source breakdown entries
        for source_name, source_amp in amp_sources:
            if source_amp > 0:
                source_bonus = state.total_damage * source_amp
                breakdown[f"damage_amp_{source_name}"] = {
                    "name": f"Damage Amplification ({source_name})",
                    "multiplier": 1.0 + source_amp,
                    "total_damage": source_bonus,
                }
        state.total_damage += amp_bonus

    # Actualizer ability damage amp — show as separate breakdown entry.
    # The amp was already applied per-ability in the rotation and per-proc
    # in the item-proc step, so this entry is informational only (damage
    # already counted).
    if state.ability_amp > 1.0:
        # Sum exactly the rows the amp multiplied: rotation ability rows
        # (cast_order keys) and is_ability_damage item procs
        # (Stormsurge / Zaz'Zak). Burns, on-hits, spellblades and
        # other item rows are never ability-amped and must not be counted.
        amped_keys = set(state.cast_order)
        amped_keys.update(
            effect.source.breakdown_key
            for effect in state.damage_effects.cooldown_procs
            if effect.source.is_ability_damage
        )
        amped_base = sum(
            v.get("total_damage", 0)
            for k, v in breakdown.items()
            if isinstance(v, dict) and k in amped_keys
        )
        # The amplified damage = base * amp, so the amp contribution is
        # base * (amp - 1) / amp  (since base already includes the amp).
        actualizer_bonus = amped_base * (state.ability_amp - 1.0) / state.ability_amp
        amp_name = state.damage_effects.ability_amp_source or "Ability Damage"
        breakdown[f"ability_amp_{amp_name}"] = {
            "name": f"Damage Amplification ({amp_name})",
            "multiplier": state.ability_amp,
            "total_damage": actualizer_bonus,
            "detail": "included in ability/proc totals above",
            "informational": True,
        }

    # Horizon Focus Hypershot: amp all damage except the first ability cast
    # (the first ability triggers the mark; its own damage is not amped).
    if state.hypershot_amp > 1.0:
        amped_damage = state.total_damage - rotation.first_ability_damage
        hypershot_bonus = amped_damage * (state.hypershot_amp - 1.0)
        breakdown["damage_amp_Horizon Focus"] = {
            "name": "Damage Amplification (Horizon Focus)",
            "multiplier": state.hypershot_amp,
            "total_damage": hypershot_bonus,
        }
        state.total_damage += hypershot_bonus


def _add_execute_display(state: FightState) -> None:
    """Add The Collector's execute-threshold display row.

    The execute damage is NOT added to the total; the row displays the HP
    threshold at which the target would be executed.
    """
    execute = state.damage_effects.execute
    if execute is not None:
        collector_threshold = state.target_health * execute.threshold
        threshold_pct = (
            collector_threshold / state.target_health * 100
            if state.target_health
            else 0.0
        )
        state.breakdown["execute"] = {
            "name": f"{execute.item_name} (Execute)",
            "total_damage": 0.0,
            "damage_type": "true",
            "execution_threshold_hp": collector_threshold,
            "detail": (
                f"{execute.item_name} Execution Threshold: "
                f"{collector_threshold:.0f} HP "
                f"({threshold_pct:.0f}% of {state.target_health:.0f})"
            ),
            "damage_display": f"{collector_threshold:.0f} HP",
            "informational": True,
        }


def _collect_fight_notes(
    state: FightState,
    rotation: RotationResult,
    on_hits: OnHitResult,
) -> None:
    """Collect the notes documenting conditional item assumptions."""
    notes = state.notes
    notes.extend(state.damage_effects.conditional_notes)

    if (
        rotation.has_navori
        and rotation.navori_refund > 0
        and rotation.autos_per_second > 0
    ):
        cooldown_refund_source = state.damage_effects.cooldown_refund_source
        assert cooldown_refund_source is not None
        notes.append(
            f"{cooldown_refund_source}: basic ability CDs reduced by "
            f"{rotation.navori_refund:.0%} per auto attack "
            f"({rotation.autos_per_second:.2f} autos/sec effective)."
        )

    if on_hits.phantom_hit_count > 0:
        phantom_hit = state.damage_effects.phantom_hit
        assert phantom_hit is not None
        notes.append(
            f"{phantom_hit.item_name}: {on_hits.phantom_hit_count} phantom hit(s) — "
            f"all on-hit effects apply an additional time on autos "
            f"#{', #'.join(str(a + 1) for a in sorted(on_hits.phantom_hit_autos))}."
        )


def calculate_fight_damage(
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    items: list[dict[str, Any]],
    config: FightConfig,
) -> dict[str, Any]:
    """Calculate total damage dealt over a fight duration.

    In time-based mode, abilities recast when their cooldown expires within
    the fight duration. In one-rotation mode, each ability is cast exactly
    once (fight_duration still matters for burns/DoTs/procs).

    Ability haste is read from ``champion_stats`` (keys ``ability_haste``
    and ``basic_ability_haste``), like every other champion stat.

    Args:
        champion_stats: Calculated champion stats dictionary.
        ability_damages: Parsed ability damage dictionary.
        items: List of item data for checking passives.
        config: The fight's :class:`FightConfig` (target, duration, mode).

    Returns:
        Dictionary with damage breakdown and total.
    """
    # ── Resolve resistances, penetration, amps, and attack timing ───────
    state = _resolve_combat_state(champion_stats, ability_damages, items, config)

    # ── Stat buffs from abilities (e.g. Aatrox R bonus AD) ─────────────
    _apply_stat_buff_ultimates(state)

    # ── Ability rotation, precomputed procs, and Shaped Charge ──────────
    rotation = _compute_ability_rotation(state)
    _add_precomputed_proc_damage(state)
    _add_shaped_charge_damage(state)

    # ── Auto attacks (per-auto crit simulation) ─────────────────────────
    autos = _simulate_auto_attacks(state)

    # ── On-hit damage layered onto the autos ────────────────────────────
    on_hits = _layer_on_hit_effects(state, autos)

    # ── Spellblade + Dusk and Dawn double on-hit ────────────────────────
    spellblade = _add_spellblade_damage(state, rotation, autos, on_hits)

    # ── Burn / DoT item damage ──────────────────────────────────────────
    _add_burn_damage(state, rotation)

    # ── Item procs (including ult-triggered Malignance) ─────────────────
    _add_item_proc_damage(state)

    # ── Active item damage ──────────────────────────────────────────────
    _add_item_active_damage(state)

    # ── Single-proc on-hits, Shadowflame, and Expose Weakness ───────────
    _add_single_proc_on_hits(state, rotation, autos, on_hits, spellblade)
    _add_shadowflame_cinderbloom(state)
    _add_expose_weakness(state, autos, spellblade)

    # ── Fight-wide damage amplifiers ────────────────────────────────────
    _apply_damage_amplifiers(state, rotation)

    # ── Execute threshold display (The Collector) ───────────────────────
    _add_execute_display(state)

    # ── Notes for conditional item assumptions ──────────────────────────
    _collect_fight_notes(state, rotation, on_hits)

    return {
        "breakdown": state.breakdown,
        "total_damage": state.total_damage,
        "effective_mr": state.resists.effective_mr,
        "effective_armor": state.resists.effective_armor,
        "notes": state.notes,
        # Exposed for champion-specific ability calculators (Case 1: stack
        # acceleration). Champions like Vayne can check which autos grant
        # double stacks to calculate ability procs more accurately.
        "phantom_hit_autos": on_hits.phantom_hit_autos,
        "phantom_hit_count": on_hits.phantom_hit_count,
    }


def split_auto_vs_ability(
    breakdown: dict[str, dict[str, Any]],
) -> tuple[float, float]:
    """Split a fight breakdown into (auto_attack_damage, ability_damage).

    Attribution rules, keyed off the breakdown key names this module emits:

    - Entries marked ``informational`` are display-only — their damage is
      zero or already counted in other rows (the engine marks its amp
      summaries, the execute-threshold row, and the Sundered Sky row
      this way) — so they are skipped.
    - ``auto_attacks``, ``fiendhunter_true_damage``, and keys prefixed
      ``on_hit_`` or ``spellblade_`` count as auto-attack damage.
    - ``damage_amp_<source>`` rows amplify both buckets, so their damage
      is redistributed proportionally to the pre-amp auto/ability ratio
      (dropped entirely if that total is zero).
    - Everything else counts as ability damage.
    """
    auto_attack_damage = 0.0
    ability_damage = 0.0
    redistributed_damage = 0.0  # damage_amp_<source> rows

    on_hit_prefixes = ("on_hit_", "spellblade_")

    for key, entry in breakdown.items():
        dmg = entry.get("total_damage", 0.0)
        if entry.get("informational"):
            continue
        if (
            key == "auto_attacks"
            or key == "fiendhunter_true_damage"
            or key.startswith(on_hit_prefixes)
        ):
            auto_attack_damage += dmg
        elif key.startswith("damage_amp_"):
            # Amplifiers scale both buckets — redistribute proportionally
            # below instead of attributing to either bucket.
            redistributed_damage += dmg
        else:
            ability_damage += dmg

    # Damage amplification — split proportionally.
    pre_amp_total = auto_attack_damage + ability_damage
    if pre_amp_total > 0:
        auto_ratio = auto_attack_damage / pre_amp_total
        auto_attack_damage += redistributed_damage * auto_ratio
        ability_damage += redistributed_damage * (1 - auto_ratio)

    return auto_attack_damage, ability_damage
