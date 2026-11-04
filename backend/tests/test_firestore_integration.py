"""Opt-in regression against the real Firestore CAS API, using the operator's gcloud login."""

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from google.oauth2.credentials import Credentials

from steward.config import Settings
from steward.store import Conflict, FirestoreStore


@pytest.mark.skipif(os.getenv("RUN_FIRESTORE_INTEGRATION") != "1", reason="Requires explicit live GCP access")
def test_real_firestore_rejects_concurrent_stale_writer():
    settings = Settings(_env_file=Path(__file__).resolve().parents[1] / ".env")
    if not settings.firestore_project:
        pytest.fail("Set FIRESTORE_PROJECT for the live integration test")
    token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
    store = FirestoreStore(
        settings.firestore_project, settings.firestore_collection, Credentials(token=token)
    )
    revision, _ = store.get("cas-live-verification")
    revision = store.put("cas-live-verification", revision, {"purpose": "concurrent-write regression"})

    def attempt(writer):
        try:
            store.put("cas-live-verification", revision, {"writer": writer})
            return "written"
        except Conflict:
            return "conflict"

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(attempt, [1, 2]))
    assert sorted(outcomes) == ["conflict", "written"]
