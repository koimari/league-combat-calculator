"""Tests for champion option/assumption metadata (OPTIONS/ASSUMPTIONS).

Each registered champion module declares its frontend option controls
and modeling assumptions as data beside its SLOTS; the dispatcher
serves them via get_champion_options_meta / champion_options_meta_map
(consumed by /api/config).
"""

import importlib
import inspect

from src.calculator.champions import (
    _CHAMPION_MODULES,
    RESERVED_OPTION_KEYS,
    champion_options_meta_map,
    get_champion_options_meta,
)

_OPTION_TYPES = {"bool": bool, "int": int, "float": (int, float)}


def _module(champion_name: str):
    return importlib.import_module(
        f"src.calculator.champions.{_CHAMPION_MODULES[champion_name]}"
    )


class TestGetChampionOptionsMeta:
    """Per-champion metadata accessor."""

    def test_champion_with_options(self) -> None:
        """Vayne declares the condemn_wall bool with its UI label."""
        meta = get_champion_options_meta("Vayne")
        assert meta["options"] == [
            {
                "key": "condemn_wall",
                "type": "bool",
                "default": True,
                "label": "E Condemn into wall",
            },
        ]
        assert any("Silver Bolts" in text for text in meta["assumptions"])

    def test_int_option_carries_bounds(self) -> None:
        """Akshan's passive_procs is an int input with min/max."""
        meta = get_champion_options_meta("Akshan")
        procs = next(o for o in meta["options"] if o["key"] == "passive_procs")
        assert procs["type"] == "int"
        assert procs["default"] == 3
        assert procs["min"] == 0
        assert procs["max"] == 20

    def test_unregistered_champion_has_empty_meta(self) -> None:
        """The generic path takes no options."""
        assert get_champion_options_meta("Garen") == {
            "options": [],
            "assumptions": [],
            "sources": [],
        }

    def test_registered_champion_without_options(self) -> None:
        """Ahri has neither options nor assumptions declared."""
        assert get_champion_options_meta("Ahri") == {
            "options": [],
            "assumptions": [],
            "sources": [],
        }

    def test_revision_backed_champion_exposes_sources(self) -> None:
        meta = get_champion_options_meta("Soraka")

        assert [source["label"] for source in meta["sources"]] == [
            "Starcall",
            "Equinox",
        ]
        assert all(source["url"].startswith("https://") for source in meta["sources"])
        assert all(source["revision_id"] > 0 for source in meta["sources"])
        assert all(
            source["revision_timestamp"].endswith("Z") for source in meta["sources"]
        )


class TestChampionOptionsMetaMap:
    """The /api/config map: only champions with something to show."""

    def test_includes_champions_with_options(self) -> None:
        meta_map = champion_options_meta_map()
        assert "Vayne" in meta_map
        assert "Kog'Maw" in meta_map

    def test_includes_assumptions_only_champions(self) -> None:
        """Alistar has no knobs but does have assumptions to display."""
        meta_map = champion_options_meta_map()
        assert meta_map["Alistar"]["options"] == []
        assert len(meta_map["Alistar"]["assumptions"]) > 0

    def test_includes_revision_backed_champions(self) -> None:
        meta_map = champion_options_meta_map()

        assert len(meta_map["Lissandra"]["sources"]) == 4
        assert len(meta_map["Soraka"]["sources"]) == 2

    def test_excludes_champions_with_empty_meta(self) -> None:
        meta_map = champion_options_meta_map()
        assert "Ahri" not in meta_map
        assert "Garen" not in meta_map


class TestOptionsDeclarationValidity:
    """Every registered module's OPTIONS list is well-formed and live."""

    def test_options_shape(self) -> None:
        """key/type/default/label present; defaults match their type."""
        for name in _CHAMPION_MODULES:
            for opt in get_champion_options_meta(name)["options"]:
                assert set(opt) >= {"key", "type", "default", "label"}, (name, opt)
                assert opt["type"] in _OPTION_TYPES, (name, opt)
                assert isinstance(opt["default"], _OPTION_TYPES[opt["type"]]), (
                    name,
                    opt,
                )
                if "min" in opt and "max" in opt:
                    assert opt["min"] <= opt["default"] <= opt["max"], (name, opt)

    def test_sources_shape(self) -> None:
        """Every declared source is a revision-pinned Wiki page."""
        required = {"label", "url", "revision_id", "revision_timestamp"}
        for name in _CHAMPION_MODULES:
            for source in get_champion_options_meta(name)["sources"]:
                assert set(source) == required, (name, source)
                assert source["url"].startswith("https://wiki.leagueoflegends.com/"), (
                    name,
                    source,
                )
                assert isinstance(source["revision_id"], int), (name, source)

    def test_no_option_key_collides_with_a_reserved_key(self) -> None:
        """Reserved keys are pipeline-owned (``RESERVED_OPTION_KEYS``).

        A module declaring one would render a frontend control that
        ``pipeline.run_fight`` silently clobbers in every timed fight.
        """
        for name in _CHAMPION_MODULES:
            for opt in get_champion_options_meta(name)["options"]:
                assert opt["key"] not in RESERVED_OPTION_KEYS, (
                    f"{name}: OPTIONS key {opt['key']!r} collides with a "
                    "pipeline-reserved option key"
                )

    def test_every_option_key_is_consumed_by_the_module(self) -> None:
        """Each OPTIONS key must appear in its module's source.

        The parse path reads options via ``ctx.options.get(key, ...)``
        or archetype params (``by_option(key, ...)``,
        ``count_option=key``), so a
        declared key that never appears in the module source is a stale
        declaration or a rename that missed the parse path.
        """
        for name in _CHAMPION_MODULES:
            source = inspect.getsource(_module(name))
            for opt in get_champion_options_meta(name)["options"]:
                assert f'"{opt["key"]}"' in source, (
                    f"{name}: OPTIONS key {opt['key']!r} is not referenced "
                    f"anywhere in its module — stale declaration or rename?"
                )
