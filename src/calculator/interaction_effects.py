"""Typed champion-to-champion interaction atoms.

The module stores interaction state separately from damage arithmetic. Numeric
rank values come from the cached champion ability rows. The combat walk uses
the resolved atom to apply timing, selection, and one-use rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ability_atoms import (
    atom_receipt,
    required_ability_atom,
    required_ranked_attribute_atom,
)
from .delivery_facts import ChampionFacts, CombatantFacts, DefenseWindow
from .interaction_atoms import (
    AMUMU_REDUCTION_CAP_QUERY,
    cached_ability,
    combatant_level,
    rank_for,
    ranked_atom_value,
)
from .item_effects import (
    annul_spell_shield_cooldown_atom,
    annul_spell_shield_timer_restarts,
    spell_shield_cooldown_seconds,
)
from .spell_shield_eligibility import SpellShieldComposition, SpellShieldEligibility
from .spell_shield_rearm import SpellShieldRearmClock
from .state_timeline import SourceReceipt


@dataclass(frozen=True, slots=True)
class TargetPhysicalDamageReduction:
    """One target passive that reduces physical damage before mitigation."""

    flat_amount: float
    per_instance_cap: float
    source: str
    source_atoms: tuple[dict[str, Any], ...] = ()


def resolve_physical_damage_reduction(
    combatant: ChampionFacts,
) -> TargetPhysicalDamageReduction | None:
    """Resolve a typed target passive that reduces physical damage."""
    champion_data = getattr(combatant, "champion_data", {})
    champion = str(champion_data.get("name", ""))
    if champion != "Amumu":
        return None
    request = getattr(combatant, "request", None)
    rank = rank_for(champion, combatant_level(combatant), request, "E")
    ability = cached_ability(champion_data, "E")
    if rank < 1 or ability is None:
        return None

    flat, flat_atom = required_ranked_attribute_atom(
        champion,
        champion_data,
        "E",
        "Physical Damage Reduction",
        rank,
        modifier_index=0,
    )
    armor_percent, armor_atom = required_ranked_attribute_atom(
        champion,
        champion_data,
        "E",
        "Physical Damage Reduction",
        rank,
        modifier_index=1,
    )
    magic_resistance_percent, magic_resistance_atom = required_ranked_attribute_atom(
        champion,
        champion_data,
        "E",
        "Physical Damage Reduction",
        rank,
        modifier_index=2,
    )
    flat = ranked_atom_value(
        flat_atom,
        rank,
        source=flat_atom["source"],
        unit="",
    )
    armor_percent = ranked_atom_value(
        armor_atom,
        rank,
        source=armor_atom["source"],
        unit="% bonus armor",
    )
    magic_resistance_percent = ranked_atom_value(
        magic_resistance_atom,
        rank,
        source=magic_resistance_atom["source"],
        unit="% bonus magic resistance",
    )
    cap_atom = required_ability_atom(
        champion, champion_data, "E", query=AMUMU_REDUCTION_CAP_QUERY
    )
    cap_percent = ranked_atom_value(
        cap_atom,
        1,
        source=AMUMU_REDUCTION_CAP_QUERY.source,
        unit="%",
    )
    stats = getattr(combatant, "stats", {})
    bonus_armor = max(0.0, float(stats.get("bonus_armor", 0.0) or 0.0))
    bonus_magic_resistance = max(
        0.0, float(stats.get("bonus_magic_resistance", 0.0) or 0.0)
    )
    flat_amount = max(
        0.0,
        flat
        + armor_percent * bonus_armor / 100.0
        + magic_resistance_percent * bonus_magic_resistance / 100.0,
    )
    return TargetPhysicalDamageReduction(
        flat_amount=flat_amount,
        per_instance_cap=max(0.0, cap_percent / 100.0),
        source="Amumu E · Tantrum",
        source_atoms=(
            atom_receipt(flat_atom),
            atom_receipt(armor_atom),
            atom_receipt(magic_resistance_atom),
            atom_receipt(cap_atom),
        ),
    )


def target_physical_damage_reduction_params(
    combatant: ChampionFacts,
) -> dict[str, float]:
    """Return numeric target overrides for the one-pair damage engine."""
    reduction = resolve_physical_damage_reduction(combatant)
    if reduction is None:
        return {
            "target_physical_damage_flat_reduction": 0.0,
            "target_physical_damage_flat_reduction_cap": 0.0,
        }
    return {
        "target_physical_damage_flat_reduction": reduction.flat_amount,
        "target_physical_damage_flat_reduction_cap": reduction.per_instance_cap,
    }


def public_physical_damage_reduction(
    reduction: TargetPhysicalDamageReduction | None,
) -> dict[str, Any] | None:
    """Return a JSON-safe receipt for one target physical reduction."""
    if reduction is None:
        return None
    return {
        "source": reduction.source,
        "flat_amount": round(reduction.flat_amount, 3),
        "per_instance_cap": round(reduction.per_instance_cap, 6),
        "source_atoms": [dict(atom) for atom in reduction.source_atoms],
    }


_ANNUL_ITEM_NAMES = ("Banshee's Veil", "Edge of Night", "Verdant Barrier")


@dataclass(frozen=True, slots=True)
class SpellShieldContract:
    """One resolved spell shield: kernel eligibility + composition."""

    eligibility: SpellShieldEligibility
    composition: SpellShieldComposition
    cooldown_seconds: float = 0.0
    cooldown_atom: dict[str, Any] | None = None
    rearm: SpellShieldRearmClock = field(default_factory=SpellShieldRearmClock)

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe contract receipt."""
        return {
            "eligibility": self.eligibility.public_receipt(),
            "composition": self.composition.public_receipt(),
            "cooldown_seconds": round(self.cooldown_seconds, 3),
            "cooldown_atom": (
                dict(self.cooldown_atom) if self.cooldown_atom is not None else None
            ),
            "rearm": self.rearm.public_receipt(),
        }


def resolve_spell_shield(combatant: CombatantFacts) -> SpellShieldContract | None:
    """Resolve one item-owned Annul spell shield from a combatant.

    The starting defenses (:mod:`defensive_effects`) declare readiness
    and the source label; this resolver builds the kernel eligibility —
    an infinite window until consumed (start inclusive) — the kernel
    composition — one use per hostile ability cast, no triggered heal —
    and the kernel rearm clock, whose cooldown and timer-restart clause
    both come from the :mod:`item_effects` typed accessors.  A holder
    whose Annul item cannot be named carries the default unsourced clock,
    which never rearms.  Sivir's timed shield is armed by the survival
    walk from its authored packet instead, and carries no clock at all.
    """
    defenses = getattr(combatant, "defenses", None)
    if defenses is None or not bool(getattr(defenses, "spell_shield_ready", False)):
        return None
    source = str(getattr(defenses, "spell_shield_source", "") or "Annul")
    item_name = next(
        (
            str(item.get("name", ""))
            for item in (getattr(combatant, "items", None) or ())
            if str(item.get("name", "")) in _ANNUL_ITEM_NAMES
        ),
        "",
    )
    cooldown = 0.0
    cooldown_atom: dict[str, Any] | None = None
    rearm = SpellShieldRearmClock()
    if item_name:
        cooldown = spell_shield_cooldown_seconds(item_name)
        cooldown_atom = annul_spell_shield_cooldown_atom(item_name)
        rearm = SpellShieldRearmClock(
            cooldown=cooldown,
            restarts_on_champion_damage=annul_spell_shield_timer_restarts(item_name),
            source_atom=dict(cooldown_atom),
        )
    return SpellShieldContract(
        eligibility=SpellShieldEligibility(
            name="annul",
            window=DefenseWindow(start=0.0, until=float("inf")),
            block_rule=(
                "Annul: 'blocks the next hostile ability' — one use per "
                "hostile ability instance, and the sourced cooldown rearms "
                "the shield inside the fight only once it has fully elapsed."
            ),
            source=SourceReceipt(label=source, url="https://wiki.leagueoflegends.com"),
        ),
        composition=SpellShieldComposition(),
        cooldown_seconds=cooldown,
        cooldown_atom=cooldown_atom,
        rearm=rearm,
    )


__all__ = [
    "TargetPhysicalDamageReduction",
    "public_physical_damage_reduction",
    "resolve_physical_damage_reduction",
    "resolve_spell_shield",
    "target_physical_damage_reduction_params",
]
