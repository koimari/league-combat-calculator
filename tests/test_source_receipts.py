"""Typed validation for the champion source-receipt loader."""

import json

import pytest

from src.calculator.champions import source_receipts

VALID_ROW = {
    "label": "Fixture parent entry",
    "url": "https://wiki.leagueoflegends.com/en-us/Fixture",
    "revision_id": 123,
    "revision_timestamp": "2026-08-01T00:00:00Z",
}


@pytest.fixture(name="receipt_root")
def fixture_receipt_root(tmp_path, monkeypatch):
    """Point the loader at a temporary static root, isolating its cache."""
    monkeypatch.setattr(source_receipts, "_STATIC_ROOT", tmp_path)
    monkeypatch.setattr(
        source_receipts, "_PACKET_MANIFEST", tmp_path / "reviewed-packets.json"
    )
    source_receipts._source_index.cache_clear()
    yield tmp_path
    source_receipts._source_index.cache_clear()


def _write(root, name, payload):
    (root / name).write_text(json.dumps(payload), encoding="utf-8")


def test_typed_receipt_rows_load(receipt_root):
    _write(receipt_root, "cp10_batch_99_sources.json", {"Fixture": [VALID_ROW]})
    _write(receipt_root, "reviewed-packets.json", {"champions": {}})

    assert source_receipts.load_champion_sources("Fixture") == [VALID_ROW]


@pytest.mark.parametrize(
    "broken",
    [
        {**VALID_ROW, "revision_id": "123"},
        {**VALID_ROW, "revision_id": 0},
        {**VALID_ROW, "revision_id": True},
        {**VALID_ROW, "revision_timestamp": ""},
        {key: value for key, value in VALID_ROW.items() if key != "url"},
    ],
)
def test_malformed_receipt_rows_fail_closed(receipt_root, broken):
    """A regenerated asset with untyped rows must raise, not reach /api/config."""
    _write(receipt_root, "cp10_batch_99_sources.json", {"Fixture": [broken]})
    _write(receipt_root, "reviewed-packets.json", {"champions": {}})

    with pytest.raises(RuntimeError, match="incomplete"):
        source_receipts.load_champion_sources("Fixture")


def test_malformed_manifest_fallback_rows_are_skipped(receipt_root):
    """Manifest fallback rows are optional evidence: invalid rows never load."""
    _write(
        receipt_root,
        "reviewed-packets.json",
        {"champions": {"Fixture": {"sources": [{**VALID_ROW, "revision_id": "123"}]}}},
    )

    with pytest.raises(RuntimeError, match="No source receipts"):
        source_receipts.load_champion_sources("Fixture")
