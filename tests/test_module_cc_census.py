"""Roster-wide census of where a kit's crowd control is declared (D5).

``MODULE_CC`` is the one declaration site, and it names every champion
slot the module emits. A slot whose control is one answer keeps the
constant there; a slot whose control varies within the cast, by part, by
option, by branch or by stack state, names itself ``CC_PER_PART`` and the
parts hold the answer. Nothing else may author a kind.

The census is the test because the failures it guards are counts. A
declaration drifting back out of ``MODULE_CC`` one module at a time is
invisible per module and obvious per roster, and so is the other count
this file owns: the slots whose declaration reaches no event row, where
the kit's control is real and the fight engine never sees it.
"""

import ast
from pathlib import Path

import pytest

from src.calculator.champions import (
    _CHAMPION_MODULES,
    get_champion_module_contract,
    parse_abilities,
)
from src.calculator.champions.engine import CC_PER_PART
from src.calculator.champions.module_contract import REQUIRED_CHAMPION_SLOTS
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats
from tests import cc_review

#: Slots whose control is not one constant, module -> slots.  Every entry
#: is a cast that lands two different answers (Zac's opening bounce
#: displaces and the rest slow), or one whose answer follows an option
#: (Aphelios' weapon, Sion's charge, Yasuo's two Q stacks) or the target's
#: own stack state (Annie's Pyromania charge, Kennen's Marks of the Storm).
PER_PART = {
    "Aatrox": {"Q", "W"},
    "Akali": {"Q"},
    "Alistar": {"E"},
    "Anivia": {"Q", "R"},
    "Annie": {"Q", "R", "W"},
    "Aphelios": {"P", "Q", "R"},
    "Aurelion Sol": {"R"},
    "Bard": {"P"},
    "Brand": {"Q", "R"},
    "Braum": {"P"},
    "Cassiopeia": {"R"},
    "Darius": {"E"},
    "Ekko": {"W"},
    "Evelynn": {"W"},
    "Fiddlesticks": {"Q"},
    "Fizz": {"E"},
    "Hwei": {"E", "Q", "R"},
    "Irelia": {"R"},
    "Ivern": {"R"},
    "Jayce": {"Q"},
    "K'Sante": {"W"},
    "Karma": {"W"},
    "Kayn": {"W"},
    "Kennen": {"E", "Q", "R", "W"},
    "Kled": {"Q"},
    "LeBlanc": {"E", "R"},
    "Lissandra": {"P"},
    "Lulu": {"W"},
    "Mel": {"E"},
    "Morgana": {"R"},
    "Ornn": {"R"},
    "Qiyana": {"Q"},
    "Rammus": {"W"},
    "Rengar": {"E"},
    "Samira": {"P"},
    "Sejuani": {"W"},
    "Shaco": {"R"},
    "Sion": {"Q"},
    "Sona": {"P"},
    "Swain": {"R"},
    "Tahm Kench": {"Q"},
    "Taliyah": {"E", "Q"},
    "Tryndamere": {"W"},
    "Twisted Fate": {"W"},
    "Warwick": {"E"},
    "Xayah": {"E"},
    "Xin Zhao": {"Q"},
    "Yasuo": {"Q"},
    "Yone": {"Q"},
    "Yorick": {"W"},
    "Zaahen": {"Q"},
    "Zac": {"R"},
    "Zilean": {"Q"},
    "Zyra": {"W"},
}

#: ``CC_PER_PART`` slots whose parts and authored events state no kind
#: under any option.  The sentinel points at the parts, and these are the
#: pointers that land on nothing today: the row is partless or coarse, so
#: no marker could ride it, or the branch that controls has no part of its
#: own yet.  Each module's comment carries the kit fact and the reason;
#: this is how many of them there are.
SILENT_PER_PART = frozenset(
    {
        ("Akali", "Q"),
        ("Anivia", "Q"),
        ("Anivia", "R"),
        ("Annie", "Q"),
        ("Annie", "W"),
        ("Annie", "R"),
        ("Aphelios", "P"),
        ("Bard", "P"),
        ("Brand", "Q"),
        ("Brand", "R"),
        ("Braum", "P"),
        ("Ekko", "W"),
        ("Kennen", "Q"),
        ("Kennen", "W"),
        ("Kennen", "E"),
        ("Kennen", "R"),
        ("Lissandra", "P"),
        ("Samira", "P"),
        ("Shaco", "R"),
        ("Sona", "P"),
        ("Tryndamere", "W"),
        ("Warwick", "E"),
        ("Xin Zhao", "Q"),
        ("Yorick", "W"),
        ("Zyra", "W"),
    }
)

#: Declared kinds no row of a real fight carries.  The kit applies the
#: control and the fight's ledger never shows it, so the item passives
#: armed by control (Fimbulwinter's Everlasting, Imperial Mandate's
#: Command) cannot read it: a utility cast that prices no damage and
#: authors no control event (Karthus' Wall of Pain), a rider on the auto
#: stream (Ashe's Frost Shot), or a passive whose control is stack state
#: the walk publishes as a schedule (Annie's Pyromania).
UNCARRIED = {
    ("Anivia", "W"): "knockback",
    ("Annie", "P"): "stun",
    ("Ashe", "P"): "slow",
    ("Caitlyn", "W"): "root",
    ("Camille", "R"): "knockback",
    ("Gnar", "W"): "stun",
    ("Gnar", "R"): "knockback",
    ("Illaoi", "E"): "slow",
    ("Janna", "R"): "knockback",
    ("Jarvan IV", "W"): "slow",
    ("Jayce", "E"): "knockback",
    ("Karthus", "W"): "slow",
    ("Kennen", "P"): "stun",
    ("Kha'Zix", "P"): "slow",
    ("Lulu", "R"): "knockup",
    ("Mordekaiser", "R"): "slow",
    ("Nautilus", "P"): "root",
    ("Singed", "W"): "slow",
    ("Taliyah", "W"): "knockback",
    ("Taliyah", "R"): "knockback",
    ("Twitch", "W"): "slow",
}

CHAMPIONS = sorted(_CHAMPION_MODULES)


def _source(name: str) -> ast.Module:
    module = get_champion_module_contract(name).module
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


def _variants(contract) -> list[dict]:
    """The option settings a declaration could hide behind: the defaults,
    each boolean flipped, each named choice, and each integer end."""
    out: list[dict] = [{}]
    for row in contract.options:
        if isinstance(row.get("default"), bool):
            out.append({row["key"]: not row["default"]})
        out.extend({row["key"]: choice["value"]} for choice in row.get("choices") or ())
        if row.get("type") == "int":
            out.append({row["key"]: row["min"]})
            out.append({row["key"]: row["max"]})
    return out


def _parsed_variants(name: str) -> list[dict]:
    contract = get_champion_module_contract(name)
    champion = get_champion(name)
    stats = calculate_total_stats(champion, 18, [])
    return [
        parse_abilities(
            name,
            champion,
            18,
            stats["ability_power"],
            champion_stats=stats,
            champion_options=variant,
        )
        for variant in _variants(contract)
    ]


def _slot_entries(parsed: list[dict], slot: str) -> list[dict]:
    key = "passive" if slot == "P" else slot
    return [entry for result in parsed if (entry := result.get(key))]


def _authored_kinds(entries: list[dict]) -> set[str]:
    """Every kind these entries state, on a part or on an authored event."""
    return {
        part.cc_kind
        for entry in entries
        for part in entry.get("parts") or ()
        if part.cc_kind
    } | {
        str(row.get("cc_kind"))
        for entry in entries
        for row in entry.get("damage_events") or ()
        if isinstance(row, dict) and row.get("cc_kind")
    }


def test_every_module_names_every_slot_it_emits():
    """The count D5 moves: no champion slot is left for a later reader to
    guess at, because an absent slot and a reviewed "none" read alike."""
    unnamed = {
        (name, slot)
        for name in CHAMPIONS
        for slot in REQUIRED_CHAMPION_SLOTS
        if slot in (contract := get_champion_module_contract(name)).slots
        and slot not in contract.cc_kinds
    }
    assert unnamed == set()
    declared = sum(len(get_champion_module_contract(n).cc_kinds) for n in CHAMPIONS)
    assert declared == 854


@pytest.mark.parametrize("name", CHAMPIONS)
def test_only_a_per_part_slot_authors_a_kind_on_its_parts(name):
    """The engine refuses a part-authored kind on any other slot, so this
    is what that refusal amounts to across the roster."""
    contract = get_champion_module_contract(name)
    champion = get_champion(name)
    stats = calculate_total_stats(champion, 18, [])
    parsed = parse_abilities(
        name, champion, 18, stats["ability_power"], champion_stats=stats
    )
    per_part = {slot for slot, kind in contract.cc_kinds.items() if kind == CC_PER_PART}
    assert per_part == PER_PART.get(name, set()), name
    for slot, kind in contract.cc_kinds.items():
        if kind in (CC_PER_PART, "none"):
            continue
        result_key = "passive" if slot == "P" else slot
        entry = parsed.get(result_key)
        if entry is None:
            continue
        assert {part.cc_kind for part in entry.get("parts") or ()} <= {kind}, (
            name,
            slot,
        )


@pytest.mark.parametrize("name", sorted(PER_PART))
def test_a_per_part_slot_authors_its_kind_or_is_pinned_as_silent(name):
    """The sentinel is a pointer, and a pointer at nothing is a silenced
    slot unless the roster says so.

    The parts must answer at the option defaults, with one boolean option
    flipped (Jayce's R is reviewed in hammer stance only) or under a named
    choice (Lulu's Whimsy on an enemy).  A branch that reviewed its way to
    no answer (Rammus' aggregated thorns row) is a branch, not the whole
    slot, so the slot still answers somewhere.
    """
    parsed = _parsed_variants(name)
    for slot in PER_PART[name]:
        entries = _slot_entries(parsed, slot)
        authored = bool(_authored_kinds(entries)) or any(
            entry.get("control_events") for entry in entries
        )
        assert authored is ((name, slot) not in SILENT_PER_PART), (name, slot)


@pytest.mark.parametrize("name", CHAMPIONS)
def test_a_live_declaration_reaches_the_fight_or_is_pinned_as_uncarried(name):
    """A declared kind no row of a real fight carries is control the item
    passives armed by it can never read, so it is counted here rather than
    left to the reader of one module's comment.

    Measured through the pair engine, not read off the parse: a coarse row
    still reaches the ledger at its cast boundary, and only the fight can
    say whether the marker arrived with it.
    """
    contract = get_champion_module_contract(name)
    live = {
        slot: kind
        for slot, kind in contract.cc_kinds.items()
        if kind not in (CC_PER_PART, "none")
    }
    pinned = {slot for champion, slot in UNCARRIED if champion == name}
    if not live:
        assert pinned == set(), name
        return
    carried = {
        (str(row.get("source_key")), str(row.get("cc_kind")))
        for row in cc_review.fight_ledger(name)
    }
    uncarried = {
        slot
        for slot, kind in live.items()
        if (("passive" if slot == "P" else slot), kind) not in carried
    }
    assert uncarried == pinned, name


def _authors_a_kind(keyword: ast.keyword) -> bool:
    """``cc_kind=`` that states a kind, not one that copies a part's own.

    Rebuilding a part field by field (Renata Glasc's E, Vladimir's E) reads
    ``part.cc_kind`` straight back; the module says nothing there.
    """
    value = keyword.value
    return not (isinstance(value, ast.Attribute) and value.attr == "cc_kind")


@pytest.mark.parametrize("name", CHAMPIONS)
def test_no_module_writes_a_cc_kind_outside_a_per_part_slot(name):
    """Source-level companion to the runtime rule: a module that names no
    ``CC_PER_PART`` slot has no business stating a kind on a part."""
    tree = _source(name)
    writes = [
        keyword
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "cc_kind" and _authors_a_kind(keyword)
    ]
    if writes:
        assert PER_PART.get(name), name
