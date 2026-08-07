"""Contracts for the complete runnable champion registration surface."""

import json

from src.calculator.champions import (
    _CUSTOM_CHAMPION_MODULES,
    engine_registration_kind,
    parse_champion_abilities,
    registered_champion_names,
)


def _champions() -> dict:
    with open("data/champions.json", encoding="utf-8") as handle:
        return json.load(handle)


def test_every_cached_champion_has_an_importable_engine_registration():
    champions = _champions()
    names = {champion["name"] for champion in champions.values()}
    registered = set(registered_champion_names())

    assert names == registered
    assert len(registered) == len(_CUSTOM_CHAMPION_MODULES)
    assert len(registered_champion_names()) == len(_CUSTOM_CHAMPION_MODULES)
    assert all(
        engine_registration_kind(name) == "reviewed_module"
        for name in _CUSTOM_CHAMPION_MODULES
    )


def test_custom_manifest_is_the_single_authoritative_roster():
    """_CUSTOM_CHAMPION_MODULES is the one explicit roster manifest: it must
    exactly equal the cached champion names (issue #136 — a new champion
    needs no count edits anywhere, only a manifest entry + reviewed module)."""
    champions = _champions()
    cache_names = {champion["name"] for champion in champions.values()}
    assert set(_CUSTOM_CHAMPION_MODULES) == cache_names
