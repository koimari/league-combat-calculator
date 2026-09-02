"""Yuumi — CP10.10 full-entry-reviewed packet module.

E8d ally-support: E (Zoomies) grants the caster a shield (Shield 65-165 +
40% AP; scope one_teammate — the attached anchor) and R (Final Chapter)
heals allies hit by the waves (Heal per Hit x5 == Total Heal, scope
one_teammate).  Both events are authored by the engine's ally-support
scanner from cached leveling at the cast times; the module declares E/R in
SLOTS so the fight rotation casts them.

Wave-2 ally support (HANDOVER 8.5), all authored by the scanner on the R
cast:
- Best Friend Bonus: Final Chapter's heal to the Best Friend is increased
  by 30% : 60% (based on level) — the deterministic roster model treats
  the selected teammate as the anchor/Best Friend (the same teammate the E
  shield already targets), so the bonus is a second heal packet
  (``heal:R:<cast>:best_friend``) priced at the sourced per-level row,
  read with the repo's clamped level convention (endpoints exact).
- Overheal conversion: "each heal instance beyond maximum health being
  converted into a shield that lasts for 1.5 seconds plus the remaining
  channel duration instead" — one conversion shield per heal packet with a
  live excess formula (max(0, heal - missing health)) and a sourced
  lifetime of 1.5s + the full 3.5s channel (the scanner lumps the heal at
  the cast).  The heal actions still book the same excess as overhealing
  (the kernel's excess-conversion carve-out applies only to heal-compiled
  events, not support templates — survival/ is outside this wave's edit
  boundary), so the public receipt shows both lines and the shield is the
  authored effect.
- The self-heal stream of R (5 waves x Heal per Hit) is owned by this
  module's ``derive_self_healing`` rule and is unchanged.
P (Feline Friendship) is ``modeled`` through ``COVERAGE_CHANNELS``
(``self_healing_rule``).  The heal is hit-anchored, which is a channel
this kernel has: ``healing_helpers.HealAnchor.DAMAGING_HIT`` pays per
damaging hit and is read against the ``auto_attacks`` source key by
Briar's lifesteal rule (``briar.py``), Kindred, Maokai and Aphelios.
Both of P's gates are cached rows this module reads live — the per-level
"Heal" (20 : 120.59 by level + 30% AP) and the passive's own per-level
cooldown (20 : 8s, with ``affectedByCdr`` false, so ability haste never
shortens the recharge).  The heal's ANCHOR half is what has no channel:
the ally-support scanner hangs packets on CASTS and a passive is never
cast (``champions/engine.py`` keys a P entry "passive" and no rotation
schedules one), so only the self half is priced.

W (You and Me!) is ``no_damage``: the whole slot is attachment, dashing and
the Best Friend Bonus, with no enemy-damage clause anywhere in it
(``damageType: None``, ``affects: Allies``, and both leveling rows are
recovery rows).  Its heal-and-shield-power half is withheld on its
CONDITION, not for want of a channel.  The CASTER hook is live:
``heal_and_shield_power_percent`` is a real stat key,
``damage._apply_stat_buff_ultimates`` adds any stat key generically, and
``healing_reduction.heal_and_shield_power_factor`` reads it back for the
caster at ``pipeline._attach_display_splits`` and as
``ctx.heal_power(action.attacker)`` in ``survival/transitions``.  The
condition is being attached to a Best Friend, which no module-visible
state can establish — see ASSUMPTIONS.

E's shield reaches the anchor rather than Yuumi through the scanner's
sourced scope override (``support_effects._SCOPE_OVERRIDES``), which is the
one home for the attached-bonus anchor transfer ("Affects the Anchor
instead of Yuumi").
"""

from typing import Any

from ..healing_helpers import (
    HealAnchor,
    ability_json,
    event_source,
    parsed_rank,
    payments,
)
from .engine import SlotCtx
from .healing_contract import self_healing_rule
from .inputs import champion_stat
from .module_contract import coverage
from .packet_module import build_packet_module, first_plus_repeats_parser
from .slotlib import (
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
)

PACKET_SHA256 = "1795828f6486a1da27c639b301d6ebca7047735f17a173075d41d59369c82942"

# Prowling Projectile's missile "deals magic damage to the first enemy hit.
# If the target is a champion, they are also revealed and slowed by 20% for
# 1 second"; Final Chapter's waves hit enemies who "take magic damage and
# are slowed by 10% for 1.25 seconds".  W (You and Me!) and E (Zoomies) are
# out_of_scope ally rows and P heals — none authors a damage part.
MODULE_CC = {"Q": "slow", "R": "slow", "P": "none", "W": "none", "E": "none"}

# What consumes Feline Friendship's empowered attack, per the cached innate:
# "Upon hitting them with the basic attack or Prowling Projectile ... the
# buff is consumed to heal her".  Either damaging hit spends the one buff,
# so the rule reads both source keys and pays the earlier one.
_P_TRIGGER_SOURCES = frozenset({"auto_attacks", "Q"})


def _you_and_me(packet_w):
    """W: attachment and the Best Friend Bonus — a sourced zero-damage row.

    Replaces the packet's generic "no enemy-damage formula" stub with the
    two cached Best Friend rows read back out of the cache, so the numbers
    in the row are the cache's rather than module literals.  Neither half is
    published; the reason is the condition, and it is stated in ASSUMPTIONS.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_w(ctx)
        if entry is None:
            return None
        ability = ctx.ability()
        rank = ctx.rank_for()
        if ability is None or rank < 1:
            return entry
        for attribute in ("Heal and Shield Power", "Healing On-Hit"):
            if find_named_leveling(ability, attribute) is None:
                # Fail closed: the emitted row quotes both of these, so a
                # cache that stops carrying one must not leave a receipt
                # citing a number nothing sources.
                raise ValueError(
                    f"Yuumi W (You and Me!) has no cached {attribute!r} "
                    "leveling row; the slot's receipt cites that row, so it "
                    "is refused rather than restated from a stale literal."
                )
        power = extract_value(ability, "Heal and Shield Power", rank)
        on_hit = extract_value(ability, "Healing On-Hit", rank)
        on_hit_ratio = extract_value(ability, "Healing On-Hit", rank, modifier_index=1)
        entry["detail"] = (
            "Attachment and the Best Friend Bonus: no damage row exists in "
            "the slot. The active dashes to a target ALLIED champion and "
            "attaches, so a 1v1 surface cannot cast it at all. Its Best "
            f"Friend Bonus grants Yuumi {power:g}% heal and shield power and "
            f"her Best Friend {on_hit:g} (+{on_hit_ratio:g}% AP) healing "
            "on-hit at this "
            "rank. Neither is published: the heal-and-shield-power channel "
            "EXISTS (heal_and_shield_power_percent, folded back for the "
            "caster by healing_reduction.heal_and_shield_power_factor), but "
            "the grant is gated on being attached to a Best Friend, which no "
            "module-visible state can establish; the on-hit half goes to the "
            "ally. Attached Yuumi is also untargetable and casts from her "
            "anchor, which the engine has no participant state to express."
        )
        return entry

    return parse


parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Yuumi",
    PACKET_SHA256,
    assumption_overrides=(
        "Final Chapter prices all 5 waves (Magic Damage per Hit + 4 x "
        "Reduced Damage per Hit == Total Magic Damage).",
    ),
    # Q is one missile hitting one enemy; the packet has no travel phase
    # to place.
    single_hit_slots=frozenset({"Q"}),
    cc_kinds=MODULE_CC,
    slot_parsers={
        "R": first_plus_repeats_parser(
            first_attr="Magic Damage per Hit",
            repeat_attr="Reduced Damage per Hit",
            repeats=4,
            time_offset=0.7,
            hit_interval=0.7,
            dot_duration=3.5,
        )
    },
    slot_wrappers={"W": _you_and_me},
)
ASSUMPTIONS = [
    *ASSUMPTIONS,
    "R (Final Chapter) emits, per cast on the selected teammate (the "
    "anchor/Best Friend): the sourced Total Heal (150-350 + 60% AP), the "
    "sourced per-level Best Friend bonus packet (30% : 60% based on "
    "level, 30/35/40/45/50/55/60% row read at the repo's clamped level "
    "index — the wiki bracket levels are not in the cache), and one "
    "overheal-conversion shield per heal packet: max(0, heal - missing "
    "health) for 1.5s + the full 3.5s channel (lump-at-cast model).  The "
    "conversion shields are grants into the shared shield ledger; the "
    "heal actions still book the identical excess as overhealing (kernel "
    "carve-out applies only to heal-compiled events).",
    "Feline Friendship (P) pays its sourced self-heal (20 : 120.59 by "
    "level + 30% AP) on the first damaging hit — a basic attack or "
    "Prowling Projectile, per the cached innate — that its own per-level "
    "recharge row (20 : 8s, affectedByCdr false) allows, through this "
    "module's healing rule (COVERAGE_CHANNELS P -> self_healing_rule).  "
    "The ANCHOR half of the same heal stays unmodeled: the ally-support "
    "scanner hangs packets on casts and a passive is never cast, so only "
    "the self half has a channel.  You and Me!'s heal-and-shield-power "
    "amplifier is not published; see the W assumption for why.",
    "W (You and Me!) is no_damage, NOT out_of_scope. The cached entry "
    "carries damageType null and affects Allies, and every effect is "
    "attachment, dash, recast or the Best Friend Bonus — there is no "
    "enemy-damage clause anywhere in the slot, so there is no damage to "
    "miss. Its two leveling rows are both RECOVERY rows (Heal and Shield "
    "Power 4/5/6/7/8%, Healing On-Hit 3/4/5/6/7 + 3% AP), read live into "
    "the emitted row rather than restated as literals. Neither is "
    "published. The retired receipt blamed the CHANNEL — 'no outgoing "
    "heal-power kernel hook (the kernel prices received-healing "
    "multipliers, not caster heal power)' — and that is false: "
    "heal_and_shield_power_percent is a real stat key, "
    "damage._apply_stat_buff_ultimates adds any stat key generically, and "
    "healing_reduction.heal_and_shield_power_factor folds it back for the "
    "CASTER at pipeline._attach_display_splits and as "
    "ctx.heal_power(action.attacker) in survival/transitions (verified "
    "live: an 8% grant on a cast Yuumi slot moves champion_stats "
    "heal_and_shield_power_percent 0.0 -> 8.0 and self_healing 570.0 -> "
    "615.6, exactly x1.08). The real blocker is the CONDITION. The bonus "
    "requires Yuumi to be ATTACHED to a Best Friend, and W's own active is "
    "'dashes to the target allied champion and attaches to them' — an "
    "ability a 1v1 surface cannot cast at all. A stat_buff is emitted from "
    "parse_abilities, which has no roster visibility (SlotCtx exposes no "
    "teammate; the ally path is the cast-keyed support scanner and its "
    "_SCOPE_OVERRIDES, which is how E's shield reaches the anchor), so the "
    "grant could not be gated on an anchor existing and would inflate "
    "self_healing by up to 8% in every solo Yuumi fight. Withheld as a "
    "documented rider instead (the Akshan-W convention). The Best Friend's "
    "healing on-hit is an ALLY grant and has no channel either, and "
    "attached Yuumi's untargetability and cast-from-anchor position remain "
    "participant state the engine does not model.",
]
MODULE_COVERAGE = coverage(no_damage="W")
COVERAGE_CHANNELS = {"P": ("self_healing_rule",)}


# pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Final Chapter's five waves and Feline Friendship's on-hit heal.

    "Heal per Hit" x5 == the cached "Total Heal" row; the waves land on the
    module's own 0.7s cadence, so the heal is paid on that schedule rather
    than inferred from the damage ledger's event count.

    P (Feline Friendship) pays on a damaging hit instead: the cached innate
    empowers the next basic attack "periodically", and the buff is consumed
    on hitting with that attack or with Prowling Projectile.  Both gates are
    read live from the cache — the per-level "Heal" row (20 : 120.59 by
    level + 30% AP) and the passive's own per-level cooldown row (20 : 8s,
    ``affectedByCdr`` false, so ability haste never shortens it).
    """
    healing: list[dict] = []
    r_rank = parsed_rank(ability_damages, "R")
    per_wave = extract_named(
        ability_json(champion_data, "R"), "Heal per Hit", r_rank, champion_stats
    )
    if per_wave > 0.0:
        for cast in cast_timeline or []:
            if cast.get("slot") != "R":
                continue
            start = float(cast.get("time", 0.0))
            healing.extend(
                {
                    "time": start + index * 0.7,
                    "amount": float(per_wave),
                    "source": "Final Chapter",
                    "kind": "champion_ability",
                    "actor_wide": True,
                }
                for index in range(5)
            )
    healing.extend(
        _feline_friendship_heals(champion_data, champion_stats, damage_events)
    )
    return healing


def _feline_friendship_heals(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    damage_events: list[dict[str, Any]],
):
    """P's on-hit heals: one per damaging hit the recharge gate allows.

    The buff is up when the fight opens (the innate recharges out of
    combat), so the first damaging hit spends it and every payment re-arms
    the gate by the sourced cooldown.  Hits are walked in time order with
    the source key breaking ties, so an auto and a Prowling Projectile
    landing on the same instant spend the one buff once, deterministically.
    """
    level = max(1, int(champion_stat(champion_stats, "level")))
    passive = ability_json(champion_data, "P")
    if find_named_leveling(passive, "Heal") is None:
        # Fail closed: P is declared modeled through this rule alone, so a
        # renamed or dropped row must not silently downgrade the slot to
        # paying nothing while the contract still claims it is priced.
        raise ValueError(
            "Yuumi P (Feline Friendship) has no cached 'Heal' leveling row; "
            "the slot is declared modeled through this rule, so the heal is "
            "refused rather than silently paid as zero."
        )
    heal = extract_named(passive, "Heal", level, champion_stats, level=level)
    recharge = extract_cooldown(passive, level, level=level)
    if recharge <= 0.0:
        # Fail closed: a heal with no recharge row would pay on EVERY hit,
        # which is the silent overstatement the gate exists to prevent.
        raise ValueError(
            "Yuumi P (Feline Friendship) has a cached 'Heal' row but no "
            f"per-level cooldown row at level {level}; the on-hit heal "
            "cannot be gated and is refused rather than paid unbounded."
        )
    paid: list[dict] = []
    ready = 0.0
    for payment in sorted(
        payments(HealAnchor.DAMAGING_HIT, _P_TRIGGER_SOURCES, damage_events),
        key=lambda pay: (pay.cast_time, event_source(pay.event)),
    ):
        if payment.cast_time + 1e-9 < ready:
            continue
        paid.append(
            {
                "time": payment.cast_time,
                "amount": float(heal),
                "source": "Feline Friendship",
                "kind": "champion_passive",
                "actor_wide": True,
            }
        )
        ready = payment.cast_time + recharge
    return paid


SELF_HEALING_RULE = self_healing_rule("Yuumi")(derive_self_healing)
