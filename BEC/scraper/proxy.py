"""
scraper/proxy.py
================
L'indirizzo del proxy residenziale (IPRoyal) e la pulizia degli errori che lo
nominano. Prima stavano dentro `core/link_ingest.py`; ora li usano anche la
raccolta di Instagram (`embed_provider.py`) e il download dei reel, quindi la
copia è una sola e `link_ingest` la importa da qui.

L'indirizzo contiene una password: solo in `.env`, mai in un log o in un
messaggio. Ogni errore che può nominarlo passa da `scrub()` PRIMA di essere
tagliato o scritto.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote, unquote, urlsplit

from django.conf import settings


def scrub(text: str, proxy: str) -> str:
    """`text` with every trace of the proxy address replaced by "<proxy>".

    Run it on the WHOLE stderr, before any cut: cutting first can leave a
    fragment of the address (or of the password) at the edge that no longer
    matches the full URL. The password is also removed on its own, raw,
    decoded and URL-quoted, because yt-dlp may print it apart from the URL.
    """
    if not proxy or not text:
        return text
    secrets = [proxy]
    try:
        pw = urlsplit(proxy).password
    except ValueError:
        pw = None
    if pw:
        secrets += [pw, unquote(pw), quote(pw, safe=""), quote(pw)]
    # Longest first: the full address must go before the password inside it.
    for secret in sorted(set(filter(None, secrets)), key=len, reverse=True):
        text = text.replace(secret, "<proxy>")
    return text


def _fresh(raw: str) -> str:
    raw = (raw or "").strip()
    return raw.replace("{session}", uuid.uuid4().hex[:8]) if raw else ""


def ytdlp_proxy() -> str:
    """The proxy address for ONE download, or "" when none is configured.

    `{session}` becomes a fresh id: the provider keeps one exit IP per id, so
    a download keeps its IP from start to end and a retry gets a new one.
    """
    return _fresh(getattr(settings, "YTDLP_PROXY", ""))


def ig_proxy() -> str:
    """The proxy address for ONE Instagram read: `IG_PROXY`, else `YTDLP_PROXY`.

    Each call is a new IP (new `{session}`), so every account is read from a
    different exit and a retry never repeats the one that was just refused.
    """
    raw = getattr(settings, "IG_PROXY", "") or getattr(settings, "YTDLP_PROXY", "")
    return _fresh(raw)
