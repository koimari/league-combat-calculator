"""The scoreboard reader against its labeled corpus, and the sprite it reads with.

tests/fixtures/scoreboard/labels.json names, per frame, the rows the reader
must produce: top to bottom, players left to right, each a champion and its
item ids in strip order (None for an empty slot, "?" for an icon the labeler
could not name, which the reader may fill or leave). Champions are exact;
items are held to a corpus-wide floor, ratcheted to what the tree reads, so
a threshold change that costs a slot goes red. scripts/scoreboard_corpus.py
grows the corpus.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.build_icon_sprite import check as sprite_check
from scripts.scoreboard_corpus import CORPUS, LABELS, read_frames

ROOT = Path(__file__).resolve().parents[1]
ITEM_FLOOR = 0.99
EXTRA_CEILING = 0.0


def test_sprite_matches_the_caches() -> None:
    """The committed sprite covers every cached champion and item."""
    champions = json.loads(
        (ROOT / "data" / "champions.json").read_text(encoding="utf-8")
    )
    items = json.loads((ROOT / "data" / "items.json").read_text(encoding="utf-8"))
    reason = sprite_check(
        ROOT / "static" / "icon-sprite.json",
        ROOT / "static" / "icon-sprite.webp",
        champions,
        items,
    )
    assert reason is None, reason


@pytest.fixture(scope="module")
def readings() -> dict:
    """Labels and the reader's output for every corpus frame, read once."""
    if shutil.which("node") is None:  # pragma: no cover - toolchain dependent
        pytest.skip("node is not installed")
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    return {"labels": labels, "read": read_frames([CORPUS / name for name in labels])}


def _players(rows: list) -> list[dict]:
    return [player for row in rows for player in row]


def test_every_labeled_champion_is_read(readings: dict) -> None:
    """Every row reads the labeled champions, in order."""
    misses = []
    for name, label in readings["labels"].items():
        want = [[p["champion"] for p in row] for row in label["rows"]]
        got = [
            [p["champion"]["key"] for p in row]
            for row in readings["read"][name]["rows"]
        ]
        if want != got:
            misses.append(f"{name}: wanted {want}, read {got}")
    assert not misses, "\n".join(misses)


def test_items_clear_the_corpus_floor(readings: dict) -> None:
    """Items are read at ITEM_FLOOR or better with phantoms under EXTRA_CEILING."""
    correct = labeled = extra = 0
    report = []
    for name, label in readings["labels"].items():
        want = _players(label["rows"])
        got = _players(readings["read"][name]["rows"])
        frame_correct = frame_labeled = frame_extra = 0
        for wanted, read in zip(want, got, strict=True):
            want_ids = [i for i in wanted["items"] if i and i != "?"]
            unscored = wanted["items"].count("?")
            read_ids = [hit["key"] for hit in read["items"] if hit]
            matched = sum(
                min(want_ids.count(i), read_ids.count(i)) for i in set(want_ids)
            )
            frame_correct += matched
            frame_labeled += len(want_ids)
            frame_extra += max(0, len(read_ids) - matched - unscored)
        correct += frame_correct
        labeled += frame_labeled
        extra += frame_extra
        report.append(
            f"{name}: {frame_correct}/{frame_labeled} items, {frame_extra} extra, {readings['read'][name]['ms']} ms"
        )
    summary = "\n".join(report)
    assert labeled, "the corpus has no labeled items"
    assert correct / labeled >= ITEM_FLOOR, f"{correct}/{labeled} items read\n{summary}"
    assert (
        extra / labeled <= EXTRA_CEILING
    ), f"{extra} items read that were not there\n{summary}"
