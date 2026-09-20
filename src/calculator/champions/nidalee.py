"""Nidalee: full-entry-reviewed packet module.

W Bushwhack is a summoned trap and one sprung trap prices its full 4-second DoT,
four sourced 1-second ticks.  ``w_traps``, default 1 and capped at the sourced
level-18 trap cap of 10, prices additional pre-placed traps detonating during
the fight, each as its own full DoT: unlike Teemo's shrooms, Bushwhack carries
no refresh note anywhere in the source.  The Pounce variant is untouched.
The trap has no armor shred on this patch: the cached leveling rows carry the
DoT alone, and ``BushwhackAbility`` in the game files holds only the
``DamagePerSecond`` calculation.
P (Prowl) grants movement speed in brush and marks a Hunted target, and R
(Aspect of the Cougar) is the form swap itself, so both are movement and
transform, axes this engine lacks.  Cougar form stays reachable: the
``w_variant`` option selects the cougar abilities directly, so R has no state
of its own left to price.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from ..binary_roots import data_value, spell_object
from ..damage_event_row import event_time as _row_time
from ..healing_helpers import HealAnchor, missing_health_scaled_heal, trigger_fields
from .contract_vocabulary import coverage
from .engine import SlotCtx
from .healing_contract import SelfHealCtx, self_healing_rule
from .packet_module import build_packet_module
from .stat_grants import with_attack_speed_window

# "Up to a maximum of 4 / 6 / 8 / 10 (based on level) traps may be
# active at once" — 10 at level 18 (the test level).
_W_TRAP_CAP = 10

# Primal Surge's bonus attack speed lasts the binary PrimalSurge.ASDuration;
# the cached E prose ("for 7 seconds") corroborates it.
_E_ATTACK_SPEED_SECONDS = data_value(
    spell_object("Nidalee", "PrimalSurge"), "ASDuration"
)


def _bushwhack_traps(packet_w):
    """W: Bushwhack variant prices ``w_traps`` detonations; Pounce passthrough."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        if int(ctx.option("w_variant")) != 0:
            return packet_w(ctx)
        entry = packet_w(ctx)
        if entry is None:
            return None
        traps = min(max(int(ctx.option("w_traps")), 1), _W_TRAP_CAP)
        if traps > 1:
            entry["parts"] = tuple(
                dataclasses.replace(part, count=part.count * traps)
                for part in entry["parts"]
            )
            entry["total_raw"] = entry.get("total_raw", 0.0) * traps
        inherited = entry.get("detail", "")
        entry["detail"] = (
            f"{traps} sprung Bushwhack trap(s), each dealing its own full "
            "4-tick DoT." + (f" {inherited}" if inherited else "")
        )
        return entry

    return parse


PACKET_SHA256 = "96b6e873251ff23f700da4de3600cae2000d53929d77f7f315a48a227ac81d3d"

# The packet builder consumes these two explicit form selectors at parse time.

# Cached kit review: reviewed cc-free, whole kit.  No entry applies any
# crowd control to an enemy — Javelin Toss and Takedown only deal magic
# damage, Bushwhack's trap "deal[s] magic damage every second over 4
# seconds" (the old slow is gone from the cached text), Pounce and Swipe
# damage on arrival, Primal Surge heals, and Prowl / Aspect of the Cougar
# are Nidalee's own movement and form swap.  Every damaging slot says so
# explicitly, which is what lets control-armed item passives price a
# Nidalee fight instead of withholding on an unreviewed kit.
MODULE_CC = {"Q": "none", "W": "none", "E": "none", "P": "none", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Nidalee",
    PACKET_SHA256,
    packet_tick_fixes={
        "Bushwhack": {
            "count": 4,
            "first_tick": 1.0,
            "tick_interval": 1.0,
            "dot_duration": 4.0,
        }
    },
    # Javelin Toss and Takedown each land one hit, Swipe slashes once, and
    # W's Pounce variant damages once on arrival — the boundary claim that
    # carries MODULE_CC's reviewed answers into the event ledger.  W's
    # Bushwhack variant authors its own four-tick timing above and keeps it.
    single_hit_slots=frozenset({"Q", "W", "E"}),
    slot_wrappers={
        "W": _bushwhack_traps,
        "E": lambda packet_e: with_attack_speed_window(
            packet_e,
            duration=_E_ATTACK_SPEED_SECONDS,
            aside="Primal Surge's self-cast grant on the same E cast that heals.",
        ),
    },
    cc_kinds=MODULE_CC,
)
ASSUMPTIONS.extend(
    [
        "E places Primal Surge's bonus attack speed (human form, the "
        "self-cast) as a 7-second window at the first E cast, the cast the "
        "self-heal rule already pays; the E row's damage stays the cougar "
        "Swipe the packet prices, the same human/cougar blend the heal "
        "rule uses. The ally-cast grant and a second window are not placed.",
        "W (Bushwhack) is a summoned trap: one sprung trap prices the "
        "full 4-second DoT (E2-3 ticks); w_traps prices additional "
        "pre-placed traps, each with its own full DoT (the source has no "
        "refresh rule).",
        "The E4 worklist 'armor shred' note is stale for the current "
        "patch: the cached leveling rows and live game files carry only "
        "the trap DoT, so no shred is modeled.",
        "Trap placement, arm time, trigger radius and the trap's 6-HP "
        "health bar are state outside the damage model.",
        "P (Prowl) and R (Aspect of the Cougar) carry no enemy-damage "
        "formula of any kind (the reviewed packet's own no_damage_slots "
        "list already names both): Prowl is brush ghosting + up to 30% "
        "movement speed and the Hunt mark; Aspect of the Cougar is the "
        "human/cougar form-switch toggle whose cooldown-reset rule the "
        "form selector already encodes. Reclassified from out_of_scope "
        "to no_damage (a stale label, not a computation change): both "
        "slots were previously mislabeled out_of_scope despite the "
        "packet layer already carrying no enemy-damage formula for them.",
    ]
)
OPTIONS.append(
    {
        "key": "w_traps",
        "type": "int",
        "default": 1,
        "min": 1,
        "max": _W_TRAP_CAP,
        "label": "Sprung Bushwhack traps",
        "rotation": {"role": "self_state", "slot": "W"},
    }
)
MODULE_COVERAGE = coverage(no_damage="PR")


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Primal Surge pays a missing-health-scaled heal on each E CAST.

    Wiki "Minimum Heal" / "Maximum Heal": the heal triggers on the cast
    whether or not the paired damage landed, so the anchor is the cast and
    not the damage ledger's row count.
    """
    healing: list[dict] = []
    min_heal, max_heal = ctx.ranked_rows("E", "Minimum Heal", "Maximum Heal")
    healing.extend(
        {
            "time": _row_time(payment.event),
            "amount": 0.0,
            "amount_formula": missing_health_scaled_heal(min_heal, max_heal),
            "source": "Primal Surge",
            "kind": "champion_ability",
            **trigger_fields(payment.event),
        }
        for payment in ctx.payments(HealAnchor.CAST, "E")
    )
    return healing


SELF_HEALING_RULE = self_healing_rule("Nidalee")(derive_self_healing)
