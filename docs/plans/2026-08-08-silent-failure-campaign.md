# Silent-Failure Campaign: effects as data, triggers on one bus, claims machine-checked

## Goal

A calculator where authoring an effect that nothing consumes — or claiming coverage
that nothing backs — is a **load-time error**, not a wrong number: item and champion
mechanics compile to typed, closed-vocabulary declarations interpreted by one engine,
and every coverage claim is verified against the code that backs it.

## The motivating incident (2026-08-08 session)

The plan's requirements are extracted from a real failure. Imperial Mandate's Command
(+7% damage taken after an immobilize) silently contributed **zero** for Syndra, and
every layer failed independently:

1. **Marker never authored** — `champions/syndra.py` treated all CC as "utility only";
   E carried no `cc_kind`, so no consumer could see the stun.
2. **Marker authored but dropped in transit** — `champions/pantheon.py` W *did* author
   `cc_kind="stun"`, but without `event_order_certified` the emission gate
   (`damage.py`, `_evaluate_cast_parts`) never exported it to the event ledger.
   Pantheon + Mandate priced zero, discovered only by adversarial review.
3. **Consumer half missing** — the walk's owner-skip
   (`survival/transitions.py`, `_apply_cross_participant_modifiers`) documented that
   "the holder's pair engine already prices its own stack/amp." That pair-engine side
   (`_apply_command_amp`) did not exist. The headline TDD reads the pair engine, so
   solo holders got nothing.
4. **Coverage claimed anyway** — `item_coverage.py` `_STATEFUL_MODELED_ITEMS` said in
   prose that Command "is represented by the shared participant support ledger."
   Nothing checked the prose against code.
5. **Predicate divergence** — "is this an immobilize?" existed as different literal
   sets in `_cc_triggers`, `_fimbulwinter_trigger_kind`, and the new engine scan; one
   of them let *slows* trigger Command (wiki: immobilize only).
6. **Tag → collateral reorder** — authoring the stun fed the rotation resolver's
   generic cc-setup fan-out (`rotation_resolver.py`), opening with a sphere-less
   (stun-less) E and silently costing a Q recast at the 5.0s window boundary in
   builds with no Mandate at all. The kit dependency (Q's sphere is E's setup) was
   not representable as data; it took a hand-authored `COMBO_TABLE` seed.

Already shipped as the incident fix (this plan generalizes them, not repeats them):
`cc_kind` on `damage_entry`/`simple_damage` with bundled single-hit certification,
`_validate_cc_event_contract` in `champions/engine.py`, `IMMOBILIZING_CC_KINDS` /
`CC_KIND_VOCABULARY` / `is_immobilizing_event` in `ability_spec.py`,
`_apply_command_amp` + walk `owner` handshake, and the Syndra rotation seed.

## Diagnosis being addressed

- **A. Claims, not checks**: coverage registries hold prose; drift is undetectable.
- **B. Silent-drop transit**: events are dicts flowing through per-site allowlist
  copiers; an uncarried field vanishes. The warning comment in
  `item_support_effects.py` ("a new branch that reads ``cc_events`` … must add its
  item here, or its stream will arrive empty") documents the trap instead of closing it.
- **C. Two engines, one fight**: pair engine (TDD/breakdown) and coupled walk
  (survival/cross-participant) each implement all-source mechanics, coordinated only
  by the `owner` convention (Bloodsong, Black Cleaver, now Command).
- **D. Bespoke amp paths**: Shadowflame, Expose Weakness, Hypershot, Command are four
  hand-rolled variants of trigger→window→pool→fraction sharing only
  `_amplifier_delta_events`.
- **E. Untyped events**: no type answers "what can an event carry, who reads it";
  navigation degenerates to grep.
- **F. Kit dependencies aren't data**: setup/consume knowledge (sphere before stun)
  lives in hand seeds, invisible to the atom layer.

## Standing invariants (ratified now, enforced progressively by phases)

- **Loud by default**: a trigger authored with no reachable consumer, or consumed
  from an empty producer set, fails at parse/import — never prices zero.
- **Closed vocabularies**: every tag value validated against one frozen set at load
  (`CC_KIND_VOCABULARY` is the template).
- **One predicate, one home**: each trigger classification has exactly one callable;
  literal re-typings of its set are defects.
- **Cross-engine pairing is checked**: any walk packet that owner-skips the holder
  must name its pair-engine counterpart, and the pairing is asserted by machine.
- **Golden discipline**: pure-refactor phases show zero golden diffs; semantic
  corrections re-capture with every diff explained (existing repo rule, restated
  because phases 2 and 4 lean on it as their primary safety net).

---

## Phase 1 — Machine-checked coverage claims

**Goal.** Every modeled-item claim in `item_coverage.py` names the code and tests
that back it, and an audit fails when the backing disappears.

**Decisions.**
- Claims become structured records — prose stays for the UI, but each entry gains
  `backed_by`: importable symbol paths (e.g. `item_effects.command_amp_effect`,
  the walk packet's source string) and the ids of behavioral tests pinning it.
  *Why: the incident's step 4 — prose survived a missing implementation.*
- Verification is a test in the suite, not a script gate — it runs on every `pytest`,
  resolving each symbol and asserting each named test exists in the collected set.
  *Why: patch-day scripts run rarely; the drift window must be one commit.*
- Dual-sided items (Command, Expose Weakness, Carve) must name **both** sides
  (pair-engine pricer + walk packet) or the audit fails.
  *Why: the incident shipped with exactly one side present.*

**Shape.**
- `item_coverage.py` — claim records grow the `backed_by` field (owner unchanged).
- `tests/test_coverage_claims.py` — `test_every_stateful_claim_resolves_its_backing()`;
  `test_dual_sided_items_name_both_engines()`.

**Success criteria.**
- Renaming `command_amp_effect`, deleting `_apply_command_amp`, or removing the
  "Imperial Mandate — Command" packet source fails `tests/test_coverage_claims.py` —
  demonstrated once by mutation during development, before the pin lands.
- Every `_STATEFUL_MODELED_ITEMS` and `_PARTIAL_BLOCKED_REASONS` entry carries
  non-empty backing; an entry with unresolvable backing fails collection-time, not
  patch day.
- Zero golden diffs (metadata-only phase).

## Phase 2 — One trigger bus

**Goal.** A single typed trigger stream owns "what did this fight's events trigger";
every CC/damage/takedown-triggered consumer (both engines) reads it, and
producer/consumer registration is validated at import.

**Decisions.**
- New leaf module `trigger_stream.py` (imports `ability_spec`, imported by
  `damage.py` and `item_support_effects.py`) owning a frozen `Trigger` record
  (kind, class, time, target, source_key, event_id) and the one extraction function
  over authored events. *Why: issues B and 5 — three scanners with diverging sets.*
- `_cc_triggers`, the immobilize scan inside `_apply_command_amp`, and
  `_damage_triggers`/`_takedown_triggers` are replaced by bus reads; the literal
  kind-set in `_fimbulwinter_trigger_kind` collapses onto the shared predicate.
  Removal enforced by a source-assertion test (the `test_issue_158` precedent).
- The holder registries (`CC_TRIGGER_ITEMS`, `DAMAGE_TRIGGER_ITEMS`,
  `EVENT_SCAN_SUPPORT_ITEMS`) become declarations checked against the consumer
  branches at import — the "must add its item here" comment becomes a raised error.
  *Why: issue B's documented trap.*
- The `owner` handshake becomes a registry: walk packets that skip the holder declare
  their pair-engine counterpart; Phase 1's dual-side audit reads this registry
  instead of hand-listed names. *Why: invariant "cross-engine pairing is checked".*
- Event dicts are not retyped in this phase — the bus is the typed seam; full event
  typing is deferred to Phase 4. *Why: keeps this phase a pure refactor.*

**Shape.**
- `src/calculator/trigger_stream.py` — `Trigger`; `authored_triggers(result) -> tuple[Trigger, ...]`;
  `CONSUMERS: Mapping[str, frozenset[str]]` (item → trigger kinds);
  `validate_registrations()` (called at import by both consumers).
- `item_support_effects.py`, `damage.py` — scanners deleted, bus consumed.

**Success criteria.**
- Zero golden diffs and zero changes to `tests/test_item_support_effects.py` /
  `tests/test_syndra.py` expectations — pure refactor, behavior pinned by the
  existing suites.
- Exactly one source location parses `cc_kind` off raw event rows — enforced by a
  source-assertion test, not convention.
- Adding a consumer branch without registering its item (the Fimbulwinter-comment
  trap) raises at import; covered by a negative test.
- A trigger kind outside `CC_KIND_VOCABULARY` cannot enter the stream (negative test).

## Phase 3 — Item effects as declarative atoms

**Goal.** Item behavior (not just numbers) is declared: each effect is an atom of a
closed archetype set (window-amp, on-hit, spellblade, burn, shred-stack, threshold
shield, …) interpreted by one engine rule per archetype; a new same-archetype item is
a declaration plus tests, with no engine edits.

**Decisions ruled now** (the rest belongs to this phase's own plan, written when
picked up):
- Archetype inventory is derived from the existing `ITEM_EFFECTS` /
  `ALLY_ITEM_EFFECTS` consumers first, not designed a priori — the incident's lesson
  is that behavior already exists in ~30 shapes; the atoms must fit them, then the
  bespoke paths (issue D: Shadowflame/Expose Weakness/Hypershot/Command) migrate onto
  the shared window-amp interpreter one at a time, each behind the golden gate.
- An atom with no interpreter fails closed as "not modeled" *automatically* —
  computed coverage replaces the Phase 1 hand-listed backing for migrated items.
- Migration is strangler-style: unmigrated items keep their current paths; the
  coverage audit reports the migration frontier.

**Success criteria (contract level).**
- The four bespoke amp functions are one interpreter + four declarations; golden
  diffs are zero for the three pure migrations and explained for any correction.
- A test adds a synthetic window-amp item by declaration only and observes correct
  pricing in *both* engines — the "Imperial Mandate in one hop" property.
- Deleting an interpreter flips its items to withheld/not-modeled (never zero) —
  negative test.

## Phase 4 — Engine merge

**Goal.** One simulation; TDD, survival, and BIS score are views over the same event
timeline (typed events), ending the double-implementation tax and the `owner`
handshake entirely.

**Decisions ruled now**: the walk's existing bit-equivalence discipline
(`tests/test_participant_timeline.py`, fast-vs-legacy) is the migration harness — the
pair engine's outputs are reproduced as a view before any deletion; typed event
objects land here (issue E), not earlier. Everything else — staging, cache strategy,
score-only path — gets its own plan; this campaign only binds the end state.

**Success criteria (contract level).**
- One code path prices a given mechanic; `trigger_stream` pairing registry becomes
  empty and is deleted.
- Golden and optimizer-equivalence suites pass with zero unexplained diffs;
  `scripts/bench_coupled_optimizer.py` shows no evaluation-count regression beyond a
  bound measured before the merge and pinned with margin.

## Phase 5 — Champion atoms (long tail)

**Goal.** Champion modules are compilers to the same atom vocabulary; kit
dependencies (issue F: sphere-before-stun) are declared atoms the rotation resolver
consumes, retiring hand seeds whose knowledge the data can carry.

**Decisions ruled now**: modules remain the reviewed, fail-closed authority (repo
rule 7 unchanged); `COMBO_TABLE` seeds are only retired champion-by-champion when a
declared dependency reproduces the seed's order — asserted, then the seed deleted.

**Success criteria (contract level).**
- Syndra's Q→E dependency exists as a declaration; the resolver derives
  `Q, Q2, E, W, R` without her seed; the f2/f3 suites pin it.
- `_validate_cc_event_contract`'s guarantee holds for every atom kind: no authored
  atom can fail to reach its interpreter silently — negative test per kind.

---

## Sequencing and effort

1 → 2 are independent of the atom design and directly kill the incident's failure
class; each is roughly a session. 3 is the campaign's core and proceeds
item-archetype by item-archetype behind the golden gate. 4 is the expensive one and
must not start before 2 (the bus is its seam) and 3 (fewer bespoke paths to merge).
5 rides on 3's vocabulary. Phases 3–5 each get their own plan document when picked
up; this document binds their end states so those plans inherit contracts, not vibes.
