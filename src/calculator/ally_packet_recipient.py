"""Re-pricing a one-ally packet for the ally actually selected."""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache
from types import MappingProxyType
from typing import Any

from .ally_packet_shape import _producer, producer_item
from .interpreters.ally_packet import AllyPacketSlot, resolve_slots
from .item_behavior import AllyProducer, LevelSubject, PacketKind
from .roster_composition import Combatant

# Which declared packet a chained enchanter effect emits, keyed by the kind
# of the packet that triggered it, and which sourced fraction that packet
# carries.  Two tables rather than one runtime-computed kind (D-50): the kind
# a producer emits has to be readable from the declaration, and the fraction
# it uses has to be readable from the kind.
_CHAIN_KINDS: Mapping[str, PacketKind] = MappingProxyType(
    {"heal": PacketKind.HEAL, "shield": PacketKind.SHIELD}
)


_CHAIN_FRACTION_KEYS: Mapping[PacketKind, str] = MappingProxyType(
    {
        PacketKind.HEAL: "heal_chain_fraction",
        PacketKind.SHIELD: "shield_chain_fraction",
    }
)


def _ramp_value(
    slot: AllyPacketSlot, key: str, *, holder: Any, recipient: Any
) -> float:
    """One declared level ramp, read at the level its declaration names."""
    subject = slot.level_subject(key)
    level = holder.level if subject is LevelSubject.HOLDER else recipient.level
    return slot.level_value(key, level)


#: Stamped on a packet whose amount was read at its RECIPIENT's own level,
#: naming the producer and the ramp that priced it.  A one-ally packet's
#: recipient is chosen downstream, so the price has to move with the choice.
RECIPIENT_RAMP_KEY = "_recipient_level_ramp"


#: The ``target_scope`` values whose recipient a request can still move after
#: the packet was priced — the one condition under which
#: :data:`RECIPIENT_RAMP_KEY` is ever read back.  Declared beside the stamp and
#: consumed by ``participant_timeline._apply_item_support_selection``: a scope
#: that lands on the whole team was already priced at each member's own level,
#: so stamping it would promise a re-read that can never happen.
RETARGETABLE_SCOPES: frozenset[str] = frozenset(
    {
        "one_teammate",
        "explicit_selected_ally",
        "healed_or_shielded_ally",
        "most_wounded_ally",
        "nearest_most_wounded_ally",
        "other_nearest_wounded_ally",
    }
)


def _recipient_amount(
    slot: AllyPacketSlot, key: str, *, holder: Any, recipient: Any, scope: str
) -> dict[str, Any]:
    """The *key* ramp's amount, stamped when *scope* can still re-target it."""
    fields: dict[str, Any] = {
        "amount": _ramp_value(slot, key, holder=holder, recipient=recipient)
    }
    if (
        slot.level_subject(key) is LevelSubject.RECIPIENT
        and scope in RETARGETABLE_SCOPES
    ):
        fields[RECIPIENT_RAMP_KEY] = (slot.producer.value, key)
    return fields


@cache
def reprice_slot(owner: str, producer_value: str) -> AllyPacketSlot | None:
    """*owner*'s declared producer, compiled once per owner and producer."""
    return _producer(resolve_slots({owner}), AllyProducer(producer_value))


def repriced_for_recipient(
    template: Mapping[str, Any], recipient: Combatant
) -> dict[str, Any]:
    """*template* with any recipient-scaled amount re-read at *recipient*.

    The one re-read of :data:`RECIPIENT_RAMP_KEY`, for the one place a packet
    can change hands after it was priced.  An unstamped template comes back
    unchanged; a stamp naming a producer the holder's build does not declare
    is a stop, never the default ally's amount.

    The producer is compiled through :func:`reprice_slot`, whose cache holds
    the DECLARATION and not a number — the slot's amounts stay live
    ``ValueRef`` reads taken at ``level_value`` time — so only a registry
    refresh moving an owner's producers can stale it.
    """
    stamp = template.get(RECIPIENT_RAMP_KEY)
    if stamp is None:
        return dict(template)
    producer_value, key = stamp
    source = str(template["source"])
    owner = producer_item(source)
    slot = reprice_slot(owner, producer_value)
    if slot is None:
        raise ValueError(
            f"{source!r} is priced at its recipient's level, but {owner!r} "
            f"declares no {producer_value!r} producer to re-read it through"
        )
    return {**template, "amount": slot.level_value(key, recipient.level)}
