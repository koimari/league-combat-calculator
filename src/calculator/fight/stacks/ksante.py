"""K'Sante's Path Maker counter."""

from typing import Any

from ..results import RotationResult
from ..state import FightState
from .account import StackEvent, _resource_ledger, _StackAccount


def _add_ksante_path_maker(state: FightState, rotation: RotationResult) -> None:
    """Add K'Sante's Path Maker W receipts (P3 4A).

    W prices one physical packet (flat + the % max-health term with the
    bonus-armor/MR resist ratios — the game-verified real authored
    effect, now attributed to the CASTER's bonus stats, never the
    target's/totals) and, in All Out, the interpolated true-damage
    range by the charge fraction.  This walk is documentary: it
    receipts the engine-priced parts (amount + part identity) and the
    named fail-closed denials — the R armor/MR-to-AD resist conversion
    and the 65% health threshold are state, the W dash's multi-target
    pass-through prices ONE champion target, the monster damage cap is
    monster-only, and a missing bonus-resist state prices 0 with a
    denial — into an additive ``resource_ledger["w"]`` (kind "w")
    sub-section — the mana account is never replaced — and never
    re-prices any damage.
    """
    if "w_charge" not in (state.champion_options) and "all_out" not in (
        state.champion_options
    ):
        return
    from ...champions.ksante import KSANTE_PATH_MAKER_RULE

    w_entry = state.ability_damages.get("W")
    parts: list[Any] = []
    if isinstance(w_entry, dict):
        raw_parts = w_entry.get("parts")
        if isinstance(raw_parts, (tuple, list)):
            parts = list(raw_parts)
    missing_bonus_state = not (
        isinstance(state.champion_stats, dict)
        and "bonus_armor" in state.champion_stats
        and "bonus_magic_resistance" in state.champion_stats
    )

    account = _StackAccount("w", 0.0, 0, counting=False)
    # The accepted stream: the engine-priced W parts (the All Out
    # physical part is deliberately untimed — the pinned charge-timing
    # asymmetry — so its receipt carries the part identity, time 0.0).
    if parts:
        for index, part in enumerate(parts, start=1):
            amount = float(part.amount)
            offset = part.time_offset
            damage_type = part.damage_type
            event_time = float(offset) if offset is not None else 0.0
            account.add(
                StackEvent(
                    "hit",
                    amount,
                    event_time,
                    f"w_part:{damage_type}",
                    accepted=True,
                    reason="",
                    fields={
                        "event": "w_part",
                        "part_index": index,
                        "damage_type": damage_type,
                        "event_time": round(event_time, 3),
                    },
                )
            )
    else:
        account.add(
            StackEvent(
                "deny",
                0.0,
                0.0,
                "w_unavailable",
                accepted=False,
                reason="w_unavailable — no W cast",
            )
        )

    if missing_bonus_state:
        account.add(
            StackEvent(
                "deny",
                0.0,
                0.0,
                "w_missing_resist_state",
                accepted=False,
                reason="w_missing_resist_state — bonus armor/magic resistance absent; "
                "the resist terms priced at 0 (no invented stats)",
                fields={"event": "missing_resist_state", "event_time": 0.0},
            )
        )
    # Named fail-closed denials for the unsupported state boundaries.
    for source, reason in (
        (
            "r_resist_conversion",
            "unsupported_state:r_resist_conversion — the All Out "
            "armor/MR-to-AD resist conversion is state, never priced",
        ),
        (
            "w_multi_target_dash",
            "unsupported_claim:w_multi_target_dash — the W dash passes "
            "through enemies; the model prices ONE champion target",
        ),
        (
            "w_knockback_stun_control",
            "unsupported_claim:w_knockback_stun_control — the W "
            "knockback/stun control is state/utility, not damage",
        ),
        (
            "w_monster_damage_cap",
            "unsupported_claim:w_monster_damage_cap — the Monster Damage "
            "Cap row is monster-only, never priced for champion fights",
        ),
        (
            "w_health_threshold",
            "unsupported_state:w_health_threshold — the All Out 65% "
            "health threshold is named state, never priced",
        ),
    ):
        account.add(
            StackEvent(
                "deny",
                0.0,
                0.0,
                source,
                accepted=False,
                reason=reason,
                fields={"event": source, "event_time": 0.0},
            )
        )
    account.add(
        StackEvent(
            "deny",
            0.0,
            0.0,
            "w_event_without_identity",
            accepted=False,
            reason="missing_identity",
        )
    )

    _resource_ledger(rotation)["w"] = {
        "contract": "resource_ledger_v1",
        "owner": "main",
        "kind": "w",
        "opening_maximum": 0,
        "opening_current": 0,
        "closing_maximum": 0,
        "closing_current": 0,
        "base_maximum": 0,
        "bonus_maximum": 0,
        "receipts": account.receipts,
        "declaration": KSANTE_PATH_MAKER_RULE.public_receipt(),
    }
