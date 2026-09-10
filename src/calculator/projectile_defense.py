"""The seven champion defensive windows: what arms one, what it accepts, what it does to a hit."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .ability_atoms import atom_receipt, required_ability_atom
from .defense_composition import (
    DefenseComposition,
    DestructionRule,
    FullBlockRule,
    ReductionRule,
    UseBudget,
)
from .delivery_eligibility import (
    DefenseEligibility,
    DeliveryAcceptance,
    SourceSelection,
)
from .delivery_facts import CombatantFacts, DefenseWindow
from .interaction_atoms import (
    BRAUM_DURATION_QUERY,
    BRAUM_REDUCTION_QUERY,
    PROSE_DURATION_WINDOWS,
    cached_ability,
    prose_duration_atom,
    rank_for,
    ranked_atom_value,
    requested_window,
    source_selection,
)
from .state_timeline import SourceReceipt


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


def resolve_projectile_defense(combatant: CombatantFacts) -> ProjectileDefense | None:
    """Resolve one authored champion defensive window."""

    champion_data = getattr(combatant, "champion_data", {})
    champion = str(champion_data.get("name", ""))
    request = getattr(combatant, "request", None)
    options = getattr(request, "champion_options", None)
    options = options if isinstance(options, Mapping) else {}

    if champion == "Braum" and bool(options.get("e_active", False)):
        rank = rank_for(champion, int(combatant.level), request, "E")
        ability = cached_ability(champion_data, "E")
        if rank < 1 or ability is None:
            return None
        duration_atom = required_ability_atom(
            champion, champion_data, "E", query=BRAUM_DURATION_QUERY
        )
        reduction_atom = required_ability_atom(
            champion, champion_data, "E", query=BRAUM_REDUCTION_QUERY
        )
        source_duration = ranked_atom_value(
            duration_atom,
            rank,
            source=BRAUM_DURATION_QUERY.source,
            unit="seconds",
        )
        reduction = (
            ranked_atom_value(
                reduction_atom,
                rank,
                source=BRAUM_REDUCTION_QUERY.source,
                unit="%",
            )
            / 100.0
        )
        start, duration = requested_window(
            options, "e_active_from", "e_active_seconds", source_duration
        )
        return ProjectileDefense(
            kind="braum_unbreakable",
            source="Braum E · Unbreakable",
            start=start,
            duration=duration,
            blocked_sources=source_selection(options, "e_blocked_skillshots"),
            blocked_event_ids=source_selection(options, "e_blocked_event_ids"),
            damage_reduction=reduction,
            full_block_first=True,
            source_atoms=(
                atom_receipt(duration_atom),
                atom_receipt(reduction_atom),
            ),
        )

    window = PROSE_DURATION_WINDOWS.get(champion)
    if window is None:
        return None
    slot, fields = window
    key = slot.lower()
    if not bool(options.get(f"{key}_active", False)):
        return None
    rank = rank_for(champion, int(combatant.level), request, slot)
    ability = cached_ability(champion_data, slot)
    if rank < 1 or ability is None:
        return None
    source_duration, duration_atom = prose_duration_atom(champion, champion_data, slot)
    start, duration = requested_window(
        options, f"{key}_active_from", f"{key}_active_seconds", source_duration
    )
    selections = {
        name: source_selection(options, fields[name])
        for name in ("blocked_sources", "blocked_event_ids")
        if name in fields
    }
    return ProjectileDefense(
        start=start,
        duration=duration,
        source_atoms=(duration_atom,),
        **{**fields, **selections},
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
