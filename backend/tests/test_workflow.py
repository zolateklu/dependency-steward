from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from steward.app import create_app
from steward.domain import StartRequest
from steward.store import Conflict


async def authorized(service, plan):
    service.store.put(f"plan-{plan['id']}", 0, plan)
    return await service.start(StartRequest(plan_id=plan["id"], plan_hash=plan["hash"], publish_draft=True))


async def test_duplicate_start_and_tick_do_not_dispatch_twice(service, plan):
    job = await authorized(service, plan)
    same = await service.start(StartRequest(plan_id=plan["id"], plan_hash=plan["hash"], publish_draft=True))
    assert same["id"] == job["id"]
    await service.reconcile(job["id"], force=True)
    await service.reconcile(job["id"], force=True)
    assert len(service.github.dispatched) == 1
    assert service.store.get(f"job-{job['id']}")[1]["state"] == "running_baseline_upgrade"


async def test_end_to_end_state_recovery_and_single_publication(service, plan, result):
    job = await authorized(service, plan)
    await service.reconcile(job["id"], force=True)
    result.update(job_id=job["id"])
    service.github.result = result
    service.github.items = [
        {
            "id": 123,
            "display_title": f"steward:{job['id']}:1",
            "head_sha": plan["base_sha"],
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://github.com/owner/demo/actions/runs/123",
        }
    ]
    await service.reconcile(job["id"], force=True)
    assert service.store.get(f"job-{job['id']}")[1]["state"] == "publishing"
    # New service object represents a backend restart against the same durable state.
    recovered = type(service)(
        service.settings, service.store, service.github, service.registry, service.osv, service.gemini
    )
    await recovered.reconcile(job["id"], force=True)
    await recovered.reconcile(job["id"], force=True)
    saved = service.store.get(f"job-{job['id']}")[1]
    assert saved["state"] == "succeeded"
    assert saved["pr_url"].endswith("/pull/1")
    assert len(service.github.publications) == 1
    assert service.store.get("repository")[1]["active"] is None


async def test_cancel_prevents_publication(service, plan, result):
    job = await authorized(service, plan)
    cancelled = service.cancel(job["id"])
    await service.reconcile(job["id"], force=True)
    assert cancelled["state"] == "cancelled"
    assert not service.github.publications
    assert not service.github.dispatched


async def test_cancel_boundary_is_explicit(service, plan, result):
    job = await authorized(service, plan)
    rev, job = service.store.get(f"job-{job['id']}")
    job["state"] = "publishing"
    service.store.put(f"job-{job['id']}", rev, job)
    with pytest.raises(Conflict, match="Publication has begun"):
        service.cancel(job["id"])


async def test_failing_baseline_is_blocked_without_pr(service, plan, result):
    job = await authorized(service, plan)
    await service.reconcile(job["id"], force=True)
    result.update(job_id=job["id"])
    result["baseline"]["passed"] = False
    service.github.result = result
    service.github.items = [
        {
            "id": 123,
            "display_title": f"steward:{job['id']}:1",
            "head_sha": plan["base_sha"],
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://github.com/owner/demo/actions/runs/123",
        }
    ]
    await service.reconcile(job["id"], force=True)
    assert service.store.get(f"job-{job['id']}")[1]["state"] == "blocked"
    assert not service.github.publications


def test_snooze_and_changed_evidence(service):
    candidate = {"id": "candidate", "fingerprint": "original"}
    service.store.put("scan", 0, {"candidates": [candidate]})
    service.action("candidate", 7)
    assert service.visible_candidates({"candidates": [candidate]}) == []
    changed = deepcopy(candidate)
    changed["fingerprint"] = "new-advisory"
    assert service.visible_candidates({"candidates": [changed]}) == [changed]


def test_api_requires_auth_for_evidence_and_writes(service):
    with TestClient(create_app(service.settings, service)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/dashboard").status_code == 401
        assert client.post("/api/scan").status_code == 401
        assert client.post("/internal/tick").status_code == 401
        headers = {"Authorization": f"Bearer {service.settings.operator_token}"}
        response = client.get("/api/dashboard", headers=headers)
        assert response.status_code == 200
        assert "not-a-real-token" not in response.text
