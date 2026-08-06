You are fixing mis-modeled champion rows (E5) in a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-e5-1 (branch codex/e5-fix-1). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

CHAMPIONS + REQUIRED FIXES:
- Tryndamere: Q emits 5-25 as MAGIC damage — Q is a heal (E1 done); remove the spurious damage row
- Zed: R Death Mark static ~100-120 from a % row — implement % of stored damage
- TwistedFate: W sums all 3 cards (3.0x AD + 2.2x AP) — model card selection (gold/red/blue)
- Kled: W rank read clamped to level (11/18) — read actual W rank for the 4th-attack bonus
- Sion: Q modeled via 'Maximum Base Damage Increase' % as flat — use Min/Max Physical Damage rows
- Veigar: R always at MAXIMUM execute values — use base + execute condition

RULES:
- Every number must trace to data/champions.json leveling rows (or documented wiki prose pinned as module constants with the source cited). No invented values.
- Fix the champion module (src/calculator/champions/<name>.py), add tests (tests/test_e5_fix_1.py) asserting the corrected damage in /api/calculate fights (level 18, rank 5, R rank 3, no items), run gates (full pytest, pylint src/ --fail-under=9, black --check src/ tests/, golden — re-capture scripts/golden_baseline.json only if fight totals changed, explaining each diff), commit "feat(E5-1): fix mis-modeled rows for Tryndamere, Zed, TwistedFate, Kled, Sion, Veigar" and push origin codex/e5-fix-1. Do NOT merge.
- Only touch src/calculator/champions/, tests/, scripts/golden_baseline.json.
- Reply to parent: per champion — what was wrong, the corrected source formula, test result, gates, golden diffs explained, commit SHA.