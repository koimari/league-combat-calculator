/*!
 * shared.js — what more than one of the page's scripts needs.
 *
 * One HTML escaper for the whole page: a second copy is a second thing to
 * fix when an escape is found missing, which is the one duplication with a
 * security edge. Publishes onto window.scryglass, the surface app.js also
 * merges its request helpers onto, so the two load in either order.
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
