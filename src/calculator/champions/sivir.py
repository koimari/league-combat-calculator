"""Sivir: slot map for the archetype engine.

Q (Boomerang Blade) prices the cached "Total Maximum Champion Damage"
row, the out-and-back pass, exactly twice the single-pass row.
W (Ricochet) prices the cached "Bounce Damage" row, one bounce per
empowered basic attack the auto cadence schedules inside the 4-second
window; the neighbouring "Bonus Attack Speed" row is not the ratio.
E (Spell Shield) is a timed ``self_state_events`` window: a 1.5s shield
that heals Sivir alone after the sourced 0.25s delay.
P (Fleet of Foot) is ``no_damage``.  Its movement grant is state, not a
``stat_buff``: the magnitude is a per-level ladder with empty units that
the cache cannot index, and it decays over 1.5s with no cached uptime,
so a constant buff would over-credit Swiftmarch's adaptive force.
R (On the Hunt) publishes its 20/25/30% move speed through the stat-buff
fold, which re-applies the soft caps, and stays ``out_of_scope`` for its
unpriced cooldown refund: the refund is gated on R's own window and
driven by the auto rate, so a parse-time divisor would credit it outside
the window.  ``SivirR``'s binary ``HuntAttackSpeed`` appears nowhere in
the cached text and is recorded, not modeled.
"""

import math
from typing import Any

from ..ability_atoms import (
    AbilityAtomQuery,
    ranked_ability_atom_value,
    required_ability_atom,
    required_ranked_attribute_atom,
)
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .contract_vocabulary import coverage
from .engine import SlotCtx
from .module_helpers import buff_window_share, ranked_slot
from .packet_module import build_packet_module
from .slot_control import atom_receipt
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named
from .stat_grants import attack_speed_window

PACKET_SHA256 = "ac50a4316c8ffc3f6f326c6be14ec20867f6301066621ff49ec26c1fad1b97a7"


@ranked_slot
def _boomerang_blade(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Q: the two-way pass priced from the Total Maximum Champion Damage row."""
    total = extract_named(
        ability, "Total Maximum Champion Damage", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", total / 2.0, count=2),)
    entry["detail"] = (
        "two-way Boomerang Blade: the crossblade hits out AND back for 2x "
        "(Total Maximum Champion Damage 120-320 + 140% bonus AD + 120% AP "
        "== 2 x the single-pass row)"
    )
    return entry


_W_DURATION_SOURCE = "Sivir.W[0].effects[0].description"


# The bounce stream rides the swings the engine schedules, never a cadence
# of its own; a window with no auto stream still earns one, because the
# cache's "Ricochet resets Sivir's basic attack timer" makes the first
# empowered attack immediate.
def _empowered_swings(ctx: SlotCtx, window: float, *, bonus_rate: float) -> int:
    """Empowered basic attacks Ricochet's sourced window earns at its own rate."""
    rate = (ctx.stat("attack_speed") + bonus_rate) * float(
        ctx.option("auto_attack_uptime")
    )
    return max(1, math.floor(rate * window))


@ranked_slot
def _ricochet(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """W: one bounce per empowered attack, priced from the Bounce Damage row.

    The reviewed packet's ``ad`` ratio was the **Bonus Attack Speed** row
    (20-40%) rather than **Bounce Damage** (40-50% AD), so it underpriced
    every bounce; the atom accessor reads the damage row by name.
    """
    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
    ratio, _ = required_ranked_attribute_atom(
        "Sivir", champion_data, "W", "Bounce Damage", rank, modifier_index=0
    )
    window_atom = required_ability_atom(
        "Sivir",
        champion_data,
        "W",
        query=AbilityAtomQuery(
            source=_W_DURATION_SOURCE,
            behavior="timing",
            evidence_prefix="active duration@",
        ),
    )
    if window_atom.get("units") != ["s"]:
        raise ValueError("Sivir W empowered-window atom must use seconds")
    window = ranked_ability_atom_value(window_atom, 1, source=_W_DURATION_SOURCE)
    per_bounce = ratio / 100.0 * ctx.stat("attack_damage")
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
    )
    # The window's own attack speed: the engine places it at the W cast,
    # and the bounce count is the empowered swings that rate earns.
    bonus_as = attack_speed_window(ctx, entry, ability, rank, duration=window)
    bounces = _empowered_swings(
        ctx, window, bonus_rate=ctx.stat("attack_speed_ratio") * bonus_as / 100.0
    )
    entry["total_raw"] = per_bounce * bounces
    # The cached bounce cap ("up to 8 times ... per empowered attack") is a
    # per-attack ceiling across enemies, and the same sentence allows each
    # enemy "up to one additional time per empowered attack" — so one priced
    # target takes exactly one bounce per swing and the 8 never binds here.
    entry["parts"] = (
        DamagePart("physical", per_bounce, count=bounces, crit_effectiveness=1.0),
    )
    entry["detail"] = (
        f"{bounces} bounce(s) of the cached Bounce Damage row "
        f"({ratio:g}% AD = {per_bounce:g}) — one per empowered basic attack "
        f"in the sourced {window:g}s window, each critting with the swing "
        "that triggered it (Bounce Critical Damage is exactly 2x the "
        f"Bounce Damage row); the window's +{bonus_as:g}% bonus attack speed "
        "is placed at the W cast and rates those swings."
    )
    return entry


# Sourced from the cached Spell Shield description.  The duration is read
# through the typed ability-atom accessor (``timing.active_duration``, the
# description's "for 1.5 seconds" prose atom); the 0.25s heal delay has NO
# atom in the catalog (prose-only — recorded SOURCE GAP in the slice
# handover), so it stays a module-authored sourced literal.
_SPELL_SHIELD_HEAL_DELAY_SECONDS = 0.25


@ranked_slot
def _spell_shield(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """E: one timed spell shield with its sourced block heal.

    Numeric values ride the typed ability-atom accessors: the 1.5s window
    (``timing.active_duration``) and the Heal row (60-80% AD + 50% AP by
    rank).  The 0.25s heal delay is prose-sourced (no atom exists).
    """
    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
    duration_atom = required_ability_atom(
        "Sivir",
        champion_data,
        "E",
        query=AbilityAtomQuery(
            source="Sivir.E[0].effects[0].description",
            behavior="timing",
            evidence_prefix="active duration@",
        ),
    )
    if duration_atom.get("units") != ["s"]:
        raise ValueError("Sivir E spell-shield duration atom must use seconds")
    duration = ranked_ability_atom_value(
        duration_atom, 1, source="Sivir.E[0].effects[0].description"
    )
    ad_ratio, ad_atom = required_ranked_attribute_atom(
        "Sivir", champion_data, "E", "Heal", rank, modifier_index=0
    )
    ap_ratio, ap_atom = required_ranked_attribute_atom(
        "Sivir", champion_data, "E", "Heal", rank, modifier_index=1
    )
    heal = (
        ad_ratio * ctx.stat("attack_damage") / 100.0
        + ap_ratio * ctx.stat("ability_power") / 100.0
    )
    return {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "total_raw": 0.0,
        "damage_type": "magic",
        "parts": (),
        "self_state_events": [
            {
                "kind": "spell_shield",
                "duration": duration,
                "source": ability_name(ability),
                "on_block_heal_amount": heal,
                "on_block_heal_delay": _SPELL_SHIELD_HEAL_DELAY_SECONDS,
                "on_block_heal_source": "Spell Shield · Heal",
                "source_atoms": [
                    atom_receipt(duration_atom),
                    atom_receipt(ad_atom),
                    atom_receipt(ap_atom),
                ],
            }
        ],
        "detail": (
            "Spell Shield blocks one hostile effect during the sourced "
            f"{duration:g}s window and heals Sivir for {heal:g} after the "
            "sourced 0.25s delay."
        ),
    }


#: The basic slots On the Hunt refunds. The cached sentence says "her basic
#: abilities", which on this kit is exactly Q, W and E: R is the grant itself
#: and P is not a cast.
_R_REFUNDED_SLOTS = ("Q", "W", "E")


def _r_attack_cooldown_refund() -> float:
    """Seconds each attack takes off a basic cooldown, read from the binary."""
    return data_value(spell_object("Sivir", "SivirR"), "AttackCooldownRefund")


def _on_the_hunt(packet_r):
    """R: the packet's zero-damage row, carrying its two sourced grants.

    The cast's sourced bonus movement speed is an additive PERCENT, so it
    is published as a ``move_speed_percent`` stat buff — a term in the one
    ``resolve_move_speed`` fold, which re-applies the soft caps rather than
    adding onto the already-capped scalar (the Teemo-W channel).

    The second grant is the reason this slot was ``out_of_scope``: while the
    hunt is up, every basic attack pays 0.5s off Q, W and E's LIVE cooldowns.
    It is authored here, on the granting row, because the grant and the
    cooldowns it shortens are different slots — the one shape
    ``stack_scaled_cooldown`` cannot carry, since that is a slot's rule about
    itself. The cast scheduler walks it beside Navori's share on one pass.

    The 0.5 is SOURCED TWICE and agreeing, so nothing here is a literal: the
    cached prose says the attacks "reduce her basic abilities' current
    cooldowns by 0.5 seconds each", and the tracked binary's ``SivirR``
    carries an ``AttackCooldownRefund`` DataValue of 0.5 on every rank. The
    binary is the root, per rule 5's shape — a patch that moves the number
    moves it in the dump and this follows, where a constant would not.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_r(ctx)
        if entry is None:
            return None
        rank = ctx.rank_for("R")
        if rank < 1:
            return entry
        champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
        percent, _ = required_ranked_attribute_atom(
            "Sivir", champion_data, "R", "Bonus Movement Speed", rank, modifier_index=0
        )
        duration, _ = required_ranked_attribute_atom(
            "Sivir", champion_data, "R", "Buff Duration", rank, modifier_index=0
        )
        # The hunt expires, and a stat_buff is one scalar for the whole
        # fight, so the grant lands time-weighted by the share of the
        # window its own cached Buff Duration covers.  Reading that row
        # for the detail string alone left the buff duration-blind: it
        # published the same number in a 5s fight and a 30s one.
        published = percent * buff_window_share(ctx, duration)
        entry["stat_buff"] = {"move_speed_percent": published}
        refund = _r_attack_cooldown_refund()
        # The window is the same sourced Buff Duration row the movement grant
        # is weighted by: one cast buys one hunt, and both grants ride it.
        entry["swing_cooldown_refund"] = {
            "seconds_per_attack": refund,
            "slots": _R_REFUNDED_SLOTS,
            "window_seconds": duration,
        }
        entry["detail"] = (
            f"On the Hunt grants {percent:g}% bonus movement speed for "
            f"{duration:g}s ({published:g}% over the fight window), "
            "published as a move_speed_percent stat buff, and every basic "
            f"attack inside the {duration:g}s window pays {refund:g}s off "
            f"{', '.join(_R_REFUNDED_SLOTS)}'s live cooldowns. The ally "
            "share stays unmodeled."
        )
        return entry

    return parse


# Reviewed cc-free, whole kit: nothing Sivir casts touches an enemy with
# anything but damage.  P grants her "bonus movement speed", Q's crossblade
# only "deal[s] physical damage to enemies within its path", W's bounces
# "deal[] physical damage to them", E is a self spell shield and heal, and
# R grants her and nearby allies "bonus movement speed".
#
# Q and W are read and left undeclared: the ledger refuses a kind it cannot
# carry, and neither row is one authored hit — the crossblade hits "only
# once per pass" out and back with no cached return cadence, and Ricochet's
# bounces are counted per empowered swing but carry no authored sub-cast
# timing.  This kit stays coarse until those rows carry timing.
MODULE_CC = {"P": "none", "E": "none", "R": "none", "Q": "none", "W": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Sivir",
    PACKET_SHA256,
    slot_parsers={
        "Q": _boomerang_blade,
        "W": _ricochet,
        "E": _spell_shield,
    },
    slot_wrappers={"R": _on_the_hunt},
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "Q (Boomerang Blade) prices the full two-way pass from the cached "
    "'Total Maximum Champion Damage' row (120-320 + 140% bonus AD + "
    "120% AP == 2 x the single-pass 'Physical Damage' row): the blade "
    "deals the same damage on the way out and back.",
    "The exact return cadence is still not cached, so both passes are "
    "priced at the cast boundary: Q's entry carries no travel-time or "
    "return-delay atom, and its raw 'speed' field is two unlabelled "
    "values ('1450 - 1200') against a 1250 targetRange, so which value "
    "governs the outbound pass and which the return is not readable. "
    "castTime '0.25 : 0.1 (based on bonus attack speed)' times the cast, "
    "not the blade.",
    "E (Spell Shield) grants a 1.5 second shield (atom-backed: "
    "timing.active_duration 4d718bc78f540f0a). The first hostile ability "
    "effect during that window is blocked. The cached Heal row is applied "
    "after the sourced 0.25 second delay (prose-only — no catalog atom "
    "exists; recorded SOURCE GAP). Fleet of Foot is state and stays "
    "outside the damage ledger.",
    "W (Ricochet) prices the cached 'Bounce Damage' row (40-50% AD by "
    "rank, atom ability.bounce _damage), NOT the neighbouring 'Bonus "
    "Attack Speed' row (20-40%) the reviewed packet's ad ratio had "
    "matched. One bounce lands per empowered basic attack, and that count "
    "rests on one cached sentence: bounces 'prioritize the nearest new "
    "target, then the nearest target if no new targets are available', "
    "occur 'only up to 8 times' and 'can target each enemy up to one "
    "additional time per empowered attack'. A pair fight has one enemy "
    "and no new target, so it takes exactly one bounce per swing and the "
    "8 never binds. The swing count is the window's own auto cadence "
    "((attack_speed + the window's bonus) x auto_attack_uptime) across the "
    "sourced 4 second window (atom timing.active_duration), with a floor "
    "of one swing because 'Ricochet resets Sivir's basic attack timer'. "
    "Each bounce crits with the swing that triggered it at full "
    "effectiveness: the cached 'Bounce Critical Damage' row is exactly 2x "
    "'Bounce Damage' at every rank. W's own 20-40% bonus attack speed is "
    "placed by the engine as a 4-second window at the first W cast (one "
    "window per fight), and the bounces carry no authored sub-cast timing.",
    "P (Fleet of Foot) has no enemy-damage clause anywhere in its cached "
    "entry: the single effect grants Sivir 55:75 (based on level) bonus "
    "movement speed decaying over 1.5 seconds on her own attacks and "
    "ability hits, and the game binary's SivirPassive record carries only "
    "FlatMS and HasteDuration 1.5 with no damage formula at all. The slot "
    "emits a sourced zero-damage row (MODULE_COVERAGE: no_damage, not "
    "out_of_scope; the Vayne-P / Kalista-P / Pyke-P precedent). The flat "
    "movement grant is NOT modeled as a stat_buff, and the blocker is the "
    "cache rather than the channel (R rides that channel, so the fold "
    "composes). Two cached rows are missing. (1) The magnitude is a level "
    "ladder the cache cannot index: atom ability.per-_level _scaling "
    "carries five values [55, 60, 65, 70, 75] with every unit empty and P "
    "has no rank, so no cached row says which level each value starts at "
    "- only the gitignored binary's ByCharLevelBreakpoints does. (2) The "
    "grant decays to zero across the sourced 1.5 second window and "
    "refreshes on hit, and no cached row carries its uptime or average, "
    "so a constant full-value buff would over-credit the one number the "
    "slot would publish. (An ability stat_buff does NOT become damage "
    "here: Swiftmarch's adaptive_force_per_total_move_speed is resolved "
    "inside calculate_total_stats from the BUILD's move speed, before "
    "any cast, so the over-credit would land on the published "
    "champion_stats and the end-of-fight item_state_receipts, not on a "
    "damage row.) It stays state.",
    "R (On the Hunt) publishes its sourced 20/25/30% bonus movement speed "
    "(atom ability.bonus _movement _speed) as a move_speed_percent "
    "stat_buff, the shared channel damage._apply_stat_buff_ultimates "
    "re-folds through stats.resolve_move_speed so the movement soft caps "
    "are re-applied instead of bypassed (the Teemo-W wiring). It is "
    "time-weighted by buff_window_share over its own sourced Buff "
    "Duration row (8/10/12s by rank): a stat_buff is one scalar for the "
    "whole fight, and reading that row for the detail string alone left "
    "the buff duration-blind, publishing the same number in a 5s fight "
    "and a 30s one. "
    "The slot CLOSES as no_damage: there is no damage to miss (the "
    "binary's SivirR carries an empty mSpellCalculations) and its other "
    "sourced combat effect is priced now. 'While active, Sivir's basic "
    "attacks on-attack reduce her basic abilities' current cooldowns by "
    "0.5 seconds each' is published as a swing_cooldown_refund on this "
    "row, naming Q, W and E and its own Buff Duration window, and the "
    "cast scheduler walks it per attack beside Navori's share. The 0.5 is "
    "read from the binary's AttackCooldownRefund DataValue (0.5 on every "
    "rank), which the cached sentence states verbatim. "
    "What the earlier receipt called the blocker was real and is what "
    "this shape answers: every champion-authored refund before it was a "
    "STATIC parse-time rewrite (Ezreal's _with_q_refund divides an "
    "emitted entry's cooldown; Darius W multiplies its own), sound only "
    "because those streams are always on. Sivir's is gated on 'while "
    "active' and driven by the auto rate, so it needed a walk that reads "
    "the window and the swing stream rather than a fight-wide divisor. "
    "The ally share of the buff stays unmodeled: it prices another "
    "champion's cooldowns, which this fight does not schedule. "
    "SOURCE CONFLICT recorded, not used: SivirR also "
    "carries HuntAttackSpeed (rank 1-3 = 5%/6%/7%) that the cached wiki "
    "text does not mention at all; fail-closed, an uncorroborated "
    "attack-speed steroid is not modeled.",
]
MODULE_COVERAGE = coverage(no_damage="PR")
