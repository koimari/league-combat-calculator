"""K'Sante R — control-duration dedup certification (P1 Package 3J).

Contract under test (P3-3J):

1. K'Sante R has TWO sourced control durations in the cached champion
   (root 0.5s + end-of-displacement stun 0.3s, both in ``effects[0]``;
   ``effects[1]`` carries the terrain branch's airborne 0.264s + stun 0.5s).
   Both values 0.5 and 0.3 MUST survive in the catalog as a typed
   ``timing.control_duration_sequence`` row.
2. The scalar ``timing.control_duration`` must NOT claim multiple
   durations via unioned evidence.  Today the scalar row reads [0.5] with
   receipts from BOTH ``effects[0]`` and ``effects[1]`` — a misleading
   union (effects[1] contains a different duration pair [0.264, 0.5]).
   The contract assertion is written as the fix target and xfailed until
   the coordinator lands the dedup fix (see
   ``test_scalar_must_not_claim_multiple_durations``).
3. Preservation: no numeric value is lost — 0.5 and 0.3 appear via the
   sequence row in BOTH the live atomization and the catalog
   (``data/atoms/abilities.json``).
4. Determinism: two atomizations of the same cached champion produce
   identical records (values, units, evidence, hash).
5. Typed lookup: ``required_ability_atom`` with the exact
   (source, behavior, evidence_prefix) resolves exactly one row for the
   sequence; the scalar query is pinned as observed.
6. Single-duration champions are unchanged: Malphite Q keeps its scalar
   row with ONE value + ONE evidence receipt and gains no sequence row.
7. The atom rows are catalog-only for K'Sante: the champion module never
   imports the atom accessor, and the R runtime packet's damage parts
   come from raw leveling extraction (unchanged by any dedup fix).
"""

import copy
import json
from pathlib import Path

import pytest

from src.calculator.ability_atoms import AbilityAtomQuery, required_ability_atom
from src.calculator.atomizer_domains import atomize_abilities
from src.calculator.champions import parse_champion_abilities
from src.calculator.data_fetcher import get_champion

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "atoms" / "abilities.json"

# Exact source receipts for the two R rows (KSante is the cache key;
# the display/dispatcher name is "K'Sante").
_SEQUENCE_SOURCE = "KSante.R[0].effects[0].description"
_SCALAR_SOURCE = "KSante.R[0].effects[0].description"

# Observed content digests (content-addressed: stable while the cached
# R descriptions are unchanged; patch-day diffs are expected to move them).
_SEQUENCE_HASH_OBSERVED = "ae584f4257399269"
_SCALAR_HASH_OBSERVED = "8c920ea4e4e02b7c"


def _ksante():
    return get_champion("KSante")


def _r_timing_rows(champion):
    return [
        row
        for row in atomize_abilities("KSante", champion)["R"]
        if row["behavior"] == "timing"
    ]


def _sequence_row(rows):
    matches = [r for r in rows if r["atom_id"] == "timing.control_duration_sequence"]
    assert len(matches) == 1, f"expected exactly one sequence row, got {matches}"
    return matches[0]


def _scalar_row(rows):
    matches = [r for r in rows if r["atom_id"] == "timing.control_duration"]
    assert len(matches) == 1, f"expected exactly one scalar row, got {matches}"
    return matches[0]


def test_live_sequence_row_carries_both_control_durations():
    """Live atomization emits the typed sequence with BOTH durations."""
    row = _sequence_row(_r_timing_rows(_ksante()))
    assert row["values"] == [0.5, 0.3]
    assert row["units"] == ["s", "s"]
    assert row["source"] == _SEQUENCE_SOURCE
    assert any(
        ev.startswith("control duration sequence@effects[0].description")
        for ev in row["evidence"]
    )
    assert row["hash"] == _SEQUENCE_HASH_OBSERVED


def test_catalog_sequence_row_matches_live_and_preserves_both_values():
    """The catalog KSante R sequence row is byte-identical to the live
    atomization and preserves both 0.5 and 0.3 (no lost numeric values)."""
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    ksante_rows = catalog["objects"]["KSante"]
    live = _sequence_row(_r_timing_rows(_ksante()))
    catalog_matches = [
        r
        for r in ksante_rows
        if r["atom_id"] == "timing.control_duration_sequence"
        and r["source"] == _SEQUENCE_SOURCE
    ]
    assert len(catalog_matches) == 1, catalog_matches
    assert catalog_matches[0] == live
    assert 0.5 in catalog_matches[0]["values"] and 0.3 in catalog_matches[0]["values"]


def test_scalar_row_as_observed_today():
    # P3-3J: the scalar is emitted from the FIRST control-bearing effect of
    # the entry only, so its evidence is exactly the one receipt from the
    # effect that sourced its value (0.5 root); effects[1]'s different
    # durations no longer over-claim this row.
    row = _scalar_row(_r_timing_rows(_ksante()))
    assert row["values"] == [0.5]
    assert row["units"] == ["s"]
    assert row["source"] == _SCALAR_SOURCE
    assert row["evidence"] == ["control duration@effects[0].description"]
    assert row["hash"] == _SCALAR_HASH_OBSERVED


def test_scalar_must_not_claim_multiple_durations():
    """CONTRACT: the scalar control duration must not claim multiple
    durations via unioned evidence.

    A single-valued scalar is only truthful when its evidence is a single
    receipt from the very effect that sourced its value.  P3-3J fixed the
    emission: the scalar is emitted only from the FIRST control-bearing
    effect of each entry, so the R scalar reads [0.5] with exactly one
    receipt from effects[0] (the effect that sourced its value), while
    effects[1]'s different duration pair lives only in the sequence
    effects — no over-claim.
    """
    row = _scalar_row(_r_timing_rows(_ksante()))
    assert len(row["evidence"]) == 1
    receipt = row["evidence"][0]
    assert receipt.startswith("control duration@effects[0].description")


def test_both_control_values_preserved_via_sequence():
    """Preservation: 0.5 AND 0.3 survive in the catalog — via the sequence
    row, never flattened into the scalar."""
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    rows = [
        r
        for r in catalog["objects"]["KSante"]
        if r["source"].startswith("KSante.R")
        and r["atom_id"]
        in ("timing.control_duration", "timing.control_duration_sequence")
    ]
    sequence = _sequence_row(rows)
    scalar = _scalar_row(rows)
    assert set(sequence["values"]) == {0.5, 0.3}
    assert sequence["units"] == ["s", "s"]
    assert 0.3 not in scalar["values"], "0.3 must not be claimed by the scalar"
    assert 0.5 in scalar["values"]


def test_atomization_is_deterministic():
    """Two atomizations of the cached champion produce identical records —
    values, units, evidence, and hash all stable (contract item 4)."""
    rows_a = _r_timing_rows(copy.deepcopy(_ksante()))
    rows_b = _r_timing_rows(copy.deepcopy(_ksante()))
    assert rows_a == rows_b
    # every timing row's hash recomputes to its own record (no drift)
    for row in rows_a:
        record = {
            k: row[k]
            for k in (
                "atom_id",
                "behavior",
                "source",
                "name",
                "values",
                "units",
                "evidence",
            )
        }
        import hashlib

        expected = hashlib.sha256(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16]
        assert row["hash"] == expected, row["atom_id"]


def test_typed_lookup_sequence_resolves_exactly_one_row():
    """Typed lookup: exact (source, behavior, evidence_prefix) resolves the
    sequence row and only it."""
    atom = required_ability_atom(
        "KSante",
        _ksante(),
        "R",
        query=AbilityAtomQuery(
            source=_SEQUENCE_SOURCE,
            behavior="timing",
            evidence_prefix="control duration sequence@",
        ),
    )
    assert atom["atom_id"] == "timing.control_duration_sequence"
    assert atom["values"] == [0.5, 0.3]
    assert atom["units"] == ["s", "s"]
    assert atom["hash"] == _SEQUENCE_HASH_OBSERVED


def test_typed_lookup_scalar_query_pinned_as_observed():
    """The scalar query (prefix ``control duration@``) resolves exactly one
    row today — the misleading [0.5] union.  # P3-3J contract: after the
    scalar-evidence fix this query may resolve zero or one rows; re-pin."""
    atom = required_ability_atom(
        "KSante",
        _ksante(),
        "R",
        query=AbilityAtomQuery(
            source=_SCALAR_SOURCE,
            behavior="timing",
            evidence_prefix="control duration@",
        ),
    )
    assert atom["values"] == [0.5]
    assert atom["hash"] == _SCALAR_HASH_OBSERVED


def test_single_duration_champion_keeps_scalar_row_unaffected():
    """Single-duration behavior is unchanged: Malphite Q keeps ONE scalar
    row with ONE value + ONE evidence receipt and no sequence row."""
    malphite = get_champion("Malphite")
    rows = atomize_abilities("Malphite", malphite)
    q_rows = [
        r for r in rows["Q"] if r["atom_id"].startswith("timing.control_duration")
    ]
    assert len(q_rows) == 1
    scalar = q_rows[0]
    assert scalar["atom_id"] == "timing.control_duration"
    assert scalar["values"] == [3.0]
    assert scalar["units"] == ["s"]
    assert scalar["evidence"] == ["control duration@effects[0].description"]
    # R stays single-duration too (knockup 1.5s, one receipt)
    r_rows = [
        r for r in rows["R"] if r["atom_id"].startswith("timing.control_duration")
    ]
    assert len(r_rows) == 1
    assert r_rows[0]["values"] == [1.5]
    assert r_rows[0]["evidence"] == ["control duration@effects[0].description"]


def test_ksante_r_atom_rows_are_catalog_only():
    """The dedup fix must not change any runtime packet counts: K'Sante's
    module never consumes the atom accessor, so the atom rows are
    catalog-only and the R packet parts come from raw leveling extraction."""
    module_source = (ROOT / "src" / "calculator" / "champions" / "ksante.py").read_text(
        encoding="utf-8"
    )
    assert "ability_atoms" not in module_source
    assert "required_ability_atom" not in module_source
    assert "atomizer" not in module_source

    champion = _ksante()
    parsed = parse_champion_abilities(
        champion,
        18,
        0.0,
        ability_ranks={"R": 2},
        champion_stats={
            "attack_damage": 100.0,
            "base_attack_damage": 100.0,
            "bonus_attack_damage": 0.0,
            "health": 2000.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
        },
        champion_options={"r_terrain": True},
        target_stats={
            "target_max_health": 3000.0,
            "target_current_health": 3000.0,
            "target_missing_health": 0.0,
        },
    )
    r = parsed["R"]
    assert len(r["parts"]) == 2
    assert [part.time_offset for part in r["parts"]] == [0.3, 0.432]
    assert r["total_raw"] == 230.0
