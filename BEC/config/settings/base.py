"""
config/settings/base.py
=======================
Shared settings for the medycabrain BEC (Instagram Content Intelligence POC).
Environment-specific overrides live in production.py.
"""

import os
import re
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ── Security ───────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-key-change-me")
DEBUG = os.environ.get("DEBUG", "False").lower() == "true"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# ── Installed apps ─────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.admin",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "django_filters",
    # Local
    "core",
]

# ── Middleware ─────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # must be first
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ── Database ───────────────────────────────────────────────────────────────────
_db_url = os.environ.get("DATABASE_URL")
if _db_url:
    _ssl = os.environ.get("DB_SSL_REQUIRE", "false").lower() == "true"
    DATABASES = {"default": dj_database_url.config(conn_max_age=600, ssl_require=_ssl)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "medycabrain"),
            "USER": os.environ.get("DB_USER", "medycabrain_user"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }

# ── Django REST Framework ──────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "config.authentication.SafeTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardPagination",
    "PAGE_SIZE": 24,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "120/min",
    },
}

# ── CORS ───────────────────────────────────────────────────────────────────────
_cors_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_origins.split(",") if o.strip()]

# ── Internationalisation ───────────────────────────────────────────────────────
LANGUAGE_CODE = "it"
TIME_ZONE = "Europe/Rome"
USE_I18N = True
USE_TZ = True

# ── Static / Media ─────────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DATA_UPLOAD_MAX_MEMORY_SIZE = 52428800  # 50 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 52428800

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Project-specific paths ─────────────────────────────────────────────────────
DATA_DIR = BASE_DIR / "data"
IG_SESSION_FILE = os.environ.get("IG_SESSION_FILE", str(DATA_DIR / "ig_session.json"))
RAW_DUMP_DIR = DATA_DIR / "raw"
TMP_DIR = DATA_DIR / "tmp"
# `data/` is gitignored, so on a fresh clone these do not exist and anything
# that opens a temporary file under TMP_DIR dies with FileNotFoundError. On this
# machine they exist by accident of history, which is why the CI was the first
# to see it: the tests that exercise `fetch_audio` failed on the runner while
# passing locally.
RAW_DUMP_DIR.mkdir(parents=True, exist_ok=True)
TMP_DIR.mkdir(parents=True, exist_ok=True)

# ── LLM / Whisper / embeddings ─────────────────────────────────────────────────
# The local backstop: Ollama runs a quantized Qwen2.5-7B (Apache 2.0, zero cost,
# good Italian). The 3B is NOT usable for a client: its licence is non-commercial.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")
# Threads for generation. Ollama defaults to every core (18 here) and on this
# VDS (EPYC Zen 1, KVM) the limit is memory bandwidth, not cores: qwen2.5 7b
# Q4_K_M does 0.2-0.8 tok/s at 18 threads, 1.4-1.9 at 12, 3.8-4.0 at 6, 2.9-3.2
# at 4. 0 = do not send the option (let Ollama decide). Re-measure on new hardware.
OLLAMA_NUM_THREAD = int(os.environ.get("OLLAMA_NUM_THREAD", "6"))
# The 7b is a BACKSTOP and slow here (reads 13 tok/s, writes 2.8: ~250 s for an
# average analysis, ~530 s for the longest seen — calculated 2026-11-15 from the
# measured speeds, not timed on analysis prompts). So:
#  - window: Ollama opened it at 4096 tokens, an analysis needs up to ~3,800;
#    8192 costs 5.5 GB of the 82 free;
#  - keep_alive: a reload costs 96-123 s, the default drops the model after 5 min;
#  - read timeout: silence allowed before the first token (model load + reading
#    the prompt >200 s; it was 120 s);
#  - pipeline timeout: the whole answer (533 s writing + 123 s load, with room).
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_READ_TIMEOUT = int(os.environ.get("OLLAMA_READ_TIMEOUT", "600"))
OLLAMA_PIPELINE_TIMEOUT = int(os.environ.get("OLLAMA_PIPELINE_TIMEOUT", "1500"))
# Local calls one pipeline round may make before the stage stops and leaves the
# rest `pending` (40 x ~4 min = ~2.8 h). 0 = no cap. Without it, a night with
# Groq down would ask for ~9 h and run into the 14:15 round.
PIPELINE_LOCAL_MAX_CALLS = int(os.environ.get("PIPELINE_LOCAL_MAX_CALLS", "40"))
# Groq's per-minute cap is waited out this many times (each as long as Groq says,
# 21 s at most on 2026-11-15) before the local model is asked.
LLM_RATE_WAITS = int(os.environ.get("LLM_RATE_WAITS", "6"))
# One pipeline round at a time, across cron and "Aggiorna ora".
PIPELINE_LOCK_PATH = os.environ.get("PIPELINE_LOCK_PATH", "/tmp/medycabrain-pipeline.lock")
# Fast remote provider (OpenAI-compatible): Groq / Cerebras / OpenRouter /
# DeepSeek / Together. ~100-300 tok/s vs ~1-3 tok/s for a 7B on this CPU, so
# it is tried FIRST whenever a key is present. Ollama stays as the offline
# backstop. Set FAST_LLM_API_KEY in .env to activate.
# The LLM layer speaks one dialect, OpenAI-compatible (Groq today). Nothing
# below names a vendor — swapping provider is a config change, never a code
# change. Anthropic and the reseller gateway were removed 2026-11-15.
#
# Two models, because the two workloads have opposite needs:
#   BULK      hundreds of structured-extraction calls; cheap and fast wins
#   REASONING a handful of strategy briefs a day; quality wins
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL_BULK = os.environ.get("LLM_MODEL_BULK", "")
LLM_MODEL_REASONING = os.environ.get("LLM_MODEL_REASONING", "")
# The deep-reasoning layer. Whisper produces the transcript; THIS model has to
# read it well — what the reel actually claims, its specific subject, and how
# those claims group into themes. Cheap models fit the JSON shape but flatten
# the meaning, which is what produced "menopausa" on half the corpus.
LLM_MODEL_REASONING_2 = os.environ.get("LLM_MODEL_REASONING_2", "")
LLM_MODEL_REASONING_3 = os.environ.get("LLM_MODEL_REASONING_3", "")

FAST_LLM_API_KEY = LLM_API_KEY or os.environ.get("FAST_LLM_API_KEY", "")
FAST_LLM_BASE_URL = LLM_BASE_URL or os.environ.get("FAST_LLM_BASE_URL", "https://api.groq.com/openai/v1")
FAST_LLM_MODEL = LLM_MODEL_REASONING or os.environ.get("FAST_LLM_MODEL", "llama-3.3-70b-versatile")
# Bulk extraction (enrichment, arguments) runs hundreds of calls and would
# exhaust the big model's daily token budget in one night. A small model is
# both adequate for structured extraction and has its own, larger budget.
FAST_LLM_MODEL_BULK = LLM_MODEL_BULK or os.environ.get("FAST_LLM_MODEL_BULK", "llama-3.1-8b-instant")
# Free tiers cap tokens PER MODEL PER DAY. Reprocessing the whole corpus needs
# more than any single model's budget, so bulk work walks down this chain:
# when one model's daily budget is gone we move to the next model's own budget.
FAST_LLM_MODEL_CHAIN = [
    m.strip() for m in os.environ.get(
        "FAST_LLM_MODEL_CHAIN",
        "" if LLM_BASE_URL else
        "llama-3.3-70b-versatile,openai/gpt-oss-120b,qwen/qwen3.6-27b,llama-3.1-8b-instant",
    ).split(",") if m.strip()
]
# Audio transcription (whisper-large-v3 on the fast provider): far better on
# medical Italian than the local `small` model, and it costs the VPS nothing.
FAST_STT_MODEL = os.environ.get("FAST_STT_MODEL", "whisper-large-v3")
USE_REMOTE_STT = os.environ.get("USE_REMOTE_STT", "1") == "1"
# Transcription keeps its own endpoint, deliberately not LLM_BASE_URL: a text
# gateway need not expose /audio/transcriptions, and when it does not, every
# request 404s and silently falls back to the local `small` model — which
# mangles the vocabulary this pipeline exists to read ("umonibirentici" for
# "ormoni bioidentici"). That happened for 37 of 37 transcriptions on
# 2026-07-27, so the two providers are now configured separately.
STT_BASE_URL = os.environ.get("FAST_LLM_BASE_URL", "https://api.groq.com/openai/v1")
STT_API_KEY = os.environ.get("FAST_LLM_API_KEY", "")

# ── The remote-provider chain ───────────────────────────────────────────────
# Several providers in priority order, each with its OWN base url, key
# and model names. Several providers can still be declared (a free tier dies on
# a daily cap or a dead key, and the platform used to drop to the local model
# invisibly: 61 of 1066 enrichments on 2026-09-13), but in production the list
# is just `groq`; the local model is the second link, see llm/client.py.
#
# Declared in .env as:
#     LLM_ENDPOINTS=groq
#     LLM_GROQ_BASE_URL=... _API_KEY=... _MODEL_ANALYSIS=... _MODEL_BULK=...
#     LLM_GROQ_...                _MODEL_CHAIN=...  (same-provider fallbacks)
# Order IS priority. A provider that rejects the key or has no balance is
# skipped for the rest of the process; the next one answers.
def _llm_endpoints() -> list[dict]:
    names = [n.strip() for n in os.environ.get("LLM_ENDPOINTS", "").split(",") if n.strip()]
    out = []
    for name in names:
        p = "LLM_" + re.sub(r"[^A-Z0-9]", "_", name.upper()) + "_"
        url = os.environ.get(p + "BASE_URL", "").strip()
        if not url:
            continue
        bulk = os.environ.get(p + "MODEL_BULK", "").strip()
        reasoning = os.environ.get(p + "MODEL_REASONING", "").strip() or bulk
        analysis = os.environ.get(p + "MODEL_ANALYSIS", "").strip() or reasoning
        chain = [m.strip() for m in os.environ.get(p + "MODEL_CHAIN", "").split(",") if m.strip()]
        out.append({
            "name": name,
            "base_url": url,
            "api_key": os.environ.get(p + "API_KEY", "").strip(),
            "models": {"bulk": bulk, "reasoning": reasoning, "analysis": analysis},
            # Same-provider fallbacks: free tiers cap tokens per model per day,
            # so a sibling model on the same key still has its own budget.
            "chain": chain or list(dict.fromkeys(m for m in (analysis, reasoning, bulk) if m)),
        })
    return out


FAST_ENDPOINTS = _llm_endpoints()
if not FAST_ENDPOINTS and FAST_LLM_API_KEY:
    # Backwards compatibility: a .env written before the chain existed still
    # works, as a single endpoint built from the old variable names.
    FAST_ENDPOINTS = [{
        "name": "fast", "base_url": FAST_LLM_BASE_URL, "api_key": FAST_LLM_API_KEY,
        "models": {"bulk": FAST_LLM_MODEL_BULK, "reasoning": FAST_LLM_MODEL,
                   "analysis": LLM_MODEL_REASONING_3 or LLM_MODEL_REASONING_2
                   or LLM_MODEL_REASONING or FAST_LLM_MODEL},
        "chain": FAST_LLM_MODEL_CHAIN,
    }]

# ── Video presi da un link (YouTube, Vimeo) ────────────────────────────────
# yt-dlp scarica l'audio, ma **nessuno dei due fornitori lo dà in anonimo** da
# questo server: servono i cookie di un browser dove sei loggato, uno per
# fornitore. I file stanno fuori dal repository, in ~/.config/medycabrain/,
# permessi 0600: sono l'accesso a un account, non una chiave API. Senza, il
# link resta salvato come riferimento ma non viene trascritto, e la riga lo
# dice in chiaro.
#
# YouTube: senza cookie risponde "Sign in to confirm you're not a bot" a ogni
# player client (provato il 2026-09-13 su yt-dlp 2026.7.4 e 2026.8.19).
YT_COOKIES_FILE = os.environ.get("YT_COOKIES_FILE", "")
# Vimeo: yt-dlp 2026.08.19 rifiuta **prima ancora di chiamare Vimeo** — nel suo
# sorgente `vimeo.py:391` il client `web` ha `REQUIRES_AUTH: True` — con "The
# web client only works when logged-in". Non è un blocco sul nostro IP e non
# esiste una via anonima (client `android`: vuole token OAuth già in cache;
# `player.vimeo.com/<id>/config`: 401/403 con e senza Referer). Con i cookie
# l'audio si scarica normalmente (verificato il 14/09/2026 sui tre video TVRS).
# Qui NON serve un runtime JavaScript: quella sfida è solo di YouTube.
VIMEO_COOKIES_FILE = os.environ.get("VIMEO_COOKIES_FILE", "")
# Solo YouTube: firma gli indirizzi dei media con una sfida JavaScript. yt-dlp sa
# risolverla ma NON abilita da solo un runtime non sandboxato: va nominato.
# Senza, tornano solo le anteprime e l'errore dice "formato non disponibile",
# che manda a cercare la cosa sbagliata. Serve anche il pacchetto yt-dlp-ejs.
YT_JS_RUNTIME = os.environ.get("YT_JS_RUNTIME", "node")
# Proxy residenziale per i download di YouTube e Vimeo (core/link_ingest.py).
# Da un IP di datacenter YouTube chiede il login a ogni player client (provato
# il 2026-11-12 con 6 client, con e senza Node) e Vimeo risponde 401. Da un IP
# residenziale italiano (IPRoyal) YouTube scarica senza cookie e Vimeo lascia
# passare il player pubblico. `{session}` viene sostituito a ogni download con
# un id nuovo: stesso IP per tutto il download, IP nuovo al tentativo dopo.
# Contiene una password: solo in .env, mai nei log né nei messaggi al cliente.
# Vuoto = niente proxy, si torna ai cookie.
YTDLP_PROXY = os.environ.get("YTDLP_PROXY", "")
# Proxy per leggere gli account Instagram (scraper/embed_provider.py) e, solo se
# Instagram blocca il download diretto, per scaricare un reel. Vuoto = usa
# YTDLP_PROXY: stesso servizio, nessun segreto in più. Stesso avviso: contiene
# una password, mai nei log. Il proxy si paga a gigabyte: ~245 KB per account
# letto, ~13 MB per un video scaricato dal proxy (i video vanno diretti).
IG_PROXY = os.environ.get("IG_PROXY", "")

# DISATTIVATO dal 2026-11-14: la raccolta non chiama più Apify (rispondeva 401
# e prima si fermava per il tetto di spesa). Il codice resta, spento.
# Apify supplies reel metadata and a working CDN video url from its own
# proxied infrastructure, which is what unblocks the download backlog: our own
# calls to Instagram's media/info throttle after ~35 and then answer HTML.
# Billed per result, so callers batch per account — never per reel.
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")

# Instagram Graph API — the official replacement for cookie scraping, which
# was removed 2026-07-29 (it ran as Giuseppe's personal account). The caller
# is a Meta app + an IG BUSINESS account; competitors are read through
# business_discovery. Human setup steps: docs/instagram-graph-api-setup.md.
IG_GRAPH_TOKEN = os.environ.get("IG_GRAPH_TOKEN", "")
IG_GRAPH_USER_ID = os.environ.get("IG_GRAPH_USER_ID", "")
IG_GRAPH_API_VERSION = os.environ.get("IG_GRAPH_API_VERSION", "v21.0")
APIFY_REEL_ACTOR = os.environ.get("APIFY_REEL_ACTOR", "apify~instagram-reel-scraper")

# Serialize local Ollama calls: the CPU fits exactly one 3B/7B generation.
# Concurrent calls (nightly pipeline + a client clicking "Analizza") make
# BOTH time out, which is how the box melted down.
OLLAMA_LOCK_PATH = os.environ.get("OLLAMA_LOCK_PATH", "/tmp/medycabrain-ollama.lock")
OLLAMA_LOCK_WAIT = int(os.environ.get("OLLAMA_LOCK_WAIT", "900"))

# How long the per-call detail (`llm_calls`) and per-stage rows (`stage_runs`)
# are kept. `manage.py prune_llm_calls` deletes older rows; daily totals older
# than this are lost (no summary table in v1).
LLM_CALL_RETENTION_DAYS = int(os.environ.get("LLM_CALL_RETENTION_DAYS", "90"))

LLM_PROVIDER_ORDER = os.environ.get("LLM_PROVIDER_ORDER", "fast,ollama").split(",")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_CPU_THREADS = int(os.environ.get("WHISPER_CPU_THREADS", "4"))
EMBEDDINGS_MODEL = os.environ.get(
    "EMBEDDINGS_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)

# ── Logging ────────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
    },
}
