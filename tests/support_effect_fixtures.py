"""The actor, the grown registry and the packet vocabulary every item-support suite reads."""

import sys
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import packet_declarations

from src.calculator import ally_packet_shape, trigger_stream
from src.calculator import (
    item_behavior_catalog as catalog,
)
from src.calculator.ability_spec import Authority
from src.calculator.item_behavior import PacketKind, Persistence
from src.calculator.program.views.view_tag import ViewTag
from src.calculator.roster_composition import ActorRequest
from src.calculator.trigger_stream import CAPABILITIES


def _capability(mechanic: str, packet_source: str):
    """A synthetic seventh cross-participant producer, declared."""
    return trigger_stream.MechanicCapability(
        mechanic=mechanic,
        owner=trigger_stream.ItemOwner("Synthetic Seventh"),
        engine=trigger_stream.Engine.WALK,
        reads=frozenset(),
        needs=frozenset(),
        authority=Authority.COUPLED_ONLY,
        pairing=trigger_stream.Pairing.SOLO,
        pair_of=None,
        divergence_ref=None,
        impl="item_support_effects.derive_item_support_effects",
        packet_source=packet_source,
        view_tags=MappingProxyType({trigger_stream.Engine.WALK: ViewTag.APPLIED}),
        holder_stacking=None,
    )


def _grown_registry(mechanic: str, capability, monkeypatch, cold_memo):
    """Read the producer table off a registry carrying one more capability.

    P2c moved the table off this module's own ``_packet`` call sites and
    onto ``trigger_stream.CAPABILITIES``, so a seventh producer is now
    expressed as a declaration rather than as source text — which is the
    only way to test that the table follows the registry.
    """
    grown = MappingProxyType({**CAPABILITIES, mechanic: capability})
    monkeypatch.setattr(ally_packet_shape, "CAPABILITIES", grown)
    cold_memo(ally_packet_shape, "_declared_authorities")
    return grown


def _actor(
    participant_id: str,
    team: str,
    item_names: tuple[str, ...],
    *,
    level: int = 18,
    item_options: dict | None = None,
    ally_effects_enabled: bool = True,
):
    return SimpleNamespace(
        participant_id=participant_id,
        team=team,
        level=level,
        items=tuple({"name": name} for name in item_names),
        stats={"mana": 1000.0, "max_mana": 1000.0, "is_melee": False},
        request=ActorRequest(
            item_options=item_options or {},
            ally_effects_enabled=ally_effects_enabled,
        ),
    )


# One Abyssal holder, one ally to price and one cursed enemy — the shape the
# coupled baseline's ``mandate_abyssal_curse_roster`` scenario uses, reduced to
# the one item these slices move.  The ally is an Ahri rather than the
# baseline's Pantheon because C3 types the curse: Pantheon's only damage into
# the cursed enemy after the arming timestamp is physical, so with a magic-only
# Unmake his rows carry no multiplier at all and the roster cannot show
# an amped ally.  Ahri's Q lands magic *and* true damage into the same enemy at
# the same instant, which is the whole of C3 in one packet pair.
_ABYSSAL_ROSTER = {
    "champion": "Ahri",
    "level": 18,
    "items": ["Abyssal Mask"],
    "fight_mode": "time_based",
    "fight_duration": 8,
    "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
    "allies": [
        {
            "champion": "Ahri",
            "level": 18,
            "items": [],
            "ally_effects_enabled": True,
        }
    ],
}


def declared_classes_by_producer():
    """Each ``damage_modifier`` call site's declared class sets, by source."""
    return packet_declarations.declared("damage_classes", "attack_classes")


def timed_cross_participant_producers():
    """Every ``damage_modifier`` producer whose declaration carries an expiry.

    Read from the Phase 3 declarations rather than from the ``duration=``
    expression at the call site: 3.6 moved the number behind the producer's
    own reference, so "does this modifier close" is now a declared axis
    (``Persistence``) instead of something a reader infers from whether one
    keyword happens to be passed.  The source literal comes back through the
    mechanic's capability, which is the one home for "which packet does this
    producer emit".
    """
    sources = set()
    for producer, declaration in catalog.ALLY_PACKET_DECLARATIONS.items():
        if declaration.persistence is not Persistence.TIMED_WINDOW:
            continue
        if not any(
            spec.kind is PacketKind.DAMAGE_MODIFIER for spec in declaration.packets
        ):
            continue
        for owner in catalog.owners_for(producer):
            mechanic = f"{catalog._mechanic_slug(owner)}.{producer.value}"
            sources.add(trigger_stream.CAPABILITIES[mechanic].packet_source)
    return sources
