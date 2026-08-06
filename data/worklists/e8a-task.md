You are implementing the GREY-HEALTH primitive and its champions (E8a) in a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-e8-1 (branch codex/e8-grey-health). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

SCOPE (you OWN these files; no other agent touches them):
- src/calculator/participant_timeline.py (the shared ledger)
- src/calculator/healing.py (the heal helpers)
- src/calculator/champions/pyke.py, rengar.py, tahm_kench.py, mordekaiser.py, kled.py
- tests/test_e8_grey_health.py (new)
- scripts/golden_baseline.json (re-capture ONLY if fight totals change, explain every diff)

THE MECHANIC (from data/worklists/e8-interactions.json grey_health_design):
Pyke P (Gift of the Drowned One), Rengar W (Battle Roar), Tahm Kench E (Thick Skin), Mordekaiser W (Indestructible), Kled W/Skaarl store damage TAKEN (post-mitigation) as grey health, then pay it back as a heal when the champion's active consumes it. The 1v1 heal derivation only sees the attacker's OUTGOING events — the fix: author grey-health receipts in participant_timeline.py's INCOMING ledger. When the main is the defender and is a grey-health champion, accumulate the sourced % of post-mitigation incoming damage as grey health; pay it as a heal when the champion's active consumes it (Pyke P out-of-vision, Rengar W recast, Tahm K E, Mordekaiser W recast, Kled Skaarl remount + W). Use the same _heal_from_damage / later_target_amount plumbing as E1. The 16 E1 skips awaiting grey health (data/worklists/e8-interactions.json e1_skips_awaiting_grey_health) become implementable — implement the ones in YOUR champion list.

VALUES (source from data/champions.json leveling rows; pin prose as module constants with citations):
- Pyke P: damage taken stored as grey; when out of vision (document as boundary), heals for the stored amount; wiki ratio: heals for 100% of damage taken (capped ~9-105 by level + 6% bonus AD per 1 second out of vision... verify from the cache leveling rows; if prose-only, pin the sourced ratio).
- Rengar W: heals for 50% of damage taken in the last 1.5s (wiki "Heal for 50% of the damage taken in the last 1.5 seconds"); leveling rows have heal amounts — reconcile: the heal is (50% of recent damage) OR flat, whichever higher? Verify from cache + wiki prose; document.
- Tahm Kench E: grey-health conversion % by rank (e.g. 45/50/55/60/65% of damage taken becomes grey; 15/20/25/30/35% converted to a shield when out of combat... verify rank rows); the RECAST (E active) heals 100% of grey (or 10/15/20/25/30% per wiki — VERIFY from the cache).
- Mordekaiser W: stores 100% of damage dealt+30% of damage taken (verify) as grey; recast heals 40/42.5/45/47.5/50% of stored (verify).
- Kled W (Violent Tendencies) + Skaarl remount: Skaarl's health is grey-ish (damage taken by Skaarl); remount restores; document as the revive-boundary pattern (Aatrox ghost atom is NOT implemented).
No invented numbers — every value traces to data/champions.json or the cited wiki page with the ratio pinned as a module constant.

TESTS: tests/test_e8_grey_health.py — per champion: /api/calculate fight where the ENEMY attacks the grey champion for a known post-mitigation amount; assert the grey-health champion stores the sourced % and pays the sourced heal on consume; golden re-capture if totals changed.

GATES (in worktree): pytest tests/test_e8_grey_health.py; pytest -q (full, expect ~3482+); pylint src/ --fail-under=9; black --check src/ tests/; golden capture+compare with every diff explained.
COMMIT "feat(E8a): grey-health primitive for Pyke, Rengar, Tahm Kench, Mordekaiser, Kled" and PUSH origin/codex/e8-grey-health. Do NOT merge.
Reply to parent: per champion — source formula + stored/payback ratios, test results, gates, golden diffs explained, commit SHA.