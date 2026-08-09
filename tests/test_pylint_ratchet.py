"""The per-file pylint ratchet, including the red it can reproduce on demand."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pylint_ratchet  # noqa: E402  (path is set above)


class TestCheckRatchet:
    def test_an_unchanged_score_passes(self):
        assert (
            pylint_ratchet.check_ratchet(
                {"scripts/pylint_ratchet.py": 9.0}, score=lambda path: 9.0
            )
            == ()
        )

    def test_a_rising_score_passes(self):
        assert (
            pylint_ratchet.check_ratchet(
                {"scripts/pylint_ratchet.py": 9.0}, score=lambda path: 9.5
            )
            == ()
        )

    def test_a_falling_score_is_reported(self):
        """R-05: the gate's red, on demand, forever — the seam is ``score``."""
        (failure,) = pylint_ratchet.check_ratchet(
            {"scripts/pylint_ratchet.py": 9.5}, score=lambda path: 9.0
        )
        assert "scripts/pylint_ratchet.py" in failure
        assert "9.0000" in failure and "9.5000" in failure

    def test_float_noise_is_not_rot(self):
        assert (
            pylint_ratchet.check_ratchet(
                {"scripts/pylint_ratchet.py": 9.0}, score=lambda path: 9.0 - 1e-12
            )
            == ()
        )

    def test_a_deleted_file_fails_rather_than_disappearing(self):
        """A row that stops being checked must not stop being noticed."""
        (failure,) = pylint_ratchet.check_ratchet(
            {"src/calculator/gone.py": 10.0}, score=lambda path: 10.0
        )
        assert "no longer exists" in failure

    def test_every_baseline_row_is_checked(self):
        seen = []
        pylint_ratchet.check_ratchet(
            {"scripts/pylint_ratchet.py": 0.0, "scripts/golden_snapshot.py": 0.0},
            score=lambda path: seen.append(path) or 10.0,
        )
        assert seen == ["scripts/golden_snapshot.py", "scripts/pylint_ratchet.py"]


class TestFileScore:
    def test_a_clean_module_scores_ten(self, tmp_path):
        """The score is pylint's own, not a re-implementation of its formula."""
        module = tmp_path / "clean_module.py"
        module.write_text(
            '"""A module with nothing to say."""\n\n\n'
            "def answer():\n"
            '    """Return the answer."""\n'
            "    return 42\n",
            encoding="utf-8",
        )
        assert pylint_ratchet.file_score(str(module)) == pytest.approx(10.0)

    def test_a_dirty_module_scores_less(self, tmp_path):
        module = tmp_path / "dirty_module.py"
        module.write_text("import os\nX=1\n", encoding="utf-8")
        assert pylint_ratchet.file_score(str(module)) < 10.0


class TestBaseline:
    def test_the_baseline_comes_from_the_fingerprints_receipt(self):
        """One home for every pinned number; the gate never writes its own."""
        assert pylint_ratchet.FINGERPRINTS_PATH.name == "campaign-fingerprints.json"
        assert isinstance(pylint_ratchet.load_baseline(), dict)

    def test_the_recorded_files_all_exist(self):
        for path in pylint_ratchet.load_baseline():
            assert (REPO_ROOT / path).exists(), path
