"""PROTOTYPE, throwaway. Filter Score calls on the seed papers plus out-of-scope probes.

    ../card-read/.venv/bin/python score.py --dry-run     # rendered prompts + token counts only
    ../card-read/.venv/bin/python score.py --runs 2      # live: both variants, every paper, N runs

Writes out/<variant>.jsonl (one line per call) and prints a score table plus usage.
"""

import json
import sys
import time
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel, Field, create_model

from questions import load, render_questions, render_scope_notes

HERE = Path(__file__).parent
OUT = HERE / "out"
MODEL = "claude-haiku-5-5"
EFFORT = "low"
PRICES = {"input": 0.10, "output": 0.50, "cache_write": 0.125, "cache_read": 0.01}  # $/M tokens, prompts ≤100K
SEEDS = {"1904.12072", "2003.06413", "1606.02318", "1605.01735"}


class ScoreA(BaseModel):
    reason: str = Field(description="One line, at most 20 words.")
    score: float = Field(description="0 to 1.")


class ScoreB(BaseModel):
    reason: str = Field(description="One line, at most 20 words.")
    score: Literal[0, 1, 2, 3, 4]


def scores_model(name: str, item: type[BaseModel], ids: list[str]) -> type[BaseModel]:
    """One field per question id, so the schema follows questions.yaml instead of hard-coding Q1..Q4."""
    return create_model(name, **{qid: (item, ...) for qid in ids})


def load_prompt(name: str) -> tuple[dict, str]:
    text = (HERE / "prompts" / f"{name}.md").read_text()
    _, front, body = text.split("---\n", 2)
    meta = dict(line.split(": ", 1) for line in front.strip().splitlines())
    return meta, body.strip()


def render_system(version: str, q: dict) -> str:
    _, body = load_prompt(f"filter/{version}")
    text = body.replace("{{questions}}", render_questions(q)).replace("{{scope_notes}}", render_scope_notes(q))
    assert "{{" not in text
    return text


def render_paper(p: dict) -> str:
    return (
        f"<paper>\nTitle: {p['title']}\nCategories: {', '.join(p['categories'])}\n\n"
        f"Abstract: {p['abstract']}\n</paper>"
    )


def cost(u) -> float:
    return (
        u.input_tokens * PRICES["input"]
        + u.output_tokens * PRICES["output"]
        + (u.cache_creation_input_tokens or 0) * PRICES["cache_write"]
        + (u.cache_read_input_tokens or 0) * PRICES["cache_read"]
    ) / 1e6


def main() -> None:
    q = load(HERE / "questions.yaml")
    ids = [item["id"] for item in q["questions"]]
    papers = json.loads((HERE / "papers.json").read_text())
    runs = int(sys.argv[sys.argv.index("--runs") + 1]) if "--runs" in sys.argv else 1
    variants = {"v1a": scores_model("FilterScoresA", ScoreA, ids), "v1b": scores_model("FilterScoresB", ScoreB, ids)}
    client = anthropic.Anthropic()
    OUT.mkdir(exist_ok=True)

    for version, schema in variants.items():
        system = render_system(version, q)
        (OUT / f"{version}.system.txt").write_text(system)
        # The prefix that would be cached: system alone. The 1-token user turn is the count_tokens minimum.
        prefix = client.messages.count_tokens(
            model=MODEL, system=system, messages=[{"role": "user", "content": "x"}]
        ).input_tokens
        per_paper = [
            client.messages.count_tokens(
                model=MODEL, system=system, messages=[{"role": "user", "content": render_paper(p)}]
            ).input_tokens - prefix
            for p in papers[:3]
        ]
        print(f"{version}: system prefix ≈ {prefix} tokens (without schema); paper turn ≈ {per_paper} tokens")
        if "--dry-run" in sys.argv:
            continue

        with (OUT / f"{version}.jsonl").open("w") as f:
            for run in range(runs):
                for p in papers:
                    t0 = time.time()
                    msg = client.messages.parse(
                        model=MODEL,
                        max_tokens=4000,
                        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                        output_config={"effort": EFFORT},
                        messages=[{"role": "user", "content": render_paper(p)}],
                        output_format=schema,
                    )
                    u = msg.usage
                    rec = {
                        "run": run,
                        "arxiv_id": p["arxiv_id"],
                        "seed": p["arxiv_id"] in SEEDS,
                        "stop_reason": msg.stop_reason,
                        "scores": msg.parsed_output.model_dump() if msg.parsed_output else None,
                        "input_tokens": u.input_tokens,
                        "cache_creation_input_tokens": u.cache_creation_input_tokens,
                        "cache_read_input_tokens": u.cache_read_input_tokens,
                        "output_tokens": u.output_tokens,
                        "cost_usd": cost(u),
                        "seconds": round(time.time() - t0, 2),
                        "request_id": getattr(msg, "_request_id", None),
                    }
                    f.write(json.dumps(rec) + "\n")
                    s = rec["scores"] or {}
                    print(
                        f"{version} r{run} {p['arxiv_id']:>10} "
                        + " ".join(f"{qid}={s.get(qid, {}).get('score')}" for qid in ids)
                        + f"  in={u.input_tokens} cw={u.cache_creation_input_tokens} cr={u.cache_read_input_tokens}"
                        f" out={u.output_tokens} ${rec['cost_usd']:.5f}"
                    )


if __name__ == "__main__":
    main()
