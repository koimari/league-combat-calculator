"""Rumble: packet module over the heat system.

Two cached-row traps this module already pays are in the Champions
section of ``TRAPS.md``: a ``Bonus Damage`` leveling row that is a
monster-only cap rather than a damage source, and the
``% of maximum health`` unit spelling that once fell through
``champions/scaling.py`` to ``0.0``.

What each slot prices:

- Q (Flamespitter) prices the "Maximum Magic Damage" row, the whole
  3-second flamethrower, which is 15 ticks of "Magic Damage per Tick"
  at every rank.  The other Flamespitter rows are Minimum, per-Second
  and per-Tick views of the same damage.
- R (The Equalizer) prices all 20 Burning ticks: "Magic Damage per
  Tick" at 0.25s over up to 5 seconds, which the cache states as a
  total of 20 instances.
- P (Junkyard Titan) carries a real sourced on-hit formula in its
  Overheated effect, a per-level "Bonus Magic Damage" array with one AP
  and one target-max-health modifier, corroborated term for term by the
  binary's ``RumbleHeatSystem``.
- W (Scrap Shield) is a sourced self-shield with no damage row.  Being
  shield-only it cannot carry ``attach_self_shield``, which rides
  damage-event rows, so the ally-support scanner prices it at target
  scope "self" (the Ekko-W precedent, pinned by
  ``tests/test_support_effects.py``).

Overheat is derived, not declared.  The slot states the cached heat
rule and the fight's cast plan walks it
(``fight/rotation/cast_resource_lockout.py``): Heat per basic-ability
cast, the ceiling, the lockout and the decay, every number read from
the cached prose, so a reworked cache raises rather than pricing a
stale constant.  The walk decides how often the bar fills, where each
lockout sits inside the fight rather than off the end of the horizon,
how many seconds of bonus attack speed the windows buy, and which
swings land empowered.  None of the four is a scenario option, and the
plan can answer them because E is scheduled on its recharge
(``champions/charge_cadence.py``) and not on the gap between two banked
harpoons.  The bonus attack speed is the full cached grant rated by the
share of the fight the windows cover, which is exact because attack
speed is linear in the bonus percent.

Danger Zone is heat state and stays unpriced: Q, E, R and W price their
base rows and the Enhanced rows go unread.
"""

import math
import re
from typing import Any

from ..ability_prose import CachedSentence, extract_description_duration
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .charge_cadence import ChargeRule
from .engine import ONHIT, SlotCtx
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
            "rechargeRate and its cached stock is 2. Pricing the 0.5s "
            "inter-charge cooldown as the cadence is what put 16 basic "
            "ability casts in a ten-second fight, and it is the stated "
            "blocker for deriving Heat from the cast plan."
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
    cc_kinds=MODULE_CC,
    charge_rules=CHARGE_RULES,
)
ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "Q (Flamespitter) prices the cached Maximum Magic Damage row "
    "(62.5/93.75/125/156.25/187.5 + 131.25% AP + 7.5% : 10% of the "
    "target's maximum health) — the whole 3-second flamethrower, equal "
    "to 15 x Magic Damage per Tick at every rank.  The generated packet "
    "read the Danger Zone effect's per-level Bonus Damage row, which is "
    "the monster damage cap and is indexed by level, not rank.  The row "
    "lands as 15 ticks at 0.25-second intervals from the cast, the "
    "cadence the cached entry states ('spewing forth flames ... every "
    "0.25 seconds', plus the last flame's 0.6-second scorch).  The "
    "Danger Zone (Enhanced) rows remain unpriced.",
    "R (The Equalizer) prices all 20 Burning ticks (Magic Damage per "
    "Tick x20 == Maximum Magic Damage 600/1000/1400 + 175% AP) at "
    "0.25-second intervals over up to 5 seconds (packet_module "
    "local packet timing declaration). The initial rocket impact has no separate "
    "damage row in the cache.",
    "The Danger Zone half of the heat system is state outside the damage "
    "model: Q/E/R rotation numbers price their base rows and the Enhanced "
    "(Danger Zone) rows go unread, and W's Danger Zone Bonus (+50% shield "
    "strength) is not applied - the base Shield Strength row is priced. "
    "Only the Overheated half of heat is priced, through the "
    "overheat_windows axis.",
    "P (Junkyard Titan) prices the Overheated on-hit bonus magic damage - "
    "5:44.12 by level + 25% AP + 4% of the target's maximum health per "
    "empowered basic attack (cached P effect 3, leveling attribute 'Bonus "
    "Magic Damage', a per-level array; corroborated by the game binary's "
    "RumbleHeatSystem TotalBaseDamage / 0.25 AP coefficient / "
    "OverheatPercBonusDamage 0.04). The fight engine does not simulate "
    "heat, so overheat_autos is the explicit count of empowered autos "
    "(0 = none, the default). The 'Bonus Damage' leveling row "
    "(65:163.32 by level) is the "
    "monster-only cap on the %max-health term, not a damage source, and "
    "never binds against a champion target. Reclassified from "
    "out_of_scope to modeled; the packet's no_damage label was incomplete, "
    "not stale.",
    "P (Junkyard Titan) heat axis: overheat_windows declares how many "
    "times the mech reaches the cached Heat ceiling during the fight "
    "(0 = never, the default). Every number the axis prices is read from "
    "the cached prose and nothing is a constant here: the ceiling (150 "
    "Heat, 'becomes Overheated while at 150 Heat'), the per-cast gain "
    "(20 Heat, stated identically by Q, W and E, and they must agree) and "
    "the window (4 seconds, 'decays back down to 0 over 4 seconds') — so "
    "8 basic-ability casts fill the bar. A declared axis rather than a "
    "cast-plan derivation because the cast plan is not yet trustworthy "
    "for heat: E is scheduled on its cached 0.5s inter-charge cooldown "
    "instead of its 6s rechargeRate, which puts 16 basic casts (320 Heat) "
    "in a 10-second fight where the kit generates about 140. The window "
    "buys BOTH remaining rows of the Overheated effect, never one alone: "
    "the 50%:142.54% (by level) bonus attack speed, applied as a "
    "stat_buff weighted by the share of the fight the windows cover "
    "(exact for attack speed, which is linear in the bonus percent), and "
    "the self-silence stated in the same sentence, applied as "
    "self_cast_lockout_seconds — windows x 4 seconds taken off the shared "
    "cast schedule's horizon. Where inside the fight the lockout sits is "
    "NOT claimed: the model prices how much casting the window costs, not "
    "which casts it eats. An autos-only fight casts nothing, generates no "
    "Heat and therefore Overheats zero times whatever the axis declares. "
    "The two axes cannot contradict each other and neither is clamped into "
    "agreement, because a clamp answers an impossible request with a "
    "plausible number: a windows x 4s lockout longer than the declared "
    "fight is REFUSED naming its numbers (clamped, 3/4/5 windows in a 10s "
    "fight all priced one answer), overheat_autos with no declared window "
    "DERIVES the one window that holds the swings, and an autos-only fight "
    "drops the window and the swings together since it casts nothing and "
    "builds no Heat.",
    "W (Scrap Shield) is a sourced self-shield with no damage row: 25/55/"
    "85/115/145 + 30% AP + 4% of maximum health for 1.5 seconds. Shield-"
    "only abilities cannot carry attach_self_shield (that payload rides "
    "damage-event rows), so W stays priced by the ally-support scanner, "
    "which derives it at target scope 'self'. Its 4% max-health term was "
    "silently dropped until this session: the wiki spelling '% of maximum "
    "health' was missing from the scaling unit table and resolved to 0.0; "
    "the alias is now mapped. The bonus movement speed row is not damage "
    "and remains state. Reclassified from out_of_scope to modeled (the "
    "Ekko-W precedent for a scanner-priced shield-only slot).",
]
# No MODULE_COVERAGE: every slot is emitted and priced, which is exactly
# what ``module_contract.default_coverage`` derives from SLOTS.  Restating
# it is refused as a second home for the same fact.
