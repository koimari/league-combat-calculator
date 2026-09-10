"""What happens to an event a defense accepted.

:class:`UseBudget` (finite uses), :class:`FullBlockRule` (first valid hit or
all), :class:`DestructionRule` and :class:`ReductionRule` (later-hit and area
reduction), grouped per defense in :class:`DefenseComposition`.  They decide
WHAT happens to an eligible event; the survival walk keeps the exact applied
semantics (first block then reduce for Braum E, destroy for Yasuo W).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .delivery_classes import action_flag
from .delivery_facts import PacketFacts
from .state_timeline import SourceReceipt


@dataclass(frozen=True, slots=True)
class UseBudget:
    """Finite-use declaration for one applied action.

    ``uses`` None means unlimited (Yasuo's destruction).  ``consume``
    ``"first_eligible"`` spends the budget on the first eligible event
    (Braum's single full block); ``"each_eligible"`` would spend per
    event; ``"per_cast"`` (the spell-shield lifecycle) spends once per
    cast identity — one shield use blocks ONE hostile ability instance,
    and every later packet of the same cast follows the same block
    decision without spending again.
    """

    action_mode: str
    uses: int | None = None
    consume: Literal["first_eligible", "each_eligible", "per_cast"] = "first_eligible"
    source: SourceReceipt | None = None

    def __post_init__(self) -> None:
        """Fail closed on an impossible budget declaration."""
        if self.uses is not None and self.uses < 1:
            raise ValueError(
                f"UseBudget for {self.action_mode!r}: uses must be >= 1 or "
                f"None (unlimited), got {self.uses!r}"
            )
        if self.consume not in ("first_eligible", "each_eligible", "per_cast"):
            raise ValueError(
                f"UseBudget for {self.action_mode!r}: unknown consume policy "
                f"{self.consume!r}"
            )

    def initial_remaining(self) -> int | None:
        """The starting remaining count (None = unlimited)."""
        return self.uses

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe budget receipt."""
        return {
            "action_mode": self.action_mode,
            "uses": self.uses,
            "consume": self.consume,
            "source": self.source.public() if self.source is not None else None,
        }


@dataclass(frozen=True, slots=True)
class FullBlockRule:
    """Full-block declaration: ``"first"`` (Braum) or ``"all"`` (Fiora,
    Pantheon, Jax).  ``blocks_true_damage`` is False for first-hit rules
    (Braum E does not block true damage) and True for all-hit rules.
    """

    mode: Literal["none", "first", "all"] = "none"
    blocks_true_damage: bool = False
    source: SourceReceipt | None = None

    def __post_init__(self) -> None:
        """Fail closed on an unknown full-block mode."""
        if self.mode not in ("none", "first", "all"):
            raise ValueError(
                f"FullBlockRule: unknown mode {self.mode!r} "
                "(must be 'none', 'first', or 'all')"
            )

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe rule receipt."""
        return {
            "mode": self.mode,
            "blocks_true_damage": self.blocks_true_damage,
            "source": self.source.public() if self.source is not None else None,
        }


@dataclass(frozen=True, slots=True)
class DestructionRule:
    """Projectile-destruction declaration (Yasuo W)."""

    enabled: bool = False
    source: SourceReceipt | None = None

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe rule receipt."""
        return {
            "enabled": self.enabled,
            "source": self.source.public() if self.source is not None else None,
        }


@dataclass(frozen=True, slots=True)
class ReductionRule:
    """Later-hit reduction (Braum E after the first full block) and the
    area-ability reduction (Jax Counter Strike).  ``applies_to_true_damage``
    False keeps true damage untouched (Braum).
    """

    later_hit_reduction: float = 0.0
    area_damage_reduction: float = 0.0
    applies_to_true_damage: bool = False
    source: SourceReceipt | None = None

    def reduction_for(self, action: PacketFacts) -> float:
        """A defense with no area rule reduces area-marked skillshots with its
        later-hit reduction: Braum's shield intercepts Trueshot Barrage in-game
        (wiki: "intercepts all incoming hostile projectiles")."""
        if self.area_damage_reduction > 0.0 and action_flag(action, "area_damage"):
            return self.area_damage_reduction
        return self.later_hit_reduction

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe rule receipt."""
        return {
            "later_hit_reduction": round(self.later_hit_reduction, 6),
            "area_damage_reduction": round(self.area_damage_reduction, 6),
            "applies_to_true_damage": self.applies_to_true_damage,
            "source": self.source.public() if self.source is not None else None,
        }


@dataclass(frozen=True, slots=True)
class DefenseComposition:
    """The declared applied actions for one defense's eligible events.

    Kept separate from eligibility: an eligible event is destroyed
    (Yasuo), fully blocked (Braum first / Fiora, Pantheon, Jax all), or
    reduced (Braum later hits / Jax area).  The survival walk applies
    these exactly as today.
    """

    full_block: FullBlockRule = FullBlockRule()
    full_block_uses: UseBudget | None = None
    destroy: DestructionRule = DestructionRule()
    reduction: ReductionRule = ReductionRule()

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe composition receipt."""
        return {
            "full_block": self.full_block.public_receipt(),
            "full_block_uses": (
                self.full_block_uses.public_receipt()
                if self.full_block_uses is not None
                else None
            ),
            "destroy": self.destroy.public_receipt(),
            "reduction": self.reduction.public_receipt(),
        }


def initial_full_block_uses(composition: DefenseComposition) -> int | None:
    """The defense's starting full-block budget (None = unlimited)."""
    if composition.full_block_uses is None:
        return None
    return composition.full_block_uses.initial_remaining()
