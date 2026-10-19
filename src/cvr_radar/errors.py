"""Fejltyper. Hver type svarer til én årsag, så brugeren får den rigtige forklaring.

Alle beskeder sendes gennem `redact()`, og den oprindelige undtagelse kædes ikke på
(`raise ... from None`), så tracebacks ikke kan lække URL'er med Telegram-tokenet.
"""

from __future__ import annotations

from .redact import redact


class CvrRadarError(Exception):
    """Basisfejl. `str(err)` er altid maskeret og egnet til visning."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        self.message = redact(message)
        self.hint = redact(hint) if hint else None
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


class ConfigError(CvrRadarError):
    """Manglende eller ugyldig konfiguration."""


# --- Fælles for HTTP-tjenester ---------------------------------------------------


class ServiceError(CvrRadarError):
    """Fejl fra eller på vej til en ekstern tjeneste."""

    service = "tjenesten"


class AuthenticationError(ServiceError):
    """Tjenesten afviste adgangsoplysningerne (HTTP 401)."""


class PermissionDeniedError(ServiceError):
    """Login accepteret, men adgang til ressourcen nægtet (HTTP 403)."""


class RateLimitedError(ServiceError):
    """For mange forespørgsler (HTTP 429)."""

    def __init__(self, message: str, *, retry_after: float | None = None, hint: str | None = None) -> None:
        super().__init__(message, hint=hint)
        self.retry_after = retry_after


class ServerError(ServiceError):
    """Fejl på tjenestens server (HTTP 5xx)."""


class TimeoutError_(ServiceError):
    """Ingen svar inden for tidsgrænsen. Siger intet om adgangsoplysningerne."""


class NetworkError(ServiceError):
    """Forbindelsen kunne ikke oprettes (DNS, proxy, netværkspolitik). Ikke et loginproblem."""


class CertificateError(NetworkError):
    """TLS-certifikatet kunne ikke verificeres. Certifikatkontrol slås aldrig fra."""


class UnexpectedResponseError(ServiceError):
    """Svar der ikke passer til nogen kendt kategori."""


class NotFoundError(ServiceError):
    """Opslaget gav intet resultat."""


# --- Telegram-specifikke ---------------------------------------------------------


class ChatNotFoundError(ServiceError):
    """Telegram kender ikke chat-ID'et, eller botten har ingen samtale med det."""


class RecipientBlockedError(ServiceError):
    """Brugeren har blokeret botten eller aldrig trykket Start."""


class WebhookActiveError(ServiceError):
    """Botten har en aktiv webhook, så getUpdates ikke kan bruges."""

    def __init__(self, message: str, *, webhook_host: str | None = None, hint: str | None = None) -> None:
        super().__init__(message, hint=hint)
        self.webhook_host = webhook_host
