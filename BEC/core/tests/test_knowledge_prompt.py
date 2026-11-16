"""
The words of the analysis prompt follow what the text IS.

Behind it: the summary of a TV episode kept as Medyca's began «L'articolo di
Medyca…» because the prompt said «articolo del blog di Medyca» for everything
(client report 2026-11-16). Blogs and web pages must NOT change: 2 281 analyses
were made with the old words. No model is called: the prompt is only built.
"""

from django.test import TestCase

from core.models import BlogSource, KnowledgeDocument
from pipeline.agents.knowledge_agent import KB_SYSTEM, build_doc_enrich_prompt

# The line as it was written before, kept here to the letter so a change to the
# blog wording fails this test.
_VECCHIO = """\
Analizza questo articolo del blog di {who}{ownership}.

TITOLO: {title}

TESTO:
{text}

Il testo può essere in un'altra lingua: analizza comunque IN ITALIANO."""


def _doc(**kw):
    base = dict(source_url="https://x.example/1", title="Titolo", content_text="Il testo.",
                owner_type="owned", source_type="blog")
    base.update(kw)
    return KnowledgeDocument.objects.create(**base)


class PromptSecondoIlTipo(TestCase):
    def test_a_blog_keeps_the_old_words_to_the_letter(self):
        src = BlogSource.objects.create(name="Blog X", owner_type="competitor",
                                        index_url="https://x.example/blog")
        for doc, who, own in (
                (_doc(source=src, owner_type="competitor"), "Blog X",
                 " (un CONCORRENTE di Medyca)"),
                (_doc(source_url="https://medyca.it/a"), "Medyca",
                 " (il blog di Medyca stessa)"),
                (_doc(source_url="https://medyca.it/b", source_type="other"),
                 "Medyca", " (il blog di Medyca stessa)")):
            with self.subTest(who=who, tipo=doc.source_type):
                _, user = build_doc_enrich_prompt(doc)
                self.assertTrue(user.startswith(_VECCHIO.format(
                    who=who, ownership=own, title="Titolo", text="Il testo.")),
                    user[:300])

    def test_a_video_is_named_for_what_it_is_with_its_channel(self):
        doc = _doc(source_type="video", author="TVRS SRL", is_inspiration=True,
                   source_url="https://vimeo.com/1")
        system, user = build_doc_enrich_prompt(doc)
        self.assertNotIn("articolo del blog", user)
        self.assertNotIn("blog di Medyca", user)
        self.assertIn("TVRS SRL", user)
        self.assertIn("video", user)
        self.assertIn("mai articolo", user)
        self.assertIn("chi parla sono gli ospiti, non Medyca", user)
        self.assertIn("trascrizioni di video e interviste", system)
        self.assertEqual(system, KB_SYSTEM)

    def test_a_video_not_kept_as_reference_does_not_say_guests_speak(self):
        _, user = build_doc_enrich_prompt(
            _doc(source_type="video", author="TVRS SRL",
                 source_url="https://vimeo.com/2"))
        self.assertNotIn("ospiti", user)

    def test_a_video_without_a_channel_does_not_become_medyca(self):
        _, user = build_doc_enrich_prompt(
            _doc(source_type="video", source_url="https://vimeo.com/3"))
        self.assertIn("una fonte esterna", user)

    def test_an_interview_says_interview(self):
        _, user = build_doc_enrich_prompt(
            _doc(source_type="manual", source_url="upload://1"))
        self.assertIn("intervista", user)
        self.assertNotIn("articolo del blog", user)
        self.assertIn("mai articolo", user)
