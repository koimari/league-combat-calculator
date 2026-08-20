/*!
 * feedback.js — P7 validation-loop widget.
 *
 * Self-contained module: renders a compact "Did this match your game?"
 * (Yes / No / Off by X%) control plus a combat-log paste importer into the
 * results area, and posts game-receipts to POST /api/receipts.
 *
 * The scenario comes from the page-level hook app.js publishes:
 *
 *     window.scryglass.getCurrentLoadout()
 *
 * the exact /api/calculate payload behind the displayed result, or null
 * while nothing is displayed — so a receipt's prediction is always the
 * total the user saw.  app.js fires "scryglass:result" when that payload
 * changes.  The widget never breaks when the results area is absent: every
 * DOM lookup is null-safe and the mount point is optional.
 */
(function () {
  "use strict";

  var MOUNT_ID = "feedbackWidget";
  var RESULT_AREA_SELECTOR = ".canvas";
  var STATE = {
    action: null,
    loadout: null,
    champion: null,
    busy: false,
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function one(selector, root) {
    return (root || document).querySelector(selector);
  }

  function numberValue(node) {
    if (!node) return null;
    var value = Number(String(node.value != null ? node.value : node.textContent).trim());
    return Number.isFinite(value) ? value : null;
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /* ------------------------------------------------------------------ *
   * Loadout capture
   * ------------------------------------------------------------------ */

  function captureLoadout() {
    var hook = window.scryglass && window.scryglass.getCurrentLoadout;
    var loadout = typeof hook === "function" ? hook() : null;
    if (!loadout) {
      // Nothing displayed: clear the stale identity so the widget falls
      // silent instead of validating a number that left the screen.
      STATE.champion = null;
      return null;
    }
    STATE.champion = loadout.champion;
    return loadout;
  }

  /* ------------------------------------------------------------------ *
   * Rendering
   * ------------------------------------------------------------------ */

  // The widget's look lives in static/css/style.css with the rest of the
  // design language; this module owns behaviour only.

  function count(n, singular, plural) {
    return n + " " + (n === 1 ? singular : plural);
  }

  function contextHtml() {
    var loadout = STATE.loadout;
    var parts = [
      "Lv " + loadout.level,
      count(loadout.items.length, "item", "items"),
      count(loadout.enemies.length, "enemy", "enemies"),
    ];
    return "Recording validation for <b>" + escapeHtml(loadout.champion) + "</b> (" + parts.join(" · ") + ")";
  }

  function statusMarkup() {
    return (
      '<details class="feedback-disclosure">' +
      "<summary>Validate against a real game</summary>" +
      '<div class="feedback-body">' +
      '<p class="feedback-context">' + contextHtml() + "</p>" +
      '<div class="feedback-actions">' +
      "<span>Did this match your game?</span> " +
      '<button type="button" data-fb-action="yes">Yes</button>' +
      '<button type="button" data-fb-action="no">No</button>' +
      '<button type="button" data-fb-action="off">Off by %</button>' +
      "</div>" +
      '<div class="feedback-fields" hidden>' +
      '<label>Damage you saw in game <input type="number" id="fbObserved" min="0" step="any" placeholder="e.g. 1234" /></label>' +
      '<label id="fbOffRow" hidden>Off by <input type="number" id="fbOffPct" min="0" max="1000" step="any" /> % ' +
      '<select id="fbOffDir"><option value="higher">higher</option><option value="lower">lower</option></select></label>' +
      '<span><button type="button" data-fb-submit>Submit</button> ' +
      '<button type="button" data-fb-cancel>Cancel</button></span>' +
      "</div>" +
      '<details class="feedback-paste"><summary>Paste a combat log instead</summary>' +
      '<label><textarea id="fbPaste" rows="4" placeholder="Q 347.2&#10;W 154&#10;total 997"></textarea></label>' +
      '<button type="button" data-fb-paste-submit>Import paste</button></details>' +
      '<p class="feedback-status" role="status" hidden></p>' +
      "</div></details>"
    );
  }

  function render() {
    var mount = byId(MOUNT_ID);
    if (!mount) mount = one(RESULT_AREA_SELECTOR);
    if (!mount) return null; // results area absent — stay silent
    STATE.loadout = captureLoadout();
    if (!mount.classList.contains("feedback-widget")) {
      mount.classList.add("feedback-widget");
    }
    mount.setAttribute("data-feedback-widget", "1");
    // No champion means nothing to validate: stay silent instead of leading
    // the canvas with Yes/No buttons about a scenario that does not exist.
    mount.innerHTML = STATE.champion ? statusMarkup() : "";
    return mount;
  }

  function refreshContext() {
    var mount = byId(MOUNT_ID) || one(RESULT_AREA_SELECTOR);
    if (!mount || !mount.hasAttribute("data-feedback-widget")) return;
    STATE.loadout = captureLoadout();
    var context = one(".feedback-context", mount);
    var hasWidget = Boolean(context);
    if (Boolean(STATE.champion) !== hasWidget) {
      // Presence changed (champion picked or cleared): rebuild the widget.
      render();
      return;
    }
    // Same presence: update the context line in place so an open disclosure
    // and any half-typed fields survive the refresh.
    if (context) context.innerHTML = contextHtml();
  }

  /* ------------------------------------------------------------------ *
   * Interaction
   * ------------------------------------------------------------------ */

  function showStatus(message, isError) {
    var status = one(".feedback-status", byId(MOUNT_ID) || document);
    if (!status) return;
    status.textContent = message;
    status.classList.toggle("is-error", Boolean(isError));
    status.hidden = false;
  }

  function setBusy(busy) {
    STATE.busy = busy;
    var buttons = document.querySelectorAll("[data-fb-action],[data-fb-submit],[data-fb-paste-submit]");
    Array.prototype.forEach.call(buttons, function (button) {
      button.disabled = busy;
    });
  }

  function observedFromAction() {
    if (STATE.action === "yes") return undefined; // confirmation receipt
    if (STATE.action === "no") {
      var observed = numberValue(byId("fbObserved"));
      if (observed == null || observed < 0) {
        showStatus("Enter the damage you saw in game first.", true);
        return null;
      }
      return { tdd: observed };
    }
    if (STATE.action === "off") {
      var percent = numberValue(byId("fbOffPct"));
      if (percent == null || percent < 0) {
        showStatus("Enter the percentage difference first.", true);
        return null;
      }
      var direction = byId("fbOffDir") ? byId("fbOffDir").value : "higher";
      return { off_by_percent: percent, direction: direction };
    }
    return null;
  }

  function postReceipt(observed) {
    var loadout = captureLoadout();
    if (!loadout) {
      showStatus("Nothing to record: choose a champion and complete a build.", true);
      return;
    }
    var payload = { champion: loadout.champion, loadout: loadout, source: "manual" };
    if (observed !== undefined) payload.observed = observed;
    setBusy(true);
    fetch("/api/receipts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (response) {
        return response.json().then(function (body) {
          return { ok: response.ok, body: body };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          showStatus(
            "Receipt failed: " + (result.body && result.body.error ? result.body.error : "request error"),
            true
          );
          return;
        }
        var body = result.body;
        var verdict = body.matched ? "matched" : "mismatch";
        var percent = body.predicted && body.predicted.tdd
          ? (Math.abs(body.delta) / body.predicted.tdd) * 100
          : 0;
        showStatus(
          "Recorded #" + body.feedback_id + " · " + verdict + " · Δ " +
          body.delta + " (" + percent.toFixed(1) + "%) · model predicted " +
          body.predicted.tdd
        );
        refreshContext();
      })
      .catch(function (error) {
        showStatus("Receipt request failed: " + error.message, true);
      })
      .finally(function () {
        setBusy(false);
      });
  }

  function onDocumentClick(event) {
    var target = event.target;
    if (!target || !target.closest) return;
    if (target.closest("#" + MOUNT_ID) || target.closest(RESULT_AREA_SELECTOR)) {
      // widget-internal interactions only
    } else {
      return;
    }
    var actionButton = target.closest("[data-fb-action]");
    if (actionButton) {
      var action = String(actionButton.getAttribute("data-fb-action") || "");
      if (!STATE.champion) {
        showStatus("Choose a champion and complete a build to record a receipt.", true);
        return;
      }
      STATE.action = action;
      var fields = one(".feedback-fields", byId(MOUNT_ID) || document);
      var offRow = byId("fbOffRow");
      if (fields) fields.hidden = false;
      if (offRow) offRow.hidden = action !== "off";
      var observedInput = byId("fbObserved");
      if (observedInput) observedInput.hidden = action === "off";
      var observedLabel = observedInput ? observedInput.closest("label") : null;
      if (observedLabel) observedLabel.hidden = action === "off";
      Array.prototype.forEach.call(
        document.querySelectorAll("[data-fb-action]"),
        function (button) {
          button.setAttribute("aria-pressed", String(button === actionButton));
        }
      );
      return;
    }
    if (target.closest("[data-fb-submit]")) {
      if (STATE.action === "off" && !byId("fbOffPct")) return;
      var observed = observedFromAction();
      if (observed === null) return;
      postReceipt(observed);
      return;
    }
    if (target.closest("[data-fb-cancel]")) {
      STATE.action = null;
      var fields2 = one(".feedback-fields", byId(MOUNT_ID) || document);
      if (fields2) fields2.hidden = true;
      Array.prototype.forEach.call(
        document.querySelectorAll("[data-fb-action]"),
        function (button) {
          button.removeAttribute("aria-pressed");
        }
      );
      return;
    }
    if (target.closest("[data-fb-paste-submit]")) {
      var paste = byId("fbPaste");
      var text = paste ? String(paste.value || "").trim() : "";
      if (!text) {
        showStatus("Paste a combat log or a JSON observed payload first.", true);
        return;
      }
      var loadout2 = captureLoadout();
      if (!loadout2) {
        showStatus("Nothing to record: choose a champion and complete a build.", true);
        return;
      }
      setBusy(true);
      fetch("/api/receipts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          champion: loadout2.champion,
          loadout: loadout2,
          observed: text,
          source: "combat_log",
        }),
      })
        .then(function (response) {
          return response.json().then(function (body) {
            return { ok: response.ok, body: body };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            showStatus(
              "Import failed: " + (result.body && result.body.error ? result.body.error : "request error"),
              true
            );
            return;
          }
          var body = result.body;
          var verdict = body.matched ? "matched" : "mismatch";
          showStatus(
            "Imported #" + body.feedback_id + " · " + verdict + " · Δ " + body.delta +
            " · observed " + body.observed.tdd + " vs predicted " + body.predicted.tdd
          );
          refreshContext();
        })
        .catch(function (error) {
          showStatus("Import request failed: " + error.message, true);
        })
        .finally(function () {
          setBusy(false);
        });
    }
  }

  function init() {
    var mount = byId(MOUNT_ID);
    if (!mount && !one(RESULT_AREA_SELECTOR)) return; // no results area — never break
    render();
    // A new result landed: the displayed payload changed with it.
    document.addEventListener("scryglass:result", refreshContext);
    document.addEventListener("click", function (event) {
      onDocumentClick(event);
      // The scenario may have changed with any click (champion picked,
      // items added); keep the context line honest.
      refreshContext();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
