"""Reviewed evidence separates shield and healing rows from enemy damage."""

import copy
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import build_reviewed_modules as builder
from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.packet_module import SlotOverrides, _compiled_slot
from src.calculator.scenario import load_public_champion
from tests import row_review

ROOT = Path(__file__).resolve().parents[1]


def test_yasuo_flow_values_cannot_become_a_damage_packet():
    kit = load_public_champion("Yasuo")
    assert (
        kit["abilities"]["P"][0]["effects"][2]["leveling"][0]["attribute"]
        == "Bonus Damage"
    )
    assert builder._wiki_specs(kit["abilities"]["P"], "P") == []


def test_gwen_healing_cap_cannot_replace_the_named_proc():
    kit = copy.deepcopy(load_public_champion("Gwen"))
    spec = builder._wiki_specs(kit["abilities"]["P"], "P")[0]
    assert spec["kind"] == "named_module"
    assert spec["owner"] == "src/calculator/champions/gwen.py"
    assert "1% (+ 0.6% per 100 AP)" in spec["source_formula"]
    kit["abilities"]["P"][0]["effects"][1]["leveling"][0]["modifiers"][0]["values"] = [
        99999
    ]
    assert builder._wiki_specs(kit["abilities"]["P"], "P")[0] == spec
    with pytest.raises(ValueError, match="requires its named module"):
        _compiled_slot(spec, "P", SlotOverrides(frozenset(), {}, {}, {}, {}))


@pytest.mark.parametrize("ap", [0.0, 200.0])
@pytest.mark.parametrize("target_hp", [1000.0, 3000.0])
def test_gwen_owner_prices_target_health_and_ap(ap, target_hp):
    stats = {**row_review.STATS, "ability_power": ap}
    target = {**row_review.TARGET, "target_max_health": target_hp}
    parsed = parse_champion_abilities(
        load_public_champion("Gwen"),
        18,
        ap,
        row_review.RANKS,
        champion_stats=stats,
        target_stats=target,
    )
    assert parsed["passive"]["on_hit"]["damage_per_hit"] == pytest.approx(
        target_hp * (0.01 + 0.00006 * ap)
    )


def test_full_entry_audit_cli_bootstraps_repo_imports(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/full_entry_audit.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_full_entry_audit_rejects_wrong_named_owner(monkeypatch):
    from scripts import full_entry_audit as audit

    original_load = audit._load
    manifest = copy.deepcopy(original_load(audit.PACKET_MANIFEST_PATH))
    spec = builder._wiki_specs(load_public_champion("Gwen")["abilities"]["P"], "P")[0]
    spec["owner"] = "src/calculator/champions/yasuo.py"
    manifest["champions"]["Gwen"]["slots"]["P"] = spec
    monkeypatch.setattr(
        audit,
        "_load",
        lambda path: (
            manifest if path == audit.PACKET_MANIFEST_PATH else original_load(path)
        ),
    )
    receipt = audit._champion_module_receipt("Gwen")
    assert receipt["status"] == "review_pending"
    assert receipt["named_module_errors"] == [
        "P requires named owner src.calculator.champions.yasuo"
    ]


@pytest.mark.parametrize(
    "mutation", [{}, {"source": ["Q", 0]}, {"source_formula": "99% maximum health"}]
)
def test_full_entry_audit_checks_named_formula_source(monkeypatch, mutation):
    from scripts import full_entry_audit as audit

    original_load = audit._load
    manifest = copy.deepcopy(original_load(audit.PACKET_MANIFEST_PATH))
    spec = builder._wiki_specs(load_public_champion("Gwen")["abilities"]["P"], "P")[0]
    spec.update(mutation)
    manifest["champions"]["Gwen"]["slots"]["P"] = spec
    monkeypatch.setattr(
        audit,
        "_load",
        lambda path: (
            manifest if path == audit.PACKET_MANIFEST_PATH else original_load(path)
        ),
    )
    receipt = audit._champion_module_receipt("Gwen")
    assert receipt["status"] == ("review_pending" if mutation else "ready")
