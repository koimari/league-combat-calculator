"""What a serving surface may rank, read back off a published disposition map."""

from __future__ import annotations

from collections.abc import Mapping

from ...ability_spec import Disposition
from ...quantity import Measured, Quantity, StructuralZero, Withheld
from .view_tag import UnrankableNumber, ViewTag


def refuse_previewed(
    dispositions: Mapping[str, Mapping[str, object]], *, surface: str
) -> None:
    """Refuse a payload any of whose numbers is a preview, naming them.

    Asks the payload's own map rather than a list of the leaves a scorer
    happens to read, so retagging *any* field ``THEORETICAL`` makes the
    surface fail.  A derived figure is covered too, because the leaves it is
    derived from are in the map.
    """
    previewed = [
        path
        for path, entry in dispositions.items()
        if entry["view_tag"] != ViewTag.APPLIED.value
    ]
    if previewed:
        raise UnrankableNumber(surface, "a previewed number", previewed)


def published_tag(
    dispositions: Mapping[str, Mapping[str, object]], path: str, *, surface: str
) -> ViewTag:
    """What the payload says the number at *path* means, or a refusal.

    A leaf with no entry is refused rather than assumed applied: a number
    with no published meaning is what a fold may not carry.
    """
    try:
        entry = dispositions[path]
    except (KeyError, TypeError):
        raise UnrankableNumber(surface, "a number no entry names", [path]) from None
    return ViewTag(entry["view_tag"])


def published_quantity(
    dispositions: Mapping[str, Mapping[str, object]],
    path: str,
    value: float,
    *,
    surface: str,
) -> Quantity:
    """The quantity the payload published at *path* — disposition and all.

    The companion of :func:`published_tag`, and the half without which
    :class:`Quantity`'s propagation never reaches a serving surface.  A
    ``WITHHELD`` leaf is **absent** from the payload by ruling, so a consumer
    that reads it as ``payload.get(path, 0.0)`` gets a zero no rule computed
    and folds it into a total that then claims to be measured — the incident,
    at the aggregate, inside the one surface the algebra exists to protect.
    Reading the entry rather than the leaf is what makes the refusal
    propagate.

    ``STRUCTURAL_ZERO`` folds as ``0.0`` and therefore cannot move a number;
    it is reconstructed anyway so the total's disposition is derived from what
    the payload said rather than from what the caller assumed.  ``STARVED``
    never reaches a payload — :func:`serialize_leaf` raises while producing
    it — so an entry claiming it is a malformed payload and is refused here
    rather than reconstructed into a raise somewhere further along.
    """
    try:
        entry = dispositions[path]
    except (KeyError, TypeError):
        raise UnrankableNumber(surface, "a number no entry names", [path]) from None
    disposition = entry.get("disposition")
    if disposition == Disposition.WITHHELD.value:
        receipts = tuple(entry.get("receipts") or ())
        if not receipts:
            # ``Withheld`` refuses a receiptless refusal at construction, and
            # that raise is a bare ``ValueError`` from the vocabulary leaf.
            # A surface that promises to refuse a malformed payload has to
            # refuse it in its *own* words, or one class of malformed entry
            # leaves by a door no caller of this function is watching.
            # Unreachable from a ``serialize_leaf`` payload -- it always
            # writes the receipts -- which is exactly why it is caught here
            # rather than trusted.
            raise UnrankableNumber(
                surface, "a withheld entry carrying no receipt", [path]
            )
        return Withheld(receipts=receipts)
    if disposition == Disposition.STRUCTURAL_ZERO.value:
        reason = str(entry.get("reason") or "")
        if not reason.strip():
            # The same door, one disposition over: a declared zero with no
            # declaration is an ordinary zero, and ``StructuralZero`` says so
            # with a ``ValueError`` this surface would otherwise pass on.
            raise UnrankableNumber(
                surface, "a structural zero carrying no reason", [path]
            )
        return StructuralZero(reason=reason)
    if disposition != Disposition.MEASURED.value:
        raise UnrankableNumber(
            surface, f"a {disposition!r} disposition no payload may carry", [path]
        )
    return Measured(amount=value)
