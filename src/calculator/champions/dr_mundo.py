"""Dr. Mundo: slot map for the archetype engine.

P (Goes Where He Pleases) has no slot: it deals no enemy damage and both its arms
are priced elsewhere.  The immunity arm rides the coupled survival walk through
the timeline's t=0 arm packet; the innate regeneration is priced by the self-heal
rule off the cached P's SECOND "Max Health Damage" row, the cache mislabelling
both regeneration rows.
Q (Infected Bonesaw) is %CURRENT-health magic damage floored at a flat minimum,
and both halves defeat the generic path: the unit resolves against a stat nothing
supplies, scoring 0.0, and the floor lives in a second effect.
W (Heart Zapper) is a 3-second charge DoT plus a detonation in its own effect;
the charge total is rebuilt from the per-tick value, the cached total being stale.
E (Blunt Force Trauma) is a BUFF-phase %MAXIMUM-health to bonus-AD steroid and an
empowered next attack amplified by Mundo's OWN missing health.
R (Maximum Dosage) deals no damage but grants BASE health scaled off missing
health, raising maximum health and so feeding E's steroid.  That chain is why R
is listed BEFORE E in ``SLOTS``: a BUFF phase is evaluated in insertion order.
"""

from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from ..cast_event_row import cast_time as _row_cast_time
from .contract_vocabulary import coverage
from .engine import BUFF, SlotCtx, build_parser
from .healing_contract import SelfHealCtx, self_healing_rule
from .inputs import bool_option, champion_stat, int_option
from .module_helpers import ranked_slot
from .shared_mechanics import capped_option
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named, extract_value
from .slotlib import stat_buff
from .source_receipts import load_champion_sources

# ROOTED IN THE BINARY (data/bin/characters/drmundo.bin.json): W's field
# duration and auto-detonation instant are DrMundoW DataValues (Duration);
# the tick cadence (0.25s → 12 ticks) is the game formula "4 ticks/sec ×
# Duration" with no DataValue home, so it stays a documented derived
# constant.  DO NOT read W's total from the JSON's "Total Magic Damage"
# attribute: that template still carries 16 ticks from the pre-V12.23
# four-second duration (stale by a third).
# https://wiki.leagueoflegends.com/en-us/Dr._Mundo
_MUNDO_W_SPELL = spell_object("Dr. Mundo", "DrMundoW")
W_CHARGE_TICKS = 12
W_DURATION = data_value(_MUNDO_W_SPELL, "Duration")
W_TICK_INTERVAL = 0.25  # 4 ticks/sec, script-side — see above
W_DETONATION_TIME = data_value(_MUNDO_W_SPELL, "Duration")

# ROOTED IN THE BINARY: E's amp caps at 70% missing health
# (DrMundoE.MaxMissingHealthThreshold; the wiki page publishes no
# threshold — V25.23 patch notes corroborate), and at rank 3 R's base
# health grows a further 5% per nearby enemy champion
# (DrMundoR.BonusPerNearbyChampion).  The JSON leveling carries no trace
# of either.
_MUNDO_E_SPELL = spell_object("Dr. Mundo", "DrMundoE")
_MUNDO_R_SPELL = spell_object("Dr. Mundo", "DrMundoR")
E_MAX_DAMAGE_AMP = 0.4
E_MAX_AMP_MISSING_HEALTH_PERCENT = (
    data_value(_MUNDO_E_SPELL, "MaxMissingHealthThreshold") * 100.0
)

# HARDCODED: verify on patch updates — at rank 3 ONLY, R's increased base
# health is further increased by 5% per enemy champion within 1200 units
# at cast time (game file ``BonusPerNearbyChampion`` = 0.05). The JSON
# leveling carries no trace of it.
R_NEARBY_CHAMPION_BONUS = data_value(_MUNDO_R_SPELL, "BonusPerNearbyChampion")
R_NEARBY_BONUS_RANK = 3
R_MAX_NEARBY_CHAMPIONS = 4

_DEFAULT_MISSING_HEALTH_PERCENT = 30
_DEFAULT_NEARBY_CHAMPIONS = 0


# ---------------------------------------------------------------------------
# Shared fight state
# ---------------------------------------------------------------------------


def _missing_health_fraction(ctx: SlotCtx) -> float:
    """Mundo's own missing health as a 0..1 fraction, the ONE source.

    E's amp and R's health grant read one game state, so both use this option.
    """
    percent = float(
        ctx.options.get("mundo_missing_health_percent", _DEFAULT_MISSING_HEALTH_PERCENT)
    )
    return min(max(percent, 0.0), 100.0) / 100.0


# ---------------------------------------------------------------------------
# R: Maximum Dosage — BUFF phase, listed first (E's passive reads its health)
# ---------------------------------------------------------------------------


def _nearby_champions(ctx: SlotCtx) -> int:
    """Enemy champions inside R's 1200-unit radius when it is cast."""
    return capped_option(ctx, "r_nearby_champions", R_MAX_NEARBY_CHAMPIONS)


@ranked_slot
def _maximum_dosage(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """R: zero damage; grants BASE health from Mundo's missing health.

    BASE, not bonus (the Gnar classification trap): the grant raises max
    health — which is exactly what feeds E's passive bonus AD — but must
    never reach items that convert BONUS health (Overlord's Bloodmail).
    ``base_health`` is the fight engine's key for that distinction.
    """

    # "% missing health" is Mundo's OWN missing health — no scaling unit
    # covers that, so the percentage is read raw and applied here.
    percent = extract_value(ability, "Increased Base Health", rank) / 100.0
    if rank >= R_NEARBY_BONUS_RANK:
        percent *= 1.0 + R_NEARBY_CHAMPION_BONUS * _nearby_champions(ctx)

    max_health = ctx.stat("health")
    grant = percent * max_health * _missing_health_fraction(ctx)
    # Raise base and total together — bonus health is untouched, which is
    # what keeps the grant away from bonus-health item conversions.
    ctx.stats["health"] = max_health + grant
    ctx.stats["base_health"] = ctx.stat("base_health") + grant

    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
    )
    entry["stat_buff"] = {"base_health": grant}
    return entry


_maximum_dosage.phase = BUFF


# ---------------------------------------------------------------------------
# E: Blunt Force Trauma — the AD steroid and the empowered auto it rides
# ---------------------------------------------------------------------------

# The passive is a plain percent-of-a-stat steroid: "% maximum health" is
# TOTAL health (the game file's ``PassiveBonusAD`` carries no
# ``mStatFormula`` key, which defaults to total). E's ACTIVE, one JSON line
# below in the same ability, is "% BONUS health" — the two are one line
# apart and trivially mixed up.
_passive_bonus_ad = stat_buff(
    attr="Bonus Attack Damage",
    stat="bonus_attack_damage",
    mode="percent_of",
    percent_of="health",
    apply_to=("bonus_attack_damage", "attack_damage"),
)


def _damage_amp(ctx: SlotCtx) -> float:
    """E's bonus-damage multiplier: 1.0 at full health, 1.4 at 70% missing."""
    missing_percent = _missing_health_fraction(ctx) * 100.0
    ramp = min(missing_percent / E_MAX_AMP_MISSING_HEALTH_PERCENT, 1.0)
    return 1.0 + E_MAX_DAMAGE_AMP * ramp


def _blunt_force_trauma(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: the %max-health AD steroid plus one missing-health-amped swing.

    BUFF phase and listed after R, so the passive converts the max health R
    has already raised. The amp multiplies the WHOLE minimum bonus (flat +
    % bonus health), which reproduces the wiki's "Maximum Bonus Physical
    Damage" row exactly at full amp — that row is this same damage at amp
    1.4, never a second damage source to add.

    The empowered attack lands ONCE per cast, not on every auto (the
    Alistar rule); with no auto stream to ride, the fight engine appends
    the expected-crit base swing to this row (Blitzcrank/Caitlyn).
    """
    entry = _passive_bonus_ad(ctx)
    if entry is None:
        return None
    ability = ctx.ability()
    if ability is None:
        return None

    # Read after the passive mutated ctx.stats: safe, and deliberately so —
    # the active scales off BONUS health, which the AD buff cannot touch.
    bonus = extract_named(
        ability,
        "Minimum Bonus Physical Damage",
        entry["rank"],
        ctx.stats,
        ctx.target,
    )
    total = bonus * _damage_amp(ctx)
    entry["total_raw"] = total
    entry["parts"] = (DamagePart("physical", total),)
    # One empowered swing per cast (see above), so one part and one hit —
    # the certification that carries the row's reviewed control answer into
    # the event ledger.
    entry["event_order_certified"] = "single_hit"
    # The attack reset's THROUGHPUT is opt-in (the Vayne-Q template):
    # with the ``e_reset_throughput`` option the empower is stamped as a
    # self-supplying burst at an infinite rate — "the auto fires
    # immediately" (the cached reset prose + the binary Trait_AttackReset
    # tag; the acceleration magnitude is script-side, so no finite number
    # is invented) — and the engine's burst machinery buys one EXTRA
    # swing per accepted cast with zero dead time.  The stat_buff (the
    # passive steroid) rides the same entry untouched.  Default keeps the
    # conservative ``True`` form (casts capped at the auto count).  The
    # option is read STRICTLY so junk values fail closed to the default.
    if ctx.option("e_reset_throughput") is True:
        entry["empowers_next_auto"] = {
            "hits": 1,
            "attack_speed": float("inf"),
        }
    else:
        entry["empowers_next_auto"] = True
    return entry


_blunt_force_trauma.phase = BUFF


# ---------------------------------------------------------------------------
# Q: Infected Bonesaw
# ---------------------------------------------------------------------------


@ranked_slot
def _infected_bonesaw(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Q: % of the target's current health, floored at a flat minimum.

    The percent's unit ("% of target's current health") has no stat behind
    it in scaling.py, so the value is read raw and applied here. Every cast
    is priced against the target's FULL health (see ASSUMPTIONS): Q does
    not decay its own target across casts. The floor is not decoration —
    at rank 5 it takes over below roughly 933 target health.
    """

    percent = extract_value(ability, "Magic Damage", rank) / 100.0
    minimum = extract_value(ability, "Minimum Damage", rank)
    target_max = float(ctx.target_stat("target_max_health"))

    # Q is current-health damage.  The fight evaluator calls this closure
    # once per hit with the running target-health loss, so a repeated Q is
    # priced after the preceding casts instead of six times against full HP.
    def current_health_damage(
        missing_ratio: float,
        live_target_max_health: float | None = None,
    ) -> float:
        live_max = (
            target_max if live_target_max_health is None else live_target_max_health
        )
        current = max(0.0, live_max * (1.0 - missing_ratio))
        return max(percent * current, minimum)

    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        max(percent * target_max, minimum),
        "magic",
    )
    # Q is one impact, but its current-health formula must still be repriced
    # against the live target HP.  An authored zero offset makes that impact
    # an exact event rather than an uncertified cast-boundary aggregate.
    entry["parts"] = (
        DamagePart("magic", hp_scaled_damage=current_health_damage, time_offset=0.0),
    )
    entry["target_max_health_sensitive"] = True
    entry["detail"] = "Current-health damage with rank-scaled minimum floor"
    return entry


# ---------------------------------------------------------------------------
# W: Heart Zapper
# ---------------------------------------------------------------------------


@ranked_slot
def _heart_zapper(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """W: 12 charge ticks plus the detonation that always follows them.

    The detonation is not optional and is not a recast the player may skip
    — the field "does so automatically after the duration" — so it is one
    guaranteed instance per W cast, folded into the same entry.
    """

    per_tick = extract_named(
        ability, "Magic Damage per Tick", rank, ctx.stats, ctx.target
    )
    detonation = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)

    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        per_tick * W_CHARGE_TICKS + detonation,
        "magic",
    )
    # The packet gives both timings explicitly: one charge tick every 0.25s
    # and an automatic recast at the end of the 3s duration.  Preserve them
    # as separate events so this source is eligible for coupled ordering.
    entry["parts"] = (
        DamagePart(
            "magic",
            per_tick,
            count=W_CHARGE_TICKS,
            time_offset=W_TICK_INTERVAL,
            hit_interval=W_TICK_INTERVAL,
        ),
        DamagePart("magic", detonation, time_offset=W_DETONATION_TIME),
    )
    # Item burns (Liandry's, Blackfire Torch) stay refreshed through the
    # whole channel, not just to the cast instant (the Cassiopeia rule).
    entry["dot_duration"] = W_DURATION
    return entry


OPTIONS: list[dict[str, Any]] = [
    int_option(
        "mundo_missing_health_percent",
        _DEFAULT_MISSING_HEALTH_PERCENT,
        minimum=0,
        maximum=100,
        label="Dr. Mundo's missing health (%)",
        rotation={"role": "self_state", "slot": "E"},
    ),
    int_option(
        "r_nearby_champions",
        _DEFAULT_NEARBY_CHAMPIONS,
        minimum=0,
        maximum=R_MAX_NEARBY_CHAMPIONS,
        label="Enemy champions near R cast (rank 3 bonus)",
        rotation={"role": "self_state", "slot": "R"},
    ),
    bool_option(
        "e_reset_throughput",
        False,
        label="Model Blunt Force Trauma's attack-reset throughput: each "
        "accepted E cast buys one extra basic attack (the wiki: "
        "'Blunt Force Trauma resets Dr. Mundo's basic attack timer'; "
        "the binary Trait_AttackReset tag; the acceleration magnitude "
        "is script-side)",
        rotation={"role": "irrelevant", "slot": "E"},
    ),
]

ASSUMPTIONS = [
    "Q prices against the target's full health every cast, so repeated casts are "
    "overestimated, about 18% on two Qs.",
    "Q's minimum damage floor is modeled and takes over on a low-health target.",
    "Q's monster cap and E's 140% minion amplification do not apply: the target is a "
    "champion.",
    "All 12 ticks of W's charge are assumed to connect over 3s inside 325 units, with "
    "the detonation following.",
    "W's charge total is per-tick x 12, not the cached 16-tick Total Magic Damage "
    "row.",
    "E's bonus damage maxes at 70% missing health, not 100%: game files, undocumented "
    "on the wiki.",
    "E's empowered attack applies once per cast, not on every auto.",
    "e_reset_throughput makes each accepted E cast's empowered auto an extra swing "
    "(binary Trait_AttackReset).",
    "Casts lift to the cooldown grid when the ambient auto cap binds, and on-hit "
    "counters ride that stream.",
    "The default keeps the conservative cap, so the reset's gain is not modeled.",
    "The passive AD steroid rides the same entry, and the 4s empower window is "
    "prose-only with no atom.",
    "E's corpse knockback, 100% AD through the flung body, is not modeled: it needs a "
    "kill or a small monster.",
    "R grants base health, raising maximum health for E's passive AD but feeding no "
    "bonus-health item conversion.",
    "R's health regeneration is a 0.5s tick stream over the 10s window per cast, in "
    "the self-healing rule.",
    "R's bonus movement speed and takedown extension are not modeled and move no "
    "damage.",
    "The passive resists the next hostile immobilizing control for 4% current health "
    "plus a canister drop.",
    "It rides the coupled survival walk; the canister pickup and its destruction are "
    "unsupported timings.",
    "P (Goes Where He Pleases) regenerates 0.04% to 0.23% by level of maximum health "
    "every 0.5 seconds.",
    "That is the cached P second row, ten ticks of which equal its first row's "
    "per-five-seconds statement.",
    "The self-heal rule pays it over the fight; champion base regeneration stays "
    "outside the ledger.",
    "Q's health cost and refund and W's grey-health healing are "
    "self-sustain and are not modeled",
    "Dr. Mundo has no AP scaling anywhere in his kit",
]

SLOTS = {
    # BUFF phase, in this order: R raises max health, and E's passive then
    # converts that raised max health into bonus AD.
    "R": _maximum_dosage,
    "E": _blunt_force_trauma,
    "Q": _infected_bonesaw,
    "W": _heart_zapper,
}

# Reviewed crowd control, read from the cached kit.  Q (Infected Bonesaw)
# "deals magic damage to the first enemy hit and slows them by 40% for 2
# seconds".  W (Heart Zapper) charges, ticks and detonates with no control
# clause.  E (Blunt Force Trauma) sends a target flying only "if the target
# dies or is a small monster" — the enemy this module prices survives the
# hit, so the row applies no control.  R is the self-buff and authors no
# damage part.
MODULE_CC = {"Q": "slow", "W": "none", "E": "none", "R": "none"}

parse_abilities = build_parser(SLOTS, "Dr. Mundo", cc_kinds=MODULE_CC)

# P damages nothing and has no cast, so it emits no row; the self-heal
# rule is what prices its regeneration, and that is the channel the map
# names.
MODULE_COVERAGE = coverage()
COVERAGE_CHANNELS = {"P": ("self_healing_rule",)}


SOURCES = load_champion_sources("Dr. Mundo")


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Resolve Dr. Mundo self-healing events from its authored packet.

    Two streams, both with a cadence of their own rather than a damage
    event to ride: Maximum Dosage's regeneration over R's 10-second
    window, and Goes Where He Pleases' innate regeneration over the whole
    fight.  Both are actor-wide, so the timeline layer deduplicates the
    receipts across multiple defenders.
    """
    healing = []
    r = _healing.ability_json(ctx.champion_data, "R")
    r_rank = _healing.parsed_rank(ctx.ability_damages, "R")
    per_tick = extract_named(
        r, "Health Regenerated per 0.5 Seconds", r_rank, ctx.champion_stats, {}
    )
    duration = max(0.0, float(ctx.fight_duration_seconds or 0.0))
    if per_tick > 0.0 and duration > 0.0:
        for cast in ctx.cast_timeline or []:
            if cast.get("slot") != "R":
                continue
            start = _row_cast_time(cast) + 0.5
            end = min(duration, start - 0.5 + 10.0)
            tick = start
            while tick <= end + 1e-9:
                healing.append(
                    {
                        "time": tick,
                        "amount": float(per_tick),
                        "source": "Maximum Dosage",
                        "kind": "champion_ability",
                        "actor_wide": True,
                    }
                )
                tick += 0.5

    # Goes Where He Pleases (P): "Dr. Mundo regenerates an additional
    # 0.04% : 0.23% (based on level) of his maximum health every 0.5
    # seconds" — the cached P's SECOND "Max Health Damage" row (the cache
    # mislabels both regeneration rows as damage and states the same
    # stream twice, per five seconds and per half second; ten of the
    # second row equal the first at every level).  The heal has a cadence
    # of its own and no cast to read, so it runs the whole fight window on
    # the half-second the row names, against the maximum health R has
    # already raised.  Champion base regeneration stays outside the ledger
    # (pipeline.py adds only the item contribution), so this is the
    # passive's additional stream alone.
    level = int(champion_stat(ctx.champion_stats, "level"))
    regen_percent = extract_value(
        _healing.ability_json(ctx.champion_data, "P"),
        "Max Health Damage",
        level,
        level=level,
        occurrence=1,
    )
    per_half_second = (
        regen_percent / 100.0 * champion_stat(ctx.champion_stats, "health")
    )
    if per_half_second > 0.0 and duration > 0.0:
        tick = 0.5
        while tick <= duration + 1e-9:
            healing.append(
                {
                    "time": tick,
                    "amount": per_half_second,
                    "source": "Goes Where He Pleases",
                    "kind": "champion_passive",
                    "actor_wide": True,
                }
            )
            tick += 0.5
    return healing


SELF_HEALING_RULE = self_healing_rule("Dr. Mundo")(derive_self_healing)
