You are implementing CHAMPION SHIELD events (E8c) in a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-e8-3 (branch codex/e8-shields). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

SCOPE (you OWN these files; no other agent touches them):
- src/calculator/champions/annie.py, azir.py, ambessa.py, blitzcrank.py, braum.py, camille.py, malphite.py, senna.py, thresh.py, volibear.py, vex.py, leona.py, olaf.py, nilah.py
- tests/test_e8_shields.py (new)
- scripts/golden_baseline.json (re-capture ONLY if fight totals change, explain every diff)
DO NOT touch participant_timeline.py or healing.py (another agent owns them) — emit shields ONLY through the existing event interface.

THE MECHANIC: the shared ledger (participant_timeline.py) already consumes shield events: a champion module emits {"kind": "shield", "amount": <sourced>, "duration": <seconds>, "source": "<Ability name>"} and the survival walk grants a timed shield that absorbs damage (physical/magic/general triples) and expires after duration. Champion shields to model (all values from data/champions.json leveling rows; prose pinned as module constants with citations):
- Annie E Molten Shield (flat + AP ratio)
- Azir E Shifting Sands (flat + AP ratio)
- Ambessa W (shield on cast)
- Blitzcrank P Mana Barrier (auto-trigger passive — 30% max mana as shield, 90s CD; model as a pre-fight granted shield or document the trigger boundary with the sourced amount)
- Braum E Unbreakable (projectile-blocking — document as CC/mitigation state with sourced duration; if it reduces damage, price the reduction)
- Camille P Adaptive Defenses (auto-trigger: 20% max HP as shield vs the damage type of the last hit; document boundary, source the %)
- Malphite P Granite Shield (10% max HP, regenerates — source the 10%)
- Senna R Dawning Shadow (ALLY shield — emits a support shield via the existing ally-support event interface if one exists; else document the ally-only boundary and keep the self effect only if applicable)
- Thresh W Dark Passage (ALLY shield — same ally-support note as Senna)
- Volibear E (self shield: 14% max HP + 75% AP — source from cache)
- Vex W Personal Space (flat + AP ratio)
- Leona W Eclipse (flat + bonus-resist shield)
- Olaf W Tough It Out (flat + missing-HP shield)
- Nilah P heal-to-shield conversion (document: she converts excess healing to a shield — price as the sourced conversion % of self-heals)
For each: emit the shield event at the right timestamp in the fight (cast time for actives; pre-fight for passives with documented trigger boundaries), assert in /api/calculate fights that the shield absorbs the sourced amount (target takes reduced post-mitigation damage while shielded).
No invented numbers.

TESTS: tests/test_e8_shields.py — per champion: parse-level sourced amount + /api/calculate fight asserting the shield row exists and absorbs the sourced amount against a known incoming hit.
GATES (in worktree): pytest tests/test_e8_shields.py; pytest -q (full, expect ~3482+); pylint src/ --fail-under=9; black --check src/ tests/; golden capture+compare with every diff explained.
COMMIT "feat(E8c): champion shield events (14 champions)" and PUSH origin/codex/e8-shields. Do NOT merge.
Reply to parent: per champion — shield source formula + how the event is authored, tests, gates, golden diffs, commit SHA.