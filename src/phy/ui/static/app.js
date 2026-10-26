// Shared behaviour for every page: KaTeX with the paper's preamble macros, `r` for raw LaTeX,
// and the section pills' scroll-spy.
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

// A KaTeX error shows the raw source in red (throwOnError: false).
window.addEventListener("load", () => {
  renderMathInElement(document.body, {
    delimiters: [
      { left: "$$", right: "$$", display: true }, { left: "$", right: "$", display: false },
      { left: "\\(", right: "\\)", display: false }, { left: "\\[", right: "\\]", display: true },
    ],
    macros: window.KATEX_MACROS, throwOnError: false,
    ignoredClasses: ["raw"], ignoredTags: ["code", "script", "pre", "textarea", "input"],
  });
});

const toggleRaw = () => document.body.classList.toggle("rawmode");
document.addEventListener("click", (e) => { if (e.target.closest(".rawbtn")) toggleRaw(); });
document.addEventListener("keydown", (e) => {
  const a = document.activeElement;
  if (a && (a.tagName === "INPUT" || a.tagName === "TEXTAREA")) return;
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "r") { e.preventDefault(); toggleRaw(); }
});

// Highlight the section pill of the section at the top of the screen.
const spy = () => {
  const top = (document.querySelector(".stick")?.offsetHeight ?? 0) + 12;
  let current = 0;
  $$("section[id^=sec-]").forEach((s, i) => { if (s.getBoundingClientRect().top <= top) current = i; });
  $$(".secnav a").forEach((a, i) => a.classList.toggle("on", i === current));
};
document.addEventListener("scroll", spy, { passive: true });
window.addEventListener("load", spy);
