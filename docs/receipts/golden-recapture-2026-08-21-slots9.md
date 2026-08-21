# Golden recapture — roadmap session 4 batch D, 2026-08-21

Champions: Malzahar, Master Yi, Morgana, Nami, Nasus (one out_of_scope
slot each, per docs/roadmap-100.md's "1 slot" row). Pre-recapture compare:
0 diffs.

Root cause, all five: MODULE_COVERAGE was stale, still reporting a slot as
"out_of_scope" that was already implemented as a cast slot emitting the
pinned packet's sourced zero-damage row (no enemy-damage formula in the
Wiki packet, `kind: "no_damage"` in static/reviewed-packets.json or the
equivalent SLOTS entry for Nasus's custom engine module). Unlike roadmap
session 4 batch C (where the reclassified slot was NOT previously in
SLOTS/casting, so a new baseline row appeared), every slot here was
already casting and already emitting its zero-damage row before this
batch — the fight computation never changed, only the documentation/
MODULE_COVERAGE label did.

Per-champion slot:
- Malzahar: P (Void Shift) -> no_damage
- Master Yi: R (Highlander) -> no_damage
- Morgana: P (Soul Siphon) -> no_damage
- Nami: P (Surging Tides) -> no_damage
- Nasus: W (Wither) -> no_damage (P, Q, E, R were already "modeled")

Numeric movement: NONE. Zero diffs pre- and post-recapture; the only file
delta from `golden_snapshot.py capture` is the metadata `git_head` commit
hash field, not any champion/item damage row.

Per-champion dispositions live in each module's docstring + ASSUMPTIONS
with sourced evidence; per-champion test counts in
/tmp/session4d-progress.txt.

Recapture executed after this attribution; compare re-verified identical.
