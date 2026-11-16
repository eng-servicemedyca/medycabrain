# Architecture summary (for a fast start)

A one-page map of the whole system, so an AI session (or a new dev) can get oriented before
touching anything. For depth, follow the links into `documentation/`.

## What this is

Content-intelligence platform for **Medyca** (menopause / bioidentical hormones). It watches
Medyca's Instagram + blog content **and** competitors', understands it, groups it into themes,
and helps decide what to publish next. The one rule that overrides everything: **Medyca's own
content (`owner_type="owned"`) is never mixed with competitors' (`owner_type="competitor"`).**

## Shape

- `BEC/` — Django, **one app `core`** holds all tables (`BEC/core/models.py`). Support
  packages: `pipeline/` (the nightly job), `scraper/` (Instagram), `llm/` (model access),
  `mcp_bridge/` (the Claude connector).
- `FEC/` — React + Vite + TS frontend (token stored as `brain_token`, API base `/api/v1`).
- Live: REST API on `:8010` (Gunicorn), app preview on `:9093`, MCP server on `127.0.0.1:8025`,
  all behind nginx on `messtudent.com`.

## Data model (the DB)

Four inputs → derived layers → themes. See `documentation/low-level/01-data-model.md`.
- **Inputs:** `TrackedAccount`→`Reel`, `BlogSource`→`KnowledgeDocument`, `UploadedMedia`, `CustomTopic`.
- **Reel layers (1:1):** `Transcript`, `Enrichment`, `ReelEmbedding`; plus `ReelArgument` (1:N, verbatim `quote`).
- **Doc layers:** `KnowledgeDocument` (embeddings inline) + `DocumentArgument` (1:N).
- **Themes:** `ClusterRun` (per `scope`, one `is_current`) → `TopicCluster` → `*ClusterAssignment` tables.
- **Vectors are JSON columns** in Postgres — no pgvector; cosine is computed in NumPy.
- `owner_type` on a document is **denormalised and authoritative** — read `doc.owner_type`, never the FK.

## Pipeline

`pipeline/dag.py` (which also owns the stage list, via `build_steps()`), entry
`core/management/commands/run_pipeline.py`, one agent per stage:
`scrape → download → transcribe → enrich → embed → blogscrape → knowledge → cluster`
(eight stages; the old `batch` stage, which handed the analysis to the Anthropic Batch API, was
removed 2026-11-15 — `dag.HISTORY_ORDER` keeps it only to draw old rounds). Models are a
two-link chain: **Groq** (declared in `.env` as `LLM_ENDPOINTS=groq`) and then the **local
Ollama model** as the backstop. No Anthropic, no reseller gateway, no HuggingFace.
**Collection is split in two on purpose** (since 2026-11-14, Apify is off): the server *lists*
an account's reels by reading its public **embed page** through the residential proxy
(`scraper/embed_provider.py`: last 6 posts, only videos the account owns, no views), and yt-dlp
*downloads* each reel anonymously (direct first, proxy only if blocked). No Instagram account of
ours is involved. A run is capped (`embed_max_new_per_run`), and if every account fails the stage
is `failed`. The Apify code stays in the repository, switched off (history in `02-pipeline.md`).
Idempotent via per-row status columns; failures stay `failed` (retry is explicit). Runs nightly
via host cron, **and on demand** — `POST /api/v1/ops/run/` queues a `Job(kind="pipeline")`
(`core/pipeline_run.py`), one run at a time. `core/queue_eta.py` says how much is left and how
long it should take, measured from the recent runs in `logs/pipeline.log`.
See `documentation/low-level/02-pipeline.md`.
**Progress is recorded**: every stage writes `stage_runs` (`core/progress.py`: done/total) and every
model call writes `llm_calls` (`llm/usage.py`, numbers only, never the text); the page «Avanzamento»
(`/avanzamento`, `GET /ops/progress/`) reads them, tqdm style, with who works each item.

## Models

Vendor-neutral. Code asks for a tier via `model_for("analysis"|"reasoning"|"bulk")`
(`llm/client.py`); the actual id is in `.env`. The chain is Groq → local `qwen2.5:7b` (slow: ~4 min per analysis, hence one worker,
Groq's per-minute cap is waited out 6 times before going local, local calls queue with no cap by default (`PIPELINE_LOCAL_MAX_CALLS=0`; a number above 0 brings the brake back and leaves the rest `pending`), one round at a time by file lock: a big round can last hours and the 14:15 one skips). `chat(remote_only=True)` never reaches
the local model: editorial plan, search reranker, `eval_mcp` judge. STT = Whisper large-v3 (remote) / faster-whisper
(local). Embeddings = multilingual MiniLM. RAG (`core/knowledge.py`): `semantic_search` blends
`0.75·cosine + 0.25·lexical`, keeps owned/competitor quotas, optional LLM reranker. The engine
powers MCP `cerca` (the in-app chat was removed 2026-11-15); its reranker is Groq-only, and when
Groq refuses the search answers at once with the plain order. See `documentation/low-level/03-llm-and-embeddings.md`.

## MCP connector

Standalone ASGI server `BEC/mcp_bridge/server.py` (systemd `medycabrain-mcp`, uvicorn `:8025`).
`django.setup()` in-process → queries Postgres via ORM. Ten read-only tools:
- `panoramica()` — ORM counts. `temi(scope)` — cluster tables. `leggi_reel` / `leggi_articolo` /
  `leggi("reel:ID"|"blog:ID", parte=1)` — direct ORM lookup; text up to 30 000 characters per answer,
  longer texts in parts (`parte`, `troncato`). `cerca_reel` / `cerca_articoli` / `cerca_tutto` /
  `cerca_riferimenti` — `core.knowledge.semantic_search(rerank=True)`. `fonti_blog` — the blogs.
- Whole text read (16/11/2026): up to 8 000 chars in two calls, above in ~6 000-char pieces (`pipeline/whole_text.py`), up to 12 claims. `full_text_status` says whether an analysis read everything; old ones (cut at 6 000 / 8 000 / 3 000) show `nota_analisi` until redone (`import_reanalysis`).
- Auth = secret path segment (`MCP_SECRET`); URL is the credential. See
  `documentation/low-level/04-mcp-connector.md`.

## When you change something

**`main` is never written to directly.** Every change goes: branch → commit → push → pull
request, and Giuseppe merges after reading the diff. Rule: `.claude/rules/git-flow.md`.

The work is done by a **team of agents**, hub and spoke: the main session becomes the team
lead via the `medyca-capo` skill, and launches five spokes in `.claude/agents/` —
`medyca-architetto` (designs, stops for approval) → `medyca-sviluppatore` (writes) →
`medyca-revisore` + `medyca-collaudatore` (in parallel: one reads, one executes) →
`medyca-rilasciatore` (deploys, asking before each step). They cannot talk to each other:
the shared task file in `.claude/tasks/` is the only channel. Start one with `/feature`,
see the board with `/bacheca`. Full description: `documentation/low-level/08-agent-team.md`.

Two required CI jobs guard the PR (`.github/workflows/ci.yml`): Django checks + migration
drift + tests on the light `BEC/requirements-ci.txt`, and the frontend build (which is also
the type check).

Read `.claude/rules/documentation.md`. Any new feature or structural change updates the
matching doc **in the same commit** — the `documentation/` folder, the in-app Documentazione
page, and the drawio diagram as applicable.
