# Surface-area backlog

What the surface-area campaign (`docs/plans/2026-08-20-surface-area-campaign.md`) surfaced
but did not fix: asides from the eleven unit reports and the blind audit, de-duplicated and
re-verified against the tree at `0fa19e6`. Ordered by the cost paid today. Delete a row
when its fix lands; this file is the one home for the list.

## B. Fallbacks and single-home violations still standing

| # | Where | What | Action |
|---|---|---|---|

## C. API / UI

| # | Where | What | Action |
|---|---|---|---|

## D. Champion package

| # | Where | What | Action |
|---|---|---|---|
| D3 | ~40 custom parsers (`akshan.py:257`, `darius.py:215`, …) | `entry["event_order_certified"] = "single_hit"` hand-assigned — the fact, not a wrapper; fine, but `single_hit_slots` now exists for packet rows. | Opportunistic. |
| D11 | `survival/compile.py:69-70` `requires_holder_health_ratio` | Can no longer fire — Knight's Vow's packet also carries `redirect_fraction`, which refuses first. | Delete or reorder deliberately. |

## E. Tests and gates

| # | Where | What | Action |
|---|---|---|---|
| E12 | `tests/coverage_resolver.py` (1.8k) + `test_coverage_claims.py` (2.7k, subprocess pytest at `:654`) + `coverage_evidence.py` (1.1k) | 5.6k lines proving evidence strings name real symbols, run through `conftest.py` on every `pytest -k`. | Not deletable; worth knowing it is the largest non-domain cost per run. |
| E14 | `scripts/load_sanity.py` | Updated in 39d3794 for `checks.cache`; not run live (needs `DATABASE_URL`/`REDIS_URL`). | Run once against a deployed target. |

## F. Data and receipts

| # | Where | What | Action |
|---|---|---|---|

## G. Traps (informational — not fixes)

- Compiled slot order is Q,W,E,R,P while `REQUIRED_CHAMPION_SLOTS` is P,Q,W,E,R; the ledger replays insertion order for float sums, so any reorder is a numeric change.
- `interpreters._threshold_regeneration_thresholds` now stops the whole `uncompilable_item_receipt` call on one broken declaration (request-level, not per-item) — intended since 5055dc5.
- `sed -i` in Git-Bash strips CRLF; use byte-preserving scripts for bulk edits on this tree.
- Two Claude Code sessions in one worktree: a `git checkout -- <dir>` in one discards the other's uncommitted edits. Use a second worktree.
