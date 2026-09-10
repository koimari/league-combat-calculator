"""The actor, the grown registry and the packet vocabulary every item-support suite reads."""

import ast
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

from src.calculator import (
    ally_packet_shape,
    item_support_effects,
    trigger_stream,
)
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


@contextmanager
def _grown_registry(mechanic: str, capability):
    """Read the producer table off a registry carrying one more capability.

    P2c moved the table off this module's own ``_packet`` call sites and
    onto ``trigger_stream.CAPABILITIES``, so a seventh producer is now
    expressed as a declaration rather than as source text — which is the
    only way to test that the table follows the registry.
    """
    grown = MappingProxyType({**CAPABILITIES, mechanic: capability})
    ally_packet_shape.CAPABILITIES = grown
    ally_packet_shape._declared_authorities.cache_clear()
    try:
        yield grown
    finally:
        ally_packet_shape.CAPABILITIES = CAPABILITIES
        ally_packet_shape._declared_authorities.cache_clear()


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


def _is_packet_kind_node(node, kind: str) -> bool:
    """Whether a ``_packet(kind=...)`` node names ``PacketKind.<KIND>.value``.

    ER1 put the kind on the enum rather than a bare string literal at every
    site, so the three source walks below ask this one question instead of
    each matching a spelling.
    """
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "value"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == kind.upper()
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "PacketKind"
    )


def _packet_keyword(call, name):
    """The value node of one keyword argument of a ``_packet(...)`` call.

    Moved out of ``item_support_effects`` at P2c.  ``CAPABILITIES`` is the
    authority table, not a walk of the module's own source, so the walk
    over its construction sites is purely a test-side source assertion and
    lives with the assertions.
    """
    return next((k.value for k in call.keywords if k.arg == name), None)


def declared_packet_keywords(*names):
    """Each ``damage_modifier`` call site's declared keywords, by source.

    Read from the construction sites and evaluated in the module's own
    namespace, so the test sees the declaration a reader sees rather than a
    packet a fixture happened to build.  A keyword the call site does not
    pass comes back ``None`` — absent and defaulted are the same thing to
    ``_packet`` and the caller decides what that means.

    Public, and the one AST walk over those call sites: the Phase 0
    sentinels in ``test_phase0_sentinels`` read the same declarations (their
    class sets and their expiries), and a second walk would be a second home
    for one fact.
    """
    module_source = Path(item_support_effects.__file__).read_text(encoding="utf-8")
    declared = {}
    for node in ast.walk(ast.parse(module_source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_packet"
        ):
            continue
        kind = _packet_keyword(node, "kind")
        if not _is_packet_kind_node(kind, "damage_modifier"):
            continue
        source = _packet_keyword(node, "source").value
        declared[source] = {
            name: _evaluate_declaration(_packet_keyword(node, name)) for name in names
        }
    return declared


def _evaluate_declaration(expression):
    """One declared keyword's value, or ``None`` when the site omits it."""
    if expression is None:
        return None
    return eval(  # noqa: S307 - evaluates the module's own declaration AST  # pylint: disable=eval-used
        compile(ast.Expression(expression), "<declaration>", "eval"),
        vars(item_support_effects),
    )


def declared_classes_by_producer():
    """Each ``damage_modifier`` call site's declared class sets, by source."""
    return declared_packet_keywords("damage_classes", "attack_classes")


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
