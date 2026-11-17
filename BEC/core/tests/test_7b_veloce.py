"""
The local 7b, faster inside the daily round (2026-11-17).

Three things, each with what it protects:
  - the claims prompt of a text read whole begins like the analysis prompt (same
    system message, same characters up to the end of the text), so Ollama reads
    the text once; and the analysis prompt itself did not move by a letter (Groq's
    analyses stay what they were);
  - analysis and claims of a content are asked one behind the other, with their
    own failure rules (the analysis stays `done` if the claims fail, a failure
    stays `failed`, the model away leaves `pending`);
  - ceilings only for the local model, and doubles out of a short text too, by a
    stricter rule than the flat 0.90.

No model is called: `client.chat_json` is replaced by a fake, `_ollama_chat` and
`_fast_chat` by mocks. Nothing leaves the process.
"""

from __future__ import annotations

import hashlib
import re
from unittest import mock

from django.test import SimpleTestCase, TestCase

from core.models import (DONE, FAILED, PENDING, KnowledgeDocument, Reel,
                         TrackedAccount, Transcript)
from core.tests.test_llm_chain import _chain_settings, _ChainCase
from llm import client, prompts
from llm.client import LLMBusy, LLMError, LLMTruncated
from pipeline import whole_text
from pipeline.agents import enrich_agent, knowledge_agent
from pipeline.dag import Context

CLAIMS = "Ora estrai solo le affermazioni"


def testo(n_frasi: int) -> str:
    return " ".join(
        f"Frase {i} sulla menopausa e sugli ormoni, con parole abbastanza lunghe."
        for i in range(n_frasi))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def no_near_doubles(texts):
    return [[1.0 if i == j else 0.0 for j in range(len(texts))]
            for i in range(len(texts))]


class Fake:
    """Answers an analysis or a claims prompt, and remembers the order."""

    def __init__(self, fail_analysis=False, fail_claims=False, away_claims=False,
                 claims_rows=None):
        self.kinds: list[str] = []
        self.calls: list[tuple[str, str, dict]] = []
        self.fail_analysis, self.fail_claims = fail_analysis, fail_claims
        self.away_claims, self.claims_rows = away_claims, claims_rows

    def __call__(self, system, user, **kw):
        self.calls.append((system, user, kw))
        if CLAIMS in user:
            self.kinds.append("claims")
            if self.away_claims:
                raise LLMBusy("occupato")
            if self.fail_claims:
                raise ValueError("JSON rotto")
            return {"argomenti": self.claims_rows or [
                {"testo": "Affermazione numero uno",
                 "citazione": "Frase 0 sulla menopausa e sugli ormoni, con parole abbastanza lunghe."}]}
        self.kinds.append("analysis")
        if self.fail_analysis:
            raise ValueError("JSON rotto")
        return {"summary_it": "Riassunto.", "topics": ["vampate di calore"],
                "primary_topic": "vampate di calore", "is_on_topic": True,
                "off_topic_reason": "", "hook_text": "Prime parole",
                "hook_analysis_it": "Perché funziona.", "target_audience_it": "Donne",
                "content_format": "talking_head"}


def _doc(text, **kw):
    base = dict(source_url=f"https://x.example/{abs(hash(text + str(kw))) % 10**8}",
                title="Un articolo", content_text=text, owner_type="competitor",
                source_type="blog")
    base.update(kw)
    return KnowledgeDocument.objects.create(**base)


def _reel(text, caption="Una didascalia.", **kw):
    acc = TrackedAccount.objects.create(username=f"acc{Reel.objects.count()}",
                                        owner_type=kw.pop("owner_type", "competitor"))
    r = Reel.objects.create(account=acc, shortcode=f"R{Reel.objects.count()}",
                            caption=caption, transcribe_status=DONE, **kw)
    if text is not None:
        Transcript.objects.create(reel=r, text=text)
    return r


def _patches(model):
    return (mock.patch.object(client, "chat_json", side_effect=model),
            mock.patch.object(knowledge_agent, "_embed_texts", no_near_doubles),
            mock.patch.object(enrich_agent, "_embed_texts", no_near_doubles))


# ── 1. same beginning ───────────────────────────────────────────────────────
class StessoInizio(TestCase):
    def test_every_kind_of_article_claims_begins_like_its_analysis(self):
        for kw in ({"source_type": "blog"}, {"source_type": "other"},
                   {"source_type": "video", "author": "TVRS"},
                   {"source_type": "manual", "owner_type": "owned"}):
            with self.subTest(kw=kw):
                doc = _doc(testo(40), **kw)
                a_sys, a_user = knowledge_agent.build_doc_enrich_prompt(doc)
                c_sys, c_user = knowledge_agent.build_doc_arguments_prompt(doc)
                self.assertEqual(c_sys, a_sys)
                head = knowledge_agent._doc_head(doc, doc.content_text)
                self.assertTrue(a_user.startswith(head))
                self.assertTrue(c_user.startswith(head))
                self.assertTrue(c_user.endswith(
                    prompts.ARGUMENTS_TAIL_TEMPLATE.format(
                        fonte=prompts.ARGUMENTS_FROM_ARTICLE)))

    def test_a_reel_claims_begins_like_its_analysis(self):
        r = _reel(testo(40), caption="Una didascalia lunga abbastanza.")
        a_sys, a_user, _ = enrich_agent.build_enrich_prompt(r)
        fake = Fake()
        a, b, c = _patches(fake)
        with a, b, c:
            enrich_agent._extract_arguments(r)
        c_sys, c_user, kw = fake.calls[0]
        self.assertEqual(c_sys, a_sys)
        head = enrich_agent._enrich_head(r.caption, r.transcript.text)
        self.assertTrue(a_user.startswith(head))
        self.assertTrue(c_user.startswith(head))
        self.assertIn(CLAIMS, c_user[len(head):])

    def test_the_tail_is_short(self):
        # ~100 tokens: a tail of ~260 read in 21 s on the 7b, over the 20 the work set.
        self.assertLess(len(prompts.ARGUMENTS_TAIL_TEMPLATE), 520)

    def test_a_quote_from_the_title_is_not_a_quote(self):
        doc = _doc(testo(40), title="Un titolo che non sta nel testo")
        text = knowledge_agent.build_doc_arguments_prompt(doc)[1]
        self.assertIn("non dal titolo", text)
        data = {"argomenti": [{"testo": "affermazione", "citazione": doc.title}]}
        self.assertEqual(whole_text.verified_claims(data, doc.content_text)[0], [])


class AnalisiAllaLettera(TestCase):
    """The analysis prompts, frozen from `main` (sha256 of the text built there):
    a change here changes what Groq answers for every content."""

    def test_the_reel_analysis_is_the_old_one_to_the_letter(self):
        user = enrich_agent._enrich_user("Una didascalia.", "Il testo parlato del reel.",
                                         "transcript")
        self.assertEqual(sha(user), "8c22bf443256fc50d824a734c37f841ad25919c32ea0cd9b8192f7ee8c0ef8f3")
        self.assertEqual(sha(enrich_agent._enrich_user(
            "Una didascalia.", "Il testo parlato del reel.", "caption_only")),
            "1567acd4e919fe19af65f2c0cc25d0ec4a81ac9bdd663df8fd248dd73df8f373")

    def test_the_final_call_of_a_long_reel_is_the_old_one_too(self):
        # `ask_final` builds its prompt with the same function, on the notes block.
        user = enrich_agent._enrich_user("Una didascalia.", "Il testo parlato del reel.",
                                         "transcript")
        self.assertIn("REGOLE FONDAMENTALI:", user)
        self.assertEqual(prompts.ENRICH_USER_TEMPLATE,
                         prompts.ENRICH_HEAD_TEMPLATE + prompts.ENRICH_RULES)

    def test_the_article_analysis_is_the_old_one_to_the_letter(self):
        doc = _doc("Il testo dell'articolo.", title="Titolo", owner_type="owned")
        _, user = knowledge_agent.build_doc_enrich_prompt(doc)
        # the same text built on `main`, whose source was frozen when this was written
        expect = knowledge_agent._intro(doc)
        self.assertEqual(expect, "Analizza questo articolo del blog di Medyca "
                                 "(il blog di Medyca stessa).")
        self.assertEqual(sha(user), "7931985fffa5168276a4c864eec1c7efff1e8040058a06cb3e17c277e1aec4cd")


# ── 2. one behind the other ─────────────────────────────────────────────────
class UnoDietroLAltro(TestCase):
    def run_docs(self, fake, n=2, **kw):
        docs = [_doc(testo(40 + i), enrich_status=PENDING, argument_status=PENDING,
                     **kw) for i in range(n)]
        a, b, c = _patches(fake)
        with a, b, c, mock.patch.object(client, "available", return_value=True), \
                mock.patch.object(knowledge_agent, "_embed_one"), \
                mock.patch.object(knowledge_agent.progress, "note"):
            out = knowledge_agent.run(Context())
        for d in docs:
            d.refresh_from_db()
        return docs, out

    def test_documents_analysis_then_claims_then_the_next_document(self):
        fake = Fake()
        docs, out = self.run_docs(fake)
        self.assertEqual(fake.kinds, ["analysis", "claims", "analysis", "claims"])
        for d in docs:
            self.assertEqual((d.enrich_status, d.argument_status), (DONE, DONE))
            self.assertEqual(d.arguments.count(), 1)
        self.assertEqual((out["enriched"], out["arg_docs"], out["arguments"]), (2, 2, 2))

    def test_a_failed_analysis_asks_no_claims(self):
        fake = Fake(fail_analysis=True)
        docs, out = self.run_docs(fake, n=1)
        self.assertEqual(fake.kinds, ["analysis"])
        self.assertEqual((docs[0].enrich_status, docs[0].argument_status),
                         (FAILED, PENDING))
        self.assertEqual(out["enrich_failed"], 1)

    def test_failed_claims_leave_the_analysis_done_and_stay_failed(self):
        fake = Fake(fail_claims=True)
        docs, out = self.run_docs(fake, n=1)
        d = docs[0]
        self.assertEqual((d.enrich_status, d.argument_status), (DONE, FAILED))
        self.assertEqual(d.summary_it, "Riassunto.")
        self.assertIn("JSON rotto", d.last_error)
        self.assertEqual((out["enriched"], out["arg_failed"]), (1, 1))
        # the next round does not try again: a failure is an explicit act
        fake2 = Fake()
        a, b, c = _patches(fake2)
        with a, b, c, mock.patch.object(client, "available", return_value=True), \
                mock.patch.object(knowledge_agent, "_embed_one"):
            knowledge_agent.run(Context())
        self.assertEqual(fake2.calls, [])

    def test_the_model_away_between_the_two_saves_the_analysis_and_defers_the_claims(self):
        fake = Fake(away_claims=True)
        docs, out = self.run_docs(fake, n=2)
        # the first document stops the round: the second is not even tried
        self.assertEqual(fake.kinds, ["analysis", "claims"])
        done = [d for d in docs if d.enrich_status == DONE]
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0].argument_status, PENDING)
        self.assertEqual(done[0].summary_it, "Riassunto.")
        pending = [d for d in docs if d.enrich_status == PENDING]
        self.assertEqual(len(pending), 1)
        self.assertEqual(out["deferred"], 2)
        self.assertEqual(out["enrich_failed"] + out["arg_failed"], 0)

    def test_the_leftover_claims_of_an_earlier_round_are_asked_after(self):
        d = _doc(testo(40), enrich_status=DONE, argument_status=PENDING,
                 summary_it="Già fatto.")
        fake = Fake()
        a, b, c = _patches(fake)
        with a, b, c, mock.patch.object(client, "available", return_value=True), \
                mock.patch.object(knowledge_agent, "_embed_one"):
            knowledge_agent.run(Context())
        self.assertEqual(fake.kinds, ["claims"])
        d.refresh_from_db()
        self.assertEqual((d.argument_status, d.summary_it), (DONE, "Già fatto."))

    def test_a_long_text_is_not_read_twice_in_the_round(self):
        d = _doc(testo(500), enrich_status=PENDING, argument_status=PENDING)
        calls = []

        def pieces(system, user, **kw):
            calls.append(user)
            m = re.search(r"PEZZO (\d+) DI (\d+):\n(.*?)\n\nREGOLE:", user, re.S)
            if m:
                first = re.split(r"(?<=\.) ", m.group(3).strip())[0]
                return {"sintesi": "appunti", "argomenti": [
                    {"testo": f"Affermazione {m.group(1)}", "citazione": first}]}
            return Fake()(system, user)
        a, b, c = _patches(pieces)
        with a, b, c, mock.patch.object(client, "available", return_value=True), \
                mock.patch.object(knowledge_agent, "_embed_one"), \
                mock.patch.object(knowledge_agent.progress, "note"):
            knowledge_agent.run(Context())
        n = len(whole_text.split_text(d.content_text))
        self.assertEqual(len(calls), n + 1)   # the pieces and the final analysis, no more
        d.refresh_from_db()
        self.assertEqual((d.enrich_status, d.argument_status), (DONE, DONE))

    def test_reels_analysis_then_claims_and_the_owner_never_changes(self):
        reels = [_reel(testo(40 + i), owner_type="owned") for i in range(2)]
        fake = Fake()
        a, b, c = _patches(fake)
        with a, b, c, mock.patch.object(client, "available", return_value=True), \
                mock.patch.object(enrich_agent.progress, "note"):
            out = enrich_agent.run(Context())
        self.assertEqual(fake.kinds, ["analysis", "claims", "analysis", "claims"])
        for r in reels:
            r.refresh_from_db()
            self.assertEqual((r.enrich_status, r.argument_status), (DONE, DONE))
            self.assertEqual(r.account.owner_type, "owned")
        self.assertEqual((out["enriched"], out["arg_reels"]), (2, 2))

    def test_a_reel_without_speech_makes_no_call_for_claims(self):
        r = _reel(None, caption="Una didascalia lunga. " * 10)  # caption only
        fake = Fake()
        a, b, c = _patches(fake)
        with a, b, c, mock.patch.object(client, "available", return_value=True), \
                mock.patch.object(enrich_agent.progress, "note"):
            enrich_agent.run(Context())
        self.assertEqual(fake.kinds, ["analysis"])
        r.refresh_from_db()
        self.assertEqual((r.enrich_status, r.argument_status), (DONE, DONE))

    def test_reel_claims_failing_keep_the_analysis_and_stay_failed(self):
        r = _reel(testo(40))
        fake = Fake(fail_claims=True)
        a, b, c = _patches(fake)
        with a, b, c, mock.patch.object(client, "available", return_value=True), \
                mock.patch.object(enrich_agent.progress, "note"):
            out = enrich_agent.run(Context())
        r.refresh_from_db()
        self.assertEqual((r.enrich_status, r.argument_status), (DONE, FAILED))
        self.assertEqual(out["arg_failed"], 1)

    def test_reel_model_away_at_the_claims_leaves_them_pending(self):
        r = _reel(testo(40))
        fake = Fake(away_claims=True)
        a, b, c = _patches(fake)
        with a, b, c, mock.patch.object(client, "available", return_value=True), \
                mock.patch.object(enrich_agent.progress, "note"):
            out = enrich_agent.run(Context())
        r.refresh_from_db()
        self.assertEqual((r.enrich_status, r.argument_status), (DONE, PENDING))
        self.assertEqual(out["deferred"], 1)


# ── 3. ceilings only for the local model ────────────────────────────────────
@_chain_settings()
class TettiLocali(_ChainCase):
    def test_the_local_ceiling_reaches_ollama_and_groq_keeps_its_own(self):
        with mock.patch.object(client, "_fast_chat", return_value="groq") as fast:
            client.chat("s", "u", max_tokens=2000, local_max_tokens=800)
        self.assertEqual(fast.call_args.args[2], 2000)
        with mock.patch.object(client, "_fast_chat",
                               side_effect=client.LLMRateLimit(1, daily=True)), \
             mock.patch.object(client, "_ollama_chat", return_value="locale") as oll:
            client.chat("s", "u", max_tokens=2000, local_max_tokens=800)
        self.assertEqual(oll.call_args.args[2], 800)

    def test_without_a_local_ceiling_ollama_gets_the_same_as_before(self):
        with mock.patch.object(client, "_fast_chat",
                               side_effect=client.LLMRateLimit(1, daily=True)), \
             mock.patch.object(client, "_ollama_chat", return_value="locale") as oll:
            client.chat("s", "u", max_tokens=1200)
        self.assertEqual(oll.call_args.args[2], 1200)

    def test_the_ceiling_written_in_llm_calls_is_the_local_one(self):
        from core.models import LLMCall
        with mock.patch.object(client, "_fast_chat",
                               side_effect=client.LLMRateLimit(1, daily=True)), \
             mock.patch.object(client, "_ollama_chat", return_value="locale"):
            client.chat("s", "u", max_tokens=2000, local_max_tokens=800)
        self.assertEqual(LLMCall.objects.filter(provider="ollama").latest("id").max_tokens, 800)

    def test_a_local_answer_cut_at_the_ceiling_is_failed_and_not_retried(self):
        with mock.patch.object(client, "_fast_chat",
                               side_effect=client.LLMRateLimit(1, daily=True)), \
             mock.patch.object(client, "_ollama_chat",
                               side_effect=LLMTruncated("tagliata")) as oll:
            with self.assertRaises(LLMError):
                client.chat("s", "u", max_tokens=2000, local_max_tokens=800, retries=2)
        self.assertEqual(oll.call_count, 1)

    def test_the_ceilings_are_twice_what_the_7b_wrote_never_under(self):
        # measured 2026-11-16: analysis at most 202 tokens, claims at most 742
        self.assertGreaterEqual(client.LOCAL_MAX_ANALYSIS, 2 * 202)
        self.assertGreaterEqual(client.LOCAL_MAX_CLAIMS, 2 * 742)
        self.assertGreaterEqual(client.LOCAL_MAX_CLAIMS, 1500)

    def test_the_agents_pass_the_local_ceilings(self):
        fake = Fake()
        d = _doc(testo(40), enrich_status=PENDING, argument_status=PENDING)
        a, b, c = _patches(fake)
        with a, b, c:
            knowledge_agent._enrich_one(d)
            knowledge_agent._extract_arguments(d)
        self.assertEqual(fake.calls[0][2]["local_max_tokens"], client.LOCAL_MAX_ANALYSIS)
        self.assertEqual(fake.calls[1][2]["local_max_tokens"], client.LOCAL_MAX_CLAIMS)
        # Groq's ceilings did not move
        self.assertEqual(fake.calls[0][2]["max_tokens"], knowledge_agent.DOC_MAX_TOKENS)
        self.assertEqual(fake.calls[1][2]["max_tokens"], knowledge_agent.DOC_MAX_TOKENS)
        r = _reel(testo(40))
        fake = Fake()
        a, b, c = _patches(fake)
        with a, b, c:
            enrich_agent._enrich_one(r)
            enrich_agent._extract_arguments(r)
        self.assertEqual([kw["max_tokens"] for _, _, kw in fake.calls],
                         [enrich_agent.ENRICH_MAX_TOKENS, 1200])
        self.assertEqual([kw["local_max_tokens"] for _, _, kw in fake.calls],
                         [client.LOCAL_MAX_ANALYSIS, client.LOCAL_MAX_CLAIMS])


# ── 4. doubles in a short text ──────────────────────────────────────────────
def _claim(testo_, citazione):
    return {"testo": testo_, "citazione": citazione}


def _vec(by_text):
    return lambda texts: [by_text[t] for t in texts]


class DoppieNeiTestiCorti(SimpleTestCase):
    A = _claim("Il progesterone aiuta il sonno", "il progesterone aiuta il sonno nelle donne")
    # an angle of 15 degrees: cosine 0.966
    NEAR = [0.966, 0.259]

    def merged(self, claims, vectors, cap=6):
        return whole_text.merge_claims([claims], cap, embed=_vec(vectors))

    def test_the_same_quote_twice_is_one_claim_even_with_other_words(self):
        b = _claim("Il progesterone favorisce il riposo", self.A["citazione"])
        self.assertEqual(whole_text.merge_claims([[self.A, b]], 6), [self.A])

    def test_the_same_text_twice_is_one_claim_without_the_embedder(self):
        b = _claim("Il progesterone aiuta il sonno", "un'altra citazione del testo")
        self.assertEqual(whole_text.merge_claims([[self.A, b]], 6), [self.A])

    def test_very_close_claims_are_one_even_with_different_quotes(self):
        b = _claim("Il progesterone migliora il sonno", "una citazione tutta diversa qui")
        out = self.merged([self.A, b], {self.A["testo"]: [1.0, 0.0], b["testo"]: self.NEAR})
        self.assertEqual(out, [self.A])  # 0.966 >= 0.95

    def test_close_claims_with_different_quotes_under_095_both_stay(self):
        # «le donne hanno bisogno di 7 ore e mezza» / «gli uomini di 6 e mezza»: 0.92
        a = _claim("Le donne hanno bisogno di 7 ore e mezza di sonno",
                   "le donne dormono sette ore e mezza")
        b = _claim("Gli uomini hanno bisogno di 6 ore e mezza di sonno",
                   "gli uomini ne dormono solo sei e mezza")
        out = self.merged([a, b], {a["testo"]: [1.0, 0.0], b["testo"]: [0.92, 0.392]})
        self.assertEqual(out, [a, b])

    def test_at_090_with_overlapping_quotes_they_are_one(self):
        a = _claim("Il farro contiene glutine", "il farro contiene glutine e va evitato")
        b = _claim("Il farro ha glutine dentro", "il farro contiene glutine")  # inside a
        out = self.merged([a, b], {a["testo"]: [1.0, 0.0], b["testo"]: [0.92, 0.392]})
        self.assertEqual(out, [a])

    def test_quotes_sharing_most_words_overlap(self):
        self.assertTrue(whole_text._quotes_overlap(
            "il progesterone aiuta il sonno", "il sonno aiuta con il progesterone"))
        self.assertFalse(whole_text._quotes_overlap(
            "il farro contiene glutine e quindi va evitato dai celiaci",
            "nell'orzo c'è del glutine, chi è celiaco non lo mangia"))

    def test_the_embedder_not_loading_keeps_the_claims_and_drops_only_exact_doubles(self):
        def boom(_):
            raise RuntimeError("modello non caricabile")
        b = _claim("Altra cosa", "una citazione completamente diversa dalla prima")
        c = _claim("Il progesterone aiuta il sonno", "citazione diversa ancora una volta")
        out = whole_text.merge_claims([[self.A, b, c]], 6, embed=boom)
        self.assertEqual(out, [self.A, b])

    def test_eight_valid_with_one_double_keep_six_the_cap_is_after_the_filter(self):
        claims = [_claim(f"Affermazione {i} diversa", f"citazione numero {i} per intero")
                  for i in range(7)]
        claims.insert(1, _claim("Altra forma", claims[0]["citazione"]))  # the double
        vec = {c["testo"]: [1.0 if i == j else 0.0 for j in range(8)]
               for i, c in enumerate(claims)}
        out = self.merged(claims, vec, cap=6)
        self.assertEqual(len(out), 6)
        self.assertNotIn("Altra forma", [c["testo"] for c in out])
        # the cap before the filter would have kept the double and lost the 6th
        self.assertIn("Affermazione 5 diversa", [c["testo"] for c in out])


class DoppieNelSalvataggio(TestCase):
    def test_a_short_article_saves_no_doubles_and_at_most_six(self):
        text = testo(40)
        d = _doc(text, enrich_status=DONE, argument_status=PENDING)
        sentences = re.split(r"(?<=\.) ", text)
        rows = [{"testo": f"Affermazione {i}", "citazione": sentences[i]} for i in range(6)]
        rows.append({"testo": "Altra forma della prima", "citazione": sentences[0]})
        with mock.patch.object(knowledge_agent, "_embed_texts", no_near_doubles):
            n = knowledge_agent.write_doc_arguments(d, {"argomenti": rows})
        self.assertEqual(n, 6)
        self.assertEqual(d.arguments.count(), 6)
        self.assertNotIn("Altra forma della prima",
                         [a.text_it for a in d.arguments.all()])

    def test_a_reel_saves_no_doubles_either(self):
        text = testo(40)
        r = _reel(text)
        sentences = re.split(r"(?<=\.) ", text)
        rows = [{"testo": "Affermazione uno", "citazione": sentences[0]},
                {"testo": "Altra forma uno", "citazione": sentences[0]},
                {"testo": "Affermazione due", "citazione": sentences[1]}]
        with mock.patch.object(client, "chat_json", return_value={"argomenti": rows}), \
                mock.patch.object(enrich_agent, "_embed_texts", no_near_doubles):
            n = enrich_agent._extract_arguments(r)
        self.assertEqual(n, 2)
