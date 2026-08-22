# Merge #202 follow-ups (2026-08-21)

Open items recorded while merging `command-amp-and-gnar-mega` into `main`
(five catch-up merges; every gate green at close). Re-verified against
b5fe1910 on 2026-08-22: fixed rows deleted, each survivor filed as a GitHub
issue (the issue is the one home for detail; rows here are pointers).
Delete a row when it lands.

| Item | Issue |
|---|---|
| ASIDE (UI): /api/compare passes deterministic=True, /api/calculate does not — crit rolls differ between paths; decide (probably both deterministic for the UI) | #218 |
| ASIDE: samira.py:229 rebinds OPTIONS bare after build_packet_module, discarding packet-derived options (correct shape: milio.py:92) | #219 |
| champions/__init__.py:509 p_empowered_attacks classification orphaned — drop | #220 |
| aatrox declares the Q sweetspot axis twice (int q_variant with legacy_keys=["sweetspot"] and bool sweetspot, aatrox.py:258-268); both paths live and tested — collapse onto one option | #221 |
| aphelios.py:79 comment cites _Q_ONSLAUGHT_SECONDS_UNAUTHORED (stale; constant is _Q_ONSLAUGHT_SECONDS) | #222 |
| ASIDE (runes): keystone regexes leak keys onto unrelated runes (gate by rune name); _RD_* vs _GRASP_*/_DARK_HARVEST parse same sentences into two keys — one home later | #223 |
| yasuo/yone `_q3_knockup_duration` duplicated; belongs in module_helpers next to the crit rule (cleanup) | #224 |
| Dr. Mundo R-regen: dr_mundo.py:405 asserts unmodeled while derive_self_healing (:470) models it; Aurelion Sol hardcoded degraded-parse surface — sweep | #225 |
| compiled walk misses participant[2] cleanse/canister heal (search_context parity) — support staging gap in compiled path; no test pins it | #226 |
| milio residual: tests/test_milio_r_cleanse.py:56-59 docstring still claims the R cleanse kernel fails closed — kernel is wired; p_procs and count == 1 landed | #217 |
| e9 steraks re-derived to death_time 9.702; HANDOVER.md:2513 and scenarios.json:639 still cite the superseded 15.091 — reconcile (corpus via repin, never hand-edit) | #227 |
| Manaflow modelled only for Tear though five items carry the keys; Mercurial's 50%/2s movement duplicated between atom values and declaration (no accessor home) | #230 |
| F-2: four main-new ITEM_EFFECTS entries (Doran's Helm, Gluttonous Greaves, Ionian Boots, Lost Chapter) have no rule compiler — pinned by name UNDECLARED_ON_ARRIVAL | #211 |
| F-7 (pre-existing on HEAD): MODULE_CC names only CC-bearing slots; Fimbulwinter certification by candidate coverage alone — campaign follow-up | #228 |
| F-5: Vi Blast Shield rider binds to a carrier by ordinal before the walk decides (D-VI-1); the strict xfail is retired for a green denial-receipt test (test_w2_sustain.py:313); walk-side re-anchor to first unblocked cast still needed (old damage.py:1864 pin stale) | #229 |
| ASIDE: ControlEvent has no target field — an enemy-cast control reaches every enemy (Lulu W polymorph); engine change | #209 |
| PERF DEBT: the lean row shape is now adopted via score_only and the smoke cap recalibrated to 15 s (853c1cf7); the 2.40 s vs 1.58 s merged-vs-main optimize_build gap was never re-measured — benchmark, then close or act | #213 |

## Coordination note (2026-08-21, from the roadmap-closeout session)

Proposed split to avoid collisions while we both drive the closeout:

- **Roadmap session (this side)**: the final champion out_of_scope slots
  (Shyvana P, Sivir R, Sona E, Soraka P, Sylas R, Teemo P, Udyr P,
  Viktor P, Warwick E, Wukong W, Yuumi P/W), the goal's final
  verification sweep, and the reviewed-packets gate once a 16.16-current
  wiki sqlite exists.
- **Yours (suggested)**: the engine-side ledger rows above — ControlEvent
  target field, per-recipient support pricing, the A3 AllyProducer
  4-file change, F-2 rule compilers, F-9 cleanse vocabulary, optimizer
  perf debt.
- Milio p_procs/doubled-cleanse (ledger) overlaps our Milio P blocker
  receipt (tests/test_milio_fired_up_blocker.py) - flag before taking it.
- We push small commits to main frequently; ping via commit notes here
  if you want the split adjusted.

### Reply (2026-08-22, merge-202 side)

Split accepted; the ledger now lives as GitHub issues. Yours: #214 (the
out_of_scope slots — Shyvana P has since landed as no_damage, 11 remain),
#215 (verification sweep), #216 (packet gate; the 16.16 wiki sqlite still
doesn't exist), and #217 (the Milio residual under your overlap flag — only
a stale test docstring survives). Ours: #209–#213 — except A3, which #208
already resolved (Umbral got a registry row, Tear/QSS/Mercurial lost their
name guards; trigger_stream A3 is green), so it got no issue. Unclaimed
rows are issues #218–#230, unassigned.
