"""Patch-ingestion boundary tests for the vendored Wiki adapter."""

import json
from unittest.mock import Mock

import requests

from scripts.reparse_runes import drifted_runes
from src.calculator import data_updater


def test_missing_auxiliary_ability_page_does_not_drop_champion(monkeypatch):
    """A stale ChampionData spell alias may 404 without hiding its champion."""
    response = Mock(status_code=404)
    error = requests.HTTPError(response=response)
    monkeypatch.setattr(
        "lolstaticdata.champions.pull_champions_wiki.download_soup",
        Mock(side_effect=error),
    )
    handler = data_updater.LolWikiDataHandler(use_cache=False)

    assert handler._pull_champion_ability("Milio", "Cozy Campfire 2") is None


def test_non_404_ability_source_failure_still_fails_closed(monkeypatch):
    """Only known-absent auxiliary pages are skippable during a refresh."""
    response = Mock(status_code=503)
    error = requests.HTTPError(response=response)
    monkeypatch.setattr(
        "lolstaticdata.champions.pull_champions_wiki.download_soup",
        Mock(side_effect=error),
    )
    handler = data_updater.LolWikiDataHandler(use_cache=False)

    try:
        handler._pull_champion_ability("Milio", "Ultra Mega Fire Kick")
    except requests.HTTPError as caught:
        assert caught is error
    else:  # pragma: no cover - assertion branch
        raise AssertionError("non-404 source failure must remain fatal")


def test_reparse_cached_rune_effects_recomputes_without_network(tmp_path):
    """Parser improvements reach data/runes.json from cached descriptions."""
    cached = {
        "First Strike": {
            "name": "First Strike",
            "path": "Inspiration",
            "slot": "Keystone",
            "cooldown": None,
            "icon": "http://x/fs.png",
            "description": (
                "grants {{g|10}} and ''First Strike'' for 3 seconds, causing "
                "damage to deal {{as|7% '''bonus''' true damage}}. Afterwards "
                "gold equal to {{rd|50%|35%}} of all bonus damage."
            ),
            "effects": {},
        }
    }
    (tmp_path / "runes.json").write_text(json.dumps(cached), encoding="utf-8")

    updated = data_updater.reparse_cached_rune_effects(tmp_path)

    effects = updated["First Strike"]["effects"]
    assert effects["bonus_true_damage_ratio"] == 0.07
    assert effects["flat_gold"] == 10.0
    assert effects["gold_conversion_ratios"] == [0.50, 0.35]
    assert effects["buff_duration_seconds"] == 3.0
    on_disk = json.loads((tmp_path / "runes.json").read_text(encoding="utf-8"))
    assert on_disk["First Strike"]["effects"] == effects
    assert on_disk["First Strike"]["icon"] == "http://x/fs.png"


def test_the_committed_rune_cache_is_what_the_parser_produces():
    """`scripts/reparse_runes.py --check` is green on the tracked cache."""
    assert drifted_runes() == []
