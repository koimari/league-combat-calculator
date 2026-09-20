"""Naafiri: full-entry-reviewed packet module.

The game binary names her W and R slots the opposite way round from the live
kit; see the Champions section of ``TRAPS.md`` before any patch-day check.
Everything here is named by the live kit, matching ``data/champions.json``.
Q (Darkin Daggers) prices the initial hit plus ten sourced 0.5s bleed ticks.
The recast against an already-bleeding champion adds the cached Minimum and
Maximum Bonus Physical Damage rows interpolated on the target's missing
health; the remaining-bleed term is the ticks, so nothing is double-priced.
Q's heal is the cached "Heal" row through ``derive_self_healing``.
W (The Call of the Pack) is a BUFF-phase ``stat_buff``: 20% of TOTAL AD as
bonus AD, prose-only and corroborated by ``NaafiriADPercentBoost``, plus the
ranked ``move_speed_percent``.  Mutating ``ctx.stats`` in-parse is what lets
Q, E, R and the packmate row scale off the buffed AD.
E (Eviscerate) prices the dash and the arrival Flurry together.
P (We Are More) prices the packmate coupling: the summon deals nothing and the
pack's contribution is R's own "Physical Damage per Packmate" row.  ``w_hunt``
selects the raised cap and the AD steroid together, so there is one hunt
state.  Packmate basic attacks stay unpriced; see ASSUMPTIONS.
"""

from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import BUFF, SlotCtx
from .healing_contract import SelfHealCtx, self_healing_rule
from .inputs import bool_option
from .module_helpers import ability_slot, buff_window_share, ranked_slot
from .packet_module import build_packet_module
from .shared_mechanics import multi_pass_damage
from .slot_entries import STEROID_ZERO, damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named, extract_value

PACKET_SHA256 = "422062ecdd781eb5a57f34b7b9c3221288b03f12811cb2d0788a6a877afe4896"


# The bleed cadence is binary DataValues (NaafiriQ.BleedInterval /
# BleedDuration): 0.5s first tick, ten ticks over the 5-second window.
# The recast fires one interval after the first cast ("can be recast
# after 0.5 seconds and within 4 seconds").
_NAAFIRI_Q_SPELL = spell_object("Naafiri", "NaafiriQ")
_BLEED_TICK_INTERVAL = data_value(_NAAFIRI_Q_SPELL, "BleedInterval")
_BLEED_DURATION = data_value(_NAAFIRI_Q_SPELL, "BleedDuration")
_BLEED_TICKS = round(_BLEED_DURATION / _BLEED_TICK_INTERVAL)
_BLEED_FIRST_TICK = _BLEED_TICK_INTERVAL
_RECAST_TIME_OFFSET = _BLEED_TICK_INTERVAL

# W (The Call of the Pack) grants "20% AD bonus attack damage" — the
# binary's NaafiriADPercentBoost on the SWAPPED record
# Characters/Naafiri/Spells/NaafiriRAbility/NaafiriR, whose BonusAD
# calculation reads stat 2 (attack damage) with no mStatFormula override,
# i.e. 20% of TOTAL AD granted as bonus AD.  The hunt lasts the same
# spell's Duration DataValue.
_NAAFIRI_R_SPELL = spell_object("Naafiri", "NaafiriR")
_HUNT_AD_PERCENT = data_value(_NAAFIRI_R_SPELL, "NaafiriADPercentBoost") * 100.0
_HUNT_DURATION = data_value(_NAAFIRI_R_SPELL, "Duration")

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


@ranked_slot
def _call_of_the_pack(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """W: the hunt's 20%-of-total-AD bonus-attack-damage steroid.

    See the module docstring's W entry for the two-channel sourcing of
    the 20% (wiki prose + the swapped binary record's
    ``NaafiriADPercentBoost``) and for why the branch's bonus movement
    speed stays a documented rider instead of a ``stat_buff`` key.
    """

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
    share = buff_window_share(ctx, _HUNT_DURATION)
    granted = _HUNT_AD_PERCENT / 100.0 * ctx.stat("attack_damage")
    bonus = granted * share
    movement = extract_value(ability, "Bonus Movement Speed", rank)
    ctx.stats["attack_damage"] = ctx.stat("attack_damage") + bonus
    ctx.stats["bonus_attack_damage"] = ctx.stat("bonus_attack_damage") + bonus
    entry["stat_buff"] = {
        "bonus_attack_damage": bonus,
        # Both halves of one expiring cast take the same share: a
        # stat_buff is one scalar for the whole fight, so a term left at
        # full magnitude reads the same in a 5s fight and a 30s one.
        "move_speed_percent": movement * share,
    }
    entry["detail"] = (
        f"+{granted:.1f} bonus attack damage for {_HUNT_DURATION:g}s "
        f"({_HUNT_AD_PERCENT:g}% of total AD, wiki W prose corroborated by "
        f"the game binary's NaafiriADPercentBoost); +{bonus:.1f} over the "
        "fight window.  The hunt also raises the Packmate cap (priced on "
        f"the We Are More row) and grants +{movement:g}% movement speed "
        f"({movement * share:g}% over the window), published as a "
        "move_speed_percent stat buff — a term in the shared "
        "movement-speed fold.  The untargetability and the Packmate "
        "vanish/reappear are state."
    )
    return entry


_call_of_the_pack.phase = BUFF


@ability_slot("P")
def _we_are_more(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """P: the pack's sourced share of Hounds' Pursuit (Illaoi-P pattern).

    The innate summon deals no damage of its own.  What the Packmates
    contribute is R's own "Physical Damage per Packmate" leveling row
    times the sourced Packmate count at this level and hunt state; their
    basic attacks stay unpriced with a named receipt (module docstring).
    """
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


@ranked_slot
def _darkin_daggers(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Q: initial dagger + 10 bleed ticks + the recast's bonus damage."""

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

    if bool(ctx.option("q_recast")):
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
            if bool(ctx.option("q_recast"))
            else "; recast bonus not priced (q_recast off)"
        )
    )
    return entry


# E: dash damage plus the Flurry explosion on arrival.
_eviscerate = multi_pass_damage(
    "physical",
    passes=(("Dash Physical Damage", 0.0), ("Flurry Physical Damage", 0.5)),
    detail=(
        "Dash Physical Damage + Flurry Physical Damage == Total Physical "
        "Damage (the flurry explodes on arrival, 0.5s cadence authored)."
    ),
)


# Reviewed crowd control, read from the cached kit.  Q (Darkin Daggers)
# "deals physical damage to enemies hit and inflicts them with a bleed"
# with no control clause, and E (Eviscerate) dashes and explodes with
# none either.  R (Hounds' Pursuit) arrives and "deals physical damage
# and slows the target by 99% for 0.25 seconds" — the slow lands on
# Naafiri's own arrival hit.  P's Packmates land with her and apply
# nothing of their own; W authors no damage part.
MODULE_CC = {"P": "none", "Q": "none", "E": "none", "R": "slow", "W": "none"}

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

OPTIONS: list[dict[str, Any]] = [
    *list(OPTIONS),
    bool_option(
        "q_recast",
        True,
        label="Q recast hits the bleeding target (bonus damage + heal)",
        rotation={"role": "self_state", "slot": "Q"},
    ),
    bool_option(
        "w_hunt",
        True,
        label="W hunt is active (20% AD bonus attack damage + the raised "
        "Packmate cap)",
        # A SELF steroid, so self_state and not setup: W's ordering edge is
        # structural already, since the slot's stat_buff on
        # ``bonus_attack_damage`` puts buffs-first ahead of Q/E/R.
        rotation={"role": "self_state", "slot": "W"},
    ),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "Q (Darkin Daggers) prices the initial hit and 10 sourced 0.5s bleed ticks, "
    "per-tick x 10.",
    "Q's recast bonus interpolates the Minimum and Maximum rows by missing health, "
    "q_recast (default on).",
    "The recast's remaining bleed is already in those ticks and is not "
    "double-counted.",
    "Q's recast on a champion heals Naafiri the cached 45 to 105 + 40% bonus AD, one "
    "heal per cast.",
    "The self-heal rule authors it and the support scanner defers, keeping one ledger "
    "receipt.",
    "E (Eviscerate) prices the dash plus the Flurry explosion, summing to the Total "
    "Physical Damage row.",
    "W (The Call of the Pack) grants bonus AD of 20% of total AD for the 5s hunt "
    "(wiki W prose).",
    "The binary's NaafiriADPercentBoost 0.20 sits on the swapped R record, per the "
    "module docstring.",
    "It is a buff-phase stat_buff, so Q, E, R, Packmate and autos price off it; "
    "w_hunt (default on) gates it.",
    "W's bonus movement speed, 20/22.5/25/27.5/30% by rank, is a real leveling row "
    "matching the binary.",
    "It publishes as a move_speed_percent stat_buff on the same w_hunt gate, through "
    "resolve_move_speed.",
    "It takes the same buff_window_share as the AD term: the hunt expires at 5s and a "
    "stat_buff is one scalar.",
    "The hunt's 1s untargetability, the Packmate vanish and the 1.75s R extension are "
    "state.",
    "P (We Are More) prices the pack's share of Hounds' Pursuit: R's 12.5/20/27.5 + "
    "10% bonus AD per Packmate.",
    "The Packmate count is the sourced 2/3/4/5 by level, with binary breakpoints at "
    "levels 9, 12 and 15.",
    "While w_hunt is on it is the raised 4/5/6/7 (wiki W note); the wiki R table "
    "confirms both columns.",
    "The whole pack lands at the end of R's 0.75s channel as proc_count = Packmate "
    "with one hit per part.",
    "The engine prices sum(part.amount x count) x proc_count, so carrying the size "
    "twice would square it.",
    "The row is withheld while Hounds' Pursuit is unlearned, keeping one pack landing "
    "per R cast.",
    "P Packmate BASIC ATTACKS are documented-not-modeled: the formula lives only in "
    "the game binary.",
    "NaafiriP's PackmateTotalDamage is 10 to 20 + 4% bonus AD by level at "
    "PackmateBaseAS 0.688.",
    "The wiki Pets entry is outside the local cache: cached P says only 'See Pets for "
    "full details'.",
    "P's pack uptime, leap range, frenzy stacking and taunt are unmodeled state on "
    "top.",
    "The summon precedent requires a cached wiki row for a pet's per-attack damage.",
    "R (Hounds' Pursuit) prices Naafiri's own dash hit; its shield "
    "(100/150/200 + 150% bonus AD) and the 99% slow stay state",
]

# No MODULE_COVERAGE: every slot now emits a priced row — P the pack's
# share of Hounds' Pursuit, W the hunt's stat_buff — which is exactly
# what the contract derives from SLOTS.


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Resolve Naafiri self-healing events from its authored packet."""
    healing = []
    q_rank = _healing.parsed_rank(ctx.ability_damages, "Q")
    q_heal = extract_named(
        _healing.ability_json(ctx.champion_data, "Q"),
        "Heal",
        q_rank,
        ctx.champion_stats,
    )
    # One heal per Q cast: the module emits the initial hit at the cast
    # boundary, then the bleed ticks and the recast share later
    # timestamps, so the heal anchors to the cast's first hit (the recast
    # hits an already-bleeding champion the same cast).  Matching cast
    # time to event time exactly drops a cast whose published time the
    # engine rounded, so the anchor is resolved by ``HealAnchor.CAST``.
    for payment in ctx.payments(_healing.HealAnchor.CAST, "Q"):
        _healing.heal_from_damage(
            healing,
            payment.event,
            q_heal,
            "Darkin Daggers",
            link_to_damage=False,
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Naafiri")(derive_self_healing)
