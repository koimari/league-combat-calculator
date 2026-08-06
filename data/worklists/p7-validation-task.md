You are building the VALIDATION LOOP backend (P7) + TRUST-LABEL data endpoints (P4) + the MONETIZATION DESIGN DOC (P8) for a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-p7 (branch codex/p7-validation). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

CONTEXT: Engine fully modeled (173/173 'ok', deterministic — P1 done). Database layer merged (src/db.py, SQLAlchemy; tables: builds, share_links, cached_results, validation_feedback (id, champion, loadout/expected/actual JSON, source 'manual|combat_log|practice_tool', matched, note, created_at), staleness_state, cache_counters). POST /api/feedback + GET /api/feedback exist (P6).

YOU OWN:
- src/app.py (backend routes only — static/js/app.js is owned by the P5 agent)
- src/db.py (only to extend the feedback model if needed)
- static/js/feedback.js (a small self-contained module for the feedback UI — do NOT touch app.js)
- templates/index.html (add the feedback widget hook + script tag — coordinate: keep it additive)
- docs/monetization-design.md (P8 design doc)
- tests/test_p7_validation.py

P7 — VALIDATION LOOP:
1. GAME-RECEIPT IMPORT: POST /api/receipts {champion, loadout (mirror of /api/calculate payload), observed: {"tdd": number, "sources": {"Q": number, ...}} or a raw combat-log paste, source} -> validates the receipt shape, computes the model's prediction for the same loadout via the engine, stores a ValidationFeedback row with matched = abs(observed - predicted) <= tolerance (relative 10% or absolute 20, whichever larger) and the delta. Returns {feedback_id, matched, predicted, observed, delta}.
2. FEEDBACK WIDGET: static/js/feedback.js renders a compact 'Did this match your game?' (Yes / No / Off by X%) widget in the results area + a paste-import textarea; posts to /api/receipts. The widget must not break when the results area is absent.
3. SURFACE SYSTEMATIC ERRORS: GET /api/validation?champion=&limit= -> {feedback, count, systematic: [{champion, bias: signed avg delta, n, flagged: bool}]} — bias beyond +-15% with n>=5 flags the champion as systematically off.
4. GET /api/validation/champions -> champions flagged or with feedback counts, for a future dashboard.

P4 — TRUST-LABEL DATA (backend side; the P5 agent renders the UI):
5. GET /api/certainty?champion= -> {"champion": "...", "slots": {"Q": {"certainty": "exact|estimate|boundary", "reason": "..."}}} — derive per ability: EXACT when every damaging/heal row is a sourced formula with no player-controlled default (no options); ESTIMATE when the module uses a defaulted option (stacks/procs/uptime) or a documented approximation (burn GCD spread, Black Cleaver average stacks, missing-health default %); BOUNDARY when a documented non-computed mechanic exists (death-only trigger, incoming-damage window, enemy-projectile reflection). Source: the champion module's ASSUMPTIONS/OPTIONS + the audit entries (data/champion-audit/batch-p1-*.json).
6. GET /api/not-modeled?champion= -> {"champion": "...", "items": ["..."]} — the documented non-computed mechanics for the champion (from ASSUMPTIONS lines that say 'documented', 'state', 'not modeled', 'boundary').

P8 — MONETIZATION/COMMUNITY DESIGN DOC (docs/monetization-design.md): premium tier proposal (advanced comparisons, unlimited builds/shares, validation dashboards, meta aggregation), community features (public shared-build gallery with meta stats, build ratings), Riot-compliance constraints for any aggregation, pricing sketch. DESIGN ONLY — no implementation.

GATES: pytest -q full; pylint src/ --fail-under=9; black --check src/ tests/; node --check static/js/feedback.js; git diff --check; golden compare identical (no engine change).
COMMIT "feat(P7/P4/P8): validation receipts + certainty/not-modeled endpoints + monetization design" and PUSH origin/codex/p7-validation. Do NOT merge.
Reply to parent: receipt-import flow + tolerance semantics, systematic-bias detection, certainty derivation rules per champion sample, the /api/certainty contract, monetization doc outline, tests, gates, commit SHA.