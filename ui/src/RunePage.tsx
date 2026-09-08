"use client";

import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import type { Build, Config, Rune } from "./types";
import { GameTooltip } from "./Tooltip";
import {
  runeIcons,
  runeDescriptions,
  runeDescriptionVersion,
  runePathDescriptions,
  shardDescriptions,
  runePathAssets,
  shardAssetIds,
  shardIcons,
} from "./rune-assets";
import {
  availableRunePaths,
  changePrimaryPath,
  changeSecondaryPath,
  choosePrimaryRune,
  chooseSecondaryRune,
  chooseStatShard,
  inferRunePaths,
} from "./rune-state";

export interface RunePageProps {
  config: Config;
  build: Build;
  onChange: (change: Partial<Build>) => void;
  onClose: () => void;
}
const pathColors: Record<string, string> = {
  Precision: "#c8aa6e",
  Domination: "#d7656e",
  Sorcery: "#a4abff",
  Resolve: "#a7cc8a",
  Inspiration: "#71c9ce",
};
const pathStyle = (path: string): CSSProperties =>
  ({ "--rune-path-color": pathColors[path] ?? "#c8aa6e" }) as CSSProperties;

export function RunePage({ config, build, onChange, onClose }: RunePageProps) {
  const initial = inferRunePaths(config, build);
  const [primary, setPrimary] = useState(initial.primary);
  const [secondary, setSecondary] = useState(initial.secondary);
  const [inspected, setInspected] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const id = useId();
  const paths = availableRunePaths(config);
  const primaryRunes = config.runes.filter(
    (rune) => rune.path === primary && rune.row > 0,
  );
  const secondaryRunes = config.runes.filter(
    (rune) => rune.path === secondary && rune.row > 0,
  );
  const primaryRows = [...new Set(primaryRunes.map((rune) => rune.row))].sort(
    (a, b) => a - b,
  );
  const secondaryRows = [
    ...new Set(secondaryRunes.map((rune) => rune.row)),
  ].sort((a, b) => a - b);
  const selectedPrimary = primaryRunes.filter((rune) =>
    build.minor_runes.includes(rune.name),
  );
  const selectedSecondary = secondaryRunes.filter((rune) =>
    build.minor_runes.includes(rune.name),
  );
  const keystone = config.keystones.find(
    (rune) => rune.name === build.keystone && rune.path === primary,
  );
  useEffect(() => {
    const node = dialog.current;
    node?.showModal();
    return () => node?.close();
  }, []);

  function switchPrimary(path: string) {
    if (path === primary) return;
    const next = changePrimaryPath(config, build, path, secondary);
    setPrimary(path);
    setSecondary(next.secondary);
    setInspected(`${path} primary path`);
    onChange(next.change);
  }
  function switchSecondary(path: string) {
    if (path === primary || path === secondary) return;
    setSecondary(path);
    setInspected(`${path} secondary path`);
    onChange(changeSecondaryPath(config, build, primary));
  }
  function pathButton(path: string, isPrimary: boolean) {
    const chosen = path === (isPrimary ? primary : secondary);
    return (
      <GameTooltip
        key={path}
        title={path}
        description={runePathDescriptions[path] ?? ""}
        meta={`${isPrimary ? "Primary" : "Secondary"} path · ${chosen ? "Selected" : "Select this path"}`}
      >
        <button
          type="button"
          className="calculator-rune-path-choice"
          aria-label={`${isPrimary ? "Primary" : "Secondary"} path: ${path}`}
          aria-pressed={chosen}
          style={pathStyle(path)}
          onClick={() =>
            isPrimary ? switchPrimary(path) : switchSecondary(path)
          }
        >
          {runePathAssets[path]?.icon ? (
            <img src={runePathAssets[path].icon} alt="" />
          ) : (
            <span>{path.slice(0, 1)}</span>
          )}
        </button>
      </GameTooltip>
    );
  }
  function runeButton(rune: Rune, isPrimary: boolean) {
    const selected =
      rune.row === 0
        ? build.keystone === rune.name
        : build.minor_runes.includes(rune.name);
    const icon = runeIcons[rune.name] ?? rune.icon;
    const tooltip = `${rune.name}${rune.implemented ? "" : " · Unavailable in this calculator"}`;
    const meta = `${rune.path} · ${rune.row === 0 ? "Keystone" : `Row ${rune.row}`} · ${selected ? "Selected" : "Unselected"}${rune.implemented ? "" : " · Unavailable in this calculator"} · Client ${runeDescriptionVersion}`;
    return (
      <GameTooltip
        key={rune.name}
        title={rune.name}
        description={
          runeDescriptions[rune.name] ??
          "Description unavailable for this source."
        }
        meta={meta}
      >
        <button
          type="button"
          className={`calculator-rune-choice ${rune.row === 0 ? "calculator-rune-keystone" : ""}`}
          aria-label={tooltip}
          aria-pressed={selected}
          aria-disabled={!rune.implemented}
          onMouseEnter={() => setInspected(tooltip)}
          onFocus={() => setInspected(tooltip)}
          onClick={() => {
            if (!rune.implemented) return;
            onChange(
              isPrimary
                ? choosePrimaryRune(config, build, rune, primary)
                : chooseSecondaryRune(config, build, rune, primary, secondary),
            );
          }}
        >
          <span className="calculator-rune-icon">
            {icon ? (
              <img src={icon} alt="" />
            ) : (
              <span className="calculator-rune-letter">
                {rune.name.slice(0, 1)}
              </span>
            )}
          </span>
        </button>
      </GameTooltip>
    );
  }
  function row(runes: Rune[], isPrimary: boolean, key: string) {
    const isKeystone = runes[0]?.row === 0;
    const selected = runes.some((rune) =>
      rune.row === 0
        ? build.keystone === rune.name
        : build.minor_runes.includes(rune.name),
    );
    return (
      <div
        key={key}
        className={`calculator-rune-row ${isKeystone ? "calculator-rune-keystone-row" : ""} ${selected ? "calculator-rune-row-selected" : ""}`}
        role="group"
        aria-label={`${isPrimary ? "Primary" : "Secondary"} ${isKeystone ? "keystone" : `rune row ${runes[0]?.row ?? key}`}`}
      >
        <span className="calculator-rune-rail-node" aria-hidden="true" />
        {isKeystone && (
          <span className="calculator-rune-row-label">Keystones</span>
        )}
        <div className="calculator-rune-row-choices">
          {runes.map((rune) => runeButton(rune, isPrimary))}
        </div>
        <span className="calculator-rune-row-divider" aria-hidden="true" />
      </div>
    );
  }
  const primaryComplete =
    Boolean(keystone) && selectedPrimary.length === primaryRows.length;
  const secondaryComplete = selectedSecondary.length === 2;
  const shardCount = config.rune_shards.filter((shard, index) =>
    shard.options.some((option) => option.name === build.stat_shards[index]),
  ).length;
  return (
    <dialog
      ref={dialog}
      className="calculator-rune-page"
      aria-labelledby={id}
      onCancel={onClose}
      onClick={(event) => {
        if (event.target === dialog.current) onClose();
      }}
    >
      <header className="calculator-rune-page-header">
        <div>
          <h2 id={id}>Runes</h2>
          <span>
            {primary} + {secondary}
          </span>
        </div>
        <button type="button" onClick={onClose} aria-label="Close rune page">
          ×
        </button>
      </header>
      <div
        className="calculator-rune-canvas"
        style={
          {
            "--rune-environment": `url("${runePathAssets[primary]?.background ?? ""}")`,
          } as CSSProperties
        }
      >
        <section
          className="calculator-rune-tree calculator-rune-primary"
          style={pathStyle(primary)}
          aria-label="Primary rune path"
        >
          <div className="calculator-rune-tree-header">
            <span className="calculator-rune-path-emblem" title={primary}>
              {runePathAssets[primary]?.icon && (
                <img src={runePathAssets[primary].icon} alt={primary} />
              )}
            </span>
            <div
              className="calculator-rune-paths"
              aria-label="Choose primary path"
            >
              {paths.map((path) => pathButton(path, true))}
            </div>
          </div>
          <div className="calculator-rune-tree-rows">
            {row(
              config.keystones.filter((rune) => rune.path === primary),
              true,
              "keystones",
            )}
            {primaryRows.map((number) =>
              row(
                primaryRunes.filter((rune) => rune.row === number),
                true,
                String(number),
              ),
            )}
          </div>
        </section>
        <section
          className="calculator-rune-tree calculator-rune-secondary"
          style={pathStyle(secondary)}
          aria-label="Secondary rune path"
        >
          <div className="calculator-rune-tree-header">
            <span className="calculator-rune-path-emblem" title={secondary}>
              {runePathAssets[secondary]?.icon && (
                <img src={runePathAssets[secondary].icon} alt={secondary} />
              )}
            </span>
            <div
              className="calculator-rune-paths"
              aria-label="Choose secondary path"
            >
              {paths
                .filter((path) => path !== primary)
                .map((path) => pathButton(path, false))}
            </div>
          </div>
          <div className="calculator-rune-tree-rows">
            {secondaryRows.map((number) =>
              row(
                secondaryRunes.filter((rune) => rune.row === number),
                false,
                String(number),
              ),
            )}
            <div className="calculator-rune-shards" aria-label="Stat shards">
              {config.rune_shards.map((shard, index) => (
                <div
                  className={`calculator-rune-shard-row ${build.stat_shards[index] ? "calculator-rune-row-selected" : ""}`}
                  key={shard.row}
                  role="group"
                  aria-label={`${shard.name} shard`}
                >
                  <span
                    className="calculator-rune-rail-node"
                    aria-hidden="true"
                  />
                  <div className="calculator-rune-row-choices">
                    {shard.options.map((option) => {
                      const selected = build.stat_shards[index] === option.name;
                      const icon = shardIcons[shardAssetIds[option.name]];
                      const tooltip = `${option.name}${option.implemented ? "" : " · Unavailable in this calculator"}`;
                      return (
                        <GameTooltip
                          key={option.name}
                          title={option.name}
                          description={
                            shardDescriptions[shardAssetIds[option.name]] ??
                            "Description unavailable for this source."
                          }
                          meta={`${shard.name} shard · ${selected ? "Selected" : "Unselected"}${option.implemented ? "" : " · Unavailable in this calculator"} · Client ${runeDescriptionVersion}`}
                        >
                          <button
                            type="button"
                            className="calculator-rune-choice calculator-rune-shard"
                            key={option.name}
                            aria-label={tooltip}
                            aria-pressed={selected}
                            aria-disabled={!option.implemented}
                            onMouseEnter={() =>
                              setInspected(`${shard.name}: ${tooltip}`)
                            }
                            onFocus={() =>
                              setInspected(`${shard.name}: ${tooltip}`)
                            }
                            onClick={() =>
                              onChange(
                                chooseStatShard(
                                  config,
                                  build,
                                  index,
                                  option.name,
                                ),
                              )
                            }
                          >
                            <span className="calculator-rune-icon">
                              {icon ? (
                                <img src={icon} alt="" />
                              ) : (
                                <span>{option.name.slice(0, 1)}</span>
                              )}
                            </span>
                          </button>
                        </GameTooltip>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
      <footer className="calculator-rune-page-footer">
        <div className="calculator-rune-page-status">
          <span role="status">{inspected || "Select your runes"}</span>
          <small>
            {primaryComplete
              ? "Primary complete"
              : `${selectedPrimary.length + Number(Boolean(keystone))}/${primaryRows.length + 1} primary`}{" "}
            ·{" "}
            {secondaryComplete
              ? "Secondary complete"
              : `${selectedSecondary.length}/2 secondary`}{" "}
            · {shardCount}/{config.rune_shards.length} shards
          </small>
        </div>
        <div>
          <button
            type="button"
            className="calculator-rune-clear"
            onClick={() => {
              onChange({
                keystone: "",
                keystone_options: {},
                minor_runes: [],
                rune_options: {},
                stat_shards: [],
              });
              setInspected("Rune page cleared");
            }}
          >
            Clear page
          </button>
          <button
            type="button"
            className="calculator-rune-done"
            onClick={onClose}
          >
            Done
          </button>
        </div>
      </footer>
    </dialog>
  );
}
export default RunePage;
