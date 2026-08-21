"""Sourced ally-targeted shields/heals from champion ability packets."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from .capabilities import SUPPORT_TARGET_RESOLUTION_SCOPES
from .data_registry import data_version, store_for_generation
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

    The sentence names an ally, so the row leaves the caster at the scope
    the whole ability resolved; or it names only the caster, so the row is
    a self grant; or it names neither recipient, and the row is refused —
    a recipient nobody sourced is not a teammate by default.

    That is what "Ekko W shields himself" and "Ekko W heals an ally" turn
    on: Parallel Convergence says "it detonates to grant *him* a shield" —
    Ekko named, no ally anywhere in the ability — so the shield is his and
    nothing leaves him.  Defaulting sent it to a teammate instead.  An
    explicit per-champion override still wins (Yuumi E's attached anchor,
    Kindred R's "all targetable units").
    """
    if override is not None:
        return override, target_self
    if _ALLY_PROSE.search(prose):
        return scope, target_self
    if champion.lower() in prose or _CASTER_PROSE.search(prose):
        return "self", True
    return None


def _declares_a_heal(prose: str) -> bool:
    """Whether the sentence declaring a ``Heal``-named row states a heal.

    The wiki's ability template names the last unlabelled row of a sentence
    ``Heal`` whatever it measures: Mordekaiser W's is the Potential Shield
    *decay rate* ("decays by 8 : 25 (based on level) every second") and Udyr
    Q's is the lightning strikes' minimum-damage floor.  Neither sentence
    heals anyone, so neither becomes a heal packet.
    """
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
    # E8d follow-up: Bard W (Caretaker's Shrine) heals scale with charge
    # time between these two sourced rows; Taric Q carries only the
    # "Maximum Charges" attribute and its heal is owned by the E1 rule
    # (issue #143), so it is deliberately NOT a support candidate.
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

# Issue #143: prose-only ally heals were previously re-derived here from a
# hardcoded (base, ap_ratio, max_health_ratio) tuple (Taric Q's 1-charge
# floor).  Taric Q now has ONE ledger owner — the E1 self-heal rule in
# ``healing.py`` prices the sourced stock and the participant timeline fans
# out that one event to selected allies — so the scanner never re-derives it.
# There is intentionally no numeric heal registry left in this module.
# E8d follow-up: target-scope overrides for casts whose cached description
# markers cannot express the sourced targeting.  Yuumi's E (Zoomies) shields
# the attached ally, not Yuumi herself, while attached — the deterministic
# roster model targets one selected teammate (the anchor).
_SCOPE_OVERRIDES: dict[tuple[str, str], str] = {
    ("Yuumi", "E"): "one_teammate",
    # P1-3: Lux W (Prismatic Barrier) shields Lux herself on the throw and
    # the return ("Lux gains the shield upon throwing and upon retrieving
    # the wand"); the allied half needs a teammate roster the 1v1 lacks,
    # so the deterministic single-target cast targets self.
    ("Lux", "W"): "self",
    # Issue #143 (phase 2): Rakan Q's cached prose ("Rakan heals himself
    # and nearby allied champions") resolves ``self_and_all_teammates``,
    # which double-granted the self heal at the scanner's rank-indexed 80
    # while the champion rule prices the per-LEVEL self heal (40 : 230
    # based on level — 210 at level 18).  The champion-owned self-heal
    # wins; the scanner's ally branch stays at its own amount, so the
    # packet targets ALLIES ONLY.  In a 1v1 (no selected teammate) the
    # packet resolves to nothing and the self heal pays exactly once.
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
}

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

# Issue #143: slots whose heal the champion module / E1 self-heal rule
# authors itself instead of this scanner.  The scanner must never re-derive
# these: every one is a known double-grant or fabrication (see the issue
# audit and output/issue-143-findings.md).  Defined exactly once — a second
# assignment shadows the first at import time (the E9-3/E9-2 history) and
# is a hard contract-test failure.
#
# Phase 1 (E9-3/E9-2/E1 reconciliation):
# - Shyvana W: the 'Heal' row is the DRAGON-FORM recast heal
#   (60 : 104.71 by level + 4% : 8.47% by level missing health, gated on
#   the explosion hitting a champion), authored by
#   ``healing.derive_self_healing``; the scanner's static read would emit
#   the rank-indexed flat at cast time unconditionally (no dragon gate, no
#   missing-health term, wrong leveling index).
# - Naafiri Q: the recast heal rides the module's Q damage receipts at the
#   cached "Heal" row (``healing.derive_self_healing``).
# - Taric Q: Starlight's Touch is priced per stocked charge by the E1 rule
#   (sourced "Maximum Charges" row + description formulas); the scanner's
#   hardcoded one-charge tuple double-granted the same cast at a different
#   amount.
#
# Phase 2 (the remaining issue #143 audit).  Two groups:
# 1) SELF-heal double-grants — the healing rule authors the self heal
#    (rank/level-indexed sourced rows, missing-health terms, Wound/first-W
#    gates) and the scanner re-derived the same cast into the support
#    ledger, so one cast healed self twice at (often) inconsistent amounts:
#    Sona W, Janna R, Milio R, Irelia Q, Vladimir Q, Volibear W, Ekko R,
#    Gangplank W, Kha'Zix W, Tahm Kench Q.
# 2) FABRICATED ally heals — self-only abilities whose description markers
#    made the scanner emit an ally packet that does not exist in the game:
#    Sylas W (Kingslayer), Tryndamere Q (Bloodlust), Talon Q (Noxian
#    Diplomacy), Yorick Q (Last Rites), Kindred W (Hunter's Vigor).  The
#    cached prose for each says the champion heals THEMSELVES only.
#
# Rakan Q is deliberately NOT here: its scanner ALLY branch (rank-indexed
# 80) is kept at its own amount while the champion rule owns the self heal
# (per-level 210) — see ``_SCOPE_OVERRIDES``.
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

    A support row's "target" is the shield's or heal's recipient, not an
    enemy — Taric W's Bastion is "7 / 8 / 9 / 10 / 11% of target's maximum
    health", each recipient off their own.  Such a row resolved against an
    empty target map, which made it 0.0 and dropped it.
    """
    leveling = find_named_leveling(ability, attribute)
    return leveling is not None and any(
        "target's" in unit
        for modifier in leveling.get("modifiers", [])
        for unit in modifier.get("units", [])
    )


def _caster_as_recipient(stats: dict[str, float]) -> dict[str, float]:
    """The one recipient whose stats a scan holds: the caster's own.

    Live health is not a scan-time fact, so only maximum health resolves; a
    row scaling off the recipient's current or missing health still comes
    back 0.0 and is refused (Seraphine W's pulse heal).
    """
    return {"target_max_health": float(stats.get("health", 0.0) or 0.0)}


@dataclass(frozen=True)
class _Row:
    """One resolved leveling row: what it grants, to whom, from which cast."""

    attribute: str
    kind: str
    target_scope: str
    target_self: bool
    recipient_scaled: bool = False


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
    if champion_key in _MODULE_AUTHORED_HEAL_SLOTS:
        # Issue #143 (phase 2): a module/healing-rule-authored heal slot is
        # the exact receipt (level-indexed bases, missing-health terms, a
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
    # E8d follow-up: a sourced per-champion target-scope override wins over
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
        # Issue #142: fail closed at the emitter.  A typo or novel scope must
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
        if recipient_scaled:
            # Only one recipient's stats are in reach, so only the caster's
            # copy has a sourced amount; the ally copy is withheld rather
            # than granted the caster's number.
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


def derive_ally_effects(
    champion_data: dict[str, Any],
    level: int,
    stats: dict[str, float],
    cast_timeline: list[dict[str, Any]],
    ability_ranks: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Return explicit shield/heal packets and their sourced cast times.

    The timeline has no player cursor/target selection, so packets carry a
    sourced target scope for the coupled resolver to apply deterministically:
    ``self``, one selected teammate, or all selected teammates.  A missing
    scope is never silently treated as an area effect.
    """
    if not _has_support_attributes(champion_data):
        return []
    effects: list[dict[str, Any]] = []
    requested_ranks = ability_ranks or {}
    for slot in _SUPPORT_SLOTS:
        ability = _ability(champion_data, slot)
        if not ability:
            continue
        rank = _slot_rank(champion_data, slot, level, requested_ranks)
        if rank < 1:
            continue
        # Validate every authored cast of the slot, even when its resolved
        # packet is zero or intentionally omitted (a per-tick heal without a
        # complete cadence, a module-authored shield, a silenced row).
        times = [
            _sourced_cast_time(cast, slot=slot)
            for cast in cast_timeline
            if cast.get("slot") == slot
        ]
        rows = _slot_rows(champion_data.get("name", ""), slot, ability)
        recipient = _caster_as_recipient(stats)
        for cast_time in times:
            for row in rows:
                amount = extract_named(
                    ability,
                    row.attribute,
                    rank,
                    stats,
                    recipient if row.recipient_scaled else {},
                )
                if amount > 0:
                    effects.append(
                        {
                            "time": cast_time,
                            "kind": row.kind,
                            "amount": float(amount),
                            "source": f"{ability.get('name', slot)} · {row.attribute}",
                            "slot": slot,
                            "target_self": row.target_self,
                            "target_scope": row.target_scope,
                            "rank": rank,
                        }
                    )
    return sorted(effects, key=lambda event: (event["time"], event["kind"]))
