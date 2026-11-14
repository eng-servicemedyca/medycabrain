"""
scraper/embed_provider.py
=========================
Legge gli ultimi post di un account Instagram dalla pagina pubblica "embed"
(`instagram.com/<utente>/embed/`), passando dal proxy residenziale. Senza
account Instagram, senza cookie, senza Apify: vede solo ciò che vede un
visitatore anonimo.

Provato il 2026-11-14 dal VDS: attraverso il proxy la pagina risponde 200
(circa 250 KB, 1-2 s) con un blocco `contextJSON` che contiene il profilo e
`graphql_media`, **gli ultimi 6 post**. Senza proxy (IP di datacenter) Instagram
rimanda al login: il proxy qui non è un'ottimizzazione, è la condizione.

Cosa dà, per ogni post: codice, id, se è un video, data, didascalia, commenti,
"mi piace" (se l'account non li nasconde), immagine di copertina, proprietario.
Cosa NON dà: indirizzo del video (lo trova il download con yt-dlp dal codice),
visualizzazioni, durata (la scrive il download leggendola dal file).

Limiti che contano:
  * **6 post per lettura.** Se un account ne pubblica di più tra due letture, i
    più vecchi si perdono. Non c'è una pagina successiva su questa strada.
  * **Pagina pubblica non documentata.** Instagram può cambiarla o chiuderla
    quando vuole; in quel caso si alza `IGSchemaChanged`/`IGBlocked` e la
    raccolta lo dice, non c'è una seconda strada pronta.
  * **Proprietario.** Un reel in collaborazione compare sui profili di tutti i
    coautori ma ha UN proprietario. `_upsert_reel` riassegna il reel
    all'account che lo sta leggendo: se lo lasciassimo passare, un reel in
    collaborazione tra Medyca (`owned`) e un concorrente cambierebbe parte a
    ogni giro, e il contenuto di Medyca si mescolerebbe con quello dei
    competitor. Per questo `parse_embed` consegna SOLO i post il cui
    proprietario è l'account richiesto, e scarta la pagina intera se il nome
    nel `contextJSON` non è quello chiesto.

Blocco riconosciuto, mai insistito: 401/403/429, rimando al login o pagina senza
dati. Un solo secondo tentativo con un IP nuovo, poi l'account fallisce per quel
giro. Il proxy si paga a gigabyte: ogni errore passa da `proxy.scrub`.
"""

from __future__ import annotations

import json
import logging
import re

from curl_cffi import requests as curl_requests

from scraper import ig_client
from scraper.proxy import ig_proxy, scrub
from scraper.types import IGBlocked, IGSchemaChanged, ProfileMeta, ReelMeta

logger = logging.getLogger(__name__)

# Quanti post dà la pagina. Serve a riconoscere il possibile buco: se tutti e
# 6 sono nuovi, ce ne sono probabilmente altri più vecchi che non vediamo.
PAGE_SIZE = 6

# Un username Instagram: lettere, numeri, punto, underscore, fino a 30. Una
# virgola (`elena,palliotto`) non è un nome: Instagram risponde con una pagina
# vuota che sembrerebbe "ha cambiato la pagina". Si riconosce prima, a costo zero.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


class AccountNotFound(Exception):
    """The name is wrong or the account does not exist: a property of the
    account, not of Instagram or the proxy. Not retried."""

_BLOCK_STATUSES = {401, 403, 429}
_CONTEXT_RE = re.compile(r'"contextJSON":("(?:[^"\\]|\\.)*")')


def configured() -> bool:
    return bool(ig_proxy())


def _ctx_from_html(html: str) -> dict:
    m = _CONTEXT_RE.search(html or "")
    if not m:
        raise IGSchemaChanged("pagina embed senza contextJSON")
    try:
        # contextJSON è una stringa JSON dentro il JSON della pagina.
        ctx = json.loads(json.loads(m.group(1)))["context"]
    except (ValueError, KeyError, TypeError) as exc:
        raise IGSchemaChanged(f"contextJSON illeggibile: {exc!r}") from exc
    if not isinstance(ctx, dict):
        raise IGSchemaChanged("contextJSON senza 'context'")
    return ctx


def parse_embed(html: str, username: str) -> tuple[ProfileMeta, list[ReelMeta], int]:
    """(profilo, reel dell'account, quanti post c'erano in pagina).

    Solo video il cui proprietario è `username`. Alza IGSchemaChanged se la
    pagina non ha i dati o appartiene a un altro nome.
    """
    ctx = _ctx_from_html(html)
    wanted = username.strip().lower()
    got = str(ctx.get("username") or "").lower()
    if got != wanted:
        raise IGSchemaChanged(f"la pagina è di @{got or '?'}, non di @{wanted}")
    media = ctx.get("graphql_media")
    if not isinstance(media, list):
        raise IGSchemaChanged("contextJSON senza graphql_media")

    profile = ProfileMeta(
        username=username,
        ig_user_id=str(ctx.get("owner_id") or ""),
        display_name=ctx.get("full_name") or "",
        profile_pic_url=ctx.get("profile_pic_url") or "",
        followers_count=ctx.get("followers_count"),
    )
    reels: list[ReelMeta] = []
    for entry in media:
        node = (entry or {}).get("shortcode_media") or {}
        if not node.get("shortcode") or not node.get("is_video"):
            continue  # foto e caroselli: solo video, come prima
        owner = str((node.get("owner") or {}).get("username") or "").lower()
        if owner != wanted:
            logger.info("[embed] @%s: %s è di @%s (collaborazione?), scartato",
                        username, node["shortcode"], owner or "?")
            continue
        caps = ((node.get("edge_media_to_caption") or {}).get("edges")) or []
        caption = ((caps[0] or {}).get("node") or {}).get("text", "") if caps else ""
        # Se l'account nasconde i "mi piace" il conteggio è 0 per finta:
        # None non sovrascrive niente (`_upsert_reel`), 0 sì.
        hidden = bool(node.get("like_and_view_counts_disabled"))
        likes = None if hidden else (node.get("edge_liked_by") or {}).get("count")
        comments = (node.get("edge_media_to_comment") or {}).get("count")
        if comments is None:
            comments = node.get("commenter_count")
        # `media_preview` è una miniatura binaria: inutile nel file grezzo.
        raw = {k: v for k, v in node.items() if k != "media_preview"}
        reels.append(ReelMeta(
            shortcode=node["shortcode"],
            ig_media_id=str(node.get("id") or ""),
            caption=caption,
            thumbnail_url=node.get("display_url") or "",
            view_count=node.get("video_view_count"),  # di norma assente
            like_count=likes,
            comment_count=comments,
            posted_at_ts=node.get("taken_at_timestamp"),
            raw=raw,
        ))
    return profile, reels, len(media)


def _get(username: str, impersonate: str) -> str:
    """Una richiesta alla pagina embed, con un IP nuovo. Alza IGBlocked o altro."""
    proxy = ig_proxy()
    if not proxy:
        raise IGBlocked("nessun proxy configurato (IG_PROXY / YTDLP_PROXY)")
    session = ig_client.build_session({}, impersonate=impersonate)
    try:
        resp = session.get(
            f"https://www.instagram.com/{username}/embed/",
            proxies={"http": proxy, "https": proxy}, timeout=40,
            headers={"Accept-Language": "it-IT,it;q=0.9"},
        )
    except Exception as exc:  # noqa: BLE001 — rete/proxy: l'errore può nominare il proxy
        raise RuntimeError(scrub(repr(exc), proxy)[:300]) from None
    if resp.status_code in _BLOCK_STATUSES:
        raise IGBlocked(f"HTTP {resp.status_code} sulla pagina embed")
    if "/accounts/login" in str(getattr(resp, "url", "")):
        raise IGBlocked("rimandato al login")
    if resp.status_code == 404:
        raise AccountNotFound("HTTP 404 sulla pagina embed")
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} sulla pagina embed")
    return resp.text


def fetch_account(username: str, impersonate: str = "chrome124"
                  ) -> tuple[ProfileMeta, list[ReelMeta], int]:
    """Legge un account. Un secondo tentativo, con un IP nuovo, e basta.

    Un nome non valido o un 404 (`AccountNotFound`) non si ritenta: è una
    proprietà dell'account, non del proxy.
    """
    if not _USERNAME_RE.match(username or ""):
        raise AccountNotFound(f"«{username}» non è un nome Instagram valido")
    last: Exception | None = None
    for attempt in (1, 2):
        try:
            return parse_embed(_get(username, impersonate), username)
        except AccountNotFound:
            raise
        except (IGBlocked, IGSchemaChanged, RuntimeError) as exc:
            last = exc
            logger.warning("[embed] @%s tentativo %s/2: %s", username, attempt, exc)
    assert last is not None
    raise last
