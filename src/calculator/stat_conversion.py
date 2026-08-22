"""How a champion's own kit rewrites a stat the item fold hands it.

A conversion is not a slot: it prices nothing the enemy takes and it
belongs where item stats are folded, not where casts are parsed. This leaf
owns the shape and nothing else — each champion module declares its own
``MODULE_STAT_CONVERSION``, ``stats.calculate_total_stats`` is the one
place that applies it, and the numbers stay in the champion's module.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BonusHealthConversion:
    """Bonus health the champion may not keep, and what it becomes instead.

    Pyke's Gift of the Drowned Ones is the whole vocabulary today: his
    maximum health cannot rise except by growth, and every point of bonus
    health he is denied returns as ``attack_damage_ratio`` of itself in
    bonus attack damage. The wiki's own note settles the order — anything
    that raises the health first (Warmog's Vitality, Overgrowth) raises the
    attack damage with it — so the fold converts the completed bonus
    health, after every multiplier and rune grant.
    """

    source: str
    attack_damage_ratio: float
