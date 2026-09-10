"""The revision a declaration's numbers were read from, and the registry entry it is cited from."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from . import item_effects, rune_effects
from .reference_vocabulary import VALUE_REGISTRIES, ValueRefError, ValueRegistry


class UnsourcedDeclarationError(ValueError):
    """No citation could be resolved for a declaration's owner.

    Raised by :func:`receipt_for`.  A declaration with no receipt is a number
    whose provenance is a memory, which is what every audit in this
    repository exists to make impossible.
    """


@dataclass(frozen=True, slots=True)
class SourceReceipt:
    """The revision a declaration's numbers were read from.

    ``revision_id`` is a MediaWiki revision id, or ``0`` — the explicit
    marker for a value read from the patch-stamped cached item source, which
    exposes no revision id.  Zero is spelled rather than omitted for the same
    reason the campaign spells ``STRUCTURAL_ZERO``: an absent id and an id
    that does not exist must not look alike.  ``revision_timestamp`` is the
    human-checkable stamp for that revision; when the id is ``0`` it names
    the cache instead (the precedent already in ``defensive_effects``).
    """

    url: str
    revision_id: int
    revision_timestamp: str

    def __post_init__(self) -> None:
        """Reject a receipt that cites nothing checkable."""
        if not self.url.startswith("http"):
            raise ValueRefError(f"SourceReceipt url must be a URL, got {self.url!r}")
        if isinstance(self.revision_id, bool):
            raise ValueRefError("SourceReceipt revision_id must be an int")
        if self.revision_id < 0:
            raise ValueRefError("SourceReceipt revision_id must not be negative")
        if not self.revision_timestamp.strip():
            raise ValueRefError("SourceReceipt revision_timestamp must not be empty")


def live_registry(registry: ValueRegistry) -> Mapping[str, Mapping[str, object]]:
    """The live registry mapping for one member of the union."""
    if registry == "ITEM_EFFECTS":
        return item_effects.ITEM_EFFECTS
    if registry == "ALLY_ITEM_EFFECTS":
        return item_effects.ALLY_ITEM_EFFECTS
    if registry == "RUNE_EFFECTS":
        return rune_effects.RUNE_EFFECTS
    raise ValueRefError(
        f"{registry!r} is not one of {sorted(VALUE_REGISTRIES)} — a declaration "
        "may only reference a registry that owns runtime numbers (D-46)"
    )
