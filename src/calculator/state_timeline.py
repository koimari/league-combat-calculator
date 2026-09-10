"""The kernel's transition record: the receipt a declaration cites, the stamp, and the timeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, NamedTuple

from .control_spec import IMMOBILIZING_CC_KINDS

# Floating-point tolerance shared with the damage/survival walks.  All
# kernel comparisons use the same 1e-9 convention as the engine receipts.
_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class SourceReceipt:
    """One reviewed provenance record for a kernel declaration.

    ``revision_id`` 0 with a cache-backed ``revision_timestamp`` marks a
    value reviewed from the local data cache rather than a pinned wiki
    revision (the same convention ``defensive_effects`` uses for its
    cache-backed defense sources).
    """

    label: str
    url: str
    revision_id: int = 0
    revision_timestamp: str = "cached data (patch cache)"
    key: str | None = None

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> SourceReceipt:
        """Adapt the two receipt spellings used in this codebase.

        Item option rows publish ``source_url``/``source_revision_id``;
        champion and defense sources publish ``label``/``url``/
        ``revision_id``/``revision_timestamp``.
        """
        url = str(
            mapping.get("source_url")
            or mapping.get("url")
            or "https://wiki.leagueoflegends.com"
        )
        return cls(
            label=str(mapping.get("label") or mapping.get("item") or url),
            url=url,
            revision_id=int(mapping.get("source_revision_id", 0) or 0),
            revision_timestamp=str(
                mapping.get("revision_timestamp") or "cached data (patch cache)"
            ),
        )

    def public(self) -> dict[str, Any]:
        """JSON-safe public receipt for this source record."""
        row: dict[str, Any] = {
            "label": self.label,
            "url": self.url,
            "revision_id": self.revision_id,
            "revision_timestamp": self.revision_timestamp,
        }
        if self.key is not None:
            row["key"] = self.key
        return row


# Ordered tiers mirror the survival walk's phase ordering at one timestamp:
# scheduled expiry applies before new state, consume/reset after the gains
# they depend on, and cooldown start after the proc that triggers it.  A
# lower tier sorts first.
TIER_EXPIRE = -2.0


TIER_GAIN = 0.0


TIER_CONSUME = 0.5


TIER_COOLDOWN_START = 1.0


TransitionKind = Literal[
    "gain",
    "refresh",
    "extend",
    "replace",
    "expire",
    "consume",
    "consume_denied",
    "reset",
    "gain_denied",
    "proc",
    "cooldown_start",
    "trigger_skipped",
    "charge_gain",
    "charge_spend",
    "charge_denied",
    "lockout_start",
    "lockout_end",
    "combat_freeze",
]


class EventStamp(NamedTuple):
    """When a kernel event happens, in the walk's deterministic total order.

    ``sequence`` breaks ties between events sharing one ``time``: every
    ledger here sorts on ``(time, tier, sequence, insertion_order)``, and
    the caller feeds stamps in the same order the survival/damage walks
    author their packets.
    """

    time: float
    sequence: int = 0


@dataclass(frozen=True, slots=True)
class Transition:
    """One timestamped state transition in the kernel's total order."""

    time: float
    kind: TransitionKind
    sequence: int
    tier: float
    detail: Mapping[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        """JSON-safe receipt; ``detail`` rides under its own key so the
        top-level ``time``/``kind``/``sequence``/``tier`` stay stable."""
        return {
            "time": self.time,
            "kind": self.kind,
            "sequence": self.sequence,
            "tier": self.tier,
            "detail": dict(self.detail),
        }


class StateTimeline:
    """Append-only transition log with a deterministic total order.

    Sort key: ``(time, tier, sequence, insertion_order)``.  The caller
    feeds transitions in the same ``(time, sequence)`` order the
    survival/damage walks use; ties at one ``(time, sequence)`` are
    decided by tier (expiry before gain before cooldown start), and
    insertion order breaks the final tie deterministically.
    """

    def __init__(self) -> None:
        self._transitions: list[Transition] = []
        self._order = 0

    def record(
        self,
        stamp: EventStamp,
        kind: TransitionKind,
        *,
        tier: float = TIER_GAIN,
        detail: Mapping[str, Any] | None = None,
    ) -> Transition:
        """Record one transition and return it."""
        transition = Transition(
            time=stamp.time,
            kind=kind,
            sequence=stamp.sequence,
            tier=tier,
            detail=dict(detail or {}),
        )
        self._transitions.append(transition)
        self._order += 1
        return transition

    def transitions(self) -> list[Transition]:
        """The deterministic total order over recorded transitions."""
        return sorted(
            self._transitions,
            key=lambda t: (
                t.time,
                t.tier,
                t.sequence,
                self._transitions.index(t),
            ),
        )

    def public_receipt(self) -> list[dict[str, Any]]:
        """JSON-safe ordered receipt for every transition."""
        return [transition.public() for transition in self.transitions()]

    def __len__(self) -> int:
        return len(self._transitions)


@dataclass(frozen=True, slots=True)
class CcTriggerRule:
    """Crowd-control trigger classification (Fimbulwinter Everlasting).

    Everlasting fires only from an explicitly authored immobilize, or a
    slow for a melee holder.  ``immobilize_kinds`` is the sourced
    immobilize vocabulary (``ability_spec.IMMOBILIZING_CC_KINDS``, the one
    home the trigger bus already reads); a bare ``crowd_control`` flag is
    intentionally NOT enough to distinguish the immobilize/slow branches.
    """

    name: str
    immobilize_kinds: frozenset[str] = field(
        default_factory=lambda: frozenset(IMMOBILIZING_CC_KINDS)
    )
    slow_kind: str = "slow"
    slow_melee_only: bool = True
    source: SourceReceipt | None = None

    def is_candidate(self, event: Mapping[str, Any]) -> bool:
        """Whether the event can carry a qualifying CC trigger at all."""
        kind = str(event.get("cc_kind", "")).lower().strip()
        if kind in self.immobilize_kinds or kind == self.slow_kind:
            return True
        return bool(
            event.get("immobilized")
            or event.get("hard_cc")
            or event.get("crowd_control")
            or event.get("slowed")
            or event.get("slow")
        )

    def match(self, event: Mapping[str, Any], *, is_melee: bool) -> str:
        """Return ``"immobilize"``, ``"slow"``, or ``""`` for one event."""
        kind = str(event.get("cc_kind", "")).lower().strip()
        if kind in self.immobilize_kinds:
            return "immobilize"
        if bool(event.get("immobilized")) or bool(event.get("hard_cc")):
            return "immobilize"
        if kind == self.slow_kind or bool(event.get("slowed") or event.get("slow")):
            if self.slow_melee_only and not is_melee:
                return ""
            return "slow"
        return ""

    def denial_reason(self, event: Mapping[str, Any], *, is_melee: bool) -> str | None:
        """Name why a CC-adjacent event cannot fire, or ``None``.

        ``None`` means the event is not a CC candidate at all (no
        crowd-control metadata, so nothing to deny) or it matched an eligible
        branch.  Denials are named so the consumer can receipt them fail
        closed instead of silently skipping:

        - ``"unknown_cc_kind"``: a ``cc_kind`` outside the sourced vocabulary;
        - ``"untyped_cc"``: only a bare ``crowd_control`` flag, which cannot
          tell the immobilize and slow branches apart;
        - ``"ranged_slow"``: a slow-classified event whose holder is not melee.

        The adjacency test is broader than :meth:`is_candidate` on purpose: an
        event carrying an out-of-vocabulary ``cc_kind`` is CC-adjacent and
        receipted, though it can never match a branch.
        """
        if self.match(event, is_melee=is_melee):
            return None
        kind = str(event.get("cc_kind", "")).lower().strip()
        has_kind = bool(kind)
        has_flag = bool(
            event.get("immobilized")
            or event.get("hard_cc")
            or event.get("crowd_control")
            or event.get("slowed")
            or event.get("slow")
        )
        if not has_kind and not has_flag:
            return None
        if has_kind and kind not in self.immobilize_kinds and kind != self.slow_kind:
            return "unknown_cc_kind"
        if kind == self.slow_kind or bool(event.get("slowed") or event.get("slow")):
            return "ranged_slow"
        return "untyped_cc"

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe public receipt."""
        return {
            "name": self.name,
            "immobilize_kinds": sorted(self.immobilize_kinds),
            "slow_kind": self.slow_kind,
            "slow_melee_only": self.slow_melee_only,
            "source": self.source.public() if self.source is not None else None,
        }
