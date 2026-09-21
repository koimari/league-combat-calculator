"""The internal row corpus the published census could not provide.

``tests/test_row_stream_census.py`` measures what the engine PUBLISHES,
because the coupled baseline is a committed corpus of published rows. The
modules that build that payload read the internal shape, so that census
licenses none of their reads: they run at publication rather than after it.

``scripts/internal_row_census.py`` captures the missing corpus by walking
one timed fight per registered champion, and this runs its ``check``, so
the committed receipt cannot drift from the engine.

What the corpus does NOT establish is as load-bearing as what it does. It
is one scenario shape per champion, so a key it calls universal is
universal across kits, not across every request a user can build. Reading
it as more than that is the mistake the published census already made once
by pooling two streams.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import internal_row_census as census  # noqa: E402


def _committed() -> dict:
    return json.loads(census.RECEIPT.read_text(encoding="utf-8"))


def test_the_receipt_is_committed_and_names_its_probe():
    """A corpus whose reach is not stated is a corpus nobody can bound."""
    receipt = _committed()
    assert receipt["champions"] > 150
    assert receipt["probe"]["enemy"]
    assert receipt["probe"]["fight_duration_seconds"] > 0


def test_the_receipt_matches_the_engine():
    """The gate: ``check``'s own comparison, run here rather than described."""
    assert _committed() == census.measure()


@pytest.mark.parametrize("stream", census.STREAMS)
def test_every_declared_stream_was_actually_seen(stream):
    """A stream that produced no row would publish an empty universal set,
    which reads as "nothing is safe" and is really "nothing was measured"."""
    block = _committed()["streams"][stream]
    assert block["rows"] > 0, stream
    assert block["universal"], stream


def test_the_damage_row_keys_the_serializer_reads_are_universal():
    """Why this corpus exists: ``public_response`` reads these four.

    Named individually rather than as a count, so a key leaving the
    universal set fails here pointing at the reader that depends on it.
    """
    universal = set(_committed()["streams"]["damage_events"]["universal"])
    for field in ("source_key", "damage_type", "damage", "phase"):
        assert field in universal, field


def test_a_moved_universal_set_is_reported_rather_than_absorbed():
    """The permanent negative: the gate can fail on demand."""
    measured = census.measure()
    measured["streams"]["damage_events"]["universal"].append("not_a_real_key")
    assert measured != _committed()


def test_the_corpus_does_not_claim_more_reach_than_it_has():
    """One scenario shape per champion, and the receipt says so.

    ``raw_damage`` is on 3,697 of 3,960 rows here: near-universal, and
    therefore exactly the kind of key a reader skimming a summary would
    convert. It is absent from the universal set, which is the corpus
    refusing to round up.
    """
    universal = set(_committed()["streams"]["damage_events"]["universal"])
    assert "raw_damage" not in universal
    assert "resistance_met" not in universal
