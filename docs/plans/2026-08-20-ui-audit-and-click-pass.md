# UI audit and click pass — 2026-08-20

Two deliverables: (1) an audit of the user-facing UI as it runs today, each finding tied
to a runtime probe from this session; (2) the UX pass that follows from it, decided here
and discharged in the same change set. Status lives in the tables; delete a row when its
fix lands and the follow-up list below is the only thing left.

Evidence: `/api/calculate` probes against the local server (Aatrox L18 vs Practice Dummy;
Kai'Sa L13 + Kraken/Guinsoo/IE + PTA vs Akali L13) and Playwright drives of the real page.
`scripts/ui_click_probe.py` replays the after-state workflows and prints the click counts.

## Part 1 · Audit

### Functional defects (what the user reported, and what is actually wrong)

| # | Reported | Root cause (verified) | Fix |
|---|---|---|---|
| 1 | Level needs one click per level; 10 champions at 18 = 180 clicks | `.stepper` ± buttons only; the `#levelInput` number box is `visually-hidden`; new enemies always start at LV 1 | Slider + breakpoints (1/6/11/16/18/cap), number entry, enemies default to the main champion's level, "all roster → LV n" |
| 2 | Casts/Procs steppers do nothing | `engineAbilityRanks`/`engineChampionOptions` never read `abilityInput(slot).casts` except P→`passive_procs` and E→`mines_hit` when the module declares them. The engine schedules casts by cooldown inside the window; a cast count has no payload field. Aatrox's P proc button is disabled with a tooltip nobody reads (🚫 cursor in the report) | Remove the steppers. Show the engine's own cast count per ability (`cast_timeline`) as a read-only readout after a result |
| 3 | Scenario options shown at the bottom, not with their ability | `renderChampionOptions` renders every module option in one block under the kit; only options bound by name (`q_variant`, `passive_procs`, …) attach to a card | Options whose label or key names a slot (`Q Sweetspot hits`, `q_*`, `passive_*`) render inside that ability's card; the rest stay in the shared block |
| 4 | Aatrox Q variants unclickable / do nothing | Eight wiki packet variants render as buttons; `abilityOptionBinding` finds no module option for Aatrox Q, so the buttons are disabled and the payload ignores the index. Correct behaviour — wrong to render | Render a variant row only when the slot has a bound option |
| 5 | Q rank 5 at level 1 changes nothing | The UI clamps rank to `maxRank` only; `engineAbilityRanks` silently trims to the level budget before posting (the backend refuses `Q rank 5 requires champion level 9`). Probe: L1 Q1 = 400.9, L1 "Q5" = same request | Cap the control at the level-derived rank and the point budget; disable + at the cap and say why |
| 6 | Rotations slider does nothing | `configuredFightWindow = duration × rotations`, capped at the engine's 30 s; the backend's `rotation_count` only divides `expected_autos_per_rotation`. Two sliders for one number, and once the enemy is dead (see 9) more window adds nothing | One **Fight length** slider (1–30 s); `rotations` leaves the public capability contract, payload sends 1 |
| 7 | Aatrox Q shows one cast, not three spaced hits | `champions/aatrox.py::_darkin_blade` sums the sweetspot/normal triad into one entry by design ("Q: sum all three … into one entry"); one event at 0.25 s carries 829 damage | Out of this pass — a champion-module change (`add-champion`), recorded under follow-ups |
| 8 | Event ledger unreadable (`auto_attacks`, raw keys) | `renderPrototypeResult` prints `event.source` verbatim: `auto_attacks`, `on_hit_ability_passive`, `keystone_Press the Attack amp`, `passive_plasma`, `Q`; 0-damage rows after the target dies are listed one by one (13 of 17 rows in the Aatrox probe) | Human labels from one mapping (ability names from the kit, item/keystone names from the key), a table layout, post-death zero rows collapsed into one line |
| 9 | Keystone changes nothing (600 stays 600) | The headline is `headline_total` = damage dealt **before the target dies**, capped at its HP. Practice Dummy = 1,000 HP; an added enemy is LV 1. Probe: Aatrox L18 raw 2,870 → headline 1,000; with PTA raw 3,065 → headline 1,000; Kai'Sa 3 items vs Akali L1: 518 = 518 = 518, verdict "LEVEL". Keystones work (API: +195 PTA, +123 Electrocute) — the target was dead either way | Verdict discloses a defeated target (time of death, raw output, overkill); enemies default to the main's level; the objective strip suggests Kill time when every enemy dies |
| 10 | No auto-attack-only mode | The engine accepts `fight_mode: "auto_only"` (Aatrox L18: 1,060 vs 2,870) and no control sends it | "Actions: Full kit / Autos only" in the Window constraint; new scenario capability field |

### Other findings from the sweep

| Where | Finding | Action |
|---|---|---|
| Fight timeline | Cast-time labels overlap when autos land <0.3 s apart ("0.8s 0.9s 1.1s…" smear in the Kai'Sa run) | Suppress a label closer than 4% of the axis to the previous one |
| Constraints · Window | Default fight mode is `one_rotation` (5 s) from `fight_defaults`; the slider says "Window per rotation 10s" until the first render | Single Fight-length slider reads the engine default |
| Rail · Roster card | "Wiki ability ranks" ± per slot: 4 steppers per enemy; ranks are derived from level anyway (`defaultAbilityRanks`) | Keep (collapsed under level), ranks follow level unless touched |
| Rail · Roster | Champion picker closes after each pick; no way to set several levels at once | Roster header quick-set |
| Duel panel | Item slot → modal → pick → modal closes: 2 clicks + a search per slot | Picker stays open and advances to the next empty slot of the same build |
| Duel panel | Rune page = 9 separate modals | One rune-page dialog |
| Practice dummy | 1,000 HP / 100 armor / 100 MR at LV 18: dies to one Q at level 18 | Keep the exact-stats contract; the verdict disclosure (9) makes it legible |
| No console errors, no 4xx/5xx across the sweep (BIS, best buy, share, objectives, snapshot lens all respond) | — | — |

### Click counts (measured on the running page)

| Workflow | Today | After this pass |
|---|---|---|
| Champion → LV 18 | 20 (open, search+pick, 17 ×) | 4 (open, search+pick, one breakpoint) |
| 10 roster champions at LV 18 | 190 | 20 (add+pick each; level inherited from the main) |
| Six items in Build A | 12 + 6 searches | 7 + 6 searches |
| Full rune page (keystone, 5 runes, 3 shards) | 18 | 10 |
| Change fight length | 2 controls, multiplied | 1 slider |
| Autos-only reading | impossible | 2 |

## Part 2 · Decisions

1. **Casts/Procs steppers are removed**, not hidden. A module-declared count option (Kai'Sa
   plasma, Heimerdinger mines) renders as that option, on the ability card it names.
2. **Variant rows render only when bound.** The flattened wiki packets stay in the catalog
   for BIS; nothing unbound is shown as a control.
3. **Rank controls are legal by construction**: cap = `min(maxRank, level-derived cap)`,
   total points ≤ level, trimmed the way `engineAbilityRanks` already trims. The "+" is
   disabled at the cap with the reason in its title.
4. **Level is a slider with breakpoints** (`1 · 6 · 11 · 16 · 18`, plus the role cap when it is
   20) and a visible number input; the same component on main and roster cards. A new
   enemy or ally starts at the main champion's level. The roster step carries
   "Everyone → LV n".
5. **One Fight-length slider.** `rotations` is removed from the public capability contract
   and the template; the payload sends `rotations: 1`. `MAX_ROTATIONS` stays a backend limit.
6. **Actions segmented control** (Full kit / Autos only) next to the fight length; payload
   `fight_mode: "auto_only"`. New scenario field `actions` with token `data-fight-mode`.
7. **Defeated-target disclosure** in the verdict strip: "ENEMY DEAD AT 0.8 S · 4,556 RAW ·
   2,653 OVERKILL" under the headline whenever every enemy dies inside the window; the
   summary sentence points at Kill time.
8. **Ledger = a table** (time · actor · action · target · damage) with one label function
   (`eventSourceLabel`) for every source key, and a single collapsed row for post-death
   zero-damage events.
9. **Item picker advances**: picking an item for `attacker.buildX.i` fills it and re-opens on
   the next empty slot of the same side; Esc/close or a full build ends the run. Roster item
   strips behave the same.
10. **Rune page dialog**: one dialog for keystone, five runes and three shards; choosing a
    keystone fixes the primary path, the first secondary choice fixes the secondary path.
    `validate_rune_page` stays the authority.

## Success criteria and results (2026-08-21)

| Criterion | Result |
|---|---|
| Golden gate zero diffs | `OK: snapshot identical` — no calculation code changed |
| `black --check`, `pylint src/`, `pytest` | see the session recap; the capability contract tests (`test_issues_78`, `test_f0_frontend`, `test_app`, `test_frontend_qa_147_157`) were updated with the controls they pin |
| Champion → LV 18 | 4 clicks (open, search+pick, breakpoint) — Playwright drive |
| Enemy at the main's level | 0 clicks (inherited: Akali entered at LV 18); "Everyone → 11" moved the roster in 1 |
| Five ordinary items (boots on) | 6 clicks: one open, five picks; the picker closed itself on the full build |
| Full rune page | 10 clicks: one open, keystone, 3 primary, 2 secondary, 3 shards; kicker read "9 OF 9 CHOSEN · PRECISION + SORCERY" and the engine accepted the page |
| Rank cap | Q "+" disabled at LV 1 with title "Rank 2 needs level 3" |
| Defeated-target disclosure | Aatrox L18 vs dummy: headline 1,000 TDD with "ENEMY DOWN AT 0.8 S · 1,435 RAW · 435 OVERKILL"; with 5 items + runes "… 5,768 RAW · 4,768 OVERKILL" |
| Autos only | Aatrox L18 vs Akali L11, 5 s: 1,644 full kit → 690 autos only; Window reads "5s · autos only · AA calc" |
| Event lanes | "Auto attack", "On-hit passive", "Q · The Darkin Blade", then one lane "Every enemy is down · 16 later events landed on nobody" |
| No dead control mounted | casts/procs/hits steppers, unbound variant rows and the rotations slider are gone from the template, app.js and the capability contract |

## Follow-ups (not this pass)

- Aatrox Q as three timed hits (`champions/aatrox.py`, `add-champion`).
- Practice Dummy presets by level (needs a sourced table; nothing invented).
- Enemy "Passive procs" option copy ("Backend-declared enemy champion inputs") is module
  prose; better labels belong to each module's `OPTIONS`.
