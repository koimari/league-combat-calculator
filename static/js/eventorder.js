/*!
 * eventorder.js — F2 optimal event-order panel.
 *
 * Self-contained module: renders the fight's cast sequence as a chip rail
 * plus the combo rationale from the /api/calculate "rotation" receipt, so
 * the UI can show WHY the order is optimal ("Q poisons, E consumes").
 *
 * The module never depends on app.js internals.  It installs a read-only
 * wrapper around window.fetch BEFORE app.js fires its first request, so it
 * captures each /api/calculate response the app already makes — no extra
 * API calls, no response mutation, and the app's own promise chain is
 * untouched.  It renders into the optional #eventOrderPanel mount point
 * (templates/index.html) and stays hidden when no rotation receipt exists.
 */
(function () {
  "use strict";

  var MOUNT_ID = "eventOrderPanel";
  var STYLE_ID = "scryglass-event-order-style";
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

  /* ------------------------------------------------------------------ *
   * Minimal self-contained styles (no static/css edits).
   * ------------------------------------------------------------------ */

  function installStyle() {
    if (byId(STYLE_ID)) return;
    var style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent =
      "#eventOrderPanel{display:block;margin:14px 0 0;padding:14px 16px;" +
      "border:1px solid rgba(127,127,127,.25);border-radius:12px;" +
      "background:linear-gradient(180deg,rgba(255,255,255,.03),rgba(255,255,255,0));}" +
      "#eventOrderPanel[hidden]{display:none;}" +
      ".event-order-head{display:flex;align-items:baseline;gap:8px;margin-bottom:10px;}" +
      ".event-order-head .micro-label{font-size:11px;letter-spacing:.08em;" +
      "text-transform:uppercase;color:rgba(235,235,235,.55);}" +
      ".event-order-head .event-order-mode{margin-left:auto;font-size:11px;" +
      "color:rgba(235,235,235,.45);}" +
      ".event-order-rail{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;}" +
      ".event-order-chip{display:inline-flex;align-items:center;gap:5px;" +
      "padding:4px 9px;border-radius:999px;font-size:12px;line-height:1;" +
      "background:rgba(127,127,127,.14);border:1px solid rgba(127,127,127,.22);}" +
      ".event-order-chip b{font-weight:700;letter-spacing:.02em;}" +
      ".event-order-chip small{color:rgba(235,235,235,.5);}" +
      ".event-order-chip.setup{border-color:rgba(120,200,255,.5);" +
      "background:rgba(120,200,255,.12);}" +
      ".event-order-chip.consume{border-color:rgba(255,180,120,.5);" +
      "background:rgba(255,180,120,.12);}" +
      ".event-order-why{margin:0;font-size:13px;line-height:1.55;" +
      "color:rgba(235,235,235,.85);}" +
      ".event-order-why .why-label{display:block;font-size:11px;" +
      "letter-spacing:.08em;text-transform:uppercase;" +
      "color:rgba(235,235,235,.5);margin-bottom:4px;}" +
      ".event-order-sources{margin:8px 0 0;padding:8px 10px 0;border-top:" +
      "1px dashed rgba(127,127,127,.3);font-size:11px;line-height:1.5;" +
      "color:rgba(235,235,235,.45);}" +
      ".event-order-sources li{margin:0 0 2px;}";
    (document.head || document.documentElement).appendChild(style);
  }

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
   * Capture: read-only wrapper around the app's own fetch.
   * ------------------------------------------------------------------ */

  function capturePayload(payload) {
    if (!payload || typeof payload !== "object" || payload.error) return;
    latest = payload;
    render(payload);
  }

  function installFetchCapture() {
    if (!window.fetch || window.__scryglassEventOrderCapture) return;
    window.__scryglassEventOrderCapture = true;
    var originalFetch = window.fetch;
    window.fetch = function () {
      var promise = originalFetch.apply(this, arguments);
      try {
        var url = arguments[0];
        if (typeof url === "string" && url.indexOf("/api/calculate") !== -1) {
          promise.then(function (response) {
            try {
              response.clone().json().then(capturePayload);
            } catch (error) {
              // Non-JSON or already-consumed body — ignore, never break the app.
            }
          }).catch(function () {
            // Capture failures are invisible to the app's own promise chain.
          });
        }
      } catch (error) {
        // Never let the capture break the app's own request.
      }
      return promise;
    };
  }

  /* ------------------------------------------------------------------ *
   * Re-render when the result area changes (mount appears late, build
   * comparison flips, etc.) — only with the last captured payload.
   * ------------------------------------------------------------------ */

  function installObserver() {
    var target = document.querySelector(".result-column") || document.body;
    if (!window.MutationObserver) return;
    var observer = new MutationObserver(function () {
      if (latest) render(latest);
    });
    observer.observe(target, { childList: true, subtree: true });
  }

  installStyle();
  installFetchCapture();
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
