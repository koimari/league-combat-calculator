"""Diana — slot map for the archetype engine.

Why each slot is non-generic:
- P (Moonsilver Blade) is two components the generic path misread: it
  applied the cleave damage on EVERY auto (the mechanic is a 2-stack
  cycle — every 3rd basic attack cleaves) and missed the attack-speed
  buff entirely (both AS arrays hide under the generic attribute
  "Per-Level Scaling"; position distinguishes base from tripled). Split
  into two slots here: "P" is the BUFF-phase AS steroid (the tripled
  post-ability-cast values, assumed always active — she casts constantly,
  Q's 6s cooldown vs the 5s window), and "auto_attacks_moonsilver_cleave"
  prices floor(autos / 3) cleave procs over a timed fight's auto stream.
  The cleave is spell AoE riding the autos, NOT an on-hit effect: it
  neither applies nor triggers item on-hits and ignores on-hit
  effectiveness, and its synthetic slot key gives the breakdown row the
  ``auto_attacks_`` prefix so ``split_auto_vs_ability`` buckets it as
  auto-attack damage (the Corki split rule). Priced after the rotation,
  it takes the auto-stream magic pen (the Terminus split rule).
- Q (Crescent Strike) is the one generic-shaped slot, pinned so the slot
  map is the whole kit. Moonlight (the 3s debuff enabling E's reset) has
  no damage of its own and is modeled entirely inside E.
- W (Pale Cascade) must read "Total Magic Damage" (3 orbs); the
  classifier picks the per-orb entry. The shield (both shield
  attributes) is pure mitigation and deliberately not modeled.
- E (Lunar Rush) is two dashes per activation with ``moonlight_reset``
  on: the first dash consumes Q's Moonlight, zeroing E's current
  cooldown, and she immediately dashes again — per-dash damage on the
  part with ``count=2`` (never pre-multiplied — the Amumu trap) and
  ``cast_instances=2`` for per-cast item procs; the natural cooldown
  separates activations.
- R (Moonfall) deals no damage with the pull itself; the delayed beam
  (always fires — the target is a champion) gains a per-champion bonus
  beyond the first that the generic path cannot express
  (``champions_pulled`` option). The "Total Damage Vs. 5 Champions"
  attribute is a derived display value and is only used as a test
  cross-check; the "Slow" attribute is not damage.

All numeric values are read from the champion JSON data; the only
mechanic constants are the cleave cadence and R's pull cap below.
"""

import math
from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import BUFF, SlotCtx, build_parser
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    simple_damage,
    sum_modifiers,
)
from .source_receipts import load_champion_sources
from .inputs import bool_option, int_option

# The binary roots the cleave's 2-stack cycle; R's beam bonus counts champions
# pulled beyond the first, up to 5 total, which remains a mechanic cap.
# https://wiki.leagueoflegends.com/en-us/Diana
_DIANA_PASSIVE_SPELL = spell_object("Diana", "DianaPassive")
_CLEAVE_EVERY_N_ATTACKS = int(data_value(_DIANA_PASSIVE_SPELL, "AttackCount"))
_R_MAX_CHAMPIONS_PULLED = 5

# Moonfall's damage is the beam, and the beam lands after the pull: "If an
# enemy champion is pulled, she calls down a beam of moonlight to strike
# upon the area around her after 1 second, dealing magic damage to all
# nearby enemies" (data/champions.json Diana R).  The cached entry
# attaches no cast-time qualifier to the number, so it is read from the
# cast start as written.
_DIANA_R_SPELL = spell_object("Diana", "DianaR")
_R_BEAM_SECONDS = data_value(_DIANA_R_SPELL, "Delay")

# P stores base and tripled attack speed as the 1st and 2nd
# "Per-Level Scaling" leveling entries (both arrays run 40 entries,
# indexed by level - 1). The base values (37.35% at level 20) are
# deliberately unused: tripled uptime is assumed 100%.
_TRIPLED_AS_OCCURRENCE = 1


def _moonsilver_blade(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: tripled bonus attack speed (15-35% base, x3 after any cast).

    BUFF phase — the tripled AS is fed into ``ctx.stats`` (so the cleave
    slot's auto count sees it) and emitted as a ``stat_buff`` so the
    fight engine's auto count and reported champion stats reflect it.
    """
    ability = ctx.ability()
    if ability is None:
        return None

    leveling = find_named_leveling(
        ability, "Per-Level Scaling", occurrence=_TRIPLED_AS_OCCURRENCE
    )
    if leveling is None:
        # A silent 0 would erase the passive — fail loudly instead.
        raise ValueError(
            "Diana P: second 'Per-Level Scaling' leveling entry (tripled "
            "attack speed) missing from the ability JSON"
        )
    tripled_as = sum_modifiers(leveling, ctx.level)

    # Parse-time context: the cleave slot's auto count reads attack_speed.
    ctx.stats["bonus_attack_speed"] = ctx.stat("bonus_attack_speed") + tripled_as
    ctx.stats["attack_speed"] = ctx.stat("attack_speed") + ctx.stat(
        "attack_speed_ratio"
    ) * (tripled_as / 100.0)

    entry = damage_entry(ability_name(ability), ctx.level, 0.0, 0.0, "magic")
    entry["stat_buff"] = {"bonus_attack_speed": tripled_as}
    entry["detail"] = (
        f"+{tripled_as:g}% bonus attack speed (tripled post-cast value, "
        f"assumed always active)"
    )
    return entry


_moonsilver_blade.phase = BUFF


def _moonsilver_cleave(ctx: SlotCtx) -> dict[str, Any] | None:
    """P cleave: every 3rd basic attack deals spell AoE magic damage.

    Rides the auto stream only — floor(autos / 3) procs over a timed
    fight's auto window; per-cast mode and zero-uptime fights have no
    auto stream, so no cleaves (accepted behavior, not a bug). The
    attack speed already includes P's buff (BUFF phase ran first), so
    the count matches the fight engine's buffed auto count.
    """
    ability = ctx.ability("P")
    if ability is None:
        return None
    duration = ctx.options.get("fight_duration_seconds")
    if duration is None:
        return None

    uptime = float(ctx.option("auto_attack_uptime"))
    num_autos = math.floor(ctx.stat("attack_speed") * float(duration) * uptime)
    cleaves = num_autos // _CLEAVE_EVERY_N_ATTACKS
    if cleaves <= 0:
        return None

    per_cleave = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )
    autos_per_second = ctx.stat("attack_speed") * uptime
    return {
        "name": "Moonsilver Blade (cleave)",
        "damage_type": "magic",
        "total_raw": per_cleave * cleaves,
        "parts": (DamagePart("magic", per_cleave),),
        "proc_count": cleaves,
        "damage_events": [
            {
                "time": (
                    index * _CLEAVE_EVERY_N_ATTACKS + (_CLEAVE_EVERY_N_ATTACKS - 1)
                )
                / autos_per_second,
                "damage_type": "magic",
                "damage": per_cleave,
                "event_precision": "exact",
            }
            for index in range(cleaves)
        ],
        "event_phase": "auto",
        "unit": "cleaves",
        "detail": (
            f"every 3rd basic attack: {cleaves} cleave(s) from "
            f"{num_autos} auto(s) over {float(duration):g}s"
        ),
    }


def _lunar_rush(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: dash damage, twice per activation when Moonlight resets it."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    per_dash = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    dashes = 2 if ctx.option("moonlight_reset") else 1
    return {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": per_dash * dashes,
        # Per-dash damage stays on the amount (never pre-multiplied);
        # each dash is its own cast for per-cast item procs.
        "parts": (DamagePart("magic", per_dash, count=dashes),),
        "cast_instances": dashes,
    }


def _moonfall(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: the delayed beam — base plus a bonus per champion pulled
    beyond the first (the pull itself deals no damage)."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    pulled = int(ctx.option("champions_pulled"))
    pulled = min(max(pulled, 1), _R_MAX_CHAMPIONS_PULLED)
    total = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    total += (pulled - 1) * extract_named(
        ability, "Bonus Damage Per Champion", rank, ctx.stats, ctx.target
    )

    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", total, time_offset=_R_BEAM_SECONDS),)
    if pulled > 1:
        entry["detail"] = f"beam vs {pulled} champions pulled"
    return entry


OPTIONS: list[dict[str, Any]] = [
    bool_option(
        "moonlight_reset",
        True,
        label="E consumes Q's Moonlight and resets (2 dashes per activation)",
        rotation={
            "role": "consume",
            "slot": "E",
            "condition": "moonlight",
            "kind": "mark_consume",
            "setup_slot": "Q",
            "note": (
                "E consumes Q's Moonlight for the reset; the option gates "
                "the dash count (2 vs 1 damage instances), not the Q->E edge."
            ),
        },
    ),
    int_option(
        "champions_pulled",
        1,
        minimum=1,
        maximum=_R_MAX_CHAMPIONS_PULLED,
        label="Champions pulled by R (beam gains 35/60/85 +15% AP per "
        "champion beyond the first)",
    ),
]

ASSUMPTIONS = [
    "Passive tripled attack speed (post-ability-cast) assumed always "
    "active during the fight",
    "Passive cleave procs on every 3rd auto attack; rides the auto stream "
    "only (no cleaves in one-rotation mode)",
    "All 3 W orbs detonate on the target; W shield not modeled",
    "R beam always fires (target is a champion); pull itself deals no damage",
    "E's second dash (after Moonlight reset) hits the same target for full damage",
]

SLOTS = {
    "P": _moonsilver_blade,
    # The bolt's arc has no sourced duration in the cached packet, so the
    # cast boundary is the only placement its one explosion has.
    "Q": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "W": simple_damage(attr="Total Magic Damage", dmg_type="magic"),
    "E": _lunar_rush,
    "R": _moonfall,
    # Synthetic slot: the auto_attacks_ prefix buckets the row as
    # auto-attack damage in split_auto_vs_ability.
    "auto_attacks_moonsilver_cleave": _moonsilver_cleave,
}

# Cached kit review.  Q only "afflict[s] them with Moonlight", a mark that
# reveals and that Lunar Rush consumes — no control.  R "pulls all nearby
# enemies towards her ... then slows them for 2 seconds" and only then
# lands the beam this row prices, so the pull is the immobilizing control
# the damaged target took; the beam's sourced 1-second delay is now
# authored, which is what lets the row say so.
#
# W and E stay UNREVIEWED, so this kit keeps the coarse control-armed
# scan.  W's row is the cached "Total Magic Damage" of all three spheres,
# which detonate "upon contact with an enemy" on no sourced cadence, and
# E's row is the dash count in one part with no interval between the two
# dashes.  Neither is a delay this review can author.
MODULE_CC = {"Q": "none", "R": "pull"}

parse_abilities = build_parser(SLOTS, "Diana", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Diana")
