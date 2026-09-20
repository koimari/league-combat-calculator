"""Ziggs: slot map for the archetype engine.

P (Short Fuse) is invisible to the generic path: its cached leveling carries
ONLY the per-level base values with no AP modifier at all, so the 50% AP ratio
is a module constant from the wiki, and the proc count is the ``passive_procs``
option, its 12-second cooldown being refunded per ability cast so uptime depends
on the rotation.  Row 0 of the "Per-Level Scaling" pair is against champions;
row 1, the 175% vs-structures multiple, is deliberately ignored.
E (Hexplosive Minefield) is multi-hit: one full mine plus ``mines_hit - 1`` at
the "Reduced Damage per Mine" values, clamped at the "Maximum Total Magic
Damage" row.  The generic path counts one mine.
R (Mega Inferno Bomb) is a sweet-spot toggle on ``r_sweet_spot``, "Epicenter
Magic Damage" against the outer ring's "Reduced Damage" row.
Q and W are plain reads pinned to their exact "Magic Damage" attribute, so W's
turret-only "Demolition Threshold" row can never win.
"""

import re
from collections.abc import Mapping
from typing import Any

from ..ability_prose import CachedSentence
from ..binary_roots import data_value, spell_object
from .engine import SlotCtx, build_parser
from .inputs import bool_option, int_option
from .module_helpers import ranked_slot
from .shared_option_keys import PASSIVE_PROCS_OPTION
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named, extract_value
from .slotlib import by_option, proc_damage, simple_damage
from .source_receipts import load_champion_sources

# HARDCODED: verify on patch updates — the wiki-scraped JSON stores
# Short Fuse's per-level base but drops its AP modifier entirely.
# https://wiki.leagueoflegends.com/en-us/Ziggs (Short Fuse: 50% AP)
SHORT_FUSE_AP_RATIO = data_value(spell_object("Ziggs", "ZiggsPassiveBuff"), "APRatio")


_SHORT_FUSE_REFUND = CachedSentence(
    re.compile(
        r"reduced by\s*(?P<values>\d+\s*/\s*\d+\s*/\s*\d+)\s*\(based on level\)",
        re.IGNORECASE,
    ),
    missing="Ziggs P: Short Fuse cooldown refund is missing from the cached source",
)


def _short_fuse_refund_seconds(ability: Mapping[str, Any], level: int) -> float:
    """Read the sourced 4/5/6-second cast refund from passive prose."""
    values = _SHORT_FUSE_REFUND.level_values(ability)
    breakpoint_index = 0 if level < 7 else (1 if level < 13 else 2)
    return values[breakpoint_index]


def _short_fuse_damage(ctx: SlotCtx, ability: dict[str, Any]) -> float:
    """One Short Fuse proc: per-level JSON base + hardcoded 50% AP."""
    base = extract_value(ability, "Per-Level Scaling", ctx.level)
    return base + SHORT_FUSE_AP_RATIO * ctx.stat("ability_power")


_short_fuse_packet = proc_damage(
    per_proc=_short_fuse_damage,
    dmg_type="magic",
    count_option=PASSIVE_PROCS_OPTION,
    default_count=2,
    phase_order_events=True,
)


def _short_fuse(ctx: SlotCtx) -> dict[str, Any] | None:
    """Emit Short Fuse with its sourced timed cooldown/refund contract."""
    ability = ctx.ability()
    entry = _short_fuse_packet(ctx)
    if ability is None or entry is None:
        return entry
    cooldown_values = [
        value
        for modifier in ability.get("cooldown", {}).get("modifiers", [])
        for value in modifier.get("values", [])
    ]
    if not cooldown_values:
        raise ValueError(
            "Ziggs P: Short Fuse cooldown is missing from the cached source"
        )
    entry["armed_procs"] = {
        "arming_slots": ("Q", "W", "E", "R"),
        "max_stacks": 1,
        "cooldown": float(cooldown_values[0]),
        "cooldown_reduction_per_cast": _short_fuse_refund_seconds(ability, ctx.level),
        "armed_at_start": True,
        "requested": ctx.options.get(PASSIVE_PROCS_OPTION) is not None,
    }
    return entry


@ranked_slot
def _hexplosive_minefield(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """E: 1 full mine + (mines_hit - 1) reduced mines, capped by JSON."""

    mines = max(1, int(ctx.option("mines_hit")))
    full = extract_named(ability, "Magic Damage per Mine", rank, ctx.stats, ctx.target)
    reduced = extract_named(
        ability, "Reduced Damage per Mine", rank, ctx.stats, ctx.target
    )
    cap = extract_named(
        ability, "Maximum Total Magic Damage", rank, ctx.stats, ctx.target
    )
    total = min(full + (mines - 1) * reduced, cap)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["event_order_certified"] = "single_hit"
    return entry


OPTIONS = [
    int_option(
        PASSIVE_PROCS_OPTION,
        2,
        minimum=0,
        maximum=10,
        label=(
            "Short Fuse procs; unset derives them from the cached 12s timer "
            "and the level refund each cast takes off it"
        ),
        derives=True,
        rotation={"role": "self_state", "slot": "P"},
    ),
    int_option(
        "mines_hit",
        4,
        minimum=1,
        maximum=11,
        label="E mines hit",
        rotation={"role": "self_state", "slot": "E"},
    ),
    bool_option(
        "r_sweet_spot",
        True,
        label="R hits epicenter (sweet spot)",
        rotation={"role": "irrelevant", "slot": "R"},
    ),
]

ASSUMPTIONS = [
    "Short Fuse structure bonus (175% damage, 87.5% AP vs turrets) not "
    "modeled — champion-fight calculator",
    "Short Fuse proc count is user-set (default 2); its per-ability-cast "
    "cooldown refund (4/5/6s) is applied against the authored cast timeline",
    "Q bounces don't change damage; single explosion assumed to hit",
    "W turret-execute threshold (Demolition) not modeled — turrets only",
    "E slow and W knockback are utility, no damage contribution",
    "Enemy hits 4 E mines by default (1 full + 3 reduced); configurable",
    "R defaults to epicenter (sweet spot) damage; toggle for outer ring",
]

SLOTS = {
    # These reviewed packets are one direct champion hit at the authored cast
    # boundary.  The explicit certification is important to ordered item
    # passives (Eclipse/Muramana/Bastionbreaker): it is not a guessed
    # multi-tick schedule, and E's mine count remains a single aggregate
    # packet under the selected ``mines_hit`` option.
    "Q": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "W": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "E": _hexplosive_minefield,
    "R": by_option(
        "r_sweet_spot",
        {
            True: simple_damage(
                attr="Epicenter Magic Damage",
                dmg_type="magic",
                event_order_certified="single_hit",
            ),
            False: simple_damage(
                attr="Reduced Damage",
                dmg_type="magic",
                event_order_certified="single_hit",
            ),
        },
        default=True,
    ),
    "P": _short_fuse,
}

# Satchel Charge's detonation "deal[s] magic damage to nearby enemies and
# knock[s] them back over 0.5 seconds"; each Hexplosive Minefield mine
# explodes "dealing magic damage and slowing them for 1.5 seconds".
# Bouncing Bomb and Mega Inferno Bomb only explode.  P is the Short Fuse
# empowered basic attack, not an ability event.
MODULE_CC = {"Q": "none", "W": "knockback", "E": "slow", "R": "none", "P": "none"}

parse_abilities = build_parser(SLOTS, "Ziggs", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Ziggs")
