"""PROTOTYPE, throwaway. A rough pass of the decided Verify rules (SPEC §7.4) over
out/draft.json, so the Card can be judged as the Reader will see it. Number
tolerance and failure statuses are the Verify ticket's job; this is naive.

    .venv/bin/python verify.py src_1904.12072/flattened.txt
Writes out/card.json and out/card.md.
"""

import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).parent / "out"


def canonicalise(text: str) -> str:
    text = re.sub(r"~?\\(cite[pt]?|ref|eqref|label)\{[^}]*\}", "", text)
    text = re.sub(r"\\([%&$])", r"\1", text)
    for _ in range(3):
        text = re.sub(r"\\(emph|textit|textbf|text)\{([^{}]*)\}", r"\2", text)
    text = re.sub(r"``|''|[“”]", '"', text)
    text = re.sub(r"[‘’]", "'", text)
    text = re.sub(r"---|--|[–—]", "-", text)
    text = re.sub(r"~|\\,|\\ |\\;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


HEADING = re.compile(r"\\(section|subsection|subsubsection|paragraph)\*?\{((?:[^{}]|\{[^{}]*\})*)\}")
ENV = re.compile(r"\\begin\{(equation|align|figure|table)\*?\}(.*?)\\end\{\1\*?\}", re.S)


def locate(source: str, quote: str) -> tuple[int, str | None]:
    """Count matches in canonical space; derive loc from the first match by
    mapping back to the raw text through a per-heading scan (rough)."""
    cq, cs = canonicalise(quote), canonicalise(source)
    n = cs.count(cq) if cq else 0
    if not n:
        return 0, None
    # find raw position: canonicalise growing prefixes is too slow; use a
    # word-anchored search for the first 4 words of the quote instead.
    words = cq.split()[:4]
    pat = r"\s+".join(re.escape(w) for w in words)
    m = re.search(pat, source) or re.search(re.escape(words[0]), source)
    pos = m.start() if m else 0
    heads = [h for h in HEADING.finditer(source) if h.start() < pos]
    loc = f'Sec. "{heads[-1].group(2)}"' if heads else "front matter"
    for env in ENV.finditer(source):
        if env.start() < pos < env.end():
            lab = re.search(r"\\label\{([^}]*)\}", env.group(2))
            if lab:
                loc += f" · {lab.group(1)}"
    return n, loc


NUM = re.compile(r"\d+(?:\.\d+)?")


def check_fact(fact: dict, source: str) -> dict:
    ev = []
    for q in fact["evidence"]:
        n, loc = locate(source, q["quote"])
        words = len(canonicalise(q["quote"]).split())
        shape_ok = 5 <= words <= 60 and "..." not in q["quote"] and "…" not in q["quote"]
        ev.append({**q, "found": n > 0 and shape_ok, "loc": loc, "match_count": n, "words": words})
    found = any(e["found"] for e in ev)
    support = "unsupported" if not found else ("inferred" if fact.get("inferred") else "supported")
    return {**fact, "evidence": ev, "support": support}


def main() -> None:
    source = Path(sys.argv[1]).read_text()
    draft = json.loads((OUT / "draft.json").read_text())
    card = dict(draft)
    for k in ("system", "method", "baselines", "claimed_advance", "code_data"):
        if card[k]:
            card[k] = check_fact(card[k], source)
    for k in ("key_results", "assumptions", "limitations_stated"):
        card[k] = [check_fact(f, source) for f in card[k]]

    canon = canonicalise(source)
    invented = [
        (r["value"], x) for r in card["key_results"] for x in NUM.findall(r["value"]) if x not in canon
    ]
    labels = set(re.findall(r"\\label\{([^}]*)\}", source))
    bad_labels = [e["label"] for e in card["key_equations"] + card["key_figures"] if e["label"] and e["label"] not in labels]
    facts = [card[k] for k in ("system", "method", "baselines", "claimed_advance", "code_data") if card[k]]
    facts += card["key_results"] + card["assumptions"] + card["limitations_stated"]
    card["_verify"] = {
        "unsupported_count": sum(f["support"] == "unsupported" for f in facts),
        "inferred_count": sum(f["support"] == "inferred" for f in facts),
        "fact_count": len(facts),
        "invented_numbers": invented,
        "unknown_labels": bad_labels,
    }
    (OUT / "card.json").write_text(json.dumps(card, indent=2, ensure_ascii=False))
    (OUT / "card.md").write_text(render(card))
    print(json.dumps(card["_verify"], indent=2))


BADGE = {"supported": "✅", "inferred": "🟡 inferred", "unsupported": "🟥 UNSUPPORTED"}


def render_fact(name: str, f: dict) -> str:
    lines = [f"**{name}** {BADGE[f['support']]}: {f['value']}"]
    for e in f["evidence"]:
        mark = "found" if e["found"] else "NOT FOUND"
        extra = f", also {e['match_count'] - 1}× elsewhere" if e["match_count"] > 1 else ""
        lines.append(f"  > {e['quote']}\n  > — *{e['loc'] or '?'}* ({mark}, {e['words']} words{extra})")
    return "\n".join(lines)


def render(c: dict) -> str:
    v = c["_verify"]
    s = [f"# Card (prototype)\n\n{v['fact_count']} facts · {v['unsupported_count']} unsupported · "
         f"{v['inferred_count']} inferred · invented numbers: {v['invented_numbers'] or 'none'} · "
         f"unknown labels: {v['unknown_labels'] or 'none'}\n", f"**tl;dr** {c['tldr']}\n", "## Key results"]
    s += [render_fact(f"R{i + 1}", r) for i, r in enumerate(c["key_results"])]
    s += ["## Assumptions"] + [render_fact(f"A{i + 1}", a) for i, a in enumerate(c["assumptions"])]
    s += ["## The paper"]
    for k in ("system", "method", "baselines", "claimed_advance", "code_data"):
        s.append(render_fact(k, c[k]) if c[k] else f"**{k}**: none")
    s += ["## Limitations (stated)"] + [render_fact(f"L{i + 1}", {**l, "inferred": False}) for i, l in enumerate(c["limitations_stated"])]
    s += ["## Key equations"] + [f"- `{e['label']}`: {e['meaning']}\n  `{e['latex']}`" for e in c["key_equations"]]
    s += ["## Key figures"] + [f"- `{f['label']}`: {f['why']}" for f in c["key_figures"]]
    s += ["## Research questions"] + [f"- {q['id']}: {q['why']}" for q in c["questions"]]
    o = c["opinion"]
    s += ["## Agent's opinion"] + [f"- flagged: {l['value']}" for l in o["limitations_flagged"]]
    s.append(f"- deep read: {'yes' if o['deep_read']['recommend'] else 'no'}: {o['deep_read']['why']}")
    return "\n\n".join(s) + "\n"


if __name__ == "__main__":
    main()
