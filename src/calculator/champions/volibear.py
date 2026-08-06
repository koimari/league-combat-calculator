"""Volibear — reviewed packet slots plus the E3 stack mechanics.

E3 additions over the CP10.9 packet module:
- P (The Relentless Storm) becomes a BUFF-phase stack slot: each of up
  to 5 stacks grants 5% (+ 3% per 100 AP) bonus attack speed (25% + 15%
  per 100 AP fully stacked), and at 5 stacks basic attacks gain
  Lightning Claws on-hit bonus magic damage (level-scaled flat + 45%
  AP). The stack count is a user option (``relentless_storm_stacks``,
  default 5 = the sustained-fight state) — the model cannot simulate
  which specific damage events re-stack the 6-second window, so the
  pre-stacked count is priced instead, matching the module convention
  for stack passives (Ezreal P, Darius P).
- W (Frenzied Maul) prices the Wounded 2nd bite: the first cast marks
  the target Wounded for 8 seconds and the next cast on the same
  target deals 50% (+ 25% per 100 bonus AD) increased damage. The
  ``w_wounded`` option (default True) selects the already-marked bite —
  the one-rotation model casts W once, so this is the sourced
  empowered cast rather than a simulated apply-then-recast sequence.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .reviewed_batch_09 import build_batch_module
from .slotlib import attach_self_shield, damage_entry, extract_cooldown, extract_named

_packet_parse, _packet_slots, _packet_assumptions, _packet_sources, _packet_options = (
    build_batch_module("Volibear")
)

# HARDCODED: verify on patch updates — The Relentless Storm's per-stack
# attack speed (5% + 3% per 100 AP) and the Wounded bite's increase
# (50% + 25% per 100 bonus AD) are wiki prose; the JSON only carries the
# Lightning Claws on-hit damage row and the W base damage.
_RELENTLESS_STORM_MAX_STACKS = 5
_STORM_AS_PER_STACK = 5.0  # % bonus attack speed per stack
_STORM_AS_PER_100_AP = 3.0  # additional % per stack per 100 AP
_WOUNDED_BONUS_BASE = 0.50  # +50% damage on the 2nd bite
_WOUNDED_BONUS_PER_100_BONUS_AD = 0.25  # +25% per 100 bonus AD
# HARDCODED: verify on patch updates — Sky Splitter's self shield is
# prose-only in the cached ability description ("a shield equal to 14% of
# his maximum health (+ 75% AP) for 3 seconds"); the JSON carries no
# Shield leveling row, so the ratio and duration are pinned here from the
# cached description (data/champions.json, Volibear E).
_SKY_SPLITTER_SHIELD_MAX_HP_RATIO = 0.14
_SKY_SPLITTER_SHIELD_AP_RATIO = 0.75
_SKY_SPLITTER_SHIELD_DURATION_SECONDS = 3.0


def _relentless_storm(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: per-stack bonus AS; at 5 stacks, Lightning Claws on-hit magic.

    BUFF phase: the bonus attack speed is published as a ``stat_buff``
    the fight engine applies before autos are counted, and the
    Lightning Claws on-hit rides the same entry so a fully-stacked
    Volibear's basic attacks carry the sourced magic damage.
    """
    ability = ctx.ability()
    if ability is None:
        return None

    stacks = int(
        ctx.options.get("relentless_storm_stacks", _RELENTLESS_STORM_MAX_STACKS)
    )
    stacks = min(max(stacks, 0), _RELENTLESS_STORM_MAX_STACKS)
    ap = ctx.stats.get("ability_power", 0.0)
    per_stack = _STORM_AS_PER_STACK + _STORM_AS_PER_100_AP * ap / 100.0
    bonus_as = stacks * per_stack

    entry: dict[str, Any] = {
        "name": ability.get("name", "The Relentless Storm"),
        "rank": ctx.level,
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "stat_buff": {"bonus_attack_speed": bonus_as},
        "detail": (
            f"{stacks}/{_RELENTLESS_STORM_MAX_STACKS} stack(s); "
            f"{bonus_as:g}% bonus attack speed ({per_stack:g}% per stack)"
        ),
    }

    if stacks >= _RELENTLESS_STORM_MAX_STACKS:
        per_hit = extract_named(
            ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
        )
        if per_hit > 0:
            entry["on_hit"] = {
                "name": "Lightning Claws (on-hit)",
                "damage_per_hit": per_hit,
                "damage_type": "magic",
            }
    return entry


_relentless_storm.phase = BUFF


def _frenzied_maul(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: base physical damage; the Wounded 2nd bite adds the sourced
    increased-damage part (50% + 25% per 100 bonus AD of the base)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    base = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    cooldown = extract_cooldown(ability, rank)
    name = ability.get("name", "Frenzied Maul")

    if not ctx.options.get("w_wounded", True):
        return damage_entry(name, rank, cooldown, base, "physical")

    bonus_ad = ctx.stats.get("bonus_attack_damage", 0.0)
    extra_ratio = (
        _WOUNDED_BONUS_BASE + _WOUNDED_BONUS_PER_100_BONUS_AD * bonus_ad / 100.0
    )
    extra = base * extra_ratio
    entry = damage_entry(name, rank, cooldown, base + extra, "physical")
    entry["parts"] = (
        DamagePart("physical", base),
        DamagePart("physical", extra),
    )
    entry["detail"] = (
        f"Wounded 2nd bite: +{extra_ratio * 100:g}% increased damage "
        f"(+{extra:g} over the {base:g} base)"
    )
    return entry


def _sky_splitter(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: the reviewed magic hit plus the sourced self-shield payload.

    The 14% max HP + 75% AP shield (cached description prose) rides the
    E damage event; the shared ledger grants it as a timed 3-second
    self-shield at the cast.
    """
    entry = _packet_e(ctx)
    rank = int(entry.get("rank", 0) or 0) if entry is not None else 0
    if entry is None or rank < 1:
        return entry
    shield = _SKY_SPLITTER_SHIELD_MAX_HP_RATIO * ctx.stats.get(
        "health", 0.0
    ) + _SKY_SPLITTER_SHIELD_AP_RATIO * ctx.stats.get("ability_power", 0.0)
    return attach_self_shield(
        entry,
        amount=shield,
        duration=_SKY_SPLITTER_SHIELD_DURATION_SECONDS,
        source=entry.get("name", "Sky Splitter"),
        detail=(
            f"E also shields Volibear for {shield:g} for "
            f"{_SKY_SPLITTER_SHIELD_DURATION_SECONDS:g}s "
            f"(14% max HP + 75% AP)"
        ),
    )


SLOTS = dict(_packet_slots)
SLOTS["P"] = _relentless_storm
SLOTS["W"] = _frenzied_maul
_packet_e = SLOTS["E"]
SLOTS["E"] = _sky_splitter
parse_abilities = build_parser(SLOTS, "Volibear")

OPTIONS = list(_packet_options) + [
    {
        "key": "relentless_storm_stacks",
        "type": "int",
        "default": _RELENTLESS_STORM_MAX_STACKS,
        "min": 0,
        "max": _RELENTLESS_STORM_MAX_STACKS,
        "label": "The Relentless Storm stacks",
    },
    {
        "key": "w_wounded",
        "type": "bool",
        "default": True,
        "label": "W hits an already-Wounded target (2nd bite)",
    },
]

ASSUMPTIONS = list(_packet_assumptions) + [
    "The Relentless Storm stack count is user-set (default 5 = fully "
    "stacked); the 6-second stack window and which damage events refresh "
    "it are not simulated",
    "Each stack grants 5% (+ 3% per 100 AP) bonus attack speed — wiki "
    "prose (module constant)",
    "Lightning Claws on-hit magic damage applies to every basic attack "
    "while at 5 stacks; the 450-range secondary-target chain is not "
    "modeled (single-target calc)",
    "Frenzied Maul's Wounded 2nd bite deals 50% (+ 25% per 100 bonus AD) "
    "increased damage — wiki prose (module constant); the option picks "
    "the already-marked bite because the one-rotation model casts W once",
    "E (Sky Splitter) also shields Volibear for 14% max HP + 75% AP for "
    "3s at the cast (cached description prose, module constants); the "
    "shield absorbs incoming damage in the participant ledger",
    "Q's stun/MS, W's heal and R's bonus health remain utility/state " "only",
]

SOURCES = list(_packet_sources)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
