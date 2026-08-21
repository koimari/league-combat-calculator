# Golden recapture — roadmap session 4 batch E, 2026-08-21

Champions: Neeko, Nocturne, Nunu & Willump, Ornn, Pantheon (one
`out_of_scope` slot each, per docs/roadmap-100.md's "1 slot" row, session
7/8 groupings). Pre-recapture compare: 0 diffs.

Root cause, all five: same stale-label pattern as roadmap session 4 batch D
(receipt slots9.md) — MODULE_COVERAGE reported a slot as `out_of_scope`
that was already sourced as `no_damage` by the pinned reviewed packet
(`static/reviewed-packets.json`, per-champion `slots[<slot>].kind ==
"no_damage"` with an explicit reason string), and in four of the five
cases the slot was already an active cast slot in the module (via
`build_packet_module`'s `no_damage` branch, unmodified by the named
module), already emitting the packet's sourced zero-damage row before
this batch. The fight computation never changed for those four; only the
documentation/`MODULE_COVERAGE` label did.

Per-champion slot:

- Neeko: P (Inherent Glamour) -> no_damage. Cast slot unmodified from
  `build_packet_module` output (module overrides only Q/E/R); packet
  declares P `kind: "no_damage"`.
- Nocturne: W (Shroud of Darkness) -> no_damage. Cast slot unmodified
  from `build_packet_module` output (module overrides E-tether behavior
  and P/on-hit specs, not W); packet declares W `kind: "no_damage"`.
- Nunu & Willump: P (Call of the Freljord) -> no_damage. Cast slot
  unmodified from `build_packet_module` output (module overrides only
  Q); packet declares P `kind: "no_damage"`. The module docstring's
  prior "P ... is documented out_of_scope" was itself the stale label.
- Ornn: P (Living Forge) -> no_damage. **Differs from the other four**:
  Ornn's module is fully custom (does not call `build_packet_module` at
  all), and its `SLOTS` dict was authored directly with only Q/W/E/R —
  P was never wired as a cast slot at all. This matches the Malzahar
  precedent from batch D exactly: a non-cast P slot corrected from
  `out_of_scope` to `no_damage` on sourced evidence alone (the pinned
  packet's `kind: "no_damage"` declaration for P, corroborating the
  module's pre-existing ASSUMPTIONS line that Living Forge is an
  item/state system with no direct enemy damage). Documentation-only;
  P remains absent from `SLOTS`.
- Pantheon: P (Mortal Will) -> no_damage. Cast slot unmodified from
  `build_packet_module` output (module overrides Q/W/R, not P); packet
  declares P `kind: "no_damage"`. The module docstring already stated
  "P (Mortal Will) remains a documented no-damage row" in prose — the
  `MODULE_COVERAGE` dict itself had not been updated to match.

Numeric movement: NONE. Zero diffs pre- and post-recapture; the only file
delta from `golden_snapshot.py capture` is the metadata `git_head` commit
hash field, not any champion/item damage row.

Per-champion dispositions live in each module's docstring + ASSUMPTIONS
with sourced evidence (the `static/reviewed-packets.json` per-slot `kind`
and `reason` fields); per-champion test counts in
`/tmp/session4e-progress.txt`.

Recapture executed after this attribution; compare re-verified identical.
