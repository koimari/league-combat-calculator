# Zero-residue ledger

One line per iteration of the zero-leftover-mechanics campaign, appended
never rewritten. Each line is the four DONE probes measured on the tree at
that moment, so a later reader can see which way each number moved and what
moved it.

The probes, in order:

1. `out_of_scope` champion slots, from every registered module's own contract
   (`get_champion_module_contract(name).coverage`).
2. Runes implemented over runes total, from `rune_catalog()`.
3. `docs/coverage-residue.json` rows, split by reason, beside whether
   `scripts/coverage_census.py check` is green.
4. Research gaps from the archetype ground-up results, closed or receipted.

| when | slots out_of_scope | runes | residue rows | census | note |
|---|---|---|---|---|---|
| 2026-09-16T20:55Z | 5 (Sylas R, Teemo P, Udyr P, Viktor P, Wukong W) | 62/62 | 10 (9 unsourced, 1 certification_shape) | stale | baseline. The goal's snapshot said 5 slots naming Sivir R, 31/62 runes and 24 residue rows with 3 certification_shape: Sivir R closed earlier, the runes are all compiled, and Aatrox Q/W and Darius R are already out of the residue, so only Yone E remains of the three. Census reads stale because the Yone fix is in the tree and not yet captured. |
| 2026-09-16T21:20Z | 5 (unchanged) | 62/62 | 9 (9 unsourced, 0 certification_shape) | green | certification_shape is at ZERO. Yone E closed with no new data, which is what that reason always meant: its stored-damage events are built by the fight engine from a rule the module declares, so they carry no parts for a reviewed kind to ride, and the builder now stamps the owning entry's own reviewed state onto each one. Fail-closed both ways, driven over the builder with one flag flipped. Coarse census pairs 40 to 36, items swept clean 169 to 173, both goldens identical because a certification marker is not a number. |
| 2026-09-16T22:05Z | 5 (unchanged) | 62/62 implemented; priced 38 to 39, refused 24 to 23 | 9 (unchanged) | green | `implemented` was already 62/62, so the real probe-2 reading is the priced-against-refused split, and the frontier doc's "31 priced" is stale by 8. Built the shared axis: `RuneStat.ARMOR` and `MAGIC_RESIST`, which the closed stat set had no members for, so a resistance could not be a rune stat at all. Conditioning prices on it. Its numbers were in prose only and its cached `effects` read `{}`, so the rune parser learned the `'''bonus''' armor` shape and the reparse filled Conditioning and Unflinching and nothing else. A correction the measurement forced: holder resistances do NOT reduce the holder's own damage taken, because effective health is health, shields and healing with no resistance term, and a pure-armor Chain Vest moves no number there. What they do buy is kit scaling, measured at Malphite +11.4, Rammus +9.6, K'Sante +6.5, Braum +0.0 over ten seconds. The rune discloses both halves and its 3% of TOTAL resists stays withheld for want of a percent-of-total channel. |
