# Surface-area resolution campaign — results

Branch `surface-area-resolution`. Two waves of isolated-worktree workers plus one
consolidation pass; every backlog row acted on. Residuals and new findings live in
`docs/surface-area-backlog.md` (the one home); traps went to `CLAUDE.md` Known Quirks.

| Row | Outcome |
|---|---|
| E14 | Run live locally (self-provisions; "needs deployed target" premise was wrong). Surfaced and fixed a `db.cache_set` select-then-insert race that 500'd winning responses; deterministic concurrency test pins it. `load_sanity` now PASSes, 0 failures. |
| E12, ER7 | Closed: measured no-win and intact-sentinel notes; the tests themselves encode them. |
| SD9 | All five number-bearing tags retired; flat readers + `magic_damage_amp` compiler; parity green per commit; claims layer re-pointed at the catalog. |
| SC1/SC2/SC11 | Jayce Q rides the form axis; refusal pass runs at render() end (complete, exemptions pinned); gating ruled contract coverage in code. |
| SC3 | Sivir W prices the Bounce Damage row (40.8 → 51.0), per bounce. |
| SC4 | `applies_item_on_hits` moved to `infernum`; W's cooldown (0.8 s) and swap (0.25 s) separated. |
| SC5/SC6/SC7/SC10 | Dead bool dropped (both kits); crit vocabulary declared on three kits (Xin Zhao W ruled a deterministic amplifier, no new key); Scalemail wired fail-loud; Ornn W stamped. |
| SC8 | Redirect parents publish the packet the walk applied (one object). |
| SC9 | One pre-combat composition (`stats.resolve_pre_combat_stats`), five surfaces, AST-pinned; pure refactor. |
| SC12 | Udyr E, Naafiri W, Seraphine W wired; Singed R re-keyed onto the fold (uncapped MS had reached Swiftmarch); Sivir P + Singed P → CF11 (cache gaps). |
| SC13 | Premise wrong (casts already scheduled); the real gap — receipt view dropping `cc_magnitude` — fixed and pinned. |
| ER2 | Aatrox Q/W re-timed with corpus+oracle re-pins; Annie/Kennen stack walks; Annie E priced; Vex R split; Jayce R rides `rides_scheduled_auto` (a missing forced swing surfaced and fixed); Aphelios weapons priced 4/5. |
| ER5 | Lint package-wide; 256/307 modules pinned; 576 sites converted, six dead literals removed; 51-module tail declared in `TAIL`. |
| CF17 | `overheat_windows` heat axis; AS half and lockout priced together from cache; the 100-Heat prose corrected to the cached 150. |
| CF11 | Unchanged by ruling (patch-day parser fixes); grew the campaign's cache-gap findings. |

New rows SR1–SR6 record what the campaign surfaced but did not rule.
