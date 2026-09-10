import test from "node:test";
import assert from "node:assert/strict";
import type { Champion, Config, Item } from "./types.ts";
import { newParticipant } from "./scenario-state.ts";
import type {
  ScoreboardHit,
  ScoreboardPlayer,
  ScoreboardReading,
} from "./scoreboard-vision.d.ts";
import {
  playersOf,
  loadoutFor,
  scoreboardLoadResult,
  type ScoreboardCatalog,
  type ScoreboardReadPlayer,
} from "./scoreboard-load.ts";

const champion = (name: string): Champion => ({
  name,
  icon: "",
  engine_registration: name.toLowerCase(),
  abilities: {},
});
const item = (
  id: number,
  name: string,
  tier: number,
  stage?: "starter" | "intermediate" | "upgraded",
): Item => ({
  id,
  name,
  icon: "",
  price: 0,
  tier,
  ap: 0,
  ad: 0,
  hp: 0,
  armor: 0,
  mr: 0,
  haste: 0,
  ...(stage ? { support_quest_stage: stage } : {}),
});
const config = {
  domain_contract: {
    role_quest: {
      roles: ["top", "jungle", "mid", "bottom", "support"],
      level_cap: { default: 20, by_role: {} },
      inventory_capacity: { default: 6, by_role: {} },
      boots_tier: {
        default: 3,
        by_role: { support: { complete: 3, incomplete: 2 } },
      },
    },
    rank_allocation: {
      by_champion: {},
      default_rules: {
        rank_unlock_levels: {
          Q: [1, 3, 5, 7, 9, 11, 13, 15, 17],
          W: [2, 4, 6, 8, 10, 12, 14, 16, 18],
          E: [1, 3, 5, 7, 9, 11, 13, 15, 17],
          R: [6, 11, 16],
        },
        free_ranks: {},
      },
      rules_by_champion: {
        Lulu: {
          rank_unlock_levels: {
            Q: [1, 3, 5, 7, 9, 11, 13, 15, 17],
            W: [2, 4, 6, 8, 10, 12, 14, 16, 18],
            E: [1, 3, 5, 7, 9, 11, 13, 15, 17],
            R: [6, 11, 16],
          },
          free_ranks: { W: 1 },
        },
      },
    },
  },
} as unknown as Config;
const catalog: ScoreboardCatalog = {
  champions: [champion("Ashe"), champion("Lulu"), champion("Zed")],
  items: [
    item(2001, "Long Sword", 1),
    item(2002, "Spellthief's Edge", 1, "starter"),
    item(2003, "Frostfang", 2, "upgraded"),
  ],
  boots: [
    item(1001, "Boots of Swiftness", 1),
    item(1002, "Ionian Boots of Lucidity", 2),
    item(1003, "Quest-tier Boots", 3),
  ],
  config,
};
const hit = (
  kind: "champion" | "item",
  key: string,
  overrides: Partial<ScoreboardHit> = {},
): ScoreboardHit => ({
  kind,
  key,
  score: 0.9,
  gap: 0.3,
  x: 0,
  y: 0,
  size: 30,
  ...overrides,
});
const player = (
  championKey: string,
  side: number,
  items: (ScoreboardHit | null)[] = [],
): ScoreboardPlayer => ({
  champion: hit("champion", championKey),
  side,
  items,
});
const readPlayer = (
  championKey: string,
  row: number,
  items: (ScoreboardHit | null)[] = [],
): ScoreboardReadPlayer => ({
  ...player(championKey, 0, items),
  row,
  role: ["top", "jungle", "mid", "bottom", "support"][row] ?? "",
});

test("loadoutFor dedups items, splits out boots and keeps the row role by default", () => {
  const read = readPlayer("Ashe", 0, [
    hit("item", "2001"),
    hit("item", "1001"),
    hit("item", "2001"),
    null,
  ]);
  const loadout = loadoutFor(catalog, read);
  assert.equal(loadout.champion, "Ashe");
  assert.equal(loadout.role, "top");
  assert.equal(loadout.boots, "Boots of Swiftness");
  assert.deepEqual(loadout.items, ["Long Sword", null, null, null, null, null]);
  assert.equal(loadout.questComplete, false);
});

test("any support quest item forces the support role and completes the quest at its own boots gate", () => {
  const read = readPlayer("Ashe", 3, [
    hit("item", "2002"),
    hit("item", "1001"),
  ]);
  const loadout = loadoutFor(catalog, read);
  assert.equal(loadout.role, "support");
  // Tier 1 boots do not clear the support incomplete gate (tier 2).
  assert.equal(loadout.questComplete, false);
});

test("an upgraded support item completes the quest regardless of boots tier", () => {
  const read = readPlayer("Ashe", 4, [
    hit("item", "2003"),
    hit("item", "1001"),
  ]);
  const loadout = loadoutFor(catalog, read);
  assert.equal(loadout.role, "support");
  assert.equal(loadout.questComplete, true);
});

test("boots above the support incomplete gate complete the quest without an upgraded item", () => {
  const read = readPlayer("Ashe", 4, [
    hit("item", "2002"),
    hit("item", "1003"),
  ]);
  const loadout = loadoutFor(catalog, read);
  assert.equal(loadout.role, "support");
  assert.equal(loadout.questComplete, true);
});

test("an item id absent from the catalog is dropped, not placed in a slot", () => {
  const read = readPlayer("Ashe", 0, [
    hit("item", "9999"),
    hit("item", "2001"),
  ]);
  const loadout = loadoutFor(catalog, read);
  assert.deepEqual(loadout.items, ["Long Sword", null, null, null, null, null]);
});

test("playersOf assigns roles by row and empties past the fifth", () => {
  const reading: ScoreboardReading = {
    hits: [],
    rows: [[player("Ashe", 0), player("Lulu", 1)], [player("Zed", 0)]],
  };
  const players = playersOf(reading);
  assert.deepEqual(
    players.map((p) => p.role),
    ["top", "top", "jungle"],
  );
  assert.deepEqual(
    players.map((p) => p.row),
    [0, 0, 1],
  );
});

test("scoreboardLoadResult splits by side, keeps the main level, and caps rosters", () => {
  const reading: ScoreboardReading = {
    hits: [],
    rows: Array.from({ length: 6 }, (_, row) => [
      player("Ashe", 0),
      player("Lulu", 1),
    ]),
  };
  const main = { ...newParticipant("main"), level: 11 };
  let counter = 0;
  const result = scoreboardLoadResult(
    reading,
    0,
    catalog,
    main,
    () => `id-${counter++}`,
  );
  assert.equal(result.main.id, "main");
  assert.equal(result.main.champion, "Ashe");
  assert.equal(result.main.level, 11);
  assert.equal(result.allies.length, 4);
  assert.equal(result.enemies.length, 5);
  assert.ok(
    result.allies.every(
      (ally) => ally.champion === "Ashe" && ally.level === 11,
    ),
  );
  assert.ok(
    result.enemies.every(
      (enemy) => enemy.champion === "Lulu" && enemy.level === 11,
    ),
  );
  assert.deepEqual(
    result.allies.map((ally) => ally.id),
    ["id-0", "id-1", "id-2", "id-3"],
  );
});

test("scoreboardLoadResult applies a champion's free ranks, reduced for the main's level", () => {
  const reading: ScoreboardReading = {
    hits: [],
    rows: [[player("Lulu", 0)]],
  };
  const main = { ...newParticipant("main"), level: 3 };
  const result = scoreboardLoadResult(reading, 0, catalog, main);
  assert.deepEqual(result.main.ranks, { Q: 0, W: 1, E: 0, R: 0 });
});

test("scoreboardLoadResult throws when the picked index has no player", () => {
  const reading: ScoreboardReading = { hits: [], rows: [[player("Ashe", 0)]] };
  assert.throws(() =>
    scoreboardLoadResult(reading, 5, catalog, newParticipant("main")),
  );
});

test("an unmodeled champion still loads with its read name, matching the shared-build page", () => {
  const reading: ScoreboardReading = {
    hits: [],
    rows: [[player("Ashe", 0), player("NotARealChampion", 1)]],
  };
  const result = scoreboardLoadResult(
    reading,
    0,
    catalog,
    newParticipant("main"),
  );
  assert.equal(result.enemies[0].champion, "NotARealChampion");
});
