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


class TestTheChargeFieldCapsAreStillAbsent:
    """SR4's seven persistent-object slots, and Caitlyn W's missing stock.

    Each banks one cast because no source here states how many objects may
    stand at once. Verified in BOTH places the number could be: the cached
    ability prose, and the spell objects in the tracked binaries, whose
    scalar fields are cast and missile geometry with no cap among them.

    The distinction this class rests on is between the STOCK, how many
    casts are banked, and the FIELD cap, how many objects may hold at once.
    The binaries do carry the stock, as ``mMaxAmmo`` per rank, which the
    sibling class pins. They do not carry the cap, and it is the cap these
    rules wait on.

    Two of the original nine turned out to state a cap in prose after all,
    which is exactly why this watches rather than asserts once.
    """

    #: ``(champion, slot, the word the cap sentence would name)``.
    SLOTS = [
        ("Gangplank", "E", "keg"),
        ("Jhin", "E", "trap"),
        ("Teemo", "R", "mushroom"),
        ("Zyra", "W", "seed"),
        ("Azir", "W", "soldier"),
        ("Ivern", "W", "brush"),
        ("Kalista", "W", "sentinel"),
    ]

    FIELD_CAP = re.compile(
        r"can be deployed at a time|may be active at a time|at a time|simultaneously",
        re.I,
    )

    @pytest.mark.parametrize(("champion", "slot", "word"), SLOTS)
    def test_no_field_cap_sentence(self, champion, slot, word):
        prose = _ability_prose(champion, slot)
        assert prose, f"{champion} {slot} has no cached prose at all"
        assert not self.FIELD_CAP.search(prose), (
            f"{champion} {slot} now states a field cap; its ChargeRule can "
            f"bank more than one {word}, so re-read SR4"
        )

    def test_caitlyn_w_still_states_no_stock(self):
        """The odd one out: no field cap AND no charge stock."""
        prose = _ability_prose("Caitlyn", "W")
        assert prose
        assert not re.search(r"stocks?\b[^.]*?up to a maximum of \d+", prose, re.I)
        assert not self.FIELD_CAP.search(prose)

    #: ``champion -> (bin slot path fragment, the mMaxAmmo the binary holds)``.
    #: The GAME FILES carry a charge stock for every one of these, per rank,
    #: where the wiki prose carries one for only some. That is a source this
    #: campaign had not looked in, and SR4 says the opposite about Caitlyn.
    BINARY_AMMO = {
        "caitlyn": ("CaitlynWAbility/CaitlynW", [2, 3, 3, 4, 4, 5, 5]),
        "gangplank": ("GangplankEAbility/GangplankE", [3, 3, 3, 4, 4, 5, 5]),
        "jhin": ("JhinEAbility/JhinE", [2, 2, 2, 2, 2, 2, 2]),
        "zyra": ("ZyraWAbility/ZyraW", [2, 2, 2, 2, 2, 2, 2]),
        "azir": ("AzirWAbility/AzirW", [2, 2, 2, 2, 2, 2, 2]),
        "ivern": ("IvernWAbility/IvernW", [3, 3, 3, 3, 3, 3, 3]),
    }

    @pytest.mark.parametrize("stem", sorted(BINARY_AMMO))
    def test_the_binary_carries_a_charge_stock_the_prose_does_not(self, stem):
        """The find, pinned: these stocks are NOT absent, only unread.

        A slot banking one cast because "the cache states no stock" is
        resting on the wiki prose alone. ``mMaxAmmo`` is the game's own
        ammo count and it is in the tracked binary for every one of these,
        Caitlyn included, whose ``ChargeRule`` says no stock exists.

        Wiring it into ``charge_cadence`` moves cast schedules for several
        champions and is its own slice. This asserts the data is there so
        that slice starts from a fact rather than a rediscovery.
        """
        fragment, expected = self.BINARY_AMMO[stem]
        data = json.loads((BINS / f"{stem}.bin.json").read_text(encoding="utf-8"))
        key = next(key for key in data if key.endswith(fragment))
        assert data[key]["mSpell"]["mMaxAmmo"] == expected
