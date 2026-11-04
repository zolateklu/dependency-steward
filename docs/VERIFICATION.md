# Live verification · 4 November 2026

## Resources

- App: https://dependency-steward-an5pneq45q-uc.a.run.app
- Source and owned fixture: https://github.com/zolateklu/dependency-steward
- GCP project: `dependency-steward-zelalem`; Firestore Native in `us-central1`.
- Worker: separate private Cloud Run service; anonymous requests return HTTP 403.
- Scheduler: `steward-reconcile`, `*/5 * * * *`, Africa/Addis_Ababa, authenticated with the scheduler service account's OIDC token.

## Observed checks

- GitHub runtime token reads the configured repository and execution workflow.
- Gemini's configured `gemini-3.5-flash-lite` model is available and generates responses.
- Slack connection test delivered with HTTP 200 / `ok` after the operator authorized test and demo messages.
- Firestore read/write and job-prefix queries work. The cloud app reads jobs created through the local verification harness, demonstrating shared durable state.
- Live scan inspected 68 lockfile entries and produced six update candidates, including a Zod advisory with CVSS 8.2.
- Public app health: HTTP 200. Anonymous dashboard: HTTP 401. Public app worker route: HTTP 404. Authenticated dashboard: HTTP 200.
- Authenticated private worker invocation: HTTP 200. Scheduler invocation also succeeded.
- Backend policy/provider/state suite: 32 passing tests when live Firestore integration is enabled (31 pass and one is skipped in ordinary CI). The real CAS test allows exactly one concurrent writer and rejects the stale writer. Fixture: four passing tests, passing typecheck and build. Frontend production build passes.

## Compatible upgrade

- Job: `1edbc3e049233e5cea1c7c5a`.
- Zod 3.24.2 → 3.25.76, authorized through the dashboard.
- [Actions baseline and candidate](https://github.com/zolateklu/dependency-steward/actions/runs/41885825552).
- Four tests passed before and after; typecheck and build passed. No model repair was needed.
- [Draft PR #1](https://github.com/zolateklu/dependency-steward/pull/1) contains only `package.json` and `package-lock.json`.

## Breaking upgrade

- Job: `a877eed8fe13fdb414c65544`.
- Zod 3.24.2 → 4.6.7.
- [Initial baseline and failing upgrade](https://github.com/zolateklu/dependency-steward/actions/runs/41886267691).
- One Gemini request proposed a source edit to `src/schema.ts`: use `ZodError.issues` instead of `.errors`, with an explicit issue type.
- [Repair run](https://github.com/zolateklu/dependency-steward/actions/runs/41886680019) passed the required checks.
- [Draft PR #2](https://github.com/zolateklu/dependency-steward/pull/2) was published by the corrected cloud worker after resuming the persisted job. One repair attempt and one Gemini request were used; all four tests, typecheck, and build passed.
- The candidate removes `GHSA-mrhx-c7xc-m3w5` and introduces no new advisory. Tests and workflow files remain unchanged.

## Recovery and controls

- A scheduled Cloud Run write exposed an expired Firestore transaction. The store now uses atomic update-time preconditions instead of transaction handles. The concurrent-writer regression passed against the real service, and the fixed cloud worker resumed the existing publishing job and delivered PR #2 without rerunning Gemini or the workflow.
- The Scheduler is enabled with OIDC on its five-minute cadence. Explicit Scheduler triggers were also used during verification; the final publication used the deployed private worker.
- A cloud API snooze survived a subsequent live scan. No duplicate scan notifications were created, and the original snooze state was restored after the test.
- Replaying completed jobs leaves their existing PR and notification keys intact. Queued cancellation job `80e8af5646eeb82b5a44909b` never dispatched a workflow or created a PR; replaying its tick created no duplicate. Both upgrade completion notifications were delivered to Slack.

## Interpretation

The initial compatible workflow and diagnosis were accelerated using explicit verification-harness ticks; the production cadence remains five minutes. Both upgrade tests use real GitHub-hosted execution, npm packages, OSV data, and live Gemini for the repair. Mocked provider responses are used only in the automated policy/state tests.

No PR has been merged and the deliberately old fixture remains on the default branch for reproducible demonstrations. Passing checks establish this fixture's configured coverage only. The video walkthrough still needs to be recorded; its script is in `VIDEO_WALKTHROUGH.md`.

## Persistent sign-in follow-up

Browser authentication now exchanges the operator token for a revocable, opaque four-hour session. The cookie is Secure, HttpOnly, SameSite=Strict and host-only in production; the token is cleared from the form and is not stored in browser storage. Session records retain only a hash of the cookie value and an operator-key fingerprint.

Five session tests cover new API instance/browser-client restoration, expiry, forged cookies, credential rotation, server-side logout, and cross-site write rejection. The standard suite passes 36 tests, with the existing opt-in live Firestore test skipped. A browser sign-in/refresh/logout/refresh check passed. Live HTTPS checks on Cloud Run verified cookie attributes, restored authentication from a fresh client, and rejected reuse of the cookie after logout.
