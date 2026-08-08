"""Quinn — CP10.6 full-entry-reviewed packet module.

E5-2 fix — Harrier (P): the reviewed packet declared the passive
no_damage/out_of_scope even though the wiki carries a sourced on-hit
formula — "Quinn's basic attacks on-hit against Harrier targets are
empowered to consume the mark to deal 15 : 132.35 (based on level)
(+ 40% bonus AD) bonus physical damage" (data/champions.json P "Bonus
Physical Damage" row) — while equivalent on-hit passives (Nautilus P,
Poppy P) are modeled.  Harrier is now an on-hit entry priced at the
per-level flat plus 40% bonus AD per marked-target auto.
"""

from .packet_module import build_packet_module
from .engine import ONHIT, SlotCtx, build_parser
from .slotlib import extract_named, on_hit_entry

PACKET_SHA256 = "a88925854e27a0548631207e5f283df6a0a369c6249f4ded272801230c801852"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Quinn", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec


def _harrier(ctx: SlotCtx):
    """P: on-hit bonus physical damage against Harrier-marked targets."""
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
    per_hit = extract_named(
        ability, "Bonus Physical Damage", ctx.level, ctx.stats, ctx.target
    )
    return on_hit_entry(ability.get("name", "Harrier"), per_hit, "physical")


_harrier.phase = ONHIT

SLOTS = dict(SLOTS)
SLOTS["P"] = _harrier
parse_abilities = build_parser(SLOTS, "Quinn")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Harrier) prices the wiki's on-hit row: 15 : 132.35 (based on "
    "level) (+ 40% bonus AD) bonus physical damage when a basic attack "
    "consumes the Harrier mark (data/champions.json P 'Bonus Physical "
    "Damage'), modeled like Nautilus and Poppy on-hit passives.",
    "The Harrier mark requires Quinn's Q/E/R or Valor's periodic marking "
    "first; the on-hit is priced per auto against the marked target.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
