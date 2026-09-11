"""One home for what a charge ability's cooldown means.

A charge ability carries two cached timers twelve times apart: ``cooldown``
is the short gap the game enforces between two casts already banked (Rumble
E: 0.5s), and ``rechargeRate`` is what it costs to bank one cast at all (6s).
Pricing the first as the recast cadence schedules a cast every half second,
which is the defect this module closes: the repo's own Rumble notes measured
16 basic-ability casts in a ten-second fight where the kit affords about
three.

So ``cooldown`` on an engine entry means one thing everywhere: the time to
regain one cast. For a charge slot that is the recharge, and a slot whose
cached ability carries a ``rechargeRate`` either prices it already or
declares a :class:`ChargeRule`, which prices it here. A slot that prices the
short timer by accident fails its parse naming both numbers; the cache
decides which slots are charge slots, so a champion reworked into charges
fails the day its cache changes rather than quietly gaining casts.

How many casts a slot banks is cached too, in one of two shapes: a
``Maximum charges`` leveling row (Gangplank E 3/3/4/4/5, Teemo R 3/4/5,
Taric Q 1/2/3/4/5) or the stocking sentence every other charge ability
carries ("Rumble periodically stocks an Electro Harpoon charge, up to a
maximum of 2"). Nothing here invents a count: a slot whose cache states
neither fails, and only a module's reviewed ``charges`` answers it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .slot_extract import extract_cooldown, extract_value
from .slot_control import extract_recharge

# Cached timers are wiki decimals and equality between two of them is exact
# well inside this. It is a float-noise guard, not a tolerance for numbers
# that disagree.
_SAME_SECOND = 1e-9

# "…periodically stocks a Seed charge, up to a maximum of 2." The stocking
# verb is required: "stacking up to 2 times" on the same page is Rumble E's
# DEBUFF limit, and a looser pattern reads it as a charge count.
_STOCK_SENTENCE = re.compile(r"stocks?\b[^.]*?up to a maximum of (\d+)", re.IGNORECASE)
_MAX_CHARGE_ROW = "maximum charges"


@dataclass(frozen=True)
class ChargeRule:
    """One module's reviewed answer for one charge slot.

    Declaring the rule is what hands the slot's cadence to this module: the
    entry's cooldown becomes the cached recharge and its stock the cached
    count. ``why`` is the review, and it is required, because a reader
    meeting a charge slot needs to know someone looked.

    ``charges`` overrides the cached stock, for the slot whose cache states
    no count; ``authored_cadence`` says the module prices a recast timer of
    its own (a folded haste, a resource, a reviewed rework), which turns off
    the cadence rewrite and the equality check and nothing else.
    """

    why: str
    charges: int | None = None
    authored_cadence: bool = False

    def __post_init__(self) -> None:
        if not self.why.strip():
            raise ValueError("ChargeRule must carry its review in why")
        if self.charges is not None and self.charges < 1:
            raise ValueError(
                f"ChargeRule charges must be at least 1, got {self.charges}"
            )


def _slot_prose(ability_json: Mapping[str, Any]) -> str:
    """Every sentence the cache carries about one ability, in one string."""
    parts: list[str] = []
    for key in ("notes", "blurb"):
        text = ability_json.get(key)
        if text:
            parts.append(str(text))
    for effect in _rows(ability_json, "effects"):
        description = effect.get("description")
        if description:
            parts.append(str(description))
    return " ".join(parts)


def _rows(payload: Mapping[str, Any], key: str) -> tuple[Any, ...]:
    """One cached list, or no rows when the cache carries none."""
    rows = payload.get(key)
    return tuple(rows) if rows else ()


def _cached_stock(ability_json: Mapping[str, Any], rank: int) -> int | None:
    """The banked cast count the cache states for this slot at this rank."""
    for effect in _rows(ability_json, "effects"):
        for leveling in _rows(effect, "leveling"):
            attribute = leveling.get("attribute")
            if attribute is None:
                continue
            attribute = str(attribute).strip()
            if attribute.lower() == _MAX_CHARGE_ROW:
                return int(extract_value(ability_json, attribute, rank))
    match = _STOCK_SENTENCE.search(_slot_prose(ability_json))
    return int(match.group(1)) if match else None


def stamp_charge_cadence(
    entry: dict[str, Any],
    ability_json: Mapping[str, Any] | None,
    rule: ChargeRule | None,
    *,
    champion_name: str,
    slot: str,
    rank: int,
    level: int,
) -> None:
    """Price a charge slot's cadence and stock, or refuse the slot's parse."""
    ability = dict(ability_json) if ability_json else {}
    if not _rows(ability, "rechargeRate"):
        if rule is not None:
            raise ValueError(
                f"{champion_name} {slot}: ChargeRule declared for a slot whose "
                "cached ability carries no rechargeRate"
            )
        return
    if "cooldown" not in entry:
        # Not a castable entry, so it prices no cadence and there is none to
        # get wrong: a charge slot a module emits as state only.
        return
    recharge = extract_recharge(ability, rank, level=level)
    between = extract_cooldown(ability, rank, level=level)
    if rule is None:
        priced = float(entry["cooldown"])
        raise ValueError(
            f"{champion_name} {slot} is a charge ability and declares no "
            f"ChargeRule: its cached rechargeRate is {recharge:g}s and the "
            f"cached cooldown, {between:g}s, is the gap between two banked "
            f"casts, not the time to bank one (the slot prices {priced:g}s "
            "today). Declaring the rule prices the cached recharge and the "
            "cached stock; charges and authored_cadence are how a module "
            "keeps a number of its own, and why says which and for what."
        )
    if not rule.authored_cadence:
        entry["cooldown"] = recharge
    entry["charge_between_casts"] = between
    charges = rule.charges if rule.charges is not None else _cached_stock(ability, rank)
    if charges is None:
        raise ValueError(
            f"{champion_name} {slot}: the cache states no charge stock — no "
            "'Maximum charges' leveling row and no stocking sentence — so the "
            "module's ChargeRule must carry the reviewed count in charges"
        )
    if charges > 1:
        entry["charge_pool"] = charges
