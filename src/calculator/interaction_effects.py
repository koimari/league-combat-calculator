"""Typed champion-to-champion interaction atoms.

The module stores interaction state separately from damage arithmetic. Numeric
rank values come from the cached champion ability rows. The combat walk uses
the resolved atom to apply timing, selection, and one-use rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .ability_atoms import (
    AbilityAtomQuery,
    ranked_ability_atom_value,
    required_ability_atom,
    required_ranked_attribute_atom,
)
from .delivery_eligibility import (
    DefenseComposition,
    DefenseEligibility,
    DefenseWindow,
    DeliveryAcceptance,
    DestructionRule,
    FullBlockRule,
    ReductionRule,
    SourceSelection,
    SourceReceipt,
    SpellShieldComposition,
    SpellShieldEligibility,
    SpellShieldRearmClock,
    UseBudget,
)
from .item_effects import (
    annul_spell_shield_cooldown_atom,
    annul_spell_shield_timer_restarts,
    spell_shield_cooldown_seconds,
)
from .champions.skill_orders import get_ability_rank


@dataclass(frozen=True, slots=True)
class ProjectileDefense:
    """One selected window for a champion projectile defense."""

    kind: str
    source: str
    start: float
    duration: float
    blocked_sources: tuple[str, ...] = ()
    blocked_event_ids: tuple[str, ...] = ()
    damage_reduction: float = 0.0
    full_block_first: bool = False
    full_block_all: bool = False
    destroy_projectiles: bool = False
    blocks_basic_attacks: bool = False
    area_damage_reduction: float = 0.0
    requires_skillshot: bool = True
    source_atoms: tuple[dict[str, Any], ...] = ()

    @property
    def until(self) -> float:
        """Return the exclusive end time of the active defense window."""
        return self.start + self.duration


@dataclass(frozen=True, slots=True)
class TargetPhysicalDamageReduction:
    """One target passive that reduces physical damage before mitigation."""

    flat_amount: float
    per_instance_cap: float
    source: str
    source_atoms: tuple[dict[str, Any], ...] = ()


def _rank_for(champion: str, level: int, request: Any, slot: str) -> int:
    requested = getattr(request, "ability_ranks", None)
    if isinstance(requested, Mapping) and slot in requested:
        return int(requested[slot])
    return int(get_ability_rank(slot, level, champion))


def _ability(champion_data: Mapping[str, Any], slot: str) -> Mapping[str, Any] | None:
    entries = champion_data.get("abilities", {}).get(slot, [])
    if not isinstance(entries, list) or not entries:
        return None
    ability = entries[0]
    return ability if isinstance(ability, Mapping) else None


def _source_selection(options: Mapping[str, Any], key: str) -> tuple[str, ...]:
    selected = options.get(key, [])
    if not isinstance(selected, list):
        return ()
    return tuple(str(value).strip() for value in selected if str(value).strip())


def _window(
    options: Mapping[str, Any],
    start_key: str,
    duration_key: str,
    source_duration: float,
) -> tuple[float, float]:
    start = max(0.0, float(options.get(start_key, 0.0) or 0.0))
    requested = max(0.0, float(options.get(duration_key, 0.0) or 0.0))
    duration = source_duration if requested <= 0.0 else min(source_duration, requested)
    return start, duration


_PROSE_DURATION_QUERIES: dict[tuple[str, str], AbilityAtomQuery] = {
    ("Yasuo", "W"): AbilityAtomQuery(
        source="Yasuo.W[0].effects[0].description",
        behavior="timing",
        evidence_prefix="active duration@",
    ),
    ("Samira", "W"): AbilityAtomQuery(
        source="Samira.W[0].effects[0].description",
        behavior="timing",
        evidence_prefix="active duration@",
    ),
    ("Gwen", "W"): AbilityAtomQuery(
        source="Gwen.W[0].effects[0].description",
        behavior="timing",
        evidence_prefix="active duration@",
    ),
    ("Fiora", "W"): AbilityAtomQuery(
        source="Fiora.W[0].effects[0].description",
        behavior="timing",
        evidence_prefix="active duration@",
    ),
    ("Pantheon", "E"): AbilityAtomQuery(
        source="Pantheon.E[0].effects[0].description",
        behavior="timing",
        evidence_prefix="active duration@",
    ),
    ("Jax", "E"): AbilityAtomQuery(
        source="Jax.E[0].effects[0].description",
        behavior="timing",
        evidence_prefix="active duration@",
    ),
}

_BRAUM_DURATION_QUERY = AbilityAtomQuery(
    source="Braum.E[0].effects[0].leveling[1].modifiers[0]",
    behavior="ability",
    evidence_prefix="Barrier Duration@",
)
_BRAUM_REDUCTION_QUERY = AbilityAtomQuery(
    source="Braum.E[0].effects[0].leveling[0].modifiers[0]",
    behavior="ability",
    evidence_prefix="Damage reduction@",
)
_AMUMU_REDUCTION_CAP_QUERY = AbilityAtomQuery(
    source="Amumu.E[0].effects[0].description",
    behavior="ability",
    evidence_prefix="damage reduction cap@",
)


def _atom_receipt(atom: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the provenance fields that identify one runtime atom."""
    return {
        key: atom[key]
        for key in (
            "atom_id",
            "behavior",
            "source",
            "values",
            "units",
            "evidence",
            "hash",
        )
    }


def _ranked_atom_value(
    atom: Mapping[str, Any], rank: int, *, source: str, unit: str
) -> float:
    """Read one ranked atom value and validate its source unit."""
    units = atom.get("units")
    if not isinstance(units, list) or rank < 1 or rank > len(units):
        raise ValueError(f"ability atom {source!r} has no unit for rank {rank}")
    if str(units[rank - 1]).strip().lower() != unit:
        raise ValueError(
            f"ability atom {source!r} must use {unit!r}, got {units[rank - 1]!r}"
        )
    return ranked_ability_atom_value(atom, rank, source=source)


def _combatant_level(combatant: Any) -> int:
    """Read a level from either a timeline combatant or resolved loadout."""
    level = getattr(combatant, "level", None)
    if level is None:
        level = getattr(getattr(combatant, "request", None), "level", 0)
    return int(level)


def _prose_duration_atom(
    champion: str, champion_data: Mapping[str, Any], slot: str
) -> tuple[float, dict[str, Any]]:
    """Return one validated prose duration atom for a defense window."""
    query = _PROSE_DURATION_QUERIES[(champion, slot)]
    atom = required_ability_atom(champion, champion_data, slot, query=query)
    if atom.get("units") != ["s"]:
        raise ValueError(f"{champion} {slot} defense duration atom must use seconds")
    return ranked_ability_atom_value(atom, 1, source=query.source), _atom_receipt(atom)


def resolve_physical_damage_reduction(
    combatant: Any,
) -> TargetPhysicalDamageReduction | None:
    """Resolve a typed target passive that reduces physical damage."""
    champion_data = getattr(combatant, "champion_data", {})
    champion = str(champion_data.get("name", ""))
    if champion != "Amumu":
        return None
    request = getattr(combatant, "request", None)
    rank = _rank_for(champion, _combatant_level(combatant), request, "E")
    ability = _ability(champion_data, "E")
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
    flat = _ranked_atom_value(
        flat_atom,
        rank,
        source=flat_atom["source"],
        unit="",
    )
    armor_percent = _ranked_atom_value(
        armor_atom,
        rank,
        source=armor_atom["source"],
        unit="% bonus armor",
    )
    magic_resistance_percent = _ranked_atom_value(
        magic_resistance_atom,
        rank,
        source=magic_resistance_atom["source"],
        unit="% bonus magic resistance",
    )
    cap_atom = required_ability_atom(
        champion, champion_data, "E", query=_AMUMU_REDUCTION_CAP_QUERY
    )
    cap_percent = _ranked_atom_value(
        cap_atom,
        1,
        source=_AMUMU_REDUCTION_CAP_QUERY.source,
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
            _atom_receipt(flat_atom),
            _atom_receipt(armor_atom),
            _atom_receipt(magic_resistance_atom),
            _atom_receipt(cap_atom),
        ),
    )


def target_physical_damage_reduction_params(combatant: Any) -> dict[str, float]:
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


def resolve_projectile_defense(combatant: Any) -> ProjectileDefense | None:
    """Resolve one authored champion defensive window."""

    champion_data = getattr(combatant, "champion_data", {})
    champion = str(champion_data.get("name", ""))
    request = getattr(combatant, "request", None)
    options = getattr(request, "champion_options", None)
    options = options if isinstance(options, Mapping) else {}

    if champion == "Braum" and bool(options.get("e_active", False)):
        rank = _rank_for(champion, int(combatant.level), request, "E")
        ability = _ability(champion_data, "E")
        if rank < 1 or ability is None:
            return None
        duration_atom = required_ability_atom(
            champion, champion_data, "E", query=_BRAUM_DURATION_QUERY
        )
        reduction_atom = required_ability_atom(
            champion, champion_data, "E", query=_BRAUM_REDUCTION_QUERY
        )
        source_duration = _ranked_atom_value(
            duration_atom,
            rank,
            source=_BRAUM_DURATION_QUERY.source,
            unit="seconds",
        )
        reduction = (
            _ranked_atom_value(
                reduction_atom,
                rank,
                source=_BRAUM_REDUCTION_QUERY.source,
                unit="%",
            )
            / 100.0
        )
        start, duration = _window(
            options, "e_active_from", "e_active_seconds", source_duration
        )
        return ProjectileDefense(
            kind="braum_unbreakable",
            source="Braum E · Unbreakable",
            start=start,
            duration=duration,
            blocked_sources=_source_selection(options, "e_blocked_skillshots"),
            blocked_event_ids=_source_selection(options, "e_blocked_event_ids"),
            damage_reduction=reduction,
            full_block_first=True,
            source_atoms=(
                _atom_receipt(duration_atom),
                _atom_receipt(reduction_atom),
            ),
        )

    if champion == "Yasuo" and bool(options.get("w_active", False)):
        rank = _rank_for(champion, int(combatant.level), request, "W")
        ability = _ability(champion_data, "W")
        if rank < 1 or ability is None:
            return None
        source_duration, duration_atom = _prose_duration_atom(
            champion, champion_data, "W"
        )
        start, duration = _window(
            options, "w_active_from", "w_active_seconds", source_duration
        )
        return ProjectileDefense(
            kind="yasuo_wind_wall",
            source="Yasuo W · Wind Wall",
            start=start,
            duration=duration,
            blocked_sources=_source_selection(options, "w_blocked_skillshots"),
            blocked_event_ids=_source_selection(options, "w_blocked_event_ids"),
            destroy_projectiles=True,
            source_atoms=(duration_atom,),
        )

    if champion == "Samira" and bool(options.get("w_active", False)):
        rank = _rank_for(champion, int(combatant.level), request, "W")
        ability = _ability(champion_data, "W")
        if rank < 1 or ability is None:
            return None
        source_duration, duration_atom = _prose_duration_atom(
            champion, champion_data, "W"
        )
        start, duration = _window(
            options, "w_active_from", "w_active_seconds", source_duration
        )
        return ProjectileDefense(
            kind="samira_blade_whirl",
            source="Samira W · Blade Whirl",
            start=start,
            duration=duration,
            blocked_sources=_source_selection(options, "w_blocked_skillshots"),
            destroy_projectiles=True,
            source_atoms=(duration_atom,),
        )

    if champion == "Gwen" and bool(options.get("w_active", False)):
        rank = _rank_for(champion, int(combatant.level), request, "W")
        ability = _ability(champion_data, "W")
        if rank < 1 or ability is None:
            return None
        source_duration, duration_atom = _prose_duration_atom(
            champion, champion_data, "W"
        )
        start, duration = _window(
            options, "w_active_from", "w_active_seconds", source_duration
        )
        return ProjectileDefense(
            kind="gwen_hallowed_mist",
            source="Gwen W · Hallowed Mist",
            start=start,
            duration=duration,
            blocked_sources=_source_selection(options, "w_blocked_skillshots"),
            destroy_projectiles=True,
            source_atoms=(duration_atom,),
        )

    if champion == "Fiora" and bool(options.get("w_active", False)):
        rank = _rank_for(champion, int(combatant.level), request, "W")
        ability = _ability(champion_data, "W")
        if rank < 1 or ability is None:
            return None
        source_duration, duration_atom = _prose_duration_atom(
            champion, champion_data, "W"
        )
        start, duration = _window(
            options, "w_active_from", "w_active_seconds", source_duration
        )
        return ProjectileDefense(
            kind="fiora_riposte",
            source="Fiora W · Riposte",
            start=start,
            duration=duration,
            blocked_sources=_source_selection(options, "w_blocked_sources"),
            full_block_all=True,
            requires_skillshot=False,
            source_atoms=(duration_atom,),
        )

    if champion == "Pantheon" and bool(options.get("e_active", False)):
        rank = _rank_for(champion, int(combatant.level), request, "E")
        ability = _ability(champion_data, "E")
        if rank < 1 or ability is None:
            return None
        source_duration, duration_atom = _prose_duration_atom(
            champion, champion_data, "E"
        )
        start, duration = _window(
            options, "e_active_from", "e_active_seconds", source_duration
        )
        return ProjectileDefense(
            kind="pantheon_aegis_assault",
            source="Pantheon E · Aegis Assault",
            start=start,
            duration=duration,
            blocked_sources=_source_selection(options, "e_blocked_skillshots"),
            full_block_all=True,
            source_atoms=(duration_atom,),
        )

    if champion == "Jax" and bool(options.get("e_active", False)):
        rank = _rank_for(champion, int(combatant.level), request, "E")
        ability = _ability(champion_data, "E")
        if rank < 1 or ability is None:
            return None
        source_duration, duration_atom = _prose_duration_atom(
            champion, champion_data, "E"
        )
        start, duration = _window(
            options, "e_active_from", "e_active_seconds", source_duration
        )
        return ProjectileDefense(
            kind="jax_counter_strike",
            source="Jax E · Counter Strike",
            start=start,
            duration=duration,
            full_block_all=True,
            blocks_basic_attacks=True,
            area_damage_reduction=0.25,
            requires_skillshot=False,
            source_atoms=(duration_atom,),
        )

    return None


_ANNUL_ITEM_NAMES = ("Banshee's Veil", "Edge of Night", "Verdant Barrier")


@dataclass(frozen=True, slots=True)
class SpellShieldContract:
    """One resolved spell shield: kernel eligibility + composition."""

    eligibility: SpellShieldEligibility
    composition: SpellShieldComposition
    cooldown_seconds: float = 0.0
    cooldown_atom: dict[str, Any] | None = None
    rearm: SpellShieldRearmClock = SpellShieldRearmClock()

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


def resolve_spell_shield(combatant: Any) -> SpellShieldContract | None:
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


def defense_eligibility(defense: ProjectileDefense | None) -> DefenseEligibility | None:
    """Build the kernel eligibility contract from one defense atom.

    The runtime ProjectileDefense keeps its sourced window/selection
    parsing; the kernel owns the delivery classification and the
    eligibility decision.  ``accepts_unknown`` declares that a defense
    with no delivery filters (Fiora's full block) does not need a
    delivery decision, so an unmarked packet is accepted.
    """
    if defense is None:
        return None
    return DefenseEligibility(
        name=defense.kind,
        window=DefenseWindow(
            start=defense.start,
            until=defense.until,
            source_atoms=defense.source_atoms,
        ),
        selection=SourceSelection(
            blocked_sources=defense.blocked_sources,
            blocked_event_ids=defense.blocked_event_ids,
        ),
        acceptance=DeliveryAcceptance(
            requires_skillshot=defense.requires_skillshot,
            blocks_basic_attacks=defense.blocks_basic_attacks,
            area_damage_reduction=defense.area_damage_reduction,
            accepts_unknown=not (
                defense.requires_skillshot
                or defense.blocks_basic_attacks
                or defense.area_damage_reduction > 0.0
            ),
        ),
        source=SourceReceipt(
            label=str(defense.source or defense.kind),
            url="https://wiki.leagueoflegends.com",
        ),
    )


def defense_composition(defense: ProjectileDefense | None) -> DefenseComposition | None:
    """Build the kernel composition rules from one defense atom.

    Braum E: ``full_block first`` with a one-use budget, later hits
    reduced by the sourced rank value.  Yasuo W: unlimited destruction.
    The other authored defenses (Samira, Gwen, Fiora, Pantheon, Jax)
    keep their existing rules — they are later-P2 recomposition targets.
    """
    if defense is None:
        return None
    full_mode = (
        "all"
        if defense.full_block_all
        else ("first" if defense.full_block_first else "none")
    )
    uses = (
        UseBudget(
            action_mode="full_block",
            uses=1,
            consume="first_eligible",
        )
        if defense.full_block_first
        else None
    )
    return DefenseComposition(
        full_block=FullBlockRule(
            mode=full_mode,
            blocks_true_damage=defense.full_block_all,
        ),
        full_block_uses=uses,
        destroy=DestructionRule(enabled=defense.destroy_projectiles),
        reduction=ReductionRule(
            later_hit_reduction=defense.damage_reduction,
            area_damage_reduction=defense.area_damage_reduction,
            applies_to_true_damage=defense.full_block_all,
        ),
    )


def public_defense(defense: ProjectileDefense | None) -> dict[str, Any] | None:
    """Return a JSON-safe interaction atom for the survival receipt."""

    if defense is None:
        return None
    eligibility = defense_eligibility(defense)
    composition = defense_composition(defense)
    return {
        "kind": defense.kind,
        "source": defense.source,
        "start": round(defense.start, 3),
        "until": round(defense.until, 3),
        "blocked_sources": list(defense.blocked_sources),
        "blocked_event_ids": list(defense.blocked_event_ids),
        "damage_reduction": round(defense.damage_reduction, 6),
        "full_block_first": defense.full_block_first,
        "full_block_all": defense.full_block_all,
        "destroy_projectiles": defense.destroy_projectiles,
        "blocks_basic_attacks": defense.blocks_basic_attacks,
        "area_damage_reduction": round(defense.area_damage_reduction, 6),
        "requires_skillshot": defense.requires_skillshot,
        "source_atoms": [dict(atom) for atom in defense.source_atoms],
        "acceptance": (
            eligibility.acceptance.public_receipt() if eligibility is not None else None
        ),
        "composition": (
            composition.public_receipt() if composition is not None else None
        ),
    }


__all__ = [
    "ProjectileDefense",
    "TargetPhysicalDamageReduction",
    "defense_composition",
    "defense_eligibility",
    "public_defense",
    "public_physical_damage_reduction",
    "resolve_physical_damage_reduction",
    "resolve_projectile_defense",
    "resolve_spell_shield",
    "target_physical_damage_reduction_params",
]
