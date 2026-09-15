"""The two options blocked on data no source here states, and a watch on it.

``scripts/coverage_status.py`` reports exactly two champion options as
blocked rather than derivable: Heimerdinger's turret attack rate and
Kindred's Wolf attack rate. Both are blocked because the number is absent,
not because nobody has written the walk, and deriving either would mean
inventing a value.

Absence is easy to assert and easy to leave asserted forever, so these
watch BOTH places the number could arrive. The day a patch adds it, these
fail and name the option they unblock, instead of the block quietly
outliving its reason.

They are deliberately phrased as "still absent". A failure here is good
news: it means the data landed and an option can be closed.
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAMPIONS = REPO_ROOT / "data" / "champions.json"
BINS = REPO_ROOT / "data" / "bin" / "characters"

#: What an attack rate would look like in either source, however spelled.
RATE_WORDS = re.compile(
    r"attack speed|attacks? per second|attack rate|attacks once every", re.I
)


def _cached(champion: str) -> dict:
    return json.loads(CHAMPIONS.read_text(encoding="utf-8"))[champion]


def _ability_prose(champion: str, slot: str) -> str:
    return " ".join(
        str(effect.get("description", ""))
        for ability in _cached(champion)["abilities"].get(slot, ())
        for effect in ability.get("effects", ())
    )


class TestHeimerdingerSTurretRateIsStillAbsent:
    """``q_turret_attacks`` cannot be derived without the turret's own rate."""

    def test_the_cached_ability_states_no_rate(self):
        prose = _ability_prose("Heimerdinger", "Q")
        assert not RATE_WORDS.search(prose), (
            "Heimerdinger Q now states an attack rate; q_turret_attacks may "
            "be derivable, so re-read coverage_status._BLOCKED_ON_DATA"
        )

    def test_no_tracked_binary_holds_a_turret_record(self):
        """The turret is its own character, and its record is not here.

        Heimerdinger's own bin carries his basic attack only; the turret's
        CharacterRecord lives in a file this repo does not track.
        """
        names = sorted(path.name for path in BINS.glob("*.bin.json"))
        assert "heimerdinger.bin.json" in names, "the probe lost its corpus"
        assert not [name for name in names if "turret" in name.lower()]


class TestKindredSWolfRateIsStillAbsent:
    """``w_attacks`` cannot be derived without Wolf's base rate."""

    def test_the_cache_states_only_the_scaling_and_not_the_base(self):
        prose = _ability_prose("Kindred", "W")
        assert (
            "25% of" in prose and "bonus attack speed" in prose
        ), "Kindred W no longer states the scaling this block rests on"
        assert not re.search(r"attacks (once )?every [\d.]+ seconds", prose, re.I)
        assert not re.search(r"base attack speed of [\d.]+", prose, re.I)

    def test_no_tracked_binary_holds_a_wolf_record(self):
        names = sorted(path.name for path in BINS.glob("*.bin.json"))
        assert "kindred.bin.json" in names, "the probe lost its corpus"
        assert not [name for name in names if "wolf" in name.lower()]


@pytest.mark.parametrize(
    ("option", "champion"),
    [("q_turret_attacks", "Heimerdinger"), ("w_attacks", "Kindred")],
)
def test_the_block_is_still_declared_where_the_page_reads_it(option, champion):
    """The assertion above and the published page cannot drift apart.

    If someone sources the number and derives the option, the table entry
    goes too, and this catches a half-done closure either way.
    """
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import coverage_status

    assert f"{option}:{champion}" in coverage_status._BLOCKED_ON_DATA
