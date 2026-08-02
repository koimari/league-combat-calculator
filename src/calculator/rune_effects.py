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


def refresh_rune_effects() -> None:
    """Re-read data/runes.json in place after a data update."""
    RUNE_EFFECTS.clear()
    RUNE_EFFECTS.update(_load_rune_effects())


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


KeystoneEffect = KeystoneProcEffect | KeystoneWindowAmpEffect | KeystoneProcAmpEffect


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
        level_index = max(1, min(inputs.level, len(base_by_level))) - 1
        return (
            base_by_level[level_index]
            + bonus_ad_ratio * stats.get("bonus_attack_damage", 0.0)
            + ap_ratio * stats.get("ability_power", 0.0)
        )

    def adaptive_type(stats: Mapping[str, float]) -> str:
        ad_contribution = bonus_ad_ratio * stats.get("bonus_attack_damage", 0.0)
        ap_contribution = ap_ratio * stats.get("ability_power", 0.0)
        return "physical" if ad_contribution > ap_contribution else "magic"

    return KeystoneProcEffect(
        keystone_name=name,
        breakdown_key=f"keystone_{name}",
        display_name=f"{name} (keystone)",
        stacks_required=int(effects.number("stacks_required")),
        stack_window_seconds=effects.number("stack_window_seconds"),
        cooldown_seconds=top.number("cooldown"),
        proc_delay_seconds=effects.number("proc_delay_seconds"),
        raw_damage=raw,
        damage_type=adaptive_type,
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
        level_index = max(1, min(inputs.level, len(base_by_level))) - 1
        return base_by_level[level_index]

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


_KEYSTONE_COMPILERS: dict[str, Callable[[Mapping[str, Any]], KeystoneEffect]] = {
    "Electrocute": _compile_electrocute,
    "First Strike": _compile_first_strike,
    "Press the Attack": _compile_press_the_attack,
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
