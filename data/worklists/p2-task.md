You are doing the CLOSED-BETA POLISH (P2) for the Scryglass calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-p2 (branch codex/p2-polish). Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

YOU OWN: static/js/app.js (polish paths only), templates/index.html (additive), static/css/style.css, tests/test_p2_polish.py (new).

DELIVERABLES:
1. #78 FOLLOW-UP: make the frontend CONSUME contract.controls for runtime-disable. The backend capabilities.py now declares a `controls` section (view_switch, game_state, objective, best_in_slot, optimize, quick_mode, share, picker, roster_membership) with availability metadata. Implement: on app load, fetch /api/config, and gate the corresponding UI controls — e.g. if controls.best_in_slot is unavailable, disable the BIS triggers with the backend reason; if quick_mode is unavailable, hide the Quick tab with a tooltip; if share is unavailable, hide the share buttons. Fall back to current behavior if /api/config lacks the controls section (defensive).
2. SHARE-PAGE POLISH: the ?share= read-only view — better presentation (champion card, certainty chips, rotation rationale from the new rotation receipt, event-order rail), a proper page title (document.title = "Scryglass · <champion> build"), and a "Open in editor" that works from any state.
3. MOBILE POLISH: verify + fix the analyst view on 390px (section grouping, no horizontal overflow — the F0 review already stacked quick cards; do the same for the analyst breakdown tables: allow horizontal scroll within the table card rather than page overflow).
4. ANALYTICS WITH CONSENT: a consent banner (localStorage `scryglass_analytics_consent`), and when consented, a privacy-respecting ping endpoint POST /api/analytics/ping {event, took_ms} — reuse the P1b metrics_events table (or a new analytics_events table in src/db.py; report if backend work is needed). No third-party scripts.

GATES: pytest -q full; pylint src/ --fail-under=9; black --check src/ tests/; node --check static/js/app.js; git diff --check; golden identical (UI-only).
COMMIT "feat(P2): contract.controls runtime gating + share-page polish + mobile + consent analytics" and PUSH origin/codex/p2-polish. Do NOT merge.
Reply to parent: per deliverable — what changed, browser evidence (share page + mobile), tests, gates, commit SHA.