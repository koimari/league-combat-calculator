"""Every champion option key whose declaration and its read sit in different files.

One module declares the OPTIONS row and another consults it, so the
spelling is a contract: it lives here, the reader imports the name, and
the declaring row takes it wherever that module has an import to spare.
``tests/test_shared_option_keys.py`` fails on a name no OPTIONS row
declares, and on an engine module that reads a key as a literal.
A key only its own module reads is declared there, not here.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import NamedTuple


class DefenseWindowOptions(NamedTuple):
    """One slot's window: the toggle, the start time, the held duration."""

    active: str
    active_from: str
    active_seconds: str


def _window(slot: str) -> DefenseWindowOptions:
    key = slot.lower()
    return DefenseWindowOptions(
        f"{key}_active", f"{key}_active_from", f"{key}_active_seconds"
    )


W_WINDOW = _window("W")
E_WINDOW = _window("E")

#: The window a slot's options drive, for a reader holding the slot letter.
WINDOW_OPTIONS = MappingProxyType({"W": W_WINDOW, "E": E_WINDOW})

# Which incoming events a defensive window is asked to stop.
W_BLOCKED_SKILLSHOTS = "w_blocked_skillshots"
W_BLOCKED_SOURCES = "w_blocked_sources"
W_BLOCKED_EVENT_IDS = "w_blocked_event_ids"
E_BLOCKED_SKILLSHOTS = "e_blocked_skillshots"
E_BLOCKED_EVENT_IDS = "e_blocked_event_ids"

#: How many times a per-fight passive procs (`slotlib.proc_damage`).
PASSIVE_PROCS_OPTION = "passive_procs"

#: The share of the target's health already gone
#: (`module_helpers.missing_hp_fraction`).
TARGET_MISSING_HP_OPTION = "target_missing_hp_pct"

#: Yasuo's and Yone's shared Q stack count (`yasuo_yone`).
GATHERING_STORM_OPTION = "q_gathering_storm"

#: Seraphine's W caster already holds a shield (`support_effects`).
SERAPHINE_ALREADY_SHIELDED = "w_already_shielded"

#: Tahm Kench presses Thick Skin (`participant_timeline`).
TAHM_KENCH_GREY_SHIELD = "e_convert_grey_shield"

#: Who Lulu's W and R land on (`pipeline` pins both for the roster).
LULU_WHIMSY_TARGET = "lulu_whimsy_target"
LULU_WILD_GROWTH_TARGET = "lulu_wild_growth_target"

# The walks in `fight/stacks/` gate on these and seed their counters from
# them: an unrecognised spelling withholds the whole ledger silently.
ASHE_FOCUS_ACTIVE = "q_active"
ASHE_FOCUS_STACKS = "q_focus_stacks"
AURELION_SOL_STARDUST_STACKS = "stardust_stacks"
BARD_CHIMES = "chimes"
HEIMERDINGER_GRENADE_UPGRADE = "e_upgrade"
HEIMERDINGER_ROCKETS = "w_rockets"
KSANTE_ALL_OUT = "all_out"
KSANTE_PATH_MAKER_CHARGE = "w_charge"
RENGAR_FEROCITY = "p_ferocity"
SENNA_MIST_STACKS = "senna_mist_stacks"
