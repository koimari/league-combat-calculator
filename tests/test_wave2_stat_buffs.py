"""Slice 4 of the utility-axis census: the stat grants the engine dispatches.

Nineteen slots across seventeen champions emitted a zero-damage row whose
cached leveling the fight engine could already fold in — ``stat_buff``'s
dispatch (``damage.py`` bonus_attack_speed / bonus_attack_damage /
bonus_health, plus the generic per-key add) and ``engine.py``'s
``target_debuff``.  Two claims per slot:

* the row grants exactly what the cache says (read at the same rank and
  stats through ``tests.row_review``, so the number traces to
  ``data/champions.json`` and not to this file); and
* the grant reaches the fight — a real ``run_fight`` through
  ``pipeline`` whose auto count, attack damage, maximum health or
  effective armour moves with it.

The withheld side of each fight probe is the same fight with the slot's
own option turned down, where the slot has one; where it does not, the
comparison is against the stat the build alone supplies.
"""

import math

import pytest

from src.calculator.champions.slotlib import (
    extract_named,
    extract_value,
    find_named_leveling,
    sum_modifiers,
)
from src.calculator.data_fetcher import fetch_champion_data
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.scenario import load_public_champion
from src.calculator.stats import calculate_total_stats
from tests import row_review

_LEVEL = 18
_WINDOW = 5.0
_TARGET_HEALTH = 2000.0
_TARGET_ARMOR = 100.0
_TARGET_MR = 100.0

_CHAMPIONS = {data.get("name"): data for data in fetch_champion_data().values()}


def _fight(champion, **options):
    """One 5-second sustained fight at level 18 with no items."""
    params = FightParams(
        target_health=_TARGET_HEALTH,
        target_bonus_health=0.0,
        target_armor=_TARGET_ARMOR,
        target_magic_resistance=_TARGET_MR,
        fight_duration_seconds=_WINDOW,
        auto_attack_uptime=1.0,
        one_rotation=False,
        include_actives=True,
        cast_order=None,
        auto_attacks_only=False,
        ability_ranks=None,
        champion_options=options or None,
        deterministic=True,
    )
    return run_fight(_CHAMPIONS[champion], _LEVEL, [], params)


def _fight_casting(champion, cast_order):
    """The same fight with an explicit rotation — a slot left out is never cast."""
    params = FightParams(
        target_health=_TARGET_HEALTH,
        target_bonus_health=0.0,
        target_armor=_TARGET_ARMOR,
        target_magic_resistance=_TARGET_MR,
        fight_duration_seconds=_WINDOW,
        auto_attack_uptime=1.0,
        one_rotation=False,
        include_actives=True,
        cast_order=list(cast_order),
        auto_attacks_only=False,
        ability_ranks=None,
        champion_options=None,
        deterministic=True,
    )
    return run_fight(_CHAMPIONS[champion], _LEVEL, [], params)


def _autos(result):
    return (result.get("auto_attack_schedule") or {}).get("expected_autos_total")


def _build_stats(champion):
    """The stats the build alone supplies, before any ability buff."""
    return calculate_total_stats(_CHAMPIONS[champion], _LEVEL, [])


def _row(champion, slot, attribute):
    """One cached leveling row, resolved raw (percentages stay percentages)."""
    ability = load_public_champion(champion)["abilities"][slot][0]
    return extract_value(ability, attribute, row_review.RANKS[slot])


def _slot_entry(champion, slot, **options):
    return row_review.entry(champion, "passive" if slot == "P" else slot, **options)


# ---------------------------------------------------------------------------
# The attack-speed grants: the row, then the auto count it buys
# ---------------------------------------------------------------------------

# (champion, slot, cached attribute, the number that row holds at the
# reviewed rank).  The literal is the assertion's quoted evidence; the
# comparison itself is against the cache.
_ATTACK_SPEED_ROWS = [
    ("Tristana", "Q", "Bonus Attack Speed", 120.0),
    ("Quinn", "W", "Bonus Attack Speed", 80.0),
    ("Master Yi", "R", "Bonus Attack Speed", 65.0),
    ("Nocturne", "W", "Bonus Attack Speed", 50.0),
    ("Twitch", "Q", "Bonus Attack Speed", 60.0),
    ("Viego", "E", "Bonus Attack Speed", 50.0),
    ("Olaf", "W", "Bonus Attack Speed", 80.0),
    ("Lulu", "W", "Bonus Attack Speed", 30.0),
]

# Rows whose grant is an asserted STATE rather than the slot's own cast.
# Every other row here fires when the ability is cast, so the default
# parse already holds it.  Twitch's Ambush is the exception and the
# reason this table exists: casting Q is what ENTERS the camouflage, and
# the attack speed arrives only when he BREAKS it, so a Twitch who cast Q
# at t=0 is not attacking at t=0.  ``q_ambush_break`` is the user saying
# he walked in already stealthed — the same shape as ``poison_stacks``
# asserting stacks already on the target — and it defaults off so the
# unasserted fight does not bill a phantom proc.  Arming it here keeps
# both claims of this slice intact for the slot without pretending the
# default grants it; ``test_twitch_ambush_grants_its_row_only_once_the_``
# ``stealth_breaks`` below is what pins the default itself.
_ARMED_BY = {("Twitch", "Q"): {"q_ambush_break": True}}


def _buff_window_start(champion, slot, result, **options):
    """When the granted rate begins — 0.0 unless the row is WINDOWED.

    A plain ``stat_buff`` is one scalar for the whole fight, so it starts
    at 0.0.  A row that also carries ``auto_attack_override`` is windowed,
    and ``damage.py`` resolves that window's start by walking
    ``cast_order`` to the ``"Q"`` slot — the Q-slot-only kernel — so the
    start is the Q cast's own time, read here from the fight's published
    ``cast_timeline`` rather than restated.
    """
    entry = _slot_entry(champion, slot, **options)
    override = entry.get("auto_attack_override") or {}
    if "active_duration" not in override:
        return 0.0
    start = next(
        cast["time"] for cast in result["cast_timeline"] if cast["slot"] == "Q"
    )
    # The identity below has no post-window term, so the window must
    # still be open when the fight ends.  Every windowed row here
    # satisfies that; one that stopped would fail here, not silently.
    assert start + override["active_duration"] >= _WINDOW
    return start


@pytest.mark.parametrize(
    ("champion", "slot", "attribute", "quoted"), _ATTACK_SPEED_ROWS
)
def test_the_attack_speed_row_is_what_the_slot_grants(
    champion, slot, attribute, quoted
):
    """A direct parse has no fight window, so the whole row lands."""
    cached = _row(champion, slot, attribute)
    assert cached == pytest.approx(quoted)
    entry = _slot_entry(champion, slot, **_ARMED_BY.get((champion, slot), {}))
    assert entry["total_raw"] == 0.0
    assert entry["stat_buff"]["bonus_attack_speed"] == pytest.approx(cached)


@pytest.mark.parametrize(
    ("champion", "slot", "attribute", "quoted"), _ATTACK_SPEED_ROWS
)
def test_the_attack_speed_grant_reaches_the_fights_auto_count(
    champion, slot, attribute, quoted
):
    """base_AS + AS_ratio x bonus/100, then the autos the rate buys.

    The count splits at the moment the buff STARTS: autos before it ride
    the base rate, autos inside it the buffed one, and the floor applies
    per phase.  For an unwindowed grant, and for a windowed one whose
    window opens at t=0, the pre-window phase is empty and the whole
    thing collapses to ``floor(fought x window)`` — which is every row
    here but Twitch, whose Ambush is cast third and so opens its window
    at 0.25s.  Crediting those 0.25 seconds at the buffed rate is exactly
    the one auto of over-count this term removes.
    """
    del attribute, quoted
    options = _ARMED_BY.get((champion, slot), {})
    build = _build_stats(champion)
    result = _fight(champion, **options)
    fought = result["champion_stats"]["attack_speed"]
    assert fought > build["attack_speed"]
    granted = (fought - build["attack_speed"]) / build["attack_speed_ratio"] * 100.0
    assert granted > 0.0

    start = _buff_window_start(champion, slot, result, **options)
    assert _autos(result) == math.floor(build["attack_speed"] * start) + math.floor(
        fought * (_WINDOW - start)
    )
    assert _autos(result) > math.floor(build["attack_speed"] * _WINDOW)


def test_tristana_rapid_fire_doubles_the_auto_count_it_was_missing():
    """The assumption this slice deleted, priced: 4 autos become 8."""
    build = _build_stats("Tristana")
    result = _fight("Tristana")
    assert math.floor(build["attack_speed"] * _WINDOW) == 4
    assert _autos(result) == 8
    assert result["champion_stats"]["attack_speed"] == pytest.approx(1.6658, abs=5e-4)
    assert result["auto_attack_damage"] == pytest.approx(472.0, abs=0.05)
    assert result["total_damage"] == pytest.approx(899.5, abs=0.05)


def test_nocturne_doubles_its_row_only_when_the_spell_shield_blocks():
    """The passive half always; the enhanced row is opt-in and windowed."""
    passive = _row("Nocturne", "W", "Bonus Attack Speed")
    enhanced = _row("Nocturne", "W", "Enhanced Bonus Attack Speed")
    assert (passive, enhanced) == (50.0, 100.0)
    held = _slot_entry("Nocturne", "W")["stat_buff"]["bonus_attack_speed"]
    blocked = _slot_entry("Nocturne", "W", w_spellshield_block=True)["stat_buff"][
        "bonus_attack_speed"
    ]
    assert held == pytest.approx(passive)
    assert blocked == pytest.approx(enhanced)
    # In a 5-second fight the 5-second enhanced window is fully covered,
    # so the fight sees the doubled row too.
    armed = _fight("Nocturne", w_spellshield_block=True)
    plain = _fight("Nocturne")
    assert _autos(armed) > _autos(plain)


def test_twitch_ambush_grants_its_row_only_once_the_stealth_breaks():
    """The withheld side is the DEFAULT here, and it publishes no key.

    The slot was re-reviewed with the option renamed ``q_ambush_break``
    and defaulted OFF: casting Ambush enters the camouflage rather than
    leaving it, so the unasserted fight must not hold the steroid at all.
    The held side therefore asserts the absence of ``stat_buff`` — a
    stronger statement than the zero it used to read, which a slot that
    silently stopped computing its grant could also have produced.
    """
    held = _slot_entry("Twitch", "Q")
    armed = _slot_entry("Twitch", "Q", q_ambush_break=True)

    assert "stat_buff" not in held
    assert "auto_attack_override" not in held
    assert held["total_raw"] == 0.0
    assert armed["stat_buff"]["bonus_attack_speed"] == pytest.approx(
        _row("Twitch", "Q", "Bonus Attack Speed")
    )


def test_viego_mist_uptime_scales_the_row_it_grants():
    full = _slot_entry("Viego", "E")["stat_buff"]["bonus_attack_speed"]
    half = _slot_entry("Viego", "E", e_mist_uptime=50)["stat_buff"][
        "bonus_attack_speed"
    ]
    assert full == pytest.approx(50.0)
    assert half == pytest.approx(25.0)


def test_lulu_prices_the_self_cast_and_defers_the_ally_one():
    """W's attack speed and R's health are the *self* branch only."""
    self_as = _slot_entry("Lulu", "W")["stat_buff"]["bonus_attack_speed"]
    ally_as = _slot_entry("Lulu", "W", lulu_whimsy_target="ally")["stat_buff"][
        "bonus_attack_speed"
    ]
    enemy_as = _slot_entry("Lulu", "W", lulu_whimsy_target="enemy")["stat_buff"][
        "bonus_attack_speed"
    ]
    assert self_as == pytest.approx(30.0)
    assert (ally_as, enemy_as) == (0.0, 0.0)
    assert (
        "ally-support scanner"
        in _slot_entry("Lulu", "W", lulu_whimsy_target="ally")["detail"]
    )

    health = _slot_entry("Lulu", "R")["stat_buff"]["bonus_health"]
    ally_health = _slot_entry("Lulu", "R", lulu_wild_growth_target="ally")["stat_buff"][
        "bonus_health"
    ]
    # 575 at rank 3 + 55% of the 200 AP row_review supplies.
    assert health == pytest.approx(575.0 + 0.55 * row_review.STATS["ability_power"])
    assert ally_health == 0.0


def test_lulu_wild_growth_raises_the_fights_maximum_health():
    build = _build_stats("Lulu")
    result = _fight("Lulu")
    granted = extract_named(
        load_public_champion("Lulu")["abilities"]["R"][0],
        "Bonus Health",
        3,
        dict(result["champion_stats"]),
        {},
    )
    assert granted > 0.0
    assert result["champion_stats"]["health"] == pytest.approx(
        build["health"] + granted
    )


# ---------------------------------------------------------------------------
# The attack-damage, ability-power and health grants
# ---------------------------------------------------------------------------


def test_olaf_berserker_rage_scales_with_the_declared_missing_health():
    """0% : 100% (based on missing health) of the per-level row.

    The row runs 50% : 107.84% across the twenty levels this season
    allows; level 18 is 100%, and the second row beside it (life steal)
    has no stat_buff key.
    """
    ability = load_public_champion("Olaf")["abilities"]["P"][0]
    at_full_rage = sum_modifiers(
        find_named_leveling(ability, "Per-Level Scaling", occurrence=0),
        _LEVEL,
        level=_LEVEL,
    )
    assert at_full_rage == pytest.approx(100.0)
    default = _slot_entry("Olaf", "P")["stat_buff"]["bonus_attack_speed"]
    assert default == pytest.approx(0.30 * at_full_rage)
    assert _slot_entry("Olaf", "P", olaf_missing_health_percent=0)["stat_buff"][
        "bonus_attack_speed"
    ] == pytest.approx(0.0)
    assert _slot_entry("Olaf", "P", olaf_missing_health_percent=100)["stat_buff"][
        "bonus_attack_speed"
    ] == pytest.approx(at_full_rage)


def test_olaf_ragnarok_grants_attack_damage_and_resistances():
    """10/20/30 + 25% AD, and 10/15/20 armour and magic resistance."""
    entry = _slot_entry("Olaf", "R")
    ad_row = extract_named(
        load_public_champion("Olaf")["abilities"]["R"][0],
        "Bonus Attack Damage",
        3,
        dict(row_review.STATS),
        {},
    )
    resists = _row("Olaf", "R", "Bonus Resistances")
    assert ad_row == pytest.approx(30.0 + 0.25 * row_review.STATS["attack_damage"])
    assert resists == pytest.approx(20.0)
    assert entry["stat_buff"] == {
        "bonus_attack_damage": pytest.approx(ad_row),
        "armor": pytest.approx(resists),
        "magic_resistance": pytest.approx(resists),
    }


def test_olafs_three_steroids_reach_one_fight():
    build = _build_stats("Olaf")
    result = _fight("Olaf")
    stats = result["champion_stats"]
    assert _autos(result) == 9 > math.floor(build["attack_speed"] * _WINDOW) == 5
    # R's 3-second window covers 3 of the 5 seconds: 0.6 x (30 + 25% AD).
    assert stats["attack_damage"] > build["attack_damage"]
    assert result["total_damage"] == pytest.approx(1346.1, abs=0.05)


def test_singed_insanity_potion_amplifies_his_own_poison():
    """One Bonus Stats row becomes AP, both resistances and movement speed.

    Four stats, not three: the cached description names the row's grants as
    "ability power, bonus armor, bonus magic resistance, bonus movement
    speed", and ``champions/singed.py`` grants the same flat number to all
    four.  Only the row's health/mana regeneration is left without a
    ``stat_buff`` key, because nothing in a fixed-window fight reads it.
    """
    bonus = _row("Singed", "R", "Bonus Stats")
    assert bonus == pytest.approx(85.0)
    entry = _slot_entry("Singed", "R")
    assert entry["stat_buff"] == {
        "ability_power": pytest.approx(bonus),
        "armor": pytest.approx(bonus),
        "magic_resistance": pytest.approx(bonus),
        "move_speed": pytest.approx(bonus),
    }
    build = _build_stats("Singed")
    result = _fight("Singed")
    assert result["champion_stats"]["ability_power"] == pytest.approx(
        build["ability_power"] + bonus
    )
    # Q's poison tick and E's fling both carry AP ratios and parse after R.
    assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(72.09, abs=0.05)
    assert result["breakdown"]["E"]["total_damage"] == pytest.approx(148.38, abs=0.05)


def test_naafiri_hunt_grants_twenty_percent_of_attack_damage():
    entry = _slot_entry("Naafiri", "W")
    expected = 0.20 * row_review.STATS["attack_damage"]
    assert entry["stat_buff"] == {"bonus_attack_damage": pytest.approx(expected)}
    build = _build_stats("Naafiri")
    result = _fight("Naafiri")
    assert result["champion_stats"]["attack_damage"] == pytest.approx(
        build["attack_damage"] * 1.20
    )


def test_rammus_spiked_shell_sums_both_resistances():
    """percent_of mode reads one stat; this row is 15% of each."""
    entry = _slot_entry("Rammus", "P")
    expected = 0.15 * row_review.STATS["armor"] + 0.15 * (
        row_review.STATS["magic_resistance"]
    )
    assert entry["stat_buff"] == {"bonus_attack_damage": pytest.approx(expected)}
    build = _build_stats("Rammus")
    result = _fight("Rammus")
    assert result["champion_stats"]["attack_damage"] == pytest.approx(
        build["attack_damage"]
        + 0.15 * build["armor"]
        + 0.15 * build["magic_resistance"]
    )


def test_nunu_call_of_the_freljord_grants_its_prose_attack_speed():
    from src.calculator.champions import nunu_willump

    entry = _slot_entry("Nunu & Willump", "P")
    assert entry["stat_buff"] == {
        "bonus_attack_speed": pytest.approx(nunu_willump._P_BONUS_ATTACK_SPEED)
    }
    build = _build_stats("Nunu & Willump")
    result = _fight("Nunu & Willump")
    assert result["champion_stats"]["attack_speed"] == pytest.approx(
        build["attack_speed"]
        + build["attack_speed_ratio"] * nunu_willump._P_BONUS_ATTACK_SPEED / 100.0
    )


def test_renata_bailout_prices_the_mean_of_its_own_ramp():
    """0% : 100% effectiveness over 5s averages the two cached rows."""
    ability = load_public_champion("Renata Glasc")["abilities"]["W"][0]
    start = extract_named(ability, "Bonus Attack Speed", 5, dict(row_review.STATS), {})
    end = extract_named(
        ability, "Maximum Bonus Attack Speed", 5, dict(row_review.STATS), {}
    )
    # 30% + 1% per 100 AP, ramping to 60% + 2% per 100 AP at 200 AP.
    assert (start, end) == (pytest.approx(32.0), pytest.approx(64.0))
    entry = _slot_entry("Renata Glasc", "W")
    assert entry["stat_buff"]["bonus_attack_speed"] == pytest.approx((start + end) / 2)
    ally = _slot_entry("Renata Glasc", "W", w_bailout_target="ally")
    assert ally["stat_buff"]["bonus_attack_speed"] == 0.0


def test_varus_living_vengeance_is_off_until_a_takedown_arms_it():
    """Default off, so the default request's numbers do not move."""
    held = _slot_entry("Varus", "P")["stat_buff"]
    assert held == {
        "bonus_attack_speed": 0.0,
        "bonus_attack_damage": 0.0,
        "ability_power": 0.0,
    }
    armed = _slot_entry("Varus", "P", p_champion_takedown=True)["stat_buff"]
    assert armed["bonus_attack_speed"] == pytest.approx(30.0)
    # 33% of the resulting TOTAL bonus attack speed, as both AD and AP.
    assert armed["bonus_attack_damage"] == pytest.approx(0.33 * 30.0)
    assert armed["ability_power"] == pytest.approx(0.33 * 30.0)
    assert _fight("Varus")["total_damage"] == pytest.approx(1092.5, abs=0.05)
    assert _fight("Varus", p_champion_takedown=True)["total_damage"] == pytest.approx(
        1341.4, abs=0.05
    )


# ---------------------------------------------------------------------------
# The one debuff: Rengar's flat armour shred
# ---------------------------------------------------------------------------


def test_rengar_thrill_of_the_hunt_shreds_flat_armour():
    """15/20/25 for 4s, weighted by the share of the fight it covers."""
    shred = _row("Rengar", "R", "Armor Reduction")
    assert shred == pytest.approx(25.0)
    entry = _slot_entry("Rengar", "R")
    assert entry["total_raw"] == 0.0
    assert entry["target_debuff"] == {
        "armor_reduction_flat": pytest.approx(shred),
        "duration": pytest.approx(4.0),
    }
    assert "target_debuff" not in _slot_entry("Rengar", "R", r_thrill_attack=False)

    armed = _fight("Rengar")
    withheld = _fight("Rengar", r_thrill_attack=False)
    # 4 seconds of a 5-second fight is 0.8 of the 25.
    assert withheld["effective_armor"] == pytest.approx(_TARGET_ARMOR)
    assert armed["effective_armor"] == pytest.approx(_TARGET_ARMOR - 0.8 * shred)
    assert armed["total_damage"] > withheld["total_damage"]


class TestAnActiveGrantRidesItsCast:
    """A stat buff an active grants is earned by casting it, not by owning it.

    The audit's probe: Tristana's Rapid Fire doubled her auto count whether
    or not Q was in the rotation. A rotation that never casts the ability
    earns none of its grant; a passive's grant is always on.
    """

    def test_tristana_q_left_out_of_the_rotation_grants_no_attack_speed(self):
        with_q = _fight_casting("Tristana", ["Q", "W", "E", "R"])
        without_q = _fight_casting("Tristana", ["W", "E", "R"])
        assert _autos(with_q) > _autos(without_q)
        assert "Q" not in without_q["breakdown"]
        assert with_q["champion_stats"]["attack_speed"] > (
            without_q["champion_stats"]["attack_speed"]
        )

    def test_olaf_passive_grant_stays_on_whatever_the_rotation(self):
        default = _fight_casting("Olaf", ["Q", "W", "E", "R"])
        no_casts = _fight_casting("Olaf", [])
        # Berserker Rage is a passive: the attack-speed grant reaches the fight
        # with an empty rotation too, while W (an active grant) does not.
        assert (
            no_casts["champion_stats"]["attack_speed"]
            > _build_stats("Olaf")["attack_speed"]
        )
        assert (
            default["champion_stats"]["attack_speed"]
            > no_casts["champion_stats"]["attack_speed"]
        )
