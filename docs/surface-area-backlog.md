# Surface-area backlog

What the surface-area campaign (`docs/plans/2026-08-20-surface-area-campaign.md`) surfaced
and its backlog sweep did not close. Delete a row when its fix lands; this file is the one
home for the list. Traps live in `CLAUDE.md` Known Quirks.

| # | Where | What | Action |
|---|---|---|---|
| D3 | ~40 custom parsers (`akshan.py:257`, `darius.py:215`, …) | `entry["event_order_certified"] = "single_hit"` hand-assigned — the fact, not a wrapper; fine, but `single_hit_slots` now exists for packet rows. | Opportunistic. |
| E14 | `scripts/load_sanity.py` | Updated in 39d3794 for `checks.cache`; not run live (needs `DATABASE_URL`/`REDIS_URL`). | Run once against a deployed target. |
| E12 | `tests/coverage_resolver.py` (1.8k) + `test_coverage_claims.py` (2.7k, subprocess pytest at `:654`) + `coverage_evidence.py` (1.1k) | 5.6k lines proving evidence strings name real symbols, run through `conftest.py` on every `pytest -k`; the largest non-domain cost per run. | Not deletable; speed it up only with a measured benchmark. |
| C10 | `static/js/app.js` `VARIANT_BOOLEAN_OPTIONS` / `wikiFallbackAbility` | Variant buttons flatten *forms* and *packets* onto one index, but a form toggle and a packet toggle are different axes, so one index per option cannot serve both. Live: Gnar's Q flattens to Boomerang / Boomerang-reduced / Boulder Toss, and `mega: 1` makes the reduced Mini packet read as Mega while Boulder Toss (the real Mega Q) sends `mega: false` — W/E meanwhile render Mega. | Stamp each flattened variant with its source form, and read form toggles from the form rather than the flat index. |
| F1 | `item_effects.ALLY_ITEM_EFFECTS["Imperial Mandate"]["control_ability_haste"]` | Mandate's *Control* passive ("abilities with immobilizing effects have their cooldown reduced equivalent to 20 ability haste") is sourced and cached, the key is declared in `ALLY_ENTRY_SHAPES`, and nothing reads it: `grep control_ability_haste src/` finds only the registry and the shape. The item's own stat block carries 15 AH; the conditional 20 is a second, per-ability figure `get_item_stats` correctly does not fold in. It shortens a real rotation in a `time_based` window, so it is damage-relevant. | Needs a per-ability haste axis in the cooldown path (`damage.py` / `pipeline.py`), keyed off the slot's reviewed `MODULE_CC` immobilize marker — the same marker Command already gates on. |
