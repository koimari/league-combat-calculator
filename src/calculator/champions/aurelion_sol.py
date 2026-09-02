"""Aurelion Sol — slot map for the archetype engine.

Why each slot is non-generic:
- Q (Breath of Light) is a channeled beam the classifier cannot model:
  the per-cast entry is one full 3.25s channel (beam per-second x 3.25
  plus 3 bursts), the burst's Stardust %maxHP component is a degraded
  wiki parse (values all 0, garbage units) with its value rooted in the
  character binary below, the W toggle
  multiplies the beam's flat damage, and timed fights channel Q
  continuously for the whole fight (the pipeline injects the duration
  via the ``fight_duration_seconds`` option; see ``pipeline.run_fight``).
  The JSON attr "Total Maximum Magic Damage" has only 4 values because
  rank 5 has no practical channel cap (160s) — never read it; the
  per-second attr is complete at every rank.
- W (Astral Flight) is a damage-less dash, deliberately absent from the
  map; its only calc effect is Q's beam modifier, gated by ``w_active``.
  The cached "Breath of Light Flat Damage Modifier" row (108-112%) is a
  multiplier on Q, not a W damage row — hence ``no_damage``, not a gap.
- E (Singularity) must read "Total Magic Damage" (full 5s zone) and
  carries the execute-threshold display line (5% + 2.6% per 100
  Stardust of max HP — wiki prose with no usable JSON home).
- R swaps between Falling Star (R[0]) and The Skies Descend (R[1]) via
  the ``r_empowered`` option. The empowered shockwave (R[1] effect[1])
  is excluded: a target hit by the star is immune to the shockwave.
- P (Cosmic Creator) is the Stardust stack mechanic — no damage row; it
  exists as the ``stardust_stacks`` option feeding Q and E.  Every
  Stardust effect the cache states (Q burst %maxHP, W range, E radius and
  execute threshold, R radius) augments another slot, so nothing about P
  is unpriced.

P and W are ``no_damage``, not ``out_of_scope``: both emit an explicit,
user-visible zero-damage row (``module_helpers.no_damage``) rather than
staying silently absent from the parse output.

  - P (Cosmic Creator): the cached entry's own leveling is empty
    (``data/champions.json`` AurelionSol P: single effect row,
    ``"leveling": []``) — P grants no damage of its own; it is the
    permanent Stardust counter that parameterizes Q's burst and E's
    execute threshold (both already modeled above via
    ``AURELION_SOL_STARDUST_RULE`` / the ``stardust_stacks`` option).
    Corroborated by the game binary
    (``data/bin/characters/aurelionsol.bin.json``,
    ``Characters/AurelionSol/Spells/AurelionSolPassiveAbility/
    AurelionSolPassive``): its ``mSpell`` carries no damage-type field,
    and its only ``mSpellCalculations`` entries (``QPassiveScaling``,
    ``EPassiveScalingExecute``) are the shared scaling formulas Q/E
    already read — P itself computes nothing.
  - W (Astral Flight): the cached entry's only leveling row is "Breath
    of Light Flat Damage Modifier" (108-112%), a multiplier consumed by
    Q's beam (``_w_beam_modifier`` above) — W carries no damage
    attribute of its own. Corroborated by the game binary
    (``Characters/AurelionSol/Spells/AurelionSolWAbility/AurelionSolW``):
    its ``mSpellCalculations`` are ``DashSpeed`` and two dash-speed/
    level-interpolation helpers, no damage node. W stays gated behind
    the existing ``w_active`` option for its Q-modifier effect; the new
    slot only makes W's own zero-damage state visible.
"""

from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import CC_PER_PART, SlotCtx, build_parser
from .inputs import bool_option, int_option
from .module_contract import coverage
from .module_helpers import delayed_damage, no_damage_slot, ranked_slot
from .slotlib import (
    ability_name,
    by_option,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
)
from .source_receipts import load_champion_sources

# One full Q channel: 3.25 s of beam, with a burst on the primary target
# at each full second of channel (3 bursts).
_Q_CHANNEL_SECONDS = 3.25
_Q_BURSTS_PER_CHANNEL = 3

# Sourced channel bounds: the 0.25s recast lockout (binary
# mSpellCooldownOrSealedQueueThreshold 0.25, wiki effects[5]) means a
# channel shorter than 0.25s cannot start; rank 5 caps at 160s (wiki
# effects[4]; binary MaxChannelDuration 9999.0 is effectively unlimited
# but the wiki's 160s is the practical game cap).
_Q_CANCEL_LOCKOUT = 0.25
_RANK5_CHANNEL_CAP = 160.0

# The Stardust/execute constants are ROOTED IN THE BINARY, not hand-copied:
# the wiki modifier parser degrades (Q burst: values [0,...], units
# "(3.1% Stardust)% of target's maximum health") and the E execute threshold
# has no champion-JSON entry at all, so the values resolve through
# ``binary_roots`` from data/bin/characters/aurelionsol.bin.json (client
# 16.15.8024387).  A patch that moves a root moves the module with it; a dump
# that goes missing fails closed at import.
# https://wiki.leagueoflegends.com/en-us/Aurelion_Sol
_Q_SPELL = spell_object("Aurelion Sol", "AurelionSolQ")
_E_SPELL = spell_object("Aurelion Sol", "AurelionSolE")
_Q_BURST_MAXHP_PCT_PER_STARDUST = (
    data_value(_Q_SPELL, "QMaxHealthTrueDamagePerStack") * 100.0
)  # % of target max HP per stack (binary stores the fraction)
_E_EXECUTE_BASE_PCT = data_value(_E_SPELL, "BaseExecutionThreshold")
_E_EXECUTE_PCT_PER_100_STARDUST = (
    data_value(_E_SPELL, "ExecutionGrowthPerBreakpoint") * 100.0
)  # per-stack growth, displayed per 100 Stardust
# Stardust generation (wiki: the beam burst "generates 2 Stardust if they
# are a champion").
_STARDUST_PER_Q_BURST = data_value(_Q_SPELL, "QMassStolen")


class _StardustRule:
    """The typed Stardust (Cosmic Creator) counter declaration (P3 3X).

    Stardust is a PERMANENT counter generated by damaging abilities:
    the Q burst grants +2 per champion hit, E grants +1 per full second
    a champion is in the zone plus kill bounties (2/2/1), and R grants
    +5 per enemy champion hit — champion takedowns themselves grant NO
    Stardust (they only refund W's cooldown).  Both priced terms are
    continuous LINEAR in stacks (Q burst +0.031% max HP per stack; E
    execute 5% + 2.6% per 100); the per-100 rows are display milestones
    only.  ``public_receipt()`` rides the option's ``state`` and the
    resource-ledger stardust declaration.
    """

    def __init__(self) -> None:
        self.q_burst_maxhp_pct_per_100 = 3.1
        self.e_execute_base_pct = _E_EXECUTE_BASE_PCT
        self.e_execute_pct_per_100 = _E_EXECUTE_PCT_PER_100_STARDUST
        self.stardust_per_q_burst = _STARDUST_PER_Q_BURST
        self.bursts_per_q_channel = _Q_BURSTS_PER_CHANNEL
        self.execute_breakpoint_stacks = 100  # the per-100 milestone step
        self.max_stacks = 999  # the ledger/API bound (the cache's cap)
        self.permanent = True
        # Atom-backed certification surface (P4/P1): every priced constant
        # maps to its evidence root.  The Q burst's Stardust term roots in
        # the HALF-PARSED atom (values zeroed, the 3.1% lives in the units
        # string — d7b0a266cad8da3f) with the binary
        # QMaxHealthTrueDamagePerStack 0.00031 as the value root; the E
        # execute constants have no JSON home (the binary
        # BaseExecutionThreshold 5.0 / ExecutionGrowthPerBreakpoint 0.026
        # are the root); the +2/burst roots in the binary QMassStolen 2.0.
        self.atom_ids = {
            "per_stack_burst_maxhp_pct": {
                "atom_id": "ability.bonus _magic _damage.modifier_2",
                "hash": "d7b0a266cad8da3f",
            },
            "execute_base_pct": {
                "atom_id": "binary:BaseExecutionThreshold",
                "hash": "",
            },
            "execute_pct_per_100": {
                "atom_id": "binary:ExecutionGrowthPerBreakpoint",
                "hash": "",
            },
            "stardust_per_q_burst": {
                "atom_id": "binary:QMassStolen",
                "hash": "",
            },
        }
        # The certified values the atom_ids map (fail-closed staleness:
        # the hashes are pinned; a patch that changes the atoms or the
        # binary roots trips the tests, never a silent drift).
        self.certified_constants = {
            "per_stack_burst_maxhp_pct": 0.031,
            "execute_base_pct": self.e_execute_base_pct,
            "execute_pct_per_100": self.e_execute_pct_per_100,
            "stardust_per_q_burst": self.stardust_per_q_burst,
        }
        self.source = {
            "label": (
                "Local League Wiki cache — Aurelion Sol P (Cosmic Creator) "
                "Stardust prose; values binary-confirmed in the local "
                "Community Dragon cache (aurelionsol.bin.json 16.15.8024387)"
            ),
            "url": "https://wiki.leagueoflegends.com/en-us/Aurelion_Sol",
            "revision_id": 3952788,
            "revision_timestamp": "2025-09-10T01:55:29Z",
        }

    def public_receipt(self) -> dict[str, Any]:
        return {
            "name": "Aurelion Sol — Cosmic Creator (Stardust)",
            "per_stack_burst_maxhp_pct": 0.031,
            "q_burst_maxhp_pct_per_100": self.q_burst_maxhp_pct_per_100,
            "execute_base_pct": self.e_execute_base_pct,
            "execute_pct_per_100": self.e_execute_pct_per_100,
            "execute_pct_per_100_stacks": self.e_execute_pct_per_100,
            "e_execute_base_pct": self.e_execute_base_pct,
            "e_execute_pct_per_100": self.e_execute_pct_per_100,
            "stardust_per_q_burst": self.stardust_per_q_burst,
            "bursts_per_q_channel": self.bursts_per_q_channel,
            "execute_breakpoint_stacks": self.execute_breakpoint_stacks,
            "max_stacks": self.max_stacks,
            "atom_ids": {key: dict(value) for key, value in self.atom_ids.items()},
            "certified_constants": dict(self.certified_constants),
            "permanent": self.permanent,
            "source": dict(self.source),
        }


AURELION_SOL_STARDUST_RULE = _StardustRule()

# Both R branches strike after their own sourced delay, from cast start:
# "calls down a star that strikes the target location after 1.25 seconds,
# dealing magic damage to enemies hit and stunning them for 1 second"
# (R[0]) and "calls down a giant star that strikes the target location
# after 2 seconds, dealing 25% increased damage in a larger area and
# knocking up enemies hit for 1 second" (R[1]).
_R_FALLING_STAR_SECONDS = 1.25
_R_SKIES_DESCEND_SECONDS = 2.0


def _w_beam_modifier(ctx: SlotCtx) -> float:
    """W's 108-112% multiplier on Q's beam flat damage; 1.0 when inactive.

    Beam only, per the wiki's "its non-burst flat damage is increased" —
    never the burst base or any AP portion. No effect until W is learned.
    """
    if not ctx.option("w_active"):
        return 1.0
    w_ability = ctx.ability("W")
    w_rank = ctx.rank_for("W")
    if w_ability is None or w_rank < 1:
        return 1.0
    modifier = extract_value(
        w_ability, "Breath of Light Flat Damage Modifier", w_rank, 0
    )
    if modifier <= 0:
        # A missing attribute reads as 0.0, which would annihilate the
        # beam instead of scaling it — fail loudly (a patch renamed it).
        raise ValueError(
            "Aurelion Sol W: 'Breath of Light Flat Damage Modifier' is "
            "missing from the ability JSON — cannot scale Q's beam damage"
        )
    return modifier / 100.0


# The beam ticks 8 times per second — the JSON's per-tick row is
# exactly 1/8 of the per-second row at every rank (5.625 = 45/8 ...
# 13.125 = 105/8), and its "Total Maximum Magic Damage" is 26 ticks of
# it (146.25 = 26 x 5.625 at rank 1), i.e. one full 3.25s channel.  A
# burst lands on the primary target at each full second of the channel.
_Q_TICKS_PER_SECOND = 8
_Q_TICK_INTERVAL = 1.0 / _Q_TICKS_PER_SECOND  # "every 0.125 seconds"


@ranked_slot
def _breath_of_light(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Q: full-channel beam + bursts; continuous channel in timed fights."""

    ap = ctx.stat("ability_power")
    beam_per_second = _beam_per_second(ctx, ability, rank, ap)
    per_burst = _burst_damage(ctx, ability, rank, ap)

    seconds, bursts, cooldown = _channel_window(ctx, ability, rank)
    # The beam is per-tick damage x (seconds / tick interval): 26 ticks
    # of the per-tick row for one 3.25s channel, exactly the sourced
    # "Total Maximum Magic Damage" (per-second x 3.25).
    ticks = round(seconds / _Q_TICK_INTERVAL)
    per_tick = beam_per_second * _Q_TICK_INTERVAL
    total = per_tick * ticks + per_burst * bursts
    parts = [
        DamagePart(
            "magic",
            per_tick,
            count=ticks,
            time_offset=_Q_TICK_INTERVAL,
            hit_interval=_Q_TICK_INTERVAL,
        ),
        DamagePart(
            "magic",
            per_burst,
            count=bursts,
            time_offset=1.0,
            hit_interval=1.0,
        ),
    ]

    secondary_part = _secondary_beam_part(ctx, ability, rank, ap, ticks=ticks)
    if secondary_part is not None:
        parts.insert(0, secondary_part)
        total += _secondary_beam_per_second(ctx, ability, rank, ap) * seconds

    entry = damage_entry(ability_name(ability), rank, cooldown, total, "magic")
    entry["parts"] = tuple(parts)
    entry["detail"] = (
        f"{ticks} sourced beam tick(s) at 0.125s intervals; {bursts} burst(s) "
        f"at each full second."
    )
    if secondary_part is not None:
        entry["detail"] += (
            " secondary target(s) take the sourced 50%-strength beam "
            f"({_secondary_beam_per_second(ctx, ability, rank, ap):g}/s total, "
            "W-modified)"
        )
    return entry


def _channel_window(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> tuple[float, int, float]:
    """(seconds, bursts, cooldown) of one Q channel.

    Timed fights channel Q continuously for the whole duration (one
    burst per full second, the entry never recasts); otherwise one
    3.25s channel with 3 bursts and the sourced cooldown.
    """
    fight_seconds = ctx.options.get("fight_duration_seconds")
    if fight_seconds is not None:
        seconds = float(fight_seconds)
        # P4-Asol-Q: channel shorter than the 0.25s cancel lockout
        # cannot start — treat as a normal cast (sourced cooldown,
        # zero beam time).
        if seconds <= _Q_CANCEL_LOCKOUT:
            return 0.0, 0, extract_cooldown(ability, rank)
        # P4-Asol-Q: at rank 5 the sourced channel cap is 160s.
        if rank >= 5 and seconds > _RANK5_CHANNEL_CAP:
            seconds = _RANK5_CHANNEL_CAP
        return seconds, int(seconds), 999.0
    return _Q_CHANNEL_SECONDS, _Q_BURSTS_PER_CHANNEL, extract_cooldown(ability, rank)


def _beam_per_second(
    ctx: SlotCtx, ability: dict[str, Any], rank: int, ap: float
) -> float:
    """Primary beam damage per second: flat x W modifier + % AP."""
    return (
        extract_value(ability, "Magic Damage per Second", rank, 0)
        * _w_beam_modifier(ctx)
        + ap * extract_value(ability, "Magic Damage per Second", rank, 1) / 100.0
    )


def _burst_damage(ctx: SlotCtx, ability: dict[str, Any], rank: int, ap: float) -> float:
    """One primary-target Stardust burst: flat + % AP + Stardust % max HP."""
    stacks = float(ctx.option("stardust_stacks"))
    max_hp = ctx.target_stat("target_max_health")
    return (
        extract_value(ability, "Bonus Magic Damage", rank, 0)
        + ap * extract_value(ability, "Bonus Magic Damage", rank, 1) / 100.0
        + (_Q_BURST_MAXHP_PCT_PER_STARDUST * stacks / 100.0) * max_hp
    )


def _secondary_beam_part(
    ctx: SlotCtx, ability: dict[str, Any], rank: int, ap: float, *, ticks: int
) -> DamagePart | None:
    """The per-tick secondary-beam part, or None with no secondary target."""
    per_second = _secondary_beam_per_second(ctx, ability, rank, ap)
    if per_second <= 0.0:
        return None
    return DamagePart(
        "magic",
        per_second * _Q_TICK_INTERVAL,
        count=ticks,
        time_offset=_Q_TICK_INTERVAL,
        hit_interval=_Q_TICK_INTERVAL,
    )


def _secondary_beam_per_second(
    ctx: SlotCtx, ability: dict[str, Any], rank: int, ap: float
) -> float:
    """Total sourced 50%-strength beam per second across secondary targets.

    "Secondary Magic Damage per Second" is exactly half the primary row
    at every rank (flat and % AP); the Stardust bursts stay
    primary-only ("Against the primary target, the beam will deal a
    burst"), and W's flat-damage modifier applies to the secondary beam
    as non-burst flat damage.  Zero when no secondary target is
    selected via the declared ``q_secondary_targets`` option.
    """
    secondary_targets = min(max(int(ctx.option("q_secondary_targets")), 0), 5)
    if not secondary_targets:
        return 0.0
    return (
        extract_value(ability, "Secondary Magic Damage per Second", rank, 0)
        * _w_beam_modifier(ctx)
        + ap
        * extract_value(ability, "Secondary Magic Damage per Second", rank, 1)
        / 100.0
    ) * secondary_targets


# E (Singularity) ticks 20 times over its 5-second zone — the JSON's
# "Total Magic Damage" row is exactly 20x the "Magic Damage per Tick"
# row at every rank (50/2.5 .. 150/7.5), so the tick count is sourced
# rather than invented.  Each tick is one 0.25s step of the zone.
_E_TICKS = 20
_E_DURATION = data_value(_E_SPELL, "Duration")
_E_TICK_INTERVAL = _E_DURATION / _E_TICKS  # "every 0.25 seconds"


@ranked_slot
def _singularity(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """E: 20 sourced ticks of the full-zone total, plus the execute line."""

    total = extract_named(ability, "Total Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            total / _E_TICKS,
            count=_E_TICKS,
            time_offset=_E_TICK_INTERVAL,
            hit_interval=_E_TICK_INTERVAL,
        ),
    )
    # Item burns stay refreshed through the whole 5s zone (the
    # Cassiopeia rule).
    entry["dot_duration"] = _E_DURATION

    stacks = float(ctx.option("stardust_stacks"))
    threshold_pct = _E_EXECUTE_BASE_PCT + _E_EXECUTE_PCT_PER_100_STARDUST * (
        stacks / 100.0
    )
    detail = f"Executes below {threshold_pct:.1f}% max HP"
    max_hp = ctx.target_stat("target_max_health")
    if max_hp > 0:
        detail += f" ({threshold_pct / 100.0 * max_hp:.0f} HP)"
    entry["detail"] = detail
    return entry


# P: the permanent Stardust counter — documented zero-damage row.
#
# P grants no damage of its own; it only parameterizes Q's burst and
# E's execute threshold through the ``stardust_stacks`` option, both
# priced above via ``AURELION_SOL_STARDUST_RULE``.
_cosmic_creator = no_damage_slot(
    "Cosmic Creator grants Aurelion Sol permanent Stardust stacks "
    "from his damaging abilities; the cached entry's own leveling "
    "is empty (data/champions.json AurelionSol P) and the game "
    "binary's passive spell record carries no damage-type field "
    "(data/bin/characters/aurelionsol.bin.json, "
    "AurelionSolPassiveAbility) — its only mSpellCalculations "
    "(QPassiveScaling, EPassiveScalingExecute) are the shared "
    "scaling formulas Q's burst and E's execute threshold already "
    "read via stardust_stacks. P itself prices nothing."
)


# W: the damage-less dash — documented zero-damage row.
#
# W's only calc effect is Q's beam flat-damage modifier
# (``_w_beam_modifier`` above), already gated by the ``w_active``
# option; W itself carries no damage attribute.
_astral_flight = no_damage_slot(
    "Astral Flight is a damage-less dash; its only cached "
    "leveling row is the 'Breath of Light Flat Damage Modifier' "
    "(108-112%) already consumed as Q's beam multiplier "
    "(_w_beam_modifier, gated by w_active) — no damage attribute "
    "belongs to W itself. Corroborated by the game binary "
    "(AurelionSolWAbility): its mSpellCalculations are DashSpeed "
    "and dash-speed/level-interpolation helpers only."
)


OPTIONS: list[dict[str, Any]] = [
    int_option(
        "stardust_stacks",
        0,
        minimum=0,
        maximum=999,
        label="Stardust stacks",
        state=AURELION_SOL_STARDUST_RULE.public_receipt(),
    ),
    bool_option("w_active", False, label="W (Astral Flight) active"),
    bool_option("r_empowered", False, label="R empowered (The Skies Descend)"),
    int_option(
        "q_secondary_targets",
        0,
        minimum=0,
        maximum=5,
        label="Enemies caught by the beam beyond the primary (each takes "
        "the sourced 50%-strength 'Secondary Magic Damage per "
        "Second' row; the Stardust bursts stay primary-only)",
        rotation={"role": "irrelevant", "slot": "Q"},
    ),
]

ASSUMPTIONS = [
    "Q is modeled as one full 3.25s channel per cast: full beam damage "
    "plus 3 bursts on the primary target (in-game the channel can run "
    "longer — up to 160s at rank 5, unlimited during W)",
    "Timed fights assume Q channels continuously for the whole duration, "
    "uninterrupted by other casts — beam damage every second, one burst "
    "per full second; below rank 5 without W this overstates Q uptime "
    "(3.25s channel cap plus cooldown gaps)",
    "Timed fights count the whole Q channel as a single cast for "
    "cast-counted item effects (e.g. spellblade procs)",
    "W active multiplies Q's beam flat damage only (wiki: 'non-burst flat "
    "damage'), never the burst base or AP portions; the channel window is "
    "unchanged for an apples-to-apples toggle comparison",
    "E assumes the target stays in the zone for the full 5s (all 20 ticks)",
    "Empowered R shows the star impact only — a target hit by the star is "
    "immune to the shockwave",
    "Secondary-target Q beam damage is priced from the sourced "
    "'Secondary Magic Damage per Second' row (exactly 50% of the "
    "primary row at every rank, flat and % AP) per secondary target "
    "selected via the parse/API-level q_secondary_targets option "
    "(default 0 = primary only); the Stardust bursts remain "
    "primary-target-only, and W's flat-damage modifier applies to the "
    "secondary beam as non-burst flat damage.  The key is a declared "
    "OPTIONS row like every other secondary-target count in the roster "
    "(Orianna's Command: Attack, Xayah's Clean Cuts): a formula reads its "
    "options through the rows the frontend renders, so the number it "
    "falls back to and the number the user is shown are one value",
    "Q's cached 'cost' row (8.75/10/11.25/12.5/13.75 mana) is NOT a "
    "stale value: it is the wiki's per-0.25s-tick drain, exactly 1/4 "
    "of the game's per-second convention (bin AurelionSolQ 'mana' "
    "[35, 40, 45, 50, 55]; ddragon costBurn '35/40/45/50/55', costType "
    "'Mana per second') — the ratio is exact (4.0x) at every rank, the "
    "same wiki per-tick display convention this module already sources "
    "for Q's damage rows (8 beam ticks/s). patch_regression.py's "
    "ability-row comparison flags this as 'cost drifted' because it "
    "diffs the raw cached values against the raw per-second game "
    "field without a unit conversion; that comparison is a row-mapping "
    "artifact, not a real cache drift (verified 16.15/16.16.1: cdtb "
    "aurelionsol.bin.json + ddragon AurelionSol.json). resource_cost is "
    "not stamped for Q's channel (no per-cast test asserts it), so no "
    "runtime behavior is affected either way.",
    "P (Cosmic Creator) and W (Astral Flight) carry no sourced "
    "damage/heal/shield row of their own (P's leveling is empty; W's "
    "only leveling row is the Q beam multiplier already priced above) "
    "— both are no_damage, not out_of_scope, and each emits an explicit "
    "zero-damage state row rather than staying silently absent.",
]

SLOTS = {
    "P": _cosmic_creator,
    "Q": _breath_of_light,
    "W": _astral_flight,
    "E": _singularity,
    # Both R branches land on their own sourced delay, and the two apply
    # different control, so each authors its own kind on its own part
    # rather than sharing one MODULE_CC answer.
    "R": by_option(
        "r_empowered",
        {
            False: delayed_damage(
                delay=_R_FALLING_STAR_SECONDS,
                attr="Magic Damage",
                dmg_type="magic",
                cc_kind="stun",
            ),
            True: delayed_damage(
                delay=_R_SKIES_DESCEND_SECONDS,
                attr="Empowered Magic Damage",
                dmg_type="magic",
                source=("R", 1),
                cooldown_from=("R", 0),
                cc_kind="knockup",
            ),
        },
        default=False,
    ),
}

# Cached kit review.  Q's beam only burns and reveals.  E's black hole
# "drag[s] [enemies] inward", which the Wiki's crowd-control taxonomy does
# not list among its four displacements (knock aside/back/up, pull) nor
# among the immobilizing effects, and its movement-speed floor applies to
# "minions and monsters" only — so neither slot controls the champion it
# damages.  R is deliberately absent from this dict rather than
# unreviewed: its two branches apply different control (Falling Star
# stuns, The Skies Descend knocks up) on different sourced delays, so the
# answer is a property of the branch and each variant authors its own
# ``cc_kind`` on its own part above.  P and W are absent too: their rows
# price no damage part for an event to carry a kind.
MODULE_CC = {"Q": "none", "E": "none", "R": CC_PER_PART}

parse_abilities = build_parser(SLOTS, "Aurelion Sol", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Aurelion Sol")

# P and W emit a row but price no damage, which is not what SLOTS derives.
MODULE_COVERAGE = coverage(no_damage="PW")
