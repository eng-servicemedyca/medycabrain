"""
pipeline/whole_text.py
======================
Reading a whole text, however long: cut it, read it piece by piece, stitch.

Why it exists. The summary and the claims of a long text used to be made on its
first part (6 000 / 8 000 characters for articles and episodes, 3 000 for reels):
the connector had to say so in `nota_analisi`. A text of 30 000 characters
(~8 700 tokens) cannot go in one request either: Groq's free tier caps a minute
at 8 000 tokens, and the local 7b has a window of 8 192 tokens.

The rule, shared by reels and articles (`enrich_agent`, `knowledge_agent`):

* Up to SHORT_MAX (8 000) characters: the short road, as before — two calls
  (analysis, claims), now both reading the whole text.
* Above: pieces of at most PIECE_TARGET (~6 000) characters, cut at the last
  sentence end (else the last space, never mid-word), NO overlap between pieces
  (an overlap would make the same claim twice). Each piece is ONE call that gives
  its claims (at most CLAIMS_PER_PIECE, each with a quote checked against THAT
  piece) and a line of notes. The pieces' claims are merged in code (duplicates
  out, then chosen in turns from every piece so they cover the whole text, final
  order = order in the text, at most CLAIMS_LONG). One last call writes the
  analysis from the notes. A long text is read ONCE, not twice.
* ONE size for Groq and the local model: who answers is decided inside
  `client.chat()`, call by call, so the same text can have piece 1 on Groq and
  piece 2 on the 7b. Two thresholds would mean pieces that change mid-text.
* A piece that fails fails the whole content (`WholeTextError`): never an
  analysis of 6 pieces out of 7 shown as whole. Nothing is saved until the end
  (the caller does one write). If the model is not available (NOT_THE_ITEMS_FAULT)
  the error passes through untouched: the content stays `pending`, the pieces
  already done are thrown away and redone next round — saving them would need a
  table, for little gain.
* Known limit: past MAX_PIECES (40, ~240 000 characters) the notes no longer fit
  the final call. The longest text today is 85 699 characters (15 pieces).

Nothing here calls a model by itself: the callers pass `ask_piece` / `ask_final`.
documentation/low-level/03-llm-and-embeddings.md has the numbers.
"""

from __future__ import annotations

import logging
import math
import re

from llm import prompts
from llm.client import NOT_THE_ITEMS_FAULT

logger = logging.getLogger(__name__)

# Up to here a text is read whole in one call per task; above, in pieces.
SHORT_MAX = 8000
# A piece is never longer than this (~1 750 tokens, the size the research report
# recommends for small models). Pieces of a text are all about the same length.
PIECE_TARGET = 6000
MAX_PIECES = 40
CLAIMS_PER_PIECE = 3
CLAIMS_SHORT = 6    # up to SHORT_MAX characters, as it always was
CLAIMS_LONG = 12    # longer texts: six would leave an hour-long episode half bare
NOTE_WORDS = 25     # asked of the model; the code only clips at twice this
# Two claims this close (cosine of the vectors the platform already uses) are the
# same claim. NOT tuned: to be checked on the first contents read this way.
DEDUP_SIMILARITY = 0.90

_SENTENCE_END = re.compile(r"[.!?…][\"'»”)]*\s|\n")


class WholeTextError(Exception):
    """A piece (or the final summary) failed. The content is `failed`, with this
    message in `last_error`; nothing was saved."""


def _norm(text: str) -> str:
    # Lazy: enrich_agent imports this module.
    from pipeline.agents.enrich_agent import _norm as norm
    return norm(text)


def _cut(text: str, start: int, limit: int) -> int:
    """Where the piece that starts at `start` ends, at most at `limit`."""
    # Prefer a sentence end in the last 40% of the window: a cut right after
    # the first sentence would leave a tiny piece and push the rest down.
    window = start + int((limit - start) * 0.6)
    best = -1
    for m in _SENTENCE_END.finditer(text, window, limit):
        best = m.end()
    if best > start:
        return best
    # Whisper often writes no punctuation at all: the last space, anywhere.
    space = max(text.rfind(c, start + 1, limit) for c in (" ", "\n", "\t"))
    if space > start:
        return space + 1
    return limit  # no space at all: the only case of a cut inside a word


def split_text(text: str) -> list[str]:
    """The text in pieces that glue back to the exact text ("".join(...) == text).

    8 000 characters or less is one piece (the short road). Above, `n` pieces of
    about equal length, none over PIECE_TARGET. The size is recomputed on what is
    left after each cut, so a cut made early (a sentence end found sooner) cannot
    leave a last piece longer than the limit.
    """
    text = text or ""
    if len(text) <= SHORT_MAX:
        return [text]
    pieces, pos = [], 0
    while True:
        rest = len(text) - pos
        k = math.ceil(rest / PIECE_TARGET)
        if k <= 1:
            pieces.append(text[pos:])
            return pieces
        cut = _cut(text, pos, pos + math.ceil(rest / k))
        pieces.append(text[pos:cut])
        pos = cut


def is_long(text: str) -> bool:
    return len(text or "") > SHORT_MAX


def claims_limit(text: str) -> int:
    return CLAIMS_LONG if is_long(text) else CLAIMS_SHORT


def verified_claims(data, source_text: str, *, min_text: int = 1,
                    limit: int | None = None,
                    strict: bool = False) -> tuple[list[dict], int, int]:
    """(claims that hold, how many were dropped, how many rows the answer had).

    THE grounding contract, one copy for reels, articles, pieces and the import
    of answers made outside the pipeline: a claim is kept only if its quote
    really appears in `source_text` (folded the same way on both sides). This is
    what makes fabrication structurally impossible rather than merely
    discouraged by the prompt. `limit` caps the claims KEPT, after the check.

    `strict` (the import): an answer with no list of claims at all is an error,
    not an empty list.
    """
    if isinstance(data, list) and data and isinstance(data[0], dict) \
            and "argomenti" in data[0]:
        data = data[0]
    rows = data.get("argomenti") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        if strict:
            raise ValueError("risposta non utilizzabile: manca la lista «argomenti»")
        rows = []
    haystack = _norm(source_text)
    kept: list[dict] = []
    dropped = 0
    for row in rows:
        if not isinstance(row, dict):
            dropped += 1
            continue
        claim = str(row.get("testo") or "").strip()
        quote = str(row.get("citazione") or "").strip()
        if len(claim) < min_text or not claim:
            continue
        needle = _norm(quote)
        if len(needle) < 12 or needle not in haystack:
            dropped += 1
            continue
        kept.append({"testo": claim[:1000], "citazione": quote[:1000]})
    if limit is not None:
        kept = kept[:limit]
    return kept, dropped, len(rows)


def parse_piece(data, piece: str) -> tuple[str, list[dict]]:
    """(notes, verified claims) of one piece's answer. The quotes are checked
    against THIS piece: the model saw only it, so it cannot stitch a quote
    across two."""
    if isinstance(data, list):
        data = next((d for d in data if isinstance(d, dict)), None)
    if not isinstance(data, dict):
        raise ValueError("risposta non utilizzabile: atteso un oggetto JSON")
    words = str(data.get("sintesi") or "").split()
    note = " ".join(words[:NOTE_WORDS * 2])
    claims, dropped, _ = verified_claims(data, piece, limit=CLAIMS_PER_PIECE)
    if dropped:
        logger.info("[whole_text] %d affermazioni scartate (citazione non trovata)",
                    dropped)
    return note, claims


def merge_claims(per_piece: list[list[dict]], cap: int, embed=None) -> list[dict]:
    """Stitch the pieces' claims: no doubles, spread over the whole text, in order.

    1. Doubles out: same quote, same claim, or (with `embed`, a function from a
       list of texts to unit vectors) claims closer than DEDUP_SIMILARITY.
       The first in text order is the one kept.
    2. Chosen in turns — the first of every piece, then the second of every
       piece — until `cap`, so the end of the text is as present as the start.
    3. Returned in text order.
    """
    flat = [(i, j, c) for i, claims in enumerate(per_piece)
            for j, c in enumerate(claims)]
    seen_q, seen_t, keep = set(), set(), []
    for i, j, c in flat:
        q, t = _norm(c["citazione"]), _norm(c["testo"])
        if q in seen_q or t in seen_t:
            continue
        seen_q.add(q)
        seen_t.add(t)
        keep.append((i, j, c))
    if embed is not None and len(keep) > 1:
        try:
            vecs = embed([c["testo"] for _, _, c in keep])
            kept_idx: list[int] = []
            for n in range(len(keep)):
                if all(float(sum(a * b for a, b in zip(vecs[n], vecs[m])))
                       < DEDUP_SIMILARITY for m in kept_idx):
                    kept_idx.append(n)
            keep = [keep[n] for n in kept_idx]
        except Exception as exc:  # noqa: BLE001
            # The near-doubles are a nicety: a model that cannot load must not
            # lose the content. The exact doubles are already out.
            logger.warning("[whole_text] doppie per somiglianza saltate: %r", exc)
    by_piece: dict[int, list[tuple[int, int, dict]]] = {}
    for item in keep:
        by_piece.setdefault(item[0], []).append(item)
    chosen: list[tuple[int, int, dict]] = []
    rnd = 0
    while len(chosen) < cap and any(len(v) > rnd for v in by_piece.values()):
        for i in sorted(by_piece):
            if len(by_piece[i]) > rnd and len(chosen) < cap:
                chosen.append(by_piece[i][rnd])
        rnd += 1
    chosen.sort(key=lambda it: (it[0], it[1]))
    return [c for _, _, c in chosen]


def notes_block(notes: list[str], claims: list[dict], opening: str = "") -> str:
    """The text the final call reads in place of the long text."""
    lines = [f"Pezzo {i} di {len(notes)}: {n or '(nessun appunto)'}"
             for i, n in enumerate(notes, 1)]
    return prompts.WHOLE_NOTES_TEMPLATE.format(
        opening=(prompts.WHOLE_OPENING_TEMPLATE.format(opening=opening)
                 if opening else ""),
        notes="\n".join(lines),
        claims="\n".join(f"- {c['testo']}" for c in claims) or "(nessuna)")


def read_whole(text: str, what: str, ask_piece, ask_final, *, opening: str = "",
               embed=None):
    """Read a long text in pieces. Returns (the final answer, the claims).

    `ask_piece(user_prompt)` and `ask_final(notes_block)` make the calls and
    return the parsed JSON. Anything they raise is a failure of the content
    (`WholeTextError`, naming the piece) EXCEPT NOT_THE_ITEMS_FAULT, which
    passes through: that is the model, not the content.
    """
    pieces = split_text(text)
    n = len(pieces)
    if n > MAX_PIECES:
        raise WholeTextError(
            f"testo troppo lungo: {len(text)} caratteri sono {n} pezzi, il "
            f"massimo è {MAX_PIECES}")
    notes, per_piece = [], []
    for i, piece in enumerate(pieces, 1):
        user = prompts.PIECE_USER_TEMPLATE.format(
            n=i, total=n, what=what, text=piece)
        try:
            note, claims = parse_piece(ask_piece(user), piece)
        except NOT_THE_ITEMS_FAULT:
            raise
        except Exception as exc:  # noqa: BLE001
            raise WholeTextError(f"pezzo {i} di {n}: {exc!r}") from exc
        notes.append(note)
        per_piece.append(claims)
    claims = merge_claims(per_piece, CLAIMS_LONG, embed)
    try:
        final = ask_final(notes_block(notes, claims, opening))
    except NOT_THE_ITEMS_FAULT:
        raise
    except Exception as exc:  # noqa: BLE001
        raise WholeTextError(f"riassunto finale: {exc!r}") from exc
    return final, claims
