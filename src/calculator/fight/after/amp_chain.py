"""Which declared amplifier occupies each chain slot, and how one amp's bonus is booked."""

from collections.abc import Sequence
from typing import Any

from ... import rune_effects
from ...interpreters import amp_magnitude, delta_amp
from ...item_behavior import AmpChainSlot, FightFacts
from ..state import FightState, _held_owners


def _amplifier_delta_events(
    amped_events: list,
    bonus: float,
) -> list[dict[str, Any]]:
    """Author an amplifier row's bonus onto the exact events it amplified.

    A fight-wide amplifier prices its bonus as one fraction of the running
    total, so its per-event delta is that same fraction of each amplified
    event — expressed as a pro-rata share so the authored events sum
    exactly to the row total. Each delta keeps its amplified event's time
    and timeline order; the ``amplifier`` phase rank then places it
    immediately after that event in the shared ledger.  Consumes the light
    ledger rows ``(sort_key, damage, damage_type, source_key)``.
    """
    amped_total = sum(row[1] for row in amped_events)
    if bonus <= 0 or amped_total <= 0:
        return []
    return [
        {
            "damage_type": row[2],
            "damage": bonus * row[1] / amped_total,
            "time": row[0][0],
            "timeline_order": row[0][1],
        }
        for row in amped_events
    ]


def _amp_slot(
    state: FightState, slot: AmpChainSlot, *extra_owners: str
) -> "delta_amp.AmpSlot | None":
    """The declared amp occupying one chain slot for this build.  ``None``
    means nothing the build holds declares the slot, an answer and not a zero.
    ``extra_owners`` carries the keystone, an owner the item list cannot hold."""
    owners = _held_owners(state)
    owners.extend(extra_owners)
    return _amp_slot_for(state, slot, owners)


def _amp_slot_for(
    state: FightState, slot: AmpChainSlot, owners: Sequence[str]
) -> "delta_amp.AmpSlot | None":
    """One chain slot resolved for an explicit owner list.

    Split from :func:`_amp_slot` for the one mechanic whose eligible owner is
    narrower than the build: only the *active* spellblade's Expose Weakness
    is priced, and a build holding Bloodsong behind another spellblade must
    not be amped by an item whose proc never landed.
    """
    return delta_amp.resolve_slot(
        owners,
        slot,
        facts=FightFacts(
            level=state.level,
            fight_duration_seconds=state.fight_duration_seconds,
            target_bonus_health=max(0.0, state.target_bonus_health),
            holder_is_melee=state.is_melee,
        ),
    )


def _required_amp_slot(
    state: FightState, slot: AmpChainSlot, effect: "rune_effects.RuneEffect"
) -> "delta_amp.AmpSlot":
    """The chain slot a compiled keystone effect *must* have a declaration for.

    A selected keystone that resolved to an amp-shaped effect and declares no
    rule is a programming error, not an amp worth zero — the effect's own
    existence is the proof a holder is present.  It raises rather than
    returning ``None``, because returning would price the mechanic at zero
    with nothing saying so, which is the failure this campaign exists to end.
    """
    resolved = _amp_slot(state, slot, effect.rune_name)
    if resolved is None:
        raise amp_magnitude.DeltaAmpInterpretationError(
            f"{effect.rune_name} resolved to a {type(effect).__name__} and "
            f"declares no rule in the {slot.value} chain slot; a keystone the "
            "engine prices needs a declaration to price it from"
        )
    return resolved


def _record_amp_row(
    state: FightState,
    key: str,
    name: str,
    multiplier: float,
    *,
    amped: list,
    bonus: float,
) -> None:
    """Book one amplifier's bonus: its row, its delta events, its total.

    Every amplifier that prices a pool of ledger rows ends the same way —
    a row naming its owner and multiplier, the bonus authored back onto the
    exact events it amplified (or left coarse when it cannot be), and the
    bonus added to the fight. The shape lives here so each caller keeps only
    what differs: which rows it amplified, and by how much.
    """
    row: dict[str, Any] = {
        "name": f"Damage Amplification ({name})",
        "multiplier": multiplier,
        "total_damage": bonus,
    }
    delta_events = _amplifier_delta_events(amped, bonus)
    if delta_events:
        row["damage_events"] = delta_events
        row["event_phase"] = "amplifier"
    state.breakdown[key] = row
    state.total_damage += bonus
