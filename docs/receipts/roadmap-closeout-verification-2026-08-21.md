# Roadmap closeout — final verification sweep (issue #215)

Audited at `main` after the #214 slot dispositions, the two CI parallel-worker
race fixes, and the coworker's merged PR #231 (engine follow-ups #209–#213).
Every number below is computed live by the command shown, not carried forward
from an earlier receipt.

## 1. Champions — 173/173 registered, 865 slots

```python
from src.calculator import champions as ch
for n in sorted(ch.registered_champion_names()):
    ch.get_champion_module_meta(n)["coverage"]   # {slot: disposition}
```

| Disposition | Slots | Share |
|---|---:|---:|
| `modeled` | 771 | 89.1% |
| `no_damage` (sourced zero row) | 88 | 10.2% |
| `out_of_scope` (receipted) | 6 | 0.7% |
| **Total** | **865** | 100% |

**Every one of the 6 open slots carries a named blocker in its module's
`ASSUMPTIONS`** — zero unreceipted opens, which is the pass bar:

| Slot | Blocker (verified this sweep) |
|---|---|
| Sivir R | MS decomposition + cooldown-refund channel absent; `HuntAttackSpeed` wiki/bin conflict |
| Sylas R | No cross-champion instantiation surface anywhere in the kernel; the AD→AP conversion has no channel to rewrite a foreign ability's scaling. Viego P and Mordekaiser R are withheld for the same reason |
| Teemo P | Timed-AS window is `q_window_*` state end to end (`damage.py:783-787`, consumed `7876-7896`); every producer is a Q slot. No passive can reach it |
| Udyr P | Same `q_window_*` blocker |
| Viktor P | Augments live as `effects[2+]` inside the base entries; transform axis the engine does not have |
| Wukong W | No sourced clone attack rate in cache or bin, and pricing it needs a second attacker's timeline |

Each was re-derived from primary sources during #214 rather than inherited —
three of them (Alistar R, Warwick E, Ornn P) were *retired* as blockers in the
same pass once PR #202's `damage_modifier` seam obsoleted them, so the six
that remain are the ones that survived re-examination.

## 2. Items — 209 SR-admitted, zero blocked

```python
[i for i in fetch_item_data().values() if is_ordinary_sr_item(i)]
tests.item_probe.attacker_coverage(item)["status"]
```

| Status | Count |
|---|---:|
| `modeled_effect` | 58 |
| `modeled_state` | 61 |
| `stats_only` (certified) | 90 |
| `blocked` | **0** |
| **Total** | **209** |

The `blocked` bucket is now empty — Fimbulwinter's untyped mana gate, the last
entry, cleared. The 90 `stats_only` items are certified by
`tests/test_stats_only_items.py` (321 parametrized cases): each is verified
SR-admitted, optimizer- and calculation-eligible, stat-delta-checked against
`calculate_total_stats`, and the 41 carrying described passives have their
cached branch text pinned byte-for-byte so a patch cannot silently attach a
damage clause to a certified item.

## 3. Runes — 63 rows + 3 shards

| Measure | Count |
|---|---:|
| Rows in `data/runes.json` (excl. shards) | 63 |
| Rows with parsed effects | 45 |
| Compiled entries in `RUNE_EFFECTS` | 62 |
| Receipt-only kinds | 3 |
| Shards | 3 |

Only compiled runes are selectable; everything else fails closed through the
`rune_effects` convention (CLAUDE.md rule 5).

## 4. Atoms — 19,855 across 6 domains, manifest verified

Each domain's manifest `sha256` re-computed with
`atomizer.hash_domain_file(...)` and compared:

| Domain | Objects | Atoms | Hash matches |
|---|---:|---:|---|
| items | 324 | 1,667 | yes |
| abilities | 173 | 5,094 | yes |
| runes | 17 | 127 | yes |
| economics | 323 | 817 | yes |
| stats | 173 | 6,779 | yes |
| champions | 173 | 5,371 | yes |
| **Total** | | **19,855** | **6/6** |

Domain hashing is content-stable (`generated_at` excluded), so this equality
survives any regeneration — the fix that ended the per-patch hash treadmill.

## 5. Gates

| Gate | Result |
|---|---|
| `golden_snapshot.py compare` | `OK: snapshot identical` |
| `coverage_census.py check` | exit 0 |
| coupled-golden allowlist | every standing diff claimed by a committed receipt |
| literal-defaults (rule 5) | green both directions — no new fallbacks, no stale frozen rows |
| ci_evidence_parity | green (18 evidence-path references, all tracked or guarded) |
| rotation f2/f3 | green |
| gate cluster combined | 239 passed |
| full suite | **15,147 passed, 0 failed, 0 xfailed** |
| CI on `main` | 7/7 jobs green incl. 4 coverage-census shards |

## 6. Remaining ledger — known, tracked, not failures

- **6 receipted champion slots** (§1) — each blocked on a named kernel axis or
  an absent source, not on effort.
- **#216 reviewed-packets gate** — needs a 16.16-current wiki revision sqlite;
  the local copy predates the patch. External input, not a code defect.
- **Coworker's open engine issues** (#217–#236) — ControlScope broadcast,
  QSS-during-stasis, restricted-channel adjudication, Manaflow/Mercurial
  accessor homes, and assorted cleanups. Owned on the engine side per the
  split recorded in `docs/plans/2026-08-21-merge-202-followups.md`.

## Verdict

Every champion slot, SR item, rune row and atom domain is either **modeled**,
**sourced-zero (`no_damage`)**, **certified (`stats_only`)**, or **fail-closed
behind a named receipt naming its blocker**. Nothing is unaccounted for, and
nothing is priced on an invented number.
