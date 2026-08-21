"""Tests for the Aphelios champion module's E slot (Weapon Queue System).

P/Q/W/R are exercised elsewhere (test_e1_healing_b1.py, test_issue_137.py,
test_p1_review_2.py, test_spellblade_on_hit_matrix.py,
test_survival_kernel.py) since Aphelios' weapon-aware kit is threaded
through those thematic suites rather than a single champion file. This
file covers the roadmap session (2026-08-21) closing the last
out_of_scope slot: E now emits a sourced zero-damage row.
"""


class TestEWeaponQueueSystem:
    """E (Weapon Queue System) carries no enemy-damage attribute
    (damageType: None, empty leveling list on both effects) — it emits a
    sourced zero-damage row rather than staying silently absent."""

    def test_e_present_zero_damage(self, aphelios_data, parse_at) -> None:
        _, abilities = parse_at(aphelios_data, 9)
        entry = abilities["E"]
        assert entry["name"] == "Weapon Queue System"
        assert entry["total_raw"] == 0.0
        assert entry["parts"] == ()
        assert entry["detail"]


class TestModuleCoverage:
    def test_all_five_slots_covered(self) -> None:
        from src.calculator.champions.aphelios import MODULE_COVERAGE

        assert MODULE_COVERAGE == {
            "P": "modeled",
            "Q": "modeled",
            "W": "modeled",
            "E": "no_damage",
            "R": "modeled",
        }
