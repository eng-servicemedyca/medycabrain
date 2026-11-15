"""
llm/client.py
=============
LLM access with a two-link chain: the remote provider (Groq, any
OpenAI-compatible endpoint declared in `LLM_ENDPOINTS`) first, then the local
Ollama model as the backstop. Nothing else is in the chain: no Anthropic, no
reseller gateway, no HuggingFace (removed 2026-11-15 — the paid ones had been
failing for weeks, and the client wants "Groq or local, full stop").

Ollama is pinned to OLLAMA_NUM_THREAD threads (default 6): on this VDS more
threads make generation slower, not faster (3.8-4.0 tok/s at 6, 0.2-0.8 at 18).

The local model is a BACKSTOP, and it is slow: qwen2.5 7b reads 13 tok/s and
writes 2.8, so an average analysis (1,500 in, 400 out) takes ~250 s and the
longest seen ~530 s (calculated 2026-11-15 from the measured speeds; the 3b the
numbers came from is not usable commercially). What that implies, all below:

  * Groq's per-minute cap is WAITED OUT (up to LLM_RATE_WAITS times, each as long
    as Groq says, 21 s at most on 2026-11-15) instead of falling to the local
    model after three refusals. 169 of 287 Groq calls failed that way on
    2026-11-15 and every one was "retry in 1-21 s".
  * The local window is OLLAMA_NUM_CTX (Ollama's own default, 4096, left 260
    tokens of room after an analysis prompt), the model stays loaded
    (OLLAMA_KEEP_ALIVE: reloading costs 96-123 s), silence is allowed for
    OLLAMA_READ_TIMEOUT (reading the prompt alone is ~112 s, plus a load) and
    the whole answer for OLLAMA_PIPELINE_TIMEOUT.
  * A cut answer is an error with its own name (`LLMTruncated`), never half a
    JSON returned in silence. Neither it nor a busy slot is retried: a retry
    costs another 4-9 minutes (it used to mean up to 45 before failing).
  * A pipeline round may make at most PIPELINE_LOCAL_MAX_CALLS local calls
    (`LLMLocalBudget`); the stage leaves what it did not try `pending`.
  * `remote_only=True` never reaches Ollama (the MCP search reranker, the
    editorial plan, the eval judge): a minute of waiting is worse than an
    answer in plain order, and a 3,600-token plan would take 20+ minutes.

Every attempt is recorded in `llm_calls` by `llm/usage.py` (who asked, which
model, how long it waited for the local lock, tokens, seconds — never the text).
`chat()` is the single place that does it, so the callers are untouched, and a
failing write never fails the call.
"""

from __future__ import annotations

import contextlib
import contextvars
import fcntl
import json
import logging
import os
import re
import threading
import time

import requests
from django.conf import settings

from llm import usage

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

# Which model actually served the last call. Callers record this instead of
# guessing from settings — enrichments used to all claim a model that never
# ran, which made quality regressions impossible to attribute.
_last_model: contextvars.ContextVar[str] = contextvars.ContextVar("last_model", default="")


def last_model_used() -> str:
    return _last_model.get()


class LLMError(Exception):
    pass


class LLMRateLimit(LLMError):
    """Provider is rate-limiting us (429). Carries how long to wait."""

    def __init__(self, retry_after: float, daily: bool = False):
        super().__init__(
            "daily token budget exhausted" if daily
            else f"rate limited, retry in {retry_after:.0f}s")
        self.retry_after = retry_after
        self.daily = daily


class LLMCreditError(LLMError):
    """Provider returned 401/402/403 — bad key or no balance. That endpoint is
    skipped for the rest of the process; the next one in the chain answers."""


class LLMLocalUnavailable(LLMError):
    """The local model cannot be reached at all (Ollama stopped or restarting).
    Nothing is wrong with the content being processed."""


class LLMBusy(LLMLocalUnavailable):
    """The local slot is not free (another generation, or a person has priority)
    and the wait ran out. Retrying only queues again behind the same thing."""


class LLMTruncated(LLMError):
    """The answer was cut — at the token ceiling (local or Groq: finish_reason
    "length") or by the local time ceiling. A cut JSON is a lost analysis, and a
    free text cut mid-sentence must never reach the client as if it were
    finished, so it is an error here and not a string. Not retried: the same
    prompt is cut at the same place."""


class LLMLocalBudget(LLMError):
    """This pipeline round has used its local calls (PIPELINE_LOCAL_MAX_CALLS).
    Not a failure of the item: the stage leaves it `pending` for the next round."""


class LLMRemoteUnavailable(LLMError):
    """`remote_only` call and no remote provider answered (cap, key, network).
    The caller decides what to do — rerank falls back to plain order, the plan
    says «riprova più tardi» — but it never waits for the local model."""


# Not the content's fault: the item stays `pending` and the stage says why. Real
# errors of the content (a broken answer) stay `failed`.
NOT_THE_ITEMS_FAULT = (LLMLocalBudget, LLMLocalUnavailable)


class LLMModelMissing(LLMError):
    """404: this provider does not serve that model name.

    Distinct from a dead key on purpose — the provider is fine, only the name
    is wrong, so we move to the next endpoint WITHOUT disabling this one.
    Groq retiring llama-3.3-70b-versatile is exactly this case."""


# Once a provider reports a bad key / depleted credits, skip it this process.
# Per ENDPOINT, not global: when one gateway runs out of balance the next one
# in the chain must still answer. A single flag here meant a dead gateway took
# the whole remote layer down with it and everything fell to the local model.
# name -> time it was disabled. A key refusal is not forever: the MCP connector
# is a long-lived process and one passing 403 must not switch its reranker off
# until the next restart, so a disabled endpoint is tried again after
# LLM_RETRY_DISABLED_AFTER seconds.
_fast_disabled: dict[str, float] = {}
_problem = {"text": ""}


def remote_problem() -> str:
    """Why a remote provider is switched off right now ("" if none): the
    sentence a stage shows instead of leaving it only in the log."""
    return _problem["text"] if _fast_disabled else ""


def _announce(text: str) -> None:
    """Put the sentence on the running stage's note (no-op outside a stage)."""
    with contextlib.suppress(Exception):
        from core import progress
        progress.note(text)


def _ollama_chat(system: str, user: str, max_tokens: int, temperature: float,
                 json_mode: bool = False, timeout: int | None = None, on_token=None,
                 rec=None) -> str:
    """Local generation. Streams so a slow CPU still shows life: the silence
    allowed between chunks is OLLAMA_READ_TIMEOUT, and `timeout` is the deadline
    for the whole answer. Raises `LLMTruncated` if the answer is cut.

    `rec` is the `usage.Call` of this attempt (optional): it gets the live token
    count and, from Ollama's last line, the real numbers."""
    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "stream": True,
        # num_ctx: Ollama opened this model with 4096 tokens (measured with
        # /api/ps 2026-11-15) and an analysis asks for up to 1,836 in + 2,000 out:
        # it fit by 260 tokens. keep_alive: unloaded after 5 min of silence by
        # default, and a reload costs 96-123 s.
        "options": {"temperature": temperature, "num_predict": max_tokens,
                    "num_ctx": settings.OLLAMA_NUM_CTX},
        "keep_alive": settings.OLLAMA_KEEP_ALIVE,
    }
    if settings.OLLAMA_NUM_THREAD > 0:
        # Ollama's default (all cores) collapses to <1 tok/s on this VDS; see settings.
        payload["options"]["num_thread"] = settings.OLLAMA_NUM_THREAD
    if json_mode:  # only for structured-extraction prompts, not free-text answers
        payload["format"] = "json"
    _last_model.set(f"ollama:{settings.OLLAMA_MODEL}")
    chunks: list[str] = []
    timeout = timeout or settings.OLLAMA_PIPELINE_TIMEOUT
    deadline = time.time() + timeout
    # Silence allowed: loading the model (96-123 s) and reading the prompt
    # (~112 s for a 1,500-token one) both happen before the first token.
    try:
        resp_cm = requests.post(f"{settings.OLLAMA_URL}/api/chat", json=payload,
                                stream=True,
                                timeout=(10, settings.OLLAMA_READ_TIMEOUT))
    except requests.exceptions.ConnectionError as exc:
        # Ollama stopped or restarting (it restarted by itself at 11:43 on
        # 2026-11-15, when another service on the box took the CPU): nothing
        # is wrong with the content, so this is not a failure of the item.
        raise LLMLocalUnavailable(f"Ollama non raggiungibile: {exc.__class__.__name__}") from exc
    with resp_cm as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            piece = (data.get("message") or {}).get("content", "")
            if piece:
                chunks.append(piece)
                if rec is not None:
                    # One chunk per token (43 chunks for 44 tokens, measured
                    # 2026-11-13): counting them is the live token count.
                    rec.tokens(len(chunks))
                if on_token:
                    with contextlib.suppress(Exception):
                        on_token("".join(chunks))
            if data.get("done"):
                if rec is not None:
                    _record_ollama_stats(rec, data)
                if data.get("done_reason") == "length":
                    raise LLMTruncated(
                        f"risposta locale tagliata al tetto di {max_tokens} token")
                if (data.get("prompt_eval_count") or 0) >= settings.OLLAMA_NUM_CTX - 8:
                    # The window is full: Ollama drops the start of the prompt
                    # without a word, so the answer may ignore the instructions.
                    logger.warning("[llm] ollama: prompt of %s tokens fills the %s window",
                                   data.get("prompt_eval_count"), settings.OLLAMA_NUM_CTX)
                break
            if time.time() > deadline:
                if rec is not None:
                    rec.stats(truncated=True, output_tokens=len(chunks))
                raise LLMTruncated(
                    f"risposta locale ancora in corso dopo {timeout} secondi: interrotta")
    return "".join(chunks)


def _record_ollama_stats(rec, data: dict) -> None:
    """Ollama's last line carries the real numbers (durations in nanoseconds)."""
    def secs(key):
        v = data.get(key)
        return round(v / 1e9, 2) if isinstance(v, (int, float)) else None
    rec.stats(prompt_tokens=data.get("prompt_eval_count"),
              output_tokens=data.get("eval_count"),
              load_seconds=secs("load_duration"),
              prompt_seconds=secs("prompt_eval_duration"),
              eval_seconds=secs("eval_duration"),
              # "length" = cut at num_predict (our max_tokens)
              truncated=data.get("done_reason") == "length")


@contextlib.contextmanager
def _ollama_slot(wait: int | None = None, priority: bool = False):
    """Serialize local generations across every process on the box.

    The CPU fits exactly one 3B/7B generation at a time. Two concurrent
    callers (nightly pipeline + a client pressing "Analizza") each run at
    half speed and BOTH hit their read timeout — the failure mode that made
    every job fail while burning 700% CPU. An flock turns that collision
    into a queue.
    """
    wait = wait if wait is not None else settings.OLLAMA_LOCK_WAIT
    path = settings.OLLAMA_LOCK_PATH
    prio_path = path + ".priority"
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o666)
    deadline = time.time() + wait
    prio_fd = None
    try:
        if priority:
            # Announce ourselves so batch work stands aside at its next item.
            prio_fd = os.open(prio_path, os.O_CREAT | os.O_RDWR, 0o666)
            fcntl.flock(prio_fd, fcntl.LOCK_EX)
        else:
            # Batch work: never start a new generation while a human waits.
            while os.path.exists(prio_path) and _prio_held(prio_path):
                if time.time() >= deadline:
                    raise LLMBusy("ollama busy: interactive work has priority")
                time.sleep(2.0)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() >= deadline:
                    raise LLMBusy(f"ollama busy: no free slot after {wait}s")
                time.sleep(1.0)
        yield
    finally:
        with contextlib.suppress(Exception):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        if prio_fd is not None:
            with contextlib.suppress(Exception):
                fcntl.flock(prio_fd, fcntl.LOCK_UN)
            os.close(prio_fd)


def _prio_held(prio_path: str) -> bool:
    """True while some interactive caller actually holds the priority flag
    (a stale file left by a crashed process must not block batch work)."""
    try:
        fd = os.open(prio_path, os.O_RDWR)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


def _fast_chat(system: str, user: str, max_tokens: int, temperature: float,
               json_mode: bool = False, timeout: int = 120, model: str = "",
               endpoint: dict | None = None) -> str:
    """One OpenAI-compatible remote provider (Groq, OpenRouter, a gateway, …).

    Two orders of magnitude faster than local CPU inference, which is what
    makes the Second Brain feel instant instead of frozen. `endpoint` is one
    entry of settings.FAST_ENDPOINTS — url, key and model names travel
    together, so two providers are never mixed up.
    """
    endpoint = endpoint or (settings.FAST_ENDPOINTS[0] if settings.FAST_ENDPOINTS else {})
    base_url = endpoint.get("base_url") or settings.FAST_LLM_BASE_URL
    api_key = endpoint.get("api_key") or settings.FAST_LLM_API_KEY
    payload = {
        "model": model or endpoint.get("models", {}).get("reasoning") or settings.FAST_LLM_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    # gpt-oss models emit REASONING tokens before the answer, billed against
    # max_tokens. Measured 2026-09-13 on one enrichment prompt: 406 completion
    # tokens at the default effort, 263 at "low", same JSON quality. At
    # max_tokens=20 the answer came back EMPTY — the whole budget went to
    # reasoning, with finish_reason still "stop". Silent failure; hence this.
    if "gpt-oss" in payload["model"]:
        payload.setdefault("reasoning_effort", "low")
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
        # OpenAI-compatible endpoints reject json mode outright (400) unless
        # the word "json" appears in the messages. Without this the whole
        # enrichment path silently fell back to local CPU inference.
        if "json" not in f"{system}{user}".lower():
            payload["messages"][0]["content"] = (
                system + "\n\nRispondi esclusivamente con un oggetto JSON valido.")
    _last_model.set(payload["model"])
    resp = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        json=payload, timeout=timeout,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
    )
    if resp.status_code in (401, 402, 403):
        raise LLMCreditError(
            f"{endpoint.get('name', 'fast')} rejected the key "
            f"({resp.status_code}): {resp.text[:120]}")
    if resp.status_code == 404:
        # The model name is not on this account (a provider retired it, or a
        # gateway's catalogue differs). Retrying it is pointless.
        raise LLMModelMissing(
            f"{endpoint.get('name', 'fast')} has no model {payload['model']!r}")
    if resp.status_code == 429:
        # Free tiers cap tokens-per-minute. Waiting for the bucket to refill
        # is far cheaper than falling back to a ~136s local generation.
        try:
            wait = float(resp.headers.get("retry-after", "") or 0)
        except ValueError:
            wait = 0.0
        # A per-day cap will not refill within any sane wait: escalate at once.
        daily = "per day" in resp.text.lower() or "tpd" in resp.text.lower()
        raise LLMRateLimit(wait or 20.0, daily=daily)
    if resp.status_code == 400:
        # A malformed request will fail identically on every retry: surface it
        # loudly instead of burning the local fallback on it.
        logger.error("[llm] fast provider rejected the request: %s", resp.text[:200])
    resp.raise_for_status()
    body = resp.json()
    u = body.get("usage") or {}
    usage.note_tokens(u.get("prompt_tokens"), u.get("completion_tokens"))
    choice = body["choices"][0]
    if choice.get("finish_reason") == "length":
        # Measured 2026-11-15: strategy brief, strategy draft and blog draft all
        # came back cut mid-sentence on gpt-oss-120b (its reasoning tokens count
        # against max_tokens) and were handed over as if finished.
        raise LLMTruncated(
            f"{endpoint.get('name', 'fast')}: risposta tagliata al tetto di {max_tokens} token")
    return choice["message"]["content"]


def transcribe_audio(path: str, prompt: str = "", language: str = "it") -> dict:
    """Speech-to-text on the fast provider (whisper-large-v3).

    Returns {"text", "segments", "model"}. `prompt` carries the domain
    glossary: whisper conditions on it, which is what fixes recurring medical
    terms the local `small` model mangles ("ormoni bioidentici").
    Raises LLMError so the caller can fall back to the local model.
    """
    if not settings.STT_API_KEY:
        raise LLMError("no STT provider key")
    url = f"{settings.STT_BASE_URL.rstrip('/')}/audio/transcriptions"
    data = {"model": settings.FAST_STT_MODEL, "language": language,
            "response_format": "verbose_json", "temperature": "0"}
    if prompt:
        data["prompt"] = prompt[:800]
    with open(path, "rb") as fh:
        resp = requests.post(
            url, headers={"Authorization": f"Bearer {settings.STT_API_KEY}"},
            files={"file": (os.path.basename(path), fh, "audio/mpeg")},
            data=data, timeout=300,
        )
    if resp.status_code == 429:
        try:
            wait = float(resp.headers.get("retry-after", "") or 0)
        except ValueError:
            wait = 0.0
        daily = "per day" in resp.text.lower() or "tpd" in resp.text.lower()
        raise LLMRateLimit(wait or 20.0, daily=daily)
    if resp.status_code >= 400:
        raise LLMError(f"STT failed ({resp.status_code}): {resp.text[:200]}")
    payload = resp.json()
    segments = [
        {"start": round(float(s.get("start", 0)), 2),
         "end": round(float(s.get("end", 0)), 2),
         "text": (s.get("text") or "").strip()}
        for s in payload.get("segments", [])
    ]
    return {"text": (payload.get("text") or "").strip(),
            "segments": segments,
            "model": settings.FAST_STT_MODEL}


TASKS = ("analysis", "reasoning", "bulk")


def _endpoints() -> list[dict]:
    """The remote providers still worth trying, in priority order."""
    now = time.monotonic()
    for name, since in list(_fast_disabled.items()):
        if now - since >= settings.LLM_RETRY_DISABLED_AFTER:
            del _fast_disabled[name]
    return [e for e in settings.FAST_ENDPOINTS
            if e.get("api_key") and e["name"] not in _fast_disabled]


def model_for(task: str) -> str:
    """The model name for a kind of work, on the FIRST live provider.

    'analysis'  reading a transcript, extracting claims, naming themes —
                the deep layer, where a weak model costs meaning
    'reasoning' strategy briefs and drafts
    'bulk'      mechanical, high-volume extraction

    Callers pass the result back as chat(model=...); chat() re-resolves it per
    provider as it walks the chain, so a caller never needs to know who will
    end up answering.
    """
    order = {"analysis": ("analysis", "reasoning", "bulk"),
             "reasoning": ("reasoning", "analysis", "bulk")}.get(
                 task, ("bulk", "reasoning", "analysis"))
    for ep in _endpoints() or settings.FAST_ENDPOINTS:
        for tier in order:
            if ep.get("models", {}).get(tier):
                return ep["models"][tier]
    return settings.OLLAMA_MODEL


def _task_of(model: str) -> str:
    """Which tier a model name belongs to, across every configured provider.

    This is what lets the chain keep its meaning: a caller asked for the
    'analysis' model of provider #1, so when provider #2 answers instead it
    must answer with ITS analysis model, not with provider #1's name — which
    it would 404 on.
    """
    for ep in settings.FAST_ENDPOINTS:
        for tier, name in (ep.get("models") or {}).items():
            if name and name == model:
                return tier
    return ""


def _providers() -> list[tuple[str, dict | None]]:
    """(kind, endpoint) in the order they will be tried."""
    order: list[tuple[str, dict | None]] = []
    for p in settings.LLM_PROVIDER_ORDER:
        p = p.strip().lower()
        if p == "fast":
            order += [("fast", ep) for ep in _endpoints()]
        elif p == "ollama":
            order.append(("ollama", None))
    return order


# Local calls made by THIS process in a pipeline round. A round is one process
# (cron `run_pipeline`, or the `run_job` of a manual round), so a plain counter
# is the round's counter; `DAG.run` zeroes it when a round begins.
_local_calls = 0
_local_calls_lock = threading.Lock()


def reset_local_budget() -> None:
    global _local_calls
    with _local_calls_lock:
        _local_calls = 0


def local_calls_used() -> int:
    return _local_calls


def _take_local_call() -> bool:
    """Count a local call of a pipeline round, or refuse it when the round has
    used PIPELINE_LOCAL_MAX_CALLS. Calls that are not a pipeline stage (a Job
    the client started, a command) are not capped: a person is waiting for them.

    Why a cap at all: with Groq switched off the 7b would need ~9 h for a big
    round (141 calls x ~4 min) and run into the 14:15 round."""
    global _local_calls
    cap = settings.PIPELINE_LOCAL_MAX_CALLS
    if cap <= 0 or not usage.current()["process"].startswith("pipeline:"):
        return False
    with _local_calls_lock:
        if _local_calls >= cap:
            raise LLMLocalBudget(
                f"tetto di {cap} chiamate al modello locale raggiunto in questo giro")
        _local_calls += 1
    return True


def _give_back_local_call() -> None:
    """A call that never got the slot (busy, Ollama unreachable) generated
    nothing: it must not use up the round's allowance."""
    global _local_calls
    with _local_calls_lock:
        _local_calls = max(0, _local_calls - 1)


def chat(system: str, user: str, max_tokens: int = 800, temperature: float = 0.2,
         retries: int = 2, json_mode: bool = False, timeout: int | None = None,
         on_token=None, priority: bool = False, model: str = "",
         remote_only: bool = False) -> str:
    """Return raw assistant text, trying providers in order with retries.

    json_mode nudges Ollama to emit valid JSON — set only for extraction
    prompts, never for free-text answers (it degrades prose quality).
    timeout is the ceiling of one answer: it bounds the local model (default
    OLLAMA_PIPELINE_TIMEOUT, a 7b needs minutes) and, capped at 120 s, a remote
    call. `retries` is for unexpected errors; a per-minute rate limit is waited
    out up to LLM_RATE_WAITS times, except with retries=0 ("fail fast").
    remote_only: never touch the local model; raises `LLMRemoteUnavailable`.
    """
    providers = _providers()
    if remote_only:
        providers = [p for p in providers if p[0] != "ollama"]
    if not providers:
        raise (LLMRemoteUnavailable("nessun provider remoto disponibile (manca la chiave?)")
               if remote_only else
               LLMError("no LLM provider available (no key, Ollama disabled)"))

    # The tier the caller asked for, so every provider in the chain answers
    # with ITS model of that tier instead of a name it does not serve.
    task = _task_of(model) if model else ""
    remote_timeout = min(timeout or 240, 120)
    max_waits = settings.LLM_RATE_WAITS if retries > 0 else 0

    def _model_on(endpoint) -> str:
        if not model:
            return ""
        if endpoint.get("models", {}).get(task):
            return endpoint["models"][task]
        return model if endpoint is (settings.FAST_ENDPOINTS or [None])[0] else ""

    prompt_chars = len(system) + len(user)

    def _recorded(label: str, model_name: str, fn) -> str:
        """Run one remote attempt and write it down. The row exists while the
        call is in flight (so the page can say who is working) and is closed
        with the tokens the provider reported."""
        rec = usage.begin(label, model_name, is_local=False, waiting=False,
                          max_tokens=max_tokens, prompt_chars=prompt_chars)
        try:
            text = fn()
        except BaseException as exc:
            if isinstance(exc, LLMTruncated):
                rec.stats(truncated=True)
            rec.fail(exc)
            raise
        rec.done_remote(model=last_model_used())
        return text

    def _patient(label: str, fn) -> str:
        """One remote call that waits out the per-minute cap. Groq refused 169
        of 287 calls on 2026-11-15, all with "retry in 1-21 s": waiting 20 s
        costs 12 times less than the 4-minute local call it used to trigger. A
        per-DAY cap is not waited for (it will not refill): it escalates at once."""
        waits = 0
        while True:
            try:
                return fn()
            except LLMRateLimit as exc:
                if exc.daily or waits >= max_waits:
                    raise
                waits += 1
                wait = min(max(exc.retry_after, 1.0), 60.0)
                logger.info("[llm] %s rate-limited — waiting %.0fs (%d/%d)",
                            label, wait, waits, max_waits)
                time.sleep(wait)

    def _call_alt(endpoint, alt_model: str) -> str:
        """Same endpoint, a sibling model — used when a daily cap is hit."""
        return _patient(endpoint["name"], lambda: _recorded(
            endpoint["name"], alt_model, lambda: _fast_chat(
                system, user, max_tokens, temperature, json_mode=json_mode,
                timeout=min(timeout or 240, 300), model=alt_model, endpoint=endpoint)))

    def _call(provider, endpoint=None):
        if provider == "fast":
            name = _model_on(endpoint) or endpoint.get("models", {}).get("reasoning", "")
            return _patient(endpoint["name"], lambda: _recorded(
                endpoint["name"], name, lambda: _fast_chat(
                    system, user, max_tokens, temperature,
                    json_mode=json_mode, timeout=remote_timeout,
                    model=_model_on(endpoint), endpoint=endpoint)))
        # Local generation: take the single CPU slot, never run two at once.
        # The budget is checked before the row is born: a refused call is not
        # a call. The row is born BEFORE the wait: "in coda" is a state worth showing.
        counted = _take_local_call()
        rec = usage.begin("ollama", settings.OLLAMA_MODEL, is_local=True, waiting=True,
                          max_tokens=max_tokens, prompt_chars=prompt_chars)
        try:
            with _ollama_slot(priority=priority):
                rec.running()
                text = _ollama_chat(system, user, max_tokens, temperature,
                                    json_mode=json_mode, timeout=timeout,
                                    on_token=on_token, rec=rec)
        except BaseException as exc:
            if counted and isinstance(exc, LLMLocalUnavailable):
                _give_back_local_call()
            rec.fail(exc)
            raise
        rec.done(model=f"{settings.OLLAMA_MODEL}")
        return text

    last_err = None
    for provider, endpoint in providers:
        label = endpoint["name"] if endpoint else provider
        for attempt in range(retries + 1):
            try:
                return _call(provider, endpoint)
            except LLMModelMissing as exc:
                # The provider works, the model name does not exist on it.
                # Next provider, and keep this one available for other tiers.
                logger.warning("[llm] %s: %s", label, exc)
                last_err = exc
                break
            except LLMCreditError as exc:
                logger.warning("[llm] %s key rejected/depleted — disabling it: %s",
                               label, exc)
                if provider == "fast":
                    _fast_disabled[endpoint["name"]] = time.monotonic()
                    _problem["text"] = (f"{endpoint['name'].capitalize()} non risponde: "
                                        "chiave rifiutata; il lavoro va sul modello locale")
                    _announce(_problem["text"])
                last_err = exc
                break
            except LLMTruncated as exc:
                if provider == "fast":
                    # Groq cut the answer at our ceiling. The local model would
                    # be cut at the same place after minutes of work, and a
                    # free text must not be handed over half written: the
                    # caller gets the named error at once.
                    logger.warning("[llm] %s: %s", label, exc)
                    raise
                logger.warning("[llm] %s: %s — not retrying", label, exc)
                last_err = exc
                break
            except (LLMLocalUnavailable, LLMLocalBudget) as exc:
                # Local failures with a name. None improves on a second try: the
                # slot is still taken, the answer is cut at the same place, the
                # round's budget is still spent — and each try is 4-9 minutes.
                logger.warning("[llm] %s: %s — not retrying", label, exc)
                last_err = exc
                break
            except LLMRateLimit as exc:
                last_err = exc
                if exc.daily and provider == "fast":
                    # Today's budget for THIS model is gone; each model has its
                    # own. Walk the chain before ever dropping to local CPU.
                    tried = {_model_on(endpoint)
                             or endpoint.get("models", {}).get("reasoning")}
                    for alt in endpoint.get("chain", []):
                        if alt in tried:
                            continue
                        tried.add(alt)
                        logger.warning("[llm] daily budget exhausted — switching to %s", alt)
                        try:
                            return _call_alt(endpoint, alt)
                        except LLMRateLimit as exc2:
                            last_err = exc2
                            if not exc2.daily:
                                break
                        except Exception as exc2:  # noqa: BLE001
                            last_err = exc2
                            break
                # Not daily: `_patient` already waited as many times as allowed.
                break
            except requests.exceptions.Timeout as exc:
                # Retrying a timeout means asking a machine that is already
                # too slow to redo the same work — it only deepens the jam.
                logger.warning("[llm] %s timed out after %ss — not retrying", label, timeout)
                last_err = exc
                break
            except Exception as exc:  # noqa: BLE001
                # Log it: an unexpected failure here used to be invisible, and
                # the chain moving on quietly is exactly how a misconfigured
                # provider goes unnoticed for weeks.
                logger.warning("[llm] %s failed (attempt %s/%s): %r",
                               label, attempt + 1, retries + 1, exc)
                last_err = exc
                if attempt < retries:
                    time.sleep(2 ** attempt)
    if isinstance(last_err, NOT_THE_ITEMS_FAULT):
        # The stage must be able to tell "we could not try" from "it failed".
        raise last_err
    if remote_only:
        raise LLMRemoteUnavailable(f"remote providers failed: {last_err!r}")
    raise LLMError(f"all providers failed: {last_err!r}")


def chat_json(system: str, user: str, **kwargs) -> dict | list:
    kwargs.setdefault("json_mode", True)
    return parse_json(chat(system, user, **kwargs))


def parse_json(raw: str):
    text = (raw or "").strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    return json.loads(text)


def available() -> bool:
    """True if ANY provider can serve — a remote endpoint or local Ollama.

    The remote chain has to be checked first: without it this returned False
    whenever Ollama was unreachable, and the analysis stage skipped itself
    even though a paid, working provider was configured and answering.
    """
    if _endpoints():
        return True
    if "ollama" in [p.strip().lower() for p in settings.LLM_PROVIDER_ORDER]:
        try:
            requests.get(f"{settings.OLLAMA_URL}/api/tags", timeout=3).raise_for_status()
            return True
        except Exception:  # noqa: BLE001
            return False
    return False
