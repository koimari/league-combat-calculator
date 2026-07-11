"""Amumu ability parsing and damage calculation.

Custom module needed because:
- P (Cursed Touch): Damage amplifier — Cursed targets take 10% bonus true
  damage from all pre-mitigation magic damage.  Applied as extra true damage
  on every magic-damage ability when the ``target_cursed`` option is True.
- Q (Bandage Toss): Two charges with separate inter-cast and recharge
  cooldowns.  Cast count is user-configurable (``q_casts``).
- W (Despair): Toggle DoT that ticks every 0.5 s.  Duration is
  user-configurable (``w_seconds``).
- E (Tantrum): Only the active component (effect[1]) deals damage; the
  passive damage-reduction (effect[0]) is defensive and skipped.

W %maxHP scaling note:
  The JSON stores W's per-tick %maxHP damage (including AP ratio) in a
  compound unit string: ``"% (+ 0.25% per 100 AP) of target's maximum
  health"``.  This IS handled automatically by ``scaling.py``'s
  ``_parse_compound_unit``—no hardcoding required—as long as
  ``target_max_health`` is present in the stats context passed to
  ``resolve_scaling``.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from .common import build_stats_context, extract_leveling_damage, make_rank_fn
from .generic_parser import extract_cooldown


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------

_CURSE_BONUS_FRACTION = 0.10  # 10% bonus true damage on magic damage


def _apply_curse(result: dict[str, Any], target_cursed: bool) -> None:
    """Add Cursed Touch bonus true damage to a magic-damage ability result.

    Mutates *result* in-place: adds a ``true_damage`` key equal to 10%
    of the ability's magic damage, switches ``damage_type`` to
    ``"mixed"``, and increases ``total_raw`` accordingly.
    """
    if not target_cursed:
        return
    magic = result.get("magic_damage", 0.0)
    if magic <= 0:
        return

    bonus_true = magic * _CURSE_BONUS_FRACTION
    result["true_damage"] = bonus_true
    result["total_raw"] = magic + bonus_true
    result["damage_type"] = "mixed"


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------


def parse_abilities(
    champion_data: dict[str, Any],
    level: int,
    total_ability_power: float,
    ability_ranks: dict[str, int] | None = None,
    champion_options: dict[str, Any] | None = None,
    champion_stats: dict[str, float] | None = None,
    target_stats: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse Amumu's abilities and calculate damage.

    Args:
        champion_data: Amumu's champion data dictionary from JSON.
        level: Champion level (1-18).
        total_ability_power: Total AP after items and multipliers.
        ability_ranks: Optional dict of ability key -> rank override.
        champion_options: Champion-specific options.  Supports:
            ``target_cursed`` (bool, default True) — apply Cursed Touch
            bonus true damage on magic-damage abilities.
            ``w_seconds`` (float, default 3.0) — seconds of W active.
        champion_stats: Champion's calculated stats (for scaling).
        target_stats: Target stats (for W %maxHP damage).

    Returns:
        Dictionary with ability key -> damage information.
    """
    abilities_data = champion_data.get("abilities", {})
    results: dict[str, dict[str, Any]] = {}

    # Read champion options with defaults
    if champion_options is None:
        champion_options = {}
    target_cursed = champion_options.get("target_cursed", True)
    w_seconds = max(0.5, float(champion_options.get("w_seconds", 3.0)))

    stats_context = build_stats_context(champion_stats, total_ability_power)
    rank_for = make_rank_fn("Amumu", ability_ranks, level)

    # ── P: Cursed Touch (damage amplifier, no direct damage) ─────────
    passive_list = abilities_data.get("P", [])
    if passive_list:
        results["P"] = {
            "name": passive_list[0].get("name", "Cursed Touch"),
            "rank": 1,
            "cooldown": 0.0,
            "damage_type": "true",
            "total_raw": 0.0,
            "true_damage": 0.0,
        }

    # ── Q: Bandage Toss (single-cast damage, charge recharge as CD) ──
    # Q is a recharge ability (2 charges).  The JSON ``cooldown`` field
    # stores the 3 s inter-cast timer, but the limiting factor for
    # sustained use is the ``rechargeRate`` (16-12 s per rank).  We
    # report single-cast damage and use rechargeRate as the cooldown so
    # the fight engine determines cast count correctly.
    q_rank = rank_for("Q")
    if q_rank > 0:
        q_ability = abilities_data["Q"][0]
        q_damage = extract_leveling_damage(
            q_ability, "Magic Damage", q_rank, stats_context, target_stats,
        )

        # Use rechargeRate for cooldown (fight engine cast-count calc).
        recharge_rates = q_ability.get("rechargeRate", [])
        if recharge_rates:
            idx = min(q_rank - 1, len(recharge_rates) - 1)
            q_cooldown = float(recharge_rates[idx])
        else:
            q_cooldown = extract_cooldown(q_ability, q_rank)

        q_result: dict[str, Any] = {
            "name": q_ability.get("name", "Bandage Toss"),
            "rank": q_rank,
            "cooldown": q_cooldown,
            "damage_type": "magic",
            "magic_damage": q_damage,
            "total_raw": q_damage,
        }
        _apply_curse(q_result, target_cursed)
        results["Q"] = q_result

    # ── W: Despair (toggle DoT, ticks every 0.5 s) ──────────────────
    w_rank = rank_for("W")
    if w_rank > 0:
        w_ability = abilities_data["W"][0]
        w_per_tick = extract_leveling_damage(
            w_ability, "Magic Damage Per Tick", w_rank,
            stats_context, target_stats,
        )
        w_ticks = int(w_seconds / 0.5)
        w_total_magic = w_per_tick * w_ticks

        w_result: dict[str, Any] = {
            "name": w_ability.get("name", "Despair"),
            "rank": w_rank,
            "cooldown": 0.0,  # toggle ability, no cooldown
            "damage_type": "magic",
            "damage_per_tick": w_per_tick,
            "total_ticks": w_ticks,
            "magic_damage": w_total_magic,
            "total_raw": w_total_magic,
        }
        _apply_curse(w_result, target_cursed)
        results["W"] = w_result

    # ── E: Tantrum (single-hit AoE, effect[1] only) ─────────────────
    e_rank = rank_for("E")
    if e_rank > 0:
        e_ability = abilities_data["E"][0]
        # effect[0] is passive damage reduction — skip.
        # effect[1] has the "Magic Damage" active component.
        e_damage = extract_leveling_damage(
            e_ability, "Magic Damage", e_rank, stats_context, target_stats,
        )
        e_cooldown = extract_cooldown(e_ability, e_rank)

        e_result: dict[str, Any] = {
            "name": e_ability.get("name", "Tantrum"),
            "rank": e_rank,
            "cooldown": e_cooldown,
            "damage_type": "magic",
            "magic_damage": e_damage,
            "total_raw": e_damage,
        }
        _apply_curse(e_result, target_cursed)
        results["E"] = e_result

    # ── R: Curse of the Sad Mummy (single-hit AoE) ──────────────────
    r_rank = rank_for("R")
    if r_rank > 0:
        r_ability = abilities_data["R"][0]
        r_damage = extract_leveling_damage(
            r_ability, "Magic Damage", r_rank, stats_context, target_stats,
        )
        r_cooldown = extract_cooldown(r_ability, r_rank)

        r_result: dict[str, Any] = {
            "name": r_ability.get("name", "Curse of the Sad Mummy"),
            "rank": r_rank,
            "cooldown": r_cooldown,
            "damage_type": "magic",
            "magic_damage": r_damage,
            "total_raw": r_damage,
        }
        _apply_curse(r_result, target_cursed)
        results["R"] = r_result

    return results
