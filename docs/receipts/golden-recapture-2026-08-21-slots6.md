# Golden recapture — roadmap session 4 batch A, 2026-08-21

Champions: Aatrox, Akshan, Aphelios, Ashe, Aurora (one out_of_scope slot each,
all closed as no_damage with sourced evidence).

Pre-recapture compare: 53 diffs, partitioned exactly 1 Aatrox + 17 Akshan +
1 Aphelios + 17 Ashe + 17 Aurora, zero unattributed, ZERO numeric movement -
every diff is a structural zero-damage row (a reclassified slot now emits an
explicit 0.0 entry instead of staying silently absent). The 1-diff champions
(Aatrox E, Aphelios E) have baseline-only rows; the 17-diff champions add the
zero row across the 16 fight scenarios + baseline.

Dispositions (all no_damage, per-champion evidence in the module ASSUMPTIONS):
- Aatrox E (Umbral Dash): heal-passive already priced via derive_self_healing;
  dash has zero enemy-damage rows.
- Akshan W (Going Rogue): stealth/mark/mana text; the Bonus MS leveling row is
  documented sourced-but-unmodeled (no default-on consumer, Singed bar).
- Aphelios E (Weapon Queue System): pure UI affordance, leveling [] on both
  effect rows - not a weapon-cycling mechanic needing options.
- Ashe E (Hawkshot): vision/charge utility, zero leveling rows; the
  boundary pin in test_ashe_q_active_window.py re-pinned to no_damage.
- Aurora W (Across the Veil): invisibility + Bonus MS rows, both non-damage;
  MS rider documented per the Akshan precedent.

Recapture executed after this attribution; compare re-verified identical.

## Addendum — override-seed rotation orders (Aatrox, Aphelios)

Root cause: both champions use hand-authored ComboRule orders in
rotation_resolver.py that predate the E-slot reclassifications; derived-path
champions include no_damage slots automatically. Appended "E" to both orders
for convention consistency. Second compare: 32 diffs (16 Aatrox + 16
Aphelios), every one an additive breakdown_totals/E -> 0.0 row; zero numeric
movement (Q/W/R/auto totals byte-identical). Recaptured; identical.
