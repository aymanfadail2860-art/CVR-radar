# CVR Radar

CVR Radar skal opdage relevante, nyregistrerede danske virksomheder via Erhvervsstyrelsens
CVR-data (system-til-system-adgang, Elasticsearch) og sende hurtige Telegram-notifikationer.
Målet er lavest mulig forsinkelse **inden for CVR's vilkår**. Et eventuelt forspring i forhold
til f.eks. Lasso skal måles senere.

Overvågningen udføres med almindelig programkode. Der bruges ingen AI-modelkald pr. opslag
eller pr. besked.

**Status:** Milepæl 1 (opsætning og forbindelsestest). Se [STATUS.md](STATUS.md).

---

## Hvor kører projektet?

Projektet udvikles lige nu i en **Claude Code cloud-session** (claude.ai/code). Du behøver ikke
en lokal terminal: Claude kører kommandoerne i sessionen. Du skal selv:

1. sætte adgangsoplysninger og netværksadgang i miljøets indstillinger (se nedenfor), og
2. udføre handlingerne i Telegram (BotFather, Start, testbesked).

Senere skal programmet køre døgnet rundt på en server. Til det er der en lokal opsætning med
skjult indtastning (`cvr-radar setup-local`).

## Installation

Kræver Python 3.11 eller nyere (udviklet og testet med 3.12). Den eneste afhængighed under
kørsel er `requests`. `pytest` bruges kun til tests.

```bash
scripts/setup.sh                 # opretter .venv og installerer projektet
.venv/bin/cvr-radar --help
```

## Kommandoer

| Kommando | Hvad den gør | Netværk |
|---|---|---|
| `cvr-radar check-config` | Viser hvilke indstillinger der er sat. Hemmeligheder vises aldrig. | Nej |
| `cvr-radar cvr-test [--cvr 10150817]` | Slår ét CVR-nummer op og viser CVR-nummer og navn. | CVR |
| `cvr-radar telegram-check` | Kontrollerer bot-tokenet med `getMe` og viser, om der er en webhook. | Telegram |
| `cvr-radar telegram-find-chat [--match TEKST]` | Viser **alle** private chats, der har skrevet til botten. Vælger ikke selv nogen. | Telegram |
| `cvr-radar telegram-test` | Viser modtageren (`getChat`) og testbeskeden uden at sende den. | Telegram |
| `cvr-radar telegram-test --send` | Sender **præcis én** testbesked. Prøver ikke igen automatisk. | Telegram |
| `cvr-radar setup-local` | Kun på en lokal maskine eller server: skriver `.env` (rettigheder 600) med skjult indtastning. | Nej |

Afslutningskoder: `0` = OK, `1` = fejl fra tjeneste eller netværk, `3` = konfigurationsfejl.

## Adgangsoplysninger

Programmet læser fire miljøvariabler:

| Variabel | Indhold |
|---|---|
| `CVR_USERNAME` | Brugernavn til CVR's system-til-system-adgang |
| `CVR_PASSWORD` | Adgangskode til samme |
| `TELEGRAM_BOT_TOKEN` | Token fra @BotFather |
| `TELEGRAM_CHAT_ID` | ID på din private chat med botten (findes med `telegram-find-chat`) |

Valgfrie: `CVR_AUTH_MODE` (`basic` eller `proxy`, standard `basic`, se nedenfor), `CVR_BASE_URL` (standard `https://distribution.virk.dk`, kun `https://` tilladt),
`CVR_INDEX` (standard `cvr-permanent/virksomhed`), `HTTP_TIMEOUT_SECONDS` (standard 20).

**Indsæt aldrig adgangskoder eller tokens i chatten med Claude.**

### CVR-loginmåder (`CVR_AUTH_MODE`)

| Tilstand | Hvem sender Basic-login? | Kræver `CVR_USERNAME`/`CVR_PASSWORD` | Bruges til |
|---|---|---|---|
| `basic` (standard) | Programmet selv | Ja | Senere serverdrift |
| `proxy` | Cloudmiljøets netværksproxy (netværkshemmelighed af typen Basic for `distribution.virk.dk`) | Nej. Værdierne ignoreres, hvis de er sat. | Claude Code cloud |

I `proxy`-tilstand sætter programmet aldrig selv en `Authorization`-header. Det henter heller
ikke login fra `~/.netrc` og sender intet dummy-login. HTTPS, certifikatkontrol, den
almindelige proxyopsætning (`HTTPS_PROXY`) og forbuddet mod omdirigeringer gælder uændret.
`check-config` viser tilstanden, men CVR-adgangen er først verificeret, når `cvr-test` er
lykkedes.

### A. Claude Code cloud (nuværende miljø)

**Anbefalet: netværkshemmelighed.** Under **Network secrets** i **Edit cloud environment**
tilføjer du en hemmelighed af typen Basic med tilladt websted `distribution.virk.dk`.
Brugernavn og adgangskode gemmes i hemmeligheden, ikke i miljøvariabler. Sessionen kan ikke
se dem. Tilføj derefter kun `CVR_AUTH_MODE=proxy` under **Environment variables**, eller sæt
den foran kommandoen: `CVR_AUTH_MODE=proxy cvr-radar cvr-test`.

**Alternativ: miljøvariabler** (tilstand `basic`). Trin 3 nedenfor gælder kun, hvis du ikke
bruger en netværkshemmelighed.

1. Åbn sessionen på claude.ai/code. Vælg pilen efter sessionens titel øverst og derefter
   **Edit cloud environment**.
2. **Network access:** vælg **Custom**. Skriv én vært pr. linje under **Allowed domains**:
   ```
   distribution.virk.dk
   api.telegram.org
   ```
   Lad **Also include default list of common package managers** være slået til. Ændringen
   virker i kørende sessioner efter cirka et minut.
3. **Environment variables** (`.env`-format, én `NAVN=værdi` pr. linje):
   ```
   CVR_USERNAME=dit-brugernavn
   CVR_PASSWORD='din-adgangskode'
   TELEGRAM_BOT_TOKEN='123456789:ABC...'
   TELEGRAM_CHAT_ID=
   ```
   Sæt adgangskoden i enkelte citationstegn, hvis den indeholder `#` eller mellemrum. Ellers
   tolkes `#` som starten på en kommentar. Gem med **Save changes**.
4. Nye variabler læses, når sessionen starter, eller når den genoptages efter at have været
   inaktiv. Bed derefter Claude om at køre `check-config`. Står variablerne stadig som
   `mangler`, så start en ny session på denne branch.

> Bemærk: Alle, der bruger miljøet, kan læse miljøvariablerne, også Claude i sessionen.
> Programmet viser dem aldrig. Brug et personligt miljø, som ikke deles.

### B. Lokal maskine eller server (senere)

```bash
.venv/bin/cvr-radar setup-local      # spørger efter værdierne; adgangskode og token vises ikke
.venv/bin/cvr-radar check-config
```

`.env` er udelukket fra Git (`.gitignore`). `.env.example` viser formatet med tomme værdier.
Miljøvariabler har altid forrang for `.env`.

## Telegram: opret bot og find din chat

1. Har du ikke en bot endnu, så åbn [@BotFather](https://t.me/BotFather) i Telegram og send
   `/newbot`.
2. Vælg et **navn**, f.eks. `CVR Radar`. Vælg derefter et **brugernavn**, der slutter på
   `bot`, f.eks. `cvr_radar_dit_navn_bot`.
3. BotFather svarer med et token. Gem det som `TELEGRAM_BOT_TOKEN` i miljøets indstillinger
   (se ovenfor). Del det ikke med andre.
4. Åbn chatten med din nye bot (linket i BotFathers svar) og tryk **Start**.
5. Send derefter en besked til botten med et ord, kun du kender, f.eks.
   `CVR Radar opsætning blåbær`.
6. Kør `cvr-radar telegram-find-chat --match blåbær`. Kontrollér navn, brugernavn og
   beskedtekst. Er det din besked, så gem chat-ID'et som `TELEGRAM_CHAT_ID`.
7. Kør `cvr-radar telegram-test`. Kontrollér den viste modtager, og kør derefter
   `cvr-radar telegram-test --send`.
8. Programmet skelner mellem to ting:
   - **Accepteret af Telegram:** programmet har fået et `message_id` tilbage.
   - **Modtaget:** du har selv set beskeden på telefonen. Det skal du bekræfte.

**Webhook:** Har botten allerede en webhook, fordi den bruges af en anden integration, kan
Telegram ikke udlevere beskeder via `getUpdates`. CVR Radar ændrer **ikke** webhooken. Du kan
bruge en separat bot til CVR Radar, eller selv fjerne webhooken, hvis du er sikker på, at den
ikke bruges.

Telegram gemmer kun ventende beskeder i 24 timer. Skriv derfor til botten kort før
`telegram-find-chat`.

## CVR-forbindelsen

- Endpoint: `POST https://distribution.virk.dk/cvr-permanent/virksomhed/_search` med
  HTTP Basic-login. Se [Erhvervsstyrelsens vejledning](https://erhvervsstyrelsen.dk/kom-godt-igang-med-elasticSearch).
- Testopslaget bruger Erhvervsstyrelsens CVR-nummer 10150817. Forespørgslen er
  `term` på `Vrvirksomhed.cvrNummer` med `size: 1` og begrænset `_source`.
- Erhvervsstyrelsen advarer om, at ineffektive forespørgsler kan føre til midlertidig
  lukning af adgangen. Der er **ikke** antaget nogen godkendt forespørgselsfrekvens.

Fejl håndteres hver for sig:

| Situation | Meddelelse |
|---|---|
| HTTP 401 | Forkert brugernavn eller adgangskode |
| HTTP 403 | Manglende rettigheder |
| HTTP 429 | Begrænsning af forespørgsler (respekterer `Retry-After`) |
| HTTP 5xx | Serverfejl |
| HTTP 502 `upstream request failed` fra cloudproxyen | Netværksfejl. CVR har ikke svaret. |
| Timeout | Timeout. Siger intet om login. |
| DNS/proxy/firewall | Netværksfejl, *ikke et loginproblem* |
| Certifikatfejl | Afbrydes. Certifikatkontrollen slås aldrig fra. |

## Sikkerhed

- Kun HTTPS med normal certifikatkontrol. Redirects følges ikke.
- Adgangskode, brugernavn og bot-token maskeres i al output og logning. Det gælder også
  tokenet i Telegram-URL'er og `Authorization`-headere.
- Fejl vises uden traceback, og de oprindelige undtagelser kædes ikke på.
- Automatiserede tests bruger simulerede svar. Et rigtigt netværkskald får testen til at fejle.

## Tests

```bash
.venv/bin/pytest
```

## Næste milepæle

Se [STATUS.md](STATUS.md).
