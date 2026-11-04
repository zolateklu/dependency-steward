import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from steward.config import COMMANDS, Settings
from steward.domain import text_hash
from steward.service import Steward
from steward.store import SQLStore


@pytest.fixture
def plan():
    manifest = {
        "name": "fixture",
        "dependencies": {"zod": "3.24.2"},
        "scripts": {c: "reviewed" for c in COMMANDS},
    }
    lock = {
        "lockfileVersion": 3,
        "packages": {"": {"dependencies": {"zod": "3.24.2"}}, "node_modules/zod": {"version": "3.24.2"}},
    }
    return {
        "id": "plan-id",
        "hash": "plan-hash",
        "package": "zod",
        "target": "4.6.7",
        "installed": "3.24.2",
        "base_sha": "a" * 40,
        "base_tree": "b" * 40,
        "branch": "main",
        "repo": "owner/demo",
        "dependency_section": "dependencies",
        "allowed_paths": ["src/schema.ts"],
        "commands": COMMANDS,
        "manifest": json.dumps(manifest),
        "lock": json.dumps(lock),
        "sources": {"src/schema.ts": "old source"},
        "release_notes": "ZodError uses issues",
        "node": "24.6.0",
        "npm": "11.8.0",
    }


@pytest.fixture
def result(plan):
    manifest = json.loads(plan["manifest"])
    manifest["dependencies"]["zod"] = plan["target"]
    lock = json.loads(plan["lock"])
    lock["packages"][""]["dependencies"]["zod"] = plan["target"]
    lock["packages"]["node_modules/zod"]["version"] = plan["target"]
    report = {
        "passed": True,
        "installed": True,
        "test_count": 4,
        "commands": {c: {"exit_code": 0, "duration": 1.0, "log": "ok"} for c in COMMANDS},
    }
    changes = {"package.json": json.dumps(manifest), "package-lock.json": json.dumps(lock)}
    return {
        "baseline": deepcopy(report),
        "candidate": deepcopy(report),
        "changes": changes,
        "hashes": {p: text_hash(t) for p, t in changes.items()},
        "sources": {"src/schema.ts": "old source"},
        "osv_complete": True,
        "new_advisories": [],
        "attempt": 1,
        "plan_hash": plan["hash"],
        "base_sha": plan["base_sha"],
    }


class FakeGitHub:
    def __init__(self, plan):
        self.plan, self.items, self.dispatched, self.publications = plan, [], [], []
        self.requests = 0
        self.result = None

    async def head(self):
        return "main", self.plan["base_sha"], self.plan["base_tree"]

    async def runs(self, workflow):
        return self.items

    async def dispatch(self, workflow, branch, inputs):
        self.dispatched.append(inputs)

    async def artifact(self, run_id, name):
        return deepcopy(self.result)

    async def publish(self, job, result):
        self.publications.append(job["id"])
        return "https://github.com/owner/demo/pull/1"

    async def api(self, method, path, **kwargs):
        return None


@pytest.fixture
def service(tmp_path, plan):
    store = SQLStore(f"sqlite:///{tmp_path / 'state.db'}")
    settings = Settings(
        operator_token="o" * 32,
        worker_token="w" * 32,
        github_repo="owner/demo",
        github_token="not-a-real-token",
    )
    github = FakeGitHub(plan)

    async def query(packages):
        return {}

    return Steward(
        settings, store, github, SimpleNamespace(), SimpleNamespace(query=query), SimpleNamespace()
    )
