"""Keystone rune values and effect formulas.

Mirrors ``item_effects`` ownership rules for runes: every numeric rune value
comes from ``data/runes.json`` (parsed from the League Wiki's rune data
templates) through typed accessors that raise, naming the rune and key, when
the parse degraded. No literal fallbacks.

Only keystones with a compile function in ``_KEYSTONE_COMPILERS`` are
modeled; selecting any other keystone fails closed with a clear error. The
full roster is still served to the UI through :func:`keystone_catalog` so
unimplemented keystones can be shown greyed out.

Unsealed Spellbook is deliberately NOT compiled (see ``ASSUMPTIONS``): its
effect is a summoner-spell selection state — the user must pick the equipped
spells and every swapped spell, and each summoner spell has its own effect —
and the cached wiki template carries no numeric values for it (``effects``
is empty, ``cooldown`` is null, and the swap-cooldown sentences use
unresolved ``{{#var:...}}`` placeholders). The existing architecture has no
summoner-spell model, so compiling it would invent numbers. It stays a
named, fail-closed rejection, greyed out in the catalog.
"""

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .data_fetcher import fetch_rune_data
from .item_effects import DamageInputs
from .state_lifecycle import SourceReceipt, StackRule, TimedStackState


def _load_rune_effects() -> dict[str, dict[str, Any]]:
    """Load the parsed rune registry; an absent cache means no runes.

    Copies the fetched mapping: the data layer serves its parsed-JSON
    cache by reference, and ``refresh_rune_effects`` clears this dict in
    place — clearing the shared cache object would erase the source.
    """
    try:
        return dict(fetch_rune_data())
    except (FileNotFoundError, ValueError):
        return {}


RUNE_EFFECTS: dict[str, dict[str, Any]] = _load_rune_effects()


def _at_level(values: "tuple[float, ...] | list[float]", level: int) -> float:
    """Read a per-level table at one champion level, clamped to its ends."""
    return values[max(1, min(level, len(values))) - 1]


def refresh_rune_effects() -> None:
    """Re-read data/runes.json in place after a data update."""
    RUNE_EFFECTS.clear()
    RUNE_EFFECTS.update(_load_rune_effects())


ASSUMPTIONS: tuple[str, ...] = (
    "Unsealed Spellbook is intentionally not compiled. It is a summoner-spell "
    "selection state: the user must choose the equipped spells and each swap, "
    "and every summoner spell has its own effect (damage, shield, heal, "
    "movement, or CC). The cached wiki template (data/runes.json) has empty "
    "'effects' and null 'cooldown', and its swap-cooldown sentences use "
    "unresolved {{#var:...}} placeholders, so no honest numbers exist to "
    "compile. Modeling it would also need a summoner-spell packet model, "
    "cast-time scheduling, and spell-selection UI — files outside this "
    "module's ownership. It therefore stays a named fail-closed rejection "
    "('not modeled yet'), and the catalog shows it greyed out.",
    "The compiler reads only keys a keystone's own template authored. Some "
    "registry entries carry mis-attributed generic-parse keys (Lethal Tempo "
    "and Conqueror record a 'deathfire_tick_interval_seconds' from the shared "
    "'every N seconds' prose; Arcane Comet records its max-range ratio pair "
    "under 'deathfire_*' keys). These are parser false positives: no compiler "
    "reads them, they must never be treated as sourced values, and fixing "
    "them belongs to rune_parser (generic regexes must be Deathfire-scoped).",
    "Arcane Comet's proc is priced at the assumed 375-unit travel distance "
    "(mid-range poke); every comet is assumed to land. Aery's return travel "
    "has no sourced duration, so the next signal uses the sourced linger "
    "boundary as a lower bound. First Strike assumes the user initiates "
    "combat. These assumptions are disclosed in the fight notes by the "
    "engine.",
    "Dark Harvest's sourced 1.75s delay is the Soul-reap delay; the wiki "
    "prices the damage as immediate on the triggering hit. The compiler "
    "stores the value generically as proc_delay_seconds, and any engine that "
    "lands the damage at trigger + delay is making an engine-side choice.",
)


@dataclass(frozen=True, slots=True)
class KeystoneProcEffect:
    """A stack-triggered keystone proc with a cooldown (Electrocute-class).

    ``raw_damage`` prices one proc; ``damage_type`` resolves the adaptive
    physical/magic choice from the champion's stats. Stack accumulation and
    cooldown gating live in the fight engine, which owns the timeline.
    """

    keystone_name: str
    breakdown_key: str
    display_name: str
    stacks_required: int
    stack_window_seconds: float
    cooldown_seconds: float
    proc_delay_seconds: float
    raw_damage: Callable[[DamageInputs], float]
    damage_type: Callable[[Mapping[str, float]], str]


@dataclass(frozen=True, slots=True)
class KeystoneWindowAmpEffect:
    """A combat-opening damage-window keystone (First Strike-class).

    Post-mitigation damage dealt inside the opening window gains
    ``bonus_damage_ratio`` as bonus true damage; activation grants flat
    gold plus a melee/ranged share of the bonus damage as gold. Window
    summation lives in the fight engine, which owns the damage ledger.
    A continuous fight activates the buff exactly once, so the rune's
    out-of-combat cooldown never gates anything the engine models.
    """

    keystone_name: str
    breakdown_key: str
    display_name: str
    window_seconds: float
    bonus_damage_ratio: float
    activation_gold: float
    gold_conversion_melee: float
    gold_conversion_ranged: float

    def gold_conversion(self, is_melee: bool) -> float:
        """The share of bonus damage returned as gold for this range class."""
        return self.gold_conversion_melee if is_melee else self.gold_conversion_ranged


@dataclass(frozen=True, slots=True)
class KeystoneProcAmpEffect:
    """A stacked proc that then amplifies the rest of the fight (PTA-class).

    Basic attacks build stacks that expire ``stack_duration_seconds``
    after the last application; reaching ``stacks_required`` consumes
    them for ``raw_damage`` adaptive damage and turns on a lasting
    ``damage_amp_ratio`` amplifier of all non-true damage. The buff ends
    only out of combat, so a continuous fight keeps it from first proc
    to the end. Stack walking and amp summation live in the fight
    engine, which owns the timeline and the damage ledger.
    """

    keystone_name: str
    breakdown_key: str
    display_name: str
    stacks_required: int
    stack_duration_seconds: float
    cooldown_seconds: float
    damage_amp_ratio: float
    raw_damage: Callable[[DamageInputs], float]
    damage_type: Callable[[Mapping[str, float]], str]

    @property
    def amp_breakdown_key(self) -> str:
        """Ledger key for the lasting-amp row, beside the proc row's key."""
        return f"{self.breakdown_key} amp"

    @property
    def amp_display_name(self) -> str:
        """Display name for the lasting-amp breakdown row."""
        return f"{self.keystone_name} amp (keystone)"


@dataclass(frozen=True, slots=True)
class KeystoneAbilityProcEffect:
    """An ability-cast-triggered proc on a leveled cooldown (Arcane Comet-class).

    Each damaging ability cast fires the proc when it is off cooldown;
    basic attacks never trigger it, and damage over time neither
    triggers nor extends anything (unlike the Liandry's burn family) —
    the trigger stream is ability casts alone. ``raw_damage`` prices one
    proc at the assumed travel distance: the wiki's damage grows with
    how far the comet flies (``distance_amp_ratio`` holds the resulting
    multiplier bonus), and every comet is assumed to land. Cast walking
    and cooldown gating live in the fight engine, which owns the
    timeline.
    """

    keystone_name: str
    breakdown_key: str
    display_name: str
    cooldown_by_level: tuple[float, ...]
    proc_delay_seconds: float
    assumed_travel_distance: float
    distance_amp_ratio: float
    raw_damage: Callable[[DamageInputs], float]
    damage_type: Callable[[Mapping[str, float]], str]

    def cooldown_at(self, level: int) -> float:
        """The proc cooldown at one champion level, clamped to the table."""
        return _at_level(self.cooldown_by_level, level)


@dataclass(frozen=True, slots=True)
class KeystoneAeryEffect:
    """Summon Aery's damage and ally-shield packets.

    Aery has no cooldown field.  The fight timeline gates new signals until
    the sourced target linger ends.  Damage and shielding keep separate
    flight times because the wiki gives separate receipts for them.
    """

    keystone_name: str
    breakdown_key: str
    display_name: str
    damage_by_level: tuple[float, ...]
    shield_by_level: tuple[float, ...]
    bonus_ad_ratio: float
    ap_ratio: float
    damage_flight_seconds: float
    shield_flight_seconds: float
    shield_duration_seconds: float
    linger_seconds: float
    damage_type: Callable[[Mapping[str, float]], str]

    def raw_damage(self, inputs: DamageInputs) -> float:
        """Price one offensive signal from sourced level and stat tables."""
        stats = inputs.champion_stats
        return (
            _at_level(self.damage_by_level, inputs.level)
            + self.bonus_ad_ratio * stats.get("bonus_attack_damage", 0.0)
            + self.ap_ratio * stats.get("ability_power", 0.0)
        )

    def raw_shield(self, inputs: DamageInputs) -> float:
        """Price one ally shield from sourced level and stat tables."""
        stats = inputs.champion_stats
        return (
            _at_level(self.shield_by_level, inputs.level)
            + self.bonus_ad_ratio * stats.get("bonus_attack_damage", 0.0)
            + self.ap_ratio * stats.get("ability_power", 0.0)
        )

    def shield_amount(self, level: int, stats: Mapping[str, float]) -> float:
        """Price one ally shield from a participant result context."""
        return self.raw_shield(
            DamageInputs(
                champion_stats=stats,
                level=level,
                is_melee=False,
                target_max_health=0.0,
                target_current_health=0.0,
            )
        )


@dataclass(frozen=True, slots=True)
class KeystoneGuardianEffect:
    """Guardian's guarded-ally threshold shield.

    The participant timeline owns Guard selection, cumulative damage windows,
    and the paired shield application.  This object owns only the sourced
    level tables, ratios, and timing values.
    """

    keystone_name: str
    breakdown_key: str
    display_name: str
    threshold_by_level: tuple[float, ...]
    shield_by_level: tuple[float, ...]
    cooldown_by_level: tuple[float, ...]
    ap_ratio: float
    bonus_health_ratio: float
    trigger_window_seconds: float
    shield_duration_seconds: float

    def threshold_at(self, level: int) -> float:
        """Read the sourced post-mitigation trigger threshold."""
        return _at_level(self.threshold_by_level, level)

    def cooldown_at(self, level: int) -> float:
        """Read the sourced cooldown after a shield trigger."""
        return _at_level(self.cooldown_by_level, level)

    def shield_amount(self, level: int, stats: Mapping[str, float]) -> float:
        """Price both Guardian shields from the holder's stats."""
        return (
            _at_level(self.shield_by_level, level)
            + self.ap_ratio * stats.get("ability_power", 0.0)
            + self.bonus_health_ratio * stats.get("bonus_health", 0.0)
        )


@dataclass(frozen=True, slots=True)
class KeystoneAftershockEffect:
    """Aftershock's immobilize-triggered resistance and shockwave packets."""

    keystone_name: str
    breakdown_key: str
    display_name: str
    resistance_cap_by_level: tuple[float, ...]
    shockwave_damage_by_level: tuple[float, ...]
    cooldown_seconds: float
    flat_armor: float
    flat_magic_resistance: float
    bonus_armor_ratio: float
    bonus_magic_resistance_ratio: float
    bonus_health_ratio: float
    duration_seconds: float
    shockwave_radius: float

    def resistance_bonus(
        self, level: int, stats: Mapping[str, float], resistance_type: str
    ) -> float:
        """Price one capped resistance bonus from trigger-time stats."""
        if resistance_type == "armor":
            base = self.flat_armor
            ratio = self.bonus_armor_ratio
            stat_key = "bonus_armor"
        elif resistance_type == "magic_resistance":
            base = self.flat_magic_resistance
            ratio = self.bonus_magic_resistance_ratio
            stat_key = "bonus_magic_resistance"
        else:
            raise ValueError(
                f"Aftershock has unknown resistance type {resistance_type!r}"
            )
        uncapped = base + ratio * stats.get(stat_key, 0.0)
        return min(uncapped, _at_level(self.resistance_cap_by_level, level))

    def shockwave_raw_damage(self, level: int, stats: Mapping[str, float]) -> float:
        """Price the delayed magic shockwave from sourced level and health."""
        return _at_level(
            self.shockwave_damage_by_level, level
        ) + self.bonus_health_ratio * stats.get("bonus_health", 0.0)


@dataclass(frozen=True, slots=True)
class KeystoneGraspEffect:
    """Grasp's timed combat stacks and empowered basic attack.

    The fight engine owns stack timing and the proc target. The participant
    timeline applies the sourced self-heal and permanent health receipt.
    """

    keystone_name: str
    breakdown_key: str
    display_name: str
    damage_melee_ranged_ratios: tuple[float, float]
    heal_melee_ranged_ratios: tuple[float, float]
    bonus_health_melee_ranged: tuple[float, float]
    stack_cadence_seconds: float
    stack_generation_seconds: float
    max_stacks: int
    ready_window_seconds: float

    @staticmethod
    def _select(values: tuple[float, float], is_melee: bool) -> float:
        """Select the sourced melee or ranged value."""
        return values[0 if is_melee else 1]

    def damage_ratio(self, is_melee: bool) -> float:
        """Return the maximum-health damage ratio for one attack class."""
        return self._select(self.damage_melee_ranged_ratios, is_melee)

    def heal_ratio(self, is_melee: bool) -> float:
        """Return the maximum-health self-heal ratio for one attack class."""
        return self._select(self.heal_melee_ranged_ratios, is_melee)

    def bonus_health(self, is_melee: bool) -> float:
        """Return the permanent health gain for one attack class."""
        return self._select(self.bonus_health_melee_ranged, is_melee)

    def raw_damage(self, stats: Mapping[str, float], is_melee: bool) -> float:
        """Price one empowered attack from maximum health."""
        return self.damage_ratio(is_melee) * stats.get("health", 0.0)

    def heal_amount(self, stats: Mapping[str, float], is_melee: bool) -> float:
        """Price one self-heal from maximum health."""
        return self.heal_ratio(is_melee) * stats.get("health", 0.0)


@dataclass(frozen=True, slots=True)
class KeystoneHailOfBladesEffect:
    """Hail of Blades' temporary attack-speed and true-damage packets.

    The fight engine owns the swing schedule and the limited reset-stack
    window. This object owns the sourced level table, ratios, and timing.
    """

    keystone_name: str
    breakdown_key: str
    display_name: str
    damage_by_level: tuple[float, ...]
    bonus_ad_ratio: float
    ap_ratio: float
    bonus_attack_speed_melee_ranged: tuple[float, float]
    initial_stacks: int
    stack_duration_seconds: float
    reset_stack_limit: int
    cooldown_seconds: float

    @staticmethod
    def _select(values: tuple[float, float], is_melee: bool) -> float:
        """Select the sourced melee or ranged value."""
        return values[0 if is_melee else 1]

    def bonus_attack_speed_percent(self, is_melee: bool) -> float:
        """Return Hail's temporary bonus attack speed percentage."""
        return self._select(self.bonus_attack_speed_melee_ranged, is_melee)

    def raw_damage(self, inputs: DamageInputs) -> float:
        """Price one bonus true-damage attack from level and ratios."""
        stats = inputs.champion_stats
        return (
            _at_level(self.damage_by_level, inputs.level)
            + self.bonus_ad_ratio * stats.get("bonus_attack_damage", 0.0)
            + self.ap_ratio * stats.get("ability_power", 0.0)
        )


@dataclass(frozen=True, slots=True)
class KeystoneLethalTempoEffect:
    """Lethal Tempo's stacked attack speed and max-stack bolt."""

    keystone_name: str
    breakdown_key: str
    display_name: str
    bolt_damage_melee_by_level: tuple[float, ...]
    bolt_damage_ranged_by_level: tuple[float, ...]
    attack_speed_percent_melee_ranged: tuple[float, float]
    bolt_damage_increase_ratio_melee_ranged: tuple[float, float]
    max_stacks: int
    stack_duration_seconds: float
    expiry_step_seconds: float
    damage_type: Callable[[Mapping[str, float]], str]

    @staticmethod
    def _select(values: tuple[float, float], is_melee: bool) -> float:
        """Select the sourced melee or ranged value."""
        return values[0 if is_melee else 1]

    def attack_speed_percent(self, is_melee: bool, stacks: int) -> float:
        """Return the sourced bonus attack speed at one stack count."""
        return self._select(self.attack_speed_percent_melee_ranged, is_melee) * max(
            0, min(int(stacks), self.max_stacks)
        )

    def bolt_raw_damage(
        self, inputs: DamageInputs, is_melee: bool, stacks: int
    ) -> float:
        """Price one max-stack bolt, including its sourced AS increase."""
        table = (
            self.bolt_damage_melee_by_level
            if is_melee
            else self.bolt_damage_ranged_by_level
        )
        base = _at_level(table, inputs.level)
        total_bonus_attack_speed = inputs.champion_stats.get(
            "bonus_attack_speed", 0.0
        ) + self.attack_speed_percent(is_melee, stacks)
        increase = self._select(self.bolt_damage_increase_ratio_melee_ranged, is_melee)
        return base * (1.0 + total_bonus_attack_speed * increase)


@dataclass(frozen=True, slots=True)
class KeystoneGlacialEffect:
    """Glacial Augment's control-triggered zones and ally damage reduction."""

    keystone_name: str
    breakdown_key: str
    display_name: str
    cooldown_seconds: float
    ray_count: int
    zone_radius_units: float
    zone_width_units: float
    zone_base_duration_seconds: float
    zone_duration_cc_ratio: float
    slow_base_ratio: float
    slow_bonus_ad_ratio_per_100: float
    slow_ap_ratio_per_100: float
    slow_heal_shield_ratio_per_10: float
    damage_reduction_ratio: float

    def zone_duration(self, cc_duration: float) -> float:
        """Return the sourced zone lifetime for one control event."""
        return self.zone_base_duration_seconds + self.zone_duration_cc_ratio * max(
            0.0, cc_duration
        )

    def slow_ratio(self, stats: Mapping[str, float]) -> float:
        """Return the sourced slow from the holder's current stats."""
        return (
            self.slow_base_ratio
            + self.slow_bonus_ad_ratio_per_100
            * max(0.0, stats.get("bonus_attack_damage", 0.0))
            / 100.0
            + self.slow_ap_ratio_per_100
            * max(0.0, stats.get("ability_power", 0.0))
            / 100.0
            + self.slow_heal_shield_ratio_per_10
            * max(0.0, stats.get("heal_and_shield_power_percent", 0.0))
            / 10.0
        )


@dataclass(frozen=True, slots=True)
class KeystoneStormraiderEffect:
    """Stormraider's Surge's damage-threshold movement burst."""

    keystone_name: str
    breakdown_key: str
    display_name: str
    cooldown_by_level: tuple[float, ...]
    damage_threshold_ratio: float
    damage_window_seconds: float
    bonus_move_speed_melee_ranged: tuple[float, float]
    slow_resist_ratio: float
    duration_seconds: float

    def cooldown_at(self, level: int) -> float:
        """Read the sourced cooldown at one champion level."""
        return _at_level(self.cooldown_by_level, level)

    def bonus_move_speed_percent(self, is_melee: bool) -> float:
        """Select the sourced melee or ranged movement-speed percentage."""
        return self.bonus_move_speed_melee_ranged[0 if is_melee else 1]


@dataclass(frozen=True, slots=True)
class KeystoneFleetEffect:
    """Fleet Footwork's charged basic-attack heal and speed burst."""

    keystone_name: str
    breakdown_key: str
    display_name: str
    heal_melee_by_level: tuple[float, ...]
    heal_ranged_by_level: tuple[float, ...]
    bonus_ad_ratio_melee_ranged: tuple[float, float]
    ap_ratio_melee_ranged: tuple[float, float]
    bonus_move_speed_melee_ranged: tuple[float, float]
    minion_heal_effectiveness: float
    charge_cap: int
    move_speed_duration_seconds: float

    @staticmethod
    def _select(values: tuple[float, float], is_melee: bool) -> float:
        """Select the sourced melee or ranged value."""
        return values[0 if is_melee else 1]

    def heal_amount(
        self,
        level: int,
        stats: Mapping[str, float],
        is_melee: bool,
        *,
        against_minion: bool = False,
    ) -> float:
        """Price one Energized heal from the holder's current stats."""
        base = _at_level(
            self.heal_melee_by_level if is_melee else self.heal_ranged_by_level,
            level,
        )
        amount = (
            base
            + self._select(self.bonus_ad_ratio_melee_ranged, is_melee)
            * stats.get("bonus_attack_damage", 0.0)
            + self._select(self.ap_ratio_melee_ranged, is_melee)
            * stats.get("ability_power", 0.0)
        )
        if against_minion:
            amount *= self.minion_heal_effectiveness
        return max(0.0, amount)

    def bonus_move_speed_percent(self, is_melee: bool) -> float:
        """Select the sourced Energized movement-speed percentage."""
        return self._select(self.bonus_move_speed_melee_ranged, is_melee)


@dataclass(frozen=True, slots=True)
class KeystoneConquerorEffect:
    """Conqueror's typed stack state and max-stack healing."""

    keystone_name: str
    breakdown_key: str
    display_name: str
    adaptive_force_by_level: tuple[float, ...]
    adaptive_force_max_by_level: tuple[float, ...]
    max_stacks: int
    stacks_per_application: int
    stack_duration_seconds: float
    cast_instance_interval_seconds: float
    heal_melee_ranged_ratios: tuple[float, float]

    def adaptive_force_at(self, level: int, stacks: int) -> float:
        """Return the sourced adaptive-force amount at a stack count."""
        clamped = max(0, min(int(stacks), self.max_stacks))
        return _at_level(self.adaptive_force_by_level, level) * clamped

    def max_adaptive_force_at(self, level: int) -> float:
        """Return the source's explicit maximum-stack force table value."""
        return _at_level(self.adaptive_force_max_by_level, level)

    def bonus_attack_damage_at(self, level: int, stacks: int) -> float:
        """Convert adaptive force to bonus AD for an AD adaptive page."""
        return self.adaptive_force_at(level, stacks) * 0.6

    def ability_power_at(self, level: int, stacks: int) -> float:
        """Convert adaptive force to AP for an AP adaptive page."""
        return self.adaptive_force_at(level, stacks)

    def heal_ratio(self, is_melee: bool) -> float:
        """Select the sourced melee or ranged max-stack healing ratio."""
        return self.heal_melee_ranged_ratios[0 if is_melee else 1]

    def heal_amount(self, post_mitigation_damage: float, is_melee: bool) -> float:
        """Price the max-stack heal from post-mitigation champion damage."""
        return max(0.0, float(post_mitigation_damage)) * self.heal_ratio(is_melee)


# Reviewed provenance for Conqueror's stack rule.  Every numeric field is
# parser-owned from ``data/runes.json`` (League Wiki rune data templates);
# the cache carries no per-rune revision, so the receipt follows the
# cache-backed convention used elsewhere in this codebase.
_CONQUEROR_SOURCE = SourceReceipt(
    label="data/runes.json (League Wiki rune data templates)",
    url="https://wiki.leagueoflegends.com/en-us/Conqueror",
    revision_id=0,
    revision_timestamp="cached data/runes.json",
)


def conqueror_stack_state(
    effect: "KeystoneConquerorEffect", *, starting_stacks: int = 0
) -> TimedStackState:
    """Build the kernel-owned Conqueror stack state.

    The sourced rule: stacks last ``stack_duration_seconds`` (5) and refresh
    on subsequent damage; the cap is ``max_stacks`` (12).  Basic-attack
    packets grant ``stacks_per_application`` (2, the flattened sourced
    value; the wiki's melee/ranged 2/1 on-hit split is not extracted by the
    rune parser and stays a documented approximation).  Ability-cast packets
    grant the same amount but only once per ``cast_instance_interval_seconds``
    (4) per ability — the audit's over-stack fix: our trigger walk emits one
    packet per cast, so the sourced "up to once every 4 seconds per cast
    instance" gate binds as a per-ability cadence on repeated casts.
    """
    rule = StackRule(
        name="Conqueror",
        max_stacks=int(effect.max_stacks),
        gain_per_application=int(effect.stacks_per_application),
        duration_seconds=float(effect.stack_duration_seconds),
        refresh="refresh",
        expiry="all_at_once",
        interval_seconds=float(effect.cast_instance_interval_seconds),
        interval_key="source_key",
        interval_gate_packets=frozenset({"ability_cast"}),
        source=_CONQUEROR_SOURCE,
    )
    return TimedStackState(rule, starting_stacks=starting_stacks)


@dataclass(frozen=True, slots=True)
class KeystoneDeathfireEffect:
    """Deathfire Touch's typed burn packets and duration categories."""

    keystone_name: str
    breakdown_key: str
    display_name: str
    damage_by_level: tuple[float, ...]
    amplified_damage_by_level: tuple[float, ...]
    bonus_ad_ratios_by_state: tuple[float, float]
    ap_ratios_by_state: tuple[float, float]
    tick_interval_seconds: float
    amp_delay_seconds: float
    amp_ratio: float
    duration_by_category: Mapping[str, float]

    def duration_for(self, category: str) -> float:
        """Return one authored duration category or fail closed."""
        try:
            return float(self.duration_by_category[category])
        except KeyError as exc:
            raise KeyError(
                f"RUNE_EFFECTS[{self.keystone_name!r}] is missing burn duration "
                f"category {category!r}"
            ) from exc

    def raw_tick(
        self,
        level: int,
        stats: Mapping[str, float],
        *,
        amplified: bool = False,
    ) -> float:
        """Price one source-backed magic burn tick."""
        state = 1 if amplified else 0
        base = _at_level(
            self.amplified_damage_by_level if amplified else self.damage_by_level,
            level,
        )
        return max(
            0.0,
            base
            + self.bonus_ad_ratios_by_state[state]
            * stats.get("bonus_attack_damage", 0.0)
            + self.ap_ratios_by_state[state] * stats.get("ability_power", 0.0),
        )


@dataclass(frozen=True, slots=True)
class KeystoneDarkHarvestEffect:
    """Dark Harvest's threshold-triggered adaptive damage.

    The engine owns the target-health walk and cooldown.  ``souls`` is the
    count held before the proc; the next Soul becomes available only after
    the sourced reap delay.  The wiki prices that delay on the Soul REAP —
    the damage is immediate on the triggering hit — while
    ``proc_delay_seconds`` stores the sourced delay generically; landing the
    damage at trigger + delay is an engine-side choice (see ``ASSUMPTIONS``).
    """

    keystone_name: str
    breakdown_key: str
    display_name: str
    cooldown_seconds: float
    health_threshold_ratio: float
    base_damage: float
    soul_damage: float
    bonus_ad_ratio: float
    ap_ratio: float
    proc_delay_seconds: float
    takedown_reset_seconds: float
    damage_type: Callable[[Mapping[str, float]], str]

    def raw_damage(self, inputs: DamageInputs, souls: int = 0) -> float:
        """Price one proc from the pre-reap Soul count and champion stats."""
        stats = inputs.champion_stats
        return (
            self.base_damage
            + self.soul_damage * max(0, int(souls))
            + self.bonus_ad_ratio * stats.get("bonus_attack_damage", 0.0)
            + self.ap_ratio * stats.get("ability_power", 0.0)
        )


KeystoneEffect = (
    KeystoneProcEffect
    | KeystoneWindowAmpEffect
    | KeystoneProcAmpEffect
    | KeystoneAbilityProcEffect
    | KeystoneAeryEffect
    | KeystoneGuardianEffect
    | KeystoneAftershockEffect
    | KeystoneGraspEffect
    | KeystoneHailOfBladesEffect
    | KeystoneLethalTempoEffect
    | KeystoneGlacialEffect
    | KeystoneStormraiderEffect
    | KeystoneFleetEffect
    | KeystoneConquerorEffect
    | KeystoneDeathfireEffect
    | KeystoneDarkHarvestEffect
)


class _RequiredRuneValues:
    """Typed, contextual reads from one rune registry record."""

    def __init__(self, rune_name: str, values: Mapping[str, Any]) -> None:
        self.rune_name = rune_name
        self.values = values

    def value(self, key: str) -> Any:
        """Return one required value or raise with rune and key context."""
        if key not in self.values or self.values[key] is None:
            raise KeyError(
                f"RUNE_EFFECTS[{self.rune_name!r}] is missing {key!r} — "
                "wiki parse degraded; check rune_parser and data/runes.json"
            )
        return self.values[key]

    def number(self, key: str) -> float:
        """Return one required numeric value as a float."""
        return float(self.value(key))


def _required_leveling(name: str, effects: _RequiredRuneValues) -> list[float]:
    """Read a rune's per-level damage list, requiring all 20 levels."""
    leveling = effects.value("leveling")
    if (
        not isinstance(leveling, list)
        or not leveling
        or not isinstance(leveling[0], list)
    ):
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] 'leveling' is not a list of level tables "
            "— wiki parse degraded; check rune_parser and data/runes.json"
        )
    try:
        base_by_level = [float(value) for value in leveling[0]]
    except (TypeError, ValueError) as exc:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] 'leveling[0]' is not numeric — "
            "wiki parse degraded; check rune_parser and data/runes.json"
        ) from exc
    if len(base_by_level) < 20:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling covers {len(base_by_level)} "
            "levels; expected 20 — wiki parse degraded"
        )
    return base_by_level


def _required_pair(
    name: str, effects: _RequiredRuneValues, key: str
) -> tuple[float, float]:
    """Read one required melee/ranged pair from the rune registry."""
    values = effects.value(key)
    if not isinstance(values, list) or len(values) != 2:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] {key!r} is not a melee/ranged pair — "
            "wiki parse degraded; check rune_parser and data/runes.json"
        )
    return float(values[0]), float(values[1])


def _required_cooldown_by_level(
    name: str, entry: Mapping[str, Any]
) -> tuple[float, ...]:
    """Read a rune's per-level cooldown list, requiring all 20 levels."""
    cooldown = entry.get("cooldown")
    if not isinstance(cooldown, list) or len(cooldown) < 20:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] cooldown is not a 20-level list — "
            "wiki parse degraded; check rune_parser and data/runes.json"
        )
    return tuple(float(value) for value in cooldown)


def _ratio_adaptive_type(
    bonus_ad_ratio: float, ap_ratio: float
) -> Callable[[Mapping[str, float]], str]:
    """Adaptive damage type from ratio-weighted contributions.

    The larger contribution decides; a tie (or all-zero) defaults magic,
    matching the wiki's variable-damage rule.
    """

    def adaptive_type(stats: Mapping[str, float]) -> str:
        ad_contribution = bonus_ad_ratio * stats.get("bonus_attack_damage", 0.0)
        ap_contribution = ap_ratio * stats.get("ability_power", 0.0)
        return "physical" if ad_contribution > ap_contribution else "magic"

    return adaptive_type


def _compile_electrocute(entry: Mapping[str, Any]) -> KeystoneProcEffect:
    """Compile Electrocute: 3 stacks in 3s strike for leveled adaptive damage."""
    name = "Electrocute"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))
    base_by_level = _required_leveling(name, effects)
    bonus_ad_ratio = effects.number("bonus_ad_ratio")
    ap_ratio = effects.number("ap_ratio")
    top = _RequiredRuneValues(name, entry)

    def raw(inputs: DamageInputs) -> float:
        stats = inputs.champion_stats
        return (
            _at_level(base_by_level, inputs.level)
            + bonus_ad_ratio * stats.get("bonus_attack_damage", 0.0)
            + ap_ratio * stats.get("ability_power", 0.0)
        )

    return KeystoneProcEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        stacks_required=int(effects.number("stacks_required")),
        stack_window_seconds=effects.number("stack_window_seconds"),
        cooldown_seconds=top.number("cooldown"),
        proc_delay_seconds=effects.number("proc_delay_seconds"),
        raw_damage=raw,
        damage_type=_ratio_adaptive_type(bonus_ad_ratio, ap_ratio),
    )


def _compile_first_strike(entry: Mapping[str, Any]) -> KeystoneWindowAmpEffect:
    """Compile First Strike: 7% bonus true damage in a 3s opening window."""
    name = "First Strike"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))
    melee_ratio, ranged_ratio = _required_pair(name, effects, "melee_ranged_ratios")
    return KeystoneWindowAmpEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        window_seconds=effects.number("buff_duration_seconds"),
        bonus_damage_ratio=effects.number("bonus_true_damage_ratio"),
        activation_gold=effects.number("flat_gold"),
        gold_conversion_melee=melee_ratio,
        gold_conversion_ranged=ranged_ratio,
    )


def _compile_press_the_attack(entry: Mapping[str, Any]) -> KeystoneProcAmpEffect:
    """Compile Press the Attack: 3 autos proc leveled damage plus a lasting amp."""
    name = "Press the Attack"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))
    base_by_level = _required_leveling(name, effects)
    top = _RequiredRuneValues(name, entry)

    def raw(inputs: DamageInputs) -> float:
        return _at_level(base_by_level, inputs.level)

    def adaptive_type(stats: Mapping[str, float]) -> str:
        # Pure adaptive damage: the larger of bonus AD and AP decides.
        # A tie follows the champion's adaptive type in game; the engine
        # carries no adaptive type, so it defaults magic like Electrocute.
        bonus_ad = stats.get("bonus_attack_damage", 0.0)
        return "physical" if bonus_ad > stats.get("ability_power", 0.0) else "magic"

    return KeystoneProcAmpEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        stacks_required=int(effects.number("max_stacks")),
        stack_duration_seconds=effects.number("stack_duration_seconds"),
        cooldown_seconds=top.number("cooldown"),
        damage_amp_ratio=effects.number("damage_amp_ratio"),
        raw_damage=raw,
        damage_type=adaptive_type,
    )


# Modeling assumption, not a wiki value: how far the average comet flies
# before landing. The wiki's damage table spans 0-750 units; 375 is a
# mid-range poke distance and sits exactly halfway up the table (+50%).
ARCANE_COMET_ASSUMED_TRAVEL_DISTANCE = 375.0


def _distance_amp_ratio(
    name: str, scaling: Mapping[str, Any], distance: float
) -> float:
    """Interpolate a distance-keyed percent table at one travel distance.

    The table's values are evenly spaced across ``distance_range``;
    distances beyond the span clamp to its ends.
    """
    values = [float(value) for value in scaling["values"]]
    span_start, span_end = (float(value) for value in scaling["distance_range"])
    if len(values) < 2 or span_end <= span_start:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] distance_scaling is degenerate — "
            "wiki parse degraded; check rune_parser and data/runes.json"
        )
    fraction = min(1.0, max(0.0, (distance - span_start) / (span_end - span_start)))
    position = fraction * (len(values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    percent = values[lower] + (values[upper] - values[lower]) * (position - lower)
    return percent / 100.0


def _certify_comet_leveling_order(
    name: str,
    effects: "_RequiredRuneValues",
    base_by_level: list[float],
    scaling: Mapping[str, Any],
) -> None:
    """Certify leveling[0] is the minimum-damage table, not the max-range one.

    The comet is the first rune with two level tables, chosen by sentence
    order — a reworded wiki description leading with the max-range table
    would silently double every proc. The wiki prices maximum-range damage
    at exactly (1 + full amp) × minimum, which also certifies folding one
    multiplier over base and ratios together.
    """
    leveling = effects.value("leveling")
    span_end = float(scaling["distance_range"][1])
    full_amp = _distance_amp_ratio(name, scaling, span_end)
    max_by_level = [float(value) for value in leveling[1]] if len(leveling) > 1 else []
    if len(max_by_level) != len(base_by_level) or any(
        abs(max_value - base_value * (1.0 + full_amp)) > 1e-6
        for base_value, max_value in zip(base_by_level, max_by_level)
    ):
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling tables are not minimum then "
            "maximum-range damage (max = min × (1 + full amp)) — wiki parse "
            "degraded or description reordered; check data/runes.json"
        )


def _compile_arcane_comet(entry: Mapping[str, Any]) -> KeystoneAbilityProcEffect:
    """Compile Arcane Comet: ability casts hurl a leveled adaptive comet.

    The wiki prices the comet as a minimum-damage formula amplified by
    travel distance (up to +100% at 750 units); base and ratios grow
    together, so one multiplier at the assumed distance covers both.
    """
    name = "Arcane Comet"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))
    base_by_level = _required_leveling(name, effects)
    bonus_ad_ratio = effects.number("bonus_ad_ratio")
    ap_ratio = effects.number("ap_ratio")
    scaling = effects.value("distance_scaling")
    amp_ratio = _distance_amp_ratio(name, scaling, ARCANE_COMET_ASSUMED_TRAVEL_DISTANCE)
    _certify_comet_leveling_order(name, effects, base_by_level, scaling)

    def raw(inputs: DamageInputs) -> float:
        stats = inputs.champion_stats
        return (
            _at_level(base_by_level, inputs.level)
            + bonus_ad_ratio * stats.get("bonus_attack_damage", 0.0)
            + ap_ratio * stats.get("ability_power", 0.0)
        ) * (1.0 + amp_ratio)

    return KeystoneAbilityProcEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        cooldown_by_level=_required_cooldown_by_level(name, entry),
        proc_delay_seconds=effects.number("proc_delay_seconds"),
        assumed_travel_distance=ARCANE_COMET_ASSUMED_TRAVEL_DISTANCE,
        distance_amp_ratio=amp_ratio,
        raw_damage=raw,
        damage_type=_ratio_adaptive_type(bonus_ad_ratio, ap_ratio),
    )


def _compile_summon_aery(entry: Mapping[str, Any]) -> KeystoneAeryEffect:
    """Compile Summon Aery's sourced damage and shielding tables."""
    name = "Summon Aery"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))
    leveling = effects.value("leveling")
    if not isinstance(leveling, list) or len(leveling) < 2:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling must contain damage and shield "
            "tables — wiki parse degraded; check rune_parser and data/runes.json"
        )
    damage_by_level = tuple(float(value) for value in leveling[0])
    shield_by_level = tuple(float(value) for value in leveling[1])
    if len(damage_by_level) < 20 or len(shield_by_level) < 20:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling tables must cover 20 levels — "
            "wiki parse degraded; check rune_parser and data/runes.json"
        )
    bonus_ad_ratio = effects.number("bonus_ad_ratio")
    ap_ratio = effects.number("ap_ratio")

    return KeystoneAeryEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        damage_by_level=damage_by_level,
        shield_by_level=shield_by_level,
        bonus_ad_ratio=bonus_ad_ratio,
        ap_ratio=ap_ratio,
        damage_flight_seconds=effects.number("damage_flight_seconds"),
        shield_flight_seconds=effects.number("shield_flight_seconds"),
        shield_duration_seconds=effects.number("shield_duration_seconds"),
        linger_seconds=effects.number("linger_seconds"),
        damage_type=_ratio_adaptive_type(bonus_ad_ratio, ap_ratio),
    )


def _compile_guardian(entry: Mapping[str, Any]) -> KeystoneGuardianEffect:
    """Compile Guardian's threshold, paired shield, and cooldown tables."""
    name = "Guardian"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))
    leveling = effects.value("leveling")
    if not isinstance(leveling, list) or len(leveling) < 2:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling must contain threshold and shield "
            "tables — wiki parse degraded; check rune_parser and data/runes.json"
        )
    threshold_by_level = tuple(float(value) for value in leveling[0])
    shield_by_level = tuple(float(value) for value in leveling[1])
    if len(threshold_by_level) < 20 or len(shield_by_level) < 20:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling tables must cover 20 levels — "
            "wiki parse degraded; check rune_parser and data/runes.json"
        )
    return KeystoneGuardianEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        threshold_by_level=threshold_by_level,
        shield_by_level=shield_by_level,
        cooldown_by_level=_required_cooldown_by_level(name, entry),
        ap_ratio=effects.number("ap_ratio"),
        bonus_health_ratio=effects.number("bonus_health_ratio"),
        trigger_window_seconds=effects.number("trigger_window_seconds"),
        shield_duration_seconds=effects.number("shield_duration_seconds"),
    )


def _compile_aftershock(entry: Mapping[str, Any]) -> KeystoneAftershockEffect:
    """Compile Aftershock's resistance cap and delayed shockwave tables."""
    name = "Aftershock"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))
    leveling = effects.value("leveling")
    if not isinstance(leveling, list) or len(leveling) < 2:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling must contain resistance cap and "
            "shockwave tables — wiki parse degraded; check rune_parser and "
            "data/runes.json"
        )
    cap_by_level = tuple(float(value) for value in leveling[0])
    shockwave_by_level = tuple(float(value) for value in leveling[1])
    if len(cap_by_level) < 20 or len(shockwave_by_level) < 20:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling tables must cover 20 levels — "
            "wiki parse degraded; check rune_parser and data/runes.json"
        )
    return KeystoneAftershockEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        resistance_cap_by_level=cap_by_level,
        shockwave_damage_by_level=shockwave_by_level,
        cooldown_seconds=_RequiredRuneValues(name, entry).number("cooldown"),
        flat_armor=effects.number("flat_armor"),
        flat_magic_resistance=effects.number("flat_magic_resistance"),
        bonus_armor_ratio=effects.number("bonus_armor_ratio"),
        bonus_magic_resistance_ratio=effects.number("bonus_magic_resistance_ratio"),
        bonus_health_ratio=effects.number("bonus_health_ratio"),
        duration_seconds=effects.number("resistance_duration_seconds"),
        shockwave_radius=effects.number("shockwave_radius"),
    )


def _compile_grasp(entry: Mapping[str, Any]) -> KeystoneGraspEffect:
    """Compile Grasp's timed stacks and maximum-health attack rider."""
    name = "Grasp of the Undying"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))
    return KeystoneGraspEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        damage_melee_ranged_ratios=_required_pair(
            name, effects, "grasp_damage_melee_ranged_ratios"
        ),
        heal_melee_ranged_ratios=_required_pair(
            name, effects, "grasp_heal_melee_ranged_ratios"
        ),
        bonus_health_melee_ranged=_required_pair(
            name, effects, "grasp_bonus_health_melee_ranged"
        ),
        stack_cadence_seconds=effects.number("combat_stack_cadence_seconds"),
        stack_generation_seconds=effects.number("combat_stack_generation_seconds"),
        max_stacks=int(effects.number("max_stacks")),
        ready_window_seconds=effects.number("ready_window_seconds"),
    )


def _compile_hail_of_blades(entry: Mapping[str, Any]) -> KeystoneHailOfBladesEffect:
    """Compile Hail of Blades' sourced temporary swing window."""
    name = "Hail of Blades"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))
    return KeystoneHailOfBladesEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        damage_by_level=tuple(_required_leveling(name, effects)),
        bonus_ad_ratio=effects.number("bonus_ad_ratio"),
        ap_ratio=effects.number("ap_ratio"),
        bonus_attack_speed_melee_ranged=_required_pair(
            name, effects, "hail_bonus_attack_speed_melee_ranged"
        ),
        initial_stacks=int(effects.number("hail_initial_stacks")),
        stack_duration_seconds=effects.number("hail_stack_duration_seconds"),
        reset_stack_limit=int(effects.number("hail_reset_stack_limit")),
        cooldown_seconds=_RequiredRuneValues(name, entry).number("cooldown"),
    )


def _compile_lethal_tempo(entry: Mapping[str, Any]) -> KeystoneLethalTempoEffect:
    """Compile Lethal Tempo's stacked attack schedule and bolt tables."""
    name = "Lethal Tempo"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))

    def level_table(key: str) -> tuple[float, ...]:
        values = effects.value(key)
        if not isinstance(values, list) or len(values) < 20:
            raise KeyError(
                f"RUNE_EFFECTS[{name!r}] {key!r} must cover 20 levels — "
                "wiki parse degraded; check rune_parser and data/runes.json"
            )
        return tuple(float(value) for value in values)

    def adaptive_type(stats: Mapping[str, float]) -> str:
        return (
            "physical"
            if stats.get("bonus_attack_damage", 0.0) > stats.get("ability_power", 0.0)
            else "magic"
        )

    return KeystoneLethalTempoEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        bolt_damage_melee_by_level=level_table(
            "lethal_tempo_bolt_damage_melee_by_level"
        ),
        bolt_damage_ranged_by_level=level_table(
            "lethal_tempo_bolt_damage_ranged_by_level"
        ),
        attack_speed_percent_melee_ranged=_required_pair(
            name, effects, "lethal_tempo_attack_speed_percent_melee_ranged"
        ),
        bolt_damage_increase_ratio_melee_ranged=_required_pair(
            name, effects, "lethal_tempo_bolt_damage_increase_ratio_melee_ranged"
        ),
        max_stacks=int(effects.number("max_stacks")),
        stack_duration_seconds=effects.number("lethal_tempo_stack_duration_seconds"),
        expiry_step_seconds=effects.number("lethal_tempo_expiry_step_seconds"),
        damage_type=adaptive_type,
    )


def _compile_glacial(entry: Mapping[str, Any]) -> KeystoneGlacialEffect:
    """Compile Glacial Augment's sourced zone and reduction values."""
    name = "Glacial Augment"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))
    return KeystoneGlacialEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        cooldown_seconds=_RequiredRuneValues(name, entry).number("cooldown"),
        ray_count=int(effects.number("glacial_ray_count")),
        zone_radius_units=effects.number("glacial_zone_radius_units"),
        zone_width_units=effects.number("glacial_zone_width_units"),
        zone_base_duration_seconds=effects.number("glacial_zone_base_duration_seconds"),
        zone_duration_cc_ratio=effects.number("glacial_zone_duration_cc_ratio"),
        slow_base_ratio=effects.number("glacial_slow_base_ratio"),
        slow_bonus_ad_ratio_per_100=effects.number(
            "glacial_slow_bonus_ad_ratio_per_100"
        ),
        slow_ap_ratio_per_100=effects.number("glacial_slow_ap_ratio_per_100"),
        slow_heal_shield_ratio_per_10=effects.number(
            "glacial_slow_heal_shield_ratio_per_10"
        ),
        damage_reduction_ratio=effects.number("glacial_damage_reduction_ratio"),
    )


def _compile_stormraider(entry: Mapping[str, Any]) -> KeystoneStormraiderEffect:
    """Compile Stormraider's sourced threshold and movement burst."""
    name = "Stormraider's Surge"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))
    return KeystoneStormraiderEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        cooldown_by_level=_required_cooldown_by_level(name, entry),
        damage_threshold_ratio=effects.number("stormraider_damage_threshold_ratio"),
        damage_window_seconds=effects.number("stormraider_damage_window_seconds"),
        bonus_move_speed_melee_ranged=_required_pair(
            name, effects, "stormraider_bonus_move_speed_melee_ranged"
        ),
        slow_resist_ratio=effects.number("stormraider_slow_resist_ratio"),
        duration_seconds=effects.number("stormraider_duration_seconds"),
    )


def _compile_fleet(entry: Mapping[str, Any]) -> KeystoneFleetEffect:
    """Compile Fleet Footwork's sourced heal and Energized window."""
    name = "Fleet Footwork"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))

    def level_table(key: str) -> tuple[float, ...]:
        values = effects.value(key)
        if not isinstance(values, list) or len(values) < 20:
            raise KeyError(
                f"RUNE_EFFECTS[{name!r}] {key!r} must cover 20 levels — "
                "wiki parse degraded; check rune_parser and data/runes.json"
            )
        return tuple(float(value) for value in values)

    return KeystoneFleetEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        heal_melee_by_level=level_table("fleet_heal_melee_by_level"),
        heal_ranged_by_level=level_table("fleet_heal_ranged_by_level"),
        bonus_ad_ratio_melee_ranged=_required_pair(
            name, effects, "fleet_bonus_ad_ratio_melee_ranged"
        ),
        ap_ratio_melee_ranged=_required_pair(
            name, effects, "fleet_ap_ratio_melee_ranged"
        ),
        bonus_move_speed_melee_ranged=_required_pair(
            name, effects, "fleet_bonus_move_speed_melee_ranged"
        ),
        minion_heal_effectiveness=effects.number("fleet_minion_heal_effectiveness"),
        charge_cap=int(effects.number("fleet_charge_cap")),
        move_speed_duration_seconds=effects.number("fleet_move_speed_duration_seconds"),
    )


def _compile_conqueror(entry: Mapping[str, Any]) -> KeystoneConquerorEffect:
    """Compile Conqueror's adaptive-force stack and healing receipts."""
    name = "Conqueror"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))

    def level_table(key: str) -> tuple[float, ...]:
        values = effects.value(key)
        if not isinstance(values, list) or len(values) < 20:
            raise KeyError(
                f"RUNE_EFFECTS[{name!r}] {key!r} must cover 20 levels — "
                "wiki parse degraded; check rune_parser and data/runes.json"
            )
        return tuple(float(value) for value in values)

    return KeystoneConquerorEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        adaptive_force_by_level=level_table("conqueror_adaptive_force_by_level"),
        adaptive_force_max_by_level=level_table(
            "conqueror_adaptive_force_max_by_level"
        ),
        max_stacks=int(effects.number("max_stacks")),
        stacks_per_application=int(effects.number("conqueror_stacks_per_application")),
        stack_duration_seconds=effects.number("conqueror_stack_duration_seconds"),
        cast_instance_interval_seconds=effects.number(
            "conqueror_cast_instance_interval_seconds"
        ),
        heal_melee_ranged_ratios=_required_pair(
            name, effects, "conqueror_heal_melee_ranged_ratios"
        ),
    )


def _compile_deathfire(entry: Mapping[str, Any]) -> KeystoneDeathfireEffect:
    """Compile Deathfire Touch's typed burn tables and durations."""
    name = "Deathfire Touch"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))

    leveling = effects.value("leveling")
    if not isinstance(leveling, list) or len(leveling) < 2:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] 'leveling' must contain base and amplified "
            "20-level burn tables — wiki parse degraded; check rune_parser and "
            "data/runes.json"
        )
    tables: list[tuple[float, ...]] = []
    for index, values in enumerate(leveling[:2]):
        if not isinstance(values, list) or len(values) < 20:
            raise KeyError(
                f"RUNE_EFFECTS[{name!r}] 'leveling[{index}]' must cover 20 levels "
                "— wiki parse degraded; check rune_parser and data/runes.json"
            )
        tables.append(tuple(float(value) for value in values))

    duration_values = effects.value("deathfire_duration_seconds")
    if not isinstance(duration_values, Mapping):
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] is missing typed burn duration categories "
            "— wiki parse degraded; check rune_parser and data/runes.json"
        )
    required_categories = (
        "spell_damage",
        "area_damage",
        "persistent_damage",
        "persistent_area_damage",
        "pet_damage",
    )
    durations: dict[str, float] = {}
    for category in required_categories:
        if category not in duration_values:
            raise KeyError(
                f"RUNE_EFFECTS[{name!r}] is missing burn duration {category!r} "
                "— wiki parse degraded; check rune_parser and data/runes.json"
            )
        durations[category] = float(duration_values[category])

    return KeystoneDeathfireEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        damage_by_level=tables[0],
        amplified_damage_by_level=tables[1],
        bonus_ad_ratios_by_state=_required_pair(
            name, effects, "deathfire_bonus_ad_ratios_by_state"
        ),
        ap_ratios_by_state=_required_pair(
            name, effects, "deathfire_ap_ratios_by_state"
        ),
        tick_interval_seconds=effects.number("deathfire_tick_interval_seconds"),
        amp_delay_seconds=effects.number("deathfire_amp_delay_seconds"),
        amp_ratio=effects.number("deathfire_amp_ratio"),
        duration_by_category=durations,
    )


def _compile_dark_harvest(entry: Mapping[str, Any]) -> KeystoneDarkHarvestEffect:
    """Compile Dark Harvest's sourced threshold and Soul damage formula."""
    name = "Dark Harvest"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))
    top = _RequiredRuneValues(name, entry)
    bonus_ad_ratio = effects.number("bonus_ad_ratio")
    ap_ratio = effects.number("ap_ratio")
    return KeystoneDarkHarvestEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        cooldown_seconds=top.number("cooldown"),
        health_threshold_ratio=effects.number("health_threshold_ratio"),
        base_damage=effects.number("base_damage"),
        soul_damage=effects.number("soul_damage"),
        bonus_ad_ratio=bonus_ad_ratio,
        ap_ratio=ap_ratio,
        proc_delay_seconds=effects.number("proc_delay_seconds"),
        takedown_reset_seconds=effects.number("takedown_reset_seconds"),
        damage_type=_ratio_adaptive_type(bonus_ad_ratio, ap_ratio),
    )


# The compiled keystone roster. Every name in ``data/runes.json`` not listed
# here fails closed in :func:`resolve_keystone` with a named reason — see
# ``ASSUMPTIONS`` for why Unsealed Spellbook is intentionally absent.
_KEYSTONE_COMPILERS: dict[str, Callable[[Mapping[str, Any]], KeystoneEffect]] = {
    "Electrocute": _compile_electrocute,
    "First Strike": _compile_first_strike,
    "Press the Attack": _compile_press_the_attack,
    "Arcane Comet": _compile_arcane_comet,
    "Summon Aery": _compile_summon_aery,
    "Guardian": _compile_guardian,
    "Aftershock": _compile_aftershock,
    "Grasp of the Undying": _compile_grasp,
    "Hail of Blades": _compile_hail_of_blades,
    "Lethal Tempo": _compile_lethal_tempo,
    "Glacial Augment": _compile_glacial,
    "Stormraider's Surge": _compile_stormraider,
    "Fleet Footwork": _compile_fleet,
    "Conqueror": _compile_conqueror,
    "Deathfire Touch": _compile_deathfire,
    "Dark Harvest": _compile_dark_harvest,
}


def resolve_keystone(name: str) -> KeystoneEffect | None:
    """Compile the selected keystone, failing closed on anything unmodeled."""
    if not name:
        return None
    entry = RUNE_EFFECTS.get(name)
    if entry is None:
        raise ValueError(f"Unknown keystone {name!r}")
    compiler = _KEYSTONE_COMPILERS.get(name)
    if compiler is None:
        if name == "Unsealed Spellbook":
            raise ValueError(
                f"Keystone {name!r} is not modeled yet: it is a summoner-spell "
                "selection state (equipped and swapped spells, each with its "
                "own effect), and the cached wiki template carries no numeric "
                "values for it. Choose an implemented keystone or none."
            )
        raise ValueError(
            f"Keystone {name!r} is not modeled yet; its numbers would be "
            "estimates. Choose an implemented keystone or none."
        )
    return compiler(entry)


def validate_keystone_request(value: Any) -> str:
    """Parse the request's keystone field, rejecting unmodeled selections."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("keystone must be a string")
    name = value.strip()
    resolve_keystone(name)
    return name


def keystone_input_options_meta() -> dict[str, dict[str, Any]]:
    """Return typed state controls for keystones with explicit inputs."""
    options: dict[str, dict[str, Any]] = {}
    fleet = resolve_keystone("Fleet Footwork")
    if isinstance(fleet, KeystoneFleetEffect):
        options["Fleet Footwork"] = {
            "options": {
                "starting_charges": {
                    "type": "int",
                    "default": 0,
                    "min": 0,
                    "max": fleet.charge_cap,
                    "label": "Starting Fleet charges",
                    "description": (
                        "Charges held before the fight window. Use the cap "
                        "when the first attack starts Energized."
                    ),
                }
            }
        }
    conqueror = resolve_keystone("Conqueror")
    if isinstance(conqueror, KeystoneConquerorEffect):
        options["Conqueror"] = {
            "options": {
                "starting_stacks": {
                    "type": "int",
                    "default": 0,
                    "min": 0,
                    "max": conqueror.max_stacks,
                    "label": "Starting Conqueror stacks",
                    "description": (
                        "Stacks held before the fight window. They expire "
                        f"after {conqueror.stack_duration_seconds:g}s without damage."
                    ),
                }
            }
        }
    return options


def validate_keystone_options(value: Any, keystone_name: str) -> dict[str, int | float]:
    """Validate the selected keystone's explicit state inputs."""
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise ValueError("keystone_options must be an object")
    schemas = keystone_input_options_meta().get(keystone_name, {}).get("options", {})
    unknown_options = set(value) - set(schemas)
    if unknown_options:
        raise ValueError(
            f"Unknown option for {keystone_name or 'keystone'}: "
            f"{sorted(unknown_options)[0]}"
        )
    parsed: dict[str, int | float] = {}
    for option_name, option in schemas.items():
        supplied = value.get(option_name, option["default"])
        if option["type"] == "int" and (
            isinstance(supplied, bool) or not isinstance(supplied, int)
        ):
            raise ValueError(f"keystone_options.{option_name} must be an integer")
        if not option["min"] <= supplied <= option["max"]:
            raise ValueError(
                f"keystone_options.{option_name} must be between "
                f"{option['min']} and {option['max']}"
            )
        parsed[option_name] = supplied
    return parsed


def keystone_catalog() -> list[dict[str, Any]]:
    """Serve the full keystone roster with per-keystone model coverage."""
    return [
        {
            "name": entry.get("name", name),
            "path": entry.get("path", ""),
            "icon": entry.get("icon", ""),
            "cooldown": entry.get("cooldown"),
            "implemented": name in _KEYSTONE_COMPILERS,
        }
        for name, entry in RUNE_EFFECTS.items()
    ]
