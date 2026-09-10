"""A control atom, and the archetypes that attach one to a slot."""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from ..ability_atoms import (
    AbilityAtomQuery,
    ranked_ability_atom_value,
    required_ability_atom,
    required_ranked_attribute_atom,
)
from ..ability_spec import DamagePart
from ..control_spec import ControlEvent, ControlScope
from .slot_context import DAMAGE, PENDING_CONTROL_EVENTS, SlotCtx, SlotParser
from .slot_extract import _axis_index, ability_name, extract_cooldown, extract_named


def resolve_source(
    ctx: SlotCtx,
    source: tuple[str, int] | None,
) -> tuple[dict[str, Any] | None, str]:
    """Resolve a factory's source param to (ability JSON, source slot)."""
    src_slot, src_index = source or (ctx.slot, 0)
    return ctx.ability(src_slot, src_index), src_slot


def _control_duration_atom(
    ctx: SlotCtx,
    source: tuple[str, int] | None,
    attribute: str,
    rank: int,
    *,
    effect_index: int = 0,
) -> tuple[float, dict[str, Any]]:
    """Read a control duration through the validated ability atom catalog."""
    src_slot, src_index = source or (ctx.slot, 0)
    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
    try:
        value, atom = required_ranked_attribute_atom(
            ctx.champion_name,
            champion_data,
            src_slot,
            attribute,
            rank,
            entry_index=src_index,
        )
    except KeyError:
        source_path = (
            f"{ctx.champion_name}.{src_slot}[{src_index}].effects[{effect_index}]"
            ".description"
        )
        query = AbilityAtomQuery(
            source=source_path,
            behavior="timing",
            evidence_prefix="control duration@",
        )
        atom = required_ability_atom(
            ctx.champion_name,
            champion_data,
            src_slot,
            query=query,
        )
        value = ranked_ability_atom_value(atom, 1, source=source_path)
    _require_seconds(ctx, src_slot, atom)
    return value, atom_receipt(atom)


ATOM_RECEIPT_KEYS = (
    "atom_id",
    "behavior",
    "source",
    "values",
    "units",
    "evidence",
    "hash",
)


def atom_receipt(atom: Mapping[str, Any]) -> dict[str, Any]:
    """The provenance fields a sourced control number publishes."""
    return {key: atom[key] for key in ATOM_RECEIPT_KEYS}


_PROSE_CONTROL_PREFIXES = {
    "prose": "control duration@",
    "active": "active duration@",
}


def _prose_control_atom(
    ctx: SlotCtx,
    source: tuple[str, int] | None,
    effect_index: int,
    duration_source: str,
) -> tuple[float, dict[str, Any]]:
    """Read a control window the cache states in a sentence, not a row.

    Two evidence prefixes, because the catalog files two different readings
    of one description and a slot can carry both.  ``control duration@`` is
    a control verb followed by an interval (Udyr's pounce "stun them for
    0.75 seconds"); ``active duration@`` is the effect's own window (Bard's
    Tempered Fate "puts all units within into stasis for 2.5 seconds",
    Nasus ages his target "for 5 seconds"), which is the control's window
    exactly when the control lasts as long as the effect.  The caller says
    which it means rather than the reader guessing.
    """
    src_slot, src_index = source or (ctx.slot, 0)
    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
    source_path = (
        f"{ctx.champion_name}.{src_slot}[{src_index}].effects[{effect_index}]"
        ".description"
    )
    atom = required_ability_atom(
        ctx.champion_name,
        champion_data,
        src_slot,
        query=AbilityAtomQuery(
            source=source_path,
            behavior="timing",
            evidence_prefix=_PROSE_CONTROL_PREFIXES[duration_source],
        ),
    )
    value = ranked_ability_atom_value(atom, 1, source=source_path)
    _require_seconds(ctx, src_slot, atom)
    return value, atom_receipt(atom)


def _control_magnitude_atom(
    ctx: SlotCtx,
    source: tuple[str, int] | None,
    attribute: str,
    rank: int,
) -> tuple[float, dict[str, Any]]:
    """Read a control's strength off the named cached leveling attribute.

    Tier one only, and deliberately: a magnitude is a ranked number the
    cache either carries under a name or does not carry at all, and a prose
    fallback here would be the literal-default shape rule 5 refuses.
    """
    src_slot, src_index = source or (ctx.slot, 0)
    value, atom = required_ranked_attribute_atom(
        ctx.champion_name,
        {"name": ctx.champion_name, "abilities": ctx.abilities},
        src_slot,
        attribute,
        rank,
        entry_index=src_index,
    )
    return value, atom_receipt(atom)


def _require_seconds(ctx: SlotCtx, src_slot: str, atom: Mapping[str, Any]) -> None:
    """A control window is an interval; anything else is the wrong atom."""
    units = atom.get("units", [])
    allowed_units = {"seconds", "s"}
    if not isinstance(units, list) or any(
        str(unit).strip().lower() not in allowed_units for unit in units
    ):
        raise ValueError(
            f"{ctx.champion_name} {src_slot} control duration atom must use seconds"
        )


def resolve_casts(
    casts: int | str,
    ability: dict[str, Any],
    rank: int,
    level: int | None = None,
) -> float:
    """Resolve a casts param to a damage multiplier.

    An int is used as is; a string names a leveling attribute holding the count.
    """
    if isinstance(casts, str):
        count = extract_named(ability, casts, rank, level=level)
        return count if count > 0 else 1.0
    return float(casts)


def extract_recharge(
    ability: dict[str, Any], rank: int, *, level: int | None = None
) -> float:
    """Cooldown for a charge ability: ``rechargeRate`` at rank.

    The JSON ``cooldown`` of a charge ability is the short inter-cast timer.
    """
    rates = ability.get("rechargeRate") or []
    if not rates:
        return extract_cooldown(ability, rank, level=level)
    return float(rates[_axis_index(rates, rank, level)])


def with_control(
    parser: SlotParser,
    *,
    duration_attr: str,
    kind: str | None = None,
    source: tuple[str, int] | None = None,
    ranks: str = "rank",
    part_index: int = 0,
    effect_index: int = 0,
) -> SlotParser:
    """Attach one sourced action-blocking control interval to a damage slot.

    The interval is what this helper sources: how long, from which cached
    attribute, with the atom that proves it.  *Which* control the slot
    applies is normally the module's ``MODULE_CC`` entry, stamped after
    every phase — so a slot wrapped here and left undeclared stops the
    parse at ``engine._validate_cc_event_contract`` (a duration with no
    kind is half a declaration) instead of carrying the kind twice.

    ``kind`` is for the one slot shape ``MODULE_CC`` cannot state: a cast
    whose control differs part by part or branch by branch (Twisted Fate's
    three cards, Zilean's primed bomb).  Such a slot declares
    :data:`engine.CC_PER_PART` and authors the kind here; the engine
    refuses this argument on any slot that declared a constant.
    """
    if kind is not None and not kind.strip():
        raise ValueError("with_control kind must be a non-empty string")
    if ranks not in {"rank", "level"}:
        raise ValueError("with_control ranks must be 'rank' or 'level'")

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = parser(ctx)
        if entry is None:
            return None
        ability, source_slot = resolve_source(ctx, source)
        if ability is None:
            raise ValueError(
                f"{ctx.champion_name} {ctx.slot}: control source ability is missing"
            )
        rank = ctx.level if ranks == "level" else ctx.rank_for(source_slot)
        duration, duration_atom = _control_duration_atom(
            ctx, source, duration_attr, rank, effect_index=effect_index
        )
        if duration <= 0.0:
            raise ValueError(
                f"{ctx.champion_name} {ctx.slot}: sourced control duration "
                f"{duration_attr!r} is missing or zero"
            )
        parts = list(entry.get("parts", ()))
        if not parts or part_index >= len(parts):
            raise ValueError(
                f"{ctx.champion_name} {ctx.slot}: control part index "
                f"{part_index} is absent"
            )
        if not isinstance(parts[part_index], DamagePart):
            raise TypeError(
                f"{ctx.champion_name} {ctx.slot}: control part is not a DamagePart"
            )
        part = parts[part_index]
        parts[part_index] = replace(
            part,
            cc_kind=kind if kind is not None else part.cc_kind,
            cc_duration=duration,
            control_source_atoms=(
                *part.control_source_atoms,
                {
                    key: duration_atom[key]
                    for key in (
                        "atom_id",
                        "behavior",
                        "source",
                        "values",
                        "units",
                        "evidence",
                        "hash",
                    )
                },
            ),
        )
        entry["parts"] = tuple(parts)
        return entry

    parse.phase = getattr(parser, "phase", DAMAGE)
    return parse


def park_control_interval(
    entry: dict[str, Any],
    duration: float,
    *,
    time_offset: float | None = 0.0,
    magnitude: float = 0.0,
    scope: ControlScope = ControlScope.EVERY_TARGET,
) -> None:
    """Park a sourced control interval for ``MODULE_CC`` to name.

    :func:`with_control_event` for a slot that builds its entry by hand.
    """
    entry[PENDING_CONTROL_EVENTS] = (
        *tuple(entry.get(PENDING_CONTROL_EVENTS, ())),
        {
            "duration": float(duration),
            "time_offset": time_offset,
            "magnitude": float(magnitude),
            "scope": scope,
        },
    )


def with_control_event(
    parser: SlotParser,
    *,
    duration_attr: str | None = None,
    duration_source: str = "attribute",
    magnitude_attr: str | None = None,
    kind: str | None = None,
    time_offset: float | None = 0.0,
    effect_index: int = 0,
    scope: ControlScope = ControlScope.EVERY_TARGET,
) -> SlotParser:
    """Add one sourced control event, including to a utility-only slot.

    Like :func:`with_control`, the interval is what this helper sources and
    the kind is the module's ``MODULE_CC`` entry: an event authored with no
    ``kind`` rides the slot as a pending interval and
    ``engine._apply_module_cc`` stamps the declared kind onto it after every
    phase.  A cc-only slot therefore states its control exactly where a
    damaging slot does, and the two cannot disagree.

    ``kind`` is for the one slot shape ``MODULE_CC`` cannot state: a cast
    whose control is not one answer (Vayne's Condemn stuns only into a wall,
    on top of the knockback every cast lands; Lulu's Whimsy polymorphs only
    the enemy branch).  Such a slot declares :data:`engine.CC_PER_PART` and
    authors the kind here; the engine refuses this argument on any slot that
    declared a constant.

    ``duration_source`` names which cached window the control occupies:

    * ``"attribute"`` reads ``duration_attr`` off the ability's leveling
      rows, falling back to the ``control duration@`` prose atom;
    * ``"prose"`` reads that prose atom directly, for a control the cache
      states in a sentence and in no leveling row (Udyr's 0.75s pounce stun,
      Viktor's 1s refreshing slow window);
    * ``"active"`` reads the effect's own ``active duration@`` window, for a
      control that lasts exactly as long as the effect applying it (Bard's
      2.5s stasis, Nasus' 5s Wither).

    Naming the source at the call site is the point: a slot can carry more
    than one seconds atom and only a reviewer knows which is the control
    (Singed's Mega Adhesive carries the 0.375s landing delay, not its 3s
    field, which is why that slot stays undeclared).

    ``magnitude_attr`` sources the control's strength -- a slow's percent --
    off a named leveling attribute, through the same validated catalog.

    ``scope`` names who the control lands on; the default reaches every
    enemy the cast hit, which is the area answer (see
    :class:`ability_spec.ControlScope`).
    """
    if kind is not None and not kind.strip():
        raise ValueError("with_control_event kind must be a non-empty string")
    if duration_source not in {"attribute", "prose", "active"}:
        raise ValueError(
            "with_control_event duration_source must be 'attribute', 'prose' "
            "or 'active'"
        )
    if (duration_source == "attribute") != (duration_attr is not None):
        raise ValueError(
            "with_control_event names duration_attr for an attribute source "
            "and omits it for a prose or active one"
        )

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = parser(ctx)
        ability, source_slot = resolve_source(ctx, None)
        if ability is None:
            raise ValueError(
                f"{ctx.champion_name} {ctx.slot}: control source ability is missing"
            )
        rank = ctx.rank_for(source_slot)
        if rank < 1:
            return entry
        if duration_source != "attribute":
            duration, duration_atom = _prose_control_atom(
                ctx, None, effect_index, duration_source
            )
        else:
            duration, duration_atom = _control_duration_atom(
                ctx, None, duration_attr, rank, effect_index=effect_index
            )
        if duration <= 0.0:
            raise ValueError(
                f"{ctx.champion_name} {ctx.slot}: sourced control duration "
                f"{duration_attr or duration_source!r} is missing or zero"
            )
        magnitude = 0.0
        magnitude_atom = None
        if magnitude_attr is not None:
            magnitude, magnitude_atom = _control_magnitude_atom(
                ctx, None, magnitude_attr, rank
            )
            if magnitude <= 0.0:
                raise ValueError(
                    f"{ctx.champion_name} {ctx.slot}: sourced control magnitude "
                    f"{magnitude_attr!r} is missing or zero"
                )
        if entry is None:
            entry = {
                "name": ability_name(ability),
                "rank": rank,
                "cooldown": extract_cooldown(ability, rank),
                "damage_type": "magic",
                "total_raw": 0.0,
                "parts": (),
            }
        if kind is None:
            park_control_interval(
                entry,
                duration,
                time_offset=time_offset,
                magnitude=magnitude,
                scope=scope,
            )
        else:
            controls = list(entry.get("control_events", ()))
            controls.append(
                ControlEvent(
                    kind,
                    duration,
                    magnitude=magnitude,
                    time_offset=time_offset,
                    skillshot=False,
                    scope=scope,
                )
            )
            entry["control_events"] = tuple(controls)
        entry["control_source_atoms"] = [
            *entry.get("control_source_atoms", []),
            duration_atom,
            *([magnitude_atom] if magnitude_atom is not None else []),
        ]
        return entry

    parse.phase = getattr(parser, "phase", DAMAGE)
    return parse
