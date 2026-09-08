/**
 * Read scoreboards with the shipped static/js/scoreboard.js.
 *
 *   node scoreboard_harness.mjs <scoreboard.js> <manifest.json>
 *
 * The manifest names raw RGBA rasters Python decoded (Node has no image
 * decoder): the sprite sheet with its index, and the frames to read. Prints
 * one JSON object: `{ frames: { name: { rows, hits, ms } } }`, rows as
 * ScoreboardVision.readScoreboard returns them.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { harnessContext, runScript, evaluate } from "./harness_context.mjs";

const [scriptPath, manifestPath] = process.argv.slice(2);
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const base = dirname(resolve(manifestPath));

function raster(entry) {
  const bytes = readFileSync(resolve(base, entry.bin));
  return { width: entry.width, height: entry.height, data: new Uint8ClampedArray(bytes.buffer, bytes.byteOffset, bytes.byteLength) };
}

const context = harnessContext(manifestPath, { document: undefined });
runScript(context, scriptPath, "scoreboard.js");
const vision = evaluate(context, "ScoreboardVision");
const refs = vision.buildReferences(raster(manifest.sprite), manifest.sprite.index);

const frames = {};
for (const frame of manifest.frames) {
  const started = performance.now();
  const reading = vision.readScoreboard(raster(frame), refs);
  frames[frame.name] = { ...reading, ms: Math.round(performance.now() - started) };
}
process.stdout.write(JSON.stringify({ frames }));
