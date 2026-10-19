"""CVR_ALLOW_HTTP: bevidst tilvalg af ukrypteret HTTP, kun til http://distribution.virk.dk:80 i basic-tilstand."""

from __future__ import annotations

from dataclasses import replace

import pytest
import requests

from cvr_radar import cli, cvr_client, errors
from cvr_radar.config import Settings, load_settings
from cvr_radar.cvr_client import CvrClient
from cvr_radar.http import new_session as http_new_session
from cvr_radar.http import send

from .conftest import FakeSession, assert_no_secrets, make_response, respond
from .test_cvr_auth_modes import CapturingAdapter
from .test_cvr_client import ERST_HIT

HTTP_URL = "http://distribution.virk.dk"


def http_settings(settings: Settings, **overrides) -> Settings:
    return replace(settings, **{"cvr_allow_http": True, "cvr_base_url": HTTP_URL, **overrides})


# --- Konfiguration ---------------------------------------------------------------


def test_http_refused_by_default(settings) -> None:
    with pytest.raises(errors.ConfigError, match="https"):
        replace(settings, cvr_base_url=HTTP_URL).require_cvr()


def test_allow_http_accepts_only_official_host_on_port_80(settings) -> None:
    http_settings(settings).require_cvr()
    http_settings(settings, cvr_base_url="http://distribution.virk.dk:80").require_cvr()
    for url in ("http://example.com", "http://distribution.virk.dk:8080", "http://evil.distribution.virk.dk.example"):
        with pytest.raises(errors.ConfigError):
            http_settings(settings, cvr_base_url=url).require_cvr()


def test_allow_http_still_accepts_https(settings) -> None:
    replace(settings, cvr_allow_http=True).require_cvr()


def test_allow_http_rejected_in_proxy_mode() -> None:
    with pytest.raises(errors.ConfigError, match="basic"):
        Settings(cvr_auth_mode="proxy", cvr_allow_http=True, cvr_base_url=HTTP_URL).require_cvr()


def test_load_settings_allow_http(tmp_path) -> None:
    missing = tmp_path / "ingen"
    s = load_settings(env={"CVR_ALLOW_HTTP": "true"}, env_file=missing)
    assert s.cvr_allow_http and s.cvr_base_url == HTTP_URL and s.cvr_uses_http
    assert load_settings(env={}, env_file=missing).cvr_base_url.startswith("https://")
    explicit = load_settings(env={"CVR_ALLOW_HTTP": "true", "CVR_BASE_URL": "https://distribution.virk.dk"}, env_file=missing)
    assert not explicit.cvr_uses_http
    proxy = load_settings(env={"CVR_ALLOW_HTTP": "true", "CVR_AUTH_MODE": "proxy"}, env_file=missing)
    assert proxy.cvr_base_url.startswith("https://")
    with pytest.raises(errors.ConfigError, match="CVR_ALLOW_HTTP"):
        load_settings(env={"CVR_ALLOW_HTTP": "måske"}, env_file=missing)


def test_describe_warns_about_http(settings) -> None:
    rows = {name: (ok, detail) for name, ok, detail in http_settings(settings).describe()}
    assert rows["CVR_ALLOW_HTTP"][0] and "ukrypteret" in rows["CVR_ALLOW_HTTP"][1]
    assert rows["CVR_BASE_URL"] == (True, f"{HTTP_URL} (UKRYPTERET)")
    rows = {name: detail for name, _, detail in settings.describe()}
    assert rows["CVR_ALLOW_HTTP"] == "false: kun HTTPS"


# --- HTTP-laget --------------------------------------------------------------------


def test_send_refuses_http_without_permission() -> None:
    session = FakeSession(respond(make_response(200)))
    with pytest.raises(errors.NetworkError):
        send(session, "POST", f"{HTTP_URL}/x", service="CVR", timeout=5)
    with pytest.raises(errors.NetworkError):
        send(session, "POST", "http://example.com/x", service="CVR", timeout=5, allow_http_host="distribution.virk.dk")
    assert session.calls == []


def test_send_allows_http_for_named_host_without_redirects() -> None:
    session = FakeSession(respond(make_response(200)))
    send(session, "POST", f"{HTTP_URL}/x", service="CVR", timeout=5, allow_http_host="distribution.virk.dk")
    assert session.calls[0][2]["allow_redirects"] is False


# --- CVR-klient og CLI -------------------------------------------------------------


def test_http_lookup_sends_basic_auth_to_official_endpoint(settings) -> None:
    adapter = CapturingAdapter()
    session = http_new_session()
    session.mount("http://", adapter)
    company = CvrClient(http_settings(settings), session=session).lookup_company(10150817)
    assert (company.cvr_number, company.name) == (10150817, "ERHVERVSSTYRELSEN")
    request = adapter.sent[0]
    assert request.url == "http://distribution.virk.dk/cvr-permanent/virksomhed/_search"
    assert request.headers["Authorization"].startswith("Basic ")


def test_http_redirect_not_followed(settings) -> None:
    session = FakeSession(respond(make_response(301, headers={"Location": "http://example.com/"})))
    with pytest.raises(errors.UnexpectedResponseError):
        CvrClient(http_settings(settings), session=session).lookup_company(10150817)
    assert len(session.calls) == 1


def test_http_401_is_login_error(settings) -> None:
    session = FakeSession(respond(make_response(401)))
    with pytest.raises(errors.AuthenticationError):
        CvrClient(http_settings(settings), session=session).lookup_company(10150817)


def test_cli_cvr_test_over_http_warns(monkeypatch, capsys, settings) -> None:
    monkeypatch.setenv("CVR_USERNAME", settings.cvr_username)
    monkeypatch.setenv("CVR_PASSWORD", settings.cvr_password)
    monkeypatch.setenv("CVR_ALLOW_HTTP", "true")
    session = FakeSession(respond(make_response(200, ERST_HIT)))
    monkeypatch.setattr(cvr_client, "new_session", lambda: session)
    assert cli.main(["cvr-test"]) == cli.EXIT_OK
    text = capsys.readouterr().out
    assert_no_secrets(text)
    assert "ADVARSEL" in text and "ukrypteret HTTP" in text
    assert "ERHVERVSSTYRELSEN" in text
    assert session.calls[0][1].startswith("http://distribution.virk.dk/")


def test_cli_proxy_mode_with_allow_http_is_config_error(monkeypatch, capsys) -> None:
    monkeypatch.setenv("CVR_AUTH_MODE", "proxy")
    monkeypatch.setenv("CVR_ALLOW_HTTP", "true")
    assert cli.main(["cvr-test"]) == cli.EXIT_CONFIG


def test_telegram_never_uses_http(settings) -> None:
    from cvr_radar import telegram_client

    assert telegram_client.API_BASE.startswith("https://")
    session = FakeSession(respond(make_response(200, {"ok": True, "result": {}})))
    with pytest.raises(errors.NetworkError):
        send(session, "POST", "http://api.telegram.org/botX/getMe", service="Telegram", timeout=5)
    assert isinstance(requests, object)
