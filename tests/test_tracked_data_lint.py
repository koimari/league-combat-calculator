"""``scripts/tracked_data_lint.py``: the tracked data surface answers for itself.

Both rules are pinned at zero over the real tree, and each has a negative that
builds its dirty world in ``tmp_path`` rather than in the checkout, so a
parallel worker's scan cannot see it.

The reader set is derived from the tree, never listed here: a new receipt is
covered the moment a regenerator or a test names it, and a receipt whose last
reader goes fails on the commit that removes the reader rather than years
later.
"""

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import tracked_data_lint as lint

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(name="repo")
def _repo(tmp_path):
    """A throwaway git repo with the two scanned roots and one reader root."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    for name in ("docs/receipts", "data/atoms", "scripts", "src", "tests"):
        (tmp_path / name).mkdir(parents=True)

    def commit(paths):
        for name, text in paths.items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    return tmp_path, commit


class TestTheTreeIsClean:
    """The standing state, which is what the gate protects."""

    def test_no_tracked_receipt_is_unread(self):
        assert lint.orphans(ROOT) == ()

    def test_no_tracked_json_holds_a_machine_path(self):
        assert lint.machine_paths(ROOT) == ()

    def test_the_cli_passes_on_the_real_tree(self):
        assert lint.main([]) == 0


class TestTheReaderSetIsDerived:
    """What counts as a reader, proved on a tree the test builds."""

    def test_a_receipt_a_test_names_is_covered(self, repo):
        root, commit = repo
        commit(
            {
                "docs/receipts/kept.json": "{}",
                "tests/test_reader.py": 'PATH = "kept.json"\n',
            }
        )
        assert lint.orphans(root) == ()

    def test_a_receipt_nothing_names_is_reported(self, repo):
        root, commit = repo
        commit({"docs/receipts/orphan.json": "{}"})
        assert lint.orphans(root) == ("docs/receipts/orphan.json",)

    def test_a_glob_covers_the_files_it_matches(self, repo):
        root, commit = repo
        commit(
            {
                "data/atoms/ahri.atoms.json": "{}",
                "data/atoms/zed.atoms.json": "{}",
                "scripts/regen.py": 'ATOMS.glob("*.atoms.json")\n',
            }
        )
        assert lint.orphans(root) == ()

    def test_a_directory_scan_is_not_a_reader(self, repo):
        """One ``*.json`` anywhere in the tree would otherwise cover every receipt."""
        root, commit = repo
        commit(
            {
                "docs/receipts/orphan.json": "{}",
                "scripts/scan.py": 'RECEIPTS.glob("*.json")\nTESTS.rglob("*")\n',
            }
        )
        assert lint.orphans(root) == ("docs/receipts/orphan.json",)

    @pytest.mark.parametrize(
        ("pattern", "family"),
        [
            ("*", False),
            ("*.json", False),
            ("docs/receipts/*.json", False),
            ("*.widget.json", True),
            ("sample-Q9-*.json", True),
            ("sample-*-shard-*.json", True),
        ],
    )
    def test_a_glob_counts_only_where_it_pins_a_name(self, pattern, family):
        """The three family shapes, spelled so none of them names a tracked file.

        This file is one of the sources the reader set is derived from, so a
        live family glob here would cover its own receipts and blind the guard
        to the recurrence it exists to catch.
        """
        assert lint.names_a_family(pattern) is family

    def test_the_real_reader_set_cannot_name_a_receipt_that_never_existed(self):
        """The discrimination, measured against the literals the tree holds.

        The negatives above see only the two-line corpus they write, and the
        absent name is generated because a spelled-out one would name itself:
        this file is one of the sources the reader set is derived from.
        """
        readers = lint.Readers.in_tree(ROOT)
        absent = f"docs/receipts/{uuid4()}.json"
        assert not readers.covers(absent)
        assert readers.covers("docs/receipts/campaign-fingerprints.json")

    def test_a_docstring_mention_is_not_a_reader(self, repo):
        """The failure this rule exists for: prose about a corpus nothing opens."""
        root, commit = repo
        commit(
            {
                "docs/receipts/cited.json": "{}",
                "tests/test_prose.py": '"""Once adjudicated by cited.json."""\n',
            }
        )
        assert lint.orphans(root) == ("docs/receipts/cited.json",)

    def test_markdown_under_the_roots_is_not_a_receipt(self, repo):
        """Prose answers to ``prose_lint.py``; this rule owns the JSON."""
        root, commit = repo
        commit({"docs/receipts/notes.md": "# notes\n"})
        assert lint.orphans(root) == ()

    def test_an_untracked_scratch_file_is_out_of_scope(self, repo):
        """A test that writes into ``docs/receipts`` mid-run cannot race the gate."""
        root, commit = repo
        commit({"docs/receipts/kept.json": "{}", "tests/t.py": 'P = "kept.json"\n'})
        (root / "docs/receipts/scratch.json").write_text("{}", encoding="utf-8")
        assert lint.orphans(root) == ()


class TestMachinePaths:
    """Every shape the rule refuses, and the relative path it permits."""

    @pytest.mark.parametrize(
        "value",
        [
            "C:/Users/skywa/AppData/Local/Temp/claude/scratch",
            "C:\\Users\\skywa\\Desktop\\repo",
            "/Users/river/Projects/league-combat-calculator",
            "/home/runner/work/repo",
        ],
    )
    def test_an_absolute_machine_path_is_reported(self, repo, value):
        root, commit = repo
        commit({"docs/receipts/r.json": json.dumps({"scratch": value})})
        assert [hit.split(": ")[0] for hit in lint.machine_paths(root)] == [
            "docs/receipts/r.json"
        ]

    @pytest.mark.parametrize(
        "value",
        [
            "vendor/league-wiki-query/scripts/query_league_wiki.py",
            "<scratch>",
            "data/atoms/items.json",
            "/api/loadout-stats",
        ],
    )
    def test_a_repo_relative_path_is_permitted(self, repo, value):
        root, commit = repo
        commit({"docs/receipts/r.json": json.dumps({"path": value})})
        assert lint.machine_paths(root) == ()

    def test_a_key_is_scanned_as_well_as_a_value(self, repo):
        root, commit = repo
        commit({"docs/receipts/r.json": json.dumps({"/Users/river/x": 1})})
        assert len(lint.machine_paths(root)) == 1

    def test_a_json_file_outside_the_receipt_roots_is_scanned(self, repo):
        """The rule is tree-wide; only the orphan rule is root-scoped."""
        root, commit = repo
        commit({"src/config.json": json.dumps(["/home/runner/work"])})
        assert len(lint.machine_paths(root)) == 1
