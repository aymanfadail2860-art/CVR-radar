"""Begge loginmåder: basic (programmet sender login) og proxy (netværksproxyen tilføjer login)."""

from __future__ import annotations

from dataclasses import replace

import pytest
import requests

from cvr_radar import cli, cvr_client, errors
from cvr_radar.config import Settings, load_settings
from cvr_radar.cvr_client import CvrClient, ProxyInjectedAuth
from cvr_radar.http import new_session as http_new_session

from .conftest import FAKE_PASSWORD, FAKE_USERNAME, FakeSession, assert_no_secrets, make_response, respond
from .test_cvr_client import ERST_HIT


def proxy_settings(**overrides) -> Settings:
    return Settings(cvr_auth_mode="proxy", **overrides)


class CapturingAdapter(requests.adapters.HTTPAdapter):
    """Fanger den færdige forespørgsel, som requests ville sende, uden netværk."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[requests.PreparedRequest] = []
        self.send_kwargs: list[dict] = []

    def send(self, request, **kwargs):  # type: ignore[override]
        self.sent.append(request)
        self.send_kwargs.append(kwargs)
        response = make_response(200, ERST_HIT)
        response.request = request
        response.url = request.url
        return response


def real_session(adapter: CapturingAdapter) -> requests.Session:
    session = http_new_session()
    session.mount("https://", adapter)
    return session


@pytest.fixture
def netrc_with_login(tmp_path, monkeypatch) -> None:
    """En ~/.netrc med login til distribution.virk.dk må ikke blive brugt i proxytilstand."""
    path = tmp_path / "netrc"
    path.write_text(f"machine distribution.virk.dk login {FAKE_USERNAME} password {FAKE_PASSWORD}\n")
    path.chmod(0o600)
    monkeypatch.setenv("NETRC", str(path))


# --- Konfiguration ---------------------------------------------------------------


def test_auth_mode_parsing(tmp_path) -> None:
    missing = tmp_path / "ingen"
    assert load_settings(env={}, env_file=missing).cvr_auth_mode == "basic"
    assert load_settings(env={"CVR_AUTH_MODE": "Proxy"}, env_file=missing).cvr_auth_via_proxy
    with pytest.raises(errors.ConfigError, match="CVR_AUTH_MODE"):
        load_settings(env={"CVR_AUTH_MODE": "dummy"}, env_file=missing)


def test_proxy_mode_does_not_require_local_credentials() -> None:
    proxy_settings().require_cvr()  # må ikke kaste
    with pytest.raises(errors.ConfigError):
        Settings().require_cvr()  # basic kræver stadig login


def test_proxy_mode_still_requires_https() -> None:
    with pytest.raises(errors.ConfigError):
        proxy_settings(cvr_base_url="http://distribution.virk.dk").require_cvr()


def test_describe_proxy_mode(monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    rows = {name: (ok, detail) for name, ok, detail in proxy_settings().describe()}
    assert rows["CVR_AUTH_MODE"][0] and "ikke verificeret" in rows["CVR_AUTH_MODE"][1]
    assert rows["CVR_USERNAME"] == (True, "ikke påkrævet i proxytilstand")
    assert rows["CVR_PASSWORD"] == (True, "ikke påkrævet i proxytilstand")
    assert rows["HTTPS_PROXY"][0]
    assert "127.0.0.1" not in rows["HTTPS_PROXY"][1]


def test_describe_proxy_mode_without_proxy(monkeypatch) -> None:
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    rows = {name: ok for name, ok, _ in proxy_settings().describe()}
    assert rows["HTTPS_PROXY"] is False


def test_describe_proxy_mode_ignores_set_credentials() -> None:
    s = proxy_settings(cvr_username=FAKE_USERNAME, cvr_password=FAKE_PASSWORD)
    text = "\n".join(f"{n} {d}" for n, _, d in s.describe())
    assert "ignoreres" in text
    assert FAKE_USERNAME not in text and FAKE_PASSWORD not in text


# --- Hvad der faktisk sendes ------------------------------------------------------


def test_proxy_mode_sends_no_authorization(netrc_with_login) -> None:
    adapter = CapturingAdapter()
    s = proxy_settings(cvr_username=FAKE_USERNAME, cvr_password=FAKE_PASSWORD)  # skal ignoreres
    company = CvrClient(s, session=real_session(adapter)).lookup_company(10150817)
    assert company.name == "ERHVERVSSTYRELSEN"
    request = adapter.sent[0]
    assert "Authorization" not in request.headers
    assert request.url == "https://distribution.virk.dk/cvr-permanent/virksomhed/_search"
    assert adapter.send_kwargs[0]["verify"] is not False


def test_proxy_auth_strips_any_authorization_header() -> None:
    request = requests.Request("POST", "https://distribution.virk.dk/x", headers={"Authorization": "Basic abc"}).prepare()
    assert "Authorization" not in ProxyInjectedAuth()(request).headers


def test_basic_mode_sends_basic_authorization(settings) -> None:
    adapter = CapturingAdapter()
    CvrClient(settings, session=real_session(adapter)).lookup_company(10150817)
    assert adapter.sent[0].headers["Authorization"].startswith("Basic ")


def test_proxy_mode_respects_environment_proxy(monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    adapter = CapturingAdapter()
    CvrClient(proxy_settings(), session=real_session(adapter)).lookup_company(10150817)
    assert adapter.send_kwargs[0]["proxies"].get("https") == "http://127.0.0.1:9"


def test_proxy_mode_no_redirects() -> None:
    session = FakeSession(respond(make_response(302, headers={"Location": "http://distribution.virk.dk/"})))
    with pytest.raises(errors.UnexpectedResponseError, match="omdirigering"):
        CvrClient(proxy_settings(), session=session).lookup_company(10150817)
    assert session.calls[0][2]["allow_redirects"] is False
    assert len(session.calls) == 1


def test_proxy_mode_401_points_to_network_secret() -> None:
    session = FakeSession(respond(make_response(401)))
    with pytest.raises(errors.AuthenticationError) as exc:
        CvrClient(proxy_settings(), session=session).lookup_company(10150817)
    assert "netværkshemmelighed" in str(exc.value)


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(403, errors.PermissionDeniedError), (500, errors.ServerError), (429, errors.RateLimitedError)],
)
def test_proxy_mode_status_mapping(status, error_type) -> None:
    session = FakeSession(respond(make_response(status)))
    with pytest.raises(error_type):
        CvrClient(proxy_settings(), session=session).lookup_company(10150817)


# --- CLI -------------------------------------------------------------------------


def test_cli_check_config_proxy_mode(monkeypatch, capsys) -> None:
    monkeypatch.setenv("CVR_AUTH_MODE", "proxy")
    cli.main(["check-config"])
    text = capsys.readouterr().out
    assert "CVR_AUTH_MODE: proxy" in text
    assert "CVR_PASSWORD: ikke påkrævet" in text
    assert "IKKE verificeret" in text


def test_cli_cvr_test_proxy_mode_without_credentials(monkeypatch, capsys, netrc_with_login) -> None:
    monkeypatch.setenv("CVR_AUTH_MODE", "proxy")
    adapter = CapturingAdapter()
    monkeypatch.setattr(cvr_client, "new_session", lambda: real_session(adapter))
    assert cli.main(["cvr-test"]) == cli.EXIT_OK
    text = capsys.readouterr().out
    assert_no_secrets(text)
    assert "10150817" in text and "ERHVERVSSTYRELSEN" in text and "proxy" in text
    assert "Authorization" not in adapter.sent[0].headers


def test_cli_cvr_test_proxy_blocked_is_network_error(monkeypatch, capsys) -> None:
    monkeypatch.setenv("CVR_AUTH_MODE", "proxy")

    def blocked(m, u, k):
        raise requests.exceptions.ProxyError("Tunnel connection failed: 403 Forbidden")

    monkeypatch.setattr(cvr_client, "new_session", lambda: FakeSession(blocked))
    assert cli.main(["cvr-test"]) == cli.EXIT_ERROR
    text = capsys.readouterr().out
    assert "NetworkError" in text and "AuthenticationError" not in text


def test_basic_mode_unchanged(settings) -> None:
    session = FakeSession(respond(make_response(200, ERST_HIT)))
    CvrClient(replace(settings, cvr_auth_mode="basic"), session=session).lookup_company(10150817)
    assert session.calls[0][2]["auth"] == (FAKE_USERNAME, FAKE_PASSWORD)


def test_proxy_upstream_failure_is_network_error_not_server_error() -> None:
    response = make_response(502, raw_text="upstream request failed", headers={"Content-Type": "text/plain; charset=utf-8"})
    with pytest.raises(errors.NetworkError) as exc:
        CvrClient(proxy_settings(), session=FakeSession(respond(response))).lookup_company(10150817)
    assert not isinstance(exc.value, (errors.ServerError, errors.AuthenticationError))
    assert "loginet er ikke afprøvet" in str(exc.value)


def test_real_cvr_502_is_server_error() -> None:
    response = make_response(502, raw_text="<html>Bad Gateway</html>", headers={"Content-Type": "text/html"})
    with pytest.raises(errors.ServerError):
        CvrClient(proxy_settings(), session=FakeSession(respond(response))).lookup_company(10150817)
