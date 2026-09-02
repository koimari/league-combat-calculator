You are extending the OPTIMAL EVENT-ORDER ENGINE (F3) to ALL 173 champions, making the derivation fully algorithmic (the product owner's directive: derive on the fly from the atomized data, not a hand-maintained combo database).

YOUR WORKTREE: /Users/river/Projects/lcc-f3 (branch codex/f3-rotation-all). Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

CONTEXT: src/calculator/rotation_resolver.py (from F2) currently has a 4-signal scoring model (setup/consume auto-detect, per-rank DPS, cooldown gating, buffs-first) but only ~10 hand-curated ComboRule entries; every other champion falls back to certified/DEFAULT order with a generic rationale. The user wants: "trust 100% that results are correct only via atomized and math-backed analysis understanding what exactly each ability does. having that on the go seems faster than having a database of every single possible combo for every champion."

YOU OWN: src/calculator/rotation_resolver.py, src/calculator/damage.py (only if the scheduler hook needs it), tests/test_f3_rotation_all.py (new), docs/rotation-design.md (update), scripts/golden_baseline.json (re-capture + explain EVERY diff — derived orders may change sustained-fight totals for many champions).

DELIVERABLES:
1. FULLY ALGORITHMIC DERIVATION for all 173 champions: for a champion with NO combo-table entry, derive the order on the fly from the atomized data:
   a. DETECT setup/consume edges automatically from the ability rows + module metadata: an ability whose row names indicate application (poison/blemish/stack/mark/amp/slow/root/stun/on-hit) must precede abilities that consume (enhanced/consume/detonate/bonus-vs/X-stack/%missing); read the actual attributes from data/champions.json (e.g. 'Bonus Damage', 'Enhanced', 'Total Enhanced', 'per stack', 'poisoned', '% of target's', post_hit_proc, on_hit, dot_duration, stat_buff, AMP slots, cc_kind on parts).
   b. RANK per-rank DPS at the fight's stats for the remaining abilities (total_raw / effective cooldown × AoE weight) — high-DPS spam tools right after their setup.
   c. EMIT a rationale string citing the specific atoms that drove the order (e.g. "E's Enhanced row (…+55% AP vs poisoned) requires Q's 3s poison — Q first").
   d. FALLBACK: a champion with NO detectable edge and flat abilities keeps the certified/DEFAULT order with a rationale that says exactly that (data-driven, honest).
2. COMBO-INVARIANT TESTS: a regression suite that asserts, for EVERY champion: (a) the derived order never violates a detected setup/consume edge (E-before-poison, detonate-before-stack-application, amp-after-the-burst), (b) the rationale cites real atoms, (c) the order is stable across levels/items for the same champion (deterministic).
3. KEEP the 10 ComboRule entries as documented OVERRIDES (they are the verified seeds) but the table must not be the primary path for the other 163.
4. Verification gap report: for each champion whose derivation is ambiguous (edges detected but conflicting, or no data signal where a combo is known), list it in docs/rotation-verification-gaps.md for the F4 verification swarm.

GATES: pytest -q full; pylint src/ --fail-under=9; black --check src/ tests/; node --check static/js/app.js (unchanged); git diff --check; golden — re-capture + explain every diff (this is EXPECTED to change sustained totals for many champions).
COMMIT "feat(F3): algorithmic optimal-order derivation for all 173 champions + combo invariants" and PUSH origin/codex/f3-rotation-all. Do NOT merge.
Reply to parent: how many champions got an algorithmic (non-table, non-default) order, the detected-edge taxonomy, invariant-test design, golden diff summary, verification-gap count, tests, gates, commit SHA.