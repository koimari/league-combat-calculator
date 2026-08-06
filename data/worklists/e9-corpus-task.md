You are expanding the Practice-Tool verification corpus (E9) in a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-e9-corpus (branch codex/e9-corpus). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

SCOPE (you OWN these files; no other agent touches them):
- data/practice-corpus/scenarios.json (expand; keep schema_version 1, the four existing scenarios, and add new ones)
- docs/e9-progress.md (update the E-series status table to the merged reality)
- docs/receipts/ (regenerate with scripts/build_receipts.py AFTER the audit agents' branches are merged — do NOT run it before; the verdicts will be stale)
- scripts/ (only if a scenario-verification helper is needed)
- tests/test_e9_corpus.py (new — verify each scenario's expected values against /api/calculate)

THE CORPUS (from data/practice-corpus/scenarios.json): each scenario is a concrete input tuple (champion/level/items/enemies/allies/fight/ranks) with an expected receipt (tdd, heal amounts, event counts, BIS certified/withheld). Tiers: production / local / pending. The four existing scenarios are "local" with stale SHAs.

ADD at least one scenario PER E-SERIES WORKSTREAM, each with exact expected values computed from the CURRENT code (probe /api/calculate in the worktree, then pin the values):
- E1 self-heal: a champion with a healing.py rule (e.g. Aatrox Q heal, Vladimir W pre-mitigation 30%) — expected heal amount.
- E2 DoT ticks: a champion whose DoT was re-ticked (e.g. Malzahar E 220 total / 4 ticks, Morgana W) — expected per-tick and total.
- E3 stacks: a stack champion (e.g. Varus Blight detonation 3 stacks, Twitch Contaminate 6 stacks, Nasus Q with q_stacks=100) — expected detonation amount.
- E4 summons: a summon champion (e.g. Zyra plant attacks 4x75, Annie Tibbers 300 magic, Yorick Mist Walkers) — expected pet damage.
- E5 mis-modeled: a fixed row (e.g. Zed R stored damage 341, Veigar R min 325, Sion Q max 676.4) — expected amount.
- E8 interactions: grey health (Rengar W heals 50% of stored), a shield (Annie E absorbs X), a revive (Anivia revives with 100% max HP after lethal), Grievous Wounds (Morellonomicon reduces Aatrox heal by 40% for 3s), Serpent's Fang shield cut.
- Item receipts: 3-5 item scenarios (e.g. Serpent's Fang venom, Morellonomicon GW, Sterak's shield, Bloodthirster, Fimbulwinter).
Each scenario: id, tier "local", sha = the CURRENT git HEAD of the worktree, setup tuple, expected (exact numbers from the probe), practice_tool_steps (how to reproduce in the Practice Tool: load champ, buy item, dummy, rotate, read combat log).

VERIFY: tests/test_e9_corpus.py drives each scenario through /api/calculate and asserts the expected values (they must pass against the CURRENT code). Add the SHA check: each scenario's sha == current HEAD when written.

GATES: pytest tests/test_e9_corpus.py; pytest -q (full); pylint src/ --fail-under=9; black --check src/ tests/; node --check static/js/app.js; git diff --check.
COMMIT "feat(E9): practice-corpus scenarios for E1-E8 + local verification tests" and PUSH origin/codex/e9-corpus. Do NOT merge.
Reply to parent: scenario list (id -> expected receipt), test count, gates, commit SHA. Note: docs/receipts regeneration happens AFTER the audit branches merge — leave a clear marker in docs/e9-progress.md about the pending re-run.