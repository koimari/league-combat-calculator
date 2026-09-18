"""Precision's minor runes: what each one compiles to, and what it costs.

Precision's rows split three ways and each half of the split is pinned here.
Row 1 pays on takedowns and kills: Triumph's heal and Absorb Life's are both
priced on the one the fight really scores, and Presence of Mind restores mana
there and on damaging casts into the mana walk's own ledger. Row 2 grows with a
game-long ``Legend`` counter, which becomes a declared option: Alacrity's
attack speed, Bloodline's life steal and bonus health, and Haste's *basic*
ability haste are all real grants read through the real pipeline, each into
the channel its own sentence names. Row 3's Coup de Grace is pinned in
``test_rune_paths.py`` beside the other exemplars.
"""

import pytest

from types import SimpleNamespace

from src.calculator import rune_effects
from src.calculator import rune_restore_events
from src.calculator.calculate import calculate_payload
from src.calculator.item_effects import DamageInputs
from src.calculator.rune_paths import precision

# The two probe requests, each chosen so the grant under test is the only
# thing that moves. Jinx's window is long enough that three percent of
# attack speed buys a whole extra auto; Ashe's rotation reads nothing but
# her stat block, so bonus health shows up there and nowhere else.
# Rev'd up is declared at its cap here rather than left to derive: unset it
# rides the swing ramp, which re-rates the stream the rune is measured on
# and would make two things move at once.
_ATTACK_SPEED_PROBE = {
    "champion_options": {"jinx_rev_up_stacks": 3},
    "champion": "Jinx",
    "level": 12,
    "items": ["Doran's Blade"],
    "fight_mode": "time_based",
    "fight_duration": 30.0,
    "auto_attack_uptime_mode": "calculated",
    "ability_ranks": {"Q": 4, "W": 3, "E": 3, "R": 2},
    "target_health": 10000.0,
    "target_armor": 100.0,
    "target_mr": 100.0,
}
_HEALTH_PROBE = {
    "champion": "Ashe",
    "level": 18,
    "items": [],
    "fight_mode": "one_rotation",
    "target_health": 2000.0,
    "target_armor": 100.0,
    "target_mr": 100.0,
}


class TestLegendAlacrity:
    """Row 2: bonus attack speed, a cached base plus a cached per-stack step."""

    def test_it_grants_the_base_and_the_step_the_cache_states(self):
        """3% flat, 1.5% per stack, 18% at the ten-stack maximum."""
        effect = rune_effects.resolve_rune("Legend: Alacrity")
        assert isinstance(effect, rune_effects.RuneStatGrantEffect)
        assert effect.stat is rune_effects.RuneStat.ATTACK_SPEED_PERCENT
        assert effect.amount(_context()) == pytest.approx(3.0)
        assert effect.amount(_context(stacks=1)) == pytest.approx(4.5)
        assert effect.amount(_context(stacks=10)) == pytest.approx(18.0)

    def test_the_default_is_no_stacks_and_the_disclosure_says_so(self):
        effect = rune_effects.resolve_rune("Legend: Alacrity")
        assert "18% at its 10-stack maximum" in effect.disclosures[0]
        assert "'legend_stacks' option, whose default is no stacks" in (
            effect.disclosures[0]
        )

    def test_its_option_is_a_count_bounded_by_the_cached_ceiling(self):
        option = precision.OPTIONS["Legend: Alacrity"][0]
        assert option.key == "legend_stacks"
        assert option.kind is rune_effects.RuneOptionKind.COUNT
        assert (option.default, option.bounds) == (0.0, (0.0, 10.0))
        with pytest.raises(ValueError, match="between 0 and 10"):
            option.validated(11)
        with pytest.raises(ValueError, match="whole number"):
            option.validated(2.5)


class TestLegendBloodline:
    """Row 2: two channels off one stack count, in one declaration."""

    def test_both_halves_read_the_same_stack_count(self):
        """0.45% life steal per stack; 85 bonus health only at fifteen."""
        effect = rune_effects.resolve_rune("Legend: Bloodline")
        assert isinstance(effect, rune_effects.RuneMultiStatGrantEffect)
        assert effect.stats == (
            rune_effects.RuneStat.LIFESTEAL_PERCENT,
            rune_effects.RuneStat.BONUS_HEALTH,
        )
        steal = rune_effects.RuneStat.LIFESTEAL_PERCENT
        health = rune_effects.RuneStat.BONUS_HEALTH
        assert effect.declared_amounts(_context()) == {steal: 0.0, health: 0.0}
        assert effect.declared_amounts(_context(stacks=14)) == {
            steal: pytest.approx(6.3),
            health: 0.0,
        }
        assert effect.declared_amounts(_context(stacks=15)) == {
            steal: pytest.approx(6.75),
            health: pytest.approx(85.0),
        }

    def test_the_life_steal_reaches_the_channel_the_heal_walk_reads(self):
        """6.75% at fifteen stacks, and the fight turns it into heal packets."""
        effect = rune_effects.resolve_rune("Legend: Bloodline")
        assert "0.45% life steal per Legend stack (6.75% at its 15-stack" in (
            effect.disclosures[0]
        )
        assert "life-steal walk turns into heal packets" in effect.disclosures[0]

    def test_a_channel_the_rune_did_not_declare_is_refused(self):
        """``stats`` is the declaration; ``amounts`` may not exceed it."""
        rogue = rune_effects.RuneMultiStatGrantEffect(
            rune_name="Legend: Bloodline",
            stats=(rune_effects.RuneStat.BONUS_HEALTH,),
            amounts=lambda context: {rune_effects.RuneStat.LETHALITY: 10.0},
        )
        with pytest.raises(KeyError, match="undeclared channels"):
            rogue.declared_amounts(_context())

    def test_its_option_ceiling_is_fifteen_not_ten(self):
        """Bloodline banks five more stacks than its row siblings."""
        option = precision.OPTIONS["Legend: Bloodline"][0]
        assert option.bounds == (0.0, 15.0)
        with pytest.raises(ValueError, match="between 0 and 15"):
            option.validated(16)


class TestLegendHaste:
    """Row 2: basic ability haste, in its own channel rather than the general one."""

    def test_it_grants_its_cached_step_per_stack_into_the_basic_channel(self):
        """1.5 per stack, 15 at the ten-stack maximum — Q/W/E only."""
        effect = rune_effects.resolve_rune("Legend: Haste")
        assert isinstance(effect, rune_effects.RuneStatGrantEffect)
        assert effect.stat is rune_effects.RuneStat.BASIC_ABILITY_HASTE
        assert effect.amount(_context()) == 0.0
        assert effect.amount(_context(stacks=1)) == pytest.approx(1.5)
        assert effect.amount(_context(stacks=10)) == pytest.approx(15.0)

    def test_the_channel_is_not_the_one_the_ultimate_reads(self):
        """The whole reason for a second haste channel, pinned."""
        assert (
            rune_effects.RuneStat.BASIC_ABILITY_HASTE
            is not rune_effects.RuneStat.ABILITY_HASTE
        )
        effect = rune_effects.resolve_rune("Legend: Haste")
        assert "15 at its 10-stack maximum" in effect.disclosures[0]
        assert "basic abilities' cooldowns and nothing else" in effect.disclosures[1]

    def test_it_declares_the_same_stack_option_its_row_siblings_do(self):
        option = precision.OPTIONS["Legend: Haste"][0]
        assert option.key == "legend_stacks"
        assert (option.default, option.bounds) == (0.0, (0.0, 10.0))

    def test_the_stacks_shorten_the_basic_cooldowns_and_buy_another_cast(self):
        """15 basic ability haste: Ahri's Q and W each land a fourth cast.

        The channel's whole point, priced through the real pipeline: the
        ultimate's cooldown is untouched (one cast either way) while Q and W
        each gain one, and the total moves by exactly those two casts.
        """
        request = {
            "champion": "Ahri",
            "level": 11,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 20.0,
        }
        bare = calculate_payload(dict(request))
        stacked = calculate_payload(
            {
                **request,
                "minor_runes": ["Legend: Haste"],
                "rune_options": {"Legend: Haste": {"legend_stacks": 10}},
            }
        )
        assert bare["champion_stats"]["basic_ability_haste"] == 0.0
        assert stacked["champion_stats"]["basic_ability_haste"] == pytest.approx(15.0)
        assert bare["champion_stats"]["ability_haste"] == (
            stacked["champion_stats"]["ability_haste"]
        )
        casts = lambda result: {  # noqa: E731 - a one-use inline mapping
            slot: result["breakdown"][slot]["casts"] for slot in ("Q", "W", "E", "R")
        }
        assert casts(bare) == {"Q": 3, "W": 3, "E": 2, "R": 1}
        assert casts(stacked) == {"Q": 4, "W": 4, "E": 2, "R": 1}
        assert bare["total_damage"] == pytest.approx(1091.0, abs=0.05)
        assert stacked["total_damage"] == pytest.approx(1365.5, abs=0.05)

    def test_without_stacks_it_grants_nothing_and_the_fight_is_unchanged(self):
        request = {
            "champion": "Ahri",
            "level": 11,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 20.0,
        }
        bare = calculate_payload(dict(request))
        unstacked = calculate_payload({**request, "minor_runes": ["Legend: Haste"]})
        assert unstacked["champion_stats"] == bare["champion_stats"]
        assert unstacked["total_damage"] == pytest.approx(bare["total_damage"])


class TestPresenceOfMindPricesItsRestores:
    """Row 1: mana restores on damage and on takedown, into the mana ledger.

    Both halves were a missing parse, not a missing capability: the cache
    carried only the takedown delay, and the pipeline always ran the mana
    walk with omission, so the old "rotation is not gated" receipt was stale
    about the ledger if true about damage. The damage half rides the walk's
    timeline and the takedown half lands post-hoc at the scored takedown.
    """

    def _fight(self, runes, target_health=10000.0, **overrides):
        request = {
            "champion": "Ahri",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 20.0,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "target_health": target_health,
            "target_armor": 100.0,
            "target_mr": 100.0,
            "keystone": "Arcane Comet",
            "minor_runes": runes,
            "stat_shards": [],
        }
        request.update(overrides)
        return calculate_payload(request, deterministic=True)

    def _presence_receipts(self, result):
        return [
            row
            for row in result["resource_ledger"]["receipts"]
            if row.get("source") == "Presence of Mind (rune)"
        ]

    def test_the_parser_reads_the_growth_pair_and_the_three_scalars(self):
        effects = rune_effects.RUNE_EFFECTS["Presence of Mind"]["effects"]
        assert effects["takedown_mana_ratio"] == pytest.approx(0.15)
        assert effects["takedown_energy_ratio"] == pytest.approx(0.15)
        assert effects["restore_cooldown_seconds"] == pytest.approx(8.0)
        assert effects["proc_delay_seconds"] == pytest.approx(1.0)
        melee, ranged = effects["melee_ranged_leveling"]
        assert (len(melee), len(ranged)) == (20, 20)
        assert (melee[0], melee[17]) == pytest.approx((6.0, 44.0))
        assert (ranged[0], ranged[17]) == pytest.approx((4.8, 35.2))
        assert "parse_warnings" not in rune_effects.RUNE_EFFECTS["Presence of Mind"]

    def test_the_scalar_rules_match_no_other_rune(self):
        """The takedown shares name their resource and the cooldown is the
        rune's own parenthetical; the growth pair is shared with Lethal Tempo
        and Fleet Footwork, which state explicit ranges instead."""
        from src.calculator.rune_parser import parse_rune_effects

        runes = rune_effects.RUNE_EFFECTS
        matched = {
            key: sorted(
                name
                for name, entry in runes.items()
                if isinstance(entry, dict)
                and entry.get("description")
                and key in parse_rune_effects(name, entry["description"])[0]
            )
            for key in (
                "takedown_mana_ratio",
                "takedown_energy_ratio",
                "restore_cooldown_seconds",
            )
        }
        assert matched == {
            "takedown_mana_ratio": ["Presence of Mind"],
            "takedown_energy_ratio": ["Presence of Mind"],
            "restore_cooldown_seconds": ["Presence of Mind"],
        }

    def test_a_ranged_column_that_is_not_eighty_percent_fails_loud(self):
        """The compiler's certification, and the proof it can fail."""
        effect = rune_effects.resolve_rune("Presence of Mind")
        assert isinstance(effect, rune_effects.RuneRestoreEffect)
        with pytest.raises(KeyError, match="not the melee one at 80%"):
            precision._certify_ranged_restore(
                "Presence of Mind", [6.0, 10.0], [4.8, 9.0]
            )

    def test_it_compiles_into_the_restore_kind_with_both_halves(self):
        effect = rune_effects.resolve_rune("Presence of Mind")
        assert isinstance(effect, rune_effects.RuneRestoreEffect)
        assert effect.takedown_mana_ratio == pytest.approx(0.15)
        assert effect.takedown_delay_seconds == pytest.approx(1.0)
        assert effect.restore_cooldown_seconds == pytest.approx(8.0)
        assert effect.restore_melee_by_level[17] == pytest.approx(44.0)
        assert effect.restore_ranged_by_level[17] == pytest.approx(35.2)

    def test_the_damage_half_rides_the_walk_and_moves_no_damage(self):
        """Three procs on their 8s cooldown, the first capped at the full
        pool it lands in — the walk's own cap, receipted, not hidden. The
        total holds still: no cast was omitted for mana, so no restore buys
        one. The remaining moves by the two kept restores plus the regen the
        new timeline pops re-account, which is the walk's arithmetic and not
        a second implementation of it."""
        bare = self._fight([])
        held = self._fight(["Presence of Mind"])
        assert held["total_damage"] == pytest.approx(bare["total_damage"])
        assert held["resource_remaining"] - bare["resource_remaining"] == pytest.approx(
            80.1, abs=0.2
        )
        receipts = self._presence_receipts(held)
        assert [row["amount"] for row in receipts] == pytest.approx([35.2, 35.2, 35.2])
        assert [row["reason"] for row in receipts] == [
            "CAPPED",
            "accepted",
            "accepted",
        ]
        assert receipts[0]["time"] == pytest.approx(0.0)
        assert receipts[1]["time"] - receipts[0]["time"] == pytest.approx(8.87, abs=0.1)

    def test_the_takedown_half_lands_post_hoc_at_the_scored_kill(self):
        """15% of the 843 maximum is 126.45, dated at the last damage
        instance plus the sourced second and capped against the closing pool
        the kill ended. Damage still holds: the restore lands after the last
        cast it could have enabled."""
        bare = self._fight([], target_health=400.0)
        held = self._fight(["Presence of Mind"], target_health=400.0)
        assert held.get("target_ending_health") == pytest.approx(0.0)
        assert held["total_damage"] == pytest.approx(bare["total_damage"])
        assert held["resource_remaining"] - bare["resource_remaining"] == pytest.approx(
            206.5, abs=0.2
        )
        receipts = self._presence_receipts(held)
        assert len(receipts) == 4
        takedown = receipts[-1]
        assert takedown["amount"] == pytest.approx(126.45)
        assert takedown["reason"] == "accepted"
        assert takedown["time"] == pytest.approx(19.85, abs=0.1)

    def test_a_minion_target_arms_neither_half(self):
        """The target dies and still nothing pays: a minion is not a
        champion takedown and arms no champion damage trigger."""
        bare = self._fight([], target_health=2000.0, target_class="minion")
        held = self._fight(
            ["Presence of Mind"], target_health=2000.0, target_class="minion"
        )
        assert held.get("target_ending_health") == pytest.approx(0.0)
        assert held["total_damage"] == pytest.approx(bare["total_damage"])
        assert self._presence_receipts(held) == []
        assert held["resource_remaining"] == pytest.approx(bare["resource_remaining"])

    def test_a_holder_with_no_mana_pool_walks_no_account(self):
        bare = self._fight([], champion="Garen")
        held = self._fight(["Presence of Mind"], champion="Garen")
        assert held["total_damage"] == pytest.approx(bare["total_damage"])
        assert held["resource_ledger"] == {}
        assert any("no mana pool" in note for note in held["notes"])

    def test_an_energy_holder_keeps_its_remaining_and_its_receipt(self):
        """Lee Sin spends energy through a walk with no receipt account, so
        both energy halves stay withheld and the rune moves nothing."""
        bare = self._fight([], champion="Lee Sin")
        held = self._fight(["Presence of Mind"], champion="Lee Sin")
        assert held["total_damage"] == pytest.approx(bare["total_damage"])
        assert held["resource_ledger"] == {}
        assert held["resource_remaining"] == pytest.approx(bare["resource_remaining"])
        assert any("energy halves" in note for note in held["notes"])

    def test_it_discloses_the_floor_and_the_withheld_energy(self):
        disclosures = " ".join(
            rune_effects.resolve_rune("Presence of Mind").disclosures
        )
        assert "enables an omitted cast is priced" in disclosures
        assert "a ceiling" in disclosures
        assert "energy halves" in disclosures


class TestTheTakedownHalfReadsBackOffTheResult:
    """The post-hoc half, unit-pinned: every gate decides, nothing is assumed.

    This import is also the module's front door (D-95): the integration
    tests above exercise it through the pipeline, and these pin the gates
    directly.
    """

    def _result(self, ending=0.0, closing=400.0, maximum=843.0):
        return {
            "target_ending_health": ending,
            "damage_events": [{"time": 5.0, "damage": 100.0}],
            "resource_ledger": {
                "contract": "resource_ledger_v1",
                "owner": "main",
                "kind": "mana",
                "opening_maximum": maximum,
                "opening_current": maximum,
                "closing_maximum": maximum,
                "closing_current": closing,
                "base_maximum": maximum,
                "bonus_maximum": 0.0,
                "receipts": [],
            },
            "resource_remaining": closing,
        }

    def _params(self, runes=("Presence of Mind",), target_class="champion"):
        return SimpleNamespace(
            rune_page=rune_effects.RunePage(minor_runes=runes),
            target_class=target_class,
        )

    def test_a_scored_takedown_pays_fifteen_percent_capped_at_max(self):
        result = self._result(ending=0.0, closing=400.0)
        rune_restore_events.apply_rune_restore_takedown(result, self._params())
        assert result["resource_remaining"] == pytest.approx(526.45)
        assert result["resource_ledger"]["closing_current"] == pytest.approx(526.45)
        (receipt,) = result["resource_ledger"]["receipts"]
        assert receipt["source"] == "Presence of Mind (rune)"
        assert receipt["amount"] == pytest.approx(126.45)
        assert receipt["time"] == pytest.approx(6.0)
        assert receipt["reason"] == "accepted"
        assert receipt["current_before"] == pytest.approx(400.0)
        assert receipt["current_after"] == pytest.approx(526.45)

    def test_a_full_pool_clips_with_a_capped_receipt(self):
        result = self._result(ending=0.0, closing=800.0)
        rune_restore_events.apply_rune_restore_takedown(result, self._params())
        assert result["resource_remaining"] == pytest.approx(843.0)
        (receipt,) = result["resource_ledger"]["receipts"]
        assert receipt["reason"] == "CAPPED"
        assert receipt["current_after"] == pytest.approx(843.0)

    def test_a_survived_target_a_minion_a_missing_ledger_and_no_rune_pay_nothing(
        self,
    ):
        survived = self._result(ending=500.0)
        rune_restore_events.apply_rune_restore_takedown(survived, self._params())
        assert survived["resource_ledger"]["receipts"] == []
        assert survived["resource_remaining"] == pytest.approx(400.0)
        minion = self._result()
        rune_restore_events.apply_rune_restore_takedown(
            minion, self._params(target_class="minion")
        )
        assert minion["resource_ledger"]["receipts"] == []
        ledgeless = self._result()
        del ledgeless["resource_ledger"]
        rune_restore_events.apply_rune_restore_takedown(ledgeless, self._params())
        assert "resource_ledger" not in ledgeless
        runeless = self._result()
        rune_restore_events.apply_rune_restore_takedown(
            runeless, self._params(runes=())
        )
        assert runeless["resource_ledger"]["receipts"] == []


class TestAbsorbLifePricesItsLevelTable:

    def test_absorb_life_pays_its_level_table_on_the_kill_the_fight_scores(self):
        """The wiki's piecewise rule parses, and the kill is the one Triumph uses.

        The wiki states the span as "1 - 27 (based on level)" and its own
        prose formula as "1, +0.25 per level until level 5, then +1 per
        level until level 10, then +2 per level"; the cached table is that
        rule evaluated, and the heal is read off it at the holder's level.
        """
        table = rune_effects.RUNE_EFFECTS["Absorb Life"]["effects"]["leveling"][0]
        assert len(table) == 20
        assert [table[0], table[4], table[9], table[17], table[19]] == [
            pytest.approx(1.0),
            pytest.approx(2.0),
            pytest.approx(7.0),
            pytest.approx(23.0),
            pytest.approx(27.0),
        ]
        effect = rune_effects.resolve_rune("Absorb Life")
        assert isinstance(effect, rune_effects.RuneHealEffect)
        assert effect.trigger is rune_effects.RuneHealTrigger.TAKEDOWNS
        assert effect.delay_seconds == 0.0
        assert effect.amount(_heal_inputs(health=2358.0, level=18)) == (
            pytest.approx(23.0)
        )

    def test_absorb_life_pays_a_fight_that_kills_and_not_one_that_does_not(self):
        def fight(*, runes=(), enemy_level=6, duration=10):
            return calculate_payload(
                {
                    "champion": "Garen",
                    "level": 18,
                    "role": "top",
                    "items": ["Infinity Edge"],
                    "boots": "",
                    "enemies": [
                        {
                            "kind": "champion",
                            "champion": "Darius",
                            "level": enemy_level,
                            "role": "top",
                        }
                    ],
                    "fight_duration": duration,
                    "fight_mode": "time_based",
                    "deterministic": True,
                    "include_auto_attacks": True,
                    "auto_attack_uptime": 1.0,
                    "keystone": "Press the Attack",
                    "minor_runes": list(runes),
                    "stat_shards": [],
                }
            )

        killed = fight(runes=["Absorb Life"])
        assert killed["target_ending_health"] == pytest.approx(0.0)
        assert killed["self_healing"] == pytest.approx(23.0)
        assert fight()["self_healing"] == pytest.approx(0.0)
        survived = fight(runes=["Absorb Life"], enemy_level=18, duration=2)
        assert survived["target_ending_health"] > 0.0
        assert survived["self_healing"] == pytest.approx(0.0)

    def test_absorb_life_discloses_the_kills_this_fight_does_not_hold(self):
        effect = rune_effects.resolve_rune("Absorb Life")
        assert "the heal is a floor" in effect.disclosures[1]
        assert "minions and monsters a lane kills" in effect.disclosures[1]

    def test_triumph_heals_a_share_of_maximum_health_after_its_delay(self):
        """2.5% of maximum health, one second after the takedown."""
        effect = rune_effects.resolve_rune("Triumph")
        assert isinstance(effect, rune_effects.RuneHealEffect)
        assert effect.trigger is rune_effects.RuneHealTrigger.TAKEDOWNS
        assert effect.delay_seconds == 1.0
        assert effect.amount(_heal_inputs(health=2358.0)) == pytest.approx(58.95)

    def test_triumph_s_two_unreachable_halves_are_named_with_their_numbers(self):
        effect = rune_effects.resolve_rune("Triumph")
        assert "5% of the holder's *missing* health) is withheld" in (
            effect.disclosures[1]
        )
        assert "20 gold is not damage" in effect.disclosures[1]

    def test_the_takedown_is_the_fight_s_own_or_it_does_not_happen(self):
        """A 300-health target dies and pays 59.0; a 10000-health one does not.

        No option and no invention: the takedown is the target ending at or
        below zero health, dated at the window's last damage instance plus
        the rune's own one-second delay.
        """
        request = {
            "champion": "Ahri",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 20.0,
            "target_armor": 100.0,
            "target_mr": 100.0,
            "minor_runes": ["Triumph"],
        }
        survived = calculate_payload({**request, "target_health": 10000.0})
        killed = calculate_payload({**request, "target_health": 300.0})
        assert survived["target_ending_health"] > 0.0
        assert not [
            event
            for event in survived["self_healing_events"]
            if event["kind"] == "rune_proc"
        ]
        assert killed["target_ending_health"] == 0.0
        packets = [
            event
            for event in killed["self_healing_events"]
            if event["kind"] == "rune_proc"
        ]
        assert [(packet["source"], packet["amount"]) for packet in packets] == [
            ("Triumph (rune)", pytest.approx(59.0, abs=0.05))
        ]
        assert killed["champion_stats"]["health"] == 2358


def _heal_inputs(*, health, level=18):
    """A heal input carrying only the stats these heals' formulas read."""
    return DamageInputs(
        champion_stats={"health": health},
        level=level,
        is_melee=False,
        target_max_health=1000.0,
        target_current_health=0.0,
    )


class TestTheGrantsReachTheRealPipeline:
    def test_alacrity_moves_attack_speed_and_the_autos_it_buys(self):
        """1.3428 -> 1.3615 at no stacks is +3%, and buys a 31st auto.

        Ten stacks is 1.4553 (+18%) and 33 autos. The damage moves with the
        auto count, so the rune is priced through the swing rate rather than
        through a row of its own.
        """
        bare = calculate_payload(dict(_ATTACK_SPEED_PROBE))
        unstacked = calculate_payload(
            {**_ATTACK_SPEED_PROBE, "minor_runes": ["Legend: Alacrity"]}
        )
        stacked = calculate_payload(
            {
                **_ATTACK_SPEED_PROBE,
                "minor_runes": ["Legend: Alacrity"],
                "rune_options": {"Legend: Alacrity": {"legend_stacks": 10}},
            }
        )
        speeds = [
            result["champion_stats"]["attack_speed"]
            for result in (bare, unstacked, stacked)
        ]
        assert speeds == [
            pytest.approx(1.3428, abs=5e-5),
            pytest.approx(1.3615, abs=5e-5),
            pytest.approx(1.4553, abs=5e-5),
        ]
        # Bonus attack speed enters as base_AS + AS_ratio x percent/100, so
        # the eighteen-percent delta is exactly six times the three-percent
        # one — the grant is a percent of the ratio, never of the total.
        assert speeds[2] - speeds[0] == pytest.approx(6 * (speeds[1] - speeds[0]))
        autos = [
            result["auto_attack_schedule"]["expected_autos_total"]
            for result in (bare, unstacked, stacked)
        ]
        assert autos == [30, 31, 33]
        # Re-captured with the landing-instant ruling (hp-scaled parts).
        assert bare["total_damage"] == pytest.approx(2187.0, abs=0.05)
        assert unstacked["total_damage"] == pytest.approx(2237.5, abs=0.05)
        assert stacked["total_damage"] == pytest.approx(2338.5, abs=0.05)

    def test_bloodline_moves_health_only_at_its_maximum(self):
        """2327 health, and 2412 once the fifteenth stack lands."""
        bare = calculate_payload(dict(_HEALTH_PROBE))
        request = {**_HEALTH_PROBE, "minor_runes": ["Legend: Bloodline"]}
        unstacked = calculate_payload(dict(request))
        short = calculate_payload(
            {**request, "rune_options": {"Legend: Bloodline": {"legend_stacks": 14}}}
        )
        full = calculate_payload(
            {**request, "rune_options": {"Legend: Bloodline": {"legend_stacks": 15}}}
        )
        assert bare["champion_stats"]["health"] == 2327
        assert unstacked["champion_stats"]["health"] == 2327
        assert short["champion_stats"]["health"] == 2327
        assert full["champion_stats"]["health"] == 2412

    def test_bloodline_s_life_steal_becomes_heal_packets_on_the_ledger(self):
        """6.75% at fifteen stacks: 43.9 self-healing becomes 146.2.

        The rune grants into the life-steal channel and the fight's own
        life-steal walk turns it into timed packets off Jinx's physical
        attack events — the same door an item's life steal goes through, so
        the rune needed no heal shape of its own.
        """
        request = {**_ATTACK_SPEED_PROBE, "minor_runes": ["Legend: Bloodline"]}
        bare = calculate_payload(dict(_ATTACK_SPEED_PROBE))
        unstacked = calculate_payload(dict(request))
        stacked = calculate_payload(
            {**request, "rune_options": {"Legend: Bloodline": {"legend_stacks": 15}}}
        )
        assert bare["champion_stats"]["lifesteal_percent"] == 0.0
        assert stacked["champion_stats"]["lifesteal_percent"] == pytest.approx(6.75)
        assert unstacked["self_healing"] == pytest.approx(bare["self_healing"])
        # Re-captured with the landing-instant ruling (hp-scaled parts).
        assert bare["self_healing"] == pytest.approx(43.5, abs=0.05)
        assert stacked["self_healing"] == pytest.approx(145.7, abs=0.05)
        assert len(bare["self_healing_events"]) == 35
        assert len(stacked["self_healing_events"]) == 65

    def test_a_formerly_withheld_rune_moves_only_resource_numbers(self):
        """Presence of Mind used to refuse with 'not gated by a resource'.
        The rotation was always admitted through the mana ledger; what it
        never did was omit a cast for mana. So the rune moves the ledger
        and the remaining pool, and damage holds still. Ashe's one rotation
        spends so little that every restore caps at the full pool it lands
        in — priced and receipted as CAPPED, moving no total either way."""
        bare = calculate_payload(dict(_HEALTH_PROBE))
        held = calculate_payload({**_HEALTH_PROBE, "minor_runes": ["Presence of Mind"]})
        assert held["total_damage"] == pytest.approx(bare["total_damage"])
        assert held["champion_stats"] == bare["champion_stats"]
        receipts = [
            row
            for row in held["resource_ledger"]["receipts"]
            if row.get("source") == "Presence of Mind (rune)"
        ]
        assert receipts and all(row["reason"] == "CAPPED" for row in receipts)
        assert not any(
            "Presence of Mind is not priced" in note for note in held["notes"]
        )


class TestThePathIsCovered:
    #: Unit A2 owns these two: both need the flat damage-amp kind it adds.
    _AWAITING_THE_FLAT_AMP = {"Cut Down", "Last Stand"}

    def test_every_precision_minor_rune_compiles(self):
        catalog = {
            entry["name"]: entry["implemented"]
            for entry in rune_effects.rune_catalog()
            if entry["path"] == "Precision" and entry["row"] > 0
        }
        assert len(catalog) == 9
        uncovered = {name for name, done in catalog.items() if not done}
        assert uncovered <= self._AWAITING_THE_FLAT_AMP
        assert set(precision.COMPILERS) == set(catalog) - uncovered

    def test_every_compiled_precision_rune_resolves_to_an_effect(self):
        for name in precision.COMPILERS:
            assert rune_effects.resolve_rune(name) is not None


def _context(*, stacks=None):
    """A stat context at level 18, optionally carrying a Legend stack count."""
    options = {}
    if stacks is not None:
        options = {
            name: {"legend_stacks": stacks}
            for name in ("Legend: Alacrity", "Legend: Bloodline", "Legend: Haste")
        }
    return rune_effects.RuneStatContext(
        level=18,
        is_melee=False,
        bonus_attack_damage=0.0,
        ability_power=0.0,
        options=options,
    )
