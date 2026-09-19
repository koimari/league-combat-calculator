# Stats-only certification

`tests/test_stats_only_items.py` is the one home for the SR-admitted
`stats_only` population. It computes the set live from
`item_coverage.item_model_coverage()` behind `item_source.is_ordinary_sr_item()`,
so the count is never written down anywhere else.

Live coverage on every other axis is in `docs/coverage-status.md`.
