// Shared behaviour for every page: KaTeX with the paper's preamble macros, `r` for raw LaTeX,
// `?` for the key list, the section pills' scroll-spy. Then /review: the clock, field focus,
// Flags and the verdict keys. A write that loads a new page (saving a Review) swaps `#page`,
// so everything tied to the page's content runs again after each swap.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

// A KaTeX error shows the raw source in red (throwOnError: false).
function renderMath() {
  renderMathInElement(document.body, {
    delimiters: [
      { left: "$$", right: "$$", display: true }, { left: "$", right: "$", display: false },
      { left: "\\(", right: "\\)", display: false }, { left: "\\[", right: "\\]", display: true },
    ],
    macros: JSON.parse($("#katex-macros")?.textContent || "{}"), throwOnError: false,
    ignoredClasses: ["raw"], ignoredTags: ["code", "script", "pre", "textarea", "input"],
  });
}

// The Reader's clock. The stored time is the server's, from render to submit.
let started = Date.now(), ticking = null;
function startClock() {
  started = Date.now();
  clearInterval(ticking);
  const el = $("#timer");
  if (!el) return;
  ticking = setInterval(() => {
    const s = Math.round((Date.now() - started) / 1000);
    el.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    el.classList.toggle("warn", s >= 240 && s < 300);
    el.classList.toggle("over", s >= 300);
  }, 1000);
}

function pageLoaded() {
  renderMath();
  startClock();
  spy();
  focusField(fields()[0]);
}
window.addEventListener("load", pageLoaded);
document.body.addEventListener("htmx:afterSwap", (e) => {
  if (e.detail.target.id === "page") pageLoaded();
});

// Highlight the section pill of the section at the top of the screen.
const sections = () => $$("section[id^=sec-]");
function currentSection() {
  const top = ($(".stick")?.offsetHeight ?? 0) + 12;
  let current = 0;
  sections().forEach((s, i) => { if (s.getBoundingClientRect().top <= top) current = i; });
  return current;
}
function spy() {
  const current = currentSection();
  $$(".secnav a").forEach((a, i) => a.classList.toggle("on", i === current));
}
document.addEventListener("scroll", spy, { passive: true });
function jumpSection(d) {
  const all = sections(), s = all[Math.max(0, Math.min(all.length - 1, currentSection() + d))];
  if (!s) return;
  s.scrollIntoView({ block: "start" });
  focusField($("[data-field]", s), false);
}

// The focused field, moved with j / k and by clicking.
const fields = () => $$("[data-field]");
let current = null;
function focusField(el, scroll = true) {
  if (!el) return;
  $$("[data-field].focus").forEach((f) => f.classList.remove("focus"));
  el.classList.add("focus");
  current = el;
  if (scroll) el.scrollIntoView({ block: "nearest" });
}
function moveField(d) {
  const all = fields(), i = all.indexOf(current);
  focusField(all[Math.max(0, Math.min(all.length - 1, i + d))] || all[0]);
}

// Flags: ⚑ or f opens the field's form; 1–4 pick the kind while the note is empty; Enter
// saves, Esc cancels.
function openFlag(field) {
  const form = field && $(".flagform", field);
  if (!form) return;
  form.hidden = false;
  $("input[name=note]", form).focus();
}

const toggleRaw = () => document.body.classList.toggle("rawmode");
const toggleKeys = (show) => { const k = $("#keys"); if (k) k.hidden = show === undefined ? !k.hidden : !show; };

document.addEventListener("click", (e) => {
  if (e.target.closest(".rawbtn")) toggleRaw();
  if (e.target.closest(".keysbtn")) toggleKeys();
  const field = e.target.closest("[data-field]");
  if (field) focusField(field, false);
  if (e.target.closest(".flagbtn")) openFlag(field);
});

document.addEventListener("keydown", (e) => {
  const a = document.activeElement;
  const form = a?.closest(".flagform");
  if (form || a && (a.tagName === "INPUT" && a.type === "text" || a.tagName === "TEXTAREA")) {
    const note = form && $("input[name=note]", form);
    if (form && note.value === "" && /^[1-4]$/.test(e.key)) {
      $$("input[name=kind]", form)[+e.key - 1].checked = true;
      e.preventDefault();
    } else if (e.key === "Escape") {
      if (form) { form.hidden = true; form.reset(); }
      a.blur();
    }
    return;
  }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const verdict = $("#verdict");
  const relevance = (v) => () => { if (verdict) verdict.relevance.value = v; };
  const act = {
    r: toggleRaw, "?": () => toggleKeys(), Escape: () => toggleKeys(false),
    "[": () => jumpSection(-1), "]": () => jumpSection(1),
    j: () => moveField(1), k: () => moveField(-1),
    o: () => { const d = current && $("details.ev", current); if (d) d.open = !d.open; },
    f: () => openFlag(current),
    y: relevance("yes"), p: relevance("partly"), n: relevance("no"),
    d: () => { if (verdict) verdict.deep_read.checked = !verdict.deep_read.checked; },
    s: () => verdict?.requestSubmit(),
  }[e.key];
  if (act) { e.preventDefault(); act(); }
});
