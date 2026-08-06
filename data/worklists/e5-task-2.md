You are fixing mis-modeled champion rows (E5) in a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-e5-2 (branch codex/e5-fix-2). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

CHAMPIONS + REQUIRED FIXES:
- Nautilus: P reads %maxHP row as flat 0.75-1.5, drops 14-128 per-level term
- Poppy: P drops flat 'Bonus Magic Damage' term (keeps only %maxHP ratio)
- Nilah: Q pinned to crit-max 191% AD as flat
- Pyke: R packet is 1.5x-threshold array pinned to first 3 ranks, drops 80% bAD + lethality
- Mel: W models reflected modifier 40-60% as flat; R stored-damage not modeled
- Zoe: W Spell Thief collapsed to one flat bolt (Heal/Barrier/Smite variants)
- Riven: P declared no_damage but wiki has formula (30-46.76% AD per stack)
- Zeri: E Lightning Rounds damage out_of_scope
- Quinn: P Harrier on-hit out_of_scope while equivalent passives modeled

RULES:
- Every number must trace to data/champions.json leveling rows (or documented wiki prose pinned as module constants with the source cited). No invented values.
- Fix the champion module (src/calculator/champions/<name>.py), add tests (tests/test_e5_fix_2.py) asserting the corrected damage in /api/calculate fights (level 18, rank 5, R rank 3, no items), run gates (full pytest, pylint src/ --fail-under=9, black --check src/ tests/, golden — re-capture scripts/golden_baseline.json only if fight totals changed, explaining each diff), commit "feat(E5-2): fix mis-modeled rows for Nautilus, Poppy, Nilah, Pyke, Mel, Zoe, Riven, Zeri, Quinn" and push origin codex/e5-fix-2. Do NOT merge.
- Only touch src/calculator/champions/, tests/, scripts/golden_baseline.json.
- Reply to parent: per champion — what was wrong, the corrected source formula, test result, gates, golden diffs explained, commit SHA.