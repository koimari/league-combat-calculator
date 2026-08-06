"""Seraphine — CP10.7 full-entry-reviewed packet module.

E8d ally-support: W (Surround Sound) shields the caster and every selected
teammate (Shield Strength 60-140 + 20% AP; scope self_and_all_teammates).
The event is authored by the engine's ally-support scanner from cached
leveling at the W cast time; the module declares W in SLOTS so the fight
rotation casts it.  W's conditional pulse heal ("% of target's missing
health") is dynamic and is NOT emitted as a flat packet — it requires the
target's live missing-health state, which the support scanner does not carry.
"""

from .reviewed_batch_07 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Seraphine")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
