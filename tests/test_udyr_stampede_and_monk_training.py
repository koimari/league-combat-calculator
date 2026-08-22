"""Udyr's two remaining slots: E closes ``no_damage``, P stays receipted open.

Roadmap session 5 batch L.  The pair is the whole point of this file: two
zero-damage rows adjudicated DIFFERENTLY under the Olaf-R / Sivir-R rule.

- E (Blazing Stampede) is sourced-NON-damaging — a stance whose only
  leveling rows are movement — so it closes as ``no_damage``.  But
  ``no_damage`` is not ``no effect``: the empowered attack's 0.75s stun is
  sourced twice over (the validated ``timing.control_duration`` atom and
  the game binary's ``UdyrE`` ``StunDuration``), so it is authored as a
  real ``ControlEvent`` (the Lulu W / Rammus E / Darius E precedent)
  rather than left as prose.
- P (Bridge Between) carries Monk Training, a real 30% bonus-attack-speed
  steroid that WOULD change damage.  It stays ``out_of_scope`` with a
  receipt naming the structural blockers — and its blockers are strictly
  worse than Teemo P's in the same batch, because Monk Training's window
  is bounded by ATTACK COUNT as well as time.

Every number is re-derived from ``data/champions.json``, the typed atom
catalog, ``src/calculator/damage.py`` itself and
``data/gamefiles/characters/udyr.bin.json`` rather than trusted from the
module's prose, so a patch that adds a damage row to E, or that starts
publishing the steroid, fails here instead of leaving a stale verdict.
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator import ability_atoms
from src.calculator.ability_atoms import _ability_atoms
from src.calculator.champions import udyr
from src.calculator.data_fetcher import get_champion

RANKS = {"Q": 5, "W": 5, "E": 5, "R": 5}

_WIKI = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))["Udyr"]

# ``data/gamefiles/`` is a gitignored local cdtb cache, so CI has no copy.
# The PRIMARY receipt for every number in this file is the git-tracked
# ``data/champions.json`` and is asserted unconditionally; the binary is a
# SECOND, corroborating source, and the tests that read it skip when the
# cache is absent (the ``test_gnar_mega_gamefile.py`` ternary idiom).
_BIN_PATH = Path("data/gamefiles/characters/udyr.bin.json")
_BIN = json.loads(_BIN_PATH.read_text(encoding="utf-8")) if _BIN_PATH.exists() else None

_DAMAGE_SOURCE = Path("src/calculator/damage.py").read_text(encoding="utf-8")


def _binary_record(object_name: str) -> dict:
    """The binary record whose ``ObjectName`` is ``object_name``."""
    if _BIN is None:
        pytest.skip(f"{_BIN_PATH} absent (gitignored local game-file cache)")
    for value in _BIN.values():
        if isinstance(value, dict) and value.get("ObjectName") == object_name:
            return value
    raise AssertionError(f"{object_name} missing from the cached binary")


def _data_values(object_name: str) -> dict[str, list]:
    return {
        row["name"]: row["values"]
        for row in _binary_record(object_name)["mSpell"]["DataValues"]
    }


def _parse(**ranks) -> dict:
    return udyr.parse_abilities(get_champion("Udyr"), 18, 0.0, dict(RANKS, **ranks), {})


def _e_leveling(attribute: str) -> list[float]:
    """The E movement ladder, read straight out of the tracked cache."""
    for effect in _WIKI["abilities"]["E"][0]["effects"]:
        for row in effect.get("leveling", []):
            if row.get("attribute") == attribute:
                return [float(value) for value in row["modifiers"][0]["values"]]
    raise AssertionError(f"Udyr E {attribute!r} leveling row is missing")


def _e_descriptions() -> list[str]:
    return [
        effect.get("description") or ""
        for entry in _WIKI["abilities"]["E"]
        for effect in entry.get("effects", [])
    ]


def _p_prose() -> str:
    return " ".join(
        effect.get("description") or ""
        for entry in _WIKI["abilities"]["P"]
        for effect in entry.get("effects", [])
    )


def _coupled_fight() -> dict:
    """One coupled rotation against a real enemy — where CC surfaces.

    Udyr rejects manual ability ranks (no ultimate; the API derives them
    from level), so the ranks are the level-18 derived ones, which put E
    at rank 5 — the same rank the parse tests use.
    """
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Udyr",
            "level": 18,
            "items": [],
            "role": "jungle",
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "champion_options": {},
            "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        },
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()


class TestBlazingStampedeIsASourcedZeroDamageRow:
    """E: movement only, so the slot itself closes ``no_damage``."""

    def test_e_emits_a_visible_zero_row(self):
        row = _parse()["E"]

        assert row["name"] == "Blazing Stampede"
        assert row["total_raw"] == 0.0
        assert row["parts"] == ()
        assert row["detail"]

    def test_e_detail_replaces_the_generic_stub(self):
        """The packet's "no enemy-damage formula" boilerplate must be gone."""
        detail = _parse()["E"]["detail"]

        assert "The pinned Wiki packet contains no enemy-damage formula" not in detail
        assert detail.startswith("Stampede Stance:")

    def test_e_detail_carries_the_cached_movement_numbers(self):
        """Rank 5: 49% burst decaying to 14.7%, plus the Awaken payload."""
        detail = _parse()["E"]["detail"]

        assert "49%" in detail
        assert "14.7%" in detail
        assert "5% per 100 bonus AD" in detail
        assert "1.5% per 100 bonus AD" in detail
        assert "75 bonus attack range" in detail
        assert "30% : 41.18%" in detail
        assert "1.5s of crowd-control immunity" in detail

    @pytest.mark.parametrize("rank", [1, 2, 3, 4, 5, 6])
    def test_the_movement_ladder_is_read_at_every_rank(self, rank):
        """Re-derived from the cache, so a stripped row cannot read as 0%."""
        burst = _e_leveling("Bonus Movement Speed")[rank - 1]
        decayed = _e_leveling("Decayed Bonus Movement Speed")[rank - 1]
        detail = _parse(E=rank)["E"]["detail"]

        assert burst > 0.0 and decayed > 0.0
        assert f"{burst:g}%" in detail
        assert f"{decayed:g}%" in detail

    def test_the_cached_ladder_is_the_one_the_receipt_names(self):
        assert _e_leveling("Bonus Movement Speed") == [
            25.0,
            31.0,
            37.0,
            43.0,
            49.0,
            55.0,
        ]
        assert _e_leveling("Decayed Bonus Movement Speed") == [
            7.5,
            9.3,
            11.1,
            12.9,
            14.7,
            16.5,
        ]

    def test_e_has_no_damage_instance_anywhere_in_the_cache(self):
        """Why the slot is ``no_damage`` and not an unpriced damage row."""
        for entry in _WIKI["abilities"]["E"]:
            assert entry["damageType"] is None
            for effect in entry["effects"]:
                for row in effect["leveling"]:
                    assert row["attribute"] in {
                        "Bonus Movement Speed",
                        "Decayed Bonus Movement Speed",
                        "Per-Level Scaling",
                    }

    def test_e_atom_catalog_is_movement_timing_and_control_only(self):
        atoms = _ability_atoms("Udyr", get_champion("Udyr"))["E"]

        assert sorted(atom["atom_id"] for atom in atoms) == [
            "ability.bonus _movement _speed.modifier_0",
            "ability.bonus _movement _speed.modifier_1",
            "ability.decayed _bonus _movement _speed.modifier_0",
            "ability.decayed _bonus _movement _speed.modifier_1",
            "ability.per-_level _scaling",
            "timing.active_duration",
            "timing.control_duration",
            "timing.cooldown",
        ]
        assert not [atom for atom in atoms if atom["atom_id"].startswith("damage")]

    def test_e_publishes_the_burst_grant_as_a_move_speed_stat_buff(self):
        """The cast's own row, on the shared movement-speed channel.

        The magnitude is re-derived from the tracked cache rather than
        restated: rank 5 of the "Bonus Movement Speed" ladder, with the
        row's own "% per 100 bonus AD" modifier resolving to zero on a
        no-item parse.
        """
        row = _parse()["E"]

        assert row["stat_buff"] == {
            "move_speed_percent": _e_leveling("Bonus Movement Speed")[4]
        }
        assert "auto_attack_override" not in row

    def test_the_decayed_and_awaken_rows_stay_withheld(self):
        """One scalar cannot carry a decay curve or an unoptioned recast."""
        row = _parse()["E"]
        decayed = _e_leveling("Decayed Bonus Movement Speed")[4]

        assert row["stat_buff"]["move_speed_percent"] != pytest.approx(decayed)
        assert "not published" in row["detail"]
        assert any(
            "Decayed Bonus Movement Speed" in text and "withheld" in text
            for text in udyr.ASSUMPTIONS
        )

    @staticmethod
    def _fight_move_speed(seconds: float) -> float:
        from src.calculator.pipeline import FightParams, run_fight

        return run_fight(
            get_champion("Udyr"),
            18,
            [],
            FightParams(
                target_health=2000.0,
                target_armor=100.0,
                target_magic_resistance=50.0,
                fight_duration_seconds=seconds,
                deterministic=True,
            ),
        )["champion_stats"]["move_speed"]

    def test_the_fight_folds_the_grant_through_the_shared_move_speed_call(self):
        """Abilities, items and runes all land in one term list."""
        from src.calculator.stats import calculate_total_stats, resolve_move_speed

        build = calculate_total_stats(get_champion("Udyr"), 18, [])
        # Level 18 derives E rank 5 (Udyr's ladder runs to 6); the stance
        # lasts _E_MOVE_SPEED_SECONDS, so a 10s fight earns 4/10 of it.
        granted = _e_leveling("Bonus Movement Speed")[4]
        share = udyr._E_MOVE_SPEED_SECONDS / 10.0
        buffed = self._fight_move_speed(10.0)

        assert buffed == pytest.approx(
            resolve_move_speed(
                build["move_speed_flat"],
                build["move_speed_percent"] + granted * share,
            )
        )
        assert buffed > build["move_speed"]

    def test_the_grant_is_weighted_by_the_stances_window(self):
        """A 4s stance must not read the same in a 5s fight and a 30s one.

        The whole family shares this contract: an unweighted term made
        the published movement number duration-blind.
        """
        assert self._fight_move_speed(5.0) == pytest.approx(472.76)
        assert self._fight_move_speed(10.0) == pytest.approx(417.88)
        assert self._fight_move_speed(30.0) == pytest.approx(372.87, abs=0.01)

    def test_the_window_is_prose_because_no_atom_carries_it(self):
        """Why the constant exists: the only timing atom is the stun's."""
        assert udyr._E_MOVE_SPEED_SECONDS == 4.0
        assert "gains bonus movement speed for 4 seconds" in " ".join(_e_descriptions())
        timings = [
            atom
            for atom in _ability_atoms("Udyr", get_champion("Udyr"))["E"]
            if atom["atom_id"] == "timing.active_duration"
        ]
        assert [atom["values"] for atom in timings] == [[0.75]]


class TestTheStunIsAuthoredAsASourcedControlEvent:
    """``no_damage`` must not mean ``no effect`` — the Lulu W precedent."""

    def test_e_publishes_exactly_one_stun(self):
        events = _parse()["E"]["control_events"]

        assert [event.kind for event in events] == ["stun"]
        assert events[0].duration == pytest.approx(0.75)
        assert events[0].skillshot is False

    def test_the_control_atom_is_the_receipt(self):
        atoms = _parse()["E"]["control_source_atoms"]

        assert len(atoms) == 1
        assert atoms[0]["atom_id"] == "timing.control_duration"
        assert atoms[0]["source"] == "Udyr.E[0].effects[0].description"
        assert atoms[0]["values"] == [0.75]
        assert atoms[0]["units"] == ["s"]

    def test_the_atom_really_comes_from_the_cached_description(self):
        """The tracked-source half: the prose the atom was minted from."""
        stance = _e_descriptions()[0]

        assert "stun them for 0.75 seconds" in stance

    def test_the_duration_is_flat_across_every_rank(self):
        for rank in range(1, 7):
            events = _parse(E=rank)["E"]["control_events"]
            assert events[0].duration == pytest.approx(0.75)

    def test_the_event_is_published_at_cast_boundary_precision(self):
        """``time_offset=None`` is deliberate, not an omission.

        Rammus E, Darius E and Lulu W all stun/taunt ON THE CAST and take
        the wrapper's exact 0.0 offset.  Udyr's stun rides the next
        empowered BASIC ATTACK and the cache carries no cast-to-hit delay,
        so asserting an exact hit time would be inventing one.
        """
        assert _parse()["E"]["control_events"][0].time_offset is None

        compact = " ".join(_DAMAGE_SOURCE.split())
        assert (
            '"exact" if control.time_offset is not None else "cast_boundary"' in compact
        )

    def test_the_stun_is_not_repeated_inside_its_sourced_on_target_cooldown(self):
        """``count`` stays 1: the on-target cooldown outlasts the rotation."""
        event = _parse()["E"]["control_events"][0]

        assert event.count == 1
        assert event.hit_interval is None
        assert (
            _WIKI["abilities"]["E"][0]["onTargetCdStatic"]
            == "6 / 5.6 / 5.2 / 4.8 / 4.4 / 4"
        )
        assert "cannot affect the same target more than once" in _e_descriptions()[0]

    def test_an_unlearned_e_publishes_no_control_event(self):
        row = _parse(E=0)["E"]

        assert "control_events" not in row
        assert "control_source_atoms" not in row
        assert row["total_raw"] == 0.0

    def test_a_stripped_description_fails_closed(self, monkeypatch):
        """No literal fallback: a degraded cache must raise, not drop the stun.

        The stun duration is read ONLY through the atom catalog, and that
        catalog is memoized on ``(data_version(), champion_name)`` — not on
        the identity of the mapping handed in.  Degrading a deep copy
        in-process therefore changes nothing by itself: an earlier parse in
        this file has already filled the memo for "Udyr" at this
        generation, and the good rows would be served straight back.  The
        real event this stands for — a refreshed cache — moves the
        generation and so empties the memo, and an empty memo is exactly
        what is installed here.  The assertion is unchanged; only the
        precondition is now stated instead of assumed.
        """
        monkeypatch.setattr(ability_atoms, "_ABILITY_ATOMS_MEMO", {})
        data = json.loads(json.dumps(get_champion("Udyr")))
        for entry in data["abilities"]["E"]:
            for effect in entry["effects"]:
                effect["description"] = ""

        with pytest.raises((KeyError, ValueError)):
            udyr.parse_abilities(data, 18, 0.0, dict(RANKS), {})

    def test_the_stripped_description_guard_is_not_vacuous(self, monkeypatch):
        """The cold catalog alone must NOT raise — only the degraded one.

        Without this, the test above would still pass if clearing the memo
        were what broke the parse rather than the missing description.
        """
        monkeypatch.setattr(ability_atoms, "_ABILITY_ATOMS_MEMO", {})
        data = json.loads(json.dumps(get_champion("Udyr")))

        row = udyr.parse_abilities(data, 18, 0.0, dict(RANKS), {})["E"]
        assert row["control_events"][0].duration == pytest.approx(0.75)

    def test_the_binary_corroborates_the_stun_duration(self):
        """The SECOND receipt — skips without the local cache."""
        assert set(_data_values("UdyrE")["StunDuration"]) == {0.75}

    def test_the_binary_on_target_cooldown_matches_the_wiki_ladder(self):
        """Riot ``DataValues`` are rank-0-indexed; indices 1-6 are ranks 1-6."""
        icd = _data_values("UdyrE")["ICD"]
        wiki = [
            float(value)
            for value in _WIKI["abilities"]["E"][0]["onTargetCdStatic"].split(" / ")
        ]

        assert icd[1:7] == pytest.approx(wiki, abs=1e-6)

    def test_the_binary_corroborates_the_named_awaken_payload(self):
        values = _data_values("UdyrE")

        assert set(values["MoveSpeedDuration"]) == {4.0}
        assert set(values["EmpoweredBonusRange"]) == {75.0}
        assert set(values["UnstoppableDuration"]) == {1.5}


class TestTheStunReachesTheLiveFight:
    """The engine surface: a zero-damage row that still costs enemy actions."""

    def test_the_coupled_fight_emits_exactly_one_stun(self):
        """One stun from E, and the rest of the fight's control is R's.

        The filter names ``stun`` rather than "any reviewed control"
        because Udyr's OTHER reviewed control reaches this same fight:
        ``MODULE_CC`` marks R a slow, so Wingborne Storm's eight blizzard
        ticks each carry one.  Counting every ``cc_kind`` event would
        therefore count R's slows as if the stun had repeated.  Both
        populations are pinned exactly, so a stun that leaked onto the
        auto stream still fails here.
        """
        events = [
            event
            for event in _coupled_fight()["combat"]["events"]
            if event.get("cc_kind")
        ]
        stuns = [event for event in events if event["cc_kind"] == "stun"]

        assert len(stuns) == 1
        assert stuns[0]["cc_duration"] == pytest.approx(0.75)
        assert stuns[0]["source"] == "E"
        assert stuns[0]["time"] == pytest.approx(0.0)
        assert stuns[0]["event_precision"] == "cast_boundary"

        # The remainder is R's reviewed slow, one per blizzard tick, and
        # nothing else: no third control kind and no second E event.
        others = [event for event in events if event["cc_kind"] != "stun"]
        assert [(event["source"], event["cc_kind"]) for event in others] == [
            ("R", "slow")
        ] * 8

    def test_the_live_event_carries_the_atom_receipt(self):
        event = next(
            event
            for event in _coupled_fight()["combat"]["events"]
            if event.get("cc_kind")
        )
        atom = event["control_source_atoms"][0]

        assert atom["atom_id"] == "timing.control_duration"
        assert atom["source"] == "Udyr.E[0].effects[0].description"
        assert atom["values"] == [0.75]
        assert atom["units"] == ["s"]

    def test_the_stun_prices_no_damage(self):
        fight = _coupled_fight()
        event = next(
            event for event in fight["combat"]["events"] if event.get("cc_kind")
        )

        assert event["damage"] == pytest.approx(0.0)
        assert event["damage_type"] == ""
        assert fight["breakdown"]["E"]["total_damage"] == pytest.approx(0.0)

    def test_the_stun_costs_the_enemy_action_time(self):
        """The whole reason the slot authors a ControlEvent at all."""
        participants = {
            participant["participant_id"]: participant
            for participant in _coupled_fight()["combat"]["participants"]
        }
        enemy = participants["enemy:Aatrox"]["survival"]

        assert enemy["action_downtime"] == pytest.approx(0.75)
        assert enemy["crowd_control_until"] == pytest.approx(0.75)
        assert enemy["crowd_control_intervals"] == [
            {
                "recipient": "enemy:Aatrox",
                "kind": "stun",
                "start": 0.0,
                "end": 0.75,
                "source": "Blazing Stampede",
            }
        ]
        assert participants["main"]["survival"]["action_downtime"] == 0.0


class TestBridgeBetweenStaysReceiptedOpen:
    """P: a real attack-speed steroid, so ``out_of_scope``, not ``no_damage``."""

    def test_p_emits_a_visible_zero_row_naming_the_steroid(self):
        row = _parse()["passive"]

        assert row["name"] == "Bridge Between"
        assert row["total_raw"] == 0.0
        assert row["parts"] == ()
        assert "Monk Training" in row["detail"]
        assert "30% bonus attack speed" in row["detail"]
        assert "NOT modeled" in row["detail"]

    def test_p_publishes_nothing_to_the_engine(self):
        """The withholding is the assertion: nothing reaches the engine."""
        row = _parse()["passive"]

        for key in (
            "stat_buff",
            "auto_attack_override",
            "on_hit",
            "control_events",
            "empowers_next_auto",
        ):
            assert key not in row

    def test_the_receipt_names_both_blockers(self):
        detail = _parse()["passive"]["detail"]

        assert "Q-slot-only" in detail
        assert "bounded by attack count" in detail
        assert "cooldown refund has no engine channel" in detail

    def test_monk_training_is_sourced_by_the_tracked_wiki_prose(self):
        """The PRIMARY receipt — runs everywhere, tracked source."""
        prose = _p_prose()

        assert "Monk Training" in prose
        assert "next two basic attacks" in prose
        assert "within 4 seconds" in prose
        assert "30% bonus attack speed" in prose
        assert "refund 5% of Awakened Spirit's total cooldown" in prose

    def test_monk_training_is_corroborated_by_the_binary(self):
        """The SECOND receipt — skips without the local cache."""
        calc = _binary_record("UdyrPassive")["mSpell"]["mSpellCalculations"][
            "AttackSpeed"
        ]
        parts = calc["mFormulaParts"]

        assert calc["mDisplayAsPercent"] is True
        assert len(parts) == 1
        assert parts[0]["__type"] == "NumberCalculationPart"
        assert parts[0]["mNumber"] == pytest.approx(0.30, abs=1e-6)

        values = _data_values("UdyrPassive")
        assert set(values["AttackSpeedDuration"]) == {4.0}
        assert values["UltCDReduction"] == pytest.approx(
            [0.05] * len(values["UltCDReduction"]), abs=1e-6
        )
        assert set(values["GlobalCD"]) == {1.5}

    def test_the_cache_carries_no_atom_for_the_steroid(self):
        """Why no typed atom exists even though the value is known."""
        for entry in _WIKI["abilities"]["P"]:
            assert entry["damageType"] is None
            for effect in entry["effects"]:
                assert effect["leveling"] == []

        assert tuple(_ability_atoms("Udyr", get_champion("Udyr"))["P"]) == ()

    def test_the_windowed_attack_speed_kernel_is_q_slot_only(self):
        """Blocker one, asserted against the engine source.

        ``damage.py`` resolves an ``auto_attack_override.active_duration``
        window's START by walking ``cast_order`` and breaking on ``"Q"``.
        A P-slot steroid has no window to ride, so it could only be
        published unwindowed for the entire fight.
        """
        anchor = _DAMAGE_SOURCE.index('if "bonus_attack_speed" in stat_buff:')
        kernel = _DAMAGE_SOURCE[anchor : anchor + 2000]

        assert "auto_attack_override" in kernel
        assert "for slot in state.cast_order:" in kernel
        assert 'if slot == "Q":' in kernel
        assert 'if slot == "P":' not in kernel

    def test_the_engine_window_is_time_bounded_with_no_attack_count_bound(self):
        """Blocker one, second half: Monk Training ends on the 2nd attack.

        Tristana Q and Twitch Q in this same batch are purely
        time-bounded, which is why they get the exact window and this
        slot does not.
        """
        prose = _p_prose()
        assert "next two basic attacks" in prose

        compact = " ".join(_DAMAGE_SOURCE.split())
        assert (
            'ability_sub_payload(ability_info, "auto_attack_override") '
            ').get("active_duration")' in compact
        )
        for count_bound in ("attack_count", "max_attacks", "active_attacks"):
            assert count_bound not in _DAMAGE_SOURCE, count_bound

    def test_the_only_per_attack_cooldown_refund_path_is_item_fed(self):
        """Blocker two, asserted against the engine source.

        The engine does have a per-auto cooldown refund — Navori
        Flickerblade's — but its value is fed exclusively from the item's own
        crit declaration, whose number is a reference into ``item_effects``.
        No champion entry key reaches it, so Monk Training's 5% refund has no
        channel to publish into.
        """
        assignments = {
            line.split("=", 1)[1].strip()
            for line in _DAMAGE_SOURCE.splitlines()
            if line.strip().startswith("result.navori_refund =")
        }

        assert assignments == {"refund.fraction if refund is not None else 0.0"}
        assert "refund = _crit_profile(state).cooldown_refund" in _DAMAGE_SOURCE
        item_source = Path("src/calculator/item_effects.py").read_text(encoding="utf-8")
        assert "cd_refund_percent" in item_source
        assert "navori_refund" not in json.dumps(list(_parse()["passive"].keys()))


class TestModuleCoverageRecordsTheSplitVerdict:
    def test_coverage_map(self):
        assert udyr.MODULE_COVERAGE == {
            "P": "out_of_scope",
            "Q": "modeled",
            "W": "modeled",
            "E": "no_damage",
            "R": "modeled",
        }

    def test_the_assumptions_carry_both_verdicts(self):
        stun = next(a for a in udyr.ASSUMPTIONS if "sourced control event" in a)
        assert "0.75s" in stun
        assert "timing.control_duration" in stun
        assert "cast_boundary" in stun

        withheld = next(a for a in udyr.ASSUMPTIONS if "Monk Training" in a)
        assert "out_of_scope, not no_damage" in withheld
        assert "Miss " in withheld  # the Miss Fortune W precedent, named

    def test_closing_e_did_not_move_any_priced_row(self):
        parsed = _parse()

        assert parsed["Q"]["total_raw"] == pytest.approx(60.0)
        assert parsed["R"]["total_raw"] == pytest.approx(336.0)
        assert parsed["W"]["total_raw"] == 0.0
        assert parsed["E"]["total_raw"] == 0.0
        assert parsed["passive"]["total_raw"] == 0.0

    def test_the_q_options_still_default_as_reviewed(self):
        options = {option["key"]: option for option in udyr.OPTIONS}

        assert options["q_awaken"]["default"] is False
        assert options["q_empowered_attacks"]["default"] == 2
        assert "e_" not in "".join(options)
