from __future__ import annotations

from typing import Any

import pytest
import requests

from cvr_radar import cli, cvr_client, telegram_client

from .conftest import FAKE_PASSWORD, FAKE_TOKEN, FAKE_USERNAME, FakeSession, assert_no_secrets, make_response
from .test_cvr_client import ERST_HIT
from .test_telegram_client import BOT, fail, ok, private_update, routed


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setenv("CVR_USERNAME", FAKE_USERNAME)
    monkeypatch.setenv("CVR_PASSWORD", FAKE_PASSWORD)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")
    return monkeypatch


def use_session(monkeypatch: pytest.MonkeyPatch, module: Any, handler) -> FakeSession:
    session = FakeSession(handler)
    monkeypatch.setattr(module, "new_session", lambda: session)
    return session


def run(capsys, *argv: str) -> tuple[int, str]:
    code = cli.main(list(argv))
    output = capsys.readouterr()
    text = output.out + output.err
    assert_no_secrets(text)
    return code, text


def test_check_config_missing(capsys) -> None:
    code, text = run(capsys, "check-config")
    assert code == cli.EXIT_CONFIG
    assert "CVR_PASSWORD: mangler" in text


def test_check_config_complete_hides_secrets(env, capsys) -> None:
    code, text = run(capsys, "check-config")
    assert code == cli.EXIT_OK
    assert "IKKE afprøvet" in text


def test_cvr_test_success(env, capsys) -> None:
    use_session(env, cvr_client, lambda m, u, k: make_response(200, ERST_HIT))
    code, text = run(capsys, "cvr-test")
    assert code == 0
    assert "10150817" in text and "ERHVERVSSTYRELSEN" in text


def test_cvr_test_wrong_login(env, capsys) -> None:
    use_session(env, cvr_client, lambda m, u, k: make_response(401))
    code, text = run(capsys, "cvr-test")
    assert code == cli.EXIT_ERROR
    assert "AuthenticationError" in text


def test_cvr_test_network_error_not_called_wrong_password(env, capsys) -> None:
    def handler(m, u, k):
        raise requests.exceptions.ProxyError("Tunnel connection failed: 403 Forbidden")

    use_session(env, cvr_client, handler)
    code, text = run(capsys, "cvr-test")
    assert code == cli.EXIT_ERROR
    assert "NetworkError" in text and "ikke et loginproblem" in text


def test_cvr_test_missing_config(capsys) -> None:
    code, text = run(capsys, "cvr-test")
    assert code == cli.EXIT_CONFIG


def test_find_chat_lists_candidates_without_choosing(env, capsys) -> None:
    updates = [
        private_update(1, 111, "Anna", "hej", 1_700_000_000),
        private_update(2, 222, "Bo", "CVR Radar opsætning blåbær", 1_700_000_100, "bo"),
    ]
    use_session(env, telegram_client, routed({"getMe": ok(BOT), "getWebhookInfo": ok({"url": ""}), "getUpdates": ok(updates)}))
    code, text = run(capsys, "telegram-find-chat")
    assert code == 0
    assert "111" in text and "222" in text and "IKKE valgt" in text

    code, text = run(capsys, "telegram-find-chat", "--match", "blåbær")
    assert "222" in text and "chat-id 111" not in text


def test_find_chat_webhook_explained(env, capsys) -> None:
    session = use_session(env, telegram_client, routed({"getMe": ok(BOT), "getWebhookInfo": ok({"url": "https://andet.example/h"})}))
    code, text = run(capsys, "telegram-find-chat")
    assert code == cli.EXIT_ERROR
    assert "webhook" in text and "andet.example" in text
    assert "deleteWebhook" not in session.methods()


def test_telegram_test_dry_run_sends_nothing(env, capsys) -> None:
    session = use_session(env, telegram_client, routed({
        "getMe": ok(BOT),
        "getChat": ok({"id": 987654321, "type": "private", "first_name": "Ayman"}),
    }))
    code, text = run(capsys, "telegram-test")
    assert code == 0
    assert "sendMessage" not in session.methods()
    assert "IKKE sendt" in text and "Ayman" in text


def test_telegram_test_send_exactly_once(env, capsys) -> None:
    sent = {"message_id": 5, "chat": {"id": 987654321}, "date": 1_700_000_000}
    session = use_session(env, telegram_client, routed({
        "getMe": ok(BOT),
        "getChat": ok({"id": 987654321, "type": "private", "first_name": "Ayman"}),
        "sendMessage": ok(sent),
    }))
    code, text = run(capsys, "telegram-test", "--send")
    assert code == 0
    assert session.methods().count("sendMessage") == 1
    assert "ACCEPTERET" in text and "IKKE bekræftet" in text


def test_telegram_test_requires_chat_id(env, capsys) -> None:
    env.delenv("TELEGRAM_CHAT_ID")
    code, text = run(capsys, "telegram-test", "--send")
    assert code == cli.EXIT_CONFIG


def test_telegram_blocked_recipient(env, capsys) -> None:
    use_session(env, telegram_client, routed({
        "getMe": ok(BOT),
        "getChat": fail(400, "Bad Request: chat not found"),
    }))
    code, text = run(capsys, "telegram-test", "--send")
    assert code == cli.EXIT_ERROR
    assert "ChatNotFoundError" in text


def test_unexpected_exception_is_masked(env, capsys) -> None:
    def boom(m, u, k):
        raise RuntimeError(f"noget gik galt med /bot{FAKE_TOKEN}/getMe og {FAKE_PASSWORD}")

    use_session(env, telegram_client, boom)
    code, text = run(capsys, "telegram-check")
    assert code == cli.EXIT_ERROR
    assert "UVENTET FEJL" in text


def test_setup_local_writes_private_env_file(tmp_path, monkeypatch, capsys) -> None:
    answers = iter([FAKE_USERNAME, "987654321"])
    secrets = iter([FAKE_PASSWORD, FAKE_TOKEN])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(secrets))
    path = tmp_path / ".env"
    code, text = run(capsys, "setup-local", "--env-file", str(path))
    assert code == 0
    assert (path.stat().st_mode & 0o777) == 0o600
    from cvr_radar.config import load_settings

    s = load_settings(env={}, env_file=path)
    assert (s.cvr_username, s.cvr_password, s.telegram_bot_token, s.telegram_chat_id) == (
        FAKE_USERNAME, FAKE_PASSWORD, FAKE_TOKEN, "987654321",
    )
