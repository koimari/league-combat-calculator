import test from "node:test";
import assert from "node:assert/strict";
import { newParticipant, newBuild } from "./scenario-state.ts";
import {
  parseScenario,
  encodeScenario,
  decodeScenario,
  type SavedScenario,
} from "./scenario-storage.ts";
const scenario = (): SavedScenario => ({
  version: 1,
  main: newParticipant("main"),
  alternative: newBuild(),
  allies: [],
  enemies: [],
  autosOnly: false,
  compare: true,
  duration: 8,
  objective: "team_outcome",
  includeActives: true,
  enemiesAttack: true,
  dummyStats: { health: 1000, bonus_health: 0, armor: 100, mr: 100 },
  useSequence: false,
  events: [],
  budgets: {},
});
test("setup links round-trip manual ranks and Unicode labels", () => {
  const value = scenario();
  value.main.champion = "Vel'Koz";
  value.main.ranks.Q = 1;
  assert.deepEqual(decodeScenario(encodeScenario(value)), value);
});
test("setup import rejects duplicate identities and dangling events", () => {
  const value = scenario();
  value.allies = [newParticipant("main")];
  assert.throws(() => parseScenario(JSON.stringify(value)), /duplicate/);
  value.allies = [];
  value.events = [
    { id: "x", time: 1, caster_id: "main", slot: "E", recipient_id: "missing" },
  ];
  assert.throws(() => parseScenario(JSON.stringify(value)), /invalid spell/);
});
test("setup import rejects unbounded inventories and invalid option shapes", () => {
  const value = scenario();
  value.main.build.items.push(null);
  assert.throws(() => parseScenario(JSON.stringify(value)), /supported/);
});

test("setup import rejects duplicate spell event identities", () => {
  const value = scenario();
  value.events = [
    { id: "same", time: 1, caster_id: "main", slot: "E", recipient_id: "main" },
    { id: "same", time: 2, caster_id: "main", slot: "W", recipient_id: "main" },
  ];
  assert.throws(() => parseScenario(JSON.stringify(value)), /duplicate event/);
});
