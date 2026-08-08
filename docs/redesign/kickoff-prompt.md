# Kickoff prompt — Scryglass UI redesign

Paste this (or just "Read docs/redesign/kickoff-prompt.md and begin") into a fresh
session **on the `ui-redesign` branch**.

---

We are rebuilding this app's frontend to an approved design. All planning is done;
this session is implementation.

## Read first, in this order

1. `docs/redesign/design-language.md` — the visual system (layout concept, palette, type, shape).
2. `docs/redesign/target-2a.html` and `target-2b.html` — the approved mocks, standalone;
   open them in a browser at ≥1500px. 2a is the resting state (rail collapsed, duel on
   the full canvas); 2b is the same screen with a setup step expanded in place.
   These are the pixel targets. Match the visual output; don't copy their inline-style markup.
3. `docs/redesign/gap-ledger.md` — every current feature mapped to its home in the new
   design, plus four locked decisions (rebuild approach, solo-mode layout, single theme,
   desktop-first). The mock shows the happy path; the ledger is the real scope.
   **Nothing on that ledger may be silently dropped.**
4. `architecture.md` §Public boundary and `PRODUCT.md` — the contracts the frontend lives under.

## Ground rules

- **Backend untouched.** `app.py` routes, request/response shapes, and all APIs stay
  exactly as they are. This is a frontend-only branch.
- **Receipts-only renderer.** `static/js/app.js` contains no champion or item formulas,
  no item-id literals, no local damage/stat engine. That contract survives the rewrite.
- **Keep the state model and API layer of `app.js`; rewrite the render layer.** New
  `templates/index.html` and `static/css/style.css` are written fresh to the new IA.
  Vanilla JS — no framework, no build step, no new dependencies.
- **Accessibility floor**: keyboard navigation, visible focus, readable contrast on both
  the dark rail and cream canvas, aria-pressed/labelled controls and live regions
  preserved, color never the sole carrier of win/lose/team/certainty state.
- **Honest numbers**: certainty chips, not-modeled disclosures, certified-subset and
  partial-exhaustive notes all survive restyling. Never render an insight sentence the
  backend didn't provide.

## Suggested phasing (each phase ends working, verified in the browser)

1. **Shell + rail (collapsed)** — new index.html/style.css: rail with summarized steps
   and Constraints block, canvas placeholder. Wire existing state → rail summaries.
2. **Duel canvas** — verdict strip, mirrored builds, delta spine, fight timeline from
   existing `/api/calculate` receipts.
3. **Expanding steps** — Champion, Roster, Builds editors in place (2b behavior),
   dimmed live canvas behind, including champion options, roster item states, keystones,
   compare toggle.
4. **Solo layout** — comparison-off single-build view (locked decision 2).
5. **Analysis surfaces** — event ledger, damage breakdown, defense receipts, event-order
   panel, team-fight HP, not-modeled and trust surfaces.
6. **Optimizer surfaces** — Find best buy results band, per-slot BIS dialog.
7. **Edge surfaces** — share flow, banners (engine error, staleness, shared-view,
   consent), rewritten onboarding, footer; delete dead theme-toggle and old-CSS code.
8. **Responsive pass** — 1440 → ~1024 rail collapse, then the narrow-viewport pass.

Work test-first where behavior is testable (state transitions, payload building);
verify each phase in a real browser against the targets before moving on. `pytest`
must stay green throughout (API contract tests pin the frontend's request shapes);
`pylint src/` and `black --check` gate any Python you touch (you shouldn't need to).
The golden gate is untouched by pure UI work — if it ever diffs, you changed something
you shouldn't have.

Browser verification checklist per `architecture.md`: empty start, selection, level
changes, roster builds, A/B comparison, optimization, sharing, themes (now: the one
look), responsive layout.
