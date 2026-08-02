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

import math
import random
from collections import Counter
from dataclasses import dataclass, field
from collections.abc import Sequence
from typing import Any, Callable

from . import item_effects
from .ability_spec import DamagePart
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
        self._resolve_armor_from_target()

    def _resolve_armor_from_target(self) -> None:
        """Re-derive reduced/effective armor from the target's armor."""
        self.reduced_armor = reduce_resistance(
            self.target_armor, self.bc_reduction * 100.0
        )
        self.effective_armor = apply_armor_penetration(
            self.reduced_armor, self.flat_armor_pen, self.ability_armor_pen_percent
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
    target_magic_shield: float = 0.0
    target_physical_shield: float = 0.0
    target_general_shield: float = 0.0
    target_basic_damage_multiplier: float = 1.0
    target_basic_damage_flat_reduction: float = 0.0
    target_basic_damage_flat_reduction_cap: float = 0.0
    target_critical_strike_damage_multiplier: float = 1.0
    target_threshold_shield_amount: float = 0.0
    target_threshold_shield_health_ratio: float = 0.0
    target_threshold_shield_duration: float = 0.0
    target_threshold_shield_damage_type: str = "all"
    target_threshold_health_bonus: float = 0.0
    target_threshold_health_heal: float = 0.0
    target_threshold_health_ratio: float = 0.0
    target_threshold_health_duration: float = 0.0
    enforce_resource_limits: bool = False
    roster_target_index: int = 0
    roster_target_count: int = 1


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
    enforce_resource_limits: bool
    target_basic_damage_multiplier: float
    target_basic_damage_flat_reduction: float
    target_basic_damage_flat_reduction_cap: float
    target_critical_strike_damage_multiplier: float
    roster_target_index: int
    roster_target_count: int
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
        effectiveness: On-hit effectiveness multiplier on each proc's raw
            damage (Azir soldiers proc at 50%).
        target_basic_damage_multiplier: Target-side percentage modifier for
            the rare item proc that the Wiki tags as basic damage.

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
            raw_damage = effect.source.raw_damage(inputs) * effectiveness
            mitigated = _mitigate(
                raw_damage,
                effect.source.damage_type,
                resists,
                magic_amp,
            )
            if effect.source.basic_damage and effect.source.damage_type != "true":
                mitigated *= target_basic_damage_multiplier
            total_damage += mitigated
            current_hp -= mitigated

        # Reduce HP from auto attack + other on-hit damage
        current_hp -= auto_damage_per_hit + other_on_hit_per_hit
        if current_hp < 0:
            current_hp = 0

    return total_damage


def _schedule_cooldown_procs(
    num_auto_attacks: int,
    autos_per_second: float,
    proc_cooldown: float,
) -> list[int]:
    """Schedule per-target-cooldown on-hit procs onto the auto timeline.

    The first auto always procs; each later auto procs iff its timestamp
    (auto index / effective attack rate) is at least ``proc_cooldown``
    after the previous proc (Jarvan IV's Martial Cadence pattern).

    Args:
        num_auto_attacks: Total auto attacks in the fight.
        autos_per_second: Effective auto rate (attack_speed * uptime) —
            the same rate ``num_auto_attacks`` was derived from, so auto
            timestamps span the fight window.
        proc_cooldown: Per-target cooldown between procs, in seconds.

    Returns:
        Sorted 0-indexed auto indices on which the effect procs.
    """
    if num_auto_attacks <= 0 or autos_per_second <= 0:
        return []
    proc_autos: list[int] = []
    next_ready = 0.0
    for i in range(num_auto_attacks):
        timestamp = i / autos_per_second
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
) -> float:
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
        Total mitigated damage across all procs.
    """
    if not proc_autos:
        return 0.0

    pct = on_hit_data["current_health_percent"] / 100.0
    min_damage = on_hit_data.get("min_damage", 0.0)
    dmg_type = on_hit_data.get("damage_type", "physical")
    proc_set = set(proc_autos)

    current_hp = target_health
    total_damage = 0.0
    for i in range(num_auto_attacks):
        if i in proc_set:
            raw_damage = max(pct * current_hp, min_damage) * effectiveness
            mitigated = _mitigate(raw_damage, dmg_type, resists, magic_amp)
            total_damage += mitigated
            current_hp -= mitigated

        # Reduce HP from auto attack + other on-hit damage
        current_hp -= auto_damage_per_hit + other_on_hit_per_hit
        current_hp = max(current_hp, 0.0)

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
    effectiveness: float = 1.0,
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
            raw_damage = effect.source.raw_damage(inputs) * effectiveness
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
    return [(dtype, damage)] if dtype in {"physical", "magic", "true"} and damage > 0 else []


def _ordered_damage_events(
    breakdown: dict[str, Any],
    ability_damages: dict[str, dict[str, Any]],
    cast_order: list[str],
    *,
    cast_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Reconstruct the engine's certified damage order from its own rows.

    Ability rows are split into cast instances and follow the accepted cast
    timeline. Autos and item effects retain the engine's existing coarse
    phase order after the selected rotation. Untyped amplifier rows are
    distributed across the already-known damage composition so shield
    accounting never invents a fourth damage type.

    This ledger is deliberately internal. It is exact at the cast boundary,
    but it does not claim champion-specific spell-shield behavior within a
    multi-hit cast; those target items remain fail-closed until each ability
    supplies the necessary interaction metadata.
    """
    events: list[dict[str, Any]] = []
    sequence = 0

    def add(
        source_key: str,
        damage_type: str,
        damage: float,
        *,
        time: float,
        ordinal: int,
        phase: str,
        order: float | None = None,
    ) -> None:
        nonlocal sequence
        if damage <= 0 or damage_type not in {"physical", "magic", "true"}:
            return
        events.append(
            {
                "source_key": source_key,
                "damage_type": damage_type,
                "damage": damage,
                "time": time,
                "ordinal": ordinal,
                "phase": phase,
                "sequence": sequence,
                "order": float(sequence) if order is None else order,
            }
        )
        sequence += 1

    def add_declared_events(
        source_key: str,
        entry: dict[str, Any],
        *,
        default_phase: str,
    ) -> bool:
        """Append an engine-authored event list, returning whether it existed."""
        declared = entry.get("damage_events")
        if not isinstance(declared, list):
            return False
        phase = str(entry.get("event_phase", default_phase))
        if phase not in {"ability", "auto", "effect", "amplifier"}:
            phase = default_phase
        for ordinal, event in enumerate(declared, start=1):
            if not isinstance(event, dict):
                continue
            add(
                source_key,
                str(event.get("damage_type", "")),
                float(event.get("damage", 0.0)),
                time=float(event.get("time", 0.0)),
                ordinal=ordinal,
                phase=phase,
                order=(
                    float(event["timeline_order"])
                    if event.get("timeline_order") is not None
                    else None
                ),
            )
        return True

    timeline_by_slot: dict[str, list[dict[str, Any]]] = {}
    for event in cast_events or []:
        timeline_by_slot.setdefault(str(event.get("slot", "")), []).append(event)

    last_ability_time = 0.0
    for key in cast_order:
        entry = breakdown.get(key)
        if not entry or entry.get("informational"):
            continue
        casts = max(0, int(entry.get("casts", 0)))
        if casts <= 0:
            continue
        slot_timeline = timeline_by_slot.get(key, [])
        instances = max(1, int(ability_damages.get(key, {}).get("cast_instances", 1)))
        for cast_index in range(casts):
            cast_time = (
                float(slot_timeline[cast_index].get("time", 0.0))
                if cast_index < len(slot_timeline)
                else 0.0
            )
            last_ability_time = max(last_ability_time, cast_time)
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
                )
        else:
            damage = float(entry.get("total_damage", 0.0))
            if damage > 0:
                untyped.append((key, damage))

    typed_totals = {
        dtype: sum(
            event["damage"] for event in events if event["damage_type"] == dtype
        )
        for dtype in ("physical", "magic", "true")
    }
    typed_total = sum(typed_totals.values())
    if typed_total > 0:
        for key, damage in untyped:
            for dtype, typed_damage in typed_totals.items():
                if typed_damage > 0:
                    add(
                        key,
                        dtype,
                        damage * typed_damage / typed_total,
                        time=last_ability_time,
                        ordinal=1,
                        phase="amplifier",
                    )

    return sorted(
        events,
        key=lambda event: (
            event["time"],
            event["order"],
            {"ability": 0, "auto": 1, "effect": 2, "amplifier": 3}[event["phase"]],
            event["sequence"],
        ),
    )


def _event_timeline_coverage(
    breakdown: dict[str, Any],
    ability_damages: dict[str, dict[str, Any]],
    cast_order: list[str],
) -> dict[str, Any]:
    """Certify which active rows have authored or cast-boundary ordering."""
    exact: list[str] = []
    coarse: list[str] = []
    cast_keys = set(cast_order)
    for key, entry in breakdown.items():
        if entry.get("informational") or float(entry.get("total_damage", 0.0)) <= 0:
            continue
        damage_events = entry.get("damage_events")
        if not isinstance(damage_events, list):
            damage_events = entry.get("timeline_events")
        event_total = (
            sum(float(event.get("damage", 0.0)) for event in damage_events)
            if isinstance(damage_events, list) and damage_events
            else None
        )
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
    return {
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


@dataclass
class _ThresholdHealthState:
    """Ordered temporary-health/healing state for Protoplasm Lifeline.

    The Wiki sources the pre-damage trigger, five-second health increase, and
    heal. It does not document what happens to current health when that
    temporary maximum health expires, so a fight reaching that boundary is
    withheld instead of guessing.
    """

    base_max_health: float
    current_health: float
    bonus_health: float = 0.0
    heal_total: float = 0.0
    health_ratio: float = 0.0
    duration: float = 0.0
    triggered: bool = False
    trigger_time: float = -1.0
    last_time: float = 0.0
    healing_received: float = 0.0

    @property
    def maximum_health(self) -> float:
        return self.base_max_health + (self.bonus_health if self.triggered else 0.0)

    def advance_to(self, event_time: float) -> None:
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
            self.current_health > 0
            and self.duration > 0
            and elapsed > 0
            and self.heal_total > 0
        ):
            offered = self.heal_total * elapsed / self.duration
            received = min(offered, max(0.0, self.maximum_health - self.current_health))
            self.current_health += received
            self.healing_received += received
        self.last_time = max(self.last_time, event_time)

    def trigger_before(self, damage: float, event_time: float) -> bool:
        """Grant health before damage that would cross Lifeline's threshold."""
        if (
            self.triggered
            or damage <= 0
            or self.bonus_health <= 0
            or self.health_ratio <= 0
            or self.duration <= 0
            or self.current_health - damage
            >= self.maximum_health * self.health_ratio
        ):
            return False
        self.triggered = True
        self.trigger_time = event_time
        self.last_time = event_time
        self.current_health += self.bonus_health
        return True

    def take_damage(self, damage: float) -> None:
        self.current_health = max(0.0, self.current_health - max(0.0, damage))


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
    health_state = _ThresholdHealthState(
        base_max_health=target_health,
        current_health=target_health,
        bonus_health=max(0.0, target_threshold_health_bonus),
        heal_total=max(0.0, target_threshold_health_heal),
        health_ratio=max(0.0, target_threshold_health_ratio),
        duration=max(0.0, target_threshold_health_duration),
    )
    magic_shield = max(0.0, target_magic_shield)
    physical_shield = max(0.0, target_physical_shield)
    general_shield = max(0.0, target_general_shield)
    threshold_shield = 0.0
    threshold_shield_expires = -1.0
    threshold_triggered = False
    lifeline_threshold_hp = target_health * max(
        0.0, target_threshold_shield_health_ratio
    )
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
        health_state.advance_to(event_time)
        if threshold_shield > 0 and event_time > threshold_shield_expires:
            threshold_shield = 0.0
        source_key = str(event.get("source_key", ""))
        if (
            source_key == _LIANDRY_BURN_KEY
            and health_state.triggered
            and event_time > health_state.trigger_time + 1e-9
        ):
            adjusted = damage * health_state.maximum_health / target_health
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
            and health_state.current_health
            < health_state.maximum_health * effect.health_threshold
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

        if dtype == "magic":
            absorbed = min(magic_shield, event_damage)
            magic_shield -= absorbed
            event_damage -= absorbed
        elif dtype == "physical":
            absorbed = min(physical_shield, event_damage)
            physical_shield -= absorbed
            event_damage -= absorbed
        if event_damage > 0:
            absorbed = min(general_shield, event_damage)
            general_shield -= absorbed
            event_damage -= absorbed
        trigger_matches = (
            target_threshold_shield_damage_type == "all"
            or target_threshold_shield_damage_type == dtype
        )
        if (
            event_damage > 0
            and not threshold_triggered
            and target_threshold_shield_amount > 0
            and lifeline_threshold_hp > 0
            and trigger_matches
            and health_state.current_health - event_damage < lifeline_threshold_hp
        ):
            threshold_triggered = True
            threshold_shield = target_threshold_shield_amount
            threshold_shield_expires = event_time + target_threshold_shield_duration
        if threshold_shield > 0 and event_damage > 0:
            absorbed = min(threshold_shield, event_damage)
            threshold_shield -= absorbed
            event_damage -= absorbed
        health_state.trigger_before(event_damage, event_time)
        health_state.take_damage(event_damage)

    adjustments = {
        "liandry_delta": liandry_delta,
        "liandry_events": liandry_events,
        "threshold_health_triggered": health_state.triggered,
        "threshold_health_trigger_time": health_state.trigger_time,
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
        enforce_resource_limits=config.enforce_resource_limits,
        target_basic_damage_multiplier=config.target_basic_damage_multiplier,
        target_basic_damage_flat_reduction=(
            config.target_basic_damage_flat_reduction
        ),
        target_basic_damage_flat_reduction_cap=(
            config.target_basic_damage_flat_reduction_cap
        ),
        target_critical_strike_damage_multiplier=(
            config.target_critical_strike_damage_multiplier
        ),
        roster_target_index=max(0, int(config.roster_target_index)),
        roster_target_count=max(1, int(config.roster_target_count)),
        resists=resists,
        magic_amp=damage_effects.magic_amp,
        ability_amp=(
            damage_effects.ability_amp.multiplier(
                champion_stats, config.include_actives
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
    resource_spent: float = 0.0
    resource_remaining: float = 0.0
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


def _make_shred_ramp(
    resists: Resists,
    ability_info: dict[str, Any],
    ult_cast: bool,
    vile_decay_stacks: int,
) -> _ShredRamp | None:
    """Build the ramp for a ``stacks``-declaring target_debuff, else None."""
    debuff = ability_info.get("target_debuff")
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
) -> float:
    """Mitigated damage for *hits* identical hits of one damage part."""
    if part.damage_type == "true":
        mitigated = raw * hits
    elif part.damage_type == "physical":
        mitigated = apply_resistance(raw, state.resists.effective_armor) * hits
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
    for cast_index in range(num_casts):
        price = pricing[cast_index] if pricing is not None else _NO_PRICING
        rock_solid_consumed = False
        for part_index, part in enumerate(parts):
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
                    + crit_probability
                    * state.crit_multiplier
                    * target_crit_multiplier
                )
            rock_solid_instances = int(
                part.basic_damage
                and part.damage_type != "true"
                and hits > 0
                and raw > 0
                and not rock_solid_consumed
            )
            mitigated = 0.0
            for hit_index in range(hits):
                hit_damage = _mitigate_hits(
                    state,
                    part,
                    raw,
                    ability_mr,
                    1,
                    rock_solid_instances=int(
                        rock_solid_instances > 0 and hit_index == 0
                    ),
                )
                mitigated += hit_damage
                if part.time_offset is not None and (
                    hits == 1 or part.hit_interval is not None
                ):
                    cast_time = (
                        cast_times[cast_index]
                        if cast_times is not None and cast_index < len(cast_times)
                        else 0.0
                    )
                    damage_events.append(
                        {
                            "time": cast_time
                            + part.time_offset
                            + hit_index * (part.hit_interval or 0.0),
                            "damage_type": part.damage_type,
                            "damage": hit_damage,
                            "cast_ordinal": cast_index + 1,
                            "part_ordinal": part_index + 1,
                            "hit_ordinal": hit_index + 1,
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


def _effective_timed_cooldown(
    state: "FightState",
    result: "RotationResult",
    ability_key: str,
    ability_info: dict,
    basic_ability_haste: float,
) -> float:
    """Effective recast cooldown in timed mode: ability haste, Spear of
    Shojin basic-ability haste (Q/W/E), and Navori auto-attack refunds."""
    base_cd = ability_info.get("cooldown", 0.0)
    total_haste = state.ability_haste
    if ability_key in ("Q", "W", "E"):
        total_haste += basic_ability_haste
    cd = effective_cooldown(base_cd, total_haste)
    if result.navori_refund > 0 and cd > 0 and ability_key in ("Q", "W", "E"):
        cd = _navori_effective_cd(cd, result.autos_per_second, result.navori_refund)
    return cd


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
            next_ready[key] = (
                now + cast_times[key] + cooldown_delays[key] + cooldowns[key]
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
    """Drop casts that cannot be paid for on the shared cast timeline."""
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
    for cast_time, _order_index, ordinal, key in events:
        maximum = base_maximum + (
            maximum_bonus if cast_time < maximum_bonus_until else 0.0
        )
        remaining = min(
            maximum, remaining + max(0.0, cast_time - previous_time) * regen
        )
        previous_time = cast_time
        info = state.ability_damages[key]
        parent = info.get("recast_of")
        if parent and ordinal not in accepted_ordinals.get(parent, set()):
            omitted.append(key)
            continue
        cost = float(info.get("resource_cost", 0.0))
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
        resource_by_cast[(key, accepted_ordinal)] = {
            "resource_before": before,
            "resource_restored": restored,
            "resource_after": remaining,
        }

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
        autos_per_second = state.attack_speed * state.auto_attack_uptime
        if autos_per_second > 0:
            for index in range(state.num_auto_attacks):
                applications.append((index / autos_per_second, None, index))

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
    cast_event_order = {slot: index for index, slot in enumerate(state.cast_order)}
    result.cast_events = sorted(
        (
            {
                "time": round(cast_time, 3),
                "slot": ability_key,
                "name": ability_damages[ability_key].get("name", ability_key),
                "ordinal": ordinal + 1,
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
    state.stack_timeline = _build_stack_timeline(state, plan)
    timeline = state.stack_timeline

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
            if isinstance(empower, dict) and "swing_parts" in empower:
                parts = parts + tuple(empower["swing_parts"])
            else:
                swing = DamagePart(
                    "physical",
                    state.champion_stats.get("attack_damage", 0.0),
                    count=hits,
                    crit_effectiveness=1.0,
                    basic_damage=True,
                    # A basic attack is 100% total AD, so a mid-fight
                    # bonus-AD steroid raises the forced swing 1:1.
                    bonus_ad_ratio=1.0,
                )
                parts = parts + (swing,)
        # A ramped shred (Corki E) stacks up across this ability's own
        # hits; an unramped one lands in full after it (below).
        shred_ramp = _make_shred_ramp(resists, ability_info, ult_cast, ability_stacks)
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
            cast_times=plan.times.get(ability_key),
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
        timing_is_authored = bool(parts) and all(
            part.time_offset is not None
            and (part.count <= 1 or part.hit_interval is not None)
            for part in parts
        )
        if timing_is_authored and ability_events:
            breakdown[ability_key]["damage_events"] = [
                {
                    **event,
                    "damage": event["damage"] * state.ability_amp,
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
            detail = f"{num_casts} cast{'' if num_casts == 1 else 's'}"
            detail += f", {forced_swings} attack{'' if forced_swings == 1 else 's'}"
            if state.crit_chance > 0:
                detail += f" @ {round(state.crit_chance * 100)}% crit"
            breakdown[ability_key]["detail"] = detail
        if damage_type == "mixed":
            # Exact composition for the physical/magic/true split (the
            # ability amp scales every part uniformly).
            breakdown[ability_key]["damage_by_type"] = {
                dtype: amount * state.ability_amp
                for dtype, amount in ability_by_type.items()
            }
        # Champion-minted display text (e.g. Aurelion Sol E's execute
        # threshold) rides the entry onto its breakdown row untouched.
        if "detail" in ability_info:
            breakdown[ability_key]["detail"] = ability_info["detail"]
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
            for _ in range(applications):
                hp_now = max(0.0, target_health - mitigated_damage_dealt)
                result.ability_item_applications.append(
                    AbilityItemApplication(
                        effectiveness=effectiveness,
                        target_hp=hp_now,
                        on_hit=is_on_hit,
                        on_attack="on_attack" in triggers,
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
            _apply_basic_amp(
                state,
                part,
                _mitigate(part.amount, part.damage_type, resists, state.magic_amp)
                * part.count,
                procs=proc_count,
            )
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
        # Champion-minted display text (e.g. Braum P's cycle summary) and
        # count label (e.g. Diana's "cleaves") ride the entry onto its
        # breakdown row, as in the rotation.
        for display_key in ("detail", "unit"):
            if display_key in info:
                state.breakdown[key][display_key] = info[display_key]
        state.total_damage += proc_total


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

    raw_total = 0.0
    stacks = timeline.starting_stacks
    previous_hit = 0.0
    for application in timeline.applications:
        if stacks > 0:
            # Ticks stop ``duration`` after the last application even if
            # the next one comes later (the chain expired meanwhile).
            raw_total += integrate(
                previous_hit, min(application.time, previous_hit + duration), stacks
            )
        stacks = application.stacks_after
        previous_hit = application.time
    # Committed tail: the last application's full window of ticks.
    raw_total += integrate(previous_hit, previous_hit + duration, stacks)

    damage_type = spec.get("damage_type", "physical")
    total = _mitigate(raw_total, damage_type, state.resists, state.magic_amp)
    # A seeded-only fight lands no applications; the pre-fight stacks are
    # what the row is reporting, so they are its count.
    applications = len(timeline.applications) or timeline.starting_stacks
    state.breakdown[f"stacking_dot_{dot_key}"] = {
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
    state.total_damage += total


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


def _auto_attack_timestamps(state: FightState) -> list[float]:
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
    buff = state.damage_effects.ultimate_auto_buff
    empowered = state.empowered_autos if buff is not None else 0
    if empowered <= 0:
        return [index / normal_rate for index in range(state.num_auto_attacks)]

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
    autos_per_second = state.attack_speed * state.auto_attack_uptime

    def bonus_ad(auto_index: int) -> float:
        time = auto_index / autos_per_second if autos_per_second > 0 else 0.0
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
    effective_armor = resists.effective_armor

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
    if auto_attack_override:
        override_ad_ratio = auto_attack_override.get("ad_ratio", 1.0)
        override_crit_as_bonus = auto_attack_override.get("crit_as_bonus", False)
        override_replace_raw = auto_attack_override.get("replace_raw")
        override_damage_type = auto_attack_override.get("damage_type", "physical")
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
                swing_ad * override_ad_ratio * (1 + crit_chance * bonus_crit_ratio)
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
                    weight
                    * converted_swing_damage(outcome_raw, critical=critical)
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
            converted_critical = (
                not override_crit_as_bonus
                and (natural_crit or is_empowered or is_sundered)
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
                normal_mitigated = (
                    crit_chance
                    * (
                        converted_swing_damage(
                            swing_ad * crit_multiplier, critical=True
                        )
                        if i < converted_auto_limit
                        else _mitigate_basic_attack_swing(
                            state,
                            swing_ad * crit_multiplier,
                            critical_strike=True,
                        )
                    )
                    + (1.0 - crit_chance)
                    * (
                        converted_swing_damage(swing_ad, critical=False)
                        if i < converted_auto_limit
                        else _mitigate_basic_attack_swing(state, swing_ad)
                    )
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
        "damage_events": auto_events,
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
        for i in range(num_auto_attacks):
            ds_ad = attack_damage * ds_ratio
            if deterministic:
                ds_crit = False
                double_shot_total += (
                    crit_chance
                    * _mitigate_basic_attack_swing(
                        state,
                        ds_ad * crit_multiplier,
                        critical_strike=True,
                    )
                    + (1.0 - crit_chance)
                    * _mitigate_basic_attack_swing(state, ds_ad)
                )
                continue
            else:
                ds_crit = random.random() < crit_chance
                if ds_crit:
                    ds_crits += 1
                    raw_ds = ds_ad * crit_multiplier
                else:
                    raw_ds = ds_ad
            double_shot_total += _mitigate_basic_attack_swing(
                state,
                raw_ds,
                critical_strike=ds_crit,
            )

        ds_non_crits = num_auto_attacks - ds_crits
        breakdown["double_shot"] = {
            "name": double_shot_info.get("name", "Double Shot"),
            "count": num_auto_attacks,
            "num_crits": ds_crits,
            "num_non_crits": ds_non_crits,
            "total_damage": double_shot_total,
            "damage_type": "physical",
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

    # Process fixed-formula per-hit effects. Current-health effects are
    # simulated below because each application changes the next one's input.
    damage_inputs = _damage_inputs(state)
    for effect in state.damage_effects.per_hits:
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
        if num_auto_attacks == 0 and not counts_ability_hits:
            continue

        raw_per_hit = on_hit_data.get("damage_per_hit", 0.0) * on_hit_effectiveness
        if raw_per_hit <= 0:
            continue

        dmg_type = on_hit_data.get("damage_type", "magic")
        per_hit = _mitigate(raw_per_hit, dmg_type, resists, magic_amp)

        hits = on_hit_hits + (rotation.total_ability_hits if counts_ability_hits else 0)

        # Availability-limited on-hits (Bard meeps: stock + recharge)
        # apply at most max_procs times; autos beyond the cap are plain.
        max_procs = on_hit_data.get("max_procs")
        if max_procs is not None:
            hits = min(hits, int(max_procs))

        stacks_required = on_hit_data.get("stacks_required", 0)
        ramping = bool(on_hit_data.get("ramping"))
        stack_ramp = on_hit_data.get("stack_ramp")
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
        elif ramping and stacks_required > 1:
            # Ramping every-Nth proc (Bel'Veth R): proc k deals
            # k x per_hit — stacks accumulate and never reset, so the
            # total is per_hit x (1 + 2 + ... + procs).
            procs = hits // stacks_required
            ability_on_hit_damage = per_hit * procs * (procs + 1) / 2.0
        elif stacks_required > 1 and counts_ability_hits:
            # Shared auto+ability stack counter (e.g. Aurora P): only
            # complete procs deal damage — partial stacks expire.
            ability_on_hit_damage = (
                per_hit * stacks_required * (hits // stacks_required)
            )
        else:
            # Autos-only on-hit (e.g. Vayne W): smooth per-hit average.
            ability_on_hit_damage = per_hit * hits
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
            effectiveness=on_hit_effectiveness,
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
        for ability_key, ability_info in state.ability_damages.items():
            on_hit_data = ability_info.get("on_hit")
            if not on_hit_data:
                continue
            if "proc_cooldown" in on_hit_data:
                proc_autos = _schedule_cooldown_procs(
                    num_auto_attacks, autos_per_second, on_hit_data["proc_cooldown"]
                )
            elif "proc_window" in on_hit_data:
                if breakdown.get(ability_key, {}).get("casts", 0) < 1:
                    continue  # rider exists only after the ability is cast
                # Autos land at i / autos_per_second; the triggering auto
                # at t=0 always fits a positive window.
                autos_in_window = max(
                    1, int(autos_per_second * on_hit_data["proc_window"])
                )
                proc_autos = list(range(min(num_auto_attacks, autos_in_window)))
            else:
                continue
            if not proc_autos:
                continue
            proc_total = _simulate_cooldown_current_health_procs(
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
            on_hit_total += proc_total
            breakdown[f"on_hit_ability_{ability_key}"] = {
                "name": on_hit_data.get("name", f"{ability_key} (on-hit)"),
                "count": len(proc_autos),
                "damage_per_hit": proc_total / len(proc_autos),
                "total_damage": proc_total,
                "damage_type": on_hit_data.get("damage_type", "physical"),
                "unit": "procs",
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


def _add_spellblade_true_rider(
    state: FightState,
    source: item_effects.DamageSource,
    raw_per_proc: float,
    procs: int,
) -> None:
    """Add a champion's true-damage rider on spellblade procs (Corki P).

    The wiki special-cases spellblade effects into Hextech Munitions:
    each proc deals ``spellblade_bonus_true_ratio`` of its own
    PRE-mitigation damage again as true damage. This is ADDED ON TOP of
    the proc; its sibling ``spellblade_true_ratio`` (Camille Q2) instead
    CONVERTS that share of the proc out of the item's own damage type.
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

        if plain > 0 or converted == 0:  # unconverted builds keep the row as-is
            state.breakdown[source.breakdown_key] = {
                "name": source.display_name,
                "count": plain,
                "damage_per_hit": result.damage_per_proc,
                "unit": "procs",
                "total_damage": result.damage_per_proc * plain,
                "damage_type": source.damage_type,
            }
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
        _add_spellblade_true_rider(state, source, raw_sb, result.procs)

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


def _ability_damage_proc_triggers(
    state: FightState,
    rotation: RotationResult,
    effect: item_effects.CooldownProcEffect,
) -> list[dict[str, Any]]:
    """Schedule an ability-triggered proc onto legal damaging casts."""
    cast_sources = set(state.cast_order)
    ordered = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
    )
    unique_hits: list[dict[str, Any]] = []
    seen: set[tuple[str, int, float]] = set()
    for event in ordered:
        if event["source_key"] not in cast_sources or event["damage"] <= 0:
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
        desired_multiplier = 1.0 + max(
            0,
            source.multi_target_charges - unique_targets,
        ) * source.repeated_target_multiplier
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
        proc_triggers = (
            _ability_damage_proc_triggers(state, rotation, effect)
            if effect.trigger == "ability_damage"
            else []
        )
        if effect.trigger == "ability_damage" and not proc_triggers:
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
        raw_per_proc = source.raw_damage(_damage_inputs(state))
        mitigated_per_proc = _mitigate(
            raw_per_proc, source.damage_type, resists, state.magic_amp
        )

        # Stormsurge and Zaz'Zak deal ability damage — amplified by Actualizer
        if source.is_ability_damage:
            mitigated_per_proc *= state.ability_amp
        mitigated_per_proc *= _charged_proc_target_share(state, source)
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
                    "damage": mitigated_per_proc,
                    "damage_type": source.damage_type,
                }
                for trigger in proc_triggers
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

    if num_auto_attacks > 0:
        inputs = _damage_inputs(state)
        for effect in state.damage_effects.first_autos:
            source = effect.source
            procs = min(effect.max_procs, num_auto_attacks)
            raw_damage = source.raw_damage(inputs) * procs * effectiveness
            mitigated = _mitigate(
                raw_damage, source.damage_type, resists, state.magic_amp
            )
            if source.basic_damage and source.damage_type != "true":
                mitigated *= state.target_basic_damage_multiplier
            breakdown[source.breakdown_key] = {
                "name": source.display_name,
                "count": procs,
                "damage_per_hit": mitigated / procs,
                "unit": "procs",
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
            raw_damage = source.raw_damage(inputs) * procs * effectiveness
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
            state.total_damage += mitigated

    apps = rotation.ability_item_applications
    if num_auto_attacks > 0 or apps:
        other_on_hit_per_hit = on_hits.static_on_hit_per_hit
        if on_hits.has_current_health_on_hit and on_hits.current_health_on_hit_avg > 0:
            other_on_hit_per_hit += on_hits.current_health_on_hit_avg

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
            if proc_autos:
                if effect.tracks_target_health:
                    total_damage += _simulate_stacking_on_hit_damage(
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
                else:
                    raw = (
                        source.raw_damage(_damage_inputs(state))
                        * len(proc_autos)
                        * effectiveness
                    )
                    total_damage += _mitigate(
                        raw, source.damage_type, resists, state.magic_amp
                    ) * (
                        state.target_basic_damage_multiplier
                        if source.basic_damage and source.damage_type != "true"
                        else 1.0
                    )

            breakdown[source.breakdown_key] = {
                "name": source.display_name,
                "count": procs,
                "damage_per_hit": total_damage / procs,
                "unit": "procs",
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
        liandry_row["total_damage"] = (
            float(liandry_row["total_damage"]) + liandry_delta
        )
        liandry_row["damage_events"] = adjustments["liandry_events"]
        state.total_damage += liandry_delta
    if shadowflame_bonus > 0:
        state.breakdown[f"shadowflame_{effect.item_name}"] = {
            "name": f"{effect.item_name} (Cinderbloom)",
            "total_damage": shadowflame_bonus,
            # Cinderbloom is computed from the ordered source ledger above.
            # Keep those bonus timestamps for precision certification without
            # replaying the bonus as a second shield-resolution damage source.
            "timeline_events": bonus_events,
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
    """Collect the notes documenting conditional item and timeline assumptions."""
    notes = state.notes
    notes.extend(state.damage_effects.conditional_notes)

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
    if auto_row.get("num_crits") is not None:
        # Rescale the crit split so num_crits + num_non_crits == count.
        crits = round(auto_row["num_crits"] * remaining / original_count)
        auto_row["num_crits"] = crits
        auto_row["num_non_crits"] = remaining - crits


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

    # ── Ability rotation, precomputed procs, DoTs, and Shaped Charge ────
    rotation = _compute_ability_rotation(state)
    _add_precomputed_proc_damage(state)
    _add_stacking_dot_damage(state)
    _add_shaped_charge_damage(state)

    # ── Auto attacks (per-auto crit simulation) ─────────────────────────
    autos = _simulate_auto_attacks(state)

    # ── On-hit damage layered onto the autos ────────────────────────────
    on_hits = _layer_on_hit_effects(state, autos, rotation)

    # ── Spellblade + Dusk and Dawn double on-hit ────────────────────────
    spellblade = _add_spellblade_damage(state, rotation, autos, on_hits)

    # ── Burn / DoT item damage ──────────────────────────────────────────
    _add_burn_damage(state, rotation)

    # ── Item procs (including ult-triggered Malignance) ─────────────────
    _add_item_proc_damage(state, rotation)

    # ── Active item damage ──────────────────────────────────────────────
    _add_item_active_damage(state)

    # ── Single-proc on-hits, Shadowflame, and Expose Weakness ───────────
    _add_single_proc_on_hits(state, rotation, autos, on_hits, spellblade)
    _add_shadowflame_cinderbloom(state, config, rotation)
    _add_expose_weakness(state, autos, spellblade)

    # ── Fight-wide damage amplifiers ────────────────────────────────────
    _apply_damage_amplifiers(state, rotation)

    # ── Empowered-auto swings shown on the ability that forced them ─────
    _reattribute_empowered_swings(state)

    # ── Execute threshold display (The Collector) ───────────────────────
    _add_execute_display(state)

    # ── Notes for conditional item assumptions ──────────────────────────
    _collect_fight_notes(state, rotation, on_hits)

    shield_outcome = _resolve_starting_shield_outcome(state, config, rotation)
    timeline_coverage = _event_timeline_coverage(
        state.breakdown, state.ability_damages, state.cast_order
    )
    if (
        shield_outcome["threshold_health_triggered"]
        and config.target_threshold_health_heal > 0
    ):
        timeline_coverage["complete"] = False
        timeline_coverage["certification"] = "partial_event_order"
        timeline_coverage["coarse_sources"] = sorted(
            set(timeline_coverage["coarse_sources"])
            | {"target_Protoplasm Harness"}
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
        "notes": state.notes,
        "cast_timeline": rotation.cast_events,
        "resource_spent": rotation.resource_spent,
        "resource_remaining": rotation.resource_remaining,
        "timeline_coverage": timeline_coverage,
        **shield_outcome,
        # Exposed for champion-specific ability calculators (Case 1: stack
        # acceleration). Champions like Vayne can check which autos grant
        # double stacks to calculate ability procs more accurately.
        "phantom_hit_autos": on_hits.phantom_hit_autos,
        "phantom_hit_count": on_hits.phantom_hit_count,
    }


def _resolve_starting_shield_outcome(
    state: FightState, config: FightConfig, rotation: RotationResult
) -> dict[str, float]:
    """Split post-mitigation TDD into shield absorption and health damage.

    TDD remains damage dealt. Shields are reported as a separate defensive
    outcome so the UI does not hide how much of that damage reached health.
    """
    magic_shield = max(0.0, config.target_magic_shield)
    physical_shield = max(0.0, config.target_physical_shield)
    general_shield = max(0.0, config.target_general_shield)
    magic_absorbed = 0.0
    physical_absorbed = 0.0
    general_absorbed = 0.0
    threshold_absorbed = 0.0
    health_state = _ThresholdHealthState(
        base_max_health=state.target_health,
        current_health=state.target_health,
        bonus_health=max(0.0, config.target_threshold_health_bonus),
        heal_total=max(0.0, config.target_threshold_health_heal),
        health_ratio=max(0.0, config.target_threshold_health_ratio),
        duration=max(0.0, config.target_threshold_health_duration),
    )
    threshold_shield = 0.0
    threshold_shield_expires = -1.0
    threshold_triggered = False
    threshold_hp = (
        state.target_health * max(0.0, config.target_threshold_shield_health_ratio)
    )
    for event in _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
    ):
        event_time = float(event["time"])
        health_state.advance_to(event_time)
        if threshold_shield > 0 and event_time > threshold_shield_expires:
            threshold_shield = 0.0
        remaining = event["damage"]
        if event["damage_type"] == "magic":
            absorbed = min(magic_shield, remaining)
            magic_shield -= absorbed
            magic_absorbed += absorbed
            remaining -= absorbed
        elif event["damage_type"] == "physical":
            absorbed = min(physical_shield, remaining)
            physical_shield -= absorbed
            physical_absorbed += absorbed
            remaining -= absorbed
        absorbed = min(general_shield, remaining)
        general_shield -= absorbed
        general_absorbed += absorbed
        remaining -= absorbed

        trigger_type = config.target_threshold_shield_damage_type
        trigger_matches = trigger_type == "all" or trigger_type == event["damage_type"]
        if (
            remaining > 0
            and not threshold_triggered
            and config.target_threshold_shield_amount > 0
            and threshold_hp > 0
            and trigger_matches
            and health_state.current_health - remaining < threshold_hp
        ):
            threshold_triggered = True
            threshold_shield = config.target_threshold_shield_amount
            threshold_shield_expires = (
                event_time + config.target_threshold_shield_duration
            )

        if threshold_shield > 0 and remaining > 0:
            absorbed = min(threshold_shield, remaining)
            threshold_shield -= absorbed
            threshold_absorbed += absorbed
            remaining -= absorbed
        health_state.trigger_before(remaining, event_time)
        health_state.take_damage(remaining)

    absorbed = (
        magic_absorbed
        + physical_absorbed
        + general_absorbed
        + threshold_absorbed
    )
    return {
        "shield_absorbed": absorbed,
        "magic_shield_absorbed": magic_absorbed,
        "physical_shield_absorbed": physical_absorbed,
        "general_shield_absorbed": general_absorbed,
        "threshold_shield_absorbed": threshold_absorbed,
        "health_damage": max(0.0, state.total_damage - absorbed),
        "threshold_health_triggered": health_state.triggered,
        "threshold_health_bonus_gained": (
            health_state.bonus_health if health_state.triggered else 0.0
        ),
        "target_healing_received": health_state.healing_received,
        "target_ending_health": health_state.current_health,
        "target_effective_max_health": health_state.maximum_health,
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
    - keys prefixed ``auto_attacks`` (the stream itself plus champion
      riders on it, e.g. Corki's true-damage instance),
      ``fiendhunter_true_damage``, ``on_hit_``, or ``spellblade_`` count
      as auto-attack damage.
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
            key.startswith("auto_attacks")
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
