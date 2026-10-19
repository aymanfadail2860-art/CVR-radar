"""Fælles HTTP-kald med ensartet, maskeret fejlhåndtering.

- HTTPS med normal certifikatkontrol (requests' standard; `verify` sættes aldrig til False).
  Ukrypteret HTTP kun til én navngiven vært (`allow_http_host`), når kalderen beder om det.
- Redirects følges ikke, så et svar kan aldrig føre os over på ukrypteret HTTP.
- Netværksfejl oversættes til `NetworkError`/`TimeoutError_`, aldrig til loginfejl.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import requests

from . import __version__
from .errors import CertificateError, NetworkError, TimeoutError_

USER_AGENT = f"cvr-radar/{__version__}"


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def send(
    session: requests.Session,
    method: str,
    url: str,
    *,
    service: str,
    timeout: float,
    allow_http_host: str | None = None,
    **kwargs: Any,
) -> requests.Response:
    parsed = urlparse(url)
    plain_http_ok = (
        allow_http_host is not None
        and parsed.scheme == "http"
        and parsed.hostname == allow_http_host
        and parsed.port in (None, 80)
    )
    if parsed.scheme != "https" and not plain_http_ok:
        raise NetworkError(f"Afviser ikke-krypteret forbindelse til {service}.")
    try:
        return session.request(method, url, timeout=timeout, allow_redirects=False, **kwargs)
    except requests.exceptions.SSLError:
        raise CertificateError(
            f"TLS-certifikatet for {service} kunne ikke verificeres.",
            hint="Forbindelsen er afbrudt. Certifikatkontrol slås ikke fra; tjek systemets CA-certifikater.",
        ) from None
    except requests.exceptions.ProxyError:
        raise NetworkError(
            f"Proxy/netværkspolitik afviste forbindelsen til {service}. Det er ikke et loginproblem.",
            hint="I et cloudmiljø skal værten tilføjes under 'Allowed domains' (se README.md).",
        ) from None
    except requests.exceptions.ConnectTimeout:
        raise TimeoutError_(
            f"Tidsgrænsen blev overskredet under oprettelse af forbindelse til {service}.",
            hint="Tjek netværket. Adgangsoplysningerne er ikke afprøvet.",
        ) from None
    except requests.exceptions.ReadTimeout:
        raise TimeoutError_(
            f"{service} svarede ikke inden for {timeout:g} sekunder.",
            hint="Prøv igen senere, eller øg HTTP_TIMEOUT_SECONDS.",
        ) from None
    except requests.exceptions.ConnectionError:
        raise NetworkError(
            f"Kunne ikke oprette forbindelse til {service} (DNS, netværk eller firewall). Det er ikke et loginproblem.",
        ) from None
    except requests.exceptions.RequestException as err:
        raise NetworkError(f"Netværksfejl mod {service}: {type(err).__name__}.") from None


def retry_after_seconds(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
