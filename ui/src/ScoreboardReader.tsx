"use client";

import { useEffect, useId, useRef, useState } from "react";
import "./scoreboard-reader.css";
import {
  SCOREBOARD_ROLES,
  championFor,
  playersOf,
  scoreboardLoadResult,
  type ScoreboardCatalog,
  type ScoreboardLoadResult,
  type ScoreboardReadPlayer,
} from "./scoreboard-load";
import type { Participant } from "./scenario-state";
import {
  ScoreboardVision,
  type ScoreboardHit,
  type ScoreboardRaster,
  type ScoreboardReading,
  type ScoreboardReferences,
  type ScoreboardSpriteIndex,
} from "./scoreboard-vision.js";

export interface ScoreboardReaderProps {
  /** Where `icon-sprite.json` and `icon-sprite.webp` are served from. */
  assetBase: string;
  catalog: ScoreboardCatalog;
  main: Participant;
  onLoad: (result: ScoreboardLoadResult) => void;
}

/* Screenshots are a few MB; a small file that decodes to a huge bitmap would
 * freeze the tab, so size is checked before anything decodes. Matches
 * MAX_SCREENSHOT_MB in the old page's static/js/scoreboard.js. */
const MAX_SCREENSHOT_MB = 25;
const PREVIEW_WIDTH = 720;

let references: { base: string; refs: Promise<ScoreboardReferences> } | null =
  null;

/** Reference art fetched and fingerprinted once, then cached for later reads. */
function loadReferences(assetBase: string): Promise<ScoreboardReferences> {
  if (!references || references.base !== assetBase) {
    const refs = (async () => {
      const response = await fetch(`${assetBase}/icon-sprite.json`);
      if (!response.ok)
        throw new Error(
          `The icon sprite index did not load (${response.status}).`,
        );
      const index: ScoreboardSpriteIndex = await response.json();
      const image = await new Promise<HTMLImageElement>((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error("The icon sprite did not load."));
        img.src = `${assetBase}/icon-sprite.webp`;
      });
      return ScoreboardVision.buildReferences(rasterOf(image), index);
    })().catch((error: unknown) => {
      references = null;
      throw error;
    });
    references = { base: assetBase, refs };
  }
  return references.refs;
}

interface Raster extends ScoreboardRaster {
  scale: number;
}

/** A source image resampled to at most `maxWidth`, as the raster `ScoreboardVision` reads. */
function rasterOf(
  source: CanvasImageSource & { width: number; height: number },
  maxWidth = 2200,
): Raster {
  const scale = Math.min(1, maxWidth / source.width);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(source.width * scale);
  canvas.height = Math.round(source.height * scale);
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context)
    throw new Error(
      "This browser cannot decode images for the scoreboard reader.",
    );
  context.drawImage(source, 0, 0, canvas.width, canvas.height);
  const raster = context.getImageData(
    0,
    0,
    canvas.width,
    canvas.height,
  ) as ImageData & {
    scale?: number;
  };
  raster.scale = scale;
  return raster as Raster;
}

/* Decoded off the blob, never through an object URL: the page's CSP
 * img-src has no blob:, so an <img> pointed at one never loads. */
async function decodeImage(blob: Blob): Promise<ImageBitmap> {
  if (blob.size > MAX_SCREENSHOT_MB * 1e6) {
    throw new Error(
      `That file is ${Math.round(blob.size / 1e6)} MB; a screenshot is under ${MAX_SCREENSHOT_MB} MB.`,
    );
  }
  try {
    return await createImageBitmap(blob);
  } catch {
    throw new Error("That file is not an image the browser can open.");
  }
}

export function ScoreboardReader({
  assetBase,
  catalog,
  main,
  onLoad,
}: ScoreboardReaderProps) {
  const headingId = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const preview = useRef<HTMLCanvasElement>(null);
  const [status, setStatus] = useState("");
  const [reading, setReading] = useState<ScoreboardReading | null>(null);
  const [pickedIndex, setPickedIndex] = useState(-1);
  const mainRef = useRef(main);
  mainRef.current = main;

  useEffect(() => {
    function onPaste(event: ClipboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.closest?.("input, textarea, [contenteditable]")) return;
      const file = [...(event.clipboardData?.files ?? [])].find((candidate) =>
        candidate.type.startsWith("image/"),
      );
      if (!file) return;
      event.preventDefault();
      readBlob(file);
    }
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function drawPreview(
    image: ImageBitmap,
    read: ScoreboardReading,
    scale: number,
  ) {
    const canvas = preview.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    const ratio = PREVIEW_WIDTH / image.width;
    canvas.width = PREVIEW_WIDTH;
    canvas.height = Math.round(image.height * ratio);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    context.lineWidth = 2;
    for (const player of read.rows.flat()) {
      const hits = [
        player.champion,
        ...player.items.filter((hit): hit is ScoreboardHit => Boolean(hit)),
      ];
      for (const hit of hits) {
        context.strokeStyle =
          hit.kind === "champion"
            ? "#2f7d4f"
            : hit.unsure
              ? "#c8891a"
              : "#e8dcc0";
        context.strokeRect(
          (hit.x / scale) * ratio,
          (hit.y / scale) * ratio,
          (hit.size / scale) * ratio,
          (hit.size / scale) * ratio,
        );
      }
    }
  }

  async function readBlob(blob: Blob) {
    const node = dialog.current;
    if (node && !node.open) node.showModal();
    setStatus("Reading the scoreboard…");
    setReading(null);
    setPickedIndex(-1);
    try {
      const [refs, image] = await Promise.all([
        loadReferences(assetBase),
        decodeImage(blob),
      ]);
      const raster = rasterOf(image);
      /* One paint, so "Reading…" shows before the synchronous read blocks the
       * page for a few seconds. */
      await new Promise((resolve) => setTimeout(resolve, 30));
      const started = performance.now();
      const result = ScoreboardVision.readScoreboard(raster, refs);
      const players = playersOf(result);
      drawPreview(image, result, raster.scale);
      setReading(result);
      const firstKnown = players.findIndex((player) =>
        championFor(catalog, player),
      );
      setPickedIndex(firstKnown);
      const itemCount = players.reduce(
        (sum, player) => sum + player.items.filter(Boolean).length,
        0,
      );
      setStatus(
        players.length
          ? `Found ${players.length} champions and ${itemCount} items in ${((performance.now() - started) / 1000).toFixed(1)}s. Pick your champion, then load.`
          : "No scoreboard found. Paste a frame with the full item panel showing.",
      );
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  const players: ScoreboardReadPlayer[] = reading ? playersOf(reading) : [];

  function loadPicked() {
    if (!reading || pickedIndex < 0) return;
    onLoad(
      scoreboardLoadResult(reading, pickedIndex, catalog, mainRef.current),
    );
    dialog.current?.close();
  }

  return (
    <>
      <button
        type="button"
        className="calculator-text-button"
        title="Or paste a screenshot anywhere on the page"
        onClick={() => fileInput.current?.click()}
      >
        Read a scoreboard screenshot
      </button>
      <input
        ref={fileInput}
        type="file"
        accept="image/*"
        className="calculator-sr-only"
        aria-label="Choose a scoreboard screenshot"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) readBlob(file);
          event.target.value = "";
        }}
      />
      <dialog
        ref={dialog}
        className="calculator-scoreboard-dialog"
        aria-labelledby={headingId}
        onClick={(event) => {
          if (event.target === dialog.current) dialog.current?.close();
        }}
      >
        <header className="calculator-scoreboard-header">
          <div>
            <span className="calculator-scoreboard-kicker">Scoreboard</span>
            <h2 id={headingId}>Read from a screenshot</h2>
          </div>
          <button
            type="button"
            className="calculator-icon-button"
            onClick={() => dialog.current?.close()}
            aria-label="Close"
          >
            ×
          </button>
        </header>
        <p role="status" className="calculator-scoreboard-status">
          {status}
        </p>
        <canvas ref={preview} className="calculator-scoreboard-preview" />
        {players.length > 0 && (
          <>
            <div
              className="calculator-scoreboard-players"
              role="radiogroup"
              aria-label="Pick your champion"
            >
              {players.map((player, index) => {
                const champion = championFor(catalog, player);
                const seen = new Set<number>();
                return (
                  <label
                    key={index}
                    className={`calculator-scoreboard-player${champion ? "" : " is-unmodeled"}`}
                  >
                    <input
                      type="radio"
                      name="scoreboard-attacker"
                      value={index}
                      checked={pickedIndex === index}
                      disabled={!champion}
                      onChange={() => setPickedIndex(index)}
                    />
                    <span className="calculator-scoreboard-portrait">
                      {champion ? (
                        <img src={champion.icon} alt="" />
                      ) : (
                        <span aria-hidden="true">?</span>
                      )}
                    </span>
                    <span className="calculator-scoreboard-identity">
                      <strong>{player.champion.key}</strong>
                      <small>
                        {Math.round(player.champion.score * 100)}%{" · "}
                        {player.side ? "Right" : "Left"}
                        {" · "}
                        {SCOREBOARD_ROLES[player.row] ??
                          `row ${player.row + 1}`}
                        {champion ? "" : " · not modeled"}
                      </small>
                    </span>
                    <span className="calculator-scoreboard-items">
                      {player.items.map((hit, slot) => {
                        if (!hit)
                          return (
                            <span
                              key={slot}
                              className="calculator-scoreboard-item is-empty"
                              aria-hidden="true"
                            />
                          );
                        const id = Number(hit.key);
                        const catalogItem =
                          catalog.items.find((entry) => entry.id === id) ??
                          catalog.boots.find((entry) => entry.id === id) ??
                          null;
                        const duplicate = Boolean(
                          catalogItem && seen.has(catalogItem.id),
                        );
                        if (catalogItem) seen.add(catalogItem.id);
                        const flag =
                          !catalogItem || duplicate
                            ? "is-unknown"
                            : hit.unsure
                              ? "is-unsure"
                              : "";
                        const title = !catalogItem
                          ? "Not a buildable item"
                          : duplicate
                            ? `${catalogItem.name}, a second copy the calculator cannot hold`
                            : `${catalogItem.name} · ${Math.round(hit.score * 100)}%`;
                        return (
                          <span
                            key={slot}
                            className={`calculator-scoreboard-item ${flag}`.trim()}
                            title={title}
                          >
                            {catalogItem ? (
                              <img src={catalogItem.icon} alt="" />
                            ) : (
                              <span aria-hidden="true">?</span>
                            )}
                          </span>
                        );
                      })}
                    </span>
                  </label>
                );
              })}
            </div>
            <div className="calculator-scoreboard-legend">
              <span>
                <i
                  className="calculator-scoreboard-swatch is-unsure"
                  aria-hidden="true"
                />
                low confidence
              </span>
              <span>
                <i
                  className="calculator-scoreboard-swatch is-unknown"
                  aria-hidden="true"
                />
                not buildable here
              </span>
            </div>
          </>
        )}
        <div className="calculator-scoreboard-actions">
          <button type="button" onClick={() => dialog.current?.close()}>
            Close
          </button>
          <button type="button" disabled={pickedIndex < 0} onClick={loadPicked}>
            Load into the calculator
          </button>
        </div>
      </dialog>
    </>
  );
}
