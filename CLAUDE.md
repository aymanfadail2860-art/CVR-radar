# CLAUDE.md – retningslinjer for CVR Radar

## Projekt
Overvågning af nyregistrerede danske virksomheder via Erhvervsstyrelsens CVR-Elasticsearch
(system-til-system) med Telegram-notifikationer. Brugeren skriver på dansk, og
dokumentation og brugervendte meddelelser skrives på dansk. Status og roadmap står i
`STATUS.md`.

## Opbygning
- `src/cvr_radar/config.py`: `Settings`, indlæsning fra miljø/`.env`, validering og `describe()`.
- `src/cvr_radar/redact.py`: maskering af hemmeligheder og logging-filter.
- `src/cvr_radar/errors.py`: én fejltype pr. årsag (login, rettigheder, 429, 5xx, timeout, netværk, certifikat).
- `src/cvr_radar/http.py`: fælles `send()`, der oversætter requests-fejl og afviser ikke-HTTPS.
- `src/cvr_radar/cvr_client.py`: CVR-opslag (`CvrClient`).
- `src/cvr_radar/telegram_client.py`: Bot API (`TelegramClient`, `find_private_chats`).
- `src/cvr_radar/cli.py`: kommandoer (`cvr-radar <kommando>`).

## Kommandoer
- Opsætning: `scripts/setup.sh` (opretter `.venv`). Kør den i starten af en ny cloud-session.
- Tests: `.venv/bin/pytest`
- CLI: `.venv/bin/cvr-radar --help`

## Faste regler
- Bed aldrig brugeren om at indsætte adgangskoder eller tokens i chatten. Udskriv aldrig
  værdierne af `CVR_PASSWORD`, `CVR_USERNAME` eller `TELEGRAM_BOT_TOKEN` (heller ikke via
  `env`, `printenv` eller `echo`). Brug `cvr-radar check-config`.
- Al brugervendt tekst skal gå gennem `redact()`. Telegram-tokenet indgår i URL'en, så
  URL'er og rå undtagelsestekster vises aldrig. Brug `raise ... from None`.
- Kun HTTPS. Slå aldrig certifikatkontrol fra (`verify=False`), og fald aldrig tilbage til HTTP.
- En netværksfejl må aldrig beskrives som forkert login. Kun HTTP 401 betyder forkert login.
- Tests må aldrig lave rigtige netværkskald (`conftest.py` blokerer dem). Brug `FakeSession`.
- Send aldrig rigtige Telegram-beskeder uden brugerens udtrykkelige ønske. `telegram-test`
  sender kun med `--send`, og afsendelse gentages aldrig automatisk.
- Ændr aldrig en eksisterende Telegram-webhook automatisk.
- Ingen AI-modelkald i overvågningen. Det skal være almindelig programkode.
- Antag ikke, at en bestemt forespørgselsfrekvens mod CVR er godkendt. Hold forespørgsler
  små (`size`, `_source`).
- Hold afhængighederne få. Tilføj kun en ny pakke, hvis den sparer væsentlig kode.

## Cloudmiljø
CVR-login kommer fra en netværkshemmelighed (Basic, `distribution.virk.dk`). Kør derfor med
`CVR_AUTH_MODE=proxy`. I den tilstand må koden aldrig selv sætte `Authorization`, kræve
`CVR_USERNAME`/`CVR_PASSWORD` eller sende dummy-login (se `ProxyInjectedAuth`). Tilstanden
`basic` skal bevares til serverdrift.

Status 2026-10-19: Proxyen svarer `502 upstream request failed` for alle
`https://distribution.virk.dk`-adresser. Erhvervsstyrelsens eksempler bruger `http://`. Skift
ikke til HTTP, til en anden port eller til en tredjepartstjeneste uden en officiel
HTTPS-adresse fra Erhvervsstyrelsen.

Netværket kræver, at `distribution.virk.dk` og `api.telegram.org` står under
**Allowed domains**. Ellers giver kommandoerne `NetworkError` (proxy 403), og det er ikke
en loginfejl.
