/**
 * Cookie consent levels for RGEE (browser cookie + window API).
 * "full" = preference storage (localStorage) for theme, accessibility, onboarding.
 * "essential" = opt-out of that persistence; session-only where supported.
 */
(function () {
  "use strict";

  var COOKIE_NAME = "rgee_consent";
  var MAX_AGE_SEC = 395 * 24 * 60 * 60;

  function readCookie() {
    var match = document.cookie.match(new RegExp("(?:^|; )" + COOKIE_NAME + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : "";
  }

  function writeCookie(value) {
    document.cookie =
      COOKIE_NAME +
      "=" +
      encodeURIComponent(value) +
      ";path=/;max-age=" +
      MAX_AGE_SEC +
      ";SameSite=Lax";
  }

  window.RGEE = window.RGEE || {};
  window.RGEE.consent = {
    getLevel: function () {
      var v = readCookie();
      return v === "full" || v === "essential" ? v : "unknown";
    },
    setLevel: function (level) {
      if (level === "full" || level === "essential") writeCookie(level);
    },
    preferencesAllowed: function () {
      return readCookie() === "full";
    },
    hasAnswered: function () {
      var v = readCookie();
      return v === "full" || v === "essential";
    },
  };
})();
