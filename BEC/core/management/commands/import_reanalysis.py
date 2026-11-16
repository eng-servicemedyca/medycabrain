"""
import_reanalysis
=================
Load analyses and claims that were written OUTSIDE the pipeline — the one-off
redo of the old content on its whole text (2026-11-16, with Claude Haiku from the
owner's subscription; the nightly round stays Groq + the local model, no
Anthropic) — through the SAME parser and the SAME save the pipeline uses.

    python manage.py import_reanalysis /home/medyca-admin/medycabrain-rianalisi
    python manage.py import_reanalysis <cartella> --write
    python manage.py import_reanalysis <cartella> --write --group 1 --limit 20

The folder holds `input/*.jsonl` (one line per call, with the real prompts) and
`output/*.jsonl` (one line per answer):

    {"key": "<article|reel>:<id>:<analysis|claims>", "response": "<raw JSON text>"}

`article` is a KnowledgeDocument (an article, an episode, an interview). The
input is read only for the keys and the `group` it carries; the answers are what
is imported.

What it does, per content (never mixing two: a key names one id):
  * both answers (analysis AND claims) must be valid, or NOTHING is written for
    that content. Valid = the JSON parses (`llm.client.parse_json`), the analysis
    passes `enrichment_fields` / `apply_doc_enrich` and has a summary, and the
    claims pass `whole_text.verified_claims` (every quote verbatim in the real
    text; a claim whose quote is not found is dropped, as in the pipeline; an
    answer whose claims ALL fail is refused);
  * one transaction per content (`save_whole_reel` / `save_whole_doc`: analysis,
    claims, `full_text_status=done`, vector put back in the queue for the
    nightly embed). The old analysis stays whole until then;
  * `--dry-run` (the DEFAULT) validates and counts, writes nothing. Writing needs
    `--write`;
  * idempotent: a content already `full_text_status=done` is not rewritten.
    Contents `failed` for any reason are not touched (a failure is retried on
    purpose, never silently), nor those not yet analysed (the pipeline does them);
  * an article of up to 8 000 characters may come with the analysis only: its
    claims had already been made on the whole text, and stay.

The model is recorded in `Enrichment.llm_model` for reels (`--model`, default
`claude-haiku`). A document has no such column and none was added: the model
goes in the command's output and the log. No row is added to `llm_calls`: no
call went through this server.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.models import DONE, FAILED, KnowledgeDocument, Reel
from llm import client
from pipeline import whole_text

logger = logging.getLogger(__name__)

KINDS = {"article", "reel"}
TASKS = {"analysis", "claims"}
SHOW_REJECTED = 25


def _read_jsonl(folder: Path, bad: Counter) -> list[dict]:
    rows = []
    for path in sorted(folder.glob("*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict) or "key" not in row:
                        raise ValueError
                except ValueError:
                    bad["righe_illeggibili"] += 1
                    continue
                rows.append(row)
    return rows


def _parse_key(key) -> tuple[str, int, str] | None:
    try:
        kind, pk, task = str(key).split(":")
        if kind in KINDS and task in TASKS:
            return kind, int(pk), task
    except ValueError:
        pass
    return None


def doc_group(d: KnowledgeDocument) -> int:
    """1 episodes/videos/interviews, 2 Medyca's articles, 3 competitors' on-topic
    articles, 5 off-topic articles — the groups of the redo (the input files carry
    their own `group`, which wins; this is for a file that does not)."""
    if d.source_type in ("video", "manual") or d.is_inspiration:
        return 1
    if d.owner_type == "owned":
        return 2
    return 3 if d.is_on_topic else 5


class Command(BaseCommand):
    help = ("Import answers written outside the pipeline (one-off redo on the "
            "whole text). Dry run unless --write.")

    def add_arguments(self, parser):
        parser.add_argument("folder", help="Folder with input/ and output/ (*.jsonl).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Validate and count, write nothing (the default).")
        parser.add_argument("--write", action="store_true",
                            help="Really write. Without it nothing is written.")
        parser.add_argument("--group", type=int, action="append", default=[],
                            help="Only this group (1-5); repeatable.")
        parser.add_argument("--limit", type=int, default=0,
                            help="At most this many contents (after the filters).")
        parser.add_argument("--model", default="claude-haiku",
                            help="Name recorded as the model of the analyses.")

    def handle(self, *args, **opts):
        if opts["write"] and opts["dry_run"]:
            raise CommandError("--write e --dry-run insieme non hanno senso")
        write = opts["write"]
        folder = Path(opts["folder"])
        if not (folder / "output").is_dir():
            raise CommandError(f"manca la cartella {folder / 'output'}")
        bad: Counter = Counter()

        # What was asked: the keys (and groups) of the input, if it is there.
        asked: dict[str, int | None] = {}
        if (folder / "input").is_dir():
            for row in _read_jsonl(folder / "input", bad):
                asked[row["key"]] = row.get("group")

        # What came back. A key that comes twice: the later line wins.
        answers: dict[tuple[str, int], dict[str, object]] = {}
        for row in _read_jsonl(folder / "output", bad):
            parsed = _parse_key(row["key"])
            if parsed is None:
                bad["chiavi_non_valide"] += 1
                continue
            kind, pk, task = parsed
            if asked and row["key"] not in asked:
                bad["chiavi_non_nell_input"] += 1
                continue
            answers.setdefault((kind, pk), {})[task] = row.get("response")

        groups_of = {}
        for key, g in asked.items():
            parsed = _parse_key(key)
            if parsed and g is not None:
                groups_of[parsed[:2]] = int(g)

        reels = {r.id: r for r in Reel.objects.filter(
            id__in=[pk for k, pk in answers if k == "reel"], is_active=True)
            .select_related("account", "enrichment", "transcript")}
        docs = {d.id: d for d in KnowledgeDocument.objects.filter(
            id__in=[pk for k, pk in answers if k == "article"], is_active=True)
            .select_related("source")}

        def group_of(kind, pk, obj):
            return groups_of.get((kind, pk)) or (4 if kind == "reel" else doc_group(obj))

        todo = []
        n = Counter(bad)
        for (kind, pk) in sorted(answers):
            obj = (reels if kind == "reel" else docs).get(pk)
            if obj is None:
                n["non_trovati"] += 1
                continue
            g = group_of(kind, pk, obj)
            if opts["group"] and g not in opts["group"]:
                n["fuori_gruppo"] += 1
                continue
            todo.append((g, kind, pk, obj))
        todo.sort(key=lambda t: (t[0], t[1], t[2]))
        if opts["limit"]:
            todo = todo[:opts["limit"]]

        rejected: list[str] = []
        by_group: Counter = Counter()
        for g, kind, pk, obj in todo:
            label = f"{kind}:{pk}"
            skip = self._skip_reason(obj)
            if skip:
                n[skip] += 1
                continue
            try:
                plan = (self._plan_reel if kind == "reel" else self._plan_doc)(
                    obj, answers[(kind, pk)], opts["model"])
            except ValueError as exc:
                n["scartati"] += 1
                rejected.append(f"{label}: {exc}")
                continue
            if plan is None:  # nothing to redo (no spoken content)
                n["senza_testo"] += 1
                continue
            if not write:
                n["validi"] += 1
                by_group[g] += 1
                continue
            try:
                plan()
            except Exception as exc:  # noqa: BLE001
                n["errori_di_scrittura"] += 1
                rejected.append(f"{label}: scrittura fallita: {exc!r}")
                logger.warning("[import_reanalysis] %s: %r", label, exc)
                continue
            n["scritti"] += 1
            by_group[g] += 1

        self._report(opts, write, folder, asked, answers, n, by_group, rejected)

    # ── checks ────────────────────────────────────────────────────────────
    @staticmethod
    def _skip_reason(obj) -> str | None:
        if obj.full_text_status == DONE:
            return "gia_fatti"
        if FAILED in (obj.full_text_status, obj.enrich_status, obj.argument_status):
            return "saltati_failed"
        if obj.enrich_status != DONE:
            return "saltati_non_analizzati"
        return None

    @staticmethod
    def _parse(raw, what: str):
        if isinstance(raw, (dict, list)):
            return raw
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"{what}: risposta vuota")
        try:
            return client.parse_json(raw)
        except ValueError as exc:  # JSONDecodeError is one
            raise ValueError(f"{what}: JSON non valido ({exc})") from exc

    def _plan_reel(self, reel, got, model):
        from pipeline.agents.enrich_agent import (classify_evidence,
                                                  enrichment_fields,
                                                  save_whole_reel)
        evidence, text = classify_evidence(reel)
        if evidence != "transcript":
            return None
        if set(got) != TASKS:
            raise ValueError("manca una delle due risposte (analisi e affermazioni)")
        analysis = self._parse(got["analysis"], "analisi")
        fields = enrichment_fields(analysis, evidence, model)  # ValueError
        if not fields["summary_it"].strip():
            raise ValueError("analisi: riassunto vuoto")
        claims = self._claims(got["claims"], text + " " + (reel.caption or ""),
                              whole_text.claims_limit(text), min_text=8)
        return lambda: save_whole_reel(reel, analysis, evidence, model, claims)

    def _plan_doc(self, doc, got, model):
        from pipeline.agents.knowledge_agent import (DOC_CLAIMS_CHARS_READ,
                                                     apply_doc_enrich,
                                                     save_whole_doc)
        text = doc.content_text or ""
        if not text.strip():
            return None
        if "analysis" not in got:
            raise ValueError("manca la risposta dell'analisi")
        analysis = self._parse(got["analysis"], "analisi")
        apply_doc_enrich(doc, analysis)  # ValueError; on this copy only, no save
        if not doc.summary_it.strip():
            raise ValueError("analisi: riassunto vuoto")
        if "claims" not in got:
            if len(text) > DOC_CLAIMS_CHARS_READ:
                raise ValueError("manca la risposta delle affermazioni")
            # Up to 8 000 characters the claims had been made on the whole text
            # already: they stay, only the analysis is redone.
            return lambda: save_whole_doc(doc, analysis, None)
        claims = self._claims(got["claims"], text, whole_text.claims_limit(text))
        return lambda: save_whole_doc(doc, analysis, claims)

    def _claims(self, raw, text, limit, min_text=1):
        data = self._parse(raw, "affermazioni")
        try:
            claims, dropped, rows = whole_text.verified_claims(
                data, text, min_text=min_text, limit=limit, strict=True)
        except ValueError as exc:
            raise ValueError(f"affermazioni: {exc}") from exc
        if rows and not claims:
            raise ValueError("affermazioni: nessuna citazione trovata nel testo")
        return claims

    # ── report ────────────────────────────────────────────────────────────
    def _report(self, opts, write, folder, asked, answers, n, by_group, rejected):
        out = self.stdout.write
        out(f"{'SCRITTURA' if write else 'PROVA (dry-run): non scrivo niente'} — "
            f"cartella {folder}, modello «{opts['model']}»")
        out(f"contenuti con risposte: {len(answers)}")
        if asked:
            got_keys = {f"{k}:{pk}:{t}" for (k, pk), v in answers.items() for t in v}
            out(f"chiavi nell'input senza risposta: {len(set(asked) - got_keys)}")
        for label, key in (("scritti" if write else "validi", "scritti" if write else "validi"),
                           ("già fatti (full_text_status=done)", "gia_fatti"),
                           ("scartati (risposta non valida)", "scartati"),
                           ("saltati: failed per altri motivi", "saltati_failed"),
                           ("saltati: non ancora analizzati", "saltati_non_analizzati"),
                           ("senza parlato/testo: niente da rifare", "senza_testo"),
                           ("contenuto non trovato o non attivo", "non_trovati"),
                           ("fuori dal gruppo scelto", "fuori_gruppo"),
                           ("errori di scrittura", "errori_di_scrittura"),
                           ("righe illeggibili", "righe_illeggibili"),
                           ("chiavi non valide", "chiavi_non_valide"),
                           ("chiavi non presenti nell'input", "chiavi_non_nell_input")):
            if n[key] or key in ("scritti", "validi", "scartati"):
                out(f"  {label}: {n[key]}")
        if by_group:
            out("  per gruppo: " + ", ".join(f"{g}: {c}" for g, c in sorted(by_group.items())))
        for line in rejected[:SHOW_REJECTED]:
            out(f"  SCARTATO {line}")
        if len(rejected) > SHOW_REJECTED:
            out(f"  … e altri {len(rejected) - SHOW_REJECTED}")
        if write:
            logger.info("[import_reanalysis] %d scritti, modello %s", n["scritti"],
                        opts["model"])
        else:
            out("Per scrivere davvero: aggiungi --write.")
