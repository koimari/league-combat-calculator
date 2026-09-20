"""Morgana: packet module over two multi-instance casts.

W (Tormented Shadow) prices all ten storm ticks, on cast and every 0.5 seconds
over 5 seconds: the "Maximum Damage Per Tick" row times ten is the cached
"Maximum Total Damage" at every rank.
R (Soul Shackles) prices the initial hit and the same magic damage again when
the 3-second tether breaks, the cached "Total Magic Damage" being exactly twice
the "Magic Damage" row.
Q (Dark Binding) is a single-instance read.
E (Black Shield) deals no damage but is modeled: the support scanner prices its
cached "Magic Shield Strength" row and the ledger absorbs it as an ordinary
pool, the magic-only restriction and the control immunity being the boundary.
P (Soul Siphon) heals Morgana for 18% of the post-mitigation damage her
abilities deal, authored by ``derive_self_healing``.  The slot itself is a
zero-damage row, and its coverage is declared through ``COVERAGE_CHANNELS``
rather than a hand-written table.
"""

from functools import partial
from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from ..damage_event_row import event_damage as _row_damage
from ..healing_helpers import HealAnchor, heal_from_damage
from .engine import SlotCtx
from .healing_contract import SelfHealCtx, self_healing_rule
from .module_helpers import ranked_slot
from .packet_module import build_packet_module
from .shared_mechanics import innate_zero_row
from .slot_cc import CC_PER_PART
from .slot_control import with_control
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named, extract_value

_MORGANA_W_SPELL = spell_object("Morgana", "MorganaW")
_W_TICK_INTERVAL = data_value(_MORGANA_W_SPELL, "TickRate")
_W_DURATION = data_value(_MORGANA_W_SPELL, "WDuration")
_W_TICKS = int(_W_DURATION / _W_TICK_INTERVAL)
# R tether length, rooted in MorganaR.ChainDuration; the cached R prose
# corroborates the three-second fracture window.
_R_TETHER_SECONDS = data_value(spell_object("Morgana", "MorganaR"), "ChainDuration")


@ranked_slot
def _tormented_shadow(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """W: 10 ticks of Maximum Damage Per Tick == Maximum Total Damage."""

    per_tick = extract_named(
        ability, "Maximum Damage Per Tick", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        per_tick * _W_TICKS,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            per_tick,
            count=_W_TICKS,
            time_offset=0.0,
            hit_interval=_W_TICK_INTERVAL,
        ),
    )
    entry["dot_duration"] = _W_DURATION
    entry["detail"] = (
        f"{_W_TICKS} sourced {_W_TICK_INTERVAL:g}s-interval ticks "
        f"(Maximum Damage Per Tick x{_W_TICKS} == Maximum Total Damage)"
    )
    return entry


@ranked_slot
def _soul_shackles(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """R: initial hit + the same damage again at the 3s tether break."""

    initial = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        initial * 2,
        "magic",
    )
    # The two hits apply two different controls — the shackling slows by
    # 20% for the tether, and only the unbroken tether "become[s] stunned
    # for a duration" — so R's kinds are per part rather than per slot
    # and are authored here instead of in MODULE_CC.
    entry["parts"] = (
        DamagePart(
            "magic",
            initial,
            time_offset=0.0,
            cc_kind="slow",
        ),
        DamagePart(
            "magic",
            initial,
            time_offset=_R_TETHER_SECONDS,
            cc_kind="stun",
            cc_duration=extract_value(ability, "Stun Duration", rank),
        ),
    )
    entry["cc_reviewed"] = True
    entry["dot_duration"] = _R_TETHER_SECONDS
    entry["detail"] = (
        f"initial hit + the same {initial:.6g} magic damage at the "
        f"{_R_TETHER_SECONDS:g}s tether break (Magic Damage x2 == "
        "Total Magic Damage)"
    )
    return entry


def _soul_siphon(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: self-heal passive with no enemy damage (this module authors it)."""

    return innate_zero_row(
        ctx,
        detail=(
            "Soul Siphon heals Morgana for 18% of the post-mitigation "
            "damage dealt by her abilities (authored by this module's "
            "derive_self_healing rule); the passive "
            "itself deals no enemy damage."
        ),
    )


PACKET_SHA256 = "5cc8fcb312de2d1d31c8b63157dac32a85424fa0decca7a8f1ac4ac94d689a9d"


# Cached kit review: Q's sphere damages the first enemy hit "and root[s]
# them for a duration"; W's desecrated soil only damages.  R applies two
# controls, one per part, and declares them on its parts
# (``_soul_shackles``).  E shields an ally and P heals Morgana.
MODULE_CC = {"Q": "root", "W": "none", "R": CC_PER_PART, "P": "none", "E": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Morgana",
    PACKET_SHA256,
    # Dark Binding's sphere deals its packet once, to the first enemy it
    # hits, at the cast — the boundary claim that carries MODULE_CC's
    # reviewed answer for Q into the event ledger.
    single_hit_slots=frozenset({"Q"}),
    slot_parsers={
        "W": _tormented_shadow,
        "R": _soul_shackles,
        "P": _soul_siphon,
    },
    # The sphere's sourced Root Duration row carries MODULE_CC's reviewed
    # kind and its control atom onto the packet's Q entry.
    slot_wrappers={
        "Q": partial(with_control, duration_attr="Root Duration"),
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "W (Tormented Shadow) prices all 10 storm ticks (Maximum Damage Per "
    "Tick x10 == Maximum Total Damage 180-700 + 200% AP) at 0.5-second "
    "intervals over the 5-second desecrated area, first tick on-cast.",
    "R (Soul Shackles) prices the initial hit plus the same magic damage "
    "again at the 3-second tether break (Magic Damage x2 == Total Magic "
    "Damage 400-700 + 160% AP); the slow/root and reveal are "
    "crowd-control utility not priced as damage.",
    "P (Soul Siphon) heals Morgana for 18% of the post-mitigation "
    "damage dealt by her abilities against champions (this "
    "module's derive_self_healing rule); the passive deals no enemy damage "
    "itself.",
    "E (Black Shield) emits the selected recipient's magic shield from the "
    "typed Magic Shield Strength atom. Its typed active-duration atom keeps "
    "crowd control from adding action downtime while the shield holds.",
    "P (Soul Siphon) has no enemy-damage formula anywhere in the cached "
    "packet; it emits a sourced zero-damage row (MODULE_COVERAGE: "
    "no_damage, not out_of_scope). P is not a cast slot in this engine's "
    "rotation.",
]
COVERAGE_CHANNELS = {"P": ("self_healing_rule",)}


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Soul Siphon pays 18% of every damaging ability hit.

    "heals herself for 18% of the post-mitigation damage dealt by her
    abilities against champions, large minions, and medium and large
    monsters" (wiki P).  In a champion duel every Q/W/R damage event is
    ability damage against the champion target (W's storm ticks included);
    E is a shield and deals no damage.  The anchor is the damaging hit, so
    the rule takes its occasions from ``payments`` rather than counting
    ledger rows.
    """
    healing: list[dict] = []
    for payment in ctx.payments(
        HealAnchor.DAMAGING_HIT, lambda source: source in {"Q", "W", "R"}
    ):
        heal_from_damage(
            healing,
            payment.event,
            0.18 * max(0.0, _row_damage(payment.event)),
            "Soul Siphon",
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Morgana")(derive_self_healing)
