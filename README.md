# Dependency Steward

A dependency upgrade engineer for an operator-owned public React/TypeScript repository: authorize an exact plan, establish a clean baseline, try one dependency update, attempt one bounded source repair if needed, and publish a draft PR only with passing validation evidence.

**Status:** local implementation under verification. Cloud deployment and the live model-assisted repair demonstration are still pending. See [implementation status](docs/IMPLEMENTATION_STATUS.md). Provider mocks in the test suite do not substitute for live execution evidence.

## Project resources

- GCP project: `dependency-steward-zelalem` (separate from existing projects).
- Owned public fixture: https://github.com/zolateklu/dependency-steward
- Approved design: [solution design](docs/SOLUTION_DESIGN.md).

## Local setup

Use Python 3.12+, Node 24.6.0, npm 11.8.0, and uv. Run these commands from this directory:

```sh
cd backend
uv sync --group dev --python python3.12
# A local .env has already been created; do not overwrite it.
# For a fresh checkout only: cp .env.example .env
```

Edit `backend/.env` locally. Set `GITHUB_TOKEN` to a fine-grained PAT for only the demo repository, with Contents, Pull requests, and Actions read/write. Set `GEMINI_API_KEY` for the intended free-tier project and `SLACK_WEBHOOK` for notifications. The operator and worker tokens have already been generated locally. Never commit or share `.env`.

Build the dashboard:

```sh
cd frontend
npm ci --ignore-scripts
npm run build
```

Start the API from `backend/`:

```sh
uv run uvicorn steward.app:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and use the local `OPERATOR_TOKEN` to sign in. Run the local coordinator from a second terminal in `backend/`:

```sh
uv run python -m steward.worker
```

The coordinator checks periodically; active upgrade reconciliation is limited to one five-minute tick. SQLite is local development storage only. GCP deployment uses Firestore.

## Verify

```sh
# From backend/
uv run ruff check steward tests
uv run pytest -q

# From frontend/
npm run build

# From the repository root
npm ci --ignore-scripts
npm run --ignore-scripts test:ci
npm run --ignore-scripts typecheck
npm run --ignore-scripts build
```

The demo's deliberately older Zod version provides a real compatibility exercise. Its tests must remain unchanged through upgrades. The GitHub-hosted workflow and helper are authored under `runner/` and copied into the fixture's `.github/workflows/` and `.steward/` directories. Keep the copies synchronized before updating the fixture.

## Boundaries

One public owned repository, one direct npm dependency per job, one repair attempt. No default-branch pushes, merges, deployments of repository code, test edits, or model-generated shell commands. A passing check covers the configured test profile, not universal upgrade safety. See the design and implementation status for remaining verification and delivery work.
