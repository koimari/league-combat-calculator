"""Tests for the Aphelios champion module."""

import re

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import aphelios, parse_champion_abilities
from src.calculator.champions.slotlib import effect_description
from src.calculator.stats import calculate_total_stats
from tests import cc_review

# The two prose-sourced weapon innates, read back out of the sentence each
# constant was reviewed from, so a patch that stops stating the number turns
# the constant red instead of leaving it asserted against its own restatement.
_CALIBRUM_MARK_RE = re.compile(
    r"dealing (?P<flat>\d+(?:\.\d+)?) \(\+ (?P<ratio>\d+(?:\.\d+)?)% bonus AD\) "
    r"bonus physical damage to the main target for each mark consumed"
)
_INFERNUM_BOLT_RE = re.compile(
    r"fire bolt deals (?P<ratio>\d+(?:\.\d+)?)% AD physical damage to the "
    r"primary target"
)

WEAPONS = ("calibrum", "severum", "gravitum", "infernum", "crescendum")
# The four weapon forms whose Q prices exactly one hit; Severum's Q is
# Onslaught, six attacks on a cached beat.
SINGLE_HIT_WEAPONS = ("calibrum", "gravitum", "infernum", "crescendum")
REVIEWED_WEAPONS = SINGLE_HIT_WEAPONS


def _parse(weapon, level=18, **options):
    data = cc_review.kit("Aphelios")
    return parse_champion_abilities(
        data,
        level,
        0.0,
        champion_stats=calculate_total_stats(data, level, []),
        champion_options={"aphelios_main_weapon": weapon, **options},
    )


def _p_effects(name):
    """The cached P entry with this name, as (entry, joined descriptions)."""
    for entry in cc_review.kit("Aphelios")["abilities"]["P"]:
        if entry.get("name") == name:
            effects = entry.get("effects") or []
            return entry, " ".join(str(e.get("description", "")) for e in effects)
    raise AssertionError(f"no cached Aphelios P entry named {name!r}")


def _fight(weapon, **options):
    """One deterministic timed fight on a crit-capable build."""
    return calculate_payload(
        {
            "champion": "Aphelios",
            "level": 18,
            "items": ["Infinity Edge", "Kraken Slayer"],
            "fight_mode": "timed",
            "fight_duration_seconds": 10.0,
            "include_auto_attacks": True,
            "champion_options": {"aphelios_main_weapon": weapon, **options},
        },
        deterministic=True,
    )


class TestReviewedCrowdControl:
    """Aphelios's crowd-control review is per weapon, not per slot.

    Q is whichever Moonstone weapon is equipped — Gravitum's Binding
    Eclipse roots where the others apply nothing — so ``MODULE_CC`` names
    the slot ``CC_PER_PART`` and the answer rides the parts each weapon
    form builds.
    """

    def test_the_weapon_slots_name_themselves_per_part(self):
        from src.calculator.champions.engine import CC_PER_PART

        assert aphelios.MODULE_CC == {
            "Q": CC_PER_PART,
            "E": "none",
            "R": CC_PER_PART,
        }
        assert aphelios.parse_abilities.cc_kinds == aphelios.MODULE_CC

    def test_only_gravitums_q_controls_what_it_damages(self):
        text = cc_review.slot_text(cc_review.kit("Aphelios"), "Q")
        assert (
            "aphelios expunges all enemies with gravitum's slow debuff, "
            "dealing 50 : 140 (based on level) (+ 32% : 50% (based on level) "
            "bonus ad) (+ 70% ap) magic damage and rooting them for 1 second" in text
        )
        assert aphelios._Q_CC_BY_WEAPON["gravitum"] == "root"
        for weapon in SINGLE_HIT_WEAPONS:
            (part,) = _parse(weapon)["Q"]["parts"]
            assert part.cc_kind == aphelios._Q_CC_BY_WEAPON[weapon]

    def test_onslaught_spreads_its_attacks_over_the_cached_duration(self):
        """Six attacks over 1.75 seconds, at the rate that implies.

        The count is what scales with attack speed, not the window, so the
        beat is ``duration / count`` and every attack lands inside the
        cached duration.
        """
        text = cc_review.slot_text(cc_review.kit("Aphelios"), "Q")
        assert (
            "aphelios enters an onslaught for 1.75 seconds, gaining 25% "
            "(+ 10% per 100 ap) bonus movement speed and automatically "
            "performing up to 6 (+ 2 per 100% bonus attack speed) attacks "
            "over the duration" in text
        )
        assert aphelios._Q_CC_BY_WEAPON["severum"] == "none"
        (part,) = _parse("severum")["Q"]["parts"]
        assert part.count == 6
        assert part.time_offset == 0.0
        assert part.hit_interval == pytest.approx(aphelios._Q_ONSLAUGHT_SECONDS / 6)
        assert part.cc_kind == "none"
        assert (part.count - 1) * part.hit_interval < aphelios._Q_ONSLAUGHT_SECONDS

    def test_severum_pays_one_heal_per_attack_that_dealt_damage(self):
        """ "Severum's attacks heal Aphelios for ... the post-mitigation
        damage dealt" — six attacks, six shares, same total as the one
        payment the unspread row used to make.
        """
        payload = calculate_payload(
            {
                "champion": "Aphelios",
                "level": 18,
                "items": ["Fimbulwinter"],
                "fight_mode": "timed",
                "include_auto_attacks": True,
                "champion_options": {"aphelios_main_weapon": "severum"},
            }
        )
        onslaught = [
            event for event in payload["damage_events"] if event.get("source") == "Q"
        ]
        assert len(onslaught) == 6
        heals = [
            event
            for event in payload["self_healing_events"]
            if event["source"] == "Severum"
        ]
        by_time = {round(float(event["time"]), 3) for event in heals}
        assert {round(float(event["time"]), 3) for event in onslaught} <= by_time
        assert all(event["amount"] > 0.0 for event in heals)

    def test_moonlight_vigils_blast_slows_only_under_gravitum(self):
        text = cc_review.slot_text(cc_review.kit("Aphelios"), "R")
        assert "gravitum: increases the initial slow to 99%" in text
        for weapon in WEAPONS:
            entry = _parse(weapon)["R"]
            assert entry["event_order_certified"] == "single_hit"
            (part,) = entry["parts"]
            assert part.cc_kind == ("slow" if weapon == "gravitum" else "none")

    def test_every_weapon_clears_the_control_armed_scan(self):
        assert cc_review.unreviewed_ability_slots("Aphelios") == []
        for weapon in WEAPONS:
            payload = calculate_payload(
                {
                    "champion": "Aphelios",
                    "level": 18,
                    "items": ["Fimbulwinter"],
                    "fight_mode": "timed",
                    "include_auto_attacks": True,
                    "champion_options": {"aphelios_main_weapon": weapon},
                }
            )
            coverage = payload["timeline_coverage"]
            assert coverage["complete"] is True, weapon
            assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]

    def test_severum_clears_the_control_armed_scan_too(self):
        payload = calculate_payload(
            {
                "champion": "Aphelios",
                "level": 18,
                "items": ["Fimbulwinter"],
                "fight_mode": "timed",
                "include_auto_attacks": True,
                "champion_options": {"aphelios_main_weapon": "severum"},
            }
        )
        coverage = payload["timeline_coverage"]
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_the_weapon_queue_slot_is_no_damage_not_a_missing_axis() -> None:
    """E emits a sourced zero, because it has nothing to price.

    The Weapon Queue System reorders the next weapons and has no gameplay
    effect of its own, so E is ``no_damage`` — the pinned packet's own
    zero-damage row — rather than an engine axis Aphelios is waiting on.
    """
    from src.calculator.champions import get_champion_module_contract

    contract = get_champion_module_contract("Aphelios")
    assert "E" in contract.slots
    assert contract.coverage["E"] == "no_damage"
    assert contract.coverage_channels == {}
    for weapon in WEAPONS:
        entry = _parse(weapon)["E"]
        assert entry["name"] == "Weapon Queue System", weapon
        assert entry["total_raw"] == 0.0, weapon
        assert entry["parts"] == (), weapon
        assert entry["detail"], weapon


class TestEWeaponQueueSystem:
    """The same zero row through the shared champion fixtures."""

    def test_e_present_zero_damage(self, aphelios_data, parse_at) -> None:
        _, abilities = parse_at(aphelios_data, 9)
        entry = abilities["E"]
        assert entry["name"] == "Weapon Queue System"
        assert entry["total_raw"] == 0.0
        assert entry["parts"] == ()
        assert entry["detail"]


class TestWeaponBranches:
    """P is five innates behind one slot, and each branch says what it prices.

    Two of them put damage on the basic-attack channel, one is priced as
    healing, one damages nothing, and one is blocked by the cache.
    """

    def test_every_weapon_names_its_branch_on_the_passive_row(self):
        for weapon in WEAPONS:
            entry = _parse(weapon)["passive"]
            assert aphelios._WEAPON_LABELS[weapon] in entry["detail"], weapon

    def test_calibrums_mark_constants_equal_the_cached_sentence(self):
        """Both numbers, read back out of the sentence they were reviewed from."""
        entry, _ = _p_effects("Calibrum")
        stated = _CALIBRUM_MARK_RE.search(effect_description(entry, 1))
        assert stated, "the cached Calibrum effect no longer states the mark bonus"
        assert float(stated["flat"]) == aphelios._CALIBRUM_MARK_FLAT
        assert float(stated["ratio"]) / 100.0 == aphelios._CALIBRUM_MARK_BONUS_AD_RATIO

    def test_calibrums_mark_bonus_prices_both_of_its_terms(self):
        assert _parse("calibrum").get("passive", {}).get("on_hit") is None
        on_hit = _parse("calibrum", aphelios_calibrum_marks=3)["passive"]["on_hit"]
        # No items and no points, so bonus AD is zero and a mark is the flat 15.
        assert on_hit["damage_per_hit"] == pytest.approx(45.0)
        assert on_hit["max_procs"] == 1
        # Weapon Master's six AD points are +24 bonus AD, which is what makes
        # the ratio move a published number: 15 + 0.15 x 24 = 18.6 a mark.
        scaled = _parse(
            "calibrum", aphelios_calibrum_marks=2, aphelios_bonus_ad_points=6
        )["passive"]["on_hit"]
        assert scaled["damage_per_hit"] == pytest.approx(37.2)

    def test_infernums_primary_target_bonus_is_the_cached_sentence(self):
        entry, _ = _p_effects("Infernum")
        stated = _INFERNUM_BOLT_RE.search(effect_description(entry, 0))
        assert stated, "the cached Infernum effect no longer states the bolt's AD"
        assert float(stated["ratio"]) / 100.0 == aphelios._INFERNUM_PRIMARY_AD_RATIO
        stats = calculate_total_stats(cc_review.kit("Aphelios"), 18, [])
        on_hit = _parse("infernum")["passive"]["on_hit"]
        assert on_hit["damage_per_hit"] == pytest.approx(0.10 * stats["attack_damage"])
        # The bolt IS the basic attack, so it crits when the attack does.
        assert on_hit["crit_effectiveness"] == 1.0

    def test_crescendums_chakram_bonus_has_no_cached_row_to_price(self):
        """The one branch the cache genuinely cannot support."""
        entry, text = _p_effects("Crescendum")
        assert (
            "0% : 138.5% (based on number of Chakrams) AD additional physical "
            "damage" in text
        )
        assert all(effect.get("leveling") == [] for effect in entry["effects"])
        assert _parse("crescendum")["passive"].get("on_hit") is None
        assert "UNPRICED" in _parse("crescendum")["passive"]["detail"]

    def test_severum_and_gravitum_branches_price_no_damage(self):
        _, severum = _p_effects("Severum")
        assert "Severum's attacks heal Aphelios" in severum
        _, gravitum = _p_effects("Gravitum")
        assert "Basic attacks with Gravitum slow enemies by 30%" in gravitum
        for weapon in ("severum", "gravitum"):
            assert _parse(weapon)["passive"].get("on_hit") is None, weapon

    def test_weapon_master_grants_are_read_from_the_cached_rows(self):
        """The AD/AS/lethality rows are cached and indexed by points spent."""
        ability, _ = _p_effects("The Hitman and the Seer")
        rows = {
            leveling["attribute"]: leveling["modifiers"][0]["values"]
            for effect in ability["effects"]
            for leveling in effect.get("leveling", [])
        }
        assert rows["Bonus Attack Damage"] == [4, 8, 12, 16, 20, 24]
        assert rows["Bonus Attack Speed"] == [9, 18, 27, 36, 45, 54]
        assert rows["Lethality"] == [4.5, 9, 13.5, 18, 22.5, 27]
        entry = _parse(
            "calibrum", aphelios_bonus_ad_points=6, aphelios_bonus_as_points=4
        )["passive"]
        assert entry["stat_buff"] == {
            "bonus_attack_damage": 24.0,
            "bonus_attack_speed": 36.0,
        }
        # Spending nothing grants nothing — a rank-zero read would index the
        # row's LAST value, which is the whole six-point grant.
        assert _parse("calibrum")["passive"]["stat_buff"] == {
            "bonus_attack_damage": 0.0,
            "bonus_attack_speed": 0.0,
        }

    def test_the_mark_bonus_lands_once_and_scales_with_the_marks(self):
        """One empowered attack spends every mark: one proc, N marks' worth."""
        totals = {}
        for marks in (0, 1, 3, 5):
            row = _fight("calibrum", aphelios_calibrum_marks=marks)["breakdown"].get(
                "on_hit_ability_passive"
            )
            if marks == 0:
                assert row is None
                continue
            assert row["name"] == "Calibrum mark (on-hit)"
            assert row["count"] == 1
            totals[marks] = row["total_damage"]
        assert totals[3] == pytest.approx(3 * totals[1])
        assert totals[5] == pytest.approx(5 * totals[1])

    def test_infernum_prices_its_extra_ten_percent_on_every_swing(self):
        fight = _fight("infernum")
        row = fight["breakdown"]["on_hit_ability_passive"]
        assert row["name"] == "Infernum (on-hit)"
        assert row["count"] == fight["breakdown"]["auto_attacks"]["count"]
        assert row["total_damage"] > 0.0
        assert "on_hit_ability_passive" not in _fight("calibrum")["breakdown"]


class TestPhaseKeepsItsTwoNumbersApart:
    """SC4: the swap duration is not a cooldown, and never was one."""

    def test_the_row_carries_the_cached_cooldown(self):
        cached = cc_review.kit("Aphelios")["abilities"]["W"][0]
        assert cached["cooldown"]["modifiers"][0]["values"][0] == 0.8
        for weapon in WEAPONS:
            assert _parse(weapon)["W"]["cooldown"] == pytest.approx(0.8), weapon

    def test_the_swap_duration_is_stated_from_the_cache(self):
        cached = cc_review.kit("Aphelios")["abilities"]["W"][0]
        assert (
            "switches between his main weapon and off-hand weapon over 0.25 "
            "seconds" in cached["effects"][0]["description"]
        )
        assert "over 0.25 s" in _parse("calibrum")["W"]["detail"]

    def test_the_row_still_damages_nothing(self):
        entry = _parse("calibrum")["W"]
        assert entry["total_raw"] == 0.0
        assert _fight("calibrum")["breakdown"]["W"]["total_damage"] == 0.0


class TestDuskwaveAppliesTheOnHits:
    """SC4: Duskwave is Infernum's Q, not Calibrum's."""

    def test_the_cached_volley_sentence_belongs_to_duskwave(self):
        text = cc_review.slot_text(cc_review.kit("Aphelios"), "Q")
        assert (
            "aphelios then fires a volley of attacks at each locked-on target "
            "from his current off-hand weapon, dealing 100% ad physical damage "
            "and applying on-hit effects" in text
        )

    def test_only_infernums_q_carries_the_on_hit_application(self):
        assert _parse("infernum")["Q"]["applies_item_on_hits"] == {
            "effectiveness": 1.0,
            "hits": 1,
            "triggers": ("on_hit",),
        }
        for weapon in ("calibrum", "gravitum", "crescendum"):
            assert "applies_item_on_hits" not in _parse(weapon)["Q"], weapon

    def test_the_on_hit_matrix_receipt_agrees(self):
        import json
        from pathlib import Path

        matrix = json.loads(Path("data/onhit-matrix.json").read_text(encoding="utf-8"))
        duskwave = [
            row for row in matrix["champions"]["Aphelios"] if row["name"] == "Duskwave"
        ]
        assert duskwave
        assert duskwave[0]["effectiveness"] == 1.0


class TestModuleCoverage:
    """P/Q/W/R are exercised through the thematic suites
    (test_e1_healing_b1.py, test_issue_137.py, test_p1_review_2.py,
    test_spellblade_on_hit_matrix.py, test_survival_kernel.py); what this
    pins is that no slot is left out_of_scope."""

    def test_all_five_slots_covered(self) -> None:
        assert aphelios.MODULE_COVERAGE == {
            "P": "modeled",
            "Q": "modeled",
            "W": "modeled",
            "E": "no_damage",
            "R": "modeled",
        }
