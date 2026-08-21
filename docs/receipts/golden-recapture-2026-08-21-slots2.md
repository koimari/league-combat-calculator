# Golden recapture — roadmap slot session 2 finale (Shen + Singed), 2026-08-21

Pre-recapture compare: 63 diffs, partitioned exactly 60 Singed + 3 Shen,
zero unattributed.

## Singed (60)
Root cause: R (Insanity Potion) modeled as a BUFF-phase stat_buff feeding
Q/E AP ratios. Consumer audit trimmed the buff to the two keys with proven
consumers: ability_power (Q/E parse) and move_speed (item_state_receipts
move-speed gates). bonus_armor / bonus_magic_resistance have no consumer in
calculate_fight_damage and are recorded as sourced-but-unmodeled in
ASSUMPTIONS alongside the regen/Grievous riders (module's own no-consumer bar).
- abilities_level_11/Q: 15.0 -> 20.84375 = 15.0 + 0.10625 x 55 (R rank-2 AP)
- abilities_level_11/E: 70.0 -> 100.25 = 70.0 + 0.55 x 55
- abilities_level_11/R: cooldown 0.0 -> 100.0 (sourced ability JSON cooldown
  row via extract_cooldown; the no_formula parser hardcoded 0.0 - same quirk
  Olaf R documents) + new detail/stat_buff fields
- registered_champion_fights/Singed/*: downstream ripples of the same Q/E
  increase through proc/threshold math (Luden's, Shadowflame rows)

## Shen (3)
Root cause: P (Ki Barrier) modeled as a post-spell self-shield; W (Spirit's
Refuge) closed as a no_damage protective-zone row.
- abilities_level_11/E/self_shield_events: new Ki Barrier row (89.94 for
  2.5s, sourced per-level shield leveling; pinned by tests/test_shen.py
  incl. a live API absorption end-to-end)
- abilities_level_11/E/detail: same change, prose
- abilities_level_11/W: new baseline row (cooldown 13.0, blocks
  non-turret projectiles; no damage numbers - atoms-confirmed)

Recapture executed after this attribution; compare re-verified identical.
