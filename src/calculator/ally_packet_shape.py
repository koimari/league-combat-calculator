"""What one cross-participant item packet is, the producer it came from, and the
authority it is audited against."""

from __future__ import annotations

import math
from collections.abc import Collection, Iterable, Mapping
from functools import lru_cache
from types import MappingProxyType
from typing import Any

from .ability_spec import AttackClass, Authority, DamageClass
from .capabilities import SUPPORT_TARGET_SCOPES
from .interpreters.ally_packet import AllyPacketSlot
from .interpreters.resistance_shred import ShredSlot, walk_slot
from .item_behavior import AllyProducer, FightFacts, Resistance
from .roster_composition import Combatant
from .survival.classify import SUPPORT_RANK_KEY
from .survival.phases import TransitionRank
from .trigger_stream import CAPABILITIES, cross_participant_packet_source

# The one packet kind that changes how much damage some *other* participant
# deals or takes, and therefore the kind ``_packet`` runs its authority and
# damage-class checks on.  See *Cross-participant producers* below.
_DAMAGE_MODIFIER_KIND = "damage_modifier"


# The sentinel that separates "the caller supplied no value" from a real
# zero; a mana read that is absent is a named denial, never a 0.0.
_MISSING = object()


def _same_side(attacker: Any, actor: Any) -> bool:
    left = "main" if attacker.team in {"main", "ally"} else attacker.team
    right = "main" if actor.team in {"main", "ally"} else actor.team
    return left == right


def _teammates(attacker: Combatant, all_actors: Iterable[Combatant]) -> list[Combatant]:
    attacker_id = getattr(attacker, "participant_id", None)
    return [
        actor
        for actor in all_actors
        if getattr(actor, "participant_id", None) != attacker_id
        and _same_side(attacker, actor)
    ]


def _item_names(attacker: Combatant) -> set[str]:
    return {str(item.get("name", "")) for item in attacker.items}


def _option(attacker: Any, item_name: str, key: str, default: float = 0.0) -> float:
    request = getattr(attacker, "request", None)
    item_options = getattr(request, "item_options", {}) or {}
    options = item_options.get(item_name, {})
    value = options.get(key, default) if isinstance(options, Mapping) else default
    if isinstance(value, bool):
        raise ValueError(f"{item_name}.{key} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{item_name}.{key} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{item_name}.{key} must be finite")
    return parsed


def _producer(
    slots: Mapping[AllyProducer, tuple[AllyPacketSlot, ...]], producer: AllyProducer
) -> AllyPacketSlot | None:
    """This build's one holder of *producer*, or ``None``.

    ``None`` is an answer, not a zero: the build declares the mechanic
    nowhere, so no packet is owed.  Two holders is a stop — every producer but
    the support quest is carried by exactly one registry record, and a second
    one would be two ledgers nothing says how to combine.
    """
    found = slots.get(producer, ())
    if len(found) > 1:
        raise ValueError(
            f"{[slot.owner for slot in found]} all declare the "
            f"{producer.value} producer and no rule says how two of them "
            "combine"
        )
    return found[0] if found else None


def _shred_ramp(
    attacker: Any, names: Collection[str], resistance: Resistance, producer: str
) -> ShredSlot:
    """This holder's declared shred of *resistance*, on the receipt-walk lane.

    Both sides read the family's own declaration, through the interpreter
    registered in the lane the family declares, so the shred is one mechanic
    with one declaration and a score and a receipt cannot disagree.

    A holder of the cross-participant half whose build declares no shred is a
    **stop**: the packet would otherwise be emitted with no ramp behind it,
    which is a modifier nobody declared rather than one measuring zero.

    Two of the four :class:`~.item_behavior.BuildContext` facts are stated
    rather than passed through: a shred is a per-stack fraction and a stack
    cap, so no ``resistance_shred`` declaration reads a fight duration or a
    target's bonus health.
    """
    slot = walk_slot(
        sorted(frozenset(names)),
        resistance,
        facts=FightFacts(
            level=int(attacker.stats.get("level", 1) or 1),
            fight_duration_seconds=0.0,
            target_bonus_health=0.0,
            holder_is_melee=bool(attacker.stats.get("is_melee", False)),
        ),
    )
    if slot is None:
        raise ValueError(
            f"{attacker.participant_id} declares the {producer} producer and no "
            f"{resistance.value} resistance_shred rule; the walk would stage a "
            "reduction packet whose ramp no declaration states"
        )
    return slot


def _active_seconds(attacker: Any, slot: AllyPacketSlot | None) -> float:
    """When the scenario cast *slot*'s active, or ``0.0`` if it never did."""
    if slot is None:
        return 0.0
    return _active_seconds_for(attacker, slot.owner)


def _active_seconds_for(attacker: Any, item_name: str) -> float:
    """One validated active-seconds read for *item_name*.

    Delegates to the typed ``input_option_float_value`` accessor so the
    emission layer re-checks the schema bounds AND step multiple: a direct
    timeline caller cannot author an out-of-domain activation even though
    the request layer already validates.  Absent input reads 0.0 (no cast).
    """
    from .item_effects import input_option_float_value

    request = getattr(attacker, "request", None)
    item_options = getattr(request, "item_options", None) or {}
    return input_option_float_value(
        list(attacker.items), item_options, item_name, "active_seconds"
    )


def _packet(  # pylint: disable=too-many-arguments
    *,
    attacker: Any,
    target: Any,
    time: float,
    kind: str,
    source: str,
    amount: float = 0.0,
    duration: float = 0.0,
    target_scope: str = "one_teammate",
    rank: TransitionRank | None = None,
    authority: Authority | None = None,
    damage_classes: frozenset[DamageClass] | None = None,
    attack_classes: frozenset[AttackClass] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Build one sourced packet.

    Keyword-only, and the argument-count check is disabled for the reason
    ``trigger_stream``'s own builder disables it: every parameter is a
    declared packet axis a call site names by keyword, and folding them into
    one dict is the untyped bag the typed packet replaced.

    ``rank`` is how a packet declares *when* it arms, for the packets whose
    kind does not decide it (a barrier the triggering damage placed, say).
    It is the only way to override the walk's ladder: an author names a
    :class:`TransitionRank`, never a number.

    ``authority`` is how a ``damage_modifier`` packet declares which engine
    owns its mechanic.  It is required of those packets and meaningless on
    the rest, it is checked here — the one construction site all six
    cross-participant producers pass through — and it is deliberately *not*
    written into the returned dict: the declaration's homes are this call
    site and the mechanic's ``trigger_stream`` capability, and a packet
    payload that grew a key would move receipts inside a semantic commit
    (R-17).

    ``damage_classes`` and ``attack_classes`` are how a ``damage_modifier``
    packet says *what it applies to* — the two axes of D-04, both required
    of those packets, both banned from being empty, and both checked here.
    Unlike ``authority`` they are written into the returned dict, because
    the walk reads them per packet; they reach no receipt, because the
    published support-event payload is an explicit key list
    (``participant_timeline``'s ``support_events`` block) and neither key is
    on it.

    ``rank`` also sits earlier in the returned dict than the open ordering
    float it replaced did: that arrived through ``**fields``, after every
    explicit key, and the rank is injected before them.  Inert — the
    published receipt is assembled from an explicit key list, not from this
    dict's order — but it is a payload-shape change beyond the key's name
    and type, and a fixture comparing serialized packet order would see it.
    """
    if not math.isfinite(float(amount)) or float(amount) < 0.0:
        raise ValueError(f"{source} packet amount must be finite and non-negative")
    if not math.isfinite(float(duration)) or float(duration) < 0.0:
        raise ValueError(f"{source} packet duration must be finite and non-negative")
    if target_scope not in SUPPORT_TARGET_SCOPES:
        raise ValueError(
            f"{source} packet target_scope {target_scope!r} is outside the "
            f"closed support scope vocabulary: {sorted(SUPPORT_TARGET_SCOPES)}"
        )
    attacker_id = getattr(attacker, "participant_id", None)
    target_id = getattr(target, "participant_id", None)
    if kind != "item_denial" and (
        not isinstance(attacker_id, str)
        or not attacker_id.strip()
        or not isinstance(target_id, str)
        or not target_id.strip()
    ):
        raise ValueError(f"{source} applied packet requires participant identity")
    if kind == _DAMAGE_MODIFIER_KIND:
        _check_cross_participant_authority(source, authority, fields.get("owner"))
        _check_declared_classes(source, damage_classes, attack_classes)
        _check_aura_arming(source, fields.get("persistent"), rank)
        fields = {
            "damage_classes": damage_classes,
            "attack_classes": attack_classes,
            **fields,
        }
    return {
        "time": float(time),
        "kind": kind,
        "amount": float(amount),
        "duration": float(duration),
        "source": source,
        "source_key": source,
        "attacker": attacker_id,
        "target": target_id,
        "target_scope": target_scope,
        "target_policy": "explicit_selected_roster_target",
        "target_selection_key": fields.get("target_selection_key", f"{kind}:{source}"),
        "_item_support": True,
        **({SUPPORT_RANK_KEY: rank} if rank is not None else {}),
        **fields,
    }


@lru_cache(maxsize=1)
def _declared_authorities() -> Mapping[str, Authority]:
    """Every declared cross-participant packet source and its owning engine.

    The key is the walk packet's ``source`` literal and the value the
    ``Authority`` that capability declares.  Which halves qualify is
    ``trigger_stream.cross_participant_packet_source``'s answer.

    Cached because ``_packet`` consults it on every cross-participant packet
    it builds and the stack-ledger producers build one per damage event.
    """
    return MappingProxyType(
        {
            source: capability.authority
            for capability in sorted(
                CAPABILITIES.values(), key=lambda cap: cap.mechanic
            )
            if (source := cross_participant_packet_source(capability)) is not None
        }
    )


def _check_cross_participant_authority(
    source: str, authority: Authority | None, owner: Any
) -> None:
    """Every ``damage_modifier`` packet names its engine, and only ``SPLIT`` owns.

    The rule keys on the declared :class:`Authority`, never on a flag: three
    of the six producers set no ``all_sources``, so an ``all_sources``-keyed
    check passes Dream Maker, Black Cleaver and Bloodletter's Curse by
    construction (D-07).  ``owner`` is the walk's skip handshake — the
    holder's own contribution is priced pair-side — so it is meaningful
    exactly when the two halves are disjoint, which is what ``SPLIT`` says.

    This is also where a call site is bound to the registry: the packet is
    built with an ``authority=`` argument and it must be the one
    ``CAPABILITIES`` declares for that ``packet_source``, so the declaration
    and the construction cannot drift without a raise naming both.
    """
    declared = _declared_authorities().get(source)
    if declared is None:
        raise ValueError(
            f"{source} modifies another participant's damage but names no "
            "Authority; every damage_modifier packet declares one (D-07)"
        )
    if authority is not declared:
        raise ValueError(
            f"{source} was built with authority={authority} but its packet "
            f"declares {declared.value}"
        )
    if owner is not None and declared is not Authority.SPLIT:
        raise ValueError(
            f"{source} declares {declared.value} and carries owner={owner!r}; "
            "only SPLIT has a pair-side half for the walk to skip"
        )
    if owner is None and declared is Authority.SPLIT:
        raise ValueError(
            f"{source} declares SPLIT and carries no owner; the pair-local "
            "half is unreachable to the walk's skip and the holder is priced "
            "twice"
        )


def _check_declared_classes(
    source: str,
    damage_classes: frozenset[DamageClass] | None,
    attack_classes: frozenset[AttackClass] | None,
) -> None:
    """Every ``damage_modifier`` packet says which damage it applies to (D-04).

    Both axes are required with no default and neither may be empty:
    "empty means all" is a silent default, and the walk that consumed these
    packets untyped amplified a magic-only curse onto physical and true
    damage alike.  ``attack_classes`` is the axis on which "from all
    sources" becomes something a packet can *state* rather than something a
    reader infers from a missing restriction.
    """
    for name, declared, vocabulary in (
        ("damage_classes", damage_classes, DamageClass),
        ("attack_classes", attack_classes, AttackClass),
    ):
        if not declared:
            raise ValueError(
                f"{source} modifies another participant's damage and declares "
                f"no {name}; a non-empty frozenset of "
                f"{vocabulary.__name__} is required and empty-means-all is "
                "banned (D-04)"
            )
        if not all(isinstance(member, vocabulary) for member in declared):
            raise ValueError(
                f"{source} declares {name} holding something other than "
                f"{vocabulary.__name__} members"
            )


def _check_aura_arming(
    source: str, persistent: Any, rank: TransitionRank | None
) -> None:
    """A persistent cross-participant modifier is an aura, and arms as one.

    A ``damage_modifier`` some trigger armed is a debuff, resolving after the
    damage at its own timestamp.  A *persistent* one was in force when the
    fight opened, so that ordering would make the opening exchange the one
    exchange the aura does not price.  The kind cannot tell the two apart, so
    the aura declares ``AURA_ARM`` and this refuses a persistent modifier that
    does not.
    """
    if not persistent:
        return
    if rank is not TransitionRank.AURA_ARM:
        raise ValueError(
            f"{source} is a persistent damage_modifier and declares "
            f"rank={rank}; a persistent modifier is an aura already in "
            "force and must declare TransitionRank.AURA_ARM, or it prices "
            "nothing at its own timestamp (C4)"
        )


def producer_item(source: str) -> str:
    """The item name a producer's ``source`` literal names."""
    return source.split(" — ", 1)[0].strip()
