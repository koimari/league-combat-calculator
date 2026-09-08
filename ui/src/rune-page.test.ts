import test from "node:test";
import assert from "node:assert/strict";
import type { Build, Rune } from "./types.ts";
import {
  choosePrimaryRune,
  chooseSecondaryRune,
  changePrimaryPath,
  changeSecondaryPath,
  chooseStatShard,
  inferRunePaths,
} from "./rune-state.ts";
const rune = (
  name: string,
  path: string,
  row: number,
  implemented = true,
): Rune => ({ name, path, row, implemented, options: [] });
const runes = [
  rune("Key", "Precision", 0),
  rune("P1", "Precision", 1),
  rune("P1b", "Precision", 1),
  rune("P2", "Precision", 2),
  rune("S1", "Sorcery", 1),
  rune("S1b", "Sorcery", 1),
  rune("S2", "Sorcery", 2),
  rune("S3", "Sorcery", 3),
  rune("Off", "Sorcery", 3, false),
];
const config = { runes, keystones: [runes[0]] };
const build = (): Build => ({
  items: [],
  boots: "",
  keystone: "Key",
  keystone_options: {},
  minor_runes: ["P1", "P2", "S1", "S2"],
  rune_options: { P1: { stacks: 2 }, S1: { enabled: true } },
  item_options: {},
  stat_shards: [],
});
test("primary row replacement preserves every other row", () => {
  const change = choosePrimaryRune(config, build(), runes[2], "Precision");
  assert.deepEqual(change.minor_runes, ["P2", "S1", "S2", "P1b"]);
  assert.equal(change.rune_options?.P1, undefined);
});
test("secondary choices replace within a row and retain at most two distinct rows", () => {
  assert.deepEqual(
    chooseSecondaryRune(config, build(), runes[5], "Precision", "Sorcery")
      .minor_runes,
    ["P1", "P2", "S2", "S1b"],
  );
  assert.deepEqual(
    chooseSecondaryRune(config, build(), runes[7], "Precision", "Sorcery")
      .minor_runes,
    ["P1", "P2", "S2", "S3"],
  );
  assert.deepEqual(
    chooseSecondaryRune(config, build(), runes[8], "Precision", "Sorcery"),
    {},
  );
});
test("path changes clear incompatible selections and separate the paths", () => {
  assert.deepEqual(inferRunePaths(config, build()), {
    primary: "Precision",
    secondary: "Sorcery",
  });
  const result = changePrimaryPath(config, build(), "Sorcery", "Sorcery");
  assert.equal(result.secondary, "Precision");
  assert.equal(result.change.keystone, "");
  assert.deepEqual(result.change.minor_runes, []);
  assert.deepEqual(
    changeSecondaryPath(config, build(), "Precision").minor_runes,
    ["P1", "P2"],
  );
});
test("choosing the last shard first sends a dense array", () => {
  const shardConfig = {
    rune_shards: [1, 2, 3].map((row) => ({
      row,
      name: String(row),
      options: [{ name: "Health", implemented: true }],
    })),
  };
  assert.deepEqual(chooseStatShard(shardConfig, build(), 2, "Health"), {
    stat_shards: ["", "", "Health"],
  });
});
