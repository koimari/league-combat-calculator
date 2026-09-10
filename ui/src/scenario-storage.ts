import type { AuthoredEvent, Participant } from "./scenario-state";
import type { Build, Values } from "./types";

export interface SavedScenario {
  version: 1;
  main: Participant;
  alternative: Build;
  allies: Participant[];
  enemies: Participant[];
  autosOnly: boolean;
  compare: boolean;
  duration: number;
  objective: string;
  includeActives: boolean;
  enemiesAttack: boolean;
  dummyStats: Record<string, number>;
  useSequence: boolean;
  events: AuthoredEvent[];
  budgets: Record<string, string>;
}
const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const finite = (value: unknown, min: number, max: number) =>
  typeof value === "number" &&
  Number.isFinite(value) &&
  value >= min &&
  value <= max;
const string = (value: unknown, max = 128): value is string =>
  typeof value === "string" && value.length <= max;
const strings = (value: unknown, max = 20): value is string[] =>
  Array.isArray(value) &&
  value.length <= max &&
  value.every((item) => string(item));
const values = (value: unknown): value is Values =>
  object(value) &&
  Object.keys(value).length <= 100 &&
  Object.entries(value).every(
    ([key, entry]) =>
      string(key) &&
      ((typeof entry === "number" && Number.isFinite(entry)) ||
        typeof entry === "boolean" ||
        string(entry, 1024) ||
        strings(entry)),
  );
const options = (value: unknown) =>
  object(value) &&
  Object.keys(value).length <= 100 &&
  Object.entries(value).every(([key, entry]) => string(key) && values(entry));
function build(value: unknown): value is Build {
  return (
    object(value) &&
    Array.isArray(value.items) &&
    value.items.length === 6 &&
    value.items.every((item) => item === null || string(item)) &&
    string(value.boots) &&
    string(value.keystone) &&
    strings(value.minor_runes, 5) &&
    strings(value.stat_shards, 3) &&
    values(value.keystone_options) &&
    options(value.item_options) &&
    options(value.rune_options)
  );
}
function actor(value: unknown): value is Participant {
  return (
    object(value) &&
    string(value.id) &&
    Boolean(value.id) &&
    string(value.champion) &&
    finite(value.level, 1, 20) &&
    Number.isInteger(value.level) &&
    string(value.role) &&
    typeof value.questComplete === "boolean" &&
    object(value.ranks) &&
    ["Q", "W", "E", "R"].every(
      (slot) =>
        finite((value.ranks as Record<string, unknown>)[slot], 0, 6) &&
        Number.isInteger((value.ranks as Record<string, unknown>)[slot]),
    ) &&
    build(value.build) &&
    values(value.championOptions) &&
    object(value.supportTargets) &&
    Object.values(value.supportTargets).every(
      (entry) => finite(entry, 0, 4) && Number.isInteger(entry),
    ) &&
    typeof value.allyEffectsEnabled === "boolean" &&
    typeof value.autos === "boolean" &&
    ["calculated", "explicit"].includes(String(value.uptimeMode)) &&
    finite(value.uptime, 0, 1)
  );
}
export function parseScenario(text: string): SavedScenario {
  if (text.length > 200_000)
    throw new Error(
      "This setup is too large. Choose a calculator setup under 200 KB.",
    );
  const value: unknown = JSON.parse(text);
  if (
    !object(value) ||
    value.version !== 1 ||
    !actor(value.main) ||
    value.main.id !== "main" ||
    !build(value.alternative) ||
    !Array.isArray(value.allies) ||
    value.allies.length > 4 ||
    !value.allies.every(actor) ||
    !Array.isArray(value.enemies) ||
    value.enemies.length > 5 ||
    !value.enemies.every(actor) ||
    typeof value.autosOnly !== "boolean" ||
    typeof value.compare !== "boolean" ||
    !finite(value.duration, 1, 30) ||
    !string(value.objective) ||
    typeof value.includeActives !== "boolean" ||
    typeof value.enemiesAttack !== "boolean" ||
    typeof value.useSequence !== "boolean" ||
    !object(value.dummyStats) ||
    !["health", "bonus_health", "armor", "mr"].every((key) =>
      finite((value.dummyStats as Record<string, unknown>)[key], 0, 10000),
    ) ||
    !object(value.budgets) ||
    !Object.entries(value.budgets).every(
      ([key, entry]) =>
        string(key) && string(entry, 8) && /^(?:\d+(?:\.\d+)?)?$/.test(entry),
    ) ||
    !Array.isArray(value.events) ||
    value.events.length > 100
  )
    throw new Error("This file is not a supported calculator setup.");
  const ids = [value.main, ...value.allies, ...value.enemies].map(
    (participant) => participant.id,
  );
  if (new Set(ids).size !== ids.length)
    throw new Error("The setup contains duplicate participant IDs.");
  if (
    !value.events.every(
      (event) =>
        object(event) &&
        string(event.id) &&
        Boolean(event.id) &&
        finite(event.time, 0, 30) &&
        ids.includes(String(event.caster_id)) &&
        ids.includes(String(event.recipient_id)) &&
        ["Q", "W", "E", "R"].includes(String(event.slot)),
    )
  )
    throw new Error("The setup contains an invalid spell event.");
  if (
    new Set(value.events.map((event) => event.id)).size !== value.events.length
  )
    throw new Error("The setup contains duplicate event IDs.");
  return value as unknown as SavedScenario;
}
export function encodeScenario(value: SavedScenario): string {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  return btoa(Array.from(bytes, (byte) => String.fromCharCode(byte)).join(""));
}
export function decodeScenario(value: string): SavedScenario {
  if (value.length > 280_000) throw new Error("This setup link is too large.");
  return parseScenario(
    new TextDecoder().decode(
      Uint8Array.from(atob(value), (char) => char.charCodeAt(0)),
    ),
  );
}
