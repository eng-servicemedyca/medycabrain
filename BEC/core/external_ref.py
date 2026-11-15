"""
core/external_ref.py
====================
Fetching a web page from a URL somebody typed, safely (`safe_get`).

Used by the blog importer (`blog_agent`, `blog_discovery`) and by the places
that check a pasted link (`link_ingest`, serializers). It used to feed the
in-app chat too (`fetch_reference`: read a pasted page for one answer);
the chat was removed 2026-11-15 and that function went with it.

Why this is not just requests.get
---------------------------------
The URL comes from whoever is typing. A bare fetch turns this server into a
way of reaching things only it can reach: other services on the host, the
private network, the cloud metadata endpoint on 169.254.169.254. So the host
is resolved and every address it maps to is checked before we connect, and
redirects are followed by hand so each hop is checked too.

The check happens before the connection, so a name that resolves differently
a moment later would slip past (DNS rebinding). Closing that properly means
pinning the connection to the address we validated; it is not done here, and
is the one hole worth knowing about.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

MAX_BYTES = 3_000_000      # a page, not a download
MAX_REDIRECTS = 3
TIMEOUT = 20


class RefusedURL(ValueError):
    """The url is not one this server will fetch."""


def _check_public(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise RefusedURL("Sono ammessi solo indirizzi http e https.")
    host = parsed.hostname
    if not host:
        raise RefusedURL("Indirizzo senza nome host.")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise RefusedURL(f"Nome host non risolvibile: {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        # Anything not routable on the public internet is off limits: it can
        # only be something this server reaches and the user cannot.
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise RefusedURL(
                "Questo indirizzo punta alla rete interna del server, "
                "non a una pagina pubblica."
            )


def safe_get(url: str, *, allow_types: tuple[str, ...] = ("html", "text"),
             max_bytes: int = MAX_BYTES, timeout: int = TIMEOUT,
             user_agent: str = _UA) -> str:
    """The body of a public URL, every redirect hop re-validated, size-capped.

    This is what the blog crawler uses for every body it STORES: every
    caller shares the same refusal logic, so there is exactly one place where
    "what will this server fetch" is decided. `allow_types` exists because the
    crawler also reads sitemap/feed XML, which an html-only rule would refuse.
    """
    seen = url
    for _ in range(MAX_REDIRECTS + 1):
        _check_public(seen)
        resp = requests.get(seen, headers={"User-Agent": user_agent}, timeout=timeout,
                            allow_redirects=False, stream=True)
        if resp.is_redirect or resp.is_permanent_redirect:
            nxt = resp.headers.get("Location")
            resp.close()
            if not nxt:
                raise RefusedURL("Reindirizzamento senza destinazione.")
            seen = requests.compat.urljoin(seen, nxt)
            continue
        if resp.status_code != 200:
            resp.close()
            raise RefusedURL(f"La pagina ha risposto {resp.status_code}.")
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if not any(t in ctype for t in allow_types):
            resp.close()
            raise RefusedURL(f"Il contenuto non è una pagina web ({ctype.split(';')[0]}).")
        chunks, total = [], 0
        for chunk in resp.iter_content(64 * 1024, decode_unicode=False):
            total += len(chunk)
            if total > max_bytes:
                resp.close()
                raise RefusedURL("La pagina è troppo grande da leggere.")
            chunks.append(chunk)
        resp.close()
        raw = b"".join(chunks)
        return raw.decode(resp.encoding or "utf-8", errors="replace")
    raise RefusedURL("Troppi reindirizzamenti.")
