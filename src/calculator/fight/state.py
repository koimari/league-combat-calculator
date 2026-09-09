"""The mutable record every step function is threaded through, and the three projections of it."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .. import item_effects, rune_effects
from ..interpreters import crit_profile
from .config import BASE_CRIT_MULTIPLIER
from .declarations import BuildDeclarations
from .empower_declaration import BurstSwingSchedule
from .resists import Resists
from .results import FerocityTimeline, StackTimeline


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
    # The declared strikes this build brings, resolved through their rules.
    # They are not part of the registry's build projection: a projection that
    # defaulted them to an empty tuple would price a whole family at zero with
    # nothing saying so.
    per_hit_strikes: tuple[item_effects.PerHitEffect, ...]
    # The declared on-hits this fight's own target class arms, already
    # filtered to it: a champion-class fight arms none, because no
    # declaration names the champion class.
    class_restricted_strikes: tuple[item_effects.PerHitEffect, ...]
    # The actives this build declares, resolved through their rules.  Off the
    # registry's build projection for the same reason the strikes are: a
    # projection field that defaulted to an empty tuple would price the whole
    # family at zero with nothing saying so.
    item_actives: tuple[item_effects.DamageSource, ...]
    # The clock-driven strikes, cast-triggered procs, charged strikes, armour
    # shred and secondary-target bolts this build declares.
    declared: BuildDeclarations
    # The one spellblade this build arms, resolved through its rule.
    item_spellblade: "item_effects.SpellbladeEffect | None"
    cast_order: list[str]
    target_health: float
    target_bonus_health: float
    fight_duration_seconds: float
    auto_attack_uptime: float
    item_options: Mapping[str, Mapping[str, int | float]] | None
    # P3 package 3V: the champion scenario options (p_ferocity) — the
    # live Ferocity walk seeds its stack state from the same option the
    # module parse consumed.
    champion_options: Mapping[str, Any]
    actualizer_active_until: float
    actualizer_basic_cooldown_multiplier: float
    actualizer_resource_cost_multiplier: float
    ability_haste: float
    one_rotation: bool
    include_actives: bool
    auto_attacks_only: bool
    ultimate_recasts: bool
    deterministic: bool
    is_melee: bool
    level: int
    enforce_resource_limits: bool
    resource_restore_events: tuple[tuple[float, float], ...]
    resource_ledger_owner: str
    target_basic_damage_multiplier: float
    target_basic_damage_flat_reduction: float
    target_basic_damage_flat_reduction_cap: float
    target_champion_damage_flat_reduction: float
    target_champion_dot_damage_flat_reduction: float
    target_critical_strike_damage_multiplier: float
    roster_target_index: int
    roster_target_count: int
    # P3-3M: the target's actor class, mirrored from the fight config. The
    # ONE home every class-restricted effect reads.
    target_class: str
    # ── Resolved combat numbers ───────────────────────────────────────────
    resists: Resists
    magic_amp: float  # Abyssal Mask
    # The two per-part amps, resolved from their declarations: the
    # multiplier each part they price is worth, and the holder whose
    # breakdown row reports it.  ``""`` is the no-holder answer and is only
    # ever paired with a multiplier of exactly 1.0.
    ability_amp: float
    ability_amp_owner: str
    basic_amp: float
    basic_amp_owner: str
    # ── Attack timing ─────────────────────────────────────────────────────
    attack_speed: float
    attack_speed_ratio: float
    num_auto_attacks: int
    empowered_autos: int
    # P1 Slice 11 (Ashe Q active window): the flurry/AS window [0, end) —
    # the first ``q_window_autos`` swings ride the buffed rate + flurry
    # ratio, the rest revert to the base rate + the normal 1.0 ratio from
    # ``q_window_end`` (end-exclusive).
    q_window_autos: int = 0
    q_window_pre_autos: int = 0
    q_window_start: float = 0.0
    q_window_end: float = 0.0
    q_window_base_rate: float = 0.0
    # ── Crit (resolved after stat-buff ultimates) ─────────────────────────
    crit_chance: float = 0.0
    crit_multiplier: float = BASE_CRIT_MULTIPLIER
    # Lich Bane's sourced empowered-attack speed is applied to the authored
    # swing following each accepted Spellblade proc.  The proc timestamps are
    # prepared after the cast timeline exists and before autos are priced.
    spellblade_proc_times: tuple[float, ...] = ()
    spellblade_attack_speed_percent: float = 0.0
    # ── The compiled rune page, keystone first (empty when none selected) ──
    runes: "tuple[rune_effects.RuneEffect, ...]" = ()
    # The page's declared options, by rune. A rune formula reads them when it
    # resolves — the same values ``stats.py`` hands a stat grant — so a fight
    # priced with an option set and one priced without differ by the option
    # alone.
    rune_options: "Mapping[str, Mapping[str, float]]" = MappingProxyType({})
    # ── Keystone rune (compiled proc; None when no keystone equipped) ─────
    keystone_effect: "rune_effects.RuneEffect | None" = None
    keystone_options: Mapping[str, int | float] = field(default_factory=dict)
    # Hail of Blades owns a short, non-uniform swing schedule. The raw times
    # stay here so every auto-coupled item and rune reads the same sequence.
    hail_attack_times: tuple[float, ...] = ()
    hail_active_attack_indices: tuple[int, ...] = ()
    hail_activation_times: tuple[float, ...] = ()
    # Lethal Tempo owns a stack-sensitive swing schedule and max-stack bolt
    # indexes. The raw times are shared by every auto-coupled effect.
    lethal_attack_times: tuple[float, ...] = ()
    lethal_bolt_attack_indices: tuple[int, ...] = ()
    lethal_stack_counts: tuple[int, ...] = ()
    lethal_activation_times: tuple[float, ...] = ()
    # ── Fight timeline (built by the rotation, read by later steps) ───────
    # When stacking-DoT stacks land and which mid-fight buff windows they
    # open — the ONE home every stack-aware step reads (Case 4 and 5).
    stack_timeline: "StackTimeline | None" = None
    # Where a self-rated empowered burst (Jayce's Hyper Charge) puts its
    # swings, resolved with the cast plan and read by the swing schedule.
    burst_swings: "BurstSwingSchedule | None" = None
    # Which scheduled swings an empower that rides the ordinary stream
    # claimed, ``{slot: times}`` (see ``_resolve_scheduled_auto_rides``).
    empowered_ride_times: dict[str, tuple[float, ...]] = field(default_factory=dict)
    # Rengar's Ferocity stack walk, built with the cast plan. ``None`` for
    # every champion whose module emits no ``ferocity_parts``.
    ferocity_timeline: "FerocityTimeline | None" = None
    # ── Accumulators ──────────────────────────────────────────────────────
    breakdown: dict[str, Any] = field(default_factory=dict)
    total_damage: float = 0.0
    notes: list[str] = field(default_factory=list)
    # Mitigated bonus from basic_damage ability parts (forced swings,
    # Caitlyn's Headshot rider) amplified by Hexoptics — already inside
    # their rows; surfaced on the basic-amp info row.
    basic_amp_ability_bonus: float = 0.0

    # Set by calculate_fight_damage: receipts-only outputs (per-cast
    # resource rows) may be skipped when True.
    score_only: bool = False


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


def _held_owners(state: FightState) -> list[str]:
    """This build's item names in build order — the order a family's fold sums."""
    return [item_effects.resolved_item_name(item) for item in state.items]


def _crit_profile(state: FightState) -> "crit_profile.CritProfile":
    """What this build's crit declarations say — bonus, forced strike, refund."""
    return crit_profile.declared_crit_profile(_held_owners(state))
