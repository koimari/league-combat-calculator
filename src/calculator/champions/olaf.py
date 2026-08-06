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

from .reviewed_batch_05 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Olaf")

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
