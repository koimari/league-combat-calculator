# Gap ledger — every current feature vs. the 2a/2b mock

The mock shows the happy-path duel. The production frontend has a much larger
control surface. This ledger maps **every existing user-facing control** to its
home in the new design so nothing is silently dropped. "Decided" entries were
settled with Matthew (2026-08-08); "follow the design's logic" entries are the
implementing session's to detail, staying inside the design language.

## Locked decisions

1. **Implementation approach**: rebuild `templates/index.html` + `static/css/style.css`
   from scratch to the new IA. Keep `static/js/app.js`'s state model and API layer;
   port its render functions section by section. Vanilla JS stays; the
   receipts-only contract (no formulas in the browser) stays; APIs unchanged.
2. **Comparison off (single build)**: collapses to a dedicated single-build layout
   (centered build + absolute metrics), not an empty B column. Turning comparison
   on switches to the duel layout. The verdict strip in solo mode shows Build A's
   absolute numbers; "Enable Build B" is the visible affordance to enter the duel.
3. **Theming**: one committed look (cream canvas + dark rail). The dark/light
   theme toggle is retired. `data-theme` plumbing may be removed.
4. **Responsive**: desktop-first (1440 reference, graceful to ~1024 by collapsing
   the rail to 2a's summary width). A dedicated narrow-viewport pass is a named
   later phase **on this branch, before merge** — the browser-verification gate
   in `architecture.md` still includes responsive layout.

## Rail · step 1 Champion

| Current control | Home in new design |
|---|---|
| Champion picker (modal, search) | Expanded step 1; keep the shared picker dialog restyled to the design language |
| Role select, level stepper (level cap: trust backend validation, top-lane 20) | Expanded step 1; summarized as "MID · LV 9" when collapsed |
| Quest toggle, boots toggle | Expanded step 1; boots state appears in the collapsed summary ("BOOTS ON") |
| Ability ranks + cast counts (per ability) | Collapsed: the P/Q/W/E/R chips (rank·casts). Expanded: steppers, as the 2b enemy card shows for ranks |
| Ability variant/stance rows (multi-form champions) | Expanded step 1, under the ability chips |
| Champion options row (stacks/charges/forms, backend-declared toggles/selects/numbers) | Expanded step 1, "Scenario options" group under abilities |

## Rail · step 2 Roster

| Current control | Home in new design |
|---|---|
| Enemies (up to 5) and allies (up to 4), add/remove | 2b's expanded roster step; cards stack, enemy = red accent, ally = neutral accent |
| Practice target button | An entry in the add-enemy flow ("vs practice target") |
| Per-card: champion, role, level, ability ranks | Exactly as the 2b Aatrox card shows |
| Per-card: items (6 boxes) with stacks + item options | 2b's item boxes; stack/option editors open on box click (small popover in-card) |
| Per-card: boots toggle, quest toggle, ally-effects toggle (allies only) | Row of toggles in the card, same idiom as role/level |
| "Affects your BIS" insight callout | Keep — it's in the mock; feed it from real receipts only, else omit it (no invented prose) |

## Canvas · the build panel

Builds are **not** a rail step. A rail step that edits slots while the duel
canvas mirrors them read-only means two homes for one concept, and the mirror
is the one the user is already looking at. So the duel panel *is* the build
editor: `renderDuelSide` owns every control below, and the rail carries the
two steps (Champion, Roster) that are genuinely scenario setup.

| Current control | Home in new design |
|---|---|
| A/B 6 item slots, per-slot picker | Each `.duel-row` on the duel canvas is the picker button for that exact slot |
| Keystone slot per build (modal picker; uncompiled keystones greyed) | 7th row per side, same duel-row grammar, opening the keystone picker |
| Per-slot stacks and item options | `.duel-slot-controls` under the row that declares them |
| Copy A→B / B→A | The one whole-side move, in each side's `.duel-side-head` |
| Compare on/off toggle | The verdict strip only — "Enable Build B" on the empty challenger side, "Disable Build B" from the live duel (see locked decision 2) |
| Per-slot BIS ("Find best item for a slot", objective filter, ranked candidates, certified-subset notes, Use button) | BIS chip on each slot row plus the whole-build entry in `.build-actions`; keep every receipt/coverage note |

## Rail · Constraints block

| Current control | Home in new design |
|---|---|
| Available gold input | "Available gold" row becomes editable |
| Allow selling (pivot) checkbox | Row in the Constraints block, above Find best buy |
| Objective picker (overall/kill/survival/damage/utility) | "Objective" row expands to the 5-way segmented control (option 1a/1b show the idiom) |
| Window: rotations, window-per-rotation, auto-uptime calculated/explicit + % | "Window" row expands to the three controls; collapsed summary e.g. "1 rotation · 10s · AA calc" |
| Game state: Theory / Snapshot lens (+ mode descriptions) | A Constraints row ("State: Theory"); the mode sentence moves to the expanded editor. 1c's header shows where state reads back: "· THEORY · 1 ROTATION ·" |
| Find best buy button | Stays as the mock has it (paper button at rail bottom) |
| Optimizer results (plan summary, buy/sell/combine receipt, gold spent/remaining, partial-exhaustive note, apply) | **Not in the mock.** Render as a canvas takeover band below the verdict strip (a "best buy" result panel in the design language), never a toast; every receipt and truncation note survives |

## Canvas · verdict, duel, timeline

| Current surface | Home in new design |
|---|---|
| Verdict strip (winner, delta, objective) | Mock's header band |
| Metric list A/B (incl. "higher is better except Kill time" note) | Delta spine; keep the exception note as a spine footnote |
| Gold delta + one-line recommendation | Spine footer (1c shows it: "GOLD DELTA −300g · B is cheaper and stronger…") |
| Team-fight HP at end (all participants, shields, revives) | Below the spine or as a fourth canvas band; 1a's right panel shows the bar idiom |
| Fight timeline + cast markers | Mock's timeline band |
| Event ledger (time-indexed rows, per-row certainty chips) | "Open event ledger" expands a full-width band under the timeline |
| Damage breakdown, defense receipts | Expandable bands in the same ledger area |
| Event-order panel (optimal rotation receipt) | Same expandable area, only when the receipt exists |
| Certainty chips EXACT/ESTIMATE/BOUNDARY + trust legend | Keep chips on ledger/breakdown rows; legend lives with the ledger header |
| Not-modeled panel | Compact disclosure near the verdict (a "qualified result" marker), expanding to the list — must stay visible-when-relevant, per product principle 6 |
| Engine errors, staleness banner, share-view banner | Full-width banners above the verdict strip, design-language colors |
| Scenario sentence (aria-live summary) | Keep as visually-hidden live region; the rail summaries replace its visual role |

## Chrome and edge surfaces

| Current surface | Home in new design |
|---|---|
| Top bar (brand, patch, auth) | Rail header holds brand + patch (mock); auth/logout moves to a small rail footer |
| Share build button + panel (permanent link warning) | Action in `.build-actions` under the duel panel; panel keeps its permanence warning verbatim |
| Onboarding overlay | Rewrite for the new IA — current copy references removed Quick mode (stale even today). Keep the once-per-browser localStorage contract |
| Feedback widget, consent banner | Keep mounts; restyle to design language |
| Footer (legal links, Riot disclaimer) | Slim footer band under the canvas |
| Dark/light theme toggle | **Retired** (locked decision 3) |

## Accessibility floor (unchanged, non-negotiable)

Keyboard navigable, visible focus, readable contrast on both dark rail and cream
canvas, aria-pressed/labels/live-regions preserved through the port, color never
the sole carrier of win/lose/team/certainty.
