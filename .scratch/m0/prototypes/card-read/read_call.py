"""PROTOTYPE, throwaway. One real Read call on a flattened paper.

    .venv/bin/python read_call.py src_1904.12072/flattened.txt            # live call
    .venv/bin/python read_call.py src_1904.12072/flattened.txt --dry-run  # request + token count only

Writes out/request.json, out/response.json, out/draft.json and out/usage.json.
"""

import json
import sys
import time
from pathlib import Path

import anthropic

from card import SCHEMA_VERSION, CardDraft

HERE = Path(__file__).parent
OUT = HERE / "out"
MODEL = "claude-sonnet-5-5"
EFFORT = "medium"
PRICES = {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.20}  # $/M tokens

# Stand-in for questions.yaml (SPEC §4); its rendering into the prompt is part of the proposal.
QUESTIONS = """\
- Q1. Generative sampling for lattice field theory: flows and diffusion versus critical slowing down and topological freezing; scaling with volume and with gauge symmetry.
- Q2. Neural quantum states: architectures that reach state-of-the-art ground-state energies or dynamics, compared with DMRG, tensor networks and QMC.
- Q3. Symmetry and physics constraints in architectures: gauge equivariance and conservation laws, and what each buys in accuracy or sample efficiency.
- Q4. ML for observables and phases: phase detection, and inverse problems such as spectral reconstruction."""


def load_prompt(name: str) -> tuple[dict, str]:
    """A prompt file is YAML-ish front matter between --- lines, then the body.
    Placeholders are {{name}}: $-templating collides with LaTeX in the text."""
    text = (HERE / "prompts" / f"{name}.md").read_text()
    _, front, body = text.split("---\n", 2)
    meta = dict(line.split(": ", 1) for line in front.strip().splitlines())
    return meta, body.strip()


def build_request(paper: str) -> dict:
    read_meta, read_body = load_prompt("read/v1")
    _, system = load_prompt(read_meta["system"])
    instructions = read_body.replace("{{questions}}", QUESTIONS)
    assert "{{" not in instructions
    return dict(
        model=MODEL,
        max_tokens=32000,
        system=system,
        output_config={"effort": EFFORT},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"<paper>\n{paper}\n</paper>", "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": instructions},
                ],
            }
        ],
    )


def cost(u) -> float:
    return (
        u.input_tokens * PRICES["input"]
        + u.output_tokens * PRICES["output"]
        + (u.cache_creation_input_tokens or 0) * PRICES["cache_write"]
        + (u.cache_read_input_tokens or 0) * PRICES["cache_read"]
    ) / 1e6


def main() -> None:
    paper = Path(sys.argv[1]).read_text()
    OUT.mkdir(exist_ok=True)
    req = build_request(paper)
    (OUT / "request.json").write_text(json.dumps(req, indent=2))

    client = anthropic.Anthropic()
    counted = client.messages.count_tokens(
        model=req["model"], system=req["system"], messages=req["messages"]
    ).input_tokens
    print(f"input tokens (counted, without schema): {counted}")
    if "--dry-run" in sys.argv:
        return

    t0 = time.time()
    with client.beta.messages.stream(
        **req,
        output_format=CardDraft,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        msg = stream.get_final_message()
    elapsed = time.time() - t0

    (OUT / "response.json").write_text(msg.to_json())
    print(f"stop_reason={msg.stop_reason} model={msg.model} request_id={getattr(msg, "_request_id", None)}")
    if msg.stop_reason != "end_turn":
        sys.exit(f"not a complete Card: stop_reason={msg.stop_reason}")

    draft: CardDraft = msg.parsed_output
    (OUT / "draft.json").write_text(draft.model_dump_json(indent=2))
    u = msg.usage
    usage = {
        "model": msg.model,
        "schema_version": SCHEMA_VERSION,
        "prompt_version": "read/v1",
        "counted_input_tokens": counted,
        "input_tokens": u.input_tokens,
        "cache_creation_input_tokens": u.cache_creation_input_tokens,
        "cache_read_input_tokens": u.cache_read_input_tokens,
        "output_tokens": u.output_tokens,
        "cost_usd": round(cost(u), 4),
        "seconds": round(elapsed, 1),
        "request_id": getattr(msg, "_request_id", None),
    }
    (OUT / "usage.json").write_text(json.dumps(usage, indent=2))
    print(json.dumps(usage, indent=2))


if __name__ == "__main__":
    main()
