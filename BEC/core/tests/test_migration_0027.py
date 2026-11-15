"""
Migration 0027 (drop `batch_runs` and the `batched` state).

The point of the test is the refusal: dropping the choice while a row still sits
in `batched` would strand an item nothing will ever collect, so the migration
must stop and say so. And it must walk back (`migrate core 0026`) in structure.
"""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("core", "0026_llmcall_stagerun")]
AFTER = [("core", "0027_drop_batchrun")]


def _tables():
    with connection.cursor() as cur:
        return set(connection.introspection.table_names(cur))


class DropBatchRunMigrationTests(TransactionTestCase):
    def _migrate(self, targets):
        ex = MigrationExecutor(connection)
        ex.migrate(targets)
        return ex.loader.project_state(targets).apps

    def tearDown(self):
        # leave the test database at the latest migration for the next test
        ex = MigrationExecutor(connection)
        ex.migrate(ex.loader.graph.leaf_nodes())

    def test_goes_forward_and_back(self):
        apps = self._migrate(BEFORE)
        apps.get_model("core", "BatchRun").objects.create(
            kind="reel_enrich", batch_id="b1", status="collected")
        self.assertIn("batch_runs", _tables())

        self._migrate(AFTER)
        self.assertNotIn("batch_runs", _tables())

        # back: the table returns, empty (the rows live in the exported file)
        apps = self._migrate(BEFORE)
        self.assertIn("batch_runs", _tables())
        self.assertEqual(apps.get_model("core", "BatchRun").objects.count(), 0)

    def test_refuses_while_something_is_still_batched(self):
        apps = self._migrate(BEFORE)
        acct = apps.get_model("core", "TrackedAccount").objects.create(username="a")
        apps.get_model("core", "Reel").objects.create(
            account=acct, shortcode="S1", enrich_status="batched")
        try:
            with self.assertRaisesRegex(RuntimeError, "batched"):
                self._migrate(AFTER)
            # nothing was dropped: the refusal came before any schema change
            self.assertIn("batch_runs", _tables())
        finally:
            # tearDown walks forward again, which the stuck row would refuse
            apps.get_model("core", "Reel").objects.all().delete()
