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
Documented missing hooks: Feline Friendship's P on-hit heal (20 : 120.59
by level + 30% AP) heals Yuumi and, while attached, the anchor for the
same amount — the scanner reads only Q/W/E/R slots and the self half would
need a healing.py rule, so the P heal stays unmodeled; You and Me!'s
"heal and shield power" outgoing amplifier has no kernel hook (the kernel
prices received-healing multipliers, not caster heal power).

P (Feline Friendship) stays ``out_of_scope`` on the empowered-attack trigger
axis for a structural reason: the ally-support scanner hangs packets on
CASTS and a passive is never cast (``champions/engine.py`` keys a P entry
"passive" and no rotation schedules one), while this module's healing rule
anchors on Final Chapter's waves only.  A hit-anchored heal rule is the
channel it is waiting on.

W (You and Me!) stays ``out_of_scope`` on the attachment axis: an attached
Yuumi is untargetable and casts from her anchor, and the engine has no
participant-attachment state to express either half.

E's shield reaches the anchor rather than Yuumi through the scanner's
sourced scope override (``support_effects._SCOPE_OVERRIDES``), which is the
one home for the attached-bonus anchor transfer ("Affects the Anchor
instead of Yuumi").
"""

from ..healing_helpers import _ability, _rank
from .healing_contract import declare_healing_rule
from .packet_module import build_packet_module, full_plus_reduced_parser
from .slotlib import extract_named

PACKET_SHA256 = "1795828f6486a1da27c639b301d6ebca7047735f17a173075d41d59369c82942"

# Prowling Projectile's missile "deals magic damage to the first enemy hit.
# If the target is a champion, they are also revealed and slowed by 20% for
# 1 second"; Final Chapter's waves hit enemies who "take magic damage and
# are slowed by 10% for 1.25 seconds".  W (You and Me!) and E (Zoomies) are
# out_of_scope ally rows and P heals — none authors a damage part.
MODULE_CC = {"Q": "slow", "R": "slow"}

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
        "R": full_plus_reduced_parser(
            full_attr="Magic Damage per Hit",
            reduced_attr="Reduced Damage per Hit",
            dmg_type="magic",
            reduced_count=4,
            time_offset=0.7,
            hit_interval=0.7,
            dot_duration=3.5,
        )
    },
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
    "Feline Friendship (P) on-hit heal to Yuumi and the anchor "
    "(20 : 120.59 by level + 30% AP) is documented-only: the support "
    "scanner reads Q/W/E/R slots and the self half needs a healing.py "
    "rule; You and Me!'s heal-and-shield-power amplifier has no outgoing "
    "heal-power kernel hook.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}


# pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Final Chapter's five waves each pay their sourced Heal per Hit.

    "Heal per Hit" x5 == the cached "Total Heal" row; the waves land on the
    module's own 0.7s cadence, so the heal is paid on that schedule rather
    than inferred from the damage ledger's event count.
    """
    healing: list[dict] = []
    r_rank = _rank(ability_damages, "R")
    per_wave = extract_named(
        _ability(champion_data, "R"), "Heal per Hit", r_rank, champion_stats
    )
    if per_wave > 0.0:
        for cast in cast_timeline or []:
            if cast.get("slot") != "R":
                continue
            start = float(cast.get("time", 0.0))
            for index in range(5):
                healing.append(
                    {
                        "time": start + index * 0.7,
                        "amount": float(per_wave),
                        "source": "Final Chapter",
                        "kind": "champion_ability",
                        "actor_wide": True,
                    }
                )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


SELF_HEALING_RULE = declare_healing_rule("Yuumi", derive_self_healing)
