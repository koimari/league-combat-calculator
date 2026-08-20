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
    hits automatically double them. An optional ``max_procs`` key caps the
    number of applications (Bard meeps: stock + recharge availability) —
    autos beyond the cap land without the on-hit damage. A ``ramping``
    flag (with ``stacks_required``) makes proc k deal k x the per-hit
    damage (Bel'Veth R: stacks accumulate and never reset). A
    ``stack_ramp`` dict (``{"damage_per_stack", "max_stacks"}``) models
    per-target attack stacks amplifying the on-hit damage itself
    (Orianna P): each hit lands at the CURRENT stack count then adds a
    stack, so hit k (0-indexed) deals ``damage_per_hit +
    min(k, max_stacks) x damage_per_stack`` — the natural single-target
    ramp, with stacks assumed never to drop mid-fight.

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

**Case 4 — Hit-timeline stacking DoT** (e.g. Briar passive):
    One entry (usually the passive) declares the DoT::

        "stacking_dot": {
            "name": "Crimson Curse (bleed)",
            "damage_type": "physical",
            "single_stack_raw": 100.0,   # one stack's total over duration
            "duration": 5.0,
            "max_stacks": 5,
            "extra_stack_effectiveness": 0.25,
            "applied_by_autos": True,
        }

    and each castable whose applications add a stack carries
    ``"applies_dot_stack": True``. ``_build_stack_timeline`` builds the
    fight's hit timeline — autos at attack-speed intervals plus ability
    applications at their cast times (t=0 in one-rotation mode) — and
    ``_add_stacking_dot_damage`` integrates the tick rate at the running
    stack count: ``single_dps x (1 + extra_eff x (stacks - 1))``, stacks
    capped at ``max_stacks``. Every application refreshes the shared
    duration; a gap longer than ``duration`` expires the chain.
    Accounting is COMMITTED: the last hit's full ``duration`` of ticks
    counts even past the fight cutoff. An ``empowers_next_auto``
    applier's swing is one of the fight's autos, so its stack rides the
    auto timeline (it is only counted separately when there is no auto
    stream).

**Case 5 — Stack-triggered mid-fight steroid** (e.g. Darius' Noxian
Might): the same entry may declare::

        "stack_triggered_buff": {
            "name": "Noxian Might",
            "trigger_stacks": 5,
            "duration": 5.0,
            "bonus_attack_damage": 280.0,
        }

    Every application that lands ON ``trigger_stacks`` opens (or
    refreshes) a ``duration``-second window of bonus AD, derived from
    the SAME ``StackTimeline`` the DoT integrates — one home for "when
    does a stack land". Casts, autos and DoT ticks inside a window are
    priced against the buffed AD: a part declares how it reacts with
    ``DamagePart.bonus_ad_ratio`` (its derivative in bonus AD), the DoT
    with ``single_stack_bonus_ad_ratio``. The application that opens a
    window is NOT itself buffed — the buff is triggered BY its damage.
    A part may also declare ``dot_stack_scaled`` to hit once per stack
    on the target when the cast lands (Darius R's per-stack bonus).
"""

import heapq
import math
import random
from collections.abc import Mapping, Sequence
from collections import Counter
from dataclasses import dataclass, field, replace
from operator import itemgetter
from typing import Any, Callable

from . import item_effects
from . import resource_ledger
from . import rune_effects
from . import shield_ledger
from .ability_spec import ACTION_BLOCKING_CC_KINDS, ControlEvent, DamagePart
from .state_lifecycle import InstanceCadence, TimedStackState
from .champions.ashe import ASHE_FOCUS_STACK_RULE
from .item_support_effects import has_takedown_scan_support_items
from .resistance import (
    apply_resistance,
    apply_magic_penetration,
    apply_armor_penetration,
    reduce_resistance,
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

    Dual identity (renewal counting): for a solo ability the cast epochs are
    0, cd', 2*cd', ... and the cast rate 1/cd' = (100 + AH)/(100 * base_cd) is
    affine in ability haste — each point of AH adds a constant
    1/(100 * base_cd) casts/second. The total casts in [0, T] is the renewal
    counting function floor(T/cd') + 1 (counting the t=0 cast).

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
    # Percent BONUS armor penetration (Last Whisper family, K'Sante All
    # Out) and the target's base/bonus armor split (None = split unknown;
    # the legacy quick-scenario total-pen reading applies).
    armor_pen_bonus_percent: float = 0.0
    target_bonus_armor: float | None = None
    # Target passives such as Amumu's Tantrum reduce each physical raw
    # damage instance before resistance mitigation. The cap is a fraction
    # of that instance, not a cap on the total fight damage.
    physical_damage_flat_reduction: float = 0.0
    physical_damage_flat_reduction_cap: float = 0.0
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
        self._resolve_armor_from_target()

    def _resolve_armor_from_target(self) -> None:
        """Re-derive reduced/effective armor from the target's armor."""
        self.reduced_armor = reduce_resistance(
            self.target_armor, self.bc_reduction * 100.0
        )
        self.effective_armor = apply_armor_penetration(
            self.reduced_armor,
            self.flat_armor_pen,
            self.ability_armor_pen_percent,
            self.armor_pen_bonus_percent,
            self.target_bonus_armor,
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
            self.base_mr, self.magic_pen_flat, self.ability_magic_pen_percent
        )
        self.effective_mr_post_ult = apply_magic_penetration(
            self.reduced_mr, self.magic_pen_flat, self.ability_magic_pen_percent
        )
        self.effective_mr = self.effective_mr_post_ult

    def shred_armor(
        self, reduction_percent: float = 0.0, reduction_flat: float = 0.0
    ) -> None:
        """Reduce the target's armor and re-resolve armor.

        Percent shreds (Kog'Maw Q) scale the armor that is left; flat
        shreds (Corki E) subtract from it. Reduction — unlike penetration
        — has no floor: negative armor amplifies damage.
        """
        self.target_armor = reduce_resistance(
            self.target_armor, reduction_percent, reduction_flat
        )
        self._resolve_armor_from_target()

    def shred_mr(
        self, reduction_percent: float = 0.0, reduction_flat: float = 0.0
    ) -> None:
        """Reduce the target's magic resist and re-resolve MR.

        Same rules as :meth:`shred_armor` — flat reduction may take MR
        below zero, where it amplifies damage.
        """
        self.base_mr = reduce_resistance(
            self.base_mr, reduction_percent, reduction_flat
        )
        self._resolve_mr_from_target()

    def use_auto_pen(self) -> None:
        """Switch effective resistances to auto-attack pen (Terminus avg).

        Called once the ability rotation is done: remaining damage (autos,
        on-hits, item procs) uses the auto-attack pen variants.
        """
        self.effective_armor = apply_armor_penetration(
            self.reduced_armor,
            self.flat_armor_pen,
            self.auto_armor_pen_percent,
            self.armor_pen_bonus_percent,
            self.target_bonus_armor,
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
        reduced_raw = _apply_physical_damage_reduction(raw_damage, resists)
        return apply_resistance(reduced_raw, resists.effective_armor)
    return raw_damage


def _apply_physical_damage_reduction(raw_damage: float, resists: Resists) -> float:
    """Apply a target's capped flat reduction to one physical raw instance."""
    if raw_damage <= 0.0:
        return raw_damage
    flat = float(getattr(resists, "physical_damage_flat_reduction", 0.0) or 0.0)
    cap = float(getattr(resists, "physical_damage_flat_reduction_cap", 0.0) or 0.0)
    if flat <= 0.0 or cap <= 0.0:
        return raw_damage
    return max(0.0, raw_damage - min(flat, raw_damage * cap))


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
    # None = split unknown; the legacy quick-scenario total-pen reading
    # applies to percent BONUS penetration (LDR family).
    target_bonus_armor: float | None = None
    auto_attack_uptime: float = 0.0
    auto_attack_uptime_mode: str = "legacy"
    rotation_count: int = 1
    one_rotation: bool = False
    include_actives: bool = True
    cast_order: list[str] | None = None
    auto_attacks_only: bool = False
    deterministic: bool = False
    target_magic_shield: float = 0.0
    target_physical_shield: float = 0.0
    target_general_shield: float = 0.0
    target_basic_damage_multiplier: float = 1.0
    target_basic_damage_flat_reduction: float = 0.0
    target_basic_damage_flat_reduction_cap: float = 0.0
    target_physical_damage_flat_reduction: float = 0.0
    target_physical_damage_flat_reduction_cap: float = 0.0
    target_champion_damage_flat_reduction: float = 0.0
    target_champion_dot_damage_flat_reduction: float = 0.0
    target_critical_strike_damage_multiplier: float = 1.0
    # Target-side auras such as Frozen Heart reduce the attacker's total
    # attack speed before the authored swing schedule is compiled.
    attacker_attack_speed_multiplier: float = 1.0
    target_threshold_shield_amount: float = 0.0
    target_threshold_shield_health_ratio: float = 0.0
    target_threshold_shield_duration: float = 0.0
    target_threshold_shield_damage_type: str = "all"
    target_threshold_health_bonus: float = 0.0
    target_threshold_health_heal: float = 0.0
    target_threshold_health_ratio: float = 0.0
    target_threshold_health_duration: float = 0.0
    target_revive_health_amount: float = 0.0
    target_revive_delay: float = 0.0
    target_revive_cooldown: float = 0.0
    enforce_resource_limits: bool = False
    # Ordered external resource restores (time, amount) are supplied by the
    # coupled participant ledger for items such as Catalyst of Aeons.  The
    # engine consumes them before a simultaneous cast is admitted; ordinary
    # one-pair callers leave this empty.
    resource_restore_events: tuple[tuple[float, float], ...] = ()
    # Account owner for the typed mana resource ledger (P3 slice 1).  The
    # one-pair engine defaults to "main"; the coupled participant timeline
    # keys each attacker's fight by its participant id.
    resource_ledger_owner: str = "main"
    roster_target_index: int = 0
    roster_target_count: int = 1
    # Selected keystone rune by name ("" = none). Resolution fails closed
    # in rune_effects for unknown or unmodeled keystones.
    keystone: str = ""
    # Explicit state inputs for the selected keystone. The parser validates
    # this mapping before it reaches the fight engine.
    keystone_options: Mapping[str, int | float] = field(default_factory=dict)
    # P3-3M: the target's actor CLASS.  "champion" is the historical 1v1
    # model and the default for every existing caller; "minion" arms the
    # sourced minion-only item branches (Doran's Helm's Helping Hand).
    # The label gates class-restricted EFFECTS only — the target's stats
    # (health, armor, MR, shields) stay caller-supplied, because no minion
    # base-stat block is cached.  Unknown spellings fail closed.
    target_class: str = item_effects.DEFAULT_TARGET_CLASS

    def __post_init__(self) -> None:
        """Reject a target class the fight model cannot represent."""
        if self.target_class not in item_effects.TARGET_CLASSES:
            raise ValueError(
                "target_class must be one of "
                f"{', '.join(item_effects.TARGET_CLASSES)}; "
                f"got {self.target_class!r}"
            )


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
    item_options: Mapping[str, Mapping[str, int | float]] | None
    # P3 package 3V: the champion scenario options (p_ferocity) — the
    # live Ferocity walk seeds its stack state from the same option the
    # module parse consumed.
    champion_options: Mapping[str, Any]
    actualizer_active_until: float
    actualizer_basic_cooldown_multiplier: float
    ability_haste: float
    one_rotation: bool
    include_actives: bool
    auto_attacks_only: bool
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
    ability_amp: float  # Actualizer
    basic_amp: float  # Hexoptics C44
    hypershot_amp: float  # Horizon Focus
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
    # ── Keystone rune (compiled proc; None when no keystone equipped) ─────
    keystone_effect: "rune_effects.KeystoneEffect | None" = None
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


def _apply_basic_amp(
    state: "FightState", part: DamagePart, mitigated: float, procs: int = 1
) -> float:
    """Amplify a basic-damage part (Hexoptics C44), tracking the info-row bonus.

    Resistance is linear in raw damage, so amplifying post-mitigation is
    exact. Non-basic parts pass through untouched. ``procs`` scales only
    the tracked bonus, for callers that multiply the returned per-proc
    value afterwards.
    """
    if not part.basic_damage or state.basic_amp <= 1.0:
        return mitigated
    amped = mitigated * state.basic_amp
    state.basic_amp_ability_bonus += (amped - mitigated) * procs
    return amped


def _apply_target_basic_damage_reduction(
    state: "FightState",
    post_mitigation_damage: float,
    *,
    hits: int = 1,
    rock_solid_instances: int = 1,
) -> float:
    """Apply target-side percentage and capped-flat basic-damage defenses.

    Plating is a percentage modifier and therefore composes
    multiplicatively with armor and attacker amplifiers. Rock Solid is
    explicitly post-mitigation: it removes 15 from the first basic-damage
    instance of each cast, but never more than 20% of that instance.
    ``hits`` lets a multi-hit basic-damage part receive Plating on every hit
    while consuming Rock Solid only once for its cast instance.
    """
    if hits <= 0:
        return post_mitigation_damage
    reduced = post_mitigation_damage * state.target_basic_damage_multiplier
    # Negative parts are algebraic modifiers to a swing (Jayce W below
    # rank 5), not a separate incoming event. Plating scales the modifier,
    # but a flat defensive proc cannot be consumed by negative damage.
    if reduced <= 0:
        return reduced
    flat = state.target_basic_damage_flat_reduction
    cap = state.target_basic_damage_flat_reduction_cap
    instances = min(max(0, rock_solid_instances), hits)
    if flat <= 0 or cap <= 0 or instances <= 0:
        return reduced
    per_hit = reduced / hits
    reduction_per_instance = min(flat, per_hit * cap)
    return max(0.0, reduced - reduction_per_instance * instances)


def _apply_target_champion_damage_reduction(
    state: "FightState",
    post_mitigation_damage: float,
    *,
    hits: int = 1,
    damage_over_time: bool = False,
) -> float:
    """Apply a sourced flat reduction to champion attack or spell packets."""
    if hits <= 0 or post_mitigation_damage <= 0.0:
        return post_mitigation_damage
    reduction = (
        getattr(state, "target_champion_dot_damage_flat_reduction", 0.0)
        if damage_over_time
        else getattr(state, "target_champion_damage_flat_reduction", 0.0)
    )
    if reduction <= 0.0:
        return post_mitigation_damage
    return max(0.0, post_mitigation_damage - reduction * hits)


def _mitigate_basic_attack_swing(
    state: "FightState",
    raw_damage: float,
    damage_type: str = "physical",
    *,
    critical_strike: bool = False,
) -> float:
    """Resolve one primary basic-attack damage instance against the target."""
    mitigated = _mitigate(
        raw_damage,
        damage_type,
        state.resists,
        state.magic_amp,
    )
    mitigated *= state.basic_amp
    if critical_strike:
        mitigated *= state.target_critical_strike_damage_multiplier
    if damage_type != "true":
        mitigated = _apply_target_basic_damage_reduction(state, mitigated)
        mitigated = _apply_target_champion_damage_reduction(state, mitigated)
    return mitigated


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


def _finite_numeric_receipt(value: Any) -> float | None:
    """Coerce a JSON numeric receipt, rejecting bools, strings, and NaN."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


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
            (str(event.get("source_key", "")), event)
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
                    "trigger_source": str(event.get("source_key", "")),
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
    the auto stream applies (``state.damage_effects.per_hits``) —
    including BoRK's current-health formula, evaluated at the rotation's
    modeled target HP. Counter-gated procs (Kraken/Hullbreaker) are NOT
    summed here — the application is recorded on the fight's shared hit
    counter and its procs fire in ``_add_single_proc_on_hits``.
    On-ATTACK-only mechanics (energized procs, spellblade, phantom
    hits) are attack-triggered and never apply here. Per-hit components
    marked ``superseded_by_ability_proc`` (Muramana) are skipped too —
    their per-ability-cast damage already fired for this cast.

    Returns the application's damage per damage type; sum the values
    for the total.
    """
    inputs = _damage_inputs(state, target_current_health)
    by_type: dict[str, float] = {}
    for effect in state.damage_effects.per_hits:
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


def _damage_type_fields(by_type: dict[str, float]) -> dict[str, Any]:
    """Breakdown-row typing fields for a per-type damage composition.

    A single contributing type yields a plain ``damage_type``; multiple
    types yield ``"mixed"`` plus the exact ``damage_by_type`` composition
    that ``split_by_damage_type`` consumes.
    """
    if len(by_type) == 1:
        return {"damage_type": next(iter(by_type))}
    return {"damage_type": "mixed", "damage_by_type": dict(by_type)}


def _calculate_phantom_hits(
    num_auto_attacks: int,
    effect: item_effects.PhantomHitEffect | None,
    leading_attacks: int = 0,
) -> tuple[list[int], set[int]]:
    """Calculate which attacks trigger phantom hits.

    Rageblade grants stacking attack speed per attack (Seething Strike).
    The 4th attack maxes Seething AND starts Phantom stacking. At 2
    Phantom stacks, the next attack consumes them to trigger a Phantom
    Hit that applies all on-hit effects an additional time.

    Sequence: 5 attacks to build up, 6th triggers, then every 3rd after
    (6, 9, 12, 15, 18, ...). Phantom stacking is an ON-ATTACK mechanic,
    so the counter runs over one shared attack sequence: ability-carried
    attacks (Bel'Veth E slashes) lead, then the fight's autos continue
    it — a slash can be the 6th attack that fires the phantom.

    Args:
        num_auto_attacks: Total auto attacks in the fight.
        effect: Compiled phantom-hit cadence, or ``None``.
        leading_attacks: Ability-carried attacks that precede the autos
            on the shared attack counter.

    Returns:
        Tuple of (0-indexed leading-attack indices that trigger phantom
        hits, set of 0-indexed auto numbers that trigger phantom hits).
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
    phantom_hit_autos: set[int],
    double_on_hit_procs: int,
    hits_required: int,
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
    effectiveness: float = 1.0,
    target_basic_damage_multiplier: float = 1.0,
) -> list[float]:
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
        effectiveness: On-hit effectiveness multiplier on each proc's raw
            damage (Azir soldiers proc at 50%).
        target_basic_damage_multiplier: Target-side percentage modifier for
            the rare item proc that the Wiki tags as basic damage.

    Returns:
        Each proc's mitigated damage in ascending-auto order — the same
        order as sorted ``proc_autos`` — so callers can stamp per-swing
        damage events (sum for the total).
    """
    if not proc_autos:
        return []

    # Convert proc list to a counter: how many procs fire on each auto
    proc_counts: dict[int, int] = Counter(proc_autos)

    current_hp = target_health
    proc_damages: list[float] = []

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
            raw_damage = effect.source.raw_damage(inputs) * effectiveness
            mitigated = _mitigate(
                raw_damage,
                effect.source.damage_type,
                resists,
                magic_amp,
            )
            if effect.source.basic_damage and effect.source.damage_type != "true":
                mitigated *= target_basic_damage_multiplier
            proc_damages.append(mitigated)
            current_hp -= mitigated

        # Reduce HP from auto attack + other on-hit damage
        current_hp -= auto_damage_per_hit + other_on_hit_per_hit
        if current_hp < 0:
            current_hp = 0

    return proc_damages


def _schedule_cooldown_procs(
    swing_times: Sequence[float],
    proc_cooldown: float,
) -> list[int]:
    """Schedule per-target-cooldown on-hit procs onto the authored swings.

    The first swing always procs; each later swing procs iff its authored
    timestamp is at least ``proc_cooldown`` after the previous proc
    (Jarvan IV's Martial Cadence pattern). Consuming the same schedule
    that stamps damage events keeps the scheduling decision and the
    stamped time from diverging during empowered attack-speed windows.

    Args:
        swing_times: The fight's per-swing timestamps
            (``_auto_attack_timestamps`` order).
        proc_cooldown: Per-target cooldown between procs, in seconds.

    Returns:
        Sorted 0-indexed swing indices on which the effect procs.
    """
    proc_autos: list[int] = []
    next_ready = 0.0
    for i, timestamp in enumerate(swing_times):
        if timestamp >= next_ready:
            proc_autos.append(i)
            next_ready = timestamp + proc_cooldown
    return proc_autos


def _simulate_cooldown_current_health_procs(
    on_hit_data: dict[str, Any],
    target_health: float,
    num_auto_attacks: int,
    auto_damage_per_hit: float,
    other_on_hit_per_hit: float,
    resists: Resists,
    magic_amp: float,
    proc_autos: list[int],
    effectiveness: float = 1.0,
) -> list[float]:
    """Simulate cooldown-gated current-health procs (Jarvan IV passive).

    Each proc deals ``current_health_percent`` of the target's decayed
    current HP, floored at ``min_damage``, as ``damage_type`` damage.
    Same decaying-HP walk as the stacking on-hit simulation: the proc
    lands before that auto's own damage is subtracted.

    Args:
        on_hit_data: The ability entry's ``on_hit`` payload, carrying
            ``current_health_percent`` / ``min_damage`` / ``damage_type``.
        target_health: Target's starting (max) health.
        num_auto_attacks: Number of auto attacks in the fight.
        auto_damage_per_hit: Mitigated base auto attack damage per hit.
        other_on_hit_per_hit: Mitigated per-hit damage from other on-hit
            effects (static items/abilities plus the BoRK average).
        proc_autos: Sorted 0-indexed auto indices where the effect procs.
        effectiveness: On-hit effectiveness multiplier (Azir soldiers).

    Returns:
        Each proc's mitigated damage, in proc order (sum for the total).
    """
    if not proc_autos:
        return []

    pct = on_hit_data["current_health_percent"] / 100.0
    min_damage = on_hit_data.get("min_damage", 0.0)
    dmg_type = on_hit_data.get("damage_type", "physical")
    proc_set = set(proc_autos)

    current_hp = target_health
    proc_damages: list[float] = []
    for i in range(num_auto_attacks):
        if i in proc_set:
            raw_damage = max(pct * current_hp, min_damage) * effectiveness
            mitigated = _mitigate(raw_damage, dmg_type, resists, magic_amp)
            proc_damages.append(mitigated)
            current_hp -= mitigated

        # Reduce HP from auto attack + other on-hit damage
        current_hp -= auto_damage_per_hit + other_on_hit_per_hit
        current_hp = max(current_hp, 0.0)

    return proc_damages


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
    effectiveness: float = 1.0,
    first_auto_damage_by_auto: Sequence[float] = (),
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
        effectiveness: On-hit effectiveness multiplier on each proc's raw
            damage (Azir soldiers apply on-hit at 50%).

    Returns:
        Tuple of (total mitigated BoRK damage, total BoRK hit count,
        each hit's mitigated damage in application order — one entry per
        counted hit, so callers can stamp per-swing damage events).
    """
    if phantom_hit_autos is None:
        phantom_hit_autos = set()

    current_hp = target_health
    total_damage = 0.0
    total_hits = 0
    hit_damages: list[float] = []

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
            raw_damage = effect.source.raw_damage(inputs) * effectiveness
            mitigated = _mitigate(
                raw_damage,
                effect.source.damage_type,
                resists,
                magic_amp,
            )
            total_damage += mitigated
            total_hits += 1
            hit_damages.append(mitigated)

            current_hp -= mitigated

        # Also reduce HP by auto attack damage and other on-hit damage
        # (other on-hit phantom procs are accounted for in other_on_hit_per_hit
        #  which is already multiplied by the average hits-per-auto)
        on_hit_this_auto = other_on_hit_per_hit
        if i in phantom_hit_autos:
            on_hit_this_auto += other_on_hit_per_hit  # phantom extra proc
        # First-auto packets are authored by the single-proc pass, but they
        # still land on this auto and must lower the HP used by later
        # current-health procs. Keep this as an HP-only input: the packet is
        # added to the breakdown exactly once by _add_single_proc_on_hits.
        if i < len(first_auto_damage_by_auto):
            on_hit_this_auto += max(0.0, float(first_auto_damage_by_auto[i]))
        current_hp -= auto_damage_per_hit + on_hit_this_auto
        if current_hp < 0:
            current_hp = 0

    return total_damage, total_hits, hit_damages


def _row_damage_parts(entry: dict[str, Any]) -> list[tuple[str, float]]:
    """Return one breakdown row's exact typed post-mitigation parts."""
    by_type = entry.get("damage_by_type")
    if by_type is not None:
        return [
            (dtype, float(amount))
            for dtype, amount in by_type.items()
            if dtype in {"physical", "magic", "true"} and amount > 0
        ]
    dtype = entry.get("damage_type")
    damage = float(entry.get("total_damage", 0.0))
    return (
        [(dtype, damage)]
        if dtype in {"physical", "magic", "true"} and damage > 0
        else []
    )


# Phase precedence inside one timestamp of the reconstructed ledger.
_EVENT_PHASE_ORDER = {"ability": 0, "auto": 1, "effect": 2, "amplifier": 3}


def _ordered_damage_events(
    breakdown: dict[str, Any],
    ability_damages: dict[str, dict[str, Any]],
    cast_order: list[str],
    *,
    cast_events: list[dict[str, Any]] | None = None,
    light: bool = False,
    lean: bool = False,
) -> list[Any]:
    """Reconstruct the engine's certified damage order from its own rows.

    Ability rows are split into cast instances and follow the accepted cast
    timeline. Rows with engine-authored ``damage_events`` (autos, per-swing
    on-hit effects, timestamped procs) keep their own event order; item
    effects without authored events retain the coarse phase order after the
    selected rotation. Untyped amplifier rows are distributed across the
    already-known damage composition so shield accounting never invents a
    fourth damage type.

    ``light=True`` returns ``(sort_key, damage, damage_type, source_key,
    raw_formula, raw_damage)`` tuples instead of full rows — the same
    events, the same ``(time, order, phase, sequence)`` order, one shared
    iteration — for the mid-fight consumers (threshold-trigger scans,
    amplifier delta authoring) that never serve the returned ledger
    contract.

    ``lean=True`` keeps dict rows but drops the display-only fields
    (``ordinal``, ``phase``, ``order``, ``event_precision``,
    ``source_missing_ratio``) nothing on the scoring path reads; the
    fields that price, order, or link events are all present.  Only the
    score-only pipeline may request it — public receipts serialize the
    full rows.

    This ledger is deliberately internal. It is exact at the cast boundary,
    but it does not claim champion-specific spell-shield behavior within a
    multi-hit cast; those target items remain fail-closed until each ability
    supplies the necessary interaction metadata.
    """
    events: list[Any] = []
    sequence = 0
    typed_totals = {"physical": 0.0, "magic": 0.0, "true": 0.0}

    def add(
        source_key: str,
        damage_type: str,
        damage: float,
        *,
        time: float,
        ordinal: int,
        phase: str,
        order: float | None = None,
        raw_damage: float | None = None,
        raw_formula: Any = None,
        source_missing_ratio: float | None = None,
        event_precision: str | None = None,
        basic_attack: bool = False,
        cc_kind: str | None = None,
        cc_reviewed: bool = False,
        cc_duration: float = 0.0,
        skillshot: bool = False,
        area_damage: bool = False,
        damage_over_time: bool = False,
        control_source_atoms: tuple[Mapping[str, Any], ...] = (),
    ) -> None:
        # Row schema (including ``_lk``) must mirror add_declared_events'
        # inlined fast path below exactly; change them together.
        nonlocal sequence
        if damage <= 0 or damage_type not in {"physical", "magic", "true"}:
            return
        order_value = float(sequence) if order is None else order
        typed_totals[damage_type] += damage
        if light:
            events.append(
                (
                    (time, order_value, _EVENT_PHASE_ORDER[phase], sequence),
                    damage,
                    damage_type,
                    source_key,
                    raw_formula,
                    0.0 if raw_damage is None else raw_damage,
                )
            )
            sequence += 1
            return
        if lean:
            event = {
                "source_key": source_key,
                "damage_type": damage_type,
                "damage": damage,
                "time": time,
                "sequence": sequence,
                "_lk": (time, order_value, _EVENT_PHASE_ORDER[phase], sequence),
            }
            if raw_damage is not None:
                event["raw_damage"] = raw_damage
            # Vamp eligibility is a pricing input, not display: the
            # lifesteal/omnivamp derivations and the item support scan read
            # these markers off score-only rows too (issue #169).
            if basic_attack:
                event["basic_attack"] = True
            normalized_cc_kind = str(cc_kind).lower().strip() if cc_kind else ""
            if cc_kind is not None:
                event["cc_kind"] = str(cc_kind)
            if cc_reviewed or normalized_cc_kind in (
                ACTION_BLOCKING_CC_KINDS | {"slow"}
            ):
                event["cc_reviewed"] = True
            if cc_duration > 0.0:
                event["cc_duration"] = float(cc_duration)
            if skillshot:
                event["skillshot"] = True
            if area_damage:
                event["area_damage"] = True
            if control_source_atoms:
                event["control_source_atoms"] = [
                    dict(atom) for atom in control_source_atoms
                ]
            if damage_over_time:
                event["damage_over_time"] = True
            if basic_attack or source_key.startswith(("auto_attacks", "on_hit_")):
                event["omnivamp_effectiveness"] = 1.0
        else:
            event = {
                "source_key": source_key,
                "damage_type": damage_type,
                "damage": damage,
                "time": time,
                "ordinal": ordinal,
                "phase": phase,
                "sequence": sequence,
                "order": order_value,
                "_lk": (time, order_value, _EVENT_PHASE_ORDER[phase], sequence),
            }
            if raw_damage is not None:
                event["raw_damage"] = raw_damage
            if source_missing_ratio is not None:
                event["source_missing_ratio"] = source_missing_ratio
            if event_precision is not None:
                event["event_precision"] = event_precision
            if basic_attack:
                event["basic_attack"] = True
            normalized_cc_kind = str(cc_kind).lower().strip() if cc_kind else ""
            if cc_kind is not None:
                event["cc_kind"] = str(cc_kind)
            if cc_reviewed or normalized_cc_kind in (
                ACTION_BLOCKING_CC_KINDS | {"slow"}
            ):
                event["cc_reviewed"] = True
            if cc_duration > 0.0:
                event["cc_duration"] = float(cc_duration)
            if skillshot:
                event["skillshot"] = True
            if area_damage:
                event["area_damage"] = True
            if control_source_atoms:
                event["control_source_atoms"] = [
                    dict(atom) for atom in control_source_atoms
                ]
            if damage_over_time:
                event["damage_over_time"] = True
            if basic_attack or source_key.startswith(("auto_attacks", "on_hit_")):
                # Omnivamp's full-effectiveness branch is certified only for
                # the primary attack/on-hit packet. Area, pet, and copied
                # target rows deliberately carry no eligibility marker.
                event["omnivamp_effectiveness"] = 1.0
        if source_key in cast_order:
            event["is_ability"] = True
        if raw_damage is not None:
            event["raw_damage"] = raw_damage
        if raw_formula is not None:
            event["raw_formula"] = raw_formula
        events.append(event)
        sequence += 1

    def add_declared_events(
        source_key: str,
        entry: dict[str, Any],
        *,
        default_phase: str,
    ) -> bool:
        """Append an engine-authored event list, returning whether it existed.

        This is the hot path of ledger reconstruction — module champions
        declare nearly every event — so the row is built directly instead of
        going through ``add``'s keyword plumbing for each declared hit.  The
        row schema (including ``_lk``) must mirror ``add()`` above exactly;
        change them together.
        """
        nonlocal sequence
        declared = entry.get("damage_events")
        if not isinstance(declared, list):
            return False
        phase = str(entry.get("event_phase", default_phase))
        if phase not in _EVENT_PHASE_ORDER:
            phase = default_phase
        phase_rank = _EVENT_PHASE_ORDER[phase]
        # Per-entry constants, hoisted out of the per-event loop.
        is_ability_source = source_key in cast_order
        vamp_source = source_key.startswith(("auto_attacks", "on_hit_"))
        shield_events = entry.get("self_shield_events")
        if not isinstance(shield_events, list):
            shield_events = None
        for ordinal, event in enumerate(declared, start=1):
            if not isinstance(event, dict):
                continue
            damage = float(event.get("damage", 0.0))
            damage_type = str(event.get("damage_type", ""))
            if damage <= 0 or damage_type not in {"physical", "magic", "true"}:
                continue
            order = event.get("timeline_order")
            time = float(event.get("time", 0.0))
            order_value = float(sequence) if order is None else float(order)
            typed_totals[damage_type] += damage
            if light:
                events_append(
                    (
                        (time, order_value, phase_rank, sequence),
                        damage,
                        damage_type,
                        source_key,
                        event.get("raw_formula"),
                        float(event.get("raw_damage", 0.0) or 0.0),
                    )
                )
                sequence += 1
                continue
            if lean:
                row = {
                    "source_key": source_key,
                    "damage_type": damage_type,
                    "damage": damage,
                    "time": time,
                    "sequence": sequence,
                    "_lk": (time, order_value, phase_rank, sequence),
                }
            else:
                row = {
                    "source_key": source_key,
                    "damage_type": damage_type,
                    "damage": damage,
                    "time": time,
                    "ordinal": ordinal,
                    "phase": phase,
                    "sequence": sequence,
                    "order": order_value,
                    "_lk": (time, order_value, phase_rank, sequence),
                }
                source_missing_ratio = event.get("source_missing_ratio")
                if source_missing_ratio is not None:
                    row["source_missing_ratio"] = float(source_missing_ratio)
                event_precision = event.get("event_precision")
                if event_precision is not None:
                    row["event_precision"] = str(event_precision)
            if event.get("cc_kind") is not None:
                row["cc_kind"] = str(event["cc_kind"])
            if event.get("cc_reviewed") is True:
                row["cc_reviewed"] = True
            if float(event.get("cc_duration", 0.0) or 0.0) > 0.0:
                row["cc_duration"] = float(event["cc_duration"])
            if bool(event.get("skillshot")):
                row["skillshot"] = True
            elif bool(entry.get("skillshot")):
                row["skillshot"] = True
            if bool(event.get("area_damage")) or bool(entry.get("area_damage")):
                row["area_damage"] = True
            source_atoms = event.get("control_source_atoms")
            if isinstance(source_atoms, list):
                row["control_source_atoms"] = [
                    dict(atom) for atom in source_atoms if isinstance(atom, Mapping)
                ]
            for event_key in (
                "amplified",
                "deathfire_category",
                "trigger_source",
            ):
                if event_key in event:
                    row[event_key] = event[event_key]
            if "trigger_time" in event:
                row["trigger_time"] = float(event["trigger_time"])
            if is_ability_source:
                row["is_ability"] = True
            if shield_events is not None and ordinal - 1 < len(shield_events):
                shield = shield_events[ordinal - 1]
                if isinstance(shield, Mapping):
                    row["self_shield"] = dict(shield)
            raw_damage = event.get("raw_damage")
            if raw_damage is not None:
                row["raw_damage"] = float(raw_damage)
            raw_formula = event.get("raw_formula")
            if raw_formula is not None:
                row["raw_formula"] = raw_formula
            basic_attack = event.get("basic_attack")
            if basic_attack:
                row["basic_attack"] = True
            if isinstance(event.get("self_shield"), Mapping):
                row["self_shield"] = dict(event["self_shield"])
            if basic_attack or vamp_source:
                row["omnivamp_effectiveness"] = 1.0
            events_append(row)
            sequence += 1
        return True

    events_append = events.append
    # Built on first use: only the no-declared-events fallback below reads
    # it, and module champions declare every event.
    timeline_by_slot: dict[str, list[dict[str, Any]]] | None = None

    last_ability_time = 0.0
    for key in cast_order:
        entry = breakdown.get(key)
        if not entry or entry.get("informational"):
            continue
        casts = max(0, int(entry.get("casts", 0)))
        if casts <= 0:
            continue
        # Champion modules may have emitted a typed event ledger for this
        # ability.  Preserve it (including live target-health metadata)
        # instead of flattening the row back into one aggregate cast value.
        if add_declared_events(key, entry, default_phase="ability"):
            continue
        if timeline_by_slot is None:
            timeline_by_slot = {}
            for cast_event in cast_events or []:
                timeline_by_slot.setdefault(str(cast_event.get("slot", "")), []).append(
                    cast_event
                )
        slot_timeline = timeline_by_slot.get(key, [])
        instances = max(1, int(ability_damages.get(key, {}).get("cast_instances", 1)))
        ability_info = ability_damages.get(key, {})
        authored_parts = tuple(ability_info.get("parts", ()))
        cc_part = next(
            (part for part in authored_parts if part.cc_kind is not None), None
        )
        cc_damage_type = cc_part.damage_type if cc_part is not None else None
        cc_kind = str(cc_part.cc_kind) if cc_part is not None else None
        cc_duration = (
            max(
                float(part.cc_duration)
                for part in authored_parts
                if part.cc_duration > 0.0
            )
            if any(part.cc_duration > 0.0 for part in authored_parts)
            else 0.0
        )
        control_source_atoms = tuple(
            atom
            for part in authored_parts
            for atom in getattr(part, "control_source_atoms", ())
            if isinstance(atom, Mapping)
        )
        for cast_index in range(casts):
            cast_time = (
                float(slot_timeline[cast_index].get("time", 0.0))
                if cast_index < len(slot_timeline)
                else 0.0
            )
            last_ability_time = max(last_ability_time, cast_time)
            raw_total = float(entry.get("total_raw", 0.0) or 0.0)
            raw_per_instance = (
                raw_total / (casts * instances) if raw_total > 0.0 else None
            )
            for dtype, amount in _row_damage_parts(entry):
                per_instance = amount / (casts * instances)
                for instance_index in range(instances):
                    add(
                        key,
                        dtype,
                        per_instance,
                        time=cast_time,
                        ordinal=cast_index * instances + instance_index + 1,
                        phase="ability",
                        basic_attack=bool(entry.get("basic_attack")),
                        raw_damage=raw_per_instance,
                        cc_kind=cc_kind if dtype == cc_damage_type else None,
                        cc_reviewed=bool(ability_info.get("cc_reviewed")),
                        cc_duration=(cc_duration if dtype == cc_damage_type else 0.0),
                        skillshot=bool(entry.get("skillshot")),
                        area_damage=bool(entry.get("area_damage")),
                        control_source_atoms=(
                            control_source_atoms if dtype == cc_damage_type else ()
                        ),
                    )

    auto = breakdown.get("auto_attacks")
    if auto and not auto.get("informational"):
        if not add_declared_events("auto_attacks", auto, default_phase="auto"):
            hits = max(1, int(auto.get("count", 1)))
            for dtype, amount in _row_damage_parts(auto):
                for hit_index in range(hits):
                    add(
                        "auto_attacks",
                        dtype,
                        amount / hits,
                        time=last_ability_time,
                        ordinal=hit_index + 1,
                        phase="auto",
                        basic_attack=True,
                    )

    skipped = set(cast_order) | {"auto_attacks", "execute"}
    untyped: list[tuple[str, float]] = []
    for key, entry in breakdown.items():
        if key in skipped or entry.get("informational"):
            continue
        if add_declared_events(key, entry, default_phase="effect"):
            continue
        parts = _row_damage_parts(entry)
        if parts:
            for dtype, amount in parts:
                add(
                    key,
                    dtype,
                    amount,
                    time=last_ability_time,
                    ordinal=1,
                    phase="effect",
                    skillshot=bool(entry.get("skillshot")),
                    area_damage=bool(entry.get("area_damage")),
                )
        else:
            damage = float(entry.get("total_damage", 0.0))
            if damage > 0:
                untyped.append((key, damage))

    # ``typed_totals`` accumulated per add above, in the event order the
    # per-type sums used to walk.  Distribution reads a snapshot so the
    # rows it adds cannot skew a later type's share mid-loop.
    distribution_totals = tuple(typed_totals.items())
    typed_total = (
        typed_totals["physical"] + typed_totals["magic"] + typed_totals["true"]
    )
    if typed_total > 0:
        for key, damage in untyped:
            for dtype, typed_damage in distribution_totals:
                if typed_damage > 0:
                    add(
                        key,
                        dtype,
                        damage * typed_damage / typed_total,
                        time=last_ability_time,
                        ordinal=1,
                        phase="amplifier",
                    )

    # ``_lk`` is the (time, order, phase, sequence) key precomputed at
    # event creation; sorting on it avoids rebuilding the tuple per event
    # for every ledger reconstruction.  Light rows carry the same key as
    # their first element.
    events.sort(key=itemgetter(0) if light else itemgetter("_lk"))
    return events


def _event_timeline_coverage(
    breakdown: dict[str, Any],
    ability_damages: dict[str, dict[str, Any]],
    cast_order: list[str],
    *,
    num_auto_attacks: int = 0,
    lean: bool = False,
) -> dict[str, Any]:
    """Certify which active rows have authored or cast-boundary ordering.

    This is the one definition of "certified": rows whose damage rides
    the ambient auto stream (``requires_auto_timeline_coupling``) are
    downgraded here — not by consumers — so the fight report and
    window-sum effects can never disagree about the same source.
    """
    exact: list[str] = []
    coarse: list[str] = []
    cast_keys = set(cast_order)
    for key, entry in breakdown.items():
        if entry.get("withheld_reason"):
            coarse.append(key)
            continue
        if entry.get("informational") or float(entry.get("total_damage", 0.0)) <= 0:
            continue
        damage_events = entry.get("damage_events")
        if not isinstance(damage_events, list):
            damage_events = entry.get("timeline_events")
        # One pass computes both what two comprehensions used to: the
        # authored total (in list order) and the cast-boundary downgrade.
        event_total = None
        has_boundary = False
        if isinstance(damage_events, list) and damage_events:
            event_total = 0.0
            for event in damage_events:
                event_total += float(event.get("damage", 0.0))
                if (
                    not has_boundary
                    and isinstance(event, dict)
                    and str(event.get("event_precision", "")) == "cast_boundary"
                ):
                    has_boundary = True
        if has_boundary:
            coarse.append(key)
            continue
        if event_total is not None and math.isclose(
            event_total,
            float(entry["total_damage"]),
            rel_tol=1e-9,
            abs_tol=1e-6,
        ):
            exact.append(key)
            continue
        if key in cast_keys and int(entry.get("casts", 0)) > 0:
            info = ability_damages.get(key, {})
            if float(info.get("dot_duration", 0.0)) > 0:
                coarse.append(key)
            else:
                exact.append(key)
            continue
        coarse.append(key)
    complete = not coarse
    coupled_auto_sources = {
        key
        for key, info in ability_damages.items()
        if info.get("requires_auto_timeline_coupling")
        and num_auto_attacks > 0
        and int(breakdown.get(key, {}).get("casts", 0)) > 0
    }
    if lean:
        # Score-mode consumers only ever combine coverages by set union
        # (combine_timeline_coverages); the certification strings, notes,
        # and per-fight sorting never survive that, so skip building them.
        if coupled_auto_sources:
            return {
                "complete": False,
                "exact_sources": list(set(exact) - coupled_auto_sources),
                "coarse_sources": list(set(coarse) | coupled_auto_sources),
            }
        return {
            "complete": complete,
            "exact_sources": exact,
            "coarse_sources": coarse,
        }
    coverage = {
        "complete": complete,
        "certification": (
            "event_order_certified" if complete else "partial_event_order"
        ),
        "exact_sources": sorted(exact),
        "coarse_sources": sorted(coarse),
        "note": (
            "Every active damage source has authored event or cast-boundary order."
            if complete
            else (
                f"{len(coarse)} active damage source"
                f"{' uses' if len(coarse) == 1 else 's use'} coarse phase ordering."
            )
        ),
    }
    if coupled_auto_sources:
        coverage["complete"] = False
        coverage["certification"] = "partial_event_order"
        coverage["exact_sources"] = sorted(
            set(coverage["exact_sources"]) - coupled_auto_sources
        )
        coverage["coarse_sources"] = sorted(
            set(coverage["coarse_sources"]) | coupled_auto_sources
        )
        names = ", ".join(sorted(coupled_auto_sources))
        coverage["note"] = (
            f"{names} modifies attacks on the ambient auto stream; its bonus "
            "damage is included, but per-hit auto coupling is not yet "
            "event-order certified."
        )
    return coverage


def _fimbulwinter_event_coverage(
    items: list[dict[str, Any]],
    damage_events: list[dict[str, Any]],
    control_events: list[dict[str, Any]] | None = None,
) -> tuple[bool, str]:
    """Certify the control metadata needed by Fimbulwinter's Everlasting.

    Everlasting is not a generic "ability hit" proc.  The Wiki limits it to
    an immobilize, or a slow for a melee holder, and its shield must land after
    that authored cast.  A damage event with no reviewed ``cc_kind`` therefore
    cannot safely prove that the passive did or did not trigger.  Pure
    auto-attack windows are exact because they contain no candidate ability
    control event at all.
    """
    if not item_effects.requires_authored_control_event(items):
        return True, ""
    ability_events = [
        event
        for event in [*damage_events, *(control_events or [])]
        if isinstance(event, dict) and bool(event.get("is_ability"))
    ]
    if not ability_events:
        return True, ""
    known_cc_kinds = ACTION_BLOCKING_CC_KINDS | {"slow"}
    if all(
        event.get("cc_reviewed") is True
        and (
            event.get("cc_kind") is None
            or str(event.get("cc_kind", "")).lower().strip() in known_cc_kinds
        )
        for event in ability_events
    ):
        return True, ""
    return False, "fimbulwinter_everlasting"


@dataclass
class _ThresholdHealDrip:
    """Protoplasm Harness's sourced heal, delivered over its duration.

    ``shield_ledger`` owns the Lifeline itself — the threshold crossing and
    the temporary bonus health. The Wiki sources the accompanying heal "over
    the same duration", so this author delivers it between damage events
    rather than in one lump. A fight reaching the temporary-health expiry is
    withheld: the Wiki does not document what happens to current health when
    that temporary maximum lapses.
    """

    duration: float = 0.0
    heal_total: float = 0.0
    triggered: bool = False
    trigger_time: float = -1.0
    last_time: float = 0.0
    healing_received: float = 0.0

    def start(
        self,
        pools: shield_ledger.ShieldPools,
        event_time: float,
        armed: shield_ledger.Absorption,
    ) -> None:
        """Begin the drip on the instance whose damage armed the Lifeline.

        The window and the sourced total are read back off the armed Lifeline
        rather than staged a second time here.  The arming instant already
        delivered whatever the defender's missing health could take; only the
        remainder drips, so the two authors never exceed the sourced amount.
        """
        self.triggered = True
        self.trigger_time = event_time
        self.last_time = event_time
        self.duration = pools.threshold_health.duration
        self.heal_total = max(
            0.0, armed.threshold_health_heal - armed.threshold_health_healed
        )
        self.healing_received += armed.threshold_health_healed

    def advance_to(self, pools: shield_ledger.ShieldPools, event_time: float) -> None:
        """Apply sourced over-time healing up to one incoming event."""
        if not self.triggered:
            self.last_time = max(self.last_time, event_time)
            return
        expiry = self.trigger_time + self.duration
        if event_time >= expiry - 1e-9:
            raise ValueError(
                "Protoplasm Harness cannot be certified for damage at or after "
                "its temporary-health expiry: the current-health removal rule "
                "is not documented by the sourced Wiki data."
            )
        elapsed = max(0.0, event_time - self.last_time)
        if (
            pools.health > 0
            and self.duration > 0
            and elapsed > 0
            and self.heal_total > 0
        ):
            offered = self.heal_total * elapsed / self.duration
            received = min(offered, max(0.0, pools.max_health - pools.health))
            pools.health += received
            self.healing_received += received
        self.last_time = max(self.last_time, event_time)


_LIANDRY_BURN_KEY = "burn_Liandry's Torment"


def _calculate_shadowflame_bonus(
    effect: item_effects.MagicTrueCritEffect | None,
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
    return_events: bool = False,
    return_adjustments: bool = False,
) -> (
    tuple[float, dict[str, float]]
    | tuple[float, dict[str, float], list[dict[str, Any]]]
    | tuple[
        float,
        dict[str, float],
        list[dict[str, Any]],
        dict[str, Any],
    ]
):
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
        (total bonus damage from Shadowflame crits, bonus per damage
        type — the crit bonus keeps the underlying damage's type).
    """
    if cast_order is None:
        cast_order = list(DEFAULT_CAST_ORDER)
    crit_bonus = effect.crit_multiplier - 1.0 if effect is not None else 0.0
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
    )

    # 4. Simulate damage order, tracking target HP
    for event in events:
        damage = event["damage"]
        dtype = event["damage_type"]
        event_time = float(event["time"])
        heal_drip.advance_to(pools, event_time)
        source_key = str(event.get("source_key", ""))
        if (
            source_key == _LIANDRY_BURN_KEY
            and heal_drip.triggered
            and event_time > heal_drip.trigger_time + 1e-9
        ):
            adjusted = damage * pools.max_health / target_health
            liandry_delta += adjusted - damage
            damage = adjusted
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
            effect is not None
            and dtype in ("magic", "true")
            and pools.health < pools.max_health * effect.health_threshold
        ):
            bonus = damage * crit_bonus
            total_bonus += bonus
            bonus_by_type[dtype] = bonus_by_type.get(dtype, 0.0) + bonus
            bonus_events.append(
                {
                    "time": event_time,
                    "damage": bonus,
                    "damage_type": dtype,
                    "source_key": f"shadowflame_{effect.item_name}",
                    "trigger_source": event.get("source_key", ""),
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
    if return_adjustments:
        return total_bonus, bonus_by_type, bonus_events, adjustments
    if return_events:
        return total_bonus, bonus_by_type, bonus_events
    return total_bonus, bonus_by_type


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
    item_options: Mapping[str, Mapping[str, int | float]] | None = None,
    champion_options: Mapping[str, Any] | None = None,
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
    if item_effects.has_item(items, "Riftmaker"):
        max_stack_omnivamp = item_effects.riftmaker_max_stack_omnivamp(
            fight_duration_seconds=fight_duration_seconds,
            is_melee=bool(is_melee),
        )
        if max_stack_omnivamp > 0.0:
            # The stat bundle carries Riftmaker's base omnivamp.  The
            # max-stack branch is a fight-state transition, so add the
            # parser-owned bonus to a private copy before any healing path
            # or score-only fast-path decision reads the resolved stats.
            champion_stats = dict(champion_stats)
            champion_stats["omnivamp_percent"] = (
                champion_stats.get("omnivamp_percent", 0.0) + max_stack_omnivamp
            )
    level = int(champion_stats.get("level", 1))
    damage_effects = item_effects.resolve_damage_effects(items)
    actualizer_active_until = (
        item_effects.actualizer_active_seconds(
            items,
            item_options,
            fight_duration_seconds=fight_duration_seconds,
        )
        if config.include_actives
        else 0.0
    )
    actualizer_basic_cooldown_multiplier = (
        1.0
        / item_effects.required_effect_value(
            "Actualizer", "basic_cooldown_progress_multiplier"
        )
        if actualizer_active_until > 0.0 and item_effects.has_item(items, "Actualizer")
        else 1.0
    )

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
    armor_pen_bonus_percent = (
        champion_stats.get("armor_penetration_bonus_percent", 0.0) / 100.0
    )
    flat_armor_pen = champion_stats.get("flat_armor_penetration", 0.0)

    as_ratio = champion_stats["attack_speed_ratio"]
    attack_speed = champion_stats["attack_speed"]
    attack_speed_multiplier = max(
        0.0, min(1.0, float(config.attacker_attack_speed_multiplier))
    )
    if attack_speed_multiplier != 1.0:
        # A total attack-speed cripple scales both the opening rate and the
        # ratio used by later temporary bonus-AS windows.  This keeps the
        # aura active for every authored swing, not only the first schedule.
        champion_stats = dict(champion_stats)
        attack_speed *= attack_speed_multiplier
        as_ratio *= attack_speed_multiplier
        champion_stats["attack_speed"] = attack_speed
        champion_stats["attack_speed_ratio"] = as_ratio
    # ``calculate_total_stats`` keeps Flurry visible in the public stat
    # panel, but the authored fight starts before Yun Tal has attacked. Strip
    # that conditional amount from the opening rate; the shared swing helper
    # re-adds it only after the first attack and expires it on the sourced
    # window/cooldown.
    if item_effects.has_item(items, "Yun Tal Wildarrows"):
        flurry = item_effects.required_effect_value(
            "Yun Tal Wildarrows", "bonus_attack_speed_percent"
        )
        champion_stats = dict(champion_stats)
        attack_speed = max(0.0, attack_speed - as_ratio * flurry / 100.0)
        champion_stats["attack_speed"] = attack_speed

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
        if (
            not config.one_rotation
            and item_effects.has_item(items, "Guinsoo's Rageblade")
        ) or item_effects.has_item(items, "Yun Tal Wildarrows"):
            num_auto_attacks = len(
                item_effects.guinsoo_swing_schedule(
                    items,
                    attack_speed=attack_speed,
                    attack_speed_ratio=as_ratio,
                    duration_seconds=fight_duration_seconds,
                    uptime=auto_attack_uptime,
                    critical_chance=champion_stats.get("critical_strike_chance", 0.0)
                    / 100.0,
                )
            )
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
        armor_pen_bonus_percent=armor_pen_bonus_percent,
        flat_armor_pen=flat_armor_pen,
        target_bonus_armor=config.target_bonus_armor,
        physical_damage_flat_reduction=(config.target_physical_damage_flat_reduction),
        physical_damage_flat_reduction_cap=(
            config.target_physical_damage_flat_reduction_cap
        ),
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
        item_options=item_options,
        champion_options=dict(champion_options or {}),
        actualizer_active_until=actualizer_active_until,
        actualizer_basic_cooldown_multiplier=actualizer_basic_cooldown_multiplier,
        ability_haste=champion_stats.get("ability_haste", 0.0),
        one_rotation=config.one_rotation,
        include_actives=config.include_actives,
        auto_attacks_only=config.auto_attacks_only,
        deterministic=config.deterministic,
        is_melee=is_melee,
        level=level,
        enforce_resource_limits=config.enforce_resource_limits,
        resource_restore_events=tuple(config.resource_restore_events),
        resource_ledger_owner=str(config.resource_ledger_owner or "main"),
        target_basic_damage_multiplier=config.target_basic_damage_multiplier,
        target_basic_damage_flat_reduction=(config.target_basic_damage_flat_reduction),
        target_basic_damage_flat_reduction_cap=(
            config.target_basic_damage_flat_reduction_cap
        ),
        target_champion_damage_flat_reduction=(
            config.target_champion_damage_flat_reduction
        ),
        target_champion_dot_damage_flat_reduction=(
            config.target_champion_dot_damage_flat_reduction
        ),
        target_critical_strike_damage_multiplier=(
            config.target_critical_strike_damage_multiplier
        ),
        roster_target_index=max(0, int(config.roster_target_index)),
        roster_target_count=max(1, int(config.roster_target_count)),
        target_class=config.target_class,
        resists=resists,
        magic_amp=damage_effects.magic_amp,
        ability_amp=(
            damage_effects.ability_amp.multiplier(
                champion_stats,
                config.include_actives,
                active=actualizer_active_until > 0.0,
            )
            if damage_effects.ability_amp is not None
            else 1.0
        ),
        basic_amp=(
            damage_effects.basic_amp.multiplier(is_melee)
            if damage_effects.basic_amp is not None
            else 1.0
        ),
        hypershot_amp=damage_effects.hypershot_amp,
        attack_speed=attack_speed,
        attack_speed_ratio=as_ratio,
        num_auto_attacks=num_auto_attacks,
        empowered_autos=empowered_autos,
        keystone_effect=rune_effects.resolve_keystone(config.keystone),
        keystone_options=dict(config.keystone_options),
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
        if "armor_penetration_bonus_percent" in stat_buff:
            resists.armor_pen_bonus_percent = (
                stats.get("armor_penetration_bonus_percent", 0.0) / 100.0
            )
            resists.resolve_armor()
        # Bonus health raises max health, and items converting bonus
        # health to AD (Overlord's Bloodmail) grow with the buff
        # (Cho'Gath R's Feast stacks). The accessor is linear, so the
        # delta composes with the item-health conversion already in the
        # build stats.
        if "bonus_health" in stat_buff:
            stats["health"] = stats.get("health", 0.0) + stat_buff["bonus_health"]
            bloodmail_delta = item_effects.bloodmail_bonus_ad(
                state.items, stat_buff["bonus_health"]
            )
            if bloodmail_delta:
                stats["bonus_attack_damage"] = (
                    stats.get("bonus_attack_damage", 0.0) + bloodmail_delta
                )
                stats["attack_damage"] = stats.get(
                    "base_attack_damage", 0.0
                ) + stats.get("bonus_attack_damage", 0.0)
        # A BASE-health grant (Dr. Mundo R) raises max health exactly like
        # a bonus-health one — so %maximum-health mechanics grow with it —
        # but items converting BONUS health to a stat (Overlord's
        # Bloodmail) must NOT see it. That base-vs-bonus split is the
        # whole reason the two keys are separate (the Gnar rule).
        if "base_health" in stat_buff:
            stats["health"] = stats.get("health", 0.0) + stat_buff["base_health"]
        # Recalculate attack speed and auto count if AS was buffed
        if "bonus_attack_speed" in stat_buff:
            bonus_as_pct = stat_buff["bonus_attack_speed"]
            active_duration = (ability_info.get("auto_attack_override") or {}).get(
                "active_duration"
            )
            if active_duration:
                # P1 Slice 11: the timed Q window [cast_start, cast_start
                # + window) — the autos ride the base rate until the cast,
                # the buffed rate inside the window, then the base rate
                # again (the end-exclusive boundary).  The floor count
                # convention applies per phase (the same drop the engine
                # already does at the fight end).
                window = float(active_duration)
                cast_start = 0.0
                for slot in state.cast_order:
                    if slot == "Q":
                        break
                    cast_start += float(
                        (state.ability_damages.get(slot) or {}).get("cast_time", 0.0)
                        or 0.0
                    )
                base_as = state.attack_speed
                buffed_as = base_as + state.attack_speed_ratio * (bonus_as_pct / 100.0)
                state.q_window_start = cast_start
                state.q_window_end = cast_start + window
                state.q_window_base_rate = base_as
                pre_autos = math.floor(cast_start * base_as * state.auto_attack_uptime)
                in_autos = math.floor(
                    buffed_as
                    * min(
                        window,
                        max(0.0, state.fight_duration_seconds - cast_start),
                    )
                    * state.auto_attack_uptime
                )
                post_autos = math.floor(
                    base_as
                    * max(0.0, state.fight_duration_seconds - state.q_window_end)
                    * state.auto_attack_uptime
                )
                state.attack_speed = buffed_as
                stats["attack_speed"] = state.attack_speed
                state.q_window_autos = in_autos
                state.q_window_pre_autos = pre_autos
                state.num_auto_attacks = pre_autos + in_autos + post_autos
            else:
                state.attack_speed = state.attack_speed + state.attack_speed_ratio * (
                    bonus_as_pct / 100.0
                )
                stats["attack_speed"] = state.attack_speed
                state.num_auto_attacks = math.floor(
                    state.attack_speed
                    * state.fight_duration_seconds
                    * state.auto_attack_uptime
                )
        # A TOTAL-attack-speed multiplier (Bel'Veth True Form) scales the
        # final attack speed, outside the base + ratio x bonus formula.
        # Entries iterate in parse phase order (BUFF-phase bonus-AS
        # grants insert before DAMAGE-phase ultimates), so additive
        # bonus AS is folded in before this multiplies.
        if "total_attack_speed_percent" in stat_buff:
            state.attack_speed *= 1.0 + stat_buff["total_attack_speed_percent"] / 100.0
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

    # Champion-owned crit modifiers (Yasuo/Yone P: "total critical strike
    # chance is doubled from all other sources" and "critical strikes deal
    # only 90% of the critical damage champions usually have" — cached P
    # description prose; the 0.9 factor is also the champion's game stat
    # ``criticalStrikeDamageModifier``).  The first ``crit_modifier``
    # payload in the parsed ability rows applies to BOTH the auto-attack
    # simulation and ability parts that declare ``crit_effectiveness``,
    # because both read the shared ``state.crit_chance`` /
    # ``state.crit_multiplier`` resolved here.  Crit chance in excess of
    # 100% converts to bonus AD ("every 1% critical strike chance in
    # excess of 100% is converted into 0.5 bonus attack damage") — the
    # conversion lands on the same stats the auto stream prices.
    for ability_info in state.ability_damages.values():
        crit_modifier = ability_info.get("crit_modifier")
        if not crit_modifier:
            continue
        chance_multiplier = float(crit_modifier.get("crit_chance_multiplier", 1.0))
        raw_crit_percent = float(stats.get("critical_strike_chance", 0.0) or 0.0)
        state.crit_chance = min(raw_crit_percent / 100.0 * chance_multiplier, 1.0)
        damage_factor = float(crit_modifier.get("crit_damage_multiplier_factor", 1.0))
        state.crit_multiplier = (
            BASE_CRIT_MULTIPLIER + state.damage_effects.crit_damage_bonus
        ) * damage_factor
        excess_percent = raw_crit_percent * chance_multiplier - 100.0
        per_percent = float(
            crit_modifier.get("excess_crit_bonus_ad_per_percent", 0.0) or 0.0
        )
        if excess_percent > 0.0 and per_percent > 0.0:
            stats["bonus_attack_damage"] = (
                stats.get("bonus_attack_damage", 0.0) + excess_percent * per_percent
            )
            stats["attack_damage"] = stats.get("base_attack_damage", 0.0) + stats.get(
                "bonus_attack_damage", 0.0
            )
        break


@dataclass(frozen=True)
class AbilityItemApplication:
    """One ability-carried item application in the rotation's hit order.

    ``on_hit`` applications deal per-hit item damage and count on the
    shared on-hit counters (Kraken/Hullbreaker); ``on_attack``
    applications advance on-attack cadences (Guinsoo's phantom hit).
    Bel'Veth Q is on_hit only; her E slashes are both.
    """

    effectiveness: float
    target_hp: float  # modeled target HP when the hit landed
    on_hit: bool
    on_attack: bool
    # Authored hit boundary for the ability carrier.  ``None`` is retained
    # for legacy modules that do not publish an intra-cast ledger; stateful
    # on-hit effects must fail closed when any required carrier is untimed.
    time: float | None = None


@dataclass
class RotationResult:
    """Values produced by the ability rotation and consumed by later steps."""

    total_ability_casts: int = 0
    total_ability_hits: int = 0  # damaging hit instances, for stack counters
    # Basic attacks forced by empowered-auto casts when there is no auto
    # stream (one-rotation, or timed at zero uptime). These are real
    # attacks: they consume spellblade charges like any auto.
    forced_basic_attacks: int = 0
    # How many CASTS forced those attacks. A spellblade charge is armed
    # per ability cast, so one cast spends at most one however many
    # attacks it forces: Jayce's single Hyper Charge cast fires 3 attacks
    # but cannot proc Essence Reaver three times, while Camille's Q1 and
    # Q2 are two casts and legitimately proc twice.
    forced_swing_casts: int = 0
    total_muramana_procs: int = 0  # one per cast; multi-cast R counts each
    first_ability_damage: float = 0.0  # Horizon Focus trigger (not amped)
    has_navori: bool = False
    navori_refund: float = 0.0
    autos_per_second: float = 0.0
    last_cast_time: float = 0.0  # timed mode: when the final recast lands
    cast_events: list[dict[str, Any]] = field(default_factory=list)
    control_events: list[dict[str, Any]] = field(default_factory=list)
    resource_spent: float = 0.0
    resource_remaining: float = 0.0
    # P3 slice 1: the typed mana ledger's public section (None on energy
    # and legacy walks).
    resource_ledger: dict[str, Any] | None = None
    # Ability-carried item applications, in rotation order. They lead
    # the fight's shared counters — autos continue the same counters
    # afterwards (which counter a source advances is decided by the
    # item taxonomy, item_effects.counter_trigger).
    ability_item_applications: list[AbilityItemApplication] = field(
        default_factory=list
    )


def _empower_hits(empower: Any) -> int:
    """Basic attacks one empowered-auto cast rides or forces.

    ``empowers_next_auto`` is ``True`` (one attack — Vayne Q) or a dict
    that may carry ``hits`` (Cho'Gath E empowers the next 3). Absent
    ``hits`` defaults to 1.
    """
    return int(empower.get("hits", 1)) if isinstance(empower, dict) else 1


def _empower_cooldown_delay(empower: Any) -> float:
    """Seconds an empowered burst runs BEFORE its cooldown starts.

    An ability whose ``empowers_next_auto`` declares
    ``cooldown_starts_after_hits`` does not begin its timer on cast —
    consuming the last empowered attack does (Jayce's Hyper Charge). The
    burst's own duration is therefore dead time on the ability's cycle,
    which both delays the recast and means those attacks cannot refund
    this ability's cooldown (Navori) — it is not running yet. Zero for
    every other empowered auto, whose cooldown starts on cast.
    """
    if not isinstance(empower, dict):
        return 0.0
    if not empower.get("cooldown_starts_after_hits"):
        return 0.0
    rate = _empower_burst_attack_speed(empower)
    return _empower_hits(empower) / rate if rate > 0 else 0.0


def _empower_burst_attack_speed(empower: Any) -> float:
    """Rate the empowered swings fire at, or 0 when they ride the fight's.

    An ``empowers_next_auto`` dict may declare ``attack_speed``: its hits
    are fired at THAT rate rather than the champion's ordinary one
    (Jayce's Hyper Charge caps his attack speed for exactly 3 attacks).
    Such a burst is self-supplying — the cast forces its attacks whatever
    the ambient auto stream is doing — and it costs the fight only the
    little time those attacks occupy, leaving the rest of the fight
    running at the ordinary rate. Absent, the swings are ordinary autos.
    """
    if not isinstance(empower, dict):
        return 0.0
    return float(empower.get("attack_speed", 0.0))


def _empower_authored_timing(empower: Any) -> tuple[float, float] | None:
    """Return module-authored first-hit delay and interval for a burst.

    The timing is used only when the ability must force its own attacks
    because no ambient auto stream exists. Timed fights with an auto stream
    keep those attacks on that stream; a champion module can mark that case
    as requiring explicit coupling before its timeline is certified.
    """
    if not isinstance(empower, dict):
        return None
    timing = empower.get("authored_timing")
    if not isinstance(timing, dict):
        return None
    first = float(timing.get("first_attack_delay", 0.0))
    interval = float(timing.get("attack_interval", 0.0))
    if first < 0 or interval < 0:
        raise ValueError("Empowered attack timing cannot be negative")
    return first, interval


def _ability_mr(resists: Resists, ult_cast: bool, vile_decay_stacks: int) -> float:
    """Effective MR one ability's magic damage is mitigated by.

    Malignance's Hatefog only applies once R has been cast (``ult_cast``),
    and Bloodletter's Curse deepens the reduction per Vile Decay stack.
    """
    if resists.mr_reduction_effect is None or vile_decay_stacks <= 0:
        return (
            resists.effective_mr_post_ult if ult_cast else resists.effective_mr_pre_ult
        )
    base = resists.reduced_mr if ult_cast else resists.base_mr
    reduced = reduce_resistance(
        base,
        resists.mr_reduction_effect.reduction_per_stack * vile_decay_stacks * 100.0,
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
    armor_pct = debuff.get("armor_reduction_percent", 0.0)
    armor_flat = debuff.get("armor_reduction_flat", 0.0) * fraction
    if armor_pct or armor_flat:
        resists.shred_armor(armor_pct * fraction, armor_flat)
    mr_pct = debuff.get("mr_reduction_percent", 0.0)
    mr_flat = debuff.get("mr_reduction_flat", 0.0) * fraction
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

    def apply_remainder(self, coverage: float = 1.0) -> None:
        """Top the shred up to its lasting share of the reduction.

        The stages that already fired did so DURING the ability's own
        hits, when the debuff is freshly applied and so at full strength.
        ``coverage`` is the share that outlives the ability (see
        ``_debuff_coverage``), so this SETTLES the total at it rather
        than adding a flat remainder — at full coverage that is exactly
        the old ``(stacks - fired) / stacks``. The settlement is signed:
        a debuff that fully staged during its own ticks but expires
        before the fight ends hands part of the reduction back, which is
        exact for the flat shreds ramps actually use (Corki's Gatling
        Gun is the only one) and approximate for a percent one.
        """
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
    ult_cast: bool,
    vile_decay_stacks: int,
) -> _ShredRamp | _ThresholdShred | None:
    """Build the hit ramp/threshold for a target debuff, else None."""
    debuff = ability_info.get("target_debuff")
    threshold_hits = int(debuff.get("threshold_hits", 0)) if debuff else 0
    if threshold_hits > 0:
        if debuff.get("stacks"):
            raise ValueError(
                f"{ability_info.get('name', '?')!r}: target_debuff cannot declare "
                "both threshold_hits and stacks"
            )
        return _ThresholdShred(
            resists=resists,
            debuff=debuff,
            threshold_hits=threshold_hits,
        )
    stacks = int(debuff.get("stacks", 0)) if debuff else 0
    if stacks <= 0:
        return None
    if debuff.get("armor_reduction_percent") or debuff.get("mr_reduction_percent"):
        raise ValueError(
            f"{ability_info.get('name', '?')!r}: a ramped target_debuff must "
            "reduce resistances by a FLAT amount — percent stages compound "
            "multiplicatively and cannot be split into equal shares"
        )
    return _ShredRamp(
        resists=resists,
        debuff=debuff,
        stacks=stacks,
        ability_mr=lambda: _ability_mr(resists, ult_cast, vile_decay_stacks),
    )


def _mitigate_hits(
    state: "FightState",
    part: DamagePart,
    raw: float,
    ability_mr: float,
    hits: int,
    rock_solid_instances: int = 0,
    damage_over_time: bool = False,
) -> float:
    """Mitigated damage for *hits* identical hits of one damage part."""
    if part.damage_type == "true":
        mitigated = raw * hits
    elif part.damage_type == "physical":
        reduced_raw = _apply_physical_damage_reduction(raw, state.resists)
        mitigated = apply_resistance(reduced_raw, state.resists.effective_armor) * hits
    else:
        mitigated = apply_resistance(raw, ability_mr) * state.magic_amp * hits
    mitigated = _apply_basic_amp(state, part, mitigated)
    if part.basic_damage and part.damage_type != "true":
        mitigated = _apply_target_basic_damage_reduction(
            state,
            mitigated,
            hits=hits,
            rock_solid_instances=rock_solid_instances,
        )
    if part.damage_type != "true":
        mitigated = _apply_target_champion_damage_reduction(
            state,
            mitigated,
            hits=hits,
            damage_over_time=damage_over_time,
        )
    return mitigated


def _evaluate_cast_parts(
    state: "FightState",
    parts: tuple[DamagePart, ...],
    num_casts: int,
    ability_mr: float,
    running_damage: float,
    *,
    on_hit: "Callable[[float], float] | None" = None,
    pricing: "tuple[CastPricing, ...] | None" = None,
    cast_times: "tuple[float, ...] | None" = None,
    single_hit_event_certified: bool = False,
    damage_over_time: bool = False,
    ferocity_empowered: "tuple[bool, ...] | None" = None,
    empowered_parts: "tuple[DamagePart, ...] | None" = None,
    cc_reviewed: bool = False,
) -> tuple[float, float, dict[str, float], list[dict[str, Any]]]:
    """Evaluate an ability's typed damage parts over its casts.

    Returns total mitigated damage pre-amp; the first part's mitigated
    damage on the first cast (the Horizon Focus trigger value for mixed
    entries); per-damage-type mitigated totals pre-amp; and any authored
    absolute hit events.
    Threads running target damage through every part and cast so
    HP-scaled parts see prior hits (Akali R2 after R1, Kog'Maw R shot
    after shot).

    ``on_hit`` runs after every individual hit and returns the ability's
    MR for the hits that follow — the seam a ramped resistance shred uses
    to land between an ability's own ticks (Corki E), keeping the "a
    shred never boosts the hit that applied it" rule per tick. Without
    it a part's hits are priced in one multiply, as they always were.

    ``pricing`` carries one :class:`CastPricing` per cast, from the
    fight's stack timeline: a mid-fight bonus-AD steroid active at that
    cast (re-pricing ``bonus_ad_ratio`` parts) and the DoT stacks on the
    target (counting ``dot_stack_scaled`` parts). Absent, every cast is
    priced against the fight's static stats, exactly as before.
    """
    target_health = state.target_health
    total = 0.0
    by_type: dict[str, float] = {}
    damage_events: list[dict[str, Any]] = []
    first_part_first_cast = 0.0
    has_dynamic_part = any(part.hp_scaled_damage is not None for part in parts)
    for cast_index in range(num_casts):
        price = pricing[cast_index] if pricing is not None else _NO_PRICING
        rock_solid_consumed = False
        # P3 package 3V: a live Ferocity-empowered cast prices the
        # module's empowered part set instead of the base parts.
        cast_parts = (
            empowered_parts
            if empowered_parts is not None
            and ferocity_empowered is not None
            and cast_index < len(ferocity_empowered)
            and ferocity_empowered[cast_index]
            else parts
        )
        for part_index, part in enumerate(cast_parts):
            if part.hp_scaled_damage is not None:
                hp_now = max(0.0, target_health - running_damage)
                missing_ratio = (
                    1.0 - hp_now / target_health if target_health > 0 else 1.0
                )
                raw = part.hp_scaled_damage(missing_ratio)
            else:
                raw = part.amount
            # A mid-fight bonus-AD steroid re-prices the part's declared
            # derivative in bonus AD (Darius' Noxian Might).
            raw += part.bonus_ad_ratio * price.bonus_attack_damage
            hits = price.dot_stacks if part.dot_stack_scaled else part.count
            if part.crit_effectiveness > 0:
                eff = part.crit_effectiveness
                crit_probability = min(1.0, eff * state.crit_chance)
                target_crit_multiplier = (
                    1.0
                    if part.damage_type == "true"
                    else getattr(
                        state,
                        "target_critical_strike_damage_multiplier",
                        1.0,
                    )
                )
                raw *= (
                    1.0
                    - crit_probability
                    + crit_probability * state.crit_multiplier * target_crit_multiplier
                )
            rock_solid_instances = int(
                part.basic_damage
                and part.damage_type != "true"
                and hits > 0
                and raw > 0
                and not rock_solid_consumed
            )
            # Hits after the first are identical calls when nothing varies
            # per hit: no per-hit event authoring, no on-hit MR seam, and
            # no Hexoptics bonus tracking (its info-row accumulates per
            # call).  Price one hit and replay the identical value — the
            # same float added the same number of times in the same order.
            repeat_pure = (
                on_hit is None
                and not has_dynamic_part
                and part.time_offset is None
                and not (part.basic_damage and state.basic_amp > 1.0)
            )
            repeat_damage = (
                _mitigate_hits(
                    state,
                    part,
                    raw,
                    ability_mr,
                    1,
                    damage_over_time=damage_over_time,
                )
                if repeat_pure and hits > 1
                else None
            )
            # Dynamic target-health parts need to escape the aggregate
            # breakdown as well.  The normal cast-boundary fallback prices
            # them once against the pair's full-health target; the coupled
            # participant ledger can then re-price the event against the
            # live target HP.  When the source does not give sub-hit
            # timing, all of the part's hits intentionally share the cast
            # boundary and are marked as such below.  If one part reads
            # live target HP, export every part of the cast so the coupled
            # ledger does not lose a preceding flat hit (Akali R1 + R2 is
            # the important example).  Everything constant across the hits
            # is resolved here, once per part and cast.
            # A reviewed module may explicitly certify a single static hit at
            # the cast boundary (for example a direct spell whose cached
            # packet has no separate travel/tick phase).  Carry that proof
            # into the ledger so ordered item triggers such as Eclipse do not
            # fall back to an aggregate/coarse proc merely because the
            # ability has no sub-cast offset.
            emit_events = (
                (single_hit_event_certified and hits == 1 and len(parts) == 1)
                or (
                    part.time_offset is not None
                    and (hits == 1 or part.hit_interval is not None)
                )
                or has_dynamic_part
                or part.cc_duration > 0.0
                or part.skillshot
            )
            if emit_events:
                cast_time = (
                    cast_times[cast_index]
                    if cast_times is not None and cast_index < len(cast_times)
                    else 0.0
                )
                event_base_time = cast_time + (
                    part.time_offset if part.time_offset is not None else 0.0
                )
                event_interval = part.hit_interval or 0.0
                event_precision = (
                    "exact"
                    if single_hit_event_certified and hits == 1 and len(parts) == 1
                    else (
                        "exact"
                        if part.time_offset is not None
                        and part.hit_interval is not None
                        else (
                            "hit" if part.time_offset is not None else "cast_boundary"
                        )
                    )
                )
                event_missing_ratio = (
                    missing_ratio if part.hp_scaled_damage is not None else None
                )
            mitigated = 0.0
            for hit_index in range(hits):
                if repeat_damage is not None and (
                    hit_index > 0 or not rock_solid_instances
                ):
                    mitigated += repeat_damage
                    continue
                hit_damage = _mitigate_hits(
                    state,
                    part,
                    raw,
                    ability_mr,
                    1,
                    rock_solid_instances=int(
                        rock_solid_instances > 0 and hit_index == 0
                    ),
                    damage_over_time=damage_over_time,
                )
                mitigated += hit_damage
                if emit_events:
                    damage_events.append(
                        {
                            "time": event_base_time + hit_index * event_interval,
                            "damage_type": part.damage_type,
                            "damage": hit_damage,
                            # Forced/empowered basic attacks ride an ability
                            # row (for example Blitzcrank E or Vayne Q), so
                            # preserve their attack identity for reactive
                            # defender effects such as Bramble/Thornmail.
                            "basic_attack": bool(part.basic_damage),
                            "raw_damage": raw,
                            "raw_formula": part.hp_scaled_damage,
                            "source_missing_ratio": event_missing_ratio,
                            "event_precision": event_precision,
                            **({"damage_over_time": True} if damage_over_time else {}),
                            **(
                                {
                                    "cc_kind": str(part.cc_kind),
                                }
                                if part.cc_kind is not None
                                else {}
                            ),
                            **(
                                {"cc_reviewed": True}
                                if (
                                    cc_reviewed
                                    and (
                                        part.cc_kind is None
                                        or str(part.cc_kind).lower().strip()
                                        in (ACTION_BLOCKING_CC_KINDS | {"slow"})
                                    )
                                )
                                or (
                                    part.cc_kind is not None
                                    and str(part.cc_kind).lower().strip()
                                    in (ACTION_BLOCKING_CC_KINDS | {"slow"})
                                )
                                else {}
                            ),
                            **(
                                {"cc_duration": float(part.cc_duration)}
                                if part.cc_duration > 0.0
                                else {}
                            ),
                            **(
                                {
                                    "control_source_atoms": [
                                        dict(atom) for atom in part.control_source_atoms
                                    ]
                                }
                                if part.control_source_atoms
                                else {}
                            ),
                            **({"skillshot": True} if part.skillshot else {}),
                        }
                    )
                if on_hit is not None:
                    ability_mr = on_hit(ability_mr)
            if rock_solid_instances:
                rock_solid_consumed = True
            if cast_index == 0 and part_index == 0:
                first_part_first_cast = mitigated
            total += mitigated
            by_type[part.damage_type] = by_type.get(part.damage_type, 0.0) + mitigated
            running_damage += mitigated
    return total, first_part_first_cast, by_type, damage_events


def _apply_post_hit_proc(
    state: "FightState",
    trigger_key: str,
    ability_info: dict[str, Any],
    num_casts: int,
    cast_times: tuple[float, ...],
    running_damage: float,
) -> float:
    """Apply a proc that lands after its triggering hit.

    Some passives cannot be flattened into their triggering spell without
    breaking resistance order. Vi's Denting Blows, for example, deals its
    third-stack damage at the old armor value and only then reduces armor for
    later hits. A champion module attaches ``post_hit_proc`` to the ability
    that completes the stack cycle; this hook prices the proc, records its
    authored hit event, and applies its debuff afterwards. It is not counted
    as a cast and therefore cannot invent Muramana, burn, or spell-effect
    triggers.
    """
    spec = ability_info.get("post_hit_proc")
    if not spec or num_casts <= 0:
        return 0.0

    parts = tuple(spec.get("parts", ()))
    if not parts:
        return 0.0
    total, _, by_type, events = _evaluate_cast_parts(
        state,
        parts,
        num_casts,
        state.resists.effective_mr,
        running_damage,
        cast_times=cast_times,
    )
    if total <= 0:
        return 0.0

    row_key = str(spec.get("breakdown_key", f"post_hit_proc_{trigger_key}"))
    row: dict[str, Any] = {
        "name": str(spec.get("name", "Post-hit proc")),
        "count": num_casts,
        "damage_per_hit": total / num_casts,
        "unit": "procs",
        "total_damage": total,
        **_damage_type_fields(by_type),
    }
    if spec.get("detail"):
        row["detail"] = str(spec["detail"])
    timing_is_authored = all(
        part.time_offset is not None
        and (part.count <= 1 or part.hit_interval is not None)
        for part in parts
    )
    if timing_is_authored and events:
        row["damage_events"] = events
        row["event_phase"] = "proc"
    state.breakdown[row_key] = row
    state.total_damage += total

    debuff = spec.get("target_debuff")
    if debuff:
        coverage = (
            1.0
            if state.one_rotation
            else _debuff_coverage(
                cast_times,
                debuff.get("duration", 0.0),
                state.fight_duration_seconds,
            )
        )
        _apply_target_shred(state.resists, debuff, coverage)
    return total


def _effective_timed_cooldown(
    state: "FightState",
    result: "RotationResult",
    ability_key: str,
    ability_info: dict,
    basic_ability_haste: float,
) -> float:
    """Effective recast cooldown in timed mode: ability haste, Spear of
    Shojin basic-ability haste (Q/W/E), ultimate haste (R), and Navori
    auto-attack refunds."""
    base_cd = ability_info.get("cooldown", 0.0)
    total_haste = state.ability_haste
    if ability_key in ("Q", "W", "E"):
        total_haste += basic_ability_haste
    elif ability_key == "R":
        total_haste += float(state.champion_stats.get("ultimate_haste", 0.0) or 0.0)
    cd = effective_cooldown(base_cd, total_haste)
    if result.navori_refund > 0 and cd > 0 and ability_key in ("Q", "W", "E"):
        cd = _navori_effective_cd(cd, result.autos_per_second, result.navori_refund)
    return cd


def _cooldown_ready_at(
    state: "FightState", cooldown_start: float, cooldown: float
) -> float:
    """Return a cooldown's ready timestamp across an Actualizer window.

    Mana Made Real accelerates basic-ability cooldown *progress* only while
    its explicit eight-second window is active.  A single multiplied duration
    is wrong when a cooldown straddles that boundary, so consume the active
    portion first and continue the remainder at the ordinary rate.
    """
    if (
        cooldown <= 0.0
        or state.actualizer_active_until <= cooldown_start + _CAST_SCHEDULE_EPS
        or state.actualizer_basic_cooldown_multiplier >= 1.0
    ):
        return cooldown_start + cooldown
    progress_rate = 1.0 / state.actualizer_basic_cooldown_multiplier
    active_seconds = state.actualizer_active_until - cooldown_start
    active_progress = active_seconds * progress_rate
    if active_progress >= cooldown:
        return cooldown_start + cooldown / progress_rate
    return state.actualizer_active_until + (cooldown - active_progress)


_CAST_SCHEDULE_EPS = 1e-9


def _schedule_shared_casts(
    state: "FightState",
    result: "RotationResult",
    basic_ability_haste: float,
) -> dict[str, list[float]]:
    """Timed-mode cast start times on ONE shared timeline.

    The champion has one set of hands: each cast occupies its
    ``cast_time`` (stamped from the wiki by the champion engine; absent
    means instant, preserving the legacy ``1 + T/cd`` counts), and an
    ability recasts when its cooldown — running from the END of its
    cast — is back up and no other cast is in progress. Ties break by
    cast_order position. R and zero-cooldown entries cast exactly once
    (unchanged timed-mode rules); recast entries ride their parent's
    casts and are not scheduled. A cast counts if it STARTS within the
    fight duration. Cassiopeia's 0.75s-cooldown E exposed the old
    independent-timeline formula overcounting (5 casts vs 3 in-game
    over a 3s fight).
    """
    duration = state.fight_duration_seconds
    # Mirror the rotation loop's recast pairing exactly: an entry rides
    # its parent's casts only when the parent appears EARLIER in the
    # cast order; otherwise it schedules independently (legacy rule).
    seen: set[str] = set()
    keys: list[str] = []
    for key in state.cast_order:
        info = state.ability_damages.get(key)
        if info is None:
            continue
        parent = info.get("recast_of")
        if not (parent and parent in seen):
            keys.append(key)
        seen.add(key)
    cooldowns = {
        key: _effective_timed_cooldown(
            state, result, key, state.ability_damages[key], basic_ability_haste
        )
        for key in keys
    }
    cast_times = {key: state.ability_damages[key].get("cast_time", 0.0) for key in keys}
    # Dead time between the cast finishing and its cooldown starting: an
    # empowered burst whose timer only begins once its attacks are spent.
    cooldown_delays = {
        key: _empower_cooldown_delay(
            state.ability_damages[key].get("empowers_next_auto")
        )
        for key in keys
    }
    single_cast = {key for key in keys if key == "R" or cooldowns[key] <= 0}

    times: dict[str, list[float]] = {key: [] for key in keys}
    next_ready = dict.fromkeys(keys, 0.0)
    pending = set(keys)
    now = 0.0
    while pending and now <= duration + _CAST_SCHEDULE_EPS:
        ready = [
            key
            for key in keys
            if key in pending and next_ready[key] <= now + _CAST_SCHEDULE_EPS
        ]
        if not ready:
            # Hands free but everything on cooldown — jump to the next
            # ready time (strictly advances: nothing was ready at now).
            now = min(next_ready[key] for key in pending)
            continue
        key = ready[0]
        times[key].append(now)
        if key in single_cast:
            pending.remove(key)
        else:
            cooldown_start = now + cast_times[key] + cooldown_delays[key]
            next_ready[key] = _cooldown_ready_at(
                state,
                cooldown_start,
                cooldowns[key],
            )
        now += cast_times[key]
    return times


def _apply_empowered_burst_autos(state: "FightState", plan: "CastPlan") -> None:
    """Re-time the auto stream around empowered bursts that set their rate.

    A burst declaring ``attack_speed`` (Jayce's Hyper Charge) fires its
    hits at the cap instead of the champion's ordinary rate, so it costs
    the fight only ``hits / burst_as`` seconds. The rest of the fight
    still runs at the ordinary rate, which means the burst does not just
    re-price attacks — it BUYS extra ordinary autos with the time it
    saved. Total attacks become ``normal autos in the leftover time`` plus
    the burst swings themselves (which the breakdown later moves onto the
    ability's own row).

    A fight with no auto stream is left alone: those casts force their
    own swings onto their ability row instead (see the empowered-auto
    branch in the rotation).
    """
    if state.num_auto_attacks <= 0 or state.auto_attack_uptime <= 0:
        return

    burst_swings = 0
    burst_seconds = 0.0
    for ability_key in state.cast_order:
        ability_info = state.ability_damages.get(ability_key)
        if not ability_info:
            continue
        empower = ability_info.get("empowers_next_auto")
        burst_as = _empower_burst_attack_speed(empower) if empower else 0.0
        if burst_as <= 0:
            continue
        swings = plan.counts.get(ability_key, 0) * _empower_hits(empower)
        if swings <= 0:
            continue
        burst_swings += swings
        burst_seconds += swings / burst_as

    if burst_swings <= 0:
        return

    leftover = max(0.0, state.fight_duration_seconds - burst_seconds)
    normal_autos = math.floor(state.attack_speed * leftover * state.auto_attack_uptime)
    state.num_auto_attacks = normal_autos + burst_swings


@dataclass(frozen=True)
class CastPlan:
    """When every ability entry casts, resolved BEFORE any damage is priced.

    The rotation used to decide an ability's cast count inline, one
    ability at a time. Stack-timeline mechanics (Case 4/5) need the whole
    fight's cast schedule up front — a cast at t=3s must know which
    stacks and buffs the casts before it produced — so the resolution is
    a pass of its own.

    Mode rules are unchanged: autos-only casts nothing, one-rotation
    casts every entry once at t=0, and timed mode reads the shared cast
    schedule (a recast rides its parent's count when the parent appears
    earlier in the cast order). ``times`` always holds one timestamp per
    cast, 0.0-filled for entries the scheduler never placed;
    ``last_cast_time`` counts only genuinely scheduled casts.
    """

    counts: dict[str, int]
    times: dict[str, tuple[float, ...]]
    last_cast_time: float
    resource_spent: float = 0.0
    resource_remaining: float = 0.0
    omitted_for_resource: tuple[str, ...] = ()
    resource_by_cast: dict[tuple[str, int], dict[str, float]] = field(
        default_factory=dict
    )
    # P3 slice 1: the typed mana ledger's public section (built only by the
    # MANA admission path; None for energy/legacy walks).
    resource_ledger: dict[str, Any] | None = None


def _resolve_cast_plan(
    state: FightState,
    schedule: dict[str, list[float]],
) -> CastPlan:
    """Resolve every ability entry's cast count and cast times."""
    counts: dict[str, int] = {}
    times: dict[str, tuple[float, ...]] = {}
    last_cast_time = 0.0

    for ability_key in state.cast_order:
        ability_info = state.ability_damages.get(ability_key)
        if ability_info is None:
            continue

        scheduled: list[float] = []
        if state.auto_attacks_only:
            num_casts = 0
        elif state.one_rotation:
            num_casts = 1
        else:
            # Recasts (e.g. Q2) always match their parent ability's casts.
            parent_key = ability_info.get("recast_of")
            if parent_key and parent_key in counts:
                num_casts = counts[parent_key]
                scheduled = list(times[parent_key])
            else:
                scheduled = schedule[ability_key]
                # Empowered-auto abilities (Vayne Q) only deal damage
                # through the next basic attack(s), so casts can never
                # exceed the autos that consume them (a multi-hit empower
                # like Cho'Gath E consumes ``hits`` autos per cast). The
                # auto count itself is untouched: such casts are attack
                # resets, spent in attack-cooldown dead time (the in-game
                # reset acceleration is not modeled — conservative). With
                # no auto stream at all (zero uptime), each cast forces
                # its own attack(s) instead.
                empower = ability_info.get("empowers_next_auto")
                # A burst that fires at its OWN rate supplies the attacks
                # it needs (Jayce's Hyper Charge), so the ambient auto
                # count never limits it — only its cooldown does.
                if (
                    empower
                    and state.num_auto_attacks > 0
                    and not _empower_burst_attack_speed(empower)
                ):
                    scheduled = scheduled[
                        : state.num_auto_attacks // _empower_hits(empower)
                    ]
                num_casts = len(scheduled)
                # Burns use the fight-wide last cast as their final refresh.
                if scheduled:
                    last_cast_time = max(last_cast_time, scheduled[-1])

        counts[ability_key] = num_casts
        times[ability_key] = tuple(scheduled) if scheduled else (0.0,) * num_casts

    return CastPlan(counts=counts, times=times, last_cast_time=last_cast_time)


def _apply_resource_limits(state: FightState, plan: CastPlan) -> CastPlan:
    """Drop casts that cannot be paid for on the shared cast timeline.

    P3 slice 1: MANA fights run through the typed mana resource ledger
    (``resource_ledger``) — one account owns regen ticks, external
    restores (Catalyst's Eternity, Essence Reaver's Spellblade), ability
    restores, cast spends, Tear's max-mana growth, and Lost Chapter's
    Enlighten.  ENERGY fights (and any MANA fight declaring a temporary
    maximum bonus, which no champion sets today) keep the legacy admission
    walk verbatim so behavior is bit-for-bit unchanged.
    """
    if not state.enforce_resource_limits:
        # Direct engine callers may provide an intentionally partial stat
        # packet. The typed pipeline opts in after it has resolved the full
        # champion stat and ability packets.
        return plan
    resource_types = {
        str(info.get("resource_type", "NONE"))
        for info in state.ability_damages.values()
    }
    resource_types.discard("NONE")
    resource_types.discard("RAGE")
    if not resource_types:
        return plan
    if len(resource_types) != 1:
        state.notes.append("Resource limits unavailable: mixed resource types.")
        return plan
    resource_type = next(iter(resource_types))
    if resource_type not in {"MANA", "ENERGY"}:
        state.notes.append(
            f"Resource limits unavailable for {resource_type.lower().replace('_', ' ')}."
        )
        return plan
    if resource_type == "ENERGY":
        return _apply_resource_limits_legacy(state, plan, resource_type)
    if any(
        float(info.get("resource_maximum_bonus", 0.0) or 0.0) > 0.0
        for info in state.ability_damages.values()
    ):
        # Only Akali (ENERGY) declares a temporary maximum bonus today.  A
        # MANA ability doing so has no certified ledger representation in
        # this slice; keep the legacy walk and say so instead of guessing.
        state.notes.append(
            "Resource ledger unavailable: temporary maximum bonus declared "
            "for a mana resource."
        )
        return _apply_resource_limits_legacy(state, plan, resource_type)
    return _apply_mana_resource_limits(state, plan)


def _apply_resource_limits_legacy(
    state: FightState, plan: CastPlan, resource_type: str
) -> CastPlan:
    """Legacy admission walk (ENERGY resources; unchanged behavior)."""
    base_maximum = float(state.champion_stats.get("max_mana", 0.0))
    remaining = base_maximum
    regen = float(state.champion_stats.get("resource_regen_per_second", 0.0))
    events: list[tuple[float, int, int, str]] = []
    order = {key: index for index, key in enumerate(state.cast_order)}
    for key, times in plan.times.items():
        events.extend(
            (cast_time, order.get(key, len(order)), ordinal, key)
            for ordinal, cast_time in enumerate(times)
        )
    events.sort()

    accepted: dict[str, list[float]] = {key: [] for key in plan.times}
    accepted_ordinals: dict[str, set[int]] = {key: set() for key in plan.times}
    omitted: list[str] = []
    spent = 0.0
    previous_time = 0.0
    maximum_bonus = 0.0
    maximum_bonus_until = -1.0
    resource_by_cast: dict[tuple[str, int], dict[str, float]] = {}

    proc_restore = next(
        (
            info
            for info in state.ability_damages.values()
            if float(info.get("resource_restore_per_proc", 0.0)) > 0
            and int(info.get("proc_count", 0)) > 0
        ),
        None,
    )
    proc_restores_left = int(proc_restore.get("proc_count", 0)) if proc_restore else 0

    # Essence Reaver's Manaflow is restored by the accepted Spellblade attack,
    # not by the ability that arms it.  Keep those restores on the same
    # ordered resource timeline so a later cast can actually spend the mana
    # the preceding empowered attack returned.  Scheduling the restore only
    # after its arming cast is accepted also prevents an omitted cast from
    # minting phantom resources.
    spellblade = state.damage_effects.spellblade
    mana_restore_per_proc = 0.0
    spellblade_cooldown_ready = float("-inf")
    spellblade_restore_count = 0
    if (
        resource_type == "MANA"
        and spellblade is not None
        and (
            spellblade.mana_restore_base_ad_ratio or spellblade.mana_restore_crit_ratio
        )
        and state.num_auto_attacks > 0
    ):
        stats = state.champion_stats
        mana_restore_per_proc = item_effects.essence_reaver_mana_restore_per_proc(
            base_attack_damage=stats.get("base_attack_damage", 0.0),
            critical_strike_chance=stats.get("critical_strike_chance", 0.0),
            item_name=spellblade.source.item_name,
        )

    # Heap entries are (time, phase, cast-order, ordinal, kind, key, amount).
    # Restore events sort before a cast at the same timestamp, matching the
    # attack landing before a simultaneous ability input is evaluated.
    timeline: list[tuple[float, int, int, int, str, str, float]] = [
        (cast_time, 1, order_index, ordinal, "cast", key, 0.0)
        for cast_time, order_index, ordinal, key in events
    ]
    # Catalyst's damage-taken restoration is an external, timestamped input
    # from the coupled participant ledger.  It is ordered before casts at the
    # same timestamp, matching the sourced hit -> resource update -> input
    # sequence.  Malformed rows are ignored here; the producer is required to
    # fail closed before constructing this typed tuple.
    for restore_index, (restore_time, restore_amount) in enumerate(
        state.resource_restore_events
    ):
        try:
            restore_time = float(restore_time)
            restore_amount = float(restore_amount)
        except (TypeError, ValueError):
            continue
        if (
            not math.isfinite(restore_time)
            or not math.isfinite(restore_amount)
            or restore_amount <= 0.0
            or restore_time < 0.0
            or restore_time > state.fight_duration_seconds + _CAST_SCHEDULE_EPS
        ):
            continue
        timeline.append(
            (
                restore_time,
                0,
                -1,
                restore_index,
                "restore",
                "Catalyst of Aeons",
                restore_amount,
            ),
        )
    heapq.heapify(timeline)
    while timeline:
        (
            cast_time,
            _phase,
            _order_index,
            ordinal,
            kind,
            key,
            restore_amount,
        ) = heapq.heappop(timeline)
        maximum = base_maximum + (
            maximum_bonus if cast_time < maximum_bonus_until else 0.0
        )
        remaining = min(
            maximum, remaining + max(0.0, cast_time - previous_time) * regen
        )
        previous_time = cast_time
        if kind == "restore":
            remaining = min(maximum, remaining + restore_amount)
            continue
        info = state.ability_damages[key]
        parent = info.get("recast_of")
        if parent and ordinal not in accepted_ordinals.get(parent, set()):
            omitted.append(key)
            continue
        cost = float(info.get("resource_cost", 0.0))
        if (
            cost > 0.0
            and state.actualizer_active_until > cast_time + _CAST_SCHEDULE_EPS
            and item_effects.has_item(state.items, "Actualizer")
        ):
            cost *= item_effects.required_effect_value(
                "Actualizer", "mana_cost_multiplier"
            )
        if cost > remaining + _CAST_SCHEDULE_EPS:
            omitted.append(key)
            continue
        before = remaining
        remaining -= cost
        spent += cost
        cast_maximum_bonus = float(info.get("resource_maximum_bonus", 0.0))
        if cast_maximum_bonus > 0:
            maximum_bonus = max(maximum_bonus, cast_maximum_bonus)
            maximum_bonus_until = max(
                maximum_bonus_until,
                cast_time + float(info.get("resource_maximum_bonus_duration", 0.0)),
            )
            maximum = base_maximum + maximum_bonus

        restored = float(info.get("resource_restore", 0.0))
        if proc_restore is not None and proc_restores_left > 0:
            # A fixed-count proc entry represents those procs as having
            # happened in this scenario. For Ambessa, each accepted ability
            # cast mints one passive stack and the model weaves the selected
            # empowered attacks between casts, so their energy restoration
            # belongs on the same ordered resource timeline.
            restored += float(proc_restore["resource_restore_per_proc"])
            proc_restores_left -= 1
        remaining = min(maximum, remaining + restored)
        accepted_ordinal = len(accepted[key])
        accepted[key].append(cast_time)
        accepted_ordinals[key].add(ordinal)
        if not state.score_only:
            # Per-cast resource rows serve only the public cast-timeline
            # receipt; nothing on the scoring path reads them.
            resource_by_cast[(key, accepted_ordinal)] = {
                "resource_before": before,
                "resource_restored": restored,
                "resource_after": remaining,
            }

        if mana_restore_per_proc > 0.0 and spellblade is not None:
            # One Spellblade proc is consumed by one basic attack.  The
            # authored auto stream caps how many accepted casts can return
            # mana; cooldown and weave delay determine when each return lands.
            if spellblade_restore_count < state.num_auto_attacks:
                proc_time = (
                    max(cast_time, spellblade_cooldown_ready) + spellblade.weave_delay
                )
                spellblade_cooldown_ready = proc_time + spellblade.cooldown
                if proc_time <= state.fight_duration_seconds + _CAST_SCHEDULE_EPS:
                    heapq.heappush(
                        timeline,
                        (
                            proc_time,
                            0,
                            -1,
                            spellblade_restore_count,
                            "restore",
                            "",
                            mana_restore_per_proc,
                        ),
                    )
                    spellblade_restore_count += 1

    counts = {key: len(times) for key, times in accepted.items()}
    last_cast_time = max(
        (time for times in accepted.values() for time in times), default=0.0
    )
    return CastPlan(
        counts=counts,
        times={key: tuple(times) for key, times in accepted.items()},
        last_cast_time=last_cast_time,
        resource_spent=spent,
        resource_remaining=remaining,
        omitted_for_resource=tuple(omitted),
        resource_by_cast=resource_by_cast,
    )


def _tear_hit_identity(
    key: str, accepted_ordinal: int, info: Mapping[str, Any]
) -> str | None:
    """Return a proven hit identity for an accepted cast, or None.

    Tear's Manaflow wording triggers on affecting an enemy or ally with an
    ability.  In the fighter model a cast is a PROVEN eligible hit when its
    reviewed packet carries a champion-affecting marker: a damage part
    (``amount`` > 0 or an ``hp_scaled_damage`` closure), a crowd-control
    part, or an on-hit/empowered-auto/DoT application.  An accepted cast
    with none of those (a pure self-only receipt) fails closed with a
    ``missing_hit_identity`` denial instead of being treated as a hit.
    """
    parts = info.get("parts") or ()
    for part in parts:
        if getattr(part, "cc_kind", None) is not None:
            return f"{key}:{accepted_ordinal + 1}"
        try:
            amount = float(getattr(part, "amount", 0.0) or 0.0)
        except (TypeError, ValueError):
            amount = 0.0
        if amount > 0.0 or getattr(part, "hp_scaled_damage", None) is not None:
            return f"{key}:{accepted_ordinal + 1}"
    if any(
        info.get(marker)
        for marker in (
            "empowers_next_auto",
            "on_hit",
            "applies_dot_stack",
            "applies_item_on_hits",
        )
    ):
        return f"{key}:{accepted_ordinal + 1}"
    return None


def _tear_manaflow_for(
    state: FightState, owner: str
) -> resource_ledger.TearManaflow | None:
    """Build the holder's Tear Manaflow state, or None when not equipped.

    All numbers come from the typed ``item_effects`` accessors and the
    public option receipt; the atom hash is the verified catalog hash for
    Tear's stat.mana (data/atoms/items.json, evidence
    ``passive:Manaflow@kw:mana`` + ``stats.mana.flat``).
    """
    if not item_effects.has_item(state.items, "Tear of the Goddess"):
        return None
    options = state.item_options or {}
    authored = float(
        (options.get("Tear of the Goddess") or {}).get("manaflow_bonus_mana", 0.0)
        or 0.0
    )
    declaration = resource_ledger.TearDeclaration(
        charge_interval=float(
            item_effects.required_effect_value(
                "Tear of the Goddess", "manaflow_charge_interval"
            )
        ),
        max_charges=int(
            item_effects.required_effect_value(
                "Tear of the Goddess", "manaflow_max_charges"
            )
        ),
        bonus_mana_per_trigger=float(
            item_effects.required_effect_value(
                "Tear of the Goddess", "manaflow_bonus_mana_per_trigger"
            )
        ),
        bonus_mana_per_champion=float(
            item_effects.required_effect_value(
                "Tear of the Goddess", "manaflow_bonus_mana_per_champion"
            )
        ),
        bonus_mana_max=float(
            item_effects.required_effect_value(
                "Tear of the Goddess", "manaflow_bonus_mana_max"
            )
        ),
        source_url=str(
            item_effects.ITEM_INPUT_OPTIONS["Tear of the Goddess"]["source_url"]
        ),
        source_revision_id=int(
            item_effects.ITEM_INPUT_OPTIONS["Tear of the Goddess"]["source_revision_id"]
        ),
        atom=("stat.mana", "f8e104e5f65ff397"),
    )
    return resource_ledger.TearManaflow(
        declaration, owner=owner, authored_bonus_mana=authored
    )


def _enlighten_decl_for(
    state: FightState,
) -> resource_ledger.EnlightenDeclaration | None:
    """Return Lost Chapter's sourced Enlighten declaration, or None.

    The 20%-over-3-seconds restore is a typed rule declaration backed by
    the wiki branch and the client binary (ManaRestorePercent=0.2,
    RestorationDuration=3.0 in data/bin/items.bin.json 16.15.8024387); the
    atom hash is Lost Chapter's verified stat.mana catalog hash.
    """
    if not item_effects.has_item(state.items, "Lost Chapter"):
        return None
    return resource_ledger.EnlightenDeclaration(
        restore_percent=float(
            item_effects.required_effect_value(
                "Lost Chapter", "enlighten_restore_percent"
            )
        ),
        duration_seconds=float(
            item_effects.required_effect_value(
                "Lost Chapter", "enlighten_duration_seconds"
            )
        ),
        ticks=int(
            item_effects.required_effect_value("Lost Chapter", "enlighten_ticks")
        ),
        source_url=str(item_effects.ITEM_INPUT_OPTIONS["Lost Chapter"]["source_url"]),
        source_revision_id=int(
            item_effects.ITEM_INPUT_OPTIONS["Lost Chapter"]["source_revision_id"]
        ),
        atom=("stat.mana", "05327ad078be2bde"),
    )


def _planned_burst_seconds(state: FightState, plan: CastPlan) -> float:
    """The fight's total planned burst-time budget (all arming casts)."""
    total = 0.0
    for key in state.cast_order:
        empower = (state.ability_damages.get(key) or {}).get("empowers_next_auto")
        burst_as = _empower_burst_attack_speed(empower) if empower else 0.0
        if burst_as <= 0.0:
            continue
        hits = _empower_hits(empower)
        total += hits / burst_as * len(plan.times.get(key, ()))
    return total


def _return_denied_burst_budget(
    state: FightState,
    plan: CastPlan,
    auto_restore_rows: list[dict[str, Any]],
    denied_row: Mapping[str, Any],
    timeline: list[tuple[Any, ...]],
) -> None:
    """Return one denied burst cast's time to the ordinary restore budget.

    P1 Slice 12 (R1): the pre-admission schedule subtracted every planned
    burst cast's time from the ordinary count; a cast whose arming
    admission was DENIED never fires, so the fight's ordinary stream is
    uninterrupted and its restores must not shrink.  The first denied
    swing of a cast mints the returned ordinary rows at the current
    count's continuation (they ride their own scheduled times and heap
    order).
    """
    burst_seconds = float(denied_row.get("burst_seconds", 0.0))
    normal_rate = state.attack_speed * state.auto_attack_uptime
    if burst_seconds <= 0.0 or normal_rate <= 0.0:
        return
    planned_burst = _planned_burst_seconds(state, plan)
    ordinary_total = sum(1 for row in auto_restore_rows if row["kind"] == "ordinary")
    leftover = max(0.0, state.fight_duration_seconds - (planned_burst - burst_seconds))
    new_total = math.floor(normal_rate * leftover)
    delta = max(0, new_total - ordinary_total)
    if delta <= 0:
        return
    base_index = len(auto_restore_rows)
    for offset in range(delta):
        row_index = len(auto_restore_rows)
        auto_restore_rows.append(
            {
                "kind": "ordinary",
                "auto_index": base_index + offset + 1,
                "burst_seconds": 0.0,
            }
        )
        timeline.append(
            (
                ordinary_total / normal_rate + offset / normal_rate,
                0,
                -4,
                row_index,
                "auto_restore",
                "",
                0.0,
            )
        )


def _auto_restore_decl(
    state: FightState,
) -> tuple[str, dict[str, Any]] | None:
    """The single per-auto mana restore declaration, or None.

    A champion entry (Jayce's W passive) carries ``resource_restore_per_auto``
    as a typed dict ``{amount, source, atoms}``.  More than one declaring
    entry is not representable in this slice and raises (fail closed); the
    returned tuple names the declaring slot for the ledger detail rows.
    """
    declaring: list[tuple[str, dict[str, Any]]] = []
    for key, info in state.ability_damages.items():
        decl = info.get("resource_restore_per_auto")
        if decl is None:
            continue
        if not isinstance(decl, Mapping):
            raise ValueError(
                f"resource_restore_per_auto on slot {key!r} must be a mapping"
            )
        amount = decl.get("amount")
        source = decl.get("source")
        atoms = decl.get("atoms", ())
        if (
            isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or not math.isfinite(float(amount))
            or float(amount) <= 0.0
        ):
            raise ValueError(
                f"resource_restore_per_auto.amount on slot {key!r} must be a "
                f"positive finite number, got {amount!r}"
            )
        if not isinstance(source, str) or not source.strip():
            raise ValueError(
                f"resource_restore_per_auto.source on slot {key!r} must be a "
                "non-empty string"
            )
        if (
            not isinstance(atoms, (list, tuple))
            or not atoms
            or any(
                not isinstance(pair, (list, tuple))
                or len(pair) != 2
                or not all(isinstance(part, str) and part for part in pair)
                for pair in atoms
            )
        ):
            raise ValueError(
                f"resource_restore_per_auto.atoms on slot {key!r} must be a "
                "non-empty list of (atom_id, hash) string pairs"
            )
        declaring.append(
            (
                key,
                {
                    "amount": float(amount),
                    "source": source,
                    "atoms": tuple(tuple(pair) for pair in atoms),
                },
            )
        )
    if not declaring:
        return None
    if len(declaring) > 1:
        raise ValueError(
            "multiple resource_restore_per_auto declarations ("
            + ", ".join(repr(key) for key, _ in declaring)
            + "); the fight model supports one per-auto mana restore source"
        )
    return declaring[0]


def _auto_restore_schedule(
    state: FightState, plan: CastPlan
) -> tuple[tuple[float, ...], list[dict[str, Any]]]:
    """Auto-stream restore timestamps for the walk.

    Returns ``(ordinary_times, swing_events)``.  ``ordinary_times`` are the
    fight's ordinary basic attacks at the uniform ordinary rate (the
    post-burst count, replicating ``_apply_empowered_burst_autos``, which
    runs AFTER this walk); ``swing_events`` are per-swing restore
    descriptors for empowered bursts that fire at their own rate (Jayce's
    Hyper Charge) — each is gated on its arming cast being ACCEPTED when
    it pops (a denied cast never fires its swings, so it cannot mint mana
    — the Spellblade-restore precedent).

    The restore COUNT therefore mirrors the engine's post-admission auto
    stream in denial-free fights (normal autos outside the burst window
    plus the burst swings themselves); a denied burst cast's swings are
    skipped at pop time.  Hail of Blades / Lethal Tempo per-swing timing
    IS mirrored: ``_restore_stream_attack_timestamps`` resolves the same
    stack-sensitive schedule ``_prepare_hail_attack_schedule`` /
    ``_prepare_lethal_tempo_attack_schedule`` install later, directly from
    the keystone effect, because this walk runs before that installation.
    Lich Bane-adjusted schedules still resolve after the walk (Spellblade
    proc times are not known yet), so THEIR per-swing timing is not
    mirrored (the count is); documented in the champion module's
    ASSUMPTIONS.
    """
    times = _restore_stream_attack_timestamps(state)
    if not times:
        return (), ()
    burst_swings = 0
    burst_seconds = 0.0
    swing_events: list[dict[str, Any]] = []
    for key in state.cast_order:
        empower = (state.ability_damages.get(key) or {}).get("empowers_next_auto")
        burst_as = _empower_burst_attack_speed(empower) if empower else 0.0
        if burst_as <= 0.0:
            continue
        hits = _empower_hits(empower)
        for ordinal, cast_time in enumerate(plan.times.get(key, ())):
            burst_swings += hits
            burst_seconds += hits / burst_as
            for swing_index in range(hits):
                swing_events.append(
                    {
                        "time": cast_time + (swing_index + 1) / burst_as,
                        "arming_key": key,
                        "arming_ordinal": ordinal,
                        "swing_index": swing_index + 1,
                        "hits": hits,
                        # P1 Slice 12 (R1): this cast's burst-time
                        # contribution — a DENIED arming cast never fires
                        # its swings, so its budget is returned to the
                        # ordinary stream (the denied cast cannot shrink
                        # the per-auto restore budget).
                        "burst_seconds": hits / burst_as,
                    }
                )
    if burst_swings <= 0:
        return tuple(times), []
    normal_rate = state.attack_speed * state.auto_attack_uptime
    if normal_rate <= 0.0:
        return (), swing_events
    leftover = max(0.0, state.fight_duration_seconds - burst_seconds)
    ordinary = math.floor(normal_rate * leftover)
    return tuple(index / normal_rate for index in range(ordinary)), swing_events


def _kill_refund_decl(info: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate and normalize a champion entry's ``kill_refund`` declaration.

    P4-14: Darius W declares the typed refund rule behind the asserted
    kill (the w_kill_assertion option): when the empowered attack kills,
    refund the flat (40 = the sourced W cost).  Malformed declarations
    raise (authored code fails closed).
    """
    decl = info.get("kill_refund")
    if decl is None:
        return None
    if not isinstance(decl, Mapping):
        raise ValueError("kill_refund must be a mapping")
    flat = decl.get("flat")
    source = decl.get("source")
    atoms = decl.get("atoms", ())
    if (
        isinstance(flat, bool)
        or not isinstance(flat, (int, float))
        or not math.isfinite(float(flat))
        or float(flat) < 0.0
    ):
        raise ValueError(
            f"kill_refund.flat must be a finite non-negative number, got {flat!r}"
        )
    if not isinstance(source, str) or not source.strip():
        raise ValueError("kill_refund.source must be a non-empty string")
    if not isinstance(atoms, (list, tuple)) or any(
        not isinstance(pair, (list, tuple))
        or len(pair) != 2
        or not all(isinstance(part, str) and part for part in pair)
        for pair in atoms
    ):
        raise ValueError(
            "kill_refund.atoms must be a list of (atom_id, hash) string pairs"
        )
    return {
        "flat": float(flat),
        "source": source,
        "atoms": tuple(tuple(pair) for pair in atoms),
    }


def _kill_refund_decl_for_state(state: FightState) -> str | None:
    """The single slot declaring a kill refund, or None.

    P4-14: fail closed on more than one declaring slot — the resource
    walk supports one authored kill-refund rule per fight (mirrors the
    mark-refund and auto-restore guards).
    """
    declaring: list[str] = []
    for key, info in state.ability_damages.items():
        if _kill_refund_decl(info) is not None:
            declaring.append(key)
    if len(declaring) > 1:
        raise ValueError(
            f"multiple kill_refund declarations ({', '.join(sorted(declaring))})"
        )
    return declaring[0] if declaring else None


def _mark_refund_decl_for_state(state: FightState) -> str | None:
    """The single slot declaring a mark refund, or None.

    P1 Slice 13 (R2): fail closed on more than one declaring slot — the
    resource walk supports one authored mark-refund rule per fight
    (mirrors ``_auto_restore_decl``'s multi-declaration raise).
    """
    declaring: list[str] = []
    for key, info in state.ability_damages.items():
        if _mark_refund_decl(info) is not None:
            declaring.append(key)
    if len(declaring) > 1:
        raise ValueError(
            f"multiple mark_refund declarations ({', '.join(sorted(declaring))})"
        )
    return declaring[0] if declaring else None


def _mark_refund_decl(info: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate and normalize a champion entry's ``mark_refund`` declaration.

    Ezreal's W (Essence Flux) declares the typed refund rule: when the mark
    is detonated BY AN ABILITY, restore ``flat`` mana plus that ability's
    mana cost.  ``detonation`` (from the champion's public option) decides
    the detonation means; ``basic_attack`` disables the refund entirely.
    Malformed declarations raise (authored code fails closed).
    """
    decl = info.get("mark_refund")
    if decl is None:
        return None
    if not isinstance(decl, Mapping):
        raise ValueError("mark_refund must be a mapping")
    flat = decl.get("flat")
    window_seconds = decl.get("window_seconds")
    source = decl.get("source")
    detonation = decl.get("detonation")
    atoms = decl.get("atoms", ())
    if (
        isinstance(flat, bool)
        or not isinstance(flat, (int, float))
        or not math.isfinite(float(flat))
        or float(flat) < 0.0
    ):
        raise ValueError(
            f"mark_refund.flat must be a finite non-negative number, got {flat!r}"
        )
    if (
        isinstance(window_seconds, bool)
        or not isinstance(window_seconds, (int, float))
        or not math.isfinite(float(window_seconds))
        or float(window_seconds) <= 0.0
    ):
        raise ValueError(
            "mark_refund.window_seconds must be a finite positive number, "
            f"got {window_seconds!r}"
        )
    if not isinstance(source, str) or not source.strip():
        raise ValueError("mark_refund.source must be a non-empty string")
    if detonation not in {"ability", "basic_attack"}:
        raise ValueError(
            f"mark_refund.detonation must be 'ability' or 'basic_attack', got "
            f"{detonation!r}"
        )
    if not isinstance(atoms, (list, tuple)) or any(
        not isinstance(pair, (list, tuple))
        or len(pair) != 2
        or not all(isinstance(part, str) and part for part in pair)
        for pair in atoms
    ):
        raise ValueError(
            "mark_refund.atoms must be a list of (atom_id, hash) string pairs"
        )
    return {
        "flat": float(flat),
        "window_seconds": float(window_seconds),
        "source": source,
        "detonation": detonation,
        "atoms": tuple(tuple(pair) for pair in atoms),
    }


def _apply_mana_resource_limits(state: FightState, plan: CastPlan) -> CastPlan:
    """Admit MANA casts through the typed resource ledger (P3 slice 1).

    One account per fight owner owns every transition: base regeneration
    ticks, external restores (Catalyst's Eternity, Essence Reaver's
    Spellblade), ability restores, per-auto mana restores (Jayce's W
    passive), Essence Flux mark refunds (Ezreal's W), cast spends, Tear
    of the Goddess max-mana growth (proven accepted eligible hits only),
    and Lost Chapter's Enlighten level-up restore.  The admission
    semantics are identical to the legacy walk — same heap total order,
    same EPS boundaries, same denial list, same cast-timeline rows — and
    the ledger's receipts are the single source the public resource
    section and the Tear packets project from (no second receipt-only
    ledger).

    Champion resource mechanics ride the SAME account as cast admission,
    so restored/refunded mana can enable later casts; every restore lands
    on the restore tier (0) before a simultaneous cast's spend tier (1),
    and a denied cast never arms, detonates, or restores anything.
    """
    base_maximum = float(state.champion_stats.get("max_mana", 0.0))
    regen = float(state.champion_stats.get("resource_regen_per_second", 0.0))
    owner = str(getattr(state, "resource_ledger_owner", "") or "main")
    ledger = resource_ledger.ResourceLedger(
        owner,
        maximum=base_maximum,
        current=base_maximum,
        regen_per_second=regen,
    )
    tear = _tear_manaflow_for(state, owner)
    enlighten_decl = _enlighten_decl_for(state)

    events: list[tuple[float, int, int, str]] = []
    order = {key: index for index, key in enumerate(state.cast_order)}
    for key, times in plan.times.items():
        events.extend(
            (cast_time, order.get(key, len(order)), ordinal, key)
            for ordinal, cast_time in enumerate(times)
        )
    events.sort()

    accepted: dict[str, list[float]] = {key: [] for key in plan.times}
    accepted_ordinals: dict[str, set[int]] = {key: set() for key in plan.times}
    omitted: list[str] = []
    spent = 0.0
    previous_time = 0.0
    resource_by_cast: dict[tuple[str, int], dict[str, float]] = {}

    proc_restore = next(
        (
            info
            for info in state.ability_damages.values()
            if float(info.get("resource_restore_per_proc", 0.0)) > 0
            and int(info.get("proc_count", 0)) > 0
        ),
        None,
    )
    proc_restores_left = int(proc_restore.get("proc_count", 0)) if proc_restore else 0

    # Essence Reaver's Manaflow is restored by the accepted Spellblade attack,
    # not by the ability that arms it.  Keep those restores on the same
    # ordered resource timeline so a later cast can actually spend the mana
    # the preceding empowered attack returned.  Scheduling the restore only
    # after its arming cast is accepted also prevents an omitted cast from
    # minting phantom resources.
    spellblade = state.damage_effects.spellblade
    mana_restore_per_proc = 0.0
    spellblade_cooldown_ready = float("-inf")
    spellblade_restore_count = 0
    if (
        spellblade is not None
        and (
            spellblade.mana_restore_base_ad_ratio or spellblade.mana_restore_crit_ratio
        )
        and state.num_auto_attacks > 0
    ):
        stats = state.champion_stats
        mana_restore_per_proc = item_effects.essence_reaver_mana_restore_per_proc(
            base_attack_damage=stats.get("base_attack_damage", 0.0),
            critical_strike_chance=stats.get("critical_strike_chance", 0.0),
            item_name=spellblade.source.item_name,
        )

    # Heap entries are (time, phase, cast-order, ordinal, kind, key, amount).
    # Restore events sort before a cast at the same timestamp, matching the
    # attack landing before a simultaneous ability input is evaluated.
    timeline: list[tuple[float, int, int, int, str, str, float]] = [
        (cast_time, 1, order_index, ordinal, "cast", key, 0.0)
        for cast_time, order_index, ordinal, key in events
    ]
    # Catalyst's damage-taken restoration is an external, timestamped input
    # from the coupled participant ledger.  It is ordered before casts at the
    # same timestamp, matching the sourced hit -> resource update -> input
    # sequence.  Malformed rows are ignored here; the producer is required to
    # fail closed before constructing this typed tuple.
    for restore_index, (restore_time, restore_amount) in enumerate(
        state.resource_restore_events
    ):
        try:
            restore_time = float(restore_time)
            restore_amount = float(restore_amount)
        except (TypeError, ValueError):
            continue
        if (
            not math.isfinite(restore_time)
            or not math.isfinite(restore_amount)
            or restore_amount <= 0.0
            or restore_time < 0.0
            or restore_time > state.fight_duration_seconds + _CAST_SCHEDULE_EPS
        ):
            continue
        timeline.append(
            (
                restore_time,
                0,
                -1,
                restore_index,
                "restore",
                "Catalyst of Aeons",
                restore_amount,
            ),
        )
    # Lost Chapter's Enlighten: the explicit sourced level-up timing (the
    # smallest public option choice) authors ONE marker event.  On pop it
    # schedules the deterministic 20%-over-3s ticks against the account's
    # LIVE maximum; a missing choice creates no trigger.
    enlighten_level_up = 0.0
    if enlighten_decl is not None:
        enlighten_level_up = float(
            ((state.item_options or {}).get("Lost Chapter") or {}).get(
                "enlighten_level_up_seconds", 0.0
            )
            or 0.0
        )
    if enlighten_decl is not None and enlighten_level_up > 0.0:
        timeline.append(
            (enlighten_level_up, 0, -2, 0, "enlighten", "Lost Chapter", 0.0),
        )
    # (Enlighten tick events ride kind "enlighten_tick" so popping a tick
    # can never re-enter the level-up marker handler and re-schedule.)
    # Per-auto mana restore (Jayce's W passive): one ledger gain per
    # modeled basic attack.  Ordinary swings ride the fight's uniform
    # ordinary-rate schedule (post-burst count — see
    # ``_auto_restore_schedule``); empowered-burst swings (Hyper Charge's
    # 3 attacks) restore at their cast-relative times and are gated on
    # their arming cast being ACCEPTED, so a denied cast can never mint
    # mana.  All land on the restore tier, so a simultaneous cast input
    # sees them (engine restore-before-cast convention).
    auto_restore_decl = _auto_restore_decl(state)
    auto_restore_key = auto_restore_decl[0] if auto_restore_decl is not None else None
    auto_restore = auto_restore_decl[1] if auto_restore_decl is not None else None
    auto_restore_rows: list[dict[str, Any]] = []
    auto_restore_denials: list[dict[str, Any]] = []
    if auto_restore is not None:
        ordinary_times, swing_events = _auto_restore_schedule(state, plan)
        auto_restore_rows = [
            {"kind": "ordinary", "auto_index": index + 1}
            for index in range(len(ordinary_times))
        ]
        for swing in swing_events:
            auto_restore_rows.append(
                {
                    "kind": "swing",
                    "auto_index": len(auto_restore_rows) + 1,
                    "arming_key": swing["arming_key"],
                    "burst_seconds": swing.get("burst_seconds", 0.0),
                    "arming_ordinal": swing["arming_ordinal"],
                    "swing_index": swing["swing_index"],
                }
            )
        for row_index, restore_time in enumerate(ordinary_times):
            timeline.append((restore_time, 0, -4, row_index, "auto_restore", "", 0.0))
        for row_index in range(len(ordinary_times), len(auto_restore_rows)):
            swing = swing_events[row_index - len(ordinary_times)]
            if swing["time"] <= state.fight_duration_seconds + _CAST_SCHEDULE_EPS:
                timeline.append(
                    (swing["time"], 0, -4, row_index, "auto_swing_restore", "", 0.0)
                )
    heapq.heapify(timeline)

    sequence = 0
    tear_hits: list[dict[str, Any]] = []
    enlighten_public: dict[str, Any] | None = None
    # Essence Flux marks: one row per accepted W cast (arm order), FIFO
    # consumption by the next accepted ability cast (the model assumes
    # every cast hits, so the mark is always detonated by the next
    # ability — the 4s mark window and target-side spell shields are not
    # modeled; see the champion module's ASSUMPTIONS).
    pending_marks: list[dict[str, Any]] = []
    mark_refunds: list[dict[str, Any]] = []
    mark_decl_public: dict[str, Any] | None = None
    mark_refund_key = _mark_refund_decl_for_state(state)
    kill_refund_key = _kill_refund_decl_for_state(state)
    while timeline:
        (
            cast_time,
            _phase,
            _order_index,
            ordinal,
            kind,
            key,
            restore_amount,
        ) = heapq.heappop(timeline)
        # Base regeneration accrues on EVERY pop (restores included),
        # exactly like the legacy walk's per-event integration.
        regen_amount = max(0.0, cast_time - previous_time) * regen
        previous_time = cast_time
        if regen_amount > 0.0:
            ledger.apply(
                resource_ledger.ResourceEvent(
                    owner=owner,
                    operation=resource_ledger.OP_REGEN,
                    amount=regen_amount,
                    time=cast_time,
                    source="base regeneration",
                    sequence=sequence,
                    tier=resource_ledger.TIER_RESTORE,
                )
            )
            sequence += 1
        if kind == "restore":
            # The heap key names the restore source: Catalyst's Eternity
            # rows ride the item name (the legacy heap marker), Spellblade
            # procs ride the empty key.  No item-name dispatch happens here.
            source = (
                "Catalyst of Aeons (Eternity)" if key else "Essence Reaver (Manaflow)"
            )
            ledger.apply(
                resource_ledger.ResourceEvent(
                    owner=owner,
                    operation=resource_ledger.OP_GAIN,
                    amount=restore_amount,
                    time=cast_time,
                    source=source,
                    sequence=sequence,
                    tier=resource_ledger.TIER_RESTORE,
                )
            )
            sequence += 1
            continue
        if kind == "enlighten":
            enlighten_public = _schedule_enlighten(
                state,
                ledger,
                owner,
                enlighten_decl,
                enlighten_level_up,
                cast_time,
                timeline,
            )
            continue
        if kind == "enlighten_tick":
            # One deterministic Enlighten tick: 20% max mana over 3s in
            # equal parts, applied on the restore tier so a simultaneous
            # cast sees it (engine restore-before-cast convention).
            ledger.apply(
                resource_ledger.ResourceEvent(
                    owner=owner,
                    operation=resource_ledger.OP_GAIN,
                    amount=restore_amount,
                    time=cast_time,
                    source="Lost Chapter \u2014 Enlighten",
                    sequence=sequence,
                    tier=resource_ledger.TIER_RESTORE,
                    detail={
                        "tick": ordinal,
                        "ticks": (
                            enlighten_decl.ticks if enlighten_decl is not None else 0
                        ),
                        "level_up_time": enlighten_level_up,
                    },
                )
            )
            sequence += 1
            continue
        if kind in ("auto_restore", "auto_swing_restore"):
            # One modeled basic attack's mana restore (Jayce's W passive).
            # A burst swing whose arming Hyper Charge was denied never
            # lands, so its restore is a denial receipt, not a guess.
            row = auto_restore_rows[ordinal]
            if row["kind"] == "swing":
                arming = accepted_ordinals.get(row["arming_key"], set())
                if row["arming_ordinal"] not in arming:
                    auto_restore_denials.append(
                        {
                            "time": cast_time,
                            "source": auto_restore["source"],
                            "accepted": False,
                            "reason": "arming_cast_denied",
                            "arming_slot": row["arming_key"],
                            "arming_ordinal": row["arming_ordinal"] + 1,
                            "swing_index": row["swing_index"],
                        }
                    )
                    # P1 Slice 12 (R1): a DENIED arming cast never fires
                    # its swings, so the fight never saved that burst
                    # time — return it to the ordinary restore budget.
                    #  The first denied swing of the cast mints the
                    #  returned ordinary rows at the current count's
                    #  continuation (the engine's post-admission ordinary
                    #  stream is uninterrupted).
                    if row["swing_index"] == 1:
                        _return_denied_burst_budget(
                            state,
                            plan,
                            auto_restore_rows,
                            row,
                            timeline,
                        )
                    continue
            detail: dict[str, Any] = {
                "slot": auto_restore_key,
                "auto_index": row["auto_index"],
                "kind": row["kind"],
            }
            if row["kind"] == "swing":
                detail["arming_slot"] = row["arming_key"]
                detail["arming_ordinal"] = row["arming_ordinal"] + 1
                detail["swing_index"] = row["swing_index"]
            ledger.apply(
                resource_ledger.ResourceEvent(
                    owner=owner,
                    operation=resource_ledger.OP_GAIN,
                    amount=auto_restore["amount"],
                    time=cast_time,
                    source=auto_restore["source"],
                    sequence=sequence,
                    tier=resource_ledger.TIER_RESTORE,
                    atoms=auto_restore["atoms"],
                    detail=detail,
                )
            )
            sequence += 1
            continue
        info = state.ability_damages[key]
        parent = info.get("recast_of")
        if parent and ordinal not in accepted_ordinals.get(parent, set()):
            omitted.append(key)
            continue
        cost = float(info.get("resource_cost", 0.0))
        if (
            cost > 0.0
            and state.actualizer_active_until > cast_time + _CAST_SCHEDULE_EPS
            and item_effects.has_item(state.items, "Actualizer")
        ):
            cost *= item_effects.required_effect_value(
                "Actualizer", "mana_cost_multiplier"
            )
        spend = ledger.apply(
            resource_ledger.ResourceEvent(
                owner=owner,
                operation=resource_ledger.OP_SPEND,
                amount=cost,
                time=cast_time,
                source=f"ability {key} cast",
                sequence=sequence,
                tier=resource_ledger.TIER_CAST,
                detail={"slot": key, "ordinal": ordinal + 1},
            )
        )
        sequence += 1
        if not spend.accepted:
            # A denied cast cannot spend, so it can never trigger Tear or
            # consume a Manaflow charge (the hit is only driven below for
            # accepted casts).
            omitted.append(key)
            continue
        before = spend.current_before
        remaining = spend.current_after
        spent += cost

        restored = float(info.get("resource_restore", 0.0))
        if proc_restore is not None and proc_restores_left > 0:
            # A fixed-count proc entry represents those procs as having
            # happened in this scenario. For Ambessa, each accepted ability
            # cast mints one passive stack and the model weaves the selected
            # empowered attacks between casts, so their energy restoration
            # belongs on the same ordered resource timeline.
            restored += float(proc_restore["resource_restore_per_proc"])
            proc_restores_left -= 1
        if restored > 0.0:
            restored_receipt = ledger.apply(
                resource_ledger.ResourceEvent(
                    owner=owner,
                    operation=resource_ledger.OP_GAIN,
                    amount=restored,
                    time=cast_time,
                    source=f"ability {key} restore",
                    sequence=sequence,
                    tier=resource_ledger.TIER_RESTORE,
                )
            )
            sequence += 1
            remaining = restored_receipt.current_after
        accepted_ordinal = len(accepted[key])
        accepted[key].append(cast_time)
        accepted_ordinals[key].add(ordinal)
        if not state.score_only:
            # Per-cast resource rows serve only the public cast-timeline
            # receipt; nothing on the scoring path reads them.
            resource_by_cast[(key, accepted_ordinal)] = {
                "resource_before": before,
                "resource_restored": restored,
                "resource_after": remaining,
            }

        # Tear of the Goddess: only an ACCEPTED cast with a PROVEN
        # champion-affecting identity can consume a Manaflow charge.  The
        # granted bonus maximum mana enters the authoritative account; a
        # missing identity fails closed with a receipt and no charge is
        # spent.
        if tear is not None:
            identity = _tear_hit_identity(key, accepted_ordinal, info)
            hit_receipt, tear_event = tear.hit(
                time=cast_time,
                hit_identity=identity if identity is not None else "",
                sequence=sequence,
            )
            sequence += 1
            tear_hits.append(hit_receipt)
            if tear_event is not None:
                ledger.apply(tear_event)
                sequence += 1

        # Essence Flux mark refund (Ezreal's W): an accepted mark-arming
        # cast (W) both consumes the OLDEST pending mark (if any — the
        # mark is detonated by the next ability cast against the target;
        # every cast is assumed to hit) and arms a fresh mark.  The
        # refund is 60 + the detonating ability's ACTUAL paid cost (the
        # same ``cost`` this cast just spent, Actualizer discount
        # included).  It lands AFTER this cast's spend at the same
        # timestamp, so it can only enable LATER casts — never the
        # detonating one (the in-game sequence: cast, hit, refund).
        # Denied casts never arm or detonate (they never happen).
        mark_refund = _mark_refund_decl(info) if key == mark_refund_key else None
        kill_refund = _kill_refund_decl(info) if key == kill_refund_key else None
        if pending_marks:
            # ANY accepted ability cast against the target detonates the
            # OLDEST pending Essence Flux mark (every cast is assumed to
            # hit).  The refund is the mark's flat (60) plus THIS cast's
            # actual paid cost (the same ``cost`` just spent, Actualizer
            # discount included); it lands after this cast's spend, so it
            # can only enable LATER casts — never the detonating one
            # (in-game sequence: cast, hit, refund).  With the
            # basic_attack detonation option no mark is ever pending
            # (nothing is armed), so nothing consumes here.
            # P1 Slice 13 (R1): the mark's 4s window is enforced — a
            # detonation landing after the window is receipted
            # ``mark_expired`` and never refunds (the cached prose "marks
            # ... for 4 seconds", the binary DetonationTimeout 4.0, the
            # atom timing.active_duration b32849b968950b8e).
            if (
                cast_time - pending_marks[0]["time"]
                > pending_marks[0]["window_seconds"] + _CAST_SCHEDULE_EPS
            ):
                # The mark expired before this cast's hit — receipted, no
                # refund, and the cast still arms its own mark below.
                expired = pending_marks.pop(0)
                expired["accepted"] = False
                expired["reason"] = "mark_expired"
                expired["detonating_slot"] = None
                expired["detonating_ordinal"] = None
                expired["detonating_cost"] = 0.0
                expired["refund_amount"] = 0.0
                expired["refund_time"] = None
            else:
                consumed = pending_marks.pop(0)
                refund_amount = consumed["flat"] + cost
                consumed["accepted"] = True
                consumed["reason"] = "applied"
                consumed["detonating_slot"] = key
                consumed["detonating_ordinal"] = ordinal + 1
                consumed["detonating_cost"] = cost
                consumed["refund_amount"] = refund_amount
                consumed["refund_time"] = cast_time
                ledger.apply(
                    resource_ledger.ResourceEvent(
                        owner=owner,
                        operation=resource_ledger.OP_GAIN,
                        amount=refund_amount,
                        time=cast_time,
                        source=consumed["source"],
                        sequence=sequence,
                        tier=resource_ledger.TIER_RESTORE,
                        atoms=consumed["atoms"],
                        detail={
                            "mark_slot": consumed["mark_slot"],
                            "mark_ordinal": consumed["mark_ordinal"],
                            "detonating_slot": key,
                            "detonating_ordinal": ordinal + 1,
                            "detonating_cost": cost,
                            "flat": consumed["flat"],
                        },
                    )
                )
                sequence += 1
        if mark_refund is not None:
            # This accepted cast arms a fresh mark (Ezreal's W).  Denied
            # casts never arm (they never happen).  The public declaration
            # is captured once from the first arming cast.
            if mark_decl_public is None:
                mark_decl_public = {
                    "flat": mark_refund["flat"],
                    "window_seconds": mark_refund["window_seconds"],
                    "source": mark_refund["source"],
                    "atoms": [list(atom) for atom in mark_refund["atoms"]],
                    "detonation": mark_refund["detonation"],
                }
            mark_row: dict[str, Any] = {
                "time": cast_time,
                "source": mark_refund["source"],
                "flat": mark_refund["flat"],
                "window_seconds": mark_refund["window_seconds"],
                "atoms": [list(atom) for atom in mark_refund["atoms"]],
                "accepted": False,
                "reason": (
                    "basic_attack_detonation"
                    if mark_refund["detonation"] == "basic_attack"
                    else "armed"
                ),
                "mark_slot": key,
                "mark_ordinal": ordinal + 1,
                "detonating_slot": None,
                "detonating_ordinal": None,
                "detonating_cost": 0.0,
                "refund_amount": 0.0,
                "refund_time": None,
            }
            mark_refunds.append(mark_row)
            if mark_refund["detonation"] == "ability":
                pending_marks.append(mark_row)

        # P4-14: Darius W's asserted kill refund — an accepted W cast in
        # the kill declaration refunds the flat (the sourced 40) at the
        # cast's timestamp AFTER its spend (cast, hit, refund — the
        # Ezreal mark-refund ordering), so it can only enable later
        # casts.  Denied casts never refund (they never happen).
        if key == kill_refund_key and kill_refund is not None:
            ledger.apply(
                resource_ledger.ResourceEvent(
                    owner=owner,
                    operation=resource_ledger.OP_GAIN,
                    amount=kill_refund["flat"],
                    time=cast_time,
                    source=kill_refund["source"],
                    sequence=sequence,
                    tier=resource_ledger.TIER_RESTORE,
                    atoms=kill_refund["atoms"],
                    detail={"slot": key, "ordinal": ordinal + 1},
                )
            )
            sequence += 1

        if mana_restore_per_proc > 0.0 and spellblade is not None:
            # One Spellblade proc is consumed by one basic attack.  The
            # authored auto stream caps how many accepted casts can return
            # mana; cooldown and weave delay determine when each return lands.
            if spellblade_restore_count < state.num_auto_attacks:
                proc_time = (
                    max(cast_time, spellblade_cooldown_ready) + spellblade.weave_delay
                )
                spellblade_cooldown_ready = proc_time + spellblade.cooldown
                if proc_time <= state.fight_duration_seconds + _CAST_SCHEDULE_EPS:
                    heapq.heappush(
                        timeline,
                        (
                            proc_time,
                            0,
                            -1,
                            spellblade_restore_count,
                            "restore",
                            "",
                            mana_restore_per_proc,
                        ),
                    )
                    spellblade_restore_count += 1

    # Marks still pending when the fight ends were never detonated by an
    # ability in-window — receipted, never guessed (fail closed).  A mark
    # whose 4s window elapsed before the fight ended is ``mark_expired``
    # (P1 Slice 13), otherwise ``mark_undetonated``.
    for mark in pending_marks:
        if not mark["accepted"]:
            if (
                mark["time"] + mark.get("window_seconds", 0.0)
                < state.fight_duration_seconds + _CAST_SCHEDULE_EPS
            ):
                mark["reason"] = "mark_expired"
            else:
                mark["reason"] = "mark_undetonated"

    auto_restore_section: dict[str, Any] | None = None
    if auto_restore is not None:
        auto_restore_section = {
            "declaration": {
                "amount": auto_restore["amount"],
                "source": auto_restore["source"],
                "atoms": [list(atom) for atom in auto_restore["atoms"]],
            },
            "denials": auto_restore_denials,
        }
    mark_refunds_section: dict[str, Any] | None = None
    if mark_decl_public is not None:
        mark_refunds_section = {
            "declaration": mark_decl_public,
            "marks": mark_refunds,
        }

    counts = {key: len(times) for key, times in accepted.items()}
    last_cast_time = max(
        (time for times in accepted.values() for time in times), default=0.0
    )
    # Catalyst's Eternity heal is a projection of THIS account's accepted
    # spend receipts (P3 package 3A): one heal row per accepted spend at the
    # cast time, capped per cast and per one-second bucket.  It is computed
    # here, once, from the ledger receipts, so the receipt walk and the
    # score-only walk carry byte-identical heal rows (the legacy pipeline
    # recomputation read cast_timeline rows that score-only mode truncated
    # to the undiscounted resource_cost — the Actualizer divergence).
    catalyst_section: dict[str, Any] | None = None
    if item_effects.has_item(state.items, "Catalyst of Aeons"):
        declaration = item_effects.catalyst_eternity_declaration()
        heal_rows = resource_ledger.catalyst_eternity_heal_schedule(
            ledger.receipts(),
            heal_ratio=declaration["mana_spent_heal_ratio"],
            cap_per_cast=declaration["mana_spent_heal_cap_per_cast"],
            cap_per_second=declaration["mana_spent_heal_cap_per_second"],
        )
        catalyst_section = {
            "declaration": declaration,
            "heals": [row.public() for row in heal_rows],
        }
    return CastPlan(
        counts=counts,
        times={key: tuple(times) for key, times in accepted.items()},
        last_cast_time=last_cast_time,
        resource_spent=spent,
        resource_remaining=ledger.account.current,
        omitted_for_resource=tuple(omitted),
        resource_by_cast=resource_by_cast,
        resource_ledger=_resource_ledger_public(
            ledger,
            tear,
            tear_hits,
            enlighten_public,
            auto_restore_section,
            mark_refunds_section,
            catalyst=catalyst_section,
        ),
    )


def _schedule_enlighten(
    state: FightState,
    ledger: resource_ledger.ResourceLedger,
    owner: str,
    declaration: resource_ledger.EnlightenDeclaration | None,
    level_up_time: float,
    marker_time: float,
    timeline: list[tuple[float, int, int, int, str, str, float]],
) -> dict[str, Any]:
    """Pop the Enlighten level-up marker and schedule its restore ticks.

    The 20% base is fixed at the level-up moment against the account's LIVE
    maximum (Tear hits before the level-up enlarge the base; later events
    never retroactively resize it).  Ticks land at +1/+2/+3s on the restore
    tier, so a simultaneous cast sees them (the engine's restore-before-
    cast convention); resource changes affect only casts at or after each
    tick's timestamp.  A level-up authored outside the fight window is
    receipted, never guessed.
    """
    if declaration is None:
        return {
            "triggered": False,
            "reason": "no_declaration",
            "level_up_time": level_up_time,
            "ticks_total": 0,
            "ticks_within_window": 0,
        }
    if marker_time > state.fight_duration_seconds + _CAST_SCHEDULE_EPS:
        return {
            "declaration": declaration.public(),
            "triggered": False,
            "reason": "outside_fight_window",
            "level_up_time": level_up_time,
            "ticks_total": declaration.ticks,
            "ticks_within_window": 0,
        }
    ticks = resource_ledger.enlighten_schedule(
        level_up_time=level_up_time,
        maximum_mana=ledger.account.maximum,
        declaration=declaration,
        sequence=0,
        owner=owner,
    )
    within_window = 0
    for tick in ticks:
        if tick.time > state.fight_duration_seconds + _CAST_SCHEDULE_EPS:
            continue
        within_window += 1
        heapq.heappush(
            timeline,
            (
                tick.time,
                0,
                -3,
                int(tick.detail.get("tick", 0)),
                "enlighten_tick",
                "Lost Chapter",
                tick.amount,
            ),
        )
    return {
        "declaration": declaration.public(),
        "triggered": True,
        "reason": "level_up_restore_scheduled",
        "level_up_time": level_up_time,
        "maximum_mana_at_level_up": round(ledger.account.maximum, 6),
        "ticks_total": declaration.ticks,
        "ticks_within_window": within_window,
    }


def _resource_ledger_public(
    ledger: resource_ledger.ResourceLedger,
    tear: resource_ledger.TearManaflow | None,
    tear_hits: list[dict[str, Any]],
    enlighten_public: dict[str, Any] | None,
    auto_restore: dict[str, Any] | None = None,
    mark_refunds: dict[str, Any] | None = None,
    catalyst: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """JSON-safe public resource ledger section for a fight result.

    Additive P3 package-2/3A sub-sections (contract stays resource_ledger_v1):
    ``auto_restore`` (per-auto mana restore declaration + swing denials),
    ``mark_refunds`` (Essence Flux declaration + per-mark rows,
    applied/undetonated/basic-attack denials included), and ``catalyst``
    (Eternity declaration + the heal rows projected from the account's
    accepted spend receipts).
    """
    account = ledger.account
    section: dict[str, Any] = {
        "contract": "resource_ledger_v1",
        "owner": account.owner,
        "kind": account.kind,
        "opening_maximum": round(account.base_maximum, 6),
        "opening_current": round(account.base_maximum, 6),
        "closing_maximum": round(account.maximum, 6),
        "closing_current": round(account.current, 6),
        "base_maximum": round(account.base_maximum, 6),
        "bonus_maximum": round(account.bonus_maximum, 6),
        "receipts": [receipt.public() for receipt in ledger.receipts()],
    }
    if tear is not None:
        section["tear"] = {
            "declaration": tear.declaration.public(),
            "authored_bonus_mana": round(
                tear.bonus_total
                - sum(float(hit.get("bonus_delta", 0.0) or 0.0) for hit in tear_hits),
                6,
            ),
            "hits": tear_hits,
            "use_count": tear.use_count,
            "bonus_total": round(tear.bonus_total, 6),
            "stored_charges": tear.stored_charges,
        }
    if enlighten_public is not None:
        section["enlighten"] = enlighten_public
    if auto_restore is not None:
        section["auto_restore"] = auto_restore
    if mark_refunds is not None:
        section["mark_refunds"] = mark_refunds
    if catalyst is not None:
        section["catalyst"] = catalyst
    return section


@dataclass(frozen=True)
class StackApplication:
    """One stacking-DoT stack landing on the target."""

    time: float
    stacks_before: int  # stacks the target carried when this hit landed
    stacks_after: int  # after this application, capped at max_stacks
    buff_bonus_ad: float  # stack-triggered bonus AD already active


@dataclass(frozen=True)
class CastPricing:
    """What the fight timeline contributes to ONE cast's damage.

    ``bonus_attack_damage`` re-prices every part that declares a
    ``bonus_ad_ratio``; ``dot_stacks`` supplies the hit count of every
    part that declares ``dot_stack_scaled``. The all-zero default is
    what every fight without a stack timeline uses, so parts that
    declare neither are priced exactly as before.
    """

    bonus_attack_damage: float = 0.0
    dot_stacks: int = 0
    # P3 package 3V: the cast is a Ferocity-empowered one (Rengar) — the
    # engine prices the entry's ferocity_parts instead of parts.
    ferocity_empowered: bool = False


_NO_PRICING = CastPricing()


@dataclass(frozen=True)
class StackTimeline:
    """The fight's stacking-DoT applications and everything they gate.

    ONE home for "when does a stack land". The DoT integration
    (``_add_stacking_dot_damage``), the stack-triggered buff windows,
    per-cast stack reads (Darius R) and per-auto buff pricing all read
    THIS object, so they can never drift apart.

    ``applications`` is sorted by time; within one instant (one-rotation
    mode puts every cast at t=0) it keeps cast order, then autos.
    ``buff_windows`` are merged, sorted, half-open ``[start, end)``
    intervals of an active stack-triggered steroid.

    ``starting_stacks`` is the target's stack count at t=0 — stacks put
    on before the modeled fight. Because they were applied by pre-fight
    hits, they carry every consequence a mid-fight application would:
    they open the steroid window at t=0 when they meet
    ``trigger_stacks``, they scale ``dot_stack_scaled`` parts, and they
    tick. Seeding here is what keeps those three answers from
    disagreeing (a target cannot hold max stacks while the champion
    lacks the buff that reaching max stacks grants).
    """

    dot_key: str
    spec: dict[str, Any]
    applications: tuple[StackApplication, ...]
    buff_windows: tuple[tuple[float, float], ...]
    buff_bonus_ad: float
    buff_name: str
    starting_stacks: int
    _by_cast: dict[tuple[str, int], int]
    _by_auto: dict[int, int]

    def _at_time(self, time: float) -> StackApplication | None:
        """The last application strictly before *time*, if any."""
        found = None
        for application in self.applications:
            if application.time >= time:
                break
            found = application
        return found

    def cast_pricing(self, ability_key: str, ordinal: int, time: float) -> CastPricing:
        """Timeline-derived pricing for one cast of *ability_key*.

        A cast that applies a stack is priced from its OWN slot in the
        timeline: it reads the stacks it found on arrival, and the cast
        that lands the trigger stack is not buffed by the window its own
        damage opens. Any other cast is priced from the fight clock.
        """
        index = self._by_cast.get((ability_key, ordinal))
        if index is not None:
            application = self.applications[index]
            return CastPricing(application.buff_bonus_ad, application.stacks_before)
        return CastPricing(self.bonus_ad_at(time), self.stacks_at(time))

    def auto_bonus_ad(self, auto_index: int, time: float) -> float:
        """Stack-triggered bonus AD active on auto attack *auto_index*."""
        index = self._by_auto.get(auto_index)
        if index is not None:
            return self.applications[index].buff_bonus_ad
        return self.bonus_ad_at(time)

    def bonus_ad_at(self, time: float) -> float:
        """Stack-triggered bonus AD active at *time*."""
        for start, end in self.buff_windows:
            if start <= time < end:
                return self.buff_bonus_ad
        return 0.0

    def stacks_at(self, time: float) -> int:
        """Stacks on the target at *time*, before anything landing there."""
        duration = float(self.spec["duration"])
        previous = self._at_time(time)
        if previous is None:
            # Pre-fight stacks, applied at t=0 and expiring like any
            # other application.
            return self.starting_stacks if time < duration else 0
        if time - previous.time >= duration:
            return 0
        return previous.stacks_after


def _find_stacking_dot(state: FightState) -> tuple[str, dict[str, Any]] | None:
    """The entry declaring the fight's stacking DoT — one per champion."""
    return next(
        (
            (key, info["stacking_dot"])
            for key, info in state.ability_damages.items()
            if "stacking_dot" in info
        ),
        None,
    )


def _stack_application_times(
    state: FightState,
    plan: CastPlan,
    spec: dict[str, Any],
) -> list[tuple[float, tuple[str, int] | None, int | None]]:
    """Every stack application as ``(time, cast slot, auto index)``.

    Ability applications land at their cast times (all t=0 in
    one-rotation mode); an ``empowers_next_auto`` applier's swing IS one
    of the fight's autos, so its stack rides the auto timeline whenever
    one exists. Sorting is stable, so casts keep cast order within one
    instant and autos follow them.
    """
    applications: list[tuple[float, tuple[str, int] | None, int | None]] = []
    for ability_key in state.cast_order:
        info = state.ability_damages.get(ability_key)
        if info is None or not info.get("applies_dot_stack"):
            continue
        if info.get("empowers_next_auto") and state.num_auto_attacks > 0:
            continue
        for ordinal, cast_time in enumerate(plan.times[ability_key]):
            applications.append((cast_time, (ability_key, ordinal), None))

    if spec.get("applied_by_autos", True) and state.num_auto_attacks > 0:
        applications.extend(
            (time, None, index)
            for index, time in enumerate(_auto_attack_timestamps(state))
        )

    applications.sort(key=lambda application: application[0])
    return applications


def _build_stack_timeline(state: FightState, plan: CastPlan) -> StackTimeline | None:
    """Walk the fight's stack applications once, deriving everything.

    Stack rules (shared by every consumer): each application adds a
    stack up to ``max_stacks`` and refreshes the shared window; a gap of
    ``duration`` or more expires the chain. An application that lands ON
    ``trigger_stacks`` opens or refreshes the stack-triggered steroid
    (Darius' Noxian Might) — including a reapplication at max stacks, so
    holding the target at max holds the buff. Returns None when the
    champion declares no stacking DoT.

    A ``starting_stacks`` spec seeds the target's pre-fight stacks. They
    were put on by pre-fight hits, so if they already meet
    ``trigger_stacks`` the fight opens with the steroid running — the
    t=0 casts are buffed by a window they did not open themselves.
    """
    found = _find_stacking_dot(state)
    buff = next(
        (
            info["stack_triggered_buff"]
            for info in state.ability_damages.values()
            if "stack_triggered_buff" in info
        ),
        None,
    )
    if found is None:
        if buff is not None:
            # The buff is triggered BY stacks; with no stacking DoT to
            # count them it could never fire, and would silently grant
            # nothing rather than failing loudly.
            raise ValueError(
                f"stack_triggered_buff {buff.get('name', '?')!r} declared "
                "without a stacking_dot to trigger it — the buff has no "
                "stack source"
            )
        return None
    dot_key, spec = found

    duration = float(spec["duration"])
    max_stacks = int(spec["max_stacks"])
    trigger_stacks = int(buff["trigger_stacks"]) if buff else 0
    buff_duration = float(buff["duration"]) if buff else 0.0
    buff_bonus_ad = float(buff["bonus_attack_damage"]) if buff else 0.0

    starting_stacks = min(int(spec.get("starting_stacks", 0)), max_stacks)

    applications: list[StackApplication] = []
    by_cast: dict[tuple[str, int], int] = {}
    by_auto: dict[int, int] = {}
    windows: list[list[float]] = []
    stacks = starting_stacks
    previous_time = 0.0
    buff_until = 0.0  # never active before the first trigger (times >= 0)
    if buff is not None and starting_stacks > 0 and starting_stacks >= trigger_stacks:
        # Pre-fight hits reached the trigger, so the window is already
        # running when the fight opens.
        buff_until = buff_duration
        windows.append([0.0, buff_until])

    for time, cast_slot, auto_index in _stack_application_times(state, plan, spec):
        if stacks > 0 and time - previous_time >= duration:
            stacks = 0
        stacks_before = stacks
        # The application that opens a window is not itself buffed: the
        # steroid is triggered BY the damage this hit deals.
        active_ad = buff_bonus_ad if time < buff_until else 0.0
        stacks = min(stacks + 1, max_stacks)
        if cast_slot is not None:
            by_cast[cast_slot] = len(applications)
        if auto_index is not None:
            by_auto[auto_index] = len(applications)
        applications.append(StackApplication(time, stacks_before, stacks, active_ad))
        if buff is not None and stacks >= trigger_stacks:
            buff_until = time + buff_duration
            if windows and time <= windows[-1][1]:
                windows[-1][1] = buff_until
            else:
                windows.append([time, buff_until])
        previous_time = time

    return StackTimeline(
        dot_key=dot_key,
        spec=spec,
        applications=tuple(applications),
        buff_windows=tuple((start, end) for start, end in windows),
        buff_bonus_ad=buff_bonus_ad,
        buff_name=str(buff["name"]) if buff else "",
        starting_stacks=starting_stacks,
        _by_cast=by_cast,
        _by_auto=by_auto,
    )


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

    # Timed mode: all abilities share one cast timeline (cast times lock
    # out other casts). One-rotation and autos-only modes never recast,
    # so they skip scheduling entirely.
    timed_mode = not (state.one_rotation or state.auto_attacks_only)
    schedule = (
        _schedule_shared_casts(state, result, basic_ability_haste) if timed_mode else {}
    )

    # Resolve WHEN everything casts before pricing anything: the stack
    # timeline (Case 4/5) must exist before the first cast is priced, and
    # both it and the DoT integration afterwards read this one plan.
    plan = _apply_resource_limits(state, _resolve_cast_plan(state, schedule))
    result.last_cast_time = plan.last_cast_time
    result.resource_spent = plan.resource_spent
    result.resource_remaining = plan.resource_remaining
    result.resource_ledger = plan.resource_ledger
    cast_event_order = {slot: index for index, slot in enumerate(state.cast_order)}
    result.cast_events = sorted(
        (
            {
                "time": round(cast_time, 3),
                "slot": ability_key,
                "name": ability_damages[ability_key].get("name", ability_key),
                "ordinal": ordinal + 1,
                "cast_id": f"{ability_key}:{ordinal + 1}",
                "target_id": f"target:{state.roster_target_index}",
                "resource_cost": float(
                    ability_damages[ability_key].get("resource_cost", 0.0)
                ),
                **plan.resource_by_cast.get((ability_key, ordinal), {}),
            }
            for ability_key, times in plan.times.items()
            for ordinal, cast_time in enumerate(times)
        ),
        key=lambda event: (
            event["time"],
            cast_event_order.get(event["slot"], len(cast_event_order)),
            event["ordinal"],
        ),
    )
    if plan.omitted_for_resource:
        omitted_counts = {
            key: plan.omitted_for_resource.count(key)
            for key in dict.fromkeys(plan.omitted_for_resource)
        }
        detail = ", ".join(f"{key} x{count}" for key, count in omitted_counts.items())
        state.notes.append(
            f"Started at full resource; insufficient resource omitted {detail}."
        )
    # An empowered burst that sets its own attack speed re-times the auto
    # stream — do it before anything prices an auto or counts an on-hit.
    _apply_empowered_burst_autos(state, plan)
    _prepare_hail_attack_schedule(state)
    _prepare_lethal_tempo_attack_schedule(state)
    state.stack_timeline = _build_stack_timeline(state, plan)
    timeline = state.stack_timeline
    state.ferocity_timeline = _build_ferocity_timeline(state, plan)
    ferocity_timeline = state.ferocity_timeline
    if ferocity_timeline is not None:
        # P3 package 3V: the Ferocity counter rides the public
        # resource-ledger section (an additive sub-section like
        # auto_restore/mark_refunds — the mana-only account is untouched).
        ledger_section = result.resource_ledger
        if not isinstance(ledger_section, dict):
            ledger_section = {}
            result.resource_ledger = ledger_section
        rule = ferocity_timeline.stack.rule
        stack = ferocity_timeline.stack
        result.resource_ledger = {
            "contract": "resource_ledger_v1",
            "owner": "main",
            "kind": "ferocity",
            "opening_maximum": rule.max_stacks,
            "opening_current": ferocity_timeline.starting_stacks,
            "closing_maximum": rule.max_stacks,
            "closing_current": stack.stacks,
            "base_maximum": rule.max_stacks,
            "bonus_maximum": 0,
            "receipts": ferocity_timeline.receipts,
            "declaration": rule.public_receipt(),
            "state_transitions": stack.public_receipt()["transitions"],
        }

    for ability_key in state.cast_order:
        if ability_key not in ability_damages:
            continue
        ability_info = ability_damages[ability_key]

        num_casts = plan.counts[ability_key]
        # Per-cast timeline pricing: a mid-fight bonus-AD steroid active
        # at that cast, and the DoT stacks on the target when it lands.
        pricing = (
            tuple(
                timeline.cast_pricing(ability_key, ordinal, cast_time)
                for ordinal, cast_time in enumerate(plan.times[ability_key])
            )
            if timeline is not None
            else None
        )
        # P3 package 3V: Rengar's live Ferocity walk marks the casts that
        # consume the 4-stack cap (empowered); the entry's ferocity_parts
        # replace the base parts for those casts.
        ferocity_timeline = state.ferocity_timeline
        ferocity_empowered = (
            tuple(
                ferocity_timeline.cast_empowered(ability_key, ordinal)
                for ordinal in range(num_casts)
            )
            if ferocity_timeline is not None
            else None
        )
        ferocity_parts = ability_info.get("ferocity_parts")

        # Malignance MR reduction activates when R is cast
        if ability_key == "R":
            ult_cast = True

        result.total_ability_casts += num_casts
        # Damaging hit instances: each damaging part is one hit per cast
        # (Aurora Q = first cast + recast = 2). Feeds on-hit stack
        # counters that count ability hits (``count_ability_hits``).
        result.total_ability_hits += num_casts * sum(
            part.count
            for part in ability_info["parts"]
            if part.amount > 0 or part.hp_scaled_damage is not None
        )
        damage_type = ability_info["damage_type"]

        # Bloodletter's Curse: magic damage abilities apply a Vile Decay
        # stack. The ability's own damage benefits from its stack.
        ability_stacks = 0
        if resists.mr_reduction_effect and damage_type in ("magic", "mixed"):
            vile_decay_stacks = min(
                vile_decay_stacks + 1,
                resists.mr_reduction_effect.max_stacks,
            )
            ability_stacks = vile_decay_stacks
        ability_mr = _ability_mr(resists, ult_cast, ability_stacks)

        # All damage arithmetic is typed DamageParts — champion-specific
        # scaling lives in the champion module's closures, never here.
        parts = ability_info["parts"]
        # An empowered-auto cast with no auto stream to ride (one-rotation
        # mode, or a timed fight at zero auto uptime) still forces its
        # basic attack(s) — carry the consumed swings on the ability's
        # own row, matching the in-game "attack + bonus" hit (Blitzcrank
        # E, Vayne Q; Cho'Gath E forces ``hits`` = 3 swings). Timed
        # fights WITH autos never get here: casts are capped by the auto
        # count above, and the auto stream itself carries the swings. A
        # dict-valued flag may carry module-authored ``swing_parts``
        # replacing the default expected-crit swing (Camille Q: the
        # whole attack cannot crit and may convert to true damage).
        empower = ability_info.get("empowers_next_auto")
        forced_swings = 0
        if empower and num_casts > 0 and state.num_auto_attacks == 0:
            hits = _empower_hits(empower)
            forced_swings = num_casts * hits
            result.forced_basic_attacks += forced_swings
            result.forced_swing_casts += num_casts
            authored_timing = _empower_authored_timing(empower)
            if authored_timing is not None:
                first_delay, attack_interval = authored_timing
                parts = tuple(
                    (
                        replace(
                            part,
                            time_offset=first_delay,
                            hit_interval=(attack_interval if part.count > 1 else None),
                        )
                        if part.count == hits and part.time_offset is None
                        else part
                    )
                    for part in parts
                )
            if isinstance(empower, dict) and "swing_parts" in empower:
                swing_parts = tuple(empower["swing_parts"])
                if authored_timing is not None:
                    first_delay, attack_interval = authored_timing
                    swing_parts = tuple(
                        (
                            replace(
                                part,
                                time_offset=first_delay,
                                hit_interval=(
                                    attack_interval if part.count > 1 else None
                                ),
                            )
                            if part.count == hits and part.time_offset is None
                            else part
                        )
                        for part in swing_parts
                    )
                parts = parts + swing_parts
            else:
                first_delay = None
                attack_interval = None
                if authored_timing is not None:
                    first_delay, attack_interval = authored_timing
                swing = DamagePart(
                    "physical",
                    state.champion_stats.get("attack_damage", 0.0),
                    count=hits,
                    crit_effectiveness=1.0,
                    basic_damage=True,
                    # A basic attack is 100% total AD, so a mid-fight
                    # bonus-AD steroid raises the forced swing 1:1.
                    bonus_ad_ratio=1.0,
                    time_offset=first_delay,
                    hit_interval=(attack_interval if hits > 1 else None),
                )
                parts = parts + (swing,)
        # A ramped shred (Corki E) stacks up across this ability's own
        # hits; an unramped one lands in full after it (below).
        shred_ramp = _make_shred_ramp(resists, ability_info, ult_cast, ability_stacks)
        cast_times = plan.times.get(ability_key, ())
        control_specs = tuple(ability_info.get("control_events", ()))
        if control_specs:
            serialized_controls: list[dict[str, Any]] = []
            for control in control_specs:
                if not isinstance(control, ControlEvent):
                    raise TypeError(
                        f"{ability_key} control_events must contain ControlEvent"
                    )
                serialized_controls.append(
                    {
                        "kind": "crowd_control",
                        "cc_kind": control.kind,
                        "cc_duration": float(control.duration),
                        "time_offset": control.time_offset,
                        "count": int(control.count),
                        "hit_interval": control.hit_interval,
                        "skillshot": bool(
                            control.skillshot or ability_info.get("skillshot")
                        ),
                    }
                )
            for cast_index, cast_time in enumerate(cast_times):
                cast_id = f"{ability_key}:{cast_index + 1}"
                target_id = f"target:{state.roster_target_index}"
                for control in control_specs:
                    offset = (
                        float(control.time_offset)
                        if control.time_offset is not None
                        else 0.0
                    )
                    interval = float(control.hit_interval or 0.0)
                    for control_index in range(control.count):
                        result.control_events.append(
                            {
                                "time": float(cast_time)
                                + offset
                                + interval * control_index,
                                "kind": "crowd_control",
                                "cc_kind": control.kind,
                                "cc_duration": float(control.duration),
                                "damage": 0.0,
                                "damage_type": "",
                                "source_key": ability_key,
                                "source": ability_info.get("name", ability_key),
                                "is_ability": True,
                                "cast_id": cast_id,
                                "application_id": cast_id,
                                "target_id": target_id,
                                **(
                                    {"cc_reviewed": True}
                                    if control.kind.lower().strip()
                                    in (ACTION_BLOCKING_CC_KINDS | {"slow"})
                                    else {}
                                ),
                                "skillshot": bool(
                                    control.skillshot or ability_info.get("skillshot")
                                ),
                                "event_precision": (
                                    "exact"
                                    if control.time_offset is not None
                                    else "cast_boundary"
                                ),
                                **(
                                    {
                                        "control_source_atoms": [
                                            dict(atom)
                                            for atom in ability_info.get(
                                                "control_source_atoms", []
                                            )
                                        ]
                                    }
                                    if ability_info.get("control_source_atoms")
                                    else {}
                                ),
                                "sequence": 1_000_000 + len(result.control_events),
                            }
                        )
        (
            ability_total,
            first_part_damage,
            ability_by_type,
            ability_events,
        ) = _evaluate_cast_parts(
            state,
            parts,
            num_casts,
            ability_mr,
            mitigated_damage_dealt,
            on_hit=shred_ramp.stage if shred_ramp is not None else None,
            pricing=pricing,
            cast_times=cast_times,
            single_hit_event_certified=(
                ability_info.get("event_order_certified") == "single_hit"
            ),
            damage_over_time=bool(
                ability_info.get("dot_duration")
                or ability_info.get("dot_tick_interval")
            ),
            ferocity_empowered=ferocity_empowered,
            empowered_parts=ferocity_parts,
            cc_reviewed=bool(ability_info.get("cc_reviewed")),
        )

        # Apply ability-specific damage amplifiers (e.g., Actualizer).  When
        # the active has an authored expiry, exact hit receipts are split at
        # that boundary instead of treating the whole rotation as active.
        ability_amp = state.ability_amp
        active_event_damage = 0.0
        event_base_damage = sum(
            float(event.get("damage", 0.0) or 0.0) for event in ability_events
        )
        if state.actualizer_active_until > 0.0:
            if ability_events:
                active_event_damage = sum(
                    float(event.get("damage", 0.0) or 0.0)
                    for event in ability_events
                    if float(event.get("time", 0.0) or 0.0)
                    < state.actualizer_active_until - _CAST_SCHEDULE_EPS
                )
                if event_base_damage > 0.0:
                    ability_total += active_event_damage * (ability_amp - 1.0)
            elif cast_times:
                active_casts = sum(
                    1
                    for time in cast_times[:num_casts]
                    if float(time) < state.actualizer_active_until - _CAST_SCHEDULE_EPS
                )
                ability_total *= 1.0 + (ability_amp - 1.0) * active_casts / max(
                    1, num_casts
                )
            else:
                # No authored timestamps means the direct engine path cannot
                # split the active window; preserve its explicit active
                # assumption rather than silently dropping the amp.
                ability_total *= ability_amp
        else:
            ability_total *= ability_amp

        # Muramana procs once per DAMAGING ability cast: Shock is gated on
        # "Dealing ability damage to champions" (P3 package 3E), so a cast
        # that deals zero damage (spell-shield slots, rank-0 leftovers,
        # stat-buff ultimates) never procs.  Multi-instance abilities (e.g.
        # Ahri R with 3 dashes) proc once per instance.
        cast_instances = ability_info.get("cast_instances", 1)
        if num_casts > 0 and ability_total > 0.0:
            result.total_muramana_procs += cast_instances * num_casts

        # Track the first ability hit for Horizon Focus (trigger, not amped).
        # For mixed-type abilities (e.g. Ahri Q: magic outgoing + true return),
        # only the first hit (magic portion) triggers — the return is amped.
        if first_ability_key is None and num_casts > 0 and ability_total > 0.0:
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
            "total_raw": sum(
                float(part.amount) * max(1, int(part.count)) for part in parts
            ),
        }
        if bool(ability_info.get("skillshot")) or any(part.skillshot for part in parts):
            breakdown[ability_key]["skillshot"] = True
        if bool(ability_info.get("area_damage")):
            breakdown[ability_key]["area_damage"] = True
        # Module-authored self-shield payloads (E8c) ride the ability's
        # damage events: ``_ordered_damage_events`` copies each aligned
        # entry onto the matching damage-event row as ``self_shield`` so the
        # participant ledger can grant a timed self-shield at that event's
        # timestamp.  The Eclipse item authors the identical breakdown shape
        # (``self_shield_events``), so the ledger path is shared, not new.
        if ability_info.get("self_shield_events") is not None:
            breakdown[ability_key]["self_shield_events"] = ability_info[
                "self_shield_events"
            ]
        timing_is_authored = bool(parts) and all(
            part.time_offset is not None
            and (part.count <= 1 or part.hit_interval is not None)
            for part in parts
        )
        has_dynamic_part = any(part.hp_scaled_damage is not None for part in parts)
        single_hit_certified = ability_info.get("event_order_certified") == "single_hit"
        if (
            timing_is_authored
            or has_dynamic_part
            or (single_hit_certified and ability_events)
        ) and ability_events:
            breakdown[ability_key]["damage_events"] = [
                {
                    **event,
                    "damage": event["damage"]
                    * (
                        ability_amp
                        if state.actualizer_active_until <= 0.0
                        or float(event.get("time", 0.0) or 0.0)
                        < state.actualizer_active_until - _CAST_SCHEDULE_EPS
                        else 1.0
                    ),
                }
                for event in ability_events
            ]
            breakdown[ability_key]["event_phase"] = "ability"
        # With no auto row to report them, the basic attacks this cast
        # forced — and the crit riding them — are otherwise invisible:
        # the UI's "N casts" text says nothing about the swings folded
        # into this row. Crit here is priced as an EXPECTED value, so
        # state the rate rather than inventing an integer crit count.
        if forced_swings > 0:
            # Preserve the fact that this ability row contains a real basic
            # attack when no authored hit timing exists. Reactive defender
            # effects must still recognize the forced swing.
            breakdown[ability_key]["basic_attack"] = True
            detail = f"{num_casts} cast{'' if num_casts == 1 else 's'}"
            detail += f", {forced_swings} attack{'' if forced_swings == 1 else 's'}"
            if state.crit_chance > 0:
                detail += f" @ {round(state.crit_chance * 100)}% crit"
            breakdown[ability_key]["detail"] = detail
        active_damage_types = {
            dtype for dtype, amount in ability_by_type.items() if amount > 0
        }
        if damage_type == "mixed" or len(active_damage_types) > 1:
            # Exact composition for the physical/magic/true split. This also
            # covers an empowered magic on-hit whose forced basic-attack swing
            # adds a physical part to the same visible row (Shen Q).
            breakdown[ability_key]["damage_by_type"] = {
                dtype: amount * state.ability_amp
                for dtype, amount in ability_by_type.items()
                if amount > 0
            }
        # Champion-minted display text (e.g. Aurelion Sol E's execute
        # threshold) rides the entry onto its breakdown row untouched.
        if "detail" in ability_info:
            breakdown[ability_key]["detail"] = ability_info["detail"]
        if control_specs:
            breakdown[ability_key]["control_events"] = serialized_controls
        state.total_damage += ability_total
        mitigated_damage_dealt += ability_total

        # Ability-carried item applications (Bel'Veth Q/E): each hit
        # applies the build's per-hit on-hit item effects at the slot's
        # declared effectiveness. The per-hit damage comes from the same
        # compiled specs the auto stream reads; each application decays
        # the modeled target HP so BoRK's current-health formula ramps
        # down through the combo. The slot's effectiveness is its own
        # modifier — a champion ``auto_attack_override`` effectiveness
        # applies to autos only. The spec's ``triggers`` declare what
        # the application carries: "on_hit" (per-hit item damage +
        # on-hit counters) and/or "on_attack" (counts as an attack for
        # on-attack cadences like Guinsoo's phantom hit). Counter procs
        # themselves fire in _add_single_proc_on_hits and
        # _layer_on_hit_effects from the records kept here.
        on_hit_spec = ability_info.get("applies_item_on_hits")
        if on_hit_spec and num_casts > 0:
            applications = num_casts * int(on_hit_spec["hits"])
            effectiveness = float(on_hit_spec["effectiveness"])
            triggers = frozenset(on_hit_spec.get("triggers", ("on_hit",)))
            is_on_hit = "on_hit" in triggers
            applied_total = 0.0
            applied_by_type: dict[str, float] = {}
            application_times = [
                float(event.get("time", 0.0))
                for event in ability_events
                if isinstance(event, dict)
            ]
            if len(application_times) < applications:
                # A carrier may have several ordered hits inside a cast while
                # the ability itself has no sourced sub-hit delay.  Preserve
                # the cast's authored boundary for each application instead
                # of leaving the shared on-hit counter untimestamped.  The
                # order remains the module's part order; no fractional
                # average or target-health guess is introduced.
                cast_times = [float(time) for time in plan.times.get(ability_key, ())]
                hits_per_cast = max(1, int(on_hit_spec.get("hits", 1)))
                fallback_times = [
                    cast_time for cast_time in cast_times for _ in range(hits_per_cast)
                ]
                if len(fallback_times) >= applications:
                    application_times = fallback_times[:applications]
            for application_index in range(applications):
                hp_now = max(0.0, target_health - mitigated_damage_dealt)
                authored_time = (
                    application_times[application_index]
                    if application_index < len(application_times)
                    and len(application_times) >= applications
                    else None
                )
                result.ability_item_applications.append(
                    AbilityItemApplication(
                        effectiveness=effectiveness,
                        target_hp=hp_now,
                        on_hit=is_on_hit,
                        on_attack="on_attack" in triggers,
                        time=authored_time,
                    )
                )
                applied = (
                    _ability_applied_on_hit_damage(state, effectiveness, hp_now)
                    if is_on_hit
                    else {}
                )
                applied_sum = sum(applied.values())
                for dtype, amount in applied.items():
                    applied_by_type[dtype] = applied_by_type.get(dtype, 0.0) + amount
                applied_total += applied_sum
                mitigated_damage_dealt += applied_sum
            if applied_total > 0:
                breakdown[f"on_hit_items_{ability_key}"] = {
                    "name": f"{ability_info['name']} (item on-hits)",
                    "count": applications,
                    "damage_per_hit": applied_total / applications,
                    "total_damage": applied_total,
                    **_damage_type_fields(applied_by_type),
                }
                state.total_damage += applied_total

        # Stack/combo procs whose resistance debuff begins only AFTER the
        # proc damage (Vi W) live between the triggering hit and the next
        # ability. They are damage events, not additional casts.
        post_hit_total = _apply_post_hit_proc(
            state,
            ability_key,
            ability_info,
            num_casts,
            plan.times.get(ability_key, ()),
            mitigated_damage_dealt,
        )
        mitigated_damage_dealt += post_hit_total

        # Apply target debuffs (e.g. Kog'Maw Q resistance shred) AFTER
        # computing this ability's own damage, so subsequent abilities
        # benefit from the shred but the source ability does not. An
        # ability that never gets cast (autos-only mode) shreds nothing.
        # A ramped debuff already staged itself across the ability's own
        # hits; only its unfired remainder lands here.
        target_debuff = ability_info.get("target_debuff")
        if target_debuff and num_casts > 0:
            # A shred that expires is applied time-weighted by how much
            # of the fight its windows actually cover (see
            # ``_debuff_coverage``); one with no declared duration lasts
            # the fight, as it always has.
            # One-rotation mode is a burst: the whole combo lands well
            # inside any shred window, and its ``fight_duration_seconds``
            # is only a nominal cap — weighting by it would be arbitrary.
            coverage = (
                1.0
                if state.one_rotation
                else _debuff_coverage(
                    plan.times.get(ability_key, ()),
                    target_debuff.get("duration", 0.0),
                    state.fight_duration_seconds,
                )
            )
            if shred_ramp is not None:
                shred_ramp.apply_remainder(coverage)
            else:
                _apply_target_shred(resists, target_debuff, coverage)

    # Update effective MR for non-ability damage using final Vile Decay stacks.
    # Non-ability damage occurs during/after the full rotation, so use
    # post-ult MR (Malignance reduction active).
    if resists.mr_reduction_effect and vile_decay_stacks > 0:
        mr_with_stacks = reduce_resistance(
            resists.reduced_mr,
            resists.mr_reduction_effect.reduction_per_stack * vile_decay_stacks * 100.0,
        )
        mr_with_stacks = max(mr_with_stacks, min(0.0, resists.reduced_mr))
        resists.effective_mr = apply_magic_penetration(
            mr_with_stacks, resists.magic_pen_flat, resists.auto_magic_pen_percent
        )

    # Abilities are done; remaining damage (autos, on-hit, item procs)
    # switches to the auto-attack pen variants (Terminus average).
    if resists.has_terminus and resists.terminus_avg_pen > 0:
        resists.use_auto_pen()

    return result


def _add_precomputed_proc_damage(
    state: FightState, rotation: RotationResult | None = None
) -> None:
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
        authored_proc_times: list[float] | None = None
        if (
            info.get("timeline_event_model") == "ziggs_short_fuse"
            and not state.one_rotation
            and state.num_auto_attacks > 0
            and rotation is not None
        ):
            # Short Fuse starts ready, then enters its 12s cooldown after the
            # empowered swing.  Every ability cast reduces the remaining
            # cooldown at cast start by the sourced level refund.
            cooldown = float(info.get("short_fuse_cooldown", 0.0))
            refund = float(info.get("short_fuse_refund", 0.0))
            auto_times = _auto_attack_timestamps(state)
            cast_times = sorted(float(event["time"]) for event in rotation.cast_events)
            ready_at = 0.0
            cast_index = 0
            authored_proc_times = []
            for auto_time in auto_times:
                while (
                    cast_index < len(cast_times) and cast_times[cast_index] <= auto_time
                ):
                    if ready_at > cast_times[cast_index]:
                        ready_at = max(cast_times[cast_index], ready_at - refund)
                    cast_index += 1
                if auto_time + 1e-9 < ready_at:
                    continue
                authored_proc_times.append(auto_time)
                ready_at = auto_time + cooldown
                if len(authored_proc_times) >= int(proc_count):
                    break
            proc_count = len(authored_proc_times)
            if proc_count <= 0:
                continue
        elif (
            info.get("timeline_event_model") == "ziggs_short_fuse"
            and state.one_rotation
            and rotation is not None
            and state.num_auto_attacks >= int(proc_count)
        ):
            # A one-rotation request supplies a fixed Short Fuse proc count.
            # When the authored auto stream contains at least that many
            # swings, attach each proc to its corresponding swing so the
            # candidate timeline is ordered rather than leaving every build
            # partial merely because the passive row was aggregated.
            authored_proc_times = _auto_attack_timestamps(state)[: int(proc_count)]
        if (
            info.get("event_order_certified") == "auto_stack_proc"
            and not state.one_rotation
        ):
            # The module's packet count is an upper bound; a stack-triggered
            # proc cannot occur before its required ambient swings land.
            every = max(1, int(info.get("auto_stack_every", 1)))
            proc_count = min(int(proc_count), int(state.num_auto_attacks) // every)
            if proc_count <= 0:
                continue
        coupled_to_autos = bool(info.get("requires_auto_timeline_coupling"))
        if coupled_to_autos:
            # A champion cannot consume more empowered-attack stacks than
            # there are authored auto swings in this window.  The old fixed
            # proc count made Ambessa's passive damage appear even with no
            # attacks and overstated both damage and healing.
            proc_count = min(int(proc_count), int(state.num_auto_attacks))
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
        # Keep the existing aggregate arithmetic, but retain the priced
        # per-instance values for champion passives that explicitly need an
        # authored event ledger.  Caitlyn's Headshot is one proc row whose
        # parts may contain several distinct basic-attack instances (a trap
        # headshot, E-granted headshots, and natural cadence headshots).  A
        # single phase-order row made every Caitlyn build look uncertified to
        # the coupled optimizer even when no other source was partial.
        priced_part_instances: list[tuple[str, float]] = []
        per_proc = 0.0
        for part in parts:
            mitigated_part = _apply_basic_amp(
                state,
                part,
                _mitigate(part.amount, part.damage_type, resists, state.magic_amp),
                procs=part.count * proc_count,
            )
            per_proc += mitigated_part * part.count
            priced_part_instances.extend(
                (part.damage_type, mitigated_part) for _ in range(part.count)
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
        # Module-authored self-shield payloads (E8c) ride proc rows too: the
        # rebuilt damage-event ledger is aligned by ordinal against this list
        # in ``_ordered_damage_events`` (Akshan's Dirty Fighting proc shield
        # grants on the first completed 3-stack detonation).
        if info.get("self_shield_events") is not None:
            state.breakdown[key]["self_shield_events"] = info["self_shield_events"]
        if (
            rotation is not None
            and info.get("timeline_event_model") == "brand_blaze"
            and int(proc_count) == 1
        ):
            # Brand's packet supplies the 0.25s tick cadence and the
            # two-second ring delay. The accepted cast ledger supplies the
            # actual stack-application times, including Pyroclasm's sourced
            # 0.15s bounce spacing, so no phase-order estimate is used.
            stack_count = int(info.get("dot_stack_count", 0))
            tick_interval = float(info.get("dot_tick_interval", 0.0))
            ability_events = _ordered_damage_events(
                state.breakdown,
                state.ability_damages,
                state.cast_order,
                cast_events=rotation.cast_events,
            )
            stack_times = [
                float(event["time"])
                for event in ability_events
                if event.get("phase") == "ability"
                and event.get("source_key") in state.ability_damages
            ][:stack_count]
            dot_damage = (
                priced_part_instances[0][1]
                if stack_count > 0 and priced_part_instances
                else 0.0
            )
            detonation_damage = (
                priced_part_instances[stack_count][1]
                if len(priced_part_instances) > stack_count
                else 0.0
            )
            if (
                stack_count > 0
                and tick_interval > 0
                and len(stack_times) == stack_count
            ):
                authored: list[dict[str, Any]] = []
                ticks = int(round(float(info.get("dot_duration", 0.0)) / tick_interval))
                for stack_time in stack_times:
                    for tick_index in range(1, ticks + 1):
                        authored.append(
                            {
                                "time": stack_time + tick_index * tick_interval,
                                "damage_type": dtype,
                                "damage": dot_damage / ticks,
                                "event_precision": "exact",
                            }
                        )
                if detonation_damage > 0:
                    authored.append(
                        {
                            "time": stack_times[-1] + 2.0,
                            "damage_type": dtype,
                            "damage": detonation_damage,
                            "event_precision": "exact",
                        }
                    )
                if authored and math.isclose(
                    sum(event["damage"] for event in authored),
                    proc_total,
                    rel_tol=1e-9,
                    abs_tol=1e-6,
                ):
                    state.breakdown[key]["damage_events"] = authored
                    state.breakdown[key]["event_phase"] = "effect"
        declared_events = info.get("damage_events")
        if info.get("timeline_event_model") == "braum_concussive" and isinstance(
            declared_events, list
        ):
            raw_event_total = sum(
                float(event.get("damage", 0.0))
                for event in declared_events
                if isinstance(event, dict)
            )
            if raw_event_total > 0:
                scale = proc_total / raw_event_total
                state.breakdown[key]["damage_events"] = [
                    {
                        **event,
                        "damage_type": dtype,
                        "damage": float(event.get("damage", 0.0)) * scale,
                        "event_precision": "exact",
                    }
                    for event in declared_events
                    if isinstance(event, dict)
                ]
                state.breakdown[key]["event_phase"] = "effect"
        elif authored_proc_times is not None and len(authored_proc_times) == proc_count:
            state.breakdown[key]["damage_events"] = [
                {
                    "time": time,
                    "damage_type": dtype,
                    "damage": per_proc,
                    "event_precision": "exact",
                }
                for time in authored_proc_times
            ]
            state.breakdown[key]["event_phase"] = "auto"
        elif isinstance(declared_events, list) and len(declared_events) == proc_count:
            # Champion modules may provide a sourced phase-order ledger for
            # fixed-count procs (for example Akali's passive).  Re-price each
            # declared event with the same mitigation used for the aggregate
            # row while preserving its authored ordering metadata.
            state.breakdown[key]["damage_events"] = [
                {
                    **event,
                    "damage_type": dtype,
                    "damage": per_proc,
                    "raw_damage": sum(part.amount * part.count for part in parts),
                }
                for event in declared_events
                if isinstance(event, dict)
            ]
            state.breakdown[key]["event_phase"] = str(info.get("event_phase", "effect"))
        elif (
            info.get("event_order_certified") == "auto_stack_proc"
            and state.num_auto_attacks > 0
        ):
            # A champion-owned stack proc can certify its timing when the
            # module supplies the sourced stack cadence (Akshan: every
            # third damaging attack).  Do not invent times when the fight
            # contains fewer swings than the requested proc packet.
            every = max(1, int(info.get("auto_stack_every", 1)))
            required_swings = proc_count * every
            auto_times = _auto_attack_timestamps(state)
            if required_swings <= len(auto_times):
                state.breakdown[key]["damage_events"] = [
                    {
                        "time": auto_times[(index + 1) * every - 1],
                        "damage_type": dtype,
                        "damage": per_proc,
                        "event_precision": "exact",
                    }
                    for index in range(proc_count)
                ]
                state.breakdown[key]["event_phase"] = "auto"
        elif (
            key == "passive"
            and info.get("name") == "Headshot"
            and priced_part_instances
        ):
            # Headshot's module owns the ordering assumptions: with no
            # ambient autos, the E/trap attacks are forced at the combo
            # boundary; with autos, the first converted swings land on the
            # same authored timestamps as the auto stream.  The parser's
            # aggregate packet stays unchanged, so this ledger is runtime
            # evidence rather than a new guessed formula.
            if state.num_auto_attacks > 0 and state.auto_attack_uptime > 0:
                auto_times = _auto_attack_timestamps(state)
                # Caitlyn's timed packet emits the trap rider as the final
                # part after the common E/cadence rider.  The Wiki ordering
                # is trap first, then E grants, then natural cadence.
                if len(priced_part_instances) > 1:
                    ordered_instances = [
                        priced_part_instances[-1],
                        *priced_part_instances[:-1],
                    ]
                else:
                    ordered_instances = priced_part_instances
                event_times = auto_times[: len(ordered_instances)]
                event_phase = "auto"
            else:
                ordered_instances = priced_part_instances
                event_times = [0.0] * len(ordered_instances)
                event_phase = "effect"
            state.breakdown[key]["damage_events"] = [
                {
                    "time": event_times[index] if index < len(event_times) else 0.0,
                    "damage_type": event_type,
                    "damage": event_damage,
                    "event_precision": "exact",
                }
                for index, (event_type, event_damage) in enumerate(ordered_instances)
            ]
            state.breakdown[key]["event_phase"] = event_phase
        elif coupled_to_autos and state.num_auto_attacks > 0:
            auto_times = _auto_attack_timestamps(state)
            authored_events = [
                {
                    "time": auto_times[index] if index < len(auto_times) else 0.0,
                    "damage_type": dtype,
                    "damage": per_proc,
                }
                for index in range(proc_count)
            ]
            # Ability hits can advance a coupled passive between autos
            # (Aurora's Spirit Abjuration). Keep the public ledger
            # chronological even when those authored hit times arrive out
            # of order relative to the ambient auto cadence.
            authored_events.sort(key=lambda event: float(event["time"]))
            state.breakdown[key]["damage_events"] = authored_events
            state.breakdown[key]["event_phase"] = "auto"
        # Champion-minted display text (e.g. Braum P's cycle summary) and
        # count label (e.g. Diana's "cleaves") ride the entry onto its
        # breakdown row, as in the rotation.
        for display_key in ("detail", "unit"):
            if display_key in info:
                state.breakdown[key][display_key] = info[display_key]
        state.total_damage += proc_total


def _ability_dot_tick_events(
    entry: dict[str, Any],
    info: dict[str, Any],
    cast_times: list[float],
) -> list[dict[str, float | str]] | None:
    """One DoT ability row's per-tick events, or None to stay coarse.

    A row qualifies when its ability declares both ``dot_duration`` and a
    wiki-sourced ``dot_tick_interval``. Each accepted cast spreads its even
    share of the row's typed damage across the DoT window from its cast
    time, using the same full-tick/remainder split as item burns. Rows
    without a sourced cadence author nothing (fail-closed — a cadence is
    never invented), as do rows whose totals a later step may move
    (``empowers_next_auto`` swings) or whose typed parts do not reproduce
    the row total. A malformed cadence (non-finite or non-numeric
    ``dot_duration``/``dot_tick_interval``) is treated the same as a missing
    one — fail-closed, never coerced or invented.
    """
    dot_duration = _finite_numeric_receipt(info.get("dot_duration", 0.0)) or 0.0
    tick_interval = _finite_numeric_receipt(info.get("dot_tick_interval", 0.0)) or 0.0
    if dot_duration <= 0 or tick_interval <= 0:
        return None
    if info.get("empowers_next_auto"):
        return None  # the reattributed swing would break the event sum
    casts = max(0, int(entry.get("casts", 0)))
    if casts <= 0:
        return None
    parts = _row_damage_parts(entry)
    if not parts or not math.isclose(
        sum(amount for _, amount in parts),
        float(entry.get("total_damage", 0.0)),
        rel_tol=1e-9,
        abs_tol=1e-6,
    ):
        return None
    events: list[dict[str, float | str]] = []
    for cast_index in range(casts):
        cast_time = cast_times[cast_index] if cast_index < len(cast_times) else 0.0
        for dtype, amount in parts:
            for tick in _periodic_damage_events(
                amount / casts, dtype, dot_duration, tick_interval
            ):
                events.append({**tick, "time": cast_time + float(tick["time"])})
    events.sort(key=lambda tick: float(tick["time"]))
    return events or None


def _author_ability_dot_events(state: FightState, rotation: RotationResult) -> None:
    """Author per-tick damage events for DoT ability rows with sourced cadence.

    Ticks let the coverage classifier certify a ``dot_duration`` row
    instead of downgrading it at the cast boundary; rows that stay
    unsourced keep coarse ordering. Rows that already authored their own
    event ledger are left alone.
    """
    times_by_slot: dict[str, list[float]] = {}
    for event in rotation.cast_events:
        slot = str(event.get("slot", ""))
        times_by_slot.setdefault(slot, []).append(float(event.get("time", 0.0)))
    for key in state.cast_order:
        entry = state.breakdown.get(key)
        info = state.ability_damages.get(key, {})
        if not entry or entry.get("damage_events") is not None:
            continue
        events = _ability_dot_tick_events(entry, info, times_by_slot.get(key, []))
        if events is not None:
            entry["damage_events"] = events
            entry["event_phase"] = "ability"


class _DotTickLedger:
    """Buckets a stacking DoT's continuous integral into sourced ticks.

    Constructed with the spec's ``tick_interval`` (0 disables authoring —
    an unsourced cadence is never invented) and the fight's rate integral.
    ``accumulate`` integrates one constant-stack span, cutting it at the
    tick boundaries riding the current chain's clock; ``open_chain``
    anchors that clock at the application that opened a chain;
    ``close_chain`` flushes the last partial tick where a chain's bleed
    actually stopped. ``events`` scales the raw buckets to the mitigated
    total, since mitigation is one linear factor.
    """

    def __init__(
        self,
        interval: float,
        integrate: Callable[[float, float, int], float],
    ) -> None:
        self.interval = interval
        self.authoring = interval > 0
        self._integrate = integrate
        self._raw_ticks: list[list[float]] = []  # [time, raw damage]
        self._pending_raw = 0.0
        self._next_tick: float | None = None

    def open_chain(self, time: float) -> None:
        """Anchor the tick clock when no chain is running."""
        if self.authoring and self._next_tick is None:
            self._next_tick = time + self.interval

    def close_chain(self, time: float) -> None:
        """Flush the chain's last partial tick and drop its clock."""
        if self.authoring:
            self._flush(time)
            self._next_tick = None

    def accumulate(self, start: float, end: float, stacks: int) -> float:
        """Integrate [start, end), bucketing the raw damage into ticks."""
        if not self.authoring:
            return self._integrate(start, end, stacks)
        raw = 0.0
        cursor = start
        while self._next_tick is not None and self._next_tick <= end:
            raw += self._bucket(cursor, self._next_tick, stacks)
            cursor = self._next_tick
            self._flush(self._next_tick)
            self._next_tick += self.interval
        raw += self._bucket(cursor, end, stacks)
        return raw

    def _bucket(self, start: float, end: float, stacks: int) -> float:
        segment = self._integrate(start, end, stacks)
        self._pending_raw += segment
        return segment

    def _flush(self, time: float) -> None:
        if self._pending_raw > 0:
            self._raw_ticks.append([time, self._pending_raw])
            self._pending_raw = 0.0

    def events(
        self, damage_type: str, total: float, raw_total: float
    ) -> list[dict[str, Any]] | None:
        """The mitigated per-tick event list, or None when not authoring."""
        if not (self.authoring and self._raw_ticks and raw_total > 0 and total > 0):
            return None
        scale = total / raw_total
        events: list[dict[str, Any]] = [
            {
                "time": time,
                "damage_type": damage_type,
                "damage": raw * scale,
                "event_precision": "exact",
            }
            for time, raw in self._raw_ticks
        ]
        # Eliminate floating-point drift while preserving every tick's timing.
        events[-1]["damage"] += total - sum(event["damage"] for event in events)
        return events


def _integrate_stack_chains(
    timeline: StackTimeline,
    duration: float,
    ledger: _DotTickLedger,
) -> float:
    """Walk the stack applications, integrating every chain's raw damage.

    Each span between applications ticks at the running stack count;
    ticks stop ``duration`` after the last application even if the next
    one comes later (the chain expired meanwhile), and the final
    application commits its full window of ticks past the fight cutoff.
    The ledger buckets the same integral into tick events as it goes.
    """
    raw_total = 0.0
    stacks = timeline.starting_stacks
    previous_hit = 0.0
    if stacks > 0:
        ledger.open_chain(0.0)  # the pre-fight chain is already running
    for application in timeline.applications:
        if stacks > 0:
            chain_end = min(application.time, previous_hit + duration)
            raw_total += ledger.accumulate(previous_hit, chain_end, stacks)
            if application.stacks_before == 0:
                # The chain expired before this hit: close its last
                # (partial) tick where the bleed actually stopped.
                ledger.close_chain(chain_end)
        # A fresh chain's ticks ride this application's clock; a running
        # chain keeps its anchor (open_chain is a no-op then).
        ledger.open_chain(application.time)
        stacks = application.stacks_after
        previous_hit = application.time
    # Committed tail: the last application's full window of ticks.
    raw_total += ledger.accumulate(previous_hit, previous_hit + duration, stacks)
    ledger.close_chain(previous_hit + duration)
    return raw_total


def _add_stacking_dot_damage(state: FightState) -> None:
    """Add hit-timeline stacking DoT damage (Case 4, e.g. Briar's bleed).

    Integrates the DoT's tick rate at the running stack count over the
    fight's :class:`StackTimeline` — the SAME applications the rotation
    priced its casts against. Every application refreshes the shared
    duration (in-game: reapplying refreshes the whole bleed); a gap
    longer than ``duration`` expires the chain. Committed accounting:
    the final ``duration`` of ticks after the last hit counts in full,
    even past the fight cutoff. A stack-triggered bonus-AD window
    (Case 5) raises the tick rate for exactly the part of each gap that
    falls inside it, so a window opening mid-gap splits that gap. The
    DoT cannot crit and triggers nothing; it is mitigated once as its
    declared type.

    A spec with a sourced ``tick_interval`` also authors per-tick damage
    events: the same integral is bucketed at tick boundaries riding each
    chain's clock (anchored at the application that opened the chain; a
    gap of ``duration`` closes the chain's last partial tick where the
    bleed stopped and the next application re-anchors the grid). Without
    a sourced cadence no events are invented and the row stays coarse.
    """
    timeline = state.stack_timeline
    if timeline is None:
        return
    # Pre-fight stacks tick on their own, so a fight that lands no
    # applications still bleeds when the target arrives stacked.
    if not timeline.applications and timeline.starting_stacks <= 0:
        return
    dot_key, spec = timeline.dot_key, timeline.spec

    duration = float(spec["duration"])
    extra_effectiveness = float(spec["extra_stack_effectiveness"])
    single_stack_dps = float(spec["single_stack_raw"]) / duration
    # A mid-fight bonus-AD steroid raises every stack's rate by the
    # DoT's own declared derivative in bonus AD (Darius' bleed: 30% of
    # bonus AD per stack).
    buffed_bonus_dps = (
        float(spec.get("single_stack_bonus_ad_ratio", 0.0))
        * timeline.buff_bonus_ad
        / duration
    )

    def tick_rate(stacks: int, buffed: bool) -> float:
        """Raw DPS at a stack count; extra stacks may tick reduced."""
        single = single_stack_dps + (buffed_bonus_dps if buffed else 0.0)
        return single * (1.0 + extra_effectiveness * (stacks - 1))

    def integrate(start: float, end: float, stacks: int) -> float:
        """Raw damage ticked over [start, end), split at buff windows."""
        total_raw = 0.0
        cursor = start
        for window_start, window_end in timeline.buff_windows:
            if window_end <= cursor:
                continue
            if window_start >= end:
                break
            if window_start > cursor:
                total_raw += tick_rate(stacks, False) * (window_start - cursor)
                cursor = window_start
            segment_end = min(window_end, end)
            total_raw += tick_rate(stacks, True) * (segment_end - cursor)
            cursor = segment_end
        if cursor < end:
            total_raw += tick_rate(stacks, False) * (end - cursor)
        return total_raw

    ledger = _DotTickLedger(float(spec.get("tick_interval", 0.0)), integrate)
    raw_total = _integrate_stack_chains(timeline, duration, ledger)

    damage_type = spec.get("damage_type", "physical")
    total = _mitigate(raw_total, damage_type, state.resists, state.magic_amp)
    # A seeded-only fight lands no applications; the pre-fight stacks are
    # what the row is reporting, so they are its count.
    applications = len(timeline.applications) or timeline.starting_stacks
    row: dict[str, Any] = {
        "name": spec["name"],
        "count": applications,
        "damage_per_hit": total / applications,
        "unit": "stacks",
        "total_damage": total,
        "damage_type": damage_type,
        "detail": (
            f"{applications} stack application(s); each refresh commits "
            f"the full {duration:g}s of ticks"
        ),
    }
    events = ledger.events(damage_type, total, raw_total)
    if events is not None:
        row["damage_events"] = events
        row["event_phase"] = "effect"
    state.breakdown[f"stacking_dot_{dot_key}"] = row
    state.total_damage += total


def _shaped_charge_proc_receipts(
    state: FightState,
    rotation: RotationResult,
    cooldown: float,
) -> list[dict[str, Any]] | None:
    """Return Shaped Charge trigger times with their timing precision.

    Exact ability hit packets are preferred when the champion module authors
    them. Otherwise, the existing cast-boundary fallback is retained and
    explicitly marked coarse. A per-slot cursor prevents repeated casts from
    reusing one authored packet.
    """
    if not math.isfinite(cooldown) or cooldown <= 0.0:
        return None
    receipts: list[dict[str, Any]] = []
    ready_at = 0.0
    event_cursors: dict[str, int] = {}
    breakdown = getattr(state, "breakdown", {})
    for cast_event in rotation.cast_events:
        if not isinstance(cast_event, Mapping):
            return None
        slot = cast_event.get("slot")
        if not isinstance(slot, str):
            return None
        event_time = _finite_numeric_receipt(cast_event.get("time"))
        if event_time is None or event_time < 0.0:
            return None
        ability = state.ability_damages.get(slot)
        if not isinstance(ability, Mapping):
            return None
        parts = ability.get("parts", ())
        if not isinstance(parts, (tuple, list)):
            return None
        damaging = any(
            getattr(part, "amount", 0.0) > 0.0
            or getattr(part, "hp_scaled_damage", None) is not None
            for part in parts
        )
        if not damaging:
            continue
        trigger_time = event_time
        precision = _item_proc_precision(state, slot)
        row = breakdown.get(slot) if isinstance(breakdown, Mapping) else None
        authored_events = row.get("damage_events") if isinstance(row, Mapping) else None
        if isinstance(authored_events, list):
            cursor = event_cursors.get(slot, 0)
            while cursor < len(authored_events):
                candidate = authored_events[cursor]
                if not isinstance(candidate, Mapping):
                    return None
                candidate_time = _finite_numeric_receipt(candidate.get("time"))
                candidate_damage = _finite_numeric_receipt(candidate.get("damage"))
                if candidate_time is None or candidate_damage is None:
                    return None
                if candidate_time + 1e-9 < event_time:
                    cursor += 1
                    continue
                if candidate_damage > 0.0:
                    trigger_time = candidate_time
                    precision = str(candidate.get("event_precision", "exact"))
                    cursor += 1
                    event_cursors[slot] = cursor
                    break
                cursor += 1
            else:
                event_cursors[slot] = cursor
        if trigger_time < ready_at:
            continue
        receipts.append({"time": trigger_time, "event_precision": precision})
        ready_at = trigger_time + cooldown
    return receipts


def _add_shaped_charge_damage(state: FightState, rotation: RotationResult) -> None:
    """Add ability-triggered lethality procs from the authored cast ledger."""
    for effect in state.damage_effects.shaped_charges:
        source = effect.source
        proc_receipts = _shaped_charge_proc_receipts(state, rotation, effect.cooldown)
        if proc_receipts is None:
            # A malformed cast ledger withholds every proc boundary.  Keep a
            # NAMED zero-damage row (P3 package 3D): callers can distinguish
            # a malformed ledger from a passive that never fired, and the
            # coverage classifier treats the withheld row as coarse so the
            # optimizer exclusion receipt names it.  No damage is invented.
            per_proc = source.raw_damage(_damage_inputs(state))
            state.breakdown[source.breakdown_key] = {
                "name": source.display_name,
                "count": 0,
                "damage_per_proc": per_proc,
                "total_damage": 0.0,
                "damage_type": source.damage_type,
                "event_phase": "coarse",
                "withheld_reason": "malformed_proc_receipt",
            }
            continue
        if not proc_receipts:
            # No damaging ability cast consumed the charge: the passive
            # never fired, and no row is authored (no aggregate substitute).
            continue
        per_proc = source.raw_damage(_damage_inputs(state))
        procs = len(proc_receipts)
        total_damage = per_proc * procs
        state.breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "count": procs,
            "damage_per_proc": per_proc,
            "total_damage": total_damage,
            "damage_type": source.damage_type,
            "damage_events": [
                {
                    "time": receipt["time"],
                    "damage": per_proc,
                    "damage_type": source.damage_type,
                    "event_precision": receipt["event_precision"],
                }
                for receipt in proc_receipts
            ],
            "event_phase": "ability",
        }
        state.total_damage += total_damage


@dataclass
class AutoAttackResult:
    """Values produced by the auto-attack simulation for later steps."""

    auto_damage_per_hit: float = 0.0
    double_shot_info: dict[str, Any] | None = None


def _base_auto_attack_timestamps(state: FightState) -> list[float]:
    """Return the same per-swing schedule used to derive the auto count.

    A normal stream starts at time zero and advances at attack speed times
    uptime. Ultimate attack-speed windows use their buffed rate first, then
    hand the remaining swings to the ordinary rate. Keeping this schedule next
    to the count calculation prevents threshold defenses from treating a
    multi-second auto stream as one post-rotation burst.
    """
    if state.num_auto_attacks <= 0 or state.auto_attack_uptime <= 0:
        return []
    normal_rate = state.attack_speed * state.auto_attack_uptime
    if normal_rate <= 0:
        return []
    if state.q_window_end > 0.0:
        # P1 Slice 11 (Ashe Q active window): the autos ride the base
        # rate before the cast, the buffed rate inside [cast_start,
        # q_window_end), then the base rate again from the window end
        # (end-exclusive — a swing landing exactly at the boundary is
        # normal).
        buffed_rate = state.attack_speed * state.auto_attack_uptime
        base_rate = state.q_window_base_rate * state.auto_attack_uptime
        times = []
        if base_rate > 0.0:
            times.extend(index / base_rate for index in range(state.q_window_pre_autos))
        if buffed_rate > 0.0:
            times.extend(
                state.q_window_start + index / buffed_rate
                for index in range(state.q_window_autos)
            )
        if base_rate > 0.0:
            times.extend(
                state.q_window_end + index / base_rate
                for index in range(
                    state.num_auto_attacks
                    - state.q_window_pre_autos
                    - state.q_window_autos
                )
            )
        return times
    buff = state.damage_effects.ultimate_auto_buff
    empowered = state.empowered_autos if buff is not None else 0
    if empowered <= 0:
        if (
            not state.one_rotation
            and item_effects.has_item(state.items, "Guinsoo's Rageblade")
        ) or item_effects.has_item(state.items, "Yun Tal Wildarrows"):
            times = list(
                item_effects.guinsoo_swing_schedule(
                    state.items,
                    attack_speed=state.attack_speed,
                    attack_speed_ratio=state.attack_speed_ratio,
                    duration_seconds=state.fight_duration_seconds,
                    uptime=state.auto_attack_uptime,
                    critical_chance=state.champion_stats.get(
                        "critical_strike_chance", 0.0
                    )
                    / 100.0,
                )
            )
        else:
            times = [index / normal_rate for index in range(state.num_auto_attacks)]
        return times

    buffed_rate = (
        state.attack_speed
        + state.attack_speed_ratio * buff.bonus_attack_speed_percent / 100.0
    ) * state.auto_attack_uptime
    if buffed_rate <= 0:
        return [index / normal_rate for index in range(state.num_auto_attacks)]
    times = [index / buffed_rate for index in range(empowered)]
    normal_start = empowered / buffed_rate
    times.extend(
        normal_start + index / normal_rate
        for index in range(state.num_auto_attacks - empowered)
    )
    return times


def _hail_attack_schedule(
    state: FightState, effect: "rune_effects.KeystoneHailOfBladesEffect"
) -> tuple[list[float], list[int], list[float]]:
    """Build Hail's timed swing window and active attack indexes.

    The first completed attack activates Hail and benefits from it. Each
    active basic attack consumes one sourced stack. A later activation waits
    for the sourced cooldown. Basic-attack reset receipts are handled by
    their carrier rows; the ambient schedule contains no reset event.
    """
    base_rate = state.attack_speed * state.auto_attack_uptime
    if (
        base_rate <= 0.0
        or state.fight_duration_seconds <= 0.0
        or effect.initial_stacks <= 0
        or effect.stack_duration_seconds <= 0.0
    ):
        return [], [], []

    bonus_percent = effect.bonus_attack_speed_percent(state.is_melee)
    active_rate = (
        state.attack_speed + state.attack_speed_ratio * bonus_percent / 100.0
    ) * state.auto_attack_uptime
    if active_rate <= 0.0:
        return [], [], []

    times: list[float] = []
    active_indexes: list[int] = []
    activation_times: list[float] = []
    current = 0.0
    cooldown_ready = float("-inf")
    active_until = float("-inf")
    stacks = 0
    duration = state.fight_duration_seconds
    base_interval = 1.0 / base_rate
    active_interval = 1.0 / active_rate

    while current < duration - 1e-12:
        attack_index = len(times)
        times.append(current)

        if stacks <= 0 and current + 1e-9 >= cooldown_ready:
            stacks = effect.initial_stacks
            active_until = current + effect.stack_duration_seconds
            activation_times.append(current)

        if stacks > 0 and current <= active_until + 1e-9:
            active_indexes.append(attack_index)
            stacks -= 1
            active_until = current + effect.stack_duration_seconds
            if stacks == 0:
                cooldown_ready = current + effect.cooldown_seconds

        interval = active_interval if stacks > 0 else base_interval
        next_time = current + interval
        if stacks > 0 and next_time > active_until + 1e-9:
            stacks = 0
            interval = base_interval
            next_time = current + interval
        current = next_time

    return times, active_indexes, activation_times


def _prepare_hail_attack_schedule(state: FightState) -> None:
    """Install Hail's raw swing schedule before the rotation is priced."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneHailOfBladesEffect):
        return
    times, active_indexes, activation_times = _hail_attack_schedule(state, effect)
    state.hail_attack_times = tuple(times)
    state.hail_active_attack_indices = tuple(active_indexes)
    state.hail_activation_times = tuple(activation_times)
    state.num_auto_attacks = len(times)

    # Terminus and Black Cleaver are priced from the authored auto count.
    # Re-resolve their auto variants after Hail changes that count, before
    # the ability rotation consumes the resistance object.
    if state.damage_effects.stacking_pen is not None:
        state.resists.terminus_avg_pen = state.damage_effects.stacking_pen.average_pen(
            state.num_auto_attacks
        )
    if state.damage_effects.armor_reduction is not None:
        state.resists.bc_reduction = (
            state.damage_effects.armor_reduction.average_reduction(
                state.num_auto_attacks
            )
        )
    state.resists.resolve_magic()
    state.resists.resolve_armor()


def _lethal_tempo_stacks_at(
    effect: "rune_effects.KeystoneLethalTempoEffect",
    stacks: int,
    last_attack: float | None,
    attack_time: float,
) -> int:
    """Expire Lethal Tempo stacks before one later attack."""
    if last_attack is None or attack_time < last_attack + effect.stack_duration_seconds:
        return stacks
    elapsed = attack_time - (last_attack + effect.stack_duration_seconds)
    expired = 1 + int(math.floor(elapsed / effect.expiry_step_seconds + 1e-9))
    return max(0, stacks - expired)


def _lethal_tempo_attack_schedule(
    state: FightState,
    effect: "rune_effects.KeystoneLethalTempoEffect",
    attack_times: list[float] | None = None,
) -> tuple[list[float], list[int], list[int], list[float]]:
    """Build Lethal Tempo's stack-sensitive swing and bolt schedule."""
    base_rate = state.attack_speed * state.auto_attack_uptime
    if (
        base_rate <= 0.0
        or state.fight_duration_seconds <= 0.0
        or effect.max_stacks <= 0
        or effect.stack_duration_seconds <= 0.0
        or effect.expiry_step_seconds <= 0.0
    ):
        return [], [], [], []

    if attack_times is not None:
        times = sorted(float(time) for time in attack_times)
        generated = False
    else:
        times = []
        current = 0.0
        generated = True
        while current < state.fight_duration_seconds - 1e-12:
            times.append(current)
            current += 1.0 / base_rate

    bolt_indexes: list[int] = []
    stack_counts: list[int] = []
    activation_times: list[float] = []
    stacks = 0
    last_attack: float | None = None

    if generated:
        times = []
        current = 0.0
        while current < state.fight_duration_seconds - 1e-12:
            current_stacks = _lethal_tempo_stacks_at(
                effect, stacks, last_attack, current
            )
            if current_stacks <= 0:
                current_stacks = 0
                activation_times.append(current)
            stacks = min(effect.max_stacks, current_stacks + 1)
            index = len(times)
            times.append(current)
            stack_counts.append(stacks)
            if stacks >= effect.max_stacks:
                bolt_indexes.append(index)
            last_attack = current
            bonus_percent = effect.attack_speed_percent(state.is_melee, stacks)
            rate = (
                state.attack_speed + state.attack_speed_ratio * bonus_percent / 100.0
            ) * state.auto_attack_uptime
            if rate <= 0.0:
                break
            current += 1.0 / rate
        return times, bolt_indexes, stack_counts, activation_times

    for attack_time in times:
        stacks = _lethal_tempo_stacks_at(effect, stacks, last_attack, attack_time)
        if stacks <= 0:
            stacks = 0
            activation_times.append(attack_time)
        stacks = min(effect.max_stacks, stacks + 1)
        index = len(stack_counts)
        stack_counts.append(stacks)
        if stacks >= effect.max_stacks:
            bolt_indexes.append(index)
        last_attack = attack_time
    return times, bolt_indexes, stack_counts, activation_times


def _prepare_lethal_tempo_attack_schedule(state: FightState) -> None:
    """Install Lethal Tempo's raw swing schedule before the rotation."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneLethalTempoEffect):
        return
    times, bolt_indexes, stack_counts, activation_times = _lethal_tempo_attack_schedule(
        state, effect
    )
    state.lethal_attack_times = tuple(times)
    state.lethal_bolt_attack_indices = tuple(bolt_indexes)
    state.lethal_stack_counts = tuple(stack_counts)
    state.lethal_activation_times = tuple(activation_times)
    state.num_auto_attacks = len(times)

    if state.damage_effects.stacking_pen is not None:
        state.resists.terminus_avg_pen = state.damage_effects.stacking_pen.average_pen(
            state.num_auto_attacks
        )
    if state.damage_effects.armor_reduction is not None:
        state.resists.bc_reduction = (
            state.damage_effects.armor_reduction.average_reduction(
                state.num_auto_attacks
            )
        )
    state.resists.resolve_magic()
    state.resists.resolve_armor()


def _auto_attack_timestamps(state: FightState) -> list[float]:
    """Return the shared swing schedule after temporary AS adjustments."""
    times = (
        list(state.hail_attack_times)
        if state.hail_attack_times
        else (
            list(state.lethal_attack_times)
            if state.lethal_attack_times
            else _base_auto_attack_timestamps(state)
        )
    )
    return _apply_spellblade_attack_speed(state, times)


def _restore_stream_attack_timestamps(state: FightState) -> list[float]:
    """The auto-attack swing schedule the per-auto resource walk rides.

    ``_auto_restore_schedule`` runs BEFORE ``_prepare_hail_attack_schedule``
    / ``_prepare_lethal_tempo_attack_schedule`` install their stack-sensitive
    schedules onto ``state.hail_attack_times`` / ``state.lethal_attack_times``
    (see ``calculate_fight_damage``'s ordering), so reading those fields here
    would silently fall back to the uniform base schedule.  Resolve the SAME
    schedule those two installers compute directly from the keystone effect
    instead — ``_hail_attack_schedule`` / ``_lethal_tempo_attack_schedule``
    depend only on ``state.attack_speed``, ``state.auto_attack_uptime``,
    ``state.fight_duration_seconds`` and the keystone effect, none of which
    the cast plan or the installers' own state mutations (``num_auto_attacks``,
    re-resolved resistances) affect — so recomputing here is side-effect free
    and always superseded moments later by the real installer call once the
    resource walk has consumed it.

    If the schedule fields are ALREADY populated (a future caller after the
    installers ran), prefer them outright rather than recomputing. Lich
    Bane's proc-timed speedup is not resolved yet at this point in the
    pipeline (``_prepare_spellblade_attack_schedule`` needs the priced
    rotation), so it is not mirrored here — matching the champion module's
    documented ASSUMPTIONS.
    """
    if state.hail_attack_times:
        return list(state.hail_attack_times)
    if state.lethal_attack_times:
        return list(state.lethal_attack_times)
    effect = state.keystone_effect
    if isinstance(effect, rune_effects.KeystoneHailOfBladesEffect):
        times, _active_indexes, _activation_times = _hail_attack_schedule(state, effect)
        if times:
            return list(times)
    elif isinstance(effect, rune_effects.KeystoneLethalTempoEffect):
        times, _bolt_indexes, _stack_counts, _activation_times = (
            _lethal_tempo_attack_schedule(state, effect)
        )
        if times:
            return list(times)
    return _base_auto_attack_timestamps(state)


def _find_auto_attack_override(
    ability_damages: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the first champion ``auto_attack_override`` payload, if any.

    Supported keys: ``ad_ratio`` / ``crit_as_bonus`` (Ashe — crit chance
    converts to bonus damage on every auto), ``replace_raw`` /
    ``damage_type`` / ``name`` (Azir — the auto stream is replaced
    wholesale by a module-computed flat amount that cannot crit),
    ``damage_ratio`` (Bel'Veth — every basic attack, crit or not, deals
    this fraction of its normal damage), and ``on_hit_effectiveness``
    (Azir 0.5, Bel'Veth 0.75 — scales every on-hit rider on the autos).
    """
    for info in ability_damages.values():
        if "auto_attack_override" in info:
            return info["auto_attack_override"]
    return None


def _basic_attack_true_rider(
    ability_damages: dict[str, dict[str, Any]],
) -> tuple[float, str]:
    """A champion's bonus-true-damage share of every basic attack.

    Corki's Hextech Munitions: each attack deals 20% of its own
    PRE-MITIGATION damage again as true damage. Declared as
    ``basic_attack_true_ratio`` on the ability entry; riding the raw
    damage is what makes the true instance crit-multiplied, exactly as
    the wiki describes ("affected by critical strike modifiers").

    Returns ``(ratio, display_name)``; ratio 0.0 when no entry declares
    it. The name comes from the declaring entry — no second key.
    """
    for info in ability_damages.values():
        ratio = info.get("basic_attack_true_ratio", 0.0)
        if ratio > 0:
            return ratio, info.get("name", "Passive")
    return 0.0, ""


def _on_hit_effectiveness(state: FightState) -> float:
    """Item-effect effectiveness on the auto stream (default 1.0).

    A champion ``auto_attack_override`` may carry ``on_hit_effectiveness``
    (Azir soldiers: 0.5). While such an override is active, ALL
    per-attack and proc-style item effects — per-hit on-hits, spellblade,
    energized, stack-counter procs like Kraken Slayer — apply at this
    effectiveness (game-verified for Azir). Sundered Sky is the
    exception: it does not apply at all on replaced autos (handled in
    ``_simulate_auto_attacks``, which skips its branch in replace mode).
    """
    override = _find_auto_attack_override(state.ability_damages)
    return override.get("on_hit_effectiveness", 1.0) if override else 1.0


def _auto_swing_bonus_ad(
    state: FightState,
    damage_ratio: float,
) -> Callable[[int], float]:
    """Per-auto bonus AD from a stack-triggered steroid (Case 5).

    A mid-fight buff (Darius' Noxian Might) covers only part of the
    fight, so an auto is priced at the AD its own timestamp saw — read
    from the fight's shared :class:`StackTimeline`, which already knows
    which auto opened the window (and so is not itself buffed).
    ``damage_ratio`` mirrors the flat basic-attack modifier the caller
    already applied to the base AD (Bel'Veth's 75%). Returns a function
    of the auto index that is constantly 0.0 whenever no such buff
    exists — every other champion's swings are untouched.
    """
    timeline = state.stack_timeline
    if timeline is None or not timeline.buff_windows:
        return lambda auto_index: 0.0
    swing_times = _auto_attack_timestamps(state)

    def bonus_ad(auto_index: int) -> float:
        time = swing_times[auto_index] if auto_index < len(swing_times) else 0.0
        return timeline.auto_bonus_ad(auto_index, time) * damage_ratio

    return bonus_ad


def _simulate_auto_attacks(state: FightState) -> AutoAttackResult:
    """Simulate each auto attack individually, rolling (or expecting) crits.

    Handles champion auto-attack overrides (Ashe: crit chance converts to
    bonus damage on every auto; Azir: soldier attacks replace the auto
    stream with flat magic damage that cannot crit), Fiendhunter Bolts
    empowered autos
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

    attack_damage = state.champion_stats["attack_damage"]

    # Detect auto_attack_override (e.g. Ashe passive — crit chance converts
    # to bonus damage instead of crit strikes; Q changes AD ratio).
    auto_attack_override = _find_auto_attack_override(state.ability_damages)

    # Detect champion double-shot passive (e.g. Akshan — second auto per
    # attack at reduced AD ratio, applies on-hits and can crit).
    double_shot_info: dict[str, Any] | None = None
    for _ds_key, _ds_info in state.ability_damages.items():
        if "double_shot" in _ds_info:
            double_shot_info = _ds_info["double_shot"]
            break

    # A bounded set of attacks may replace their normal physical swing with
    # one modified basic-damage instance (Galio's Colossal Smash). The
    # module supplies only the non-AD bonus; the ordinary swing path below
    # continues to own crits, Sundered Sky, and mid-fight AD changes.
    conversion_info: dict[str, Any] | None = None
    for _conversion_key, _conversion_entry in state.ability_damages.items():
        if "auto_attack_conversion" in _conversion_entry:
            conversion_info = _conversion_entry["auto_attack_conversion"]
            break
    converted_auto_limit = min(
        num_auto_attacks,
        max(0, int(conversion_info.get("count", 0))) if conversion_info else 0,
    )

    # Simulate each auto attack individually, rolling for crits
    auto_physical_total = 0.0
    converted_auto_total = 0.0
    fiendhunter_true_total = 0.0
    passive_true_total = 0.0  # champion rider (Corki P), % of the raw swing
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

    sundered_sky_damage_diff = 0.0  # post-target: + = bonus, - = lost damage

    # Ashe-style override: crit chance converts to bonus AD ratio on every
    # auto instead of random crit strikes.  ad_ratio replaces the normal 1.0.
    # Azir-style override: replace_raw substitutes the whole auto formula
    # with a flat module-computed amount (its own damage type, no crits).
    override_ad_ratio = 0.0
    override_crit_as_bonus = False
    override_replace_raw: float | None = None
    override_damage_type = "physical"
    damage_ratio = 1.0
    passive_true_ratio, passive_true_name = _basic_attack_true_rider(
        state.ability_damages
    )
    q_window_end = state.q_window_end
    if auto_attack_override:
        override_ad_ratio = auto_attack_override.get("ad_ratio", 1.0)
        override_crit_as_bonus = auto_attack_override.get("crit_as_bonus", False)
        override_replace_raw = auto_attack_override.get("replace_raw")
        override_damage_type = auto_attack_override.get("damage_type", "physical")
        if not override_replace_raw and q_window_end > 0.0:
            # P1 Slice 11: the flurry ratio applies only inside the Q
            # active window [0, q_window_end) — the post-window swings
            # revert to the normal 1.0 ratio (Frost Shot's crit-as-bonus
            # stays on for every swing).  The hoisted override_ad_ratio
            # stays the flurry value; the per-swing swing_window_ratio
            # below applies the window.
            pass
        # Flat modifier on ALL basic-attack damage (Bel'Veth passive:
        # 75%): scaling the AD every auto branch reads covers normal,
        # crit, empowered, forced-crit, and double-shot attacks alike.
        damage_ratio = auto_attack_override.get("damage_ratio", 1.0)
        attack_damage *= damage_ratio

    # A stack-triggered bonus-AD steroid (Darius' Noxian Might) only
    # covers part of the fight, so each swing is priced at the AD its own
    # timestamp saw. Without such a buff every swing_ad below is exactly
    # ``attack_damage``, as it always was.
    swing_bonus_ad = _auto_swing_bonus_ad(state, damage_ratio)
    auto_times = _auto_attack_timestamps(state)
    auto_events: list[dict[str, Any]] = []
    fiendhunter_events: list[dict[str, Any]] = []
    passive_true_events: list[dict[str, Any]] = []
    converted_auto_events: list[dict[str, Any]] = []
    converted_natural_crits = 0

    def converted_swing_damage(raw_ad: float, *, critical: bool) -> float:
        """Price one modified attack, reducing only its AD crit component."""
        assert conversion_info is not None
        adjusted_ad = raw_ad
        if critical:
            adjusted_ad *= state.target_critical_strike_damage_multiplier
        return _mitigate_basic_attack_swing(
            state,
            float(conversion_info.get("bonus_raw", 0.0)) + adjusted_ad,
            str(conversion_info.get("damage_type", "magic")),
        )

    for i in range(num_auto_attacks):
        attack_time = auto_times[i] if i < len(auto_times) else 0.0
        swing_ad = attack_damage + swing_bonus_ad(i)
        if override_replace_raw is not None:
            # Full auto replacement (Azir W): flat raw per attack, the
            # override's damage type, cannot crit — crit items, the
            # empowered-auto item branches, and Sundered Sky's forced
            # first-auto crit (game-verified: not applied by soldier
            # attacks at all) never apply.
            mitigated = _mitigate(
                override_replace_raw, override_damage_type, resists, state.magic_amp
            )
            auto_physical_total += mitigated
            non_crit_damage_per_hit = mitigated
            auto_events.append(
                {
                    "time": attack_time,
                    "damage_type": override_damage_type,
                    "damage": mitigated,
                }
            )
            continue
        is_empowered = ultimate_auto_buff is not None and i < empowered_autos
        is_sundered = first_auto_crit is not None and i == 0
        if deterministic:
            natural_crit = False
        else:
            natural_crit = random.random() < crit_chance

        if natural_crit:
            num_crits += 1

        deterministic_outcomes: list[tuple[float, float, bool]] | None = None
        sundered_normal_raw: float | None = None

        swing_window_ratio = (
            override_ad_ratio
            if q_window_end <= 0.0
            or (state.q_window_start <= attack_time < q_window_end)
            else 1.0
        )
        if override_crit_as_bonus:
            # Crit chance converts to bonus damage on every auto (e.g. Ashe).
            # Passive: "bonus damage equal to X% of the attack's damage."
            # The bonus is multiplicative with the attack's base damage ratio,
            # because each Q arrow individually applies Frost Shot.
            # Formula: AD * ad_ratio * (1 + crit_chance * (crit_mult - 1))
            # The per-swing ratio honors the Q active window.  Without IE: AD * ratio * (1 + crit_chance)
            # With IE:    AD * ratio * (1 + crit_chance * 1.30)
            bonus_crit_ratio = crit_multiplier - 1.0
            raw_phys = (
                swing_ad * swing_window_ratio * (1 + crit_chance * bonus_crit_ratio)
            )
            raw_true = 0.0
        elif is_empowered:
            if deterministic:
                # Expected-value for empowered autos
                raw_phys_crit = swing_ad * crit_multiplier
                raw_true_crit = raw_phys_crit * fh_true_ratio
                raw_phys_no = swing_ad * crit_multiplier * fh_reduced_crit
                raw_phys = crit_chance * raw_phys_crit + (1 - crit_chance) * raw_phys_no
                raw_true = crit_chance * raw_true_crit
                deterministic_outcomes = [
                    (crit_chance, raw_phys_crit, True),
                    (1.0 - crit_chance, raw_phys_no, True),
                ]
            elif natural_crit:
                # Full crit + bonus true damage
                raw_phys = swing_ad * crit_multiplier
                raw_true = raw_phys * fh_true_ratio
            else:
                # Reduced crit (80% of normal crit damage)
                raw_phys = swing_ad * crit_multiplier * fh_reduced_crit
                raw_true = 0.0
            fiendhunter_true_total += raw_true
        elif is_sundered:
            # Sundered Sky: forced crit at reduced ratio, overrides natural crit
            raw_phys = swing_ad * crit_multiplier * ss_reduced_crit
            # Calculate what the auto would have dealt without Sundered Sky
            if deterministic:
                normal_raw = swing_ad * (
                    crit_chance * crit_multiplier + (1 - crit_chance)
                )
            elif natural_crit:
                normal_raw = swing_ad * crit_multiplier
            else:
                normal_raw = swing_ad
            sundered_normal_raw = normal_raw
            raw_true = 0.0
        else:
            if deterministic:
                # Expected-value: blend crit and non-crit damage
                raw_phys = swing_ad * (
                    crit_chance * crit_multiplier + (1 - crit_chance)
                )
                deterministic_outcomes = [
                    (crit_chance, swing_ad * crit_multiplier, True),
                    (1.0 - crit_chance, swing_ad, False),
                ]
            elif natural_crit:
                raw_phys = swing_ad * crit_multiplier
            else:
                raw_phys = swing_ad
            raw_true = 0.0

        if deterministic_outcomes is not None:
            if i < converted_auto_limit:
                mitigated = sum(
                    weight * converted_swing_damage(outcome_raw, critical=critical)
                    for weight, outcome_raw, critical in deterministic_outcomes
                )
            else:
                mitigated = sum(
                    weight
                    * _mitigate_basic_attack_swing(
                        state, outcome_raw, critical_strike=critical
                    )
                    for weight, outcome_raw, critical in deterministic_outcomes
                )
        else:
            converted_critical = not override_crit_as_bonus and (
                natural_crit or is_empowered or is_sundered
            )
            if i < converted_auto_limit:
                mitigated = converted_swing_damage(
                    raw_phys,
                    critical=converted_critical,
                )
            else:
                mitigated = _mitigate_basic_attack_swing(
                    state,
                    raw_phys,
                    critical_strike=converted_critical,
                )

        if sundered_normal_raw is not None:
            if deterministic:
                normal_mitigated = crit_chance * (
                    converted_swing_damage(swing_ad * crit_multiplier, critical=True)
                    if i < converted_auto_limit
                    else _mitigate_basic_attack_swing(
                        state,
                        swing_ad * crit_multiplier,
                        critical_strike=True,
                    )
                ) + (1.0 - crit_chance) * (
                    converted_swing_damage(swing_ad, critical=False)
                    if i < converted_auto_limit
                    else _mitigate_basic_attack_swing(state, swing_ad)
                )
            else:
                normal_mitigated = (
                    converted_swing_damage(
                        sundered_normal_raw,
                        critical=natural_crit,
                    )
                    if i < converted_auto_limit
                    else _mitigate_basic_attack_swing(
                        state,
                        sundered_normal_raw,
                        critical_strike=natural_crit,
                    )
                )
            sundered_sky_damage_diff = mitigated - normal_mitigated
        if i < converted_auto_limit:
            converted_auto_total += mitigated
            converted_natural_crits += int(natural_crit)
            converted_auto_events.append(
                {
                    "time": attack_time,
                    "damage_type": str(conversion_info.get("damage_type", "magic")),
                    "damage": mitigated,
                }
            )
        else:
            auto_physical_total += mitigated
            auto_events.append(
                {
                    "time": attack_time,
                    "damage_type": "physical",
                    "damage": mitigated,
                }
            )
        if raw_true > 0:
            fiendhunter_events.append(
                {
                    "time": attack_time,
                    "damage_type": "true",
                    "damage": raw_true * basic_amp,
                }
            )
        # Champion rider: a share of this swing's PRE-mitigation damage
        # again as true damage (Corki P). Riding raw_phys carries the
        # attack's crit multiplier, exactly as the wiki describes.
        passive_true_total += raw_phys * passive_true_ratio
        if raw_phys * passive_true_ratio > 0:
            passive_true_events.append(
                {
                    "time": attack_time,
                    "damage_type": "true",
                    "damage": raw_phys * passive_true_ratio * basic_amp,
                }
            )

        # Track per-hit damage for crits vs non-crits (last value wins;
        # all crits deal the same and all non-crits deal the same)
        if deterministic:
            non_crit_damage_per_hit = mitigated
        elif natural_crit:
            crit_damage_per_hit = mitigated
        else:
            non_crit_damage_per_hit = mitigated

    # Apply basic damage amplification (e.g. Hexoptics C44 Magnification)
    fiendhunter_true_total *= basic_amp
    # Corki's true instance is basic damage in-game, like the physical one.
    passive_true_total *= basic_amp

    auto_total = auto_physical_total + converted_auto_total
    auto_damage_per_hit = auto_total / num_auto_attacks if num_auto_attacks > 0 else 0.0
    ordinary_auto_count = num_auto_attacks - converted_auto_limit
    ordinary_crits = max(0, num_crits - converted_natural_crits)
    num_non_crits = ordinary_auto_count - ordinary_crits

    auto_name = "Auto Attacks"
    auto_damage_type = "physical"
    if override_replace_raw is not None:
        auto_name = auto_attack_override.get("name", auto_name)
        auto_damage_type = override_damage_type

    breakdown["auto_attacks"] = {
        "name": auto_name,
        "count": ordinary_auto_count,
        "num_crits": ordinary_crits,
        "num_non_crits": num_non_crits,
        "crit_damage_per_hit": crit_damage_per_hit if ordinary_crits > 0 else None,
        "non_crit_damage_per_hit": (
            non_crit_damage_per_hit if num_non_crits > 0 else None
        ),
        "damage_per_hit": (
            auto_physical_total / ordinary_auto_count
            if ordinary_auto_count > 0
            else 0.0
        ),
        "total_damage": auto_physical_total,
        "damage_type": auto_damage_type,
        # ``auto_events`` also contains swings consumed by a champion-owned
        # empowered/modified attack row.  Those swings are accounted for in
        # that row (or forced cast entry), so keep this ledger aligned with
        # the ordinary-auto aggregate before certifying its event total.
        "damage_events": auto_events[:ordinary_auto_count],
        "event_phase": "auto",
    }
    if conversion_info is not None and converted_auto_limit > 0:
        breakdown["on_hit_ability_passive"] = {
            "name": str(conversion_info.get("name", "Modified attacks")),
            "count": converted_auto_limit,
            "damage_per_hit": converted_auto_total / converted_auto_limit,
            "total_damage": converted_auto_total,
            "damage_type": str(conversion_info.get("damage_type", "magic")),
            "damage_events": converted_auto_events,
            "event_phase": "auto",
            "detail": (
                f"{converted_auto_limit} modified basic attack"
                f"{'' if converted_auto_limit == 1 else 's'}; includes the swing"
            ),
        }
    if ultimate_auto_buff is not None and empowered_autos > 0:
        breakdown["auto_attacks"]["empowered_count"] = empowered_autos

    # Sundered Sky breakdown: show the damage difference on first auto.
    # Replaced autos (Azir soldiers) never consume Sundered Sky — no row.
    if (
        first_auto_crit is not None
        and num_auto_attacks > 0
        and override_replace_raw is None
    ):
        mitigated_diff = abs(sundered_sky_damage_diff)
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
            "damage_events": fiendhunter_events,
            "event_phase": "auto",
        }

    if passive_true_total > 0:
        breakdown["auto_attacks_true_damage"] = {
            "name": f"{passive_true_name} (true damage)",
            "count": num_auto_attacks,
            "damage_per_hit": passive_true_total / num_auto_attacks,
            "total_damage": passive_true_total,
            "damage_type": "true",
            "damage_events": passive_true_events,
            "event_phase": "auto",
        }

    # Add basic damage amp breakdown entry (informational — already applied)
    if basic_amp > 1.0:
        amp_effect = state.damage_effects.basic_amp
        amp_name = amp_effect.item_name if amp_effect is not None else "Basic Damage"
        basic_amp_bonus = (
            (auto_total + fiendhunter_true_total + passive_true_total)
            * (basic_amp - 1.0)
            / basic_amp
        ) + state.basic_amp_ability_bonus
        breakdown[f"basic_amp_{amp_name}"] = {
            "name": f"Damage Amplification ({amp_name})",
            "multiplier": basic_amp,
            "total_damage": basic_amp_bonus,
            "detail": "included in the auto attack / basic damage rows above",
            "informational": True,
        }

    # Double shot: second auto per attack at reduced AD (e.g. Akshan passive)
    double_shot_total = 0.0
    if double_shot_info and num_auto_attacks > 0:
        ds_ratio = double_shot_info.get("ad_ratio", 0.5)
        ds_crits = 0
        double_shot_events: list[dict[str, Any]] = []
        for i in range(num_auto_attacks):
            ds_ad = attack_damage * ds_ratio
            if deterministic:
                ds_crit = False
                event_damage = crit_chance * _mitigate_basic_attack_swing(
                    state,
                    ds_ad * crit_multiplier,
                    critical_strike=True,
                ) + (1.0 - crit_chance) * _mitigate_basic_attack_swing(state, ds_ad)
                double_shot_total += event_damage
                double_shot_events.append(
                    {
                        "time": auto_times[i] if i < len(auto_times) else 0.0,
                        "damage_type": "physical",
                        "damage": event_damage,
                        "event_precision": "exact",
                    }
                )
                continue
            else:
                ds_crit = random.random() < crit_chance
                if ds_crit:
                    ds_crits += 1
                    raw_ds = ds_ad * crit_multiplier
                else:
                    raw_ds = ds_ad
            event_damage = _mitigate_basic_attack_swing(
                state,
                raw_ds,
                critical_strike=ds_crit,
            )
            double_shot_total += event_damage
            double_shot_events.append(
                {
                    "time": auto_times[i] if i < len(auto_times) else 0.0,
                    "damage_type": "physical",
                    "damage": event_damage,
                    "event_precision": "exact",
                }
            )

        ds_non_crits = num_auto_attacks - ds_crits
        breakdown["double_shot"] = {
            "name": double_shot_info.get("name", "Double Shot"),
            "count": num_auto_attacks,
            "num_crits": ds_crits,
            "num_non_crits": ds_non_crits,
            "total_damage": double_shot_total,
            "damage_type": "physical",
            "damage_events": double_shot_events,
            "event_phase": "auto",
        }

    state.total_damage += (
        auto_total + fiendhunter_true_total + passive_true_total + double_shot_total
    )

    return AutoAttackResult(
        auto_damage_per_hit=auto_damage_per_hit,
        double_shot_info=double_shot_info,
    )


@dataclass
class OnHitResult:
    """Values produced by on-hit layering and consumed by later steps."""

    phantom_hit_count: int = 0  # auto-segment phantom hits only
    phantom_hit_autos: set[int] = field(default_factory=set)
    static_on_hit_per_hit: float = 0.0  # mitigated, for HP simulations
    # Same per-hit damage keyed by damage type (physical/magic/true) —
    # types the spellblade double-on-hit breakdown row exactly.
    static_on_hit_by_type: dict[str, float] = field(default_factory=dict)
    current_health_on_hit_avg: float = 0.0
    current_health_damage_type: str = "physical"
    has_current_health_on_hit: bool = False
    # Indices in the rotation's ON-HIT application sequence whose attack
    # fired a phantom hit — each grants one extra on-hit counter stack
    # (consumed by _add_single_proc_on_hits).
    phantom_ability_stack_positions: set[int] = field(default_factory=set)


def _armed_class_restricted_per_hits(
    state: FightState,
) -> tuple[item_effects.PerHitEffect, ...]:
    """The build's class-restricted on-hits this target class arms (P3-3M).

    A champion-class fight (the default and the only class every existing
    caller authors) arms nothing, so the auto stream is bit-identical to
    the pre-P3-3M engine. A minion-class fight arms exactly the branches
    whose sourced text names that class.
    """
    return tuple(
        effect
        for effect in state.damage_effects.class_restricted_per_hits
        if effect.target_class == state.target_class
    )


def _layer_on_hit_effects(
    state: FightState,
    autos: AutoAttackResult,
    rotation: RotationResult,
) -> OnHitResult:
    """Layer per-hit on-hit damage (items and abilities) onto the autos.

    Computes Guinsoo's Rageblade phantom hits centrally — they apply ALL
    on-hit effects an additional time — and counts double-shot extra
    applications. Constant-damage on-hit items and ability on-hits
    (e.g. Vayne W stacks, Viego passive) multiply per-hit damage by the
    total application count; BoRK is simulated per-auto against the
    target's decreasing current HP. Ability on-hits flagged
    ``count_ability_hits`` (e.g. Aurora P) also count the rotation's
    damaging ability hits toward their stack counter.

    A champion ``auto_attack_override`` may carry ``on_hit_effectiveness``
    (Azir soldiers: on-hit at 50%) — it scales every per-hit on-hit
    application here, including the BoRK simulation.
    """
    resists = state.resists
    breakdown = state.breakdown
    num_auto_attacks = state.num_auto_attacks
    magic_amp = state.magic_amp

    on_hit_effectiveness = _on_hit_effectiveness(state)

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
    # Phantom stacking is an ON-ATTACK cadence (item taxonomy), so
    # ability-carried applications that count as attacks (Bel'Veth E
    # slashes) lead the shared attack counter before the autos.
    phantom_effect = state.damage_effects.phantom_hit
    apps = rotation.ability_item_applications
    attack_app_indices: list[int] = []
    if phantom_effect is not None and apps:
        wants_on_attack = (
            item_effects.counter_trigger(phantom_effect.item_name) == "on_attack"
        )
        attack_app_indices = [
            i
            for i, app in enumerate(apps)
            if (app.on_attack if wants_on_attack else app.on_hit)
        ]
    ability_phantoms, result.phantom_hit_autos = _calculate_phantom_hits(
        num_auto_attacks, phantom_effect, leading_attacks=len(attack_app_indices)
    )
    result.phantom_hit_count = len(result.phantom_hit_autos)

    # Ability-segment phantom hits: re-apply the per-hit item effects
    # once at the firing attack's own effectiveness (a slash's 8-32%),
    # and grant one extra stack on the shared ON-HIT counters at that
    # hit's position (mapped below; consumed by the stacking-proc walk).
    if ability_phantoms:
        on_hit_seq_index = {}
        seq = 0
        for i, app in enumerate(apps):
            if app.on_hit:
                on_hit_seq_index[i] = seq
                seq += 1
        phantom_ability_damage = 0.0
        phantom_by_type: dict[str, float] = {}
        for position in ability_phantoms:
            app = apps[attack_app_indices[position]]
            applied = _ability_applied_on_hit_damage(
                state, app.effectiveness, app.target_hp
            )
            for dtype, amount in applied.items():
                phantom_by_type[dtype] = phantom_by_type.get(dtype, 0.0) + amount
            phantom_ability_damage += sum(applied.values())
            mapped = on_hit_seq_index.get(attack_app_indices[position])
            if mapped is not None:
                result.phantom_ability_stack_positions.add(mapped)
        if phantom_ability_damage > 0:
            assert phantom_effect is not None
            breakdown["on_hit_items_phantom"] = {
                "name": f"{phantom_effect.item_name} phantom hits (ability attacks)",
                "count": len(ability_phantoms),
                "total_damage": phantom_ability_damage,
                **_damage_type_fields(phantom_by_type),
            }
            on_hit_total += phantom_ability_damage

    # Double shot applies on-hit effects an additional time per auto
    double_shot_extra = num_auto_attacks if autos.double_shot_info else 0
    on_hit_hits = num_auto_attacks + result.phantom_hit_count + double_shot_extra

    # Every auto-segment on-hit application rides a timestamped swing, so
    # the rows built below can author exact per-swing damage events. One
    # entry per application, in the shared counter's order: the swing
    # itself, its Rageblade phantom re-application, then a double-shot
    # extra — all at that swing's authored time.
    swing_times = _auto_attack_timestamps(state)
    if len(swing_times) != num_auto_attacks:
        swing_times = []  # unresolvable schedule: rows stay coarse
    application_times: list[float] = []
    for auto_index, swing_time in enumerate(swing_times):
        application_times.append(swing_time)
        if auto_index in result.phantom_hit_autos:
            application_times.append(swing_time)
        if double_shot_extra:
            application_times.append(swing_time)

    def swing_event_row(
        times: list[float], damages: list[float], damage_type: str
    ) -> dict[str, Any]:
        """Row fields authoring one typed event per (time, damage) pair."""
        ordered = sorted(
            zip(times, damages),
            key=lambda pair: float(pair[0]),
        )
        return {
            "event_phase": "auto",
            "damage_events": [
                {"time": time, "damage": damage, "damage_type": damage_type}
                for time, damage in ordered
            ],
        }

    # Process fixed-formula per-hit effects. Current-health effects are
    # simulated below because each application changes the next one's input.
    # Class-restricted branches (P3-3M) join the same stream only when the
    # fight's target class arms them, so they ride the identical
    # mitigation, phantom/double-shot counting, breakdown row, and
    # per-swing event authoring as every other on-hit item.
    damage_inputs = _damage_inputs(state)
    for effect in (
        *state.damage_effects.per_hits,
        *_armed_class_restricted_per_hits(state),
    ):
        if effect.tracks_current_health:
            continue

        source = effect.source
        raw_per_hit = source.raw_damage(damage_inputs) * on_hit_effectiveness
        if raw_per_hit <= 0:
            continue

        per_hit = _mitigate(raw_per_hit, source.damage_type, resists, magic_amp)

        # All on-hit items get phantom hit bonus procs.
        hits = on_hit_hits
        item_damage = per_hit * hits
        on_hit_total += item_damage
        result.static_on_hit_per_hit += per_hit
        result.static_on_hit_by_type[source.damage_type] = (
            result.static_on_hit_by_type.get(source.damage_type, 0.0) + per_hit
        )

        breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "count": hits,
            "damage_per_hit": per_hit,
            "total_damage": item_damage,
            "damage_type": source.damage_type,
        }
        if application_times:
            breakdown[source.breakdown_key].update(
                swing_event_row(application_times, [per_hit] * hits, source.damage_type)
            )

    # Ability-carried on-hit effects can be timestamped from the same
    # accepted ability ledger that prices the cast.  This is required for
    # stack counters such as Aurora's Spirit Abjuration: a fractional
    # per-hit average would invent damage before the third stack exists.
    # Only the ability on-hit loop below reads these times, so a kit with
    # no ability-carried on-hit skips the ledger reconstruction entirely.
    ability_hit_times = (
        [
            float(event["time"])
            for event in _ordered_damage_events(
                state.breakdown,
                state.ability_damages,
                state.cast_order,
                cast_events=rotation.cast_events,
            )
            if event.get("phase") == "ability"
            and event.get("source_key") in state.ability_damages
        ]
        if any(
            ability_info.get("on_hit")
            for ability_info in state.ability_damages.values()
        )
        else []
    )
    combined_application_times = ability_hit_times + application_times

    # Process ability on-hit effects (Case 2: abilities that add damage per
    # auto attack, e.g. Viego passive % health on-hit). These are passed in
    # ability_damages with an "on_hit" key containing per-hit damage info.
    # Phantom hits also apply these an additional time.
    for ability_key, ability_info in state.ability_damages.items():
        on_hit_data = ability_info.get("on_hit")
        if not on_hit_data:
            continue
        if "proc_cooldown" in on_hit_data or "proc_window" in on_hit_data:
            continue  # scheduled current-health procs are simulated below
        counts_ability_hits = bool(on_hit_data.get("count_ability_hits"))
        carries_on_ability_on_hits = bool(on_hit_data.get("applies_on_ability_on_hits"))
        if (
            num_auto_attacks == 0
            and not counts_ability_hits
            and not carries_on_ability_on_hits
        ):
            continue

        raw_base = float(on_hit_data.get("damage_per_hit", 0.0))
        if raw_base <= 0:
            continue

        dmg_type = on_hit_data.get("damage_type", "magic")
        raw_per_hit = raw_base * on_hit_effectiveness
        per_hit = _mitigate(raw_per_hit, dmg_type, resists, magic_amp)

        hits = on_hit_hits + (rotation.total_ability_hits if counts_ability_hits else 0)

        # Some champion on-hits explicitly ride ability-carried on-hit
        # instances as well as ordinary attacks. Bel'Veth R is the canonical
        # case: Q and E each apply the ramping true damage through their own
        # effectiveness, while ambient autos use Death in Lavender's 75%.
        # Preserve the actual carrier order because hit k deals k times the
        # base value. Ability-fired and auto-fired Guinsoo phantoms are extra
        # applications immediately after their carrier; Akshan-style double
        # shots likewise add one application per ambient attack.
        carrier_effectiveness: list[float] | None = None
        carrier_times: list[float] | None = None
        leading_carrier_hits = 0
        if carries_on_ability_on_hits:
            carrier_effectiveness = []
            carrier_times = []
            on_hit_position = 0
            for app in apps:
                if not app.on_hit:
                    continue
                carrier_effectiveness.append(app.effectiveness)
                if app.time is not None:
                    carrier_times.append(float(app.time))
                else:
                    carrier_times = None
                if on_hit_position in result.phantom_ability_stack_positions:
                    carrier_effectiveness.append(app.effectiveness)
                    if carrier_times is not None:
                        carrier_times.append(float(app.time))
                on_hit_position += 1
            # Ability-carried applications have no authored timestamps
            # unless the carrier module supplied them.  While any lead
            # carrier is untimed, this row stays coarse rather than inventing
            # an average boundary.
            leading_carrier_hits = len(carrier_effectiveness)
            for auto_index in range(num_auto_attacks):
                carrier_effectiveness.append(on_hit_effectiveness)
                if carrier_times is not None:
                    if auto_index < len(application_times):
                        carrier_times.append(float(application_times[auto_index]))
                    else:
                        carrier_times = None
                if auto_index in result.phantom_hit_autos:
                    carrier_effectiveness.append(on_hit_effectiveness)
                    if carrier_times is not None:
                        if auto_index < len(application_times):
                            carrier_times.append(float(application_times[auto_index]))
                        else:
                            carrier_times = None
                if autos.double_shot_info:
                    carrier_effectiveness.append(on_hit_effectiveness)
                    if carrier_times is not None:
                        if auto_index < len(application_times):
                            carrier_times.append(float(application_times[auto_index]))
                        else:
                            carrier_times = None
            hits = len(carrier_effectiveness)

        # Availability-limited on-hits (Bard meeps: stock + recharge)
        # apply at most max_procs times; autos beyond the cap are plain.
        max_procs = on_hit_data.get("max_procs")
        if max_procs is not None:
            hits = min(hits, int(max_procs))

        stacks_required = on_hit_data.get("stacks_required", 0)
        ramping = bool(on_hit_data.get("ramping"))
        stack_ramp = on_hit_data.get("stack_ramp")

        # Per-swing events are authorable only when every counted hit is
        # an auto-segment application with an authored swing time —
        # ability-carried hits (leading carriers, shared auto+ability
        # counters) have no timestamps yet and keep the row coarse.
        stampable = (
            bool(application_times)
            and leading_carrier_hits == 0
            and not (counts_ability_hits and rotation.total_ability_hits > 0)
            and hits <= len(application_times)
        )
        carrier_stampable = (
            carrier_effectiveness is not None
            and carrier_times is not None
            and len(carrier_times) >= hits
        )
        if carrier_stampable:
            stampable = True
        ability_counter_stampable = (
            counts_ability_hits
            and rotation.total_ability_hits > 0
            and len(combined_application_times) >= hits
        )
        if ability_counter_stampable:
            stampable = True
        event_times: list[float] | None = None
        event_damages: list[float] | None = None
        if stack_ramp:
            # Stack-ramped on-hit (Orianna P): each hit lands at the
            # CURRENT stack count then adds a stack (capped), so hit k
            # deals per_hit + min(k, max_stacks) x per_stack. Stacks are
            # assumed never to drop mid-fight (sustained attacking).
            per_stack = _mitigate(
                float(stack_ramp["damage_per_stack"]) * on_hit_effectiveness,
                dmg_type,
                resists,
                magic_amp,
            )
            max_stacks = int(stack_ramp["max_stacks"])
            stacked_hits = sum(min(k, max_stacks) for k in range(hits))
            ability_on_hit_damage = per_hit * hits + per_stack * stacked_hits
            if stampable:
                # Hit k lands at the CURRENT stack count — its own value.
                event_times = application_times[:hits]
                event_damages = [
                    per_hit + min(k, max_stacks) * per_stack for k in range(hits)
                ]
        elif ramping:
            # Ramping proc k deals k x its base. When abilities can carry the
            # on-hit, each application has its own effectiveness; otherwise
            # the ordinary auto effectiveness is uniform. ``stacks_required``
            # remains supported for pre-26.15 every-Nth formulations.
            procs = hits // max(1, stacks_required)
            if carrier_effectiveness is not None and stacks_required <= 1:
                carrier_damages = [
                    _mitigate(
                        raw_base * effectiveness * stack, dmg_type, resists, magic_amp
                    )
                    for stack, effectiveness in enumerate(
                        carrier_effectiveness, start=1
                    )
                ]
                ability_on_hit_damage = sum(carrier_damages)
                if stampable:
                    # No leading carriers: the carrier order IS the
                    # auto-segment application order.
                    event_times = (
                        carrier_times[:hits]
                        if carrier_stampable
                        else application_times[:hits]
                    )
                    event_damages = carrier_damages
            else:
                ability_on_hit_damage = per_hit * procs * (procs + 1) / 2.0
                if stampable:
                    # Proc j fires on the application landing its Nth stack.
                    interval = max(1, stacks_required)
                    event_times = [
                        application_times[j * interval - 1] for j in range(1, procs + 1)
                    ]
                    event_damages = [per_hit * j for j in range(1, procs + 1)]
        elif stacks_required > 1 and counts_ability_hits:
            # Shared auto+ability stack counter (e.g. Aurora P): only
            # complete procs deal damage — partial stacks expire.
            ability_on_hit_damage = (
                per_hit * stacks_required * (hits // stacks_required)
            )
            if ability_counter_stampable:
                event_times = [
                    combined_application_times[j * stacks_required - 1]
                    for j in range(1, hits // stacks_required + 1)
                ]
                event_damages = [per_hit * stacks_required] * (hits // stacks_required)
        else:
            # Autos-only on-hit (e.g. Vayne W): smooth per-hit average.
            # The total includes partial stacks, so events are the same
            # per-swing shares — the ledger must sum to the row exactly.
            ability_on_hit_damage = per_hit * hits
            if stampable:
                event_times = application_times[:hits]
                event_damages = [per_hit] * hits
        on_hit_total += ability_on_hit_damage
        if max_procs is None and not ramping and not stack_ramp:
            static_share = per_hit
        elif on_hit_hits > 0:
            # Capped on-hits don't land on every auto — feed the HP
            # simulations (BoRK, spellblade doubling) the per-auto average.
            static_share = ability_on_hit_damage / on_hit_hits
        else:
            static_share = 0.0
        if static_share > 0:
            result.static_on_hit_per_hit += static_share
            result.static_on_hit_by_type[dmg_type] = (
                result.static_on_hit_by_type.get(dmg_type, 0.0) + static_share
            )

        ability_name = on_hit_data.get("name", f"{ability_key} (on-hit)")
        if stacks_required > 1:
            # Stack-based on-hit (e.g. Vayne W): display as procs.
            # Ramping procs escalate, so their per-proc figure is the
            # average (total / procs) rather than a fixed amount.
            proc_count = hits // stacks_required
            if ramping and proc_count > 0:
                damage_per_proc = ability_on_hit_damage / proc_count
            else:
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
            # Stack-ramped hits escalate, so their per-hit figure is the
            # average (total / hits) rather than the 0-stack base.
            breakdown[f"on_hit_ability_{ability_key}"] = {
                "name": ability_name,
                "count": hits,
                "damage_per_hit": (
                    ability_on_hit_damage / hits if stack_ramp and hits else per_hit
                ),
                "total_damage": ability_on_hit_damage,
                "damage_type": dmg_type,
            }
        if event_times is not None and event_damages is not None:
            breakdown[f"on_hit_ability_{ability_key}"].update(
                swing_event_row(event_times, event_damages, dmg_type)
            )

    # BoRK: simulate with decreasing target current HP per auto attack.
    # Phantom hit autos cause BoRK to proc twice (at different current HP).
    # Double shot (e.g. Akshan) also procs BoRK an extra time per auto.
    # First-auto packets are priced here as HP-only inputs; their damage row
    # and fight total remain owned by _add_single_proc_on_hits below.
    first_auto_damage_by_auto = _first_auto_damage_by_auto_for_health_walk(
        state,
        rotation,
        num_auto_attacks,
        swing_times,
        on_hit_effectiveness,
    )
    if current_health_effect is not None and num_auto_attacks > 0:
        (
            current_health_total,
            current_health_hits,
            current_health_hit_damages,
        ) = _simulate_current_health_on_hit(
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
            effectiveness=on_hit_effectiveness,
            first_auto_damage_by_auto=first_auto_damage_by_auto,
        )
        result.current_health_on_hit_avg = (
            current_health_total / current_health_hits
            if current_health_hits > 0
            else 0.0
        )
        result.current_health_damage_type = current_health_effect.source.damage_type
        on_hit_total += current_health_total

        source = current_health_effect.source
        breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "count": current_health_hits,
            "damage_per_hit": result.current_health_on_hit_avg,
            "total_damage": current_health_total,
            "damage_type": source.damage_type,
        }
        # The simulation walks the same application order the swing
        # schedule authored, so its per-hit values stamp one event each.
        if application_times and len(current_health_hit_damages) == len(
            application_times
        ):
            breakdown[source.breakdown_key].update(
                swing_event_row(
                    application_times,
                    current_health_hit_damages,
                    source.damage_type,
                )
            )

    # Scheduled current-health on-hits ride the fight's auto timeline and
    # read the target's decayed current HP per proc. Two schedules:
    # ``proc_cooldown`` (Jarvan IV's Martial Cadence) procs the first
    # auto, then the first auto at/after (last proc + per-target
    # cooldown); ``proc_window`` (Camille R's rider) procs every auto
    # landing inside the window after the ability is cast — so a fight
    # that never casts it (auto-only mode) gets nothing. Schedule-gated
    # procs don't land on every auto, which is why phantom hits / double
    # shots never add procs and why the proc stays out of
    # static_on_hit_per_hit (spellblade doubling and the BoRK simulation
    # must not re-apply it).
    if num_auto_attacks > 0:
        autos_per_second = state.attack_speed * state.auto_attack_uptime
        # Both proc schedules read the same authored swing times that stamp
        # their events; the uniform fallback only covers an unresolvable
        # schedule, whose rows stay coarse anyway.
        proc_schedule = swing_times or (
            [i / autos_per_second for i in range(num_auto_attacks)]
            if autos_per_second > 0
            else []
        )
        for ability_key, ability_info in state.ability_damages.items():
            on_hit_data = ability_info.get("on_hit")
            if not on_hit_data:
                continue
            if "proc_cooldown" in on_hit_data:
                proc_autos = _schedule_cooldown_procs(
                    proc_schedule, on_hit_data["proc_cooldown"]
                )
            elif "proc_window" in on_hit_data:
                if breakdown.get(ability_key, {}).get("casts", 0) < 1:
                    continue  # rider exists only after the ability is cast
                # The triggering auto at t=0 always fits a positive window.
                autos_in_window = max(
                    1,
                    sum(
                        1 for time in proc_schedule if time < on_hit_data["proc_window"]
                    ),
                )
                proc_autos = list(range(min(num_auto_attacks, autos_in_window)))
            else:
                continue
            if not proc_autos:
                continue
            proc_damages = _simulate_cooldown_current_health_procs(
                on_hit_data,
                state.target_health,
                num_auto_attacks,
                autos.auto_damage_per_hit,
                result.static_on_hit_per_hit + result.current_health_on_hit_avg,
                resists,
                magic_amp,
                proc_autos,
                effectiveness=on_hit_effectiveness,
            )
            proc_total = sum(proc_damages)
            on_hit_total += proc_total
            proc_damage_type = on_hit_data.get("damage_type", "physical")
            breakdown[f"on_hit_ability_{ability_key}"] = {
                "name": on_hit_data.get("name", f"{ability_key} (on-hit)"),
                "count": len(proc_autos),
                "damage_per_hit": proc_total / len(proc_autos),
                "total_damage": proc_total,
                "damage_type": proc_damage_type,
                "unit": "procs",
            }
            if swing_times:
                # Each proc rides one specific swing — stamp its time.
                breakdown[f"on_hit_ability_{ability_key}"].update(
                    swing_event_row(
                        [swing_times[i] for i in proc_autos],
                        proc_damages,
                        proc_damage_type,
                    )
                )

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
    mana_restored: float = 0.0
    self_healing: float = 0.0


def _spellblade_proc_times(
    rotation: RotationResult,
    effect: item_effects.SpellbladeEffect,
    procs: int,
) -> list[float]:
    """Weave-timed spellblade proc times from the accepted cast timeline.

    Each accepted cast arms one charge (the engine assumes charges
    persist through the item cooldown, as its proc pricing already
    does).  A charge is consumed one weave delay after the later of its
    arming cast and the cooldown's end, and the cooldown restarts at the
    consuming attack — matching the ``cooldown + weave_delay`` spacing
    the proc count was priced with. Returns ``[]`` when the accepted
    casts cannot reproduce the engine's priced proc count — the row then
    stays coarse rather than carrying an event list that contradicts its
    total.
    """
    if procs <= 0:
        return []
    cast_times = sorted(float(event["time"]) for event in rotation.cast_events)
    times: list[float] = []
    cooldown_ends = float("-inf")
    for cast_time in cast_times:
        if len(times) == procs:
            break
        proc_time = max(cast_time, cooldown_ends) + effect.weave_delay
        times.append(proc_time)
        cooldown_ends = proc_time + effect.cooldown
    return times if len(times) == procs else []


def _apply_spellblade_attack_speed(
    state: FightState, times: list[float]
) -> list[float]:
    """Apply Lich Bane's empowered-attack speed to authored swing times.

    The engine's swing timestamps represent attack impacts.  When a
    Spellblade proc is armed, the first authored swing at or after its
    weave-timed proc consumes the charge.  Lich Bane's sourced bonus attack
    speed shortens the interval immediately after that empowered impact;
    later swings then continue at the ordinary authored rate.  This keeps
    the existing attack-count contract intact while making every dependent
    on-hit/proc row read the same adjusted schedule.
    """
    bonus_percent = state.spellblade_attack_speed_percent
    proc_times = state.spellblade_proc_times
    if bonus_percent <= 0.0 or not proc_times or len(times) < 2:
        return times
    normal_rate = state.attack_speed * state.auto_attack_uptime
    buffed_rate = (
        state.attack_speed + state.attack_speed_ratio * bonus_percent / 100.0
    ) * state.auto_attack_uptime
    if normal_rate <= 0.0 or buffed_rate <= normal_rate:
        return times
    normal_interval = 1.0 / normal_rate
    buffed_interval = 1.0 / buffed_rate
    advance = normal_interval - buffed_interval
    adjusted = list(times)
    next_swing = 0
    for proc_time in proc_times:
        while next_swing < len(adjusted) and adjusted[next_swing] < proc_time:
            next_swing += 1
        if next_swing >= len(adjusted) - 1:
            break
        # The swing at ``next_swing`` consumes the charge; its faster
        # windup makes every later authored impact arrive ``advance`` sooner.
        for index in range(next_swing + 1, len(adjusted)):
            adjusted[index] -= advance
        next_swing += 1
    return adjusted


def _prepare_spellblade_attack_schedule(
    state: FightState, rotation: RotationResult
) -> None:
    """Prepare Lich Bane's proc timestamps before the auto stream is priced."""
    effect = state.damage_effects.spellblade
    if effect is None or effect.bonus_attack_speed_percent <= 0.0:
        return
    onhit_applications = [
        application
        for application in rotation.ability_item_applications
        if application.on_hit
    ]
    consuming_attacks = (
        state.num_auto_attacks + rotation.forced_basic_attacks + len(onhit_applications)
    )
    attack_limit = (
        consuming_attacks
        if state.num_auto_attacks > 0
        else rotation.forced_swing_casts + len(onhit_applications)
    )
    if attack_limit <= 0:
        return
    procs = min(
        rotation.total_ability_casts,
        1 + int(state.fight_duration_seconds / (effect.cooldown + effect.weave_delay)),
        attack_limit,
    )
    proc_times = _spellblade_proc_times(rotation, effect, procs)
    if len(proc_times) != procs:
        return
    state.spellblade_proc_times = tuple(proc_times)
    state.spellblade_attack_speed_percent = effect.bonus_attack_speed_percent


def _add_spellblade_true_rider(
    state: FightState,
    source: item_effects.DamageSource,
    raw_per_proc: float,
    procs: int,
    proc_times: list[float],
) -> None:
    """Add a champion's true-damage rider on spellblade procs (Corki P).

    The wiki special-cases spellblade effects into Hextech Munitions:
    each proc deals ``spellblade_bonus_true_ratio`` of its own
    PRE-mitigation damage again as true damage. This is ADDED ON TOP of
    the proc; its sibling ``spellblade_true_ratio`` (Camille Q2) instead
    CONVERTS that share of the proc out of the item's own damage type.
    The rider shares the procs' weave-timed events when they exist.
    """
    ratio = max(
        (
            info.get("spellblade_bonus_true_ratio", 0.0)
            for info in state.ability_damages.values()
        ),
        default=0.0,
    )
    if ratio <= 0 or procs <= 0:
        return

    rider_total = raw_per_proc * ratio * procs
    state.breakdown[f"{source.breakdown_key}_bonus_true"] = {
        "name": f"{source.display_name} (bonus true damage)",
        "count": procs,
        "damage_per_hit": rider_total / procs,
        "unit": "procs",
        "total_damage": rider_total,
        "damage_type": "true",
    }
    if len(proc_times) == procs:
        state.breakdown[f"{source.breakdown_key}_bonus_true"]["damage_events"] = [
            {
                "time": proc_time,
                "damage": rider_total / procs,
                "damage_type": "true",
            }
            for proc_time in proc_times
        ]
    state.total_damage += rider_total


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

    Spellblade procs on replaced autos (Azir soldiers) at the override's
    on-hit effectiveness (game-verified: Lich Bane procs at 50% damage).
    """
    resists = state.resists
    result = SpellbladeResult()

    effect = state.damage_effects.spellblade
    if effect is not None:
        result.item = effect.source.item_name
        result.expose_weakness_melee = effect.expose_weakness_melee
        result.expose_weakness_ranged = effect.expose_weakness_ranged

    # A spellblade charge is consumed by any basic attack — the auto
    # stream when one exists, plus attacks forced by empowered-auto
    # casts when it doesn't (Camille Q, Blitzcrank E in one-rotation) —
    # and by ability hits that apply item on-hits (wiki: spellblade can
    # be "applied by an ability that triggers on-hit effects" — Ezreal
    # Q, Bel'Veth Q). Without those, an auto-less fight showed zero
    # Sheen procs for the champions built around them.
    onhit_applications = [a for a in rotation.ability_item_applications if a.on_hit]
    consuming_attacks = (
        state.num_auto_attacks + rotation.forced_basic_attacks + len(onhit_applications)
    )
    if effect is not None and consuming_attacks > 0:
        source = effect.source
        sb_effectiveness = _on_hit_effectiveness(state)
        if state.num_auto_attacks == 0 and onhit_applications:
            # No auto stream: procs are consumed by the ability
            # applications (and any forced attacks). Assume procs land
            # on the highest-effectiveness consumers first — the same
            # first-lands assumption the true-conversion accounting
            # below makes.
            sb_effectiveness = max(
                [a.effectiveness for a in onhit_applications]
                + ([sb_effectiveness] if rotation.forced_basic_attacks else [])
            )
        raw_sb = source.raw_damage(_damage_inputs(state)) * sb_effectiveness
        effective_sb_cd = effect.cooldown + effect.weave_delay

        result.damage_per_proc = _mitigate(
            raw_sb, source.damage_type, resists, state.magic_amp
        )

        # Number of procs: limited by ability casts and cooldown. With no
        # auto stream the consuming hits are the attacks casts forced —
        # a charge is armed per cast, so a cast that forces a whole burst
        # (Jayce's 3 Hyper Charge attacks) still spends just one — plus
        # the on-hit ability applications (each is a real separate hit;
        # the cast cap already stops a multi-hit cast from double-spending).
        attack_limit = (
            consuming_attacks
            if state.num_auto_attacks > 0
            else rotation.forced_swing_casts + len(onhit_applications)
        )
        result.procs = min(
            rotation.total_ability_casts,
            1 + int(state.fight_duration_seconds / effective_sb_cd),
            attack_limit,
        )

        # True-damage conversion (Camille Q2): an entry flagged
        # ``spellblade_true_ratio`` converts the proc its empowered
        # attack consumes — that ratio of the proc becomes unmitigated
        # true damage, the rest keeps the item's own type. One converted
        # proc per cast of the flagged entry (assumes procs land on the
        # flagged casts first — exact whenever procs aren't starved).
        converted_ratio = 0.0
        converted = 0
        for key, info in state.ability_damages.items():
            ratio = info.get("spellblade_true_ratio", 0.0)
            if ratio > 0:
                converted_ratio = max(converted_ratio, ratio)
                converted += state.breakdown.get(key, {}).get("casts", 0)
        converted = min(converted, result.procs)
        converted_per_proc = raw_sb * converted_ratio + result.damage_per_proc * (
            1.0 - converted_ratio
        )

        plain = result.procs - converted
        sb_total = result.damage_per_proc * plain + converted_per_proc * converted

        # Weave-timed events: authored only when the accepted casts
        # reproduce the priced proc count, and only for unconverted
        # builds (the true-conversion split's proc-to-cast assignment
        # is an assumption, not a certified order).
        proc_times = _spellblade_proc_times(rotation, effect, result.procs)

        if plain > 0 or converted == 0:  # unconverted builds keep the row as-is
            state.breakdown[source.breakdown_key] = {
                "name": source.display_name,
                "count": plain,
                "damage_per_hit": result.damage_per_proc,
                "unit": "procs",
                "total_damage": result.damage_per_proc * plain,
                "damage_type": source.damage_type,
            }
            if converted == 0 and proc_times:
                state.breakdown[source.breakdown_key]["damage_events"] = [
                    {
                        "time": proc_time,
                        "damage": result.damage_per_proc,
                        "damage_type": source.damage_type,
                    }
                    for proc_time in proc_times
                ]
        if converted > 0:
            converted_by_type = {"true": raw_sb * converted_ratio * converted}
            if converted_ratio < 1.0:
                converted_by_type[source.damage_type] = (
                    result.damage_per_proc * (1.0 - converted_ratio) * converted
                )
            state.breakdown[f"{source.breakdown_key}_true"] = {
                "name": f"{source.display_name} (true conversion)",
                "count": converted,
                "damage_per_hit": converted_per_proc,
                "unit": "procs",
                "total_damage": converted_per_proc * converted,
                **_damage_type_fields(converted_by_type),
            }
        state.total_damage += sb_total
        _add_spellblade_true_rider(state, source, raw_sb, result.procs, proc_times)

        # Spellblade siblings are resolved from the same accepted proc event
        # as the damage.  They are informational resource/sustain outputs in
        # the damage calculator (the surrounding participant ledger owns
        # resource admission and health mutation), but are never silently
        # dropped from the item packet.
        stats = state.champion_stats
        if effect.mana_restore_base_ad_ratio or effect.mana_restore_crit_ratio:
            mana_per_proc = effect.mana_restore_base_ad_ratio * stats.get(
                "base_attack_damage", 0.0
            ) + effect.mana_restore_crit_ratio * min(
                stats.get("critical_strike_chance", 0.0) / 100.0, 1.0
            )
            result.mana_restored = mana_per_proc * result.procs
            state.breakdown[f"mana_{result.item}"] = {
                "name": f"{result.item} (Manaflow)",
                "count": result.procs,
                "proc_times": list(proc_times),
                "amount_per_proc": mana_per_proc,
                "total_amount": result.mana_restored,
                "unit": "mana",
            }
        if effect.self_heal_ap_ratio or effect.self_heal_bonus_health_ratio:
            heal_per_proc = effect.self_heal_ap_ratio * stats.get(
                "ability_power", 0.0
            ) + effect.self_heal_bonus_health_ratio * stats.get("bonus_health", 0.0)
            result.self_healing = heal_per_proc * result.procs
            state.breakdown[f"heal_{result.item}"] = {
                "name": f"{result.item} (self-heal)",
                "count": result.procs,
                "proc_times": list(proc_times),
                "amount_per_proc": heal_per_proc,
                "total_amount": result.self_healing,
                "unit": "health",
            }

    # ── Double on-hit from spellblade (Dusk and Dawn) ──
    if effect is not None and result.procs > 0:
        if effect.double_on_hit:
            result.double_on_hit_procs = result.procs
            extra_by_type = {
                dtype: amount * result.double_on_hit_procs
                for dtype, amount in on_hits.static_on_hit_by_type.items()
            }

            # Current-health extra procs use the fight's average per-hit damage.
            if on_hits.has_current_health_on_hit and state.num_auto_attacks > 0:
                ch_type = on_hits.current_health_damage_type
                extra_by_type[ch_type] = extra_by_type.get(ch_type, 0.0) + (
                    on_hits.current_health_on_hit_avg * result.double_on_hit_procs
                )

            extra_on_hit = sum(extra_by_type.values())
            if extra_on_hit > 0:
                state.breakdown[f"double_on_hit_{result.item}"] = {
                    "name": f"{result.item} (Double On-Hit)",
                    "count": result.double_on_hit_procs,
                    "damage_per_hit": extra_on_hit / result.double_on_hit_procs,
                    "unit": "procs",
                    "total_damage": extra_on_hit,
                    **_damage_type_fields(extra_by_type),
                }
                state.total_damage += extra_on_hit

    # Double shot on-hit stacking: each auto generates an extra on-hit
    # application, accelerating Kraken Slayer / Hullbreaker procs.
    if autos.double_shot_info:
        result.double_on_hit_procs += state.num_auto_attacks

    return result


def _periodic_damage_events(
    total_damage: float,
    damage_type: str,
    duration: float,
    interval: float,
) -> list[dict[str, float | str]]:
    """Split an aggregate periodic total into timestamped full/partial ticks."""
    if total_damage <= 0 or duration <= 0 or interval <= 0:
        return []
    events: list[dict[str, float | str]] = []
    full_ticks = int(duration / interval + 1e-9)
    damage_rate = total_damage / duration
    for index in range(full_ticks):
        events.append(
            {
                "time": (index + 1) * interval,
                "damage_type": damage_type,
                "damage": damage_rate * interval,
            }
        )
    remainder = duration - full_ticks * interval
    if remainder > 1e-9:
        events.append(
            {
                "time": duration,
                "damage_type": damage_type,
                "damage": damage_rate * remainder,
            }
        )
    if events:
        # Eliminate floating-point drift while preserving every tick's timing.
        emitted = sum(float(event["damage"]) for event in events)
        events[-1]["damage"] = float(events[-1]["damage"]) + total_damage - emitted
    return events


def _add_burn_damage(state: FightState, rotation: RotationResult) -> None:
    """Add burn/DoT item damage: burns, Immolate, and Unending Despair.

    Burns refresh on each ability hit (and on Malignance's Hatefog DoT),
    so the effective burn window stretches across the rotation's cast
    spread, and the final application resolves fully past the fight's
    end (refresh EVENTS stop with the last cast/DoT tick; the burn they
    lit does not).
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

        # Champion DoTs (e.g. Brand's Blaze) keep dealing ability
        # damage for their ``dot_duration`` tail after the applying
        # cast — every tick refreshes the burn. Ablaze re-applies on
        # each cast, so the tail extends from the LAST cast.
        champion_dot_tail = max(
            (info.get("dot_duration", 0.0) for info in ability_damages.values()),
            default=0.0,
        )
        # Other item DoTs (e.g. Malignance Hatefog) deal ability
        # damage that also refreshes burns.  Hatefog starts at R cast
        # (not at fight start), so its refresh window begins partway
        # through the cast_spread.
        # In timed mode, abilities recast on cooldown across the whole
        # fight — the last recast (rotation.last_cast_time) refreshes
        # the burn far beyond the GCD combo spread.
        dot_refresh_end = max(cast_spread, rotation.last_cast_time) + champion_dot_tail
        for ultimate_proc in state.damage_effects.ultimate_procs:
            if "R" in ability_damages:
                # R1 lands r_extra dashes (x0.5s each) before the last hit
                r_start = cast_spread - r_extra * inter_cast_delay
                hatefog_end = r_start + ultimate_proc.duration
                dot_refresh_end = max(dot_refresh_end, hatefog_end)

        # The final refresh's burn resolves in FULL — DoT consequences
        # of casts made within the fight tick out past its end, in both
        # modes. Capping timed mode at fight_duration priced the burn
        # as rate x fight_duration and undercounted short fights ~3x
        # (user-measured: Cassiopeia + Blackfire over 3s did ~90
        # in-game, the capped model said ~30).
        effective_burn_time = dot_refresh_end + burn_duration
        if effective_burn_time > burn_duration:
            burn_multiplier = effective_burn_time / burn_duration
            raw_burn *= burn_multiplier
        burn_mitigated = _mitigate(raw_burn, "magic", resists, state.magic_amp)

        state.breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": burn_mitigated,
            "damage_type": source.damage_type,
            "damage_events": _periodic_damage_events(
                burn_mitigated,
                source.damage_type,
                effective_burn_time,
                effect.tick_interval,
            ),
            "event_phase": "effect",
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
        if source.event_interval is not None:
            state.breakdown[source.breakdown_key]["damage_events"] = (
                _periodic_damage_events(
                    immolate_mitigated,
                    source.damage_type,
                    state.fight_duration_seconds,
                    source.event_interval,
                )
            )
            state.breakdown[source.breakdown_key]["event_phase"] = "effect"
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
            # Anguish begins its fixed cadence when combat starts.  The first
            # authored cast is the engine's sourced combat-start boundary; a
            # no-cast fight starts at zero rather than inventing a delay.
            combat_start = min(
                (float(event.get("time", 0.0)) for event in rotation.cast_events),
                default=0.0,
            )
            damage_per_proc = periodic_mitigated / procs if procs else 0.0
            damage_events = [
                {
                    "time": combat_start + (index + 1) * effect.interval,
                    "damage_type": source.damage_type,
                    "damage": damage_per_proc,
                    "event_precision": "exact",
                    "target_range_units": item_effects.required_effect_value(
                        "Unending Despair", "range_units"
                    ),
                    "target_scope": "enemy_champions_within_range",
                }
                for index in range(procs)
            ]
            row = {
                "name": source.display_name,
                "total_damage": periodic_mitigated,
                "damage_type": source.damage_type,
                "damage_events": damage_events,
                "event_phase": "effect",
            }
            if effect.self_heal_post_mitigation_multiplier > 0.0:
                row["self_heal_post_mitigation_multiplier"] = (
                    effect.self_heal_post_mitigation_multiplier
                )
            state.breakdown[source.breakdown_key] = row
            state.total_damage += periodic_mitigated


def _unique_ledger_hits(
    state: FightState,
    rotation: RotationResult,
    source_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Distinct positive damage instances from the ordered ledger, in order.

    ``source_keys`` narrows the walk to specific rows (ability casts for
    ability-triggered procs); ``None`` keeps every damage source.
    """
    ordered = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
    )
    unique_hits: list[dict[str, Any]] = []
    seen: set[tuple[str, int, float]] = set()
    for event in ordered:
        if event["damage"] <= 0:
            continue
        if source_keys is not None and event["source_key"] not in source_keys:
            continue
        identity = (
            event["source_key"],
            int(event["ordinal"]),
            float(event["time"]),
        )
        if identity in seen:
            continue
        seen.add(identity)
        unique_hits.append(event)
    return unique_hits


def _ability_damage_proc_triggers(
    state: FightState,
    rotation: RotationResult,
    effect: item_effects.CooldownProcEffect,
) -> list[dict[str, Any]]:
    """Schedule an ability-triggered proc onto legal damaging casts."""
    unique_hits = _unique_ledger_hits(state, rotation, set(state.cast_order))

    proc_triggers: list[dict[str, Any]] = []
    ready_at = float("-inf")
    for event in unique_hits:
        event_time = float(event["time"])
        if event_time + 1e-9 < ready_at:
            continue
        proc_triggers.append(event)
        if not effect.repeat_on_cooldown:
            break
        ready_at = event_time + effect.cooldown
    return proc_triggers


def _champion_damage_proc_triggers(
    state: FightState,
    rotation: RotationResult,
    effect: item_effects.CooldownProcEffect,
) -> list[dict[str, Any]]:
    """Schedule a damaging-a-champion proc onto the ordered ledger.

    Any positive damage event arms the proc (Hextech Alternator's Revved
    triggers on abilities, attacks, and item effects alike). Repeat procs
    wait out the cooldown; each completed attack windup between procs
    refunds ``on_attack_cooldown_refund`` seconds of it (Scout's
    Slingshot's Bullseye).
    """
    unique_hits = _unique_ledger_hits(state, rotation)
    swing_times = sorted(_auto_attack_timestamps(state))
    refund = effect.on_attack_cooldown_refund

    def cooldown_ready(last_proc_time: float, event_time: float) -> bool:
        elapsed = event_time - last_proc_time
        if refund > 0:
            attacks_between = sum(
                1 for swing in swing_times if last_proc_time < swing <= event_time
            )
            elapsed += refund * attacks_between
        return elapsed + 1e-9 >= effect.cooldown

    proc_triggers: list[dict[str, Any]] = []
    last_proc_time: float | None = None
    for event in unique_hits:
        event_time = float(event["time"])
        if last_proc_time is not None and not cooldown_ready(
            last_proc_time, event_time
        ):
            continue
        proc_triggers.append(event)
        if not effect.repeat_on_cooldown:
            break
        last_proc_time = event_time
    return proc_triggers


def _damage_threshold_trigger_time(
    state: FightState,
    rotation: RotationResult,
    effect: item_effects.CooldownProcEffect,
) -> float | None:
    """Time the rolling damage window first crosses the item's threshold.

    Walks the certified ledger built so far (abilities at cast times,
    autos at swing times, earlier authored item events) and returns the
    moment a ``damage_threshold`` trigger (Stormsurge's Squall) first
    held ``damage_threshold_ratio`` of the target's max health within
    ``damage_threshold_window`` seconds. Returns ``None`` when the model
    never crosses the threshold — the row then stays coarse (the engine
    still prices the proc, but cannot certify when it fires).
    """
    ratio = effect.damage_threshold_ratio
    window = effect.damage_threshold_window
    if ratio <= 0 or window <= 0:
        return None
    threshold = ratio * state.target_health
    events = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        light=True,
    )
    window_sum = 0.0
    window_start = 0
    for row in events:
        event_time = row[0][0]
        window_sum += row[1]
        while events[window_start][0][0] < event_time - window - 1e-9:
            window_sum -= events[window_start][1]
            window_start += 1
        if window_sum + 1e-6 >= threshold:
            return event_time
    return None


@dataclass(frozen=True, slots=True)
class _EclipseStackTrigger:
    """One validated Eclipse stack candidate."""

    time: float
    phase: int
    sequence: int
    precision: str
    target_id: str
    application_id: str


def _stacked_champion_proc_times(
    state: FightState,
    rotation: RotationResult,
    effect: item_effects.CooldownProcEffect,
) -> (
    tuple[
        list[dict[str, Any]],
        item_effects.WindowStackGate,
        list[dict[str, Any]],
    ]
    | None
):
    """Schedule a stack-gated champion proc from authored hit boundaries.

    Each ordinary cast instance can add one stack to one enemy champion.
    Positive direct-damage casts, typed control-only casts, forced attacks,
    and ambient attacks share one application-identity dedupe.  Damage and
    control from the same ordinary cast therefore feed the gate once.

    The reviewed Eclipse source also names DoT applications.  The generic
    ability packet does not identify the application boundary separately
    from its ticks.  Those candidates stay withheld with a named receipt;
    ticks never become guessed stack events.  Champion-specific exceptions
    that split one player cast into several Eclipse cast instances also stay
    outside this generic collector.
    """
    required = effect.stack_required
    window = effect.stack_window
    if required <= 1 or window <= 0.0:
        return None
    triggers: list[_EclipseStackTrigger] = []
    denials: list[dict[str, Any]] = []
    accepted_applications: set[tuple[str, str]] = set()
    event_cursors: dict[str, int] = {}
    forced_attack_events: list[tuple[float, str, str, str]] = []
    forced_event_slots: set[str] = set()

    def deny(
        reason: str,
        *,
        source_key: str,
        time: float,
        cast_id: object = None,
        target_id: object = None,
    ) -> None:
        source = item_effects.eclipse_trigger_source_receipt()
        receipt: dict[str, Any] = {
            "source": "Eclipse (Ever Rising Moon)",
            "reason": reason,
            "source_key": source_key,
            "time": time,
            "source_url": source.url,
            "source_revision_id": source.revision_id,
        }
        if isinstance(cast_id, str) and cast_id:
            receipt["cast_id"] = cast_id
        if isinstance(target_id, str) and target_id:
            receipt["target_id"] = target_id
        denials.append(receipt)

    def add_trigger(trigger: _EclipseStackTrigger) -> None:
        identity = (trigger.target_id, trigger.application_id)
        if identity in accepted_applications:
            return
        accepted_applications.add(identity)
        denials[:] = [
            denial
            for denial in denials
            if not (
                denial.get("cast_id") == trigger.application_id
                and denial.get("target_id") == trigger.target_id
            )
        ]
        triggers.append(trigger)

    for sequence, cast_event in enumerate(rotation.cast_events):
        if not isinstance(cast_event, Mapping):
            return None
        slot = cast_event.get("slot")
        event_time = _finite_numeric_receipt(cast_event.get("time"))
        if not isinstance(slot, str) or event_time is None or event_time < 0.0:
            return None
        cast_id = cast_event.get("cast_id")
        target_id = cast_event.get("target_id")
        if not isinstance(cast_id, str) or not cast_id.strip():
            deny(
                "application_identity_unavailable",
                source_key=slot,
                time=event_time,
                target_id=target_id,
            )
            continue
        if not isinstance(target_id, str) or not target_id.strip():
            deny(
                "target_identity_unavailable",
                source_key=slot,
                time=event_time,
                cast_id=cast_id,
            )
            continue
        row = state.breakdown.get(slot)
        if not isinstance(row, Mapping):
            continue
        raw_damage = row.get("total_damage", 0.0)
        if isinstance(raw_damage, bool) or not isinstance(raw_damage, (int, float)):
            return None
        if math.isfinite(float(raw_damage)) and float(raw_damage) > 0.0:
            ability_info = state.ability_damages.get(slot)
            if isinstance(ability_info, Mapping) and (
                ability_info.get("dot_duration") is not None
                or ability_info.get("dot_tick_interval") is not None
            ):
                deny(
                    "dot_application_timing_unavailable",
                    source_key=slot,
                    time=event_time,
                    cast_id=cast_id,
                    target_id=target_id,
                )
                continue
            trigger_time = event_time
            precision = _item_proc_precision(state, slot)
            authored_events = row.get("damage_events")
            if isinstance(authored_events, list):
                if row.get("basic_attack") and slot not in forced_event_slots:
                    forced_event_slots.add(slot)
                    for candidate in authored_events:
                        if not isinstance(candidate, Mapping):
                            return None
                        if not candidate.get("basic_attack"):
                            continue
                        candidate_time = _finite_numeric_receipt(candidate.get("time"))
                        candidate_damage = _finite_numeric_receipt(
                            candidate.get("damage")
                        )
                        if candidate_time is None or candidate_damage is None:
                            return None
                        if candidate_damage > 0.0:
                            forced_attack_events.append(
                                (
                                    candidate_time,
                                    str(candidate.get("event_precision", "exact")),
                                    target_id,
                                    f"{cast_id}:forced:{len(forced_attack_events) + 1}",
                                )
                            )
                cursor = event_cursors.get(slot, 0)
                while cursor < len(authored_events):
                    candidate = authored_events[cursor]
                    if not isinstance(candidate, Mapping):
                        return None
                    candidate_time = _finite_numeric_receipt(candidate.get("time"))
                    candidate_damage = _finite_numeric_receipt(candidate.get("damage"))
                    if candidate_time is None or candidate_damage is None:
                        return None
                    if candidate_time + 1e-9 < event_time:
                        cursor += 1
                        continue
                    if candidate_damage > 0.0:
                        trigger_time = candidate_time
                        precision = str(candidate.get("event_precision", "exact"))
                        cursor += 1
                        event_cursors[slot] = cursor
                        break
                    cursor += 1
                else:
                    return None
            # Ability phase precedes autos at the same timestamp.
            add_trigger(
                _EclipseStackTrigger(
                    time=trigger_time,
                    phase=0,
                    sequence=sequence,
                    precision=precision,
                    target_id=target_id,
                    application_id=cast_id,
                )
            )

    for control_sequence, control_event in enumerate(
        getattr(rotation, "control_events", ())
    ):
        if not isinstance(control_event, Mapping):
            return None
        source_key = control_event.get("source_key")
        event_time = _finite_numeric_receipt(control_event.get("time"))
        cast_id = control_event.get("application_id") or control_event.get("cast_id")
        target_id = control_event.get("target_id")
        if not isinstance(source_key, str) or event_time is None or event_time < 0.0:
            return None
        if not isinstance(cast_id, str) or not cast_id.strip():
            deny(
                "application_identity_unavailable",
                source_key=source_key,
                time=event_time,
                target_id=target_id,
            )
            continue
        if not isinstance(target_id, str) or not target_id.strip():
            deny(
                "target_identity_unavailable",
                source_key=source_key,
                time=event_time,
                cast_id=cast_id,
            )
            continue
        if (target_id, cast_id) in accepted_applications:
            continue
        ability_info = state.ability_damages.get(source_key)
        cc_kind = control_event.get("cc_kind")
        if (
            not isinstance(ability_info, Mapping)
            or ability_info.get("cc_reviewed") is not True
            or control_event.get("cc_reviewed") is not True
            or not isinstance(cc_kind, str)
            or not cc_kind.strip()
        ):
            deny(
                "cc_review_unavailable",
                source_key=source_key,
                time=event_time,
                cast_id=cast_id,
                target_id=target_id,
            )
            continue
        precision = control_event.get("event_precision")
        if not isinstance(precision, str) or not precision.strip():
            deny(
                "cc_application_timing_unavailable",
                source_key=source_key,
                time=event_time,
                cast_id=cast_id,
                target_id=target_id,
            )
            continue
        add_trigger(
            _EclipseStackTrigger(
                time=event_time,
                phase=0,
                sequence=len(rotation.cast_events) + control_sequence,
                precision=precision,
                target_id=target_id,
                application_id=cast_id,
            )
        )

    if len(forced_attack_events) != rotation.forced_basic_attacks:
        # A forced attack without a positive authored packet normally has no
        # certified landing boundary; retain the explicit coarse fallback
        # rather than counting an invented cast-time stack.  Exception: a
        # CERTIFIED forced-attack cast (single_hit / auto_stack_proc) has no
        # sub-cast offsets — its explicit cast boundary IS the swing, so it
        # contributes one trigger at the certified precision (E9-BIS).
        if rotation.forced_basic_attacks > 0:
            missing = rotation.forced_basic_attacks - len(forced_attack_events)
            for sequence, cast_event in enumerate(rotation.cast_events):
                if missing <= 0:
                    break
                if not isinstance(cast_event, Mapping):
                    return None
                slot = cast_event.get("slot")
                if not isinstance(slot, str):
                    return None
                row = state.breakdown.get(slot)
                if (
                    not isinstance(row, Mapping)
                    or float(row.get("total_damage", 0.0)) <= 0
                ):
                    continue
                # A forced-attack row whose own ``basic_attack`` flag IS the
                # swing receipt (Jayce Hyper Charge, Blitzcrank Power Fist)
                # certifies its cast boundary as the hit.  Regular certified
                # ability casts already contributed one stack in the main
                # loop; only basic_attack rows satisfy the forced-swing count.
                # An empowered-auto cast rides ``hits`` swings (Hyper Charge
                # forces 3), each a distinct Eclipse stack at the cast time.
                if row.get("basic_attack") is not True:
                    continue
                ability_info = state.ability_damages.get(slot)
                empower = (
                    ability_info.get("empowers_next_auto")
                    if isinstance(ability_info, Mapping)
                    else None
                )
                hits = _empower_hits(empower) if empower is not None else 1
                cast_time = _finite_numeric_receipt(cast_event.get("time")) or 0.0
                cast_id = cast_event.get("cast_id")
                target_id = cast_event.get("target_id")
                if (
                    not isinstance(cast_id, str)
                    or not cast_id.strip()
                    or not isinstance(target_id, str)
                    or not target_id.strip()
                ):
                    return None
                for hit_index in range(hits):
                    forced_attack_events.append(
                        (
                            cast_time,
                            "exact",
                            target_id,
                            f"{cast_id}:forced:{hit_index + 1}",
                        )
                    )
                missing -= hits
            if missing > 0:
                return None
    for index, (time, precision, target_id, application_id) in enumerate(
        forced_attack_events
    ):
        add_trigger(
            _EclipseStackTrigger(
                time=time,
                phase=1,
                sequence=len(triggers) + index,
                precision=precision,
                target_id=target_id,
                application_id=application_id,
            )
        )

    swing_times = _auto_attack_timestamps(state) if state.num_auto_attacks > 0 else []
    if state.num_auto_attacks > 0 and len(swing_times) != state.num_auto_attacks:
        return None
    auto_row = state.breakdown.get("auto_attacks")
    auto_damage = (
        auto_row.get("total_damage", 0.0) if isinstance(auto_row, Mapping) else 0.0
    )
    if state.num_auto_attacks > 0:
        if isinstance(auto_damage, bool) or not isinstance(auto_damage, (int, float)):
            return None
        if math.isfinite(float(auto_damage)) and float(auto_damage) > 0.0:
            offset = len(triggers)
            target_id = f"target:{state.roster_target_index}"
            for index, time in enumerate(swing_times):
                add_trigger(
                    _EclipseStackTrigger(
                        time=time,
                        phase=1,
                        sequence=offset + index,
                        precision="exact",
                        target_id=target_id,
                        application_id=f"auto:{index + 1}",
                    )
                )

    triggers.sort(key=lambda row: (row.time, row.phase, row.sequence))
    # The stack/trigger timing is kernel-owned (state_lifecycle): the gate
    # records every gain/window-expiry/proc/per-target-cooldown-start
    # transition in the same (time, phase, sequence) total order the walk
    # feeds, and returns the completed pairs.  The damage formula stays
    # here with the engine.
    gate = item_effects.eclipse_trigger_gate(effect)
    proc_events: list[dict[str, Any]] = []
    for trigger in triggers:
        for proc in gate.feed(
            trigger.time,
            sequence=trigger.sequence,
            precision=trigger.precision,
            target=trigger.target_id,
        ):
            proc_events.append(
                {
                    "time": proc.time,
                    "damage": 0.0,
                    "damage_type": effect.source.damage_type,
                    "event_precision": proc.precision,
                    "target_id": proc.target,
                }
            )
    return proc_events, gate, denials


def _charged_proc_target_share(
    state: FightState,
    source: item_effects.DamageSource,
) -> float:
    """Return this roster target's share of one charged proc application."""
    if source.multi_target_charges <= 0:
        return 1.0
    target_count = max(1, state.roster_target_count)
    target_index = max(0, state.roster_target_index)
    unique_targets = min(target_count, source.multi_target_charges)
    if target_index == 0:
        desired_multiplier = (
            1.0
            + max(
                0,
                source.multi_target_charges - unique_targets,
            )
            * source.repeated_target_multiplier
        )
    elif target_index < unique_targets:
        desired_multiplier = 1.0
    else:
        desired_multiplier = 0.0
    return desired_multiplier / source.single_target_multiplier


def _add_item_proc_damage(
    state: FightState,
    rotation: RotationResult,
) -> None:
    """Add proc-type item damage and ultimate-triggered procs (Malignance)."""
    resists = state.resists

    for effect in state.damage_effects.cooldown_procs:
        if effect.late_phase:
            continue
        source = effect.source
        if effect.trigger == "ability_damage":
            proc_triggers = _ability_damage_proc_triggers(state, rotation, effect)
        elif effect.trigger == "champion_damage":
            proc_triggers = _champion_damage_proc_triggers(state, rotation, effect)
        else:
            proc_triggers = []
        if (
            effect.trigger in {"ability_damage", "champion_damage"}
            and not proc_triggers
        ):
            continue
        procs = (
            len(proc_triggers)
            if proc_triggers
            else (
                1 + int(state.fight_duration_seconds / effect.cooldown)
                if effect.repeat_on_cooldown
                else 1
            )
        )
        # A damage-threshold trigger (Stormsurge) fires once, at the
        # ledger moment the rolling burst window first fills.  Resolve
        # the time before this row lands in the breakdown it walks.
        threshold_time = (
            _damage_threshold_trigger_time(state, rotation, effect)
            if effect.trigger == "damage_threshold" and procs == 1
            else None
        )
        if effect.trigger == "damage_threshold" and threshold_time is None:
            # A threshold-gated proc is conditional damage, not a guaranteed
            # cast-boundary packet.  If the certified rolling window never
            # reaches the sourced threshold, the proc never fires and must
            # not inflate the result or downgrade the frontend timeline.
            continue
        raw_per_proc = source.raw_damage(_damage_inputs(state))
        base_mitigated_per_proc = _mitigate(
            raw_per_proc, source.damage_type, resists, state.magic_amp
        )

        # Stormsurge and Zaz'Zak deal ability damage — amplified by
        # Actualizer.  Timestamped trigger receipts split the amp at the
        # explicit expiry boundary; an un-timestamped proc retains the
        # direct-engine active assumption.
        target_share = _charged_proc_target_share(state, source)
        event_damages: list[float] = []
        if proc_triggers:
            for trigger in proc_triggers:
                trigger_time = float(trigger["time"])
                amp = (
                    state.ability_amp
                    if source.is_ability_damage
                    and (
                        state.actualizer_active_until <= 0.0
                        or trigger_time
                        < state.actualizer_active_until - _CAST_SCHEDULE_EPS
                    )
                    else 1.0
                )
                event_damages.append(base_mitigated_per_proc * amp * target_share)
            proc_mitigated = sum(event_damages)
            mitigated_per_proc = (
                sum(event_damages) / len(event_damages) if event_damages else 0.0
            )
        else:
            amp = state.ability_amp if source.is_ability_damage else 1.0
            if threshold_time is not None and state.actualizer_active_until > 0.0:
                if threshold_time >= state.actualizer_active_until - _CAST_SCHEDULE_EPS:
                    amp = 1.0
            mitigated_per_proc = base_mitigated_per_proc * amp * target_share
            proc_mitigated = mitigated_per_proc * procs

        state.breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": proc_mitigated,
            "damage_type": source.damage_type,
        }
        if proc_triggers:
            state.breakdown[source.breakdown_key]["damage_events"] = [
                {
                    "time": float(trigger["time"]),
                    "timeline_order": float(trigger["order"]) + 0.5,
                    "damage": event_damages[index],
                    "damage_type": source.damage_type,
                }
                for index, trigger in enumerate(proc_triggers)
            ]
        elif threshold_time is not None:
            state.breakdown[source.breakdown_key]["damage_events"] = [
                {
                    "time": threshold_time,
                    "damage": proc_mitigated,
                    "damage_type": source.damage_type,
                }
            ]
        if source.multi_target_charges:
            state.breakdown[source.breakdown_key]["targeting"] = {
                "kind": "charged_bounce",
                "charges": source.multi_target_charges,
                "repeat_multiplier": source.repeated_target_multiplier,
                "single_target_multiplier": source.single_target_multiplier,
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
        # The zone opens at R1: stamp the proc at the cast timeline's
        # first R cast.  Without a timestamped R cast the row stays
        # coarse (a stat-only R never reaches here — r_info exists).
        r_cast_times = [
            float(event["time"])
            for event in rotation.cast_events
            if event.get("slot") == "R"
        ]
        if r_cast_times:
            state.breakdown[source.breakdown_key]["damage_events"] = [
                {
                    "time": min(r_cast_times),
                    "damage": ult_proc_mitigated,
                    "damage_type": source.damage_type,
                }
            ]
        state.total_damage += ult_proc_mitigated


def _damaging_cast_times(state: FightState, rotation: RotationResult) -> list[float]:
    """Chronological cast times of accepted DAMAGING ability casts.

    Zero-damage casts (stat-buff ultimates) are excluded — they apply no
    keystone stacks and hurl no comets. Instances the engine cannot
    timestamp or certify are not counted — item-effect applications,
    recast instances beyond the first, and pure crowd-control casts (CC
    application stacks in game, but the engine carries no CC metadata).
    Omitting an instance can only delay a proc, never invent one.
    """
    damaging_slots = {
        slot
        for slot, entry in state.ability_damages.items()
        if float(entry.get("total_raw", 0.0)) > 0
    }
    return sorted(
        float(event["time"])
        for event in rotation.cast_events
        if event.get("slot") in damaging_slots
    )


def _keystone_instance_times(
    state: FightState, rotation: RotationResult
) -> list[float]:
    """Chronological damage-instance times the keystone stack counter sees.

    One instance per accepted damaging ability cast (wiki: up to one
    stack per cast instance) plus one per simulated auto swing.
    """
    times = _damaging_cast_times(state, rotation)
    times.extend(_auto_attack_timestamps(state))
    return sorted(times)


def _record_keystone_proc_row(
    state: FightState,
    effect: (
        "rune_effects.KeystoneProcEffect"
        " | rune_effects.KeystoneProcAmpEffect"
        " | rune_effects.KeystoneAbilityProcEffect"
        " | rune_effects.KeystoneAeryEffect"
    ),
    proc_times: list[float],
) -> None:
    """Price one keystone's proc damage and record its breakdown row.

    Every proc-class keystone row looks alike — leveled adaptive damage
    priced once, mitigated, one timestamped event per proc — so the
    shape lives here, shared by every stack-walking keystone.
    """
    raw_per_proc = effect.raw_damage(_damage_inputs(state))
    damage_type = effect.damage_type(state.champion_stats)
    mitigated_per_proc = _mitigate(
        raw_per_proc, damage_type, state.resists, state.magic_amp
    )
    total = mitigated_per_proc * len(proc_times)
    state.breakdown[effect.breakdown_key] = {
        "name": effect.display_name,
        "total_damage": total,
        "damage_type": damage_type,
        "count": len(proc_times),
        "event_phase": "effect",
        "damage_events": [
            {
                "time": proc_time,
                "damage": mitigated_per_proc,
                "damage_type": damage_type,
            }
            for proc_time in proc_times
        ],
    }
    state.total_damage += total


def _add_keystone_damage(state: FightState, rotation: RotationResult) -> None:
    """Add keystone rune proc damage from the fight's real instance stream.

    Walks the timestamped instances with the keystone's sourced stack
    window: a stack expires ``stack_window_seconds`` after it was applied,
    so reaching ``stacks_required`` live stacks means that many instances
    landed within one window. Procs start the cooldown, clear the stacks,
    and suppress new stacks until the keystone is ready again (runes do
    not stack while on cooldown). Each proc is priced once and recorded
    as a timestamped damage event for the ledger and timeline consumers.
    """
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneProcEffect):
        return
    proc_times: list[float] = []
    live_stacks: list[float] = []
    ready_at = 0.0
    for instance_time in _keystone_instance_times(state, rotation):
        if instance_time < ready_at:
            continue
        live_stacks = [
            applied
            for applied in live_stacks
            if instance_time - applied < effect.stack_window_seconds
        ]
        live_stacks.append(instance_time)
        if len(live_stacks) >= effect.stacks_required:
            proc_times.append(instance_time + effect.proc_delay_seconds)
            ready_at = instance_time + effect.cooldown_seconds
            live_stacks = []
    if not proc_times:
        return
    _record_keystone_proc_row(state, effect, proc_times)


def _add_keystone_ability_proc_damage(
    state: FightState, rotation: RotationResult
) -> None:
    """Add ability-cast keystone proc damage (Arcane Comet-class).

    Every accepted damaging ability cast hurls the proc when the rune is
    off its leveled cooldown; the damage event lands after the sourced
    flight delay. Basic attacks never trigger this class, and the
    engine's DoT ticks are not cast instances — damage over time neither
    triggers nor extends anything here (unlike the Liandry's burn
    family). Each proc is priced at the compiled assumed travel distance
    and assumed to land; both assumptions are disclosed in the notes.
    """
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneAbilityProcEffect):
        return
    cooldown = effect.cooldown_at(state.level)
    proc_times: list[float] = []
    ready_at = 0.0
    for cast_time in _damaging_cast_times(state, rotation):
        if cast_time < ready_at:
            continue
        proc_times.append(cast_time + effect.proc_delay_seconds)
        ready_at = cast_time + cooldown
    if not proc_times:
        # A selected keystone that never fires must say so — only
        # damaging ability casts trigger it, so autos-only fights get zero.
        state.notes.append(
            f"{effect.keystone_name} never procced: the simulated fight "
            "cast no damaging abilities."
        )
        return
    _record_keystone_proc_row(state, effect, proc_times)
    state.notes.append(
        f"{effect.keystone_name} assumes every comet lands after a "
        f"{effect.assumed_travel_distance:g}-unit flight "
        f"(+{effect.distance_amp_ratio * 100:.0f}% distance damage), never dodged."
    )


def _aery_trigger_times(state: FightState, rotation: RotationResult) -> list[float]:
    """Return one timestamp per accepted damaging Aery signal source.

    Ability casts and basic attacks use their certified streams.  Remaining
    timed damage rows are item effects.  Keystone and amplifier rows cannot
    signal Aery themselves, so they stay outside this trigger stream.
    """
    times = _damaging_cast_times(state, rotation)
    times.extend(_auto_attack_timestamps(state))
    for event in _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
    ):
        if float(event.get("damage", 0.0) or 0.0) <= 0.0:
            continue
        if event.get("is_ability") or event.get("basic_attack"):
            continue
        source_key = str(event.get("source_key", ""))
        if _is_auto_stream_key(source_key) or source_key.startswith(
            ("keystone_", "damage_amp_")
        ):
            continue
        times.append(float(event.get("time", 0.0)))
    return sorted(times)


def _add_keystone_aery_damage(state: FightState, rotation: RotationResult) -> None:
    """Add Summon Aery damage with its sourced flight and linger gate."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneAeryEffect):
        return
    proc_times: list[float] = []
    ready_at = 0.0
    for trigger_time in _aery_trigger_times(state, rotation):
        if trigger_time < ready_at:
            continue
        proc_times.append(trigger_time + effect.damage_flight_seconds)
        # The wiki gives a target linger but gives no fixed return travel
        # duration.  The sourced linger boundary is the deterministic lower
        # bound for the next signal and is disclosed in the fight notes.
        ready_at = trigger_time + effect.damage_flight_seconds + effect.linger_seconds
    if not proc_times:
        state.notes.append(
            f"{effect.keystone_name} never procced: the simulated fight "
            "had no accepted damaging signal."
        )
        return
    _record_keystone_proc_row(state, effect, proc_times)
    state.notes.append(
        f"{effect.keystone_name} uses sourced {effect.damage_flight_seconds:g}-second "
        f"damage flight and {effect.linger_seconds:g}-second linger; return travel "
        "is movement-dependent, so the next signal uses the sourced linger boundary."
    )


def _aftershock_trigger_events(
    state: FightState, rotation: RotationResult
) -> list[dict[str, Any]]:
    """Return one event per accepted immobilizing cast for Aftershock.

    Reviewed control events are preferred. Damage packets carry the same
    control metadata for modules whose hit part owns the immobilize, so those
    packets fill the gaps. A control event and its damage packet share one
    source/time identity and must not trigger twice.
    """
    triggers: list[dict[str, Any]] = []
    seen: set[tuple[str, float, str]] = set()

    def add(event: Mapping[str, Any]) -> None:
        kind = str(event.get("cc_kind", "")).lower()
        duration = float(event.get("cc_duration", 0.0) or 0.0)
        if kind not in ACTION_BLOCKING_CC_KINDS or duration <= 0.0:
            return
        try:
            time = float(event.get("time", 0.0) or 0.0)
        except (TypeError, ValueError):
            return
        key = (str(event.get("source_key", "")), round(time, 9), kind)
        if key in seen:
            return
        seen.add(key)
        triggers.append(
            {
                "time": time,
                "source_key": str(event.get("source_key", "")),
                "source": str(event.get("source", event.get("source_key", ""))),
                "cc_kind": kind,
                "cc_duration": duration,
                "sequence": int(event.get("sequence", 0) or 0),
            }
        )

    for event in rotation.control_events:
        if isinstance(event, Mapping):
            add(event)
    for event in _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
    ):
        add(event)
    return sorted(triggers, key=lambda event: (event["time"], event["sequence"]))


def _add_keystone_aftershock_damage(
    state: FightState, rotation: RotationResult
) -> None:
    """Add Aftershock's delayed magic shockwave from immobilizing casts."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneAftershockEffect):
        return
    triggers = _aftershock_trigger_events(state, rotation)
    if not triggers:
        state.notes.append(
            f"{effect.keystone_name} never procced: the simulated fight had no "
            "accepted immobilizing control event."
        )
        return
    raw_damage = effect.shockwave_raw_damage(state.level, state.champion_stats)
    mitigated_damage = _mitigate(raw_damage, "magic", state.resists, state.magic_amp)
    ready_at = 0.0
    proc_events: list[dict[str, Any]] = []
    for trigger in triggers:
        trigger_time = float(trigger["time"])
        if trigger_time + 1e-9 < ready_at:
            continue
        proc_events.append(
            {
                "time": trigger_time + effect.duration_seconds,
                "damage": mitigated_damage,
                "raw_damage": raw_damage,
                "damage_type": "magic",
                "trigger_time": trigger_time,
                "trigger_source": trigger["source"],
                "cc_kind": trigger["cc_kind"],
                "shockwave_radius": effect.shockwave_radius,
            }
        )
        ready_at = trigger_time + effect.cooldown_seconds
    if not proc_events:
        state.notes.append(
            f"{effect.keystone_name} never procced: every immobilizing event "
            f"landed during its {effect.cooldown_seconds:g}-second cooldown."
        )
        return
    state.breakdown[effect.breakdown_key] = {
        "name": effect.display_name,
        "total_damage": mitigated_damage * len(proc_events),
        "damage_type": "magic",
        "count": len(proc_events),
        "event_phase": "effect",
        "damage_events": proc_events,
    }
    state.total_damage += mitigated_damage * len(proc_events)
    state.notes.append(
        f"{effect.keystone_name} uses a sourced {effect.duration_seconds:g}-second "
        f"resistance window, {effect.cooldown_seconds:g}-second cooldown, and "
        f"{effect.shockwave_radius:g}-unit shockwave radius."
    )


def _dark_harvest_trigger_event(event: Mapping[str, Any]) -> bool:
    """Return whether one ordered event is a certified non-proc hit.

    Ability casts and basic attacks carry the runtime's direct-damage
    receipts. Other effect rows need a source-specific proc classification,
    so they stay outside this threshold scan until they carry one.
    """
    if event.get("pet_damage") or event.get("dark_harvest_eligible"):
        return True
    return str(event.get("phase", "")) in {"ability", "auto"}


def _add_keystone_dark_harvest(state: FightState, rotation: RotationResult) -> None:
    """Add Dark Harvest procs from the ordered live-health event walk."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneDarkHarvestEffect):
        return

    base_events = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
    )
    if not base_events:
        state.notes.append(
            f"{effect.keystone_name} never procced: the simulated fight "
            "had no timestamped damage events."
        )
        return

    damage_type = effect.damage_type(state.champion_stats)
    target_health = max(0.0, float(state.target_health))
    threshold = target_health * effect.health_threshold_ratio
    ready_at = 0.0
    souls = 0
    source_index = 0
    pending: list[dict[str, Any]] = []
    proc_events: list[dict[str, Any]] = []
    skipped_after_death = 0

    def queue_proc(trigger_time: float) -> None:
        nonlocal ready_at
        raw_damage = effect.raw_damage(_damage_inputs(state), souls)
        mitigated_damage = _mitigate(
            raw_damage, damage_type, state.resists, state.magic_amp
        )
        pending.append(
            {
                "time": trigger_time + effect.proc_delay_seconds,
                "trigger_time": trigger_time,
                "souls": souls,
                "raw_damage": raw_damage,
                "damage": mitigated_damage,
            }
        )
        ready_at = trigger_time + effect.cooldown_seconds

    while source_index < len(base_events) or pending:
        next_source = (
            base_events[source_index] if source_index < len(base_events) else None
        )
        pending.sort(key=lambda item: float(item["time"]))
        next_proc = pending[0] if pending else None
        source_time = (
            float(next_source.get("time", 0.0)) if next_source is not None else math.inf
        )
        proc_time = float(next_proc["time"]) if next_proc is not None else math.inf

        if next_source is not None and source_time <= proc_time:
            event = next_source
            source_index += 1
            if target_health <= 0.0:
                continue
            damage = max(0.0, float(event.get("damage", 0.0) or 0.0))
            if (
                damage > 0.0
                and _dark_harvest_trigger_event(event)
                and target_health < threshold
                and source_time + 1e-9 >= ready_at
            ):
                queue_proc(source_time)
            target_health = max(0.0, target_health - damage)
            continue

        proc = pending.pop(0)
        if target_health <= 0.0:
            skipped_after_death += 1
            continue
        proc_events.append(
            {
                "time": float(proc["time"]),
                "damage": float(proc["damage"]),
                "raw_damage": float(proc["raw_damage"]),
                "damage_type": damage_type,
                "trigger_time": float(proc["trigger_time"]),
                "souls": int(proc["souls"]),
            }
        )
        target_health = max(0.0, target_health - float(proc["damage"]))
        souls += 1

    if not proc_events:
        state.notes.append(
            f"{effect.keystone_name} never procced: no timestamped direct hit "
            f"landed below {effect.health_threshold_ratio:.0%} target health."
        )
        return

    total_damage = sum(float(event["damage"]) for event in proc_events)
    state.breakdown[effect.breakdown_key] = {
        "name": effect.display_name,
        "total_damage": total_damage,
        "damage_type": damage_type,
        "count": len(proc_events),
        "event_phase": "effect",
        "damage_events": proc_events,
    }
    state.total_damage += total_damage
    state.notes.append(
        f"{effect.keystone_name} uses a sourced {effect.health_threshold_ratio:.0%} "
        f"maximum-health threshold, {effect.proc_delay_seconds:g}-second reap "
        f"delay, and {effect.cooldown_seconds:g}-second cooldown from each hit. "
        f"The first proc starts at 0 Souls; {souls} Soul(s) were reaped."
    )
    if skipped_after_death:
        state.notes.append(
            f"{effect.keystone_name}: {skipped_after_death} delayed proc(s) "
            "were withheld after the target died."
        )
    state.notes.append(
        f"{effect.keystone_name}: the sourced {effect.takedown_reset_seconds:g}-second "
        "takedown reset needs a team takedown receipt and is not applied in this "
        "single-target damage pass."
    )


def _certified_ledger(
    state: FightState, rotation: RotationResult
) -> tuple[list[dict[str, Any]], set[str], list[str]]:
    """The ordered damage events plus the certified/coarse source split.

    Window and lasting-amp keystones must agree with the fight report
    about which sources carry certified event times; both read this one
    helper so ``_event_timeline_coverage``'s definition of "certified"
    stays structural rather than by convention.
    """
    events = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
    )
    coverage = _event_timeline_coverage(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        num_auto_attacks=state.num_auto_attacks,
    )
    return events, set(coverage["exact_sources"]), coverage["coarse_sources"]


def _add_keystone_window_amp_damage(
    state: FightState, rotation: RotationResult
) -> None:
    """Add opening-window keystone bonus damage (First Strike-class).

    The buff activates once at combat start — a continuous fight never
    re-enters combat, so the rune's out-of-combat cooldown is moot. Its
    bonus is a sourced ratio of the post-mitigation damage dealt inside
    the opening window, read from the ordered damage ledger, and lands
    as true damage. The gold it generates (flat activation gold plus the
    melee/ranged share of the bonus) is reported on the breakdown row
    and in the fight notes; gold is not damage and never joins the total.

    Runs after every damage row exists and before fight-wide amplifiers:
    amp rows carry no event times, so the window is summed pre-amp — a
    conservative understatement whenever an amplifier is active.
    """
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneWindowAmpEffect):
        return
    # Only sources with certified event times can be placed inside the
    # window. Coarse-timed rows (DoTs whose totals resolve past their
    # cast, item effects without authored events, auto-coupled casts)
    # are excluded and disclosed — omitting a source can only understate
    # the bonus, never overstate it.
    events, certified, coarse_sources = _certified_ledger(state, rotation)
    contributing = [
        event
        for event in events
        if event["source_key"] in certified and event["time"] < effect.window_seconds
    ]
    window_damage = sum(event["damage"] for event in contributing)

    bonus = effect.bonus_damage_ratio * window_damage
    gold = effect.activation_gold + effect.gold_conversion(state.is_melee) * bonus
    if window_damage > 0:
        auto_stream_damage = sum(
            event["damage"]
            for event in contributing
            if _is_auto_stream_key(event["source_key"])
        )
        state.breakdown[effect.breakdown_key] = {
            "name": effect.display_name,
            "total_damage": bonus,
            "damage_type": "true",
            "count": 1,
            "event_phase": "effect",
            "gold_generated": gold,
            "auto_attack_fraction": auto_stream_damage / window_damage,
            "damage_events": [
                {
                    "time": event["time"],
                    "damage": effect.bonus_damage_ratio * event["damage"],
                    "damage_type": "true",
                }
                for event in contributing
            ],
        }
        state.total_damage += bonus
    # The activation itself (and its flat gold) does not depend on any
    # window damage being certified — the notes always surface.
    state.notes.append(
        f"{effect.keystone_name} assumes you initiate combat; it generated "
        f"{gold:.0f} gold ({effect.activation_gold:.0f} on activation plus "
        f"{effect.gold_conversion(state.is_melee) * 100:.0f}% of "
        f"{bonus:.0f} bonus true damage)."
    )
    if coarse_sources:
        state.notes.append(
            f"{effect.keystone_name} window excludes sources without "
            f"certified event times ({', '.join(sorted(coarse_sources))}); "
            "its bonus is a floor, not an estimate."
        )


def _refreshing_stack_proc_times(
    state: FightState, effect: "rune_effects.KeystoneProcAmpEffect"
) -> tuple[list[float], bool]:
    """Walk the simulated auto swings with a refreshing stack rule.

    Only basic attacks stack this keystone class — ability casts never
    do. Every application refreshes all stacks, so the count survives
    while consecutive swings land within ``stack_duration_seconds`` of
    each other. Reaching the required stacks procs on that swing and
    clears them. Stacks are assumed not to build during the per-target
    cooldown — the wiki does not document this either way, and the
    assumption can only delay a proc, never invent one. Returns the
    proc times plus whether that assumption gated any swing, so the
    caller can disclose it.
    """
    proc_times: list[float] = []
    stacks = 0
    last_stack_time = float("-inf")
    ready_at = 0.0
    cooldown_gated = False
    for swing_time in _auto_attack_timestamps(state):
        if swing_time < ready_at:
            cooldown_gated = True
            continue
        if swing_time - last_stack_time >= effect.stack_duration_seconds:
            stacks = 0
        stacks += 1
        last_stack_time = swing_time
        if stacks >= effect.stacks_required:
            proc_times.append(swing_time)
            ready_at = swing_time + effect.cooldown_seconds
            stacks = 0
    return proc_times, cooldown_gated


def _grasp_proc_events(
    state: FightState, rotation: RotationResult
) -> list[dict[str, float | int]]:
    """Walk Grasp's timed combat stacks over the authored attack timeline.

    A combat entry starts one stack cycle. The first stack arrives after the
    sourced cadence, four stacks complete the cycle, and the next basic
    attack consumes them inside the sourced ready window. After a consume,
    the next cycle starts from that attack while combat continues.
    """
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneGraspEffect):
        return []
    attack_times = _auto_attack_timestamps(state)
    if not attack_times:
        return []
    combat_times = _keystone_instance_times(state, rotation)
    if not combat_times:
        return []
    cadence = effect.stack_cadence_seconds
    generation = effect.stack_generation_seconds
    if cadence <= 0.0 or generation < 0.0 or effect.max_stacks <= 0:
        return []

    stack_count = 0
    next_stack_time = combat_times[0] + cadence
    last_combat_time = combat_times[0]
    ready_until = float("-inf")
    proc_events: list[dict[str, float | int]] = []
    for attack_time in attack_times:
        combat_at_attack = [
            combat_time for combat_time in combat_times if combat_time <= attack_time
        ]
        if combat_at_attack:
            latest_combat_time = combat_at_attack[-1]
            if latest_combat_time - last_combat_time > generation:
                stack_count = 0
                next_stack_time = latest_combat_time + cadence
            last_combat_time = latest_combat_time
        if stack_count >= effect.max_stacks and attack_time > ready_until + 1e-9:
            stack_count = 0
            next_stack_time = attack_time + cadence
        while (
            next_stack_time <= attack_time + 1e-9
            and next_stack_time <= last_combat_time + generation + 1e-9
            and stack_count < effect.max_stacks
        ):
            stack_count += 1
            if stack_count >= effect.max_stacks:
                ready_until = next_stack_time + effect.ready_window_seconds
            next_stack_time += cadence
        if stack_count >= effect.max_stacks and attack_time <= ready_until + 1e-9:
            proc_events.append(
                {
                    "time": attack_time,
                    "trigger_time": attack_time,
                    "stacks": effect.max_stacks,
                }
            )
            stack_count = 0
            next_stack_time = attack_time + cadence
            ready_until = float("-inf")
    return proc_events


def _add_keystone_grasp_damage(state: FightState, rotation: RotationResult) -> None:
    """Add Grasp's empowered basic attacks and sourced self-heal receipts."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneGraspEffect):
        return
    proc_events = _grasp_proc_events(state, rotation)
    if not proc_events:
        state.notes.append(
            f"{effect.keystone_name} never procced: the authored basic-attack "
            f"timeline did not reach {effect.max_stacks} combat stacks."
        )
        return

    stats = state.champion_stats
    damage_type = "magic"
    raw_health = float(stats.get("health", 0.0) or 0.0)
    raw_damage_events: list[dict[str, float | int | str]] = []
    heal_events: list[dict[str, float | str | bool]] = []
    bonus_health_events: list[dict[str, float | str]] = []
    total_damage = 0.0
    total_healing = 0.0
    total_bonus_health = 0.0
    for event in proc_events:
        raw_damage = effect.raw_damage({"health": raw_health}, state.is_melee)
        mitigated = _mitigate(raw_damage, damage_type, state.resists, state.magic_amp)
        heal_amount = effect.heal_amount({"health": raw_health}, state.is_melee)
        bonus_health = effect.bonus_health(state.is_melee)
        raw_damage_events.append(
            {
                "time": float(event["time"]),
                "trigger_time": float(event["trigger_time"]),
                "damage": mitigated,
                "raw_damage": raw_damage,
                "damage_type": damage_type,
                "stacks": int(event["stacks"]),
            }
        )
        heal_events.append(
            {
                "time": float(event["time"]),
                "amount": heal_amount,
                "trigger_source": "auto_attacks",
                "actor_wide": True,
            }
        )
        bonus_health_events.append(
            {
                "time": float(event["time"]),
                "amount": bonus_health,
                "source": effect.display_name,
                "kind": "permanent_bonus_health",
            }
        )
        total_damage += mitigated
        total_healing += heal_amount
        total_bonus_health += bonus_health
        raw_health += bonus_health

    state.breakdown[effect.breakdown_key] = {
        "name": effect.display_name,
        "total_damage": total_damage,
        "damage_type": damage_type,
        "count": len(raw_damage_events),
        "event_phase": "effect",
        "damage_events": raw_damage_events,
        "permanent_health_gained": total_bonus_health,
        "permanent_health_events": bonus_health_events,
    }
    state.breakdown[f"heal_{effect.keystone_name}"] = {
        "name": f"{effect.display_name} (self-heal)",
        "count": len(heal_events),
        "amount_per_proc": total_healing / len(heal_events),
        "total_amount": total_healing,
        "unit": "health",
        "heal_events": heal_events,
        "event_phase": "heal",
    }
    state.total_damage += total_damage
    state.notes.append(
        f"{effect.keystone_name} procced {len(proc_events)} time(s) from "
        f"{effect.max_stacks} stacks, with a {effect.ready_window_seconds:g}-second "
        "ready window. Permanent health gains are applied in the ordered "
        "participant receipt."
    )


def _forced_basic_attack_times(
    state: FightState, rotation: RotationResult
) -> list[float]:
    """Return authored forced basic-attack times when no ambient stream exists."""
    if state.num_auto_attacks > 0 or rotation.forced_basic_attacks <= 0:
        return []
    times: list[float] = []
    for cast_event in rotation.cast_events:
        slot = cast_event.get("slot")
        if not isinstance(slot, str):
            continue
        row = state.breakdown.get(slot)
        if not isinstance(row, Mapping):
            continue
        authored = row.get("damage_events")
        if not isinstance(authored, list):
            continue
        for event in authored:
            if not isinstance(event, Mapping) or not event.get("basic_attack"):
                continue
            damage = float(event.get("damage", 0.0) or 0.0)
            if damage > 0.0:
                times.append(float(event.get("time", 0.0) or 0.0))
    return sorted(times)


def _hail_active_for_forced_attacks(
    effect: "rune_effects.KeystoneHailOfBladesEffect", attack_times: list[float]
) -> tuple[list[int], list[float]]:
    """Walk Hail stacks over authored forced attacks."""
    active_indexes: list[int] = []
    activation_times: list[float] = []
    stacks = 0
    ready_at = float("-inf")
    active_until = float("-inf")
    for index, attack_time in enumerate(attack_times):
        if attack_time > active_until + 1e-9:
            stacks = 0
        if stacks <= 0 and attack_time + 1e-9 >= ready_at:
            stacks = effect.initial_stacks
            active_until = attack_time + effect.stack_duration_seconds
            activation_times.append(attack_time)
        if stacks <= 0 or attack_time > active_until + 1e-9:
            continue
        active_indexes.append(index)
        stacks -= 1
        active_until = attack_time + effect.stack_duration_seconds
        if stacks == 0:
            ready_at = attack_time + effect.cooldown_seconds
    return active_indexes, activation_times


def _add_keystone_hail_of_blades(state: FightState, rotation: RotationResult) -> None:
    """Add Hail's true-damage rider from the shared basic-attack stream."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneHailOfBladesEffect):
        return

    forced_times = _forced_basic_attack_times(state, rotation)
    if state.hail_attack_times:
        attack_times = _auto_attack_timestamps(state)
        active_indexes = list(state.hail_active_attack_indices)
        activation_times = list(state.hail_activation_times)
        carrier = "ambient basic attacks"
    elif forced_times:
        attack_times = forced_times
        active_indexes, activation_times = _hail_active_for_forced_attacks(
            effect, attack_times
        )
        carrier = "forced basic attacks"
    else:
        state.notes.append(
            f"{effect.keystone_name} never procced: the fight had no "
            "authored basic-attack landing."
        )
        return

    if not active_indexes:
        state.notes.append(
            f"{effect.keystone_name} never procced: all authored basic attacks "
            f"landed outside its {effect.stack_duration_seconds:g}-second stack window."
        )
        return

    raw_damage = effect.raw_damage(_damage_inputs(state))
    if raw_damage <= 0.0:
        return
    damage_events = [
        {
            "time": attack_times[index],
            "damage": raw_damage,
            "raw_damage": raw_damage,
            "damage_type": "true",
            "basic_attack": True,
            "trigger_source": carrier,
        }
        for index in active_indexes
        if index < len(attack_times)
    ]
    if not damage_events:
        return
    total_damage = sum(float(event["damage"]) for event in damage_events)
    state.breakdown[effect.breakdown_key] = {
        "name": effect.display_name,
        "total_damage": total_damage,
        "damage_type": "true",
        "count": len(damage_events),
        "event_phase": "effect",
        "damage_events": damage_events,
        "active_attack_indices": active_indexes,
        "activation_times": activation_times,
        "bonus_attack_speed_percent": effect.bonus_attack_speed_percent(state.is_melee),
        "initial_stacks": effect.initial_stacks,
        "reset_stack_limit": effect.reset_stack_limit,
    }
    state.total_damage += total_damage
    state.notes.append(
        f"{effect.keystone_name} used {len(damage_events)} active basic attack(s) "
        f"from {carrier}. The sourced {effect.bonus_attack_speed_percent(state.is_melee):g}% "
        "attack-speed window is included in the shared swing schedule. "
        f"Basic-attack reset stacks remain available up to {effect.reset_stack_limit} "
        "times when a carrier publishes a reset receipt."
    )


def _add_keystone_lethal_tempo(state: FightState, rotation: RotationResult) -> None:
    """Add Lethal Tempo's max-stack adaptive bolt events."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneLethalTempoEffect):
        return

    forced_times = _forced_basic_attack_times(state, rotation)
    if state.lethal_attack_times:
        attack_times = _auto_attack_timestamps(state)
        bolt_indexes = list(state.lethal_bolt_attack_indices)
        stack_counts = list(state.lethal_stack_counts)
        activation_times = list(state.lethal_activation_times)
        carrier = "ambient basic attacks"
    elif forced_times:
        (
            attack_times,
            bolt_indexes,
            stack_counts,
            activation_times,
        ) = _lethal_tempo_attack_schedule(state, effect, forced_times)
        carrier = "forced basic attacks"
    else:
        state.notes.append(
            f"{effect.keystone_name} never reached maximum stacks: the fight "
            "had no authored basic-attack landing."
        )
        return

    if not bolt_indexes:
        state.notes.append(
            f"{effect.keystone_name} never reached its {effect.max_stacks} "
            "stack bolt threshold."
        )
        return

    inputs = _damage_inputs(state)
    damage_type = effect.damage_type(state.champion_stats)
    damage_events = []
    for index in bolt_indexes:
        if index >= len(attack_times) or index >= len(stack_counts):
            continue
        stacks = stack_counts[index]
        raw_damage = effect.bolt_raw_damage(inputs, state.is_melee, stacks)
        if raw_damage <= 0.0:
            continue
        damage_events.append(
            {
                "time": attack_times[index],
                "damage": raw_damage,
                "raw_damage": raw_damage,
                "damage_type": damage_type,
                "basic_attack": True,
                "trigger_source": carrier,
                "stack_count": stacks,
                "bonus_attack_speed_percent": effect.attack_speed_percent(
                    state.is_melee, stacks
                ),
            }
        )
    if not damage_events:
        return

    total_damage = sum(float(event["damage"]) for event in damage_events)
    state.breakdown[effect.breakdown_key] = {
        "name": effect.display_name,
        "total_damage": total_damage,
        "damage_type": damage_type,
        "count": len(damage_events),
        "event_phase": "effect",
        "damage_events": damage_events,
        "bolt_attack_indices": bolt_indexes,
        "stack_counts": stack_counts,
        "activation_times": activation_times,
        "max_stacks": effect.max_stacks,
        "stack_duration_seconds": effect.stack_duration_seconds,
        "expiry_step_seconds": effect.expiry_step_seconds,
        "attack_speed_percent_per_stack": effect.attack_speed_percent(
            state.is_melee, 1
        ),
    }
    state.total_damage += total_damage
    state.notes.append(
        f"{effect.keystone_name} fired {len(damage_events)} max-stack bolt(s) "
        f"from {carrier}. Each stack adds "
        f"{effect.attack_speed_percent(state.is_melee, 1):g}% bonus attack speed; "
        f"stacks expire one at a time every {effect.expiry_step_seconds:g}s "
        f"after {effect.stack_duration_seconds:g}s without an attack."
    )


@dataclass
class FerocityTimeline:
    """Rengar's live Ferocity walk result (P3 package 3V).

    The stack machine is the kernel's ``TimedStackState`` built from the
    module's typed ``RENGAR_FEROCITY_STACK_RULE``; the per-cast empowered
    flags are derived by walking the plan's accepted Q/W/E cast times in
    the same order the post-rotation receipt walk consumes them, so the
    damage pricing and the receipts cannot disagree.
    """

    stack: Any
    starting_stacks: int = 0
    _empowered_by_cast: dict[tuple[str, int], bool] = field(default_factory=dict)
    receipts: list[dict[str, Any]] = field(default_factory=list)

    def cast_empowered(self, ability_key: str, ordinal: int) -> bool:
        """Whether one accepted Q/W/E cast consumed the 4-stack cap."""
        return self._empowered_by_cast.get((ability_key, ordinal), False)


def _build_ferocity_timeline(
    state: FightState, plan: CastPlan
) -> FerocityTimeline | None:
    """Walk Rengar's accepted basic-ability casts against the kernel rule.

    The module prices live empowered casts from the typed rule; this
    timeline (a) seeds the kernel stack state from the same ``p_ferocity``
    option the module parse consumed, (b) applies one gain per accepted
    Q/W/E cast at its cast time (the kernel owns the 1-second per-stack
    no-refresh expiry, the 10-second combat freeze, and the cap), and
    (c) marks the cast that consumes the cap as empowered.  Returns None
    for any champion whose module does not emit ``ferocity_parts``.
    """
    if not any(
        "ferocity_parts" in info
        for info in state.ability_damages.values()
        if isinstance(info, dict)
    ):
        return None
    from .champions.rengar import RENGAR_FEROCITY_STACK_RULE

    rule = RENGAR_FEROCITY_STACK_RULE
    options = state.champion_options or {}
    try:
        seeded = int(options.get("p_ferocity", 0) or 0)
    except (TypeError, ValueError):
        seeded = 0
    seeded = max(0, min(seeded, 4))
    stack = TimedStackState(RENGAR_FEROCITY_STACK_RULE, starting_stacks=seeded)
    empowered: dict[tuple[str, int], bool] = {}
    receipts: list[dict[str, Any]] = []
    sequence = 0
    casts: list[tuple[float, str, int]] = []
    for ability_key in ("Q", "W", "E"):
        for ordinal, cast_time in enumerate(plan.times.get(ability_key, ())):
            casts.append((float(cast_time), ability_key, ordinal))
    casts.sort(key=lambda row: (row[0], ("Q", "W", "E").index(row[1]), row[2]))
    for cast_time, ability_key, ordinal in casts:
        before = stack.stacks
        transitions = stack.apply_gain(
            cast_time,
            kind="basic_ability_cast",
            packet="ability_cast",
            meta={"source": f"{ability_key} cast", "source_key": ability_key},
            sequence=sequence,
        )
        sequence += 1
        denied = any(
            getattr(transition, "kind", None) == "gain_denied"
            for transition in transitions
        )
        receipts.append(
            {
                "operation": "gain",
                "amount": 1.0,
                "time": round(float(cast_time), 3),
                "source": f"{ability_key} cast",
                "sequence": sequence,
                "tier": 0.0,
                "atoms": [],
                "current_before": before,
                "maximum_before": rule.max_stacks,
                "current_after": stack.stacks,
                "maximum_after": rule.max_stacks,
                "accepted": not denied,
                "reason": "at_cap" if denied else "",
            }
        )
        if denied:
            # At the cap the cast is EMPOWERED: consume the four stacks
            # and price the module's ferocity parts.
            consume_before = stack.stacks
            stack.consume(
                cast_time,
                sequence=sequence,
                meta={"source": f"{ability_key} cast"},
            )
            sequence += 1
            receipts.append(
                {
                    "operation": "consume",
                    "amount": float(consume_before),
                    "time": round(float(cast_time), 3),
                    "source": f"{ability_key} cast",
                    "sequence": sequence,
                    "tier": 0.0,
                    "atoms": [],
                    "current_before": consume_before,
                    "maximum_before": rule.max_stacks,
                    "current_after": stack.stacks,
                    "maximum_after": rule.max_stacks,
                    "accepted": True,
                    "reason": "empowered",
                }
            )
            empowered[(ability_key, ordinal)] = True
    return FerocityTimeline(
        stack=stack,
        starting_stacks=seeded,
        _empowered_by_cast=empowered,
        receipts=receipts,
    )


def _conqueror_trigger_events(
    state: FightState, rotation: RotationResult
) -> list[dict[str, Any]]:
    """Group certified ability casts and basic attacks into Conqueror hits.

    Conqueror grants one stack packet per ability cast instance. A multi-hit
    cast must not grant one packet per hit. Basic-attack and on-hit rows at
    one landing share one packet, so the max-stack heal sees the full
    post-mitigation attack damage.
    """
    ordered = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
    )
    detailed = [event for event in ordered if isinstance(event, Mapping)]
    ability_events = [
        event
        for event in detailed
        if event.get("is_ability") and float(event.get("damage", 0.0) or 0.0) > 0.0
    ]
    cast_times: dict[str, list[float]] = {}
    for cast in rotation.cast_events:
        slot = str(cast.get("slot", ""))
        if slot in state.cast_order:
            cast_times.setdefault(slot, []).append(float(cast.get("time", 0.0)))

    triggers: list[dict[str, Any]] = []
    for slot, times in cast_times.items():
        slot_events = [
            event for event in ability_events if event.get("source_key") == slot
        ]
        for index, cast_time in enumerate(times):
            next_cast = times[index + 1] if index + 1 < len(times) else math.inf
            cast_events = [
                event
                for event in slot_events
                if cast_time - 1e-9 <= float(event.get("time", 0.0)) < next_cast - 1e-9
            ]
            if not cast_events:
                continue
            trigger_time = min(
                float(event.get("time", cast_time)) for event in cast_events
            )
            triggers.append(
                {
                    "time": trigger_time,
                    "sequence": min(
                        int(event.get("sequence", 0)) for event in cast_events
                    ),
                    "source_key": slot,
                    "source": slot,
                    "damage": sum(
                        float(event.get("damage", 0.0) or 0.0) for event in cast_events
                    ),
                    "packet": "ability_cast",
                }
            )

    auto_events = [
        event
        for event in detailed
        if str(event.get("phase", "")) == "auto"
        and float(event.get("damage", 0.0) or 0.0) > 0.0
    ]
    auto_groups: dict[float, list[Mapping[str, Any]]] = {}
    for event in auto_events:
        time = round(float(event.get("time", 0.0)), 9)
        auto_groups.setdefault(time, []).append(event)
    for time, events in auto_groups.items():
        triggers.append(
            {
                "time": time,
                "sequence": min(int(event.get("sequence", 0)) for event in events),
                "source_key": "auto_attacks",
                "source": "auto_attacks",
                "damage": sum(
                    float(event.get("damage", 0.0) or 0.0) for event in events
                ),
                "packet": "basic_attack",
            }
        )
    return sorted(
        triggers,
        key=lambda event: (float(event["time"]), int(event["sequence"])),
    )


def _add_keystone_conqueror(state: FightState, rotation: RotationResult) -> None:
    """Add Conqueror's stack timeline and max-stack healing receipt.

    The stack timing is kernel-owned (state_lifecycle): the walk feeds the
    certified ability-cast and basic-attack trigger stream into a
    ``TimedStackState`` built from the rune's sourced stack rule, and the
    kernel owns gain, the 5-second expiry/refresh, the 4-second per-cast
    interval gate, and the max-stack cap.  The kernel's transition receipt
    (including expiries and interval denials) rides the breakdown row as
    ``state_transitions``.  Adaptive force stays a typed state receipt: the
    current ability evaluator prices champion formulas before this walk, so
    that force remains withheld until every AD/AP formula can be re-priced
    from a per-cast state.
    """
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneConquerorEffect):
        return

    options = state.keystone_options or {}
    starting_stacks = int(options.get("starting_stacks", 0) or 0)
    triggers = _conqueror_trigger_events(state, rotation)
    stack_state = rune_effects.conqueror_stack_state(
        effect, starting_stacks=starting_stacks
    )
    stack_events: list[dict[str, Any]] = []
    heal_events: list[dict[str, Any]] = []
    for trigger in triggers:
        trigger_time = float(trigger["time"])
        transitions = stack_state.apply_gain(
            trigger_time,
            kind=trigger["packet"],
            packet=trigger["packet"],
            meta=trigger,
            sequence=int(trigger.get("sequence", 0)),
        )
        gain_transition = None
        for transition in reversed(transitions):
            if transition.kind in (
                "gain",
                "refresh",
                "extend",
                "replace",
                "gain_denied",
            ):
                gain_transition = transition
                break
        detail = gain_transition.detail if gain_transition is not None else {}
        stacks_before = int(detail.get("stacks_before", stack_state.stacks))
        stacks = stack_state.stacks
        stacks_gained = max(0, stacks - stacks_before)
        damage = float(trigger["damage"])
        stack_event = {
            "time": trigger_time,
            "kind": "status",
            "source": "Conqueror · stack",
            "source_key": effect.breakdown_key,
            "target_scope": "self",
            "target_policy": "self",
            "stacks_before": stacks_before,
            "stacks_after": stacks,
            "stacks_gained": stacks_gained,
            "max_stacks": effect.max_stacks,
            "adaptive_force": effect.adaptive_force_at(state.level, stacks),
            "packet": trigger["packet"],
            "trigger_source": trigger["source"],
            "event_precision": "exact",
            "_event_id": f"main:conqueror:stack:{len(stack_events)}",
        }
        if gain_transition is not None and gain_transition.kind == "gain_denied":
            stack_event["denied"] = str(detail.get("reason", ""))
        stack_events.append(stack_event)
        if stacks >= effect.max_stacks and damage > 0.0:
            heal_events.append(
                {
                    "time": trigger_time,
                    "amount": effect.heal_amount(damage, state.is_melee),
                    "trigger_source": trigger["source"],
                    "actor_wide": True,
                    "kind": "keystone",
                    "healing_category": "direct",
                    "stacks": stacks,
                    "_event_id": f"main:conqueror:heal:{len(heal_events)}",
                }
            )

    state.breakdown[effect.breakdown_key] = {
        "name": effect.display_name,
        "informational": True,
        "event_phase": "effect",
        "count": len(stack_events),
        "starting_stacks": starting_stacks,
        "max_stacks": effect.max_stacks,
        "stack_duration_seconds": effect.stack_duration_seconds,
        "stacks_per_application": effect.stacks_per_application,
        "cast_instance_interval_seconds": effect.cast_instance_interval_seconds,
        "adaptive_force_per_stack_at_level": effect.adaptive_force_at(state.level, 1),
        "adaptive_force_at_max": effect.adaptive_force_at(
            state.level, effect.max_stacks
        ),
        "adaptive_force_max_source": effect.max_adaptive_force_at(state.level),
        "adaptive_force_state_applied": False,
        "stack_events": stack_events,
        "state_transitions": stack_state.public_receipt()["transitions"],
    }
    if heal_events:
        total_healing = sum(float(event["amount"]) for event in heal_events)
        state.breakdown[f"heal_{effect.keystone_name}"] = {
            "name": f"{effect.display_name} (max-stack heal)",
            "owner": "keystone",
            "count": len(heal_events),
            "amount_per_proc": total_healing / len(heal_events),
            "total_amount": total_healing,
            "unit": "health",
            "heal_events": heal_events,
            "event_phase": "heal",
        }
    if not triggers:
        state.notes.append(
            f"{effect.keystone_name} recorded no certified ability-cast or "
            "basic-attack damage packets."
        )
    elif not heal_events:
        state.notes.append(
            f"{effect.keystone_name} reached {stack_state.stacks} stack(s), "
            f"below its {effect.max_stacks}-stack healing threshold."
        )
    else:
        state.notes.append(
            f"{effect.keystone_name} recorded {len(stack_events)} certified "
            f"stack packet(s) and {len(heal_events)} max-stack heal(s)."
        )
    state.notes.append(
        f"{effect.keystone_name} adaptive force is withheld from damage pricing: "
        "champion AD/AP formulas need per-cast re-pricing before this state can "
        "change damage."
    )


def _add_senna_souls(
    state: FightState,
    rotation: RotationResult,
    shield_outcome: Mapping[str, Any],
    damage_events: list[dict[str, Any]],
) -> None:
    """Add Senna's Absolution Mist soul-counter ledger (P3 package 3W).

    Mist is a PERMANENT pre-fight counter: the seeded ``senna_mist_stacks``
    option prices the stats at parse time (0.75 bonus AD per soul, 20
    range + 10% crit per 20), and the only ACCEPTED live soul event is
    the fight's champion takedown (``target_ending_health <= 0`` — the
    3K-style synthesis shape; one soul from the champion wraith pickup).
    This walk is documentary: it receipts the gains, the every-20
    threshold crossings, and the fail-closed denials into an additive
    ``resource_ledger["mist"]`` (kind "souls") sub-section — the mana
    account is never replaced — and never re-prices any damage.
    """
    if "senna_mist_stacks" not in (state.champion_options or {}):
        # Not a Senna-configured fight: no souls surface at all.
        return
    from .champions.senna import SENNA_MIST_RULE

    option = state.champion_options or {}
    try:
        seeded = int(option.get("senna_mist_stacks", 40) or 40)
    except (TypeError, ValueError):
        seeded = 40
    if not (0 <= seeded <= 300):
        seeded = max(0, min(seeded, 300))
    receipts: list[dict[str, Any]] = []
    thresholds: list[dict[str, Any]] = []
    current = seeded
    gains = 0

    def _add_receipt(
        operation: str,
        amount: float,
        time: float,
        source: str,
        accepted: bool,
        reason: str,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        nonlocal current, gains
        before = current
        if accepted:
            current += amount
            gains += 1
        receipts.append(
            {
                "owner": "main",
                "kind": "souls",
                "operation": operation,
                "amount": amount,
                "time": round(float(time), 3),
                "source": source,
                "sequence": len(receipts) + 1,
                "tier": 0.0,
                "atoms": [],
                "current_before": before,
                "maximum_before": 300,
                "current_after": current,
                "maximum_after": 300,
                "accepted": accepted,
                "reason": reason,
                **(dict(detail) if detail else {}),
            }
        )

    # The accepted soul event: the champion takedown of the modeled target.
    # (A killed target's 0.0 must not fall back to the survived default.)
    raw_ending = shield_outcome.get("target_ending_health")
    target_health = float(raw_ending if raw_ending is not None else 1.0)
    if target_health <= 0.0:
        kill_time = max(
            (float(event.get("time", 0.0) or 0.0) for event in damage_events),
            default=0.0,
        )
        _add_receipt(
            "gain",
            1.0,
            kill_time,
            "champion takedown",
            True,
            "",
            {
                "event": "takedown",
                "target": shield_outcome.get("target", "target"),
                "event_time": round(kill_time, 3),
            },
        )
    else:
        _add_receipt("gain", 0.0, 0.0, "champion takedown", False, "no_takedown_event")
    # Named fail-closed denials for the unsupported soul sources (the
    # module's documented boundaries): the model never authors these
    # events, but a future source must not silently mint souls.
    for source in ("minion_drop", "wraith_farm", "mark_consume"):
        _add_receipt(
            "gain",
            0.0,
            0.0,
            f"unsupported_soul_source:{source}",
            False,
            f"unsupported_soul_source:{source}",
            {"event": source, "event_time": 0.0},
        )
    _add_receipt(
        "gain",
        0.0,
        0.0,
        "soul_event_without_identity",
        False,
        "missing_identity",
    )

    # Every-20 threshold crossings: documented, never re-priced.
    threshold_value = seeded // 20 * 20
    while threshold_value <= current:
        thresholds.append(
            {
                "threshold": threshold_value,
                "threshold_count": threshold_value,
                "range_delta": 20.0,
                "crit_delta": 10.0,
                "bonus_attack_range": 20.0 * (threshold_value // 20),
                "bonus_critical_strike_chance": 10.0 * (threshold_value // 20),
                "stacks_before": max(0, threshold_value - 20),
                "stacks_after": threshold_value,
                "stat_application": "parse_time_seeded",
            }
        )
        threshold_value += 20

    ledger_section = rotation.resource_ledger
    if not isinstance(ledger_section, dict):
        ledger_section = {}
        rotation.resource_ledger = ledger_section
    ledger_section["souls"] = {
        "contract": "resource_ledger_v1",
        "owner": "main",
        "kind": "souls",
        "opening_maximum": 300,
        "opening_current": seeded,
        "closing_maximum": 300,
        "closing_current": current,
        "base_maximum": 300,
        "bonus_maximum": 0,
        "receipts": receipts,
        "threshold_transitions": thresholds,
        "declaration": SENNA_MIST_RULE.public_receipt(),
    }
    state.breakdown["mist"] = {
        "name": SENNA_MIST_RULE.public_receipt()["name"],
        "owner": "champion",
        "informational": True,
        "event_phase": "effect",
        "count": gains,
        "starting_stacks": seeded,
        "state": f"{seeded} seeded Mist souls; {current} at fight end",
        "max_stacks": 300,
        "soul_events": [
            receipt for receipt in receipts if receipt["operation"] == "gain"
        ],
        "threshold_transitions": thresholds,
    }
    if gains:
        state.notes.append(
            f"Senna Mist: {current} souls at fight end ({gains} champion "
            f"takedown soul(s) gained over the seeded {seeded})."
        )
    else:
        state.notes.append(
            f"Senna Mist: {current} souls (no champion takedown — the "
            "seeded counter is the whole admission; minion drops and "
            "Wraith-farming are named unsupported sources)."
        )


def _feed_ashe_focus_stack(
    stack: Any,
    swings: list[Any],
    q_casts: list[Mapping[str, Any]],
    duration: float,
    q_window_end: float = 0.0,
) -> tuple[list[dict[str, Any]], int, int]:
    """Feed the Focus stack machine from the engine's per-swing stream.

    The Q-activation consume sorts BEFORE the same-timestamp swings (the
    model activates Q before any swing at t=0 when the gate is open);
    each auto swing then gains a stack at its swing time.  Returns the
    receipt list, the accepted-gain count and the activation count.
    """
    receipts: list[dict[str, Any]] = []
    current = 0
    gains = 0
    consumes = 0
    sequence = 0

    def _record(
        operation: str,
        amount: float,
        time: float,
        source: str,
        status: tuple[bool, str],
    ) -> None:
        nonlocal current, gains
        accepted, reason = status
        before = current
        if accepted:
            current = max(0, current + amount)
            if operation == "gain":
                gains += 1
        receipts.append(
            {
                "owner": "main",
                "kind": "focus",
                "operation": operation,
                "amount": amount,
                "time": round(float(time), 3),
                "source": source,
                "sequence": len(receipts) + 1,
                "tier": 0.0,
                "atoms": [],
                "current_before": before,
                "maximum_before": 4,
                "current_after": current,
                "maximum_after": 4,
                "accepted": accepted,
                "reason": reason,
            }
        )

    events: list[tuple[float, str, int]] = []
    for cast in q_casts:
        events.append((float(cast.get("time", 0.0)), "consume", 0))
    for index, swing in enumerate(swings):
        if isinstance(swing, Mapping):
            events.append((float(swing.get("time", 0.0) or 0.0), "gain", index + 1))
    events.sort(
        key=lambda entry: (entry[0], 0 if entry[1] == "consume" else 1, entry[2])
    )
    for time, kind, index in events:
        sequence += 1
        if kind == "consume":
            before = stack.stacks
            stack.consume(
                time,
                sequence=sequence,
                meta={"source": "Ranger's Focus activation"},
            )
            after = stack.stacks
            if before >= 4:
                consumes += 1
                _record(
                    "consume",
                    -(before - after),
                    time,
                    "Ranger's Focus activation",
                    (True, ""),
                )
            else:
                _record(
                    "consume",
                    0.0,
                    time,
                    "Ranger's Focus activation",
                    (False, "below_cap"),
                )
        elif q_window_end > 0.0 and time < q_window_end:
            # P1 Slice 11: the "while Ranger's Focus is INACTIVE" clause
            # — the flurry-window swings generate NO Focus (a named
            # denial distinct from at_cap, the stack never mutates); the
            # gains resume at t >= q_window_end.
            _record(
                "gain",
                0.0,
                time,
                f"auto attack {index}",
                (False, "active_window"),
            )
        else:
            before = stack.stacks
            transitions = stack.apply_gain(
                time,
                kind="auto_attack",
                packet="basic_attack",
                meta={
                    "source": f"auto attack {index}",
                    "source_key": "auto_attacks",
                },
                sequence=sequence,
            )
            after = stack.stacks
            denied = bool(transitions) and transitions[-1].kind == "gain_denied"
            if denied:
                _record(
                    "gain",
                    0.0,
                    time,
                    f"auto attack {index}",
                    (False, "at_cap"),
                )
            else:
                _record(
                    "gain", after - before, time, f"auto attack {index}", (True, "")
                )
    sequence += 1
    stack.materialize_expiries(duration, sequence=sequence)
    return receipts, gains, consumes


def _add_ashe_focus(state: FightState, rotation: RotationResult) -> None:
    """Add Ashe's live Focus stack lifecycle receipts (P1 Slice 10).

    The Focus stack machine runs POST-ROTATION over the engine's
    already-priced per-swing events: each auto attack at its swing time
    gains a stack (cap 4, the 4s window refreshing on subsequent
    attacks, the 1/s step-down expiry, cap noop — a capped attack does
    NOT refresh, NO combat extension) via the typed
    ASHE_FOCUS_STACK_RULE, and the Ranger's Focus activation CONSUMES
    all 4 stacks (the wiki cost box "30 Mana + 4 Focus" — the
    consume-on-activation) when the modeled fight casts Q at the full
    stack.  This walk is documentary: it receipts the gains, the
    consume, the expiries, and the fail-closed denials into an additive
    ``resource_ledger["focus"]`` sub-section — the real mana account is
    never replaced — and never re-prices the parse-time Q (the gate +
    the flurry/AS pricing stay exactly as the module prices them).
    """
    option = state.champion_options or {}
    q_entry = state.ability_damages.get("Q") or {}
    q_active = bool(option.get("q_active", True))
    is_ashe = str(q_entry.get("name", "")) == "Ranger's Focus"
    # The Ashe identity: the module's Q entry name, OR the explicitly
    # passed q_active False override (the Q entry is absent when the
    # module gates on q_active first — the Focus still exists, the auto
    # gains are documented, no consume can fire).  The walk must never
    # run for another champion's Q.
    if not is_ashe and (q_active or "q_active" not in option):
        return
    if q_active and not q_entry:
        # Q rank 0 (unlearned) -> no Focus system at all.
        return
    try:
        seeded = int(option.get("q_focus_stacks", 4) or 4)
    except (TypeError, ValueError):
        seeded = 4
    if not (0 <= seeded <= 4):
        seeded = max(0, min(seeded, 4))
    stack = TimedStackState(ASHE_FOCUS_STACK_RULE, starting_stacks=seeded)
    swings = (state.breakdown.get("auto_attacks") or {}).get("damage_events") or []
    q_casts = [
        event for event in rotation.cast_events if str(event.get("slot", "")) == "Q"
    ]
    receipts, gains, consumes = _feed_ashe_focus_stack(
        stack,
        swings,
        q_casts,
        float(state.fight_duration_seconds or 0.0),
        q_window_end=float(state.q_window_end or 0.0),
    )
    closing = stack.stacks

    if swings:
        _add_focus_denial(
            receipts,
            "auto_attack_without_identity",
            "missing_identity",
        )
    for source, reason in (
        (
            "unsupported_focus_source:ability_cast",
            "unsupported_focus_source:ability_cast — only auto-attack "
            "swings generate Focus",
        ),
        (
            "unsupported_focus_source:on_hit",
            "unsupported_focus_source:on_hit — on-hit riders never "
            "generate Focus (Runaan's bolts excluded)",
        ),
    ):
        _add_focus_denial(receipts, source, reason)

    ledger_section = rotation.resource_ledger
    if not isinstance(ledger_section, dict):
        ledger_section = {}
        rotation.resource_ledger = ledger_section
    ledger_section["focus"] = {
        "contract": "resource_ledger_v1",
        "owner": "main",
        "kind": "focus",
        "opening_maximum": 4,
        "opening_current": seeded,
        "closing_maximum": 4,
        "closing_current": closing,
        "base_maximum": 4,
        "bonus_maximum": 0,
        "receipts": receipts,
        "declaration": ASHE_FOCUS_STACK_RULE.public_receipt(),
        "state_transitions": stack.public_receipt()["transitions"],
    }
    state.breakdown["focus"] = {
        "name": ASHE_FOCUS_STACK_RULE.public_receipt()["name"],
        "owner": "champion",
        "informational": True,
        "event_phase": "effect",
        "count": gains,
        "starting_stacks": seeded,
        "state": f"{seeded}/4 Focus stacks (seeded); {closing}/4 at fight end",
        "max_stacks": 4,
        "stack_duration_seconds": 4.0,
        "combat_extension_seconds": 0.0,
        "stack_events": [
            {
                "time": receipt["time"],
                "swing_index": None,
                "kind": receipt["operation"],
            }
            for receipt in receipts
            if receipt["operation"] in ("gain", "consume")
        ],
        "state_transitions": stack.public_receipt()["transitions"],
    }
    if gains or consumes:
        state.notes.append(
            f"Ashe Focus: {closing}/4 stacks at fight end ({gains} accepted "
            f"auto-attack gain(s); {consumes} Ranger's Focus activation(s))."
        )
    else:
        state.notes.append(
            "Ashe Focus recorded no accepted auto-attack swings "
            "(the seeded stacks are the whole admission)."
        )


def _add_focus_denial(
    receipts: list[dict[str, Any]],
    source: str,
    reason: str,
) -> None:
    """Append one named fail-closed denial receipt (the Rengar/Senna
    walk shape: accepted False, amount 0, the current unchanged)."""
    receipts.append(
        {
            "owner": "main",
            "kind": "focus",
            "operation": "gain",
            "amount": 0.0,
            "time": 0.0,
            "source": source,
            "sequence": len(receipts) + 1,
            "tier": 0.0,
            "atoms": [],
            "current_before": 0,
            "maximum_before": 4,
            "current_after": 0,
            "maximum_after": 4,
            "accepted": False,
            "reason": reason,
        }
    )


def _add_ksante_path_maker(state: FightState, rotation: RotationResult) -> None:
    """Add K'Sante's Path Maker W receipts (P3 4A).

    W prices one physical packet (flat + the % max-health term with the
    bonus-armor/MR resist ratios — the game-verified real authored
    effect, now attributed to the CASTER's bonus stats, never the
    target's/totals) and, in All Out, the interpolated true-damage
    range by the charge fraction.  This walk is documentary: it
    receipts the engine-priced parts (amount + part identity) and the
    named fail-closed denials — the R armor/MR-to-AD resist conversion
    and the 65% health threshold are state, the W dash's multi-target
    pass-through prices ONE champion target, the monster damage cap is
    monster-only, and a missing bonus-resist state prices 0 with a
    denial — into an additive ``resource_ledger["w"]`` (kind "w")
    sub-section — the mana account is never replaced — and never
    re-prices any damage.
    """
    if "w_charge" not in (state.champion_options or {}) and "all_out" not in (
        state.champion_options or {}
    ):
        return
    from .champions.ksante import KSANTE_PATH_MAKER_RULE

    w_entry = state.ability_damages.get("W")
    parts: list[Any] = []
    if isinstance(w_entry, dict):
        raw_parts = w_entry.get("parts")
        if isinstance(raw_parts, tuple) or isinstance(raw_parts, list):
            parts = list(raw_parts)
    missing_bonus_state = not (
        isinstance(state.champion_stats, dict)
        and "bonus_armor" in state.champion_stats
        and "bonus_magic_resistance" in state.champion_stats
    )

    receipts: list[dict[str, Any]] = []

    def _add_receipt(
        operation: str,
        amount: float,
        time: float,
        source: str,
        accepted: bool,
        reason: str,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        receipts.append(
            {
                "owner": "main",
                "kind": "w",
                "operation": operation,
                "amount": amount,
                "time": round(float(time), 3),
                "source": source,
                "sequence": len(receipts) + 1,
                "tier": 0.0,
                "atoms": [],
                "current_before": 0.0,
                "maximum_before": 0,
                "current_after": 0.0,
                "maximum_after": 0,
                "accepted": accepted,
                "reason": reason,
                **(dict(detail) if detail else {}),
            }
        )

    # The accepted stream: the engine-priced W parts (the All Out
    # physical part is deliberately untimed — the pinned charge-timing
    # asymmetry — so its receipt carries the part identity, time 0.0).
    if parts:
        for index, part in enumerate(parts, start=1):
            amount = float(getattr(part, "amount", 0.0))
            offset = getattr(part, "time_offset", None)
            damage_type = getattr(part, "damage_type", "")
            event_time = float(offset) if offset is not None else 0.0
            _add_receipt(
                "hit",
                amount,
                event_time,
                f"w_part:{damage_type}",
                True,
                "",
                {
                    "event": "w_part",
                    "part_index": index,
                    "damage_type": damage_type,
                    "event_time": round(event_time, 3),
                },
            )
    else:
        _add_receipt(
            "deny", 0.0, 0.0, "w_unavailable", False, "w_unavailable — no W cast"
        )

    if missing_bonus_state:
        _add_receipt(
            "deny",
            0.0,
            0.0,
            "w_missing_resist_state",
            False,
            "w_missing_resist_state — bonus armor/magic resistance absent; "
            "the resist terms priced at 0 (no invented stats)",
            {"event": "missing_resist_state", "event_time": 0.0},
        )
    # Named fail-closed denials for the unsupported state boundaries.
    for source, reason in (
        (
            "r_resist_conversion",
            "unsupported_state:r_resist_conversion — the All Out "
            "armor/MR-to-AD resist conversion is state, never priced",
        ),
        (
            "w_multi_target_dash",
            "unsupported_claim:w_multi_target_dash — the W dash passes "
            "through enemies; the model prices ONE champion target",
        ),
        (
            "w_knockback_stun_control",
            "unsupported_claim:w_knockback_stun_control — the W "
            "knockback/stun control is state/utility, not damage",
        ),
        (
            "w_monster_damage_cap",
            "unsupported_claim:w_monster_damage_cap — the Monster Damage "
            "Cap row is monster-only, never priced for champion fights",
        ),
        (
            "w_health_threshold",
            "unsupported_state:w_health_threshold — the All Out 65% "
            "health threshold is named state, never priced",
        ),
    ):
        _add_receipt(
            "deny",
            0.0,
            0.0,
            source,
            False,
            reason,
            {"event": source, "event_time": 0.0},
        )
    _add_receipt(
        "deny",
        0.0,
        0.0,
        "w_event_without_identity",
        False,
        "missing_identity",
    )

    ledger_section = rotation.resource_ledger
    if not isinstance(ledger_section, dict):
        ledger_section = {}
        rotation.resource_ledger = ledger_section
    ledger_section["w"] = {
        "contract": "resource_ledger_v1",
        "owner": "main",
        "kind": "w",
        "opening_maximum": 0,
        "opening_current": 0,
        "closing_maximum": 0,
        "closing_current": 0,
        "base_maximum": 0,
        "bonus_maximum": 0,
        "receipts": receipts,
        "declaration": KSANTE_PATH_MAKER_RULE.public_receipt(),
    }


def _add_heimerdinger_w_e(state: FightState, rotation: RotationResult) -> None:
    """Add Heimerdinger's W/E multi-part receipts (P3 3Z).

    W (Hextech Micro-Rockets) prices one first rocket + (n-1)
    subsequent rockets against the champion target from the degraded
    explicit rows; E (CH-2/CH-3X Electron Storm Grenade) prices ONE
    champion damage instance per cast.  The unsupported multi-target
    claims — the W rocket fan spread, the E grenade bounces, the
    stun/slow control, turret targeting/beam charge, and the R-upgraded
    W swarm (half-parsed W[1] rows) — are named fail-closed denials:
    the model never invents multi-target damage.  This walk is
    documentary: it receipts the engine-priced parts (the per-event
    damage_events identity) and the denials into an additive
    ``resource_ledger["w_e"]`` (kind "w_e") sub-section — the mana
    account is never replaced — and never re-prices any damage.
    """
    if "w_rockets" not in (state.champion_options or {}) and "e_upgrade" not in (
        state.champion_options or {}
    ):
        return
    from .champions.heimerdinger import (
        HEIMER_E_GRENADE_RULE,
        HEIMER_W_ROCKETS_RULE,
    )

    receipts: list[dict[str, Any]] = []

    def _add_receipt(
        operation: str,
        amount: float,
        time: float,
        source: str,
        accepted: bool,
        reason: str,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        receipts.append(
            {
                "owner": "main",
                "kind": "w_e",
                "operation": operation,
                "amount": amount,
                "time": round(float(time), 3),
                "source": source,
                "sequence": len(receipts) + 1,
                "tier": 0.0,
                "atoms": [],
                "current_before": 0.0,
                "maximum_before": 0,
                "current_after": 0.0,
                "maximum_after": 0,
                "accepted": accepted,
                "reason": reason,
                **(dict(detail) if detail else {}),
            }
        )

    # The accepted stream: the engine-priced W/E parts, one receipt per
    # damage_event (the swing/impact identity), amounts = the raw values.
    for slot in ("W", "E"):
        row = state.breakdown.get(slot)
        events: list[Mapping[str, Any]] = []
        if isinstance(row, dict):
            raw = row.get("damage_events")
            if isinstance(raw, list):
                events = [event for event in raw if isinstance(event, dict)]
        if events:
            for index, event in enumerate(events, start=1):
                event_time = float(event.get("time", 0.0))
                _add_receipt(
                    "hit",
                    float(event.get("raw_damage", 0.0)),
                    event_time,
                    f"{slot.lower()}_part",
                    True,
                    "",
                    {
                        "event": f"{slot.lower()}_part",
                        "event_index": index,
                        "event_time": round(event_time, 3),
                    },
                )
        elif row is None:
            _add_receipt(
                "deny",
                0.0,
                0.0,
                f"{slot}_unavailable",
                False,
                f"{slot}_unavailable — no {slot} cast in this fight",
            )
        else:
            _add_receipt(
                "deny",
                0.0,
                0.0,
                f"{slot}_part_without_identity",
                False,
                "missing_identity",
            )

    # Named fail-closed denials for the unsupported multi-target claims.
    for source, reason in (
        (
            "rocket_fan_multi_target",
            "unsupported_claim:rocket_fan_multi_target — the W rocket "
            "fan can spread across multiple targets; the model prices "
            "ONE champion target (fail-closed)",
        ),
        (
            "grenade_bounce",
            "unsupported_claim:grenade_bounce — the E grenade bounces "
            "can hit multiple enemies; the model prices ONE champion "
            "damage instance per cast (fail-closed)",
        ),
        (
            "grenade_control",
            "unsupported_claim:grenade_control — the E stun/slow "
            "control is state/utility, not direct champion damage",
        ),
        (
            "turret_targeting",
            "unsupported_claim:turret_targeting — turret targeting and "
            "beam charge are utility; the turret damage is the Q entry",
        ),
        (
            "upgraded_w_swarm",
            "unsupported_claim:upgraded_w_swarm — the R-upgraded "
            "Hextech Rocket Swarm (W[1] rows) is not priced; R is an "
            "empowerment toggle (fail-closed)",
        ),
    ):
        _add_receipt(
            "deny",
            0.0,
            0.0,
            source,
            False,
            reason,
            {"event": source, "event_time": 0.0},
        )
    _add_receipt(
        "deny",
        0.0,
        0.0,
        "w_e_event_without_identity",
        False,
        "missing_identity",
    )

    ledger_section = rotation.resource_ledger
    if not isinstance(ledger_section, dict):
        ledger_section = {}
        rotation.resource_ledger = ledger_section
    ledger_section["w_e"] = {
        "contract": "resource_ledger_v1",
        "owner": "main",
        "kind": "w_e",
        "opening_maximum": 0,
        "opening_current": 0,
        "closing_maximum": 0,
        "closing_current": 0,
        "base_maximum": 0,
        "bonus_maximum": 0,
        "receipts": receipts,
        "declaration": {
            "rockets": HEIMER_W_ROCKETS_RULE.public_receipt(),
            "grenade": HEIMER_E_GRENADE_RULE.public_receipt(),
        },
    }


def _add_bard_travelers_call(state: FightState, rotation: RotationResult) -> None:
    """Add Bard's Traveler's Call chime counter + meep ledger (P3 3Y).

    Chimes are a PERMANENT pre-fight counter: the seeded ``chimes``
    option prices the meep math at parse time (30 + 6 per 5 chimes +
    40% AP; the stock/recharge availability breakpoint tables).  The
    model cannot simulate map chime spawning/collection — no engine
    stream — so chime gains are named fail-closed denials.  The only
    ACCEPTED live events the engine prices are the meep-empowered
    autos: each empowered auto consumes one meep from the availability
    pool (stock + floor(duration / recharge) = the on-hit's
    ``max_procs``), booked as an identity-bearing spend.  This walk is
    documentary: it receipts the spends, the availability, and the
    fail-closed denials into an additive ``resource_ledger["chimes"]``
    (kind "chimes") sub-section — the mana account is never replaced —
    and never re-prices any damage.
    """
    if "chimes" not in (state.champion_options or {}):
        return
    from .champions.bard import (
        BARD_TRAVELERS_CALL_RULE,
        _CHIMES_PER_TIER,
        _DEFAULT_CHIMES,
        _MEEP_AP_RATIO,
        _MEEP_BASE,
        _MEEP_PER_TIER,
        _MEEP_RECHARGE_TIERS,
        _MEEP_STOCK_TIERS,
        _tier_value,
    )

    option = state.champion_options or {}
    try:
        seeded = int(option.get("chimes", _DEFAULT_CHIMES) or _DEFAULT_CHIMES)
    except (TypeError, ValueError):
        seeded = _DEFAULT_CHIMES
    if not (0 <= seeded <= 200):
        seeded = max(0, min(seeded, 200))

    # The availability the engine actually priced at parse time: the P
    # on-hit's max_procs (stock + floor(duration / recharge) when timed).
    on_hit = state.ability_damages.get("passive", {}).get("on_hit", {})
    if (
        on_hit.get("name") != "Traveler's Call (Meep)"
        or not isinstance(on_hit.get("max_procs"), (int, float))
        or float(on_hit.get("max_procs", 0.0)) <= 0
    ):
        opening = 0
    else:
        opening = int(on_hit["max_procs"])

    stock = _tier_value(_MEEP_STOCK_TIERS, seeded)
    recharge = _tier_value(_MEEP_RECHARGE_TIERS, seeded)
    recharges = max(0, opening - stock)
    ap = float(state.champion_stats.get("ability_power", 0.0) or 0.0)
    per_meep = (
        _MEEP_BASE + _MEEP_PER_TIER * (seeded // _CHIMES_PER_TIER) + _MEEP_AP_RATIO * ap
    )

    receipts: list[dict[str, Any]] = []
    current = seeded
    consumed = 0

    def _add_receipt(
        operation: str,
        amount: float,
        time: float,
        source: str,
        accepted: bool,
        reason: str,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        nonlocal current, consumed
        before = current
        if accepted:
            current -= amount
            consumed += 1
        receipts.append(
            {
                "owner": "main",
                "kind": "chimes",
                "operation": operation,
                "amount": amount,
                "time": round(float(time), 3),
                "source": source,
                "sequence": len(receipts) + 1,
                "tier": 0.0,
                "atoms": [],
                "current_before": before,
                "maximum_before": 200,
                "current_after": current,
                "maximum_after": 200,
                "accepted": accepted,
                "reason": reason,
                **(dict(detail) if detail else {}),
            }
        )

    # The accepted stream: one meep consumed per meep-empowered auto,
    # with the engine's per-swing timestamps as the event identity.
    meep_row = state.breakdown.get("on_hit_ability_passive")
    events: list[Mapping[str, Any]] = []
    if isinstance(meep_row, dict):
        raw = meep_row.get("damage_events")
        if isinstance(raw, list):
            events = [event for event in raw if isinstance(event, dict)]
    if opening > 0 and events:
        for index, event in enumerate(events, start=1):
            event_time = float(event.get("time", 0.0))
            _add_receipt(
                "spend",
                1.0,
                event_time,
                "meep_empowered_auto",
                True,
                "",
                {
                    "event": "meep_auto",
                    "event_index": index,
                    "event_time": round(event_time, 3),
                },
            )
    elif meep_row is None or opening <= 0:
        _add_receipt(
            "deny", 0.0, 0.0, "no_meep_auto_event", False, "no_meep_auto_event"
        )
    else:
        _add_receipt(
            "deny",
            0.0,
            0.0,
            "meep_auto_without_identity",
            False,
            "missing_identity",
        )

    # Named fail-closed denials for the unsupported chime/meep surfaces.
    for source in ("chime_spawn", "chime_collect"):
        _add_receipt(
            "deny",
            0.0,
            0.0,
            f"unsupported_chime_source:{source}",
            False,
            "unsupported_chime_source:"
            + source
            + " — the model cannot simulate map chime spawning/collection",
            {"event": source, "event_time": 0.0},
        )
    _add_receipt(
        "deny",
        0.0,
        0.0,
        "unsupported_meep_effect:slow",
        False,
        "unsupported_meep_effect:slow — the meep slow (25%..75% at 5+ "
        "chimes) is CC with no damage component",
        {"event": "meep_slow", "event_time": 0.0},
    )
    _add_receipt(
        "deny",
        0.0,
        0.0,
        "unsupported_meep_effect:splash",
        False,
        "unsupported_meep_effect:splash — the 15+ chime splash/cone "
        "never hits the primary target (single-target model)",
        {"event": "meep_splash", "event_time": 0.0},
    )
    _add_receipt(
        "deny",
        0.0,
        0.0,
        "meep_event_without_identity",
        False,
        "missing_identity",
    )

    availability = {
        "stock": stock,
        "recharge": recharge,
        "max_procs": opening,
        "recharges": recharges,
        "window_seconds": float(state.fight_duration_seconds or 0.0),
    }

    ledger_section = rotation.resource_ledger
    if not isinstance(ledger_section, dict):
        ledger_section = {}
        rotation.resource_ledger = ledger_section
    ledger_section["chimes"] = {
        "contract": "resource_ledger_v1",
        "owner": "main",
        "kind": "chimes",
        "opening_maximum": 200,
        "opening_current": seeded,
        "closing_maximum": 200,
        "closing_current": current,
        "base_maximum": 200,
        "bonus_maximum": 0,
        "receipts": receipts,
        "availability": availability,
        "threshold_transitions": [
            {
                "chimes": seeded,
                "per_meep_damage": per_meep,
                "stock": stock,
                "recharge_seconds": recharge,
                "stat_application": "parse_time_seeded",
            }
        ],
        "declaration": BARD_TRAVELERS_CALL_RULE.public_receipt(),
    }
    state.breakdown["chimes"] = {
        "name": BARD_TRAVELERS_CALL_RULE.public_receipt()["name"],
        "owner": "champion",
        "informational": True,
        "event_phase": "auto",
        "count": consumed,
        "starting_stacks": seeded,
        "state": f"{seeded} seeded chimes (permanent); {current} at fight end",
        "max_stacks": 200,
        "spend_events": [
            receipt for receipt in receipts if receipt["operation"] == "spend"
        ],
        "availability": availability,
    }
    if consumed:
        state.notes.append(
            f"Bard Meeps: {consumed} meep-empowered auto(s) consumed "
            f"{consumed} of {opening} available ({stock} stock + "
            f"{recharges} recharge); {current} chimes at fight end."
        )
    else:
        state.notes.append(
            "Bard Meeps: no meep-empowered auto (stocked meeps "
            "unconsumed; chime collection is a named unsupported source)."
        )


def _add_aurelion_sol_stardust(state: FightState, rotation: RotationResult) -> None:
    """Add Aurelion Sol's Cosmic Creator Stardust counter ledger (P3 3X).

    Stardust is a PERMANENT counter generated by damaging abilities; the
    only ACCEPTED live gain the engine certifies is the Q burst against
    the champion target (+2 per burst — game QMassStolen 2.0, wiki "the
    beam will deal a burst ... and additionally generates 2 Stardust if
    they are a champion").  Champion takedowns grant NO Stardust (they
    only refund W's cooldown), so the Senna takedown synthesis is NOT
    reused — a takedown event is a named denial.  The walk is
    documentary: it receipts the gains, the per-100 display milestones,
    and the fail-closed denials into an additive
    ``resource_ledger["stardust"]`` (kind "stardust") sub-section — the
    mana account is never replaced — and never re-prices any damage.
    """
    if "stardust_stacks" not in (state.champion_options or {}):
        return
    from .champions.aurelion_sol import (
        AURELION_SOL_STARDUST_RULE,
        _Q_BURSTS_PER_CHANNEL,
        _STARDUST_PER_Q_BURST,
    )

    option = state.champion_options or {}
    try:
        seeded = int(option.get("stardust_stacks", 0) or 0)
    except (TypeError, ValueError):
        seeded = 0
    if not (0 <= seeded <= 999):
        seeded = max(0, min(seeded, 999))
    receipts: list[dict[str, Any]] = []
    milestones: list[dict[str, Any]] = []
    current = seeded
    gains = 0

    def _add_receipt(
        operation: str,
        amount: float,
        time: float,
        source: str,
        accepted: bool,
        reason: str,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        nonlocal current, gains
        before = current
        if accepted:
            current += amount
            gains += 1
        receipts.append(
            {
                "owner": "main",
                "kind": "stardust",
                "operation": operation,
                "amount": amount,
                "time": round(float(time), 3),
                "source": source,
                "sequence": len(receipts) + 1,
                "tier": 0.0,
                "atoms": [],
                "current_before": before,
                "maximum_before": 999,
                "current_after": current,
                "maximum_after": 999,
                "accepted": accepted,
                "reason": reason,
                **(dict(detail) if detail else {}),
            }
        )

    # The accepted stream: one Q burst vs the champion target per full
    # second of channel (timed) or 3 per Q cast (one-rotation/auto-only),
    # mirroring the module's _channel_window semantics from state fields.
    q_casts = [
        event for event in rotation.cast_events if str(event.get("slot", "")) == "Q"
    ]
    timed = not (state.one_rotation or state.auto_attacks_only)
    bursts_per_cast = (
        int(state.fight_duration_seconds) if timed else _Q_BURSTS_PER_CHANNEL
    )
    if q_casts and bursts_per_cast > 0:
        for cast in q_casts:
            cast_time = float(cast.get("time", 0.0))
            ordinal = int(cast.get("ordinal", 0) or 0)
            for burst_index in range(bursts_per_cast):
                _add_receipt(
                    "gain",
                    _STARDUST_PER_Q_BURST,
                    cast_time,
                    "q_burst_champion",
                    True,
                    "",
                    {
                        "event": "q_burst",
                        "source_key": "Q",
                        "cast_ordinal": ordinal,
                        "burst_index": burst_index + 1,
                        "event_time": round(cast_time, 3),
                    },
                )
    else:
        _add_receipt("gain", 0.0, 0.0, "q_burst_champion", False, "no_q_burst_event")

    # Named fail-closed denials for the unsupported Stardust sources.
    for source in (
        "champion_takedown",
        "e_champion_seconds",
        "e_kill_bounty",
        "r_multihit",
        "minion_farm",
    ):
        _add_receipt(
            "gain",
            0.0,
            0.0,
            f"unsupported_stardust_source:{source}",
            False,
            f"unsupported_stardust_source:{source}",
            {"event": source, "event_time": 0.0},
        )
    _add_receipt(
        "gain",
        0.0,
        0.0,
        "stardust_event_without_identity",
        False,
        "missing_identity",
    )

    # Per-100 display milestones: both priced terms are LINEAR — the rows
    # document the display values and never re-price (mechanical False).
    breakpoint = AURELION_SOL_STARDUST_RULE.execute_breakpoint_stacks
    milestone = seeded // breakpoint * breakpoint + breakpoint
    while milestone <= current:
        k = milestone // breakpoint
        milestones.append(
            {
                "threshold": milestone,
                "threshold_count": milestone,
                "q_burst_maxhp_pct": (
                    AURELION_SOL_STARDUST_RULE.q_burst_maxhp_pct_per_100 * k
                ),
                "e_execute_threshold_pct": (
                    AURELION_SOL_STARDUST_RULE.e_execute_base_pct
                    + AURELION_SOL_STARDUST_RULE.e_execute_pct_per_100 * k
                ),
                "execute_pct_delta": AURELION_SOL_STARDUST_RULE.e_execute_pct_per_100,
                "mechanical": False,
                "stacks_before": milestone - breakpoint,
                "stacks_after": milestone,
                "stat_application": "parse_time_seeded",
            }
        )
        milestone += breakpoint

    ledger_section = rotation.resource_ledger
    if not isinstance(ledger_section, dict):
        ledger_section = {}
        rotation.resource_ledger = ledger_section
    ledger_section["stardust"] = {
        "contract": "resource_ledger_v1",
        "owner": "main",
        "kind": "stardust",
        "opening_maximum": 999,
        "opening_current": seeded,
        "closing_maximum": 999,
        "closing_current": current,
        "base_maximum": 999,
        "bonus_maximum": 0,
        "receipts": receipts,
        "threshold_transitions": milestones,
        "declaration": AURELION_SOL_STARDUST_RULE.public_receipt(),
    }
    state.breakdown["stardust"] = {
        "name": AURELION_SOL_STARDUST_RULE.public_receipt()["name"],
        "owner": "champion",
        "informational": True,
        "event_phase": "effect",
        "count": gains,
        "starting_stacks": seeded,
        "state": f"{seeded} seeded Stardust; {current} at fight end",
        "max_stacks": 999,
        "gain_events": [
            receipt for receipt in receipts if receipt["operation"] == "gain"
        ],
        "threshold_transitions": milestones,
    }
    if gains:
        state.notes.append(
            f"Aurelion Sol Stardust: {current} stacks at fight end "
            f"({gains} Q-burst champion hit(s) gained over the seeded "
            f"{seeded})."
        )
    else:
        state.notes.append(
            f"Aurelion Sol Stardust: {current} stacks (no Q burst — the "
            "seeded counter is the whole admission; E champion-seconds, E "
            "kill bounties, R multihits, and minion farming are named "
            "unsupported sources)."
        )


def _slot_ordinals(rotation: RotationResult, slot: str) -> list[int]:
    """The accepted-cast ordinals of one basic-ability slot."""
    return [
        int(event.get("ordinal", 0) or 0) - 1
        for event in rotation.cast_events
        if str(event.get("slot", "")) == slot
    ]


def _add_rengar_ferocity(state: FightState, rotation: RotationResult) -> None:
    """Add Rengar's live Ferocity stack timeline receipt (P3 package 3V).

    The stack machine already ran inside the rotation (``_build_ferocity_
    timeline`` priced the empowered casts); this walk publishes the same
    accepted Q/W/E cast stream as the breakdown's ``ferocity`` row with
    the kernel's stack_events and state_transitions, mirroring the
    Conqueror receipt shape.
    """
    timeline = getattr(state, "ferocity_timeline", None)
    if timeline is None:
        return
    stack = timeline.stack
    rule = stack.rule
    cast_events = [
        event
        for event in rotation.cast_events
        if str(event.get("slot", "")) in {"Q", "W", "E"}
    ]
    # P3 package 3V fail-closed: a requested cast slot that is not one of
    # the champion's known slots authors a named denial receipt instead of
    # being silently dropped (the counter ledger's accepted=False row).
    known_slots = set(state.ability_damages)
    for slot in state.cast_order:
        if slot in {"Q", "W", "E"} or slot in known_slots:
            continue
        if not any(
            receipt.get("reason", "").startswith("unknown_cast_slot")
            for receipt in timeline.receipts
        ):
            timeline.receipts.append(
                {
                    "operation": "gain",
                    "amount": 0.0,
                    "time": 0.0,
                    "source": f"{slot} cast",
                    "sequence": len(timeline.receipts),
                    "tier": 0.0,
                    "atoms": [],
                    "current_before": stack.stacks,
                    "maximum_before": rule.max_stacks,
                    "current_after": stack.stacks,
                    "maximum_after": rule.max_stacks,
                    "accepted": False,
                    "reason": f"unknown_cast_slot:{slot}",
                }
            )
    state.breakdown["ferocity"] = {
        "name": rule.name,
        "owner": "champion",
        "informational": True,
        "event_phase": "effect",
        "count": len(cast_events),
        "starting_stacks": timeline.starting_stacks,
        "state": (
            f"{timeline.starting_stacks}/4 Ferocity stacks (seeded); "
            f"{stack.stacks}/4 at fight end"
        ),
        "max_stacks": rule.max_stacks,
        "stack_duration_seconds": rule.duration_seconds,
        "combat_extension_seconds": rule.combat_extension_seconds,
        "stack_events": [
            {
                "time": round(float(event.get("time", 0.0)), 3),
                "slot": event.get("slot"),
                "ordinal": event.get("ordinal"),
                "empowered": timeline.cast_empowered(
                    str(event.get("slot", "")),
                    int(event.get("ordinal", 0) or 0) - 1,
                ),
            }
            for event in cast_events
        ],
        "state_transitions": stack.public_receipt()["transitions"],
    }
    if not cast_events:
        state.notes.append("Rengar Ferocity recorded no accepted basic-ability casts.")
    else:
        state.notes.append(
            f"Rengar Ferocity: {stack.stacks}/4 stacks at fight end "
            f"({len(cast_events)} accepted basic-ability casts)."
        )
    # P3 package 3V: the live empowered cast consumes the cap; later
    # casts of the same slot price the base values.  The module's static
    # detail describes the seeded branch — append the live consumption
    # note so the public breakdown reflects the actual first-cast-only
    # empowerment.
    for slot in ("Q", "W", "E"):
        empowered_any = any(
            timeline.cast_empowered(slot, ordinal)
            for ordinal in _slot_ordinals(rotation, slot)
        )
        base_any = any(
            not timeline.cast_empowered(slot, ordinal)
            for ordinal in _slot_ordinals(rotation, slot)
        )
        info = state.ability_damages.get(slot)
        row = state.breakdown.get(slot)
        detail = (
            str(row.get("detail", ""))
            if isinstance(row, dict)
            else str(info.get("detail", "")) if info is not None else ""
        )
        if not detail or not empowered_any or not base_any:
            continue
        if "consuming all 4 stacks" in detail and "later casts" not in detail:
            note = (
                "  (Live: only the first basic-ability cast at the cap is "
                "empowered; later casts price the base values.)"
            )
            if isinstance(row, dict):
                row["detail"] = detail + note
            elif info is not None:
                info["detail"] = detail + note


def _deathfire_trigger_events(
    state: FightState, rotation: RotationResult
) -> list[dict[str, Any]]:
    """Group ability damage into typed Deathfire burn applications."""
    ordered = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
    )
    detailed = [
        event
        for event in ordered
        if isinstance(event, Mapping)
        and event.get("is_ability")
        and float(event.get("damage", 0.0) or 0.0) > 0.0
    ]
    cast_times: dict[str, list[float]] = {}
    for cast in rotation.cast_events:
        slot = str(cast.get("slot", ""))
        if slot in state.cast_order:
            cast_times.setdefault(slot, []).append(float(cast.get("time", 0.0)))

    triggers: list[dict[str, Any]] = []
    for slot, times in cast_times.items():
        info = state.ability_damages.get(slot, {})
        category = str(info.get("deathfire_category", ""))
        if not category:
            continue
        slot_events = [event for event in detailed if event.get("source_key") == slot]
        for index, cast_time in enumerate(times):
            next_cast = times[index + 1] if index + 1 < len(times) else math.inf
            cast_events = [
                event
                for event in slot_events
                if cast_time - 1e-9
                <= float(event.get("time", cast_time))
                < next_cast - 1e-9
            ]
            if not cast_events:
                continue
            if category.startswith("persistent_"):
                # Persistent damage applies on each authored tick. Events at
                # one timestamp share one application, so repeated DamagePart
                # instances cannot create duplicate refreshes.
                by_time: dict[float, list[Mapping[str, Any]]] = {}
                for event in cast_events:
                    event_time = round(float(event.get("time", cast_time)), 9)
                    by_time.setdefault(event_time, []).append(event)
                for event_time, events in by_time.items():
                    triggers.append(
                        {
                            "time": event_time,
                            "sequence": min(
                                int(event.get("sequence", 0)) for event in events
                            ),
                            "source_key": slot,
                            "source": slot,
                            "category": category,
                            "damage": sum(
                                float(event.get("damage", 0.0) or 0.0)
                                for event in events
                            ),
                            "event_precision": min(
                                (
                                    str(event.get("event_precision", "cast_boundary"))
                                    for event in events
                                ),
                                key=lambda value: (value != "exact", value),
                            ),
                        }
                    )
                continue
            triggers.append(
                {
                    "time": min(
                        float(event.get("time", cast_time)) for event in cast_events
                    ),
                    "sequence": min(
                        int(event.get("sequence", 0)) for event in cast_events
                    ),
                    "source_key": slot,
                    "source": slot,
                    "category": category,
                    "damage": sum(
                        float(event.get("damage", 0.0) or 0.0) for event in cast_events
                    ),
                    "event_precision": min(
                        (
                            str(event.get("event_precision", "cast_boundary"))
                            for event in cast_events
                        ),
                        key=lambda value: (value != "exact", value),
                    ),
                }
            )
    return sorted(
        triggers,
        key=lambda event: (float(event["time"]), int(event["sequence"])),
    )


def _add_keystone_deathfire(state: FightState, rotation: RotationResult) -> None:
    """Add Deathfire Touch's refreshed, delayed magic burn."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneDeathfireEffect):
        return

    triggers = _deathfire_trigger_events(state, rotation)
    damage_events: list[dict[str, Any]] = []
    trigger_events: list[dict[str, Any]] = []
    active_start: float | None = None
    active_until = float("-inf")
    next_tick: float | None = None
    active_trigger: dict[str, Any] | None = None
    total_damage = 0.0
    amplified_ticks = 0

    def emit_until(limit: float) -> None:
        """Emit all authored ticks through one active burn boundary."""
        nonlocal next_tick, total_damage, amplified_ticks
        while next_tick is not None and next_tick <= limit + 1e-9:
            amplified = (
                active_start is not None
                and next_tick - active_start >= effect.amp_delay_seconds - 1e-9
            )
            raw_damage = effect.raw_tick(
                state.level,
                state.champion_stats,
                amplified=amplified,
            )
            mitigated = _mitigate(
                raw_damage,
                "magic",
                state.resists,
                state.magic_amp,
            )
            if mitigated > 0.0:
                source = active_trigger or {}
                damage_events.append(
                    {
                        "time": next_tick,
                        "damage": mitigated,
                        "raw_damage": raw_damage,
                        "damage_type": "magic",
                        "event_precision": "exact",
                        "trigger_time": float(source.get("time", next_tick)),
                        "trigger_source": source.get("source", "ability"),
                        "deathfire_category": source.get("category", "spell_damage"),
                        "amplified": amplified,
                    }
                )
                total_damage += mitigated
                amplified_ticks += int(amplified)
            next_tick += effect.tick_interval_seconds

    for trigger in triggers:
        trigger_time = float(trigger["time"])
        duration = effect.duration_for(str(trigger["category"]))
        if active_start is None or trigger_time > active_until + 1e-9:
            if active_start is not None:
                emit_until(active_until)
            active_start = trigger_time
            active_until = trigger_time + duration
            next_tick = trigger_time + effect.tick_interval_seconds
            active_trigger = trigger
            new_chain = True
        else:
            emit_until(trigger_time)
            active_until = trigger_time + duration
            active_trigger = trigger
            new_chain = False
        trigger_events.append(
            {
                **trigger,
                "duration_seconds": duration,
                "new_chain": new_chain,
                "event_precision": trigger.get("event_precision", "cast_boundary"),
            }
        )
    if active_start is not None:
        emit_until(active_until)

    state.breakdown[effect.breakdown_key] = {
        "name": effect.display_name,
        "total_damage": total_damage,
        "damage_type": "magic",
        "count": len(damage_events),
        "event_phase": "effect",
        "damage_events": damage_events,
        "trigger_events": trigger_events,
        "duration_by_category": dict(effect.duration_by_category),
        "tick_interval_seconds": effect.tick_interval_seconds,
        "amp_delay_seconds": effect.amp_delay_seconds,
        "amp_ratio": effect.amp_ratio,
        "amplified_tick_count": amplified_ticks,
        "pet_damage_category_modeled": False,
    }
    state.total_damage += total_damage
    if not triggers:
        state.notes.append(
            f"{effect.keystone_name} recorded no classified ability-damage "
            "application; pet damage remains unavailable without a typed pet "
            "packet."
        )
    else:
        state.notes.append(
            f"{effect.keystone_name} recorded {len(triggers)} typed burn "
            f"application(s), {len(damage_events)} tick(s), and "
            f"{amplified_ticks} amplified tick(s). Pet damage remains "
            "unavailable without a typed pet packet."
        )


def _add_keystone_fleet_footwork(state: FightState, rotation: RotationResult) -> None:
    """Add Fleet's charged heal and one-second movement-speed window."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneFleetEffect):
        return

    options = state.keystone_options or {}
    starting_charges = int(options.get("starting_charges", 0) or 0)
    movement_events: list[dict[str, Any]] = []
    heal_events: list[dict[str, Any]] = []
    base_row: dict[str, Any] = {
        "name": effect.display_name,
        "informational": True,
        "event_phase": "effect",
        "count": 0,
        "starting_charges": starting_charges,
        "charge_cap": effect.charge_cap,
        "movement_events": movement_events,
    }
    state.breakdown[effect.breakdown_key] = base_row

    if starting_charges < effect.charge_cap:
        state.notes.append(
            f"{effect.keystone_name} is withheld: the fight starts with "
            f"{starting_charges} of {effect.charge_cap} sourced charges, and "
            "the charge gain rate is not authored in the cached rune source."
        )
        return

    forced_times = _forced_basic_attack_times(state, rotation)
    if state.num_auto_attacks > 0:
        attack_times = _auto_attack_timestamps(state)
        carrier = "ambient basic attacks"
    elif forced_times:
        attack_times = forced_times
        carrier = "forced basic attacks"
    else:
        state.notes.append(
            f"{effect.keystone_name} never procced: the fight had no "
            "authored basic-attack landing."
        )
        return
    if not attack_times:
        state.notes.append(
            f"{effect.keystone_name} never procced: the shared attack schedule "
            "did not publish a landing."
        )
        return

    event_time = float(attack_times[0])
    heal_amount = effect.heal_amount(
        state.level,
        state.champion_stats,
        state.is_melee,
    )
    move_speed = effect.bonus_move_speed_percent(state.is_melee)
    movement_event = {
        "time": event_time,
        "kind": "movement",
        "amount": move_speed,
        "bonus_move_speed_percent": move_speed,
        "duration": effect.move_speed_duration_seconds,
        "source": "Fleet Footwork · Energized movement speed",
        "source_key": effect.breakdown_key,
        "target_scope": "self",
        "target_policy": "self",
        "fleet_starting_charges": starting_charges,
        "fleet_charge_cap": effect.charge_cap,
        "fleet_move_speed_duration_seconds": effect.move_speed_duration_seconds,
        "event_precision": "exact",
        "_event_id": "main:fleet-footwork:movement:0",
        "_priority": -1.0,
    }
    movement_events.append(movement_event)
    heal_event = {
        "time": event_time,
        "amount": heal_amount,
        "trigger_source": "auto_attacks",
        "actor_wide": True,
        "kind": "keystone",
        "healing_category": "direct",
        "_event_id": "main:fleet-footwork:heal:0",
    }
    heal_events.append(heal_event)
    state.breakdown[f"heal_{effect.keystone_name}"] = {
        "name": f"{effect.display_name} (self-heal)",
        "owner": "keystone",
        "count": 1,
        "amount_per_proc": heal_amount,
        "total_amount": heal_amount,
        "unit": "health",
        "heal_events": heal_events,
        "event_phase": "heal",
    }
    base_row.update(
        {
            "count": 1,
            "movement_speed_percent": move_speed,
            "move_speed_duration_seconds": effect.move_speed_duration_seconds,
        }
    )
    state.notes.append(
        f"{effect.keystone_name} used one Energized basic attack from {carrier}. "
        f"The sourced {move_speed:g}% movement-speed window lasts "
        f"{effect.move_speed_duration_seconds:g}s."
    )


def _add_keystone_proc_amp_damage(state: FightState, rotation: RotationResult) -> None:
    """Add Press the Attack-class proc damage and its lasting amplifier.

    The stacked proc prices leveled adaptive damage per proc, exactly
    like an Electrocute-class row. From the first proc onward the buff
    amplifies every certified non-true damage event by the sourced
    ratio until combat ends — a continuous fight never drops it. The
    triggering swing and the first proc itself predate the buff, so
    only events strictly after the first proc time are amplified;
    coarse-timed sources are excluded and disclosed, keeping the amp a
    floor, never an estimate.
    """
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneProcAmpEffect):
        return
    proc_times, cooldown_gated = _refreshing_stack_proc_times(state, effect)
    if not proc_times:
        # A selected keystone that never fires must say so — only basic
        # attacks stack it, so ability-only or slow-swing fights get zero.
        state.notes.append(
            f"{effect.keystone_name} never procced: the simulated fight "
            f"never landed {effect.stacks_required} basic attacks within "
            f"its {effect.stack_duration_seconds:g}s stack duration."
        )
        return
    _record_keystone_proc_row(state, effect, proc_times)
    if cooldown_gated:
        state.notes.append(
            f"{effect.keystone_name} stacks are assumed not to build during "
            f"its {effect.cooldown_seconds:g}s per-target cooldown (the wiki "
            "does not document this); re-procs may land late, so the proc "
            "count is a floor."
        )

    # The amp reads the ledger after the proc row exists, so later procs
    # (adaptive, never true damage) are amplified while the first — which
    # lands the same instant the buff turns on — is excluded by the
    # strictly-after cut, matching the wiki's triggering-attack rule.
    amp_start = proc_times[0]
    events, certified, coarse_sources = _certified_ledger(state, rotation)
    amplified = [
        event
        for event in events
        if event["source_key"] in certified
        and event["time"] > amp_start
        and event["damage_type"] != "true"
    ]
    if amplified:
        amp_by_type: dict[str, float] = {}
        for event in amplified:
            bonus = effect.damage_amp_ratio * event["damage"]
            amp_by_type[event["damage_type"]] = (
                amp_by_type.get(event["damage_type"], 0.0) + bonus
            )
        amp_total = sum(amp_by_type.values())
        state.breakdown[effect.amp_breakdown_key] = {
            "name": effect.amp_display_name,
            "total_damage": amp_total,
            "damage_by_type": amp_by_type,
            "count": 1,
            "event_phase": "effect",
            "damage_events": [
                {
                    "time": event["time"],
                    "damage": effect.damage_amp_ratio * event["damage"],
                    "damage_type": event["damage_type"],
                }
                for event in amplified
            ],
        }
        state.total_damage += amp_total
    if coarse_sources:
        state.notes.append(
            f"{effect.keystone_name} amp excludes sources without "
            f"certified event times ({', '.join(sorted(coarse_sources))}); "
            "its bonus is a floor, not an estimate."
        )


def _add_item_active_damage(state: FightState, rotation: RotationResult) -> None:
    """Add active-item damage (skipped when actives are excluded).

    Each active is cast once. The engine's standing assumption — the
    same one the coarse ledger encoded — is that it fires with the end
    of the rotation opener, so its event is stamped at the last accepted
    damaging cast (fight start when there are no casts).
    """
    if not state.include_actives:
        return
    resists = state.resists
    active_time = max(_damaging_cast_times(state, rotation), default=0.0)
    secondary_item_name = item_effects.active_secondary_ad_item_name(state.items)
    for source in state.damage_effects.actives:
        raw_active = source.raw_damage(_damage_inputs(state))
        active_mitigated = _mitigate(
            raw_active, source.damage_type, resists, state.magic_amp
        )

        damage_events = [
            {
                "time": active_time,
                "damage": active_mitigated,
                "damage_type": source.damage_type,
            }
        ]
        state.breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": active_mitigated,
            "damage_type": source.damage_type,
            "damage_events": damage_events,
        }
        if source.lifesteal_effectiveness > 0.0:
            heal_amount = _active_lifesteal_amount(
                state, damage_events[0], source.lifesteal_effectiveness
            )
            if heal_amount is not None:
                state.breakdown[f"heal_{source.item_name}"] = {
                    "name": f"{source.item_name} (life steal)",
                    "count": 1,
                    "proc_times": [active_time],
                    "amount_per_proc": heal_amount,
                    "total_amount": heal_amount,
                    "unit": "health",
                }

        secondary_target_count = max(0, state.roster_target_count - 1)
        if (
            source.item_name == secondary_item_name
            and secondary_target_count > 0
            and 1 <= state.roster_target_index <= secondary_target_count
        ):
            raw_secondary = item_effects.hydra_cleave_secondary_ad_damage(
                total_attack_damage=state.champion_stats.get("attack_damage", 0.0),
                is_melee=state.is_melee,
                item_name=source.item_name,
            )
            secondary_mitigated = _mitigate(
                raw_secondary, source.damage_type, resists, state.magic_amp
            )
            secondary_key = f"secondary_{source.item_name}"
            secondary_event = {
                "time": active_time,
                "damage": secondary_mitigated,
                "damage_type": source.damage_type,
            }
            state.breakdown[secondary_key] = {
                "name": f"{source.display_name} (secondary)",
                "count": 1,
                "unit": "packets",
                "total_damage": secondary_mitigated,
                "damage_type": source.damage_type,
                "damage_events": [secondary_event],
                "targeting": {
                    "kind": "active_secondary",
                    "secondary_target_count": secondary_target_count,
                    "allocated_target_index": state.roster_target_index,
                    "roster_target_count": state.roster_target_count,
                },
            }
            if source.lifesteal_effectiveness > 0.0:
                heal_amount = _active_lifesteal_amount(
                    state, secondary_event, source.lifesteal_effectiveness
                )
                if heal_amount is not None:
                    state.breakdown[f"heal_{source.item_name}"] = {
                        "name": f"{source.item_name} (life steal)",
                        "count": 1,
                        "proc_times": [active_time],
                        "amount_per_proc": heal_amount,
                        "total_amount": heal_amount,
                        "unit": "health",
                    }
            state.total_damage += secondary_mitigated
        state.total_damage += active_mitigated


_CERTIFIED_CAST_PRECISIONS = frozenset({"single_hit", "auto_stack_proc"})


def _item_proc_precision(state: FightState, slot: str) -> str:
    """Return the event precision an item proc rides on one ability cast.

    An ordered item trigger (Muramana Shock, Eclipse stacking, Shaped
    Charge) lands on the ability's hit.  For an ability whose cast boundary
    IS the authored hit — a module ``single_hit`` / ``auto_stack_proc``
    marker, or a cast-order row with casts and no DoT, the same condition
    the coverage classifier uses to certify it — the proc event is
    ``exact``.  Generic/uncertified abilities and DoT casts keep
    ``cast_boundary``, which the coverage classifier treats as coarse and
    the BIS optimizer excludes — the fail-closed contract for abilities
    whose hit timing is not proven.
    """
    info = state.ability_damages.get(slot)
    if isinstance(info, Mapping):
        certified = info.get("event_order_certified")
        if isinstance(certified, str) and certified in _CERTIFIED_CAST_PRECISIONS:
            return "exact"
        # The DoT check reads the ABILITY packet's dot duration (P3 package
        # 3D): breakdown rows never carry dot_duration, so reading it there
        # was a dead branch that stamped uncertified DoT casts as exact.
        dot = float(info.get("dot_duration", 0.0) or 0.0)
    else:
        dot = 0.0
    # Unit-test states (SimpleNamespace) may omit the fight breakdown; the
    # cast-order check is best-effort there and fails closed to boundary.
    row = getattr(state, "breakdown", None)
    if isinstance(row, Mapping):
        row = row.get(slot)
    cast_order = getattr(state, "cast_order", None)
    if cast_order is not None and slot in cast_order and isinstance(row, Mapping):
        casts = int(row.get("casts", 0) or 0)
        if casts > 0 and dot <= 0.0:
            return "exact"
    return "cast_boundary"


@dataclass(frozen=True, slots=True)
class _MuramanaCastReceipt:
    """Validated inputs for one Muramana cast-ledger row."""

    slot: str
    event_time: float
    cast_id: str | None
    target_id: str | None
    raw_instances: int
    authored_events: list[dict[str, Any]] | None
    proc_precision: str


def _muramana_cast_receipt(
    state: FightState,
    cast_event: Any,
    breakdown: Mapping[str, Any],
    *,
    require_identity: bool,
) -> _MuramanaCastReceipt | None:
    """Validate one cast row and collect its proc-event inputs."""
    if not isinstance(cast_event, Mapping):
        return None
    slot = cast_event.get("slot")
    ability = state.ability_damages.get(slot) if isinstance(slot, str) else None
    if not isinstance(slot, str) or not isinstance(ability, Mapping):
        return None
    parts = ability.get("parts", ())
    if not isinstance(parts, (tuple, list)):
        return None
    if not any(
        getattr(part, "amount", 0.0) > 0.0
        or getattr(part, "hp_scaled_damage", None) is not None
        for part in parts
    ):
        return _MuramanaCastReceipt(slot, 0.0, None, None, 0, None, "")
    event_time = _finite_numeric_receipt(cast_event.get("time"))
    cast_id = cast_event.get("cast_id")
    target_id = cast_event.get("target_id")
    raw_instances = ability.get("cast_instances", 1)
    if (
        event_time is None
        or event_time < 0.0
        or (
            require_identity
            and (
                not isinstance(cast_id, str)
                or not cast_id.strip()
                or not isinstance(target_id, str)
                or not target_id.strip()
            )
        )
        or isinstance(raw_instances, bool)
        or not isinstance(raw_instances, int)
        or raw_instances <= 0
    ):
        return None
    row = breakdown.get(slot)
    authored_events = row.get("damage_events") if isinstance(row, Mapping) else None
    return _MuramanaCastReceipt(
        slot=slot,
        event_time=event_time,
        cast_id=cast_id if isinstance(cast_id, str) else None,
        target_id=target_id if isinstance(target_id, str) else None,
        raw_instances=raw_instances,
        authored_events=authored_events if isinstance(authored_events, list) else None,
        proc_precision=_item_proc_precision(state, slot),
    )


def _muramana_identity_fields(
    receipt: _MuramanaCastReceipt,
    instance_index: int,
    *,
    enabled: bool,
) -> dict[str, str]:
    """Return the validated target and per-instance cast identity fields."""
    if not enabled:
        return {}
    cast_id = receipt.cast_id
    if receipt.raw_instances > 1:
        cast_id = f"{cast_id}:{instance_index + 1}"
    return {"cast_id": str(cast_id), "target_id": str(receipt.target_id)}


def _muramana_authored_events(
    receipt: _MuramanaCastReceipt,
    cursor: int,
    *,
    include_identity: bool,
) -> tuple[list[dict[str, Any]], int] | None:
    """Consume one positive authored packet for each cast instance."""
    authored_events = receipt.authored_events
    if authored_events is None:
        return None
    events: list[dict[str, Any]] = []
    for instance_index in range(receipt.raw_instances):
        while cursor < len(authored_events):
            candidate = authored_events[cursor]
            cursor += 1
            if not isinstance(candidate, Mapping):
                return None
            candidate_time = _finite_numeric_receipt(candidate.get("time"))
            candidate_damage = _finite_numeric_receipt(candidate.get("damage"))
            if candidate_time is None or candidate_damage is None:
                return None
            if candidate_time + 1e-9 < receipt.event_time:
                continue
            if candidate_damage <= 0.0:
                continue
            precision = candidate.get("event_precision")
            if not isinstance(precision, str) or not precision.strip():
                return None
            events.append(
                {
                    "time": candidate_time,
                    "damage": 0.0,
                    "event_precision": precision,
                    **_muramana_identity_fields(
                        receipt, instance_index, enabled=include_identity
                    ),
                }
            )
            break
        else:
            return None
    return events, cursor


def _muramana_boundary_events(
    receipt: _MuramanaCastReceipt, *, include_identity: bool
) -> list[dict[str, Any]]:
    """Build one cast-boundary event for each validated cast instance."""
    return [
        {
            "time": receipt.event_time,
            "damage": 0.0,
            "event_precision": receipt.proc_precision,
            **_muramana_identity_fields(
                receipt, instance_index, enabled=include_identity
            ),
        }
        for instance_index in range(receipt.raw_instances)
    ]


def _apply_muramana_lockout(
    events: list[dict[str, Any]], lockout_seconds: float | None
) -> list[dict[str, Any]]:
    """Filter exact event identities through the shared cadence primitive."""
    if lockout_seconds is None:
        return events
    cadence = InstanceCadence(interval_seconds=lockout_seconds)
    return [
        event
        for event in events
        if cadence.allow(
            float(event["time"]),
            f"{event['target_id']}|cast:{event['cast_id']}",
        )
    ]


def _muramana_proc_events(
    state: FightState,
    rotation: RotationResult,
    *,
    lockout_seconds: float | None = None,
) -> list[dict[str, Any]] | None:
    """Build lockout-filtered events for authored Muramana proc instances.

    Cast ID, target ID, exact hit time, and the parser-owned lockout are
    required. A malformed receipt withholds the event list. The caller can
    then use the existing named aggregate fallback.
    """
    if rotation.total_muramana_procs <= 0:
        return []
    gate_enabled = lockout_seconds is not None
    if gate_enabled and (not math.isfinite(lockout_seconds) or lockout_seconds <= 0.0):
        return None
    events: list[dict[str, Any]] = []
    event_cursors: dict[str, int] = {}
    breakdown = getattr(state, "breakdown", {})
    if not isinstance(breakdown, Mapping):
        breakdown = {}
    for cast_event in rotation.cast_events:
        receipt = _muramana_cast_receipt(
            state, cast_event, breakdown, require_identity=gate_enabled
        )
        if receipt is None:
            return None
        if receipt.raw_instances == 0:
            continue
        if receipt.authored_events is not None:
            authored = _muramana_authored_events(
                receipt,
                event_cursors.get(receipt.slot, 0),
                include_identity=gate_enabled,
            )
            if authored is None:
                return None
            event_cursors[receipt.slot] = authored[1]
            events.extend(authored[0])
            continue
        events.extend(_muramana_boundary_events(receipt, include_identity=gate_enabled))
    if len(events) != rotation.total_muramana_procs:
        return None
    return _apply_muramana_lockout(events, lockout_seconds)


def _first_damaging_ability_event(
    state: FightState, rotation: RotationResult
) -> tuple[float, str] | None:
    """Return the first authored damaging ability event, if one exists.

    Voltaic's current Galvanize branch can consume a ready Energized effect
    from an ability. Prefer a module-authored packet timestamp; when a
    generated module has only an authored damaging cast total, use the
    sourced ability-cast instance as the trigger boundary. That boundary is
    distinct from an uncertified packet timestamp: Galvanize is defined by
    the ability cast instance, not by an invented sub-event order.
    """
    for cast_event in rotation.cast_events:
        if not isinstance(cast_event, Mapping):
            continue
        slot = cast_event.get("slot")
        if not isinstance(slot, str):
            continue
        cast_time = _finite_numeric_receipt(cast_event.get("time"))
        if cast_time is None:
            continue
        row = state.breakdown.get(slot)
        if isinstance(row, Mapping):
            events = row.get("damage_events")
            if isinstance(events, list):
                positive = [
                    event
                    for event in events
                    if isinstance(event, Mapping)
                    and _finite_numeric_receipt(event.get("damage")) not in (None, 0.0)
                ]
                if positive:
                    first = min(
                        positive,
                        key=lambda event: float(event.get("time", 0.0)),
                    )
                    event_time = _finite_numeric_receipt(first.get("time"))
                    if event_time is not None:
                        event_precision = str(
                            first.get("event_precision", "cast_boundary")
                        )
                        return event_time, event_precision
            if float(row.get("total_damage", 0.0) or 0.0) > 0.0:
                return cast_time, "ability_cast_instance"
    return None


def _author_energized_ability_proc(
    state: FightState,
    rotation: RotationResult,
    effect: item_effects.FirstAutoEffect,
    effectiveness: float,
) -> bool:
    """Author one Galvanize packet before its triggering ability.

    The return value tells the auto scheduler that the opening charge was
    consumed.  A missing authored damaging ability is not an error: the item
    remains ready for the ordinary explicit auto schedule.
    """
    if not effect.energized_ability_trigger or effect.energized_max_stacks <= 0:
        return False
    ability_event = _first_damaging_ability_event(state, rotation)
    if ability_event is None:
        return False
    ability_proc_time, ability_proc_precision = ability_event
    source = effect.source
    ability_raw = source.raw_damage(_damage_inputs(state)) * effectiveness
    ability_mitigated = _mitigate(
        ability_raw, source.damage_type, state.resists, state.magic_amp
    )
    if ability_mitigated <= 0.0:
        return False
    ability_key = f"{source.breakdown_key}_ability"
    ability_row: dict[str, Any] = {
        "name": f"{source.display_name} (Galvanize)",
        "count": 1,
        "damage_per_hit": ability_mitigated,
        "unit": "procs",
        "total_damage": ability_mitigated,
        "damage_type": source.damage_type,
        "event_phase": "ability",
        "damage_events": [
            {
                "time": ability_proc_time,
                "damage": ability_mitigated,
                "damage_type": source.damage_type,
                # Firmament is an ordered pre-packet effect, so it sorts
                # before the triggering ability packet at the same time.
                "timeline_order": -1.0,
                "event_precision": ability_proc_precision,
            }
        ],
    }
    ability_row["energized_schedule"] = item_effects.energized_schedule_receipt(
        source.item_name
    )
    temporary_lethality = (
        effect.temporary_lethality_melee
        if state.is_melee
        else effect.temporary_lethality_ranged
    )
    if temporary_lethality > 0 and effect.temporary_lethality_duration > 0:
        ability_row["temporary_lethality"] = {
            "amount": temporary_lethality,
            "duration": effect.temporary_lethality_duration,
            "applies_before_event": True,
            "applied_to_triggering_event": True,
            "applied_to_later_events": False,
            "note": (
                "Galvanize Firmament is applied before the triggering ability, "
                "per the sourced Wiki entry."
            ),
        }
    state.breakdown[ability_key] = ability_row
    state.total_damage += ability_mitigated
    return True


def _target_health_before_timestamp(state: FightState, timestamp: float) -> float:
    """Return target HP before authored packets at ``timestamp``.

    Current-health item formulas read the shared event ledger rather than the
    fight aggregate.  Untimed rows are deliberately ignored: they cannot
    justify a fabricated HP transition and remain an explicit coverage gap.
    """
    dealt = 0.0
    for row in state.breakdown.values():
        if not isinstance(row, Mapping):
            continue
        events = row.get("damage_events")
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, Mapping):
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


def _first_auto_damage_by_auto_for_health_walk(
    state: FightState,
    rotation: RotationResult,
    num_auto_attacks: int,
    swing_times: Sequence[float],
    effectiveness: float,
) -> list[float]:
    """Price first-auto packets as HP inputs without authoring them twice.

    ``_layer_on_hit_effects`` runs before ``_add_single_proc_on_hits``.  The
    latter owns the output rows/total, while this helper supplies only the
    packets' mitigated damage to the BoRK HP walk.  Keeping the two concerns
    separate prevents the first-auto packet from being added to fight damage
    twice.
    """
    if num_auto_attacks <= 0:
        return []

    packets = [0.0] * num_auto_attacks
    for effect in state.damage_effects.first_autos:
        source = effect.source
        if not item_effects.first_auto_state_ready(
            state.items, state.item_options, source.item_name
        ):
            continue
        # Galvanize consumes an energized charge on the first damaging ability;
        # that packet is not also an auto packet.  The authoring pass handles
        # the actual ability row; this HP-only pass just omits its auto index.
        ability_consumed = (
            effect.energized_ability_trigger
            and effect.energized_max_stacks > 0
            and _first_damaging_ability_event(state, rotation) is not None
        )
        if effect.chain_targets_max > 0:
            chain_target_count = item_effects.statikk_chain_target_count(state.level)
            allocated_targets = min(
                max(1, state.roster_target_count), chain_target_count
            )
            if state.roster_target_index >= allocated_targets:
                continue
        if ability_consumed:
            initial_stacks = 0.0
        else:
            initial_stacks = float(effect.energized_max_stacks)
        if effect.energized_max_stacks > 0:
            proc_indices = item_effects.energized_proc_indices(
                source.item_name,
                num_auto_attacks,
                initial_stacks=initial_stacks,
            )
        else:
            proc_indices = tuple(range(min(effect.max_procs, num_auto_attacks)))
        for proc_index in proc_indices:
            if proc_index >= num_auto_attacks:
                continue
            if proc_index < len(swing_times):
                target_current_health = _target_health_before_timestamp(
                    state, float(swing_times[proc_index])
                )
            else:
                target_current_health = float(state.target_health)
            raw = (
                source.raw_damage(
                    _damage_inputs(state, target_current_health=target_current_health)
                )
                * effectiveness
            )
            mitigated = _mitigate(
                raw, source.damage_type, state.resists, state.magic_amp
            )
            if source.basic_damage and source.damage_type != "true":
                mitigated *= state.target_basic_damage_multiplier
            packets[proc_index] += max(0.0, mitigated)
    return packets


def _copied_on_hit_packet(
    state: FightState,
    on_hits: OnHitResult,
    effectiveness: float,
    target_current_health: float,
) -> dict[str, float]:
    """Resolve one copied on-hit packet, including current-health effects."""
    packets = {
        damage_type: float(amount)
        for damage_type, amount in on_hits.static_on_hit_by_type.items()
        if amount > 0.0
    }
    for effect in state.damage_effects.per_hits:
        if not effect.tracks_current_health:
            continue
        raw = (
            effect.source.raw_damage(
                _damage_inputs(state, target_current_health=target_current_health)
            )
            * effectiveness
        )
        if raw <= 0.0:
            continue
        mitigated = _mitigate(
            raw,
            effect.source.damage_type,
            state.resists,
            state.magic_amp,
        )
        packets[effect.source.damage_type] = (
            packets.get(effect.source.damage_type, 0.0) + mitigated
        )
    return packets


def _add_copied_stacking_on_hit_packets(
    state: FightState,
    rotation: RotationResult,
    on_hits: OnHitResult,
    spellblade: SpellbladeResult,
    copied_events: list[dict[str, Any]],
    proc_indices: Sequence[int],
    swing_times: Sequence[float],
    effectiveness: float,
) -> bool:
    """Replay stack-gated on-hit effects carried by a copied chain hit.

    Electrospark's full Wiki entry explicitly says that its secondary
    packets apply on-hit effects.  A secondary chain packet is an additional
    on-hit application on the same ordered target ledger; it therefore must
    advance Kraken/Hullbreaker's counters, but must not advance canonical
    on-attack effects such as Energized or Phantom Hit.  The normal attack,
    ability, phantom, and Spellblade applications are walked first in their
    existing order, then the copied packet is inserted after the triggering
    swing.  Only the damage attributable to the copied packet is appended to
    ``copied_events``.

    Returns ``True`` when every copied stack packet was timestamped and
    replayed.  A malformed or coarse schedule leaves the caller's existing
    fail-closed coverage intact.
    """
    if (
        not copied_events
        or not proc_indices
        or not state.damage_effects.stacking_on_hits
    ):
        return True
    if len(swing_times) != state.num_auto_attacks:
        return False

    copied_by_auto: dict[int, list[dict[str, Any]]] = {}
    for event, index in zip(copied_events, proc_indices):
        copied_by_auto.setdefault(int(index), []).append(event)
    apps = rotation.ability_item_applications

    for effect in state.damage_effects.stacking_on_hits:
        if item_effects.counter_trigger(effect.source.item_name) == "on_attack":
            # Statikk's chain carries on-hit effects, not on-attack effects.
            continue

        stacks = 0
        # Ability-carried on-hit applications lead the shared counter.  A
        # phantom hit on an ability application contributes one additional
        # on-hit stack at that same authored position.
        on_hit_sequence_index = 0
        for app in apps:
            if not app.on_hit:
                continue
            stacks += 1
            if stacks >= effect.hits_required:
                stacks = 0
            if on_hit_sequence_index in on_hits.phantom_ability_stack_positions:
                stacks += 1
                if stacks >= effect.hits_required:
                    stacks = 0
            on_hit_sequence_index += 1

        for index, swing_time in enumerate(swing_times):
            applications = 1
            if index in on_hits.phantom_hit_autos:
                applications += 1
            if index < spellblade.double_on_hit_procs:
                applications += 1
            for _application in range(applications):
                stacks += 1
                if stacks >= effect.hits_required:
                    stacks = 0

            copied_at_swing = copied_by_auto.get(index, [])
            if not copied_at_swing:
                continue
            for event in copied_at_swing:
                stacks += 1
                if stacks < effect.hits_required:
                    continue
                stacks = 0
                prior_copied_damage = sum(
                    sum(
                        float(amount)
                        for amount in candidate.get("packets", {}).values()
                        if isinstance(amount, (int, float))
                    )
                    for candidate in copied_events
                    if candidate is not event
                    and float(candidate.get("time", 0.0)) <= swing_time + 1e-9
                )
                target_current_health = max(
                    0.0,
                    _target_health_before_timestamp(state, swing_time)
                    - prior_copied_damage,
                )
                raw = (
                    effect.source.raw_damage(
                        _damage_inputs(
                            state, target_current_health=target_current_health
                        )
                    )
                    * effectiveness
                )
                mitigated = _mitigate(
                    raw,
                    effect.source.damage_type,
                    state.resists,
                    state.magic_amp,
                )
                if effect.source.basic_damage and effect.source.damage_type != "true":
                    mitigated *= state.target_basic_damage_multiplier
                packets = event.setdefault("packets", {})
                packets[effect.source.damage_type] = (
                    packets.get(effect.source.damage_type, 0.0) + mitigated
                )
                event.setdefault("stacked_copied_sources", []).append(
                    effect.source.item_name
                )
    return True


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

    Stack counters count ON-HIT applications, so they run on one shared
    hit sequence: the rotation's ability-carried applications (Bel'Veth
    Q/E) lead, then the autos continue the same counter. A proc fires at
    the effectiveness of the hit that landed the Nth stack.

    Replaced autos (Azir soldiers) consume energized effects and build
    stack-counter procs normally, but every auto-triggered proc's damage
    is scaled by the override's on-hit effectiveness (game-verified:
    Statikk Shiv and Kraken Slayer proc at 50% damage).
    """
    resists = state.resists
    breakdown = state.breakdown
    num_auto_attacks = state.num_auto_attacks
    effectiveness = _on_hit_effectiveness(state)

    # Galvanize is an ability-capable Energized trigger.  It is authored once
    # before the auto pass so zero-auto rotations (for example a spell-only
    # one-rotation scenario) still consume and price the ready charge.
    ability_consumed_items = {
        effect.source.item_name
        for effect in state.damage_effects.first_autos
        if _author_energized_ability_proc(state, rotation, effect, effectiveness)
    }

    # The auto stream's authored per-swing schedule.  Swing-riding procs
    # stamp their events at these times; an empty list (no stream, or a
    # count mismatch) keeps those rows coarse.
    swing_times = _auto_attack_timestamps(state)
    if len(swing_times) != num_auto_attacks:
        swing_times = []

    if num_auto_attacks > 0:
        inputs = _damage_inputs(state)
        if item_effects.has_item(state.items, "Runaan's Hurricane"):
            secondary_target_count = item_effects.runaan_secondary_target_count(
                roster_target_count=state.roster_target_count
            )
            if 1 <= state.roster_target_index <= secondary_target_count:
                raw_bolt = (
                    item_effects.runaan_secondary_target_damage(
                        total_attack_damage=state.champion_stats["attack_damage"]
                    )
                    * effectiveness
                )
                if raw_bolt > 0.0:
                    crit_raw = raw_bolt * state.crit_multiplier
                    if state.deterministic:
                        bolt_damage = state.crit_chance * _mitigate_basic_attack_swing(
                            state, crit_raw, critical_strike=True
                        ) + (1.0 - state.crit_chance) * _mitigate_basic_attack_swing(
                            state, raw_bolt
                        )
                    else:
                        bolt_damage = _mitigate_basic_attack_swing(state, raw_bolt)
                    bolt_total = bolt_damage * num_auto_attacks
                    bolt_key = "secondary_Runaan's Hurricane"
                    bolt_row: dict[str, Any] = {
                        "name": "Runaan's Hurricane (Wind's Fury bolt)",
                        "count": num_auto_attacks,
                        "damage_per_hit": bolt_damage,
                        "unit": "bolts",
                        "total_damage": bolt_total,
                        "damage_type": "physical",
                        "targeting": {
                            "kind": "runaan_bolt",
                            "secondary_target_count": secondary_target_count,
                            "allocated_target_index": state.roster_target_index,
                            "roster_target_count": state.roster_target_count,
                            "copied_on_hit_scope": "fixed_source_packets",
                        },
                    }
                    if swing_times and len(swing_times) == num_auto_attacks:
                        bolt_row["event_phase"] = "auto"
                        bolt_row["damage_events"] = [
                            {
                                "time": swing_times[index],
                                "damage": bolt_damage,
                                "damage_type": "physical",
                            }
                            for index in range(num_auto_attacks)
                        ]
                    breakdown[bolt_key] = bolt_row
                    state.total_damage += bolt_total

                    copied_events: list[dict[str, Any]] = []
                    for index in range(num_auto_attacks):
                        event_time = (
                            swing_times[index] if index < len(swing_times) else 0.0
                        )
                        copied_events.append(
                            {
                                "time": event_time,
                                "packets": _copied_on_hit_packet(
                                    state,
                                    on_hits,
                                    effectiveness,
                                    _target_health_before_timestamp(state, event_time),
                                ),
                            }
                        )
                    copied_by_type: dict[str, float] = {}
                    for copied_event in copied_events:
                        for damage_type, amount in copied_event["packets"].items():
                            copied_by_type[damage_type] = (
                                copied_by_type.get(damage_type, 0.0) + amount
                            )
                    copied_total = sum(copied_by_type.values())
                    if copied_total > 0.0:
                        copied_key = "on_hit_secondary_Runaan's Hurricane"
                        copied_row: dict[str, Any] = {
                            "name": "Runaan's Hurricane copied on-hit (secondary)",
                            "count": num_auto_attacks,
                            "damage_per_hit": copied_total / num_auto_attacks,
                            "unit": "bolts",
                            "total_damage": copied_total,
                            **_damage_type_fields(copied_by_type),
                            "targeting": {
                                "kind": "runaan_bolt_copied_on_hit",
                                "secondary_target_count": secondary_target_count,
                                "allocated_target_index": state.roster_target_index,
                                "roster_target_count": state.roster_target_count,
                                "copied_on_hit_scope": "per_hit_source_packets",
                            },
                        }
                        if swing_times and len(swing_times) == num_auto_attacks:
                            copied_row["event_phase"] = "auto"
                            copied_row["damage_events"] = [
                                {
                                    "time": copied_event["time"],
                                    "damage": amount,
                                    "damage_type": damage_type,
                                }
                                for copied_event in copied_events
                                for damage_type, amount in copied_event[
                                    "packets"
                                ].items()
                            ]
                        breakdown[copied_key] = copied_row
                        state.total_damage += copied_total

        cleave_item_name = item_effects.cleave_on_hit_item_name(state.items)
        secondary_target_count = max(0, state.roster_target_count - 1)
        if (
            cleave_item_name is not None
            and secondary_target_count > 0
            and 1 <= state.roster_target_index <= secondary_target_count
        ):
            cleave_damages = [
                _mitigate(
                    item_effects.hydra_cleave_secondary_ad_damage(
                        total_attack_damage=state.champion_stats.get(
                            "attack_damage", 0.0
                        ),
                        is_melee=state.is_melee,
                        item_name=cleave_item_name,
                    )
                    * effectiveness,
                    "physical",
                    resists,
                    state.magic_amp,
                )
                for _ in range(num_auto_attacks)
            ]
            cleave_total = sum(cleave_damages)
            if cleave_total > 0.0:
                cleave_key = f"on_hit_secondary_{cleave_item_name}"
                cleave_row: dict[str, Any] = {
                    "name": f"{cleave_item_name} Cleave (secondary)",
                    "count": num_auto_attacks,
                    "damage_per_hit": cleave_total / num_auto_attacks,
                    "unit": "packets",
                    "total_damage": cleave_total,
                    "damage_type": "physical",
                    "targeting": {
                        "kind": "cleave_secondary",
                        "secondary_target_count": secondary_target_count,
                        "allocated_target_index": state.roster_target_index,
                        "roster_target_count": state.roster_target_count,
                    },
                }
                if swing_times and len(swing_times) == num_auto_attacks:
                    cleave_row["event_phase"] = "auto"
                    cleave_row["damage_events"] = [
                        {
                            "time": swing_times[index],
                            "damage": damage,
                            "damage_type": "physical",
                        }
                        for index, damage in enumerate(cleave_damages)
                    ]
                breakdown[cleave_key] = cleave_row
                state.total_damage += cleave_total

        for effect in state.damage_effects.first_autos:
            source = effect.source
            if not item_effects.first_auto_state_ready(
                state.items, state.item_options, source.item_name
            ):
                # Blackout's unseen gate is an explicit scenario input.  A
                # equipped Umbral Glaive never guesses that the target was
                # unseen; without the ready receipt, the proc is withheld.
                continue
            chain_target_count = 0
            if effect.chain_targets_max > 0:
                # Statikk's one energized proc is a single chain across the
                # selected roster.  The per-target fight is evaluated once
                # for each roster member, so allocate the packet to the
                # sourced level-scaled prefix instead of duplicating it on
                # every target.  Copied on-hit siblings remain a separate
                # coverage boundary until the roster ledger can replay them.
                chain_target_count = item_effects.statikk_chain_target_count(
                    state.level
                )
                allocated_targets = min(
                    max(1, state.roster_target_count), chain_target_count
                )
                if state.roster_target_index >= allocated_targets:
                    continue
            if effect.energized_max_stacks > 0:
                proc_indices = item_effects.energized_proc_indices(
                    source.item_name,
                    num_auto_attacks,
                    initial_stacks=(
                        0.0
                        if source.item_name in ability_consumed_items
                        else float(effect.energized_max_stacks)
                    ),
                )
                procs = len(proc_indices)
            else:
                proc_indices = tuple(range(min(effect.max_procs, num_auto_attacks)))
                procs = len(proc_indices)
            if procs <= 0:
                continue
            proc_times = [
                swing_times[index] for index in proc_indices if index < len(swing_times)
            ]
            proc_damages: list[float] = []
            for proc_time in proc_times:
                proc_inputs = _damage_inputs(
                    state,
                    target_current_health=_target_health_before_timestamp(
                        state, proc_time
                    ),
                )
                raw_proc = source.raw_damage(proc_inputs) * effectiveness
                mitigated_proc = _mitigate(
                    raw_proc, source.damage_type, resists, state.magic_amp
                )
                if source.basic_damage and source.damage_type != "true":
                    mitigated_proc *= state.target_basic_damage_multiplier
                proc_damages.append(mitigated_proc)
            if not proc_damages:
                raw_damage = source.raw_damage(inputs) * procs * effectiveness
                mitigated = _mitigate(
                    raw_damage, source.damage_type, resists, state.magic_amp
                )
                if source.basic_damage and source.damage_type != "true":
                    mitigated *= state.target_basic_damage_multiplier
                proc_damages = [mitigated / procs] * procs
            else:
                mitigated = sum(proc_damages)
            breakdown[source.breakdown_key] = {
                "name": source.display_name,
                "count": procs,
                "damage_per_hit": mitigated / procs,
                "unit": "procs",
                "total_damage": mitigated,
                "damage_type": source.damage_type,
            }
            if effect.energized_max_stacks > 0:
                breakdown[source.breakdown_key]["energized_schedule"] = (
                    item_effects.energized_schedule_receipt(source.item_name)
                )
            if chain_target_count:
                breakdown[source.breakdown_key]["targeting"] = {
                    "kind": "chain_lightning",
                    "chain_target_count": chain_target_count,
                    "allocated_target_index": state.roster_target_index,
                    "roster_target_count": state.roster_target_count,
                    "copied_on_hit_effects": True,
                }
            temporary_lethality = (
                effect.temporary_lethality_melee
                if state.is_melee
                else effect.temporary_lethality_ranged
            )
            if temporary_lethality > 0 and effect.temporary_lethality_duration > 0:
                breakdown[source.breakdown_key]["temporary_lethality"] = {
                    "amount": temporary_lethality,
                    "duration": effect.temporary_lethality_duration,
                    "applies_before_event": True,
                    "applied_to_triggering_event": True,
                    "applied_to_later_events": False,
                    "note": (
                        "Firmament's additional lethality is applied before its "
                        "own packet and the triggering attack, per the sourced Wiki."
                    ),
                }
            # First-hit procs ride the opening swings of the stream.
            if swing_times and all(
                proc_index < len(swing_times) for proc_index in proc_indices
            ):
                breakdown[source.breakdown_key]["event_phase"] = "auto"
                breakdown[source.breakdown_key]["damage_events"] = [
                    {
                        "time": swing_times[proc_index],
                        "damage": proc_damages[position],
                        "damage_type": source.damage_type,
                    }
                    for position, proc_index in enumerate(proc_indices)
                ]
            if chain_target_count and state.roster_target_index > 0:
                # Electrospark applies on-hit effects to secondary targets.
                # Every per-hit packet, including current-health formulas, is
                # replayed at the proc timestamp. Stack-counter effects are
                # replayed after the ordinary attack/ability applications on
                # the same target ledger, preserving their copied-hit order.
                copied_events = []
                for proc_index in proc_indices:
                    proc_time = (
                        swing_times[proc_index]
                        if proc_index < len(swing_times)
                        else 0.0
                    )
                    copied_events.append(
                        {
                            "time": proc_time,
                            "packets": _copied_on_hit_packet(
                                state,
                                on_hits,
                                effectiveness,
                                _target_health_before_timestamp(state, proc_time),
                            ),
                        }
                    )
                copied_stacking_certified = _add_copied_stacking_on_hit_packets(
                    state,
                    rotation,
                    on_hits,
                    spellblade,
                    copied_events,
                    proc_indices,
                    swing_times,
                    effectiveness,
                )
                copied_by_type: dict[str, float] = {}
                for copied_event in copied_events:
                    for damage_type, amount in copied_event["packets"].items():
                        copied_by_type[damage_type] = (
                            copied_by_type.get(damage_type, 0.0) + amount
                        )
                copied_total = sum(copied_by_type.values())
                if copied_total > 0.0:
                    copied_key = f"on_hit_chain_{source.item_name}"
                    copied_row: dict[str, Any] = {
                        "name": f"{source.display_name} copied on-hit (secondary)",
                        "count": procs,
                        "damage_per_hit": copied_total / procs,
                        "unit": "procs",
                        "total_damage": copied_total,
                        **_damage_type_fields(copied_by_type),
                        "targeting": {
                            "kind": "chain_lightning_copied_on_hit",
                            "source": source.item_name,
                            "allocated_target_index": state.roster_target_index,
                            "roster_target_count": state.roster_target_count,
                            "copied_on_hit_scope": "per_hit_source_packets",
                            "copied_stacking_on_hits": copied_stacking_certified,
                        },
                    }
                    if swing_times and all(
                        proc_index < len(swing_times) for proc_index in proc_indices
                    ):
                        copied_row["event_phase"] = "auto"
                        copied_row["damage_events"] = [
                            {
                                "time": copied_event["time"],
                                "damage": amount,
                                "damage_type": damage_type,
                            }
                            for copied_event in copied_events
                            for damage_type, amount in copied_event["packets"].items()
                        ]
                    breakdown[copied_key] = copied_row
                    state.total_damage += copied_total
            state.total_damage += mitigated

    if num_auto_attacks > 0:
        inputs = _damage_inputs(state)
        secondary_item_name = item_effects.hydra_secondary_item_name(state.items)
        secondary_active_indices: tuple[int, ...] = ()
        for effect in state.damage_effects.auto_cooldowns:
            source = effect.source
            # Prefer the authored swing schedule over a duration quotient:
            # a cooldown is consumed by an actual empowered attack, so an
            # exact fight boundary with no swing must not invent another
            # Titanic Crescent proc.
            proc_indices: list[int] = []
            if swing_times:
                ready = 0.0
                for index, swing_time in enumerate(swing_times):
                    if swing_time + 1e-9 >= ready:
                        proc_indices.append(index)
                        ready = swing_time + effect.cooldown
            if swing_times:
                procs = len(proc_indices)
            else:
                procs = (
                    1 + int(state.fight_duration_seconds / effect.cooldown)
                    if effect.cooldown > 0
                    else 1
                )
                procs = min(procs, num_auto_attacks)
                proc_indices = list(range(procs))
            if procs <= 0:
                continue
            raw_per_proc = source.raw_damage(inputs)
            base_effect = next(
                (
                    per_hit
                    for per_hit in state.damage_effects.per_hits
                    if per_hit.source.item_name == source.item_name
                ),
                None,
            )
            if base_effect is not None:
                # The ordinary 1% max-health packet is already in the
                # per-hit on-hit row.  Crescent is the replacement 4%
                # packet, so this row carries only its additional 3% delta.
                raw_per_proc -= base_effect.source.raw_damage(inputs)
                if source.item_name == secondary_item_name:
                    secondary_active_indices = tuple(proc_indices)
            raw_damage = raw_per_proc * procs * effectiveness
            mitigated = _mitigate(
                raw_damage, source.damage_type, resists, state.magic_amp
            )
            breakdown[source.breakdown_key] = {
                "name": source.display_name,
                "count": procs,
                "damage_per_hit": mitigated / procs,
                "unit": "procs",
                "total_damage": mitigated,
                "damage_type": source.damage_type,
            }
            # Each empowered swing is the first one at/after the effect's
            # cooldown gate.  Authored only when the swing schedule
            # reproduces the priced proc count exactly.
            proc_times = [
                swing_times[index] for index in proc_indices if index < len(swing_times)
            ]
            if len(proc_times) == procs:
                breakdown[source.breakdown_key]["event_phase"] = "auto"
                breakdown[source.breakdown_key]["damage_events"] = [
                    {
                        "time": proc_time,
                        "damage": mitigated / procs,
                        "damage_type": source.damage_type,
                    }
                    for proc_time in proc_times
                ]
            state.total_damage += mitigated

        # Titanic's Cleave cone strikes one packet on each selected
        # secondary roster target per authored auto.  The empowered swing
        # uses the parser-sourced 9% secondary ratio; ordinary swings use
        # the 3% ratio.  Primary target index 0 receives no cone packet.
        secondary_target_count = max(0, state.roster_target_count - 1)
        if (
            secondary_target_count > 0
            and state.roster_target_index > 0
            and state.roster_target_index <= secondary_target_count
            and secondary_item_name is not None
        ):
            cone_damages: list[float] = []
            active_indices = set(secondary_active_indices)
            for auto_index in range(num_auto_attacks):
                raw_cone = (
                    item_effects.hydra_secondary_target_damage(
                        max_health=state.champion_stats.get("health", 0.0),
                        is_melee=state.is_melee,
                        empowered=auto_index in active_indices,
                        item_name=secondary_item_name,
                    )
                    * effectiveness
                )
                cone_damages.append(
                    _mitigate(raw_cone, "physical", resists, state.magic_amp)
                )
            cone_total = sum(cone_damages)
            if cone_total > 0.0:
                cone_key = "secondary_Titanic Hydra"
                cone_row: dict[str, Any] = {
                    "name": "Titanic Hydra Cleave (secondary)",
                    "count": num_auto_attacks,
                    "damage_per_hit": cone_total / num_auto_attacks,
                    "unit": "packets",
                    "total_damage": cone_total,
                    "damage_type": "physical",
                    "targeting": {
                        "kind": "hydra_cleave",
                        "secondary_target_count": secondary_target_count,
                        "allocated_target_index": state.roster_target_index,
                        "roster_target_count": state.roster_target_count,
                    },
                }
                if swing_times and len(swing_times) == num_auto_attacks:
                    cone_row["event_phase"] = "auto"
                    cone_row["damage_events"] = [
                        {
                            "time": swing_times[index],
                            "damage": damage,
                            "damage_type": "physical",
                        }
                        for index, damage in enumerate(cone_damages)
                    ]
                breakdown[cone_key] = cone_row
                state.total_damage += cone_total

    apps = rotation.ability_item_applications
    if num_auto_attacks > 0 or apps:
        other_on_hit_per_hit = on_hits.static_on_hit_per_hit
        if on_hits.has_current_health_on_hit and on_hits.current_health_on_hit_avg > 0:
            other_on_hit_per_hit += on_hits.current_health_on_hit_avg

        # Auto-segment procs ride specific swings, whose times the auto
        # stream already authored (``swing_times`` above); ability-segment
        # procs have no timestamps yet, so any of those keeps the row coarse.
        for effect in state.damage_effects.stacking_on_hits:
            source = effect.source
            # The item taxonomy decides which ability applications
            # advance this counter (Kraken/Hullbreaker count ON-HIT
            # applications; an on-attack-gated counter would count only
            # attack-carrying applications like Bel'Veth E slashes).
            wants_on_attack = (
                item_effects.counter_trigger(source.item_name) == "on_attack"
            )
            counted_hits = [
                app
                for app in apps
                if (app.on_attack if wants_on_attack else app.on_hit)
            ]
            # Phantom hits fired by ability attacks re-apply on-hit —
            # one extra stack on on-hit-gated counters at that position.
            extra_stacks = (
                set() if wants_on_attack else on_hits.phantom_ability_stack_positions
            )
            ability_procs, proc_autos = _calculate_stacking_procs(
                num_auto_attacks,
                on_hits.phantom_hit_autos,
                spellblade.double_on_hit_procs,
                hits_required=effect.hits_required,
                leading_ability_hits=len(counted_hits),
                ability_extra_stacks=extra_stacks,
            )
            procs = len(ability_procs) + len(proc_autos)
            if procs <= 0:
                continue

            # Ability-segment procs: the hit that lands the Nth stack
            # fires the proc at ITS effectiveness (Bel'Veth Q 75%, E
            # 8-32%), reading the rotation's modeled target HP (with
            # earlier procs of this effect folded in).
            total_damage = 0.0
            proc_hp_dealt = 0.0
            for hit_index in ability_procs:
                app = counted_hits[hit_index]
                inputs = _damage_inputs(state, max(0.0, app.target_hp - proc_hp_dealt))
                raw = source.raw_damage(inputs) * app.effectiveness
                mitigated = _mitigate(raw, source.damage_type, resists, state.magic_amp)
                if source.basic_damage and source.damage_type != "true":
                    mitigated *= state.target_basic_damage_multiplier
                total_damage += mitigated
                proc_hp_dealt += mitigated

            # Auto-segment procs: unchanged auto-timeline behavior at
            # the auto stream's effectiveness.
            auto_proc_damages: list[float] = []
            if proc_autos:
                if effect.tracks_target_health:
                    auto_proc_damages = _simulate_stacking_on_hit_damage(
                        effect,
                        _damage_inputs(state),
                        state.target_health,
                        num_auto_attacks,
                        autos.auto_damage_per_hit,
                        other_on_hit_per_hit,
                        resists,
                        state.magic_amp,
                        proc_autos,
                        effectiveness=effectiveness,
                        target_basic_damage_multiplier=(
                            state.target_basic_damage_multiplier
                        ),
                    )
                    total_damage += sum(auto_proc_damages)
                else:
                    raw = (
                        source.raw_damage(_damage_inputs(state))
                        * len(proc_autos)
                        * effectiveness
                    )
                    auto_segment_total = _mitigate(
                        raw, source.damage_type, resists, state.magic_amp
                    ) * (
                        state.target_basic_damage_multiplier
                        if source.basic_damage and source.damage_type != "true"
                        else 1.0
                    )
                    total_damage += auto_segment_total
                    auto_proc_damages = [auto_segment_total / len(proc_autos)] * len(
                        proc_autos
                    )

            breakdown[source.breakdown_key] = {
                "name": source.display_name,
                "count": procs,
                "damage_per_hit": total_damage / procs,
                "unit": "procs",
                "total_damage": total_damage,
                "damage_type": source.damage_type,
            }
            # Every proc fired on a timestamped swing: author its events.
            # Ability-segment procs carry no authored timestamps yet, so
            # a row containing any stays coarse deliberately.
            if not ability_procs and auto_proc_damages and swing_times:
                breakdown[source.breakdown_key]["event_phase"] = "auto"
                breakdown[source.breakdown_key]["damage_events"] = [
                    {
                        "time": swing_times[auto_index],
                        "damage": damage,
                        "damage_type": source.damage_type,
                    }
                    for auto_index, damage in zip(sorted(proc_autos), auto_proc_damages)
                ]
            state.total_damage += total_damage

    for effect in state.damage_effects.cooldown_procs:
        if not effect.late_phase:
            continue
        source = effect.source
        stack_timing = _stacked_champion_proc_times(state, rotation, effect)
        if stack_timing is None:
            # A malformed ledger withholds event precision: no certifiable
            # attack boundary exists, so the coarse fallback below prices a
            # duration-scaled aggregate (preserved legacy behavior).  The
            # row is stamped with NAMED fail-closed reasons (P3 package
            # 3C): callers can distinguish a malformed ledger from a
            # passive that never fired, and the self-shield loss is
            # receipted, not silent.
            stack_events = None
            stack_gate = None
            stack_source_denials: list[dict[str, Any]] = []
            stack_withheld = "malformed_proc_receipt"
        else:
            stack_events, stack_gate, stack_source_denials = stack_timing
            stack_withheld = (
                "eclipse_stack_source_unavailable" if stack_source_denials else None
            )
        if stack_events is not None and not stack_events and not stack_source_denials:
            # No completed stack pair means the passive never fired.  Do not
            # substitute a guaranteed aggregate proc for a condition the
            # authored cast/attack ledger proves did not occur.
            continue
        if stack_events:
            procs = len(stack_events)
        elif stack_source_denials:
            # The source class is valid, but one required identity or timing
            # input is unavailable.  Keep a named zero-damage row.  A denied
            # candidate cannot become a duration-scaled aggregate proc.
            procs = 0
        else:
            # Preserve a coarse price only when the ledger is malformed or
            # explicitly lacks a certifiable attack boundary.
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
            "count": procs,
        }
        if stack_withheld is not None:
            breakdown[source.breakdown_key]["event_phase"] = "coarse"
            breakdown[source.breakdown_key]["withheld_reason"] = stack_withheld
            if stack_events is None:
                breakdown[source.breakdown_key][
                    "shield_withheld_reason"
                ] = "self_shield_attached_only_to_certified_proc_events"
        if stack_source_denials:
            breakdown[source.breakdown_key][
                "stack_source_denials"
            ] = stack_source_denials
            if stack_gate is not None:
                breakdown[source.breakdown_key][
                    "state_transitions"
                ] = stack_gate.public_receipt()
        if stack_events:
            self_shield_events: list[dict[str, Any]] = []
            for event in stack_events:
                event["damage"] = total_damage / procs
                if effect.self_shield_duration > 0.0:
                    shield_base = (
                        effect.self_shield_melee_base
                        if state.is_melee
                        else effect.self_shield_ranged_base
                    )
                    shield_ratio = (
                        effect.self_shield_melee_bonus_ad_ratio
                        if state.is_melee
                        else effect.self_shield_ranged_bonus_ad_ratio
                    )
                    self_shield_events.append(
                        {
                            "amount": max(
                                0.0,
                                shield_base
                                + shield_ratio
                                * float(
                                    state.champion_stats.get("bonus_attack_damage", 0.0)
                                ),
                            ),
                            "duration": effect.self_shield_duration,
                            "source": source.display_name,
                            # The shield arms on the SAME proc event it
                            # rides: its time and event precision are the
                            # completed pair's (P3 package 3C).
                            "time": float(event.get("time", 0.0)),
                            "event_precision": str(
                                event.get("event_precision", "exact")
                            ),
                        }
                    )
            breakdown[source.breakdown_key]["damage_events"] = stack_events
            if self_shield_events:
                breakdown[source.breakdown_key][
                    "self_shield_events"
                ] = self_shield_events
            breakdown[source.breakdown_key]["event_phase"] = (
                "coarse" if stack_source_denials else "effect"
            )
            # Public kernel receipt: every stack gain, window expiry, proc,
            # and per-target cooldown start in walk order (state_lifecycle).
            if stack_gate is not None:
                breakdown[source.breakdown_key][
                    "state_transitions"
                ] = stack_gate.public_receipt()
        state.total_damage += total_damage

    for source in state.damage_effects.per_ability_hits:
        if rotation.total_muramana_procs <= 0:
            # No damaging ability cast consumed Shock: the passive never
            # fired, and no row is authored (P3 package 3E; the
            # Shaped-Charge precedent — no aggregate substitute).
            continue
        raw = source.raw_damage(_damage_inputs(state))
        per_proc = _mitigate(raw, source.damage_type, resists, state.magic_amp)
        total_damage = per_proc * rotation.total_muramana_procs
        breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": total_damage,
            "damage_type": source.damage_type,
        }
        proc_events = _muramana_proc_events(
            state,
            rotation,
            lockout_seconds=source.same_target_cast_lockout_seconds,
        )
        if proc_events is None:
            # A malformed or count-mismatched cast ledger withholds the
            # event list: the aggregate price is preserved (the proc count
            # is the trusted cast receipt) but the row is stamped with a
            # NAMED reason (P3 package 3E), and the coverage classifier
            # keeps it coarse.
            breakdown[source.breakdown_key]["event_phase"] = "coarse"
            breakdown[source.breakdown_key][
                "withheld_reason"
            ] = "malformed_proc_receipt"
        else:
            total_damage = per_proc * len(proc_events)
            breakdown[source.breakdown_key]["total_damage"] = total_damage
            breakdown[source.breakdown_key]["lockout_receipt"] = {
                "interval_seconds": source.same_target_cast_lockout_seconds,
                "identity": "target_id|cast:cast_id",
                "candidate_count": rotation.total_muramana_procs,
                "accepted_count": len(proc_events),
                "suppressed_count": rotation.total_muramana_procs - len(proc_events),
            }
            for event in proc_events:
                event["damage"] = per_proc
                event["damage_type"] = source.damage_type
            if proc_events:
                breakdown[source.breakdown_key]["damage_events"] = proc_events
                breakdown[source.breakdown_key]["event_phase"] = "ability"
        state.total_damage += total_damage


def _add_on_hit_healing(
    state: FightState,
    autos: AutoAttackResult,
    on_hits: OnHitResult,
) -> None:
    """Emit exact item-heal receipts for authored basic-attack on-hits.

    Cull's Reap heal is attached to the auto stream, including sourced
    Rageblade phantom and double-shot applications.  Ability-carried on-hit
    copies, pets, and other un-timestamped carriers remain withheld rather
    than receiving an invented time.
    """
    effects = state.damage_effects.on_hit_heals
    if not effects or state.num_auto_attacks <= 0:
        return
    swing_times = _auto_attack_timestamps(state)
    if len(swing_times) != state.num_auto_attacks:
        return

    application_times: list[float] = []
    double_shot_extra = state.num_auto_attacks if autos.double_shot_info else 0
    for auto_index, swing_time in enumerate(swing_times):
        application_times.append(swing_time)
        if auto_index in on_hits.phantom_hit_autos:
            application_times.append(swing_time)
        if double_shot_extra:
            application_times.append(swing_time)

    for effect in effects:
        if not application_times:
            continue
        state.breakdown[f"heal_{effect.item_name}"] = {
            "name": f"{effect.item_name} (Reap)",
            "count": len(application_times),
            "amount_per_proc": effect.amount,
            "total_amount": effect.amount * len(application_times),
            "unit": "health",
            "heal_events": [
                {
                    "time": event_time,
                    "amount": effect.amount,
                    "trigger_source": "auto_attacks",
                }
                for event_time in application_times
            ],
            "event_phase": "heal",
        }


def _add_first_auto_healing(state: FightState) -> None:
    """Emit Sundered Sky's first-attack heal with a live missing-HP formula."""
    effect = state.damage_effects.first_auto_crit
    if effect is None or (
        effect.heal_base_ad_ratio <= 0.0 and effect.heal_missing_health_ratio <= 0.0
    ):
        return
    auto_row = state.breakdown.get("auto_attacks")
    damage_events = auto_row.get("damage_events") if auto_row else None
    if not isinstance(damage_events, list) or not damage_events:
        return
    try:
        event_time = float(damage_events[0]["time"])
    except (KeyError, TypeError, ValueError):
        return
    base_ad = float(state.champion_stats.get("base_attack_damage", 0.0))
    # Lightshield Strike heals 100% bAD (melee) / 50% bAD (ranged) — the
    # ranged variant is sourced from the wiki's {{rd|100%|50%}} (pass 17).
    heal_ratio = (
        effect.heal_base_ad_ratio_ranged
        if getattr(state, "is_melee", True) is False
        else effect.heal_base_ad_ratio
    )
    base_amount = heal_ratio * base_ad
    if base_amount <= 0.0:
        return

    def amount_formula(
        current_health: float,
        maximum_health: float,
        base_amount: float = base_amount,
        missing_ratio: float = effect.heal_missing_health_ratio,
    ) -> float:
        return base_amount + missing_ratio * max(0.0, maximum_health - current_health)

    state.breakdown[f"heal_{effect.item_name}"] = {
        "name": f"{effect.item_name} (Lightshield Strike)",
        "count": 1,
        "amount_per_proc": base_amount,
        "total_amount": base_amount,
        "unit": "health",
        "heal_events": [
            {
                "time": event_time,
                "amount": base_amount,
                "amount_formula": amount_formula,
                "trigger_source": "auto_attacks",
                "overheal_to_temporary_health": (
                    effect.temporary_health_duration > 0.0
                ),
                "temporary_health_duration": effect.temporary_health_duration,
            }
        ],
        "event_phase": "heal",
    }


def _add_shadowflame_cinderbloom(
    state: FightState, config: FightConfig, rotation: RotationResult
) -> None:
    """Resolve max-health-sensitive damage, then add Cinderbloom's bonus."""
    effect = state.damage_effects.magic_true_crit
    has_threshold_health = config.target_threshold_health_bonus > 0
    if effect is None and not has_threshold_health:
        return
    (
        shadowflame_bonus,
        bonus_by_type,
        bonus_events,
        adjustments,
    ) = _calculate_shadowflame_bonus(
        effect,
        state.breakdown,
        state.ability_damages,
        state.target_health,
        state.cast_order,
        cast_events=rotation.cast_events,
        target_magic_shield=config.target_magic_shield,
        target_physical_shield=config.target_physical_shield,
        target_general_shield=config.target_general_shield,
        target_threshold_shield_amount=config.target_threshold_shield_amount,
        target_threshold_shield_health_ratio=(
            config.target_threshold_shield_health_ratio
        ),
        target_threshold_shield_duration=config.target_threshold_shield_duration,
        target_threshold_shield_damage_type=(
            config.target_threshold_shield_damage_type
        ),
        target_threshold_health_bonus=config.target_threshold_health_bonus,
        target_threshold_health_heal=config.target_threshold_health_heal,
        target_threshold_health_ratio=config.target_threshold_health_ratio,
        target_threshold_health_duration=config.target_threshold_health_duration,
        return_events=True,
        return_adjustments=True,
    )
    liandry_delta = float(adjustments["liandry_delta"])
    if abs(liandry_delta) > 1e-9:
        liandry_row = state.breakdown.get(_LIANDRY_BURN_KEY)
        if liandry_row is None:  # pragma: no cover - registry invariant
            raise RuntimeError("Liandry adjustment has no breakdown row")
        liandry_row["total_damage"] = float(liandry_row["total_damage"]) + liandry_delta
        liandry_row["damage_events"] = adjustments["liandry_events"]
        state.total_damage += liandry_delta
    if shadowflame_bonus > 0:
        state.breakdown[f"shadowflame_{effect.item_name}"] = {
            "name": f"{effect.item_name} (Cinderbloom)",
            "total_damage": shadowflame_bonus,
            # Cinderbloom is computed from the ordered source ledger above.
            # Preserve each trigger timestamp in the shared damage ledger so
            # participant death can stop only later bonus packets.
            "damage_events": bonus_events,
            **_damage_type_fields(bonus_by_type),
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


def _amplifier_delta_events(
    amped_events: list,
    bonus: float,
) -> list[dict[str, Any]]:
    """Author an amplifier row's bonus onto the exact events it amplified.

    A fight-wide amplifier prices its bonus as one fraction of the running
    total, so its per-event delta is that same fraction of each amplified
    event — expressed as a pro-rata share so the authored events sum
    exactly to the row total. Each delta keeps its amplified event's time
    and timeline order; the ``amplifier`` phase rank then places it
    immediately after that event in the shared ledger.  Consumes the light
    ledger rows ``(sort_key, damage, damage_type, source_key)``.
    """
    amped_total = sum(row[1] for row in amped_events)
    if bonus <= 0 or amped_total <= 0:
        return []
    return [
        {
            "damage_type": row[2],
            "damage": bonus * row[1] / amped_total,
            "time": row[0][0],
            "timeline_order": row[0][1],
        }
        for row in amped_events
    ]


def _hypershot_delta_events(
    state: FightState,
    rotation: RotationResult,
    bonus: float,
) -> list[dict[str, Any]]:
    """Author Horizon Focus's amp onto every event after the trigger cast.

    The first ability cast triggers Hypershot and is not amped, so its
    ledger events are excluded from the attribution pool. If the trigger
    cast cannot be isolated to events matching the rotation's recorded
    trigger damage (e.g. a mixed-type opener whose non-triggering part is
    amped), no events are authored and the row stays explicitly coarse.
    """
    events = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        light=True,
    )
    trigger_key = next(
        (
            k
            for k in state.cast_order
            if k in state.breakdown
            and float(state.breakdown[k].get("total_damage", 0.0)) > 0.0
        ),
        None,
    )
    trigger_times = [row[0][0] for row in events if row[3] == trigger_key]
    if trigger_key is None or not trigger_times:
        return []
    trigger_time = min(trigger_times)

    trigger_rows = [
        (index, row)
        for index, row in enumerate(events)
        if row[3] == trigger_key and row[0][0] == trigger_time
    ]
    trigger_event_index = next(
        (
            index
            for index, row in trigger_rows
            if math.isclose(
                row[1], rotation.first_ability_damage, rel_tol=1e-6, abs_tol=1e-3
            )
        ),
        None,
    )
    if trigger_event_index is None:
        return []
    return _amplifier_delta_events(
        [row for index, row in enumerate(events) if index != trigger_event_index],
        bonus,
    )


def _apply_general_amplifiers(state: FightState, rotation: RotationResult) -> None:
    """Apply whole-total amps (Lord Dominik's, Riftmaker, Liandry-class).

    Each source gets one ``damage_amp_<source>`` row whose delta events
    ride the pre-amp ledger's timestamps.
    """
    amp_sources = [
        (
            effect.item_name,
            effect.amp_fraction(
                state.fight_duration_seconds,
                max(0, state.target_bonus_health),
                state.champion_stats,
            ),
        )
        for effect in state.damage_effects.damage_amplifiers
    ]
    amp = 1.0 + sum(source_amp for _, source_amp in amp_sources)
    if amp <= 1.0:
        return
    amp_bonus = state.total_damage * (amp - 1.0)
    amped_events = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        light=True,
    )
    # Create per-source breakdown entries
    for source_name, source_amp in amp_sources:
        if source_amp > 0:
            source_bonus = state.total_damage * source_amp
            row = {
                "name": f"Damage Amplification ({source_name})",
                "multiplier": 1.0 + source_amp,
                "total_damage": source_bonus,
            }
            delta_events = _amplifier_delta_events(amped_events, source_bonus)
            if delta_events:
                row["damage_events"] = delta_events
                row["event_phase"] = "amplifier"
            state.breakdown[f"damage_amp_{source_name}"] = row
    state.total_damage += amp_bonus


def _apply_damage_amplifiers(state: FightState, rotation: RotationResult) -> None:
    """Apply fight-wide damage amplifiers and their breakdown rows.

    General amps (Lord Dominik's Regards, Riftmaker-class) multiply the
    whole running total, one ``damage_amp_<source>`` row per source. The
    Actualizer ability amp was already applied per-ability/per-proc, so
    its row is informational only. Horizon Focus amplifies everything
    except the first ability cast (the trigger). Each amp row authors its
    delta back onto the events it amplified, at their times, so shield
    and threshold accounting sees the amp when the damage landed; a row
    whose amplified pool cannot be event-isolated stays coarse and rides
    the ledger's explicit untyped fail-soft instead.
    """
    breakdown = state.breakdown
    _apply_general_amplifiers(state, rotation)

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
        row = {
            "name": "Damage Amplification (Horizon Focus)",
            "multiplier": state.hypershot_amp,
            "total_damage": hypershot_bonus,
        }
        delta_events = _hypershot_delta_events(state, rotation, hypershot_bonus)
        if delta_events:
            row["damage_events"] = delta_events
            row["event_phase"] = "amplifier"
        breakdown["damage_amp_Horizon Focus"] = row
        state.total_damage += hypershot_bonus


def _apply_temporary_lethality_windows(state: FightState) -> None:
    """Apply authored temporary lethality to later physical event packets.

    Firmament (Voltaic Cyclosword) grants flat lethality *after* its
    energized packet.  The item proc and ordinary attacks are priced before
    the proc is added, so the window is resolved once the complete authored
    ledger exists.  We rescale only later, timestamped physical packets by
    the ratio of the new and old armor multipliers; this preserves crits,
    item amplifiers, and any other post-mitigation modifiers already present
    on the event.  Untimed/coarse rows remain unchanged rather than receiving
    guessed penetration.
    """
    old_armor = float(state.resists.effective_armor)
    old_multiplier = apply_resistance(1.0, old_armor)
    if not math.isfinite(old_multiplier) or old_multiplier <= 0.0:
        return

    windows: list[dict[str, Any]] = []
    for source_key, row in state.breakdown.items():
        if not isinstance(row, dict):
            continue
        temporary = row.get("temporary_lethality")
        events = row.get("damage_events")
        if not isinstance(temporary, Mapping) or not isinstance(events, list):
            continue
        amount = _finite_numeric_receipt(temporary.get("amount"))
        duration = _finite_numeric_receipt(temporary.get("duration"))
        if amount is None or amount <= 0.0 or duration is None or duration <= 0.0:
            continue
        trigger_times = [
            _finite_numeric_receipt(event.get("time"))
            for event in events
            if isinstance(event, Mapping)
        ]
        trigger_times = [time for time in trigger_times if time is not None]
        if not trigger_times:
            continue
        windows.append(
            {
                "source_key": str(source_key),
                "trigger_time": min(trigger_times),
                "end_time": min(trigger_times) + duration,
                "amount": amount,
                "applies_to_triggering_event": bool(
                    temporary.get("applied_to_triggering_event", False)
                    or temporary.get("applies_before_event", False)
                ),
                "applied_count": 0,
            }
        )

    if not windows:
        return

    for source_key, row in state.breakdown.items():
        if not isinstance(row, dict):
            continue
        events = row.get("damage_events")
        if not isinstance(events, list):
            continue
        row_delta = 0.0
        for event in events:
            if not isinstance(event, dict) or event.get("damage_type") != "physical":
                continue
            event_time = _finite_numeric_receipt(event.get("time"))
            damage = _finite_numeric_receipt(event.get("damage"))
            if event_time is None or damage is None or damage <= 0.0:
                continue
            extra_lethality = 0.0
            active_windows: list[dict[str, Any]] = []
            for window in windows:
                # Firmament is an ordered pre-packet effect: its extra
                # lethality applies to its own damage and to the triggering
                # attack/ability.  Later events use the ordinary strict
                # after-trigger boundary.  Ability events at the same
                # timestamp are excluded unless they are the named Galvanize
                # row; the sourced trigger is still the packet before them.
                same_time_trigger = (
                    window["applies_to_triggering_event"]
                    and abs(event_time - window["trigger_time"]) <= 1e-9
                    and (
                        str(source_key) == window["source_key"]
                        or str(row.get("event_phase", "")) != "ability"
                    )
                )
                later_event = (
                    event_time > window["trigger_time"]
                    and event_time <= window["end_time"] + 1e-9
                )
                if same_time_trigger or later_event:
                    extra_lethality += float(window["amount"])
                    active_windows.append(window)
            if extra_lethality <= 0.0:
                continue
            percent_pen = (
                state.resists.auto_armor_pen_percent
                if str(row.get("event_phase", "")) == "auto"
                else state.resists.ability_armor_pen_percent
            )
            new_armor = apply_armor_penetration(
                state.resists.reduced_armor,
                state.resists.flat_armor_pen + extra_lethality,
                percent_pen,
                state.resists.armor_pen_bonus_percent,
                state.resists.target_bonus_armor,
            )
            new_multiplier = apply_resistance(1.0, new_armor)
            if not math.isfinite(new_multiplier) or new_multiplier <= 0.0:
                continue
            new_damage = damage * (new_multiplier / old_multiplier)
            if not math.isfinite(new_damage):
                continue
            delta = new_damage - damage
            event["damage"] = new_damage
            row_delta += delta
            for window in active_windows:
                window["applied_count"] += 1
        if row_delta:
            row["total_damage"] = float(row.get("total_damage", 0.0)) + row_delta
            if "damage_per_hit" in row and row.get("count"):
                row["damage_per_hit"] = float(row["total_damage"]) / float(row["count"])
            state.total_damage += row_delta

    for window in windows:
        row = state.breakdown.get(window["source_key"])
        if not isinstance(row, dict):
            continue
        temporary = row.get("temporary_lethality")
        if not isinstance(temporary, dict):
            continue
        applied = int(window["applied_count"])
        temporary["applied_to_triggering_event"] = bool(
            temporary.get("applied_to_triggering_event", False) and applied > 0
        )
        temporary["applied_to_later_events"] = applied > 0
        temporary["applied_event_count"] = applied
        temporary["note"] = (
            "Applied before the triggering Firmament packet and to later "
            "timestamped physical events within the sourced window."
            if applied > 0
            else "No timestamped physical events fell within the window."
        )


def _add_stored_damage(state: FightState, rotation: RotationResult) -> None:
    """Resolve champion-owned stored damage from the post-mitigation ledger.

    A stored-damage entry declares its ratio, window, source slots, and
    whether the ambient auto stream contributes. The source ledger is built
    before the stored proc is added, so the proc cannot store itself.
    """
    source_events = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
    )
    cast_positions = {slot: index for index, slot in enumerate(state.cast_order)}
    cast_times_by_slot: dict[str, list[float]] = {}
    for cast_event in rotation.cast_events:
        slot = str(cast_event.get("slot", ""))
        cast_times_by_slot.setdefault(slot, []).append(
            float(cast_event.get("time", 0.0))
        )

    for slot, ability_info in state.ability_damages.items():
        storage = ability_info.get("stored_damage")
        if not isinstance(storage, Mapping):
            continue
        row = state.breakdown.get(slot)
        if not isinstance(row, dict):
            continue
        cast_times = cast_times_by_slot.get(slot, [])
        if not cast_times:
            continue

        ratio = float(storage.get("ratio", 0.0) or 0.0)
        duration = float(storage.get("duration", 0.0) or 0.0)
        source_slots = {
            str(source_slot) for source_slot in storage.get("source_slots", ())
        }
        include_auto_attacks = bool(storage.get("include_auto_attacks", False))
        if ratio <= 0.0 or duration <= 0.0 or not source_slots:
            continue

        stored_events: list[dict[str, Any]] = []
        for start_time in cast_times[: max(0, int(row.get("casts", 0)))]:
            end_time = start_time + duration
            source_damage = 0.0
            for event in source_events:
                if not isinstance(event, Mapping):
                    continue
                damage_type = str(event.get("damage_type", ""))
                if damage_type not in {"physical", "magic"}:
                    continue
                source_key = str(event.get("source_key", ""))
                is_auto = source_key == "auto_attacks"
                if source_key not in source_slots and not (
                    is_auto and include_auto_attacks
                ):
                    continue
                event_time = float(event.get("time", 0.0) or 0.0)
                if event_time < start_time - _CAST_SCHEDULE_EPS:
                    continue
                if event_time > end_time + _CAST_SCHEDULE_EPS:
                    continue
                if (
                    abs(event_time - start_time) <= _CAST_SCHEDULE_EPS
                    and not is_auto
                    and source_key in cast_positions
                    and cast_positions[source_key] <= cast_positions.get(slot, -1)
                ):
                    continue
                source_damage += float(event.get("damage", 0.0) or 0.0)

            stored = source_damage * ratio
            if stored > 0.0:
                stored_events.append(
                    {
                        "time": end_time,
                        "damage_type": "true",
                        "damage": stored,
                        "event_precision": "exact",
                    }
                )

        total_stored = sum(float(event["damage"]) for event in stored_events)
        row["total_damage"] = total_stored
        row["total_raw"] = total_stored
        row["damage_type"] = "true"
        row["damage_by_type"] = {"true": total_stored} if total_stored > 0.0 else {}
        row["damage_events"] = stored_events
        row["event_phase"] = "ability"
        if total_stored > 0.0:
            row["detail"] = (
                f"{ratio * 100:g}% of post-mitigation physical and magic "
                f"champion damage stored in {len(stored_events)} Spirit Form "
                f"window{'s' if len(stored_events) != 1 else ''}"
            )
            state.total_damage += total_stored


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
    """Collect the notes documenting conditional item and timeline assumptions."""
    notes = state.notes
    notes.extend(state.damage_effects.conditional_notes)

    if state.target_class != item_effects.DEFAULT_TARGET_CLASS:
        armed = _armed_class_restricted_per_hits(state)
        armed_names = ", ".join(sorted(effect.source.item_name for effect in armed))
        notes.append(
            f"Target class '{state.target_class}': the sourced class-restricted "
            f"item branches are armed ({armed_names or 'none in this build'}). "
            "Named boundary — champion ABILITY class clauses (Nasus Q stacks, "
            "Cho'Gath Feast, Ezreal R's minion row) are not adjudicated, and "
            "ability-carried on-hit applications do not carry the class-"
            "restricted branch; the target's stats stay caller-supplied, not "
            "a sourced minion stat block."
        )

    timeline = state.stack_timeline
    if timeline is not None and timeline.buff_windows:
        uptime = sum(end - start for start, end in timeline.buff_windows)
        notes.append(
            f"{timeline.buff_name}: {len(timeline.buff_windows)} window(s) "
            f"from the stack timeline — +{timeline.buff_bonus_ad:.0f} bonus AD, "
            f"first at {timeline.buff_windows[0][0]:.2f}s, {uptime:.2f}s "
            f"committed (a window runs its full duration past the fight's "
            f"end, like the DoT it rides)."
        )

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


def _reattribute_empowered_swings(state: FightState) -> None:
    """Show an empowered auto's swing on the ability that forced it.

    An ``empowers_next_auto`` ability (Mundo E, Camille Q, Darius W,
    Cho'Gath E) consumes a basic attack, so in-game the player sees ONE
    hit worth ``attack + bonus``. With no auto stream the ability row
    already carries that swing (``_compute_ability_rotation``); with a
    stream it was left in the auto row, so the same ability read as
    bonus-only in timed fights and attack+bonus in one-rotation — two
    meanings for one row. Moving the consumed swings here reconciles the
    modes.

    Damage only moves BETWEEN rows: the fight total is untouched, and so
    is every on-hit row, which the empowered attack genuinely still
    triggers. The swing is priced at the auto row's blended per-hit
    average, so the remaining autos keep their per-hit damage and the
    crit split is rescaled to stay consistent with the new count.
    """
    auto_row = state.breakdown.get("auto_attacks")
    if not auto_row:
        return
    original_count = auto_row.get("count", 0)
    per_hit = auto_row.get("damage_per_hit", 0.0)
    if original_count <= 0 or per_hit <= 0:
        return

    remaining = original_count
    for ability_key in state.cast_order:
        info = state.ability_damages.get(ability_key)
        row = state.breakdown.get(ability_key)
        if info is None or row is None:
            continue
        empower = info.get("empowers_next_auto")
        if not empower:
            continue
        swings = min(row.get("casts", 0) * _empower_hits(empower), remaining)
        if swings <= 0:
            continue

        row["total_damage"] += swings * per_hit
        auto_row["total_damage"] -= swings * per_hit
        remaining -= swings
        # ``detail`` always wins over the UI's derived "N casts" text, so
        # spell out that the row now includes the attack it consumed.
        casts = row.get("casts", 0)
        base = row.get("detail") or f"{casts} cast{'' if casts == 1 else 's'}"
        row["detail"] = f"{base}, incl. basic attack"

    if remaining == original_count:
        return

    auto_row["count"] = remaining
    # Empowered attacks are consumed from the front of the shared auto
    # stream (the same ordering used by the cast ledger).  Remove those
    # swings from the ordinary-auto receipt as well as its aggregate; leaving
    # them in the event list makes a certified row's events sum above its
    # displayed damage and downgrades otherwise exact champion timelines.
    auto_events = auto_row.get("damage_events")
    if isinstance(auto_events, list):
        auto_row["damage_events"] = auto_events[:remaining]
    if auto_row.get("num_crits") is not None:
        # Rescale the crit split so num_crits + num_non_crits == count.
        crits = round(auto_row["num_crits"] * remaining / original_count)
        auto_row["num_crits"] = crits
        auto_row["num_non_crits"] = remaining - crits


def _apply_shield_reaver_venom(
    config: FightConfig,
    items: list[dict[str, Any]],
    champion_stats: dict[str, float],
) -> tuple[FightConfig, list[str]]:
    """Cut the target's non-magic shields for the attacker's Shield Reaver.

    Serpent's Fang's venom reduces the target's active shields on first
    damage and any shields gained while the attacker keeps dealing damage —
    a sustained rotation keeps the venom applied throughout. Magic-damage
    shields (Hexdrinker, Maw of Malmortius, Kaenic Rookern, ability magic
    shields) are unaffected, and Protoplasm Harness's temporary health and
    healing are not shields.
    """
    is_melee = bool(champion_stats.get("is_melee", True))
    fraction = item_effects.shield_reduction_fraction(items, is_melee=is_melee)
    if fraction <= 0.0:
        return config, []

    keep = 1.0 - fraction
    threshold_is_cuttable = (
        config.target_threshold_shield_damage_type != "magic"
        and config.target_threshold_shield_amount > 0
    )
    if (
        config.target_physical_shield <= 0
        and config.target_general_shield <= 0
        and not threshold_is_cuttable
    ):
        return config, []

    reduced = replace(
        config,
        target_physical_shield=config.target_physical_shield * keep,
        target_general_shield=config.target_general_shield * keep,
        target_threshold_shield_amount=(
            config.target_threshold_shield_amount * keep
            if threshold_is_cuttable
            else config.target_threshold_shield_amount
        ),
    )
    venom_seconds = float(
        item_effects.required_effect_value("Serpent's Fang", "venom_duration")
    )
    note = (
        f"Serpent's Fang: Shield Reaver cuts the target's non-magic shields "
        f"by {fraction:.0%} ({'melee' if is_melee else 'ranged'}) — the "
        f"rotation keeps its {venom_seconds:g}-second venom applied; "
        "magic-damage shields are unaffected."
    )
    return reduced, [note]


def _require_target_class_support(
    config: FightConfig, items: list[dict[str, Any]]
) -> None:
    """Refuse a non-champion-class fight the item model cannot price.

    ``FightConfig.__post_init__`` already rejected an unknown class. This
    is the second, build-scoped gate: an item whose cached effect text
    names a target class it is not adjudicated for would be priced with
    the champion-class reading (Statikk Shiv's Electrospark is 60 magic
    damage on a champion and a sourced 90 on a non-champion), so the
    fight fails closed with every offending item and clause named rather
    than silently under- or over-counting.
    """
    denials = item_effects.target_class_denials(items, config.target_class)
    if denials:
        raise ValueError(
            f"target_class={config.target_class!r} is not supported by this "
            "build: " + "; ".join(denials)
        )


def calculate_fight_damage(
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    items: list[dict[str, Any]],
    config: FightConfig,
    score_only: bool = False,
    tuple_ledger: bool = False,
    item_options: Mapping[str, Mapping[str, int | float]] | None = None,
    champion_options: Mapping[str, Any] | None = None,
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
    # ── Target class admission (P3-3M) ──────────────────────────────────
    _require_target_class_support(config, items)

    # ── Shield Reaver venom cuts the target's non-magic shields ─────────
    config, shield_reaver_notes = _apply_shield_reaver_venom(
        config, items, champion_stats
    )

    # ── Resolve resistances, penetration, amps, and attack timing ───────
    state = _resolve_combat_state(
        champion_stats,
        ability_damages,
        items,
        config,
        item_options=item_options,
        champion_options=champion_options,
    )
    state.score_only = score_only
    state.notes.extend(shield_reaver_notes)

    # ── Stat buffs from abilities (e.g. Aatrox R bonus AD) ─────────────
    _apply_stat_buff_ultimates(state)

    # ── Ability rotation, precomputed procs, DoTs, and Shaped Charge ────
    rotation = _compute_ability_rotation(state)
    _add_rengar_ferocity(state, rotation)
    _author_ability_dot_events(state, rotation)
    _add_precomputed_proc_damage(state, rotation)
    _add_stacking_dot_damage(state)
    _add_shaped_charge_damage(state, rotation)

    # ── Auto attacks (per-auto crit simulation) ─────────────────────────
    _prepare_spellblade_attack_schedule(state, rotation)
    autos = _simulate_auto_attacks(state)

    # ── On-hit damage layered onto the autos ────────────────────────────
    on_hits = _layer_on_hit_effects(state, autos, rotation)

    # ── Spellblade + Dusk and Dawn double on-hit ────────────────────────
    spellblade = _add_spellblade_damage(state, rotation, autos, on_hits)

    # ── Burn / DoT item damage ──────────────────────────────────────────
    _add_burn_damage(state, rotation)

    # ── Item procs (including ult-triggered Malignance) ─────────────────
    _add_item_proc_damage(state, rotation)

    # ── Keystone rune proc (Electrocute-class stack triggers) ───────────
    _add_keystone_damage(state, rotation)

    # ── Keystone threshold proc (Dark Harvest-class) ────────────────────
    _add_keystone_dark_harvest(state, rotation)

    # ── Keystone ability-cast proc (Arcane Comet-class) ─────────────────
    _add_keystone_ability_proc_damage(state, rotation)

    # ── Active item damage ──────────────────────────────────────────────
    _add_item_active_damage(state, rotation)

    # ── Single-proc on-hits, Shadowflame, and Expose Weakness ───────────
    _add_single_proc_on_hits(state, rotation, autos, on_hits, spellblade)
    _add_on_hit_healing(state, autos, on_hits)
    _add_first_auto_healing(state)
    _add_shadowflame_cinderbloom(state, config, rotation)
    _add_expose_weakness(state, autos, spellblade)

    # ── Deathfire's typed refreshed burn ────────────────────────────────
    _add_keystone_deathfire(state, rotation)

    # ── Conqueror's certified stack state and max-stack healing ────────
    _add_keystone_conqueror(state, rotation)

    # ── Summon Aery damage and signal cadence ───────────────────────────
    _add_keystone_aery_damage(state, rotation)

    # ── Aftershock delayed shockwave from immobilizing casts ────────────
    _add_keystone_aftershock_damage(state, rotation)

    # ── Grasp's timed combat stacks and empowered basic attack ──────────
    _add_keystone_grasp_damage(state, rotation)

    # ── Hail of Blades' temporary attack window and true-damage rider ───
    _add_keystone_hail_of_blades(state, rotation)

    # ── Lethal Tempo's stacked attack window and max-stack bolt ────────
    _add_keystone_lethal_tempo(state, rotation)

    # ── Fleet Footwork's charged heal and movement window ──────────────
    _add_keystone_fleet_footwork(state, rotation)

    # ── Keystone opening-window bonus (First Strike-class) ──────────────
    _add_keystone_window_amp_damage(state, rotation)

    # ── Keystone stacked proc plus lasting amp (Press the Attack-class) ─
    _add_keystone_proc_amp_damage(state, rotation)

    # ── Fight-wide damage amplifiers ────────────────────────────────────
    _apply_damage_amplifiers(state, rotation)

    # ── Empowered-auto swings shown on the ability that forced them ─────
    _reattribute_empowered_swings(state)

    # ── Temporary penetration windows (Voltaic Firmament) ──────────────
    # Resolve after every source and amplifier has authored its events, but
    # before reconstructing the shared ledger consumed by shields/healing.
    _apply_temporary_lethality_windows(state)
    _add_stored_damage(state, rotation)

    # ── Execute threshold display (The Collector) ───────────────────────
    _add_execute_display(state)

    # ── Notes for conditional item assumptions ──────────────────────────
    _collect_fight_notes(state, rotation, on_hits)

    # The exact event ledger the shield/temporary-health resolver consumes is
    # also the fight's returned ``damage_events``: nothing mutates the
    # breakdown after this point, so reconstruct it once.  Downstream team
    # simulation uses this same ordered ledger; it must never reconstruct
    # timing from aggregate breakdown rows.
    # ``tuple_ledger`` callers (the scoring fast path, for champions with
    # no self-heal rules and no Protoplasm target) consume the ledger as
    # light rows directly; every other caller gets the dict contract.
    damage_events = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        light=tuple_ledger,
        lean=score_only,
    )
    # ── Generic life-steal packets from exact physical attack events ─────
    # Run after the shared ledger is reconstructed so forced/basic attacks
    # carried by ability rows retain their explicit basic_attack marker.
    if not tuple_ledger:
        _add_lifesteal_events(state, damage_events)
        _add_omnivamp_events(state, damage_events)
    # Execute thresholds are terminal target-state transitions. Ability
    # thresholds apply only to their own cast. Item thresholds apply to every
    # authored packet. When both apply, keep the larger threshold.
    if not tuple_ledger:
        item_execute = state.damage_effects.execute
        for event in damage_events:
            if not isinstance(event, dict):
                continue
            source_key = str(event.get("source_key", ""))
            ability = state.ability_damages.get(source_key, {})
            # P4: the on-hit passive row's events carry source_key
            # "on_hit_ability_passive" — resolve the passive entry's own
            # execute stamp (Zeri's Living Battery).
            if not ability and source_key == "on_hit_ability_passive":
                ability = state.ability_damages.get("passive", {})
            ability_ratio = float(ability.get("execute_threshold_ratio", 0.0) or 0.0)
            item_ratio = (
                float(item_execute.threshold) if item_execute is not None else 0.0
            )
            if ability_ratio >= item_ratio and ability_ratio > 0:
                event["execute_threshold_ratio"] = ability_ratio
                event["execute_source"] = str(
                    ability.get("execute_source") or ability.get("name") or source_key
                )
            elif item_ratio > 0:
                event["execute_threshold_ratio"] = item_ratio
                event["execute_source"] = item_execute.item_name
    if (
        score_only
        and config.target_threshold_health_heal <= 0
        and not has_takedown_scan_support_items(items)
    ):
        # Score-mode consumers replay shields inside the coupled survival
        # walk and never read the one-pair shield outcome.  The remaining
        # engine-side consumers are the Protoplasm coverage downgrade below
        # (requires a positive threshold heal) and the takedown-scanning
        # support items, whose ``takedown_events`` synthesis reads
        # ``target_ending_health`` (issue #169) — both keep the outcome.
        shield_outcome: dict[str, float] = {}
    else:
        shield_outcome = _resolve_starting_shield_outcome(state, config, damage_events)
    _add_senna_souls(state, rotation, shield_outcome, damage_events)
    _add_aurelion_sol_stardust(state, rotation)
    _add_bard_travelers_call(state, rotation)
    _add_heimerdinger_w_e(state, rotation)
    _add_ksante_path_maker(state, rotation)
    _add_ashe_focus(state, rotation)
    timeline_coverage = _event_timeline_coverage(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        num_auto_attacks=state.num_auto_attacks,
        lean=score_only,
    )
    fimbulwinter_complete, fimbulwinter_source = _fimbulwinter_event_coverage(
        items, damage_events, rotation.control_events
    )
    if not fimbulwinter_complete:
        timeline_coverage["complete"] = False
        timeline_coverage["certification"] = "partial_event_order"
        timeline_coverage["coarse_sources"] = sorted(
            set(timeline_coverage["coarse_sources"]) | {fimbulwinter_source}
        )
        timeline_coverage["note"] = (
            "Fimbulwinter's Everlasting needs an authored immobilize/slow marker; "
            "the ability packet did not certify its crowd-control state."
        )
    if (
        config.target_threshold_health_heal > 0
        and shield_outcome["threshold_health_triggered"]
    ):
        timeline_coverage["complete"] = False
        timeline_coverage["certification"] = "partial_event_order"
        timeline_coverage["coarse_sources"] = sorted(
            set(timeline_coverage["coarse_sources"]) | {"target_Protoplasm Harness"}
        )
        timeline_coverage["note"] = (
            "Protoplasm Harness's sourced total healing is spread over five "
            "seconds; its internal heal tick cadence is not source-certified."
        )
    return {
        "breakdown": state.breakdown,
        "total_damage": state.total_damage,
        "effective_mr": state.resists.effective_mr,
        "effective_armor": state.resists.effective_armor,
        "keystone": (
            state.keystone_effect.keystone_name
            if state.keystone_effect is not None
            else ""
        ),
        "notes": state.notes,
        "cast_timeline": rotation.cast_events,
        "resource_spent": rotation.resource_spent,
        "resource_remaining": rotation.resource_remaining,
        "resource_ledger": rotation.resource_ledger,
        "resource_restore_events": [
            {
                "time": round(float(time), 6),
                "amount": round(float(amount), 6),
                "source": "Catalyst of Aeons (Eternity)",
            }
            for time, amount in state.resource_restore_events
            if math.isfinite(float(time)) and math.isfinite(float(amount))
        ],
        "timeline_coverage": timeline_coverage,
        "damage_events": damage_events,
        "control_events": rotation.control_events,
        **shield_outcome,
        # Exposed for champion-specific ability calculators (Case 1: stack
        # acceleration). Champions like Vayne can check which autos grant
        # double stacks to calculate ability procs more accurately.
        "phantom_hit_autos": on_hits.phantom_hit_autos,
        "phantom_hit_count": on_hits.phantom_hit_count,
        "item_state_receipts": item_effects.item_state_receipts(
            items,
            item_options,
            fight_duration_seconds=config.fight_duration_seconds,
            is_melee=state.is_melee,
            bonus_health=float(champion_stats.get("bonus_health", 0.0) or 0.0),
            bonus_mana=float(champion_stats.get("bonus_mana", 0.0) or 0.0),
            max_mana=float(champion_stats.get("max_mana", 0.0) or 0.0),
            total_attack_damage=float(champion_stats.get("attack_damage", 0.0) or 0.0),
            total_move_speed=float(champion_stats.get("move_speed", 0.0) or 0.0),
            lethality=float(champion_stats.get("lethality", 0.0) or 0.0),
        ),
    }


def _resolve_starting_shield_outcome(
    state: FightState, config: FightConfig, damage_events: list[dict[str, Any]]
) -> dict[str, float]:
    """Split post-mitigation TDD into shield absorption and health damage.

    TDD remains damage dealt. Shields are reported as a separate defensive
    outcome so the UI does not hide how much of that damage reached health.
    """
    repriced = False
    pools = shield_ledger.build_pools(
        state.target_health,
        magic_shield=config.target_magic_shield,
        physical_shield=config.target_physical_shield,
        general_shield=config.target_general_shield,
        threshold_shield_amount=config.target_threshold_shield_amount,
        threshold_shield_health_ratio=config.target_threshold_shield_health_ratio,
        threshold_shield_duration=config.target_threshold_shield_duration,
        threshold_shield_damage_type=config.target_threshold_shield_damage_type,
        threshold_health_bonus=config.target_threshold_health_bonus,
        threshold_health_heal=config.target_threshold_health_heal,
        threshold_health_ratio=config.target_threshold_health_ratio,
        threshold_health_duration=config.target_threshold_health_duration,
    )
    heal_drip = _ThresholdHealDrip()
    threshold_health = pools.threshold_health
    if shield_ledger.is_inert(pools):
        # No shield can absorb and no threshold state can arm: every
        # per-event absorption below is exactly ``- 0.0``, so the walk
        # reduces bit-for-bit to sequential floored health subtraction.
        current_health = pools.health
        for event in damage_events:
            current_health = max(0.0, current_health - event["damage"])
            # P4: the single-fight walk mirrors the survival terminal
            # transition's execute gate (inclusive <=, after the event's
            # own damage) so /api/calculate agrees with the pair/timeline
            # surface (Zeri's Living Battery).
            ratio = float(event.get("execute_threshold_ratio", 0.0) or 0.0)
            if (
                ratio > 0.0
                and current_health > 0.0
                and current_health <= pools.max_health * ratio
            ):
                current_health = 0.0
        pools.health = current_health
    else:
        for event in damage_events:
            event_time = float(event["time"])
            heal_drip.advance_to(pools, event_time)
            remaining = float(event["damage"])
            raw_formula = event.get("raw_formula")
            raw_damage = float(event.get("raw_damage", 0.0) or 0.0)
            if callable(raw_formula) and raw_damage > 0.0:
                missing_ratio = max(
                    0.0,
                    min(
                        1.0,
                        1.0 - pools.health / max(pools.max_health, 1e-12),
                    ),
                )
                try:
                    live_raw = max(
                        0.0,
                        float(raw_formula(missing_ratio, pools.max_health)),
                    )
                except TypeError:
                    live_raw = max(0.0, float(raw_formula(missing_ratio)))
                live_damage = remaining * live_raw / raw_damage
                if abs(live_damage - remaining) > 1e-9:
                    repriced = True
                    remaining = live_damage
                    event["damage"] = live_damage
            outcome = shield_ledger.absorb(
                pools, remaining, event["damage_type"], event_time
            )
            if outcome.threshold_health_triggered:
                heal_drip.start(pools, event_time, outcome)

    if repriced:
        repriced_by_source: dict[str, list[float]] = {}
        for event in damage_events:
            repriced_by_source.setdefault(str(event.get("source_key", "")), []).append(
                float(event.get("damage", 0.0))
            )
        for source_key, entry in state.breakdown.items():
            values = repriced_by_source.get(source_key)
            if not values:
                continue
            entry["total_damage"] = sum(values)
            declared = entry.get("damage_events")
            if isinstance(declared, list):
                for index, nested in enumerate(declared):
                    if isinstance(nested, dict) and index < len(values):
                        nested["damage"] = values[index]
        state.total_damage = sum(
            float(entry.get("total_damage", 0.0))
            for entry in state.breakdown.values()
            if isinstance(entry, dict) and not entry.get("informational")
        )

    absorbed = pools.shield_absorbed
    return {
        "shield_absorbed": absorbed,
        "magic_shield_absorbed": pools.magic_absorbed,
        "physical_shield_absorbed": pools.physical_absorbed,
        "general_shield_absorbed": pools.general_absorbed,
        "threshold_shield_absorbed": pools.threshold_absorbed,
        "health_damage": max(0.0, state.total_damage - absorbed),
        "threshold_health_triggered": heal_drip.triggered,
        "threshold_health_bonus_gained": (
            threshold_health.bonus
            if threshold_health is not None and threshold_health.triggered
            else 0.0
        ),
        "target_healing_received": heal_drip.healing_received,
        "target_ending_health": pools.health,
        "target_effective_max_health": pools.max_health,
    }


def _is_auto_stream_key(key: str) -> bool:
    """Whether a breakdown key belongs to the auto-attack damage stream.

    The stream itself plus champion riders on it (e.g. Corki's
    true-damage instance) share the ``auto_attacks`` prefix; on-hit,
    spellblade, and Fiendhunter rows ride the swings too.
    """
    return (
        key.startswith("auto_attacks")
        or key == "fiendhunter_true_damage"
        or key.startswith(("on_hit_", "spellblade_"))
    )


def split_auto_vs_ability(
    breakdown: dict[str, dict[str, Any]],
) -> tuple[float, float]:
    """Split a fight breakdown into (auto_attack_damage, ability_damage).

    Attribution rules, keyed off the breakdown key names this module emits:

    - Entries marked ``informational`` are display-only — their damage is
      zero or already counted in other rows (the engine marks its amp
      summaries, the execute-threshold row, and the Sundered Sky row
      this way) — so they are skipped.
    - Rows that declare ``auto_attack_fraction`` know their own
      composition (First Strike's window bonus spans both streams) and
      are split by it.
    - ``_is_auto_stream_key`` rows count as auto-attack damage.
    - ``damage_amp_<source>`` rows amplify both buckets, so their damage
      is redistributed proportionally to the pre-amp auto/ability ratio
      (dropped entirely if that total is zero).
    - Everything else counts as ability damage.
    """
    auto_attack_damage = 0.0
    ability_damage = 0.0
    redistributed_damage = 0.0  # damage_amp_<source> rows

    for key, entry in breakdown.items():
        dmg = entry.get("total_damage", 0.0)
        if entry.get("informational"):
            continue
        if "auto_attack_fraction" in entry:
            fraction = float(entry["auto_attack_fraction"])
            auto_attack_damage += dmg * fraction
            ability_damage += dmg * (1.0 - fraction)
        elif _is_auto_stream_key(key):
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


def split_by_damage_type(
    breakdown: dict[str, dict[str, Any]],
) -> dict[str, float]:
    """Split a fight breakdown into physical/magic/true damage totals.

    Attribution rules, keyed off the row fields this module emits:

    - Entries marked ``informational`` are display-only — their damage
      is zero or already counted in other rows — so they are skipped.
    - Entries carrying ``damage_by_type`` (mixed rows built from typed
      parts) contribute their exact per-type composition.
    - Entries with a singular ``damage_type`` contribute their full
      damage to that bucket.
    - Everything else — ``damage_amp_<source>`` rows and mixed rows
      whose composition is not reconstructable — scales or combines all
      types, so its damage is redistributed proportionally to the typed
      totals (dropped entirely if that total is zero).
    """
    totals = {"physical": 0.0, "magic": 0.0, "true": 0.0}
    redistributed_damage = 0.0

    for entry in breakdown.values():
        if entry.get("informational"):
            continue
        by_type = entry.get("damage_by_type")
        if by_type is not None:
            # Keys are validated DamagePart/DamageType values
            # (physical/magic/true); a stray key should raise.
            for dtype, amount in by_type.items():
                totals[dtype] += amount
        elif entry.get("damage_type") in totals:
            totals[entry["damage_type"]] += entry.get("total_damage", 0.0)
        else:
            redistributed_damage += entry.get("total_damage", 0.0)

    typed_total = sum(totals.values())
    if typed_total > 0:
        for dtype in totals:
            totals[dtype] += redistributed_damage * (totals[dtype] / typed_total)

    return totals
