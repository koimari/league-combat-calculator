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

# P4: the Harrier CRIT boundary — the bonus is priced NON-crit because
# no pinned source states it crits: the pinned cache (rev 4009372) and
# the live wiki carry no crit sentence for the bonus (the wiki's general
# rule: on-hit damage does not crit unless stated); the historical
# "can critically strike" note was REMOVED 2020-08-30 (rev 3109549); the
# binary has no crit coefficient for the passive.  The degraded P
# cooldown row (values [0,0,0], units "7 : 2.56 (based on critical
# strike chance)") is the mark-interval scaling (7s at 0% crit ->
# 2.56s at 100%), a mark-COOLDOWN mechanic, not a damage term — pinned
# so a future fixed row forces re-review (the fail-closed staleness
# gate).  If a pinned source ever states the empowered attack crits,
# the engine's on_hit crit_effectiveness wiring is the pre-specified
# flip-switch.
_HARRIER_CRIT_BOUNDARY = "non_crit"

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
    "P4 CRIT BOUNDARY (named fail-closed): the Harrier bonus is priced "
    "NON-crit — no pinned source states it crits (the pinned cache rev "
    "4009372 and the live wiki carry no crit sentence; the wiki's "
    "general rule is on-hit damage does not crit unless stated; the "
    "historical 'can critically strike' note was removed 2020-08-30; "
    "the binary has no crit coefficient).  _HARRIER_CRIT_BOUNDARY = "
    "'non_crit' pins it; a future sourced statement flips the engine's "
    "pre-specified on_hit crit_effectiveness wiring.",
    "The degraded P cooldown row (values [0,0,0], units '7 : 2.56 "
    "(based on critical strike chance)') is the mark-interval scaling "
    "(7s at 0% crit -> 2.56s at 100%), a mark-COOLDOWN mechanic not "
    "priced as damage; the row's degraded shape is pinned so a future "
    "fixed row forces re-review.",
    "Harrier deals 75 bonus physical damage against monsters (the "
    "cached effects[2] + the binary BonusMonsterDmg 75.0) — not priced "
    "(no monster-target kind in the 1v1 model; named boundary).",
    "Behind Enemy Lines (R-active) disables Harrier and removes all "
    "marks (cached effects[3]) — not gated in the model (named "
    "boundary; the on-hit is unconditional).",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
