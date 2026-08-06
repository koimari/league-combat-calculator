You are implementing REVIVE events and ALLY-SUPPORT heals/shields (E8d) in a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-e8-4 (branch codex/e8-support). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

SCOPE (you OWN these files; no other agent touches them):
- src/calculator/champions/anivia.py, zac.py, zilean.py, taric.py, rakan.py, sona.py, nami.py, yuumi.py, milio.py, kayle.py, seraphine.py, janna.py, bard.py, soraka.py
- tests/test_e8_support.py (new)
- scripts/golden_baseline.json (re-capture ONLY if fight totals change, explain every diff)
DO NOT touch participant_timeline.py or healing.py (another agent owns them) — emit events ONLY through the existing interfaces. The engine has derive_ally_effects / support entries (support_effects.py, item_support_effects.py) and a revive state transition ("Revive is a state transition rather than healing: allowed to run after a lethal packet and restores a sourced resource amount"). If a needed engine hook is MISSING, document it precisely in your reply (file+function+why) instead of editing the shared files — I will apply it after the grey-health agent's merge.

REVIVES (source from cache leveling + prose):
- Anivia P Rebirth: post-lethal, revives with sourced % max HP (e.g. 30/35/40% by level — verify); emit the revive event the engine consumes; assert in a fight where Anivia takes lethal damage -> she revives with the sourced HP.
- Zac P Cell Division: revive with sourced % max HP from bloblets (verify %).
- Zilean R Chronoshift: revive with sourced flat + AP ratio HP (verify leveling).
- (Kled Skaarl remount is owned by the grey-health agent — skip.)
- Aatrox is explicitly NOT implemented (pre-rework ghost atom) — do not touch.

ALLY-SUPPORT heals/shields (champion emits a support event targeting allies; the ledger already tracks support_shield_received / support heals from items — reuse the same event shape):
- Sona W Aria of Perseverance (ally heal + shield)
- Nami W Ebb and Flow (ally heal)
- Yuumi E Zoomies (ally heal + shield — Yuumi's E1 self-heal already exists; add the ally target)
- Milio W Cozy Fire / R Breath of Life (ally heals)
- Taric Q Starlight's Touch (ally heal) + R Cosmic Radiance (invulnerability — document as state)
- Rakan Q Gleaming Quill (ally heal) + P Fancy Footwork (self shield)
- Kayle W Celestial Blessing (ally heal — self modeled in E1; add ally)
- Seraphine W Surround Sound (ally heal + shield)
- Janna R Monsoon (ally heal — huge over time; source the per-tick row)
- Bard W Caretaker's Shrine (ally heal — shrines; source the heal row)
- Soraka W Astral Infusion (ally heal — costs her own health; document the cost)
For each: emit the support heal/shield event with sourced amounts; assert in a /api/calculate fight WITH AN ALLY in the roster (enemies + allies lists are supported) that the ally's ledger receives the heal/shield. If the 1v1 API doesn't support allies, test via the roster path the existing tests use for ally support.
No invented numbers.

TESTS: tests/test_e8_support.py — per champion: sourced amount + fight assertion (revive post-lethal HP for the revive trio; ally ledger heal/shield for the support set).
GATES (in worktree): pytest tests/test_e8_support.py; pytest -q (full); pylint src/ --fail-under=9; black --check src/ tests/; golden capture+compare with every diff explained.
COMMIT "feat(E8d): revive events (Anivia, Zac, Zilean) + ally-support heals/shields (11 champions)" and PUSH origin/codex/e8-support. Do NOT merge.
Reply to parent: per champion — source formula + event authored, tests, gates, golden diffs, ANY missing engine hooks you identified, commit SHA.