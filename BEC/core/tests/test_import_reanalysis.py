"""
`manage.py import_reanalysis`: answers written outside the pipeline (the one-off
redo with Claude Haiku, 2026-11-16) go through the pipeline's own parser and save.

What these protect:
  - a dry run (the default) validates and counts and writes NOTHING;
  - --write: analysis, claims and `full_text_status=done` in one transaction per
    content, the vector put back in the queue, the model recorded;
  - a content is written only if BOTH answers are valid (invented quote, broken
    JSON, one answer missing → nothing, the old analysis stays);
  - idempotent: a content already `done` is not rewritten; `failed` ones are not
    touched; owners never mix; no model call and no `llm_calls` row.
"""

from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from core.models import (DONE, FAILED, PENDING, DocumentArgument, Enrichment,
                         KnowledgeDocument, LLMCall, Reel, ReelArgument,
                         ReelEmbedding, TrackedAccount, Transcript)
from core.tests.test_whole_text import testo
from llm import client

ANALISI_DOC = {"summary_it": "Riassunto fatto su tutto il testo.",
               "topics": ["vampate di calore"], "primary_topic": "vampate di calore",
               "is_on_topic": True, "off_topic_reason": ""}
ANALISI_REEL = dict(ANALISI_DOC, hook_text="Prime parole", hook_analysis_it="Funziona.",
                    target_audience_it="Donne", content_format="talking_head")


def frasi(text):
    return [s for s in text.split(". ") if s]


def claims_from(text, idx=(0, 100, 250)):
    fs = frasi(text)
    return {"argomenti": [{"testo": f"Affermazione {i}", "citazione": fs[i] + "."}
                          for i in idx if i < len(fs)]}


class ImportaLeRisposte(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "input").mkdir()
        (self.dir / "output").mkdir()
        self.rows_in, self.rows_out = [], []
        # The model must never be called: the answers are already written.
        p = mock.patch.object(client, "chat", side_effect=AssertionError("modello chiamato"))
        p.start()
        self.addCleanup(p.stop)

        self.testo_doc = testo(500, "d")
        self.doc = KnowledgeDocument.objects.create(
            source_url="https://x.example/a", title="Puntata", source_type="video",
            owner_type="competitor", content_text=self.testo_doc,
            summary_it="Riassunto vecchio.", enrich_status=DONE, argument_status=DONE,
            embed_status=DONE)
        DocumentArgument.objects.create(document=self.doc, text_it="vecchia", quote="vecchia citazione")
        self.testo_reel = testo(500, "r")
        acc = TrackedAccount.objects.create(username="comp", owner_type="competitor")
        self.reel = Reel.objects.create(account=acc, shortcode="R1", caption="Didascalia",
                                        transcribe_status=DONE, enrich_status=DONE,
                                        argument_status=DONE)
        Transcript.objects.create(reel=self.reel, text=self.testo_reel)
        Enrichment.objects.create(reel=self.reel, summary_it="vecchio", llm_model="groq")
        ReelEmbedding.objects.create(reel=self.reel, vector=[0.5, 0.5], model_name="m")
        ReelArgument.objects.create(reel=self.reel, text_it="vecchia", quote="vecchia citazione")

    # helpers
    def ask(self, kind, pk, task, response, group=1):
        key = f"{kind}:{pk}:{task}"
        self.rows_in.append({"key": key, "group": group, "task": task})
        self.rows_out.append({"key": key,
                              "response": response if isinstance(response, str)
                              else json.dumps(response)})

    def everything(self):
        self.ask("article", self.doc.id, "analysis", ANALISI_DOC, group=1)
        self.ask("article", self.doc.id, "claims", claims_from(self.testo_doc), group=1)
        self.ask("reel", self.reel.id, "analysis", ANALISI_REEL, group=4)
        self.ask("reel", self.reel.id, "claims", claims_from(self.testo_reel), group=4)

    def run_cmd(self, *args):
        for name, rows in (("input", self.rows_in), ("output", self.rows_out)):
            (self.dir / name / "lotto-001.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        out = io.StringIO()
        call_command("import_reanalysis", str(self.dir), *args, stdout=out)
        return out.getvalue()

    def refresh(self):
        self.doc.refresh_from_db()
        self.reel.refresh_from_db()

    # dry run
    def test_the_default_is_a_dry_run_that_counts_and_writes_nothing(self):
        self.everything()
        out = self.run_cmd()
        self.assertIn("dry-run", out)
        self.assertIn("validi: 2", out)
        self.refresh()
        self.assertEqual(self.doc.summary_it, "Riassunto vecchio.")
        self.assertEqual(self.doc.full_text_status, PENDING)
        self.assertEqual([a.text_it for a in self.doc.arguments.all()], ["vecchia"])
        self.assertEqual(Enrichment.objects.get(reel=self.reel).summary_it, "vecchio")
        self.assertEqual(self.reel.full_text_status, PENDING)

    def test_write_and_dry_run_together_are_refused(self):
        self.everything()
        with self.assertRaises(CommandError):
            self.run_cmd("--write", "--dry-run")

    # write
    def test_write_saves_analysis_claims_and_marks_the_content_done(self):
        self.everything()
        out = self.run_cmd("--write", "--model", "claude-haiku")
        self.assertIn("scritti: 2", out)
        self.refresh()
        self.assertEqual((self.doc.full_text_status, self.doc.enrich_status,
                          self.doc.argument_status), (DONE, DONE, DONE))
        self.assertEqual(self.doc.summary_it, "Riassunto fatto su tutto il testo.")
        quotes = [a.quote for a in self.doc.arguments.all()]
        self.assertEqual(len(quotes), 3)           # the old claim is replaced
        for q in quotes:
            self.assertIn(q, self.testo_doc)
        self.assertEqual(self.doc.embed_status, PENDING)   # vector redone tonight
        enr = Enrichment.objects.get(reel=self.reel)
        self.assertEqual((enr.summary_it, enr.llm_model),
                         ("Riassunto fatto su tutto il testo.", "claude-haiku"))
        self.assertEqual(self.reel.full_text_status, DONE)
        self.assertEqual(self.reel.arguments.count(), 3)
        self.assertEqual(ReelEmbedding.objects.get(reel=self.reel).vector, [])

    def test_no_llm_call_is_recorded_and_no_model_is_called(self):
        self.everything()
        before = LLMCall.objects.count()
        self.run_cmd("--write")   # `client.chat` raises if touched (setUp)
        self.assertEqual(LLMCall.objects.count(), before)

    def test_the_owner_never_changes(self):
        self.everything()
        self.run_cmd("--write")
        self.refresh()
        self.assertEqual(self.doc.owner_type, "competitor")
        self.assertEqual(self.reel.account.owner_type, "competitor")

    def test_an_answer_for_one_content_never_lands_on_another(self):
        other = KnowledgeDocument.objects.create(
            source_url="https://x.example/b", title="Altra", owner_type="owned",
            content_text=testo(500, "o"), summary_it="Mia.", enrich_status=DONE,
            argument_status=DONE)
        self.everything()
        self.run_cmd("--write")
        other.refresh_from_db()
        self.assertEqual((other.summary_it, other.full_text_status), ("Mia.", PENDING))

    # idempotence and skips
    def test_a_second_run_rewrites_nothing(self):
        self.everything()
        self.run_cmd("--write")
        self.refresh()
        first = list(self.doc.arguments.values_list("id", flat=True))
        out = self.run_cmd("--write")
        self.assertIn("scritti: 0", out)
        self.assertIn("già fatti (full_text_status=done): 2", out)
        self.refresh()
        self.assertEqual(list(self.doc.arguments.values_list("id", flat=True)), first)

    def test_a_content_failed_for_another_reason_is_not_touched(self):
        self.doc.enrich_status = FAILED
        self.doc.save()
        self.everything()
        out = self.run_cmd("--write")
        self.assertIn("saltati: failed per altri motivi: 1", out)
        self.doc.refresh_from_db()
        self.assertEqual((self.doc.enrich_status, self.doc.summary_it),
                         (FAILED, "Riassunto vecchio."))

    def test_a_content_not_yet_analysed_is_left_to_the_pipeline(self):
        self.reel.enrich_status = PENDING
        self.reel.save()
        self.everything()
        out = self.run_cmd("--write")
        self.assertIn("non ancora analizzati: 1", out)
        self.reel.refresh_from_db()
        self.assertEqual(self.reel.full_text_status, PENDING)

    # invalid answers
    def test_an_invented_quote_discards_the_content_and_keeps_the_old_analysis(self):
        self.ask("article", self.doc.id, "analysis", ANALISI_DOC)
        self.ask("article", self.doc.id, "claims", {"argomenti": [
            {"testo": "x", "citazione": "una citazione che il testo non contiene mai"}]})
        out = self.run_cmd("--write")
        self.assertIn("scartati (risposta non valida): 1", out)
        self.assertIn("nessuna citazione trovata", out)
        self.refresh()
        self.assertEqual(self.doc.summary_it, "Riassunto vecchio.")
        self.assertEqual(self.doc.full_text_status, PENDING)
        self.assertEqual([a.text_it for a in self.doc.arguments.all()], ["vecchia"])

    def test_one_invented_claim_among_true_ones_is_dropped_the_rest_kept(self):
        data = claims_from(self.testo_doc)
        data["argomenti"].append({"testo": "x", "citazione": "frase del tutto inventata qui"})
        self.ask("article", self.doc.id, "analysis", ANALISI_DOC)
        self.ask("article", self.doc.id, "claims", data)
        self.run_cmd("--write")
        self.assertEqual(self.doc.arguments.count(), 3)

    def test_broken_json_discards_the_content(self):
        self.ask("article", self.doc.id, "analysis", "{non è json")
        self.ask("article", self.doc.id, "claims", claims_from(self.testo_doc))
        out = self.run_cmd("--write")
        self.assertIn("JSON non valido", out)
        self.refresh()
        self.assertEqual(self.doc.full_text_status, PENDING)

    def test_an_analysis_with_no_summary_is_refused(self):
        self.ask("article", self.doc.id, "analysis", dict(ANALISI_DOC, summary_it=""))
        self.ask("article", self.doc.id, "claims", claims_from(self.testo_doc))
        self.assertIn("riassunto vuoto", self.run_cmd("--write"))

    def test_one_answer_missing_discards_the_content(self):
        self.ask("reel", self.reel.id, "analysis", ANALISI_REEL, group=4)
        out = self.run_cmd("--write")
        self.assertIn("manca una delle due risposte", out)
        self.reel.refresh_from_db()
        self.assertEqual(self.reel.full_text_status, PENDING)

    def test_a_long_article_needs_its_claims_too(self):
        self.ask("article", self.doc.id, "analysis", ANALISI_DOC)
        self.assertIn("manca la risposta delle affermazioni", self.run_cmd("--write"))

    def test_an_article_up_to_8000_may_come_with_the_analysis_only(self):
        t = testo(100, "c")   # ~7 000 characters: its claims were made whole already
        short = KnowledgeDocument.objects.create(
            source_url="https://x.example/c", title="Media", owner_type="owned",
            content_text=t, summary_it="vecchio", enrich_status=DONE,
            argument_status=DONE, embed_status=DONE)
        DocumentArgument.objects.create(document=short, text_it="resta", quote="resta qui")
        self.ask("article", short.id, "analysis", ANALISI_DOC, group=2)
        out = self.run_cmd("--write")
        self.assertIn("scritti: 1", out)
        short.refresh_from_db()
        self.assertEqual((short.summary_it, short.full_text_status, short.embed_status),
                         ("Riassunto fatto su tutto il testo.", DONE, PENDING))
        self.assertEqual([a.text_it for a in short.arguments.all()], ["resta"])

    def test_unknown_keys_and_unreadable_lines_are_counted_not_fatal(self):
        self.everything()
        self.rows_out.append({"key": "boh:1:analysis", "response": "{}"})
        self.rows_out.append({"key": f"article:999999:analysis", "response": "{}"})
        self.rows_in.append({"key": "article:999999:analysis", "group": 1})
        out = self.run_cmd()
        self.assertIn("chiavi non valide: 1", out)
        self.assertIn("contenuto non trovato o non attivo: 1", out)

    # filters
    def test_group_and_limit(self):
        self.everything()
        out = self.run_cmd("--write", "--group", "4")
        self.assertIn("scritti: 1", out)
        self.assertIn("fuori dal gruppo scelto: 1", out)
        self.refresh()
        self.assertEqual((self.doc.full_text_status, self.reel.full_text_status),
                         (PENDING, DONE))
        out = self.run_cmd("--write", "--limit", "1")
        self.assertIn("scritti: 1", out)
        self.refresh()
        self.assertEqual(self.doc.full_text_status, DONE)

    def test_a_missing_output_folder_is_an_error(self):
        with self.assertRaises(CommandError):
            call_command("import_reanalysis", str(self.dir / "non-esiste"))
