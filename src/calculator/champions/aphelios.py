"""Aphelios' reviewed weapon-aware damage module.

The weapon choice is explicit input, never inferred from a marksman
archetype.  Q's Onslaught is represented as an attack event whose count is
the Wiki's ``6 + 2 per 100% bonus attack speed`` rule; the other weapon Q
forms use the pinned packet variants.  R's initial blast and the basic-attack
follow-up are kept separate so resistance and event ordering remain visible.

Reviewed crowd control rides the parts rather than a ``MODULE_CC`` map:
both Q and R are one slot per weapon, and the weapons do not control alike
(``_Q_CC_BY_WEAPON``, ``_R_CC_BY_WEAPON``).
"""

from dataclasses import replace
from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown

PACKET_SHA256 = "8a0a5d9fa966d29c754a5e4bc8ca56d541a843bb2af95c3266438556aebf499c"

_packet_parse, _packet_slots, _packet_assumptions, _packet_sources, _ = (
    build_packet_module("Aphelios", PACKET_SHA256)
)
PACKET_SPEC = _packet_slots.packet_spec

_WEAPON_INDEX = {
    "calibrum": 0,
    "severum": 1,
    "gravitum": 2,
    "infernum": 3,
    "crescendum": 4,
}
_WEAPON_LABELS = {
    "calibrum": "Calibrum",
    "severum": "Severum",
    "gravitum": "Gravitum",
    "infernum": "Infernum",
    "crescendum": "Crescendum",
}

# Q's reviewed crowd control is per weapon, because Q is five spells.  Read
# off data/champions.json Aphelios Q, in the cache's own order:
#   Moonshot     "fires a bolt of energy ... that deals ... damage to the
#                 first enemy hit" — nothing else.
#   Onslaught    "automatically performing up to 6 (+ 2 per 100% bonus
#                 attack speed) attacks over the duration" — attacks only.
#                 Absent from the map: see _Q_ONSLAUGHT_SECONDS_UNAUTHORED.
#   Binding Eclipse
#                "dealing ... magic damage and rooting them for 1 second".
#   Duskwave     "dealing ... physical damage to all enemies hit and
#                 locking onto each of them" — the lock-on is targeting.
#   Sentry       "autonomously attacks the nearest visible enemy in range
#                 ... dealing ... physical damage per hit".
_Q_CC_BY_WEAPON = {
    "calibrum": "none",
    "gravitum": "root",
    "infernum": "none",
    "crescendum": "none",
    "severum": "none",
}

# Onslaught's whole schedule is in one cached sentence: "Aphelios enters an
# onslaught for 1.75 seconds ... automatically performing up to 6 (+ 2 per
# 100% bonus attack speed) attacks over the duration".  The count is what
# scales, not the window, so the attacks come at a fixed rate of
# ``count / 1.75`` per second — the first as he enters the onslaught, the
# rest on that beat, all of them inside the cached duration.
#
# Severum's self-heal follows those attacks rather than the row, because
# it says so: "Severum's attacks heal Aphelios for ... of the post-
# mitigation damage dealt" is a share of each attack, and the rule is
# declared ``HealAnchor.DAMAGING_HIT``, so six attacks pay six shares of
# what they each dealt and an attack that dealt nothing pays nothing.
_Q_ONSLAUGHT_SECONDS = 1.75

# R's blast controls only under Gravitum, which "Increases the initial slow
# to 99%"; every other weapon's follow-up is a mark, a heal, bonus damage
# or extra chakrams.
_R_CC_BY_WEAPON = dict.fromkeys(_WEAPON_INDEX, "none") | {"gravitum": "slow"}


def _main_weapon(ctx: SlotCtx) -> str:
    value = str(ctx.options.get("aphelios_main_weapon", "calibrum")).lower()
    return value if value in _WEAPON_INDEX else "calibrum"


def _weapon_master(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("P")
    if not ability:
        return None
    ad_points = min(max(int(ctx.option("aphelios_bonus_ad_points")), 0), 6)
    as_points = min(max(int(ctx.option("aphelios_bonus_as_points")), 0), 6)
    lethality_points = min(max(int(ctx.option("aphelios_lethality_points")), 0), 6)
    entry = damage_entry(ability["name"], 1, 0.0, 0.0, "physical")
    bonus_ad = 4.0 * ad_points
    bonus_as = 9.0 * as_points
    if bonus_ad:
        ctx.stats["attack_damage"] = ctx.stat("attack_damage") + bonus_ad
        ctx.stats["bonus_attack_damage"] = ctx.stat("bonus_attack_damage") + bonus_ad
    if bonus_as:
        ctx.stats["bonus_attack_speed"] = ctx.stat("bonus_attack_speed") + bonus_as
        ctx.stats["attack_speed"] = (
            ctx.stat("attack_speed") + ctx.stat("attack_speed_ratio") * bonus_as / 100.0
        )
    if lethality_points:
        ctx.stats["lethality"] = ctx.stat("lethality") + 4.5 * lethality_points
    entry["stat_buff"] = {
        "bonus_attack_damage": bonus_ad,
        "bonus_attack_speed": bonus_as,
    }
    entry["detail"] = (
        f"Weapon Master: {ad_points} AD / {as_points} AS / {lethality_points} lethality points"
    )
    return entry


_weapon_master.phase = BUFF


def _phase(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("W")
    if not ability:
        return None
    entry = damage_entry(ability["name"], 1, 0.25, 0.0, "physical")
    entry["detail"] = "Swap main and off-hand weapons"
    return entry


def _q(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("Q", 0)
    if not ability:
        return None
    weapon = _main_weapon(ctx)
    rank = ctx.level
    if weapon != "severum":
        # The generated source has one packet for each Wiki weapon form. Its
        # variants are explicitly selected here rather than by role.
        original = ctx.options.get("q_variant")
        ctx.options["q_variant"] = _WEAPON_INDEX[weapon]
        try:
            result = _packet_slots["Q"](ctx)
            if result is not None and weapon == "calibrum":
                # Wiki: Duskwave volleys apply on-hit effects at 100%.
                result["applies_item_on_hits"] = {
                    "effectiveness": 1.0,
                    "hits": 1,
                    "triggers": ("on_hit",),
                }
            if result is not None:
                # Each of these four weapon forms prices one hit, so the
                # cast boundary IS the hit and the reviewed kind rides it.
                result["parts"] = tuple(
                    replace(part, cc_kind=_Q_CC_BY_WEAPON[weapon])
                    for part in result.get("parts", ())
                )
                result["event_order_certified"] = "single_hit"
            return result
        finally:
            if original is None:
                ctx.options.pop("q_variant", None)
            else:
                ctx.options["q_variant"] = original

    # Onslaught: six attacks, plus two per 100% bonus attack speed. The
    # attack event carries 20%-41% AD per hit and therefore scales with both
    # AD and attack-speed-derived count, not raw AD alone.
    values = (0.20, 0.235, 0.27, 0.305, 0.34, 0.375, 0.41)
    ratio = values[min(max(rank, 1), len(values)) - 1]
    bonus_as = max(0.0, float(ctx.stat("bonus_attack_speed")))
    count = max(1, int(6 + 2 * bonus_as / 100.0))
    per_hit = ratio * float(ctx.stat("attack_damage"))
    entry = damage_entry(
        ability.get("name", "Onslaught"),
        rank,
        10.0,
        per_hit * count,
        "physical",
    )
    entry["parts"] = (
        DamagePart(
            "physical",
            amount=per_hit,
            count=count,
            time_offset=0.0,
            hit_interval=_Q_ONSLAUGHT_SECONDS / count,
            cc_kind=_Q_CC_BY_WEAPON["severum"],
        ),
    )
    entry["detail"] = f"Onslaught: {count} weapon attacks at {ratio:.1%} AD each"
    # Wiki: every Onslaught attack applies on-hit effects at 25% effectiveness.
    entry["applies_item_on_hits"] = {
        "effectiveness": 0.25,
        "hits": count,
        "triggers": ("on_hit",),
    }
    return entry


def _r(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("R")
    if not ability:
        return None
    r_rank = 1 if ctx.level < 11 else (2 if ctx.level < 16 else 3)
    base = (125.0, 175.0, 225.0)[r_rank - 1]
    ad = float(ctx.stat("bonus_attack_damage"))
    ap = float(ctx.stat("ability_power"))
    # The cache carries no leveling row for Moonlight Vigil, so its bases stay
    # reviewed constants — but the cooldown row is there, and it falls by rank.
    entry = damage_entry(
        ability["name"],
        r_rank,
        extract_cooldown(ability, r_rank),
        base + 0.20 * ad + ap,
        "physical",
    )
    entry["parts"] = (
        DamagePart(
            "physical",
            amount=base + 0.20 * ad + ap,
            cc_kind=_R_CC_BY_WEAPON[_main_weapon(ctx)],
        ),
    )
    # One blast, priced once: the cast boundary is the hit.
    entry["event_order_certified"] = "single_hit"
    detail = f"Moonlight Vigil initial blast · {_WEAPON_LABELS[_main_weapon(ctx)]} follow-up is event-ordered separately"
    # The healing rule reads this marker to gate Severum's overheal-to-
    # shield conversion (the Shyvana dragon-form convention).
    if _main_weapon(ctx) == "severum" and bool(
        ctx.options.get("aphelios_overheal_shield", True)
    ):
        detail += " · overheal shield on"
    entry["detail"] = detail
    return entry


SLOTS = {"P": _weapon_master, "W": _phase, "Q": _q, "R": _r}
parse_abilities = build_parser(SLOTS, "Aphelios")

OPTIONS = [
    {
        "key": "aphelios_main_weapon",
        "type": "select",
        "default": "calibrum",
        "label": "Aphelios main weapon",
        "choices": [
            {"value": key, "label": label} for key, label in _WEAPON_LABELS.items()
        ],
    },
    {
        "key": "aphelios_bonus_ad_points",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 6,
        "label": "Weapon Master AD points",
    },
    {
        "key": "aphelios_bonus_as_points",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 6,
        "label": "Weapon Master AS points",
    },
    {
        "key": "aphelios_lethality_points",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 6,
        "label": "Weapon Master lethality points",
    },
    {
        "key": "aphelios_overheal_shield",
        "type": "bool",
        "default": True,
        "label": "Severum overheal converts into a shield",
    },
]

ASSUMPTIONS = [
    "The main weapon and Weapon Master skill-point allocation are explicit scenario inputs.",
    "Onslaught applies wiki-sourced item on-hits at 25% per attack; Duskwave (calibrum Q) at 100%. Moonlight Vigil follow-ups remain unmodeled.",
    "Moonlight Vigil models the sourced initial blast; weapon-specific follow-up attacks remain listed in the result as a separate coverage boundary.",
    "Severum's excess healing converts into a shield capped at the sourced "
    "per-level 'Heal' row (10 : 160 by level + 6% maximum health) that "
    "lingers for up to 30 seconds (wiki P prose); with "
    "aphelios_overheal_shield (default True) the healing rule stamps each "
    "Severum heal with the sourced cap and duration, and the participant "
    "timeline converts heal-in-excess-of-maximum-health into a timed "
    "shield at the heal's timestamp.",
]
SOURCES = list(_packet_sources) + [
    {
        "label": "Aphelios weapon system",
        "url": "https://wiki.leagueoflegends.com/en-us/Aphelios",
        "revision_id": 4022591,
        "revision_timestamp": "2026-05-27T00:28:15Z",
    },
]


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Aphelios")
