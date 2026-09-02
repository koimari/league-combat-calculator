"""The rule Yasuo and Yone share: the crit conversion and the Q3 whirlwind.

The cached P prose is verbatim Yasuo's for both ("total critical strike
chance is doubled ... every 1% ... converted into 0.5 bonus attack damage
... 90% of the critical damage champions usually have"); both champions
carry the champion stat criticalStrikeDamageModifier.flat = 0.9; the
binaries corroborate CritDamageMod 0.9 + CritToAD 50.0 (the x2 chance is
script-side).  The Q's degraded "Critical Strike Damage" rows (189% +
28.35% AD = 1.05 x 1.8 + 1.05 x 0.27; 198% + 29.7% AD = 1.1 x 1.8 + 1.1 x
0.27) are the display of this same converted system.
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import DAMAGE, SlotCtx, SlotParser
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_description_control_duration,
    extract_named,
    extract_value,
)

CRIT_CHANCE_MULTIPLIER = 2.0
CRIT_DAMAGE_MULTIPLIER_FACTOR = 0.9
EXCESS_CRIT_BONUS_AD_PER_PERCENT = 0.5


def crit_conversion_payload() -> dict[str, Any]:
    """The engine's crit_modifier payload for the shared conversion."""
    return {
        "crit_chance_multiplier": CRIT_CHANCE_MULTIPLIER,
        "crit_damage_multiplier_factor": CRIT_DAMAGE_MULTIPLIER_FACTOR,
        "excess_crit_bonus_ad_per_percent": EXCESS_CRIT_BONUS_AD_PER_PERCENT,
    }


def crit_conversion_certification(
    atom_hash: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(certified_constants, atom_ids) for the conversion rule.

    The 0.9 factor is the champion stat criticalStrikeDamageModifier.flat
    (the pinned atom hash varies per champion); the x2 chance + 0.5 AD
    per excess % are cached-P-prose + binary roots.  A patch that
    changes the roots trips the pinned hash (fail-closed staleness).
    """
    cert = dict(crit_conversion_payload())
    atoms = {
        "crit_damage_multiplier_factor": {
            "atom_id": "stats.critical_strike_damage_modifier.flat",
            "hash": atom_hash,
        },
    }
    return cert, atoms


# The Q3 knock-up has no cached leveling row: its only source is the
# "Gathering Storm Bonus" branch of the Q description, which is also the
# branch that states the empower exists at all.
Q3_KNOCKUP_BRANCH = "Gathering Storm Bonus"


def q3_knockup_duration(champion: str, ability: dict[str, Any]) -> float:
    """The Q3 whirlwind's knock-up, read off its own sourced branch."""
    for index, effect in enumerate(ability.get("effects") or []):
        if Q3_KNOCKUP_BRANCH not in str(effect.get("description") or ""):
            continue
        duration = extract_description_control_duration(ability, index)
        if duration:
            return float(duration)
        break
    raise ValueError(
        f"{champion} Q: the cached {Q3_KNOCKUP_BRANCH!r} branch states no "
        "knock-up duration, so the Q3 control fails closed rather than "
        "shipping an invented interval"
    )


def gathering_storm_thrust(champion: str) -> SlotParser:
    """Q: the thrust, empowered into the Q3 whirlwind at 2 Gathering Storm stacks.

    "[The] damage based on its AD ratio can critically strike" (cached Q
    description): the flat base never crits, so it is a plain part; the AD
    portion is a separate crit-eligible part using the crit chance and
    multiplier the engine resolves from P's crit_modifier.  Both parts are
    the one thrust — the split is crit eligibility, not a second hit — so
    the ledger sees ONE landing: the flat part carries the cast instant
    (and with it the control marker) and the AD part rides that event.

    The knock-up is a property of the branch, not of the slot, so it is
    authored here rather than in MODULE_CC: only the 2-stack cast is the
    whirlwind that knocks up, and that sentence is where its duration is
    read from.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ranked = ctx.ranked()
        if ranked is None:
            return None
        ability, rank = ranked
        stacks = min(max(int(ctx.option("q_gathering_storm")), 0), 2)
        damage = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
        entry = damage_entry(
            ability_name(ability),
            rank,
            extract_cooldown(ability, rank),
            damage,
            "physical",
        )
        flat = extract_value(ability, "Physical Damage", rank, 0)
        ad_ratio = extract_value(ability, "Physical Damage", rank, 1) / 100.0
        ad_part = ctx.stat("attack_damage") * ad_ratio
        knockup = q3_knockup_duration(champion, ability) if stacks >= 2 else 0.0
        entry["parts"] = (
            DamagePart(
                "physical",
                flat,
                time_offset=0.0,
                cc_kind="knockup" if stacks >= 2 else "none",
                cc_duration=knockup,
            ),
            DamagePart("physical", ad_part, crit_effectiveness=1.0),
        )
        if stacks >= 2:
            entry["detail"] = (
                "Gathering Storm at 2 stacks: this cast is the Q3 whirlwind — "
                f"same sourced damage as a normal thrust, adding a {knockup:g}s "
                "knock-up (crowd-control state, not damage)."
            )
        else:
            entry["detail"] = (
                f"Gathering Storm {stacks}/2 stacks; the Q3 whirlwind at 2 "
                "stacks deals the same sourced damage (the empower is the "
                "knock-up, a crowd-control state)."
            )
        return entry

    parse.phase = DAMAGE
    return parse
