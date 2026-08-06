"""Kayle — full-entry reviewed CP10.3 module.

Option keys consumed by the shared parser: "p_exalted", "e_empowered".

E8d ally-support: W (Celestial Blessing) heals the selected teammate.  The
event is authored by the engine's ally-support scanner from the cached W
leveling (Heal 55-155 + 25% AP; scope one_teammate) at the W cast time; the
module declares W in SLOTS so the fight rotation casts it.
"""

from .reviewed_batch_03 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Kayle")
MODULE_COVERAGE = {slot: "modeled" for slot in "PQWER"}
REVIEW_STATUS = "reviewed_module"
