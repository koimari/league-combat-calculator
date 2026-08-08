/* STALE badge — patch-day trust indicator (P3).

 * Self-contained module: reads /api/staleness (the patch-regression report
 * comparing the wiki cache against the game files) and patches the DOM with
 * visible "STALE · PATCH x.y" badges when the selected champion or any
 * selected item is stale.  It never modifies app.js; it observes the DOM so
 * badges stay correct as app.js re-renders slots and champion selections.
 */
(function () {
  "use strict";

  var CHAMPION_BADGE_SELECTOR = ".stale-badge--champion";
  var CHAMPION_HEADING_IDS = ["championName", "championBriefName"];
  var ITEM_BADGE_SELECTOR = ".stale-badge--item";
  var SLOT_SELECTOR = ".item-slot, .roster-item-slot";
  var ITEM_ID_PATTERN = /\/item\/(\d+)\.png/;

  var report = null;

  function badgeText() {
    return "STALE · PATCH " + (report && report.patch ? report.patch : "?");
  }

  function championName() {
    var node = document.getElementById("championName");
    return node ? node.textContent.trim() : "";
  }

  function staleChampion(name) {
    return Boolean(report && report.champions && report.champions[name] && report.champions[name].stale);
  }

  function staleItemId(id) {
    return Boolean(report && report.items && report.items[id] && report.items[id].stale);
  }

  function staleItemName(name) {
    if (!report || !report.items || !name) return false;
    var normalized = String(name).trim().toLowerCase();
    var keys = Object.keys(report.items);
    for (var i = 0; i < keys.length; i += 1) {
      var entry = report.items[keys[i]];
      if (entry && entry.stale && String(entry.name || "").toLowerCase() === normalized) {
        return true;
      }
    }
    return false;
  }

  function makeBadge(extraClass, title) {
    var badge = document.createElement("span");
    badge.className = "stale-badge" + (extraClass ? " " + extraClass : "");
    badge.textContent = badgeText();
    if (title) badge.title = title;
    badge.setAttribute("data-stale-patch", report ? report.patch : "");
    return badge;
  }

  function renderChampionBadge() {
    // Two homes for the champion name in the redesigned rail: the always
    // visible collapsed brief and the heading inside the expanded step-1
    // editor. Badge both, or a stale champion is invisible until you open
    // the editor that would have warned you.
    var name = championName();
    var isStale = Boolean(name) && staleChampion(name);
    for (var i = 0; i < CHAMPION_HEADING_IDS.length; i += 1) {
      var heading = document.getElementById(CHAMPION_HEADING_IDS[i]);
      if (!heading || !heading.parentNode) continue;
      var existing = heading.parentNode.querySelector(CHAMPION_BADGE_SELECTOR);
      if (isStale && !existing) {
        heading.parentNode.insertBefore(
          makeBadge("stale-badge--champion", name + " differs from the " + (report ? report.patch : "") + " game files"),
          heading.nextSibling
        );
      } else if (!isStale && existing) {
        existing.parentNode.removeChild(existing);
      }
    }
  }

  function itemIdFromSlot(slot) {
    var image = slot.querySelector("img");
    if (!image) return null;
    var match = ITEM_ID_PATTERN.exec(image.getAttribute("src") || "");
    return match ? match[1] : null;
  }

  function itemNameFromSlot(slot) {
    var small = slot.querySelector("small");
    if (small && small.textContent.trim()) return small.textContent.trim();
    var label = slot.getAttribute("aria-label") || "";
    var match = /^Change (.+)$/.exec(label.trim());
    return match ? match[1] : "";
  }

  function renderItemBadges() {
    var slots = document.querySelectorAll(SLOT_SELECTOR);
    for (var i = 0; i < slots.length; i += 1) {
      var slot = slots[i];
      var existing = slot.querySelector(ITEM_BADGE_SELECTOR);
      var id = itemIdFromSlot(slot);
      var name = itemNameFromSlot(slot);
      var isStale = (id && staleItemId(id)) || (!id && staleItemName(name));
      if (isStale && !existing) {
        var badge = makeBadge(
          "stale-badge--item",
          (name || id) + " differs from the " + (report ? report.patch : "") + " game files"
        );
        badge.textContent = "STALE";
        slot.appendChild(badge);
      } else if (!isStale && existing) {
        existing.parentNode.removeChild(existing);
      }
    }
  }

  var debounceTimer = null;
  function renderAll() {
    if (debounceTimer) window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(function () {
      renderChampionBadge();
      renderItemBadges();
    }, 120);
  }

  function observe() {
    var observer = new MutationObserver(function (mutations) {
      var relevant = mutations.some(function (mutation) {
        return (
          mutation.type === "characterData" ||
          (mutation.type === "childList" &&
            (mutation.target.nodeType === 1 && mutation.target.matches(SLOT_SELECTOR))) ||
          (mutation.type === "childList" && mutation.target.id === "championName") ||
          (mutation.type === "childList" && mutation.target.id === "statsGrid")
        );
      });
      if (relevant) renderAll();
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  function init() {
    fetch("/api/staleness", { credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) return null;
        return response.json();
      })
      .then(function (data) {
        report = data;
        if (!report) return;
        renderChampionBadge();
        renderItemBadges();
        observe();
      })
      .catch(function () {
        /* no report: badge simply never appears */
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
