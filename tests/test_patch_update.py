"""Tests for the patch-day audit helpers in scripts/patch_update.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from src.calculator import item_effects
from src.calculator.data_fetcher import fetch_item_data

from patch_update import (
    ECONOMICS_TABLES,
    ally_effect_lines,
    economics_lines,
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


class TestAllyEffectLines:
    """D-47: the hand-authored ally table is refresh-inert, so patch day says so."""

    def _shop(self, **moved):
        """A cached shop holding every hand-authored item, some values moved."""
        return {
            name: {
                "name": name,
                "stats": {
                    "abilityPower": {
                        "flat": (
                            moved.get("ap", 0.0) if name == moved.get("item") else 0.0
                        )
                    }
                },
            }
            for name in item_effects.ALLY_ITEM_EFFECTS
        }

    def test_an_unchanged_cached_entry_says_so_and_does_not_block(self) -> None:
        cached = self._shop()
        lines, ok = ally_effect_lines(cached, cached)
        assert ok
        assert lines[-1].endswith("cached entry is unchanged)")

    def test_a_numeric_move_is_flagged_with_the_keys_that_cannot_refresh(self) -> None:
        lines, ok = ally_effect_lines(
            self._shop(), self._shop(item="Abyssal Mask", ap=5.0)
        )
        assert ok, "a moved entry is review, not a release block"
        assert any("Abyssal Mask (NEEDS REVIEW)" in line for line in lines)
        assert any("magic_damage_amp" in line for line in lines)
        assert any(
            "do not\n    refresh" in line or "do not refresh" in line for line in lines
        )

    def test_an_item_that_left_the_shop_blocks(self) -> None:
        """The only branch that can stop a patch: a record pricing nothing."""
        shop = self._shop()
        without = {k: v for k, v in shop.items() if k != "Abyssal Mask"}
        lines, ok = ally_effect_lines(shop, without)
        assert not ok
        assert any(
            "BLOCKING: Abyssal Mask is no longer in the cached shop" in line
            for line in lines
        )
        assert any("** BLOCKING" in line for line in lines)

    def test_every_hand_authored_item_is_audited(self) -> None:
        """No member of the table is exempt from the section."""
        lines, ok = ally_effect_lines(self._shop(), {})
        assert not ok
        blocked = {
            line.split("BLOCKING: ")[1].split(" is no longer")[0]
            for line in lines
            if "BLOCKING: " in line and " is no longer" in line
        }
        assert blocked == set(item_effects.ALLY_ITEM_EFFECTS)


class TestEconomicsLines:
    """The sourced gold table must be current for the cache it prices."""

    def _tables(self):
        import json  # noqa: PLC0415  pylint: disable=import-outside-toplevel

        return json.loads(ECONOMICS_TABLES.read_text(encoding="utf-8"))

    def test_a_current_table_says_so_and_does_not_block(self) -> None:
        tables = self._tables()
        lines, ok = economics_lines(
            tables, fetch_item_data(), tables["patch"]["ddragon"]
        )
        assert ok
        assert lines[-1].endswith("every ordinary item priced)")

    def test_a_table_pinned_to_another_release_blocks(self) -> None:
        lines, ok = economics_lines(self._tables(), fetch_item_data(), "99.1.1")
        assert not ok
        assert any(line.startswith("  BLOCKING: pinned to DDragon ") for line in lines)
        assert lines[-1].startswith("  ** BLOCKING")
