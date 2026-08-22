"""Reads into the CommunityDragon character binaries under ``data/bin``.

``data/bin/characters/`` is a gitignored local game-file cache, so the
tests that quote it skip where it is absent; what they all need from a
spell record is one named ``DataValues`` row, which lives here once.

This is a test helper, not a test module: it holds no assertions.
"""


def data_value(record: dict, name: str) -> list[float]:
    """One named ``DataValues`` row out of a binary spell record."""
    for entry in record.get("DataValues", []):
        if entry.get("name") == name:
            return list(entry.get("values") or [])
    raise AssertionError(f"binary record has no DataValues row {name!r}")
