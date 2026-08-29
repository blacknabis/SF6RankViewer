"use strict";

(function exposeDashboardViewer(root, factory) {
  const api = Object.freeze(factory());
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else if (root) {
    root.SF6DashboardViewer = api;
  }
})(typeof globalThis === "object" ? globalThis : this, function createDashboardViewerBoundary() {
  function create(options) {
    const dependencies = options && typeof options === "object" ? options : {};
    if (!dependencies.document || typeof dependencies.document.getElementById !== "function") {
      throw new TypeError("document dependency is required");
    }
    if (!dependencies.metrics || typeof dependencies.metrics !== "object") {
      throw new TypeError("metrics dependency is required");
    }

    return Object.freeze({
      renderAggregate() {},
      renderFeed() {},
      setRegionState() {},
      bindInteractions() {}
    });
  }

  return { create };
});
