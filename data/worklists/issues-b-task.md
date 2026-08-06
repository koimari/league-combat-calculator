You are resolving GitHub issue #46 on the Scryglass calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-issues-b (branch codex/issues-b-defenses). Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

YOU OWN: src/calculator/defensive_effects.py, src/calculator/participant_timeline.py (defensive paths), tests/test_issues_46.py (new), scripts/golden_baseline.json (re-capture + explain if needed). Read src/calculator/item_effects.py but DO NOT edit it (another agent owns it) — if a defensive item needs an item_effects change, note it in your reply for me to apply.

#46 — complete opening mitigation, spell shields, and Lifeline defenses. Acceptance pass over the FULL scope:
- Banshee's Veil / Edge of Night / Verdant Barrier (Annul spell shields) — verify the spell shield is ready at fight start (spell_shield_ready fields) and blocks one typed ability hit in the ledger; test with a fight where the spell shield absorbs a spell.
- Celestial Opposition (Blessing of the Mountain) — proc shield wired (E8c/E9-BIS certified? verify it certifies in /api/bis).
- Noxian Endurance / Armored Advance (Plating) — basic_damage_flat_reduction wired + tested.
- Bloodthirster Ichorshield starting state + overshield.
- Sterak's Gage / Maw (Lifeline) threshold shields + maw_lifeline_omnivamp_percent toggle.
- Every item above must (a) resolve in a /api/calculate fight with the sourced shield/reduction receipt, (b) certify in /api/bis (appear in certified candidates for a fitting champion, e.g. tank/AD/AP), or be a DOCUMENTED exclusion with a sourced reason.
- Fix any gap; add coverage tests per item.

GATES: pytest -q full; pylint src/ --fail-under=9; black --check src/ tests/; golden compare (explain diffs); git diff --check.
COMMIT "fix(#46): opening mitigation + spell shields + Lifeline acceptance" and PUSH origin/codex/issues-b-defenses. Do NOT merge.
Reply to parent: per item — wired state + test evidence + BIS certification result, any item_effects change I need to apply, commit SHA.