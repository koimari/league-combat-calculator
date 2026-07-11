"""Aatrox — slot map for the archetype engine.

Why each slot is non-generic:
- R (World Ender) grants bonus AD as a PERCENTAGE of total AD — a
  ``stat_buff`` in percent_of mode (BUFF phase, so Q/W scale off the
  buffed AD).
- Q (The Darkin Blade) is three sequential casts with individually
  named damage attributes, summed by ``multi_hit_sum``; the
  ``sweetspot`` option (default True) picks the sweetspot triad over
  the normal-cast triad via ``by_option``.
- W (Infernal Chains) hits twice — the "Total Damage" attribute
  (initial + pull-back combined) instead of the single-hit
  "Physical Damage" the classifier would find.
- P (Deathbringer Stance) is on-hit magic damage as a per-LEVEL
  percentage of target max health — ``on_hit_pct_health`` with
  scale="level".
- E (Umbral Dash) is a dash with healing amp only — no damage, absent
  from the slot map.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from .engine import build_parser
from .slotlib import (
    by_option,
    multi_hit_sum,
    on_hit_pct_health,
    simple_damage,
    stat_buff,
)

_Q_SWEETSPOT_ATTRS = [
    "First Sweetspot Damage",
    "Second Sweetspot Damage",
    "Third Sweetspot Damage",
]
_Q_NORMAL_ATTRS = [
    "First Cast Damage",
    "Second Cast Damage",
    "Third Cast Damage",
]

OPTIONS = [
    {"key": "sweetspot", "type": "bool", "default": True, "label": "Q Sweetspot hits"},
]

ASSUMPTIONS = [
    "Assumed R is always active",
    "W always hits both initial and pull-back damage",
]

SLOTS = {
    "R": stat_buff(
        "Bonus Attack Damage",
        "bonus_attack_damage",
        mode="percent_of",
        percent_of="attack_damage",
        apply_to=("attack_damage", "bonus_attack_damage"),
    ),
    "Q": by_option(
        "sweetspot",
        {
            True: multi_hit_sum(_Q_SWEETSPOT_ATTRS, dmg_type="physical"),
            False: multi_hit_sum(_Q_NORMAL_ATTRS, dmg_type="physical"),
        },
        default=True,
    ),
    "W": simple_damage(attr="Total Damage", dmg_type="physical"),
    "P": on_hit_pct_health("Max Health Damage", "magic", scale="level"),
}

parse_abilities = build_parser(SLOTS, "Aatrox")
