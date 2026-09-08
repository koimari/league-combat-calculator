/* Scoreboard autofill: paste a broadcast or in-game scoreboard and read the ten
 * champions and their items off it into the roster.
 *
 * `ScoreboardVision` is the matcher: pure functions over ImageData-shaped
 * rasters ({width, height, data}) with no DOM, so tests/js/scoreboard_harness.mjs
 * drives the very same code over the labeled corpus. Reference art is the
 * per-patch sprite scripts/build_icon_sprite.py writes. Search is coarse to
 * fine and anchored: a 4x4 thumbnail of every position on a downscaled
 * pyramid is scored against every icon in a 12-dimensional projection, the
 * strongest positions are verified by 8x8 then 24x24 correlation at full
 * resolution, and once one portrait is certain the rest are read off the
 * panel's structure: its column for teammates, one row for an opponent and
 * that opponent's column, each row band for items at one shared size, and
 * the grids those define for whatever a search missed. The DOM wiring
 * underneath turns a pasted image into a request payload for
 * loadSharedBuildIntoAnalyst.
 */
const ScoreboardVision = (() => {
  "use strict";

  const THUMB = 4;
  const COARSE = 8;
  const FINE = 24;
  /* Projection widths of the 4x4 (search) and 8x8 (shortlist) stages. */
  const THUMB_DIMS = 12;
  const COARSE_DIMS = 24;
  const SHORTLIST = 6;
  const MIN_SCORE = { champion: 0.78, item: 0.72 };
  /* Margin over the runner-up key. Footage and HUD texture reach 0.85 against
   * some dark portrait but never with a clear runner-up; real portraits carry
   * 0.3 or more. Items have true lookalikes (component swords), so none. */
  const MIN_GAP = { champion: 0.28, item: 0 };
  /* A slot on a player's established item grid is strong evidence on its own,
   * so a cell there is kept at a lower correlation than a free detection, if
   * it also has a clear runner-up margin; text past a strip's end matches
   * some icon at 0.7 but never with one. A high score alone still passes. */
  const FILL_SCORE = 0.62;
  const FILL_GAP = 0.22;
  const SURE_FILL = 0.78;
  /* Only hits this strong vote on the shared item size. */
  const SURE_SCORE = 0.8;
  /* A refined 4x4 thumbnail must score this before the cell is classified. */
  const THUMB_GATE = 0.55;
  const MIN_CONTRAST = 24;
  /* Portraits on broadcast panels are often a zoomed crop of the square icon. */
  const CHAMPION_CROPS = [1, 0.85];
  const SIZE_RATIO = 1.15;
  /* Coarse candidates verified per search: a few per size for the anchor,
   * every one to a cap inside the column, row and item bands. Real icons can
   * rank past 200 in coarse order, so no early stop. */
  const VERIFY = { anchor: 12, cap: 400 };
  /* Portrait sizes the anchor is sought at, on a frame no wider than the
   * page's 2200px working width; tried nearest this typical size first. */
  const PORTRAIT = { min: 24, max: 64, typical: 34 };
  /* An anchor this certain ends the size search early. */
  const SURE_ANCHOR = 0.9;
  /* Slots a scoreboard shows per player: six items, boots, and a trinket. */
  const MAX_SLOTS = 8;
  /* Players per team, so rows per column. */
  const MAX_ROWS = 5;

  /* --- fingerprints --------------------------------------------------- */

  /**
   * Area-resample the square at (x, y, size) into `vec` as n×n RGB, zero-mean
   * and unit length; returns the cell's RMS deviation before normalizing.
   */
  function fingerprint(raster, x, y, size, n, vec) {
    const { width, data } = raster;
    const left = Math.round(x);
    const top = Math.round(y);
    const edges = new Int32Array(n + 1);
    for (let i = 0; i <= n; i += 1) edges[i] = Math.round((i * size) / n);
    let k = 0;
    for (let i = 0; i < n; i += 1) {
      const y0 = top + edges[i];
      const y1 = top + Math.max(edges[i] + 1, edges[i + 1]);
      for (let j = 0; j < n; j += 1) {
        const x0 = left + edges[j];
        const x1 = left + Math.max(edges[j] + 1, edges[j + 1]);
        let r = 0;
        let g = 0;
        let b = 0;
        for (let yy = y0; yy < y1; yy += 1) {
          let p = (yy * width + x0) * 4;
          for (let xx = x0; xx < x1; xx += 1, p += 4) {
            r += data[p];
            g += data[p + 1];
            b += data[p + 2];
          }
        }
        const count = (y1 - y0) * (x1 - x0);
        vec[k] = r / count;
        vec[k + 1] = g / count;
        vec[k + 2] = b / count;
        k += 3;
      }
    }
    return normalize(vec);
  }

  /** Zero-mean, unit-length in place; returns the RMS deviation. */
  function normalize(vec) {
    let mean = 0;
    for (let i = 0; i < vec.length; i += 1) mean += vec[i];
    mean /= vec.length;
    let norm = 0;
    for (let i = 0; i < vec.length; i += 1) {
      vec[i] -= mean;
      norm += vec[i] * vec[i];
    }
    const contrast = Math.sqrt(norm / vec.length);
    norm = Math.sqrt(norm) || 1;
    for (let i = 0; i < vec.length; i += 1) vec[i] /= norm;
    return contrast;
  }

  function dot(a, aOffset, b, bOffset, length) {
    let sum = 0;
    for (let i = 0; i < length; i += 1) sum += a[aOffset + i] * b[bOffset + i];
    return sum;
  }

  /* --- references ----------------------------------------------------- */

  /** Top `k` principal directions of `rows` (count × dims), by power iteration. */
  function principalAxes(rows, count, dims, k) {
    const cov = new Float64Array(dims * dims);
    for (let r = 0; r < count; r += 1) {
      for (let i = 0; i < dims; i += 1) {
        const a = rows[r * dims + i];
        for (let j = 0; j < dims; j += 1) cov[i * dims + j] += a * rows[r * dims + j];
      }
    }
    const axes = new Float32Array(k * dims);
    const v = new Float64Array(dims);
    const w = new Float64Array(dims);
    for (let c = 0; c < k; c += 1) {
      for (let i = 0; i < dims; i += 1) v[i] = Math.sin(1 + i + c);
      for (let iteration = 0; iteration < 40; iteration += 1) {
        for (let i = 0; i < dims; i += 1) {
          let sum = 0;
          for (let j = 0; j < dims; j += 1) sum += cov[i * dims + j] * v[j];
          w[i] = sum;
        }
        for (let p = 0; p < c; p += 1) {
          let along = 0;
          for (let i = 0; i < dims; i += 1) along += w[i] * axes[p * dims + i];
          for (let i = 0; i < dims; i += 1) w[i] -= along * axes[p * dims + i];
        }
        let norm = 0;
        for (let i = 0; i < dims; i += 1) norm += w[i] * w[i];
        norm = Math.sqrt(norm) || 1;
        for (let i = 0; i < dims; i += 1) v[i] = w[i] / norm;
      }
      for (let i = 0; i < dims; i += 1) axes[c * dims + i] = v[i];
    }
    return axes;
  }

  /**
   * Fingerprint every sprite cell. `index` is static/icon-sprite.json and
   * `sheet` the decoded sprite. Champion cells also get a center-cropped
   * variant; variants share a key and the classifier scores a key by its
   * best variant. Per kind, the 4x4 and 8x8 fingerprints are projected onto
   * their own principal axes, which is what makes scoring a cell against
   * every reference cheap enough to do thousands of times per read.
   */
  function buildReferences(sheet, index) {
    const cell = index.cell;
    const entries = [];
    for (const [name, number] of Object.entries(index.champions)) {
      CHAMPION_CROPS.forEach((crop) => entries.push({ kind: "champion", key: name, number, crop }));
    }
    for (const [id, number] of Object.entries(index.items)) {
      entries.push({ kind: "item", key: id, number, crop: 1 });
    }
    const thumbLen = THUMB * THUMB * 3;
    const coarseLen = COARSE * COARSE * 3;
    const fineLen = FINE * FINE * 3;
    const thumb = new Float32Array(entries.length * thumbLen);
    const coarse = new Float32Array(entries.length * coarseLen);
    const fine = new Float32Array(entries.length * fineLen);
    entries.forEach((entry, i) => {
      const inset = Math.round((cell * (1 - entry.crop)) / 2);
      const x = (entry.number % index.columns) * cell + inset;
      const y = Math.floor(entry.number / index.columns) * cell + inset;
      fingerprint(sheet, x, y, cell - 2 * inset, THUMB, thumb.subarray(i * thumbLen, (i + 1) * thumbLen));
      fingerprint(sheet, x, y, cell - 2 * inset, COARSE, coarse.subarray(i * coarseLen, (i + 1) * coarseLen));
      fingerprint(sheet, x, y, cell - 2 * inset, FINE, fine.subarray(i * fineLen, (i + 1) * fineLen));
    });
    const projection = (indices, source, len, dims) => {
      const rows = new Float32Array(indices.length * len);
      indices.forEach((i, r) => rows.set(source.subarray(i * len, (i + 1) * len), r * len));
      const axes = principalAxes(rows, indices.length, len, dims);
      const projected = new Float32Array(indices.length * dims);
      for (let r = 0; r < indices.length; r += 1) {
        for (let c = 0; c < dims; c += 1) projected[r * dims + c] = dot(rows, r * len, axes, c * len, len);
      }
      return { axes, projected };
    };
    const kinds = {};
    for (const kind of ["champion", "item"]) {
      const indices = entries.map((e, i) => (e.kind === kind ? i : -1)).filter((i) => i >= 0);
      kinds[kind] = {
        indices,
        thumb: projection(indices, thumb, thumbLen, THUMB_DIMS),
        coarse: projection(indices, coarse, coarseLen, COARSE_DIMS),
      };
    }
    return { entries, fine, fineLen, coarseLen, thumbLen, kinds };
  }

  /**
   * Best key of `kind` for one cell: shortlist by the projected 8x8
   * correlation, decide by the exact 24x24 one. `gap` is the margin over the
   * best *different* key, the confidence the review sheet flags on;
   * `contrast` is the cell's RMS deviation, which is what tells a blank slot
   * from a dark icon.
   */
  function classify(raster, x, y, size, refs, kind) {
    const { indices, coarse } = refs.kinds[kind];
    const coarseVec = new Float32Array(refs.coarseLen);
    fingerprint(raster, x, y, size, COARSE, coarseVec);
    const proj = new Float32Array(COARSE_DIMS);
    for (let c = 0; c < COARSE_DIMS; c += 1) proj[c] = dot(coarseVec, 0, coarse.axes, c * refs.coarseLen, refs.coarseLen);
    const shortIndex = new Int32Array(SHORTLIST).fill(-1);
    const shortScore = new Float32Array(SHORTLIST).fill(-Infinity);
    for (let r = 0; r < indices.length; r += 1) {
      const score = dot(proj, 0, coarse.projected, r * COARSE_DIMS, COARSE_DIMS);
      if (score <= shortScore[SHORTLIST - 1]) continue;
      let slot = SHORTLIST - 1;
      while (slot > 0 && shortScore[slot - 1] < score) {
        shortScore[slot] = shortScore[slot - 1];
        shortIndex[slot] = shortIndex[slot - 1];
        slot -= 1;
      }
      shortScore[slot] = score;
      shortIndex[slot] = indices[r];
    }
    const fineVec = new Float32Array(refs.fineLen);
    const contrast = fingerprint(raster, x, y, size, FINE, fineVec);
    let best = null;
    let second = 0;
    for (let s = 0; s < SHORTLIST; s += 1) {
      const i = shortIndex[s];
      if (i < 0) break;
      const score = dot(fineVec, 0, refs.fine, i * refs.fineLen, refs.fineLen);
      const entry = refs.entries[i];
      if (!best || score > best.score) {
        if (best && best.key !== entry.key) second = Math.max(second, best.score);
        best = { kind, key: entry.key, score, gap: 0, contrast, x, y, size };
      } else if (entry.key !== best.key) {
        second = Math.max(second, score);
      }
    }
    if (best) best.gap = best.score - second;
    return best;
  }

  /** The projected 4x4 score of one full-resolution cell against every icon of `kind`. */
  function thumbScore(raster, refs, kind, x, y, size, vec, proj) {
    const { axes, projected } = refs.kinds[kind].thumb;
    const count = refs.kinds[kind].indices.length;
    fingerprint(raster, x, y, size, THUMB, vec);
    for (let c = 0; c < THUMB_DIMS; c += 1) proj[c] = dot(vec, 0, axes, c * refs.thumbLen, refs.thumbLen);
    let best = -1;
    for (let r = 0; r < count; r += 1) {
      const score = dot(proj, 0, projected, r * THUMB_DIMS, THUMB_DIMS);
      if (score > best) best = score;
    }
    return best;
  }

  /**
   * The full-resolution verdict on a candidate. A pyramid peak can sit a
   * whole cell off the icon (its `reach`), so unless the candidate is
   * `anchored` (a slot on a known grid, classified over a 3x3 window two
   * pixels apart at three sizes) the thumbnail score is re-taken on
   * a 2px grid over that window first: a cell that never looks like an
   * icon is rejected there, before any classification, and the two best
   * spots are classified, since a 4x4 thumbnail can prefer the edge of a
   * neighbour. The survivor is polished by 1px steps and at most one size
   * step either way, re-classifying so the key may change as it settles.
   */
  function verify(raster, candidate, refs, kind, anchored = false) {
    const inside = (x, y, size) => x >= 0 && y >= 0 && x + size <= raster.width && y + size <= raster.height;
    if (!inside(candidate.x, candidate.y, candidate.size)) return null;
    let best = null;
    if (anchored) {
      for (const size of [candidate.size - 1, candidate.size, candidate.size + 1]) {
        for (const dy of [-2, 0, 2]) {
          for (const dx of [-2, 0, 2]) {
            const hit = inside(candidate.x + dx, candidate.y + dy, size)
              ? classify(raster, candidate.x + dx, candidate.y + dy, size, refs, kind)
              : null;
            if (hit && (!best || hit.score > best.score)) best = hit;
          }
        }
      }
    } else {
      const vec = new Float32Array(refs.thumbLen);
      const proj = new Float32Array(THUMB_DIMS);
      const reach = Math.max(3, candidate.reach || Math.round(candidate.size / 4));
      const spots = [];
      for (let dy = -reach; dy <= reach; dy += 2) {
        for (let dx = -reach; dx <= reach; dx += 2) {
          const x = candidate.x + dx;
          const y = candidate.y + dy;
          if (inside(x, y, candidate.size)) spots.push({ x, y, score: thumbScore(raster, refs, kind, x, y, candidate.size, vec, proj) });
        }
      }
      spots.sort((a, b) => b.score - a.score);
      if (!spots.length || spots[0].score < THUMB_GATE) return null;
      for (const spot of spots.slice(0, 2)) {
        const hit = classify(raster, spot.x, spot.y, candidate.size, refs, kind);
        if (hit && (!best || hit.score > best.score)) best = hit;
      }
    }
    if (!best || best.contrast < MIN_CONTRAST || best.score < MIN_SCORE[kind] - 0.1) return null;
    const smallest = Math.round(candidate.size / SIZE_RATIO);
    const largest = Math.round(candidate.size * SIZE_RATIO);
    for (let moved = true, rounds = 0; moved && rounds < 6; rounds += 1) {
      moved = false;
      for (const [dx, dy, ds] of [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]]) {
        const x = best.x + dx;
        const y = best.y + dy;
        const size = best.size + ds;
        if (!inside(x, y, size) || size < smallest || size > largest) continue;
        const hit = classify(raster, x, y, size, refs, kind);
        if (hit && hit.score > best.score) {
          best = hit;
          moved = true;
        }
      }
    }
    return best.contrast >= MIN_CONTRAST ? best : null;
  }

  /* --- coarse search -------------------------------------------------- */

  /**
   * A pyramid level: `raster` box-filtered down by `factor` as RGB floats,
   * one row at a time on first use, since a band search touches a few rows
   * of a level and a whole-frame filter per level was most of a read.
   */
  function pyramidLevel(raster, factor) {
    const width = Math.floor(raster.width / factor);
    const height = Math.floor(raster.height / factor);
    const level = { width, height, factor, data: new Float32Array(width * height * 3), ready: new Uint8Array(height) };
    level.prepare = (i0, i1) => {
      for (let i = Math.max(0, i0); i < Math.min(height, i1); i += 1) {
        if (!level.ready[i]) filterRow(raster, level, i);
      }
    };
    return level;
  }

  function filterRow(raster, level, i) {
    const { width, factor, data: out } = level;
    const { data } = raster;
    level.ready[i] = 1;
    {
      const y0 = Math.round(i * factor);
      const y1 = Math.max(y0 + 1, Math.round((i + 1) * factor));
      for (let j = 0; j < width; j += 1) {
        const x0 = Math.round(j * factor);
        const x1 = Math.max(x0 + 1, Math.round((j + 1) * factor));
        let r = 0;
        let g = 0;
        let b = 0;
        for (let yy = y0; yy < y1; yy += 1) {
          let p = (yy * raster.width + x0) * 4;
          for (let xx = x0; xx < x1; xx += 1, p += 4) {
            r += data[p];
            g += data[p + 1];
            b += data[p + 2];
          }
        }
        const count = (y1 - y0) * (x1 - x0);
        const q = (i * width + j) * 3;
        out[q] = r / count;
        out[q + 1] = g / count;
        out[q + 2] = b / count;
      }
    }
  }

  /**
   * Where icons of `kind` at about `size` px could be inside `region`
   * ({x0, y0, x1, y1}, full-resolution, whole raster when null): every
   * position of a pyramid level, scored by its projected 4x4 thumbnail
   * against every reference, kept when it beats its 3x3 neighbours,
   * strongest first. The level's cells are size/4 px, or size/8 when `fine`
   * (each thumbnail cell then sums a 2x2 block), which places a peak within
   * an eighth of the icon instead of a quarter; a whole-frame search takes
   * the cheap level, a band search the fine one. `levels` memoizes per level.
   */
  function coarseSearch(raster, refs, kind, size, region, levels, fine = false) {
    const block = fine ? 2 : 1;
    const factor = size / (THUMB * block);
    const key = `${size}:${block}`;
    let level = levels && levels.get(key);
    if (!level) {
      level = pyramidLevel(raster, factor);
      if (levels) levels.set(key, level);
    }
    const { width, height, data } = level;
    const { axes, projected } = refs.kinds[kind].thumb;
    const count = refs.kinds[kind].indices.length;
    const thumbLen = refs.thumbLen;
    const span = THUMB * block;
    const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
    const i0 = region ? clamp(Math.floor(region.y0 / factor), 0, height) : 0;
    const i1 = region ? clamp(Math.ceil(region.y1 / factor), 0, height) : height;
    const j0 = region ? clamp(Math.floor(region.x0 / factor), 0, width) : 0;
    const j1 = region ? clamp(Math.ceil(region.x1 / factor), 0, width) : width;
    const iEnd = Math.min(height, i1 + span) - span;
    const jEnd = Math.min(width, j1 + span) - span;
    level.prepare(i0, iEnd + span);
    const scores = new Float32Array(width * height).fill(-1);
    const vec = new Float32Array(thumbLen);
    const proj = new Float32Array(THUMB_DIMS);
    for (let i = i0; i <= iEnd; i += 1) {
      for (let j = j0; j <= jEnd; j += 1) {
        vec.fill(0);
        for (let yy = 0; yy < span; yy += 1) {
          let p = ((i + yy) * width + j) * 3;
          const row = Math.floor(yy / block) * THUMB;
          for (let xx = 0; xx < span; xx += 1, p += 3) {
            const k = (row + Math.floor(xx / block)) * 3;
            vec[k] += data[p];
            vec[k + 1] += data[p + 1];
            vec[k + 2] += data[p + 2];
          }
        }
        normalize(vec);
        for (let c = 0; c < THUMB_DIMS; c += 1) proj[c] = dot(vec, 0, axes, c * thumbLen, thumbLen);
        let best = -1;
        for (let r = 0; r < count; r += 1) {
          const score = dot(proj, 0, projected, r * THUMB_DIMS, THUMB_DIMS);
          if (score > best) best = score;
        }
        scores[i * width + j] = best;
      }
    }
    const found = [];
    for (let i = i0; i <= iEnd; i += 1) {
      for (let j = j0; j <= jEnd; j += 1) {
        const score = scores[i * width + j];
        if (score < 0.3) continue;
        let peak = true;
        for (let di = -1; di <= 1 && peak; di += 1) {
          for (let dj = -1; dj <= 1; dj += 1) {
            const ni = i + di;
            const nj = j + dj;
            if ((di || dj) && ni >= 0 && nj >= 0 && ni < height && nj < width && scores[ni * width + nj] > score) { peak = false; break; }
          }
        }
        if (peak) found.push({ x: Math.round(j * factor), y: Math.round(i * factor), size, score, reach: Math.ceil(factor) });
      }
    }
    return found.sort((a, b) => b.score - a.score);
  }

  /** Greedy non-maximum suppression on hits sorted by score. */
  function suppress(hits) {
    const kept = [];
    for (const hit of hits) {
      if (kept.every((k) => Math.abs(k.x - hit.x) >= k.size / 2 || Math.abs(k.y - hit.y) >= k.size / 2)) kept.push(hit);
    }
    return kept;
  }

  function sizesBetween(min, max, ratio = SIZE_RATIO) {
    const sizes = [];
    for (let s = min; s <= max; s = Math.max(s + 1, Math.round(s * ratio))) sizes.push(Math.round(s));
    return sizes;
  }

  /**
   * Verified hits of `kind` at `size` within `region`, strongest first, no
   * overlaps. A band search takes the fine pyramid level; a whole-frame one
   * the cheap level.
   */
  function search(raster, refs, kind, size, region, levels, verifyCount = VERIFY.cap) {
    const candidates = coarseSearch(raster, refs, kind, size, region, levels, Boolean(region)).slice(0, verifyCount);
    const hits = [];
    for (const candidate of candidates) {
      const hit = verify(raster, candidate, refs, kind);
      if (hit && hit.score >= MIN_SCORE[kind] && hit.gap >= MIN_GAP[kind]) hits.push(hit);
    }
    return suppress(hits.sort((a, b) => b.score - a.score));
  }

  /* --- structure ------------------------------------------------------ */

  function median(values) {
    const sorted = [...values].sort((a, b) => a - b);
    return sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0;
  }

  const centreY = (hit) => hit.y + hit.size / 2;

  /**
   * The strongest portrait anywhere, any size: the anchor every other search
   * hangs off. Only the few best coarse candidates per size are verified,
   * a certain hit at a likely size spares the unlikely ones, and the winner
   * is re-verified one size step either way, since everything downstream
   * is searched at its size.
   */
  function anchor(raster, refs, sizes, levels) {
    let best = null;
    for (const size of [...sizes].sort((a, b) => Math.abs(a - PORTRAIT.typical) - Math.abs(b - PORTRAIT.typical))) {
      for (const hit of search(raster, refs, "champion", size, null, levels, VERIFY.anchor)) {
        if (!best || hit.score > best.score) best = hit;
      }
      if (best && best.score >= SURE_ANCHOR) break;
    }
    if (!best || best.score < MIN_SCORE.champion + 0.05) return null;
    for (const size of [Math.round(best.size / SIZE_RATIO), Math.round(best.size * SIZE_RATIO)]) {
      const hit = verify(raster, { x: best.x, y: best.y, size, reach: 3 }, refs, "champion");
      if (hit && hit.score > best.score) best = hit;
    }
    return best;
  }

  /**
   * Every portrait sharing the anchor's column and size: a team reads down
   * the panel. Then the opposing team: one full-width search along the
   * strongest teammate's row finds its opponent, and that opponent's column
   * holds the rest, so a stray match elsewhere on a row is never taken.
   */
  function portraits(raster, refs, first, levels) {
    const size = first.size;
    const column = { x0: first.x - size / 2, x1: first.x + size * 1.5, y0: 0, y1: raster.height };
    const team = search(raster, refs, "champion", size, column, levels)
      .filter((hit) => Math.abs(hit.size - size) <= size * 0.2 && Math.abs(hit.x - first.x) <= size / 2);
    let opposing = [];
    for (const hit of [...team].sort((a, b) => b.score - a.score)) {
      const row = { x0: 0, x1: raster.width, y0: centreY(hit) - size * 0.75, y1: centreY(hit) + size * 0.75 };
      const mate = search(raster, refs, "champion", size, row, levels).find((m) => Math.abs(m.x - hit.x) >= size);
      if (!mate) continue;
      const theirs = { x0: mate.x - size / 2, x1: mate.x + size * 1.5, y0: 0, y1: raster.height };
      opposing = search(raster, refs, "champion", size, theirs, levels).filter((m) => Math.abs(m.x - mate.x) <= size / 2);
      break;
    }
    return fillColumns(raster, refs, suppress([...team, ...opposing].sort((a, b) => b.score - a.score)), size);
  }

  /**
   * Portraits missed by the searches, recovered from the grid the found ones
   * define: each column's x and the rows' uniform pitch give every slot,
   * and an empty slot is classified in place, at half the free-search margin
   * since the slot itself vouches for it. A column keeps its strongest
   * MAX_ROWS-tall window.
   */
  function fillColumns(raster, refs, found, size) {
    const columns = [];
    for (const hit of [...found].sort((a, b) => b.score - a.score)) {
      const column = columns.find((c) => Math.abs(c.x - hit.x) <= size / 2);
      if (column) column.hits.push(hit);
      else columns.push({ x: hit.x, hits: [hit] });
    }
    const ys = [...new Set(found.map((h) => Math.round(centreY(h))))].sort((a, b) => a - b);
    const gaps = [];
    for (let i = 1; i < ys.length; i += 1) if (ys[i] - ys[i - 1] > size / 2 && ys[i] - ys[i - 1] < size * 2.5) gaps.push(ys[i] - ys[i - 1]);
    const pitch = median(gaps);
    if (!pitch || columns.length > 2) return found;
    const all = [];
    for (const column of columns) {
      const x = Math.round(median(column.hits.map((h) => h.x)));
      const slot = new Map(column.hits.map((h) => [Math.round((centreY(h) - ys[0]) / pitch), h]));
      const known = [...slot.keys()].sort((a, b) => a - b);
      const filled = [];
      for (let k = known[0] - MAX_ROWS + 1; k <= known[known.length - 1] + MAX_ROWS - 1; k += 1) {
        const y = Math.round(ys[0] + k * pitch - size / 2);
        if (y < 0 || y + size > raster.height) continue;
        const hit = slot.get(k) || verify(raster, { x, y, size }, refs, "champion", true);
        filled.push(hit && hit.score >= MIN_SCORE.champion && hit.gap >= MIN_GAP.champion / 2 ? hit : null);
      }
      let best = null;
      for (let start = 0; start < filled.length; start += 1) {
        const window = filled.slice(start, start + MAX_ROWS);
        const strength = window.reduce((sum, hit) => sum + (hit ? hit.score : 0), 0);
        if (!best || strength > best.strength) best = { window, strength };
      }
      if (best) all.push(...best.window.filter(Boolean));
    }
    return all;
  }

  /** Group hits into rows by centre y, tolerance half a portrait. */
  function rows(hits, size) {
    const sorted = [...hits].sort((a, b) => centreY(a) - centreY(b));
    const bands = [];
    for (const hit of sorted) {
      const band = bands[bands.length - 1];
      if (band && Math.abs(centreY(hit) - band.y) < size / 2) band.hits.push(hit);
      else bands.push({ y: centreY(hit), hits: [hit] });
    }
    return bands;
  }

  /**
   * Slots on a uniform pitch through the items a player already has, each
   * placed off its nearest known neighbour so pitch error cannot accumulate;
   * every empty position is classified so a missed icon is recovered and a
   * blank slot stays blank. The strongest MAX_SLOTS-wide window is the
   * strip, which drops whatever text past its ends resembled an icon.
   * `pitchHint` is the panel-wide pitch, preferred over the player's own
   * few gaps, which round a pixel off and drift the outer slots.
   */
  function fillStrip(raster, refs, items, itemSize, pitchHint, champion, bounds) {
    const sorted = [...items].sort((a, b) => a.x - b.x);
    if (!sorted.length) return [];
    const gaps = [];
    for (let i = 1; i < sorted.length; i += 1) {
      const gap = sorted[i].x - sorted[i - 1].x;
      if (gap < itemSize * 1.6) gaps.push(gap);
    }
    const rough = pitchHint || median(gaps) || itemSize + 1;
    const slot = sorted.map((h) => Math.round((h.x - sorted[0].x) / rough));
    const span = slot[slot.length - 1] - slot[0];
    const pitch = span ? (sorted[sorted.length - 1].x - sorted[0].x) / span : rough;
    const y = Math.round(median(sorted.map((h) => h.y)));
    const size = Math.round(itemSize);
    const known = new Map(sorted.map((h, i) => [slot[i], h]));
    const filled = [];
    for (let k = slot[0] - 7; k <= slot[slot.length - 1] + 7; k += 1) {
      let nearest = 0;
      slot.forEach((s, i) => { if (Math.abs(s - k) < Math.abs(slot[nearest] - k)) nearest = i; });
      const x = Math.round(sorted[nearest].x + (k - slot[nearest]) * pitch);
      if (x < 0 || x + size > raster.width) continue;
      if (Math.abs(x - champion.x) < champion.size && Math.abs(y - champion.y) < champion.size) continue;
      if (bounds && (x < bounds.min || x > bounds.max)) continue;
      const hit = known.get(k) || verify(raster, { x, y, size }, refs, "item", true);
      filled.push(hit && hit.score >= FILL_SCORE && (hit.gap >= FILL_GAP || hit.score >= SURE_FILL) ? hit : null);
    }
    let best = null;
    for (let start = 0; start < filled.length; start += 1) {
      const window = filled.slice(start, start + MAX_SLOTS);
      const strength = window.reduce((sum, hit) => sum + (hit ? hit.score : 0), 0);
      if (!best || strength > best.strength) best = { window, strength };
    }
    if (!best) return [];
    const first = best.window.findIndex(Boolean);
    const last = best.window.length - 1 - [...best.window].reverse().findIndex(Boolean);
    return first < 0 ? [] : best.window.slice(first, last + 1);
  }

  /**
   * Read a whole scoreboard: rows of players, each a champion with the items
   * nearest it on its row. Rows are returned top to bottom; within a row,
   * players left to right, so a two-column broadcast panel yields
   * `[left, right]` per row and role order down the rows.
   */
  function readScoreboard(raster, refs, options = {}) {
    const levels = new Map();
    const portraitSizes = options.portraitSizes || sizesBetween(PORTRAIT.min, Math.min(PORTRAIT.max, Math.floor(raster.height / 6)));
    const first = anchor(raster, refs, portraitSizes, levels);
    if (!first) return { hits: [], rows: [] };
    const champions = portraits(raster, refs, first, levels);
    const size = first.size;
    const bands = rows(champions, size);
    const itemSizes = [0.72, 0.78, 0.85, 0.92, 1].map((share) => Math.round(size * share));
    const items = [];
    let itemSize = null;
    for (const band of bands) {
      const xs = band.hits.map((hit) => hit.x);
      const region = {
        x0: Math.min(...xs) - size * (MAX_SLOTS + 2),
        x1: Math.max(...xs) + size * (MAX_SLOTS + 3),
        y0: band.y - size * 0.6,
        y1: band.y + size * 0.6,
      };
      const trial = itemSize ? [itemSize] : itemSizes;
      let bestForBand = null;
      for (const candidate of trial) {
        const found = search(raster, refs, "item", candidate, region, levels)
          .filter((hit) => Math.abs(centreY(hit) - band.y) <= size * 0.4);
        const sure = found.filter((hit) => hit.score >= SURE_SCORE);
        const strength = sure.reduce((sum, hit) => sum + hit.score, 0);
        if (!bestForBand || strength > bestForBand.strength) bestForBand = { found, sure, strength };
      }
      if (!itemSize && bestForBand.sure.length >= 3) itemSize = median(bestForBand.sure.map((h) => h.size));
      items.push(...bestForBand.found);
    }
    const strip = itemSize || size * 0.8;
    const neighbours = [];
    for (const band of bands) {
      const xs = items.filter((hit) => Math.abs(centreY(hit) - band.y) <= size * 0.5).map((hit) => hit.x).sort((a, b) => a - b);
      for (let i = 1; i < xs.length; i += 1) if (xs[i] - xs[i - 1] < strip * 1.6) neighbours.push(xs[i] - xs[i - 1]);
    }
    const pitchHint = median(neighbours);
    const result = bands.map((band) => {
      const players = band.hits.sort((a, b) => a.x - b.x);
      const owned = players.map(() => []);
      for (const item of items) {
        if (Math.abs(centreY(item) - band.y) > size * 0.5) continue;
        let nearest = 0;
        players.forEach((p, i) => {
          if (Math.abs(p.x - item.x) < Math.abs(players[nearest].x - item.x)) nearest = i;
        });
        owned[nearest].push(item);
      }
      return players.map((champion, i) => {
        const left = players.filter((p) => p.x < champion.x).map((p) => p.x);
        const right = players.filter((p) => p.x > champion.x).map((p) => p.x);
        const bounds = {
          min: left.length ? (champion.x + Math.max(...left)) / 2 : -Infinity,
          max: right.length ? (champion.x + Math.min(...right)) / 2 : Infinity,
        };
        return { champion, items: fillStrip(raster, refs, owned[i], strip, pitchHint, champion, bounds) };
      });
    });
    return { hits: [...champions, ...items], rows: result };
  }

  return { fingerprint, buildReferences, classify, coarseSearch, verify, readScoreboard, MIN_SCORE, MIN_CONTRAST };
})();

/* --- page wiring ------------------------------------------------------- */

(function initScoreboardAutofill() {
  "use strict";
  if (typeof document === "undefined" || !document.getElementById || typeof loadSharedBuildIntoAnalyst !== "function") return;

  const ROLES = ["top", "jungle", "mid", "bottom", "support"];
  let references = null;

  async function loadReferences() {
    if (references) return references;
    const index = await (await fetch("/static/icon-sprite.json")).json();
    const image = await new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("The icon sprite did not load."));
      img.src = "/static/icon-sprite.webp";
    });
    references = ScoreboardVision.buildReferences(rasterOf(image), index);
    return references;
  }

  function rasterOf(source, maxWidth = 2200) {
    const scale = Math.min(1, maxWidth / source.width);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(source.width * scale);
    canvas.height = Math.round(source.height * scale);
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.drawImage(source, 0, 0, canvas.width, canvas.height);
    const raster = context.getImageData(0, 0, canvas.width, canvas.height);
    raster.scale = scale;
    return raster;
  }

  function loadImage(blob) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(blob);
      const img = new Image();
      img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("That file is not an image the browser can open.")); };
      img.src = url;
    });
  }

  /**
   * The reading as the share loader expects it: names, not ids, boots split
   * out. The items also settle the role quest, which the backend enforces:
   * tier-3 boots and an upgraded support item exist only once the quest is
   * done, and any support quest item puts the player in the support role.
   */
  function payloadFor(reading, attackerIndex, level) {
    const players = reading.rows.flatMap((row, r) => row.map((p, side) => ({ ...p, role: ROLES[r] || "", side })));
    const attacker = players[attackerIndex];
    const loadout = (player) => {
      const ids = player.items.filter(Boolean).map((hit) => Number(hit.key)).filter((id) => getItem(id));
      const boots = ids.find((id) => isRoleBoot(id));
      const tier = Number(engine.boots.find((item) => Number(item.id) === boots)?.tier);
      const questStages = ids.map((id) => getItem(id).supportQuestStage).filter(Boolean);
      return {
        champion: player.champion.key,
        level,
        role: questStages.length ? "support" : player.role,
        role_quest_complete: tier >= 3 || questStages.includes("upgraded"),
        items: ids.filter((id) => id !== boots).map((id) => itemName(id)),
        boots: boots ? itemName(boots) : "",
      };
    };
    return {
      ...loadout(attacker),
      enemies: players.filter((p) => p.side !== attacker.side).map(loadout),
      allies: players.filter((p) => p.side === attacker.side && p !== attacker).map(loadout),
    };
  }

  /* --- review sheet ---------------------------------------------------- */

  const dialog = document.getElementById("scoreboardDialog");
  const preview = document.getElementById("scoreboardPreview");
  const table = document.getElementById("scoreboardRows");
  const status = document.getElementById("scoreboardStatus");
  const apply = document.getElementById("scoreboardApply");
  let current = null;

  function say(text) { if (status) status.textContent = text; }

  function drawPreview(image, reading, scale) {
    const width = 720;
    const ratio = width / image.width;
    preview.width = width;
    preview.height = Math.round(image.height * ratio);
    const context = preview.getContext("2d");
    context.drawImage(image, 0, 0, preview.width, preview.height);
    context.lineWidth = 2;
    reading.rows.flat().forEach((player) => {
      [player.champion, ...player.items.filter(Boolean)].forEach((hit) => {
        context.strokeStyle = hit.kind === "champion" ? "#2f7d4f" : hit.gap < 0.08 ? "#c8891a" : "#e8dcc0";
        context.strokeRect((hit.x / scale) * ratio, (hit.y / scale) * ratio, (hit.size / scale) * ratio, (hit.size / scale) * ratio);
      });
    });
  }

  function renderRows(reading) {
    const players = reading.rows.flatMap((row, r) => row.map((p, side) => ({ ...p, row: r, side })));
    table.innerHTML = players.map((player, index) => {
      const champion = getChampion(player.champion.key);
      const items = player.items.map((hit) => {
        if (!hit) return '<span class="scoreboard-item is-empty" title="Empty slot"></span>';
        const item = getItem(Number(hit.key));
        const flag = !item ? " is-unknown" : hit.gap < 0.08 ? " is-unsure" : "";
        const title = `${item ? item.name : "Not a buildable item"} · ${(hit.score * 100).toFixed(0)}%`;
        return `<span class="scoreboard-item${flag}" title="${escapeHtml(title)}"><img src="${itemImage(hit.key)}" alt="${escapeHtml(item ? item.name : hit.key)}" /></span>`;
      }).join("");
      const known = Boolean(champion);
      return `<label class="scoreboard-player${known ? "" : " is-unknown"}">
        <input type="radio" name="scoreboardAttacker" value="${index}" ${index === 0 ? "checked" : ""} ${known ? "" : "disabled"} />
        <span class="scoreboard-side">${(player.champion.score * 100).toFixed(0)}% · ${player.side ? "Right" : "Left"} · ${ROLES[player.row] || "row " + (player.row + 1)}${known ? "" : " · not modeled"}</span>
        <img class="scoreboard-portrait" src="${championImage(player.champion.key)}" alt="" />
        <strong>${escapeHtml(player.champion.key)}</strong>
        <span class="scoreboard-items">${items}</span>
      </label>`;
    }).join("");
  }

  async function readBlob(blob) {
    if (!dialog) return;
    dialog.showModal();
    say("Reading the scoreboard…");
    table.innerHTML = "";
    apply.disabled = true;
    try {
      const [refs, image] = await Promise.all([loadReferences(), loadImage(blob)]);
      const raster = rasterOf(image);
      /* ceiling: the read blocks the page for a few seconds; a worker if that grates. */
      await new Promise((resolve) => setTimeout(resolve, 30));
      const started = performance.now();
      const reading = ScoreboardVision.readScoreboard(raster, refs);
      const players = reading.rows.flat().length;
      drawPreview(image, reading, raster.scale);
      renderRows(reading);
      current = { reading };
      const items = reading.rows.flat().reduce((n, p) => n + p.items.filter(Boolean).length, 0);
      say(players
        ? `Found ${players} champions and ${items} items in ${((performance.now() - started) / 1000).toFixed(1)}s. Pick your champion, then load.`
        : "No scoreboard found. Paste a frame with the full item panel showing.");
      apply.disabled = !players;
    } catch (error) {
      say(error.message || String(error));
    }
  }

  apply?.addEventListener("click", () => {
    if (!current) return;
    const picked = Number(table.querySelector('input[name="scoreboardAttacker"]:checked')?.value || 0);
    loadSharedBuildIntoAnalyst(payloadFor(current.reading, picked, state.attacker.level));
    dialog.close();
  });
  document.getElementById("scoreboardClose")?.addEventListener("click", () => dialog.close());

  document.addEventListener("paste", (event) => {
    const file = [...(event.clipboardData?.files || [])].find((f) => f.type.startsWith("image/"));
    if (!file || event.target?.closest?.("input, textarea")) return;
    event.preventDefault();
    readBlob(file);
  });
  const picker = document.getElementById("scoreboardFile");
  picker?.addEventListener("change", () => { if (picker.files[0]) readBlob(picker.files[0]); picker.value = ""; });
  document.getElementById("scoreboardPaste")?.addEventListener("click", () => picker?.click());
})();
