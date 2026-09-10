"""Adding an on-hit item, through the path a real one takes.

Four registries carry a new item: the cached record its branch text lives in,
the parser line that reads that text, the registry entry that owns its
numbers, and the capability that names the step which prices it.  Each test
installs a fresh cached record, so nothing leaks into a sibling and the
identity memo in `_resolve_damage_effects_uncached` cannot serve a stale
compile.  The positive is pinned against Nashor's Tooth, whose numbers this
item copies: same fight, to the last bit.
"""

import copy
import dataclasses
import sys
from functools import cache
from types import MappingProxyType

import pytest

from src.calculator import item_effects, passive_parser, trigger_stream
from src.calculator.calculate import calculate_payload
from src.calculator.data_fetcher import (
    DEFAULT_DATA_DIR,
    _cache_version,
    _item_name_index,
    fetch_item_data,
)
from src.calculator.item_behavior_catalog import BehaviorCatalogError, behavior_rules
from src.calculator.pipeline import run_fight
from src.calculator.scenario import parse_scenario_request, resolve_scenario

#: The synthetic item: a name no cache holds, and the numbers of the item it
#: is pinned against.
NAME = "Synthetic Fang"
SLUG = "synthetic_fang"
BRANCH = "Synthetic Bite"
TWIN = "Nashor's Tooth"
TWIN_PAIR_MECHANIC = "nashors_tooth.on_hit_preview"
TWIN_WALK_MECHANIC = "nashors_tooth.on_hit"

#: The shape half of the registry entry: what kind of effect it is and which
#: term schema its numbers are read through.  The numbers themselves come out
#: of the parser, off the cached branch text.
SHAPE = {"type": "on_hit", "formula": "flat_ap", "damage_type": "magic"}

#: One attacking fight, long enough for ten swings to carry the on-hit.
REQUEST = {
    "champion": "Kog'Maw",
    "level": 18,
    "fight_mode": "timed",
    "fight_duration_seconds": 8.0,
    "include_auto_attacks": True,
    "auto_attack_uptime": 1.0,
}


def _fight_total(items: list[str]) -> float:
    """One build's total damage, at the precision the engine computed it."""
    request = parse_scenario_request({**REQUEST, "items": items}, deterministic=True)
    resolved = resolve_scenario(request)
    return run_fight(
        resolved.champion_data,
        request.level,
        list(resolved.items),
        resolved.fight_params,
    )["total_damage"]


def _give_every_capability_projection_a_fresh_cache(monkeypatch):
    """Re-bind each ``@cache`` projection over ``CAPABILITIES`` to a fresh one.

    The projections are derived from the module rather than listed, and each
    is replaced wherever it is bound, so a projection added later cannot be
    forgotten and nothing this fixture computes lands in a cache a sibling
    test on the same worker reads back.
    """
    for name, cached in list(vars(trigger_stream).items()):
        if not hasattr(cached, "cache_clear") or cached.__module__ != (
            trigger_stream.__name__
        ):
            continue
        fresh = cache(cached.__wrapped__)
        for module in list(sys.modules.values()):
            if getattr(module, name, None) is cached:
                monkeypatch.setattr(module, name, fresh)


@pytest.fixture(name="install")
def _install(monkeypatch):
    """Register the synthetic item, with any one of its four halves omitted."""

    def register(*, parse=True, reference=True, capability=True, formula="flat_ap"):
        index = _item_name_index(*_cache_version(DEFAULT_DATA_DIR, "items.json"))
        record = copy.deepcopy(index[TWIN.lower()])
        record["name"] = NAME
        record["id"] = 990001
        record["passives"] = [record["passives"][0]]
        record["passives"][0]["name"] = BRANCH
        monkeypatch.setitem(index, NAME.lower(), record)
        monkeypatch.setitem(fetch_item_data(), "990001", record)
        if parse:
            monkeypatch.setitem(
                passive_parser._ITEM_PARSE_CONFIG,
                NAME,
                [("passive", BRANCH, passive_parser._parse_simple_on_hit, {})],
            )
        if reference:
            shape = {**SHAPE, "formula": formula}
            monkeypatch.setitem(
                item_effects._REFERENCE_ITEM_EFFECTS,
                NAME,
                {**shape, "base": 15.0, "ap_ratio": 0.15},
            )
            parsed = (
                passive_parser.parse_item_effect(NAME, fetch_item_data())
                if parse
                else {}
            )
            monkeypatch.setitem(item_effects.ITEM_EFFECTS, NAME, {**shape, **parsed})
        if capability:
            declared = trigger_stream.CAPABILITIES
            owner = trigger_stream.ItemOwner(name=NAME)
            monkeypatch.setattr(
                trigger_stream,
                "CAPABILITIES",
                MappingProxyType(
                    {
                        **declared,
                        f"{SLUG}.on_hit_preview": dataclasses.replace(
                            declared[TWIN_PAIR_MECHANIC],
                            mechanic=f"{SLUG}.on_hit_preview",
                            owner=owner,
                        ),
                        f"{SLUG}.on_hit": dataclasses.replace(
                            declared[TWIN_WALK_MECHANIC],
                            mechanic=f"{SLUG}.on_hit",
                            owner=owner,
                            pair_of=f"{SLUG}.on_hit_preview",
                        ),
                    }
                ),
            )
            _give_every_capability_projection_a_fresh_cache(monkeypatch)
        return record

    return register


class TestTheItemThatDeclaresEverything:
    """Four registries, and the item is priced like any other."""

    def test_the_parser_reads_its_numbers_off_the_cached_branch(self, install):
        install()
        assert passive_parser.parse_item_effect(NAME, fetch_item_data()) == {
            "damage_type": "magic",
            "base": 15.0,
            "ap_ratio": 0.15,
        }

    def test_it_compiles_to_one_declared_on_hit_mechanic(self, install):
        install()
        assert [rule.mechanic_id for rule in behavior_rules(NAME)] == [f"{SLUG}.on_hit"]

    def test_it_authors_its_own_breakdown_row(self, install):
        install()
        payload = calculate_payload({**REQUEST, "items": [NAME]}, deterministic=True)
        row = payload["breakdown"][f"on_hit_{NAME}"]
        assert row["name"] == f"{NAME} (on-hit)"
        assert row["total_damage"] > 0

    def test_its_fight_is_the_twins_fight_to_the_last_bit(self, install):
        """Same numbers, same schedule: the totals agree at ``repr(float)``."""
        install()
        assert repr(_fight_total([NAME])) == repr(_fight_total([TWIN]))

    def test_the_step_that_prices_it_is_the_step_it_declares(self, install):
        """D3's loop, closed for an item nobody hand-listed anywhere."""
        install()
        trace = calculate_payload(
            {**REQUEST, "items": [NAME]}, deterministic=True, trace=True
        )["trace"]
        measured = {
            line["step"]
            for line in trace["lines"]
            if line["source"] == f"on_hit_{NAME}"
        }
        assert measured == {trigger_stream.CAPABILITIES[f"{SLUG}.on_hit_preview"].impl}


class TestTheFourWaysItFailsClosed:
    """Each omission stops the calculation and names what is missing."""

    def test_a_cached_passive_no_registry_entry_declares_is_withheld(self, install):
        install(reference=False)
        with pytest.raises(ValueError, match="declared by no BehaviorRule"):
            calculate_payload({**REQUEST, "items": [NAME]}, deterministic=True)

    def test_a_formula_no_term_schema_describes_is_refused(self, install):
        install(formula="flat_ap_typo")
        with pytest.raises(BehaviorCatalogError, match="no term schema describes"):
            calculate_payload({**REQUEST, "items": [NAME]}, deterministic=True)

    def test_an_unparsed_entry_names_the_key_it_is_missing(self, install):
        install(parse=False)
        with pytest.raises(KeyError, match="is missing 'base'"):
            calculate_payload({**REQUEST, "items": [NAME]}, deterministic=True)

    def test_a_mechanic_no_capability_declares_has_no_pricing_home(self, install):
        """A rule with no capability names no pricing home, so it is refused."""
        install(capability=False)
        with pytest.raises(BehaviorCatalogError, match="declares no capability"):
            calculate_payload({**REQUEST, "items": [NAME]}, deterministic=True)
