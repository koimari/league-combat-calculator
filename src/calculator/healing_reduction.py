"""Sourced healing-reduction triggers for the coupled combat timeline."""

from __future__ import annotations

from importlib import import_module
from collections.abc import Iterable, Mapping
from typing import Any

from .item_source import effect_text

# The cached item packets describe the trigger and three-second window.  The
# patch-wide Grievous Wounds rule supplies the current 40% reduction.
GRIEVOUS_WOUNDS_FACTOR = 0.60
GRIEVOUS_WOUNDS_DURATION = 3.0


def _trigger_damage_types(text: str) -> frozenset[str]:
    lowered = text.lower()
    if "grievous wounds" not in lowered or "inflict" not in lowered:
        return frozenset()
    if "when struck" in lowered:
        # Reactive anti-heal (Bramble Vest's Thorns) wounds whoever strikes
        # the wearer, not the wearer's own targets — the coupled timeline
        # applies it from incoming attack events instead.
        return frozenset()
    damage_types: set[str] = set()
    if "physical damage" in lowered:
        damage_types.add("physical")
    if "magic damage" in lowered:
        damage_types.add("magic")
    return frozenset(damage_types)


def healing_reduction_profiles(
    items: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Return exact anti-heal trigger packets from cached Wiki text.

    A packet is accepted only when both the Grievous Wounds marker and its
    damage-type trigger are present, so ambiguous effects fail closed.
    """
    profiles: list[dict[str, Any]] = []
    for item in items:
        item_name = str(item.get("name", ""))
        for passive in item.get("passives") or ():
            damage_types = _trigger_damage_types(effect_text(passive))
            if not damage_types:
                continue
            profiles.append(
                {
                    "item": item_name,
                    "source": str(passive.get("name") or "Grievous Wounds"),
                    "damage_types": damage_types,
                    "factor": GRIEVOUS_WOUNDS_FACTOR,
                    "duration": GRIEVOUS_WOUNDS_DURATION,
                }
            )
    return tuple(profiles)


def matching_healing_reduction(
    profiles: Iterable[dict[str, Any]],
    damage_type: str,
) -> tuple[dict[str, Any], ...]:
    """Return profiles whose Wiki trigger includes *damage_type*."""
    return tuple(
        profile
        for profile in profiles
        if damage_type in profile.get("damage_types", ())
    )


def champion_grievous_wound_sources(
    champion_data: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Return a reviewed champion's sourced Grievous Wounds packets.

    A champion module declares which of its abilities inflict Grievous
    Wounds (Katarina R Death Lotus, Varus E Hail of Arrows) through the
    ``GRIEVOUS_WOUNDS_SOURCES`` attribute; the patch-wide 40%-for-3s rule
    supplies strength and duration, and the cached ability JSON supplies
    the display label ("Katarina · Death Lotus").  Champions without the
    module attribute return no packets. Synthetic/development fixtures also
    have no production registration and must never invent a wound.
    """
    champion_name = str(champion_data.get("name", ""))
    # Resolved lazily so this module never participates in the package
    # import order; the champions registry is heavy and not needed unless
    # a wound-declaring module is actually on the roster.
    from .champions import _CHAMPION_MODULES  # pylint: disable=import-outside-toplevel

    module_name = _CHAMPION_MODULES.get(champion_name)
    if module_name is None:
        return ()
    package = f"{__name__.rsplit('.', 1)[0]}.champions"
    module = import_module(f".{module_name}", package=package)
    sources = getattr(module, "GRIEVOUS_WOUNDS_SOURCES", None)
    if not sources:
        return ()
    # A module may pin the exact wounding ability when the slot's first
    # cached entry is not the wounding one (Kled's Pocket Pistol is the
    # dismounted Q entry, not the mounted Bear Trap on a Rope).
    label_overrides = getattr(module, "GRIEVOUS_WOUNDS_SOURCE_LABELS", None) or {}
    abilities = champion_data.get("abilities") or {}
    packets: list[dict[str, Any]] = []
    for source_key in sources:
        entries = abilities.get(source_key) or []
        ability_name = ""
        if entries:
            ability_name = str(entries[0].get("name", "") or "")
        override = label_overrides.get(source_key)
        if override:
            label = f"{champion_name} · {override}"
        elif ability_name:
            label = f"{champion_name} · {ability_name}"
        else:
            label = f"{champion_name} · {source_key}"
        packets.append(
            {
                "source_key": str(source_key),
                "source": label,
                "factor": GRIEVOUS_WOUNDS_FACTOR,
                "duration": GRIEVOUS_WOUNDS_DURATION,
            }
        )
    return tuple(packets)
