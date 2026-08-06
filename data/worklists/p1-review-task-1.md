You are ELIMINATING the remaining 'review' audit status for your champions (P1: zero-review push) in a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-p1-1 (branch codex/p1-review-1). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

YOUR CHAMPIONS (10):
Akshan, KSante, Locke, Malphite, Nasus, RekSai, Seraphine, Sylas, Vex, Yasuo

THE MANDATE (user): "we should have nothing in review. we should make it ready since we have atomized everything, it should be computable and deterministic."

FOR EACH CHAMPION — the review item and the exact mechanic to make deterministic (from data/champion-audit/batch-e9-*.json gap_summaries, verbatim below):
### Akshan
E3 closed the main stack mechanic: Dirty Fighting 3-stack detonation damage (passive_procs) and the double-shot are modeled from description-text extraction. The 3rd-stack proc SHIELD (40-280 + 35% bAD) remains unmodeled — it rides the exact proc the module prices but is not in the E8c shield set, and the module ASSUMPTIONS carry no boundary note for it (only the CP-era audit documents it as a codebase-wide defensive-shield convention). W stealth/revive and R channel utility documented. Verdict: review (judgment call on the proc shield).

### KSante
E1-b6 evaluated but deliberately skipped the All Out conversion self-heal (test file documents: P/Q/W/E/R carry damage/shields/buffs only in the data, no heal term; the e8 grey-health design lists K'Sante R as a skip awaiting grey-health), and the module documents the omnivamp/resist conversion as explicit state — so the CP-era gap is now a documented boundary. E shield is emitted by the support scanner (Footwork 240 in a probe). P marks, Q, W charge + All Out true branch and R are modeled.

### Locke
The reviewed batch models P on-hit, Q with soul_nails stack bonus (q_casts/soul_nails options), E dash, and R totem damage (execute threshold documented as explicit target state). The W recast heal remains unmodeled but is now DOCUMENTED as a boundary: E1-b6 pins the absence with a sourced reason (the grey-health heal needs post-mitigation damage TAKEN from enemy champions, which the 1v1 pair ledger does not author; the W row states 'grey health storage ... and recast healing are self-state') — note the E8a grey-health primitive covers Pyke/Rengar/TahmKench/Mordekaiser but not Locke, so extending it here is a human-scope decision. Verdict stays review: core damage modeled, W heal a documented boundary.

### Malphite
E8c closed the main review item: P Granite Shield is modeled as a pre-fight 10%-max-HP barrier riding the first Q cast (verified 243.3 in breakdown detail). Q/E/R damage and the W on-hit bonus are modeled. The W empowered-attack cone splash and the P-tripled bonus armor remain unmodeled with no in-module note (single-target splash is defensible but undocumented; armor is defensive). Verdict: review (W splash/armor boundary).

### Nasus
E3/E2 closed the main gaps: Q stack scaling (q_stacks option; 200 stacks -> 857.5 vs 757.5 at 0), E Spirit Fire initial + 10 ticks, and R Fury of the Sands 30 ticks are all modeled. P Soul Eater lifesteal (12-24% based on level) remains unmodeled (Nasus absent from HEALING_RULE_CHAMPIONS; P declared zero-damage row with no heal note). Verdict: review (P lifesteal).

### RekSai
No E-series workstream implemented Rek'Sai mechanics (E4 lists her tunnel summon but the summon batches excluded her; the tunnel is zero-damage utility anyway). Q variants (q_variant option), W Unburrow, E Furious Bite, and R Void Rush damage packets remain correct. The max-Fury E true-damage variant (84-204 + 72% bAD) remains unmodeled with no fury-state option or boundary note, and P Fury of the Xeric'Kai regen / P max-HP damage and burrow CC are documented out_of_scope — the fury-E variant keeps this at review (documented packet scope, undecided fury state). Verdict unchanged.

### Seraphine
E8d closed the W Surround Sound item: the shield (Shield Strength 60-140 + 20% AP) is now emitted as a self-and-allies support event and the conditional missing-health pulse heal is documented as not emitted (dynamic state the scanner cannot carry). The CP-era review's Q item persists and is undocumented: High Note prices only the flat 60-160 + 40% AP row while the 'Maximum Enhanced Damage' (105-280 + 70% AP, +0-75% by missing health) is dropped. E/R damage modeled; P note echo stays documented out.

### Sylas
The primary CP-era gap (W Kingslayer self-heal) is closed by E1-b2: Sylas is in HEALING_RULE_CHAMPIONS with the missing-health-scaled heal (test_sylas_kingslayer_heals_scaled_by_missing), and Q/W/E damage packets remain correct. The secondary CP-era item — the E2 shield (SylasEShield atom) — remains unmodeled with no module boundary note (E8c's shield set did not include Sylas), and P Petricite Burst + R Hijack stay documented out_of_scope/no_damage. The CP-era 'clear gap' was heal-driven and is fixed, but the unmodeled E2 shield (defensive) keeps this at review.

### Vex
E8c closed the shield gap: W Personal Space now deals damage AND grants the sourced self-shield (verified 150 for 2.5s in breakdown detail) via the shared ledger, with the support scanner told to defer. Q/W/E/R damage modeled. P Doom 'n Gloom's empowered-auto bonus magic damage (40-162.94 + 25% AP) plus the fear remain out_of_scope with no in-module boundary note (only the CP-era review mentions it). Verdict: review (P empowered auto).

### Yasuo
E3-2 implemented the Q3 Gathering Storm (q_gathering_storm option) and E Ride the Wind per-stack damage (e_stacks option, verified in a probe), closing the CP-era gap's Q3 item; W/R keep packet pricing and P Flow shield is a documented state row. The CP-era gap's other main item persists as a documented boundary rather than an implementation: P's crit conversion (total crit chance doubled) and reduced crit damage are called out in the P row reason as 'passive stats' but no champion-specific crit doubling exists anywhere in the calculator, so Q/auto crit math is still wrong with items.

HOW TO CLOSE EACH (choose the sourced, deterministic path):
1. If the cached data/champions.json leveling rows or wiki prose carry a formula (flat + ratios, per-level arrays, %max/%missing health terms, per-tick totals), implement it in the module with the codebase's typed accessors/options conventions. Player-controlled state (stacks, procs, charges, uptime, empowered choices) becomes an OPTION with the sourced default and exact formula — the fight is deterministic given the option.
2. Heals/shields/revives go through src/calculator/healing.py (HEALING_RULE_CHAMPIONS) or the E8c self_shield_events / E8d ally-support interfaces — follow the existing patterns (grey health, _heal_from_damage, later_target_amount).
3. On-hit / empowered-auto / proc mechanics use the engine's on-hit, every-Nth-hit, empowers_next_auto, post_hit_proc patterns (Vayne W, Varus Blight, Akshan double_shot precedents).
4. Multi-part abilities (two-pass, bounces, lingering DoTs, shield+damage, buffs that feed other abilities) price EVERY sourced part with authored timing (time_offset / hit_interval / dot_duration), like the E2/E5 conventions.
5. A mechanic may remain non-priced ONLY if it is genuinely inexpressible in a deterministic single-target fight (e.g. an enemy-projectile reflection with no modeled enemy source, a death-only trigger) — then it must be a DOCUMENTED option or zero-damage receipt with a sourced reason, and the champion still gets verdict 'ok' ONLY if nothing damage-relevant is silently absent. If you cannot close an item deterministically, keep verdict 'review' and say exactly why in your reply (do not fake 'ok').
6. Update the champion's audit entry in a NEW file data/champion-audit/batch-p1-1.json: {"ChampionName": {"verdict": "ok", "gap_summary": "<what was closed + source formula + test evidence>", "module": "<name>.py", "slots": {...}}} — for EVERY one of your 10 champions.

TESTS: tests/test_p1_review_1.py — per champion, /api/calculate assertions (level 18, rank 5, R rank 3, no items, 0 resists) with expected values recomputed from the cached leveling rows + the fight's own stats; plus one probe per new option.

GATES (in worktree): pytest tests/test_p1_review_1.py; pytest -q (full); pylint src/ --fail-under=9; black --check src/ tests/; golden — re-capture scripts/golden_baseline.json ONLY if fight totals change, explaining every diff (these ARE behavior fixes; expect diffs for your champions).
COMMIT "feat(P1-1): zero-review closures for Akshan, KSante, Locke, Malphite, Nasus, RekSai, Seraphine, Sylas, Vex, Yasuo" and PUSH origin/codex/p1-review-1. Do NOT merge. Do NOT touch data/champion-audit/batch-e9-* (write batch-p1-1.json only).
Reply to parent: per champion — the closed mechanic + source formula + option added, test result, gates, golden diffs explained, commit SHA; and any champion you could NOT close (with the exact blocker).