"""Exercise the owned assessment fixture with live APIs; never prints credentials."""

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import httpx
from google.oauth2.credentials import Credentials

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from steward.config import Settings
from steward.domain import PlanRequest, StartRequest
from steward.providers import OSV, Gemini, GitHub, Registry
from steward.service import Steward
from steward.store import FirestoreStore


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["scan", "start", "tick", "status"])
    parser.add_argument("--package", default="zod")
    parser.add_argument("--target")
    parser.add_argument("--job")
    args = parser.parse_args()
    settings = Settings(_env_file=ROOT / "backend/.env")
    token = subprocess.check_output(
        ["gcloud", "auth", "print-access-token"], text=True
    ).strip()
    store = FirestoreStore(
        settings.firestore_project,
        settings.firestore_collection,
        Credentials(token=token),
    )
    async with httpx.AsyncClient(timeout=60) as client:
        svc = Steward(
            settings,
            store,
            GitHub(settings.github_token, settings.github_repo, client),
            Registry(client),
            OSV(client),
            Gemini(settings.gemini_api_key, settings.gemini_model, client),
        )
        if args.action == "scan":
            result = await svc.scan()
            print(
                json.dumps(
                    {
                        "packages": result["scan"]["package_count"],
                        "complete": result["scan"]["complete"],
                        "candidates": [
                            {k: c[k] for k in ("name", "version", "target", "score")}
                            for c in result["visible_candidates"]
                        ],
                    },
                    indent=2,
                )
            )
            return
        if args.action == "start":
            plan = await svc.plan(PlanRequest(package=args.package, target=args.target))
            job = await svc.start(
                StartRequest(
                    plan_id=plan["id"], plan_hash=plan["hash"], publish_draft=True
                )
            )
            print(
                "Authorized owned-fixture validation:",
                job["id"],
                plan["package"],
                plan["installed"],
                "→",
                plan["target"],
                flush=True,
            )
            await svc.reconcile(job["id"], force=True)
            job_id = job["id"]
        else:
            job_id = args.job
            if not job_id:
                _, repo = store.get("repository")
                job_id = (
                    (repo or {}).get("active", {}).get("id")
                    if (repo or {}).get("active")
                    else None
                )
            if args.action == "tick" and job_id:
                await svc.reconcile(job_id, force=True)
        if job_id:
            _, job = store.get(f"job-{job_id}")
            print(
                json.dumps(
                    {
                        k: job.get(k)
                        for k in (
                            "id",
                            "state",
                            "attempt",
                            "model_calls",
                            "run_url",
                            "pr_url",
                        )
                    },
                    indent=2,
                )
            )
            print("Latest event:", job["events"][-1]["message"])
        else:
            print("No active upgrade.")


if __name__ == "__main__":
    asyncio.run(main())
