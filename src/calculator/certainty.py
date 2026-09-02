"""Per-ability certainty classification from module and audit evidence."""

import json
import re
from collections.abc import Collection, Iterable, Mapping
from pathlib import Path
from typing import Any

from .cast_dependency import BASE_CAST_SLOTS
from .champions import get_champion_module_meta

_SLOT_LETTERS = BASE_CAST_SLOTS

CERTAINTY_EXACT = "exact"
CERTAINTY_ESTIMATE = "estimate"
CERTAINTY_BOUNDARY = "boundary"

# Assumption-line classifiers for the trust label.  A line is BOUNDARY when
# it documents a mechanic the module deliberately does not compute; a line
# is ESTIMATE when it documents a defaulted or approximated input.  Lines
# with neither marker contribute no certainty signal.
_BOUNDARY_MARKERS = (
    "not modeled",
    "not modelled",
    "not priced",
    "not entered",
    "not simulated",
    "not produced",
    "not computed",
    "does not simulate",
    "does not model",
    "out of scope",
    "out-of-scope",
    "utility only",
    "utility-only",
    "stays state",
    "remains state",
    "boundary",
    "unavailable",
    "deals no enemy damage",
)
_ESTIMATE_MARKERS = (
    "approximat",
    "assum",
    "estimated",
    "conservative",
    "slightly",
    "player-controlled",
    "default",
    "uptime",
    "on-hit model",
    "sourced upper",
)

# Curated option-key -> slot overrides for keys whose label carries no slot
# letter and whose mechanic is not the champion's ability name (pet summons,
# passives, form-adjacent toggles).  Without these the option would degrade
# the whole kit to estimate; with them the trust label stays per-ability.
_OPTION_SLOT_OVERRIDES = {
    "adoration_cash_in": "P",
    "adoration_stacks": "P",
    "daisy_attacks": "R",
    "marks": "P",
    "plant_attacks": "W",
    "plant_count": "W",
    "sapling_empowered": "E",
    "scalemail_stacks": "P",
    "soul_mark_proc": "W",
    "stone_skin_stacks": "P",
    "target_cursed": "P",
    "tibbers_attacks": "R",
    "tibbers_aura_seconds": "R",
    "voidling_attacks": "W",
    "voidling_count": "W",
}

# P1 audit entries (data/champion-audit/batch-p1-*.json) are the certified
# slot-coverage receipts for the 30 reviewed champions; the trust label
# consults them before module prose.
_AUDIT_GLOB = "batch-p1-*.json"
# Mutable holder so the lazy load needs no ``global`` statement.
_AUDIT_CACHE: dict[str, object] = {"loaded": False, "entries": {}}


def _audit_entries() -> dict[str, dict]:
    """Lazily load the P1 champion-audit slot-coverage receipts."""
    if _AUDIT_CACHE["loaded"]:
        return _AUDIT_CACHE["entries"]  # type: ignore[return-value]
    entries: dict[str, dict] = {}
    audit_dir = Path(__file__).resolve().parents[2] / "data" / "champion-audit"
    try:
        for path in sorted(audit_dir.glob(_AUDIT_GLOB)):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            entries.update(
                {
                    name: entry
                    for name, entry in payload.items()
                    if isinstance(name, str) and isinstance(entry, dict)
                }
            )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        entries = {}
    _AUDIT_CACHE["loaded"] = True
    _AUDIT_CACHE["entries"] = entries
    return entries


def _option_affects_slot(
    option: Mapping[str, Any], slot: str, ability_names: Mapping[str, list[str]]
) -> bool:
    """Whether one OPTIONS entry is a player-controlled input for ``slot``."""
    key = str(option.get("key", "")).lower()
    label = str(option.get("label", ""))
    if key in _OPTION_SLOT_OVERRIDES:
        return _OPTION_SLOT_OVERRIDES[key] == slot
    prefix = key.split("_", 1)[0]
    if prefix in {"p", "q", "w", "e", "r"}:
        return prefix.upper() == slot
    if key.startswith("passive"):
        return slot == "P"
    if re.search(rf"\b{slot}\b", label):
        return True
    return any(
        name and name.lower() in label.lower() for name in ability_names.get(slot, ())
    )


def classify_assumption(text: str) -> str | None:
    """Classify one ASSUMPTIONS line as estimate/boundary, or None."""
    lowered = text.lower()
    is_estimate = any(marker in lowered for marker in _ESTIMATE_MARKERS)
    if is_estimate:
        return CERTAINTY_ESTIMATE
    if any(marker in lowered for marker in _BOUNDARY_MARKERS):
        return CERTAINTY_BOUNDARY
    return None


def _line_mentions_slot(
    line: str, slot: str, ability_names: Mapping[str, list[str]]
) -> bool:
    """Whether an assumption line talks about ``slot`` (letter, name, or
    the passive keyword)."""
    if re.search(rf"\b{slot}\b", line):
        return True
    if slot == "P" and re.search(r"\bpassive\b", line, re.IGNORECASE):
        return True
    return any(name and name in line for name in ability_names.get(slot, ()))


_Verdict = tuple[str, str]


def _certified_boundary(
    slot: str,
    coverage: Mapping[str, str],
    *,
    module_slots: Collection[str],
    ability_names: Mapping[str, list[str]],
    audit: Mapping[str, Any] | None,
) -> _Verdict | None:
    """The boundary the audit, the module coverage or an absent slot entry documents."""
    audit_state = None
    if audit and isinstance(audit.get("slots"), dict):
        audit_state = audit["slots"].get(slot)
    cov_state = coverage.get(slot)
    if audit_state == "out_of_scope" or cov_state == "out_of_scope":
        return CERTAINTY_BOUNDARY, (
            f"{slot} is documented out of scope: the module deliberately does "
            f"not compute it (no damage row is priced)."
        )
    if audit_state == "no_damage" or cov_state == "no_damage":
        return CERTAINTY_BOUNDARY, (
            f"{slot} is documented as dealing no enemy damage in the model; "
            f"only a zero-damage/utility receipt exists."
        )
    if slot not in module_slots and slot in ability_names:
        return CERTAINTY_BOUNDARY, (
            f"{slot} is not modeled: the champion module has no slot entry "
            f"for it, so no damage row is priced."
        )
    return None


def _option_labels(options: Iterable[Mapping[str, Any]]) -> str:
    """``'key' (default value)`` for each option, comma-joined."""
    return ", ".join(
        f"'{option.get('key')}' (default {option.get('default')})" for option in options
    )


def _slot_option_estimate(
    slot: str, options: Iterable[Mapping[str, Any]], ability_names: dict[str, list[str]]
) -> _Verdict | None:
    """The estimate the slot's own player-controlled defaulted options impose."""
    slot_options = [
        option
        for option in options
        if _option_affects_slot(option, slot, ability_names)
    ]
    if not slot_options:
        return None
    return CERTAINTY_ESTIMATE, (
        f"Uses player-controlled defaulted option(s): {_option_labels(slot_options)}; "
        f"the damage row depends on the supplied value."
    )


def _assumption_verdict(
    slot: str, assumptions: Iterable[str], ability_names: dict[str, list[str]]
) -> _Verdict | None:
    """What a documented assumption naming the slot classifies to, boundary first."""
    slot_lines = [
        line for line in assumptions if _line_mentions_slot(line, slot, ability_names)
    ]
    for line in slot_lines:
        if classify_assumption(line) == CERTAINTY_BOUNDARY:
            return CERTAINTY_BOUNDARY, f"Documented non-computed mechanic: {line}"
    for line in slot_lines:
        if classify_assumption(line) == CERTAINTY_ESTIMATE:
            return CERTAINTY_ESTIMATE, f"Documented approximation/assumption: {line}"
    return None


def _global_option_estimate(
    slot: str, options: Iterable[Mapping[str, Any]], ability_names: dict[str, list[str]]
) -> _Verdict | None:
    """The estimate kit-wide defaulted options (form toggles, pet counts,
    AD/AS points) impose on every damaging slot: the kit depends on them."""
    global_options = [
        option
        for option in options
        if not any(
            _option_affects_slot(option, other, ability_names)
            for other in ability_names
        )
    ]
    if not global_options:
        return None
    return CERTAINTY_ESTIMATE, (
        f"Kit-wide player-controlled option(s) {_option_labels(global_options)} "
        f"can change the damage rows; {slot} inherits the estimate."
    )


# pylint: disable-next=too-many-arguments,too-many-positional-arguments
def _slot_certainty(
    slot: str,
    options: Iterable[Mapping[str, Any]],
    assumptions: Iterable[str],
    coverage: Mapping[str, str],
    module_slots: Collection[str],
    ability_names: dict[str, list[str]],
    audit: Mapping[str, Any] | None,
    registration: str,
) -> _Verdict:
    """Derive one slot's certainty level and its human-readable reason."""
    verdict = (
        _certified_boundary(
            slot,
            coverage,
            module_slots=module_slots,
            ability_names=ability_names,
            audit=audit,
        )
        or _slot_option_estimate(slot, options, ability_names)
        or _assumption_verdict(slot, assumptions, ability_names)
        or _global_option_estimate(slot, options, ability_names)
    )
    if verdict is not None:
        return verdict
    if registration != "reviewed_module":
        return CERTAINTY_ESTIMATE, (
            f"No player-controlled defaults or documented boundaries for "
            f"{slot}, but the champion has no validated named module — treat "
            f"numbers as estimates."
        )
    return CERTAINTY_EXACT, (
        f"Every damaging/heal row for {slot} is a sourced formula with no "
        f"player-controlled default."
    )


def derive_certainty(champion: str, champion_data: Mapping[str, Any]) -> dict[str, Any]:
    """Per-slot certainty for one champion, from module + audit evidence."""
    meta = get_champion_module_meta(champion)
    options = meta.get("options") or []
    assumptions = meta.get("assumptions") or []
    coverage = meta.get("coverage") or {}
    module_slots = meta.get("slots") or []
    registration = meta.get("registration") or "unregistered"
    audit = _audit_entries().get(champion)

    ability_names: dict[str, list[str]] = {}
    for slot, entries in (champion_data.get("abilities") or {}).items():
        if isinstance(entries, list):
            names = [
                str(entry.get("name", "")).strip()
                for entry in entries
                if isinstance(entry, dict) and entry.get("name")
            ]
            ability_names[str(slot)] = [name for name in names if name]

    existing_slots = [
        slot for slot in _SLOT_LETTERS if slot in ability_names or slot in module_slots
    ]
    slots = {
        slot: {
            "certainty": certainty,
            "reason": reason,
        }
        for slot in existing_slots
        for certainty, reason in [
            _slot_certainty(
                slot,
                options,
                assumptions,
                coverage,
                module_slots=module_slots,
                ability_names=ability_names,
                audit=audit,
                registration=registration,
            )
        ]
    }
    return {
        "champion": champion,
        "slots": slots,
        "certified": registration == "reviewed_module",
        "registration": registration,
    }
