"""Heimerdinger's rocket, grenade and source-receipted turret timeline."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage
from .slotlib import damage_entry, extract_cooldown, extract_named, extract_recharge
from .source_receipts import load_champion_sources
from .inputs import int_option


def _turret_damage(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("Q", min(max(int(ctx.option("q_variant")), 0), 1))
    if ability is None:
        return None
    variant = min(max(int(ctx.option("q_variant")), 0), 1)
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None
    turret_count = min(max(int(ctx.option("q_turrets")), 1), 3)
    attacks = min(max(int(ctx.option("q_turret_attacks")), 1), 12)
    if variant == 0:
        shot = (
            7.0
            + (23.0 - 7.0) * (ctx.level - 1) / 17.0
            + 0.35 * ctx.stat("ability_power")
        )
        beam = 40.0 + 20.0 * (rank - 1) + 0.55 * ctx.stat("ability_power")
        name = "H-28G Evolution Turret"
    else:
        r_rank = min(max(ctx.rank_for("R"), 1), 3)
        shot = 80.0 + 20.0 * (r_rank - 1) + 0.35 * ctx.stat("ability_power")
        beam = 100.0 + 40.0 * (r_rank - 1) + 0.70 * ctx.stat("ability_power")
        name = "H-28Q Apex Turret"
    total_shots = turret_count * attacks
    beam_count = min(max(int(ctx.option("q_beams")), 0), turret_count)
    parts = [
        DamagePart(
            "magic",
            shot,
            count=total_shots,
            time_offset=0.0,
            hit_interval=1.0 if variant else 1.75,
        )
    ]
    if beam_count:
        parts.append(
            DamagePart(
                "magic", beam, count=beam_count, time_offset=2.0, hit_interval=1.0
            )
        )
    # Q is a charge ability: the JSON cooldown field holds only the 1s
    # inter-cast timer, and the limiter for sustained use is the 20s
    # rechargeRate.  Without it the engine scheduled 9 deploys in a 10s
    # window — each cast re-priced the full turret swarm.
    cooldown = extract_recharge(ctx.ability("Q", 0), rank)
    entry = damage_entry(
        name,
        rank,
        cooldown,
        sum(p.amount * p.count for p in parts),
        "magic",
    )
    entry["parts"] = tuple(parts)
    entry["event_order_certified"] = "sourced turret attack and beam cadence"
    entry["detail"] = (
        f"{turret_count} {name} unit(s), {attacks} shot(s) each, {beam_count} charged beam(s)."
    )
    return entry


# W/E timing + upgraded-E constants (P3 package 3Z).  0.25 is the cached
# W/E castTime ("0.25"); 0.35 / 0.08 / 0.6 have NO JSON home — they are
# module-authored timing pins (the wiki's rocket cadence), declared with
# provenance in the typed rule receipts and flagged uncertified.
_W_FIRST_TIME_OFFSET = 0.25
_W_LATER_TIME_OFFSET = 0.35
_W_HIT_INTERVAL = 0.08
_E_TIME_OFFSET = 0.6
_E_UPGRADED_VALUES = (100.0, 200.0, 300.0)
_E_UPGRADED_AP_RATIO = 0.60


class _MicroRocketsRule:
    """The typed Hextech Micro-Rockets declaration (P3 package 3Z).

    W prices one first rocket from the "Initial Rocket Magic Damage"
    row + (n-1) subsequent rockets from the "Subsequent Rocket Magic
    Damage" row (the per-rocket champion reduction).  The cached
    leveling rows are degraded (units arrays empty) — the module names
    the explicit rows, which resolve flat.  The rocket count (1..5,
    default 5) and the timing pins (first 0.25 = the cached castTime;
    subsequent 0.35 start @ 0.08 interval = module-authored) ride the
    ``w_rockets`` option's state receipt.
    """

    def __init__(self) -> None:
        self.first_row_attribute = "Initial Rocket Magic Damage"
        self.subsequent_row_attribute = "Subsequent Rocket Magic Damage"
        self.first_time_offset = _W_FIRST_TIME_OFFSET
        self.subsequent_time_offset = _W_LATER_TIME_OFFSET
        self.hit_interval = _W_HIT_INTERVAL
        self.default = 5
        self.min = 1
        self.max = 5
        self.source = {
            "label": "Local League Wiki cache — Heimerdinger W template",
            "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Heimerdinger/W",
            "revision_id": 2864243,
            "revision_timestamp": "2019-11-03T20:09:52Z",
            "parent_revision_id": 4025016,
            "note": "first_time_offset is the cached W castTime; "
            "subsequent_time_offset/hit_interval are module-authored "
            "(no JSON home) — flagged uncertified.",
        }

    def public_receipt(self) -> dict[str, Any]:
        return {
            "name": "Heimerdinger — Hextech Micro-Rockets (W)",
            "first_row_attribute": self.first_row_attribute,
            "subsequent_row_attribute": self.subsequent_row_attribute,
            "first_time_offset": self.first_time_offset,
            "subsequent_time_offset": self.subsequent_time_offset,
            "hit_interval": self.hit_interval,
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "source": dict(self.source),
        }


HEIMER_W_ROCKETS_RULE = _MicroRocketsRule()


class _GrenadeRule:
    """The typed Electron Storm Grenade declaration (P3 package 3Z).

    E prices ONE champion damage instance per cast.  The base variant
    reads the cached "Magic Damage" row (degraded units — resolved
    flat); the R-upgraded variant prices the module tuple
    100/200/300 (+60% AP) — the cached E[1] row is HALF-PARSED
    (modifiers:[] — the numbers survive only in the attribute string),
    so the tuple is a declared module constant with provenance.  The
    0.6 impact offset is module-authored (uncertified).  Bounces,
    stun and slow are control state, not damage.
    """

    def __init__(self) -> None:
        self.base_row_attribute = "Magic Damage"
        self.upgraded_values = _E_UPGRADED_VALUES
        self.upgraded_ap_ratio = _E_UPGRADED_AP_RATIO
        self.time_offset = _E_TIME_OFFSET
        self.one_instance = True
        self.source = {
            "label": "Local League Wiki cache — Heimerdinger E template",
            "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Heimerdinger/E",
            "revision_id": 2864389,
            "revision_timestamp": "2019-11-03T20:12:23Z",
            "parent_revision_id": 4025016,
            "note": "upgraded_values/upgraded_ap_ratio come from the "
            "half-parsed E[1] attribute string (no modifiers/atoms); "
            "time_offset is module-authored (no JSON home) — flagged "
            "uncertified.",
        }

    def public_receipt(self) -> dict[str, Any]:
        return {
            "name": "Heimerdinger — CH-2/CH-3X Electron Storm Grenade (E)",
            "base_row_attribute": self.base_row_attribute,
            "upgraded_values": list(self.upgraded_values),
            "upgraded_ap_ratio": self.upgraded_ap_ratio,
            "time_offset": self.time_offset,
            "one_instance": self.one_instance,
            "source": dict(self.source),
        }


HEIMER_E_GRENADE_RULE = _GrenadeRule()


def _require_row(ability: dict[str, Any], attribute: str) -> None:
    """Fail loud when the named leveling row is absent (cache corruption).

    The degraded W/E rows must never price a silent zero: a missing row
    raises naming the champion, ability and attribute (the repo's
    fail-closed convention for missing keys).
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                return
    raise KeyError(
        f"Heimerdinger {ability.get('name', '?')} has no {attribute!r} " "leveling row"
    )


def _micro_rockets(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked("W", 0)
    if ranked is None:
        return None
    ability, rank = ranked
    rockets = min(max(int(ctx.option("w_rockets")), 1), 5)
    _require_row(ability, "Initial Rocket Magic Damage")
    _require_row(ability, "Subsequent Rocket Magic Damage")
    first = extract_named(
        ability, "Initial Rocket Magic Damage", rank, ctx.stats, ctx.target
    )
    later = extract_named(
        ability, "Subsequent Rocket Magic Damage", rank, ctx.stats, ctx.target
    )
    parts = [DamagePart("magic", first, time_offset=_W_FIRST_TIME_OFFSET)]
    if rockets > 1:
        parts.append(
            DamagePart(
                "magic",
                later,
                count=rockets - 1,
                time_offset=_W_LATER_TIME_OFFSET,
                hit_interval=_W_HIT_INTERVAL,
            )
        )
    entry = damage_entry(
        ability.get("name", "Hextech Micro-Rockets"),
        rank,
        extract_cooldown(ability, rank),
        first + later * (rockets - 1),
        "magic",
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = (
        f"{rockets} authored rockets; subsequent rockets use the reduced champion damage row."
    )
    return entry


def _grenade(ctx: SlotCtx) -> dict[str, Any] | None:
    variant = min(max(int(ctx.option("e_upgrade")), 0), 1)
    ranked = ctx.ranked("E", variant)
    if ranked is None:
        return None
    ability, rank = ranked
    if variant == 0:
        _require_row(ability, "Magic Damage")
        value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    else:
        r_rank = min(max(ctx.rank_for("R"), 1), 3)
        value = _E_UPGRADED_VALUES[r_rank - 1] + _E_UPGRADED_AP_RATIO * ctx.stat(
            "ability_power"
        )
    entry = damage_entry(
        ability.get("name", "CH-2 Electron Storm Grenade"),
        rank,
        extract_cooldown(ctx.ability("E", 0), rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=_E_TIME_OFFSET),)
    entry["detail"] = (
        "One champion damage instance; bounces, stun and slow are sourced control state."
    )
    return entry


def _upgrade(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="UPGRADE!!!",
        reason="The ultimate is an empowerment toggle; its selected Q/W/E variant carries the outgoing damage.",
    )


SLOTS = {
    "P": lambda ctx: no_damage(
        ctx,
        name="Hextech Affinity",
        reason="The passive is movement speed near allied structures or turrets.",
    ),
    "Q": _turret_damage,
    "W": _micro_rockets,
    "E": _grenade,
    "R": _upgrade,
}
# Turret attacks/beams and both rocket waves only damage.  Both grenade
# variants "slow them by 35% for 2 seconds" on every enemy they damage;
# the 1.5-second stun needs a centre hit the module does not model, so the
# unconditional slow is the reviewed kind.  P and R author no damage part.
MODULE_CC = {"Q": "none", "W": "none", "E": "slow"}

parse_abilities = build_parser(SLOTS, "Heimerdinger", cc_kinds=MODULE_CC)
OPTIONS = [
    int_option(
        "q_variant", 0, minimum=0, maximum=1, label="Turret variant (Evolution/Apex)"
    ),
    int_option("q_turrets", 3, minimum=1, maximum=3, label="Deployed turrets"),
    int_option("q_turret_attacks", 3, minimum=1, maximum=12, label="Turret attacks"),
    int_option("q_beams", 1, minimum=0, maximum=3, label="Charged beams"),
    int_option(
        "w_rockets",
        5,
        minimum=1,
        maximum=5,
        label="Rockets hitting the target",
        state=HEIMER_W_ROCKETS_RULE.public_receipt(),
    ),
    int_option(
        "e_upgrade",
        0,
        minimum=0,
        maximum=1,
        label="Grenade variant",
        state=HEIMER_E_GRENADE_RULE.public_receipt(),
    ),
]
ASSUMPTIONS = [
    "Turret shot/beam values and cadences are copied from the full Wiki Pets entry because the champion slot template intentionally contains no pet formula rows.",
    "Q is a charge ability: its cooldown is the 20s rechargeRate (the "
    "JSON cooldown field is only the 1s inter-cast timer), so one deploy "
    "is priced per 20s window; the q_turrets/q_turret_attacks options set "
    "how many turrets and shots one deploy contributes.",
    "The R upgrade is the q_variant option: the H-28Q Apex Turret rows "
    "scale by R rank (shots 80-120 +35% AP, beams 100-180 +70% AP).",
    "Rocket multi-hit reduction uses the explicit first/subsequent rows; only one champion hit is counted for the upgraded grenade.",
    "UPGRADE!!!, stuns, slows, turret targeting and vision are state/utility, not extra direct champion damage.",
]
SOURCES = load_champion_sources("Heimerdinger")
