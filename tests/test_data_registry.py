"""Front-door tests for data write ownership and atomic cache writes."""

import json

import pytest

from src.calculator.data_registry import write_runtime_cache


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
