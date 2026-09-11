# Coverage status

How much of the game the calculator models, measured on every axis at
once. Every number here is written by `scripts/coverage_status.py` from
the repo's own receipts and a live scan of the registered modules, and
`--check` is a gate, so this page cannot drift from the tree.

```bash
python scripts/coverage_status.py --check
```

## The short answer

| Axis | Covered | Of |
|---|---|---|
| Champion slots priced or stateful | 771 | 865 (89.1%) |
| Champion slots with nothing left to price | 88 | 865 (10.2%) |
| Champion slots the engine has no axis for | 6 | 865 (0.7%) |
| Runes compiled | 62 | every selectable rune |
| Keystones compiled | 62 | 62 |
| Items swept clean by the census | 169 | 209 |

A slot is `modeled` when it carries a priced row or a state row the engine
consumes, `no_damage` when it is emitted and has nothing left to price, and
`out_of_scope` when the engine has no axis for it at all and the module's
own docstring says so.

## Champions, slot by slot

173 named modules, which is every champion the cache
holds. Unknown names fail closed: there is no generic parser.

| Slot | modeled | no_damage | out_of_scope |
|---|---|---|---|
| P | 130 | 40 | 3 |
| Q | 172 | 1 | 0 |
| W | 151 | 21 | 1 |
| E | 158 | 15 | 0 |
| R | 160 | 11 | 2 |

The 6 slots with no engine axis at all:

| Champion | Slot |
|---|---|
| Sivir | R |
| Sylas | R |
| Teemo | P |
| Udyr | P |
| Viktor | P |
| Wukong | W |

## Depth: what the engine still asks the user

A calculator is only as deep as the questions it answers for itself, so
this is the number to steer by. Of
354 champion options, 45 ask for a count of
something that happens INSIDE the modelled fight: how many procs landed,
how many ticks a channel took, how many attacks a pet made. Each of those
is a derivation the engine could do from the cast plan and the swing
schedule, the way Rumble's Heat now is
(`fight/rotation/cast_resource_lockout.py`), and each retired one removes
a way to get a wrong answer by leaving a default alone.

A further 12 count state the champion arrived WITH —
stacks farmed over a game, souls collected, a mark already on the target.
No engine derives those and asking is correct.
32 carry a label that says neither and need a reading.

| Bucket | Options | Who can answer |
|---|---|---|
| In-fight counts | 45 | the engine, once each is derived |
| Pre-fight state | 12 | the player, permanently |
| Unreviewed | 32 | undecided; read the label |
| Not a count at all | 265 | the player: a variant, a target, a cone's reach |

The in-fight counts, which are the work:

| Champion | Option | Asks for |
|---|---|---|
| Akali | `passive_procs` | Passive procs |
| Akshan | `passive_procs` | Passive procs (3-stack) |
| Akshan | `e_shots` | E shots fired |
| Ambessa | `passive_procs` | Passive procs |
| Annie | `tibbers_attacks` | Tibbers auto attacks (0 = none; defaults to the fight window at the sourced enrage + 0.625 AS cadence) |
| Azir | `soldier_autos` | Replace basic attacks with Sand Soldier attacks |
| Bel'Veth | `q_casts` | Q casts (directional charges used) |
| Ekko | `p_procs` | Z-Drive Resonance detonations (3 stacks each) |
| Evelynn | `q_recasts` | Hate Spike recasts |
| Fiddlesticks | `w_ticks` | Bountiful Harvest ticks |
| Fiddlesticks | `r_ticks` | Crowstorm ticks |
| Fiora | `e_attacks` | Bladework attacks |
| Galio | `passive_procs` | Colossal Smash attacks available |
| Gangplank | `p_procs` | Trial by Fire procs |
| Gwen | `q_snippy_stacks` | Snippy stacks consumed by Q |
| Gwen | `r_casts` | Needlework casts |
| Hecarim | `w_ticks` | Spirit of Dread ticks |
| Heimerdinger | `q_turret_attacks` | Turret attacks |
| Hwei | `we_hits` | Stirring Lights hits |
| Ivern | `daisy_attacks` | Daisy attacks (5s window) |
| Jax | `e_dodged_attacks` | Counter Strike attacks dodged |
| Jhin | `r_shots` | Curtain Call bullets |
| Karthus | `e_ticks` | Defile damage ticks (one rotation) |
| Kindred | `w_attacks` | Wolf attacks (W) |
| Lillia | `p_ticks` | Dream Dust ticks |
| Locke | `q_casts` | Ritual Nails casts |
| Lux | `p_illumination_procs` | Illumination procs in the fight (each post-ability auto / Final Spark consumes one mark) |
| Malzahar | `voidling_attacks` | Attacks per Voidling (0 = none; defaults to the sourced attack-speed cadence over the fight window) |
| Milio | `p_procs` | Fired Up! hits landed |
| Miss Fortune | `p_procs` | Love Taps (attacks that tag a new enemy) |
| Rammus | `w_thorns_autos` | Enemy basic attacks during Defensive Ball Curl |
| Renata Glasc | `p_leverage_procs` | Leverage on-hit procs (unmarked first-hits; the mark lasts 6s and refreshes, so a 1v1 prices one per target) |
| Shaco | `p_procs` | Backstab attacks (basic attacks landing from behind) |
| Shaco | `w_box_attacks` | Jack in the Box attacks |
| Shaco | `r_clone_attacks` | R clone basic attacks commanded |
| Shen | `q_attacks_landed` | Q empowered attacks landed |
| Shyvana | `q_casts` | Emberstrike casts |
| Sylas | `passive_procs` | Unshackled attacks spent (each replaces one swing) |
| Talon | `passive_procs` | Blade's End 3-stack consumes |
| Udyr | `q_empowered_attacks` | Q empowered basic attacks |
| Wukong | `r_casts` | Cyclone casts |
| Yorick | `mist_walker_attacks` | Mist Walker attacks per walker (5s window) |
| Yorick | `maiden_attacks` | Maiden of the Mist attacks (5s window) |
| Ziggs | `passive_procs` | Short Fuse procs |
| Zyra | `plant_attacks` | Plant attacks per plant (5s window) |

Counting options whose label states neither reading:

| Champion | Option | Asks for |
|---|---|---|
| Ashe | `q_focus_stacks` | Focus stacks (4 = Ranger's Focus ready) |
| Aurelion Sol | `stardust_stacks` | Stardust stacks |
| Braum | `e_blocked_skillshots` | Skillshot slots to block; an empty list blocks all marked skillshots |
| Cho'Gath | `feast_stacks` | Feast stacks |
| Draven | `adoration_stacks` | Adoration stacks |
| Ezreal | `passive_stacks` | Passive stacks (Rising Spell Force) |
| Graves | `e_true_grit_stacks` | True Grit stacks |
| Gwen | `w_blocked_skillshots` | Skillshot slots to destroy; an empty list destroys all marked skillshots |
| Hecarim | `q_stacks` | Rampage stacks |
| Irelia | `p_stacks` | Ionian Fervor stacks |
| Jax | `p_stacks` | Relentless Assault stacks |
| Jinx | `jinx_rev_up_stacks` | Pow-Pow Rev'd Up stacks |
| Jinx | `jinx_get_excited_stacks` | Get Excited! champion stacks |
| Kalista | `rend_stacks` | Rend stacks |
| Kassadin | `r_stacks` | Riftwalk stacks |
| Kindred | `w_hunters_vigor_stacks` | Hunter's Vigor stacks (100 = the next basic attack heals) |
| Kindred | `e_stacks` | Mounting Dread stacks (3 = pounce) |
| Mel | `r_overwhelm_stacks` | Overwhelm stacks on the target when Golden Eclipse detonates |
| Pantheon | `e_blocked_skillshots` | Front-facing skillshot slots to block; an empty list blocks all marked skillshots |
| Samira | `p_style_stacks` | Style stacks (6 = S rank, R ready) |
| Samira | `w_blocked_skillshots` | Skillshot slots to destroy; an empty list destroys all marked skillshots |
| Senna | `senna_mist_stacks` | Mist (soul) stacks |
| Shyvana | `scalemail_stacks` | Scalemail stacks |
| Smolder | `p_stacks` | Dragon Practice stacks (225+ = tier-3 true-damage burn on Q) |
| Tristana | `e_stacks` | Explosive Charge stacks when it detonates (4 = max 100% increase, instant detonation) |
| Varus | `blight_stacks` | Blight stacks on the target when Piercing Arrow lands (3 = fully stacked; the Q detonation consumes them) |
| Volibear | `relentless_storm_stacks` | The Relentless Storm stacks |
| Wukong | `stone_skin_stacks` | Strength of Stone stacks |
| Xayah | `clean_cuts_stacks` | Clean Cuts stacks |
| Yasuo | `e_stacks` | Ride the Wind stacks |
| Yasuo | `w_blocked_skillshots` | Skillshot slots to block; an empty list blocks all marked skillshots |
| Zaahen | `p_determination_stacks` | Determination stacks (12 = filled, which doubles the bonus) |

## Items and runes

- **133 items** carry typed effect entries in
  `item_effects.ITEM_EFFECTS`. Every number comes from the cache through a
  typed accessor with no literal fallback, and a missing key raises.
- The census sweeps **209 items** against every registered
  champion. 0 pairs fail; 40 price
  coarsely, all of them one acknowledged mechanic
  (`docs/coverage-residue.json`, 10 rows).
- **62 runes** compile, including all
  62 keystones, with
  0 unmodeled. Only compiled runes are
  selectable; everything else fails closed.

## Where the remaining work is written down

Nothing unmodelled is silent. Each of these is a receipt with a reason per
row, and each has a gate that fails when a row appears without one.

| Receipt | Rows | What it holds |
|---|---|---|
| `docs/coverage-census.json` | 40 | champion and item pairs that price coarsely or refuse |
| `docs/coverage-residue.json` | 10 | frontier entries that cannot close without inventing data |
| `docs/surface-area-backlog.md` | 8 | everything the surface-area campaigns surfaced and did not close |
| `scripts/swing_stream_audit.py` | 9 | cached per-attack riders that do not publish a swing key |

## What 100% would mean, and what it would not

Slot coverage is close to total, so it is the wrong number to steer by.
The honest frontier is depth, and it has three parts:

1. **Counts the engine still asks for** — the table above. Each is a
   derivation the fight could do, and each retired one removes a way for a
   reader to get a wrong answer by leaving a default alone.
2. **Axes the engine does not have** — a summon that fights on its own, a
   stat conversion with no channel, a persistent object with a field cap.
   These need new engine shapes, not more packets.
3. **Approximations that are stated rather than exact** — a fight-averaged
   attack-speed share, a resistance bound once per ability row, a charge
   stock capped at one where no cached field states the real cap. Each is
   named where it is made.
