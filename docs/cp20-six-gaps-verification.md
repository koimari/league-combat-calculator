# CP20 Six-Gap Item Verification on `820acbc3`

Tier: **local commit** · Branch: `codex/handover-processing` · Base SHA: `820acbc3`

The six named CP20 gaps (`docs/cp20-remaining-item-gaps.json`) are implemented
on the current production SHA with typed values and tests:

| Item | Claimed branches | Verified on `820acbc3` |
|---|---|---|
| **Cull** | Reap on-hit healing; 100-minion progression; 350 gold completion | `item_effects.py`: `reap_max_gold=100.0`, `reap_completion_gold=350.0`, `reap_gold_per_minion=1.0`, progression + completion receipts (lines ~1295–1309); coverage reasons in `item_coverage.py`; tests in 7 files |
| **Phage** | Rage melee/ranged MS; 2 s duration | `item_effects.py`: `rage_bonus_move_speed_melee=20.0`, `rage_bonus_move_speed_ranged=10.0`, `rage_duration=2.0`; `item_coverage.py` ("Rage is emitted once per authored basic attack with the sourced melee or ranged value"); tests in `test_item_coverage.py`, `test_item_support_effects.py` |
| **Runic Compass** | 800-gold Support Quest; Shared Riches; Ward active | `item_effects.py`: `support_quest_threshold=800.0`, `shared_riches_interval=20.0`, `shared_riches_gold_*`, `ward_charges=3.0`; quest logic at line 1330; `role_quests.py` stage `intermediate`; tests in `test_role_quests.py`, `test_item_coverage.py` |
| **Tear of the Goddess** | Manaflow timing; 3/6 bonus-mana triggers; 360 cap; minion-only Helping Hand | `item_effects.py`: `manaflow_bonus_mana.max=360.0` (×4 Tear-family), `helping_hand_minion_damage=5.0`; `passive_parser.py` `_parse_manaflow` (charge/transform state); coverage: "Manaflow's bounded bonus-mana progression and minion-only Helping Hand"; tests in `test_item_effects.py`, `test_item_coverage.py` |
| **Umbral Glaive** | Blackout vision state; 1 s unseen gate; 4 s trigger window; 50 + 1.5 lethality true damage | `item_effects.py`: `lethality_ratio=1.5` ("Melee: 50 + 1.5 per lethality, Ranged: 25 + 0.75 per lethality"); `damage.py`: Blackout unseen gate is an explicit scenario input; `item_source.py` handles the Blackout split; coverage: vision dimension; tests in `test_item_damage.py`, `test_item_effects.py`, `test_item_coverage.py` |
| **World Atlas** | 400-gold Support Quest; Shared Riches; Ward active | `item_effects.py`: `support_quest_threshold=400.0`, `shared_riches_*`, `ward_charges=3.0`; quest logic at line 1330; `role_quests.py` stage `starter`; tests in `test_item_support_effects.py`, `test_item_effects.py`, `test_app.py`, `test_item_coverage.py` |

Conclusion: the six CP20 item gaps are closed in code on `820acbc3` (zero
`review_pending`, zero blocked in the umbrella audit). What remains for #40 is
the documented preview/production receipt tier, not implementation.
