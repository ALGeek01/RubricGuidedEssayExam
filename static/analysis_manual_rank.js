/**
 * Manual 1–4 signal bars for question-analysis feedback (click or drag).
 */
(function () {
  function setRank(group, value) {
    var bars = group.querySelector(".analysis-rank-bars");
    var hidden = group.querySelector('input[type="hidden"][name^="manual_"]');
    var pillId = group.getAttribute("data-pill-id");
    var pill = pillId ? document.getElementById(pillId) : null;
    var label = group.getAttribute("data-rank-label") || "Rank";
    var v = parseInt(String(value), 10);
    if (isNaN(v) || v < 0) v = 0;
    if (v > 4) v = 4;
    if (hidden) hidden.value = v > 0 ? String(v) : "0";
    if (bars) {
      bars.setAttribute("aria-valuenow", String(v));
      var btns = bars.querySelectorAll(".analysis-rank-bar");
      btns.forEach(function (btn) {
        var lvl = parseInt(btn.getAttribute("data-value") || "0", 10);
        var lit = v > 0 && lvl <= v;
        btn.classList.toggle("is-lit", lit);
        btn.classList.toggle("is-active", v > 0 && lvl === v);
        btn.setAttribute("aria-pressed", v > 0 && lvl === v ? "true" : "false");
      });
    }
    if (pill) {
      pill.textContent = v > 0 ? "You " + label + " " + v + "/4" : "You " + label + " —";
    }
  }

  function bindGroup(group) {
    var bars = group.querySelector(".analysis-rank-bars");
    if (!bars) return;
    var hidden = group.querySelector('input[type="hidden"][name^="manual_"]');
    var initial = parseInt(
      (hidden && hidden.value) || bars.getAttribute("data-initial") || "0",
      10
    );
    setRank(group, initial);

    var dragging = false;
    var dragMoved = false;

    bars.querySelectorAll(".analysis-rank-bar").forEach(function (btn) {
      btn.addEventListener("mousedown", function (ev) {
        if (ev.button !== 0) return;
        ev.preventDefault();
        dragging = true;
        dragMoved = false;
      });

      btn.addEventListener("mouseenter", function () {
        if (!dragging) return;
        dragMoved = true;
        setRank(group, btn.getAttribute("data-value"));
      });

      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        if (dragMoved) {
          dragMoved = false;
          return;
        }
        var val = parseInt(btn.getAttribute("data-value") || "0", 10);
        var cur = parseInt((hidden && hidden.value) || "0", 10);
        if (cur === val) {
          setRank(group, 0);
        } else {
          setRank(group, val);
        }
      });

      btn.addEventListener("dblclick", function (ev) {
        ev.preventDefault();
        setRank(group, 0);
      });

      btn.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          var val = parseInt(btn.getAttribute("data-value") || "0", 10);
          var cur = parseInt((hidden && hidden.value) || "0", 10);
          if (cur === val) {
            setRank(group, 0);
          } else {
            setRank(group, val);
          }
        }
      });
    });

    document.addEventListener("mouseup", function () {
      dragging = false;
    });

    bars.addEventListener("keydown", function (ev) {
      var cur = parseInt((hidden && hidden.value) || "0", 10);
      if (ev.key === "ArrowRight" || ev.key === "ArrowUp") {
        ev.preventDefault();
        setRank(group, Math.min(4, cur + 1));
      } else if (ev.key === "ArrowLeft" || ev.key === "ArrowDown") {
        ev.preventDefault();
        setRank(group, Math.max(0, cur - 1));
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".analysis-manual-rank-block").forEach(bindGroup);
  });
})();
