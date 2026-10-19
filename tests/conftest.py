"""Fælles test-hjælpere. Alle HTTP-kald simuleres; rigtige netværkskald får testen til at fejle."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
import requests

from cvr_radar.config import Settings

FAKE_TOKEN = "123456789:AAHfakeTokenForTestsOnly_abcdefghijklmn"
FAKE_PASSWORD = "S3cret-Pa55word!"
FAKE_USERNAME = "test_cvr_user"


@pytest.fixture(autouse=True)
def isolate(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    for name in ("CVR_USERNAME", "CVR_PASSWORD", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                 "CVR_AUTH_MODE", "CVR_BASE_URL", "CVR_INDEX", "HTTP_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CVR_RADAR_ENV_FILE", str(tmp_path / "ingen.env"))

    def no_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Test forsøgte et rigtigt netværkskald")

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", no_network)


def make_response(status: int, body: Any = None, headers: dict[str, str] | None = None, raw_text: str | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = (raw_text if raw_text is not None else json.dumps(body if body is not None else {})).encode()
    response.headers.update(headers or {})
    return response


class FakeSession:
    """Erstatning for requests.Session. `handler(method, url, kwargs)` returnerer et svar eller kaster."""

    def __init__(self, handler: Callable[[str, str, dict[str, Any]], requests.Response]) -> None:
        self.handler = handler
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.headers: dict[str, str] = {}

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        self.calls.append((method, url, kwargs))
        return self.handler(method, url, kwargs)

    def methods(self) -> list[str]:
        """Telegram-metodenavne i kaldsrækkefølge (sidste URL-del)."""
        return [url.rsplit("/", 1)[-1] for _, url, _ in self.calls]


def respond(response: requests.Response) -> Callable[..., requests.Response]:
    return lambda method, url, kwargs: response


def raise_(exc: Exception) -> Callable[..., requests.Response]:
    def handler(method: str, url: str, kwargs: dict[str, Any]) -> requests.Response:
        raise exc

    return handler


@pytest.fixture
def settings() -> Settings:
    from cvr_radar.redact import register_secrets

    register_secrets([FAKE_USERNAME, FAKE_PASSWORD, FAKE_TOKEN])
    return Settings(
        cvr_username=FAKE_USERNAME,
        cvr_password=FAKE_PASSWORD,
        telegram_bot_token=FAKE_TOKEN,
        telegram_chat_id="987654321",
    )


def assert_no_secrets(text: str) -> None:
    for secret in (FAKE_TOKEN, FAKE_PASSWORD, FAKE_USERNAME, FAKE_TOKEN.split(":", 1)[1]):
        assert secret not in text, f"Hemmelighed lækket i: {text!r}"
    assert "Basic " + "dGVzd" not in text  # base64 af brugernavn
