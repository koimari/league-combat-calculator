export const skillSlots = ["Q", "W", "E", "R"] as const;
export function unspentSkillPoints(
  level: number,
  ranks: Record<string, number>,
): number {
  return Math.max(
    0,
    Math.min(level, 18) -
      skillSlots.reduce((sum, slot) => sum + (ranks[slot] ?? 0), 0),
  );
}
export function increaseSkillRank(
  level: number,
  ranks: Record<string, number>,
  slot: string,
  cap: number | undefined,
): Record<string, number> | null {
  if (
    !skillSlots.some((key) => key === slot) ||
    cap === undefined ||
    (ranks[slot] ?? 0) >= cap ||
    unspentSkillPoints(level, ranks) < 1
  )
    return null;
  return { ...ranks, [slot]: (ranks[slot] ?? 0) + 1 };
}
