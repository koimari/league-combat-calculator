"""Issue #135 — the frontend must never re-implement the damage engine.

The in-browser duplicate engine (and its retired 175% critical strike
formula ``1 + (crit / 100) * 0.75``) was deleted from ``static/js/app.js``.
These static contract tests forbid the old formulas, item-id literals, and
dead clusters from returning, pin the single ``attackerLevelCap``
definition, and require the stat cards to consume the backend
``/api/loadout-stats`` receipt.  The 200% critical strike contract itself
is pinned at the public boundary in ``test_frontend_crit_backend_200.py``.
"""

from pathlib import Path

import pytest

APP_JS = Path("static/js/app.js")
SOURCE = APP_JS.read_text(encoding="utf-8")

# Every one of these was live or dead duplicate-engine code on the day the
# issue was filed; none may reappear.
FORBIDDEN_LITERALS = [
    "0.7025",  # level-growth duplicate of src/calculator/stats.growth_stat
    "0.0175",  # level-growth duplicate
    "crit / 100) * 0.75",  # retired 175% crit multiplier (backend BASE_CRIT_MULTIPLIER = 2.0)
    "3089",  # Rabadon's Deathcap by literal id
    "6653",  # Liandry's Torment by literal id
    "6655",  # Luden's Echo by literal id
    "4645",  # Shadowflame by literal id
    "6616",  # Staff of Flowing Water by literal id
    "1.08",  # mid-quest AD/AP duplicate of role_quests.py 8.0%
]

FORBIDDEN_IDENTIFIERS = [
    # local damage engine
    "calculateBuild",
    "buildStats",
    "championStats",
    "attackerChampionStats",
    "rosterChampionStats",
    "autoAttacksForStats",
    "ludenDamage",
    "abilityDamageRows",
    "addBreakdown",
    "allyStatBonuses",
    "rankedValue",
    "effectiveMagicResistance",
    "effectivePhysicalArmor",
    # dead local BIS scoring cluster
    "bisBuildScore",
    "bisPacketValue",
    "bisDamageMultiplier",
    "bisAbilityDamage",
    "bisAutoDamage",
    "bisUtilityValue",
    "bisItemEffects",
    "bisOutgoingSupport",
    "bisSupportItemValue",
    "bisHealingPotential",
    "bisIncomingPressure",
    # dead local optimizer cluster
    "optimizerCandidatePool",
    "roleAwareOptimizerCandidatePool",
    "optimizeRoleAwareBuild",
    "optimizeFullBuild",
    "rosterOptimizerCandidatePool",
    "legalOptimizerBuild",
    "optimizerExclusiveGroups",
    # other dead clusters
    "resultReason",
    "mechanicDetail",
    "itemOccurrence",
    "fightOrderTimeline",
    "exactStatMatrix",
    "exactPoint",
    "exactSupportOutputs",
    "idsForBis",
    "rosterBisIds",
    "buildOptionsForSide",
    "windowControl",
    "renderBuildStrip",
    "renderRoleControls",
    "renderAbilityPackage",
    "targetCard",
    "allyCard",
    "rosterCard",
    "statMatrix",
    "scenarioCapabilityAttributes",
]


@pytest.mark.parametrize("literal", FORBIDDEN_LITERALS)
def test_app_js_forbids_retired_formula_literals(literal):
    assert literal not in SOURCE


@pytest.mark.parametrize("identifier", FORBIDDEN_IDENTIFIERS)
def test_app_js_forbids_dead_engine_identifiers(identifier):
    assert identifier not in SOURCE


def test_app_js_defines_attacker_level_cap_exactly_once():
    assert SOURCE.count("function attackerLevelCap()") == 1


def test_app_js_analyst_fallback_returns_unavailable_never_local_estimates():
    # The null-response branch must surface "Unavailable" instead of
    # computing local numbers, and the result renderer must only ever
    # consume backend receipts.
    assert 'if (!engine.responses) return "Unavailable";' in SOURCE
    assert "renderPrototypeResult(engine.responses?.a || null" in SOURCE
    assert "clearAnalystScores()" in SOURCE
    assert "calculateBuild" not in SOURCE


def test_app_js_stat_cards_consume_backend_loadout_stats():
    # Positive receipt contract: the stat cards come from POST
    # /api/loadout-stats (with the /api/calculate participant stats as a
    # same-loadout backfill), never from local champion math.
    assert '"/api/loadout-stats"' in SOURCE
    assert "function scheduleLoadoutStats(" in SOURCE
    assert "function displayStatsFromBackend(" in SOURCE
    assert "function currentLoadoutStats(" in SOURCE
    assert "engine.loadoutStats" in SOURCE
    assert "function mainParticipantBackendStats(" in SOURCE
