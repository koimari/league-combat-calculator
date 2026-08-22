"""``TESTING`` is one session-wide answer that a test borrows, never assigns.

``src.app.app`` is a module-level singleton, so the flag is process-global: an
assignment without a restore decides it for every later file in the session,
which is how ``test_app.py``'s rate-limit tests came to depend on a leak from
whichever file ran before them.  ``tests/conftest.py`` holds it on for the
session and ``tests/app_config.py`` is the borrow; ``monkeypatch.setitem`` is
the other restoring form.  A bare subscript assignment is neither.
"""

import ast
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent

sys.path.insert(0, str(TESTS.parent / "scripts"))

import testing_flag_codemod  # noqa: E402  (path set above)

#: The borrow's own home, where the assignment is the implementation.
EXEMPT = frozenset({"app_config.py"})


def _assignments(tree: ast.AST) -> list[int]:
    """Lines assigning to a ``config["TESTING"]`` subscript."""
    return [
        node.lineno
        for node in ast.walk(tree)
        for target in getattr(node, "targets", ())
        if isinstance(target, ast.Subscript)
        and isinstance(target.slice, ast.Constant)
        and target.slice.value == "TESTING"
    ]


def test_no_test_assigns_the_shared_testing_flag():
    """Borrow it through ``app_config`` or ``monkeypatch.setitem`` instead."""
    offenders = [
        f"{path.name}:{line}"
        for path in sorted(TESTS.rglob("*.py"))
        if path.name not in EXEMPT
        for line in _assignments(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert offenders == []


def test_the_scan_finds_a_planted_assignment(tmp_path):
    """The gate is driven by a real walk, not by an empty one."""
    planted = tmp_path / "planted.py"
    planted.write_text('app.config["TESTING"] = True\n', encoding="utf-8")
    assert _assignments(ast.parse(planted.read_text(encoding="utf-8"))) == [1]


def test_the_codemod_keeps_crlf_and_refuses_a_sole_statement():
    """Its two hazards on this tree: the line endings, and emptying a block."""
    source = 'def f():\r\n    app.config["TESTING"] = True\r\n    return 1\r\n'
    deletable, refused = testing_flag_codemod.removable(source)
    assert (deletable, refused) == ([2], [])
    assert testing_flag_codemod.rewrite(source, deletable) == (
        "def f():\r\n    return 1\r\n"
    )
    sole = 'with x:\n    app.config["TESTING"] = True\n'
    assert testing_flag_codemod.removable(sole) == ([], [2])


def test_the_session_holds_the_flag_on():
    """The autouse session fixture, observed rather than described."""
    from src import app as app_module

    assert app_module.app.config["TESTING"] is True
