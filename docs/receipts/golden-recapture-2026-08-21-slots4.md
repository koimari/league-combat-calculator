# Golden recapture — roadmap slot session 3 wave 2 (Kindred, Lulu, Miss Fortune), 2026-08-21

Pre-recapture compare: 24 diffs, ALL Miss Fortune, zero unattributed.
Kindred and Lulu closures were label/no_damage-only and produced zero
golden movement (verified identical before the MF work landed).

## Miss Fortune (24)
Root cause: P (Love Tap) modeled as on_hit max_procs=1, total-AD ratio by
level from the game binary's ByCharLevelBreakpoints (L1 0.5, +0.1 at
4/7/9/11/13/20/25/30; wiki 6-tier row cross-checks tiers 1-6). W (Strut)
closed as no_damage with an AS-window receipt (the engine's timed-AS path
is Q-slot-hardcoded; documented, not modeled).
- on_hit_ability_passive new rows: L11 = 0.9 x 76 total AD x 100/150
  (50 armor) x 1 proc = 45.60 exactly; L18/L20 rows scale by the same
  formula at 1.0/1.1 ratios.
- total_damage rows: += the same single-proc amounts.
- Remaining rows: structural zero/row-presence changes from the W
  no_damage reclassification.

Recapture executed after this attribution; compare re-verified identical.
