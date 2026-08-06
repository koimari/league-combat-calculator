You are building the PATCH-DAY TRUST pipeline (P3) for a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-p3 (branch codex/p3-staleness). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python. The system python3 at /usr/bin/python3 (or the venv) can call the cdtb CLI at /Users/river/.local/mcp/wad-env/bin/cdtb (CommunityDragonToolbox; also a python module in /Users/river/.local/mcp/wad-env/lib/python3.12/site-packages/cdtb).

PROBLEM: patches land every 2 weeks. The calculator reads a wiki cache (data/champions.json, data/items.json with revision receipts). When a patch changes a kit, the cached values go stale silently until a human re-validates. The general public needs the stale state detected on DAY ZERO.

DELIVERABLES:
1. scripts/patch_regression.py — compares the CACHED wiki values against the GAME FILES ground truth for the current patch:
   - Use cdtb (game=16.15 or the live version) to download/extract champion CharacterRecord stats (baseHealth/healthPerLevel/baseDamage/damagePerLevel/baseArmor/armorPerLevel/baseMR/mrPerLevel/baseAS/ASPerLevel/baseHP5/baseMP5 etc.) from each champion's WAD (e.g. data/final/champions/<name>.en_us.wad.client → bin dump), plus item stats from the items bin.
   - Compare against data/champions.json stats + data/items.json stats (the wiki cache). The Gnar precedent in src/calculator/champions/gnar.py shows how game-file values were verified manually (gnarbig.bin.json CharacterRecords minus gnar.bin.json's); automate that comparison.
   - Ability-leveling comparison is BEST-EFFORT: where the bin structure maps to the wiki's leveling rows by ability name/attribute, compare; where it cannot map, record "unchecked" — never claim checked.
   - Output data/staleness.json: {"patch": "16.15", "checked_at": ..., "champions": {"Ahri": {"stale": bool, "stat_drift": {"health": {"cached": 594, "game": 600}}, "ability_rows_checked": n, "ability_rows_stale": n, "note": "..."}}, "items": {...}}. Tolerances: stat drift within 0.5% or ±2 flat is a rounding difference (not stale); anything beyond is stale.
   - Exit code 0 when nothing stale, 1 when stale items exist (patch-day gate).
2. A STALE badge in the UI: when the selected champion or any selected item is in staleness.json as stale, render a visible "STALE · PATCH 16.15" badge. Implement the badge as static/js/staleness.js (a small self-contained module that reads /api/staleness and patches the DOM) + include it in templates/index.html + CSS in static/css (add a class). Do NOT modify static/js/app.js (another agent owns it).
3. A /api/staleness endpoint in src/app.py serving data/staleness.json (and a regenerate trigger guarded by the existing admin/update-data auth pattern).
4. tests/test_p3_staleness.py — unit tests for the comparison tolerances + a fixture-driven stale detection.

GATES: pytest -q full; pylint src/ --fail-under=9; black --check src/ tests/; node --check static/js/staleness.js; git diff --check; golden compare (should be identical — no engine change).
COMMIT "feat(P3): patch-regression vs game files + STALE badge" and PUSH origin/codex/p3-staleness. Do NOT merge.
Reply to parent: the extraction method (which WADs/bins, how stats map), staleness.json shape + sample rows, badge implementation, endpoint, tests, gates, commit SHA.