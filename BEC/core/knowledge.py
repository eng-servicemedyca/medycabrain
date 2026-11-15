"""
core/knowledge.py
=================
Retrieval over the Medyca knowledge bank — the "second brain" (MEDYC-10).

The knowledge bank has two content types:
  - KnowledgeDocument  (blog articles: Medyca's own and the competitors')
  - Reels              (Medyca's and the competitors') — transcripts + captions

`semantic_search` embeds a query and cosine-ranks it against both sources,
returning unified hits with a snippet + score. It is the engine of the MCP
connector (`mcp_bridge/server.py`, the client's way in) and of
`GET knowledge/search/`, and it calls NO model except the optional reranker.

The in-app chat that used to sit on top (`answer`, RAG with citations) was
removed 2026-11-15: the client uses the connector. Its prompt, the pasted-page
references and `knowledge/ask/` went with it.
"""

from __future__ import annotations

import logging
import re
import threading

import numpy as np

from django.conf import settings

from django.db.models import Count, Q

from core.models import DONE, KnowledgeDocument, Reel
from llm import client, usage

logger = logging.getLogger(__name__)

_embedder = None


# Loading the model is not thread-safe: two threads entering SentenceTransformer
# at the same time leave it half-built and every call then dies with
# "Cannot copy out of meta tensor; no data!". The MCP bridge warms the model in
# a background thread while already serving requests, so that race is not
# hypothetical — it is the normal startup. One lock, held only for the load.
_embedder_lock = threading.Lock()


def _get_embedder():
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:   # another thread may have finished while we waited
                from sentence_transformers import SentenceTransformer
                _embedder = SentenceTransformer(settings.EMBEDDINGS_MODEL)
    return _embedder


def _embed_query(text: str) -> np.ndarray:
    v = _get_embedder().encode([text], normalize_embeddings=True, show_progress_bar=False)[0]
    return np.asarray(v, dtype=np.float32)


_INDEX_CACHE: dict = {}


def _corpus_stamp() -> tuple:
    """Cheap fingerprint of the indexed corpus.

    Two counts and the newest embedding: enough to notice the pipeline
    adding, re-embedding or deactivating anything, without reading 900 rows
    on every question just to discover nothing changed.
    """
    from django.db.models import Max

    from core.models import ReelEmbedding

    # Max(updated_at), not created_at: an in-place re-embed reuses rows and
    # leaves created_at and the counts unchanged, which used to let the search
    # serve a stale index until a restart. updated_at bumps on every save.
    agg = ReelEmbedding.objects.aggregate(n=Count("id"), last=Max("updated_at"))
    docs = KnowledgeDocument.objects.filter(is_active=True).aggregate(
        n=Count("id"), last=Max("updated_at"))
    return (agg["n"], agg["last"], docs["n"], docs["last"],
            Reel.objects.filter(is_active=True, enrich_status=DONE).count())


def _load_index(scope: str = "all") -> list[dict]:
    """Every embedded item the search can return.

    `scope`: "medyca" (own content only), "competitor", or "all". Competitor
    reels carry their account, because "who said this" is half the answer when
    the client compares themselves to the market.
    """
    stamp = _corpus_stamp()
    hit = _INDEX_CACHE.get(scope)
    if hit and hit[0] == stamp:
        return hit[1]

    items = []
    want_owned = scope in ("all", "medyca", "owned")
    want_comp = scope in ("all", "competitor")
    owners = ([] if not want_owned else ["owned"]) + ([] if not want_comp else ["competitor"])
    docs = (KnowledgeDocument.objects
            # is_on_topic=False is the model's own verdict that this page is
            # not editorial content (cookie walls, event pages, recipes):
            # letting it into the index means a search can return a banner.
            # Material the client added on purpose is exempt: the verdict is
            # made against a menopause-centred prompt, which rejected 404 of
            # 835 articles on 2026-09-13 — a TV episode on prediabetes would
            # be judged off-topic and vanish from the library the moment he
            # added it. A model's opinion must not delete a human's choice.
            .filter(is_active=True, owner_type__in=owners)
            .filter(Q(is_on_topic=True) | Q(is_inspiration=True))
            .exclude(embedding=[])
            .select_related("source"))
    for d in docs:
        items.append({
            "kind": "blog", "owner": d.owner_type, "id": d.id, "title": d.title,
            "url": d.source_url, "summary": d.summary_it,
            # The source name plays the role a reel's account plays: for a
            # competitor article, "whose blog said this" is half the answer.
            "account": d.source.name if d.source else (d.author or ""),
            # Travels into the search hit so the MCP can say "this is
            # reference material" and hand back the link.
            "inspiration": d.is_inspiration,
            "text": d.content_text, "topics": d.topics,
            "vec": np.asarray(d.embedding, dtype=np.float32),
            "chunks": d.chunk_vectors or None,
        })
    reels = (
        Reel.objects.filter(account__owner_type__in=owners, is_active=True,
                            enrich_status=DONE)
        .exclude(embedding__isnull=True)
        .select_related("account", "enrichment", "transcript", "embedding")
    )
    for r in reels:
        emb = getattr(r, "embedding", None)
        if not emb or not emb.vector:
            continue
        enr = getattr(r, "enrichment", None)
        tr = getattr(r, "transcript", None)
        # A reel whose video was never downloaded and that has no caption is
        # marked enriched (evidence='insufficient') and still gets a vector —
        # of the empty string, which sits at a fixed point close to everything.
        # Ten of those scored 0.84 on "Bijuva", taking the top three places
        # ahead of the reel actually called "bijuva pro e contro". A source
        # with nothing in it cannot answer anything: keep it out.
        if not ((tr.text if tr else "") or r.caption or
                (enr.summary_it if enr else "")).strip():
            continue
        items.append({
            "kind": "reel",
            "owner": r.account.owner_type,
            "id": r.id,
            "title": (enr.primary_topic if enr else "") or (enr.summary_it if enr else "") or r.caption[:80],
            "url": f"https://www.instagram.com/reel/{r.shortcode}/",
            "summary": (enr.summary_it if enr else ""),
            "account": r.account.username,
            "text": (tr.text if tr else "") or r.caption,
            "topics": enr.topics if enr else [],
            "vec": np.asarray(emb.vector, dtype=np.float32),
            "chunks": emb.chunk_vectors or None,
        })
    _INDEX_CACHE[scope] = (stamp, items)
    return items


def _snippet(text: str, n: int = 320) -> str:
    text = " ".join((text or "").split())
    return text[:n] + ("…" if len(text) > n else "")


def _chunks(text: str, size: int = 700, overlap: int = 120) -> list[str]:
    """Split a document into overlapping passages.

    Sending a summary to the model is not retrieval: the answer usually lives
    in one paragraph in the middle of a transcript. Chunking lets us send the
    passage that actually contains it.
    """
    text = " ".join((text or "").split())
    if len(text) <= size:
        return [text] if text else []
    out, start = [], 0
    while start < len(text):
        out.append(text[start:start + size])
        start += size - overlap
    return out


def _lexical_score(query: str, text: str) -> float:
    """Fraction of the query's distinctive words that appear verbatim.

    Embeddings miss rare tokens — drug and brand names like "Bijuva" are
    exactly what a client asks about, so keyword evidence is blended in.
    """
    import re
    import unicodedata
    norm = lambda t: unicodedata.normalize("NFKC", t or "").lower()
    words = [w for w in re.findall(r"\w+", norm(query)) if len(w) >= 5]
    if not words:
        return 0.0
    hay = norm(text)
    return sum(1 for w in words if w in hay) / len(words)


# Medyca's own material is 70 items against 835 competitor ones. On one global
# ranking those odds decide the outcome: measured, the first Medyca result for
# "Bijuva" landed 27th, for "perimenopausa" 66th, for "cosa manca ai nostri
# contenuti" 99th — so the assistant, asked to compare, truthfully reported having no
# Medyca material and looked disconnected from its own knowledge bank.
#
# The two sides are therefore ranked separately and merged. This is a deliberate
# trade: a guaranteed slot sometimes shows a Medyca item less relevant than the
# competitor it displaced. That is the point of a comparison tool — but only up
# to a point, hence the floor below.
# Expressed as a share, not a count, so the balance survives a smaller top_k —
# which is exactly what happens when a pasted page takes some of the slots.
# Trimming a merged list instead would silently undo the quota: the leftovers
# are re-sorted by score, and on score the competitors win again.
OWNED_SHARE = 5 / 12

# Each side is filtered against its OWN best, not against the global best.
#
# Two reasons. An absolute cutoff does not work: on the nonsense query "ricetta
# della pasta al forno" the best competitor still scored 0.50, because
# similarity values in this space are compressed. And a global reference is
# quietly unfair — the maximum of 835 samples runs higher than the maximum of
# 70 by sample size alone, so measuring Medyca against the competitors' best
# penalises it for being the smaller corpus, which is the very bias this whole
# change exists to remove. It showed up immediately: "cosa manca ai nostri
# contenuti" returned zero Medyca sources, on the one question that is entirely
# about Medyca's own material.
#
# Within a side, 60% of that side's best keeps the real match for "Bijuva"
# (0.40 of 0.40) and drops the padding ("donna", 0.21).
RELEVANCE_FLOOR = 0.60


def _rank(index: list[dict], query: str, qvec) -> list[tuple[float, dict, float]]:
    if not index:
        return []
    mat = np.vstack([it["vec"] for it in index])
    dense = mat @ qvec  # normalized vectors → cosine
    out = []
    for i, it in enumerate(index):
        lex = _lexical_score(query, f"{it['title']} {it['summary']} {it['text']}")
        out.append((0.75 * float(dense[i]) + 0.25 * lex, it, lex))
    out.sort(key=lambda r: -r[0])
    return out


RERANK_POOL = 15  # candidates the LLM reranker reorders before the top_k cut


def semantic_search(query: str, top_k: int = 6, scope: str = "all",
                    rerank: bool = False, only_inspiration: bool = False,
                    kind: str | None = None) -> list[dict]:
    """Hybrid retrieval over the knowledge bank.

    Documents are ranked by embedding similarity blended with verbatim
    keyword evidence; the winning passage inside each document is then
    selected so the generator receives the text that answers the question,
    not the opening lines of the article.

    Under scope "all" the two sides are ranked separately and merged, so
    Medyca's own material is present whenever it has something to say.

    With `rerank`, a wider pool is retrieved (quotas scale with it, so the
    Medyca/competitor balance is preserved), an LLM reorders it by relevance
    to the question — the highest-precision lever given the weak, compressed
    cosine space of the small embedder — and the top_k best are returned. The
    reranker failing (no LLM, bad reply) falls back to the blend order, never
    to an error.

    `kind` ("reel" / "blog" / None) narrows the index to one content type
    BEFORE ranking, exactly as `only_inspiration` does. It is the cheap lever
    behind the typed MCP tools: filtering to the right type up front means the
    rerank pays for a pool of `want` items that are all the right type, instead
    of over-fetching a mixed pool of 24, reranking all of it, and discarding
    most — which cost 11-14s and could starve (8 articles asked out of a
    reel-dominated pool came back as two, because the post-filter ran AFTER the
    cut). Filtered here, a typed search runs in the cerca_tutto regime (~2.6s).
    """
    index = _load_index(scope)
    if kind:
        index = [i for i in index if i.get("kind") == kind]
    if only_inspiration:
        # Rank INSIDE the reference material, never filter after the fact: a
        # handful of short reference cards would never reach the top of a
        # corpus of 1.483 items, so a post-filter returns an empty list and
        # looks like "we have nothing on that" when we do.
        index = [i for i in index if i.get("inspiration")]
    if not index:
        return []
    q = _embed_query(query)
    # Retrieve a pool, cut to top_k after the LLM has had its say.
    want = max(top_k, RERANK_POOL) if rerank else top_k

    # A question that names the blogs must be answered from the blogs. Neither
    # signal catches this on its own: "blog" is four letters, under the
    # lexical scorer's length floor, and in embedding space an article about a
    # subject sits next to a reel about the same subject. Measured: asked to
    # compare blogs, retrieval returned 11 reels and 1 article while 30
    # articles sat in the bank — and the model rightly refused to answer.
    wants_articles = bool(re.search(r"\bblog\b|\barticol\w*", query, re.I))

    if scope in ("all",):
        owned = _rank([i for i in index if i.get("owner") != "competitor"], query, q)
        comp = _rank([i for i in index if i.get("owner") == "competitor"], query, q)

        def _keep(ranked, slots):
            # Padding a quota with weak matches is another way of answering
            # badly, so a slot the side cannot fill well is left to the other.
            if not ranked:
                return []
            floor = ranked[0][0] * RELEVANCE_FLOOR
            take = [r for r in ranked[:slots] if r[0] >= floor]
            if wants_articles:
                # Reserve up to half the side's slots for its best articles,
                # displacing its weakest reels. The articles are measured
                # against the best ARTICLE, not the side floor — the side
                # floor is set by the reels, and asking blogs to clear a bar
                # set by reels is the same per-group unfairness the two-side
                # split exists to remove, one level down.
                side_blogs = [r for r in ranked if r[1]["kind"] == "blog"]
                b_floor = side_blogs[0][0] * RELEVANCE_FLOOR if side_blogs else 0.0
                blogs = [r for r in side_blogs
                         if r[0] >= b_floor and r not in take][:max(1, slots // 2)]
                for b in blogs:
                    non_blog = [r for r in take if r[1]["kind"] != "blog"]
                    if len(take) < slots:
                        take.append(b)
                    elif non_blog:
                        take.remove(non_blog[-1])
                        take.append(b)
                take.sort(key=lambda r: -r[0])
            return take

        owned_slots = max(1, round(want * OWNED_SHARE))
        take_owned = _keep(owned, owned_slots)
        take_comp = _keep(comp, want - owned_slots)
        spare = want - len(take_owned) - len(take_comp)
        if spare > 0:
            seen = {id(r[1]) for r in take_owned + take_comp}
            rest = sorted((r for r in owned + comp if id(r[1]) not in seen),
                          key=lambda r: -r[0])
            take_comp += rest[:spare]
        scored = sorted(take_owned + take_comp, key=lambda r: -r[0])
    else:
        scored = _rank(index, query, q)

    out = []
    for score, it, lex in scored[:want]:
        passage = (_best_passage(it["text"] or it["summary"], q, it.get("chunks"))
                   or _snippet(it["text"]))
        out.append({
            "kind": it["kind"], "owner": it.get("owner", "owned"),
            # Carried through to the hit, not just held on the index item:
            # the MCP builds its answer from these dicts, and a flag that
            # stops here is a flag the client never sees.
            "inspiration": it.get("inspiration", False),
            "account": it.get("account", ""),
            "id": it["id"], "title": it["title"],
            "url": it["url"], "summary": it["summary"], "topics": it["topics"],
            "snippet": passage,
            "score": round(float(score), 3),
            "keyword_match": round(lex, 2),
        })
    if rerank and len(out) > 1:
        out = _rerank(query, out)
    return out[:top_k]


def _rerank(query: str, hits: list[dict]) -> list[dict]:
    """Reorder candidates by LLM-judged relevance to the question.

    One structured call over the whole pool (the same shape eval_mcp uses to
    judge relevance), not one per hit. On any failure the original blend
    order is kept — the reranker sharpens, it must never break retrieval.
    """
    try:
        lines = [f"{i}. [{h['kind']}] {h.get('title','')[:70]} — "
                 f"{(h.get('snippet') or '')[:160]}"
                 for i, h in enumerate(hits)]
        user = ("Ordina questi risultati dal più al meno pertinente alla "
                f"DOMANDA.\n\nDOMANDA: {query}\n\nRISULTATI:\n"
                + "\n".join(lines)
                + '\n\nRestituisci SOLO JSON: {"ordine": [indici dal più '
                  'pertinente]}. Includi ogni indice una volta sola.')
        # 200 tokens was not enough: Sonnet 5 hit the ceiling on every call
        # (2026-09-13), so the reranker silently never ran and retrieval was
        # always served in blend order. The answer is a list of indices plus
        # whatever preamble the model adds — cheap, but not 200-tokens cheap.
        # 1000 was still not enough: with a full RERANK_POOL of long snippets
        # Sonnet 5 sometimes prefaces the JSON with a line of reasoning and
        # tips over 1000, so the MCP search hung (2026-09-15). Two guards:
        # 2000 tokens gives comfortable headroom (measured: the same real
        # pool reranks in ~2-3s and never truncates), and `retries=0` makes a
        # truncation fail *fast* — it is deterministic, so retrying it 3× only
        # multiplies the latency the client feels as "search not working"
        # before this same except-block falls back to the blend order anyway.
        # `default=True`: the MCP search is its own process with no other
        # label, so its calls say "mcp:cerca".
        with usage.scope("mcp:cerca", default=True):
            data = client.chat_json(
                "Sei un valutatore di pertinenza per una ricerca. Solo JSON valido.",
                user, max_tokens=2000, temperature=0.0,
                model=client.model_for("bulk"), retries=0)
        order = data.get("ordine") if isinstance(data, dict) else None
        if not order:
            return hits
        seen, ranked = set(), []
        for idx in order:
            if isinstance(idx, int) and 0 <= idx < len(hits) and idx not in seen:
                seen.add(idx)
                ranked.append(hits[idx])
        # Anything the model dropped keeps its blend order at the tail.
        ranked += [h for i, h in enumerate(hits) if i not in seen]
        return ranked
    except Exception as exc:  # noqa: BLE001 — sharpening is optional, never fatal
        logger.warning("[rerank] fallito, tengo l'ordine del blend: %r", exc)
        return hits


def _best_passage(text: str, qvec, cached=None) -> str:
    """The chunk of `text` closest to the query vector.

    `cached` are the passage vectors computed once by the embed stage, in the
    order _chunks produces them. Encoding them per question instead cost
    15-18s — the whole of a search's latency — so they are only computed here
    when a document predates the change or its text moved on since.
    """
    parts = _chunks(text)
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if cached is not None and len(cached) == len(parts):
        vecs = np.asarray(cached, dtype=np.float32)
    else:
        vecs = np.asarray(
            _get_embedder().encode(parts, normalize_embeddings=True,
                                   show_progress_bar=False),
            dtype=np.float32,
        )
    sims = vecs @ qvec
    return parts[int(np.argmax(sims))]
