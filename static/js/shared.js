/*!
 * shared.js — what more than one of the page's scripts needs.
 *
 * The HTML escaper eventorder.js and feedback.js bind at load, so index.html
 * loads this script before them and tests/test_redesign_frontend.py holds
 * that order. Both this file and app.js merge onto window.scryglass rather
 * than assigning it, so the namespace itself survives either load order.
 * app.js keeps its own narrower escapeHtml, which scoreboard.js resolves off
 * the page's global scope.
 */
(function () {
  "use strict";

  var shared = (window.scryglass = window.scryglass || {});

  shared.escapeHtml = function (value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  };
})();
