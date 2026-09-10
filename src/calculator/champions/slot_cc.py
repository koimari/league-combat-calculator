"""The module's crowd-control declaration, stamped onto the parts a slot emits."""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from ..ability_spec import DamagePart, Disposition, ZeroPolicy, part_damage_types
from ..control_spec import CC_KIND_VOCABULARY, NO_CONTROL_KIND, ControlEvent
from .entry_shape import EmittedSlot, part_reaches_event_ledger
from .slot_context import PENDING_CONTROL_EVENTS


def _validate_cc_event_contract(
    emitted: EmittedSlot,
    entry: Mapping[str, Any],
    declared: str | None = None,
) -> None:
    """A part-authored ``cc_kind`` must be a known kind that reaches the
    event ledger.

    CC-triggered item passives (Imperial Mandate's Command, Fimbulwinter's
    Everlasting) read the marker off authored damage events only. A marker
    on an entry the fight engine will aggregate coarsely — no single-hit
    certification, no authored ``time_offset``, no dynamic part, no
    module-authored event list — silently never triggers anything, so a
    module that wrote one onto a part it picked is stopped here, at parse
    time.

    ``declared`` is the module's ``MODULE_CC`` value for this slot, and a
    part carrying it is NOT part-authored: the declaration states the kit's
    fact for the whole slot and :func:`_apply_module_cc` stamps it on every
    part, coarse ones included. Where the row cannot carry it the marker
    lands nowhere, which is a fact about the row rather than a mistake
    about the kit — refusing it here would make the slot undeclarable, and
    ``MODULE_CC`` names every slot the module emits. The roster census
    (``tests/test_module_cc_census.py``) counts and names those slots.
    """
    parts = entry.get("parts") or ()
    for part in parts:
        # A sourced duration with no kind is half a declaration; the kind
        # arrives from the part itself or from MODULE_CC (stamped before
        # this check), never later.
        if (
            getattr(part, "cc_duration", 0.0) > 0
            and getattr(part, "cc_kind", None) is None
        ):
            raise emitted.refuse(
                f"a part authors cc_duration={part.cc_duration} " "without a cc_kind"
            )
    cc_parts = [part for part in parts if getattr(part, "cc_kind", None) is not None]
    if not cc_parts:
        return
    for part in cc_parts:
        if part.cc_kind.lower().strip() not in CC_KIND_VOCABULARY:
            raise emitted.refuse(
                f"unknown cc_kind {part.cc_kind!r} (known kinds are "
                "defined by ability_spec.CC_KIND_VOCABULARY)"
            )
    if declared and declared != CC_PER_PART:
        # A constant declaration is stamped on every part of the slot,
        # coarse ones included, so no part here authored anything.
        return
    for part in cc_parts:
        if not part_reaches_event_ledger(entry, part):
            raise emitted.refuse(
                f"cc_kind {part.cc_kind!r} would never reach the event ledger — "
                "certify event_order_certified='single_hit' (one landing), "
                "author the part's time_offset, author damage_events, or "
                "empower a basic attack; without one of these the CC "
                "silently triggers nothing"
            )


# A cast whose only damage is the basic attack it forces prices at zero on
# its own account.  That is a declaration, not a computation, so the marker
# part it carries is a structural zero with a reason.
_EMPOWER_MARKER_ZERO = ZeroPolicy(
    disposition=Disposition.STRUCTURAL_ZERO,
    reason=(
        "an empowering cast deals no damage of its own: its bonus rides the "
        "basic attacks it forces, so this part exists only to carry the "
        "module's reviewed cc_kind onto the swings the fight engine "
        "reattributes to the row"
    ),
)


def _empower_marker_part(
    entry: Mapping[str, Any],
    kind: str,
    champion_name: str,
    slot: str,
) -> DamagePart | None:
    """The carrier for a declaration on a slot that emits no damage part.

    The empower shells return ``parts = ()`` and their damage is the swing
    ``damage._reattribute_empowered_swings`` moves onto the row, so one
    zero-damage part is what gives the marker somewhere to live for
    ``fight.cast_control_marker._declared_cc_marker`` to read.

    ``None`` is the quiet answer: a row with no parts and no empower
    prices nothing an ability event could carry this parse, and
    ``tests/test_module_cc_census.py`` counts the slots it lands on.
    """
    if not entry.get("empowers_next_auto"):
        return None
    damage_type = str(entry.get("damage_type", ""))
    if damage_type not in part_damage_types():
        raise ValueError(
            f"{champion_name} slot {slot!r}: MODULE_CC declares {kind!r} on a "
            f"partless empower whose damage_type is {damage_type!r}, which is "
            "not a part damage type (known types are defined by "
            "ability_spec.part_damage_types)"
        )
    return DamagePart(
        damage_type,
        0.0,
        cc_kind=kind,
        zero_policy=_EMPOWER_MARKER_ZERO,
    )


#: The ``MODULE_CC`` value for a slot whose control is not one answer.
#:
#: A slot-level kind is a constant, and some slots do not have one: the
#: kind varies by part (Zac's Elastic Slingshot knocks back the first
#: bounce and slows the rest), by option (Aphelios' weapon, Sion's charge
#: time, Yasuo's two Q stacks) or by both.  Those slots author the kind on
#: the part that carries it, and name themselves here so the declaration
#: still lists every reviewed slot in one place.  It is a pointer, not a
#: second home: :func:`_apply_module_cc` stamps nothing for such a slot,
#: and authoring a kind on a slot NOT declared here is refused
#: (:func:`_refuse_undeclared_part_cc`), so the pointer cannot go stale.
CC_PER_PART = "per_part"


def _apply_module_cc(
    entry: dict[str, Any],
    kind: str,
    champion_name: str,
    slot: str,
) -> None:
    """Stamp the module's declared cc kind on every part this slot emits.

    ``MODULE_CC`` declares the kit fact once, per slot; a slot emits one
    cast, so every part of that cast carries the same reviewed control
    state.  Stamping here rather than at each construction site is what
    makes the declaration true of parts a module rebuilds after
    ``damage_entry`` (Pantheon's Q and R do exactly that) and of parts an
    AMP-phase slot appends to a finished entry (Amumu's Cursed Touch),
    instead of only of the ones that happened to go through a builder
    keyword.

    A part that carries its own kind under a constant declaration is a
    second home for one fact — whether it agrees or not — so it raises: a
    slot whose control really does vary within the cast declares
    :data:`CC_PER_PART` instead, and one whose control is a constant keeps
    the constant in ``MODULE_CC`` alone.

    A slot with no parts at all gets one built for it, stops the import,
    or is a row that prices nothing: :func:`_empower_marker_part` rules
    which.  A declaration on a row that does price damage always stamps
    rather than returning quietly.
    """
    if kind == CC_PER_PART:
        # The parts already carry the answer, and a branch that reviewed
        # its way to *no* answer (Rammus' aggregated thorns row) leaves
        # them bare on purpose.  Stamping here would overwrite both.  A
        # control event on such a slot authors its own kind for the same
        # reason, so an unstamped interval here is half a declaration.
        if entry.get(PENDING_CONTROL_EVENTS):
            raise ValueError(
                f"{champion_name} slot {slot!r}: declares {CC_PER_PART!r} but a "
                "control event authored no kind — a slot whose control is not "
                "one answer names each one where it is built"
            )
        return
    parts = entry.get("parts") or ()
    if kind == NO_CONTROL_KIND:
        # The reviewed no-CC statement: the fight engine's event rows read
        # it as ``cc_reviewed`` (a row with no kind at all is unreviewed).
        if entry.get("control_events") or entry.get(PENDING_CONTROL_EVENTS):
            raise ValueError(
                f"{champion_name} slot {slot!r}: MODULE_CC declares no crowd "
                "control but the entry authors control_events"
            )
        entry["cc_reviewed"] = True
    elif any(event.kind == kind for event in entry.get("control_events") or ()):
        # A control event naming a DIFFERENT kind is a second control the
        # cast applies (Vayne's Condemn stuns into a wall on top of the
        # knockback every cast lands, Shaco's box fears on sight), which the
        # one-kind declaration cannot hold and which is therefore authored
        # where it is built.  A control event naming the SAME kind is the
        # declaration said twice.
        raise ValueError(
            f"{champion_name} slot {slot!r}: MODULE_CC declares {kind!r} and a "
            "control event restates it — one cast's crowd control has one "
            "home; drop the event's kind and the declared one is stamped onto "
            "the sourced interval"
        )
    elif entry.get(PENDING_CONTROL_EVENTS):
        entry["control_events"] = tuple(
            ControlEvent(
                kind,
                float(pending["duration"]),
                magnitude=float(pending["magnitude"]),
                time_offset=pending["time_offset"],
                skillshot=False,
                scope=pending["scope"],
            )
            for pending in entry.pop(PENDING_CONTROL_EVENTS)
        )
    if not parts:
        marker = _empower_marker_part(entry, kind, champion_name, slot)
        if marker is not None:
            entry["parts"] = (marker,)
        return
    stamped: list[Any] = []
    for part in parts:
        existing = getattr(part, "cc_kind", None)
        if existing is not None:
            raise ValueError(
                f"{champion_name} slot {slot!r}: MODULE_CC declares "
                f"{kind!r} and a part declares {existing!r} — one cast's "
                "crowd control has one home; drop the part's cc_kind, or "
                f"declare the slot {CC_PER_PART!r} if the kind really does "
                "vary within the cast"
            )
        stamped.append(replace(part, cc_kind=kind))
    entry["parts"] = tuple(stamped)


def _refuse_undeclared_part_cc(
    emitted: EmittedSlot,
    entry: Mapping[str, Any],
    declared_keys: frozenset[str],
) -> None:
    """A part may only author a kind for a slot ``MODULE_CC`` names.

    Raises:
        ValueError: The entry's parts author crowd control for a slot the
            module's ``MODULE_CC`` does not declare, so the kit's control
            has a second, unlisted home.
    """
    if emitted.result_key in declared_keys:
        return
    authored = sorted(
        {
            part.cc_kind
            for part in entry.get("parts") or ()
            if getattr(part, "cc_kind", None) is not None
        }
    )
    if authored:
        raise emitted.refuse(
            f"parts author cc_kind(s) {authored} for a slot MODULE_CC does "
            f"not declare — declare the slot (the constant kind, or "
            f"{CC_PER_PART!r} when the kind "
            "varies within the cast)"
        )


def _resolve_pending_control_events(
    emitted: EmittedSlot, entry: dict[str, Any]
) -> None:
    """Refuse a sourced control interval no ``MODULE_CC`` entry gave a kind.

    Raises:
        ValueError: The entry still carries an unstamped control interval,
            so its slot is one the module never declared.
    """
    if entry.pop(PENDING_CONTROL_EVENTS, ()):
        raise emitted.refuse(
            "a control event carries a sourced duration but no kind, because "
            "MODULE_CC does not declare the slot — declare it there, which is "
            "where a kit's crowd control is stated once"
        )
