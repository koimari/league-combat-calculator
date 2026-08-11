"""Lulu — CP10.4 full-entry-reviewed packet module.

E8d: E (Help, Pix!) Shield Strength is emitted as an ally-support event
by the support scanner.

P1-2 fix — P (Pix, Faerie Companion) becomes a modeled ONHIT slot: Pix
fires a barrage of ``lulu_pix_bolts`` (default 3, wiki prose) magic
bolts at the target whenever Lulu basic-attacks on-attack; each bolt
deals the per-level "Per-Level Scaling" row (5 : 39 by level) + 5% AP
(the AP ratio is prose in the cached P description; the second
Per-Level Scaling row is the 3-bolt total 15 : 117 + 15% AP).  The
on-hit entry prices bolts x per-bolt so reducing the barrage keeps the
sourced per-bolt row exact.
"""

from typing import Any

from .engine import ONHIT, SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import extract_named, on_hit_entry

# HARDCODED: verify on patch updates — the 3-bolt barrage and each bolt's
# 5% AP ratio are wiki P prose; the JSON carries the per-bolt and
# 3-bolt-total flat per-level rows.
_PIX_BOLTS_DEFAULT = 3
_PIX_BOLT_AP_RATIO = 0.05

PACKET_SHA256 = "2dcdd74eafe747d8fbd7233f3202b76fca9be9d6250a336ce0fe7f8ef2f2f1e1"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Lulu", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec


def _pix_bolts(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Pix's 3-bolt barrage on basic attacks (per-bolt row x count)."""
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
    bolts = min(max(int(ctx.options.get("lulu_pix_bolts", _PIX_BOLTS_DEFAULT)), 0), 3)
    if bolts <= 0:
        return None
    per_bolt_flat = extract_named(
        ability, "Per-Level Scaling", ctx.level, ctx.stats, ctx.target
    )
    ap = float(ctx.stat("ability_power"))
    per_bolt = per_bolt_flat + _PIX_BOLT_AP_RATIO * ap
    return on_hit_entry(
        ability.get("name", "Pix, Faerie Companion"),
        per_bolt * bolts,
        "magic",
    )


_pix_bolts.phase = ONHIT

SLOTS = dict(SLOTS)
SLOTS["P"] = _pix_bolts
parse_abilities = build_parser(SLOTS, "Lulu")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Pix, Faerie Companion) fires lulu_pix_bolts (default 3) magic "
    "bolts on each basic attack; each bolt deals the per-level row "
    "(5 : 39 by level) + 5% AP (module constants; the AP ratio is wiki "
    "prose). The second Per-Level Scaling row is the full 3-bolt total "
    "(15 : 117 + 15% AP).",
]
OPTIONS.append(
    {
        "key": "lulu_pix_bolts",
        "type": "int",
        "default": _PIX_BOLTS_DEFAULT,
        "min": 0,
        "max": 3,
        "label": "Pix bolts per basic attack",
    }
)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "E"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
