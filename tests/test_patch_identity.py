from __future__ import annotations

import pytest

from src.calculator.data_registry import write_runtime_cache
from src.calculator.patch_identity import PatchIdentityError, canonical_patch


def test_patch_namespaces_are_explicit() -> None:
    assert canonical_patch("26.15").public_patch == "26.15"
    assert canonical_patch("16.15").public_patch == "26.15"
    assert canonical_patch("16.16.1").public_patch == "26.16"
    assert canonical_patch("26.01").client_patch == "16.1"
    assert canonical_patch("26.16").client_patch == "16.16"


def test_unknown_patch_is_rejected() -> None:
    with pytest.raises(PatchIdentityError):
        canonical_patch("14.24")


def test_runtime_metadata_records_public_and_client_labels(tmp_path) -> None:
    write_runtime_cache(
        tmp_path,
        "champions.json",
        {"champion": "Ahri"},
        source_version="16.16.1",
    )
    metadata = (tmp_path / ".champions.json.meta").read_text(encoding="utf-8")
    assert '"public_patch": "26.16"' in metadata
    assert '"client_patch": "16.16"' in metadata
