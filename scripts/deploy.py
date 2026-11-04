"""Deploy the already-built image. Secrets are referenced by resource name, never by value."""

import argparse
import json
import subprocess
from pathlib import Path

PROJECT = "dependency-steward-zelalem"
REGION = "us-central1"
RUNTIME = f"steward-runtime@{PROJECT}.iam.gserviceaccount.com"
SCHEDULER = f"steward-scheduler@{PROJECT}.iam.gserviceaccount.com"
ROOT = Path(__file__).resolve().parents[1]


def run(args, check=True):
    result = subprocess.run(
        ["gcloud", *args, f"--project={PROJECT}", "--quiet"],
        capture_output=True,
        text=True,
        check=check,
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("build_id")
    args = parser.parse_args()
    image = f"{REGION}-docker.pkg.dev/{PROJECT}/steward/app:{args.build_id}"
    secrets = ",".join(
        f"{key.upper()}=steward-{key.replace('_', '-')}:latest"
        for key in (
            "operator_token",
            "worker_token",
            "github_token",
            "gemini_api_key",
            "slack_webhook",
        )
    )
    urls = {}
    for role in ("web", "worker"):
        name = "dependency-steward" if role == "web" else "dependency-steward-worker"
        run(
            [
                "run",
                "deploy",
                name,
                f"--image={image}",
                f"--region={REGION}",
                f"--service-account={RUNTIME}",
                "--min-instances=0",
                "--max-instances=1",
                "--concurrency=1",
                "--memory=512Mi",
                "--cpu=1",
                "--timeout=180",
                "--cpu-throttling",
                "--allow-unauthenticated"
                if role == "web"
                else "--no-allow-unauthenticated",
                f"--set-secrets={secrets}",
                f"--set-env-vars=FIRESTORE_PROJECT={PROJECT},GITHUB_REPO=zolateklu/dependency-steward,APP_ROLE={role}",
            ]
        )
        urls[role] = run(
            [
                "run",
                "services",
                "describe",
                name,
                f"--region={REGION}",
                "--format=value(status.url)",
            ]
        ).stdout.strip()
        print(f"Deployed {role}: {urls[role]}", flush=True)
    run(
        [
            "run",
            "services",
            "add-iam-policy-binding",
            "dependency-steward-worker",
            f"--region={REGION}",
            f"--member=serviceAccount:{SCHEDULER}",
            "--role=roles/run.invoker",
            "--condition=None",
        ]
    )
    exists = (
        run(
            [
                "scheduler",
                "jobs",
                "describe",
                "steward-reconcile",
                f"--location={REGION}",
            ],
            False,
        ).returncode
        == 0
    )
    run(
        [
            "scheduler",
            "jobs",
            "update" if exists else "create",
            "http",
            "steward-reconcile",
            f"--location={REGION}",
            "--schedule=*/5 * * * *",
            "--time-zone=Africa/Addis_Ababa",
            "--http-method=POST",
            f"--uri={urls['worker']}/internal/tick",
            f"--oidc-service-account-email={SCHEDULER}",
            f"--oidc-token-audience={urls['worker']}",
            "--attempt-deadline=180s",
            "--max-retry-attempts=1",
        ]
    )
    artifact = ROOT / "artifacts" / "deployment.json"
    scheduler_state = run(
        [
            "scheduler",
            "jobs",
            "describe",
            "steward-reconcile",
            f"--location={REGION}",
            "--format=value(state)",
        ]
    ).stdout.strip()
    if scheduler_state == "PAUSED":
        run(
            ["scheduler", "jobs", "resume", "steward-reconcile", f"--location={REGION}"]
        )
    artifact.parent.mkdir(exist_ok=True)
    artifact.write_text(
        json.dumps(
            {"project": PROJECT, "region": REGION, "image": image, **urls}, indent=2
        )
    )
    print("Private worker and five-minute OIDC scheduler configured.", flush=True)


if __name__ == "__main__":
    main()
