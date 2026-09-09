"""One row of the reconstructed ledger: its time key, typed parts, share and precision."""

import math
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from ...ability_atoms import ability_field
from ...survival.pricing import AuthoredDeclaration
from ...trigger_stream import TriggerKind
from ..state import FightState


def _row_time(row: Mapping[str, Any]) -> float:
    """One event row's time, the key every chronological sort uses."""
    return float(row["time"])


def _finite_numeric_receipt(value: Any) -> float | None:
    """Coerce a JSON numeric receipt, rejecting bools, strings, and NaN."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _damage_type_fields(by_type: dict[str, float]) -> dict[str, Any]:
    """Breakdown-row typing fields: one contributing type yields a plain
    ``damage_type``, several yield ``"mixed"`` plus the ``damage_by_type``
    composition ``split_by_damage_type`` consumes."""
    if len(by_type) == 1:
        return {"damage_type": next(iter(by_type))}
    return {"damage_type": "mixed", "damage_by_type": dict(by_type)}


# A row's total and its ledger must be the same arithmetic: ``+=`` and
# ``sum()`` over the same numbers disagree by an ulp, so a row that gave every
# swing away would read a crumb instead of 0.0 and count as an active source.
def _ledger_total(events: Sequence[Mapping[str, Any]]) -> float:
    """What an authored event list is worth, summed one way everywhere."""
    return sum(float(event["damage"]) for event in events)


def _row_damage_parts(entry: Mapping[str, Any]) -> list[tuple[str, float]]:
    """Return one breakdown row's exact typed post-mitigation parts."""
    by_type = entry.get("damage_by_type")
    if by_type is not None:
        return [
            (dtype, float(amount))
            for dtype, amount in by_type.items()
            if dtype in {"physical", "magic", "true"} and amount > 0
        ]
    dtype = entry.get("damage_type")
    damage = float(entry.get("total_damage", 0.0))
    return (
        [(dtype, damage)]
        if dtype in {"physical", "magic", "true"} and damage > 0
        else []
    )


# A row whose ledger held no certifiable boundary authors no events of its own,
# and the reconstruction below synthesizes one per typed part instead.  The
# declaration is split the way the damage was, through the same restatement
# :func:`restate_declaration` applies when a re-pricing site moves a packet's
# magnitude; otherwise a row falling into two damage types would hand one
# magnitude to both packets and the walk would price the family twice.
def _row_declaration_share(
    declaration: tuple[Any, ...] | None, amount: float, total: float
) -> tuple[Any, ...] | None:
    """One coarse row's declaration, as the share one synthesized event
    carries.  ``None`` in, ``None`` out."""
    if declaration is None or total <= 0.0:
        return None
    return tuple(AuthoredDeclaration(*declaration).rescaled_by(amount / total))


# Phase precedence inside one timestamp of the reconstructed ledger.
_EVENT_PHASE_ORDER = {"ability": 0, "auto": 1, "effect": 2, "amplifier": 3}


# Sources whose packets carry omnivamp's full-effectiveness marker.
_VAMP_SOURCE_PREFIXES = ("auto_attacks", "on_hit_")


# The control stream alone: an immobilize walk never reads a damage trigger,
# and asking for one would build a projection it discards (D-30).
_CONTROL_TRIGGER_ONLY = frozenset({TriggerKind.CC})


# A row whose entry authored no optional fields.
_NO_EVENT_FIELDS: Mapping[str, Any] = MappingProxyType({})


# The one fact a synthesized auto-attack row authors: it is a basic attack.
_AUTO_EVENT_FIELDS: Mapping[str, Any] = MappingProxyType({"basic_attack": True})


def _damage_event_row(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    light: bool,
    lean: bool,
    source_key: str,
    damage_type: str,
    *,
    damage: float,
    time: float,
    sequence: int,
    order_value: float,
    phase: str,
    ordinal: int,
    fields: Mapping[str, Any],
    is_ability: bool,
    vamp_source: bool,
    shield_events: list[Any] | None,
) -> Any:
    """One reconstructed-ledger row, in the shape its consumer reads.

    The one home of the row schema.  ``fields`` is the authored event (or,
    for an entry the reconstruction had to synthesize, a mapping spelled the
    same way), and everything optional is read off it here, so the three
    shapes stay projections of one field list: ``light`` is the tuple
    mid-fight scans read, ``lean`` the dict the scoring path reads without
    display-only fields, and the default the full dict receipts serialize.
    ``_lk`` is the ``(time, order, phase, sequence)`` sort key, built once
    here so ordering never rebuilds it per event.
    """
    sort_key = (time, order_value, _EVENT_PHASE_ORDER[phase], sequence)
    raw_damage = fields.get("raw_damage")
    if light:
        return (
            sort_key,
            damage,
            damage_type,
            source_key,
            fields.get("raw_formula"),
            0.0 if raw_damage is None else float(raw_damage),
            fields.get("declared"),
        )
    row: dict[str, Any] = {
        "source_key": source_key,
        "damage_type": damage_type,
        "damage": damage,
        "time": time,
        "sequence": sequence,
        "_lk": sort_key,
    }
    if not lean:
        row["ordinal"] = ordinal
        row["phase"] = phase
        row["order"] = order_value
        missing_ratio = fields.get("source_missing_ratio")
        if missing_ratio is not None:
            row["source_missing_ratio"] = float(missing_ratio)
        precision = fields.get("event_precision")
        if precision is not None:
            row["event_precision"] = str(precision)
    cc_kind = fields.get("cc_kind")
    if cc_kind is not None:
        row["cc_kind"] = str(cc_kind)
    # Reviewed when the entry says so, or when the part carries an authored
    # kind at all — ``trigger_stream._classify_cc`` reads a row exactly this
    # way, and ``"none"`` is the reviewed-no-CC marker, so it certifies the
    # row while narrowing nothing and never becoming a live control kind.
    if cc_kind is not None or fields.get("cc_reviewed"):
        row["cc_reviewed"] = True
    cc_duration = fields.get("cc_duration")
    if cc_duration is not None and float(cc_duration) > 0.0:
        row["cc_duration"] = float(cc_duration)
    # The delivery facts an interaction reads off the packet: what shape the
    # ability threw, whether it hit an area, whether it ticks, and the atoms
    # its control was sourced from.
    if fields.get("skillshot"):
        row["skillshot"] = True
    if fields.get("area_damage"):
        row["area_damage"] = True
    if fields.get("cast_while_disabled"):
        # A summon's attack, not the caster's cast: the walk's attacker
        # crowd-control gate does not stop it.
        row["cast_while_disabled"] = True
    if fields.get("damage_over_time"):
        row["damage_over_time"] = True
    source_atoms = fields.get("control_source_atoms")
    if source_atoms:
        row["control_source_atoms"] = [
            dict(atom) for atom in source_atoms if isinstance(atom, Mapping)
        ]
    for passthrough in ("amplified", "deathfire_category", "trigger_source"):
        if passthrough in fields:
            row[passthrough] = fields[passthrough]
    trigger_time = fields.get("trigger_time")
    if trigger_time is not None:
        row["trigger_time"] = float(trigger_time)
    if is_ability:
        row["is_ability"] = True
    # The event names its own shield; the entry's parallel list supplies one
    # for events that do not.
    shield = fields.get("self_shield")
    if shield is None and shield_events is not None and ordinal <= len(shield_events):
        shield = shield_events[ordinal - 1]
    if isinstance(shield, (dict, Mapping)):
        row["self_shield"] = dict(shield)
    if raw_damage is not None:
        row["raw_damage"] = float(raw_damage)
    raw_formula = fields.get("raw_formula")
    if raw_formula is not None:
        row["raw_formula"] = raw_formula
    # The declaration this packet is a price of, for a family whose
    # retirement moved the pricing to the walk: ``(mechanic_id,
    # pre-mitigation magnitude)``.  Absent on every packet whose family the
    # pair engine still prices, which is what keeps the walk's
    # from-declaration path reachable only by a family that opted in.
    declared = fields.get("declared")
    if declared is not None:
        row["declared"] = declared
    basic_attack = fields.get("basic_attack")
    if basic_attack:
        row["basic_attack"] = True
    if basic_attack or vamp_source:
        # Omnivamp's full-effectiveness branch is certified only for the
        # primary attack/on-hit packet. Area, pet, and copied target rows
        # deliberately carry no eligibility marker.  Both vamp markers are a
        # pricing input, not display, so the lean shape keeps them: the
        # lifesteal/omnivamp derivations and the item support scan read them
        # off score-only rows too.
        row["omnivamp_effectiveness"] = 1.0
    return row


# ``cast_events`` publishes times rounded to 3 decimals (the one rounding
# site, in ``_compute_ability_rotation``) while rows author raw plan times.
# Walkers matching authored events against that public boundary must accept
# half the rounding step, or an up-rounded cast time disowns its own hit.
_CAST_TIME_RESOLUTION = 5e-4


_CERTIFIED_CAST_PRECISIONS = frozenset({"single_hit", "auto_stack_proc"})


def _item_proc_precision(state: FightState, slot: str) -> str:
    """Return the event precision an item proc rides on one ability cast.

    An ordered item trigger (Muramana Shock, Eclipse stacking, Shaped
    Charge) lands on the ability's hit.  For an ability whose cast boundary
    IS the authored hit — a module ``single_hit`` / ``auto_stack_proc``
    marker, or a cast-order row with casts and no DoT, the same condition
    the coverage classifier uses to certify it — the proc event is
    ``exact``.  Generic/uncertified abilities and DoT casts keep
    ``cast_boundary``, which the coverage classifier treats as coarse and
    the BIS optimizer excludes — the fail-closed contract for abilities
    whose hit timing is not proven.
    """
    info = state.ability_damages.get(slot)
    if isinstance(info, Mapping):
        certified = info.get("event_order_certified")
        if isinstance(certified, str) and certified in _CERTIFIED_CAST_PRECISIONS:
            return "exact"
        # The DoT check reads the ABILITY packet's dot duration (P3 package
        # 3D): breakdown rows never carry dot_duration, so reading it there
        # was a dead branch that stamped uncertified DoT casts as exact.
        dot = float(ability_field(info, "dot_duration"))
    else:
        dot = 0.0
    # A slot with no breakdown row, or a fight with no cast order, has no
    # authored hit to certify: both fail closed to the cast boundary.
    row = state.breakdown
    if isinstance(row, Mapping):
        row = row.get(slot)
    cast_order = state.cast_order
    if cast_order is not None and slot in cast_order and isinstance(row, Mapping):
        casts = int(row.get("casts", 0) or 0)
        if casts > 0 and dot <= 0.0:
            return "exact"
    return "cast_boundary"
