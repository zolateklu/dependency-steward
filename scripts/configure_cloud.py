"""Upload local secrets without putting their values in command arguments or tool output."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from steward.config import Settings

PROJECT = "dependency-steward-zelalem"
RUNTIME = f"steward-runtime@{PROJECT}.iam.gserviceaccount.com"
ROOT = Path(__file__).resolve().parents[1]


def command(args, data=None, check=True):
    return subprocess.run(
        ["gcloud", *args, f"--project={PROJECT}", "--quiet"],
        input=data,
        text=True,
        capture_output=True,
        check=check,
    )


def main():
    settings = Settings(_env_file=ROOT / "backend/.env")
    settings.require_ready()
    for key in (
        "operator_token",
        "worker_token",
        "github_token",
        "gemini_api_key",
        "slack_webhook",
    ):
        value = getattr(settings, key)
        if not value:
            raise ValueError(f"Missing required local setting: {key}")
        name = "steward-" + key.replace("_", "-")
        exists = command(["secrets", "describe", name], check=False).returncode == 0
        if not exists:
            command(["secrets", "create", name, "--replication-policy=automatic"])
        command(["secrets", "versions", "add", name, "--data-file=-"], data=value)
        command(
            [
                "secrets",
                "add-iam-policy-binding",
                name,
                f"--member=serviceAccount:{RUNTIME}",
                "--role=roles/secretmanager.secretAccessor",
                "--condition=None",
            ]
        )
        print(f"Configured Secret Manager: {name}", flush=True)
    (ROOT / "artifacts").mkdir(exist_ok=True)
    print("Secret values were never printed or written to deployment files.")


if __name__ == "__main__":
    main()
