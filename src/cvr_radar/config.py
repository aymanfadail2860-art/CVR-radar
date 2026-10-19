"""Konfiguration fra miljøvariabler, eventuelt suppleret af en lokal `.env`-fil.

Miljøvariabler har altid forrang. `.env` bruges kun til variabler, der ikke allerede
er sat, og filen må aldrig lægges i Git.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .errors import ConfigError
from .redact import register_secrets

DEFAULT_CVR_BASE_URL = "https://distribution.virk.dk"
# Erhvervsstyrelsens tjeneste svarer kun på HTTP. HTTP tillades kun til denne vært,
# kun på port 80 og kun når CVR_ALLOW_HTTP=true er sat bevidst (login sendes ukrypteret).
CVR_HTTP_HOST = "distribution.virk.dk"
CVR_HTTP_BASE_URL = f"http://{CVR_HTTP_HOST}"
_TRUE_VALUES = ("1", "true", "ja", "yes")
_FALSE_VALUES = ("", "0", "false", "nej", "no")
DEFAULT_CVR_INDEX = "cvr-permanent/virksomhed"
DEFAULT_TIMEOUT_SECONDS = 20.0

# basic: programmet sender selv HTTP Basic-login (serverdrift).
# proxy: miljøets netværksproxy tilføjer Basic-login (Claude Code cloud med netværkshemmelighed).
AUTH_MODE_BASIC = "basic"
AUTH_MODE_PROXY = "proxy"
AUTH_MODES = (AUTH_MODE_BASIC, AUTH_MODE_PROXY)

SECRET_VARS = ("CVR_PASSWORD", "TELEGRAM_BOT_TOKEN")
REQUIRED_VARS = ("CVR_USERNAME", "CVR_PASSWORD", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")

_TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
_CHAT_ID_RE = re.compile(r"^-?\d{1,20}$")
_INDEX_RE = re.compile(r"^[a-z0-9_-]+(/[a-z0-9_-]+)?$")


def parse_env_file(path: Path) -> dict[str, str]:
    """Læs en simpel `.env`-fil: `KEY=value` pr. linje, `#` for kommentarer, valgfri citationstegn."""
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key:
            values[key] = value
    return values


@dataclass(frozen=True)
class Settings:
    cvr_username: str = field(default="", repr=False)
    cvr_password: str = field(default="", repr=False)
    telegram_bot_token: str = field(default="", repr=False)
    telegram_chat_id: str = ""
    cvr_auth_mode: str = AUTH_MODE_BASIC
    cvr_allow_http: bool = False
    cvr_base_url: str = DEFAULT_CVR_BASE_URL
    cvr_index: str = DEFAULT_CVR_INDEX
    http_timeout: float = DEFAULT_TIMEOUT_SECONDS
    env_file: str | None = None

    # --- Krav pr. kommando --------------------------------------------------

    @property
    def cvr_auth_via_proxy(self) -> bool:
        return self.cvr_auth_mode == AUTH_MODE_PROXY

    @property
    def cvr_uses_http(self) -> bool:
        return urlparse(self.cvr_base_url).scheme == "http"

    def require_cvr(self) -> None:
        if self.cvr_auth_via_proxy and self.cvr_allow_http:
            raise ConfigError(
                "CVR_ALLOW_HTTP kan kun bruges med CVR_AUTH_MODE=basic.",
                hint="Cloudmiljøets proxy understøtter ikke HTTP. HTTP er kun til drift på egen maskine eller server.",
            )
        if self.cvr_auth_via_proxy:
            _check_base_url(self.cvr_base_url, allow_http=False)
            return
        missing = [n for n, v in (("CVR_USERNAME", self.cvr_username), ("CVR_PASSWORD", self.cvr_password)) if not v]
        if missing:
            raise ConfigError(
                f"Mangler {', '.join(missing)}.",
                hint="Sæt variablerne i miljøets opsætning (se README.md, afsnittet 'Adgangsoplysninger').",
            )
        _check_base_url(self.cvr_base_url, allow_http=self.cvr_allow_http)

    def require_telegram_token(self) -> None:
        if not self.telegram_bot_token:
            raise ConfigError("Mangler TELEGRAM_BOT_TOKEN.", hint="Opret en bot hos @BotFather (se README.md).")
        if not _TOKEN_RE.match(self.telegram_bot_token):
            raise ConfigError(
                "TELEGRAM_BOT_TOKEN har ikke det forventede format (<tal>:<tegn>).",
                hint="Kopiér tokenet fra BotFather igen, uden mellemrum eller citationstegn.",
            )

    def require_chat_id(self) -> None:
        if not self.telegram_chat_id:
            raise ConfigError(
                "Mangler TELEGRAM_CHAT_ID.",
                hint="Kør 'cvr-radar telegram-find-chat' og gem det bekræftede chat-ID.",
            )
        if not _CHAT_ID_RE.match(self.telegram_chat_id):
            raise ConfigError("TELEGRAM_CHAT_ID skal være et heltal, f.eks. 123456789.")

    # --- Oversigt uden hemmeligheder ----------------------------------------

    def describe(self) -> list[tuple[str, bool, str]]:
        """Returnér (navn, ok, beskrivelse) for hver indstilling. Hemmeligheder vises aldrig."""
        rows: list[tuple[str, bool, str]] = []
        if self.cvr_auth_via_proxy:
            rows.append((
                "CVR_AUTH_MODE", True,
                "proxy: miljøets netværksproxy skal tilføje Basic-login (ikke verificeret før et vellykket cvr-test)",
            ))
            for name, value in (("CVR_USERNAME", self.cvr_username), ("CVR_PASSWORD", self.cvr_password)):
                rows.append((name, True, "sat, men ignoreres i proxytilstand" if value else "ikke påkrævet i proxytilstand"))
            has_proxy = bool(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))
            rows.append((
                "HTTPS_PROXY", has_proxy,
                "sat (miljøets netværksproxy)" if has_proxy else "ikke sat: proxytilstand kræver miljøets netværksproxy",
            ))
        else:
            rows.append(("CVR_AUTH_MODE", True, "basic: programmet sender selv Basic-login"))
            rows.append(("CVR_USERNAME", bool(self.cvr_username), "sat" if self.cvr_username else "mangler"))
            rows.append(("CVR_PASSWORD", bool(self.cvr_password), "sat (skjult)" if self.cvr_password else "mangler"))

        if not self.telegram_bot_token:
            rows.append(("TELEGRAM_BOT_TOKEN", False, "mangler"))
        elif _TOKEN_RE.match(self.telegram_bot_token):
            rows.append(("TELEGRAM_BOT_TOKEN", True, "sat (skjult), format ser rigtigt ud"))
        else:
            rows.append(("TELEGRAM_BOT_TOKEN", False, "sat (skjult), men formatet er forkert"))

        if not self.telegram_chat_id:
            rows.append(("TELEGRAM_CHAT_ID", False, "mangler (find det med 'telegram-find-chat')"))
        elif _CHAT_ID_RE.match(self.telegram_chat_id):
            rows.append(("TELEGRAM_CHAT_ID", True, f"sat: {self.telegram_chat_id}"))
        else:
            rows.append(("TELEGRAM_CHAT_ID", False, "sat, men er ikke et heltal"))

        if self.cvr_allow_http and self.cvr_auth_via_proxy:
            rows.append(("CVR_ALLOW_HTTP", False, "true, men kan ikke bruges med CVR_AUTH_MODE=proxy"))
        elif self.cvr_allow_http:
            rows.append(("CVR_ALLOW_HTTP", True, f"true: ADVARSEL, HTTP til {CVR_HTTP_HOST} er tilladt, og login sendes ukrypteret"))
        else:
            rows.append(("CVR_ALLOW_HTTP", True, "false: kun HTTPS"))
        try:
            _check_base_url(self.cvr_base_url, allow_http=self.cvr_allow_http and not self.cvr_auth_via_proxy)
            note = " (UKRYPTERET)" if self.cvr_uses_http else ""
            rows.append(("CVR_BASE_URL", True, self.cvr_base_url + note))
        except ConfigError as err:
            rows.append(("CVR_BASE_URL", False, str(err)))
        rows.append(("CVR_INDEX", bool(_INDEX_RE.match(self.cvr_index)), self.cvr_index))
        rows.append(("HTTP_TIMEOUT_SECONDS", True, f"{self.http_timeout:g} sekunder"))
        return rows


def _check_base_url(url: str, *, allow_http: bool) -> None:
    parsed = urlparse(url)
    if not parsed.hostname or parsed.scheme not in ("https", "http"):
        raise ConfigError("CVR_BASE_URL skal være en https://-adresse.")
    if parsed.scheme == "http":
        if not allow_http:
            raise ConfigError(
                "CVR_BASE_URL skal være en https://-adresse. Ukrypteret HTTP er ikke tilladt.",
                hint=f"HTTP til {CVR_HTTP_HOST} kræver CVR_ALLOW_HTTP=true (se README.md).",
            )
        if parsed.hostname != CVR_HTTP_HOST or parsed.port not in (None, 80):
            raise ConfigError(f"HTTP er kun tilladt til {CVR_HTTP_BASE_URL} (port 80).")
    if parsed.username or parsed.password:
        raise ConfigError("CVR_BASE_URL må ikke indeholde brugernavn eller adgangskode.")


def load_settings(env: dict[str, str] | None = None, env_file: Path | None = None) -> Settings:
    """Byg `Settings` fra miljøet. `env`/`env_file` kan angives i tests."""
    source = dict(os.environ if env is None else env)
    if env_file is None:
        env_file = Path(source.get("CVR_RADAR_ENV_FILE", ".env"))
    used_file: str | None = None
    if env_file.is_file():
        for key, value in parse_env_file(env_file).items():
            if not source.get(key):
                source[key] = value
        used_file = str(env_file)

    def get(name: str, default: str = "") -> str:
        return (source.get(name) or default).strip()

    timeout_raw = get("HTTP_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
    try:
        timeout = float(timeout_raw)
        if not 1 <= timeout <= 120:
            raise ValueError
    except ValueError:
        raise ConfigError("HTTP_TIMEOUT_SECONDS skal være et tal mellem 1 og 120.") from None

    auth_mode = get("CVR_AUTH_MODE", AUTH_MODE_BASIC).lower()
    if auth_mode not in AUTH_MODES:
        raise ConfigError("CVR_AUTH_MODE skal være 'basic' eller 'proxy'.")

    allow_http_raw = get("CVR_ALLOW_HTTP").lower()
    if allow_http_raw not in _TRUE_VALUES + _FALSE_VALUES:
        raise ConfigError("CVR_ALLOW_HTTP skal være 'true' eller 'false'.")
    allow_http = allow_http_raw in _TRUE_VALUES
    default_base_url = CVR_HTTP_BASE_URL if allow_http and auth_mode == AUTH_MODE_BASIC else DEFAULT_CVR_BASE_URL

    settings = Settings(
        cvr_username=get("CVR_USERNAME"),
        cvr_password=source.get("CVR_PASSWORD", "") or "",  # adgangskoder trimmes ikke
        telegram_bot_token=get("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=get("TELEGRAM_CHAT_ID"),
        cvr_auth_mode=auth_mode,
        cvr_allow_http=allow_http,
        cvr_base_url=get("CVR_BASE_URL", default_base_url).rstrip("/"),
        cvr_index=get("CVR_INDEX", DEFAULT_CVR_INDEX).strip("/"),
        http_timeout=timeout,
        env_file=used_file,
    )
    register_secrets([settings.cvr_username, settings.cvr_password, settings.telegram_bot_token])
    return settings
