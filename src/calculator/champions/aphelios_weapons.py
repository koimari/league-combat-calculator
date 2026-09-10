"""Which of the five weapons is in hand, what each adds on hit, and the Weapon Master points."""

from typing import Any

from ..binary_roots import calculation_coefficient, data_value, spell_object
from .engine import BUFF, SlotCtx
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_value

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
#                 Absent from the map: see _Q_ONSLAUGHT_SECONDS.
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


# R's blast controls only under Gravitum, which "Increases the initial slow
# to 99%"; every other weapon's follow-up is a mark, a heal, bonus damage
# or extra chakrams.
_R_CC_BY_WEAPON = dict.fromkeys(_WEAPON_INDEX, "none") | {"gravitum": "slow"}


def _main_weapon(ctx: SlotCtx) -> str:
    value = str(ctx.option("aphelios_main_weapon")).lower()
    return value if value in _WEAPON_INDEX else "calibrum"


# HARDCODED: verify on patch updates.  Both weapon innates below state their
# damage in prose over an empty ``leveling`` list, so the numbers are
# reviewed constants and ``tests/test_aphelios.py`` pins the cached sentence
# each one is read from:
#   Calibrum  "dealing 15 (+ 15% bonus AD) bonus physical damage to the main
#             target for each mark consumed"
#   Infernum  "The fire bolt deals 110% AD physical damage to the primary
#             target" — ten points above the 100% AD the basic attack
#             already deals, so the branch prices the difference on the same
#             swing, at the crit effectiveness a basic attack has.
_CALIBRUM_MARK_FLAT = 15.0


_APHELIOS_CALIBRUM_Q_SPELL = spell_object("Aphelios", "ApheliosCalibrumQ")


_CALIBRUM_MARK_BONUS_AD_RATIO = calculation_coefficient(
    _APHELIOS_CALIBRUM_Q_SPELL, "BonusDamagePerMark"
)


_INFERNUM_PRIMARY_AD_RATIO = data_value(
    spell_object("Aphelios", "ApheliosInfernumQ"), "InfernumDamageMultiplier"
)


# The three weapon branches that price no damage row of their own, and why.
_P_BRANCH_UNPRICED = {
    "severum": (
        "attacks heal, and the heal is priced by this module's healing rule "
        "off the cached Per-Level Scaling rows rather than as damage"
    ),
    "gravitum": (
        "attacks slow and deal no damage of their own; an auto-carried slow "
        "is not ability control (the Ashe Frost Shot reading)"
    ),
    "crescendum": (
        "UNPRICED — the cached Chakram effect states '0% : 138.5% (based on "
        "number of Chakrams) AD additional physical damage' in prose with an "
        "empty leveling list, so no per-Chakram row exists to price"
    ),
}


def _weapon_branch(ctx: SlotCtx, weapon: str) -> tuple[dict[str, Any] | None, str]:
    """The main weapon's innate: its on-hit row, and what the branch says.

    Only Calibrum and Infernum put damage on the basic-attack channel; the
    other three declare their reviewed reason and price nothing.
    """
    if weapon == "calibrum":
        marks = max(int(ctx.option("aphelios_calibrum_marks")), 0)
        if not marks:
            return None, "no marks consumed, so the empowered attack is a plain one"
        per_mark = _CALIBRUM_MARK_FLAT + _CALIBRUM_MARK_BONUS_AD_RATIO * ctx.stat(
            "bonus_attack_damage"
        )
        return (
            {
                "name": "Calibrum mark (on-hit)",
                "damage_per_hit": per_mark * marks,
                "damage_type": "physical",
                # "The empowered attack will consume the marks from ALL
                # targets" — one attack spends the lot, so the row lands once.
                "max_procs": 1,
            },
            f"one empowered attack consumes {marks} mark(s) at {per_mark:.1f} each",
        )
    if weapon == "infernum":
        return (
            {
                "name": "Infernum (on-hit)",
                "damage_per_hit": (_INFERNUM_PRIMARY_AD_RATIO - 1.0)
                * ctx.stat("attack_damage"),
                "damage_type": "physical",
                # The bolt IS the basic attack, so it crits when the attack
                # does: "Critical strikes instead spray 6 missiles".
                "crit_effectiveness": 1.0,
            },
            f"every attack deals {_INFERNUM_PRIMARY_AD_RATIO:.0%} AD to the "
            "primary target (the cone's secondary targets need a roster and "
            "stay unpriced)",
        )
    return None, _P_BRANCH_UNPRICED[weapon]


def _weapon_master_grant(ability: dict[str, Any], attribute: str, points: int) -> float:
    """One cached Weapon Master row at the points spent; none spent, none granted."""
    return extract_value(ability, attribute, points) if points >= 1 else 0.0


def _weapon_master(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("P")
    if not ability:
        return None
    ad_points = max(int(ctx.option("aphelios_bonus_ad_points")), 0)
    as_points = max(int(ctx.option("aphelios_bonus_as_points")), 0)
    lethality_points = max(int(ctx.option("aphelios_lethality_points")), 0)
    entry = damage_entry(ability_name(ability), 1, 0.0, 0.0, "physical")
    bonus_ad = _weapon_master_grant(ability, "Bonus Attack Damage", ad_points)
    bonus_as = _weapon_master_grant(ability, "Bonus Attack Speed", as_points)
    lethality = _weapon_master_grant(ability, "Lethality", lethality_points)
    if bonus_ad:
        ctx.stats["attack_damage"] = ctx.stat("attack_damage") + bonus_ad
        ctx.stats["bonus_attack_damage"] = ctx.stat("bonus_attack_damage") + bonus_ad
    if bonus_as:
        ctx.stats["bonus_attack_speed"] = ctx.stat("bonus_attack_speed") + bonus_as
        ctx.stats["attack_speed"] = (
            ctx.stat("attack_speed") + ctx.stat("attack_speed_ratio") * bonus_as / 100.0
        )
    if lethality:
        ctx.stats["lethality"] = ctx.stat("lethality") + lethality
    entry["stat_buff"] = {
        "bonus_attack_damage": bonus_ad,
        "bonus_attack_speed": bonus_as,
    }
    # The branch reads the stats the buff above has already moved, because
    # Calibrum's mark scales with the bonus AD Weapon Master just granted.
    weapon = _main_weapon(ctx)
    on_hit, branch_detail = _weapon_branch(ctx, weapon)
    if on_hit is not None:
        entry["on_hit"] = on_hit
    entry["detail"] = (
        f"Weapon Master: {ad_points} AD / {as_points} AS / {lethality_points} "
        f"lethality points · {_WEAPON_LABELS[weapon]}: {branch_detail}"
    )
    return entry


_weapon_master.phase = BUFF
