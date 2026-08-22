"""Naafiri — CP10.5 full-entry-reviewed packet module (E2/E9-2 fixes).

E2 DoT fix: Q (Darkin Daggers) prices the initial hit plus 10 sourced
0.5s bleed ticks (Total Bleed Physical Damage == per-tick x 10).

E9-2 gap fixes:
- Q recast: the recast hits an already-bleeding champion for the
  "remaining bleed damage plus additional bonus physical damage".  The
  bonus is the cached Minimum/Maximum Bonus Physical Damage rows (30-80
  + 40% bAD at the minimum, 60-160 + 140% bAD at the maximum),
  interpolated 0% : 100% by the target's missing health; the remaining
  bleed term is covered by the already-priced bleed ticks (conservative:
  the recast does not double-price them).
- Q self-heal: the recast against a champion heals Naafiri for the
  cached "Heal" row (45-105 + 40% bonus AD) — authored by the E1
  self-heal rule (HEALING_RULE_CHAMPIONS); the support scanner defers
  this slot so the ledger has one receipt.
- E (Eviscerate) prices BOTH the dash and the Flurry explosion on
  arrival (Dash Physical Damage + Flurry Physical Damage == Total
  Physical Damage), instead of the packet's dash-only row.

!!! GAME-FILE SLOT LABELS ARE SWAPPED — READ BEFORE ANY PATCH-DAY CHECK
Naafiri's binary (``data/bin/characters/naafiri.bin.json``) names her
two upper spell slots the OPPOSITE way round from the live kit, the
wiki, and ``data/champions.json``.  This is a naming artifact of her
2025 rework, not a data error, and it is the single easiest way to
mis-source this champion (the Gnar-P game-file caveat pattern):

  - binary ``Characters/Naafiri/Spells/NaafiriRAbility/NaafiriR``
    IS wiki/live **W — The Call of the Pack**.  Proof: its
    ``cooldownTime`` is the padded 7-slot ``[26, 26, 24, 22, 20, 18,
    18]`` (ranks 1-5 at indices 1-5 = 26/24/22/20/18, the wiki W
    cooldown), and its ``DataValues`` are ``PackmatesToAdd`` (2),
    ``Duration`` (5.0), ``MoveSpeedAmount`` (padded ``[.175, .20,
    .225, .25, .275, .30, .325]`` = the wiki W row 20/22.5/25/27.5/30%
    at ranks 1-5), ``UntargetableDuration`` (1.0 — the wiki W's
    "untargetable for the first 1 second") and ``NaafiriADPercentBoost``
    (0.20 — the wiki W's "gains 20% AD bonus attack damage").
  - binary ``Characters/Naafiri/Spells/NaafiriWAbility/NaafiriW``
    IS wiki/live **R — Hounds' Pursuit**.  Proof: ``cooldownTime`` is
    the padded ``[110, 110, 95, 80, 80, 80, 80]`` (R ranks 1-3 =
    110/95/80), and its calculations are ``TotalDamage`` /
    ``PackmateDamage`` / ``ArmorShred`` / ``ShieldTotal``.

The same swap runs through ``data/atoms/v2/naafiri.atoms.v2.json``,
whose ``behavior`` field uses the BINARY names: the atom row tagged
``NaafiriR`` (``Trait_Untargetable``) is wiki W, and the rows tagged
``NaafiriW`` (``Trait_DamageAbility``, ``Trait_Shield``,
``Trait_AttackBuff_Duration``) are wiki R.  Everything in THIS module
is named by the live/wiki kit, matching ``data/champions.json``.

Do NOT try to resolve the swap from the ``NaafiriR*`` / ``NaafiriW*``
CHILD objects (``NaafiriRShield``, ``NaafiriRVision``,
``NaafiriRMoveSpeed``, ``NaafiriRPassive``, ``NaafiriWShred``, the
``NaafiriPackmate*`` shells).  Every one of them is an empty marker —
``DataValues`` and ``mSpellCalculations`` are both empty — so they
carry no number to cross-check a cooldown or a ratio against, and the
atomizer classifies them by NAME (``evidence`` reads ``name:shield``,
``name:movespeed``), which is precisely the signal the swap corrupts.
Only the five primary records ``NaafiriP`` / ``NaafiriQ`` /
``NaafiriW`` / ``NaafiriE`` / ``NaafiriR`` hold DataValues or
calculations, and the two-channel cooldown match above is the only
sound way to bind them to live slots.

Roadmap session (2026-08-21): closes both of Naafiri's out_of_scope
slots (P, W).

  - W (The Call of the Pack) is a real, sourced steroid, so it gets a
    slot-parser override rather than a relabel (Aatrox R / Singed R
    precedent: a BUFF-phase ``stat_buff``).  The wiki W's third effect
    branch reads "While on the hunt, Naafiri gains 20% AD bonus attack
    damage and grants herself and all Packmates bonus movement speed";
    the 20% lives in prose rather than a leveling row, so it is pinned
    as a module constant and corroborated by the binary's
    ``NaafiriADPercentBoost`` = 0.20 (see the swap note above).  Both
    channels agree it is unranked, and the binary's ``BonusAD``
    calculation is a ``StatByNamedDataValueCalculationPart`` on stat 2
    (attack damage) with NO ``mStatFormula`` override — i.e. 20% of
    TOTAL AD, granted as bonus AD, which is exactly what the wiki's
    "20% AD" notation means.  Modeled as BUFF phase (mutates
    ``ctx.stats`` in-parse) so Q/E/R and the packmate row below all
    scale off the buffed bonus AD, and emitted as a ``stat_buff``
    payload so the fight engine's autos see it too.
    The same branch's bonus movement speed (20/22.5/25/27.5/30% by W
    rank, a real leveling row, corroborated by the binary's
    ``MoveSpeedAmount``) is sourced but deliberately NOT modeled: it is
    an additive PERCENT bonus, and the only ability-buff channel
    (``_apply_stat_buff_ultimates`` in ``damage.py``) adds a flat
    number straight onto ``champion_stats["move_speed"]``, bypassing
    both the additive-percent composition and
    ``stats.apply_movement_speed_soft_caps``.  Feeding that unclamped
    scalar to the one live consumer (``item_effects``'
    ``adaptive_force_per_total_move_speed``, i.e. Swiftmarch's adaptive
    force) would turn an uncertified movement number into damage, so
    it stays a documented rider — see ASSUMPTIONS.
  - P (We Are More) closes as the packmate DAMAGE coupling, the Illaoi-P
    precedent (a passive slot that prices the pet damage other slots
    trigger).  The innate summon itself deals nothing; what the pack
    contributes on Hounds' Pursuit IS wiki-sourced, on R's own second
    leveling row "Physical Damage per Packmate" (12.5/20/27.5 + 10%
    bonus AD), which the packet ignored entirely.  The packmate count
    is sourced three ways and all three agree exactly:
      * wiki P text: "up to 2 / 3 / 4 / 5 (based on level)";
      * binary ``NaafiriP``'s ``PackmateCap`` calculation:
        ``mLevel1Value`` 2 with +1 breakpoints at levels 9, 12 and 15;
      * the wiki R notes' packmate-total table, which is the arithmetic
        product of the two rows above — "Levels 16:18: 137.5 (+ 50%
        bonus AD) / 192.5 (+ 70% bonus AD)" is exactly 5 x 27.5 (+5 x
        10%) and 7 x 27.5 (+7 x 10%), and every other band checks the
        same way (L6-8: 2 x 12.5 = 25 / 4 x 12.5 = 50; L9-11: 3 x 12.5
        = 37.5 at rank 1 and 3 x 20 = 60 at rank 2; L12-14: 4 x 20 =
        80; L15: 5 x 20 = 100).  The table's second column is the
        wiki W note's raised cap ("While The Call of the Pack is
        active, it increases We Are More's summon cap to 4 / 5 / 6 / 7
        (based on level)"), so the two columns are selected by the SAME
        ``w_hunt`` option that gates the AD steroid — one hunt state,
        not two independent guesses.
    Packmate BASIC ATTACKS stay unpriced with a named receipt: their
    formula exists only in the game binary (``NaafiriP``'s
    ``PackmateTotalDamage`` = level-interpolated 10->20 + 4% bonus AD,
    with ``PackmateBaseAS`` 0.688), because the wiki's per-champion
    Pets entry is NOT part of the local cache — ``data/champions.json``
    P says only "See Pets for full details on Packmates".  The E4
    summon precedent (Malzahar voidlings, Annie's Tibbers) requires a
    cached wiki row for the per-attack damage and pins only the cadence
    as a module constant; there is no cached row here to pin against,
    and the pack's uptime/target-selection (leap range, frenzy
    stacking, taunt) is unmodeled state on top.  Pricing it would be a
    single-channel invention, so it is documented instead — see
    ASSUMPTIONS.
"""

from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx
from .healing_contract import self_healing_rule
from .module_helpers import buff_window_share
from .packet_module import build_packet_module
from .slotlib import (
    STEROID_ZERO,
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
)
from .inputs import bool_option

PACKET_SHA256 = "422062ecdd781eb5a57f34b7b9c3221288b03f12811cb2d0788a6a877afe4896"


# HARDCODED: verify on patch updates — the sourced bleed tick count:
# Total Bleed Physical Damage == Bleed Physical Damage per Tick x 10 at
# every rank (E2 worklist, data/worklists/e2-dot-ticks.json), with the
# wiki's 0.5s cadence over 5 seconds.  The recast fires 0.5s after the
# first cast ("can be recast after 0.5 seconds and within 4 seconds").
_BLEED_TICKS = 10
_BLEED_FIRST_TICK = 0.5
_BLEED_TICK_INTERVAL = 0.5
_BLEED_DURATION = 5.0
_RECAST_TIME_OFFSET = 0.5

# HARDCODED: verify on patch updates against the GAME FILES as well as the
# wiki — and read the slot-swap warning in the module docstring first.
# W (The Call of the Pack) grants "20% AD bonus attack damage" in wiki
# prose only (no leveling row), corroborated by the binary's
# NaafiriADPercentBoost = 0.20 on the SWAPPED record
# Characters/Naafiri/Spells/NaafiriRAbility/NaafiriR, whose BonusAD
# calculation reads stat 2 (attack damage) with no mStatFormula override,
# i.e. 20% of TOTAL AD granted as bonus AD.  The hunt lasts 5 seconds
# (wiki W text; binary Duration = 5.0).
_HUNT_AD_PERCENT = 20.0
_HUNT_DURATION = 5.0

# Packmate counts by champion level, sourced three ways (wiki P text, the
# binary's PackmateCap breakpoints at levels 9/12/15, and the wiki R
# notes' packmate-total table — see the module docstring).  The first
# column is We Are More's own cap; the second is the cap while The Call
# of the Pack's hunt is active (wiki W note).
_PACKMATE_CAP_BY_LEVEL = ((15, 5, 7), (12, 4, 6), (9, 3, 5), (1, 2, 4))
# Wiki R: "Naafiri and her Packmates channel for 0.75 seconds ... upon
# completion of the channel, they dash to the target".  The pack lands
# with her, so every packmate hit is authored at the end of the channel.
_R_CHANNEL_TIME = 0.75
_PACKMATE_DAMAGE_ATTR = "Physical Damage per Packmate"


def _packmate_count(level: int, *, hunt: bool) -> int:
    """Sourced number of Packmates at *level*, per the hunt state."""
    for threshold, base_cap, hunt_cap in _PACKMATE_CAP_BY_LEVEL:
        if level >= threshold:
            return hunt_cap if hunt else base_cap
    raise ValueError(f"Naafiri: no sourced Packmate cap for level {level!r}")


def _call_of_the_pack(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the hunt's 20%-of-total-AD bonus-attack-damage steroid.

    See the module docstring's W entry for the two-channel sourcing of
    the 20% (wiki prose + the swapped binary record's
    ``NaafiriADPercentBoost``) and for why the branch's bonus movement
    speed stays a documented rider instead of a ``stat_buff`` key.
    """
    ranked = ctx.ranked("W", 0)
    if ranked is None:
        return None
    ability, rank = ranked

    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    if not bool(ctx.option("w_hunt")):
        entry["detail"] = (
            "Hunt not priced (w_hunt off): the 20% AD bonus attack damage "
            "and the raised Packmate cap are both withheld."
        )
        return entry

    # The hunt expires; a stat_buff is one scalar for the whole fight, so
    # the grant lands time-weighted by the share of the window it covers
    # (Blitzcrank's Overdrive rule, module_helpers.buff_window_share).
    granted = _HUNT_AD_PERCENT / 100.0 * ctx.stat("attack_damage")
    bonus = granted * buff_window_share(ctx, _HUNT_DURATION)
    movement = extract_value(ability, "Bonus Movement Speed", rank)
    ctx.stats["attack_damage"] = ctx.stat("attack_damage") + bonus
    ctx.stats["bonus_attack_damage"] = ctx.stat("bonus_attack_damage") + bonus
    entry["stat_buff"] = {"bonus_attack_damage": bonus}
    entry["detail"] = (
        f"+{granted:.1f} bonus attack damage for {_HUNT_DURATION:g}s "
        f"({_HUNT_AD_PERCENT:g}% of total AD, wiki W prose corroborated by "
        f"the game binary's NaafiriADPercentBoost); +{bonus:.1f} over the "
        "fight window.  The hunt also raises the Packmate cap (priced on "
        f"the We Are More row) and grants +{movement:g}% movement speed, "
        "which stays a sourced-but-unmodeled rider — see ASSUMPTIONS.  The "
        "untargetability and the Packmate vanish/reappear are state."
    )
    return entry


_call_of_the_pack.phase = BUFF


def _we_are_more(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the pack's sourced share of Hounds' Pursuit (Illaoi-P pattern).

    The innate summon deals no damage of its own.  What the Packmates
    contribute is R's own "Physical Damage per Packmate" leveling row
    times the sourced Packmate count at this level and hunt state; their
    basic attacks stay unpriced with a named receipt (module docstring).
    """
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
    name = ability_name(ability)
    hunt = bool(ctx.option("w_hunt"))
    count = _packmate_count(ctx.level, hunt=hunt)
    r_ability = ctx.ability("R", 0)
    r_rank = ctx.rank_for("R")
    if r_ability is None or r_rank < 1 or count < 1:
        return {
            "name": name,
            "damage_type": "physical",
            "total_raw": 0.0,
            "parts": (),
            "detail": (
                f"{count} Packmate(s) active; Hounds' Pursuit is unlearned, "
                "so the pack has no sourced damage row (their basic attacks "
                "are documented-not-modeled — see ASSUMPTIONS)."
            ),
        }

    per_packmate = extract_named(
        r_ability, _PACKMATE_DAMAGE_ATTR, r_rank, ctx.stats, ctx.target
    )
    # ``proc_count`` is the number of DISCRETE proc instances and
    # ``DamagePart.count`` is the number of hits INSIDE one instance;
    # ``_add_precomputed_proc_damage`` prices
    # ``sum(part.amount * part.count) * proc_count``, so carrying the pack
    # size in both fields would multiply it in twice (a count-squared
    # overstatement, and ``_apply_basic_amp`` would also be told about
    # ``count x proc_count`` damage instances).  One Packmate hit is one
    # part; the pack size is the proc count.
    return {
        "name": name,
        "damage_type": "physical",
        "total_raw": per_packmate * count,
        "parts": (
            DamagePart(
                "physical",
                per_packmate,
                count=1,
                time_offset=_R_CHANNEL_TIME,
                hit_interval=0.0,
            ),
        ),
        "proc_count": count,
        "unit": "Packmate hits",
        "event_phase": "effect",
        "damage_events": [
            {
                "time": _R_CHANNEL_TIME,
                "damage_type": "physical",
                "damage": per_packmate,
                "event_precision": "phase_order",
            }
            for _ in range(count)
        ],
        "detail": (
            f"{count} Packmate(s) land Hounds' Pursuit with her at "
            f"{per_packmate:.2f} physical each (sourced 'Physical Damage per "
            f"Packmate' row at R rank {r_rank}); the count is the "
            + ("hunt-raised" if hunt else "We Are More")
            + " cap at level "
            f"{ctx.level}.  Packmate basic attacks are not priced."
        ),
    }


def _darkin_daggers(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: initial dagger + 10 bleed ticks + the recast's bonus damage."""
    ranked = ctx.ranked("Q", 0)
    if ranked is None:
        return None
    ability, rank = ranked

    initial = extract_named(
        ability, "Initial Physical Damage", rank, ctx.stats, ctx.target
    )
    per_tick = extract_named(
        ability, "Bleed Physical Damage per Tick", rank, ctx.stats, ctx.target
    )
    parts: list[DamagePart] = [
        DamagePart("physical", initial, time_offset=0.0),
        DamagePart(
            "physical",
            per_tick,
            count=_BLEED_TICKS,
            time_offset=_BLEED_FIRST_TICK,
            hit_interval=_BLEED_TICK_INTERVAL,
        ),
    ]
    total = initial + per_tick * _BLEED_TICKS

    if bool(ctx.options.get("q_recast", True)):
        minimum = extract_named(
            ability, "Minimum Bonus Physical Damage", rank, ctx.stats, ctx.target
        )
        maximum = extract_named(
            ability, "Maximum Bonus Physical Damage", rank, ctx.stats, ctx.target
        )

        def recast_bonus(missing_ratio: float) -> float:
            return minimum + (maximum - minimum) * missing_ratio

        parts.append(
            DamagePart(
                "physical",
                hp_scaled_damage=recast_bonus,
                time_offset=_RECAST_TIME_OFFSET,
            )
        )
        total += minimum

    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = tuple(parts)
    entry["dot_duration"] = _BLEED_DURATION
    entry["detail"] = (
        f"Initial hit + {_BLEED_TICKS} sourced 0.5s-interval bleed ticks "
        f"(Bleed Physical Damage per Tick x{_BLEED_TICKS} = Total Bleed "
        "Physical Damage)"
        + (
            "; recast bonus damage interpolated between the Minimum/Maximum "
            "Bonus Physical Damage rows by target missing health"
            if bool(ctx.options.get("q_recast", True))
            else "; recast bonus not priced (q_recast off)"
        )
    )
    return entry


def _eviscerate(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: dash damage plus the Flurry explosion on arrival."""
    ranked = ctx.ranked("E", 0)
    if ranked is None:
        return None
    ability, rank = ranked

    dash = extract_named(ability, "Dash Physical Damage", rank, ctx.stats, ctx.target)
    flurry = extract_named(
        ability, "Flurry Physical Damage", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        dash + flurry,
        "physical",
    )
    entry["parts"] = (
        DamagePart("physical", dash, time_offset=0.0),
        DamagePart("physical", flurry, time_offset=0.5),
    )
    entry["detail"] = (
        "Dash Physical Damage + Flurry Physical Damage == Total Physical "
        "Damage (the flurry explodes on arrival, 0.5s cadence authored)."
    )
    return entry


# Reviewed crowd control, read from the cached kit.  Q (Darkin Daggers)
# "deals physical damage to enemies hit and inflicts them with a bleed"
# with no control clause, and E (Eviscerate) dashes and explodes with
# none either.  R (Hounds' Pursuit) arrives and "deals physical damage
# and slows the target by 99% for 0.25 seconds" — the slow lands on
# Naafiri's own arrival hit.  P's Packmates land with her and apply
# nothing of their own; W authors no damage part.
MODULE_CC = {"P": "none", "Q": "none", "E": "none", "R": "slow"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Naafiri",
    PACKET_SHA256,
    # Hounds' Pursuit is one arrival on the singled-out champion —
    # one part and one hit, which is what carries R's reviewed slow
    # into the event ledger.  (Eviscerate's dash-and-explode row is
    # two hits, so it is not certified here.)
    single_hit_slots=frozenset({"R"}),
    packet_tick_fixes={
        "Darkin Daggers": {
            "initial_tick": 0.0,
            "extra_part": {
                "attribute": "Bleed Physical Damage per Tick",
                "count": 10,
                "damage_type": "physical",
                "first_tick": 0.5,
                "tick_interval": 0.5,
                "dot_duration": 5.0,
            },
        }
    },
    slot_parsers={
        "P": _we_are_more,
        "Q": _darkin_daggers,
        "E": _eviscerate,
        "W": _call_of_the_pack,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS: list[dict[str, Any]] = list(OPTIONS) + [
    bool_option(
        "q_recast",
        True,
        label="Q recast hits the bleeding target (bonus damage + heal)",
    ),
    bool_option(
        "w_hunt",
        True,
        label="W hunt is active (20% AD bonus attack damage + the raised "
        "Packmate cap)",
    ),
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Q (Darkin Daggers) prices the initial hit, 10 sourced 0.5s bleed "
    "ticks (Total Bleed Physical Damage == per-tick x 10, E2 worklist), "
    "and the recast's bonus damage — interpolated between the "
    "Minimum/Maximum Bonus Physical Damage rows (0% : 100% based on "
    "target missing health) when q_recast is on (default); the remaining "
    "bleed damage of the recast is covered by the already-priced bleed "
    "ticks and is not double-counted",
    "Q recast against a champion heals Naafiri for the cached Heal row "
    "(45-105 + 40% bonus AD) — one heal per Q cast, authored by the E1 "
    "self-heal rule; the support scanner defers this slot to keep one "
    "ledger receipt",
    "E (Eviscerate) prices the dash plus the Flurry explosion (Dash "
    "Physical Damage + Flurry Physical Damage == Total Physical Damage)",
    "W (The Call of the Pack) grants bonus attack damage equal to 20% of "
    "total AD for the 5s hunt (wiki W prose, corroborated by the game "
    "binary's NaafiriADPercentBoost = 0.20 on the SWAPPED NaafiriR "
    "record — see the module docstring's slot-label warning).  It is a "
    "BUFF-phase stat_buff, so Q/E/R and the Packmate row all price off "
    "the buffed bonus AD and the fight engine applies it to autos; the "
    "w_hunt option (default on) withholds the whole hunt when off",
    "W's bonus movement speed (20/22.5/25/27.5/30% by rank, a real "
    "leveling row corroborated by the binary's MoveSpeedAmount) is "
    "sourced but NOT modeled: stats publishes the move_speed_flat / "
    "move_speed_percent pair and the shared resolve_move_speed fold "
    "(soft caps included), and this slot is not yet wired onto it; the "
    "one live consumer is item_effects' "
    "adaptive_force_per_total_move_speed (Swiftmarch) — an uncertified "
    "movement number would become damage.  The hunt's 1s "
    "untargetability, the Packmate vanish/reappear and the 1.75s "
    "hunt extension from casting R are state",
    "P (We Are More) prices the pack's sourced share of Hounds' Pursuit: "
    "R's own 'Physical Damage per Packmate' row (12.5/20/27.5 + 10% "
    "bonus AD) times the sourced Packmate count — 2/3/4/5 by level "
    "(wiki P text; binary PackmateCap breakpoints at levels 9/12/15), "
    "or the hunt-raised 4/5/6/7 while w_hunt is on (wiki W note).  Both "
    "columns are confirmed by the wiki R notes' packmate-total table "
    "(e.g. levels 16-18: 5 x 27.5 = 137.5 + 50% bonus AD, 7 x 27.5 = "
    "192.5 + 70% bonus AD).  The whole pack lands at the end of R's "
    "0.75s channel, emitted as proc_count = the Packmate count with ONE "
    "hit per part — the engine prices sum(part.amount x part.count) x "
    "proc_count, so carrying the pack size in both fields would square "
    "it — and the row is withheld entirely while Hounds' Pursuit is "
    "unlearned, which keeps it exactly one pack landing per R cast",
    "P Packmate BASIC ATTACKS are documented-not-modeled: their formula "
    "exists only in the game binary (NaafiriP's PackmateTotalDamage = "
    "level-interpolated 10-20 + 4% bonus AD, PackmateBaseAS 0.688) "
    "because the wiki's Pets entry is not part of the local cache "
    "(data/champions.json P says only 'See Pets for full details'), and "
    "the pack's uptime, leap range, frenzy stacking and taunt are "
    "unmodeled state on top; the E4 summon precedent requires a cached "
    "wiki row for a pet's per-attack damage",
    "R (Hounds' Pursuit) prices Naafiri's own dash hit; its shield "
    "(100/150/200 + 150% bonus AD) and the 99% slow stay state",
]

# No MODULE_COVERAGE: every slot now emits a priced row — P the pack's
# share of Hounds' Pursuit, W the hunt's stat_buff — which is exactly
# what the contract derives from SLOTS.


# pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Naafiri self-healing events from its authored packet."""
    healing = []
    q_rank = _healing.parsed_rank(ability_damages, "Q")
    q_heal = _healing.extract_named(
        _healing.ability_json(champion_data, "Q"), "Heal", q_rank, champion_stats
    )
    # One heal per Q cast: the module emits the initial hit at the cast
    # boundary, then the bleed ticks and the recast share later
    # timestamps, so the heal anchors to the cast's first hit (the recast
    # hits an already-bleeding champion the same cast).  Matching cast
    # time to event time exactly drops a cast whose published time the
    # engine rounded, so the anchor is resolved by ``HealAnchor.CAST``.
    for payment in _healing.payments(
        _healing.HealAnchor.CAST, "Q", damage_events, cast_timeline
    ):
        _healing.heal_from_damage(
            healing,
            payment.event,
            q_heal,
            "Darkin Daggers",
            link_to_damage=False,
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Naafiri")(derive_self_healing)
