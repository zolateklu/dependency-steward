# Implementation status

Started 4 November 2026 following the recruiter's approval of the upgraded direction.

## Provisioned

- Separate GCP project: `dependency-steward-zelalem`.
- The existing open billing account is linked; Run, Firestore, Scheduler, Artifact Registry, Cloud Build, and Secret Manager APIs are enabled.
- Firestore Native `(default)` database in `us-central1`, with the free tier enabled.
- Separate public owned fixture: https://github.com/zolateklu/dependency-steward.
- Existing selected gcloud project has not been changed.

## Local implementation

- React/TypeScript dashboard, token sign-in, queue, plan authorization, run timeline, test reports, before/after file view, cancellation, acknowledgement, and seven-day snooze.
- FastAPI API; revision-checked SQL and Firestore stores; durable plan/job state and repository lease; authenticated worker tick.
- Live GitHub, OSV, npm clients; bounded Gemini repair client; Slack deduplication.
- Immutable version/commit plans; Actions dispatch and reconciliation; baseline/candidate evidence; one repair attempt; publication gates and idempotent draft PR creation.
- Reviewed GitHub-hosted baseline/upgrade/repair workflow and stdlib execution helper.
- Public React fixture with four tests and an intentionally older Zod dependency. Zod 4 replaces the application's `errors` interface with `issues`, providing a genuine source compatibility exercise.

## Required before final delivery

- Configure a fine-grained runtime GitHub token scoped to the fixture; Gemini key on the intended free tier; Slack webhook.
- Verify the live compatible and breaking-upgrade paths, actual artifacts, bounded model repair, PR publication, cancellation, and no-change reconciliation.
- Deploy the app/private worker, mount secrets, configure IAM and Scheduler, and verify Firestore persistence and notifications.
- Finish UI accessibility/control details, including 1/7/30-day snooze selection, actual line-diff rendering, release-note evidence, and setup messaging.
- Record the assessment video and give the user final links and setup instructions.

Local tests and mocked provider runs do not establish that the live upgrade workflow or cloud deployment works. This file records the remaining delivery work explicitly.
