#!/usr/bin/env python3
"""Interactive Rengar pen comparison.

The file has no third-party dependency.  Run it from this repository to use
the current calculator data.  A copied file uses the level-14 Rengar snapshot
in ``_standalone_model``.  This keeps the calculator easy to share.

The comparison is:

* Bastionbreaker + Umbral Glaive + Voltaic Cyclosword
* Bastionbreaker + Umbral Glaive + Lord Dominik's Regards

The script reports packet damage.  It also reports damage that can land on
the supplied current health.  Breakpoints use packet damage so a target that
dies does not hide a build difference.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if (_PROJECT_ROOT / "src").is_dir():
    sys.path.insert(0, str(_PROJECT_ROOT))


try:
    from src.calculator.resistance import apply_armor_penetration, apply_resistance
except (ImportError, TypeError):
    # Python 3.9 cannot import the repository's PEP 604 annotations.  The
    # copied script still has a complete level-14 snapshot for that case.

    def apply_resistance(raw_damage: float, resistance: float) -> float:
        """Apply League resistance math for the standalone copy."""
        if resistance >= 0.0:
            return raw_damage * 100.0 / (100.0 + resistance)
        return raw_damage * (2.0 - 100.0 / (100.0 - resistance))

    def apply_armor_penetration(
        target_armor: float, flat_penetration: float, percent_penetration: float
    ) -> float:
        """Apply percent armor penetration, then flat penetration."""
        if target_armor <= 0.0:
            return target_armor
        return max(0.0, target_armor * (1.0 - percent_penetration) - flat_penetration)


@dataclass(frozen=True)
class BuildPacket:
    """Raw Rengar packet values and the build penetration stats."""

    name: str
    q_raw: float
    w_raw: float
    e_raw: float
    auto_raw: float
    flat_armor_pen: float
    percent_armor_pen: float
    lethality: float


@dataclass(frozen=True)
class Model:
    """The sourced values shared by the two build paths."""

    triple: BuildPacket
    ldr: BuildPacket
    bastion_base: float
    bastion_lethality_ratio: float
    umbral_base: float
    umbral_lethality_ratio: float
    cyclosword_current_health_ratio: float
    cyclosword_extra_lethality: float
    ldr_max_amp: float
    ldr_bonus_health_cap: float
    source: str


@dataclass(frozen=True)
class Inputs:
    """One user-supplied comparison scenario."""

    enemy_total_hp: float
    enemy_current_hp: float
    enemy_bonus_hp: float
    user_total_hp: float
    enemy_armor: float
    enemy_mr: float
    r_armor_reduction: float
    one_auto: bool
    umbral_ready: bool
    cyclosword_lethality_for_true_procs: bool


@dataclass(frozen=True)
class DamageResult:
    """One build's result for one scenario."""

    packet_damage: float
    delivered_damage: float
    physical_damage: float
    magic_damage: float
    true_damage: float
    cyclosword_raw: float
    shaped_charge_true: float
    umbral_true: float
    ldr_amp: float
    armor_before_pen: float
    armor_for_early_physical: float
    armor_for_late_physical: float


def _standalone_model(one_auto: bool) -> Model:
    """Return a shareable level-14 snapshot from the current app.

    The values came from the app's deterministic level-14 Rengar rotation at
    zero target resistances.  The repository path below is preferred when it
    is available, so the item registry remains the live source there.
    """
    return Model(
        triple=BuildPacket(
            name="Triple lethality",
            q_raw=149.8,
            w_raw=170.0,
            e_raw=236.0,
            auto_raw=274.0 if one_auto else 0.0,
            flat_armor_pen=50.0,
            percent_armor_pen=0.0,
            lethality=50.0,
        ),
        ldr=BuildPacket(
            name="LDR",
            q_raw=145.8,
            w_raw=170.0,
            e_raw=220.0,
            auto_raw=317.5 if one_auto else 0.0,
            flat_armor_pen=40.0,
            percent_armor_pen=0.35,
            lethality=40.0,
        ),
        bastion_base=50.0,
        bastion_lethality_ratio=1.5,
        umbral_base=50.0,
        umbral_lethality_ratio=1.5,
        cyclosword_current_health_ratio=0.09,
        cyclosword_extra_lethality=15.0,
        ldr_max_amp=0.15,
        ldr_bonus_health_cap=1500.0,
        source="standalone level-14 Rengar snapshot",
    )


def _breakdown_total(result: dict, key: str) -> float:
    """Read one raw calibration row."""
    row = result.get("breakdown", {}).get(key, {})
    return float(row.get("total_damage", 0.0))


def _model_from_repository(level: int, one_auto: bool) -> Model:
    """Build the model from the calculator's typed item and champion paths."""
    from src.calculator.data_fetcher import get_champion, get_item_by_name
    from src.calculator.item_effects import required_effect_value
    from src.calculator.pipeline import FightParams, run_fight

    item_names = {
        "triple": ["Bastionbreaker", "Umbral Glaive", "Voltaic Cyclosword"],
        "ldr": ["Bastionbreaker", "Umbral Glaive", "Lord Dominik's Regards"],
    }
    champion = get_champion("Rengar")
    item_options = {"Umbral Glaive": {"nightstalker_ready": 1}} if one_auto else None

    def calibrate(names: list[str]) -> tuple[dict, list[dict]]:
        items = [get_item_by_name(name) for name in names]
        params = FightParams(
            target_health=10000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            target_bonus_health=0.0,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.3 if one_auto else 0.0,
            auto_attack_uptime_mode="explicit",
            one_rotation=True,
            role="top",
            item_options=item_options,
            deterministic=True,
        )
        return run_fight(champion, level, items, params), items

    triple_result, _ = calibrate(item_names["triple"])
    ldr_result, _ = calibrate(item_names["ldr"])
    triple_stats = triple_result["champion_stats"]
    ldr_stats = ldr_result["champion_stats"]

    def number(item: str, key: str) -> float:
        return float(required_effect_value(item, key))

    return Model(
        triple=BuildPacket(
            name="Triple lethality",
            q_raw=_breakdown_total(triple_result, "Q"),
            w_raw=_breakdown_total(triple_result, "W"),
            e_raw=_breakdown_total(triple_result, "E"),
            auto_raw=_breakdown_total(triple_result, "auto_attacks"),
            flat_armor_pen=float(triple_stats["flat_armor_penetration"]),
            percent_armor_pen=float(triple_stats["armor_penetration_percent"]) / 100.0,
            lethality=float(triple_stats["lethality"]),
        ),
        ldr=BuildPacket(
            name="LDR",
            q_raw=_breakdown_total(ldr_result, "Q"),
            w_raw=_breakdown_total(ldr_result, "W"),
            e_raw=_breakdown_total(ldr_result, "E"),
            auto_raw=_breakdown_total(ldr_result, "auto_attacks"),
            flat_armor_pen=float(ldr_stats["flat_armor_penetration"]),
            percent_armor_pen=float(ldr_stats["armor_penetration_percent"]) / 100.0,
            lethality=float(ldr_stats["lethality"]),
        ),
        bastion_base=number("Bastionbreaker", "base_melee"),
        bastion_lethality_ratio=number("Bastionbreaker", "lethality_ratio_melee"),
        umbral_base=number("Umbral Glaive", "base"),
        umbral_lethality_ratio=number("Umbral Glaive", "lethality_ratio"),
        cyclosword_current_health_ratio=number(
            "Voltaic Cyclosword", "current_hp_ratio_melee"
        ),
        cyclosword_extra_lethality=number(
            "Voltaic Cyclosword", "temporary_lethality_melee"
        ),
        ldr_max_amp=number("Lord Dominik's Regards", "max_amp"),
        ldr_bonus_health_cap=number("Lord Dominik's Regards", "bonus_hp_cap"),
        source=f"repository data, level-{level} deterministic Rengar calibration",
    )


def load_model(level: int, one_auto: bool) -> Model:
    """Use live repository data when the file runs inside the project."""
    try:
        return _model_from_repository(level, one_auto)
    except (ImportError, TypeError):
        if level != 14:
            raise RuntimeError(
                "The copied standalone file has a level-14 snapshot. "
                "Use level 14, or run the file from the calculator repository."
            ) from None
        return _standalone_model(one_auto)


def _mitigation(resistance: float) -> float:
    """Return the post-resistance multiplier for one raw damage point."""
    return apply_resistance(1.0, resistance)


def evaluate(
    model: Model,
    values: Inputs,
    *,
    armor: float | None = None,
    bonus_hp: float | None = None,
    current_hp: float | None = None,
) -> tuple[DamageResult, DamageResult]:
    """Evaluate both builds for a scenario or a breakpoint probe."""
    target_armor = values.enemy_armor if armor is None else max(0.0, armor)
    target_bonus_hp = values.enemy_bonus_hp if bonus_hp is None else max(0.0, bonus_hp)
    target_current_hp = (
        values.enemy_current_hp if current_hp is None else max(0.0, current_hp)
    )
    reduced_armor = target_armor - max(0.0, values.r_armor_reduction)
    triple = model.triple
    ldr = model.ldr
    triple_early_armor = apply_armor_penetration(
        reduced_armor, triple.flat_armor_pen, triple.percent_armor_pen
    )
    triple_late_armor = apply_armor_penetration(
        reduced_armor,
        triple.flat_armor_pen + model.cyclosword_extra_lethality,
        triple.percent_armor_pen,
    )
    ldr_armor = apply_armor_penetration(
        reduced_armor, ldr.flat_armor_pen, ldr.percent_armor_pen
    )
    triple_lethality_for_true = triple.lethality + (
        model.cyclosword_extra_lethality
        if values.cyclosword_lethality_for_true_procs
        else 0.0
    )
    shaped_true_triple = model.bastion_base + (
        model.bastion_lethality_ratio * triple_lethality_for_true
    )
    umbral_true_triple = (
        model.umbral_base + model.umbral_lethality_ratio * triple_lethality_for_true
        if values.one_auto and values.umbral_ready
        else 0.0
    )
    triple_cyclosword_raw = model.cyclosword_current_health_ratio * target_current_hp
    triple_early_physical = (triple.q_raw + triple.e_raw) * _mitigation(
        triple_early_armor
    )
    triple_late_physical = (
        (triple.auto_raw if values.one_auto else 0.0) + triple_cyclosword_raw
    ) * _mitigation(triple_late_armor)
    triple_magic = triple.w_raw * _mitigation(values.enemy_mr)
    triple_true = shaped_true_triple + umbral_true_triple
    triple_packet = (
        triple_early_physical + triple_late_physical + triple_magic + triple_true
    )

    ldr_true_shaped = model.bastion_base + model.bastion_lethality_ratio * ldr.lethality
    ldr_true_umbral = (
        model.umbral_base + model.umbral_lethality_ratio * ldr.lethality
        if values.one_auto and values.umbral_ready
        else 0.0
    )
    ldr_physical = (
        ldr.q_raw + ldr.e_raw + (ldr.auto_raw if values.one_auto else 0.0)
    ) * _mitigation(ldr_armor)
    ldr_magic = ldr.w_raw * _mitigation(values.enemy_mr)
    ldr_true = ldr_true_shaped + ldr_true_umbral
    ldr_amp = model.ldr_max_amp * min(
        max(0.0, target_bonus_hp) / model.ldr_bonus_health_cap, 1.0
    )
    ldr_packet = (ldr_physical + ldr_magic + ldr_true) * (1.0 + ldr_amp)

    return (
        DamageResult(
            packet_damage=triple_packet,
            delivered_damage=min(max(0.0, target_current_hp), triple_packet),
            physical_damage=triple_early_physical + triple_late_physical,
            magic_damage=triple_magic,
            true_damage=triple_true,
            cyclosword_raw=triple_cyclosword_raw,
            shaped_charge_true=shaped_true_triple,
            umbral_true=umbral_true_triple,
            ldr_amp=0.0,
            armor_before_pen=reduced_armor,
            armor_for_early_physical=triple_early_armor,
            armor_for_late_physical=triple_late_armor,
        ),
        DamageResult(
            packet_damage=ldr_packet,
            delivered_damage=min(max(0.0, target_current_hp), ldr_packet),
            physical_damage=ldr_physical * (1.0 + ldr_amp),
            magic_damage=ldr_magic * (1.0 + ldr_amp),
            true_damage=ldr_true * (1.0 + ldr_amp),
            cyclosword_raw=0.0,
            shaped_charge_true=ldr_true_shaped * (1.0 + ldr_amp),
            umbral_true=ldr_true_umbral * (1.0 + ldr_amp),
            ldr_amp=ldr_amp,
            armor_before_pen=reduced_armor,
            armor_for_early_physical=ldr_armor,
            armor_for_late_physical=ldr_armor,
        ),
    )


def first_crossing(
    function: Callable[[float], float],
    start: float,
    end: float,
    samples: int = 2000,
) -> float | None:
    """Find the first sign change and refine it with bisection."""
    if end <= start:
        return None
    previous_x = start
    previous_y = function(previous_x)
    if abs(previous_y) <= 1e-9:
        return previous_x
    step = (end - start) / max(1, samples)
    for index in range(1, samples + 1):
        current_x = end if index == samples else start + step * index
        current_y = function(current_x)
        if abs(current_y) <= 1e-9:
            return current_x
        if previous_y * current_y < 0.0:
            low, high = previous_x, current_x
            low_y = previous_y
            for _ in range(70):
                middle = (low + high) / 2.0
                middle_y = function(middle)
                if abs(middle_y) <= 1e-10:
                    return middle
                if low_y * middle_y <= 0.0:
                    high = middle
                else:
                    low, low_y = middle, middle_y
            return (low + high) / 2.0
        previous_x, previous_y = current_x, current_y
    return None


def _winner(delta: float) -> str:
    if abs(delta) <= 0.01:
        return "tie"
    return "triple lethality" if delta > 0.0 else "LDR"


def _prompt_float(
    label: str, default: float | None = None, minimum: float = 0.0
) -> float:
    """Read one finite non-negative number."""
    suffix = f" [{default:g}]" if default is not None else ""
    while True:
        raw = input(f"{label}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        try:
            value = float(raw)
        except ValueError:
            print("Enter a number.")
            continue
        if not math.isfinite(value) or value < minimum:
            print(f"Enter a number at least {minimum:g}.")
            continue
        return value


def _prompt_int(label: str, default: int, minimum: int, maximum: int) -> int:
    """Read one bounded integer."""
    while True:
        raw = input(f"{label} [{default}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("Enter a whole number.")
            continue
        if not minimum <= value <= maximum:
            print(f"Enter a whole number from {minimum} to {maximum}.")
            continue
        return value


def _prompt_yes_no(label: str, default: bool) -> bool:
    """Read a yes/no answer."""
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{label} [{suffix}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Enter y or n.")


def _read_inputs() -> tuple[int, Inputs]:
    """Collect every scenario input used by the equations."""
    print("\nRengar item comparison")
    print("Enter the target state at the moment Cyclosword procs.\n")
    level = _prompt_int("Rengar level", 14, 1, 20)
    total_hp = _prompt_float("Enemy total HP", 2500.0)
    current_hp = _prompt_float("Enemy current HP", total_hp)
    while current_hp > total_hp:
        print("Current HP cannot be above total HP.")
        current_hp = _prompt_float("Enemy current HP", total_hp)
    bonus_hp = _prompt_float("Enemy bonus HP", 1000.0)
    user_hp = _prompt_float("Rengar total HP", 1847.0)
    armor = _prompt_float("Enemy armor", 200.0)
    mr = _prompt_float("Enemy magic resistance", 50.0)
    r_reduction = _prompt_float("Rengar R armor reduction", 20.0)
    one_auto = _prompt_yes_no("Include one auto attack", True)
    umbral_ready = _prompt_yes_no("Umbral Glaive ready", True) if one_auto else False
    true_snapshot = _prompt_yes_no(
        "Apply Cyclosword +15 lethality to Bastionbreaker and Umbral true procs",
        False,
    )
    return level, Inputs(
        enemy_total_hp=total_hp,
        enemy_current_hp=current_hp,
        enemy_bonus_hp=bonus_hp,
        user_total_hp=user_hp,
        enemy_armor=armor,
        enemy_mr=mr,
        r_armor_reduction=r_reduction,
        one_auto=one_auto,
        umbral_ready=umbral_ready,
        cyclosword_lethality_for_true_procs=true_snapshot,
    )


def _fmt(value: float) -> str:
    return f"{value:,.2f}"


def _print_row(label: str, triple: str, ldr: str) -> None:
    """Print one aligned build row."""
    print(f"{label:<24} {triple:>18}  {ldr:>10}")


def _print_result(
    model: Model, values: Inputs, triple: DamageResult, ldr: DamageResult
) -> None:
    """Print a compact result table."""
    print("\nINPUTS")
    print(
        "Enemy HP: "
        f"total {_fmt(values.enemy_total_hp)}, "
        f"current {_fmt(values.enemy_current_hp)}, "
        f"bonus {_fmt(values.enemy_bonus_hp)}"
    )
    print(
        f"Enemy armor {_fmt(values.enemy_armor)}, "
        f"MR {_fmt(values.enemy_mr)}, "
        f"R reduction {_fmt(values.r_armor_reduction)}"
    )
    print(
        f"One auto: {'yes' if values.one_auto else 'no'}, "
        f"Umbral ready: {'yes' if values.umbral_ready else 'no'}"
    )
    print("\nRESULT")
    print(f"Source: {model.source}")
    print(f"Rengar HP entered: {_fmt(values.user_total_hp)}")
    print("Current LDR formula uses target bonus HP. It does not use holder HP.")
    print("The current engine applies its LDR amplifier to the full damage total.")
    print(f"Armor after R reduction: {_fmt(triple.armor_before_pen)}")
    print("\n                         Triple lethality       LDR")
    _print_row("Packet damage", _fmt(triple.packet_damage), _fmt(ldr.packet_damage))
    _print_row(
        "Damage that can land",
        _fmt(triple.delivered_damage),
        _fmt(ldr.delivered_damage),
    )
    _print_row(
        "Physical damage", _fmt(triple.physical_damage), _fmt(ldr.physical_damage)
    )
    _print_row("Magic damage", _fmt(triple.magic_damage), _fmt(ldr.magic_damage))
    _print_row("True damage", _fmt(triple.true_damage), _fmt(ldr.true_damage))
    _print_row("Cyclosword raw", _fmt(triple.cyclosword_raw), "0.00")
    _print_row(
        "Bastionbreaker true",
        _fmt(triple.shaped_charge_true),
        _fmt(ldr.shaped_charge_true),
    )
    _print_row("Umbral true", _fmt(triple.umbral_true), _fmt(ldr.umbral_true))
    _print_row("LDR amp", "0.00%", f"{ldr.ldr_amp:.2%}")
    delta = triple.packet_damage - ldr.packet_damage
    print(f"\nPacket delta: {_fmt(delta)}. Winner: {_winner(delta)}.")
    print("Breakpoints use packet damage. A kill can make delivered damage look tied.")


def _print_breakpoints(model: Model, values: Inputs) -> None:
    """Find and print the three scenario breakpoints."""

    def delta_for(**kwargs: float) -> float:
        triple, ldr = evaluate(model, values, **kwargs)
        return triple.packet_damage - ldr.packet_damage

    print("\nBREAKPOINTS")
    armor_end = max(2000.0, values.enemy_armor * 2.0 + 100.0)
    armor_break = first_crossing(lambda armor: delta_for(armor=armor), 0.0, armor_end)
    bonus_end = max(3000.0, values.enemy_bonus_hp * 2.0 + 1000.0)
    bonus_break = first_crossing(
        lambda bonus: delta_for(bonus_hp=bonus), 0.0, bonus_end
    )
    current_break = first_crossing(
        lambda current: delta_for(current_hp=current),
        0.0,
        max(1.0, values.enemy_total_hp),
    )
    rows = (
        ("Enemy armor", armor_break, 0.0, armor_end, lambda x: delta_for(armor=x)),
        (
            "Enemy bonus HP",
            bonus_break,
            0.0,
            bonus_end,
            lambda x: delta_for(bonus_hp=x),
        ),
        (
            "Enemy current HP",
            current_break,
            0.0,
            max(1.0, values.enemy_total_hp),
            lambda x: delta_for(current_hp=x),
        ),
    )
    for label, crossing, start, end, function in rows:
        if crossing is None:
            print(f"{label:<18} no crossover from {_fmt(start)} to {_fmt(end)}")
            continue
        offset = max(0.01, (end - start) / 1000.0)
        below = function(max(start, crossing - offset))
        above = function(min(end, crossing + offset))
        print(
            f"{label:<18} {_fmt(crossing)}  "
            f"below: {_winner(below):<17} above: {_winner(above)}"
        )
    print("User total HP breakpoint: none under the current LDR source rule.")


def main() -> None:
    """Run the interactive calculator."""
    try:
        level, values = _read_inputs()
        model = load_model(level, values.one_auto)
        triple, ldr = evaluate(model, values)
        _print_result(model, values, triple, ldr)
        _print_breakpoints(model, values)
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.")
        sys.exit(1)
    except RuntimeError as error:
        print(f"\nCannot run: {error}")
        sys.exit(2)


if __name__ == "__main__":
    main()
