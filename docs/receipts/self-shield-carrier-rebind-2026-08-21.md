# A self-shield rider binds to the first ability packet that lands

**Status:** closed (issue #229). Landed 2026-09-02.
**Owner surface:** `survival/transitions.py` walk, `participant_timeline`
rider build, `champions/slotlib.attach_self_shield`.

## The rule

A self-shield with no cast and no damage of its own reaches the ledger as a
**rider**: `slotlib.attach_self_shield` hangs a one-element
`self_shield_events` list on an ability entry and `damage._damage_event_row`
copies it onto that entry's damage events **aligned by ordinal**. So the
payload is nailed to one carrier packet at *authoring* time.

Which packets actually **land** is decided much later, inside the ordered
survival walk, from state the author could not have had: the attacker's
crowd control, the target's death, the fight window, the redirect gate,
spell shields. The rider's trigger is "the holder's next ability hit", so
the binding has to move with them.

It does. `attach_self_shield` stamps `rebind_on_ability_hit` on the payload,
`participant_timeline` carries it onto the rider as `_rebind_on_ability_hit`,
and `program.compile.action_from_event` reads it into
`SurvivalAction.rebinds_on_ability_hit`. When the walk's trigger gate would
refuse such a rider, `transitions.run_survival_walk` parks it in
`ctx.pending_self_shields` instead, and `_rebind_self_shields` arms it on the
next ability packet the holder lands, at that packet's timestamp. The moved
action keeps its ledger slot and its event dict, so the rider moves rather
than being granted twice.

Vi at level 18 against a ranked Ahri, 10 s: the charm at 0.0 blocks the Q at
1.721 the payload was hung on, Vi's E lands at 3.221, and Blast Shield is
granted there for 292.8 over 3 s, absorbing 228.4 before it expires at 6.221.

## What declares the re-bind, and what does not

Every champion module authors through `attach_self_shield`, so all seventeen
callers re-bind (Akshan, Ambessa, Blitzcrank, Camille, Malphite, Neeko,
Rakan, Renata Glasc, Senna, Sett, Shen, Shyvana, Skarner, Vex, Vi, Viktor,
Volibear). Eclipse's Ever Rising Moon builds its own payload in `damage.py`
and states no re-bind: it arms on the certified proc event it rides, and a
blocked proc is a shield the fight did not earn.

## When nothing can carry it

`participant_timeline._self_shield_carrier_denials` names a rider that was
refused `trigger_event_skipped` while its holder authored in-window ability
packets and landed none. The row is published in `combat.item_denial_receipts`
and names the authored carrier, the last candidate the rider could have taken,
and the amount withheld. A rider refused on its own terms, and a holder who
authored no candidate, get no row.

## Scope, measured

The fix needed no candidate-carrier list on `SurvivalAction`, no change in the
three ledger implementations, and no compiled-path decision. `survival/compile.py`
already declines any event carrying a `self_shield` with `self_shield_payload`,
so score mode never holds one of these riders, and the walk reschedules through
the same sorted insertion the ledgers' `schedule_heal` already used.
