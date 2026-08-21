# Golden recapture — roadmap session 4 batch B, 2026-08-21

Champions: Blitzcrank, Camille, Cassiopeia, Cho'Gath, Dr. Mundo (one
out_of_scope slot each — the single passive P — dispositioned this batch).

Pre-recapture compare: 2 diffs, partitioned exactly 1 Cassiopeia +
1 Cho'Gath, zero unattributed, ZERO numeric movement — each diff is a
structural zero-damage row (a reclassified slot now emits an explicit 0.0
entry instead of staying silently absent):

- `/champion_baselines/Cassiopeia/abilities_level_11/passive`: `<absent>` ->
  sourced zero-damage entry ("Serpentine Grace", 6-40% MS-bonus
  effectiveness by level — no positioning/MS-to-damage kernel in this
  calculator).
- `/champion_baselines/Chogath/abilities_level_11/passive`: `<absent>` ->
  sourced zero-damage entry ("Carnivore", kill-triggered heal/mana — the 1v1
  model has no minion kills and no kill receipt).

Blitzcrank and Camille show ZERO diffs: both P slots (Mana Barrier, Adaptive
Defenses) were reclassified out_of_scope -> modeled with no SLOTS/code
change — the shield damage was already fully modeled via their Q/W
`attach_self_shield` payloads, so MODULE_COVERAGE was corrected without
altering any parse output.

Dr. Mundo: OPEN, untouched. Its P (Goes Where He Pleases) is pinned
`out_of_scope` by a pre-existing 1700+-line xfailed TDD contract
(`tests/test_dr_mundo_passive.py`, "P2 Slice 8", S1-S17) for a larger,
separately-scoped canister/cleanse-kernel immunity project — reclassifying
it here would break that contract rather than close a slot. No golden
movement, by construction.

Dispositions (per-champion evidence in each module's ASSUMPTIONS):
- Blitzcrank P (Mana Barrier): modeled — shield priced via Q's
  `attach_self_shield`, live-tested in `test_e8_shields.py`.
- Camille P (Adaptive Defenses): modeled — shield priced via W's
  `attach_self_shield`, live-tested in `test_e8_shields.py`.
- Cassiopeia P (Serpentine Grace): no_damage — pure MS-bonus-effectiveness
  state, no positioning/MS-to-damage kernel exists in this calculator.
- Cho'Gath P (Carnivore): no_damage — kill-triggered heal/mana only; the
  boundary is already documented verbatim in
  `tests/test_e1_healing_b3.py` ("the 1v1 model has no minion kills and no
  kill receipt").
- Dr. Mundo P (Goes Where He Pleases): OPEN — named receipt
  `tests/test_dr_mundo_passive.py`, no code change.

Neither Cassiopeia nor Cho'Gath is in `rotation_resolver.COMBO_TABLE`'s
cast order for P (Cassiopeia's `_CAST_SLOTS` structurally excludes P;
Cho'Gath is not in `COMBO_TABLE` at all) — no combo-table edit needed, no
f2/f3 rotation-order addendum required (unlike the Aatrox/Aphelios case in
slots6).

Recapture executed after this attribution; compare re-verified identical.
