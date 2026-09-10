"""What one support row publishes: recipient scaling, rank, duration and timing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .ability_atoms import (
    AbilityAtomQuery,
    atom_receipt,
    ranked_ability_atom_value,
    required_ability_atom,
)
from .capabilities import SUPPORT_TARGET_RESOLUTION_SCOPES
from .champions.skill_orders import get_ability_rank
from .champions.slot_extract import find_named_leveling
from .support_scan import (
    _CHAMPION_HEAL_ATTR,
    _CHAMPION_SHIELD_ATTR,
    _MODULE_AUTHORED_HEAL_SLOTS,
    _MODULE_AUTHORED_SHIELD_SLOTS,
    _SCOPE_OVERRIDES,
    _STATE_AUTHORED_HEAL_SLOTS,
    _declares_a_heal,
    _row_target,
    _support_profile,
)

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


def _caster_as_recipient(stats: Mapping[str, float]) -> dict[str, float]:
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
    """One rank's share of the recipient's maximum health, as a fraction.

    Callers reach here only after the unit-shape gate certified the row, so
    an empty values list is a vanished row and raises rather than returning
    a ratio the downstream ``<= 0.0`` guard would silently swallow.
    """
    leveling = find_named_leveling(ability, attribute)
    values = (leveling or {}).get("modifiers", [{}])[0].get("values") or []
    if not values:
        raise ValueError(
            f"recipient-scaled row {attribute!r} on {ability.get('name')!r} "
            "certified by its unit shape but carries no values"
        )
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
    champion_data: Mapping[str, Any],
    slot: str,
    level: int,
    requested_ranks: Mapping[str, int],
) -> int:
    """The rank this slot is cast at: the request's, else the skill order's."""
    default_rank = get_ability_rank(slot, level, champion_data.get("name", ""))
    try:
        return max(0, int(requested_ranks.get(slot, default_rank)))
    except (TypeError, ValueError):
        return default_rank


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
    return {"duration": duration, "duration_atom": atom_receipt(atom)}


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
        "activation_delay_atom": atom_receipt(delay_atom),
        "duration_atom": atom_receipt(duration_atom),
    }
