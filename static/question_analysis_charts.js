/**
 * Exam question analysis dashboard — Chart.js widgets (RGEE theme colors).
 * Palette follows document CSS variables so light / high-contrast themes stay readable.
 */
(function () {
  "use strict";

  function buildChartPalette() {
    var root = document.documentElement;
    var cs = getComputedStyle(root);
    var light = root.getAttribute("data-theme") === "light";
    var pick = function (name, fallback) {
      var v = (cs.getPropertyValue(name) || "").trim();
      return v || fallback;
    };
    var text = pick("--text", "#e2e8f0");
    var muted = pick("--muted", "#94a3b8");
    var accent = pick("--accent", "#38bdf8");
    var accent2 = pick("--accent-2", "#818cf8");
    var grid = light
      ? "rgba(15, 23, 42, 0.14)"
      : "rgba(148, 163, 184, 0.22)";
    var donutBorder = light
      ? "rgba(15, 23, 42, 0.22)"
      : "rgba(15, 23, 42, 0.85)";
    return {
      accent: accent,
      accent2: accent2,
      mint: "#34d399",
      rose: "#f472b6",
      amber: "#fbbf24",
      text: text,
      muted: muted,
      grid: grid,
      surface: light ? "rgba(255, 255, 255, 0)" : "rgba(24, 34, 54, 0.5)",
      donutBorder: donutBorder,
      isLight: light,
    };
  }

  var C = buildChartPalette();

  var payloadEl = document.getElementById("analysis-chart-payload");
  if (!payloadEl) return;

  var raw = payloadEl.textContent.trim();
  if (!raw) return;

  var payload;
  try {
    payload = JSON.parse(raw);
  } catch (e) {
    return;
  }

  if (payload.empty) {
    return;
  }

  var charts = [];

  function registerChart(chart) {
    if (chart) charts.push(chart);
  }

  function layoutPadding() {
    return { top: 8, right: 10, bottom: 10, left: 8 };
  }

  function titleFont() {
    return {
      family: "Outfit, system-ui, sans-serif",
      size: 14,
      weight: "700",
    };
  }

  function tickFont() {
    return {
      family: "Outfit, system-ui, sans-serif",
      size: 12,
      weight: "600",
    };
  }

  function legendOpts() {
    return {
      labels: {
        color: C.text,
        font: { family: "Outfit, system-ui, sans-serif", size: 12, weight: "600" },
        boxWidth: 12,
        padding: 12,
      },
    };
  }

  var debounceTimer = null;
  function scheduleChartReflow() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () {
      debounceTimer = null;
      charts.forEach(function (ch) {
        try {
          ch.resize();
        } catch (e) {
          /* ignore */
        }
      });
    }, 120);
  }

  var dashboardEl = document.getElementById("analysis-dashboard");
  if (dashboardEl && typeof ResizeObserver !== "undefined") {
    var ro = new ResizeObserver(scheduleChartReflow);
    ro.observe(dashboardEl);
  }
  window.addEventListener("resize", scheduleChartReflow, { passive: true });

  var mt = document.getElementById("metric-total");
  var ms = document.getElementById("metric-sessions");
  var mr = document.getElementById("metric-relevance");
  if (mt) mt.textContent = String(payload.total);
  if (ms) ms.textContent = String(payload.sessions);
  if (mr) {
    mr.textContent =
      payload.overall && typeof payload.overall.relevance === "number"
        ? payload.overall.relevance.toFixed(2)
        : "—";
  }

  var qf = payload.quality_freq || [0, 0, 0, 0];
  var gf = payload.grade_freq || [0, 0, 0, 0];
  var labels14 = ["Code 1", "Code 2", "Code 3", "Code 4"];

  var elQ = document.getElementById("chart-quality-donut");
  if (elQ && window.Chart) {
    registerChart(
    new Chart(elQ, {
      type: "doughnut",
      data: {
        labels: labels14,
        datasets: [
          {
            data: qf,
            backgroundColor: [C.accent, C.accent2, C.mint, C.rose],
            borderColor: C.donutBorder,
            borderWidth: 2,
            hoverOffset: 6,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: layoutPadding() },
        cutout: "58%",
        plugins: {
          legend: legendOpts(),
          title: {
            display: true,
            text: "Essay quality codes (1–4)",
            color: C.text,
            font: titleFont(),
          },
        },
      },
    })
    );
  }

  var elG = document.getElementById("chart-grade-donut");
  if (elG && window.Chart) {
    registerChart(
    new Chart(elG, {
      type: "doughnut",
      data: {
        labels: labels14,
        datasets: [
          {
            data: gf,
            backgroundColor: [C.mint, C.accent, C.amber, C.accent2],
            borderColor: C.donutBorder,
            borderWidth: 2,
            hoverOffset: 6,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: layoutPadding() },
        cutout: "58%",
        plugins: {
          legend: legendOpts(),
          title: {
            display: true,
            text: "Grade fit codes (1–4)",
            color: C.text,
            font: titleFont(),
          },
        },
      },
    })
    );
  }

  var elO = document.getElementById("chart-overall-bars");
  if (elO && window.Chart && payload.overall) {
    registerChart(
    new Chart(elO, {
      type: "bar",
      data: {
        labels: ["Relevance", "Emb. quality", "Humor / levity"],
        datasets: [
          {
            label: "Mean (0–10)",
            data: [payload.overall.relevance, payload.overall.quality, payload.overall.humor],
            backgroundColor: [C.accent, C.accent2, C.mint],
            borderRadius: 8,
            borderSkipped: false,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: layoutPadding() },
        scales: {
          x: {
            min: 0,
            max: 10,
            grid: { color: C.grid },
            ticks: {
              color: C.muted,
              font: tickFont(),
            },
            border: { color: C.grid },
          },
          y: {
            grid: { display: false },
            ticks: {
              color: C.text,
              font: tickFont(),
            },
            border: { display: false },
          },
        },
        plugins: {
          legend: { display: false },
          title: {
            display: true,
            text: "Supplementary embedding means",
            color: C.text,
            font: titleFont(),
          },
        },
      },
    })
    );
  }

  var elC = document.getElementById("chart-by-category");
  if (elC && window.Chart && payload.categories && payload.categories.length) {
    var cats = payload.categories;
    registerChart(
    new Chart(elC, {
      type: "bar",
      data: {
        labels: cats.map(function (c) {
          return c.label;
        }),
        datasets: [
          {
            label: "Mean quality code",
            data: cats.map(function (c) {
              return c.mean_quality_code;
            }),
            backgroundColor: C.accent,
            borderRadius: 5,
          },
          {
            label: "Mean appropriateness",
            data: cats.map(function (c) {
              return c.mean_grade_approp_code;
            }),
            backgroundColor: C.mint,
            borderRadius: 5,
          },
          {
            label: "Relevance ÷2.5",
            data: cats.map(function (c) {
              return c.relevance_score / 2.5;
            }),
            backgroundColor: C.accent2,
            borderRadius: 5,
          },
          {
            label: "Humor ÷2.5",
            data: cats.map(function (c) {
              return c.humor_score / 2.5;
            }),
            backgroundColor: C.rose,
            borderRadius: 5,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: layoutPadding() },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: C.text,
              maxRotation: 45,
              minRotation: 0,
              autoSkip: true,
              maxTicksLimit: 14,
              font: tickFont(),
            },
            border: { color: C.grid },
          },
          y: {
            min: 0,
            suggestedMax: 4.5,
            grid: { color: C.grid },
            ticks: { color: C.muted, font: tickFont() },
            border: { color: C.grid },
          },
        },
        plugins: {
          legend: legendOpts(),
          title: {
            display: true,
            text: "Means by comparison category",
            color: C.text,
            font: titleFont(),
          },
        },
      },
    })
    );
  }

  var elS = document.getElementById("chart-single-session");
  if (elS && window.Chart && payload.single_exam) {
    var se = payload.single_exam;
    registerChart(
    new Chart(elS, {
      type: "line",
      data: {
        labels: se.labels,
        datasets: [
          {
            label: "Quality code",
            data: se.quality_code,
            borderColor: C.accent,
            backgroundColor: C.isLight
              ? "rgba(3, 105, 161, 0.12)"
              : "rgba(56, 189, 248, 0.12)",
            tension: 0.25,
            fill: false,
            pointRadius: 4,
            pointHoverRadius: 6,
          },
          {
            label: "Appropriateness code",
            data: se.grade_code,
            borderColor: C.mint,
            backgroundColor: "rgba(52, 211, 153, 0.1)",
            tension: 0.25,
            fill: false,
            pointRadius: 4,
          },
          {
            label: "Relevance (0–10)",
            data: se.relevance,
            borderColor: C.accent2,
            tension: 0.25,
            fill: false,
            pointRadius: 3,
            yAxisID: "y1",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: layoutPadding() },
        interaction: { mode: "index", intersect: false },
        scales: {
          x: {
            grid: { color: C.grid },
            ticks: { color: C.text, font: tickFont() },
            border: { color: C.grid },
          },
          y: {
            type: "linear",
            position: "left",
            min: 0,
            max: 4.5,
            title: {
              display: true,
              text: "Codes / scaled",
              color: C.text,
              font: tickFont(),
            },
            grid: { color: C.grid },
            ticks: { color: C.muted, font: tickFont() },
            border: { color: C.grid },
          },
          y1: {
            type: "linear",
            position: "right",
            min: 0,
            max: 10,
            grid: { drawOnChartArea: false },
            ticks: { color: C.muted, font: tickFont() },
            border: { display: false },
            title: {
              display: true,
              text: "Relevance",
              color: C.text,
              font: tickFont(),
            },
          },
        },
        plugins: {
          legend: legendOpts(),
          title: {
            display: true,
            text: "Single session — per question",
            color: C.text,
            font: titleFont(),
          },
        },
      },
    })
    );
  }

  scheduleChartReflow();
})();
