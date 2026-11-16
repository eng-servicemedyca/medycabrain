"""
Migration 0028 (`full_text_status`).

A row whose text (a reel: transcript AND caption) fitted in the old cut was read whole: `done`. A longer one was
made on its beginning only: `pending`, to be redone. The cut is 6 000 characters
for a document and 3 000 for a reel's transcript and 1 500 for its caption; a text of exactly that many
characters is inside it. It must also walk back.
"""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("core", "0027_drop_batchrun")]
AFTER = [("core", "0028_full_text_status")]


class FullTextStatusMigrationTests(TransactionTestCase):
    def _migrate(self, targets):
        ex = MigrationExecutor(connection)
        ex.migrate(targets)
        return ex.loader.project_state(targets).apps

    def tearDown(self):
        ex = MigrationExecutor(connection)
        ex.migrate(ex.loader.graph.leaf_nodes())

    def test_short_texts_are_done_and_long_ones_pending(self):
        apps = self._migrate(BEFORE)
        acct = apps.get_model("core", "TrackedAccount").objects.create(username="a")
        Reel, Transcript = apps.get_model("core", "Reel"), apps.get_model("core", "Transcript")
        Doc = apps.get_model("core", "KnowledgeDocument")
        # A caption over 1 500 only counts for a reel WITH speech (40+ characters).
        caps = {"LONGCAP": 1501, "EDGECAP": 1500, "CAPONLY": 2000, "CAP39": 2000,
                "CAP40": 2000}
        for code, n in (("NOSPEECH", None), ("EDGE", 3000), ("SHORT", 100), ("LONG", 3001),
                        ("LONGCAP", 100), ("EDGECAP", 100), ("CAPONLY", None),
                        ("CAP39", 39), ("CAP40", 40)):
            r = Reel.objects.create(account=acct, shortcode=code,
                                    caption="c" * caps.get(code, 10))
            if n is not None:
                Transcript.objects.create(reel=r, text="a" * n)
        for i, n in enumerate((0, 6000, 6001, 20000)):
            Doc.objects.create(source_url=f"https://x.example/{i}",
                               content_text="a" * n)

        apps = self._migrate(AFTER)
        Reel, Doc = apps.get_model("core", "Reel"), apps.get_model("core", "KnowledgeDocument")
        got = dict(Reel.objects.values_list("shortcode", "full_text_status"))
        self.assertEqual(got, {"NOSPEECH": "done", "EDGE": "done",
                               "SHORT": "done", "LONG": "pending",
                               # the old analysis cut the caption at 1 500 too
                               "LONGCAP": "pending", "EDGECAP": "done",
                               # no speech: the caption is now read whole
                               "CAPONLY": "done", "CAP39": "done",
                               "CAP40": "pending"})
        got = {len(c): s for c, s in Doc.objects.values_list("content_text", "full_text_status")}
        self.assertEqual(got, {0: "done", 6000: "done", 6001: "pending", 20000: "pending"})

    def test_goes_back(self):
        self._migrate(AFTER)
        apps = self._migrate(BEFORE)
        self.assertFalse(any(f.name == "full_text_status"
                             for f in apps.get_model("core", "Reel")._meta.get_fields()))
