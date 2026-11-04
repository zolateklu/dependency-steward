# Dependency Steward

A dependency upgrade engineer for an operator-owned public React/TypeScript repository. Authorize an exact plan, establish a clean baseline, try one direct dependency update, attempt one bounded source repair if required, and receive a draft PR only after validation passes.

- **App:** https://dependency-steward-an5pneq45q-uc.a.run.app
- **Source and reproducible fixture:** https://github.com/zolateklu/dependency-steward
- **Design:** [solution design](docs/SOLUTION_DESIGN.md)
- **Observed results:** [live verification](docs/VERIFICATION.md)
- **Recording guide:** [video walkthrough](docs/VIDEO_WALKTHROUGH.md)

Sign in with the `OPERATOR_TOKEN` from your local `backend/.env`. Secrets belong only in that ignored local file and GCP Secret Manager; none are bundled in the frontend.

## What it does

The queue uses GitHub, npm, and OSV to show exact installed versions, published targets, advisories, dependency paths, and deterministic priorities. A plan records the repository commit, exact target version, reviewed source files, pinned toolchain, test commands, and authorization to publish a draft PR.

A trusted GitHub Actions workflow runs the baseline and candidate on separate clean VMs. If the candidate introduces a failure, Gemini can propose one bounded source edit. The backend validates the edit paths, hashes, citations, and size, then tests the exact candidate again. Missing evidence, baseline failures, new advisories, stale commits, cancellation, and failed checks block publication.

The dashboard shows progress, install/test/typecheck/build logs, source differences, and PR or blocker results. A private Cloud Run worker continues while the browser is closed. Cloud Scheduler reconciles jobs every five minutes and triggers the daily scan at 09:00 Africa/Addis_Ababa. Slack receives deduplicated notifications. A human reviews and merges.

## Local setup

Requirements: Python 3.12+, Node 24.6.0, npm 11.8.0, uv, and an authenticated gcloud CLI when using Firestore.

From the repository root:

```sh
uv sync --project backend --group dev --python python3.12
npm ci --prefix frontend --ignore-scripts
npm run build --prefix frontend
```

The local `.env` already exists on the author's machine. For a fresh checkout, copy `backend/.env.example` to `backend/.env`, generate two different tokens with `secrets.token_urlsafe(32)`, and supply the GitHub/Gemini/Slack settings. The GitHub fine-grained token needs only this repository and Contents, Pull requests, and Actions read/write.

```sh
backend/.venv/bin/python scripts/dev.py
```

Open http://127.0.0.1:8000. This development entry point refreshes your existing gcloud CLI credentials without changing global application-default credentials or another project's service-account impersonation. Set `FIRESTORE_PROJECT` to your intended project; leave it blank to use SQLite locally.

For local worker ticks, run this from `backend/` in another terminal:

```sh
uv run python -m steward.worker
```

For frontend development, run `npm run dev --prefix frontend`; Vite proxies API requests to the local backend. SQLite and local filesystems never hold authoritative cloud job state.

## Tests

From the repository root:

```sh
backend/.venv/bin/ruff check backend/steward backend/tests
backend/.venv/bin/pytest -q backend/tests
npm run build --prefix frontend
npm ci --ignore-scripts
npm run --ignore-scripts test:ci
npm run --ignore-scripts typecheck
npm run --ignore-scripts build
```

Policy/state/provider tests include unsafe paths, stale source hashes, oversized repairs, unsafe archives, publication gates, lost-update prevention, idempotent dispatch/publication, cancellation, baseline failure, snooze changes, request budgets, and authenticated API boundaries. Mocked providers exercise failures; [live runs](docs/VERIFICATION.md) separately establish actual execution.

## Cloud deployment

The dedicated project is `dependency-steward-zelalem`, region `us-central1`. It has Firestore Native, a `steward` Artifact Registry repository, a `steward-runtime` service account, a `steward-build` image builder, and a `steward-scheduler` invoker. Existing projects and the selected gcloud configuration are unchanged.

The runtime has Datastore User and per-secret Secret Accessor permissions. The builder has Artifact Registry Writer, Storage Object Viewer, and Logs Writer. The scheduler has Cloud Run Invoker on the private worker. Cloud Run instances scale to zero and are capped at one per service.

```sh
# Upload configured local secrets without placing values in command arguments.
backend/.venv/bin/python scripts/configure_cloud.py

# Build; use the returned build ID after it succeeds.
gcloud builds submit --config=cloudbuild.yaml \
  --service-account=projects/dependency-steward-zelalem/serviceAccounts/steward-build@dependency-steward-zelalem.iam.gserviceaccount.com \
  --project=dependency-steward-zelalem

backend/.venv/bin/python scripts/deploy.py BUILD_ID
```

These scripts target the existing dedicated assessment project. For another deployment, provision the same resources and update the project/region constants. The public service uses `APP_ROLE=web`; its worker route is disabled. The `APP_ROLE=worker` service requires Cloud Run IAM authentication, with Scheduler OIDC at the edge. Secrets are referenced by name, and Firestore stores plans, state, events, and deduplication keys. The five-minute cadence can add visible stage latency.

## Fixture and scope

The root React invitation app intentionally uses older Zod 3.24.2. Its four tests protect the validation contract; a Zod 4 update requires adapting `ZodError.errors` to `issues`. Tests remain unchanged through upgrades. See [fixture notes](docs/FIXTURE.md). The execution helper and workflow are authored under `runner/` and copied to `.steward/` and `.github/workflows/`; keep these copies synchronized.

One public owned repository, one direct npm dependency, one repair attempt. No automatic merges, default-branch pushes, repository-code execution in Cloud Run, test edits, or model-generated shell commands. Passing checks establish configured coverage only. Private customer repositories and stronger hostile-code isolation are production extensions, outside this prototype.
