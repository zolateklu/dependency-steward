# Implementation status · 4 November 2026

## Implemented and deployed

- React/TypeScript operator dashboard: sign-in, live ranked queue, exact plan authorization, run timeline, install/test/typecheck/build evidence, unified file differences, source-linked release context, cancellation, acknowledgement, and 1/7/30-day snooze.
- FastAPI app plus a private Cloud Run worker. The public app disables its worker route. Cloud Run IAM verifies Scheduler OIDC requests.
- Durable Firestore state, immutable plans, per-repository job reservation, compare-and-set transitions, dispatch intents, bounded repair requests, request budgets, and publication/notification deduplication.
- Real GitHub, npm, OSV, Gemini, GitHub Actions, and Slack integrations. Runtime secrets are in Secret Manager and are excluded from the repository and frontend.
- Reviewed GitHub-hosted baseline, upgrade, and repair jobs. Repository scripts run on isolated VMs, never in Cloud Run. Source edits are path/hash/size checked; tests and workflows are protected.
- The full application and owned root React fixture share https://github.com/zolateklu/dependency-steward. No PR is automatically merged.
- Separate GCP project `dependency-steward-zelalem`, Firestore in `us-central1`, two Cloud Run services, and a five-minute Scheduler job. Existing projects and the selected gcloud project remain unchanged.

## Verification

See [live verification](VERIFICATION.md) for exact execution links and observed outcomes. Automated tests cover the publication policy and failure states; live provider runs establish actual upgrade behavior. The Firestore concurrency regression also runs against the real service when explicitly enabled.

The initial Cloud Run transaction path exposed an expired-transaction error during a scheduled write. It was replaced with server-enforced update-time preconditions; a concurrent-writer check verified that exactly one write succeeds. The corrected version is deployed, with Scheduler resumed.

## Submission work remaining

Record and review the final assessment video with the author's narration. [The walkthrough script](VIDEO_WALKTHROUGH.md) covers the product, live results, frontend, and backend. A script is not a completed recording. No submission email has been sent.

## Prototype limits

One owned public repository, one direct npm dependency per upgrade, one repair attempt, and a single operator token. Cloud orchestration reconciles every five minutes, so stages can have scheduling latency. Passing checks establish the fixture's configured coverage, not universal safety. Private customer repositories, multi-user auth, broader ecosystems, and stronger isolation for hostile repositories are production extensions.
