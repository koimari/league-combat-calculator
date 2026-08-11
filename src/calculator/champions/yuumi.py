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
- The self-heal stream of R (5 waves x Heal per Hit) is owned by the E1
  rule in healing.py and is unchanged.
Documented missing hooks: Feline Friendship's P on-hit heal (20 : 120.59
by level + 30% AP) heals Yuumi and, while attached, the anchor for the
same amount — the scanner reads only Q/W/E/R slots and the self half would
need a healing.py rule, so the P heal stays unmodeled; You and Me!'s
"heal and shield power" outgoing amplifier has no kernel hook (the kernel
prices received-healing multipliers, not caster heal power).
"""

from .packet_module import build_packet_module, full_plus_reduced_parser

PACKET_SHA256 = "1795828f6486a1da27c639b301d6ebca7047735f17a173075d41d59369c82942"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Yuumi",
    PACKET_SHA256,
    assumption_overrides=(
        "Final Chapter prices all 5 waves (Magic Damage per Hit + 4 x "
        "Reduced Damage per Hit == Total Magic Damage).",
    ),
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
PACKET_SPEC = SLOTS.packet_spec
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
