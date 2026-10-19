"""Fjernelse af hemmeligheder fra tekst, før den vises eller logges.

Telegram-tokenet indgår i selve API-adressen (https://api.telegram.org/bot<TOKEN>/...),
så enhver fejltekst fra requests/urllib3 kan indeholde det. Derfor sendes al tekst,
der kan stamme fra et netværkskald, gennem `redact()` før den vises.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

MASK = "***"

# Telegram bot-token: <bot-id>:<35+ tegn>. Matches også uden "bot"-præfiks.
_TELEGRAM_TOKEN_RE = re.compile(r"\d{5,}:[A-Za-z0-9_-]{20,}")
# Authorization-headere (Basic/Bearer) og brugerinfo i URL'er.
_AUTH_HEADER_RE = re.compile(r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?)(basic|bearer)\s+[^\s'\",}]+")
_URL_USERINFO_RE = re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@")

_known_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Registrér en konkret hemmelig værdi, så den altid maskeres."""
    if value and len(value) >= 4:
        _known_secrets.add(value)


def register_secrets(values: Iterable[str | None]) -> None:
    for value in values:
        register_secret(value)


def redact(text: object) -> str:
    """Returnér `text` som streng med alle kendte og genkendelige hemmeligheder maskeret."""
    result = str(text)
    # Længste først, så en hemmelighed der indeholder en anden maskeres helt.
    for secret in sorted(_known_secrets, key=len, reverse=True):
        result = result.replace(secret, MASK)
    result = _TELEGRAM_TOKEN_RE.sub(MASK, result)
    result = _AUTH_HEADER_RE.sub(lambda m: f"{m.group(1)}{m.group(2)} {MASK}", result)
    result = _URL_USERINFO_RE.sub(lambda m: f"{m.group(1)}{MASK}@", result)
    return result


class RedactingFilter(logging.Filter):
    """Logging-filter der maskerer hemmeligheder i alle logbeskeder."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


def configure_logging(level: int = logging.WARNING) -> None:
    """Opsæt logning med maskering. urllib3 holdes på WARNING, da DEBUG logger fulde URL'er."""
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
