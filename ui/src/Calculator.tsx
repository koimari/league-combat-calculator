"use client";

import { useEffect, useRef, useState, useId, type ReactNode } from "react";
import { ChampionHud } from "./ChampionHud";
import { RunePage } from "./RunePage";
import { GameTooltip } from "./Tooltip";
import "./rune-page.css";
import { useLoadoutStats } from "./useLoadoutStats";
import { request } from "./api";
import { shopGroup, wikiText } from "./shop";
import type {
  Build,
  Champion,
  Config,
  Item,
  Optimization,
  Option,
  Result,
  Values,
} from "./types";

export interface CalculatorProps {
  apiBase?: string;
  className?: string;
  advancedHref?: string;
}
const emptyBuild = (): Build => ({
  items: Array(6).fill(null),
  boots: "",
  keystone: "",
  keystone_options: {},
  minor_runes: [],
  stat_shards: [],
  item_options: {},
  rune_options: {},
});
const format = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value)
    ? new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value)
    : "—";
const label = (value: string) => value.replaceAll("_", " ");
const normalize = (value: string) =>
  value.toLowerCase().replace(/[^a-z0-9]/g, "");

function Options({
  options,
  values,
  onChange,
}: {
  options: Option[];
  values: Values;
  onChange: (values: Values) => void;
}) {
  return (
    <div className="calculator-options">
      {options.map((option) => {
        const value = values[option.key] ?? option.default ?? "";
        const type =
          option.type ?? (option.kind === "switch" ? "switch" : "int");
        const change = (next: Values[string]) =>
          onChange({ ...values, [option.key]: next });
        const choices = option.options ?? option.choices;
        return (
          <label
            className={
              type === "bool" || type === "switch"
                ? "calculator-check"
                : "calculator-field"
            }
            key={option.key}
          >
            {type === "bool" || type === "switch" ? (
              <>
                <input
                  type="checkbox"
                  checked={Boolean(value)}
                  onChange={(e) =>
                    change(
                      type === "switch"
                        ? Number(e.target.checked)
                        : e.target.checked,
                    )
                  }
                />
                <span>{option.label ?? label(option.key)}</span>
              </>
            ) : (
              <>
                <span>{option.label ?? label(option.key)}</span>
                {choices ? (
                  <select
                    value={String(value)}
                    onChange={(e) => change(e.target.value)}
                  >
                    {choices.map((choice) =>
                      typeof choice === "string" ? (
                        <option key={choice}>{choice}</option>
                      ) : (
                        <option key={choice.value} value={choice.value}>
                          {choice.label}
                        </option>
                      ),
                    )}
                  </select>
                ) : type === "string_list" ? (
                  <input
                    value={
                      Array.isArray(value) ? value.join(", ") : String(value)
                    }
                    placeholder="Separate values with commas"
                    onChange={(e) =>
                      change(
                        e.target.value
                          .split(",")
                          .map((s) => s.trim())
                          .filter(Boolean),
                      )
                    }
                  />
                ) : (
                  <input
                    type={
                      ["int", "float", "number"].includes(type)
                        ? "number"
                        : "text"
                    }
                    min={option.min ?? option.minimum}
                    max={option.max ?? option.maximum}
                    step={option.step ?? (type === "int" ? 1 : "any")}
                    value={String(value)}
                    onChange={(e) =>
                      change(
                        e.target.type === "number"
                          ? e.target.value === ""
                            ? ""
                            : Number(e.target.value)
                          : e.target.value,
                      )
                    }
                  />
                )}
              </>
            )}
          </label>
        );
      })}
    </div>
  );
}

const shopStats = [
  ["Attack damage", ["ad"], "sword"],
  ["Ability power", ["ap"], "spark"],
  ["Attack speed", ["attackSpeed"], "arrows"],
  ["Critical strike", ["crit"], "burst"],
  ["Health", ["hp"], "heart"],
  ["Armor", ["armor"], "shield"],
  ["Magic resistance", ["mr"], "ward"],
  ["Ability haste", ["haste"], "clock"],
  ["Mana", ["mana", "manaRegen"], "drop"],
  ["Magic penetration", ["pen", "percentPen"], "wand"],
  ["Armor penetration", ["lethality", "percentArmorPen"], "pierce"],
  [
    "Healing",
    ["lifesteal", "omnivamp", "healAndShieldPower", "healthRegen"],
    "heal",
  ],
  ["Movement speed", ["moveSpeed", "moveSpeedPercent"], "boot"],
  ["Tenacity", ["tenacity"], "anchor"],
] as const;
const itemStatLabels: [keyof Item, string, boolean?][] = [
  ["ad", "Attack damage"],
  ["ap", "Ability power"],
  ["attackSpeed", "Attack speed", true],
  ["crit", "Critical strike chance", true],
  ["critDamage", "Critical strike damage", true],
  ["hp", "Health"],
  ["armor", "Armor"],
  ["mr", "Magic resistance"],
  ["haste", "Ability haste"],
  ["mana", "Mana"],
  ["pen", "Magic penetration"],
  ["percentPen", "Magic penetration", true],
  ["lethality", "Lethality"],
  ["percentArmorPen", "Armor penetration", true],
  ["lifesteal", "Life steal", true],
  ["omnivamp", "Omnivamp", true],
  ["healAndShieldPower", "Heal and shield power", true],
  ["healthRegen", "Base health regeneration", true],
  ["manaRegen", "Base mana regeneration", true],
  ["moveSpeed", "Move speed"],
  ["moveSpeedPercent", "Move speed", true],
  ["tenacity", "Tenacity", true],
];
function ShopIcon({ name }: { name: string }) {
  const paths: Record<string, string> = {
    sword: "M5 19 18 6 20 4 20 9 8 21M4 14l6 6M3 21l3-3",
    spark: "m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z",
    arrows: "M4 7h14m-4-4 4 4-4 4M20 17H6m4-4-4 4 4 4",
    burst: "m12 2 2 6 6-3-3 6 5 2-6 2 2 6-6-4-5 5 1-7-6-2 7-2Z",
    heart: "M12 21 3.5 12.5C-1 6 7 1 12 7c5-6 13-1 8.5 5.5Z",
    shield: "m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6ZM12 3v18",
    ward: "m12 2 8 4v7l-8 9-8-9V6ZM8 10l4-4 4 4-4 7Z",
    clock:
      "M12 7v6l4 2M8 3h8M12 3v2M20 6l-2 2M21 13a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
    drop: "M12 2S4 11 4 15a8 8 0 0 0 16 0c0-4-8-13-8-13ZM8 15c0 3 2 4 4 4",
    wand: "m4 21 12-12M12 7l3-3 5 5-3 3ZM18 2v2M22 6h-2M7 6v4M5 8h4",
    pierce: "m3 21 17-17M13 4h7v7M4 7l5-2M17 15l-1 5M5 5l1 9 8 7 6-6",
    heal: "M9 3h6v6h6v6h-6v6H9v-6H3V9h6Z",
    boot: "M7 3h9l-1 10 6 4v4H3v-5l4-5ZM7 7h8",
    anchor:
      "M12 7v14M5 12H2l2 6 8 3 8-3 2-6h-3M8 10h8M15 4a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
    grid: "M3 3h6v6H3ZM15 3h6v6h-6ZM3 15h6v6H3ZM15 15h6v6h-6Z",
  };
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name] ?? paths.grid} />
    </svg>
  );
}
interface ShopState {
  budget: string;
  spend: number;
  replacement: number;
  replacingName: string | null;
  label: string;
  selectedName: string;
  onSelect: (name: string) => void;
  boots: boolean;
  slotAvailable: boolean;
  catalogue: Item[];
  quickBoots: Item[];
  inventory: {
    name: string | null;
    label: string;
    active: boolean;
    boots?: boolean;
    index: number;
  }[];
  onBudget: (value: string) => void;
  onSlot: (index: number, boots: boolean) => void;
  onClear: () => void;
  onTab: (boots: boolean) => void;
  optimizer?: ReactNode;
}
function ItemShop({
  shop,
  items,
  onPick,
  onClose,
}: {
  shop: ShopState;
  items: Item[];
  onPick: (name: string) => void;
  onClose: () => void;
}) {
  const [bisOpen, setBisOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [stats, setStats] = useState<string[]>([]);
  const [affordable, setAffordable] = useState(false);
  const [sort, setSort] = useState("price");
  const [itemClass, setItemClass] = useState("");
  const selectedName = shop.selectedName;
  const setSelectedName = shop.onSelect;
  const [recipeName, setRecipeName] = useState(shop.selectedName);
  const dialog = useRef<HTMLDialogElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const id = useId();
  useEffect(() => {
    const node = dialog.current;
    node?.showModal();
    search.current?.focus();
    return () => node?.close();
  }, []);
  const available =
    shop.budget === ""
      ? null
      : Number(shop.budget) - shop.spend + shop.replacement;
  const remaining =
    shop.budget === "" ? null : Number(shop.budget) - shop.spend;
  const selected = shop.catalogue.find((item) => item.name === selectedName);
  const ownedElsewhere = (name: string) =>
    shop.inventory.some((slot) => slot.name === name && !slot.active);
  const selectedAvailable =
    items.some((item) => item.name === selectedName) &&
    !ownedElsewhere(selectedName);
  const canAdd = Boolean(selected && selectedAvailable && shop.slotAvailable);
  const matches = items
    .filter(
      (item) =>
        normalize(
          [
            item.name,
            ...(item.effects ?? []).map(
              (effect) => `${effect.name ?? ""} ${wikiText(effect.text)}`,
            ),
            ...itemStatLabels
              .filter(([key]) => Number(item[key]) > 0)
              .map(([, label]) => label),
          ].join(" "),
        ).includes(normalize(query)) &&
        (!itemClass || item.shop_tags?.includes(itemClass)) &&
        stats.every((stat) =>
          shopStats
            .find(([name]) => name === stat)?.[1]
            .some((field) => Number(item[field]) > 0),
        ) &&
        (!affordable || available === null || item.price <= available),
    )
    .sort((a, b) =>
      sort === "name"
        ? a.name.localeCompare(b.name)
        : a.price - b.price || a.name.localeCompare(b.name),
    );
  const [reverse, setReverse] = useState(false);
  const groups = reverse
    ? ["Other items", "Legendary", "Epic", "Starter & Basic"]
    : ["Starter & Basic", "Epic", "Legendary", "Other items"];
  const recipe =
    shop.catalogue.find((item) => item.name === recipeName) ?? selected;
  const category = shopGroup;
  const buildsInto = recipe?.builds_into ?? [];
  const components = recipe?.builds_from ?? [];
  function relationButton(
    relation: NonNullable<Item["builds_from"]>[number],
    index: number,
    keepTree = false,
  ) {
    const item = shop.catalogue.find(
      (candidate) => candidate.id === relation.id,
    );
    return (
      <div key={`${relation.id}-${index}`}>
        {item ? (
          iconButton(item, true, keepTree)
        ) : (
          <button
            type="button"
            className="calculator-shop-tree-item"
            disabled
            title={`${relation.name ?? `Item ${relation.id}`} · unavailable in calculator`}
            aria-label={`${relation.name ?? `Item ${relation.id}`}, unavailable in calculator`}
          >
            <span className="calculator-shop-item-art">
              {relation.icon ? (
                <img src={relation.icon} alt="" />
              ) : (
                <span>?</span>
              )}
            </span>
            <span className="calculator-shop-item-price">
              {relation.price === null ? "—" : format(relation.price)}
            </span>
          </button>
        )}
      </div>
    );
  }
  function choose(item: Item, keepTree = false) {
    setSelectedName(item.name);
    if (!keepTree) setRecipeName(item.name);
  }
  function add(item: Item) {
    if (
      shop.slotAvailable &&
      items.some((candidate) => candidate.name === item.name) &&
      !ownedElsewhere(item.name)
    )
      onPick(item.name);
  }
  function iconButton(item: Item, tree = false, keepTree = false) {
    const description = [
      ...itemStatLabels
        .filter(([key]) => Number(item[key]) > 0)
        .map(
          ([key, label, percent]) =>
            `${format(item[key])}${percent ? "%" : ""} ${label}`,
        ),
      ...(item.effects ?? []).map(
        (effect) => `${effect.name ?? effect.kind}\n${wikiText(effect.text)}`,
      ),
    ].join("\n\n");
    return (
      <GameTooltip
        key={item.id}
        title={item.name}
        description={description}
        meta={`${format(item.price)} gold`}
        className="calculator-shop-tooltip"
      >
        <button
          type="button"
          className={
            tree ? "calculator-shop-tree-item" : "calculator-shop-item"
          }
          aria-label={`${item.name}, ${format(item.price)} gold`}
          aria-pressed={item.name === selectedName}
          onClick={() => choose(item, keepTree)}
          onDoubleClick={() => add(item)}
          onContextMenu={(event) => {
            event.preventDefault();
            choose(item);
            add(item);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              add(item);
            }
          }}
        >
          <span className="calculator-shop-item-art">
            <img src={item.icon} alt="" loading="lazy" />
            {shop.inventory.some((slot) => slot.name === item.name) && (
              <span className="calculator-shop-owned" aria-label="In build">
                ✓
              </span>
            )}
          </span>
          <span className="calculator-shop-item-price">
            {format(item.price)}
          </span>
        </button>
      </GameTooltip>
    );
  }
  return (
    <dialog
      ref={dialog}
      className="calculator-item-shop"
      aria-labelledby={id}
      onCancel={onClose}
      onClick={(event) => {
        if (event.target === dialog.current) onClose();
      }}
    >
      <header className="calculator-shop-header">
        <div className="calculator-shop-title">
          <ShopIcon name="grid" />
          <h2 id={id}>Item shop</h2>
          <span>{shop.label}</span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="calculator-shop-close"
          aria-label="Close item shop"
        >
          ×
        </button>
      </header>
      <div className="calculator-shop-body">
        <aside
          className="calculator-shop-quickbuy"
          aria-label="Quick buy and inventory"
        >
          <section>
            <h3>Boots</h3>
            <div className="calculator-shop-quick-grid">
              {shop.quickBoots.map((item) => (
                <button
                  type="button"
                  className="calculator-shop-item"
                  key={item.id}
                  title={item.name}
                  aria-label={`View ${item.name}, ${format(item.price)} gold`}
                  aria-pressed={selectedName === item.name}
                  onClick={() => {
                    shop.onTab(true);
                    choose(item);
                  }}
                >
                  <span className="calculator-shop-item-art">
                    <img src={item.icon} alt="" loading="lazy" />
                  </span>
                  <span className="calculator-shop-item-price">
                    {format(item.price)}
                  </span>
                </button>
              ))}
            </div>
          </section>
          <section className="calculator-shop-bag">
            <h3>{shop.label}</h3>
            <div className="calculator-shop-inventory-slots">
              {shop.inventory.map((slot) => {
                const item = shop.catalogue.find(
                  (candidate) => candidate.name === slot.name,
                );
                return (
                  <button
                    type="button"
                    key={`${slot.boots ? "boots" : "item"}-${slot.index}`}
                    aria-label={`${slot.label}${slot.name ? `: ${slot.name}` : ": empty"}`}
                    title={slot.name ?? slot.label}
                    aria-pressed={slot.active}
                    onClick={() => {
                      shop.onSlot(slot.index, Boolean(slot.boots));
                      if (slot.name) setSelectedName(slot.name);
                    }}
                  >
                    {item ? (
                      <img src={item.icon} alt="" />
                    ) : slot.boots ? (
                      <ShopIcon name="boot" />
                    ) : (
                      <span>{slot.index + 1}</span>
                    )}
                  </button>
                );
              })}
            </div>
            <button
              type="button"
              className="calculator-shop-bag-remove"
              disabled={!shop.replacingName}
              onClick={shop.onClear}
              aria-label="Remove selected inventory item"
            >
              ×
            </button>
            <span className="calculator-shop-bag-hint">
              Select a slot to replace it
            </span>
          </section>
        </aside>
        <aside className="calculator-shop-rail" aria-label="Item stat filters">
          <button
            type="button"
            title="Clear stat filters"
            aria-label="All stats"
            aria-pressed={stats.length === 0}
            onClick={() => setStats([])}
          >
            <ShopIcon name="grid" />
          </button>
          <span className="calculator-shop-rail-rule" />
          {shopStats.map(([name, , icon]) => (
            <button
              type="button"
              key={name}
              title={name}
              aria-label={name}
              aria-pressed={stats.includes(name)}
              onClick={() =>
                setStats((current) =>
                  current.includes(name)
                    ? current.filter((value) => value !== name)
                    : [...current, name],
                )
              }
            >
              <ShopIcon name={icon} />
              <span className="calculator-shop-stat-tooltip">{name}</span>
            </button>
          ))}
        </aside>
        <section
          className="calculator-shop-catalogue"
          aria-label="Browse items"
        >
          <div className="calculator-shop-tabs" aria-label="Item categories">
            <button
              type="button"
              aria-pressed={!shop.boots}
              onClick={() => shop.onTab(false)}
            >
              All items
            </button>
            <button
              type="button"
              aria-pressed={shop.boots}
              onClick={() => shop.onTab(true)}
            >
              <ShopIcon name="boot" />
              Boots
            </button>
            {shop.optimizer && (
              <button
                type="button"
                aria-pressed={bisOpen}
                onClick={() => setBisOpen(!bisOpen)}
              >
                BIS builder
              </button>
            )}
          </div>
          {bisOpen && (
            <section className="calculator-shop-bis" aria-label="BIS builder">
              {shop.optimizer}
            </section>
          )}
          <div className="calculator-shop-tools">
            <label className="calculator-shop-search">
              <svg viewBox="0 0 20 20" aria-hidden="true">
                <circle cx="8" cy="8" r="5.5" />
                <path d="m12 12 5 5" />
              </svg>
              <span className="calculator-sr-only">Search shop</span>
              <input
                ref={search}
                type="search"
                placeholder="Search for items"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            <div className="calculator-shop-filter-row">
              <label>
                <input
                  type="checkbox"
                  checked={affordable}
                  disabled={available === null}
                  onChange={(event) => setAffordable(event.target.checked)}
                />
                Can afford
              </label>
              <label className="calculator-shop-sort">
                <span>Sort</span>
                <select
                  value={sort}
                  onChange={(event) => setSort(event.target.value)}
                >
                  <option value="price">Price</option>
                  <option value="name">Name</option>
                </select>
              </label>
              <span aria-live="polite">{matches.length} items</span>
            </div>
            {stats.length > 0 && (
              <div className="calculator-shop-active-filters">
                {stats.map((stat) => (
                  <button
                    type="button"
                    key={stat}
                    onClick={() =>
                      setStats((current) =>
                        current.filter((value) => value !== stat),
                      )
                    }
                  >
                    {stat}
                    <span aria-hidden="true">×</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="calculator-shop-classes" aria-label="Item classes">
            <button
              type="button"
              title="All classes"
              aria-label="All classes"
              aria-pressed={!itemClass}
              onClick={() => setItemClass("")}
            >
              <ShopIcon name="grid" />
            </button>
            {[
              ["FIGHTER", "Fighter", "sword"],
              ["MARKSMAN", "Marksman", "arrows"],
              ["ASSASSIN", "Assassin", "pierce"],
              ["MAGE", "Mage", "spark"],
              ["TANK", "Tank", "shield"],
              ["SUPPORT", "Support", "heal"],
            ].map(([value, name, icon]) => (
              <button
                type="button"
                key={value}
                title={name}
                aria-label={name}
                aria-pressed={itemClass === value}
                onClick={() => setItemClass(itemClass === value ? "" : value)}
              >
                <ShopIcon name={icon} />
              </button>
            ))}
            <button
              type="button"
              className="calculator-shop-tier-order"
              title="Reverse item quality order"
              aria-label="Reverse item quality order"
              aria-pressed={reverse}
              onClick={() => setReverse((value) => !value)}
            >
              ↕
            </button>
          </div>
          <div className="calculator-shop-grid-scroll">
            {(shop.boots ? ["Boots"] : groups).map((group) => {
              const groupItems = shop.boots
                ? matches
                : matches.filter((item) => category(item) === group);
              return (
                groupItems.length > 0 && (
                  <section className="calculator-shop-group" key={group}>
                    <h3>{group}</h3>
                    <div className="calculator-shop-grid">
                      {groupItems.map((item) => iconButton(item))}
                    </div>
                  </section>
                )
              );
            })}
            {matches.length === 0 && (
              <p className="calculator-shop-empty">
                No items match these filters.
              </p>
            )}
          </div>
        </section>
        <aside className="calculator-shop-detail" aria-label="Selected item">
          <div className="calculator-shop-detail-scroll">
            <section className="calculator-shop-upgrades">
              <h3>Builds into</h3>
              <div className="calculator-shop-related">
                {buildsInto.length ? (
                  buildsInto.map((item, index) => relationButton(item, index))
                ) : (
                  <span>
                    {selected
                      ? "No upgrades in this catalogue"
                      : "Select an item"}
                  </span>
                )}
              </div>
            </section>
            <div className="calculator-shop-tree">
              {recipe ? (
                <>
                  <div className="calculator-shop-tree-root">
                    {iconButton(recipe, true, true)}
                  </div>
                  {components.length > 0 && (
                    <div className="calculator-shop-tree-branches">
                      {components.map((item, index) => (
                        <div
                          className="calculator-shop-tree-branch"
                          key={`${item.id}-${index}`}
                        >
                          {relationButton(item, index, true)}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <span className="calculator-shop-tree-empty">
                  <ShopIcon name="grid" />
                </span>
              )}
            </div>
            <div className="calculator-shop-purchase">
              <div className="calculator-shop-purchase-note" role="status">
                {!shop.slotAvailable
                  ? "Select an inventory slot to replace."
                  : selected && !selectedAvailable
                    ? "This item is already in the build or unavailable for this slot."
                    : selected &&
                        available !== null &&
                        selected.price > available
                      ? `${format(selected.price - available)} gold above budget`
                      : shop.replacement
                        ? `${format(shop.replacement)} gold credited for replacement`
                        : "Full item price"}
              </div>
              <button
                type="button"
                disabled={!canAdd}
                onClick={() => selected && add(selected)}
              >
                {shop.replacingName ? "Replace item" : "Add to build"}
                {selected && <span>{format(selected.price)} gold</span>}
              </button>
            </div>
            {selected ? (
              <section className="calculator-shop-description">
                <div className="calculator-shop-selected-heading">
                  <img src={selected.icon} alt="" />
                  <div>
                    <h3>{selected.name}</h3>
                    <span className="calculator-shop-gold">
                      ◉ {format(selected.price)}
                    </span>
                  </div>
                </div>
                <dl>
                  {itemStatLabels
                    .filter(([field]) => Number(selected[field]) > 0)
                    .map(([field, text, percent]) => (
                      <div key={field}>
                        <dt>{text}</dt>
                        <dd>
                          {format(Number(selected[field]))}
                          {percent ? "%" : ""}
                        </dd>
                      </div>
                    ))}
                </dl>
                {selected.effects?.map((effect, index) => (
                  <section
                    className="calculator-shop-effect"
                    key={`${effect.kind}-${effect.name}-${index}`}
                  >
                    <h4>
                      {effect.name ?? label(effect.kind)}
                      <span>{effect.kind}</span>
                    </h4>
                    <p>{wikiText(effect.text)}</p>
                  </section>
                ))}
              </section>
            ) : (
              <div className="calculator-shop-description calculator-shop-empty">
                Select an item to see its stats and build path.
              </div>
            )}
          </div>
        </aside>
      </div>
      <footer className="calculator-shop-footer">
        <div className="calculator-shop-footer-actions">
          <button
            type="button"
            className="calculator-shop-remove"
            disabled={!shop.replacingName}
            onClick={shop.onClear}
          >
            Remove item
          </button>
          <span>
            {shop.replacingName ??
              (shop.slotAvailable ? "Select an item to add" : "Inventory full")}
          </span>
        </div>
        <div className="calculator-shop-gold-controls">
          <label>
            <span>Total budget</span>
            <div>
              <span aria-hidden="true">◉</span>
              <input
                aria-label="Total build budget in gold"
                type="number"
                min="0"
                step="1"
                placeholder="Unlimited"
                value={shop.budget}
                onChange={(event) =>
                  shop.onBudget(
                    event.target.value === ""
                      ? ""
                      : String(Math.max(0, Number(event.target.value))),
                  )
                }
              />
            </div>
          </label>
          <div className="calculator-shop-wallet">
            <span>{format(shop.spend)} spent</span>
            <strong>
              {remaining === null
                ? "Unlimited gold"
                : `${format(remaining)} remaining`}
            </strong>
            {shop.replacement > 0 && (
              <small>{format(available)} available for slot</small>
            )}
          </div>
        </div>
        <p className="calculator-shop-footnote">
          Full prices · Component discounts and sales excluded. Double-click or
          right-click to add.
        </p>
      </footer>
    </dialog>
  );
}
function Picker({
  title,
  entries,
  onPick,
  onClose,
}: {
  title: string;
  entries: {
    name: string;
    icon?: string;
    detail?: string;
    disabled?: boolean;
  }[];
  onPick: (name: string) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const id = useId();
  useEffect(() => {
    const node = dialog.current;
    node?.showModal();
    search.current?.focus();
    return () => node?.close();
  }, []);
  const matches = entries.filter((entry) =>
    normalize(entry.name).includes(normalize(query)),
  );
  return (
    <dialog
      ref={dialog}
      className="calculator-picker"
      aria-labelledby={id}
      onCancel={onClose}
      onClick={(event) => {
        if (event.target === dialog.current) onClose();
      }}
    >
      <div className="calculator-picker-heading">
        <h2 id={id}>{title}</h2>
        <button
          type="button"
          className="calculator-icon-button"
          onClick={onClose}
          aria-label="Close selection"
        >
          ×
        </button>
      </div>
      <label className="calculator-search">
        <span className="calculator-sr-only">Search {title.toLowerCase()}</span>
        <input
          ref={search}
          type="search"
          placeholder="Search by name…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      <div className="calculator-picker-count" aria-live="polite">
        {matches.length} available
      </div>
      <div className="calculator-choices">
        {matches.length ? (
          matches.map((entry) => (
            <button
              type="button"
              key={entry.name}
              className="calculator-choice"
              disabled={entry.disabled}
              onClick={() => onPick(entry.name)}
            >
              {entry.icon ? (
                <img src={entry.icon} alt="" loading="lazy" />
              ) : (
                <span className="calculator-choice-placeholder">◇</span>
              )}
              <span>
                <strong>{entry.name}</strong>
                {entry.detail && <small>{entry.detail}</small>}
              </span>
              <span aria-hidden="true">↗</span>
            </button>
          ))
        ) : (
          <p className="calculator-empty">No matches. Try another name.</p>
        )}
      </div>
    </dialog>
  );
}

function ResultCard({
  result,
  side,
  stale,
}: {
  result: Result;
  side: string;
  stale: boolean;
}) {
  const rows = Object.entries(result.breakdown ?? {});
  const coverage = result.timeline_coverage;
  return (
    <section
      className="calculator-result-card"
      aria-label={`Build ${side} result`}
    >
      <div className="calculator-card-heading">
        <h3>Build {side}</h3>
        <span className="calculator-tag">
          {stale
            ? "Previous result"
            : coverage?.complete
              ? "Event order checked"
              : "Coverage limited"}
        </span>
      </div>
      <div className="calculator-headline">
        <span>{format(result.headline_total)}</span>
        <p>Damage dealt</p>
      </div>
      {result.headline_total == null && (
        <p className="calculator-notice">
          The engine withheld the headline for this setup.
        </p>
      )}
      <div className="calculator-result-stats">
        <div>
          <span>Health damage</span>
          <strong>{format(result.health_damage)}</strong>
        </div>
        <div>
          <span>Shield absorbed</span>
          <strong>{format(result.shield_absorbed)}</strong>
        </div>
        <div>
          <span>Self healing</span>
          <strong>{format(result.self_healing)}</strong>
        </div>
      </div>
      <table className="calculator-breakdown">
        <caption>Damage by source</caption>
        <thead>
          <tr>
            <th scope="col">Source</th>
            <th scope="col">Damage</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([key, row]) => (
            <tr key={key}>
              <td>
                <span>{row.name || label(key)}</span>
                {row.casts || row.count ? (
                  <small>
                    {row.casts
                      ? `${row.casts} cast${row.casts === 1 ? "" : "s"}`
                      : `${row.count} hit${row.count === 1 ? "" : "s"}`}
                  </small>
                ) : null}
              </td>
              <td>{format(row.total_damage)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <details className="calculator-details">
        <summary>Calculation receipt</summary>
        <div className="calculator-detail-content">
          {coverage?.note && <p>{coverage.note}</p>}
          {result.notes?.map((note, index) => (
            <p key={index}>{note}</p>
          ))}
          {result.cast_timeline && (
            <>
              <h4>Cast order</h4>
              <ol className="calculator-timeline">
                {result.cast_timeline.map((event, index) => (
                  <li key={index}>
                    <span>{format(event.time)}s</span>{" "}
                    {event.name || event.slot}
                  </li>
                ))}
              </ol>
            </>
          )}
          <details>
            <summary>Source dispositions</summary>
            <pre>{JSON.stringify(result.dispositions ?? {}, null, 2)}</pre>
          </details>
        </div>
      </details>
    </section>
  );
}

export function Calculator(props: CalculatorProps) {
  return <CalculatorSession key={props.apiBase ?? ""} {...props} />;
}
function CalculatorSession({
  apiBase = "",
  className = "",
  advancedHref,
}: CalculatorProps) {
  const [catalog, setCatalog] = useState<{
    champions: Champion[];
    items: Item[];
    boots: Item[];
    config: Config;
  } | null>(null);
  const [loadVersion, setLoadVersion] = useState(0);
  const [loadError, setLoadError] = useState("");
  const [champion, setChampion] = useState("");
  const [level, setLevel] = useState(18);
  const [target, setTarget] = useState("");
  const [targetLevel, setTargetLevel] = useState(18);
  const [targetRanks, setTargetRanks] = useState<Record<string, number> | null>(
    null,
  );
  const [targetBuild, setTargetBuild] = useState<Build>(emptyBuild());
  const [hudSide, setHudSide] = useState(0);
  const [role, setRole] = useState("");
  const [questComplete, setQuestComplete] = useState(false);
  const [builds, setBuilds] = useState<[Build, Build]>([
    emptyBuild(),
    emptyBuild(),
  ]);
  const [compare, setCompare] = useState(true);
  const [duration, setDuration] = useState(10);
  const [targetStats, setTargetStats] = useState<Record<string, number>>({});
  const [targetItems, setTargetItems] = useState<(string | null)[]>(
    Array(6).fill(null),
  );
  const [championOptions, setChampionOptions] = useState<Values>({});
  const [ranks, setRanks] = useState<Record<string, number> | null>(null);
  const [autos, setAutos] = useState(true);
  const [enemyAttack, setEnemyAttack] = useState(true);
  const [budgets, setBudgets] = useState(["", "", ""]);
  const [shopSelection, setShopSelection] = useState("");
  const [picker, setPicker] = useState<{
    kind: "champion" | "target" | "item" | "boots" | "targetItem";
    side?: number;
    slot?: number;
  } | null>(null);
  const [results, setResults] = useState<Result[]>([]);
  const [resultKey, setResultKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [runeSide, setRuneSide] = useState<number | null>(null);
  const [optimization, setOptimization] = useState<Optimization | null>(null);
  const active = useRef<AbortController | null>(null);
  const version = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      request<Champion[]>(apiBase, "champions", controller.signal),
      request<Item[]>(apiBase, "items", controller.signal),
      request<Item[]>(apiBase, "boots", controller.signal),
      request<Config>(apiBase, "config", controller.signal),
    ])
      .then(([champions, items, boots, config]) => {
        if (controller.signal.aborted) return;
        setCatalog({ champions, items, boots, config });
        setDuration(config.fight_defaults.duration_seconds);
        setTargetStats(config.default_target);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setLoadError(e.message);
      });
    return () => controller.abort();
  }, [apiBase, loadVersion]);
  const inputKey = JSON.stringify({
    apiBase,
    questComplete,
    champion,
    level,
    target,
    targetLevel,
    targetRanks,
    targetBuild,
    targetStats,
    targetItems,
    role,
    builds,
    compare,
    duration,
    championOptions,
    ranks,
    autos,
    enemyAttack,
    budgets,
  });
  const [previousInputKey, setPreviousInputKey] = useState(inputKey);
  if (previousInputKey !== inputKey) {
    setPreviousInputKey(inputKey);
    setBusy(false);
    setError("");
    setOptimization(null);
  }
  useEffect(() => {
    version.current++;
    active.current?.abort();
  }, [inputKey]);
  useEffect(() => () => active.current?.abort(), []);
  const stale = resultKey !== inputKey;
  const config = catalog?.config;
  const roleRules = config?.domain_contract.role_quest;
  const roleValue = (key: "level_cap" | "inventory_capacity" | "boots_tier") =>
    roleRules?.[key].by_role[role]?.[
      questComplete ? "complete" : "incomplete"
    ] ?? roleRules?.[key].default;
  const levelCap = roleValue("level_cap");
  const capacity = roleValue("inventory_capacity");
  const ordinarySlots = (build: Build) =>
    Math.min(6, (capacity ?? 6) - (build.boots ? 1 : 0));
  const chosen = catalog?.champions.find((c) => c.name === champion);
  const targetChampion = catalog?.champions.find((c) => c.name === target);
  const itemByName = (name: string | null) =>
    catalog?.items.find((i) => i.name === name) ??
    catalog?.boots.find((i) => i.name === name);
  const editBuild = (index: number, change: Partial<Build>) =>
    setBuilds(
      (previous) =>
        previous.map((build, i) =>
          i === index ? { ...build, ...change } : build,
        ) as [Build, Build],
    );
  const setItem = (side: number, slot: number, name: string | null) => {
    const items = [...builds[side].items];
    items[slot] = name;
    editBuild(side, { items });
  };
  const open = (
    kind: NonNullable<typeof picker>["kind"],
    side?: number,
    slot?: number,
  ) => setPicker({ kind, side, slot });
  function payload(build: Build) {
    return {
      champion,
      level,
      role,
      role_quest_complete: questComplete,
      items: build.items.filter(Boolean),
      boots: build.boots,
      include_boots: Boolean(build.boots),
      keystone: build.keystone,
      minor_runes: build.minor_runes,
      stat_shards: build.stat_shards,
      item_options: Object.fromEntries(
        Object.entries(build.item_options).filter(
          ([name]) => build.items.includes(name) || name === build.boots,
        ),
      ),
      rune_options: Object.fromEntries(
        Object.entries(build.rune_options).filter(
          ([name]) =>
            name === build.keystone || build.minor_runes.includes(name),
        ),
      ),
      keystone_options: build.keystone_options,
      champion_options: championOptions,
      ability_ranks: ranks,
      fight_mode: "time_based",
      fight_duration: duration,
      include_auto_attacks: autos,
      auto_attack_uptime_mode: "calculated",
      auto_attack_uptime: 0,
      enemies_attack: enemyAttack,
      include_actives: true,
      deterministic: true,
      ...(target
        ? {
            enemies: [
              {
                kind: "champion",
                champion: target,
                level: targetLevel,
                items: targetItems.filter(Boolean),
                boots: targetBuild.boots,
                include_boots: Boolean(targetBuild.boots),
                ability_ranks: targetRanks,
                keystone: targetBuild.keystone,
                minor_runes: targetBuild.minor_runes,
                stat_shards: targetBuild.stat_shards,
                rune_options: targetBuild.rune_options,
              },
            ],
          }
        : {
            target_health: targetStats.health,
            target_bonus_health: targetStats.bonus_health,
            target_armor: targetStats.armor,
            target_mr: targetStats.mr,
          }),
    };
  }
  function statsBody(
    name: string,
    atLevel: number,
    build: Build,
    targetSide = false,
  ) {
    return name
      ? {
          champion: name,
          level: atLevel,
          items: (targetSide ? targetItems : build.items).filter(Boolean),
          boots: build.boots,
          include_boots: Boolean(build.boots),
          role: targetSide ? "" : role,
          role_quest_complete: targetSide ? false : questComplete,
          keystone: build.keystone,
          minor_runes: build.minor_runes,
          stat_shards: build.stat_shards,
          rune_options: build.rune_options,
          item_options: build.item_options,
          champion_options: targetSide ? {} : championOptions,
        }
      : null;
  }
  const ownHudStats = useLoadoutStats(
    apiBase,
    statsBody(champion, level, builds[hudSide]),
  );
  const enemyHudStats = useLoadoutStats(
    apiBase,
    statsBody(target, targetLevel, targetBuild, true),
  );
  const defaultRanks = (selected: Champion | undefined, atLevel: number) =>
    selected?.rank_defaults_by_level?.[String(atLevel)] ?? null;
  const rankCapsAtLevel = (atLevel: number) => ({
    Q: Math.min(5, Math.ceil(atLevel / 2)),
    W: Math.min(5, Math.ceil(atLevel / 2)),
    E: Math.min(5, Math.ceil(atLevel / 2)),
    R: atLevel >= 16 ? 3 : atLevel >= 11 ? 2 : atLevel >= 6 ? 1 : 0,
  });
  async function calculate() {
    if (!chosen?.engine_registration || !catalog) return;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const current = ++version.current;
    setBusy(true);
    setError("");
    setOptimization(null);
    try {
      const response = compare
        ? await request<{ results: Result[] }>(
            apiBase,
            "compare",
            controller.signal,
            { builds: builds.map(payload) },
          )
        : {
            results: [
              await request<Result>(
                apiBase,
                "calculate",
                controller.signal,
                payload(builds[0]),
              ),
            ],
          };
      if (controller.signal.aborted || current !== version.current) return;
      if (
        !Array.isArray(response.results) ||
        response.results.some((result) => result.error)
      )
        throw new Error(
          response.results?.find((result) => result.error)?.error ??
            "The engine returned an incomplete result.",
        );
      setResults(response.results);
      setResultKey(inputKey);
    } catch (e) {
      if (!controller.signal.aborted)
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (current === version.current) setBusy(false);
    }
  }
  async function optimize(side: number) {
    if (!champion) return;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const current = ++version.current;
    setBusy(true);
    setError("");
    try {
      const response = await request<Optimization>(
        apiBase,
        "optimize",
        controller.signal,
        {
          ...payload(builds[side]),
          objective: "total_damage",
          locked_items: builds[side].items.filter(Boolean),
          locked_boots: builds[side].boots,
          max_legendary_slots: ordinarySlots(builds[side]),
          ...(budgets[side] === ""
            ? {}
            : { gold_budget: Number(budgets[side]) }),
        },
      );
      if (!controller.signal.aborted && current === version.current)
        setOptimization(response);
    } catch (e) {
      if (!controller.signal.aborted)
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (current === version.current) setBusy(false);
    }
  }
  function pickerEntries() {
    if (!picker || !catalog) return [];
    if (picker.kind === "champion" || picker.kind === "target")
      return catalog.champions.map((c) => ({
        ...c,
        disabled: picker.kind === "champion" && !c.engine_registration,
        detail: !c.engine_registration ? "Attacker unavailable" : undefined,
      }));
    const entries =
      picker.kind === "boots"
        ? catalog.boots.filter(
            (item) =>
              item.tier <=
              (picker.side === 2 ? 2 : (roleValue("boots_tier") ?? 2)),
          )
        : catalog.items;
    return entries.map((item) => ({
      ...item,
      stats: item,
      detail: [
        `${format(item.price)} gold`,
        item.ap ? `${format(item.ap)} AP` : "",
        item.ad ? `${format(item.ad)} AD` : "",
        item.hp ? `${format(item.hp)} health` : "",
      ]
        .filter(Boolean)
        .join(" · "),
    }));
  }
  const spendFor = (names: (string | null)[]) =>
    names.reduce((sum, name) => sum + (itemByName(name)?.price ?? 0), 0);
  const shopIndex = picker?.kind === "targetItem" ? 2 : (picker?.side ?? 0);
  const shopBuild =
    shopIndex === 2
      ? { ...targetBuild, items: targetItems }
      : builds[shopIndex];
  const shopCapacity = shopIndex === 2 ? 6 : (capacity ?? 6);
  const shopOrdinarySlots = Math.min(
    6,
    shopCapacity - (shopBuild.boots ? 1 : 0),
  );
  const shopSpend =
    shopIndex === 2
      ? spendFor([...targetItems, targetBuild.boots])
      : spendFor([...shopBuild.items, shopBuild.boots]);
  const replacingName =
    (picker?.kind === "boots"
      ? shopBuild.boots
      : picker?.kind === "targetItem"
        ? targetItems[picker.slot ?? 0]
        : shopBuild.items[picker?.slot ?? 0]) ?? null;
  const shopSlotAvailable =
    picker?.kind === "boots"
      ? !shopBuild.items[5] || shopCapacity >= 7
      : (picker?.slot ?? -1) >= 0 && (picker?.slot ?? 0) < shopOrdinarySlots;
  const shopSlots = shopBuild.items
    .slice(0, shopOrdinarySlots)
    .map((name, index) => ({
      name,
      index,
      label: `Item ${index + 1}`,
      active: picker?.kind !== "boots" && picker?.slot === index,
    }));
  const shopInventory: ShopState["inventory"] = [
    ...shopSlots,
    {
      name: shopBuild.boots || null,
      index: -1,
      label: "Boots",
      boots: true,
      active: picker?.kind === "boots",
    },
  ];
  function changeShopTab(boots: boolean) {
    if (boots) setPicker({ kind: "boots", side: shopIndex });
    else {
      const slots = shopBuild.items.slice(0, shopOrdinarySlots);
      setPicker({
        kind: shopIndex === 2 ? "targetItem" : "item",
        side: shopIndex,
        slot: slots.findIndex((name) => !name),
      });
    }
  }
  function clearShopSlot() {
    if (!picker) return;
    if (picker.kind === "boots") {
      if (shopIndex === 2)
        setTargetBuild((current) => ({ ...current, boots: "" }));
      else editBuild(shopIndex, { boots: "" });
    } else if (shopIndex === 2)
      setTargetItems((current) =>
        current.map((name, index) => (index === picker.slot ? null : name)),
      );
    else if ((picker.slot ?? -1) >= 0) setItem(shopIndex, picker.slot!, null);
  }
  function pick(name: string) {
    if (!picker) return;
    if (picker.kind === "champion") {
      setChampion(name);
      setChampionOptions({});
      setRanks(null);
      setPicker(null);
    } else if (picker.kind === "target") {
      setTarget(name);
      setTargetRanks(null);
      setPicker(null);
    } else if (picker.kind === "boots") {
      if (!shopSlotAvailable) return;
      if (shopIndex === 2)
        setTargetBuild((current) => ({ ...current, boots: name }));
      else editBuild(shopIndex, { boots: name });
      const slots = shopBuild.items.slice(0, Math.min(6, shopCapacity - 1));
      setPicker({
        kind: shopIndex === 2 ? "targetItem" : "item",
        side: shopIndex,
        slot: slots.findIndex((item) => !item),
      });
    } else {
      if ((picker.slot ?? -1) < 0) return;
      const current =
        picker.kind === "targetItem" ? targetItems : shopBuild.items;
      const items = current.map((item, index) =>
        index === picker.slot ? name : item,
      );
      if (picker.kind === "targetItem") setTargetItems(items);
      else editBuild(shopIndex, { items });
      const limit = shopOrdinarySlots;
      setPicker({
        ...picker,
        slot: items.slice(0, limit).findIndex((item) => !item),
      });
    }
  }
  const itemSlot = (
    name: string | null,
    index: number,
    side: number,
    targetSlot = false,
  ) => {
    const item = itemByName(name);
    return (
      <div
        className={`calculator-item-slot ${name ? "calculator-item-filled" : ""}`}
        key={index}
      >
        <button
          type="button"
          onClick={() => open(targetSlot ? "targetItem" : "item", side, index)}
          aria-label={`${name ? "Replace " + name : "Choose item " + (index + 1)} for ${targetSlot ? "target" : "build " + (side === 0 ? "A" : "B")}`}
        >
          {item ? (
            <img src={item.icon} alt="" />
          ) : (
            <span className="calculator-slot-plus">+</span>
          )}
          <span>{name ?? `Item ${index + 1}`}</span>
        </button>
        {name && (
          <button
            type="button"
            className="calculator-clear"
            aria-label={`Clear ${name} from ${targetSlot ? "target" : "build " + (side === 0 ? "A" : "B")}`}
            onClick={() => {
              if (targetSlot) {
                const next = [...targetItems];
                next[index] = null;
                setTargetItems(next);
              } else setItem(side, index, null);
            }}
          >
            ×
          </button>
        )}
      </div>
    );
  };
  return (
    <div className={`calculator-root ${className}`}>
      <header className="calculator-intro">
        <div>
          <p className="calculator-eyebrow">
            League of Legends · Build research
          </p>
          <h1>Combat calculator</h1>
          <p>Compare items in the same fight.</p>
        </div>
        <div className="calculator-patch">
          {config?.data_snapshot.patch.public ? (
            <>
              Patch <strong>{config.data_snapshot.patch.public}</strong>
            </>
          ) : (
            "Loading patch…"
          )}
        </div>
      </header>
      {loadError ? (
        <div className="calculator-notice" role="alert">
          <p>{loadError}</p>
          <button
            type="button"
            onClick={() => {
              setLoadError("");
              setLoadVersion((v) => v + 1);
            }}
          >
            Retry connection
          </button>
        </div>
      ) : !catalog ? (
        <div className="calculator-loading" role="status">
          Loading champions and items…
        </div>
      ) : (
        <>
          <section className="calculator-hud-matchup" aria-label="Matchup">
            <div
              className="calculator-hud-build-switch"
              role="group"
              aria-label="Displayed build"
            >
              <button
                type="button"
                aria-pressed={hudSide === 0}
                onClick={() => setHudSide(0)}
              >
                Your build A
              </button>
              {compare && (
                <button
                  type="button"
                  aria-pressed={hudSide === 1}
                  onClick={() => setHudSide(1)}
                >
                  Your build B
                </button>
              )}
            </div>
            <ChampionHud
              champion={chosen}
              label={`Your champion · build ${hudSide === 0 ? "A" : "B"}`}
              level={level}
              maxLevel={levelCap ?? 18}
              onLevel={(value) => {
                setRanks(
                  value > level &&
                    config?.domain_contract.rank_allocation.by_champion[
                      champion
                    ] !== "level_derived"
                    ? (ranks ?? defaultRanks(chosen, level))
                    : null,
                );
                setLevel(value);
              }}
              onChampion={() => open("champion")}
              ranks={ranks}
              defaultRanks={defaultRanks(chosen, level) ?? undefined}
              onRanks={setRanks}
              rankCaps={rankCapsAtLevel(level)}
              ranksDerived={
                config?.domain_contract.rank_allocation.by_champion[
                  champion
                ] === "level_derived"
              }
              {...ownHudStats}
              items={[
                ...builds[hudSide].items.slice(
                  0,
                  ordinarySlots(builds[hudSide]),
                ),
                ...(builds[hudSide].boots ? [builds[hudSide].boots] : []),
              ].map(itemByName)}
              onItem={(index) =>
                builds[hudSide].boots && index >= ordinarySlots(builds[hudSide])
                  ? open("boots", hudSide)
                  : open("item", hudSide, index)
              }
              onShop={() =>
                open(
                  "item",
                  hudSide,
                  Math.max(
                    0,
                    builds[hudSide].items.findIndex((name) => !name),
                  ),
                )
              }
              onRunes={() => setRuneSide(hudSide)}
              gold={
                budgets[hudSide] === ""
                  ? "Open shop · BIS"
                  : `${format(Number(budgets[hudSide]) - spendFor([...builds[hudSide].items, builds[hudSide].boots]))} gold · BIS`
              }
              resourceLabel={chosen?.resource}
            />
            <ChampionHud
              champion={targetChampion}
              label="Enemy champion"
              level={targetLevel}
              maxLevel={18}
              onLevel={(value) => {
                setTargetRanks(
                  value > targetLevel &&
                    config?.domain_contract.rank_allocation.by_champion[
                      target
                    ] !== "level_derived"
                    ? (targetRanks ?? defaultRanks(targetChampion, targetLevel))
                    : null,
                );
                setTargetLevel(value);
              }}
              onChampion={() => open("target")}
              ranks={targetRanks}
              defaultRanks={
                defaultRanks(targetChampion, targetLevel) ?? undefined
              }
              onRanks={setTargetRanks}
              rankCaps={rankCapsAtLevel(targetLevel)}
              ranksDerived={
                config?.domain_contract.rank_allocation.by_champion[target] ===
                "level_derived"
              }
              stats={
                target
                  ? enemyHudStats.stats
                  : {
                      health: targetStats.health,
                      armor: targetStats.armor,
                      magic_resistance: targetStats.mr,
                    }
              }
              loading={enemyHudStats.loading}
              error={enemyHudStats.error}
              items={[
                ...targetItems.slice(0, targetBuild.boots ? 5 : 6),
                ...(targetBuild.boots ? [targetBuild.boots] : []),
              ].map(itemByName)}
              onItem={(index) =>
                targetBuild.boots && index === 5
                  ? open("boots", 2)
                  : open("targetItem", 2, index)
              }
              onShop={() =>
                open(
                  "targetItem",
                  2,
                  Math.max(
                    0,
                    targetItems.findIndex((name) => !name),
                  ),
                )
              }
              onRunes={target ? () => setRuneSide(2) : undefined}
              gold="Enemy items"
              resourceLabel={targetChampion?.resource}
            />
            {target && (
              <button
                type="button"
                className="calculator-text-button"
                onClick={() => {
                  setTarget("");
                  setTargetItems(Array(6).fill(null));
                  setTargetRanks(null);
                }}
              >
                Use practice target
              </button>
            )}
            {!target && (
              <div className="calculator-practice-controls">
                {Object.entries(targetStats).map(([key, value]) => (
                  <label className="calculator-field" key={key}>
                    <span>
                      Target {key === "mr" ? "magic resistance" : label(key)}
                    </span>
                    <input
                      type="number"
                      min={config?.input_limits[`target_${key}`]?.[0]}
                      max={config?.input_limits[`target_${key}`]?.[1]}
                      value={value}
                      onChange={(event) =>
                        setTargetStats({
                          ...targetStats,
                          [key]: Number(event.target.value),
                        })
                      }
                    />
                  </label>
                ))}
              </div>
            )}
          </section>
          <div className="calculator-build-toolbar">
            <h2>Loadout</h2>
            <label className="calculator-check">
              <input
                type="checkbox"
                checked={compare}
                onChange={(e) => {
                  setCompare(e.target.checked);
                  if (!e.target.checked) setHudSide(0);
                }}
              />
              Compare two builds
            </label>
          </div>
          <details className="calculator-details calculator-loadout-drawer">
            <summary>Build settings</summary>
            <div
              className={`calculator-builds ${compare ? "" : "calculator-single"}`}
            >
              {builds.slice(0, compare ? 2 : 1).map((build, side) => (
                <section
                  className="calculator-build-card"
                  key={side}
                  aria-label={`Build ${side === 0 ? "A" : "B"}`}
                >
                  <div className="calculator-card-heading">
                    <div className="calculator-build-title">
                      <span>{side === 0 ? "A" : "B"}</span>
                      <h3>
                        {side === 0 ? "First build" : "Alternative build"}
                      </h3>
                      <button
                        type="button"
                        className="calculator-text-button"
                        onClick={() => setRuneSide(side)}
                      >
                        Runes
                      </button>
                    </div>
                    <button
                      type="button"
                      className="calculator-text-button"
                      onClick={() => editBuild(side, emptyBuild())}
                    >
                      Clear build
                    </button>
                  </div>
                  <div className="calculator-build-cost">
                    <span>
                      Selected items:{" "}
                      <strong>
                        {format(spendFor([...build.items, build.boots]))} gold
                      </strong>
                    </span>
                    {budgets[side] !== "" && (
                      <span>
                        Remaining budget:{" "}
                        <strong>
                          {format(
                            Number(budgets[side]) -
                              spendFor([...build.items, build.boots]),
                          )}{" "}
                          gold
                        </strong>
                      </span>
                    )}
                  </div>
                  <div className="calculator-slots">
                    {build.items
                      .slice(
                        0,
                        Math.max(
                          ordinarySlots(build),
                          build.items.reduce(
                            (last, item, index) => (item ? index + 1 : last),
                            0,
                          ),
                        ),
                      )
                      .map((name, index) => itemSlot(name, index, side))}
                    {build.boots && (
                      <div className="calculator-item-slot calculator-item-filled">
                        <button
                          type="button"
                          onClick={() => open("boots", side)}
                          aria-label={`Replace boots for build ${side === 0 ? "A" : "B"}`}
                        >
                          <img src={itemByName(build.boots)?.icon} alt="" />
                          <span>{build.boots}</span>
                        </button>
                        <button
                          type="button"
                          className="calculator-clear"
                          aria-label={`Clear boots from build ${side === 0 ? "A" : "B"}`}
                          onClick={() => editBuild(side, { boots: "" })}
                        >
                          ×
                        </button>
                      </div>
                    )}
                  </div>
                  <div className="calculator-build-footer">
                    <button
                      type="button"
                      className="calculator-text-button"
                      onClick={() => open("boots", side)}
                    >
                      {build.boots ? "Change boots" : "+ Add boots"}
                    </button>
                    {side === 1 && (
                      <button
                        type="button"
                        className="calculator-text-button"
                        onClick={() => editBuild(1, structuredClone(builds[0]))}
                      >
                        Copy build A
                      </button>
                    )}
                  </div>
                  <details className="calculator-details">
                    <summary>Rune effects & item settings</summary>
                    <div className="calculator-detail-content">
                      <button
                        type="button"
                        className="calculator-secondary"
                        onClick={() => setRuneSide(side)}
                      >
                        Edit rune page
                      </button>
                      <p>
                        {build.keystone || "Choose runes"}
                        {build.minor_runes.length
                          ? ` · ${build.minor_runes.join(" · ")}`
                          : ""}
                      </p>
                      <Options
                        options={Object.entries(
                          config?.keystone_options[build.keystone]?.options ??
                            {},
                        ).map(([key, value]) => ({ key, ...value }))}
                        values={build.keystone_options}
                        onChange={(values) =>
                          editBuild(side, { keystone_options: values })
                        }
                      />
                      {[build.keystone, ...build.minor_runes]
                        .filter(Boolean)
                        .map((name) => {
                          const options =
                            config?.runes.find((r) => r.name === name)
                              ?.options ?? [];
                          return options.length ? (
                            <div key={name}>
                              <h4>{name}</h4>
                              <Options
                                options={options}
                                values={build.rune_options[name] ?? {}}
                                onChange={(values) =>
                                  editBuild(side, {
                                    rune_options: {
                                      ...build.rune_options,
                                      [name]: values,
                                    },
                                  })
                                }
                              />
                            </div>
                          ) : null;
                        })}
                      {[...build.items, build.boots]
                        .filter((n): n is string => Boolean(n))
                        .map((name) => {
                          const opts = config?.item_options[name]?.options;
                          if (!opts) return null;
                          return (
                            <div key={name}>
                              <h4>{name}</h4>
                              <Options
                                options={Object.entries(opts).map(
                                  ([key, value]) => ({ key, ...value }),
                                )}
                                values={build.item_options[name] ?? {}}
                                onChange={(values) =>
                                  editBuild(side, {
                                    item_options: {
                                      ...build.item_options,
                                      [name]: values,
                                    },
                                  })
                                }
                              />
                            </div>
                          );
                        })}
                    </div>
                  </details>
                </section>
              ))}
            </div>
          </details>
          <section className="calculator-fight-bar" aria-label="Fight controls">
            <label className="calculator-duration">
              <span>Fight length</span>
              <input
                type="range"
                min={config?.input_limits.fight_duration[0]}
                max={config?.input_limits.fight_duration[1]}
                step={1}
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
              />
              <output>{duration}s</output>
            </label>
            <button
              type="button"
              className="calculator-primary"
              disabled={!chosen?.engine_registration || busy}
              onClick={calculate}
            >
              {busy
                ? "Calculating…"
                : compare
                  ? "Compare builds"
                  : "Calculate damage"}
              <span aria-hidden="true">↗</span>
            </button>
          </section>
          <details className="calculator-details calculator-settings">
            <summary>Fight settings & champion options</summary>
            <div className="calculator-detail-content">
              <div className="calculator-options">
                <label className="calculator-field">
                  <span>Role</span>
                  <select
                    value={role}
                    onChange={(e) => {
                      setRole(e.target.value);
                      const cap =
                        roleRules?.level_cap.by_role[e.target.value]?.[
                          questComplete ? "complete" : "incomplete"
                        ] ?? roleRules?.level_cap.default;
                      if (cap && level > cap) setLevel(cap);
                    }}
                  >
                    <option value="">No role selected</option>
                    {(roleRules?.roles ?? []).map((r) => (
                      <option key={r} value={r}>
                        {label(r)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="calculator-check">
                  <input
                    type="checkbox"
                    disabled={!role}
                    checked={questComplete}
                    onChange={(e) => {
                      setQuestComplete(e.target.checked);
                      const cap =
                        roleRules?.level_cap.by_role[role]?.[
                          e.target.checked ? "complete" : "incomplete"
                        ];
                      if (cap && level > cap) setLevel(cap);
                    }}
                  />
                  Role quest complete
                </label>
                <label className="calculator-check">
                  <input
                    type="checkbox"
                    checked={autos}
                    onChange={(e) => setAutos(e.target.checked)}
                  />
                  Include basic attacks
                </label>
                <label className="calculator-check">
                  <input
                    type="checkbox"
                    checked={enemyAttack}
                    onChange={(e) => setEnemyAttack(e.target.checked)}
                  />
                  Target attacks back
                </label>
              </div>
              {!target ? (
                <div className="calculator-options">
                  {Object.entries(targetStats).map(([key, value]) => (
                    <label className="calculator-field" key={key}>
                      <span>
                        Target {key === "mr" ? "magic resistance" : label(key)}
                      </span>
                      <input
                        type="number"
                        min={config?.input_limits[`target_${key}`]?.[0]}
                        max={config?.input_limits[`target_${key}`]?.[1]}
                        value={value}
                        onChange={(e) =>
                          setTargetStats({
                            ...targetStats,
                            [key]: Number(e.target.value),
                          })
                        }
                      />
                    </label>
                  ))}
                </div>
              ) : (
                <>
                  <h4>Target items</h4>
                  <div className="calculator-slots calculator-target-slots">
                    {targetItems.map((name, index) =>
                      itemSlot(name, index, 0, true),
                    )}
                  </div>
                </>
              )}
              {champion && (
                <>
                  <h4>{champion} options</h4>
                  <Options
                    options={config?.champion_options[champion]?.options ?? []}
                    values={championOptions}
                    onChange={setChampionOptions}
                  />
                  <details className="calculator-details">
                    <summary>Champion assumptions & sources</summary>
                    <div className="calculator-detail-content">
                      {config?.champion_options[champion]?.assumptions.map(
                        (text, index) => (
                          <p key={index}>{text}</p>
                        ),
                      )}
                      {config?.champion_options[champion]?.sources.map(
                        (source, index) => (
                          <p key={index}>
                            {source.url ? (
                              <a
                                href={source.url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                {source.label}
                              </a>
                            ) : (
                              source.label
                            )}
                            {source.revision_id
                              ? ` · revision ${source.revision_id}`
                              : ""}
                          </p>
                        ),
                      )}
                    </div>
                  </details>
                </>
              )}
            </div>
          </details>
          {error && (
            <div className="calculator-notice" role="alert">
              <strong>Calculation unavailable</strong>
              <p>{error}</p>
            </div>
          )}
          <div className="calculator-results-heading">
            <h2>Results</h2>
            <span role="status">
              {busy
                ? "Waiting for the engine…"
                : results.length
                  ? error
                    ? "Previous result. Resolve the error, then calculate."
                    : stale
                      ? "Inputs changed. Calculate to update."
                      : "Calculation complete"
                  : "Choose a champion, then calculate."}
            </span>
          </div>
          {results.length ? (
            <div
              className={`calculator-results ${results.length === 1 ? "calculator-single" : ""}`}
              aria-busy={busy}
            >
              {results.map((result, index) => (
                <ResultCard
                  key={index}
                  result={result}
                  side={index === 0 ? "A" : "B"}
                  stale={stale || Boolean(error)}
                />
              ))}
            </div>
          ) : (
            <div className="calculator-results-empty">
              <span aria-hidden="true">↗</span>
              <div>
                <h3>Your builds, in one fight.</h3>
                <p>
                  Damage, healing, and each ability’s contribution appear here
                  after calculation.
                </p>
              </div>
            </div>
          )}
          <footer className="calculator-footer">
            <span>
              Calculated from the selected fight. Champion assumptions apply.
            </span>
            {advancedHref && (
              <a href={advancedHref}>Open full fight controls ↗</a>
            )}
          </footer>
          {runeSide !== null && config && (
            <RunePage
              config={config}
              build={runeSide === 2 ? targetBuild : builds[runeSide]}
              onChange={(change) =>
                runeSide === 2
                  ? setTargetBuild((current) => ({ ...current, ...change }))
                  : editBuild(runeSide, change)
              }
              onClose={() => setRuneSide(null)}
            />
          )}
          {picker &&
            (picker.kind === "champion" || picker.kind === "target" ? (
              <Picker
                title={
                  picker.kind === "champion"
                    ? "Choose your champion"
                    : "Choose target"
                }
                entries={pickerEntries()}
                onPick={pick}
                onClose={() => setPicker(null)}
              />
            ) : (
              <ItemShop
                items={pickerEntries() as Item[]}
                onPick={pick}
                onClose={() => setPicker(null)}
                shop={{
                  selectedName: shopSelection,
                  onSelect: setShopSelection,
                  budget: budgets[shopIndex],
                  spend: shopSpend,
                  replacement: itemByName(replacingName)?.price ?? 0,
                  replacingName,
                  label:
                    shopIndex === 2
                      ? "Target"
                      : `Build ${shopIndex === 0 ? "A" : "B"}`,
                  boots: picker.kind === "boots",
                  slotAvailable: shopSlotAvailable,
                  catalogue: [
                    ...(catalog?.items ?? []),
                    ...(catalog?.boots ?? []),
                  ],
                  quickBoots: (catalog?.boots ?? []).filter(
                    (item) =>
                      item.tier <=
                      (shopIndex === 2 ? 2 : (roleValue("boots_tier") ?? 2)),
                  ),
                  inventory: shopInventory,
                  onBudget: (value) =>
                    setBudgets((current) =>
                      current.map((budget, index) =>
                        index === shopIndex ? value : budget,
                      ),
                    ),
                  onSlot: (index, boots) =>
                    setPicker({
                      kind: boots
                        ? "boots"
                        : shopIndex === 2
                          ? "targetItem"
                          : "item",
                      side: shopIndex,
                      slot: index,
                    }),
                  onClear: clearShopSlot,
                  onTab: changeShopTab,
                  optimizer:
                    shopIndex < 2 ? (
                      <>
                        <h3>
                          Find items for build {shopIndex === 0 ? "A" : "B"}
                        </h3>
                        <p>
                          Your selected items stay locked. Search fills the open
                          slots within the total budget.
                        </p>
                        <button
                          type="button"
                          className="calculator-primary"
                          disabled={!chosen?.engine_registration || busy}
                          onClick={() => optimize(shopIndex)}
                        >
                          {busy ? "Searching…" : "Find best items"}
                        </button>
                        {!chosen && (
                          <p>Select your champion before searching.</p>
                        )}
                        {error && <p role="alert">{error}</p>}
                        {optimization && (
                          <div role="status">
                            <h4>
                              {optimization.is_certified_best
                                ? "Certified result"
                                : "Candidate build"}
                            </h4>
                            <p>
                              {[
                                ...(optimization.items ?? []),
                                optimization.boots,
                              ]
                                .filter(Boolean)
                                .join(" · ")}
                            </p>
                            <p>
                              {format(optimization.total_damage)} damage in this
                              fight.
                            </p>
                            {!optimization.is_certified_best && (
                              <p>
                                BIS remains unconfirmed.{" "}
                                {optimization.search_guarantee ===
                                "local_search"
                                  ? "The search sampled builds; it did not test every combination."
                                  : "Some candidates could not be compared with complete timing."}
                              </p>
                            )}
                            <p>{optimization.search_timeline_coverage?.note}</p>
                            {optimization.timeline_coverage?.complete && (
                              <button
                                type="button"
                                className="calculator-secondary"
                                onClick={() =>
                                  editBuild(shopIndex, {
                                    items: [
                                      ...(optimization.items ?? []),
                                      ...Array(6).fill(null),
                                    ].slice(0, 6),
                                    boots: optimization.boots ?? "",
                                  })
                                }
                              >
                                {optimization.is_certified_best
                                  ? "Apply result"
                                  : "Use candidate build"}
                              </button>
                            )}
                            <details>
                              <summary>Search details</summary>
                              <p>
                                {format(optimization.evaluations)} evaluations
                              </p>
                              <p>{optimization.timeline_coverage?.note}</p>
                              {optimization.search_timeline_coverage?.coarse_sources?.map(
                                (source) => (
                                  <p key={source}>{source}</p>
                                ),
                              )}
                            </details>
                          </div>
                        )}
                      </>
                    ) : undefined,
                }}
              />
            ))}
        </>
      )}
    </div>
  );
}
export default Calculator;
