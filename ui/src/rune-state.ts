import type { Build, Config, Rune } from "./types.ts";
type RuneCatalogue = Pick<Config, "runes" | "keystones">;
export const runePathOrder = [
  "Precision",
  "Domination",
  "Sorcery",
  "Resolve",
  "Inspiration",
];

export function availableRunePaths(config: RuneCatalogue): string[] {
  const paths = [
    ...new Set([...config.keystones, ...config.runes].map((rune) => rune.path)),
  ];
  return [
    ...runePathOrder.filter((path) => paths.includes(path)),
    ...paths.filter((path) => !runePathOrder.includes(path)),
  ];
}
export function inferRunePaths(
  config: RuneCatalogue,
  build: Build,
): { primary: string; secondary: string } {
  const paths = availableRunePaths(config);
  const chosen = config.runes.filter((rune) =>
    build.minor_runes.includes(rune.name),
  );
  const primary =
    config.keystones.find((rune) => rune.name === build.keystone)?.path ??
    chosen[0]?.path ??
    paths[0] ??
    "";
  const secondary =
    chosen.find((rune) => rune.path !== primary)?.path ??
    (primary !== "Sorcery" && paths.includes("Sorcery")
      ? "Sorcery"
      : paths.find((path) => path !== primary)) ??
    "";
  return { primary, secondary };
}
function minorChange(build: Build, selected: string[]): Partial<Build> {
  return {
    minor_runes: selected,
    rune_options: Object.fromEntries(
      Object.entries(build.rune_options).filter(([name]) =>
        selected.includes(name),
      ),
    ),
  };
}
export function changePrimaryPath(
  config: RuneCatalogue,
  build: Build,
  path: string,
  secondary: string,
): { change: Partial<Build>; secondary: string } {
  const nextSecondary =
    path === secondary
      ? (availableRunePaths(config).find((candidate) => candidate !== path) ??
        "")
      : secondary;
  const kept =
    path === secondary
      ? []
      : build.minor_runes.filter((name) =>
          config.runes.some(
            (rune) =>
              rune.name === name && rune.path === secondary && rune.row > 0,
          ),
        );
  return {
    change: { ...minorChange(build, kept), keystone: "", keystone_options: {} },
    secondary: nextSecondary,
  };
}
export function changeSecondaryPath(
  config: RuneCatalogue,
  build: Build,
  primary: string,
): Partial<Build> {
  return minorChange(
    build,
    build.minor_runes.filter((name) =>
      config.runes.some(
        (rune) => rune.name === name && rune.path === primary && rune.row > 0,
      ),
    ),
  );
}
export function choosePrimaryRune(
  config: RuneCatalogue,
  build: Build,
  rune: Rune,
  primary: string,
): Partial<Build> {
  if (!rune.implemented || rune.path !== primary) return {};
  if (rune.row === 0)
    return {
      keystone: rune.name,
      keystone_options:
        rune.name === build.keystone ? build.keystone_options : {},
    };
  const names = build.minor_runes.filter(
    (name) =>
      !config.runes.some(
        (candidate) =>
          candidate.name === name &&
          candidate.path === primary &&
          candidate.row === rune.row,
      ),
  );
  return minorChange(build, [...names, rune.name]);
}
export function chooseSecondaryRune(
  config: RuneCatalogue,
  build: Build,
  rune: Rune,
  primary: string,
  secondary: string,
): Partial<Build> {
  if (
    !rune.implemented ||
    rune.row === 0 ||
    rune.path !== secondary ||
    primary === secondary
  )
    return {};
  const primaryNames = build.minor_runes.filter((name) =>
    config.runes.some(
      (candidate) =>
        candidate.name === name &&
        candidate.path === primary &&
        candidate.row > 0,
    ),
  );
  const previous = build.minor_runes
    .map((name) => config.runes.find((candidate) => candidate.name === name))
    .filter((candidate): candidate is Rune =>
      Boolean(
        candidate &&
          candidate.path === secondary &&
          candidate.row > 0 &&
          candidate.row !== rune.row,
      ),
    );
  // Keep the most recently selected other row when a third row is chosen.
  return minorChange(build, [
    ...primaryNames,
    ...previous.slice(-1).map((candidate) => candidate.name),
    rune.name,
  ]);
}
export function chooseStatShard(
  config: Pick<Config, "rune_shards">,
  build: Build,
  row: number,
  name: string,
): Partial<Build> {
  if (
    !config.rune_shards[row]?.options.some(
      (option) => option.name === name && option.implemented,
    )
  )
    return {};
  return {
    stat_shards: config.rune_shards.map((_, index) =>
      index === row ? name : (build.stat_shards[index] ?? ""),
    ),
  };
}
