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
354 champion options, 0 ask for a count of
something that happens INSIDE the modelled fight: how many procs landed,
how many ticks a channel took, how many attacks a pet made. Each of those
is a derivation the engine could do from the cast plan and the swing
schedule, the way Rumble's Heat now is
(`fight/rotation/cast_resource_lockout.py`), and each retired one removes
a way to get a wrong answer by leaving a default alone.

A further 15 default to the whole sourced thing —
a channel's every tick, a clip's every shot — so the option only removes
from a complete reading, and 24 derive their
default outright and take an override.
34 are facts no engine holds: state the champion
arrived with (stacks farmed over a game, souls collected) and facts about
the ENEMY or about where the champion stood (how many attacks an evasion
dodged, how many swings landed from behind). Asking for those is correct.
0 carry a label that says neither and need a reading.

| Bucket | Options | Who can answer |
|---|---|---|
| In-fight counts, still asked | 0 | the engine, once each is derived |
| In-fight counts, blocked on data | 2 | nobody, until the missing number is sourced |
| In-fight STACK LEVELS | 14 | the engine, once a stack timeline reaches the cast |
| In-fight counts, full by default | 15 | already complete; the option removes |
| In-fight counts, derived default | 24 | the engine; the option is an override |
| Pre-fight state | 34 | the player, permanently |
| Unreviewed | 0 | undecided; read the label |
| Not a count at all | 265 | the player: a variant, a target, a cone's reach |

That first row is at zero. Every count of something inside the
modelled fight is answered by the fight, and what remains below it
is either blocked on a number no source here states, or a fact the
engine has no standing to invent.

Stack LEVELS the fight builds and a cast reads. Deriving these means
walking a stack timeline into the cast pricing, not counting procs,
so they are the next campaign (`docs/surface-area-backlog.md` SR8)
and are reported apart from the row above rather than folded into it.

`[full]` defaults to the top of its range, so it prices the fully
stacked reading and over-counts a fight too short to reach it;
`[floor]` defaults to the bottom and under-counts a long one. Which
way each errs is the half a reader needs:

| Champion | Option | Asks for |
|---|---|---|
| Ashe | `q_focus_stacks` | Focus stacks (4 = Ranger's Focus ready) [full] |
| Ezreal | `passive_stacks` | Passive stacks (Rising Spell Force) [full] |
| Graves | `e_true_grit_stacks` | True Grit stacks [full] |
| Hecarim | `q_stacks` | Rampage stacks [full] |
| Irelia | `p_stacks` | Ionian Fervor stacks [full] |
| Jax | `p_stacks` | Relentless Assault stacks [full] |
| Jinx | `jinx_rev_up_stacks` | Pow-Pow Rev'd Up stacks [full] |
| Kassadin | `r_stacks` | Riftwalk stacks [floor] |
| Kindred | `w_hunters_vigor_stacks` | Hunter's Vigor stacks (100 = the next basic attack heals) [floor] |
| Kindred | `e_stacks` | Mounting Dread stacks (3 = pounce) [floor] |
| Samira | `p_style_stacks` | Style stacks (6 = S rank, R ready) [full] |
| Volibear | `relentless_storm_stacks` | The Relentless Storm stacks [floor] |
| Wukong | `stone_skin_stacks` | Strength of Stone stacks [floor] |
| Zaahen | `p_determination_stacks` | Determination stacks (12 = filled, which doubles the bonus) [floor] |

Counts the fight could walk if one missing number were sourced:

| Champion | Option | Missing |
|---|---|---|
| Heimerdinger | `q_turret_attacks` | the turret's attack speed, which is in no cached field and in no spell object this repo tracks |
| Kindred | `w_attacks` | Wolf's base attack rate; the cache states only that it scales with 25% of Kindred's bonus attack speed |

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
| `docs/surface-area-backlog.md` | 10 | everything the surface-area campaigns surfaced and did not close |
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
