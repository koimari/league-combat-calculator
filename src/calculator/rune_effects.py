"""Keystone rune values and effect formulas.

Mirrors ``item_effects`` ownership rules for runes: every numeric rune value
comes from ``data/runes.json`` (parsed from the League Wiki's rune data
templates) through typed accessors that raise, naming the rune and key, when
the parse degraded. No literal fallbacks.

Only keystones with a compile function in ``_KEYSTONE_COMPILERS`` are
modeled; selecting any other keystone fails closed with a clear error. The
full roster is still served to the UI through :func:`keystone_catalog` so
unimplemented keystones can be shown greyed out.
"""

from dataclasses import dataclass
from typing import Any, Callable, Mapping

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
    base_by_level = [float(value) for value in effects.value("leveling")[0]]
    if len(base_by_level) < 20:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling covers {len(base_by_level)} "
            "levels; expected 20 — wiki parse degraded"
        )
    return base_by_level


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
        float(value) for value in effects.value("melee_ranged_ratios")
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


_KEYSTONE_COMPILERS: dict[str, Callable[[Mapping[str, Any]], KeystoneEffect]] = {
    "Electrocute": _compile_electrocute,
    "First Strike": _compile_first_strike,
    "Press the Attack": _compile_press_the_attack,
    "Arcane Comet": _compile_arcane_comet,
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
