You are fixing mis-modeled champion rows (E5) in a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-e5-3 (branch codex/e5-fix-3). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

CHAMPIONS + REQUIRED FIXES:
- MonkeyKing: Q armor-reduction debuff unmodeled (infra exists — KogMaw Q)

RULES:
- Every number must trace to data/champions.json leveling rows (or documented wiki prose pinned as module constants with the source cited). No invented values.
- Fix the champion module (src/calculator/champions/<name>.py), add tests (tests/test_e5_fix_3.py) asserting the corrected damage in /api/calculate fights (level 18, rank 5, R rank 3, no items), run gates (full pytest, pylint src/ --fail-under=9, black --check src/ tests/, golden — re-capture scripts/golden_baseline.json only if fight totals changed, explaining each diff), commit "feat(E5-3): fix mis-modeled rows for MonkeyKing" and push origin codex/e5-fix-3. Do NOT merge.
- Only touch src/calculator/champions/, tests/, scripts/golden_baseline.json.
- Reply to parent: per champion — what was wrong, the corrected source formula, test result, gates, golden diffs explained, commit SHA.