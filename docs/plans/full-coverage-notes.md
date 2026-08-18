# Full-coverage campaign — recon pointers

Working notes for the campaign in `2026-08-18-full-coverage-campaign.md`. File:line
references from the 2026-08-18 recon; verify before relying on exact lines.

## Certification machinery

- One classifier: `damage._event_timeline_coverage` (damage.py:1760-1871). Exact = authored
  `damage_events` whose `damage` sums to the row's `total_damage` (rel 1e-9/abs 1e-6), no
  event marked `event_precision: "cast_boundary"`. Cast-order rows with `casts > 0` pass
  unless `dot_duration > 0`. Rows with no events are coarse.
- Module-authored ledgers: literal `damage_events` on the parser entry, re-priced at
  damage.py:4919-4934 (exemplars: lux.py:85, diana.py:144, braum.py:199, twitch.py:94).
- `event_order_certified: "single_hit" | "auto_stack_proc"` on a parser entry certifies
  item proc precision (`_item_proc_precision`, damage.py:8596-8625); `auto_stack_proc`
  additionally clamps procs to real swings (damage.py:4754-4763, 4936-4943). Exemplar:
  akshan.py:288-320. Whitelisted keys: champions/engine.py:106-107.
- Stack counters: `stacks_required` (+ `count_ability_hits` to merge ability hits into the
  auto stream — damage.py:6414-6461). Exemplars: vayne.py:59-90, aurora.py:52-79.
- Timeline-walk modules read reserved options `auto_attack_uptime` /
  `fight_duration_seconds` (champions/inputs.py:191-202, injected pipeline.py:1062-1072);
  exemplar braum.py:96-205 (returns None in one-rotation, degrades instead of withholding).

## Coarse-row producers to close (engine side)

- `auto_attacks` under AS-modifying kits: swing schedule cleared when
  `len(swing_times) != num_auto_attacks` (damage.py:6310-6311); 26 champions affected with
  on-hit items (Blitzcrank, Briar, Camille, Cho'Gath, Darius, Dr. Mundo, Draven, Ekko,
  Fiora, Fizz, Garen, Gragas, Gwen, Hecarim, Illaoi, Jax, Jayce, Kassadin, Kayle, Kled,
  Leona, Nasus, Shen, Shyvana, Vayne, Wukong).
- `on_hit_items_Q/W/E/R` ability-attack on-hit rows (14+ champs: Aphelios, Bel'Veth,
  Briar, Ezreal, Fiora, Fizz, Gangplank, Irelia, Senna, Smolder, Viego, Warwick, Yunara,
  Zaahen), `on_hit_ability_*`, `on_hit_items_phantom` (damage.py:6292-6297),
  `double_on_hit_Dusk and Dawn`, `damage_amp_Horizon Focus` (damage.py:10342-10406 shape),
  `on_hit_Guinsoo's Rageblade`, `on_hit_Kraken Slayer`, `on_hit_Hullbreaker`,
  `spellblade_Dusk and Dawn(_true)`, `expose_weakness_Bloodsong` (damage.py:10396).
- Item proc precision pairs: Eclipse (16) / Muramana (17) on Dr. Mundo, Jayce, Kalista,
  Kayle, Malphite, Qiyana, Sejuani, Shen, Shyvana, Smolder, Tahm Kench, Talon, Twitch,
  Varus, Vel'Koz, Viego, Ziggs — their cast rows lack certification.
- Kits: Fizz W (DoT row, no ticks), Shen Q (`requires_auto_timeline_coupling`,
  shen.py:156; synthetic cadence at damage.py:4996-5013). Ambessa declares the same flag
  (ambessa.py:177) but her census run was clean — verify her coupled row fires and certify.
- `fimbulwinter_everlasting`: control token via `_control_armed_event_coverage`
  (damage.py:1900-1945, injected 11344-11353) — any damaging ability event without
  reviewed `cc_kind` (`cc_kind`/`cc_reviewed`, damage.py:3311-3318). 169 champions.
- `target_Protoplasm Harness`: injected damage.py:11354-11368 via
  `threshold_defense.threshold_health_coverage_source` when the Lifeline heals; no
  authored tick cadence. Expiry refusal: `ThresholdExpiryWithheld`
  (interpreters/threshold_defense.py:127-139, raised damage.py:1995-1996).
- Escape hatch that must not widen: `EXPLICIT_APPLICABILITY_EXCLUSION_SOURCES`
  (timeline_coverage.py:12-19).

## Withhold surfaces (all must stay, populations emptied)

- Mode: pipeline.py:964-981 + roster_composition.py:34-51; module constants only
  (vi.py:271-283, kaisa.py:238-252, karthus.py:159-172, taliyah.py:176-188).
- Certified target timeline: item_coverage.py:853-880. Coverage classes:
  item_coverage.py:74-115. Keystones: rune_effects.py:439-459 (4 compiled), refused list =
  `data_updater.KEYSTONE_NAMES` minus compiled.
- BIS 500: `UnrankableNumber` is TypeError by design (program/views/__init__.py:81-118);
  app.py handlers at 1255/1289/1324/1387 catch only ValueError/LookupError/KeyError.
- Optimizer silent `-inf`: optimizer.py:371-377, 492-493 (no withheld_builds row).

## Four champions (blockers, from module docstrings)

- Vi: W stacks from autos+Q+E with 4 s expiry, repeat procs, E reset on real stream
  (vi.py:66-131, 161-217). Pattern: aurora + braum-style windows.
- Kai'Sa: Plasma persistence between rotations, Supercharge AS window (engine buffed-rate
  scheduler exists: damage.py:5470-5479), on-attack cooldown refunds, R reset
  (kaisa.py:87-211).
- Karthus: Defile persistent toggle + mana exhaustion, Lay Waste cadence, Death Defied
  post-death window (karthus.py:19-133, 209-255).
- Taliyah: Worked Ground persistence changing later Q damage/cost/cooldown, volley overlap,
  repeated E windows (taliyah.py:16-158).
- Tests pinning the restrictions: test_event_order_certification.py:186-313, 445-454;
  test_vi.py:207-283; test_kaisa.py:255-288; test_karthus.py:98-107; test_taliyah.py:125-132;
  test_app.py:485-538, 2133-2148.

## Flagged, out of contract (next campaign's frontier)

Self-healing rules absent for ~116 of 173 champions (healing_legacy.py:294-356); grey
health only 5; compiled-walk refusals for 16 items (docs/behavior-frontier.json);
`optimizer_supported_items` publishes only aggregate counts; custom cast orders
unsupported everywhere by design (capabilities.py:254-262).
