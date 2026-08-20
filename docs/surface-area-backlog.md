# Surface-area backlog

What the surface-area campaign (`docs/plans/2026-08-20-surface-area-campaign.md`) surfaced
but did not fix: asides from the eleven unit reports and the blind audit, de-duplicated and
re-verified against the tree at `0fa19e6`. Ordered by the cost paid today. Delete a row
when its fix lands; this file is the one home for the list.

## A. Engine numbers and semantics

| # | Where | What | Action |
|---|---|---|---|
| A1 | `src/calculator/damage.py` ~7620-7690 (Liandry's/Blackfire burns; Hatefog refresh tail at `:7684 if "R" in ability_damages`) | Burns fire in `auto_only` with no ability hit (Ahri + Liandry's: burn 35.0 + amp 8.8, certified exact); the Hatefog tail extends them off the R *key*, not an accepted R cast. Same family as U05b's fix for Horizon Focus / Malignance. | Gate on a damaging ability hit / the rotation's accepted R, like 0ff91c6 and 23af61b did; add the census-style probe. Golden will move for `auto_only`-style cells only. |
| A2 | `damage.py` `_add_expose_weakness` | Prices (total − arming sequence) × rate even when its own ledger holds nothing after the arming proc (Vayne one_rotation: 22.8 on an empty pool). Standing ruling Phase 4 S7. | Re-rule: the coarse label is honest but the number disagrees with the ledger. |
| A3 | spellblade weave (`damage.py`) | Arming proc placed at a fixed 1.5 s even when the on-hit-applying ability lands at 0.0 (Ezreal Q, Senna Q). | Take the proc time from the ability's hit time. |
| A4 | `damage.py` ~4830 | Post-rotation Vile Decay MR is overwritten by `use_auto_pen()` when Terminus is held — ordering quirk. | Resolve MR once, after both. |
| A5 | `damage.py` `_simulate_ordered_damage` + `program/build.py:410-443` | In coupled fights with Shadowflame the second shield walk runs in full and its Cinderbloom row is dropped and re-priced (`pair_preview_of`); only the Liandry `adjustments` half survives. | Skip the Cinderbloom half when the caller is coupled. Golden-relevant. |
| A6 | `damage.py:1403-1781` `_ordered_damage_events` (+ `_event_timeline_coverage` ~1782) | One row schema in six literal spellings (light tuple / lean dict / full dict × `add` / `add_declared_events`), kept in step by a comment. | One row factory the three shapes project; float-addition order is load-bearing (`survival/accumulate.py`), so golden must show zero diffs. |
| A7 | `public_response.py` / `calculate.py` | Solo `/api/calculate` carries a `combat.breakdown` row with `participant_id ""` and `total_damage 0.0` — a placeholder in the public shape. | Drop the empty row. |
| A8 | `static/js/app.js:2378` `exactObjectiveMetric` | With allies, the "damage" objective shows team damage while the validation receipt predicts the attacker's row — a number no receipt should match. | Either the widget says so or `displayed_prediction` grows the rule. |

## B. Fallbacks and single-home violations still standing

| # | Where | What | Action |
|---|---|---|---|
| B1 | `src/calculator/economy.py:55-73` `item_total()` | Falls back to the wiki-cache total when no sourced row exists. `refresh_economics_data.stale_reasons` now guarantees a row for every ordinary SR item, so the fallback is dead for them and silent for anything else. | Raise. |
| B2 | `item_effects.py` ~4811 `ITEM_EFFECTS[name].get("ultimate_haste", 0.0)` | Same uneven-sibling read the U03 sites had. | `_declared_effect_value`. |
| B3 | `item_effects.py` ~32 `ENERGIZED_SOURCE_RECEIPT["distance_units_per_stack"]` | No src reader (only `tests/test_issues_45_43.py:388`); a second home for the per-item static key's 24.0. | Delete; the static key is the owner. |
| B4 | `passive_parser.py:2742-2745` `parse_all_item_effects` | Silently drops an item whose `parse_item_effect` returns None/empty; surfaces only on read or via the parity test. | Raise naming the item. |
| B5 | `roster_composition.py:101,150-155`, `participant_timeline.py:965/975` (`Combatant.request: Any`); `survival/transitions.py:261,264` `getattr(self.ledger, "records_*", True)`; `program/compile.py:1569-1575` `getattr(payload, …)`; `item_coverage.py:~635-660`, `interpreters/stat_derivation.StatSlot.granted`, `gated_state_reason` `getattr(payload, name, None)` | The U09 family on other subjects: declared-absence reads across typed objects. | Type the field (Protocol/Union) and read directly, as 5a260de did for `defenses`. |
| B6 | `app.py api_champions` `champ_data.get("icon","")` / `get("patchLastChanged")`; `optimizer.item_gold` `.get(...).get("total", 0)` | Literal defaults on cache-owned fields. | Required reads. |
| B7 | `src/calculator/champions/*.py` — 75 modules `SOURCES = [ {literal row} ]`; 24 `load_champion_sources(...)`; the rest via `build_packet_module` | Three ways to populate one receipt; the 75 inline literals bypass `source_receipts._source_index()`, so a patch-day revision bump lands in two unrelated places. | Codemod the literals onto `load_champion_sources` once the batch assets carry every name. |
| B8 | `healing_legacy.HEALING_RULE_CHAMPIONS` ↔ 57 × `SELF_HEALING_RULE`; 57 × 3-line late import `# pylint: disable=wrong-import-position` | Membership validated one direction only (a module that declares but is absent from the set is silently ignored); the late import is a circular-import workaround copy-pasted 57 times; `_legacy_derive_self_healing` is 1,741 lines of `if name ==` for 56/57 "unmigrated" rules. | Two-line reverse assertion now; the import restructure and the real migration are their own campaign. |
| B9 | `scripts/build_bis_profiles.py`, `build_ability_catalog.py` | Import zero `src`; re-parse `data/champions.json` and re-derive ability leveling, then publish to the UI (`app.js:4706-4707`). A second ability-parsing home with no gate comparing it to the engine. `("P","Q","W","E","R")` literal copies ×6 (`build_ability_catalog.py:22`, `build_bis_profiles.py:24`, `app.py` ×2, `capabilities.py`, `certainty.py`) vs `cast_dependency.BASE_CAST_SLOTS`. | Build both catalogs from the champion contracts; import the slot tuple. |
| B10 | `.claude/skills/` ↔ `.agents/skills/` | Near-identical trees; every skill edit this campaign was made twice. | One tree, one pointer (the `Agents.md` treatment). |
| B11 | `static/data.json` | Hand-committed, no generator in `scripts/`, one patch stale (Spellslinger's Shoes `percentPen`, Redemption price). Since 7cc64a9 the picker reads the API for every stat it serves. | Generate it on patch day or shrink it to icons. |

## C. API / UI

| # | Where | What | Action |
|---|---|---|---|
| C1 | `/api/champions` entries; `app.js:41-42,2061,3766,4733`; `public_loadout_summary` | One registry fact in five fields (`verified`, `engine_registered`, `engine_backend_enabled`, `availability.ready`, `engine_registration`); app.js keeps two always-equal sets; the summary emits it thrice. | One field. UI-visible contract change — propose first. |
| C2 | `app.js` (~1965, 2378, 3172, 3238) + `validation_receipts.displayed_prediction` | The "headline the main combat row" rule is spelled ≥3× in JS and once in Python; nothing ties them. | A `headline_total` leaf on the response, read by both. |
| C3 | `static/js/feedback.js:200,302` | Hand-rolled `fetch("/api/receipts", {method:"POST"…})`; `postJson` exists. | Use it. |
| C4 | `/api/items` `into`, `categories` | Always `[]` — reads `item.get("into")`/`("categories")` while the cache keys are `buildsInto` / `shop.tags`; no consumer beyond the merge (`app.js:313-314`). | Serve them or drop them. |
| C5 | `app.py` `api_save_build`, `api_create_share` | DB writes with no `_spend_rate_limit` (the only sites are calculate/bis/optimize/receipts/metrics). | Spend a token. |
| C6 | `app.py:261` `_DEV_UPDATE_TOKEN = secrets.token_urlsafe(32)` | Minted per import → per-worker cookie for `/api/update-data`. | Derive from config or accept single-worker. |
| C7 | `docs/invite-flow.md:88` | Says the landing page calls `POST /api/auth/invite`; `templates/beta_landing.html` has no fetch (form posts to `/auth/login`). | Fix the doc or wire the check. |
| C8 | `db.list_metric_events` | Test-only. | Cut it if nothing will call it. |
| C9 | `docs/deploy.md:42` | Post-deploy metrics smoke only checks for a non-503. | Assert the scorecard shape. |

## D. Champion package

| # | Where | What | Action |
|---|---|---|---|
| D1 | `packet_module.build_packet_module` ~640-700 | Still R0912 (19/12) and R0915 (72/50); the variants loop is the natural `_variant_parsers` extraction. | Extract. |
| D2 | maokai, yorick, zyra, rengar, samira, sett, yasuo, yone, jinx, aphelios | Replace the compiled `ASSUMPTIONS` wholesale with stale copies of older compiler boilerplate. | Extend, don't replace. |
| D3 | ~40 custom parsers (`akshan.py:257`, `darius.py:215`, …) | `entry["event_order_certified"] = "single_hit"` hand-assigned — the fact, not a wrapper; fine, but `single_hit_slots` now exists for packet rows. | Opportunistic. |
| D4 | `swain.py` | `getattr(packet_r, "phase", "damage")` — compiled parsers always carry `.phase`. | Direct read. |
| D5 | `cast_dependency` / `rotation_resolver.DependencyReceipt` | A 7-ledger taxonomy computed for 3 declaring champions (brand, syndra, zed) and rendered by no client (`grep dependenc static/js/app.js` → 0). | Render it or stop publishing it. |
| D6 | `ability_spec.quantity_sum` (test-only), `parts_raw_total` (~100 test call sites) | Test helpers living in `src`. | Move to `tests/`. |
| D7 | `item_behavior.Attribution` | One-member enum (`HOLDER`) since `DAMAGE_SOURCE` went. | Remove the axis or give it a second live value. |
| D8 | `item_behavior.py` banner "Eight shapes", `stat_derivation.py` "nine shapes", tests "the tenth shape" | Ten payload types. | Count once, in one place. |
| D9 | `item_coverage.py:226-265` | Tombstone comments describing what used to stand there. | Delete (rule: current state only). |
| D10 | `survival/outcome_state.py` `adjust` / `Adjustment` / `HOLDER_HEALTH_GATE` | Zero production callers; the holder-health gate uses `ledger.skip` (`transitions.py:1243`), not `adjust`. Tests pin the revision contract. | Connect the gate to the API or delete the API. |
| D11 | `survival/compile.py:69-70` `requires_holder_health_ratio` | Can no longer fire — Knight's Vow's packet also carries `redirect_fraction`, which refuses first. | Delete or reorder deliberately. |
| D12 | `item_behavior_catalog.py` ~1302 `COMPILED_KERNEL_CANNOT_AMP` text; `ReceiptScope.SCORE_KERNEL_DAMAGE_MODIFIER` | "Until that stage's flip lands" — the flip landed; the constant is a documented revert target, its prose is stale; the scope is unreached in production. | Rewrite the prose; keep the symbol. |

## E. Tests and gates

| # | Where | What | Action |
|---|---|---|---|
| E1 | `tests/test_cp10_batch_01..11.py` (11 files, ~1.1k lines) | One ~100-line template over 12-champion slices of a batch schedule that no longer exists. | One parametrized test over `registered_champion_names()`. |
| E2 | `tests/test_f2_rotation.py` (1,024) vs `test_f3_rotation_all.py` (1,612) | F3's docstring says it replaces F2's hand-curated seeds; F2's unique cases are a handful of cadence checks. | Fold and delete. |
| E3 | `tests/test_migration_frontier.py:150-170,305` (`REPORT_TIP="067c94c"`), `tests/test_trigger_stream.py` ~2711-2800 (`git archive <commit>` per test) | Closed-campaign git walks inside kept product tests; the reason CI keeps `fetch-depth: 0`. | Pin the artefacts, drop the history walk, shallow-fetch CI. |
| E4 | 15 asserts on `<module>.MODULE_COVERAGE` (`test_tryndamere.py:22`, `test_twitch.py:21`, `test_udyr.py:22`, `test_veigar.py:32`, `test_viego.py`, `test_viktor.py:31`, `test_warwick.py:34`, `test_yorick.py:35`, `test_yuumi.py`, `test_zed.py`, `test_zilean.py:47`); `test_champion_module_contract.py:41-43`; `::test_no_packet_module_builds_a_parser_of_its_own` | Pin the declaration (or restate the implementation) rather than the contract; the last one greps source for the literal `"PACKET_SPEC"` and would trip on a comment. | Assert through the contract. |
| E5 | `tests/test_p7_validation.py::_payload` | Still sends `one_rotation` with no `target_*` — not the UI's shape (`_ui_payload` is). | Switch. |
| E6 | `tests/test_engine.py::TestDedicatedDispatch::test_dispatcher_fallback_uses_engine` | Name and docstring say "fallback"; nothing falls back. | Rename. |
| E7 | `scripts/pylint_ratchet.py` + `tests/test_pylint_ratchet.py`; `docs/receipts/campaign-fingerprints.json["pylint"]` | A per-file ratchet no CI step runs and no test compares to the live receipt (197 pinned files drift silently). | Wire as a gate or cut. |
| E8 | `scripts/golden_snapshot.py compare scripts/golden_coupled_exact.json` | Reports 7 spurious diffs (24 vs 20 scenarios) — `compare` ignores the file's `exact` flag; only the pytest path compares the exact set. | Honour the flag. |
| E10 | `.github/workflows/tests.yml:62` `TODO(issue #139)` | `champion_optimizer_matrix` receipt is not schema-validated. | Validate it like the others. |
| E11 | `scripts/coverage_census.py check` | Exact dict equality with the receipt: any roster/shop/certified-item change must regenerate `docs/coverage-census.json` in the same PR. | One line in `add-champion` / `add-item-effect` skills. |
| E12 | `tests/coverage_resolver.py` (1.8k) + `test_coverage_claims.py` (2.7k, subprocess pytest at `:654`) + `coverage_evidence.py` (1.1k) | 5.6k lines proving evidence strings name real symbols, run through `conftest.py` on every `pytest -k`. | Not deletable; worth knowing it is the largest non-domain cost per run. |
| E13 | `scripts/issue_gate.py`, `scripts/rengar_pen_breakpoints.py` (597) | Nothing executes `issue_gate` (a test asserts the filename exists); the Rengar script is test-only with no doc. | Purpose test each; cut or document. |
| E14 | `scripts/load_sanity.py` | Updated in 39d3794 for `checks.cache`; not run live (needs `DATABASE_URL`/`REDIS_URL`). | Run once against a deployed target. |

## F. Data and receipts

| # | Where | What | Action |
|---|---|---|---|
| F2 | `champions/source_receipts.py:66` | `static/cp10_batch_*_sources.json` glob: a stray file dropped into `static/` silently becomes runtime source of truth; batches 01/02 have no file and fall through to `reviewed-packets.json`. | Enumerate the files the registry expects. |
| F5 | `item_effects.py:2417` `everlasting_trigger_kind: "crowd_control"` | Not what the consumer keys on (it reads `CcClass` from the bus). | Delete the key. |

## G. Traps (informational — not fixes)

- Compiled slot order is Q,W,E,R,P while `REQUIRED_CHAMPION_SLOTS` is P,Q,W,E,R; the ledger replays insertion order for float sums, so any reorder is a numeric change.
- `interpreters._threshold_regeneration_thresholds` now stops the whole `uncompilable_item_receipt` call on one broken declaration (request-level, not per-item) — intended since 5055dc5.
- `sed -i` in Git-Bash strips CRLF; use byte-preserving scripts for bulk edits on this tree.
- Two Claude Code sessions in one worktree: a `git checkout -- <dir>` in one discards the other's uncommitted edits. Use a second worktree.
