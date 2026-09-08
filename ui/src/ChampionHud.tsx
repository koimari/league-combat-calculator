import { useId, useState } from "react";
import type { Champion, Item } from "./types";
import "./champion-hud.css";
import { GameTooltip } from "./Tooltip";
import { wikiText } from "./shop";
import { increaseSkillRank, unspentSkillPoints } from "./hud-ranks";

export interface ChampionHudProps {
  champion?: Champion;
  label: string;
  level: number;
  maxLevel: number;
  onLevel: (level: number) => void;
  onChampion: () => void;
  ranks: Record<string, number> | null;
  onRanks?: (ranks: Record<string, number> | null) => void;
  rankCaps?: Record<string, number>;
  defaultRanks?: Record<string, number>;
  ranksDerived?: boolean;
  stats: Record<string, number> | null;
  loading?: boolean;
  error?: string;
  items: (Item | undefined)[];
  onItem: (index: number) => void;
  onShop: () => void;
  onRunes?: () => void;
  gold: string;
  resourceLabel?: string;
}

const statRows = [
  ["attack_damage", "AD", "Attack damage", "physical"],
  ["ability_power", "AP", "Ability power", "magic"],
  ["armor", "AR", "Armor", "armor"],
  ["magic_resistance", "MR", "Magic resistance", "resist"],
  ["attack_speed", "AS", "Attack speed", "speed"],
  ["ability_haste", "AH", "Ability haste", "haste"],
  ["critical_strike_chance", "CR", "Critical strike chance", "physical"],
  ["move_speed", "MS", "Movement speed", "speed"],
] as const;

const extraStats: {
  key: string;
  label: string;
  group: "Offense" | "Defense";
  percent?: boolean;
}[] = [
  { key: "attack_damage", label: "Attack damage", group: "Offense" },
  { key: "base_attack_damage", label: "Base attack damage", group: "Offense" },
  {
    key: "bonus_attack_damage",
    label: "Bonus attack damage",
    group: "Offense",
  },
  { key: "ability_power", label: "Ability power", group: "Offense" },
  { key: "attack_speed", label: "Attack speed", group: "Offense" },
  { key: "attack_speed_ratio", label: "Attack speed ratio", group: "Offense" },
  {
    key: "bonus_attack_speed",
    label: "Bonus attack speed",
    group: "Offense",
    percent: true,
  },
  {
    key: "magic_penetration_flat",
    label: "Flat magic penetration",
    group: "Offense",
  },
  {
    key: "magic_penetration_percent",
    label: "Magic penetration",
    group: "Offense",
    percent: true,
  },
  { key: "lethality", label: "Lethality", group: "Offense" },
  {
    key: "flat_armor_penetration",
    label: "Flat armor penetration",
    group: "Offense",
  },
  {
    key: "armor_penetration_percent",
    label: "Total armor penetration",
    group: "Offense",
    percent: true,
  },
  {
    key: "armor_penetration_bonus_percent",
    label: "Bonus armor penetration",
    group: "Offense",
    percent: true,
  },
  {
    key: "critical_strike_chance",
    label: "Critical strike chance",
    group: "Offense",
    percent: true,
  },
  {
    key: "critical_strike_damage_percent",
    label: "Bonus critical damage",
    group: "Offense",
    percent: true,
  },
  { key: "ability_haste", label: "Ability haste", group: "Offense" },
  {
    key: "basic_ability_haste",
    label: "Basic ability haste",
    group: "Offense",
  },
  { key: "ultimate_haste", label: "Ultimate haste", group: "Offense" },
  { key: "health", label: "Health", group: "Defense" },
  { key: "base_health", label: "Base health", group: "Defense" },
  { key: "bonus_health", label: "Bonus health", group: "Defense" },
  { key: "armor", label: "Armor", group: "Defense" },
  { key: "bonus_armor", label: "Bonus armor", group: "Defense" },
  { key: "magic_resistance", label: "Magic resistance", group: "Defense" },
  {
    key: "bonus_magic_resistance",
    label: "Bonus magic resistance",
    group: "Defense",
  },
  { key: "max_mana", label: "Resource capacity", group: "Defense" },
  { key: "bonus_mana", label: "Bonus resource capacity", group: "Defense" },
  {
    key: "resource_regen_per_second",
    label: "Resource regeneration / second",
    group: "Defense",
  },
  {
    key: "health_regen_per_five",
    label: "Health regeneration / 5 seconds",
    group: "Defense",
  },
  {
    key: "health_regen_per_second",
    label: "Health regeneration / second",
    group: "Defense",
  },
  {
    key: "health_regen_percent",
    label: "Bonus health regeneration",
    group: "Defense",
    percent: true,
  },
  {
    key: "lifesteal_percent",
    label: "Life steal",
    group: "Defense",
    percent: true,
  },
  {
    key: "omnivamp_percent",
    label: "Omnivamp",
    group: "Defense",
    percent: true,
  },
  {
    key: "heal_and_shield_power_percent",
    label: "Heal and shield power",
    group: "Defense",
    percent: true,
  },
  {
    key: "tenacity_percent",
    label: "Tenacity",
    group: "Defense",
    percent: true,
  },
  { key: "move_speed", label: "Movement speed", group: "Defense" },
  { key: "move_speed_flat", label: "Flat movement speed", group: "Defense" },
  {
    key: "move_speed_percent",
    label: "Bonus movement speed",
    group: "Defense",
    percent: true,
  },
  { key: "gold_per_10", label: "Gold / 10 seconds", group: "Defense" },
];

const statDescriptions: Record<string, string> = {
  attack_damage:
    "Damage stat used by basic attacks and abilities that scale with attack damage.",
  ability_power: "Increases effects that scale with ability power.",
  armor: "Defensive stat used when the engine resolves physical damage.",
  magic_resistance:
    "Defensive stat used when the engine resolves magic damage.",
  attack_speed:
    "Basic attacks per second before combat effects change attack speed.",
  ability_haste: "Haste used by the engine when it resolves ability cooldowns.",
  critical_strike_chance:
    "Chance for an eligible attack to critically strike, expressed as a percentage.",
  move_speed:
    "Movement speed before combat effects. Movement affects the calculated attack uptime.",
};

function abilityDescription(
  ability:
    | {
        description?: string;
        rank_values?: { label: string; values: string[] }[];
      }
    | undefined,
) {
  if (!ability) return "Choose a champion to view this ability.";
  return [
    ability.description
      ? wikiText(ability.description)
      : "Ability description is unavailable in the current source.",
    ...(ability.rank_values ?? []).map(
      (row) =>
        `${wikiText(row.label)}: ${row.values.map(wikiText).join(" / ")}`,
    ),
  ].join("\n\n");
}

function itemDescription(item: Item | undefined) {
  if (!item) return "Open the shop to choose an item for this slot.";
  const values: [number | undefined, string][] = [
    [item.ad, "attack damage"],
    [item.ap, "ability power"],
    [item.hp, "health"],
    [item.armor, "armor"],
    [item.mr, "magic resistance"],
    [item.haste, "ability haste"],
    [item.mana, "mana"],
    [item.attackSpeed, "% attack speed"],
    [item.crit, "% critical strike chance"],
    [item.critDamage, "% critical strike damage"],
    [item.pen, "magic penetration"],
    [item.percentPen, "% magic penetration"],
    [item.lethality, "lethality"],
    [item.percentArmorPen, "% armor penetration"],
    [item.lifesteal, "% life steal"],
    [item.omnivamp, "% omnivamp"],
    [item.healAndShieldPower, "% heal and shield power"],
    [item.healthRegen, "% health regeneration"],
    [item.manaRegen, "% mana regeneration"],
    [item.moveSpeed, "movement speed"],
    [item.moveSpeedPercent, "% movement speed"],
    [item.tenacity, "% tenacity"],
  ];
  const stats = values
    .filter(([value]) => value !== undefined && value !== 0)
    .map(([value, label]) => `${value} ${label}`)
    .join(" · ");
  return (
    [
      stats,
      ...(item.effects ?? []).map(
        (effect) =>
          `${effect.name ? wikiText(effect.name) + ": " : ""}${wikiText(effect.text)}`,
      ),
    ]
      .filter(Boolean)
      .join("\n\n") || "Effect text is unavailable in the current source."
  );
}

function numberText(value: number | undefined, digits = 0) {
  return value === undefined || !Number.isFinite(value)
    ? "—"
    : value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function ChampionHud({
  champion,
  label,
  level,
  maxLevel,
  onLevel,
  onChampion,
  ranks,
  onRanks,
  rankCaps,
  defaultRanks,
  ranksDerived = false,
  stats,
  loading = false,
  error,
  items,
  onItem,
  onShop,
  onRunes,
  gold,
  resourceLabel = "Mana",
}: ChampionHudProps) {
  const id = useId();
  const [statTab, setStatTab] = useState("Basic");
  const editable = Boolean(onRanks && rankCaps && !ranksDerived && champion);
  const resolvedRanks = ranks ?? defaultRanks ?? { Q: 0, W: 0, E: 0, R: 0 };
  const points = unspentSkillPoints(level, resolvedRanks);
  const visibleStats = loading || error ? null : stats;
  const health = visibleStats?.health;
  const resource = visibleStats?.max_mana;
  return (
    <section
      className="champion-hud"
      aria-labelledby={`${id}-title`}
      aria-busy={loading}
    >
      <header className="champion-hud-heading">
        <h3 id={`${id}-title`}>
          <span>{label}</span> {champion?.name ?? "Choose champion"}
        </h3>
        {editable && (
          <div className="champion-hud-skill-controls">
            <span role="status">
              {points} unspent {points === 1 ? "point" : "points"}
            </span>
            <button
              type="button"
              className="champion-hud-rank-mode"
              onClick={() => onRanks?.({ Q: 0, W: 0, E: 0, R: 0 })}
            >
              Reset skill points
            </button>
            <button
              className="champion-hud-rank-mode"
              type="button"
              onClick={() =>
                onRanks?.(
                  ranks === null
                    ? { ...(defaultRanks ?? { Q: 0, W: 0, E: 0, R: 0 }) }
                    : null,
                )
              }
            >
              {ranks === null ? "Edit ability ranks" : "Use automatic ranks"}
            </button>
          </div>
        )}
      </header>
      <div className="champion-hud-viewport">
        <div className="champion-hud-frame">
          <div className="champion-hud-identity">
            <button
              className="champion-hud-portrait"
              type="button"
              onClick={onChampion}
              aria-label={`${label}: choose champion`}
            >
              {champion?.icon ? (
                <img src={champion.icon} alt={champion.name} />
              ) : (
                <span>+</span>
              )}
            </button>
            <label className="champion-hud-level" title={`${label} level`}>
              <span className="champion-hud-sr">{label} level</span>
              <input
                type="number"
                min={1}
                max={maxLevel}
                value={level}
                onChange={(event) => {
                  const value = event.currentTarget.valueAsNumber;
                  if (
                    Number.isInteger(value) &&
                    value >= 1 &&
                    value <= maxLevel
                  )
                    onLevel(value);
                }}
              />
            </label>
          </div>
          <div className="champion-hud-center">
            <div className="champion-hud-abilities">
              {["P", "Q", "W", "E", "R"].map((slot) => {
                const ability = champion?.abilities[slot];
                const cap = rankCaps?.[slot];
                const rank = (ranks ?? defaultRanks)?.[slot];
                const usedElsewhere = Object.entries(ranks ?? {}).reduce(
                  (sum, [key, value]) => sum + (key === slot ? 0 : value),
                  0,
                );
                const allowedRank = Math.max(
                  0,
                  Math.min(cap ?? 0, Math.min(level, 18) - usedElsewhere),
                );
                return (
                  <div
                    className={`champion-hud-ability${slot === "P" ? " champion-hud-passive" : ""}`}
                    key={slot}
                  >
                    {slot !== "P" && (
                      <GameTooltip
                        className="champion-hud-upgrade-tooltip"
                        title={`Level up ${slot}`}
                        description={
                          ranksDerived
                            ? "This champion's ability ranks follow its level. Change the champion level to update them."
                            : !champion
                              ? "Choose a champion first."
                              : points === 0
                                ? "All available skill points are spent. Increase the champion level or reset skill points to change the allocation."
                                : (rank ?? 0) >= (cap ?? 0)
                                  ? "This ability has reached its rank limit at the selected champion level."
                                  : `Spend one skill point to increase ${ability?.name ?? slot} to rank ${(rank ?? 0) + 1}.`
                        }
                      >
                        <button
                          type="button"
                          className="champion-hud-upgrade"
                          aria-label={`${label}: level up ${slot}`}
                          aria-disabled={
                            !editable ||
                            increaseSkillRank(
                              level,
                              resolvedRanks,
                              slot,
                              cap,
                            ) === null
                          }
                          onClick={() => {
                            if (!editable) return;
                            const next = increaseSkillRank(
                              level,
                              resolvedRanks,
                              slot,
                              cap,
                            );
                            if (next) onRanks?.(next);
                          }}
                        >
                          <span className="champion-hud-sr">
                            Level up {slot}
                          </span>
                        </button>
                      </GameTooltip>
                    )}
                    <GameTooltip
                      className="champion-hud-ability-tooltip"
                      title={ability?.name ?? `${slot} ability`}
                      description={abilityDescription(ability)}
                      meta={`${slot}${rank === undefined ? "" : ` · Rank ${rank}`} · Source values by rank`}
                    >
                      <button
                        type="button"
                        className="champion-hud-ability-image"
                        aria-label={`${slot}: ${ability?.name ?? "ability details"}`}
                      >
                        {ability?.icon ? (
                          <img src={ability.icon} alt={ability.name} />
                        ) : (
                          <span>{slot}</span>
                        )}
                        <kbd>{slot}</kbd>
                      </button>
                    </GameTooltip>
                    {slot !== "P" && (
                      <div className="champion-hud-rank">
                        {editable && ranks !== null && cap !== undefined ? (
                          <label>
                            <span className="champion-hud-sr">
                              {label} {slot} rank
                            </span>
                            <input
                              type="number"
                              min={0}
                              max={allowedRank}
                              value={rank ?? 0}
                              onChange={(event) => {
                                const value = event.currentTarget.valueAsNumber;
                                if (
                                  Number.isInteger(value) &&
                                  value >= 0 &&
                                  value <= allowedRank
                                )
                                  onRanks?.({ ...ranks, [slot]: value });
                              }}
                            />
                          </label>
                        ) : (
                          <span
                            title={
                              ranksDerived
                                ? "Ranks follow champion level"
                                : "The engine sets automatic ranks"
                            }
                          >
                            {rank === undefined ? "Auto" : rank}
                          </span>
                        )}
                        {cap !== undefined && (
                          <span
                            className="champion-hud-pips"
                            aria-hidden="true"
                          >
                            {Array.from(
                              { length: Math.max(0, Math.min(8, cap)) },
                              (_, index) => (
                                <i
                                  className={
                                    rank !== undefined && index < rank
                                      ? "filled"
                                      : ""
                                  }
                                  key={index}
                                />
                              ),
                            )}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            <div className="champion-hud-bars">
              <GameTooltip
                className="champion-hud-bar-tooltip"
                title="Health"
                description="Maximum health before combat, from the selected champion, level, items and runes. The bar shows the full starting amount."
                meta={`${numberText(health)} health`}
              >
                <div
                  tabIndex={0}
                  className="champion-hud-bar champion-hud-health"
                  aria-label={`Health: ${numberText(health)}`}
                >
                  <span>Health</span>
                  <strong>
                    {health === undefined
                      ? "—"
                      : `${numberText(health)} / ${numberText(health)}`}
                  </strong>
                </div>
              </GameTooltip>
              {resource !== undefined && (
                <GameTooltip
                  className="champion-hud-bar-tooltip"
                  title={resourceLabel}
                  description={`Maximum ${resourceLabel.toLowerCase()} before combat. This value comes from the selected loadout.`}
                  meta={`${numberText(resource)} ${resourceLabel.toLowerCase()}`}
                >
                  <div
                    tabIndex={0}
                    className="champion-hud-bar champion-hud-resource"
                    aria-label={`${resourceLabel}: ${numberText(resource)}`}
                  >
                    <span>{resourceLabel}</span>
                    <strong>
                      {numberText(resource)} / {numberText(resource)}
                    </strong>
                  </div>
                </GameTooltip>
              )}
            </div>
          </div>
          <div className="champion-hud-inventory">
            <div className="champion-hud-slots">
              {Array.from({ length: 6 }, (_, index) => (
                <GameTooltip
                  key={index}
                  className="champion-hud-item-tooltip"
                  title={items[index]?.name ?? `Item slot ${index + 1}`}
                  description={itemDescription(items[index])}
                  meta={
                    items[index]
                      ? `${items[index].price.toLocaleString()} gold`
                      : "Inventory"
                  }
                >
                  <button
                    type="button"
                    onClick={() => onItem(index)}
                    aria-label={`${label}: ${items[index]?.name ?? `empty item slot ${index + 1}`}`}
                  >
                    {items[index]?.icon ? (
                      <img src={items[index].icon} alt={items[index].name} />
                    ) : (
                      <span aria-hidden="true">{index + 1}</span>
                    )}
                  </button>
                </GameTooltip>
              ))}
            </div>
            <button
              className="champion-hud-gold"
              type="button"
              onClick={onShop}
              aria-label={`${label}: open shop${gold ? `, ${gold} gold` : ""}`}
            >
              <span aria-hidden="true">●</span> {gold || "Shop"}
            </button>
          </div>
          {onRunes && (
            <button
              className="champion-hud-runes"
              type="button"
              onClick={onRunes}
            >
              Runes
            </button>
          )}
          <dl className="champion-hud-stats" aria-label="Stats before combat">
            {statRows.map(([key, short, name, tone]) => (
              <div key={key}>
                <dt className={`champion-hud-stat-${tone}`}>
                  <GameTooltip
                    className="champion-hud-stat-tooltip"
                    title={name}
                    description={statDescriptions[key]}
                    meta={`${numberText(visibleStats?.[key], key === "attack_speed" ? 2 : 0)}${key === "critical_strike_chance" ? "%" : ""} · Before combat`}
                  >
                    <span
                      tabIndex={0}
                      aria-label={name}
                      className={`champion-hud-stat-icon champion-hud-icon-${key}`}
                    />
                  </GameTooltip>
                  <abbr className="champion-hud-sr">{short}</abbr>
                </dt>
                <dd>
                  {numberText(
                    visibleStats?.[key],
                    key === "attack_speed" ? 2 : 0,
                  )}
                  {key === "critical_strike_chance" &&
                  visibleStats?.[key] !== undefined
                    ? "%"
                    : ""}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
      <div
        className="champion-hud-stat-tabs"
        role="tablist"
        aria-label={`${label} stat categories`}
      >
        {["Basic", "Offense", "Defense", "All"].map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            id={`${id}-tab-${tab}`}
            aria-controls={`${id}-stat-panel`}
            aria-selected={statTab === tab}
            tabIndex={statTab === tab ? 0 : -1}
            onKeyDown={(event) => {
              const tabs = ["Basic", "Offense", "Defense", "All"];
              const current = tabs.indexOf(tab);
              const next =
                event.key === "ArrowRight"
                  ? (current + 1) % 4
                  : event.key === "ArrowLeft"
                    ? (current + 3) % 4
                    : event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? 3
                        : -1;
              if (next < 0) return;
              event.preventDefault();
              setStatTab(tabs[next]);
              event.currentTarget.parentElement
                ?.querySelectorAll("button")
                [next]?.focus();
            }}
            onClick={() => setStatTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>
      <div
        id={`${id}-stat-panel`}
        role="tabpanel"
        aria-labelledby={`${id}-tab-${statTab}`}
      >
        {statTab !== "Basic" && (
          <div className="champion-hud-expanded-stats">
            {extraStats
              .filter((stat) => statTab === "All" || stat.group === statTab)
              .map((stat) => (
                <GameTooltip
                  key={stat.key}
                  className="champion-hud-expanded-stat"
                  title={stat.label}
                  description={
                    statDescriptions[stat.key] ??
                    `${stat.label} from this loadout before combat. Combat effects can change this value.`
                  }
                >
                  <div tabIndex={0}>
                    <span>{stat.label}</span>
                    <strong>
                      {numberText(visibleStats?.[stat.key], 2)}
                      {stat.percent && visibleStats?.[stat.key] !== undefined
                        ? "%"
                        : ""}
                    </strong>
                  </div>
                </GameTooltip>
              ))}
          </div>
        )}
        <p className="champion-hud-caption">Stats before combat</p>
      </div>
      {(loading || error) && (
        <p className="champion-hud-status" role={error ? "alert" : "status"}>
          {error || "Loading champion stats…"}
        </p>
      )}
    </section>
  );
}
