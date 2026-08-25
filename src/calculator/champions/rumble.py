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

    The heat axis prices the other two rows of the same effect:
      * The 50% : 142.54% bonus attack speed and the self-silence stated
        in the same sentence ("disabling his abilities as his Heat
        decays back down to 0 over 4 seconds") are priced TOGETHER, off
        one declared axis, because pricing either alone overstates
        Rumble in one direction or the other.
        ``overheat_windows`` declares how many times the mech reaches
        the ceiling; ``_heat_mechanics`` reads the ceiling (150 Heat),
        the per-cast gain (20 Heat, and Q/W/E must agree) and the window
        (4 seconds) out of the cached prose, so the axis prices no
        constant of its own and a reworked cache raises.
        Why DECLARED and not derived from the cast plan, which does
        carry sourced heat amounts: a probe of the real pipeline puts 16
        basic-ability casts in a 10-second fight — 320 Heat, two
        Overheats — because E is scheduled on its cached 0.5s
        inter-charge ``cooldown`` while its ``rechargeRate`` is 6s for
        two charges. Deriving heat from that plan would place the first
        lockout at 4.5s off ~11 phantom casts. Heat is derivable the day
        E's charges are, and ``_heat_mechanics`` already publishes the
        casts-per-window count that derivation needs.
        The two axes cannot contradict each other, and a clamp is never
        how that is enforced — a clamp answers an impossible request with
        a plausible number. A lockout longer than the declared fight is
        REFUSED, naming its numbers (``_refuse_impossible_heat_state``);
        clamped, three, four and five windows in a ten-second fight all
        priced one answer. Empowered swings with no declared window
        DERIVE the one window that holds them, because a swing is
        evidence of the window it landed in and because the shared option
        sweeps arm one option at a time, so no cross-option rule could be
        satisfied. An autos-only fight drops both: no cast, no Heat.
        Both halves land through primitives that already existed: the
        bonus attack speed as a ``stat_buff`` weighted by
        ``buff_window_share`` (exact for attack speed, which is linear
        in the bonus percent), and the lockout as
        ``self_cast_lockout_seconds`` — seconds ``damage.py`` takes off
        the shared cast schedule's horizon. Placement inside the fight
        is NOT claimed: the model prices how much casting the window
        costs, not which casts it eats.
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
import re
from typing import Any

from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx
from .module_helpers import buff_window_share
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    extract_description_duration,
    extract_named,
    extract_value,
    find_named_leveling,
    on_hit_entry,
    simple_damage,
)
from .inputs import int_option
from ..binary_roots import data_value, spell_object

PACKET_SHA256 = "c18c1e6e7005c17066acf180ec68a2013bb656c20a88655a536f0a2bc9a078f5"

# Upper bound on the explicit Overheated auto count; a sanity rail on user
# input, not a modeled game value (the Rammus w_thorns_autos rail).
_MAX_OVERHEAT_AUTOS = 30

# Same rail, on the heat axis: how many times one fight may be declared to
# Overheat.  Not a game bound either — the game's bound is the arithmetic
# in ``_heat_mechanics`` against the fight window.
_MAX_OVERHEAT_WINDOWS = 5

# The heat system's three numbers live in cached prose, not in a leveling
# row, so they are read with these and every miss raises.  Slot casts:
# "Rumble generates 20 Heat to activate his flamethrower"; the ceiling:
# "becomes Overheated while at 150 Heat"; the window: "disabling his
# abilities as his Heat decays back down to 0 over 4 seconds".
_HEAT_PER_CAST_RE = re.compile(r"generates\s+(?P<value>\d+(?:\.\d+)?)\s+Heat")
_MAX_HEAT_RE = re.compile(
    r"becomes\s+Overheated\s+while\s+at\s+(?P<value>\d+(?:\.\d+)?)\s+Heat"
)

# The slots whose cast the cache says generates Heat.  R is deliberately
# absent: The Equalizer delays the decay ("or The Equalizer within 2
# seconds") and generates none.
_HEAT_GENERATOR_SLOTS = ("Q", "W", "E")
_OVERHEAT_EFFECT_INDEX = 2


def _effect_text(ability: dict[str, Any] | None, index: int) -> str:
    """One cached effect description, or an empty string when absent."""
    if ability is None:
        return ""
    effects = ability.get("effects")
    if not isinstance(effects, list) or not 0 <= index < len(effects):
        return ""
    effect = effects[index]
    if not isinstance(effect, dict):
        return ""
    description = effect.get("description")
    return description if isinstance(description, str) else ""


def _heat_mechanics(ctx: SlotCtx) -> tuple[float, float, float]:
    """The cached Heat ceiling, per-cast gain, and Overheat window.

    Every number is read out of the cached descriptions the sentences above
    quote, so a reworded or reworked cache raises here instead of pricing a
    stale constant.
    """
    passive = ctx.ability("P")
    if passive is None:
        raise ValueError("Rumble P: the cached Junkyard Titan entry is missing")
    ceiling = _MAX_HEAT_RE.search(_effect_text(passive, 0))
    if ceiling is None:
        raise ValueError(
            "Rumble P: the cached innate no longer states the Overheat "
            "ceiling ('becomes Overheated while at N Heat')"
        )

    gains: set[float] = set()
    for slot in _HEAT_GENERATOR_SLOTS:
        match = _HEAT_PER_CAST_RE.search(_effect_text(ctx.ability(slot), 0))
        if match is None:
            raise ValueError(
                f"Rumble {slot}: the cached entry no longer states its Heat "
                "generation ('Rumble generates N Heat')"
            )
        gains.add(float(match.group("value")))
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
    return float(ceiling.group("value")), gains.pop(), float(window)


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


def _refuse_impossible_heat_state(
    ctx: SlotCtx,
    *,
    windows: int,
    locked: float,
    window: float,
) -> None:
    """Refuse a lockout the declared fight cannot hold.

    A CONTRADICTION is refused rather than clamped, because a clamp answers
    an impossible request with a plausible number: three, four and five
    windows in a ten-second fight all priced the same attack speed —
    ``buff_window_share`` capped at 1.0 — while ``self_cast_lockout_seconds``
    kept growing past a horizon already at zero.
    """
    # ``fight_duration_seconds`` is zero in one-rotation mode and in a
    # direct parse call — no clock, so no horizon to contradict.
    duration = float(ctx.option("fight_duration_seconds"))
    if 0.0 < duration < locked:
        raise ValueError(
            f"Rumble P: overheat_windows={windows} declares "
            f"{windows} x {window:g}s = {locked:g}s Overheated, which does "
            f"not fit in the declared {duration:g}s fight. The mech cannot "
            "spend longer locked out than the fight lasts; declare at most "
            f"{int(duration // window)} window(s)"
        )


def _junkyard_titan(ctx: SlotCtx) -> dict[str, Any] | None:
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
    lands.  ``max_procs`` keeps that channel honest, and ``overheat_autos``
    is the explicit count of empowered swings.

    ``overheat_windows`` is the heat axis (see the module docstring): the
    declared number of times the mech reaches the cached Heat ceiling.  It
    buys the two halves that need a clock — ``windows x window`` seconds of
    bonus attack speed and the same seconds of self-silence.  Both are
    withheld entirely at zero windows, because a payload present at a
    magnitude of zero still reads as a priced slot to ``coverage_truth``
    (the phantom-proc rule this module already applies to the rider).

    The two axes cannot contradict each other.  Declared swings derive the
    window that holds them, an autos-only fight drops both, and a lockout
    longer than the declared fight is refused outright.
    """
    ability = ctx.ability("P")
    if ability is None:
        return None
    autos = min(max(int(ctx.option("overheat_autos")), 0), _MAX_OVERHEAT_AUTOS)
    per_auto = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )
    entry = on_hit_entry(ability_name(ability), per_auto, "magic")
    if autos:
        entry["on_hit"]["max_procs"] = autos
    else:
        # Zero empowered swings must cost zero, and must READ as zero: a
        # rider payload with a max of 0 still reads as a priced slot to
        # ``coverage_truth``.  No declared swing, no rider (the
        # phantom-proc rule this batch applied to Rammus' thorns).
        del entry["on_hit"]
    entry["target_max_health_sensitive"] = True

    ceiling, per_cast, window = _heat_mechanics(ctx)
    casts_per_window = math.ceil(ceiling / per_cast)
    windows = min(max(int(ctx.option("overheat_windows")), 0), _MAX_OVERHEAT_WINDOWS)
    # An empowered swing IS evidence of an Overheat window: the row exists
    # only "during this time".  So declared autos derive the one window that
    # holds them rather than pricing upside with no window to pay for it —
    # a derivation and not a refusal, because the shared option sweeps
    # (cast_dependency_audit.option_states) arm one option at a time and can
    # never satisfy a cross-option rule.
    derived_window = bool(autos) and not windows
    if derived_window:
        windows = 1
    # A fight that casts nothing builds no Heat, so it never Overheats
    # whatever the axis says — the mech only heats on a basic ability cast,
    # and with no window there are no empowered swings either.
    autos_only = bool(ctx.option("auto_attacks_only"))
    if autos_only:
        windows = 0
        derived_window = False
        if autos:
            autos = 0
            del entry["on_hit"]
    locked = windows * window
    _refuse_impossible_heat_state(ctx, windows=windows, locked=locked, window=window)
    detail = (
        f"Overheated: {per_auto:.2f} bonus magic damage on-hit "
        f"(level-{ctx.level} flat + 25% AP + 4% target maximum health) "
        f"x {autos} empowered auto(s)"
    )
    if windows:
        granted = _overheat_attack_speed(ability, ctx.level)
        share = buff_window_share(ctx, locked)
        entry["stat_buff"] = {"bonus_attack_speed": granted * share}
        entry["self_cast_lockout_seconds"] = locked
        detail += (
            f"; {windows} Overheat window(s) of {window:g}s "
            + ("derived from the declared swings" if derived_window else "declared")
            + f" ({int(ceiling)} Heat at {int(per_cast)} per basic ability "
            f"cast = {casts_per_window} casts each): +{granted:g}% bonus "
            f"attack speed over {locked:g}s of the fight (a {share:.3f} "
            "share, exact for attack speed, which is linear in the bonus) "
            "and the same seconds removed from the cast schedule, the "
            "self-silence the cache states in the same sentence"
        )
    elif autos_only:
        detail += (
            "; an autos-only fight casts nothing, so the mech builds no Heat "
            "and never Overheats — neither the empowered swings nor the "
            "bonus attack speed nor the ability lockout applies"
        )
    else:
        detail += (
            "; no Overheat window is declared (overheat_windows = 0) and no "
            "empowered swing implies one, so neither the bonus attack speed "
            "nor the ability lockout applies"
        )
    detail += (
        "; the 'Bonus Damage' row is the monster-only cap on the "
        "%max-health term, not a damage source"
    )
    entry["detail"] = detail
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
    int_option(
        "overheat_windows",
        0,
        minimum=0,
        maximum=_MAX_OVERHEAT_WINDOWS,
        label="Times the mech Overheats during the fight",
        rotation={
            "role": "self_state",
            "slot": "P",
            "note": (
                "Heat is a resource this engine does not simulate, and the "
                "cast plan cannot stand in for it while E is scheduled on "
                "its 0.5s inter-charge cooldown instead of its 6s recharge. "
                "How often the mech reaches the ceiling is declared."
            ),
        },
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
