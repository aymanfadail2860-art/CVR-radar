from __future__ import annotations

import pytest

from cvr_radar.config import Settings, load_settings, parse_env_file
from cvr_radar.errors import ConfigError

from .conftest import FAKE_PASSWORD, FAKE_TOKEN


def test_missing_cvr_credentials_named_in_error() -> None:
    with pytest.raises(ConfigError) as exc:
        Settings().require_cvr()
    assert "CVR_USERNAME" in str(exc.value) and "CVR_PASSWORD" in str(exc.value)


def test_missing_telegram_token_and_chat_id() -> None:
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        Settings().require_telegram_token()
    with pytest.raises(ConfigError, match="TELEGRAM_CHAT_ID"):
        Settings().require_chat_id()


def test_malformed_token_and_chat_id_rejected_without_echo() -> None:
    bad = "not-a-token-but-secret"
    with pytest.raises(ConfigError) as exc:
        Settings(telegram_bot_token=bad).require_telegram_token()
    assert bad not in str(exc.value)
    with pytest.raises(ConfigError):
        Settings(telegram_chat_id="@mig").require_chat_id()


@pytest.mark.parametrize("url", ["http://distribution.virk.dk", "ftp://x", "https://u:p@distribution.virk.dk", "distribution.virk.dk"])
def test_only_https_base_url_allowed(url: str) -> None:
    with pytest.raises(ConfigError):
        Settings(cvr_username="u", cvr_password="p", cvr_base_url=url).require_cvr()


def test_describe_never_contains_secrets(settings: Settings) -> None:
    text = "\n".join(f"{n} {d}" for n, _, d in settings.describe())
    assert FAKE_PASSWORD not in text
    assert FAKE_TOKEN not in text
    assert settings.cvr_username not in text
    assert all(ok for _, ok, _ in settings.describe())


def test_repr_hides_secrets(settings: Settings) -> None:
    assert FAKE_PASSWORD not in repr(settings)
    assert FAKE_TOKEN not in repr(settings)


def test_env_file_parsing(tmp_path) -> None:
    path = tmp_path / ".env"
    path.write_text(
        "# kommentar\n"
        "CVR_USERNAME=bruger\n"
        "CVR_PASSWORD='med # hash'\n"
        'TELEGRAM_CHAT_ID="42"\n'
        "export HTTP_TIMEOUT_SECONDS=5 # kommentar\n"
        "TOM=\n"
        "ugyldig linje\n",
        encoding="utf-8",
    )
    assert parse_env_file(path) == {
        "CVR_USERNAME": "bruger",
        "CVR_PASSWORD": "med # hash",
        "TELEGRAM_CHAT_ID": "42",
        "HTTP_TIMEOUT_SECONDS": "5",
        "TOM": "",
    }


def test_environment_overrides_env_file(tmp_path) -> None:
    path = tmp_path / ".env"
    path.write_text("CVR_USERNAME=fra_fil\nCVR_PASSWORD=fil_kode\n", encoding="utf-8")
    s = load_settings(env={"CVR_USERNAME": "fra_miljo"}, env_file=path)
    assert s.cvr_username == "fra_miljo"
    assert s.cvr_password == "fil_kode"
    assert s.env_file == str(path)


def test_defaults_and_invalid_timeout(tmp_path) -> None:
    s = load_settings(env={}, env_file=tmp_path / "findes-ikke")
    assert s.cvr_base_url == "https://distribution.virk.dk"
    assert s.cvr_index == "cvr-permanent/virksomhed"
    with pytest.raises(ConfigError):
        load_settings(env={"HTTP_TIMEOUT_SECONDS": "nul"}, env_file=tmp_path / "findes-ikke")
