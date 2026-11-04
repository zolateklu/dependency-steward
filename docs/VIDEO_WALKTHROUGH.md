# Assessment walkthrough

Record the deployed app and this repository with your own narration. Do not display `.env`, Secret Manager values, API keys, or the operator token.

1. **Problem and role (30 seconds).** Explain the dependency-maintenance engineer role. Dependabot already opens updates; the additional value here is reproducing a baseline, attempting a real upgrade, investigating a new failure, applying a bounded source repair, and handing over validated code.
2. **Live queue and plan (45 seconds).** Show the real GitHub/npm/OSV scan, Zod advisory, exact installed/target versions, score breakdown, and source references. Open a plan and show the base SHA, reviewed source paths, toolchain, required checks, and authorization checkbox.
3. **Compatible upgrade (30 seconds).** Open the Zod 3.25.76 result. Show the four tests, typecheck and build results, GitHub execution link, and draft PR. No model repair was necessary.
4. **Breaking upgrade and repair (60 seconds).** Open the Zod 4.6.7 result. Open the initial Actions run linked in the verification notes to show the failed candidate, then return to the dashboard for the diagnostic that `ZodError.errors` changed, the constrained edit to `src/schema.ts`, and the repair run. Show the final tests and draft PR when successful; show the blocker honestly if unsuccessful. Tests must be unchanged.
5. **Agent behavior and controls (30 seconds).** Show the Scheduler job, persisted Firestore job events, Slack completion notification, snooze, and cancellation. Explain that the browser can close while the worker continues; a human still merges.
6. **Frontend implementation (30 seconds).** Walk through `frontend/src/main.tsx`: authenticated API calls, plan authorization, progress polling, evidence panels, and diff view.
7. **Backend implementation (60 seconds).** Walk through `backend/steward/service.py` (state machine and recovery), `domain.py` (repair/publication policy), `providers.py` (real APIs), `store.py` (revision checks), and `.steward/execute.py` plus the Actions workflow (clean baseline/candidate VMs and exact repair artifact).
8. **Limits and evidence (15 seconds).** State the prototype scope: one owned public repository, one direct dependency per job, one repair, draft PRs only, and configured test coverage rather than universal safety. Link the live verification document and tests.

Use `docs/VERIFICATION.md` for exact PR/run links and observed results. A script is not a completed recording; record and review the final video before submission.
