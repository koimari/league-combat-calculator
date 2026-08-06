You are ELIMINATING the remaining 'review' audit status for your champions (P1: zero-review push) in a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-p1-3 (branch codex/p1-review-3). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

YOUR CHAMPIONS (10):
Briar, Kindred, Lux, Mel, Neeko, Riven, Skarner, Varus, Vladimir, Zac

THE MANDATE (user): "we should have nothing in review. we should make it ready since we have atomized everything, it should be computable and deterministic."

FOR EACH CHAMPION — the review item and the exact mechanic to make deterministic (from data/champion-audit/batch-e9-*.json gap_summaries, verbatim below):
### Briar
E1-b6 added the Chilling Scream per-tick heal to HEALING_RULE_CHAMPIONS (4 sourced ticks, verified in a probe), so the E heal is now modeled at the engine layer despite the module ASSUMPTION text saying 'all healing skipped'. Still unmodeled and documented as boundaries: P bleed self-heal (25% of damage dealt), Blood Frenzy/W life steal and Snack Attack heals, R life-steal healing, and E charge damage-reduction; the module explicitly lists each in ASSUMPTIONS. Bleed, Q/W/E/R damage and the R explosion are modeled.

### Kindred
E3/E4/E1 closed most gaps: Mark stacks (marks), Mounting Dread 3-stack pounce (e_stacks), Wolf's Frenzy summon damage (w_attacks) and the Lamb's Respite end-of-zone heal (healing.py; verified 375.0 at level 18) are all modeled. The W passive Hunter's Vigor heal at 100 stacks remains unmodeled with no module boundary note (only the CP-era/E5 worklist mention it). Q and R are documented out_of_scope rows. Verdict: review (minor W-passive heal).

### Lux
No E-series workstream touched Lux: Q/E/R damage packets remain correct, while P Illumination proc damage (30-200 + 35% AP on post-ability autos) and W Prismatic Barrier shields stay declared out_of_scope in MODULE_COVERAGE with no compensating auto hook. The E3 stack worklist lists Lux P/W but the stack implementation batches did not include her, so the CP-era review items remain open: whether the P proc and W shield belong in the single-target rotation is a documented-but-undecided scope question. Verdict unchanged: review.

### Mel
E5-2 fixed the W mis-read (Replicated Projectile modifier is a % of an unmodeled enemy projectile — now prices no damage and is documented) and R now prices the flat Magic Damage row plus the (4/7/10 + 4% AP)-per-stack Overwhelm term (r_overwhelm_stacks option). Remaining CP-era partial reads are unfixed and undocumented: Q prices only the Initial Explosion row (the 6-10-bolt volley's Total Magic Damage row is dropped) and E prices only the orb hit (the solar-field per-second DoT 16-64 is dropped). The P stored-damage execute is documented as a kill boundary.

### Neeko
No E-series workstream touched Neeko (E4 lists her W clone but the summon implementation batches did not include her; E3 lists Shapesplitter informatively). Q/W/E/R damage packets remain modeled (Q initial hit only — the 35-135 + 25% AP subsequent bounces are not priced), and P disguise, W clone/stealth, and the R shield stay out_of_scope per MODULE_COVERAGE, which is documentation but leaves the CP-era review items open (Q bounce damage and R shield are damage/defense-relevant, undecided scope). Verdict unchanged: review.

### Riven
E5-2 fixed P Runic Blade (empowered autos now deal the sourced 30-46.76% AD bonus as an on-hit), closing the CP-era review's P item. Still open from the same review and undocumented: R1 Blade of the Exile's AD buff (20/25/30% bonus AD for 15s) is not expressed — the R slot prices only the Wind Slash (300-600 + 165% bAD) — so all physical damage in the ult window is understated; E Valor shield stays documented no_damage.

### Skarner
E2 closed the Q mis-price: Shattered Earth prices all three empowered hits (Bonus Physical Damage per Hit x3 == Total; verified upheaval 395.0 vs shatter 390.0 at level 18). P max-HP DoT, W damage and R Impale modeled. Remaining review items: W's 8%-max-HP shield unmodeled, and E (Ixtal's Impact) is a formula_slot in the packet manifest yet declared out_of_scope in MODULE_COVERAGE (inconsistency). Verdict: review.

### Varus
E3-1 closed the core CP-era gap: the Blight stack/detonation system is implemented — W is an on-hit passive applying stacks, Q prices the fully-charged arrow plus one detonation of the blight_stacks option (per-stack %max-HP row; test_blight_stacks_option_seeds_the), and E is correctly typed physical with its Grievous Wounds window (E8b). Verified via /api/calculate probe at level 18, no items: blight_stacks=3 resolves (total_damage 520.0). Two documented/undocumented residuals keep it at review: Q's 0-50% charge scaling is documented as priced at Maximum, but the W active charged-shot empower (bonus magic damage equal to 6-21% of target's MISSING health on the next Q) remains unmodeled with no boundary note; E/R also detonate in-game but are conservatively not double-priced (documented).

### Vladimir
E0/E1 modeled the Q/W/R self-heals (Transfusion 40, Hemoplague 350, Sanguine Pool 22.5 x4 in probes) and E2-3 priced E's charged ticks, so the CP-era heal family is closed. The one remaining CP-era review item is still open and undocumented in the module: R Hemoplague's 10% increased-damage-taken debuff is not expressed by the R packet (burst + heal only) — a damage-modification mechanic the audit flagged as a judgment call. P Crimson Pact stat conversion stays documented out.

### Zac
E1-b4 added the Cell Division blob heal (4-8.47% max health per ability hit; probe: 7 heals of ~203), E8d added the sourced revive (50% max health after the level-bracketed 8-4s window, 300s cd), and E2-3 priced R as initial + 3 reduced bounces (Total row) — closing the CP-era P-mis-model and R items; the old P packet no longer emits damage. Still open and undocumented from the CP-era gap: Q prices the per-hit 'Magic Damage' row (probe: 118.4, one hit of 60-180 + 30% AP) instead of 'Total Magic Damage' (2x, the two-hit Stretching Strikes) — a reviewed packet pricing an ability incompletely.

HOW TO CLOSE EACH (choose the sourced, deterministic path):
1. If the cached data/champions.json leveling rows or wiki prose carry a formula (flat + ratios, per-level arrays, %max/%missing health terms, per-tick totals), implement it in the module with the codebase's typed accessors/options conventions. Player-controlled state (stacks, procs, charges, uptime, empowered choices) becomes an OPTION with the sourced default and exact formula — the fight is deterministic given the option.
2. Heals/shields/revives go through src/calculator/healing.py (HEALING_RULE_CHAMPIONS) or the E8c self_shield_events / E8d ally-support interfaces — follow the existing patterns (grey health, _heal_from_damage, later_target_amount).
3. On-hit / empowered-auto / proc mechanics use the engine's on-hit, every-Nth-hit, empowers_next_auto, post_hit_proc patterns (Vayne W, Varus Blight, Akshan double_shot precedents).
4. Multi-part abilities (two-pass, bounces, lingering DoTs, shield+damage, buffs that feed other abilities) price EVERY sourced part with authored timing (time_offset / hit_interval / dot_duration), like the E2/E5 conventions.
5. A mechanic may remain non-priced ONLY if it is genuinely inexpressible in a deterministic single-target fight (e.g. an enemy-projectile reflection with no modeled enemy source, a death-only trigger) — then it must be a DOCUMENTED option or zero-damage receipt with a sourced reason, and the champion still gets verdict 'ok' ONLY if nothing damage-relevant is silently absent. If you cannot close an item deterministically, keep verdict 'review' and say exactly why in your reply (do not fake 'ok').
6. Update the champion's audit entry in a NEW file data/champion-audit/batch-p1-3.json: {"ChampionName": {"verdict": "ok", "gap_summary": "<what was closed + source formula + test evidence>", "module": "<name>.py", "slots": {...}}} — for EVERY one of your 10 champions.

TESTS: tests/test_p1_review_3.py — per champion, /api/calculate assertions (level 18, rank 5, R rank 3, no items, 0 resists) with expected values recomputed from the cached leveling rows + the fight's own stats; plus one probe per new option.

GATES (in worktree): pytest tests/test_p1_review_3.py; pytest -q (full); pylint src/ --fail-under=9; black --check src/ tests/; golden — re-capture scripts/golden_baseline.json ONLY if fight totals change, explaining every diff (these ARE behavior fixes; expect diffs for your champions).
COMMIT "feat(P1-3): zero-review closures for Briar, Kindred, Lux, Mel, Neeko, Riven, Skarner, Varus, Vladimir, Zac" and PUSH origin/codex/p1-review-3. Do NOT merge. Do NOT touch data/champion-audit/batch-e9-* (write batch-p1-3.json only).
Reply to parent: per champion — the closed mechanic + source formula + option added, test result, gates, golden diffs explained, commit SHA; and any champion you could NOT close (with the exact blocker).