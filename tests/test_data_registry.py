"""Front-door tests for data write ownership and atomic cache writes."""

import json

import pytest

from src.calculator.data_registry import data_version, write_runtime_cache


def test_runtime_cache_write_has_metadata_and_rejects_foreign_files(tmp_path) -> None:
    write_runtime_cache(
        tmp_path,
        "champions.json",
        {"champion": "Ahri"},
        source_url="https://example.test/cache",
    )

    assert json.loads((tmp_path / "champions.json").read_text()) == {"champion": "Ahri"}
    metadata = json.loads((tmp_path / ".champions.json.meta").read_text())
    assert metadata["source_url"] == "https://example.test/cache"
    with pytest.raises(ValueError, match="not a runtime-cache file"):
        write_runtime_cache(tmp_path, "worklist.json", {})


def test_data_version_advances_once_per_accepted_cache_write(tmp_path) -> None:
    """One bump per write, none for a refusal, and never backwards.

    The counter is process-global, so every assertion here is relative to
    the version this test started at; an absolute value would only pin the
    order the suite happened to run in.
    """
    start = data_version()

    write_runtime_cache(tmp_path, "items.json", {"items": []})
    assert data_version() == start + 1

    # An identical payload is still a new cache generation: the writer, not
    # the content, is what a memo can observe.
    write_runtime_cache(tmp_path, "items.json", {"items": []})
    assert data_version() == start + 2

    with pytest.raises(ValueError, match="not a runtime-cache file"):
        write_runtime_cache(tmp_path, "worklist.json", {})
    assert data_version() == start + 2
