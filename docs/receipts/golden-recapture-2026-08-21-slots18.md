# Golden recapture — final-slots batch part 1 (Alistar R), 2026-08-21

Alistar R (Unbreakable Will) implemented via the PR-202 damage_modifier
self_state_events seam (Briar E precedent) — the old "no incoming-damage-
reduction hook" receipt is obsolete. Sourced: 55/65/75% reduction (wiki
row, per-rank % units), 7.0s active duration (timing atom), cooldown
120/100/80. Rank-2 golden row pins multiplier 0.35 over 7s. Fail-closed
guards: every unit entry must be percent; missing atoms raise.

Compare: 19 diffs = 17 Alistar structural rows (the new zero-damage R
entry across baseline + fight scenarios) + 2 metadata fingerprint
counters (leaves 58443->58497, numeric 44829->44857; recorded in
campaign-fingerprints.json). Zero damage-total movement.

Recapture executed after this attribution; compare re-verified identical.
