/**
 * Question analysis — Share snapshot (PDF, email, JSON).
 */
(function () {
  "use strict";

  var backdrop = null;
  var dialog = null;
  var statusEl = null;
  var baseSnapshot = null;
  var busy = false;

  function $(id) {
    return document.getElementById(id);
  }

  function openDialog() {
    if (!backdrop || !dialog) return;
    backdrop.hidden = false;
    dialog.hidden = false;
    document.body.classList.add("analysis-share-open");
    var first = dialog.querySelector(".analysis-share-option:not([disabled])");
    if (first) first.focus();
  }

  function closeDialog() {
    if (!backdrop || !dialog) return;
    backdrop.hidden = true;
    dialog.hidden = true;
    document.body.classList.remove("analysis-share-open");
    $("btn-analysis-share").focus();
  }

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg || "";
  }

  function loadBaseSnapshot() {
    var el = $("analysis-share-payload");
    if (!el) return null;
    try {
      return JSON.parse(el.textContent || "null");
    } catch (e) {
      return null;
    }
  }

  function freqLine(freq, prefix) {
    if (!freq || !freq.length) return prefix + ": (none)";
    return (
      prefix +
      ": " +
      freq
        .map(function (n, i) {
          return "code " + (i + 1) + "=" + n;
        })
        .join(", ")
    );
  }

  function buildExecutiveSummary(pkg) {
    var f = pkg.filters || {};
    var lines = [
      "RGEE Exam Question Analysis — Share Snapshot",
      "Generated: " + (pkg.exported_at || pkg.generated_at || ""),
      "",
      "Filters",
      "- Session: " + (f.session_id != null ? "#" + f.session_id : "All recent"),
      "- Education level: " + (f.education_level_label || "Any"),
      "- LLM mode: " + (f.llm_mode_label || f.llm_mode || ""),
      "- Compare by: " + (f.compare_by_label || f.compare_by || ""),
      "- Max questions: " + (f.sample_limit != null ? f.sample_limit : ""),
      "",
      "Method: " + (pkg.methodology_note || "(not recorded)"),
      "",
    ];

    var m = pkg.metrics || {};
    var views = m.views || {};
    var ai = views.ai || m;
    if (ai && !ai.empty) {
      lines.push("AI ranking");
      lines.push("- Questions scored: " + (ai.total != null ? ai.total : "—"));
      lines.push("- Exam sessions: " + (ai.sessions != null ? ai.sessions : "—"));
      if (ai.overall) {
        lines.push(
          "- Mean relevance / emb.Q / humor: " +
            ai.overall.relevance +
            " / " +
            ai.overall.quality +
            " / " +
            ai.overall.humor
        );
      }
      lines.push(freqLine(ai.quality_freq, "- Quality tier counts"));
      lines.push(freqLine(ai.grade_freq, "- Appropriateness tier counts"));
      lines.push("");
    }

    var manual = views.manual;
    if (manual && !manual.empty) {
      lines.push("Manual ranking");
      lines.push("- Manual Qly set: " + (manual.manual_qly_set || 0));
      lines.push("- Manual Lvl set: " + (manual.manual_lvl_set || 0));
      if (manual.overall) {
        if (manual.overall.mean_quality != null) {
          lines.push("- Mean manual Qly: " + manual.overall.mean_quality);
        }
        if (manual.overall.mean_grade != null) {
          lines.push("- Mean manual Lvl: " + manual.overall.mean_grade);
        }
      }
      lines.push(freqLine(manual.quality_freq, "- Your Qly counts"));
      lines.push(freqLine(manual.grade_freq, "- Your Lvl counts"));
      lines.push("");
    }

    var cmp = views.compare;
    if (cmp && !cmp.empty) {
      lines.push("Compare (AI vs you)");
      if (cmp.qly) {
        lines.push(
          "- Qly paired: " +
            cmp.qly.paired +
            ", agree: " +
            cmp.qly.agree +
            (cmp.qly.agree_pct != null ? " (" + cmp.qly.agree_pct + "%)" : "")
        );
      }
      if (cmp.lvl) {
        lines.push(
          "- Lvl paired: " +
            cmp.lvl.paired +
            ", agree: " +
            cmp.lvl.agree +
            (cmp.lvl.agree_pct != null ? " (" + cmp.lvl.agree_pct + "%)" : "")
        );
      }
      lines.push("");
    }

    var mc = pkg.manual_rank_counts || {};
    lines.push("Manual ranks in sample: Qly=" + (mc.quality || 0) + ", Lvl=" + (mc.grade || 0));
    lines.push("Questions in export: " + ((pkg.questions && pkg.questions.length) || 0));
    lines.push("");
    lines.push("Full numeric payload and chart images are in the JSON export or PDF attachment.");

    return lines.join("\n");
  }

  function mergeExportPackage(chartImages) {
    var activeView =
      window.rgeeAnalysisCharts && window.rgeeAnalysisCharts.getView
        ? window.rgeeAnalysisCharts.getView()
        : "ai";
    var pkg = JSON.parse(JSON.stringify(baseSnapshot || {}));
    pkg.exported_at = new Date().toISOString();
    pkg.dashboard_view_at_export = activeView;
    pkg.chart_images = chartImages || {};
    pkg.summary_text = buildExecutiveSummary(pkg);
    return pkg;
  }

  function downloadJson(pkg) {
    var blob = new Blob([JSON.stringify(pkg, null, 2)], { type: "application/json" });
    var a = document.createElement("a");
    var stamp = (pkg.exported_at || "").slice(0, 10) || "export";
    a.href = URL.createObjectURL(blob);
    a.download = "rgee-analysis-share-" + stamp + ".json";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () {
      URL.revokeObjectURL(a.href);
      a.remove();
    }, 400);
  }

  function buildPrintHtml(pkg) {
    var f = pkg.filters || {};
    var host = $("analysis-share-print-root");
    if (!host) return null;

    function esc(s) {
      return String(s == null ? "" : s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    }

    function metricTable(viewName, data) {
      if (!data || data.empty) {
        return "<h3>" + esc(viewName) + "</h3><p>No data for this view.</p>";
      }
      var rows = "";
      rows += "<tr><th>Questions</th><td>" + esc(data.total) + "</td></tr>";
      if (viewName === "AI ranking" && data.sessions != null) {
        rows += "<tr><th>Sessions</th><td>" + esc(data.sessions) + "</td></tr>";
      }
      if (viewName === "Manual ranking") {
        rows += "<tr><th>Manual Qly set</th><td>" + esc(data.manual_qly_set) + "</td></tr>";
        rows += "<tr><th>Manual Lvl set</th><td>" + esc(data.manual_lvl_set) + "</td></tr>";
      }
      if (viewName === "Compare" && data.qly) {
        rows +=
          "<tr><th>Qly agreement</th><td>" +
          esc(data.qly.agree) +
          " / " +
          esc(data.qly.paired) +
          " (" +
          esc(data.qly.agree_pct) +
          "%)</td></tr>";
      }
      if (data.quality_freq) {
        rows +=
          "<tr><th>Quality freq (1–4)</th><td>" + esc(data.quality_freq.join(", ")) + "</td></tr>";
      }
      if (data.grade_freq) {
        rows +=
          "<tr><th>Grade freq (1–4)</th><td>" + esc(data.grade_freq.join(", ")) + "</td></tr>";
      }
      return (
        "<h3>" +
        esc(viewName) +
        '</h3><table class="analysis-share-pdf-table"><tbody>' +
        rows +
        "</tbody></table>"
      );
    }

    function chartImageSrc(entry) {
      if (!entry) return "";
      if (typeof entry === "string") return entry;
      return entry.src || "";
    }

    function chartHtmlLegend(entry) {
      if (!entry || !entry.isDonut || !entry.legend || !entry.legend.length) return "";
      var items = entry.legend
        .map(function (row) {
          return (
            '<li class="analysis-share-pdf-legend-item">' +
            '<span class="analysis-share-pdf-swatch" style="background:' +
            esc(row.color) +
            ';"></span>' +
            '<span class="analysis-share-pdf-legend-label">' +
            esc(row.label) +
            " · count " +
            esc(row.value) +
            "</span></li>"
          );
        })
        .join("");
      return '<ul class="analysis-share-pdf-legend">' + items + "</ul>";
    }

    function chartSection(label, images) {
      if (!images || !Object.keys(images).length) return "";
      var html =
        '<h4 class="analysis-share-pdf-chart-heading html2pdf__page-break-avoid">' +
        esc(label) +
        " charts</h4><div class=\"analysis-share-pdf-charts analysis-share-pdf-charts--stack\">";
      Object.keys(images).forEach(function (key) {
        var entry = images[key];
        var src = chartImageSrc(entry);
        if (!src) return;
        var title =
          entry && entry.title
            ? entry.title
            : key.replace(/chart-/g, "").replace(/-/g, " ");
        html +=
          '<div class="analysis-share-pdf-chart-block html2pdf__page-break-avoid">' +
          '<p class="analysis-share-pdf-chart-title">' +
          esc(title) +
          "</p>" +
          '<figure class="analysis-share-pdf-figure">' +
          '<img src="' +
          src +
          '" alt="' +
          esc(title) +
          '">' +
          "</figure>" +
          chartHtmlLegend(entry) +
          "</div>";
      });
      html += "</div>";
      return html;
    }

    var views = (pkg.metrics && pkg.metrics.views) || {};
    var imgs = pkg.chart_images || {};

    var qRows = (pkg.questions || [])
      .slice(0, 80)
      .map(function (q) {
        return (
          "<tr><td>#" +
          esc(q.session_id) +
          "</td><td>Q" +
          (parseInt(q.question_index, 10) + 1) +
          "</td><td>" +
          esc(q.quality_code) +
          "</td><td>" +
          esc(q.grade_appropriateness_code) +
          "</td><td>" +
          esc(q.manual_quality_code != null ? q.manual_quality_code : "—") +
          "</td><td>" +
          esc(q.manual_grade_code != null ? q.manual_grade_code : "—") +
          "</td><td>" +
          esc(q.relevance_score) +
          "</td></tr>"
        );
      })
      .join("");

    host.innerHTML =
      '<article class="analysis-share-pdf-doc" style="background:#ffffff;color:#020617;width:100%;">' +
      "<h1>Exam question analysis — snapshot</h1>" +
      "<p class=\"analysis-share-pdf-meta\">Generated " +
      esc(pkg.exported_at || pkg.generated_at) +
      "</p>" +
      "<h2>Filters</h2><table class=\"analysis-share-pdf-table\"><tbody>" +
      "<tr><th>Session</th><td>" +
      esc(f.session_id != null ? "#" + f.session_id : "All") +
      "</td></tr>" +
      "<tr><th>Education level</th><td>" +
      esc(f.education_level_label) +
      "</td></tr>" +
      "<tr><th>LLM mode</th><td>" +
      esc(f.llm_mode_label) +
      "</td></tr>" +
      "<tr><th>Compare by</th><td>" +
      esc(f.compare_by_label) +
      "</td></tr>" +
      "<tr><th>Sample limit</th><td>" +
      esc(f.sample_limit) +
      "</td></tr>" +
      "</tbody></table>" +
      "<h2>Method</h2><p>" +
      esc(pkg.methodology_note) +
      "</p>" +
      "<h2>Metrics by view</h2>" +
      metricTable("AI ranking", views.ai || pkg.metrics) +
      metricTable("Manual ranking", views.manual) +
      metricTable("Compare", views.compare) +
      chartSection("AI", imgs.ai) +
      chartSection("Manual", imgs.manual) +
      chartSection("Compare", imgs.compare) +
      "<h2>Questions (up to 80)</h2>" +
      '<table class="analysis-share-pdf-table analysis-share-pdf-qtable"><thead><tr>' +
      "<th>Session</th><th>Q</th><th>AI Qly</th><th>AI Lvl</th><th>You Qly</th><th>You Lvl</th><th>Rel</th>" +
      "</tr></thead><tbody>" +
      qRows +
      "</tbody></table>" +
      '<p class="analysis-share-pdf-foot">RGEE · ' +
      esc(pkg.page_path || "") +
      "</p></article>";

    return host;
  }

  var PDF_PRINT_STYLES =
    "body{margin:0;padding:12px;font-family:system-ui,sans-serif;font-size:11pt;color:#020617;background:#fff}" +
    ".analysis-share-pdf-doc{color:#020617;background:#fff;-webkit-print-color-adjust:exact;print-color-adjust:exact}" +
    ".analysis-share-pdf-doc h1,.analysis-share-pdf-doc h2,.analysis-share-pdf-doc h3,.analysis-share-pdf-doc h4{color:#020617}" +
    ".analysis-share-pdf-doc h1{font-size:18pt;margin:0 0 6px}" +
    ".analysis-share-pdf-doc h2{font-size:13pt;margin:14px 0 6px}" +
    ".analysis-share-pdf-doc h3{font-size:11.5pt;margin:10px 0 4px}" +
    ".analysis-share-pdf-doc h4{font-size:10.5pt;margin:8px 0 4px}" +
    ".analysis-share-pdf-meta,.analysis-share-pdf-foot{font-size:9pt;color:#334155}" +
    ".analysis-share-pdf-table{width:100%;border-collapse:collapse;margin:6px 0 10px;font-size:9.5pt}" +
    ".analysis-share-pdf-table th,.analysis-share-pdf-table td{border:1px solid #475569;padding:4px 6px;text-align:left;color:#020617}" +
    ".analysis-share-pdf-table th{background:#cbd5e1;font-weight:700}" +
    ".analysis-share-pdf-table td{background:#fff}" +
    ".analysis-share-pdf-charts--stack{display:flex;flex-direction:column;gap:14px}" +
    ".analysis-share-pdf-chart-block{margin:0 0 12px;page-break-inside:avoid;break-inside:avoid-page}" +
    ".analysis-share-pdf-chart-title{margin:0 0 6px;font-size:11pt;font-weight:700;color:#020617}" +
    ".analysis-share-pdf-figure{margin:0;page-break-inside:avoid}" +
    ".analysis-share-pdf-chart-heading{page-break-after:avoid}" +
    ".analysis-share-pdf-figure img{max-height:220px;width:100%;height:auto;object-fit:contain;display:block;border:1px solid #475569}" +
    ".analysis-share-pdf-legend{margin:8px 0 0;padding:0;list-style:none;display:flex;flex-wrap:wrap;gap:6px 14px}" +
    ".analysis-share-pdf-legend-item{display:inline-flex;align-items:center;gap:6px;margin:0}" +
    ".analysis-share-pdf-swatch{width:11px;height:11px;border-radius:2px;border:1px solid #475569;flex-shrink:0}" +
    ".analysis-share-pdf-legend-label{font-size:10pt;font-weight:700;color:#020617}";

  function boostPdfCloneForCapture(clonedDoc) {
    var doc = clonedDoc.querySelector(".analysis-share-pdf-doc");
    if (!doc) return;
    doc.style.color = "#020617";
    doc.style.background = "#ffffff";
    clonedDoc.querySelectorAll(".analysis-share-pdf-table th").forEach(function (th) {
      th.style.backgroundColor = "#cbd5e1";
      th.style.color = "#020617";
      th.style.borderColor = "#475569";
      th.style.fontWeight = "700";
    });
    clonedDoc.querySelectorAll(".analysis-share-pdf-table td").forEach(function (td) {
      td.style.color = "#020617";
      td.style.borderColor = "#475569";
      td.style.backgroundColor = "#ffffff";
    });
    clonedDoc.querySelectorAll(".analysis-share-pdf-figure img").forEach(function (img) {
      img.style.border = "1px solid #475569";
    });
    clonedDoc.querySelectorAll(".analysis-share-pdf-chart-title, .analysis-share-pdf-legend-label").forEach(
      function (el) {
        el.style.color = "#020617";
        el.style.fontWeight = "700";
      }
    );
  }

  function waitForPaint() {
    return new Promise(function (resolve) {
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          setTimeout(resolve, 150);
        });
      });
    });
  }

  function waitForImages(root) {
    var imgs = root.querySelectorAll("img");
    if (!imgs.length) return Promise.resolve();
    return Promise.all(
      Array.prototype.map.call(imgs, function (img) {
        if (img.complete && img.naturalWidth > 0) return Promise.resolve();
        return new Promise(function (resolve) {
          img.onload = resolve;
          img.onerror = resolve;
          setTimeout(resolve, 800);
        });
      })
    );
  }

  function beginPdfCapture(host) {
    host.classList.add("is-pdf-capture");
    document.body.classList.add("analysis-share-pdf-busy");
  }

  function endPdfCapture(host) {
    host.classList.remove("is-pdf-capture");
    document.body.classList.remove("analysis-share-pdf-busy");
  }

  function printWindowFallback(host) {
    return new Promise(function (resolve) {
      var w = window.open("", "_blank", "noopener,noreferrer,width=900,height=700");
      if (!w) {
        setStatus("Allow pop-ups, then try PDF again (or use Download JSON).");
        resolve();
        return;
      }
      w.document.open();
      w.document.write(
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>RGEE analysis snapshot</title>" +
          "<style>" +
          PDF_PRINT_STYLES +
          "</style></head><body>" +
          host.innerHTML +
          "</body></html>"
      );
      w.document.close();
      w.focus();
      setTimeout(function () {
        try {
          w.print();
        } catch (e) {
          /* ignore */
        }
        resolve();
      }, 400);
    });
  }

  function pdfFilename(pkg) {
    var stamp = (pkg.exported_at || "").slice(0, 10) || "export";
    return "rgee-analysis-share-" + stamp + ".pdf";
  }

  function jsonFilename(pkg) {
    var stamp = (pkg.exported_at || "").slice(0, 10) || "export";
    return "rgee-analysis-share-" + stamp + ".json";
  }

  async function buildPdfBlob(pkg) {
    var host = buildPrintHtml(pkg);
    if (!host) {
      throw new Error("Print container missing");
    }

    var target = host.querySelector(".analysis-share-pdf-doc") || host;
    var filename = pdfFilename(pkg);

    beginPdfCapture(host);
    try {
      await waitForPaint();
      await waitForImages(host);
      await waitForPaint();

      if (typeof html2pdf === "undefined") {
        return null;
      }

      return await html2pdf()
        .set({
          margin: [8, 8, 10, 8],
          filename: filename,
          image: { type: "png", quality: 1 },
          html2canvas: {
            scale: 3,
            useCORS: true,
            allowTaint: true,
            logging: false,
            backgroundColor: "#ffffff",
            scrollX: 0,
            scrollY: 0,
            letterRendering: true,
            onclone: function (clonedDoc) {
              boostPdfCloneForCapture(clonedDoc);
            },
          },
          jsPDF: { unit: "mm", format: "a4", orientation: "portrait" },
          pagebreak: {
            mode: ["css", "legacy"],
            avoid: [
              ".analysis-share-pdf-figure",
              ".analysis-share-pdf-chart-heading",
              ".html2pdf__page-break-avoid",
            ],
          },
        })
        .from(target)
        .outputPdf("blob");
    } finally {
      endPdfCapture(host);
    }
  }

  async function savePdf(pkg) {
    try {
      var blob = await buildPdfBlob(pkg);
      if (blob) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = pdfFilename(pkg);
        document.body.appendChild(a);
        a.click();
        setTimeout(function () {
          URL.revokeObjectURL(url);
          a.remove();
        }, 400);
        return;
      }
      var host = buildPrintHtml(pkg);
      if (!host) throw new Error("Print container missing");
      setStatus("Opening print dialog — choose Save as PDF.");
      await printWindowFallback(host);
    } catch (err) {
      console.error("html2pdf failed", err);
      setStatus("PDF engine failed — opening print dialog instead.");
      var host = buildPrintHtml(pkg);
      if (host) await printWindowFallback(host);
    }
  }

  function canUseNativeShare() {
    return typeof navigator !== "undefined" && typeof navigator.share === "function";
  }

  async function runNativeShare(btn) {
    if (busy || !baseSnapshot) return;
    busy = true;
    if (btn) {
      btn.setAttribute("aria-busy", "true");
    }
    try {
      var pkg = await buildFullPackage();
      var files = [];
      var jsonBlob = new Blob([JSON.stringify(pkg, null, 2)], { type: "application/json" });
      files.push(new File([jsonBlob], jsonFilename(pkg), { type: "application/json" }));

      try {
        var pdfBlob = await buildPdfBlob(pkg);
        if (pdfBlob) {
          files.push(new File([pdfBlob], pdfFilename(pkg), { type: "application/pdf" }));
        }
      } catch (pdfErr) {
        console.warn("PDF not attached to system share", pdfErr);
      }

      var pageUrl = window.location.origin + (pkg.page_path || window.location.pathname);
      var shareData = {
        title: "RGEE question analysis",
        text: (pkg.summary_text || buildExecutiveSummary(pkg)).slice(0, 8000),
        url: pageUrl,
      };

      if (navigator.canShare && files.length) {
        try {
          if (navigator.canShare({ files: files })) {
            shareData.files = files;
          } else if (navigator.canShare({ files: [files[0]] })) {
            shareData.files = [files[0]];
          }
        } catch (canErr) {
          /* ignore */
        }
      }

      await navigator.share(shareData);
    } catch (err) {
      if (err && err.name === "AbortError") {
        return;
      }
      console.warn("navigator.share failed, opening export dialog", err);
      setStatus("System share unavailable — choose an export format.");
      openDialog();
    } finally {
      busy = false;
      if (btn) {
        btn.removeAttribute("aria-busy");
      }
    }
  }

  function emailShare(pkg) {
    var subject = encodeURIComponent("RGEE question analysis snapshot");
    var body = encodeURIComponent(pkg.summary_text || buildExecutiveSummary(pkg));
    window.location.href = "mailto:?subject=" + subject + "&body=" + body;
  }

  async function buildFullPackage() {
    var chartImages = {};
    if (window.rgeeAnalysisCharts && window.rgeeAnalysisCharts.captureAllViewCharts) {
      setStatus("Capturing charts for all views…");
      chartImages = await window.rgeeAnalysisCharts.captureAllViewCharts(true);
    } else if (window.rgeeAnalysisCharts && window.rgeeAnalysisCharts.exportChartImages) {
      chartImages = { ai: window.rgeeAnalysisCharts.exportChartImages() };
    }
    return mergeExportPackage(chartImages);
  }

  async function runExport(kind) {
    if (busy || !baseSnapshot) return;
    busy = true;
    var opts = dialog.querySelectorAll(".analysis-share-option");
    opts.forEach(function (b) {
      b.disabled = true;
    });
    setStatus("Preparing snapshot…");
    try {
      var pkg = await buildFullPackage();
      if (kind === "json") {
        downloadJson(pkg);
        setStatus("JSON downloaded.");
      } else if (kind === "pdf") {
        setStatus("Building PDF…");
        await savePdf(pkg);
        setStatus("PDF saved.");
      } else if (kind === "email") {
        emailShare(pkg);
        setStatus("Email client opened with summary text.");
      }
      setTimeout(closeDialog, 600);
    } catch (err) {
      setStatus("Export failed. Try again or use JSON.");
      console.error(err);
    } finally {
      busy = false;
      opts.forEach(function (b) {
        b.disabled = false;
      });
    }
  }

  function onShareClick(ev) {
    var btn = ev.currentTarget;
    if (!baseSnapshot) {
      setStatus("Run analysis first to generate a shareable snapshot.");
      openDialog();
      return;
    }
    if (canUseNativeShare()) {
      runNativeShare(btn);
      return;
    }
    setStatus("");
    openDialog();
  }

  function init() {
    backdrop = $("analysis-share-backdrop");
    dialog = $("analysis-share-dialog");
    statusEl = $("analysis-share-status");
    baseSnapshot = loadBaseSnapshot();

    var btn = $("btn-analysis-share");
    if (!btn) return;

    btn.addEventListener("click", onShareClick);
    if (backdrop) {
      backdrop.addEventListener("click", closeDialog);
    }
    var closeBtn = $("analysis-share-close");
    if (closeBtn) closeBtn.addEventListener("click", closeDialog);

    dialog.querySelectorAll("[data-share-action]").forEach(function (el) {
      el.addEventListener("click", function () {
        var action = el.getAttribute("data-share-action");
        if (!baseSnapshot) {
          setStatus("Run analysis with results before exporting.");
          return;
        }
        runExport(action);
      });
    });

    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && dialog && !dialog.hidden) closeDialog();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
