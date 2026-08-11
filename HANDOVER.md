# Combat behaviour atomization handover

Status: active — resumed 2026-08-09. Wave 1 (Briar E, CP20 items, self-healing,
champion mechanics) integrated and green: 5074 tests pass, Black clean, atomizer
regenerates, golden diff fully categorized (baseline NOT recaptured — see §6).

Repository: `/Users/river/Projects/league-combat-calculator`

Goal thread: `019fe452-4686-7ec0-8174-0070395948ba`

This file records the full scope, the completed work, the current dirty-worktree boundary, and the remaining work.

## 1. User goal

Continue cleaning all unmodeled combat behaviour with proper atomization.

The requested behavior includes:

- Champions, items, runes, and their interactions use typed numerical atoms.
- Crowd control counts as time in which the affected participant cannot act.
- Zhonya's Hourglass counts as stasis time in which the participant cannot act.
- Guardian Angel counts death and revive time in the survival timeline.
- Every support shield or heal has an explicit recipient choice for each packet.
- Braum E models its limited active window and selected blocked skillshots.
- Yasuo W models its limited active window and selected blocked skillshots.
- The same interaction model must support other projectile defenses and limited windows.
- Public results must expose source receipts and the selected interaction inputs.

The broader task is to keep closing every named unmodeled behavior in the repository. A fail-closed result must name the missing behavior. It must not invent a number.

## 2. Repository and collaboration rules

These rules come from the project instructions and remain active during resume.

- Preserve the shared dirty worktree. Inspect ownership before editing a file.
- Edit only files required for the active slice.
- Keep `vendor/lolstaticdata/` unchanged except for a targeted parser fix that blocks the requested behavior.
- `data_fetcher.py` reads the tracked cache. It does not fetch or write network data.
- `data_updater.py` writes the tracked cache through `data_registry.write_runtime_cache`.
- Research downloads use named evidence roots and explicit CLI paths.
- Named champion modules under `src/calculator/champions/` are the production runtime path.
- The generic parser is for explicit synthetic or development fixtures.
- Every calculation function needs a corresponding test.
- Item numbers come from typed accessors in `item_effects.py`.
- Missing item keys raise with the item and key.
- Ability and interaction numbers come from validated atoms with source, evidence, and hash receipts.
- Run the project gates before treating a calculation change as complete.
- Do not recapture the golden baseline until every authored behavior difference has an explanation.

The repository is public. GitHub Actions have unlimited capacity. Auto-merge is enabled by the user as repository state. The setting is outside this task's jurisdiction and must remain unchanged. This handover contains no authorization to stage, commit, push, merge, or create a pull request.

## 3. Architecture used by this task

### Atom catalog

- `src/calculator/atomizer.py` owns the common atom contract, deduplication, hashes, atomic writes, and manifests.
- `src/calculator/atomizer_domains.py` atomizes abilities, items, runes, stats, champions, and economics.
- `src/calculator/ability_atoms.py` selects one exact ability atom and validates its hash and payload.
- `src/calculator/champions/slotlib.py` owns shared ability extraction helpers and prose timing extraction.
- `scripts/atomize.py` regenerates the catalogs.
- `data/atoms/` contains generated catalogs and manifests.

Every numeric atom needs:

- a stable `atom_id`;
- a behavior category;
- the exact source path;
- values and units;
- an evidence receipt;
- a content hash.

The atomizer deduplicates by `(atom_id, behavior)`. Separate values that need separate runtime meaning require separate atom IDs or a typed sequence atom.

### Combat and survival kernel

- `src/calculator/ability_spec.py` defines `DamagePart` and `ControlEvent`.
- `src/calculator/champions/engine.py` validates module entry fields and stamps cached projectile and area markers.
- `src/calculator/damage.py` prices typed damage, builds ordered events, and carries event metadata.
- `src/calculator/participant_timeline.py` pairs participants, resolves support recipients, serializes public events, and runs the coupled survival walk.
- `src/calculator/survival/actions.py` converts event dictionaries into typed `SurvivalAction` values.
- `src/calculator/survival/transitions.py` applies shields, heals, stasis, revives, crowd control, projectile defenses, and damage modifiers.
- `src/calculator/survival/receipt_state.py` stores public survival receipts.
- `src/calculator/survival/compile.py` builds the score adapter and fails closed when a support transition cannot be represented safely.

### Support and target selection

- `src/calculator/support_effects.py` derives champion shield and heal packets.
- `src/calculator/item_support_effects.py` derives item support packets.
- `participant_timeline.py` resolves `target_scope`, `target_selection_key`, and explicit teammate indexes.
- `static/js/app.js` renders string-list options and support target controls.

The target selection contract supports self, one teammate, all teammates, self plus one teammate, self plus all teammates, explicit selected ally, most wounded ally, and related typed policies. An unsupported scope raises at the emitter.

## 4. Completed work in this goal

### 4.1 Action downtime and state timing

The survival state now carries:

- `crowd_control_intervals`;
- `action_downtime_intervals`;
- `crowd_control_until`;
- `stasis_until`;
- `invulnerable_until`;
- `untargetable_until`;
- death intervals;
- revive state and revive time.

Action-blocking control uses `ACTION_BLOCKING_CC_KINDS` in `ability_spec.py`. The walk merges overlapping intervals and reports action downtime. Slow remains a movement effect unless the source also supplies an action-blocking control event.

The control event path supports damage-attached control and control-only packets. The source control atoms are carried into event receipts.

### 4.2 Zhonya and Guardian Angel

Zhonya's Hourglass uses an explicit `stasis_active_seconds` input. The selected stasis interval blocks actions and incoming damage through the survival walk.

Guardian Angel uses the typed revive path. Death is recorded as a downtime interval. The revive packet restores the sourced health amount and resumes the participant state after the revive time.

The current work also carries Guardian's Horn flat champion-damage and damage-over-time reductions through the typed item, scenario, timeline, and survival paths.

### 4.3 Projectile and attack defenses

`src/calculator/interaction_effects.py` contains the typed `ProjectileDefense` contract.

Implemented defense sources include:

- Braum E, Unbreakable;
- Yasuo W, Wind Wall;
- Samira W, Blade Whirl;
- Gwen W, Hallowed Mist;
- Fiora W, Riposte;
- Pantheon E, Aegis Assault;
- Jax E, Counter Strike.

Each selected window carries a source duration atom. The request can select the active start, active duration, and blocked source slots. Braum blocks the first selected skillshot and reduces later selected hits. Yasuo, Samira, and Gwen destroy selected marked projectiles. Fiora and Pantheon use full-block behavior for their selected incoming packets.

Jax E now has these typed rules:

- basic attacks match `blocks_basic_attacks`;
- cached `spellEffects` values mark area abilities with `area_damage`;
- marked area abilities receive a 25% reduction during the selected E window;
- area abilities bypass Jax's full basic-attack block and use the area reduction;
- public events carry the area marker and the projectile-defense receipt.

The focused test is `tests/test_interaction_atoms.py::test_jax_e_reduces_marked_area_ability_damage_during_the_sourced_window`.

### 4.4 Support shields and heals

Support effects now carry a per-packet target selection key. The public and roster UI exposes the choice.

Current source-specific support handling includes:

- Morgana E magic shield, duration, and crowd-control immunity while the shield remains;
- Taric W shield formula based on the protected target's maximum health;
- Seraphine W delayed missing-health heal with an existing-shield gate;
- target-scope overrides for Ekko W, K'Sante E, Kassadin Q, Lee Sin W, Lux W, Rakan Q, Rumble W, and Yuumi E;
- typed self and ally copies for module-authored support and healing rules;
- support target controls in the main and roster UI.

The support ledger applies shield pools, shield expiry, received healing, healing reduction, and source receipts in the shared transition kernel.

### 4.5 Typed timing and control atom work

The ability atom system now supports typed source reads for:

- shield duration;
- active defense duration;
- crowd-control duration;
- control-only events;
- source control receipts attached to damage parts;
- formula atoms for target maximum health and target missing health;
- Amumu's capped physical damage reduction.

The following champion packets were moved through typed control duration reads:

- Amumu Q and R;
- Jax E;
- Taric E;
- Varus R;
- Vayne E;
- Brand Q;
- Malphite R;
- Vel'Koz E;
- Cassiopeia R facing-selected stun or slow;
- Xayah E root after the selected feather count.

### 4.6 Amumu E physical damage reduction

Amumu E, Tantrum, now resolves:

- flat reduction;
- bonus-armor scaling;
- bonus-magic-resistance scaling;
- the 50% per-instance cap from the cached description.

The reduction is applied to each physical raw damage instance before armor mitigation. The survival receipt exposes all four source atoms.

### 4.7 Event metadata fixes

The ordered damage event path now keeps:

- skillshot markers from cached projectile classification;
- area-ability markers from cached `spellEffects` classification;
- basic-attack markers;
- control metadata;
- control source atoms;
- damage-over-time markers;
- public interaction receipts.

The rotation resolver cache key was repaired so a cached order does not reuse a result for a different request.

### 4.8 Fixture and regression updates

Some existing expected values changed because the authored control behavior now consumes action time. Updated fixtures include:

- Camille shield isolation;
- Taric Q isolation;
- Cassiopeia and Varus rotation exceptions;
- Vayne rotation order;
- Morgana source hash;
- Sterak's practice-corpus death time and modeled crowd-control note.

These are intentional behavior changes. Review them before any golden baseline decision.

### 4.9 Wave 1 (2026-08-09): Briar E damage-reduction window

Briar E, Chilling Scream, now models its sourced timed self damage-reduction
window and terrain-collision control (HANDOVER §7 Step 2 completed):

- `self_state_events` on the E entry: `kind="damage_modifier"`, `multiplier =
  1 - 35/100` read from the `ability.damage_reduction` atom, `duration =
  min(e_charge_seconds, sourced 1s)` from the `timing.active_duration` atom,
  `all_sources=True`, `_priority=-1.0` (pre-damage priority: a modifier armed
  at the same timestamp as an incoming hit applies before that hit), and the
  reduction/duration atom dicts in `source_atoms`.
- Terrain collision (option `e_wall_collision`): `control_events` knockup 0.5s
  then stun 1.5s from the `timing.control_duration_sequence` atom, with the
  sequence atom on the control receipt.
- `_SELF_STATE_EVENT_KINDS` in `support_effects.py` gained `damage_modifier`;
  `derive_self_state_effects` carries `multiplier`/`amount`/armor&mr reduction
  percent/`_priority` (validated finite, fail closed), the boolean flags
  `all_sources`/`damage_reduction`/`persistent`/`next_event_only`,
  `owner`/`source_participant`/`resistance_type`, and `source_atoms`.
- `survival/compile.py::add_support_templates` compiles `damage_modifier`
  templates into `ActionKind.DAMAGE_MODIFIER` at phase -1.0 carrying every
  typed field; `unrepresentable_template_receipt` fails closed with named
  receipts (`support_duration=0`, `support_damage_modifier_multiplier=nonfinite`,
  `support_damage_modifier_amount=nonfinite`, `support_kind=...`). The score
  walk and receipt walk use the same `run_survival_walk` kernel, so score and
  receipt agree (pinned by tests).
- Public serialization: `participant_timeline.py` support-events serializer
  now emits `source_atoms` (list of atom dicts); `_utility_outcome_receipt`
  counts multiplier windows (`damage_reduction.multiplier_windows` with
  source/multiplier/duration/expires_at) from the unfiltered stream so
  amount=0 multiplier modifiers are no longer invisible.
- New option `e_charge_seconds` (float, default 1.0, max 1.0 = sourced cap,
  rotation `{"role": "self_state", "slot": "E"}`); ASSUMPTIONS updated.
- Tests: `tests/test_briar_e.py` (20 cases) — atom resolution, 35% reduction
  on physical/magic/true in-window, no reduction after expiry, charge cap,
  wall-collision control receipts + 2.0s action downtime, same-timestamp
  pre-damage priority, score/receipt parity, fail-closed compiler receipts.

### 4.10 Wave 1 (2026-08-09): CP20 six-item gaps closed

Cull, Phage, Runic Compass, Tear of the Goddess, Umbral Glaive, World Atlas are
end-to-end (`docs/cp20-remaining-item-gaps.json` status = implemented):

- Cull: Reap on-hit heal 3/auto, 100-minion progression (1 gold/minion),
  350-gold completion payout — economy packet emits 450 at 100 kills.
- Phage: Rage melee 20% / ranged 10% movement speed, 2s, per-authored-auto
  timed movement packets (receipt-only, never converted to damage).
- Runic Compass / World Atlas: Support Quest (800/400 gold), Shared Riches
  interval (20s) with per-minion-type gold, Ward active (3 charges) — quest
  packets enriched with `quest_complete`/`ward_charges`.
- Tear: Manaflow 8s charge interval + new `manaflow_max_charges` 4.0, 3/6
  bonus-mana triggers, 360 cap, minion-only Helping Hand — ordered
  kind="resource" packets (new utility dimension) per authored cast,
  receipt-only, never fed to ability admission.
- Umbral Glaive: Blackout 8s vision receipt (ward_only, unseen gate 1s,
  trigger window 4s) + first-auto 50 + 1.5×lethality true damage typed and
  gated on `nightstalker_ready`; ward-only siblings are vision receipts.
- Coverage: all six classified `modeled_state`, optimizer-eligible; frontend
  receipts added (economy chip, resource chip, Blackout, ward details).
- Tests: `tests/test_cp20_items.py` (28 cases).

### 4.11 Wave 1 (2026-08-09): champion self-healing

`src/calculator/healing.py` gained two new sourced rules and the full
25-champion audit table is recorded in the subagent report (kept in the goal
thread); implemented rules (existing + new):

- NEW Sett P (Pit Grit): always-on 0.5s regen stream, 20 ticks/10s, amount =
  min(19, floor(missing%/5)) × sourced base row (0.075…1.05 by level).
- NEW Maokai P (Sap Magic): P cooldown 30→20s reduced 4s per cast trigger,
  heal = sourced 4%…12.8% max health on the first auto after ready, gated
  live at ≤95% max health.
- Verified/locked existing rules: Alistar P, Ekko R, Fiora P, Garen P, Illaoi
  P, Kayle W, Kindred R/W, Sylas W, Trundle R, Udyr W, Swain R, Tahm Kench Q,
  Volibear W, Xin Zhao W, Mordekaiser W (E8a grey), Gwen P, Camille W,
  Cho'Gath P, Pyke P, Rek'Sai P.
- Documented fail-closed boundaries (named in module ASSUMPTIONS): Bard W
  shrine heal, Cho'Gath P kill heal, Pyke P out-of-vision consume, Rek'Sai P
  burrow heal (no stance trigger), Zoe W heal mimic (no sourced atom), Morde R
  (needs defender stats in self-heal ledger), Ekko R health-lost rider (uses
  sourced minimum floor).
- Tests: `tests/test_self_healing_champions.py` (8 cases).

### 4.12 Wave 1 (2026-08-09): champion mechanics packets

11 packets implemented across the 27-champion audit (full table in the
subagent report); every new OPTIONS entry carries an inline rotation
declaration and all defaults reproduce previous numbers EXCEPT Nasus:

- Varus Q charge (`q_charge_fraction`, min/max row interpolation),
- Vladimir E charge (`e_charge_fraction`, per-modifier min/max interpolation;
  E now reads the live cached cooldown array 13/11/9/7/5 instead of the
  reviewed packet's fixed 13.0 — see §6 golden note),
- Darius R execute recast (`r_execute_recast`, default off),
- Nasus Q cooldown halving during R (`r_q_cooldown_halved`, default True when
  R ranked — the only default-on numeric change; see §6),
- Aurelion Sol Q secondary beam, Aurora Q subsequent bolts, Caitlyn Q 60%
  secondary, Orianna Q 70% secondary, Gnar Q Mini 50% return-pass
  (`q_secondary_targets` / `q_marked_enemies`),
- Xayah Clean Cuts secondary feathers (`clean_cuts_secondary_targets`),
- Aphelios Moonlight Vigil follow-ups (`r_followup_targets`),
- Senna W root control (sourced Root Duration via `with_control`); the Relic
  Cannon 20% AD rider stays document-only (engine on-hit contract = one
  per-auto payload per entry; documented in senna.py ASSUMPTIONS).
- Tests: `tests/test_mechanics_packets.py` (34 cases).

### 4.13 Wave 2 (2026-08-09): ally support coverage

11-champion audit (Sona, Nami, Yuumi, Seraphine, Taric, Rakan, Karma, Milio,
Renata, Janna, Ivern) with 4 implemented packet types:

- Nami W return-bounce heal (new packet `heal:W:<cast>:bounce`): amount =
  max(sourced Minimum Heal row, Heal row × (0.60 + 0.30×AP/100)); the
  sourced Minimum row is exactly 60% of the Heal row at every rank; atoms:
  Heal + Minimum Heal with hashes.
- Yuumi R Best Friend bonus heal (`heal:R:<cast>:best_friend`): Total Heal ×
  clamped per-level 30…60% read; endpoints 210 at 18 / 105 at 1.
- Yuumi R overheal→shield conversion (2 packets): live excess formula
  max(0, heal − missing health), general pool, expiry at cast + 5.0s
  (1.5s shield-duration atom + 3.5s channel atom); documented artifact: the
  heal actions still book the same excess as overhealing (kernel carve-out
  applies only to heal-compiled events).
- Renata E Loyalty Program scope fix: `_SCOPE_OVERRIDES` one_teammate →
  all_teammates so every selected teammate gets the sourced Shield Strength;
  the module-authored self shield stays a single self grant.

Verified already-covered (checklist passes, no re-implementation): Sona W
heal + Melody shield, Yuumi E anchor shield, Seraphine W shield + gated
pulse, Taric W max-health shield + R invulnerability + Q fan-out, Rakan
Q/E/P, Karma E, Milio W/E/R, Janna E shield + R fan-out, Ivern E.

Documented-only (named reasons in module ASSUMPTIONS): Renata W Bailout
revive+burn (needs a mid-fight conditional revive survival/ kind — the only
real support gap in the 11), Yuumi P anchor heal + W heal/shield-power amp,
Karma R+E Defiance (no sourced numbers — fails closed), Janna E bonus AD
rider, Milio W ally tick cadence, Sona most-wounded = explicit roster
selection.

Golden impact: ZERO (1v1 harness has no selected teammates; every new packet
resolves to no_selected_teammate and drops cleanly). Files: support_effects.py,
participant_timeline.py (support sections), nami.py, yuumi.py, renata_glasc.py,
sona.py, seraphine.py, taric.py, rakan.py, karma.py, milio.py, janna.py, ivern.py
(ASSUMPTIONS), tests/test_ally_support_wave2.py (10). Focused: 226 passed;
broader sweep 817 passed.

### 4.14 Wave 2 (2026-08-09): keystone/rune audit

Unsealed Spellbook decision: KEEP THE EXPLICIT REJECTION (do not model). The
cached template has no numeric payload (unresolved {{#var:}} placeholders),
its effect is a summoner-spell selection state with no model anywhere in src/,
and honest modeling is cross-cutting (participant_timeline/damage/pipeline/
UI/data_updater/rune_parser/atomizer_domains — every file outside the owner's
scope). It stays greyed-out and /api/calculate + /api/optimize reject it with
a named 400 reason.

Audit findings (keystone -> action): keystone_options parity pinned by tests
(Fleet/Conqueror exposed AND consumed); engine-hardcoded starting stacks
(Dark Harvest/Electrocute/PTA/Lethal Tempo/Grasp) report-only (adding an
option rune_effects could not consume would break parity — needs damage.py
ownership); Dark Harvest 1.75s soul-reap delay documented (engine lands
damage at trigger+1.75); Electrocute cooldown-clock start documented;
Conqueror cast_instance_interval_seconds compiled but never read by the
engine (over-stack risk) report-only; Comet/Aery/First Strike timing
assumptions disclosed; Guardian/Aery target selection OK; roster multi-target
keystone procs price primary target only (report-only); no compiled keystone
consumes action time; score/receipt parity structural for the 11 damage-class
keystones, the 5 utility keystones fail the compiled score path with named
receipts and /api/optimize falls back to the receipt walk (verified live,
pinned by TestOptimizeFallbackParity).

Self-contained fail-closed fixes in rune_effects.py: First Strike
melee_ranged_ratios now read via _required_pair (named KeyError); _required_leveling
now rejects non-list/non-numeric tables with named KeyErrors; Unsealed
Spellbook rejection names the reason.

Parser false positives (report-only, data quality): Lethal Tempo + Conqueror
record deathfire_tick_interval_seconds from the generic "every N seconds"
regex; Arcane Comet records deathfire ratios + Aftershock's shockwave_radius.
All atomized into data/atoms/runes.json as if sourced; NO compiler reads them;
documented in ASSUMPTIONS for the next owner (fix = scope regexes to
Deathfire's template only). Hail of Blades 2-vs-3 buffed attacks data
discrepancy noted (engine follows the cache faithfully).

Minor runes: zero presence in src/; the high-leverage ones (Revitalize, Bone
Plating, Second Wind, Font of Life, Overheal, Coup/Cut Down/Giant Slayer,
Sudden Impact, Presence of Mind/Manaflow Band) need data_updater + parser +
atomizer extensions first — roadmap P1/P3 consumers.

Files: src/calculator/rune_effects.py, tests/test_keystone_audit.py (40).
Focused: 196 passed. Golden impact: NONE (error-message text only).

### 4.15 Pass-16 correction (2026-08-09): Veigar R execute curve

The prior handover's pass-16 decision required boost = min(1, missing_ratio /
(2/3)) — 1.5% per 1% missing health, capped at 66.66% missing (target at 33%
health) — but the code (commit c76352d, E5-1) shipped the mirrored curve
((missing − 2/3)/(1/3), full boost only at 0 health). Verified against the
cached wiki wording ("increased by 0% : 100% (based on target's missing
health)"), the live tooltip ("1.5% per 1% of target's missing health; capped
at 66.66% missing health"), and the game binary (MaxExecuteMult = 2.0).

Applied (veigar.py): `_EXECUTE_MISSING_RATIO_CAP = 2/3`, boost =
min(1, missing/(2/3)); module docstring, ASSUMPTIONS, and detail updated with
the tooltip evidence. Tests: test_p2_math_foundations ramp test now asserts
1x @0, 1.5x @1/3, 2x @2/3, 2x @1; the Jensen test flipped from convex
(E[d]≥d(E[M])) to concave (E[d]≤d(E[M]), deterministic path OVERstates);
test_e5_fix_1 uses the deterministic no-enemy 1000-HP/MR-100 numbers
(272.5/1000 missing → raw 325×1.40875; 300-HP target → capped 650 row);
data/practice-corpus scenarios.json e9-e5-veigar pin updated to 399.1/262.6
with the formula note (coordinator-authored, matches the corrected engine);
docs/math-foundations.md rewritten for the concave ramp.

Golden delta: +34 Veigar registered-fight lines (R boosted by the live
missing health at cast in every fight; Shadowflame scales with the boosted
R in magic builds) + 1 Veigar R-detail wording line. All explained.

### 4.16 Pass-18 correction (2026-08-09): BoRK first-auto HP-walk ordering

The pass-18 isolated patch fixes first-auto packet ordering in the BoRK
current-health walk: `_layer_on_hit_effects` now prices first-auto packets
(Statikk Shiv, Umbral Glaive, Voltaic family) as HP-only inputs via
`_first_auto_damage_by_auto_for_health_walk` (Galvanize ability-consumed
charges skipped; Statikk chain-target allocation respected; Umbral gated by
`first_auto_state_ready`), passed into `_simulate_current_health_on_hit` so
later current-health procs see the drained HP. The damage rows/totals remain
owned by `_add_single_proc_on_hits` (no double count). Corrected result
(coordinator-verified): BoRK 337.607, fight total 710.941 (the pass
markdown's 328.26 table double-subtracted Statikk after auto 0).

Applied manually to src/calculator/damage.py (the coordinator's patch file
contained the pre-existing dirty-tree hunks too; only the 4 BoRK hunks were
missing from the shared tree). New tests in tests/test_item_damage.py
(TestBorkFirstAutoCurrentHealthOrdering: BoRK events
[80, 72.53, 66.97, 61.62, 56.49], Statikk 40.0, total = autos + BoRK + Shiv).
Golden impact: ZERO (no first-auto+BoRK combo in the golden harness).

### 4.17 P1 (2026-08-09): Trigger and State Lifecycle kernel

ONE shared kernel, six consumers recomposed (RLM-1 owner p1-state-lifecycle;
two RLM-2 read-only audits integrated: p1-provenance-items, p1-matrix-champions).

Kernel — `src/calculator/state_lifecycle.py` (~1515 lines, dependency-light
leaf; stdlib + ability_spec only): typed declarations with source receipts —
SourceReceipt, TriggerPredicate, CcTriggerRule (Fimbulwinter immobilize/slow
classification), StackRule + TimedStackState (max/gain/per-kind gains/duration/
refresh/expiry/cap/combat-extension/payload/consume-at-cap/reset/seed),
WindowGateRule + WindowStackGate (Eclipse two-hit window + per-target
cooldown), CooldownRule + CooldownState (global + per-target), ChargePoolRule,
LockoutRule, InstanceCadence. Deterministic total order (time, tier,
sequence, insertion): expire -2.0 < ready/lockout-end -1.0 < gain/refresh/
extend/replace/denied 0.0 < consume/reset 0.5 < cooldown/lockout-start 1.0;
expiry wins at an exact boundary. Public receipts: StateTimeline.public_receipt()
surfaced on breakdown rows (Eclipse proc_Eclipse.state_transitions, Conqueror
keystone_Conqueror.state_transitions, Fimbulwinter trigger_rule + cooldown,
Ashe/Rengar OPTIONS state receipts, FoN declaration receipt).

Consumers (before -> after):
1. Eclipse — damage.py pair-loop gate replaced by kernel WindowStackGate.feed()
   (item_effects.eclipse_trigger_gate); zero numeric change.
2. Fimbulwinter — item_support_effects seen_casts/cooldown set replaced by
   kernel CcTriggerRule + CooldownState(8s) + InstanceCadence; shapes preserved.
3. Conqueror — rune_effects adds conqueror_stack_state(); damage.py hand-rolled
   expiry/cap loop replaced by TimedStackState.apply_gain; THE AUDIT FIX IS
   LIVE: cast_instance_interval_seconds (4s) is now READ (repeat same-ability
   casts within 4s denied); basic attacks ungated; 5s expiry preserved.
4. Force of Nature — item_effects force_of_nature_steadfast_rule();
   defensive_effects reads the six ChampionDefenses fields from the single
   kernel declaration.
5. Ashe — ashe.py ASHE_FOCUS_STACK_RULE (cap 4, 4s, refresh-on-attack, 1/s
   step-down drain from window end, capped gains do NOT refresh; wiki rev
   4015971); Q gates on the typed state seeded from q_focus_stacks.
6. Rengar — rengar.py RENGAR_FEROCITY_STACK_RULE (cap 4, per-stack 1s,
   refresh none, 10s combat extension, consume-at-cap empowered; P-template
   rev 2864152); Q/W/E empowered reads the typed state.

Files: NEW state_lifecycle.py + tests/test_state_lifecycle.py (47) +
tests/test_state_lifecycle_consumers.py (25); edited item_effects.py,
item_support_effects.py, rune_effects.py, ashe.py, rengar.py; surgical
damage.py (~150 lines: Eclipse gate + Conqueror walk) + defensive_effects.py
(~20 lines: FoN reads the kernel rule). Also fixed the pre-existing pylint
E0602 (typing.Iterable unimported in serpents_fang_venom).

Documented-only remnants (named reasons): FoN timed stack MACHINE stays in
survival/transitions.py (survival owner's file); Eclipse/Fimbulwinter
compiled score path still fails closed via COMPILED_WALK_UNREPRESENTABLE_ITEMS
(survival owner's domain) — the kernel owns the CC predicate/stack timing on
the receipt side; Ashe/Rengar per-attack/cast live gains not wired (the
rotation resolver does not feed per-swing events into champion-module
parses — state is typed and seeded from the explicit option); Rengar 1s
duration is 2019-template prose (verify on patch updates); Conqueror
melee/ranged 2/1 stack split not extracted by rune_parser (flattened 2,
pre-existing); adaptive-force→bonus-AD 0.6 conversion report-only;
Fimbulwinter 20% mana threshold has no atom; 1200-unit radius atom
unconsumed (pre-existing).

Score-vs-receipt parity pinned: Eclipse kernel proc times == damage_events
times; Conqueror grants/denials == stack_events and state_transitions;
keystone_state_events aggregation preserved; Fimbulwinter packet shapes
preserved. Golden: ZERO new diffs (845 unchanged; ports are numeric no-ops).

### 4.18 P2 Slice 1 (2026-08-09): Delivery and Interaction Eligibility — Braum E + Yasuo W

One shared kernel, two regression consumers (RLM-1 owner p2-delivery-eligibility;
three RLM-2 read-only audits integrated: p2-provenance, p2-runtime-trace,
p2-test-matrix [C wrote tests/test_delivery_interaction_eligibility.py — 40 tests]).

Kernel — `src/calculator/delivery_eligibility.py` (~600 lines, dependency-light
leaf; stdlib + state_lifecycle.SourceReceipt). THREE orthogonal contracts:
- DELIVERY TYPE: six typed DeliveryDeclaration rows (projectile, hitscan,
  area, targeted, basic_attack, damage_over_time) with source receipts;
  classify_delivery(action) is a deterministic pure function of the action's
  typed markers; required_delivery_class raises UnknownDeliveryError; the
  decision path fails closed with the named reason "unknown_delivery".
- DEFENSE ELIGIBILITY: DefenseEligibility (DefenseWindow start-inclusive/
  end-exclusive; SourceSelection = blocked_sources casefold slot matching
  UNION blocked_event_ids exact _event_id match; DeliveryAcceptance
  reproducing defense_matches' gates exactly + accepts_unknown); decide()
  -> EligibilityDecision with named reasons (outside_window /
  source_not_selected / delivery_not_accepted / unknown_delivery);
  stable_event_key = "source_key:time:sequence" (the walk identity, now
  kernel-owned).
- MITIGATION/COMPOSITION: UseBudget (None/first/each), FullBlockRule
  (none/first/all; blocks_true_damage), DestructionRule, ReductionRule
  (reduction_for uses an area reduction ONLY when the defense declares one),
  DefenseComposition.

Consumers: interaction_effects.resolve_projectile_defense KEPT (sourced
window/selection/atoms) + now reads e/w_blocked_event_ids; defense_matches
DELEGATES to the kernel; survival receipt_state/transitions consume kernel
decisions (same gate order, first-use consumption points preserved;
uses_remaining; event-id matches; unmatched-id fail-closed receipt);
SurvivalAction gains damage_over_time; braum.py/yasuo.py OPTIONS +
ASSUMPTIONS only; rotation classifications added.

DELIBERATE BEHAVIOR CHANGE (reviewed and accepted): area-marked skillshots
vs Braum E (Ezreal R Trueshot Barrage, Ahri Q) are now REDUCED by the ranked
projectile value (0.55 at rank 5) instead of the legacy misleading "reduced
by 0.0" receipt — the old behavior was a Jax-area branch leaking into the
shared reduction path; wiki: Braum's shield "intercepts all incoming hostile
projectiles". Pinned by matrix D7.7/D7.8. Not golden-visible (no golden fight
arms e_active/w_active).

Atoms (all pre-existing, read-only): Braum E Barrier Duration
(ability.barrier _duration, hash d6f463652bc9c57b, 3.0-4.0s), Braum E Damage
reduction (ability.damage reduction, hash 3e8de1fe75f419da, 35-55%), Yasuo W
active duration (timing.active_duration, hash df1b544914798426, 4.0s).

Files: NEW delivery_eligibility.py + tests/test_delivery_eligibility_kernel.py
(35) + tests/test_delivery_eligibility_consumers.py (15); C-OWNED
tests/test_delivery_interaction_eligibility.py (40). EDITED:
interaction_effects.py, survival/actions.py, survival/compile.py,
survival/receipt_state.py, survival/transitions.py, champions/braum.py,
champions/yasuo.py, champions/__init__.py.

Gates: pytest 5287 passed in 264.62s (5197 + 90 new); black 489 unchanged;
pylint owned source 9.71/10 (kernel 10.00 after removing 2 unused imports —
no E/F; remaining findings pre-existing); atomize clean (no atomizer
changes); golden 845 — IDENTICAL to the pre-existing count, ZERO new.

Documented later-P2 (slice boundary): spell shields, CC immunity, cleanse,
Samira/Gwen/Fiora/Pantheon/Jax recomposition onto the kernel; damage_over_time
marker declared but never stamped on event rows (Malzahar E ticks inherit the
skillshot marker and are destroyed by Wind Wall — pinned current behavior,
contract question in the matrix); true-damage policy asymmetry now explicit;
Braum facing model (melee/non-projectile/ground AoE) unmodeled; Yasuo W
travel/wall-width/basic-attack projectile destruction unmodeled; event-id
selection positional per scenario (unmatched ids receipted); uses latch is
per-fight; Jax area 0.25 literal not atom-backed; compiled score path drops
area_damage/basic_attack (Jax score-mode divergence).

### 4.19 P2 Slice 2 (2026-08-09): Spell-shield eligibility and use lifecycle

Sivir E + Banshee's Veil / Edge of Night / Verdant Barrier Annul (RLM-1
owner p2s2-spell-shield; three RLM-2 audits integrated: p2s2-provenance,
p2s2-runtime-trace, p2s2-test-matrix [C wrote tests/test_spell_shield_eligibility.py — 31 tests]).

Kernel extension (delivery_eligibility.py — same leaf, no second decision
path). Six orthogonal lifecycle phases:
- ARMING: support_packet_priority(kind) — one shared arm-priority table
  (spell_shield/stasis/invulnerability/untargetable -2.0, shield/damage_
  modifier/temporary_health -1.0, else 1.0), replacing the duplicated rule
  in participant_timeline and compile.
- ELIGIBILITY: SpellShieldEligibility(window, acceptance, block_rule,
  source) + SpellShieldAcceptance(requires_ability, blocks_basic_attacks=
  False, blocks_control_only=True, accepts_unknown=False); named denials:
  outside_window / basic_attack_not_blocked / not_an_ability /
  control_only_not_blocked / unknown_delivery / unknown_cast_identity.
- CAST GROUPING: resolve_cast_identity(action) — sourced (ability_instance),
  derived (source_key:time), unknown (fail-closed, never spends);
  spell_shield_group_key attacker-qualifies (pipeline stamps slot:ordinal
  WITHOUT attacker — cross-attacker collision fixed).
- USE CONSUMPTION: UseBudget consume="per_cast" (validated literal) — one
  spend per cast identity; same-cast later packets reuse the decision.
- BLOCKED EFFECT: SpellShieldComposition — FullBlockRule(all, true damage
  included), one-use per-cast budget, optional TriggeredHealRule.
- TRIGGERED HEAL: fires once per consumed use; source atoms attached.

Behavior changes (each source-backed, pinned by matrix tests):
(a) Cross-attacker cast grouping: one use now blocks ONE hostile ability
    instance (Ahri E blocked, Lux E lands 174.3, one heal) — the old
    attacker-unqualified slot:ordinal grouping blocked both.
(b) Braum full-block no longer spends the spell shield (walk order now
    stasis -> projectile destroy/full-block -> spell shield; full-blocked
    packets skip with defense.kind; 'prior_defense_fully_blocked' receipt).
(c) Reduced-then-blocked packets carry BOTH receipts (Braum reduce 0.55 +
    spell-shield block on the same event).
(d) Control packets of one cast share the cast's ability_instance (a
    blocked cast's CC can no longer land after its damage was blocked).
(e) Sivir E duration/heal now read through hash-validated atoms (same
    values): timing.active_duration 1.5s hash 4d718bc78f540f0a; heal
    ability.heal.modifier_0 6c6ba50a6d62b2f3 (%AD) + modifier_1
    ea3a4eff27b79d2e (%AP); 0.25s heal delay = SOURCE GAP (prose-sourced
    literal, documented).
(f) Annul cooldowns source-receipted: BV c020562aebacbe01 (40s), EoN
    30d03573d07ed0a5 (40s), VB 2a40799f92fb6749 (60s); spell_shield_cooldown_
    seconds validates the registry literal against the atom (stale fails
    closed); the mislabeled shield.flat atoms are documented NOT consumable.
Everything else numerically identical (same blocking/heal/windows/pinned
fields; same score-path fail-closed receipts).

Public receipts: spell_shield survival-row receipt — source, window
(Annul until=None), acceptance, block_rule, categorical rules (five rules
with wiki receipts), uses_before/after, selected_cast_identity,
blocked_packets (event_key/time/source/cast identity), decisions,
triggered_heal (time/amount/delay/source), cooldown_seconds + cooldown_atom.

Files: EDITED delivery_eligibility.py, item_effects.py, interaction_effects.py,
survival/transitions.py, survival/receipt_state.py, participant_timeline.py,
champions/sivir.py, support_effects.py, defensive_effects.py, survival/compile.py.
C-OWNED tests/test_spell_shield_eligibility.py (31).

Gates: pytest 5318 passed in 169.40s (5287 + 31); black 490 unchanged; pylint
9.74/10 no E/F; atomize clean (metadata only); golden 845 — identical, ZERO new.

Known limits / follow-up (slice boundary): CC immunity, cleanse, Morgana E,
Mikael's, QSS, Mercurial, Nocturne W = later P2 slices; Annul rearm +
cooldown-restart-on-damage not modeled (cooldowns receipted 40/40/60); item-
effect packets + monster basic attacks have no model tag (ability-only gate is
a declared narrowing); DoT ticks not blocked per tick (needs the unstamped
damage_over_time marker); Sivir 0.25s delay prose gap; Annul shield.flat atom
mislabel flagged; pipeline ability_instance attacker-unqualified (kernel
qualifies; future pipeline fix receipt-only).

Disclosure (verified by parent): the owner's ONE failed `git stash push`
attempt (pathspec error — untracked P2 Slice-1 files aborted it; nothing
stashed; `git stash list` still shows only the two pre-existing entries;
working tree unchanged). No further git write commands were run.

### 4.20 P2 Slice 3 (2026-08-09): Crowd-control immunity — Morgana E Black Shield

One NEW orthogonal leaf `src/calculator/crowd_control_eligibility.py` (478
lines; stdlib + ACTION_BLOCKING_CC_KINDS + delivery_eligibility
DefenseWindow/stable_event_key + state_lifecycle.SourceReceipt +
shield_ledger.TimedShield). Six separation concerns: control classification
(CONTROL_BLOCKING_KINDS + CONTROL_SOFT_KINDS; unknown kinds fail closed
with "unknown_control"; no cc_kind never reports a block), immunity
eligibility (CrowdControlEligibility; named reasons
""/outside_window/control_not_blocking/unknown_control/shield_not_held),
shield ownership (immunity_holder returns the EXACT TimedShield entry —
source match AND alive amount AND expiry; another shield never holds;
fresh re-grant = new holder), shield lifetime (DefenseWindow
start-inclusive/end-exclusive), packet ordering (stable_event_key +
walk action_key total order), receipt writing (decision receipt +
per-event crowd_control_blocked + survival-row crowd_control_immunity with
reason_immunity_ended expired/drained/fight_end).

SAME-HIT ORDERING is deliberately NOT certified: the wiki notes state
gate-before-absorb ("negates crowd control effects before any magic damage
is absorbed; even if the shield is broken... disables will not apply") but
the evidence is SINGLE-PROVENANCE, so same_hit_ordering() fails closed with
"missing_same_hit_rule" (R19); the walk keeps its pinned gate-before-absorb
order (R6a) and the alternate variant is xfailed (R6a-alt) with that exact
reason. PRESERVED scientific limit.

Migration: transitions._crowd_control_immunity_active DELETED -> kernel
immunity_holder + _sync_crowd_control_immunity (legacy projection derived
from the ledger); _apply_shield registers the grant entry (source/granted_at/
expires_at/amount/source_atoms/ended_reason); _apply_crowd_control's bespoke
check -> ONE contract decision for damage-attached AND control-only packets;
post-absorb shield_amount_after written on both paths; finalize records
expired/fight_end. Walk order pinned (R11a-e): stasis -> projectile
destroy/full-block -> spell shield -> CC immunity -> damage.

Atoms (verified): strength 797fffe3046f726e (100-320), AP 9615675a3294f657
(70%), duration 106f001ee676d9f2 (5s), cooldown b5874e9621d31c02 (26-16s);
categorical cc-immunity 4bf95a560923b33d (champions.json); receipts attach
strength+duration (R12 pins hashes).

Files: NEW crowd_control_eligibility.py; EDITED survival/transitions.py +
survival/receipt_state.py; C-OWNED tests/test_crowd_control_immunity.py
(30 passed + 1 xfailed R6a-alt).

Behavior changes (all matrix-pinned, zero numeric changes to any fight):
immunity tied to the exact ledger entry (R8/R18); expiry/depletion clear
immediately (R6b/R7); same-hit gate-before-absorb pinned with fail-closed
certification (R6a/R19); control-only rides the same contract (R3/R16);
unknown kinds fail closed with named reason (R10); blocked control adds no
downtime, unblocked adds sourced duration (R1-R3/R12); non-control damage
never reports a block (R14); walk order with spell shield/projectile defense
unchanged (R11a-e); score path runs the identical kernel (explicit parity
run + contract-owned compiled_support_receipt fail-closed escape, R13).

Gates: pytest 5348 passed + 1 xfailed in 337.18s (5318 + 30 + 1 xfail);
black 492 unchanged; pylint 9.76/10 no E/F; atomize clean (metadata only);
golden 845 — identical, ZERO new.

Known limits / follow-up (next = cleanse): cleanse (QSS/Mercurial/Mikael's)
= P2 Slice 4 on the control-classification contract; same-hit second
provenance (Riot game scripts) to certify same_hit_ordering and unpin
R6a-alt; nearsight + allied-CC exclusions declared (no modeled sources);
Illaoi Test of Spirit + Chum the Waters attach declared follow-ups;
shield-destroying effects bypass (no modeled source); dead fields
support_shield_expired/timed_shields flagged for a future cleanup; Sivir
0.25s heal-delay prose gap + Annul rearm remain Slice-2 follow-ups.

### 4.21 P2 Slice 4 (2026-08-09): Item cleanse eligibility and action-downtime truncation

Mikael's Blessing (Purify — one explicitly selected ally, incl. heal),
Quicksilver Sash (Quicksilver — self), Mercurial Scimitar (Quicksilver —
self; movement speed kept as a SEPARATE utility effect).  (RLM-1 owner
p2s4-cleanse; three RLM-2 audits integrated: p2s4-provenance,
p2s4-runtime-trace, p2s4-test-matrix [C wrote
tests/test_cleanse_eligibility.py — 27 rows, 48 collected]).

Kernel — `src/calculator/cleanse_eligibility.py` (~900 lines,
dependency-light leaf; stdlib + crowd_control_eligibility classification +
delivery_eligibility DefenseWindow/stable_event_key + state_lifecycle
SourceReceipt).  Nine separation concerns: control classification (reused
KNOWN_CONTROL_KINDS), cleanse eligibility (one sourced declaration per item
in ITEM_CLEANSE_DECLARATIONS with wording receipts + atom hashes),
activation time (stable_event_key + walk total order), target selection
(self / explicit_selected_ally, `target_not_selected`), use consumption
(one use per item per fight; `use_spent` only from the holder's live use
state), interval truncation (`truncate_intervals`: historical downtime
remains; active interval ends at activation; same-timestamp controls
removed entirely; future controls untouched — no immunity), heal (Mikael's
100-250 by target level, atom heal.flat cf9fe930ebd40602, SEPARATE effect),
movement utility (Mercurial 50% bonus total MS / 2 s, atom
control.movement_speed 5e5f100f08a793f9, SEPARATE effect), receipts
(decision/recipient `cleanse`/caster `cleanse_use` with pinned field sets).
Unknown control kinds fail closed (`unknown_control`); unknown sources
raise KeyError.

CASTABILITY (sourced): wiki Cleanse atom + client binaries
(data/bin/items.bin.json 16.15.8024387): QSS/Mercurial spells carry
canCastWhileDisabled=true + cannotBeSuppressed=true -> self-casts fire
while CC'd but NOT while suppressed (`caster_control_blocks_cleanse`);
Mikael's 3222Active carries neither flag -> its heal+cleanse stays gated
by the walk's attacker crowd-control gate (`attacker_state_blocked`,
use NOT consumed, use receipt fired_while_crowd_controlled=False).
Suppression removal SET: Mikael's wording excludes it; QSS/Mercurial
wording excludes only Airborne (R7 primary = castability denial; the
wording-based removal variant is the xfailed alternate).  Airborne is
excluded per every wording (`excluded_control_kind`).

Cooldowns: wiki caches carry null for all three actives -> cooldown_seconds
None + cooldown_source_gap receipt (binary caches: Mikael's 120 s,
Mercurial 90 s, QSS 90-vs-0 conflicting — receipted, never enforced).

Walk integration (MINIMAL — no new bespoke branch set): kind="cleanse"
packets ride the existing UTILITY dispatch; Mikael's Purify rides its heal
packet's cleanse marker; ONE kernel truncation applied to BOTH
crowd_control_intervals and action_downtime_intervals (death/stasis kinds
untouched), crowd_control_until recomputed from kept intervals; gated
cleanse activations write the use receipt at the attacker-state gate;
survival rows expose cleanse / cleanse_use / cleanse_denied (intervals_after
+ downtime_after re-derived from the FINAL ledger at assembly).  The
authoring layer emits QSS/Mercurial self-cast cleanse packets (+ Mercurial
movement) from new ITEM_INPUT_OPTIONS active_seconds; the selection gate
stays unchanged (self scope / existing explicit_selected_ally heal).

Score path: cleanse/movement templates already fail closed
(support_kind=cleanse/movement); the heal+cleanse marker now fails closed
with the contract-owned `support_cleanse` gate (compile.py
unrepresentable_heal_receipt + cleanse_eligibility.compiled_support_receipt
mirror) instead of silently compiling as a plain heal.

Atoms (verified): heal.flat cf9fe930ebd40602 (100-250),
control.movement_speed 5e5f100f08a793f9 (50%/2 s), control.ghosted
8b8e9cbe2fd7cb01 (declared; ghosting position modeling out of scope);
the mislabeled Mikael's control.blind f52f8fa1303b07da / vision.sight
33a5ca6ed5e751cf atoms are documented NOT consumable (keyword artifacts
carrying the heal values).

Behavior changes (each matrix-pinned): QSS/Mercurial item_options accepted
(active_seconds; previously named 400); a cleanse activation truncates
eligible active controls; the cleanse utility dimension now counts
kind="cleanse" packets; utility_kind on SurvivalAction now derives from
the event's authored kind string (was dead — enum-vs-string set bug);
QSS coverage stats_only -> modeled_state (reason names the sourced
cleanse); Mercurial movement rides the Shurelya-style utility pattern.
Mikael's heal behavior unchanged (heal amount/selection identical).

Files: NEW src/calculator/cleanse_eligibility.py +
tests/test_cleanse_eligibility_kernel.py (19) +
tests/test_cleanse_eligibility_consumers.py (14); C-OWNED
tests/test_cleanse_eligibility.py (48 collected, 6 deliberate xfails).
EDITED: survival/transitions.py, survival/receipt_state.py,
survival/actions.py, survival/compile.py, item_support_effects.py,
item_effects.py, item_coverage.py.

Gates: pytest 5423 passed + 7 xfailed (5348 + 75 new; 6 new deliberate
xfails); black 496 files unchanged; pylint owned source 9.71/10 no E/F
(pre-existing warning classes only, incl. item_effects broad-exception +
item_coverage line-length pre-existing); atomize clean (metadata only);
golden 845 — identical, ZERO new (no golden fight arms cleanse actives).

Known limits / follow-up (slice boundary): champion cleanses (Gangplank W,
Rengar empowered W, Milio R, Dr. Mundo passive, Olaf R), summoner spell
Cleanse, tenacity, slow resistance, CC immunity, future protection
windows, and any movement-position/spatial modeling = follow-up; item
actives during stasis unmodeled (utility packets ride the dispatch before
the stasis gate — pre-existing, same as Shurelya's); QSS cooldown binary
conflict (90 vs 0) unresolved; Mikael's heal level-domain (1-18) is a
code-side assumption (binary formula corroborates linear-by-char-level);
Mikael's cast-range discrepancy (cache range 0 vs binary 650) unmodeled;
QSS wiki revision (3729899, 2024-08) older than the other items — re-pull
on patch day; suppression removal-set for QSS/Mercurial remains wording-
pinned with the in-game castability denial as the observable rule.


### 4.22 P3 Slice 1 (2026-08-09): Shared mana resource ledger — Tear + Lost Chapter

One typed mana account per (owner, kind) — `src/calculator/resource_ledger.py`
(new leaf ~720 lines, stdlib only). Typed ops: max_increase, gain, spend,
refund, regen, clamp (unknown op raises). Fail-closed: unknown kind, wrong/
missing owner, non-finite/negative amounts, clamp amount != 0, current
outside [0, max] at construction; spend beyond current denied
"insufficient_resource"; over-restoration receipted CAPPED; max_increase
grows maximum and NEVER moves current (sourced Manaflow rule); zero amounts
accepted no-ops. Deterministic total order (time, tier, sequence,
insertion): TIER_RESTORE=0 before TIER_CAST=1 (restore-before-cast
convention). Receipts record owner/kind/op/amount/time/source/sequence/
tier/atoms/current+maximum before+after/accepted/reason/detail.

Migration (one resource truth — no second ledger):
- pipeline cast admission: damage._apply_resource_limits dispatches — ENERGY
  (and the Akali temp-max case) keeps the LEGACY walk bit-for-bit; MANA runs
  _apply_mana_resource_limits through the ledger with IDENTICAL heap order,
  EPS boundaries, regen-on-every-pop, Actualizer 2x window, recast parent
  gate, resource_by_cast rows, insufficient-note. result["resource_ledger"]
  (contract resource_ledger_v1).
- Catalyst restore pass UNTOUCHED (hard-out); its (time, amount) rows flow
  into the SAME ledger as gain ops, ordered before simultaneous casts.
- TEAR: the receipt-only recomputation in item_support_effects RETIRED;
  packets are now a projection of ledger hit receipts with the identical
  schema; only accepted hits become packets; denials receipted
  (missing_hit_identity / no_charge_available / cap_reached — no charge
  consumed at cap); bonus max mana enters the authoritative account
  (closing = opening + 6 per accepted hit; admission can spend it).
  Sourced: 8s cadence, 4 stored charges, 3 minion/6 champion, 360 cap
  (wiki + items.bin.json ManaChargeAmmoCD/ManaChargeMaxAmmo/ManaPerCharge/
  MaxMana); first charge at t=0 kept (both formulas agree; tests pin it);
  per-champion 6 is wiki-only (binary gap receipted); InternalCDPerCastID
  6.5s observed, deliberately not modeled.
- LOST CHAPTER (NEW): ITEM_INPUT_OPTIONS["Lost Chapter"]
  .enlighten_level_up_seconds (float 0..30 step 1, default 0 = NO trigger —
  the smallest explicit timing choice; rendered through the existing
  stack-control UI; served by /api/config); enlighten_restore_percent=20.0 /
  duration=3.0 / ticks=3 as code-owned static keys (parser refresh cannot
  overwrite); driver authors ONE marker event; on pop computes 20% of the
  LIVE maximum (Tear growth before the level-up enlarges the base) and
  pushes 3 equal ticks at +1/+2/+3s; outside-window level-ups receipted
  (triggered=True, ticks_within_window=0), never guessed; MAX triggers 1.
- participant_timeline keys accounts by participant id
  (_actor_params_with_ledger_owner); public_response exposes resource_ledger;
  item_coverage: Lost Chapter stats_only -> modeled_state, Tear wording
  updated to "projected from the typed mana resource ledger".

Atoms (verified): Tear stat.mana f8e104e5f65ff397 (240), Lost Chapter
stat.mana 05327ad078be2bde (300), Catalyst stat.mana cc42451dcf4dfd78 /
stat.health a30899d6cbe13bf7 / heal.flat 37693854f1ef7bb0. NO atoms exist
for Manaflow cadence/values or Enlighten 20%/3s — they are rule
declarations with source receipts (wiki branch + revision; Tear rev
4026380, Lost Chapter rev 3989340), which is the design intent.

RLM-2 audits: A (provenance; binary evidence + gaps), B (runtime trace;
breakage risks honored verbatim), C (matrix; tests/test_resource_ledger.py —
68 tests, ambiguity notes honored).

Files: NEW resource_ledger.py + tests/test_resource_ledger.py (C-owned, 68)
+ tests/test_resource_ledger_consumers.py (14). EDITED: damage.py,
item_support_effects.py, item_effects.py, item_coverage.py,
public_response.py, participant_timeline.py, pipeline.py,
tests/test_cp20_items.py (3 Tear tests now build ledger state through the
kernel).

Behavior changes (pinned): Tear max enters the account (Ahri+Tear 24s:
3 accepted hits +18 max, 9 no_charge_available denials, packets 6/12/18);
denied casts never trigger Tear; missing hit identity fails closed
(utility-only casts get missing_hit_identity receipts — 224/815 parsed
entries lack a champion-affecting proof, overwhelmingly passives; real-cast
examples receipted; per-champion hit proofs = cast-lifecycle follow-up);
Lost Chapter absent -> no trigger, explicit 2.0s -> 3 gains at 3/4/5s
(20%/3 each); Karthus fixture: level-up enables later casts; same-time
order pinned (restore tier before cast tier); an Enlighten infinite-loop
bug (tick events re-scheduling themselves) found and fixed; energy
champions bit-for-bit (legacy walk); manaless champions no ledger/packets.

Gates: pytest 5505 passed + 7 xfailed in 154.30s (5423 + 82); black 499
unchanged; pylint 9.72/10 no E/F; atomize clean (metadata only); golden 845
— identical, ZERO new (golden Tear sweep never exhausts mana, so +6 max
cannot change admission).

P3 follow-ups (hard-out boundary, recorded): Catalyst migration —
COMPLETED in P3 package 3A (§4.24); Rod of Ages, Actualizer, Essence
Reaver, Manamune/Muramana damage, Fimbulwinter, Archangel/Seraph,
Jayce/Ezreal refunds (next package), all other champion resources (energy/fury/ammo/charges), Rengar Ferocity, Senna souls, ASol
Stardust, rotation redesign, cast-lifecycle, spatial, level-growth mid-
fight, Tear per-champion hit proofs, multiple Enlighten level-ups,
compiled-walk resource-receipt skip, Enlighten UI chip.

### 4.23 P3 Package 2 (2026-08-09): Champion mana restore/refund on the shared ledger — Jayce + Ezreal

Jayce W-slot passive mana restore (Lightning Field, NOT Hyper Charge — the
cache is authoritative: W[0] effects[0] "Passive: Jayce's basic attacks
restore mana on-hit", Mana Restored 15-25 over 6 ranks; binary ManaGain
13-25 on StaticField; Hyper Charge has no mana wording) and Ezreal W mark
refund (Essence Flux — NOT Q: effects[2] "If the mark was detonated with an
ability, Ezreal restores 60 mana plus the mana cost of that ability"; Q's
effects[1] is a 1.5s COOLDOWN refund, never routed through the ledger; the
flat 60 is prose-only — no atom exists — binary ManaReturn [60 x7]
corroborates, so it is a typed rule declaration with wiki rev 4041697 +
binary receipts, per the §4.22 Enlighten precedent).

Contract additions (additive to resource_ledger_v1, no schema change):
- Champion entry field resource_restore_per_auto {amount (ranked atom),
  source, atoms} — declared by Jayce's W in BOTH stances; the walk
  schedules ONE OP_GAIN per modeled basic attack (ordinary-rate schedule +
  one gain per in-window Hyper Charge swing, each gated on its arming cast
  being ACCEPTED — denied cast -> arming_cast_denied receipt, never a
  gain), all on TIER_RESTORE (restore-before-cast). Malformed/multiple
  declarations RAISE. Public section resource_ledger.auto_restore.
- Champion entry field mark_refund {flat 60.0, source, atoms, detonation
  ability|basic_attack} — declared by Ezreal's W (option-baked at parse);
  every ACCEPTED W cast arms a mark; every ACCEPTED ability cast consumes
  the OLDEST pending mark (FIFO) and applies OP_GAIN = 60 + the detonating
  cast's ACTUAL paid cost (Actualizer discount included) at the detonation
  timestamp AFTER its spend, tier TIER_RESTORE (refunds enable LATER casts,
  never the detonating one); denied casts never consume (mark persists);
  undetonated marks at fight end -> named denial row mark_undetonated.
  Public section resource_ledger.mark_refunds.
- Ezreal option w_mark_detonation (select ability default / basic_attack)
  via the existing champion-options UI; basic_attack -> zero refund gains +
  one named row per W cast (basic_attack_detonation).
- No duplicate mana state: ledger receipts remain the ONLY truth; champion
  modules do not use the per-cast resource_restore field (cast_timeline
  resource_restored stays 0.0 for both, pinned); refund semantics ride
  OP_GAIN with source/mark receipts (typed refund ops exist in the kernel).

Atoms: Jayce required_ranked_attribute_atom("Jayce","W","Mana Restored",
entry 0) -> ability.mana _restored, values [15,17,19,21,23,25], hash
bfeb0d88945a263e. Ezreal flat 60: NO atom (prose-only; verified catalog) —
typed declaration with receipts.

Files: EDITED damage.py (walk kinds auto_restore/auto_swing_restore +
mark FIFO + public sections), champions/jayce.py, champions/ezreal.py,
champions/engine.py (allowed entry keys), champions/__init__.py (rotation
classification w_mark_detonation); NEW tests/test_mana_restore_refund.py
(RLM-2 C matrix, 22) + tests/test_resource_ledger_champion_consumers.py
(6).

Behavior pinned: Jayce 12s hammer low-mana — 12 restores x25, 7 CAPPED,
later casts affordable; cannon — 8 ordinary + 6 in-window swing restores;
denied burst casts -> arming_cast_denied. Ezreal one-rotation W,Q,E,R at
120 mana — E admitted ONLY with the refund; W-chain 2 refunds of 110,
last mark mark_undetonated; FIFO persistence past denied detonators;
basic_attack option zero gains. Score parity pinned; regression green
(Ahri receipts, Garen manaless, Akali energy legacy, Catalyst/Spellblade/
Enlighten/Tear unchanged).

Gates: pytest 5533 passed + 7 xfailed in 144.57s (5505 + 28); black 501
unchanged; pylint 9.73/10 no E/F; atomize clean (content-identical);
golden 847 = 845 pre-existing + 2 NEW expected baseline-declaration lines
(Jayce W resource_restore_per_auto {"amount": 21.0, atom
bfeb0d88945a263e}; Ezreal W mark_refund {"flat": 60.0, detonation:
ability}) — zero fight-summary changes (all Jayce/Ezreal golden fights
start full and never exhaust mana). Baseline NOT recaptured (parent's
call).

P3 follow-ups (hard-out, recorded): Catalyst migration — COMPLETED in
P3 package 3A (§4.24); RoA/Actualizer/Essence
Reaver/Manamune/Fimbulwinter/Archangel migrations; Rengar Ferocity, Senna
souls, ASol Stardust, other champion resources; rotation redesign;
cast-lifecycle (P4); Tear per-champion hit proofs; compiled-walk
resource-receipt skip; multiple Enlighten level-ups; Enlighten UI chip;
NEW — Ezreal mark 4s window + target-side spell-shield/block-dodge
detonation eligibility (delivery/eligibility packages); NEW — prose
"restore(s) X mana" atomizer extractor (blast radius: Ezreal W 60, Smolder
Q 15); NEW — Jayce per-swing timing under HoB/LT/Lich Bane (count parity
holds); NEW — Jayce Hyper Charge duration wiki 4.0s vs binary 3.6s
discrepancy (unresolved, untouched); NEW — energy-champion per-auto
restore patterns stay on the legacy walk.


### 4.24 P3 Package 3A (2026-08-09): Catalyst of Aeons resource-ledger completion

The Eternity heal is now a pure projection of the typed mana ledger's
ACCEPTED spend receipts — the legacy cast_timeline recomputation in
pipeline.py is gone (it read walk-internal resource snapshots that
score-only mode truncated to the UNDISCOUNTED resource_cost, so an
Actualizer-active Catalyst fight healed 15/5/15 on the receipt path but
7.5/7.5/7.5 on the score path — same fight, different survival totals).

Single authoritative account: `resource_ledger.py` gains the pure
`catalyst_eternity_heal_schedule(receipts, heal_ratio, cap_per_cast,
cap_per_second)` projection (+ `CatalystHealRow`): accepted spend receipts
in ledger order -> one heal row per cast at the cast time, amount =
min(20/cast, 0.25 x spend, remaining 20/s floor-bucket budget); denied
spends can never produce a row. `damage._apply_mana_resource_limits`
computes the rows ONCE from `ledger.receipts()` and publishes
`resource_ledger.catalyst` (typed declaration + heal rows) — contract
stays resource_ledger_v1, so the receipt walk and the score-only walk
emit byte-identical heal packets (Actualizer parity pinned: both modes
now 15/5/15/5 on the doubled 60 spend). `pipeline._item_self_healing_events`
is now a thin reader of the catalyst section (same item_proc schema:
`_trigger_source`/`_trigger_time`/`_trigger_sequence` unchanged); a fight
without the typed account (energy/manaless resource or resource limits
disabled) emits NO heal and appends a named note instead of healing from
the wrong resource's deltas (behavior fix: Eternity heals on MANA spent).

Typed sourcing: all four values (0.10 / 0.25 / 20 / 20) stay code-owned
statics in item_effects.py; the entry now also carries the wiki revision
receipt (page 2964, rev 3960416 — docs/wiki-full-entry-audit.json) as
code-owned source_url/source_revision_id keys (Vampiric Scepter
precedent), and `item_effects.catalyst_eternity_declaration()` bundles
the four values + source receipt + the item's verified stat atom hashes.
RLM-2 A provenance: 0.10/0.25/20-per-cast are wiki + binary
(EternityManaRestore/HealthRestore/MaxHealPerCast in
data/bin/items.bin.json 16.15.8024387) + atoms (heal.flat
37693854f1ef7bb0, stat.mana cc42451dcf4dfd78, stat.health
a30899d6cbe13bf7 — hashes verified); the 20/s cap is wiki-only,
binary-implied by EternityCDPerCast=1.0 (no direct field; conservative).

Unchanged: mana restore side (incoming pre-mitigation champion damage ->
OP_GAIN tier 0 at the hit timestamp, capped at max mana) already rode the
ledger (P3S1); `survival/compile.py` still fails closed for Catalyst
builds with `item_mechanic=Catalyst of Aeons` (the restore->admission
rerun and the ledger-projected heals never reach the compiled score
kernel); `item_coverage.py` wording updated (automatic policy: no user
input required).

RLM-2 audits: A (provenance; all values certified, zero mismatches,
source receipt gap closed), B (runtime; found + fixed the score/receipt
divergence), C (matrix; tests/test_catalyst_resource_ledger.py — 23
tests, all green BEFORE integration and still green after; owned the
file alone).

Files: NEW resource_ledger.py section (projection + row) and
tests/test_catalyst_resource_ledger.py (C-owned, 23). EDITED:
item_effects.py (source receipt keys + declaration accessor), damage.py
(catalyst section on the ledger walk), pipeline.py (projection reader +
no-ledger note), survival/compile.py (comments), item_coverage.py
(wording), participant_timeline.py (docstring accuracy only),
tests/test_item_sustain.py (synthetic fixture re-pointed at the
projection contract), tests/test_resource_ledger.py (stale comment).

Behavior changes (pinned): score-only and receipt paths now heal
IDENTICALLY for Catalyst builds (Actualizer-doubled spend respected on
both); energy champions holding Catalyst no longer heal from energy
deltas (named note instead); a future per-cast MANA restore champion
would heal on GROSS spend (receipt amount) — the correct Eternity
semantics, latent today. Zero golden impact: the item sweep pins no
Catalyst heal amounts.

Gates: focused 140 (C matrix + ledger + sustain + mana restore), full
pytest 5563 passed + 7 xfailed in 127.13s (5540 + 23), black clean on
all 8 changed files, pylint 9.72/10 combined no E/F and ZERO owned
findings (new code clean; remaining are the documented pre-existing
warning classes), atomize content-identical (generated_at only), golden
857 = 857 prior — ZERO new differences (0 Catalyst lines; category
breakdown matches the §6 taxonomy: 664 event-metadata markers, 55
breakdown/total, 52 authored control/spell-shield receipts, 38 Veigar
pass-16, 28 Nasus, 12 other, 6 Vladimir, 2 P3-package-2 declarations).
Baseline NOT recaptured.

P3 follow-ups (hard-out, recorded after 3A): RoA/Actualizer/Essence
Reaver/Manamune/Fimbulwinter/Archangel migrations; Rengar Ferocity, Senna
souls, ASol Stardust, other champion resources; rotation redesign;
cast-lifecycle (P4); Tear per-champion hit proofs; compiled-walk
resource-receipt skip; multiple Enlighten level-ups; Enlighten UI chip;
Ezreal mark 4s window + detonation eligibility; prose "restore(s) X mana"
atomizer extractor; Jayce per-swing timing under HoB/LT/Lich Bane; Jayce
Hyper Charge duration wiki 4.0s vs binary 3.6s (unresolved); NEW —
energy-champion Catalyst restores still ride the legacy walk (a Catalyst
holder without a mana pool gains energy from the damage-taken rows — the
legacy ENERGY walk is bit-for-bit untouched per P3S1; fix belongs to a
champion-resource package); NEW — engine seam drops out-of-window restore
rows without a named denial receipt (producer already fails closed, so
unreachable from real fights).


### 4.25 P1 Package 3B (2026-08-09): Fimbulwinter Everlasting CC packet certification

The Everlasting packet contract is complete with NAMED fail-closed denial
receipts: every trigger that cannot fire emits an ``item_denial`` receipt
(kind="item_denial", source "Fimbulwinter — Everlasting", time, reason) —
``ranged_slow`` (slow-classified event on a non-melee holder),
``mana_gate`` (current mana <= 20% max, including manaless), ``cooldown``
(in-flight 8s global), ``duplicate_instance`` (InstanceCadence once-only),
``untyped_cc`` (bare crowd_control flag), ``unknown_cc_kind`` (cc_kind
outside the sourced vocabulary). Events with NO CC metadata are not
candidates and produce nothing. The reasons are kernel-owned:
`state_lifecycle.CcTriggerRule.denial_reason(event, is_melee=...)` — the
adjacency test is deliberately broader than `is_candidate` so an unknown
kind is receipted even though it can never match a branch.

Receipts never leak into the applied support stream:
`participant_timeline._support_effect_templates` splits `item_denial` rows
into a collector (`denial_receipts`), threaded through the per-pair and
fallback paths, and the timeline result exposes them publicly as
`result["item_denial_receipts"]` (time/source/reason/attacker/target/
cc_kind/event_id). The compiled/score call sites and the survival walk
never see them.

Also completed (audit-driven):
- CONTROL-ONLY TRIGGERS: `_cc_triggers` now scans BOTH the damage stream
  and `control_events` (Darius E / Elise E style control-only packets
  previously never armed Everlasting); a (time, source_key, cc_kind)
  dedupe keeps exactly one copy when the pair enrichment merged a control
  row into the per-event view (no double-fire, no spurious denials).
- STABLE SHIELD IDENTITY: the shield packet carries a deterministic
  `_event_id` = `{attacker}:fimbulwinter:{ability_instance|source_key:time}`.
- TUPLE-LEDGER HARDENING: CC-trigger holders (Fimbulwinter, Bandlepipes,
  Solstice Sleigh, Imperial Mandate) were missing from
  EVENT_SCAN_SUPPORT_ITEMS — a score-only tuple fight would have silently
  starved the CC scan (latent; the compiled path fails closed for
  Fimbulwinter today). Added per the set's own documented contract.

Provenance (RLM-2 A): 100 base / 0.045 current-mana ratio / 1.8x
multi-target / 3s duration / 8s cooldown / Awe 0.15 are wiki (rev
3984419) + binary (Items/3121, 16.15.8024387) + atom backed (3121 atoms:
shield.flat, timing.cooldown, stat.mana, control.immobilize, control.slow;
manifest verified; item id 3121 — NOT 3802 which is Lost Chapter). The
20%-max-mana gate has NO local source (wiki cache, binary, and atoms all
lack it — it is game-script behavior in 3121.lua, not decomposed): it is
a documented rule declaration, boundary strictly-above (<= denied,
manaless denied) — flagged in item_coverage wording, holds "sourced"
status until script-level binary evidence exists. The 1200-unit
nearby-enemy RANGE is sourced (wiki + binary effectRadius + atom) but
unmodeled: nearby_enemy_count = whole enemy roster, 1.8x applies
unconditionally with >1 enemy — documented in item_coverage, unchanged
behavior (C's tests pin the roster-count observable).

Certification gate UNCHANGED (fail-closed): `_fimbulwinter_event_coverage`
still requires every ability event to carry typed cc_kind/cc_reviewed, so
unreviewed abilities keep `fimbulwinter_everlasting` coarse + optimizer
withhold; typed-CC fights (Ahri E, Cassiopeia R, Nautilus R, Jhin W,
auto-only windows) certify. The "reviewed, no CC" opt-in marker for the
remaining champion modules (and the multi-part same-ability stamping for
Morgana R / Karma W) is the recorded follow-up — B's audit mapped the
design (per-module CC_REVIEW_STATUS opt-in; per-entry cc_reviewed stamps),
deliberately NOT blanket-defaulted because the known-degraded parses
(AGENTS.md §Known Quirks) would falsely certify.

RLM-2 audits: A (provenance; certified values + gate/range caveats), B
(runtime; G1-G6 gap ranking; the denial design + G3/G4/G5 fixes), C
(matrix; tests/test_fimbulwinter_cc_packet.py — 52 tests, 8 xfails
pre-integration that are now PASSING; owned the file; xfail markers
flipped by the coordinator after the receipt contract landed).

Files: EDITED src/calculator/state_lifecycle.py (denial_reason kernel
method), item_support_effects.py (denial rows + _cc_event_stream +
EVENT_SCAN_SUPPORT_ITEMS + shield _event_id), participant_timeline.py
(denial split + public item_denial_receipts), item_coverage.py (wording:
denials, gate source-status, range caveat), tests/test_state_lifecycle.py
(kernel denial tests), tests/test_state_lifecycle_consumers.py +
tests/test_item_support_effects.py (existing Fimbulwinter tests updated
to filter kind=="shield" and pin the new denial rows; +2 control-only
tests), tests/test_participant_timeline.py (+2 integration tests:
ranged-slow denial split via Cassiopeia R facing-off, score-only dict-row
pin), tests/test_fimbulwinter_cc_packet.py (C-owned; xfail flips).

Behavior changes (pinned): denied triggers now produce named receipts
where they were silent; control-only CC (Darius E style) now arms the
shield in the fallback/direct derive paths; the paired path was already
correct (enrichment merged control rows). Score-only tuple fights for
CC-trigger holders keep dict rows. Survival totals, shield amounts, and
all certified-fight behavior unchanged.

Gates: focused 799 (Fimbulwinter matrix + ledger + item + state +
timeline + optimizer), full pytest 5621 passed + 7 xfailed in 125.47s
(5563 + 58 new), black clean (9 files), pylint 9.69/10 no E/F and ZERO
findings on new code (remaining are the documented pre-existing R/C
warning classes), atomize content-identical (generated_at only; 3121
atoms byte-identical to HEAD), golden 857 = 857 prior — ZERO new
differences (0 Fimbulwinter/shield/support lines; the single "shield"
line is the pre-existing Sivir spell-shield metadata). Baseline NOT
recaptured.

Follow-ups (recorded): per-module "reviewed, no CC" opt-in markers +
per-entry cc_reviewed stamping for mixed typed-CC abilities (Morgana R,
Karma W) to certify remaining champion fights; 1200-unit nearby-enemy
range modeling; 20% gate script-level binary evidence; same-time
reactive-vs-shield ordering pin for enemy holders; cadence-burn
(mana/cooldown-denied casts consume their instance) — documented, not
changed.


### 4.26 P1 Package 3C (2026-08-09): Eclipse stack self-shield and proc-timing certification

Eclipse's Ever Rising Moon stack/proc/shield contract is certified with
NAMED fail-closed receipts and explicit packet ordering. The mechanics
were already implemented (kernel WindowStackGate, engine pair scheduling,
participant self-shield, optimizer timing exclusion, BIS certification);
this package completed the certification surface:

- NAMED MALFORMED-PROC RECEIPT: the malformed-ledger coarse fallback
  (damage.py late-phase proc path) now stamps its duration-scaled row with
  `event_phase="coarse"`, `withheld_reason="malformed_proc_receipt"`, and
  `shield_withheld_reason="self_shield_attached_only_to_certified_proc_events"`
  — callers can distinguish a malformed ledger from a passive that never
  fired, and the shield loss is receipted, not silent (was: bare 4-key row).
- SHIELD TIMING ON THE RECEIPT: each `self_shield_events` dict now carries
  the completed pair's `time` and `event_precision` (the shield arms on the
  same proc event it rides). Ledger rows carry the same fields.
- SAME-TIME ORDERING EXPLICIT: the public support-events serializer now
  exposes `priority` (damage 0.0 / shields 0.5 / heals 1.0); the pinned
  observable is damage-first — the proc's own damage at t is NOT absorbed
  by the shield armed at t (absorbed 0), the shield absorbs reactive
  same-time hits and later hits, and expiry is EXCLUSIVE at t+duration
  (hit at exactly t+2 not absorbed). bis.py BIS note states the model-wide
  additive-shield-stacking choice.
- TUPLE-LEDGER HARDENING: the score-only tuple predicate now excludes
  Eclipse holders (light rows cannot carry `self_shield`); the compiled
  walk already failed closed, so this is defense-in-depth.
- UNREADABLE SHIELD RECEIPT: an unreadable `self_shield` payload drops the
  shield AND appends a named `item_denial_receipts` row
  (`reason="self_shield_payload_unreadable"`) — the 3B denial channel
  extended to Eclipse shields.
- TARGET BOOKKEEPING DOCUMENTED: the engine is 1v1, so the gate is fed
  without a target and receipts name the `default` target; per-target
  cooldown semantics are realized by one gate per pair fight (per-pair
  isolation = League's per-champion clocks) — documented in the engine
  docstring (kernel per-target clocks are tested directly).
- SOURCE RECEIPT FIXED: `_ECLIPSE_TRIGGER_SOURCE` now carries the real
  full-entry audit revision (page 740131, revision 4015408,
  2026-05-04T14:02:12Z) instead of the cache-backed zero revision.
- COVERAGE WORDING: item_coverage gains an explicit Eclipse entry (kernel
  stack gate, sourced proc + timed self shield, malformed-ledger named
  withhold, proc_Eclipse timing exclusion before ranking).

Provenance (RLM-2 A): all 10 values certified — 8 wiki+binary+atom
(6%/4% max HP, 6s cooldown, 160/80 base, 40%/20% bonus AD, 2s shield,
2s window via binary WindowDuration), `stack_required=2` wiki-only (no
binary field), item id 6692 (4016 = Wordless Promise; 226692 is a
non-SR variant). Mismatches: binary expresses ranged damage as 6%x0.667
= 4.002% vs wiki/registry 4% (immaterial); the per-target cooldown is a
kernel interpretation (per-champion stacking implied, not verbatim);
atoms carry the values as flat keyword blobs (stack count and window
conflated; cooldown has no atom).

RLM-2 audits: A (provenance; M6 receipt fix), B (runtime; GAP 1-9 ranked;
G1-G7 implemented as above, G8 target-eligibility + G9 stat-default
documented as info), C (matrix; tests/test_eclipse_timing_packet.py —
36 tests; 1 xfail pre-integration now PASSING; owned the file; xfail
flipped and shield-dict pins updated by the coordinator after the 3C
receipts landed).

Files: EDITED src/calculator/damage.py (withheld markers, shield timing,
docstring), pipeline.py (tuple predicate), participant_timeline.py
(unreadable-shield denial receipt, public priority), item_effects.py
(source revision), item_coverage.py (Eclipse wording), bis.py (BIS note),
tests/test_eclipse_timing_packet.py (C-owned; xfail flip + shield pin +
GAP-4 receipt test), tests/test_item_damage.py +
tests/test_state_lifecycle_consumers.py (shield-dict pins),
tests/test_participant_timeline.py (GAP-3 tuple pin).

Behavior changes (pinned): coarse-fallback rows carry named withheld
receipts (no numeric change); shield receipts carry time/precision
(additive keys — 3 exact-equality pins updated); score-only Eclipse
fights keep dict rows; unreadable shields produce named denial receipts.
All proc counts, damage, shield amounts, and certified-fight behavior
unchanged.

Gates: focused 698 (Eclipse matrix + item + state + timeline + optimizer
+ participant), full pytest 5658 passed + 7 xfailed in 281.18s (5621 +
37 new), black clean (10 files), pylint 9.73/10 no E/F and ZERO findings
on new code (remaining are the documented pre-existing R/C warning
classes), atomize content-identical (generated_at only; 6692 atoms
byte-identical to HEAD), golden 857 = 857 prior — ZERO new differences
(0 Eclipse/proc/shield lines). Baseline NOT recaptured.

Follow-ups (recorded): multi-target roster engine (per-target cooldown
clocks then feed real targets); DoT/CC stack sources (wiki grants stacks
for DoT/CC applications — the engine counts damaging casts and autos
only; documented withheld dimension); strongest-shield-selection rule
(additive stacking documented); pet-exclusion test (implicit today).


#### 4.26A P1 Eclipse DoT/CC stack-source certification (2026-08-11)

The ordinary Eclipse stack-source contract now covers sourced direct
damage and reviewed control-only applications. Each candidate must carry
an enemy target id, a cast or application id, and a timestamp. The
WindowStackGate now uses the real target id. Damage and CC from one
ordinary cast against one target share one application identity and add
one stack. Two distinct cast identities can complete the two-stack
window. Missing identity, target, timing, or CC review status produces a
named denial receipt.

Generic DoT ticks no longer stand in for an application. The local Wiki
authorizes DoT applications as stack sources, but it does not provide the
application timestamp or refresh semantics needed by the event model.
These candidates now fail closed with
`dot_application_timing_unavailable`. A fight with only blocked Eclipse
candidates keeps a zero-damage row with
`withheld_reason="eclipse_stack_source_unavailable"` and publishes the
source denials. This keeps the supported base path separate from the
blocked DoT timing claim.

Source authority: Eclipse page 740131, revision 4015408,
2026-05-04T14:02:12Z; content SHA256
`1d2c8b7e1332e9fcaa8d11ec090c238f7a872fe119f20841d96d49d2cc82b3ec`;
document SHA256
`933e566cc738fa9d81efbb5050d6d47470730d9eb1a7b62d71af547b5a80f92c`.
The local binary certifies the 2.0-second window. It does not certify the
DoT/CC source semantics. Named champion exceptions for Ambessa R, Master
Yi Q, and Warwick R remain separate packets.

Files touched by this packet: `src/calculator/damage.py`,
`src/calculator/item_effects.py`, `src/calculator/item_coverage.py`,
`tests/test_eclipse_dot_cc_stack_sources.py`,
`tests/test_eclipse_timing_packet.py`, `tests/test_eclipse_timeline.py`,
and `tests/test_state_lifecycle_consumers.py`.

Gates: focused Eclipse slice 66 passed + 2 strict xfailed; related suite
1197 passed + 2 strict xfailed; full pytest twice, both 7466 passed + 55
xfailed; black clean across 555 files; full-source pylint 9.55/10 with
the shared baseline unchanged and owned E/F lint 10.00/10; two temporary
atom generations content-identical after generated-time and manifest
digest normalization, with no tracked atom write; golden compare kept
the shared 1015 differences and contained zero Eclipse lines, so the
baseline was not recaptured; Catalyst + resource-ledger suites: 140
passed.

Follow-ups: source the generic DoT application timestamp and refresh
rules before enabling that stack source; model named champion
exceptions in their own packets; multi-target roster, strongest-shield
selection, and pet exclusions remain recorded boundaries.


### 4.27 P1 Package 3D (2026-08-09): Bastionbreaker Shaped Charge packet certification

Shaped Charge's next-damaging-ability true-damage proc is certified with a
NAMED malformed-ledger receipt. The mechanics were already implemented
(parser, compiler, cooldown-gated scheduling, authored-hit preference,
coverage exclusion); this package closed the certification surface:

- NAMED MALFORMED-LEDGER RECEIPT: `_add_shaped_charge_damage` now
  distinguishes a malformed cast ledger (`proc_receipts is None`) from a
  passive that never fired (empty — still no row, no aggregate
  substitute). A malformed ledger keeps a ZERO-DAMAGE row stamped
  `event_phase="coarse"` + `withheld_reason="malformed_proc_receipt"`
  (Eclipse-3C precedent); no damage is invented. `_event_timeline_coverage`
  treats a row carrying `withheld_reason` as a coarse source even at zero
  total damage, so `shaped_charge_Bastionbreaker` enters coarse_sources
  and the optimizer/BIS exclusion receipt names it — a malformed ledger is
  now distinguishable from a never-fired passive without re-deriving
  coverage (was: silent absence + falsely-complete timeline).
- DOD PRECISION FIX: `_item_proc_precision` read `dot_duration` from the
  breakdown row (a dead branch — ability rows never carry it), stamping
  uncertified DoT casts as "exact". It now reads the ability packet's
  `dot_duration` (the same source the coverage classifier uses), so a DoT
  ability's item proc (Shaped Charge / Eclipse / Muramana) honestly falls
  back to `cast_boundary` → coarse → excluded until event-certified.
- SOURCE RECEIPT: the Bastionbreaker registry record now carries the
  code-owned wiki revision receipt (page 1714197, rev 4046567,
  2026-07-28T19:50:32Z — docs/wiki-full-entry-audit.json) as
  source_url/source_revision_id static keys (Catalyst-3A pattern); the
  five numeric values stay parser-owned.
- COVERAGE WORDING: item_coverage gains an explicit Bastionbreaker entry
  (20s next-instance semantics, 50/25 + 1.5/0.75 per lethality TRUE
  damage, authored-hit preference, named malformed withhold, coarse
  exclusion) plus a NAMED BOUNDARY note for Sabotage: its turret/epic-
  monster targets do not exist in the 1v1 champion-only model, so it is
  NOT modeled (the full-entry audit's "modeled" claim for Sabotage is
  stale — flagged for a future audit refresh).

Provenance (RLM-2 A): all five values certified — base 50/25,
lethality ratios 1.5/0.75 (binary: AbilityDamageCalc 50.0 + mStat 29
Lethality 1.5, ranged via AbilityDamageRangeMod 0.5), cooldown 20.0
(binary mDataValues Cooldown + wiki structured field), damage_type
"true" wiki-only (no binary type marker), atoms damage.ability/
damage.true [50,25,1.5,0.75,1.0] with verified hashes. Sabotage is a
separate passive (300/240 + 25/20 per lethality, 3s takedown window,
90s buff, 3s DoT, turret/epic-monster target — sourced in the atom
catalog damage.basic_attack) with zero code footprint in the shaped
charge path — no conflation. Trigger semantics verbatim: "Your next
instance of ability damage to a champion or epic monster with a
champion ability deals ... bonus true damage" — one proc per damaging
ability cast, champion-only (1v1), autos/item-procs never trigger,
cooldown anchored at the consumed hit time (inclusive boundary).

RLM-2 audits: A (provenance; G4 receipt wiring), B (runtime; G1 blocking
+ G2-G7; G1+G2 named receipt implemented, DoT precision fixed, G4 wired,
G3 Sabotage boundary noted, G5-G7 documented), C (matrix;
tests/test_bastionbreaker_packet.py — 42 tests; 1 xfail pre-integration
now PASSING; owned the file; the malformed-pin rewrite + xfail flip were
the coordinator's integration per the binding spec).

Files: EDITED src/calculator/damage.py (malformed named row + coverage
carve + _item_proc_precision DoT fix), item_effects.py (source receipt
keys), item_coverage.py (Bastionbreaker + Sabotage boundary wording),
tests/test_bastionbreaker_packet.py (C-owned; pin rewrite + xfail flip).
No changes to parser, compiler, scheduler, pricing, or the certified row
shape (the 7-key certified row is pinned).

Behavior changes (pinned): malformed ledgers now produce a named
zero-damage coarse row + coarse coverage source (was: silent absence with
falsely-complete coverage); DoT-ability item procs without authored
events now fall back to cast_boundary (was: falsely exact). No damage
numbers changed in any real fight; score/receipt parity verified
identical; optimizer exclusion and BIS behavior unchanged.

Gates: focused 695 (Bastionbreaker matrix + item + timeline + optimizer
+ participant + Eclipse), full pytest 5700 passed + 7 xfailed in 274.70s
(5658 + 42 new), black clean (4 files), pylint 9.73/10 no E/F and ZERO
findings on new code (remaining are the documented pre-existing R/C
warning classes), atomize content-identical (generated_at only; 2520
atoms byte-identical to HEAD), golden 857 = 857 prior — ZERO new
differences (0 Bastionbreaker/shaped_charge/event_precision lines).
Baseline NOT recaptured.

Follow-ups (recorded): Sabotage modeling (needs turret/epic-monster
targets — a spatial/objective package) + the stale "modeled" claim in
docs/wiki-full-entry-audit.json (refresh via scripts/full_entry_audit.py);
G6 per-slot cursor advance on cooldown-skipped recasts (no module authors
more events than accepted casts today); G7 authored-event unstamped
precision defaults to exact (modules stamp today); G5 lethality stat
default (production always populated).


### 4.28 P1 Package 3E (2026-08-09): Muramana Shock ability-timing certification

Muramana's Shock ability branch is certified with a NAMED malformed-ledger
receipt, a damaging-cast gate, and explicit non-conflation boundaries.
The mechanics were already implemented (parser, compiler, per-cast-instance
scheduling, authored-hit preference, Ezreal-Q on-hit suppression); this
package closed the certification surface:

- DAMAGING-CAST GATE (P0 behavior fix, runtime-audit finding): Shock is
  gated on "Dealing ability damage to champions" — `total_muramana_procs`
  now increments only when a cast deals damage (`ability_total > 0.0`), and
  `_muramana_proc_events` skips zero-damage slots via the same parts
  predicate Shaped Charge uses.  Previously a zero-damage cast (Vayne W,
  Sivir E spell-shield, rank-0 leftovers, stat-buff ultimates) minted a
  Shock proc; the golden item-sweep Vayne fight drops exactly one proc
  (the single new golden diff, explained below).
- NAMED MALFORMED-LEDGER RECEIPT: a malformed or count-mismatched cast
  ledger keeps its aggregate price (the proc count is the trusted cast
  receipt) but the row is stamped `event_phase="coarse"` +
  `withheld_reason="malformed_proc_receipt"` (was: silent aggregate-only
  row, indistinguishable from never-fired without re-deriving coverage).
- NEVER-FIRED SUPPRESSION: an autos-only fight (zero damaging casts) now
  authors NO `muramana_ability` row (Shaped-Charge precedent; was a
  zero-price placeholder row invisible to coverage).
- SOURCE RECEIPT: the Muramana registry record now carries the code-owned
  wiki revision receipt (page 747852, rev 4005926,
  2026-04-05T23:26:41Z — docs/wiki-full-entry-audit.json) as
  source_url/source_revision_id static keys; the four Shock/Awe numbers
  stay parser-owned (pinned by TestValuesSourcedFromTheCache).
- COVERAGE WORDING: item_coverage gains an explicit Muramana entry
  (one Shock per DAMAGING ability instance 4%/3% max mana, 1.2% on-hit on
  real autos only with ability-carried on-hit suppression, named malformed
  withhold, coarse exclusion, Awe separation) plus a NAMED BOUNDARY note
  for the sourced 6.5s per-target Shock lockout (wiki + binary
  PerCastIDLockout + atom): per-cast-instance counting is modeled; the
  same-target short-ICD lockout (Ezreal/Cassiopeia rotations) is the
  recorded follow-up.

Provenance (RLM-2 A): all values certified — on-hit 1.2%, ability melee
4% / ranged 3%, Awe 2%, physical (wiki rev 4005926 + binary Items/3042
tooltip values AND GameCalculation coefficients + atoms damage.ability
[4.0,3.0,6.5] etc. with verified hashes). The 6.5s lockout is sourced in
all three layers (PerCastIDLockout) but unmodeled — per-cast-instance
counting matches the wiki's once-per-cast-instance rule for single-target
fights; short-ICD same-target suppression is the divergence (documented,
not modeled — C's tests pin the absence of a cooldown key). Manamune
(3004) carries only Awe+Manaflow, Muramana (3042) only Awe+Shock — clean
separation; Awe (0.02, shared BonusADFromMana calc) bridges the
transformation with no discontinuity.

RLM-2 audits: A (provenance; 6.5s lockout finding), B (runtime; P0 Gap 2
zero-damage gate + Gap 1 named receipt + Gap 3 row suppression + Gap 4
revision wiring; all implemented), C (matrix; tests/test_muramana_packet.py
— 48 tests; 2 xfails pre-integration now PASSING; owned the file; the
malformed-pin rewrite, autos-only pin rewrite, xfail flips, zero-damage
tests, and revision assertion were the coordinator's integration per the
binding spec).

Files: EDITED src/calculator/damage.py (damaging-cast gate in
total_muramana_procs + _muramana_proc_events, malformed named row,
never-fired row suppression), item_effects.py (source receipt keys),
item_coverage.py (Muramana + 6.5s lockout boundary wording),
tests/test_muramana_packet.py (C-owned; pin rewrites + xfail flips +
zero-damage + revision tests), tests/test_muramana_timeline.py (unit
fixtures gain realistic parts packets), tests/test_item_effects.py
(parser-ownership pin updated for the receipt-only static entry).

Behavior changes (pinned): zero-damage casts no longer proc Shock (Vayne
W/Sivir E/rank-0 slots — the golden Vayne sweep drops exactly one proc);
malformed ledgers carry the named withheld receipt; autos-only fights
author no ability row. No changes to the certified per-cast-instance
timing, authored-hit preference, Ezreal-Q suppression, real-auto on-hit,
Awe conversion, or score/receipt parity (verified identical).

Gates: focused 1135 (Muramana matrix + item + Ezreal + stats + source +
coverage + timeline + optimizer + participant + app + economy + survival),
full pytest 5748 passed + 7 xfailed in 353.87s (5700 + 48 new), black
clean (6 files), pylint 9.73/10 no E/F and ZERO findings on new code
(remaining are the documented pre-existing R/C warning classes), atomize
content-identical (generated_at only; 3042 atoms byte-identical to HEAD),
golden 858 = 857 prior + 1 NEW explained diff:
`/item_sweep/Muramana/vayne/total_damage: 1241.3 -> 1179.74` — Vayne's
sweep rotation includes Silver Bolts (W, a zero-damage passive slot) which
previously minted a Shock proc; the P3-3E damaging-cast gate correctly
removes it (one fewer 61.56 proc). Baseline NOT recaptured (per
instructions; the new diff is the pinned behavior fix).

Follow-ups (recorded): model the 6.5s per-target Shock lockout for
short-ICD same-target rotations (Ezreal Q spam, Cassiopeia E) — needs a
registry per-target lockout key + timing gate; add explicit count key to
the muramana_ability row (cosmetic 3D-family parity; skipped to avoid
golden churn); malformed vs count-mismatch both collapse to None (single
reason suffices — mismatch is defense-in-depth).


### 4.29 P1 Package 3F (2026-08-09): Zhonya's Hourglass active stasis input and receipt certification

Zhonya's Time Stop input and receipt path is certified. The mechanics were
already implemented (typed option schema, defensive derivation, STASIS
kernel state, compiled parity); this package closed the certification
surface:

- STEP ENFORCEMENT (G1): `validate_item_input_options` and the resolver
  mirror `input_option_float_value` now reject float option values that are
  not multiples of the schema step (stasis_active_seconds step 0.5: 1.3 /
  2.25 raise "must be a multiple of 0.5" at BOTH layers; previously the
  step was UI-only).  Integer options keep their existing lenient behavior
  (their step is a UI hint) — restricted to float options after the World
  Atlas shared_riches_gold regression.
- PROVENANCE FIELDS (G3): the Zhonya/Seeker registry records now carry the
  code-owned wiki revision receipt (page 43052, rev 3902922) as
  source_url/source_revision_id static keys (Guardian's Horn pattern);
  stasis_duration stays the only numeric key.  Seeker's shared-evidence
  note records that its OWN audit revision is 3837259 (page 860703) while
  the pinned receipt is Zhonya's — both carry the identical 2.5s value.
- COVERAGE WORDING (G5): the target-modeled entry now states the stasis
  window is unpriced in optimizer ranking (candidates default to zero
  active seconds; price per candidate via candidate_item_options).
- WEAK-PIN FIX (C's ambiguity): test_survival_kernel._timeline now wires
  `item_options=params.item_options` into resolve_starting_defenses like
  the production seam (calculate.py:_combat_receipt) — the Zhonya
  compiled==receipt parity test previously ran with NO ACTIVE STASIS
  (trivially equal walks); it now prices the real 2.0s window and both
  walks still deep-equal.
- BOUNDARY PIN (G2): test_participant_timeline gains an app-altitude pin
  that the legacy one-way score path (run_fight headline total_damage) is
  stasis-blind while the coupled combat timeline prices the same input —
  the two numbers are documented as different altitudes (no timeline in
  the headline path), not a silent degrade.
- STEP TEST: C's matrix gains `test_step_validation_rejects_non_multiple_
  values` (both layers reject 1.3/2.25/0.7; multiples 0.0-2.5 pass) and the
  registry key-set pin was updated for the provenance fields.

Provenance (RLM-2 A): item 3157 = Zhonya's Hourglass (page 43052); the
2.5s Time Stop duration is TRIPLE-sourced (wiki cached branch "Put
yourself in stasis for 2.5 seconds...", binary Items/3157 mDataValues
Duration=2.5 + spell effect amounts, atom control.stasis 2.5 hash
48781f08a515df76 verified); revision chain 3902922 verified across the
audit doc, ITEM_INPUT_OPTIONS (x2), and _STASIS_SOURCE.  The cached
assignment wording "Place your champion into Stasis..." is a paraphrase —
the real cached wording is quoted above.  Activation time: NOT sourced
(the binary castFrame 25.0 windup is uncorroborated by the wiki; unused)
— the input means a documented FIGHT-START WINDOW at t=0 (model-authored,
fail-closed: 0.0 = not used, item presence alone never starts stasis).

RLM-2 audits: A (provenance; 120s-cooldown finding + Seeker revision
mismatch), B (runtime; G1 step + G2 legacy-blind + G3 provenance + G4
boundary pins + G5/G6 wording — G1/G3/G5 implemented, G2 pinned, G4
covered by C's matrix test 14, G6 recorded), C (matrix;
tests/test_zhonya_packet.py — 24 tests ALL PASS pre-integration, ZERO
xfails; +1 step test and 1 key-set pin update by the coordinator).

Files: EDITED src/calculator/item_effects.py (step enforcement x2 +
provenance fields + static keys), item_coverage.py (G5 wording),
tests/test_zhonya_packet.py (C-owned; step test + key-set pin),
tests/test_survival_kernel.py (weak-pin fix), tests/test_participant_
timeline.py (G2 boundary pin).

Behavior changes (pinned): non-multiple float option values (1.3 / 2.25)
are now rejected at both layers with a named error; the survival-kernel
Zhonya parity test now genuinely exercises active stasis (still
compiled==receipt); everything else is additive provenance/wording.
Coupled-timeline stasis semantics unchanged (seeded state before the walk,
strict-expiry at exactly t=duration is exclusive, t=0 triple ordering
deterministic, incoming blocked "target_state_blocked", holder outgoing
"attacker_state_blocked", action-downtime stasis interval row).

Gates: focused 862 (Zhonya matrix + defensive + survival kernel + item +
coverage + participant + scenario + app + p5 + cleanse + bard + CC
immunity + spell shield + delivery + optimizer), full pytest 5786 passed
+ 7 xfailed in 92.27s (5748 + 38 new), black clean (5 files), pylint
9.76/10 no E/F and ZERO findings on new code (remaining are the
documented pre-existing R/C warning classes), atomize run TWICE with
content-identical results (generated_at only; 3157 atoms byte-identical
to HEAD), golden 858 = prior state — ZERO new differences from 3F (the
single Muramana/Vayne line is the already-documented P3-3E behavior fix;
no Zhonya golden scenario exists). Baseline NOT recaptured.

Named boundaries (recorded): mid-fight activation (no activation-timestamp
field; input = t=0 fight-start window; a stasis packet is never authored
at a nonzero time from the input alone — C test 23); the 120s active
cooldown (BINARY-ONLY source — wiki cache records cooldown null; never
binds in a <=30s window with a single t=0 cast; do not invent a number);
utility/on-hit item actives ride BEFORE the stasis gates during stasis
(HANDOVER §4.2 softness, re-confirmed); the legacy one-way headline score
is stasis-blind by architecture (no timeline) — pinned; step 0.5 and
default 0.0 are model-authored UI conventions (max 2.5 IS sourced).


### 4.30 P1 Package 3G (2026-08-09): Mikael's Blessing active Purify and ally-heal receipt certification

Mikael's Purify input and receipt path is certified. The mechanics were
already implemented (cleanse kernel with named reasons, heal packet,
consumer matrix); this package closed the certification surface:

- COVERAGE WORDING (G1): Mikael's now has an explicit
  `_STATEFUL_MODELED_ITEMS` entry — the attacker-side runtime reason is the
  support-ledger wording (was the generic "exposes its damage-relevant
  state as a scenario control." — the `_REVIEWED_STATS_ONLY` line was dead
  code shadowed by the ITEM_INPUT_OPTIONS branch; kept for C's pin).
- EMISSION VALIDATION (G4): the seven ally-support active_seconds reads
  (Locket, Mikael's, QSS, Mercurial, Redemption, Shurelya's, Stridebreaker)
  now route through a new `_active_seconds` helper that delegates to the
  typed `input_option_float_value` — the emission layer re-checks the
  schema bounds AND step multiple, so a direct timeline caller cannot
  author an out-of-domain activation (31.0 or 0.3) even though the request
  layer already validates.
- UTILITY PANEL (G5): `utility_outcomes` now counts cleanse-marked heal
  packets (kind "heal" + cleanse=True) in the cleanse dimension — a real
  Purify cast reports event_count 1 instead of 0 (R1 pin flipped).
- BOUNDARY TEST (G6): a Purify activation at exactly a control's end time
  is `control_not_active` (end-exclusive interval, use consumed, intervals
  untouched) — pinned at the kernel.
- CONFIG PIN (G8): /api/config serves Mikael's full active_seconds schema
  {float, "Purify active seconds", 0.0, 0.0, 30.0, 0.5} + source_revision
  3984364 — pinned.

Provenance (RLM-2 A): item 3222 confirmed; heal 100/250 TRIPLE-sourced
(wiki {{pp|100 to 250|type=target's level}} + binary HealAmountMin/Max +
atom heal.flat cf9fe930ebd40602); revision chain 3984364 verified across
ITEM_INPUT_OPTIONS, ALLY_ITEM_EFFECTS, cleanse declaration _cache_receipt,
and docs/wiki-full-entry-audit.json (2026-01-14, page 1469747); the
level-domain interpolation (linear 1->18) structurally matches the binary
ByCharLevelInterpolation formula (endpoints model-authored, documented);
exclusions (airborne/blind/disarm/nearsight/suppression) match the wiki
branch verbatim; castability (3222Active has neither canCastWhileDisabled
nor cannotBeSuppressed) matches the binary — Mikael's Purify is gated by
the walk's attacker-state gate. Named boundaries: the 120s cooldown is
binary-only (wiki null) and receipted but never enforced (one use per
fight); the binary cast range 650 is unmodeled; the wiki's self-cast
branch is unmodeled (ally-only by design, pinned).

RLM-2 audits: A (provenance; M1-M5 gaps recorded), B (runtime; G1-G8 —
G1/G4/G5/G6/G8 implemented, G2 revision-chain covered by C's test 48 +
cp47 flagged as a historical checkpoint claim, G3 covered by C's test 50,
G7 verified-no-risk), C (matrix; tests/test_mikael_packet.py — 58 tests
ALL PASS pre-integration, ZERO xfails; coordinator additions: G6 kernel
boundary test, G8 config pin, R1 utility-count pin flip).

Files: EDITED src/calculator/item_coverage.py (stateful entry),
item_support_effects.py (_active_seconds + 7 sites), participant_timeline.py
(utility cleanse filter), tests/test_mikael_packet.py (C-owned; unchanged
by the coordinator — it passed as delivered), tests/test_cleanse_eligibility.py
(R1 utility pin flip), tests/test_cleanse_eligibility_kernel.py (G6 end-exact
test), tests/test_app.py (G8 config pin).

Behavior changes (pinned): the utility panel counts a Purify cast as one
cleanse event (was 0); the emission layer rejects out-of-domain
active_seconds (was reachable only via direct timeline callers); the
attacker-side coverage reason is the support-ledger wording. No change to
packet times, heal amounts, cleanse decisions, exclusions, downtime
truncation, same-time ordering, or score/parity (all verified).

Gates: focused 720 (+ the 2 known pre-existing app rate-limit flakes that
pass in isolation), full pytest 5845 passed + 7 xfailed in 90.76s (5786 +
59 new), black clean (8 files), FULL-SRC pylint 9.55/10 — unchanged from
the documented pre-existing baseline (the E-findings are the pre-existing
data_updater.py vendor-import artifacts; zero findings on new code),
atomize run TWICE with content-identical results (generated_at only; 3222
atoms byte-identical to HEAD, heal.flat 100/250 hash cf9fe930ebd40602),
golden 858 = prior state — ZERO new differences from 3G (the single
Muramana/Vayne line is the already-documented P3-3E fix), Catalyst
resource-ledger set re-run: 133 passed (3A intact). Baseline NOT
recaptured.

Follow-ups (recorded): the cp47-production-acceptance.json residual line
("Locket, Mikael's Blessing, and Redemption target-use effects remain
blocked under #48") is a CP16-time-boxed historical checkpoint claim — the
current-state truth is item_coverage ("Purify is represented by the shared
participant support ledger...") and the umbrella/audit docs; refresh the
checkpoint doc only when its generator is re-run.  Binary-only 120s
cooldown and 650 cast range stay named boundaries (one use per fight; no
range enforcement for ally actives).  Mikael's self-cast branch (wiki
"from yourself or the target allied champion") stays unmodeled — ally-only
by design.


### 4.31 P1 Package 3H (2026-08-09): Redemption active Intervention receipt certification

Redemption's Intervention input and receipt path is certified, with two
PROVENANCE CORRECTIONS from the audits:

- COOLDOWN CORRECTED (M1): the registry's 120.0s cooldown contradicted the
  binary (Items/3107 mDataValues Cooldown = 90.0; the cached wiki active
  records null) and matched Mikael's binary — a copy-paste contamination.
  Now 90.0 with a binary-only receipt comment; never enforced (one cast
  per fight from the single active_seconds input).
- UNSOURCED REVEAL REMOVED (M2): `target_area_reveal_duration` 3.0 had NO
  local source (wiki text names no number — "granting sight of the area
  for the duration"; the binary has no reveal value) and was removed.  The
  sourced reveal EFFECT is now a support kind="vision" receipt per
  selected enemy at the activation time, window [cast, impact] = the
  sourced 2.5s beam_delay (the call-down during which sight is granted),
  with the same cast-range coverage assumption as the heal/damage packets.
- RANGE SEMANTICS NAMED (M3/G3): the 5500-unit range is the sourced CAST
  range (wiki active.range + binary CastRange), while the beam area is the
  sourced 550-radius area (wiki wording + binary AOESize).  The packet
  comment and coverage wording now state the "within_5500_units"
  range_assumption is the CAST-RANGE coverage assumption — every selected
  roster member assumed inside the area, no proximity order invented.
- COMPILED PARITY WORDER CORRECTED (G2): the certified parity is VIA
  FALLBACK — the heal template is plain (compiles), but the kind="damage"
  template fails closed ("support_kind=damage" — the compiled score kernel
  stages only shield/heal support templates), so every active-Redemption
  evaluation falls back to the authoritative receipt walk with EQUAL
  results (per-evaluation for the main holder, search-invariant for an
  ally holder).  Test docstrings corrected to state the honest mechanism.
- BOUNDARY PINS: dead-enemy-at-impact (beam damage skipped, health_damage
  == lethal only) and dead-ally-at-impact (beam heal does not resurrect,
  healing_received 0) pinned at the shared survival-kernel seam.
- COVERAGE WORDING: item_coverage's target entry now names the cast-range
  coverage assumption, the 550-radius beam area, the binary-only 90s
  cooldown (one cast per fight), and the parsed-but-unapplied 10%
  heal-and-shield-power stat (named limitation, cross-item).

Provenance (RLM-2 A): item 3107 confirmed (page 1301768, revision
4015392, 2026-05-04T13:22:53Z, status ready); receipt chain verified
across ALLY_ITEM_EFFECTS, ITEM_INPUT_OPTIONS, and the audit doc; heal
150-350 by target level (wiki pp + binary HealMin/Max + atom heal.flat),
10% enemy MAX-health true damage (wiki + binary DamageToChampions 0.10 +
atom damage.true), 2.5s beam delay (wiki text + riot; binary has no spell
record — no contradiction), 5500 cast range (wiki + binary CastRange).
Gaps recorded: binary spell record absent locally (delay/reveal/cooldown
beyond the item record unverifiable), wiki cooldown absent (null), the
level-domain endpoints are binary-structure-backed with model-authored
1->18 endpoints (consistent with ByCharLevelInterpolation endValue 1.0).
Separation verified: Redemption 150-350 vs Mikael's 100-250 vs Locket
290-360 — no cross-contamination; only the cooldown 120 was the sibling
copy-paste, now corrected.

RLM-2 audits: A (provenance; M1 cooldown correction + M2 reveal removal +
M3 range semantics — all implemented), B (runtime; G1 reveal receipt +
G2 compiled wording + G3 range comment + G5 H+SP limitation + G7 snapshot
note — G1/G2/G3 implemented, G5/G7 documented; G4 cp47 historical claim
kept; G6 cooldown corrected by M1), C (matrix; tests/test_redemption_packet.py
— 51 passed + 1 xfail pre-integration; the xfail flipped and the reveal/
cooldown pins updated by the coordinator per the provenance corrections;
+2 kernel boundary pins).

Files: EDITED src/calculator/item_effects.py (cooldown 90.0 + reveal key
removed), item_support_effects.py (vision receipts + range/max-HP
comments), item_coverage.py (target wording), participant_timeline.py
(reveal_duration whitelist), tests/test_redemption_packet.py (C-owned;
xfail flip + reveal/cooldown/order/scope pin updates + 2 kernel boundary
pins).

Behavior changes (pinned): a kind="vision" receipt per selected enemy at
the activation time (window = sourced 2.5s beam_delay) joins the support
stream; the registry cooldown is the binary 90.0 (dead value, never
enforced); the unsourced 3.0 reveal duration no longer exists.  All heal
amounts, true-damage amounts, beam timings, scopes, and ordering are
unchanged and verified.

Gates: focused 883 (+ the 2 known pre-existing app rate-limit flakes that
pass in isolation), full pytest 5899 passed + 7 xfailed in 92.00s (5845 +
54 new), black clean (5 files), FULL-SRC pylint 9.55/10 — unchanged from
the documented pre-existing baseline (17 pre-existing data_updater.py
vendor E-artifacts; zero findings on new code), atomize run TWICE with
content-identical results (generated_at only; 3107 atoms byte-identical
to HEAD — 8 atom ids incl. heal.flat/damage.true/vision.sight), golden
858 = prior state — ZERO new differences from 3H (the single
Muramana/Vayne line is the already-documented P3-3E fix), Catalyst
resource-ledger set re-run: 133 passed (3A intact).  Baseline NOT
recaptured.

Follow-ups (recorded): H+SP (10%) parsed but not applied to item ally
heals/shields — a cross-item named limitation (only Aery consumes it);
the cp47 residual "#48 blocked" line is a CP16 historical checkpoint
claim (keep); the binary spell record for ItemRedemption is absent
locally (delay/reveal/cooldown binary verification limited to the item
record); in-fight max-HP growth (Heartsteel/Grasp) is not reflected in
the beam's 10% snapshot.


### 4.32 P1 Package 3I (2026-08-09): Briar E (Chilling Scream) certification

Briar E's Chilling Scream slice is certified and the partial atomizer edits
are closed out.  The module (Wave 1), the prose extractors, the catalog,
and the tests were already green; this package verified every 3I rule and
closed the process gaps:

- ATOMIZER SLICE CLOSED (HANDOVER §5 partial edits): the slotlib prose
  extractors (damage reduction, duration, control-duration sequence) and
  the atomizer_domains emissions (ability.damage_reduction,
  timing.active_duration, timing.control_duration_sequence, plus the
  sibling shield/invulnerability/cap atoms) are now formatted, linted
  (one W1309 f-string fixed; unused json/Path imports dropped), and
  test-covered.  The catalog data/atoms/abilities.json ALREADY carries the
  19 Briar E rows (HANDOVER §5's "not regenerated" note was stale on this
  point — the worktree catalog was regenerated 2026-08-10 and is
  hash-identical to live atomization); regeneration remains
  content-deterministic (generated_at only).
- WRITERS GOVERNANCE (G2): data_registry.WRITERS["atoms"] now declares
  both scripts/atomize.py and scripts/extract_atoms.py (the inventory
  test's literal-path scan could not catch atomize.py's dynamic --out
  path).
- OPTIONS-TO-ATOM TIE (G5): test_briar_e pins that the e_charge_seconds
  schema max (1.0) equals the sourced timing.active_duration atom value —
  a schema change without a source change fails the tie.
- TEST MATRIX (C-owned): test_briar_e grew from 20 to 37 tests — atoms
  resolve with exact atom_ids/evidence/hashes; missing/malformed atoms
  fail closed through the module naming the source path; e_charge_seconds
  bounds (schema 0..1 default 1; clamp not rejection: negative -> 0 = no
  window, >1 -> sourced 1s); exact boundary timing at the kernel seam
  (hit at exactly window start reduced; hit at exactly end NOT reduced —
  half-open [start, end); the window arithmetic receipt total); all-source
  reduction (physical/magic/true in-window, full after); wall-collision
  control sequence (knockup 0.5 @0 + stun 1.5 @0.5, source atoms,
  downtime 2.0, opt-in) + wall bonus damage atom-re-derived; compiled ==
  receipt parity (damage modifier staged at phase -1.0, control events
  compile); 5 compiler fail-closed receipts; deterministic receipts.

Provenance (RLM-2 A): 35% damage reduction, 1s charge window ("charging
for up to 1 second" — explicit), 0.5s knockup + 1.5s stun, and the
Maximum/Bonus/Total magic-damage branches are all wiki-backed (tracked
data/champions.json, unmodified; audit page 1594660 rev 4046069 ready;
E template rev 3590413) AND atom-backed with verified hashes
(ability.damage_reduction 35% 493d3f4e2eebac87, timing.active_duration
1s 04f66f2047bf908a, timing.control_duration_sequence [0.5,1.5]s
244c863ed6544fe9); Maximum+Bonus==Total holds across all ranks and
ratios.  Flag: "35% from all sources" is a documented inference (the
cached prose says only "gains 35% damage reduction"; the only cached
"all sources" phrase is the passive's healing line) — explicit in
ASSUMPTIONS and tested.

RLM-2 audits: A (provenance; all values certified + the "all sources"
inference flag), B (runtime; NO functional gaps — G1 delivery/staging
NOT performed per publication limits, G2 WRITERS done, G3 golden
re-capture deferred (the 5 Briar lines are already in the 858 prior
state — no new diffs), G4 lint done, G5 tie test done, G6 K'Sante-R
atomizer dedup hazard handed to the atomizer owner), C (tests;
test_briar_e.py 20 -> 37, all PASS, zero xfails; ambiguities A-F
documented: positional sequence-role attribution, first-phrase duration
extraction fragility, kernel-pinned expiry, silent >1 clamp, data-
dependent 3.0x ratio, negative->no-packet).

Files: EDITED src/calculator/data_registry.py (WRITERS atoms),
atomizer_domains.py (unused imports dropped + W1309 f-string),
tests/test_briar_e.py (C-owned; +16 tests from C + 1 OPTIONS tie from
the coordinator).  slotlib.py and briar.py unchanged (already green).
No behavior changes: the module, extractors, emissions, and catalog
were already correct; the slice adds verification, lint, and governance.

Gates: focused 373 (Briar + atomizer + participant timeline + survival
kernel + interaction atoms + writer inventory + p1/e1/champion/f3
regressions), full pytest 5916 passed + 7 xfailed in 90.61s (5899 +
17 new), black clean (4 files), FULL-SRC pylint 9.55/10 — unchanged
from the documented pre-existing baseline (17 pre-existing
data_updater.py vendor E-artifacts; the atomizer_domains/slotlib/
data_registry findings are the documented R/C/W classes; zero new
findings after the lint fixes), atomize run TWICE with
content-identical results (generated_at only; Briar E atoms verified:
35% / 1s / [0.5,1.5]s with the expected hashes), golden 858 = prior
state — ZERO new differences from 3I (the 5 Briar lines —
E self_state_events damage_modifier, E/R area_damage + skillshot
markers — are the Wave-1 authored lines already counted in the prior
858; the Muramana/Vayne line is the documented P3-3E fix), Catalyst
resource-ledger set re-run: 133 passed (3A intact).  Baseline NOT
recaptured.

Follow-ups (recorded): G1 delivery — the untracked data/atoms/*.json
domain files need staging when the user authorizes commits (the
tracked manifest already references them); G3 golden re-capture for
the Wave-1 Briar rows is deferred to the coordinated worktree-wide
recapture; G6 K'Sante-R atomizer dedup first-wins/evidence-union
hazard — COMPLETED in P1 package 3J (§4.33): per-entry scalar
emission + memo-key fix, 32 rows' evidence collapsed, sequence
unchanged; the positional control-sequence role attribution and the
first-phrase duration extraction fragility (A's/B's/C's flags) stay
documented; the "all sources" reduction is a documented inference.


### 4.33 P1 Package 3J (2026-08-09): K'Sante R atomization dedup certification

The atomizer dedup hazard (HANDOVER §4.32 follow-up G6) is closed: the
scalar timing.control_duration no longer over-claims evidence from effects
whose values were dropped.

- SCALAR-EMISSION FIX: `atomizer_domains.atomize_abilities` emits the
  scalar timing.control_duration only from the FIRST control-bearing
  effect of each entry (a per-entry flag).  Previously the slot-level
  (atom_id, behavior) dedup merged later effects' scalars with
  first-wins values + evidence union — 32 slots' scalar rows claimed
  evidence from effects whose durations were silently dropped (K'Sante R:
  scalar [0.5] with receipts from effects[0] AND effects[1], while
  effects[1] holds the terrain branch [0.264 airborne + 0.5 stun]).
  After the fix: values/units/source unchanged, evidence collapses to
  exactly one receipt, hashes re-derived.  K'Sante R scalar ->
  8c920ea4e4e02b7c; K'Sante R sequence [0.5, 0.3] UNCHANGED
  (ae584f4257399269 — fully sourced from effects[0]'s root+stun; the
  terrain branch's 0.264/0.5 are prose-only, never catalogued, matching
  the certified evidence review).  Catalog delta: 5,092 rows, 32 changed,
  0 added/removed, 5,060 byte-identical; items/runes/economics/stats/
  champions domains byte-identical.  The single remaining multi-evidence
  scalar is Gnar E (cross-entry same-value union — value-honest by
  design).
- MEMO-KEY FIX (ability_atoms): `_ABILITY_ATOMS_MEMO` is now keyed by
  (id(champion_data), champion_name) — the same cached object can be
  atomized under the data key ("KSante") by a typed lookup and under the
  display name ("K'Sante") by the fight path (interaction_effects prose
  durations); the id-only key returned the wrong champion's rows and made
  the 3J typed lookups fail after any K'Sante API fight (pre-existing
  bug surfaced by the new tests).
- TEST MATRIX (C-owned): tests/test_ksante_r_atomizer.py — 10 tests:
  sequence row carries both values (live + catalog, hash-pinned); the
  scalar must not claim multiple durations (the strict xfail flipped to a
  passing contract assertion); determinism; typed lookups; single-duration
  regression (Malphite Q 3.0 / R 1.5 unchanged); catalog-only module
  (ksante.py reads no atoms — no runtime packet impact).

Provenance (RLM-2 A): K'Sante R timing fully sourced from verbatim cached
text (root 0.5s + non-terrain stun 0.3s in effects[0]; terrain airborne
0.264s + stun 0.5s + strike delay 0.132s in effects[1]; All Out 15s in
effects[2]); the sequence [0.5, 0.3] is effects[0]-sourced; the terrain
branch values are prose-only (never in the catalog — must not be read
from data/atoms/abilities.json); audit page 1544537 rev 4011715 ready;
R template rev 3471724.  Runtime consumers verified unreachable-today:
all 12 scalar reads + the Briar sequence read target single-duration
rows whose source/evidence do not change.

RLM-2 audits: A (provenance; M1 evidence over-claim + M2 value drop
confirmed), B (runtime; quantified blast radius + the smallest fix =
per-entry scalar flag + 32-row delta; generic merge changes rejected),
C (tests; 9/10 pass + 1 strict xfail pre-integration; xfail flipped and
pins updated by the coordinator; K'Sante Q flagged as the same pattern —
the per-entry flag fixes it too).

Files: EDITED src/calculator/atomizer_domains.py (per-entry scalar flag),
src/calculator/ability_atoms.py (memo key + name), tests/test_ksante_r_atomizer.py
(C-owned; xfail flip + re-pins), regenerated data/atoms/abilities.json +
manifest.json (32 rows' evidence/hash).  The K'Sante module (ksante.py)
is unchanged — it reads no atoms.

Gates: focused 256 (3J + atomizer + Briar + Cassiopeia + e3 + interaction
atoms + mechanics packets), full pytest 5926 passed + 7 xfailed in 90.16s
(5916 + 10 new), black clean (3 files), FULL-SRC pylint 9.55/10 —
unchanged from the documented pre-existing baseline (17 pre-existing
data_updater.py vendor E-artifacts; zero new findings), atomize run TWICE
with content-identical results (generated_at only; 5,092 rows; 1
remaining value-honest multi-evidence scalar), golden 858 = prior state —
ZERO new differences from 3J (the 3 KSante Q/W marker lines, the 5 Briar
lines, and the Muramana/Vayne line are all prior-documented), Catalyst
resource-ledger set re-run: 133 passed (3A intact).  Baseline NOT
recaptured.

Follow-ups (recorded): the K'Sante Q 0.8s stun and the R terrain-branch
0.264/0.5 timings remain wiki-prose-only (no catalog rows — the per-entry
flag intentionally does not ADD values; a future typed branch-variant
schema would be the representation); the "over X seconds" pull-drag
phrases are not control durations (regex requires "for X seconds"); the
R timing.active_duration [0.5] is the root (a control), not the 15s All
Out buff (active_duration reads effect_index 0 only).


### 4.34 P1 Package 3K (2026-08-09): Cryptbloom takedown heal certification

Cryptbloom's Life From Death takedown heal is certified, with two real
bugs fixed (compiled parity + synthesis target corruption) and the
coverage/compile classification completed.

- G2 FIX (synthesis target corruption): the `target_id` parameter of
  `_support_effect_templates` was SHADOWED by loop variables
  (`for target_index, target_id in enumerate(target_ids)` and
  `for ally_index, target_id in enumerate(target_ids)`) — a roster
  support holder's synthesized takedown target leaked the last iterated
  support-target id, making the heal behavior champion-identity-
  dependent.  Loop variables renamed (ally_target_id / heal_target_id).
- G1 FIX (compiled parity): the compiled BASE panel (roster ally
  attackers) and SIGNATURE panel (roster enemy attackers) called
  `_support_effect_templates` WITHOUT target_id — a roster Cryptbloom
  holder whose first-pair defender died synthesized no takedown, so the
  compiled score walk SILENTLY omitted the heal (equal: False).  Both
  panel call sites now pass the real defender id
  (`target_id=defender.participant_id` / `target_id="main"`), mirroring
  the receipt composition.
- G3 FIX (compiled representation): the timed-heal rejection
  (`support_duration=1.75`) is removed — for kind=="heal" the template
  now compiles directly.  Provably safe: Cryptbloom is the ONLY support
  heal packet with a duration, and the shared kernel applies heals flat
  in both walks (it never reads action.duration for heals).  Main-holder
  kill evaluations no longer pay the per-evaluation compile+fallback.
- COVERAGE (G5): Cryptbloom moved from `_REVIEWED_STATS_ONLY`
  (stats_only) to `_STATEFUL_MODELED_ITEMS` (modeled_state) with the
  support-ledger wording + `_UTILITY_DIMENSIONS` = (ally_support,
  sustain).  The stale docs/wiki-full-entry-audit.json entry (registry_
  effect_type null) is flagged for the audit pipeline refresh.
- TEST MATRIX (C-owned): tests/test_cryptbloom_takedown_heal.py — 23
  tests (typed values + revision 3989109, missing-key fail-loud, takedown
  scan predicates, kill fight emits one heal per recipient at the
  takedown time, amount = 100 + 0.20 x holder AP, no-kill/malformed/
  dead-owner boundaries, recipients never the dead enemy, multi-takedown
  both-fire, one-packet-applied-once (1.75s is metadata), compiled
  representation, score-only parity, public serialization, coverage,
  determinism); +1 roster-holder parity test from the coordinator.

Provenance (RLM-2 A): item 3137; all four values certified — 100.0 and
0.20 are wiki+binary+atom backed (BaseHeal / HealAPRatio in
Items/3137), 1.75 is wiki+atom backed (no binary corroboration), 60.0 is
wiki+binary backed (no atom); revision 3989109 matches the audit (page
1619523, 2026-01-30, ready).  Trigger "Scoring a takedown against an
enemy champion while alive and within 3 seconds of damaging them" — the
3s window is binary-corroborated (TakedownWindow=3.0).  Named boundaries:
the 600-unit nova radius is NOT locally sourced and NOT modeled (every
selected roster member assumed hit); the cooldown's per-takedown vs
per-champion semantics are unsourced (60s carried on the packet, never
enforced — one takedown per holder per fight from the first defender
pair); the kill time is the LAST authored damage event (deterministic,
equals the kill moment only when the rotation ends at the kill — a true
kill-moment anchor is a recorded follow-up).

RLM-2 audits: A (provenance; all values certified + the radius/cooldown
boundaries), B (runtime; G1 parity failure + G2 target shadowing + G3
compile representation + G4 kill-time + G5 coverage + G6 cooldown — all
addressed as above or documented), C (tests; 23/23 pass pre-integration,
zero xfails; 2 pins updated by the coordinator for the G3 behavior
change + 1 roster-holder parity test).

Files: EDITED src/calculator/participant_timeline.py (shadowed loop
vars + panel target_ids), survival/compile.py (timed-heal representation),
item_coverage.py (modeled_state + utility dimensions), tests/test_cryptbloom_takedown_heal.py
(C-owned; +1 roster parity test, 2 pins updated).  item_effects.py
unchanged (values + revision already typed).

Gates: focused 449 (+6 pre-existing xfails), full pytest 5950 passed +
7 xfailed in 92.27s (5926 + 24 new), black clean (4 files), FULL-SRC
pylint 9.55/10 — unchanged from the documented pre-existing baseline
(17 pre-existing data_updater.py vendor E-artifacts; the participant_
timeline/compile R0801 flood is the documented pre-existing duplicate-
code class; zero new findings), atomize run TWICE with content-identical
results (generated_at only; 3137 atoms unchanged), golden 858 = prior
state — ZERO new differences from 3K (the heal never changes TDD; the
Muramana/Vayne line is the documented P3-3E fix), Catalyst resource-
ledger set re-run: 133 passed (3A intact).  Baseline NOT recaptured.

Follow-ups (recorded): a true kill-moment anchor (first event where
cumulative damage crosses target effective max health) instead of the
last-authored-event time — a bigger change, deferred; the 600-unit nova
radius needs game-file sourcing before it can be modeled; the stale
docs/wiki-full-entry-audit.json Cryptbloom entry (registry_effect_type
null) needs the audit pipeline refresh; the 60s cooldown semantics
(per-takedown vs per-champion) remain unsourced — one takedown per
holder per fight from the first defender pair is the model.


### 4.35 P1 Package 3L (2026-08-09): Gluttonous Greaves Slay omnivamp certification

Gluttonous Greaves' Slay passive is modeled on the Immortal Path contract
(identical cached passive; the boot-upgrade quest maps 3008 -> 3168).

- TYPED REGISTRY: ITEM_INPUT_OPTIONS["Gluttonous Greaves"] gains the
  slay_stacks option (int, 0..10, default 0, bonus_omnivamp_per_unit 0.6,
  source rev 4030444); ITEM_EFFECTS["Gluttonous Greaves"] gains the typed
  sustain values slay_omnivamp_per_takedown 0.6 / slay_max_stacks 10 /
  slay_max_omnivamp 6.0 + the source receipt (code-owned static keys).
- TYPED ACCESSOR: `gluttonous_greaves_slay_omnivamp(items, item_options)`
  projects the authored stacks to omnivamp percent (capped at
  slay_max_stacks), with no literal fallback; the accessor is wired into
  resolve_stat_effects' bonus_omnivamp sum (omnivamp_percent = base 4.0 +
  stacks x 0.6) and the item_state_receipts branch (state "slay_stacks",
  stacks, max_stacks, omnivamp, source_url, source_revision_id).
- NAMED BOUNDARY (takedown admission): the takedown stream is support-
  packet-only and CANNOT project into pre-fight stats (stats resolve
  before the fight) — the authored slay_stacks scenario option is the
  valid champion-takedown admission (the Immortal Path precedent).
  Gluttonous does NOT join TAKEDOWN_SCAN_SUPPORT_ITEMS; a kill fight
  authors no Slay support packets.
- HEALING APPLICATION: NOT receipt-only — the resolved omnivamp folds
  into the boot's omnivamp_percent and the engine prices vamp healing on
  its explicitly single-target attack/on-hit packets (the conservative
  omnivamp scope; area/pet/copied rows withheld with a named receipt),
  with the vamp carve-out and score/receipt parity shared with all vamp
  sources.
- COVERAGE: moved from _REVIEWED_STATS_ONLY (stats_only) to
  _STATEFUL_MODELED_ITEMS (modeled_state) with the Slay/omnivamp/stack
  wording + the withheld takedown-admission dimension; /api/boots and
  /api/config expose the option; optimizer/BIS unchanged (default 0
  stacks = byte-identical numbers).

Provenance (RLM-2 A): item 3008; 0.6 per champion takedown / 10-stack cap
/ 6% maximum all wiki + binary (OmnivampOnTakedown 0.006, MaxStacks 10)
+ atom backed (stack.gain [0.6, 10.0, 6.0] 1c7a2831810f1325); base 4%
omnivamp + 45 MS wiki+binary; revision 4030444 (page 1661999,
2026-06-16, ready) verified against the article index and cache fetch
time.  No duration/decay/cooldown sourced (stacks permanent).  Separation
clean: Gluttonous (3008) -> Immortal Path (3168) is the boot-upgrade quest
(identical Slay contract); Gunmetal Greaves (3172) has zero omnivamp;
Riftmaker's omnivamp is a different combat-stack trigger.

RLM-2 audits: A (provenance; all values certified + the 4%-omnivamp atom
gap + the stale simpleDescription flag), B (runtime; the scenario-option
precedent + the takedown-stream-can't-project-stats finding + the healing
application proof), C (tests; 19 PASS + 9 XFAIL pre-integration; the 9
xfails flipped/renegotiated by the coordinator to the stat-path contract
after B's finding).

Files: EDITED src/calculator/item_effects.py (option + registry + static
keys + accessor + resolve_stat_effects + item_state_receipts branch),
item_coverage.py (modeled_state wording), tests/test_gluttonous_greaves.py
(C-owned; 9 contract tests flipped/renegotiated + stale pins updated).

Gates: focused 806 (+2 known pre-existing app rate-limit flakes that pass
in isolation), full pytest 5976 passed + 7 xfailed in 90.37s (5950 + 26
new), black clean (3 files), FULL-SRC pylint 9.55/10 — unchanged from the
documented pre-existing baseline (17 pre-existing data_updater.py vendor
E-artifacts; zero new findings), atomize run TWICE with content-identical
results (generated_at only; 3008 atoms unchanged), golden 858 = prior
state — ZERO new differences from 3L (default-0 stacks keeps the
omnivamp/heal numbers byte-identical; the Muramana/Vayne line is the
documented P3-3E fix), Catalyst resource-ledger set re-run: 133 passed
(3A intact).  Baseline NOT recaptured.

Follow-ups (recorded): the base 4% omnivamp stat has no typed key (the
stats.py omnivamp path is not fail-closed like lifesteal) — typing all
cached omnivamp items is a separate stretch; the 3008 simpleDescription
is a stale cache artifact (no numeric impact); the
docs/wiki-full-entry-audit.json entry needs the audit pipeline refresh
(registry_effect_type null); the takedown-driven stack admission would
need post-fight stat machinery (out of scope, named boundary).


### 4.36 P1 Package 3M (2026-08-09): Doran's Helm Helping Hand minion-only damage certification

Doran's Helm's Helping Hand ("Basic attacks deal 5 bonus physical damage
on-hit against minions") is now TYPED and RECEIPT-ONLY, mirroring the
Tear of the Goddess Helping Hand precedent (§4.22).  The acceptance's
conditional was resolved TRUE: the 1v1 champion fight model has no
representable minion target (no target-kind field on FightConfig/
FightState/DamageInputs; scenario enemies are ChampionLoadouts; damage
events carry no target kind), so the branch FAILS CLOSED with a named
boundary and is NEVER an on-champion packet.

- TYPED REGISTRY: ITEM_INPUT_OPTIONS["Doran's Helm"] carries the source
  receipt (wiki rev 4034679, page 1726898, status ready); ITEM_EFFECTS
  gains the code-owned stat_conversion entry with
  helping_hand_minion_damage 5.0 (+ source comment); the static key is
  registered in _STATIC_VALUE_KEYS_BY_ITEM and rides the shared
  stat_conversion metadata key list.
- ATOM-BACKED ACCESSOR: `dorans_helm_helping_hand_minion_damage()` reads
  the typed value and validates it against the pinned catalog atoms
  (damage.basic_attack f991d9ce51cb971b / damage.on_hit 0d448c6a3c15051e
  / damage.physical 9780d84ddfec7afe, all [5.0] flat, source
  "Doran's Helm.passives[0].branches[0]") — a stale static literal
  diverging from the catalog fails closed with a ValueError naming the
  atom hash (monkeypatch test).
- RECEIPT: item_state_receipts emits a "helping_hand_minion_only" row
  (helping_hand_minion_damage 5.0, helping_hand_minion_only True,
  helping_hand_boundary naming the champion-model boundary,
  source_url + source_revision_id 4034679 from the input-options receipt)
  — the ONLY observable the branch adds.
- NAMED BOUNDARY (target admission): no classified minion target exists
  in the 1v1 model, so the 5 bonus physical damage is never compiled
  (resolve_damage_effects per_hits stay empty for Helm), never enters
  the champion breakdown, and changes zero fight numbers.  Champion
  targets, abilities, item procs, and unknown/malformed target kinds
  receive no invented damage.  Resistance handling, basic-attack-only
  wording, and physical-not-true classification are pinned in the test
  matrix as the "awaiting P3-3M minion target gate" xfails (a future
  minion-target model must satisfy them).
- COVERAGE: item_model_coverage special-cases Doran's Helm BEFORE the
  ITEM_EFFECTS branch -> status stats_only (optimizer_eligible +
  calculation_eligible True) with the reason naming the minion-only +
  receipt-only boundary (the plain ITEM_EFFECTS branch would have
  over-claimed "represented by the fight model").  The stale
  _REVIEWED_STATS_ONLY reason is superseded.

Provenance (RLM-2 A): item 1120 = binary itemID 1120 = "Doran's Helm"
verified in both roots; 5 damage wiki-backed (branch + riotDescription)
AND binary-backed (Items/1120 BonusDamageToMinions=5.0) AND atom-backed
(three 5.0 atoms, hashes recomputed = match); minion-only restriction =
wiki wording ("against minions") + binary field name; physical type =
wiki + atom (binary silent); basic-attack-only = wiki + atom only (gap
G1 recorded); stats 150 HP / 8 armor / 8 MR + price 450 both roots;
revision receipt 4034679 (page 1726898, 2026-06-23, ready) lives in
docs/wiki-full-entry-audit.json; separation clean vs Ring (1056) /
Shield (1054) / Blade (1055) / Cull (1083) / Tear (3070 — the SAME
Helping Hand passive, already modeled receipt-only).

RLM-2 audits: A (provenance; all values certified + gaps: basic-attack-
only wiki-only, no minion atom restriction, stale legacy item-atoms dir),
B (runtime; no target-kind taxonomy, Tear precedent, coverage ordering
hazard, score/parity zero-impact by construction), C (tests; 17-test
matrix 8 PASS / 9 XFAIL pre-integration; 3 flipped to PASS + 1
monkeypatch test added; 6 remain xfail on the genuinely-absent minion
target gate).

Files: EDITED src/calculator/item_effects.py (input-options receipt +
offline entry + static keys + atom constants + accessor + item_state_
receipts branch), item_coverage.py (special-case branch), tests/
test_dorans_helm_minion_damage.py (C-owned; 3 xfails flipped + 2 receipt
pins renegotiated + monkeypatch test).

Gates: focused 872 + new file 12 passed / 6 xfailed, full pytest 5988
passed + 13 xfailed in 87.05s (5976 + 12 new), black clean (3 files),
FULL-SRC pylint 9.55/10 — UNCHANGED from the documented baseline (17
pre-existing E/F artifacts incl. the data_updater.py vendor set; the
R0912 too-many-branches on item_model_coverage is pre-existing at
15/12; the R0915 too-many-statements transient from the first draft was
removed — 51/50 -> 50, rating +0.00), atomize run TWICE with
content-identical results (generated_at only), golden 858 = prior state
— ZERO new differences from 3M (the receipt-only branch changes no
damage numbers; the Muramana/Vayne + Briar/KSante lines are prior
documented packages), Catalyst resource-ledger set re-run: 133 passed
(3A intact).  Baseline NOT recaptured.

Follow-ups (recorded): a classified minion target (target-kind field +
scenario admission + per-kind resist model) is the prerequisite for the
6 pinned minion-gate tests — out of scope, named boundary; the
basic-attack-only constraint is wiki/atom-only evidence (binary silent);
Ring/Shield carry the same Helping Hand passive but their receipts do
not pin it (same fix shape, out of 3M scope); the public /api/calculate
response does not serialize item_state_receipts (raw-result/test-only).


### 4.37 P1 Package 3N (2026-08-09): Ionian Boots of Lucidity Ionian Insight summoner spell haste certification

Ionian Boots of Lucidity's Ionian Insight ("Gain 10 summoner spell
haste") is now TYPED and RECEIPT-ONLY.  The acceptance's conditional was
resolved TRUE: the engine has NO summoner-spell action model (no
summoner cast/cooldown/haste state on FightConfig/FightState/DamageInputs,
the scheduler, the timeline, runes, or champions; Unsealed Spellbook and
Zoe's spell-shard mimics are the architecture's own admissions), so the
branch FAILS CLOSED with a named boundary and is NEVER an ability-haste
packet.

- TYPED REGISTRY: ITEM_INPUT_OPTIONS["Ionian Boots of Lucidity"] carries
  the source receipt (wiki rev 4022246, page 41221, status ready);
  ITEM_EFFECTS gains the code-owned stat_conversion entry with
  summoner_spell_haste 10.0 (+ source comment); the static key is
  registered in _STATIC_VALUE_KEYS_BY_ITEM and the shared
  stat_conversion metadata key list.
- ATOM-BACKED ACCESSOR: `ionian_insight_summoner_spell_haste()` reads the
  typed value and validates it against the pinned catalog atom
  (stat.haste 1e775793fa61a40e, [10.0] flat, source
  "Ionian Boots of Lucidity.passives[0].branches[0]", evidence
  "@kw:summoner spell haste" — the atomizer maps the summoner-spell-haste
  keyword onto the shared stat.haste atom, so the receipt pins the exact
  record via its hash); a diverging registry literal fails closed with a
  ValueError naming the atom hash (monkeypatch test).
- RECEIPT: item_state_receipts emits an "ionian_insight_summoner_spell_haste"
  row (summoner_spell_haste 10.0, summoner_spell_haste_only True,
  summoner_spell_haste_boundary naming the absent-summoner-state boundary,
  source_url + source_revision_id 4022246 auto-derived) — the ONLY
  observable the branch adds.
- ABILITY-HASTE SEPARATION (the core pin): the item's 10 ABILITY HASTE
  (stats.abilityHaste.flat) and 10 SUMMONER SPELL HASTE are separate
  channels (cache stats block vs passive; riotDescription <stats> vs
  <passive>; binary mAbilityHasteMod 10.0 vs SummonerHaste 10.0; atoms
  stat.ability_haste 305818c346391945 vs stat.haste 1e775793fa61a40e).
  The fight model already prices the 10 ability haste (verified: Cass E
  cast count shifts with the stat); the passive adds NO cooldown
  reduction, NO damage, NO auto change — with-vs-without fights are
  bit-identical, and the timed delta equals exactly the +10-stat
  prediction (30s Ahri: W 6->7 casts == ceil(30/effective_cooldown)).
  A summoner-haste leak (haste 20) would predict W=8/Q=6 and is rejected.
- NAMED BOUNDARY (absent summoner state): no summoner fields exist in
  damage events/breakdown/timeline; the receipt row is the ONLY summoner
  surface.  The Flash/Ignite point-9 pin (300s Flash -> 272.73s,
  180s Ignite -> 163.64s, 9.09% faster under the typed 10) is now a
  PASSING arithmetic contract for the future summoner-spell model.
- COVERAGE: item_model_coverage's new _RECEIPT_ONLY_BOUNDARY_REASONS
  dict (Doran's Helm + Ionian Boots) short-circuits BOTH the
  ITEM_EFFECTS and ITEM_INPUT_OPTIONS branches (which would over-claim
  modeled_effect/modeled_state) -> status stats_only (optimizer_eligible
  + calculation_eligible True) with a reason naming the receipt-only
  summoner-spell-haste boundary.  The stale _REVIEWED_STATS_ONLY prose is
  superseded.

Provenance (RLM-2 A): item 3158 = binary itemID 3158 = "Ionian Boots of
Lucidity" (unique, price 900); 10 summoner spell haste wiki-backed
(branch + riotDescription) AND binary-backed (Items/3158 SummonerHaste
10.0) AND atom-backed (stat.haste 1e775793fa61a40e, hash recomputed);
10 ability haste + 45 MS stat-backed (binary mAbilityHasteMod 10.0 /
mFlatMovementSpeedMod 45.0); revision receipt 4022246 (page 41221,
2026-05-24, ready, verdict out_of_scope); separation clean vs Crimson
Lucidity (3171 — same-named Riot passive but 20 haste, the item_source
naming ACK is about 3171 not the boots) and Jarvan I's (1111 — 10 haste,
distributed-boots upgrade); no other summoner-spell-haste representation
in champions/runes/golden.  Binary-only note: FeatsHaste 5.0 on 3158 is
not mirrored in cache/atoms (future package).

RLM-2 audits: A (provenance; all values certified + the FeatsHaste flag),
B (runtime; NO summoner-spell machinery — conclusive; the 10 AH is
already priced end-to-end; the coverage-ordering hazard demonstrated
live; byte-stability proven: stat_conversion is a registered dispatch
no-op and the golden snapshot never records receipts), C (tests;
20-test matrix 15 PASS / 5 XFAIL pre-integration; all 5 flipped to PASS;
2 fail-closed pins renegotiated to the receipt surface).

Files: EDITED src/calculator/item_effects.py (input-options receipt +
offline entry + static keys + metadata key + atom constants + accessor +
item_state_receipts branch), item_coverage.py (_RECEIPT_ONLY_BOUNDARY_
REASONS refactor: the 3M Helm branch + the 3N Ionian branch merge into
one dict-driven branch — keeps item_model_coverage under the pylint
R0915 threshold), tests/test_ionian_boots_summoner_haste.py (C-owned;
5 xfails flipped + 2 receipt pins renegotiated).

Gates: focused 699 + new file 20 passed, full pytest 6008 passed + 13
xfailed in 90.85s (5988 + 20 new), black clean (3 files), FULL-SRC
pylint 9.55/10 — UNCHANGED from the documented baseline (17 pre-existing
E/F artifacts; R0912 on item_model_coverage pre-existing at 15/12; the
R0915 transient from the first draft was removed by the dict merge —
52/50 -> 50, rating +0.00), atomize run TWICE with content-identical
results (generated_at only), golden 858 = prior state — ZERO new
differences from 3N (receipt-only changes no fight numbers; the
Muramana/Vayne + Briar/KSante lines are prior documented packages),
Catalyst resource-ledger set re-run: 133 passed (3A intact).  Baseline
NOT recaptured.

Follow-ups (recorded): a summoner-spell action model (cast scheduling +
cooldowns + selection UI, per Unsealed Spellbook's own rejection note)
is the prerequisite for the point-9 Flash/Ignite pin to become a real
timing effect — out of scope, named boundary; Crimson Lucidity (3171,
20 haste) and Jarvan I's (1111) share the same passive — same fix shape,
out of 3N scope; FeatsHaste 5.0 (binary-only) unpinned; the public
/api/calculate response does not serialize item_state_receipts.


### 4.38 P1 Package 3O (2026-08-09): Gunmetal Greaves Noxian Gait Riot-only branch certification

Gunmetal Greaves' Noxian Gait ("Attacks against Champions grant Move
Speed On-Hit decaying over 2 seconds.") is now a TYPED NAMED BOUNDARY.
The acceptance's conditional was resolved PARTIAL: the runtime HAS
movement-packet machinery (Phage Rage per-auto movement events, Fleet
Footwork / Stormraider's), but the effect is NOT representable — the
wiki cache has NO passive branch (passives=[], noEffects=true; audit rev
4013706 records effect_count 0 — the Wiki page removed the effect in
V26.01), the riotDescription carries NO magnitude, and the fight model
has NO decaying-movement kernel (movement events are flat amount +
duration; a flat packet would misrepresent "decaying").  The magnitude
exists ONLY in the gitignored client binary (Items/3172 MeleeMS 0.15 /
RangedMSMultiplier 0.667 / Duration 2.0, MSAmount calc, 3172Speed spell)
— wiki-absent, atom-less, and unmodelable without a decay kernel, so it
stays UNSOURCED and untyped.

- TYPED BOUNDARY KEYS (code-owned statics in the existing sustain entry,
  one record per item): noxian_gait_decay_seconds 2.0 (riotDescription
  "decaying over 2 seconds" + binary Duration=2.0 — both channels),
  noxian_gait_champions_only True (riotDescription "Attacks against
  Champions"), noxian_gait_magnitude_unsourced True (the acceptance's
  "no guessed magnitude" is a typed, fail-loud flag).  Static keys
  registered in _STATIC_VALUE_KEYS_BY_ITEM.
- RECEIPT: item_state_receipts emits a "noxian_gait_boundary" row
  (decay 2.0, champions_only True, magnitude_unsourced True, boundary
  string naming Riot-only + missing magnitude + no decaying-movement
  model, source_url + source_revision_id 4013706 auto-derived from the
  new ITEM_INPUT_OPTIONS source-only entry) — the ONLY observable added.
- ORDINARY STATS PARITY: the 40% AS + 45 MS + 5% lifesteal flow
  unchanged (equip delta EXACTLY {attack_speed +0.25, bonus_attack_speed
  +40, lifesteal_percent +5, move_speed +45}; AD/AH/AP and every other
  stat unchanged); with-vs-without fights bit-identical modulo the
  boundary receipt row; Noxian Gait adds NO damage/AS/LS/AH/TDD and no
  movement packet (resolve_damage_effects per_hits stay empty; zero
  movement keys in events/breakdown/timeline).
- FAIL-CLOSED: fabricated Noxian Gait options are rejected ("Unknown
  option for Gunmetal Greaves"); empty options are the absent state
  (no-op); a fabricated magnitude key read raises KeyError naming
  item+key.
- COVERAGE: KEEP modeled_effect (the typed sustain IS a modeled fight
  effect — heal_lifesteal breakdown row; the sustain class is
  modeled_effect; moving to stats_only would downgrade the honest
  lifesteal claim and flip test_item_coverage.py + the umbrella audit).
  Reason tightened: names the unsourced magnitude, the no-decaying-
  movement-model boundary, the noxian_gait_boundary receipt, and the
  still-applied stats; "Noxian Gait" + "out of scope" substrings kept
  (existing pins stay green).
- ORDINARY-STATS ATOM RECEIPTS (unchanged): economy.total 1100
  11819bca31abd870, stat.attack_speed 40 819c15a12e066e1e, stat.movespeed
  45 3caf1eb28e932b54; no lifesteal atom (cache flat=0, percent=5.0
  skipped by the atomizer) and NO Noxian atom (no wiki branch — atoms
  derive from the wiki cache only).

Provenance (RLM-2 A): item 3172 = binary itemID 3172 = "Gunmetal
Greaves" (unique; tier 3 BOOTS, 1100 gold, buildsFrom 3006 Berserker's);
40% AS (mPercentAttackSpeedMod 0.40), 45 MS (mFlatMovementSpeedMod 45),
5% lifesteal (cache stats.lifesteal.percent 5.0 + mPercentLifeStealMod
0.05 + typed registry rev 4013706); zero omnivamp separation verified;
Noxian Gait wiki branch ABSENT (rev 4013706 records V26.01 removal),
riotDescription magnitude-less; binary magnitude exists (MeleeMS 0.15 /
RangedMSMultiplier 0.667 / Duration 2.0) but nothing consumes it;
audit page 1675881 / rev 4013706 / 2026-04-29 / ready / effect_count 0;
separation clean vs Crimson Lucidity 3171 ("Noxian Haste" is a
DIFFERENT passive — 20 summoner haste + ally MS) and Berserker's 3006;
"old Gunmetal" = stale Feats-era 1600-price record.

RLM-2 audits: A (provenance; all values certified + TWO caveats: the
reconciliation doc's "the game file (16.15) has no Noxian Gait branch"
sentence is CONTRADICTED by the repo's own binary evidence root; the
sell-price 440-cache-vs-770-ddragon discrepancy is systematic across
boots), B (runtime; partial representability — Phage precedent exists
but no decaying-movement kernel; magnitude wiki-absent; byte-stability
proof: golden snapshots totals+breakdown keys only), C (tests; 19-test
matrix 17 PASS / 2 XFAIL pre-integration; 1 xfail flipped (receipt row)
+ 6 pins renegotiated to the typed surface; 1 xfail remains on the
genuinely-absent decaying-movement model).

Files: EDITED src/calculator/item_effects.py (Gunmetal entry boundary
keys + comment, static keys, ITEM_INPUT_OPTIONS source-only entry,
item_state_receipts noxian_gait_boundary branch), item_coverage.py
(reason tightening, branch statement count unchanged), tests/
test_gunmetal_greaves_riot_branch.py (C-owned; 1 xfail flipped + 6 pins
renegotiated).

Gates: focused 729 + new file 18 passed / 1 xfailed, full pytest 6026
passed + 14 xfailed (6013 + 18 new... prior 6008 + 18 = 6026; xfailed 13
-> 14 with the movement-state pin), black clean (3 files), FULL-SRC
pylint 9.55/10 — UNCHANGED from the documented baseline (17 pre-existing
E/F artifacts; no new findings; item_model_coverage statement/branch
counts unchanged), atomize run TWICE with content-identical results
(generated_at only), golden 858 = prior state — ZERO new differences
from 3O (receipt-only changes no fight numbers), Catalyst resource-ledger
set re-run: 133 passed (3A intact).  Baseline NOT recaptured.

Follow-ups (recorded): a decaying-movement model (time-varying movement
kernel + per-auto movement proc consumption) is the prerequisite for the
single pinned movement-state xfail — out of scope, named boundary;
docs/item-source-reconciliation.md's "16.15 binary has no Noxian Gait
branch" sentence is contradicted by the repo's own data/bin/items.bin.json
(MeleeMS/RangedMSMultiplier/Duration present) — factual doc correction
deferred (docs file not in the 3O changed-path set); the boots'
sell-price 440-vs-770 discrepancy is systematic (economics-sourced nulls
cache_sell for all boots); the stale "Mobility and Tenacity"
simpleDescription label is text-only.


### 4.39 P1 Package 3P (2026-08-09): Guardian Angel Rebirth resurrection parity certification

Guardian Angel's Rebirth is now CERTIFIED with full score/receipt parity
and a lethal-anchored resurrection window.  The acceptance's parity
conditional was resolved: both adapters already drove the shared survival
kernel, so the score and receipt paths carry identical revive rows; the
two real gaps found were (A) the resurrection window was NOT anchored to
the lethal hit (a pre-lethal packet + 4.0s could revive EARLY — e.g.
death at 9.981, revive at 10.654 = only 0.673s of stasis), and (B) GA
still sat in COMPILED_WALK_UNREPRESENTABLE_ITEMS even though the
compiled kernel implements revive_candidate_actions (Zac's champion
revive already rode the compiled path).

- LETHAL-ANCHORED WINDOW (behavior fix): the kernel now skips any revive
  candidate that fires before death_time + delay (new typed `delay` field
  on SurvivalAction, authored by both adapters from the sourced
  revive_delay; skip reason "revive_window_not_elapsed").  The lethal
  packet's own candidate applies at exactly death + delay, so the full
  sourced stasis elapses even in sustained fights (GA: death 9.981 ->
  revive 13.981; Anivia: death 4.312 -> revive 10.312).  Champions share
  the fix (Anivia/Zac/Zilean — their contracts are also lethal-anchored);
  the e9-e8-anivia-rebirth corpus pin was re-probed and re-pinned
  (revive_time 6.0 -> 10.312, death_time 11.858 -> 15.091) per the
  corpus test's own re-pin rule.
- COMPILED PATH (Part A): "Guardian Angel" removed from
  COMPILED_WALK_UNREPRESENTABLE_ITEMS (compile.py) + the stale phase-2
  comment corrected; GA now compiles like Zac (compiled context clean,
  panels non-empty, uncompilable False) with byte-identical results
  (proven by the new parity test in C's matrix).  Removes the
  per-evaluation fallback for GA roster enemies.
- TYPED REGISTRY: the GA entry gains revive_mana_ratio 1.0 (the triply
  sourced 100% max-mana restore — wiki branch + riotDescription + binary
  mEffectAmount[3]=1.0), one_use True, source_url + source_revision_id
  4046863 (2026-07-28 — NEWER than the stale audit JSON row 4001358,
  recorded as a follow-up); static keys registered.  Existing
  revive_health_ratio 0.50 / revive_delay 4.0 / revive_cooldown 300.0
  unchanged (4/4 sourced: wiki + riot + binary mEffectAmount [0.5, 4.0,
  300.0, 1.0] + code).
- ATOM-TIED ACCESSOR: guardian_angel_rebirth_declaration() validates the
  typed declaration against the crammed Rebirth atom heal.flat
  83706c231e0d8fee ([4.0, 50.0, 100.0, 300.0], units [s, percent,
  percent, s]) — the parser crammed all four numbers into every
  keyword-matched atom, so the declaration maps ratio*100 back to the
  atom's percent values and fails closed naming the hash on divergence.
- RECEIPT ROW: item_state_receipts emits exactly one "rebirth" row
  (revived True, revive_health_restored = 0.5 x base_health [new
  base_health parameter], delay 4.0, cooldown 300.0, one_use True, mana
  ratio 1.0, source revision 4046863 via the new ITEM_INPUT_OPTIONS
  source-only entry) + three named boundaries: the 100% max-mana restore
  (the survival ledger has no mana pool — typed, never applied), the
  300s cooldown (modeled fights <=30s; the one-use revive_used gate is
  the operative rule), and the 4s stasis (modeled as the dead state:
  incoming window damage skipped as overkill, holder authors no outgoing
  actions until the revive applies).
- SCORE/RECEIPT PARITY: both paths (coupled score surface and receipt
  walk) return IDENTICAL survival rows through the shared kernel
  (revived / revive_time / revive_health_restored / revive_source /
  first_death_time / death_time / terminal_phase); the legacy pair
  scorer (run_fight score_only) carries NO survival state — that is the
  named fail-closed boundary (pinned: target_* survival keys absent).
- NO OUTGOING TDD: the revive adds no damage anywhere and is NOT healing
  (healing_received stays 0.0 while restore > 0 — a state transition);
  ordinary +55 AD / +45 armor stats unchanged (equip delta EXACTLY
  {attack_damage 55, armor 45, bonus_* 55/45}).
- COVERAGE: unchanged posture (stats_only attacker-side / modeled
  target-side — the revive changes the TARGET's durability, never the
  holder's outgoing TDD); the existing reason already names the survival
  ledger.  outcome_dimensions ("revive",) unchanged.

Provenance (RLM-2 A): item 3026 = binary itemID 3026 (unique, tier 3
LEGENDARY, 3200 gold = Steel Sigil 2019 + B.F. Sword 1038 + 800 combine);
stats 55 AD / 45 armor verified 3/3 (cache, vendor raw, binary
mFlatPhysicalDamageMod/mFlatArmorMod); Rebirth values verified 4/4
(wiki branch, riotDescription, binary mEffectAmount [0.5, 4.0, 300.0,
1.0], code) — 50% BASE health, 4s delay, 300s cooldown (starts after
resurrection ends), 100% MAX mana (was NOT modeled — now typed + named
boundary); one-use + stasis (invulnerable/untargetable/unable-to-act)
sourced by wiki+riot keyword and enforced via revive_used + the dead
state; atoms: 3 clean (economy.total 3200 ae0fd5dcd4e41f18, armor 45
990c9a8c4255f26c, AD 55 4948674c3d1c2121) + 4 crammed multi-value atoms
(heal.flat 83706c231e0d8fee etc.) backing no single value; separation
clean vs champion revives (Anivia 6s/240s/full max HP; Zac 4s/300s/50%
MAXIMUM health — different basis than GA's 50% BASE; Zilean 3s/
120-90-60s) and vs Sterak's (no revive) / Zhonya (stasis without revive).

RLM-2 audits: A (provenance; two follow-ups: the stale audit JSON row
4001358 vs code 4046863; the unmapped 5th mEffectAmount element),
B (runtime; parity already satisfied via the shared kernel — rule 5
clean, no literals; the structural gaps: the stale compiled blocklist
entry + the missing receipt row + the unanchored window), C (tests;
29-test matrix 24 PASS / 5 XFAIL pre-integration; 3 xfails flipped +
3 pins renegotiated to the anchored/compiled contract; 2 xfails remain:
explicit stasis-state authoring (dead-state implements the observables)
and the >fight-length 300s cooldown re-arm (one-use is the operative
rule)).

Files: EDITED src/calculator/item_effects.py (entry keys + static keys
+ ITEM_INPUT_OPTIONS source-only entry + declaration accessor +
rebirth receipt branch + base_health parameter), survival/actions.py
(delay field + mapping), survival/transitions.py (lethal-anchored
window gate), survival/compile.py (blocklist removal + comment +
candidate delay), participant_timeline.py (candidate delay),
item_coverage.py (no status change), tests/test_guardian_angel_
resurrection.py (C-owned), tests/test_e9_corpus.py + data/practice-
corpus/scenarios.json (the e9-e8-anivia-rebirth re-pin for the anchored
window).

Gates: focused 773 + new file 27 passed / 2 xfailed, full pytest 6053
passed + 16 xfailed in 128.91s (6026 + 27 new), black clean (8 files),
FULL-SRC pylint 9.55/10 — UNCHANGED from the documented baseline (17
pre-existing E/F artifacts; zero new findings), atomize run TWICE with
content-identical results (generated_at only), golden 858 = prior state
— ZERO new differences from 3P (the anchored window only changes fights
where a revive fires; the golden paths carry no survival-ledger
revives; the Muramana/Vayne + Briar/KSante lines are prior documented
packages), Catalyst resource-ledger set re-run: 133 passed (3A intact).
Baseline NOT recaptured.

Follow-ups (recorded): re-capture the audit JSON row for Guardian Angel
to revision 4046863 (the row still says 4001358; article-index cannot
arbitrate); the 5th binary mEffectAmount element (0.0) has no local
source mapping; explicit stasis-state authoring (stasis_until/stasis_
source fields) would make the 4s window visible as a state rather than
the dead-state implementation — not required by the observables; the
300s cooldown re-arm cannot be expressed in fights <=30s (one-use
gate).


### 4.40 P1 Package 3Q (2026-08-09): Force of Nature compiled-walk + optimizer certification

Force of Nature's Steadfast is now CERTIFIED on the compiled score path
with full parity and a corrected per-instance stack cadence.

- PER-INSTANCE CADENCE (behavior fix): the sourced rule is "Once per
  cast instance, each incoming basic attack, ability, or item effect can
  only generate 1 stack of Steadfast from their damage every 1 second" —
  every cast instance carries its own 1-second throttle, so DIFFERENT
  instances stack within a second and the SAME instance re-stacks at 1s
  intervals.  The previous kernel gate was a GLOBAL 1/s across all
  instances plus a one-stack-per-window per-instance cache (under-granted
  vs the game).  The kernel now tracks per-cast-key last-grant times
  (state field force_cast_last_times) with the all-at-once expiry anchor
  unchanged (lazy reset on the next qualifying packet); both adapters
  share the kernel, so parity is preserved by construction.
- COMPILED PATH (certification): the compile.py blocklist entry removed;
  the compiled kernel now stages Steadfast exactly like the receipt: the
  score context stamps each engine event with ability_instance (from the
  cast timeline, mirroring _pair_packet's enrichment) and the pair's
  finite final effective_armor/effective_mr baselines (for the dynamic
  repricing); compile.add_packet + add_engine_result's dict branch carry
  the three metadata fields into SurvivalAction; the TUPLE-ledger branch
  fails closed with a new named receipt "tuple_ledger_stack_metadata"
  when the defender arms a stack machine (tuple rows omit the metadata
  the machine needs).  Roster-side FoN holders no longer poison the
  compiled context (search-invariant scan passes); main-holder
  evaluations ride the compiled path (panels non-empty, uncompilable
  False) with byte-identical results.
- REPRICING RULE (pinned): prospective per packet, inclusive of the
  reaching packet — update_combat_state runs before the packet's damage
  flow, so the 8th (reaching) packet is already mitigated at
  baseline+70; earlier packets are never re-mitigated; a packet without
  _baseline_effective_mr is never silently repriced
  (dynamic_resistance_unavailable receipt).  The ordinary +400 HP /
  +55 MR / +4% MS stats are separate and always applied.
- RECEIPT ROW: item_state_receipts emits exactly one "steadfast" row
  (max_stacks 8, duration_seconds 7.0, interval_seconds 1.0,
  immobilize_stacks 2, bonus_magic_resistance 70.0,
  bonus_move_speed_percent 6.0, source_url + source_revision_id 4016272
  passed explicitly from the code-owned _FORCE_OF_NATURE_SOURCE) + two
  named boundaries: the 6% bonus move speed at max stacks is declared
  metadata only (neither walk authors a movement event — the "movement"
  coverage dimension stays descriptive), and the duration refresh on
  DEALING damage to the stacker is unmodeled (only incoming champion
  magic damage refreshes — conservative under-grant).
- COVERAGE: item_model_coverage now returns the specific Steadfast
  reason (new _MODELED_EFFECT_REASONS dict consulted by the ITEM_EFFECTS
  branch — zero net statement/branch change, keeping item_model_coverage
  under the pylint thresholds) instead of the generic "Damage-relevant
  effects are represented by the fight model."; the target-side reason
  is tightened with the same boundaries; posture unchanged
  (modeled_effect, optimizer_eligible + calculation_eligible True,
  outcome_dimensions ["movement","defense"]); optimizer/BIS scores
  UNCHANGED by certification (identical numbers via the shared kernel;
  the 70 MR was already priced through the receipt walk).
- FAIL-CLOSED: fabricated FoN item options rejected ("Unknown item
  option target"); missing/malformed typed values raise naming
  item+key; absent FoN produces no stacks and no receipt row; non-champ
  / physical / zero-damage / reactive magic packets gain no stacks;
  immobilize +2 rides a QUALIFYING magic packet's immobilized marker
  (pure-CC or physical immobilizes grant nothing — named conservative
  boundary).

Provenance (RLM-2 A): item 4401 = binary itemID 4401 (unique, tier 3
LEGENDARY, 2800 = 2050 + 750 combine); stats 400 HP / 55 MR / 4% MS
verified cache+binary; Steadfast values 7s / 8 max / 1s interval / +2
immobilize / +70 MR / +6% MS verified 4/4 (wiki branch, riotDescription,
binary mDataValues BuffDuration 7.0 / MaxStacks 8.0 / StackRefreshTimer
1.0 / ImmobilizeStacks 2.0 / BonusMagicResist 70.0 / MoveSpeed 0.06,
code statics); revision 4016272 (page 3590, 2026-05-10, ready) ==
code-pinned _FORCE_OF_NATURE_SOURCE == test pin (NO drift); atoms: 3
clean (economy.total 2800 bc11034caf0e2ef3, health 400 85e70be907a4a3b6,
magic_resistance 55 8a08542f3b171560 — evidence polluted with the
passive kw) + 6 crammed 7-value atoms (control.immobilize, control.
movement_speed, damage.basic_attack, damage.magic, damage.reduction,
stack.gain) backing no single value; 4% MS stat has NO atom (flat-only
atomizer); separation clean vs Jak'Sho (voidborn — same stack machine,
sibling package still blocklisted), Randuin's, Kaenic, Maw, Gargoyle,
Abyssal; zero omnivamp/lifesteal.

RLM-2 audits: A (provenance; gaps: crammed atoms, 4% MS atom missing,
outgoing-refresh unmodeled, immobilize gate conservative, 6% MS
metadata-only, stale simpleDescription, no source keys in the registry
entry — receipt rides defensive_effects), B (runtime; receipt machine
live-verified; compiled gap = 2 metadata fields across 4 edit sites +
tuple fail-closed; the 6 mismatches: blocklist fallback, un-blocklist
divergence without the fix, movement payload unapplied on BOTH paths,
dealing-refresh unmodeled, stale fight-end count, packet-conditional
+2, cadence gate stricter than game, triggering-packet over-mitigation,
coverage overstatement), C (tests; 35-test matrix 32 PASS / 3 XFAIL
pre-integration; all 3 flipped (compiled panels, coverage reason,
receipt row); 4 pins renegotiated (cadence x2, expiry x1, enemy-poison
x1); 0 xfail remain).

Files: EDITED src/calculator/survival/transitions.py (per-instance
cadence), survival/actions.py (compiled_damage_action metadata fields),
survival/compile.py (blocklist removal + tuple_ledger_stack_metadata
guard + metadata carry), survival/receipt_state.py (force_cast_last_times
template), participant_timeline.py (score-context stamping +
defender_stack_armed), item_effects.py (steadfast receipt row),
item_coverage.py (_MODELED_EFFECT_REASONS + target wording),
defensive_effects.py (assumption text), tests/test_force_of_nature_
compiled_parity.py (C-owned; 3 xfails flipped + 4 pins renegotiated).

Gates: focused 751 + new file 35 passed (2 known pre-existing app
rate-limiter flakes in batch context, pass isolated), full pytest 6088
passed + 16 xfailed in 126.40s (6053 + 35 new), black clean (9 files),
FULL-SRC pylint 9.55/10 — UNCHANGED from the documented baseline (17
pre-existing E/F artifacts; zero new findings; item_model_coverage stays
under the R0915 threshold via the dict-driven reason), atomize run TWICE
with content-identical results (generated_at only), golden 858 = prior
state — ZERO new differences from 3Q (the cadence fix only changes
survival-walk stack fights; the golden baseline has no FoN stack
scenarios; the Muramana/Vayne + Briar/KSante lines are prior documented
packages), Catalyst resource-ledger set re-run: 133 passed (3A intact).
Baseline NOT recaptured.

Follow-ups (recorded): Jak'Sho's Voidborn Resilience shares the stack
machine and remains blocklisted pending its own package (the
defender_stack_armed tuple guard already covers it); the 6% bonus move
speed could become an applied movement event (Stormraider pattern +
score-mode fail-closed note) — out of scope, named boundary; the
dealing-damage refresh needs per-target source tracking — named
boundary; the crammed 7-value atoms and the missing 4% MS atom are
atomizer-domain gaps; the simpleDescription "max Health Regeneration"
label is stale text-only; the audit JSON + _FORCE_OF_NATURE_SOURCE
revision (4016272) has no drift.


### 4.41 P1 Package 3R (2026-08-09): Jak'Sho, The Protean compiled-walk + optimizer certification

Jak'Sho's Voidborn Resilience is now CERTIFIED on the compiled score path
with full parity, plus two pre-existing compiled-path defects repaired.

- COMPILED PATH (certification): the compile.py blocklist entry removed;
  the 3Q infrastructure already stamps ability_instance + finite
  effective_armor/effective_mr baselines for stack-armed defenders, and
  the shared kernel's voidborn branch (one stack per second of combat
  time — `stacks = min(5, floor(time / 1.0))` per qualifying packet,
  events on change only; cap payload multiplies BONUS armor and BONUS
  magic resistance by 0.30 into the dynamic deltas; prospective
  repricing inclusive of the reaching packet, physical -> armor delta
  and magic -> MR delta) runs on both adapters.  Main-holder and
  roster-enemy-holder evaluations now ride the compiled path (panels
  non-empty, uncompilable False) with byte-identical results.
- DEFECT 1 (pre-existing crash, repaired): the score context enriched
  engine events with `dict(event)` UNGATED, so a tuple-ledger pair
  (Riven/Jarvan IV/Rek'Sai light rows) crashed with a ValueError instead
  of failing closed — live for Force of Nature holders too.  The
  stamping condition now requires a dict ledger; tuple rows reach
  add_engine_result, where a stack-armed defender fails closed with the
  named receipt tuple_ledger_stack_metadata and falls back with parity,
  and an unarmed defender compiles directly.
- DEFECT 2 (dead guard, repaired): defender_stack_armed read
  `voidborn_stack_interval` — a field StartingDefenses does not have
  (the registry key is voidborn_stack_interval but the StartingDefenses
  attribute is jaksho_stack_interval) — so the tuple guard never fired
  for Jak'Sho.  Fixed to jaksho_stack_interval (the force arm was
  already correct).
- RECEIPT ROW: item_state_receipts emits exactly one "voidborn" row
  (stack_interval 1.0, max_stacks 5, bonus_resistance_multiplier 0.30,
  source_url + source_revision_id 3984950 passed explicitly from
  _JAKSHO_SOURCE) + two named boundaries: combat time is the qualifying
  incoming-packet timestamp (the fight window is the combat window — no
  expiry inside a fight, "until the end of combat"), and the holder's
  own outgoing damage does not advance its stacks (conservative
  under-grant).
- COVERAGE: item_model_coverage now returns the specific Voidborn reason
  (new _MODELED_EFFECT_REASONS entry naming the bonus-resistance
  reprice + boundaries) and outcome_dimensions ["defense"] (new
  _UTILITY_DIMENSIONS entry); posture unchanged (modeled_effect,
  optimizer_eligible + calculation_eligible True); BIS scores UNCHANGED
  (the 30% multiplier was already priced identically by both walks).
- FAIL-CLOSED: fabricated Jak'Sho item options rejected ("Unknown item
  option target"); missing/malformed typed values raise naming item+key;
  absent Jak'Sho produces no stacks and no receipt row; minion/reactive/
  zero-damage/self packets never advance the clock; a packet without a
  baseline resistance is never silently repriced
  (dynamic_resistance_unavailable); true damage advances stacks but is
  never repriced (correct); the reaching packet is itself repriced
  prospectively.

Provenance (RLM-2 A): item 6665 = binary itemID 6665 (unique, tier 3
LEGENDARY, 3200 = 2550 + 650 combine); stats 350 HP / 45 armor / 45 MR
verified cache+binary; Voidborn values verified: 5 cap (branch +
binary MaxStacks 5.0), 0.30 multiplier (branch + binary
BonusResistPercentage 0.30), BONUS-only + "until the end of combat"
(branch + riotDescription; kernel multiplies the bonus pools only);
1s interval is wiki-prose + code-static ONLY (binary carries no interval
field — the GAP is flagged, low risk); revision 3984950 (page 1550191,
2026-01-17, ready) == code-pinned _JAKSHO_SOURCE == audit row; atoms: 3
clean (economy.total 3200 4003a8fd9a19a2fd, health 350 1ac08338d063029d,
armor 45 a96b7c7319516706, magic_resistance 45 f09883b4d9a7c19d —
evidence polluted by the passive kw) + 1 crammed (stack.gain [5.0, 30.0]
33c6594ab7f2fb6b); separation clean vs FoN (magic-event flat +70 vs
combat-time 30% of BONUS), Randuin's, Kaenic, Frozen Heart, Thornmail,
Gargoyle; zero omnivamp/lifesteal.

RLM-2 audits: A (provenance; gaps: 1s interval not binary-backed,
crammed stack.gain atom, polluted evidence, generic coverage reason,
dead _REVIEWED_STATS_ONLY line, no mid-fight combat-end/reset — named
boundary), B (runtime; receipt path CORRECT end-to-end incl. the armor
reprice leg; the two defects above; coverage reason/dimension + receipt
row missing; golden byte-stable — one TDD-only item_sweep row pair
ahri 817.29 / vayne 788.1, no survival scenarios), C (tests; 31-test
matrix 25 PASS / 6 XFAIL pre-integration; all 6 flipped; 2 PASS-today
pins renegotiated to the compiled contract (enemy-roster poison,
capability-scan receipt); 0 xfail remain).

Files: EDITED src/calculator/participant_timeline.py (defender_stack_
armed attr fix + tuple-ledger gate), survival/compile.py (blocklist
removal + comment), item_effects.py (voidborn receipt row),
item_coverage.py (_MODELED_EFFECT_REASONS entry + _UTILITY_DIMENSIONS
entry), tests/test_jaksho_compiled_parity.py (C-owned; 6 xfails flipped
+ 2 pins renegotiated).

Gates: focused 741 + new file 31 passed (2 known pre-existing app
rate-limiter flakes in batch context, pass isolated; FoN parity file
kept green), full pytest 6119 passed + 16 xfailed in 117.60s (6088 +
31 new), black clean (5 files), FULL-SRC pylint 9.55/10 — UNCHANGED
from the documented baseline (17 pre-existing E/F artifacts; zero new
findings; item_model_coverage stays under the R0915 threshold — the
dict entries add no branch statements), atomize run TWICE with
content-identical results (generated_at only), golden 858 = prior state
— ZERO new differences from 3R (the compiled certification changes no
fight numbers; the golden baseline's single Jak'Sho item_sweep row pair
is TDD-only), Catalyst resource-ledger set re-run: 133 passed (3A
intact).  Baseline NOT recaptured.

Follow-ups (recorded): the 1s combat interval is wiki-prose + code-static
only (no binary mDataValue — a future client-binary check could pin it);
mid-fight combat-end/reset is unmodeled (the fight window IS the combat
window — named boundary); the crammed stack.gain atom and the polluted
stat atom evidence are atomizer-domain gaps; the dead _REVIEWED_STATS_ONLY
line-243 entry could be removed; the receipt-layer "force_of_nature"
dynamic MR field displays the Jak'Sho delta when only Jak'Sho is armed
(display-only, parity-safe, both walks identical — left untouched per
the no-conflation rule).


### 4.42 P1 Package 3S (2026-08-09): Knight's Vow compiled-walk + optimizer certification

Knight's Vow's Sacrifice/Pledge is now CERTIFIED on the compiled score
path with the Worthy redirect split + holder heals staged per panel and
a corrected fail-closed designation contract.

- NO-SELECTION SENTINEL (contract fix): Pledge is unit-targeted, so the
  authored worthy_target_index is the whole designation.  The schema
  default changed from 0 (first teammate — an invented designation) to
  -1 (the no-selection sentinel): a missing index means NO Worthy ally —
  no redirect and no heal, never an invented first teammate.  The shared
  tether resolver (resolve_knights_vow_tether) is used by BOTH the
  receipt scheduler and the compiled staging so the walks cannot
  disagree about the tether.
- COMPILED PATH (certification): the blocklist entry removed; the score
  path stages the receipt scheduler's behavior per panel — the
  pre-mitigation split (raw recovery from action raw_damage or the 3Q-
  stamped baseline resistances; per-target mitigation factors ported
  from the receipt expansion incl. penetration, basic-damage defenses,
  and flat reductions; the child REDIRECT action trigger-linked to the
  parent at phase 0.5 with CC fields copied so immobilize windows stay
  byte-identical; the parent's direct amount + holder-gate metadata) and
  the 12% holder heals (kind HEAL, subject = the KV holder,
  requires_holder_health_ratio enforced by the shared kernel; the
  compiled support-template reject for that field was relaxed — the
  kernel gates it).  Children register in the attacker's damage order
  and heals in the support entries so the breakdown totals and
  support/healing outputs attribute identically.  The score walk's
  TransitionContext now carries the staged redirect_children (base +
  per-signature + per-evaluation fresh maps), so the kernel's
  holder-health gate cancels/restores exactly like the receipt.  Main-
  holder AND roster-holder (ally/enemy) evaluations compile (panels
  non-empty, uncompilable False) with byte parity on every survival row
  and every breakdown field except the documented CC-blocked total
  delta (below).
- TUPLE-LEDGER: "Knight's Vow" added to EVENT_SCAN_SUPPORT_ITEMS so a
  score-only tuple-ledger fight keeps dict rows (the staging reads the
  per-event view) — named fail-closed boundary; tuple fights fail closed
  with parity and no crash (verified).
- RECEIPT ROW: item_state_receipts emits exactly one "sacrifice" row
  (worthy_target_index, worthy_within_range, holder_above_30_percent,
  redirect_fraction 0.14, holder_heal_fraction 0.12, worthy_range_units
  1250.0, holder_health_threshold_ratio 0.30, source_url +
  source_revision_id 4023793) + the target_boundary naming the
  unit-targeted designation and the authored range gate.
- COVERAGE: item_model_coverage now returns the specific
  Sacrifice/Pledge reason (new _MODELED_STATE_REASONS dict consulted by
  the ITEM_INPUT_OPTIONS branch — zero net statement/branch change,
  thresholds preserved); posture unchanged (modeled_state,
  optimizer_eligible + calculation_eligible True); BIS scores UNCHANGED
  (the split was already priced by both walks).
- DOCUMENTED DELTA (receipt-vs-compiled total_damage): the receipt's
  total_damage is the outgoing EVENT ledger sum — it includes packets
  the walk skipped for attacker CC-blocked states at their full event
  values, plus the mirrored redirect clones.  The compiled total is the
  APPLIED-based sum (the honest number; the applied children and the
  mirrored clones are the same amounts and cancel).  For a CC-blocked
  attacker (Janna charmed at t=0 in the parity fixture), the named delta
  is exactly the blocked parents' event values (compiled == receipt -
  blocked); every other row is byte-equal.  The legacy/receipt total
  semantics are unchanged (pre-existing event-ledger view).

Provenance (RLM-2 A): item 3109 = binary itemID 3109 (unique, tier 3
LEGENDARY, 2300 = 3067+1031+1006 + 400 combine); stats 200 HP / 40
armor / 10 AH / 100% base regen verified cache+binary; Sacrifice values
verified 4/4 (wiki branch, riotDescription, binary mDataValues
DamageRedirection 0.14 / DamageRedirectionThreshold 0.30 / TetherRange
1250.0 / AllyHealingConversion 0.12, code statics); the 14% applies to
PRE-mitigation physical+magic (true excluded), the 12% heal to
POST-mitigation Worthy damage to champions (true included); the holder
gate is STRICTLY above 30% of max health (1e-9 epsilon, re-checked per
packet); revision 4023793 (page 1301838, 2026-05-29, ready) == code pin
== audit; atoms: 3 clean (economy.total 2300 44d9fa4671337f8a, armor 40
15ac45b1df7c86bb, ability_haste 10 17d7cc3a6f546163) + 4 crammed 4-value
atoms; binary Cooldown=60.0 vs wiki "(0s)" flagged as an unresolved
source conflict (model consumes no cooldown — one designation per
fight); separation clean vs Locket/Mikael's/Redemption/Zeke's/Ardent;
zero omnivamp/lifesteal.

RLM-2 audits: A (provenance; clean + caveats: the 60s cooldown conflict,
the crammed atoms, the flat-only regen atom gap), B (runtime; the
receipt scheduler + kernel mapped; the compiled gap = shared tether +
redirect split port + heal staging + ctx.redirect_children + three
panel hooks; the two latent guards (unrepresentable_damage_receipt
"redirect_fraction" / unrepresentable_template_receipt
"requires_holder_health_ratio") bypassed by the staging; the receipt's
event-ledger total vs the compiled's applied-ledger total; the
ENV-SCAN tuple boundary), C (tests; 35-test matrix 30 PASS / 5 XFAIL
pre-integration; all 5 flipped; 7 pins renegotiated (sentinel x2,
options schema, legacy score surface, enemy-holder poison, parity
delta, compiled-panels equality shape); 0 xfail remain).

Files: EDITED src/calculator/item_effects.py (sentinel default + receipt
row), item_support_effects.py (shared tether resolver + sentinel +
EVENT_SCAN entry), survival/compile.py (module-level resistance imports,
template reject relaxed, support field mapping, stage_knights_vow_
redirect_actions + stage_knights_vow_heals), survival/actions.py (no
change — the redirect fields already existed), survival/__init__.py
(exports), participant_timeline.py (base/signature/fresh staging hooks,
_SignaturePanel kv_redirect_children, CoupledSearchContext field, walk
context redirect_children), item_coverage.py (_MODELED_STATE_REASONS +
entry), tests/test_knights_vow_compiled_parity.py (C-owned; 5 xfails
flipped + 7 pins renegotiated), tests/test_survival_kernel.py (the
poison-contract test re-pinned to the compiled contract).

Gates: focused 767 + new file 35 passed (2 known pre-existing app
rate-limiter flakes in batch context, pass isolated; FoN + Jak'Sho
parity files kept green), full pytest 6154 passed + 16 xfailed in
109.04s (6119 + 35 new), black clean (9 files), FULL-SRC pylint 9.55/10
— UNCHANGED from the documented baseline (17 pre-existing E/F
artifacts; zero new findings; the transient Sequence undefined-variable
+ redefined-import findings from the first draft were fixed), atomize
run TWICE with content-identical results (generated_at only), golden
858 = prior state — ZERO new differences from 3S (the compiled
certification changes no fight numbers outside coupled KV scenarios;
the golden sweep is 1v1 with no roster), Catalyst resource-ledger set
re-run: 133 passed (3A intact).  Baseline NOT recaptured.

Follow-ups (recorded): the binary Cooldown=60.0 vs wiki "(0s)" conflict
(model consumes no cooldown — one designation per fight); the 100% base
health regen has no atom (systematic flat-only atomizer limit); the
crammed 4-value Sacrifice atoms are an atomizer-domain gap; the
receipt's event-ledger total_damage (CC-blocked packets included at
full event values) vs the compiled's applied-based total is a
documented pre-existing semantic — a future package could align the
legacy total to the applied ledger; the 1250-unit tether has no
coordinate model (the authored within-range gate IS the tether
assumption — named boundary).


### 4.43 P1 Package 3T (2026-08-09): Maw of Malmortius compiled-walk + optimizer certification

Maw of Malmortius' Lifeline is now CERTIFIED on the compiled score path
with byte parity, including the walk-authored omnivamp heals.

- COMPILED PATH (certification): the blocklist entry removed; the
  threshold-lifeline shield was ALREADY kernel-shared (the Sterak's
  parity test proved the pattern).  The ONE real gap was the
  walk-authored omnivamp heal: the kernel authors each 10%-of-post-
  mitigation vamp heal at the triggering damage event's time via
  ledger.schedule_heal, and the ScoreLedger raised an AssertionError
  (an uncaught 500 on blocklist removal).  The ScoreLedger now mirrors
  the ReceiptLedger's insertion capability: it holds the live actions
  list + index_of (wired at the compiled walk's ledger construction),
  tracks current_index (the walk's hasattr contract), converts the heal
  event via survival_action_from_event (phase 1.0, _sk via action_key,
  new aidx), grows the applied/status parallel arrays by one, and
  inserts beside the current action with the identical sort-key skip
  loop.  Both walks now author the same heals at the same timestamps
  with the same amounts (byte-equal survival rows incl. healing_received
  and the shield/trigger fields); main-holder AND roster-holder
  evaluations compile (panels non-empty, uncompilable False).
- TYPED READS (fail-loud naming): _lifeline_defense now reads the
  shield base/ratio/threshold/duration keys via required_effect_value —
  every missing Maw key raises KeyError naming item AND key (the prior
  bare-KeyError gap for the shield keys is closed for the whole Lifeline
  family).
- RECEIPT ROW: item_state_receipts emits exactly one "lifeline" row
  (health_threshold 0.30, shield_melee_base 200, shield_melee_bonus_ad_
  ratio 1.50, shield_ranged_base 150, shield_ranged_bonus_ad_ratio
  1.125, duration_seconds 3.0, damage_type magic,
  lifeline_omnivamp_percent 10.0, source_url + source_revision_id
  3984424) + two named boundaries: the cached 90s cooldown (one-trigger
  per fight, no re-arm — never enforced) and the omnivamp-until-end-of-
  combat (the flag arms on the triggering packet and is never cleared
  mid-walk — the fight window IS the combat window).
- COVERAGE: item_model_coverage now returns the specific Lifeline
  reason (new _MODELED_EFFECT_REASONS entry naming the magic shield,
  the melee/ranged amounts, the strict threshold, and the omnivamp
  window) + outcome_dimensions ["defense"] (new _UTILITY_DIMENSIONS
  entry); posture unchanged (modeled_effect, optimizer_eligible +
  calculation_eligible True); BIS scores UNCHANGED (the Lifeline was
  already priced by the receipt walk for every evaluation).
- FAIL-CLOSED: magic-only trigger + magic-only absorption (physical and
  true damage never arm nor drain); the strict threshold (a hit landing
  EXACTLY on 30% does not arm); one-trigger with no re-arm; uncertified
  timed fights withheld target-side (require_certified_target_timeline
  names the item + the coarse sources; one_rotation skips the gate);
  no owner path for ally/enemy inference; fabricated item options
  rejected; missing/malformed typed values raise naming item+key.

Provenance (RLM-2 A): item 3156 = binary itemID 3156 (unique, tier 3
LEGENDARY, 3100 = Hexdrinker 3155 + Caulfield's 3133); stats 60 AD / 15
AH / 40 MR verified cache+binary; Lifeline values verified 4/4 (wiki
branch, riotDescription, binary mDataValues ShieldSize 200 /
LowHealthThreshold 0.30 / ShieldDuration 3.0 / ShieldADScaling 1.5 /
BuffVamp 0.10 / RangedShieldMod 0.75 / Cooldown 90, code statics): the
{{rd|200|150}} second value is the RANGED value (NOT level-scaled — Maw
has no level term; the ranged 150/1.125 are DERIVED via RangedShieldMod
0.75, matching the typed keys); the omnivamp "until end of combat" =
binary BuffDuration 5 + BuffExtension 3 (refresh); revision 3984424
(page 416253, 2026-01-14, ready) == code pin (the _MAW_SOURCE timestamp
23:08:00Z vs the audit 22:24:02Z is a minor metadata mismatch); atoms: 4
clean (economy.total 3100 6d7767e110ed1e7d, ability_haste 15
ca8cab10e246fe51, attack_damage 60 0476b4d41cb8d020, magic_resistance 40
501fa294fcdab9e4) + 5 crammed 7-value atoms (the damage.magic atom is a
FALSE POSITIVE — Lifeline deals no damage); separation clean vs
Immortal Shieldbow (level-scaled, all-damage) / Hexdrinker (level-
scaled 110-280, magic, 2.5s) / Seraph's (mana) / Sterak's (bonus
health, all) / Edge of Night (Annul, not threshold); zero vamp beyond
the 10% lifeline.

RLM-2 audits: A (provenance; gaps: the passive-stats omnivamp 30.0
parser artifact (the threshold was grabbed instead of 10 — runtime-
unused), the crammed atoms, the binary price 750, the source-timestamp
mismatch), B (runtime; receipt path fully verified live (trigger at
0.5, 290.0 shield absorbed, 5 omnivamp heals 13.3); the event-certified
requirement = require_certified_target_timeline (timed non-rotation
fights, target-side only — the main's own Maw is un-gated, an
asymmetry documented); the compiled gap = the ONE walk-authored heal
mechanism; tuple ledger excludes Maw holders without crashing), C
(tests; 49-test matrix 45 PASS / 4 XFAIL pre-integration; all 4 flipped
+ 2 PASS-today pins renegotiated (receipt row, coverage dimensions); 0
xfail remain).

Files: EDITED src/calculator/survival/score_state.py (walk-authored
heal insertion capability + array growth + wiring), participant_timeline
.py (ScoreLedger wiring), survival/transitions.py (no change after the
pre-author experiment reverted — the kernel's trigger-time scheduling
works for both ledgers), survival/actions.py + compile.py + __init__.py
(no net change after the revert), defensive_effects.py (_lifeline_defense
typed reads), item_effects.py (lifeline receipt row), item_coverage.py
(_MODELED_EFFECT_REASONS + _UTILITY_DIMENSIONS entries),
tests/test_maw_compiled_parity.py (C-owned; 4 xfails flipped + 2 pins
renegotiated).

Gates: focused 835 + new file 49 passed (2 known pre-existing app
rate-limiter flakes in batch context, pass isolated; the FoN/KV/Jak'Sho
parity files kept green), full pytest 6203 passed + 16 xfailed in
131.85s (6154 + 49 new), black clean (10 files), FULL-SRC pylint
9.55/10 — UNCHANGED from the documented baseline (17 pre-existing E/F
artifacts; zero new findings; the transient Mapping undefined-variable
findings from the first draft were fixed), atomize run TWICE with
content-identical results (generated_at only), golden 858 = prior state
— ZERO new differences from 3T (the Lifeline is never exercised by the
golden sweep — no enemy; the KogMaw champion-baseline rows are the
pre-existing schema drift), Catalyst resource-ledger set re-run: 133
passed (3A intact).  Baseline NOT recaptured.

Follow-ups (recorded): the main-side Maw is not gated by the event-
certified requirement (target-side only — an asymmetry worth a future
policy decision); the passive-stats omnivamp 30.0 parser artifact
(vendor regex grabs the threshold — runtime-unused but contaminates the
crammed atom); the crammed 7-value Lifeline atoms are an atomizer-domain
gap; the _MAW_SOURCE timestamp differs from the audit receipt (same
revision); the binary price 750 is an unused legacy field.


### 4.44 P1 Package 3U (2026-08-09): Verdant Barrier compiled-walk + optimizer certification

Verdant Barrier's Annul is now CERTIFIED on the compiled score path with
byte parity — the LAST item of HANDOVER §8.2's compiled-walk
unrepresentable list (the list is now EMPTY).

- COMPILED PATH (certification): the Annul spell-shield kernel was
  already shared (the eligibility decision, one-use per cast, cast
  grouping, blocked packets, the opening-ready infinite window); the ONE
  gap was the compiled path's missing delivery metadata.  The score
  context now stamps is_ability (mirroring _pair_packet's enrichment)
  and the canonical basic_attack flag on autos; compiled_damage_action +
  both compile paths carry is_ability/basic_attack/area_damage (the
  area_damage flag fixed a delivery-classification divergence in the
  decisions receipt — Ahri's Q classified area on the receipt vs
  targeted on the compiled path).  All three Annul items (Banshee's
  Veil / Edge of Night / Verdant Barrier) leave COMPILED_WALK_
  UNREPRESENTABLE_ITEMS — the family shares one contract and one
  staging.  The tuple-ledger guard now distinguishes the Annul case
  (tuple_ledger_spell_shield_metadata vs tuple_ledger_stack_metadata)
  for spell-shield-armed defenders.  Main-holder AND roster-holder
  evaluations compile (panels non-empty, uncompilable False) with
  byte-equal survival rows (the full spell-shield lifecycle row
  included).
- RECEIPT ROW: item_state_receipts emits exactly one "annul" row
  (spell_shield_ready True, spell_shield_cooldown 60.0 atom-validated,
  cooldown_atom timing.cooldown 2a40799f92fb6749, source_url +
  source_revision_id 3957920) + the rearm_boundary naming the 60s
  cooldown and the "timer restarts upon taking damage from champions"
  rule as receipted named boundaries (rearm is never modeled inside one
  fight — verified: a 70s window with an ability at t=65 does NOT
  re-arm).
- COVERAGE: item_model_coverage now returns the Annul-specific reason
  (the defensive_start branch names the spell shield + the 60s cooldown
  + the damage-restart boundaries for all three Annul items) and
  outcome_dimensions ["spell_protection"] (new _UTILITY_DIMENSIONS
  entry — family parity with Banshee's Veil/Edge of Night); posture
  unchanged (stats_only, optimizer_eligible + calculation_eligible
  True); BIS exclusion is STRUCTURAL (EPIC tier-2 component building
  into Banshee's Veil — the legendary-only candidate pool excludes it
  by construction, never withheld).
- FAIL-CLOSED: the ability-only gate is BY CAST IDENTITY (is_ability),
  not damage type — basic attacks pass (basic_attack_not_blocked, no
  consumption), unclassifiable packets pass (unknown_delivery, no
  consumption), but true-damage and control-only packets OF AN ABILITY
  CAST are consumed and nullified with the cast; the shield blocks for
  the holder only (no inferred owner path); one use per cast, no rearm;
  missing/malformed typed values raise naming item+key; a divergent
  cooldown literal fails closed against the catalog atom.

Provenance (RLM-2 A): item 4632 = binary itemID 4632 (unique, tier 2
EPIC, 1600 = 2x Amplifying Tome + Blasting Wand recipe, buildsInto 3102
Banshee's Veil); stats 40 AP / 25 MR verified cache+binary; Annul values
verified: the 60s cooldown TRIPLY corroborated (cache branch + binary
SpellShieldCooldown 60.0 + Cooldown 60.0) + atom timing.cooldown
2a40799f92fb6749 + registry 60.0; the "blocks the next hostile ability"
ability-only wording + the "timer restarts upon taking damage from
champions" restart-to-full semantics (rearm unmodeled — named boundary);
revision 3957920 (page 1469810, 2025-10-05, ready) == code-pinned
_ANNUL_SOURCES; atoms: 4 clean (economy.total 1600 76ae25eeb53859b1,
ability_power 40 630d5d092e262fa2, magic_resistance 25
30491e6da4b07d62, timing.cooldown 60 2a40799f92fb6749) + the documented
MISLABELED shield.flat [60.0 s] atom (never consumable as a shield
amount — same pattern on both siblings); separation clean vs the
Lifeline family (threshold shields — no spell shield) and the 40-vs-60s
Annul sibling split (Banshee's c020562aebacbe01 / Edge 30d03573d07ed0a5
/ Verdant 2a40799f92fb6749).

RLM-2 audits: A (provenance; gaps: the vestigial binary mDataValues
(MagicResistPerStack/Period/MaxMR/CooldownReductionAmount — unused), the
mislabeled shield.flat atom, the audit has_cooldown=false detector
inconsistency vs the atomizer, the legacy bin price field), B (runtime;
the exact compiled gap = the missing delivery flags (is_ability/
basic_attack) — quantified pre-fix mismatches (+135.6 main / +146.5
dict / +83.3 tuple); the tuple guard distinction; the rearm/damage-
restart named boundaries; BIS exclusion structural), C (tests; 36-test
matrix ALL PASS today — the completion landed mid-session and C
reconciled the contract flips + removed the 4 xfail markers; 0 xfail
remain).

Files: EDITED src/calculator/survival/actions.py (compiled_damage_action
delivery params), survival/compile.py (compile paths carry the flags +
the tuple_ledger_spell_shield_metadata distinction + blocklist removal
for all three Annul items), participant_timeline.py (score-context
stamping: is_ability + basic_attack + area_damage pass-through),
item_effects.py (annul receipt row), item_coverage.py (Annul reason +
spell_protection dimension), tests/test_verdant_barrier_compiled_parity
.py (C-owned; 38 cases, all passing), tests/test_spell_shield_
eligibility.py (the R11 blocklist receipt re-pinned to the compiled-
certified contract).

Gates: focused 699 + 38 passed (2 known pre-existing app rate-limiter
flakes in batch context, pass isolated; all parity files kept green),
full pytest 6241 passed + 16 xfailed (6203 + 38 new; the count was
stable across two runs), black clean (7 files), FULL-SRC pylint 9.55/10
— UNCHANGED from the documented baseline (17 pre-existing E/F
artifacts; zero new findings), atomize run TWICE with content-identical
results (generated_at only), golden 858 = prior state — ZERO new
differences from 3U (the Annul is never exercised by the golden sweep;
no Verdant/Annul rows in the diff), Catalyst resource-ledger set re-run:
133 passed (3A intact).  Baseline NOT recaptured.

Follow-ups (recorded): the rearm + cooldown-restart-on-champion-damage
mechanics remain receipted named boundaries (a future fight-length
extension could model a 60s rearm; the restart rule needs a
damage-tracking kernel); the audit's has_cooldown detector disagrees
with the atomizer on the same branch (detector fix); the mislabeled
shield.flat-in-seconds atoms across the Annul family are a documented
atomizer quirk; the vestigial binary stacking-MR mDataValues are unused.


### 4.45 P1 Package 3V (2026-08-09): Rengar Ferocity live state + resource/counter ledger integration

Rengar's Unseen Predator Ferocity is now LIVE: the accepted basic-ability
cast stream feeds the kernel stack state, the empowered pricing is
per-cast, and the counter rides the resource-ledger surface.

- THE INTEGRATION (the smallest slice, proven by the Conqueror pattern):
  the champion module's Q/W/E entries now emit BOTH part sets
  unconditionally — ``parts`` (the base per-rank values, always the
  engine's default) and ``ferocity_parts`` (the wiki Ferocity Bonus
  per-level values) — while the seeded ``total_raw`` headline + detail
  keep the parse-level behavior.  The engine builds a per-cast
  ``FerocityTimeline`` inside the rotation (``_build_ferocity_timeline``,
  a TimedStackState walk over the accepted Q/W/E cast times with the
  kernel rule: cap 4, gain 1, 1s no-refresh per-stack expiry, 10s combat
  freeze, all-at-once expiry, cap noop) and prices the ``ferocity_parts``
  for the casts that consume the cap (the 4th-stack empowered cast) via
  the CastPricing ``ferocity_empowered`` flag.  The post-rotation walk
  (``_add_rengar_ferocity``, the Conqueror twin) publishes the
  breakdown's ``ferocity`` row (stack_events + state_transitions +
  seeded/live state text) and the RESOURCE-LEDGER counter account.
- THE LEDGER SURFACE: Rengar's ``resource_ledger`` section is now the
  Ferocity counter account (contract resource_ledger_v1, kind
  "ferocity", opening/closing current, the ResourceReceipt-shaped
  per-cast rows — operation gain/consume with current_before/after,
  maximum_before/after, accepted, reason at_cap/empowered/unknown_cast_
  slot — plus the rule declaration + the kernel state_transitions).  The
  mana-only ResourceAccount is untouched (Rengar has no mana); the
  counter is a champion-consumer sub-section like auto_restore/
  mark_refunds.
- THE LIVE RULES (kernel-owned + walk-driven): each ACCEPTED Q/W/E cast
  (the cooldown-admitted cast_timeline rows) gains +1; P and R never
  gain; at the 4-stack cap the next basic-ability cast is EMPOWERED —
  the kernel consume clears 4->0 and the engine prices the
  ferocity_parts (only that cast; later casts price base); the 5th gain
  in a long fight re-empowers (the cap-at-5th rule); the 1s per-stack
  no-refresh expiry and the 10s combat freeze are kernel semantics
  receipted in the state_transitions; DoT ticks and item procs never
  grant nor extend (the walk gains only from the accepted basic casts);
  a requested cast slot outside the champion's known slots authors a
  named ``unknown_cast_slot`` denial receipt; the seeded p_ferocity
  option (0..4, API 400 outside range, module clamp) remains the
  starting state and the P row's parse-level text is unchanged.
- SCORE/RECEIPT PARITY: ``calculate_fight_damage(score_only=True)`` runs
  the identical timeline + walk (the receipts and the empowered pricing
  are byte-identical — the resource_ledger ferocity receipts and the
  Q/W/E total_raw match under score_only); the coupled compiled path
  flows through the same run_fight results.
- PUBLIC RECEIPTS: the breakdown ``ferocity`` row (rule name, seeded
  "N/4" + live "N/4 at fight end", max/duration/extension, stack_events,
  state_transitions, the live detail note "only the first basic-ability
  cast at the cap is empowered; later casts price the base values" on
  the affected slots), the resource_ledger ferocity account, and the
  notes.

Provenance (RLM-2 A): Rengar cache entry (id 107, resource FEROCITY,
patch 26.05, parent rev 3993826); P prose "Rengar generates a stack of
Ferocity for 1 second, stacking up 4 times but not refreshing on
subsequent triggers (unexpected) ... prevented from expiring for 10
seconds after dealing or taking damage, excluding damage dealt by damage
over time or proc effects"; the StackRule values: cap 4 (prose + binary
MaxFerocity), gain 1 (prose), 1s (prose-only — the P template rev
2864152, the module's source receipt), 10s extension (prose + binary
InCombatTimer 10.0), no-refresh + all-at-once (prose); the Q/W/E base
rank arrays + the Ferocity Bonus per-LEVEL arrays (the module prices the
wiki arrays; W's empowered level array conflicts in shape with the game
record — flagged); PACKET_SHA256 verified; 27 ability atoms all
recompute (no [4,1,10] ferocity atom exists — cap/extension not
atomized).

RLM-2 audits: A (provenance; gaps: the 1s prose-only, the W empowered
array shape conflict, the missing ferocity atom), B (runtime; the
cast-event observation point = rotation.cast_events; the Conqueror walk
pattern; the resource ledger is mana-only and NOT the carrier — the
counter rides state_lifecycle + the ledger sub-section; the pricing seam
= CastPricing + _evaluate_cast_parts), C (tests; 25-test matrix 15 PASS
/ 10 XFAIL pre-integration; all 10 flipped + 6 pins renegotiated to the
live contract (gains 4, closing values, the dot fixture, the account
shape, the live detail, the e3 live expectations); 0 xfail remain).

Files: EDITED src/calculator/champions/rengar.py (dual part sets on
Q/W/E — base parts always + ferocity_parts always, seeded headline
kept), champions/engine.py (_ALLOWED_ENTRY_KEYS += ferocity_parts),
damage.py (FerocityTimeline + _build_ferocity_timeline + the CastPricing
flag + the pricing seam + the ledger account + _add_rengar_ferocity
breakdown/notes/denials + champion_options threading),
pipeline.py (champion_options passthrough), tests/test_rengar_ferocity_
ledger.py (C-owned; 10 xfails flipped + 6 pins renegotiated),
tests/test_e3_stacks_2.py (the empowered Q/W/E test re-pinned to the
live first-cast-only contract).

Gates: focused 416 + 25 passed (2 known pre-existing app rate-limiter
flakes in batch context, pass isolated), full pytest run TWICE with
stable results: 6266 passed + 16 xfailed (6241 + 25 new) on both runs,
black clean on src/ + tests/ + scripts/, FULL-SRC pylint 9.55/10 —
UNCHANGED (17 pre-existing E/F artifacts; the transient plan_times
undefined-variable finding fixed; the W0613/W0612 findings are
pre-existing untouched-region classes), atomize run TWICE with
content-identical results (generated_at only), golden compare: 877 vs
the prior 858 — NINETEEN new differences, ALL explained by 3V and
additive (3x the ferocity_parts key on the Rengar Q/W/E
champion-baseline ability rows + 16x the ferocity breakdown row on the
registered Rengar fights with totals 0.0 — the row carries no damage;
ZERO numeric damage changes; the skillshot/area_damage rows are the
pre-existing schema drift), baseline NOT recaptured, Catalyst +
resource-ledger suites: 140 passed (the client's independent check).

Follow-ups (recorded): the 1s Ferocity duration is prose-only (no
numeric game field — verify against current game files on patch
updates); W's empowered level array conflicts in shape with the game
record (module prices wiki — flagged); the cap 4 / 10s extension have
no atoms (atomizer-domain gap); the 10s combat freeze arms from gains
only in the standalone fight (the taking-damage note_activity wiring
from the coupled timeline's incoming events is the documented follow-on
— the DoT/proc exclusion is structural in the standalone walk).


### 4.46 P1 Package 3W (2026-08-09): Senna Absolution Mist soul counter + resource/counter ledger integration

Senna's Absolution Mist souls are now receipted on a live counter
ledger, with the permanent pre-stacked option and every-20 threshold
math documented — never re-priced.

- THE INTEGRATION (documentary — the smallest safe slice): Mist souls
  are a PERMANENT pre-fight counter: the seeded ``senna_mist_stacks``
  option (default 40, clamp 0..300) prices the stats at parse time
  (0.75 bonus AD per soul; 20 range + 10% crit per 20 thresholds) and
  the model cannot simulate Wraith-farming, so the live ledger RECEIPTS
  the gains and threshold crossings without changing any fight number.
  The typed ``SENNA_MIST_RULE`` declaration (the four numbers +
  permanent flag + the Data_Senna template source receipt rev 2864157)
  rides the option's ``state`` receipt (the p_ferocity pattern).
- THE ACCEPTED SOUL-EVENT STREAM: the ONLY supported live soul gain is
  the fight's champion takedown — ``target_ending_health <= 0`` (the
  3K-style synthesis shape; one soul from the champion wraith pickup at
  the kill timestamp, ownership "main" + event identity in the detail).
  Minion drops / Wraith-farming / mark-consume generation are named
  unsupported sources (per-fight denial receipts
  ``unsupported_soul_source:minion_drop`` / ``:wraith_farm`` /
  ``:mark_consume``) and a surviving target receipts
  ``no_takedown_event`` — never an inferred kill.
- THE LEDGER SURFACE: an ADDITIVE ``resource_ledger["souls"]``
  sub-section (kind "souls", contract resource_ledger_v1, opening/
  closing currents seeded from the option, base_maximum 300,
  ResourceReceipt-shaped gain rows with owner/kind/operation/amount/
  time/source/sequence/tier/atoms/current/maximum/accepted/reason, the
  declaration, and the ``threshold_transitions`` rows with threshold_count
  (the multiple-of-20 value), range_delta 20.0, crit_delta 10.0,
  stacks_before/after, stat_application "parse_time_seeded").  Senna's
  REAL mana account (kind "mana") is never replaced — the merge keeps
  the Tear/Catalyst/Enlighten consumers intact.
- THE BREAKDOWN + NOTES: an informational ``mist`` row (rule name,
  seeded/live state text, soul_events, threshold_transitions) + the
  notes naming the gains or the no-takedown boundary.
- SCORE/RECEIPT PARITY + OPTIMIZER SAFETY: the walk is post-rotation
  and additive — total_damage, every breakdown damage row, the mana
  receipts, and the souls account are byte-identical under score_only;
  senna_mist_stacks is classified self_state/P (the rotation resolver
  only acknowledges it) and the ledger changes no search-relevant
  output.

Provenance (RLM-2 A): Senna cache entry (patch 26.14, parent rev
4025085); P prose (the Mist rules: 0.75 bonus AD per stack; every 20
stacks -> 20 range + 10% crit; the wraith drop rules 5%/32%/8.4%, epic
2, 8 gold; the >100% crit -> 0.35% life-steal conversion); the module
constants (0.75/20/20/10 — wiki-PROSE-ONLY, the one uncertifiable set —
no binary evidence; flagged); the Weakened Soul 1-10% current-health
leveling + the mark 4s (atom-backed); the R shield 120/160/200 + 50% AP
+ 150% Mist (fully sourced incl. the 150% atom ab65b71871f6c0a7); the Q/
W values binary/atom-backed; 25/25 Senna atoms hash-verified (no
[0.75,20,10] mist atom — the Mist effect has no leveling row); the P
template rev 2864157 (2019 launch-era — the pinned revision does not
vouch for the current-cache Mist numbers, flagged); PACKET_SHA256
verified.

RLM-2 audits: A (provenance; gaps: the prose-only 0.75/20/10 triple,
the launch-era P template revision vs the current cache, the soul-gain
event rules unmodeled by design, the stale packet header patch label),
B (runtime; the static path fully mapped; reading B (documentary — no
re-pricing) recommended over A (mid-fight re-pricing) — the CastPricing
seam would break golden parity + the ASSUMPTIONS; the takedown
synthesis as the only supported event; the merge-instead-of-replace
splice; the permanent-counter semantics — no TimedStackState, a fake
timer would silently expire souls), C (tests; 28-test matrix 15 PASS /
13 XFAIL pre-integration; all 13 flipped + 4 pins renegotiated (the
kill fixtures, the accepted-gains filter, the threshold field spellings,
the denial-precedence); 0 xfail remain).

Files: EDITED src/calculator/champions/senna.py (the typed _MistRule +
SENNA_MIST_RULE + the option's state receipt), damage.py
(_add_senna_souls — the documentary walk: takedown gain, unsupported
denials, threshold rows, the additive souls ledger sub-section, the
breakdown row + notes; called after the shield-outcome resolution),
tests/test_senna_souls_ledger.py (C-owned; 13 xfails flipped + 4 pins
renegotiated).

Gates: focused 537 + 28 passed (2 known pre-existing app rate-limiter
flakes in batch context, pass isolated), full pytest run TWICE with
stable results: 6294 passed + 16 xfailed (6266 + 28 new) on both runs,
black clean on src/ + tests/ + scripts/, FULL-SRC pylint 9.55/10 —
UNCHANGED (17 pre-existing E/F artifacts; zero new findings), atomize
run TWICE with content-identical results (generated_at only), golden
compare: 877 = the PRIOR state — ZERO new Senna mist/soul deltas from
3W (the documentary ledger changes no fight numbers; the 19 Rengar
deltas from 3V remain the only explained additions), baseline NOT
recaptured, Catalyst + resource-ledger suites: 140 passed (the client's
independent check).

Follow-ups (recorded): the 0.75/20/10 Mist triple is wiki-prose-only
(no binary confirmation anywhere locally — a game-file pull would be
needed to certify); the pinned P-template revision is launch-era and
does not vouch for the current-cache Mist numbers; the soul DROP rules
(5%/32%/8.4%, epic 2, 8 gold, wraith 8s) and the >100% crit -> 0.35%
life-steal conversion remain unmodeled named boundaries; Weakened
Soul's max-health proxy + the mark onTargetCdStatic 6/5/4 remain the
documented module conventions.


### 4.47 P1 Package 3X (2026-08-09): Aurelion Sol Q Stardust permanent counter + resource/counter ledger integration

Aurelion Sol's Cosmic Creator Stardust is now receipted on a live
counter ledger, with the seeded permanent option and the linear Q/E
terms documented — never re-priced.

- THE INTEGRATION (documentary — the Senna 3W mirror): the typed
  ``AURELION_SOL_STARDUST_RULE`` declaration (per-stack burst 0.031%,
  execute base 5.0 + 2.6 per 100, +2 Stardust per Q burst, 3 bursts per
  channel, permanent, source = wiki rev 3952788 + the local Community
  Dragon binary 16.15.8024387 — QMaxHealthTrueDamagePerStack 0.00031 /
  BaseExecutionThreshold 5.0 / ExecutionGrowthPerBreakpoint 0.026,
  ALL THREE binary-confirmed, stronger than the module's own wiki-only
  claim) rides the option's state receipt (the p_ferocity/SENNA pattern).
- THE ACCEPTED STREAM (B's core correction): Stardust is NOT
  takedown-based — the wiki prose + the game files both say it is
  ability-generated (Q burst +2 per champion hit, E +1/s + kill
  bounties 2/2/1, R +5/hit; champion takedowns only refund W's
  cooldown — ``TakedownCooldownMultiplier``, NO Stardust).  The only
  certified live gain the engine prices is the Q burst vs the champion
  target: +2 per burst (3 per Q cast one-rotation; ``int(duration)``
  bursts in timed fights — the module's ``_channel_window`` semantics).
  The Senna takedown synthesis is NOT reused — a takedown event is a
  named denial.
- THE LEDGER SURFACE: an additive ``resource_ledger["stardust"]``
  sub-section (kind "stardust", contract resource_ledger_v1, opening/
  closing currents seeded from the option, base_maximum 999, the
  ResourceReceipt-shaped per-burst gain rows with owner/kind/event
  identity, the declaration, and the per-100 ``threshold_transitions``
  milestone rows (threshold_count, q_burst_maxhp_pct 3.1×k,
  e_execute_threshold_pct 5+2.6×k, execute_pct_delta 2.6,
  mechanical False — both priced terms are continuous LINEAR in stacks,
  the per-100 rows are display milestones only, stat_application
  "parse_time_seeded"); Aurelion Sol's REAL mana account (kind "mana")
  is never replaced.
- THE BREAKDOWN + NOTES: an informational ``stardust`` row (rule name,
  seeded/live state text, gain_events, threshold_transitions) + the
  notes naming the gains or the no-Q-burst boundary.
- FAIL-CLOSED: ``no_q_burst_event`` (no accepted Q casts), the named
  ``unsupported_stardust_source`` denials (champion_takedown /
  e_champion_seconds / e_kill_bounty / r_multihit / minion_farm) +
  ``missing_identity``; the malformed seed clamps to 0..999 (the API
  layer rejects out-of-range with the named 400s); the parse path's
  unclamped behavior (a pinned divergence from Senna — the clamp lives
  ONLY at the API) is unchanged.
- SCORE/RECEIPT PARITY + OPTIMIZER SAFETY: the walk is post-rotation
  and additive, with NO mode-sensitive inputs (no shield_outcome) — the
  stardust account is byte-identical under score_only; stardust_stacks
  is classified self_state/P and the ledger changes no search output.

Provenance (RLM-2 A): Aurelion Sol cache entry (revision 3952788,
page 1266197, ready); P prose "Aurelion Sol's damaging abilities against
enemies generate him permanent stacks of Stardust"; the Q burst prose
("generates 2 Stardust if they are a champion", the degraded modifier
row values [0,...] units "(3.1% Stardust)% of target's maximum health");
E execute prose (5% + 2.6% per 100, excluding epic monsters); the R
transform (75 Stardust — vs the game file CalamityStacks 50 — a genuine
discrepancy flagged for patch day); the 0.031/5.0/2.6 triple
BINARY-CONFIRMED (aurelionsol.bin.json); 32/32 Asol atoms hash-verified
(no stardust/execute atom — the degraded Q atom d7b0a266cad8da3f is the
only one); the Q channel 3.25s/3 bursts + the E 20 ticks sourced; the
binary receipt added to the rule's source (A's gap #2 closed); the
"TrueDamage" naming flag + the E cooldown discrepancy (12 cache vs 8-10
binary) recorded.

RLM-2 audits: A (provenance; gaps: the binary receipt now recorded, the
TrueDamage naming + E cooldown + R-transform discrepancies flagged, the
atom gap), B (runtime; the brief's takedown premise REFUTED — the
accepted stream = the Q burst +2 per champion hit; the linear terms
documented; the takedown synthesis NOT reused; the exact Senna-mirror
integration with no shield_outcome dependence — stronger parity), C
(tests; 34-test matrix 21 PASS / 13 XFAIL pre-integration; all 13
flipped + 4 pins renegotiated (the mana coexistence, the no-Q denial
reason, the 95-seed milestone fixture, the per-stack rule fields); 0
xfail remain).

Files: EDITED src/calculator/champions/aurelion_sol.py (the typed
_StardustRule + AURELION_SOL_STARDUST_RULE + the option's state
receipt + the binary source receipt), damage.py (_add_aurelion_sol_
stardust — the Q-burst gains, the unsupported denials, the per-100
milestone rows, the additive stardust ledger sub-section, the breakdown
row + notes; called after the Senna walk), tests/test_aurelion_sol_
stardust_ledger.py (C-owned; 13 xfails flipped + 4 pins renegotiated).

Gates: focused 539 + 34 passed (2 known pre-existing app rate-limiter
flakes in batch context, pass isolated), full pytest run TWICE with
stable results: 6328 passed + 16 xfailed (6294 + 34 new) on both runs,
black clean on src/ + tests/ + scripts/, FULL-SRC pylint 9.55/10 —
UNCHANGED (17 pre-existing E/F artifacts; zero new findings), atomize
run TWICE with content-identical results (generated_at only), golden
compare: 877 = the PRIOR state — ZERO new Aurelion stardust deltas (the
documentary ledger changes no fight numbers; the 19 Rengar rows from 3V
remain the only explained additions), baseline NOT recaptured, Catalyst
+ resource-ledger suites: 140 passed (the client's independent check).

Follow-ups (recorded): the R transform threshold discrepancy (75 wiki vs
50 game — patch-day flag); the Q burst's "TrueDamage" binary naming vs
the module's magic pricing (review flag); the E cooldown discrepancy (12
cache vs 8-10 binary); the monster cap 300 + the >100% crit conversion
boundaries; the E champion-seconds / R multihit / kill-bounty gains
remain named unsupported sources (no champion-count-in-zone stream).


### 4.48 P1 Package 3Y (2026-08-09): Bard Traveler's Call chime counter + meep/resource-counter ledger

Bard's chime counter and meep availability are now receipted on a live
counter ledger, with the seeded permanent option and the meep math
documented — never re-priced.

- THE INTEGRATION (documentary — the 3W Senna / 3X Aurelion Sol
  mirror): the typed ``BARD_TRAVELERS_CALL_RULE`` declaration (meep
  base 30, +6 per 5 chimes, +40% AP, the stock 1..9 + recharge 8..4s
  breakpoint tables, permanent, source = wiki rev 4002472 ≡ the full
  entry audit, 2026-03-25T15:16:50Z) rides the option's ``state``
  receipt.  All meep numbers are PROSE-ONLY (P[0] has no leveling rows
  — the degraded parse; A's audit cross-verified the formula against
  all 20 notes-table rows); the recharge 8s base is inferred (the only
  cached trace is the garbled units "50 • 8 : 4").  No meep number is
  binary-confirmed — the wiki revision is the authoritative receipt.
- THE ACCEPTED STREAM (B + C converged): MEEP CONSUMPTION, not chime
  gains.  The model cannot simulate map chime spawning/collection (no
  engine stream — the wiki event rules are prose-only), so chime gains
  are named fail-closed denials.  The only identity-bearing live events
  the engine prices are the meep-empowered autos: each empowered auto
  consumes one meep from the availability pool (stock +
  floor(duration/recharge) = the P on-hit's ``max_procs``), booked as a
  spend receipt with the engine's per-swing timestamps as the event
  identity (event_index + event_time).
- THE LEDGER SURFACE: an additive ``resource_ledger["chimes"]``
  sub-section (kind "chimes", contract resource_ledger_v1, opening ==
  closing == the seeded counter absent events, base_maximum 200, the
  ResourceReceipt-shaped spend rows booking balance row by row, the
  availability dict {stock, recharge, max_procs, recharges,
  window_seconds}, the parse-time meep-math milestone row
  (stat_application "parse_time_seeded"), the declaration); Bard's
  REAL mana account (kind "mana") is never replaced.
- THE BREAKDOWN + NOTES: one informational ``chimes`` breakdown row
  (zero total_damage; the pre-walk boundary test re-pinned to include
  it) + the notes naming the consumption or the no-meep boundary.
- FAIL-CLOSED: ``no_meep_auto_event`` (zero autos), ``meep_auto_without_
  identity`` (missing_identity — unresolvable swing schedule), the named
  ``unsupported_chime_source:chime_spawn/chime_collect`` + ``unsupported_
  meep_effect:slow/splash`` denials (the 25%..75% slow is CC; the 15+
  chime splash/cone never hits the primary target), ``meep_event_without_
  identity``; the API keeps the named 400s ("abc"/2.5/201); the parse's
  lower-only clamp (500 -> 630, ASol-style, pinned by C) is unchanged.
- SCORE/RECEIPT PARITY + OPTIMIZER SAFETY: the walk is post-rotation,
  mode-invariant, additive; the chimes account is byte-identical under
  score_only (B verified the meep on-hit row identical across
  full/scored/tuple); chimes is classified self_state/P and the
  optimizer never varies champion_options — the ledger changes no
  search output.

Provenance (RLM-2 A): the meep formula + stock/recharge tables = wiki
prose (20-row notes table cross-verifies the formula; the recharge
reductions 7/6/5/4 EXACT, base 8s inferred); 18 abilities + 3 binary P
atoms hash-verified (P atoms are timings only — ammo/slow/chime-pickup
atoms exist with EMPTY values, confirming mechanic existence, ZERO
numbers); no meep-damage/chime/stock atom exists; SOURCES rev 4002472 ≡
audit rev 4002472; STALE-AUTHORITY FINDING: docs/wiki-full-entry-audit
+ reviewed-packets still label Bard P "no_damage" (the packet view —
the module emits the meep on-hit; a regeneration under the 08-08
module-authority semantics yields modeled — recorded, no gate failure);
cosmetic atom_id spaces flagged.

RLM-2 audits: A (provenance; above), B (runtime; the accepted stream =
meep consumption with the swing-time identity; the availability split
documented — recharges are a parse-time projection, never minted as
per-event receipts (no identity exists); the exact Senna/Aurelion
mirror; the mode-invariance proof), C (tests; 34-test matrix 22 PASS /
12 XFAIL pre-integration; all 12 flipped + 1 boundary re-pin (the
pre-walk breakdown set now includes the informational chimes row —
the delivered contract); 0 xfail remain).

Files: EDITED src/calculator/champions/bard.py (the typed
_TravelersCallRule + BARD_TRAVELERS_CALL_RULE + the option's state
receipt), damage.py (_add_bard_travelers_call — the spend receipts,
the unsupported denials, the availability dict, the additive chimes
ledger sub-section, the breakdown row + notes; called after the ASol
walk), tests/test_bard_chimes_ledger.py (C-owned; 12 xfails flipped +
1 boundary re-pin).

Gates: focused sanity 919 passed (2 known pre-existing app
rate-limiter flakes in batch context, pass isolated) + Bard 84 passed,
full pytest run TWICE with stable results: 6362 passed + 16 xfailed
(6328 + 34 new) on both runs, black clean on src/ + tests/ + scripts/,
FULL-SRC pylint 9.55/10 — UNCHANGED (17 pre-existing E/F artifacts;
zero new findings), atomize run TWICE with content-identical results
(generated_at only), golden compare: 877 = the PRIOR state — ZERO new
Bard ledger deltas (the snapshot passes champion_options=None, the
walk guards out; the 4 Bard skillshot/area rows are the pre-existing
drift class already tallied), baseline NOT recaptured, Catalyst +
resource-ledger suites: 140 passed.

Follow-ups (recorded): the stale "no_damage" P label in
docs/wiki-full-entry-audit.json + reviewed-packets.json (regenerate
under the 08-08 module-authority semantics — no runtime impact); the
meep numbers are prose-only (a binary receipt would need
BardPSpiritMissile* game-file values — currently empty in the local
atoms); the 200-chime UI cap is unsourced; the recharge 8s base is
inferred; the meep slow + splash + chime event rules remain named
unmodeled boundaries.


### 4.49 P1 Package 3Z (2026-08-09): Heimerdinger W/E degraded multi-part rocket and grenade behavior

Heimerdinger's W (Hextech Micro-Rockets) and E (CH-2/CH-3X Electron
Storm Grenade) multi-part behavior is now typed-declared with
provenance receipts, the fail-loud missing-row guard landed, and the
unsupported multi-target claims receipted as named fail-closed denials
— never re-priced.

- THE INTEGRATION (documentary — the 3W/3X/3Y mirror): the typed
  ``HEIMER_W_ROCKETS_RULE`` (first_row_attribute "Initial Rocket Magic
  Damage", subsequent_row_attribute "Subsequent Rocket Magic Damage",
  the timing pins first 0.25 / subsequent 0.35 @ 0.08 interval, the
  bounds 1..5 default 5, source = W template rev 2864243 + parent
  4025016) rides the ``w_rockets`` option's state receipt, and
  ``HEIMER_E_GRENADE_RULE`` (base_row_attribute "Magic Damage",
  upgraded_values 100/200/300 + 60% AP, time_offset 0.6, one_instance,
  source = E template rev 2864389 + parent 4025016) rides
  ``e_upgrade``'s.  Both cached W/E leveling rows are DEGRADED (units
  arrays empty — the generic path can't attribute them; the module
  names the explicit rows, which resolve flat).
- SOURCING: W first 50..150 +55% AP + subsequent 10..30 +12% AP and E
  base 60..220 +60% AP are BINARY-CONFIRMED from the cached leveling
  rows; the E upgraded tuple 100/200/300 (+60% AP) is HALF-PARSED (the
  E[1] row's modifiers:[] — the numbers survive only in the attribute
  string, no atoms) — a declared module constant with provenance;
  0.25 = the cached castTime; 0.35/0.08/0.6 are module-authored timing
  pins with NO JSON home — declared in the receipts + flagged
  uncertified.  The W[1] Rocket Swarm (Rockets 2:5 / 6:20 / 135-225
  +45% AP rows) is half-parsed and UNMODELED — a named denial.
- FAIL-LOUD ROWS: ``_require_row`` in the module raises KeyError
  naming the champion + ability + attribute when a W/E leveling row is
  missing (cache corruption) — the silent zero-total_raw behavior is
  GONE (the C-pinned fail-closed contract).
- THE LEDGER SURFACE: ``_add_heimerdinger_w_e`` — an additive
  ``resource_ledger["w_e"]`` (kind "w_e") sub-section beside the mana
  account: one accepted "hit" receipt per engine damage_event (the W
  parts' swing times + the E impact — amounts = the raw values, e.g.
  150 + 30x4 + 300 at W5/R3/E-upgraded, with event_index + event_time
  identity) + the named fail-closed denials: rocket_fan_multi_target,
  grenade_bounce, grenade_control (stun/slow), turret_targeting
  (targeting/beam charge), upgraded_w_swarm, w_e_event_without_
  identity (missing_identity), plus the slot_unavailable /
  part_without_identity guards.  The declaration = the two typed rule
  receipts.  No breakdown row, no notes (the mana section's receipts
  surface stays the only top-level one).
- SCORE/RECEIPT PARITY + OPTIMIZER SAFETY: the walk is post-rotation,
  mode-invariant, additive (reads the breakdown damage_events — the
  same rows in full/scored/tuple); the surface is byte-identical under
  score_only; w_rockets/e_upgrade are search-invariant (the optimizer
  never varies champion_options); the walk changes no damage numbers.

Provenance (RLM-2 A): W/E damage + cooldown rows binary-confirmed
from data/champions.json (the degraded empty-units resolve flat);
55/55 Heimerdinger atoms hash-verified (13 W/E damage-row atoms carry
the degraded empty units verbatim; the half-parsed upgrade rows have
NO atoms — only placeholder rows atomized, fossilizing labels into
units); E[1] timing.control_duration_sequence [2.0, 1.5] exists; the
0.35/0.08/0.6 timings have no atom home; SOURCES rev 4025016 (parent)
+ 2864243 (W) + 2864389 (E) ≡ the full-entry audit (expected_effects
match the cached rows verbatim); the 2019 template bodies are not
locally verifiable (the values came from the 2026 parent parse).

RLM-2 audits: A (provenance; the two degradation classes — empty-units
+ half-parsed upgrades; the separation list), B (runtime; the accepted
stream = the per-damage_event engine-priced parts; the denial list;
the fail-loud row guard; the ledger sub-section placement; parity),
C (tests; 44-test matrix 36 PASS / 8 XFAIL pre-integration; all 8
flipped; 0 xfail remain; the E detail-text-not-a-denial pin).

Files: EDITED src/calculator/champions/heimerdinger.py (the typed
rules + option state receipts + _require_row + the promoted timing/
upgraded-E constants), damage.py (_add_heimerdinger_w_e — the hit
receipts + named denials + the additive w_e ledger sub-section; called
after the Bard walk), tests/test_heimerdinger_multihit.py (C-owned;
8 xfails flipped).

Gates: focused sanity 947 passed (2 known pre-existing app
rate-limiter flakes in batch context, pass isolated) + 3Z 44 passed,
full pytest run TWICE with stable results: 6406 passed + 16 xfailed
(6362 + 44 new) on both runs, black clean on src/ + tests/ + scripts/,
FULL-SRC pylint 9.55/10 — UNCHANGED (17 pre-existing E/F artifacts;
zero new findings), atomize run TWICE with content-identical results
(generated_at only), golden compare: 877 = the PRIOR state — ZERO new
Heimerdinger ledger deltas (the snapshot passes champion_options=None,
the walk guards out; the 5 Heimerdinger skillshot/area rows are the
pre-existing drift class already tallied), baseline NOT recaptured,
Catalyst + resource-ledger suites: 140 passed.

Follow-ups (recorded): the 0.35/0.08/0.6 timing pins + the upgraded-E
tuple are uncertified literals (the upgraded-E tuple could gain a
binary receipt only from a game-file atom — none exists locally); the
W[1] Rocket Swarm remains unmodeled (half-parsed); the upgraded-E mana
cost stays the base 85 (the wiki R prose "no mana cost" divergence is
pinned + flagged — NOT overridden, preserving existing behavior); the
E stun 1.5s is prose-only (not atomized); the E base 11s flat cooldown
vs the W 11..7 scaling.


### 4.50 P1 Package 4A (2026-08-09): K'Sante W Path Maker bonus-resistance / state behavior

VERDICT (B runtime + parent game-file verification): the W bonus
resistance scaling is a REAL AUTHORED EFFECT — game file
data/bin/characters/ksante.bin.json KSanteW: BaseDamage [15..195],
MaxHealthDamage 0.08, MaxHealthDamageResistRatio 0.0002 (= 2% per 100
bonus armor AND bonus magic resistance — mStat 1 = BonusArmor, mStat 6
= BonusMagicResist), RDamageIncreaseMin 0.1 / RDamageIncreaseMax 0.8
(the All Out true-damage fraction of the physical formula — the wiki
min/max true rows are exactly those fractions: 0.8%/0.2% = 0.1x of
8%/2%, 6.4%/1.6% = 0.8x).  The cached W rows carry the ratios ONLY
inside the degraded units text; the generic compound-unit resolver
MISATTRIBUTED them to the caster's TOTAL armor/MR (physical 9.8% of
maxHP at the fixture's 50/40 totals — 196 — instead of the correct
8.6% bonus attribution — 172; +24 raw overstatement; the same pattern
in the true range).  THE FIX: the typed reads price the resist terms
with the CASTER'S BONUS armor/magic resistance (the module's own P
marked-attack pattern), never the totals or the target's.

- THE INTEGRATION: ``_PathMakerRule``/``KSANTE_PATH_MAKER_RULE`` (the
  three row attributes, base 8% maxHP, the resist ratios 2.0/0.2/1.6
  percent per 100, the charge bounds 0..1 step 0.25 default 1.0, source
  = W template rev 3471720 + parent 4011715 + the game-file receipt)
  rides the ``w_charge`` option's state receipt; ``_require_row``
  fail-loud guards (KeyError naming champion/ability/attribute) for
  the three W rows; the typed reads in ``_path_maker``
  (flat + (base_pct + RATIO*(bonus_armor/100) + RATIO*(bonus_mr/100))/
  100 x maxHP for physical and the interpolated min/max true range in
  All Out); the All Out physical part stays UNTIMED (the pinned
  charge-timing asymmetry — B's 1-line timing fix NOT applied,
  preserving the pinned behavior).
- THE LEDGER SURFACE: ``_add_ksante_path_maker`` — an additive
  ``resource_ledger["w"]`` (kind "w") sub-section beside the mana
  account: one accepted "hit" receipt per engine-priced W part
  (amounts = the parse raws, part identity via part_index +
  damage_type + the true part's charge time; the untimed physical
  receipts carry time 0.0) + the named fail-closed denials:
  r_resist_conversion (the All Out armor/MR-to-AD conversion — state),
  w_missing_resist_state (bonus armor/MR absent -> priced 0 + denial,
  never a guess), w_multi_target_dash, w_knockback_stun_control,
  w_monster_damage_cap, w_health_threshold (the 65% threshold),
  w_event_without_identity (missing_identity), w_unavailable.  The
  declaration = the typed rule receipt.
- SCORE/RECEIPT PARITY + OPTIMIZER SAFETY: parse-time pricing only (no
  re-pricing); the walk is mode-invariant + additive; the surface is
  byte-identical under score_only (C's S9 matrix, 8 option combos);
  w_charge/all_out are search-invariant (the optimizer never varies
  champion_options).

Provenance (RLM-2 A was cancelled mid-run — its final ipython call
hung ~25 min with no toolResult; the cancellation reason was recorded
in /tmp/4a_helper_cancellations.txt.  ALL of A's assigned evidence was
independently verified by the parent before cancellation: the cached
W rows (Physical Damage [45..165] + [8] with the fossilized units;
min/max true [4.5..16.5]/[0.8] and [36..132]/[6.4] with 0.2%/1.6%; the
Monster Cap; Total Mixed), the 10 W abilities atoms (values + degraded
units + hashes read directly from data/atoms/abilities.json — the W
rows ARE atomized, the resist ratios only inside the units), the game
file (above), and the audit receipts (parent rev 4011715
@2026-04-22T20:20:34Z ≡ module SOURCES, W template rev 3471720
@2022-10-16T16:25:10Z, ready, no missing slots)).

RLM-2 audits: B (runtime; the misattribution verdict + the numeric
proof + the 6-denial list + the mode-invariance proof — reviewed), C
(tests; 40-test matrix 35 PASS / 5 XFAIL pre-integration; ALL flipped
with 10 re-pins to the fixed bonus attribution — the S1/S2/S4 typed
values via the new _typed_w helper, the S6 pinned-actual re-pinned to
the fix (196 -> 172 term), the flat-only xfail re-pinned to the
sourced full-term contract, the walk's expected amounts, and the
heal_omnivamp-row tolerance in the denial-sum pin), A (cancelled
mid-run; evidence verified by the parent — see above).

Files: EDITED src/calculator/champions/ksante.py (the typed rule +
option state + _require_row + the bonus-attributed typed reads),
damage.py (_add_ksante_path_maker — the hit receipts + named denials +
the additive w ledger sub-section; called after the Heimer walk),
tests/test_ksante_w_resistance.py (C-owned; 5 xfails flipped + 10
re-pins).

Gates: focused sanity 1006 passed (2 known pre-existing app
rate-limiter flakes in batch context, pass isolated) + 4A 40 passed,
full pytest run TWICE with stable results: 6446 passed + 16 xfailed
(6406 + 40 new) on both runs, black clean on src/ + tests/ + scripts/,
FULL-SRC pylint 9.55/10 — UNCHANGED (17 pre-existing E/F artifacts;
zero new findings), atomize run TWICE with content-identical results
(generated_at only), golden compare: 911 = 877 prior + 34 NEW K'Sante
W deltas — ALL EXPLAINED (the resist-attribution behavior fix: W
total_raw 317.0 -> 265.0 at lvl 11 no-items — the 52 raw total-armor
term removed (bonus = 0 with no items) — plus the parts mirror + 32
registered-fight rows (breakdown_totals/W + total_damage at lvl 11/18 x
4 builds x sustained/one-shot), every row the same -34.66/-50.66
mitigated delta class = 52/76 raw x 100/150; the 3 K'Sante
skillshot/area stamps are the pre-existing drift class), baseline NOT
recaptured, Catalyst + resource-ledger suites: 140 passed.

Follow-ups (recorded): the pre-fix W price overstated the resist term
via TOTAL-armor attribution (fixed); the fixture-visible magnitude was
+24 raw at bonus 20/10/totals 50/40; the R stat_buff engine mutates
the caller's stats dict in place (pre-existing quirk outside 4A — C
flagged; the parity tests use fresh stats per fight); the All Out
physical part timing stays untimed (pinned asymmetry; a future
timing-authority fix would add its damage_events + walk identity
times); the R armor/MR-to-AD conversion and the 65% threshold remain
named state.


### 4.51 P2 Slice 5 (2026-08-09): Gangplank W Remove Scurvy champion cleanse

HANDOVER §4.21's first champion cleanse is wired: the W cast IS the
cleanse activation (NO user option — the source supports the cast, not
an optional toggle; B's runtime decision, overriding C's w_time
candidate as unsourced control), riding the P2 Slice 4 item-cleanse
kernel.  The heal and the cleanse stay SEPARATE authored effects.

- THE TYPED DECLARATION: ``_RemoveScurvyRule``/``REMOVE_SCURVY_RULE``
  in the module (heal flat 45..145 + 90% AP + 13% missing health,
  cooldown 22..14, cost 60..100, target_scope self,
  excluded_control_kinds (airborne, knockback, knockup), source =
  W template rev 2864237 + parent 4002542 + the game file
  gangplank.bin.json (BaseHeal [20..170], PercentHeal 13,
  StatByCoefficient 0.9 AP, canCastWhileDisabled true,
  cannotBeSuppressed true) + the 4 atom hashes) + the
  ``_require_w_rows`` fail-loud guards (missing "Heal" row/modifiers
  raise naming the champion — the silent-zero path is gone).
- THE CLEANSE KERNEL: a SEPARATE champion declaration table
  (``CHAMPION_CLEANSE_SOURCES`` + ``CHAMPION_CLEANSE_DECLARATIONS`` in
  cleanse_eligibility.py — the Slice 4 ITEM table + its exact-set pins
  stay untouched) with the resolver fallbacks; one kind="cleanse"
  self-cast packet per W cast authored in participant_timeline's
  ``_support_effect_templates`` from the pair cast_timeline (cast time
  = the activation; W rank 0 -> no cast -> no packet); the Slice 4
  kernel applies the per-fight one-use latch (first cast decides vs
  the ACTIVE control intervals, truncate_intervals on BOTH ledgers,
  historical downtime kept, later controls untouched — no immunity),
  the self-scope castability (fires while CC'd; suppression ->
  caster_control_blocks_cleanse, use NOT consumed; airborne/
  knockback/knockup -> excluded_control_kind — the displacement
  override is a named boundary), the named denials
  (use_spent/control_not_active/unknown_control/target_not_selected/
  not_armed/missing identity), and the Slice 4 decision/use receipts
  (survival["cleanse"] + survival["cleanse_use"] +
  survival["cleanse_denied"]); the utility panel counts the cleanse
  (event_count + applied_dimensions ["cleanse"]).
- THE HEAL CARVE-OUT (the one behavior-fix kernel edit): the W heal
  (healing.py's E1 rule — flat + 90% AP + 13% MISSING health re-priced
  live at the cast) authors the typed ``cast_while_disabled`` flag; the
  survival gate exempts HEAL kinds carrying it from the crowd-control
  branch ONLY (stasis/invulnerable/untargetable still block — the
  Cleanse atom) — Remove Scurvy now fires while the caster is charmed/
  stunned (game canCastWhileDisabled), the spell's defining property.
- SCORE ADAPTER AGREEMENT: the compiled walk cannot model the interval
  truncation — the W cleanse packet fails closed with the NAMED
  receipts (``support_kind=cleanse`` via compiled_support_receipt +
  unrepresentable_template_receipt) and the fight is priced by the
  receipt walk — never silently re-priced (the compiled heal builder +
  the support-template builder copy the flag so the plain-heal
  representability + parity hold).
- W stays OUT of outgoing damage (total_raw 0 / no parts / no damage
  events — every mode); mana 60..100 + cd 22..14 receipted, never
  kernel-enforced as a recast gate (the engine scheduler + the one-use
  latch are the operative rules).

Provenance (RLM-2 A): the heal flat/AP/missing + cd/cost are
BINARY-CONFIRMED (gangplank.bin.json + the 4 ability atoms with
recomputed hashes); castability flags binary-confirmed (the QSS/
Mercurial pair); castTime 0.25 dual-confirmed; the cleanse SCOPE is
CC-only wiki-prose (the binary has no per-kind removal table); the
Stat-15 missing-health identity is unmapped in-repo (gap); cost
un-atomized (gap); the binary heal atom carries cd+bitmask, not the
heal numbers (the ability atoms are the numeric receipt).

RLM-2 audits: A (provenance; above), B (runtime; the NO-OPTION
decision + the activation semantics + the heal carve-out + the score
verdict + the fail-closed list — reviewed), C (tests; 43-test matrix
24 PASS / 19 XFAIL pre-integration; all flipped with the option-based
fixtures re-pinned to the W-cast contract (the activation = the cast
time; the no-option API contract; the deterministic simulate pins for
later-control + the score gates) — reviewed).

Files: EDITED src/calculator/champions/gangplank.py (the typed rule +
the require-row guards + the unused-import cleanup), healing.py (the
W heal's cast_while_disabled flag), cleanse_eligibility.py (the
champion sources + declaration + the resolver fallbacks),
participant_timeline.py (the per-W-cast cleanse packet authoring),
survival/actions.py (the typed cast_while_disabled field + mapping),
survival/transitions.py (the gate exemption, restructured to keep
R0916 off), survival/compile.py (the flag copies),
tests/test_gangplank_w_cleanse.py (C-owned; 19 xfails flipped + the
re-pin batch).

Gates: focused sanity 809 passed + 9 xfailed (2 known pre-existing
app rate-limiter flakes in batch context, pass isolated) + 4B 43
passed, full pytest run TWICE with stable results: 6489 passed + 16
xfailed (6446 + 43 new) on both runs, black clean on src/ + tests/ +
scripts/, FULL-SRC pylint 9.55/10 — RESTORED (the 4B gate edit
briefly pushed an R0916 over the threshold — restructured; the module
rule's R0902/C0116 fixed via a source property + docstring; zero net
new findings; the 17 pre-existing E/F artifacts unchanged), atomize
run TWICE with content-identical results (generated_at only), golden
compare: 911 = the PRIOR state — ZERO new Gangplank deltas (the
snapshot passes no champion_options; the heal/cleanse never touch
breakdown_totals; the 4 Gangplank skillshot/area rows are the
pre-existing drift class), baseline NOT recaptured, Catalyst +
resource-ledger suites: 140 passed.

Follow-ups (recorded): the cleanse scope is prose-only (no per-kind
binary table); the Stat-15 missing-health identity is unmapped; the W
cooldown is receipted, never enforced; the airborne displacement
override stays a named boundary (a blink/dash is not modeled); the
stasis cast is unmodeled (the item precedent — the heal stays blocked
under stasis); the pre-existing TESTING-flag leak from six ledger test
files (app rate-limiter flakes in combined runs) remains flagged.


### 4.52 P2 Slice 6 (2026-08-09): Rengar empowered W Battle Roar champion cleanse

HANDOVER §4.21's second champion cleanse is wired: the EMPOWERED-W
cleanse condition (source-supported) rides the Slice 4/5 champion-
cleanse kernel with the live Ferocity per-cast flag as the gate — NO
user toggle, NO base-W cleanse.

- THE CONDITION (B's decision + C's pins): the cleanse fires ONLY on
  LIVE-EMPOWERED W casts — the 3V Ferocity walk's per-cast flag from
  breakdown["ferocity"]["stack_events"] (slot + ordinal matched to the
  cast_timeline W row), NEVER the seeded p_ferocity alone (a Q-first
  rotation consumes the cap, so the seed-4 W@0 cast stays BASE; seed 3
  reaches the cap by Q@0's gain, so W@0 IS empowered).  The packet
  authoring in participant_timeline's _support_effect_templates reads
  the engine-published stack_events (the single source of truth — no
  re-derivation) with a fail-loud KeyError when W casts exist but the
  ferocity row is absent (never silently assume base).  Non-empowered
  W casts author NOTHING (absence — the same authoring gate as W
  rank 0).
- THE DECLARATION: CHAMPION_CLEANSE_SOURCES + CHAMPION_CLEANSE_
  DECLARATIONS += "Rengar W" (active_name "Battle Roar", self scope,
  excluded_control_kinds () — the wording "cleanses himself from ALL
  crowd control" carries NO displacement carve-out, unlike Gangplank's;
  cooldown gap receipted; heal None — the E8a grey-health heal is the
  separate authored heal; source = wiki W template rev 2864299 +
  parent 3993826 + the game file RengarWEmp canCastWhileDisabled true /
  cannotBeSuppressed true — the base RengarW record carries neither
  flag; the W DataValues rows are EMPTY in the local dump — the W
  numbers come from the wiki rows).  The one-use latch keys "Rengar W"
  (separate from "Gangplank W" by construction).
- THE HEAL INTERACTION (zero delta): the E8a grey-health heal stays
  byte-identical per cast (50% of post-mitigation incoming in the
  1.5s window, consume ratio 1.0, "grey health will not be consumed"
  note untouched).  The ordering property verified: the cleanse packet
  sorts BEFORE the grey-heal at the same timestamp (action_key tie-
  break) and the utility dispatch precedes the attacker gate — so on
  an empowered W cast while CC'd the cleanse fires, truncates the CC,
  and the heal at the same timestamp then passes the gate and lands —
  WITHOUT any cast_while_disabled delta on the heal (base-W heal
  behavior unchanged).
- SCORE ADAPTER AGREEMENT: identical to Slice 5 — the empowered-W
  packet fails closed with the NAMED receipts (support_kind=cleanse
  via both gates) and the fight is priced by the receipt walk; never
  a silent re-price.  The engine W/ferocity surface stays byte-
  identical full vs score_only (C's parity pins).
- The W damage (base 50..170 rank + 80% AP / empowered 50..240 level +
  80% AP / monster 65..137.65), the Ferocity ledger (3V), the existing
  options (p_ferocity only), the GP W + item cleanses — all untouched.

Provenance (RLM-2 A): the W base/empowered/monster damage + cooldown
are BINARY (leveling rows); the cleanse condition is the Ferocity-
Bonus prose + the game file flag pair (RengarWEmp ONLY — the binary
discriminator); the grey ratios (50%/1.5s/100% monster) are prose-only
(the binary carries the DataValue NAMES with empty arrays — monster
100% has zero code presence); the cleanse wording produces no atom;
the binary atom "stasis" tag is a keyword artifact shared by both
branches (the flag pair, not the tag, discriminates); 7/7 W atom
hashes recomputed OK.

RLM-2 audits: A (provenance; above), B (runtime; the live stack_events
seam + the no-heal-delta ordering proof + the score verdict + the
fail-closed list — reviewed), C (tests; 59-test matrix 44 PASS / 15
XFAIL pre-integration; all flipped with the pre-wiring pins re-pinned
(the couple's own ferocity semantics: seed 3 -> W@0 empowered at 0.0,
seed 4 -> W@10, Garen's control_not_active decisions, the duration
windows) — reviewed).

Files: EDITED src/calculator/cleanse_eligibility.py (the Rengar W
sources + declaration), participant_timeline.py (the empowered-W
packet authoring + the fail-loud missing-row guard),
tests/test_rengar_w_cleanse.py (C-owned; 15 xfails flipped + the re-
pin batch), HANDOVER.md.

Gates: focused sanity 812 passed + 7 xfailed (2 known pre-existing
app rate-limiter flakes in batch context, pass isolated) + 4C 59
passed, full pytest run TWICE with stable results: 6548 passed + 16
xfailed (6489 + 59 new) on both runs, black clean on src/ + tests/ +
scripts/ (transitions.py re-formatted — the Slice 5 gate block), FULL-
SRC pylint 9.55/10 — UNCHANGED (zero new findings), atomize run TWICE
with content-identical results (generated_at only), golden compare:
911 = the PRIOR state — ZERO new Rengar deltas (the 21 Rengar rows are
the 3V additive class already tallied; the cleanse lives in the couple
path the snapshot does not capture), baseline NOT recaptured, Catalyst
+ resource-ledger suites: 140 passed.

Follow-ups (recorded): the W DataValues are empty in the local binary
dump (the numbers rest on the wiki rows + the ability atoms); the
monster 100% grey ratio is unmodeled (prose-only); the binary "stasis"
atom tag is a keyword artifact (the RengarWEmp flag pair is the real
discriminator — a future atomizer pass could capture the flags); the
CCImmuneDuration 1.5 immunity mechanic is NOT modeled (no-immunity is
the pinned contract — later controls untouched).


### 4.53 P2 Slice 7 (2026-08-09): Milio R Breath of Life champion cleanse

HANDOVER §4.21's third champion cleanse is wired — the self + ALL
selected-teammates cast with the cast-inhibiting gate (the OPPOSITE of
the GP/Rengar carve-outs).

- THE SHAPE (B's decision): the R cleanse rides the EXISTING E8d heal
  packet as a **Mikael's-style marker** (heal + ``cleanse: True`` +
  ``cleanse_item: "Milio R"`` + ``cleanse_group``) — NOT a separate
  utility packet.  The R "cannot be used while affected by
  cast-inhibiting crowd control" (wiki effects[1] + the game file:
  MilioR carries NEITHER canCastWhileDisabled nor cannotBeSuppressed)
  therefore holds automatically: the attacker gate blocks the WHOLE
  cast (every recipient's heal+cleanse) while the caster is CC'd —
  use NOT consumed, nothing truncates (the Slice 4 R22 gated path).
  The fan-out (self + every selected teammate) propagates the marker
  with zero participant_timeline change.
- THE KERNEL DELTAS: the NEW ``target_scope "self_and_all_teammates"``
  in CleanseEligibility.decide (any authored recipient valid — the
  walk authors one packet per roster member from the E8d fan-out;
  each recipient's OWN control intervals decide at the activation) +
  the **per-cast group latch** (``cleanse_group`` on SurvivalAction —
  all recipients of ONE cast share ONE use; a second cast denies all
  its recipients use_spent + cleanse_denied) + the gated-use group
  skip (a blocked multi-recipient cast writes its use receipt once).
  The 65% tenacity for 3s stays utility state (never priced); the
  heal is E8d's separate authored effect (heal None on the
  declaration — the kernel never mints a second).
- THE DECLARATION: CHAMPION_CLEANSE_SOURCES/DECLARATIONS += "Milio R"
  (active_name Breath of Life, scope self_and_all_teammates,
  excluded (airborne, knockback, knockup) — the "non-airborne"
  wording's displacement family (contrast Rengar's EMPTY set),
  cooldown [160,145,130] receipted + gap False (fully sourced, never
  enforced — the engine's single-cast rule is the operative limit),
  heal None, source = R template rev 3535281 (2023 — flagged stale
  vs the parent 3892686; numbers match the binary) + the game file
  MilioR (HealBase 150/250/350 + 0.5 AP, TenacityAmount 0.65,
  cooldownTime, SelfAoe 700, NO castability flags) + the 3 ability
  atom hashes (838c3aab52b4e9c6 / f01d47304a7cab5a / 5c61af44e7eb944d).
- THE RANK-0 GATE: the R slot uses a NEW ``_rank_gated_no_damage``
  parser (packet_module) — an unlearned R is ABSENT (no cast row, no
  heal, no cleanse); the E8d heal rule gates on the rank too.  The
  generic no_damage behavior is UNCHANGED (the initial generic gate
  was reverted after its blast radius broke the CP10.4 batch pins +
  the Mikael's score parity — the opt-in per-slot parser is the
  narrow fix).
- SCORE ADAPTER AGREEMENT: identical to Slices 5/6 — the heal+marker
  fails closed with the NAMED receipts (support_cleanse via
  unrepresentable_heal_receipt + support_kind=cleanse via the
  template gate) and the fight is priced by the receipt walk; never a
  silent re-price.  The engine R surface stays byte-identical full vs
  score_only (C's parity pins).
- The W/E ally-support (Cozy Campfire lump + 25-tick self rule; Warm
  Hugs shield), the Q damage, the GP/Rengar/item cleanses, the
  Ferocity + grey-health packages — all untouched.

Provenance (RLM-2 A): the R heal 150/250/350 + 50% AP + cd 160/145/130
+ cost 100 are wiki+binary EXACT; the cleanse scope ("non-airborne") is
prose-only (the binary removal set is undecoded); the tenacity 65%/3s
is binary (amount unatomized); the castability (NOT castable while
cast-inhibiting CC'd) is wiki prose CONSISTENT with the binary (no
flags → the Mikael's-gated pattern); castTime "none" vs binary 0.713 +
effectRadius 700 vs castRadius 800 flagged; the R template receipt is
2y stale (2023 vs 2025 parent); 5 ability + 3 binary atoms recomputed
OK.

RLM-2 audits: A (provenance; above), B (runtime; the heal+marker
decision + the group latch + the scope mechanics + the score verdict +
the fail-closed list — reviewed), C (tests; 53-test matrix 38 PASS /
15 XFAIL pre-integration; all flipped with the re-pin batch (the
kernel-harness group fixtures, the gated-shape castability pins, the
rank-0 absence, the removed-tail pin, the same-timestamp heal quirk)
— reviewed).

Files: EDITED src/calculator/healing.py (the R heal's markers + rank
gate), cleanse_eligibility.py (the Milio R sources + declaration + the
self_and_all_teammates scope branch), survival/actions.py (the
cleanse_group field + mapping), survival/transitions.py (the group
latch in _apply_cleanse + the gated-use group skip),
champions/packet_module.py (_rank_gated_no_damage + the no_damage
slot_parsers consult — the generic gate reverted), champions/milio.py
(the rank-gated R parser), tests/test_milio_r_cleanse.py (C-owned; 15
xfails flipped + the re-pin batch), tests/test_rengar_w_cleanse.py
(the tables pin += Milio R), HANDOVER.md.

Gates: focused sanity 1052 passed + 6 xfailed (2 known pre-existing
app rate-limiter flakes in batch context, pass isolated) + 4D 53
passed, full pytest run TWICE with stable results: 6601 passed + 16
xfailed (6548 + 53 new) on both runs, black clean on src/ + tests/ +
scripts/, FULL-SRC pylint 9.55/10 — UNCHANGED (zero new findings),
atomize run TWICE with content-identical results (generated_at only),
golden compare: 911 = the PRIOR state — ZERO new Milio deltas (the
rank-gated R keeps the original detail wording byte-identical; the 2
Milio skillshot/area rows are the pre-existing drift class), baseline
NOT recaptured, Catalyst + resource-ledger suites: 140 passed.

Follow-ups (recorded): the R template receipt vintage (2023 — re-pull
under a future patch); the castTime "none" vs 0.713 + the 700/800
radius discrepancy; the tenacity amount + the cleanse scope are
unatomized (a future atomizer pass could capture TenacityAmount + the
removal set); the 0.75s post-cast self-lock is unmodeled; the game's
"affects untargetable units" note is unmodeled (the kernel's
untargetable gate blocks the cast — a named boundary).


### 4.54 P2 Slice 8 (2026-08-09): Dr. Mundo P Goes Where He Pleases (champion cleanse + canister)

HANDOVER §4.21's fourth champion cleanse is wired — as a RESIST, not a
truncation: the passive IMMUNITY consumes the next hostile
immobilizing control BEFORE it ever applies.

- THE SEMANTIC (B's decision + C's pins): the wiki "gains immunity to
  the next hostile immobilizing effect" — the effect NEVER applies (no
  interval, no downtime, no crowd_control_until change; removed_
  controls [] and downtime_before == after == 0 — an immunity, never
  a truncation).  The resist gate sits INSIDE _apply_crowd_control
  after the spell-shield/Black-Shield gates (their priority holds)
  and before the interval application.  The trigger scope: the
  immobilizing kinds = CONTROL_BLOCKING_KINDS minus polymorph (the
  wiki immobilize atom — slow/ground pass through and never consume
  the immunity); hostile = the attacker's team != the subject's.
- THE ARM: a new standalone kind CROWD_CONTROL_RESIST + the
  participant-timeline t=0 arm packet (pre-damage priority -2.0 —
  authored for "Dr. Mundo"/"DrMundo", the display-name fix after the
  first probe) with a per-fight one-shot latch (the cooldown 60->15
  receipted, never enforced; the wiki linear row + the game step
  function's agreement at levels 1/18 flagged).  The arm is
  REPRESENTABLE in the compiled walk (it only sets the armed state;
  the resist gate is the shared kernel — the compiled support builder
  maps the kind, so Dr. Mundo roster fights keep the compiled path
  instead of falling back).
- THE COST + CANISTER: the resist pays 4% CURRENT health (the kernel-
  internal subtraction with the shared lethal bookkeeping); the
  canister drop is receipted (525 units / 7s lifetime / 115 pickup
  radius / 15s refund — game DrMundoP DataValues, binary-confirmed);
  the pickup heal (4% MAX health) + the enemy destruction are NAMED
  unsupported timings (no movement model — no auto-pickup, no user
  toggle — the drop heals nothing).
- THE RECEIPTS: the Slice 4-7 cleanse-shaped row (eligible/item
  "Dr. Mundo P"/removed_controls []/downtime 0/0/use_consumed) +
  cleanse_use + passive_cost (percent/amount/health_before/after) +
  canister + pickup (supported False) + passive_cooldown + the
  passive_state (armed) + the crowd_control_resisted list — all
  assembled into the survival rows.
- THE DECLARATION: CHAMPION_CLEANSE_SOURCES/DECLARATIONS += "Dr.
  Mundo P" (active_name Goes Where He Pleases, scope self, NO
  exclusions — every immobilizing kind, cooldown row 60->15 + gap
  False, heal None, source = parent rev 4007950 + the game file
  (CurrentHealthLoss/MaxHealthGain/refund/lifetime/range + the -9
  breakpoints) + the timing.cooldown atom hash 8953fa74569fe1ab).
- THE MODULE: P stays SLOT-ABSENT (the golden stays zero-delta) but
  the docstring + ASSUMPTIONS now document the modeled immunity vs
  the named-unsupported pickup/destruction + the unmodeled innate
  regen (the "documented deliberate absence" replaced by the bounded
  implementation per the completion rule).
- SCORE ADAPTER: the arm compiles (representable); the resist gate +
  the cost run in the shared kernel (both adapters — full == score by
  construction; C's parity pins).  The resist receipts are score-
  ledger-inert (the score never mints support value from them).

Provenance (RLM-2 A): every P numeric is BINARY-CONFIRMED (cost 0.04
current, heal 0.04 max, refund 15s, lifetime 7s, range 525, pickup
radius 115, drop angle 70, the cooldown formula, the regen formulas —
the regen rows recomputed exactly); the trigger scope + the enemy-
destroy + the respawn reset are WIKI-PROSE-ONLY (scripted in the
uncached game Lua); the cooldown cache row (linear 60->15) vs the game
step function (60/51/42/33/24/15) agree only at levels 1/18 — flagged;
the 40-value regen row is levels 1-40 (the module's 18/20-level slice
receipted); 4 ability atoms + 1 binary atom hash-verified; NO atoms
for the cost/heal/refund/range (prose — receipted from the game file
instead); the P template receipt is 2021-stale (vs the 2026 parent).

RLM-2 audits: A (provenance; above), B (runtime; the resist-not-
truncate decision + the pre-application intercept + the arm priority +
the canister-timing decision (b) + the score verdict + the fail-closed
list — reviewed), C (tests; 55-test matrix 40 PASS / 15 XFAIL pre-
integration; all flipped with the re-pin batch (the harness arm, the
cost health_before evaluation, the score parity shape, the level-1
harness cooldown, the tables pins) — reviewed).

Files: EDITED src/calculator/survival/actions.py (the kind + the
standalone entry), transitions.py (_apply_mundo_p_resist +
_apply_crowd_control_resist + the resist gate + the dispatch),
compile.py (the arm's representable gate + the support-builder kind
mapping), receipt_state.py (the new survival-row keys), delivery_
eligibility.py (the arm priority -2.0), participant_timeline.py (the
Dr. Mundo arm authoring), cleanse_eligibility.py (the "Dr. Mundo P"
sources + declaration + the mirror), champions/dr_mundo.py (docs +
ASSUMPTIONS), tests/test_dr_mundo_passive.py (C-owned; 15 xfails
flipped + the re-pin batch), tests/test_rengar_w_cleanse.py +
tests/test_milio_r_cleanse.py (the tables pins += Dr. Mundo P),
HANDOVER.md.

Gates: focused sanity 1011 passed + 7 xfailed (2 known pre-existing
app rate-limiter flakes in batch context, pass isolated) + 4E 55
passed, full pytest run TWICE with stable results: 6656 passed + 16
xfailed (6601 + 55 new) on both runs, black clean on src/ + tests/ +
scripts/, FULL-SRC pylint 9.55/10 — UNCHANGED (zero new findings),
atomize run TWICE with content-identical results (generated_at only),
golden compare: 911 = the PRIOR state — ZERO new Dr. Mundo deltas (P
stays slot-absent; the single DrMundo row is the pre-existing
skillshot drift class), baseline NOT recaptured, Catalyst +
resource-ledger suites: 140 passed.

Follow-ups (recorded): the trigger scope + enemy-destroy + respawn
reset are prose-only (the uncached game Lua would be the receipt); the
cooldown row vs step-function discrepancy (the game is authoritative
at levels 16-18); the innate regen (effects[0]) stays unmodeled
self-sustain; the canister pickup + destruction remain named
unsupported (a future movement model could land them); the same-cast
NESTED-damage prevention (the wiki notes) is a named boundary (only
same-cast CONTROL packets are blocked now); the P template receipt
vintage (2021) flagged for a future re-pull.


### 4.55 P2 Slice 9 (2026-08-09): Olaf R Ragnarok (champion cleanse + crowd-control immunity)

HANDOVER §4.21's FIFTH and final champion cleanse is wired — the cast
CLEANSES the active controls AND opens a 3s IMMUNITY window, with the
bonus-stat receipts separate.

- THE ACTIVATION: the R cast IS the activation (timed 0.5 / one_rotation
  0.0 — the deterministic engine cast_timeline); NO toggle, NO typed
  option (the completion rule: only if the input contract supports it —
  it does not need one); the R rank gate (the Milio/rank-gated no_damage
  precedent) removes the rank-0 cast entirely.
- THE CLEANSE: a kind-"cleanse" packet per R cast (the Slice 4 kernel —
  the "Olaf R" declaration: self scope, excluded the displacement family
  (airborne/knockback/knockup — the notes' blink/dash carve-out), cd
  100/90/80 receipted never enforced, heal None) — fires while CC'd
  (the game flag pair canCastWhileDisabled + cannotBeSuppressed; the
  utility-before-gate dispatch), suppression ACTIVE at the cast denies
  the cleanse (caster_control_blocks_cleanse, use NOT consumed); the
  SpecialCase_StasisLocked stasis lock is a named boundary (no kernel
  gate for support packets — adding one would change the QSS/Mercurial
  contract).
- THE IMMUNITY: a duration-armed window on the Slice 8
  crowd_control_resist kind (the arm carries duration 3.0; the kernel
  arms state["ragnarok_immunity"] {source, start, until, blocked,
  decisions} + a gate inside _apply_crowd_control between the grants
  and the Mundo gates — blocks EVERY hostile blocking control in
  [cast, cast+3) end-exclusive, including the displacement family
  (Trait_CCImmune; the cleanse's carve-out applies only to already-
  active displacement), no cost, no latch-off).  The grants/Black-
  Shield path was REJECTED (shield-coupled — the immunity would die at
  the first damage tick or invent a shield).  The arm is representable
  in the compiled walk (full == score agree on the blocking).
- THE STAT RECEIPTS (separate authored effects): armor/MR 10/15/20 via
  kind-"stat_buff" packets (3s, receipted never consumed by
  mitigation); the first-second MS 20/45/70 via kind-"movement" (1s,
  the utility panel's speed_percent_seconds; the facing/2000-unit
  condition prose-only); the bonus AD 10/20/30 + 25% total AD + the
  10% size + the 2.5s duration-extension have NO kernel fields —
  receipted named-unsupported (module constants + the declaration
  wordings + the game DataValues; never applied — the fight-long
  parse-side stat_buff path was NOT used, it would misprice the 3s
  window).
- SCORE ADAPTER: the cleanse/stat_buff/movement packets fail closed
  with the named receipts (support_kind=cleanse / stat_buff /
  movement) → the receipt-walk fallback; the immunity arm compiles —
  never a silent re-price.

Provenance (RLM-2 A): every R numeric is ≥2-evidence confirmed (3s
Duration, Resists 10/15/20, FlatAD 10/20/30 + PercentTotalADAmp 0.25,
Haste 20/45/70 + HasteDuration 1.0, DurationExtension 2.5, cooldownTime
100/90/80, mana 100 — wiki + olaf.bin.json OlafRagnarok + the 5 ability
atoms hash-verified); the castability flag pair binary-confirmed; the
size 10% + the MS facing/2000-unit condition + the airborne carve-out +
the debuff scope + the extension triggers are PROSE-ONLY (scripted in
the uncached Lua); the wiki castTime "none" vs the binary castFrame 13
discrepancy flagged; effects[2] wiki leveling is half-parsed ([]).

RLM-2 audits: A (provenance; above), B (runtime; the cleanse+window
combination + the duration-armed resist + the grants-path rejection +
the stat surfaces + the score verdict — reviewed), C (tests; 69-test
matrix 52 PASS / 17 XFAIL pre-integration; all flipped with the re-pin
batch (the ragnarok_immunity row key, the rank-0 absence, the wired
charm truncation, the resolver, the score gates, the tables pins) —
reviewed).

Files: EDITED src/calculator/champions/olaf.py (the rank-gated R +
the Ragnarok constants), cleanse_eligibility.py (the "Olaf R" sources +
declaration), participant_timeline.py (the per-R-cast authoring: the
cleanse + immunity arm + stat_buff + movement packets; the rank from
the request's ability ranks), survival/transitions.py (the duration-
armed window branch in _apply_crowd_control_resist + the ragnarok gate
in _apply_crowd_control), survival/receipt_state.py (the ragnarok_
immunity survival-row key), tests/test_olaf_r_cleanse.py (C-owned; 16
xfails flipped + the re-pin batch), tests/test_dr_mundo_passive.py +
tests/test_rengar_w_cleanse.py + tests/test_milio_r_cleanse.py (the
tables pins += Olaf R), HANDOVER.md.

Gates: focused sanity 1137 passed + 7 xfailed (2 known pre-existing
app rate-limiter flakes in batch context, pass isolated) + 4F 69
passed, full pytest run TWICE with stable results: 6725 passed + 16
xfailed (6656 + 69 new) on both runs, black clean on src/ + tests/ +
scripts/, FULL-SRC pylint 9.55/10 — UNCHANGED (zero new findings),
atomize run TWICE with content-identical results (generated_at only),
golden compare: 911 = the PRIOR state — ZERO new Olaf deltas (the
rank-gated R keeps the original detail wording byte-identical; the 2
Olaf skillshot/area rows are the pre-existing drift class), baseline
NOT recaptured, Catalyst + resource-ledger suites: 140 passed.

Follow-ups (recorded): the size 10% + the MS facing/2000-unit condition
+ the airborne carve-out + the debuff scope are prose-only (the uncached
Lua); the stasis-lock is a named boundary (a future kernel gate would
change the QSS/Mercurial contract); the AD + size + 2.5s extension are
receipted named-unsupported (a future SurvivalAction field could land
them); the duration-extension triggers (on-hit / Reckless Swing) stay
unmodeled; the wiki castTime "none" vs the binary castFrame 13 flagged.
With Slice 9, HANDOVER §4.21's champion-cleanses follow-up list
(Gangplank W, Rengar W, Milio R, Dr. Mundo P, Olaf R) is COMPLETE.


### 4.56 P1 Slice 10 (2026-08-09): Ashe Focus live stack lifecycle

The typed Ashe Focus rule's LIVE per-attack gains are now wired — the
rotation resolver's per-swing feed gap is closed by a documentary walk
over the engine's already-priced swing stream.

- THE WALK: ``_feed_ashe_focus_stack`` + ``_add_ashe_focus`` in
  damage.py (called after the K'Sante walk; the identity gate = the
  module's Q entry name "Ranger's Focus" OR the explicitly passed
  q_active-False override — the walk must never run for another
  champion's Q; Q rank 0 (unlearned) returns).  The seed comes from
  the existing q_focus_stacks option (clamped 0-4); the accepted
  stream = the auto-attack swings from breakdown["auto_attacks"]
  ["damage_events"] (each swing's time + index identity — the
  on-hit riders never mint Focus, the cached Runaan's note); the
  Q-activation CONSUME at the Q cast time (the live wiki cost box
  "30 Mana + 4 Focus" — B's correction to C's no-consume pin: the
  reviewed cache prose alone lacks the consume language, the cost-box
  receipt is the binding evidence) sorts BEFORE the same-timestamp
  swings; the fight-end expiry materialization via the new public
  TimedStackState.materialize_expiries wrapper.
- THE KERNEL SEMANTICS (all as executed by the typed rule): +1 per
  swing, cap 4, the 4s window refreshing on subsequent attacks, the
  1/s step-down (the first step AT the deadline, then 1/s), cap noop
  (a capped attack does NOT refresh), NO combat extension (0.0 — the
  Rengar 10s freeze is the only champion extension).
- THE SURFACE: the additive resource_ledger["focus"] sub-section
  (kind "focus", the Rengar-shaped receipts with the gain/consume/
  at_cap/below_cap rows + the state_transitions, the declaration) —
  the real mana account is NEVER replaced; the breakdown["focus"]
  informational row (count/starting/closing/stack_duration/
  combat_extension_seconds/stack_events/state_transitions); the
  notes; the named fail-closed denials
  (auto_attack_without_identity/missing_identity +
  unsupported_focus_source:ability_cast + :on_hit).
- NO RE-PRICING: the walk never writes ability_damages["Q"] (unlike
  the Rengar ferocity_parts coupling) — the parse-time gate + the
  flurry/AS pricing stay exactly as the module prices them; the
  existing options (q_focus_stacks/q_active) keep their roles; NO new
  option.
- FAIL-LOUD ROWS: ``_require_q_rows`` in ashe.py raises KeyError when
  the "Bonus Attack Speed"/"Total Damage Per Flurry" rows are missing
  (the silent-zero fallback is gone).

Provenance (RLM-2 A): the cap 4 + the 4s window + the 1/s drain + the
AS 20-60% + the flurry 110-130% AD + the cost 30 + the NO cooldown
(Trait_NoCooldown — the cache null is not a loss) are BINARY-confirmed
(ashe.bin.json AsheQ: MaxStacks/StackDuration/TimerDuration/
StackFalloffDuration/BonusAS/DamagePerStrike/ShotsPerStrike); the
gain-per-attack + the refresh + the capped-no-refresh semantics are
prose-only (script-driven); the 6s Q active window (BuffDuration) is
NOT modeled (a named boundary — the model's Q-window-is-permanent
pin); the Q template rev 2863918 + the parent 4015971 receipts; the
4 Ranger's Focus atoms + the Focus-window atom hash-verified (the
timing.active_duration atom mislabels the 4s Focus window as the
active duration — flagged).

RLM-2 audits: A (provenance; above), B (runtime; the consume-on-
activation correction + the auto-stream seam + the kernel semantics +
the score verdict — reviewed), C (tests; 50-test matrix 41 PASS / 9
XFAIL pre-integration; all flipped with the re-pin batch (the consume
rows, the identity gate, the q_active-False fixtures, the scheduled
step gaps, the swing-time tolerance) — reviewed).

Files: EDITED src/calculator/damage.py (_add_ashe_focus +
_feed_ashe_focus_stack + _add_focus_denial + the top-level
ASHE_FOCUS_STACK_RULE import + the call), state_lifecycle.py (the
public materialize_expiries wrapper), champions/ashe.py
(_require_q_rows), tests/test_ashe_focus_lifecycle.py (C-owned; 9
xfails flipped + the re-pin batch), HANDOVER.md.

Gates: focused sanity 1183 passed + 6 xfailed (2 known pre-existing
app rate-limiter flakes in batch context, pass isolated) + 4G 50
passed, full pytest run TWICE with stable results: 6775 passed + 16
xfailed (6725 + 50 new) on both runs, black clean on src/ + tests/ +
scripts/, FULL-SRC pylint 9.55/10 — RESTORED after the walk's refactor
(the 31-local/70-statement function split into the feed helper + the
denial helper; the in-function import moved to the top; the 5-arg
record closure; zero net new findings), atomize run TWICE with
content-identical results (generated_at only), golden compare: 927 =
911 prior + 16 NEW informational focus rows — ALL EXPLAINED (the
breakdown_totals/focus 0.0 rows on the 16 registered Ashe fights — the
same additive informational class as the 3V ferocity rows), baseline
NOT recaptured, Catalyst + resource-ledger suites: 140 passed.

Follow-ups (recorded): the gain-per-attack + refresh + capped-no-
refresh semantics are prose-only (script-driven — verify against the
game on patch updates); the 6s Q active window is unmodeled (the
model's Q-window-is-permanent pin; a future windowed-Q slice could
land it); the timing.active_duration atom mislabels the Focus window
(flagged for the atomizer); the "while Ranger's Focus is inactive"
prose clause is noted (the model cannot honor it without the 6s
window).


### 4.57 P1 Slice 11 (2026-08-09): Ashe Q six-second active window + the atom label correction

The Q-window-is-permanent pin is replaced by the TIMED 6s active window,
and the mislabeled Focus-window atom is corrected.

- THE WINDOW: the Q entry's auto_attack_override now carries
  ``active_duration: 6.0`` (the game file AsheQ BuffDuration 6.0 flat at
  every rank + the cached effect-1 prose "Active: For 6 seconds..."; the
  module constant ASHE_Q_ACTIVE_DURATION_SECONDS beside the StackRule
  receipt).  The engine prices the window [cast_start, cast_start+6)
  end-exclusive: the autos ride the base rate before the cast, the
  buffed rate + the flurry ratio inside the window, then the base rate +
  the normal 1.0 ratio from the window end (Frost Shot's crit-as-bonus
  stays on for every swing).  The floor-count convention applies per
  phase (the in-window count capped at the fight end — the 5s sustained
  fights stay ZERO-delta in the golden).
- THE FOCUS WALK (4G) under the window: the "while Ranger's Focus is
  INACTIVE" clause is honored — the in-window swings gain NOTHING (a
  named denial reason "active_window", distinct from at_cap, the stack
  never mutates) and the gains resume at t >= the window end.  The
  consume-on-activation + the 4s Focus stack window + the 1/s step-down
  stay the separate clocks.
- THE ATOM CORRECTION: the effect-0-only atomizer scan mislabeled Ashe
  Q's 4s Focus window as "timing.active_duration".  An EXPLICIT map
  (_FOCUS_WINDOW_EFFECTS + _FOCUS_WINDOW_ACTIVE_EFFECTS — NOT a keyword
  rule, 61 genuine actives mention stacks) relabels the Focus window to
  ``timing.stack_duration`` [4.0] (hash c11240f633391d49, evidence
  "stack duration@effects[0].description") and extracts the real 6s
  active window as ``timing.active_duration`` [6.0] (hash
  468689debc47d9b6, "active duration@effects[1].description"); every
  other champion's atoms stay byte-identical.
- SCORE/OPTIMIZER: one kernel prices the window (the score path
  structurally identical — the 10s byte-parity tests); no new option;
  the existing q_active/q_focus_stacks semantics preserved.

Provenance (RLM-2 A): the 6s window is BINARY (BuffDuration 6.0 × 7
ranks) + the cache prose; the Focus window 4s + the drain 1/s + the AS
20-60% + the flurry 110-130% AD all binary+cache agree; the cooldown
null vs binary 0 (Trait_NoCooldown) noted; the first-flurry 20% bonus
(mCoefficient 0.25/1.25) unmodeled; the 4 atoms hash-verified.

RLM-2 audits: A (provenance; above), B (runtime; the per-swing window
seam + the three-phase schedule + the floor-count convention + the
atom map + the score verdict — reviewed), C (tests; 59-test matrix 45
PASS / 14 XFAIL pre-integration; all flipped with the re-pin batch (the
engine-convention counts 7+3, the total 806.67, the corrected atom
records, the wired boundary/denial pins) — reviewed).

Files: EDITED src/calculator/champions/ashe.py (the 6s constant + the
override's active_duration), damage.py (the FightState window fields +
the piecewise AS/count + the three-phase schedule + the per-swing ratio
+ the Focus walk's active_window denials), atomizer_domains.py (the
explicit focus-window map), data/atoms (regenerated — Ashe Q now 17
rows), tests/test_ashe_q_active_window.py (C-owned; 14 xfails flipped +
the re-pin batch), tests/test_ashe_focus_lifecycle.py + tests/test_e3_
stacks_2.py (the windowed re-pins: the 10s/14s post-window gains, the
closing 3, the 5s e3 fixtures), HANDOVER.md.

Gates: focused sanity 1267 passed + 6 xfailed (2 known pre-existing
app rate-limiter flakes in batch context, pass isolated) + 4H 59
passed, full pytest run TWICE with stable results: 6834 passed + 16
xfailed (6775 + 59 new) on both runs, black clean on src/ + tests/ +
scripts/, FULL-SRC pylint 9.55/10 — UNCHANGED (zero new findings),
atomize run TWICE with content-identical results (generated_at only),
golden compare: 928 = 927 prior + 1 NEW row — the Q override's
active_duration 6.0 parse row (fully explained; the 5s registered
fights stay ZERO-delta — the floor-count cap), baseline NOT
recaptured, Catalyst + resource-ledger suites: 140 passed.

Follow-ups (recorded): the first-flurry 20% bonus (the mCoefficient
0.25/1.25) stays unmodeled; the Fiendhunter/ultimate-auto-buff
coexistence with the Q window is a named boundary (the Q branch wins);
the 6s window is anchored at the Q cast time (the [W,Q,R] order's
pre-cast segment is floor-dropped); the cache cooldown null vs the
binary 0 noted.


### 4.58 P1 Slice 12 (2026-08-09): Jayce W per-basic-attack mana restore — certification + the denied-cast budget repair

The champion-authored per-auto restore seam (Jayce's W passive, "Mana
Restored" 15/17/19/21/23/25) is CERTIFIED end-to-end, and the runtime
seam's ONE genuine defect is repaired.

- THE ACCEPTED STREAM: every modeled ordinary basic attack restores
  (both stances — an explicit module interpretation: the passive text
  and the binary ManaGain live on the hammer W only, neither source
  states stance gating), at its own swing time i/rate, amount = the
  ranked atom value (15-25 by W rank; the binary ManaGain ranks 1-6
  agree, index 0 is the 13.0 unleveled placeholder), tier 0 (before a
  same-time cast spend), CAPPED at the max mana (overflow is receipted
  reason "CAPPED", current pinned at maximum, no spill).  Hyper Charge
  burst autos ALSO restore — each in-window swing at cast_time+(k+1)/
  burst_as, gated on its arming cast being ACCEPTED (a denied cast
  mints arming_cast_denied denial receipts, never gains; an
  accepted-but-out-of-window cast's swings simply produce no row — the
  gating happens at schedule-pop, a named asymmetry).  Rank 0: no W,
  no declaration, no section.
- THE R1 REPAIR: the pre-admission schedule subtracted every planned
  burst cast's burst time from the ordinary count — INCLUDING
  later-denied casts, which never fire, so their budget shrank the
  ordinary restore stream (a real auto's mana was lost; the slice's own
  test had pinned the undercount 3 vs the auto row 4).  The denial
  branch now returns the denied cast's burst time to the budget on its
  first swing (_return_denied_burst_budget + _planned_burst_seconds;
  the ordinary rows mint at the current count's continuation, the
  engine's post-admission ordinary stream is uninterrupted).
- DEFERRED (documented xfail "awaiting P1-12 HoB/LT per-swing restore
  timing"): the restore walk runs before the HoB/Lethal-Tempo schedule,
  so restore times ride the uniform base schedule while damage events
  ride the rune-adjusted ones (counts agree, times diverge).  Reordering
  the scheduling is out of minimal scope.
- SOURCES (RLM-2 A, hash-verified): wiki cache W[0].effects[0]
  leveling[0] "Mana Restored" [15,17,19,21,23,25] == the game binary
  JayceStaticField ManaGain [13,15,17,19,21,23,25] (index 0 placeholder)
  == the atom ability.mana _restored bfeb0d88945a263e (recomputed 26/26
  Jayce atoms match; the runtime read re-verifies the hash).  Revision
  receipt: wiki-full-entry-audit Jayce page 573196, revision 4008136,
  2026-04-13T19:03:09Z — matches the module SOURCES.  Gaps disclosed:
  both-stances + burst-coverage are module interpretations (source-
  silent); staleness.json does not game-map the row; the Hyper Charge
  duration 4.0s wiki vs 3.6s binary stays unresolved (out of scope).
- PUBLIC SURFACE: resource_ledger receipt {owner, kind mana,
  operation gain, amount, time, source "Jayce W passive (Mana
  Restored)", sequence, tier 0, atoms, current/maximum before/after,
  accepted, reason accepted|CAPPED, detail {slot W, auto_index,
  kind ordinary|swing + arming identity}}; auto_restore section
  {declaration {amount, source, atoms}, denials}; score path
  byte-identical on the ledger surface (display-only per-cast rows
  skipped), restore never enters total_damage (the optimizer is
  affected only through cast admission).
- FILES: EDITED src/calculator/damage.py (the schedule's per-swing
  burst_seconds + the denial branch's budget return + the two small
  helpers; jayce.py NOT touched — its seam was already complete and
  certified), tests/test_jayce_w_mana_restore.py (C-owned, 30 tests:
  29 PASS + 1 xfail; one re-pin 3→4 for the R1 fix), HANDOVER.md.
- GATES: sanity 951 passed + 2 known pre-existing app rate-limiter
  flakes + 1 xfail; full pytest TWICE stable: 6863 passed + 17 xfailed
  (6834 + 29 new; the 17th xfail is the HoB timing), black clean,
  FULL-SRC pylint 9.55/10 UNCHANGED (zero new findings), atomize twice
  content-identical (manifest only), golden compare: 928 rows = 927
  accumulated (3V-4G, all explained) + 1 Ashe active_duration (4H) —
  ZERO new from this slice (R1 is runtime accounting only; the Jayce
  parse row resource_restore_per_auto + the Q/W area_damage rows
  pre-date this slice), baseline NOT recaptured, Catalyst +
  resource-ledger suites: 140 passed.

Follow-ups (recorded): the HoB/LT per-swing restore timing (the xfail);
the accepted-but-out-of-window cast's silence vs the denied cast's
denial receipts (the named asymmetry); the both-stances + burst-
coverage interpretations rest on the module ASSUMPTIONS; the Hyper
Charge 4.0s vs 3.6s duration discrepancy (HANDOVER §4.23).


### 4.59 P1 Slice 13 (2026-08-09): Ezreal W Essence Flux mark refund — certification + the 4s mark-window repair

The Ezreal mark-refund seam is CERTIFIED end-to-end, and the two
defects the runtime audit proved are repaired: the un-enforced 4s mark
window (D1 — the engine refunded marks detonated more than 4s after
arming; proven with its own schedule: a W-only chain's 5.583s gaps
minted 110-refunds the in-game marks would never pay) and the
multi-declaration fail-open (D2 — more than one mark_refund slot was
not rejected).

- THE ACCEPTED STREAM: an accepted ability cast consumes the OLDEST
  pending mark (FIFO pop(0); every cast assumed to hit) and refunds 60
  (the flat, rank-invariant, no atom — the binary ManaReturn 60x7 + the
  wiki prose) PLUS the detonating cast's ACTUAL paid cost (Actualizer
  discount included), at the detonating cast's timestamp, AFTER its
  spend in the receipt stream (cast, hit, refund — it can only enable
  LATER casts, incl. same-timestamp ones via the restore tier), CAPPED
  at the max mana.  A W cast both detonates (if pending) and arms; the
  pure W chain's gaps (5.583s) EXPIRE the marks — each W receipted
  mark_expired, nothing refunded, the last mark undetonated (the
  end-of-fight receipt distinguishes mark_expired (window elapsed
  before the end) from mark_undetonated).  Denied casts never spend,
  never arm, never consume (the mark persists past them); the
  w_mark_detonation=basic_attack option arms nothing and refunds
  nothing.  Rank 0: no W, no marks, no section.
- THE WINDOW (R1): W_MARK_WINDOW_SECONDS = 4.0 pinned beside the flat
  (cache prose "marks ... for 4 seconds" + the binary DetonationTimeout
  4.0 + the atom timing.active_duration b32849b968950b8e); the decl
  carries window_seconds (validated finite > 0, fail closed); the
  consumption expires a mark when cast_time - arm_time > window + EPS
  (end-exclusive-with-epsilon; the expired cast still arms its own
  mark — the if/else restructure keeps the arming after the expiry
  receipt); the fight-end pending-mark pass receipts mark_expired vs
  mark_undetonated.
- THE MULTI-DECLARATION GUARD (R2): _mark_refund_decl_for_state raises
  "multiple mark_refund declarations (Q, W)" on more than one declaring
  slot (mirrors _auto_restore_decl; dormant today — only ezreal.py
  declares).
- DEFERRED (documented xfails): target-side spell shields / Block /
  Dodge detonation eligibility (no input exists); per-target mark
  attribution (single-target fights).
- SOURCES (RLM-2 A, hash-verified): wiki cache W effects[0..2] (the 4s
  prose + the detonation prose + the refund prose verbatim) + cost
  [50x5] + cd [8x5]; the binary ManaReturn [60.0 x7] + DetonationTimeout
  [4.0 x7] + BaseDamage/APRatio/mStat-2 cross-checks + mana [50x6];
  the atom catalog: all 5 W atoms recomputed (fc2ec4c0d15236fc,
  3bf51f22202c5058, 2779b25f0ed1e9de, b32849b968950b8e, b794a6fc0b95a03b)
  and the REFUND-ATOM ABSENCE confirmed (effects[2] has no leveling row
  — the flat is a typed rule declaration, atoms () honestly); revision
  receipt 4041697 (2026-07-10T18:11:03Z) == the module SOURCES == the
  full-entry audit.  Gaps disclosed: the "+ mana cost" clause is
  script-side (wiki-only); the detonation triggers wiki-sourced only;
  the 4s window + shields were the recorded HANDOVER deferrals (§4.23,
  §4.40) now closed for the window.
- PUBLIC SURFACE: mark_refunds {declaration {flat, window_seconds,
  source, atoms, detonation}, marks (per-W-cast rows: time, source,
  flat, window_seconds, atoms, accepted, reason armed|applied|
  mark_expired|mark_undetonated|basic_attack_detonation, mark_slot,
  mark_ordinal, detonating_slot/ordinal/cost, refund_amount/time)};
  gain receipts carry the full shape + detail; score_only is
  byte-identical on the refund surface (the pure-W chain's parity is
  the empty-stream equality); the refund never enters total_damage.
- FILES: EDITED src/calculator/champions/ezreal.py (the window constant
  + the decl field + the ASSUMPTIONS), src/calculator/damage.py (the
  decl validation + the guard + the expiry consumption + the fight-end
  expiry pass + the arming/declaration window fields),
  tests/test_ezreal_w_mark_refund.py (C-owned, 25 tests: 23 PASS + 2
  xfail — the R1 re-pins: the W-chain/expiry/ability-detonation counts,
  the score-parity split, the public shapes + the new R2 + fight-end
  expiry tests), tests/test_mana_restore_refund.py (the M4 helper is
  now window-aware; M5 re-pinned to the expiry chain), tests/
  test_resource_ledger_champion_consumers.py (the W-chain re-pin),
  HANDOVER.md.
- GATES: sanity 974 passed + 3 xfailed + the 2 known pre-existing app
  rate-limiter flakes (pass isolated); full pytest TWICE stable: 6886
  passed + 19 xfailed both runs (6863 + 23 new; the 2 new xfails are
  the spell-shield + multi-target deferrals); black clean; FULL-SRC
  pylint 9.55/10 UNCHANGED (zero new findings); atomize twice
  content-identical (manifest only); golden compare: 928 rows = 927
  accumulated + 1 Ashe active_duration — ZERO new rows from this slice
  (the Ezreal mark_refund parse row pre-existed; its content now
  includes window_seconds — the slice's own declaration field,
  explained; no registered-fight damage deltas), baseline NOT
  recaptured; Catalyst + resource-ledger suites: 140 passed.

Follow-ups (recorded): the target-side spell-shield/Block/Dodge
detonation eligibility + the per-target mark attribution (the xfails);
the basic_attack option's receipted "basic_attack_detonation" rows even
with zero autos (documented option semantics — a gate would break the
pinned consumers); the Actualizer + refund interaction is now unpinned
by a dedicated test (the paid-cost reading is pinned in M4/M10
fixtures without the discount).


### 4.60 P4 Slice 14 (2026-08-09): Darius W Crippling Strike kill-triggered cooldown halving + mana refund

The W kill rule is modeled as an ASSERTION — the fight model's target
never dies, so no input can prove a kill (the named-receipt
alternative already existed as the ASSUMPTIONS line, now replaced).

- THE CONTRACT: the ``w_kill_assertion`` option (bool, default False,
  "Assume every accepted W empowered attack kills the target...") —
  the r_execute_recast precedent, WITHOUT rotation metadata (an
  execute-role edge on the damage row reorders the derived Darius
  rotation — verified; the option is centrally classified
  ``irrelevant`` so the rotation exhaustiveness contract passes).  With
  the option ON, the parsed W entry halves its sourced cooldown (5 ->
  2.5; haste applies to the halved base) and declares the typed
  ``kill_refund`` {flat 40.0, source "Darius W (Crippling Strike) kill
  refund", atoms ()}.  With the option OFF the entry is byte-identical
  (the rule is simply not modeled).
- THE REFUND: the mana walk (``_apply_mana_resource_limits``) mints one
  OP_GAIN of the flat at each ACCEPTED W cast's timestamp AFTER its
  spend (cast, hit, refund — the Ezreal mark-refund ordering; tier
  TIER_RESTORE, detail {slot W, ordinal}; can only enable later casts);
  denied casts never refund; the gains ride the resource_ledger_v1
  receipts (no new public section); the score path is byte-identical.
- THE COOLDOWN: parse-level halving (5 -> 2.5) — observationally
  identical to "every killing W halves its own post-cast cooldown"
  since every asserted cast kills; the schedule proof: [E,Q,W,R] 10s
  timed fight W at [1.4, 3.9, 7.15, 9.65] (4 casts) vs [1.4, 7.15]
  (2); one-rotation mode: cast count stays 1, the refund still fires
  at t=0.
- SOURCES (RLM-2 A): the cached effects[0..2] verbatim (the empower
  prose, the kill rule, the reset prose) + cost [40x5] + cd [5x5] +
  affectedByCdr; the binary W hit spell PercentCDRefund [50.0 x7] (the
  HALF is data — the kill CHECK is script-side) + ADRatio 1.4-1.6
  (total = base 1.0 + the wiki 40-60% bonus) + mana [40x6] +
  Trait_AttackReset (the reset is data-backed); the atom catalog: the
  4 W atoms recomputed (a94382ffe99ee8a9, dfb11fc26eebb59d,
  d968c3ec9a1d13d9, b920fb10837a441c) and the kill-rule atom ABSENCE
  confirmed (prose-only); the ONLY local exclusion is jungle plants
  (the cached notes — structures are in affects but never excluded by
  the notes; no exclusion is invented); the module SOURCES revision
  4022598 (the full-entry audit's W receipt is 2019 — recorded drift).
- FAIL-CLOSED: w_kill_assertion with no kill_refund declaration raises
  (the "silently wins" guard); malformed kill_refund (non-mapping,
  flat < 0 / non-finite / bool, empty source, bad atoms) raises naming
  the field; multiple declaring slots raise; the API already 400s
  unknown option keys + non-bool values; unknown entry keys raise at
  the engine gate (kill_refund admitted to _ALLOWED_ENTRY_KEYS).
- FILES: EDITED src/calculator/champions/darius.py (the two constants
  with receipts + the conditional contract + the option + the
  ASSUMPTIONS), src/calculator/champions/engine.py (the key gate),
  src/calculator/champions/__init__.py (the central irrelevant
  classification), src/calculator/damage.py (_kill_refund_decl +
  _kill_refund_decl_for_state + the walk's refund block — the legacy
  energy path's duplicate block was removed after the app test caught
  it), tests/test_darius_w_kill_refund.py (C-owned, 33 tests, all
  flipped + re-pinned: the S1 snapshot, the default-vs-asserted
  schedule pins at the [E,Q,W,R] times, the one-rotation boundary, the
  rotation-free option meta), HANDOVER.md.
- GATES: sanity 1045 passed + 3 xfailed + the 2 known pre-existing app
  rate-limiter flakes (pass isolated); full pytest TWICE stable: 6919
  passed + 19 xfailed both runs (6886 + 33 new); black clean; FULL-SRC
  pylint 9.55/10 UNCHANGED (zero new findings); atomize twice
  content-identical (manifest only); golden compare: 928 rows — ZERO
  new from this slice (the conditional declaration leaves the
  registered parse rows byte-identical; the 4 Darius rows are
  pre-existing accumulated deltas), baseline NOT recaptured; Catalyst +
  resource-ledger suites: 140 passed.

Follow-ups (recorded): the kill trigger + the mana-refund amount are
script-side (the 50% magnitude + the 40 cost are data-backed; the
trigger check is not in the repo); the jungle-plant exclusion is
trivially satisfied (champion target) and the structure/monster
question is unresolved by local evidence; the in-game swing lands one
auto interval after the cast and the 4s empower window is never
enforced (the coarse hit-at-cast timing, documented); the
full-entry-audit Darius W receipt is 2019 vs the module's 2026
revision (recorded drift).


### 4.61 P4 Vayne Q (2026-08-09): Tumble attack-reset throughput — opt-in reset acceleration (zero engine changes)

The reset's THROUGHPUT is modeled as an opt-in assertion.  Default and
registered fights stay byte-identical.

- THE CONTRACT: the ``q_tumble_reset`` option (bool, default False,
  "Model Tumble's attack-reset throughput: each accepted Q cast buys
  one extra basic attack") — no rotation metadata (centrally classified
  ``irrelevant``, slot Q — the w_kill_assertion precedent; a rotation
  edge would reorder the derived Vayne rotation).  With the option ON,
  ``_tumble`` stamps ``empowers_next_auto`` as the SELF-SUPPLYING
  BURST dict ``{"hits": 1, "attack_speed": float("inf")}`` instead of
  ``True`` — the Jayce Hyper-Charge payload, the narrowest existing
  contract, ZERO engine changes: the cast cap lifts (``_resolve_cast_plan``
  skips the cap for burst forms), the burst machinery re-times
  (``swings/inf = 0.0`` dead time) so ``num_auto_attacks = ordinary
  autos + Q_casts`` — each accepted cast buys one EXTRA swing — and the
  reattribution/forced-swing/on-hit/W counters ride the augmented
  stream.  The infinite rate is the exact encoding of "the auto fires
  immediately" (the wiki reset prose + the binary Trait_AttackReset
  tag; the acceleration magnitude is script-side, so no finite number
  is invented); arithmetic-safe at all four engine rate sites and never
  serialized to public JSON.  The option is read STRICTLY (``is True``)
  so junk values fail closed to the default.
- THE QUANTIFIED DELTA (reference config, 1.29 AS / 50 haste / 10s /
  uptime 1.0): off 12 autos / 12 Q casts (capped) / 4 W procs /
  5199.75 total; on 16 Q casts on the k*(2/3)s grid (the 16th at
  exactly 10.0) / 28 total swings (12 ordinary + 16 reset) / 9 W
  procs (28//3) / 9095.92 total.  The API surface (10s, Q CD 1.0): Q
  casts 8 -> 10, the auto row surfaces 8 ordinary autos, W 2 -> 6
  procs.  One-rotation with a stream: the single cast buys one extra
  swing; one-rotation/zero-uptime without a stream: byte-identical
  on/off (the forced-swing rule, which never procs Silver Bolts,
  unchanged).
- SOURCES (RLM-2 A, hash-verified): the cached Q effects verbatim
  (the 3s-window empower prose + "Tumble resets Vayne's basic attack
  timer.") + the 75-115% AD + 50% AP row + cost [30x5] + cd
  [6,5,4,3,2] + the notes; the binary: TotalADRatio 0.75-1.15 +
  APRatio 0.5 + Duration [3.0] + cooldownTime [6..2] + mana [30x6] +
  mSpellTags Trait_AttackReset (exactly once) + mCantCancelWhileWindingUp
  (the reset is data-backed ONLY by the tag; the acceleration
  magnitude + the dash duration are script-side); the 4 Q atoms
  recomputed (431e1de1196a0035, b0b88edb9077bd18, 568a84f9430078e3,
  c9023255a08ea0bc) + the reset-atom absence confirmed; the module
  SOURCES revision 3979075 == the parent receipt.
- FAIL-CLOSED: the option is unknown to the API until declared (400),
  non-bool values rejected ("must be true or false"), junk reads
  default via the strict ``is True`` check; the entry keys stay
  engine-known (hits/attack_speed); no new validation surface.
- FILES: EDITED src/calculator/champions/vayne.py (the payload switch
  + the option + the ASSUMPTIONS/docstring), src/calculator/champions/
  __init__.py (the central irrelevant classification),
  tests/test_vayne_q_reset.py (C-owned, 30 tests — 10 xfails flipped;
  re-pins reconciled to the engine's display conventions: the
  cast_timeline 3-decimal rounding and the W row's per-swing smearing
  (28 x 200/3 = 1866.67 with 9 completed procs), the API surface's
  cap-lift observables), tests/test_champion_options.py (the Vayne
  options-meta pin), HANDOVER.md.
- GATES: sanity 1128 passed + 3 xfailed + the 2 known pre-existing app
  rate-limiter flakes (pass isolated); full pytest TWICE stable: 6949
  passed + 19 xfailed both runs (6919 + 30 new); black clean; FULL-SRC
  pylint 9.55/10 UNCHANGED (zero new findings); atomize twice
  content-identical (manifest only); golden compare: 928 rows — ZERO
  new from this slice (the option defaults off, so the registered
  parse rows stay byte-identical; the 2 Vayne rows are pre-existing
  accumulated deltas), baseline NOT recaptured; Catalyst +
  resource-ledger suites: 140 passed.

Follow-ups (recorded): the acceleration magnitude + the dash duration
are script-side (VayneTumble.lua not shipped) — the infinite-rate
encoding is the evidence-consistent choice and no finite number is
invented; the 4s (3s) empower window is never enforced (the model's
hit time is the cast time); the phantom binary rank-0/rank-6 entries
unused; the wiki per-slot Q template receipt is 2019 (parent page
2025-12-25, revision 3979075 — recorded drift).


### 4.62 P4 Dr. Mundo E (2026-08-09): Blunt Force Trauma attack-reset throughput — opt-in reset acceleration (the Vayne-Q template, zero engine changes)

The reset's THROUGHPUT is modeled as an opt-in assertion.  Default and
registered fights stay byte-identical.

- THE CONTRACT: the ``e_reset_throughput`` option (bool, default False,
  "Model Blunt Force Trauma's attack-reset throughput: each accepted E
  cast buys one extra basic attack") — no rotation metadata (centrally
  classified ``irrelevant``, slot E — the q_tumble_reset precedent).
  With the option ON, ``_blunt_force_trauma`` stamps
  ``empowers_next_auto`` as the SELF-SUPPLYING BURST dict
  ``{"hits": 1, "attack_speed": float("inf")}`` instead of ``True`` —
  the Vayne-Q/Jayce payload, ZERO engine changes: the cast cap lifts
  (when it binds), the burst machinery re-times (swings/inf = 0.0 dead
  time) so ``num_auto_attacks = ordinary autos + E_casts``, and the
  reattribution/forced-swing/on-hit counters ride the augmented stream.
  The infinite rate is the exact encoding of "the auto fires
  immediately" (the cached reset prose "Blunt Force Trauma resets Dr.
  Mundo's basic attack timer." + the binary DrMundoE Trait_AttackReset
  tag; the acceleration magnitude is script-side, so no finite number
  is invented); arithmetic-safe and never serialized.  The option is
  read STRICTLY (``is True``); junk fails closed to the default.
- E-SPECIFIC CHECKS (all pass, no deviation): the entry is ONE row
  with BOTH the passive AD steroid (stat_buff 151.0504 = 3.2% of the
  R-raised max health) AND the empower — the payload switch replaces
  ONLY the empower value; the stat_buff survives untouched (verified
  live; the engine applies it in its own loop).  The amp is per-PARSE
  (read once at fight start; the re-swing uses the same entry).  NO
  timing.active_duration atom exists for E (the atomizer's prose scan
  is effects[0]-only, and E's effects[0] is the PASSIVE) — pinned as
  an explicit absence; the window's contract is the prose itself.
  Manaless: E's 10-70 HEALTH cost is unmodeled (no MANA/ENERGY
  resource → the ledger walk early-returns; resource_ledger {} /
  spent 0.0).
- THE QUANTIFIED DELTA (reference config, L18 E5/Q5/W5/R3, +2000 bonus
  health, AS 1.0, 10s, uptime 1.0): OFF total 2601.209142857143 (autos
  8 x 127.5252, E 424.9075428571429, Q 926.1, W 230.0); ON
  2856.259542857143 (autos 10 — delta +255.0504 = 2 bought swings; E
  casts stay 2 on the 6s cooldown grid — the cap never binds at the
  reference window; the cap LIFT is proven on the AS 0.3 / haste 100
  fixture: E 3 -> 5 casts).  One-rotation with a stream: +1 swing;
  one-rotation/zero-uptime without: byte-identical (the forced-swing
  rule, unchanged).  API surface (0.8 uptime): autos 6 -> 8.
- SOURCES (RLM-2 A, hash-verified): the four cached E effects verbatim
  (the passive prose, the empower prose with the 4s window + the
  0-40% amp, the 140% minion/monster line, the reset prose) + the min
  bonus 5/15/25/35/45 + 5% bonus health + the max row (the same
  damage at amp 1.4) + cd [9,8.25,7.5,6.75,6] + the HEALTH cost
  [10..70]; the binary: DrMundoE mSpellTags [Trait_AttackReset,
  PositiveEffect_EmpowerAttack, ...] + AttackOverrideDuration [4.0] +
  FlatHealthCost [-5,10..70,85] + BaseDamage [-5,5..45,55] +
  BonusHealthRatio 0.05 + MaxMissingHealthThreshold 0.7 +
  MaxDamageAmp 1.4 + MinionMod/MonsterMod 1.4 + HealthToADRatio
  (2..3.2); the 14 E atoms recomputed (51d0a2ca5a739a6f,
  aeba0d1d15c0cb94, af89da91c67dfe21, 9869fb3d76a36103 + the
  min/max/minion/monster family) + the reset-atom AND the
  active-duration-atom absences confirmed; the module SOURCES revision
  4007950 == the parent receipt (NO drift — the first slice without
  the 2019-vs-2026 gap).
- FAIL-CLOSED: the API rejects unknown keys (400) and non-bool values
  ("must be true or false") once declared; the strict is-True module
  read; the option-on never silently no-ops (the opted-in pins fail
  otherwise); zero-autos/one-rotation-no-stream byte-identical; Q's
  current-health repricing + W's 12-tick charge + R's base-health
  grant are untouched (verified event-by-event).
- FILES: EDITED src/calculator/champions/dr_mundo.py (the payload
  switch + the option + the ASSUMPTIONS/docstring), src/calculator/
  champions/__init__.py (the central irrelevant classification),
  tests/test_mundo_e_reset.py (C-owned, 31 tests — 8 xfails flipped +
  the S1 options snapshot re-pin), tests/test_dr_mundo.py (the
  options-set pin), tests/test_dr_mundo_passive.py (the no-p-option
  options pin), HANDOVER.md.
- GATES: sanity 1224 passed + 3 xfailed + the 2 known pre-existing app
  rate-limiter flakes (pass isolated); full pytest TWICE stable: 6980
  passed + 19 xfailed both runs (6949 + 31 new); black clean; FULL-SRC
  pylint 9.55/10 UNCHANGED (zero new findings); atomize twice
  content-identical (manifest only); golden compare: 928 rows — ZERO
  new from this slice (the option defaults off; the 1 DrMundo row is a
  pre-existing accumulated delta), baseline NOT recaptured; Catalyst +
  resource-ledger suites: 140 passed.

Follow-ups (recorded): the acceleration magnitude + the windup timing
(binary mCastTime 1.0/castFrame 1.225 vs the wiki castTime "none") are
script-side — the infinite-rate encoding is evidence-consistent and no
finite number is invented; E's 4s window has no atom (prose-only, the
atomizer's effects[0]-only prose scan) — a candidate for the
_FOCUS_WINDOW_EFFECTS-style explicit map if the E window ever needs an
atom; the HEALTH cost is unmodeled (manaless champion; the ledger
never runs); the binary client patch (26.15-era) postdates the wiki
patchLastChanged (26.08) — all values agree, re-verify next patch day.


### 4.63 P4 Jayce form transitions (2026-08-09): the FORM TRANSITION RECEIPT — no new option, no engine change

The mid-fight stance change is certified as NOT representable in the
current engine, and the smallest evidence-backed contract is the
transition RECEIPT (a named boundary), not a new input.

- THE VERDICT (RLM-2 B, engine-feasibility proof): the fight engine
  consumes ONE parsed entry set per slot, precomputed across seven
  phases (the cast schedule, the cast plan, the fight-wide stat_buff
  loop, the empowered-burst auto re-time, the rotation pricing, the
  per-auto restore declaration, the damage-event ledger) — a mid-fight
  stance swap changes NOTHING in the already-built schedule; R is
  pinned single-cast at t=0; stat_buffs are fight-wide; cooldowns are
  one-per-slot (Hammer Q 6s vs Cannon Q 8s cannot be expressed); a
  two-entry-set fight would raise the two-declaration guard and
  duplicate breakdown rows.  The only per-cast parts seam (Rengar's
  ferocity) is parts-only and stack-keyed.  Building the split would be
  engine surgery across schedule/plan/stat-buff/auto-retime/pricing —
  the opposite of the smallest contract.
- THE CONTRACT: NO transform option is declared (any transform_*,
  transform_time, stance_sequence spelling is REJECTED by name at the
  API boundary — the existing unknown-option 400 is the fail-closed
  gate, pinned); ``hammer_stance`` remains the whole-fight stance
  selector; ASSUMPTIONS[0] now carries the FORM TRANSITION RECEIPT:
  "the R cast IS the Transform and the engine schedules it exactly
  once at t=0 (R first in CAST_ORDER, the engine's single-cast rule);
  the fight plays entirely in the destination stance that
  hammer_stance selects; a fight that opens in one stance and flips at
  a provable later time is NOT representable — model a cross-stance
  sequence as TWO one-stance fights (one per stance) to bound the
  transition; the in-game transform is instant, costs nothing, and its
  6s cooldown is sourced but never recast (R casts once); the P
  passive (30 MS + ghosting for 0.75s on every swap) is utility-only
  and not modeled."
- THE BOUNDING PAIR (the receipt's two-fight model, reference build
  L18 Q/W/E r6, 250 AD/150 bonus, 1.0 AS, 10s): Cannon 4994.0 (Q
  1344, W 1650, R 0, autos 2000) vs Hammer 5280.0 (Q 1025, W 880, R
  425, autos 2250); the cross-combo (672+512.5 Q / 825+440 W in ONE
  fight) is the documented gap, never invented.  The W per-auto
  restore rides both stances (the cannon pipeline fight: 13 rows — 7
  ordinary + 6 Hyper Charge swing rows, auto_index 1..13; the hammer:
  9 ordinary rows).
- SOURCES (RLM-2 A, hash-verified): the cached R entries verbatim
  (both names, empty leveling, cd [6x6] affectedByCdr, cost null,
  castTime "none") + the P entries (30 MS + ghosting for 0.75s);
  the binary: cooldownTime [6.0x7] on BOTH stance-swap spells (NO
  Trait_NoCooldown — the transform is NOT free; 6s is sourced), no
  cast-time magnitude (castFrame 3.0 animator-driven), the HtG record
  owns ALL magnitudes (Resists 5/12/19/26 + 7.5% bAD, Damage
  25/60/95/130 + 30% bAD, RangedFormShred 20/25/30/35% + 5s,
  FlatMovementSpeed 30.0 + 0.75s), the vestigial mEffectAmount arrays
  on the melee-auto record (flagged dead data); the atoms: R cooldown
  09ec6b9b472be16f + R 5s shred window 0cc9de17ee0266ed + P 0.75s
  b5b6ed0704daa315 + W mana bfeb0d88945a263e recomputed (26/26),
  Hammer R[1] has ZERO atoms and the shred/resists/MS are prose-only;
  revision 4008136 == the module SOURCES.
- FAIL-CLOSED: transform_* spellings 400 at the API boundary (the
  named gate; the direct engine ignores unknown champion_options by
  design — validation lives at the scenario boundary, pinned);
  hammer_stance is bool-typed; one-rotation/zero-auto modes are
  transition-free (the forced-swing rule + the one-stance totals
  unchanged); the R cast is single at t=0.
- FILES: EDITED src/calculator/champions/jayce.py (the ASSUMPTIONS
  receipt only — NO code-path change), tests/test_jayce_form_transition.py
  (C-owned, 48 tests — the 10 MODEL-B1 xfails reconciled to the
  receipt contract: no-option-declared, the one-stance bounding pair,
  the per-stance forced swings, the API rejection pins, the both-stance
  restore rows), HANDOVER.md.
- GATES: sanity 1236 passed + 3 xfailed + the 2 known pre-existing app
  rate-limiter flakes (pass isolated); full pytest TWICE stable: 7028
  passed + 19 xfailed both runs (6980 + 48 new); black clean; FULL-SRC
  pylint 9.55/10 UNCHANGED (zero new findings); atomize twice
  content-identical (manifest only); golden compare: 928 rows — ZERO
  new from this slice (the ASSUMPTIONS text is not in the golden; the
  3 Jayce rows are pre-existing §4.58-era deltas), baseline NOT
  recaptured; Catalyst + resource-ledger suites: 140 passed.

Follow-ups (recorded): a mid-fight transition would require engine
surgery (per-cast entry dispatch across the seven consumption phases +
a two-entry-set fight contract) — the receipt's two-one-stance-fight
guidance is the supported path; the transform's cast-time magnitude is
script-side (castFrame 3.0, wiki "none"); the P passive stays
unmodeled; the Hammer-R cooldown atom is absent by design (dedup with
R[0]'s 6s).


### 4.64 P4 Senna Relic Cannon (2026-08-09): the 20%-AD on-hit rider — a second BUFF-phase slot (P2), ZERO engine changes

The Relic Cannon rider is modeled as INHERENT + source-backed (no
option) via a second Senna-only slot riding the existing on-hit seam.

- THE CONTRACT: ``SLOTS["P2"] = _relic_cannon`` (BUFF phase, after P so
  the rider reads the Mist-buffed parse-time AD) emits its OWN ``on_hit``
  payload — the engine's ability-on-hit loop prices ANY entry's payload,
  including a slot key outside P/Q/W/E/R, so the one-per-auto-payload
  limit per entry is preserved (the P entry keeps exactly the Weakened
  Soul mark) and NO shared engine file changes.  ``stacks_required`` /
  ``count_ability_hits`` absent: the rider fires on every basic-attack
  on-hit (autos + phantom hits + double shots — never ability hits),
  its own breakdown row ``on_hit_ability_P2`` with exact per-swing
  events, physical, lifesteal-eligible (the on_hit_ row prefix), feeding
  the static per-hit feed (BoRK/Kraken/spellblade-doubling composition).
- THE VALUE: 20% of TOTAL AD — the wiki prose "20% AD" (P effects[3],
  leveling empty, no atom) + the binary SennaPassive
  mSpellCalculations.BonusOnHitDamage = StatByCoefficient(mStat 2, NO
  mStatFormula = total AD per the repo-pinned convention; Senna Q's
  mStatFormula 2 is the bonus-AD shape) coefficient 0.2.  The parent's
  "bonus AD" framing was NOT source-backed and was corrected to total AD
  (the module constant _RELIC_CANNON_AD_RATIO = 0.2 + the
  _RelicCannonRule receipt with the wiki revision + the binary path).
- THE BOUNDARIES (named): the engine has no structure or
  invulnerability concept — the wiki's exclusions ("not applied against
  structures; only if the attack deals more than 0 damage") are named
  assumptions (the engine's raw_base <= 0 skip mirrors the AD<=0 edge);
  the MS-steal (10/15/20% for 0.5s — binary MSStealDuration 0.5 + the
  level-6/9 breakpoints) is utility and not modeled.
- THE GOLDEN DELTAS (inherent + source-backed, baseline NOT recaptured —
  the compare now shows 947 = 928 + 19 new, EVERY one enumerated):
  (a) the parse snapshot gains the P2 entry key; (b) the 8 registered
  SUSTAINED Senna fights gain on_hit_ability_P2 (32.0/32.0/125.33/101.87
  at L11, 42.67/42.67/125.33/127.33 at L18) + the total_damage shifts
  (+32.0/+32.0/+126.37/+101.87 at L11, +42.67/+42.67/+126.58/+127.33 at
  L18); (c) the physical builds' Kraken missing-HP row shifts by the
  HP-walk composition (100.07 -> 101.11, 121.3 -> 122.56) — the rider
  decays the target earlier, physically correct; (d) the burst fights
  are byte-identical (no autos, no rider row).  All match B's live
  A/B deltas.
- FAIL-CLOSED: no option is declared (the option surface stays exactly
  [senna_mist_stacks]; every relic spelling 400s "unknown option" at
  the API boundary); the P2 payload is module-authored code (no user
  input); zero-auto/one-rotation-no-stream: the row absent, totals
  unchanged; the mark cadence + the item on-hits + the Q item
  applications are untouched (the rider adds no applications to the
  shared counters — verified).
- FILES: EDITED src/calculator/champions/senna.py (the constants + the
  _RelicCannonRule receipt + _relic_cannon + SLOTS["P2"] + the
  ASSUMPTIONS replacement — NO other source file), tests/test_senna_relic_cannon.py
  (C-owned, 36 tests — the 12 MODEL-xfails reconciled to the inherent
  contract: the P2 payload/row placement, the total-AD formula, the
  zero-Mist-vs-40-Mist per-hit proof, the registered golden deltas, the
  API rejection pins, the Kraken-application separation, the souls-ledger
  coexistence), tests/test_senna_souls_ledger.py (the not-modeled
  assumption pin -> the modeled receipt), tests/test_cp10_batch_07.py
  (the SLOTS-count pin 5 -> 6 for Senna), HANDOVER.md.
- GATES: sanity 1195 passed + 3 xfailed + the 2 known pre-existing app
  rate-limiter flakes (pass isolated); full pytest TWICE stable: 7064
  passed + 19 xfailed both runs (7028 + 36 new); black clean; FULL-SRC
  pylint 9.55/10 UNCHANGED (zero new findings); atomize twice
  content-identical (manifest only); golden compare: 947 = 928 prior +
  19 NEW rows — every Senna delta enumerated and explained above
  (inherent + source-backed), baseline NOT recaptured; Catalyst +
  resource-ledger suites: 140 passed.

Follow-ups (recorded): the every-auto trigger is script-side (wiki
prose + the absence of any binary limiter — the definitive citation
needs the game script); the P template receipt (rev 2864157, 2019)
predates the cached Relic prose (no fresh revision receipt — the
binary corroboration is the modern source); whether Q also fires the
rider is not stated in the local cache (out of scope); the pre-existing
on_hit payload-key validation gap (a typo'd damage_per_hit silently
vanishes — a future _ALLOWED_ON_HIT_KEYS hardening is recorded);
Senna's parse gains the P2 slot (the cp10 SLOTS-count pin updated).


### 4.65 P4/P1 Aurelion Sol Q Stardust scaling (2026-08-09): certification + the typed milestone/atom-certification surface

The Q Stardust scaling is CERTIFIED end-to-end (the §4.47 rule already
prices every term), and the two remaining completion-rule violations
are closed: the ledger milestone literals and the missing
atom-certification surface.

- THE CONTRACT: (1) ``_StardustRule`` gains ``execute_breakpoint_stacks =
  100`` + ``max_stacks = 999`` + the ``atom_ids`` certification map
  (per_stack_burst_maxhp_pct -> the HALF-PARSED atom
  ability.bonus _magic _damage.modifier_2 d7b0a266cad8da3f — the
  degraded row whose values are zeroed and whose 3.1% lives in the
  units string; execute_base_pct/execute_pct_per_100/stardust_per_q_burst
  -> the binary roots BaseExecutionThreshold 5.0 /
  ExecutionGrowthPerBreakpoint 0.026 / QMassStolen 2.0) +
  ``certified_constants``; all published in ``public_receipt()`` (the
  option's state + the ledger declaration).  (2) the ledger's per-100
  milestone math (damage.py) now reads the RULE's values
  (q_burst_maxhp_pct_per_100 / e_execute_base_pct /
  e_execute_pct_per_100 / execute_breakpoint_stacks) instead of the
  hardcoded 3.1/5.0/2.6/100 literals — behavior-identical today,
  fail-closed against silent patch-day divergence.  NO engine edit,
  NO new option (the primary/secondary split is already priced from
  the sourced half-strength rows + the binary AOEModifier 0.5; the
  bursts stay primary-only).
- THE CERTIFIED NUMBERS (dual-root wiki + binary): +2 Stardust per Q
  burst vs a champion (QMassStolen 2.0; the {a110bc47} 4.0 override
  noted); burst = 60-100 + 30% AP + 3.1% max HP per 100 stacks (the
  binary QMaxHealthTrueDamagePerStack 0.00031 — linear 0.031%/stack,
  1.86/stack per 3-burst channel @2000 HP); charge 3.25s (3 bursts per
  full second — BurstAfter 1.0; 26 ticks at 8/s); beam 45-105/s + 55%
  AP; secondary exactly 50% (AOEModifier 0.5); monster cap 300 (named
  out-of-scope — no monster target kind); cd 3s; E execute display
  5% + 2.6%/100 (the binary BaseExecutionThreshold 5.0 +
  ExecutionGrowthPerBreakpoint 0.026); first-enemy beam
  (Trait_Ranged_StopsFirstHit); 0.25s cancel threshold
  (mSpellCooldownOrSealedQueueThreshold); revision 3952788 == the
  module SOURCES; all 5093 atoms re-verified.
- DOCUMENTED UNSUPPORTED BOUNDARIES (strict xfails, retained): the
  rank-5 "160 seconds" channel (wiki prose vs the binary's rank-5
  MaxChannelDuration 3.25 — the 9999 lives in the W-flight slots; the
  per-cast window stays 3.25s) and the 0.25s-cancel 1s lockout (the
  0.25 threshold is binary, the 1s lockout script-side — no cancel
  concept in the model).
- FILES: EDITED src/calculator/champions/aurelion_sol.py (the rule
  fields + the receipt), src/calculator/damage.py (the milestone
  literals -> the typed rule), tests/test_aurelion_sol_stardust.py
  (C-owned, 44 tests: 42 PASS + 2 xfail — the S9 atom-certification
  xfail flipped to a live pin), HANDOVER.md.
- GATES: sanity 611 passed + 5 xfailed + the 2 known pre-existing app
  rate-limiter flakes (pass isolated); full pytest TWICE stable: 7106
  passed + 21 xfailed both runs (7064 + 42 new; the 2 new xfails are
  the documented boundaries); black clean; FULL-SRC pylint 9.55/10
  UNCHANGED (zero new findings); atomize twice content-identical
  (manifest only); golden compare: 947 rows — ZERO new from this slice
  (the milestone typing is behavior-identical; the 4 Aurelion rows are
  pre-existing classifier tags), baseline NOT recaptured; Catalyst +
  resource-ledger suites: 140 passed.

Follow-ups (recorded, patch-day): the Q beam/burst attribute reads
("Magic Damage per Second", "Bonus Magic Damage") lack the W-modifier-
style missing-key guard (extract_value's silent 0.0 — a rename would
zero the beam; log for the patch workflow); the wiki/binary Q cost
drift (cache 8.75-13.75/tick vs binary ManaCostPerSecond 30-60 —
flagged stale in staleness.json); the R transform 75 vs 50 (R2 record)
+ the E cooldown 12 vs the toggle 10/9.5/9/8.5/8 + the Q burst
"TrueDamage" naming-vs-type flag (§4.47 follow-ups, reproduced);
QMassStolen's {a110bc47} 4.0 override noted; the atom_ids hashes are
pinned so patch changes trip the tests (fail-closed staleness).


### 4.66 P4 Quinn P (Harrier) crit-chance (2026-08-09): certification + the named fail-closed CRIT boundary

The Harrier on-hit is CERTIFIED end-to-end; the crit term is NOT
source-backed and is declared as a named fail-closed boundary (the
client's directive: "If the numeric crit term is not source-backed,
certify a named fail-closed boundary").

- THE CERTIFIED ON-HIT: Harrier = "Bonus Physical Damage" 15..132.35
  (20 per-level entries — 15@1, 120@18, 132.35@20; the binary's
  ByCharLevelInterpolation 15->120 extended linearly to the level-20
  cap) + 40% bonus AD (the binary ADRatio 0.4 — float32-verified),
  physical, ONHIT phase, per marked-target auto (count == autos; the
  mark requires Q/E/R or Valor's periodic marking first).  All values
  typed from the pinned cache row via extract_named/sum_modifiers —
  zero literals; the atoms recomputed (3738717a70d96778, f5d253ac12f722b2,
  7aef3aea28570130, b1da09c15c0adb6b); PACKET_SHA256 pin live; the
  module SOURCES parent rev 4009372 (the P template receipt is 2019 —
  recorded currency gap).
- THE CRIT BOUNDARY (named fail-closed): NO pinned source states the
  Harrier bonus crits — the pinned cache (rev 4009372) and the live
  wiki carry no crit sentence for the bonus (the wiki's general rule:
  on-hit damage does not crit unless stated); the historical "can
  critically strike" note was REMOVED 2020-08-30 (rev 3109549); the
  binary has no crit coefficient for the passive (only the global
  critDamageMultiplier 2.0 + the ordinary QuinnCritAttack animation
  spell).  The row is priced NON-crit (the on-hit path's only
  capability) and pinned by the typed ``_HARRIER_CRIT_BOUNDARY =
  "non_crit"`` constant + the ASSUMPTIONS receipt.  The engine's on_hit
  ``crit_effectiveness`` wiring (the _ALLOWED_ON_HIT_KEYS validation +
  the _layer_on_hit_effects blend, mirroring the ability-part crit
  math) is the PRE-SPECIFIED flip-switch for a future sourced
  statement — explicitly NOT wired now (an unsourced change to shared
  machinery for ~15 champions would be the silent-overstatement class
  the rules forbid).  Verified: at 0/50/100% crit the Harrier row's
  per-hit is INVARIANT while the auto row scales (113 -> 742.9); the
  row carries no crit keys.
- THE DEGRADED ROW (pinned): the P cooldown row values [0,0,0] with
  units "7 : 2.56 (based on critical strike chance)" — the mark-
  INTERVAL scaling (7s at 0% crit -> 2.56s at 100%), a mark-cooldown
  mechanic, NOT a damage term; the atom timing.cooldown b1da09c15c0adb6b
  normalizes the units to "s" (the prose dropped — unrecoverable); the
  binary has no passive cooldown DataValue (script-side).  The degraded
  shape is pinned so a future fixed row forces re-review (fail-closed
  staleness).
- NAMED BOUNDARIES (also pinned): the monster term (75 vs monsters —
  the cached effects[2] + the binary BonusMonsterDmg 75.0) is not
  priced (no monster-target kind); Behind Enemy Lines (R-active)
  disables Harrier + removes marks (cached effects[3]) — the on-hit
  stays unconditional; the 1s re-mark cooldown + the mark priority
  notes are unmodeled; the mark 4s duration is sourced (RevealDuration
  4.0 + the active_duration atom) but not priced as a cooldown.
- FILES: EDITED src/calculator/champions/quinn.py (the CRIT BOUNDARY
  constant + the docstring + the four ASSUMPTIONS rows — NO pricing
  change), tests/test_quinn_p_crit.py (C-owned, 40 tests — the 3
  xfails reconciled to the live boundary pins: the monster + BEL named
  boundaries + the crit-term receipt), HANDOVER.md.
- GATES: sanity 579 passed + 5 xfailed + the 2 known pre-existing app
  rate-limiter flakes (pass isolated); full pytest TWICE stable: 7146
  passed + 21 xfailed both runs (7106 + 40 new); black clean; FULL-SRC
  pylint 9.55/10 UNCHANGED (zero new findings); atomize twice
  content-identical (manifest only); golden compare: 947 rows — ZERO
  new from this slice (the boundary contract changes no pricing; the 2
  Quinn rows are pre-existing classifier tags), baseline NOT
  recaptured; Catalyst + resource-ledger suites: 140 passed.

Follow-ups (recorded): the engine's on_hit payload-key validation gap
(fail-open seam — _ALLOWED_ON_HIT_KEYS hardening is the pre-requisite
for any future on_hit extension); the level-18/20 endpoint note (the
binary interpolates 15->120 while the cache extends to 132.35@20 — the
cache is the source of truth, staleness "unchecked"); the docs/
receipts/champions/quinn.json empty atoms/module_coverage + the
packet/audit assets' P no_damage staleness vs the E5-2 module override
(recorded); the 2020-removed crit note + the live wiki's absence mean
the crit wiring stays OFF until a pinned source states it.


### 4.67 P4 Yasuo & Yone Q3 critical conversion (2026-08-09): Yasuo certified + Yone's missing conversion fixed

- THE CONTRACT: Yasuo's crit machinery is CERTIFIED (its Q crit values
  reproduce the degraded "Critical Strike Damage" rows bit-exactly:
  189% + 28.35% AD = 1.05 x 1.8 + 1.05 x 0.27; the row is the display of
  the modeled converted system, NOT a distinct mechanic — never priced).
  Yone's IDENTICAL conversion was entirely MISSING (a real bug: its Q
  never crits, its autos crit at the raw chance x 2.0 without the 0.9
  reduction or the excess-AD) and is now MIRRORED from Yasuo:
  1. yone.py _way_of_the_hunter emits the SAME crit_modifier payload
     (2.0 chance multiplier / 0.9 damage factor / 0.5 AD per excess % —
     the cached Yone P prose is verbatim Yasuo's; the 0.9 stat atom
     1142fbe0a600fcc8; the binary YoneCritToAD 50.0 + CritDamageMod 0.9),
  2. _mortal_steel splits the Q into flat + AD-ratio parts with
     crit_effectiveness=1.0 on the 110% AD portion (the binary
     TotalDamageCrit structure),
  3. the Q3 branch adds the 0.75s knock-up CC state to the flat part
     (the binary Q3KnockupDuration 0.75 — Yasuo parity; previously
     detail-only).
  The rule's constants + certification moved to a SHARED module_helpers
  rule (crit_conversion_payload / crit_conversion_certification) with
  per-module aliases + atom_ids (yasuo f375a24fbf0555e1 / yone
  1142fbe0a600fcc8) — no duplication, fail-closed pinned hashes.  The
  engine gained "atom_ids"/"certified_constants" entry keys (documentary
  surfaces on state rows).
- QUANTIFIED (B's A/B + C's matrix): Yasuo at 0/25/50/100% item crit
  (-> 0/50/100/200% converted): Q/cast 227.10/269.94/312.78/312.78 (the
  >100% excess caps the chance + grants AD to autos only); the Yone
  fix: Q/cast at 50% raw + IE 313.10 -> 514.37 (125 + 171 x 1.1 x 2.07),
  autos 262.5 -> 353.97 (AD x 2.07 at converted 100%).
- THE DEGRADED ROWS (pinned, never priced): Yasuo "Critical Strike
  Damage" values [0x5] units "(189% + 28.35%) AD"; Yone's split
  "(198%" + "%) AD" + [29.7x5]; the atoms ad38810cc04c7723 /
  6f43777074cc9c33 + 83e6154bf72561e7 carry the degraded state; the
  Q3 crit is NOT distinct from Q crit (one shared row/chance/multiplier
  — the knock-up is the only Q3 addition).
- NAMED BOUNDARIES: the excess-crit AD reaches autos but not
  parse-time-priced ability parts (repo-wide pattern — the Q keeps the
  parse-time AD; a future re-pricing hook is out of scope); the Q
  cooldown is flat 4.0s (the cached AS-reduction units, capped 67%,
  unmodeled — certified flat); the Q3 knock-up flows into the damage
  events via cc_kind/cc_duration but neither module emits the
  control_events ledger (paired-CC item support misses the Q3 knock-up
  — recorded).
- FILES: EDITED src/calculator/champions/yone.py (P payload + Q split +
  Q3 CC), src/calculator/champions/yasuo.py (the certification surface
  only — the crit behavior certified unchanged), src/calculator/
  champions/module_helpers.py (the shared rule), src/calculator/
  champions/engine.py (the two documentary entry keys),
  tests/test_yasuo_yone_q3_crit.py (C-owned, 54 cases — the 2 xfails
  flipped: the Yone conversion + the atom-certification surface; the
  Yone-behavior pins re-based to the fixed values), HANDOVER.md.
- GATES: sanity 899 passed + 12 xfailed + the 2 known pre-existing app
  rate-limiter flakes (pass isolated); full pytest TWICE stable: 7200
  passed + 21 xfailed both runs (7146 + 54 new); black clean; FULL-SRC
  pylint 9.55/10 UNCHANGED (zero new findings — the yone mirror's
  duplicate-code is a documented targeted disable; the shared rule
  extraction); atomize twice content-identical (manifest only); golden
  compare: 976 = 947 prior + 29 NEW rows — every delta explained: the
  Yone parse rows (Q parts[1] + the P crit_modifier/certified_constants/
  atom_ids), the Yasuo/Yone P certification surfaces, and the 12
  registered Yone fights' Q/auto/Kraken/total shifts with the crit-item
  builds (the behavior fix); the Yasuo W rows are another in-flight
  slice's accumulated deltas (noted), baseline NOT recaptured; Catalyst
  + resource-ledger suites: 140 passed.

Follow-ups (recorded): the Yone P prose is verbatim Yasuo's (possible
template copy) though both data layers agree on 0.9 — game-side check
recommended before any future pin; the x2 crit-chance multiplier is
script-side (the binary CritChanceMultiplier DataValue = 1.0); the
Gathering Storm stack cap 2 is script-side (the 6s duration is data);
Yasuo's Q3 knock-up is 0.9s wiki-prose (the binary only has a
TOOLTIPONLY 1.0 — Yone's 0.75s is real data); the disarm 0.1s reset is
prose-only; the Q3 knock-up's control_events ledger emission is
recorded for a future CC-support slice.


### 4.68 P4 Zeri P Living Battery execute range (2026-08-09): the degraded execute threshold implemented

The P slot was declared "modeled" but priced ZERO damage (a dead packet
with the misattributed full-charge ratio) — the execute range is now
implemented via the engine's existing ratio seam.

- THE CONTRACT: ``_living_battery`` (ONHIT, bound to SLOTS["P"]) prices
  the uncharged zap per auto (the cached "Per-Level Scaling" 10..27.35
  degraded row + the 3% AP prose term — the binary MinDamage 0.03) and
  stamps the EXECUTE: ``execute_threshold_ratio`` =
  (70..170.59 + 20% AP)/target_max_health + ``execute_source`` =
  "Living Battery" (the degraded "Bonus Damage" row + the survived 20%
  AP unit; the binary PassiveExecuteThreshold 70.0->160.0 + coefficient
  0.2 corroborates; the wiki L20 extension 170.59 is the repo
  convention).  The engine's stamp loop gained the one-line resolution
  for the on-hit passive source_key, and the single-fight target walk
  mirrors the survival terminal transition's execute gate (inclusive
  <=, AFTER the event's own damage — the zap counts toward the
  crossing) so /api/calculate agrees with the pair/timeline surface.
- THE CERTIFICATION SURFACE: the ``_LivingBatteryExecuteRule``
  (ZERI_P_EXECUTE_RULE — the Asol pattern): public_receipt with the
  threshold endpoints 70/170.59 + the AP ratios + the atom_ids
  (ability.bonus _damage.modifier_0 9fa7c9206eb1e3c8 +
  .modifier_1 404ba4027bf78118 — the pinned degraded-row atoms) + the
  wiki/binary sources (parent rev 4019486).
- NAMED BOUNDARIES: the full-charge attack (effects[2]), the charge
  mechanic (effects[0]), and the shielded/invulnerable exclusion (the
  engine's applied_to_health gate covers fully-absorbed hits; a shield
  on an enemy below the threshold is a named assumption); the equality
  is INCLUSIVE <= (the engine seam; the wiki's "below" is the
  script-side operator — documented); the L18 (160) vs L20 (170.59)
  endpoint follows the repo convention; the stale P template revision
  (3380499/2022) is pinned for patch-day.
- FILES: EDITED src/calculator/champions/zeri.py (_living_battery +
  the rule + the constants + SLOTS["P"]), src/calculator/damage.py
  (the one-line on-hit stamp resolution + the single-fight execute
  gate), tests/test_zeri_p_execute_range.py (C-owned, 44 tests — the 7
  xfails flipped; the fixtures re-based to the ratio semantics: the
  parse target max threaded through the helper, the on-hit row key, the
  detail capitalization), tests/test_yasuo_yone_q3_crit.py (the
  abilities-domain manifest pin re-based to the branch's regenerated
  sha cb0ef06033971bdc — pre-existing drift, verified), HANDOVER.md.
- GATES: sanity 819 passed + 5 xfailed + the 2 known pre-existing app
  rate-limiter flakes (pass isolated); full pytest TWICE stable: 7244
  passed + 21 xfailed both runs (7200 + 44 new); black clean; FULL-SRC
  pylint 9.55/10 UNCHANGED (zero new findings); atomize twice
  content-identical (manifest only); golden compare: 1007 = 976 prior
  + 31 NEW rows — every Zeri delta enumerated: the passive parse
  surface (on_hit/execute_source/execute_threshold_ratio/
  certified_constants/atom_ids/detail + the removed dead packet keys)
  and the 8 registered sustained fights' on_hit_ability_passive +
  total_damage shifts (+38.02..+140.8) with the Kraken/Shadowflame
  secondary HP-walk rows; burst fights byte-identical, baseline NOT
  recaptured; Catalyst + resource-ledger suites: 140 passed.

Follow-ups (recorded): the binary's stray "{72c5c2a8}": 2 flag on
PassiveExecuteThreshold (likely "is execute" — undocumented); the
max-charge 100 is wiki-only (not in the binary); the atom
per-_level _scaling evidence unions effects[1]+effects[2] while
holding only effects[1] values (never certify the full-charge base
against it); the shield-below-threshold exclusion + the full-charge +
the charge mechanic stay named boundaries.


### 4.69 P4 Gnar Mega form game-file verification (2026-08-09): all five constants CERTIFIED vs the game files

- THE VERDICT (RLM-2 A, read-only + the wad-toolchain extraction): ALL
  FIVE hardcoded Rage Gene constants PASS vs the local game-file
  authority (client 16.15.8024387): the GnarBig CharacterRecord root
  extracted from the local client WAD (Gnar.wad.client ->
  data/characters/gnarbig/gnarbig.bin, Characters/GnarBig/
  CharacterRecords/Root: HP 640/122, AD 66/5.5, armor 36/6.7, MR
  33/4.8, AS 0.625 + 0.5%/lvl) MINUS the Mini root (data/bin/
  characters/gnar.bin.json: 540/79, 60/3.2, 32/3.7, 30 + 1.3/lvl,
  0.625 + 6%/lvl):  MEGA_BONUS_HEALTH (100,43) PASS exact;
  MEGA_BONUS_AD (6,2.3) PASS exact (the wiki's 5.7 growth claim is
  stale — the game says 5.5 -> the 2.3 delta; the in-repo GnarPassive
  tooltip calc 6.0->48.5 uses the old 2.5/lvl and is NOT authority);
  MEGA_BONUS_ARMOR (4,3) PASS; MEGA_BONUS_MR (3,3.5) PASS (the Mini MR
  growth 1.3/lvl verified under the hashed root key); MEGA_ATTACK_SPEED_LOSS
  (0,5.5) PASS (6.0 vs 0.5 per-level bonus-AS magnitudes).
- THE GROWTH ENDPOINTS (standard formula, multiplier 17.0 at 18 /
  19.665 at 20): HP +100/+831/+945.595; AD +6/+45.1/+51.2295; ARMOR
  +4/+55/+62.995; MR +3/+62.5/+71.8275; AS-loss 0/-93.5/-108.1575
  percentage points (C's level-20 set corrected the parent's +943.5
  guess).  The base-vs-bonus AD rule confirmed (the grant lands in
  base_attack_damage only — R's %bonus-AD ratios see 0 without items,
  wall 600 flat; +80 bonus AD -> 660; the recorded bug-history failure
  was the misclassification).  The AS-loss = percentage points of
  BONUS AS through the ratio (net Mega level-AS growth 0.5%/lvl;
  engine AS 0.625/0.678125/0.686453125).  E (Crunch) prices its
  own-max-HP unit against the BUFFED health; R is Mega-only and
  level-flat.
- THE FAIL-CLOSED RECORD: the REPO-LEVEL parsed GnarBig root remains
  ABSENT (no data/bin/characters/gnarbig.bin.json + no
  Characters/GnarBig/CharacterRecords/Root inside gnar.bin.json;
  decompose_binaries.py extracts one path per WAD and gnarbig is not a
  WAD unit — the raw authority exists only inside the local client
  WAD).  The constants' receipts now carry the P4 game-file authority
  note (the extraction path + the stale-tooltip warning + the
  re-derive-when-it-lands instruction); C's matrix pins the absence
  loudly (2 tests flip when the parsed root lands) + the strict xfail
  re-deriving all five deltas stays until the coordinator lands the
  parsed authority (a decompose-pipeline write task, out of scope).
- FILES: EDITED src/calculator/champions/gnar.py (the authority
  receipt comment ONLY — the constants unchanged, certified),
  tests/test_gnar_mega_gamefile.py (C-owned, 58 tests: 57 PASS + 1
  strict xfail), tests/test_yasuo_yone_q3_crit.py +
  tests/test_zeri_p_execute_range.py (the manifest-domain pins re-based
  to the branch's regenerated digests — champions 38e5019f909b756c,
  abilities 65cf8c425ec587e7 — verified against the on-disk files),
  HANDOVER.md.  gnar.py's uncommitted Q/R work (the pre-existing dirty
  diff) untouched.
- GATES: sanity 714 passed + 6 xfailed + the 2 known pre-existing app
  rate-limiter flakes (pass isolated); full pytest TWICE stable: 7301
  passed + 22 xfailed both runs (7244 + 57 new; the 22nd xfail is the
  GnarBig-root delta re-derivation); black clean; FULL-SRC pylint
  9.55/10 UNCHANGED (zero new findings); atomize twice content-identical
  (manifest only); golden compare: 1007 rows — ZERO new from this slice
  (the certified constants + the authority comment change no outputs;
  the 2 Gnar rows are pre-existing classifier tags), baseline NOT
  recaptured; Catalyst + resource-ledger suites: 140 passed.
- HELPER STATUS: gnar-mega-provenance + gnar-mega-tests reviewed
  (reports above); gnar-mega-runtime BLOCKED after the bounded wait
  (no report received; the seam facts it would cover — the panel, the
  AS math, the E/R consumers, the API output — were independently
  verified by C's live pins) — recorded before deletion.

Follow-ups (recorded): land the parsed GnarBig root (extend
decompose_binaries.py + the receipt — a write task) to flip the
absence pins + the strict xfail; on patch updates verify the constants
against the local client's Gnar.wad.client data/characters/gnarbig/
gnarbig.bin (or the CDragon URL) minus gnar's root, never the wiki
stat box.


### 4.70 P4 Vladimir E (Tides of Blood) charge time (2026-08-09): the atom-backed fail-closed read swap + the charge-model certification

- THE VERDICT: the charge model (the fraction interpolation between the
  sourced Minimum/Maximum Magic Damage rows via e_charge_fraction,
  default 1.0 = fully charged) is magnitude-CERTIFIED (cache <-> binary
  <-> atoms <-> module all agree: 1.5s channel [binary Effect7 + the
  timing.active_duration atom 367b90ae9fc5cf38], 1.0s ramp [binary
  Effect8 + mChannelDuration, wiki prose only — NO atom, the degraded
  "charge time" row], min 30..90 + 1.5% maxHP + 35% AP, max 60..180 +
  6% + 80% AP, slow 40..60% for 0.5s, cost 2/4/6/8% tiers in the units
  prose).  B's audit demonstrated the fail-open gaps (missing rows ->
  silent 0.0; missing cooldown -> zero-CD over-cast; the
  ctx.stats.get("health", 0.0) literal fallback) — the completion lands
  the ATOM-BACKED FAIL-CLOSED READ SWAP (the Briar-E precedent): all
  six min/max row reads + the cooldown (timing.cooldown
  15cbce498dc12195 [13,11,9,7,5]) resolve through required_ability_atom
  / ranked_ability_atom_value (missing/stale rows RAISE naming the
  source — never a silent 0.0), ctx.stats["health"]/["ability_power"]
  direct reads (the pipeline always supplies them), the bool-fraction
  hardening, with ZERO semantic change (the default-option numbers
  byte-identical).
- THE CERTIFICATION SURFACE: TIDES_OF_BLOOD_CHARGE_RULE (the Asol
  pattern: public_receipt with ramp 1.0 / channel 1.5 / default 1.0 /
  the atom_ids / the ramp_source naming the wiki prose root) +
  E_HEALTH_COST_RULE + E_SLOW_RULE (the documented boundary receipts:
  the cost's 2%/8% endpoints + the below-12% free clause from
  effects[4] — priced: False, no attacker current-health input exists;
  the slow 40..60% for 0.5s at full charge only — utility).
- NAMED BOUNDARIES: the engine does NOT time the channel (the E damage
  lands at the cast start; the 1.5s auto-recast, the 20% channel
  self-slow tail, the health cost, the 12% free clause, the enemy slow
  — all named out-of-scope; a full 1.5s cast_time would be WRONG for
  this kit — W stays usable mid-channel); the binary-vs-wiki cooldown
  drift (the binary channel atom carries 15.0 rank-1 vs the cached
  13/11/9/7/5 the module reads — a patch-day flag); the stale 2019 E
  template receipt 2864482 vs the 13.17-rework content; the ramp shape
  (linear interpolation — data has only constants, no curve).
- FILES: EDITED src/calculator/champions/vladimir.py (the read swap +
  the rule + the boundary receipts + the ASSUMPTIONS note),
  tests/test_vladimir_e_charge_time.py (C-owned, 59 tests — the 4
  xfails reconciled: the cost + free-rule + slow boundaries via the
  receipt rules, the charge-model certification), the manifest-domain
  pins across test_yasuo_yone_q3_crit.py / test_zeri_p_execute_range.py
  / test_gnar_mega_gamefile.py / test_vladimir_e_charge_time.py re-based
  to the branch's live digests (champions 49e1c1ddcb91244a, abilities
  56c47afaf5f0b20b, stats 2917a0f457713533 — the shared worktree's
  regenerations keep moving them; the manifest + the files agree),
  HANDOVER.md.
- GATES: sanity 794 passed + 6 xfailed + the 2 known pre-existing app
  rate-limiter flakes (pass isolated); full pytest TWICE stable: 7360
  passed + 22 xfailed both runs (7301 + 59 new); black clean; FULL-SRC
  pylint 9.55/10 UNCHANGED (zero new findings); atomize twice
  content-identical (manifest only); golden compare: 1007 rows — the 12
  Vladimir rows are the PRE-EXISTING dirty-state rows (the E parse
  detail + the classifier tags + the F-series sustained E doubling —
  recorded by A as not-this-parser; the atom-backed swap is
  behavior-identical, so ZERO new from this slice), baseline NOT
  recaptured; Catalyst + resource-ledger suites: 140 passed.

Follow-ups (recorded, patch-day): re-pull the E template receipt (the
2019 rev vs the 13.17+ content); the binary-vs-wiki cooldown drift
(15.0 vs 13/11/9/7/5); the mChannelDuration-vs-Effect7 window
ambiguity (the buff bin/script absent locally); the ramp shape's
linear interpolation is an assumption (endpoints sourced); the
health-cost + 12%-free + slow stay named boundaries.

## 5. Current worktree boundary

The worktree is shared and heavily dirty. The current status contains many existing user changes, generated catalogs, frontend changes, tests, and new files. Preserve all of them.

The most recent completed code slice touched these areas:

- `src/calculator/champions/engine.py`;
- `src/calculator/champions/jax.py`;
- `src/calculator/interaction_effects.py`;
- `src/calculator/damage.py`;
- `src/calculator/participant_timeline.py`;
- `src/calculator/survival/actions.py`;
- `src/calculator/survival/transitions.py`;
- `tests/test_interaction_atoms.py`.

Two partial Briar atomizer edits were made after the last full validation:

- `src/calculator/champions/slotlib.py` now has a prose extractor for a percentage damage-reduction phrase and a helper that returns all control durations in one description.
- `src/calculator/atomizer_domains.py` now emits `ability.damage_reduction` and `timing.control_duration_sequence` for those phrases.

The Briar champion module was not changed.  The Briar atomizer edits
have been CLOSED OUT by P1 package 3I (§4.32): the catalog
`data/atoms/abilities.json` was regenerated (hash-identical to live
atomization), the extractor edits were formatted/linted/test-covered, and
the governance (WRITERS) + OPTIONS-to-atom tie landed.

The following files are present as user-owned changes or additions and require ownership checks before edits:

- `src/calculator/ability_atoms.py`;
- `src/calculator/interaction_effects.py`;
- `tests/test_interaction_atoms.py`;
- `data/atoms/abilities.json`;
- `data/atoms/champions.json`;
- `data/atoms/economics.json`;
- `data/atoms/items.json`;
- `data/atoms/manifest.json`;
- `data/atoms/runes.json`;
- `data/atoms/stats.json`;
- `DESIGN.md`;
- `uv.lock`;
- `static/img/rift-background-user.webp`.

Wave 1 (2026-08-09) added these owned changes on top of the above (all
preserved, none committed):

- `src/calculator/champions/briar.py` (E damage-modifier window + control),
  `src/calculator/support_effects.py` (damage_modifier self-state carry),
  `src/calculator/survival/compile.py` (DAMAGE_MODIFIER template compile +
  fail-closed receipts), `tests/test_briar_e.py` (new).
- `src/calculator/item_effects.py`, `item_support_effects.py`,
  `item_coverage.py`, `participant_timeline.py` (resource/vision utility
  buckets + `source_atoms` + `damage_reduction.multiplier_windows`),
  `static/js/app.js`, `docs/cp20-remaining-item-gaps.json`,
  `tests/test_cp20_items.py` (new).
- `src/calculator/healing.py` (Sett P, Maokai P), `champions/sett.py`,
  `maokai.py`, `mordekaiser.py`, `zoe.py`, `reksai.py` (ASSUMPTIONS),
  `tests/test_self_healing_champions.py` (new).
- `champions/varus.py`, `vladimir.py`, `darius.py`, `nasus.py`,
  `aurelion_sol.py`, `aurora.py`, `caitlyn.py`, `orianna.py`, `gnar.py`,
  `xayah.py`, `aphelios.py`, `senna.py`,
  `tests/test_mechanics_packets.py` (new).
- Central integration: `tests/test_p7_validation.py` (Aurora Q certainty
  pin: boundary → estimate with `q_marked_enemies`), `champions/briar.py`
  (rotation declaration for `e_charge_seconds`), `participant_timeline.py`
  (public `source_atoms` + multiplier-window receipts),
  `champions/slotlib.py` + `participant_timeline.py` (Black formatting of
  the handover's unfinished slice and the integration edits).

## 6. Last validation evidence

Wave-1 integration gates (all green, 2026-08-09):

```text
.venv/bin/pytest -q
5533 passed, 7 xfailed in 144.57s  (P3 Package 2: 5505 + 28)

.venv/bin/black --check src/ tests/ scripts/
501 files would be left unchanged

.venv/bin/pylint <P3 Package 2 source files>
9.73/10; no E/F class findings; the rest are the documented pre-existing
warning classes

.venv/bin/python scripts/atomize.py all --out data/atoms
atomized ['abilities', 'champions', 'economics', 'items', 'runes', 'stats'] -> data/atoms

.venv/bin/python scripts/golden_snapshot.py compare scripts/golden_baseline.json
FAIL: 847 difference(s) vs scripts/golden_baseline.json  (baseline NOT recaptured)
— 845 pre-existing + 2 NEW expected declaration lines (Jayce W
resource_restore_per_auto; Ezreal W mark_refund) — see §4.23; zero
fight-summary changes.
```

Golden diff taxonomy (every difference explained; the baseline predates the
goal's event-metadata work, so the count is larger than the pre-wave 454,
which was measured on a partially-broken tree):

- ~704 event-metadata marker lines (`skillshot`/`area_damage` `<absent> ->
  true on every champion's parsed entries; stamped by
  `champions/engine.py`, pre-wave authored work, zero damage-math impact).
- ~70 pre-existing authored control/rotation/survival lines (typed
  `parts[0]` cc_kind/cc_duration, `control_events` +
  `control_source_atoms` for Darius/Elise/Lulu/Nocturne/Rammus/Shaco/
  Soraka/Veigar/Xayah, Sivir E spell-shield self_state, Yasuo W wind-wall
  defensive_interaction, Braum E baseline entry + `breakdown_totals/E:
  0.0` keys, Vayne rotation order (Q/auto shift), Bel'Veth and Nautilus
  shadowflame drift, Horizon Focus 0.04 float drift).
- ~35 NEW at wave-2/pass-16 integration, all authored behavior:
  - Veigar (34 registered-fight lines + 1 R-detail line): the pass-16 execute
    curve (boost = min(1, missing_ratio/(2/3)) — 1.5% per 1% missing, capped
    at 66.66%) replaces the mirrored curve; R is boosted by the target's live
    missing health in every golden fight (Q+W land before R), and Shadowflame
    scales with the boosted R in magic builds. See §4.15.
  - BoRK pass-18 first-auto HP-walk ordering: ZERO golden lines (no
    first-auto+BoRK combo in the harness). See §4.16.
- ~36 NEW at wave-1, all authored behavior:
  - Nasus (26 registered-fight lines + 2 baseline lines): Q cooldown halved
    during Fury of the Sands (`r_q_cooldown_halved` default True when R
    ranked) — timed fights cast ~2× Q; autos and totals shift accordingly.
    This is the real in-game mechanic.
  - Vladimir (5 registered-fight lines + 1 baseline detail): E now reads the
    live cached cooldown array 13/11/9/7/5 instead of the reviewed packet's
    fixed 13.0, so a 5s sustained max-rank fight fits 2 E casts instead of 1;
    per-cast damage identical (max-row formula). `e_charge_fraction`
    default 1.0 = fully charged.
  - Briar (1 baseline line): E `self_state_events` damage-modifier receipt
    (metadata; run_fight damage numbers unchanged).
  - Senna (1 baseline line): W parts now carry sourced root cc
    (`cc_kind='root'`, 1.75s).
  - Fixture pin: `test_p7_validation.py` Aurora Q certainty
    boundary → estimate (`q_marked_enemies` option), with the reason
    asserted.

## 7. Immediate resume plan

### Step 1: run the full gates (green after every wave — see §6)

Wave-1, wave-2, pass-16, and pass-18 gates were run by the integration
coordinator on 2026-08-09: full pytest (5125), Black, targeted pylint
(9.71/10), atomizer regeneration, and the golden comparison with the
taxonomy above. The baseline stays untouched until the user authorizes a
recapture decision.

### Step 2: wave 2 — COMPLETED (see §4.13-4.14)

Ally support (11 champions, 4 new packet types) and keystone audit (Unsealed
Spellbook rejection kept) are integrated and green.

### Step 3: P1 — Trigger and State Lifecycle — COMPLETED (see §4.17)

Kernel + six consumers integrated and green (5197 tests, golden 845 with
zero new diffs). Next: P2 — Delivery and Interaction Eligibility (typed
projectile/hitscan/area/targeted/basic-attack/DoT delivery + eligibility
filters, block uses, first-hit, destruction, reductions; regression
fixtures Braum and Yasuo; then spell shields, CC immunity, cleanse).

## 8. Remaining behavior work

The list below contains the remaining workstreams recorded in the repository audit and current champion assumptions. Some entries may already be partially covered by generic support or state code. Recheck runtime output before implementing a duplicate packet.

### 8.1 Remaining item packets from CP20 — COMPLETED (wave 1)

All six items (Cull, Phage, Runic Compass, Tear of the Goddess, Umbral
Glaive, World Atlas) are implemented end-to-end; see §4.10. Remaining
per-item notes: Runic/World Atlas Bounty of Worlds 4-ward stock and ward
placement range (600) are role-quest/map transforms, not modeled; Tear's
3-mana minion floor never fires (no non-champion targets) and resource
packets are receipt-only; Umbral's Blackout aura range (400), cooldown
(90), and ward-denial target count stay receipt-only.


The authoritative local list is `docs/cp20-remaining-item-gaps.json`.

| Item | Remaining branches |
| --- | --- |
| Cull | Reap on-hit healing, 100-minion progression, 350-gold completion payout |
| Phage | Rage melee movement speed, Rage ranged movement speed, two-second duration |
| Runic Compass | 800-gold Support Quest, Shared Riches, Ward active |
| Tear of the Goddess | Manaflow timing, 3/6 bonus-mana triggers, 360 bonus-mana cap, minion-only Helping Hand |
| Umbral Glaive | Blackout vision state, one-second unseen gate, four-second trigger window, 50 + 1.5 lethality true damage |
| World Atlas | 400-gold Support Quest, Shared Riches, Ward active |

Each item needs typed values in `item_effects.py`, ordered packets in `item_support_effects.py`, participant application in `participant_timeline.py`, optimizer coverage in `item_coverage.py`, and public receipts in `static/js/app.js` where applicable.

### 8.2 Item timing and optimizer certification — NEXT (roadmap P1/P3)

Still withheld/coarse (P1 now owns the receipt-side stack/CC predicates for

self-shield + proc timing, Muramana ability timing, Fimbulwinter CC
packet certification; the compiled-walk unrepresentable list (Banshee's
Veil, Edge of Night, Death's Dance, Doran's sustain, Force of Nature,
Guardian Angel, Jak'Sho, Knight's Vow, Maw, Verdant Barrier); active
UI controls for Zhonya's/Mikael's/Redemption; Cryptbloom takedown heal — COMPLETED in P1 package 3K (§4.34): compiled parity + target-synthesis fixes, timed-heal compile representation, modeled_state coverage,
Gluttonous Greaves omnivamp — COMPLETED in P1 package 3L (§4.35): typed Slay stack option + accessor + stat/receipt projection; Lost Chapter mana, Doran's Helm minion-only damage — COMPLETED in P1 package 3M (§4.36): typed + atom-backed 5.0 with a receipt-only named boundary (no minion target in the 1v1 model);
damage, Ionian Boots summoner haste, Gunmetal Riot branch.

The audit identifies these item branches as withheld from BIS or still coarse:

- Bastionbreaker's shaped-charge packet — COMPLETED in P1 package 3D
  (§4.27): named malformed-ledger receipt + coarse coverage, DoT proc
  precision fix, source receipt wired; Sabotage remains a named boundary
  (turret/epic-monster targets unmodeled).
- Eclipse's stack self-shield and proc timing — COMPLETED in P1 package
  3C (§4.26): named malformed-proc/shield receipts, shield timing on the
  receipts, explicit same-time ordering, tuple-ledger hardening, source
  revision wired. DoT/CC stack-source certification — COMPLETED in
  §4.26A: reviewed control-only applications use typed target and cast
  identities with same-cast deduplication; generic DoT timing fails
  closed with a named receipt. Multi-target roster and sourced DoT
  application timing remain follow-ups.
- Muramana ability timing — COMPLETED in P1 package 3E (§4.28): named
  malformed-ledger receipt, zero-damage-cast gate, never-fired row
  suppression, source receipt wired; the 6.5s per-target Shock lockout
  remains a documented follow-up.
- Fimbulwinter's crowd-control packet certification — COMPLETED in P1
  package 3B (§4.25): named denial receipts, control-only triggers,
  stable shield identity, tuple-ledger hardening; the per-champion
  "reviewed, no CC" opt-in markers remain a follow-up.

The current compiled-walk unrepresentable list also contains stateful paths such as Banshee's Veil, Edge of Night, Death's Dance, Doran's sustain effects, Force of Nature — COMPLETED in P1 package 3Q (§4.40): per-instance 1s Steadfast cadence with the compiled path certified; Guardian Angel — COMPLETED in P1 package 3P (§4.39): lethal-anchored Rebirth with full score/receipt parity and the compiled path certified; Jak'Sho — COMPLETED in P1 package 3R (§4.41): combat-time Voidborn stacks with the compiled path certified (tuple-ledger fail-closed repaired) and the 30% bonus-resistance reprice pinned; Knight's Vow — COMPLETED in P1 package 3S (§4.42): the Worthy redirect split + holder heals staged per panel with a unit-targeted no-selection designation contract; Maw of Malmortius — COMPLETED in P1 package 3T (§4.43): the Lifeline threshold shield + walk-authored omnivamp heals certified on the compiled path with byte parity; and Verdant Barrier — COMPLETED in P1 package 3U (§4.44): the Annul spell shield certified on the compiled path with byte parity (the LAST remaining item — the compiled-walk unrepresentable list is now EMPTY).

Active/input-gated item work needs clear UI controls and receipts —
Zhonya's Hourglass COMPLETED in P1 package 3F (§4.29): step-enforced
bounded input, provenance fields, parity-pin fix, named boundaries
(mid-fight activation, 120s cooldown, legacy-headline stasis-blindness).
Mikael's Blessing COMPLETED in P1 package 3G (§4.30): emission-layer
step/bounds validation, utility-panel cleanse counting, coverage wording,
config pin. Redemption COMPLETED in P1 package 3H (§4.31): vision receipt
for the sourced call-down window, cooldown corrected to the binary 90.0,
unsourced reveal duration removed, cast-range semantics named, compiled
fallback parity documented.

The remaining stats-only or mixed item audit includes Cryptbloom's takedown heal, Gluttonous Greaves omnivamp — COMPLETED in P1 package 3L (§4.35): typed Slay stack option + accessor + stat/receipt projection; Lost Chapter mana, Doran's Helm minion-only damage — COMPLETED in P1 package 3M (§4.36): typed + atom-backed 5.0 with a receipt-only named boundary (no minion target in the 1v1 model); damage, Ionian Boots summoner haste — COMPLETED in P1 package 3N (§4.37): typed + atom-backed 10.0 with a receipt-only named boundary (no summoner-spell action model), never an ability-haste packet; and the Gunmetal Riot-only branch — COMPLETED in P1 package 3O (§4.38): typed noxian_gait_boundary receipt (sourced 2.0s decay + champions-only target; magnitude UNSOURCED — wiki branch absent, binary-only, no decaying-movement model).

### 8.3 Keystone and rune work — COMPLETED (wave 2, §4.14)

Wave-2 owner decides Unsealed Spellbook (model vs documented rejection)
and audits keystone state inputs (keystone_options, proc timing, target
selection, action downtime, score-vs-receipt parity) plus minor runes.


The current keystone compiler has typed implementations for Electrocute, First Strike, Press the Attack, Arcane Comet, Summon Aery, Guardian, Aftershock, Grasp of the Undying, Hail of Blades, Lethal Tempo, Glacial Augment, Stormraider's Surge, Fleet Footwork, Conqueror, Deathfire Touch, and Dark Harvest.

`Unsealed Spellbook` remains in `data/runes.json` without a compiler entry. It currently fails closed. Decide whether to model its spell-selection state or keep the explicit rejection.

Audit all keystone state inputs, especially `keystone_options`, proc timing, target selection, action downtime, and score-versus-receipt parity. Minor rune interactions need the same typed treatment when they affect damage, shields, healing, resources, or state.

### 8.4 Champion self-healing — COMPLETED (wave 1)

See §4.11: Sett P and Maokai P implemented; 17 rules verified/locked;
7 documented fail-closed boundaries (Bard W, Cho'Gath P, Pyke P,
Rek'Sai P, Zoe W mimic, Morde R, Ekko R rider).


The deep audit lists these heal-named champion mechanics as missing or requiring a runtime audit:

Alistar, Bard, Cho'Gath, Ekko, Fiora, Garen, Illaoi, Kayle, Kindred, K'Sante, Locke, Pyke, Rakan, Rek'Sai, Seraphine, Sett, Sylas, Trundle, Udyr, Vladimir, Yuumi, and Zoe.

Additional self-heal mechanics use non-heal names and need field-level review. The audit calls out Swain, Nasus, Maokai, Tahm Kench, Volibear, Xin Zhao, Mordekaiser, Gwen, and Camille.

For each champion, identify the trigger, target, amount formula, healing reduction behavior, timing, death boundary, and source atom. Add a healing rule only when the live target health required by the formula is available.

### 8.5 Ally support coverage — COMPLETED (wave 2, §4.13); the only
real gap is Renata W Bailout (needs a mid-fight conditional revive
survival/ kind — roadmap P1 state-kernel work).

Sona, Nami, Yuumi, Seraphine, Taric, Rakan, Karma, Milio, Renata,
Janna, Ivern. Wave-2 owner runs the per-packet verification checklist
and produces the audit table; 63 champions with shield-named spell
objects in the cache — source inventory is the completeness check.


Audit champion-owned shields and heals for Sona, Nami, Yuumi, Seraphine, Taric, Rakan, Karma, Milio, Renata, Janna, Ivern, and every other champion with a support attribute in the cache.

For every packet verify:

- self versus ally ownership;
- target scope;
- selected teammate index;
- repeated cast selection;
- shield pool and expiry;
- live missing-health or maximum-health formula;
- healing reduction;
- source atoms and public receipt;
- score and receipt adapter behavior.

The cache reports 63 champions with shield-named spell objects. Use the source inventory instead of assuming the current support registry is complete.

### 8.6 Champion mechanics — COMPLETED (wave 1)

See §4.12: 11 packets implemented (Varus Q charge, Vladimir E charge,
Darius R recast, Nasus R Q-halving, ASol/Aurora/Caitlyn/Orianna/Gnar
secondary targets, Xayah feathers, Aphelios follow-ups, Senna W root).
Remaining document-only: kill boundaries (Syndra R execute, Darius W
refund, Kog'Maw death passive, Cho'Gath kill gains), stack expiry
(Ashe Focus 4s, Rengar Ferocity 1s), attack-reset throughput (Vayne Q,
Dr. Mundo E), Jayce cross-stance rotation + W mana restore, Senna Relic
Cannon rider (needs engine on-hit contract extension), Bel'Veth
Runaan's, Ziggs turret threshold, Orianna W slow field, Rengar movement
state, Quinn P crit (no cached row), Caitlyn brush doubling.


These are the main known behavior families from the current modules. Verify each against the runtime before implementation because a generic path may already cover part of a listed assumption.

| Family | Known remaining or audit candidates |
| --- | --- |
| Secondary-target and splash behavior | Aurelion Sol Q secondary beam, Aurora Q subsequent bolts, Bard chime splash, Caitlyn secondary values, Gnar Q reduced damage, Orianna secondary-target reduction, Xayah secondary-target damage |
| Charges and channel windows | Briar E reduction and CC, Varus Q charge, Vladimir E charge, Taliyah distance timing, Hwei charge branches |
| Resets and recasts | Darius R execute recast, Darius W kill refund, Nasus Q cooldown reduction, Vayne Q reset acceleration, Dr. Mundo attack reset, Jayce form transitions, Vi and similar reset inputs |
| Self defense and state | Diana W shield assumption needs verification, Annie E retaliation, Ivern state, Kled grey health, Briar E, Viktor and other shield/state packets |
| Passives and stack expiry | Ashe stack expiry, Rengar Ferocity expiry, Senna passive on-hit, Nasus permanent gains, Bel'Veth passive details, Bard chimes, Aurelion Sol Stardust |
| Heals and sustain | Cassiopeia E heal, Darius and Mundo kill boundaries, Dr. Mundo self sustain, Nasus, Vladimir, Rakan, Sylas, Kayle, Kindred, Udyr, Volibear, Xin Zhao |
| Pets, summons, and terrain | Azir Sun Disc, Zyra plant attack state, Yorick Maiden and mark state, Jarvan IV E ally aura, Ivern leash state, Taliyah terrain, Kog'Maw passive |
| Utility and target rules | Orianna W slow field, Bard slow, Camille slow, Briar slow, Rengar movement state, Jayce mana refund, Ezreal mana refund, Aphelios Moonlight Vigil follow-ups |
| Execute and kill boundaries | Syndra 100-stack R execute, Ziggs turret threshold, Kog'Maw Icathian Surprise, Darius R recast, Nasus and Cho'Gath kill gains |

The current named-module assumptions also mention Aphelios Moonlight Vigil follow-ups, Bel'Veth Runaan's behavior, Caitlyn brush doubling, Senna Relic Cannon's 20% AD rider, and Zeri or Quinn special scaling. Review those packets individually.

### 8.7 Known degraded parser cases

Vladimir E charge time now has a typed selection (`e_charge_fraction`, §4.12). Remaining: Aurelion Sol Q Stardust, Bard P Chimes, Heimerdinger W/E,
K'Sante W, Quinn P crit, Yasuo/Yone Q3 crit conversion, Zeri P execute
range, Gnar Mega game-file verification (patch updates).


The project instructions identify these known degraded wiki parses:

- Aurelion Sol Q Stardust scaling;
- Bard P Chimes;
- Heimerdinger W and E multi-part rockets;
- K'Sante W bonus resistances;
- Quinn P critical chance;
- Vladimir E charge time;
- Yasuo and Yone Q3 critical conversion;
- Zeri P execute range;
- Gnar Mega form stat deltas.

Named modules exist for these cases. Verify each source path and option. Gnar Mega constants require game-file verification because the wiki stat box has been stale in prior patches.

### 8.8 Full decomposition and certification work

The deep audit defines seven long-running workstreams:

1. Full Wiki article ingestion for mechanics, buffs, statuses, CC, objectives, minions, turrets, terrain, vision, runes, and patch history.
2. Game binary ingestion for CharacterRecords, SpellData, ItemData, BuffData, rune data, and map data.
3. A dual-provenance fundamental behavior catalog.
4. Champion recomposition for self-healing, ally support, class semantics, and per-slot quirks.
5. Item recomposition for timing, state, and optimizer certification.
6. Certification with zero unexplained BIS withholdings and complete receipts.
7. Practice Tool reproducibility with deterministic scenario fixtures and combat-log comparison.

These workstreams are documented in `docs/deep-audit-2026-08.md`. The CP20 item document currently reports local implementation ready with preview evidence pending.

## 9. Definition of done for each new behavior

A behavior is complete when all applicable points are true:

- The source cache has the required value.
- The atomizer emits the value with units, evidence, and a valid hash.
- The named champion or item module reads the atom through a typed accessor.
- The event or state packet has explicit timing and target policy.
- The survival action carries every field used by the transition.
- The receipt walk applies the packet at the correct phase.
- The score adapter has the same semantics or fails closed with a named receipt.
- The public result shows the source and selected inputs.
- The UI exposes a required selection or active window.
- Focused tests cover the source, formula, timing, target, and interaction.
- The full suite passes.
- Black and targeted pylint pass, with existing warnings separated from owned warnings.
- Atom catalogs regenerate successfully.
- Golden differences are reviewed and explained.

## 10. Resume checklist

Use this order when the goal resumes:

1. Read this file and `architecture.md`.
2. Run `git status --short`.
3. Inspect the partial Briar edits and current atom catalog state.
4. Finish and test Briar E.
5. Regenerate `data/atoms/`.
6. Run focused interaction and atomizer tests.
7. Run the full test suite.
8. Run Black, targeted pylint, and the golden comparison.
9. Select the next bounded slice from CP20 items, rune coverage, support coverage, or champion self-healing.
10. Preserve all unrelated dirty changes.

Use `.venv/bin/python` for repository scripts. Bare `python3` has failed before test collection in this checkout because of runtime annotation compatibility.



## 11. Durable atomization roadmap (coordinator directive, 2026-08-09)

Design rules:

- Numerical and quantifiable source values become Atom records with exact
  evidence and hashes.
- Categorical mechanics become small typed declarations with source receipts.
- User decisions become scenario options with public receipts.
- Keep the contracts orthogonal and composable.

Priorities (in order; actor lifecycle, pets, and summons follow after state
lifecycle and spatial topology are stable):

- **P1 — Trigger and State Lifecycle**: thresholds, stack caps, durations,
  tick rates, lockouts, refresh, expiry, consume policy. First consumers:
  Eclipse, Fimbulwinter, Conqueror, Force of Nature, Ashe stacks, Rengar
  Ferocity.
- **P2 — Delivery and Interaction Eligibility**: typed projectile, hitscan,
  area, targeted, basic attack, and damage-over-time delivery plus
  eligibility filters, block uses, first-hit behavior, destruction,
  reductions. Regression fixtures: Braum and Yasuo; then extend spell
  shields, crowd-control immunity, and cleanse rules.
- **P3 — Resource and Counter Ledger**: mana, energy, fury, ammo, charges,
  permanent counters, gain, spend, refund, cap, decay, source ownership.
  First consumers: Tear, Lost Chapter, Jayce, Ezreal, Rengar, Senna,
  Aurelion Sol.
- **P4 — Cast Lifecycle and Action Economy**: windup, channel, charge cap,
  recast window, reset, cooldown refund, attack reset, action lock. First
  consumers: Varus Q, Vladimir E, Darius R/W, Nasus Q, Vayne Q, Dr. Mundo,
  form transitions.
- **P5 — Spatial Zone and Vision Timeline**: radius, range, travel speed,
  zone duration, occupancy, terrain collision, brush state, unseen gates.
  First consumers: Umbral Glaive, Gwen, Ivern, Taliyah, terrain/brush.

Delegation structure per priority:

- One RLM-1 owner controls the shared contracts and kernel files.
- RLM-2 children perform read-only source inventories, provenance checks,
  and test-matrix design; write access for an RLM-2 child only to an
  explicit disjoint test file.
- After the primitive is green, separate RLM-1 owners recompose disjoint
  champion, item, and rune modules.

Certification gate (per priority, before promotion):

- unused atoms; unsourced runtime numbers; unsupported semantic
  declarations; receipt-versus-score parity; public option receipts.

Gate sequence for every slice: focused tests, full pytest, pylint for source
changes, atomizer regeneration, golden comparison with every numeric
difference explained. Preserve unrelated edits and current publication
authority limits (no stage/commit/push/merge/PR/auto-merge without user
authorization).
