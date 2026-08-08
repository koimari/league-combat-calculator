> Historical worklist (completed E9.5 wave). Architecture references below
> predate issue #161: the `reviewed_batch_*` modules and the shared
> `packet_module` exception tables (`_PACKET_TICK_FIXES`) have since been
> dissolved into the named champion modules.

You are fixing the FINAL genuine gaps found by the E9 re-audit (E9.5 gap-fix wave) in a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-e9-fix-2 (branch codex/e9-fix-2). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

YOUR CHAMPIONS AND THE EXACT GAPS (from data/champion-audit/batch-e9-*.json, verbatim):
### Ahri
No E-series work closed Ahri's only flagged mechanic: Essence Theft (P) consumes 9 stacks to heal 35-95, listed in e3-stacks with no stack attributes; the module (ahri.py, empty ASSUMPTIONS, no P slot/option) still does not model it and Ahri is absent from HEALING_RULE_CHAMPIONS — the CP-era note ('P passive heal absent from both module and atoms') is still open and undocumented. Q/W/E/R damage rows (two-pass Q, three-flame W, charm E, three-dash R) remain fully modeled.

### Illaoi
E4-1 kept the tentacle summon damage (P tentacle procs via p_tentacles, Q command row, W, E, R) but the tentacle SELF-HEAL (5% of missing health per tentacle champion hit) is still neither modeled nor documented: Illaoi remains absent from HEALING_RULE_CHAMPIONS and the module ASSUMPTIONS never mention the heal (probe shows no Illaoi healing events). This is the exact CP-era gap, still open.

### Kled
E5-1 fixed the W rank read (4th-attack bonus now uses the actual W rank instead of clamping to level) and E8a documented the Skaarl mount pool (400-1400 HP) as a revive-boundary pattern, closing the CP-era review items on W and P. Still open and undocumented: the e8-interactions worklist lists Q (Pocket Pistol) Grievous Wounds, but kled.py declares no GRIEVOUS_WOUNDS_SOURCES and the module ASSUMPTIONS never mention it (E8b implemented only Katarina R and Varus E). R charge shield remains documented utility state.

### LeeSin
The e8 shield worklist item is now closed by the support scanner (Safeguard W shield emits 240 in a probe), but the CP-era Q two-stage gap remains: the reviewed-packets asset carries Resonating Strike (120-360 + 180% bAD) as a Q variant while reviewed_batch_03 pins Lee Sin's Q to simple_damage('Physical Damage') with no option exposed, so the recast is silently unmodeled and undocumented (probe shows only Sonic Wave). R collision splash is single-target-irrelevant; P Flurry stays a documented no-damage row.

### Naafiri
E2-2 priced Q's bleed as 10 sourced 0.5s ticks (Total Bleed == per-tick x10), but the CP-era gap items beyond the bleed are still absent and undocumented: Q's recast bonus damage (30-160 + 40-140% bAD, Minimum/Maximum Bonus Physical Damage rows) and Q's self-heal (45-105 + 40% bAD; Naafiri absent from HEALING_RULE_CHAMPIONS), plus E's Flurry explosion (60-160 + 80% bAD — the packet prices only the Dash row, dropping ~80% of E's Total). P packmate summon and W/R shields remain documented out.

### Pantheon
No E-series fix touched Pantheon (module unchanged, not in any E2-E8 partition): the CP-era gap items are all still open and undocumented — Q prices only the Hurl base (70-190 + 115% bAD + 50% AP) while the <20%-HP execute (Increased Hurl Damage 155-455 + 230% bAD + 100% AP) and the Mortal Will empowered per-level term (20-265.88) are dropped; R prices the center Magic Damage but not the Reduced edge row; and W Shield Vault emits damage (98.2 in a probe) from the %max-HP Physical Damage row read as flat despite MODULE_COVERAGE declaring W out_of_scope.

### Renata
The e3-stacks P Leverage mechanic is still neither modeled nor documented: Renata's on-hit mark deals 1-2% max-HP per level bonus magic damage but P stays out_of_scope with only the generic 'no enemy-damage formula' reason (factually wrong), and the probe shows no P damage. E Loyalty Program's Shield Strength (50-110 + 50% AP) is likewise not granted — the description marker ('Renata and allies struck are granted a shield') is not recognized as self-targeted, so the scanner drops it with no teammates. Q/E damage remain modeled; W bailout and R berserk stay documented out.

### Sion
E5-1 fixed Q (Minimum/Maximum Physical Damage rows interpolated by q_charge_fraction, default fully charged) and the W Soul Furnace shield is now emitted by the support scanner (461.4 in a probe), closing those CP-era items. Still open and undocumented from the CP-era review: E Roar of the Slayer's 25% armor reduction for 4s (present in the cache as prose, no module note) is not modeled, so all physical damage after E is overstated; P Glory in Death stays a documented no-damage row.

### Smolder
E1-b2 added the R self-heal to HEALING_RULE_CHAMPIONS (flat 100-170 + 50% bAD + 75% AP; probe: 170 heal), closing the CP-era gap's primary item. Still open and undocumented: Q's 0-75% (+0-22.5%) crit-chance damage increase and the tier-3 225-stack true-damage burn are not modeled — Q prices the flat base + summed AD ratios only, and P Dragon Practice stays out_of_scope with no boundary note tying it to the burn; E flight utility remains documented out.

### Urgot
The CP-era gap was never touched by any E-series partition (module unchanged): W Purge still prices ONE shot (12 + 20-34% AD; probe: 29.4) instead of the ~12 shots over 4s at 3.0 AS, understating his core DPS; P Echoing Flames leg on-hit (%max-HP damage) remains out_of_scope with no damage; R Fear Beyond Death's sub-25% execute/fear is unmodeled. E Disdain's shield is now emitted by the support scanner (135.0 in a probe), closing that sub-item. None of the remaining items are documented in the module.

RULES (project conventions):
- Every number must trace to data/champions.json leveling rows (or wiki prose pinned as module constants with the source cited in SOURCES/ASSUMPTIONS). NO invented values.
- Follow existing module conventions: slot parsers (engine/slotlib), options dict for player-controlled state (e.g. r_shrooms, voidling_attacks), typed accessors.
- For DoT/channel counts: use the cached per-tick + total rows (implied_ticks = total/per-tick) exactly like E2 did (packet_module._PACKET_TICK_FIXES or custom parsers).
- For heals: add the champion to HEALING_RULE_CHAMPIONS in src/calculator/healing.py ONLY if the heal is a self-heal the ledger should emit (flat or %-of-damage with sourced ratios). For %-of-missing/max health heals use the fight's live stats where the engine supports it; otherwise pin the sourced formula with the boundary documented.
- For on-hit/stack passives: use the engine's on-hit / every-Nth-hit / post_hit_proc patterns from E3 (vayne_w, varus blight).
- For multi-shot channels (Lucian R 22 shots, MF R 14-18 waves, Morgana W 10 ticks, Urgot W ~12 shots, Xerath R 6 recasts, Sion Q already done): price per-shot x sourced shot count at the sourced cadence over the fight window, exactly like E2's tick fixes.
- Add tests: tests/test_e9_fix_2.py — per champion, /api/calculate fight assertions (level 18, rank 5, R rank 3, no items, 0 resists) with expected values recomputed from the cached leveling rows + the fight's own stats.
- Run gates in the worktree: pytest tests/test_e9_fix_2.py; pytest -q (full); pylint src/ --fail-under=9; black --check src/ tests/; golden — re-capture scripts/golden_baseline.json ONLY if fight totals change, explaining every diff (these ARE behavior fixes, so expect diffs for your champions).
- Commit "feat(E9-2): close final audit gaps for Ahri, Illaoi, Kled, LeeSin, Naafiri, Pantheon, Renata, Sion, Smolder, Urgot" and push origin/codex/e9-fix-2. Do NOT merge. Do not touch data/champion-audit/.
- Reply to parent: per champion — the wrong row/mechanic, the corrected sourced formula + count, test result, gates, golden diffs explained, commit SHA.