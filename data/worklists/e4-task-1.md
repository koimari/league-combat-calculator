You are implementing summoned-unit damage (E4) in a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-e4-1 (branch codex/e4-summon-1). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

CHAMPIONS + MECHANICS:
- Annie: Tibbers: summon burst already modeled; ensure aura ticks + Tibbers attacks in window
- Heimerdinger: turrets: Q turret attacks (sourced damage), R upgrade
- Malzahar: voidlings: W summon damage (voidling attacks, 2-4 active)
- Azir: Sand Soldiers: W soldier attacks + Q command dash damage
- Illaoi: tentacles: P spawn + commanded slam damage (9-180 + 110% AD + 40% AP)

DESIGN PRINCIPLES:
- Pet damage sources: (1) the champion ability descriptions in data/champions.json (formulas like Illaoi tentacle "9:180 (based on level) (+110% AD) (+40% AP) physical"), (2) existing module pet constants (e.g. Annie Tibbers burst+aura already in the module), (3) the wiki 'Champion summoned units' page, (4) the fight window (one_rotation / duration).
- Where the fight model cannot price a pet's autonomous behavior (pet AS/HP not in the cache, leash ranges, AI), model the SOUNDED fixed contributions: summon burst, aura ticks, commanded attacks with known counts (e.g. a pet that attacks once per rotation, or N attacks over the fight duration at the sourced attack pattern). Expose an option for the number of pet attacks/uptime where the player would control it. Document every boundary.
- Follow the codebase conventions: module structure (src/calculator/champions/<name>.py), slot parsing (packet/wiki_attribute/options), typed accessors, tests.

For each champion: implement the pet/summon damage in the champion module, add tests (tests/test_e4_summon_1.py) asserting the sourced pet damage in a /api/calculate fight (level 18, rank 5 / R rank 3, no items), run gates (pytest full, pylint, black, golden — re-capture golden if pet damage now modeled, explaining each diff), commit "feat(E4-1): summon damage for Annie, Heimerdinger, Malzahar, Azir, Illaoi" and push origin codex/e4-summon-1. Do NOT merge.

Rules: only touch src/calculator/champions/, tests/, scripts/golden_baseline.json (if needed). Reply to parent with: per champion — the summon modeled (source formula, attack count, damage), test result, gate results, golden diffs explained, commit SHA.