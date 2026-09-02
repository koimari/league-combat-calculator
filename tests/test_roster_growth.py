"""Roster-growth regression for issue #136.

Adding one champion must require NO literal-count edits anywhere: the
builders derive their counts from the cache, the registry derives from
``_CHAMPION_MODULES`` (the single explicit manifest), and the audits
derive from the cache.  A literal count guard anywhere would fail these
tests when the roster grows — including one written here, so the expected
size is :func:`_grown_size`, derived from the same cache the fixture is.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _grown_size() -> int:
    """The cached roster plus the one synthetic champion the fixture adds."""
    return len(_cache_with_synthetic_champion())


def _cache_with_synthetic_champion() -> dict:
    """Every cached champion plus one synthetic champion."""
    with (ROOT / "data" / "champions.json").open(encoding="utf-8") as handle:
        champions = json.load(handle)
    base = next(value for value in champions.values() if value.get("name") == "Ahri")
    synthetic = copy.deepcopy(base)
    synthetic["name"] = "Synthetic 174"
    synthetic["key"] = "Synthetic174"
    synthetic["id"] = "Synthetic174"
    champions["Synthetic174"] = synthetic
    return champions


def test_catalog_builder_accepts_a_larger_cached_roster(tmp_path):
    """build_catalog derives its count — no literal guard (was SystemExit)."""
    from scripts.build_ability_catalog import build_catalog

    source = tmp_path / "champions.json"
    source.write_text(json.dumps(_cache_with_synthetic_champion()), encoding="utf-8")

    catalog = build_catalog(source, "26.15")
    assert catalog["champion_count"] == _grown_size()
    assert len(catalog["champions"]) == _grown_size()


def test_bis_profiles_builder_accepts_a_larger_cached_roster(tmp_path):
    """build_profiles derives its count — no literal guard (was SystemExit)."""
    from scripts.build_bis_profiles import build_profiles

    source = tmp_path / "champions.json"
    source.write_text(json.dumps(_cache_with_synthetic_champion()), encoding="utf-8")

    profiles = build_profiles(source, "26.15", None)
    assert profiles["champion_count"] == _grown_size()
    assert len(profiles["champions"]) == _grown_size()


def test_builder_cli_mains_succeed_with_a_larger_cached_roster(tmp_path):
    """The CLI entry points exit 0 on a grown cache (were SystemExit 1)."""
    source = tmp_path / "champions.json"
    source.write_text(json.dumps(_cache_with_synthetic_champion()), encoding="utf-8")

    catalog_out = tmp_path / "ability-catalog.json"
    catalog = subprocess.run(
        [
            sys.executable,
            "scripts/build_ability_catalog.py",
            "--source",
            str(source),
            "--output",
            str(catalog_out),
            "--patch",
            "26.15",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert catalog.returncode == 0, catalog.stderr

    bis_out = tmp_path / "bis-profiles.json"
    bis = subprocess.run(
        [
            sys.executable,
            "scripts/build_bis_profiles.py",
            "--source",
            str(source),
            "--output",
            str(bis_out),
            "--patch",
            "26.15",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert bis.returncode == 0, bis.stderr


def test_registry_grows_with_a_manifest_entry(monkeypatch):
    """A new champion only needs a _CHAMPION_MODULES entry."""
    from src.calculator.champions import (
        _CHAMPION_MODULES,
        registered_champion_names,
    )

    with (ROOT / "data" / "champions.json").open(encoding="utf-8") as handle:
        cache_names = {value["name"] for value in json.load(handle).values()}
    assert set(registered_champion_names()) == cache_names

    monkeypatch.setitem(_CHAMPION_MODULES, "Synthetic 174", _CHAMPION_MODULES["Ahri"])
    grown = registered_champion_names()
    assert "Synthetic 174" in grown
    assert len(grown) == len(cache_names) + 1


def test_api_config_counts_match_the_live_registry():
    """/api/config's champion_engine counts equal the derived registry."""
    from src import app as app_module
    from src.calculator.champions import registered_champion_names

    app_module.app.config["RATE_LIMIT_ENABLED"] = False
    engine = (
        app_module.app.test_client().get("/api/config").get_json()["champion_engine"]
    )
    assert engine["registered_count"] == len(registered_champion_names())
    assert "generated_count" not in engine
    assert "unreviewed_count" not in engine
    assert "generic_enabled" not in engine


def test_full_entry_audit_derives_from_the_cache(monkeypatch, tmp_path):
    """The audit reads the cache, so a bigger cache audits bigger."""
    import scripts.full_entry_audit as audit

    source = tmp_path / "champions.json"
    source.write_text(json.dumps(_cache_with_synthetic_champion()), encoding="utf-8")
    monkeypatch.setattr(audit, "CHAMPIONS_PATH", source)

    names = audit.champion_names()
    assert len(names) == _grown_size()
    assert "Synthetic 174" in names
