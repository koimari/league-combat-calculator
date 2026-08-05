# CP20 Item Umbrella Review (handover processing, 5 Aug 2026)

Status: **REVIEWED — code already promoted; evidence still required.**

## 1. Verdict

The standalone CP20 commit `0147d5a` (`/private/tmp/cp20-issue40`, branch
`codex/cp20-item-umbrella-final`) is **superseded**. Its content has already
landed on `main` through the CP20 merge line:

| Commit | Merge | What |
|---|---|---|
| `a4ee5f9` | PR #102 | CP20: audit every item across runtime coverage paths |
| `bec9df1` | PR #103 | CP20 upgraded-boot stats follow-up |
| `efcfdce` | PR #114 | CP20 support-item ledger reconciliation |
| `4cf08e8` | — | CP20: reconcile remaining item coverage gaps |

`4cf08e8`'s diff is exactly the handover's "15-file parent-to-commit diff"
(`docs/cp20-remaining-item-gaps.json`, `docs/item-umbrella-audit.json`,
`docs/wiki-full-entry-audit.json`, `src/calculator/damage.py`,
`item_coverage.py`, `item_effects.py`, `item_support_effects.py`,
`participant_timeline.py`, `static/js/app.js`, and six test files;
971 insertions, 380 deletions).

**Do not merge `0147d5a` as-is.** Its tree predates CP10 champion modules and
CP19's utility fix; a normal merge would regress `main` (the worktree has no
merge base with `origin/main`; history is grafted/shallow).

## 2. Test evidence (Python 3.14, pytest 9.1.1, uv-managed env)

| Tree | SHA | Result |
|---|---|---|
| `main` (clean worktree) | `820acbc3` | **3199 passed** |
| CP20 standalone tree | `0147d5a` | 3042 passed |

The 157-test delta is entirely tests present on `main` and absent from CP20's
older base: `tests/test_cp10_batch_01..11.py` (champion modules) and
`tests/test_frontend_level_controls_contract.py` (CP11). No CP20-side test
fails against its own tree.

## 3. Item-count universe reconciliation (issue #40)

Three count systems exist; they describe different universes:

| System | Universe | Counts |
|---|---|---|
| `docs/item-umbrella-audit.json` (on main `820acbc3`) | ordinary source items, per-item attacker/target coverage | 209 items; attacker: 80 `modeled_effect` + 30 `modeled_state` + 99 `stats_only`; target: 171 `not_target_relevant` + 29 `modeled` + 9 `modeled_event_certified`; **0 blocked, 0 review_pending**; 202 manual/runtime; 130 optimizer-eligible |
| `docs/cp20-remaining-item-gaps.json` (on main) | CP20 audit subset | 209 ordinary / 202 manual / 130 optimizer; 0 pending/blocked/mismatch/conflict; status `local_implementation_ready_preview_pending` |
| issue #40 body snapshot | selectable items (older) | 188 selectable; 66 `modeled_effect`; 5 `modeled_state`; 87 `stats_only`; 30 attacker-blocked; 17 target-blocked |

The #40 snapshot predates the CP20 merges (30 attacker blocks → 0; totals
shift as coverage completed). **Every future receipt must state its universe
and filter rules** (source items vs selectable vs runtime vs optimizer, boots
included/excluded) before counts are compared.

Global zero-block and scenario-specific withholding can coexist: production
BIS still withholds Bastionbreaker/Muramana (before timeline) and
Fimbulwinter (partial) in the Utility scenario while the global map reports
zero blocked — per-scenario event-order certification is a separate axis from
per-item coverage.

## 4. Remaining work for #40

1. Fresh receipts on the current production SHA (`820acbc3`) — the umbrella
   audit and gap list are already present in the tree; regenerate/verify and
   capture the source manifest hash.
2. Preview deployment of a `codex/` branch built on `820acbc3`, then
   production evidence.
3. Reconcile the item-count definitions in the #40 issue body (universe +
   filter rules per receipt).
4. Keep the per-scenario withholding explanations (Bastionbreaker, Muramana,
   Fimbulwinter) as audit rows with Apply disabled.
