"""Roster-wide census of where a kit's crowd control is declared (D5).

``MODULE_CC`` is the one declaration site.  A slot whose control is one
answer keeps the constant there; a slot whose control varies within the
cast — by part, by option, or by branch — names itself ``CC_PER_PART``
there and the parts hold the answer.  Nothing else may author a kind.

The census is the test because the failure it guards is a *count*: the
declaration drifting back out of ``MODULE_CC`` one module at a time is
invisible per module and obvious per roster.
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
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats

#: The three kits whose review concluded no slot-level answer is true.
#: Kennen's Mark of the Storm stuns on the third stack any ability applied
#: and Annie is Energized at fight start, so neither a slot-wide kind nor a
#: slot-wide "none" is true of their damaging slots; Aatrox's Q knock-up is
#: the sweetspot branch and its W slows then pulls, both of which need the
#: rows re-timed against pinned receipts.  A fourth entry is a review that
#: gave up, so the set is pinned rather than counted.
DECLARE_NOTHING = {"Aatrox", "Annie", "Kennen"}

#: Slots whose control is not one constant, module -> slots.  Every entry
#: is a cast that lands two different answers (Zac's opening bounce
#: displaces and the rest slow), or one whose answer follows an option
#: (Aphelios' weapon, Sion's charge, Yasuo's two Q stacks).
PER_PART = {
    "Alistar": {"E"},
    "Aphelios": {"Q", "R"},
    "Aurelion Sol": {"R"},
    "Cassiopeia": {"R"},
    "Fiddlesticks": {"Q"},
    "Fizz": {"E"},
    "Hwei": {"Q", "E", "R"},
    "Irelia": {"R"},
    "Ivern": {"R"},
    # R left per_part while Cannon Transform was an untimed zero row; both
    # branches now ride the swing they empower, so the slot answers "none".
    "Jayce": {"Q"},
    "K'Sante": {"W"},
    "Karma": {"W"},
    "Kayn": {"W"},
    "Kled": {"Q"},
    "LeBlanc": {"E", "R"},
    "Mel": {"E"},
    "Morgana": {"R"},
    "Ornn": {"R"},
    "Qiyana": {"Q"},
    "Rammus": {"W"},
    "Rengar": {"E"},
    "Sejuani": {"W"},
    "Sion": {"Q"},
    "Swain": {"R"},
    "Tahm Kench": {"Q"},
    "Taliyah": {"Q", "E"},
    "Twisted Fate": {"W"},
    "Yasuo": {"Q"},
    "Yone": {"Q"},
    "Zaahen": {"Q"},
    "Zac": {"R"},
    "Zilean": {"Q"},
}

CHAMPIONS = sorted(_CHAMPION_MODULES)


def _source(name: str) -> ast.Module:
    module = get_champion_module_contract(name).module
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", CHAMPIONS)
def test_every_module_states_its_review_at_module_cc(name):
    """Presence is the point: absence by omission reads like absence by
    review, and only one of the two is an answer."""
    module = get_champion_module_contract(name).module
    assert hasattr(module, "MODULE_CC"), name
    assert isinstance(module.MODULE_CC, dict), name


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
def test_a_per_part_slot_really_authors_a_kind_somewhere(name):
    """The sentinel is a pointer; a pointer at nothing is a silenced slot.

    The parts must answer at the option defaults or with one boolean option
    flipped (Jayce's R is reviewed in hammer stance only) — a branch that
    reviewed its way to no answer (Rammus' aggregated thorns row) is a
    branch, not the whole slot.
    """
    contract = get_champion_module_contract(name)
    champion = get_champion(name)
    stats = calculate_total_stats(champion, 18, [])
    variants = [{}] + [
        {row["key"]: not row["default"]}
        for row in contract.options
        if isinstance(row.get("default"), bool)
    ]
    parsed = [
        parse_abilities(
            name,
            champion,
            18,
            stats["ability_power"],
            champion_stats=stats,
            champion_options=variant,
        )
        for variant in variants
    ]
    for slot in PER_PART[name]:
        result_key = "passive" if slot == "P" else slot
        kinds = {
            part.cc_kind
            for result in parsed
            for part in (result.get(result_key) or {}).get("parts") or ()
            if part.cc_kind is not None
        }
        assert kinds, (name, slot)


def test_the_roster_declares_all_but_the_reviewed_refusals():
    """The count D5 moves: every module but the pinned refusals declares."""
    silent = {
        name for name in CHAMPIONS if not get_champion_module_contract(name).cc_kinds
    }
    assert silent == DECLARE_NOTHING
    assert len(CHAMPIONS) - len(silent) == 170


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
