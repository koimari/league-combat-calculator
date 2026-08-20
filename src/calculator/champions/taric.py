"""Taric — CP10.8 full-entry-reviewed packet module.

Q (Starlight's Touch) heals himself and nearby allies per stocked charge.
The cached Q leveling exposes only "Maximum Charges", so the ally-support
scanner cannot author it and does not try; the E1 self-healing rule prices
the sourced stock (238.1 at level 18 with no items) and the participant
timeline fans that one event out to the selected allies — the
``self_healing_rule`` channel this module declares.

W (Bastion) shields "himself and the target allied champion" for "7 / 8 / 9
/ 10 / 11% of target's maximum health", each recipient off their own.  The
scan holds one recipient's stats — the caster's — so the shield is priced
from Taric's own maximum health (256.08 at rank 5, level 18, no items) and
granted to Taric alone; the ally copy needs the roster the scan does not
carry, and granting it Taric's number instead would be a fabrication.  The
passive's "6 : 10% of Taric's armor" tether bonus is unpriced.

P (Bravado) is ``modeled``: the sourced on-attack bonus (93.0 magic at level
18 with no bonus armor) rides the two attacks an ability cast empowers.

R (Cosmic Radiance) stays ``out_of_scope`` on the invulnerability axis: 2.5
seconds in which the team takes no damage at all has no engine channel — the
model has no damage-immunity window, only shields and heals.
"""

from typing import Any

from .engine import ONHIT, SlotCtx
from .healing_contract import declare_healing_rule
from .packet_module import build_packet_module
from .slotlib import extract_named, on_hit_entry, simple_damage

PACKET_SHA256 = "c4661e1dfa5a63e1d512d64efc3bbb6cfb5e5d22f3c5d3e08c363f4d5c672cb4"

# Bravado empowers "his next two basic attacks within 5 seconds" after each
# ability cast, so one cast is worth two attacks — the disclosed default.
_BRAVADO_ATTACKS_PER_CAST = 2


def _bravado(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: bonus magic damage on the attacks an ability cast empowers."""
    ability = ctx.ability()
    if ability is None:
        return None
    per_hit = extract_named(
        ability, "Per-Level Scaling", ctx.level, ctx.stats, ctx.target, level=ctx.level
    )
    if per_hit <= 0:
        return None
    attacks = max(0, int(ctx.option("p_empowered_attacks")))
    entry = on_hit_entry(ability.get("name", "Bravado"), per_hit, "magic")
    entry["on_hit"]["max_procs"] = attacks
    entry["detail"] = (
        f"{attacks} empowered attack(s) of {per_hit:.2f} bonus magic damage "
        "(25 : 101 based on level + 15% bonus armor); the 100% total attack "
        "speed those attacks gain and the 1 : 2s cooldown refund they pay "
        "have no engine channel"
    )
    return entry


_bravado.phase = ONHIT

# Reviewed crowd control, read from the cached kit: E (Dazzle) "projects a
# beam of starlight in the target direction that deals magic damage to
# enemies hit and stuns them for 1.5 seconds".  Q, W and R deal no damage
# — heal, shield and invulnerability — and P is an attack-stream rider, so
# E is the whole of this kit's reviewable control.
MODULE_CC = {"E": "stun"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Taric",
    PACKET_SHA256,
    slot_parsers={
        # One beam, one blow, so the row is a hit the ledger can time.
        "E": simple_damage(
            attr="Magic Damage",
            dmg_type="magic",
            ranks="rank",
            source=("E", 0),
            event_order_certified="single_hit",
        ),
        "P": _bravado,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = list(OPTIONS) + [
    {
        "key": "p_empowered_attacks",
        "type": "int",
        "default": _BRAVADO_ATTACKS_PER_CAST,
        "min": 0,
        "max": 10,
        "label": "Bravado attacks landed",
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Bravado) prices the sourced on-attack bonus (25 : 101 based on level "
    "+ 15% bonus armor) on the two attacks one ability cast empowers "
    "(selectable); the 100% total attack speed and the 1 : 2s basic-ability "
    "cooldown refund those attacks carry have no engine channel.",
]
MODULE_COVERAGE = {
    slot: ("out_of_scope" if slot == "R" else "modeled") for slot in "PQWER"
}
COVERAGE_CHANNELS = {"Q": ("self_healing_rule",)}

SELF_HEALING_RULE = declare_healing_rule("Taric")
