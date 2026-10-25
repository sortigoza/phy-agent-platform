// PROTOTYPE. Shared behaviour for all variants: KaTeX, timer, keyboard, Flag marks.
const V = document.body.dataset.variant;
const VS = document.body.dataset.variants.split(",");
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

// --- KaTeX with the paper's preamble macros; errors fall back to red raw source
function renderMath(el) {
  renderMathInElement(el, {
    delimiters: [
      { left: "$$", right: "$$", display: true }, { left: "$", right: "$", display: false },
      { left: "\\(", right: "\\)", display: false }, { left: "\\[", right: "\\]", display: true },
    ],
    macros: window.KATEX_MACROS, throwOnError: false,
    ignoredClasses: ["raw"], ignoredTags: ["code", "script", "pre", "textarea", "input"],
  });
}
window.addEventListener("load", () => renderMath(document.body));

// --- timer
const t0 = Date.now();
const secs = () => Math.round((Date.now() - t0) / 1000);
setInterval(() => {
  const s = secs(), el = $("#timer");
  el.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  el.classList.toggle("warn", s >= 240 && s < 300);
  el.classList.toggle("over", s >= 300);
}, 1000);
document.body.addEventListener("htmx:configRequest", (e) => {
  if (e.detail.elt.id === "verdict") e.detail.parameters.seconds_spent = secs();
});

// --- fields and focus
const fields = () => $$("[data-field]").filter((e) => e.offsetParent !== null);
let cur = null;
function focusField(el) {
  if (!el) return;
  $$("[data-field].focus").forEach((e) => e.classList.remove("focus"));
  el.classList.add("focus");
  cur = el;
  el.scrollIntoView({ block: "nearest" });
  if (V === "B") {
    $$(".dpane").forEach((d) => (d.hidden = true));
    $("#" + el.dataset.detail).hidden = false;
  }
}
function move(d) {
  const fs = fields(), i = fs.indexOf(cur);
  focusField(fs[Math.max(0, Math.min(fs.length - 1, i + d))] || fs[0]);
}
document.addEventListener("click", (e) => {
  const f = e.target.closest("[data-field]");
  if (f) focusField(f);
  if (e.target.closest(".flagbtn")) openFlag(f);
  if (e.target.closest(".okbtn")) markOk(f);
  const g = e.target.closest("[data-goto]");
  if (g) goto(+g.dataset.goto);
  const c = e.target.closest("[data-cycle]");
  if (c) cycle(+c.dataset.cycle);
});

// --- Flags
function flagForm(f) {
  return V === "B" ? $("#" + f.dataset.detail + " .flagform") : $(".flagform", f);
}
function openFlag(f) {
  if (!f) return;
  const form = flagForm(f);
  form.hidden = false;
  $("input[name=note]", form).focus();
}
let lastFlagged = null;
document.body.addEventListener("htmx:afterRequest", (e) => {
  if (e.detail.elt.classList?.contains("flagform")) lastFlagged = e.detail.elt.closest("[data-field]") || cur;
});
document.body.addEventListener("htmx:afterSettle", () => {
  $$("[data-field]").forEach((f) => {
    const flagged = !!$("#chips-" + f.id + " .chip");
    f.classList.toggle("flagged", flagged);
    const dot = $(".flagdot", f);
    if (dot) dot.hidden = !flagged;
  });
  if (lastFlagged) {
    focusField(lastFlagged);
    if (V === "C") advanceFrom(lastFlagged);
    lastFlagged = null;
  }
  updateProgress();
});

// --- C: steps
function goto(i) {
  const steps = $$(".step");
  if (!steps.length) return;
  i = Math.max(0, Math.min(steps.length - 1, i));
  steps.forEach((s, j) => (s.hidden = j !== i));
  $$(".stepper li").forEach((l, j) => l.classList.toggle("on", j === i));
  window.scrollTo(0, 0);
  focusField(fields()[0]);
}
function markOk(f) {
  if (!f) return;
  f.classList.add("ok");
  updateProgress();
  advanceFrom(f);
}
function advanceFrom(f) {
  const step = f.closest(".step");
  const rest = $$("[data-field]", step).filter((e) => !e.classList.contains("ok") && !e.classList.contains("flagged"));
  if (rest.length) focusField(rest[0]);
  else setTimeout(() => goto(+step.dataset.step + 1), 250);
}
function updateProgress() {
  $$(".step[data-step]").forEach((s) => {
    const fs = $$("[data-field]", s), p = $(`[data-prog="${s.dataset.step}"]`);
    if (!p || !fs.length) return;
    const done = fs.filter((e) => e.classList.contains("ok") || e.classList.contains("flagged")).length;
    p.textContent = `${done}/${fs.length}`;
    p.closest("li").classList.toggle("done", done === fs.length);
  });
}
const curStep = () => +($(".step:not([hidden])")?.dataset.step ?? 0);

// --- variants (PROTOTYPE switcher)
function cycle(d) {
  const i = (VS.indexOf(V) + d + VS.length) % VS.length;
  const u = new URL(location);
  u.searchParams.set("variant", VS[i]);
  location = u;
}

// --- keyboard
document.addEventListener("keydown", (e) => {
  const a = document.activeElement;
  const typing = a && (a.tagName === "TEXTAREA" || (a.tagName === "INPUT" && a.type === "text"));
  if (typing) {
    const form = a.closest(".flagform");
    if (form && a.value === "" && "1234".includes(e.key) && e.key.length === 1) {
      $$("input[name=kind]", form)[+e.key - 1].checked = true;
      e.preventDefault();
    } else if (e.key === "Escape") {
      if (form && V !== "B") form.hidden = true;
      a.blur();
    }
    return;
  }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const verdict = $("#verdict");
  const act = {
    j: () => move(1), k: () => move(-1),
    o: () => { const d = cur && $("details.ev", cur); if (d) d.open = !d.open; },
    f: () => openFlag(cur), x: () => V === "C" && markOk(cur),
    y: () => (verdict.relevance.value = "yes"), p: () => (verdict.relevance.value = "partly"),
    n: () => (verdict.relevance.value = "no"),
    d: () => (verdict.deep_read.checked = !verdict.deep_read.checked),
    s: () => {
      if (V === "C" && verdict.offsetParent === null) return goto($$(".step").length - 1);
      verdict.requestSubmit();
    },
    r: () => document.body.classList.toggle("rawmode"),
    "`": () => $("#statepanel").classList.toggle("min"),
    "?": () => ($("#help").hidden = !$("#help").hidden),
    Escape: () => ($("#help").hidden = true),
    ArrowLeft: () => cycle(-1), ArrowRight: () => cycle(1),
    "]": () => V === "C" && goto(curStep() + 1), "[": () => V === "C" && goto(curStep() - 1),
  }[e.key];
  if (act) { e.preventDefault(); act(); }
});

window.addEventListener("load", () => { if (V === "C") goto(0); else focusField(fields()[0]); });
