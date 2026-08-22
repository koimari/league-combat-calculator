"""Every module's coverage map, checked against what its parse actually did.

``MODULE_COVERAGE`` is the one place a module says what its five slots
mean, and until this sweep nothing read the whole tree's worth of those
claims against a real parse.  Two claims are checked, both in the
vocabulary's own terms:

* **modeled means there is a row.**  A slot the map calls ``modeled``,
  and that names no ``COVERAGE_CHANNELS`` channel, must emit an entry at
  some vantage a real request reaches — one rotation, the timed fight
  window, or a declared option the player can set.  Kalista W, Jayce E,
  Braum P and Ekko P each read ``modeled`` while emitting nothing at
  default options before this existed.
* **no_damage and out_of_scope mean no damage.**  Neither may put damage
  on the enemy at either vantage.  Narrower than ``coverage_truth``'s
  coarse ``priced``, deliberately: a self stat buff is a real outcome and
  is not damage, so Teemo's Move Quick and Kai'Sa's Supercharge stay
  ``no_damage`` while reading ``priced``.

The option table is a declaration, not an exemption: the sweep asserts the
named option really does produce the row, so an option that stops working
fails here rather than quietly turning the claim back into a lie.
"""

import pytest

from src.calculator.champions import (
    get_champion_module_contract,
    registered_champion_names,
)
from tests import coverage_truth

#: A ``modeled`` slot whose row only exists once the player sets the option
#: named here.  The default is off because the mechanic is player state —
#: stacks carried in, a form toggled, a mark consumed — and inventing a
#: default would price a fight nobody asked for.
OPTION_GATED: dict[tuple[str, str], tuple[str, object]] = {
    ("Alistar", "P"): ("p_triumph_stacks", 6),
    ("Cho'Gath", "P"): ("p_carnivore_kills", 10),
    ("Ekko", "P"): ("p_procs", 3),
    ("Elise", "P"): ("spider_form", True),
    ("Fiora", "P"): ("p_vitals", 4),
    ("Gnar", "P"): ("mega", True),
    ("Gnar", "R"): ("mega", True),
    ("Jayce", "E"): ("hammer_stance", True),
    ("Jinx", "P"): ("jinx_get_excited_stacks", 5),
    ("Kalista", "W"): ("soul_mark_proc", True),
}

CHAMPIONS = sorted(registered_champion_names())


def _answers(champion):
    return {
        "per_cast": coverage_truth.emitted(champion),
        "timed": coverage_truth.emitted(champion, vantage=coverage_truth.TIMED),
    }


@pytest.mark.parametrize("champion", CHAMPIONS)
def test_a_modeled_slot_emits_a_row_somewhere(champion):
    """``modeled`` is a claim that a row exists; this is where it is read."""
    contract = get_champion_module_contract(champion)
    answers = _answers(champion)
    for slot, status in contract.coverage.items():
        if status != "modeled" or contract.coverage_channels.get(slot):
            continue
        if any(vantage[slot] != coverage_truth.ABSENT for vantage in answers.values()):
            continue
        gate = OPTION_GATED.get((champion, slot))
        assert gate is not None, (
            f"{champion} {slot} reads 'modeled' but emits no row at either "
            "vantage and names no COVERAGE_CHANNELS channel; declare the "
            "option that produces it, or say what the slot really is"
        )
        option, value = gate
        gated = coverage_truth.emitted(champion, **{option: value})
        assert gated[slot] != coverage_truth.ABSENT, (
            f"{champion} {slot} is declared option-gated on {option!r}, but "
            f"setting it to {value!r} still emits no row"
        )


@pytest.mark.parametrize("champion", CHAMPIONS)
def test_an_undamaging_slot_never_damages(champion):
    """``no_damage`` and ``out_of_scope`` are claims about enemy damage."""
    contract = get_champion_module_contract(champion)
    for label, vantage in (
        ("per_cast", coverage_truth.PER_CAST),
        ("timed", coverage_truth.TIMED),
    ):
        parsed = coverage_truth.parse(champion, vantage=vantage)
        for slot, status in contract.coverage.items():
            if status == "modeled":
                continue
            entry = coverage_truth.slot_entry(parsed, slot)
            assert not coverage_truth.prices_enemy_damage(entry), (
                f"{champion} {slot} reads {status!r} but prices enemy damage "
                f"at the {label} vantage"
            )


def test_every_option_gated_row_names_a_slot_that_needs_the_table():
    """A stale exemption is its own failure: the table holds no spare rows."""
    for (champion, slot), (option, _value) in OPTION_GATED.items():
        contract = get_champion_module_contract(champion)
        assert contract.coverage[slot] == "modeled", (champion, slot)
        assert option in {
            row.get("key") for row in contract.options
        }, f"{champion} declares no option {option!r}"
        answers = _answers(champion)
        assert all(
            vantage[slot] == coverage_truth.ABSENT for vantage in answers.values()
        ), f"{champion} {slot} emits without its option; drop the table row"
