"""Olaf — CP10.5 full-entry-reviewed packet module, plus the E8c W shield.

E8c addition over the reviewed packet:
- W (Tough It Out) grants Olaf a shield for 2.5 seconds equal to
  10/40/70/100/130 (+ 17.5% missing health) (cached Shield Strength
  row).  W deals no damage, so the shield is emitted by the
  ally-support scanner at the W cast (self-targeted).  The missing
  health term is evaluated by the scanner at 0 (full-health floor);
  the sourced 17.5% missing-health scaling is a documented boundary —
  the module pins it as a constant for audit, but the scanner's packet
  carries the flat component only.
"""

from .packet_module import _rank_gated_no_damage, build_packet_module

PACKET_SHA256 = "abc0765ed94d66999d26bc7fe98c41c49c3d5e3631c4cca2a96a59de1ba776eb"

# P2 Slice 9 (Ragnarok): the R is heal/cleanse/immunity-only (no outgoing
# damage) AND unlearnable-while-absent — an R rank 0 must not book a cast.
_RANK_GATED_R = _rank_gated_no_damage(
    "R",
    reason="The pinned Wiki packet contains no enemy-damage formula for "
    "this slot; it is modeled as a non-damaging/state-only ability.",
)

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Olaf", PACKET_SHA256, slot_parsers={"R": _RANK_GATED_R}
)
PACKET_SPEC = SLOTS.packet_spec

# P2 Slice 9 — Ragnarok sourced values (wiki rows + the game file
# OlafRagnarok: Resists 10/15/20, Duration 3.0, FlatAD 10/20/30,
# PercentTotalADAmp 0.25, HasteDuration 1.0, Haste 20/45/70 %,
# DurationExtension 2.5, cooldownTime 100/90/80, mana 100,
# canCastWhileDisabled true / cannotBeSuppressed true).  The cleanse +
# immunity + stat receipts are authored per R cast by the participant
# timeline; the AD + 10% size + 2.5s duration-extension have no kernel
# fields — receipted named-unsupported (never applied); the first-second
# MS facing/2000-unit condition is prose-only (the movement utility
# surface carries the amount + 1s window).
RAGNAROK_DURATION_SECONDS = 3.0
RAGNAROK_FIRST_SECOND_MS_WINDOW = 1.0
RAGNAROK_BONUS_AD = (10.0, 20.0, 30.0)
RAGNAROK_BONUS_AD_TOTAL_PERCENT = 25.0
RAGNAROK_SIZE_INCREASE_PERCENT = 10.0
RAGNAROK_DURATION_EXTENSION_SECONDS = 2.5

# HARDCODED: verify on patch updates — Tough It Out's 2.5s shield
# duration and 17.5% missing-health ratio are prose/cached leveling
# (data/champions.json, Olaf W): "grants himself a shield for 2.5
# seconds" + Shield Strength 10/40/70/100/130 (+ 17.5% missing health),
# capped at 70% missing health.  The scanner emits the flat component at
# the full-health floor; the missing-health term is documented.
TOUGH_IT_OUT_SHIELD_DURATION_SECONDS = 2.5
TOUGH_IT_OUT_MISSING_HEALTH_RATIO = 0.175
TOUGH_IT_OUT_MISSING_HEALTH_CAP = 0.70

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Tough It Out) shields Olaf for the sourced 10/40/70/100/130 + "
    "17.5% missing health for 2.5s at the cast; the ally-support scanner "
    "emits the self packet with the flat component at the full-health "
    "floor (the missing-health term and its 70%-of-missing-health cap "
    "are documented boundaries), and it absorbs incoming damage in the "
    "participant ledger",
]

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
