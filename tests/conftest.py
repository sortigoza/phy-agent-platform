import inspect

import httpx
import httpx2
import pytest
from respx.mocks import Mocker
from respx.transports import TryTransport


class HTTPX2Mocker(Mocker):
    """Lets respx replay requests made through httpx2, which the anthropic SDK uses.

    Use with `respx.mock(using="httpx2")`. Requests and responses are copied between the
    two libraries' types so routes are written exactly as for httpx.
    """

    name = "httpx2"
    targets = ["httpx2._client.Client", "httpx2._client.AsyncClient"]
    target_methods = ["_transport_for_url"]

    @classmethod
    def _to_httpx(cls, request: httpx2.Request) -> httpx.Request:
        return httpx.Request(
            request.method, str(request.url), headers=request.headers.raw, content=request.read()
        )

    @classmethod
    def _to_httpx2(cls, response: httpx.Response) -> httpx2.Response:
        return httpx2.Response(
            response.status_code, headers=response.headers.raw, content=response.read()
        )

    @classmethod
    def mock(cls, spec):
        def handler(request):
            return cls._to_httpx2(cls.handler(cls._to_httpx(request)))

        async def async_handler(request):
            return cls._to_httpx2(await cls.async_handler(cls._to_httpx(request)))

        def _transport_for_url(self, *args, **kwargs):
            sync = not inspect.iscoroutinefunction(self.request)
            mock_transport = httpx2.MockTransport(handler if sync else async_handler)
            return TryTransport([mock_transport, spec(self, *args, **kwargs)])

        return _transport_for_url


@pytest.fixture(autouse=True)
def phy_home(tmp_path, monkeypatch):
    """Every test gets its own $PHY_HOME and HOME, and no ambient Anthropic credentials."""
    home = tmp_path / "phy-home"
    monkeypatch.setenv("PHY_HOME", str(home))
    monkeypatch.setenv("HOME", str(tmp_path / "user-home"))
    for var in [
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_PROFILE",
        "ANTHROPIC_CONFIG_DIR",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_FEDERATION_RULE_ID",
    ]:
        monkeypatch.delenv(var, raising=False)
    return home
