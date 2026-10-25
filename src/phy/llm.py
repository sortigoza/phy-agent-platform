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


def check_auth(model: str) -> str:
    """Make one tiny call to `model` and return the credential source that worked."""
    try:
        client = anthropic.Anthropic()
    except anthropic.CredentialsError as e:
        raise AuthError(f"Anthropic credentials could not be loaded ({e}); {LOGIN_HINT}") from None
    source = credential_source(client)
    if source is None:
        raise AuthError(f"no Anthropic credentials found; {LOGIN_HINT}")
    try:
        client.messages.create(
            model=model,
            max_tokens=8,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": "Reply with: ok"}],
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        raise AuthError(
            f"credentials from {source} were rejected (HTTP {e.status_code}); {LOGIN_HINT}"
        ) from None
    except anthropic.APIStatusError as e:
        raise AuthError(
            f"auth check call to {model} failed (HTTP {e.status_code}: {e.message})"
        ) from None
    except anthropic.APIConnectionError as e:
        raise AuthError(f"auth check could not reach the Anthropic API ({e})") from None
    log.info("auth.checked", source=source, model=model)
    return source
