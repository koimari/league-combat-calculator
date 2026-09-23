"""Aphelios: reviewed weapon-aware damage module.

``aphelios_main_weapon`` is the form axis, the way Kayn's form and Jayce's
stance are theirs: P, Q and R each branch on it, and the weapon is explicit
input, never inferred from an archetype.  Q's Onslaught is an attack event whose
count is the wiki's 6 plus 2 per 100% bonus attack speed; R's initial blast and
its basic-attack follow-up stay separate so resistance and event order remain
visible.
P holds each weapon's innate and the five branches are not alike.  Calibrum's
mark bonus and Infernum's 110%-AD attack are priced on the basic-attack channel,
Severum's heal by this module's healing rule, and Gravitum's innate is a slow
that damages nothing.  Crescendum's is the one the cache cannot support: it
states a 0 to 138.5% range by Chakram count in prose over an empty ``leveling``
list, so the branch stays unpriced rather than inventing the curve.
E (Weapon Queue System) is the one slot with no damage row, a pure interface
affordance with ``damageType: None`` and empty leveling, compiled by the pinned
packet as ``no_damage``.
``MODULE_CC`` names Q and R ``CC_PER_PART``: each is one slot per weapon and the
weapons do not control alike, so the kind rides the part each form builds.
"""

from dataclasses import replace
from typing import Any

from .. import healing_helpers as _healing
from ..ability_atoms import ability_field, ability_payload
from ..ability_prose import extract_description_duration
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from ..damage_event_row import event_damage as _row_damage
from .aphelios_weapons import (
    _Q_CC_BY_WEAPON,
    _R_CC_BY_WEAPON,
    _WEAPON_INDEX,
    _WEAPON_LABELS,
    OPTION_KEYS,
    _main_weapon,
    _weapon_master,
)
from .contract_vocabulary import coverage
from .engine import SlotCtx
from .healing_contract import SelfHealCtx, self_healing_rule
from .inputs import bool_option, champion_stat, int_option
from .packet_module import build_packet_module
from .slot_cc import CC_PER_PART
from .slot_entries import damage_entry
from .slot_extract import (
    ability_name,
    extract_cooldown,
    find_named_leveling,
    sum_modifiers,
)

PACKET_SHA256 = "8a0a5d9fa966d29c754a5e4bc8ca56d541a843bb2af95c3266438556aebf499c"


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
_Q_ONSLAUGHT_SECONDS = data_value(
    spell_object("Aphelios", "ApheliosSeverumQ"), "Duration"
)


def _phase(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the weapon swap, with each of its two numbers in its own home.

    Phase has a cached cooldown (0.8 s) and a cached swap duration ("switches
    between his main weapon and off-hand weapon over 0.25 seconds"); both are
    read here, and neither stands in for the other.  The swap itself is state
    the module holds fixed — ``aphelios_main_weapon`` is the weapon for the
    whole fight — so W's row has no weapon branch to price.
    """
    ability = ctx.ability("W")
    if not ability:
        return None
    swap_seconds = extract_description_duration(ability)
    if swap_seconds is None:
        raise ValueError(
            "Aphelios W: the cached Phase description states no swap "
            "duration, so the row has no sourced number to publish"
        )
    entry = damage_entry(
        ability_name(ability), 1, extract_cooldown(ability, 1), 0.0, "physical"
    )
    entry["detail"] = (
        f"Swap main and off-hand weapons over {swap_seconds:g} s; the fight "
        f"holds one main weapon ({_WEAPON_LABELS[_main_weapon(ctx)]})"
    )
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
                if result is not None and weapon == "infernum":
                    # Duskwave is Infernum's Q, and it is the weapon Q that
                    # applies on-hits: "Aphelios then fires a volley of
                    # attacks at each locked-on target from his current
                    # off-hand weapon ... and applying on-hit effects" (the
                    # volley's own 100% AD needs the off-hand weapon and
                    # stays unpriced).  data/onhit-matrix.json says the same.
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
            ability_name(ability),
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
_R_FOLLOWUP_CRIT_EXTRA = data_value(
    spell_object("Aphelios", "ApheliosR"), "CritDamageMod"
)  # 100% : 130% ramp by crit chance
_R_FOLLOWUP_CRIT_CHANCE_BONUS = 0.09  # (+ 0% : 9%) by crit chance
_R_FOLLOWUP_DELAY = 0.3  # "After 0.3 seconds of the illumination"


def _r_followup_expected_crit(ctx: SlotCtx) -> float:
    """Expected crit multiplier of one follow-up attack at this build."""
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
    if _main_weapon(ctx) == "severum" and bool(ctx.option("aphelios_overheal_shield")):
        detail += " · overheal shield on"
    entry["detail"] = detail
    return entry


# Reviewed crowd control, read from the cached kit.  Q and R are one slot
# per weapon and the weapons do not control alike, so both answer per part
# (``_Q_CC_BY_WEAPON``, ``_R_CC_BY_WEAPON``).  P is the Weapon Master
# skill-point innate plus the main weapon's branch, W "swap[s] main and
# off-hand weapons" and E is the queue prompt.  P and W are read and left
# undeclared all the same — each prices an untimed zero part the event
# ledger cannot carry a kind for, and P's weapon branch rides the on-hit
# channel, which carries no kind either (Gravitum's slow: see
# ``_P_BRANCH_UNPRICED``).  E's row has no part at all.
MODULE_CC = {
    "Q": CC_PER_PART,
    "E": "none",
    "R": CC_PER_PART,
    "P": CC_PER_PART,
    "W": "none",
}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Aphelios",
    PACKET_SHA256,
    assumption_overrides=(
        "The main weapon is the form axis for P, Q and R, and Weapon Master points "
        "are scenario inputs.",
        "Weapon Master's AD, AS and lethality grants read the cached rows indexed by "
        "points spent.",
        "P prices two of the five weapon innates on the basic-attack channel.",
        "Calibrum's mark adds 15 + 15% bonus AD on one empowered attack, at "
        "aphelios_calibrum_marks (default 0).",
        "Infernum's primary attack is 110% AD, the extra 10% on the same swing; the "
        "cone's secondaries stay unpriced.",
        "Severum prices as healing, Gravitum damages nothing, Crescendum's Chakram "
        "bonus is prose over empty leveling.",
        "That prose is '0% : 138.5% (based on number of Chakrams) AD additional "
        "physical damage'.",
        "Phase (W) is a weapon swap, not a damage cast: cached 0.8s cooldown, cached "
        "0.25s swap.",
        "One main weapon holds for the whole fight, with no mid-fight swap.",
        "Onslaught (severum Q) applies cached item on-hits at 25% per attack, "
        "Duskwave (infernum Q) at 100%.",
        "Duskwave's own 100% AD comes from the off-hand weapon and stays unpriced.",
        "Moonlight Vigil (R) prices the sourced initial blast.",
        "Each r_followup_targets (default 0) champion takes one 100% AD sky attack "
        "applying on-hit at 100% (cached R prose).",
        "Its sourced crit row is '100% : 130% (+ 0% : 9%) based on critical strike "
        "chance'.",
        "It is baked in as an expected-value multiplier 1 + 0.39 x crit^2, weaker "
        "than a 200% attack.",
        "Severum overheal becomes a shield capped at the cached Heal row (10 to 160 "
        "by level + 6% maximum health) for 30s.",
        "aphelios_overheal_shield (default True) stamps each Severum heal, and the "
        "timeline converts the excess at its time.",
        "E (Weapon Queue System) has damageType None and empty leveling rows in "
        "data/champions.json, so its slot is no_damage.",
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
    int_option(
        "r_followup_targets",
        0,
        minimum=0,
        maximum=5,
        label="Locked-on targets hit by Moonlight Vigil follow-up attacks "
        "(each takes one 100% AD main-weapon attack with on-hits)",
        rotation={"role": "irrelevant", "slot": "R"},
    ),
    {
        "key": OPTION_KEYS.main_weapon,
        "type": "select",
        "default": "calibrum",
        "label": "Aphelios main weapon",
        "choices": [
            {"value": key, "label": label} for key, label in _WEAPON_LABELS.items()
        ],
        "rotation": {"role": "irrelevant", "slot": "Q"},
    },
    int_option(
        OPTION_KEYS.calibrum_marks,
        0,
        minimum=0,
        maximum=5,
        label="Calibrum marks the next empowered attack consumes "
        "(each adds 15 + 15% bonus AD physical damage)",
        rotation={"role": "irrelevant", "slot": "P"},
    ),
    int_option(
        OPTION_KEYS.bonus_ad_points,
        0,
        minimum=0,
        maximum=6,
        label="Weapon Master AD points",
        rotation={"role": "self_state", "slot": "P"},
    ),
    int_option(
        OPTION_KEYS.bonus_as_points,
        0,
        minimum=0,
        maximum=6,
        label="Weapon Master AS points",
        rotation={"role": "self_state", "slot": "P"},
    ),
    int_option(
        OPTION_KEYS.lethality_points,
        0,
        minimum=0,
        maximum=6,
        label="Weapon Master lethality points",
        rotation={"role": "self_state", "slot": "P"},
    ),
    bool_option(
        "aphelios_overheal_shield",
        True,
        label="Severum overheal converts into a shield",
        rotation={"role": "self_state", "slot": "P"},
    ),
]

# The Weapon Queue System has nothing to price — it is the prompt that
# reorders the next weapons, with no gameplay effect of its own — so the
# packet's own no_damage row is what E emits, and the slot is no_damage
# rather than an axis the engine is missing.
MODULE_COVERAGE = coverage(no_damage="E")


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Resolve Aphelios self-healing events from its authored packet."""
    healing = []
    r_detail = str(ability_field(ability_payload(ctx.ability_damages, "R"), "detail"))
    if "Severum" in r_detail:
        severum = next(
            (
                entry
                for entry in ctx.champion_data.get("abilities", {}).get("P", [])
                if isinstance(entry, dict) and entry.get("name") == "Severum"
            ),
            {},
        )
        level = int(champion_stat(ctx.champion_stats, "level"))
        basic_scaling = find_named_leveling(severum, "Per-Level Scaling", 0)
        ability_scaling = find_named_leveling(severum, "Per-Level Scaling", 1)
        basic_ratio = (
            sum_modifiers(basic_scaling, level, ctx.champion_stats, {}) / 100.0
            if basic_scaling is not None
            else 0.0
        )
        ability_ratio = (
            sum_modifiers(ability_scaling, level, ctx.champion_stats, {}) / 100.0
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
        heal_leveling = find_named_leveling(severum, "Heal")
        shield_cap = (
            sum_modifiers(heal_leveling, level, ctx.champion_stats, {})
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
        for payment in ctx.payments(
            _healing.HealAnchor.DAMAGING_HIT,
            lambda source: source in {"auto_attacks", "Q"},
        ):
            event = payment.event
            # With Severum equipped the Q row is Onslaught, whose attacks
            # count as ability attacks for the heal.
            ratio = (
                basic_ratio
                if _healing.ledger_source_key(event) == "auto_attacks"
                else ability_ratio
            )
            amount = max(0.0, _row_damage(event)) * ratio
            _healing.heal_from_damage(healing, event, amount, "Severum")
            if overheal_shield and amount > 0.0 and shield_cap > 0.0:
                healing[-1]["overheal_to_shield"] = True
                healing[-1]["overheal_shield_cap"] = shield_cap
                healing[-1]["overheal_shield_duration"] = 30.0
    return healing


SELF_HEALING_RULE = self_healing_rule("Aphelios")(derive_self_healing)
