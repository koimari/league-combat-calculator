"""Quinn — CP10.6 full-entry-reviewed packet module.

E5-2 fix — Harrier (P): the reviewed packet declared the passive
no_damage/out_of_scope even though the wiki carries a sourced on-hit
formula — "Quinn's basic attacks on-hit against Harrier targets are
empowered to consume the mark to deal 15 : 132.35 (based on level)
(+ 40% bonus AD) bonus physical damage" (data/champions.json P "Bonus
Physical Damage" row) — while equivalent on-hit passives (Nautilus P,
Poppy P) are modeled.  Harrier is now an on-hit entry priced at the
per-level flat plus 40% bonus AD per marked-target auto.

W (Heightened Senses) carries the other half of that mark: "whenever
Quinn uses a basic attack on-attack against a target marked by Harrier
or consumes their mark, she gains bonus attack speed ... for 2 seconds".
The module already prices Harrier on every auto, so the same auto stream
keeps the 2-second window refreshed and the cached "Bonus Attack Speed"
row (28-80%) is emitted as a BUFF-phase ``stat_buff``.  W's other grant
is movement speed, for which ``stat_buff`` has no key.
"""

from typing import Any

from .packet_module import build_packet_module
from .engine import BUFF, ONHIT, SlotCtx
from .slotlib import (
    STEROID_ZERO,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    on_hit_entry,
)

PACKET_SHA256 = "a88925854e27a0548631207e5f283df6a0a369c6249f4ded272801230c801852"


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


def _heightened_senses(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the Harrier-auto attack-speed buff (28-80%), refreshed per auto."""
    ability = ctx.ability("W")
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None

    bonus_as = extract_value(ability, "Bonus Attack Speed", rank)
    movement = extract_value(ability, "Bonus Movement Speed", rank)
    entry = damage_entry(
        ability.get("name", "Heightened Senses"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    entry["detail"] = (
        f"+{bonus_as:g}% bonus attack speed for 2s per Harrier auto — the "
        "same auto stream P prices keeps it refreshed; the row's "
        f"+{movement:g}% bonus movement speed has no stat_buff key"
    )
    return entry


_heightened_senses.phase = BUFF


# Cached kit review.  Q damages and then "the primary target is
# nearsighted for 1.75 seconds if they are a champion ... otherwise, they
# are disarmed": against the fight's champion target that is a nearsight,
# which is not an immobilize and has no kind in the vocabulary (the Graves
# W reading), and the disarm branch never reaches a champion.  E "deal[s]
# physical damage, knock[s] them back a very short distance over 0.5
# seconds, and slow[s] them by 50%" — the knock back is the immobilize the
# slow rides with.  R's Skystrike only rains arrows "dealing physical
# damage to nearby enemies and marking them with harrier"; the
# "immobilized" wording on that entry is about Quinn losing the ability, not
# about control she applies.  W (vision) deals no damage and P is an on-hit
# rider on the auto stream.
MODULE_CC = {"Q": "none", "E": "knockback", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Quinn",
    PACKET_SHA256,
    # Valor's dive, the Vault dash and Skystrike's volley each deal their
    # packet once, at the cast — the boundary claim that carries MODULE_CC's
    # reviewed answers into the event ledger.
    single_hit_slots=frozenset({"Q", "E", "R"}),
    slot_parsers={
        "P": _harrier,
        "W": _heightened_senses,
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Harrier) prices the wiki's on-hit row: 15 : 132.35 (based on "
    "level) (+ 40% bonus AD) bonus physical damage when a basic attack "
    "consumes the Harrier mark (data/champions.json P 'Bonus Physical "
    "Damage'), modeled like Nautilus and Poppy on-hit passives.",
    "The Harrier mark requires Quinn's Q/E/R or Valor's periodic marking "
    "first; the on-hit is priced per auto against the marked target.",
    "W (Heightened Senses) grants the cached Bonus Attack Speed row "
    "(28-80%) for 2 seconds on every Harrier auto; since P prices the "
    "mark on each auto, the window is held for the fight rather than "
    "time-weighted.  W's Bonus Movement Speed row and the active's "
    "vision sweep are not priced — stat_buff has no movement-speed key.",
]

# No MODULE_COVERAGE: every one of the five slots now emits a priced row,
# which is exactly what the contract derives from SLOTS.
