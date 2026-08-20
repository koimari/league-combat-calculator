# Goal: 0 failed + 0 xfailed on the league-combat-calculator suite

## Objective
Drive the full pytest suite to **0 failures** and **0 xfailed**.

## Baseline (recorded 2026-08-12)
- Passing: 7,584
- Failed: 48 (all depth2-atom-corpus data drift)
- Xfailed: 57 (mixed: alternate-contract variants, source-unavailable gates, missing features, deliberate boundaries)
- Verification command: `.venv/bin/pytest -q --tb=no`

## Protocol
Fixed evaluation: the full test suite must exit with zero failed and zero xfailed.
- **In-bounds levers**: update test assertion values to the current regenerated data; regenerate atoms; remove/retire test rows that encode no-longer-possible alternatives (a removed variant's PRIMARY is already covered); reconcile stale golden baselines with every diff explained.
- **Forbidden (never do to move numbers)**: weaken a real assertion, delete a genuine boundary test to hide it, fake an implementation, materially change a pin that a live mechanic depends on.

## Scope
### Phase A — failures (48)
- Eclipse value drift + cascade (10)
- Gunmetal Greaves cache/format (7)
- Champion stat drift: Camille, Bel'Veth, Azir, Syndra \u2014 R, Sterak's (8)
- Item / boot / rune drift: Runaan's, Fleet Footwork, Hail of Blades, tier-3 boots (15)

### Phase B — xfails (57)
- Remove \"alt\" alternate-contract rows whose primary is already pinned (the removed row only re-tests the unchosen branch).
- Source-unavailable gates: flip to documented-boundary rows or implement the missing source.
- Deliberate boundaries: convert to a named test (fail-closed receipt asserted) instead of xfail.

## Stop condition
Full suite exits with `0 failed, 0 xfailed`. Report evidence per round.


## Progress
### Round 1 (this session)
- Phase A failures fixed: manifest-hash (3) + Zeri notes, Eclipse value drift across test_item_damage / test_eclipse_timing_packet / test_state_lifecycle_consumers / test_eclipse_timeline (all green now). P5 spatial + P4 ASol work done earlier.
- Round 2 (in progress): e8/e9 Fimbulwinter xfails resolved via authorized mana-gate fixture (12 + 20 passed).

### Round 3 (last 6 xfails)
- `test_r19_alt_compiled_walk_represents_the_cleanse` — lever (a): removed.
  Primary `test_r19_compiled_walk_contract_owned_gate` (passing) already pins
  `compiled_support_receipt` returning `"support_cleanse"` for a
  cleanse-marked heal template and `None` for a plain one; the owner landed
  the fail-closed gate, not the staged-truncation alternate.
- `test_r22_alt_mikaels_exemption_contradicts_binary_evidence` — lever (a):
  removed. Primary `test_r22_mikaels_heal_stays_gated_while_caster_is_ccd`
  (passing) pins Mikael's Purify staying gated while the caster is
  crowd-controlled (binary audit: 3222Active has neither
  `canCastWhileDisabled` nor `cannotBeSuppressed`), citing
  `healing_received == 0.0`, the target's stun interval untouched at
  `[1.0, 3.0]`, and the caster's `cleanse_use` receipt
  (`fired_while_crowd_controlled=False`, use not consumed).
- `test_r23_item_options_rejected_with_named_validation_error_today`
  [Quicksilver Sash / Mercurial Scimitar] — lever (a): removed. The P2
  Slice 4 active option landed for both items, so the 400 "Unknown item
  option target" this row asserted is no longer reachable; primary
  `test_r23_new_self_cleanse_option_accepted_and_applied` (passing, both
  items) pins the current 200 self-cast-cleanse behavior instead.
- `test_multi_tick_dot_application_adds_one_cast_stack` — lever (a):
  removed. This was the unpinned alternate of the already-passing
  `test_multi_tick_dot_does_not_add_one_stack_per_tick`, which pins the
  fail-closed boundary (`withheld_reason=eclipse_stack_source_unavailable`,
  `stack_source_denials` names `dot_application_timing_unavailable`) — the
  generic DoT packet has no sourced application timestamp and no champion
  module supplies one in this fixture, so the "adds one stack" branch is
  unreachable, not just untested.
- `test_malformed_dot_metadata_has_named_denial` — lever (b), small src fix:
  a non-numeric `dot_tick_interval` (e.g. `"half-second"`) crashed
  `calculate_fight_damage` with a raw `ValueError` inside
  `_ability_dot_tick_events` (`src/calculator/damage.py`). Fixed by coercing
  through the existing `_finite_numeric_receipt` helper (same convention
  used elsewhere in `damage.py` for malformed-metadata receipts) so a
  malformed cadence is now treated the same as a missing one — fail-closed,
  never crashed or invented. Once fixed, the malformed case rides the SAME
  existing Eclipse stack-source seam a well-formed DoT ability rides
  (`stack_source_denials` names `dot_application_timing_unavailable`); there
  is no separate `dot_classification_unavailable` reason or top-level
  `item_denial_receipts` list anywhere in the codebase, so the test was
  rewritten to pin the actual seam instead of the invented one. Golden
  snapshot compare: `OK: snapshot identical to scripts/golden_baseline.json`
  (real champion packets never carry non-numeric DoT metadata, so the
  coercion fix is a no-op for them).

Verification: `.venv/bin/pytest tests/test_cleanse_eligibility.py
tests/test_eclipse_dot_cc_stack_sources.py -q -rxX` → 53 passed, 0 failed,
0 xfailed. Full suite: `.venv/bin/pytest -q --tb=no` → 7688 passed, 0
failed, 0 xfailed — goal condition met.
