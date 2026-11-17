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
an article. Whole text (2026-11-16; before, the summary read the first 6 000 characters and
the claims the first 8 000). Up to 8 000 characters: one call for the analysis and
one for the claims, both on the whole text. Above: pieces of ~6 000 characters,
one call each (at most 3 claims with a quote checked against the piece, plus a
line of notes), then one call that writes the analysis from the notes, at most 12
claims for the text — see `pipeline/whole_text.py` for the rule and for why. In
that case analysis AND claims are saved together at the end, and a failed piece
makes the document `failed`, never half-saved. `full_text_status` says whether the
analysis in force read everything (`nota_analisi` of the MCP connector depends on
it).

Analysis and claims of an article are asked ONE BEHIND THE OTHER (2026-11-17), with
the same beginning of prompt, so the local model reads the text once (see
`enrich_agent`'s docstring and `documentation/low-level/03-llm-and-embeddings.md`).

Failures stay FAILED. The old blanket FAILED→PENDING reset at the end of
every run was an infinite retry loop that also hid the failure; retry is now
an explicit act (reprocess --stage knowledge).
"""

from __future__ import annotations

import logging

from django.conf import settings

from django.db import transaction

from core import progress
from core.models import DONE, FAILED, PENDING, DocumentArgument, KnowledgeDocument
from llm import client, prompts
from llm.client import NOT_THE_ITEMS_FAULT
from pipeline import whole_text

logger = logging.getLogger(__name__)

# The OLD cut: until 2026-11-16 the summary / topic read this much of a text and
# the claims the second number. Nothing is cut any more (whole_text.SHORT_MAX and
# the pieces); the numbers stay because `nota_analisi` of the MCP connector names
# them for the documents still waiting to be read whole (`full_text_status` not
# `done`), so the note says what really happened to THOSE analyses.
DOC_SUMMARY_CHARS_READ = 6000
DOC_CLAIMS_CHARS_READ = 8000

KB_SYSTEM = (
    "Sei un analista di contenuti medici in lingua italiana, specializzato in "
    "menopausa, terapie ormonali e salute femminile. Analizzi articoli di blog "
    "e trascrizioni di video e interviste, di diversi autori: alcuni sono di "
    "Medyca, altri di concorrenti. "
    "Rispondi SEMPRE ed esclusivamente con un oggetto JSON valido."
)

# The JSON the analysis asks for, apart from the rest so the short road (the
# text itself) and the long one (the notes of its pieces) ask the very same thing.
KB_ENRICH_JSON = """\
Restituisci un JSON:
{{
  "summary_it": "riassunto in 2-3 frasi, in italiano",
  "topics": ["4-8 argomenti/parole chiave in italiano, minuscolo"],
  "primary_topic": "IL soggetto specifico dell'articolo, 2-5 parole. Mai un termine ombrello come 'menopausa' o 'salute femminile': ciò che distingue QUESTO articolo dagli altri",
  "is_on_topic": true,
  "off_topic_reason": "se is_on_topic è false: perché (es. ricetta di cucina, pagina promozionale)"
}}
"""

# The analysis prompt is a HEAD (what the text is, the title, the text) and what
# follows. The claims call starts with the very same head (`build_doc_arguments_prompt`):
# Ollama keeps the beginning of the last prompt and reads only what differs, so
# the 7b reads the text once for the two calls (see prompts.ARGUMENTS_TAIL_TEMPLATE).
KB_ENRICH_HEAD = """\
{intro}

TITOLO: {title}

TESTO:
{text}

"""

KB_ENRICH_USER = KB_ENRICH_HEAD + """\
Il testo può essere in un'altra lingua: analizza comunque IN ITALIANO.

""" + KB_ENRICH_JSON


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


def _doc_enrich_user(doc: KnowledgeDocument, text: str) -> str:
    return KB_ENRICH_USER.format(intro=_intro(doc), title=doc.title, text=text)


def _doc_head(doc: KnowledgeDocument, text: str) -> str:
    return KB_ENRICH_HEAD.format(intro=_intro(doc), title=doc.title, text=text)


def build_doc_enrich_prompt(doc: KnowledgeDocument) -> tuple[str, str]:
    """(system, user) for one article, episode or interview read on the SHORT
    road (up to whole_text.SHORT_MAX characters: the text goes in whole). A longer
    text is read in pieces (`_read_whole_doc`) and never comes here."""
    return KB_SYSTEM, _doc_enrich_user(doc, doc.content_text or "")


def apply_doc_enrich(doc: KnowledgeDocument, data) -> list[str]:
    """Validate one analysis answer and put it on the instance, WITHOUT saving.
    Returns the fields it set. Raises ValueError for an answer that is not an
    object. The pipeline and `import_reanalysis` both come here."""
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
    return ["summary_it", "topics", "primary_topic", "is_on_topic",
            "off_topic_reason", "enrich_status", "last_error"]


def write_doc_enrich(doc: KnowledgeDocument, data) -> None:
    """Store one analysis (short road)."""
    fields = apply_doc_enrich(doc, data)
    # The short road read the whole text (a long one is saved by
    # `save_whole_doc`, never here).
    doc.full_text_status = DONE
    doc.save(update_fields=fields + ["full_text_status"])


def save_whole_doc(doc: KnowledgeDocument, data, claims: list[dict] | None) -> None:
    """Analysis AND claims in one transaction, the document marked read whole.

    The one save of a document read in pieces, and the one `import_reanalysis`
    uses for answers made outside the pipeline. The answer is validated BEFORE
    anything is written, so a bad one leaves the old analysis and claims intact.
    `claims=None` keeps the claims there are (an article of up to 8 000
    characters had them made on the whole text already).
    The vector is put back in the queue: it was built from the old summary
    (documentation/low-level/03, «Re-embed after a re-analysis»).
    """
    fields = apply_doc_enrich(doc, data)  # ValueError here: nothing written yet
    with transaction.atomic():
        if claims is not None:
            doc.arguments.all().delete()
            DocumentArgument.objects.bulk_create(
                [DocumentArgument(document=doc, text_it=c["testo"],
                                  quote=c["citazione"]) for c in claims])
            doc.argument_status = DONE
            fields.append("argument_status")
        doc.full_text_status = DONE
        doc.embed_status = PENDING
        doc.save(update_fields=fields + ["full_text_status", "embed_status"])


def _what(doc: KnowledgeDocument) -> str:
    """What the text is, for «pezzo 3 di 7 di …»: the model must not treat a piece
    as a whole text, nor call an episode an article."""
    kind = {"manual": "un'intervista", "video": "un video"}.get(
        doc.source_type, "un articolo del blog")
    return f"{kind} intitolato «{doc.title}»"


def _read_whole_doc(doc: KnowledgeDocument) -> list[dict]:
    """A text over whole_text.SHORT_MAX: pieces, notes, one final analysis, one
    save. Returns the claims saved."""
    text = doc.content_text or ""

    def ask_piece(user):
        return client.chat_json(prompts.ARGUMENTS_SYSTEM, user, max_tokens=1200,
                                local_max_tokens=client.LOCAL_MAX_PIECE,
                                model=client.model_for("analysis"))

    def ask_final(block):
        return client.chat_json(
            KB_SYSTEM, _doc_enrich_user(doc, block), max_tokens=DOC_MAX_TOKENS,
            local_max_tokens=client.LOCAL_MAX_ANALYSIS,
            model=client.model_for("analysis"))

    data, claims = whole_text.read_whole(
        text, _what(doc), ask_piece, ask_final, embed=_embed_texts)
    try:
        save_whole_doc(doc, data, claims)
    except ValueError as exc:
        raise whole_text.WholeTextError(f"riassunto finale: {exc!r}") from exc
    return claims


def _embed_texts(texts: list[str]):
    return _embedder().encode(texts, normalize_embeddings=True,
                              show_progress_bar=False)


def _enrich_one(doc: KnowledgeDocument) -> None:
    if whole_text.is_long(doc.content_text):
        _read_whole_doc(doc)  # analysis + claims, saved together
        return
    system, user = build_doc_enrich_prompt(doc)
    data = client.chat_json(system, user, max_tokens=DOC_MAX_TOKENS,
                            local_max_tokens=client.LOCAL_MAX_ANALYSIS,
                            # The same deep-reading tier the reels get: what
                            # an article claims and how specific its subject
                            # is decide the whole thematic layer above it.
                            model=client.model_for("analysis"))
    write_doc_enrich(doc, data)


def build_doc_arguments_prompt(doc: KnowledgeDocument) -> tuple[str, str] | None:
    """(system, user) for claim extraction on the short road, or None when the
    article is too short to carry a claim worth quoting.

    The system message and the beginning of the user message are the analysis's,
    character for character (the same function builds both), so the local model
    finds the text in its cache; only the tail is new. The title is in the head
    now, hence «non dal titolo» in the tail: a quote taken from it would be
    dropped by the check below."""
    text = doc.content_text or ""
    if len(text.strip()) < 200:
        return None
    return KB_SYSTEM, _doc_head(doc, text) + prompts.ARGUMENTS_TAIL_TEMPLATE.format(
        fonte=prompts.ARGUMENTS_FROM_ARTICLE)


def write_doc_arguments(doc: KnowledgeDocument, data) -> int:
    """Store the claims (short road). The quote must appear verbatim in the text
    or the claim is dropped — the grounding contract, identical for reels."""
    claims, dropped, _ = whole_text.verified_claims(data, doc.content_text or "")
    # Doubles out, THEN the cap: the 7b repeats itself, and a cap before the
    # filter would keep two of the same claim and lose a different one.
    claims = whole_text.merge_claims([claims], whole_text.CLAIMS_SHORT,
                                     embed=_embed_texts)
    doc.arguments.all().delete()  # idempotent re-extraction
    for c in claims:
        DocumentArgument.objects.create(document=doc, text_it=c["testo"],
                                        quote=c["citazione"])
    if dropped:
        logger.info("[knowledge] %s: %d affermazioni scartate (citazione non trovata)",
                    doc.source_url, dropped)
    return len(claims)


def _extract_arguments(doc: KnowledgeDocument) -> int:
    if whole_text.is_long(doc.content_text):
        if doc.argument_status == DONE and doc.full_text_status == DONE:
            # `_enrich_one` has just read it in pieces and saved the claims with
            # the analysis (uploads and reprocess call the two in a row): reading
            # it again would only repeat the same dozen calls.
            return doc.arguments.count()
        return len(_read_whole_doc(doc))
    built = build_doc_arguments_prompt(doc)
    if built is None:
        return 0
    system, user = built
    data = client.chat_json(system, user, max_tokens=DOC_MAX_TOKENS,
                            local_max_tokens=client.LOCAL_MAX_CLAIMS,
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


def _enrich_then_claims(doc: KnowledgeDocument):
    """One document, its two calls one behind the other: (claims made or None,
    the error of the claims or None).

    The analysis comes first and its error is RAISED (the caller marks the document
    failed). The claims' error is RETURNED: the analysis is already saved and stays
    `done` whatever happens next. None for the claims means they were not asked:
    a long text has them from the pieces, and a document whose claims were made
    before only wanted its analysis redone. Back to back because the local model
    keeps the beginning of the last prompt: the claims prompt begins like the
    analysis one, so the text is read once (2026-11-16: 21 s instead of 91)."""
    _enrich_one(doc)
    if doc.argument_status != PENDING:
        return None, None
    try:
        return _extract_arguments(doc), None
    except Exception as exc:  # noqa: BLE001
        return None, exc


def run(ctx) -> dict:
    from pipeline.agents.enrich_agent import _fail_whole, _parallel

    enriched = enrich_failed = embedded = embed_failed = 0
    arg_docs = total_args = arg_failed = deferred = 0
    stopped, stop_exc = False, None

    def claims_done(doc, n):
        nonlocal arg_docs, total_args
        doc.argument_status = DONE
        doc.save(update_fields=["argument_status"])
        arg_docs += 1
        total_args += n or 0

    def claims_failed(doc, exc):
        nonlocal arg_failed
        doc.argument_status = FAILED
        doc.last_error = repr(exc)[:500]
        doc.save(update_fields=["argument_status", "last_error"]
                 + _fail_whole(doc, exc))
        arg_failed += 1
        logger.warning("[knowledge] arguments failed %s: %r", doc.source_url, exc)

    if client.available():
        qs = KnowledgeDocument.objects.filter(
            enrich_status=PENDING, is_active=True).select_related("source")
        if ctx.limit:
            qs = qs[: ctx.limit]
        # The cost of a document is the model's reading time, not CPU:
        # the reel stage's thread pool applies unchanged.
        docs = list(qs)
        progress.open(len(docs), "articoli", "Analisi e affermazioni")
        done_ids = set()
        for doc, res, exc in _parallel(docs, _enrich_then_claims):
            if isinstance(exc, NOT_THE_ITEMS_FAULT):
                # Not tried, not failed: stays pending for the next round.
                stopped, stop_exc = True, exc
                deferred += len(docs) - len(done_ids)
                break
            done_ids.add(doc.id)
            if exc is not None:
                doc.enrich_status = FAILED
                doc.last_error = repr(exc)[:500]
                doc.save(update_fields=["enrich_status", "last_error"]
                         + _fail_whole(doc, exc))
                enrich_failed += 1
                logger.warning("[knowledge] enrich failed %s: %r", doc.source_url, exc)
                continue
            enriched += 1
            n, claims_exc = res
            if claims_exc is None:
                if n is not None:
                    claims_done(doc, n)
            elif isinstance(claims_exc, NOT_THE_ITEMS_FAULT):
                # The analysis is saved; this document's claims, and everything
                # after it, wait for the next round (still `pending`).
                stopped, stop_exc = True, claims_exc
                deferred += 1 + len(docs) - len(done_ids)
                break
            else:
                claims_failed(doc, claims_exc)

        # Only the leftovers of an earlier round (analysis made, claims not) come
        # here: the documents of this round had both calls in the loop above.
        if not stopped:
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
                    claims_done(doc, n)
                else:
                    claims_failed(doc, exc)

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
