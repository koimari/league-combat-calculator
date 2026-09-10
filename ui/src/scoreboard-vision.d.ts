// Types for `scoreboard-vision.js`, the ES module `ui/build.mjs` generates
// from the DOM-free half of `static/js/scoreboard.js` (Skyway's matcher for
// the advanced page). The two hosts of the shared calculator bundle this
// module, so neither page needs a global script.

/** ImageData-shaped raster `ScoreboardVision` reads pixels from. */
export interface ScoreboardRaster {
  width: number;
  height: number;
  data: Uint8ClampedArray;
}

/** The decoded `static/icon-sprite.json` index `buildReferences` consumes. */
export interface ScoreboardSpriteIndex {
  cell: number;
  columns: number;
  patch: string;
  champions: Record<string, number>;
  items: Record<string, number>;
}

/** Opaque projected fingerprints `buildReferences` returns and `readScoreboard` takes. */
export type ScoreboardReferences = unknown;

/** One classified cell: a champion portrait or an item icon. */
export interface ScoreboardHit {
  kind: "champion" | "item";
  /** The champion name or the item id, as a string, per the sprite index. */
  key: string;
  score: number;
  gap: number;
  x: number;
  y: number;
  size: number;
  contrast?: number;
  unsure?: boolean;
  column?: number;
}

export interface ScoreboardPlayer {
  champion: ScoreboardHit;
  /** Portrait column, left to right: which side the player is on. */
  side: number;
  /** One entry per read item slot; `null` for an empty slot. */
  items: (ScoreboardHit | null)[];
}

export interface ScoreboardReading {
  hits: ScoreboardHit[];
  /** Rows top to bottom, in role order; within a row, players left to right. */
  rows: ScoreboardPlayer[][];
}

export declare const ScoreboardVision: {
  buildReferences: (
    sheet: ScoreboardRaster,
    index: ScoreboardSpriteIndex,
  ) => ScoreboardReferences;
  readScoreboard: (
    raster: ScoreboardRaster,
    refs: ScoreboardReferences,
  ) => ScoreboardReading;
};
