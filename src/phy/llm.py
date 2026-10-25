"""All model calls. phy has no credential code: the SDK's lookup chain finds them
(`ANTHROPIC_API_KEY` if set, otherwise the `ant auth login` profile in `~/.config/anthropic/`).
"""

import anthropic
import structlog
from anthropic.lib.credentials import CredentialsFile, WorkloadIdentityCredentials

log = structlog.get_logger()

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


def _translate(e: anthropic.APIError, source: str, call: str, other: type[Exception]) -> Exception:
    """Rejected credentials become AuthError; any other failure of `call` becomes `other`."""
    if isinstance(e, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return AuthError(
            f"credentials from {source} were rejected (HTTP {e.status_code}); {LOGIN_HINT}"
        )
    if isinstance(e, anthropic.APIStatusError):
        return other(f"{call} failed (HTTP {e.status_code}: {e.message})")
    return other(f"{call} could not reach the Anthropic API ({e})")
