"""Klient til Telegrams officielle Bot API: https://core.telegram.org/bots/api

Tokenet indgår i URL'en, så URL'en vises eller logges aldrig. Fejltekster sendes
gennem `redact()` via fejltyperne i `errors.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from .config import Settings
from .errors import (
    AuthenticationError,
    ChatNotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    RecipientBlockedError,
    ServerError,
    TimeoutError_,
    UnexpectedResponseError,
    WebhookActiveError,
)
from .http import new_session, send

SERVICE = "Telegram (api.telegram.org)"
API_BASE = "https://api.telegram.org"
TEST_MESSAGE = "CVR Radar: Telegram-forbindelsen virker."


@dataclass(frozen=True)
class BotInfo:
    id: int
    username: str
    first_name: str


@dataclass(frozen=True)
class SentMessage:
    message_id: int
    chat_id: int
    date: datetime


@dataclass
class ChatCandidate:
    chat_id: int
    first_name: str
    last_name: str
    username: str
    last_text: str
    last_date: datetime
    message_count: int

    @property
    def display_name(self) -> str:
        name = " ".join(p for p in (self.first_name, self.last_name) if p) or "(uden navn)"
        return f"{name} (@{self.username})" if self.username else name


def build_test_message(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return (
        f"[TEST] {TEST_MESSAGE}\n"
        f"Sendt {now:%Y-%m-%d %H:%M} UTC. Dette er ikke en virksomhedsnotifikation."
    )


class TelegramClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        settings.require_telegram_token()
        self._settings = settings
        self._session = session or new_session()

    def _call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        url = f"{API_BASE}/bot{self._settings.telegram_bot_token}/{method}"
        response = send(
            self._session,
            "POST",
            url,
            service=SERVICE,
            timeout=self._settings.http_timeout,
            json=payload or {},
        )
        try:
            data = response.json()
        except ValueError:
            data = None
        if isinstance(data, dict) and data.get("ok") is True:
            return data.get("result")
        _raise_api_error(method, response.status_code, data if isinstance(data, dict) else {})
        return None  # pragma: no cover

    # --- Opslag --------------------------------------------------------------

    def get_me(self) -> BotInfo:
        result = self._call("getMe")
        return BotInfo(id=int(result["id"]), username=result.get("username", ""), first_name=result.get("first_name", ""))

    def get_webhook_info(self) -> dict[str, Any]:
        return self._call("getWebhookInfo") or {}

    def get_updates(self) -> list[dict[str, Any]]:
        """Hent ventende opdateringer uden `offset`, så de ikke markeres som læst."""
        webhook = self.get_webhook_info()
        if webhook.get("url"):
            raise webhook_error(webhook)
        return self._call("getUpdates", {"limit": 100, "timeout": 0, "allowed_updates": ["message"]}) or []

    def get_chat(self, chat_id: str | int) -> dict[str, Any]:
        return self._call("getChat", {"chat_id": chat_id}) or {}

    # --- Afsendelse ----------------------------------------------------------

    def send_message(self, chat_id: str | int, text: str) -> SentMessage:
        """Send én besked. Gentages aldrig automatisk, så der ikke opstår dubletter."""
        try:
            result = self._call(
                "sendMessage",
                {"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            )
        except TimeoutError_ as err:
            raise TimeoutError_(
                f"{err.message} Beskeden kan alligevel være leveret.",
                hint="Send ikke igen automatisk. Se efter på telefonen før et nyt forsøg.",
            ) from None
        return SentMessage(
            message_id=int(result["message_id"]),
            chat_id=int(result["chat"]["id"]),
            date=datetime.fromtimestamp(int(result["date"]), tz=timezone.utc),
        )


def find_private_chats(updates: list[dict[str, Any]]) -> list[ChatCandidate]:
    """Saml private chats fra opdateringer. Grupper og kanaler udelades. Vælger ingen automatisk."""
    candidates: dict[int, ChatCandidate] = {}
    for update in updates:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        if chat.get("type") != "private" or "id" not in chat:
            continue
        chat_id = int(chat["id"])
        date = datetime.fromtimestamp(int(message.get("date", 0)), tz=timezone.utc)
        text = str(message.get("text") or "(ikke-tekst-besked)")
        existing = candidates.get(chat_id)
        if existing is None:
            candidates[chat_id] = ChatCandidate(
                chat_id=chat_id,
                first_name=str(chat.get("first_name", "")),
                last_name=str(chat.get("last_name", "")),
                username=str(chat.get("username", "")),
                last_text=text,
                last_date=date,
                message_count=1,
            )
        else:
            existing.message_count += 1
            if date >= existing.last_date:
                existing.last_text = text
                existing.last_date = date
    return sorted(candidates.values(), key=lambda c: c.last_date, reverse=True)


def webhook_error(webhook: dict[str, Any]) -> WebhookActiveError:
    host = urlparse(str(webhook.get("url", ""))).hostname or "ukendt vært"
    return WebhookActiveError(
        f"Botten har en aktiv webhook til {host}, så Telegram udleverer ikke beskeder via getUpdates.",
        webhook_host=host,
        hint=(
            "CVR Radar ændrer ikke den eksisterende integration. Brug en separat bot til CVR Radar, "
            "eller fjern selv webhooken (deleteWebhook), hvis du er sikker på, at den ikke bruges."
        ),
    )


def _raise_api_error(method: str, status: int, data: dict[str, Any]) -> None:
    code = int(data.get("error_code") or status)
    description = str(data.get("description") or f"HTTP {status}")
    lowered = description.lower()

    if code == 401 or (code == 404 and method in {"getMe", "getWebhookInfo"}):
        raise AuthenticationError(
            f"Telegram afviste bot-tokenet ({code}: {description}).",
            hint="Kontrollér TELEGRAM_BOT_TOKEN. Hent eventuelt et nyt med /token hos @BotFather.",
        )
    if code == 403:
        if "blocked" in lowered or "can't initiate" in lowered or "deactivated" in lowered:
            raise RecipientBlockedError(
                f"Telegram kan ikke levere til modtageren ({description}).",
                hint="Åbn chatten med botten i Telegram og tryk Start (eller fjern blokeringen).",
            )
        raise PermissionDeniedError(f"Telegram nægtede handlingen ({description}).")
    if code == 400 and "chat not found" in lowered:
        raise ChatNotFoundError(
            "Telegram kender ikke dette chat-ID for botten (chat not found).",
            hint="Kontrollér TELEGRAM_CHAT_ID, og at du har trykket Start i chatten med botten.",
        )
    if code == 409:
        if "webhook" in lowered:
            raise WebhookActiveError(
                "Botten har en aktiv webhook, så getUpdates kan ikke bruges.",
                hint="CVR Radar ændrer ikke webhooken automatisk. Se README.md.",
            )
        raise UnexpectedResponseError(
            "Et andet program henter allerede beskeder fra denne bot (getUpdates-konflikt).",
            hint="Stop det andet program, eller brug en separat bot til CVR Radar.",
        )
    if code == 429:
        retry_after = (data.get("parameters") or {}).get("retry_after")
        raise RateLimitedError(
            "Telegram begrænser forespørgsler (429)."
            + (f" Vent {retry_after} sekunder." if retry_after is not None else ""),
            retry_after=float(retry_after) if retry_after is not None else None,
        )
    if code >= 500:
        raise ServerError(f"Telegram-serveren svarede med fejl ({code}). Prøv igen senere.")
    raise UnexpectedResponseError(f"Telegram afviste {method} ({code}: {description}).")
