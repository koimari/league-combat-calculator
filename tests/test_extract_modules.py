"""`scripts/extract_modules.py` on a synthetic package: what moves, what refuses.

file-length-ok: one test file per module under test, and the tool's contract is
one thing: the units it cuts, the imports it computes, the refusals, the residue
and the readers it repoints.
"""

import ast
import json
from pathlib import Path

import pytest

from scripts import extract_modules, module_units

WIDGET = '''"""Widget engine."""

import logging
from dataclasses import dataclass
from decimal import Decimal
from math import floor, isclose
from types import MappingProxyType

from .helper import boost, shine

LOGGER = logging.getLogger(__name__)
RATES = MappingProxyType({"fast": 2.0})

__all__ = ["Widget", "turn", "keep", "shine"]


# The wheel every turn spins.
# Its label reads the rate table.
@dataclass
class Widget:
    """One widget."""

    name: str

    def label(self) -> str:
        return f"{self.name} at {RATES['fast']}"


def turn(widget: "Widget") -> float:
    from .helper import spin

    spin()
    parts: list[Decimal] = [boost(rate) for rate in RATES.values()]
    LOGGER.info("turning %s", widget.label())
    return 0.0 if isclose(sum(parts), 0.0) else sum(parts)


def keep(widget):
    return floor(turn(widget) + STAY)


STAY = 1.0


def ping(n):
    return pong(n) if n else 0.0


def pong(n):
    return ping(n - 1)
'''

READER = '''"""A reader outside the package."""

from src.calculator import widget
from src.calculator.widget import Widget, keep


def test_turn(monkeypatch):
    monkeypatch.setattr("src.calculator.widget.turn", lambda w: 1.0)
    note = "src.calculator.widget.turn is documented here"
    assert widget.turn(Widget("a")) == 1.0
    assert keep is not None
    return note
'''

#: A second source, for the annotation forms the widget engine does not spell:
#: a ``__future__`` import, a ``Literal`` whose members are values, and a type
#: parameter the def itself binds.
GADGET = '''"""Gadget engine."""

from __future__ import annotations

from typing import Literal

MODE_COUNT = 2


def pick[T](items: list[T], mode: Literal["first", "none"]) -> T:
    return items[0] if mode == "first" else items[-1]


def count() -> int:
    return MODE_COUNT
'''

#: Reads Python never evaluates: a quoted annotation naming a moved unit, and a
#: deferred import that goes stale while the module-level one stays live.
QUOTED = '''"""A reader whose annotations are quoted."""

from src.calculator import widget


def spin(w: "widget.Widget") -> float:
    from src.calculator import widget as inner

    return inner.turn(w) + widget.keep(w)
'''

#: The whole read of the source is one quoted annotation of a unit that stays,
#: beside an import held for its side effect and marked as such.
QUOTED_ONLY = '''"""A reader that only names the source in an annotation."""

from src.calculator import widget
from src.calculator import widget as registered  # noqa: F401 - registers the widget


def hold(w: "widget.STAY") -> float:
    return 0.0
'''

SIBLING = '''"""A reader inside the package."""

from .widget import RATES, keep


def rate_sum():
    return sum(RATES.values()) + keep(None)
'''

#: Three modules under one new package, so that every import a new module needs
#: has to be computed: from a sibling new module, from the source's own import
#: block, and from a package the source reached relatively.
ASSIGNMENT = {
    "source": "src/calculator/widget.py",
    "packages": {"src/calculator/fight": "the widget engine's steps."},
    "modules": [
        {
            "path": "src/calculator/fight/rates.py",
            "docstring": "the rate table and the engine's log.",
            "defs": ["LOGGER", "RATES"],
        },
        {
            "path": "src/calculator/fight/wheel.py",
            "docstring": "the widget a turn spins.",
            "defs": ["Widget"],
        },
        {
            "path": "src/calculator/fight/turning.py",
            "docstring": "one turn of one widget.",
            "defs": ["turn"],
        },
    ],
}


#: A package `__init__` as the source: a reader spells the directory's name.
PANEL = '''"""Panel."""

TAG = "panel"


def label():
    return TAG
'''

PANEL_READER = '''"""A reader of the panel package."""

from src.calculator.panel import TAG, label
'''

PANEL_SIBLING = '''"""A reader inside the panel package."""

from . import TAG, label
'''

PANEL_ASSIGNMENT = {
    "source": "src/calculator/panel/__init__.py",
    "modules": [
        {
            "path": "src/calculator/panel/tag.py",
            "docstring": "what a panel is called.",
            "defs": ["TAG"],
        }
    ],
}


GADGET_ASSIGNMENT = {
    "source": "src/calculator/gadget.py",
    "packages": {"src/calculator/gear": "the gadget's steps."},
    "modules": [
        {
            "path": "src/calculator/gear/picking.py",
            "docstring": "picking one item.",
            "defs": ["pick"],
        }
    ],
}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A synthetic repo with the source, a sibling reader and an outside reader."""
    _write(tmp_path / "src/calculator/widget.py", WIDGET)
    _write(tmp_path / "src/calculator/gadget.py", GADGET)
    _write(tmp_path / "src/calculator/helper.py", '"""Helper."""\n')
    _write(tmp_path / "src/calculator/panel/__init__.py", PANEL)
    _write(tmp_path / "src/calculator/panel/banner.py", PANEL_SIBLING)
    _write(tmp_path / "tests/test_panel.py", PANEL_READER)
    _write(tmp_path / "src/calculator/sibling.py", SIBLING)
    _write(tmp_path / "src/calculator/quoted.py", QUOTED)
    _write(tmp_path / "src/calculator/quoted_only.py", QUOTED_ONLY)
    _write(tmp_path / "tests/test_widget.py", READER)
    (tmp_path / "scripts").mkdir()
    monkeypatch.setattr(extract_modules, "REPO", tmp_path)
    return tmp_path


def _plan(assignment=None, **kwargs):
    return extract_modules.Plan(assignment or ASSIGNMENT, **kwargs)


def _written(tree, relative):
    """One written file's text, newlines normalised; the raw bytes are pinned once."""
    return (tree / relative).read_bytes().decode("utf-8").replace("\r\n", "\n")


class TestFreeNames:
    """What one unit reads through an annotation Python never evaluates."""

    def test_a_literal_member_is_not_a_read(self):
        node = ast.parse('def p(m: Literal["first", "none"]) -> int:\n    return 0')
        assert module_units.free_names(node.body[0]) == {"Literal"}

    def test_a_type_parameter_is_not_a_read(self):
        node = ast.parse("def p[T](item: T) -> T:\n    return item")
        assert module_units.free_names(node.body[0]) == set()


class TestPlanning:
    """What the plan resolves before anything is written."""

    def test_every_import_a_new_module_needs_is_computed(self, tree):
        by_key = {m.key: m.imports for m in _plan().modules}
        assert by_key["src/calculator/fight/rates.py"] == [
            "import logging",
            "from types import MappingProxyType",
        ]
        assert by_key["src/calculator/fight/wheel.py"] == [
            "from dataclasses import dataclass",
            "from .rates import RATES",
        ]
        assert by_key["src/calculator/fight/turning.py"] == [
            "from decimal import Decimal",
            "from math import isclose",
            "from ..helper import boost",
            "from .rates import LOGGER, RATES",
            "from .wheel import Widget",
        ]

    def test_a_string_annotation_is_a_read(self, tree):
        turning = next(m for m in _plan().modules if m.path.stem == "turning")
        assert "from .wheel import Widget" in turning.imports

    def test_a_local_variable_annotation_is_a_read(self, tree):
        """Python never evaluates one, so the symbol table cannot see it."""
        turning = next(m for m in _plan().modules if m.path.stem == "turning")
        assert "from decimal import Decimal" in turning.imports

    def test_a_future_import_is_not_a_read(self, tree):
        assert _plan(GADGET_ASSIGNMENT).residue_reads == {"MODE_COUNT"}

    def test_an_annotation_resolves_to_the_one_import_it_needs(self, tree):
        module = _plan(GADGET_ASSIGNMENT).modules[0]
        assert module.imports == ["from typing import Literal"]

    def test_two_reads_of_one_module_become_one_import(self):
        statements = [
            "import logging",
            "from .rates import LOGGER",
            "from .rates import RATES",
        ]
        assert extract_modules.merge_imports(statements) == [
            "import logging",
            "from .rates import LOGGER, RATES",
        ]

    def test_a_read_of_a_unit_that_stays_is_imported_from_the_source(self, tree):
        """``keep`` reads ``STAY`` and ``turn``, and nothing left reads ``keep``."""
        assignment = dict(ASSIGNMENT) | {
            "modules": [
                {
                    "path": "src/calculator/fight/keeping.py",
                    "docstring": "keeping.",
                    "defs": ["keep"],
                }
            ]
        }
        module = _plan(assignment).modules[0]
        assert module.imports == [
            "from math import floor",
            "from ..widget import STAY, turn",
        ]
        assert module.deps == {"src/calculator/widget.py"}

    def test_the_graph_carries_one_edge_per_computed_sibling(self, tree):
        deps = {m.path.stem: sorted(m.deps) for m in _plan().modules}
        assert deps["rates"] == []
        assert deps["wheel"] == ["src/calculator/fight/rates.py"]
        assert deps["turning"] == [
            "src/calculator/fight/rates.py",
            "src/calculator/fight/wheel.py",
        ]

    def test_the_printed_plan_names_units_sizes_imports_and_the_graph(self, tree):
        printed = extract_modules.print_plan(_plan())
        assert "moving 4 units into 3 modules; 5 units stay" in printed
        assert "units: Widget" in printed
        assert (
            "src/calculator/fight/wheel.py -> src/calculator/fight/rates.py" in printed
        )
        assert "residue imports back:\n  from .fight.turning import turn" in printed


class TestRefusals:
    """What the tool will not carry out: an import loop, and a def with no unit."""

    def test_a_cycle_through_the_residue_refuses(self, tree):
        """``turn`` reads three units that stay, and ``keep`` stays and reads it."""
        assignment = dict(ASSIGNMENT) | {
            "modules": [
                {
                    "path": "src/calculator/fight/turning.py",
                    "docstring": "one turn.",
                    "defs": ["turn"],
                }
            ]
        }
        with pytest.raises(extract_modules.Refusal) as refusal:
            _plan(assignment)
        assert str(refusal.value) == (
            "cycle: src/calculator/fight/turning.py -> src/calculator/widget.py"
            " -> src/calculator/fight/turning.py"
        )

    def test_a_cycle_refuses_and_prints_it(self, tree):
        assignment = dict(ASSIGNMENT) | {
            "modules": [
                {
                    "path": "src/calculator/fight/a.py",
                    "docstring": "a.",
                    "defs": ["ping"],
                },
                {
                    "path": "src/calculator/fight/b.py",
                    "docstring": "b.",
                    "defs": ["pong"],
                },
            ]
        }
        with pytest.raises(extract_modules.Refusal) as refusal:
            _plan(assignment)
        assert str(refusal.value).startswith("cycle: ")
        assert "src/calculator/fight/a.py" in str(refusal.value)

    def test_a_def_the_source_does_not_have_refuses(self, tree):
        assignment = dict(ASSIGNMENT) | {
            "modules": [
                {
                    "path": "src/calculator/fight/a.py",
                    "docstring": "a.",
                    "defs": ["nope"],
                }
            ]
        }
        with pytest.raises(extract_modules.Refusal, match="not a unit of"):
            _plan(assignment)


class TestWriting:
    """What lands on disk under ``--write``."""

    def test_a_unit_takes_the_comment_block_directly_above_it(self, tree):
        extract_modules.write_plan(_plan(write=True))
        wheel = _written(tree, "src/calculator/fight/wheel.py")
        assert (
            "# The wheel every turn spins.\n# Its label reads the rate table." in wheel
        )
        assert "@dataclass\nclass Widget:" in wheel
        assert "The wheel every turn spins" not in _written(
            tree, "src/calculator/widget.py"
        )

    def test_a_deferred_relative_import_is_re_levelled(self, tree):
        extract_modules.write_plan(_plan(write=True))
        turning = _written(tree, "src/calculator/fight/turning.py")
        assert "    from ..helper import spin" in turning

    def test_the_source_newline_is_kept(self, tree):
        extract_modules.write_plan(_plan(write=True))
        for relative in ("src/calculator/fight/wheel.py", "src/calculator/widget.py"):
            raw = (tree / relative).read_bytes()
            assert b"\r\n" in raw
            assert b"\n" not in raw.replace(b"\r\n", b"")

    def test_the_residue_binds_the_moved_names_it_still_reads(self, tree):
        extract_modules.write_plan(_plan(write=True))
        residue = _written(tree, "src/calculator/widget.py")
        assert "from .fight.turning import turn" in residue
        assert "def keep(widget):" in residue
        assert "def turn(" not in residue

    def test_the_residue_import_sorts_into_its_block(self, tree):
        """isort's place, not the block's end: `.fight.turning` precedes `.helper`."""
        extract_modules.write_plan(_plan(write=True))
        lines = _written(tree, "src/calculator/widget.py").split("\n")
        assert lines.index("from .fight.turning import turn") < lines.index(
            "from .helper import shine"
        )

    def test_the_residue_drops_an_import_only_a_moved_unit_read(self, tree):
        extract_modules.write_plan(_plan(write=True))
        residue = _written(tree, "src/calculator/widget.py")
        assert "import logging" not in residue
        assert "from .helper import boost" not in residue

    def test_the_residue_keeps_its_future_import(self, tree):
        extract_modules.write_plan(_plan(GADGET_ASSIGNMENT, write=True))
        residue = _written(tree, "src/calculator/gadget.py")
        assert "from __future__ import annotations" in residue
        assert "from typing import Literal" not in residue

    def test_an_import_the_residue_half_reads_keeps_that_half(self, tree):
        extract_modules.write_plan(_plan(write=True))
        residue = _written(tree, "src/calculator/widget.py")
        assert "from math import floor\n" in residue
        assert "isclose" not in residue

    def test_all_drops_the_names_that_moved(self, tree):
        extract_modules.write_plan(_plan(write=True))
        residue = _written(tree, "src/calculator/widget.py")
        assert '__all__ = ["keep", "shine"]' in residue

    def test_a_package_init_is_read_by_its_directory_name(self, tree):
        """`__init__` names no module: both homes are spelled `panel.<name>`."""
        extract_modules.write_plan(_plan(PANEL_ASSIGNMENT, write=True))
        reader = _written(tree, "tests/test_panel.py")
        assert "from src.calculator.panel import label" in reader
        assert "from src.calculator.panel.tag import TAG" in reader
        assert "from .tag import TAG" in _written(
            tree, "src/calculator/panel/__init__.py"
        )
        sibling = _written(tree, "src/calculator/panel/banner.py")
        assert "from . import label" in sibling
        assert "from .tag import TAG" in sibling

    def test_a_name_only_all_publishes_keeps_its_import(self, tree):
        """A re-export is a read: `shine` has no body that names it."""
        extract_modules.write_plan(_plan(write=True))
        residue = _written(tree, "src/calculator/widget.py")
        assert "from .helper import shine" in residue

    def test_each_new_package_gets_its_one_docstring_line(self, tree):
        extract_modules.write_plan(_plan(write=True))
        assert _written(tree, "src/calculator/fight/__init__.py").startswith(
            '"""the widget engine\'s steps."""'
        )

    def test_a_docstring_too_wide_for_one_line_is_wrapped(self):
        """The assignment writes one line; the file has to fit the width."""
        wrapped = extract_modules.docstring_block("word " * 30)
        assert max(len(line) for line in wrapped.split("\n")) <= 88
        assert wrapped.startswith('"""word')
        assert wrapped.endswith('"""')

    def test_a_written_module_starts_with_its_docstring_then_its_imports(self, tree):
        extract_modules.write_plan(_plan(write=True))
        head = _written(tree, "src/calculator/fight/wheel.py").split("\n")
        assert head[0] == '"""the widget a turn spins."""'
        assert head[3] == "from dataclasses import dataclass"
        assert head[5] == "from .rates import RATES"

    def test_one_blank_line_separates_the_written_import_sections(self, tree):
        extract_modules.write_plan(_plan(write=True))
        head = _written(tree, "src/calculator/fight/turning.py").split("\n")
        assert head[3:8] == [
            "from decimal import Decimal",
            "from math import isclose",
            "",
            "from ..helper import boost",
            "from .rates import LOGGER, RATES",
        ]


class TestReaderRewriting:
    """Every form a reader spells a moved name with."""

    def test_an_absolute_import_splits_across_the_new_homes(self, tree):
        extract_modules.write_plan(_plan(write=True))
        reader = _written(tree, "tests/test_widget.py")
        assert "from src.calculator.fight.wheel import Widget" in reader
        assert "from src.calculator.widget import keep" in reader

    def test_a_relative_import_stays_relative(self, tree):
        extract_modules.write_plan(_plan(write=True))
        sibling = _written(tree, "src/calculator/sibling.py")
        assert "from .fight.rates import RATES" in sibling
        assert "from .widget import keep" in sibling

    def test_an_attribute_read_is_repointed_and_its_module_imported(self, tree):
        extract_modules.write_plan(_plan(write=True))
        reader = _written(tree, "tests/test_widget.py")
        assert 'turning.turn(Widget("a"))' in reader
        assert "from src.calculator.fight import turning" in reader

    def test_a_monkeypatch_target_string_is_repointed(self, tree):
        extract_modules.write_plan(_plan(write=True))
        reader = _written(tree, "tests/test_widget.py")
        assert '"src.calculator.fight.turning.turn"' in reader

    def test_an_added_import_lands_where_isort_sorts_it(self, tree):
        """In front of the import it precedes, and in order among its own."""
        extract_modules.write_plan(_plan(write=True))
        reader = _written(tree, "tests/test_widget.py").split("\n")
        assert reader.index("from src.calculator.fight import turning") < reader.index(
            "from src.calculator.widget import keep"
        )
        quoted = _written(tree, "src/calculator/quoted.py")
        assert "from src.calculator.fight import turning, wheel" in quoted

    def test_a_quoted_annotation_of_a_moved_name_is_repointed(self, tree):
        extract_modules.write_plan(_plan(write=True))
        reader = _written(tree, "src/calculator/quoted.py")
        assert 'def spin(w: "wheel.Widget")' in reader
        assert "from src.calculator.fight import turning, wheel" in reader

    def test_a_deferred_import_goes_stale_on_its_own_scope(self, tree):
        """The module-level alias stays live on `widget.keep`; the inner one does not."""
        extract_modules.write_plan(_plan(write=True))
        reader = _written(tree, "src/calculator/quoted.py")
        assert "import widget as inner" not in reader
        assert "from src.calculator import widget" in reader

    def test_a_quoted_annotation_of_a_kept_name_keeps_the_import(self, tree):
        extract_modules.write_plan(_plan(write=True))
        reader = _written(tree, "src/calculator/quoted_only.py")
        assert "from src.calculator import widget" in reader
        assert 'def hold(w: "widget.STAY")' in reader

    def test_an_import_marked_noqa_is_held_for_its_side_effect(self, tree):
        extract_modules.write_plan(_plan(write=True))
        reader = _written(tree, "src/calculator/quoted_only.py")
        assert "import widget as registered  # noqa: F401" in reader

    def test_an_import_of_the_source_no_read_is_left_for_is_dropped(self, tree):
        extract_modules.write_plan(_plan(write=True))
        reader = _written(tree, "tests/test_widget.py")
        assert "from src.calculator import widget" not in reader
        assert "from src.calculator.fight import turning" in reader

    def test_a_string_that_merely_contains_the_name_is_untouched(self, tree):
        extract_modules.write_plan(_plan(write=True))
        reader = _written(tree, "tests/test_widget.py")
        assert '"src.calculator.widget.turn is documented here"' in reader

    def test_every_rewritten_site_is_reported(self, tree):
        rewrites = _plan().rewrites
        assert set(rewrites) == {
            "src/calculator/quoted.py",
            "src/calculator/sibling.py",
            "tests/test_widget.py",
        }
        assert len(rewrites["tests/test_widget.py"]) == 5


class TestCheckedInAssignments:
    """``scripts/assignments/`` against the tree it records."""

    def test_every_module_an_assignment_declares_exists_on_disk(self) -> None:
        """A record naming a file the tree does not hold is a record nobody can read.

        The mapping is reviewable rather than replayable (post-run renames live
        in each file's ``decisions``), so the path is what still has to be true.
        """
        root = Path(__file__).resolve().parent.parent
        missing = [
            f"{assignment.name}: {module['path']}"
            for assignment in sorted((root / "scripts" / "assignments").glob("*.json"))
            for module in json.loads(assignment.read_text(encoding="utf-8")).get(
                "modules", ()
            )
            if not (root / module["path"]).exists()
        ]
        assert missing == []


class TestCommandLine:
    """The two modes, through ``main``."""

    def test_check_prints_the_plan_and_writes_nothing(self, tree, capsys):
        path = tree / "assignment.json"
        path.write_text(json.dumps(ASSIGNMENT), encoding="utf-8")
        before = _written(tree, "src/calculator/widget.py")
        assert extract_modules.main([str(path)]) == 0
        assert "moving 4 units into 3 modules" in capsys.readouterr().out
        assert _written(tree, "src/calculator/widget.py") == before
        assert not (tree / "src/calculator/fight").exists()

    def test_a_refusal_exits_one(self, tree, capsys):
        path = tree / "assignment.json"
        broken = dict(ASSIGNMENT) | {
            "modules": [
                {
                    "path": "src/calculator/fight/a.py",
                    "docstring": "a.",
                    "defs": ["turn"],
                }
            ]
        }
        path.write_text(json.dumps(broken), encoding="utf-8")
        assert extract_modules.main([str(path)]) == 1
        assert "cycle" in capsys.readouterr().err
