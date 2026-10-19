# Projektstatus

Opdateret: 2026-10-19

## Milepæl 1: opsætning og forbindelsestest (implementeret)

| Del | Status |
|---|---|
| Python-projekt (`pyproject.toml`, Python ≥ 3.11, kun `requests` under kørsel) | Færdig |
| Konfiguration fra miljøvariabler og valgfri `.env` | Færdig |
| `check-config` uden visning af hemmeligheder | Færdig |
| CVR-klient med opslag på 10150817 og fejlhåndtering | Færdig, men **ikke verificeret mod den rigtige server** |
| Telegram `getMe`, webhook-tjek, find privat chat, én testbesked | Færdig, men **ikke verificeret mod Telegram** |
| Maskering af hemmeligheder i output og logning | Færdig |
| CVR-loginmåde `CVR_AUTH_MODE=proxy` (netværkshemmelighed i cloud) og `basic` (server) | Færdig |
| Automatiserede tests (simulerede svar) | 93 tests består |

### Ikke verificeret endnu

- **CVR (forsøgt 2026-10-19 i proxytilstand):** Netværkshemmeligheden er sat op, og
  forespørgslen når cloudproxyen. Proxyen svarer dog `HTTP 502 upstream request failed`
  efter cirka 6 sekunder. Det gælder både `/cvr-permanent/virksomhed/_search` og forsiden
  `https://distribution.virk.dk/`.
  - Erhvervsstyrelsen har altså ikke svaret, og loginet er ikke afprøvet. Det er hverken
    401, 403 eller en serverfejl hos CVR.
  - Erhvervsstyrelsens officielle eksempler bruger `http://distribution.virk.dk`. Den
    sandsynlige årsag er, at tjenesten ikke svarer på HTTPS/443, eller at den afviser
    cloudmiljøets IP-adresser. Det er ikke bekræftet.
  - CVR Radar skifter ikke til HTTP. Afventer svar fra Erhvervsstyrelsen om en officiel
    HTTPS-adresse.
- **Telegram:** `api.telegram.org` er blokeret, og der er ingen bot-token eller chat-ID.
  Botten er ikke bekræftet.

## Næste milepæle (ikke påbegyndt)

Følgende er bevidst **ikke** med i milepæl 1: fuld registerimport, permanent polling og
masseudsendelse.

1. **Database over kendte CVR-numre** (SQLite først), så programmet kan genkende, hvad det
   allerede har set.
2. **Skelnen mellem nyregistrering, opdatering og genaktivering**, f.eks. ud fra
   stiftelsesdato, `sidstOpdateret` og statusændringer. Kun ægte nyregistreringer giver
   notifikation som standard.
3. **Løbende ændringshentning** med alle resultatsider (scroll/`search_after`) og gemt
   fremskridt, så intet tabes ved genstart. Frekvensen skal afklares med CVR's vilkår eller
   Erhvervsstyrelsen. Den er ikke antaget godkendt.
4. **Holdbar beskedkø** i databasen med status (afventer/sendt/fejlet), genforsøg med
   backoff, respekt for Telegrams `retry_after` og idempotens mod dubletter. En timeout ved
   afsendelse må ikke føre til blind gentagelse.
5. **Filtre** for branche (DB07-koder), geografi (kommune/postnummer) og
   reklamebeskyttelse. Virksomheder med reklamebeskyttelse må ikke bruges til markedsføring.
6. **Serverdrift:** systemd-service, `EnvironmentFile` med rettigheder 600, logrotation,
   overvågning og backup af databasen. Desuden **hastighedsmåling**: tidsstempel for
   registrering i CVR → vores opdagelse → Telegram accepteret, til sammenligning med Lasso.

## Bemærkninger

- Cloudmiljøet har en forudkonfigureret adgang til `api.cvr.dev`. Det er en tredjeparts-API
  og ikke Erhvervsstyrelsens system. CVR Radar bruger den ikke.
