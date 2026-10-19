from __future__ import annotations

from typing import Any

import pytest
import requests

from cvr_radar import errors
from cvr_radar.telegram_client import TEST_MESSAGE, TelegramClient, build_test_message, find_private_chats

from .conftest import FAKE_TOKEN, FakeSession, assert_no_secrets, make_response, raise_

BOT = {"id": 123456789, "is_bot": True, "first_name": "CVR Radar", "username": "cvr_radar_test_bot"}


def ok(result: Any) -> requests.Response:
    return make_response(200, {"ok": True, "result": result})


def fail(code: int, description: str, **extra: Any) -> requests.Response:
    return make_response(code, {"ok": False, "error_code": code, "description": description, **extra})


def routed(routes: dict[str, requests.Response]):
    def handler(method: str, url: str, kwargs: dict[str, Any]) -> requests.Response:
        return routes[url.rsplit("/", 1)[-1]]

    return handler


def client(settings, handler) -> tuple[TelegramClient, FakeSession]:
    session = FakeSession(handler)
    return TelegramClient(settings, session=session), session


def private_update(update_id: int, chat_id: int, first: str, text: str, date: int, username: str = "") -> dict:
    chat = {"id": chat_id, "type": "private", "first_name": first}
    if username:
        chat["username"] = username
    return {"update_id": update_id, "message": {"message_id": update_id, "chat": chat, "date": date, "text": text}}


def test_get_me_success_uses_https_and_token_only_in_url(settings) -> None:
    c, session = client(settings, routed({"getMe": ok(BOT)}))
    bot = c.get_me()
    assert bot.username == "cvr_radar_test_bot"
    _, url, kwargs = session.calls[0]
    assert url == f"https://api.telegram.org/bot{FAKE_TOKEN}/getMe"
    assert kwargs["allow_redirects"] is False and "verify" not in kwargs


@pytest.mark.parametrize("code", [401, 404])
def test_invalid_token(settings, code) -> None:
    c, _ = client(settings, routed({"getMe": fail(code, "Unauthorized" if code == 401 else "Not Found")}))
    with pytest.raises(errors.AuthenticationError) as exc:
        c.get_me()
    assert_no_secrets(str(exc.value) + str(exc.value.hint))


def test_network_error_does_not_leak_token(settings) -> None:
    leaky = requests.exceptions.ConnectionError(
        f"HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries exceeded with url: /bot{FAKE_TOKEN}/getMe"
    )
    c, _ = client(settings, raise_(leaky))
    with pytest.raises(errors.NetworkError) as exc:
        c.get_me()
    assert not isinstance(exc.value, errors.AuthenticationError)
    assert_no_secrets(str(exc.value))
    assert exc.value.__cause__ is None


def test_webhook_blocks_get_updates_without_changing_it(settings) -> None:
    c, session = client(settings, routed({"getWebhookInfo": ok({"url": "https://eksisterende.example.com/hook?secret=x"})}))
    with pytest.raises(errors.WebhookActiveError) as exc:
        c.get_updates()
    assert exc.value.webhook_host == "eksisterende.example.com"
    assert "secret=x" not in str(exc.value)
    assert session.methods() == ["getWebhookInfo"]  # hverken getUpdates eller deleteWebhook kaldt


def test_get_updates_conflict(settings) -> None:
    c, _ = client(settings, routed({
        "getWebhookInfo": ok({"url": ""}),
        "getUpdates": fail(409, "Conflict: terminated by other getUpdates request"),
    }))
    with pytest.raises(errors.UnexpectedResponseError, match="andet program"):
        c.get_updates()


def test_get_updates_does_not_acknowledge(settings) -> None:
    c, session = client(settings, routed({"getWebhookInfo": ok({"url": ""}), "getUpdates": ok([])}))
    assert c.get_updates() == []
    assert "offset" not in session.calls[-1][2]["json"]


def test_find_private_chats_lists_all_candidates_and_skips_groups() -> None:
    updates = [
        private_update(1, 111, "Anna", "hej", 1_700_000_000, "anna"),
        {"update_id": 2, "message": {"chat": {"id": -100, "type": "group", "title": "Gruppe"}, "date": 1_700_000_001, "text": "x"}},
        private_update(3, 222, "Bo", "CVR Radar opsætning", 1_700_000_100),
        private_update(4, 111, "Anna", "igen", 1_700_000_200, "anna"),
    ]
    candidates = find_private_chats(updates)
    assert [c.chat_id for c in candidates] == [111, 222]
    anna = candidates[0]
    assert (anna.last_text, anna.message_count, anna.display_name) == ("igen", 2, "Anna (@anna)")


def test_send_message_once_and_accepted(settings) -> None:
    sent = {"message_id": 77, "chat": {"id": 987654321, "type": "private"}, "date": 1_700_000_000, "text": "x"}
    c, session = client(settings, routed({"sendMessage": ok(sent)}))
    result = c.send_message("987654321", build_test_message())
    assert result.message_id == 77
    assert session.methods() == ["sendMessage"]
    assert TEST_MESSAGE in session.calls[0][2]["json"]["text"]
    assert session.calls[0][2]["json"]["text"].startswith("[TEST]")


def test_send_timeout_is_not_retried(settings) -> None:
    c, session = client(settings, raise_(requests.exceptions.ReadTimeout("read timed out")))
    with pytest.raises(errors.TimeoutError_) as exc:
        c.send_message("987654321", "x")
    assert len(session.calls) == 1
    assert "leveret" in str(exc.value)


@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        (fail(403, "Forbidden: bot was blocked by the user"), errors.RecipientBlockedError),
        (fail(403, "Forbidden: bot can't initiate conversation with a user"), errors.RecipientBlockedError),
        (fail(400, "Bad Request: chat not found"), errors.ChatNotFoundError),
        (fail(429, "Too Many Requests: retry after 12", parameters={"retry_after": 12}), errors.RateLimitedError),
        (fail(502, "Bad Gateway"), errors.ServerError),
        (make_response(500, raw_text="<html>"), errors.ServerError),
    ],
)
def test_send_errors(settings, response, error_type) -> None:
    c, session = client(settings, routed({"sendMessage": response}))
    with pytest.raises(error_type) as exc:
        c.send_message("987654321", "x")
    assert len(session.calls) == 1
    assert_no_secrets(str(exc.value))
    if error_type is errors.RateLimitedError:
        assert exc.value.retry_after == 12
