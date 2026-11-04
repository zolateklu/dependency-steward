"""Local app using the operator's existing gcloud CLI login without replacing global ADC."""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx
import uvicorn
from google.auth.credentials import Credentials
from google.auth.exceptions import RefreshError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from steward.app import create_app
from steward.config import Settings
from steward.providers import OSV, Gemini, GitHub, Registry
from steward.service import Steward
from steward.store import FirestoreStore, SQLStore


class GcloudCredentials(Credentials):
    def refresh(self, request):
        result = subprocess.run(
            [
                "gcloud",
                "config",
                "config-helper",
                "--force-auth-refresh",
                "--format=json",
            ],
            text=True,
            capture_output=True,
        )
        if result.returncode:
            raise RefreshError("Refresh your local gcloud login with gcloud auth login")
        credential = json.loads(result.stdout)["credential"]
        self.token = credential["access_token"]
        self.expiry = datetime.fromisoformat(
            credential["token_expiry"].replace("Z", "+00:00")
        ).replace(tzinfo=None)


def main():
    settings = Settings(_env_file=ROOT / "backend/.env").model_copy(
        update={"session_cookie_secure": False}
    )
    client = httpx.AsyncClient(timeout=60)
    store = (
        FirestoreStore(
            settings.firestore_project,
            settings.firestore_collection,
            GcloudCredentials(),
        )
        if settings.firestore_project
        else SQLStore(settings.database_url)
    )
    service = Steward(
        settings,
        store,
        GitHub(settings.github_token, settings.github_repo, client),
        Registry(client),
        OSV(client),
        Gemini(settings.gemini_api_key, settings.gemini_model, client),
    )
    uvicorn.run(create_app(settings, service), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
