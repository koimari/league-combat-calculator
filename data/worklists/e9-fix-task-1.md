You are fixing the FINAL genuine gaps found by the E9 re-audit (E9.5 gap-fix wave) in a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-e9-fix-1 (branch codex/e9-fix-1). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

YOUR CHAMPIONS AND THE EXACT GAPS (from data/champion-audit/batch-e9-*.json, verbatim):
### Lucian
CP-era gap NOT closed: R (The Culling) is still priced as ONE shot (packet base 15/30/45 + ratios) while the wiki cache carries up to 22 shots over the 3s channel ('Physical Damage Per Shot' row, count unset) — a ~20x undercount of the ability's damage. P Lightslinger's second-shot damage (50-60% AD per ability) is also declared out_of_scope with the generic 'no enemy-damage formula' reason although the wiki P is a damaging on-attack mechanic; neither carries a boundary note in the module. Q/W packets are correct single-instance reads; E dash documented. Verdict: gap (R channel count + P double-shot).

### MissFortune
New module (no CP-era entry) but gap: E2 fixed E (Make It Rain) to 8 sourced ticks, but R (Bullet Time) still prices ONE wave (packet base 20/30/40 + ratios) while the wiki cache carries 'Total Waves' 14/16/18 and 'Maximum Total Physical Damage' 280/500/720 — a ~14-18x undercount with no boundary note anywhere in the module. Q double-up modeled; P Love Tap and W Strut documented out_of_scope. Verdict: gap (R wave count).

### Morgana
CP-era gap NOT closed: W (Tormented Shadow) still prices ONE tick (packet base 18-70 = 'Maximum Damage Per Tick') while the wiki carries 'Maximum Total Damage' 180-700 over the 5s/10-tick storm (~10x undercount); R (Soul Shackles) prices only the initial hit (200-350) while the wiki's 'Total Magic Damage' 400-700 includes the second tether-break hit; and P Soul Siphon spellvamp is unmodeled (Morgana absent from HEALING_RULE_CHAMPIONS, P declared no_damage). No boundary note for any of these in the module. Verdict: gap (W ticks, R second hit, P heal).

### Nunu
New module (no CP-era entry) but gap: Q (Consume) is priced from the 'Non-Champion True Damage' row (400-1200) — the wrong basis for a champion-combat calculator — while the wiki cache effect[2] carries 'Champion Magic Damage' 60-220 + 65% AP + 5% bonus HP (plus champion heal rows), which the module ignores with no note. E2 fixed E to the 3-snowball volley; W/R damage modeled. Verdict: gap (Q champion-damage basis).

### Talon
CP-era gap NOT closed: P (Blade's End) is declared out_of_scope with the generic 'no enemy-damage formula' reason although the wiki cache carries the per-level bleed damage (80-303.53 + 210% bonus AD on the 3-stack consume) — Talon's main burst finisher is silently absent. Q's self-heal is also unmodeled (Talon absent from HEALING_RULE_CHAMPIONS). W two-hit and R modeled; E parkour documented. Verdict: gap (P bleed + Q heal).

### Warwick
CP-era gap NOT closed: R (Infinite Duress) is declared no_damage with the generic 'no enemy-damage formula' reason although the wiki cache carries 'Total Magic Damage' 175/350/525 + 167% bonus AD over the 1.5s channel (3 on-hit applications) — and healing.py already has an R 100%-heal rule that can never fire because the module emits no R damage events. Q damage + Q heal modeled (verified 86.1 heal at level 18); W/E/P documented out_of_scope. Verdict: gap (R damage).

### Teemo
E2-3/E4 fixed R: Noxious Trap now prices the full 4-tick poison DoT (per-tick x4 == Total Magic Damage) with the r_shrooms trap-count option (verified via /api/calculate probe at level 18, no items: r_shrooms=2 → R 612.5 total) and trap placement/arm time documented as state. The CP-era gap item for E remains UNCLOSED: Toxic Shot's packet prices only the on-hit (9-65 + 5% bAD + 30% AP; parse E 65.0 at rank 5) while the cached JSON's Magic Damage per Tick (6-30 + 2.5% bAD + 10% AP) and Total Poison Damage (24-120 + 10% bAD + 40% AP) rows are not expressed and the module has no boundary note for the poison half of the ability — verdict stays gap.

### Rumble
The heat/Danger Zone system remains documented out_of_scope (P/W no_damage rows; the CP-era review already noted rotation numbers assume no heat state), but a NEW unmodeled-and-undocumented pricing issue fails the audit: R The Equalizer is priced as ONE tick of the Burning DoT (packet base 30/50/70 + 8.75% AP per 0.25s tick) while the cached wiki rows give Maximum Magic Damage 600/1000/1400 (20 ticks up to 5s) — the E3-stacks worklist entry for Rumble R flags this field DoT and the module has no tick count and no boundary note, so R is understated ~20x. Q/E damage packets are correct. Verdict downgraded to gap until the R DoT pricing is fixed or documented.

RULES (project conventions):
- Every number must trace to data/champions.json leveling rows (or wiki prose pinned as module constants with the source cited in SOURCES/ASSUMPTIONS). NO invented values.
- Follow existing module conventions: slot parsers (engine/slotlib), options dict for player-controlled state (e.g. r_shrooms, voidling_attacks), typed accessors.
- For DoT/channel counts: use the cached per-tick + total rows (implied_ticks = total/per-tick) exactly like E2 did (packet_module._PACKET_TICK_FIXES or custom parsers).
- For heals: add the champion to HEALING_RULE_CHAMPIONS in src/calculator/healing.py ONLY if the heal is a self-heal the ledger should emit (flat or %-of-damage with sourced ratios). For %-of-missing/max health heals use the fight's live stats where the engine supports it; otherwise pin the sourced formula with the boundary documented.
- For on-hit/stack passives: use the engine's on-hit / every-Nth-hit / post_hit_proc patterns from E3 (vayne_w, varus blight).
- For multi-shot channels (Lucian R 22 shots, MF R 14-18 waves, Morgana W 10 ticks, Urgot W ~12 shots, Xerath R 6 recasts, Sion Q already done): price per-shot x sourced shot count at the sourced cadence over the fight window, exactly like E2's tick fixes.
- Add tests: tests/test_e9_fix_1.py — per champion, /api/calculate fight assertions (level 18, rank 5, R rank 3, no items, 0 resists) with expected values recomputed from the cached leveling rows + the fight's own stats.
- Run gates in the worktree: pytest tests/test_e9_fix_1.py; pytest -q (full); pylint src/ --fail-under=9; black --check src/ tests/; golden — re-capture scripts/golden_baseline.json ONLY if fight totals change, explaining every diff (these ARE behavior fixes, so expect diffs for your champions).
- Commit "feat(E9-1): close final audit gaps for Lucian, MissFortune, Morgana, Nunu, Talon, Warwick, Teemo, Rumble" and push origin/codex/e9-fix-1. Do NOT merge. Do not touch data/champion-audit/.
- Reply to parent: per champion — the wrong row/mechanic, the corrected sourced formula + count, test result, gates, golden diffs explained, commit SHA.