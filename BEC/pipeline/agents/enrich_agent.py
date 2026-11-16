"""
pipeline/agents/enrich_agent.py
===============================
EnrichAgent — one LLM call per reel with enrich_status='pending':
extracts summary_it, topics, hook, target audience, content_format.

Then extracts standalone arguments/claims (layer-2) for reels with
argument_status='pending'. Both stages are idempotent and skip gracefully
when no model can answer (pipeline continues).

Both stages run ONE reel at a time by default (ENRICH_WORKERS=1). They used to
run five (measured 2026-07-27: 17 s -> 3.6 s a reel on Anthropic), but the
ceiling is Groq's per-minute token cap, not the number of threads, and five
threads retrying together were what pushed 169 of 287 Groq calls into a refusal
on 2026-11-15 (and then onto the local model). It also matters for the local
backstop, which does one generation at a time. The cap is WAITED OUT inside
`client.chat()` (a 429 says nothing about the content), so a rate limit never
becomes a failed reel.

By default a round has no limit on local calls: with Groq out the work queues on
the local model. If PIPELINE_LOCAL_MAX_CALLS is set above 0 (settings.py) and
runs out (`LLMLocalBudget`) the stage stops, says so in its note, and the reels
it did not try STAY `pending` for the next round — they are not `failed`.
Real failures stay `failed`; this is not one.

The whole transcript is read (2026-11-16; before, the first 3 000 characters).
Up to 8 000 characters: one call for the analysis and one for the claims, both on
the whole text and the whole caption. Above: pieces of ~6 000 characters, one call
each, then one call that writes the analysis from the notes — see
`pipeline/whole_text.py` for the rule and for why. In that case analysis AND
claims are saved together at the end, and a failed piece makes the reel `failed`
(`enrich_status`, `argument_status`, `full_text_status`), never half-saved.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

from django.db.models import Q

from django.db import transaction

from core import progress
from core.models import (DONE, FAILED, PENDING, SKIPPED, Enrichment, Reel,
                         ReelArgument, ReelEmbedding)
from llm import client, prompts
from llm.client import NOT_THE_ITEMS_FAULT, LLMLocalBudget, LLMRateLimit
from pipeline import whole_text

logger = logging.getLogger(__name__)

# The OLD cut: until 2026-11-16 the analysis and the claims read only this much of
# a transcript. Nothing is cut any more (whole_text.SHORT_MAX and the pieces);
# the number stays because `nota_analisi` of the MCP connector names it for the
# reels still waiting to be read whole (`full_text_status` not `done`).
TRANSCRIPT_CHARS_READ = 3000

VALID_FORMATS = {
    "talking_head", "voiceover", "tutorial", "testimonianza",
    "text_overlay", "intervista", "altro",
}
_DELAY = 0.3

# One by default (see the module docstring): the ceiling is Groq's per-minute
# token cap and the local model's single slot, not the thread count. The rate
# limit itself is waited out in `client.chat()`; `_with_retry` below only matters
# if someone raises this above 1 and a limit still escapes.
_WORKERS = max(1, int(os.environ.get("ENRICH_WORKERS", "1")))
# A 429 is not a failure of the reel. Marking it FAILED would be permanent —
# failures are deliberately never auto-retried — so a rate limit has to be
# waited out rather than recorded as a defect in the content.
_RATE_RETRIES = 4


def _tracked(call, item):
    """Count one item on the stage's bar and name it for the model calls it
    makes. It runs INSIDE the worker thread, not in the loop that collects
    results: there the results arrive in submission order and late, so a slow
    first reel would hold the whole bar still. Counted once per item, not per
    rate-limit retry."""
    progress.start_item(*progress.describe(item))
    try:
        out = call()
    except NOT_THE_ITEMS_FAULT:
        # Not tried, not failed: it stays pending for the next round.
        progress.item_done("skipped")
        raise
    except BaseException:
        progress.item_done("failed")
        raise
    progress.item_done("done")
    return out


def _with_retry(fn, reel):
    """One unit of work, in its own thread, patient with rate limits."""
    from django.db import connection

    def _attempts():
        for attempt in range(_RATE_RETRIES):
            try:
                return fn(reel)
            except LLMRateLimit as exc:
                if exc.daily or attempt == _RATE_RETRIES - 1:
                    raise
                wait = min(max(exc.retry_after, 2.0), 60.0)
                logger.info("[enrich] %s: limite di frequenza, attendo %.0fs",
                            reel.shortcode, wait)
                time.sleep(wait)
        raise RuntimeError("unreachable")

    try:
        return _tracked(_attempts, reel)
    finally:
        # Threads get their own connection; leaving them open exhausts the
        # database's connection slots over a long run.
        connection.close()


def _parallel(reels, fn):
    """Run fn over reels concurrently, yielding (reel, result, error)."""
    if _WORKERS == 1:
        for reel in reels:
            try:
                yield reel, _tracked(lambda: fn(reel), reel), None
            except Exception as exc:  # noqa: BLE001
                yield reel, None, exc
        return
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {pool.submit(_with_retry, fn, r): r for r in reels}
        for fut, reel in futures.items():
            try:
                yield reel, fut.result(), None
            except Exception as exc:  # noqa: BLE001
                yield reel, None, exc


def note_stopped(deferred: int, exc: BaseException | None = None) -> str:
    """Say, on the stage and in the log, that the round stopped without being
    able to try some items — and why — and what it left for the next one.

    Two reasons, neither a failure of the content: the round used its cap of
    local calls, or the local model could not be reached (busy, stopped). If a
    remote provider is switched off (refused key) that is said too: it is the
    reason the work was on the slow model at all."""
    from django.conf import settings

    if isinstance(exc, client.LLMLocalUnavailable):
        why = "il modello locale non era disponibile (occupato o spento)"
    else:
        n = settings.PIPELINE_LOCAL_MAX_CALLS
        why = (f"usate le {n} chiamate al modello locale del giro" if n != 1 else
               "usata la chiamata al modello locale del giro")
    text = f"Fermato: {why}. {deferred} restano in attesa per il giro dopo."
    if client.remote_problem():
        text = f"{client.remote_problem()}. {text}"
    progress.note(text)
    logger.warning("[pipeline] %s", text)
    return text


def note_remote_problem() -> None:
    """A stage that finished normally still says if Groq was switched off."""
    if client.remote_problem():
        progress.note(client.remote_problem())


_MIN_CAPTION_CHARS = 80  # below this a caption is hashtags/greetings, not content


def _norm(text: str) -> str:
    """Fold text for substring checks: unicode-normalised, lowercase, single
    spaces. Instagram captions use mathematical-bold letters that would
    otherwise never match."""
    import re as _re
    import unicodedata
    t = unicodedata.normalize("NFKC", text or "").lower()
    return _re.sub(r"\s+", " ", t).strip()


def _caption_signal(caption: str) -> str:
    """Caption text with hashtags/mentions stripped — what actually says
    something about the content."""
    import re as _re
    return _re.sub(r"[#@]\w+", " ", caption or "").strip()


def classify_evidence(reel: Reel) -> tuple[str, str]:
    """Return (evidence, transcript_text).

    'transcript'   — there is spoken content to analyse
    'caption_only' — no audio, but the caption carries real information
    'insufficient' — neither; the model would have to invent everything
    """
    transcript = getattr(reel, "transcript", None)
    text = (transcript.text if transcript else "") or ""
    if len(text.strip()) >= 40:
        return "transcript", text
    if len(_caption_signal(reel.caption)) >= _MIN_CAPTION_CHARS:
        return "caption_only", ""
    return "insufficient", ""


def cut_by_old_rule(transcript_text: str, caption: str) -> bool:
    """Was the analysis made before 2026-11-16 on a cut text? Only a reel WITH
    speech (a transcript of 40+ characters) is: its transcript went over 3 000 or
    its caption over 1 500. One without speech had its caption read whole.
    Migration 0028 writes the same rule with its own numbers."""
    if len(transcript_text or "") < 40:
        return False
    return len(transcript_text) > TRANSCRIPT_CHARS_READ or len(caption or "") > 1500


def canonical_topic(t: str) -> str:
    """Fold synonym variants onto one label so the same idea stops arriving
    under three names ("terapia con ormoni bioidentici" == "ormoni bioidentici")."""
    t = " ".join((t or "").lower().split())
    return prompts.TOPIC_SYNONYMS.get(t, t)


def pick_primary_topic(raw: str, topics: list[str]) -> str:
    """Keep the model's specific answer, or recover one from the topic list.

    An umbrella label ("menopausa") is rejected: it is true of nearly every
    reel here and therefore separates nothing.
    """
    cand = canonical_topic(raw)
    if cand and cand not in prompts.UMBRELLA_TOPICS:
        return cand[:80]
    for t in topics:  # fall back to the first genuinely specific topic
        c = canonical_topic(t)
        if c and c not in prompts.UMBRELLA_TOPICS:
            return c[:80]
    return ""


# Measured 2026-09-13 over the whole backlog on Sonnet 5: at 700 tokens six of
# ~150 answers came back truncated mid-string, and at 1200 two more still did
# (stop_reason=max_tokens at exactly the ceiling — Sonnet writes long Italian
# summaries). A truncated answer is a LOST analysis, not a shorter one, and
# output is billed on what is actually produced, so a high ceiling costs
# nothing on the answers that already fit.
ENRICH_MAX_TOKENS = 2000


def _enrich_user(caption: str, transcript: str, evidence: str) -> str:
    user = prompts.ENRICH_USER_TEMPLATE.format(
        caption=caption, transcript=transcript or "(nessuna trascrizione)")
    if evidence == "caption_only":
        user += prompts.ENRICH_CAPTION_ONLY_NOTE
    return user


def build_enrich_prompt(reel: Reel) -> tuple[str, str, str] | None:
    """(system, user, evidence) for one reel read on the SHORT road (a transcript
    up to whole_text.SHORT_MAX), or None when there is nothing worth asking.
    Kept apart from the call so the question has one definition. Caption and
    transcript go in whole: Instagram allows 2 200 characters of caption, and 197
    reels went over the old 1 500 cut.
    """
    evidence, transcript_text = classify_evidence(reel)
    if evidence == "insufficient":
        return None
    return (prompts.ENRICH_SYSTEM,
            _enrich_user(reel.caption or "", transcript_text, evidence), evidence)


def enrichment_fields(data, evidence: str, model_name: str) -> dict:
    """Validate one model answer and turn it into the Enrichment columns, without
    writing anything. Raises ValueError for an answer that is not an object.

    Same canonicalisation, same truncation, same guard on the hook for every
    answer, whoever wrote it — the pipeline and `import_reanalysis` both come here.
    """
    # The model occasionally wraps the object in an array ([{...}]) — 10 of
    # ~150 answers on the 2026-09-13 run. The content is fine; only the
    # envelope is wrong, and crashing on it threw away a paid answer.
    if isinstance(data, list):
        data = next((d for d in data if isinstance(d, dict)), None)
    if not isinstance(data, dict):
        raise ValueError("risposta non utilizzabile: atteso un oggetto JSON")

    fmt = str(data.get("content_format", "")).strip().lower()
    if fmt not in VALID_FORMATS:
        fmt = "altro"
    topics = data.get("topics") or []
    if isinstance(topics, str):
        topics = [t.strip() for t in topics.split(",") if t.strip()]
    seen, canon = set(), []
    for t in topics:
        c = canonical_topic(str(t))
        if c and c not in seen:
            seen.add(c)
            canon.append(c)
    topics = canon
    primary = pick_primary_topic(str(data.get("primary_topic", "")), topics)

    hook = str(data.get("hook_text", ""))[:500]
    if evidence == "caption_only":
        hook = ""  # there is no spoken opening to quote

    return {
        "summary_it": str(data.get("summary_it", ""))[:2000],
        "topics": [t[:60] for t in topics][:6],
        "primary_topic": primary,
        "hook_text": hook,
        "hook_analysis_it": "" if not hook else str(data.get("hook_analysis_it", ""))[:1000],
        "target_audience_it": str(data.get("target_audience_it", ""))[:1000],
        "content_format": fmt,
        "llm_model": (model_name or "")[:64],
        "evidence": evidence,
        "is_on_topic": bool(data.get("is_on_topic", True)),
        "off_topic_reason": str(data.get("off_topic_reason", ""))[:300],
        "raw_response": data,
    }


def write_enrichment(reel: Reel, data: dict, evidence: str, model_name: str) -> None:
    """Turn one model answer into the Enrichment row."""
    Enrichment.objects.update_or_create(
        reel=reel, defaults=enrichment_fields(data, evidence, model_name))


def save_whole_reel(reel: Reel, data, evidence: str, model_name: str,
                    claims: list[dict]) -> None:
    """Analysis AND claims in one transaction, the reel marked read whole.

    The one save of a reel read in pieces, and the one `import_reanalysis` uses
    for answers made outside the pipeline. The answer is validated BEFORE
    anything is written, so a bad one leaves the old analysis and the old claims
    untouched; the customer never sees a reel without them.
    """
    fields = enrichment_fields(data, evidence, model_name)
    with transaction.atomic():
        Enrichment.objects.update_or_create(reel=reel, defaults=fields)
        reel.arguments.all().delete()
        ReelArgument.objects.bulk_create(
            [ReelArgument(reel=reel, text_it=c["testo"], quote=c["citazione"])
             for c in claims])
        reel.enrich_status = reel.argument_status = reel.full_text_status = DONE
        reel.last_error = ""
        reel.save(update_fields=["enrich_status", "argument_status",
                                 "full_text_status", "last_error"])
        # The vector was built from the old summary: empty it, and the embed
        # stage (which computes the vectors that are missing or empty) redoes it
        # tonight. Saved, not .update(): `updated_at` is what makes the search
        # index notice.
        for emb in ReelEmbedding.objects.filter(reel=reel):
            emb.vector = []
            emb.save(update_fields=["vector", "updated_at"])


def _embed_texts(texts: list[str]):
    from pipeline.agents import cluster_agent
    return cluster_agent._get_embedder().encode(
        texts, normalize_embeddings=True, show_progress_bar=False)


def _read_whole_reel(reel: Reel, transcript: str) -> list[dict]:
    """A transcript over whole_text.SHORT_MAX: pieces, notes, one final analysis,
    one save. Returns the claims saved."""
    caption = reel.caption or ""

    def ask_piece(user):
        return client.chat_json(prompts.ARGUMENTS_SYSTEM, user, max_tokens=1200,
                                model=client.model_for("analysis"))

    def ask_final(block):
        return client.chat_json(
            prompts.ENRICH_SYSTEM, _enrich_user(caption, block, "transcript"),
            max_tokens=ENRICH_MAX_TOKENS, model=client.model_for("analysis"))

    # Hook and hook analysis speak about the opening: the final call also gets
    # its first words as they are, not only notes about them.
    data, claims = whole_text.read_whole(
        transcript, "un reel di Instagram", ask_piece, ask_final,
        opening=transcript[:1500], embed=_embed_texts)
    try:
        save_whole_reel(reel, data, "transcript", client.last_model_used(), claims)
    except ValueError as exc:
        raise whole_text.WholeTextError(f"riassunto finale: {exc!r}") from exc
    return claims


def _enrich_one(reel: Reel) -> None:
    evidence, transcript_text = classify_evidence(reel)

    if evidence == "insufficient":
        # Nothing to analyse. Asking anyway is exactly how the model ended up
        # inventing medical claims for a reel that only said "grazie a tutti".
        Enrichment.objects.update_or_create(
            reel=reel,
            defaults={"summary_it": "", "topics": [], "primary_topic": "", "hook_text": "",
                      "hook_analysis_it": "", "target_audience_it": "",
                      "content_format": "altro", "llm_model": "",
                      "evidence": evidence, "raw_response": {}},
        )
        logger.info("[enrich] %s: dati insufficienti — nessuna chiamata LLM", reel.shortcode)
        return

    if evidence == "transcript" and whole_text.is_long(transcript_text):
        _read_whole_reel(reel, transcript_text)  # analysis + claims, saved together
        return

    built = build_enrich_prompt(reel)
    assert built is not None  # "insufficient" returned above
    system, user, evidence = built

    # Reading a transcript well is the whole point of this step.
    data = client.chat_json(system, user, max_tokens=ENRICH_MAX_TOKENS,
                            model=client.model_for("analysis"))
    write_enrichment(reel, data, evidence, client.last_model_used())


def _extract_arguments(reel: Reel) -> int:
    evidence, transcript_text = classify_evidence(reel)
    if evidence != "transcript":
        # No spoken content: any "claim" would be produced from thin air.
        reel.arguments.all().delete()
        return 0

    if whole_text.is_long(transcript_text):
        if reel.argument_status == DONE and reel.full_text_status == DONE:
            # `_enrich_one` has just read it in pieces and saved the claims with
            # the analysis (reprocess and uploads call the two in a row): reading
            # it again would only repeat the same dozen calls.
            return reel.arguments.count()
        return len(_read_whole_reel(reel, transcript_text))

    user = prompts.ARGUMENTS_USER_TEMPLATE.format(
        caption=reel.caption or "", transcript=transcript_text)
    # 1200, not 600: a reel with several claims plus its verbatim quotes does
    # not fit in 600 tokens, and a truncated answer is unparseable JSON, not a
    # shorter list. 74 of 139 extractions failed that way on 2026-09-13.
    data = client.chat_json(prompts.ARGUMENTS_SYSTEM, user, max_tokens=1200,
                            model=client.model_for("analysis"))
    # The claim survives only if its quote really appears in the source — the
    # caption counts too, a reel can say it in writing.
    claims, dropped, _ = whole_text.verified_claims(
        data, transcript_text + " " + (reel.caption or ""), min_text=8,
        limit=whole_text.CLAIMS_SHORT)
    reel.arguments.all().delete()  # re-extraction replaces
    for c in claims:
        ReelArgument.objects.create(reel=reel, text_it=c["testo"],
                                    quote=c["citazione"])
    if dropped:
        logger.info("[enrich] %s: %d affermazioni scartate (citazione non trovata)",
                    reel.shortcode, dropped)
    return len(claims)


def _fail_whole(obj, exc) -> list[str]:
    """A piece failed: the whole content is `failed`, all three states, and says
    which piece. Returns the fields to save (the caller adds its own)."""
    if not isinstance(exc, whole_text.WholeTextError):
        return []
    obj.enrich_status = obj.argument_status = obj.full_text_status = FAILED
    return ["enrich_status", "argument_status", "full_text_status"]


def run(ctx) -> dict:
    if not client.available():
        return {"skipped": True,
                "note": "nessun modello disponibile (Groq senza chiave, Ollama spento)"}

    # Stage A: enrichment. Include silent reels (transcription SKIPPED) —
    # they still have captions worth enriching.
    qs = Reel.objects.filter(
        Q(transcribe_status=DONE) | Q(transcribe_status=SKIPPED),
        enrich_status=PENDING, is_active=True,
    )
    if ctx.limit:
        qs = qs[: ctx.limit]
    enriched = failed = deferred = 0
    # Materialise before handing out to threads: a lazy, sliced queryset would
    # be re-evaluated per worker.
    reels = list(qs)
    progress.open(len(reels), "reel", "Analisi")
    stopped, stop_exc = False, None
    for reel, _res, exc in _parallel(reels, _enrich_one):
        if isinstance(exc, NOT_THE_ITEMS_FAULT):
            # Left pending on purpose, and the rest of the list with it.
            stopped, stop_exc = True, exc
            deferred = sum(1 for r in reels if r.enrich_status == PENDING)
            break
        if exc is None:
            reel.enrich_status = DONE
            reel.full_text_status = DONE  # read whole: short road or pieces
            reel.last_error = ""
            reel.save(update_fields=["enrich_status", "full_text_status",
                                     "last_error"])
            enriched += 1
        else:
            reel.enrich_status = FAILED
            reel.last_error = repr(exc)[:500]
            reel.save(update_fields=["enrich_status", "last_error"]
                      + _fail_whole(reel, exc))
            failed += 1
            logger.warning("[enrich] %s failed: %r", reel.shortcode, exc)

    # Stage B: argument extraction
    qs2 = Reel.objects.filter(argument_status=PENDING, enrich_status=DONE, is_active=True)
    if ctx.limit:
        qs2 = qs2[: ctx.limit]
    arg_reels = total_args = arg_failed = 0
    arg_list = list(qs2)
    progress.open(len(arg_list), "reel", "Affermazioni")
    for reel, n, exc in _parallel(arg_list, _extract_arguments):
        if isinstance(exc, NOT_THE_ITEMS_FAULT):
            stopped, stop_exc = True, exc
            deferred += sum(1 for r in arg_list if r.argument_status == PENDING)
            break
        if exc is None:
            reel.argument_status = DONE
            reel.save(update_fields=["argument_status"])
            arg_reels += 1
            total_args += n or 0
        else:
            reel.argument_status = FAILED
            reel.last_error = repr(exc)[:500]
            reel.save(update_fields=["argument_status", "last_error"]
                      + _fail_whole(reel, exc))
            arg_failed += 1
            logger.warning("[arguments] %s failed: %r", reel.shortcode, exc)

    # Retry transient failures next run
    # NOTE: failures are deliberately left as FAILED. Resetting them to
    # PENDING (as this used to) hid every error and retried it forever.

    out = {"enriched": enriched, "enrich_failed": failed,
           "arg_reels": arg_reels, "arguments": total_args, "arg_failed": arg_failed}
    if stopped:
        note_stopped(deferred, stop_exc)
        out["deferred"] = deferred
        out["stopped"] = ("modello locale non disponibile"
                          if isinstance(stop_exc, client.LLMLocalUnavailable)
                          else "tetto di chiamate al modello locale")
    else:
        note_remote_problem()
    return out
