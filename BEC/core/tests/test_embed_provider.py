"""
La raccolta di Instagram dalla pagina "embed" (scraper/embed_provider.py) e il
suo posto nella pipeline (scraper_agent.run, downloader_agent).

In CI Instagram non c'è: la pagina è costruita qui con la stessa forma di quella
vera (provata il 2026-11-14: `contextJSON` = stringa JSON dentro il JSON della
pagina, `context.graphql_media` = ultimi 6 post, ognuno con `owner.username`).

L'invariante che conta: il fornitore consegna SOLO i post il cui proprietario è
l'account richiesto. `_upsert_reel` riassegna il reel all'account che lo legge:
un reel in collaborazione tra Medyca e un concorrente cambierebbe parte a ogni
giro e il contenuto di Medyca si mescolerebbe con quello dei competitor.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from core.models import PENDING, Reel, TrackedAccount
from scraper import embed_provider
from scraper.proxy import ig_proxy, scrub
from scraper.types import IGBlocked, IGSchemaChanged

PROXY = "http://user:SECRET_pw-{session}@geo.example:1"


def node(code, owner, *, video=True, ts=1794474183, likes=7, hidden=False, **kw):
    n = {
        "__typename": "GraphVideo" if video else "GraphImage",
        "id": f"id-{code}", "shortcode": code, "is_video": video,
        "display_url": f"https://cdn.example/{code}.jpg",
        "edge_media_to_caption": {"edges": [{"node": {"text": f"didascalia {code}"}}]},
        "edge_media_to_comment": {"count": 4},
        "edge_liked_by": {"count": likes},
        "like_and_view_counts_disabled": hidden,
        "taken_at_timestamp": ts,
        "owner": {"id": "1", "username": owner},
        "media_preview": "\u0000binario",
    }
    n.update(kw)
    return {"shortcode_media": n}


def page(username, nodes):
    ctx = {"context": {"username": username, "full_name": "Nome", "owner_id": 99,
                       "followers_count": 3083, "profile_pic_url": "https://cdn.example/p.jpg",
                       "graphql_media": nodes}}
    # Come la pagina vera: una stringa JSON dentro il JSON.
    return '<script>..."contextJSON":' + json.dumps(json.dumps(ctx)) + ',"x":1</script>'


class ParseEmbedTests(SimpleTestCase):
    def test_keeps_own_videos_with_their_fields(self):
        html = page("medyca.menopausa", [node("AAA", "medyca.menopausa", likes=7)])
        profile, reels, n = embed_provider.parse_embed(html, "medyca.menopausa")
        self.assertEqual(n, 1)
        self.assertEqual(profile.ig_user_id, "99")
        self.assertEqual(profile.followers_count, 3083)
        r = reels[0]
        self.assertEqual((r.shortcode, r.ig_media_id, r.caption), ("AAA", "id-AAA", "didascalia AAA"))
        self.assertEqual((r.like_count, r.comment_count, r.posted_at_ts), (7, 4, 1794474183))
        self.assertEqual(r.thumbnail_url, "https://cdn.example/AAA.jpg")
        self.assertIsNone(r.view_count)          # la pagina non le dà
        self.assertEqual(r.video_url, "")        # lo trova il download
        self.assertNotIn("media_preview", r.raw)

    def test_collaboration_reel_of_another_owner_is_dropped(self):
        """L'invariante: un reel di un altro proprietario non passa."""
        html = page("competitor_x", [
            node("OWN", "competitor_x"),
            node("COLLAB", "medyca.menopausa"),   # compare qui ma è di Medyca
        ])
        _, reels, n = embed_provider.parse_embed(html, "competitor_x")
        self.assertEqual([r.shortcode for r in reels], ["OWN"])
        self.assertEqual(n, 2)

    def test_owner_match_ignores_case(self):
        html = page("Medyca.Menopausa", [node("AAA", "MEDYCA.menopausa")])
        _, reels, _ = embed_provider.parse_embed(html, "medyca.menopausa")
        self.assertEqual(len(reels), 1)

    def test_photos_and_carousels_are_not_reels(self):
        html = page("a", [node("IMG", "a", video=False), node("VID", "a")])
        _, reels, n = embed_provider.parse_embed(html, "a")
        self.assertEqual([r.shortcode for r in reels], ["VID"])
        self.assertEqual(n, 2)

    def test_hidden_likes_are_none_not_zero(self):
        """0 sovrascriverebbe in `_upsert_reel` un valore vero; None no."""
        html = page("a", [node("V", "a", likes=0, hidden=True)])
        _, reels, _ = embed_provider.parse_embed(html, "a")
        self.assertIsNone(reels[0].like_count)

    def test_page_of_another_name_is_refused(self):
        with self.assertRaises(IGSchemaChanged):
            embed_provider.parse_embed(page("altro", [node("A", "altro")]), "richiesto")

    def test_page_without_data_is_schema_changed(self):
        with self.assertRaises(IGSchemaChanged):
            embed_provider.parse_embed("<html>niente</html>", "a")
        with self.assertRaises(IGSchemaChanged):
            embed_provider.parse_embed('"contextJSON":"{\\"context\\":{\\"username\\":\\"a\\"}}"', "a")


@override_settings(YTDLP_PROXY=PROXY, IG_PROXY="")
class FetchTests(SimpleTestCase):
    def _resp(self, status=200, text="", url="https://www.instagram.com/a/embed/"):
        return mock.Mock(status_code=status, text=text, url=url)

    def _session(self, *responses):
        s = mock.Mock()
        s.get.side_effect = list(responses)
        return mock.patch("scraper.embed_provider.ig_client.build_session", return_value=s), s

    def test_ok(self):
        p, s = self._session(self._resp(text=page("a", [node("V", "a")])))
        with p:
            _, reels, _ = embed_provider.fetch_account("a")
        self.assertEqual(len(reels), 1)
        self.assertEqual(s.get.call_count, 1)

    def test_login_redirect_is_blocked_after_exactly_one_retry(self):
        login = self._resp(url="https://www.instagram.com/accounts/login/?next=/a/embed/")
        p, s = self._session(login, login, login)
        with p, self.assertRaises(IGBlocked):
            embed_provider.fetch_account("a")
        self.assertEqual(s.get.call_count, 2)   # mai più di un secondo tentativo

    def test_429_then_ok_uses_a_new_ip(self):
        p, s = self._session(self._resp(429), self._resp(text=page("a", [node("V", "a")])))
        with p:
            embed_provider.fetch_account("a")
        proxies = [c.kwargs["proxies"]["https"] for c in s.get.call_args_list]
        self.assertEqual(len(set(proxies)), 2)  # {session} diverso a ogni richiesta

    def test_page_without_data_is_schema_changed(self):
        p, s = self._session(self._resp(text="<html/>"), self._resp(text="<html/>"))
        with p, self.assertRaises(IGSchemaChanged):
            embed_provider.fetch_account("a")

    def test_404_is_not_retried(self):
        p, s = self._session(self._resp(404))
        with p, self.assertRaises(embed_provider.AccountNotFound):
            embed_provider.fetch_account("a")
        self.assertEqual(s.get.call_count, 1)

    def test_a_name_that_is_not_a_username_is_refused_without_a_request(self):
        """`elena,palliotto`: la virgola non è un nome, e non serve chiedere."""
        p, s = self._session()
        with p, self.assertRaises(embed_provider.AccountNotFound):
            embed_provider.fetch_account("elena,palliotto")
        s.get.assert_not_called()

    def test_network_error_never_shows_the_proxy_password(self):
        def boom(*a, **kw):
            raise OSError(f"tunnel failed {kw['proxies']['https']}")
        s = mock.Mock()
        s.get.side_effect = boom
        with mock.patch("scraper.embed_provider.ig_client.build_session", return_value=s):
            with self.assertRaises(RuntimeError) as cm:
                embed_provider.fetch_account("a")
        self.assertNotIn("SECRET", str(cm.exception))

    @override_settings(YTDLP_PROXY="", IG_PROXY="")
    def test_without_proxy_it_is_blocked_in_words(self):
        with self.assertRaises(IGBlocked):
            embed_provider.fetch_account("a")


class ProxySettingTests(SimpleTestCase):
    @override_settings(YTDLP_PROXY=PROXY, IG_PROXY="")
    def test_ig_proxy_falls_back_to_ytdlp_proxy_with_fresh_session(self):
        a, b = ig_proxy(), ig_proxy()
        self.assertNotIn("{session}", a)
        self.assertNotEqual(a, b)
        self.assertTrue(embed_provider.configured())

    @override_settings(YTDLP_PROXY="http://u:Y@h:1", IG_PROXY="http://u:IG@h:2")
    def test_ig_proxy_wins_when_set(self):
        self.assertIn(":IG@", ig_proxy())

    @override_settings(YTDLP_PROXY="", IG_PROXY="")
    def test_not_configured(self):
        self.assertFalse(embed_provider.configured())

    def test_scrub_is_the_one_used_by_link_ingest(self):
        from core import link_ingest
        self.assertIs(link_ingest._scrub, scrub)
        self.assertNotIn("CRET", scrub("x http://u:S%40CRET@h:1 y", "http://u:S%40CRET@h:1"))


class NullsLastTests(TestCase):
    """I reel dell'embed non hanno visualizzazioni: in PostgreSQL i NULL, con
    `DESC`, vanno per primi e le classifiche si aprirebbero con «0 view»."""

    def setUp(self):
        from django.contrib.auth.models import User
        from rest_framework.authtoken.models import Token
        from rest_framework.test import APIClient
        self.acc = _mk_account("a", "competitor")
        self.new = Reel.objects.create(account=self.acc, shortcode="NEW", view_count=None)
        self.old = Reel.objects.create(account=self.acc, shortcode="OLD", view_count=500)
        self.mid = Reel.objects.create(account=self.acc, shortcode="MID", view_count=50)
        u = User.objects.create_user("t", password="x")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=u).key}")

    def test_reel_list_sorted_by_views_puts_empty_last(self):
        r = self.client.get("/api/v1/reels/?ordering=-view_count").json()
        self.assertEqual([x["shortcode"] for x in r["results"]], ["OLD", "MID", "NEW"])

    def test_top_reels_of_a_theme_do_not_open_with_empty_views(self):
        from core.models import ClusterRun, ReelClusterAssignment, TopicCluster
        run = ClusterRun.objects.create(scope="competitor", is_current=True)
        cl = TopicCluster.objects.create(run=run, label_it="tema", size=6)
        reels = [self.new, self.old, self.mid] + [
            Reel.objects.create(account=self.acc, shortcode=f"X{i}", view_count=10 + i)
            for i in range(3)]
        for r in reels:
            ReelClusterAssignment.objects.create(run=run, cluster=cl, reel=r)
        r = self.client.get("/api/v1/second-brain/graph/")
        self.assertEqual(r.status_code, 200)
        ids = {n["id"] for n in r.json()["nodes"]}
        # 6 reel, i 5 "top": quello senza numero resta fuori, non è il primo.
        self.assertNotIn("reel:NEW", ids)
        self.assertIn("reel:OLD", ids)


def _mk_account(name, owner):
    return TrackedAccount.objects.create(username=name, owner_type=owner, is_active=True)


@override_settings(YTDLP_PROXY=PROXY, IG_PROXY="")
class ScraperRunTests(TestCase):
    def setUp(self):
        self.mine = _mk_account("medyca.menopausa", "owned")
        self.rival = _mk_account("rival", "competitor")
        for p in (mock.patch("pipeline.agents.scraper_agent.time.sleep"),
                  mock.patch("pipeline.agents.scraper_agent._dump_raw", return_value="x.json"),
                  mock.patch("scraper.graph_client.configured", return_value=False)):
            p.start()
            self.addCleanup(p.stop)

    def _fetch(self, pages):
        """pages: {username: html | Exception}"""
        def fake(username, impersonate="chrome124"):
            v = pages[username]
            if isinstance(v, Exception):
                raise v
            return embed_provider.parse_embed(v, username)
        return mock.patch("scraper.embed_provider.fetch_account", side_effect=fake)

    def _run(self):
        from pipeline.agents import scraper_agent
        return scraper_agent.run(mock.Mock())

    def test_collaboration_reel_never_changes_side(self):
        """Medyca ha già il suo reel; il concorrente lo mostra in collaborazione."""
        Reel.objects.create(account=self.mine, shortcode="COLLAB", media_status=PENDING)
        pages = {
            "medyca.menopausa": page("medyca.menopausa", [node("COLLAB", "medyca.menopausa")]),
            "rival": page("rival", [node("COLLAB", "medyca.menopausa"), node("OWNRIVAL", "rival")]),
        }
        with self._fetch(pages):
            res = self._run()
        self.assertEqual(Reel.objects.get(shortcode="COLLAB").account, self.mine)
        self.assertEqual(Reel.objects.get(shortcode="OWNRIVAL").account, self.rival)
        self.assertEqual(Reel.objects.get(shortcode="OWNRIVAL").account.owner_type, "competitor")
        self.assertEqual(res["new_reels"], 1)

    def test_new_reel_is_pending_and_owned_account_is_read_first(self):
        pages = {"medyca.menopausa": page("medyca.menopausa", [node("M1", "medyca.menopausa")]),
                 "rival": page("rival", [node("R1", "rival")])}
        order = []
        with self._fetch(pages) as f:
            f.side_effect = lambda u, impersonate="x": (order.append(u),
                                                        embed_provider.parse_embed(pages[u], u))[1]
            self._run()
        self.assertEqual(order[0], "medyca.menopausa")
        self.assertEqual(Reel.objects.get(shortcode="M1").media_status, PENDING)

    def test_cap_per_run_keeps_the_newest_and_defers_the_rest(self):
        from core.models import ScraperConfig
        ScraperConfig.objects.create(key="embed_max_new_per_run", value={"value": 2})
        nodes = [node(f"C{i}", "rival", ts=1000 + i) for i in range(6)]
        pages = {"medyca.menopausa": page("medyca.menopausa", []), "rival": page("rival", nodes)}
        with self._fetch(pages):
            res = self._run()
        self.assertEqual(sorted(Reel.objects.values_list("shortcode", flat=True)), ["C4", "C5"])
        self.assertEqual(res["deferred"], 4)
        self.assertTrue(res["gap_possible"] == ["rival"])  # 6 su 6 nuovi: possibile buco

    def test_known_reels_do_not_count_against_the_cap_and_no_gap_is_flagged(self):
        Reel.objects.create(account=self.rival, shortcode="C0", media_status="done")
        nodes = [node(f"C{i}", "rival", ts=1000 + i) for i in range(6)]
        pages = {"medyca.menopausa": page("medyca.menopausa", []), "rival": page("rival", nodes)}
        with self._fetch(pages):
            res = self._run()
        self.assertEqual(res["new_reels"], 5)
        self.assertEqual(res["gap_possible"], [])

    def test_one_blocked_account_fails_alone_and_stays_failed(self):
        pages = {"medyca.menopausa": IGBlocked("HTTP 429"),
                 "rival": page("rival", [node("R1", "rival")])}
        with self._fetch(pages):
            res = self._run()
        self.mine.refresh_from_db()
        self.assertIn("blocked", self.mine.scrape_state["last_error"])
        self.assertEqual(self.mine.scrape_state["consecutive_failures"], 1)
        self.assertEqual(res["failed_accounts"], 1)
        self.assertEqual(res["new_reels"], 1)

    def test_every_account_failed_fails_the_stage_with_a_plain_sentence(self):
        from core.upload_workflow import ClientError
        pages = {"medyca.menopausa": IGBlocked("HTTP 429"), "rival": IGBlocked("HTTP 429")}
        with self._fetch(pages), self.assertRaises(ClientError) as cm:
            self._run()
        msg = str(cm.exception)
        self.assertIn("Instagram ha rifiutato la lettura", msg)
        # Il dettaglio tecnico non arriva al cliente: resta in last_error.
        self.assertNotIn("429", msg)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.scrape_state["last_error"], "blocked: HTTP 429")  # una volta sola

    def test_proxy_or_network_trouble_is_said_in_plain_words(self):
        from core.upload_workflow import ClientError
        boom = RuntimeError("Failed to perform, curl: (7) see https://curl.se/libcurl/")
        pages = {"medyca.menopausa": boom, "rival": boom}
        with self._fetch(pages), self.assertRaises(ClientError) as cm:
            self._run()
        self.assertIn("connessione (proxy)", str(cm.exception))
        self.assertNotIn("curl", str(cm.exception))
        self.mine.refresh_from_db()
        self.assertTrue(self.mine.scrape_state["last_error"].startswith("error: "))
        self.assertNotIn("error: error", self.mine.scrape_state["last_error"])

    def test_a_wrong_name_is_not_called_a_changed_page(self):
        """Gli altri account si leggono: questo ha un nome sbagliato."""
        pages = {"medyca.menopausa": page("medyca.menopausa", []),
                 "rival": embed_provider.IGSchemaChanged("pagina embed senza contextJSON")}
        with self._fetch(pages):
            res = self._run()
        self.assertEqual(res["failed_accounts"], 1)
        self.assertTrue(res["detail"]["rival"].startswith("not_found:"))
        self.rival.refresh_from_db()
        self.assertTrue(self.rival.scrape_state["last_error"].startswith("not_found:"))

    def test_not_found_account_stays_failed_and_does_not_log_the_old_provider(self):
        pages = {"medyca.menopausa": page("medyca.menopausa", []),
                 "rival": embed_provider.AccountNotFound("HTTP 404")}
        with self._fetch(pages), self.assertLogs("pipeline.agents.scraper_agent", "WARNING") as logs:
            self._run()
        self.assertNotIn("doc_id", "\n".join(logs.output))
        self.rival.refresh_from_db()
        self.assertEqual(self.rival.scrape_state["consecutive_failures"], 1)

    def test_default_cap_is_five_new_reels_per_run(self):
        """Decisione 8: il buco rientra piano, il ritmo che la catena regge."""
        nodes = [node(f"D{i}", "rival", ts=1000 + i) for i in range(6)]
        pages = {"medyca.menopausa": page("medyca.menopausa", []), "rival": page("rival", nodes)}
        with self._fetch(pages):
            res = self._run()
        self.assertEqual(Reel.objects.count(), 5)
        self.assertEqual(res["deferred"], 1)

    def test_three_blocks_in_a_row_stop_the_run(self):
        for n in ("c", "d"):
            _mk_account(n, "competitor")
        pages = {u: IGBlocked("HTTP 429") for u in ("medyca.menopausa", "rival", "c", "d")}
        with self._fetch(pages) as f:
            with self.assertRaises(Exception):
                self._run()
        self.assertEqual(f.call_count, 3)   # il quarto non viene nemmeno chiesto

    def test_without_proxy_the_stage_fails_saying_suspended_and_calls_nobody(self):
        """Non "done": la pagina Stato direbbe "sospesa" e "tutto in ordine"."""
        from core.upload_workflow import ClientError
        with override_settings(YTDLP_PROXY="", IG_PROXY=""), self._fetch({}) as f:
            with self.assertRaises(ClientError) as cm:
                self._run()
        self.assertIn("sospesa", str(cm.exception))
        f.assert_not_called()

    def test_apify_is_never_called(self):
        pages = {"medyca.menopausa": page("medyca.menopausa", []), "rival": page("rival", [])}
        with self._fetch(pages), \
                mock.patch("scraper.apify_provider.fetch_reels") as ap, \
                mock.patch("scraper.apify_provider.enabled", return_value=True):
            self._run()
        ap.assert_not_called()


@override_settings(YTDLP_PROXY=PROXY, IG_PROXY="")
class DownloaderTests(TestCase):
    def setUp(self):
        acc = _mk_account("a", "competitor")
        self.reel = Reel.objects.create(account=acc, shortcode="ZZZ", media_status=PENDING)
        from pipeline.agents import downloader_agent as d
        self.d = d
        for target, rv in (("_has_audio", True), ("_extract_audio", None),
                           ("_media_duration", 31.5), ("_download", None)):
            p = mock.patch.object(d, target, return_value=rv)
            p.start()
            self.addCleanup(p.stop)

    def _go(self, fetch):
        with mock.patch.object(self.d, "_ytdlp_fetch", side_effect=fetch) as f, \
                mock.patch.object(Path, "unlink"):
            self.d._process_one(self.reel)
        return f

    def test_direct_first_and_duration_read_from_the_file(self):
        f = self._go(lambda r, m, proxy="": {"view_count": 1200})
        self.assertEqual(f.call_count, 1)
        self.assertEqual(f.call_args.kwargs.get("proxy", ""), "")
        self.reel.refresh_from_db()
        self.assertEqual(self.reel.duration_s, 31.5)
        self.assertEqual(self.reel.view_count, 1200)
        self.assertEqual(self.reel.media_status, "done")

    def test_blocked_direct_retries_once_through_the_proxy(self):
        from scraper.types import IGThrottled
        calls = []

        def fetch(r, m, proxy=""):
            calls.append(proxy)
            if not proxy:
                raise IGThrottled("login")
            return {}
        self._go(fetch)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], "")
        self.assertNotIn("{session}", calls[1])

    def test_blocked_without_proxy_defers(self):
        from scraper.types import IGThrottled
        with override_settings(YTDLP_PROXY="", IG_PROXY=""):
            with self.assertRaises(IGThrottled):
                self._go(mock.Mock(side_effect=IGThrottled("login")))

    def test_counts_from_yt_dlp_are_sane_and_never_worse(self):
        b = self.d._better_count
        self.assertEqual(b("view_count", None, 900), 900)
        self.assertEqual(b("view_count", 1000, 900), 1000)       # mai peggio
        self.assertEqual(b("comment_count", 4, -1), 4)           # mai negativo
        self.assertEqual(b("comment_count", 4, None), 4)
        self.assertEqual(b("comment_count", None, 5), 5)
        self.assertEqual(b("like_count", 7, 9), 9)

    def test_hidden_likes_stay_hidden_whatever_yt_dlp_says(self):
        """Misurato: yt-dlp dà like_count=3 su due reel diversi di un account da
        3000 follower che nasconde i like: non è un conteggio vero."""
        self.reel.like_count = None
        self.reel.save()
        self._go(lambda r, m, proxy="": {"like_count": 3, "comment_count": 4})
        self.reel.refresh_from_db()
        self.assertIsNone(self.reel.like_count)
        self.assertEqual(self.reel.comment_count, 4)

    def test_a_negative_like_count_never_reaches_the_row(self):
        self.reel.like_count = 10
        self.reel.save()
        self._go(lambda r, m, proxy="": {"like_count": -1})
        self.reel.refresh_from_db()
        self.assertEqual(self.reel.like_count, 10)

    def test_prefetch_is_gone(self):
        self.assertFalse(hasattr(self.d, "_prefetch_urls"))
