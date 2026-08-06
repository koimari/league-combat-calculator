/*!
 * feedback.js — P7 validation-loop widget.
 *
 * Self-contained module: renders a compact "Did this match your game?"
 * (Yes / No / Off by X%) control plus a combat-log paste importer into the
 * results area, and posts game-receipts to POST /api/receipts.
 *
 * The widget never depends on app.js internals.  It prefers a page-level
 * hook when the P5 app exposes one:
 *
 *     window.scryglass = { getCurrentLoadout: () => ({...calculate payload}) }
 *
 * and otherwise captures the visible scenario from the DOM (champion,
 * level, role, build A items, ability ranks, champion options, fight
 * window, keystone).  It must never break when the results area is absent,
 * so every DOM lookup is null-safe and the mount point is optional.
 */
(function () {
  "use strict";

  var MOUNT_ID = "feedbackWidget";
  var RESULT_AREA_SELECTOR = ".result-column";
  var SLOT_LETTERS = ["P", "Q", "W", "E", "R"];
  var STATE = {
    action: null,
    loadout: null,
    champion: null,
    level: null,
    busy: false,
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function one(selector, root) {
    return (root || document).querySelector(selector);
  }

  function textOf(node) {
    return node ? String(node.textContent || "").trim() : "";
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

  function hookLoadout() {
    if (
      window.scryglass &&
      typeof window.scryglass.getCurrentLoadout === "function"
    ) {
      try {
        var captured = window.scryglass.getCurrentLoadout();
        if (captured && typeof captured === "object") return captured;
      } catch (error) {
        // Fall through to DOM capture; never let the hook break the widget.
      }
    }
    return null;
  }

  function captureFromDom() {
    var championNode = byId("championName");
    var champion = textOf(championNode);
    if (!champion || champion === "Choose a champion") return null;

    var level = numberValue(byId("levelInput"));
    if (level == null) level = numberValue(byId("levelOutput"));
    var roleSelect = byId("roleSelect");
    var role = roleSelect ? String(roleSelect.value || "") : "";

    var items = [];
    var boots = "";
    var slots = byId("slotsA");
    if (slots) {
      var slotButtons = slots.querySelectorAll("button.slot:not(.empty-slot)");
      Array.prototype.forEach.call(slotButtons, function (button) {
        var image = one("img", button);
        var name = image ? String(image.getAttribute("alt") || "").trim() : "";
        if (!name) return;
        if (String(button.getAttribute("data-path") || "").indexOf("questBoot") !== -1) {
          boots = name;
        } else if (items.indexOf(name) === -1) {
          items.push(name);
        }
      });
    }

    var abilityRanks = {};
    var abilityRow = byId("abilityRow");
    if (abilityRow) {
      var rankButtons = abilityRow.querySelectorAll("[data-ability-rank]");
      Array.prototype.forEach.call(rankButtons, function (button) {
        var slot = String(button.getAttribute("data-ability-rank") || "").trim();
        if (!slot) return;
        var output = button.parentElement ? one("output", button.parentElement) : null;
        var rank = numberValue(output);
        if (rank != null) abilityRanks[slot] = Math.max(0, Math.floor(rank));
      });
    }

    var championOptions = {};
    var optionRow = byId("championOptionsRow");
    if (optionRow) {
      var optionControls = optionRow.querySelectorAll("[data-champion-option]");
      Array.prototype.forEach.call(optionControls, function (control) {
        var key = String(control.getAttribute("data-champion-option") || "").trim();
        if (!key) return;
        var optionType = String(control.getAttribute("data-option-type") || "");
        if (control.type === "checkbox") {
          championOptions[key] = control.checked;
        } else if (optionType === "select" || control.tagName === "SELECT") {
          championOptions[key] = control.value;
        } else {
          var numeric = Number(control.value);
          if (Number.isFinite(numeric)) championOptions[key] = numeric;
        }
      });
    }

    var rotations = numberValue(byId("rotationRange"));
    if (rotations == null) rotations = 1;
    var duration = numberValue(byId("durationRange"));
    if (duration == null) duration = 10;
    var uptimeModeToggle = byId("uptimeModeToggle");
    var explicitUptime = uptimeModeToggle
      ? String(uptimeModeToggle.getAttribute("aria-pressed")) === "true"
      : false;
    var uptime = numberValue(byId("uptimeRange"));
    if (uptime == null) uptime = 0;
    uptime = explicitUptime ? uptime / 100 : 0;

    var keystone = "";
    var keystoneSlot = one("#slotsA .keystone-slot");
    if (keystoneSlot) {
      var keystoneName = textOf(one("small", keystoneSlot));
      if (keystoneName && keystoneName !== "Add keystone") keystone = keystoneName;
    }

    var enemyCount = numberValue(byId("enemyCount")) || 0;
    var fightMode = rotations > 1 || uptime > 0 ? "time_based" : "one_rotation";
    return {
      champion: champion,
      level: Math.max(1, Math.min(18, Math.floor(level || 1))),
      role: role,
      items: items,
      boots: boots,
      ability_ranks: abilityRanks,
      champion_options: championOptions,
      keystone: keystone,
      rotations: Math.max(1, Math.min(6, Math.floor(rotations))),
      fight_mode: fightMode,
      fight_duration: duration,
      include_auto_attacks: uptime > 0,
      auto_attack_uptime: uptime,
      auto_attack_uptime_mode: explicitUptime ? "explicit" : "calculated",
      enemies: [],
      allies: [],
      _snapshot: {
        itemCount: items.length,
        rankCount: Object.keys(abilityRanks).length,
        optionCount: Object.keys(championOptions).length,
        enemyCount: enemyCount,
      },
    };
  }

  function captureLoadout() {
    var loadout = hookLoadout() || captureFromDom();
    if (!loadout) return null;
    STATE.champion = loadout.champion;
    STATE.level = loadout.level;
    return loadout;
  }

  /* ------------------------------------------------------------------ *
   * Rendering
   * ------------------------------------------------------------------ */

  function injectStyles() {
    if (byId("feedbackWidgetStyles")) return;
    var style = document.createElement("style");
    style.id = "feedbackWidgetStyles";
    style.textContent =
      ".feedback-widget{margin-top:14px;padding:12px 14px;border:1px solid #2d2d2d;" +
      "border-radius:10px;background:#161616;color:#e8e4d8;font:12px/1.45 system-ui,sans-serif}" +
      ".feedback-widget summary{cursor:pointer;font-weight:700;letter-spacing:.02em}" +
      ".feedback-widget .feedback-context{margin:8px 0;color:#a9a49a}" +
      ".feedback-widget .feedback-context b{color:#f1eddf}" +
      ".feedback-widget .feedback-actions{display:flex;gap:8px;flex-wrap:wrap}" +
      ".feedback-widget button{border:1px solid #3a3a3a;background:#222;color:#e8e4d8;" +
      "padding:5px 12px;border-radius:8px;cursor:pointer;font:inherit}" +
      ".feedback-widget button:hover,.feedback-widget button:focus-visible{border-color:#8f8a7c}" +
      ".feedback-widget button[aria-pressed=\"true\"]{border-color:#c5120b;background:#3a1715}" +
      ".feedback-widget .feedback-fields{display:grid;gap:8px;margin-top:10px}" +
      ".feedback-widget label{display:flex;gap:8px;align-items:center;color:#a9a49a;flex-wrap:wrap}" +
      ".feedback-widget input[type=\"number\"],.feedback-widget select,.feedback-widget textarea{" +
      "background:#202020;border:1px solid #3a3a3a;color:#f1eddf;border-radius:6px;padding:4px 6px;font:inherit}" +
      ".feedback-widget textarea{width:100%;box-sizing:border-box;resize:vertical}" +
      ".feedback-widget .feedback-paste{margin-top:10px}" +
      ".feedback-widget .feedback-status{margin:8px 0 0;color:#c9c3b4}" +
      ".feedback-widget .feedback-status.is-error{color:#ff8f87}";
    document.head.appendChild(style);
  }

  function statusMarkup() {
    var context;
    if (!STATE.champion) {
      context = "Choose a champion and complete a build to record a game receipt.";
    } else {
      var snapshot = (STATE.loadout && STATE.loadout._snapshot) || {};
      var parts = [
        "Lv " + (STATE.level || "—"),
        (snapshot.itemCount != null ? snapshot.itemCount : (STATE.loadout && STATE.loadout.items ? STATE.loadout.items.length : 0)) + " items",
        "loadout snapshot",
      ];
      if (snapshot.enemyCount > 0) {
        parts.push("multi-target roster — receipt uses the solo default target");
      }
      context = "Recording validation for <b>" + escapeHtml(STATE.champion) + "</b> (" + parts.join(" · ") + ")";
    }
    return (
      '<p class="feedback-context">' + context + "</p>" +
      '<div class="feedback-actions">' +
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
      '<p class="feedback-status" role="status" hidden></p>'
    );
  }

  function render() {
    var mount = byId(MOUNT_ID);
    if (!mount) mount = one(RESULT_AREA_SELECTOR);
    if (!mount) return null; // results area absent — stay silent
    injectStyles();
    STATE.loadout = captureLoadout();
    if (!mount.classList.contains("feedback-widget")) {
      mount.classList.add("feedback-widget");
    }
    mount.setAttribute("data-feedback-widget", "1");
    mount.innerHTML = statusMarkup();
    return mount;
  }

  function refreshContext() {
    var mount = byId(MOUNT_ID) || one(RESULT_AREA_SELECTOR);
    if (!mount || !mount.hasAttribute("data-feedback-widget")) return;
    STATE.loadout = captureLoadout();
    var context = one(".feedback-context", mount);
    if (!context) return;
    context.innerHTML = statusMarkup().match(
      /<p class="feedback-context">[\s\S]*?<\/p>/
    )[0];
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
    document.addEventListener("click", onDocumentClick);
    document.addEventListener("click", function () {
      refreshContext();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
