# Low-level: LLM, speech-to-text, embeddings, and RAG

Which models the platform uses, how it picks them, and how search actually ranks results.

## The model the platform runs on

The code is **vendor-neutral on purpose**. Nothing in the source names an LLM vendor. Code
asks for a *tier* and the concrete model id comes from config (`BEC/config/settings/base.py`,
overridable in `BEC/.env`). Swapping providers is an env change, not a code change.

**Since 2026-11-15 the chain has two links and nothing else: Groq, then the local model.**
Anthropic (the paid key, rejected with 401 since early October), the `aiapiflow` reseller
(balance exhausted, and it resold Claude access) and HuggingFace (dormant) are gone from the
code, the settings, `.env.example` and `requirements.txt` (`anthropic` and its Batch API stage
with them). The decision is Giuseppe's: «o Groq o chiamate al modello locale, punto».

### `model_for(task)` — the three tiers

Defined in `BEC/llm/client.py`. Callers ask for a task, not a model:

| Tier call | Used for |
|---|---|
| `model_for("analysis")` | the *strongest* model: reading transcripts, extracting claims/themes, naming clusters |
| `model_for("reasoning")` | strategy briefs, blog drafts, editorial plan |
| `model_for("bulk")` | high-volume mechanical extraction, the **search reranker** (Groq only), blog URL-pattern classification |

It returns the tier's model **on the first live provider**. Callers pass that string back as
`chat(model=...)`; `chat()` re-resolves it per provider via `_task_of()` as it walks the chain,
so a caller never needs to know who will answer — and provider #2 is never asked for provider
#1's model name, which it would 404 on.

### The provider chain (ordered, one entry per provider)

`LLM_PROVIDER_ORDER` (default `fast,ollama`) picks the *kinds* of provider; `LLM_ENDPOINTS`
lists the remote ones **in priority order**, each with its own url, key and models:

```
LLM_ENDPOINTS=groq
LLM_GROQ_BASE_URL / _API_KEY / _MODEL_ANALYSIS / _MODEL_REASONING / _MODEL_BULK
LLM_GROQ_MODEL_CHAIN     (same-provider fallbacks for daily caps)
```

A `.env` written before the chain existed still works: with `LLM_ENDPOINTS` unset, one endpoint
is built from the old `LLM_*` / `FAST_LLM_*` names.

**One dialect.** Every remote provider speaks OpenAI's shape (`POST /chat/completions`,
`Authorization: Bearer`) and goes through `_fast_chat`. There is no `dialect` field any more: it
existed only for Anthropic's own API (`/v1/messages`, `x-api-key`), which is gone.

- **fast** — every entry of `FAST_ENDPOINTS`, in order (Groq).
- **ollama** — local, the last resort. Serialized by a file lock (`_ollama_slot`) because the
  CPU fits one ~7B generation at a time; an interactive caller can claim `priority`.
  The number of threads is `OLLAMA_NUM_THREAD` (default 6, sent as `options.num_thread` by
  `_ollama_chat`; `0` = do not send it). Ollama's own default is all 18 cores, and on this VDS
  (EPYC Zen 1, KVM) the ceiling is memory, not cores. Measured with qwen2.5 7b Q4_K_M:
  18 threads 0.2-0.8 tok/s, 12 threads 1.4-1.9, **6 threads 3.8-4.0**, 4 threads 2.9-3.2.

Errors, and what each one does to the chain:

| Response | Exception | Effect |
|---|---|---|
| 429, per minute | `LLMRateLimit` | **waited out, up to `LLM_RATE_WAITS` (6) times**, each as long as `retry-after` says (1-60 s; Groq said 1-21 s on 2026-11-15), and only then the next link. `retries=0` means «fail fast»: no waiting (the search reranker) |
| 429, per day | `LLMRateLimit(daily=True)` | not waited for (it will not refill): walks that provider's own `_MODEL_CHAIN` — free tiers cap tokens per model per day, so a sibling model still has budget — then the local model |
| 401 / 402 / 403 | `LLMCreditError` | that endpoint is **skipped for `LLM_RETRY_DISABLED_AFTER` (600 s), then tried again** (the MCP connector is a long process: one passing 403 must not switch its reranker off until a restart); the next link answers meanwhile. It is **said**, not only logged: the running stage's note reads «Groq non risponde: chiave rifiutata; il lavoro va sul modello locale» (`client.remote_problem()`), on Avanzamento |
| 404 | `LLMModelMissing` | the provider is fine, the model name is not on it: move to the next endpoint **without** disabling this one |
| anything else | logged at WARNING, retried (`retries`, backoff 1-2 s), then next endpoint | a misconfigured provider must never fail silently |
| local answer cut (token ceiling or time ceiling) | `LLMTruncated` | **an error, not a half string**; **not retried**; the call row is `failed` + `truncated` |
| local slot taken, wait ran out | `LLMBusy` (a `LLMLocalUnavailable`) | **not retried** (it used to be, up to 3 × 900 s = 45 min before failing); does not use the round's allowance |
| Ollama not reachable (stopped, restarting) | `LLMLocalUnavailable` | not retried; no allowance used. **Not the content's fault**: with the budget error it is in `NOT_THE_ITEMS_FAULT`, and the stage leaves the item `pending` |
| Groq answer cut (`finish_reason: length`) | `LLMTruncated` | **raised at once** (not sent to the 7b, which would be cut at the same place minutes later); row `failed` + `truncated`; the job says «Riprova: la risposta del modello è stata tagliata…». A free text (strategy, drafts) is never handed over half written |
| round used its local calls | `LLMLocalBudget` | not retried; reaches the stage as itself — see below |
| `remote_only` and no remote link answered | `LLMRemoteUnavailable` | the caller decides (plain order / «Riprova più tardi»); the local model is never asked |

> **Why per-endpoint and not global.** Until 2026-09-13 one flag disabled the whole remote
> layer, so a single dead gateway dropped everything to the local 3B model — silently. Measured
> damage: of 1066 enrichments, 947 were done by `claude-opus-5` and **61 by `ollama:qwen2.5:3b`**
> after the gateway's balance ran out, with 164 more left `failed`. `Enrichment.llm_model` records
> the model that *actually* served (`last_model_used()`), which is the only way that was visible.

### Deployed configuration (2026-11-15)

| Priority | Provider | Analysis / Reasoning | Bulk | Notes |
|---|---|---|---|---|
| 1 | **Groq** (`api.groq.com/openai/v1`) | `openai/gpt-oss-120b` | `openai/gpt-oss-20b` | free, no card; **caps tokens per minute (public: 8,000 for the 120b) and per day (200,000)**; ~0.4s per call |
| 2 | **Ollama** (local) | `qwen2.5:7b-instruct-q4_K_M` | same | backstop. Apache 2.0, 4.7 GB. The old 3b is **not** usable for a client: its licence is "Qwen Research", non-commercial |

Known limits, measured rather than assumed:

- **Local Ollama is slow by hardware.** The machine tops out at ~5.6-7 tok/s in total for the 7b,
  even with answers in parallel; reading the prompt runs at 9-13 tok/s. Bigger memory pages and
  passive waiting were tried and gave nothing. The 3b model has not been re-measured at 6 threads.

- Groq retired `llama-3.3-70b-versatile` and `llama-3.1-8b-instant`; both 404 on this account.
  Live catalogue: `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`,
  `qwen/qwen3.6-27b`, `groq/compound`, `groq/compound-mini`, `whisper-large-v3`.
- **gpt-oss models emit reasoning tokens before the answer**, billed against `max_tokens`. One
  enrichment prompt: 406 completion tokens at default effort, 263 at `reasoning_effort: low`,
  identical JSON quality. At `max_tokens=20` the answer came back **empty** with
  `finish_reason: "stop"` — a silent failure. `_fast_chat` sets `reasoning_effort: low` on any
  `gpt-oss` model.
- Groq's free tier caps requests per day per model (order of 250-1,000; read the live figure in
  console.groq.com → Settings → Limits). That is what `_MODEL_CHAIN` is for.
- **Every call is now recorded** (since 2026-11-13) in `llm_calls` — see
  [«What is recorded for each call»](#what-is-recorded-for-each-call). Money is still read on
  the provider's own dashboard; what the table gives is calls, tokens and **seconds per process**.

### The local backstop: qwen2.5 7b (2026-11-15)

Groq is first, the local model second, and it is **slow**. Numbers (speeds measured on this VDS
with the old 3b's real token counts; **the 7b times below are calculated, not timed on analysis
prompts** — the first real round replaces them with `llm_calls` data):

| | Reads | Writes | Total |
|---|---|---|---|
| average call (1,507 prompt + 389 answer tokens) | 112 s | 139 s | **~251 s** |
| longest seen on 2026-11-15 (1,180 answer tokens) | 112 s | 421 s | **~533 s** |
| first call, model to load | | | **+96-123 s** |

(7b: reads 13.4 tok/s, writes 2.8. The 3b took 97 s on average; the 7b is ~2.6× slower. It is the
model because it is already on the machine and **Apache 2.0**; the 3b is "Qwen Research", non-commercial.)

One real check of the code path (2026-11-15, `client.chat_json` with the 7b, a synthetic reel
prompt, a scratch database): 905 prompt + 174 answer tokens in **145 s** — model load 38 s, reading
55 s (16.5 tok/s), writing 52 s (3.3 tok/s), JSON complete, nothing cut. The same prompt on Groq
`gpt-oss-120b`: 1.1 s (912 + 378 tokens). One sample, not a benchmark.

What that forces, all in `llm/client.py` and `config/settings/base.py`:

| Setting | Default | Why |
|---|---|---|
| `OLLAMA_NUM_CTX` | 8192 | Ollama opened the model with a 4096 window; an analysis asks for up to 1,836 in + 2,000 out. 5.5 GB of the 82 free |
| `OLLAMA_KEEP_ALIVE` | `30m` | the default unloads after 5 min; a reload is 96-123 s |
| `OLLAMA_READ_TIMEOUT` | 600 s | silence allowed before the first token (load + reading the prompt >200 s; it was 120) |
| `OLLAMA_PIPELINE_TIMEOUT` | 1500 s | ceiling of one local answer when the caller gave none (533 s writing + 123 s load, with room). It used to be 240: an average answer needs 251 |
| `PIPELINE_LOCAL_MAX_CALLS` | **0** (was 40) | `0` = no cap: with Groq out the work queues on the local model. A number above 0 brings the brake back (40 ≈ 2.8 h per round). Price of no cap: a big round can last ~9 h and the 14:15 round skips on the round lock |
| `OLLAMA_LOCK_WAIT` | **1800 s** (was 900) | how long a caller waits its turn for the local slot; it must outlast `OLLAMA_PIPELINE_TIMEOUT` (1500 s) or a caller gives up while the queue is healthy |
| `LLM_RATE_WAITS` | 6 | waits on Groq's per-minute cap before going local |
| `LLM_RETRY_DISABLED_AFTER` | 600 s | a refused key is tried again after this long |
| `ENRICH_WORKERS` | **1** (was 5) | the limit is Groq's per-minute token cap, not the thread count: five threads retrying together pushed 169 of 287 Groq calls into a refusal on 2026-11-15 |

Callers with their own ceilings (second round, after the test: on `gpt-oss-120b` the reasoning tokens
count against `max_tokens`, and strategy brief, strategy draft and blog draft came back **cut
mid-sentence 3 times out of 3**): strategy brief 900→**1800** tokens, strategy draft 1200→**2400**,
blog interview 1600→**3200**, expand 1200→**2400**, draft 1400→**2800**; time ceilings 1800 s for those
and 900 s for ideation (was 600) and the editorial plan (Groq only). Real check on Groq, 2026-11-15:
brief 834 tokens used of 1800, strategy draft 1429 of 2400 (it would have been cut at the old 1200),
blog draft 672 of 2800, all `finish_reason` ≠ `length`.

**Work that never goes local** (`chat(..., remote_only=True)`): the editorial plan (3,600 tokens ≈
21 min + reading, against a 15 min ceiling, and a JSON that long breaks easily on a 7b), the MCP
search reranker (≈ 1m45 on the 7b, queued behind the pipeline for up to 15 min: the client would
see a frozen search) and `eval_mcp`'s judge (4,000 tokens). If Groq refuses: the plan job says
«Il servizio dei modelli ha raggiunto il suo limite in questo momento. Riprova più tardi.», the
search answers at once with the plain order, the eval prints no judge score.

**The cap of local calls is off by default (`PIPELINE_LOCAL_MAX_CALLS=0`, since 2026-11-15): when Groq cannot answer, the work goes on the local model and queues there, one call at a time.** Known limit: with Groq out a big round on the 7b can last hours (141 calls × ~4 min ≈ 9 h); the 14:15 round finds the round lock taken and skips (exit code 3), so rounds never overlap. The rest of this paragraph describes the brake, which only acts if someone sets a number above 0. It leaves work `pending`, never `failed`. `chat()` counts local calls made
by a *pipeline* process (`process` starts with `pipeline:`; a Job the client started is never
capped: a person is waiting). When the round has used them, `LLMLocalBudget` reaches the stage
(`enrich`, `knowledge`): it stops, leaves what it did not try `pending`, writes a note on the
stage («Fermato: usate le N chiamate al modello locale del giro. N restano in attesa per il giro
dopo.», shown on the Avanzamento card and in the log) and returns `deferred` / `stopped`. Real errors
stay `failed`. `DAG.run` zeroes the counter at the start of each round. `cluster` naming that hits
the cap simply gets no name from the model (it already falls back).

**One round at a time.** `DAG.run` holds a file lock (`PIPELINE_LOCK_PATH`, `flock`, gone with the
process) for the whole round, so cron-vs-cron (03:30 still working at 14:15) and cron-vs-«Aggiorna
ora» cannot overlap. The loser writes «un altro giro sta già lavorando: questo non parte» in the log
and exits with code 3 (`ROUND_BUSY`); a manual job fails with «Un altro aggiornamento sta già
lavorando. Riprova quando ha finito.».

Expected hours of local work per round with the 7b (estimates: tokens measured, speed from one
test, on a machine whose speed varies by up to 70%):

| Round | Calls, tokens | Groq refusing like on 15/11 (no change) | With one thread + waiting | Groq off entirely |
|---|---|---|---|---|
| typical: 8 reels + 11 articles | 38, ~62,000 | 0-0.5 h | **0 h** | 2.7 h |
| large: 10 reels + 54 articles | 141, ~230,000 | **1.6 h** | **0-1.3 h** | 9.2 h, stopped at 2.8 h by the cap |

Known limits (written the moment they were known):
- **Groq's free tier is the whole first link.** Public limit for `gpt-oss-120b`: 8,000 tokens/min,
  200,000/day (the limit of *our* account was not verified; it is read only in the Groq console).
  A large round used 170,240 tokens on 15/11, 85% of a day: the 14:15 round and the buttons find
  little. Groq can change limits or retire a model without notice (it did twice).
- **The editorial plan and the search reranker have no backstop** (by design, above).
- **The 7b's quality on these prompts is not proven.** The 3b's three-content test gave more generic
  themes and invented quotes; the quote check drops invented quotes, generic themes pass. Groq's
  `gpt-oss-120b` has never written strategy, plan or drafts for this project (the last ones, in
  July-August, came from Claude through the removed reseller): read one of each.
- **Waiting on Groq has no overall ceiling**: up to 6 waits × 60 s = 360 s per call, about 1,080 s
  when the daily cap walks the sibling models; a «request too large for the minute» 429 wastes all
  six waits. Acceptable for a night round, not measured for a job a person is waiting for.
- **The local model slows down a lot if another program shares the machine** (2026-11-15: a
  service at 226% CPU, Ollama restarted by itself, 342 s for one call against 99-163 s): the cap of
  40 local calls is **1.1-3.8 hours**, not a fixed 2.8.
- **Texts written by a model must be re-read by a person** (strategy brief and draft, blog drafts,
  editorial plan). Drafts can contain **dosages and medical statements**; no check verifies them.
  The 7b also garbles terms (a reel's «brain fog» became «fuga del cervello»): its themes and
  analyses are to be looked at.
- `LLM_ENDPOINTS` accepts only the names the code knows (`groq`). Any other (`anthropic`, `flow`,
  `hf`…) is **ignored with one warning at startup and no request is ever made**, so a key left in an
  old `.env` cannot leave the machine.
- The search reranker waits **10 s at most** for Groq (`knowledge.RERANK_TIMEOUT`), then answers in
  plain order.
### What is recorded for each call

`llm/usage.py`, hooked in `chat()` (`llm/client.py`) — the one place all 16 callers pass
through, so none of them changed. Numbers and short labels only: **no prompt, no answer**.

- **Local model (Ollama).** The row is born `waiting` **before** the lock, goes `running` as
  the lock is taken (`wait_seconds`), counts tokens live (one stream chunk per token, written at
  most every 2 s), and closes with Ollama's own last line: `prompt_eval_count`, `eval_count`,
  `load/prompt_eval/eval_duration` (nanoseconds). `done_reason == "length"` or a timeout that
  returns partial text (`_ollama_chat` returns what it has, without an error) → `truncated`.
  "No free slot after 900 s" → `failed`.
- **Remote models** (`_fast_chat`): a row at the start and one
  update at the end, with the token counts the provider reports (`usage`; if absent the tokens
  stay empty and the row is still written). No live tokens: they answer all at once.
- **Whisper** (`transcriber_agent._transcribe`) is not a `chat()` call, but takes the same
  machine: `usage.stt()` records it (`kind='stt'`) so its hours enter the daily totals.
- **Who asked**: `usage.scope(process, stage, job_id, run_id)` — set by `DAG.run`
  (`pipeline:<stage>`), `run_job` (`job:<kind>`) and the reranker (`mcp:cerca`, only when
  nothing else labels it). Rows older than 2026-11-15 may carry `web:chat`; the page labels
  them «Chat sui contenuti (funzione tolta)». Without a scope: `cmd:<command>` or
  `altro`. The label lives in a contextvar **and** a process-wide fallback set from the main
  thread, because a contextvar does not cross into a `ThreadPoolExecutor` (`enrich` uses 5
  threads); the fallback is not set from web request threads (it would leak between requests).
- **Recording never breaks a call.** Every write is in a savepoint and wrapped: on any error a
  warning is logged and the call goes on; a database error also trips a 30 s breaker so a dead
  database does not add a connection timeout to every model call.
- Machine hours = seconds the local model held the lock + local transcription; **not**
  multiplied by the 18 cores (one generation uses the whole machine; measured 2026-11-13, see
  the decision log in `.claude/tasks/2026-11-13-processi-locali.md`).

Measured on this VDS before the thread fix (kept because the page's first job is to show it):
qwen2.5 7b Q4_K_M at 18 threads 0.2-0.8 tok/s, at 6 threads 3.8-4.0 tok/s; the memory bus, not
the cores, is the ceiling. Ollama loads the model with a 4096-token window (`/api/ps`,
`client.py` does not set `num_ctx`): a longer prompt is cut silently. Not changed here.

### Token ceilings (and the Batch API, removed)

The nightly analysis used to go through Anthropic's Batch API (half price, answers within 24h,
stage `batch`, table `batch_runs`, `manage.py sonnet_batch`). **Removed 2026-11-15**: the stage had
delivered nothing since 2026-10-03 (key rejected), zero rows were left in `batched`, and the
client wants no Anthropic call at all. The 26 receipts are exported to a file at release, before the
migration (`0027`) drops the table (the command is in the task file, «da fare in produzione»); which model analysed what is already in
`enrichments.llm_model` (947 Opus 5, 406 Sonnet 5, 138 gpt-oss-120b at the time).

**Token ceilings are a correctness issue, not a cost knob.** A truncated answer is unparseable
JSON — a *lost* analysis, not a shorter one. Measured on the 2026-09-13 backlog run (Sonnet 5):
at `max_tokens=700`, 6 of ~150 enrichment answers truncated; at 1200, 2 more still did; claim
extraction at 600 lost **74 of 139**. Current values: `ENRICH_MAX_TOKENS = 2000`, claim
extraction 1200.

The model also occasionally wraps the object in an array (`[{...}]`) — 10 of ~150 answers.
`write_enrichment` unwraps a single-element list rather than throwing away an answer.

**Re-embed after a re-analysis.** A document's vector is built from its title, summary and
topics as well as its body, so rewriting an analysis leaves the old vector in place and the
document keeps being found by the wrong questions. `embed_status` says `done`, so nothing
revisits it on its own — set it back to `pending` for the rows you re-analysed. This bit the 323
articles recovered on 2026-09-13: their summaries had been empty when they were first embedded.

## What the document analysis reads, and what it calls the text (2026-11-16)

`knowledge_agent.build_doc_enrich_prompt` reads **the first 6 000 characters** of a text for the
summary and the topic, and **the first 8 000** for the claims (`DOC_SUMMARY_CHARS_READ`,
`DOC_CLAIMS_CHARS_READ`); the reel analysis reads **3 000** (`enrich_agent.TRANSCRIPT_CHARS_READ`).
Measured the same day: 854 of 2 302 articles and 17 of 18 episodes/interviews are longer than
6 000, so the summary of a 17 000-character episode is made on its first third. Known limit, not
changed here: reading everything means summarising in pieces and stitching (Groq allows 8 000
tokens a minute, so a long text does not fit one call). The connector tells the client's Claude
(`nota_analisi`, see `04-mcp-connector.md`). Also read only at the start: the article draft from an
interview (12 000), the article/reel comparison (4 000), the document vector (4 000, softened by
the passage vectors that cover the whole text).

The words of the prompt follow `source_type` (`_intro`): a blog or a web page is «un articolo del
blog di …», **to the letter as before** (2 281 analyses did not move; a test pins it); a video is
«la trascrizione di questo video (una puntata o un intervento) di <canale>», an upload «questa
intervista caricata da Medyca», both with «chiamala puntata, video o intervista: mai articolo», and
for reference material «chi parla sono gli ospiti, non Medyca». Cause: the prompt said «articolo del
blog di Medyca» for everything, and a TV episode kept as Medyca's came back as «L'articolo di
Medyca…». `KB_SYSTEM` now also says «trascrizioni di video e interviste» (it changes for blogs too,
by design). Summaries already written are **not** redone: 12 of them still say «articolo».

## Speech-to-text

- **Remote (preferred when `USE_REMOTE_STT`):** `whisper-large-v3` via `transcribe_audio()`,
  configured with `STT_BASE_URL` / `STT_API_KEY`. Deliberately a **separate endpoint** from the
  text LLM so the two can scale and fail independently.
- **Local fallback:** faster-whisper (`WHISPER_MODEL=small`, int8) on CPU.

## Embeddings

- **Model:** `EMBEDDINGS_MODEL = sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
  (a local multilingual MiniLM). Loaded lazily in `core/knowledge.py` (`_get_embedder`) and in
  `cluster_agent._get_embedder`.
- Vectors are **normalized**, so cosine similarity = a dot product.
- **Storage:** JSON columns in Postgres — no pgvector (see
  [01-data-model.md](01-data-model.md#why-embeddings-are-json-not-pgvector)).
- **What text gets embedded for a reel:** `enrichment.summary_it` + `topics` +
  `transcript[:4000]` (`_EMBED_TEXT_CHARS`). The 4000-char cap matters: an earlier version
  read only `transcript[:600]`, which made anything past ~40 seconds invisible to ranking.

## Retrieval / RAG — `core/knowledge.py`

This module powers the MCP `cerca` tools and `GET knowledge/search/`. (It used to power the
in-app chat too, removed 2026-11-15.)

```mermaid
flowchart TD
    Q["query"] --> E["_embed_query()<br/>MiniLM vector"]
    IDX["_load_index(scope)<br/>vectors from Postgres,<br/>cached by _corpus_stamp()"] --> R
    E --> R["_rank()<br/>0.75·cosine + 0.25·lexical"]
    R --> M["merge owned vs competitor<br/>quota: OWNED_SHARE=5/12<br/>floor: RELEVANCE_FLOOR=0.60"]
    M --> P["_best_passage()<br/>pick closest chunk"]
    P --> RR{"rerank?"}
    RR -->|yes| LLM["_rerank()<br/>one JSON call, model_for('bulk')<br/>RERANK_POOL=15, fails safe"]
    RR -->|no| OUT
    LLM --> OUT["ranked hits"]
```

### `semantic_search(query, top_k, scope, rerank)`

1. **Load index** — `_load_index(scope)` reads all vectors from Postgres and caches them in
   `_INDEX_CACHE`, keyed on a cheap `_corpus_stamp()` fingerprint (uses `Max(updated_at)` so
   in-place re-embeds invalidate the cache). Only `is_active=True, is_on_topic=True` documents
   and `enrich_status=DONE` reels with non-empty text are indexed.
   - **`kind` filter (optional).** `kind="reel"` / `"blog"` narrows the index to one content type
     right here, exactly as `only_inspiration` narrows it to reference material. This is what the
     typed MCP tools (`cerca_reel` / `cerca_articoli`) pass. It matters for **latency**: filtering
     the type up front means the pool the rerank pays for is all the right type and of size
     `want=max(top_k, RERANK_POOL)`, instead of over-fetching a mixed pool of `top_k*3=24` and
     discarding most after the LLM ran. Measured, that cut a typed search from 11–14s into the
     `cerca_tutto` regime (~2.6s), and killed the starvation where a minority type post-filtered
     to fewer than `top_k` results. Callers that want both types leave `kind=None`.
2. **Embed the query** — `_embed_query()`.
3. **Hybrid rank** — `_rank()` blends dense and lexical: `0.75 * cosine + 0.25 * lexical_score`.
   The lexical term (`_lexical_score`) is what catches exact drug/brand names like "Bijuva"
   that a fuzzy vector might miss.
4. **Keep the two sides fair** — under `scope="all"`, owned and competitor are ranked
   *separately* then merged with a quota: `OWNED_SHARE = 5/12` and a relevance floor
   `RELEVANCE_FLOOR = 0.60`. This stops the bigger corpus from crowding out Medyca's smaller
   one. Queries that mention "blog"/"articol…" reserve half the slots for articles.
5. **Pick the passage** — `_best_passage()` selects the chunk (from cached `chunk_vectors`)
   closest to the query, so a hit shows the *relevant* passage, not the article's first lines.
6. **Optional rerank** — `_rerank(query, out)` makes **one** structured LLM call
   (`model_for("bulk")`, `max_tokens=2000`, `retries=0`) over a `RERANK_POOL=15` candidate
   pool, asking for a JSON `{"ordine": [...]}` ordering, then returns the top `top_k`. On *any*
   failure it falls back to the blend order — it never errors out. MCP `cerca` calls it with
   `rerank=True`; it is **Groq only** (see below).
   - **Known limit / why `retries=0`:** with a full pool of long snippets Sonnet 5 sometimes
     prefaces the JSON with a line of reasoning and tips over the ceiling (`stop_reason=max_tokens`).
     At the old `max_tokens=1000` this surfaced as an intermittent **~30–40s hang** on MCP search —
     the client saw "search not working" — because a truncation is deterministic yet the default
     `retries=2` retried it 3× with backoff before the fallback ran (2026-09-15). `2000` gives
     headroom (the same real pool reranks in ~2–3s) and `retries=0` makes the rare truncation fall
     back to the blend order in one shot instead of multiplying the latency.

### The chat is gone

`answer()` / `_prepare()` (the grounded RAG chat reply, its prompt, the pasted-page references
read through `core/external_ref.fetch_reference`) and `knowledge/ask/` were **removed
2026-11-15**: the client uses the MCP connector, and with a local fallback a chat answer would
have taken minutes. Nothing was stored by the chat, so no migration. `core/knowledge.py` now has
one job: `semantic_search`.

Next: [the MCP connector](04-mcp-connector.md).
