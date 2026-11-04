import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from .config import COMMANDS
from .domain import (
    digest,
    now,
    parse_lock,
    priority,
    publication_gate,
    source_path,
    text_hash,
    validate_repair,
)
from .providers import ProviderError
from .store import Conflict

TERMINAL = {"succeeded", "blocked", "cancelled", "stale"}


def event(job, message):
    job["updated_at"] = now()
    job.setdefault("events", []).append({"at": now(), "state": job["state"], "message": message})


def encoded(value):
    raw = json.dumps(value, separators=(",", ":")).encode()
    if len(raw) > 45000:
        raise ValueError("Workflow input exceeds its bounded size")
    return base64.b64encode(raw).decode()


class Steward:
    def __init__(self, settings, store, github, registry, osv, gemini):
        self.settings, self.store, self.github = settings, store, github
        self.registry, self.osv, self.gemini = registry, osv, gemini

    def mutate(self, key, fn):
        for _ in range(8):
            rev, value = self.store.get(key)
            result = fn(value)
            try:
                self.store.put(key, rev, result)
                return result
            except Conflict:
                continue
        raise Conflict("Concurrent work is still in progress; retry shortly")

    async def notify(self, key, text):
        if not self.settings.slack_webhook:
            return
        # Reserve first: an unknown HTTP result must never generate duplicate alerts on retry.
        rev, _ = self.store.get(f"notification-{key}")
        if rev:
            return
        try:
            rev = self.store.put(f"notification-{key}", 0, {"status": "delivery_unknown", "at": now()})
        except Conflict:
            return
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                response = await client.post(self.settings.slack_webhook, json={"text": text[:3500]})
                status = "delivered" if response.status_code == 200 else "failed"
            except httpx.HTTPError:
                status = "delivery_unknown"
        self.store.put(f"notification-{key}", rev, {"status": status, "at": now()})

    async def scan(self):
        branch, sha, _ = await self.github.head()
        lock_text, _ = await self.github.file("package-lock.json", sha)
        packages = parse_lock(json.loads(lock_text))
        if len(packages) > 1500:
            raise ValueError("Repository exceeds the 1,500-package prototype limit")
        _, previous = self.store.get("scan")
        previous_by_id = {c["id"]: c for c in (previous or {}).get("candidates", [])}
        complete, warnings = True, []
        try:
            matches = await self.osv.query(packages)
        except (ProviderError, httpx.HTTPError) as exc:
            matches, complete = {}, False
            warnings.append(str(exc))
        candidates, details, metadata = [], {}, {}
        for package in packages:
            ids = matches.get((package["name"], package["version"]), [])
            if not package["direct"] and not ids:
                continue
            target = None
            if package["direct"]:
                try:
                    if package["name"] not in metadata:
                        metadata[package["name"]] = await self.registry.metadata(package["name"])
                    meta = metadata[package["name"]]
                    target = meta["latest"] if meta["latest"] in meta["versions"] else None
                    if target == package["version"]:
                        target = None
                except (ProviderError, httpx.HTTPError):
                    warnings.append(f"Metadata unavailable for {package['name']}")
            if not ids and not target:
                continue
            advisories = []
            for advisory_id in ids:
                if len(details) >= 60 and advisory_id not in details:
                    complete = False
                    continue
                try:
                    if advisory_id not in details:
                        details[advisory_id] = await self.osv.detail(advisory_id)
                    advisories.append(details[advisory_id])
                except (ProviderError, httpx.HTTPError):
                    complete = False
            key = digest({"name": package["name"], "path": package["path"]})[:20]
            prior = previous_by_id.get(key)
            novel = bool(set(ids) - set((prior or {}).get("advisory_ids", [])))
            score, parts, severity = priority(advisories, package["dev"], target, novel, complete)
            fingerprint = digest(
                {"ids": ids, "severity": severity, "target": target, "installed": package["version"]}
            )
            candidates.append(
                {
                    **package,
                    "id": key,
                    "target": target,
                    "advisory_ids": ids,
                    "advisory_urls": [f"https://osv.dev/vulnerability/{v}" for v in ids],
                    "score": score,
                    "score_parts": parts,
                    "severity": severity,
                    "fingerprint": fingerprint,
                    "complete": complete,
                    "actionable": bool(target and package["direct"]),
                }
            )
        prs = await self.github.api("GET", "pulls", params={"state": "open", "per_page": 100})
        dependabot = [p for p in prs if p.get("user", {}).get("login") == "dependabot[bot]"][:10]
        candidates.sort(key=lambda c: (-c["score"], -c["score_parts"]["severity"], c["name"], c["id"]))
        scan = {
            "at": now(),
            "base_sha": sha,
            "branch": branch,
            "complete": complete,
            "warnings": sorted(set(warnings)),
            "package_count": len(packages),
            "candidates": candidates,
            "dependabot": [
                {"title": p["title"], "url": p["html_url"], "body": (p.get("body") or "")[:20000]}
                for p in dependabot
            ],
        }
        self.mutate("scan", lambda _: scan)
        visible = self.visible_candidates(scan)
        for candidate in visible[:3]:
            prior = previous_by_id.get(candidate["id"])
            _, action = self.store.get(f"action-{candidate['id']}")
            if prior and prior["fingerprint"] == candidate["fingerprint"]:
                continue
            if action and action.get("acknowledged") == candidate["fingerprint"]:
                continue
            await self.notify(
                f"scan-{candidate['id']}-{candidate['fingerprint']}",
                f"Dependency Steward: {candidate['name']} {candidate['version']} → "
                f"{candidate['target'] or 'investigate'} · priority {candidate['score']}",
            )
        return self.dashboard()

    def visible_candidates(self, scan):
        visible = []
        for candidate in (scan or {}).get("candidates", []):
            _, action = self.store.get(f"action-{candidate['id']}")
            snoozed = (
                action
                and action.get("fingerprint") == candidate["fingerprint"]
                and action.get("until", "") > now()
            )
            if not snoozed:
                visible.append(candidate)
        return visible

    def dashboard(self):
        _, scan = self.store.get("scan")
        jobs = sorted(self.store.list("job-"), key=lambda j: j["created_at"], reverse=True)
        # Evidence remains behind authentication; avoid sending large source/log bodies in this summary.
        summaries = [
            {k: v for k, v in j.items() if k not in ("result", "plan", "repair", "dispatch_payload")}
            | {"package": j["plan"]["package"], "target": j["plan"]["target"]}
            for j in jobs[:30]
        ]
        return {
            "repo": self.settings.github_repo,
            "scan": scan,
            "visible_candidates": self.visible_candidates(scan),
            "jobs": summaries,
            "configured": bool(self.settings.github_token and self.settings.github_repo),
            "model_configured": bool(self.settings.gemini_api_key),
            "slack_configured": bool(self.settings.slack_webhook),
        }

    def action(self, candidate_id, days):
        _, scan = self.store.get("scan")
        candidate = next((c for c in (scan or {}).get("candidates", []) if c["id"] == candidate_id), None)
        if not candidate:
            raise ValueError("Candidate no longer exists; scan again")
        if days not in (0, 1, 7, 30):
            raise ValueError("Snooze must be 1, 7 or 30 days; zero acknowledges")
        self.mutate(
            f"action-{candidate_id}",
            lambda _: {
                "fingerprint": candidate["fingerprint"],
                "acknowledged": candidate["fingerprint"] if days == 0 else None,
                "until": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat() if days else "",
            },
        )
        return self.dashboard()

    async def plan(self, request):
        branch, sha, tree = await self.github.head()
        manifest, _ = await self.github.file("package.json", sha)
        lock, _ = await self.github.file("package-lock.json", sha)
        data = json.loads(manifest)
        packages = parse_lock(json.loads(lock))
        installed = next(
            (p["version"] for p in packages if p["direct"] and p["name"] == request.package), None
        )
        if not installed or installed == request.target:
            raise ValueError("Choose a changed direct dependency version")
        if not set(COMMANDS).issubset(data.get("scripts", {})):
            raise ValueError("Repository must define test:ci, typecheck, and build scripts")
        metadata = await self.registry.metadata(request.package)
        if request.target not in metadata["versions"]:
            raise ValueError("Target version is not published in the npm registry")
        if metadata["versions"][request.target].get("deprecated"):
            raise ValueError("Deprecated target versions are not executable")
        _, workflow_sha = await self.github.file(f".github/workflows/{self.settings.github_workflow}", sha)
        _, runner_sha = await self.github.file(".steward/execute.py", sha)
        files = {}
        for path in self.settings.source_paths:
            source_path(path)
            content, _ = await self.github.file(path, sha)
            if len(content.encode()) > 24000:
                raise ValueError("Reviewed source exceeds the prototype evidence limit")
            files[path] = content
        if not files or len(files) > 5:
            raise ValueError("Configure one to five reviewed source paths")
        section = "dependencies" if request.package in data.get("dependencies", {}) else "devDependencies"
        plan = {
            "repo": self.settings.github_repo,
            "branch": branch,
            "base_sha": sha,
            "base_tree": tree,
            "package": request.package,
            "installed": installed,
            "target": request.target,
            "dependency_section": section,
            "manifest": manifest,
            "lock": lock,
            "allowed_paths": list(files),
            "sources": files,
            "source_hashes": {p: text_hash(t) for p, t in files.items()},
            "commands": COMMANDS,
            "node": self.settings.node_version,
            "npm": self.settings.npm_version,
            "workflow_sha": workflow_sha,
            "runner_sha": runner_sha,
            "timeout_minutes": 10,
            "target_url": f"https://www.npmjs.com/package/{request.package}/v/{request.target}",
            "release_notes": await self.registry.release_context(metadata, request.target),
            "created_at": now(),
        }
        plan["hash"] = digest(plan)
        plan["id"] = uuid.uuid4().hex
        if len(json.dumps(plan).encode()) > 200000:
            raise ValueError("Plan exceeds the prototype's durable storage budget")
        self.store.put(f"plan-{plan['id']}", 0, plan)
        return plan

    async def start(self, request):
        _, plan = self.store.get(f"plan-{request.plan_id}")
        if not plan or plan["hash"] != request.plan_hash:
            raise ValueError("Plan is missing or its authorization hash changed")
        _, current, _ = await self.github.head()
        if current != plan["base_sha"]:
            raise ValueError("Default branch moved; create and authorize a new plan")
        job_id = digest({"plan": plan["id"], "hash": plan["hash"]})[:24]

        def reserve(repo):
            repo = repo or {}
            if repo.get("active") and repo["active"]["id"] != job_id:
                raise Conflict("A repository upgrade is already active")
            repo["active"] = {"id": job_id, "plan_id": plan["id"], "authorized_at": now()}
            return repo

        self.mutate("repository", reserve)
        rev, existing = self.store.get(f"job-{job_id}")
        if existing:
            return existing
        job = {
            "id": job_id,
            "state": "queued",
            "plan": plan,
            "created_at": now(),
            "updated_at": now(),
            "authorized_at": now(),
            "publish_draft": True,
            "attempt": 1,
            "events": [],
            "model_calls": 0,
        }
        event(job, "Plan authorized; waiting for the worker")
        self.store.put(f"job-{job_id}", rev, job)
        return job

    def cancel(self, job_id):
        def apply(job):
            if not job:
                raise ValueError("Unknown job")
            if job["state"] == "publishing":
                raise Conflict("Publication has begun; the in-flight API request cannot be retracted")
            if job["state"] not in TERMINAL:
                job["state"] = "cancelled"
                event(job, "Cancelled before publication; remote execution will be stopped on reconciliation")
            return job

        return self.mutate(f"job-{job_id}", apply)

    async def tick(self, force=False):
        _, repo = self.store.get("repository")
        if repo and repo.get("active"):
            active = repo["active"]
            _, job = self.store.get(f"job-{active['id']}")
            if not job:
                _, plan = self.store.get(f"plan-{active['plan_id']}")
                if not plan:
                    raise ValueError("Reserved upgrade has no plan")
                job = {
                    "id": active["id"],
                    "plan": plan,
                    "state": "queued",
                    "created_at": active["authorized_at"],
                    "authorized_at": active["authorized_at"],
                    "updated_at": now(),
                    "publish_draft": True,
                    "attempt": 1,
                    "model_calls": 0,
                    "events": [],
                }
                self.store.put(f"job-{job['id']}", 0, job)
            await self.reconcile(job["id"], force)
        _, scan = self.store.get("scan")
        eat = datetime.now(ZoneInfo("Africa/Addis_Ababa"))
        if eat.hour >= self.settings.daily_scan_hour_eat and (
            not scan or scan["at"][:10] < eat.date().isoformat()
        ):
            await self.scan()
        return self.dashboard()

    async def reconcile(self, job_id, force=False):
        rev, job = self.store.get(f"job-{job_id}")
        if not job:
            return
        if job.get("lease_until", "") > now():
            return
        if not force and job.get("next_tick", "") > now() and job["state"] not in TERMINAL:
            return
        job["lease_until"] = (datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat()
        job["lease_id"] = uuid.uuid4().hex
        job["next_tick"] = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        try:
            rev = self.store.put(f"job-{job_id}", rev, job)
        except Conflict:
            return
        try:
            if job["state"] == "cancelled" and job.get("run_id") and not job.get("remote_cancelled"):
                await self.github.api("POST", f"actions/runs/{job['run_id']}/cancel")
                job["remote_cancelled"] = True
            if job["state"] not in TERMINAL:
                await self.advance(job)
        except (ValueError, ProviderError, httpx.HTTPError) as exc:
            # Unknown dispatch/publication results are reconciled before any retry.
            if job["state"] in ("publishing",) or job.get("dispatch_intent"):
                event(job, f"External result uncertain; reconciliation required: {str(exc)[:300]}")
            else:
                job["state"] = "blocked"
                event(job, str(exc)[:500])
        except Conflict:
            return
        job["lease_until"] = ""
        try:
            rev, latest = self.store.get(f"job-{job_id}")
            if latest["state"] == "cancelled" and job["state"] != "cancelled":
                return
            if latest.get("lease_id") != job.get("lease_id"):
                return
            self.store.put(f"job-{job_id}", rev, job)
        except Conflict:
            # A user cancellation won the CAS; never overwrite it with a late worker result.
            return
        if job["state"] in TERMINAL:
            self.mutate(
                "repository",
                lambda r: (
                    {**(r or {}), "active": None}
                    if ((r or {}).get("active") or {}).get("id") == job_id
                    else r
                ),
            )
            await self.notify(
                f"job-{job_id}",
                f"Dependency Steward: {job['plan']['package']} → "
                f"{job['plan']['target']} · {job['state']}\n{job.get('pr_url') or job['events'][-1]['message']}",
            )

    async def advance(self, job):
        plan = job["plan"]
        if job["state"] == "publishing":
            _, sha, _ = await self.github.head()
            try:
                publication_gate(job, job["result"], sha)
            except ValueError:
                job["state"] = "stale" if sha != plan["base_sha"] else "blocked"
                raise
            job["pr_url"] = await self.github.publish(job, job["result"])
            job["state"] = "succeeded"
            event(job, "Draft PR published with tested evidence")
            return
        if job["state"] in ("queued", "diagnosing"):
            if job["state"] == "diagnosing":
                if job["model_calls"] >= 3:
                    raise ValueError("Model request budget exhausted")
                job["model_calls"] += 1
                # This count is saved before invoking the model by the next durable stage; a crash can
                # retry diagnosis, so the state is checkpointed explicitly below.
                self.checkpoint(job)
                result = job["result"]
                evidence = {
                    "plan": {k: plan[k] for k in ("package", "installed", "target", "allowed_paths")},
                    "sources": result["sources"],
                    "source_hashes": {p: text_hash(t) for p, t in result["sources"].items()},
                    "evidence_ids": ["candidate-diagnostics", "target-metadata"],
                    "candidate-diagnostics": result["candidate"],
                    "target-metadata": plan["release_notes"],
                }
                proposal = await self.gemini.repair(evidence)
                repair = validate_repair(
                    proposal, result["sources"], plan["allowed_paths"], set(evidence["evidence_ids"])
                )
                if not repair.edits:
                    raise ValueError("No supported source repair: " + repair.uncertainty)
                job["repair"] = repair.model_dump()
                job["attempt"] = 2
            job["dispatch_payload"] = self.payload(job)
            job["dispatch_intent"] = now()
            job["dispatch_count"] = 0
            job["state"] = "running_baseline_upgrade" if job["attempt"] == 1 else "running_repair"
            event(job, "Execution dispatch intent recorded")
            self.checkpoint(job)
        if job["state"] in ("running_baseline_upgrade", "running_repair"):
            title = f"steward:{job['id']}:{job['attempt']}"
            runs = await self.github.runs(self.settings.github_workflow)
            matched = [
                r for r in runs if r.get("display_title") == title and r.get("head_sha") == plan["base_sha"]
            ]
            if not matched:
                if job.get("dispatch_count", 0):
                    # Wait for GitHub's eventually consistent listing; never blindly dispatch twice.
                    elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(job["dispatch_intent"])
                    if elapsed.total_seconds() > 1800:
                        job["dispatch_intent"] = None
                        raise ValueError(
                            "Dispatch outcome remained unknown for 30 minutes; inspect GitHub before retrying"
                        )
                    return
                _, sha, _ = await self.github.head()
                if sha != plan["base_sha"]:
                    job["state"] = "stale"
                    job["dispatch_intent"] = None
                    event(job, "Base moved before dispatch; a new plan is required")
                    return
                job["dispatch_count"] = 1
                self.checkpoint(job)
                await self.github.dispatch(
                    self.settings.github_workflow, plan["branch"], job["dispatch_payload"]
                )
                event(job, "GitHub Actions dispatched; waiting for its correlated run")
                return
            if len(matched) != 1:
                job["dispatch_intent"] = None
                raise ValueError("Duplicate workflow runs require operator investigation")
            run = matched[0]
            job["run_id"], job["run_url"] = run["id"], run["html_url"]
            job["dispatch_intent"] = None
            if run["status"] != "completed":
                return
            artifact_name = f"steward-{job['id']}-{job['attempt']}"
            result = await self.github.artifact(run["id"], artifact_name)
            if len(json.dumps(result).encode()) > 650000:
                raise ValueError("Execution evidence exceeds the durable storage budget")
            if (
                result.get("job_id") != job["id"]
                or result.get("plan_hash") != plan["hash"]
                or result.get("base_sha") != plan["base_sha"]
                or result.get("attempt") != job["attempt"]
            ):
                raise ValueError("Artifact correlation mismatch")
            previous_result = job.get("result")
            job["result"] = result
            if not result.get("baseline", {}).get("passed"):
                raise ValueError("Baseline failed; upgrade was not evaluated")
            if job["attempt"] == 2:
                if result.get("input_hash") != digest(previous_result):
                    raise ValueError("Repair did not use the exact tested candidate")
            if not result.get("candidate", {}).get("passed"):
                if job["attempt"] == 2:
                    raise ValueError("The single source repair did not pass validation")
                job["candidate_run_id"] = run["id"]
                job["state"] = "diagnosing"
                event(job, "Upgrade introduced a failure; bounded source diagnosis is next")
                return
            if run.get("conclusion") != "success":
                raise ValueError("Execution workflow did not finish successfully")
            before = await self.osv.query(parse_lock(json.loads(plan["lock"])))
            after = await self.osv.query(parse_lock(json.loads(result["changes"]["package-lock.json"])))
            old_ids = {v for values in before.values() for v in values}
            new_ids = {v for values in after.values() for v in values}
            result.update(
                osv_complete=True,
                removed_advisories=sorted(old_ids - new_ids),
                remaining_advisories=sorted(new_ids & old_ids),
                new_advisories=sorted(new_ids - old_ids),
            )
            job["state"] = "publishing"
            _, sha, _ = await self.github.head()
            try:
                publication_gate(job, result, sha)
            except ValueError:
                job["state"] = "blocked"
                raise
            event(job, "All checks passed; publication boundary entered")
            # Persist the irreversible publication boundary before a later tick performs API writes.

    def checkpoint(self, job):
        rev, current = self.store.get(f"job-{job['id']}")
        if current["state"] == "cancelled":
            raise Conflict("User cancelled the job")
        self.store.put(f"job-{job['id']}", rev, job)

    def payload(self, job):
        plan = {
            k: v for k, v in job["plan"].items() if k not in ("manifest", "lock", "sources", "release_notes")
        }
        payload = {
            "job_id": job["id"],
            "attempt": str(job["attempt"]),
            "plan_b64": encoded(plan),
            "repair_b64": "",
        }
        if job["attempt"] == 2:
            payload["repair_b64"] = encoded(
                {
                    "repair": job["repair"],
                    "run_id": job["candidate_run_id"],
                    "artifact": f"steward-{job['id']}-1",
                    "input_hash": digest(job["result"]),
                }
            )
        return payload
