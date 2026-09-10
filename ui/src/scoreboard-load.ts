import type { Champion, Config, Item } from "./types";
import type {
  ScoreboardPlayer,
  ScoreboardReading,
} from "./scoreboard-vision.js";
import {
  newParticipant,
  newBuild,
  zeroRanks,
  domainValue,
  reduceRanksForLevel,
  type Participant,
} from "./scenario-state.ts";

/** Row order a broadcast panel reads top to bottom, per `ScoreboardVision`. */
export const SCOREBOARD_ROLES = ["top", "jungle", "mid", "bottom", "support"];

export interface ScoreboardCatalog {
  champions: Champion[];
  items: Item[];
  boots: Item[];
  config: Config;
}

export interface ScoreboardReadPlayer extends ScoreboardPlayer {
  /** Row index, top to bottom. */
  row: number;
  /** `SCOREBOARD_ROLES[row]`, or "" past the fifth row. */
  role: string;
}

/** Every player read, top to bottom then left to right, with the role its row implies. */
export function playersOf(reading: ScoreboardReading): ScoreboardReadPlayer[] {
  return reading.rows.flatMap((row, r) =>
    row.map((player) => ({
      ...player,
      row: r,
      role: SCOREBOARD_ROLES[r] ?? "",
    })),
  );
}

/** A player's champion, matched against the catalog by name. `null` when the
 * scoreboard read a champion the engine has no module for. */
export function championFor(
  catalog: ScoreboardCatalog,
  player: ScoreboardReadPlayer,
): Champion | null {
  return (
    catalog.champions.find(
      (champion) => champion.name === player.champion.key,
    ) ?? null
  );
}

function catalogItem(
  catalog: ScoreboardCatalog,
  id: number,
): { item: Item; isBoot: boolean } | null {
  const boot = catalog.boots.find((entry) => entry.id === id);
  if (boot) return { item: boot, isBoot: true };
  const item = catalog.items.find((entry) => entry.id === id);
  if (item) return { item, isBoot: false };
  return null;
}

export interface ScoreboardLoadout {
  champion: string;
  role: string;
  questComplete: boolean;
  items: (string | null)[];
  boots: string;
}

/**
 * A player's loadout, folded through the same role-quest rule the backend
 * enforces: boots above the tier an unfinished quest allows, or an upgraded
 * support item, complete the quest; any support quest item puts the player
 * in the support role. Items are matched by numeric id against the catalog,
 * deduplicated, boots split into their own slot (one only, the first found),
 * the rest filling the six build slots in read order. Mirrors `payloadFor`
 * in the old page's `static/js/scoreboard.js`, over the typed catalog
 * instead of the vanilla page's `engine` globals.
 */
export function loadoutFor(
  catalog: ScoreboardCatalog,
  player: ScoreboardReadPlayer,
): ScoreboardLoadout {
  const seen = new Set<number>();
  const ids: number[] = [];
  for (const hit of player.items) {
    if (!hit) continue;
    const id = Number(hit.key);
    if (seen.has(id) || !catalogItem(catalog, id)) continue;
    seen.add(id);
    ids.push(id);
  }
  const bootsId = ids.find((id) => catalogItem(catalog, id)?.isBoot);
  const bootsItem =
    bootsId === undefined
      ? null
      : (catalogItem(catalog, bootsId)?.item ?? null);
  const otherIds = ids.filter((id) => id !== bootsId);
  const stages = otherIds
    .map((id) => catalogItem(catalog, id)?.item.support_quest_stage)
    .filter((stage): stage is "starter" | "intermediate" | "upgraded" =>
      Boolean(stage),
    );
  const role = stages.length ? "support" : player.role;
  const probe: Participant = {
    ...newParticipant("scoreboard-probe"),
    role,
    questComplete: false,
  };
  const incompleteBootsTier = domainValue(catalog.config, probe, "boots_tier");
  const questComplete =
    (bootsItem !== null && bootsItem.tier > incompleteBootsTier) ||
    stages.includes("upgraded");
  const items: (string | null)[] = Array(6).fill(null);
  otherIds.slice(0, 6).forEach((id, index) => {
    items[index] = catalogItem(catalog, id)?.item.name ?? null;
  });
  return {
    champion: player.champion.key,
    role,
    questComplete,
    items,
    boots: bootsItem?.name ?? "",
  };
}

function ranksFor(catalog: ScoreboardCatalog, champion: string, level: number) {
  const byChampion =
    catalog.config.domain_contract.rank_allocation.rules_by_champion?.[
      champion
    ];
  const rules =
    byChampion ?? catalog.config.domain_contract.rank_allocation.default_rules;
  const ranks = { ...zeroRanks(), ...byChampion?.free_ranks };
  return reduceRanksForLevel(ranks, level, rules);
}

/** A read player folded into a full `Participant`, the same shape
 * `addParticipant`/`pickChampion` build in `Calculator.tsx`. */
function participantFor(
  catalog: ScoreboardCatalog,
  player: ScoreboardReadPlayer,
  id: string,
  level: number,
): Participant {
  const loadout = loadoutFor(catalog, player);
  return {
    ...newParticipant(id),
    champion: loadout.champion,
    level,
    role: loadout.role,
    questComplete: loadout.questComplete,
    ranks: ranksFor(catalog, loadout.champion, level),
    build: { ...newBuild(), items: loadout.items, boots: loadout.boots },
  };
}

export interface ScoreboardLoadResult {
  main: Participant;
  allies: Participant[];
  enemies: Participant[];
}

/**
 * The reading, folded into a roster: the picked player becomes `main` (kept
 * at its current level), the rest of their team becomes allies (capped at
 * 4) and the opposing team becomes enemies (capped at 5). A scoreboard shows
 * no runes, ability ranks beyond the champion's free ranks, or per-player
 * levels, so every loaded participant shares the main's level, as a shared
 * build does.
 */
export function scoreboardLoadResult(
  reading: ScoreboardReading,
  pickedIndex: number,
  catalog: ScoreboardCatalog,
  main: Participant,
  makeId: () => string = () => crypto.randomUUID(),
): ScoreboardLoadResult {
  const players = playersOf(reading);
  const picked = players[pickedIndex];
  if (!picked) throw new Error("No player is selected.");
  const level = main.level;
  const teammates = players
    .filter((player) => player !== picked && player.side === picked.side)
    .slice(0, 4);
  const opponents = players
    .filter((player) => player.side !== picked.side)
    .slice(0, 5);
  return {
    main: { ...participantFor(catalog, picked, "main", level), id: "main" },
    allies: teammates.map((player) =>
      participantFor(catalog, player, makeId(), level),
    ),
    enemies: opponents.map((player) =>
      participantFor(catalog, player, makeId(), level),
    ),
  };
}
