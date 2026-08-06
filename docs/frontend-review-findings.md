# Scryglass frontend — ground-up review findings (F0)

Audit date: 2026-08-06 · Branch: `codex/f0-frontend` · Baseline commit: `d94f75c`

## Method

- Live app: `flask --app src.app run --port 5000` (Python
  `/Users/river/Projects/league-combat-calculator-audit/.venv/bin/python`).
- Browser automation: Playwright (`/tmp/pw-qa`, playwright-core 1.62.1) with
  the pinned Chromium
  (`.../ms-playwright/chromium-1129/.../Chromium`), desktop 1440×900 and
  mobile 390×844 (touch emulation).
- Every claim below was observed in the running app (DOM probes, network
  capture, screenshots), not inferred from source alone.
- Gates at audit time: `pytest -q` 3955 passed; `pylint src/` 9.48/10;
  `black --check` clean; golden compare identical.

---

## A. Bugs and inconsistencies (verified live)

### A1. CRITICAL — the analyst builder is duplicated in the template with 45 duplicate IDs

`templates/index.html` contains the **entire analyst builder twice**:

1. a pre-P5 top-level `.content-grid` (builder + result column) that is
   **always visible** — it is not inside `#quickView` or `#analystView`;
2. a P5-era copy wrapped in `<div id="analystView" hidden>` (the same builder
   + result column + scenario rail + `#shareAnalystButton` + trust panels).

45 element IDs appear twice (`championPicker`, `statsGrid`, `slotsA`,
`slotsB`, `resultStatus`, `enemyCount`, `roleSelect`, `levelInput`, …).
`document.getElementById` resolves every lookup to the **first** copy — the
always-visible legacy one — so the P5 view system drives the wrong DOM:

- **On initial load** the "Quick" tab is marked active while the full analyst
  builder renders *above* the quick view. Desktop: legacy grid occupies
  y 214–4075 (h 3861px), quick view starts at y 1792. Mobile (390×844):
  legacy grid is 5893px tall, quick view starts at y 3610. First-time users
  land on a dense analyst form, not the promised 3-click flow.
- **Clicking "Analyst"** hides the quick view and reveals `#analystView` at
  y 4147 (desktop) — *below* the still-visible legacy grid. Its inner
  `#slotsA` etc. are **empty** (0 children) because rendering binds to the
  legacy copy. Analyst mode therefore shows a populated builder plus an empty
  duplicate below it.
- **`#shareAnalystButton` is effectively unreachable**: it exists only in the
  `#analystView` copy. In the default view it is inside a `hidden` container;
  in analyst mode it sits at y ~4993, far below the fold, attached to an
  empty build grid. The analyst share feature is dead in practice.
- A shared link (`?share=token`) renders its read-only card inside
  `#quickResults`, which is pushed to y 1792+ by the legacy grid — the shared
  content is a full viewport-height below the fold on desktop.

Root cause: the P5 change (commit `c6de8f9`) copied the builder markup into a
new `#analystView` wrapper instead of moving it.

### A2. Engine failures are invisible

`scheduleEngineCalculation` writes `/api/calculate` failures into the hidden
legacy divs `#why` / `#resultContext` (both `hidden`). The visible result
column shows nothing: `resultStatus` stays `"waiting"`, scores keep stale
values, and no error text appears anywhere. Any calculation failure is
silent to the user. (Observed in code; the visible column never receives the
error path.)

### A3. The per-slot damage breakdown + certainty chips render into a hidden container

The analyst's detailed "Damage sources / participant ledger" table
(`renderExactBreakdown`) writes into `#damageBreakdown`, which lives inside
the `hidden` `#analystView` in the default view and at the very bottom of the
empty duplicate in analyst mode. After a successful calculation the element
is unhidden but measures 0×0 because its parent chain is `display:none`
(quick mode) or detached below the fold (analyst mode). **The most valuable
analyst surface — per-ability damage with per-slot certainty chips — is never
actually visible.** (Verified: after Akali + Shadowflame vs Orianna the table
text exists in the DOM, `hidden=false`, rect 0×0.)

### A4. Range sliders have no accessible name

`<label class="range-control"><span>Rotations</span><output>…</output><input
type="range" …></label>` — the label associates with the `<output>`, not the
`<input>` (the `<output>` is the first labelable descendant), so
`input.labels.length === 0` and the sliders have no accessible name. Affects
Rotations, Window-per-rotation, and Auto-uptime in the analyst builder.

### A5. Four H1 elements on one page

Page load contains `Choose a champion` (legacy copy), `Choose a champion`
(analyst copy), `What should I build next?` (quick), and `Item calculator`
(analyst wrapper). Broken document outline; screen-reader users get no
usable page title.

### A6. Analyst mode blocks the first calculation on an enemy

`scheduleEngineCalculation` requires `state.targets.length > 0` with every
target championed. Quick mode defaults to a practice target (Jhin, lvl 18);
the analyst builder starts with zero enemies, so a new analyst user must go
through three pickers (champion → item → enemy) before the first number
appears. The empty roster hint ("Add a target to the coupled timeline") is
the only affordance.

### A7. No pending indicator during engine calculation

`engine.pending` is tracked but never rendered; `resultStatus` stays
`"waiting"` for the whole request and flips straight to `"reviewed"`. On a
slow network the app looks dead between edits. (Local latency is ~10 ms, so
this only bites in production/WAN conditions — but BIS is a heavier sweep
and the quick flow shows a spinner, so the analyst column is inconsistent.)

### A8. "Quick · 3 clicks" copy vs 4-step markup

The tab hint promises 3 clicks; the `<ol class="quick-steps">` renders 4
numbered steps (champion, role, enemy, items) + a run button. Enemy and
items are optional, so the flow *can* be 3 clicks (champion, role, run) —
but the visible 4-step list makes the copy look wrong. Either rename the
hint or mark optional steps visually.

### A9. Flagged to the calculation team — surprising BIS ranking (not a frontend bug)

Quick flow, Akali mid, no items, vs itemless Jhin lvl 18, 10s window:
`/api/bis` ranks **Blade of the Ruined King #1 (+699 TDD)** over Hextech
Gunblade and Shadowflame. The frontend renders the backend ranking
faithfully (candidate names/scores/deltas all match the API), so this is a
modeling/ranking question, not a display bug — but it is exactly the kind of
"Best modelled" surprise a casual user will screenshot and tweet. Worth a
domain check on how BORK's %HP on-hit and AD value are attributed in
sustained windows with calculated AA uptime. (The quick card correctly
labels the result space: "Best modelled" / coverage notes.)

### A10. Mixed external icon CDNs

Champion/item images load from `ddragon.leagueoflegends.com/cdn/16.15.1`;
BIS candidate icons load from `raw.communitydragon.org/16.15/...`. Two
external dependencies, version-pinned separately; if either is unreachable,
images fail silently (broken `<img>` with no fallback). No error state for
image load failures anywhere.

### A11. Staleness and certainty surfaces work but are buried

- The champion STALE badge (staleness.js) works: Soraka shows
  `STALE · PATCH 16.15` next to the champion name. Item badges appear only
  on filled slots. The badge has no link/explanation beyond a `title`.
- The certainty legend (EXACT / ESTIMATE / BOUNDARY) renders only after a
  champion is picked, and in the analyst view it lives in the `#analystView`
  copy (below the fold / in the empty duplicate) — so analysts rarely see
  it. Per-slot chips exist only inside the invisible `#damageBreakdown`
  (A3) and in BIS rows.
- The `/api/certainty` + `/api/not-modeled` contracts load correctly (not
  placeholder mocks in the live app).

---

## B. Dead code and duplication

### B1. Dead renderers (defined, never called)

- `renderBuilder()` — the legacy builder renderer writing into the hidden
  `#builder` shell (the one referenced by the #78 capability work). Unused.
- `renderResults()` — legacy result renderer writing into hidden
  `#winnerVisual` / `#scoreGrid` / `#threshold` / `#rotationTable` /
  `#resultContext` / `#tableA` / `#tableB`. Unused.
- `renderExactResults()` — legacy "exact" result renderer. Unused.
- `renderEngineUnavailable()` — engine-availability screen. Unused.
- Transitively dead with the above: `renderResistanceOutput`,
  `renderDamageBreakdown`, `renderMechanicsOutput`, `renderExactStatMatrix`,
  `renderExactResistance`, `renderExactMechanics`,
  `renderExactSupportOutputs`.
- Legacy optimizer helpers with zero call sites: `applyRosterBuild`,
  `optimizeRosterBuild`, `reoptimizeAttackerAfterRosterChange`,
  `rosterBisCandidates`, `rosterBisStacks`, `bisCandidates`,
  `stacksForBis`, `openRosterBis` (a one-line alias of `openBackendBis`).

### B2. Hidden legacy DOM the renderers target

`#builder`, `#winnerVisual`, `#scoreGrid`, `#resistanceOutput`,
`#threshold`, `#mechanicsOutput`, `#rotationTable`, `#resultContext`,
`#resultFootnote`, `#tableA`, `#tableB`, and the `.method` details block
with the `#baseDamage` / `#apRatio` / `#physicalDamage` / `#adRatio` manual
inputs. All `hidden`. The manual inputs are still bound at boot
(`addEventListener` on each) and feed the legacy `calculateBuild`
local-simulator path — dead UI, live state fields.

### B3. Duplicate template ids

45 duplicated IDs (see A1). Also orphaned JS lookups:
`$("scenarioChampion")` / `$("scenarioRole")` target elements that do not
exist in the template (null-guarded, so silent).

### B4. Near-duplicate view markup

The top-level `.content-grid` and the `#analystView` `.content-grid` are
byte-identical except for `#shareAnalystButton` and the trust panels. One
copy must go; the survivor should be the `#analystView` one (it has the
scenario rail, share button, trust panels, and hidden legacy leftovers to
prune).

---

## C. UX friction and information architecture

1. **The analyst/quick split is the right model** — the product brief asks
   for a decision-first surface plus a full scenario builder — but the
   landing is broken by A1: the wrong view is visible on load, and the
   analyst tab reveals an empty shell. The IA is sound; the wiring is not.
2. **No bridge between quick and analyst.** Quick results give a
   recommendation with no way to open the same scenario in the analyst
   builder (the shared-build "Open in editor" only works for share tokens).
   The natural loop — quick verdict → analyst deep-dive → share → receipt —
   is missing two of its four edges.
3. **Trust surfaces are undiscoverable.** Certainty chips, staleness badges,
   and the not-modeled list exist but are scattered (quick after-row, analyst
   copy below fold, hidden breakdown). There is no single place where the
   user can see "how much do I trust this number and what is missing".
4. **The analyst empty state is a wall.** No champion → four sections of
   "Choose a champion…" prompts; no enemy → calculation silently waits. The
   scenario sentence ("Akali level 1 · Overall · theory state · 1 rotation ·
   5s each · 0% auto uptime") is good when it appears, but appears only after
   a champion is chosen.
5. **BIS latency feedback is good** (dialog opens with "Scoring every legal
   candidate…"), the quick run has a spinner with elapsed time — but the
   analyst result column has no equivalent for engine runs.
6. **Result area is answer-first but buried**: after a full scenario the
   result column shows the verdict + metric list + health ledger + event
   ledger, yet the per-slot breakdown (A3) that would let an analyst verify
   *which ability/item produced what* is invisible. The proof trail exists —
   it is just not surfaced.

---

## D. Accessibility and mobile

1. A5: four H1s; also duplicate landmarks: `nav` count 2, dialogs 2
   (picker + BIS — both legitimate).
2. A4: unlabeled range sliders. The feedback widget's offset-direction
   control (`#fbOffDir`) is also unlabeled.
3. All 174 buttons have accessible names (text or aria-label) — good.
4. Mobile (390×844): the quick flow works end-to-end and its result cards
   stack single-column (the P5 media queries are fine); the view-switch tabs
   stretch full-width. The blocker is purely A1 (6k px of legacy builder
   above the quick view). Touch targets in the quick flow are adequate; the
   analyst steppers are small but usable.
5. No `prefers-reduced-motion` handling for the map wash / smooth scrolls;
   no `:focus-visible` audit beyond what shipped (partial).

---

## E. Performance

| Asset | Size |
|---|---|
| `static/js/app.js` | 312 KB (258 top-level functions) |
| `static/css/style.css` | 71 KB |
| `templates/index.html` | 24 KB |
| `static/data.json` | 237 KB |
| `/api/champions` + `/api/items` + `/api/config` | ~750 KB JSON |
| `static/js/feedback.js` + `staleness.js` | 24 KB |

- Local load-to-idle ≈ 640 ms; the JSON bootstrap is ~1 MB (fine locally,
  worth cache headers / a lighter config split in production).
- `/api/calculate` ≈ 10 ms locally; quick "Best next item" round trip
  ≈ 230 ms (baseline + BIS in parallel). BIS 95-candidate sweep is fast
  locally; production latency needs the pending states from A7.
- Render churn: `render()` rebuilds the entire builder innerHTML on every
  state change (45 call sites in app.js). Acceptable at this scale, but the
  duplicated DOM (A1) doubles the work and defeats browser layout caching.
- `app.js` is one 312 KB file with no module split; the quick and analyst
  flows, trust labels, sharing, and the review tool all live in it. Splitting
  is not required for F0 but the dead-code removal (B1/B2) trims ~10–15 KB.

---

## Fix list implemented on this branch

See `docs/frontend-design.md` for the design; the implementation:

1. De-duplicated the analyst builder (single copy inside `#analystView`);
   quick view is the true landing; analyst tab shows the one populated
   builder. (A1)
2. Removed dead renderers and hidden legacy DOM; made the manual-package
   bindings null-safe. (B1/B2)
3. Moved the damage breakdown + per-slot certainty chips into the visible
   result column. (A3)
4. Added a visible engine error surface (`#engineError`) and a
   "calculating…" pending state. (A2, A7)
5. Added a one-click "Practice target" enemy affordance in the analyst
   roster. (A6)
6. Added "Open in analyst" from quick results (quick → analyst bridge).
   (C2)
7. Fixed slider labels; single visible H1 per view ("Item calculator"
   stays the analyst page H1, the champion name became an H2). (A4, A5)
8. Quick optional steps were already marked visually; the 3-click promise
   is honest (champion, role, run). No change needed. (A8)
9. Surfaced the defense receipts (starting armor/MR, shields, flat/crit
   reductions, shield/healing absorbed, target endpoint) in a visible
   "Starting defenses" section of the result column — previously they only
   rendered into a hidden container. (A3 extension)
10. Shared-link recipients now get the read-only build card above the fold
    (the interactive quick form collapses in ?share= mode). (A1 extension)
11. Added `tests/test_f0_frontend.py` (20 tests) pinning the above, and
    updated the stale frontend-contract pins in `test_app.py` /
    `test_issues_78.py` that referenced the removed legacy DOM.
