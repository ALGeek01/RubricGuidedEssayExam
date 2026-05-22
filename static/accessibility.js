/**
 * RGEE sitewide accessibility preferences (WCAG-oriented controls).
 * Persists in localStorage; applies classes on document.documentElement.
 * Reading bar: full-width horizontal clear band; follows pointer Y immediately on each move (no easing delay).
 * Speech feedback: browser Speech Synthesis (local device voices; user picks default voice).
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
      ttsEnabled: false,
      ttsVoiceUri: "",
      ttsRate: 1,
      ttsPitch: 1,
      ttsVolume: 1,
      ttsOnClick: true,
      ttsOnSelect: true,
      ttsGenderFilter: "any",
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
      ttsEnabled: !!saved.ttsEnabled,
      ttsVoiceUri: typeof saved.ttsVoiceUri === "string" ? saved.ttsVoiceUri : "",
      ttsRate:
        typeof saved.ttsRate === "number" && saved.ttsRate >= 0.5 && saved.ttsRate <= 2
          ? saved.ttsRate
          : 1,
      ttsPitch:
        typeof saved.ttsPitch === "number" && saved.ttsPitch >= 0.5 && saved.ttsPitch <= 2
          ? saved.ttsPitch
          : 1,
      ttsVolume:
        typeof saved.ttsVolume === "number" && saved.ttsVolume >= 0 && saved.ttsVolume <= 1
          ? saved.ttsVolume
          : 1,
      ttsOnClick: saved.ttsOnClick !== false,
      ttsOnSelect: saved.ttsOnSelect !== false,
      ttsGenderFilter:
        saved.ttsGenderFilter === "female" || saved.ttsGenderFilter === "male"
          ? saved.ttsGenderFilter
          : "any",
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

  /** Local text-to-speech (browser Speech Synthesis — device voices, user-picked default). */
  function initA11ySpeech(api) {
    var synth = window.speechSynthesis || null;
    var ttsBound = false;
    var GENDER_ANY = "any";
    var GENDER_FEMALE = "female";
    var GENDER_MALE = "male";

    function prefs() {
      return api.getState();
    }

    function patchState(patch, message) {
      api.update(patch, message);
    }

    function inferGender(voice) {
      var n = (voice.name || "").toLowerCase();
      if (
        /female|woman|girl|samantha|victoria|karen|moira|fiona|tessa|veena|zira|hazel|susan|linda|heera|maria|paulina|monica|laura|anna|ellen|sara|amelie|flo|grandma|grandpa.*female/i.test(
          n,
        )
      ) {
        return GENDER_FEMALE;
      }
      if (
        /male|man|boy|daniel|david|james|john|fred|ralph|richard|tom|aaron|gordon|bruce|lee|mark|oliver|arthur|marco|diego|jorge|ivan|xander|yuri|grandpa(?!.*female)/i.test(
          n,
        )
      ) {
        return GENDER_MALE;
      }
      return GENDER_ANY;
    }

    function voiceGender(voice) {
      return inferGender(voice);
    }

    function filterVoices(list, genderFilter) {
      if (!genderFilter || genderFilter === GENDER_ANY) return list;
      return list.filter(function (v) {
        var g = voiceGender(v);
        if (genderFilter === GENDER_FEMALE) return g === GENDER_FEMALE;
        if (genderFilter === GENDER_MALE) return g === GENDER_MALE;
        return true;
      });
    }

    function loadVoices() {
      if (!synth) return [];
      return (synth.getVoices() || []).filter(function (v) {
        return v && v.lang;
      });
    }

    function selectedVoice() {
      var p = prefs();
      if (!p || !p.ttsVoiceUri || !synth) return null;
      var list = loadVoices();
      for (var i = 0; i < list.length; i += 1) {
        if (list[i].voiceURI === p.ttsVoiceUri) return list[i];
      }
      return null;
    }

    function speak(text, options) {
      if (!synth || !text) return false;
      var p = prefs();
      if (!p || !p.ttsEnabled) return false;
      var voice = selectedVoice();
      if (!voice) {
        api.announce("Choose a default voice under Focus and reading, Speech feedback, first.");
        return false;
      }

      var chunk = String(text).replace(/\s+/g, " ").trim();
      if (!chunk) return false;
      if (chunk.length > 500) chunk = chunk.slice(0, 497) + "…";

      synth.cancel();
      var u = new SpeechSynthesisUtterance(chunk);
      u.voice = voice;
      u.lang = voice.lang || undefined;
      u.rate =
        options && typeof options.rate === "number" ? options.rate : parseFloat(p.ttsRate) || 1;
      u.pitch =
        options && typeof options.pitch === "number" ? options.pitch : parseFloat(p.ttsPitch) || 1;
      u.volume =
        options && typeof options.volume === "number" ? options.volume : parseFloat(p.ttsVolume) || 1;
      synth.speak(u);
      return true;
    }

    function stop() {
      if (synth) synth.cancel();
    }

    function labelForElement(el) {
      if (!el || el.closest("#a11y-root")) return "";
      var tag = (el.tagName || "").toLowerCase();
      if (el.getAttribute("aria-label")) return el.getAttribute("aria-label").trim();
      var labelledBy = el.getAttribute("aria-labelledby");
      if (labelledBy) {
        var parts = labelledBy.split(/\s+/);
        var out = [];
        for (var i = 0; i < parts.length; i += 1) {
          var ref = document.getElementById(parts[i]);
          if (ref && ref.textContent) out.push(ref.textContent.trim());
        }
        if (out.length) return out.join(" ");
      }
      if (tag === "input" || tag === "textarea") {
        var ph = el.getAttribute("placeholder");
        if (ph) return ph;
        if (el.value) return el.value;
      }
      if (tag === "img" && el.getAttribute("alt")) return el.getAttribute("alt").trim();
      var text = (el.textContent || "").replace(/\s+/g, " ").trim();
      if (text.length > 200) text = text.slice(0, 197) + "…";
      return text;
    }

    function onInteractiveClick(ev) {
      var p = prefs();
      if (!p || !p.ttsEnabled || !p.ttsOnClick) return;
      var el = ev.target.closest(
        "button, a[href], [role='button'], input[type='button'], input[type='submit'], summary, .btn, label",
      );
      if (!el || el.closest("#a11y-root, #a11y-panel, .cookie-banner")) return;
      if (el.disabled || el.getAttribute("aria-disabled") === "true") return;
      var line = labelForElement(el);
      if (line) speak(line);
    }

    function onTextSelected() {
      var p = prefs();
      if (!p || !p.ttsEnabled || !p.ttsOnSelect) return;
      var sel = window.getSelection();
      if (!sel || sel.isCollapsed) return;
      var text = sel.toString().replace(/\s+/g, " ").trim();
      if (text.length >= 2) speak(text);
    }

    function populateVoiceSelect(selectEl, genderFilter, selectedUri) {
      if (!selectEl) return;
      var list = filterVoices(loadVoices(), genderFilter);
      list.sort(function (a, b) {
        if (a.lang < b.lang) return -1;
        if (a.lang > b.lang) return 1;
        return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
      });
      selectEl.innerHTML = "";
      var placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent =
        list.length > 0
          ? "Choose your default voice…"
          : "No voices — reload page or check OS speech settings";
      selectEl.appendChild(placeholder);
      var byLang = {};
      list.forEach(function (v) {
        var lang = v.lang || "unknown";
        if (!byLang[lang]) byLang[lang] = [];
        byLang[lang].push(v);
      });
      Object.keys(byLang)
        .sort()
        .forEach(function (lang) {
          var group = document.createElement("optgroup");
          group.label = lang;
          byLang[lang].forEach(function (v) {
            var opt = document.createElement("option");
            opt.value = v.voiceURI;
            var g = voiceGender(v);
            var gLabel = g === GENDER_FEMALE ? " · F" : g === GENDER_MALE ? " · M" : "";
            opt.textContent = v.name + gLabel;
            if (selectedUri && v.voiceURI === selectedUri) opt.selected = true;
            group.appendChild(opt);
          });
          selectEl.appendChild(group);
        });
    }

    function syncTtsUi() {
      var p = prefs();
      if (!p) return;
      var enableToggle = document.getElementById("a11y-tts-enable");
      var clickToggle = document.getElementById("a11y-tts-click");
      var selectToggle = document.getElementById("a11y-tts-select");
      var genderSelect = document.getElementById("a11y-tts-gender");
      var voiceSelect = document.getElementById("a11y-tts-voice");
      var rateInput = document.getElementById("a11y-tts-rate");
      var pitchInput = document.getElementById("a11y-tts-pitch");
      var volumeInput = document.getElementById("a11y-tts-volume");
      var rateVal = document.getElementById("a11y-tts-rate-val");
      var pitchVal = document.getElementById("a11y-tts-pitch-val");
      var volumeVal = document.getElementById("a11y-tts-volume-val");
      var unsupported = document.getElementById("a11y-tts-unsupported");
      var supported = !!synth;
      if (unsupported) unsupported.hidden = supported;
      if (enableToggle) enableToggle.setAttribute("aria-pressed", p.ttsEnabled ? "true" : "false");
      if (clickToggle) clickToggle.setAttribute("aria-pressed", p.ttsOnClick ? "true" : "false");
      if (selectToggle) selectToggle.setAttribute("aria-pressed", p.ttsOnSelect ? "true" : "false");
      if (genderSelect) genderSelect.value = p.ttsGenderFilter || GENDER_ANY;
      if (rateInput) rateInput.value = String(p.ttsRate != null ? p.ttsRate : 1);
      if (pitchInput) pitchInput.value = String(p.ttsPitch != null ? p.ttsPitch : 1);
      if (volumeInput) volumeInput.value = String(p.ttsVolume != null ? p.ttsVolume : 1);
      if (rateVal) rateVal.textContent = rateInput ? rateInput.value : "1";
      if (pitchVal) pitchVal.textContent = pitchInput ? pitchInput.value : "1";
      if (volumeVal) volumeVal.textContent = volumeInput ? volumeInput.value : "1";
      populateVoiceSelect(voiceSelect, p.ttsGenderFilter, p.ttsVoiceUri);
      var panel = document.querySelector(".a11y-tts-panel");
      if (panel) panel.hidden = !p.ttsEnabled || !supported;
    }

    function bindTtsUi() {
      if (ttsBound) return;
      ttsBound = true;
      var enableToggle = document.getElementById("a11y-tts-enable");
      var clickToggle = document.getElementById("a11y-tts-click");
      var selectToggle = document.getElementById("a11y-tts-select");
      var genderSelect = document.getElementById("a11y-tts-gender");
      var voiceSelect = document.getElementById("a11y-tts-voice");
      var previewBtn = document.getElementById("a11y-tts-preview");
      var stopBtn = document.getElementById("a11y-tts-stop");
      var rateInput = document.getElementById("a11y-tts-rate");
      var pitchInput = document.getElementById("a11y-tts-pitch");
      var volumeInput = document.getElementById("a11y-tts-volume");

      if (synth) {
        loadVoices();
        speechSynthesis.addEventListener("voiceschanged", function () {
          syncTtsUi();
        });
      }

      if (enableToggle) {
        enableToggle.addEventListener("click", function () {
          var p = prefs();
          var next = !p.ttsEnabled;
          patchState(
            { ttsEnabled: next },
            next ? "Speech on. Pick your default voice below." : "Speech feedback off.",
          );
        });
      }
      if (clickToggle) {
        clickToggle.addEventListener("click", function () {
          var p = prefs();
          patchState(
            { ttsOnClick: !p.ttsOnClick },
            p.ttsOnClick ? "Speak on click off." : "Speak on click on.",
          );
        });
      }
      if (selectToggle) {
        selectToggle.addEventListener("click", function () {
          var p = prefs();
          patchState(
            { ttsOnSelect: !p.ttsOnSelect },
            p.ttsOnSelect ? "Speak selection off." : "Speak selection on.",
          );
        });
      }
      if (genderSelect) {
        genderSelect.addEventListener("change", function () {
          patchState(
            { ttsGenderFilter: genderSelect.value, ttsVoiceUri: "" },
            "Voice list filtered. Choose your default voice.",
          );
        });
      }
      if (voiceSelect) {
        voiceSelect.addEventListener("change", function () {
          var uri = voiceSelect.value || "";
          var name = "";
          if (uri) {
            loadVoices().forEach(function (voice) {
              if (voice.voiceURI === uri) name = voice.name;
            });
          }
          patchState(
            { ttsVoiceUri: uri },
            uri
              ? "Default voice set to " + (name || "selected voice") + "."
              : "No default voice selected.",
          );
        });
      }
      if (previewBtn) {
        previewBtn.addEventListener("click", function () {
          speak("This is your preview. Rubric Guided Essay Exam speech is ready.");
        });
      }
      if (stopBtn) {
        stopBtn.addEventListener("click", function () {
          stop();
          api.announce("Speech stopped.");
        });
      }
      function bindRange(input, key, label) {
        if (!input) return;
        input.addEventListener("input", function () {
          var patch = {};
          patch[key] = parseFloat(input.value);
          patchState(patch, label + " " + input.value + ".");
        });
      }
      bindRange(rateInput, "ttsRate", "Speech rate");
      bindRange(pitchInput, "ttsPitch", "Speech pitch");
      bindRange(volumeInput, "ttsVolume", "Speech volume");

      if (synth) {
        document.addEventListener("click", onInteractiveClick, true);
        document.addEventListener("mouseup", onTextSelected);
        document.addEventListener("keyup", function (ev) {
          if (ev.key === "Escape") stop();
        });
      }
      syncTtsUi();
    }

    bindTtsUi();

    return {
      speak: speak,
      stop: stop,
      syncUi: syncTtsUi,
      getVoices: loadVoices,
      supported: !!synth,
    };
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
    var speech = null;

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
      if (speech && speech.syncUi) speech.syncUi();
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

    window.RGEE = window.RGEE || {};
    var a11yApi = {
      getState: function () {
        return state;
      },
      update: function (patch, message) {
        if (patch && typeof patch === "object") {
          Object.keys(patch).forEach(function (k) {
            state[k] = patch[k];
          });
        }
        commit(message);
      },
      announce: function (message) {
        announce(live, message);
      },
    };
    speech = initA11ySpeech(a11yApi);
    window.RGEE.a11y = a11yApi;
    window.RGEE.tts = speech;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
