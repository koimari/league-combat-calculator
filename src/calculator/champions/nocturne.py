"""Nocturne — CP10.5 full-entry-reviewed packet module.

E2 DoT fix: E (Unspeakable Horror) prices 4 sourced 0.5s tether ticks
(this module's packet timing declaration).
"""

from .packet_module import build_packet_module

PACKET_SHA256 = "0ce5c515d925ee81726b3430bfa9068b01a64a9901b67361a7f8da766fd561b8"

# Cached kit review.  Q's shadow blade only "deal[s] physical damage to
# enemies hit" — its one "slow" word is the dusk trail "slowly
# disappear[ing]", not a slow applied to anyone.  E's tether ticks for
# magic damage and, unbroken, "the target is feared for a duration while
# being slowed by 90%": the fear is the immobilize the slow rides with.  R
# nearsights, which is not an immobilize and has no kind in the vocabulary
# (the Graves W reading), and its damaging recast dash applies nothing.
# W (spell shield) deals no damage, and P is absent because Umbra Blades is
# an on-hit rider on the auto stream rather than an ability event.
MODULE_CC = {"Q": "none", "E": "fear", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Nocturne",
    PACKET_SHA256,
    packet_tick_fixes={
        "Unspeakable Horror": {
            "count": 4,
            "first_tick": 0.5,
            "tick_interval": 0.5,
            "dot_duration": 2.0,
        }
    },
    # Duskbringer's blade hits each enemy in its line once and Paranoia's
    # recast dash damages once on arrival — the boundary claim that carries
    # MODULE_CC's reviewed answers into the event ledger.  E already
    # authors its own four-tick tether timing above.
    single_hit_slots=frozenset({"Q", "R"}),
    cc_kinds=MODULE_CC,
)
PACKET_SPEC = SLOTS.packet_spec
_ON_HIT_SPECS: dict[str, dict] = {
    "P": {"effectiveness": 1.0, "hits": 1, "triggers": ("on_hit",)},
}

_parse_abilities = parse_abilities


def parse_abilities(*args, **kwargs):
    """Parse abilities, then declare wiki-sourced item on-hit application."""
    result = _parse_abilities(*args, **kwargs)
    for slot, spec in _ON_HIT_SPECS.items():
        entry = result.get(slot) or (result.get("passive") if slot == "P" else None)
        if entry is not None:
            entry["applies_item_on_hits"] = dict(spec)
    return result


# The on-hit declaration above wraps the compiled parser, so the reviewed
# crowd control it carries has to travel with the wrapper: the contract
# proves the module's declaration and its parser's wiring are one dict.
parse_abilities.cc_kinds = _parse_abilities.cc_kinds


MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
