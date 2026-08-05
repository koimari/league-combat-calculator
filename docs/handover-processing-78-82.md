# #78 Capability Contract + #82 Boot/Support Verification (local commit evidence)

Branch: `codex/handover-processing` · Base SHA: `820acbc3` · Tier: **local commit**

## #78 — backend capability contract (implemented + round-trip tested)

`src/calculator/capabilities.py` publishes `public_capability_contract(...)`; `/api/config`
exposes it as `capabilities` with `schema_version`, `scope`, `participant_ledger`,
`participants.{main,enemy,ally}.fields`, `scenario.fields`, `scenario.limits`, and `catalogs`.

Per-kind fields (each: supported + reason + payload_field + state_path + frontend_token):
- all kinds: `champion`, `level`, `role`, `role_quest_complete`, `boots`, `include_boots`,
  `items`, `item_options`, `ability_ranks`, `champion_options`, `cast_order`
  (cast_order explicitly unsupported with reason — backend derives authored order)
- main-only: `ability_casts`, `ability_hits`, `ability_variants` (conditional),
  `keystone`, `ally_effects_enabled` (unsupported with reason)
- ally-only: `ally_effects_enabled` (supported); enemy/ally casts/hits/variants
  explicitly unsupported with reasons
- scenario: `rotations`, `window`, `auto_attack_uptime`, `auto_attack_uptime_mode`

Frontend consumes the contract (`capabilityFor`, `scenarioCapabilityFor`,
`capabilityAttributes`, `data-capability-field`, disabled+title+aria-disabled on
unsupported) across role/quest/boots/items/ranks/options/level/keystone/ally-effects
and scenario controls.

Round-trip tests (all pass on this SHA):
- `test_capability_contract_has_a_frontend_control_and_serialization_for_every_supported_field`
  (iterates every participant + scenario field: unsupported ⇒ reason; supported ⇒
  frontend_token present in app.js/templates, payload_field in source)
- `test_participant_controls_share_the_same_target_policy_receipt`
- `test_frontend_level_controls_contract.py` (2 tests)
- 42 capability/contract/frontend/config tests pass in `test_app.py` subset

`/api/champions` remains authoritative: `champion_engine` exposes
registered/reviewed/generated counts (173/173/0 on this SHA) + module contract.

## #82 — role-quest boot upgrades + support progression (implemented + tested)

- `src/calculator/role_quests.py`: `BOOT_UPGRADES` (all 7 tier-2→tier-3 pairs),
  `SUPPORT_QUEST_ITEM_STAGES` (starter/intermediate/upgraded for all 5 support items),
  `support_quest_item_contract()`, `boot_upgrade_contract()`.
- `src/calculator/loadout_rules.py`: `required_boots_tier` (mid+quest ⇒ 3),
  `inventory_capacity` (bottom+quest ⇒ 7), support-stage gating (one upgraded
  support item only after completion; non-support roles rejected).
- Typed stats / passives for upgraded items: `passive_parser.py` (Bloodsong
  spellblade + Expose Weakness, Zaz'Zak's Realmspike proc, Swiftmarch
  adaptive-force conversion), `item_source.py` (Crimson Lucidity, Gunmetal
  Greaves), `item_coverage.py` (Immortal Path, Celestial Opposition, Dream
  Maker, Solstice Sleigh, Swiftmarch, Gunmetal Greaves coverage reasons),
  `participant_timeline.py` (Celestial Opposition mitigation, Immortal Path
  below-half healing multiplier, Dream Maker flat reduction).
- Upgraded-boot stats eligible: PR #103 (`bec9df1`); support-quest transition
  normalization merged `8d6abe4` (PR #106; branch `codex/cp82-support-quest-parity`
  head `7589400` is an ancestor of `main`).

Tests passing on this SHA: `test_role_quests.py` (6: tier-2 pair coverage, quest
stages, level caps), `test_item_support_effects.py` (14: typed progression
receipts, support quest items, ally targeting), `test_support_effects.py` (14) —
34 total.

## Still required (production tier, blocked on session)

- #78: preview + production browser checks that rendered controls match payload
  behavior (data-capability-field audit against live page).
- #82: preview + production QA across all 7 boot pairs + 5 upgraded support
  items with no misleading partial result.
