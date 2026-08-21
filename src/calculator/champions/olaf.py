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

Roadmap session (2026-08-21): closes one of Olaf's two out_of_scope
slots (P); R stays open with a named receipt.

  - P (Berserker Rage): not a damage gap but a stale label — the
    pinned packet already declares P ``kind: "no_damage"``
    (``static/reviewed-packets.json``), so ``build_packet_module`` was
    already emitting a proper zero-damage row while ``MODULE_COVERAGE``
    still read "out_of_scope".  Berserker Rage is a pure self-state
    passive (reduced damage taken scaling with missing health, slow
    immunity) with no enemy-damage clause anywhere in the cached entry.
    Reclassified to ``no_damage`` on the pinned-packet declaration, with
    no behavior change (the parser output is byte-identical).
  - R (Ragnarok) stays ``out_of_scope``, unchanged (pinned by
    ``tests/test_olaf_r_cleanse.py::TestSourceAndTypedValues::
    test_r_assumptions_absent_cleanse_mention``, which asserts
    ``MODULE_COVERAGE["R"] == "out_of_scope"``).  R IS more than a
    no-damage slot: its cast cleanses active crowd control, grants a 3s
    CC-immunity window, and applies bonus armor/MR/AD/size/movement-speed
    self-buffs — a full sourced cleanse+immunity+stat-buff kit that the
    P2 Slice 4-8 kernel does not wire for Olaf today
    (``resolve_cleanse_item("Olaf R")`` fails closed with a named
    KeyError).  ``test_olaf_r_cleanse.py`` is the existing 2200+-line
    named-unsupported receipt for this boundary: it pins every sourced
    R row (resistances, AD, MS, duration, size, cooldown, cost) against
    both the wiki cache and the game binary, proves the underlying
    kernel primitives (cleanse truncation, immunity window, stat-buff
    dispatch) already work in isolation, and pytest.mark.xfails the
    wired R activation pending a dedicated P2-9 coordinator completion
    that is explicitly out of this session's scope. R is therefore
    "out_of_scope" (a real, sourced, unmodeled mechanic), not
    "no_damage" (a confirmed zero-effect slot) — the two labels are not
    interchangeable here.
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
    "P (Berserker Rage) carries no enemy-damage formula of any kind (the "
    "reviewed packet's own no_damage slot declaration already names it): "
    "a self-state passive (damage-taken reduction scaling with missing "
    "health, slow immunity). Reclassified from out_of_scope to no_damage "
    "(a stale label, not a computation change): the slot was previously "
    "mislabeled out_of_scope despite the packet layer already carrying "
    "no enemy-damage formula for it.",
    # NOTE: the R (Ragnarok) receipt lives ONLY in this module's
    # docstring, not here — tests/test_olaf_r_cleanse.py pins
    # `"Ragnarok" not in " ".join(ASSUMPTIONS)` as the "R stays
    # out_of_scope, untouched" boundary marker; adding an R-naming
    # assumption string would flip that pinned test.
]

MODULE_COVERAGE = {
    "P": "no_damage",
    "Q": "modeled",
    "W": "modeled",
    "E": "modeled",
    "R": "out_of_scope",
}
REVIEW_STATUS = "reviewed_module"
