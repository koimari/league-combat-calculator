"""Zac — CP10.10 full-entry-reviewed packet module.

E3 boundary: the worklist assigns Zac no damage-relevant stack mechanic.
The passive's Goo chunks heal Zac (4% : 8.47% max health per chunk) and
reduce W's cooldown; the resurrection is a death passive. Neither
changes outgoing damage, so no stack slot is added.

Coverage: P is ``modeled`` through the revive channel, not through its
own packet row; Q/W/E/R price their cached damage rows.

E4 boundary: the E4-3 worklist skips Zac — R (Let's Bounce!) is the
self-movement rework, not a summoned unit (the "Champion summoned
units" page lists only Zac's Cell Division Bloblets, which are a death
passive with no outgoing damage).  No summon slot is added; the
reviewed bounce packet pricing is unchanged.

P (Cell Division) emits a named state row with no damage part.  The
packet generator reads a ``targetMaxHp`` ratio there, but the cached
prose pays it off ZAC — "Zac will consume it to heal for 4% : 8.47%
(based on level) of HIS maximum health" — under the same "Max Health
Damage" attribute name ``derive_self_healing`` below reads for the heal
ledger.  A self-heal has no place in the damage vocabulary, so the slot
publishes none; the revive and the chunk heal are what the engine prices
for it, through the two channels ``COVERAGE_CHANNELS`` names.
"""

from dataclasses import replace
from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import CC_PER_PART, SlotCtx
from .healing_contract import self_healing_rule
from .inputs import champion_stat
from .module_helpers import no_damage, ranked_slot
from .packet_module import build_packet_module, full_plus_reduced_parser
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
)

PACKET_SHA256 = "73c072964c8c0863856fbd128d75afd0584bb1763baf64063b3bfb8a7df2ac3f"


# E8d: sourced Cell Division revive values.  Cached passive prose (data/
# champions.json, Zac P Cell Division): "enters resurrection for 8 / 7 / 6 /
# 5 / 4 (based on level) seconds, instantly restoring 50% of his maximum
# health ... After the duration, Zac is revived with 10 : 50% maximum
# health."  The binary ZacPassiveChunkDrop.ReviveCooldown corroborates the
# 300-second cooldown; the wiki's level brackets (levels 1 / 6 / 10 / 13 / 17) map
# to the 8 / 7 / 6 / 5 / 4 second resurrection windows, and the revive
# restores between 10% and 50% maximum health based on how many of the four
# bloblets survive.  The deterministic fight model assumes all four
# bloblets survive (no bloblet damage is modeled), so the sourced revive is
# 50% maximum health.  The engine's revive state transition consumes
# ``StartingDefenses.revive_*`` fields; the shared defense resolver wires
# these per champion.
_ZAC_P_SPELL = spell_object("Zac", "ZacPassiveChunkDrop")
REVIVE_COOLDOWN_SECONDS = data_value(_ZAC_P_SPELL, "ReviveCooldown")
_REVIVE_MAX_HEALTH_RATIO = 0.50
# (level, delay) brackets: 8 / 7 / 6 / 5 / 4 seconds at levels 1 / 6 / 10 / 13 / 17.
_REVIVE_DELAY_BRACKETS = ((17, 4.0), (13, 5.0), (10, 6.0), (6, 7.0), (1, 8.0))


def starting_revive_defense(level: int, stats: dict[str, float]) -> dict[str, float]:
    """Return Zac's sourced Cell Division revive fields for StartingDefenses."""
    delay = next(d for threshold, d in _REVIVE_DELAY_BRACKETS if level >= threshold)
    return {
        "revive_health_amount": float(champion_stat(stats, "health"))
        * _REVIVE_MAX_HEALTH_RATIO,
        "revive_delay": delay,
        "revive_cooldown": REVIVE_COOLDOWN_SECONDS,
    }


# P1-3: Q (Stretching Strikes) prices BOTH arm strikes.  The wiki's
# "Total Magic Damage" row is exactly 2 x the per-hit "Magic Damage" row
# (120-360 + 60% AP + 6% of bonus health == 2 x 60-180 + 30% AP + 3% of
# bonus health at every rank): the cast's left-arm strike plus the
# empowered second Stretching Strike that replaces Zac's next basic
# attack while the tether persists.  The second strike has a sourced
# 0.25-second cast time.
@ranked_slot
def _stretching_strikes(ctx: SlotCtx, ability: dict[str, Any], rank: int):
    """Q: both Stretching Strikes — 2 x the sourced per-hit Magic Damage."""
    per_hit = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        per_hit * 2,
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", amount=per_hit, time_offset=0.0),
        DamagePart("magic", amount=per_hit, time_offset=0.25),
    )
    entry["detail"] = (
        f"both arm strikes: 2 x {per_hit:g} (per-hit 'Magic Damage' x 2 "
        "== the wiki's 'Total Magic Damage' row); the second strike is "
        "the empowered basic-attack replacement"
    )
    return entry


def _lets_bounce(packet_r):
    """R: the opening bounce displaces; the later bounces only slow.

    "Each bounce deals magic damage to enemies hit, knocks them back over 1
    second, and slows them by 20% ... ones beyond the first deal 50% damage
    to them and do not apply the knock back" — one cast, two answers, so
    they are authored per part instead of in ``MODULE_CC``.  The parts are
    already the same split: the full-damage opening bounce, then the three
    reduced ones.
    """

    def parse(ctx: SlotCtx):
        entry = packet_r(ctx)
        if entry is None:
            return None
        entry["parts"] = tuple(
            replace(part, cc_kind="knockback" if index == 0 else "slow")
            for index, part in enumerate(entry.get("parts") or ())
        )
        return entry

    return parse


# Stretching Strikes catches the first enemy hit, "dealing magic damage,
# slowing them by 40% for 0.5 seconds" (its root and knock-up need a
# *second*, different target, which a duel does not have); Unstable Matter
# only "explodes to deal magic damage to nearby enemies"; Elastic
# Slingshot lands "deal[ing] magic damage to nearby enemies and knock[ing]
# them up and stun[ning] them for 0.5 seconds".  R is not here: its opening
# bounce and its later ones apply different control, so the kinds are
# authored per part in ``_lets_bounce``.  P is the Goo/revive state row.
MODULE_CC = {"Q": "slow", "W": "none", "E": "knockup", "R": CC_PER_PART}


def _cell_division(ctx: SlotCtx):
    """P: a state row with no enemy-damage term of its own.

    The packet's ``targetMaxHp`` ratio is a generation mislabel — the
    cached prose pays it off ZAC's maximum health — so publishing it as a
    damage part put a heal in the damage vocabulary.  Both halves of the
    slot are priced by the channels ``COVERAGE_CHANNELS`` names.
    """
    return no_damage(
        ctx,
        name="Cell Division",
        reason=(
            "Cell Division deals no enemy damage: the cached 'Max Health "
            "Damage' ratio is Zac's own Goo chunk heal (4% : 8.47% of HIS "
            "maximum health), priced through the self_healing_rule "
            "channel, and the resurrection through "
            "starting_revive_defense."
        ),
    )


parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Zac",
    PACKET_SHA256,
    assumption_overrides=(
        "Let's Bounce! prices the initial bounce plus 3 reduced bounces "
        "(Magic Damage Per Hit + 3 x Reduced Damage Per Hit == Total Magic "
        "Damage).",
    ),
    # E's landing and W's explosion are one hit each at the cast.  W states
    # its certification through a slot parser because it is a
    # ``wiki_attribute`` slot, which ``single_hit_slots`` does not reach.
    single_hit_slots=frozenset({"E"}),
    slot_parsers={
        "W": simple_damage(
            attr="Magic Damage",
            dmg_type="magic",
            source=("W", 0),
            event_order_certified="single_hit",
        ),
        "R": full_plus_reduced_parser(
            full_attr="Magic Damage Per Hit",
            reduced_attr="Reduced Damage Per Hit",
            dmg_type="magic",
            reduced_count=3,
            time_offset=1.0,
            hit_interval=1.0,
            dot_duration=3.0,
        ),
        "Q": _stretching_strikes,
        # P's packet ratio is a mislabeled SELF heal, so the slot emits no
        # enemy-damage row at all rather than one whose only honest value
        # is zero.  The heal itself is the healing rule's, and the revive
        # the starting-defense channel's.
        "P": _cell_division,
    },
    slot_wrappers={
        "R": _lets_bounce,
    },
    cc_kinds=MODULE_CC,
)

# All five slots are emitted, so the derived map already calls them
# modeled.  P's own packet row is the one that prices nothing (its cached
# chunk percentage is read as target-max-health damage and resolves to
# zero); what the engine prices for the slot is the revive — 1269.0, half
# of Zac's level-18 itemless maximum health — plus the Goo chunk heal the
# healing rule authors, so P names both channels.
COVERAGE_CHANNELS = {"P": ("starting_revive_defense", "self_healing_rule")}
ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "Q (Stretching Strikes) prices both arm strikes: 2 x the sourced "
    "per-hit 'Magic Damage' row == the wiki's 'Total Magic Damage' row "
    "(data/champions.json Q; 120-360 + 60% AP + 6% of bonus health at "
    "rank 5); the second strike replaces Zac's next basic attack while "
    "the tether persists (0.25s cast).",
    "P (Cell Division) is modeled as the sourced revive state: 50% maximum "
    "health restored after the level-bracketed resurrection window "
    "(8 / 7 / 6 / 5 / 4s at levels 1 / 6 / 10 / 13 / 17) on a 300s cooldown "
    "(cached passive prose; all four bloblets assumed to survive).",
    "P emits a state row with NO damage part: the packet generator's "
    "'targetMaxHp' ratio is a mislabeled self-heal-on-chunk term ('heal "
    "for 4% : 8.47% of HIS maximum health', not the target's), so it is "
    "not published in the damage vocabulary at all. The revive and the "
    "chunk heal are what the engine prices for the slot, through the "
    "starting_revive_defense and self_healing_rule channels this module "
    "names in COVERAGE_CHANNELS.",
]


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Zac self-healing events from its authored packet.

    The chunk pays a percentage of Zac's own MAXIMUM health, which the
    build already knows, so the amount is resolved here rather than
    deferred to the walk as an ``amount_formula``: a formula is for a live
    reading (current health, a missing-health ratio) and this rule has
    none, while the one-pair receipt cannot evaluate one.
    """
    healing = []
    p = _healing.ability_json(champion_data, "P")
    level = int(champion_stat(champion_stats, "level"))
    chunk_pct = extract_named(p, "Max Health Damage", level, champion_stats, {})
    amount = max(0.0, champion_stat(champion_stats, "health") * chunk_pct / 100.0)

    healing.extend(
        {
            "time": float(event.get("time", 0.0)),
            "amount": amount,
            "source": "Cell Division",
            "kind": "champion_passive",
            **_healing.trigger_fields(event),
        }
        for event in _healing.attributed_events(
            damage_events, lambda source, _event: source in {"Q", "W", "E", "R"}
        )
    )
    return healing


SELF_HEALING_RULE = self_healing_rule("Zac")(derive_self_healing)
