import type { Build, Champion, Config, Values, RankRules } from "./types";

export type SkillRanks = Record<string, number>;
export interface Participant {
  id: string;
  champion: string;
  level: number;
  role: string;
  questComplete: boolean;
  ranks: SkillRanks;
  build: Build;
  championOptions: Values;
  supportTargets: Record<string, number>;
  allyEffectsEnabled: boolean;
  autos: boolean;
  uptimeMode: "calculated" | "explicit";
  uptime: number;
}
export interface AuthoredEvent {
  id: string;
  time: number;
  caster_id: string;
  slot: "Q" | "W" | "E" | "R";
  recipient_id: string;
}
export const zeroRanks = (): SkillRanks => ({ Q: 0, W: 0, E: 0, R: 0 });
export const newBuild = (): Build => ({
  items: Array(6).fill(null),
  boots: "",
  keystone: "",
  keystone_options: {},
  minor_runes: [],
  stat_shards: [],
  item_options: {},
  rune_options: {},
});
export const newParticipant = (id: string): Participant => ({
  id,
  champion: "",
  level: 1,
  role: "",
  questComplete: false,
  ranks: zeroRanks(),
  build: newBuild(),
  championOptions: {},
  supportTargets: {},
  allyEffectsEnabled: true,
  autos: true,
  uptimeMode: "calculated",
  uptime: 0,
});
export function domainValue(
  config: Config,
  participant: Participant,
  key: "level_cap" | "inventory_capacity" | "boots_tier",
): number {
  const rule = config.domain_contract.role_quest[key];
  return (
    rule.by_role[participant.role]?.[
      participant.questComplete ? "complete" : "incomplete"
    ] ?? rule.default
  );
}
export function skillCaps(level: number, rules?: RankRules): SkillRanks {
  if (rules)
    return Object.fromEntries(
      Object.entries(rules.rank_unlock_levels).map(([slot, levels]) => [
        slot,
        levels.filter((unlock) => unlock <= level).length,
      ]),
    );
  return {
    Q: Math.min(5, Math.ceil(level / 2)),
    W: Math.min(5, Math.ceil(level / 2)),
    E: Math.min(5, Math.ceil(level / 2)),
    R: level >= 16 ? 3 : level >= 11 ? 2 : level >= 6 ? 1 : 0,
  };
}
// Lowering a level can only remove ranks. It never spends a point for the user.
export function reduceRanksForLevel(
  ranks: SkillRanks,
  level: number,
  rules?: RankRules,
): SkillRanks {
  const caps = skillCaps(level, rules);
  const free = rules?.free_ranks ?? zeroRanks();
  const next = Object.fromEntries(
    Object.entries(caps).map(([slot, cap]) => [
      slot,
      Math.max(free[slot] ?? 0, Math.min(cap, ranks[slot] ?? 0)),
    ]),
  );
  let excess =
    Object.entries(next).reduce(
      (sum, [slot, rank]) => sum + rank - (free[slot] ?? 0),
      0,
    ) - Math.min(level, 18);
  for (const slot of ["R", "E", "W", "Q"]) {
    const removed = Math.min(
      next[slot] - (free[slot] ?? 0),
      Math.max(0, excess),
    );
    next[slot] -= removed;
    excess -= removed;
  }
  return next;
}
export function serializeParticipant(
  participant: Participant,
  build = participant.build,
) {
  return {
    kind: "champion",
    champion: participant.champion,
    level: participant.level,
    role: participant.role,
    role_quest_complete: participant.questComplete,
    items: build.items.filter((item): item is string => Boolean(item)),
    boots: build.boots,
    include_boots: Boolean(build.boots),
    ability_ranks: { ...participant.ranks },
    champion_options: participant.championOptions,
    keystone: build.keystone,
    keystone_options: build.keystone_options,
    minor_runes: build.minor_runes,
    stat_shards: build.stat_shards,
    item_options: Object.fromEntries(
      Object.entries(build.item_options).filter(
        ([name]) => build.items.includes(name) || name === build.boots,
      ),
    ),
    rune_options: Object.fromEntries(
      Object.entries(build.rune_options).filter(
        ([name]) => name === build.keystone || build.minor_runes.includes(name),
      ),
    ),
    support_target_selections: participant.supportTargets,
    ally_effects_enabled: participant.allyEffectsEnabled,
    include_auto_attacks: participant.autos,
    auto_attack_uptime_mode: participant.autos
      ? participant.uptimeMode
      : "explicit",
    auto_attack_uptime: participant.autos ? participant.uptime : 0,
  };
}
export function compactSlotIndex(
  items: (string | null)[],
  visualSlot: number,
): number {
  return items[visualSlot]
    ? items.slice(0, visualSlot).filter(Boolean).length
    : items.filter(Boolean).length;
}
export function championByName(champions: Champion[], name: string) {
  return champions.find((champion) => champion.name === name);
}
/** Preserve the identity of a selected teammate when roster positions change. */
export function reindexSupportTargets(
  previous: Participant[],
  next: Participant[],
): Participant[] {
  return next.map((owner) => {
    const oldTeammates = previous.filter(
      (actor) => actor.id !== owner.id && actor.champion,
    );
    const teammates = next.filter(
      (actor) => actor.id !== owner.id && actor.champion,
    );
    const supportTargets: Record<string, number> = {};
    for (const [key, index] of Object.entries(owner.supportTargets)) {
      const recipient = oldTeammates[index];
      const nextIndex = recipient
        ? teammates.findIndex((actor) => actor.id === recipient.id)
        : -1;
      if (nextIndex >= 0) supportTargets[key] = nextIndex;
    }
    return { ...owner, supportTargets };
  });
}
