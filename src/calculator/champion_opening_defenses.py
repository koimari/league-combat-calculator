"""The defences a champion's kit has up before the first cast: Galio's shield and the revives."""

from collections.abc import Mapping

from .champions.skill_orders import get_ability_rank
from .item_behavior import DefenseField, DefenseMechanic
from .item_behavior_catalog import DEFENSE_RECEIPTS
from .starting_defenses import _DefenseLedger

_GALIO_SHIELD_MIN_PERCENT = 7.5


_GALIO_SHIELD_MAX_PERCENT = 13.5


_GALIO_NOTE = "Anti-Magic Bulwark is ready because Galio has not recently taken damage."


# E8d follow-up: sourced revive-source labels for champions whose modules
# declare ``starting_revive_defense``; used by the ledger's revive receipts.
_CHAMPION_REVIVE_SOURCES = {
    "Anivia": "Rebirth",
    "Zac": "Cell Division",
    "Zilean": "Chronoshift",
}


_GALIO = "Galio"


def _apply_galio(
    ledger: _DefenseLedger, champion_name: str, level: int, stats: Mapping[str, float]
) -> None:
    """Galio's Shield of Durand, one of two defences no item carries."""
    if champion_name != _GALIO or get_ability_rank("W", level, _GALIO) < 1:
        return
    maximum_health = float(stats["health"])
    percent = (
        _GALIO_SHIELD_MIN_PERCENT
        + (_GALIO_SHIELD_MAX_PERCENT - _GALIO_SHIELD_MIN_PERCENT) * (level - 1) / 17.0
    )
    ledger.write(DefenseField.MAGIC_SHIELD, maximum_health * percent / 100.0)
    ledger.notes.append(_GALIO_NOTE)
    ledger.cite(
        DefenseMechanic.SHIELD_OF_DURAND,
        _GALIO,
        DEFENSE_RECEIPTS[DefenseMechanic.SHIELD_OF_DURAND],
    )


def _champion_starting_revive(
    champion_name: str, level: int, stats: dict[str, float]
) -> dict[str, float]:
    """Resolve a champion module's sourced revive fields, if it declares any.

    Mirrors the healing_reduction champion-source lookup: modules that
    implement ``starting_revive_defense`` (Anivia Rebirth, Zac Cell
    Division, Zilean Chronoshift) return the revive payload; every other
    champion fails closed with zero revive fields.
    """
    # pylint: disable-next=import-outside-toplevel
    from .champions import _CHAMPION_MODULES

    module = _CHAMPION_MODULES.get(champion_name)
    if module is None:
        return {}
    resolver = getattr(module, "starting_revive_defense", None)
    if resolver is None:
        return {}
    return resolver(level, stats)


def _apply_champion_revive(
    ledger: _DefenseLedger, champion_name: str, level: int, stats: dict[str, float]
) -> None:
    """A champion passive's own resurrection, which no item declares."""
    fields = _champion_starting_revive(champion_name, level, stats)
    if not fields:
        return
    ledger.write(
        DefenseField.REVIVE_HEALTH_AMOUNT,
        float(fields.get("revive_health_amount", 0.0)),
    )
    ledger.write(DefenseField.REVIVE_DELAY, float(fields.get("revive_delay", 0.0)))
    ledger.write(
        DefenseField.REVIVE_COOLDOWN, float(fields.get("revive_cooldown", 0.0))
    )
    ledger.write(
        DefenseField.REVIVE_SOURCE, _CHAMPION_REVIVE_SOURCES.get(champion_name, "")
    )
