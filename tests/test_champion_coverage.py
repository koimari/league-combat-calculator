"""Exhaustive contracts for fail-closed attacker certification reasons."""

import json

from src.calculator.champion_coverage import attacker_availability
from src.calculator.champions import reviewed_champion_names


def _champions():
    with open("data/champions.json", encoding="utf-8") as handle:
        return list(json.load(handle).values())


def test_every_cached_champion_has_an_explicit_attacker_status():
    verified = set(reviewed_champion_names())
    reports = [attacker_availability(champion, verified) for champion in _champions()]

    assert len(reports) == 173
    assert sum(report["ready"] for report in reports) == len(verified)
    for report in reports:
        if report["ready"]:
            assert report == {
                "ready": True,
                "verification": "reviewed_module",
                "blockers": [],
            }
        else:
            assert report["verification"] == "blocked"
            assert report["blockers"]
            assert all(blocker["code"] for blocker in report["blockers"])
            assert all(blocker["label"] for blocker in report["blockers"])


def test_known_complex_kits_report_their_actual_blocker_categories():
    verified = set(reviewed_champion_names())
    by_name = {champion["name"]: champion for champion in _champions()}

    assert attacker_availability(by_name["Aphelios"], verified) == {
        "ready": True,
        "verification": "reviewed_module",
        "blockers": [],
    }
    for name in ("Teemo", "Ryze", "Samira"):
        report = attacker_availability(by_name[name], verified)
        assert report["ready"] is False
        assert report["verification"] == "blocked"
        assert report["blockers"]


def test_unsupported_scaling_names_the_affected_ability():
    verified = set(reviewed_champion_names())
    reports = [attacker_availability(champion, verified) for champion in _champions()]
    assert any(not report["ready"] for report in reports)
    assert all(report["blockers"] for report in reports if not report["ready"])


def test_reviewed_module_overrides_heuristic_complexity():
    verified = set(reviewed_champion_names())
    ziggs = next(champion for champion in _champions() if champion["name"] == "Ziggs")

    assert attacker_availability(ziggs, verified)["ready"] is True
