"""Ivern's brush on-hit, Triggerseed explosion and Daisy summon damage."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import calculation_coefficient, data_value_at_rank, spell_object
from .pet_window import derived_attack_count
from .charge_cadence import ChargeRule
from .engine import ONHIT, SlotCtx, build_parser
from .inputs import bool_option, int_option
from .module_helpers import named_damage, no_damage, ranked_slot
from .slot_cc import CC_PER_PART
from .slot_control import with_control
from .slot_entries import damage_entry, on_hit_entry
from .slot_extract import ability_name, extract_cooldown, extract_named
from .slotlib import simple_damage
from .source_receipts import load_champion_sources


def _brushmaker(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    if not bool(ctx.option("w_in_brush")):
        return no_damage(
            ctx,
            name=ability_name(ability),
            reason="Brushmaker is active utility while not in brush.",
            slot="W",
        )
    value = extract_named(
        ability, "Additional Magic Damage", ctx.rank_for(), ctx.stats, ctx.target
    )
    entry = on_hit_entry(ability_name(ability), value, "magic")
    entry["detail"] = (
        "Brushmaker bonus attack magic damage; brush duration and allied-brush branch "
        "are explicit state."
    )
    return entry


_brushmaker.phase = ONHIT


_triggerseed = named_damage(
    "Magic Damage",
    "magic",
    time_offset=2.0,
    detail="Shield is granted immediately; the sourced explosion occurs after two seconds.",
)


# HARDCODED: verify on patch updates — Daisy's attack stats are not in the
# champion JSON (the R text says only "See Pets for more details").  Sourced
# from the Community Dragon game files (current patch) and the wiki pet
# infobox:
#   https://raw.communitydragon.org/latest/game/data/characters/
#     ivern/ivern.bin.json (IvernR DataValues: DaisyAD, DaisyAS,
#       ShockwaveBaseDamage) and ivernminion/ivernminion.bin.json (unit AS
#       0.75 base)
#   https://wiki.leagueoflegends.com/en-us/Ivern (Daisy pet section)
# Daisy basic attack: 70/100/130 (R rank 1/2/3) (+ 15% AP) physical at
# 0.75 (+ 30/45/60% based on R rank) attack speed -> 1.2 at R rank 3, so
# the default 6 attacks fill the 5-second one-rotation window.
# Daisy Smash!: every third basic attack is empowered (after 2 stacks) to
# deal 90/140/190 (R rank) (+ 50% AP) magic damage and knock up — priced
# as the sourced magic part below; the 3s post-smash lockout is state.
_IVERN_R_SPELL = spell_object("Ivern", "IvernR")
_DAISY_AD_BY_RANK = tuple(
    data_value_at_rank(_IVERN_R_SPELL, "DaisyAD", rank) for rank in range(1, 4)
)
_DAISY_AD_AP_RATIO = calculation_coefficient(_IVERN_R_SPELL, "TotalDaisyAD")
_DAISY_AS_BONUS_BY_RANK = tuple(
    data_value_at_rank(_IVERN_R_SPELL, "DaisyAS", rank) / 100.0 for rank in range(1, 4)
)
_DAISY_BASE_AS = 0.75
# A clockless parse (a direct parse_abilities call, a one-rotation fight)
# carries no fight duration, and this is the window such a reading uses: the
# five seconds the declared count was written against, so a parse with no
# clock prices exactly what it always did.
_DAISY_FALLBACK_WINDOW = 5.0
# Daisy's lifetime is in neither the cache nor the spell object, so the
# derived count is bounded by this declared rail rather than by her own
# clock: at her rank-1 cadence it is about seventeen seconds of attacking.
# A fight longer than that prices the rail and says so, instead of pricing
# a pet that would have expired.
_DAISY_MAX_ATTACKS = 20
_DAISY_SMASH_BY_RANK = tuple(
    data_value_at_rank(_IVERN_R_SPELL, "ShockwaveBaseDamage", rank)
    for rank in range(1, 4)
)
_DAISY_SMASH_AP_RATIO = calculation_coefficient(_IVERN_R_SPELL, "TotalShockwaveDamage")


@ranked_slot
def _daisy(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
    """R: Daisy! — basic attacks plus the 3-hit Daisy Smash knockup."""
    index = min(rank - 1, len(_DAISY_AD_BY_RANK) - 1)
    daisy_attack_speed = _DAISY_BASE_AS * (1.0 + _DAISY_AS_BONUS_BY_RANK[index])
    attacks = derived_attack_count(
        ctx,
        "daisy_attacks",
        attack_speed=daisy_attack_speed,
        fallback_window=_DAISY_FALLBACK_WINDOW,
        maximum=_DAISY_MAX_ATTACKS,
    )
    if attacks <= 0:
        return no_damage(
            ctx,
            name="Daisy!",
            reason=(
                "daisy_attacks is 0: the request asked for none. Leave it "
                "unset and the count is derived from Daisy's cadence over "
                "the fight window."
            ),
        )
    ap = ctx.stat("ability_power")
    per_attack = _DAISY_AD_BY_RANK[index] + _DAISY_AD_AP_RATIO * ap
    per_smash = _DAISY_SMASH_BY_RANK[index] + _DAISY_SMASH_AP_RATIO * ap

    # Every third attack is the empowered Daisy Smash (the smash replaces
    # the ordinary swing, so the counts never double-price an attack).
    smashes = attacks // 3
    normals = attacks - smashes
    interval = 1.0 / (_DAISY_BASE_AS * (1.0 + _DAISY_AS_BONUS_BY_RANK[index]))
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        per_attack * normals + per_smash * smashes,
        "physical",
    )
    # Daisy's ordinary swings apply nothing; the smash this module already
    # reviews as a knockup carries that kind, which is why R's kinds ride
    # its parts instead of MODULE_CC.
    entry["parts"] = (
        DamagePart(
            "physical",
            per_attack,
            count=normals,
            time_offset=0.0,
            hit_interval=interval,
            cc_kind="none",
        ),
        DamagePart(
            "magic",
            per_smash,
            count=smashes,
            time_offset=2.0 * interval,
            hit_interval=3.0 * interval,
            cc_kind="knockup",
        ),
    )
    entry["detail"] = (
        f"Daisy: {attacks} attacks ({normals} basic of {per_attack:.2f} physical "
        f"+ {smashes} Daisy Smash of {per_smash:.2f} magic) at "
        f"{_DAISY_BASE_AS * (1.0 + _DAISY_AS_BONUS_BY_RANK[index]):.2f} attack "
        "speed; the 3s smash lockout and knockup CC are state"
    )
    return entry


SLOTS = {
    "P": lambda ctx: no_damage(
        ctx,
        name="Friend of the Forest",
        reason=(
            "Grove channel, health/mana cost, camp release and full bounty are jungle "
            "utility state."
        ),
    ),
    # The vine damages "the first enemy hit and root[s] them"; the root's
    # duration is read off the packet's own Root Duration row rather than
    # restated, and the single-hit certification is what carries the kind
    # into the event ledger.
    "Q": with_control(
        simple_damage(
            attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
        ),
        duration_attr="Root Duration",
    ),
    "W": _brushmaker,
    "E": _triggerseed,
    "R": _daisy,
}

# Q's vine damages "the first enemy hit and root[s] them"; E's seed
# "explode[s] to deal magic damage to nearby enemies and slow them for 2
# seconds".  R is absent because Daisy's two packets differ (see _daisy).
# P and W author no damage part (W is the on-hit bolt).
MODULE_CC = {"Q": "root", "E": "slow", "R": CC_PER_PART, "P": "none", "W": "none"}


# What this module says about its charge slot (charge_cadence.py).
CHARGE_RULES = {
    "W": ChargeRule(
        why=(
            "W (Brushmaker) banks brush on its cached 20s rechargeRate, "
            "not on the 0.5s gap between two banked casts. The cached "
            "stock of 3 is not spent here: the brush stays."
        ),
        charges=1,
    )
}
parse_abilities = build_parser(
    SLOTS, "Ivern", cc_kinds=MODULE_CC, charge_rules=CHARGE_RULES
)
OPTIONS = [
    bool_option("w_in_brush", True, label="Ivern is in brush"),
    int_option(
        "daisy_attacks",
        6,
        minimum=0,
        maximum=_DAISY_MAX_ATTACKS,
        label=(
            "Daisy attacks; unset derives them from her cadence over the "
            "fight window"
        ),
    ),
]
ASSUMPTIONS = [
    "Ivern's non-epic monster prohibition and grove economics are preserved as utility/state.",
    "Brushmaker's self bonus attack is an on-hit package; allied champion bolts are a "
    "separate roster branch.",
    "Daisy's basic attacks (70/100/130 by R rank + 15% AP physical) and the "
    "third-hit Daisy Smash (90/140/190 by R rank + 50% AP magic) are "
    "game-file constants; verify on patch updates against Community Dragon",
    "Daisy attacks at 0.75 (+ 30/45/60% by R rank) attack speed, and her "
    "attack count is DERIVED from that cadence over the fight window "
    "(champions/pet_window.py): six attacks in a five-second fight, twelve "
    "in a ten-second one. The sourced 3-hit smash cadence prices one smash "
    "per 3 attacks (the smash replaces the ordinary swing). A request may "
    "name the count instead, for the positioning and leash the clock cannot "
    "know. Neither the cache nor the spell object states how long Daisy "
    "lives, so the derivation is bounded at 20 attacks, about seventeen "
    "seconds of her rank-1 cadence, and a longer fight prices that bound "
    "rather than a pet that would have expired.",
    "Daisy Smash!'s 3-second lockout, knockup/stun CC, spawn damage "
    "reduction and leash range are state, not modeled",
    "E (Triggerseed) shields the target allied champion, Daisy, or Ivern "
    "himself (cached prose 'or himself', so the scanner profile is "
    "self-or-target one_teammate): the roster model shields the selected "
    "teammate for the sourced Shield Strength (75-235 + 50% AP) for 2s "
    "and falls back to Ivern in a solo fight; the sourced explosion "
    "damage after 2s and the slow are the module's E damage entry.",
]
SOURCES = load_champion_sources("Ivern")
