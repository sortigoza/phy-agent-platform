# Pipeline Stages are single Messages API calls; the Agent SDK is reserved for Meta-work

Filter, Read and Verify each give the model one Paper version's text and need one structured answer back. They need no tools, no exploration and no loop. So each is a single Messages API call with a JSON-schema output (`output_config.format`) and prompt caching, not an Agent SDK agent. That keeps runs deterministic in shape, cheap to replay against the Golden set, and eligible for the Batch API (50% off), which the Agent SDK cannot use. It also means a run is fully described by one request and one response, which is what lets plain JSONL run logs replace Langfuse.

The "agentic" part of the platform is Meta-work: an Improver agent (M2) that reads Flags, Instruments and failing runs, proposes a new prompt or parser version, runs the Golden set, and hands the result to the Reader. That work is open-ended and tool-heavy, so it is where the Claude Agent SDK earns its cost.

## Considered Options

- **Agent SDK agent per paper, with read-only file tools** (the original draft). Rejected: the tools only re-implemented "here is the paper". It added hooks and tool plumbing, and it blocked batching.
- **Citations API for Evidence.** Rejected for now: citations cannot be combined with structured outputs, and the code-based verbatim quote check gives the same guarantee without that constraint.
