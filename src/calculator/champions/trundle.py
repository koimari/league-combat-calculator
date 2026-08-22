"""Trundle — CP10.8 full-entry-reviewed packet module.

P (King's Tribute) heals "1.8% : 5.94% (based on level) of their maximum
health" whenever a nearby enemy dies (cached P prose; the level row is
mislabelled ``Max Health Damage``).  A duel simulates no wave and no
takedown, so the count is the ``p_nearby_deaths`` option and the P row
carries the sourced per-death amount for the self-heal rule to place.

W (Frozen Domain) is the kit's attack-speed steroid — the compiled
no-damage row is replaced by the shared ``stat_buff`` slot so the cached
"Bonus Attack Speed" row reaches the auto stream.

E (Pillar of Ice) is a ``no_damage`` slot: its 34-50% slow rides a
control event with the cached duration and magnitude, while the terrain
and the creation knockback have no engine axis.
"""

from typing import Any

from ..ability_atoms import ability_payload
from .. import healing_helpers as _healing
from .engine import SlotCtx
from .healing_contract import self_healing_rule
from .packet_module import build_packet_module, repeat_damage_parser
from .slotlib import extract_value, stat_buff, with_control_event
from .inputs import float_option, int_option
from .module_contract import coverage

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
MODULE_CC = {"Q": "slow", "E": "slow", "R": "none"}

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
        # it instead of the packet's no-damage placeholder.  The zone is
        # ground Trundle has to stand on, so the steroid carries the
        # uptime option rather than assuming the whole window.
        "W": stat_buff(
            attr="Bonus Attack Speed",
            stat="bonus_attack_speed",
            apply_to=("bonus_attack_speed",),
            uptime_option="w_zone_uptime",
        ),
    },
    slot_wrappers={
        "P": _kings_tribute,
        # Pillar of Ice prices no damage; it "acts as terrain and slows
        # nearby enemies" for the pillar's own 6-second window, which is
        # the slot's active-duration atom, and the cached "Slow" row
        # (34/38/42/46/50%) is how hard.  The creation knockback carries
        # no sourced duration anywhere and stays unpriced.
        "E": lambda parser: with_control_event(
            parser,
            duration_source="active",
            magnitude_attr="Slow",
        ),
    },
)

OPTIONS = list(OPTIONS) + [
    float_option(
        "w_zone_uptime",
        1.0,
        minimum=0.0,
        maximum=1.0,
        label="Fraction of the fight Trundle stands in W's Frozen Domain",
        step=0.1,
        rotation={
            "role": "self_state",
            "slot": "W",
            "note": (
                "Frozen Domain is ground, not a self-buff: standing on it "
                "is player state no cast order can express."
            ),
        },
    ),
    int_option(
        "p_nearby_deaths",
        0,
        minimum=0,
        maximum=10,
        label="Nearby enemy deaths during the fight (P King's Tribute)",
        step=1,
        rotation={
            "role": "self_state",
            "slot": "P",
            "note": (
                "King's Tribute pays on a nearby death, which no cast "
                "orders; the count is player state, not a rotation edge."
            ),
        },
    ),
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (King's Tribute) heals 1.8% : 5.94% (based on level) of the dying "
    "unit's maximum health per nearby enemy death — the cached P level "
    "row, which the wiki data mislabels 'Max Health Damage'. A duel "
    "simulates no wave, so p_nearby_deaths (default 0) supplies the count "
    "and the heals ride Trundle's first damaging hits; the dying unit is "
    "priced as the enemy champion this fight targets, so a minion death "
    "would be worth far less than the receipt states",
    "W (Frozen Domain) is ground, not a self-buff: its 30-90% bonus attack "
    "speed only applies while Trundle stands inside the zone, so "
    "w_zone_uptime (default 1.0 — the whole window, which an 8-second zone "
    "on a recastable cooldown can cover) scales the granted percentage. "
    "Attack speed is linear in the bonus percent, so a scaled grant is the "
    "exact fight average rather than an approximation. W's bonus movement "
    "speed and its 25% increased healing from all sources are not modeled",
    "E (Pillar of Ice) is terrain, a knockback and a 34-50% slow: the "
    "slow is priced as a control event with its cached duration and "
    "magnitude, while the terrain and knockback have no engine axis",
]

MODULE_COVERAGE = coverage(no_damage="E")


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Trundle self-healing events from its authored packet."""
    healing = []
    # Subjugate drains the target, "dealing magic damage and healing himself
    # for the same amount" (wiki R effect[0]); Total Healing and Total Magic
    # Damage share the same % of the target's maximum health leveling values.
    # The engine's R event carries the drain's pre-mitigation damage, which is
    # exactly the heal amount — the heal does not pass through magic resistance.
    for event in _healing.attributed_events(
        damage_events, lambda source, _event: source == "R"
    ):
        dealt = float(event.get("raw_damage", event.get("damage", 0.0)) or 0.0)
        _healing.heal_from_damage(
            healing, event, dealt, "Subjugate", link_to_damage=False
        )
    # King's Tribute (P): "Whenever a nearby enemy dies, Trundle heals himself
    # for 1.8% : 5.94% (based on level) of their maximum health."  The module
    # priced the per-death amount against the enemy this fight targets and
    # carried it on the P row with the user's declared death count.  A heal a
    # takedown pays has neither a cast nor a damage row, so each death rides
    # one of the fight's first damaging hits, in order.
    tribute = ability_payload(ability_damages, "passive").get("self_heal_state")
    if isinstance(tribute, dict):
        amount = float(tribute.get("amount", 0.0) or 0.0)
        for payment in _healing.takedown_payments(
            int(tribute.get("deaths", 0) or 0), damage_events
        ):
            healing.append(
                {
                    "time": float(payment.event.get("time", 0.0)),
                    "amount": amount,
                    "source": "King's Tribute",
                    "kind": "champion_passive",
                    "actor_wide": True,
                    **_healing.trigger_fields(payment.event),
                }
            )
    return healing


SELF_HEALING_RULE = self_healing_rule("Trundle")(derive_self_healing)
