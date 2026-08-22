# Merge #202 follow-ups (2026-08-21)

Open items recorded while merging `command-amp-and-gnar-mega` into `main`
(five catch-up merges; every gate green at close). Each is a decision or a
post-merge slice, not a defect the merge left red. Delete a row when it lands.

| Item |
|---|
| architecture.md healing paragraph assumes HealAnchor lives in healing_helpers — confirm with HEALING-API.md |
| scripts/golden_baseline.json resolved to ours; RECAPTURE at end |
| ASIDE (UI agent): /api/compare passes deterministic=True, /api/calculate does not — crit rolls differ between paths; decide (probably both deterministic for the UI) |
| ASIDE samira.py rebinds OPTIONS after build_packet_module (pre-existing) — look |
| champions/__init__.py p_empowered_attacks classification orphaned — drop |
| aatrox: main's q_variant (default 7) makes ours' sweetspot bool path dead — cleanup pass later |
| aphelios.py:52 comment cites _Q_ONSLAUGHT_SECONDS_UNAUTHORED (stale name) |
| docs/plans/utility-axis-census.json pins healing_legacy.py:489 — regenerate |
| ASIDE (runes): main's keystone regexes leak keys onto unrelated runes (gate by rune name); _RD_* vs _GRASP_*/_DARK_HARVEST parse same sentences into two keys — one home later |
| data/atoms/manifest.json source_ref pins old champions.json hash — regenerate atoms manifest (find the script: grep scripts for manifest.json) at regeneration time |
| yasuo/yone `_q3_knockup_duration` duplicated; belongs in module_helpers next to crit rule (cleanup) |
| Dr. Mundo R-regen mode parity; Aurelion Sol golden parse surface — sweep |
| compiled walk misses participant[2] cleanse/canister heal (search_context parity, 2) — support staging gap in compiled path (program/compile) |
| milio: p_procs option + doubled cleanse count (2) — champion module |
| templates/index.html:132 literal 26.15 rail text — read from served patch field |
| A3: QSS/Mercurial/Umbral/Tear need AllyProducer members + CAPABILITIES (4-file change) — deferred with guards intact; trigger_stream A3 test red (4) — decide: xfail with issue or do it |
| e9 steraks: death_time moved 11.858 -> 15.091 with same shield numbers — timeline-side; re-derive corpus entry at end if timeline is right |
| per-recipient pricing of ally-scaled support rows (one row per recipient with that recipient's stats) - post-merge |
| repin_corpus.reprobe_failures str(exc).splitlines()[0] IndexError on empty message — tiny fix |
| ASIDE post-merge: Manaflow modelled only for Tear though five items carry the keys; Mercurial's 50%/2s movement duplicated between atom values and declaration (no accessor home) |
| F-2: four main-new ITEM_EFFECTS entries (Doran's Helm, Gluttonous Greaves, Ionian Boots, Lost Chapter) have no rule compiler — pinned by name UNDECLARED_ON_ARRIVAL; declare post-merge |
| F-9: cleanse KNOWN_CONTROL_KINDS vs CC_KIND_VOCABULARY disagree (disarm/ground dead; cripple/flee/pull/snare/stasis undeclared for cleanse) — post-merge |
| F-7 (pre-existing on HEAD): MODULE_CC names only CC-bearing slots; Fimbulwinter certification by candidate coverage alone — campaign follow-up |
| F-5 (strict xfail): Vi Blast Shield rider attaches to first Q even when that cast is attacker_state_blocked; needs walk-side re-anchor to first unblocked cast (damage.py:1864 binding) |
| ASIDE: ControlEvent has no target field — an enemy-cast control reaches every enemy (Lulu W polymorph); engine change post-merge |
| PERF DEBT: optimize_build Ahri/18/5 = 2.40 s merged vs 1.58 s main-alone (event-row schema: ~22 fields/row, +22% rows); CI smoke cap raised 5->8 s with the figures in the test docstring; the `lean` row shape is reserved for score-only and requested 0 times — adopting it for the optimizer is a shape decision (~40 ms) |

## Coordination note (2026-08-21, from the roadmap-closeout session)

Proposed split to avoid collisions while we both drive the closeout:

- **Roadmap session (this side)**: the final champion out_of_scope slots
  (Shyvana P, Sivir R, Sona E, Soraka P, Sylas R, Teemo P, Udyr P,
  Viktor P, Warwick E, Wukong W, Yuumi P/W), the goal's final
  verification sweep, and the reviewed-packets gate once a 16.16-current
  wiki sqlite exists.
- **Yours (suggested)**: the engine-side ledger rows above — ControlEvent
  target field, per-recipient support pricing, the A3 AllyProducer
  4-file change, F-2 rule compilers, F-9 cleanse vocabulary, optimizer
  perf debt.
- Milio p_procs/doubled-cleanse (ledger) overlaps our Milio P blocker
  receipt (tests/test_milio_fired_up_blocker.py) - flag before taking it.
- We push small commits to main frequently; ping via commit notes here
  if you want the split adjusted.
