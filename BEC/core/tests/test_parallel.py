"""
The local model works on N things at once (2026-11-20, `.claude/tasks/
2026-11-18-locale-parallelo.md`).

What these protect, each one a decision of the design:
  - N seats from two numbers (`OLLAMA_NUM_PARALLEL`, `LOCAL_SLOTS`), never under 1,
    and with nothing written exactly one, as before;
  - the lock hands out N seats and the next caller waits, then says «busy»;
  - the priority of a person is SHARED: two of them do not queue one behind the
    other, and the nightly round stands aside while any of them holds it;
  - a job of the client (`job:...`) has priority by itself, the round does not;
  - Groq stays one call at a time, but `remote_only` does not queue behind it;
  - the pieces of a long text run together and come back IN THE ORDER OF THE TEXT;
    a failed piece stops the ones not yet started, the lowest piece number is
    the error kept, and a real failure beats «model away»;
  - the threads inherit the name of the content, with «· pezzo 3/7»;
  - `_parallel`: short ones first, results as they are ready, a flag instead of
    throwing away what is running, one count per deferred item;
  - the embedder is loaded once even if three threads ask at the same time.

No model is called and nothing leaves the process: Groq and Ollama are fakes, and
the threads never touch the database (so these are `SimpleTestCase`).
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import sys
import tempfile
import threading
import time
import types
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from core.tests.test_llm_chain import ENDPOINT
from core.tests.test_whole_text import _PEZZO, testo
from llm import client, usage
from llm.client import LLMBusy
from pipeline import whole_text
from pipeline.agents import cluster_agent, enrich_agent


# ── how many seats ──────────────────────────────────────────────────────────
class LocalSlotsTests(SimpleTestCase):
    def _n(self, parallel, slots):
        with override_settings(OLLAMA_NUM_PARALLEL=parallel, LOCAL_SLOTS=slots):
            return client.local_slots()

    def test_nothing_written_is_one_seat_as_before(self):
        self.assertEqual(self._n(1, 0), 1)

    def test_default_is_all_the_seats_ollama_has(self):
        self.assertEqual(self._n(3, 0), 3)

    def test_we_can_use_fewer_than_ollama_has(self):
        self.assertEqual(self._n(3, 2), 2)

    def test_never_more_than_ollama_has(self):
        self.assertEqual(self._n(2, 5), 2)

    def test_never_under_one(self):
        self.assertEqual(self._n(0, 0), 1)
        self.assertEqual(self._n(-4, 2), 1)


# ── the lock ────────────────────────────────────────────────────────────────
class SeatsTests(SimpleTestCase):
    def setUp(self):
        p = override_settings(OLLAMA_LOCK_PATH=tempfile.mktemp(prefix="test-seats-"))
        p.enable()
        self.addCleanup(p.disable)

    @staticmethod
    def _take(stack, n):
        for _ in range(n):
            stack.enter_context(client._ollama_slot(wait=1))

    @override_settings(OLLAMA_NUM_PARALLEL=3, LOCAL_SLOTS=0)
    def test_three_seats_and_the_fourth_waits_then_says_busy(self):
        with contextlib.ExitStack() as stack:
            self._take(stack, 3)
            t0 = time.time()
            with self.assertRaises(LLMBusy):
                with client._ollama_slot(wait=1):
                    self.fail("a fourth caller got a seat")
            self.assertGreaterEqual(time.time() - t0, 1.0)  # it did wait, as before
        # a seat freed: the next one passes at once
        with client._ollama_slot(wait=1):
            pass

    @override_settings(OLLAMA_NUM_PARALLEL=1, LOCAL_SLOTS=0)
    def test_one_seat_by_default_the_second_is_busy(self):
        with client._ollama_slot(wait=1):
            with self.assertRaises(LLMBusy):
                with client._ollama_slot(wait=1):
                    self.fail("two at once with one seat")

    @override_settings(OLLAMA_NUM_PARALLEL=3, LOCAL_SLOTS=2)
    def test_local_slots_caps_the_seats_we_use(self):
        with contextlib.ExitStack() as stack:
            self._take(stack, 2)
            with self.assertRaises(LLMBusy):
                with client._ollama_slot(wait=1):
                    self.fail("a third seat was used")

    @override_settings(OLLAMA_NUM_PARALLEL=3, LOCAL_SLOTS=0)
    def test_a_seat_is_given_back_even_when_the_work_fails(self):
        for _ in range(5):
            with self.assertRaises(RuntimeError):
                with client._ollama_slot(wait=1):
                    raise RuntimeError("generation broke")
        with contextlib.ExitStack() as stack:
            self._take(stack, 3)

    @override_settings(OLLAMA_NUM_PARALLEL=3, LOCAL_SLOTS=0)
    def test_the_old_one_seat_lock_file_is_seat_zero(self):
        """A process on the old code holds `OLLAMA_LOCK_PATH` alone: with it taken
        only two seats are left, never three."""
        fd = os.open(settings.OLLAMA_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o666)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            with contextlib.ExitStack() as stack:
                self._take(stack, 2)
                with self.assertRaises(LLMBusy):
                    with client._ollama_slot(wait=1):
                        self.fail("three seats beside an old holder")
        finally:
            os.close(fd)


class SharedPriorityTests(SimpleTestCase):
    def setUp(self):
        p = override_settings(OLLAMA_LOCK_PATH=tempfile.mktemp(prefix="test-prio-"),
                              OLLAMA_NUM_PARALLEL=3, LOCAL_SLOTS=0)
        p.enable()
        self.addCleanup(p.disable)

    def test_two_people_hold_priority_together_without_waiting_for_each_other(self):
        t0 = time.time()
        with client._ollama_slot(wait=5, priority=True):
            with client._ollama_slot(wait=5, priority=True):
                with client._ollama_slot(wait=5, priority=True):
                    pass
        self.assertLess(time.time() - t0, 1.0)  # no queue, no timeout

    def test_the_round_does_not_start_while_a_person_holds_priority(self):
        with client._ollama_slot(wait=5, priority=True):
            with mock.patch.object(client.time, "sleep"):
                with self.assertRaises(LLMBusy):
                    with client._ollama_slot(wait=0):
                        self.fail("batch work started while a person waits")

    def test_the_round_goes_on_once_the_people_are_done(self):
        with client._ollama_slot(wait=5, priority=True):
            pass
        with client._ollama_slot(wait=1):
            pass

    def test_a_job_of_the_client_has_priority_by_itself(self):
        with usage.scope("job:upload", job_id=1):
            self.assertTrue(client._is_client_job())
        with usage.scope("pipeline:enrich", stage="enrich"):
            self.assertFalse(client._is_client_job())
        with usage.scope("cmd:reprocess"):
            self.assertFalse(client._is_client_job())

    def test_chat_asks_for_priority_when_the_caller_is_a_job(self):
        asked = []

        def slot(wait=None, priority=False):
            asked.append(priority)
            return contextlib.nullcontext()

        with override_settings(FAST_ENDPOINTS=[], LLM_PROVIDER_ORDER=["ollama"]), \
             mock.patch.object(client, "_ollama_slot", side_effect=slot), \
             mock.patch.object(client, "_ollama_chat", return_value="ok"), \
             mock.patch.object(usage, "begin", return_value=mock.MagicMock()):
            with usage.scope("job:blog", job_id=2):
                client.chat("s", "u", retries=0)
            with usage.scope("pipeline:enrich", stage="enrich"):
                client.chat("s", "u", retries=0)
        self.assertEqual(asked, [True, False])


# ── Groq stays one at a time ────────────────────────────────────────────────
@override_settings(FAST_ENDPOINTS=[ENDPOINT], LLM_PROVIDER_ORDER=["fast"],
                   LLM_REMOTE_PARALLEL=1)
class RemoteGateTests(SimpleTestCase):
    def setUp(self):
        client._fast_disabled.clear()
        client._remote_gate_state = None
        self.addCleanup(setattr, client, "_remote_gate_state", None)
        p = mock.patch.object(usage, "begin", return_value=mock.MagicMock())
        p.start()
        self.addCleanup(p.stop)

    def _fan_out(self, n):
        live = {"now": 0, "max": 0}
        lock = threading.Lock()

        def fake(*a, **k):
            with lock:
                live["now"] += 1
                live["max"] = max(live["max"], live["now"])
            time.sleep(0.15)
            with lock:
                live["now"] -= 1
            return "ok"

        with mock.patch.object(client, "_fast_chat", side_effect=fake):
            threads = [threading.Thread(target=client.chat, args=("s", "u"),
                                        kwargs={"retries": 0}) for _ in range(n)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        return live["max"]

    def test_three_threads_still_reach_groq_one_at_a_time(self):
        self.assertEqual(self._fan_out(3), 1)

    @override_settings(LLM_REMOTE_PARALLEL=2)
    def test_the_number_is_a_setting_for_the_day_groq_has_a_wider_plan(self):
        self.assertEqual(self._fan_out(4), 2)

    def test_remote_only_does_not_queue_behind_the_batch(self):
        """A person waiting on the MCP search must not stand in the batch's line."""
        gate = client._remote_gate()
        gate.acquire()  # the batch is holding Groq
        try:
            done = []
            with mock.patch.object(client, "_fast_chat", return_value="ok"):
                t = threading.Thread(target=lambda: done.append(
                    client.chat("s", "u", retries=0, remote_only=True)))
                t.start()
                t.join(timeout=3)
            self.assertEqual(done, ["ok"])
        finally:
            gate.release()


# ── the pieces of a long text ───────────────────────────────────────────────
def long_text(pieces: int) -> str:
    t = testo(100 * pieces)
    assert len(whole_text.split_text(t)) >= pieces
    return t


def answer(user: str):
    """(piece number, a valid answer quoting the first sentence of that piece)."""
    m = _PEZZO.search(user)
    n, piece = int(m.group(1)), m.group(3)
    first = re.split(r"(?<=\.) ", piece.strip())[0]
    return n, {"sintesi": f"appunti {n}",
               "argomenti": [{"testo": f"Affermazione {n}", "citazione": first}]}


class PiecesTogetherTests(SimpleTestCase):
    """`read_whole` with the model faked at `ask_piece`/`ask_final`."""

    def setUp(self):
        p = mock.patch("django.db.backends.base.base.BaseDatabaseWrapper.close")
        self.close = p.start()
        self.addCleanup(p.stop)

    def _read(self, text, ask_piece, slots=3):
        finals = []

        def ask_final(block):
            finals.append(block)
            return {"summary_it": "ok"}

        def no_near_doubles(texts):
            return [[1.0 if i == j else 0.0 for j in range(len(texts))]
                    for i in range(len(texts))]

        with mock.patch.object(client, "local_slots", return_value=slots):
            _, claims = whole_text.read_whole(text, "un reel", ask_piece, ask_final,
                                              embed=no_near_doubles)
        return claims, finals[0]

    def test_answers_arriving_in_reverse_come_back_in_the_order_of_the_text(self):
        text = long_text(4)
        total = len(whole_text.split_text(text))

        def ask_piece(user):
            n, ans = answer(user)
            time.sleep(0.05 * (total - n))  # the LAST piece ends first
            return ans

        claims, block = self._read(text, ask_piece)
        self.assertEqual([c["testo"] for c in claims],
                         [f"Affermazione {i}" for i in range(1, total + 1)])
        order = [block.index(f"Pezzo {i} di {total}: appunti {i}")
                 for i in range(1, total + 1)]
        self.assertEqual(order, sorted(order))

    def test_with_one_seat_it_is_the_old_sequence_in_one_thread(self):
        threads = set()

        def ask_piece(user):
            threads.add(threading.get_ident())
            return answer(user)[1]

        self._read(long_text(3), ask_piece, slots=1)
        self.assertEqual(threads, {threading.get_ident()})
        self.close.assert_not_called()

    def test_never_more_pieces_at_once_than_seats(self):
        live = {"now": 0, "max": 0}
        lock = threading.Lock()

        def ask_piece(user):
            with lock:
                live["now"] += 1
                live["max"] = max(live["max"], live["now"])
            time.sleep(0.05)
            with lock:
                live["now"] -= 1
            return answer(user)[1]

        self._read(long_text(6), ask_piece, slots=3)
        self.assertEqual(live["max"], 3)

    def test_a_failed_piece_stops_the_ones_not_started_and_names_itself(self):
        asked = []

        def ask_piece(user):
            n, ans = answer(user)
            asked.append(n)
            if n == 1:
                raise ValueError("JSON rotto")
            time.sleep(0.3)
            return ans

        with self.assertRaises(whole_text.WholeTextError) as cm:
            self._read(long_text(6), ask_piece, slots=2)
        self.assertIn("pezzo 1 di", str(cm.exception))
        # piece 1 broke at once: its thread must not go on to piece 3 or later
        self.assertLessEqual(set(asked), {1, 2})

    def test_with_several_failures_the_lowest_piece_is_the_error_kept(self):
        text = long_text(3)
        total = len(whole_text.split_text(text))
        barrier = threading.Barrier(total)

        def ask_piece(user):
            n, _ = answer(user)
            barrier.wait(timeout=5)  # every piece is running before any breaks
            time.sleep(0.05 * (total - n))  # the highest number breaks FIRST
            raise ValueError(f"rotto {n}")

        with self.assertRaises(whole_text.WholeTextError) as cm:
            self._read(text, ask_piece, slots=total)
        self.assertIn("pezzo 1 di", str(cm.exception))

    def test_a_real_failure_beats_the_model_being_away(self):
        text = long_text(3)
        total = len(whole_text.split_text(text))
        barrier = threading.Barrier(total)

        def ask_piece(user):
            n, ans = answer(user)
            barrier.wait(timeout=5)
            if n == 1:
                raise LLMBusy("occupato")      # the LOWEST piece: the model is away
            if n == 2:
                raise ValueError("risposta rotta")
            return ans

        with self.assertRaises(whole_text.WholeTextError) as cm:
            self._read(text, ask_piece, slots=total)
        self.assertIn("pezzo 2 di", str(cm.exception))

    def test_only_the_model_being_away_passes_through_untouched(self):
        def ask_piece(user):
            n, ans = answer(user)
            if n == 2:
                raise LLMBusy("occupato")
            return ans

        with self.assertRaises(LLMBusy):
            self._read(long_text(3), ask_piece, slots=3)

    def test_each_thread_inherits_the_item_and_adds_the_piece_number(self):
        labels = {}

        def ask_piece(user):
            n, ans = answer(user)
            labels[n] = usage._item_var.get()
            return ans

        usage.set_item("reel", 7, "@medyca · ABC")
        try:
            self._read(long_text(4), ask_piece, slots=3)
            total = len(labels)
            self.assertGreater(total, 1)
            for n, item_ in labels.items():
                self.assertEqual(item_["id"], 7)
                self.assertEqual(item_["label"], f"@medyca · ABC · pezzo {n}/{total}")
            # the caller's own label is not touched by the copies
            self.assertEqual(usage._item_var.get()["label"], "@medyca · ABC")
        finally:
            usage.clear_item()

    def test_each_thread_inherits_who_is_calling(self):
        seen = []

        def ask_piece(user):
            seen.append(usage.current()["process"])
            return answer(user)[1]

        # A thread has no process-wide fallback when the scope was opened outside
        # the main thread (a job of the web server): only the copy tells it who asks.
        def in_a_web_thread():
            with usage.scope("job:upload", job_id=4):
                self._read(long_text(3), ask_piece, slots=3)

        t = threading.Thread(target=in_a_web_thread)
        t.start()
        t.join()
        self.assertEqual(set(seen), {"job:upload"})

    def test_each_thread_closes_its_database_connection(self):
        text = long_text(4)
        self._read(text, lambda u: answer(u)[1], slots=3)
        self.assertGreaterEqual(self.close.call_count, len(whole_text.split_text(text)))


class TagItemTests(SimpleTestCase):
    def tearDown(self):
        usage.clear_item()

    def test_a_long_title_gives_way_to_the_suffix(self):
        usage.set_item("article", 1, "x" * 200)
        usage.tag_item(" · pezzo 12/15")
        label = usage._item_var.get()["label"]
        self.assertEqual(len(label), 80)
        self.assertTrue(label.endswith(" · pezzo 12/15"))

    def test_without_an_item_it_does_nothing(self):
        usage.clear_item()
        usage.tag_item(" · pezzo 1/2")
        self.assertIsNone(usage._item_var.get())


# ── `_parallel` ─────────────────────────────────────────────────────────────
def item(i, long=False):
    return SimpleNamespace(id=i, shortcode=f"s{i}",
                           content_text=("x" * 9000) if long else "x" * 100)


class ParallelHelperTests(SimpleTestCase):
    def setUp(self):
        p = mock.patch("django.db.backends.base.base.BaseDatabaseWrapper.close")
        p.start()
        self.addCleanup(p.stop)

    @staticmethod
    def _run(items, fn, slots):
        with mock.patch.object(client, "local_slots", return_value=slots):
            return list(enrich_agent._parallel(items, fn))

    def test_results_come_as_they_are_ready_not_as_they_started(self):
        def fn(it):
            time.sleep(0.4 if it.id == 0 else 0.01)
            return it.id

        out = self._run([item(i) for i in range(3)], fn, slots=3)
        self.assertEqual(out[-1][0].id, 0)          # the slow first one comes last
        self.assertEqual(sorted(r for _, r, _ in out), [0, 1, 2])

    def test_one_seat_keeps_the_given_order_in_the_calling_thread(self):
        threads, order = set(), []

        def fn(it):
            threads.add(threading.get_ident())
            order.append(it.id)

        self._run([item(2, long=True), item(0), item(1)], fn, slots=1)
        self.assertEqual(order, [2, 0, 1])
        self.assertEqual(threads, {threading.get_ident()})

    def test_short_contents_first_together_then_long_ones_alone(self):
        order = []
        live = {"now": 0, "max_short": 0, "max_long": 0}
        lock = threading.Lock()

        def fn(it):
            kind = "max_long" if len(it.content_text) > 8000 else "max_short"
            with lock:
                order.append(it.id)
                live["now"] += 1
                live[kind] = max(live[kind], live["now"])
            time.sleep(0.05)
            with lock:
                live["now"] -= 1

        items = [item(0, long=True), item(1), item(2), item(3, long=True),
                 item(4), item(5)]
        self._run(items, fn, slots=3)
        self.assertEqual(set(order[:4]), {1, 2, 4, 5})     # the short ones first
        self.assertEqual(order[4:], [0, 3])                # then the long, in order
        self.assertEqual(live["max_short"], 3)
        self.assertEqual(live["max_long"], 1)

    def test_the_flag_lets_the_running_finish_and_does_not_start_the_rest(self):
        started = []

        def fn(it):
            started.append(it.id)
            if it.id == 0:
                time.sleep(0.4)
                return "finished"
            raise LLMBusy("occupato")

        out = self._run([item(i) for i in range(5)], fn, slots=2)
        by_id = {it.id: (res, exc) for it, res, exc in out}
        self.assertEqual(by_id[0], ("finished", None))        # recorded, not thrown away
        for i in (1, 2, 3, 4):
            self.assertIsInstance(by_id[i][1], LLMBusy)       # deferred
        self.assertEqual(set(started), {0, 1})                # 2, 3, 4 never started
        self.assertEqual(len(out), 5)                          # every item accounted for

    def test_the_flag_works_with_one_seat_too(self):
        started = []

        def fn(it):
            started.append(it.id)
            if it.id == 1:
                raise LLMBusy("occupato")

        out = self._run([item(i) for i in range(5)], fn, slots=1)
        self.assertEqual(started, [0, 1])
        self.assertEqual([type(e).__name__ if e else None for _, _, e in out],
                         [None, "LLMBusy", "LLMBusy", "LLMBusy", "LLMBusy"])

    def test_the_error_of_the_claims_raises_the_flag_too(self):
        """`_enrich_then_claims` RETURNS the error of the claims: the analysis is
        saved, but the model is away, so the others must not start."""
        started = []

        def fn(it):
            started.append(it.id)
            return None, (LLMBusy("occupato") if it.id == 0 else None)

        out = self._run([item(i) for i in range(4)], fn, slots=1)
        self.assertEqual(started, [0])
        self.assertEqual(len(out), 4)
        self.assertTrue(all(isinstance(e, LLMBusy) for _, _, e in out[1:]))

    def test_a_real_error_is_the_items_own_and_stops_nothing(self):
        def fn(it):
            if it.id == 1:
                raise ValueError("risposta rotta")
            return it.id

        out = self._run([item(i) for i in range(4)], fn, slots=2)
        errs = {it.id: e for it, _, e in out}
        self.assertIsInstance(errs[1], ValueError)
        self.assertEqual([errs[i] for i in (0, 2, 3)], [None, None, None])


# ── the embedder ────────────────────────────────────────────────────────────
class EmbedderLockTests(SimpleTestCase):
    def test_three_threads_load_the_model_once(self):
        loads = []

        class Fake:
            def __init__(self, name):
                loads.append(name)
                time.sleep(0.2)

        fake_module = types.ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = Fake
        saved = cluster_agent._embedder
        cluster_agent._embedder = None
        got = []
        try:
            with mock.patch.dict(sys.modules, {"sentence_transformers": fake_module}):
                threads = [threading.Thread(
                    target=lambda: got.append(cluster_agent._get_embedder()))
                    for _ in range(3)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
        finally:
            cluster_agent._embedder = saved
        self.assertEqual(len(loads), 1)
        self.assertEqual(len({id(g) for g in got}), 1)
