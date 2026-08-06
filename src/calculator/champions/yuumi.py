"""Yuumi — CP10.10 full-entry-reviewed packet module.

E8d ally-support: E (Zoomies) grants the caster a shield (Shield 65-165 +
40% AP; scope self per the cached "grants herself a shield" prose).  R
(Final Chapter) heals allies hit by the waves (Heal per Hit x5 == Total
Heal, scope one_teammate).  Both events are authored by the engine's
ally-support scanner from cached leveling at the cast times; the module
declares E/R in SLOTS so the fight rotation casts them.  The attached-bonus
anchor transfer of E ("Affects the Anchor instead of Yuumi") is a scope
detection the scanner does not express — see E8d reply for the missing hook.
"""

from .reviewed_batch_10 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Yuumi")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
