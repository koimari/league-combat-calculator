> Historical worklist (completed E9.5 wave). Architecture references below
> predate issue #161: the shared `packet_module` exception tables
> (`_PACKET_TICK_FIXES`) have since been dissolved into the named
> champion modules.

You are fixing the FINAL genuine gaps found by the E9 re-audit (E9.5 gap-fix wave) in a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-e9-fix-3 (branch codex/e9-fix-3). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

YOUR CHAMPIONS AND THE EXACT GAPS (from data/champion-audit/batch-e9-*.json, verbatim):
### Shyvana
The CP-era review flagged W's shield strength (60-140 + 12% bonus health) and dragon-form self-heal (60-104.71 by level + 4-8.47% missing health when the recast hits a champion) as unmodeled; neither E-series workstream addressed them (Shyvana is absent from HEALING_RULE_CHAMPIONS and from the E8c shield set) and the module's ASSUMPTIONS only loosely cover 'the shield and movement utility' — the dragon-form W heal has NO boundary note at all, while the cached JSON carries an explicit Heal row. The damage model (Scalemail stacks, dragon Q/E options, W recast) is verified working via /api/calculate probe (scalemail_stacks=10 + dragon_form=True resolves, total_damage 506.5), but the unmodeled, undocumented W heal/shield family keeps this at gap.

### Sejuani
The CP-era audit rated Sejuani ok but noted W's second swing uncertainty ('not accounted for if the wiki_attribute is per-swing'); this re-audit confirms the misprice: W Winter's Wrath is read via wiki_attribute 'Physical Damage' which resolves ONLY the first swing row (5-45 + 30% AP + 4% max HP — and even the %max-HP term does not resolve), while the cached JSON also carries the second swing (5-85 + 60% AP + 8% max HP) and the Total Physical Damage row (10-130 + 90% AP + 12% max HP). Parse shows W total 45 at rank 5 vs a 130+ total in-game — the reviewed packet prices the ability incorrectly, so the verdict moves to review. P/E/Q/R damage packets remain correct; mark-stack and CC are documented state.

### Sivir
The CP-era audit rated Sivir ok ('Q two-way Boomerang Blade'), but this re-audit finds the reviewed packet prices Q incorrectly: the packet reads the single-pass 'Physical Damage' row (60-160 + 70% bAD + 60% AP at rank 5 → 160), while the cached JSON's Total Maximum Champion Damage row (120-320 + 140% bAD + 120% AP) and the in-game two-way boomerang both confirm the blade hits out AND back for 2x — parse shows Q total 160 vs 320 in-game, a ~2x understatement with no boundary note. W Ricochet bounce is modeled; P/E/R are documented out_of_scope (E spell shield, R team buff). Verdict moves to review for the reviewed-packet Q misprice.

### Xerath
The CP-era audit rated Xerath ok, but this re-audit finds the reviewed packet prices R incorrectly: Rite of the Arcane's packet reads the per-shot Magic Damage row (170/220/270 + 45% AP) and prices ONE shot, while the cached JSON carries Number of Recasts 4/5/6 and Total Magic Damage 680/1100/1620 (+180/225/270% AP) — parse R 270.0 at rank 3 vs 1620.0 in-game, a ~6x understatement with no boundary note, and the E3-stacks worklist entry (Maximum Stacks / Increased Damage per Stack) is unaddressed. Q (max-charge, documented), W and E packets are correct; P mana restore is out_of_scope. Reviewed packet prices R incorrectly — verdict review.

### Viego
No E-series workstream changed Viego (E8d's possession note is the only touch). This re-audit confirms and extends the CP-era review: the reviewed packet prices Q and R as health-ratio terms ONLY — Q resolves just the passive %current-HP on-hit (the active 25-85 + 70% AD physical damage row and the mark-consuming second strike are dropped; parse Q 0.0) and R resolves only the %missing-health bonus 12-20% + 5%/100 bAD (the 120% AD crit-scaled base strike is dropped; parse R 202.5 at 50% missing vs ~382.5 in-game), so both abilities are understated with no boundary notes. W damage is correct, E/P are documented out_of_scope, and the possession/transform mechanic is documented as inherently out of scope. Reviewed packet still prices abilities incorrectly — verdict review.

### Sett
E3-2 implemented the Pit Grit combo (p_right_punches option prices the Right Punch bonus 5-100 by level + 55% bAD; verified via /api/calculate probe at level 18, no items: p_right_punches=6 → P 705.0). The CP-era reviewed-packet pricing issues remain: W Haymaker is typed magic when its center-line damage is true damage and its grit term (25% per 100 bAD of expended Grit) does not resolve (W total 160 flat only), Q prices one of the two empowered attacks (Bonus Physical Damage read once), and the W grit shield is unmodeled — none have boundary notes. Per the rules a reviewed packet still pricing abilities incorrectly stays review.

### Poppy
E5-2 closed the main CP-era item: P Iron Ambassador now prices the flat per-level Bonus Magic Damage (20-198.82 on the empowered buckler auto) instead of the misread %max-HP shield row, with the buckler-retrieval shield documented as non-damage in ASSUMPTIONS (test_poppy_p_prices_the_flat_bonus_magic). Q double-hit, W, and E keep the reviewed packets. One reviewed-packet pricing issue remains: R Keeper's Verdict is priced at the uncharged 100-200 + 45% bAD row while the charged 200-400 + 90% bAD branch (a charge-state variant the E3 worklist flags) is not modeled and has no boundary note — per the rules a reviewed packet still pricing an ability incorrectly stays review.

### Yone
E3-2 implemented the Q Gathering Storm stack system (q_gathering_storm option: Q3 at 2 stacks keeps the sourced damage with the knock-up as CC state; test_yone_q3_gathering_storm_keeps_sourced). The core CP-era gap remains OPEN: E Soul Unbound's Damage Stored wiki_attribute still emits 0.0 true damage at every rank (verified: E total_raw 0.0; the 25-35% of-damage-dealt row has no damage context in the static read), so Yone's signature death-mark reapplication contributes nothing — the module only states it 'keeps the reviewed packet's Damage Stored row', with no boundary note explaining the 0 contribution. P crit conversion and W self-shield remain unmodeled without boundary notes. Reviewed packet still prices E incorrectly — verdict review.

### Velkoz
E3-1 closed the primary CP-era gap: P Organic Deconstruction now prices the 3-stack consume (per-level 35-197.06 + 60% AP; parse P 180.0 at level 18, test_three_stack_consume_is_level_scaled_true). Q/W/E damage packets are correct. Two documented boundaries keep it at review: R Life Form Disintegration Ray keeps the reviewed packet's SINGLE-tick pricing (base 34.62-71.15 = per-tick row) with the full 13-tick channel (Maximum Damage 450-925) and the Researched true-damage conversion explicitly documented as not modeled in ASSUMPTIONS — a reviewed packet that still prices the channel at one tick; W's 2-charge ammo is modeled as a recharge without a charge-count option. CP-era gap closed, documented residuals remain.

### Rammus
The e5-mismodeled W item was never fixed (Rammus is not in the E5 partition): the reviewed packet still prices Defensive Ball Curl from the Bonus Armor row as magic damage (probe: 75.1, i.e. 47 + 60% armor against MR) while the actual thorns damage (15 + 10% total armor + 10% total MR) has no leveling row in the cache — a reviewed packet pricing an ability incorrectly, and the mis-read is not documented. Q and R rows match; E taunt and P spiked-shell remain documented out.

RULES (project conventions):
- Every number must trace to data/champions.json leveling rows (or wiki prose pinned as module constants with the source cited in SOURCES/ASSUMPTIONS). NO invented values.
- Follow existing module conventions: slot parsers (engine/slotlib), options dict for player-controlled state (e.g. r_shrooms, voidling_attacks), typed accessors.
- For DoT/channel counts: use the cached per-tick + total rows (implied_ticks = total/per-tick) exactly like E2 did (packet_module._PACKET_TICK_FIXES or custom parsers).
- For heals: add the champion to HEALING_RULE_CHAMPIONS in src/calculator/healing.py ONLY if the heal is a self-heal the ledger should emit (flat or %-of-damage with sourced ratios). For %-of-missing/max health heals use the fight's live stats where the engine supports it; otherwise pin the sourced formula with the boundary documented.
- For on-hit/stack passives: use the engine's on-hit / every-Nth-hit / post_hit_proc patterns from E3 (vayne_w, varus blight).
- For multi-shot channels (Lucian R 22 shots, MF R 14-18 waves, Morgana W 10 ticks, Urgot W ~12 shots, Xerath R 6 recasts, Sion Q already done): price per-shot x sourced shot count at the sourced cadence over the fight window, exactly like E2's tick fixes.
- Add tests: tests/test_e9_fix_3.py — per champion, /api/calculate fight assertions (level 18, rank 5, R rank 3, no items, 0 resists) with expected values recomputed from the cached leveling rows + the fight's own stats.
- Run gates in the worktree: pytest tests/test_e9_fix_3.py; pytest -q (full); pylint src/ --fail-under=9; black --check src/ tests/; golden — re-capture scripts/golden_baseline.json ONLY if fight totals change, explaining every diff (these ARE behavior fixes, so expect diffs for your champions).
- Commit "feat(E9-3): close final audit gaps for Shyvana, Sejuani, Sivir, Xerath, Viego, Sett, Poppy, Yone, Velkoz, Rammus" and push origin/codex/e9-fix-3. Do NOT merge. Do not touch data/champion-audit/.
- Reply to parent: per champion — the wrong row/mechanic, the corrected sourced formula + count, test result, gates, golden diffs explained, commit SHA.