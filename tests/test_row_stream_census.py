"""Which keys every row of each published stream carries, measured.

ER5's remaining tail is mostly ``row.get(key, <literal>)`` on published
rows, and whether converting one is a fix or a new crash depends entirely
on whether that stream stamps the key on every row. This is that table, and
it is re-derived from the committed coupled baseline on every run rather
than written down once.

The trap it exists to stop is POOLING. A first pass at the damage row
measured ``combat/events`` and ``fights/damage_events`` together, concluded
that only four keys were universal, and recorded that ``raw_damage`` sat on
1,706 of 2,458 rows. Both streams are internally consistent: ``raw_damage``
is on every ``combat/events`` row and on no fight row. Pooling two shapes
manufactures an optional field out of two required ones, and the conclusion
it invites, that some producer stamps inconsistently, is false.

Converting a tail site needs THREE answers, not one, and each was learned
from a conversion that had to be undone:

1. Is the key universal on the stream? That is what this table answers, and
   answering it by pooling two streams is how the first attempt produced a
   figure that was true and misleading at once.

2. Does the variable definitely hold a row of that stream? A census-proven
   field is still unsafe where the variable can be a sentinel:
   ``build_evaluation``'s ``main_survival`` is the ``{}`` its own ``next``
   falls back to, and indexing it raised on a real optimizer path.

3. Is the CONTAINER guaranteed? ``combat/events`` is published by 23 of the
   26 censused scenarios, so the stream's own default is real even though
   every field on every row it does publish is not.

4. Does the site run AFTER publication? This table is measured on published
   rows. ``participant_timeline``'s overheal pass is the producer of
   ``overheal`` and runs over heal events before they are published, which
   is why it opens by skipping any row that already has one. A row in
   flight is not yet the shape the census describes, so nothing here
   licenses indexing it.

5. Is TOLERATING a malformed row part of the reader's contract? This is the
   clause that has disqualified the most sites, and a census can never
   answer it. ``bis_objective`` is handed partial payloads and ``bis.py``
   wraps the candidate loop in ``except (KeyError, ValueError)``, which
   withholds that build from ranking, so indexing converts a scored
   candidate into a silently dropped one. ``public_response`` is worse:
   withholding a malformed event IS its job, pinned by tests that hand it
   partial rows on purpose, so indexing turns graceful withholding into a
   crash at the API boundary. In both, the default is the contract.

   The internal corpus (``docs/receipts/internal-row-census.json``) proves
   all four fields the serializer reads are on every one of the 3,960 rows
   the engine builds. It licenses the read and the contract forbids it. A
   corpus answers what the data IS, never what a reader promised.

And one boundary, which is where this method stops rather than a clause a
site can pass. The census is trustworthy because
``golden_coupled_baseline.json`` is a COMMITTED corpus of published rows
that a test re-derives on every run. Internal rows have no such corpus: the
pair baseline holds aggregate totals, not event rows. Probing a handful of
fights measures nine universal keys on the internal ``damage_events`` shape
and would license ``public_response``'s serializer reads, but a sample of
eight champions in one scenario shape is not a corpus, and converting on it
would be the pooling mistake again in a new costume. Censusing the internal
shapes means capturing and gating a corpus for them first, which is its own
slice.

A site clears all five or it keeps its default, and the default is then
correct rather than debt. Mechanising clauses 1 and 2 over the largest tail
module found five loops iterating a censused stream and exactly one site
inside them, and clause 4 disqualified that one. Clause 5 then disqualified
the next five, which git history had cleared and the census licensed. The
mechanically provable set is very small; a default in this tree is more
often a contract than a mistake.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE = Path("scripts/golden_coupled_baseline.json")

#: ``stream -> (row count, the keys on EVERY row of it)``. Regenerate with
#: ``test_the_census_is_current`` when a producer starts or stops stamping
#: a field; that test prints the table it expected.
CENSUS: dict[str, tuple[int, tuple[str, ...]]] = {
    "combat/events": (
        1706,
        (
            "attacker",
            "damage",
            "damage_type",
            "event_id",
            "event_precision",
            "overkill",
            "pair_damage",
            "raw_damage",
            "sequence",
            "source",
            "target",
            "time",
        ),
    ),
    "combat/healing_events": (
        909,
        (
            "amount",
            "applied_amount",
            "attacker",
            "event_id",
            "healing_reduction_factor",
            "overheal",
            "raw_amount",
            "reduced_amount",
            "source",
            "temporary_health",
            "time",
        ),
    ),
    "combat/breakdown": (
        77,
        (
            "champion",
            "death_time",
            "effective_health",
            "healing_output",
            "healing_received",
            "healing_reduced",
            "health_damage",
            "incoming_damage",
            "outgoing_damage_before_death",
            "participant_id",
            "shield_absorbed",
            "sources",
            "support_shield_received",
            "support_value",
            "survived_window",
            "team",
            "total_damage",
        ),
    ),
    "combat/item_denial_receipts": (
        5,
        (
            "attacker",
            "event_id",
            "kind",
            "reason",
            "source",
            "target",
            "time",
        ),
    ),
    "combat/participants": (
        77,
        (
            "champion",
            "level",
            "participant_id",
            "survival",
            "team",
        ),
    ),
    "combat/support_events": (
        70,
        (
            "amount",
            "applied_amount",
            "attacker",
            "duration",
            "event_id",
            "kind",
            "raw_amount",
            "recipient",
            "reduced_amount",
            "source",
            "target",
            "target_policy",
            "target_scope",
            "target_selection_key",
            "time",
        ),
    ),
    "fights/cast_timeline": (
        207,
        (
            "cast_id",
            "name",
            "ordinal",
            "resource_after",
            "resource_before",
            "resource_cost",
            "resource_restored",
            "slot",
            "target_id",
            "time",
        ),
    ),
    "fights/damage_events": (752, ("damage", "damage_type", "phase", "source", "time")),
    "fights/self_healing_events": (252, ("amount", "kind", "source", "time")),
}


def _streams() -> dict[str, list[dict]]:
    """Every published row stream the committed baseline holds."""
    snapshot = json.loads(BASELINE.read_text(encoding="utf-8"))
    streams: dict[str, list[dict]] = {}
    for scenario in snapshot["coupled_scenarios"].values():
        for key, value in (scenario.get("combat") or {}).items():
            if _is_row_list(value):
                streams.setdefault(f"combat/{key}", []).extend(value)
        for fight in (scenario.get("fights") or {}).values():
            for key, value in fight.items():
                if _is_row_list(value):
                    streams.setdefault(f"fights/{key}", []).extend(value)
    return streams


def _is_row_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(row, dict) for row in value)
    )


def _universal(rows: list[dict]) -> tuple[str, ...]:
    counts = Counter(key for row in rows for key in row)
    return tuple(sorted(key for key, count in counts.items() if count == len(rows)))


@pytest.mark.parametrize("stream", sorted(CENSUS))
def test_the_census_is_current(stream):
    """A producer that starts or stops stamping a field turns this red.

    Red here is not automatically a defect: a new optional field is normal.
    It is a prompt to re-read the row's module before any fail-closed reader
    is widened or narrowed on the strength of the old table.
    """
    rows = _streams().get(stream, [])
    expected_count, expected_keys = CENSUS[stream]
    assert len(rows) == expected_count, stream
    assert (
        _universal(rows) == expected_keys
    ), f"{stream}'s universal key set moved; measured {_universal(rows)}"


def test_every_published_row_stream_is_in_the_census():
    """A stream nobody measured is a stream nobody can safely convert."""
    assert set(_streams()) - set(CENSUS) == set()


def test_pooling_two_streams_manufactures_an_optional_field():
    """The permanent negative: the mistake this table exists to prevent.

    Asserted rather than described, so the reasoning cannot quietly rot back
    into the pooled reading that produced the wrong figure the first time.
    """
    streams = _streams()
    combat = streams["combat/events"]
    fights = streams["fights/damage_events"]
    assert "raw_damage" in _universal(combat)
    assert "raw_damage" not in _universal(fights)
    assert all("raw_damage" not in row for row in fights)
    # Pooled, a key that is required in one shape and absent from the other
    # reads as merely optional, which is the false conclusion.
    assert "raw_damage" not in _universal(combat + fights)


def _survival_dicts() -> list[dict]:
    """The ``survival`` sub-dict of every participants row.

    Nested rather than a top-level list, so ``_streams`` does not reach it,
    and censused separately because four call sites read its fields with
    literal defaults. Every participants row carries one and it is always a
    Mapping, which is what licenses indexing it at all.
    """
    snapshot = json.loads(BASELINE.read_text(encoding="utf-8"))
    return [
        row["survival"]
        for scenario in snapshot["coupled_scenarios"].values()
        for row in (scenario.get("combat") or {}).get("participants") or ()
        if isinstance(row.get("survival"), dict)
    ]


#: The survival sub-dict's own universal keys, the four this campaign reads.
#: Its full set is 67 wide; only the fields a caller indexes are pinned, so
#: an unrelated field appearing or leaving does not turn this red.
SURVIVAL_READ_FIELDS = (
    "death_time",
    "effective_health",
    "healing_received",
    "shield_absorbed",
    "support_shield_received",
)


def test_every_participants_row_carries_a_survival_mapping():
    """Clause 2 for the nested dict: the variable is always a row's own."""
    snapshot = json.loads(BASELINE.read_text(encoding="utf-8"))
    rows = [
        row
        for scenario in snapshot["coupled_scenarios"].values()
        for row in (scenario.get("combat") or {}).get("participants") or ()
    ]
    assert rows
    assert all(isinstance(row.get("survival"), dict) for row in rows)


@pytest.mark.parametrize("field", SURVIVAL_READ_FIELDS)
def test_the_survival_fields_this_campaign_indexes_are_universal(field):
    rows = _survival_dicts()
    assert rows
    absent = [row for row in rows if field not in row]
    assert absent == [], f"{field} missing from {len(absent)} of {len(rows)}"


def _receipt_view_input_rows() -> list[dict]:
    """The rows ``program/views/receipt`` is HANDED, not the ones it writes.

    The view builds ``combat/events``, so the published census measures its
    output and licenses none of its reads. Its input is captured here by
    driving the same coupled rebuild the baseline is captured from, which
    is the only corpus that speaks for it.
    """
    import sys as _sys

    _sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import golden_snapshot as gs

    import src.calculator.program.views.receipt as receipt_view

    seen: list[dict] = []
    original = receipt_view._damage_event_rows

    def spy(events, writer, prefix):
        seen.extend(row for row in events if isinstance(row, dict))
        return original(events, writer, prefix)

    receipt_view._damage_event_rows = spy
    try:
        gs.rebuild_for(json.loads(BASELINE.read_text(encoding="utf-8")))
    finally:
        receipt_view._damage_event_rows = original
    return seen


@pytest.mark.parametrize("field", ["source_key", "damage_type", "damage", "time"])
def test_the_receipt_view_is_handed_these_on_every_row(field):
    """What licenses the indexed reads in ``_damage_event_rows``."""
    rows = _receipt_view_input_rows()
    assert len(rows) > 1500
    absent = [row for row in rows if field not in row]
    assert absent == [], f"{field} missing from {len(absent)} of {len(rows)}"


@pytest.mark.parametrize(
    ("field", "ceiling"),
    [("overkill", 1.0), ("raw_damage", 0.9), ("event_precision", 0.5)],
)
def test_the_receipt_view_s_other_reads_really_are_optional(field, ceiling):
    """Their defaults are the measurement, not an oversight.

    ``overkill`` is the sharp one: 1,675 of 1,706 is near enough to
    universal that a reader skimming would convert it.
    """
    rows = _receipt_view_input_rows()
    present = sum(1 for row in rows if field in row)
    assert 0 < present < len(rows), field
    assert present / len(rows) <= ceiling, field


def test_three_agreeing_corpora_still_do_not_speak_for_a_fourth_input():
    """The clearest case for measuring the input rather than inferring it.

    ``damage`` is universal on every damage-row corpus this campaign built:
    3,960 internal rows over 173 champions, the 1,706 the receipt view is
    handed, and the 752 published fight rows. Converting
    ``action.event.get("damage", 0.0)`` in ``survival/receipt_ledger`` on
    the strength of those three would have been a bug.

    The rows reaching ``skip()`` are every SKIPPED action, heals included,
    so only ``_event_id``, ``attacker`` and ``time`` are on all of them.
    Agreement between corpora is not evidence about a corpus nobody
    measured.
    """
    import src.calculator.survival.receipt_ledger as receipt_ledger

    seen: list[dict] = []
    original = receipt_ledger.ReceiptLedger.skip

    def spy(self, action, *args, **kwargs):
        event = getattr(action, "event", None)
        if isinstance(event, dict):
            seen.append(dict(event))
        return original(self, action, *args, **kwargs)

    receipt_ledger.ReceiptLedger.skip = spy
    try:
        import sys as _sys

        _sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import golden_snapshot as gs

        gs.rebuild_for(json.loads(BASELINE.read_text(encoding="utf-8")))
    finally:
        receipt_ledger.ReceiptLedger.skip = original

    assert len(seen) > 900
    carrying = sum(1 for row in seen if "damage" in row)
    assert 0 < carrying < len(seen), carrying
    assert _universal(seen) == ("_event_id", "attacker", "time")
