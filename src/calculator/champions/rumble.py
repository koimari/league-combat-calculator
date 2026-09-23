"""Rumble: packet module over the heat system.

Two cached-row traps it pays are in ``TRAPS.md``: a ``Bonus Damage`` row that
is a monster-only cap, and the ``% of maximum health`` spelling that fell to 0.
Q (Flamespitter) prices "Maximum Magic Damage", the whole 3-second
flamethrower, 15 ticks of "Magic Damage per Tick"; the Minimum, per-Second
and per-Tick rows are views of the same damage.
E (Electro Harpoon) carries one harpoon's cached MR shred as a target_debuff.
R (The Equalizer) prices all 20 Burning ticks, 0.25s apart over 5 seconds.
P (Junkyard Titan) carries the real on-hit formula, an Overheated per-level
"Bonus Magic Damage" array with one AP and one target-max-health modifier.
W (Scrap Shield) is a sourced self-shield with no damage row; shield-only, it
cannot carry ``attach_self_shield``, so the scanner prices it at scope "self".
Overheat is derived, not declared: the slot states the cached heat rule
(Heat per cast, ceiling, lockout, decay) and the cast plan walks it, placing
each lockout where it happens, with E on its recharge rather than the gap
between banked harpoons, and rating the cached bonus attack speed by the
windows' share of the fight.  Danger Zone is heat state: every slot prices
its base row and the Enhanced rows go unread.
"""

import math
import re
from typing import Any

from ..ability_prose import CachedSentence, extract_description_duration
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .charge_cadence import ChargeRule
from .engine import DAMAGE, ONHIT, SlotCtx, SlotParser
from .module_helpers import ability_slot
from .packet_module import build_packet_module
from .slot_entries import on_hit_entry
from .slot_extract import (
    ability_name,
    extract_named,
    extract_value,
    find_named_leveling,
)
from .slotlib import simple_damage

PACKET_SHA256 = "c18c1e6e7005c17066acf180ec68a2013bb656c20a88655a536f0a2bc9a078f5"


# The heat system's three numbers live in cached prose, not in a leveling
# row, so they are read with these and every miss raises.  Slot casts:
# "Rumble generates 20 Heat to activate his flamethrower"; the ceiling:
# "becomes Overheated while at 150 Heat"; the window: "disabling his
# abilities as his Heat decays back down to 0 over 4 seconds".
_HEAT_PER_CAST_RE = re.compile(r"generates\s+(?P<value>\d+(?:\.\d+)?)\s+Heat")
_MAX_HEAT = CachedSentence(
    re.compile(r"becomes\s+Overheated\s+while\s+at\s+(?P<value>\d+(?:\.\d+)?)\s+Heat"),
    missing=(
        "Rumble P: the cached innate no longer states the Overheat ceiling "
        "('becomes Overheated while at N Heat')"
    ),
)

# The slots whose cast the cache says generates Heat.  R is deliberately
# absent: The Equalizer delays the decay ("or The Equalizer within 2
# seconds") and generates none.  One sentence, one refusal per slot.
_HEAT_GENERATOR_SLOTS = ("Q", "W", "E")
_HEAT_PER_CAST = {
    slot: CachedSentence(
        _HEAT_PER_CAST_RE,
        missing=(
            f"Rumble {slot}: the cached entry no longer states its Heat "
            "generation ('Rumble generates N Heat')"
        ),
    )
    for slot in _HEAT_GENERATOR_SLOTS
}
_OVERHEAT_EFFECT_INDEX = 2


# The decay half of the same innate, in the same cached sentence: "decays
# by 10 Heat per second after not using any basic ability within 4 seconds
# or The Equalizer within 2 seconds."
_HEAT_DECAY = CachedSentence(
    re.compile(
        r"decays\s+by\s+(?P<rate>\d+(?:\.\d+)?)\s+Heat\s+per\s+second"
        r"[^.]*?within\s+(?P<basic>\d+(?:\.\d+)?)\s+seconds"
        r"[^.]*?within\s+(?P<ultimate>\d+(?:\.\d+)?)\s+seconds"
    ),
    missing=(
        "Rumble P: the cached innate no longer states its Heat decay "
        "('decays by N Heat per second after not using any basic ability "
        "within N seconds or The Equalizer within N seconds')"
    ),
)


def _heat_decay(ctx: SlotCtx) -> tuple[float, float, float]:
    """The cached decay rate and the two delays that start it.

    Read from the innate's own sentence, so a reworked decay raises here
    rather than leaving the fight's Heat walk filling a bar that never
    empties.
    """
    passive = ctx.ability("P")
    if passive is None:
        raise ValueError("Rumble P: the cached Junkyard Titan entry is missing")
    match = _HEAT_DECAY.match(passive)
    return (
        float(match.group("rate")),
        float(match.group("basic")),
        float(match.group("ultimate")),
    )


def _heat_mechanics(ctx: SlotCtx) -> tuple[float, float, float]:
    """The cached Heat ceiling, per-cast gain, and Overheat window.

    Every number is read out of the cached descriptions the sentences above
    quote, so a reworded or reworked cache raises here instead of pricing a
    stale constant.
    """
    passive = ctx.ability("P")
    if passive is None:
        raise ValueError("Rumble P: the cached Junkyard Titan entry is missing")
    ceiling = _MAX_HEAT.value(passive)
    gains = {
        sentence.value(ctx.ability(slot) or {})
        for slot, sentence in _HEAT_PER_CAST.items()
    }
    if len(gains) != 1:
        raise ValueError(
            "Rumble: the cached Q/W/E entries disagree on Heat per cast "
            f"({sorted(gains)}) - the shared per-cast gain priced here has "
            "changed upstream"
        )

    window = extract_description_duration(passive, _OVERHEAT_EFFECT_INDEX)
    if not window:
        raise ValueError(
            "Rumble P: the cached Overheated effect no longer states its "
            "duration ('decays back down to 0 over N seconds')"
        )
    return ceiling, gains.pop(), float(window)


# Flamespitter's cadence is the cache's own, and it is stated twice.  The
# entry reads "Rumble generates 20 Heat to activate his flamethrower for 3
# seconds, spewing forth flames in a frontal cone every 0.25 seconds.
# Enemies hit by the flame are scorched for 0.6 seconds, taking magic
# damage every 0.25 seconds as well as upon being hit if not currently
# scorched" — flames at 0.00 through 3.00 are thirteen instances on the
# beat, and the last flame's 0.6-second scorch tails two more at 3.25 and
# 3.50.  Fifteen, which is exactly the ratio the rank rows already carry
# (Maximum Magic Damage == 15 x Magic Damage per Tick at every rank), the
# equality ``_flamespitter_full_channel`` re-checks against the cache.
_Q_TICKS = 15
_Q_TICK_INTERVAL = data_value(spell_object("Rumble", "RumbleFlameThrower"), "TickRate")

_flamespitter = simple_damage(attr="Maximum Magic Damage", dmg_type="magic")


def _flamespitter_full_channel(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the full 3-second flamethrower on its sourced 0.25-second beat."""
    entry = _flamespitter(ctx)
    if entry is None:
        return None
    entry["target_max_health_sensitive"] = True
    ability = ctx.ability()
    rank = ctx.rank_for()
    per_tick = extract_named(
        ability, "Magic Damage per Tick", rank, ctx.stats, ctx.target
    )
    total = float(entry["total_raw"])
    # The cached rows are rounded to three decimals apiece, so they agree
    # to a tenth of a percent rather than exactly; a real change to the
    # tick count moves this ratio by 1/15th and trips the guard.
    if not math.isclose(per_tick * _Q_TICKS, total, rel_tol=1e-3):
        raise ValueError(
            "Rumble Q: the cached 'Magic Damage per Tick' x 15 no longer "
            "equals 'Maximum Magic Damage' - the 15-tick channel pinned "
            "here has changed upstream"
        )
    # One beat, authored as the cache states it: the first flame lands at
    # the cast (castTime is "none") and the fifteenth 3.5 seconds later.
    # The row's total stays the sourced Maximum row, split evenly, so the
    # rounding above never leaks into the number.
    entry["parts"] = (
        DamagePart(
            "magic",
            total / _Q_TICKS,
            count=_Q_TICKS,
            time_offset=0.0,
            hit_interval=_Q_TICK_INTERVAL,
        ),
    )
    entry["detail"] = (
        f"{_Q_TICKS} ticks at {_Q_TICK_INTERVAL:g}-second intervals "
        "(3-second flamethrower plus the last flame's 0.6-second scorch)"
    )
    return entry


_flamespitter_full_channel.phase = "damage"


def _overheat_attack_speed(ability: dict[str, Any], level: int) -> float:
    """The Overheated bonus attack speed at *level*, or raise.

    ``extract_value`` indexes a row's LAST value when the level exceeds the
    row's axis, so a shortened cache would silently price the level-20
    maximum at every level.  The row's own length is checked first (the
    Aphelios Weapon Master guard).
    """
    leveling = find_named_leveling(ability, "Per-Level Scaling")
    modifiers = leveling.get("modifiers") if isinstance(leveling, dict) else None
    values = modifiers[0].get("values") if modifiers else None
    if not isinstance(values, list) or len(values) < level:
        raise ValueError(
            "Rumble P: the cached 'Per-Level Scaling' row does not carry the "
            f"Overheated bonus attack speed at level {level} "
            f"({0 if not isinstance(values, list) else len(values)} value(s) "
            "on a per-level axis)"
        )
    granted = extract_value(ability, "Per-Level Scaling", level)
    if granted <= 0:
        raise ValueError(
            "Rumble P: the cached 'Per-Level Scaling' row prices the "
            f"Overheated bonus attack speed at {granted} for level {level}"
        )
    return granted


@ability_slot("P")
def _junkyard_titan(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """P: the Overheated window — its on-hit damage, bonus AS, and lockout.

    The "Bonus Magic Damage" leveling row is a per-LEVEL array (20
    entries), so it is read at ``ctx.level``, not at an ability rank —
    Junkyard Titan is an innate with no rank of its own.  ``extract_named``
    resolves all three modifiers together: the flat per-level term,
    "% AP", and "% of the target's maximum health".

    The damage row rides the basic-attack stream, because that is where the
    game puts it and the only channel a passive slot has: ``passive`` is
    not an orderable cast (``pipeline.validate_cast_order_for_kit``
    refuses it), so a ``parts``-priced passive row parses and then never
    lands.

    Nothing about Heat is declared here any more.  The slot states the
    cached rule — what a basic ability cast adds, the ceiling, the lockout,
    and the decay with its delay — and the fight's own cast plan walks it
    (``fight/rotation/cast_resource_lockout.py``).  How often the mech
    Overheats, how many seconds of bonus attack speed that buys and which
    swings are empowered are all read off the plan that happened.
    """
    per_auto = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )
    entry = on_hit_entry(ability_name(ability), per_auto, "magic")
    entry["target_max_health_sensitive"] = True

    ceiling, per_cast, window = _heat_mechanics(ctx)
    decay_rate, basic_delay, ultimate_delay = _heat_decay(ctx)
    entry["cast_resource_lockout"] = {
        "slots": _HEAT_GENERATOR_SLOTS,
        "per_cast": per_cast,
        "ceiling": ceiling,
        "seconds": window,
        "decay_per_second": decay_rate,
        "decay_delay_seconds": basic_delay,
        "ultimate_slot": "R",
        "ultimate_delay_seconds": ultimate_delay,
    }
    # The FULL grant: the fight rates it by the share of the fight the
    # derived windows cover, because the bonus applies only inside them.
    entry["stat_buff"] = {
        "bonus_attack_speed": _overheat_attack_speed(ability, ctx.level)
    }
    casts_per_window = math.ceil(ceiling / per_cast)
    entry["detail"] = (
        f"Overheated: {per_auto:.2f} bonus magic damage on-hit "
        f"(level-{ctx.level} flat + 25% AP + 4% target maximum health) on "
        "every swing inside an Overheat window; the windows are derived "
        f"from the fight's own cast plan ({int(ceiling)} Heat at "
        f"{int(per_cast)} per basic ability cast = {casts_per_window} casts "
        f"each, decaying {decay_rate:g} Heat per second once the mech has "
        f"gone {basic_delay:g}s without a basic ability and "
        f"{ultimate_delay:g}s without The Equalizer). Each window is "
        f"{window:g}s of ability lockout, taken where it happens, and "
        "the same seconds of bonus attack speed; the 'Bonus Damage' row is "
        "the monster-only cap on the %max-health term, not a damage source"
    )
    return entry


_junkyard_titan.phase = ONHIT


# E's harpoon "inflicting them with magic resistance reduction for 4
# seconds": each harpoon's window is the binary's ShredDuration.
_E_SHRED_DURATION = data_value(spell_object("Rumble", "RumbleGrenade"), "ShredDuration")
_E_SHRED_ROW = "Magic Resistance Reduction"


def _with_harpoon_shred(compiled: SlotParser) -> SlotParser:
    """E: the packet's harpoon hit, carrying one harpoon's cached MR shred.

    The cache stacks the shred "up to 2 times"; the engine's percent shred
    cannot stack, so this is the one-harpoon row, never "Total MR Reduction".
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = compiled(ctx)
        ranked = ctx.ranked()
        if entry is None or ranked is None:
            return entry
        ability, rank = ranked
        shred = extract_value(ability, _E_SHRED_ROW, rank)
        if shred <= 0:
            raise ValueError(
                f"Rumble E: the cached {_E_SHRED_ROW!r} row prices {shred} at "
                f"rank {rank}"
            )
        entry["target_debuff"] = {
            "mr_reduction_percent": shred,
            "duration": _E_SHRED_DURATION,
        }
        return entry

    parse.phase = getattr(compiled, "phase", DAMAGE)
    return parse


# Cached kit review.  E's harpoon deals magic damage while "inflicting them
# with magic resistance reduction ... and slowing them for 2 seconds" — the
# shred is a resistance effect, the slow is the control.  R's field marks
# enemies burning, "taking magic damage every 0.25 seconds and being slowed
# by 35%".  Q's flames only scorch: the entry's damage clauses carry no
# control word, so the answer is a reviewed "none", and the fifteen ticks
# authored above are what carries it to the event ledger.  W is a shield,
# and P answers per part (``_junkyard_titan``): the Overheated row can only
# carry a reviewed kind when it prices a single empowered swing, because
# nothing sources the arrival times a multi-auto row aggregates.
MODULE_CC = {"E": "slow", "Q": "none", "R": "slow", "P": "none", "W": "none"}

# What this module says about its charge slot (charge_cadence.py).
CHARGE_RULES = {
    "E": ChargeRule(
        why=(
            "E (Electro Harpoon) banks harpoons on its cached 6s "
            "rechargeRate and its cached stock is 2; the 0.5s cooldown is "
            "only the gap between two banked harpoons, so the Heat walk "
            "counts the harpoons the recharge allows."
        ),
    )
}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Rumble",
    PACKET_SHA256,
    packet_tick_fixes={
        "The Equalizer": {
            "count": 20,
            "first_tick": 0.25,
            "tick_interval": 0.25,
            "dot_duration": 5.0,
        }
    },
    # The harpoon "deals magic damage to the first enemy hit" once — the
    # boundary claim that carries MODULE_CC's reviewed answer for E into
    # the event ledger.  R already authors its own twenty-tick timing.
    single_hit_slots=frozenset({"E"}),
    slot_parsers={"Q": _flamespitter_full_channel, "P": _junkyard_titan},
    slot_wrappers={"E": _with_harpoon_shred},
    cc_kinds=MODULE_CC,
    charge_rules=CHARGE_RULES,
)
ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "Q (Flamespitter) prices the cached Maximum Magic Damage row for the whole "
    "3-second flamethrower.",
    "That is 62.5/93.75/125/156.25/187.5 + 131.25% AP + 7.5 to 10% of target maximum "
    "health.",
    "It equals 15 x Magic Damage per Tick at every rank, landing at 0.25s intervals "
    "from the cast.",
    "The cached entry states that cadence, plus the last flame's 0.6s scorch.",
    "The Danger Zone per-level Bonus Damage row is the monster cap, indexed by level, "
    "and stays unpriced.",
    "R (The Equalizer) prices all 20 Burning ticks at 0.25s intervals over up to 5 "
    "seconds.",
    "That is per-tick x20 == Maximum Magic Damage 600/1000/1400 + 175% AP.",
    "The initial rocket impact has no separate damage row in the cache.",
    "E (Electro Harpoon) shreds MR by the cached one-harpoon Magic Resistance "
    "Reduction row, 10 to 18% by rank.",
    "The shred lasts the binary's ShredDuration, 4 seconds, and lands after E's own "
    "damage.",
    "It is weighted by the share of the fight its 4-second windows cover; one-rotation "
    "mode applies it in full.",
    "Two harpoons inside 4 seconds stack to the cached Total MR Reduction row; only one "
    "stack is priced.",
    "So the banked opening pair understates the shred, and E's second harpoon meets "
    "none of the first's.",
    "E is scheduled on its cached 6s rechargeRate with its cached stock of 2 harpoons.",
    "The Danger Zone half of the heat system is state outside the damage model.",
    "Q, E and R price their base rows and the Enhanced Danger Zone rows go unread.",
    "W's Danger Zone Bonus of +50% shield strength is not applied: the base Shield "
    "Strength row is priced.",
    "Only the Overheated half of heat is priced, walked over the fight's own cast "
    "plan.",
    "P (Junkyard Titan) prices the Overheated on-hit bonus, not the monster-only cap: "
    "5 to 44.12 by level.",
    "It adds 25% AP and 4% of target maximum health, from cached P effect 3's Bonus "
    "Magic Damage row.",
    "The binary's RumbleHeatSystem TotalBaseDamage, 0.25 AP coefficient and 0.04 "
    "bonus corroborate it.",
    "The Bonus Damage row, 65 to 163.32 by level, is that cap and never binds against "
    "a champion.",
    "Every heat number is read from cached prose: 20 Heat per Q, W or E cast and a 150 "
    "Heat ceiling.",
    "The window is 4 seconds, 'decays back down to 0 over 4 seconds', so 8 basic "
    "casts fill the bar.",
    "Heat decays 10 per second once 4s pass without a basic ability and 2s without "
    "The Equalizer.",
    "Each window opens where the bar fills and silences every cast inside it.",
    "Every swing inside a window carries the on-hit bonus; no swing outside one does.",
    "The 50% to 142.54% by level bonus attack speed is a stat_buff weighted by the "
    "windows' fight share.",
    "That weighting is exact for attack speed, which is linear in the bonus percent.",
    "An autos-only fight casts nothing, builds no Heat and Overheats zero times.",
    "W (Scrap Shield) is a sourced self-shield with no damage row: 25/55/85/115/145 + "
    "30% AP + 4% health.",
    "It holds 1.5 seconds.",
    "A shield-only ability cannot carry attach_self_shield, which rides damage-event "
    "rows.",
    "W stays priced by the ally-support scanner, which derives it at target scope "
    "'self'.",
    "The wiki spelling '% of maximum health' is mapped in the scaling unit table.",
    "W's bonus movement speed row is not damage and remains state.",
]
# No MODULE_COVERAGE: every slot is emitted and priced, which is exactly
# what ``module_contract.default_coverage`` derives from SLOTS.  Restating
# it is refused as a second home for the same fact.
