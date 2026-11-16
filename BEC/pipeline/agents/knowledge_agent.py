"""
pipeline/agents/knowledge_agent.py
==================================
Enriches + embeds blog articles — Medyca's own AND the competitors'.

Parity with the reel pipeline, where it makes sense: the same deep-reading
model (`model_for("analysis")`), a primary_topic under the same rule (the
one specific subject, never an umbrella term), an on-topic verdict, and
claim extraction with the same grounding contract — every claim carries a
verbatim quote from the article or it is not stored.

What deliberately differs from reels: no hook and no content_format — those
describe a video's craft, not an article's.

Language: bodies are never translated. Summaries and topics come out Italian
regardless of the source language, because Italian topic strings are what
clustering and custom-topic matching compare across sources. For non-Italian
documents the embedding uses ONLY the Italian material the model produced —
an English body mixed into the vector makes English docs cluster with each
other instead of by subject.

What the text is: the prompt names it by `source_type` — a blog or a web page is
«un articolo del blog», a video «la trascrizione di un video» of its channel, an
uploaded interview «un'intervista» — so the summary of an episode never calls it
an article. Reading limit, known: the summary reads the first 6 000 characters
and the claims the first 8 000; the rest of a long episode is not summarised
(the MCP connector says so in `nota_analisi`).

Failures stay FAILED. The old blanket FAILED→PENDING reset at the end of
every run was an infinite retry loop that also hid the failure; retry is now
an explicit act (reprocess --stage knowledge).
"""

from __future__ import annotations

import logging

from django.conf import settings

from core import progress
from core.models import DONE, FAILED, PENDING, DocumentArgument, KnowledgeDocument
from llm import client, prompts
from llm.client import NOT_THE_ITEMS_FAULT

logger = logging.getLogger(__name__)

# How much of a text the model reads for the summary / topic and for the claims.
# Named so the MCP connector can say where the analysis stops (`nota_analisi`)
# from the same number the prompts use. Known limit: a long episode is
# summarised on its first third (documentation/low-level/03).
DOC_SUMMARY_CHARS_READ = 6000
DOC_CLAIMS_CHARS_READ = 8000

KB_SYSTEM = (
    "Sei un analista di contenuti medici in lingua italiana, specializzato in "
    "menopausa, terapie ormonali e salute femminile. Analizzi articoli di blog "
    "e trascrizioni di video e interviste, di diversi autori: alcuni sono di "
    "Medyca, altri di concorrenti. "
    "Rispondi SEMPRE ed esclusivamente con un oggetto JSON valido."
)

KB_ENRICH_USER = """\
{intro}

TITOLO: {title}

TESTO:
{text}

Il testo può essere in un'altra lingua: analizza comunque IN ITALIANO.

Restituisci un JSON:
{{
  "summary_it": "riassunto in 2-3 frasi, in italiano",
  "topics": ["4-8 argomenti/parole chiave in italiano, minuscolo"],
  "primary_topic": "IL soggetto specifico dell'articolo, 2-5 parole. Mai un termine ombrello come 'menopausa' o 'salute femminile': ciò che distingue QUESTO articolo dagli altri",
  "is_on_topic": true,
  "off_topic_reason": "se is_on_topic è false: perché (es. ricetta di cucina, pagina promozionale)"
}}
"""


def _embedder():
    from pipeline.agents import cluster_agent
    return cluster_agent._get_embedder()


# Same reasoning as ENRICH_MAX_TOKENS for reels: a truncated answer is a lost
# analysis, not a shorter one, and output is billed on what is produced.
DOC_MAX_TOKENS = 2000


def _intro(doc: KnowledgeDocument) -> str:
    """The opening line of the prompt: it names what the text IS.

    Every document used to be «un articolo del blog di Medyca», so a TV episode
    kept as Medyca's came back summarised as «l'articolo di Medyca» (client
    report 2026-11-16). Blogs and web pages keep the old wording to the letter:
    2 281 analyses must not move. Videos and interviews are named for what they
    are, and told never to call themselves an article.
    """
    if doc.source_type == "manual":
        intro = "Analizza la trascrizione di questa intervista caricata da Medyca."
    elif doc.source_type == "video":
        channel = (doc.source.name if doc.source else doc.author) or "una fonte esterna"
        intro = ("Analizza la trascrizione di questo video (una puntata o un "
                 f"intervento) di {channel}.")
    else:
        who = doc.source.name if doc.source else "Medyca"
        ownership = (" (un CONCORRENTE di Medyca)" if doc.owner_type == "competitor"
                     else " (il blog di Medyca stessa)")
        return f"Analizza questo articolo del blog di {who}{ownership}."
    intro += " Nel riassunto chiamala puntata, video o intervista: mai articolo."
    if doc.is_inspiration:
        intro += (" È materiale di riferimento scelto da Medyca: chi parla sono "
                  "gli ospiti, non Medyca.")
    return intro


def build_doc_enrich_prompt(doc: KnowledgeDocument) -> tuple[str, str]:
    """(system, user) for one article, episode or interview."""
    return KB_SYSTEM, KB_ENRICH_USER.format(
        intro=_intro(doc), title=doc.title,
        text=(doc.content_text or "")[:DOC_SUMMARY_CHARS_READ])


def write_doc_enrich(doc: KnowledgeDocument, data) -> None:
    """Store one analysis."""
    from pipeline.agents.enrich_agent import canonical_topic, pick_primary_topic

    # The model occasionally wraps the object in an array; the content is
    # fine, only the envelope is wrong.
    if isinstance(data, list):
        data = next((d for d in data if isinstance(d, dict)), None)
    if not isinstance(data, dict):
        raise ValueError("risposta non utilizzabile: atteso un oggetto JSON")

    topics = data.get("topics") or []
    if isinstance(topics, str):
        topics = [t.strip() for t in topics.split(",") if t.strip()]
    topics = [canonical_topic(str(t))[:60] for t in topics][:8]
    doc.summary_it = str(data.get("summary_it", ""))[:2000]
    doc.topics = topics
    doc.primary_topic = pick_primary_topic(
        str(data.get("primary_topic", "")), topics)[:80]
    doc.is_on_topic = bool(data.get("is_on_topic", True))
    doc.off_topic_reason = str(data.get("off_topic_reason") or "")[:300] \
        if not doc.is_on_topic else ""
    doc.enrich_status = DONE
    doc.last_error = ""
    doc.save(update_fields=["summary_it", "topics", "primary_topic",
                            "is_on_topic", "off_topic_reason",
                            "enrich_status", "last_error"])


def _enrich_one(doc: KnowledgeDocument) -> None:
    system, user = build_doc_enrich_prompt(doc)
    data = client.chat_json(system, user, max_tokens=DOC_MAX_TOKENS,
                            # The same deep-reading tier the reels get: what
                            # an article claims and how specific its subject
                            # is decide the whole thematic layer above it.
                            model=client.model_for("analysis"))
    write_doc_enrich(doc, data)


def build_doc_arguments_prompt(doc: KnowledgeDocument) -> tuple[str, str] | None:
    """(system, user) for claim extraction, or None when the article is too
    short to carry a claim worth quoting."""
    text = (doc.content_text or "")[:DOC_CLAIMS_CHARS_READ]
    if len(text.strip()) < 200:
        return None
    return prompts.ARGUMENTS_SYSTEM, prompts.ARGUMENTS_USER_TEMPLATE.format(
        transcript=text, caption="")


def write_doc_arguments(doc: KnowledgeDocument, data) -> int:
    """Store the claims. The quote must appear verbatim in the article or the
    claim is dropped — the grounding contract, identical for reels."""
    from pipeline.agents.enrich_agent import _norm

    text = (doc.content_text or "")[:DOC_CLAIMS_CHARS_READ]
    if isinstance(data, list) and data and isinstance(data[0], dict) \
            and "argomenti" in data[0]:
        data = data[0]
    rows = (data.get("argomenti") if isinstance(data, dict) else data) or []
    doc.arguments.all().delete()  # idempotent re-extraction
    haystack = _norm(text)
    created = dropped = 0
    for row in rows[:6]:
        claim = str(row.get("testo") or "").strip()
        quote = str(row.get("citazione") or "").strip()
        if not claim or not quote:
            continue
        needle = _norm(quote)
        if len(needle) < 12 or needle not in haystack:
            dropped += 1
            continue
        DocumentArgument.objects.create(document=doc, text_it=claim[:1000],
                                        quote=quote[:1000])
        created += 1
    if dropped:
        logger.info("[knowledge] %s: %d affermazioni scartate (citazione non trovata)",
                    doc.source_url, dropped)
    return created


def _extract_arguments(doc: KnowledgeDocument) -> int:
    built = build_doc_arguments_prompt(doc)
    if built is None:
        return 0
    system, user = built
    data = client.chat_json(system, user, max_tokens=DOC_MAX_TOKENS,
                            model=client.model_for("analysis"))
    return write_doc_arguments(doc, data)


def _embed_one(doc: KnowledgeDocument) -> None:
    base = f"{doc.title}\n{doc.summary_it}\n{' '.join(doc.topics)}"
    if doc.language and doc.language != "it":
        # Only the Italian material the model produced: mixing an English
        # body into a multilingual vector makes English docs cluster with
        # each other rather than by subject.
        text = base
    else:
        # Same reasoning as _reel_text: the dense vector should read most of
        # the body, not the first 1500 chars. An interview transcript in
        # particular has its substance spread across the whole text.
        text = f"{base}\n{doc.content_text[:4000]}"
    vec = _embedder().encode([text], normalize_embeddings=True,
                             show_progress_bar=False)[0]
    doc.embedding = vec.tolist()
    doc.embedding_model = settings.EMBEDDINGS_MODEL
    doc.embed_status = DONE
    doc.save(update_fields=["embedding", "embedding_model", "embed_status"])


def run(ctx) -> dict:
    from pipeline.agents.enrich_agent import _parallel

    enriched = enrich_failed = embedded = embed_failed = 0
    arg_docs = total_args = arg_failed = deferred = 0
    stopped, stop_exc = False, None

    if client.available():
        qs = KnowledgeDocument.objects.filter(
            enrich_status=PENDING, is_active=True).select_related("source")
        if ctx.limit:
            qs = qs[: ctx.limit]
        # The cost of a document is the model's reading time, not CPU:
        # the reel stage's thread pool applies unchanged.
        docs = list(qs)
        progress.open(len(docs), "articoli", "Analisi")
        done_ids = set()
        for doc, _res, exc in _parallel(docs, _enrich_one):
            if isinstance(exc, NOT_THE_ITEMS_FAULT):
                # Not tried, not failed: stays pending for the next round.
                stopped, stop_exc = True, exc
                deferred += len(docs) - len(done_ids)
                break
            done_ids.add(doc.id)
            if exc is None:
                enriched += 1
            else:
                doc.enrich_status = FAILED
                doc.last_error = repr(exc)[:500]
                doc.save(update_fields=["enrich_status", "last_error"])
                enrich_failed += 1
                logger.warning("[knowledge] enrich failed %s: %r", doc.source_url, exc)

        qs_a = KnowledgeDocument.objects.filter(
            argument_status=PENDING, enrich_status=DONE, is_active=True)
        if ctx.limit:
            qs_a = qs_a[: ctx.limit]
        arg_list = list(qs_a)
        progress.open(len(arg_list), "articoli", "Affermazioni")
        arg_done = 0
        for doc, n, exc in _parallel(arg_list, _extract_arguments):
            if isinstance(exc, NOT_THE_ITEMS_FAULT):
                stopped, stop_exc = True, exc
                deferred += len(arg_list) - arg_done
                break
            arg_done += 1
            if exc is None:
                doc.argument_status = DONE
                doc.save(update_fields=["argument_status"])
                arg_docs += 1
                total_args += n or 0
            else:
                doc.argument_status = FAILED
                doc.last_error = repr(exc)[:500]
                doc.save(update_fields=["argument_status", "last_error"])
                arg_failed += 1
                logger.warning("[knowledge] arguments failed %s: %r",
                               doc.source_url, exc)

    # Embedding needs no LLM; embed anything enriched (or at least fetched).
    qs2 = KnowledgeDocument.objects.filter(
        embed_status=PENDING, is_active=True).exclude(content_text="")
    if ctx.limit:
        qs2 = qs2[: ctx.limit]
    to_embed = list(qs2)
    progress.open(len(to_embed), "articoli", "Vettori")
    for doc in to_embed:
        progress.start_item(*progress.describe(doc))
        try:
            _embed_one(doc)
            embedded += 1
            progress.item_done("done")
        except Exception as exc:  # noqa: BLE001
            progress.item_done("failed")
            doc.embed_status = FAILED
            doc.last_error = repr(exc)[:500]
            doc.save(update_fields=["embed_status", "last_error"])
            embed_failed += 1
            logger.warning("[knowledge] embed failed %s: %r", doc.source_url, exc)

    # NOTE: failures stay FAILED, per project rule. The blanket reset that
    # used to live here re-queued every permanently broken doc on every run —
    # an infinite retry that also hid the failure from every status page.
    out = {"enriched": enriched, "enrich_failed": enrich_failed,
           "arg_docs": arg_docs, "arguments": total_args,
           "arg_failed": arg_failed,
           "embedded": embedded, "embed_failed": embed_failed}
    if stopped:
        from pipeline.agents.enrich_agent import note_stopped
        note_stopped(deferred, stop_exc)
        out["deferred"] = deferred
        out["stopped"] = ("modello locale non disponibile"
                          if isinstance(stop_exc, client.LLMLocalUnavailable)
                          else "tetto di chiamate al modello locale")
    else:
        from pipeline.agents.enrich_agent import note_remote_problem
        note_remote_problem()
    return out
