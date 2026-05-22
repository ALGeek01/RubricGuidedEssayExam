/**
 * Cookie consent banner, cookie settings dialog, and first-time onboarding tour.
 */
(function () {
  "use strict";

  var LS_ONBOARD = "rgee_onboarding_done_v1";
  var SS_ONBOARD = "rgee_onboarding_session_v1";

  function clearPreferenceLocalStorage() {
    try {
      localStorage.removeItem("rgee_theme_v1");
      localStorage.removeItem("rgee_a11y_prefs_v1");
      localStorage.removeItem(LS_ONBOARD);
    } catch (e) {}
  }

  function onboardingComplete() {
    try {
      if (window.RGEE.consent.preferencesAllowed()) return localStorage.getItem(LS_ONBOARD) === "1";
      return sessionStorage.getItem(SS_ONBOARD) === "1";
    } catch (e) {
      return false;
    }
  }

  function setOnboardingComplete() {
    try {
      if (window.RGEE.consent.preferencesAllowed()) localStorage.setItem(LS_ONBOARD, "1");
      else sessionStorage.setItem(SS_ONBOARD, "1");
    } catch (e) {}
  }

  function reloadForConsent() {
    window.location.reload();
  }

  function bindCookieBar() {
    var bar = document.getElementById("cookie-consent-bar");
    var acceptAll = document.getElementById("cookie-accept-all");
    var essential = document.getElementById("cookie-essential-only");
    if (!bar || !acceptAll || !essential) return;

    acceptAll.addEventListener("click", function () {
      window.RGEE.consent.setLevel("full");
      bar.hidden = true;
      reloadForConsent();
    });
    essential.addEventListener("click", function () {
      window.RGEE.consent.setLevel("essential");
      clearPreferenceLocalStorage();
      bar.hidden = true;
      reloadForConsent();
    });
  }

  function openDialog(el) {
    if (!el) return;
    el.hidden = false;
    var t = el.querySelector("h2, h3, button");
    window.setTimeout(function () {
      if (t) t.focus();
    }, 10);
  }

  function closeDialog(el) {
    if (el) el.hidden = true;
  }

  function bindCookieSettings() {
    var dlg = document.getElementById("cookie-settings-dialog");
    var openFooter = document.getElementById("footer-cookie-choices");
    var closeBtn = document.getElementById("cookie-settings-close");
    var backdrop = document.getElementById("cookie-settings-backdrop");
    var save = document.getElementById("cookie-settings-save");
    var radios = dlg ? dlg.querySelectorAll('input[name="cookie-level"]') : [];

    function syncRadios() {
      var level = window.RGEE.consent.getLevel();
      var v = level === "full" || level === "essential" ? level : "essential";
      for (var i = 0; i < radios.length; i++) {
        radios[i].checked = radios[i].value === v;
      }
    }

    function open() {
      syncRadios();
      openDialog(dlg);
      if (backdrop) backdrop.hidden = false;
    }

    function close() {
      closeDialog(dlg);
      if (backdrop) backdrop.hidden = true;
    }

    if (openFooter) openFooter.addEventListener("click", open);
    if (closeBtn) closeBtn.addEventListener("click", close);
    if (backdrop) backdrop.addEventListener("click", close);
    if (save) {
      save.addEventListener("click", function () {
        var chosen = "essential";
        for (var i = 0; i < radios.length; i++) {
          if (radios[i].checked) chosen = radios[i].value;
        }
        var prev = window.RGEE.consent.getLevel();
        window.RGEE.consent.setLevel(chosen);
        if (chosen === "essential") clearPreferenceLocalStorage();
        close();
        if (chosen !== prev) reloadForConsent();
      });
    }

    var replay = document.getElementById("cookie-onboarding-replay");
    if (replay) {
      replay.addEventListener("click", function () {
        try {
          localStorage.removeItem(LS_ONBOARD);
          sessionStorage.removeItem(SS_ONBOARD);
        } catch (e) {}
        close();
        reloadForConsent();
      });
    }

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && dlg && !dlg.hidden) close();
    });
  }

  function bindOnboarding() {
    var overlay = document.getElementById("onboarding-overlay");
    var dialog = document.getElementById("onboarding-dialog");
    var titleEl = document.getElementById("onboarding-title");
    var bodyEl = document.getElementById("onboarding-body");
    var stepEl = document.getElementById("onboarding-step-label");
    var backBtn = document.getElementById("onboarding-back");
    var nextBtn = document.getElementById("onboarding-next");
    var skipBtn = document.getElementById("onboarding-skip");
    if (!overlay || !dialog || !titleEl || !bodyEl || !nextBtn || !skipBtn) return;

    var steps = [
      {
        title: "Welcome to RGEE",
        html:
          "<p>This site runs <strong>rubric-guided essay exams</strong>: students answer questions and receive structured feedback; instructors can review sessions and tools.</p><p>Use this short tour to learn where the main controls live.</p>",
      },
      {
        title: "Top navigation",
        html:
          "<p>The header links move you around the app: <strong>Home</strong> for starting or resuming an exam, <strong>Instructor</strong> for the professor dashboard, and <strong>Developer tools</strong> when you are signed in as an instructor.</p>",
      },
      {
        title: "Theme",
        html:
          "<p>The <strong>sun / moon</strong> button next to the menu switches <strong>light</strong> and <strong>dark</strong> appearance. Whether it is remembered after you leave depends on your cookie choice (preference cookies).</p>",
      },
      {
        title: "Accessibility",
        html:
          "<p>The floating <strong>accessibility</strong> button in the lower-right opens options such as a reading bar, <strong>local speech feedback</strong> (choose your own voice), high contrast, text size, and link underlining. These can also be tied to preference storage when you allow it.</p>",
      },
      {
        title: "Students: start or resume",
        html:
          "<p>From <strong>Home</strong>, use <strong>Start exam</strong> to begin (generated or instructor-nominated flow) or <strong>Resume exam</strong> if you already have an exam code.</p><p>To see this tour again, open <strong>Cookie choices</strong> in the footer and use <strong>Replay welcome tour</strong>.</p>",
      },
    ];

    var idx = 0;

    function render() {
      var s = steps[idx];
      titleEl.textContent = s.title;
      bodyEl.innerHTML = s.html;
      if (stepEl) stepEl.textContent = "Step " + (idx + 1) + " of " + steps.length;
      if (backBtn) backBtn.hidden = idx === 0;
      nextBtn.textContent = idx === steps.length - 1 ? "Finish" : "Next";
    }

    function openOnboarding() {
      idx = 0;
      overlay.hidden = false;
      dialog.hidden = false;
      render();
      window.setTimeout(function () {
        nextBtn.focus();
      }, 50);
    }

    function closeOnboarding() {
      overlay.hidden = true;
      dialog.hidden = true;
    }

    function finishTour() {
      setOnboardingComplete();
      closeOnboarding();
    }

    backBtn.addEventListener("click", function () {
      if (idx > 0) {
        idx--;
        render();
      }
    });
    nextBtn.addEventListener("click", function () {
      if (idx >= steps.length - 1) finishTour();
      else {
        idx++;
        render();
      }
    });
    skipBtn.addEventListener("click", finishTour);

    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) finishTour();
    });

    document.addEventListener("keydown", function (e) {
      if (dialog.hidden) return;
      if (e.key === "Escape") finishTour();
    });

    return { openOnboarding: openOnboarding };
  }

  function init() {
    if (!window.RGEE || !window.RGEE.consent) return;

    var footerMeta = document.querySelector(".site-footer-meta");

    bindCookieSettings();

    var bar = document.getElementById("cookie-consent-bar");
    if (!window.RGEE.consent.hasAnswered()) {
      if (bar) bar.hidden = false;
      if (footerMeta) footerMeta.hidden = true;
      document.body.classList.add("cookie-consent-visible");
      bindCookieBar();
      return;
    }

    document.body.classList.remove("cookie-consent-visible");

    if (footerMeta) footerMeta.hidden = false;
    if (bar) bar.hidden = true;

    var tour = bindOnboarding();
    if (tour && !onboardingComplete()) {
      window.setTimeout(function () {
        tour.openOnboarding();
      }, 400);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
