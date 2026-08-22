"""Sourced ally-targeted shields/heals from champion ability packets."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .ability_atoms import (
    AbilityAtomQuery,
    ranked_ability_atom_value,
    required_ranked_attribute_atom,
    required_ability_atom,
)
from .capabilities import SUPPORT_TARGET_RESOLUTION_SCOPES
from .item_behavior import PacketKind
from .data_registry import data_version, store_for_generation
from .survival.actions import SUPPORT_RANK_KEY, TransitionRank
from .champions.slotlib import extract_named, find_named_leveling
from .champions.skill_orders import get_ability_rank


def _ability(data: dict[str, Any], slot: str) -> dict[str, Any]:
    entries = data.get("abilities", {}).get(slot, [])
    return entries[0] if entries and isinstance(entries[0], dict) else {}


def _first_attribute(ability: dict[str, Any], names: tuple[str, ...]) -> str | None:
    available = {
        leveling.get("attribute", "")
        for effect in ability.get("effects", [])
        for leveling in effect.get("leveling", [])
    }
    return next((name for name in names if name in available), None)


# One leveling row is declared by ONE effect sentence, but the scope and kind
# below are read from every sentence of the ability joined together.  That
# blob can only ever be over-broad about a single row — it sees an ally some
# other sentence grants to, and a heal some other sentence performs — so the
# row's own declaring sentence decides its recipient (``_row_target``) and
# whether it is a heal at all (``_declares_a_heal``); the blob only supplies
# the breadth of an ally scope the sentence already established.
#
# An ally the row can grant to.  "Allied" alone only qualifies the noun after
# it, and not every allied noun receives anything: Bel'Veth R's True Form
# sentence ends "...spawn from allied and enemy minions that die nearby",
# which named a teammate for a heal that is hers.
_ALLY_PROSE = re.compile(
    r"\ball(?:y|ies)\b|\bteammates?\b|\ballied\s+(?:champion|unit|turret|target)"
)
# The caster, named or pronounced.  Reflexives and the singular third
# person are bound to the sentence's subject, which is the caster; "they",
# "them" and "their" are not — every wiki sentence that uses them is
# speaking about the ability's target (Zilean R's "they revive while being
# healed", Lulu E's "they are granted a shield").
_CASTER_PROSE = re.compile(
    r"\b(?:he|him|his|she|her|hers|himself|herself|themselves|itself)\b"
)
_HEAL_PROSE = re.compile(r"\bheal(?:s|ed|ing)?\b|\brestor(?:e|es|ing)\b|\bregenerat")


def _row_prose(ability: dict[str, Any]) -> dict[str, str]:
    """Each attribute mapped to the lowercased prose of the effect declaring it.

    ``extract_named`` reads the FIRST matching leveling entry across effects,
    so the first declaring effect is the sentence that row's number came from.
    """
    prose: dict[str, str] = {}
    for effect in ability.get("effects", []):
        description = str(effect.get("description", "")).lower()
        for leveling in effect.get("leveling", []):
            prose.setdefault(str(leveling.get("attribute", "")), description)
    return prose


def _row_target(
    prose: str, *, champion: str, scope: str, target_self: bool, override: str | None
) -> tuple[str, bool] | None:
    """Who one row grants to, read from its own declaring sentence.

    A sentence naming an ally leaves the caster at the scope the whole
    ability resolved; one naming only the caster is a self grant; one naming
    neither recipient is refused, because a recipient nobody sourced is not a
    teammate by default.  An explicit per-champion override still wins
    (Yuumi E's attached anchor, Kindred R's "all targetable units").
    """
    if override is not None:
        # The override fixes the SCOPE; the flag has to follow it when the
        # scope it names is the caster.  Passing the ability-wide flag
        # through published ``scope="self"`` with ``target_self=False`` for a
        # sentence no self marker matches (Rumble W's bare "grant himself"),
        # a pair the ordinary path cannot produce and one the teammate-less
        # branch of the roster resolver reads as "grant nobody".
        return override, target_self or override == "self"
    if _ALLY_PROSE.search(prose):
        return scope, target_self
    if champion.lower() in prose or _CASTER_PROSE.search(prose):
        return "self", True
    return None


# The wiki's ability template names the last unlabelled row ``Heal`` whatever
# it measures: Mordekaiser W's is the Potential Shield decay rate ("decays by
# 8 : 25 (based on level) every second"), Udyr Q's a minimum-damage floor.
def _declares_a_heal(prose: str) -> bool:
    """Whether the sentence declaring a ``Heal``-named row states a heal."""
    return bool(_HEAL_PROSE.search(prose))


# The shield and heal lookups, in priority order: the first name a kit
# carries is the row that is priced.  A conditional row's floor precedes its
# ceiling ("Minimum" before "Maximum") so an amount the scan cannot condition
# is the guaranteed one — Shen R's shield is "increased by 0% : 60% (based on
# target's missing health)" and live health is not a scan-time fact.
_SHIELD_ATTRIBUTES = (
    "Shield Strength",
    "Shield",
    # Magic-only shields (Morgana E's Black Shield, Galio W, Kassadin Q):
    # the ledger absorbs them as an ordinary pool — the magic-only
    # restriction is the boundary named in each module.
    "Magic Shield Strength",
    "Minimum Shield Strength",
    "Maximum Shield Strength",
)
_HEAL_ATTRIBUTES = (
    "Total Heal",
    "Heal",
    "Heal Per Tick",
    # Bard W (Caretaker's Shrine) heals scale with charge time between these
    # two sourced rows.  Taric Q carries only the "Maximum Charges" attribute
    # and its heal belongs to the E1 rule, so it is NOT a support candidate.
    "Minimum Heal",
    "Maximum Heal",
)

# Attribute names that make a kit a support-packet candidate — the union of
# the shield and heal lookups above.  A champion whose ability JSON carries
# none of them can never emit a packet, so the coupled optimizer's per-
# candidate calls skip the full walk.  Memoized by champion-data identity
# and re-verified on every hit, so a data refresh can never serve a stale
# answer through a recycled ``id()``.
_SUPPORT_ATTRIBUTES = frozenset(_SHIELD_ATTRIBUTES + _HEAL_ATTRIBUTES)

# The slots a support packet can hang on.  A packet hangs on a CAST, and a
# passive is never cast: ``champions/engine.py`` keys a P entry "passive" and
# the rotation schedules none, so widening this tuple to P would add a pass
# that can never fire.  A passive shield or heal therefore rides a damaging
# cast through ``slotlib.attach_self_shield`` (Rakan P, Shen P) or a healing
# rule (Yuumi P) instead of this scanner.
_SUPPORT_SLOTS = ("Q", "W", "E", "R")
_SUPPORT_ATTRS_MEMO: dict[tuple[int, int], tuple[dict[str, Any], bool]] = {}

# E8d follow-up: per-champion heal-attribute overrides.  Bard W's shrine
# gathers power over 5s; the deterministic single-target model prices the
# fully-charged sourced row (Maximum Heal) and documents the charge-time
# boundary in the packet source label.
_CHAMPION_HEAL_ATTR: dict[tuple[str, str], str] = {
    ("Bard", "W"): "Maximum Heal",
}

# P1-3: per-champion shield-attribute overrides.  Lux W (Prismatic
# Barrier) shields Lux on both the throw and the return of the wand, so
# one cast stacks two "Shield Strength" shields into the sourced
# "Maximum Shield" row (80-200 + 80% AP by rank, data/champions.json);
# the generic scanner would price one half-strength shield.
_CHAMPION_SHIELD_ATTR: dict[tuple[str, str], str] = {
    ("Lux", "W"): "Maximum Shield",
}

# Taric Q has ONE ledger owner: the E1 self-heal rule in ``healing.py`` prices
# the sourced stock and the participant timeline fans that one event out to
# selected allies.  This module holds no numeric heal registry, deliberately.
#
# Target-scope overrides for casts whose cached description markers cannot
# express the sourced targeting.  Yuumi's E (Zoomies) shields the attached
# ally, not Yuumi herself, and the deterministic roster model targets one
# selected teammate (the anchor).
_SCOPE_OVERRIDES: dict[tuple[str, str], str] = {
    # These abilities have a self-or-ally cast in their source description.
    # The deterministic roster model exposes the ally choice when a roster
    # exists and falls back to the caster in a solo fight.
    ("Ekko", "W"): "self",
    ("K'Sante", "E"): "one_teammate",
    ("Kassadin", "Q"): "self",
    ("Lee Sin", "W"): "self_and_one_teammate",
    ("Yuumi", "E"): "one_teammate",
    ("Rumble", "W"): "self",
    # P1-3: Lux W (Prismatic Barrier) shields Lux herself on the throw and
    # the return ("Lux gains the shield upon throwing and upon retrieving
    # the wand"); the allied half needs a teammate roster the 1v1 lacks,
    # so the deterministic single-target cast targets self.
    ("Lux", "W"): "self",
    # Rakan Q's cached prose ("Rakan heals himself and nearby allied
    # champions") would resolve ``self_and_all_teammates`` and double-grant
    # the self heal, which the champion rule prices per LEVEL (40 : 230 based
    # on level, 210 at level 18).  The champion-owned self heal wins, so this
    # packet targets ALLIES ONLY; in a 1v1 it resolves to nothing and the self
    # heal pays exactly once.
    ("Rakan", "Q"): "all_teammates",
    # Lamb's Respite (R) is one of the two ally grants whose declaring
    # sentence names no ally, so ``_row_target`` would refuse it: "All
    # targetable units within the zone are healed when the blessing ends."
    # Every unit in the zone is healed, not one, and the self copy is the
    # healing rule's ("Lamb's Respite", actor-wide) — so the scanner's
    # packet is the allied half and it reaches all of them.
    ("Kindred", "R"): "all_teammates",
    # Kassadin Q ("He also gains a shield...") and Galio W ("Galio gains
    # Anti-Magic Bulwark...") were pinned here while only reflexive verb
    # forms counted as the caster; ``_row_target`` reads the ordinary
    # pronoun and the champion's own name now, so both resolve to ``self``
    # from their sentences and need no entry.
    ("Taric", "R"): "self_and_all_teammates",
    # E8d follow-up: Renata's E (Loyalty Program) rockets "grant a shield
    # to Renata and allies struck" — every selected teammate the rockets
    # pass through, not one.  The SELF half is module-authored on the E
    # damage entry (E8c payload), so the scanner's ally branch resolves
    # all_teammates and never double-grants the caster.
    ("Renata Glasc", "E"): "all_teammates",
}

# Some ally-facing abilities create a shared combat state instead of a heal or
# shield packet.  They still use the same target-selection and support ledger
# path so each protected participant receives one typed state action.
_SUPPORT_STATE_SLOTS = frozenset({("Taric", "R")})

# P1-Renata-W: Renata's Bailout (W) is the one reviewed ally-targeted cast
# whose payload is a ramping stat buff instead of a shield or a heal, so the
# shield/heal attribute scan above can never reach it.  It rides its own
# registry and reads every number from a typed ability atom or from the
# cached description prose — never from a literal here.
_SUPPORT_BUFF_SLOTS = frozenset({("Renata Glasc", "W")})

# E8c: slots whose shield the champion module authors itself (via the
# ``self_shield_events`` payload on its damage entry) instead of this
# scanner.  The scanner would otherwise re-derive the same ability from
# its cached JSON — with a rank-indexed (not level-indexed) base for
# Ambessa W and a description-marker miss that mis-targets Vex W's
# self-only Personal Space as a one-teammate packet — and double-grant
# the shield.  Modules own the exact level/stat formula and duration;
# the scanner defers so the ledger sees exactly one sourced shield.
_MODULE_AUTHORED_SHIELD_SLOTS = frozenset(
    {
        ("Ambessa", "W"),
        ("Vex", "W"),
        # E9-3: Shyvana's Inferno Aegis module authors the sourced shield
        # ('Shield Strength' + 12% bonus health + the per-nearby-champion
        # 'Increased shield per champion' increment) with an explicit
        # consumed-at-recast duration; the scanner's rank-based read of the
        # same rows would double-grant a less precise amount.
        ("Shyvana", "W"),
    }
)

# Slots whose heal the champion module or the E1 self-heal rule authors, so
# this scanner must never re-derive them.  Assigned exactly once: a second
# assignment shadows the first at import time and fails the contract test.
#
# Three shapes put a slot here.  A gated recast the scanner cannot see:
# Shyvana W's dragon-form heal (60 : 104.71 by level plus 4% : 8.47% by level
# missing health, gated on the explosion hitting a champion), Naafiri Q's
# recast riding the module's damage receipts, Taric Q priced per stocked
# charge.  A self heal both sides would grant, so one cast heals twice at
# inconsistent amounts: Sona W, Janna R, Milio R, Irelia Q, Vladimir Q,
# Volibear W, Ekko R, Gangplank W, Kha'Zix W, Tahm Kench Q.  An ally packet
# the game does not have, invented from description markers on a self-only
# ability: Sylas W, Tryndamere Q, Talon Q, Yorick Q, Kindred W, whose cached
# prose each say the champion heals THEMSELVES only.
#
# Rakan Q is deliberately NOT here: its scanner ALLY branch (rank-indexed 80)
# keeps its own amount while the champion rule owns the per-level 210 self
# heal.  See ``_SCOPE_OVERRIDES``.
#
# Sona W is in this set but its Melody shield stays scanner-owned: the
# heal-branch skip below nulls only ``heal_attr``, so "Shield Strength"
# packets still emit (the shield has no module author).
_MODULE_AUTHORED_HEAL_SLOTS = frozenset(
    {
        ("Shyvana", "W"),
        ("Naafiri", "Q"),
        ("Taric", "Q"),
        ("Sona", "W"),
        ("Janna", "R"),
        ("Milio", "R"),
        ("Irelia", "Q"),
        ("Vladimir", "Q"),
        ("Volibear", "W"),
        ("Ekko", "R"),
        ("Gangplank", "W"),
        ("Kha'Zix", "W"),
        ("Tahm Kench", "Q"),
        ("Sylas", "W"),
        ("Tryndamere", "Q"),
        ("Talon", "Q"),
        ("Yorick", "Q"),
        ("Kindred", "W"),
        # Starcall (Q) puts Rejuvenation on SORAKA ("star dust returns to
        # Soraka, granting her Rejuvenation"); the healing rule already
        # prices it as the 12 sourced ticks (``Starcall · Rejuvenation``,
        # Heal per Tick x12 == Total Heal), and the scanner re-derived the
        # same regeneration as a flat ally heal at the cast.  An ally only
        # gets Rejuvenation through Astral Infusion, whose own heal is a
        # separate row.
        ("Soraka", "Q"),
        # Phase 3 (the W3 scan): three more self-heal double-grants the
        # recipient rule alone would have kept, each already paid by the
        # ledger's own owner.
        # - Vladimir R: "heal Vladimir for each infected champion" is the
        #   healing rule's Hemoplague receipt (full amount, reduced copy
        #   attached for later roster targets).
        # - Locke W: Soul Ignition stores grey health and the recast
        #   "consumes his grey health to heal for the same amount" — the
        #   participant timeline authors that payback off the INCOMING
        #   ledger (``GREY_HEALTH_RULE_CHAMPIONS``); the cached "Heal" rows
        #   are the pool's per-level cap and its missing-health ceiling,
        #   read at rank by a scan that cannot see damage taken.
        # - Zilean R: "they revive while being healed" is the Chronoshift
        #   revive, already priced as sourced revive state through
        #   ``zilean.starting_revive_defense`` /
        #   ``defensive_effects.resolve_starting_defenses``.
        ("Vladimir", "R"),
        ("Locke", "W"),
        ("Zilean", "R"),
    }
)

# State-transition modules can own a conditional recovery packet without
# joining the self-heal registry. Sivir E creates its heal only after a
# spell-shield block, so the generic scanner must omit its cached Heal row.
# Roadmap session 1: Zilean R (Chronoshift) carries a "Heal" leveling row
# (600/850/1100 + 200% AP) that only pays out on resurrection after the
# protected champion takes fatal damage within the rune's 5s window — it is
# not a heal that fires on cast. Before this entry existed the generic scan
# matched "Heal" and emitted an unconditional "Chronoshift · Heal" packet at
# cast time (verified live: derive_ally_effects on a bare R cast returned a
# full-amount heal event with no fatal-damage gate at all), double-counting
# against the correct, already-implemented revive heal that
# ``zilean.starting_revive_defense`` feeds through
# ``StartingDefenses.revive_health_amount`` / the survival kernel (see
# tests/test_ally_support_wave2.py's ``zilr`` cases and
# tests/test_e8_followup_hooks.py's revive_source assertion). R is excluded
# here so the scanner defers entirely to the revive-conditional path.
_STATE_AUTHORED_HEAL_SLOTS = frozenset({("Sivir", "E"), ("Zilean", "R")})

# These cached descriptions state a shield lifetime. The typed duration atom
# points at the sentence that names the shield, so a preceding slow, channel,
# or attack-speed duration cannot become the shield lifetime.
_SHIELD_DURATION_ATOM_QUERIES: dict[tuple[str, str], AbilityAtomQuery] = {
    ("Annie", "E"): AbilityAtomQuery(
        source="Annie.E[0].effects[0].description",
        behavior="timing",
        evidence_prefix="active duration@",
    ),
    ("Morgana", "E"): AbilityAtomQuery(
        source="Morgana.E[0].effects[0].description",
        behavior="timing",
        evidence_prefix="active duration@",
    ),
    ("Azir", "E"): AbilityAtomQuery(
        source="Azir.E[0].effects[0].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Diana", "W"): AbilityAtomQuery(
        source="Diana.W[0].effects[0].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Ekko", "W"): AbilityAtomQuery(
        source="Ekko.W[0].effects[2].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Ivern", "E"): AbilityAtomQuery(
        source="Ivern.E[0].effects[0].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Janna", "E"): AbilityAtomQuery(
        source="Janna.E[0].effects[1].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Jarvan IV", "W"): AbilityAtomQuery(
        source="Jarvan IV.W[0].effects[1].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("K'Sante", "E"): AbilityAtomQuery(
        source="K'Sante.E[0].effects[0].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Kai'Sa", "R"): AbilityAtomQuery(
        source="Kai'Sa.R[0].effects[0].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Karma", "E"): AbilityAtomQuery(
        source="Karma.E[0].effects[0].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Kassadin", "Q"): AbilityAtomQuery(
        source="Kassadin.Q[0].effects[1].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Lee Sin", "W"): AbilityAtomQuery(
        source="Lee Sin.W[0].effects[0].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Lulu", "E"): AbilityAtomQuery(
        source="Lulu.E[0].effects[2].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Lux", "W"): AbilityAtomQuery(
        source="Lux.W[0].effects[0].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Milio", "E"): AbilityAtomQuery(
        source="Milio.E[0].effects[0].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Olaf", "W"): AbilityAtomQuery(
        source="Olaf.W[0].effects[1].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Nautilus", "W"): AbilityAtomQuery(
        source="Nautilus.W[0].effects[0].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Orianna", "E"): AbilityAtomQuery(
        source="Orianna.E[0].effects[1].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Rakan", "E"): AbilityAtomQuery(
        source="Rakan.E[0].effects[0].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Riven", "E"): AbilityAtomQuery(
        source="Riven.E[0].effects[0].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Rumble", "W"): AbilityAtomQuery(
        source="Rumble.W[0].effects[0].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Renata Glasc", "E"): AbilityAtomQuery(
        source="Renata Glasc.E[0].effects[1].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Senna", "R"): AbilityAtomQuery(
        source="Senna.R[0].effects[2].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Seraphine", "W"): AbilityAtomQuery(
        source="Seraphine.W[0].effects[0].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Sona", "W"): AbilityAtomQuery(
        source="Sona.W[0].effects[1].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Taric", "W"): AbilityAtomQuery(
        source="Taric.W[0].effects[1].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Thresh", "W"): AbilityAtomQuery(
        source="Thresh.W[0].effects[1].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Udyr", "W"): AbilityAtomQuery(
        source="Udyr.W[0].effects[1].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Urgot", "E"): AbilityAtomQuery(
        source="Urgot.E[0].effects[0].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Yuumi", "E"): AbilityAtomQuery(
        source="Yuumi.E[0].effects[0].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
    ("Yone", "W"): AbilityAtomQuery(
        source="Yone.W[0].effects[1].description",
        behavior="timing",
        evidence_prefix="shield duration@",
    ),
}

_INVULNERABILITY_ATOM_QUERIES: dict[
    tuple[str, str], tuple[AbilityAtomQuery, AbilityAtomQuery]
] = {
    ("Taric", "R"): (
        AbilityAtomQuery(
            source="Taric.R[0].effects[0].description",
            behavior="timing",
            evidence_prefix="invulnerability delay@",
        ),
        AbilityAtomQuery(
            source="Taric.R[0].effects[0].description",
            behavior="timing",
            evidence_prefix="invulnerability duration@",
        ),
    ),
}


def _has_support_attributes(champion_data: dict[str, Any]) -> bool:
    memo_key = (data_version(), id(champion_data))
    memo = _SUPPORT_ATTRS_MEMO.get(memo_key)
    if memo is not None and memo[0] is champion_data:
        return memo[1]
    found = any(
        leveling.get("attribute") in _SUPPORT_ATTRIBUTES
        for slot in _SUPPORT_SLOTS
        for effect in _ability(champion_data, slot).get("effects", [])
        for leveling in effect.get("leveling", [])
    )
    store_for_generation(_SUPPORT_ATTRS_MEMO, memo_key, (champion_data, found))
    return found


# The attribute names and target-scope markers below are pure cached-JSON
# facts per ability, so they are derived once per ability object and cache
# generation — ``(data_version(), id(ability))``, identity-verified on every
# hit (D-49) — instead of per optimizer candidate.  The write goes through
# ``store_for_generation``, which also drops the superseded generation that an
# unbounded version-prefixed memo would otherwise retain along with every
# cached dict it references.
_SUPPORT_PROFILE_MEMO: dict[tuple[int, int], tuple[dict, tuple]] = {}


def _sourced_cast_time(cast: dict[str, Any], *, slot: str) -> float:
    """Return one finite authored cast time; never default a missing timestamp."""
    if "time" not in cast:
        raise ValueError(f"Support cast {slot} is missing its sourced time")
    value = cast["time"]
    if isinstance(value, bool):
        raise ValueError(f"Support cast {slot} time must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Support cast {slot} time must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"Support cast {slot} time must be finite")
    return parsed


def _support_profile(
    ability: dict[str, Any],
) -> tuple[str | None, str | None, bool, str, dict[str, str]]:
    memo_key = (data_version(), id(ability))
    memo = _SUPPORT_PROFILE_MEMO.get(memo_key)
    if memo is not None and memo[0] is ability:
        return memo[1]
    shield_attr = _first_attribute(ability, _SHIELD_ATTRIBUTES)
    heal_attr = _first_attribute(ability, _HEAL_ATTRIBUTES)
    description = " ".join(
        str(effect.get("description", "")) for effect in ability.get("effects", [])
    ).lower()
    target_self = any(
        marker in description
        for marker in (
            "shields herself",
            "shields himself",
            "shields themselves",
            "shield themselves",
            "grants herself",
            "granting herself",
            "grants himself",
            "granting himself",
            "grants themselves",
            "granting themselves",
            "or herself",
            "or himself",
            "or themselves",
            "herself or",
            "himself or",
            "themselves or",
            "around herself",
            "around himself",
            "around themselves",
            "heals herself",
            "heals himself",
            "heals themselves",
            "healing herself",
            "healing himself",
            "healing themselves",
            "healing and cleansing herself",
            "healing and cleansing himself",
            "healing and cleansing themselves",
            "to herself",
            "to himself",
            "to themselves",
        )
    )
    all_teammates = any(
        marker in description
        for marker in (
            "all allied champions",
            "all allied units",
            "nearby allied champions",
            "nearby allied units",
            "nearby allies",
            "all allies",
        )
    )
    # Several reviewed support casts affect the caster and another selected
    # ally (Sona W), or the caster plus every nearby ally (Soraka R, Janna R,
    # Seraphine W, Milio R).  Keep those scopes explicit so the roster
    # resolver does not silently drop the self packet or treat a self-only
    # cast as an area effect.
    if target_self and all_teammates:
        target_scope = "self_and_all_teammates"
    elif target_self and any(
        f"{pronoun} and" in description
        for pronoun in ("herself", "himself", "themselves")
    ):
        target_scope = "self_and_one_teammate"
    elif target_self and any(
        f"{pronoun} or" in description or f"or {pronoun}" in description
        for pronoun in ("herself", "himself", "themselves")
    ):
        # Self-or-target casts (Karma E, Orianna E) use the deterministic
        # selected-teammate branch when a roster target exists, while the
        # ledger falls back to self when no teammate is selected.
        target_scope = "one_teammate"
    elif target_self:
        target_scope = "self"
    elif all_teammates:
        target_scope = "all_teammates"
    else:
        target_scope = "one_teammate"
    profile = (shield_attr, heal_attr, target_self, target_scope, _row_prose(ability))
    store_for_generation(_SUPPORT_PROFILE_MEMO, memo_key, (ability, profile))
    return profile


def _scales_off_the_recipient(ability: dict[str, Any], attribute: str) -> bool:
    """Whether a row's amount is a share of the RECIPIENT's own stats.

    A support row's "target" is the recipient, not an enemy: Taric W's Bastion
    is "7 / 8 / 9 / 10 / 11% of target's maximum health", each recipient off
    their own.
    """
    leveling = find_named_leveling(ability, attribute)
    return leveling is not None and any(
        "target's" in unit
        for modifier in leveling.get("modifiers", [])
        for unit in modifier.get("units", [])
    )


def _caster_as_recipient(stats: dict[str, float]) -> dict[str, float]:
    """The one recipient whose stats a scan holds: only the caster's maximum health."""
    return {"target_max_health": float(stats.get("health", 0.0) or 0.0)}


def _recipient_max_health_row(ability: dict[str, Any], attribute: str) -> bool:
    """Whether a row is a plain share of the recipient's MAXIMUM health.

    That shape survives leaving the scan: maximum health is a build stat the
    coupled composition holds for every recipient, so the packet can carry
    its ratio and be priced per ally.  A share of the recipient's MISSING or
    current health (Seraphine W) is live walk state and stays withheld.
    """
    leveling = find_named_leveling(ability, attribute)
    if leveling is None:
        return False
    modifiers = leveling.get("modifiers") or []
    if len(modifiers) != 1:
        return False
    units = modifiers[0].get("units") or []
    return bool(units) and all(
        str(unit).strip() == "% of target's maximum health" for unit in units
    )


def recipient_max_health_ratio(
    ability: dict[str, Any], attribute: str, rank: int
) -> float:
    """One rank's share of the recipient's maximum health, as a fraction."""
    leveling = find_named_leveling(ability, attribute)
    values = (leveling or {}).get("modifiers", [{}])[0].get("values") or []
    if not values:
        return 0.0
    return float(values[min(max(int(rank), 1), len(values)) - 1]) / 100.0


@dataclass(frozen=True)
class _Row:
    """One resolved leveling row: what it grants, to whom, from which cast."""

    attribute: str
    kind: str
    target_scope: str
    target_self: bool
    recipient_scaled: bool = False
    recipient_max_health: bool = False


def _slot_rows(champion: str, slot: str, ability: dict[str, Any]) -> list[_Row]:
    """The shield and heal rows one slot publishes, or none.

    Every registry that can silence or redirect a row is applied here, in the
    order a reviewer reads them: module-authored slots first, then the sourced
    per-champion attribute and scope overrides, then the two fail-closed reads
    of the row's own declaring sentence.
    """
    if (champion, slot) in _MODULE_AUTHORED_SHIELD_SLOTS:
        # E8c: a module-authored shield slot is the module's exact receipt
        # (level-indexed bases, stat scalings, and sourced duration).  The
        # scanner defers to it so the ledger never grants the same shield
        # twice from two derivations of one ability (Shyvana W is in both
        # registries — the shield set alone skips the whole slot).
        return []
    shield_attr, heal_attr, target_self, target_scope, row_prose = _support_profile(
        ability
    )
    champion_key = (champion, slot)
    # E8d follow-up / P1-3: a sourced per-champion attribute override wins
    # over the generic lookup (Bard W's fully-charged shrine; Lux W's two
    # stacked shields == Maximum Shield).
    heal_attr = _CHAMPION_HEAL_ATTR.get(champion_key, heal_attr)
    shield_attr = _CHAMPION_SHIELD_ATTR.get(champion_key, shield_attr)
    if champion_key in _MODULE_AUTHORED_HEAL_SLOTS | _STATE_AUTHORED_HEAL_SLOTS:
        # A module or healing-rule authored heal slot is the exact receipt
        # (level-indexed bases, missing-health terms, a
        # dragon-form gate and Wound/first-cast gates the scanner cannot
        # see).  Only the HEAL row defers: a shield row on the same slot
        # stays scanner-owned unless the shield registry claims the whole
        # slot (Sona W's Melody shield has no module author).
        heal_attr = None
    if heal_attr == "Heal Per Tick":
        # A per-tick entry is not a complete heal packet without its authored
        # duration/tick cadence; fail closed rather than multiply a guess.
        heal_attr = None
    if heal_attr is not None and not _declares_a_heal(row_prose.get(heal_attr, "")):
        heal_attr = None
    # A sourced per-champion target-scope override wins over
    # the description markers (Yuumi E's attached anchor).
    override = _SCOPE_OVERRIDES.get(champion_key)
    rows: list[_Row] = []
    for attribute, kind in ((shield_attr, "shield"), (heal_attr, "heal")):
        if attribute is None:
            continue
        resolved = _row_target(
            row_prose.get(attribute, ""),
            champion=champion,
            scope=target_scope,
            target_self=target_self,
            override=override,
        )
        if resolved is None:
            # The declaring sentence names no recipient; see ``_row_target``.
            continue
        scope, resolved_self = resolved
        # Fail closed at the emitter.  A typo or novel scope must
        # name the champion+slot at the source instead of silently redirecting
        # the packet to teammate zero in the coupled resolver.
        if scope not in SUPPORT_TARGET_RESOLUTION_SCOPES:
            raise ValueError(
                "Unsupported support target_scope "
                f"{scope!r} for {champion} {slot} "
                f"from source {ability.get('name', slot)!r}; supported scopes: "
                f"{sorted(SUPPORT_TARGET_RESOLUTION_SCOPES)}"
            )
        recipient_scaled = _scales_off_the_recipient(ability, attribute)
        recipient_max_health = recipient_scaled and _recipient_max_health_row(
            ability, attribute
        )
        if recipient_scaled and not recipient_max_health:
            # Only one recipient's stats are in reach, so only the caster's
            # copy has a sourced amount; the ally copy is withheld rather
            # than granted the caster's number.  A copy that resolves to
            # nothing even against the caster is refused by the emitter.
            # A plain maximum-health share is the exception: it keeps its
            # sourced scope and carries its ratio to the composition, which
            # holds every recipient's maximum health.
            scope, resolved_self = "self", True
        # ``target_self`` is the resolver's fallback for a teammate-less
        # roster and only a shield row carries it: a heal packet is always
        # granted outward, and the caster's own copy rides its scope.
        rows.append(
            _Row(
                attribute,
                kind,
                scope,
                kind == "shield" and resolved_self,
                recipient_scaled,
                recipient_max_health,
            )
        )
    return rows


def _slot_rank(
    champion_data: dict[str, Any],
    slot: str,
    level: int,
    requested_ranks: dict[str, int],
) -> int:
    """The rank this slot is cast at: the request's, else the skill order's."""
    default_rank = get_ability_rank(slot, level, champion_data.get("name", ""))
    try:
        return max(0, int(requested_ranks.get(slot, default_rank)))
    except (TypeError, ValueError):
        return default_rank


def _atom_receipt(atom: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the provenance fields that identify one runtime atom."""
    return {
        key: atom[key]
        for key in (
            "atom_id",
            "behavior",
            "source",
            "values",
            "units",
            "evidence",
            "hash",
        )
    }


def _shield_duration_metadata(
    champion_data: dict[str, Any], slot: str
) -> dict[str, Any]:
    """Return a reviewed shield lifetime from its typed duration atom."""
    champion_name = str(champion_data.get("name", ""))
    query = _SHIELD_DURATION_ATOM_QUERIES.get((champion_name, slot))
    if query is None:
        return {}
    atom = required_ability_atom(
        champion_name,
        champion_data,
        slot,
        query=query,
    )
    duration = ranked_ability_atom_value(atom, 1, source=query.source)
    if atom.get("units") != ["s"]:
        raise ValueError(
            f"{champion_name} {slot} shield duration atom must use seconds"
        )
    return {"duration": duration, "duration_atom": _atom_receipt(atom)}


def _invulnerability_timing_metadata(
    champion_data: dict[str, Any], slot: str
) -> dict[str, Any]:
    """Return a typed descent delay and invulnerability window."""
    champion_name = str(champion_data.get("name", ""))
    queries = _INVULNERABILITY_ATOM_QUERIES.get((champion_name, slot))
    if queries is None:
        raise ValueError(f"{champion_name} {slot} has no invulnerability timing atoms")
    delay_query, duration_query = queries
    delay_atom = required_ability_atom(
        champion_name,
        champion_data,
        slot,
        query=delay_query,
    )
    duration_atom = required_ability_atom(
        champion_name,
        champion_data,
        slot,
        query=duration_query,
    )
    for label, atom in (("delay", delay_atom), ("duration", duration_atom)):
        if atom.get("units") != ["s"]:
            raise ValueError(
                f"{champion_name} {slot} invulnerability {label} atom "
                "must use seconds"
            )
    return {
        "activation_delay": ranked_ability_atom_value(
            delay_atom, 1, source=delay_query.source
        ),
        "duration": ranked_ability_atom_value(
            duration_atom, 1, source=duration_query.source
        ),
        "activation_delay_atom": _atom_receipt(delay_atom),
        "duration_atom": _atom_receipt(duration_atom),
    }


# P1-Renata-W: every Bailout number below is read from one of these typed
# sources.  The four ramping bonuses are ranked leveling atoms (modifier 0
# is the flat percent, modifier 1 the per-100-AP percent); the active
# window is the timing atom; the takedown-refresh window, the post-takedown
# health, and the burn-stop rule are matched out of the cached description
# prose.  A missing row raises instead of falling back to a literal.
_BAILOUT_RAMP_ATTRIBUTES = (
    ("bonus_attack_speed_percent", "Bonus Attack Speed"),
    ("maximum_bonus_attack_speed_percent", "Maximum Bonus Attack Speed"),
    ("bonus_move_speed_percent", "Bonus Movement Speed"),
    ("maximum_bonus_move_speed_percent", "Maximum Bonus Movement Speed"),
)
_BAILOUT_DURATION_QUERY = AbilityAtomQuery(
    source="Renata.W[0].effects[0].description",
    behavior="timing",
    evidence_prefix="active duration@",
)
_BAILOUT_TAKEDOWN_WINDOW_PATTERN = re.compile(
    r"takedown against an enemy champion within "
    r"(?P<seconds>\d+(?:\.\d+)?) seconds of damaging them"
)
_BAILOUT_TAKEDOWN_HEALTH_PATTERN = re.compile(
    r"setting their current health to (?P<percent>\d+(?:\.\d+)?)% "
    r"of their maximum health"
)
_BAILOUT_BURN_STOP_MARKER = (
    "burn will stop once the target scores a takedown against an enemy champion"
)
# P1-Renata-W (lethal half): the cached prose that states the rules the
# runtime WITHHOLDS.  Each marker/pattern must still match, so a source
# rewrite that drops the rule breaks the packet instead of silently
# changing what the denial claims to be withholding.
_BAILOUT_RESTORE_PATTERN = re.compile(
    r"restored to (?P<percent>\d+(?:\.\d+)?)% of their maximum health"
)
_BAILOUT_ONCE_PER_APPLICATION_MARKER = "may occur only once per application of Bailout"
#: The cardinality the marker above states in words ("only once").  It is a
#: rule count, not a tunable: the marker must be present or the packet
#: raises, so the count can never outlive the sentence that states it.
_BAILOUT_ACTIVATIONS_PER_APPLICATION = 1
_BAILOUT_PRECEDENCE_MARKER = "takes priority over all"
_BAILOUT_PRECEDENCE_TERMS = ("resurrection", "zombie state")
_BAILOUT_PRECEDENCE_VALUE = "over_all_resurrection_and_zombie_state_effects"
_BAILOUT_DENIAL_SOURCE = "Bailout · Lethal-Damage Restore"
_BAILOUT_W_SOURCE_LABEL = "Renata Glasc W ability entry"


def _bailout_authority() -> Mapping[str, Any]:
    """Return the Renata module's local W source-status receipt."""
    # pylint: disable=import-outside-toplevel
    from .champions import renata_glasc

    return renata_glasc.BAILOUT_AUTHORITY


def _bailout_denied_components() -> tuple[str, ...]:
    """Return the survival components the burn-authority conflict withholds.

    The module's authority receipt owns the list, so the public denial rows
    and the module's own documented coverage can never drift apart.
    """
    components = tuple(
        str(component)
        for component in _bailout_authority().get("denied_survival_components", ())
    )
    if not components:
        raise ValueError(
            "renata_glasc.BAILOUT_AUTHORITY must name at least one "
            "denied_survival_components entry while W is runtime-unavailable"
        )
    return components


def _bailout_w_source() -> Mapping[str, Any]:
    """Return the reviewed W wiki-entry receipt (url + revision)."""
    # pylint: disable=import-outside-toplevel
    from .champions import renata_glasc

    for entry in renata_glasc.SOURCES:
        if str(entry.get("label", "")) == _BAILOUT_W_SOURCE_LABEL:
            return entry
    raise KeyError(
        "Renata Glasc W denial receipt needs the reviewed source row "
        f"labelled {_BAILOUT_W_SOURCE_LABEL!r}; renata_glasc.SOURCES has "
        f"{sorted(str(entry.get('label', '')) for entry in renata_glasc.SOURCES)}"
    )


def _bailout_ramp_metadata(
    champion_data: dict[str, Any],
    ability: dict[str, Any],
    rank: int,
    stats: Mapping[str, float],
) -> dict[str, Any]:
    """Return Bailout's typed ramping bonuses, window, and takedown rules.

    The lethal-damage half of Bailout (the restore to full health and the
    maximum-health burn that follows it) is NOT published here: the local
    Wiki cache and the local game binary disagree on the burn cadence and
    on its damage class, so the packet carries the module's named denial
    receipt instead of a survival number nothing can source.
    """
    atom_key = str(champion_data.get("key") or champion_data.get("name", ""))
    champion_label = str(champion_data.get("name", ""))
    ability_power = float(stats.get("ability_power", 0.0) or 0.0)
    metadata: dict[str, Any] = {}
    atoms: list[dict[str, Any]] = []
    for field_name, attribute in _BAILOUT_RAMP_ATTRIBUTES:
        base, base_atom = required_ranked_attribute_atom(
            atom_key, champion_data, "W", attribute, rank, modifier_index=0
        )
        ratio, ratio_atom = required_ranked_attribute_atom(
            atom_key, champion_data, "W", attribute, rank, modifier_index=1
        )
        for expected, atom in (("%", base_atom), ("% per 100 AP", ratio_atom)):
            units = atom.get("units", ())
            if len(units) < rank or units[rank - 1] != expected:
                raise ValueError(
                    f"{champion_label} W {attribute} atom "
                    f"{atom.get('source', '')!r} must use {expected!r} units"
                )
        metadata[field_name] = base + ratio * ability_power / 100.0
        atoms.append(_atom_receipt(base_atom))
        atoms.append(_atom_receipt(ratio_atom))

    duration_atom = required_ability_atom(
        atom_key, champion_data, "W", query=_BAILOUT_DURATION_QUERY
    )
    if duration_atom.get("units") != ["s"]:
        raise ValueError(f"{champion_label} W active duration atom must use seconds")
    duration = ranked_ability_atom_value(
        duration_atom, 1, source=_BAILOUT_DURATION_QUERY.source
    )
    atoms.append(_atom_receipt(duration_atom))

    effects = ability.get("effects", [])
    active = str(effects[0].get("description", "")) if effects else ""
    lethal = str(effects[1].get("description", "")) if len(effects) > 1 else ""
    window_match = _BAILOUT_TAKEDOWN_WINDOW_PATTERN.search(active)
    if window_match is None:
        raise ValueError(
            f"{champion_label} W takedown-refresh window is missing from the "
            "cached active description"
        )
    window_seconds = float(window_match.group("seconds"))
    health_match = _BAILOUT_TAKEDOWN_HEALTH_PATTERN.search(lethal)
    if health_match is None:
        raise ValueError(
            f"{champion_label} W post-takedown health is missing from the "
            "cached lethal-damage description"
        )
    if _BAILOUT_BURN_STOP_MARKER not in lethal:
        raise ValueError(
            f"{champion_label} W burn-stop-on-takedown rule is missing from "
            "the cached lethal-damage description"
        )
    window_label = f"{window_seconds:g}".replace(".", "_") if window_seconds else "0"

    return {
        **metadata,
        "duration": duration,
        # "Bailout's duration resets whenever the target scores a takedown"
        # — the reset restores the same sourced active window.
        "refresh_duration": duration,
        "refresh_trigger": f"takedown_within_{window_label}_seconds",
        "takedown_window": window_seconds,
        "takedown_stops_burn": True,
        "takedown_health_ratio": float(health_match.group("percent")) / 100.0,
        **_bailout_withheld_lethal_shape(champion_label, ability, lethal),
        "source_atoms": atoms,
    }


def _bailout_withheld_lethal_shape(
    champion_label: str, ability: Mapping[str, Any], lethal: str
) -> dict[str, Any]:
    """Return the sourced SHAPE of Bailout's withheld lethal-damage half.

    The lethal half stays fail-closed: the packet names the denial rather
    than publishing an unsourced survival gain.  The fields below are the
    shape of what is withheld (ratio, activation cap, precedence) — never an
    applied number — and every cached rule they describe must still be
    present, so a source rewrite that drops one breaks the packet instead of
    silently changing what the denial claims to be withholding.
    """
    restore_match = _BAILOUT_RESTORE_PATTERN.search(lethal)
    if restore_match is None:
        raise ValueError(
            f"{champion_label} W lethal-damage restore ratio is missing from "
            "the cached lethal-damage description"
        )
    if _BAILOUT_ONCE_PER_APPLICATION_MARKER not in lethal:
        raise ValueError(
            f"{champion_label} W one-activation-per-application rule is "
            "missing from the cached lethal-damage description"
        )
    notes = str(ability.get("notes", "") or "")
    if _BAILOUT_PRECEDENCE_MARKER not in notes or any(
        term not in notes for term in _BAILOUT_PRECEDENCE_TERMS
    ):
        raise ValueError(
            f"{champion_label} W resurrection/zombie-state precedence rule "
            "is missing from the cached ability notes"
        )

    authority = _bailout_authority()
    if bool(authority.get("runtime_available")):
        raise ValueError(
            f"{champion_label} W lethal-damage restore is marked "
            "runtime_available but no survival contract implements it"
        )

    return {
        "lethal_restore_available": False,
        "lethal_restore_denial": str(authority.get("reason", "")),
        "lethal_restore_ratio": float(restore_match.group("percent")) / 100.0,
        "lethal_activations_per_application": _BAILOUT_ACTIVATIONS_PER_APPLICATION,
        "resurrection_precedence": _BAILOUT_PRECEDENCE_VALUE,
        "denied_survival_components": list(_bailout_denied_components()),
    }


def _bailout_denial_rows(
    ramp: Mapping[str, Any],
    *,
    time: float,
    target_self: bool,
    target_scope: str,
    target_selection_key: str,
) -> list[dict[str, Any]]:
    """Return one public denial receipt per withheld Bailout component.

    Bailout's lethal-damage half cannot be published (see
    ``renata_glasc.BAILOUT_AUTHORITY``), and a covered participant's death,
    survival, or Guardian Angel resurrection would otherwise be reported as
    if Bailout were not on them at all.  These rows are RECEIPTS, not
    applied packets: ``_support_effect_templates`` routes ``item_denial``
    out of the applied stream into the public denial section, so the answer
    names the refusal instead of silently standing in for it.

    This function only sets ``target_self``/``target_scope``/
    ``target_selection_key`` — it does not know which participant the cast
    resolved to. The caller (``participant_timeline``'s support-effect
    loop, around the ``resolved_template = {**resolved_effect, "attacker":
    ..., "target": ...}`` assembly) resolves ``target_self``/
    ``target_scope`` through ``_support_target_ids`` and merges the
    concrete ``attacker``/``target`` participant-id keys onto each denial
    row downstream, alongside every other support-effect template.
    """
    source_entry = _bailout_w_source()
    reason = str(ramp.get("lethal_restore_denial", ""))
    if not reason:
        raise ValueError(
            "Renata Glasc W denial receipt requires a named reason from "
            "renata_glasc.BAILOUT_AUTHORITY"
        )
    return [
        {
            "time": time,
            "kind": PacketKind.ITEM_DENIAL.value,
            "source": _BAILOUT_DENIAL_SOURCE,
            "reason": reason,
            "denied_component": component,
            "source_url": str(source_entry.get("url", "")),
            "source_revision_id": source_entry.get("revision_id"),
            "slot": "W",
            "target_self": target_self,
            "target_scope": target_scope,
            "target_selection_key": target_selection_key,
        }
        for component in _bailout_denied_components()
    ]


def _morgana_black_shield_metadata(
    champion_data: dict[str, Any],
    ability: dict[str, Any],
    rank: int,
    stats: Mapping[str, float],
) -> dict[str, Any]:
    """Return Black Shield's typed pool, duration, and source receipts."""
    champion_name = str(champion_data.get("name", ""))
    strength_source = "Morgana.E[0].effects[0].leveling[0].modifiers[0]"
    strength_atom = required_ability_atom(
        champion_name,
        champion_data,
        "E",
        query=AbilityAtomQuery(
            source=strength_source,
            behavior="ability",
            evidence_prefix="Magic Shield Strength@",
        ),
    )
    strength_base = ranked_ability_atom_value(
        strength_atom, rank, source=strength_source
    )
    base_stats = dict(stats)
    base_stats["ability_power"] = 0.0
    parsed_base = extract_named(ability, "Magic Shield Strength", rank, base_stats, {})
    if abs(parsed_base - strength_base) > 1e-9:
        raise ValueError(
            "Morgana E Magic Shield Strength atom disagrees with cached ability data"
        )

    duration_metadata = _shield_duration_metadata(champion_data, "E")
    return {
        **duration_metadata,
        "shield_pool": "magic",
        "crowd_control_immunity_while_shield": True,
        "crowd_control_immunity_source": str(ability.get("name", "Black Shield")),
        "source_atom": _atom_receipt(strength_atom),
    }


def _target_max_health_shield_metadata(
    champion_data: dict[str, Any],
    ability: dict[str, Any],
    slot: str,
    attribute: str,
    rank: int,
) -> dict[str, Any]:
    """Return a typed target-health formula when the source names one."""
    champion_name = str(champion_data.get("name", ""))
    for effect_index, effect in enumerate(ability.get("effects", [])):
        for leveling_index, leveling in enumerate(effect.get("leveling", [])):
            if leveling.get("attribute") != attribute:
                continue
            for modifier_index, modifier in enumerate(leveling.get("modifiers", [])):
                units = [
                    str(unit).strip().lower() for unit in modifier.get("units", [])
                ]
                if not units or any(
                    unit != "% of target's maximum health" for unit in units
                ):
                    continue
                source = (
                    f"{champion_name}.{slot}[0].effects[{effect_index}]"
                    f".leveling[{leveling_index}].modifiers[{modifier_index}]"
                )
                atom = required_ability_atom(
                    champion_name,
                    champion_data,
                    slot,
                    query=AbilityAtomQuery(
                        source=source,
                        behavior="ability",
                        evidence_prefix=f"{attribute}@",
                    ),
                )
                ratio = ranked_ability_atom_value(atom, rank, source=source) / 100.0

                def amount_formula(
                    _current_health: float,
                    maximum_health: float,
                    ratio: float = ratio,
                ) -> float:
                    return max(0.0, maximum_health) * ratio

                return {
                    "amount": 0.0,
                    "amount_formula": amount_formula,
                    "amount_formula_atom": _atom_receipt(atom),
                }
    return {}


def _target_missing_health_heal_metadata(
    champion_data: dict[str, Any],
    slot: str,
    attribute: str,
    rank: int,
) -> dict[str, Any]:
    """Return a typed live missing-health formula when the source names it."""
    champion_name = str(champion_data.get("name", ""))
    value, atom = required_ranked_attribute_atom(
        champion_name,
        champion_data,
        slot,
        attribute,
        rank,
    )
    units = [str(unit).strip().lower() for unit in atom.get("units", [])]
    if not units or any(unit != "% of target's missing health" for unit in units):
        raise ValueError(
            f"{champion_name} {slot} {attribute} atom must use target missing health"
        )
    ratio = value / 100.0

    def amount_formula(
        current_health: float,
        maximum_health: float,
        ratio: float = ratio,
    ) -> float:
        return max(0.0, maximum_health - current_health) * ratio

    return {
        "amount": 0.0,
        "amount_formula": amount_formula,
        "amount_formula_atom": _atom_receipt(atom),
    }


# ---------------------------------------------------------------------------
# Wave-2 champion follow-up packets (HANDOVER 8.5): sourced bounce and
# best-friend riders that ride the base scanner packet of the same cast.
# Every number comes from the cached leveling rows / typed atoms below; the
# two prose coefficients are quoted from the cached descriptions with the
# same documentation style as healing.py's E1 rules and renata_glasc.py.
# ---------------------------------------------------------------------------

# Nami W (Ebb and Flow) bounce prose — cached
# ``Nami.W[0].effects[1].description``: "each bounce modifying the
# effectiveness of the next by -20% (+ 15% per 100 AP)".  The reduction is
# per-bounce off the ORIGINAL first-target value: the sourced "Minimum
# Heal" row is exactly 60% of the "Heal" row at every rank (93 = 0.6 x 155
# at rank 5), so the second bounce keeps 1 - 2 x 0.20 = 60% at 0 AP — the
# sourced Minimum Heal row is the documented floor, exactly as the E1 rule
# floors the first bounce.
_NAMI_BOUNCE_REDUCTION_PER_BOUNCE = 0.20
_NAMI_BOUNCE_AP_RELIEF_PER_100 = 0.15

# Yuumi R (Final Chapter) Best Friend bonus — cached
# ``Yuumi.R[0].effects[4].description``: "Final Chapter's heal to the Best
# Friend is increased by 30% : 60% (based on level)" with the sourced
# per-level row (30 / 35 / 40 / 45 / 50 / 55 / 60%).  The deterministic
# roster model treats the selected teammate as the anchor and Best Friend
# (the same teammate Yuumi E already targets), so the bonus rides the
# base heal packet of the same cast.
_YUUMI_R_BEST_FRIEND_QUERY = AbilityAtomQuery(
    source="Yuumi.R[0].effects[4].leveling[0].modifiers[0]",
    behavior="ability",
    evidence_prefix="Per-Level Scaling@",
)
# The conversion shield lifetime is "1.5 seconds plus the remaining
# channel duration" (cached ``Yuumi.R[0].effects[1].description``); the
# scanner lumps the sourced Total Heal at the cast, so the remaining
# channel is the full sourced 3.5s channel (``effects[0]``).
_YUUMI_R_SHIELD_DURATION_QUERY = AbilityAtomQuery(
    source="Yuumi.R[0].effects[1].description",
    behavior="timing",
    evidence_prefix="shield duration@",
)
_YUUMI_R_CHANNEL_QUERY = AbilityAtomQuery(
    source="Yuumi.R[0].effects[0].description",
    behavior="timing",
    evidence_prefix="active duration@",
)


def _clamped_per_level_fraction(atom: Mapping[str, Any], level: int) -> float:
    """Read a per-level atom row at the repo's clamped level index.

    Rows with one value per level index directly (20 values); shorter
    per-level rows (Yuumi R's 7-value Best Friend row) clamp at the last
    value — the same convention ``slotlib._modifier_value`` and the
    Renata P Leverage rule use.  The wiki bracket levels are not present
    in the cache, so the endpoints (30% at level 1, 60% at level 18) are
    exact and intermediate levels follow the established clamp.
    """
    values = atom.get("values", ())
    if not values:
        raise ValueError(f"per-level atom {atom.get('source', '')!r} has no values")
    index = min(max(level, 1) - 1, len(values) - 1)
    value = values[index]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"per-level atom {atom.get('source', '')!r} "
            f"level {level} is not numeric"
        )
    return float(value) / 100.0


def _nami_return_bounce_packet(
    champion_data: dict[str, Any],
    ability: dict[str, Any],
    slot: str,
    rank: int,
    stats: Mapping[str, float],
    base_amount: float,
    cast_time: float,
    cast_index: int,
) -> dict[str, Any]:
    """Ebb and Flow's return bounce heals the selected teammate again.

    Cast on the selected teammate, the stream bounces to the enemy and
    back; the second bounce keeps 60% + 30% per 100 AP of the original
    heal, never below the sourced "Minimum Heal" row (which is exactly the
    60% floor at every rank).  The packet has its own selection key so the
    roster UI can choose the return-bounce recipient explicitly.
    """
    _, heal_atom = required_ranked_attribute_atom(
        "Nami", champion_data, slot, "Heal", rank
    )
    _, floor_atom = required_ranked_attribute_atom(
        "Nami", champion_data, slot, "Minimum Heal", rank
    )
    floor = extract_named(ability, "Minimum Heal", rank, stats, {})
    ap = float(stats.get("ability_power", 0.0) or 0.0)
    factor = 1.0 - 2.0 * (
        _NAMI_BOUNCE_REDUCTION_PER_BOUNCE - _NAMI_BOUNCE_AP_RELIEF_PER_100 * ap / 100.0
    )
    amount = max(floor, base_amount * factor)
    return {
        "time": cast_time,
        "kind": "heal",
        "amount": amount,
        "source": "Ebb and Flow · Return Bounce",
        "slot": slot,
        "target_self": False,
        "target_scope": "one_teammate",
        "rank": rank,
        "target_selection_key": f"heal:{slot}:{cast_index}:bounce",
        "source_atoms": [_atom_receipt(heal_atom), _atom_receipt(floor_atom)],
    }


def _yuumi_best_friend_packet(
    champion_data: dict[str, Any],
    slot: str,
    level: int,
    rank: int,
    base_amount: float,
    cast_time: float,
    cast_index: int,
) -> dict[str, Any]:
    """Final Chapter's Best Friend bonus heal on the selected teammate.

    The anchor (the selected teammate) is healed for the sourced per-level
    bonus (30% : 60% based on level) of the sourced Total Heal, emitted as
    its own packet with an explicit selection key so the base and bonus
    heals stay independently targetable.
    """
    _, total_atom = required_ranked_attribute_atom(
        "Yuumi", champion_data, slot, "Total Heal", rank
    )
    bonus_atom = required_ability_atom(
        "Yuumi",
        champion_data,
        slot,
        query=_YUUMI_R_BEST_FRIEND_QUERY,
    )
    fraction = _clamped_per_level_fraction(bonus_atom, level)
    return {
        "time": cast_time,
        "kind": "heal",
        "amount": base_amount * fraction,
        "source": "Final Chapter · Best Friend Bonus",
        "slot": slot,
        "target_self": False,
        "target_scope": "one_teammate",
        "rank": rank,
        "target_selection_key": f"heal:{slot}:{cast_index}:best_friend",
        "source_atoms": [_atom_receipt(total_atom), _atom_receipt(bonus_atom)],
    }


def _yuumi_conversion_shield_packet(
    champion_data: dict[str, Any],
    heal_event: Mapping[str, Any],
    slot: str,
) -> dict[str, Any]:
    """Final Chapter's overheal-to-shield conversion for one heal packet.

    Cached ``Yuumi.R[0].effects[1].description``: "each heal instance
    beyond maximum health being converted into a shield that lasts for
    1.5 seconds plus the remaining channel duration instead".  The live
    excess ``max(0, heal - missing)`` is a shield formula the survival
    kernel evaluates against the target's current health at the packet's
    timestamp (same amount_formula path as Taric W), so the shield pool
    and expiry follow the shared shield ledger.
    """
    shield_duration_atom = required_ability_atom(
        "Yuumi",
        champion_data,
        slot,
        query=_YUUMI_R_SHIELD_DURATION_QUERY,
    )
    channel_atom = required_ability_atom(
        "Yuumi",
        champion_data,
        slot,
        query=_YUUMI_R_CHANNEL_QUERY,
    )
    duration = float(shield_duration_atom["values"][0]) + float(
        channel_atom["values"][0]
    )
    heal_amount = float(heal_event.get("amount", 0.0))

    def amount_formula(
        current_health: float,
        maximum_health: float,
        heal: float = heal_amount,
    ) -> float:
        return max(0.0, heal - max(0.0, maximum_health - current_health))

    return {
        "time": float(heal_event.get("time", 0.0)),
        "kind": "shield",
        "amount": 0.0,
        "amount_formula": amount_formula,
        "source": "Final Chapter · Overheal Conversion",
        "slot": slot,
        "target_self": False,
        "target_scope": "one_teammate",
        "rank": int(heal_event.get("rank", 0)),
        # The conversion rides the heal it converts: it shares the parent
        # heal's selection key so the roster's chosen recipient for that
        # heal packet also receives its shield (in-game the conversion
        # lands on the ally who was healed, not an independent target).
        "target_selection_key": str(heal_event.get("target_selection_key", "")),
        "duration": duration,
        "duration_atom": _atom_receipt(shield_duration_atom),
        "source_atoms": [
            _atom_receipt(shield_duration_atom),
            _atom_receipt(channel_atom),
        ],
    }


def derive_ally_effects(
    champion_data: dict[str, Any],
    level: int,
    stats: dict[str, float],
    cast_timeline: list[dict[str, Any]],
    ability_ranks: dict[str, int] | None = None,
    champion_options: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return explicit shield/heal packets and their sourced cast times.

    The timeline has no player cursor/target selection, so packets carry a
    sourced target scope for the coupled resolver to apply deterministically:
    ``self``, one selected teammate, or all selected teammates.  A missing
    scope is never silently treated as an area effect.
    """
    champion_name = str(champion_data.get("name", ""))
    if not _has_support_attributes(champion_data) and not any(
        (champion_name, slot) in _SUPPORT_STATE_SLOTS | _SUPPORT_BUFF_SLOTS
        for slot in ("Q", "W", "E", "R")
    ):
        return []
    effects: list[dict[str, Any]] = []
    requested_ranks = ability_ranks or {}
    options = champion_options or {}
    for slot in _SUPPORT_SLOTS:
        ability = _ability(champion_data, slot)
        if not ability:
            continue
        rank = _slot_rank(champion_data, slot, level, requested_ranks)
        if rank < 1:
            continue
        champion_key = (champion_name, slot)
        rows = _slot_rows(champion_name, slot, ability)
        shield_row = next((row for row in rows if row.kind == "shield"), None)
        heal_row = next((row for row in rows if row.kind == "heal"), None)
        target_self, target_scope = False, ""
        if champion_key in _SUPPORT_STATE_SLOTS | _SUPPORT_BUFF_SLOTS:
            # These two branches grant a packet that no leveling row
            # declares, so their recipient comes from the slot's own profile
            # and its sourced override rather than from a row's own
            # sentence.  Fail closed at the emitter: a typo or
            # novel scope must name the champion+slot at the source instead
            # of silently redirecting the packet to teammate zero in the
            # coupled resolver.  A row's own scope is checked in
            # ``_slot_rows``.
            _, _, target_self, target_scope, _ = _support_profile(ability)
            target_scope = _SCOPE_OVERRIDES.get(champion_key, target_scope)
            if target_scope not in SUPPORT_TARGET_RESOLUTION_SCOPES:
                raise ValueError(
                    "Unsupported support target_scope "
                    f"{target_scope!r} for {champion_name} {slot} "
                    f"from source {ability.get('name', slot)!r}; supported "
                    f"scopes: {sorted(SUPPORT_TARGET_RESOLUTION_SCOPES)}"
                )
        if champion_key in _SUPPORT_STATE_SLOTS:
            timing_metadata = _invulnerability_timing_metadata(champion_data, slot)
            casts = [event for event in cast_timeline if event.get("slot") == slot]
            for cast_index, cast in enumerate(casts):
                cast_time = _sourced_cast_time(cast, slot=slot)
                effects.append(
                    {
                        "time": cast_time + timing_metadata["activation_delay"],
                        "kind": "invulnerability",
                        "duration": timing_metadata["duration"],
                        "activation_delay": timing_metadata["activation_delay"],
                        "source": (f"{ability.get('name', slot)} · Invulnerability"),
                        "slot": slot,
                        "target_self": True,
                        "target_scope": target_scope,
                        "rank": rank,
                        "target_selection_key": f"state:{slot}:{cast_index}",
                        **timing_metadata,
                    }
                )
            continue
        if champion_key in _SUPPORT_BUFF_SLOTS:
            # P1-Renata-W: one ramping stat-buff packet per accepted cast.
            # The scope is the sourced self-or-one-ally cast, so a roster
            # fight resolves the selected teammate and a solo fight falls
            # back to the caster (``target_self``).
            ramp = _bailout_ramp_metadata(champion_data, ability, rank, stats)
            for cast_index, cast in enumerate(
                [event for event in cast_timeline if event.get("slot") == slot]
            ):
                cast_time = _sourced_cast_time(cast, slot=slot)
                selection_key = f"buff:{slot}:{cast_index}"
                effects.append(
                    {
                        "time": cast_time,
                        "kind": "stat_buff",
                        "amount": 0.0,
                        "source": f"{ability.get('name', slot)} · Chemtech Formula",
                        "slot": slot,
                        "target_self": target_self,
                        "target_scope": target_scope,
                        "rank": rank,
                        "target_selection_key": selection_key,
                        **ramp,
                    }
                )
                # The same cast's lethal-damage half is withheld: publish
                # its named denial beside the buff so the covered
                # participant's survival row is never read as complete.
                effects.extend(
                    _bailout_denial_rows(
                        ramp,
                        time=cast_time,
                        target_self=target_self,
                        target_scope=target_scope,
                        target_selection_key=selection_key,
                    )
                )
            continue
        if shield_row is None and heal_row is None:
            continue
        casts = [event for event in cast_timeline if event.get("slot") == slot]
        for cast_index, cast in enumerate(casts):
            # Validate every authored support cast, even when its resolved
            # packet is zero or intentionally omitted (for example, a
            # per-tick heal without a complete cadence).
            _sourced_cast_time(cast, slot=slot)
            if shield_row is not None:
                shield_attr = shield_row.attribute
                # The amount is resolved, never taken from the metadata's
                # placeholder: a recipient-scaled row is narrowed to the one
                # recipient the scan holds stats for, so it is PRICED against
                # the caster and granted to him alone.  The metadata's atom
                # receipt rides along, but its ``amount`` of 0.0 would
                # publish the zero this row is meant to be priced or refused
                # instead of.
                amount_metadata = {
                    key: value
                    for key, value in _target_max_health_shield_metadata(
                        champion_data, ability, slot, shield_attr, rank
                    ).items()
                    if key != "amount"
                }
                amount = extract_named(
                    ability,
                    shield_attr,
                    rank,
                    stats,
                    _caster_as_recipient(stats) if shield_row.recipient_scaled else {},
                )
                shield_scope = shield_row.target_scope
                shield_self = shield_row.target_self
                if amount > 0:
                    event = {
                        "time": _sourced_cast_time(cast, slot=slot),
                        "kind": "shield",
                        "amount": float(amount),
                        "source": f"{ability.get('name', slot)} · {shield_attr}",
                        "slot": slot,
                        "target_self": shield_self,
                        "target_scope": shield_scope,
                        "rank": rank,
                        "target_selection_key": f"shield:{slot}:{cast_index}",
                        **amount_metadata,
                    }
                    if shield_row.recipient_max_health:
                        # The amount above is the CASTER's copy.  The ratio
                        # rides the packet so the composition can price each
                        # other recipient off their own maximum health.
                        event["recipient_max_health_ratio"] = (
                            recipient_max_health_ratio(ability, shield_attr, rank)
                        )
                    if shield_attr == "Magic Shield Strength":
                        event["shield_pool"] = "magic"
                    if champion_key == ("Morgana", "E"):
                        event.update(
                            _morgana_black_shield_metadata(
                                champion_data, ability, rank, stats
                            )
                        )
                    else:
                        event.update(_shield_duration_metadata(champion_data, slot))
                    effects.append(event)
            # A module or healing-rule authored heal slot is the
            # exact receipt (level-indexed bases, missing-health terms, and a
            # dragon-form gate the scanner cannot see).  ``_slot_rows`` has
            # already dropped those rows, together with a per-tick row whose
            # cadence is not authored and a ``Heal``-named row whose sentence
            # heals nobody.
            if heal_row is not None:
                heal_attr = heal_row.attribute
                cast_time = _sourced_cast_time(cast, slot=slot)
                amount_metadata: dict[str, Any] = {}
                heal_time = cast_time
                requires_existing_shield = False
                shield_gate_time: float | None = None
                shield_gate_assumed = False
                if champion_key == ("Seraphine", "W"):
                    amount_metadata = _target_missing_health_heal_metadata(
                        champion_data, slot, heal_attr, rank
                    )
                    duration_metadata = _shield_duration_metadata(champion_data, slot)
                    duration = float(duration_metadata["duration"])
                    heal_time = cast_time + duration
                    shield_gate_assumed = (
                        bool(options.get("w_already_shielded", False))
                        and cast_index == 0
                    )
                    requires_existing_shield = not shield_gate_assumed
                    shield_gate_time = cast_time
                # Same rule as the shield row above: the resolved amount is
                # the answer and the metadata never supplies a placeholder
                # zero.  A heal scaling off the recipient's CURRENT or
                # MISSING health resolves to nothing against the caster's
                # scan-time stats, which is a refusal (Seraphine W's pulse),
                # not a zero-valued packet.
                amount_metadata.pop("amount", None)
                amount = extract_named(
                    ability,
                    heal_attr,
                    rank,
                    stats,
                    _caster_as_recipient(stats) if heal_row.recipient_scaled else {},
                )
                source_label = f"{ability.get('name', slot)} · {heal_attr}"
                if amount > 0:
                    event = {
                        "time": heal_time,
                        "kind": "heal",
                        "amount": amount,
                        "source": source_label,
                        "slot": slot,
                        "target_self": heal_row.target_self,
                        "target_scope": heal_row.target_scope,
                        "rank": rank,
                        "target_selection_key": f"heal:{slot}:{cast_index}",
                        **amount_metadata,
                    }
                    if champion_key == ("Seraphine", "W"):
                        event.update(
                            {
                                "requires_existing_shield": requires_existing_shield,
                                "shield_gate_target": "attacker",
                                "shield_gate_time": shield_gate_time,
                                "shield_gate_assumed": shield_gate_assumed,
                            }
                        )
                    effects.append(event)
                    # Wave-2 follow-up packets (HANDOVER 8.5): sourced
                    # riders on the same cast keep the base packet's amount
                    # intact (the E8d pins read the first matching packet),
                    # carry their own target-selection keys, and attach the
                    # atom receipts that prove every number.
                    if champion_key == ("Nami", "W"):
                        effects.append(
                            _nami_return_bounce_packet(
                                champion_data,
                                ability,
                                slot,
                                rank,
                                stats,
                                amount,
                                heal_time,
                                cast_index,
                            )
                        )
                    elif champion_key == ("Yuumi", "R"):
                        best_friend = _yuumi_best_friend_packet(
                            champion_data,
                            slot,
                            level,
                            rank,
                            amount,
                            heal_time,
                            cast_index,
                        )
                        effects.append(best_friend)
                        effects.append(
                            _yuumi_conversion_shield_packet(
                                champion_data,
                                event,
                                slot,
                            )
                        )
                        effects.append(
                            _yuumi_conversion_shield_packet(
                                champion_data,
                                best_friend,
                                slot,
                            )
                        )
    return sorted(effects, key=lambda event: (event["time"], event["kind"]))


_SELF_STATE_EVENT_KINDS = frozenset(
    {
        "spell_shield",
        "stasis",
        "invulnerability",
        "untargetable",
        "crowd_control",
        # A timed self damage-reduction window (Briar E charge).  The typed
        # fields the survival kernel reads ride the emitted event verbatim.
        "damage_modifier",
    }
)


def derive_self_state_effects(
    ability_damages: Mapping[str, Any],
    cast_timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expand module-authored self state atoms over accepted cast times.

    A state packet is authored by a named champion module.  The cast
    timeline supplies the only valid time for that packet.  Unknown kinds,
    invalid durations, and missing sources fail closed at the atom boundary.
    """
    effects: list[dict[str, Any]] = []
    for slot, entry in ability_damages.items():
        if not isinstance(entry, Mapping):
            continue
        raw_events = entry.get("self_state_events")
        if raw_events is None:
            continue
        if not isinstance(raw_events, list):
            raise ValueError(f"{slot} self_state_events must be a list")
        casts = [
            cast
            for cast in cast_timeline
            if isinstance(cast, Mapping) and str(cast.get("slot", "")) == str(slot)
        ]
        for cast_index, cast in enumerate(casts):
            cast_time = _sourced_cast_time(cast, slot=str(slot))
            for state_index, raw_event in enumerate(raw_events):
                if not isinstance(raw_event, Mapping):
                    raise ValueError(
                        f"{slot} self_state_events[{state_index}] must be an object"
                    )
                kind = str(raw_event.get("kind", ""))
                if kind not in _SELF_STATE_EVENT_KINDS:
                    raise ValueError(
                        f"{slot} self state kind {kind!r} is not supported"
                    )
                try:
                    duration = float(raw_event["duration"])
                    time_offset = float(raw_event.get("time_offset", 0.0) or 0.0)
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(
                        f"{slot} self state event needs numeric duration and offset"
                    ) from exc
                if not math.isfinite(duration) or duration <= 0.0:
                    raise ValueError(f"{slot} self state duration must be positive")
                if not math.isfinite(time_offset):
                    raise ValueError(f"{slot} self state time_offset must be finite")
                source = str(raw_event.get("source", ""))
                if not source:
                    raise ValueError(f"{slot} self state source is required")
                event = {
                    "time": cast_time + time_offset,
                    "kind": kind,
                    "duration": duration,
                    "source": source,
                    "source_key": str(slot),
                    "slot": str(slot),
                    "target_self": True,
                    "target_scope": "self",
                    "rank": entry.get("rank", 0),
                    "_event_id": f"self_state:{slot}:{cast_index}:{state_index}",
                }
                for field in (
                    "on_block_heal_amount",
                    "on_block_heal_delay",
                    "on_block_heal_source",
                ):
                    if field in raw_event:
                        event[field] = raw_event[field]
                # Atom receipts authored by the champion module (Sivir E:
                # duration + Heal atoms) ride the arm packet so the kernel
                # contract and the public receipt can prove the source.
                if "source_atoms" in raw_event:
                    atoms = raw_event["source_atoms"]
                    if not isinstance(atoms, list) or not all(
                        isinstance(atom, Mapping) for atom in atoms
                    ):
                        raise ValueError(
                            f"{slot} self state source_atoms must be a list "
                            "of atom objects"
                        )
                    event["source_atoms"] = [dict(atom) for atom in atoms]
                # Timed damage modifiers carry their typed kernel fields
                # (multiplier, all_sources, damage_reduction, persistent,
                # next_event_only, owner/source routing, resistance
                # reduction) plus the source-atom receipts so the public
                # support receipt can prove where each number came from.
                # Invalid numeric payloads fail closed at the atom boundary
                # exactly like a missing duration or source.
                for field in (
                    "multiplier",
                    "amount",
                    "armor_reduction_percent",
                    "mr_reduction_percent",
                ):
                    if field in raw_event:
                        try:
                            number = float(raw_event[field])
                        except (TypeError, ValueError) as exc:
                            raise ValueError(
                                f"{slot} self state {field} must be numeric"
                            ) from exc
                        if not math.isfinite(number):
                            raise ValueError(
                                f"{slot} self state {field} must be finite"
                            )
                        event[field] = number
                # The arm rank a module declares when its kind does
                # not decide it (Briar's E reduction is an aura, not
                # a triggered debuff).  A member of the closed
                # vocabulary or nothing: an author may choose a rank,
                # never invent an ordering.
                if SUPPORT_RANK_KEY in raw_event:
                    try:
                        event[SUPPORT_RANK_KEY] = TransitionRank(
                            raw_event[SUPPORT_RANK_KEY]
                        )
                    except ValueError as exc:
                        raise ValueError(
                            f"{slot} self state {SUPPORT_RANK_KEY} must be "
                            "a TransitionRank member"
                        ) from exc
                for field in (
                    "all_sources",
                    "damage_reduction",
                    "persistent",
                    "next_event_only",
                    "owner",
                    "source_participant",
                    "resistance_type",
                    # D-04: a damage_modifier names its classes on the
                    # module entry; the kernel refuses an empty declaration.
                    "damage_classes",
                    "attack_classes",
                ):
                    if field in raw_event:
                        event[field] = raw_event[field]
                if "source_atoms" in raw_event:
                    atoms = raw_event["source_atoms"]
                    if not isinstance(atoms, list) or not all(
                        isinstance(atom, Mapping) for atom in atoms
                    ):
                        raise ValueError(
                            f"{slot} self state source_atoms must be a list of atoms"
                        )
                    event["source_atoms"] = [dict(atom) for atom in atoms]
                effects.append(event)
    return sorted(
        effects,
        key=lambda event: (
            float(event["time"]),
            str(event["source_key"]),
            str(event["_event_id"]),
        ),
    )
