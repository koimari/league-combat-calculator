"""Exhaustive contracts for fail-closed attacker certification reasons."""

import json

from src.calculator.champion_coverage import attacker_availability
from src.calculator.champions import registered_champion_names


def _champions():
    with open("data/champions.json", encoding="utf-8") as handle:
        return list(json.load(handle).values())


def test_every_cached_champion_has_an_explicit_attacker_status():
    verified = set(registered_champion_names())
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
    verified = set(registered_champion_names())
    by_name = {champion["name"]: champion for champion in _champions()}

    aphelios = attacker_availability(by_name["Aphelios"], verified)
    teemo = attacker_availability(by_name["Teemo"], verified)
    nami = attacker_availability(by_name["Nami"], verified)
    olaf = attacker_availability(by_name["Olaf"], verified)
    assert "alternate_forms" in {row["code"] for row in aphelios["blockers"]}
    assert {"attack_events", "timed_stages"} <= {
        row["code"] for row in teemo["blockers"]
    }
    toxic_shot = next(
        row for row in teemo["blockers"] if row["code"] == "attack_events"
    )
    assert "E · Toxic Shot" in toxic_shot["abilities"]
    assert {"attack_events", "timed_stages"} <= {
        row["code"] for row in nami["blockers"]
    }
    assert "stat_steroids" in {row["code"] for row in olaf["blockers"]}


def test_unsupported_scaling_names_the_affected_ability():
    verified = set(registered_champion_names())
    report = next(
        attacker_availability(champion, verified)
        for champion in _champions()
        if any(
            blocker["code"] == "unsupported_scaling"
            for blocker in attacker_availability(champion, verified)["blockers"]
        )
    )
    blocker = next(
        blocker
        for blocker in report["blockers"]
        if blocker["code"] == "unsupported_scaling"
    )

    assert blocker["abilities"]
    assert blocker["units"]


def test_reviewed_module_overrides_heuristic_complexity():
    verified = set(registered_champion_names())
    ziggs = next(champion for champion in _champions() if champion["name"] == "Ziggs")

    assert attacker_availability(ziggs, verified)["ready"] is True
