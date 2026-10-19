"""Klient til Erhvervsstyrelsens CVR-data via Elasticsearch (system-til-system-adgang).

Dokumentation: https://erhvervsstyrelsen.dk/kom-godt-igang-med-elasticSearch
Eksterne brugere kan kun søge (`/<indeks>/<type>/_search`) med HTTP Basic-login.
Ineffektive forespørgsler kan medføre midlertidig lukning af adgangen, så alle
opslag begrænses med `_source` og `size`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
from requests.auth import AuthBase

from .config import Settings
from .errors import (
    AuthenticationError,
    NetworkError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    ServerError,
    UnexpectedResponseError,
)
from .http import new_session, retry_after_seconds, send

SERVICE = "CVR (distribution.virk.dk)"
ERHVERVSSTYRELSEN_CVR = 10150817


@dataclass(frozen=True)
class Company:
    cvr_number: int
    name: str


def build_lookup_query(cvr_number: int) -> dict[str, Any]:
    return {
        "_source": [
            "Vrvirksomhed.cvrNummer",
            "Vrvirksomhed.virksomhedMetadata.nyesteNavn.navn",
        ],
        "query": {"term": {"Vrvirksomhed.cvrNummer": cvr_number}},
        "size": 1,
    }


def validate_cvr_number(value: str | int) -> int:
    text = str(value).strip()
    if not (text.isdigit() and len(text) == 8):
        raise ValueError("Et CVR-nummer består af præcis 8 cifre.")
    return int(text)


class ProxyInjectedAuth(AuthBase):
    """Proxytilstand: send intet login selv; miljøets netværksproxy tilføjer Basic-login.

    At angive et auth-objekt forhindrer også, at requests henter login fra ~/.netrc,
    og en eventuel Authorization-header fjernes, før forespørgslen sendes.
    """

    def __call__(self, request: requests.PreparedRequest) -> requests.PreparedRequest:
        request.headers.pop("Authorization", None)
        return request


class CvrClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        settings.require_cvr()
        self._settings = settings
        self._session = session or new_session()
        self.search_url = f"{settings.cvr_base_url}/{settings.cvr_index}/_search"
        self._auth: AuthBase | tuple[str, str]
        if settings.cvr_auth_via_proxy:
            self._auth = ProxyInjectedAuth()
        else:
            self._auth = (settings.cvr_username, settings.cvr_password)

    def search(self, body: dict[str, Any]) -> dict[str, Any]:
        response = send(
            self._session,
            "POST",
            self.search_url,
            service=SERVICE,
            timeout=self._settings.http_timeout,
            json=body,
            auth=self._auth,
            headers={"Accept": "application/json"},
        )
        _raise_for_status(response, via_proxy=self._settings.cvr_auth_via_proxy)
        try:
            data = response.json()
        except ValueError:
            raise UnexpectedResponseError(f"{SERVICE} svarede med noget, der ikke er JSON.") from None
        if not isinstance(data, dict) or "hits" not in data:
            raise UnexpectedResponseError(f"{SERVICE} svarede uden et 'hits'-felt.")
        return data

    def lookup_company(self, cvr_number: int) -> Company:
        data = self.search(build_lookup_query(cvr_number))
        hits = data.get("hits", {}).get("hits") or []
        if not hits:
            raise NotFoundError(
                f"CVR-nummer {cvr_number} blev ikke fundet.",
                hint="Login og forbindelse virker, men opslaget gav intet resultat.",
            )
        return parse_company(hits[0])


def parse_company(hit: dict[str, Any]) -> Company:
    try:
        virksomhed = hit["_source"]["Vrvirksomhed"]
        cvr_number = int(virksomhed["cvrNummer"])
    except (KeyError, TypeError, ValueError):
        raise UnexpectedResponseError("Resultatet mangler Vrvirksomhed.cvrNummer.") from None
    name = ((virksomhed.get("virksomhedMetadata") or {}).get("nyesteNavn") or {}).get("navn")
    if not name:
        raise UnexpectedResponseError(f"Resultatet for {cvr_number} mangler virksomhedsnavn.")
    return Company(cvr_number=cvr_number, name=str(name))


def _is_proxy_upstream_failure(response: requests.Response) -> bool:
    """Claude Code-miljøets proxy svarer selv med kort tekst, når den ikke kan nå værten."""
    return (
        response.headers.get("Content-Type", "").startswith("text/plain")
        and response.text.strip().lower() == "upstream request failed"
    )


def _raise_for_status(response: requests.Response, *, via_proxy: bool = False) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    if status == 401 and via_proxy:
        raise AuthenticationError(
            "CVR afviste login (HTTP 401). I proxytilstand kommer loginet fra miljøets netværkshemmelighed.",
            hint=(
                "Kontrollér brugernavn og adgangskode i netværkshemmeligheden, og at den gælder for "
                "distribution.virk.dk. Kun HTTP 401 betyder afvist login."
            ),
        )
    if status == 401:
        raise AuthenticationError(
            "CVR afviste login (HTTP 401): brugernavn eller adgangskode er forkert.",
            hint="Kontrollér CVR_USERNAME og CVR_PASSWORD. Tjek for mellemrum før/efter værdierne.",
        )
    if status == 403:
        raise PermissionDeniedError(
            "CVR nægtede adgang (HTTP 403): brugeren mangler rettighed til indekset, eller adgangen er spærret.",
            hint="Kontakt Erhvervsstyrelsen (cvrselvbetjening@erst.dk) hvis det fortsætter.",
        )
    if status == 429:
        wait = retry_after_seconds(response)
        raise RateLimitedError(
            "CVR begrænser forespørgsler (HTTP 429)."
            + (f" Vent mindst {wait:g} sekunder." if wait is not None else ""),
            retry_after=wait,
            hint="Send ikke flere forespørgsler lige nu.",
        )
    if status in (502, 503, 504) and _is_proxy_upstream_failure(response):
        raise NetworkError(
            f"Netværksproxyen kunne ikke nå CVR-serveren (HTTP {status} fra proxyen: upstream request failed). "
            "CVR har ikke svaret, og loginet er ikke afprøvet.",
            hint=(
                "Erhvervsstyrelsens egne eksempler bruger http://, og HTTPS-adressen svarer ikke herfra. "
                "CVR Radar falder ikke tilbage til HTTP. Få oplyst en HTTPS-adresse af Erhvervsstyrelsen."
            ),
        )
    if status >= 500:
        raise ServerError(f"CVR-serveren svarede med fejl (HTTP {status}). Prøv igen senere.")
    if 300 <= status < 400:
        raise UnexpectedResponseError(
            f"CVR svarede med omdirigering (HTTP {status}). Den følges ikke af sikkerhedshensyn.",
        )
    if status == 404:
        raise UnexpectedResponseError(
            "CVR-indekset blev ikke fundet (HTTP 404).",
            hint="Kontrollér CVR_BASE_URL og CVR_INDEX.",
        )
    raise UnexpectedResponseError(f"CVR afviste forespørgslen (HTTP {status}).")
