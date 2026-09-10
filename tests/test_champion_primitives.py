"""Tests for champion-layer primitives shared by all champion modules.

Covers calculate_ability_damage (champions.common), effective_cooldown
(damage.py), castTime extraction (champions.slotlib), skill-order rank
resolution (champions.skill_orders), the shared mechanic shapes
(champions.shared_mechanics) and the composition helpers
(champions.module_helpers).
"""

import re

import pytest

from src.calculator.ability_spec import DamageClass
from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.common import calculate_ability_damage
from src.calculator.champions.inputs import ChampionInputError
from src.calculator.champions.module_helpers import (
    innate_on_hit,
    named_damage,
    no_damage,
)
from src.calculator.champions.shared_mechanics import (
    attack_speed_steroid,
    capped_option,
    damage_reduction_window,
    empowered_auto_entry,
    innate_zero_row,
    move_speed_grant,
    multi_pass_damage,
    per_level_on_hit,
    per_level_row,
    prose_numbers,
    ranked_packet_slot,
    reduced_secondary_hits,
    ticked_channel,
    unreachable_innate,
    with_self_shield,
)
from src.calculator.champions.skill_orders import get_ability_rank
from src.calculator.champions.slot_context import SlotCtx
from src.calculator.champions.slot_extract import extract_cast_time
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import effective_cooldown


class TestCalculateAbilityDamage:
    """Tests for raw ability damage calculation."""

    def test_base_only(self) -> None:
        assert calculate_ability_damage(100, 0.5, 0) == 100.0

    def test_with_scaling(self) -> None:
        result = calculate_ability_damage(100, 0.5, 200)
        assert result == 200.0

    def test_zero_base_with_scaling(self) -> None:
        result = calculate_ability_damage(0, 0.5, 200)
        assert result == 100.0


class TestGetAbilityRank:
    """Tests for skill order (Q > W > E, R at 6/11/16)."""

    def test_level_1_q_rank_1(self) -> None:
        assert get_ability_rank("Q", 1) == 1

    def test_level_6_q_rank_3(self) -> None:
        assert get_ability_rank("Q", 6) == 3

    def test_level_6_w_rank_1(self) -> None:
        assert get_ability_rank("W", 6) == 1

    def test_level_6_e_rank_1(self) -> None:
        assert get_ability_rank("E", 6) == 1

    def test_level_6_r_rank_1(self) -> None:
        assert get_ability_rank("R", 6) == 1

    def test_level_11_q_rank_5(self) -> None:
        assert get_ability_rank("Q", 11) == 5

    def test_level_11_w_rank_3(self) -> None:
        assert get_ability_rank("W", 11) == 3

    def test_level_11_e_rank_1(self) -> None:
        assert get_ability_rank("E", 11) == 1

    def test_level_11_r_rank_2(self) -> None:
        assert get_ability_rank("R", 11) == 2

    def test_level_16_r_rank_3(self) -> None:
        assert get_ability_rank("R", 16) == 3

    def test_level_18_all_maxed(self) -> None:
        assert get_ability_rank("Q", 18) == 5
        assert get_ability_rank("W", 18) == 5
        assert get_ability_rank("E", 18) == 5
        assert get_ability_rank("R", 18) == 3


class TestGetEffectiveCooldown:
    """Tests for cooldown reduction from ability haste."""

    def test_no_haste(self) -> None:
        assert effective_cooldown(7.0, 0.0) == 7.0

    def test_with_haste(self) -> None:
        result = effective_cooldown(7.0, 15.0)
        expected = 7.0 * 100 / 115
        assert abs(result - expected) < 0.01


class TestExtractCastTime:
    """Wiki castTime free text -> seconds of cast lockout."""

    def test_missing_and_none_strings_are_instant(self) -> None:
        assert extract_cast_time({}) == 0.0
        assert extract_cast_time({"castTime": None}) == 0.0
        assert extract_cast_time({"castTime": "none"}) == 0.0
        assert extract_cast_time({"castTime": "None"}) == 0.0
        assert extract_cast_time({"castTime": "false"}) == 0.0

    def test_plain_numbers(self) -> None:
        assert extract_cast_time({"castTime": "0.25"}) == pytest.approx(0.25)
        assert extract_cast_time({"castTime": "1"}) == pytest.approx(1.0)
        assert extract_cast_time({"castTime": 0.5}) == pytest.approx(0.5)

    def test_first_cast_segment_wins_over_recast(self) -> None:
        """'cast • recast': only the first segment locks out the caster."""
        assert extract_cast_time({"castTime": "0.25 • None"}) == pytest.approx(0.25)
        assert extract_cast_time({"castTime": "None • 0.25"}) == 0.0
        assert extract_cast_time({"castTime": "1 • 1.25"}) == pytest.approx(1.0)

    def test_scaling_text_takes_base_value(self) -> None:
        """Level/AS-scaled cast times read the first (slowest) value."""
        assert extract_cast_time(
            {"castTime": "0.25 / 0.225 / 0.2 / 0.175 (based on level)"}
        ) == pytest.approx(0.25)
        assert extract_cast_time(
            {"castTime": "0.25 : 0.1 (based on bonus attack speed)"}
        ) == pytest.approx(0.25)

    def test_windup_percentage_reads_at_base_seconds(self) -> None:
        """'80% of X's windup time (0.4 at base...)': 80 is not seconds."""
        assert extract_cast_time(
            {"castTime": "80% of Senna's windup time (0.4 at base attack speed)"}
        ) == pytest.approx(0.4)

    def test_pure_windup_text_is_instant(self) -> None:
        assert extract_cast_time({"castTime": "Attack Windup Time"}) == 0.0
        assert extract_cast_time({"castTime": "Basic attack timer"}) == 0.0


class TestTargetDebuffDurations:
    """Every resistance shred in the game expires — none is permanent.

    An undeclared duration means "rest of the fight", which over-shreds
    any timed fight longer than the debuff. These are the real in-game
    durations, read from each ability's own wiki description.
    """

    # (champion, slot, level, expected duration in seconds)
    _SHREDS = [
        ("Kog'Maw", "Q", 18, 4.0),  # "for 4 seconds"
        ("Briar", "Q", 18, 5.0),  # "for 5 seconds"
        ("Jarvan IV", "Q", 18, 3.0),  # "for 3 seconds"
        ("Jayce", "R", 18, 5.0),  # "for 5 seconds"
        # Corki's stacks last 2s but REFRESH through his 4s channel, so
        # the shred is up from the cast until 2s after the last tick.
        ("Corki", "E", 18, 6.0),
    ]

    @pytest.mark.parametrize(("champion", "slot", "level", "duration"), _SHREDS)
    def test_shred_declares_its_duration(self, champion, slot, level, duration) -> None:
        abilities = parse_champion_abilities(
            get_champion(champion), level, 100.0, champion_stats={}
        )
        debuff = abilities[slot]["target_debuff"]
        assert debuff["duration"] == pytest.approx(duration)


# ---------------------------------------------------------------------------
# Shared mechanic shapes
# ---------------------------------------------------------------------------


def _row(attribute: str, values: list, units: list | None = None) -> dict:
    """One effects[].leveling[] entry with a single modifier."""
    return {
        "attribute": attribute,
        "modifiers": [{"values": values, "units": units or [""] * len(values)}],
    }


def _json(
    name: str = "Test Ability",
    rows: list | None = None,
    description: str = "",
    cooldowns: list | None = None,
) -> dict:
    """One ability JSON entry: a name, one effect and its leveling rows."""
    ability: dict = {
        "name": name,
        "effects": [{"description": description, "leveling": rows or []}],
    }
    if cooldowns is not None:
        ability["cooldown"] = {
            "modifiers": [{"values": cooldowns, "units": [""] * len(cooldowns)}]
        }
    return ability


def _ctx(slot: str = "Q", **overrides) -> SlotCtx:
    """A slot context with every block a shared helper may read declared."""
    fields = {
        "slot": slot,
        "champion_name": "TestChamp",
        "level": 9,
        "ability_ranks": {"P": 1, "Q": 3, "W": 2, "E": 1, "R": 1},
        "stats": {"ability_power": 100.0, "health": 2000.0},
        "target": {"target_max_health": 2500.0},
        "options": {},
        "option_defaults": {"fight_duration_seconds": 0.0},
    }
    fields.update(overrides)
    return SlotCtx(**fields)


class TestCappedOption:
    """One declared count option, clamped to its cap."""

    def test_it_clamps_between_zero_and_the_cap(self) -> None:
        ctx = _ctx(options={"n": 9}, option_defaults={"n": 0})
        assert capped_option(ctx, "n", 5) == 5
        assert (
            capped_option(_ctx(options={"n": -3}, option_defaults={"n": 0}), "n", 5)
            == 0
        )

    def test_it_reads_the_declared_default_when_unset(self) -> None:
        assert capped_option(_ctx(option_defaults={"n": 2}), "n", 5) == 2

    def test_an_undeclared_option_is_refused(self) -> None:
        """The helper closes the ``.get(key, literal)`` its call sites had."""
        with pytest.raises(ChampionInputError, match="which its OPTIONS"):
            capped_option(_ctx(), "never_declared", 5)


class TestProseNumbers:
    """Numbers a kit states only in a sentence."""

    _PATTERN = re.compile(r"(\d+(?:\.\d+)?)% of maximum health for (\d+(?:\.\d+)?)s")

    def test_it_returns_every_captured_group_as_a_float(self) -> None:
        ctx = _ctx(
            abilities={
                "P": [_json(description="shields for 12% of maximum health for 2s")]
            }
        )
        assert prose_numbers(ctx, "P", self._PATTERN) == (12.0, 2.0)

    def test_an_absent_entry_and_a_missed_match_answer_alike(self) -> None:
        assert prose_numbers(_ctx(abilities={}), "P", self._PATTERN) is None
        ctx = _ctx(abilities={"P": [_json(description="no numbers here")]})
        assert prose_numbers(ctx, "P", self._PATTERN) is None


class TestPerLevelRow:
    """A base stated once per champion level, read at the level."""

    def test_it_reads_the_long_row_at_the_champion_level(self) -> None:
        ctx = _ctx(
            "W", abilities={"W": [_json(rows=[_row("Shield", list(range(1, 21)))])]}
        )
        assert per_level_row(ctx, "Shield", champion="TestChamp") == 9.0

    def test_an_absent_entry_prices_nothing(self) -> None:
        assert per_level_row(_ctx("W", abilities={}), "Shield", champion="X") == 0.0

    def test_a_missing_row_is_a_stop_naming_the_champion_and_slot(self) -> None:
        ctx = _ctx("W", abilities={"W": [_json()]})
        with pytest.raises(ValueError, match="TestChamp W Shield leveling row"):
            per_level_row(ctx, "Shield", champion="TestChamp")

    def test_a_module_may_keep_its_own_refusal_text(self) -> None:
        ctx = _ctx("W", abilities={"W": [_json()]})
        with pytest.raises(ValueError, match="Viktor Q shield leveling row"):
            per_level_row(
                ctx,
                "Shield",
                champion="Viktor",
                stop="Viktor Q shield leveling row is unavailable",
            )


class TestReducedSecondaryHits:
    """A primary hit plus the targets an option counts."""

    @staticmethod
    def _ability() -> dict:
        return _json(
            "Bolt",
            rows=[
                _row("Physical Damage", [100, 100, 100, 100, 100]),
                _row("Reduced Damage", [60, 60, 60, 60, 60]),
            ],
        )

    def _entry(self, targets: int, **kwargs) -> dict:
        ctx = _ctx(options={"n": targets}, option_defaults={"n": 0})
        return reduced_secondary_hits(
            ctx,
            self._ability(),
            3,
            dmg_type="physical",
            primary_row="Physical Damage",
            reduced_row="Reduced Damage",
            option="n",
            lead="primary hit",
            noun="secondary target(s)",
            **kwargs,
        )

    def test_secondary_targets_are_priced_at_the_sourced_reduced_row(self) -> None:
        entry = self._entry(2)
        assert entry["total_raw"] == pytest.approx(220.0)
        assert [part.count for part in entry["parts"]] == [1, 2]
        assert all(part.time_offset == 0.0 for part in entry["parts"])
        assert entry["detail"] == (
            "primary hit + 2 secondary target(s) at the sourced 60% Reduced Damage "
            "row each"
        )

    def test_one_target_certifies_the_single_hit_instead(self) -> None:
        entry = self._entry(0)
        assert entry["event_order_certified"] == "single_hit"
        assert entry["parts"][0].time_offset is None
        assert "detail" not in entry

    def test_an_arrival_kit_keeps_its_offset_and_makes_no_claim(self) -> None:
        """``certify_single_hit=False`` is the Orianna answer: one arrival."""
        entry = self._entry(0, certify_single_hit=False)
        assert "event_order_certified" not in entry
        assert entry["parts"][0].time_offset == 0.0

    def test_the_option_is_capped(self) -> None:
        assert self._entry(50)["parts"][1].count == 5

    def test_an_undeclared_option_is_refused(self) -> None:
        ctx = _ctx()
        with pytest.raises(ChampionInputError):
            reduced_secondary_hits(
                ctx,
                self._ability(),
                3,
                dmg_type="physical",
                primary_row="Physical Damage",
                reduced_row="Reduced Damage",
                option="undeclared",
                lead="primary hit",
                noun="secondary target(s)",
            )


class TestTickedChannel:
    """A channel priced as N even sourced ticks."""

    def test_the_row_is_the_per_tick_number_times_the_tick_count(self) -> None:
        ability = _json("Ray", rows=[_row("Damage Per Tick", [10, 20, 30])])
        entry = ticked_channel(
            _ctx("R"),
            ability,
            2,
            attr="Damage Per Tick",
            dmg_type="magic",
            ticks=13,
            interval=0.2,
            dot_duration=2.6,
            detail=lambda per_tick, total: f"{per_tick:g} x 13 == {total:g}",
        )
        part = entry["parts"][0]
        assert (part.count, part.time_offset, part.hit_interval) == (13, 0.2, 0.2)
        assert entry["total_raw"] == pytest.approx(260.0)
        assert entry["dot_duration"] == 2.6
        assert entry["detail"] == "20 x 13 == 260"

    def test_a_row_the_cache_stopped_carrying_prices_zero(self) -> None:
        """``extract_named`` answers 0.0, so the channel is visibly empty."""
        entry = ticked_channel(
            _ctx("R"),
            _json("Ray"),
            2,
            attr="Damage Per Tick",
            dmg_type="magic",
            ticks=13,
            interval=0.2,
            dot_duration=2.6,
            detail=lambda per_tick, total: f"{per_tick:g}/{total:g}",
        )
        assert entry["total_raw"] == 0.0
        assert entry["detail"] == "0/0"


class TestMultiPassDamage:
    """One cast delivered as several sourced rows."""

    _ABILITY = _json(
        "Grenade",
        rows=[
            _row("Initial Magic Damage", [50, 60, 70]),
            _row("Return Magic Damage", [30, 40, 50]),
        ],
    )

    def _entry(self, *passes, rank: int = 2) -> dict:
        slot = multi_pass_damage("magic", passes=passes, detail="two passes")
        return slot(
            _ctx("W", abilities={"W": [self._ABILITY]}, ability_ranks={"W": rank})
        )

    def test_each_pass_lands_at_its_authored_offset(self) -> None:
        entry = self._entry(("Initial Magic Damage", 0.25), ("Return Magic Damage", 2))
        assert [(part.amount, part.time_offset) for part in entry["parts"]] == [
            (60.0, 0.25),
            (40.0, 2),
        ]
        assert entry["total_raw"] == pytest.approx(100.0)
        assert entry["detail"] == "two passes"

    def test_a_pass_the_cache_lost_is_a_visible_zero_part(self) -> None:
        entry = self._entry(("Initial Magic Damage", 0.0), ("Gone", 1.0))
        assert [part.amount for part in entry["parts"]] == [60.0, 0.0]

    def test_an_unlearned_slot_prices_nothing(self) -> None:
        assert self._entry(("Initial Magic Damage", 0.0), rank=0) is None


class TestEmpoweredAutoEntry:
    """A cast whose payload rides the next basic attack."""

    _PROC = {"name": "Empower", "damage_per_hit": 40.0, "damage_type": "magic"}

    def test_the_shell_carries_the_proc_and_no_direct_damage(self) -> None:
        entry = empowered_auto_entry(
            _json("Empower"), 3, "magic", dict(self._PROC), cooldown=7.0, detail="one"
        )
        assert entry["on_hit"]["damage_per_hit"] == 40.0
        assert entry["parts"] == ()
        assert entry["total_raw"] == 0.0
        assert entry["empowers_next_auto"] is True
        assert entry["detail"] == "one"

    def test_a_rider_becomes_the_rows_one_basic_damage_part(self) -> None:
        entry = empowered_auto_entry(
            _json("Starfire"),
            3,
            "magic",
            dict(self._PROC),
            cooldown=0.0,
            detail="passive plus one swing",
            empowered_damage=125.0,
            target_max_health_sensitive=True,
        )
        part = entry["parts"][0]
        assert (part.amount, part.basic_damage, part.time_offset) == (125.0, True, 0.1)
        assert entry["total_raw"] == 125.0
        assert entry["target_max_health_sensitive"] is True
        assert list(entry)[-1] == "detail"

    def test_a_row_with_no_cached_name_is_refused(self) -> None:
        with pytest.raises(ChampionInputError, match="carries no 'name'"):
            empowered_auto_entry(
                {"effects": []}, 3, "magic", dict(self._PROC), cooldown=0.0, detail="x"
            )


class TestAttackSpeedSteroid:
    """A window's attack speed, weighted by the share of the fight it covers."""

    _ABILITY = _json("Strut", rows=[_row("Bonus Attack Speed", [40, 50, 60, 70, 80])])

    def _entry(self, window: float) -> dict:
        ctx = _ctx("W", option_defaults={"fight_duration_seconds": window})
        return attack_speed_steroid(
            ctx, self._ABILITY, 2, duration=4.0, aside="and nothing else"
        )

    def test_a_window_shorter_than_the_fight_is_time_weighted(self) -> None:
        entry = self._entry(8.0)
        assert entry["stat_buff"]["bonus_attack_speed"] == pytest.approx(25.0)
        assert entry["detail"] == (
            "+50% bonus attack speed for 4s (25% over the fight window); "
            "and nothing else"
        )

    def test_a_fight_with_no_window_takes_the_whole_grant(self) -> None:
        assert self._entry(0.0)["stat_buff"]["bonus_attack_speed"] == pytest.approx(
            50.0
        )

    def test_a_missing_row_grants_nothing_rather_than_a_literal(self) -> None:
        ctx = _ctx("W", option_defaults={"fight_duration_seconds": 0.0})
        entry = attack_speed_steroid(ctx, _json("Strut"), 2, duration=4.0, aside="none")
        assert entry["stat_buff"]["bonus_attack_speed"] == 0.0


class TestMoveSpeedGrant:
    """A cast's own movement grant, on the shared movement fold."""

    def test_the_grant_is_time_weighted_and_the_detail_is_handed_it(self) -> None:
        ctx = _ctx("W", option_defaults={"fight_duration_seconds": 10.0})
        entry = move_speed_grant(
            ctx,
            {"name": "Move Quick", "detail": "stub"},
            granted=60.0,
            duration=5.0,
            detail=lambda published: f"{published:g}% over the fight window",
        )
        assert entry["stat_buff"] == {"move_speed_percent": pytest.approx(30.0)}
        assert entry["detail"] == "30% over the fight window"

    def test_a_zero_grant_still_publishes_its_row(self) -> None:
        """A row that says nothing is granted must not vanish."""
        ctx = _ctx("W", option_defaults={"fight_duration_seconds": 0.0})
        entry = move_speed_grant(
            ctx, {}, granted=0.0, duration=5.0, detail=lambda published: "none"
        )
        assert entry["stat_buff"] == {"move_speed_percent": 0.0}


class TestPerLevelOnHit:
    """An innate's per-level on-hit plus its AP share."""

    _P = _json("Fired Up!", rows=[_row("Per-Level Scaling", list(range(10, 30)))])

    def test_the_row_is_the_per_level_number_plus_the_ap_share(self) -> None:
        ctx = _ctx("P", abilities={"P": [self._P]}, option_defaults={"n": 3})
        entry = per_level_on_hit(
            ctx,
            ap_ratio=0.20,
            count_option="n",
            detail=lambda per_hit, count: f"{count} x {per_hit:g}",
        )
        assert entry["on_hit"]["damage_per_hit"] == pytest.approx(38.0)
        assert entry["on_hit"]["max_procs"] == 3
        assert entry["detail"] == "3 x 38"

    def test_a_row_worth_nothing_emits_nothing(self) -> None:
        ctx = _ctx(
            "P",
            abilities={"P": [_json("Fired Up!")]},
            stats={"ability_power": 0.0},
            option_defaults={"n": 3},
        )
        assert (
            per_level_on_hit(
                ctx, ap_ratio=0.20, count_option="n", detail=lambda per_hit, count: ""
            )
            is None
        )

    def test_an_absent_innate_emits_nothing(self) -> None:
        ctx = _ctx("P", abilities={}, option_defaults={"n": 3})
        assert (
            per_level_on_hit(
                ctx, ap_ratio=0.20, count_option="n", detail=lambda per_hit, count: ""
            )
            is None
        )


class TestInnateZeroRows:
    """The two P rows that publish a boundary instead of a number."""

    def test_an_innate_authored_elsewhere_keeps_a_named_zero_row(self) -> None:
        ctx = _ctx("P", abilities={"P": [_json("Soul Eater", cooldowns=[9, 9, 9])]})
        entry = innate_zero_row(
            ctx, detail="the heal rule authors it", dmg_type="physical"
        )
        assert entry["name"] == "Soul Eater"
        assert (entry["rank"], entry["cooldown"], entry["total_raw"]) == (9, 0.0, 0.0)
        assert entry["damage_type"] == "physical"
        assert entry["parts"] == ()
        assert entry["detail"] == "the heal rule authors it"

    def test_an_unreachable_trigger_quotes_its_sourced_magnitude(self) -> None:
        innate = _json(
            "Surprise", rows=[_row("Bonus True Damage", list(range(100, 120)))]
        )
        ctx = _ctx("P", abilities={"P": [innate]})
        entry = unreachable_innate(
            ctx,
            row="Bonus True Damage",
            dmg_type="true",
            detail=lambda context, would_be: f"{would_be:g} at level {context.level}",
        )
        assert entry["total_raw"] == 0.0
        assert entry["damage_type"] == "true"
        assert entry["detail"] == "108 at level 9"

    def test_both_answer_none_when_the_innate_is_absent(self) -> None:
        ctx = _ctx("P", abilities={})
        assert innate_zero_row(ctx, detail="x") is None
        assert (
            unreachable_innate(
                ctx, row="Bonus True Damage", dmg_type="true", detail=lambda c, w: ""
            )
            is None
        )


class TestDamageReductionWindow:
    """The self-state row a sourced damage-reduction active publishes."""

    @staticmethod
    def _alistar_ctx() -> SlotCtx:
        champion = get_champion("Alistar")
        return _ctx(
            "R",
            champion_name="Alistar",
            abilities=champion["abilities"],
            level=18,
            ability_ranks={"R": 3},
        )

    def _window(self, ctx: SlotCtx) -> dict:
        return damage_reduction_window(
            ctx,
            ctx.ability("R"),
            3,
            duration_source="Alistar.R[0].effects[0].description",
            damage_classes=frozenset({DamageClass.PHYSICAL, DamageClass.MAGIC}),
            detail=lambda percent, duration: f"{percent:g}% for {duration:g}s",
        )

    def test_the_row_carries_the_sourced_multiplier_and_window(self) -> None:
        """A runtime probe through the cached Alistar packet, not a fixture."""
        entry = self._window(self._alistar_ctx())
        state = entry["self_state_events"][0]
        assert entry["total_raw"] == 0.0
        assert state["kind"] == "damage_modifier"
        assert 0.0 < state["multiplier"] < 1.0
        assert state["duration"] > 0.0
        assert state["damage_classes"] == frozenset(
            {DamageClass.PHYSICAL, DamageClass.MAGIC}
        )
        assert entry["detail"].endswith("s")
        assert len(state["source_atoms"]) == 2

    def test_a_percentage_atom_in_other_units_is_refused(self, monkeypatch) -> None:
        module = "src.calculator.champions.shared_mechanics"
        monkeypatch.setattr(
            f"{module}.required_ranked_attribute_atom",
            lambda *args, **kwargs: (55.0, {"units": ["s"]}),
        )
        with pytest.raises(ValueError, match="Alistar R damage-reduction atom"):
            self._window(self._alistar_ctx())

    def test_a_duration_atom_in_other_units_is_refused(self, monkeypatch) -> None:
        module = "src.calculator.champions.shared_mechanics"
        monkeypatch.setattr(
            f"{module}.required_ability_atom", lambda *args, **kwargs: {"units": ["%"]}
        )
        with pytest.raises(ValueError, match="Alistar R active-duration atom"):
            self._window(self._alistar_ctx())


class TestSlotWrappers:
    """The three wrappers a champion module composes a slot out of."""

    @staticmethod
    def _packet(entry):
        def parse(ctx: SlotCtx):
            return dict(entry) if entry is not None else None

        return parse

    def test_a_learned_packet_row_is_handed_to_the_body(self) -> None:
        seen = {}

        def body(ctx, entry, ability, rank):
            seen.update({"rank": rank, "name": ability["name"]})
            entry["detail"] = "re-detailed"
            return entry

        ctx = _ctx("W", abilities={"W": [_json("Move Quick")]})
        entry = ranked_packet_slot(self._packet({"detail": "stub"}), body)(ctx)
        assert entry["detail"] == "re-detailed"
        assert seen == {"rank": 2, "name": "Move Quick"}

    def test_an_unlearned_slot_keeps_the_packets_own_stub(self) -> None:
        def body(ctx, entry, ability, rank):
            raise AssertionError("the body must not run for an unlearned slot")

        ctx = _ctx("W", abilities={"W": [_json()]}, ability_ranks={"W": 0})
        assert ranked_packet_slot(self._packet({"detail": "stub"}), body)(ctx) == {
            "detail": "stub"
        }
        assert ranked_packet_slot(self._packet(None), body)(_ctx("W")) is None

    def test_a_self_shield_rides_the_slots_first_damage_event(self) -> None:
        wrapped = with_self_shield(
            self._packet({"rank": 3, "name": "Q"}),
            shield=lambda ctx: 0.2 * ctx.stat("health"),
            window=2.0,
            source="Mana Barrier",
            detail=lambda ctx, shield: f"shield {shield:g}",
        )
        entry = wrapped(_ctx())
        payload = entry["self_shield_events"][0]
        assert (payload["amount"], payload["duration"]) == (400.0, 2.0)
        assert payload["source"] == "Mana Barrier"
        assert entry["event_order_certified"] == "single_hit"
        assert entry["detail"] == "shield 400"

    def test_an_unlearned_slot_grants_no_shield(self) -> None:
        wrapped = with_self_shield(
            self._packet({"rank": 0}),
            shield=lambda ctx: 1.0,
            window=2.0,
            source="Mana Barrier",
            detail=lambda ctx, shield: "never",
        )
        assert wrapped(_ctx()) == {"rank": 0}

    def test_an_absent_row_grants_no_shield(self) -> None:
        wrapped = with_self_shield(
            self._packet(None),
            shield=lambda ctx: 1.0,
            window=2.0,
            source="Mana Barrier",
            detail=lambda ctx, shield: "never",
        )
        assert wrapped(_ctx()) is None


class TestAdditiveModuleHelpers:
    """The keywords the shared shapes added to the existing helpers."""

    def test_no_damage_takes_a_damage_type_and_a_stated_cooldown(self) -> None:
        ctx = _ctx("W", abilities={"W": [_json("Meditate", cooldowns=[20, 19, 18])]})
        entry = no_damage(ctx, name="Meditate", reason="channel", dmg_type="physical")
        assert (entry["damage_type"], entry["cooldown"]) == ("physical", 19)
        stated = no_damage(
            ctx, name="Meditate", reason="channel", dmg_type="physical", cooldown=0.0
        )
        assert stated["cooldown"] == 0.0

    def test_no_damage_still_answers_none_for_an_unlearned_slot(self) -> None:
        ctx = _ctx("W", abilities={"W": [_json()]}, ability_ranks={"W": 0})
        assert no_damage(ctx, name="x", reason="y", dmg_type="physical") is None

    def test_innate_on_hit_takes_the_kits_own_name_and_detail(self) -> None:
        ctx = _ctx("P", abilities={"P": [_json("P", rows=[_row("Bonus", [1, 2, 3])])]})
        entry = innate_on_hit(
            "Bonus", "magic", name="An Acquired Taste", detail="one stack"
        )(ctx)
        assert entry["name"] == "An Acquired Taste"
        assert entry["detail"] == "one stack"

    def test_innate_on_hit_still_defaults_to_the_cached_name(self) -> None:
        ctx = _ctx("P", abilities={"P": [_json("Innate", rows=[_row("Bonus", [1])])]})
        entry = innate_on_hit("Bonus", "magic")(ctx)
        assert entry["name"] == "Innate"
        assert "detail" not in entry

    def test_named_damage_picks_its_row_from_the_fights_options(self) -> None:
        ability = _json(
            "Eep",
            rows=[
                _row("Magic Damage", [10, 20, 30, 40, 50]),
                _row("Increased Damage", [15, 25, 35, 45, 55]),
            ],
        )
        slot = named_damage(
            lambda ctx: (
                "Increased Damage" if ctx.option("epicenter") else "Magic Damage"
            ),
            "magic",
        )
        ctx = _ctx(abilities={"Q": [ability]}, option_defaults={"epicenter": True})
        assert slot(ctx)["total_raw"] == 35.0
        plain = _ctx(abilities={"Q": [ability]}, option_defaults={"epicenter": False})
        assert slot(plain)["total_raw"] == 30.0

    def test_named_damage_resolves_a_callable_entry_key_with_the_context(self) -> None:
        ability = _json("Shiv", rows=[_row("Magic Damage", [10, 20, 30, 40, 50])])
        ctx = _ctx(abilities={"Q": [ability]}, option_defaults={"execute": True})
        entry = named_damage(
            "Magic Damage",
            "magic",
            detail=lambda context: f"execute={context.option('execute')}",
        )(ctx)
        assert entry["detail"] == "execute=True"

    def test_named_damage_leaves_a_plain_entry_key_alone(self) -> None:
        ability = _json("Shiv", rows=[_row("Magic Damage", [10, 20, 30, 40, 50])])
        ctx = _ctx(abilities={"Q": [ability]})
        entry = named_damage("Magic Damage", "magic", detail="flat")(ctx)
        assert entry["detail"] == "flat"
