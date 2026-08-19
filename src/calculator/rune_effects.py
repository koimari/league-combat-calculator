"""Keystone rune values and effect formulas.

Mirrors ``item_effects`` ownership rules for runes: every numeric rune value
comes from ``data/runes.json`` (parsed from the League Wiki's rune data
templates) through typed accessors that raise, naming the rune and key, when
the parse degraded. No literal fallbacks.

Only keystones with a compile function in ``_KEYSTONE_COMPILERS`` are
modeled; selecting any other keystone fails closed with a clear error. All
seventeen cached keystones compile today, so :func:`keystone_catalog` greys
out nothing — but a rune the next patch adds arrives uncompiled and is
refused until someone declares it.

A compiled keystone is not the same claim as a keystone that deals damage.
Nine price damage on a declared trigger stream; three have no combat number
in any source and five have halves this engine holds no channel for (a
keystone stat, a heal, a shield, a crowd-control trigger). Those eight
compile to a :class:`KeystoneNoDamageEffect` carrying the disposition and
the reason, which the engine publishes — never a silent zero.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping

from .ability_spec import Disposition, ZeroPolicy
from .data_fetcher import fetch_rune_data
from .item_effects import DamageInputs


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


def rune_effect_value(rune_name: str, key: str) -> float:
    """Return one required numeric rune value, failing loudly.

    The public read behind ``value_ref.ValueRef(registry="RUNE_EFFECTS", …)``:
    keystones are runtime damage producers, so CLAUDE.md rule 5's no-literals
    discipline reaches them, and a declaration referencing a rune number needs
    the same fail-loud accessor items already have.  It reuses
    ``_RequiredRuneValues`` rather than re-reading the registry, so "read a
    rune number" keeps one implementation.

    A rune record has two levels — the entry's own fields (``cooldown``) and
    the parser's ``effects`` block — and a reference names a number, not a
    level, so both are searched.  A key present in **both** raises rather
    than picking one: two numbers under one name is a parse defect, and
    silently preferring a level is how a declaration starts citing the wrong
    one.
    """
    entry = RUNE_EFFECTS.get(rune_name)
    if not isinstance(entry, Mapping):
        raise KeyError(f"RUNE_EFFECTS[{rune_name!r}] is missing")
    effects = entry.get("effects")
    effects = effects if isinstance(effects, Mapping) else {}
    top_level = entry.get(key) is not None
    if top_level and effects.get(key) is not None:
        raise KeyError(
            f"RUNE_EFFECTS[{rune_name!r}] holds {key!r} at both levels; two "
            "numbers under one name is a parse defect, not a preference"
        )
    if top_level:
        return _RequiredRuneValues(rune_name, entry).number(key)
    return _RequiredRuneValues(rune_name, effects).number(key)


class KeystoneTrigger(Enum):
    """Which of the fight's event streams a proc-class keystone watches.

    The engine owns the timeline; a keystone owns *which* of its events it
    counts. Naming the stream here keeps that a declared fact instead of a
    walker per keystone.
    """

    #: Damaging ability casts and simulated auto swings, one counter.
    DAMAGE_INSTANCES = "damage_instances"
    #: Simulated auto swings alone — abilities never stack these.
    BASIC_ATTACKS = "basic_attacks"
    #: Accepted damaging ability casts alone — autos never trigger these.
    DAMAGING_CASTS = "damaging_casts"


@dataclass(frozen=True, slots=True)
class KeystoneProcEffect:
    """A stack-triggered keystone proc with a cooldown (Electrocute-class).

    ``raw_damage`` prices one proc; ``damage_type`` resolves the adaptive
    physical/magic choice from the champion's stats. Stack accumulation and
    cooldown gating live in the fight engine, which owns the timeline.

    ``trigger`` names the event stream the stacks come from,
    ``stack_window_seconds`` is ``None`` for a keystone whose stacks the
    cache gives no expiry for, and ``consumes_stacks`` is false where the
    rune keeps its stacks and empowers every later trigger (Lethal Tempo)
    rather than spending them (Electrocute). ``disclosures`` are the
    keystone's own receipts — assumed cadences and withheld halves — which
    the engine publishes verbatim; the words belong with the keystone.
    """

    keystone_name: str
    breakdown_key: str
    display_name: str
    stacks_required: int
    stack_window_seconds: float | None
    cooldown_seconds: float
    proc_delay_seconds: float
    raw_damage: Callable[[DamageInputs], float]
    damage_type: Callable[[Mapping[str, float]], str]
    trigger: KeystoneTrigger = KeystoneTrigger.DAMAGE_INSTANCES
    consumes_stacks: bool = True
    disclosures: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class KeystoneNoDamageEffect:
    """A compiled keystone that books no damage, and says why.

    Two dispositions reach here, and the difference is the receipt.
    ``STRUCTURAL_ZERO`` is a keystone with no combat damage in any source —
    zero is the answer. ``WITHHELD`` is a real effect this engine has no
    channel for (a keystone stat, a heal, a shield, a crowd-control
    trigger): the number exists and is refused, never estimated.

    Modelled on ``item_behavior_catalog``'s ``ZeroPolicy`` declarations so a
    keystone that contributes nothing is *selectable and receipted* rather
    than a refusal at the API boundary.
    """

    keystone_name: str
    zero_policy: ZeroPolicy
    disclosures: tuple[str, ...] = ()

    @property
    def receipts(self) -> tuple[str, ...]:
        """The fight notes this keystone publishes, verdict first."""
        verdict = (
            "deals no damage in any fight"
            if self.zero_policy.disposition is Disposition.STRUCTURAL_ZERO
            else "is not priced"
        )
        return (
            f"{self.keystone_name} {verdict}: {self.zero_policy.reason}.",
        ) + self.disclosures


@dataclass(frozen=True, slots=True)
class KeystoneWindowAmpEffect:
    """A combat-opening damage-window keystone (First Strike-class).

    Post-mitigation damage dealt inside the opening window gains a sourced
    ratio as bonus true damage; activation grants flat gold plus a
    melee/ranged share of the bonus damage as gold. A continuous fight
    activates the buff exactly once, so the rune's out-of-combat cooldown
    never gates anything the engine models.

    **The window and the ratio are not here.** They are the amp chain's
    ``OPENING_WINDOW`` slot, declared as a ``BehaviorRule`` over
    ``RUNE_EFFECTS`` references, and one number with two homes is the drift
    this campaign exists to remove. What is left is the gold accounting and
    the receipt strings, which no amp declaration models: gold is not damage
    and never joins the total.
    """

    keystone_name: str
    breakdown_key: str
    display_name: str
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
    amplifier of all non-true damage. The buff ends only out of combat, so a
    continuous fight keeps it from first proc to the end. Stack walking lives
    in the fight engine, which owns the timeline.

    **The amplifier is not here.** Its ratio, the events it prices and the
    boundary that excludes the swing that armed it are the amp chain's
    ``LASTING_PROC_AMP`` slot, declared as a ``BehaviorRule`` over
    ``RUNE_EFFECTS`` references. What is left is the proc itself.
    """

    keystone_name: str
    breakdown_key: str
    display_name: str
    stacks_required: int
    stack_duration_seconds: float
    cooldown_seconds: float
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


KeystoneEffect = (
    KeystoneProcEffect
    | KeystoneWindowAmpEffect
    | KeystoneProcAmpEffect
    | KeystoneAbilityProcEffect
    | KeystoneNoDamageEffect
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


def _required_leveling(
    name: str,
    effects: _RequiredRuneValues,
    key: str = "leveling",
    index: int = 0,
) -> list[float]:
    """Read one of a rune's per-level tables, requiring all 20 levels.

    ``key`` and ``index`` because a rune record states several tables under
    several names — a melee and a ranged one, a base and an escalated one —
    and every one of them is read through this same fail-loud door.
    """
    tables = effects.value(key)
    if index >= len(tables):
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] {key} holds {len(tables)} tables and "
            f"table {index} was required — wiki parse degraded"
        )
    by_level = [float(value) for value in tables[index]]
    if len(by_level) < 20:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] {key} covers {len(by_level)} "
            "levels; expected 20 — wiki parse degraded"
        )
    return by_level


def _required_pair(
    name: str, effects: _RequiredRuneValues, key: str
) -> tuple[float, float]:
    """Read a rune's melee/ranged pair, in that order."""
    values = [float(value) for value in effects.value(key)]
    if len(values) != 2:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] {key} holds {len(values)} values and is "
            "not a melee/ranged pair — wiki parse degraded"
        )
    return values[0], values[1]


def _certify_smaller_table_first(
    name: str, effects: _RequiredRuneValues, key: str, second: str
) -> None:
    """Certify the first of two per-level tables is the smaller quantity.

    A rune stating two tables is read by sentence order, so a reworded wiki
    page would silently swap them — the failure Arcane Comet's own
    certification exists for. Where the second table is the larger quantity
    at every level, the order is checkable without pinning a ratio a patch
    may legitimately move; ``second`` names what that larger table is, so
    the failure says which two quantities changed places.
    """
    other = _required_leveling(name, effects, key, 1)
    first = _required_leveling(name, effects, key, 0)
    if any(later <= earlier for earlier, later in zip(first, other)):
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] {key} does not lead with the smaller "
            f"table, so table 0 is no longer the damage and table 1 the "
            f"{second} — wiki parse degraded or description reordered"
        )


def _certify_uniform_escalation(
    name: str, effects: _RequiredRuneValues, key: str
) -> None:
    """Certify the second table is the first scaled by one factor above 1.

    The escalated table is the base table times a single stated increase, so
    a uniform ratio above 1 across every level certifies which one is the
    base — again without pinning the increase itself.
    """
    base = _required_leveling(name, effects, key, 0)
    escalated = _required_leveling(name, effects, key, 1)
    ratios = [later / earlier for earlier, later in zip(base, escalated) if earlier]
    if len(ratios) != len(base) or any(
        ratio <= 1.0 or abs(ratio - ratios[0]) > 1e-9 for ratio in ratios
    ):
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] {key} is not a base table and one "
            "uniformly escalated copy of it — wiki parse degraded or "
            "description reordered"
        )


def _pure_adaptive_type(stats: Mapping[str, float]) -> str:
    """Adaptive damage type for a proc with no ratios of its own.

    The larger of bonus AD and AP decides. A tie follows the champion's
    adaptive type in game; the engine carries no adaptive type, so it
    defaults magic like Electrocute.
    """
    bonus_ad = stats.get("bonus_attack_damage", 0.0)
    return "physical" if bonus_ad > stats.get("ability_power", 0.0) else "magic"


def _stated_type(damage_type: str) -> Callable[[Mapping[str, float]], str]:
    """A damage type the rune states outright, not an adaptive choice."""

    def stated(stats: Mapping[str, float]) -> str:
        del stats
        return damage_type

    return stated


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
    melee_ratio, ranged_ratio = (
        float(value) for value in effects.value("gold_conversion_ratios")
    )
    return KeystoneWindowAmpEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
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

    return KeystoneProcAmpEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        stacks_required=int(effects.number("max_stacks")),
        stack_duration_seconds=effects.number("stack_duration_seconds"),
        cooldown_seconds=top.number("cooldown"),
        raw_damage=raw,
        damage_type=_pure_adaptive_type,
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


# Modeling assumption, not a wiki value: how long Aery stays away once sent.
# The cache carries her 0.45s outward pounce and nothing else of the cycle —
# the wiki states the ~2s linger and the return flight (a level-keyed speed
# that ramps with distance and can be picked up early) only in prose, so none
# of it parsed. 3s covers a linger plus a short return at trade range; the
# round trip is that plus the cached pounce, and it is what gates re-procs.
SUMMON_AERY_ASSUMED_RETURN_SECONDS = 3.0


def _compile_summon_aery(entry: Mapping[str, Any]) -> KeystoneProcEffect:
    """Compile Summon Aery: autos and abilities send her out and she pounces.

    Aery is gated by her flight, not a cooldown, so the engine's re-proc
    gate is the assumed round trip — stated the way Arcane Comet's assumed
    travel distance is. Her ally shield is the same rune's other half and
    the pair engine has no ally to cast it on; it is withheld, not zeroed.
    """
    name = "Summon Aery"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))
    base_by_level = _required_leveling(name, effects)
    _certify_smaller_table_first(name, effects, "leveling", "ally shield")
    bonus_ad_ratio = effects.number("bonus_ad_ratio")
    ap_ratio = effects.number("ap_ratio")
    pounce_seconds = effects.number("proc_delay_seconds")
    round_trip = pounce_seconds + SUMMON_AERY_ASSUMED_RETURN_SECONDS

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
        stacks_required=1,
        stack_window_seconds=None,
        cooldown_seconds=round_trip,
        proc_delay_seconds=pounce_seconds,
        raw_damage=raw,
        damage_type=_ratio_adaptive_type(bonus_ad_ratio, ap_ratio),
        trigger=KeystoneTrigger.DAMAGE_INSTANCES,
        disclosures=(
            f"{name} is gated by her flight, not a cooldown: she is assumed "
            f"to be back {round_trip:g}s after being sent ({pounce_seconds:g}s "
            "pounce from the cache plus an assumed "
            f"{SUMMON_AERY_ASSUMED_RETURN_SECONDS:g}s linger and return).",
            f"{name}'s ally shield is withheld: the pair engine prices one "
            "attacker against one target and has no ally to shield.",
        ),
    )


def _compile_hail_of_blades(entry: Mapping[str, Any]) -> KeystoneProcEffect:
    """Compile Hail of Blades: empowered swings deal leveled bonus true damage.

    The attack-speed half is the rune's larger contribution and no keystone
    reaches ``stats.py``, so it is withheld rather than guessed. The cache
    carries the 10s cooldown but not how many stacks one activation grants,
    so exactly one swing per activation is priced — a floor.
    """
    name = "Hail of Blades"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))
    base_by_level = _required_leveling(name, effects)
    bonus_ad_ratio = effects.number("bonus_ad_ratio")
    ap_ratio = effects.number("ap_ratio")
    top = _RequiredRuneValues(name, entry)
    melee_as, ranged_as = _required_pair(name, effects, "attack_speed_ratios")

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
        stacks_required=1,
        stack_window_seconds=None,
        cooldown_seconds=top.number("cooldown"),
        # The damage lands on-hit with the swing; the rune states no delay.
        proc_delay_seconds=0.0,
        raw_damage=raw,
        damage_type=_stated_type("true"),
        trigger=KeystoneTrigger.BASIC_ATTACKS,
        disclosures=(
            f"{name}'s bonus attack speed "
            f"({melee_as * 100:g}% melee / {ranged_as * 100:g}% ranged, and the "
            "attack-speed cap it lifts) is withheld: no keystone reaches the "
            "stat block, so the fight's swing rate is the build's alone.",
            f"{name} prices one empowered swing per activation: the cache "
            "carries its cooldown but not how many stacks an activation "
            "grants, so the swing count is a floor.",
        ),
    )


def _compile_grasp_of_the_undying(entry: Mapping[str, Any]) -> KeystoneProcEffect:
    """Compile Grasp of the Undying: one empowered attack for maximum health.

    The magic hit is a share of the holder's own maximum health, which the
    cache states for melee and ranged. What it does not state is the stack
    cadence that arms and re-arms it, so exactly one proc is priced.
    """
    name = "Grasp of the Undying"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))
    melee_ratio, ranged_ratio = _required_pair(
        name, effects, "max_health_damage_ratios"
    )
    melee_heal, ranged_heal = _required_pair(name, effects, "max_health_heal_ratios")
    melee_health, ranged_health = _required_pair(
        name, effects, "permanent_bonus_health"
    )

    def raw(inputs: DamageInputs) -> float:
        ratio = melee_ratio if inputs.is_melee else ranged_ratio
        return ratio * inputs.champion_stats.get("health", 0.0)

    return KeystoneProcEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        stacks_required=1,
        stack_window_seconds=None,
        # No re-arm: the cadence that would time a second proc is not in the
        # cache, so the engine prices the one proc it can and says so.
        cooldown_seconds=float("inf"),
        proc_delay_seconds=0.0,
        raw_damage=raw,
        damage_type=_stated_type("magic"),
        trigger=KeystoneTrigger.BASIC_ATTACKS,
        disclosures=(
            f"{name} prices exactly one empowered attack, at the fight's "
            "first swing: the cache carries its damage share but not the "
            "stack cadence that arms and re-arms it, so re-procs are "
            "withheld and the count is a floor of one.",
            f"{name}'s heal ({melee_heal * 100:g}% / {ranged_heal * 100:g}% "
            f"maximum health) and permanent bonus health ({melee_health:g} / "
            f"{ranged_health:g}) are withheld: the engine has no keystone "
            "channel for either.",
        ),
    )


def _compile_lethal_tempo(entry: Mapping[str, Any]) -> KeystoneProcEffect:
    """Compile Lethal Tempo: swings past maximum stacks fire an adaptive bolt.

    The attack-speed half — the rune's real contribution — is withheld: no
    keystone reaches ``stats.py``. The bolt is priced from the cache, its
    per-bonus-attack-speed increase reading the build's own bonus attack
    speed, which understates it by exactly the withheld half.
    """
    name = "Lethal Tempo"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))
    melee_by_level = _required_leveling(name, effects, "melee_ranged_leveling", 0)
    ranged_by_level = _required_leveling(name, effects, "melee_ranged_leveling", 1)
    melee_per_as, ranged_per_as = _required_pair(
        name, effects, "damage_per_bonus_attack_speed_ratios"
    )
    melee_as, ranged_as = _required_pair(name, effects, "attack_speed_ratios")
    max_stacks = int(effects.number("max_stacks"))

    def raw(inputs: DamageInputs) -> float:
        table = melee_by_level if inputs.is_melee else ranged_by_level
        per_as = melee_per_as if inputs.is_melee else ranged_per_as
        bonus_as = inputs.champion_stats.get("bonus_attack_speed", 0.0)
        return _at_level(table, inputs.level) * (1.0 + per_as * bonus_as)

    return KeystoneProcEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        # The swing that reaches maximum stacks is not counted as empowered:
        # the wiki does not order its on-attack stack grant against the bolt,
        # so the empowered stream starts one swing later — a floor.
        stacks_required=max_stacks + 1,
        stack_window_seconds=None,
        cooldown_seconds=0.0,
        proc_delay_seconds=0.0,
        raw_damage=raw,
        damage_type=_pure_adaptive_type,
        trigger=KeystoneTrigger.BASIC_ATTACKS,
        consumes_stacks=False,
        disclosures=(
            f"{name}'s bonus attack speed (up to "
            f"{melee_as * max_stacks * 100:g}% melee / "
            f"{ranged_as * max_stacks * 100:g}% ranged) is withheld: no "
            "keystone reaches the stat block, so the fight's swing rate is "
            "the build's alone and the bolt's per-attack-speed increase "
            "reads the build's bonus attack speed only.",
            f"{name} empowers swings from the {max_stacks + 1}th on and its "
            "stacks are assumed not to decay between them; the cache carries "
            "no stack duration, so the empowered count is a floor.",
        ),
    )


def _compile_deathfire_touch(entry: Mapping[str, Any]) -> KeystoneProcEffect:
    """Compile Deathfire Touch: each damaging cast burns for at least one tick.

    The cache carries the tick's damage and its cadence but not the burn's
    duration (which the wiki keys to the form of ability damage) nor the
    escalation after three seconds, so one tick per cast is priced — the
    floor every application guarantees.
    """
    name = "Deathfire Touch"
    effects = _RequiredRuneValues(name, entry.get("effects", {}))
    base_by_level = _required_leveling(name, effects)
    _certify_uniform_escalation(name, effects, "leveling")
    bonus_ad_ratio = effects.number("bonus_ad_ratio")
    ap_ratio = effects.number("ap_ratio")
    tick_seconds = effects.number("tick_interval_seconds")

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
        stacks_required=1,
        stack_window_seconds=None,
        cooldown_seconds=0.0,
        proc_delay_seconds=tick_seconds,
        raw_damage=raw,
        damage_type=_stated_type("magic"),
        trigger=KeystoneTrigger.DAMAGING_CASTS,
        disclosures=(
            f"{name} prices one {tick_seconds:g}s burn tick per damaging "
            "ability cast: the cache carries the tick but not the burn's "
            "duration or its escalation after three seconds, so the tick "
            "count is a floor of one per cast.",
        ),
    )


# The keystones that book no damage: disposition, the reason that becomes
# the receipt, and any further half this engine refuses. A table rather than
# eight compilers, because these differ only in their words — and a
# difference that is only words belongs in a table beside its reader, which
# is what ``_KEYSTONE_COMPILERS`` itself is.
_NO_DAMAGE_KEYSTONES: Mapping[str, tuple[Disposition, str, tuple[str, ...]]] = {
    "Unsealed Spellbook": (
        Disposition.STRUCTURAL_ZERO,
        "it swaps summoner spells out of combat, and no source states a "
        "combat number for it",
        (),
    ),
    "Glacial Augment": (
        Disposition.STRUCTURAL_ZERO,
        "its zones slow, and the damage reduction they apply protects the "
        "holder's allies while explicitly excluding the holder",
        (),
    ),
    "Stormraider's Surge": (
        Disposition.STRUCTURAL_ZERO,
        "it grants movement speed and slow resist, neither of which the "
        "engine's damage model reads",
        (
            "Stormraider's Surge's zero is exact only while the holder owns "
            "no Swiftmarch, whose passive converts movement speed into "
            "adaptive force (item_effects.swiftmarch_adaptive_force); that "
            "coupling is disclosed, not modeled.",
        ),
    ),
    "Conqueror": (
        Disposition.WITHHELD,
        "its stacks grant adaptive force and no keystone reaches the stat "
        "block, so the engine has no channel to price them through",
        (
            "Conqueror's heal at maximum stacks is withheld too: the engine "
            "has no keystone healing channel.",
        ),
    ),
    "Fleet Footwork": (
        Disposition.WITHHELD,
        "its empowered attack heals and grants movement speed, and the "
        "engine has no keystone healing channel to price the heal through",
        (
            "Fleet Footwork deals no damage of its own, so nothing is "
            "understated in the damage total by withholding it.",
        ),
    ),
    "Aftershock": (
        Disposition.WITHHELD,
        "its shockwave fires only after the holder immobilizes a champion, "
        "and ability events carry no reviewed crowd-control kind, so the "
        "engine cannot say whether or when it lands",
        (
            "Aftershock's bonus resistances are withheld for the same reason "
            "and are defensive besides: the pair engine prices outgoing "
            "damage.",
        ),
    ),
    "Guardian": (
        Disposition.WITHHELD,
        "it shields the holder or a guarded ally against incoming damage, "
        "and the pair engine prices the holder's outgoing damage",
        (),
    ),
    # Every term of Dark Harvest's damage is cached and its condition is
    # not, so the engine cannot say whether a proc landed. Pricing it on the
    # cooldown alone would invent procs against a healthy target, which is
    # the one direction this engine never errs in.
    "Dark Harvest": (
        Disposition.WITHHELD,
        "its reap fires only against a champion below a share of maximum "
        "health and the cache carries no such threshold, so the engine "
        "cannot say when — or whether — it lands",
        (
            "Dark Harvest's soul count is unknowable in one fight and would "
            "be priced at zero souls; the missing gate withholds the proc "
            "anyway.",
        ),
    ),
}


def _no_damage_compiler(
    name: str,
) -> Callable[[Mapping[str, Any]], KeystoneNoDamageEffect]:
    """The compiler for one damageless keystone, from its declaration."""
    disposition, reason, disclosures = _NO_DAMAGE_KEYSTONES[name]

    def compile_declared(entry: Mapping[str, Any]) -> KeystoneNoDamageEffect:
        del entry  # the declaration is the whole compilation
        return KeystoneNoDamageEffect(
            keystone_name=name,
            zero_policy=ZeroPolicy(disposition, reason),
            disclosures=disclosures,
        )

    return compile_declared


_KEYSTONE_COMPILERS: dict[str, Callable[[Mapping[str, Any]], KeystoneEffect]] = {
    "Electrocute": _compile_electrocute,
    "First Strike": _compile_first_strike,
    "Press the Attack": _compile_press_the_attack,
    "Arcane Comet": _compile_arcane_comet,
    "Summon Aery": _compile_summon_aery,
    "Hail of Blades": _compile_hail_of_blades,
    "Grasp of the Undying": _compile_grasp_of_the_undying,
    "Lethal Tempo": _compile_lethal_tempo,
    "Deathfire Touch": _compile_deathfire_touch,
    **{name: _no_damage_compiler(name) for name in _NO_DAMAGE_KEYSTONES},
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
