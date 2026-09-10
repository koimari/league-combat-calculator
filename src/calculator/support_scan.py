"""Which champion slots the cached rows say heal or shield an ally, and the profile that
answer folds into."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

from .data_registry import data_version, store_for_generation


def _ability(data: Mapping[str, Any], slot: str) -> dict[str, Any]:
    entries = data.get("abilities", {}).get(slot, [])
    return entries[0] if entries and isinstance(entries[0], dict) else {}


def _first_attribute(ability: Mapping[str, Any], names: tuple[str, ...]) -> str | None:
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


def _row_prose(ability: Mapping[str, Any]) -> dict[str, str]:
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


def _sourced_cast_time(cast: Mapping[str, Any], *, slot: str) -> float:
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
