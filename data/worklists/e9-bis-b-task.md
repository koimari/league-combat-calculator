You are eliminating the remaining BIS item withholdings (E9-BIS-B) in a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-e9-bis-b (branch codex/e9-bis-b). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

PROBLEM: /api/bis withholds these items as candidates across champions (the corpus scenario cp21-bis-utility-ahri pins two of them as 'withheld_before_timeline'):
1. Support starter upgrades withheld for ALL 173 champions: Bloodsong, Celestial Opposition, Dream Maker, Solstice Sleigh, Zaz'Zak's Realmspike (support/ward-starter items whose effects the item coverage marks blocked/withheld).
2. Bastionbreaker, Eclipse, Muramana — explicitly-audited timing exclusions (EXPLICIT_APPLICABILITY_EXCLUSION_SOURCES in src/calculator/timeline_coverage.py: muramana_ability, proc_Eclipse, shaped_charge_Bastionbreaker — coarse sources with no authored event timing).

THE GOAL: model each item's effect so the optimizer can CERTIFY candidates carrying it (or, for items whose game effect is genuinely unpriceable in the fight model, convert the withholding into a DOCUMENTED boundary: update the corpus scenario expectation + item coverage note so the withholding is an audited, sourced decision — never silent).

CONTEXT (read first):
- src/calculator/timeline_coverage.py — the exclusion mechanism (EXPLICIT_APPLICABILITY_EXCLUSION_SOURCES).
- src/calculator/item_coverage.py — how item effects get 'blocked'/'withheld' verdicts and what certification requires.
- src/calculator/item_effects.py — typed accessors; data/items.json for the cached effects (find the items by name).
- src/calculator/item_support_effects.py — support-item effects (Knights Vow etc.).
- tests/test_item_coverage.py or similar — existing item coverage tests.

FOR EACH ITEM: find its cached effect in data/items.json; model the damage/shield/heal in the item effects layer with AUTHORED EVENT TIMING (the item event lands at a sourced timestamp — cast time, proc trigger, or buff window), so timeline coverage goes exact and the candidate certifies. Where the game effect is a stat-only or utility-only item (e.g. a ward upgrade with no combat effect), certify it as a no-damage source with the sourced reason. Tests: /api/bis for 2-3 champions per item asserting the item now appears in certified candidates (or is a documented exclusion with the corpus scenario updated).

RULES: only touch src/calculator/ (item effects/coverage/support layers + timeline_coverage if needed), tests/test_e9_bis_b.py (new), data/practice-corpus/scenarios.json (ONLY if an expectation must change — add a comment marker), scripts/golden_baseline.json (re-capture + explain if item totals change).
GATES: pytest tests/test_e9_bis_b.py; pytest -q (full); pylint src/ --fail-under=9; black --check src/ tests/; golden compare (explain any diffs).
COMMIT "feat(E9-BIS-B): certify/audit remaining BIS item withholdings" and PUSH origin/codex/e9-bis-b. Do NOT merge.
Reply to parent: per item — the modeled effect + authored timing (or the documented exclusion + why), certified/withheld before/after for the test champions, gates, golden status, commit SHA.
CRITICAL EXECUTION RULE: You MUST produce a pushed branch. Do NOT stop at exploration. Work through the items one at a time, commit after each, and push origin/codex/e9-bis-b when done (or after the first commit if you risk stopping early). If you find the work is too large for one pass, SPAWN YOUR OWN CHILDREN (you are allowed RLM depth 2): give each child 2-3 items on a separate branch/worktree under /Users/river/Projects/lcc-e9-bis-b-<n>/, then merge their branches into yours and push. Never end a turn without either a pushed commit or an explicit blocker report.

SUGGESTED ORDER (each item: find cached effect -> model with authored timing -> verify /api/bis certifies for 2 champions -> commit):
1. Bloodsong (support starter upgrade — spellblade proc on support items)
2. Celestial Opposition (support starter upgrade — proc shield)
3. Dream Maker (support starter upgrade — proc damage/buffs)
4. Solstice Sleigh (support starter upgrade — proc heal)
5. Zaz'Zak's Realmspike (support starter upgrade — proc damage)
6. Eclipse (proc_Eclipse coarse source -> authored self-shield event timing)
7. Muramana (muramana_ability coarse source -> authored ability-hit timing)
8. Bastionbreaker (shaped_charge_Bastionbreaker coarse source -> authored charge timing)
If an item's combat effect is genuinely unpriceable in the fight model (pure utility/vision), certify it as a documented no-damage source and UPDATE the corpus scenario expectation with a marker comment.
