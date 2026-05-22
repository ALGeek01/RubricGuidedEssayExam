/**
 * Exam question analysis dashboard — Chart.js with AI / manual / compare views.
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
    return {
      accent: pick("--accent", "#38bdf8"),
      accent2: pick("--accent-2", "#818cf8"),
      mint: "#34d399",
      rose: "#f472b6",
      amber: "#fbbf24",
      text: pick("--text", light ? "#0f172a" : "#eef2f8"),
      legend: pick("--text", light ? "#0f172a" : "#f1f5f9"),
      muted: light ? "#334155" : pick("--muted", "#94a3b8"),
      grid: light ? "rgba(15, 23, 42, 0.2)" : "rgba(148, 163, 184, 0.28)",
      surface: light ? "rgba(255, 255, 255, 0)" : "rgba(24, 34, 54, 0.5)",
      donutBorder: light ? "rgba(15, 23, 42, 0.35)" : "rgba(15, 23, 42, 0.85)",
      chartBackground: light ? "rgba(241, 245, 249, 1)" : "rgba(22, 32, 52, 1)",
      isLight: light,
    };
  }

  /** High-contrast palette for PDF / share exports (readable on white paper). */
  function buildPrintChartPalette() {
    return {
      accent: "#0369a1",
      accent2: "#4338ca",
      mint: "#047857",
      rose: "#be185d",
      amber: "#b45309",
      text: "#020617",
      muted: "#334155",
      grid: "rgba(15, 23, 42, 0.28)",
      surface: "#ffffff",
      donutBorder: "#ffffff",
      isLight: true,
    };
  }

  var printExportMode = false;
  var pdfBgPluginRegistered = false;
  var pdfTypographyPluginRegistered = false;
  var savedChartDefaults = null;
  var PRINT_INK = "#020617";
  var PRINT_INK_LEGEND = "#000000";

  var pdfBgPlugin = {
    id: "rgeePdfWhiteBackground",
    beforeDraw: function (chart) {
      if (!printExportMode) return;
      var ctx = chart.ctx;
      ctx.save();
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, chart.width, chart.height);
      ctx.restore();
    },
  };

  var themeChartBgPlugin = {
    id: "rgeeThemeChartBackground",
    beforeDraw: function (chart) {
      if (printExportMode) return;
      var ctx = chart.ctx;
      ctx.save();
      ctx.fillStyle = C.chartBackground || (C.isLight ? "#f1f5f9" : "#1a2338");
      ctx.fillRect(0, 0, chart.width, chart.height);
      ctx.restore();
    },
  };

  var themeChartBgRegistered = false;

  var pdfTypographyPlugin = {
    id: "rgeePdfTypography",
    beforeInit: function (chart) {
      if (!printExportMode) return;
      applyInkToChartOptions(chart.options);
    },
    beforeUpdate: function (chart) {
      if (!printExportMode) return;
      applyInkToChartOptions(chart.options);
    },
  };

  function chartInkColor() {
    return printExportMode ? PRINT_INK : C.text;
  }

  function chartInkLegendColor() {
    return printExportMode ? PRINT_INK_LEGEND : C.legend || C.text;
  }

  function chartInkMuted() {
    return printExportMode ? "#1e293b" : C.muted;
  }

  function syncThemeChartDefaults() {
    C = getPalette();
    if (!window.Chart) return;
    Chart.defaults.color = chartInkColor();
    Chart.defaults.font = {
      family: "Outfit, system-ui, sans-serif",
      size: 12,
      weight: "600",
    };
  }

  function refreshChartsForTheme() {
    if (!views || printExportMode) return;
    syncThemeChartDefaults();
    renderView(activeView);
  }

  function applyInkToChartOptions(options) {
    if (!options) return;
    var ink = PRINT_INK;
    var legendInk = PRINT_INK_LEGEND;
    options.color = ink;
    if (!options.plugins) return;
    if (options.plugins.title) {
      options.plugins.title.color = ink;
      if (!options.plugins.title.font) options.plugins.title.font = titleFont();
    }
    if (options.plugins.legend && options.plugins.legend.labels) {
      options.plugins.legend.labels.color = legendInk;
      options.plugins.legend.labels.font = {
        family: "Outfit, system-ui, sans-serif",
        size: printExportMode ? 13 : 12,
        weight: printExportMode ? "700" : "600",
      };
    }
    if (options.scales) {
      Object.keys(options.scales).forEach(function (key) {
        var sc = options.scales[key];
        if (!sc) return;
        if (sc.ticks) {
          sc.ticks.color = chartInkMuted();
        }
        if (sc.title) {
          sc.title.color = ink;
        }
      });
    }
  }

  function applyInkToChartInstance(chart) {
    if (!chart || !printExportMode) return;
    applyInkToChartOptions(chart.options);
    if (chart.legend && chart.legend.options && chart.legend.options.labels) {
      chart.legend.options.labels.color = PRINT_INK_LEGEND;
    }
    if (chart.canvas && chart.canvas.parentElement) {
      chart.canvas.parentElement.style.color = PRINT_INK;
    }
  }

  function prepareChartDomForPrint() {
    document.querySelectorAll(".analysis-chart-canvas-wrap").forEach(function (wrap) {
      wrap.style.color = PRINT_INK;
      wrap.style.background = "#ffffff";
    });
  }

  function clearChartDomPrintStyles() {
    document.querySelectorAll(".analysis-chart-canvas-wrap").forEach(function (wrap) {
      wrap.style.color = "";
      wrap.style.background = "";
    });
  }

  function getPalette() {
    return printExportMode ? buildPrintChartPalette() : buildChartPalette();
  }

  function setPrintExportMode(on) {
    printExportMode = !!on;
    C = getPalette();
    if (!window.Chart) return;

    if (printExportMode) {
      prepareChartDomForPrint();
      if (!savedChartDefaults) {
        savedChartDefaults = {
          color: Chart.defaults.color,
          font: Chart.defaults.font
            ? {
                family: Chart.defaults.font.family,
                size: Chart.defaults.font.size,
                weight: Chart.defaults.font.weight,
              }
            : undefined,
        };
      }
      Chart.defaults.color = PRINT_INK;
      Chart.defaults.font = {
        family: "Outfit, system-ui, sans-serif",
        size: 12,
        weight: "600",
      };
      if (!pdfBgPluginRegistered) {
        Chart.register(pdfBgPlugin);
        pdfBgPluginRegistered = true;
      }
      if (!pdfTypographyPluginRegistered) {
        Chart.register(pdfTypographyPlugin);
        pdfTypographyPluginRegistered = true;
      }
      return;
    }

    clearChartDomPrintStyles();
    if (savedChartDefaults) {
      Chart.defaults.color = savedChartDefaults.color;
      if (savedChartDefaults.font) {
        Chart.defaults.font = savedChartDefaults.font;
      }
    }
  }

  function chartDevicePixelRatio() {
    return printExportMode ? 2 : undefined;
  }

  function baseChartOptions(extra) {
    var opt = extra || {};
    var dpr = chartDevicePixelRatio();
    if (dpr) {
      opt.devicePixelRatio = dpr;
    }
    return opt;
  }

  var C = buildChartPalette();
  var labels14 = ["Code 1", "Code 2", "Code 3", "Code 4"];
  var deltaLabels = ["−3", "−2", "−1", "0", "+1", "+2", "+3"];
  var charts = [];
  var rootPayload = null;
  var views = null;
  var activeView = "ai";
  var debounceTimer = null;
  var chartImageCache = { ai: null, manual: null, compare: null };

  function layoutPadding() {
    return { top: 8, right: 10, bottom: 10, left: 8 };
  }

  function titleFont() {
    return { family: "Outfit, system-ui, sans-serif", size: 14, weight: "700" };
  }

  function tickFont() {
    return { family: "Outfit, system-ui, sans-serif", size: 12, weight: "600" };
  }

  function legendOpts() {
    return {
      labels: {
        color: chartInkLegendColor(),
        font: {
          family: "Outfit, system-ui, sans-serif",
          size: C.isLight ? 13 : 12,
          weight: "700",
        },
        boxWidth: 12,
        padding: 12,
      },
    };
  }

  function titleOpts(text, show) {
    return {
      display: show !== false,
      text: text,
      color: chartInkColor(),
      font: {
        family: "Outfit, system-ui, sans-serif",
        size: C.isLight ? 15 : 14,
        weight: "700",
      },
    };
  }

  function donutPlugins(title) {
    if (printExportMode) {
      return {
        legend: { display: false },
        title: { display: false, text: title },
      };
    }
    return {
      legend: legendOpts(),
      title: titleOpts(title),
    };
  }

  function donutEmptySegmentColors() {
    return printExportMode
      ? ["#cbd5e1", "#cbd5e1", "#cbd5e1", "#cbd5e1"]
      : [C.muted, C.muted, C.muted, C.muted];
  }

  function destroyCharts() {
    charts.forEach(function (ch) {
      try {
        ch.destroy();
      } catch (e) {
        /* ignore */
      }
    });
    charts = [];
  }

  function registerChart(chart) {
    if (chart) charts.push(chart);
  }

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

  function setWidgetVisibility(mode) {
    document.querySelectorAll("[data-show-views]").forEach(function (el) {
      var allowed = (el.getAttribute("data-show-views") || "").split(/\s+/);
      var show = allowed.indexOf(mode) !== -1;
      if (show) {
        el.removeAttribute("hidden");
      } else {
        el.setAttribute("hidden", "hidden");
      }
    });
  }

  function updateAccentMetric(mode, v) {
    var kicker = document.getElementById("metric-accent-kicker");
    var value = document.getElementById("metric-accent-value");
    var foot = document.getElementById("metric-accent-foot");
    if (!kicker || !value || !foot) return;

    if (mode === "ai") {
      kicker.textContent = "Mean relevance";
      value.textContent =
        v.overall && typeof v.overall.relevance === "number"
          ? v.overall.relevance.toFixed(2)
          : "—";
      foot.textContent = "0–10 embedding signal";
      return;
    }
    if (mode === "manual") {
      kicker.textContent = "Mean manual Qly";
      value.textContent =
        v.overall && typeof v.overall.mean_quality === "number"
          ? v.overall.mean_quality.toFixed(2)
          : "—";
      foot.textContent =
        "Instructor ranks set for " + String(v.manual_qly_set || 0) + " question(s)";
      return;
    }
    kicker.textContent = "Qly agreement";
    var pct = v.qly && typeof v.qly.agree_pct === "number" ? v.qly.agree_pct : null;
    value.textContent = pct !== null ? pct.toFixed(1) + "%" : "—";
    foot.textContent =
      v.qly && v.qly.paired
        ? v.qly.agree + " of " + v.qly.paired + " paired (AI vs you)"
        : "Save manual Qly ranks to compare";
  }

  function updateHeadlineStats(v, mode) {
    var mt = document.getElementById("metric-total");
    var ms = document.getElementById("metric-sessions");
    if (mt) mt.textContent = String(v.total != null ? v.total : "—");
    if (ms) {
      ms.textContent =
        mode === "ai" && typeof v.sessions === "number"
          ? String(v.sessions)
          : mode === "manual"
            ? String(v.manual_lvl_set != null ? v.manual_lvl_set : "—")
            : mode === "compare" && v.lvl
              ? String(v.lvl.paired || 0)
              : "—";
    }
    var sessionsKicker = document.querySelector(
      "#metric-sessions"
    );
    if (sessionsKicker) {
      var foot = sessionsKicker.parentElement;
      if (foot) {
        var kicker = foot.querySelector(".analysis-widget-kicker");
        var footEl = foot.querySelector(".analysis-widget-foot");
        if (kicker && footEl) {
          if (mode === "ai") {
            kicker.textContent = "Exam sessions";
            footEl.textContent = "Distinct session ids";
          } else if (mode === "manual") {
            kicker.textContent = "Manual Lvl set";
            footEl.textContent = "Questions with appropriateness rank";
          } else {
            kicker.textContent = "Lvl pairs";
            footEl.textContent = "Both AI and manual Lvl present";
          }
        }
      }
    }
    updateAccentMetric(mode, v);
  }

  function donutChart(elId, data, title, colors) {
    var el = document.getElementById(elId);
    if (!el || !window.Chart) return;
    registerChart(
      new Chart(el, baseChartOptions({
        type: "doughnut",
        data: {
          labels: labels14,
          datasets: [
            {
              data: data,
              backgroundColor: colors,
              borderColor: C.donutBorder,
              borderWidth: 2,
              hoverOffset: 6,
            },
          ],
        },
        options: {
          color: chartInkColor(),
          responsive: true,
          maintainAspectRatio: false,
          layout: { padding: layoutPadding() },
          cutout: "58%",
          plugins: donutPlugins(title),
        },
      }))
    );
  }

  function renderAi(v) {
    updateHeadlineStats(v, "ai");
    donutChart(
      "chart-quality-donut",
      v.quality_freq || [0, 0, 0, 0],
      "AI essay quality codes (1–4)",
      [C.accent, C.accent2, C.mint, C.rose]
    );
    donutChart(
      "chart-grade-donut",
      v.grade_freq || [0, 0, 0, 0],
      "AI grade fit codes (1–4)",
      [C.mint, C.accent, C.amber, C.accent2]
    );

    var elO = document.getElementById("chart-overall-bars");
    if (elO && window.Chart && v.overall) {
      registerChart(
        new Chart(elO, baseChartOptions({
          type: "bar",
          data: {
            labels: ["Relevance", "Emb. quality", "Humor / levity"],
            datasets: [
              {
                label: "Mean (0–10)",
                data: [v.overall.relevance, v.overall.quality, v.overall.humor],
                backgroundColor: [C.accent, C.accent2, C.mint],
                borderRadius: 8,
                borderSkipped: false,
              },
            ],
          },
          options: {
            color: chartInkColor(),
            indexAxis: "y",
            responsive: true,
            maintainAspectRatio: false,
            layout: { padding: layoutPadding() },
            scales: {
              x: {
                min: 0,
                max: 10,
                grid: { color: C.grid },
                ticks: { color: chartInkMuted(), font: tickFont() },
                border: { color: C.grid },
              },
              y: {
                grid: { display: false },
                ticks: { color: chartInkColor(), font: tickFont() },
                border: { display: false },
              },
            },
            plugins: {
              legend: { display: false },
              title: titleOpts("Supplementary embedding means"),
            },
          },
        }))
      );
    }

    renderCategoryBar(v.categories, "ai");
    renderSingleSession(v.single_exam, "ai");
  }

  function renderManual(v) {
    updateHeadlineStats(v, "manual");
    if (v.no_manual) {
      donutChart(
        "chart-quality-donut",
        [0, 0, 0, 0],
        "Manual Qly — none saved yet",
        donutEmptySegmentColors()
      );
      donutChart(
        "chart-grade-donut",
        [0, 0, 0, 0],
        "Manual Lvl — none saved yet",
        donutEmptySegmentColors()
      );
    } else {
      donutChart(
        "chart-quality-donut",
        v.quality_freq || [0, 0, 0, 0],
        "Your quality ranks (1–4)",
        [C.rose, C.amber, C.mint, C.accent]
      );
      donutChart(
        "chart-grade-donut",
        v.grade_freq || [0, 0, 0, 0],
        "Your appropriateness ranks (1–4)",
        [C.accent2, C.mint, C.accent, C.rose]
      );
    }
    renderCategoryBar(v.categories, "manual");
    renderSingleSession(v.single_exam, "manual");
  }

  function renderCompare(v) {
    updateHeadlineStats(v, "compare");
    var elQ = document.getElementById("chart-quality-donut");
    if (elQ && window.Chart) {
      registerChart(
        new Chart(elQ, baseChartOptions({
          type: "bar",
          data: {
            labels: labels14,
            datasets: [
              {
                label: "AI Qly",
                data: v.quality_freq_ai || [0, 0, 0, 0],
                backgroundColor: C.accent,
                borderRadius: 4,
              },
              {
                label: "Your Qly",
                data: v.quality_freq_manual || [0, 0, 0, 0],
                backgroundColor: C.rose,
                borderRadius: 4,
              },
            ],
          },
          options: {
            color: chartInkColor(),
            responsive: true,
            maintainAspectRatio: false,
            layout: { padding: layoutPadding() },
            scales: {
              x: {
                grid: { display: false },
                ticks: { color: chartInkColor(), font: tickFont() },
                border: { color: C.grid },
              },
              y: {
                min: 0,
                suggestedMax: 4,
                grid: { color: C.grid },
                ticks: { color: chartInkMuted(), font: tickFont(), precision: 0 },
                border: { color: C.grid },
              },
            },
            plugins: {
              legend: legendOpts(),
              title: titleOpts("Quality code counts — AI vs you"),
            },
          },
        }))
      );
    }

    var elG = document.getElementById("chart-grade-donut");
    if (elG && window.Chart) {
      registerChart(
        new Chart(elG, baseChartOptions({
          type: "bar",
          data: {
            labels: labels14,
            datasets: [
              {
                label: "AI Lvl",
                data: v.grade_freq_ai || [0, 0, 0, 0],
                backgroundColor: C.mint,
                borderRadius: 4,
              },
              {
                label: "Your Lvl",
                data: v.grade_freq_manual || [0, 0, 0, 0],
                backgroundColor: C.amber,
                borderRadius: 4,
              },
            ],
          },
          options: {
            color: chartInkColor(),
            responsive: true,
            maintainAspectRatio: false,
            layout: { padding: layoutPadding() },
            scales: {
              x: {
                grid: { display: false },
                ticks: { color: chartInkColor(), font: tickFont() },
                border: { color: C.grid },
              },
              y: {
                min: 0,
                suggestedMax: 4,
                grid: { color: C.grid },
                ticks: { color: chartInkMuted(), font: tickFont(), precision: 0 },
                border: { color: C.grid },
              },
            },
            plugins: {
              legend: legendOpts(),
              title: titleOpts("Appropriateness counts — AI vs you"),
            },
          },
        }))
      );
    }

    var elD = document.getElementById("chart-compare-delta");
    if (elD && window.Chart) {
      registerChart(
        new Chart(elD, baseChartOptions({
          type: "bar",
          data: {
            labels: deltaLabels,
            datasets: [
              {
                label: "Qly Δ (you − AI)",
                data: v.delta_qly_freq || [0, 0, 0, 0, 0, 0, 0],
                backgroundColor: C.accent,
                borderRadius: 4,
              },
              {
                label: "Lvl Δ (you − AI)",
                data: v.delta_lvl_freq || [0, 0, 0, 0, 0, 0, 0],
                backgroundColor: C.mint,
                borderRadius: 4,
              },
            ],
          },
          options: {
            color: chartInkColor(),
            responsive: true,
            maintainAspectRatio: false,
            layout: { padding: layoutPadding() },
            scales: {
              x: {
                grid: { display: false },
                ticks: { color: chartInkColor(), font: tickFont() },
                border: { color: C.grid },
              },
              y: {
                min: 0,
                grid: { color: C.grid },
                ticks: { color: chartInkMuted(), font: tickFont(), precision: 0 },
                border: { color: C.grid },
              },
            },
            plugins: {
              legend: legendOpts(),
              title: titleOpts("Paired rank deltas (manual − AI)"),
            },
          },
        }))
      );
    }

    renderCategoryBar(v.categories, "compare");
    renderSingleSession(v.single_exam, "compare");
  }

  function renderCategoryBar(cats, mode) {
    var elC = document.getElementById("chart-by-category");
    if (!elC || !window.Chart || !cats || !cats.length) return;

    var labels = cats.map(function (c) {
      return c.label;
    });
    var datasets;
    var title;

    if (mode === "manual") {
      title = "Mean manual codes by category";
      datasets = [
        {
          label: "Mean manual Qly",
          data: cats.map(function (c) {
            return c.mean_manual_quality != null ? c.mean_manual_quality : null;
          }),
          backgroundColor: C.rose,
          borderRadius: 5,
        },
        {
          label: "Mean manual Lvl",
          data: cats.map(function (c) {
            return c.mean_manual_grade != null ? c.mean_manual_grade : null;
          }),
          backgroundColor: C.amber,
          borderRadius: 5,
        },
      ];
    } else if (mode === "compare") {
      title = "AI vs manual means by category";
      datasets = [
        {
          label: "AI mean Qly",
          data: cats.map(function (c) {
            return c.mean_ai_quality;
          }),
          backgroundColor: C.accent,
          borderRadius: 5,
        },
        {
          label: "Your mean Qly",
          data: cats.map(function (c) {
            return c.mean_manual_quality != null ? c.mean_manual_quality : null;
          }),
          backgroundColor: C.rose,
          borderRadius: 5,
        },
        {
          label: "AI mean Lvl",
          data: cats.map(function (c) {
            return c.mean_ai_grade;
          }),
          backgroundColor: C.mint,
          borderRadius: 5,
        },
        {
          label: "Your mean Lvl",
          data: cats.map(function (c) {
            return c.mean_manual_grade != null ? c.mean_manual_grade : null;
          }),
          backgroundColor: C.amber,
          borderRadius: 5,
        },
      ];
    } else {
      title = "Means by comparison category";
      datasets = [
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
      ];
    }

    registerChart(
      new Chart(elC, baseChartOptions({
        type: "bar",
        data: { labels: labels, datasets: datasets },
        options: {
          color: chartInkColor(),
          responsive: true,
          maintainAspectRatio: false,
          layout: { padding: layoutPadding() },
          scales: {
            x: {
              grid: { display: false },
              ticks: {
                color: chartInkColor(),
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
              ticks: { color: chartInkMuted(), font: tickFont() },
              border: { color: C.grid },
            },
          },
          plugins: {
            legend: legendOpts(),
            title: titleOpts(title),
          },
        },
      }))
    );
  }

  function renderSingleSession(se, mode) {
    var elS = document.getElementById("chart-single-session");
    if (!elS || !window.Chart || !se) return;

    var datasets;
    var title = "Single session — per question";

    if (mode === "manual") {
      datasets = [
        {
          label: "Your Qly",
          data: se.quality_code,
          borderColor: C.rose,
          tension: 0.25,
          fill: false,
          pointRadius: 4,
          spanGaps: true,
        },
        {
          label: "Your Lvl",
          data: se.grade_code,
          borderColor: C.amber,
          tension: 0.25,
          fill: false,
          pointRadius: 4,
          spanGaps: true,
        },
      ];
      title = "Your manual ranks — single session";
    } else if (mode === "compare") {
      datasets = [
        {
          label: "AI Qly",
          data: se.ai_quality,
          borderColor: C.accent,
          tension: 0.25,
          fill: false,
          pointRadius: 4,
        },
        {
          label: "Your Qly",
          data: se.man_quality,
          borderColor: C.rose,
          tension: 0.25,
          fill: false,
          pointRadius: 4,
          spanGaps: true,
        },
        {
          label: "AI Lvl",
          data: se.ai_grade,
          borderColor: C.mint,
          tension: 0.25,
          fill: false,
          pointRadius: 4,
        },
        {
          label: "Your Lvl",
          data: se.man_grade,
          borderColor: C.amber,
          tension: 0.25,
          fill: false,
          pointRadius: 4,
          spanGaps: true,
        },
      ];
      title = "AI vs your ranks — single session";
    } else {
      datasets = [
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
        },
        {
          label: "Appropriateness code",
          data: se.grade_code,
          borderColor: C.mint,
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
      ];
    }

    var options = {
      color: chartInkColor(),
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: layoutPadding() },
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          grid: { color: C.grid },
          ticks: { color: chartInkColor(), font: tickFont() },
          border: { color: C.grid },
        },
        y: {
          type: "linear",
          position: "left",
          min: 0,
          max: 4.5,
          grid: { color: C.grid },
          ticks: { color: chartInkMuted(), font: tickFont() },
          border: { color: C.grid },
        },
      },
      plugins: {
        legend: legendOpts(),
        title: titleOpts(title),
      },
    };

    if (mode === "ai" && se.relevance) {
      options.scales.y1 = {
        type: "linear",
        position: "right",
        min: 0,
        max: 10,
        grid: { drawOnChartArea: false },
        ticks: { color: chartInkMuted(), font: tickFont() },
        border: { display: false },
      };
    }

    registerChart(
      new Chart(elS, baseChartOptions({
        type: "line",
        data: { labels: se.labels, datasets: datasets },
        options: options,
      }))
    );
  }

  function buildChartExportItem(ch) {
    var id = ch.canvas.id;
    var titlePlugin = ch.options.plugins && ch.options.plugins.title;
    var titleText = titlePlugin && titlePlugin.text ? titlePlugin.text : id;
    var item = {
      src: ch.toBase64Image("image/png", 1),
      chartId: id,
      title: titleText,
    };

    if (ch.config.type === "doughnut" && ch.data && ch.data.datasets && ch.data.datasets[0]) {
      item.isDonut = true;
      item.legend = [];
      var labels = ch.data.labels || labels14;
      var ds = ch.data.datasets[0];
      var colors = ds.backgroundColor;
      var values = ds.data || [];
      for (var i = 0; i < labels.length; i += 1) {
        item.legend.push({
          label: String(labels[i]),
          color: Array.isArray(colors) ? colors[i] : colors,
          value: values[i] != null ? values[i] : 0,
        });
      }
    }

    return item;
  }

  function exportChartImages() {
    var out = {};
    charts.forEach(function (ch) {
      if (!ch || !ch.canvas || !ch.canvas.id) return;
      try {
        applyInkToChartInstance(ch);
        ch.update("none");
        out[ch.canvas.id] = buildChartExportItem(ch);
      } catch (e) {
        /* ignore */
      }
    });
    return out;
  }

  function cacheActiveViewCharts() {
    chartImageCache[activeView] = exportChartImages();
  }

  function renderView(mode) {
    if (!views || !views[mode] || views[mode].empty) return;
    C = getPalette();
    destroyCharts();
    setWidgetVisibility(mode);
    activeView = mode;
    if (mode === "ai") renderAi(views.ai);
    else if (mode === "manual") renderManual(views.manual);
    else if (mode === "compare") renderCompare(views.compare);
    scheduleChartReflow();
    setTimeout(cacheActiveViewCharts, printExportMode ? 220 : 180);
  }

  function captureAllViewCharts(forPrint) {
    var modes = ["ai", "manual", "compare"];
    var start = activeView;
    var i = 0;
    var waitMs = forPrint ? 560 : 320;

    setPrintExportMode(!!forPrint);

    return new Promise(function (resolve) {
      function step() {
        if (i >= modes.length) {
          setPrintExportMode(false);
          renderView(start);
          setTimeout(function () {
            resolve({
              ai: chartImageCache.ai || {},
              manual: chartImageCache.manual || {},
              compare: chartImageCache.compare || {},
            });
          }, 280);
          return;
        }
        var mode = modes[i];
        i += 1;
        if (!views[mode] || views[mode].empty) {
          chartImageCache[mode] = {};
          step();
          return;
        }
        renderView(mode);
        setTimeout(function () {
          cacheActiveViewCharts();
          step();
        }, waitMs);
      }
      step();
    });
  }

  function init() {
    var payloadEl = document.getElementById("analysis-chart-payload");
    if (!payloadEl) return;

    var raw = payloadEl.textContent.trim();
    if (!raw) return;

    try {
      rootPayload = JSON.parse(raw);
    } catch (e) {
      return;
    }

    if (rootPayload.empty) return;

    views = rootPayload.views || {
      ai: rootPayload,
      manual: { empty: true },
      compare: { empty: true },
    };

    var dashboardEl = document.getElementById("analysis-dashboard");
    if (dashboardEl && typeof ResizeObserver !== "undefined") {
      var ro = new ResizeObserver(scheduleChartReflow);
      ro.observe(dashboardEl);
    }
    window.addEventListener("resize", scheduleChartReflow, { passive: true });

    if (window.Chart && !themeChartBgRegistered) {
      Chart.register(themeChartBgPlugin);
      themeChartBgRegistered = true;
    }

    syncThemeChartDefaults();

    if (typeof MutationObserver !== "undefined") {
      var themeObserver = new MutationObserver(function (mutations) {
        for (var i = 0; i < mutations.length; i += 1) {
          if (mutations[i].attributeName === "data-theme") {
            refreshChartsForTheme();
            break;
          }
        }
      });
      themeObserver.observe(document.documentElement, { attributes: true });
    }

    renderView("ai");

    window.rgeeAnalysisCharts = {
      setView: function (mode) {
        if (!views[mode] || views[mode].empty) return;
        renderView(mode);
      },
      getView: function () {
        return activeView;
      },
      getPayload: function () {
        return rootPayload;
      },
      exportChartImages: exportChartImages,
      captureAllViewCharts: captureAllViewCharts,
      getChartImageCache: function () {
        return chartImageCache;
      },
      refreshTheme: refreshChartsForTheme,
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
