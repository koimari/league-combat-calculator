import test from "node:test";
import assert from "node:assert/strict";
import { increaseSkillRank, unspentSkillPoints } from "./hud-ranks.ts";
test("a saved allocation keeps a new level point available", () => {
  const ranks = { Q: 1, W: 0, E: 0, R: 0 };
  assert.equal(unspentSkillPoints(2, ranks), 1);
  assert.deepEqual(increaseSkillRank(2, ranks, "W", 1), {
    Q: 1,
    W: 1,
    E: 0,
    R: 0,
  });
  assert.equal(ranks.W, 0);
});
test("level cap and used points block unavailable upgrades", () => {
  assert.equal(increaseSkillRank(5, { Q: 0, W: 0, E: 0, R: 0 }, "R", 0), null);
  assert.equal(increaseSkillRank(1, { Q: 1, W: 0, E: 0, R: 0 }, "W", 1), null);
  assert.equal(increaseSkillRank(3, { Q: 2, W: 0, E: 0, R: 0 }, "Q", 2), null);
});
test("quest levels do not add skill points beyond the authored eighteen", () => {
  assert.equal(unspentSkillPoints(20, { Q: 5, W: 5, E: 5, R: 3 }), 0);
  assert.equal(increaseSkillRank(20, { Q: 5, W: 5, E: 5, R: 3 }, "R", 4), null);
});
