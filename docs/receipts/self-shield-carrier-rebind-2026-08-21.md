# D-VI-1 — a self-shield rider cannot re-bind when its carrier is skipped

**Status:** open, receipted fail-closed. Not fixed in this session.
**Found:** 2026-08-21, via `tests/test_w2_sustain.py::TestViBlastShield`.
**Owner surface:** `survival/` walk + `participant_timeline` rider build.
**Named receipt:** `self_shield_carrier_skipped`, published in
`combat.item_denial_receipts`.

## 1. The wrong number

Level-18 Vi, no items, vs. a level-18 Ahri with ranked abilities, 10s
time-based fight (`tests/test_w2_sustain.py::_fight("Vi")`):

| figure | published before this session | truth |
| --- | ---: | --- |
| `survival.shield_absorbed` (main) | `0.0` | Blast Shield should have been granted |
| Blast Shield `applied_amount` | `0.0` (`trigger_event_skipped`) | 292.8 granted, then absorbing |

Vi's kit lands 5 ability packets in that fight. She is shielded by none of
them, and the payload says so with a skip reason that reads as a *game
fact*. It is not one — it is a modelling artifact.

## 2. Root cause

Blast Shield has no cast and no damage, so it reaches the ledger as a
**rider**: `slotlib.attach_self_shield` hangs a one-element
`self_shield_events` list on an ability entry, and
`damage._damage_event_row` copies it onto that entry's damage events
**aligned by ordinal**:

```python
shield = fields.get("self_shield")
if shield is None and shield_events is not None and ordinal <= len(shield_events):
    shield = shield_events[ordinal - 1]
```

So the rider is nailed to **event ordinal 1 of one chosen slot**, at
*authoring* time. `participant_timeline` then turns that packet's
`self_shield` into a support event whose `_trigger_event_id` is that exact
packet.

Which packets actually **land** is decided much later, inside the ordered
survival walk, and it depends on live state the author could not have had:
`survival/transitions.py` gates a packet on
`states[action.attacker]["crowd_control_until"] > event_time`
(`attacker_state_blocked`), on `target_dead`, on `outside_window`, on the
redirect gate, and on spell shields — all of which evolve *during* the
walk.

In this fight Ahri's charm lands at 0.0. Vi's Q packet at 1.721 is therefore
published `attacker_state_blocked`, and the walk's trigger gate then refuses
the rider on the carrier's behalf:

```python
if (not guardian_reactive and (action.trigger >= 0 or action.trigger_slot != NO_SLOT)) \
        and not ledger.trigger_applied(action):
    ledger.skip(action, "trigger_event_skipped", ...)
```

**That gate is correct** and must stay: an effect whose trigger packet never
landed must not survive on its own. The defect is one layer up — the rider
has exactly one carrier and no way to move to another. Vi's E lands at
3.221 and her Q lands again at 8.971; in game either grants Blast Shield.
The model grants nothing, because the only carrier it knows about is the
packet that was blocked.

Restated as an invariant the code violates:

> A rider whose trigger condition is "the next ability hit" must bind to the
> first ability packet that **lands**, which is only knowable during the
> walk. It currently binds to the first ability packet that was
> **authored**, which is knowable before the walk and is not the same thing.

## 3. Why this was not fixed here (size assessment)

The fix is a re-bind capability in the rider/trigger kernel, not a champion
edit. Concretely it needs, at minimum:

1. A rider to arrive at the walk with an **ordered candidate carrier list**
   rather than a single `_trigger_event_id` — a new field on
   `survival/actions.py::SurvivalAction` (and its packed row indices).
2. The walk to hold a refused rider **pending** and arm it at the first
   later carrier that passes every gate, instead of `continue`-ing at the
   trigger gate in `survival/transitions.py`.
3. The same behaviour in **all three ledger implementations** that must
   agree packet-for-packet — `outcome_state.py`, `score_state.py`,
   `receipt_state.py` (each has its own `skip` / `trigger_applied`).
4. Re-ranked ordering: the rider currently declares
   `TransitionRank.LATE_BARRIER` relative to *its* timestamp. Arming at a
   different timestamp moves it inside the snapshot machinery that
   precomputes `ctx.shield_presence_at_time` per snapshot, and past
   `shield_ledger.expire_timed`.
5. `survival/compile.py` representability: the compiled score kernel already
   declines `self_shield_payload` and falls back to the walk, so the
   compiled path needs re-deciding, not merely re-checking.
6. Each rider's **own** re-bind rule. "The next ability hit" (Vi's Blast
   Shield) is not "on damaging a champion" (Eclipse's Ever Rising Moon) is
   not a per-cast rider. There are 20 champion modules calling
   `attach_self_shield` plus the Eclipse item family; a blanket re-bind
   would invent trigger conditions for all of them.

Item 6 is the one that makes this genuinely large rather than merely broad:
the kernel cannot re-bind correctly until each rider states the condition it
re-binds on, which is a per-module sourcing pass on top of the kernel work.
That is a dedicated slice, not a sweep item.

## 4. What was done instead

The zero is no longer published as a fact. `participant_timeline`
`_self_shield_carrier_denials` audits the two resolved ledgers after the
walk and emits a named denial into the existing public
`combat.item_denial_receipts` section — the channel whose own contract is
"a denial is a receipt with no applied amount, published as its own section
rather than as a zero packet a reader would have to interpret"
(`program/views/receipt.py`).

```json
{
  "time": 1.721,
  "kind": "item_denial",
  "source": "Blast Shield",
  "reason": "self_shield_carrier_skipped",
  "attacker": "main",
  "target": "main",
  "event_id": "main:enemy:Ahri:2:shield",
  "carrier_event_id": "main:enemy:Ahri:2",
  "carrier_skipped_reason": "attacker_state_blocked",
  "rebind_time": 3.221,
  "withheld_amount": 292.8
}
```

The audit fires only when all three of these hold, so it never invents a
denial:

1. The rider was refused as `trigger_event_skipped` — the one skip reason
   that means "the packet I was nailed to did not land". A rider refused on
   its own terms is left alone.
2. That carrier packet is genuinely skipped in the published ledger
   (cross-checked, not re-read off the stamp).
3. The holder landed at least one **ability** packet at or after the
   carrier's timestamp. This is the half that makes the zero wrong. A
   holder who landed nothing after the skip was never going to be shielded,
   and gets no receipt.

`withheld_amount` is the figure the model declined to apply, so a consumer
can see the size of the gap rather than only its existence.

### Deliberate limits of the receipt

- It is a **detector, not a fix**. `shield_absorbed` still reads `0.0`;
  the receipt is what stops that zero being read as the game's answer.
- It detects the *carrier-skipped* shape only. A rider whose carrier is
  never authored at all (a slot ranked 0, an ability the rotation never
  casts) is a different question and is not in scope here.
- It reports at most one row per rider — the rider is refused once.

## 5. Closing this defect

The fix must move **both** halves at once, and the pin asserts both:

- `tests/test_w2_sustain.py::TestViBlastShield::test_a_charmed_carrier_withholds_the_shield_with_a_named_receipt`
  pins `shield_absorbed == 0.0` **and** the exact denial row. A fix flips
  the absorbed figure and drops the receipt; a half-fix that moves only one
  of the two fails this test, which is the point of pinning both.
- `...::test_the_granted_shield_absorbs_something_when_its_carrier_lands` is
  the control: an unimpeded carrier already pays the shield and emits no
  denial today, and must keep doing so.

Golden note: the denial section is additive. It adds leaves to the golden
snapshot for exactly those fights that already published a stranded rider;
it moves no damage, healing, or survival number.
