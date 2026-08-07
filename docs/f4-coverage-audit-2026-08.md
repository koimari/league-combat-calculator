# F4 Rotation Coverage Audit — 2026-08-06

## Scope and evidence

This is the current-head disposition of every numbered F3 rotation gap in
`docs/rotation-verification-gaps.md`. The alpha, beta, and gamma F4 reports
reviewed all **19 rows**, covering **29 champion entries**; the three batch
assignments cover the complete local roster (`58 + 58 + 57 = 173`) with no
unassigned champion. The project-venv checks covered the 173-entry registry,
all-champion F3 invariants, and the F4 semantic regression suite.

| F3 row | Champion entry/entries | Current disposition |
|---:|---|---|
| 1 | Tristana | Fixed: typed `self_setup` E charge; E opens the cast order. |
| 2 | Caitlyn | Certified with limitation: trap/Headshot is passive damage state, not a cast-slot edge. |
| 3 | Kennen | Certified with limitation: Mark of the Storm is passive/auto-driven; W prose detonation remains documented. |
| 4 | Volibear | Certified with limitation: Wounded is a self-consumed, order-neutral mark. |
| 5 | Viego | Certified with limitation: Q mark is consumed by the auto stream, not a cast slot. |
| 6 | Naafiri | Certified with limitation: Q bleed/recast is self-slot state; no cross-slot edge is claimed. |
| 7 | Nidalee | Corrected at current head: selected-row matching prevents Takedown's missing-health attributes from leaking into default Javelin Toss; default order is Q → W → E → R. Form/trap state remains documented. |
| 8 | Illaoi | Certified with limitation: spirit/vessel state is outside a typed cast-slot relationship. |
| 9 | Yasuo | Certified with limitation: Q3 and E stacks are self-generated state; Q3 is not a separate slot. |
| 10 | Gnar | Certified with limitation: Mega/Mini is form state and R is unavailable in Mini form. |
| 11 | Jayce, Kai'Sa, Karthus, Shen, Taliyah, Vi | Certified module orders reproduced; Jayce's unused phantom Q2 remains a documented metadata nit. |
| 12 | Hwei | Corrected at current head: execute metadata is scoped to the selected QW/Severing Bolt row and variant-aware rule caching; default QQ is Q → W → E → R, QW is R → Q → W → E. |
| 13 | Seraphine | Certified: E → R → Q → W with E→Q and R→Q missing-health edges; dedicated regression pin added. |
| 14 | Renekton, Rumble | Renekton's fury-gated enhancement remains a limitation; Rumble's base E MR shred is fixed and yields E → Q → W → R. |
| 15 | Darius | Fixed: non-damaging E no longer becomes a passive stack applier; no false E→R stack edge. |
| 16 | Briar | Certified: Q shred opens and W missing-health execute closes. |
| 17 | Brand | Certified with documented seed override; Blaze detonation is passive-driven, with a cosmetic seed-label limitation. |
| 18 | Xin Zhao, Varus | Certified module coverage; Varus's R→Q seed exception is pinned, Xin's challenged prose remains outside typed edges. |
| 19 | Nautilus, Lulu, Malphite, Poppy | Certified module coverage with honest flat orders and sourced atoms. |

## Current-head semantic safeguards

- `rotation_resolver.py` now selects the parsed source row before evaluating
  attribute/prose consumers, preventing inactive form variants from creating
  false execute, mark, or stored-damage edges.
- Hwei's `q_missing_health` option is gated to the QW/Severing Bolt packet.
- Hwei derived-order caching includes the selected packet name, so QQ and QW
  cannot reuse each other's order.
- Regression coverage includes Zed, Yone, Karma, Tristana, Darius, Nasus,
  Rumble, Swain, Anivia, Draven, Veigar, Seraphine, default Hwei/Nidalee
  variant leakage, and active Hwei QW behavior.

## Roster verification

- `data/champions.json`: 173 champions.
- Reviewed modules: 173 ready, 0 blocked.
- `tests/test_champion_coverage.py` and `tests/test_f3_rotation_all.py`
  iterate and validate the complete 173-champion roster.
- Remaining documented limitations are intentionally not represented as fake
  damage or invented cast edges; they require a separately sourced atom or
  explicit module override before being promoted.
