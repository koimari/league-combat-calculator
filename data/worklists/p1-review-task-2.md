You are ELIMINATING the remaining 'review' audit status for your champions (P1: zero-review push) in a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-p1-2 (branch codex/p1-review-2). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

YOUR CHAMPIONS (10):
Aphelios, Karthus, Lulu, MasterYi, Nautilus, Rell, Shaco, Udyr, Viktor, Yunara

THE MANDATE (user): "we should have nothing in review. we should make it ready since we have atomized everything, it should be computable and deterministic."

FOR EACH CHAMPION — the review item and the exact mechanic to make deterministic (from data/champion-audit/batch-e9-*.json gap_summaries, verbatim below):
### Aphelios
E1 closed the primary gap: Severum's post-mitigation lifesteal heal is modeled in healing.py and fires in /api/calculate (18.7 per auto at level 18, weapon selectable via aphelios_main_weapon). The overheal-to-shield conversion of that heal (wiki P: excess heal becomes a shield) remains unmodeled with no module note. Onslaught attack-count rule, other weapon Q forms and R blast modeled; weapon follow-up attacks documented as a coverage boundary. Verdict: review (overheal shield only).

### Karthus
Alive-state damage was already fully modeled (W MR shred applied before damage, Q isolated-vs-shared formula, E exact tick count with mana cost, R after the 3s channel) and remains correct; the E-series added nothing for Karthus. The only excluded family is Death Defied (P) — post-death channel + AoE — which remains explicitly unmodeled but DOCUMENTED as a deliberate boundary in ASSUMPTIONS and the module docstring ('certified alive-state one-rotation package'); whether post-death casting belongs in scope is a human/product decision, so the verdict stays review. Verified via /api/calculate probe at level 18, no items: e_ticks=5 resolves (total_damage 496.9).

### Lulu
E8d closed the E shield item (Help, Pix! Shield Strength is emitted as an ally-support event), but the CP-era review's main open question persists: P Pix bolt damage (3 bolts per auto, 5-39 + 5% AP each) is still unmodeled — P stays out_of_scope with only the generic packet reason, and the auto-attack policy adds no Pix bolts (probe sources show only Q and E). Q damage and E damage are modeled; W/R remain documented out.

### MasterYi
E3 closed the stack gap: Double Strike is an every-3rd-hit ONHIT slot (50%-AD second strike, autos-only per wiki). Q/E damage modeled. The W Meditate self-heal remains unmodeled (Master Yi absent from HEALING_RULE_CHAMPIONS) — flagged in the E5 worklist as lower severity because W is a defensive channel, but no module boundary note exists. Verdict: review (Meditate heal).

### Nautilus
E5-2 fixed P (Staggering Blow now prices the sourced 14-128 per-level on-hit instead of the root-duration row mis-read as flat). Still open from the CP-era review: W Titan's Wrath prices only one Magic Damage per Instance (probe: 23.0) instead of the Total Magic Damage (30-70 + 40% AP) of the two-instance Pain of Wrath, and R prices the chase-eruption Magic Damage row (probe: 148.0 at rank 3) rather than the primary-target Increased Damage (150-400 + 80% AP) — neither read is documented in the module; the W shield is now emitted by the support scanner (371.5 in a probe).

### Rell
E2 closed the R Magnet Storm tick total (8 sourced 0.25s ticks) and Q/W variant pricing works (w_variant: mount-up 355.0 vs crash-down 410.0 at level 18). Remaining review items from CP era: P Break the Mold on-hit (5% armor + 5% MR) declared out_of_scope despite a real damage formula, W shield unmodeled, and E Full Tilt is a formula_slot in the packet manifest yet marked out_of_scope in MODULE_COVERAGE (inconsistency). Verdict: review.

### Shaco
E4 closed the summon gap: W Jack in the Box prices the full sprung volley of Increased-Damage shots (w_box_attacks; 10 -> 692.5 vs 1 -> 310.0 at level 18) with CC/fear documented as state. Remaining review items: E Two-Shiv Poison prices only the base Magic Damage row (the wiki Increased-Damage execute row vs <30% HP targets is unmodeled) and R's controllable clone is not expressed (only the death-explosion damage is priced). Verdict: review.

### Udyr
E1/E2 closed the core gaps: W Iron Mantle heal streams (verified 178.9 at level 18) and R Wingborne Storm 8-tick total are modeled. Q Wilding Claw remains out_of_scope in MODULE_COVERAGE despite the packet manifest carrying a Q wiki_attribute (Max Health Damage) — the E5 worklist flags the same inconsistency; the Awaken self-heal and W shield also remain unmodeled (Udyr's heal rule covers the stance streams). Verdict: review (Q empowered attacks).

### Viktor
E2 closed the R gap: Arcane Storm prices impact + 6 storm ticks (Magic Damage + 6 x per-tick == Total). Q Siphon Power still prices only the projectile (60-120 + 40% AP): the Discharge empowered-auto on-hit (Modified/Total Magic Damage rows) and the Q shield remain unmodeled with no in-module note (the CP-era review flagged it as a judgment call). W cc and P augments documented out_of_scope. Verdict: review (Q discharge + shield).

### Yunara
No E-series fix touched Yunara (module unchanged): the CP-era review items persist — W prices only the initial impact (55-215 + 85% bAD + 50% AP) while the lingering-bead DoT (15% of impact per 0.25s; 'Linger Magic Damage per Tick'/'Total Expanded Damage' rows in the cache) is dropped, and R is priced as the empowered Arc of Ruin base (160/320/480, no ratio) rather than a buff — both undocumented in the module. Q/E rows and the minion-only execute notes are modeled.

HOW TO CLOSE EACH (choose the sourced, deterministic path):
1. If the cached data/champions.json leveling rows or wiki prose carry a formula (flat + ratios, per-level arrays, %max/%missing health terms, per-tick totals), implement it in the module with the codebase's typed accessors/options conventions. Player-controlled state (stacks, procs, charges, uptime, empowered choices) becomes an OPTION with the sourced default and exact formula — the fight is deterministic given the option.
2. Heals/shields/revives go through src/calculator/healing.py (HEALING_RULE_CHAMPIONS) or the E8c self_shield_events / E8d ally-support interfaces — follow the existing patterns (grey health, _heal_from_damage, later_target_amount).
3. On-hit / empowered-auto / proc mechanics use the engine's on-hit, every-Nth-hit, empowers_next_auto, post_hit_proc patterns (Vayne W, Varus Blight, Akshan double_shot precedents).
4. Multi-part abilities (two-pass, bounces, lingering DoTs, shield+damage, buffs that feed other abilities) price EVERY sourced part with authored timing (time_offset / hit_interval / dot_duration), like the E2/E5 conventions.
5. A mechanic may remain non-priced ONLY if it is genuinely inexpressible in a deterministic single-target fight (e.g. an enemy-projectile reflection with no modeled enemy source, a death-only trigger) — then it must be a DOCUMENTED option or zero-damage receipt with a sourced reason, and the champion still gets verdict 'ok' ONLY if nothing damage-relevant is silently absent. If you cannot close an item deterministically, keep verdict 'review' and say exactly why in your reply (do not fake 'ok').
6. Update the champion's audit entry in a NEW file data/champion-audit/batch-p1-2.json: {"ChampionName": {"verdict": "ok", "gap_summary": "<what was closed + source formula + test evidence>", "module": "<name>.py", "slots": {...}}} — for EVERY one of your 10 champions.

TESTS: tests/test_p1_review_2.py — per champion, /api/calculate assertions (level 18, rank 5, R rank 3, no items, 0 resists) with expected values recomputed from the cached leveling rows + the fight's own stats; plus one probe per new option.

GATES (in worktree): pytest tests/test_p1_review_2.py; pytest -q (full); pylint src/ --fail-under=9; black --check src/ tests/; golden — re-capture scripts/golden_baseline.json ONLY if fight totals change, explaining every diff (these ARE behavior fixes; expect diffs for your champions).
COMMIT "feat(P1-2): zero-review closures for Aphelios, Karthus, Lulu, MasterYi, Nautilus, Rell, Shaco, Udyr, Viktor, Yunara" and PUSH origin/codex/p1-review-2. Do NOT merge. Do NOT touch data/champion-audit/batch-e9-* (write batch-p1-2.json only).
Reply to parent: per champion — the closed mechanic + source formula + option added, test result, gates, golden diffs explained, commit SHA; and any champion you could NOT close (with the exact blocker).