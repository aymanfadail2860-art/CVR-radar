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
| Automatiserede tests (simulerede svar) | 72 tests består |

### Ikke verificeret endnu

- **CVR:** Netværkspolitikken i cloudmiljøet blokerer `distribution.virk.dk`, og
  `CVR_USERNAME`/`CVR_PASSWORD` er ikke sat. Den autentificerede test er ikke udført. Det
  er heller ikke bekræftet i praksis, at endpoint-stien og HTTPS på port 443 virker.
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
