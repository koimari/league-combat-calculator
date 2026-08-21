# Golden recapture — roadmap session 4 batch G, 2026-08-21

Champions: Ryze, Senna, Shaco, Swain, Tahm Kench (one out_of_scope slot
each per roadmap-100.md sec 2.2's 1-slot row).

Pre-recapture compare: 7 diffs, all under
`/champion_baselines/Shaco/abilities_level_11/passive/*` — zero diffs from
Ryze, Senna, Swain, or Tahm Kench.

## Per-champion disposition

- **Ryze P (Arcane Mastery):** stale-label fix, `out_of_scope` ->
  `no_damage`. The cached effect ("increases his maximum mana by 10% per
  100 AP") is a self mana buff with an empty leveling row; the pinned
  reviewed packet already declared `kind="no_damage"` and P was never
  reassigned away from `build_packet_module`'s no-damage branch, so the
  parsed output was already a sourced zero-damage row — only
  `MODULE_COVERAGE`'s label was stale (Malzahar/Nasus precedent, batch D).
  Zero golden movement, as expected for a label-only fix.
- **Senna E (Curse of the Black Mist):** stale-label fix, `out_of_scope`
  -> `no_damage`. All five cached effects are self/ally camouflage and
  movement-speed utility prose with zero enemy-damage leveling; E is not
  one of the four slots the module reassigns (P, P2, R, W, Q). Same
  Malzahar/Nasus precedent. Zero golden movement.
- **Shaco P (Backstab):** genuine gap closure, not a label fix. The
  pinned reviewed packet mislabeled a real, sourced formula as
  `no_damage`; the cached P effect carries a 20-value ("Per-Level
  Scaling") leveling row plus `affects: "Enemies"` /
  `damageType: "PHYSICAL_DAMAGE"` — "20 : 31.18 (based on level) (+20%
  bonus AD) bonus physical damage when hitting an enemy from behind,
  affected by critical strike modifiers." The game file
  (`shaco.bin.json` `ShacoPassiveAbility/ShacoPassive`) corroborates the
  AD-ratio term exactly: `StatByNamedDataValue(mStat=2, mStatFormula=2,
  AttackBonusADRatio=0.2)` matches the wiki's "+20% bonus AD" 1:1. The
  positional "from behind" condition has no representation in this
  engine's stateless single-target duel model, so it is gated behind an
  explicit `p_backstab` option (default `False`, matching the module's
  own `e_execute`/`r_clone_attacks` convention for caller-supplied state
  the engine cannot derive) — crit-conservative flat on-hit rider (Riven
  P/Runic Blade precedent). Now wired: `SLOTS["P"] = _backstab`,
  `MODULE_COVERAGE["P"] = "modeled"`, `p_backstab` OPTION added, and an
  ASSUMPTIONS entry documents the boundary. All 7 diffs are the
  structural consequence of this reclassification at the golden fixture's
  default options (`p_backstab=False`): the P slot now emits a real
  `on_hit` entry (0.0 damage at the deterministic default) instead of the
  packet-module's placeholder cast-slot fields (`cooldown`, `rank`,
  `resource_cost`, `resource_type`), and `damage_type`/`detail` change to
  reflect the on-hit rider rather than the generic no-damage boilerplate.
  Zero numeric movement in priced damage (the default is 0.0 either way);
  the diff is purely structural/representational.
- **Swain P (Ravenous Flock):** stale-label fix, `out_of_scope` ->
  `no_damage`. Soul-fragment collection (permanent bonus health per
  stack, self-heal on claim), empty leveling row, `damageType: null`.
  Same Malzahar/Nasus precedent. Zero golden movement.
- **Tahm Kench E (Thick Skin):** stale-label fix, `out_of_scope` ->
  `no_damage`. All three cached effects are self-directed grey-health
  state (`affects: "Self"`) — the "Max Health Damage" leveling attribute
  on the second effect is the generic wiki parser's mislabeled name for
  the self out-of-combat heal-restore percentage, the same misparse
  pattern as Rek'Sai P (batch F precedent). The module's own SLOTS dict
  has never wired E (documented boundary predating this pass); E remains
  absent from `parse_abilities`' output, matching
  `tests/test_champion_withholdings.py`'s `"E" not in tahm_abilities`
  invariant. Zero golden movement.

## Recapture

Recapture executed after this attribution; compare re-verified identical
against the new baseline.

## Rotation-classification fix (found in full-suite validation)

The new `p_backstab` OPTION had no entry in
`src/calculator/champions/__init__.py`'s central
`_ROTATION_CLASSIFICATIONS` table, failing
`tests/test_champion_options.py::TestRotationDeclarations`'s
exhaustiveness gate (every declared option must carry a rotation
semantics declaration). Classified `"p_backstab": {"role": "self_state",
"slot": "P"}` — the same boolean self-state-gate pattern as `p_ready`,
`w_active`, and `w_already_shielded` (whether an on-hit rider currently
applies, not a setup/consume edge against another slot). Metadata-only;
re-verified golden compare stays identical and
`tests/test_champion_options.py` passes 16/16 after the fix.
