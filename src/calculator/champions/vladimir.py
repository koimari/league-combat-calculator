"""Vladimir — CP10.9 full-entry-reviewed packet module.

P1-3 closure — R (Hemoplague) damage amplification: the reviewed R
packet priced only the detonation burst (plus the E1 heal family).  The
plague also "infects enemies hit for 4 seconds, increasing the damage
they take from all sources by 10%" (data/champions.json R prose; the
wiki's Hemoplague notes state it "amplifies itself for an actual damage
of 165 / 275 / 385 (+ 77% AP)" — the 150/250/350 (+ 70% AP) detonation
plus its own 10%).  An AMP-phase pseudo-slot (the Amumu Cursed Touch
precedent) adds a 10% bonus part to every damage entry while the mark is
on the target, gated by the ``r_hemoplague_debuff`` option (default on,
with the sourced R-first opening assumption).  In-game true damage is
not amplified (wiki bug note); Vladimir's kit deals none.

Roadmap session 4 batch H (2026-08-21): P (Crimson Pact) has no
enemy-damage formula: its cached effect converts a percentage of
Vladimir's bonus health into ability power (a pure self stat-conversion,
no enemy-damage row anywhere in the entry). The pinned reviewed packet
(static/reviewed-packets.json) independently declares P ``kind:
"no_damage"`` with a sourced reason, and P is not one of the slots this
module's ``slot_parsers`` reassigns (only W and E are overridden), so it
falls to ``build_packet_module``'s default no_damage branch and already
emits the packet's sourced zero-damage row today — MODULE_COVERAGE was
simply stale, still reading "out_of_scope" for an already-covered slot
(the Malzahar/Nasus precedent, roadmap session 4 batch D; the
Ryze/Senna/Swain/Tahm Kench precedent, batch G). Reclassified to
"no_damage"; zero fight-computation change.
"""

from typing import Any

from ..ability_atoms import (
    AbilityAtomQuery,
    ranked_ability_atom_value,
    required_ability_atom,
)
from ..ability_spec import DamagePart
from .engine import AMP, SlotCtx, build_parser
from .packet_module import build_packet_module, repeat_damage_parser
from .slotlib import damage_entry

PACKET_SHA256 = "03e211424b005b94fe9d0df6d90a10efc1aa4d935e306143b14b0b254bd3532d"

# HARDCODED: verify on patch updates — Tides of Blood's charge ramp
# ("increased based on charge time up to the first second" of the
# 1.5-second channel) is wiki prose; the ramp's endpoints are the
# sourced Minimum/Maximum Magic Damage rows, which do NOT scale
# uniformly (flat x2, % max health x4, % AP ~x2.3), so each modifier
# interpolates on its own between its min and max values.  The 1.5s
# channel is atom-backed (timing.active_duration 367b90ae9fc5cf38); the
# 1.0s ramp has NO atom anywhere (prose-only — the degraded "charge
# time" row) and stays a documented hardcoded constant (the charge
# fraction is the model's selection surface).  The engine does NOT time
# the channel: the E damage lands at the cast start, and the 1.5s
# auto-recast, the 20% channel self-slow tail, the health cost
# (cached values zeroed, the 2/4/6/8% tiers in the units prose), the
# below-12% free clause, and the enemy slow are named out-of-scope
# boundaries (W stays usable mid-channel — a full 1.5s cast_time would
# be wrong for this kit).
_E_CHARGE_RAMP_SECONDS = 1.0  # damage maxes out after 1.0s of charging
_E_CHANNEL_SECONDS = 1.5  # total charge window before the auto-recast


class _TidesOfBloodChargeRule:
    """The typed charge-model certification (the Asol/Briar pattern).

    The charge selection: e_charge_fraction (0..1, default 1.0 = fully
    charged, reproducing the reviewed packet's maximum-row numbers).
    The min/max rows are the atoms ability.minimum _magic _damage /
    ability.maximum _magic _damage (modifiers 0..2); the channel is the
    timing.active_duration atom; the 1.0s ramp roots in the wiki prose
    (no atom exists — the degraded "charge time" parse).
    """

    def certified_atom_ids(self) -> dict[str, Any]:
        """The pinned atom evidence (the receipt's atom_ids)."""
        return dict(self.public_receipt()["atom_ids"])

    def public_receipt(self) -> dict[str, Any]:
        """The typed charge-model receipt (ramp/channel/default/atoms)."""
        return {
            "name": "Tides of Blood charge model",
            "ramp_seconds": _E_CHARGE_RAMP_SECONDS,
            "channel_seconds": _E_CHANNEL_SECONDS,
            "default_fraction": 1.0,
            "ramp_source": (
                "wiki prose (degraded 'charge time' parse — no atom): "
                "'increased based on charge time up to the first second'"
            ),
            "atom_ids": {
                "channel_seconds": {
                    "atom_id": "timing.active_duration",
                    "hash": "367b90ae9fc5cf38",
                },
                "min_modifier_0": {
                    "atom_id": "ability.minimum _magic _damage.modifier_0",
                    "hash": "ed0a9a756a254ee9",
                },
                "max_modifier_0": {
                    "atom_id": "ability.maximum _magic _damage.modifier_0",
                    "hash": "1e9f85c82f8835bf",
                },
            },
        }


TIDES_OF_BLOOD_CHARGE_RULE = _TidesOfBloodChargeRule()
E_CHARGE_RULE = TIDES_OF_BLOOD_CHARGE_RULE  # the test-surface alias


class _TidesOfBloodBoundaryRules:
    """The documented out-of-scope boundaries (receipts, not seams).

    The health cost: the cached cost row's values are zeroed with the
    2% / 4% / 6% / 8% tiers in the units prose; the engine has no
    attacker current-health input, so the cost is NOT priced (the
    endpoints + the below-12% free clause from effects[4] are declared
    as the documented boundary).  The enemy slow (40-60% for 0.5s, only
    at full charge — "charged for at least 1 second" == the ramp
    completion) is utility per the module assumptions.
    """

    def public_receipt(self) -> dict[str, Any]:
        """Both boundary receipts (the test surface calls public_receipt)."""
        return {
            "health_cost": self.health_cost_receipt(),
            "slow": self.slow_receipt(),
        }

    def health_cost_receipt(self) -> dict[str, Any]:
        """The health-cost boundary receipt (2/8% endpoints + the 12% free clause)."""
        return {
            "name": "Tides of Blood health cost (boundary)",
            "priced": False,
            "cost_percent_at_min_charge": 2.0,
            "cost_percent_at_max_charge": 8.0,
            "free_below_fraction_of_max_health": 0.12,
            "source": {
                "wiki": {
                    "revision_id": 2864482,
                    "row": "the cached cost row units prose '2% / 4% / 6% / "
                    "8% (based on charge time)' (values zeroed) + effects[4] "
                    "prose",
                },
                "boundary": "no attacker current-health input exists",
            },
        }

    def slow_receipt(self) -> dict[str, Any]:
        """The enemy-slow utility boundary receipt (40-60% for 0.5s at full charge)."""
        return {
            "name": "Tides of Blood slow (utility boundary)",
            "priced": False,
            "slow_level_1": 40.0,
            "slow_level_5": 60.0,
            "duration_seconds": 0.5,
            "requires_full_ramp": True,
            "full_charge_only": True,
            "source": {
                "wiki": {
                    "revision_id": 2864482,
                    "row": "the cached Slow row [40..60]% + effects[2] "
                    "prose 'charged for at least 1 second'",
                },
                "boundary": "utility, not modeled",
            },
        }


_TIDES_BOUNDARIES = _TidesOfBloodBoundaryRules()
E_HEALTH_COST_RULE = _TIDES_BOUNDARIES
E_SLOW_RULE = _TIDES_BOUNDARIES


def _tides_of_blood(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: charge-interpolated nova between the sourced min/max rows.

    Each of the three modifiers (flat, % maximum health, % AP) is read
    from BOTH the Minimum and Maximum rows at the selected
    ``e_charge_fraction`` (default 1.0 = fully charged, which reproduces
    the reviewed packet's maximum-row numbers exactly).  The "% maximum
    health" term follows the reviewed packet's stat resolution: the
    champion's OWN maximum health (``ctx.stats["health"]``), the same
    ``health`` stat the pinned packet maps it to.
    """
    ability = ctx.ability("E", 0)
    if ability is None:
        return None
    rank = ctx.rank_for("E")
    if rank < 1:
        return None

    raw_fraction = ctx.options.get("e_charge_fraction", 1.0)
    if isinstance(raw_fraction, bool):
        raise ValueError("e_charge_fraction must be a number, not a bool")
    fraction = min(max(float(raw_fraction), 0.0), 1.0)

    # P4: the atom-backed FAIL-CLOSED read swap (the Briar-E precedent) —
    # every row read resolves through the atom catalog (missing/stale
    # rows raise naming the source; never a silent 0.0).
    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}

    def _row(attribute: str, modifier_index: int) -> float:
        """One min/max row modifier through the atom catalog (fail closed)."""
        atom = required_ability_atom(
            ctx.champion_name,
            champion_data,
            "E",
            query=AbilityAtomQuery(
                source=f"Vladimir.E[0].effects[1].leveling[{0 if 'Minimum' in attribute else 1}]"
                f".modifiers[{modifier_index}]",
                behavior="ability",
                evidence_prefix=f"{attribute}@effects[1]",
            ),
        )
        return ranked_ability_atom_value(atom, rank, source=f"E {attribute}")

    def _interp(attribute: str, modifier_index: int) -> float:
        """The fraction-interpolated value of one row modifier."""
        minimum = _row(attribute, modifier_index)
        maximum = _row(
            "Maximum Magic Damage" if "Minimum" in attribute else attribute,
            modifier_index,
        )
        return minimum + (maximum - minimum) * fraction

    flat = _interp("Minimum Magic Damage", 0)
    total = (
        flat
        + _interp("Minimum Magic Damage", 1) / 100.0 * float(ctx.stats["health"])
        + _interp("Minimum Magic Damage", 2) / 100.0 * float(ctx.stats["ability_power"])
    )
    # P4: the cooldown read is atom-backed (timing.cooldown
    # 15cbce498dc12195, [13,11,9,7,5]) — a missing/stale row raises
    # instead of a silent 0.0.
    cooldown_atom = required_ability_atom(
        ctx.champion_name,
        champion_data,
        "E",
        query=AbilityAtomQuery(
            source="Vladimir.E[0].cooldown",
            behavior="timing",
            evidence_prefix="cooldown.modifiers[0]",
        ),
    )
    cooldown = ranked_ability_atom_value(cooldown_atom, rank, source="E cooldown")
    entry = damage_entry(
        ability.get("name", "Tides of Blood"),
        rank,
        cooldown,
        total,
        "magic",
    )
    hp_percent = _interp("Minimum Magic Damage", 1)
    ap_percent = _interp("Minimum Magic Damage", 2)
    entry["detail"] = (
        f"{fraction * 100:g}% charge ({fraction * _E_CHARGE_RAMP_SECONDS:g}s of "
        f"the {_E_CHARGE_RAMP_SECONDS:g}s ramp; {_E_CHANNEL_SECONDS:g}s channel): "
        f"flat {flat:g} + {hp_percent:g}% maximum health + "
        f"{ap_percent:g}% AP"
    )
    return entry


parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Vladimir",
    PACKET_SHA256,
    assumption_overrides=(
        "Sanguine Pool prices all 4 pool ticks (Magic Damage Per Tick x 4 "
        "== Total Magic Damage) at 0.5-second intervals over 2 seconds.",
    ),
    slot_parsers={
        "W": repeat_damage_parser(
            attr="Magic Damage Per Tick",
            dmg_type="magic",
            count=4,
            time_offset=0.5,
            hit_interval=0.5,
            dot_duration=2.0,
        ),
        "E": _tides_of_blood,
    },
)
PACKET_SPEC = SLOTS.packet_spec

# HARDCODED: verify on patch updates — wiki prose, not in the JSON
# leveling rows.  Hemoplague: "increasing the damage they take from all
# sources by 10%" (patch history: "Damage amplification reduced to 10%
# from 12%", duration 4 seconds).
_R_HEMOPLAGUE_INCREASE = 0.10


def _apply_hemoplague(result: dict[str, Any]) -> None:
    """Scale every part by the 10% increased-damage-taken debuff.

    Scaling each part's amount in place (instead of appending one bonus
    part) preserves the authored per-tick / per-hit timing of the
    entry's event timeline — a single appended un-timed part would
    collapse a ticked ability back to one aggregate cast event (the E2
    tick certification).
    """
    parts = result.get("parts", ())
    if not parts:
        return
    scaled = []
    for part in parts:
        amount = float(part.amount) * (1.0 + _R_HEMOPLAGUE_INCREASE)
        scaled.append(
            DamagePart(
                part.damage_type,
                amount=amount,
                count=part.count,
                hp_scaled_damage=part.hp_scaled_damage,
                crit_effectiveness=part.crit_effectiveness,
                basic_damage=part.basic_damage,
                bonus_ad_ratio=part.bonus_ad_ratio,
                dot_stack_scaled=part.dot_stack_scaled,
                time_offset=part.time_offset,
                hit_interval=part.hit_interval,
                cc_kind=part.cc_kind,
                cc_duration=part.cc_duration,
                skillshot=part.skillshot,
            )
        )
    result["parts"] = tuple(scaled)
    total = sum(float(part.amount) * max(1, int(part.count)) for part in scaled)
    result["total_raw"] = total
    if "damage_by_type" in result:
        result["damage_by_type"] = {
            dtype: amount * (1.0 + _R_HEMOPLAGUE_INCREASE)
            for dtype, amount in result["damage_by_type"].items()
        }


def _hemoplague_amp(ctx: SlotCtx) -> None:
    """AMP pseudo-slot: the 10% debuff amplifies every damage entry."""
    if not ctx.options.get("r_hemoplague_debuff", True):
        return
    for key in ("Q", "W", "E", "R"):
        entry = ctx.results.get(key)
        if entry is not None:
            _apply_hemoplague(entry)


_hemoplague_amp.phase = AMP


SLOTS = dict(SLOTS)
SLOTS["hemoplague"] = _hemoplague_amp
parse_abilities = build_parser(SLOTS, "Vladimir")

OPTIONS = list(OPTIONS) + [
    {
        "key": "e_charge_fraction",
        "type": "float",
        "default": 1.0,
        "min": 0.0,
        "max": 1.0,
        "step": 0.1,
        "label": (
            "Tides of Blood charge (0 = uncharged minimum, 1 = fully "
            "charged after 1s of the 1.5s channel)"
        ),
        "rotation": {"role": "irrelevant", "slot": "E"},
    },
    {
        "key": "r_hemoplague_debuff",
        "type": "bool",
        "default": True,
        "label": (
            "Hemoplague mark active: the target takes 10% increased "
            "damage from all sources while marked (R-first opening)"
        ),
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "R (Hemoplague) marks the target for 4 seconds: all damage dealt "
    "while marked is increased by 10% (cached R prose; patch history "
    "'reduced to 10% from 12%').  The AMP pseudo-slot adds the sourced "
    "10% bonus part to every damage entry (Q/W/E/R), so the R "
    "detonation itself prices 165/275/385 (+ 77% AP) — the wiki's "
    "explicit self-amplified note.  The mark is assumed applied at "
    "fight start (R-first opening) so the whole one-rotation window "
    "sits inside the 4s mark; toggle r_hemoplague_debuff off to price "
    "an unmarked rotation.  In-game true damage is not amplified "
    "(wiki bug note); Vladimir's kit deals none.",
    "E (Tides of Blood) interpolates each sourced modifier (flat, "
    "% maximum health, % AP) between the cached Minimum and Maximum "
    "Magic Damage rows by the e_charge_fraction option (default 1.0 = "
    "fully charged, exactly the reviewed packet's maximum-row numbers). "
    "The ramp completes over the first 1 second of the 1.5-second "
    "channel (wiki prose; the degraded 'charge time' parse carries no "
    "leveling data, so the fraction is the selection).  The "
    "% maximum health term follows the reviewed packet's stat "
    "resolution: the champion's own maximum health.  The 40-60% slow "
    "on fully charged casts is utility.",
    "P (Crimson Pact) has no enemy-damage formula: it converts a "
    "percentage of bonus health into ability power, a pure self "
    "stat-conversion (confirmed by the pinned reviewed packet's "
    "kind='no_damage' declaration for P). P is a cast slot in this "
    "module (never reassigned away from build_packet_module's "
    "no_damage branch), so MODULE_COVERAGE reflects a sourced "
    "no-damage classification rather than an unmodeled gap (no_damage, "
    "not out_of_scope).",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "no_damage")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .. import healing_helpers as _healing  # pylint: disable=wrong-import-position


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument,wrong-import-position
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Vladimir self-healing events from its authored packet."""
    healing = []
    q_rank = _healing._rank(ability_damages, "Q")
    q_heal = _healing.extract_named(
        _healing._ability(champion_data, "Q"), "Heal", q_rank, champion_stats
    )
    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "Q"
    ):
        _healing._heal_from_damage(
            healing, event, q_heal, "Transfusion", link_to_damage=False
        )
    # Sanguine Pool (W): heals for 30% of pre-mitigation damage dealt
    # (patch 12.13: "Healing increased to 30% of damage dealt from 15%";
    # 18% against minions — champion targets assumed here).
    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "W"
    ):
        # Pre-mitigation damage per the wiki ("30% of the pre-mitigation
        # damage dealt"); the engine exposes it as event["raw_damage"].
        dealt = float(event.get("raw_damage", event.get("damage", 0.0)) or 0.0)
        _healing._heal_from_damage(healing, event, 0.30 * dealt, "Sanguine Pool")
    # Hemoplague (R): flat heal per infected champion, reduced for later
    # targets (wiki: "Heal: 150 / 250 / 350 (+ 70% AP)" and
    # "Reduced Heal: 60 / 100 / 140 (+ 28% AP)").  Each pair fight sees
    # only its own R packet, so every copy is authored at the full value
    # with the reduced amount attached as an explicit receipt; the
    # coupled participant ledger re-prices later roster targets so the
    # first infected champion pays the full heal and each additional
    # champion pays the reduced heal.
    r_rank = _healing._rank(ability_damages, "R")
    r_heal = _healing.extract_named(
        _healing._ability(champion_data, "R"), "Heal", r_rank, champion_stats
    )
    r_reduced = _healing.extract_named(
        _healing._ability(champion_data, "R"), "Reduced Heal", r_rank, champion_stats
    )
    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "R"
    ):
        _healing._heal_from_damage(
            healing,
            event,
            r_heal,
            "Hemoplague",
            later_target_amount=r_reduced,
            link_to_damage=False,
        )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Vladimir", derive_self_healing)
