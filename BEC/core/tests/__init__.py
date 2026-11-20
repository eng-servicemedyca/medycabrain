"""Tests must never hold the REAL pipeline lock (`/tmp/medycabrain-pipeline.lock`) or the real Ollama seats:
a cron round starting at that moment would be refused, and a real round running
would fail the tests. Every test process gets a lock file of its own, removed
when it ends (the suite used to leave an empty one in /tmp)."""

import atexit
import os
import shutil
import tempfile

from django.conf import settings

_lock_dir = tempfile.mkdtemp(prefix="medycabrain-test-")
settings.PIPELINE_LOCK_PATH = os.path.join(_lock_dir, "round.lock")
atexit.register(shutil.rmtree, _lock_dir, ignore_errors=True)

# Same for the local model's seats: without this every test that goes through
# `_ollama_slot` created and locked the real /tmp/medycabrain-ollama.lock(.N)
# and `.priority`, which the CRM shares.
settings.OLLAMA_LOCK_PATH = os.path.join(_lock_dir, "ollama.lock")
