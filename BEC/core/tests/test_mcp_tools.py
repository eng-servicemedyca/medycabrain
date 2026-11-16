"""
The MCP gate test: all ten connector tools, wired end to end, on a tiny seeded
corpus — with the embedder and the LLM reranker FAKED so it runs in CI, where
`requirements-ci.txt` deliberately has no torch, no sentence-transformers and no
LLM keys (the heavy models are imported lazily and never load here).

It tests the CONTRACT and the WIRING, not retrieval quality: the shape of every
hit, that each typed search keeps only its side of the corpus, that ownership
labels are right (competitor → "competitor", owned → "Medyca", reference
material → "riferimento", never a bare "competitor"/"Medyca"), that a typed
search does not starve when its type is the minority, and that all ten tools are
still registered on the server. Retrieval quality against real models is
`manage.py eval_mcp`, which runs on the VPS, not in this gate.

Two tricks keep the heavy models out of the path (see the design,
`.claude/tasks/2026-09-16-mcp-search-affidabile.md`):
  - `core.knowledge._get_embedder` is stubbed with a fake whose `.encode()`
    returns fixed-width normalised vectors. It is the ONLY place search needs the
    embedder, because document vectors are read from the DB.
  - every seeded text is < 700 chars, so `_best_passage` short-circuits to the
    single chunk without ever encoding it (`core/knowledge.py`, `len(parts)==1`).
  - `core.knowledge.client.chat_json` (the reranker's one network call) is
    stubbed to `{}`, which makes `_rerank` keep the blend order — the wiring runs,
    nothing leaves the process.
"""

from __future__ import annotations

import zlib
from unittest import mock

import numpy as np
from django.test import SimpleTestCase, TestCase

# Tool functions are plain module-level callables: @server.tool returns the
# function unchanged, so the gate can call them in-process without the HTTP
# server. Importing the module runs django.setup() (idempotent under the test
# runner) and spawns a daemon warm thread whose embedder import is lazy and
# swallowed — it never touches this test's path.
from mcp_bridge import server

_DIM = 16


def _vec(text: str) -> np.ndarray:
    """A deterministic non-negative unit vector from a text's word buckets.

    Non-negative so any two vectors have cosine >= 0 (keeps the relevance floor
    well-behaved on a tiny corpus); a shared word lifts the similarity, which is
    all the ranking needs here. crc32, not hash(), so it does not move with
    PYTHONHASHSEED — the stored document vectors and the query vector must land
    in the same buckets.
    """
    v = np.zeros(_DIM, dtype=np.float32)
    import re
    for w in re.findall(r"\w+", (text or "").lower()):
        v[zlib.crc32(w.encode()) % _DIM] += 1.0
    n = float(np.linalg.norm(v))
    if n == 0.0:
        v[:] = 1.0 / np.sqrt(_DIM)
        return v
    return v / n


class _FakeEmbedder:
    """Stands in for SentenceTransformer: same `.encode` signature, no torch."""

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        return np.asarray([_vec(t) for t in texts], dtype=np.float32)


class MCPToolsGate(TestCase):
    @classmethod
    def setUpTestData(cls):
        from core.models import (
            DONE, ArgumentAssignment, BlogSource, ClusterRun, DocumentArgument,
            Enrichment, KnowledgeDocument, Reel, ReelArgument, ReelEmbedding,
            TopicCluster, TrackedAccount, Transcript,
        )

        owned_acc = TrackedAccount.objects.create(
            username="medyca.menopausa", owner_type="owned")
        comp_acc = TrackedAccount.objects.create(
            username="competitor.ig", owner_type="competitor")

        def _reel(acc, shortcode, text, topic, views=100):
            r = Reel.objects.create(
                account=acc, shortcode=shortcode, caption=text,
                enrich_status=DONE, view_count=views, like_count=10)
            Transcript.objects.create(reel=r, text=text)
            Enrichment.objects.create(
                reel=r, summary_it=f"Riassunto: {topic}", topics=[topic],
                primary_topic=topic, hook_text=f"Gancio su {topic}",
                hook_analysis_it="Analisi del gancio.",
                content_format="talking_head",
                target_audience_it="Donne in menopausa.")
            ReelEmbedding.objects.create(
                reel=r, vector=_vec(text).tolist(), chunk_vectors=[])
            return r

        cls.reel_owned = _reel(
            owned_acc, "OWNEDREEL1",
            "Vampate di calore in menopausa: rimedi e terapia ormonale bioidentica.",
            "vampate", views=500)
        cls.reel_comp = _reel(
            comp_acc, "COMPREEL1",
            "Vampate di calore: cosa dicono i competitor sulla menopausa.",
            "vampate", views=300)
        # Pad the corpus so reels are the clear majority — the pre-fix starvation
        # case, where a typed article search over-fetched a reel-dominated pool.
        for i in range(6):
            _reel(comp_acc, f"COMPREEL{i+2}",
                  "Ormoni e menopausa: contenuto generico del competitor.",
                  "ormoni")

        owned_blog = BlogSource.objects.create(
            name="Blog Medyca", owner_type="owned",
            index_url="https://medyca.it/blog")
        comp_blog = BlogSource.objects.create(
            name="Blog Competitor", owner_type="competitor",
            index_url="https://competitor.example/blog")

        owned_text = ("Il metodo Marion Gluck applica la terapia ormonale "
                      "bioidentica alla menopausa con ormoni su misura.")
        cls.doc_owned = KnowledgeDocument.objects.create(
            source_type="blog", source=owned_blog, owner_type="owned",
            source_url="https://medyca.it/blog/marion-gluck",
            title="Il metodo Marion Gluck", content_text=owned_text,
            summary_it="Metodo Marion Gluck.", primary_topic="marion gluck",
            is_on_topic=True, embedding=_vec(owned_text).tolist())
        DocumentArgument.objects.create(
            document=cls.doc_owned,
            text_it="Il metodo usa ormoni bioidentici su misura.",
            quote="terapia ormonale bioidentica")

        comp_text = ("La terapia ormonale in menopausa secondo un blog "
                     "competitor: indicazioni generali e cautele.")
        cls.doc_comp = KnowledgeDocument.objects.create(
            source_type="blog", source=comp_blog, owner_type="competitor",
            source_url="https://competitor.example/blog/tos",
            title="Terapia ormonale in menopausa", content_text=comp_text,
            summary_it="TOS competitor.", primary_topic="terapia ormonale",
            is_on_topic=True, embedding=_vec(comp_text).tolist())

        # Reference material: a TV episode the client added on purpose. It carries
        # owner_type="competitor" and is_on_topic=False (a menopause-centred
        # verdict would reject it) but is_inspiration exempts it — it must appear
        # in cerca_riferimenti and be labelled by its source, "YouTVRS".
        rif_text = ("Puntata Canale Salute: sindrome metabolica, sovrappeso e "
                    "pressione arteriosa, salute metabolica.")
        cls.doc_rif = KnowledgeDocument.objects.create(
            source_type="video", source=None, owner_type="competitor",
            source_url="https://vimeo.com/1220776839",
            title="Canale Salute — Sindrome metabolica", content_text=rif_text,
            author="YouTVRS", summary_it="Sindrome metabolica.",
            primary_topic="sindrome metabolica", is_on_topic=False,
            off_topic_reason="Tratta salute metabolica, non menopausa.",
            is_inspiration=True, embedding=_vec(rif_text).tolist())

        # A current competitor cluster with one assigned reel argument, for `temi`.
        run = ClusterRun.objects.create(
            scope="competitor", status="done", is_current=True)
        cluster = TopicCluster.objects.create(
            run=run, label_it="Vampate di calore", description_it="Tema vampate.",
            size=2, keywords=["vampate", "calore", "menopausa"])
        arg = ReelArgument.objects.create(
            reel=cls.reel_comp, text_it="Le vampate si trattano con la TOS.",
            quote="Vampate di calore")
        ArgumentAssignment.objects.create(
            run=run, argument=arg, cluster=cluster, similarity=0.9)

    def setUp(self):
        import core.knowledge as knowledge
        # The index cache is module-global and outlives a test; drop it so this
        # class's seeded corpus is read fresh.
        knowledge._INDEX_CACHE.clear()
        self._p1 = mock.patch.object(knowledge, "_get_embedder",
                                     return_value=_FakeEmbedder())
        self._p2 = mock.patch.object(knowledge.client, "chat_json",
                                     return_value={})
        self._p1.start()
        self._p2.start()
        self.addCleanup(self._p1.stop)
        self.addCleanup(self._p2.stop)

    # ── hit shape ──────────────────────────────────────────────────────────
    _HIT_KEYS = {"id", "tipo", "di", "titolo", "estratto", "url",
                 "ispirazione", "pertinenza", "apri_nel_brain"}

    def test_search_hits_have_the_documented_shape(self):
        hits = server.cerca_tutto("menopausa vampate terapia", limite=8)
        self.assertTrue(hits, "cerca_tutto non ha restituito nulla")
        for h in hits:
            self.assertEqual(set(h), self._HIT_KEYS, h)
            self.assertRegex(h["id"], r"^(reel|blog):\d+$")

    # ── self-explanatory references: title + source + link on every hit ────
    def test_every_hit_carries_a_brain_link_for_its_own_id(self):
        """The client could not tell which content 'blog:843' meant.

        Every hit must be citable as "titolo — di (link)", and the link must
        point at THIS hit: a link built from the wrong id would send the client
        to somebody else's content, which is worse than no link at all.
        """
        for h in server.cerca_tutto("menopausa vampate terapia", limite=8):
            kind, pk = h["id"].split(":")
            self.assertEqual(h["apri_nel_brain"],
                             f"{server.BRAIN_BASE_URL}/content/{kind}/{pk}", h)
            self.assertTrue(h["titolo"], h)
            self.assertTrue(h["di"], h)

    def test_brain_link_uses_the_kind_and_id_of_the_hit(self):
        hit = server._hit({"kind": "blog", "id": 843, "owner": "owned",
                           "title": "Il metodo Marion Gluck"})
        self.assertTrue(hit["apri_nel_brain"].endswith("/content/blog/843"), hit)
        reel = server._hit({"kind": "reel", "id": 199, "owner": "competitor",
                            "account": "competitor.ig", "title": "t"})
        self.assertTrue(reel["apri_nel_brain"].endswith("/content/reel/199"), reel)

    def test_brain_base_url_is_not_hardcoded_in_the_link(self):
        """The brain moves with the deployment; a stale link is a wrong link."""
        with mock.patch.object(server, "BRAIN_BASE_URL", "https://brain.example"):
            hit = server._hit({"kind": "blog", "id": 7, "owner": "owned",
                               "title": "t"})
        self.assertEqual(hit["apri_nel_brain"],
                         "https://brain.example/content/blog/7")

    def test_invite_page_uses_public_url(self):
        # The invite page hands the client the connector address: it must come
        # from MCP_PUBLIC_URL, not a hardcoded host that no longer answers.
        import asyncio
        sent = []

        async def send(msg):
            sent.append(msg)

        with mock.patch.object(server, "MCP_PUBLIC_URL", "https://mcp.example"), \
                mock.patch.object(server, "MCP_SECRET", "s3cret"):
            asyncio.run(server._invite_page(send))
        body = sent[1]["body"].decode()
        self.assertIn("https://mcp.example/s3cret/mcp", body)
        self.assertNotIn("messtudent.com", body)

    def test_server_instructions_forbid_citing_a_bare_number(self):
        # The instructions are what actually makes the client's Claude cite
        # readably; without this line the new field is just unused data.
        instr = server.server.instructions
        self.assertIn("apri_nel_brain", instr)
        self.assertIn("titolo", instr)

    # ── typed searches keep only their side ────────────────────────────────
    def test_cerca_reel_returns_only_reels(self):
        hits = server.cerca_reel("vampate di calore menopausa", limite=8)
        self.assertTrue(hits)
        self.assertTrue(all(h["id"].startswith("reel:") for h in hits), hits)
        self.assertTrue(all(h["tipo"] == "reel" for h in hits), hits)

    def test_cerca_articoli_returns_only_articles(self):
        hits = server.cerca_articoli("terapia ormonale menopausa", limite=8)
        self.assertTrue(hits)
        self.assertTrue(all(h["id"].startswith("blog:") for h in hits), hits)

    def test_cerca_riferimenti_returns_only_inspiration(self):
        hits = server.cerca_riferimenti("sindrome metabolica pressione", limite=8)
        self.assertTrue(hits, "cerca_riferimenti non ha trovato il materiale")
        self.assertTrue(all(h["ispirazione"] for h in hits), hits)
        self.assertIn(f"blog:{self.doc_rif.id}", [h["id"] for h in hits])

    # ── the client's road must not break when Groq refuses ─────────────────
    def test_search_answers_in_plain_order_when_groq_refuses_and_never_asks_ollama(self):
        """The reranker is Groq-only (2026-11-15). Whatever Groq does — per-minute
        cap, daily cap, dead key, network — the search must still answer, at
        once, with the blend order, and must not queue behind the local model."""
        from django.test import override_settings

        from llm import client
        endpoint = {"name": "groq", "base_url": "http://groq.invalid/v1",
                    "api_key": "k", "models": {"bulk": "b", "reasoning": "r",
                                               "analysis": "a"}, "chain": ["a", "b"]}
        plain = [h["id"] for h in
                 server.cerca_tutto("menopausa vampate terapia", limite=8)]
        self.assertTrue(plain)

        self._p2.stop()  # the real chat_json now, so the whole chain is exercised
        for err in (client.LLMRateLimit(5), client.LLMRateLimit(5, daily=True),
                    client.LLMCreditError("401"), RuntimeError("rete giu'")):
            client._fast_disabled.clear()
            with self.subTest(err=repr(err)), \
                 override_settings(FAST_ENDPOINTS=[endpoint],
                                   LLM_PROVIDER_ORDER=["fast", "ollama"]), \
                 mock.patch.object(client, "_fast_chat", side_effect=err), \
                 mock.patch.object(client.time, "sleep") as sleep, \
                 mock.patch.object(client, "_ollama_chat") as ollama, \
                 mock.patch.object(client, "_ollama_slot") as slot:
                hits = server.cerca_tutto("menopausa vampate terapia", limite=8)
                self.assertEqual([h["id"] for h in hits], plain)
                ollama.assert_not_called()
                slot.assert_not_called()
                sleep.assert_not_called()   # no waiting either: the client is waiting

    # ── no starvation: the minority type still comes back ──────────────────
    def test_typed_article_search_does_not_starve_against_a_reel_majority(self):
        # Eight reels, two on-topic articles: pre-fix the over-fetched pool was
        # mostly reels and the post-filter could return zero. Both articles must
        # come back now that the type filter runs before the rerank.
        ids = {h["id"] for h in
               server.cerca_articoli("terapia ormonale menopausa", limite=8)}
        self.assertIn(f"blog:{self.doc_owned.id}", ids, ids)
        self.assertIn(f"blog:{self.doc_comp.id}", ids, ids)

    # ── ownership / reference labels ───────────────────────────────────────
    def test_hit_label_owned_competitor_and_reference(self):
        owned = server._hit({"kind": "blog", "id": 1, "owner": "owned",
                             "account": "Blog Medyca", "title": "t"})
        self.assertEqual(owned["di"], "Medyca")

        comp = server._hit({"kind": "reel", "id": 2, "owner": "competitor",
                            "account": "competitor.ig", "title": "t"})
        self.assertIn("competitor", comp["di"].lower())

        rif = server._hit({"kind": "blog", "id": 3, "owner": "competitor",
                          "account": "YouTVRS", "inspiration": True, "title": "t"})
        self.assertEqual(rif["di"], "riferimento: YouTVRS")
        # Reference material is neither side, spelled out: never a bare label.
        self.assertNotIn("competitor", rif["di"].lower())
        self.assertNotIn("medyca", rif["di"].lower())

    def test_reference_search_never_labels_inspiration_as_a_side(self):
        for h in server.cerca_riferimenti("sindrome metabolica", limite=8):
            self.assertTrue(h["di"].startswith("riferimento:"), h)
            self.assertNotIn("competitor", h["di"].lower())
            self.assertNotIn("medyca", h["di"].lower())

    # ── leggi_* ────────────────────────────────────────────────────────────
    def test_leggi_reel_reads_one_reel_with_its_video_fields(self):
        doc = server.leggi_reel(f"reel:{self.reel_owned.id}")
        self.assertEqual(doc["tipo"], "reel")
        self.assertEqual(doc["di"], "Medyca")
        self.assertIn("vampate", doc["trascrizione"].lower())
        self.assertIn("gancio", doc)

    def test_leggi_articolo_labels_owned_and_reference(self):
        owned = server.leggi_articolo(f"blog:{self.doc_owned.id}")
        self.assertEqual(owned["di"], "Medyca")
        self.assertEqual(owned["tipo"], "articolo")

        rif = server.leggi_articolo(f"blog:{self.doc_rif.id}")
        self.assertEqual(rif["di"], "riferimento: YouTVRS")
        self.assertEqual(rif["tipo"], "video di riferimento")
        self.assertTrue(rif["ispirazione"])
        self.assertNotIn("competitor", rif["di"].lower())

    def test_leggi_gives_back_the_link_it_must_be_cited_with(self):
        # Reading a content is where Claude writes the answer from, so the link
        # has to be there too — not only on the search hit it came from.
        reel = server.leggi_reel(f"reel:{self.reel_owned.id}")
        self.assertEqual(
            reel["apri_nel_brain"],
            f"{server.BRAIN_BASE_URL}/content/reel/{self.reel_owned.id}")
        self.assertTrue(reel["titolo"])

        doc = server.leggi_articolo(f"blog:{self.doc_owned.id}")
        self.assertEqual(
            doc["apri_nel_brain"],
            f"{server.BRAIN_BASE_URL}/content/blog/{self.doc_owned.id}")
        self.assertEqual(doc["titolo"], "Il metodo Marion Gluck")

        # Same through the untyped tool, which routes on the prefix.
        self.assertEqual(server.leggi(f"blog:{self.doc_rif.id}")["apri_nel_brain"],
                         f"{server.BRAIN_BASE_URL}/content/blog/{self.doc_rif.id}")

    def test_leggi_routes_on_the_id_prefix(self):
        self.assertEqual(server.leggi(f"reel:{self.reel_owned.id}")["tipo"], "reel")
        self.assertEqual(
            server.leggi(f"blog:{self.doc_comp.id}")["tipo"], "articolo")
        self.assertIn("errore", server.leggi("nope:1"))

    # ── the ORM-only tools ─────────────────────────────────────────────────
    def test_panoramica_counts_by_side_and_keeps_reference_apart(self):
        pano = server.panoramica()
        self.assertEqual(pano["reel"]["medyca"], 1)
        self.assertEqual(pano["reel"]["competitor"], 7)
        self.assertEqual(pano["articoli"]["medyca"], 1)
        self.assertEqual(pano["articoli"]["competitor"], 1)
        # The reference video is not folded into the article totals.
        self.assertEqual(pano["materiale_di_riferimento"]["totale"], 1)

    def test_fonti_blog_labels_each_source(self):
        by_name = {b["nome"]: b for b in server.fonti_blog()}
        self.assertEqual(by_name["Blog Medyca"]["di"], "Medyca")
        self.assertEqual(by_name["Blog Competitor"]["di"], "competitor")

    def test_fonti_blog_leaves_out_removed_sources(self):
        from django.utils import timezone

        from core.models import BlogSource
        BlogSource.objects.filter(name="Blog Competitor").update(
            removed_at=timezone.now(), is_active=False)
        names = {b["nome"] for b in server.fonti_blog()}
        self.assertNotIn("Blog Competitor", names)
        self.assertIn("Blog Medyca", names)

    def test_temi_returns_the_current_competitor_cluster(self):
        temi = server.temi(scope="competitor")
        self.assertTrue(temi)
        self.assertEqual(temi[0]["tema"], "Vampate di calore")
        self.assertTrue(temi[0]["esempi_affermazioni"])

    def test_tipo_names_an_interview_and_a_plain_video(self):
        from core.models import KnowledgeDocument
        intervista = KnowledgeDocument.objects.create(
            source_type="manual", owner_type="owned", title="Intervista",
            source_url="upload://x", content_text="Parla la dottoressa.")
        video = KnowledgeDocument.objects.create(
            source_type="video", owner_type="owned", title="Puntata",
            source_url="https://vimeo.com/1", content_text="Una puntata.")
        self.assertEqual(
            server.leggi_articolo(f"blog:{intervista.id}")["tipo"], "intervista")
        self.assertEqual(
            server.leggi_articolo(f"blog:{video.id}")["tipo"], "video")

    # ── contract barrier: the ten tools stay registered ────────────────────
    def test_all_ten_tools_are_registered_on_the_server(self):
        names = {t.name for t in server.server._tool_manager.list_tools()}
        self.assertEqual(names, {
            "panoramica", "cerca_reel", "cerca_articoli", "cerca_tutto",
            "leggi_reel", "leggi_articolo", "leggi", "cerca_riferimenti",
            "fonti_blog", "temi",
        })


def _testo_lungo(frasi: int) -> str:
    """A text of `frasi` sentences, each different, with one paragraph break."""
    righe = [f"Questa è la frase numero {i} della puntata sulla menopausa."
             for i in range(frasi)]
    righe[frasi // 2] += "\n"
    return " ".join(righe)


class TestoPerParti(SimpleTestCase):
    """`_parti`: the text in pieces that glue back to the exact text."""

    def test_a_short_text_is_one_part_and_identical(self):
        self.assertEqual(server._parti("Poche parole."), ["Poche parole."])
        self.assertEqual(server._parti(""), [""])

    def test_a_text_just_at_the_limit_is_one_part(self):
        t = "a" * 100
        self.assertEqual(server._parti(t, 100), [t])

    def test_the_parts_glue_back_to_the_exact_text(self):
        t = _testo_lungo(1200)  # about 70 000 characters
        self.assertGreater(len(t), 60_000)
        parti = server._parti(t)
        self.assertEqual("".join(parti), t)
        self.assertGreaterEqual(len(parti), 3)
        for p in parti:
            self.assertTrue(p)
            self.assertLessEqual(len(p), server.TESTO_MAX_CARATTERI)

    def test_every_part_but_the_last_ends_at_a_sentence_end(self):
        parti = server._parti(_testo_lungo(1200))
        for p in parti[:-1]:
            self.assertRegex(p, r"(?:[.?!] |\n)$", p[-40:])

    def test_a_cut_without_sentence_ends_falls_on_a_space_not_mid_word(self):
        t = " ".join(["parola"] * 500)  # no full stop at all
        parti = server._parti(t, 100)
        self.assertEqual("".join(parti), t)
        for p in parti[:-1]:
            self.assertTrue(p.endswith(" "), repr(p[-10:]))
            self.assertLessEqual(len(p), 100)
        for p in parti:  # every word survives whole
            self.assertTrue(all(w == "parola" for w in p.split()))

    def test_a_text_with_no_space_is_cut_hard_and_still_ends(self):
        t = "x" * 250
        parti = server._parti(t, 100)
        self.assertEqual(parti, ["x" * 100, "x" * 100, "x" * 50])

    def test_a_sentence_end_outside_the_last_window_is_not_used(self):
        # The only full stop is at the very start: cutting there would make a
        # tiny piece. The space nearer the limit wins.
        t = "Ok. " + " ".join(["parola"] * 3000)
        parti = server._parti(t, 3000)
        self.assertGreater(len(parti[0]), 2000)

    def test_the_part_number_is_read_as_text_too(self):
        self.assertEqual(server._parse_parte("2"), 2)
        self.assertEqual(server._parse_parte(" 3 "), 3)
        self.assertEqual(server._parse_parte(1), 1)
        for bad in (0, -1, "0", "due", "", None, True, "1.5"):
            with self.subTest(bad=bad):
                self.assertIn("errore", server._parse_parte(bad))

    def test_a_part_out_of_range_is_a_clear_error(self):
        t = _testo_lungo(1200)
        n = len(server._parti(t))
        err = server._pezzo(t, n + 1, "leggi_articolo")
        self.assertEqual(err, {"errore": f"questo contenuto ha {n} parti: "
                                         f"chiedi una parte da 1 a {n}"})
        uno = server._pezzo("corto", 2, "leggi_articolo")
        self.assertEqual(uno, {"errore": "questo contenuto ha 1 parte: chiedi la parte 1"})

    def test_the_analysis_note_only_when_the_text_is_longer_than_what_was_read(self):
        self.assertEqual(server._nota_analisi("a" * 6000, 6000), "")
        nota = server._nota_analisi("a" * 16865, 6000)
        self.assertIn("primi 6.000 caratteri su 16.865", nota)
        self.assertIn("vale il testo", nota)

    def test_the_note_is_not_said_once_the_analysis_read_the_whole_text(self):
        self.assertEqual(server._nota_analisi("a" * 16865, 6000, "done"), "")
        for stato in ("pending", "failed"):
            with self.subTest(stato=stato):
                self.assertIn("primi 6.000 caratteri su 16.865",
                              server._nota_analisi("a" * 16865, 6000, stato))

    def test_the_numbers_in_the_note_are_the_ones_the_pipeline_reads(self):
        from pipeline.agents import enrich_agent, knowledge_agent
        self.assertEqual(knowledge_agent.DOC_SUMMARY_CHARS_READ, 6000)
        self.assertEqual(knowledge_agent.DOC_CLAIMS_CHARS_READ, 8000)
        self.assertEqual(enrich_agent.TRANSCRIPT_CHARS_READ, 3000)


class LeggiTestoLungo(TestCase):
    """`leggi_*` on a text over the threshold, through the three tools."""

    def setUp(self):
        from core.models import (Enrichment, KnowledgeDocument, Reel,
                                 TrackedAccount, Transcript)
        self.testo = _testo_lungo(1200)
        # No vector on purpose: the search index never sees these long texts.
        self.doc = KnowledgeDocument.objects.create(
            source_type="video", owner_type="owned", is_inspiration=True,
            author="TVRS SRL", title="Menopausa parte 1",
            source_url="https://vimeo.com/1", content_text=self.testo,
            summary_it="Riassunto dell'inizio.")
        acc = TrackedAccount.objects.create(username="lungo.ig",
                                            owner_type="competitor")
        self.reel = Reel.objects.create(account=acc, shortcode="LUNGO1",
                                        caption="c")
        Transcript.objects.create(reel=self.reel, text=self.testo)
        Enrichment.objects.create(reel=self.reel, summary_it="Sintesi.",
                                  primary_topic="vampate")
        self.n = len(server._parti(self.testo))

    def _tutte(self, chiama):
        """Read every part the way a client would: following parte_successiva."""
        pezzi, risposta = [], chiama(1)
        while True:
            pezzi.append(risposta)
            if risposta["parte_successiva"] is None:
                return pezzi
            risposta = chiama(risposta["parte_successiva"])

    def test_article_parts_followed_to_the_end_give_the_exact_text(self):
        pezzi = self._tutte(
            lambda p: server.leggi_articolo(f"blog:{self.doc.id}", parte=p))
        self.assertEqual(len(pezzi), self.n)
        self.assertEqual("".join(r["testo"] for r in pezzi), self.testo)
        for i, r in enumerate(pezzi, 1):
            self.assertEqual((r["parte"], r["parti_totali"]), (i, self.n))
            self.assertEqual(r["caratteri_totali"], len(self.testo))
            self.assertTrue(r["troncato"])
        self.assertIn("parte=2", pezzi[0]["come_leggere_il_resto"])
        self.assertIn("leggi_articolo", pezzi[0]["come_leggere_il_resto"])
        self.assertIn("ultima parte", pezzi[-1]["come_leggere_il_resto"])
        # The signal to ask for more is parte_successiva, not troncato: on the
        # last part troncato stays true, parte_successiva is empty.
        ultima = pezzi[-1]
        self.assertTrue(ultima["troncato"])
        self.assertIsNone(ultima["parte_successiva"])
        self.assertIn("il testo finisce qui", ultima["come_leggere_il_resto"])

    def test_reel_parts_followed_to_the_end_give_the_exact_text(self):
        pezzi = self._tutte(
            lambda p: server.leggi_reel(f"reel:{self.reel.id}", parte=p))
        self.assertEqual("".join(r["trascrizione"] for r in pezzi), self.testo)
        self.assertIn("leggi_reel", pezzi[0]["come_leggere_il_resto"])

    def test_leggi_routes_the_part_for_both_kinds(self):
        a = server.leggi(f"blog:{self.doc.id}", parte=2)
        self.assertEqual((a["parte"], a["tipo"]), (2, "video di riferimento"))
        r = server.leggi(f"reel:{self.reel.id}", parte=2)
        self.assertEqual(r["parte"], 2)
        self.assertIn("trascrizione", r)

    def test_the_part_can_be_written_as_text(self):
        for chiama, id_ in ((server.leggi_articolo, f"blog:{self.doc.id}"),
                            (server.leggi_reel, f"reel:{self.reel.id}"),
                            (server.leggi, f"blog:{self.doc.id}")):
            with self.subTest(chiama=chiama.__name__):
                self.assertEqual(chiama(id_, parte="2")["parte"], 2)

    def test_a_part_out_of_range_or_not_a_number_is_an_error_never_empty(self):
        for chiama, id_ in ((server.leggi_articolo, f"blog:{self.doc.id}"),
                            (server.leggi_reel, f"reel:{self.reel.id}"),
                            (server.leggi, f"blog:{self.doc.id}")):
            for parte in (self.n + 1, 99, 0, -1, "boh"):
                with self.subTest(chiama=chiama.__name__, parte=parte):
                    r = chiama(id_, parte=parte)
                    self.assertEqual(set(r), {"errore"}, r)
                    self.assertTrue(r["errore"])

    def test_part_two_is_light_but_still_citable(self):
        r = server.leggi_articolo(f"blog:{self.doc.id}", parte=2)
        self.assertEqual(
            set(r), {"tipo", "titolo", "di", "apri_nel_brain", "url", "testo",
                     "caratteri_totali", "parte", "parti_totali", "troncato",
                     "parte_successiva", "come_leggere_il_resto"})
        self.assertEqual(r["di"], "riferimento: TVRS SRL")
        self.assertTrue(r["apri_nel_brain"].endswith(f"/content/blog/{self.doc.id}"))
        rr = server.leggi_reel(f"reel:{self.reel.id}", parte=2)
        self.assertEqual(rr["di"], "competitor: @lungo.ig")
        self.assertNotIn("riassunto", rr)
        self.assertNotIn("affermazioni", rr)

    def test_part_one_carries_summary_claims_and_the_analysis_note(self):
        a = server.leggi_articolo(f"blog:{self.doc.id}")
        self.assertEqual(a["riassunto"], "Riassunto dell'inizio.")
        self.assertIn("affermazioni", a)
        self.assertIn("primi 6.000 caratteri", a["nota_analisi"])
        r = server.leggi_reel(f"reel:{self.reel.id}")
        self.assertIn("primi 3.000 caratteri", r["nota_analisi"])

    def test_the_note_follows_full_text_status_for_both_kinds(self):
        for stato, voluta in (("done", False), ("pending", True), ("failed", True)):
            with self.subTest(stato=stato):
                self.doc.full_text_status = stato
                self.doc.save()
                self.reel.full_text_status = stato
                self.reel.save()
                a = server.leggi_articolo(f"blog:{self.doc.id}")
                r = server.leggi_reel(f"reel:{self.reel.id}")
                self.assertEqual("nota_analisi" in a, voluta)
                self.assertEqual("nota_analisi" in r, voluta)

    def test_up_to_twelve_claims_are_given_not_ten(self):
        from core.models import DocumentArgument, ReelArgument
        for i in range(14):
            DocumentArgument.objects.create(document=self.doc, text_it=f"a{i}", quote=f"q{i}")
            ReelArgument.objects.create(reel=self.reel, text_it=f"a{i}", quote=f"q{i}")
        self.assertEqual(
            len(server.leggi_articolo(f"blog:{self.doc.id}")["affermazioni"]), 12)
        self.assertEqual(
            len(server.leggi_reel(f"reel:{self.reel.id}")["affermazioni"]), 12)

    def test_a_short_text_is_one_whole_part_without_a_note(self):
        from core.models import KnowledgeDocument
        corto = KnowledgeDocument.objects.create(
            source_type="blog", owner_type="owned", title="Breve",
            source_url="https://medyca.it/breve", content_text="Un testo breve.")
        r = server.leggi_articolo(f"blog:{corto.id}")
        self.assertEqual(r["testo"], "Un testo breve.")
        self.assertEqual((r["parte"], r["parti_totali"], r["troncato"],
                          r["parte_successiva"]), (1, 1, False, None))
        self.assertEqual(r["caratteri_totali"], len("Un testo breve."))
        self.assertNotIn("nota_analisi", r)
        self.assertEqual(r["come_leggere_il_resto"], "")
        self.assertEqual(
            server.leggi_articolo(f"blog:{corto.id}", parte=2),
            {"errore": "questo contenuto ha 1 parte: chiedi la parte 1"})

    def test_the_instructions_and_descriptions_tell_how_to_read_the_rest(self):
        instr = server.server.instructions
        self.assertNotIn("`troncato` è vero il testo continua", instr)
        for parola in ("parte", "troncato", "parte_successiva", "nota_analisi"):
            self.assertIn(parola, instr)
        self.assertNotIn("testo integrale", instr)
        tools = {t.name: t for t in server.server._tool_manager.list_tools()}
        for nome in ("leggi_reel", "leggi_articolo", "leggi"):
            self.assertIn("parte", tools[nome].parameters["properties"])
            self.assertIn("troncato", tools[nome].description)
            self.assertNotIn("integrale", tools[nome].description)
