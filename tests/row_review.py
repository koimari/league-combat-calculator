"""Shared reads for the ability-row reviews.

The generated packet asset (``static/reviewed-packets.json``) picks one
``effects[].leveling[]`` row per ability, and its picker has no way to
tell a leg of a multi-hit cast from the cast's own total.  Where a named
module supersedes that pick, its test makes the same two claims:

* the module prices the **cached** row it says it prices — not a number
  written into the module — which is what :func:`cached_row` reads; and
* that row is not the one the generated packet still carries, which is
  what :func:`packet_row_total` shows.

Both sides are computed from the same stats and the same rank, so a
patch that moves the cache moves both together and the ratio between
them is the reviewed fact.

This is a test helper, not a test module: it holds no assertions.
"""

from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.slotlib import extract_named
from src.calculator.scenario import load_public_champion

# One fixed, explicit stat block, so every row that scales resolves and
# both sides of a comparison see the same inputs.
STATS = {
    "ability_power": 200.0,
    "attack_damage": 200.0,
    "base_attack_damage": 100.0,
    "bonus_attack_damage": 100.0,
    "health": 2000.0,
    "base_health": 1200.0,
    "bonus_health": 800.0,
    "armor": 100.0,
    "bonus_armor": 50.0,
    "magic_resistance": 60.0,
    "bonus_magic_resistance": 30.0,
    "max_mana": 1000.0,
    "bonus_mana": 400.0,
}
TARGET = {
    "target_max_health": 2500.0,
    "target_current_health": 2500.0,
    "target_missing_health": 0.0,
}
RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _slot_entry(champion, slot, options):
    parsed = parse_champion_abilities(
        load_public_champion(champion),
        18,
        STATS["ability_power"],
        RANKS,
        champion_stats=dict(STATS),
        target_stats=dict(TARGET),
        champion_options=options or None,
    )
    return parsed[slot]


def priced(champion, slot, **options):
    """The raw total the champion's module prices for one slot."""
    return _slot_entry(champion, slot, options)["total_raw"]


def parts(champion, slot, **options):
    """The damage parts the champion's module authors for one slot.

    A part's ``time_offset`` / ``hit_interval`` is the module's authored
    hit schedule, which is what puts the row in the fight's event ledger
    and lets a reviewed ``cc_kind`` reach a control-armed item.
    """
    return _slot_entry(champion, slot, options)["parts"]


def cached_row(champion, slot, attribute, entry=0):
    """One named cached leveling row, resolved at the same rank and stats."""
    ability = load_public_champion(champion)["abilities"][slot][entry]
    return extract_named(ability, attribute, RANKS[slot], dict(STATS), dict(TARGET))


def packet_row(champion, slot, module, variant=None):
    """The base array the generated packet still carries for one slot."""
    spec = module.PACKET_SPEC["slots"][slot]
    if variant is not None:
        spec = spec["variants"][variant]
    return spec["base"]
