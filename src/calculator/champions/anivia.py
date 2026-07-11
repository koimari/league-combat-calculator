"""Anivia — slot map for the archetype engine.

Why each slot is non-generic:
- Q (Flash Frost) must read "Total Magic Damage" (pass-through +
  detonation combined) — an attribute override, not a classifier pick.
- E (Frostbite) must read "Enhanced Damage" (target assumed Chilled).
- R (Glacial Storm) is a two-phase toggle DoT: the first 1.5 s (3 ticks
  at 0.5 s) deal the initial per-tick damage, everything after deals the
  empowered value. Duration comes from the ``r_duration`` option
  (default 5 s, floored at 1.5 s so the initial phase always completes),
  and the cooldown is pinned to 999 s so the fight engine casts it
  exactly once per fight.
- W (utility wall) and the passive (resurrection) deal no damage and are
  deliberately absent from the slot map.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from .engine import build_parser
from .slotlib import simple_damage, toggle_dot

OPTIONS = [
    {
        "key": "r_duration",
        "type": "float",
        "default": 5.0,
        "label": "R duration (seconds)",
        "min": 1.5,
        "max": 30,
        "step": 0.5,
    },
]

ASSUMPTIONS = [
    "Q hits both pass-through and detonation (total damage used)",
    "E target is always Chilled (empowered damage used)",
    "R first 1.5s uses initial tick damage, remaining uses fully-formed tick damage",
    "W skipped (utility wall, no damage)",
    "Passive skipped (resurrection only, no damage)",
]

SLOTS = {
    "Q": simple_damage(attr="Total Magic Damage", dmg_type="magic"),
    "E": simple_damage(attr="Enhanced Damage", dmg_type="magic"),
    "R": toggle_dot(
        phases=[
            ("Magic Damage per Tick", 3),
            ("Empowered Damage per Tick", None),
        ],
        duration_option=("r_duration", 5.0),
        min_duration=1.5,
        cooldown=999.0,
        dmg_type="magic",
    ),
}

parse_abilities = build_parser(SLOTS, "Anivia")
