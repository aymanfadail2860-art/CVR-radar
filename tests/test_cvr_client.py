from __future__ import annotations

import pytest
import requests

from cvr_radar import errors
from cvr_radar.cvr_client import CvrClient, build_lookup_query, validate_cvr_number

from .conftest import FAKE_PASSWORD, FakeSession, assert_no_secrets, make_response, raise_, respond

ERST_HIT = {
    "took": 3,
    "hits": {
        "total": 1,
        "hits": [
            {
                "_index": "cvr-permanent",
                "_source": {
                    "Vrvirksomhed": {
                        "cvrNummer": 10150817,
                        "virksomhedMetadata": {"nyesteNavn": {"navn": "ERHVERVSSTYRELSEN"}},
                    }
                },
            }
        ],
    },
}


def client(settings, handler) -> tuple[CvrClient, FakeSession]:
    session = FakeSession(handler)
    return CvrClient(settings, session=session), session


def test_lookup_success_and_request_shape(settings) -> None:
    c, session = client(settings, respond(make_response(200, ERST_HIT)))
    company = c.lookup_company(10150817)
    assert (company.cvr_number, company.name) == (10150817, "ERHVERVSSTYRELSEN")

    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "https://distribution.virk.dk/cvr-permanent/virksomhed/_search"
    assert kwargs["json"] == build_lookup_query(10150817)
    assert kwargs["auth"] == (settings.cvr_username, FAKE_PASSWORD)
    assert kwargs["allow_redirects"] is False
    assert "verify" not in kwargs  # certifikatkontrol forbliver requests' standard (slået til)


def test_query_is_limited() -> None:
    q = build_lookup_query(10150817)
    assert q["size"] == 1
    assert q["query"] == {"term": {"Vrvirksomhed.cvrNummer": 10150817}}
    assert q["_source"]


def test_not_found(settings) -> None:
    c, _ = client(settings, respond(make_response(200, {"hits": {"total": 0, "hits": []}})))
    with pytest.raises(errors.NotFoundError):
        c.lookup_company(12345678)


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, errors.AuthenticationError),
        (403, errors.PermissionDeniedError),
        (429, errors.RateLimitedError),
        (500, errors.ServerError),
        (503, errors.ServerError),
        (404, errors.UnexpectedResponseError),
        (301, errors.UnexpectedResponseError),
        (400, errors.UnexpectedResponseError),
    ],
)
def test_http_status_mapping(settings, status, error_type) -> None:
    c, _ = client(settings, respond(make_response(status, {"error": "x"}, headers={"Retry-After": "30"})))
    with pytest.raises(error_type) as exc:
        c.lookup_company(10150817)
    assert_no_secrets(str(exc.value) + str(exc.value.hint))
    if status == 429:
        assert exc.value.retry_after == 30


def test_only_401_is_reported_as_wrong_password(settings) -> None:
    c, _ = client(settings, respond(make_response(401)))
    with pytest.raises(errors.AuthenticationError) as exc:
        c.lookup_company(10150817)
    assert "adgangskode" in str(exc.value)


@pytest.mark.parametrize(
    ("exc", "error_type"),
    [
        (requests.exceptions.ConnectTimeout("connect timeout"), errors.TimeoutError_),
        (requests.exceptions.ReadTimeout("read timeout"), errors.TimeoutError_),
        (requests.exceptions.ConnectionError("Name or service not known"), errors.NetworkError),
        (requests.exceptions.ProxyError("Tunnel connection failed: 403 Forbidden"), errors.NetworkError),
        (requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED"), errors.CertificateError),
    ],
)
def test_network_failures_are_not_login_errors(settings, exc, error_type) -> None:
    c, _ = client(settings, raise_(exc))
    with pytest.raises(error_type) as caught:
        c.lookup_company(10150817)
    assert not isinstance(caught.value, (errors.AuthenticationError, errors.PermissionDeniedError))
    assert "adgangskode" not in str(caught.value).lower()
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_secret_in_exception_text_is_masked(settings) -> None:
    leaky = requests.exceptions.ConnectionError(f"failed for https://{settings.cvr_username}:{FAKE_PASSWORD}@host")
    c, _ = client(settings, raise_(leaky))
    with pytest.raises(errors.NetworkError) as exc:
        c.lookup_company(10150817)
    assert_no_secrets(str(exc.value))


def test_invalid_json_and_missing_fields(settings) -> None:
    c, _ = client(settings, respond(make_response(200, raw_text="<html>")))
    with pytest.raises(errors.UnexpectedResponseError):
        c.lookup_company(10150817)
    c, _ = client(settings, respond(make_response(200, {"hits": {"hits": [{"_source": {}}]}})))
    with pytest.raises(errors.UnexpectedResponseError):
        c.lookup_company(10150817)


def test_http_base_url_refused_before_any_request(settings) -> None:
    from dataclasses import replace

    with pytest.raises(errors.ConfigError):
        CvrClient(replace(settings, cvr_base_url="http://distribution.virk.dk"), session=FakeSession(respond(make_response(200))))


@pytest.mark.parametrize("value", ["1015081", "101508170", "1015081x", ""])
def test_validate_cvr_number_rejects(value) -> None:
    with pytest.raises(ValueError):
        validate_cvr_number(value)


def test_validate_cvr_number_accepts() -> None:
    assert validate_cvr_number(" 10150817 ") == 10150817
