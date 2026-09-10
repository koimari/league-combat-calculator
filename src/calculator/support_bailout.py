"""Renata Glasc's Bailout: its ramp, its denial rows and the shape it withholds."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .ability_atoms import (
    AbilityAtomQuery,
    atom_receipt,
    ranked_ability_atom_value,
    required_ability_atom,
    required_ranked_attribute_atom,
)
from .champions import renata_bailout_authority
from .item_behavior import PacketKind

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
    return renata_bailout_authority.BAILOUT_AUTHORITY


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
        atoms.append(atom_receipt(base_atom))
        atoms.append(atom_receipt(ratio_atom))

    duration_atom = required_ability_atom(
        atom_key, champion_data, "W", query=_BAILOUT_DURATION_QUERY
    )
    if duration_atom.get("units") != ["s"]:
        raise ValueError(f"{champion_label} W active duration atom must use seconds")
    duration = ranked_ability_atom_value(
        duration_atom, 1, source=_BAILOUT_DURATION_QUERY.source
    )
    atoms.append(atom_receipt(duration_atom))

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
