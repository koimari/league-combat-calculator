"""Rumble — CP10.6 packet module with the E9-1 R gap fix.

E9-1 closes the remaining audit gap: R (The Equalizer) priced ONE tick
of the Burning DoT.  The wiki cache carries "Magic Damage per Tick"
(30/50/70 + 8.75% AP) and "Maximum Magic Damage" (600/1000/1400 +
175% AP): 20 ticks at 0.25 seconds over up to 5 seconds of Burning
("Enemies may be Burning for up to 5 seconds, for a total of 20
instances of its effect").  The packet_module _PACKET_TICK_FIXES entry
prices all 20 ticks.

The heat/Danger Zone system remains documented out_of_scope (P/W
no_damage rows); rotation numbers assume no heat state (the CP-era
review boundary).  Q/E damage packets are correct; E additionally
emits the sourced 4-second Magic Resistance Reduction as a
``target_debuff`` on the E entry.
"""

from typing import Any

from .reviewed_batch_06 import build_batch_module
from .slotlib import extract_value

# Electro Harpoon's MR reduction lasts 4 seconds ("inflicting them with
# magic resistance reduction for 4 seconds", the E ability description).
E_MR_REDUCTION_DURATION = 4.0


def _with_e_mr_reduction_shred(
    parse: Any,
) -> Any:
    """Attach Electro Harpoon's rank-aware MR shred to the E packet.

    The reviewed packet prices the harpoon's "Magic Damage" exactly;
    the "Magic Resistance Reduction" rank row (10/12/14/16/18% by rank)
    rides the same hit as a ``target_debuff``.  damage.py applies the
    shred AFTER E's own damage (the Kog'Maw rule), so the packet's
    numeric damage is untouched and later casts/autos see the reduced
    magic resistance for the debuff's 4 seconds.
    """

    def parse_abilities(
        champion_data: dict[str, Any],
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, dict[str, Any]]:
        result = parse(champion_data, *args, **kwargs)
        entry = result.get("E")
        if entry is None:
            return result
        abilities = (
            champion_data.get("abilities", {})
            if isinstance(champion_data, dict)
            else {}
        )
        e_entries = abilities.get("E") or []
        rank = int(entry.get("rank", 0))
        if not e_entries or rank < 1:
            return result
        shred = extract_value(e_entries[0], "Magic Resistance Reduction", rank)
        if shred > 0:
            entry["target_debuff"] = {
                "mr_reduction_percent": shred,
                "duration": E_MR_REDUCTION_DURATION,
            }
        return result

    return parse_abilities


parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Rumble")
parse_abilities = _with_e_mr_reduction_shred(parse_abilities)
ASSUMPTIONS = list(ASSUMPTIONS) + [
    "E (Electro Harpoon) keeps the reviewed packet's Magic Damage; its "
    "Magic Resistance Reduction rank row (10/12/14/16/18% by rank) "
    "rides the same hit as a 4-second target_debuff, applied after "
    "E's own damage (the Kog'Maw rule).",
    "R (The Equalizer) prices all 20 Burning ticks (Magic Damage per "
    "Tick x20 == Maximum Magic Damage 600/1000/1400 + 175% AP) at "
    "0.25-second intervals over up to 5 seconds (packet_module "
    "_PACKET_TICK_FIXES).  The initial rocket impact has no separate "
    "damage row in the cache.",
    "The heat/Danger Zone system is state outside the damage model: "
    "Q/E/R rotation numbers assume no heat state (the CP-era review "
    "boundary).",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
