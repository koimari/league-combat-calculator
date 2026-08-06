You are establishing the MATHEMATICAL FOUNDATIONS of a League of Legends combat calculator (P2) in /Users/river/Projects/lcc-p2-math (branch codex/p2-math-foundations).

CONTEXT: The calculator (Scryglass) computes deterministic combat outcomes: per-ability damage, DoT ticks, stacks, summons, heals/shields/revives, item procs, and a BIS optimizer ranking ~96 candidate item builds against a coupled participant event timeline. All champion/item formulas trace to the League wiki cache (data/champions.json, data/items.json) + game files. The engine lives in src/calculator/ (damage.py, participant_timeline.py, healing.py, optimizer.py, resistance.py, stats.py).

YOUR TOOLS: the free research toolkit at ~/.local/mcp/helpers.py (arxiv_search, web_search) and ~/.local/mcp/mcp_client.py — NO paid APIs. Use arxiv to find the mathematical literature grounding each modeling choice.

DELIVERABLES (all in the worktree):
1. docs/math-foundations.md — the mathematical basis for EVERY modeling family, with arxiv citations:
   a. Expected-damage & combat simulation: renewal/reward theory for cast+auto timing schedules, linearity of expectation for multi-hit abilities/procs/DoT ticks, order statistics / quantiles for execute thresholds (Veigar R, Pyke R) and missing-health terms, geometric sums for proc chains.
   b. Resistance & penetration derivation: the 100/(100+R) damage-reduction identity, percent-then-flat penetration order, when the composition is exact vs an approximation, negative-resistance behavior.
   c. BIS optimization: formulate the candidate ranking exactly (combinatorial optimization over loadout slots with coupled timeline evaluation), the search space size, and the approximation/duality used to keep ~96 candidates tractable; any published theory for such item-recommendation problems.
   d. Variance/confidence: what the deterministic single number does and does not claim; how a validation corpus turns point estimates into calibrated statements.
   e. A FORMULA-AUDIT TABLE: for each engine formula family (auto DPS, ability rotation, DoT totals, on-hit stacking, grey health, GW reduction, shield absorption, revive, BIS score), the theorem/identity it instantiates and any edge case the math says is wrong.
2. If the audit finds a formula that is mathematically wrong or an approximation presented as exact, FIX it in src/calculator/ (you may edit engine files) with a test, and cite the theorem in the code comment.
3. tests/test_p2_math_foundations.py — a small suite pinning the identities (e.g. 100/(100+R) round-trips, linearity-of-expectation checks on a multi-part ability, execute-quantile boundary).

GATES: pytest -q full; pylint src/ --fail-under=9; black --check src/ tests/; golden compare (explain diffs if any).
COMMIT "feat(P2): mathematical foundations for combat simulation + formula audit" and PUSH origin/codex/p2-math-foundations. Do NOT merge.
Reply to parent: the arxiv sources cited, the formula-audit findings (what was right, what was fixed), test/gate results, commit SHA.