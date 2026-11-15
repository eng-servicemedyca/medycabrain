"""
The model chain after 2026-11-15: Groq first, the local 7b as the backstop, and
nothing else. Every test fakes the network and Ollama — nothing leaves the
process — and the clock (`time.sleep`), so six "waits" cost nothing.

What these protect, each one a decision of the design (`.claude/tasks/
2026-11-14-analisi-in-casa.md`, «Revisione del disegno (15/11)»):
  - the chain read from `.env.example` is Groq + local, no Anthropic / flow / hf;
  - Groq's per-minute cap is waited out SIX times before the local model;
  - a cut or busy local answer is an error with a name and is not retried;
  - `remote_only` never reaches Ollama;
  - a round's cap of local calls leaves the rest `pending`, never `failed`;
  - the 7b gets a bigger window, stays loaded, and is allowed to be slow;
  - one round at a time.
"""

from __future__ import annotations

import fcntl
import os
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from llm import client, usage
from llm.client import (LLMBusy, LLMError, LLMLocalBudget, LLMRateLimit,
                        LLMRemoteUnavailable, LLMTruncated)

ENDPOINT = {"name": "groq", "base_url": "http://groq.invalid/v1", "api_key": "k",
            "models": {"bulk": "m-bulk", "reasoning": "m-120", "analysis": "m-120"},
            "chain": ["m-120", "m-sibling", "m-bulk"]}


def _chain_settings(**extra):
    return override_settings(FAST_ENDPOINTS=[ENDPOINT],
                             LLM_PROVIDER_ORDER=["fast", "ollama"], **extra)


class _ChainCase(TestCase):
    def setUp(self):
        client._fast_disabled.clear()
        client.reset_local_budget()
        usage._reset_breaker()
        self.sleeps = []
        p = mock.patch.object(client.time, "sleep", side_effect=self.sleeps.append)
        p.start()
        self.addCleanup(p.stop)


class EnvExampleChainTests(SimpleTestCase):
    """`.env.example` is the template Giuseppe copies: it must describe the chain
    the code supports, and nothing from the vendors that were removed."""

    @staticmethod
    def _example() -> dict:
        path = Path(settings.BASE_DIR) / ".env.example"
        env = {}
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k] = v
        return env

    def test_the_chain_is_groq_then_local_and_nothing_else(self):
        import importlib
        env = self._example()
        with mock.patch.dict(os.environ, env):
            base = importlib.import_module("config.settings.base")
            endpoints = base._llm_endpoints()
        self.assertEqual([e["name"] for e in endpoints], ["groq"])
        self.assertEqual(env["LLM_PROVIDER_ORDER"].split(","), ["fast", "ollama"])
        self.assertEqual(env["OLLAMA_MODEL"], "qwen2.5:7b-instruct-q4_K_M")

    def test_no_removed_vendor_is_left_in_the_example(self):
        keys = " ".join(self._example())
        for gone in ("ANTHROPIC", "BATCH_", "HF_", "FLOW"):
            self.assertNotIn(gone, keys)

    def test_the_new_local_settings_are_documented(self):
        env = self._example()
        for key in ("OLLAMA_NUM_CTX", "OLLAMA_KEEP_ALIVE", "OLLAMA_PIPELINE_TIMEOUT",
                    "PIPELINE_LOCAL_MAX_CALLS"):
            self.assertIn(key, env)

    def test_the_removed_stage_and_code_are_gone(self):
        self.assertFalse(hasattr(client, "_anthropic_chat"))
        self.assertFalse(hasattr(client, "_hf_chat"))
        self.assertFalse(hasattr(settings, "BATCH_ENABLED"))
        self.assertFalse(hasattr(settings, "HF_API_TOKEN"))
        with self.assertRaises(ImportError):
            import llm.batch  # noqa: F401


class OllamaPayloadTests(SimpleTestCase):
    def _sent(self, lines, **kw):
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.iter_lines.return_value = lines
        with mock.patch.object(client.requests, "post", return_value=resp) as post:
            out = client._ollama_chat("s", "u", 50, 0.0, **kw)
        return post, out

    @override_settings(OLLAMA_NUM_CTX=8192, OLLAMA_KEEP_ALIVE="30m")
    def test_window_and_keep_alive_are_in_the_payload(self):
        post, _ = self._sent([b'{"message": {"content": "ok"}, "done": true}'])
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["options"]["num_ctx"], 8192)
        self.assertEqual(body["keep_alive"], "30m")

    @override_settings(OLLAMA_READ_TIMEOUT=600)
    def test_silence_allowed_is_ten_minutes_not_two(self):
        post, _ = self._sent([b'{"message": {"content": "ok"}, "done": true}'])
        self.assertEqual(post.call_args.kwargs["timeout"], (10, 600))

    def test_a_cut_answer_is_an_error_with_its_name_not_a_string(self):
        with self.assertRaisesRegex(LLMTruncated, "tagliata"):
            self._sent([b'{"message": {"content": "{\\"a\\": "}, "done": false}',
                        b'{"message": {"content": ""}, "done": true, "done_reason": "length"}'])

    def test_a_deadline_overrun_is_also_a_named_error(self):
        lines = [b'{"message": {"content": "x"}, "done": false}'] * 3
        with mock.patch.object(client.time, "time", side_effect=[0, 0, 10_000, 10_000]):
            with self.assertRaises(LLMTruncated):
                self._sent(lines, timeout=5)

    def test_a_whole_answer_passes(self):
        _, out = self._sent([b'{"message": {"content": "ciao"}, "done": false}',
                             b'{"message": {"content": ""}, "done": true, "done_reason": "stop"}'])
        self.assertEqual(out, "ciao")


@_chain_settings()
class RateLimitWaitTests(_ChainCase):
    def test_six_waits_on_the_per_minute_cap_before_the_local_model(self):
        with mock.patch.object(client, "_fast_chat",
                               side_effect=LLMRateLimit(5)) as fast, \
             mock.patch.object(client, "_ollama_chat", return_value="locale") as oll:
            out = client.chat("s", "u")
        self.assertEqual(out, "locale")
        self.assertEqual(fast.call_count, 7)          # 1 try + 6 waits
        self.assertEqual(self.sleeps, [5.0] * 6)      # as long as Groq says
        self.assertEqual(oll.call_count, 1)

    def test_groq_answering_after_two_waits_never_reaches_the_local_model(self):
        with mock.patch.object(client, "_fast_chat",
                               side_effect=[LLMRateLimit(3), LLMRateLimit(4), "groq"]), \
             mock.patch.object(client, "_ollama_chat") as oll:
            self.assertEqual(client.chat("s", "u"), "groq")
        self.assertEqual(self.sleeps, [3.0, 4.0])
        oll.assert_not_called()

    def test_retries_zero_means_fail_fast_no_waiting(self):
        with mock.patch.object(client, "_fast_chat", side_effect=LLMRateLimit(5)) as fast, \
             mock.patch.object(client, "_ollama_chat", return_value="locale"):
            client.chat("s", "u", retries=0)
        self.assertEqual(fast.call_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_a_daily_cap_is_not_waited_for_it_walks_the_sibling_models(self):
        seen = []

        def fast(system, user, mt, temp, json_mode=False, timeout=0, model="", endpoint=None):
            seen.append(model)
            if model != "m-sibling":
                raise LLMRateLimit(1, daily=True)
            return "dal fratello"

        with mock.patch.object(client, "_fast_chat", side_effect=fast), \
             mock.patch.object(client, "_ollama_chat") as oll:
            self.assertEqual(client.chat("s", "u", model="m-120"), "dal fratello")
        self.assertEqual(self.sleeps, [])
        self.assertIn("m-sibling", seen)
        oll.assert_not_called()


@_chain_settings()
class LocalFailureTests(_ChainCase):
    def _groq_down(self):
        return mock.patch.object(client, "_fast_chat",
                                 side_effect=LLMRateLimit(1, daily=True))

    def test_a_cut_local_answer_is_not_retried(self):
        with self._groq_down(), \
             mock.patch.object(client, "_ollama_chat",
                               side_effect=LLMTruncated("tagliata")) as oll:
            with self.assertRaises(LLMError):
                client.chat("s", "u", retries=2)
        self.assertEqual(oll.call_count, 1)

    def test_a_busy_local_slot_is_not_retried(self):
        with self._groq_down(), \
             mock.patch.object(client, "_ollama_slot", side_effect=LLMBusy("occupato")) as slot, \
             mock.patch.object(client, "_ollama_chat") as oll:
            with self.assertRaises(LLMError):
                client.chat("s", "u", retries=2)
        self.assertEqual(slot.call_count, 1)
        oll.assert_not_called()

    def test_a_cut_answer_is_recorded_as_failed_and_truncated(self):
        from core.models import LLMCall

        def cut(system, user, mt, temp, json_mode=False, timeout=None,
                on_token=None, rec=None):
            rec.stats(truncated=True, output_tokens=7)
            raise LLMTruncated("tagliata")

        with self._groq_down(), mock.patch.object(client, "_ollama_chat", side_effect=cut):
            with self.assertRaises(LLMError):
                client.chat("s", "u")
        row = LLMCall.objects.filter(provider="ollama").latest("id")
        self.assertEqual((row.status, row.truncated, row.output_tokens),
                         ("failed", True, 7))

    def test_ollama_answers_inside_the_pipeline_ceiling_by_default(self):
        with self._groq_down(), \
             mock.patch.object(client, "_ollama_chat", return_value="ok") as oll:
            client.chat("s", "u")
        # no explicit timeout: _ollama_chat picks OLLAMA_PIPELINE_TIMEOUT itself
        self.assertIsNone(oll.call_args.kwargs["timeout"])


@_chain_settings()
class RemoteOnlyTests(_ChainCase):
    def test_remote_only_never_calls_ollama_when_groq_refuses(self):
        for err in (LLMRateLimit(5), LLMRateLimit(5, daily=True),
                    client.LLMCreditError("401"), RuntimeError("rete")):
            client._fast_disabled.clear()
            with self.subTest(err=repr(err)), \
                 mock.patch.object(client, "_fast_chat", side_effect=err), \
                 mock.patch.object(client, "_ollama_chat") as oll, \
                 mock.patch.object(client, "_ollama_slot") as slot:
                with self.assertRaises(LLMRemoteUnavailable):
                    client.chat("s", "u", remote_only=True)
                oll.assert_not_called()
                slot.assert_not_called()

    def test_remote_only_still_uses_groq_when_it_answers(self):
        with mock.patch.object(client, "_fast_chat", return_value="groq"):
            self.assertEqual(client.chat("s", "u", remote_only=True), "groq")

    @override_settings(FAST_ENDPOINTS=[], LLM_PROVIDER_ORDER=["fast", "ollama"])
    def test_remote_only_without_any_key_is_the_named_error(self):
        with mock.patch.object(client, "_ollama_chat") as oll:
            with self.assertRaises(LLMRemoteUnavailable):
                client.chat("s", "u", remote_only=True)
        oll.assert_not_called()

    def test_the_editorial_plan_asks_remote_only_and_says_riprova_piu_tardi(self):
        from core import editorial
        from core.upload_workflow import _client_message
        seen = {}

        def boom(*a, **kw):
            seen.update(kw)
            raise LLMRemoteUnavailable("tetto")

        with mock.patch.object(editorial.client, "chat_json", side_effect=boom):
            with self.assertRaises(LLMRemoteUnavailable) as cm:
                editorial.generate_plan(n=3)
        self.assertTrue(seen["remote_only"])
        self.assertIn("Riprova più tardi", _client_message(cm.exception))

    def test_the_rerank_asks_remote_only(self):
        from core import knowledge
        seen = {}

        def fake(*a, **kw):
            seen.update(kw)
            return {"ordine": [1, 0]}

        hits = [{"kind": "reel", "title": "a", "snippet": "x"},
                {"kind": "reel", "title": "b", "snippet": "y"}]
        with mock.patch.object(knowledge.client, "chat_json", side_effect=fake):
            out = knowledge._rerank("q", hits)
        self.assertTrue(seen["remote_only"])
        self.assertEqual([h["title"] for h in out], ["b", "a"])


@_chain_settings(PIPELINE_LOCAL_MAX_CALLS=2)
class LocalBudgetTests(_ChainCase):
    def _groq_down(self):
        return mock.patch.object(client, "_fast_chat",
                                 side_effect=LLMRateLimit(1, daily=True))

    def test_the_cap_refuses_the_third_local_call_with_its_own_error(self):
        with self._groq_down(), \
             mock.patch.object(client, "_ollama_chat", return_value="ok") as oll, \
             usage.scope("pipeline:enrich", stage="enrich"):
            self.assertEqual(client.chat("s", "u"), "ok")
            self.assertEqual(client.chat("s", "u"), "ok")
            with self.assertRaises(LLMLocalBudget):
                client.chat("s", "u")
        self.assertEqual(oll.call_count, 2)
        self.assertEqual(client.local_calls_used(), 2)

    def test_groq_calls_do_not_use_the_allowance(self):
        with mock.patch.object(client, "_fast_chat", return_value="groq"), \
             usage.scope("pipeline:enrich", stage="enrich"):
            for _ in range(5):
                client.chat("s", "u")
        self.assertEqual(client.local_calls_used(), 0)

    def test_a_person_waiting_is_never_capped(self):
        with self._groq_down(), \
             mock.patch.object(client, "_ollama_chat", return_value="ok"), \
             usage.scope("job:strategy"):
            for _ in range(4):
                client.chat("s", "u")
        self.assertEqual(client.local_calls_used(), 0)

    @override_settings(PIPELINE_LOCAL_MAX_CALLS=0)
    def test_zero_means_no_cap(self):
        with self._groq_down(), \
             mock.patch.object(client, "_ollama_chat", return_value="ok"), \
             usage.scope("pipeline:enrich", stage="enrich"):
            for _ in range(4):
                client.chat("s", "u")


class StageKeepsWhatItDidNotTryPendingTests(TestCase):
    """The cap is not a failure: the stage stops, says so, and leaves the reels
    it did not try `pending`. A real error stays `failed`."""

    @classmethod
    def setUpTestData(cls):
        from core.models import DONE, Reel, TrackedAccount, Transcript
        acc = TrackedAccount.objects.create(username="x", owner_type="competitor")
        cls.reels = []
        for i in range(4):
            r = Reel.objects.create(account=acc, shortcode=f"S{i}", caption="c" * 100,
                                    transcribe_status=DONE)
            Transcript.objects.create(reel=r, text="parlato " * 20)
            cls.reels.append(r)

    def _run(self, fn):
        from pipeline.agents import enrich_agent
        from pipeline.dag import Context
        with mock.patch.object(enrich_agent.client, "available", return_value=True), \
             mock.patch.object(enrich_agent, "_enrich_one", side_effect=fn), \
             mock.patch.object(enrich_agent, "_extract_arguments", return_value=0), \
             mock.patch.object(enrich_agent.progress, "note") as note:
            return enrich_agent.run(Context()), note

    def test_budget_leaves_pending_and_says_so(self):
        calls = []

        def fn(reel):
            calls.append(reel.id)
            if len(calls) > 1:
                raise LLMLocalBudget("tetto")

        out, note = self._run(fn)
        from core.models import Reel
        states = list(Reel.objects.order_by("id").values_list("enrich_status", flat=True))
        self.assertEqual(states.count("done"), 1)
        self.assertEqual(states.count("pending"), 3)
        self.assertNotIn("failed", states)
        self.assertEqual(out["deferred"], 3)
        self.assertEqual(out["enrich_failed"], 0)
        self.assertEqual(len(calls), 2)               # it stopped, it did not grind on
        self.assertIn("restano in attesa", note.call_args.args[0])

    def test_a_real_error_stays_failed(self):
        def fn(reel):
            raise RuntimeError("risposta rotta")

        out, _ = self._run(fn)
        from core.models import Reel
        self.assertEqual(Reel.objects.filter(enrich_status="failed").count(), 4)
        self.assertEqual(out["enrich_failed"], 4)
        self.assertNotIn("deferred", out)

    def test_one_worker_by_default(self):
        from pipeline.agents import enrich_agent
        self.assertEqual(enrich_agent._WORKERS, 1)


class OneRoundAtATimeTests(SimpleTestCase):
    def test_a_second_round_refuses_and_says_so_while_the_first_works(self):
        from pipeline.dag import DAG, ROUND_BUSY, Context, Step
        ran = []
        with tempfile.TemporaryDirectory() as tmp:
            lock = os.path.join(tmp, "round.lock")
            with override_settings(PIPELINE_LOCK_PATH=lock):
                fd = os.open(lock, os.O_CREAT | os.O_RDWR)
                fcntl.flock(fd, fcntl.LOCK_EX)           # "another round is working"
                try:
                    with mock.patch("builtins.print") as pr:
                        code = DAG([Step("x", lambda ctx: ran.append(1))]).run(Context())
                finally:
                    os.close(fd)
                self.assertEqual(code, ROUND_BUSY)
                self.assertEqual(ran, [])
                self.assertIn("un altro giro", " ".join(str(c) for c in pr.call_args_list))

    def test_the_lock_is_released_when_the_round_ends(self):
        from pipeline.dag import DAG, Context, Step
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(PIPELINE_LOCK_PATH=os.path.join(tmp, "round.lock")):
                with mock.patch("core.progress.plan_stages", return_value={}), \
                     mock.patch("core.progress.drop_waiting"):
                    for _ in range(2):   # the second would be refused if it leaked
                        self.assertEqual(
                            DAG([Step("x", lambda ctx: {})]).run(Context()), 0)

    def test_a_dry_run_takes_no_lock(self):
        from pipeline.dag import DAG, Context, Step
        with tempfile.TemporaryDirectory() as tmp:
            lock = os.path.join(tmp, "round.lock")
            with override_settings(PIPELINE_LOCK_PATH=lock):
                fd = os.open(lock, os.O_CREAT | os.O_RDWR)
                fcntl.flock(fd, fcntl.LOCK_EX)
                try:
                    self.assertEqual(
                        DAG([Step("x", lambda ctx: {})]).run(Context(dry_run=True)), 0)
                finally:
                    os.close(fd)


class StatusPageSaysTheTruthTests(SimpleTestCase):
    def test_models_names_groq_then_the_local_model_and_marks_remote_only(self):
        from core import ops
        with override_settings(FAST_ENDPOINTS=[ENDPOINT], OLLAMA_MODEL="qwen-locale"):
            rows = {r["task"]: r["model"] for r in ops.models()}
        self.assertEqual(rows["Analisi dei contenuti"], "m-120 → riserva: qwen-locale")
        self.assertIn("solo Groq", rows["Piano editoriale"])
        self.assertIn("solo Groq", rows["Riordino dei risultati di ricerca"])
        self.assertNotIn("claude", " ".join(rows.values()).lower())


# ── second round of fixes (review R1-R3, test D1-D4) ──────────────────────────

@_chain_settings()
class SlowGroqRerankTests(_ChainCase):
    def test_the_rerank_waits_ten_seconds_at_most_then_answers_in_plain_order(self):
        import requests
        from core import knowledge
        seen = {}

        def slow(url, **kw):
            seen["timeout"] = kw.get("timeout")
            raise requests.exceptions.ReadTimeout("Groq accetta e poi tace")

        hits = [{"kind": "reel", "title": "a", "snippet": "x"},
                {"kind": "reel", "title": "b", "snippet": "y"}]
        with mock.patch.object(client.requests, "post", side_effect=slow), \
             mock.patch.object(client, "_ollama_chat") as oll:
            out = knowledge._rerank("q", hits)
        self.assertEqual(seen["timeout"], knowledge.RERANK_TIMEOUT)
        self.assertLessEqual(knowledge.RERANK_TIMEOUT, 10)
        self.assertEqual([h["title"] for h in out], ["a", "b"])   # plain order
        oll.assert_not_called()
        self.assertEqual(self.sleeps, [])


@_chain_settings(LLM_RETRY_DISABLED_AFTER=600)
class RefusedKeyIsSeenAndNotForeverTests(_ChainCase):
    def test_a_refused_key_is_said_on_the_stage_note_not_only_in_the_log(self):
        with mock.patch.object(client, "_fast_chat", side_effect=client.LLMCreditError("403")), \
             mock.patch.object(client, "_ollama_chat", return_value="locale"), \
             mock.patch("core.progress.note") as note:
            client.chat("s", "u")
        self.assertIn("Groq non risponde: chiave rifiutata", note.call_args.args[0])
        self.assertIn("modello locale", client.remote_problem())

    def test_it_is_tried_again_after_the_interval(self):
        with mock.patch.object(client, "_fast_chat", side_effect=client.LLMCreditError("403")), \
             mock.patch.object(client, "_ollama_chat", return_value="locale"):
            client.chat("s", "u")
        self.assertEqual(client._endpoints(), [])            # off for now
        later = client.time.monotonic() + 601
        with mock.patch.object(client.time, "monotonic", return_value=later):
            self.assertEqual([e["name"] for e in client._endpoints()], ["groq"])
        self.assertEqual(client.remote_problem(), "")         # and no longer reported

    def test_a_stage_that_ends_normally_still_says_it(self):
        from pipeline.agents import enrich_agent
        client._fast_disabled["groq"] = client.time.monotonic()
        client._problem["text"] = "Groq non risponde: chiave rifiutata; il lavoro va sul modello locale"
        with mock.patch.object(enrich_agent.progress, "note") as note:
            enrich_agent.note_remote_problem()
        self.assertIn("chiave rifiutata", note.call_args.args[0])


class KnownProvidersOnlyTests(SimpleTestCase):
    def _endpoints(self, names):
        import importlib
        env = {"LLM_ENDPOINTS": names, "LLM_GROQ_BASE_URL": "https://g.invalid/v1",
               "LLM_GROQ_API_KEY": "k", "LLM_GROQ_MODEL_BULK": "b",
               "LLM_ANTHROPIC_BASE_URL": "https://api.anthropic.com",
               "LLM_ANTHROPIC_API_KEY": "sk-old", "LLM_ANTHROPIC_MODEL_BULK": "x",
               "LLM_FLOW_BASE_URL": "https://flow.invalid/v1", "LLM_FLOW_API_KEY": "old",
               "LLM_FLOW_MODEL_BULK": "y"}
        with mock.patch.dict(os.environ, env):
            base = importlib.import_module("config.settings.base")
            with self.assertLogs("config.settings", "WARNING") as logs:
                import logging
                logging.getLogger("config.settings").warning("sentinel")  # assertLogs needs one
                out = base._llm_endpoints()
        return out, logs.output

    def test_old_vendor_names_are_ignored_with_one_warning_and_their_keys_never_used(self):
        out, logs = self._endpoints("anthropic,groq,flow,hf")
        self.assertEqual([e["name"] for e in out], ["groq"])
        warned = [l for l in logs if "sconosciuti" in l]
        self.assertEqual(len(warned), 1)
        self.assertIn("anthropic", warned[0])
        self.assertNotIn("sk-old", " ".join(logs))             # no secret in the log
        self.assertNotIn("sk-old", repr(out))                  # and not in the chain

    def test_only_old_names_means_no_endpoint_at_all(self):
        out, _ = self._endpoints("anthropic,flow")
        self.assertEqual(out, [])


@_chain_settings()
class GroqCutAnswerTests(_ChainCase):
    def _post(self, finish):
        resp = mock.MagicMock(status_code=200)
        resp.json.return_value = {"choices": [{"finish_reason": finish,
                                               "message": {"content": "A metà fra"}}],
                                  "usage": {"prompt_tokens": 5, "completion_tokens": 900}}
        return mock.patch.object(client.requests, "post", return_value=resp)

    def test_finish_reason_length_is_a_named_error_recorded_as_truncated(self):
        from core.models import LLMCall
        with self._post("length"), mock.patch.object(client, "_ollama_chat") as oll:
            with self.assertRaises(LLMTruncated):
                client.chat("s", "u", max_tokens=900)
        oll.assert_not_called()    # the 7b would be cut at the same place, minutes later
        row = LLMCall.objects.filter(provider="groq").latest("id")
        self.assertEqual((row.status, row.truncated), ("failed", True))

    def test_a_finished_answer_passes(self):
        with self._post("stop"):
            self.assertEqual(client.chat("s", "u"), "A metà fra")

    def test_the_client_hears_it_and_the_ceilings_are_doubled(self):
        import inspect

        from core import blog_workflow, strategy
        from core.upload_workflow import _client_message
        self.assertIn("tagliata", _client_message(LLMTruncated("x")))
        self.assertIn("Riprova più tardi", _client_message(LLMRemoteUnavailable("x")))
        self.assertTrue(_client_message(LLMRemoteUnavailable("x")).startswith("Riprova"))
        src = inspect.getsource(strategy)
        self.assertIn("max_tokens=1800", src)
        self.assertIn("max_tokens=2400", src)
        self.assertIn("max_tokens=2400", inspect.getsource(blog_workflow))


@_chain_settings(PIPELINE_LOCAL_MAX_CALLS=2)
class LocalNotReachableTests(_ChainCase):
    def _groq_down(self):
        return mock.patch.object(client, "_fast_chat",
                                 side_effect=LLMRateLimit(1, daily=True))

    def test_ollama_not_reachable_is_not_the_contents_fault_and_costs_no_allowance(self):
        import requests
        with self._groq_down(), \
             mock.patch.object(client.requests, "post",
                               side_effect=requests.exceptions.ConnectionError("giù")), \
             usage.scope("pipeline:enrich", stage="enrich"):
            for _ in range(3):
                with self.assertRaises(client.LLMLocalUnavailable):
                    client.chat("s", "u")
        self.assertEqual(client.local_calls_used(), 0)

    def test_a_busy_slot_costs_no_allowance(self):
        with self._groq_down(), \
             mock.patch.object(client, "_ollama_slot", side_effect=LLMBusy("occupato")), \
             usage.scope("pipeline:enrich", stage="enrich"):
            for _ in range(3):
                with self.assertRaises(LLMBusy):
                    client.chat("s", "u")
        self.assertEqual(client.local_calls_used(), 0)


class BusyLocalLeavesItemsPendingTests(StageKeepsWhatItDidNotTryPendingTests):
    """Same fixtures as the budget test: a busy or stopped local model is not the
    reel's fault either. `failed` is only for a real error of the content."""

    def test_busy_leaves_pending_and_the_note_says_the_local_model_was_unavailable(self):
        def fn(reel):
            raise LLMBusy("occupato")

        out, note = self._run(fn)
        from core.models import Reel
        self.assertEqual(Reel.objects.filter(enrich_status="pending").count(), 4)
        self.assertEqual(Reel.objects.filter(enrich_status="failed").count(), 0)
        self.assertEqual(out["deferred"], 4)
        self.assertIn("non era disponibile", note.call_args.args[0])

    def test_unreachable_ollama_is_the_same(self):
        def fn(reel):
            raise client.LLMLocalUnavailable("spento")

        out, _ = self._run(fn)
        from core.models import Reel
        self.assertEqual(Reel.objects.filter(enrich_status="failed").count(), 0)
        self.assertEqual(out["stopped"], "modello locale non disponibile")

    def test_the_note_says_groq_is_off_when_it_is(self):
        client._fast_disabled["groq"] = client.time.monotonic()
        client._problem["text"] = "Groq non risponde: chiave rifiutata; il lavoro va sul modello locale"
        self.addCleanup(client._fast_disabled.clear)

        def fn(reel):
            raise LLMLocalBudget("tetto")

        _, note = self._run(fn)
        self.assertIn("Groq non risponde", note.call_args.args[0])
        self.assertIn("restano in attesa", note.call_args.args[0])
