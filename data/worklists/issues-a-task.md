You are resolving GitHub issues #45 and #43 on the Scryglass calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-issues-a (branch codex/issues-a-items). Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

YOU OWN: src/calculator/item_effects.py, src/calculator/stats.py, src/calculator/healing.py (item-sustain paths only), src/calculator/damage.py (item-family paths only), tests/test_issues_45_43.py (new), scripts/golden_baseline.json (re-capture + explain if item totals change).

#45 — grouped sustain stats and item healing:
1. Add typed lifesteal entries for Vampiric Scepter and Mercurial Scimitar (sourced from data/items.json + wiki; no literal fallbacks — missing keys must raise naming the item+key). Bloodthirster/BotRK/Ravenous Hydra/Doran's Blade already exist — verify and extend to a grouped receipt.
2. Verify Cull's 3 health on-hit is modeled (it has reap_minion_kills option — check the 3-health-on-hit term).
3. Grouped sustain aggregation: stats.py should aggregate lifesteal/omnivamp/heal-shield-power into the loadout stats + the participant timeline's sustain receipts (healing_received etc.). Tests assert a champion with BotRK+Bloodthirster heals the sourced % per auto.
4. Tests: /api/calculate fights asserting sourced sustain amounts.

#43 — on-hit, Spellblade, Energized, Hydra families:
Verify each sibling effect the issue calls out; implement it with typed accessors or record a DOCUMENTED boundary (sourced reason, never silent):
- Guinsoo's Rageblade Seething Strike stacking 0-32% AS (stack option with sourced per-stack row)
- Lich Bane empowered-attack bonus AS
- Essence Reaver Spellblade mana restoration
- Dusk and Dawn (secondary target documented)
- Hydra cleave secondary-target damage (single-target model boundary with sourced cone numbers documented)
- Energized (Statikk/RFC/Stormrazor/Voltaic) — verify the energized proc cadence/timing from E9-BIS
Tests per family: /api/calculate assertion + parse-level sourced-value pins.

GATES: pytest -q full; pylint src/ --fail-under=9; black --check src/ tests/; golden — re-capture ONLY if item totals change, explaining each diff; git diff --check.
COMMIT "fix(#45,#43): grouped sustain + item family siblings" and PUSH origin/codex/issues-a-items. Do NOT merge.
Reply to parent: per issue — what was wired (source row + accessor), what became a documented boundary (with the reason), tests, gates, golden diffs explained, commit SHA.