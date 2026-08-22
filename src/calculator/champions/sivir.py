"""Sivir — CP10.7 full-entry-reviewed packet module, plus the E9-3 Q fix.

E9-3: Boomerang Blade (Q) is a two-way blade: "Upon reaching maximum
range, the crossblade returns to her ... dealing the same damage to
enemies on its way back" — the cached "Total Maximum Champion Damage"
row (120-320 + 140% bonus AD + 120% AP) is exactly double the
single-pass "Physical Damage" row the reviewed packet priced.  The
module now prices the Total row so a full out-and-back pass deals the
in-game 2x damage (320 at rank 5 vs the old 160).

E (Spell Shield) is ``modeled`` as a timed ``self_state_events`` window:
the sourced 1.5s shield blocks one hostile effect and, after the sourced
0.25s delay, heals Sivir for the cached Heal row (60-80% AD + 50% AP by
rank), scoped to herself — "she heals herself and activates Fleet of
Foot" names no ally.

W (Ricochet) prices the cached **Bounce Damage** row (40-50% AD by
rank), one bounce per empowered basic attack the fight's own auto
cadence schedules inside the sourced 4-second window.  The reviewed
packet's ``ad`` ratio was the neighbouring **Bonus Attack Speed** row
(20-40%), which underpriced every bounce.

  - P (Fleet of Foot) closes as ``no_damage``.  Its single cached effect
    is a self movement-speed buff — "basic attacks on-attack and ability
    hits against enemy champions grant her 55 : 75 (based on level) bonus
    movement speed decaying over 1.5 seconds" — with no enemy-damage row
    anywhere in the entry, and the game binary agrees: the
    ``SivirPassive`` record's ONLY calculation is ``FlatMS`` (plus a
    ``HasteDuration`` of 1.5), with no damage formula at all.  The label
    is the Vayne-P / Kalista-P / Pyke-P shape: sourced, non-damaging.

    The grant is still NOT a ``stat_buff``, and the reason is the cache
    rather than the channel: R now rides that same channel, so the fold
    composes.  Two cached rows are missing.  (1) The magnitude is a LEVEL
    ladder the cache cannot index: atom ``ability.per-_level _scaling``
    carries five values [55, 60, 65, 70, 75] with every unit empty, and
    P has no rank, so nothing in the cache says which level each value
    starts at (only the gitignored binary's ``ByCharLevelBreakpoints``
    does).  (2) The grant decays to zero across the sourced 1.5s window
    and refreshes on hit, and no cached row carries its uptime or its
    average, so a constant full-value buff would over-credit it.  That
    over-credit is not cosmetic: ``item_effects``'
    ``adaptive_force_per_total_move_speed`` (Swiftmarch) turns total
    movement speed into DAMAGE.  It stays state.

  - R (On the Hunt) grants its sourced 20/25/30% bonus movement speed
    through the shared fold — a ``move_speed_percent`` stat buff, the
    Teemo-W channel, which ``damage._apply_stat_buff_ultimates`` re-folds
    through ``stats.resolve_move_speed`` so the soft caps are re-applied
    rather than bypassed.  The slot stays OPEN ``out_of_scope`` (the
    Olaf-R rule) because its other sourced combat effect still has no
    channel at all: "Sivir's basic attacks on-attack reduce her basic
    abilities' current cooldowns by 0.5 seconds each" —
    ``on_attack_cooldown_refund`` is a field of
    ``item_effects.CooldownProcEffect`` (Scout's Slingshot) read only by
    the item-proc scheduler, so there is no ability-cooldown refund
    surface for a champion to author.  The ally share of the buff is
    unmodeled too.
    One further binary row is a genuine SOURCE CONFLICT and is recorded
    rather than used: ``SivirR`` carries ``HuntAttackSpeed`` (rank 1-3 =
    5%/6%/7%) that the cached wiki text does not mention at all.
    Fail-closed: an uncorroborated attack-speed steroid is not modeled.
"""

import math
from typing import Any

from ..ability_atoms import (
    AbilityAtomQuery,
    required_ability_atom,
    required_ranked_attribute_atom,
    ranked_ability_atom_value,
)
from ..ability_spec import DamagePart
from .engine import SlotCtx
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    atom_receipt,
    damage_entry,
    extract_cooldown,
    extract_named,
)
from .module_contract import coverage

PACKET_SHA256 = "ac50a4316c8ffc3f6f326c6be14ec20867f6301066621ff49ec26c1fad1b97a7"


def _boomerang_blade(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the two-way pass priced from the Total Maximum Champion Damage row."""
    ranked = ctx.ranked("Q")
    if ranked is None:
        return None
    ability, rank = ranked
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
def _empowered_swings(ctx: SlotCtx, window: float) -> int:
    """Empowered basic attacks Ricochet's sourced window earns this fight."""
    rate = ctx.stat("attack_speed") * float(ctx.option("auto_attack_uptime"))
    return max(1, math.floor(rate * window))


def _ricochet(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: one bounce per empowered attack, priced from the Bounce Damage row.

    The reviewed packet's ``ad`` ratio was the **Bonus Attack Speed** row
    (20-40%) rather than **Bounce Damage** (40-50% AD), so it underpriced
    every bounce; the atom accessor reads the damage row by name.
    """
    ranked = ctx.ranked("W")
    if ranked is None:
        return None
    ability, rank = ranked
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
    bounces = _empowered_swings(ctx, window)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        per_bounce * bounces,
        "physical",
    )
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
        "Bounce Damage row). W's own 20-40% bonus attack speed is not "
        "modeled, so the swing count is a floor."
    )
    return entry


# Sourced from the cached Spell Shield description.  The duration is read
# through the typed ability-atom accessor (``timing.active_duration``, the
# description's "for 1.5 seconds" prose atom); the 0.25s heal delay has NO
# atom in the catalog (prose-only — recorded SOURCE GAP in the slice
# handover), so it stays a module-authored sourced literal.
_SPELL_SHIELD_HEAL_DELAY_SECONDS = 0.25


def _spell_shield(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: one timed spell shield with its sourced block heal.

    Numeric values ride the typed ability-atom accessors: the 1.5s window
    (``timing.active_duration``) and the Heal row (60-80% AD + 50% AP by
    rank).  The 0.25s heal delay is prose-sourced (no atom exists).
    """
    ranked = ctx.ranked("E")
    if ranked is None:
        return None
    ability, rank = ranked
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


def _on_the_hunt(packet_r):
    """R: the packet's zero-damage row, now carrying its movement grant.

    The cast's sourced bonus movement speed is an additive PERCENT, so it
    is published as a ``move_speed_percent`` stat buff — a term in the one
    ``resolve_move_speed`` fold, which re-applies the soft caps rather than
    adding onto the already-capped scalar (the Teemo-W channel).
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
        entry["stat_buff"] = {"move_speed_percent": percent}
        entry["detail"] = (
            f"On the Hunt grants {percent:g}% bonus movement speed for "
            f"{duration:g}s, published as a move_speed_percent stat buff at "
            "the fight-start boundary every stat_buff has. The ally share "
            "and the 0.5s basic-ability cooldown refund stay unmodeled."
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
MODULE_CC = {"P": "none", "E": "none", "R": "none"}

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

ASSUMPTIONS = list(ASSUMPTIONS) + [
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
    "8 never binds. The swing count is the fight's own auto cadence "
    "(attack_speed x auto_attack_uptime) across the sourced 4 second "
    "window (atom timing.active_duration), with a floor of one swing "
    "because 'Ricochet resets Sivir's basic attack timer'. Each bounce "
    "crits with the swing that triggered it at full effectiveness: the "
    "cached 'Bounce Critical Damage' row is exactly 2x 'Bounce Damage' "
    "at every rank. W's own 20-40% bonus attack speed is NOT modeled, so "
    "the swing count is a floor, and the bounces carry no authored "
    "sub-cast timing.",
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
    "so a constant full-value buff would over-credit it - and the one "
    "live consumer of that stat is item_effects' "
    "adaptive_force_per_total_move_speed (Swiftmarch), where an "
    "over-credited movement number becomes damage. It stays state.",
    "R (On the Hunt) publishes its sourced 20/25/30% bonus movement speed "
    "(atom ability.bonus _movement _speed) as a move_speed_percent "
    "stat_buff, the shared channel damage._apply_stat_buff_ultimates "
    "re-folds through stats.resolve_move_speed so the movement soft caps "
    "are re-applied instead of bypassed (the Teemo-W wiring). The buff "
    "applies at the same fight-start boundary every stat_buff has; its "
    "sourced 8/10/12 second duration by rank covers the modeled windows. "
    "The slot still stays out_of_scope, NOT no_damage (the Olaf-R rule: "
    "a real, sourced, unmodeled mechanic is out_of_scope). There is no "
    "damage to miss - the binary's SivirR carries an empty "
    "mSpellCalculations - but its other sourced combat effect still has "
    "no channel: 'Sivir's basic attacks on-attack reduce her basic "
    "abilities' current cooldowns by 0.5 seconds each' - "
    "on_attack_cooldown_refund is a field of "
    "item_effects.CooldownProcEffect read only by the item-proc "
    "scheduler, so no ability-cooldown-refund surface exists for a "
    "champion to author. The ally share of the buff is unmodeled too. "
    "SOURCE CONFLICT recorded, not used: SivirR also "
    "carries HuntAttackSpeed (rank 1-3 = 5%/6%/7%) that the cached wiki "
    "text does not mention at all; fail-closed, an uncorroborated "
    "attack-speed steroid is not modeled.",
]
MODULE_COVERAGE = coverage(no_damage="P", out_of_scope="R")
