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

Roadmap session 4 (2026-08-20): closes both of Lulu's out_of_scope slots
(W, R). Both were already wired via the reviewed packet's ``no_damage``
kind (``static/reviewed-packets.json``, Lulu W/R -- see
``build_packet_module``'s ``elif spec.get("kind") == "no_damage"``
branch) -- ``MODULE_COVERAGE`` was simply stale, still reading
"out_of_scope" for slots the packet review had already closed to an
explicit zero-damage row, the identical stale-label pattern
Anivia-W/Alistar-P were corrected under in the prior roadmap session.
Reclassified W -> no_damage, R -> no_damage; no behavior change.

  - W (Whimsy): the cached ability's only leveling rows are "Disable
    Duration" (enemy polymorph/silence) and "Bonus Attack Speed" /
    "Effect Duration" (ally/self buff) -- no damage attribute anywhere
    (data/champions.json Lulu W). Cross-checked against the atoms
    capture (data/atoms/lulu.atoms.json: LuluW/LuluWBuff/LuluWDebuff all
    carry ``damage_type: null``). The enemy-cast branch already carries
    its polymorph control event via ``with_control_event`` below; the
    ally-cast attack-speed/movement-speed buff is an ally-coupled state
    grant with no enemy-damage or engine-consumed shield/heal attribute
    to price (the Kai'Sa-R precedent: sourced, but nothing to model).
  - R (Wild Growth): the cached ability's only leveling rows are "Bonus
    Health" (ally/self buff) and "Slow" (enemy debuff) -- no damage
    attribute (data/champions.json Lulu R). Cross-checked against the
    atoms capture (LuluR/LuluRSlow: ``damage_type: null``; LuluR's
    ``damage.aoe`` atom is a structural AoE-zone tag off the 1s knockup,
    not a priced formula). The knockup is CC with no damage component
    and the bonus-health/size grant is an ally-coupled state buff, same
    as W's ally cast -- nothing to price.
"""

from typing import Any

from .engine import ONHIT, SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import extract_named, on_hit_entry, with_control_event

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
    ap = float(ctx.stats.get("ability_power", 0.0))
    per_bolt = per_bolt_flat + _PIX_BOLT_AP_RATIO * ap
    return on_hit_entry(
        ability.get("name", "Pix, Faerie Companion"),
        per_bolt * bolts,
        "magic",
    )


_pix_bolts.phase = ONHIT

SLOTS = dict(SLOTS)
SLOTS["P"] = _pix_bolts
SLOTS["W"] = with_control_event(
    SLOTS["W"],
    kind="polymorph",
    duration_attr="Disable Duration",
)
parse_abilities = build_parser(SLOTS, "Lulu")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Pix, Faerie Companion) fires lulu_pix_bolts (default 3) magic "
    "bolts on each basic attack; each bolt deals the per-level row "
    "(5 : 39 by level) + 5% AP (module constants; the AP ratio is wiki "
    "prose). The second Per-Level Scaling row is the full 3-bolt total "
    "(15 : 117 + 15% AP).",
    "W (Whimsy) has no sourced damage/heal/shield number: the enemy cast "
    "is polymorph + movement slow (CC, no damage), the ally/self cast is "
    "a bonus attack-speed/movement-speed buff (state) -- explicit "
    "no_damage row (roadmap session 4: reclassified from out_of_scope, "
    "no behavior change)",
    "R (Wild Growth) has no sourced damage/heal/shield number: the 1s "
    "knockup is CC with no damage component and the bonus-health/size "
    "grant is an ally-coupled state buff -- explicit no_damage row "
    "(roadmap session 4: reclassified from out_of_scope, no behavior "
    "change)",
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
    "P": "modeled",
    "Q": "modeled",
    "W": "no_damage",
    "E": "modeled",
    "R": "no_damage",
}
REVIEW_STATUS = "reviewed_module"
