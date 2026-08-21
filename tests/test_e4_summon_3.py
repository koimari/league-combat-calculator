"""E4 summoned-unit damage — batch 3 (traps).

One test per champion drives an ``/api/calculate`` fight at level 18
(basic abilities rank 5, ultimates rank 3, no items, target armor/MR 0
so post-mitigation damage equals the raw wiki values) and asserts the
sourced trap/summon damage.  Every number traces to
``data/champions.json`` leveling rows or the pinned module constants
that hardcode sourced wiki pet values, following the E2/E3 test
conventions.

Summons under test (E4-3 worklist ``data/worklists/e4-partition.json``):

- Teemo   R  Noxious Trap      shroom detonation DoT (E2 ticks) x r_shrooms + slow
- Shaco   W  Jack in the Box   sprung-box attack volley: up to 10 shots at 0.5s
                                (single-target "Increased Damage" row)
- Nidalee W  Bushwhack         trap DoT (E2 ticks) x w_traps (Pounce untouched)
- Caitlyn W  Yordle Snap Trap  zero-damage utility row; the trap's damage is the
                                trap Headshot priced by P (w_traps headshots)
- Jhin    E  Captive Audience  Lotus Trap damage x e_traps (2nd trap at 65%)
- Zac     —  skipped           R (Let's Bounce!) is a self-movement rework, not
                                a pet; its reviewed bounce pricing is unchanged
"""

import json
import re
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_CACHE_KEY_BY_DISPLAY = {
    str(value.get("name", "")): key
    for key, value in _CHAMPION_DATA.items()
    if isinstance(value, dict) and str(value.get("name", "")).strip()
}
_FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
# Nidalee is a transformation kit: manual rank allocations are unavailable,
# so its fight uses the level-18 skill-order ranks.
_NO_RANKS_CHAMPIONS = {"Nidalee"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fight(
    champion: str,
    *,
    options: dict | None = None,
    ranks: dict | None = None,
    duration: float = 10.0,
) -> dict:
    """One /api/calculate fight at level 18, rank 5 / R rank 3, no items."""
    payload = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": "mid",
        "ability_ranks": ranks,
        "champion_options": options or {},
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": False,
        "target_health": 2000,
        "target_armor": 0,
        "target_mr": 0,
    }
    if champion in _NO_RANKS_CHAMPIONS:
        payload["ability_ranks"] = None
    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _leveling(champion: str, slot: str, attribute: str) -> dict:
    """Return one leveling entry from data/champions.json, failing loudly."""
    ability = _CHAMPION_DATA[_CACHE_KEY_BY_DISPLAY[champion]]["abilities"][slot][0]
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                return leveling
    raise AssertionError(f"{champion} {slot} has no leveling attribute {attribute!r}")


def _normalize_unit(unit: str) -> str:
    return re.sub(r"\s+", " ", unit.strip())


def _resolve(
    champion: str,
    slot: str,
    attribute: str,
    rank: int,
    stats: dict,
    target_max_health: float,
) -> float:
    """Sum one leveling entry at rank against the fight's own stats.

    Handles exactly the unit vocabularies the tested abilities use; an
    unexpected unit fails loudly so the test cannot silently pass with a
    dropped term.
    """
    total = 0.0
    for modifier in _leveling(champion, slot, attribute).get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        idx = min(max(rank, 1) - 1, len(values) - 1)
        value = float(values[idx])
        unit = _normalize_unit(units[idx]) if idx < len(units) else ""
        if unit in ("", "%"):
            total += value
        elif unit == "% AP":
            total += value / 100.0 * float(stats.get("ability_power", 0.0))
        elif unit == "% AD":
            total += value / 100.0 * float(stats.get("attack_damage", 0.0))
        elif unit == "% bonus AD":
            total += value / 100.0 * float(stats.get("bonus_attack_damage", 0.0))
        elif unit == "% of target's maximum health":
            total += value / 100.0 * target_max_health
        elif unit == "% per 100 AP":
            total += value * float(stats.get("ability_power", 0.0)) / 100.0
        else:
            raise AssertionError(
                f"unhandled unit {unit!r} for {champion} {slot} {attribute}"
            )
    return total


def _slot_events(data: dict, slot: str) -> list[dict]:
    return [
        event
        for event in data["damage_events"]
        if event.get("source") == slot and event.get("damage", 0.0) > 0
    ]


# ---------------------------------------------------------------------------
# Teemo — R Noxious Trap (shroom detonation DoT + slow)
# ---------------------------------------------------------------------------


class TestTeemoNoxiousTrap:
    """R rank 3: "Magic Damage per Tick" 112.5, "Total Magic Damage" 450
    -> one shroom detonation = 4 ticks at 1s (the E2-3 pricing)."""

    def test_one_detonation_prices_the_full_poison_dot(self) -> None:
        data = _fight("Teemo", ranks=_FULL_RANKS)
        stats = data["champion_stats"]
        per_tick = _resolve(
            "Teemo",
            "R",
            "Magic Damage per Tick",
            3,
            stats,
            data["target_effective_max_health"],
        )
        row = data["breakdown"]["R"]
        assert row["casts"] == 1
        assert row["total_damage"] == pytest.approx(per_tick * 4)
        events = _slot_events(data, "R")
        assert len(events) == 4
        assert all(event["damage"] == pytest.approx(per_tick) for event in events)

    def test_r_shrooms_option_prices_sequential_detonations(self) -> None:
        """Each shroom detonation prices its own full DoT (the wiki note:
        multiple shrooms only refresh the poison, they never stack)."""
        data = _fight("Teemo", ranks=_FULL_RANKS, options={"r_shrooms": 2})
        stats = data["champion_stats"]
        per_tick = _resolve(
            "Teemo",
            "R",
            "Magic Damage per Tick",
            3,
            stats,
            data["target_effective_max_health"],
        )
        row = data["breakdown"]["R"]
        assert row["total_damage"] == pytest.approx(per_tick * 4 * 2)
        events = _slot_events(data, "R")
        assert len(events) == 8
        # The sourced slow is reported on the row (utility, not damage).
        assert "slow" in row.get("detail", "").lower()


# ---------------------------------------------------------------------------
# Shaco — W Jack in the Box (sprung-box attack volley)
# ---------------------------------------------------------------------------


class TestShacoJackInTheBox:
    """W rank 5: "Increased Damage" 85 (+18% AP); the sprung box fires
    every 0.5s for its 5-second lifetime == 10 attacks against one
    target (the fight model's duel), so the default volley is 850."""

    def test_full_volley_prices_ten_sourced_shots(self) -> None:
        data = _fight("Shaco", ranks=_FULL_RANKS)
        stats = data["champion_stats"]
        per_shot = _resolve(
            "Shaco",
            "W",
            "Increased Damage",
            5,
            stats,
            data["target_effective_max_health"],
        )
        row = data["breakdown"]["W"]
        assert row["casts"] == 1
        assert row["total_damage"] == pytest.approx(per_shot * 10)
        events = _slot_events(data, "W")
        assert len(events) == 10
        assert all(event["damage"] == pytest.approx(per_shot) for event in events)

    def test_w_box_attacks_option_controls_uptime(self) -> None:
        """The box fires at 0.5s intervals; 4 attacks model the target
        leaving the box's range mid-fight."""
        data = _fight("Shaco", ranks=_FULL_RANKS, options={"w_box_attacks": 4})
        stats = data["champion_stats"]
        per_shot = _resolve(
            "Shaco",
            "W",
            "Increased Damage",
            5,
            stats,
            data["target_effective_max_health"],
        )
        row = data["breakdown"]["W"]
        assert row["total_damage"] == pytest.approx(per_shot * 4)
        assert len(_slot_events(data, "W")) == 4


# ---------------------------------------------------------------------------
# Nidalee — W Bushwhack (trap DoT; Pounce untouched)
# ---------------------------------------------------------------------------


class TestNidaleeBushwhack:
    """W (level-18 rank 5): "Magic Damage Per Tick" 50 (+5% AP), "Total
    Magic Damage" 200 (+20% AP) -> 4 ticks at 1s (the E2-3 pricing)."""

    def test_one_trap_prices_the_full_dot(self) -> None:
        data = _fight("Nidalee")
        stats = data["champion_stats"]
        per_tick = _resolve(
            "Nidalee",
            "W",
            "Magic Damage Per Tick",
            5,
            stats,
            data["target_effective_max_health"],
        )
        row = data["breakdown"]["W"]
        casts = max(1, int(row.get("casts", 1)))
        assert row["total_damage"] == pytest.approx(per_tick * 4 * casts)
        assert len(_slot_events(data, "W")) == 4 * casts

    def test_w_traps_option_prices_additional_detonations(self) -> None:
        """Pre-placed Bushwhack traps each deal their own full DoT."""
        data = _fight("Nidalee", options={"w_traps": 2})
        stats = data["champion_stats"]
        per_tick = _resolve(
            "Nidalee",
            "W",
            "Magic Damage Per Tick",
            5,
            stats,
            data["target_effective_max_health"],
        )
        row = data["breakdown"]["W"]
        casts = max(1, int(row.get("casts", 1)))
        assert row["total_damage"] == pytest.approx(per_tick * 4 * 2 * casts)
        assert len(_slot_events(data, "W")) == 8 * casts

    def test_pounce_variant_stays_a_single_hit(self) -> None:
        """The cougar Pounce variant must remain one hit per cast (the
        E2 boundary): 6s cooldown -> two casts in 10s."""
        data = _fight("Nidalee", options={"w_variant": 1})
        row = data["breakdown"]["W"]
        casts = max(1, int(row.get("casts", 1)))
        assert row["total_damage"] == pytest.approx(190.0 * casts)
        assert len(_slot_events(data, "W")) == casts


# ---------------------------------------------------------------------------
# Caitlyn — W Yordle Snap Trap (zero-damage summon row + trap headshot)
# ---------------------------------------------------------------------------


class TestCaitlynYordleSnapTrap:
    """W deals no direct damage: the trap roots/reveals, and its damage
    contribution is the trap Headshot priced by the passive row with W's
    "Headshot Damage Increase" (35-215 + 30% bonus AD by rank)."""

    def test_w_row_is_zero_damage_utility(self) -> None:
        data = _fight("Caitlyn", ranks=_FULL_RANKS)
        row = data["breakdown"]["W"]
        assert row["total_damage"] == 0.0
        assert "trap" in row.get("detail", "").lower()

    def test_trap_headshot_carries_w_increase(self) -> None:
        """Default w_traps=1: the passive prices 2 forced headshots from E
        plus 1 trap headshot (swing + total-AD rider + W increase)."""
        data = _fight("Caitlyn", ranks=_FULL_RANKS)
        stats = data["champion_stats"]
        ad = float(stats.get("attack_damage", 0.0))
        trap_increase = _resolve(
            "Caitlyn",
            "W",
            "Headshot Damage Increase",
            5,
            stats,
            data["target_effective_max_health"],
        )
        swing = ad  # no crit chance, no bonus crit damage
        rider = ad  # level 18 -> 100% total-AD Headshot ratio
        # 3 forced headshots: 2 E-granted (E rank-5 cooldown 8s -> two
        # casts in 10s) + 1 trap; the rider applies to the 2 E-granted
        # shots, and the trap headshot carries W's damage increase.
        row = data["breakdown"]["passive"]
        assert row["total_damage"] == pytest.approx(
            swing * 3 + rider * 2 + (rider + trap_increase)
        )

    def test_w_traps_option_counts_trap_headshots(self) -> None:
        """Each extra sprung trap adds one trap Headshot: a forced swing
        plus the rider plus W's damage increase."""
        base = _fight("Caitlyn", ranks=_FULL_RANKS)
        extra = _fight("Caitlyn", ranks=_FULL_RANKS, options={"w_traps": 2})
        stats = extra["champion_stats"]
        ad = float(stats.get("attack_damage", 0.0))
        trap_increase = _resolve(
            "Caitlyn",
            "W",
            "Headshot Damage Increase",
            5,
            stats,
            extra["target_effective_max_health"],
        )
        delta = ad + ad + trap_increase  # one more swing + rider + W increase
        assert extra["breakdown"]["passive"]["total_damage"] - base["breakdown"][
            "passive"
        ]["total_damage"] == pytest.approx(delta)

    def test_w_traps_zero_removes_the_trap_headshot(self) -> None:
        """w_traps=0 models a fight with no sprung trap: no W row and no
        trap headshot in the passive."""
        data = _fight("Caitlyn", ranks=_FULL_RANKS, options={"w_traps": 0})
        assert "W" not in data["breakdown"]
        assert "0 trap" in data["breakdown"]["passive"].get("detail", "")


# ---------------------------------------------------------------------------
# Jhin — E Captive Audience (Lotus Trap detonation)
# ---------------------------------------------------------------------------


class TestJhinCaptiveAudience:
    """E rank 5: "Magic Damage" 260 (+120% AD + 100% AP) per Lotus Trap;
    a champion struck by another Lotus Trap within 1s takes the 65%
    "Reduced Damage" row (169 + 78% AD + 65% AP).  Jhin's Whisper AD is
    an engine-applied ``stat_buff``, so the parse-time ability amounts
    use the PRE-buff AD (``calculate_total_stats``) — the same context
    the module resolves against."""

    @staticmethod
    def _parse_stats() -> dict:
        return calculate_total_stats(get_champion("Jhin"), 18, [])

    def test_one_trap_prices_the_full_detonation(self) -> None:
        data = _fight("Jhin", ranks=_FULL_RANKS)
        stats = self._parse_stats()
        full = _resolve(
            "Jhin", "E", "Magic Damage", 5, stats, data["target_effective_max_health"]
        )
        row = data["breakdown"]["E"]
        casts = max(1, int(row.get("casts", 1)))
        assert row["total_damage"] == pytest.approx(full * casts)
        assert len(_slot_events(data, "E")) == casts

    def test_e_traps_option_prices_the_reduced_second_trap(self) -> None:
        """e_traps=2: the first trap full, the second at the 65% reduced
        row (the charge cap is 2)."""
        data = _fight("Jhin", ranks=_FULL_RANKS, options={"e_traps": 2})
        stats = self._parse_stats()
        full = _resolve(
            "Jhin", "E", "Magic Damage", 5, stats, data["target_effective_max_health"]
        )
        reduced = _resolve(
            "Jhin", "E", "Reduced Damage", 5, stats, data["target_effective_max_health"]
        )
        row = data["breakdown"]["E"]
        casts = max(1, int(row.get("casts", 1)))
        assert row["total_damage"] == pytest.approx((full + reduced) * casts)
        events = _slot_events(data, "E")
        assert len(events) == 2 * casts


# ---------------------------------------------------------------------------
# Zac — boundary: R rework is not a pet
# ---------------------------------------------------------------------------


class TestZacBoundary:
    """The E4-3 worklist skips Zac: R (Let's Bounce!) is the
    self-movement rework, not a summoned unit, so the reviewed bounce
    pricing is unchanged (full + 3 reduced bounces == the wiki Total)."""

    def test_r_keeps_the_reviewed_bounce_pricing(self) -> None:
        data = _fight("Zac", ranks=_FULL_RANKS)
        stats = data["champion_stats"]
        full = _resolve(
            "Zac",
            "R",
            "Magic Damage Per Hit",
            3,
            stats,
            data["target_effective_max_health"],
        )
        reduced = _resolve(
            "Zac",
            "R",
            "Reduced Damage Per Hit",
            3,
            stats,
            data["target_effective_max_health"],
        )
        row = data["breakdown"]["R"]
        assert row["total_damage"] == pytest.approx(full + 3 * reduced)
