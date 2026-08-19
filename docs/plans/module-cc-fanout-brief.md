# MODULE_CC fan-out — batch brief

Shared brief for the wave-4B batches. Read with
`docs/plans/2026-08-18-full-coverage-campaign.md` (Decision 6, Banned shortcuts) and
`CLAUDE.md`. Your batch message names your champions; nothing else is yours.

## Why

`damage._control_armed_event_coverage` marks a whole timed fight coarse
(`fimbulwinter_everlasting`) when a build carries Fimbulwinter and any damaging
*ability* event lacks a reviewed crowd-control kind. 172 champion×Fimbulwinter pairs
are the largest remaining coverage family. A kit clears the scan only when **every**
ability event it emits is reviewed — partial review flips nothing.

## The contract (wave 4A, commit 78d9b0b)

- `MODULE_CC = {"Q": "stun", ...}` at module level, wired into the module's parser:
  `build_parser(SLOTS, "<Name>", cc_kinds=MODULE_CC)`, or
  `build_packet_module(..., cc_kinds=MODULE_CC)`. Declaring it without wiring raises.
- Validated by `champions/module_contract.py`: keys ⊆ the module's own `SLOTS`,
  values ∈ `ability_spec.CC_KIND_VOCABULARY` (the immobilize kinds ∪ `slow`, `none`).
- **Absent slot = unreviewed. `"none"` = reviewed, applies no control.** Different
  answers; never write `"none"` to silence a slot you did not read.
- `engine._apply_module_cc` stamps the kind on every part the slot emits, including
  parts rebuilt after `damage_entry`. A part with its own explicit kind keeps it; a
  *different* kind raises.
- A declared kind must reach the event ledger (`engine._validate_cc_event_contract`),
  `"none"` included. A slot whose parts never emit events fails at import — that is
  the check working, not an obstacle to route around.

## Declaring is free (wave 4A-2, commit 566b393)

Earlier batches found that declaring a kind reordered the rotation and moved
damage, and some suppressed true facts to avoid it. That is fixed: no
module-sourced `cc_kind` orders anything, whether declared per slot or authored
per part. Ordering comes only from declared `CAST_DEPENDENCIES`. **Declare what
the text says and never trade a fact for a quiet gate** — if a declaration moves
a number now, that is a finding to report, not a reason to drop it.

`"cripple"` and `"silence"` are in the vocabulary (commit 96457fa) for control
that is neither an immobilize nor a movement slow.

## What each champion needs

1. Read the cached ability text for every slot (`data/champions.json`, the champion's
   `abilities`), and decide the kind **from that text**. Cite nothing you did not read.
   Multi-effect abilities: the kind is what the ability applies to the *target it
   damages*. A slow is `"slow"`; a knock-up/aside is `"knockup"`/`"knockback"`; a
   root/stun/charm/taunt/fear/suppression each have their own kind.
2. Declare `MODULE_CC` for every slot the module emits, and wire it.
3. Probe: `calculate_payload({"champion": N, "level": 18, "items": ["Fimbulwinter"],
   "fight_mode": "timed", "include_auto_attacks": True})` must report
   `timeline_coverage.complete` true with `fimbulwinter_everlasting` absent.
4. If a slot cannot reach the ledger, that champion stays coarse. **Do not force it.**
   Report the champion, the slot, and why (no authored timing, aggregated multi-hit
   row, etc.). Cheap, honest fixes are in scope — Corki's pilot needed `single_hit`
   certification on one slot and one-part-per-missile on another, both of which the
   ledger already agreed with. Re-pricing a mechanic is not in scope.

## Evidence per champion

One test per champion in its `tests/test_<name>.py` (create following an existing
champion test's shape): the Fimbulwinter probe above, plus an assertion that the
declared kinds match the cached text — a champion your review calls cc-free gets a
test scanning its whole cached kit for control vocabulary.

## Banned

Stamping `"none"` to clear the scan; declaring a kind a slot's text does not support;
weakening `_validate_cc_event_contract`, `_control_armed_event_coverage`, or the
classifier; editing `damage.py`, `trigger_stream.py`, `engine.py`, `slotlib.py`,
`packet_module.py`, `module_contract.py`, `rotation_resolver.py` (wave 4A owns the
mechanism — report a needed change instead).

## Gates

`pytest` on every test file you touched plus `tests/test_champion_module_contract.py`,
`tests/test_event_order_certification.py`, `tests/test_f3_rotation_all.py`;
`black src/ tests/`; `pylint` on touched modules no worse than before.
`python scripts/golden_snapshot.py compare scripts/golden_baseline.json`: `cc_kind`
prints in `DamagePart`'s repr, so stamped parts show repr-only diffs — enumerate them
and confirm **zero numeric diffs**. Never re-capture the baseline. Do not commit.

Report: per champion one line (kinds declared → probe result), the list that stayed
coarse with the blocking slot named, golden diff classification, gate output.
