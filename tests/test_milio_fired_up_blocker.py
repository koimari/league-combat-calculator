"""Milio P (Fired Up!) — the recorded, fail-closed source blocker.

Roadmap session 2 closed Taric P by building ``damage.py``'s
``_empower_window_procs``.  Session 1 had blocked BOTH Taric P and
Milio P on that same missing dedup primitive, so the natural reading is
that Milio P is now unblocked too.  It is not, and this module is the
receipt for why.

The dedup dependency IS satisfied (pinned below: the primitive exists
and already accepts an ``ability_hit`` consumer, which is Fired Up!'s
"next basic attack OR ability hit").

MERGE: this branch's ``milio.py`` prices the half the cache sources —
the enchanted hit's burn (10 : 50 by level + 20% of Milio's AP), on a
selectable proc count — so P is ``modeled``, not ``out_of_scope``.  The
three SOURCE blockers below still hold, and they now bound the WITHHELD
half (the AD burst) rather than the whole slot:

1. The burst's "7% / 11% / 15% (based on level) of enchanted target's
   AD" has no per-level array in any cached artifact, and no artifact
   states which levels map to 7 / 11 / 15.
2. The burst scales off the ENCHANTED TARGET's AD (an ally), and this
   engine models a single attacker.
3. W arms Fired Up! every 3 seconds across its 6s hearth, not once at
   the cast, so the primitive's cast-time ``armed_by`` resolution would
   undercount W's arms — which is why the proc count is an OPTION.

These tests assert the ABSENCE of the missing terms on purpose: the
moment a patch pull starts publishing the breakpoints or a ratio, they
fail and force Milio's withheld burst to be revisited rather than
staying quietly shelved behind a stale reason.
"""

import json
from pathlib import Path

from src.calculator.champions import get_champion_module_contract
from src.calculator.champions.milio import ASSUMPTIONS
from src.calculator.damage import _empower_window_procs

# Coverage has one home now: the validated module contract.
MODULE_COVERAGE = get_champion_module_contract("Milio").coverage

_REPO = Path(__file__).resolve().parents[1]
_MILIO_P = json.loads((_REPO / "data" / "champions.json").read_text(encoding="utf-8"))[
    "Milio"
]["abilities"]["P"][0]
_ATOMS = json.loads(
    (_REPO / "data" / "atoms" / "v2" / "milio.atoms.v2.json").read_text(
        encoding="utf-8"
    )
)
_DDRAGON = json.loads(
    (_REPO / "data" / "gamefiles" / "ddragon" / "Milio.json").read_text(
        encoding="utf-8"
    )
)["data"]["Milio"]


def _p_atoms() -> list[dict]:
    """Every atom whose behavior belongs to the Fired Up! passive."""
    rows = _ATOMS if isinstance(_ATOMS, list) else _ATOMS.get("atoms", _ATOMS)
    return [row for row in rows if str(row.get("behavior", "")).startswith("MilioP")]


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

    def test_no_cached_leveling_row_carries_the_burst_values(self) -> None:
        """The two P leveling rows are the BURN, not the burst."""
        first_values = [
            modifier["values"][0]
            for effect in _MILIO_P.get("effects", [])
            for leveling in effect.get("leveling", [])
            for modifier in leveling.get("modifiers", [])
            if modifier.get("values")
        ]
        # 10 == burn total (BaseDamageStart), 1.67 == burn per 0.25s tick.
        assert first_values == [10, 1.67]
        assert 7 not in first_values

    def test_no_leveling_row_ramps_from_seven_to_fifteen(self) -> None:
        for effect in _MILIO_P.get("effects", []):
            for leveling in effect.get("leveling", []):
                for modifier in leveling.get("modifiers", []):
                    values = modifier.get("values") or []
                    assert not (values and values[0] == 7 and 15 in values)

    def test_the_game_file_atoms_publish_no_burst_ratio(self) -> None:
        passive_atoms = _p_atoms()
        assert passive_atoms, "Milio's P atoms disappeared; re-derive the blocker"
        assert {atom["behavior"] for atom in passive_atoms} == {
            "MilioPassive",
            "MilioPBuff",
            "MilioPBurn",
        }
        for atom in passive_atoms:
            parameters = atom.get("parameters", {})
            # None (key absent) and {} both mean "no ratio published";
            # a populated map would fail here and reopen the blocker.
            assert not parameters.get("ratios")
            amounts = parameters.get("effect_amounts", {})
            # Only the burn is quantified: 10 -> 50 over the level ramp.
            assert amounts.get("BaseDamageStart")
            assert amounts.get("BaseDamageEnd")
            assert not [key for key in amounts if "AD" in key or "Ratio" in key]

    def test_ddragon_carries_only_a_numberless_blurb(self) -> None:
        description = _DDRAGON["passive"]["description"]
        assert "7" not in description
        assert "%" not in description

    def test_no_cached_source_states_the_level_breakpoints(self) -> None:
        """The heart of the blocker: three values, no level schedule."""
        haystacks = [json.dumps(_MILIO_P), json.dumps(_p_atoms()), json.dumps(_DDRAGON)]
        for phrase in (
            "levels 1",
            "at level 7",
            "at level 13",
            "increasing at levels",
        ):
            assert not any(phrase in haystack for haystack in haystacks), (
                f"a cached source now states {phrase!r} — Milio P's burst "
                "breakpoints may be sourceable; revisit the blocker"
            )


class TestBlockerTwoTheBurstScalesOffAnotherChampion:
    def test_the_burst_reads_the_enchanted_targets_ad(self) -> None:
        descriptions = " ".join(
            effect.get("description", "") for effect in _MILIO_P.get("effects", [])
        )
        assert "of enchanted target's AD" in descriptions

    def test_the_cached_notes_tag_ally_triggered_damage_as_proc_damage(self) -> None:
        assert "triggered by allies" in _MILIO_P["notes"]


class TestBlockerThreeWArmsOnACadenceNotAtTheCast:
    def test_the_hearth_reapplies_fired_up_on_a_sourced_interval(self) -> None:
        tooltip = _DDRAGON["spells"][1]["tooltip"]
        assert "Fired Up!" in tooltip
        assert "healfrequencyseconds" in tooltip

    def test_the_w_atom_pins_the_three_second_reapplication(self) -> None:
        rows = _ATOMS if isinstance(_ATOMS, list) else _ATOMS.get("atoms", _ATOMS)
        w_atoms = [row for row in rows if row.get("behavior") == "MilioW"]
        assert w_atoms
        assert any(
            "Fired Up! at most once every 3s" in reason
            for atom in w_atoms
            for reason in atom.get("parameters", {}).get("reset_on", [])
        )
        assert any(
            atom.get("parameters", {})
            .get("effect_amounts", {})
            .get("HealFrequencySeconds")
            == [3.0] * 6
            for atom in w_atoms
        )


class TestTheBlockerIsRecorded:
    """The blocker lives in the contract, not only in a docstring."""

    def test_p_prices_the_sourced_half_only(self) -> None:
        # MERGE: this branch models P (the enchanted hit's sourced burn),
        # so the slot is ``modeled``; the blockers above bound the
        # WITHHELD AD burst, which the assumptions below still disclose.
        assert MODULE_COVERAGE["P"] == "modeled"
        assert MODULE_COVERAGE["Q"] == "modeled"
        assert MODULE_COVERAGE["W"] == "modeled"
        assert MODULE_COVERAGE["E"] == "modeled"
        assert MODULE_COVERAGE["R"] == "modeled"

    def test_assumptions_name_all_three_source_blockers(self) -> None:
        blockers = [row for row in ASSUMPTIONS if row.startswith("P (Fired Up!)")]
        assert len(blockers) == 3
        joined = " ".join(blockers)
        assert "7% / 11% / 15%" in joined
        assert "ENCHANTED TARGET's AD" in joined
        assert "every 3 seconds" in joined

    def test_assumptions_record_that_the_dedup_blocker_is_retired(self) -> None:
        """Stops a later session re-citing the session-1 reason.

        The record moved into blocker 3's own row: the primitive is named
        and the reason it is not used is its cast-time ``armed_by``
        resolution, not its absence.
        """
        assert any("_empower_window_procs" in row for row in ASSUMPTIONS)
        assert any("undercount its arms" in row for row in ASSUMPTIONS)
