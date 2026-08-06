You are building the CASUAL UX layer (P5) + TRUST LABELS UI (P4) for a League of Legends combat calculator — for the general public.

YOUR WORKTREE: /Users/river/Projects/lcc-p5 (branch codex/p5-ux). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

CONTEXT: The engine is fully modeled (173/173 champions deterministic 'ok', zero review — P1 done). A database layer (P6, merged) provides POST /api/builds, GET /api/builds/<id>, POST /api/share {build_id, slug?} -> {token, url}, GET /api/share/<token> (public read-only, increments views). The backend has /api/calculate, /api/bis, /api/optimize. A staleness badge module static/js/staleness.js exists (P3 merged).

YOU OWN (no other agent touches these):
- static/js/app.js (the main UI)
- templates/index.html
- static/css/ (styles)
- tests/test_p5_ux.py (new; frontend contract tests via the running server or jsdom-free DOM assertions where feasible — at minimum assert the API contracts the UI consumes)

P5 — CASUAL UX (the "general public" flow):
1. QUICK MODE: a prominent 'Quick' tab/button that collapses the analyst UI into one guided flow: pick champion (search) -> pick role -> [optional: pick enemy] -> press 'Best next item'. It calls /api/optimize (or /api/bis) and renders TOP-3 recommendations, each with the item name, its TDD/EHP delta vs the current build, and a ONE-LINE 'why' (e.g. 'biggest single-slot damage gain', 'fixes your armor problem', 'cheapest slot improvement'). Must complete in <10s for a casual user (show a spinner; the API is the same as today).
2. PRESET SCENARIOS: 3-5 one-click presets ('Full rotation vs tank', '10s sustained vs squishy', 'Burst vs 1v1', 'Team fight 4v4') that set the fight window/roster for the user.
3. BUILD SHARING: 'Share this build' button in quick mode + the analyst view: POST /api/builds with the current scenario (mirror /api/calculate payload; boots/fight settings ride fight_params), then POST /api/share to mint a token, then a copyable URL /api/share/<token> (or a route /s/<token> that renders the shared build — implement /s/<token> as a template route in app.py ONLY IF needed; otherwise the share token API is enough). On load with ?share=<token>, render the shared build read-only.
4. MOBILE-USABLE: the quick mode must work on a phone viewport (portrait, touch-friendly): big target buttons, no hover-dependent UI, the top-3 cards stack vertically.
5. Trust labels UI (P4): the breakdown/ability rows render a certainty chip next to each damage/heal number: EXACT (fully sourced formula, no options), ESTIMATE (uses a defaulted player-controlled option), BOUNDARY (documented non-computed mechanic). The chip reads a new backend field 'certainty' on each ability row (the P7 backend agent adds /api/certainty + /api/not-modeled; CONSUME those endpoints; the response shapes are: /api/certainty -> {"champion": "...", "slots": {"Q": {"certainty": "exact|estimate|boundary", "reason": "..."}}} and /api/not-modeled -> {"champion": "...", "items": ["..."]}). Render the per-champion 'What is not modeled' list in an info panel. If the endpoints are not ready when you test, mock the contract and note it.

GATES: node --check static/js/app.js; pytest -q full; pylint src/ --fail-under=9; black --check src/ tests/; git diff --check; golden compare identical (UI-only; if app.py gained a /s/ route, that is fine but no engine change).
COMMIT "feat(P5): casual quick mode + presets + build sharing + trust-label chips" and PUSH origin/codex/p5-ux. Do NOT merge.
Reply to parent: quick-mode flow, preset list, share flow + URL, mobile notes, trust-chip rendering + the /api/certainty contract you consumed, tests, gates, commit SHA.