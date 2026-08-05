# Full Wiki-entry review requirement

Every item and champion that can appear in the calculator must be reviewed
against its complete League Wiki parent entry before a mechanic is called
modeled.

For an item, the review covers the entire page: current stats, every passive,
every active, all branches and notes, target restrictions, range and area
rules, cooldowns, transformations, progression/economy state, map/mode
availability, and relevant patch-history changes. A single passive excerpt or
the Riot tooltip is not sufficient. Each effect is either represented through
typed accessors and an ordered event receipt, or is named as explicitly
blocked/out of scope with a user-visible reason.

For a champion, the review covers the complete parent page and every passive,
Q, W, E, and R entry, including ranks, costs, cooldowns, targeting, variants,
recasts, forms, stack/charge state, secondary targets, and utility-only
branches. Each slot must have a revision-backed module receipt, a tested
implementation or an explicit no-damage/unsupported classification.

The release gate is `scripts/full_entry_audit.py`. It must report every
in-scope entry as `ready`, with no `review_pending` records and no missing
champion slots. The audit receipt records the page revision, content hashes,
section/effect expectations, and the runtime coverage reason. A clean unit
test without this full-entry receipt does not authorize promotion or issue
closure.
