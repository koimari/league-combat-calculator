/*!
 * eventorder.js — F2 optimal event-order panel.
 *
 * Self-contained module: renders the fight's cast sequence as a chip rail
 * plus the combo rationale from the /api/calculate "rotation" receipt, so
 * the UI can show WHY the order is optimal ("Q poisons, E consumes").
 *
 * The module never depends on app.js internals.  It listens for the
 * "scryglass:result" event app.js publishes whenever it displays a result,
 * whose detail is that receipt — no extra API calls, no wrapper around the
 * app's own request, and no load-order constraint.  It renders into the
 * optional #eventOrderPanel mount point (templates/index.html) and stays
 * hidden when no rotation receipt exists.
 */
(function () {
  "use strict";

  var MOUNT_ID = "eventOrderPanel";
  var latest = null;

  function byId(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function fmtTime(value) {
    var number = Number(value);
    if (!Number.isFinite(number)) return "0.0s";
    return (Math.round(number * 100) / 100).toFixed(2).replace(/\.?0+$/, "") + "s";
  }

  /* The panel's look lives in static/css/style.css with the rest of the
   * design language; this module owns behaviour only. */

  /* ------------------------------------------------------------------ *
   * Rendering
   * ------------------------------------------------------------------ */

  function chipClass(slot, rotation) {
    var setup = (rotation && rotation.setup) || [];
    var consume = (rotation && rotation.consume) || [];
    if (setup.indexOf(slot) !== -1) return " setup";
    if (consume.indexOf(slot) !== -1) return " consume";
    return "";
  }

  function render(payload) {
    var mount = byId(MOUNT_ID);
    if (!mount) return;
    if (!payload || !payload.rotation) {
      mount.hidden = true;
      return;
    }
    var rotation = payload.rotation;
    var order = Array.isArray(rotation.order) ? rotation.order : [];
    var timeline = Array.isArray(payload.cast_timeline) ? payload.cast_timeline : [];
    if (!order.length) {
      mount.hidden = true;
      return;
    }

    var bySlot = {};
    timeline.forEach(function (event) {
      var slot = String(event && event.slot || "");
      if (!slot) return;
      bySlot[slot] = {
        name: event.name ? String(event.name) : slot,
        time: Number(event.time),
      };
    });

    var aoe = (rotation && rotation.aoe) || {};
    var chips = order.map(function (slot) {
      var meta = bySlot[slot] || { name: slot, time: null };
      var parts = [];
      if (meta.time != null && Number.isFinite(meta.time)) {
        parts.push(escapeHtml(fmtTime(meta.time)));
      }
      var aoeTargets = Number(aoe[slot]);
      if (Number.isFinite(aoeTargets) && aoeTargets > 1) {
        parts.push("AoE \u00b7 up to " + aoeTargets + " champions");
      }
      var label = parts.length ? "<small>" + parts.join(" \u00b7 ") + "</small>" : "";
      return (
        '<span class="event-order-chip' + chipClass(slot, rotation) + '" ' +
        'title="' + escapeHtml(meta.name) + '">' +
        "<b>" + escapeHtml(String(slot)) + "</b>" + label +
        "</span>"
      );
    }).join("");

    var sources = Array.isArray(rotation.sources) && rotation.sources.length
      ? '<ul class="event-order-sources">' +
        rotation.sources.map(function (source) {
          return "<li>" + escapeHtml(source) + "</li>";
        }).join("") +
        "</ul>"
      : "";

    var lastTime = 0;
    timeline.forEach(function (event) {
      var time = Number(event && event.time);
      if (Number.isFinite(time)) lastTime = Math.max(lastTime, time);
    });
    var modeLabel = lastTime > 0
      ? "timed · " + escapeHtml(fmtTime(lastTime)) + " window"
      : "one rotation · burst";

    mount.innerHTML =
      '<div class="event-order-head">' +
      '<span class="micro-label">Event order · optimal rotation</span>' +
      '<span class="event-order-mode">' + escapeHtml(modeLabel) + "</span>" +
      "</div>" +
      '<div class="event-order-rail">' + chips + "</div>" +
      '<p class="event-order-why"><span class="why-label">Why this order</span>' +
      escapeHtml(rotation.rationale || "") + "</p>" +
      sources;
    mount.hidden = false;
  }

  /* ------------------------------------------------------------------ *
   * Capture: the receipt app.js publishes with every displayed result.
   * ------------------------------------------------------------------ */

  function capturePayload(payload) {
    if (!payload || typeof payload !== "object" || payload.error) return;
    latest = payload;
    render(payload);
  }

  function installResultListener() {
    document.addEventListener("scryglass:result", function (event) {
      capturePayload(event.detail);
    });
  }

  /* ------------------------------------------------------------------ *
   * Re-render when the result area changes (mount appears late, build
   * comparison flips, etc.) — only with the last captured payload.
   * ------------------------------------------------------------------ */

  function installObserver() {
    var target = document.querySelector(".canvas") || document.body;
    if (!window.MutationObserver) return;
    var mountEl = document.getElementById("eventOrderPanel");
    var observer = new MutationObserver(function (records) {
      // Never re-render from our own mutations: render() replaces the
      // mount's innerHTML, which would otherwise re-trigger this observer
      // forever and peg the main thread (freeze after adding an enemy).
      for (var i = 0; i < records.length; i++) {
        var node = records[i].target;
        if (node === mountEl || (mountEl && mountEl.contains(node))) return;
      }
      if (latest) render(latest);
    });
    observer.observe(target, { childList: true, subtree: true });
  }

  installResultListener();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      installObserver();
      if (latest) render(latest);
    });
  } else {
    installObserver();
    if (latest) render(latest);
  }
})();
