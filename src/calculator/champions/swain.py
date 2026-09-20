"""Swain: full-entry-reviewed packet module.

Q (Death's Hand) unleashes five bolts over 0.264 seconds, later bolts against
one enemy dealing 25% bonus damage, so the single-target cast is the cache's
"Total Damage" row, the first bolt at full and four at the bonus row, exactly
twice the per-bolt row at every rank.  Five bolts are not one hit, so Q declares
its aggregate at the cast boundary and the bolt cadence has no offsets yet.
R variant 0 (Demonic Ascension) still prices ONE 0.5-second drain tick for a
whole channel.  The cache carries no total for it, the channel's length being a
Demonic Energy economy, so pricing it needs a modeled duration, not another row.
P (Ravenous Flock) is the Soul Fragment stack buff, 15 bonus health per stack.
The count is an explicit option defaulting to zero, because fragments come from
enemy deaths and from the W and E-recast rips this rotation does not author.
The bonus health reaches the parse context before R, whose Heal per Tick row
carries a %bonus-health ratio.
"""

from dataclasses import replace
from typing import Any

from .. import healing_helpers as _healing
from ..binary_roots import data_value, spell_object
from .engine import BUFF, SlotCtx
from .healing_contract import SelfHealCtx, self_healing_rule
from .inputs import champion_stat, int_option
from .module_helpers import ability_slot, typed_damage
from .packet_module import build_packet_module
from .slot_cc import CC_PER_PART
from .slot_entries import STEROID_ZERO, damage_entry
from .slot_extract import ability_name, find_named_leveling, sum_modifiers

PACKET_SHA256 = "fba3384adee7755ce0b4adcfad1f4abef6da73244cc511c141ce127b1b15de3a"

# Rooted in SwainPassive.HealthIncrement; the passive carries no leveling row,
# and the cache states no cap, so the option's ceiling remains the module's
# declared input bound.
_P_HEALTH_PER_FRAGMENT = data_value(
    spell_object("Swain", "SwainPassive"), "HealthIncrement"
)
_P_MAX_FRAGMENTS = 30


@ability_slot("P")
def _ravenous_flock(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """P: 15 permanent bonus health for each Soul Fragment held."""

    fragments = min(max(int(ctx.option("p_soul_fragments")), 0), _P_MAX_FRAGMENTS)
    bonus_health = _P_HEALTH_PER_FRAGMENT * fragments
    # BUFF phase: R's Heal per Tick row carries a "% of his bonus health"
    # ratio and parses after this slot.
    ctx.stats["bonus_health"] = ctx.stat("bonus_health") + bonus_health
    ctx.stats["health"] = ctx.stat("health") + bonus_health
    entry = damage_entry(
        ability_name(ability),
        ctx.level,
        0.0,
        0.0,
        "magic",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {"bonus_health": bonus_health}
    entry["detail"] = (
        f"{fragments} Soul Fragment(s) x {_P_HEALTH_PER_FRAGMENT:g} = "
        f"+{bonus_health:g} permanent bonus health; the 6%-maximum-health "
        "heal on claiming one is a claim event this rotation does not author"
    )
    return entry


_ravenous_flock.phase = BUFF


def _deaths_hand(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: all five bolts against one enemy, declared at the cast."""
    return typed_damage(ctx, "Total Damage", "magic", time_offset=0.0)


# Reviewed crowd control, read from the cached kit.  Q (Death's Hand)
# "deal[s] magic damage to enemies hit" with no control clause.  W (Vision
# of Empire) explodes "dealing magic damage to enemies within ... and
# slowing them by 50% for 1.5 seconds".  E (Nevermove) "detonates upon the
# first enemy hit, dealing magic damage to nearby enemies and rooting them
# for 1.5 seconds".  R is variant-dependent and is authored on its parts
# below, because the two casts under that one slot answer differently.
MODULE_CC = {"Q": "none", "W": "slow", "E": "root", "R": CC_PER_PART, "P": "none"}

# Demonic Ascension "drains the lifeforce of nearby enemies, both dealing
# magic damage and healing himself every 0.5 seconds" — no control.
# Demonflare "deals magic damage to nearby enemies and slows them by 50%".
_R_VARIANT_CC = ("none", "slow")


def _ravenous_flock_ultimate(packet_r):
    """R: the selected variant's packet, carrying that variant's own cc."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_r(ctx)
        if entry is None:
            return None
        try:
            index = int(ctx.option("r_variant"))
        except (TypeError, ValueError):
            index = 0
        kind = _R_VARIANT_CC[min(max(index, 0), len(_R_VARIANT_CC) - 1)]
        entry["parts"] = tuple(
            part if part.cc_kind is not None else replace(part, cc_kind=kind)
            for part in entry.get("parts") or ()
        )
        return entry

    parse.phase = packet_r.phase
    return parse


parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Swain",
    PACKET_SHA256,
    # Each of these packets prices one blow: W the single delayed
    # explosion, E the single detonation, and R either one drain tick or
    # the one Demonflare nova.  Q prices five bolts and declares their
    # aggregate at the cast instead.
    single_hit_slots=frozenset({"W", "E", "R"}),
    slot_parsers={"Q": _deaths_hand, "P": _ravenous_flock},
    assumption_overrides=(
        "Q (Death's Hand) prices the single-target total of all five bolts: the "
        "cached Total Damage row.",
        "That is 120/180/240/300/360 + 90% AP, one bolt plus four at the 25% Bonus "
        "Damage Per Bolt row.",
        "The 0.264-second cadence across the five bolts is not authored.",
        "R variant 0 (Demonic Ascension) prices one 0.5-second drain tick.",
        "The cache lists no total for the channel, whose length the Demonic Energy "
        "economy sets.",
        "The whole-channel price is withheld rather than guessed.",
    ),
    slot_wrappers={
        "R": _ravenous_flock_ultimate,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    *list(OPTIONS),
    int_option(
        "p_soul_fragments",
        0,
        minimum=0,
        maximum=_P_MAX_FRAGMENTS,
        label="Soul Fragments held (15 permanent bonus health each)",
        rotation={
            "role": "self_state",
            "slot": "P",
            "note": "Fragments carried into the fight; P's health buff is "
            "self-state, not a consumed setup.",
        },
    ),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "P (Ravenous Flock) grants 15 permanent bonus health per Soul Fragment (cached P "
    "prose, no row).",
    "p_soul_fragments defaults to 0: deaths and Vision of Empire or Nevermove rips "
    "this fight never authors.",
    "The health reaches the parse context before R, whose Heal per Tick row scales "
    "with bonus health.",
]

# No MODULE_COVERAGE: every one of the five slots emits a priced row now.


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Resolve Swain self-healing events from its authored packet.

    Demonic Ascension drains nearby enemies, healing a flat amount per
    0.5-second tick per target affected (cached R effect[1]: Heal per Tick
    7.5/15/22.5 + 2.5% AP + 0.75% of his bonus health).  The Reduced Heal
    per Tick entry is the 90%-reduced minion/monster variant, so a
    champion duel pays the full amount.  The R packet prices one drain
    tick per cast, so each R hit that dealt damage heals one tick's flat
    value.  The "% of his bonus health" unit is not a generic scaling
    unit, so it is resolved with an explicit override rather than silently
    dropped.
    """
    healing = []
    r_ability = _healing.ability_json(ctx.champion_data, "R")
    r_rank = _healing.parsed_rank(ctx.ability_damages, "R")
    heal_leveling = find_named_leveling(r_ability, "Heal per Tick")

    def swain_bonus_health(unit: str, value: float) -> float | None:
        if unit == "% of his bonus health":
            return value / 100.0 * champion_stat(ctx.champion_stats, "bonus_health")
        return None

    heal_per_tick = (
        sum_modifiers(
            heal_leveling,
            r_rank,
            ctx.champion_stats,
            {},
            modifier_override=swain_bonus_health,
        )
        if heal_leveling is not None
        else 0.0
    )
    for payment in ctx.payments(_healing.HealAnchor.DAMAGING_HIT, "R"):
        _healing.heal_from_damage(
            healing,
            payment.event,
            heal_per_tick,
            "Demonic Ascension",
            link_to_damage=False,
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Swain")(derive_self_healing)
