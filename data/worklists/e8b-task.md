You are implementing GRIEVOUS WOUNDS application and shield-reduction (E8b) in a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-e8-2 (branch codex/e8-grievous). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

SCOPE (you OWN these files; no other agent touches them):
- src/calculator/champions/katarina.py, varus.py
- src/calculator/item_effects.py or src/calculator/items.py (Serpent's Fang venom — check where item effects live; typed accessors only, no literal fallbacks per AGENTS.md)
- src/calculator/healing_reduction.py (ONLY if a champion-wound hook is missing; otherwise use the existing interfaces)
- tests/test_e8_grievous.py (new)
- scripts/golden_baseline.json (re-capture ONLY if fight totals change, explain every diff)

CONTEXT: The engine already applies ITEM Grievous Wounds via healing_reduction_profiles(items) + _A_WOUND in participant_timeline.py's survival walk (GRIEVOUS_WOUNDS_FACTOR = 0.4 i.e. 60% reduction for 3s — verify the constant and its item sources: Oblivion Orb, Morellonomicon, Chemtech Putrifier, Mortal Reminder, Thornmail...). Your job:
1) VERIFY item GW works end-to-end: fight with a self-healing champion (e.g. Aatrox Q / Warwick) against an enemy holding Morellonomicon/Oblivion Orb — the self-heal must be reduced by 60%/40% for 3s after damage. Fix anything broken. Add tests.
2) CHAMPION-applied GW: Katarina R (Death Lotus — applies 40% GW for 3s on every hit; wiki) and Varus E (Hail of Arrows — applies 40% GW for 3s). If the champion-module interface can emit a wound event the engine's _A_WOUND consumes, emit it; if a small hook in healing_reduction.py / participant_timeline.py is needed, add it (you own those files for this purpose). Tests: enemy self-healer reduced by the sourced % while the champion's GW is active.
3) Serpent's Fang (item): the venom REDUCES SHIELDS the target gains by 50%/35% (melee/ranged) for 3s — apply at shield GRANT time: when the attacker holds Serpent's Fang and has damaged the target within 3s, shields the target gains are reduced by the sourced %. The engine's shield path (kind == "shield" events in participant_timeline.py) applies healing_received_multiplier to shield amounts — reuse that mechanism if suitable, else add the venom hook (you own participant_timeline.py for this). Tests: target gains a known shield while venom is active -> shield amount reduced by 50%/35%.
No invented numbers: Serpent's Fang value from data/items.json + item_effects typed accessors; GW % from the engine's existing constant (verify it matches the game: 40% reduction for 3s).

GATES (in worktree): pytest tests/test_e8_grievous.py; pytest -q (full); pylint src/ --fail-under=9; black --check src/ tests/; golden capture+compare with every diff explained.
COMMIT "feat(E8b): champion-applied Grievous Wounds (Katarina R, Varus E) + Serpent's Fang shield-reduction" and PUSH origin/codex/e8-grievous. Do NOT merge.
Reply to parent: item-GW verification result, the champion-GW hook, Serpent's Fang mechanism, tests, gates, golden diffs, commit SHA.