"use client";

import { useEffect, useRef, useState, useId, type ReactNode } from "react";
import { Options } from "./Options";
import { ChampionHud } from "./ChampionHud";
import { RunePage } from "./RunePage";
import { GameTooltip } from "./Tooltip";
import "./rune-page.css";
import {
  parseScenario,
  encodeScenario,
  decodeScenario,
  type SavedScenario,
} from "./scenario-storage";
import { SupportTargets } from "./SupportTargets";
import { EventEditor } from "./EventEditor";
import { PurchasePlanner } from "./PurchasePlanner";
import { SlotSearch } from "./SlotSearch";
import { CombatResults } from "./CombatResults";
import { Timeline, type ScheduledMark } from "./Timeline";
import { ScoreboardReader } from "./ScoreboardReader";
import {
  newParticipant,
  newBuild,
  zeroRanks,
  domainValue,
  skillCaps,
  reduceRanksForLevel,
  serializeParticipant,
  compactSlotIndex,
  reindexSupportTargets,
  type Participant,
  type AuthoredEvent,
} from "./scenario-state";
import "./roster-workspace.css";
import { useLoadoutStats } from "./useLoadoutStats";
import { request } from "./api";
import { shopGroup, wikiText } from "./shop";
import type { Build, Champion, Config, Item, Result } from "./types";

export interface CalculatorProps {
  apiBase?: string;
  /** Where the scoreboard sprite (`icon-sprite.json`, `.webp`) is served from. */
  assetBase?: string;
  className?: string;
  advancedHref?: string;
}
const format = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value)
    ? new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value)
    : "—";
const label = (value: string) => value.replaceAll("_", " ");
const normalize = (value: string) =>
  value.toLowerCase().replace(/[^a-z0-9]/g, "");

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
          </div>
          {shop.optimizer && (
            <section
              className="calculator-shop-bis"
              aria-label="Rank selected item slot"
            >
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

type StepKey = "teams" | "build" | "fight";
const STEPS: { key: StepKey; title: string }[] = [
  { key: "teams", title: "Teams" },
  { key: "build", title: "Build" },
  { key: "fight", title: "Fight" },
];

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
  assetBase = "/static",
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
  const [main, setMain] = useState(() => newParticipant("main"));
  const [alternative, setAlternative] = useState<Build>(newBuild);
  const [allies, setAllies] = useState<Participant[]>([]);
  const [enemies, setEnemies] = useState<Participant[]>([]);
  const [selectedId, setSelectedId] = useState("main");
  const [side, setSide] = useState(0);
  const [compare, setCompare] = useState(true);
  const [duration, setDuration] = useState(8);
  const [objective, setObjective] = useState("team_outcome");
  const [autosOnly, setAutosOnly] = useState(false);
  const [setupMessage, setSetupMessage] = useState("");
  const setupFile = useRef<HTMLInputElement>(null);
  const [includeActives, setIncludeActives] = useState(true);
  const [enemiesAttack, setEnemiesAttack] = useState(true);
  const [countAfterEnd, setCountAfterEnd] = useState(true);
  const [dummyStats, setDummyStats] = useState<Record<string, number>>({});
  const [useSequence, setUseSequence] = useState(false);
  const [events, setEvents] = useState<AuthoredEvent[]>([]);
  const [selectedEventId, setSelectedEventId] = useState("");
  const [step, setStep] = useState<StepKey>("teams");
  const [budgets, setBudgets] = useState<Record<string, string>>({});
  const [picker, setPicker] = useState<{
    kind: "champion" | "item" | "boots";
    id: string;
    side: number;
    slot: number;
  } | null>(null);
  const [runeOwner, setRuneOwner] = useState<{
    id: string;
    side: number;
  } | null>(null);
  const [shopSelection, setShopSelection] = useState("");
  const [results, setResults] = useState<Result[]>([]);
  const [resultKey, setResultKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef<AbortController | null>(null);
  const requestVersion = useRef(0);
  const setupLoaded = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      request<Champion[]>(apiBase, "champions", controller.signal),
      request<Item[]>(apiBase, "items", controller.signal),
      request<Item[]>(apiBase, "boots", controller.signal),
      request<Config>(apiBase, "config", controller.signal),
    ])
      .then(([champions, items, boots, config]) => {
        if (!controller.signal.aborted) {
          setCatalog({ champions, items, boots, config });
          if (!setupLoaded.current) {
            setDuration(config.fight_defaults.duration_seconds);
            setDummyStats(config.default_target);
          }
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setLoadError(e.message);
      });
    return () => controller.abort();
  }, [apiBase, loadVersion]);
  const participants = [main, ...allies, ...enemies];
  const selected =
    participants.find((actor) => actor.id === selectedId) ?? main;
  const config = catalog?.config;
  const rankRules = (actor: Participant) =>
    config?.domain_contract.rank_allocation.rules_by_champion?.[
      actor.champion
    ] ?? config?.domain_contract.rank_allocation.default_rules;
  const championFor = (actor: Participant) =>
    catalog?.champions.find((champion) => champion.name === actor.champion);
  const itemFor = (name: string | null) =>
    catalog?.items.find((item) => item.name === name) ??
    catalog?.boots.find((item) => item.name === name);
  const getBuild = (actor: Participant, buildSide = side) =>
    actor.id === "main" && buildSide === 1 ? alternative : actor.build;
  const selectedBuild = getBuild(selected);
  const participantLabel = (actor: Participant) =>
    actor.id === "main"
      ? "Your champion"
      : allies.some((ally) => ally.id === actor.id)
        ? `Ally ${allies.findIndex((ally) => ally.id === actor.id) + 1}`
        : `Enemy ${enemies.findIndex((enemy) => enemy.id === actor.id) + 1}`;
  function editParticipant(id: string, change: Partial<Participant>) {
    if (change.champion !== undefined) {
      if (id === "main" || allies.some((actor) => actor.id === id)) {
        const previous = [main, ...allies];
        const next = reindexSupportTargets(
          previous,
          previous.map((actor) =>
            actor.id === id ? { ...actor, ...change } : actor,
          ),
        );
        setMain(next[0]);
        setAllies(next.slice(1));
      } else
        setEnemies(
          reindexSupportTargets(
            enemies,
            enemies.map((actor) =>
              actor.id === id ? { ...actor, ...change } : actor,
            ),
          ),
        );
    } else if (id === "main") setMain((current) => ({ ...current, ...change }));
    else if (allies.some((actor) => actor.id === id))
      setAllies((current) =>
        current.map((actor) =>
          actor.id === id ? { ...actor, ...change } : actor,
        ),
      );
    else
      setEnemies((current) =>
        current.map((actor) =>
          actor.id === id ? { ...actor, ...change } : actor,
        ),
      );
  }
  function editBuild(id: string, buildSide: number, change: Partial<Build>) {
    const actor = participants.find((actor) => actor.id === id);
    if (!actor) return;
    if (id === "main" && buildSide === 1)
      setAlternative((current) => ({ ...current, ...change }));
    else editParticipant(id, { build: { ...actor.build, ...change } });
  }
  function editLevel(actor: Participant, level: number) {
    editParticipant(actor.id, {
      level,
      ranks: reduceRanksForLevel(actor.ranks, level, rankRules(actor)),
    });
  }
  function roleChange(
    actor: Participant,
    role: string,
    questComplete = actor.questComplete,
  ) {
    const next = { ...actor, role, questComplete };
    const level = config
      ? Math.min(actor.level, domainValue(config, next, "level_cap"))
      : actor.level;
    editParticipant(actor.id, {
      role,
      questComplete,
      level,
      ranks: reduceRanksForLevel(actor.ranks, level, rankRules(actor)),
    });
  }
  function addParticipant(team: "ally" | "enemy") {
    const actor = newParticipant(crypto.randomUUID());
    if (team === "ally") setAllies((current) => [...current, actor]);
    else setEnemies((current) => [...current, actor]);
    setSelectedId(actor.id);
    setPicker({ kind: "champion", id: actor.id, side: 0, slot: 0 });
  }
  function removeParticipant(id: string) {
    if (allies.some((actor) => actor.id === id)) {
      const previous = [main, ...allies];
      const next = reindexSupportTargets(
        previous,
        previous.filter((actor) => actor.id !== id),
      );
      setMain(next[0]);
      setAllies(next.slice(1));
    } else
      setEnemies(
        reindexSupportTargets(
          enemies,
          enemies.filter((actor) => actor.id !== id),
        ),
      );
    setSetupMessage(
      "Participant removed. Recipient choices for that participant were cleared.",
    );
    setEvents((current) =>
      current.filter(
        (event) => event.caster_id !== id && event.recipient_id !== id,
      ),
    );
    if (selectedId === id) setSelectedId("main");
  }
  const openShop = (actor: Participant, index = 0, boots = false) => {
    setSelectedId(actor.id);
    setShopSelection(
      boots ? getBuild(actor).boots : (getBuild(actor).items[index] ?? ""),
    );
    setPicker({
      kind: boots ? "boots" : "item",
      id: actor.id,
      side: actor.id === "main" ? side : 0,
      slot: index,
    });
  };
  const slotsFor = (actor: Participant, build: Build) =>
    Math.min(
      6,
      (config ? domainValue(config, actor, "inventory_capacity") : 6) -
        (build.boots ? 1 : 0),
    );
  const spend = (build: Build) =>
    [...build.items, build.boots].reduce<number>(
      (sum, name) => sum + (itemFor(name)?.price ?? 0),
      0,
    );
  // Receipt IDs use names and a suffix for duplicates; UI IDs remain stable through edits.
  const runtimeIds = new Map<string, string>([["main", "main"]]);
  for (const [team, roster] of [
    ["ally", allies],
    ["enemy", enemies],
  ] as const) {
    const counts = new Map<string, number>();
    for (const actor of roster.filter((actor) => actor.champion)) {
      const count = (counts.get(actor.champion) ?? 0) + 1;
      counts.set(actor.champion, count);
      runtimeIds.set(
        actor.id,
        `${team}:${actor.champion}${count > 1 ? `:${count}` : ""}`,
      );
    }
  }
  function payload(build: Build) {
    return {
      ...serializeParticipant(main, build),
      fight_mode: autosOnly ? "auto_only" : "time_based",
      fight_duration: duration,
      include_actives: includeActives,
      enemies_attack: enemiesAttack,
      count_damage_after_fight_end: countAfterEnd,
      deterministic: true,
      allies: allies
        .filter((actor) => actor.champion)
        .map((actor) => serializeParticipant(actor)),
      ...(enemies.some((actor) => actor.champion)
        ? {
            enemies: enemies
              .filter((actor) => actor.champion)
              .map((actor) => serializeParticipant(actor)),
          }
        : {
            target_health: dummyStats.health,
            target_bonus_health: dummyStats.bonus_health,
            target_armor: dummyStats.armor,
            target_mr: dummyStats.mr,
          }),
      ...(useSequence
        ? {
            combat_events_mode: "overrides",
            combat_events: events.map((event) => ({
              ...event,
              caster_id: runtimeIds.get(event.caster_id) ?? event.caster_id,
              recipient_id:
                runtimeIds.get(event.recipient_id) ?? event.recipient_id,
            })),
          }
        : {}),
    };
  }
  const eventActors = participants
    .filter((actor) => actor.champion)
    .map((actor) => ({
      id: actor.id,
      label: `${actor.champion} · ${participantLabel(actor)}`,
      team: enemies.some((enemy) => enemy.id === actor.id) ? "enemy" : "ally",
      champion: championFor(actor),
      ranks: actor.ranks,
    }));
  /* The engine's own schedule for the main champion, read off the last
   * result: each cast from cast_timeline and each landed basic attack from
   * damage_events. Other lanes show only authored casts until the engine
   * publishes their schedules. */
  const schedule: ScheduledMark[] = (() => {
    const result = results[0];
    if (!result) return [];
    const casts = (result.cast_timeline ?? []).map((cast) => ({
      actorId: "main",
      time: cast.time,
      kind: "cast" as const,
      label: cast.slot,
    }));
    const autoTimes = new Set<number>();
    for (const row of Array.isArray(result.damage_events)
      ? (result.damage_events as { time?: number; basic_attack?: boolean }[])
      : []) {
      if (row.basic_attack && typeof row.time === "number")
        autoTimes.add(Number(row.time.toFixed(2)));
    }
    return [
      ...casts,
      ...[...autoTimes].map((time) => ({
        actorId: "main",
        time,
        kind: "auto" as const,
        label: "Basic attack",
      })),
    ];
  })();
  const stepHint = (key: StepKey) => {
    const chosen = participants.filter((actor) => actor.champion).length;
    if (key === "teams")
      return chosen
        ? `${chosen} champion${chosen === 1 ? "" : "s"}`
        : "Pick champions";
    if (key === "build") return selected.champion || "Choose a champion";
    return results.length
      ? resultKey !== inputKey
        ? "Inputs changed"
        : "Calculated"
      : `${duration}s fight`;
  };
  const inputKey = JSON.stringify({
    main,
    alternative,
    allies,
    enemies,
    duration,
    autosOnly,
    includeActives,
    enemiesAttack,
    countAfterEnd,
    dummyStats,
    useSequence,
    events,
    compare,
  });
  const [previousInput, setPreviousInput] = useState(inputKey);
  if (previousInput !== inputKey) {
    setPreviousInput(inputKey);
    setBusy(false);
    setError("");
  }
  useEffect(() => {
    active.current?.abort();
    requestVersion.current++;
  }, [inputKey]);
  useEffect(() => () => active.current?.abort(), []);
  function currentSetup(): SavedScenario {
    return {
      version: 1,
      main,
      alternative,
      allies,
      enemies,
      compare,
      duration,
      objective,
      autosOnly,
      includeActives,
      enemiesAttack,
      countAfterEnd,
      dummyStats,
      useSequence,
      events,
      budgets,
    };
  }
  function loadSetup(value: SavedScenario) {
    setupLoaded.current = true;
    setMain(value.main);
    setAlternative(value.alternative);
    setAllies(value.allies);
    setEnemies(value.enemies);
    setCompare(value.compare);
    setDuration(value.duration);
    setObjective(value.objective);
    setAutosOnly(value.autosOnly);
    setIncludeActives(value.includeActives);
    setEnemiesAttack(value.enemiesAttack);
    setCountAfterEnd(value.countAfterEnd ?? true);
    setDummyStats(value.dummyStats);
    setUseSequence(value.useSequence);
    setEvents(value.events);
    setBudgets(value.budgets);
    setSelectedId("main");
    setSide(0);
    setResults([]);
    setSetupMessage("Setup loaded.");
  }
  useEffect(() => {
    const readLink = () => {
      const hash = window.location.hash;
      if (!hash.startsWith("#setup=")) return;
      try {
        loadSetup(decodeScenario(decodeURIComponent(hash.slice(7))));
      } catch (e) {
        setSetupMessage(
          e instanceof Error ? e.message : "The setup link could not be read.",
        );
      }
    };
    // Read the browser URL after hydration and respond to explicitly opened setup links.
    const frame = window.requestAnimationFrame(readLink);
    window.addEventListener("hashchange", readLink);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("hashchange", readLink);
    };
  }, []);
  function downloadSetup() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(currentSetup(), null, 2)], {
        type: "application/json",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "scryglass-fight.json";
    link.click();
    URL.revokeObjectURL(url);
    setSetupMessage("Setup saved.");
  }
  async function copySetupLink() {
    try {
      const url = `${window.location.origin}${window.location.pathname}#setup=${encodeURIComponent(encodeScenario(currentSetup()))}`;
      await navigator.clipboard.writeText(url);
      setSetupMessage("Setup link copied.");
    } catch {
      setSetupMessage(
        "The browser could not copy the link. Save the setup as a file.",
      );
    }
  }
  const hudStats = useLoadoutStats(
    apiBase,
    selected.champion ? serializeParticipant(selected, selectedBuild) : null,
  );
  async function calculate() {
    if (!main.champion) return;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const version = ++requestVersion.current;
    setBusy(true);
    setError("");
    try {
      const response = compare
        ? await request<{ results: Result[] }>(
            apiBase,
            "compare",
            controller.signal,
            { builds: [payload(main.build), payload(alternative)] },
          )
        : {
            results: [
              await request<Result>(
                apiBase,
                "calculate",
                controller.signal,
                payload(main.build),
              ),
            ],
          };
      if (controller.signal.aborted || version !== requestVersion.current)
        return;
      if (
        !Array.isArray(response.results) ||
        response.results.some((result) => result.error)
      )
        throw new Error(
          response.results?.find((result) => result.error)?.error ??
            "The calculation returned an incomplete result.",
        );
      setResults(response.results);
      setResultKey(inputKey);
    } catch (e) {
      if (!controller.signal.aborted)
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (version === requestVersion.current) setBusy(false);
    }
  }
  const shopActor =
    participants.find((actor) => actor.id === picker?.id) ?? selected;
  const shopBuild = getBuild(shopActor, picker?.side ?? 0);
  const shopCapacity = config
    ? domainValue(config, shopActor, "inventory_capacity")
    : 6;
  const shopSlots = slotsFor(shopActor, shopBuild);
  const slotIndex = picker?.slot ?? 0;
  const isBoots = picker?.kind === "boots";
  const replacingName =
    (isBoots ? shopBuild.boots : shopBuild.items[slotIndex]) ?? null;
  const budgetKey = `${shopActor.id}:${picker?.side ?? 0}`;
  const budget = budgets[budgetKey] ?? "";
  const slotAvailable = isBoots
    ? shopBuild.items.filter(Boolean).length < shopCapacity ||
      Boolean(shopBuild.boots)
    : slotIndex >= 0 && slotIndex < shopSlots;
  const shopItems = isBoots
    ? (catalog?.boots ?? []).filter(
        (item) =>
          item.tier <=
          (config ? domainValue(config, shopActor, "boots_tier") : 2),
      )
    : (catalog?.items ?? []);
  function setShopSlot(index: number, boots: boolean) {
    if (picker)
      setPicker({ ...picker, kind: boots ? "boots" : "item", slot: index });
  }
  function equip(name: string | null, advance = true) {
    if (!picker || (!slotAvailable && name !== null)) return;
    const items = [...shopBuild.items];
    if (isBoots) {
      if (name) {
        const limit = Math.min(6, shopCapacity - 1);
        for (let index = limit; index < items.length; index++) {
          if (items[index]) {
            const empty = items.slice(0, limit).findIndex((item) => !item);
            if (empty >= 0) {
              items[empty] = items[index];
              items[index] = null;
            }
          }
        }
      }
      editBuild(shopActor.id, picker.side, { boots: name ?? "", items });
    } else {
      items[slotIndex] = name;
      editBuild(shopActor.id, picker.side, { items });
    }
    if (advance && name) {
      const limit = isBoots ? Math.min(6, shopCapacity - 1) : shopSlots;
      const next = items.slice(0, limit).findIndex((item) => !item);
      if (next >= 0) setPicker({ ...picker, kind: "item", slot: next });
    }
  }
  function pickChampion(name: string) {
    if (!picker) return;
    editParticipant(picker.id, {
      champion: name,
      ranks: {
        ...zeroRanks(),
        ...config?.domain_contract.rank_allocation.rules_by_champion?.[name]
          ?.free_ranks,
      },
      championOptions: {},
    });
    setPicker(null);
  }
  const selectedChampion = championFor(selected);
  const objectives = config?.domain_contract.bis_objectives ?? {
    team_outcome: {
      label: "Team damage advantage",
      description:
        "Selected team's damage before defeat minus the opposing team's damage before defeat.",
    },
  };
  const subjectTeam =
    shopActor.id === "main"
      ? "main"
      : allies.some((actor) => actor.id === shopActor.id)
        ? "ally"
        : "enemy";
  const subjectRoster = subjectTeam === "ally" ? allies : enemies;
  const bisBody = {
    ...payload(side === 1 ? alternative : main.build),
    objective,
    subject_team: subjectTeam,
    subject_index:
      subjectTeam === "main"
        ? 0
        : subjectRoster
            .filter((actor) => actor.champion)
            .findIndex((actor) => actor.id === shopActor.id),
    slot_kind: isBoots ? "boots" : "item",
    slot_index: isBoots ? 0 : compactSlotIndex(shopBuild.items, slotIndex),
    ...(budget === ""
      ? {}
      : {
          max_item_gold: Math.max(
            0,
            Math.floor(
              Number(budget) -
                spend(shopBuild) +
                (itemFor(replacingName)?.price ?? 0),
            ),
          ),
        }),
  };
  const searchReady = !main.champion
    ? "Choose your champion first."
    : !shopActor.champion
      ? "Choose a champion for this participant."
      : !slotAvailable
        ? "Select an available inventory slot."
        : subjectTeam !== "main" && !shopActor.role
          ? "Set this champion's role before ranking items."
          : "";
  function rosterRow(actor: Participant) {
    const build = getBuild(actor);
    const champion = championFor(actor);
    return (
      <div
        className={`calculator-roster-row ${actor.id === selectedId ? "is-selected" : ""}`}
        key={actor.id}
      >
        <button
          type="button"
          className="calculator-roster-identity"
          aria-pressed={actor.id === selectedId}
          onClick={() => {
            setSelectedId(actor.id);
            if (!actor.champion)
              setPicker({ kind: "champion", id: actor.id, side: 0, slot: 0 });
          }}
          aria-label={`Edit ${participantLabel(actor)} ${actor.champion || "empty slot"}`}
        >
          {champion ? (
            <img src={champion.icon} alt="" />
          ) : (
            <span
              className="calculator-roster-empty-portrait"
              aria-hidden="true"
            >
              +
            </span>
          )}
          <span>
            <strong>{actor.champion || "Choose champion"}</strong>
            <small>
              {participantLabel(actor)}
              {actor.champion ? ` · Level ${actor.level}` : ""}
            </small>
          </span>
        </button>
        <div
          className="calculator-roster-inventory"
          aria-label={`${participantLabel(actor)} item slots`}
        >
          {Array.from({ length: slotsFor(actor, build) }, (_, index) => (
            <button
              type="button"
              key={index}
              aria-label={`${participantLabel(actor)} ${actor.champion}: ${build.items[index] ?? `empty item slot ${index + 1}`}`}
              onClick={() => openShop(actor, index)}
            >
              {itemFor(build.items[index]) ? (
                <img src={itemFor(build.items[index])!.icon} alt="" />
              ) : (
                <span>{index + 1}</span>
              )}
            </button>
          ))}
          {build.boots && (
            <button
              type="button"
              aria-label={`${participantLabel(actor)} ${actor.champion}: ${build.boots}`}
              onClick={() => openShop(actor, 0, true)}
            >
              <img src={itemFor(build.boots)?.icon} alt="" />
            </button>
          )}
        </div>
      </div>
    );
  }
  return (
    <div className={`calculator-root calculator-roster-workspace ${className}`}>
      <header className="calculator-intro">
        <div>
          <h1>Combat calculator</h1>
          <p>Build the teams. Set the fight.</p>
        </div>
        <div className="calculator-patch">
          Patch <strong>{config?.data_snapshot.patch.public ?? "…"}</strong>
        </div>
      </header>
      <div className="calculator-setup-actions">
        <button type="button" onClick={downloadSetup} disabled={!catalog}>
          Save setup
        </button>
        <button type="button" onClick={() => setupFile.current?.click()}>
          Load setup
        </button>
        <button type="button" onClick={copySetupLink} disabled={!catalog}>
          Copy setup link
        </button>
        <input
          ref={setupFile}
          type="file"
          accept="application/json,.json"
          className="calculator-sr-only"
          aria-label="Load calculator setup"
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            try {
              if (file.size > 200_000)
                throw new Error("Choose a setup file under 200 KB.");
              loadSetup(parseScenario(await file.text()));
            } catch (e) {
              setSetupMessage(
                e instanceof Error
                  ? e.message
                  : "The setup file could not be read.",
              );
            }
            event.target.value = "";
          }}
        />
        <span role="status">{setupMessage}</span>
      </div>
      {loadError ? (
        <div className="calculator-notice" role="alert">
          <p>{loadError}</p>
          <button
            type="button"
            onClick={() => {
              setLoadError("");
              setLoadVersion((value) => value + 1);
            }}
          >
            Retry connection
          </button>
        </div>
      ) : !catalog ? (
        <div role="status" className="calculator-loading">
          Loading champions and items…
        </div>
      ) : (
        <>
          <nav className="calculator-steps" aria-label="Setup steps">
            {STEPS.map((entry, index) => (
              <button
                type="button"
                key={entry.key}
                aria-current={step === entry.key ? "step" : undefined}
                onClick={() => setStep(entry.key)}
              >
                <span className="calculator-step-number">{index + 1}</span>
                <span className="calculator-step-title">{entry.title}</span>
                <span className="calculator-step-hint">
                  {stepHint(entry.key)}
                </span>
              </button>
            ))}
          </nav>
          <div className="calculator-stage">
            <div className="calculator-stage-main">
              {step === "teams" && (
                <>
                  <section
                    className="calculator-team-rosters"
                    aria-label="Team rosters"
                  >
                    <div className="calculator-scoreboard-trigger">
                      <ScoreboardReader
                        assetBase={assetBase}
                        catalog={catalog}
                        main={main}
                        onLoad={(result) => {
                          setMain(result.main);
                          setAllies(result.allies);
                          setEnemies(result.enemies);
                          setSelectedId("main");
                        }}
                      />
                    </div>
                    <div className="calculator-team">
                      <div className="calculator-section-heading">
                        <h2>
                          Your team <span>{1 + allies.length}/5</span>
                        </h2>
                        <button
                          type="button"
                          className="calculator-text-button"
                          disabled={allies.length >= 4}
                          onClick={() => addParticipant("ally")}
                        >
                          Add ally
                        </button>
                      </div>
                      {rosterRow(main)}
                      {allies.map(rosterRow)}
                      {!allies.length && (
                        <p className="calculator-roster-hint">
                          Add allies to model their damage and support.
                        </p>
                      )}
                    </div>
                    <div className="calculator-team">
                      <div className="calculator-section-heading">
                        <h2>
                          Enemy team <span>{enemies.length}/5</span>
                        </h2>
                        <button
                          type="button"
                          className="calculator-text-button"
                          disabled={enemies.length >= 5}
                          onClick={() => addParticipant("enemy")}
                        >
                          Add enemy
                        </button>
                      </div>
                      {enemies.map(rosterRow)}
                      {!enemies.length && (
                        <div className="calculator-dummy-panel">
                          <strong>Practice target</strong>
                          <div className="calculator-practice-controls">
                            {Object.entries(dummyStats).map(([key, value]) => (
                              <label className="calculator-field" key={key}>
                                <span>
                                  {key === "mr"
                                    ? "Magic resistance"
                                    : label(key)}
                                </span>
                                <input
                                  type="number"
                                  min={
                                    config?.input_limits[`target_${key}`]?.[0]
                                  }
                                  max={
                                    config?.input_limits[`target_${key}`]?.[1]
                                  }
                                  value={value}
                                  onChange={(e) =>
                                    setDummyStats({
                                      ...dummyStats,
                                      [key]: Number(e.target.value),
                                    })
                                  }
                                />
                              </label>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </section>
                  <div className="calculator-step-nav">
                    <button
                      type="button"
                      className="calculator-primary"
                      onClick={() => setStep("build")}
                    >
                      Next · Build
                    </button>
                  </div>
                </>
              )}
              {step === "build" && (
                <>
                  <div
                    className="calculator-participant-strip"
                    role="tablist"
                    aria-label="Participants"
                  >
                    {participants.map((actor) => (
                      <button
                        type="button"
                        role="tab"
                        key={actor.id}
                        aria-selected={actor.id === selectedId}
                        className={`calculator-participant-chip${actor.id === selectedId ? " is-selected" : ""}${enemies.some((enemy) => enemy.id === actor.id) ? " is-enemy" : ""}`}
                        onClick={() => setSelectedId(actor.id)}
                        title={participantLabel(actor)}
                      >
                        {championFor(actor)?.icon ? (
                          <img src={championFor(actor)!.icon} alt="" />
                        ) : (
                          <span aria-hidden="true">+</span>
                        )}
                        <span>{actor.champion || participantLabel(actor)}</span>
                      </button>
                    ))}
                  </div>
                  <section
                    className="calculator-selected-participant"
                    aria-label="Selected participant"
                  >
                    <div className="calculator-participant-toolbar">
                      <div
                        className="calculator-hud-build-switch"
                        role="group"
                        aria-label="Displayed build"
                      >
                        <button
                          type="button"
                          aria-pressed={side === 0}
                          onClick={() => setSide(0)}
                        >
                          Build A
                        </button>
                        {compare && (
                          <button
                            type="button"
                            aria-pressed={side === 1}
                            onClick={() => setSide(1)}
                          >
                            Build B
                          </button>
                        )}
                      </div>
                      <label className="calculator-check">
                        <input
                          type="checkbox"
                          checked={compare}
                          onChange={(e) => {
                            setCompare(e.target.checked);
                            if (!e.target.checked) setSide(0);
                          }}
                        />
                        Compare builds
                      </label>
                      {selected.id !== "main" && (
                        <button
                          type="button"
                          className="calculator-text-button"
                          onClick={() => removeParticipant(selected.id)}
                        >
                          Remove {participantLabel(selected).toLowerCase()}
                        </button>
                      )}
                    </div>
                    <ChampionHud
                      champion={selectedChampion}
                      label={`${participantLabel(selected)}${selected.id === "main" ? ` · build ${side === 0 ? "A" : "B"}` : ""}`}
                      level={selected.level}
                      maxLevel={domainValue(
                        catalog.config,
                        selected,
                        "level_cap",
                      )}
                      onLevel={(value) => editLevel(selected, value)}
                      onChampion={() =>
                        setPicker({
                          kind: "champion",
                          id: selected.id,
                          side: 0,
                          slot: 0,
                        })
                      }
                      ranks={selected.ranks}
                      onRanks={(ranks) =>
                        editParticipant(selected.id, {
                          ranks: ranks ?? zeroRanks(),
                        })
                      }
                      rankCaps={skillCaps(selected.level, rankRules(selected))}
                      minimumRanks={rankRules(selected)?.free_ranks}
                      {...hudStats}
                      items={[
                        ...selectedBuild.items.slice(
                          0,
                          slotsFor(selected, selectedBuild),
                        ),
                        ...(selectedBuild.boots ? [selectedBuild.boots] : []),
                      ].map(itemFor)}
                      onItem={(index) =>
                        openShop(
                          selected,
                          index,
                          index >= slotsFor(selected, selectedBuild),
                        )
                      }
                      onShop={() =>
                        openShop(
                          selected,
                          Math.max(
                            0,
                            selectedBuild.items
                              .slice(0, slotsFor(selected, selectedBuild))
                              .findIndex((item) => !item),
                          ),
                        )
                      }
                      onRunes={() =>
                        setRuneOwner({
                          id: selected.id,
                          side: selected.id === "main" ? side : 0,
                        })
                      }
                      gold="Open item shop"
                      runesLabel={
                        selectedBuild.keystone
                          ? `Runes · ${selectedBuild.keystone}`
                          : "Runes"
                      }
                      resourceLabel={selectedChampion?.resource}
                    />
                    <div className="calculator-participant-actions">
                      <button
                        type="button"
                        className="calculator-secondary"
                        onClick={() => openShop(selected, 0, true)}
                      >
                        {selectedBuild.boots ? "Change boots" : "Choose boots"}
                      </button>
                      {selected.id === "main" && side === 1 && (
                        <button
                          type="button"
                          className="calculator-text-button"
                          onClick={() =>
                            setAlternative(structuredClone(main.build))
                          }
                        >
                          Copy build A
                        </button>
                      )}
                      <span>{format(spend(selectedBuild))} gold in items</span>
                    </div>
                    <div className="calculator-participant-settings">
                      <label className="calculator-field">
                        <span>Role</span>
                        <select
                          aria-label={`${participantLabel(selected)} role`}
                          value={selected.role}
                          onChange={(e) => roleChange(selected, e.target.value)}
                        >
                          <option value="">Choose role</option>
                          {config?.domain_contract.role_quest.roles.map(
                            (role) => (
                              <option key={role} value={role}>
                                {label(role)}
                              </option>
                            ),
                          )}
                        </select>
                      </label>
                      <label className="calculator-check">
                        <input
                          type="checkbox"
                          checked={selected.questComplete}
                          disabled={!selected.role}
                          onChange={(e) =>
                            roleChange(
                              selected,
                              selected.role,
                              e.target.checked,
                            )
                          }
                        />
                        Role quest complete
                      </label>
                      <label className="calculator-check">
                        <input
                          type="checkbox"
                          checked={selected.autos}
                          onChange={(e) =>
                            editParticipant(selected.id, {
                              autos: e.target.checked,
                            })
                          }
                        />
                        Basic attacks
                      </label>
                      <label className="calculator-field">
                        <span>Attack uptime</span>
                        <select
                          value={selected.uptimeMode}
                          onChange={(e) =>
                            editParticipant(selected.id, {
                              uptimeMode: e.target
                                .value as Participant["uptimeMode"],
                            })
                          }
                        >
                          <option value="calculated">Calculated</option>
                          <option value="explicit">Manual</option>
                        </select>
                      </label>
                      {selected.uptimeMode === "explicit" && (
                        <label className="calculator-field">
                          <span>Uptime %</span>
                          <input
                            type="number"
                            min={0}
                            max={100}
                            value={selected.uptime * 100}
                            onChange={(e) =>
                              editParticipant(selected.id, {
                                uptime:
                                  Math.max(
                                    0,
                                    Math.min(100, Number(e.target.value)),
                                  ) / 100,
                              })
                            }
                          />
                        </label>
                      )}
                    </div>
                    {selectedBuild.items
                      .slice(slotsFor(selected, selectedBuild))
                      .some(Boolean) && (
                      <div className="calculator-notice" role="alert">
                        <p>
                          This role and boots leave fewer item slots. Remove the
                          extra items before calculating.
                        </p>
                        {selectedBuild.items.map((name, index) =>
                          name && index >= slotsFor(selected, selectedBuild) ? (
                            <button
                              type="button"
                              key={index}
                              onClick={() =>
                                editBuild(selected.id, side, {
                                  items: selectedBuild.items.map(
                                    (item, itemIndex) =>
                                      itemIndex === index ? null : item,
                                  ),
                                })
                              }
                            >
                              Remove {name}
                            </button>
                          ) : null,
                        )}
                      </div>
                    )}
                    {selected.id !== "main" &&
                      allies.some((actor) => actor.id === selected.id) && (
                        <label className="calculator-check">
                          <input
                            type="checkbox"
                            checked={selected.allyEffectsEnabled}
                            onChange={(event) =>
                              editParticipant(selected.id, {
                                allyEffectsEnabled: event.target.checked,
                              })
                            }
                          />
                          Apply this ally’s support effects
                        </label>
                      )}
                    <details className="calculator-details">
                      <summary>
                        {selected.champion || "Champion"} options and item state
                      </summary>
                      <div className="calculator-detail-content">
                        <Options
                          options={
                            config?.champion_options[selected.champion]
                              ?.options ?? []
                          }
                          values={selected.championOptions}
                          onChange={(championOptions) =>
                            editParticipant(selected.id, { championOptions })
                          }
                        />
                        {[...selectedBuild.items, selectedBuild.boots]
                          .filter((name): name is string => Boolean(name))
                          .map((name) => {
                            const options = config?.item_options[name]?.options;
                            if (!options) return null;
                            return (
                              <div key={name}>
                                <h3>{name}</h3>
                                <Options
                                  options={Object.entries(options).map(
                                    ([key, value]) => ({ key, ...value }),
                                  )}
                                  values={
                                    selectedBuild.item_options[name] ?? {}
                                  }
                                  onChange={(values) =>
                                    editBuild(selected.id, side, {
                                      item_options: {
                                        ...selectedBuild.item_options,
                                        [name]: values,
                                      },
                                    })
                                  }
                                />
                              </div>
                            );
                          })}
                        <Options
                          options={Object.entries(
                            config?.keystone_options[selectedBuild.keystone]
                              ?.options ?? {},
                          ).map(([key, value]) => ({ key, ...value }))}
                          values={selectedBuild.keystone_options}
                          onChange={(values) =>
                            editBuild(selected.id, side, {
                              keystone_options: values,
                            })
                          }
                        />
                        {[selectedBuild.keystone, ...selectedBuild.minor_runes]
                          .filter(Boolean)
                          .map((name) => {
                            const options =
                              config?.runes.find((rune) => rune.name === name)
                                ?.options ?? [];
                            return options.length ? (
                              <div key={name}>
                                <h3>{name}</h3>
                                <Options
                                  options={options}
                                  values={
                                    selectedBuild.rune_options[name] ?? {}
                                  }
                                  onChange={(values) =>
                                    editBuild(selected.id, side, {
                                      rune_options: {
                                        ...selectedBuild.rune_options,
                                        [name]: values,
                                      },
                                    })
                                  }
                                />
                              </div>
                            ) : null;
                          })}
                      </div>
                    </details>
                  </section>
                  {!useSequence && results[0] && (
                    <SupportTargets
                      result={results[0]}
                      actors={participants
                        .filter((actor) => actor.champion)
                        .map((actor) => ({
                          id: actor.id,
                          runtimeId: runtimeIds.get(actor.id)!,
                          name: actor.champion,
                          team: enemies.some((enemy) => enemy.id === actor.id)
                            ? "enemy"
                            : "ally",
                          selections: actor.supportTargets,
                        }))}
                      onChange={(id, key, value) => {
                        const actor = participants.find(
                          (actor) => actor.id === id,
                        )!;
                        editParticipant(id, {
                          supportTargets: {
                            ...actor.supportTargets,
                            [key]: value,
                          },
                        });
                      }}
                    />
                  )}
                  <div className="calculator-step-nav">
                    <button
                      type="button"
                      className="calculator-secondary"
                      onClick={() => setStep("teams")}
                    >
                      Back · Teams
                    </button>
                    <button
                      type="button"
                      className="calculator-primary"
                      onClick={() => setStep("fight")}
                    >
                      Next · Fight
                    </button>
                  </div>
                </>
              )}
              {step === "fight" && (
                <>
                  <Timeline
                    enabled={useSequence}
                    onEnabled={(enabled) => {
                      setUseSequence(enabled);
                      if (enabled) setAutosOnly(false);
                    }}
                    duration={duration}
                    actors={eventActors}
                    events={events}
                    onChange={setEvents}
                    capabilities={
                      config?.domain_contract.combat_events?.champions ?? {}
                    }
                    schedule={schedule}
                    selectedId={selectedEventId}
                    onSelect={setSelectedEventId}
                  />
                  <details className="calculator-event-list">
                    <summary>Event list</summary>
                    <EventEditor
                      enabled={useSequence}
                      onEnabled={(enabled) => {
                        setUseSequence(enabled);
                        if (enabled) setAutosOnly(false);
                      }}
                      events={events}
                      onChange={setEvents}
                      duration={duration}
                      capabilities={
                        config?.domain_contract.combat_events?.champions ?? {}
                      }
                      actors={participants
                        .filter((actor) => actor.champion)
                        .map((actor) => ({
                          id: actor.id,
                          label: `${actor.champion} · ${participantLabel(actor)}`,
                          team: enemies.some((enemy) => enemy.id === actor.id)
                            ? "enemy"
                            : "ally",
                          champion: championFor(actor),
                          ranks: actor.ranks,
                        }))}
                    />
                  </details>
                  {results.length > 0 && (
                    <div className="calculator-result-details">
                      {results.map((result, index) => (
                        <div key={index}>
                          {(resultKey !== inputKey || Boolean(error)) && (
                            <p className="calculator-notice">
                              Previous team result. Calculate to update.
                            </p>
                          )}
                          <CombatResults
                            result={result}
                            title={`Build ${index === 0 ? "A" : "B"} · team fight`}
                          />
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="calculator-step-nav">
                    <button
                      type="button"
                      className="calculator-secondary"
                      onClick={() => setStep("build")}
                    >
                      Back · Build
                    </button>
                  </div>
                </>
              )}
            </div>
            <aside className="calculator-result-rail" aria-label="Fight result">
              <section
                className="calculator-fight-bar"
                aria-label="Fight controls"
              >
                <label className="calculator-duration">
                  <span>Fight length</span>
                  <input
                    type="range"
                    min={config?.input_limits.fight_duration[0]}
                    max={config?.input_limits.fight_duration[1]}
                    step={0.5}
                    value={duration}
                    onChange={(e) => setDuration(Number(e.target.value))}
                  />
                  <output>{duration}s</output>
                </label>
                <label className="calculator-check">
                  <input
                    type="checkbox"
                    checked={autosOnly}
                    onChange={(event) => {
                      setAutosOnly(event.target.checked);
                      if (event.target.checked) setUseSequence(false);
                    }}
                  />
                  Basic attacks only
                </label>
                <label className="calculator-check">
                  <input
                    type="checkbox"
                    checked={includeActives}
                    onChange={(e) => setIncludeActives(e.target.checked)}
                  />
                  Item actives
                </label>
                <label className="calculator-check">
                  <input
                    type="checkbox"
                    checked={enemiesAttack}
                    onChange={(e) => setEnemiesAttack(e.target.checked)}
                  />
                  Enemies attack
                </label>
                <label
                  className="calculator-check"
                  title="On: a hit lit inside the fight still lands after it (a fused bomb, a channel, a DoT's remaining ticks, a burn's tail). Off: every landing is clipped at the fight's end."
                >
                  <input
                    type="checkbox"
                    checked={countAfterEnd}
                    onChange={(e) => setCountAfterEnd(e.target.checked)}
                  />
                  Count damage after the fight ends
                </label>
                <button
                  type="button"
                  className="calculator-primary"
                  disabled={!championFor(main)?.engine_registration || busy}
                  onClick={calculate}
                >
                  {busy
                    ? "Calculating…"
                    : compare
                      ? "Compare builds"
                      : "Calculate fight"}
                </button>
              </section>
              {error && (
                <div className="calculator-notice" role="alert">
                  <strong>Calculation unavailable</strong>
                  <p>{error}</p>
                </div>
              )}
              <div className="calculator-results-heading">
                <h2>Fight result</h2>
                <span role="status">
                  {busy
                    ? "Waiting for the engine…"
                    : results.length
                      ? resultKey !== inputKey
                        ? "Inputs changed. Calculate to update."
                        : "Calculation complete"
                      : "Choose a champion and allocate skill points."}
                </span>
              </div>
              {results.length ? (
                <div
                  className={`calculator-results ${results.length === 1 ? "calculator-single" : ""}`}
                >
                  {results.map((result, index) => (
                    <ResultCard
                      key={index}
                      result={result}
                      side={index === 0 ? "A" : "B"}
                      stale={resultKey !== inputKey || Boolean(error)}
                    />
                  ))}
                </div>
              ) : (
                <p className="calculator-results-empty">
                  The result shows damage, health, shields, and healing for the
                  selected fight.
                </p>
              )}
            </aside>
          </div>
          <footer className="calculator-footer">
            <span>
              Patch-pinned mechanics. Coverage details appear with each result.
            </span>
            {advancedHref && (
              <a href={advancedHref}>Full calculator workspace</a>
            )}
          </footer>
          {runeOwner && (
            <RunePage
              config={catalog.config}
              build={getBuild(
                participants.find((actor) => actor.id === runeOwner.id) ?? main,
                runeOwner.side,
              )}
              onChange={(change) =>
                editBuild(runeOwner.id, runeOwner.side, change)
              }
              onClose={() => setRuneOwner(null)}
            />
          )}
          {picker &&
            (picker.kind === "champion" ? (
              <Picker
                title={`Choose ${participantLabel(shopActor).toLowerCase()}`}
                entries={catalog.champions.map((champion) => ({
                  ...champion,
                  disabled: !champion.engine_registration,
                  detail: !champion.engine_registration
                    ? "Engine unavailable"
                    : undefined,
                }))}
                onPick={pickChampion}
                onClose={() => setPicker(null)}
              />
            ) : (
              <ItemShop
                items={shopItems}
                onPick={(name) => equip(name)}
                onClose={() => setPicker(null)}
                shop={{
                  budget,
                  spend: spend(shopBuild),
                  replacement: itemFor(replacingName)?.price ?? 0,
                  replacingName,
                  label: `${shopActor.champion || participantLabel(shopActor)} · ${isBoots ? "Boots" : `Slot ${slotIndex + 1}`}`,
                  selectedName: shopSelection,
                  onSelect: setShopSelection,
                  boots: isBoots,
                  slotAvailable,
                  catalogue: [...catalog.items, ...catalog.boots],
                  quickBoots: catalog.boots.filter(
                    (item) =>
                      item.tier <=
                      domainValue(catalog.config, shopActor, "boots_tier"),
                  ),
                  inventory: [
                    ...shopBuild.items
                      .slice(0, shopSlots)
                      .map((name, index) => ({
                        name,
                        index,
                        label: `Item ${index + 1}`,
                        active: !isBoots && index === slotIndex,
                      })),
                    {
                      name: shopBuild.boots || null,
                      index: 0,
                      label: "Boots",
                      boots: true,
                      active: isBoots,
                    },
                  ],
                  onBudget: (value) =>
                    setBudgets((current) => ({
                      ...current,
                      [budgetKey]: value,
                    })),
                  onSlot: setShopSlot,
                  onClear: () => equip(null, false),
                  onTab: (boots) =>
                    setShopSlot(
                      boots
                        ? 0
                        : Math.max(
                            0,
                            shopBuild.items
                              .slice(0, shopSlots)
                              .findIndex((item) => !item),
                          ),
                      boots,
                    ),
                  optimizer: (
                    <>
                      <SlotSearch
                        apiBase={apiBase}
                        body={bisBody}
                        title={`${shopActor.champion || "Champion"} · ${isBoots ? "Boots" : `Item slot ${slotIndex + 1}`}`}
                        ready={searchReady}
                        objective={objective}
                        objectives={objectives}
                        onObjective={setObjective}
                        onPick={(name) => equip(name, false)}
                      />
                      {shopActor.id === "main" && (
                        <PurchasePlanner
                          apiBase={apiBase}
                          body={payload(
                            picker.side === 1 ? alternative : main.build,
                          )}
                          disabled={!main.champion}
                          onApply={(items, boots) =>
                            editBuild("main", picker.side, {
                              items: Array.from(
                                { length: 6 },
                                (_, index) => items[index] ?? null,
                              ),
                              boots,
                            })
                          }
                        />
                      )}
                    </>
                  ),
                }}
              />
            ))}
        </>
      )}
    </div>
  );
}
