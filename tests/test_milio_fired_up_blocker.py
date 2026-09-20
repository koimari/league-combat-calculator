"""Milio P (Fired Up!): the priced burn, and the tripwire on the withheld burst.

``milio.py`` prices the half the cache sources, the enchanted hit's burn of
10 : 50 by level plus 20% of Milio's AP, on a selectable proc count.  The AD
burst beside it is withheld, because its magnitude is prose in every cached
artifact ("7% / 11% / 15% (based on level) of enchanted target's AD", with no
per-level array anywhere), it scales off an ALLY's attack damage where this
engine models one attacker, and W re-arms Fired Up! every 3 seconds across
its 6 s hearth rather than once at the cast.

The tripwire below fails the day a pull reworks that wording, which is when
the withheld half is worth revisiting.  The two tests beside it drive
``_empower_window_procs``, the dedup primitive an earlier reading called
missing.
"""

import json
from pathlib import Path

from src.calculator.fight.autos.empower_windows import _empower_window_procs

_REPO = Path(__file__).resolve().parents[1]
_MILIO_P = json.loads((_REPO / "data" / "champions.json").read_text(encoding="utf-8"))[
    "Milio"
]["abilities"]["P"][0]


class TestTheDedupDependencyIsSatisfied:
    """The session-1 blocker is gone; it must not be cited again."""

    def test_the_proc_window_primitive_exists_and_refreshes_rather_than_stacks(
        self,
    ) -> None:
        window = {
            "armed_by": ("W",),
            "duration": 4.0,
            "charges_per_arm": 1,
            "max_charges": 1,
            "consumed_by": ("auto", "ability_hit"),
        }
        # Two arming casts inside one live window are a REFRESH, so the
        # single charge is spent once -- the exact double-count that
        # ``empowers_next_auto`` would have booked.
        procs = _empower_window_procs(
            window, [0.0, 1.0], [(2.0, "auto"), (3.0, "auto")]
        )
        assert procs == [2.0]

    def test_the_primitive_already_accepts_an_ability_hit_consumer(self) -> None:
        """Fired Up! is spent by "the next basic attack OR ability hit"."""
        window = {
            "armed_by": ("W",),
            "duration": 4.0,
            "charges_per_arm": 1,
            "max_charges": 1,
            "consumed_by": ("auto", "ability_hit"),
        }
        assert _empower_window_procs(window, [0.0], [(1.0, "ability_hit")]) == [1.0]


class TestBlockerOneTheBurstHasNoPriceableMagnitude:
    """7 / 11 / 15 is prose in every cached artifact, with no breakpoints."""

    def test_the_cached_description_still_states_the_bracket_as_prose(self) -> None:
        descriptions = [
            effect.get("description", "") for effect in _MILIO_P.get("effects", [])
        ]
        assert any(
            "7% / 11% / 15% (based on level) of enchanted target's AD" in description
            for description in descriptions
        ), "Milio P's burst wording changed; re-derive the blocker before trusting it"
