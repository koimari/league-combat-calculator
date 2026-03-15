"""Tests for the data fetcher module."""

import json
import time
from pathlib import Path

import pytest

from src.calculator.data_fetcher import (
    _is_cache_valid,
    _write_cache,
    _read_cache,
    _validate_champion_data,
    _validate_item_data,
    fetch_champion_data,
    fetch_item_data,
    CACHE_MAX_AGE_SECONDS,
)


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


class TestCacheValidity:
    """Tests for cache validity checking."""

    def test_cache_invalid_when_no_files_exist(self, tmp_path: Path) -> None:
        assert _is_cache_valid(tmp_path, "champions.json") is False

    def test_cache_invalid_when_only_data_exists(self, tmp_path: Path) -> None:
        (tmp_path / "champions.json").write_text("{}")
        assert _is_cache_valid(tmp_path, "champions.json") is False

    def test_cache_invalid_when_only_meta_exists(self, tmp_path: Path) -> None:
        meta = {"fetched_at": time.time()}
        (tmp_path / ".champions.json.meta").write_text(json.dumps(meta))
        assert _is_cache_valid(tmp_path, "champions.json") is False

    def test_cache_valid_when_fresh(self, tmp_path: Path) -> None:
        _write_cache(tmp_path, "champions.json", {"test": "data"})
        assert _is_cache_valid(tmp_path, "champions.json") is True

    def test_cache_invalid_when_stale(self, tmp_path: Path) -> None:
        _write_cache(tmp_path, "champions.json", {"test": "data"})
        # Overwrite meta with old timestamp
        meta = {"fetched_at": time.time() - CACHE_MAX_AGE_SECONDS - 1}
        (tmp_path / ".champions.json.meta").write_text(json.dumps(meta))
        assert _is_cache_valid(tmp_path, "champions.json") is False

    def test_cache_invalid_when_meta_corrupted(self, tmp_path: Path) -> None:
        (tmp_path / "champions.json").write_text("{}")
        (tmp_path / ".champions.json.meta").write_text("not json")
        assert _is_cache_valid(tmp_path, "champions.json") is False


class TestCacheReadWrite:
    """Tests for reading and writing cache files."""

    def test_write_and_read_roundtrip(self, tmp_path: Path) -> None:
        data = {"key": "value", "nested": {"a": 1}}
        _write_cache(tmp_path, "test.json", data)
        result = _read_cache(tmp_path, "test.json")
        assert result == data

    def test_write_creates_directory(self, tmp_path: Path) -> None:
        nested_dir = tmp_path / "a" / "b" / "c"
        _write_cache(nested_dir, "test.json", {"key": "value"})
        assert (nested_dir / "test.json").exists()

    def test_write_creates_metadata(self, tmp_path: Path) -> None:
        _write_cache(tmp_path, "test.json", {"key": "value"})
        meta_path = tmp_path / ".test.json.meta"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert "fetched_at" in meta
        assert meta["filename"] == "test.json"


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
        _write_cache(tmp_path, "champions.json", SAMPLE_CHAMPION_DATA)
        result = fetch_champion_data(data_directory=tmp_path)
        assert result == SAMPLE_CHAMPION_DATA

    def test_raises_when_no_cache_exists(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="No champion data found"):
            fetch_champion_data(data_directory=tmp_path)

    def test_returns_stale_cache(self, tmp_path: Path) -> None:
        """Stale cache is still returned — staleness is informational only."""
        _write_cache(tmp_path, "champions.json", SAMPLE_CHAMPION_DATA)
        meta = {"fetched_at": time.time() - CACHE_MAX_AGE_SECONDS - 1}
        (tmp_path / ".champions.json.meta").write_text(json.dumps(meta))
        result = fetch_champion_data(data_directory=tmp_path)
        assert result == SAMPLE_CHAMPION_DATA


class TestFetchItemData:
    """Tests for the item data fetch function (cache-only)."""

    def test_returns_cached_data(self, tmp_path: Path) -> None:
        _write_cache(tmp_path, "items.json", SAMPLE_ITEM_DATA)
        result = fetch_item_data(data_directory=tmp_path)
        assert result == SAMPLE_ITEM_DATA

    def test_raises_when_no_cache_exists(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="No item data found"):
            fetch_item_data(data_directory=tmp_path)

    def test_returns_stale_cache(self, tmp_path: Path) -> None:
        """Stale cache is still returned — staleness is informational only."""
        _write_cache(tmp_path, "items.json", SAMPLE_ITEM_DATA)
        meta = {"fetched_at": time.time() - CACHE_MAX_AGE_SECONDS - 1}
        (tmp_path / ".items.json.meta").write_text(json.dumps(meta))
        result = fetch_item_data(data_directory=tmp_path)
        assert result == SAMPLE_ITEM_DATA
