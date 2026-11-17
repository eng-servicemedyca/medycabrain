"""
The whole text is read (2026-11-16): nothing is cut any more.

Up to 8 000 characters the text goes in whole, in two calls as before. Above, it
is cut in pieces, each piece is one call, and the answers are stitched in code.
What these protect:
  - the cut: never mid-word, glues back to the exact text, 8 000 is the short road;
  - a quote is checked against ITS piece (an invented one, or one that lives in
    another piece, is dropped);
  - doubles out, claims spread over the whole text, the cap held;
  - a piece that fails makes the content `failed` and saves NOTHING; the model
    being away leaves it `pending`;
  - the new field `full_text_status` and what the agents write in it.

No model is called: `client.chat_json` is replaced by a fake that answers from the
prompt it receives. Nothing leaves the process.
"""

from __future__ import annotations

import re
from unittest import mock

from django.test import SimpleTestCase, TestCase

from core.models import (DONE, FAILED, PENDING, DocumentArgument, Enrichment,
                         KnowledgeDocument, Reel, ReelArgument, ReelEmbedding,
                         TrackedAccount, Transcript)
from llm import client
from llm.client import LLMBusy
from pipeline import whole_text
from pipeline.agents import enrich_agent, knowledge_agent
from pipeline.dag import Context


def testo(n_frasi: int, tag: str = "") -> str:
    """Italian-looking text whose every sentence is different (so a quote from it
    is found in one place only)."""
    return " ".join(
        f"Frase {tag}{i} sulla menopausa e sugli ormoni, con parole abbastanza lunghe."
        for i in range(n_frasi))


_PEZZO = re.compile(r"PEZZO (\d+) DI (\d+):\n(.*?)\n\nREGOLE:", re.S)


class FakeModel:
    """Answers the three kinds of call from the prompt text.

    A piece: one claim quoting the first sentence of that piece (and a second one
    quoting the last, if `two`), and a line of notes. The final call: a valid
    analysis. `fail_piece=n` breaks piece n; `away_piece=n` makes the local model
    unavailable at piece n.
    """

    def __init__(self, fail_piece=None, away_piece=None, two=False, bad_final=False):
        self.calls: list[tuple[str, str]] = []
        self.fail_piece, self.away_piece = fail_piece, away_piece
        self.two, self.bad_final = two, bad_final

    def __call__(self, system, user, **kw):
        self.calls.append((system, user))
        m = _PEZZO.search(user)
        if m:
            n, piece = int(m.group(1)), m.group(3)
            if n == self.fail_piece:
                raise ValueError("JSON rotto")
            if n == self.away_piece:
                raise LLMBusy("occupato")
            sentences = re.split(r"(?<=\.) ", piece.strip())
            claims = [{"testo": f"Affermazione del pezzo {n}",
                       "citazione": sentences[0]}]
            if self.two:
                claims.append({"testo": f"Seconda del pezzo {n}",
                               "citazione": sentences[-1]})
            return {"sintesi": f"appunti del pezzo {n}", "argomenti": claims}
        if self.bad_final:
            return "non un oggetto"
        return {"summary_it": "Riassunto di tutto il testo.",
                "topics": ["vampate di calore"], "primary_topic": "vampate di calore",
                "is_on_topic": True, "off_topic_reason": "",
                "hook_text": "Prime parole", "hook_analysis_it": "Perché funziona.",
                "target_audience_it": "Donne in menopausa",
                "content_format": "talking_head"}

    def pieces_asked(self):
        return [u for _, u in self.calls if _PEZZO.search(u)]

    def finals(self):
        return [u for _, u in self.calls if not _PEZZO.search(u)]


def no_near_doubles(texts):
    """Stand-in for the embedder: every text is its own direction."""
    return [[1.0 if i == j else 0.0 for j in range(len(texts))]
            for i in range(len(texts))]


# ── the cut ─────────────────────────────────────────────────────────────────
class TagliaIlTesto(SimpleTestCase):
    def test_up_to_8000_characters_is_one_piece_the_short_road(self):
        t = "a" * 8000
        self.assertEqual(whole_text.split_text(t), [t])
        self.assertFalse(whole_text.is_long(t))

    def test_8001_characters_are_pieces(self):
        t = "a " * 4001  # 8002 characters
        self.assertTrue(whole_text.is_long(t))
        pieces = whole_text.split_text(t)
        self.assertEqual(len(pieces), 2)
        self.assertEqual("".join(pieces), t)

    def test_the_pieces_glue_back_and_none_is_over_the_limit(self):
        for n in (80, 150, 400, 1200):
            t = testo(n)
            with self.subTest(chars=len(t)):
                pieces = whole_text.split_text(t)
                self.assertEqual("".join(pieces), t)
                for p in pieces:
                    self.assertTrue(p.strip())
                    self.assertLessEqual(len(p), whole_text.PIECE_TARGET)

    def test_pieces_are_about_the_same_length_and_as_few_as_needed(self):
        t = testo(1200)  # ~86 000 characters, like the longest reel
        pieces = whole_text.split_text(t)
        self.assertIn(len(pieces), (15, 16))
        sizes = [len(p) for p in pieces]
        self.assertLess(max(sizes) - min(sizes), 1500, sizes)

    def test_a_cut_falls_at_the_end_of_a_sentence_when_there_is_one(self):
        for p in whole_text.split_text(testo(400))[:-1]:
            self.assertRegex(p, r"[.!?]\s$", p[-30:])

    def test_a_text_without_punctuation_is_cut_on_a_space_never_in_a_word(self):
        t = " ".join(["parola"] * 3000)  # Whisper without full stops
        pieces = whole_text.split_text(t)
        self.assertGreater(len(pieces), 1)
        self.assertEqual("".join(pieces), t)
        for p in pieces:
            self.assertTrue(all(w == "parola" for w in p.split()))

    def test_a_text_with_no_space_at_all_is_still_cut_and_glues_back(self):
        t = "x" * 20000
        pieces = whole_text.split_text(t)
        self.assertEqual("".join(pieces), t)
        self.assertTrue(all(len(p) <= whole_text.PIECE_TARGET for p in pieces))

    def test_the_cap_of_claims_follows_the_length(self):
        self.assertEqual(whole_text.claims_limit("a" * 8000), 6)
        self.assertEqual(whole_text.claims_limit("a" * 8001), 12)


# ── quotes, doubles, the cap ────────────────────────────────────────────────
class CitazioniVere(SimpleTestCase):
    PEZZO_3 = ("Il progesterone aiuta il sonno nelle donne in menopausa. "
               "Gli estrogeni proteggono le ossa dopo i cinquant'anni.")
    ALTRO = "Questa frase vive soltanto in un altro pezzo del testo."

    def claims(self, *quotes, limit=None):
        data = {"argomenti": [{"testo": f"affermazione {i}", "citazione": q}
                              for i, q in enumerate(quotes)]}
        return whole_text.verified_claims(data, self.PEZZO_3, limit=limit)

    def test_a_true_quote_is_kept(self):
        kept, dropped, rows = self.claims("Il progesterone aiuta il sonno")
        self.assertEqual((len(kept), dropped, rows), (1, 0, 1))

    def test_an_invented_quote_is_dropped(self):
        kept, dropped, _ = self.claims("Il progesterone cura ogni malattia sempre")
        self.assertEqual((kept, dropped), ([], 1))

    def test_a_quote_that_lives_in_another_piece_is_dropped(self):
        kept, dropped, _ = self.claims(self.ALTRO)
        self.assertEqual((kept, dropped), ([], 1))

    def test_a_quote_shorter_than_12_characters_is_dropped(self):
        self.assertEqual(self.claims("Il progeste")[1], 1)

    def test_the_cap_counts_the_claims_that_hold_not_the_rows(self):
        kept, _, rows = self.claims(
            "frase inventata numero uno", "Il progesterone aiuta il sonno",
            "Gli estrogeni proteggono le ossa", limit=1)
        self.assertEqual((len(kept), rows), (1, 3))
        self.assertIn("progesterone", kept[0]["citazione"])

    def test_folding_is_the_pipelines_one(self):
        kept, _, _ = self.claims("IL   PROGESTERONE aiuta il sonno")
        self.assertEqual(len(kept), 1)

    def test_strict_refuses_an_answer_with_no_list(self):
        with self.assertRaises(ValueError):
            whole_text.verified_claims({"altro": 1}, "testo", strict=True)
        self.assertEqual(whole_text.verified_claims({"altro": 1}, "testo")[0], [])

    def test_a_piece_answer_keeps_at_most_three_claims_and_clips_the_notes(self):
        piece = testo(20)
        sentences = re.split(r"(?<=\.) ", piece)
        data = {"sintesi": " ".join(["parola"] * 200),
                "argomenti": [{"testo": f"a{i}", "citazione": s}
                              for i, s in enumerate(sentences[:6])]}
        note, claims = whole_text.parse_piece(data, piece)
        self.assertEqual(len(claims), 3)
        self.assertLessEqual(len(note.split()), whole_text.NOTE_WORDS * 2)

    def test_a_piece_answer_that_is_not_an_object_is_an_error(self):
        with self.assertRaises(ValueError):
            whole_text.parse_piece("niente", "testo")


class UnisciLeAffermazioni(SimpleTestCase):
    @staticmethod
    def c(piece, j):
        return {"testo": f"testo {piece}-{j}", "citazione": f"citazione lunga {piece}-{j}"}

    def test_the_same_quote_twice_is_one_claim(self):
        a = {"testo": "uno", "citazione": "la stessa citazione lunga"}
        b = {"testo": "due", "citazione": "La stessa   citazione lunga"}
        self.assertEqual(whole_text.merge_claims([[a], [b]], 12), [a])

    def test_claims_close_in_meaning_are_one(self):
        a, b, c = self.c(0, 0), self.c(1, 0), self.c(2, 0)
        vec = {a["testo"]: [1.0, 0.0], b["testo"]: [0.99, 0.14], c["testo"]: [0.0, 1.0]}
        merged = whole_text.merge_claims(
            [[a], [b], [c]], 12, embed=lambda ts: [vec[t] for t in ts])
        self.assertEqual(merged, [a, c])

    def test_a_broken_embedder_does_not_lose_the_content(self):
        def boom(_):
            raise RuntimeError("modello non caricabile")
        merged = whole_text.merge_claims([[self.c(0, 0)], [self.c(1, 0)]], 12, embed=boom)
        self.assertEqual(len(merged), 2)

    def test_the_cap_is_held_and_every_piece_is_present(self):
        per_piece = [[self.c(p, j) for j in range(3)] for p in range(10)]  # 30 claims
        merged = whole_text.merge_claims(per_piece, 12, embed=no_near_doubles)
        self.assertEqual(len(merged), 12)
        pieces = {int(c["testo"].split()[1].split("-")[0]) for c in merged}
        # 12 claims over 10 pieces: all ten are there (the first of each), plus
        # the second of the first two — the end of the text is as present as the start.
        self.assertEqual(pieces, set(range(10)))

    def test_the_final_order_is_the_order_of_the_text(self):
        per_piece = [[self.c(p, j) for j in range(2)] for p in range(5)]
        merged = whole_text.merge_claims(per_piece, 12, embed=no_near_doubles)
        order = [tuple(map(int, c["testo"].split()[1].split("-"))) for c in merged]
        self.assertEqual(order, sorted(order))

    def test_a_piece_with_no_claims_is_not_an_error(self):
        merged = whole_text.merge_claims([[], [self.c(1, 0)], []], 12)
        self.assertEqual(len(merged), 1)


# ── reading in pieces ───────────────────────────────────────────────────────
class LetturaAPezzi(SimpleTestCase):
    def read(self, model, text=None):
        text = text or testo(300)
        return whole_text.read_whole(
            text, "un articolo", lambda u: model("S", u),
            lambda b: model("S", "FINALE\n" + b), embed=no_near_doubles)

    def test_every_piece_is_one_call_and_the_final_call_reads_the_notes(self):
        m = FakeModel()
        text = testo(300)
        final, claims = self.read(m, text)
        n = len(whole_text.split_text(text))
        self.assertEqual(len(m.pieces_asked()), n)
        self.assertEqual(len(m.finals()), 1)
        self.assertIn(f"Pezzo 1 di {n}: appunti del pezzo 1", m.finals()[0])
        self.assertIn(f"Pezzo {n} di {n}", m.finals()[0])
        self.assertEqual(len(claims), n)
        self.assertEqual(final["summary_it"], "Riassunto di tutto il testo.")

    def test_each_piece_prompt_carries_only_its_own_piece(self):
        m = FakeModel()
        text = testo(300)
        self.read(m, text)
        pieces = whole_text.split_text(text)
        for i, (user, piece) in enumerate(zip(m.pieces_asked(), pieces), 1):
            self.assertIn(f"pezzo {i} di {len(pieces)}", user)
            self.assertIn(piece, user)
            other = pieces[i % len(pieces)]
            self.assertNotIn(other, user)

    def test_a_piece_that_fails_fails_the_whole_content_and_names_the_piece(self):
        m = FakeModel(fail_piece=2)
        with self.assertRaisesRegex(whole_text.WholeTextError, r"pezzo 2 di \d+"):
            self.read(m)
        self.assertEqual(len(m.finals()), 0)  # it stopped there

    def test_a_failed_final_call_is_a_failure_too(self):
        def broken(_block):
            raise ValueError("rotto")
        with self.assertRaisesRegex(whole_text.WholeTextError, "riassunto finale"):
            whole_text.read_whole(testo(300), "x", lambda u: FakeModel()("S", u),
                                  broken, embed=no_near_doubles)

    def test_the_model_being_away_is_not_a_failure_of_the_content(self):
        with self.assertRaises(LLMBusy):
            self.read(FakeModel(away_piece=2))

    def test_a_text_too_long_for_the_notes_fails_before_any_call(self):
        m = FakeModel()
        t = "a " * (whole_text.MAX_PIECES * whole_text.PIECE_TARGET)
        with self.assertRaisesRegex(whole_text.WholeTextError, "troppo lungo"):
            self.read(m, t)
        self.assertEqual(m.calls, [])


# ── the agents ──────────────────────────────────────────────────────────────
def _doc(text, **kw):
    base = dict(source_url=f"https://x.example/{abs(hash(text)) % 10**8}",
                title="Una puntata", content_text=text, owner_type="competitor",
                source_type="video", summary_it="Riassunto vecchio.",
                enrich_status=DONE, argument_status=DONE, embed_status=DONE)
    base.update(kw)
    return KnowledgeDocument.objects.create(**base)


def _patches(model):
    return (mock.patch.object(client, "chat_json", side_effect=model),
            mock.patch.object(knowledge_agent, "_embed_texts", no_near_doubles),
            mock.patch.object(enrich_agent, "_embed_texts", no_near_doubles))


class ArticoliLetturaIntera(TestCase):
    def go(self, model, fn, *args):
        a, b, c = _patches(model)
        with a, b, c:
            return fn(*args)

    def test_a_text_up_to_8000_is_read_whole_in_two_calls(self):
        t = testo(100)  # ~7 000 characters, over the old 6 000
        self.assertGreater(len(t), 6000)
        self.assertLessEqual(len(t), 8000)
        d = _doc(t, enrich_status=PENDING, argument_status=PENDING)
        analysis = {"summary_it": "R", "topics": [], "primary_topic": "x",
                    "is_on_topic": True}
        seen = []

        def short(system, user, **kw):
            seen.append(user)
            if "Ora estrai solo le affermazioni" not in user:
                return analysis
            return {"argomenti": [{"testo": "affermazione",
                                   "citazione": t[-150:-60]}]}  # from the END
        a, b, c = _patches(short)
        with a, b, c:
            knowledge_agent._enrich_one(d)
            n = knowledge_agent._extract_arguments(d)
        self.assertEqual(len(seen), 2)
        self.assertIn(t, seen[0])   # the whole text, not its first 6 000
        self.assertIn(t, seen[1])
        self.assertEqual(n, 1)      # a quote from the end of the text holds
        d.refresh_from_db()
        self.assertEqual(d.full_text_status, DONE)
        self.assertEqual(d.enrich_status, DONE)

    def test_a_long_text_is_read_in_pieces_and_saved_together(self):
        t = testo(500)
        d = _doc(t, enrich_status=PENDING, argument_status=PENDING)
        m = FakeModel(two=True)
        self.go(m, knowledge_agent._enrich_one, d)
        d.refresh_from_db()
        n = len(whole_text.split_text(t))
        self.assertEqual(len(m.pieces_asked()), n)
        self.assertEqual((d.enrich_status, d.argument_status, d.full_text_status),
                         (DONE, DONE, DONE))
        self.assertEqual(d.summary_it, "Riassunto di tutto il testo.")
        args = list(d.arguments.all())
        self.assertEqual(len(args), whole_text.CLAIMS_LONG)
        for a in args:  # every saved quote is really in the text
            self.assertIn(a.quote, t)
        self.assertEqual(d.embed_status, PENDING)  # the vector is redone tonight

    def test_the_claims_after_it_are_not_asked_again(self):
        d = _doc(testo(500), enrich_status=PENDING, argument_status=PENDING)
        m = FakeModel()
        self.go(m, knowledge_agent._enrich_one, d)
        calls = len(m.calls)
        n = self.go(m, knowledge_agent._extract_arguments, d)
        self.assertEqual(len(m.calls), calls)
        self.assertEqual(n, d.arguments.count())

    def test_a_failed_piece_makes_the_document_failed_and_saves_nothing(self):
        d = _doc(testo(500), enrich_status=PENDING, argument_status=PENDING)
        DocumentArgument.objects.create(document=d, text_it="vecchia", quote="vecchia citazione")
        m = FakeModel(fail_piece=3)
        a, b, c = _patches(m)
        with a, b, c, mock.patch.object(client, "available", return_value=True), \
                mock.patch.object(knowledge_agent, "_embed_one"), \
                mock.patch.object(knowledge_agent.progress, "note"):
            out = knowledge_agent.run(Context())
        d.refresh_from_db()
        self.assertEqual((d.enrich_status, d.argument_status, d.full_text_status),
                         (FAILED, FAILED, FAILED))
        self.assertIn("pezzo 3 di", d.last_error)
        self.assertEqual(out["enrich_failed"], 1)
        self.assertEqual(d.summary_it, "Riassunto vecchio.")       # untouched
        self.assertEqual([x.text_it for x in d.arguments.all()], ["vecchia"])

    def test_a_failure_stays_failed_the_next_round(self):
        d = _doc(testo(500), enrich_status=FAILED, argument_status=FAILED,
                 full_text_status=FAILED)
        m = FakeModel()
        a, b, c = _patches(m)
        with a, b, c, mock.patch.object(client, "available", return_value=True), \
                mock.patch.object(knowledge_agent, "_embed_one"), \
                mock.patch.object(knowledge_agent.progress, "note"):
            knowledge_agent.run(Context())
        self.assertEqual(m.calls, [])
        d.refresh_from_db()
        self.assertEqual(d.enrich_status, FAILED)

    def test_the_model_away_in_the_middle_leaves_it_pending_with_nothing_saved(self):
        d = _doc(testo(500), enrich_status=PENDING, argument_status=PENDING,
                 summary_it="")
        m = FakeModel(away_piece=2)
        a, b, c = _patches(m)
        with a, b, c, mock.patch.object(client, "available", return_value=True), \
                mock.patch.object(knowledge_agent, "_embed_one"), \
                mock.patch.object(knowledge_agent.progress, "note"):
            out = knowledge_agent.run(Context())
        d.refresh_from_db()
        self.assertEqual((d.enrich_status, d.full_text_status), (PENDING, PENDING))
        self.assertEqual(d.summary_it, "")
        self.assertEqual(d.arguments.count(), 0)
        self.assertEqual(out["enrich_failed"], 0)
        self.assertEqual(out["deferred"], 1)

    def test_a_final_answer_that_is_not_an_object_fails_before_any_write(self):
        d = _doc(testo(500), enrich_status=PENDING, argument_status=PENDING)
        with self.assertRaisesRegex(whole_text.WholeTextError, "riassunto finale"):
            self.go(FakeModel(bad_final=True), knowledge_agent._enrich_one, d)
        d.refresh_from_db()
        self.assertEqual(d.arguments.count(), 0)
        self.assertEqual(d.summary_it, "Riassunto vecchio.")

    def test_the_owner_never_changes(self):
        d = _doc(testo(500), owner_type="owned", enrich_status=PENDING,
                 argument_status=PENDING)
        self.go(FakeModel(), knowledge_agent._enrich_one, d)
        d.refresh_from_db()
        self.assertEqual(d.owner_type, "owned")


class ReelLetturaIntera(TestCase):
    def reel(self, text, caption="didascalia", **kw):
        acc = TrackedAccount.objects.create(username=f"acc{Reel.objects.count()}",
                                            owner_type="competitor")
        r = Reel.objects.create(account=acc, shortcode=f"R{Reel.objects.count()}",
                                caption=caption, transcribe_status=DONE, **kw)
        Transcript.objects.create(reel=r, text=text)
        return r

    def go(self, model, fn, *args):
        a, b, c = _patches(model)
        with a, b, c:
            return fn(*args)

    def test_a_transcript_up_to_8000_and_a_long_caption_are_read_whole(self):
        t = testo(100)
        cap = "Didascalia lunga. " * 150  # 2 700 characters, over the old 1 500
        r = self.reel(t, cap)
        seen = []

        def short(system, user, **kw):
            seen.append(user)
            if "DIDASCALIA" in user and "REGOLE FONDAMENTALI" in user:
                return FakeModel()(system, user)
            return {"argomenti": []}
        self.go(short, enrich_agent._enrich_one, r)
        self.go(short, enrich_agent._extract_arguments, r)
        self.assertEqual(len(seen), 2)
        for u in seen:
            self.assertIn(t, u)
            self.assertIn(cap, u)

    def test_a_long_transcript_is_read_in_pieces_with_the_real_opening(self):
        t = testo(500)
        cap = "Una didascalia."
        r = self.reel(t, cap)
        m = FakeModel(two=True)
        with mock.patch.object(client, "last_model_used", return_value="modello-finto"):
            self.go(m, enrich_agent._enrich_one, r)
        r.refresh_from_db()
        self.assertEqual((r.enrich_status, r.argument_status, r.full_text_status),
                         (DONE, DONE, DONE))
        self.assertEqual(len(m.pieces_asked()), len(whole_text.split_text(t)))
        final = m.finals()[0]
        self.assertIn(t[:1500], final)       # hook and hook analysis see the real start
        self.assertIn(cap, final)
        enr = Enrichment.objects.get(reel=r)
        self.assertEqual(enr.llm_model, "modello-finto")
        self.assertEqual(enr.summary_it, "Riassunto di tutto il testo.")
        self.assertEqual(r.arguments.count(), whole_text.CLAIMS_LONG)
        for a in r.arguments.all():
            self.assertIn(a.quote, t)

    def test_the_old_vector_is_emptied_so_the_embed_stage_redoes_it(self):
        r = self.reel(testo(500))
        ReelEmbedding.objects.create(reel=r, vector=[0.1, 0.2], model_name="m")
        self.go(FakeModel(), enrich_agent._enrich_one, r)
        self.assertEqual(ReelEmbedding.objects.get(reel=r).vector, [])

    def test_a_failed_piece_makes_the_reel_failed_and_saves_nothing(self):
        r = self.reel(testo(500))
        Enrichment.objects.create(reel=r, summary_it="vecchio")
        m = FakeModel(fail_piece=2)
        a, b, c = _patches(m)
        with a, b, c, mock.patch.object(client, "available", return_value=True), \
                mock.patch.object(enrich_agent.progress, "note"):
            out = enrich_agent.run(Context())
        r.refresh_from_db()
        self.assertEqual((r.enrich_status, r.argument_status, r.full_text_status),
                         (FAILED, FAILED, FAILED))
        self.assertIn("pezzo 2 di", r.last_error)
        self.assertEqual(out["enrich_failed"], 1)
        self.assertEqual(Enrichment.objects.get(reel=r).summary_it, "vecchio")
        self.assertEqual(r.arguments.count(), 0)

    def test_a_reel_read_on_the_short_road_gets_full_text_done_from_the_stage(self):
        r = self.reel("Un parlato breve ma con abbastanza parole per essere analizzato bene.")
        m = FakeModel()
        a, b, c = _patches(m)
        with a, b, c, mock.patch.object(client, "available", return_value=True), \
                mock.patch.object(enrich_agent.progress, "note"):
            enrich_agent.run(Context())
        r.refresh_from_db()
        self.assertEqual((r.enrich_status, r.full_text_status), (DONE, DONE))

    def test_the_account_owner_never_changes(self):
        r = self.reel(testo(500))
        self.go(FakeModel(), enrich_agent._enrich_one, r)
        r.refresh_from_db()
        self.assertEqual(r.account.owner_type, "competitor")


class StatoNuovoDiDefault(TestCase):
    def test_a_new_row_starts_pending(self):
        d = _doc("Breve.", enrich_status=PENDING)
        self.assertEqual(d.full_text_status, PENDING)
        acc = TrackedAccount.objects.create(username="z", owner_type="owned")
        self.assertEqual(Reel.objects.create(account=acc, shortcode="Z").full_text_status,
                         PENDING)


class ReprocessAllineaLoStato(TestCase):
    """`reprocess` keeps `full_text_status` true, like the pipeline stage does."""

    def reel(self, text, **kw):
        acc = TrackedAccount.objects.create(username="rp", owner_type="competitor")
        r = Reel.objects.create(account=acc, shortcode="RP1", caption="c",
                                transcribe_status=DONE, enrich_status=DONE,
                                argument_status=DONE, **kw)
        Transcript.objects.create(reel=r, text=text)
        return r

    def run_enrich(self, model):
        from django.core.management import call_command
        a, b, c = _patches(model)
        import io
        with a, b, c:
            call_command("reprocess", "--stage", "enrich", stdout=io.StringIO(),
                         stderr=io.StringIO())

    def test_a_reel_of_5000_characters_becomes_done_after_reprocess(self):
        r = self.reel(testo(70))  # ~5 000 characters: read whole on the short road
        self.assertEqual(r.full_text_status, PENDING)
        self.run_enrich(FakeModel())
        r.refresh_from_db()
        self.assertEqual(r.full_text_status, DONE)

    def test_a_failed_piece_in_reprocess_ends_failed_not_done(self):
        r = self.reel(testo(500))
        self.run_enrich(FakeModel(fail_piece=2))
        r.refresh_from_db()
        self.assertEqual((r.enrich_status, r.argument_status, r.full_text_status),
                         (FAILED, FAILED, FAILED))
        self.assertIn("pezzo 2 di", r.last_error)

    def test_the_old_cut_rule_is_speech_and_over_the_cut(self):
        cut = enrich_agent.cut_by_old_rule
        self.assertFalse(cut("a" * 39, "c" * 2000))   # no speech: caption read whole
        self.assertTrue(cut("a" * 40, "c" * 2000))
        self.assertFalse(cut("a" * 3000, "c" * 1500))
        self.assertTrue(cut("a" * 3001, ""))
        self.assertTrue(cut("a" * 100, "c" * 1501))

    def test_a_new_transcript_without_speech_stays_done(self):
        self.assertFalse(enrich_agent.cut_by_old_rule("nuovo parlato", "c" * 2000))

    def test_a_new_transcript_puts_the_status_back_to_pending(self):
        import io
        import tempfile
        from pathlib import Path
        from django.core.management import call_command
        from django.test import override_settings
        r = self.reel("vecchio", audio_file="a/x.mp3", full_text_status=DONE)
        with tempfile.TemporaryDirectory() as media:
            (Path(media) / "a").mkdir()
            (Path(media) / "a/x.mp3").write_bytes(b"x")
            res = {"text": ("nuovo parlato " * 300), "segments": [], "language": "it",
                   "model_name": "m", "duration": 1}
            with override_settings(MEDIA_ROOT=media), \
                    mock.patch("pipeline.agents.transcriber_agent._transcribe",
                               return_value=res):
                call_command("reprocess", "--stage", "transcribe",
                             stdout=io.StringIO(), stderr=io.StringIO())
        r.refresh_from_db()
        self.assertEqual((r.enrich_status, r.argument_status, r.full_text_status),
                         (PENDING, PENDING, PENDING))
