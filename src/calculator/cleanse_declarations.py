"""The sourced item cleanse tooltips, one declaration per item, and the lookup over them."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from .champion_cleanses import CHAMPION_CLEANSE_DECLARATIONS, CHAMPION_CLEANSE_SOURCES
from .delivery_facts import PacketIdentity
from .item_effects import ally_item_effect_value, mercurial_quicksilver_movement


class CleanseActivation(
    PacketIdentity, Protocol
):  # pylint: disable=too-few-public-methods
    """One cleanse activation as :meth:`CleanseEligibility.decide` reads it.

    The walk builds it from the activating action, the recipient and holder
    ids, and the recipient's live control intervals.
    """

    event_id: str
    target: str
    holder: str
    active_controls: Sequence[Mapping[str, Any]]


#: The three active sources and the item each names (packet ``source`` /
#: ``source_key`` -> declaration item).  Item actives are authored with the
#: display source ("Item — Active"); the resolver accepts the item name
#: itself too.
CLEANSE_ACTIVE_SOURCES: dict[str, str] = {
    "Mikael's Blessing": "Mikael's Blessing",
    "Mikael's Blessing — Purify": "Mikael's Blessing",
    "Quicksilver Sash": "Quicksilver Sash",
    "Quicksilver Sash — Quicksilver": "Quicksilver Sash",
    "Mercurial Scimitar": "Mercurial Scimitar",
    "Mercurial Scimitar — Quicksilver": "Mercurial Scimitar",
}


MIKAELS_WORDING = (
    "Remove all crowd control debuffs (except Airborne, Blind, Disarm, "
    "Nearsight, and Suppression) from yourself or the target allied "
    "champion and heal the target for 100 to 250 (target's level)."
)


QUICKSILVER_WORDING = (
    "Removes all crowd control debuffs (except Airborne) from your champion."
)


MERCURIAL_WORDING = (
    "Removes all crowd control debuffs (except Airborne) from your champion "
    "and grants 50% bonus total movement speed and ghosting for 2 seconds."
)


#: Atom records from ``data/atoms/items.json`` (hashes independently
#: recomputed; the atomizer's keyword artifacts ``control.blind`` and
#: ``vision.sight`` on Mikael's are documented NOT consumable).
MIKAELS_HEAL_ATOM: dict[str, Any] = {
    "atom_id": "heal.flat",
    "behavior": "heal",
    "source": "Mikael's Blessing.actives[0].branches[0]",
    "name": "Purify",
    "values": [100.0, 250.0],
    "units": ["flat", "flat"],
    "evidence": ["active:Purify@kw:heal"],
    "hash": "cf9fe930ebd40602",
}


#: Rule 5: Quicksilver's percent and window live in ITEM_EFFECTS, and both
#: the atom receipt's ``values`` and the declaration below are that one read
#: — read at import, like Purify's pair, because the entry is code-owned and
#: refresh-inert (D-47).
MERCURIAL_MOVEMENT = mercurial_quicksilver_movement()


MERCURIAL_MOVEMENT_ATOM: dict[str, Any] = MERCURIAL_MOVEMENT["atom"]


def _cache_receipt(
    item: str,
    item_id: int,
    revision_id: int,
    wording: str,
) -> dict[str, Any]:
    """One cache receipt reproducing the sourced branch wording."""
    return {
        "label": f"Local League Wiki cache — {item} (data/items.json id {item_id})",
        "url": "https://wiki.leagueoflegends.com",
        "revision_id": revision_id,
        "revision_timestamp": "cached data (patch cache)",
        "cache_key": f"data/items.json[{item_id}].active[0].branches[0]",
        "wording": wording,
    }


#: The sourced declarations — one per item, read-only at runtime.  Every
#: categorical rule and atom hash is receipted; the matrix pins the exact
#: field sets (R4/R5/R20).
ITEM_CLEANSE_DECLARATIONS: dict[str, dict[str, Any]] = {
    "Mikael's Blessing": {
        "item": "Mikael's Blessing",
        "active_name": "Purify",
        "target_scope": "explicit_selected_ally",
        "excluded_control_kinds": (
            "airborne",
            "blind",
            "disarm",
            "nearsight",
            "suppression",
        ),
        "cooldown_seconds": None,
        "cooldown_source_gap": True,
        "heal": {
            # Rule 5: Purify's two numbers live in ALLY_ITEM_EFFECTS and are
            # read through the typed accessor, which raises naming the item
            # and the key if the registry ever loses one — never a literal
            # here that could outlive the source.  Read at import because
            # that registry is hand-authored and refresh-inert (D-47), so
            # there is no generation for a re-read to catch.
            "amount_min": ally_item_effect_value("Mikael's Blessing", "heal_min"),
            "amount_max": ally_item_effect_value("Mikael's Blessing", "heal_max"),
            "scaling": "target_level",
            "source": "Mikael's Blessing — Purify",
            "source_atoms": [dict(MIKAELS_HEAL_ATOM)],
        },
        "movement": None,
        "source_receipts": [
            _cache_receipt("Mikael's Blessing", 3222, 3984364, MIKAELS_WORDING)
        ],
        "source_atoms": [dict(MIKAELS_HEAL_ATOM)],
    },
    "Quicksilver Sash": {
        "item": "Quicksilver Sash",
        "active_name": "Quicksilver",
        "target_scope": "self",
        "excluded_control_kinds": ("airborne",),
        "cooldown_seconds": None,
        "cooldown_source_gap": True,
        "heal": None,
        "movement": None,
        "source_receipts": [
            _cache_receipt("Quicksilver Sash", 3140, 3729899, QUICKSILVER_WORDING)
        ],
        "source_atoms": [],
    },
    "Mercurial Scimitar": {
        "item": "Mercurial Scimitar",
        "active_name": "Quicksilver",
        "target_scope": "self",
        "excluded_control_kinds": ("airborne",),
        "cooldown_seconds": None,
        "cooldown_source_gap": True,
        "heal": None,
        "movement": {
            "amount": MERCURIAL_MOVEMENT["move_speed_percent"],
            "duration": MERCURIAL_MOVEMENT["duration_seconds"],
            "source": "Mercurial Scimitar — Quicksilver",
            "source_atoms": [dict(MERCURIAL_MOVEMENT_ATOM)],
        },
        "source_receipts": [
            _cache_receipt("Mercurial Scimitar", 3139, 3984461, MERCURIAL_WORDING)
        ],
        "source_atoms": [dict(MERCURIAL_MOVEMENT_ATOM)],
    },
}


def resolve_cleanse_item(source_or_item: str) -> str:
    """Resolve one packet source / item name to a declared cleanse.

    Fails closed (KeyError naming the source) when the source is not a
    declared cleanse active — a packet that cannot be attributed to a
    sourced declaration must never guess.
    """
    key = str(source_or_item or "").strip()
    if key in CLEANSE_ACTIVE_SOURCES:
        return CLEANSE_ACTIVE_SOURCES[key]
    if key in CHAMPION_CLEANSE_SOURCES:
        return CHAMPION_CLEANSE_SOURCES[key]
    raise KeyError(
        f"cleanse active source {key!r} is not a declared item — "
        "Mikael's Blessing / Quicksilver Sash / Mercurial Scimitar / "
        "Gangplank W only"
    )


def item_declaration(item: str) -> dict[str, Any]:
    """Return one item's sourced cleanse declaration, fail-closed."""
    if item in ITEM_CLEANSE_DECLARATIONS:
        return ITEM_CLEANSE_DECLARATIONS[item]
    if item in CHAMPION_CLEANSE_DECLARATIONS:
        return CHAMPION_CLEANSE_DECLARATIONS[item]
    raise KeyError(
        f"no cleanse declaration for item {item!r} — "
        "Mikael's Blessing / Quicksilver Sash / Mercurial Scimitar / "
        "Gangplank W only"
    )
