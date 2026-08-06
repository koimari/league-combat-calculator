# Scryglass frontend — recommended design (F0)

Companion to `docs/frontend-review-findings.md`. This is the target design the
F0 branch implements. It is intentionally concrete: component model, view
structure, trust surfacing, mobile strategy, and the exact DOM contract the
implementation follows. Backend API contract is unchanged; the only additions
are frontend-only.

## 1. Design principles (from PRODUCT.md, operationalized)

1. **The first viewport answers the question.** Quick mode is the landing and
   stays the landing: champion → role → (optional) enemy/items → top-3 next
   items with numbers. No dense form may precede it.
2. **Analyst is one mode, not a ghost.** There is exactly ONE analyst
   builder in the DOM, exactly one set of control IDs, and it is what the
   "Analyst" tab reveals. No duplicate markup, no empty shells.
3. **Trust is a first-class surface, not a footnote.** Certainty
   (exact/estimate/boundary), staleness (patch drift), and not-modeled items
   render next to the numbers they qualify, in both modes, with one shared
   legend pattern.
4. **The proof trail is visible by default.** The per-slot damage breakdown
   (ability/source × damage × certainty chip) is the analyst's core output;
   it lives in the visible result column, not a hidden div.
5. **Every async state is rendered.** waiting → calculating → reviewed /
   qualified / error are distinct visible states in the result column.
6. **Mobile is the same product.** Quick mode first; analyst builder stacks
   single-column with section grouping; the view switch stays at top;
   touch targets ≥ 40 px.

## 2. Information architecture

```
Landing (/) ──► Quick view (default tab, active on load)
                 ├─ steps 1–4 (champion, role, enemy?, items?)
                 ├─ "Best next item" → top-3 cards
                 │    ├─ certainty + staleness row
                 │    ├─ "What is not modeled" details
                 │    └─ [Share] [Open in analyst]      ← new bridge
                 └─ share links (?share=) render the read-only card here
Analyst tab ───► Analyst view (the single builder)
                 ├─ scenario rail (game state, objective, sentence)
                 ├─ champion → abilities/options → builds A/B → roster →
                 │    window (unchanged controls)
                 ├─ result column:
                 │    ├─ verdict (winner letter, label, delta)
                 │    ├─ metric list (Overall/Kill/Survival/Damage/Utility)
                 │    ├─ health ledger (team fight HP at end)
                 │    ├─ damage breakdown + certainty chips   ← moved visible
                 │    ├─ event ledger (proof details)
                 │    ├─ trust row (certainty legend + staleness) ← visible
                 │    ├─ not-modeled panel
                 │    ├─ engine error surface                 ← new
                 │    └─ feedback widget (receipts)
                 └─ [Share this build] (visible, reachable)
```

Quick ↔ analyst relationship: quick is the decision funnel; analyst is the
audit surface. Two bridges: quick results → "Open in analyst" (loads the
quick scenario into the builder) and analyst → share link → "Open in
editor" (already exists). Both flow through the same loadout-shape function.

## 3. Component model (single render path)

- **One `render()`** drives the active view. It renders the analyst builder
  (champion card, abilities, options, slots, roster, window), the result
  column, the scenario rail, and the trust panels. The quick view is
  self-contained (`renderQuickView`), as today.
- **No duplicate IDs.** `templates/index.html` defines each control id
  exactly once. `document.getElementById` and the delegated click listener
  are the only wiring (already the case — keep it).
- **Result column components** (analyst):
  - `ResultHero` — verdict, status chip (`waiting | calculating | reviewed |
    qualified | error`), summary line.
  - `MetricList` — 5 objective rows (A/B or A-only).
  - `HealthLedger` — participants with HP at end.
  - `DamageBreakdown` — per-source rows with certainty chips (was hidden;
    now inside the result column).
  - `DefenseReceipts` — "Starting defenses" table (armor/MR after
    penetration, shields, flat/crit reductions) + the shield/healing/target
    endpoint receipt line (was hidden; now visible).
  - `EventLedger` — `<details>` timeline + ledger table.
  - `TrustRow` — certainty legend chips + staleness badge summary.
  - `NotModeledPanel` — collapsible list.
  - `EngineError` — visible error box on failure (new).
  - `FeedbackWidget` — receipts mount (unchanged).
- **Quick components** (unchanged): steps, grids, run button, spinner,
  top-3 cards, after-row (share + trust legend), not-modeled details,
  shared-build read-only card. New: "Open in analyst" on the after-row.

## 4. Trust surfacing (certainty / staleness / not-modeled)

- **One legend pattern** (`EXACT / ESTIMATE / BOUNDARY` chips with
  tooltips) shared by both modes. Quick: in the after-row (as today).
  Analyst: a `TrustRow` directly under the result hero, always visible once
  a champion is selected.
- **Per-slot certainty chips ride the numbers**: every damage-breakdown row
  carries its chip (already implemented in `renderExactBreakdown` — the fix
  is only that the container is now visible).
- **Staleness** stays a DOM-observing badge module (staleness.js): champion
  badge next to the champion name, item badges on filled slots, and a one
  line in the analyst TrustRow when the champion or any selected item is
  stale ("STALE · PATCH 16.15 — differs from game files"). No new API.
- **Not-modeled** stays a collapsible panel in both modes (as today).
- These three surfaces are discoverable because they sit next to the
  numbers they qualify, not at the bottom of a hidden duplicate.

## 5. State & async feedback (analyst result column)

- `resultStatus` values: `waiting` (no scenario) → `calculating…` (request
  in flight, with a small spinner) → `reviewed` (complete timeline),
  `qualified` (partial/estimate timeline), or `error` (request failed).
- `EngineError`: on `/api/calculate` failure, render the backend's error
  message in a visible alert box in the result column and set the status
  chip to `error`. This replaces the silent hidden-`#why` path.
- The BIS dialog and quick spinner keep their existing loading feedback.

## 6. Mobile strategy (≤ 720 px)

1. Quick mode is the default landing; the analyst builder is one tap away
   via the full-width tab bar.
2. Analyst builder stacks single-column (already does); section rules keep
   visual grouping. The result column follows the builder, as today.
3. `Open in analyst` and `Share` are reachable from quick results; the
   shared read-only card renders above the fold because the legacy duplicate
   is gone.
4. Touch targets: quick grids already use large cards; keep ≥ 40 px hit
   areas on the analyst steppers/buttons (the P5 "control hit targets"
   pass already did most of this — do not regress it).
5. Viewport: keep the existing `meta viewport`, portrait media queries, and
   single-column card stacking. Add `prefers-reduced-motion` off-switch for
   the smooth-scroll/map-wash animations.

## 7. Performance

- Remove dead code (renderer family + legacy hidden DOM) — trims ~10–15 KB
  of app.js and every redundant DOM node from the page.
- Keep the delegated click listener (one listener, not N).
- The bootstrap JSON (~1 MB) is served locally; production should set
  cache headers on `/static/*` and keep `/api/config` versioned. No
  frontend change needed for F0.
- Quick flow already parallelizes baseline + BIS; keep that.

## 8. Implementation checklist (what the F0 branch ships)

- [x] index.html: delete the top-level duplicate `.content-grid`; the
      `#analystView` copy is the single analyst view.
- [x] index.html: move `#feedbackWidget` + `#damageBreakdown` into the
      visible result column; add `#engineError`; remove hidden legacy divs
      and the `.method` manual-package block.
- [x] index.html: add `aria-label` to range sliders; single visible H1 per
      view ("Item calculator" H1 + champion name H2); optional quick steps
      already marked; same-origin favicon (kills the /favicon.ico 404).
- [x] app.js: remove dead renderers/helpers; null-safe manual-package
      bindings; error + pending states; practice-target button; quick →
      analyst bridge; visible defense receipts; result-status chip;
      shared-link read-only mode.
- [x] capability contract: drop the stale `damage_package` control family
      (its manual inputs are gone); map the two new controls to declared
      families (reported to parent).
- [x] tests/test_f0_frontend.py: no duplicate ids; single analyst builder;
      visible breakdown + error surface; practice-target + bridge wiring;
      dead code gone; node --check.
- [x] Gates: pytest full, pylint ≥ 9, black, node --check, git diff
      --check, golden identical (UI-only change).

## 9. Out of scope / reported for the backend agent

- A9 (BORK #1 for Akali): ranking question for the calculation team.
- Cache headers / CDN consolidation for icons (deploy concern).
- `/api/config` payload size (backend concern).
