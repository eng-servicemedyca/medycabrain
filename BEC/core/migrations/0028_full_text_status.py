# Adds `full_text_status` to reels and knowledge_documents: did the analysis in
# force read the WHOLE text?
#
# Until 2026-11-16 the summary read the first 6 000 characters of a document and
# the first 3 000 of a reel's transcript (the claims 8 000 for documents). Those
# whose text fits inside the old cut were read whole: `done`. The others were
# made on the beginning only: `pending`, to be redone. The numbers are written
# here and not imported from the agents: a migration must keep meaning what it
# meant the day it ran, whatever the agents read later.
#
# About 3 900 rows, a few seconds. Adding the column does not lock the table for
# long (the default is a constant). Reverse: the column is dropped.

import django.db.models.functions
from django.db import migrations, models

OLD_CUT_DOCUMENT = 6000
OLD_CUT_TRANSCRIPT = 3000


def mark_already_whole(apps, schema_editor):
    Reel = apps.get_model("core", "Reel")
    KnowledgeDocument = apps.get_model("core", "KnowledgeDocument")
    long_reels = (Reel.objects
                  .annotate(n=django.db.models.functions.Length("transcript__text"))
                  .filter(n__gt=OLD_CUT_TRANSCRIPT).values("pk"))
    Reel.objects.exclude(pk__in=long_reels).update(full_text_status="done")
    long_docs = (KnowledgeDocument.objects
                 .annotate(n=django.db.models.functions.Length("content_text"))
                 .filter(n__gt=OLD_CUT_DOCUMENT).values("pk"))
    KnowledgeDocument.objects.exclude(pk__in=long_docs).update(
        full_text_status="done")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0027_drop_batchrun"),
    ]

    operations = [
        migrations.AddField(
            model_name="reel",
            name="full_text_status",
            field=models.CharField(
                choices=[("pending", "pending"), ("done", "done"),
                         ("failed", "failed"), ("skipped", "skipped")],
                default="pending", max_length=16),
        ),
        migrations.AddField(
            model_name="knowledgedocument",
            name="full_text_status",
            field=models.CharField(
                choices=[("pending", "pending"), ("done", "done"),
                         ("failed", "failed"), ("skipped", "skipped")],
                default="pending", max_length=16),
        ),
        migrations.RunPython(mark_already_whole, migrations.RunPython.noop),
    ]
