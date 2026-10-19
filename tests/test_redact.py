from __future__ import annotations

import logging

from cvr_radar.redact import RedactingFilter, redact, register_secret

from .conftest import FAKE_TOKEN, assert_no_secrets


def test_token_in_url_is_masked_even_if_unregistered() -> None:
    other = "555555555:BBBunregisteredTokenValue_0123456789"
    text = f"Max retries exceeded with url: /bot{other}/getMe"
    assert other not in redact(text)
    assert "/bot***/getMe" in redact(text)


def test_authorization_header_masked() -> None:
    assert "dXNlcjpwYXNz" not in redact("{'Authorization': 'Basic dXNlcjpwYXNz'}")
    assert "abc.def" not in redact("Authorization: Bearer abc.def")


def test_userinfo_in_url_masked() -> None:
    assert redact("https://bruger:kode@distribution.virk.dk/x") == "https://***@distribution.virk.dk/x"


def test_registered_secret_masked(settings) -> None:
    register_secret("hemmelig-kode-123")
    assert redact("kode=hemmelig-kode-123") == "kode=***"
    assert_no_secrets(redact(f"token {FAKE_TOKEN} i tekst"))


def test_logging_filter_masks_args(settings) -> None:
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, "kald til %s fejlede", (f"/bot{FAKE_TOKEN}/getMe",), None)
    RedactingFilter().filter(record)
    assert_no_secrets(record.getMessage())
