"""Zeri — CP10.10 full-entry-reviewed packet module.

E5-2 fix — Spark Surge (E): the reviewed packet emitted the Lightning
Rounds per-round bonus ("Burst Fire Bonus Magic Damage" 22-30 + 20% AP)
as ONE flat magic hit and left the Lightning Rounds mechanic out of
scope.  The wiki prose (data/champions.json E): "Afterwards, she gains
Lightning Rounds for 5 seconds, empowering Burst Fire to deal bonus
magic damage to the first enemy hit, increased by 0% : 100% (+ 0% :
30%) (based on critical strike chance)".  Burst Fire fires 7 rounds
(the E2-sourced Total/per-round ratio on Q), so the E prices 7 rounds
of the per-round bonus, scaled linearly by crit chance between the two
sourced endpoints (x1 at 0% crit, x2.3 at 100% crit).  The dash itself
deals no damage.  Secondary targets ("Burst Fire Secondary Target
Damage" 80-100%) are outside this single-target model.
"""

from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import calculation_coefficient, data_value, spell_object
from .engine import ONHIT, SlotCtx
from .module_helpers import ranked_slot
from .packet_module import build_packet_module, repeat_damage_parser
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
)

# P4: Living Battery (execute range) — the uncharged zap's flat damage
# + the execute threshold.  The cached P effects[1] "Per-Level Scaling"
# [10..27.35] + "Bonus Damage" [70..170.59] rows are the DEGRADED
# half-parses (values survive, units empty — resolved as flat by the
# typed extractor); the 20% AP unit survived.  The +3% AP zap term is
# prose-only (the binary MinDamage coefficient 0.03).  The binary's
# PassiveExecuteThreshold 70.0->160.0 + coefficient 0.2 corroborates;
# the wiki L20 extension (170.59) is the repo convention.
_ZERI_Q_SPELL = spell_object("Zeri", "ZeriQ")
_ZAP_AP_RATIO = calculation_coefficient(_ZERI_Q_SPELL, "MinDamage")
_ZAP_EXECUTE_AP_RATIO = calculation_coefficient(
    _ZERI_Q_SPELL, "PassiveExecuteThreshold"
)


class _LivingBatteryExecuteRule:
    """The typed Living Battery execute-range rule (the Asol pattern).

    The threshold 70..170.59 + 20% AP roots in the DEGRADED wiki row
    ("Bonus Damage", effects[1] — values survive, units empty) with the
    binary PassiveExecuteThreshold 70.0->160.0 + coefficient 0.2 as the
    corroborating root; the atoms 9fa7c9206eb1e3c8 / 404ba4027bf78118
    pin the row (a drift trips the tests).
    """

    def public_receipt(self) -> dict[str, Any]:
        return {
            "name": "Living Battery execute range",
            "threshold_level_1": 70.0,
            "threshold_level_20": 170.59,
            "ap_ratio": _ZAP_EXECUTE_AP_RATIO,
            "zap_ap_ratio": _ZAP_AP_RATIO,
            "atom_ids": {
                "execute_threshold": {
                    "atom_id": "ability.bonus _damage.modifier_0",
                    "hash": "9fa7c9206eb1e3c8",
                },
                "execute_ap_ratio": {
                    "atom_id": "ability.bonus _damage.modifier_1",
                    "hash": "404ba4027bf78118",
                },
            },
            "source": {
                "wiki": {
                    "url": "https://wiki.leagueoflegends.com/en-us/Zeri",
                    "revision_id": 4019486,
                    "row": "data/champions.json P effects[1] 'Bonus Damage' "
                    "(degraded: values survive, units empty)",
                },
                "binary": (
                    "data/bin/characters/zeri.bin.json ZeriQ "
                    "PassiveExecuteThreshold 70.0->160.0 + coefficient 0.2"
                ),
            },
        }


ZERI_P_EXECUTE_RULE = _LivingBatteryExecuteRule()

PACKET_SHA256 = "f03ac495eb30baef9672e60deb2f448b0da551e22e39c3113cbc0cfee9e1c055"

# Burst Fire fires 7 rounds (Total Physical Damage / per-hit on Q, locked
# by tests/test_e2_dot_3.py) "in the target direction over the cast time",
# and the cached Q entry carries no castTime of its own ("Burst Fire's
# cooldown and cast time are reduced with attack speed"), so the burst is
# authored at the cast with no interval between rounds.  E's Lightning
# Rounds bonus rides these same seven rounds, so both slots read the
# placement from here — a rider on Burst Fire cannot land anywhere else.
_BURST_ROUNDS = int(data_value(_ZERI_Q_SPELL, "NumberOfMissiles"))
_BURST_ROUND_TIME_OFFSET = 0.0
_BURST_ROUND_INTERVAL = 0.0


# Lightning Rounds empowers each round's first-enemy hit.
_E_LIGHTNING_ROUNDS_ROUNDS = _BURST_ROUNDS
# Lightning Rounds bonus "increased by 0% : 100% (+ 0% : 30%) (based on
# critical strike chance)": x2.3 at 100% crit -> 1 + 1.3 x crit_chance.
_E_BONUS_CRIT_MULTIPLIER_AT_MAX = 2.3


def _living_battery(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Living Battery — the uncharged zap + the execute range.

    The uncharged zap is per-auto magic damage (the cached "Per-Level
    Scaling" 10..27.35 + 3% AP — the degraded row resolved as flat),
    priced via the engine's on-hit payload.  The EXECUTE: the target
    dies when its current health falls at-or-below the threshold 70..
    170.59 + 20% AP (the "Bonus Damage" degraded row + the 20% AP unit;
    the binary PassiveExecuteThreshold 70.0->160.0 + coefficient 0.2).
    The engine's ratio seam hosts it as threshold/target_max_health
    (parse-time, fail-closed when the target max health is missing or
    <=0 — the ratio is omitted, never a division by zero).  The engine
    evaluates AFTER the zap's own damage (the zap counts toward the
    crossing) with the inclusive <= boundary; the wiki's "below" is the
    script-side operator (documented).  The full-charge attack, the
    charge mechanic, and the shielded/invulnerable exclusion are named
    out-of-scope boundaries (the engine's applied_to_health gate covers
    fully-absorbed hits).
    """
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
    rank = ctx.level
    zap_flat = extract_named(ability, "Per-Level Scaling", rank, ctx.stats, ctx.target)
    ap = ctx.stat("ability_power")
    zap = zap_flat + _ZAP_AP_RATIO * ap
    # extract_named already resolves the "% AP" modifier (the 20% AP
    # unit survived the degraded parse); _ZAP_EXECUTE_AP_RATIO is the
    # receipt constant, never added twice.
    threshold = extract_named(ability, "Bonus Damage", rank, ctx.stats, ctx.target)
    target_max = ctx.target_stat("target_max_health")
    entry = on_hit_entry(ability_name(ability), zap, "magic")
    if target_max > 0.0:
        entry["execute_threshold_ratio"] = threshold / target_max
        entry["execute_source"] = "Living Battery"
    entry["certified_constants"] = {
        "zap_ap_ratio": _ZAP_AP_RATIO,
        "execute_ap_ratio": _ZAP_EXECUTE_AP_RATIO,
        "threshold_level_1": 70.0,
        "threshold_level_20": 170.59,
    }
    entry["atom_ids"] = {
        "execute_threshold": {
            "atom_id": "ability.bonus _damage.modifier_0",
            "hash": "9fa7c9206eb1e3c8",
        },
        "execute_ap_ratio": {
            "atom_id": "ability.bonus _damage.modifier_1",
            "hash": "404ba4027bf78118",
        },
    }
    entry["detail"] = (
        f"Uncharged zap {zap:.2f} magic per auto; Executes below "
        f"{threshold:.0f} HP (+20% AP) — the full-charge attack, charge "
        f"generation, and the shielded/invulnerable exclusion are named "
        f"out-of-scope boundaries (sources: the cached P degraded rows + "
        f"the binary PassiveExecuteThreshold)"
    )
    return entry


_living_battery.phase = ONHIT


@ranked_slot
def _spark_surge(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """E: the dash plus 7 Lightning-Rounds-empowered Burst Fire rounds."""
    per_round = extract_named(
        ability, "Burst Fire Bonus Magic Damage", rank, ctx.stats, ctx.target
    )
    crit_chance = min(max(float(ctx.stat("critical_strike_chance")) / 100.0, 0.0), 1.0)
    multiplier = 1.0 + (_E_BONUS_CRIT_MULTIPLIER_AT_MAX - 1.0) * crit_chance
    per_round *= multiplier
    total = per_round * _E_LIGHTNING_ROUNDS_ROUNDS
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
            amount=per_round,
            count=_E_LIGHTNING_ROUNDS_ROUNDS,
            time_offset=_BURST_ROUND_TIME_OFFSET,
            hit_interval=_BURST_ROUND_INTERVAL,
        ),
    )
    entry["detail"] = (
        f"{_E_LIGHTNING_ROUNDS_ROUNDS} Burst Fire rounds x {per_round:g} "
        f"bonus magic damage (crit multiplier {multiplier:.3f})"
    )
    return entry


# Ultrashock Laser's pulse "deals physical damage to the first enemy hit
# and slows them for 2 seconds".  Burst Fire's rounds and Lightning Crash's
# nova only damage — the nova empowers Zeri (Overcharged), not the enemies
# it hits.  Spark Surge's dash and its Lightning Rounds bonus control
# nothing either: the buff "empower[s] Burst Fire to deal bonus magic
# damage to the first enemy hit ... and pierce through enemies".  P is
# absent: Living Battery rides the basic-attack stream as an on-hit
# rider, not an ability event the ledger reviews.
MODULE_CC = {"Q": "none", "W": "slow", "E": "none", "R": "none", "P": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Zeri",
    PACKET_SHA256,
    assumption_overrides=(
        "Burst Fire prices all 7 rounds (Physical Damage per Hit x 7 == "
        "Total Physical Damage).",
    ),
    # W's pulse and R's nova are one hit each at the cast; neither packet
    # carries a travel or tick phase to place.
    single_hit_slots=frozenset({"W", "R"}),
    slot_parsers={
        "P": _living_battery,
        "Q": repeat_damage_parser(
            attr="Physical Damage per Hit",
            dmg_type="physical",
            count=_BURST_ROUNDS,
            time_offset=_BURST_ROUND_TIME_OFFSET,
            hit_interval=_BURST_ROUND_INTERVAL,
        ),
        "E": _spark_surge,
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "E (Spark Surge) prices the dash plus Lightning Rounds: 7 Burst "
    "Fire rounds x the wiki's 'Burst Fire Bonus Magic Damage' row "
    "(22-30 + 20% AP, data/champions.json E), the E2-sourced round "
    "count on Q.",
    "Lightning Rounds bonus damage is 'increased by 0% : 100% (+ 0% : "
    "30%) (based on critical strike chance)'; the module scales "
    "linearly with crit chance, exact at the sourced 0%/100% endpoints.",
    "The dash itself deals no damage; 'Burst Fire Secondary Target "
    "Damage' (80-100%) applies to enemies past the first and is outside "
    "this single-target model.",
]
