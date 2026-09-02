"""Taric — CP10.8 full-entry-reviewed packet module.

E8d ally-support: Q (Starlight's Touch) heals himself and nearby allies per
stocked charge (cached prose: "25 (+ 15% AP) (+ 1% of his maximum health) per
charge"; the cached Q leveling exposes only "Maximum Charges", not a heal
row).  The engine's ally-support scanner cannot author the heal from the
cached leveling, so the Q heal is NOT emitted as a support packet — see E8d
reply for the missing hook.  R (Cosmic Radiance) is invulnerability state
(2.5s), documented as such, not a heal/shield.

Roadmap session 1 (2026-08-20): Q, W, and R are reclassified from
out_of_scope to modeled. Each already carried a real, sourced, tested
numeric effect via the ally-support/self-heal side channels before this
session — the label was simply stale:
  - Q (Starlight's Touch): self/ally heal authored below via
    ``derive_self_healing`` (25 + 15% AP + 1% max health per stocked
    charge, self_and_all_teammates fan-out via the E1 rule); Taric is in
    support_effects.py's ``_MODULE_AUTHORED_HEAL_SLOTS`` so the generic
    scanner correctly defers (pinned in tests/test_issue_143.py,
    tests/test_e1_healing_b5.py, tests/test_survival_kernel.py).
  - W (Bastion): ally/self shield via the support scanner's "Shield
    Strength" packet, an amount_formula keyed off the PROTECTED target's
    max health, 2.5s duration (support_effects.py; pinned in
    tests/test_survival_kernel.py's compiled/receipt-walk parity cases).
  - R (Cosmic Radiance): self_and_all_teammates invulnerability state,
    carried by the support scanner's ``_SUPPORT_STATE_SLOTS`` entry
    (support_effects.py; pinned in tests/test_e8_support.py's
    ``test_taric_cosmic_radiance_targets_the_caster_and_selected_ally``
    and tests/test_survival_kernel.py's delayed-ally-state cases).
Roadmap session 2 (2026-08-20): P (Bravado) is CLOSED — reclassified
from out_of_scope to modeled.  Session 1 left it open on a named
dependency ("needs proc-window dedup logic in damage.py"), because the
engine's ``empowers_next_auto`` mechanism multiplies flatly by cast
count and has no concept of a window being REFRESHED rather than
stacked — four back-to-back Q/W/E/R casts would have booked eight
empowered attacks instead of the sourced maximum of two.  That
dependency now exists: ``damage.py``'s ``_empower_window_procs`` walks
the accepted cast timeline against the fight's consuming actions and
returns one timestamp per charge actually spent.  P declares the window
below; every number in it is read from the cached wiki entry.
"""

import re
from functools import partial
from typing import Any

from ..healing_helpers import ability_json, parsed_rank
from .engine import ONHIT, SlotCtx
from .healing_contract import self_healing_rule
from .inputs import champion_stat
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    extract_named,
    find_named_leveling,
    on_hit_entry,
    simple_damage,
    sum_modifiers,
    with_control,
)

PACKET_SHA256 = "c4661e1dfa5a63e1d512d64efc3bbb6cfb5e5d22f3c5d3e08c363f4d5c672cb4"

# Bravado's damage MAGNITUDE is structured data: the cached P entry's
# "Per-Level Scaling" leveling row (25 : 101 across levels 1-20).  The
# window's SHAPE — how many attacks one cast empowers, how long the
# window lives, and the bonus-armor ratio — lives only in that entry's
# description prose, so it is regex-read from the same cached string.
# Every read below fails closed: a wiki rewrite that moves or renames a
# term raises here naming the champion and the missing term, rather than
# silently falling back to a stale literal.
_BRAVADO_SCALING_ATTRIBUTE = "Per-Level Scaling"
_BRAVADO_WINDOW_RE = re.compile(
    r"empowers his next (?P<attacks>[a-z]+) basic attacks within "
    r"(?P<seconds>\d+(?:\.\d+)?) seconds"
)
_BRAVADO_BONUS_ARMOR_RE = re.compile(r"\+\s*(?P<percent>\d+(?:\.\d+)?)%\s*bonus armor")
# The description spells the empowered-attack count as an English word.
_BRAVADO_ATTACK_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
# Every one of Taric's casts arms Bravado ("After casting an ability").
# The ability-haste cooldown refund is limited to his BASIC abilities,
# but the empowerment itself is not — R arms the window too.
_BRAVADO_ARMED_BY = ("Q", "W", "E", "R")
# Cached P note: "The first attack refreshes Bravado's duration."  Only
# the charges the window actually holds can be spent, so refreshing on
# every consume (rather than on the first alone) cannot add a proc.
_BRAVADO_REFRESH_ON_CONSUME = True


def _bravado_window_terms(ability: dict[str, Any]) -> tuple[int, float, float]:
    """Read (empowered attacks, window seconds, bonus-armor ratio) from cache.

    Raises:
        ValueError: when the cached P description declares neither the
            window shape nor the bonus-armor ratio.
    """
    for effect in ability.get("effects", []):
        description = effect.get("description", "")
        window = _BRAVADO_WINDOW_RE.search(description)
        if window is None:
            continue
        word = window.group("attacks")
        if word not in _BRAVADO_ATTACK_WORDS:
            raise ValueError(
                "Taric P (Bravado): the cached description empowers "
                f"'{word}' basic attacks, which is not a known count"
            )
        armor = _BRAVADO_BONUS_ARMOR_RE.search(description)
        if armor is None:
            raise ValueError(
                "Taric P (Bravado): the cached description carries no "
                "'+ N% bonus armor' ratio for the on-attack damage"
            )
        return (
            _BRAVADO_ATTACK_WORDS[word],
            float(window.group("seconds")),
            float(armor.group("percent")) / 100.0,
        )
    raise ValueError(
        "Taric P (Bravado): no cached description declares the 'empowers "
        "his next <N> basic attacks within <T> seconds' window"
    )


def _bravado(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the sourced on-attack packet of a cast-armed, refreshing window.

    ``empowers_next_auto`` cannot carry this passive — it multiplies
    flatly by cast count, so a four-cast rotation would book eight
    empowered attacks against a sourced maximum of two.  The entry
    instead declares an ``empower_window``, which ``damage.py`` walks
    against the accepted cast timeline and the fight's swings to spend
    at most ``max_charges`` charges per live window.
    """
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
    leveling = find_named_leveling(ability, _BRAVADO_SCALING_ATTRIBUTE)
    if leveling is None:
        raise ValueError(
            "Taric P (Bravado): the cached P entry has no "
            f"'{_BRAVADO_SCALING_ATTRIBUTE}' leveling row for its "
            "on-attack bonus magic damage"
        )
    charges, duration, armor_ratio = _bravado_window_terms(ability)
    base = sum_modifiers(leveling, ctx.level, ctx.stats, ctx.target)
    # Bonus armor is a real build stat: 0.0 here means "this build holds
    # no bonus armor", not "the source is missing" (the magnitude term
    # above is the one that fails closed).  W's own 6-10% of Taric's
    # armor grant is not applied to ``ctx.stats``, so this reads the
    # build's item/rune bonus armor only — see ASSUMPTIONS.
    per_hit = base + armor_ratio * ctx.stat("bonus_armor")
    entry = on_hit_entry(ability_name(ability), per_hit, "magic")
    entry["on_hit"]["empower_window"] = {
        "armed_by": _BRAVADO_ARMED_BY,
        "duration": duration,
        "charges_per_arm": charges,
        "max_charges": charges,
        "consumed_by": ("auto",),
        "refresh_on_consume": _BRAVADO_REFRESH_ON_CONSUME,
    }
    entry["detail"] = (
        f"Bravado: {base:g} (level {ctx.level}) + {armor_ratio * 100:g}% bonus "
        f"armor per empowered attack; a cast arms up to {charges} charges for "
        f"{duration:g}s and re-arming refreshes rather than stacks"
    )
    return entry


_bravado.phase = ONHIT


# Reviewed crowd control, read from the cached kit: E (Dazzle) "projects a
# beam of starlight in the target direction that deals magic damage to
# enemies hit and stuns them for 1.5 seconds".  Q, W and R deal no damage
# — heal, shield and invulnerability — and P is an attack-stream rider, so
# E is the whole of this kit's reviewable control.
MODULE_CC = {"E": "stun"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Taric",
    PACKET_SHA256,
    slot_parsers={
        # One beam, one blow, so the row is a hit the ledger can time.
        "E": simple_damage(
            attr="Magic Damage",
            dmg_type="magic",
            ranks="rank",
            source=("E", 0),
            event_order_certified="single_hit",
        ),
        "P": _bravado,
    },
    # The stun's duration and its source atom come off the cached E entry,
    # so MODULE_CC's reviewed kind and the priced interval are one fact.
    slot_wrappers={
        "E": partial(with_control, duration_attr="Stun Duration"),
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "E's sourced 1.5-second stun counts as target action downtime",
    "W (Bastion) shields Taric and the linked selected teammate the "
    "sourced Shield Strength as a live % of the PROTECTED TARGET's "
    "maximum health (scanner packet with a max-health amount formula "
    "and 2.5s duration, selection key shield:W:<cast>).",
    "Q (Starlight's Touch) heals Taric and every selected teammate "
    "the sourced per-charge heal (25 + 15% AP + 1% of his maximum "
    "health per charge, capped at the 5-charge maximum) via the E1 "
    "rule and its self_and_all_teammates fan-out; the scanner defers "
    "the slot (no heal row in the cached Q leveling).",
    "R (Cosmic Radiance) grants the caster and every selected "
    "teammate invulnerability after the sourced 2.5s descent for the "
    "sourced 2.5s window (state packet).",
    "P (Bravado) prices the sourced on-attack bonus magic damage "
    "(25 : 101 based on level, the cached 'Per-Level Scaling' row, "
    "+ 15% bonus armor read from the same description) once per "
    "empowered attack the window actually grants.  A cast arms up to "
    "two charges for 5 seconds and re-arming REFRESHES rather than "
    "stacks, so a four-cast rotation still books at most two "
    "empowered attacks; damage.py's empower-window walk spends the "
    "charges against the accepted cast timeline and the fight's own "
    "swings.  An attack that lands at the same instant as its arming "
    "cast does not consume a charge (the named conservative "
    "tie-break), so one-rotation fights, whose casts all collapse to "
    "t=0, price the passive at or below its live value.",
    "P (Bravado)'s two NON-damage effects are not modeled: the 100% "
    "total attack speed on each empowered attack (it would change "
    "the fight's swing count, which the auto-attack schedule owns) "
    "and the 1 : 2 (based on ability haste) cooldown refund on "
    "Taric's basic abilities.  Both are omissions, so the modeled "
    "damage is a floor, never an overstatement.",
    "P (Bravado)'s '+ 15% bonus armor' term reads the BUILD's bonus "
    "armor.  W (Bastion)'s sourced 6-10% of Taric's armor passive "
    "grant is not applied to ctx.stats by this module, so it does "
    "not feed the passive; adding it belongs to W, not P.",
]

COVERAGE_CHANNELS = {"Q": ("self_healing_rule",)}


# pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument
def _starlights_touch(
    q_ability: dict[str, Any],
    q_rank: int,
    champion_stats: dict[str, float],
) -> tuple[float, int]:
    """Price one Taric Q (Starlight's Touch) cast from the cached data.

    The per-charge and maximum formulas are wiki description text in
    ``data/champions.json``; the stock is the rank-scaled "Maximum Charges"
    leveling attribute.  Returns ``(heal_amount, charges_used)`` — the
    amount at the sourced stock, capped at the "maximum of ... at 5
    charges" row, with zero when no per-charge formula or stock exists.
    This is the single formula source for the Q heal; the support scanner
    never re-prices the slot.
    """
    charges = extract_named(q_ability, "Maximum Charges", q_rank, champion_stats, {})
    descriptions = [
        effect.get("description", "") for effect in q_ability.get("effects", [])
    ]
    per_charge_match = re.search(
        r"for\s+(\d+(?:\.\d+)?)\s*\(\+\s*(\d+(?:\.\d+)?)%\s*AP\)"
        r"\s*\(\+\s*(\d+(?:\.\d+)?)%\s*of his maximum health\)\s*per charge",
        " ".join(descriptions),
        flags=re.IGNORECASE,
    )
    maximum_match = re.search(
        r"maximum of\s+(\d+(?:\.\d+)?)\s*\(\+\s*(\d+(?:\.\d+)?)%\s*AP\)"
        r"\s*\(\+\s*(\d+(?:\.\d+)?)%\s*of his maximum health\)",
        " ".join(descriptions),
        flags=re.IGNORECASE,
    )
    if per_charge_match is None or charges <= 0.0:
        return 0.0, max(0, round(charges))
    maximum_health = champion_stat(champion_stats, "health", champion="Taric")
    ability_power = champion_stat(champion_stats, "ability_power", champion="Taric")

    def _charge_heal(flat: float, ap_percent: float, hp_percent: float) -> float:
        return (
            flat
            + ability_power * ap_percent / 100.0
            + maximum_health * hp_percent / 100.0
        )

    per_charge = _charge_heal(
        float(per_charge_match.group(1)),
        float(per_charge_match.group(2)),
        float(per_charge_match.group(3)),
    )
    heal = charges * per_charge
    if maximum_match is not None:
        heal = min(
            heal,
            _charge_heal(
                float(maximum_match.group(1)),
                float(maximum_match.group(2)),
                float(maximum_match.group(3)),
            ),
        )
    return max(0.0, heal), max(0, round(charges))


def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Starlight's Touch pays its per-charge heal on each Q cast.

    This rule is the one ledger owner of the Q heal.  The support
    scanner defers the slot (``_MODULE_AUTHORED_HEAL_SLOTS``) and
    the participant timeline fans this event out to selected teammates, so
    one formula prices every recipient.  The event declares
    ``target_scope: self_and_all_teammates`` and stamps the charge count
    used (``charges``) for the public receipt.
    """
    healing: list[dict] = []
    heal, charges = _starlights_touch(
        ability_json(champion_data, "Q"),
        parsed_rank(ability_damages, "Q"),
        champion_stats,
    )
    if heal > 0.0:
        for cast_index, cast in enumerate(cast_timeline or []):
            if cast.get("slot") != "Q":
                continue
            healing.append(
                {
                    "time": float(cast.get("time", 0.0)),
                    "amount": heal,
                    "source": "Starlight's Touch",
                    "kind": "champion_ability",
                    "actor_wide": True,
                    "target_scope": "self_and_all_teammates",
                    "charges": charges,
                    "_event_id": f"taric:q:{cast_index}",
                }
            )
    return healing


SELF_HEALING_RULE = self_healing_rule("Taric")(derive_self_healing)
