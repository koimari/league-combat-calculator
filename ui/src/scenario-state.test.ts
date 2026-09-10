import test from "node:test";
import assert from "node:assert/strict";
import {
  newParticipant,
  reduceRanksForLevel,
  serializeParticipant,
  compactSlotIndex,
  reindexSupportTargets,
} from "./scenario-state.ts";

test("new participants carry explicit zero ranks into the engine", () => {
  const actor = newParticipant("main");
  actor.champion = "Lulu";
  actor.level = 18;
  assert.deepEqual(serializeParticipant(actor).ability_ranks, {
    Q: 0,
    W: 0,
    E: 0,
    R: 0,
  });
});
test("a level change cannot allocate points, and lowering trims excess", () => {
  const ranks = { Q: 3, W: 1, E: 1, R: 1 };
  assert.deepEqual(reduceRanksForLevel(ranks, 18), ranks);
  const reduced = reduceRanksForLevel(ranks, 2);
  assert.deepEqual(reduced, { Q: 1, W: 1, E: 0, R: 0 });
  assert.deepEqual(ranks, { Q: 3, W: 1, E: 1, R: 1 });
});
test("per-slot search replaces the selected filled slot after inventory holes", () => {
  const items = [null, "A", null, "B", null, null];
  assert.equal(compactSlotIndex(items, 3), 1);
  assert.equal(compactSlotIndex(items, 0), 2);
});
test("participant serialization keeps only equipped option state", () => {
  const actor = newParticipant("ally-one");
  actor.build.items[2] = "A";
  actor.build.item_options = { A: { stacks: 3 }, B: { stacks: 9 } };
  assert.deepEqual(serializeParticipant(actor).item_options, {
    A: { stacks: 3 },
  });
});

test("roster removal preserves recipient identity and clears a removed recipient", () => {
  const main = newParticipant("main"),
    a = newParticipant("a"),
    b = newParticipant("b");
  main.champion = "Lulu";
  a.champion = "Ashe";
  b.champion = "Garen";
  main.supportTargets = { E: 1, W: 0 };
  const next = reindexSupportTargets([main, a, b], [main, b]);
  assert.deepEqual(next[0].supportTargets, { E: 0 });
});
