"""Trundle — CP10.8 full-entry-reviewed packet module.

P (King's Tribute) heals "1.8% : 5.94% (based on level) of their maximum
health" whenever a nearby enemy dies (cached P prose; the level row is
mislabelled ``Max Health Damage``).  A duel simulates no wave and no
takedown, so the count is the ``p_nearby_deaths`` option and the P row
carries the sourced per-death amount for the self-heal rule to place.

W (Frozen Domain) is the kit's attack-speed steroid — the compiled
no-damage row is replaced by the shared ``stat_buff`` slot so the cached
"Bonus Attack Speed" row reaches the auto stream.

E (Pillar of Ice) stays ``out_of_scope``: terrain, a knockback and a
34-50% slow, and the engine has no terrain axis and no CC magnitude —
``cc_kind`` is one vocabulary word per part with neither duration nor
percent (``ability_spec.py``).
"""

from typing import Any

from .engine import SlotCtx
from .healing_contract import declare_healing_rule
from .packet_module import build_packet_module, repeat_damage_parser
from .slotlib import extract_value, stat_buff

PACKET_SHA256 = "0346556b3577caf70cd1fadf59cbec2eb38d07d723625a473330e5c2618b0d4b"

# King's Tribute reads the maximum health of the unit that died.  A duel
# knows one unit's maximum health — the enemy this pair fight is priced
# against — so the heal is the sourced champion-sized amount and the
# option's count is what the user supplies.  Only the primary defender
# carries it: one death is one heal, not one per roster pair.
_P_LEVEL_ROW = "Max Health Damage"


def _kings_tribute(compiled):
    """P: carry the sourced per-death heal when the user declares deaths."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = compiled(ctx)
        if entry is None:
            return None
        deaths = max(0, int(ctx.option("p_nearby_deaths")))
        if deaths <= 0 or int(ctx.target_stat("roster_target_index")) != 0:
            return entry
        percent = extract_value(
            ctx.ability("P") or {}, _P_LEVEL_ROW, ctx.level, level=ctx.level
        )
        amount = percent / 100.0 * float(ctx.target_stat("target_max_health"))
        if amount <= 0.0:
            return entry
        entry["self_heal_state"] = {"deaths": deaths, "amount": amount}
        entry["detail"] = (
            f"{deaths} nearby enemy death(s): {percent:g}% of the dying "
            f"unit's maximum health each ({amount:.1f} against this target)"
        )
        return entry

    return parse


# Reviewed crowd control, read from the cached kit.  Q (Chomp) empowers
# one attack to "deal bonus physical damage and slow the target by 75% for
# 0.1 seconds".  R (Subjugate) "deal[s] magic damage and heal[s] himself
# for the same amount" and reduces resistances and size — real debuffs,
# but none of them crowd control.  W (Frozen Domain) and E (Pillar of Ice)
# carry the kit's other control and deal no damage.
MODULE_CC = {"Q": "slow", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Trundle",
    PACKET_SHA256,
    # Chomp is one empowered basic attack, so its row is one blow the
    # ledger can time; Subjugate already authors its 8 drain ticks.
    single_hit_slots=frozenset({"Q"}),
    cc_kinds=MODULE_CC,
    assumption_overrides=(
        "Subjugate prices the full 4-second drain: Magic Damage Per Second "
        "x 8 == Total Magic Damage / Total Healing at every rank.",
    ),
    slot_parsers={
        "R": repeat_damage_parser(
            attr="Magic Damage Per Second",
            dmg_type="magic",
            count=8,
            time_offset=0.5,
            hit_interval=0.5,
            dot_duration=4.0,
            name="Subjugate",
        ),
        # Frozen Domain's cached "Bonus Attack Speed" row (30-90% by rank)
        # through the shared steroid slot, so the fight's auto stream sees
        # it instead of the packet's no-damage placeholder.
        "W": stat_buff(
            attr="Bonus Attack Speed",
            stat="bonus_attack_speed",
            apply_to=("bonus_attack_speed",),
        ),
    },
    slot_wrappers={"P": _kings_tribute},
)

OPTIONS = list(OPTIONS) + [
    {
        "key": "p_nearby_deaths",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 10,
        "step": 1,
        "label": "Nearby enemy deaths during the fight (P King's Tribute)",
        "rotation": {
            "role": "self_state",
            "slot": "P",
            "note": (
                "King's Tribute pays on a nearby death, which no cast "
                "orders; the count is player state, not a rotation edge."
            ),
        },
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (King's Tribute) heals 1.8% : 5.94% (based on level) of the dying "
    "unit's maximum health per nearby enemy death — the cached P level "
    "row, which the wiki data mislabels 'Max Health Damage'. A duel "
    "simulates no wave, so p_nearby_deaths (default 0) supplies the count "
    "and the heals ride Trundle's first damaging hits; the dying unit is "
    "priced as the enemy champion this fight targets, so a minion death "
    "would be worth far less than the receipt states",
    "W (Frozen Domain) applies its 30-90% bonus attack speed for the "
    "whole fight; in-game the zone lasts 8 seconds and only buffs Trundle "
    "while he stands inside it. W's bonus movement speed and its 25% "
    "increased healing from all sources are not modeled",
    "E (Pillar of Ice) is terrain, a knockback and a 34-50% slow: the "
    "engine has no terrain axis, and cc_kind carries no duration or "
    "magnitude, so the slot prices nothing",
]

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "R"} else "out_of_scope")
    for slot in "PQWER"
}

SELF_HEALING_RULE = declare_healing_rule("Trundle")
