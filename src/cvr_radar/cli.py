"""Kommandolinje: `cvr-radar <kommando>` eller `python -m cvr_radar <kommando>`.

Al tekst går gennem `out()`, som maskerer hemmeligheder, og fejl vises uden traceback.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from . import __version__
from .config import REQUIRED_VARS, SECRET_VARS, Settings, load_settings, parse_env_file
from .cvr_client import ERHVERVSSTYRELSEN_CVR, CvrClient, validate_cvr_number
from .errors import ConfigError, CvrRadarError, WebhookActiveError
from .redact import configure_logging, redact
from .telegram_client import TelegramClient, build_test_message, find_private_chats, webhook_error

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFIG = 3


def out(text: str = "") -> None:
    print(redact(text))


# --- Kommandoer ------------------------------------------------------------------


def cmd_check_config(settings: Settings, args: argparse.Namespace) -> int:
    out("Konfiguration (hemmelige værdier vises aldrig):")
    if settings.env_file:
        out(f"  Lokal fil: {settings.env_file} (miljøvariabler har forrang)")
    all_ok = True
    for name, ok, detail in settings.describe():
        all_ok &= ok
        out(f"  [{'OK' if ok else '--'}] {name}: {detail}")
    out()
    if settings.cvr_auth_via_proxy:
        out("CVR-adgang i proxytilstand er IKKE verificeret, før 'cvr-radar cvr-test' er lykkedes.")
    if all_ok:
        out("Alle indstillinger er udfyldt. Forbindelserne er IKKE afprøvet af denne kommando.")
        return EXIT_OK
    out("Der mangler indstillinger. Se README.md, afsnittet 'Adgangsoplysninger'.")
    return EXIT_CONFIG


def cmd_cvr_test(settings: Settings, args: argparse.Namespace) -> int:
    try:
        cvr_number = validate_cvr_number(args.cvr)
    except ValueError as err:
        raise ConfigError(str(err)) from None
    client = CvrClient(settings)
    mode = "proxy (login tilføjes af netværksproxyen)" if settings.cvr_auth_via_proxy else "basic"
    out(f"Slår CVR-nummer {cvr_number} op via {client.search_url} (login: {mode}) ...")
    company = client.lookup_company(cvr_number)
    out("CVR-forbindelsen virker: autentificeret opslag gennemført.")
    out(f"  CVR-nummer: {company.cvr_number}")
    out(f"  Navn:       {company.name}")
    return EXIT_OK


def cmd_telegram_check(settings: Settings, args: argparse.Namespace) -> int:
    client = TelegramClient(settings)
    bot = client.get_me()
    out("Bot-tokenet virker (getMe).")
    out(f"  Bot: {bot.first_name} (@{bot.username}), id {bot.id}")
    webhook = client.get_webhook_info()
    if webhook.get("url"):
        err = webhook_error(webhook)
        out(f"  Bemærk: {err.message}")
        out(f"  {err.hint}")
    else:
        out("  Ingen webhook er sat; getUpdates kan bruges til at finde din chat.")
    return EXIT_OK


def cmd_telegram_find_chat(settings: Settings, args: argparse.Namespace) -> int:
    client = TelegramClient(settings)
    bot = client.get_me()
    updates = client.get_updates()
    candidates = find_private_chats(updates)
    if args.match:
        needle = args.match.casefold()
        candidates = [c for c in candidates if needle in c.last_text.casefold()]

    if not candidates:
        out(f"Ingen private beskeder til @{bot.username} blev fundet" + (f" med teksten '{args.match}'." if args.match else "."))
        out("Gør sådan:")
        out(f"  1. Åbn https://t.me/{bot.username} i Telegram og tryk Start.")
        out("  2. Send en besked, f.eks. 'CVR Radar opsætning' efterfulgt af et ord, kun du kender.")
        out("  3. Kør kommandoen igen (Telegram gemmer ventende beskeder i op til 24 timer).")
        return EXIT_ERROR

    out(f"Private chats med @{bot.username} (nyeste først). Der er IKKE valgt nogen automatisk:")
    for i, c in enumerate(candidates, 1):
        out(f"  {i}. chat-id {c.chat_id}: {c.display_name}")
        out(f"     seneste besked {c.last_date:%Y-%m-%d %H:%M} UTC: \"{c.last_text[:80]}\" ({c.message_count} i alt)")
    out()
    out("Kontrollér navn, brugernavn og beskedtekst. Kun hvis det er din egen besked:")
    out("gem det tilhørende chat-id som TELEGRAM_CHAT_ID (se README.md).")
    return EXIT_OK


def cmd_telegram_test(settings: Settings, args: argparse.Namespace) -> int:
    settings.require_chat_id()
    client = TelegramClient(settings)
    bot = client.get_me()
    chat = client.get_chat(settings.telegram_chat_id)
    name = " ".join(p for p in (chat.get("first_name"), chat.get("last_name")) if p) or chat.get("title") or "(uden navn)"
    username = f" (@{chat['username']})" if chat.get("username") else ""
    out(f"Modtager: chat-id {settings.telegram_chat_id}, {name}{username}, type {chat.get('type', 'ukendt')}")
    if chat.get("type") != "private":
        out("Advarsel: Modtageren er ikke en privat chat.")
    text = build_test_message()
    if not args.send:
        out("Tørkørsel: der er IKKE sendt noget. Beskeden ville være:")
        for line in text.splitlines():
            out(f"  | {line}")
        out("Kør igen med --send for at sende præcis én testbesked.")
        return EXIT_OK

    sent = client.send_message(settings.telegram_chat_id, text)
    out(f"Telegram har ACCEPTERET testbeskeden fra @{bot.username} (message_id {sent.message_id}, {sent.date:%H:%M:%S} UTC).")
    out("Modtagelsen på din telefon er IKKE bekræftet endnu. Se efter beskeden i Telegram og bekræft selv.")
    out("Kør ikke kommandoen igen, medmindre du vil have endnu en testbesked.")
    return EXIT_OK


def cmd_setup_local(settings: Settings, args: argparse.Namespace) -> int:
    """Skriv en lokal .env med skjult indtastning. Kun til lokal maskine/server, ikke cloud."""
    path = Path(args.env_file)
    existing = parse_env_file(path) if path.is_file() else {}
    if existing:
        out(f"{path} findes allerede. Tryk Enter for at beholde en eksisterende værdi.")
    values: dict[str, str] = {}
    for name in REQUIRED_VARS:
        keep = " [Enter = behold]" if existing.get(name) else ""
        prompt = f"{name}{keep}: "
        value = getpass.getpass(prompt) if name in SECRET_VARS else input(prompt)
        value = value if name in SECRET_VARS else value.strip()
        values[name] = value or existing.get(name, "")
        if "\n" in values[name] or ("'" in values[name] and '"' in values[name]):
            raise ConfigError(f"{name} indeholder tegn, som ikke kan gemmes i .env (linjeskift eller begge typer citationstegn).")
    for key, value in existing.items():
        values.setdefault(key, value)

    lines = ["# CVR Radar lokal konfiguration. Må ALDRIG lægges i Git."]
    for key, value in values.items():
        quote = "'" if "'" not in value else '"'
        lines.append(f"{key}={quote}{value}{quote}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)
    out(f"Gemt i {path} med rettigheder 600. Værdierne er ikke vist. Kør nu 'cvr-radar check-config'.")
    return EXIT_OK


# --- Opsætning af argparse ---------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cvr-radar", description="CVR Radar – opsætning og forbindelsestest.")
    parser.add_argument("--version", action="version", version=f"cvr-radar {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="kommando")

    p = sub.add_parser("check-config", help="Kontrollér opsætningen uden at vise hemmeligheder.")
    p.set_defaults(func=cmd_check_config)

    p = sub.add_parser("cvr-test", help="Slå ét CVR-nummer op (standard: Erhvervsstyrelsen).")
    p.add_argument("--cvr", default=str(ERHVERVSSTYRELSEN_CVR), help="CVR-nummer (8 cifre).")
    p.set_defaults(func=cmd_cvr_test)

    p = sub.add_parser("telegram-check", help="Kontrollér bot-tokenet med getMe.")
    p.set_defaults(func=cmd_telegram_check)

    p = sub.add_parser("telegram-find-chat", help="Vis private chats med botten, så du kan finde dit chat-ID.")
    p.add_argument("--match", help="Vis kun chats hvis seneste besked indeholder denne tekst.")
    p.set_defaults(func=cmd_telegram_find_chat)

    p = sub.add_parser("telegram-test", help="Vis modtager; med --send sendes præcis én testbesked.")
    p.add_argument("--send", action="store_true", help="Send faktisk testbeskeden.")
    p.set_defaults(func=cmd_telegram_test)

    p = sub.add_parser("setup-local", help="Lokal maskine: gem værdier i .env med skjult indtastning.")
    p.add_argument("--env-file", default=".env")
    p.set_defaults(func=cmd_setup_local)
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings()
        return args.func(settings, args)
    except WebhookActiveError as err:
        out(f"STOP: {err}")
        if err.hint:
            out(f"  {err.hint}")
        return EXIT_ERROR
    except ConfigError as err:
        out(f"KONFIGURATIONSFEJL: {err}")
        if err.hint:
            out(f"  {err.hint}")
        return EXIT_CONFIG
    except CvrRadarError as err:
        out(f"FEJL ({type(err).__name__.rstrip('_')}): {err}")
        if err.hint:
            out(f"  {err.hint}")
        return EXIT_ERROR
    except KeyboardInterrupt:
        out("Afbrudt.")
        return EXIT_ERROR
    except Exception as err:  # noqa: BLE001 - sidste værn mod lækage via traceback
        out(f"UVENTET FEJL ({type(err).__name__}): {redact(err)}")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
