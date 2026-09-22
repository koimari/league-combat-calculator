"""What each grey-health champion banks, and the cached rows those rates are read
against."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..champions.inputs import declared_option_defaults
from ..champions.skill_orders import get_ability_rank
from ..champions.slot_extract import extract_cooldown
from ..composed_event_row import row_damage, row_raw_damage

# ─────────────────────────────────────────────────────────────────────────
# Grey-health primitive (E8a)
# ─────────────────────────────────────────────────────────────────────────
# Grey-health champions store a sourced portion of post-mitigation damage
# TAKEN as a grey pool on their health bar and pay it back as a heal when
# their active consumes the pool.  The 1v1 heal derivation
# (``healing.derive_self_healing``) only sees the main's OUTGOING events,
# so the receipts are authored here against the incoming ledger: the
# main-as-defender's pair events accumulate the sourced percentage, and
# each consume heals the sourced portion.  Every ratio is pinned from
# data/champions.json prose or leveling rows (citations inline below); no
# value is invented.  The authored heals carry fixed sourced amounts (the
# pair engine's post-mitigation values) so the ordered walk and the
# compiled optimizer walk apply byte-identical numbers; walk-time state
# gates (spell shields, stasis, redirects) are documented boundaries that
# would require a stateful per-event pool, which the 1v1 receipt does not
# model.
#
# Pyke P (Gift of the Drowned Ones) — data/champions.json P prose only:
#   "Pyke stores 9% (+ 0.2% per 1 Lethality) of the post-mitigation damage
#   he takes from enemy champions as grey health ..., increased to 40%
#   (+ 0.4% per 1 Lethality) while there are two or more visible enemy
#   champions nearby. He can store up to 80 (+ 800% bonus AD) grey health,
#   with an upper cap of 55% of his maximum health."  "While Pyke is not
#   visible to enemies, he rapidly consumes his grey health to heal for the
#   same amount."  Out-of-vision is a boundary the 1v1 ledger does not
#   model, so the consume is documented, not authored as an in-window heal.
_PYKE_P_STORE_RATIO = 0.09


_PYKE_P_STORE_PER_LETHALITY = 0.002


_PYKE_P_STORE_MULTI_RATIO = 0.40


_PYKE_P_STORE_MULTI_PER_LETHALITY = 0.004


_PYKE_P_STORE_FLAT_CAP = 80.0


_PYKE_P_STORE_BONUS_AD_CAP_RATIO = 8.0  # "80 (+ 800% bonus AD)"


_PYKE_P_STORE_MAX_HEALTH_CAP_RATIO = 0.55


# Rengar W (Battle Roar) — data/champions.json W prose only (the W
# leveling rows carry the ability's magic damage, not a heal amount):
#   "Rengar stores 50% of the post-mitigation damage he has taken in the
#   last 1.5 seconds as grey health ... consuming his grey health to heal
#   for the same amount."  The active heals 100% of the stored pool, i.e.
#   50% of the post-mitigation damage taken in the 1.5 s before the cast.
#   A same-timestamp incoming packet resolves before the cast's heal (the
#   ledger's damage-before-heal phase order), so the window is inclusive.
_RENGAR_W_STORE_RATIO = 0.50


_RENGAR_W_STORE_WINDOW_SECONDS = 1.5


_RENGAR_W_CONSUME_HEAL_RATIO = 1.0


# Tahm Kench E (Thick Skin) — leveling rows:
#   "Damage Stored into Grey Health" 15/23/31/39/47 by E rank (1 enemy),
#   "Increased Damage Stored into Grey Health" 42/44/46/48/50 with 2+
#   visible enemies, pool cap "300% of his maximum health".  The heal is
#   the out-of-combat consume ("after 4 seconds without taking damage ...
#   restore 60% : 100% (based on level) of the amount") whose level row
#   "Max Health Damage" carries 60 : 100 (based on level).  The E ACTIVE
#   ("Tahm Kench converts his current grey health into a shield that lasts
#   for 2.5 seconds") pays the pool as a SHIELD instead, on E's own cached
#   3 s haste-scaled cooldown.  It is a player decision, so the module
#   declares it as the ``e_convert_grey_shield`` option and the press
#   schedule is the earliest-available convention Mordekaiser's recast
#   already uses; with the option off nothing presses and the pool pays
#   the out-of-combat heal exactly as before.  The consume is modeled as
#   one lump heal at the 4 s boundary; the wiki's 10%-max-health-per-
#   0.264 s tick delivery is a rate detail with the same total.
_TAHM_E_STORE_RANK = (0.15, 0.23, 0.31, 0.39, 0.47)


_TAHM_E_STORE_MULTI_RANK = (0.42, 0.44, 0.46, 0.48, 0.50)


_TAHM_E_STORE_CAP_RATIO = 3.0


_TAHM_E_OUT_OF_COMBAT_SECONDS = 4.0


_TAHM_E_SHIELD_DURATION_SECONDS = 2.5


# Mordekaiser W (Indestructible) — data/champions.json W prose:
#   "stores 45% of the post-mitigation damage he deals and 7.5% of the
#   pre-mitigation damage he takes ... up to 30% of his maximum health."
#   Recast ("Indestructible can be recast after 0.5 seconds while the
#   shield is active ... consuming the remaining shield, healing for a
#   portion of the amount") pays the "Shield to Healing" leveling row
#   35/37.5/40/42.5/45 by W rank of the shield amount (the pool at the
#   first W cast; the model presses the recast at its earliest available
#   time — the exact moment is a player decision, documented boundary).
#   The Potential Shield decay and the active shield's exponential decay
#   are state, not modeled.
_MORDE_W_STORE_DEALT_RATIO = 0.45


_MORDE_W_STORE_TAKEN_PRE_RATIO = 0.075


_MORDE_W_STORE_CAP_RATIO = 0.30


_MORDE_W_SHIELD_TO_HEALING_RANK = (0.35, 0.375, 0.40, 0.425, 0.45)


_MORDE_W_RECAST_AVAILABLE_SECONDS = 0.5


# Locke W (Soul Ignition) — data/champions.json W prose:
#   "He also stores an amount of grey health on his health bar equal to
#   100% of the post-mitigation damage he takes from enemy champions, up
#   to a cap ... Recast: Locke ends Soul Ignition and consumes his grey
#   health to heal for the same amount."  The cap is the leveling row
#   "Damage taken grey health cap" (40/60/80/100/120 by W rank + 100%
#   AP); the storage window is the 6-second active ("ignites his soul
#   for 6 seconds").  The recast is available after 0.5 s and "does so
#   automatically afterwards" — the auto-recast at the 6 s boundary is
#   the deterministic consume.  The additional pool from Soul Ignition's
#   health cost and the missing-health bonus ("increased by up to
#   40 : 200 (based on level) (+ 20% AP) based on his missing health")
#   are dynamic self-state and remain documented boundaries, exactly as
#   the E1-b6 review scoped them.
_LOCKE_W_STORE_RATIO = 1.0


_LOCKE_W_STORE_WINDOW_SECONDS = 6.0


_LOCKE_W_AUTO_RECAST_SECONDS = 6.0


_LOCKE_W_CONSUME_HEAL_RATIO = 1.0


def _grey_leveling_values(ability: Mapping[str, Any], attribute: str) -> list[float]:
    """Read one leveling attribute's first modifier value array."""
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            modifiers = leveling.get("modifiers", [])
            if not modifiers:
                continue
            values = modifiers[0].get("values", [])
            if values:
                return [float(value) for value in values]
    return []


def _pyke_store_ratio(stats: Mapping[str, float], enemy_count: int) -> float:
    """The share of damage taken Pyke banks, at this lethality and enemy count.

    Both the pool and the per-event receipt price the same share, so the
    two read one formula.
    """
    lethality = float(stats.get("lethality", 0.0) or 0.0)
    if enemy_count >= 2:
        return _PYKE_P_STORE_MULTI_RATIO + (
            _PYKE_P_STORE_MULTI_PER_LETHALITY * lethality
        )
    return _PYKE_P_STORE_RATIO + (_PYKE_P_STORE_PER_LETHALITY * lethality)


def _grey_level_ratio(ability: Mapping[str, Any], attribute: str, level: int) -> float:
    """One level-indexed sourced percentage (an 18+ entry row)."""
    values = _grey_leveling_values(ability, attribute)
    if not values:
        return 0.0
    index = min(max(int(level), 1) - 1, len(values) - 1)
    return float(values[index]) / 100.0


def _declared_option(
    champion: str, options: Mapping[str, Any] | None, key: str
) -> bool:
    """One champion option, falling back to the module's own declared row."""
    if options is not None and key in options:
        return bool(options[key])
    return bool(declared_option_defaults(champion)[key])


def _grey_cooldown(
    ability: Mapping[str, Any], rank: int, stats: Mapping[str, float]
) -> float:
    """One cached ability cooldown at a rank, after ability haste.

    Thick Skin's press cadence hangs off this number, so a missing cooldown
    row raises rather than pricing a zero-cooldown press loop.
    """
    base = extract_cooldown(dict(ability), rank)
    if base <= 0.0:
        raise ValueError(
            "grey-health press cadence needs a cached cooldown row; "
            f"ability {ability.get('name')!r} declares none"
        )
    haste = max(0.0, float(stats.get("ability_haste", 0.0) or 0.0))
    return base * 100.0 / (100.0 + haste)


def _press_thick_skin(
    shields: list[tuple[float, str, float, float]],
    press_time: float,
    banked: float,
    duration: float,
) -> float:
    """One Thick Skin press: the bank becomes a shield, or stays banked.

    Returns the grey health still on the bar afterwards, so a press the
    fight window never reaches consumes nothing.
    """
    if banked <= 0.0 or press_time > duration:
        return banked
    shields.append(
        (
            press_time,
            "Thick Skin (grey health)",
            banked,
            _TAHM_E_SHIELD_DURATION_SECONDS,
        )
    )
    return 0.0


def _grey_ability(champion_data: Mapping[str, Any], slot: str) -> dict[str, Any]:
    """Return one ability's first JSON entry for a slot (lists allowed)."""
    abilities = champion_data.get("abilities")
    if not isinstance(abilities, Mapping):
        return {}
    entry = abilities.get(slot)
    if isinstance(entry, list):
        entry = entry[0] if entry else None
    return dict(entry) if isinstance(entry, Mapping) else {}


def _grey_health_event_receipt(
    name: str,
    level: int,
    stats: Mapping[str, float],
    enemy_count: int,
    event: Mapping[str, Any],
    *,
    incoming: bool,
    ability_ranks: Mapping[str, int] | None = None,
) -> float | None:
    """One event's sourced grey-health contribution for the public receipt.

    ``incoming=True`` prices a packet the main TAKES, ``incoming=False`` a
    packet the main DEALS (Mordekaiser's dealt term).  Returns None when
    the champion authors no receipt for that direction.
    """
    if name == "Pyke":
        if not incoming:
            return None
        ratio = _pyke_store_ratio(stats, enemy_count)
        return ratio * max(0.0, row_damage(event))
    if name == "Rengar":
        if not incoming:
            return None
        return _RENGAR_W_STORE_RATIO * max(0.0, row_damage(event))
    if name == "Tahm Kench":
        if not incoming:
            return None
        ability_rank = int(ability_ranks.get("E", 0) or 0) if ability_ranks else 0
        if ability_rank == 0:
            ability_rank = max(1, int(get_ability_rank("E", level, name)))
        rank_row = _TAHM_E_STORE_MULTI_RANK if enemy_count >= 2 else _TAHM_E_STORE_RANK
        ratio = rank_row[min(ability_rank, len(rank_row)) - 1]
        return ratio * max(0.0, row_damage(event))
    if name == "Mordekaiser":
        damage = max(0.0, row_damage(event))
        if incoming:
            # A packet priced with no pre-mitigation figure banks the
            # post-mitigation one, which is all that row states.
            raw = row_raw_damage(event)
            return _MORDE_W_STORE_TAKEN_PRE_RATIO * max(
                0.0, damage if raw is None else raw
            )
        return _MORDE_W_STORE_DEALT_RATIO * damage
    if name == "Locke":
        if not incoming:
            return None
        return _LOCKE_W_STORE_RATIO * max(0.0, row_damage(event))
    return None
