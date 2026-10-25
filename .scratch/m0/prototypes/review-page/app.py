"""PROTOTYPE, throwaway. Review page design for ticket 05.

Three structurally different variants of `/review`, switchable via `?variant=A|B|C`
and the floating bar (or ← / →):
  A  Document     one column, quotes collapsed under each value, sticky verdict bar
  B  Split pane   compact field list on the left, the focused field's evidence on the right
  C  Triage deck  one section per step, every field marked ok or flagged, verdict last

Built from the real Card (../card-read/out/card.json, 1904.12072). That Card is clean,
so DEMO overlays fake the states it lacks (unsupported, number badges, match_count > 1,
Stale, an EPS figure). `?demo=0` shows the Card as Read produced it.

Flags and Reviews live in memory. Nothing persists.

Run:  .venv/bin/python app.py   →  http://127.0.0.1:8000/review
"""

import copy
import html
import io
import json
import re
from pathlib import Path

import pypdfium2 as pdfium
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

HERE = Path(__file__).parent
CARD_PATH = HERE.parent / "card-read/out/card.json"
SRC_DIR = HERE.parent / "card-read/src_1904.12072"
TEX = (SRC_DIR / "main.tex").read_text()

FLAG_KINDS = {
    "wrong_value": "Wrong value",
    "quote_doesnt_support": "Quote doesn't support it",
    "missing": "Something missing",
    "should_be_opinion": "Should be opinion",
}

# --- in-memory state ----------------------------------------------------------

STATE = {"flags": [], "reviews": []}


# --- LaTeX: preamble macros for KaTeX, server-side text cleanup ---------------

def preamble_macros(tex: str) -> dict[str, str]:
    """\\newcommand{\\name}[n]{body} → KaTeX macros {"\\name": "body"}. KaTeX reads #1.. itself."""
    macros = {}
    for m in re.finditer(r"\\newcommand\{(\\[A-Za-z]+)\}(?:\[\d\])?\{", tex):
        i, depth = m.end(), 1
        while depth:
            depth += {"{": 1, "}": -1}.get(tex[i], 0)
            i += 1
        macros[m.group(1)] = tex[m.end() : i - 1]
    return macros


MACROS = preamble_macros(TEX)

MATH = re.compile(r"(\$\$.+?\$\$|\$.+?\$|\\\(.+?\\\)|\\\[.+?\\\])", re.S)


def clean_text(s: str) -> str:
    """Display-only cleanup of text-mode markup. Math is left for KaTeX. Unknown commands stay raw."""
    s = html.escape(s, quote=False)
    s = re.sub(r"\{\\(?:it|em)\s+([^{}]*)\}", r"<i>\1</i>", s)
    s = re.sub(r"\{\\bf\s+([^{}]*)\}", r"<b>\1</b>", s)
    s = re.sub(r"\\(?:textit|emph)\{([^{}]*)\}", r"<i>\1</i>", s)
    s = re.sub(r"\\textbf\{([^{}]*)\}", r"<b>\1</b>", s)
    s = re.sub(r"\\(?:eq)?ref\{([^{}]*)\}", r'<span class="ref">\1</span>', s)
    s = re.sub(r"\\cite[pt]?\{([^{}]*)\}", r'<span class="ref">cite</span>', s)
    s = s.replace("~", " ").replace("\\%", "%").replace("---", "—").replace("--", "–")
    s = s.replace("``", "“").replace("''", "”")
    return s


def tex_html(s: str) -> str:
    parts = MATH.split(s)
    return "".join(html.escape(p, quote=False) if i % 2 else clean_text(p) for i, p in enumerate(parts))


# --- figures: label → files from the tarball ----------------------------------

def figure_index(tex: str) -> dict[str, dict]:
    out = {}
    for env in re.finditer(r"\\begin\{figure\*?\}(.+?)\\end\{figure\*?\}", tex, re.S):
        body = env.group(1)
        label = re.search(r"\\label\{([^}]+)\}", body)
        if not label:
            continue
        files = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", body)
        cap = re.search(r"\\caption\{(.+)", body, re.S)
        out[label.group(1)] = {"files": files, "caption": cap.group(1)[:400] if cap else ""}
    return out


FIGURES = figure_index(TEX)
PNG_CACHE: dict[str, bytes] = {}


def resolve(name: str) -> Path | None:
    for ext in ("", ".pdf", ".png", ".jpg", ".eps"):
        p = SRC_DIR / f"{name}{ext}"
        if p.exists():
            return p
    return None


def figure_png(name: str) -> bytes | None:
    if name in PNG_CACHE:
        return PNG_CACHE[name]
    p = resolve(name)
    if p is None or p.suffix == ".eps":
        return None
    if p.suffix in (".png", ".jpg"):
        data = p.read_bytes()
    else:
        page = pdfium.PdfDocument(str(p))[0]
        img = page.render(scale=1100 / page.get_width()).to_pil()
        buf = io.BytesIO()
        img.save(buf, "PNG")
        data = buf.getvalue()
    PNG_CACHE[name] = data
    return data


# --- the Card, plus DEMO overlays ---------------------------------------------

def load_card(demo: bool) -> tuple[dict, dict]:
    card = json.loads(CARD_PATH.read_text())
    meta = {
        "arxiv_id": "1904.12072",
        "version": "v2",
        "authors": "Albergo, Kanwar, Shanahan",  # from OAI-PMH metadata in the real app
        "title": "Flow-based generative models for Markov chain Monte Carlo in lattice field theory",
        "status": "verified",
        "stale_note": None,
        "fig_overrides": {},
        "number_flags": {},  # path -> [(number, "quote"|"paper")]
    }
    if not demo:
        return card, meta
    card = copy.deepcopy(card)
    # unsupported: a quote Verify could not find
    q = card["limitations_stated"][2]["evidence"][0]
    q.update(found=False, loc=None, match_count=0)
    card["limitations_stated"][2]["support"] = "unsupported"
    # a quote that appears 3× in the source
    card["key_results"][3]["evidence"][0]["match_count"] = 3
    # number badges: per-field (not in its quotes) and whole-paper (invented)
    meta["number_flags"] = {
        "system": [("6.975", "quote"), ("5.113", "quote"), ("4", "quote")],
        "baselines": [("70%", "quote")],
        "key_results[4]": [("2", "paper")],
    }
    meta["status"] = "stale"
    meta["stale_note"] = "v3 arrived 2026-10-21; this Card is from v2"
    meta["fig_overrides"] = {"coupling_layer.pdf": "coupling_layer.eps"}
    return card, meta


def quote_view(ev: dict) -> dict:
    return {
        "raw": ev["quote"],
        "html": tex_html(ev["quote"]),
        "found": ev.get("found", True),
        "loc": ev.get("loc"),
        "also": max(ev.get("match_count", 1) - 1, 0),
    }


def build_fields(card: dict, meta: dict) -> list[dict]:
    """Every reviewable field in display order. One dict per Flag target."""
    nf = meta["number_flags"]
    fields = []

    def fact(path, label, section, f, support_default=None):
        if f is None:
            fields.append({"path": path, "label": label, "section": section, "kind": "none",
                           "value_html": "<em>none</em>", "support": None, "evidence": [], "numbers": []})
            return
        fields.append({
            "path": path, "label": label, "section": section, "kind": "fact",
            "value_html": tex_html(f["value"]),
            "support": f.get("support", support_default),
            "evidence": [quote_view(e) for e in f["evidence"]],
            "numbers": nf.get(path, []),
        })

    fields.append({"path": "tldr", "label": "tl;dr", "section": "Summary", "kind": "text",
                   "value_html": tex_html(card["tldr"]), "support": None, "evidence": [], "numbers": []})
    for i, f in enumerate(card["key_results"]):
        fact(f"key_results[{i}]", f"Result {i + 1}", "Summary", f)
    for i, f in enumerate(card["assumptions"]):
        fact(f"assumptions[{i}]", f"Assumption {i + 1}", "Summary", f)
    for k, label in [("system", "System"), ("method", "Method"), ("baselines", "Baselines"),
                     ("claimed_advance", "Claimed advance"), ("code_data", "Code / data")]:
        fact(k, label, "Setup", card[k])
    for i, f in enumerate(card["limitations_stated"]):
        fact(f"limitations_stated[{i}]", f"Stated limitation {i + 1}", "Limitations", f)
    for i, e in enumerate(card["key_equations"]):
        fields.append({
            "path": f"key_equations[{i}]", "label": f"Equation {e['label'] or i + 1}", "section": "Equations & figures",
            "kind": "equation", "latex": e["latex"], "value_html": tex_html(e["meaning"]),
            "support": None, "evidence": [], "numbers": [],
        })
    for i, kf in enumerate(card["key_figures"]):
        fig = FIGURES.get(kf["label"], {"files": [], "caption": ""})
        files = [meta["fig_overrides"].get(n, n) for n in fig["files"]]
        fields.append({
            "path": f"key_figures[{i}]", "label": f"Figure {kf['label']}", "section": "Equations & figures",
            "kind": "figure", "value_html": tex_html(kf["why"]), "caption_html": tex_html(fig["caption"]),
            "files": [{"name": n, "renderable": not n.endswith(".eps") and resolve(n) is not None} for n in files],
            "support": None, "evidence": [], "numbers": [],
        })
    qs = ", ".join(f"<b>{q['id']}</b>: {html.escape(q['why'])}" for q in card["questions"]) or "<em>none</em>"
    fields.append({"path": "questions", "label": "Research questions", "section": "Equations & figures",
                   "kind": "text", "value_html": qs, "support": None, "evidence": [], "numbers": []})
    op = card["opinion"]
    for i, lf in enumerate(op["limitations_flagged"]):
        fields.append({"path": f"opinion.limitations_flagged[{i}]", "label": f"Flagged limitation {i + 1}",
                       "section": "Agent's opinion", "kind": "opinion", "value_html": tex_html(lf["value"]),
                       "support": None, "evidence": [], "numbers": []})
    dr = op["deep_read"]
    fields.append({"path": "opinion.deep_read", "label": "Deep read?", "section": "Agent's opinion",
                   "kind": "opinion",
                   "value_html": f"<b>{'Recommend' if dr['recommend'] else 'Skip'}</b> — {tex_html(dr['why'])}",
                   "support": None, "evidence": [], "numbers": []})
    return fields


def sections(fields):
    out = {}
    for f in fields:
        out.setdefault(f["section"], []).append(f)
    return list(out.items())


# --- app ----------------------------------------------------------------------

app = FastAPI()
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
T = Jinja2Templates(directory=HERE / "templates")
VARIANTS = {"A": "Document", "B": "Split pane", "C": "Triage deck"}


def state_json():
    return json.dumps(STATE, indent=1)


@app.get("/review", response_class=HTMLResponse)
def review(request: Request, variant: str = "A", demo: int = 1):
    variant = variant if variant in VARIANTS else "A"
    card, meta = load_card(bool(demo))
    fields = build_fields(card, meta)
    counts = {s: sum(f["support"] == s for f in fields) for s in ("supported", "inferred", "unsupported")}
    return T.TemplateResponse(request, f"variant_{variant.lower()}.html", {
        "card": card, "meta": meta, "fields": fields, "sections": sections(fields), "counts": counts,
        "n_numbers": sum(len(v) for v in meta["number_flags"].values()),
        "flag_kinds": FLAG_KINDS, "macros": json.dumps(MACROS), "variant": variant,
        "variants": VARIANTS, "demo": demo, "flags_by_path": flags_by_path(), "state": state_json(),
    })


def flags_by_path():
    out = {}
    for f in STATE["flags"]:
        out.setdefault(f["field_path"], []).append(f)
    return out


@app.post("/flags", response_class=HTMLResponse)
def add_flag(request: Request, field_path: str = Form(), kind: str = Form(), note: str = Form("")):
    STATE["flags"].append({"card_id": 1, "field_path": field_path, "kind": kind, "note": note})
    return T.TemplateResponse(request, "_flag_chips.html", {
        "path": field_path, "flags": flags_by_path().get(field_path, []), "flag_kinds": FLAG_KINDS,
        "state": state_json(), "oob": True,
    })


@app.post("/flags/clear", response_class=HTMLResponse)
def clear_flags(request: Request, field_path: str = Form()):
    STATE["flags"] = [f for f in STATE["flags"] if f["field_path"] != field_path]
    return T.TemplateResponse(request, "_flag_chips.html", {
        "path": field_path, "flags": [], "flag_kinds": FLAG_KINDS, "state": state_json(), "oob": True,
    })


@app.post("/reviews", response_class=HTMLResponse)
def add_review(request: Request, relevance: str = Form(), deep_read: str = Form("no"),
               seconds_spent: int = Form(0), note: str = Form("")):
    STATE["reviews"].append({"card_id": 1, "relevance": relevance, "deep_read": deep_read == "yes",
                             "seconds_spent": seconds_spent, "note": note})
    return T.TemplateResponse(request, "_saved.html", {"r": STATE["reviews"][-1], "state": state_json()})


@app.post("/reset", response_class=HTMLResponse)
def reset():
    STATE["flags"].clear()
    STATE["reviews"].clear()
    return HTMLResponse("", headers={"HX-Refresh": "true"})


@app.get("/figure/{name}")
def figure(name: str):
    data = figure_png(name)
    return Response(data, media_type="image/png") if data else Response(status_code=404)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
