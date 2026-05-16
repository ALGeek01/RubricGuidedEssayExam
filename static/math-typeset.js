/**
 * KaTeX auto-render: \\( … \\), \\[ … \\], and Markdown-style $ … $ / $$ … $$.
 */
(function () {
  function katexOpts() {
    return {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "\\[", right: "\\]", display: true },
        { left: "\\(", right: "\\)", display: false },
        { left: "$", right: "$", display: false },
      ],
      throwOnError: false,
      strict: "ignore",
      ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code", "option"],
      // Do not walk into subtrees KaTeX already emitted (supports safe re-typeset after window load).
      ignoredClasses: ["katex", "katex-display", "katex-html", "katex-mathml"],
    };
  }

  function render(root) {
    if (!root || typeof renderMathInElement !== "function") return;
    try {
      renderMathInElement(root, katexOpts());
    } catch (e) {}
  }

  window.rgeeTypesetMathRoot = render;

  function typesetExamMathRoots() {
    document.querySelectorAll(".rgee-render-math").forEach(render);
  }

  document.addEventListener("DOMContentLoaded", typesetExamMathRoots);
  window.addEventListener("load", typesetExamMathRoots);
})();
