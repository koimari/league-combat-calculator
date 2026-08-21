"""Tests for the data fetcher module."""

import json
import os
from pathlib import Path

import pytest

from src.calculator.data_fetcher import (
    _read_cache,
    _validate_champion_data,
    _validate_item_data,
    fetch_champion_data,
    fetch_item_data,
)
from src.calculator.data_registry import write_runtime_cache

SAMPLE_CHAMPION_DATA = {
    "Aatrox": {
        "name": "Aatrox",
        "stats": {
            "health": {"flat": 650, "perLevel": 114},
            "attackDamage": {"flat": 60, "perLevel": 5},
        },
        "abilities": {},
    },
    "Ahri": {
        "name": "Ahri",
        "stats": {
            "health": {"flat": 590, "perLevel": 104},
            "attackDamage": {"flat": 53, "perLevel": 3},
        },
        "abilities": {},
    },
}

SAMPLE_ITEM_DATA = {
    "1001": {
        "name": "Boots",
        "stats": {"flatMovementSpeed": 25},
    },
    "1036": {
        "name": "Long Sword",
        "stats": {"flatAttackDamage": 10},
    },
}


class TestCacheReadWrite:
    """Tests for reading and writing cache files."""

    def test_read_reuses_parsed_json_until_file_changes(self, tmp_path: Path) -> None:
        """Repeated reads share one parse for the same path and mtime."""
        data_path = tmp_path / "test.json"
        data_path.write_text('{"version": 1}', encoding="utf-8")

        first = _read_cache(tmp_path, "test.json")
        second = _read_cache(tmp_path, "test.json")

        assert second is first

        old_mtime = data_path.stat().st_mtime_ns
        data_path.write_text('{"version": 2}', encoding="utf-8")
        os.utime(data_path, ns=(old_mtime + 1_000_000, old_mtime + 1_000_000))

        refreshed = _read_cache(tmp_path, "test.json")
        assert refreshed == {"version": 2}
        assert refreshed is not first

    def test_read_cache_key_includes_full_path(self, tmp_path: Path) -> None:
        """Same-named files in different data directories never collide."""
        first_dir = tmp_path / "first"
        second_dir = tmp_path / "second"
        first_dir.mkdir()
        second_dir.mkdir()
        (first_dir / "items.json").write_text('{"source": "first"}')
        (second_dir / "items.json").write_text('{"source": "second"}')

        assert _read_cache(first_dir, "items.json") == {"source": "first"}
        assert _read_cache(second_dir, "items.json") == {"source": "second"}


class TestValidateChampionData:
    """Tests for champion data validation."""

    def test_valid_data_passes(self) -> None:
        _validate_champion_data(SAMPLE_CHAMPION_DATA)

    def test_non_dict_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a dictionary"):
            _validate_champion_data([])  # type: ignore

    def test_empty_dict_raises(self) -> None:
        with pytest.raises(ValueError, match="is empty"):
            _validate_champion_data({})

    def test_missing_name_raises(self) -> None:
        data = {"Aatrox": {"stats": {}}}
        with pytest.raises(ValueError, match="missing required field: 'name'"):
            _validate_champion_data(data)

    def test_missing_stats_raises(self) -> None:
        data = {"Aatrox": {"name": "Aatrox"}}
        with pytest.raises(ValueError, match="missing required field: 'stats'"):
            _validate_champion_data(data)


class TestValidateItemData:
    """Tests for item data validation."""

    def test_valid_data_passes(self) -> None:
        _validate_item_data(SAMPLE_ITEM_DATA)

    def test_non_dict_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a dictionary"):
            _validate_item_data("not a dict")  # type: ignore

    def test_empty_dict_raises(self) -> None:
        with pytest.raises(ValueError, match="is empty"):
            _validate_item_data({})

    def test_missing_name_raises(self) -> None:
        data = {"1001": {"stats": {}}}
        with pytest.raises(ValueError, match="missing required field: 'name'"):
            _validate_item_data(data)


class TestFetchChampionData:
    """Tests for the champion data fetch function (cache-only)."""

    def test_returns_cached_data(self, tmp_path: Path) -> None:
        write_runtime_cache(tmp_path, "champions.json", SAMPLE_CHAMPION_DATA)
        result = fetch_champion_data(data_directory=tmp_path)
        assert result == SAMPLE_CHAMPION_DATA

    def test_raises_when_no_cache_exists(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="No champion data found"):
            fetch_champion_data(data_directory=tmp_path)


class TestFetchItemData:
    """Tests for the item data fetch function (cache-only)."""

    def test_returns_cached_data(self, tmp_path: Path) -> None:
        write_runtime_cache(tmp_path, "items.json", SAMPLE_ITEM_DATA)
        result = fetch_item_data(data_directory=tmp_path)
        assert result == SAMPLE_ITEM_DATA

    def test_raises_when_no_cache_exists(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="No item data found"):
            fetch_item_data(data_directory=tmp_path)
