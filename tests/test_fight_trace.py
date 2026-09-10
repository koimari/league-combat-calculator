"""The per-fight trace: its pinned fixture, its measured steps, its refusals."""

import pytest

from src.calculator import trigger_stream
from src.calculator.calculate import calculate_payload
from src.calculator.fight import authorship
from src.calculator.fight.ledger.trace import (
    NO_RAW_PUBLISHED,
    NO_STEP_MEASURED,
    UNACCOUNTED_ROW_TOTAL,
    TraceLine,
    fight_trace,
)
from src.calculator.fight.results import CHAMPION_PRODUCER_PREFIX
from src.calculator.pipeline import run_fight
from src.calculator.scenario import parse_scenario_request, resolve_scenario
from src.calculator.survival.pricing import NO_RESISTANCE_PUBLISHED

#: The one build the trace is pinned on: one item, one spellblade, one on-hit
#: ability, and no amplifier, so every line's arithmetic has no amp term.
FIXTURE_REQUEST = {
    "champion": "Kog'Maw",
    "level": 18,
    "items": ["Dusk and Dawn"],
    "fight_mode": "timed",
    "fight_duration_seconds": 8.0,
    "include_auto_attacks": True,
    "auto_attack_uptime": 1.0,
}

#: The item families the corpus below walks, one build per exclusivity group.
CORPUS_BUILDS = (
    ("Kog'Maw", ("Dusk and Dawn",)),
    ("Kog'Maw", ("Nashor's Tooth", "Wit's End", "Guinsoo's Rageblade", "Terminus")),
    ("Kog'Maw", ("Kraken Slayer", "Statikk Shiv", "Rapid Firecannon", "Stormrazor")),
    (
        "Kog'Maw",
        ("Trinity Force", "Muramana", "Yun Tal Wildarrows", "Runaan's Hurricane"),
    ),
    (
        "Kog'Maw",
        ("Essence Reaver", "Blade of the Ruined King", "Recurve Bow", "Axiom Arc"),
    ),
    ("Darius", ("Titanic Hydra", "Black Cleaver", "Hullbreaker", "Heartsteel")),
    (
        "Darius",
        ("Ravenous Hydra", "Dead Man's Plate", "Bastionbreaker", "Sunfire Aegis"),
    ),
    (
        "Darius",
        ("Profane Hydra", "Unending Despair", "Voltaic Cyclosword", "Umbral Glaive"),
    ),
    ("Ahri", ("Liandry's Torment", "Blackfire Torch", "Shadowflame", "Malignance")),
    ("Ahri", ("Luden's Echo", "Stormsurge", "Horizon Focus", "Hextech Rocketbelt")),
    (
        "Ahri",
        ("Hollow Radiance", "Abyssal Mask", "Hextech Gunblade", "Iceborn Gauntlet"),
    ),
    ("Ahri", ("Lich Bane", "Fated Ashes", "Eclipse", "Hextech Alternator")),
)


def traced(champion: str, items: tuple[str, ...]) -> dict:
    """One build's trace block, through the same boundary the API serves."""
    return calculate_payload(
        {**FIXTURE_REQUEST, "champion": champion, "items": list(items)},
        deterministic=True,
        trace=True,
    )["trace"]


def recorded(champion: str, items: tuple[str, ...]) -> dict:
    """One build's engine result, with the authorship table recorded."""
    request = parse_scenario_request(
        {**FIXTURE_REQUEST, "champion": champion, "items": list(items)},
        deterministic=True,
    )
    resolved = resolve_scenario(request)
    with authorship.recording():
        return run_fight(
            resolved.champion_data,
            request.level,
            list(resolved.items),
            resolved.fight_params,
        )


def pair_half(mechanic: str) -> trigger_stream.MechanicCapability | None:
    """The ``Engine.PAIR`` half of a declared mechanic, itself or its pair."""
    capability = trigger_stream.CAPABILITIES.get(mechanic)
    if capability is None:
        return None
    if capability.engine is trigger_stream.Engine.PAIR:
        return capability
    return trigger_stream.CAPABILITIES.get(capability.pair_of or "")


def declared_item(mechanic: str) -> trigger_stream.MechanicCapability | None:
    """That half again, but only for a mechanic an *item* declares.

    A champion rider names its slot rather than a rule, so it reaches no
    capability at all and this is what tells the two vocabularies apart.
    """
    half = pair_half(mechanic)
    if half is None or not isinstance(half.owner, trigger_stream.ItemOwner):
        return None
    return half


@pytest.fixture(name="fixture_result", scope="module")
def _fixture_result() -> dict:
    """The pinned fight's engine result, recorded."""
    return recorded(*CORPUS_BUILDS[0])


class TestThePinnedFight:
    """Kog'Maw with Dusk and Dawn, row by row."""

    def test_the_fight_is_the_one_the_trace_is_pinned_on(self, fixture_result):
        assert len(fixture_result["breakdown"]) == 9
        assert len(fixture_result["damage_events"]) == 30
        assert round(fixture_result["total_damage"], 4) == 1934.3695
        assert round(fixture_result["effective_armor"], 4) == 75.3333
        assert round(fixture_result["effective_mr"], 4) == 75.3333

    def test_one_line_per_priced_packet(self, fixture_result):
        trace = fight_trace(fixture_result)
        assert len(trace.lines) == 30
        assert trace.effective_armor == fixture_result["effective_armor"]
        assert trace.effective_mr == fixture_result["effective_mr"]

    def test_every_line_names_a_measured_step(self, fixture_result):
        for line in fight_trace(fixture_result).lines:
            assert line.step != NO_STEP_MEASURED, line.source
            assert NO_STEP_MEASURED not in line.refusals, line.source

    def test_the_spellblade_measures_its_declared_pricing_home(self, fixture_result):
        declared = pair_half("dusk_and_dawn.spellblade")
        assert declared is not None
        measured = {
            line.step
            for line in fight_trace(fixture_result).lines
            if line.source == "spellblade_Dusk and Dawn"
        }
        assert measured == {declared.impl}
        assert declared.impl == "fight.autos.spellblade._add_spellblade_damage"

    def test_the_pinned_fight_refuses_nothing(self, fixture_result):
        """Every row states the raw its step priced from and the resistance
        that step mitigated against, so the whole table is numbers."""
        assert fight_trace(fixture_result).refusals_by_source() == {}

    def test_the_shred_lands_after_the_cast_that_applies_it(self, fixture_result):
        """Q meets the MR it shredded, and the rest of the fight meets the shred.

        The fight publishes 75.3333 effective MR, which is post-shred; Q's own
        hits are priced against the 100 they met, so the trace states two
        different numbers for one fight rather than one back-computed average.
        """
        met: dict[str, set[float | None]] = {}
        for line in fight_trace(fixture_result).lines:
            met.setdefault(line.source, set()).add(line.resistance_met)
        assert met.pop("Q") == {100.0}
        published = {
            fixture_result["effective_armor"],
            fixture_result["effective_mr"],
        }
        assert {value for values in met.values() for value in values} == published

    def test_a_stated_raw_is_the_events_own_and_never_the_rows_total(
        self, fixture_result
    ):
        """Kog'Maw R publishes ``total_raw`` 0.0 while its event states 260.5."""
        assert fixture_result["breakdown"]["R"]["total_raw"] == 0.0
        ultimate = next(
            line for line in fight_trace(fixture_result).lines if line.source == "R"
        )
        assert round(ultimate.raw, 4) == 260.5478


class TestABlankColumn:
    """What a line prints when it cannot state a fact, and when it need not."""

    @pytest.fixture(name="titanic", scope="class")
    def _titanic(self) -> dict:
        """A build holding both: rows that refuse, and a true-damage row."""
        champion, items = next(
            build for build in CORPUS_BUILDS if build[1][0] == "Titanic Hydra"
        )
        return recorded(champion, items)

    @pytest.fixture(name="refusing", scope="class")
    def _refusing(self) -> tuple[TraceLine, ...]:
        """Every line the whole corpus refuses a raw or a resistance for."""
        withheld = {NO_RAW_PUBLISHED, NO_RESISTANCE_PUBLISHED}
        return tuple(
            line
            for champion, items in CORPUS_BUILDS
            for line in fight_trace(recorded(champion, items)).lines
            if withheld & set(line.refusals)
        )

    def test_a_refused_line_carries_a_reason_and_no_number(self, refusing):
        """A refusal is never a number: the column it names is blank."""
        assert refusing
        for line in refusing:
            if NO_RAW_PUBLISHED in line.refusals:
                assert line.raw is None, line.source
            if NO_RESISTANCE_PUBLISHED in line.refusals:
                assert line.resistance_met is None, line.source

    def test_the_corpus_names_every_source_that_still_refuses_a_raw(self, refusing):
        """Four families, each a row whose step aggregates its packets before
        authoring them, so no per-instance magnitude is ever in hand."""
        assert {
            line.source for line in refusing if NO_RAW_PUBLISHED in line.refusals
        } == {
            "active_Titanic Hydra",
            "muramana_ability",
            "shadowflame_Shadowflame",
            "stacking_dot_passive",
        }

    def test_the_corpus_names_every_source_that_still_refuses_a_resistance(
        self, refusing
    ):
        """Two shapes, and neither is a mitigation site that forgot to stamp.

        Ahri W and R publish no per-hit events, so the packet the ledger
        synthesizes for their coarse rows passed through no mitigation this
        trace can read one off.  Cinderbloom takes a share of an already
        mitigated packet and meets nothing of its own, the way an amplifier
        does.
        """
        assert {
            line.source for line in refusing if NO_RESISTANCE_PUBLISHED in line.refusals
        } == {"R", "W", "shadowflame_Shadowflame"}

    def test_true_damage_states_no_resistance_and_refuses_nothing(self, titanic):
        """It met none, so the blank is the fact rather than a withheld one."""
        true_lines = [
            line for line in fight_trace(titanic).lines if line.damage_class == "true"
        ]
        assert {line.source for line in true_lines} == {"R"}
        for line in true_lines:
            assert line.resistance_met is None
            assert NO_RESISTANCE_PUBLISHED not in line.refusals


class TestTheLinesSumToTheFight:
    """Every build's lines add up to its total, or name what they cannot place."""

    @pytest.mark.parametrize(
        ("champion", "items"), CORPUS_BUILDS, ids=lambda value: str(value[0])
    )
    def test_a_corpus_build_accounts_for_its_whole_total(self, champion, items):
        result = recorded(champion, items)
        lines = fight_trace(result).lines
        assert round(sum(line.mitigated for line in lines), 4) == round(
            result["total_damage"], 4
        )

    def test_a_row_the_ledger_under_states_keeps_its_residue(self):
        """Darius W prices 1107.6923 and reconstructs two events worth 415.3846."""
        champion, items = next(
            build for build in CORPUS_BUILDS if build[1][0] == "Titanic Hydra"
        )
        result = recorded(champion, items)
        assert round(result["breakdown"]["W"]["total_damage"], 4) == 1107.6923
        residues = [
            line
            for line in fight_trace(result).lines
            if UNACCOUNTED_ROW_TOTAL in line.refusals
        ]
        assert [line.source for line in residues] == ["W"]
        assert round(residues[0].mitigated, 4) == 692.3077
        assert residues[0].raw is None
        assert (
            residues[0].step
            == "fight.rotation.ability_rotation._compute_ability_rotation"
        )


class TestTheMeasuredStep:
    """What the recorder measures, and what it costs when nobody asks."""

    def test_recording_is_off_by_default(self):
        request = parse_scenario_request(FIXTURE_REQUEST, deterministic=True)
        resolved = resolve_scenario(request)
        result = run_fight(
            resolved.champion_data,
            request.level,
            list(resolved.items),
            resolved.fight_params,
        )
        assert type(result["breakdown"]) is dict
        assert authorship.steps_of(result["breakdown"]) == {}

    def test_a_recorded_fight_names_the_frame_that_wrote_each_row(self, fixture_result):
        steps = authorship.steps_of(fixture_result["breakdown"])
        assert set(steps) == set(fixture_result["breakdown"])
        assert steps["auto_attacks"] == "fight.autos.simulation._simulate_auto_attacks"

    def test_recording_does_not_leak_past_its_block(self):
        with authorship.recording():
            assert isinstance(authorship.new_breakdown(), authorship.RecordedBreakdown)
        assert type(authorship.new_breakdown()) is dict


class TestTheAmplifier:
    """An amp is one line naming its pool, not a fact on every packet."""

    @pytest.fixture(name="amped", scope="class")
    def _amped(self) -> dict:
        """A build holding both amp shapes: a whole-total one and Hypershot."""
        return traced("Ahri", ("Riftmaker", "Horizon Focus"))

    def test_each_amplifier_gets_one_line_naming_its_pool(self, amped):
        amps = {line["source"]: line for line in amped["lines"] if line["amp"]}
        assert set(amps) == {"damage_amp_Riftmaker", "damage_amp_Horizon Focus"}
        assert amps["damage_amp_Riftmaker"]["amp"] == "x1.04 over 18 packets"
        assert amps["damage_amp_Horizon Focus"]["amp"] == "x1.1 over 35 packets"

    def test_an_amplifier_states_its_bonus_and_no_packet_facts(self, amped):
        line = next(
            row for row in amped["lines"] if row["source"].startswith("damage_amp_")
        )
        assert line["raw"] is None
        assert line["resistance_met"] is None
        assert line["refusals"] == []
        assert line["step"].startswith("fight.after.amplifiers.")

    def test_the_amplified_lines_carry_no_amp(self, amped):
        for line in amped["lines"]:
            if not line["source"].startswith("damage_amp_"):
                assert line["amp"] == "", line["source"]


class TestTheDeclaredPricingHome:
    """Every item mechanic the corpus reaches measures where it says it lives."""

    @pytest.fixture(name="measured", scope="class")
    def _measured(self) -> dict[str, set[str]]:
        """Each declared mechanic the corpus reached, and the steps that wrote it."""
        reached: dict[str, set[str]] = {}
        for champion, items in CORPUS_BUILDS:
            for line in traced(champion, items)["lines"]:
                if line["mechanic"]:
                    reached.setdefault(line["mechanic"], set()).add(line["step"])
        return reached

    def test_a_champion_rider_names_its_slot_and_declares_no_rule(self, measured):
        """The other vocabulary a mechanic column carries, and its whole extent."""
        riders = {
            mechanic
            for mechanic in measured
            if mechanic.startswith(CHAMPION_PRODUCER_PREFIX)
        }
        assert riders
        assert riders == set(measured) - {
            mechanic for mechanic in measured if declared_item(mechanic)
        }
        assert not riders & set(trigger_stream.CAPABILITIES)

    def test_the_corpus_reaches_the_item_families(self, measured):
        item_owned = {mechanic for mechanic in measured if declared_item(mechanic)}
        assert len(item_owned) >= 30
        assert {declared_item(mechanic).impl for mechanic in item_owned} >= {
            "fight.autos.first_auto_strikes._add_first_auto_strikes",
            "fight.autos.on_hit_layering._layer_on_hit_effects",
            "fight.autos.spellblade._add_spellblade_damage",
            "fight.autos.stacking_strikes._add_stacking_strikes",
            "fight.items.actives._add_item_active_damage",
            "fight.items.burns._add_burn_damage",
            "fight.items.cast_procs._add_item_proc_damage",
        }

    def test_the_measured_step_is_the_declared_impl(self, measured):
        for mechanic, steps in sorted(measured.items()):
            declared = declared_item(mechanic)
            if declared is None:
                continue
            assert steps == {declared.impl}, mechanic

    def test_the_declared_pair_corpus_is_the_size_the_design_measured(self):
        item_pair = [
            capability
            for capability in trigger_stream.CAPABILITIES.values()
            if capability.engine is trigger_stream.Engine.PAIR
            and isinstance(capability.owner, trigger_stream.ItemOwner)
        ]
        assert len(item_pair) == 58
        assert len({capability.impl for capability in item_pair}) == 21


class TestTheTraceBoundary:
    """What ``calculate_payload`` publishes, and what it withholds."""

    def test_the_trace_is_absent_unless_asked_for(self):
        payload = calculate_payload(FIXTURE_REQUEST, deterministic=True)
        assert "trace" not in payload

    def test_asking_for_it_publishes_json_safe_leaves(self):
        trace = calculate_payload(FIXTURE_REQUEST, deterministic=True, trace=True)[
            "trace"
        ]
        assert len(trace["lines"]) == 30
        first = trace["lines"][0]
        assert first["source"] == "Q"
        assert first["raw"] == 314.0
        assert first["resistance_met"] == 100.0
        assert first["refusals"] == []

    def test_each_roster_target_carries_its_own_trace(self):
        payload = calculate_payload(
            {**FIXTURE_REQUEST, "enemies": [{"champion": "Garen", "level": 18}]},
            deterministic=True,
            trace=True,
        )
        assert "trace" not in payload
        for row in payload["targets"]:
            assert row["trace"]["lines"]

    def test_a_light_ledger_fight_is_refused_rather_than_half_traced(self):
        with pytest.raises(ValueError, match="light-ledger"):
            fight_trace({"damage_events_tuple": True})
