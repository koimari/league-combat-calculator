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
section/effect expectations, the per-effect verdict, and the runtime coverage
reason for each manual-attacker, enemy-target, ally-roster, optimizer, API,
and frontend path. A clean unit test without this full-entry receipt does not
authorize promotion or issue closure.

Generated champion packet modules are deliberately not certification evidence.
They may remain importable so the backend can return a deterministic,
fail-closed explanation, but `/api/champions` must expose them as
`generated_packet` and unavailable for reviewed champion options until an exact
module has passed this requirement. The current baseline is 237 ordinary
items audited, 53 exact champion modules, and 120 generated champion packets;
the release gate remains open until the latter 120 are replaced by exact
modules or an explicitly sourced, tested out-of-scope classification.

For every item effect, the receipt must retain the full parent-page evidence
even when the runtime currently withholds the branch. A branch may not be
collapsed into a single item-level “supported” flag: its passive/active name,
all described branches, cooldown/range metadata, typed runtime verdict,
issue references, and path coverage must remain inspectable. The same rule
applies to each champion P/Q/W/E/R slot, including utility-only slots and
alternate forms.

This requirement is also a patch-day and implementation gate. A patch refresh
must run the repository's `$patch-update` workflow before any new value is
promoted. A new or changed item effect must follow `$add-item-effect`: capture
the complete parent page first, keep numeric values in typed item accessors,
and add focused ordered-event tests for every accepted branch. A parser
refresh, Riot tooltip, or isolated module excerpt never substitutes for the
full-page review receipt.
