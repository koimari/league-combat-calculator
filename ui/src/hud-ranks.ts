export const skillSlots = ["Q", "W", "E", "R"] as const;
export function unspentSkillPoints(
  level: number,
  ranks: Record<string, number>,
  minimumRanks: Record<string, number> = {},
  skillPointBudget = Math.min(level, 18),
): number {
  return Math.max(
    0,
    skillPointBudget -
      skillSlots.reduce(
        (sum, slot) =>
          sum + Math.max(0, (ranks[slot] ?? 0) - (minimumRanks[slot] ?? 0)),
        0,
      ),
  );
}
export function increaseSkillRank(
  level: number,
  ranks: Record<string, number>,
  slot: string,
  cap: number | undefined,
  minimumRanks: Record<string, number> = {},
  skillPointBudget = Math.min(level, 18),
): Record<string, number> | null {
  if (
    !skillSlots.some((key) => key === slot) ||
    cap === undefined ||
    (ranks[slot] ?? 0) >= cap ||
    unspentSkillPoints(level, ranks, minimumRanks, skillPointBudget) < 1
  )
    return null;
  return { ...ranks, [slot]: (ranks[slot] ?? 0) + 1 };
}

export function decreaseSkillRank(
  ranks: Record<string, number>,
  slot: string,
  minimumRanks: Record<string, number> = {},
): Record<string, number> | null {
  if (
    !skillSlots.some((key) => key === slot) ||
    (ranks[slot] ?? 0) <= (minimumRanks[slot] ?? 0)
  )
    return null;
  return { ...ranks, [slot]: ranks[slot] - 1 };
}
