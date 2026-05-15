/**
 * RGEE sitewide accessibility preferences (WCAG-oriented controls).
 * Persists in localStorage; applies classes on document.documentElement.
 * Reading bar: full-width horizontal clear band; follows pointer Y immediately on each move (no easing delay).
 */
(function () {
  "use strict";

  var STORAGE_KEY = "rgee_a11y_prefs_v1";
  var SESSION_KEY = "rgee_a11y_prefs_v1_session";

  function prefsAllowed() {
    return typeof window !== "undefined" && window.RGEE && window.RGEE.consent && window.RGEE.consent.preferencesAllowed();
  }

  function defaultState() {
    return {
      cursor: "default",
      focusHighlight: false,
      highContrast: false,
      textScale: "100",
      dyslexicFont: false,
      underlineLinks: false,
      readableSpacing: false,
    };
  }

  function loadState() {
    try {
      var raw = prefsAllowed() ? localStorage.getItem(STORAGE_KEY) : sessionStorage.getItem(SESSION_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (typeof parsed !== "object" || parsed === null) return null;
      return parsed;
    } catch (e) {
      return null;
    }
  }

  function saveState(state) {
    try {
      var raw = JSON.stringify(state);
      if (prefsAllowed()) {
        localStorage.setItem(STORAGE_KEY, raw);
        sessionStorage.removeItem(SESSION_KEY);
      } else {
        sessionStorage.setItem(SESSION_KEY, raw);
      }
    } catch (e) {
      /* private mode etc. */
    }
  }

  function mergeState(saved) {
    var base = defaultState();
    if (!saved) return base;
    return {
      cursor: saved.cursor === "black" || saved.cursor === "white" ? saved.cursor : "default",
      focusHighlight: !!saved.focusHighlight,
      highContrast: !!saved.highContrast,
      textScale: ["110", "125", "150"].indexOf(saved.textScale) !== -1 ? saved.textScale : "100",
      dyslexicFont: !!saved.dyslexicFont,
      underlineLinks: !!saved.underlineLinks,
      readableSpacing: !!saved.readableSpacing,
    };
  }

  function clearClassList(el, prefixes) {
    var list = el.classList;
    var toRemove = [];
    for (var i = 0; i < list.length; i++) {
      var c = list[i];
      for (var p = 0; p < prefixes.length; p++) {
        if (c.indexOf(prefixes[p]) === 0) toRemove.push(c);
      }
    }
    toRemove.forEach(function (c) {
      list.remove(c);
    });
  }

  function applyState(state) {
    var root = document.documentElement;
    clearClassList(root, ["a11y-"]);

    if (state.cursor === "black") root.classList.add("a11y-cursor-black");
    else if (state.cursor === "white") root.classList.add("a11y-cursor-white");

    if (state.highContrast) root.classList.add("a11y-high-contrast");
    if (state.dyslexicFont) root.classList.add("a11y-dyslexic");
    if (state.underlineLinks) root.classList.add("a11y-underline-links");
    if (state.readableSpacing) root.classList.add("a11y-readable-spacing");

    if (state.textScale === "110") root.classList.add("a11y-text-110");
    else if (state.textScale === "125") root.classList.add("a11y-text-125");
    else if (state.textScale === "150") root.classList.add("a11y-text-150");
  }

  function announce(liveEl, message) {
    if (!liveEl || !message) return;
    liveEl.textContent = "";
    window.setTimeout(function () {
      liveEl.textContent = message;
    }, 50);
  }

  function init() {
    var hadSaved = !!loadState();
    var state = mergeState(loadState());
    if (!hadSaved) saveState(state);

    var a11yRoot = document.getElementById("a11y-root");
    var fab = document.getElementById("a11y-fab");
    var panel = document.getElementById("a11y-panel");
    var backdrop = document.getElementById("a11y-backdrop");
    var live = document.getElementById("a11y-live");
    var readingMaskRoot = document.getElementById("a11y-reading-mask");
    var maskTop = document.getElementById("a11y-mask-top");
    var maskBottom = document.getElementById("a11y-mask-bottom");
    if (!a11yRoot || !fab || !panel || !backdrop) return;

    var cursorDefault = document.getElementById("a11y-cursor-default");
    var cursorBlack = document.getElementById("a11y-cursor-black");
    var cursorWhite = document.getElementById("a11y-cursor-white");
    var focusToggle = document.getElementById("a11y-focus-toggle");
    var hcToggle = document.getElementById("a11y-hc-toggle");
    var dysToggle = document.getElementById("a11y-dys-toggle");
    var linkToggle = document.getElementById("a11y-link-toggle");
    var spaceToggle = document.getElementById("a11y-space-toggle");
    var textSelect = document.getElementById("a11y-text-scale");
    var resetBtn = document.getElementById("a11y-reset");
    var closeBtn = document.getElementById("a11y-close");

    var previousFocus = null;
    var panelFocusables = [];
    var readingBarListenersBound = false;
    /** Last band center Y (viewport px); updated on pointer move and clamped on resize. */
    var readingBarCenterY = 0;

    function syncUi() {
      if (cursorDefault)
        cursorDefault.setAttribute("aria-pressed", state.cursor === "default" ? "true" : "false");
      if (cursorBlack) cursorBlack.setAttribute("aria-pressed", state.cursor === "black" ? "true" : "false");
      if (cursorWhite) cursorWhite.setAttribute("aria-pressed", state.cursor === "white" ? "true" : "false");
      if (focusToggle) focusToggle.setAttribute("aria-pressed", state.focusHighlight ? "true" : "false");
      if (hcToggle) hcToggle.setAttribute("aria-pressed", state.highContrast ? "true" : "false");
      if (dysToggle) dysToggle.setAttribute("aria-pressed", state.dyslexicFont ? "true" : "false");
      if (linkToggle) linkToggle.setAttribute("aria-pressed", state.underlineLinks ? "true" : "false");
      if (spaceToggle) spaceToggle.setAttribute("aria-pressed", state.readableSpacing ? "true" : "false");
      if (textSelect) textSelect.value = state.textScale;
    }

    function getReadingBarBandHeight() {
      var h = window.innerHeight;
      return Math.round(Math.max(88, Math.min(140, h * 0.16)));
    }

    function clampReadingBarCenterY(y) {
      var bh = getReadingBarBandHeight();
      var h = window.innerHeight;
      var half = bh / 2;
      return Math.max(half, Math.min(h - half, y));
    }

    function applyReadingBarAtCenterY(centerY) {
      if (!readingMaskRoot || !maskTop || !maskBottom || !state.focusHighlight) return;
      var bh = getReadingBarBandHeight();
      var h = window.innerHeight;
      var cy = clampReadingBarCenterY(centerY);
      var stripTop = cy - bh / 2;
      var stripBottom = cy + bh / 2;
      maskTop.style.height = stripTop + "px";
      maskBottom.style.top = stripBottom + "px";
      maskBottom.style.bottom = "0";
      readingMaskRoot.removeAttribute("hidden");
      readingMaskRoot.classList.add("is-on");
    }

    function hideReadingBar() {
      if (!readingMaskRoot || !maskTop || !maskBottom) return;
      readingMaskRoot.classList.remove("is-on");
      readingMaskRoot.setAttribute("hidden", "");
      maskTop.style.height = "0px";
      maskBottom.style.top = "100vh";
      maskBottom.style.bottom = "0";
    }

    function onReadingBarMouseMove(ev) {
      if (!state.focusHighlight) return;
      readingBarCenterY = ev.clientY;
      applyReadingBarAtCenterY(readingBarCenterY);
    }

    function onReadingBarResize() {
      if (!state.focusHighlight) return;
      readingBarCenterY = clampReadingBarCenterY(readingBarCenterY);
      applyReadingBarAtCenterY(readingBarCenterY);
    }

    function bindReadingBar() {
      if (!readingMaskRoot || !maskTop || !maskBottom) return;
      if (state.focusHighlight) {
        if (!readingBarListenersBound) {
          document.addEventListener("mousemove", onReadingBarMouseMove, { passive: true });
          window.addEventListener("resize", onReadingBarResize);
          readingBarListenersBound = true;
        }
        var mid = window.innerHeight / 2;
        readingBarCenterY = clampReadingBarCenterY(mid);
        applyReadingBarAtCenterY(readingBarCenterY);
      } else {
        hideReadingBar();
        if (readingBarListenersBound) {
          document.removeEventListener("mousemove", onReadingBarMouseMove);
          window.removeEventListener("resize", onReadingBarResize);
          readingBarListenersBound = false;
        }
      }
    }

    function commit(message) {
      applyState(state);
      saveState(state);
      syncUi();
      bindReadingBar();
      if (message) announce(live, message);
    }

    applyState(state);
    syncUi();
    bindReadingBar();

    function isOpen() {
      return fab.getAttribute("aria-expanded") === "true";
    }

    function getFocusable() {
      var sel =
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
      return Array.prototype.slice.call(panel.querySelectorAll(sel)).filter(function (el) {
        return el.offsetParent !== null || el === closeBtn;
      });
    }

    function openPanel() {
      previousFocus = document.activeElement;
      fab.setAttribute("aria-expanded", "true");
      panel.hidden = false;
      backdrop.hidden = false;
      panelFocusables = getFocusable();
      var first = panelFocusables[0] || closeBtn;
      window.setTimeout(function () {
        if (first) first.focus();
      }, 10);
    }

    function closePanel() {
      fab.setAttribute("aria-expanded", "false");
      panel.hidden = true;
      backdrop.hidden = true;
      if (previousFocus && typeof previousFocus.focus === "function") previousFocus.focus();
      previousFocus = null;
    }

    function togglePanel() {
      if (isOpen()) closePanel();
      else openPanel();
    }

    fab.addEventListener("click", togglePanel);
    backdrop.addEventListener("click", closePanel);
    if (closeBtn) closeBtn.addEventListener("click", closePanel);

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && isOpen()) {
        e.preventDefault();
        closePanel();
      }
      if (!isOpen() || e.key !== "Tab") return;
      panelFocusables = getFocusable();
      if (panelFocusables.length === 0) return;
      var first = panelFocusables[0];
      var last = panelFocusables[panelFocusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    });

    function setCursor(mode) {
      state.cursor = mode;
      commit(
        mode === "black"
          ? "Large black pointer cursor enabled."
          : mode === "white"
            ? "Large white pointer cursor enabled."
            : "Default cursor restored.",
      );
    }

    if (cursorDefault) cursorDefault.addEventListener("click", function () { setCursor("default"); });
    if (cursorBlack) cursorBlack.addEventListener("click", function () { setCursor("black"); });
    if (cursorWhite) cursorWhite.addEventListener("click", function () { setCursor("white"); });

    if (focusToggle) {
      focusToggle.addEventListener("click", function () {
        state.focusHighlight = !state.focusHighlight;
        commit(
          state.focusHighlight
            ? "Reading bar on: tracks the pointer with no delay."
            : "Reading bar off.",
        );
      });
    }
    if (hcToggle) {
      hcToggle.addEventListener("click", function () {
        state.highContrast = !state.highContrast;
        commit(state.highContrast ? "High contrast colors on." : "High contrast colors off.");
      });
    }
    if (dysToggle) {
      dysToggle.addEventListener("click", function () {
        state.dyslexicFont = !state.dyslexicFont;
        commit(state.dyslexicFont ? "Readable font (OpenDyslexic) on." : "Readable font off.");
      });
    }
    if (linkToggle) {
      linkToggle.addEventListener("click", function () {
        state.underlineLinks = !state.underlineLinks;
        commit(state.underlineLinks ? "Links always underlined." : "Default link styling.");
      });
    }
    if (spaceToggle) {
      spaceToggle.addEventListener("click", function () {
        state.readableSpacing = !state.readableSpacing;
        commit(state.readableSpacing ? "Increased line and letter spacing on." : "Default text spacing.");
      });
    }
    if (textSelect) {
      textSelect.addEventListener("change", function () {
        state.textScale = textSelect.value || "100";
        commit("Text size set to " + state.textScale + " percent scale.");
      });
    }
    if (resetBtn) {
      resetBtn.addEventListener("click", function () {
        state = defaultState();
        commit("All accessibility options reset.");
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
