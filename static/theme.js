/**
 * Sitewide light / dark appearance. Persists via localStorage when preference cookies
 * are allowed, otherwise sessionStorage for the current tab only.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "rgee_theme_v1";
  var SESSION_KEY = "rgee_theme_session";

  function prefsAllowed() {
    return window.RGEE && window.RGEE.consent && window.RGEE.consent.preferencesAllowed();
  }

  function isLight() {
    return document.documentElement.getAttribute("data-theme") === "light";
  }

  function persistTheme(light) {
    try {
      if (prefsAllowed()) {
        sessionStorage.removeItem(SESSION_KEY);
        if (light) localStorage.setItem(STORAGE_KEY, "light");
        else localStorage.removeItem(STORAGE_KEY);
      } else {
        if (light) sessionStorage.setItem(SESSION_KEY, "light");
        else sessionStorage.removeItem(SESSION_KEY);
      }
    } catch (e) {
      /* private mode */
    }
  }

  function applyTheme(light) {
    var root = document.documentElement;
    if (light) root.setAttribute("data-theme", "light");
    else root.removeAttribute("data-theme");
    persistTheme(light);
  }

  function syncButton(btn) {
    if (!btn) return;
    var light = isLight();
    btn.setAttribute("aria-label", light ? "Switch to dark mode" : "Switch to light mode");
    btn.setAttribute("title", light ? "Dark mode" : "Light mode");
  }

  function init() {
    var btn = document.getElementById("theme-toggle");
    syncButton(btn);
    if (!btn) return;

    btn.addEventListener("click", function () {
      applyTheme(!isLight());
      syncButton(btn);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
