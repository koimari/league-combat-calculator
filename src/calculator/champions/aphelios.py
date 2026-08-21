"""Aphelios' reviewed weapon-aware damage module.

The weapon choice is explicit input, never inferred from a marksman
archetype.  Q's Onslaught is represented as an attack event whose count is
the Wiki's ``6 + 2 per 100% bonus attack speed`` rule; the other weapon Q
forms use the pinned packet variants.  R's initial blast and the basic-attack
follow-up are kept separate so resistance and event ordering remain visible.

E (Weapon Queue System) is the one slot with no damage row, and it emits
that zero rather than staying absent: ``data/champions.json`` Aphelios E
carries ``damageType: None`` and both effect rows carry an empty
``leveling`` list — a pure UI affordance ("The icon of this ability
reflects the next weapon that is in reserve" / "Active: Aphelios receives
a text prompt of the weapon Alune will create next"), with no cast, no
cooldown and no HP number anywhere.  The pinned packet already compiles it
as a ``no_damage`` slot, so ``slot_order`` carries it instead of the module
re-authoring the same zero.

``MODULE_CC`` names Q and R ``CC_PER_PART``: both are one slot per weapon
and the weapons do not control alike, so the kind rides the part each
weapon form builds (``_Q_CC_BY_WEAPON``, ``_R_CC_BY_WEAPON``).
"""

from dataclasses import replace
from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from .inputs import champion_stat
from .engine import BUFF, CC_PER_PART, SlotCtx
from .healing_contract import declare_healing_rule
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown

PACKET_SHA256 = "8a0a5d9fa966d29c754a5e4bc8ca56d541a843bb2af95c3266438556aebf499c"


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


def _q(packet_q):

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
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
                result = packet_q(ctx)
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

    return parse


# HARDCODED: verify on patch updates — the Moonlight Vigil follow-up
# prose (cached R effect[1]): "attacks based on Aphelios' current main
# weapon will launch from the sky against each locked-on target,
# dealing 100% AD physical damage and applying on-hit effects. These
# attacks can critically strike for 100% : 130% (+ 0% : 9%) (based on
# critical strike chance)".  The follow-up crit DAMAGE ramps with crit
# chance (100% at 0% crit to 130% at 100%, plus 0-9%), so the expected
# multiplier is 1 + (0.30 + 0.09) x crit^2 — the attacks are basic
# attacks, not spells, but their crits are far weaker than the 200%
# normal attacks use.
_R_FOLLOWUP_CRIT_EXTRA = 0.30  # 100% : 130% ramp by crit chance
_R_FOLLOWUP_CRIT_CHANCE_BONUS = 0.09  # (+ 0% : 9%) by crit chance
_R_FOLLOWUP_DELAY = 0.3  # "After 0.3 seconds of the illumination"


def _r_followup_expected_crit(ctx: SlotCtx) -> float:
    """Expected crit multiplier of one follow-up attack at this build.

    The sourced crit ("100% : 130% (+ 0% : 9%) based on critical strike
    chance") is an expected value (the Caitlyn Headshot convention):
    P(crit) = crit, crit damage = 1 + 0.39 x crit, so E = 1 + 0.39 x
    crit^2.
    """
    crit = min(max(ctx.stat("critical_strike_chance") / 100.0, 0.0), 1.0)
    return 1.0 + (_R_FOLLOWUP_CRIT_EXTRA + _R_FOLLOWUP_CRIT_CHANCE_BONUS) * (
        crit * crit
    )


def _r_followup_part(ctx: SlotCtx, followups: int) -> tuple[DamagePart, float]:
    """One follow-up part: 100% AD per locked-on target, special crit.

    Returns ``(part, total)`` for the selected follow-up count.  Every
    locked-on target is struck at the same instant, one illumination
    after the blast, so the repeated part authors a zero interval rather
    than a cadence it does not have.  The blast's own weapon control does
    not ride these attacks — they are basic attacks from the sky — which
    is what the reviewed ``"none"`` on the part states.
    """
    per_followup = ctx.stat("attack_damage") * _r_followup_expected_crit(ctx)
    return (
        DamagePart(
            "physical",
            amount=per_followup,
            count=followups,
            time_offset=_R_FOLLOWUP_DELAY,
            hit_interval=0.0,
            basic_damage=True,
            cc_kind="none",
        ),
        per_followup * followups,
    )


def _r(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("R")
    if not ability:
        return None
    r_rank = 1 if ctx.level < 11 else (2 if ctx.level < 16 else 3)
    base = (125.0, 175.0, 225.0)[r_rank - 1]
    ad = float(ctx.stat("bonus_attack_damage"))
    ap = float(ctx.stat("ability_power"))
    initial = base + 0.20 * ad + ap
    total = initial
    followups = min(max(int(ctx.option("r_followup_targets")), 0), 5)
    blast = DamagePart(
        "physical",
        amount=initial,
        cc_kind=_R_CC_BY_WEAPON[_main_weapon(ctx)],
        # The blast lands at the cast boundary.  With no follow-up it is
        # the row's only part and says so through the certification below;
        # beside a follow-up it authors the instant itself, because the two
        # parts then sit at different instants and the row is a schedule.
        time_offset=0.0 if followups else None,
    )
    parts = [blast]
    if followups:
        followup_part, followup_total = _r_followup_part(ctx, followups)
        parts.append(followup_part)
        total += followup_total
    # The cache carries no leveling row for Moonlight Vigil, so its bases stay
    # reviewed constants — but the cooldown row is there, and it falls by rank.
    entry = damage_entry(
        ability["name"],
        r_rank,
        extract_cooldown(ability, r_rank),
        total,
        "physical",
    )
    entry["parts"] = tuple(parts)
    detail = f"Moonlight Vigil initial blast · {_WEAPON_LABELS[_main_weapon(ctx)]}"
    if followups:
        detail += (
            f" + {followups} locked-on target follow-up attack(s) at 100% AD "
            f"(expected crit {_r_followup_expected_crit(ctx):.3f}x)"
        )
        entry["applies_item_on_hits"] = {
            "effectiveness": 1.0,
            "hits": followups,
            "triggers": ("on_hit",),
        }
    else:
        # One blast, priced once: the cast boundary is the hit.
        entry["event_order_certified"] = "single_hit"
        detail += " follow-up is event-ordered separately"
    # The healing rule reads this marker to gate Severum's overheal-to-
    # shield conversion (the Shyvana dragon-form convention).
    if _main_weapon(ctx) == "severum" and bool(
        ctx.options.get("aphelios_overheal_shield", True)
    ):
        detail += " · overheal shield on"
    entry["detail"] = detail
    return entry


# Reviewed crowd control, read from the cached kit.  Q and R are one slot
# per weapon and the weapons do not control alike, so both answer per part
# (``_Q_CC_BY_WEAPON``, ``_R_CC_BY_WEAPON``).  P is the Weapon Master
# skill-point innate (bonus AD/AS/lethality), W "swap[s] main and off-hand
# weapons" and E is the queue prompt: all three touch no enemy.  P and W
# are read and left undeclared all the same — each prices an untimed zero
# part the event ledger cannot carry a kind for, while E's row has no part
# at all.
MODULE_CC = {"Q": CC_PER_PART, "E": "none", "R": CC_PER_PART}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Aphelios",
    PACKET_SHA256,
    assumption_overrides=(
        "The main weapon and Weapon Master skill-point allocation are explicit scenario inputs.",
        "Onslaught applies wiki-sourced item on-hits at 25% per attack; Duskwave (calibrum Q) at "
        "100%.",
        "Moonlight Vigil models the sourced initial blast; with r_followup_targets (default 0) "
        "selected, each locked-on champion also takes one follow-up attack from the sky: 100% AD "
        "physical basic damage applying on-hit effects at 100% (cached R prose), with the sourced "
        "special crit — 'critically strike for 100% : 130% (+ 0% : 9%) (based on critical strike "
        "chance)' — baked in as an expected-value multiplier 1 + 0.39 x crit^2 (the follow-up "
        "crits are far weaker than the 200% normal attacks use).",
        "Severum's excess healing converts into a shield capped at the sourced per-level 'Heal' "
        "row (10 : 160 by level + 6% maximum health) that lingers for up to 30 seconds (wiki P "
        "prose); with aphelios_overheal_shield (default True) the healing rule stamps each Severum "
        "heal with the sourced cap and duration, and the participant timeline converts "
        "heal-in-excess-of-maximum-health into a timed shield at the heal's timestamp.",
        "E (Weapon Queue System) carries no enemy-damage attribute (data/champions.json "
        "Aphelios E has damageType: None and an empty leveling list on both effect rows); "
        "the pinned packet's no_damage slot is the row it emits.",
    ),
    slot_parsers={
        "P": _weapon_master,
        "W": _phase,
        "R": _r,
    },
    slot_wrappers={
        "Q": _q,
    },
    slot_order=("P", "W", "Q", "R", "E"),
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    {
        "key": "r_followup_targets",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 5,
        "label": (
            "Locked-on targets hit by Moonlight Vigil follow-up attacks "
            "(each takes one 100% AD main-weapon attack with on-hits)"
        ),
        "rotation": {"role": "irrelevant", "slot": "R"},
    },
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

# The Weapon Queue System has nothing to price — it is the prompt that
# reorders the next weapons, with no gameplay effect of its own — so the
# packet's own no_damage row is what E emits, and the slot is no_damage
# rather than an axis the engine is missing.
MODULE_COVERAGE = {
    "P": "modeled",
    "Q": "modeled",
    "W": "modeled",
    "E": "no_damage",
    "R": "modeled",
}


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Aphelios self-healing events from its authored packet."""
    healing = []
    r_detail = str(ability_damages.get("R", {}).get("detail", ""))
    if "Severum" in r_detail:
        severum = next(
            (
                entry
                for entry in champion_data.get("abilities", {}).get("P", [])
                if isinstance(entry, dict) and entry.get("name") == "Severum"
            ),
            {},
        )
        level = int(champion_stat(champion_stats, "level"))
        basic_scaling = _healing.find_named_leveling(severum, "Per-Level Scaling", 0)
        ability_scaling = _healing.find_named_leveling(severum, "Per-Level Scaling", 1)
        basic_ratio = (
            _healing.sum_modifiers(basic_scaling, level, champion_stats, {}) / 100.0
            if basic_scaling is not None
            else 0.0
        )
        ability_ratio = (
            _healing.sum_modifiers(ability_scaling, level, champion_stats, {}) / 100.0
            if ability_scaling is not None
            else 0.0
        )
        # Severum's wiki passive converts excess healing into a shield
        # capped at the per-level "Heal" row (10 : 160 by level + 6%
        # maximum health), lingering for up to 30 seconds.  In the
        # fight's deterministic state the conversion is driven by the
        # survival walk: each heal event carries the sourced cap and
        # duration, and the participant timeline converts the excess
        # (heal in excess of the fighter's maximum health, i.e. all of
        # it while at full health) into a timed shield (the
        # ``_apply_overheal_shield`` receipt).
        heal_leveling = _healing.find_named_leveling(severum, "Heal")
        shield_cap = (
            _healing.sum_modifiers(heal_leveling, level, champion_stats, {})
            if heal_leveling is not None
            else 0.0
        )
        # The module stamps the option state on Moonlight Vigil's
        # detail (the Shyvana dragon-form convention): "overheal shield
        # on" when the user enabled the conversion (default on).
        overheal_shield = "overheal shield on" in r_detail
        # Severum pays per hit, and per hit is what it says: "Severum's
        # attacks heal Aphelios for 2% : 7.1% (based on level) of the
        # post-mitigation damage dealt".  An attack that dealt nothing heals
        # nothing, and Onslaught's six attacks are six payments of their own
        # shares, not six copies of one.
        for payment in _healing._payments(
            _healing.HealAnchor.DAMAGING_HIT,
            lambda source: source in {"auto_attacks", "Q"},
            damage_events,
        ):
            event = payment.event
            # With Severum equipped the Q row is Onslaught, whose attacks
            # count as ability attacks for the heal.
            ratio = (
                basic_ratio
                if _healing._event_source(event) == "auto_attacks"
                else ability_ratio
            )
            amount = max(0.0, float(event.get("damage", 0.0))) * ratio
            _healing._heal_from_damage(healing, event, amount, "Severum")
            if overheal_shield and amount > 0.0 and shield_cap > 0.0:
                healing[-1]["overheal_to_shield"] = True
                healing[-1]["overheal_shield_cap"] = shield_cap
                healing[-1]["overheal_shield_duration"] = 30.0
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


SELF_HEALING_RULE = declare_healing_rule("Aphelios", derive_self_healing)
