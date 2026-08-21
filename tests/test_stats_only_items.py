"""Certification for the 90 SR-admitted ``stats_only`` items (roadmap-100 §1).

``stats_only`` means ``item_coverage._attacker_coverage()`` found no
outgoing-damage mechanic on the item's OWN HOLDER to model -- not that the
cached entry is textually numberless.  51 of the 92 have no described
passive/active at all; the other 41 have a real, numeric passive/active
(shields, Grievous Wounds, stasis, ally-directed heals routed through the
separate support ledger, ...) that is correctly excluded from this
calculator's outgoing-TDD model.  See ``item_coverage.py``'s
``_STATS_ONLY_CERTIFIED_EFFECT_TEXT`` docstring for the full reasoning.

This suite is the certification pass itself:

* every item in the set is genuinely ``stats_only``, optimizer-eligible, and
  calculation-eligible (matches ``item_model_coverage``'s own contract);
* every item is an ordinary Summoner's Rift purchase per ``item_source``;
* the 41 described items' cached branch text is pinned byte-for-byte, so a
  future patch cannot silently attach a new outgoing-damage clause to a
  name-matched entry and keep sailing through as ``stats_only``;
* the item's own cached stat block is exactly what
  ``stats.calculate_total_stats`` adds when the item is equipped alone --
  spot-checked through the isolated ``bonus_*``/pass-through output fields
  that carry no other item's or the base champion's own contribution.
"""

import pytest

from src.calculator.data_fetcher import fetch_item_data, get_champion
from src.calculator.item_coverage import (
    _STATS_ONLY_CERTIFIED_EFFECT_TEXT,
    item_model_coverage,
    stats_only_effect_fingerprint,
)
from src.calculator.item_source import is_ordinary_sr_item
from src.calculator.stats import calculate_total_stats, get_item_stats

from src.calculator.item_coverage import ATTACKER_LANES


def _attacker_coverage(item):
    """Ours' lane-taking classifier, called with the cached record these
    tests carry.  The payload shape is unchanged; only the argument moved
    from the record to the name plus the lanes the caller needs."""
    return item_model_coverage(str(item["name"]), ATTACKER_LANES).as_payload()


# The 91-plus SR-admitted items whose current cached data classifies as
# stats_only.  Computed live (the same predicate the optimizer's candidate
# pool and docs/roadmap-100.md §6.1 use) rather than hand-listed, so this
# suite cannot drift from what the runtime actually classifies -- if a patch
# changes the *count*, ``test_certified_count_matches_roadmap_100`` below
# fails loudly instead of silently certifying a different set than the one
# reported in the roadmap.


def _all_stats_only_items() -> list[dict]:
    items = fetch_item_data()
    sr_items = [item for item in items.values() if is_ordinary_sr_item(item)]
    return [
        item for item in sr_items if _attacker_coverage(item)["status"] == "stats_only"
    ]


_CERTIFIED_ITEMS = _all_stats_only_items()
_CERTIFIED_NAMES = sorted(str(item["name"]) for item in _CERTIFIED_ITEMS)
_ITEMS_BY_NAME = {str(item["name"]): item for item in _CERTIFIED_ITEMS}


# ---------------------------------------------------------------------------
# Classification certification
# ---------------------------------------------------------------------------


def test_certified_count_matches_roadmap_100():
    """The SR-admitted ``stats_only`` population, re-pinned from the
    declaration-driven classifier.

    90, not the roadmap's 92.  Six items left the population because they
    declare something the engines run — Diadem of Songs, Dream Maker, Echoes
    of Helia, Moonstone Renewer and Solstice Sleigh declare ally_packet
    mechanics the support ledger schedules, and Spirit Visage declares a
    sustain multiplier — and four joined it because their declared families
    are all defences: Bramble Vest and Thornmail (reactive), Force of Nature
    and Jak'Sho (combat_state).  A count drift from here means the classifier
    moved again and must be re-read, not silently tolerated.
    """
    assert len(_CERTIFIED_ITEMS) == 90


def test_certified_names_have_no_duplicates():
    assert len(_CERTIFIED_NAMES) == len(set(_CERTIFIED_NAMES))


@pytest.mark.parametrize("item_name", _CERTIFIED_NAMES)
def test_certified_item_is_stats_only_and_eligible(item_name):
    coverage = _attacker_coverage(_ITEMS_BY_NAME[item_name])

    assert coverage["status"] == "stats_only"
    assert coverage["optimizer_eligible"] is True
    assert coverage["calculation_eligible"] is True
    assert coverage["reason"]


@pytest.mark.parametrize("item_name", _CERTIFIED_NAMES)
def test_certified_item_is_an_ordinary_sr_purchase(item_name):
    assert is_ordinary_sr_item(_ITEMS_BY_NAME[item_name])


# ---------------------------------------------------------------------------
# Effect-text drift protection (the 41 described items)
# ---------------------------------------------------------------------------


def test_fingerprint_registry_matches_the_described_subset_exactly():
    """Every stats_only item with real cached passive/active text must be
    fingerprinted, and nothing else -- an item cannot silently join or leave
    the described subset without this registry being updated alongside it.
    """
    described_names = {
        name
        for name, item in _ITEMS_BY_NAME.items()
        if stats_only_effect_fingerprint(item)
    }

    assert described_names == set(_STATS_ONLY_CERTIFIED_EFFECT_TEXT)


@pytest.mark.parametrize("item_name", sorted(_STATS_ONLY_CERTIFIED_EFFECT_TEXT))
def test_certified_effect_text_has_not_drifted(item_name):
    """A pinned item's cached branch text must match byte-for-byte.

    A failure here does not by itself mean a new outgoing-damage mechanic
    appeared -- it means a human must re-read the branch and either re-pin
    the fingerprint (no mechanic change) or reclassify the item.
    """
    live_fingerprint = stats_only_effect_fingerprint(_ITEMS_BY_NAME[item_name])

    assert live_fingerprint == _STATS_ONLY_CERTIFIED_EFFECT_TEXT[item_name]


# ---------------------------------------------------------------------------
# Stat-block certification: equipping the item alone must contribute exactly
# its own cached stat line, nothing more.
# ---------------------------------------------------------------------------

# get_item_stats() keys mapped to the calculate_total_stats() output field
# that isolates JUST that one item's own contribution -- no base-champion
# term and no other item mixed in -- for a champion equipped with only this
# one item.  Rounded fields (health/AD/AP/armor/MR/mana) round only the
# item's own contribution here (e.g. "bonus_armor" = round(item armor), not
# round(base + item)), so an exact cached item stat still needs at most a
# tolerance of one rounding half-unit, never base-champion float drift.
_ISOLATED_STAT_FIELDS: dict[str, str] = {
    "health": "bonus_health",
    "attack_damage": "bonus_attack_damage",
    "ability_power": "ability_power",  # base ability_power is always 0.0
    "armor": "bonus_armor",
    "magic_resistance": "bonus_magic_resistance",
    "magic_penetration_flat": "magic_penetration_flat",
    "magic_penetration_percent": "magic_penetration_percent",
    "lethality": "lethality",
    "armor_penetration_percent": "armor_penetration_percent",
    "armor_penetration_bonus_percent": "armor_penetration_bonus_percent",
    "critical_strike_chance": "critical_strike_chance",
    "mana": "bonus_mana",
    "ability_haste": "ability_haste",
    "omnivamp_percent": "omnivamp_percent",
    "heal_and_shield_power_percent": "heal_and_shield_power_percent",
    "health_regen_percent": "health_regen_percent",
    "tenacity_percent": "tenacity_percent",
    "gold_per_10": "gold_per_10",
    "critical_strike_damage_percent": "critical_strike_damage_percent",
}
_ROUNDED_ISOLATED_FIELDS = {
    "bonus_health",
    "bonus_attack_damage",
    "ability_power",
    "bonus_armor",
    "bonus_magic_resistance",
    "bonus_mana",
}

# attack_speed_percent is not isolated on its own (the output field also
# carries the champion's level-based AS growth), so it is checked as a
# before/after delta instead -- the field itself is never rounded, so the
# delta is exact regardless of the champion's base attack speed.
_DELTA_STAT_FIELDS: dict[str, str] = {
    "attack_speed_percent": "bonus_attack_speed",
}

_FIXTURE_CHAMPION_NAME = "Ashe"
_FIXTURE_LEVEL = 18


@pytest.mark.parametrize("item_name", _CERTIFIED_NAMES)
def test_certified_item_stat_contribution_matches_cached_stat_block(item_name):
    item = _ITEMS_BY_NAME[item_name]
    champion = get_champion(_FIXTURE_CHAMPION_NAME)
    expected = get_item_stats(item)

    equipped = calculate_total_stats(champion, _FIXTURE_LEVEL, [item])

    for stat_key, output_field in _ISOLATED_STAT_FIELDS.items():
        expected_value = expected.get(stat_key, 0.0)
        if not expected_value:
            continue
        tolerance = 0.5 if output_field in _ROUNDED_ISOLATED_FIELDS else 1e-6
        assert equipped[output_field] == pytest.approx(expected_value, abs=tolerance), (
            item_name,
            stat_key,
            output_field,
        )

    if any(expected.get(key) for key in _DELTA_STAT_FIELDS):
        baseline = calculate_total_stats(champion, _FIXTURE_LEVEL, [])
        for stat_key, output_field in _DELTA_STAT_FIELDS.items():
            expected_value = expected.get(stat_key, 0.0)
            if not expected_value:
                continue
            delta = equipped[output_field] - baseline[output_field]
            assert delta == pytest.approx(expected_value, abs=1e-6), (
                item_name,
                stat_key,
            )


def test_a_meaningful_number_of_certified_items_carry_a_checkable_stat():
    """Guards against the isolated-field map silently checking nothing.

    Some certified items (potions, wards, trinkets) legitimately have an
    empty cached stat block -- that is not a test gap. This assertion just
    confirms the field map above is not accidentally dead code.
    """
    checked = 0
    for item in _CERTIFIED_ITEMS:
        stats = get_item_stats(item)
        if any(
            stats.get(key) for key in {**_ISOLATED_STAT_FIELDS, **_DELTA_STAT_FIELDS}
        ):
            checked += 1
    assert checked >= 40
