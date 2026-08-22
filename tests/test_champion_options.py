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
    get_champion_option_rotation,
    get_champion_options_meta,
    registered_champion_names,
)
from src.calculator.champions.inputs import bool_option, float_option, int_option

_OPTION_TYPES = {
    "bool": bool,
    "int": int,
    "float": (int, float),
    "select": str,
    "string_list": list,
}


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
            {
                "key": "q_tumble_reset",
                "type": "bool",
                "default": False,
                "label": (
                    "Model Tumble's attack-reset throughput: each accepted "
                    "Q cast buys one extra basic attack (the wiki: 'Tumble "
                    "resets Vayne's basic attack timer'; the binary "
                    "Trait_AttackReset tag; the acceleration magnitude is "
                    "script-side)"
                ),
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

    def test_unknown_fixture_has_empty_meta(self) -> None:
        """Only unknown synthetic fixtures lack module metadata."""
        assert get_champion_options_meta("Synthetic Fixture") == {
            "options": [],
            "assumptions": [],
            "sources": [],
        }

    def test_manifest_receipt_fills_module_without_inline_sources(self) -> None:
        """Ahri exposes the E9-2 P option and keeps the packet sources."""
        meta = get_champion_options_meta("Ahri")
        assert [option["key"] for option in meta["options"]] == ["p_essence_fragments"]
        assert meta["assumptions"]
        assert any("Essence Theft" in text for text in meta["assumptions"])
        assert meta["sources"] == [
            {
                "label": "Local League Wiki cache",
                "url": "https://wiki.leagueoflegends.com/en-us/Ahri",
                "revision_id": 4047800,
                "revision_timestamp": "2026-07-31T01:16:52Z",
            }
        ]

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
        """A champion with no knobs still has assumptions to display.

        Named by the property rather than by one champion: a module that
        gains its first option should not turn this test red.
        """
        meta_map = champion_options_meta_map()
        knobless = [name for name, meta in meta_map.items() if not meta["options"]]
        assert knobless
        assert all(meta_map[name]["assumptions"] for name in knobless)

    def test_includes_revision_backed_champions(self) -> None:
        meta_map = champion_options_meta_map()

        assert len(meta_map["Lissandra"]["sources"]) == 4
        assert len(meta_map["Rakan"]["sources"]) == 5
        assert len(meta_map["Soraka"]["sources"]) == 2

    def test_excludes_champions_with_empty_meta(self) -> None:
        meta_map = champion_options_meta_map()
        assert "Ahri" in meta_map
        assert meta_map["Ahri"]["sources"]
        assert "Synthetic Fixture" not in meta_map


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
                if opt["type"] == "select":
                    assert opt.get("choices"), (name, opt)
                    values = [choice["value"] for choice in opt["choices"]]
                    assert len(values) == len(set(values)), (name, opt)
                    assert opt["default"] in values, (name, opt)

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
                assert source["revision_id"] > 0, (name, source)

    def test_all_registered_modules_expose_manifest_or_inline_receipts(self) -> None:
        """The full registry has no provenance-empty champion metadata."""
        names = registered_champion_names()
        assert len(names) == len(_CHAMPION_MODULES)
        assert all(get_champion_options_meta(name)["sources"] for name in names)

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
        declaration or a rename that missed the parse path.  The one generic
        consumer is ``packet_module.select_variant``: it both declares a
        ``<slot>_variant`` option (labelled ``"<SLOT> packet variant"``) and
        reads it, so those keys need no literal in the champion module.
        """
        for name in _CHAMPION_MODULES:
            source = inspect.getsource(_module(name))
            for opt in get_champion_options_meta(name)["options"]:
                key = opt["key"]
                if (
                    key == f"{key[0]}_variant"
                    and opt["label"] == f"{key[0].upper()} packet variant"
                ):
                    continue
                assert f'"{opt["key"]}"' in source, (
                    f"{name}: OPTIONS key {opt['key']!r} is not referenced "
                    f"anywhere in its module — stale declaration or rename?"
                )


class TestRotationDeclarations:
    """Every OPTIONS entry carries typed rotation semantics (issue #145).

    The rotation resolver builds its setup/consume edges FROM these
    declarations, so an unclassified option is a contract failure: a
    rotation receipt must never claim "no detectable setup/consume signal"
    while an enabled semantic option is unclassified or unsupported.
    """

    _ROTATION_ROLES = {
        "setup",
        "consume",
        "self_state",
        "execute",
        "irrelevant",
        "unsupported",
    }
    _VALID_SLOTS = {"P", "Q", "Q2", "W", "E", "R", "auto_stream"}

    def test_every_option_is_classified_for_rotation_semantics(self) -> None:
        """An unclassified option fails the suite (exhaustiveness)."""
        for name in _CHAMPION_MODULES:
            rotations = get_champion_option_rotation(name)
            for opt in get_champion_options_meta(name)["options"]:
                key = str(opt["key"])
                decl = rotations.get(key)
                assert (
                    decl is not None
                ), f"{name}: option {key!r} has no rotation classification"

    def test_rotation_declaration_shape_is_valid(self) -> None:
        """Role is closed to the six-role vocabulary; slot/setup_slot valid."""
        for name in _CHAMPION_MODULES:
            rotations = get_champion_option_rotation(name)
            for opt in get_champion_options_meta(name)["options"]:
                key = str(opt["key"])
                decl = rotations.get(key)
                assert decl is not None, (name, key)
                role = decl.get("role")
                assert role in self._ROTATION_ROLES, (name, key, decl)
                assert decl.get("slot") in self._VALID_SLOTS, (name, key, decl)
                if role in ("consume", "execute"):
                    setup_slot = decl.get("setup_slot")
                    assert setup_slot is None or setup_slot in self._VALID_SLOTS, (
                        name,
                        key,
                        decl,
                    )
                else:
                    assert "setup_slot" not in decl, (name, key, decl)


class TestOptionConstructors:
    """The typed builders every OPTIONS row is written through."""

    def test_a_bool_row_carries_no_range(self) -> None:
        assert bool_option("q_active", True, label="Q active") == {
            "key": "q_active",
            "type": "bool",
            "default": True,
            "label": "Q active",
        }

    def test_an_int_row_states_its_range(self) -> None:
        assert int_option("stacks", 3, minimum=0, maximum=6, label="Stacks") == {
            "key": "stacks",
            "type": "int",
            "default": 3,
            "min": 0,
            "max": 6,
            "label": "Stacks",
        }

    def test_a_float_row_states_its_range(self) -> None:
        assert float_option(
            "uptime", 0.5, minimum=0.0, maximum=1.0, label="Uptime"
        ) == {
            "key": "uptime",
            "type": "float",
            "default": 0.5,
            "min": 0.0,
            "max": 1.0,
            "label": "Uptime",
        }

    def test_the_key_order_is_canonical_whatever_the_call_order(self) -> None:
        """The row's shape is the builder's, not the caller's: extras follow
        the canonical five however they were passed."""
        row = int_option(
            "stacks", 3, minimum=0, maximum=6, label="Stacks", rotation={}, step=1
        )
        assert list(row) == [
            "key",
            "type",
            "default",
            "min",
            "max",
            "label",
            "step",
            "rotation",
        ]

    def test_extras_ride_through_untouched(self) -> None:
        rotation = {"role": "self_state", "slot": "E"}
        assert bool_option("e", False, label="E", rotation=rotation)["rotation"] is (
            rotation
        )

    def test_every_registered_row_matches_its_builder(self) -> None:
        """Whatever a module wrote, the published row is a builder's shape."""
        builders = {"bool": bool_option, "int": int_option, "float": float_option}
        for name in registered_champion_names():
            for row in get_champion_options_meta(name)["options"]:
                builder = builders.get(row["type"])
                if builder is None or ("min" in row) != ("max" in row):
                    continue
                extra = {
                    k: v
                    for k, v in row.items()
                    if k not in ("key", "type", "default", "min", "max", "label")
                }
                ranges = (
                    {}
                    if row["type"] == "bool"
                    else {"minimum": row["min"], "maximum": row["max"]}
                )
                assert (
                    builder(
                        row["key"],
                        row["default"],
                        label=row["label"],
                        **ranges,
                        **extra,
                    )
                    == row
                ), (name, row["key"])
