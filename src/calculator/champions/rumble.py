"""Rumble — CP10.6 packet module with the E9-1 R gap fix.

E9-1 closes the remaining audit gap: R (The Equalizer) priced ONE tick
of the Burning DoT.  The wiki cache carries "Magic Damage per Tick"
(30/50/70 + 8.75% AP) and "Maximum Magic Damage" (600/1000/1400 +
175% AP): 20 ticks at 0.25 seconds over up to 5 seconds of Burning
("Enemies may be Burning for up to 5 seconds, for a total of 20
instances of its effect"). This module's packet timing declaration
prices all 20 ticks.

Row-selection fix (Q): the generated packet read Flamespitter's "Bonus
Damage" row, which is neither a Flamespitter damage row nor rank-indexed
— it is the per-LEVEL monster cap the Danger Zone effect states
("Flamespitter's total damage based on the target's health is capped at
65 : 336.84 (based on level) against monsters"), and the packet indexed
its 20 level values by rank, so rank 5 priced the level-5 cap (107.71).
Flamespitter's own rows are Minimum / per-Second / per-Tick / Maximum
Magic Damage; this module prices the "Maximum Magic Damage" row
(62.5/93.75/125/156.25/187.5 + 131.25% AP + 7.5/8.13/8.75/9.38/10% of
the target's maximum health), which is the whole 3-second flamethrower
— 15 ticks of "Magic Damage per Tick" at every rank.


The Danger Zone half of the heat system stays unpriced: rotation
numbers assume no heat state (the CP-era review boundary), so Q/E/R
price their base rows and the Enhanced rows go unread.

Roadmap session (2026-08-21): closes both of Rumble's remaining
out_of_scope slots (P, W).

  - P (Junkyard Titan) is NOT a no-damage slot. Its third effect row,
    Overheated, carries a real sourced on-hit damage formula: "empowers
    his basic attacks to deal 5 : 44.12 (based on level) (+ 25% AP)
    (+ 4% of the target's maximum health) bonus magic damage on-hit"
    (``data/champions.json`` Rumble P, effect 3, leveling attribute
    "Bonus Magic Damage" — a 20-entry per-LEVEL array, one 25% AP
    modifier, one 4% target-max-health modifier). The game binary
    agrees exactly (``data/bin/characters/rumble.bin.json``, record
    ``RumbleHeatSystem``: ``TotalBaseDamage`` ByCharLevel 5 -> 40 with
    the level-20 extrapolation to 44.12, ``+ 0.25`` AP coefficient, and
    ``OverheatPercBonusDamage`` 0.04). The packet's ``no_damage`` label
    was therefore INCOMPLETE, not merely stale.

    Overheat is a heat-state window the fight engine does not simulate,
    so the number of empowered autos is explicit state: the
    ``overheat_autos`` option (0 by default), exactly the Rammus
    ``w_thorns_autos`` template for a proc whose trigger count the
    engine cannot derive.

    Two sourced rows in the same effect are deliberately NOT modeled:
      * The 50% : 142.54% bonus attack speed. It is inseparable from
        the very cost the same sentence states — "disabling his
        abilities as his Heat decays back down to 0 over 4 seconds".
        Importing the upside without the downside would systematically
        overstate Rumble, so both halves stay state (see ASSUMPTIONS).
        The blocker is NOT the lockout primitive — a cast-blocked span
        is a few lines in the shared cast timeline, which already models
        one pair of hands. It is the trigger INSTANT: Overheat opens
        when Heat reaches 100, the engine simulates no heat, and nothing
        in the request carries a start time. Both halves hang off that
        one unsourced instant — where the 4-second lockout sits decides
        which casts the window costs, and an attack-speed grant placed
        anywhere else than the lockout is the overstatement again. What
        unblocks it is a heat axis that gives Overheat a start time, not
        a scheduler feature; until then ``overheat_autos`` prices the
        one half that needs no clock (a count of empowered swings).
      * The "Bonus Damage" leveling row (65 : 163.32 by level). Read in
        context it is not a damage source at all — it is the cap on the
        %max-health term, "capped at 65 : 163.32 (based on level)
        against monsters". It is monster-only and this engine's
        ``target_class`` has no monster value, so it never binds on the
        champion-target surface and is documented, never added.

  - W (Scrap Shield) is a sourced self-shield with no damage row of any
    kind: "Rumble generates 20 Heat to grant himself a shield for 1.5
    seconds", Shield Strength 25/55/85/115/145 (+ 30% AP) (+ 4% of
    maximum health). Being shield-only it cannot carry
    ``attach_self_shield`` (that payload rides damage-event rows), so it
    stays priced by the ally-support scanner, which already derives it
    at target scope "self" (pinned by tests/test_support_effects.py).
    Reclassified out_of_scope -> modeled, the Ekko-W precedent for a
    scanner-priced shield-only slot.

    NOTE: closing this slot required a genuine kernel repair. The 4%
    max-health term uses the wiki spelling "% of maximum health", which
    was absent from ``champions/scaling.py``'s ``_SIMPLE_UNITS`` table
    (only the "% maximum health" spelling was mapped), so
    ``resolve_scaling`` fell through to its unrecognized-unit ``0.0``
    and SILENTLY dropped the term — the exact fail-open this codebase
    bans. The alias is now mapped; see that module's comment for the
    full blast radius (it also zeroed Galio's W shield outright).

    Danger Zone Bonus (+50% shield strength and bonus movement speed)
    is heat state and is not applied: the scanner prices the base
    "Shield Strength" row, the conservative no-heat reading this module
    has always taken for Q/E/R.
"""

import math
from typing import Any

from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx
from .packet_module import build_packet_module
from .slotlib import extract_named, on_hit_entry, simple_damage
from .inputs import int_option

PACKET_SHA256 = "c18c1e6e7005c17066acf180ec68a2013bb656c20a88655a536f0a2bc9a078f5"

# Upper bound on the explicit Overheated auto count. Overheat lasts a
# sourced 4 seconds; the bound is a sanity rail on user input, not a
# modeled game value (the Rammus w_thorns_autos rail).
_MAX_OVERHEAT_AUTOS = 30

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
_Q_TICK_INTERVAL = 0.25

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


def _junkyard_titan(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the Overheated on-hit bonus magic damage, per empowered auto.

    The "Bonus Magic Damage" leveling row is a per-LEVEL array (20
    entries), so it is read at ``ctx.level``, not at an ability rank —
    Junkyard Titan is an innate with no rank of its own.  ``extract_named``
    resolves all three modifiers together: the flat per-level term,
    "% AP", and "% of the target's maximum health".

    The row rides the basic-attack stream, because that is where the game
    puts it and the only channel a passive slot has: ``passive`` is not an
    orderable cast (``pipeline.validate_cast_order_for_kit`` refuses it),
    so a ``parts``-priced passive row parses and then never lands.
    ``max_procs`` is what keeps that channel honest — Overheat is a
    four-second window the fight engine does not simulate, so riding every
    swing of the fight would price the window for the fight's whole
    duration.  ``overheat_autos`` is therefore the explicit count of
    empowered swings, 0 by default.
    """
    ability = ctx.ability("P")
    if ability is None:
        return None
    autos = min(max(int(ctx.option("overheat_autos")), 0), _MAX_OVERHEAT_AUTOS)
    per_auto = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )
    entry = on_hit_entry(ability.get("name", "Junkyard Titan"), per_auto, "magic")
    if autos:
        entry["on_hit"]["max_procs"] = autos
    else:
        # Zero empowered swings must cost zero, and must READ as zero: a
        # rider payload with a max of 0 still reads as a priced slot to
        # ``coverage_truth``.  No declared swing, no rider (the
        # phantom-proc rule this batch applied to Rammus' thorns).
        del entry["on_hit"]
    entry["target_max_health_sensitive"] = True
    entry["detail"] = (
        f"Overheated: {per_auto:.2f} bonus magic damage on-hit "
        f"(level-{ctx.level} flat + 25% AP + 4% target maximum health) "
        f"x {autos} empowered auto(s); the 4-second Overheat window's "
        "attack-speed bonus and its ability lockout are both unmodeled "
        "state, and the 'Bonus Damage' row is the monster-only cap on "
        "the %max-health term, not a damage source"
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
MODULE_CC = {"E": "slow", "Q": "none", "R": "slow"}

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
)
OPTIONS = list(OPTIONS) + [
    int_option(
        "overheat_autos",
        0,
        minimum=0,
        maximum=_MAX_OVERHEAT_AUTOS,
        label="Basic attacks landed while Overheated",
        rotation={"role": "self_state", "slot": "P"},
    ),
]
ASSUMPTIONS = list(ASSUMPTIONS) + [
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
    "The heat/Danger Zone system is state outside the damage model: "
    "Q/E/R rotation numbers assume no heat state (the CP-era review "
    "boundary), and W's Danger Zone Bonus (+50% shield strength) is not "
    "applied - the base Shield Strength row is priced.",
    "P (Junkyard Titan) prices the Overheated on-hit bonus magic damage - "
    "5:44.12 by level + 25% AP + 4% of the target's maximum health per "
    "empowered basic attack (cached P effect 3, leveling attribute 'Bonus "
    "Magic Damage', a per-level array; corroborated by the game binary's "
    "RumbleHeatSystem TotalBaseDamage / 0.25 AP coefficient / "
    "OverheatPercBonusDamage 0.04). The fight engine does not simulate "
    "heat, so overheat_autos is the explicit count of empowered autos "
    "(0 = none, the default). The same effect's 50%:142.54% bonus attack "
    "speed is NOT modeled: it is inseparable from the ability lockout "
    "stated in the same sentence ('disabling his abilities as his Heat "
    "decays back down to 0 over 4 seconds'), and what blocks the pair is "
    "the window's START TIME, not the lockout mechanism — Overheat opens "
    "at 100 Heat, the engine simulates no heat, and nothing in the "
    "request carries that instant. Where the 4-second lockout sits "
    "decides which casts it costs, so pricing the attack speed without "
    "it would overstate Rumble exactly as before. A heat axis is what "
    "unblocks this, not a scheduler feature. The 'Bonus Damage' leveling "
    "row (65:163.32 by level) is the "
    "monster-only cap on the %max-health term, not a damage source, and "
    "never binds against a champion target. Reclassified from "
    "out_of_scope to modeled; the packet's no_damage label was incomplete, "
    "not stale.",
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
