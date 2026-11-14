"""
pipeline/agents/scraper_agent.py
================================
ScraperAgent — collects the new reels of the tracked accounts.

Who collects is decided in ONE place, `run()`: Graph API if a token is set
(it is not), else `embed` if there is a proxy, else the stage says
"sospeso" in plain words. **Apify is no longer called** (its code stays, off:
`_scrape_account_apify`, `scraper/apify_provider.py`). It answered
401 for all 23 accounts from 2026-11-12 and had already stopped on its budget
before that: no new reel entered after 2026-11-02.

`embed` (scraper/embed_provider.py) reads the public embed page of each
account from this server through the residential proxy: the last 6 posts, no
Instagram account, no cookie. Per account:
  1. read the page (new IP, one retry on a block, never more)
  2. keep only the videos OWNED by that account (a collaboration reel must not
     switch side between owned and competitor)
  3. dump each raw node to data/raw/{account}/{shortcode}.json
  4. upsert Reel rows (media_status='pending'); the download finds the video
     with yt-dlp from the shortcode

Rules of the run:
  * a pause of `embed_delay_s` (5-10 s) between accounts;
  * at most `embed_max_new_per_run` NEW reels per run (default 5, newest
    first): the first read after a long stop would otherwise bring in dozens at
    once and flood the analysis. What is left over is not lost if it is still
    within the 6 posts of the next read;
  * 3 blocked accounts in a row stop the run (the IP/route is refused; asking
    20 more times only deepens it);
  * if EVERY account failed the stage FAILS with the reason, instead of
    finishing "done" with 23 failures nobody reads.

The older paths (graphql, instaloader) are kept for the code's sake. Rate
discipline for those: min_delay_s jittered between requests,
max_pages_per_account, global_request_budget, provider_order.

IGBlocked aborts the current account but never the pipeline.
"""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.utils import timezone as dj_tz

from core import progress
from core.models import PENDING, Reel, ScraperConfig, TrackedAccount
from scraper import ig_client, instaloader_fallback
from scraper.session_store import load_cookies
from scraper.types import IGBlocked, IGSchemaChanged, ProfileMeta, ReelMeta

# Apify is billed per result, so depth is money. The floor is what it takes to
# notice a new post at all; the ceiling stops one prolific account from eating
# a run's budget. Both are editable in the admin (scraper_config).
_APIFY_MIN_DEPTH = 3


def _apify_max_depth() -> int:
    return int(_cfg("apify_max_depth", 30))

logger = logging.getLogger(__name__)


def _cfg(key, default):
    val = ScraperConfig.get(key)
    if isinstance(val, dict) and "value" in val:
        return val["value"]
    return val if val is not None else default


def _dump_raw(username: str, reel: ReelMeta):
    d = Path(settings.RAW_DUMP_DIR) / username
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{reel.shortcode}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(reel.raw, fh, ensure_ascii=False)
    return str(path.relative_to(settings.BASE_DIR))


def _upsert_reel(account: TrackedAccount, reel: ReelMeta, raw_path: str) -> bool:
    posted_at = None
    if reel.posted_at_ts:
        posted_at = datetime.fromtimestamp(reel.posted_at_ts, tz=timezone.utc)

    obj, created = Reel.objects.get_or_create(
        shortcode=reel.shortcode,
        defaults={
            "account": account,
            "ig_media_id": reel.ig_media_id,
            "caption": reel.caption,
            "posted_at": posted_at,
            "duration_s": reel.duration_s,
            "view_count": reel.view_count,
            "like_count": reel.like_count,
            "comment_count": reel.comment_count,
            "video_url": reel.video_url,
            "thumbnail_url": reel.thumbnail_url,
            "audio_info": reel.audio_info or {},
            "raw_json_path": raw_path,
            "is_active": True,
        },
    )
    if created:
        obj.media_status = PENDING
        obj.save(update_fields=["media_status"])
        return True

    # Re-scrape: refresh volatile fields (engagement counts + fresh URLs) but
    # NEVER clobber the richer media/info-backfilled fields (posted_at, caption,
    # duration) — the clips node lacks them, so writing them would null out data.
    obj.account = account
    if reel.view_count is not None:
        obj.view_count = reel.view_count
    if reel.like_count is not None:
        obj.like_count = reel.like_count
    if reel.comment_count is not None:
        obj.comment_count = reel.comment_count
    if reel.video_url:
        obj.video_url = reel.video_url
    if reel.thumbnail_url:
        obj.thumbnail_url = reel.thumbnail_url
    if posted_at and not obj.posted_at:
        obj.posted_at = posted_at
    if reel.caption and not obj.caption:
        obj.caption = reel.caption
    if reel.duration_s and not obj.duration_s:
        obj.duration_s = reel.duration_s
    # Deliberately NOT touching is_active here: a reel the client excluded
    # (greetings, off-topic guest) must stay excluded across re-scrapes.
    obj.save()
    return False


def _scrape_account_graphql(account: TrackedAccount, budget: list[int]) -> tuple[int, bool]:
    """Returns (new_reels, complete). Mutates budget[0] (remaining requests)."""
    cookies = load_cookies()
    csrf = cookies.get("csrftoken", "")
    impersonate = _cfg("impersonate", "chrome124")
    session = ig_client.build_session(cookies, impersonate=impersonate)

    doc_id = _cfg("doc_id_reels_tab", "")
    page_size = int(_cfg("page_size", 12))
    max_pages = int(_cfg("max_pages_per_account", 3))
    min_delay = float(_cfg("min_delay_s", 25))
    # Full backfill: paginate the whole depth even when pages are already known,
    # to pull the OLDER reels an incremental scrape never reaches.
    full_backfill = bool(_cfg("full_backfill", False))

    # Resolve profile
    profile = ig_client.resolve_user(session, account.username, csrftoken=csrf)
    budget[0] -= 1
    _apply_profile(account, profile)

    known = set(
        Reel.objects.filter(account=account).values_list("shortcode", flat=True)
    )
    new_count = 0
    cursor = ""
    for page_idx in range(max_pages):
        if budget[0] <= 0:
            logger.warning("[scraper] global request budget exhausted")
            return new_count, False
        time.sleep(random.uniform(min_delay, min_delay * 2))
        nodes, page_info = ig_client.fetch_reels_page(
            session, profile.ig_user_id, doc_id, after=cursor,
            page_size=page_size, csrftoken=csrf, handle=account.username,
        )
        budget[0] -= 1

        page_new = 0
        for node in nodes:
            reel = ig_client.parse_reel_node(node)
            if not reel:
                continue
            raw_path = _dump_raw(account.username, reel)
            if _upsert_reel(account, reel, raw_path):
                page_new += 1
        new_count += page_new
        logger.info("[scraper] @%s page %s: %s nodes, %s new",
                    account.username, page_idx + 1, len(nodes), page_new)

        # Incremental stop: whole page already known and no new ones.
        # Skipped in full-backfill mode so we reach the older, unseen reels.
        if not full_backfill:
            all_known = all(
                (ig_client.parse_reel_node(n) or ReelMeta(shortcode="")).shortcode in known
                for n in nodes if n
            )
            if nodes and page_new == 0 and all_known:
                logger.info("[scraper] @%s: full page already known, stopping", account.username)
                break
        if not page_info.get("has_next_page"):
            break
        cursor = page_info.get("end_cursor", "")
        account.scrape_state = {**account.scrape_state, "end_cursor": cursor}
        account.save(update_fields=["scrape_state"])

    return new_count, True


def _scrape_account_graph(account: TrackedAccount, budget: list[int]) -> tuple[int, bool]:
    """The official path: business_discovery via the Graph API.

    Same contract as the GraphQL scraper — (new_reels, complete), budget
    mutated — but no cookies, no impersonation, no quota guessing: the rate
    limits are documented and the caller is an app we registered.

    A personal target account raises NotDiscoverable; that is a property of
    the account, not a transient failure, so it is recorded on the row and
    the account is skipped in future runs until it changes.
    """
    from django.conf import settings

    from scraper import graph_client

    caller = settings.IG_GRAPH_USER_ID or graph_client.resolve_caller_ig_id()
    max_pages = int(_cfg("max_pages_per_account", 3))
    page_size = min(int(_cfg("page_size", 12)) * 2, 25)  # API pages are cheap
    full_backfill = bool(_cfg("full_backfill", False))

    state = account.scrape_state or {}
    if state.get("graph_not_discoverable"):
        logger.info("[scraper] @%s: non-Business, salto (business_discovery)",
                    account.username)
        return 0, True

    known = set(
        Reel.objects.filter(account=account).values_list("shortcode", flat=True)
    )
    new_count, cursor = 0, ""
    for page_idx in range(max_pages):
        if budget[0] <= 0:
            logger.warning("[scraper] global request budget exhausted")
            return new_count, False
        try:
            profile, reels, paging = graph_client.discover(
                account.username, caller, after=cursor, page_size=page_size)
        except graph_client.NotDiscoverable as exc:
            # Permanent property of the target, surfaced once, not retried
            # nightly into noise. Flipping the account to Business clears it
            # by hand (scrape_state) or via a fresh graph_check.
            account.scrape_state = {**state, "graph_not_discoverable": str(exc)[:200]}
            account.save(update_fields=["scrape_state"])
            logger.warning("[scraper] @%s non è Business/Creator: %s",
                           account.username, exc)
            return 0, True
        budget[0] -= 1
        if page_idx == 0:
            _apply_profile(account, profile)

        page_new = 0
        for reel in reels:
            raw_path = _dump_raw(account.username, reel)
            if _upsert_reel(account, reel, raw_path):
                page_new += 1
        new_count += page_new
        logger.info("[scraper] @%s (graph) page %s: %s video, %s new",
                    account.username, page_idx + 1, len(reels), page_new)

        if not full_backfill and reels and page_new == 0 \
                and all(r.shortcode in known for r in reels):
            break
        if not paging.get("has_next_page"):
            break
        cursor = paging.get("after", "")
        # Documented, generous limits — a short fixed pause is courtesy, not
        # the elaborate jitter the unofficial endpoint needed.
        time.sleep(2)

    return new_count, True


def _scrape_account_instaloader(account: TrackedAccount) -> tuple[int, bool]:
    known = set(Reel.objects.filter(account=account).values_list("shortcode", flat=True))
    max_pages = int(_cfg("max_pages_per_account", 3))
    page_size = int(_cfg("page_size", 12))
    profile, reels = instaloader_fallback.resolve_and_fetch(
        account.username, max_reels=max_pages * page_size, known_shortcodes=known,
    )
    _apply_profile(account, profile)
    new_count = 0
    for reel in reels:
        raw_path = _dump_raw(account.username, reel)
        if _upsert_reel(account, reel, raw_path):
            new_count += 1
    return new_count, True


def _apify_depth(account: TrackedAccount) -> int:
    """How many reels to ask Apify for, for this account.

    Every result is billed ($0.0026), whether it is new or something we
    already have. Asking a fixed depth of everyone is therefore a way of
    paying the prolific accounts' price for the quiet ones: measured on
    2026-09-11, this project's accounts post anywhere between every 0.1 days
    and every 34 days.

    So the depth is the gap since their last known post, divided by how often
    they actually post, plus a margin of three. An account that posts monthly
    is asked for a handful of reels; one that posts daily is asked for more,
    because it genuinely has more.
    """
    import math

    qs = Reel.objects.filter(account=account).exclude(posted_at=None)
    n = qs.count()
    if n < 2:
        # Nothing to reason from — a new account, or one that has never
        # returned anything. Start shallow and let the next run learn.
        return _APIFY_MIN_DEPTH
    first = qs.order_by("posted_at").first().posted_at
    last = qs.order_by("-posted_at").first().posted_at
    days_per_post = max((last - first).days, 1) / n
    gap_days = max((dj_tz.now() - last).days, 0)
    depth = math.ceil(gap_days / days_per_post) + 3
    return max(_APIFY_MIN_DEPTH, min(depth, _apify_max_depth()))


def _scrape_account_apify(account: TrackedAccount) -> tuple[int, bool]:
    """List an account's recent reels through Apify, and upsert them.

    This is the collection path since 2026-09-11. Instagram closed the two
    that came before it: listing a public profile anonymously now answers
    `401 {"require_login": true}`, and the logged-in path was removed because
    it ran as a personal account that Instagram had begun checkpointing.
    yt-dlp — which does still fetch a reel anonymously — has no working way to
    *list* an account: its own profile extractor is marked `_WORKING = False`.

    Apify queries from its own infrastructure, so no Instagram account of ours
    is involved at all. What it costs, and what stops it costing too much, is
    in `scraper/apify_budget.py`.
    """
    from scraper import apify_provider

    depth = _apify_depth(account)
    items = apify_provider.fetch_reels(account.username, limit=depth)

    new_count = 0
    for it in items:
        posted = it.get("posted_at")
        reel = ReelMeta(
            shortcode=it["shortcode"],
            caption=it.get("caption") or "",
            video_url=it.get("video_url") or "",
            thumbnail_url=it.get("thumbnail_url") or "",
            view_count=it.get("view_count"),
            like_count=it.get("like_count"),
            comment_count=it.get("comment_count"),
            duration_s=it.get("duration_s"),
            posted_at_ts=int(posted.timestamp()) if posted else None,
            raw={k: v for k, v in it.items() if k != "posted_at"},
        )
        raw_path = _dump_raw(account.username, reel)
        if _upsert_reel(account, reel, raw_path):
            new_count += 1
    return new_count, True


def _scrape_account_embed(account: TrackedAccount, cap: list[int]) -> tuple[int, bool]:
    """Read one account from its embed page. Mutates cap[0] (new reels still
    allowed in this run). Returns (new_reels, complete).

    Writes into `scrape_state`: `gap_possible` (all the posts read were new, so
    older ones may sit beyond the 6 we can see) and `deferred` (new reels left
    for the next run because of the cap).
    """
    from scraper import embed_provider

    profile, reels, n_posts = embed_provider.fetch_account(
        account.username, impersonate=_cfg("impersonate", "chrome124"))
    _apply_profile(account, profile)

    known = set(Reel.objects.filter(shortcode__in=[r.shortcode for r in reels])
                .values_list("shortcode", flat=True))
    new_count = deferred = 0
    # Newest first: if the cap bites, what stays out is the oldest.
    for reel in sorted(reels, key=lambda r: r.posted_at_ts or 0, reverse=True):
        if reel.shortcode not in known:
            if cap[0] <= 0:
                deferred += 1
                continue
            cap[0] -= 1
        raw_path = _dump_raw(account.username, reel)
        if _upsert_reel(account, reel, raw_path):
            new_count += 1
    gap = bool(reels) and n_posts >= embed_provider.PAGE_SIZE and not known
    account.scrape_state = {**account.scrape_state, "gap_possible": gap, "deferred": deferred}
    logger.info("[scraper] @%s (embed): %s video, %s new%s%s", account.username,
                len(reels), new_count,
                f", {deferred} rinviati" if deferred else "",
                ", possibile buco" if gap else "")
    return new_count, True


def _apply_profile(account: TrackedAccount, profile: ProfileMeta):
    account.ig_user_id = profile.ig_user_id or account.ig_user_id
    account.display_name = profile.display_name or account.display_name
    account.profile_pic_url = profile.profile_pic_url or account.profile_pic_url
    account.bio = profile.bio or account.bio
    if profile.followers_count is not None:
        account.followers_count = profile.followers_count
    account.save(update_fields=[
        "ig_user_id", "display_name", "profile_pic_url", "bio", "followers_count",
    ])


def run(ctx) -> dict:
    """Collect new reels for every active account.

    Apify is not called any more (see the module docstring). Meta's official
    Graph API still takes precedence when a token is set, but it is not
    configured here. Without it, the `embed` reading from the server needs the
    residential proxy; without the proxy the stage says it is suspended.
    """
    from core.upload_workflow import ClientError
    from scraper import embed_provider, graph_client

    if graph_client.configured():
        provider_order = _cfg("provider_order", ["graph"])
        if "graph" not in provider_order:
            provider_order = ["graph"] + list(provider_order)
    elif embed_provider.configured():
        provider_order = ["embed"]
    else:
        logger.warning("[scraper] nessuna fonte configurata (né IG_PROXY/YTDLP_PROXY "
                       "né IG_GRAPH_TOKEN): raccolta sospesa")
        # Failed, not "done with a note": a stage that closes "done" reads as a
        # quiet night, and the Stato box would say "sospesa" and "tutto in
        # ordine" at once. The sentence is the one the page shows.
        raise ClientError("La raccolta è sospesa: manca la connessione (proxy) per "
                          "leggere Instagram. Serve chi gestisce il server.")
    budget = [int(_cfg("global_request_budget", 40))]
    cap = [int(_cfg("embed_max_new_per_run", 5))]
    delay = float(_cfg("embed_delay_s", 5))
    # Medyca's own account first: if the cap or a block stops the run, it is
    # the competitors that wait, never the client's own content.
    accounts = TrackedAccount.objects.filter(is_active=True).order_by("-owner_type", "username")
    if not accounts:
        return {"accounts": 0, "new_reels": 0, "note": "no active accounts"}

    total_new = 0
    per_account = {}
    gaps, deferred_total = [], 0
    failed, errors = [], {}
    read_ok = 0
    blocked_streak = 0
    blocked_stop = False
    # No model works here: the bar counts accounts, the page says "nessun modello".
    progress.open(accounts.count(), "account", "Account")
    first = True
    for account in accounts:
        progress.start_item(*progress.describe(account))
        if budget[0] <= 0:
            per_account[account.username] = "skipped (budget)"
            progress.item_done("skipped")
            continue
        if blocked_stop:
            per_account[account.username] = "skipped (Instagram blocca)"
            progress.item_done("skipped")
            continue
        if provider_order == ["embed"] and not first:
            time.sleep(random.uniform(delay, delay * 2))
        first = False
        new_count, err = _scrape_one(account, provider_order, budget, cap)
        # An account whose page is empty while others were just read fine is a
        # wrong or missing name, not "Instagram changed the page".
        if err and err.startswith("schema_changed") and read_ok:
            err = "not_found: pagina senza dati mentre gli altri account si leggono"
        per_account[account.username] = new_count if err is None else err
        progress.item_done("done" if err is None else "failed")
        if err is None:
            read_ok += 1
            blocked_streak = 0
            total_new += new_count
            if account.scrape_state.get("gap_possible"):
                gaps.append(account.username)
            deferred_total += int(account.scrape_state.get("deferred") or 0)
            account.last_scraped_at = dj_tz.now()
            account.scrape_state = {**account.scrape_state, "consecutive_failures": 0,
                                    "last_error": ""}
            account.save(update_fields=["last_scraped_at", "scrape_state"])
        else:
            failed.append(account.username)
            errors[account.username] = err
            blocked_streak = blocked_streak + 1 if err.startswith("blocked") else 0
            if blocked_streak >= 3 and provider_order == ["embed"]:
                blocked_stop = True
                progress.note("fermato: Instagram blocca la lettura")
                logger.warning("[scraper] 3 account bloccati di fila: mi fermo")
            fails = int(account.scrape_state.get("consecutive_failures", 0)) + 1
            account.scrape_state = {**account.scrape_state,
                                    "consecutive_failures": fails, "last_error": err}
            account.save(update_fields=["scrape_state"])

    read = read_ok
    notes = []
    if gaps:
        notes.append(f"possibile buco (6 post tutti nuovi) su {len(gaps)} account")
    if deferred_total:
        notes.append(f"{deferred_total} reel rimandati al giro dopo (tetto per giro)")
    if failed:
        notes.append(f"{len(failed)} account non letti")
    if notes:
        progress.note("; ".join(notes))
    if read == 0 and failed:
        # Nothing was read at all: a stage that finishes "done" here reads as a
        # quiet night. It failed, and the sentence says why (detail in the log
        # and in each account's `last_error`).
        kind = errors[failed[0]].split(":", 1)[0]
        raise ClientError(_CLIENT_REASON.get(kind, _CLIENT_REASON["error"]))
    return {"accounts": len(per_account), "new_reels": total_new,
            "failed_accounts": len(failed), "gap_possible": gaps,
            "deferred": deferred_total, "detail": per_account}


def _scrape_one(account, provider_order, budget, cap=None):
    """Try providers in order. Returns (new_count, error_str|None).

    The error string starts with its kind (`blocked:`, `schema_changed:`,
    `not_found:`, `no_session:`, `error:`), once: `run()` turns the kind into a
    sentence for the client, and the detail stays in the log and `last_error`.
    """
    from scraper import embed_provider

    last_err = None
    for provider in provider_order:
        try:
            if provider == "embed":
                n, _ = _scrape_account_embed(account, cap if cap is not None else [5])
            elif provider == "graph":
                n, complete = _scrape_account_graph(account, budget)
            elif provider == "graphql":
                n, _ = _scrape_account_graphql(account, budget)
            elif provider == "instaloader":
                n, _ = _scrape_account_instaloader(account)
            else:
                continue
            account.scrape_state = {**account.scrape_state, "provider": provider}
            return n, None
        except embed_provider.AccountNotFound as exc:
            logger.warning("[scraper] @%s non trovato: %s", account.username, exc)
            return 0, f"not_found: {exc}"
        except IGSchemaChanged as exc:
            logger.error("[scraper] @%s pagina senza i dati attesi su %s: %s",
                         account.username, provider, exc)
            last_err = f"schema_changed: {exc}"
            continue
        except IGBlocked as exc:
            logger.error("[scraper] @%s blocked on %s: %s", account.username, provider, exc)
            last_err = f"blocked: {exc}"
            continue
        except FileNotFoundError as exc:
            return 0, f"no_session: {exc}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("[scraper] @%s unexpected error on %s", account.username, provider)
            last_err = f"error: {exc!r}"
            continue
    return 0, last_err


# What the client reads in the Stato box when no account could be read: one
# short sentence per kind of failure — what happened and what to do. The
# technical detail stays in the log and in `scrape_state.last_error`.
_CLIENT_REASON = {
    "blocked": "Instagram ha rifiutato la lettura. Riprova più tardi: se continua, "
               "la connessione del server verso Instagram potrebbe non funzionare.",
    "schema_changed": "Instagram ha cambiato la pagina che leggiamo: la raccolta "
                      "resta ferma finché non la adattiamo.",
    "not_found": "Non ho trovato nessuno degli account: controlla i nomi nella lista.",
    "error": "Non riesco a raggiungere Instagram dal server. Controlla che la "
             "connessione (proxy) funzioni e riprova.",
}
