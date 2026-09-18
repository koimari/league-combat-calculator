"""Presence of Mind's takedown restore, read back off a finished fight result.

The damage half rides the mana walk's own timeline, because the rotation
plan holds every trigger time before the walk runs. The takedown half
cannot: the takedown is a damage outcome, so it lands here, post-hoc, dated
at the scored takedown the same instant Triumph's heal is paid on. The
receipt is applied through the real ledger account seeded from the
section's own closings, so capping and the receipt shape are the walk's,
not a second implementation of them.
"""

from collections.abc import Mapping
from typing import Any

from . import item_effects
from .fight_params import FightParams
from .item_sustain_events import _timestamped_damage_events
from .resource_events import (
    OP_GAIN,
    RESOURCE_KIND_MANA,
    TIER_RESTORE,
    ResourceEvent,
)
from .resource_ledger import ResourceLedger
from .rune_effects import RunePage, RuneRestoreEffect, resolve_rune_page


def _scored_takedown_time(
    result: Mapping[str, Any], delay_seconds: float
) -> float | None:
    """The takedown instant, or None when the target survived.

    The rule Triumph's heal is paid on: at or below zero health, dated at
    the window's last damage instance plus the rune's own delay, which is at
    or after the instance that crossed zero.
    """
    if float(result.get("target_ending_health", 1.0) or 0.0) > 0.0:
        return None
    rows = _timestamped_damage_events(result)
    if not rows:
        return None
    return float(rows[-1]["time"]) + delay_seconds


def apply_rune_restore_takedown(result: dict[str, Any], params: FightParams) -> None:
    """Pay the takedown half into the mana ledger, in place.

    Every gate is read, never assumed: the section must be a mana account
    (a holder with no mana pool and an energy holder walk none), the target
    must be a champion (a minion is not a champion takedown), and the fight
    must have scored one. The amount is the rune's share of the closing
    maximum — the maximum only grows, so against a Manaflow holder who grew
    it after the takedown this is a ceiling, which the rune discloses — and
    it is capped against the closing pool, exact when the kill ended the
    spending and a ceiling when the takedown landed at a full pool. A
    restore that would have enabled an omitted cast is not replayed through
    admission: the ledger moves and damage holds, which is a floor in the
    rare fight that omits casts for mana.
    """
    ledger_section = result.get("resource_ledger")
    if not isinstance(ledger_section, dict) or not ledger_section:
        return
    if ledger_section.get("kind") != RESOURCE_KIND_MANA:
        return
    if params.target_class != item_effects.DEFAULT_TARGET_CLASS:
        return
    page: RunePage | None = params.rune_page
    if page is None:
        return
    effects = [
        effect
        for effect in resolve_rune_page(page)
        if isinstance(effect, RuneRestoreEffect)
    ]
    if not effects:
        return
    receipts = ledger_section.get("receipts")
    if not isinstance(receipts, list):
        return
    owner = str(ledger_section.get("owner", "main"))
    closing_maximum = float(ledger_section.get("closing_maximum", 0.0) or 0.0)
    closing_current = float(ledger_section.get("closing_current", 0.0) or 0.0)
    for effect in effects:
        moment = _scored_takedown_time(result, effect.takedown_delay_seconds)
        if moment is None:
            continue
        amount = effect.takedown_mana_ratio * closing_maximum
        if not amount > 0.0:
            continue
        account = ResourceLedger(
            owner,
            kind=RESOURCE_KIND_MANA,
            maximum=closing_maximum,
            current=closing_current,
        )
        receipt = account.apply(
            ResourceEvent(
                owner=owner,
                kind=RESOURCE_KIND_MANA,
                operation=OP_GAIN,
                amount=amount,
                time=moment,
                source=effect.source,
                sequence=len(receipts),
                tier=TIER_RESTORE,
            )
        )
        receipts.append(receipt.public())
        closing_current = account.account.current
    ledger_section["closing_current"] = round(closing_current, 6)
    result["resource_remaining"] = closing_current
