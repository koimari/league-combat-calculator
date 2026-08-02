"""Patch-ingestion boundary tests for the vendored Wiki adapter."""

from unittest.mock import Mock

import requests

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
