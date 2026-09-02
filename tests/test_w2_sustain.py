"""Self-heal and self-shield rows the coverage-frontier sustain slice landed.

Six sustain mechanics that had a cached row and no rule, plus Vi's Blast Shield and the
two grey-health slots whose primitive already prices them.

One test per slot, each pinning the number a ``/api/calculate`` fight
publishes against the cached row it comes from.  Four of the six are player
state a duel cannot derive — kills, nearby deaths, Fury, carried Triumph
stacks — so their options default to 0 and the fight publishes nothing until
the option is set; that default is pinned too, because it is what keeps a
default request's numbers where they were.
"""

import itertools

import pytest

from src import app as app_module
from src.calculator.champions import (
    get_champion_module_contract,
    parse_champion_abilities,
)
from src.calculator.champions.slotlib import extract_value
from src.calculator.data_fetcher import get_champion

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_ENEMY = {"champion": "Ahri", "level": 18, "items": [], "role": "mid"}


def _fight(champion, *, options=None, duration=10, autos=True, enemy_ranks=None):
    """One level-18 ``/api/calculate`` fight, returned whole."""
    payload = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": "top",
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": autos,
        "ability_ranks": dict(_RANKS),
        "enemies": [dict(_ENEMY, ability_ranks=enemy_ranks or dict(_RANKS))],
    }
    if options is not None:
        payload["champion_options"] = options
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _heals(payload, source):
    return [
        event for event in payload["self_healing_events"] if event["source"] == source
    ]


def _grey_shields(payload):
    """The self-shields Thick Skin's grey-health presses published."""
    return [
        event
        for event in payload["combat"]["support_events"]
        if event["target"] == "main" and event["source"] == "Thick Skin (grey health)"
    ]


def _main_survival(payload):
    return next(
        participant["survival"]
        for participant in payload["combat"]["participants"]
        if participant["participant_id"] == "main"
    )


# ---------------------------------------------------------------------------
# Slice 5 — self-heal with a cached row and no rule
# ---------------------------------------------------------------------------


class TestDrMundoGoesWhereHePleases:
    """P: the additional regeneration, on the half-second the row names."""

    def test_the_half_second_row_is_the_second_max_health_damage_row(self):
        """The cache states the same stream twice and mislabels both."""
        ability = get_champion("Dr. Mundo")["abilities"]["P"][0]
        per_five = extract_value(ability, "Max Health Damage", 18, level=18)
        per_half = extract_value(
            ability, "Max Health Damage", 18, level=18, occurrence=1
        )
        assert per_five == pytest.approx(2.3)
        assert per_half == pytest.approx(0.23)
        assert per_half * 10 == pytest.approx(per_five, rel=1e-9)

    def test_the_fight_pays_one_tick_every_half_second(self):
        """0.23% of the maximum health R raised, 0.5s to the fight's end."""
        payload = _fight("Dr. Mundo")
        heals = _heals(payload, "Goes Where He Pleases")
        buffed_health = payload["champion_stats"]["health"]
        per_tick = 0.0023 * buffed_health
        assert [round(heal["time"], 2) for heal in heals] == [
            round(0.5 * step, 2) for step in range(1, 21)
        ]
        assert all(
            heal["amount"] == pytest.approx(per_tick, abs=0.05) for heal in heals
        )
        assert per_tick == pytest.approx(5.911, abs=0.01)

    def test_the_slot_declares_the_channel_that_pays_it(self):
        contract = get_champion_module_contract("Dr. Mundo")
        assert contract.coverage["P"] == "modeled"
        assert contract.coverage_channels["P"] == ("self_healing_rule",)


class TestMordekaiserRealmOfDeath:
    """R: 10% of the banished champion's maximum health, at the cast."""

    def test_the_slot_prices_the_drain_against_this_fights_target(self):
        """The rule never sees target stats, so the slot carries the amount."""
        parsed = parse_champion_abilities(
            get_champion("Mordekaiser"),
            18,
            0.0,
            ability_ranks=dict(_RANKS),
            target_stats={"target_max_health": 2400.0, "roster_target_index": 0},
        )
        assert parsed["R"]["self_heal_state"] == {"percent": 10.0, "amount": 240.0}

    def test_a_secondary_roster_target_does_not_author_a_second_drain(self):
        """One banishment is one heal, not one per enemy in the roster."""
        parsed = parse_champion_abilities(
            get_champion("Mordekaiser"),
            18,
            0.0,
            ability_ranks=dict(_RANKS),
            target_stats={"target_max_health": 2400.0, "roster_target_index": 1},
        )
        assert "self_heal_state" not in parsed["R"]

    def test_the_fight_heals_at_the_r_cast(self):
        payload = _fight("Mordekaiser")
        (heal,) = _heals(payload, "Realm of Death")
        enemy_health = next(
            participant["stats"]["health"]
            for participant in payload["combat"]["participants"]
            if participant["participant_id"] != "main"
        )
        r_cast = next(
            cast["time"] for cast in payload["cast_timeline"] if cast["slot"] == "R"
        )
        assert heal["amount"] == pytest.approx(0.10 * enemy_health, abs=0.05)
        assert heal["amount"] == pytest.approx(235.8, abs=0.1)
        assert heal["time"] == pytest.approx(r_cast)


class TestChogathCarnivore:
    """P: 18 : 52 (based on level) per kill, count supplied by the option."""

    def test_a_duel_with_no_declared_kills_heals_nothing(self):
        assert _heals(_fight("Cho'Gath"), "Carnivore") == []

    def test_each_declared_kill_pays_the_cached_level_row(self):
        ability = get_champion("Cho'Gath")["abilities"]["P"][0]
        per_kill = extract_value(ability, "Heal", 18, level=18)
        assert per_kill == pytest.approx(52.0)
        heals = _heals(
            _fight("Cho'Gath", options={"p_carnivore_kills": 3}), "Carnivore"
        )
        assert len(heals) == 3
        assert all(
            heal["amount"] == pytest.approx(per_kill, abs=0.05) for heal in heals
        )

    def test_the_kills_ride_the_fights_own_hits(self):
        """No kill is simulated, so the count is declared and the times measured."""
        payload = _fight("Cho'Gath", options={"p_carnivore_kills": 3})
        hit_times = sorted(
            event["time"] for event in payload["damage_events"] if event["damage"] > 0.0
        )
        assert [heal["time"] for heal in _heals(payload, "Carnivore")] == hit_times[:3]


class TestTrundleKingsTribute:
    """P: a share of the dying unit's maximum health, per nearby death."""

    def test_a_duel_with_no_declared_deaths_heals_nothing(self):
        assert _heals(_fight("Trundle"), "King's Tribute") == []

    def test_each_declared_death_pays_the_cached_level_row(self):
        ability = get_champion("Trundle")["abilities"]["P"][0]
        percent = extract_value(ability, "Max Health Damage", 18, level=18)
        assert percent == pytest.approx(5.5)
        payload = _fight("Trundle", options={"p_nearby_deaths": 3})
        heals = _heals(payload, "King's Tribute")
        enemy_health = next(
            participant["stats"]["health"]
            for participant in payload["combat"]["participants"]
            if participant["participant_id"] != "main"
        )
        assert len(heals) == 3
        assert all(
            heal["amount"] == pytest.approx(percent / 100.0 * enemy_health, abs=0.05)
            for heal in heals
        )
        assert heals[0]["amount"] == pytest.approx(129.7, abs=0.1)


class TestReksaiFuryOfTheXersai:
    """P: the burrow consumes Fury to heal a share of maximum health."""

    def test_no_declared_fury_heals_nothing(self):
        assert _heals(_fight("Rek'Sai"), "Fury of the Xer'Sai") == []

    def test_full_fury_pays_the_whole_level_row_at_the_first_w(self):
        ability = get_champion("Rek'Sai")["abilities"]["P"][0]
        percent = extract_value(ability, "Max Health Damage", 18, level=18)
        assert percent == pytest.approx(20.0)
        payload = _fight("Rek'Sai", options={"p_burrow_fury": 100})
        (heal,) = _heals(payload, "Fury of the Xer'Sai")
        max_health = payload["champion_stats"]["health"]
        first_w = min(
            cast["time"] for cast in payload["cast_timeline"] if cast["slot"] == "W"
        )
        assert heal["amount"] == pytest.approx(percent / 100.0 * max_health, abs=0.05)
        assert heal["amount"] == pytest.approx(456.6, abs=0.1)
        assert heal["time"] == pytest.approx(first_w)

    def test_half_fury_pays_half_the_row(self):
        """ "0% : 100% (based on Fury)" is linear in the Fury spent."""
        (full,) = _heals(
            _fight("Rek'Sai", options={"p_burrow_fury": 100}), "Fury of the Xer'Sai"
        )
        (half,) = _heals(
            _fight("Rek'Sai", options={"p_burrow_fury": 50}), "Fury of the Xer'Sai"
        )
        assert half["amount"] == pytest.approx(full["amount"] / 2.0, abs=0.05)


class TestAlistarTriumphantRoar:
    """P: the seventh Triumph stack heals 5% of maximum health."""

    def test_a_duel_with_no_carried_stacks_never_completes_the_set(self):
        """Q and W give two stacks against one champion; the set needs seven."""
        assert _heals(_fight("Alistar"), "Triumphant Roar") == []

    def test_six_carried_stacks_complete_the_set_on_the_q_cast(self):
        payload = _fight("Alistar", options={"p_triumph_stacks": 6})
        (heal,) = _heals(payload, "Triumphant Roar")
        max_health = payload["champion_stats"]["health"]
        q_cast = min(
            cast["time"] for cast in payload["cast_timeline"] if cast["slot"] == "Q"
        )
        assert heal["amount"] == pytest.approx(0.05 * max_health, abs=0.06)
        assert heal["amount"] == pytest.approx(136.2, abs=0.1)
        assert heal["time"] == pytest.approx(q_cast)

    def test_five_carried_stacks_wait_for_the_w_cast(self):
        payload = _fight("Alistar", options={"p_triumph_stacks": 5})
        (heal,) = _heals(payload, "Triumphant Roar")
        w_cast = min(
            cast["time"] for cast in payload["cast_timeline"] if cast["slot"] == "W"
        )
        assert heal["time"] == pytest.approx(w_cast)


# ---------------------------------------------------------------------------
# Slice 7 — the residue: a home exists, and what routes to it
# ---------------------------------------------------------------------------


class TestViBlastShield:
    """P: the sourced shield rides the first ranked damage slot."""

    def test_the_payload_hangs_on_q_and_carries_the_cached_percentage(self):
        parsed = parse_champion_abilities(
            get_champion("Vi"),
            18,
            0.0,
            ability_ranks=dict(_RANKS),
            champion_stats={"health": 2440.0},
            target_stats={"roster_target_index": 0},
        )
        (payload,) = parsed["Q"]["self_shield_events"]
        assert payload == {
            "amount": pytest.approx(0.12 * 2440.0),
            "duration": 3.0,
            "source": "Blast Shield",
            "actor_wide": True,
        }
        assert "self_shield_events" not in parsed["E"]
        assert "self_shield_events" not in parsed["R"]

    def test_the_ledger_grants_it_at_qs_hit(self):
        payload = _fight("Vi")
        shields = [
            event
            for event in payload["combat"]["support_events"]
            if event["target"] == "main" and event["source"] == "Blast Shield"
        ]
        max_health = _main_survival(payload)["max_health"]
        (shield,) = shields
        assert shield["amount"] == pytest.approx(0.12 * max_health, abs=0.05)
        assert shield["amount"] == pytest.approx(292.8, abs=0.1)

    def test_the_granted_shield_absorbs_something_when_its_carrier_lands(self):
        """The mechanism itself is sound: an unimpeded Q pays the shield.

        This is the control for the defect pinned below.  Ahri with no
        ranked abilities never charms Vi, so the carrier Q lands, the rider
        arms at its timestamp, and the shield absorbs.  Nothing about the
        rider is broken -- only its binding to a carrier chosen before the
        walk knew which packets land.
        """
        payload = _fight("Vi", enemy_ranks={"Q": 0, "W": 0, "E": 0, "R": 0})
        assert _main_survival(payload)["shield_absorbed"] > 0.0
        assert payload["combat"]["item_denial_receipts"] == []

    def test_a_charmed_carrier_withholds_the_shield_with_a_named_receipt(self):
        """Defect D-VI-1, pinned fail-closed rather than tolerated.

        Ahri charms Vi at 0.0, so the Q the Blast Shield rider was nailed to
        is published with ``skipped_reason='attacker_state_blocked'`` and
        the rider inherits ``trigger_event_skipped`` -- while Vi's E at
        3.221 and Q at 8.971 both land and author no shield at all.  A rider
        on a cast that never happened should move to the cast that did, and
        it cannot: ``damage._damage_event_row`` binds the payload to one
        carrier by ORDINAL, before the ordered survival walk decides what
        lands, and re-binding is a kernel change across the rider/trigger
        surface (three ledger implementations plus the compiled path).

        So the zero is not published as a fact.  It is published beside a
        named denial receipt that says the amount was withheld, which
        carrier failed and when a re-bind would have landed.  Both halves
        are asserted here: closing D-VI-1 must flip the absorbed figure AND
        drop the receipt, and this test is what will fail if only one of the
        two moves.

        Owner: survival/pipeline.  Writeup:
        ``docs/receipts/self-shield-carrier-rebind-2026-08-21.md``.
        """
        payload = _fight("Vi")
        survival = _main_survival(payload)
        (rider,) = [
            event
            for event in payload["combat"]["support_events"]
            if event["source"] == "Blast Shield"
        ]
        (denial,) = payload["combat"]["item_denial_receipts"]
        assert rider["amount"] == pytest.approx(0.12 * survival["max_health"], abs=0.05)
        assert rider["applied_amount"] == pytest.approx(0.0)
        assert rider["skipped_reason"] == "trigger_event_skipped"
        assert survival["shield_absorbed"] == pytest.approx(0.0)
        assert denial == {
            "time": pytest.approx(1.721),
            "kind": "item_denial",
            "source": "Blast Shield",
            "reason": "self_shield_carrier_skipped",
            "attacker": "main",
            "target": "main",
            "event_id": "main:enemy:Ahri:2:shield",
            "carrier_event_id": "main:enemy:Ahri:2",
            "carrier_skipped_reason": "attacker_state_blocked",
            # The earliest ability packet Vi landed at or after the skip:
            # E at 3.221.  The game grants Blast Shield on that hit.
            "rebind_time": pytest.approx(3.221),
            "withheld_amount": pytest.approx(292.8),
        }
        # The re-bind candidate the receipt names really did land.
        assert any(
            event["time"] == pytest.approx(denial["rebind_time"])
            and event["attacker"] == "main"
            and not event.get("skipped_reason")
            for event in payload["combat"]["events"]
        )

    def test_the_slot_declares_the_channel_that_pays_it(self):
        contract = get_champion_module_contract("Vi")
        assert contract.coverage["P"] == "modeled"
        assert contract.coverage_channels["P"] == ("self_shield_events",)


class TestTheTwoShieldOnlySlotChannels:
    """A shield with no damage of its own reaches the ledger two ways.

    A PASSIVE is never cast, so its shield rides a damaging cast through
    ``slotlib.attach_self_shield`` (Shen's Ki Barrier, Rakan's Fey
    Feathers).  A shield-only CAST is scanned from its own cached row by
    the ally-support scanner, self-targeted (Jarvan IV's Golden Aegis).
    Between them no shield-only slot is left unpriced, which is why there
    is no third zero-damage channel.
    """

    @pytest.mark.parametrize(
        ("champion", "source"),
        [
            ("Shen", "Ki Barrier"),
            ("Rakan", "Fey Feathers"),
            ("Jarvan IV", "Golden Aegis · Shield Strength"),
        ],
    )
    def test_the_slot_publishes_exactly_one_shield_per_activation(
        self, champion, source
    ):
        payload = _fight(champion, duration=6)
        shields = [
            event
            for event in payload["combat"]["support_events"]
            if event["target"] == "main" and event["source"] == source
        ]
        (shield,) = shields
        assert shield["amount"] > 0.0
        assert shield["duration"] > 0.0


class TestMordekaiserIndestructible:
    """W: the grey-health primitive already routes, so the map says so."""

    def test_the_recast_heal_reaches_the_fight(self):
        payload = _fight("Mordekaiser")
        survival = _main_survival(payload)
        heals = [
            event
            for event in payload["combat"]["healing_events"]
            if event["attacker"] == "main"
            and event["source"] == "Indestructible (grey health)"
        ]
        (heal,) = heals
        first_w = min(
            cast["time"] for cast in payload["cast_timeline"] if cast["slot"] == "W"
        )
        assert survival["grey_health_stored"] > 0.0
        assert heal["amount"] == pytest.approx(
            survival["grey_health_consumed"], abs=0.05
        )
        assert heal["time"] == pytest.approx(first_w + 0.5)

    def test_the_map_calls_w_modeled_without_a_channel(self):
        """W is in SLOTS, so the contract derives the label from the row."""
        contract = get_champion_module_contract("Mordekaiser")
        assert contract.coverage["W"] == "modeled"
        assert "W" not in contract.coverage_channels


class TestTahmKenchThickSkin:
    """E: the store always routes; the consume needs the wiki's four seconds."""

    def test_the_rank_row_stores_the_incoming_damage(self):
        survival = _main_survival(_fight("Tahm Kench"))
        assert survival["grey_health_stored"] > 0.0
        assert "Thick Skin" in survival["grey_health_source"]

    def test_the_out_of_combat_consume_pays_the_level_row(self):
        """A fight that leaves four quiet seconds pays 100% of the pool at 18."""
        payload = _fight(
            "Tahm Kench",
            duration=14,
            autos=False,
            enemy_ranks={"Q": 0, "W": 0, "E": 0, "R": 3},
        )
        survival = _main_survival(payload)
        taken = sum(
            event["damage"]
            for event in payload["combat"]["events"]
            if event.get("target") == "main"
        )
        last_hit = max(
            event["time"]
            for event in payload["combat"]["events"]
            if event.get("target") == "main"
        )
        heals = [
            event
            for event in payload["combat"]["healing_events"]
            if event["source"] == "Thick Skin (grey health)"
        ]
        (heal,) = heals
        # E rank 5 stores 47% of post-mitigation damage taken; at level 18
        # the consume restores 100% of the pool, four seconds after the
        # last hit.
        assert survival["grey_health_stored"] == pytest.approx(0.47 * taken, rel=1e-3)
        assert heal["amount"] == pytest.approx(survival["grey_health_stored"], rel=1e-3)
        assert heal["time"] == pytest.approx(last_hit + 4.0)

    def test_a_continuous_fight_never_opens_the_window(self):
        """Four seconds without damage is the wiki's condition, not a bug."""
        survival = _main_survival(_fight("Tahm Kench"))
        assert survival["grey_health_consumed"] == 0.0

    def test_the_active_is_off_by_default_and_grants_no_shield(self):
        """Pressing E is a player decision, so the default request presses none."""
        payload = _fight("Tahm Kench")
        assert _grey_shields(payload) == []
        assert _main_survival(payload)["shield_absorbed"] == pytest.approx(0.0)

    def test_the_option_converts_each_banked_pool_into_a_timed_shield(self):
        """Each press pays the grey banked since the last one, for 2.5s."""
        payload = _fight("Tahm Kench", options={"e_convert_grey_shield": True})
        shields = _grey_shields(payload)
        assert shields
        assert all(shield["duration"] == pytest.approx(2.5) for shield in shields)
        # E's cached cooldown is a flat 3s at every rank, and no ability
        # haste is carried, so the presses are exactly three apart.
        times = [shield["time"] for shield in shields]
        assert times == sorted(times)
        assert all(
            later - earlier == pytest.approx(3.0)
            for earlier, later in itertools.pairwise(times)
        )
        # The whole pool is consumed by the presses, and the shields absorb.
        survival = _main_survival(payload)
        assert sum(shield["amount"] for shield in shields) == pytest.approx(
            survival["grey_health_consumed"], rel=1e-3
        )
        assert survival["shield_absorbed"] > 0.0


class TestPykeGiftOfTheDrownedOnes:
    """P: the store routes, and the two halves that do not are named."""

    def test_the_store_is_capped_by_the_sourced_flat_cap(self):
        survival = _main_survival(_fight("Pyke"))
        assert survival["grey_health_stored"] == pytest.approx(80.0)

    def test_the_consume_is_a_vision_boundary_and_pays_nothing(self):
        survival = _main_survival(_fight("Pyke"))
        assert survival["grey_health_consumed"] == 0.0
        assert "vision boundary" in survival["grey_health_source"]

    def test_the_slot_is_never_called_modeled(self):
        """No channel pays it, so the map may not call it modeled.

        Main's session-5 relabel made both a sourced ``no_damage`` row
        (the pinned packet declares the zero); what this pins is that
        neither is ``modeled`` while nothing prices the heal.
        """
        contract = get_champion_module_contract("Pyke")
        assert contract.coverage["P"] != "modeled"
        assert contract.coverage["W"] != "modeled"


# ---------------------------------------------------------------------------
# The other rows on these champions
# ---------------------------------------------------------------------------


class TestTrundleFrozenDomain:
    """W: the cached attack-speed row now reaches the auto stream."""

    def test_the_slot_buffs_the_rank_rows_attack_speed(self):
        parsed = parse_champion_abilities(
            get_champion("Trundle"), 18, 0.0, ability_ranks=dict(_RANKS)
        )
        percent = extract_value(
            get_champion("Trundle")["abilities"]["W"][0], "Bonus Attack Speed", 5
        )
        assert percent == pytest.approx(90.0)
        assert parsed["W"]["stat_buff"] == {"bonus_attack_speed": percent}

    def test_the_buff_raises_the_fights_attack_speed(self):
        """base_AS + AS_ratio x bonus%, the repo's attack-speed formula."""
        from src.calculator.stats import calculate_total_stats

        champion = get_champion("Trundle")
        unbuffed = calculate_total_stats(champion, 18, [])
        ratio = champion["stats"]["attackSpeedRatio"]["flat"]
        expected = unbuffed["attack_speed"] + ratio * 0.90
        assert _fight("Trundle")["champion_stats"]["attack_speed"] == pytest.approx(
            expected, rel=1e-3
        )
