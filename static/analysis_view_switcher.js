/**
 * In-page AI / manual / compare switcher for question analysis results.
 */
(function () {
  "use strict";

  var VIEW_COPY = {
    ai: {
      title: "Analysis overview — AI ranking",
      lead: "AI embedding ranks (1–4) and supplementary 0–10 signals for this filtered sample.",
      category:
        "AI aggregates: continuous embedding means plus mean 4-point codes by comparison category.",
      legend:
        "Collapsed cards show AI codes; expand for embedding rationale and supplementary signals.",
    },
    manual: {
      title: "Analysis overview — manual ranking",
      lead: "Instructor manual ranks (1–4) you saved on Manual feedback. Charts use only questions with a saved rank.",
      category: "Manual ranks aggregated by comparison category (mean tier where at least one rank exists).",
      legend:
        "Collapsed cards emphasize your Qly/Lvl ranks; expand for manual bars, notes, and prompt.",
    },
    compare: {
      title: "Analysis overview — AI vs you",
      lead: "Side-by-side AI embedding ranks and your manual ranks, plus agreement and delta summaries.",
      category:
        "Per category: mean AI vs mean manual codes and agreement % where both ranks exist.",
      legend:
        "Compare view highlights deltas; expand for the AI vs you summary strip and full detail.",
    },
  };

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatCell(v, digits) {
    if (v == null || v === "") return "—";
    if (typeof v === "number") return v.toFixed(digits != null ? digits : 2);
    return escapeHtml(v);
  }

  function categoryCell(row, compareBy) {
    if (row.label) {
      return escapeHtml(row.label);
    }
    if (compareBy === "education_level" && row.education_level != null) {
      return '<span class="pill pill-level pill-sm">' + escapeHtml(row.education_level) + "</span>";
    }
    if (compareBy === "llm_mode" && row.llm_mode != null) {
      return '<span class="pill pill-llm pill-sm">' + escapeHtml(row.llm_mode) + "</span>";
    }
    if (compareBy === "quality_code" && row.quality_code != null) {
      return '<span class="pill pill-sm">Code ' + escapeHtml(row.quality_code) + "</span>";
    }
    if (compareBy === "grade_appropriateness_code" && row.grade_appropriateness_code != null) {
      return '<span class="pill pill-sm">Code ' + escapeHtml(row.grade_appropriateness_code) + "</span>";
    }
    if (compareBy === "session_id" && row.session_id != null) {
      return '<a href="/professor/exam/' + escapeHtml(row.session_id) + '">#' + escapeHtml(row.session_id) + "</a>";
    }
    return escapeHtml(row.label || "—");
  }

  function llmCell(row) {
    if (row.llm_mode == null) return "—";
    return '<span class="pill pill-llm pill-sm">' + escapeHtml(row.llm_mode) + "</span>";
  }

  function renderCategoryTable(mode, tables, compareBy, compareLabel) {
    var thead = document.getElementById("analysis-category-thead");
    var tbody = document.getElementById("analysis-category-tbody");
    var subtitle = document.getElementById("analysis-category-subtitle");
    if (!thead || !tbody || !tables) return;

    var rows = tables[mode] || [];
    var head = "";
    var body = "";

    if (mode === "manual") {
      if (subtitle) subtitle.textContent = VIEW_COPY.manual.category;
      head =
        "<tr><th scope=\"col\">" +
        escapeHtml(compareLabel) +
        '</th><th scope="col">LLM</th><th scope="col">Mean manual Qly</th><th scope="col">Mean manual Lvl</th><th scope="col"># Qly set</th><th scope="col"># Lvl set</th></tr>';
      body = rows
        .map(function (row) {
          return (
            "<tr><td>" +
            categoryCell(row, compareBy) +
            "</td><td>" +
            llmCell(row) +
            "</td><td>" +
            formatCell(row.mean_manual_quality, 2) +
            "</td><td>" +
            formatCell(row.mean_manual_grade, 2) +
            "</td><td>" +
            formatCell(row.manual_qly_n, 0) +
            "</td><td>" +
            formatCell(row.manual_lvl_n, 0) +
            "</td></tr>"
          );
        })
        .join("");
    } else if (mode === "compare") {
      if (subtitle) subtitle.textContent = VIEW_COPY.compare.category;
      head =
        "<tr><th scope=\"col\">" +
        escapeHtml(compareLabel) +
        '</th><th scope="col">LLM</th><th scope="col">Mean AI Qly</th><th scope="col">Mean you Qly</th><th scope="col">Qly agree %</th><th scope="col">Mean AI Lvl</th><th scope="col">Mean you Lvl</th><th scope="col">Lvl agree %</th></tr>';
      body = rows
        .map(function (row) {
          return (
            "<tr><td>" +
            categoryCell(row, compareBy) +
            "</td><td>" +
            llmCell(row) +
            "</td><td>" +
            formatCell(row.mean_ai_quality, 2) +
            "</td><td>" +
            formatCell(row.mean_manual_quality, 2) +
            "</td><td>" +
            (row.qly_agree_pct != null ? formatCell(row.qly_agree_pct, 1) + "%" : "—") +
            "</td><td>" +
            formatCell(row.mean_ai_grade, 2) +
            "</td><td>" +
            formatCell(row.mean_manual_grade, 2) +
            "</td><td>" +
            (row.lvl_agree_pct != null ? formatCell(row.lvl_agree_pct, 1) + "%" : "—") +
            "</td></tr>"
          );
        })
        .join("");
    } else {
      if (subtitle) subtitle.textContent = VIEW_COPY.ai.category;
      head =
        "<tr><th scope=\"col\">" +
        escapeHtml(compareLabel) +
        '</th><th scope="col">LLM</th><th scope="col">Mean Q code</th><th scope="col">Mean appr. code</th><th scope="col">Mean relevance</th><th scope="col">Mean embed. Q</th><th scope="col">Mean humor</th></tr>';
      body = rows
        .map(function (row) {
          return (
            "<tr><td>" +
            categoryCell(row, compareBy) +
            "</td><td>" +
            llmCell(row) +
            "</td><td>" +
            formatCell(row.mean_quality_code, 2) +
            "</td><td>" +
            formatCell(row.mean_grade_approp_code, 2) +
            "</td><td>" +
            formatCell(row.relevance_score, 2) +
            "</td><td>" +
            formatCell(row.quality_score, 2) +
            "</td><td>" +
            formatCell(row.humor_score, 2) +
            "</td></tr>"
          );
        })
        .join("");
    }

    thead.innerHTML = head;
    tbody.innerHTML = body || '<tr><td colspan="8" class="muted">No rows for this view.</td></tr>';
  }

  function applyDetailVisibility(mode) {
    var core = document.getElementById("semantic-analysis-results");
    if (core) core.setAttribute("data-analysis-view", mode);

    document.querySelectorAll(".analysis-pill-ai").forEach(function (el) {
      el.style.display = mode === "manual" ? "none" : "";
    });
    document.querySelectorAll(".analysis-pill-manual").forEach(function (el) {
      el.style.display = mode === "ai" ? "none" : "";
    });

    document.querySelectorAll(".analysis-detail-ai-section").forEach(function (el) {
      el.style.display = mode === "manual" ? "none" : "";
    });
    document.querySelectorAll(".analysis-detail-manual-section").forEach(function (el) {
      if (mode === "ai") {
        el.style.display = "none";
      } else {
        el.style.display = "";
      }
    });
    document.querySelectorAll(".analysis-view-compare-only").forEach(function (el) {
      if (mode === "compare") {
        el.removeAttribute("hidden");
      } else {
        el.setAttribute("hidden", "hidden");
      }
    });

    var subtitle = document.querySelector(".analysis-detail-subtitle");
    if (subtitle && VIEW_COPY[mode]) {
      var link = subtitle.querySelector("a");
      var linkHtml = link ? link.outerHTML : "";
      subtitle.innerHTML = VIEW_COPY[mode].legend + (linkHtml ? " " + linkHtml : "");
    }
  }

  function setActiveButton(mode) {
    document.querySelectorAll(".analysis-view-btn").forEach(function (btn) {
      var on = btn.getAttribute("data-view") === mode;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
  }

  function switchView(mode) {
    var dash = document.getElementById("analysis-dashboard");
    if (dash) dash.setAttribute("data-analysis-view", mode);

    var title = document.getElementById("analysis-dashboard-title");
    var lead = document.getElementById("analysis-dashboard-lead");
    if (title && VIEW_COPY[mode]) title.textContent = VIEW_COPY[mode].title;
    if (lead && VIEW_COPY[mode]) lead.textContent = VIEW_COPY[mode].lead;

    if (window.rgeeAnalysisCharts && window.rgeeAnalysisCharts.setView) {
      window.rgeeAnalysisCharts.setView(mode);
    }

    var payload =
      window.rgeeAnalysisCharts && window.rgeeAnalysisCharts.getPayload
        ? window.rgeeAnalysisCharts.getPayload()
        : null;
    if (payload && payload.views && payload.views.category_tables) {
      var panel = document.getElementById("analysis-category-panel");
      var compareBy = panel ? panel.getAttribute("data-compare-by") || "education_level" : "education_level";
      var compareLabel = panel
        ? panel.getAttribute("data-compare-label") || "Category"
        : "Category";
      renderCategoryTable(mode, payload.views.category_tables, compareBy, compareLabel);
    }

    applyDetailVisibility(mode);
    setActiveButton(mode);
  }

  function init() {
    var toggle = document.querySelector(".analysis-view-toggle");
    if (!toggle) return;

    toggle.addEventListener("click", function (ev) {
      var btn = ev.target.closest(".analysis-view-btn");
      if (!btn) return;
      var mode = btn.getAttribute("data-view");
      if (!mode) return;
      switchView(mode);
    });

    var waitCharts = setInterval(function () {
      if (window.rgeeAnalysisCharts) {
        clearInterval(waitCharts);
        switchView("ai");
      }
    }, 40);
    setTimeout(function () {
      clearInterval(waitCharts);
    }, 3000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
