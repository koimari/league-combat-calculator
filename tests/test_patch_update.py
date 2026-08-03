"""Tests for the patch-day audit helpers in scripts/patch_update.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from patch_update import (
    item_source_lines,
    drop_noise,
    is_numeric_diff,
    leaf_diffs,
    name_delta,
)


class TestLeafDiffs:
    def test_changed_leaf_reports_path_old_new(self) -> None:
        old = {"stats": {"ad": 60, "hp": 600}}
        new = {"stats": {"ad": 62, "hp": 600}}
        assert list(leaf_diffs(old, new)) == [(".stats.ad", 60, 62)]

    def test_nested_list_changes_include_index(self) -> None:
        old = {"values": [10, 20, 30]}
        new = {"values": [10, 25, 30]}
        assert list(leaf_diffs(old, new)) == [(".values[1]", 20, 25)]

    def test_list_length_change_reported_and_common_prefix_compared(self) -> None:
        old = {"builds": [1, 2, 3]}
        new = {"builds": [1, 9]}
        diffs = list(leaf_diffs(old, new))
        assert (".builds(len)", 3, 2) in diffs
        assert (".builds[1]", 2, 9) in diffs

    def test_added_and_missing_keys_diff_against_none(self) -> None:
        assert list(leaf_diffs({}, {"new": 5})) == [(".new", None, 5)]
        assert list(leaf_diffs({"old": 5}, {})) == [(".old", 5, None)]

    def test_identical_structures_yield_nothing(self) -> None:
        data = {"a": [1, {"b": "x"}]}
        assert list(leaf_diffs(data, data)) == []


class TestDropNoise:
    def test_icon_and_patch_stamp_paths_are_dropped(self) -> None:
        diffs = [
            (".icon", "a.png", "b.png"),
            (".patchLastChanged", "26.13", "26.14"),
            (".abilities.Q[0].icon", "a", "b"),
            (".stats.ad", 60, 62),
        ]
        assert drop_noise(diffs) == [(".stats.ad", 60, 62)]

    def test_price_fields_are_dropped(self) -> None:
        diffs = [(".shop.prices.total", 3000, 3100), (".stats.ap", 70, 60)]
        assert drop_noise(diffs) == [(".stats.ap", 70, 60)]


class TestIsNumericDiff:
    def test_number_leaves_are_numeric(self) -> None:
        assert is_numeric_diff((".x", 60, 58))
        assert is_numeric_diff((".x", 87.5, 70))
        assert is_numeric_diff((".x", None, 5))

    def test_numeric_strings_are_numeric(self) -> None:
        assert is_numeric_diff((".width", "110", "220"))

    def test_prose_leaves_are_not_numeric(self) -> None:
        assert not is_numeric_diff((".notes", "old text 40", "new text 30"))

    def test_length_markers_are_numeric(self) -> None:
        assert is_numeric_diff((".buildsInto(len)", 32, 33))


class TestNameDelta:
    def test_reports_added_and_removed_names(self) -> None:
        old = {"Kindlegem": {}, "Fiendish Codex": {}, "Old Relic": {}}
        new = {"Kindlegem": {}, "Fiendish Codex": {}, "New Toy": {}}
        added, removed = name_delta(old, new)
        assert added == ["New Toy"]
        assert removed == ["Old Relic"]

    def test_no_changes_gives_empty_lists(self) -> None:
        assert name_delta({"A": {}}, {"A": {}}) == ([], [])


class TestItemSourceGate:
    """Patch day stops when the cache loses source coverage."""

    @staticmethod
    def _item(name, effect_name, branch_texts, riot=""):
        return {
            "name": name,
            "riotDescription": riot,
            "passives": [{"name": effect_name, "branches": list(branch_texts)}],
            "active": [],
        }

    def test_unchanged_cache_passes(self) -> None:
        items = {"Cull": self._item("Cull", "Reap", ["gold", "payout"])}
        lines, ok = item_source_lines(items, items)

        assert ok is True
        assert any("accounted for" in line for line in lines)

    def test_lost_branch_blocks_the_patch(self) -> None:
        old = {"Cull": self._item("Cull", "Reap", ["gold", "payout"])}
        new = {"Cull": self._item("Cull", "Reap", ["gold"])}
        lines, ok = item_source_lines(old, new)

        assert ok is False
        assert any("BLOCKING" in line and "Reap" in line for line in lines)

    def test_item_leaving_the_shop_is_the_shop_delta_not_a_loss(self) -> None:
        old = {"Cull": self._item("Cull", "Reap", ["gold", "payout"])}
        lines, ok = item_source_lines(old, {})

        assert ok is True
        assert not any("Reap" in line for line in lines)

    def test_unreviewed_source_conflict_blocks_the_patch(self) -> None:
        items = {
            "Cull": self._item(
                "Cull", "Reap", ["gold"], riot="<passive>Unrecorded Reaping</passive>"
            )
        }
        lines, ok = item_source_lines(items, items)

        assert ok is False
        assert any("Unrecorded Reaping" in line for line in lines)

    def test_reviewed_removal_releases_the_patch(self, monkeypatch) -> None:
        from src.calculator import item_source

        monkeypatch.setitem(
            item_source.APPROVED_BRANCH_REMOVALS,
            "Cull / passive Reap",
            "Patch 26.16 folded the payout into the gold branch.",
        )
        old = {"Cull": self._item("Cull", "Reap", ["gold", "payout"])}
        new = {"Cull": self._item("Cull", "Reap", ["gold"])}
        lines, ok = item_source_lines(old, new)

        assert ok is True
        assert any("approved" in line for line in lines)
