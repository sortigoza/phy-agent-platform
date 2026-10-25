"""All model calls. phy has no credential code: the SDK's lookup chain finds them
(`ANTHROPIC_API_KEY` if set, otherwise the `ant auth login` profile in `~/.config/anthropic/`).

Every Stage call is built here (prompt version, model, effort, cache breakpoint, output format
from the Pydantic schema), validated against that schema, priced from `config.toml` and
handed to the Tracer, whether it succeeded or not.
"""

import time

import anthropic
import structlog
from anthropic.lib.credentials import CredentialsFile, WorkloadIdentityCredentials
from pydantic import BaseModel, ValidationError

from phy import prompts
from phy.card import SCHEMA_VERSION, CardDraft, draft_format
from phy.config import Price
from phy.ctx import Ctx
from phy.prompts import PromptError
from phy.questions import render_questions
from phy.tracer import Response, Run

log = structlog.get_logger()

# A Card measured 3k output tokens; the SDK refuses a non-streaming call above about 21k.
READ_MAX_TOKENS = 16_000

LOGIN_HINT = "run `ant auth login` (or export ANTHROPIC_API_KEY for interactive use)"


class AuthError(Exception):
    pass


class ApiError(Exception):
    """A model API call failed for a reason other than credentials."""


def credential_source(client: anthropic.Anthropic) -> str | None:
    """Which credential the SDK picked, in words, or None if it found none."""
    if client.api_key:
        return "ANTHROPIC_API_KEY"
    if client.auth_token:
        return "ANTHROPIC_AUTH_TOKEN"
    match client.credentials:
        case None:
            return None
        case CredentialsFile() as profile:
            config_dir = profile.config_path.parent.parent
            return f"`ant auth login` profile {profile.profile!r} ({config_dir})"
        case WorkloadIdentityCredentials():
            return "workload identity federation"
        case other:
            return type(other).__name__


def _client() -> tuple[anthropic.Anthropic, str]:
    """A client and its credential source, or AuthError if the SDK finds no credentials."""
    try:
        client = anthropic.Anthropic()
    except anthropic.CredentialsError as e:
        raise AuthError(f"Anthropic credentials could not be loaded ({e}); {LOGIN_HINT}") from None
    source = credential_source(client)
    if source is None:
        raise AuthError(f"no Anthropic credentials found; {LOGIN_HINT}")
    return client, source


def check_auth(model: str) -> str:
    """Make one tiny call to `model` and return the credential source that worked."""
    client, source = _client()
    try:
        client.messages.create(
            model=model,
            max_tokens=8,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": "Reply with: ok"}],
        )
    except anthropic.APIError as e:
        raise _translate(e, source, f"auth check call to {model}", AuthError) from None
    log.info("auth.checked", source=source, model=model)
    return source


def count_tokens(model: str, text: str) -> int:
    """Input tokens of `text` as one user turn to `model`, from the free count_tokens endpoint."""
    client, source = _client()
    try:
        result = client.messages.count_tokens(
            model=model, messages=[{"role": "user", "content": text}]
        )
    except anthropic.APIError as e:
        raise _translate(e, source, f"count_tokens for {model}", ApiError) from None
    return result.input_tokens


def read_card(ctx: Ctx, run: Run, paper_text: str, authors: str) -> CardDraft:
    """One Read call on a Paper version's flattened text. The request is the shared system
    prompt, then the paper text ending in the cache breakpoint, then the Read instructions, so
    everything up to the paper is a prefix other per-paper calls can reuse."""
    config = ctx.config.read
    prompt = prompts.load("read", config.prompt_version)
    if prompt.schema_version != SCHEMA_VERSION:
        raise PromptError(
            f"prompt {prompt.name} targets {prompt.schema_version}, not {SCHEMA_VERSION}"
        )
    if prompt.system is None:
        raise PromptError(f"prompt {prompt.name} names no shared system prompt")
    for key in ["model", "effort"]:
        if getattr(prompt, key) != getattr(config, key):
            log.warning(
                "llm.prompt_config_differs",
                key=key,
                prompt=prompt.name,
                prompt_value=getattr(prompt, key),
                config_value=getattr(config, key),
            )
    system = prompts.load(*prompt.system.split("/", 1)).render()
    available = {"questions": render_questions(ctx.questions), "authors": authors}
    instructions = prompt.render(**{k: v for k, v in available.items() if k in prompt.params})
    request = {
        "model": config.model,
        "max_tokens": READ_MAX_TOKENS,
        "system": system,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"<paper>\n{paper_text}\n</paper>",
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": instructions},
                ],
            }
        ],
        "output_config": {"effort": config.effort, "format": draft_format()},
    }
    return _parse(ctx, run, request, CardDraft, ctx.config.prices[config.model])


def _parse[M: BaseModel](
    ctx: Ctx, run: Run, request: dict, output_format: type[M], price: Price
) -> M:
    """Make the call, trace it, and return the validated output or raise ApiError.

    This is `messages.parse()` done by hand: the request carries the schema as
    `output_config.format` and the text is validated against the same model. Doing it by hand
    keeps the raw body, so a response that fails validation is still traced and priced."""
    client, source = _client()
    call = f"{run.stage} call to {request['model']}"
    started = time.monotonic()
    try:
        raw = client.messages.with_raw_response.create(**request)
    except anthropic.APIError as e:
        error = _translate(e, source, call, ApiError)
        ctx.tracer.record(run, request, None, str(error))
        raise error from None
    body = raw.json()
    response = Response(
        body=body,
        cost_usd=cost(price, body["usage"]),
        duration_ms=round((time.monotonic() - started) * 1000),
    )
    output, error = None, None
    if body["stop_reason"] != "end_turn":
        error = f"{call} stopped with {body['stop_reason']}"
    else:
        text = "".join(block["text"] for block in body["content"] if block["type"] == "text")
        try:
            output = output_format.model_validate_json(text)
        except ValidationError as e:
            error = f"{call} returned output that fails its schema ({e.error_count()} errors)"
    ctx.tracer.record(run, request, response, error)
    log.debug(
        "llm.called",
        model=body.get("model"),
        duration_ms=response.duration_ms,
        stop_reason=body["stop_reason"],
    )
    if error:
        raise ApiError(error)
    return output


def cost(price: Price, usage: dict) -> float:
    """USD for one call, from per-million-token prices; cache writes and reads priced apart."""
    return (
        usage["input_tokens"] * price.input
        + usage["output_tokens"] * price.output
        + (usage.get("cache_creation_input_tokens") or 0) * price.cache_write
        + (usage.get("cache_read_input_tokens") or 0) * price.cache_read
    ) / 1e6


def _translate(e: anthropic.APIError, source: str, call: str, other: type[Exception]) -> Exception:
    """Rejected credentials become AuthError; any other failure of `call` becomes `other`."""
    if isinstance(e, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return AuthError(
            f"credentials from {source} were rejected (HTTP {e.status_code}); {LOGIN_HINT}"
        )
    if isinstance(e, anthropic.APIStatusError):
        return other(f"{call} failed (HTTP {e.status_code}: {e.message})")
    return other(f"{call} could not reach the Anthropic API ({e})")
